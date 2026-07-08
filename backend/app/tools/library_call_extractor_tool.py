from __future__ import annotations

import ast
from dataclasses import dataclass

from backend.app.schemas.library_call import LibraryCall
from backend.app.tools.library_function_resolver_tool import resolve_library_function


BUILTIN_CALLS = {"len", "range", "print", "str", "int", "float", "list", "dict", "set", "tuple", "enumerate", "zip", "sum", "min", "max"}
EXTERNAL_ALIAS_ROOTS = {
    "torch",
    "numpy",
    "cv2",
    "PIL",
    "einops",
    "os",
    "pathlib",
    "json",
    "math",
    "random",
    "typing",
    "dataclasses",
}
AMBIGUOUS_EXTERNAL_HINTS = ("api", "client", "module", "ops", "transform", "reader", "writer")


@dataclass
class LibraryCallExtractionResult:
    library_calls: list[dict]
    low_confidence_library_calls: list[dict]


def extract_library_calls(
    parsed_files: list[dict],
    functions: list[dict],
    classes: list[dict],
) -> LibraryCallExtractionResult:
    parsed_by_path = {item.get("file_path"): item for item in parsed_files}
    project_symbols = _project_symbols(functions, classes)
    library_calls: list[dict] = []
    low_confidence: list[dict] = []

    for function in functions:
        parsed_file = parsed_by_path.get(function.get("file_path"), {})
        aliases = parsed_file.get("aliases", {})
        calls = _extract_function_calls(function, aliases, project_symbols)
        for call in calls:
            call_dict = call.model_dump()
            library_calls.append(call_dict)
            if call.confidence == "low":
                low_confidence.append(call_dict)

    return LibraryCallExtractionResult(
        library_calls=library_calls,
        low_confidence_library_calls=low_confidence,
    )


def _extract_function_calls(function: dict, aliases: dict[str, str], project_symbols: set[str]) -> list[LibraryCall]:
    source_code = function.get("source_code")
    if not source_code:
        return []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    calls: list[LibraryCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        display_name = _call_display_name(node.func)
        if not display_name or _should_skip_call(display_name, project_symbols, aliases):
            continue
        resolved = resolve_library_function(display_name, aliases)
        if resolved.category == "unknown" and resolved.confidence == "low" and not _looks_like_possible_external_call(display_name):
            continue
        qualified_name = _qualified_function_name(function)
        line_no = None
        if function.get("start_line") is not None and getattr(node, "lineno", None) is not None:
            line_no = function["start_line"] + node.lineno - 1
        calls.append(
            LibraryCall(
                file_path=function["file_path"],
                class_name=function.get("class_name"),
                function_name=function["function_name"],
                qualified_function_name=qualified_name,
                canonical_name=resolved.canonical_name,
                display_name=resolved.display_name,
                package_name=resolved.package_name,
                category=resolved.category,
                call_text=ast.get_source_segment(source_code, node) or ast.unparse(node),
                line_no=line_no,
                confidence=resolved.confidence,
                is_recorded_in_global_library=False,
            )
        )
    return calls


def _call_display_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    return None


def _should_skip_call(display_name: str, project_symbols: set[str], aliases: dict[str, str]) -> bool:
    root = display_name.split(".", 1)[0]
    if root in {"self", "cls", "super"}:
        return True
    if display_name.startswith(("self.", "cls.", "super")):
        return True
    if root in BUILTIN_CALLS:
        return True
    if root in aliases:
        return not _alias_points_to_external_package(aliases[root])
    return root in project_symbols or display_name in project_symbols


def _looks_like_possible_external_call(display_name: str) -> bool:
    root = display_name.split(".", 1)[0]
    if "." in display_name:
        return True
    return any(hint in root.lower() for hint in AMBIGUOUS_EXTERNAL_HINTS)


def _project_symbols(functions: list[dict], classes: list[dict]) -> set[str]:
    symbols: set[str] = set()
    for class_info in classes:
        class_name = class_info.get("class_name")
        if class_name:
            symbols.add(class_name)
    for function in functions:
        function_name = function.get("function_name")
        class_name = function.get("class_name")
        if function_name:
            symbols.add(function_name)
        if function_name and class_name:
            symbols.add(f"{class_name}.{function_name}")
    return symbols


def _alias_points_to_external_package(alias_target: str) -> bool:
    root = alias_target.lstrip(".").split(".", 1)[0]
    return root in EXTERNAL_ALIAS_ROOTS


def _qualified_function_name(function: dict) -> str:
    class_name = function.get("class_name")
    function_name = function.get("function_name", "")
    return f"{class_name}.{function_name}" if class_name else function_name
