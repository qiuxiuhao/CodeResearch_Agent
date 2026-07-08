from __future__ import annotations

import ast

from backend.app.schemas.function_analysis import FunctionAnalysis
from backend.app.schemas.library_call import LibraryCall


def analyze_functions(
    functions: list[dict],
    file_analysis: list[dict],
    library_calls: list[dict],
) -> list[FunctionAnalysis]:
    file_analysis_by_path = {item.get("file_path"): item for item in file_analysis}
    library_calls_by_function = _group_library_calls(library_calls)

    analyses: list[FunctionAnalysis] = []
    for function in functions:
        qualified_name = _qualified_name(function)
        calls = [
            LibraryCall(**item)
            for item in library_calls_by_function.get((function.get("file_path", ""), qualified_name), [])
        ]
        file_info = file_analysis_by_path.get(function.get("file_path", ""), {})
        analyses.append(_analyze_single_function(function, file_info, calls))
    return analyses


def _analyze_single_function(function: dict, file_info: dict, library_calls: list[LibraryCall]) -> FunctionAnalysis:
    qualified_name = _qualified_name(function)
    function_name = function.get("function_name", "")
    file_type = file_info.get("file_type", "unknown")
    raw_calls = function.get("raw_call_expressions", [])
    evidence = [
        f"函数位于 {function.get('file_path', '')}",
        f"函数行号 {function.get('start_line')}-{function.get('end_line')}",
    ]
    if file_type != "unknown":
        evidence.append(f"所在文件类型为 {file_type}")

    is_core, core_reason = _core_function_reason(function_name, file_type, library_calls, raw_calls)
    if is_core and core_reason:
        evidence.append(core_reason)

    return FunctionAnalysis(
        file_path=function["file_path"],
        class_name=function.get("class_name"),
        function_name=function_name,
        qualified_name=qualified_name,
        start_line=function.get("start_line"),
        end_line=function.get("end_line"),
        purpose=_purpose_for(function_name, file_type),
        inputs=function.get("args", []),
        outputs=_outputs_for(function.get("source_code")),
        implementation_logic=_implementation_logic(function, raw_calls),
        computation_logic=_computation_logic(raw_calls, library_calls),
        model_position=_model_position(function_name, file_type),
        called_internal_functions=_internal_calls_for_function(function, raw_calls, library_calls),
        library_calls=library_calls,
        is_core_function=is_core,
        core_reason=core_reason,
        beginner_explanation=_beginner_explanation(function_name, file_type),
        evidence=evidence,
        confidence="high" if is_core else "medium",
    )


def _purpose_for(function_name: str, file_type: str) -> str:
    if function_name == "__init__":
        return "初始化类实例或模块成员。"
    if function_name == "forward":
        return "定义模型前向计算入口。"
    if function_name == "__len__":
        return "返回数据集或容器长度。"
    if function_name == "__getitem__":
        return "按索引读取一个数据项。"
    if function_name == "main":
        return "作为项目入口函数，串联主要运行流程。"
    if function_name.startswith("train") or function_name == "fit":
        return "组织训练相关流程。"
    if file_type == "inference" or any(word in function_name for word in ("predict", "infer", "evaluate")):
        return "组织推理、预测或评估相关流程。"
    return "实现当前文件中的辅助逻辑。"


def _outputs_for(source_code: str | None) -> list[str]:
    if not source_code:
        return []
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []
    if any(isinstance(node, ast.Return) and node.value is not None for node in ast.walk(tree)):
        return ["返回 return 表达式或计算结果。"]
    return ["无显式返回值。"]


def _implementation_logic(function: dict, raw_calls: list[str]) -> list[str]:
    logic = ["接收函数参数并执行函数体逻辑。"]
    if raw_calls:
        logic.append(f"调用 {len(raw_calls)} 个函数或方法。")
    if _has_return(function.get("source_code")):
        logic.append("通过 return 返回结果。")
    else:
        logic.append("没有显式返回具体结果。")
    return logic


def _computation_logic(raw_calls: list[str], library_calls: list[LibraryCall]) -> list[str]:
    logic: list[str] = []
    seen: set[str] = set()
    for call in library_calls:
        text = f"调用外部库函数 {call.canonical_name}。"
        if text not in seen:
            logic.append(text)
            seen.add(text)
    for call in raw_calls:
        lowered = call.lower()
        if any(keyword in lowered for keyword in ("mean", "relu", "linear", "randn", "cat", "matmul")):
            text = f"包含计算相关调用 {call}。"
            if text not in seen:
                logic.append(text)
                seen.add(text)
    return logic or ["未发现明显的数值计算调用。"]


def _model_position(function_name: str, file_type: str) -> str | None:
    if file_type == "model" and function_name == "forward":
        return "模型前向计算入口。"
    if file_type == "model" and function_name == "__init__":
        return "模型初始化逻辑。"
    return None


def _internal_calls_for_function(function: dict, raw_calls: list[str], library_calls: list[LibraryCall]) -> list[str]:
    library_names = {call.display_name for call in library_calls}
    parameter_names = set(function.get("args", []))
    result: list[str] = []
    for call in raw_calls:
        if call in library_names:
            continue
        if call == "super" or call.startswith("super"):
            continue
        if "." not in call and call not in parameter_names:
            result.append(call)
            continue
        if call.startswith(("self.", "cls.")):
            result.append(call)
    return result


def _core_function_reason(
    function_name: str,
    file_type: str,
    library_calls: list[LibraryCall],
    raw_calls: list[str],
) -> tuple[bool, str | None]:
    if file_type == "model" and function_name == "forward":
        return True, "模型文件中的 forward 方法，是模型前向计算入口。"
    if file_type == "training" and (function_name.startswith("train") or function_name == "fit"):
        return True, f"训练文件中的 {function_name} 函数，属于训练流程核心函数。"
    if file_type == "entry" and function_name == "main":
        return True, "入口文件中的 main 函数，负责串联主要运行流程。"
    if file_type == "dataset" and function_name == "__getitem__":
        return True, "数据集文件中的 __getitem__ 方法，负责按索引读取数据。"
    if any(keyword in function_name for keyword in ("loss", "inference", "predict", "evaluate")):
        return True, "函数名命中核心流程关键词。"
    if len(raw_calls) >= 3 and any(call.category in {"pytorch", "numpy"} for call in library_calls):
        return True, "函数调用较多且包含 PyTorch 或 NumPy 库函数。"
    return False, None


def _beginner_explanation(function_name: str, file_type: str) -> str:
    return f"`{function_name}` 是 {file_type} 文件中的一个函数，用来完成该文件职责中的一部分。"


def _has_return(source_code: str | None) -> bool:
    if not source_code:
        return False
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.Return) for node in ast.walk(tree))


def _qualified_name(function: dict) -> str:
    class_name = function.get("class_name")
    function_name = function.get("function_name", "")
    return f"{class_name}.{function_name}" if class_name else function_name


def _group_library_calls(library_calls: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for call in library_calls:
        key = (call.get("file_path", ""), call.get("qualified_function_name", ""))
        grouped.setdefault(key, []).append(call)
    return grouped
