from __future__ import annotations

import ast
from pathlib import Path

from backend.app.schemas.code import ClassInfo, FunctionInfo, ImportInfo, ParsedFile
from backend.app.utils.file_utils import read_text_safely
from backend.app.utils.path_utils import normalize_relative_path, resolve_path


def parse_python_file(file_path: str | Path, repo_path: str | Path | None = None) -> ParsedFile:
    source_path = resolve_path(file_path)
    relative_path = _relative_file_path(source_path, repo_path)
    errors: list[dict] = []

    try:
        source = read_text_safely(source_path)
        tree = ast.parse(source, filename=str(source_path))
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return ParsedFile(
            file_path=relative_path,
            errors=[_error("ast_parse_tool", relative_path, type(exc).__name__, str(exc))],
        )

    parser = _AstCollector(relative_path, source)
    parser.visit(tree)
    errors.extend(parser.errors)

    return ParsedFile(
        file_path=relative_path,
        imports=parser.imports,
        aliases=parser.aliases,
        classes=parser.classes,
        functions=parser.functions,
        errors=errors,
    )


def parse_python_files(repo_path: str | Path, python_files: list[str]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    root = resolve_path(repo_path)
    parsed_files: list[dict] = []
    functions: list[dict] = []
    classes: list[dict] = []
    errors: list[dict] = []

    for relative_file in python_files:
        parsed = parse_python_file(root / relative_file, root)
        parsed_dict = parsed.model_dump()
        parsed_files.append(parsed_dict)
        functions.extend(function.model_dump() for function in parsed.functions)
        classes.extend(class_info.model_dump() for class_info in parsed.classes)
        errors.extend(parsed.errors)

    return parsed_files, functions, classes, errors


class _AstCollector(ast.NodeVisitor):
    def __init__(self, file_path: str, source: str) -> None:
        self.file_path = file_path
        self.source = source
        self.imports: list[ImportInfo] = []
        self.aliases: dict[str, str] = {}
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.errors: list[dict] = []
        self._class_stack: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            display_name = alias.asname or alias.name.split(".")[0]
            self.aliases[display_name] = alias.name
            self.imports.append(
                ImportInfo(
                    module=alias.name,
                    alias=alias.asname,
                    import_type="import",
                    line_no=node.lineno,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                imported_name = "*"
            else:
                imported_name = alias.asname or alias.name
                self.aliases[imported_name] = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(
                ImportInfo(
                    module=module,
                    name=alias.name,
                    alias=alias.asname,
                    import_type="from_import",
                    line_no=node.lineno,
                )
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.classes.append(
            ClassInfo(
                file_path=self.file_path,
                class_name=node.name,
                base_classes=[_node_to_text(base) for base in node.bases],
                start_line=getattr(node, "lineno", None),
                end_line=getattr(node, "end_lineno", None),
                methods=methods,
            )
        )
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_function(node)
        self.generic_visit(node)

    def _add_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(
            FunctionInfo(
                file_path=self.file_path,
                function_name=node.name,
                class_name=self._class_stack[-1] if self._class_stack else None,
                args=[arg.arg for arg in node.args.args],
                start_line=getattr(node, "lineno", None),
                end_line=getattr(node, "end_lineno", None),
                source_code=ast.get_source_segment(self.source, node),
                raw_call_expressions=[
                    _node_to_text(call.func)
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                ],
            )
        )


def _relative_file_path(path: Path, repo_path: str | Path | None) -> str:
    if repo_path is None:
        return normalize_relative_path(path)
    root = resolve_path(repo_path)
    return normalize_relative_path(path.relative_to(root))


def _node_to_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _error(tool: str, path: str, error_type: str, message: str) -> dict:
    return {
        "tool": tool,
        "path": path,
        "error_type": error_type,
        "message": message,
    }

