from __future__ import annotations

import ast
from dataclasses import dataclass

from backend.app.schemas.model_analysis import (
    ComponentRole,
    ForwardStep,
    ModelAnalysis,
    ModelComponentCandidate,
    ModelLayer,
)


MODEL_NAME_KEYWORDS = ("model", "net", "network", "module", "classifier", "encoderdecoder")
CONTROL_FLOW_NODES = (ast.If, ast.For, ast.While)


@dataclass(frozen=True)
class ModuleDetection:
    is_module: bool
    confidence: str
    evidence: list[str]
    warnings: list[str]


def detect_models(
    parsed_files: list[dict],
    classes: list[dict],
    functions: list[dict],
    file_analysis: list[dict],
    library_calls: list[dict],
    function_analysis: list[dict],
) -> list[ModelAnalysis]:
    parsed_by_path = {item.get("file_path"): item for item in parsed_files}
    file_analysis_by_path = {item.get("file_path"): item for item in file_analysis}
    function_analysis_by_key = {
        (item.get("file_path", ""), item.get("qualified_name", "")): item
        for item in function_analysis
    }

    models: list[ModelAnalysis] = []
    for class_info in classes:
        parsed_file = parsed_by_path.get(class_info.get("file_path"), {})
        class_functions = _find_class_functions(class_info, functions)
        detection = _is_nn_module_class(class_info, parsed_file, class_functions)
        if not detection.is_module:
            continue

        aliases = parsed_file.get("aliases", {})
        init_function = class_functions.get("__init__")
        forward_function = class_functions.get("forward")
        layers = _extract_init_layers(init_function, aliases) if init_function else []
        forward_steps, model_inputs, model_outputs, forward_warnings = _extract_forward_steps(
            forward_function,
            layers,
            aliases,
        )
        component_candidates = _detect_component_candidates(class_info, layers, forward_steps, library_calls)
        model_key = (class_info.get("file_path", ""), class_info.get("class_name", ""))
        function_context = [
            item
            for key, item in function_analysis_by_key.items()
            if key[0] == model_key[0] and key[1].startswith(f"{model_key[1]}.")
        ]
        evidence = [
            *detection.evidence,
            *([f"识别到 __init__ 函数并提取 {len(layers)} 个网络层。"] if init_function else []),
            *([f"识别到 forward 函数并提取 {len(forward_steps)} 个基础数据流步骤。"] if forward_function else []),
        ]
        if function_context:
            evidence.append(f"关联到 {len(function_context)} 个函数级分析结果。")

        models.append(
            ModelAnalysis(
                file_path=class_info.get("file_path", ""),
                class_name=class_info.get("class_name", ""),
                qualified_name=class_info.get("class_name", ""),
                base_classes=class_info.get("base_classes", []),
                start_line=class_info.get("start_line"),
                end_line=class_info.get("end_line"),
                is_nn_module=True,
                init_function="__init__" if init_function else None,
                forward_function="forward" if forward_function else None,
                model_inputs=model_inputs,
                model_outputs=model_outputs,
                layers=layers,
                forward_steps=forward_steps,
                component_candidates=component_candidates,
                summary=_model_summary(class_info, layers, forward_steps),
                evidence=evidence,
                warnings=[*detection.warnings, *forward_warnings],
                confidence=detection.confidence,  # type: ignore[arg-type]
            )
        )

    _mark_main_model_candidates(models, file_analysis_by_path)
    return models


def _is_nn_module_class(class_info: dict, parsed_file: dict, class_functions: dict[str, dict]) -> ModuleDetection:
    aliases = parsed_file.get("aliases", {})
    imports = parsed_file.get("imports", [])
    bases = class_info.get("base_classes", [])
    evidence: list[str] = []
    warnings: list[str] = []

    for base in bases:
        canonical_base = _canonical_name(base, aliases)
        if base in {"nn.Module", "torch.nn.Module"} or canonical_base == "torch.nn.Module":
            evidence.append(f"基类 {base} 可还原为 torch.nn.Module。")
            return ModuleDetection(True, "high", evidence, warnings)

    has_torch_import = any(
        (item.get("module") or "").startswith("torch")
        for item in imports
    ) or any(str(target).startswith("torch") for target in aliases.values())
    if any(base.endswith(".Module") for base in bases) and has_torch_import:
        evidence.append("基类名称以 .Module 结尾，且文件导入了 torch 相关模块。")
        return ModuleDetection(True, "medium", evidence, warnings)

    class_name = class_info.get("class_name", "")
    file_path = class_info.get("file_path", "")
    lower_context = f"{class_name} {file_path}".lower()
    has_model_name = any(keyword in lower_context for keyword in MODEL_NAME_KEYWORDS)
    if has_model_name and "__init__" in class_functions and "forward" in class_functions:
        evidence.append("类名或路径命中模型关键词，且同时包含 __init__ 和 forward。")
        warnings.append("未确认继承 torch.nn.Module，按中置信模型候选处理。")
        return ModuleDetection(True, "medium", evidence, warnings)

    if has_model_name:
        warnings.append("类名或路径像模型类，但缺少继承或 forward 证据，v0.5 不纳入模型分析。")
    return ModuleDetection(False, "low", evidence, warnings)


def _find_class_functions(class_info: dict, functions: list[dict]) -> dict[str, dict]:
    file_path = class_info.get("file_path")
    class_name = class_info.get("class_name")
    result: dict[str, dict] = {}
    for function in functions:
        if function.get("file_path") == file_path and function.get("class_name") == class_name:
            result[function.get("function_name", "")] = function
    return result


def _extract_init_layers(init_function: dict, aliases: dict[str, str]) -> list[ModelLayer]:
    tree = _parse_function_source(init_function)
    if tree is None:
        return []
    source = init_function.get("source_code") or ""
    layers: list[ModelLayer] = []
    for node in ast.walk(tree):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if target is None or value is None or not isinstance(value, ast.Call):
            continue
        layer_name = _self_attribute_name(target)
        if not layer_name:
            continue
        layer_type = _canonical_name(_node_to_text(value.func), aliases)
        call_text = ast.get_source_segment(source, value) or _node_to_text(value)
        role = _role_for_name_and_type(layer_name, layer_type)
        line_no = _absolute_line_no(init_function, getattr(node, "lineno", None))
        evidence = [f"在 __init__ 中发现 self.{layer_name} = {call_text}。"]
        if role != "unknown":
            evidence.append(f"名称或类型命中 {role} 角色关键词。")
        elif _is_linear_mapping_hint(layer_name, layer_type):
            evidence.append("可能是线性映射层，具体角色需结合上下文确认。")
        layers.append(
            ModelLayer(
                name=layer_name,
                assigned_name=f"self.{layer_name}",
                layer_type=layer_type,
                call_text=call_text,
                line_no=line_no,
                role=role,
                source="init_assignment",
                evidence=evidence,
            )
        )
    return layers


def _extract_forward_steps(
    forward_function: dict | None,
    layers: list[ModelLayer],
    aliases: dict[str, str],
) -> tuple[list[ForwardStep], list[str], list[str], list[str]]:
    if not forward_function:
        return [], [], [], ["未找到 forward 函数。"]
    tree = _parse_function_source(forward_function)
    if tree is None:
        return [], [], [], ["forward 函数源码无法解析。"]

    function_def = next((node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if function_def is None:
        return [], [], [], ["forward 函数 AST 中未找到函数定义。"]

    layer_names = {layer.name for layer in layers}
    source = forward_function.get("source_code") or ""
    inputs = [arg.arg for arg in function_def.args.args if arg.arg != "self"]
    outputs: list[str] = []
    warnings: list[str] = []
    steps: list[ForwardStep] = []

    for stmt in function_def.body:
        if isinstance(stmt, CONTROL_FLOW_NODES):
            warnings.append("forward 中存在分支或循环，v0.5 仅做基础顺序识别。")
            for nested in _interesting_nested_statements(stmt):
                _append_forward_step(steps, nested, source, forward_function, layer_names, aliases, outputs)
            continue
        _append_forward_step(steps, stmt, source, forward_function, layer_names, aliases, outputs)

    if not outputs:
        outputs.append("无显式 return")
        warnings.append("forward 中未发现显式 return。")
    return steps, inputs, outputs, warnings


def _append_forward_step(
    steps: list[ForwardStep],
    stmt: ast.stmt,
    source: str,
    forward_function: dict,
    layer_names: set[str],
    aliases: dict[str, str],
    outputs: list[str],
) -> None:
    target: str | None = None
    expression_node: ast.AST | None = None
    is_return = False
    if isinstance(stmt, ast.Assign) and stmt.targets:
        target = _node_to_text(stmt.targets[0])
        expression_node = stmt.value
    elif isinstance(stmt, ast.AnnAssign):
        target = _node_to_text(stmt.target)
        expression_node = stmt.value
    elif isinstance(stmt, ast.Expr):
        expression_node = stmt.value
    elif isinstance(stmt, ast.Return):
        expression_node = stmt.value
        is_return = True
    if expression_node is None:
        return

    expression = ast.get_source_segment(source, expression_node) or _node_to_text(expression_node)
    calls = [_canonical_name(_node_to_text(call.func), aliases) for call in ast.walk(expression_node) if isinstance(call, ast.Call)]
    uses_layers = [
        f"self.{name}"
        for name in layer_names
        if f"self.{name}" in calls
    ]
    if is_return:
        outputs.append(expression)

    steps.append(
        ForwardStep(
            order=len(steps) + 1,
            target=target,
            expression=expression,
            calls=calls,
            uses_layers=uses_layers,
            line_no=_absolute_line_no(forward_function, getattr(stmt, "lineno", None)),
            explanation=_forward_step_explanation(is_return, uses_layers, calls),
            evidence=[f"forward 第 {len(steps) + 1} 个可识别语句：{expression}"],
        )
    )


def _detect_component_candidates(
    class_info: dict,
    layers: list[ModelLayer],
    forward_steps: list[ForwardStep],
    library_calls: list[dict],
) -> list[ModelComponentCandidate]:
    candidates: dict[tuple[str, str], ModelComponentCandidate] = {}
    for layer in layers:
        confidence = _role_confidence(layer.name, layer.layer_type)
        if layer.role == "unknown" or confidence == "low":
            continue
        candidates[(layer.assigned_name, layer.role)] = ModelComponentCandidate(
            name=layer.assigned_name,
            role=layer.role,
            file_path=class_info.get("file_path", ""),
            class_name=class_info.get("class_name", ""),
            line_no=layer.line_no,
            evidence=layer.evidence,
            confidence=confidence,  # type: ignore[arg-type]
        )

    for step in forward_steps:
        for call in step.calls:
            role = _role_for_name_and_type(call, call)
            confidence = _role_confidence(call, call)
            if role == "unknown" or confidence == "low":
                continue
            key = (call, role)
            candidates.setdefault(
                key,
                ModelComponentCandidate(
                    name=call,
                    role=role,
                    file_path=class_info.get("file_path", ""),
                    class_name=class_info.get("class_name", ""),
                    line_no=step.line_no,
                    evidence=[f"forward 调用 {call} 命中 {role} 角色关键词。"],
                    confidence=confidence,  # type: ignore[arg-type]
                ),
            )

    for call in library_calls:
        if call.get("file_path") != class_info.get("file_path") or call.get("class_name") != class_info.get("class_name"):
            continue
        name = call.get("canonical_name", "")
        role = _role_for_name_and_type(name, name)
        confidence = _role_confidence(name, name)
        if role in {"loss", "head", "classifier"} and confidence != "low":
            candidates.setdefault(
                (name, role),
                ModelComponentCandidate(
                    name=name,
                    role=role,
                    file_path=class_info.get("file_path", ""),
                    class_name=class_info.get("class_name", ""),
                    line_no=call.get("line_no"),
                    evidence=[f"library_calls 中 {name} 命中 {role} 角色关键词。"],
                    confidence=confidence,  # type: ignore[arg-type]
                ),
            )
    return list(candidates.values())


def _mark_main_model_candidates(models: list[ModelAnalysis], file_analysis_by_path: dict[str, dict]) -> None:
    if not models:
        return
    scored: list[tuple[int, int, int, ModelAnalysis, list[str]]] = []
    for model in models:
        score, reasons = _score_main_model_candidate(model, file_analysis_by_path.get(model.file_path, {}))
        has_forward = 1 if model.forward_function else 0
        scored.append((score, has_forward, len(model.layers), model, reasons))
    score, _has_forward, _layer_count, best_model, reasons = max(scored, key=lambda item: (item[0], item[1], item[2]))
    if score < 6:
        return
    best_model.is_main_model_candidate = True
    best_model.main_model_reason = f"主模型候选得分 {score}：{'；'.join(reasons)}"
    best_model.evidence.append(best_model.main_model_reason)


def _score_main_model_candidate(model: ModelAnalysis, file_info: dict) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if model.is_nn_module:
        score += 3
        reasons.append("继承或匹配 nn.Module")
    if model.forward_function:
        score += 3
        reasons.append("包含 forward")
    if model.init_function:
        score += 2
        reasons.append("包含 __init__")
    if any(layer.layer_type.startswith("torch.nn.") for layer in model.layers):
        score += 3
        reasons.append("在 __init__ 中定义 torch.nn 网络层")
    if any(step.uses_layers for step in model.forward_steps):
        score += 2
        reasons.append("forward 调用 self 层")
    if file_info.get("file_type") == "model":
        score += 2
        reasons.append("所在文件被识别为模型文件")
    lower_class = model.class_name.lower()
    if any(keyword in lower_class for keyword in MODEL_NAME_KEYWORDS):
        score += 1
        reasons.append("类名命中模型关键词")
    if "loss" in lower_class:
        score -= 2
        reasons.append("类名包含 Loss，降低主模型优先级")
    if "loss" in model.file_path.lower():
        score -= 2
        reasons.append("路径包含 loss，降低主模型优先级")
    return score, reasons


def _role_for_name_and_type(name: str, layer_type: str) -> ComponentRole:
    name_text = name.lower()
    type_text = layer_type.lower()
    combined_text = f"{name_text} {type_text}"
    if any(keyword in combined_text for keyword in ("encoder", "enc")):
        return "encoder"
    if any(keyword in combined_text for keyword in ("decoder", "dec")):
        return "decoder"
    if any(keyword in combined_text for keyword in ("backbone", "resnet", "vgg", "vit", "transformer", "feature_extractor")):
        return "backbone"
    if any(keyword in combined_text for keyword in ("loss", "criterion", "crossentropyloss", "mseloss", "bcewithlogitsloss")):
        return "loss"
    if any(keyword in combined_text for keyword in ("embedding", "embed")):
        return "embedding"
    if any(keyword in combined_text for keyword in ("batchnorm", "layernorm", "norm")):
        return "normalization"
    if any(keyword in combined_text for keyword in ("relu", "gelu", "sigmoid", "softmax")):
        return "activation"
    if any(keyword in name_text for keyword in ("classifier", "cls", "output")):
        return "classifier"
    if any(keyword in name_text for keyword in ("head", "cls_head", "bbox_head", "seg_head")):
        return "head"
    if any(keyword in name_text for keyword in ("proj", "projection")):
        return "head"
    if any(keyword in name_text for keyword in ("fc", "linear")):
        return "head"
    return "unknown"


def _role_confidence(name: str, layer_type: str) -> str:
    role_from_name = _role_for_name_and_type(name, "")
    role_from_type = _role_for_name_and_type("", layer_type)
    if role_from_name != "unknown" and role_from_type != "unknown":
        return "high"
    if role_from_name != "unknown" or role_from_type != "unknown":
        return "medium"
    return "low"


def _is_linear_mapping_hint(name: str, layer_type: str) -> bool:
    text = f"{name} {layer_type}".lower()
    return any(keyword in text for keyword in ("linear", "fc", "proj", "projection"))


def _forward_step_explanation(is_return: bool, uses_layers: list[str], calls: list[str]) -> str:
    if is_return:
        return "返回模型 forward 的输出表达式。"
    if uses_layers:
        return f"调用模型层 {', '.join(uses_layers)} 处理输入或中间特征。"
    if calls:
        return f"调用 {', '.join(calls)} 等函数进行张量计算。"
    return "执行 forward 中的基础表达式。"


def _model_summary(class_info: dict, layers: list[ModelLayer], forward_steps: list[ForwardStep]) -> str:
    return (
        f"`{class_info.get('class_name', '')}` 是位于 `{class_info.get('file_path', '')}` 的模型类，"
        f"识别到 {len(layers)} 个初始化层和 {len(forward_steps)} 个 forward 基础步骤。"
    )


def _parse_function_source(function: dict | None) -> ast.AST | None:
    if not function or not function.get("source_code"):
        return None
    try:
        return ast.parse(function["source_code"])
    except SyntaxError:
        return None


def _interesting_nested_statements(node: ast.AST) -> list[ast.stmt]:
    nested: list[ast.stmt] = []
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.Expr, ast.Return)):
            nested.append(child)
    return nested


def _canonical_name(name: str, aliases: dict[str, str]) -> str:
    if "." not in name:
        return aliases.get(name, name)
    root, suffix = name.split(".", 1)
    canonical_root = aliases.get(root, root)
    return f"{canonical_root}.{suffix}"


def _self_attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def _node_to_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _absolute_line_no(function: dict, node_line_no: int | None) -> int | None:
    if function.get("start_line") is None or node_line_no is None:
        return None
    return function["start_line"] + node_line_no - 1
