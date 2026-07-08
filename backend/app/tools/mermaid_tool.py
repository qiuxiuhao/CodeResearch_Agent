from __future__ import annotations

import re

from backend.app.schemas.diagram import (
    Diagram,
    DiagramEdge,
    DiagramGenerationResult,
    DiagramNode,
    DiagramSourceRef,
)


MAX_PROJECT_FILES = 20
MAX_FUNCTION_LOGIC_DIAGRAMS = 3
MAX_DIAGRAM_NODES = 20
FILE_TYPE_LABELS = {
    "entry": "入口文件",
    "model": "模型文件",
    "training": "训练文件",
    "inference": "推理文件",
    "dataset": "数据集文件",
    "config_related": "配置文件",
    "utility": "工具文件",
    "package_init": "包初始化",
    "ordinary_module": "普通模块",
    "unknown": "未知文件",
}
FILE_TYPE_PRIORITY = {
    "entry": 0,
    "model": 1,
    "training": 2,
    "dataset": 3,
    "inference": 4,
    "config_related": 5,
    "utility": 6,
    "ordinary_module": 7,
    "package_init": 8,
    "unknown": 9,
}


def generate_diagrams(
    repo_index: dict,
    file_analysis: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
    paper_analysis: dict,
    paper_code_alignment: dict,
    library_calls: list[dict],
) -> DiagramGenerationResult:
    diagrams: list[Diagram] = []
    warnings: list[str] = []
    errors: list[dict] = []

    builders = [
        ("project_structure", lambda: _build_project_structure_diagram(repo_index, file_analysis)),
        ("model_flow", lambda: _build_model_flow_diagram(model_analysis)),
        ("core_modules", lambda: _build_core_modules_diagram(file_analysis, function_analysis, model_analysis)),
        ("function_logic", lambda: _build_function_logic_diagrams(function_analysis, library_calls)),
        ("paper_code_alignment", lambda: _build_paper_code_alignment_diagram(paper_analysis, paper_code_alignment)),
    ]

    for name, builder in builders:
        try:
            result = builder()
            if isinstance(result, list):
                diagrams.extend(result)
            elif result is not None:
                diagrams.append(result)
        except Exception as exc:
            errors.append(
                {
                    "tool": "mermaid_tool",
                    "diagram": name,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    if not repo_index.get("python_files") and not file_analysis:
        warnings.append("未发现可用于生成项目结构图的 Python 文件。")
    if not model_analysis:
        warnings.append("未发现模型分析结果，跳过模型整体流程图。")
    if not paper_analysis.get("paper_provided"):
        warnings.append("未提供论文 PDF，跳过论文-代码图。")

    return DiagramGenerationResult(diagrams=diagrams, warnings=warnings, errors=errors)


def _build_project_structure_diagram(repo_index: dict, file_analysis: list[dict]) -> Diagram | None:
    python_files = repo_index.get("python_files", [])
    if not python_files and not file_analysis:
        return None

    analysis_by_path = {item.get("file_path"): item for item in file_analysis}
    sorted_files = sorted(
        python_files or list(analysis_by_path),
        key=lambda path: (FILE_TYPE_PRIORITY.get(analysis_by_path.get(path, {}).get("file_type", "unknown"), 9), path),
    )
    warnings: list[str] = []
    if len(sorted_files) > MAX_PROJECT_FILES:
        warnings.append("项目文件较多，v0.7 图中仅展示核心文件。")
    selected_files = sorted_files[:MAX_PROJECT_FILES]

    nodes = [_make_node("Project", "Project", "unknown")]
    edges: list[DiagramEdge] = []
    group_ids: dict[str, str] = {}

    for file_path in selected_files:
        info = analysis_by_path.get(file_path, {})
        file_type = info.get("file_type", "unknown")
        group_id = f"Group_{_safe_node_id(file_type)}"
        if group_id not in group_ids:
            group_ids[file_type] = group_id
            nodes.append(_make_node(group_id, FILE_TYPE_LABELS.get(file_type, file_type), "unknown"))
            edges.append(_make_edge("Project", group_id))

        file_id = f"File_{_safe_node_id(file_path)}"
        nodes.append(
            _make_node(
                file_id,
                file_path,
                "file",
                [_source_ref("file_analysis", file_path=file_path, evidence=info.get("evidence", []))],
            )
        )
        edges.append(_make_edge(group_id, file_id, source_refs=[_source_ref("repo_index", file_path=file_path)]))

        for class_name in info.get("main_classes", [])[:3]:
            class_id = f"Class_{_safe_node_id(file_path + '_' + class_name)}"
            nodes.append(
                _make_node(
                    class_id,
                    f"class {class_name}",
                    "class",
                    [_source_ref("file_analysis", file_path=file_path, class_name=class_name)],
                )
            )
            edges.append(_make_edge(file_id, class_id))

        for function_name in info.get("main_functions", [])[:3]:
            function_id = f"Func_{_safe_node_id(file_path + '_' + function_name)}"
            nodes.append(
                _make_node(
                    function_id,
                    function_name,
                    "function",
                    [_source_ref("file_analysis", file_path=file_path, function_name=function_name)],
                )
            )
            edges.append(_make_edge(file_id, function_id))

    return _diagram(
        diagram_id="project_structure",
        title="项目结构图",
        diagram_type="project_structure",
        description="基于 repo_index 和 file_analysis 生成的项目结构图。",
        direction="TD",
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        source_refs=[_source_ref("repo_index")],
    )


def _build_model_flow_diagram(model_analysis: list[dict]) -> Diagram | None:
    if not model_analysis:
        return None

    model = next((item for item in model_analysis if item.get("is_main_model_candidate")), model_analysis[0])
    class_name = model.get("class_name", "Model")
    nodes = [
        _make_node(
            f"Model_{_safe_node_id(class_name)}",
            class_name,
            "model",
            [_source_ref("model_analysis", file_path=model.get("file_path"), class_name=class_name, line_no=model.get("start_line"))],
        )
    ]
    edges: list[DiagramEdge] = []
    warnings: list[str] = []
    layer_by_names: dict[str, dict] = {}
    for layer in model.get("layers", []):
        layer_by_names[layer.get("name", "")] = layer
        layer_by_names[layer.get("assigned_name", "")] = layer

    previous_ids: list[str] = []
    inputs = model.get("model_inputs", []) or ["input"]
    for input_name in inputs[:3]:
        node_id = f"Input_{_safe_node_id(input_name)}"
        nodes.append(_make_node(node_id, f"输入 {input_name}", "unknown", [_source_ref("model_analysis", class_name=class_name)]))
        previous_ids.append(node_id)

    steps = sorted(model.get("forward_steps", []), key=lambda item: item.get("order", 0))
    if steps:
        for step in steps[:12]:
            step_nodes = _nodes_for_forward_step(step, layer_by_names, model)
            if not step_nodes:
                continue
            for node in step_nodes:
                nodes.append(node)
            for previous_id in previous_ids or [f"Model_{_safe_node_id(class_name)}"]:
                edges.append(
                    _make_edge(
                        previous_id,
                        step_nodes[0].id,
                        source_refs=[_source_ref("model_analysis", file_path=model.get("file_path"), class_name=class_name, line_no=step.get("line_no"), evidence=step.get("evidence", []))],
                    )
                )
            for source_node, target_node in zip(step_nodes, step_nodes[1:]):
                edges.append(
                    _make_edge(
                        source_node.id,
                        target_node.id,
                        source_refs=[_source_ref("model_analysis", file_path=model.get("file_path"), class_name=class_name, line_no=step.get("line_no"), evidence=step.get("evidence", []))],
                    )
                )
            previous_ids = [step_nodes[-1].id]
    else:
        warnings.append("forward 步骤不足，使用输入 -> 层 -> 输出的简化模型流程图。")
        for layer in model.get("layers", [])[:12]:
            layer_id = f"Layer_{_safe_node_id(layer.get('assigned_name', layer.get('name', 'layer')))}"
            nodes.append(_layer_node(layer, model))
            for previous_id in previous_ids or [f"Model_{_safe_node_id(class_name)}"]:
                edges.append(_make_edge(previous_id, layer_id))
            previous_ids = [layer_id]

    outputs = model.get("model_outputs", []) or ["output"]
    for output in outputs[:3]:
        output_id = f"Output_{_safe_node_id(output)}"
        nodes.append(_make_node(output_id, f"输出 {output}", "unknown", [_source_ref("model_analysis", class_name=class_name)]))
        for previous_id in previous_ids or [f"Model_{_safe_node_id(class_name)}"]:
            edges.append(_make_edge(previous_id, output_id))

    return _diagram(
        diagram_id="model_flow",
        title="模型整体流程图",
        diagram_type="model_flow",
        description="基于 model_analysis.json 的基础静态分析结果，不代表完整运行时动态图。",
        direction="LR",
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        source_refs=[_source_ref("model_analysis", file_path=model.get("file_path"), class_name=class_name)],
    )


def _build_core_modules_diagram(
    file_analysis: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
) -> Diagram | None:
    nodes: list[DiagramNode] = []
    edges: list[DiagramEdge] = []

    for model in model_analysis[:5]:
        model_id = f"Model_{_safe_node_id(model.get('class_name', 'model'))}"
        nodes.append(
            _make_node(
                model_id,
                model.get("class_name", "Model"),
                "model",
                [_source_ref("model_analysis", file_path=model.get("file_path"), class_name=model.get("class_name"), line_no=model.get("start_line"))],
            )
        )
        for component in model.get("component_candidates", [])[:8]:
            component_id = f"Component_{_safe_node_id(model.get('class_name', '') + '_' + component.get('name', 'component'))}"
            nodes.append(
                _make_node(
                    component_id,
                    f"{component.get('name', '')}: {component.get('role', 'unknown')}",
                    "component",
                    [_source_ref("model_analysis", file_path=component.get("file_path"), class_name=component.get("class_name"), line_no=component.get("line_no"), evidence=component.get("evidence", []))],
                    confidence=component.get("confidence", "medium"),
                )
            )
            edges.append(_make_edge(model_id, component_id, label=component.get("role")))

    core_functions = [item for item in function_analysis if item.get("is_core_function")][:5]
    for function in core_functions:
        function_id = f"CoreFunc_{_safe_node_id(function.get('qualified_name', function.get('function_name', 'function')))}"
        nodes.append(
            _make_node(
                function_id,
                function.get("qualified_name", function.get("function_name", "")),
                "function",
                [_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=function.get("qualified_name"), function_name=function.get("function_name"), line_no=function.get("start_line"), evidence=function.get("evidence", []))],
            )
        )
        for model in model_analysis:
            model_name = model.get("class_name", "")
            if model_name and model_name.lower() in " ".join(function.get("evidence", []) + [function.get("qualified_name", "")]).lower():
                edges.append(_make_edge(function_id, f"Model_{_safe_node_id(model_name)}", is_uncertain=True, confidence="low"))

    for file_info in file_analysis:
        if file_info.get("file_type") not in {"model", "training", "dataset"}:
            continue
        file_id = f"CoreFile_{_safe_node_id(file_info.get('file_path', 'file'))}"
        nodes.append(
            _make_node(
                file_id,
                file_info.get("file_path", ""),
                "file",
                [_source_ref("file_analysis", file_path=file_info.get("file_path"), evidence=file_info.get("evidence", []))],
            )
        )

    if not nodes:
        return None

    return _diagram(
        diagram_id="core_modules",
        title="核心模块图",
        diagram_type="core_modules",
        description="基于模型组件候选、核心函数和核心文件生成的静态模块关系图。",
        direction="TD",
        nodes=nodes,
        edges=edges,
        source_refs=[_source_ref("model_analysis"), _source_ref("function_analysis"), _source_ref("file_analysis")],
    )


def _build_function_logic_diagrams(function_analysis: list[dict], library_calls: list[dict]) -> list[Diagram]:
    selected = sorted(
        function_analysis,
        key=lambda item: (
            not item.get("is_core_function"),
            "forward" not in item.get("qualified_name", "").lower(),
            "train" not in item.get("qualified_name", "").lower(),
            item.get("qualified_name", ""),
        ),
    )[:MAX_FUNCTION_LOGIC_DIAGRAMS]
    diagrams: list[Diagram] = []
    library_calls_by_key: dict[tuple[str, str], list[dict]] = {}
    for call in library_calls:
        key = (call.get("file_path", ""), call.get("qualified_function_name", ""))
        library_calls_by_key.setdefault(key, []).append(call)

    for function in selected:
        qualified_name = function.get("qualified_name", function.get("function_name", "function"))
        function_id = f"Function_{_safe_node_id(qualified_name)}"
        nodes = [
            _make_node(
                function_id,
                qualified_name,
                "function",
                [_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=qualified_name, function_name=function.get("function_name"), line_no=function.get("start_line"), evidence=function.get("evidence", []))],
            )
        ]
        edges: list[DiagramEdge] = []
        previous_id = function_id
        warnings: list[str] = []

        if not function.get("implementation_logic"):
            warnings.append("函数实现逻辑信息不足，生成简化函数逻辑图。")
        for index, step in enumerate(function.get("implementation_logic", [])[:6], start=1):
            step_id = f"{function_id}_Step_{index}"
            nodes.append(_make_node(step_id, f"{index}. {step}", "unknown", [_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=qualified_name)]))
            edges.append(_make_edge(previous_id, step_id))
            previous_id = step_id

        for internal_name in function.get("called_internal_functions", [])[:4]:
            internal_id = f"{function_id}_Internal_{_safe_node_id(internal_name)}"
            nodes.append(_make_node(internal_id, internal_name, "function", [_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=qualified_name)]))
            edges.append(_make_edge(previous_id, internal_id, label="internal call"))
            previous_id = internal_id

        embedded_calls = function.get("library_calls") or library_calls_by_key.get((function.get("file_path", ""), qualified_name), [])
        for call in embedded_calls[:5]:
            if _is_low_confidence_unknown_call(call):
                warnings.append(f"跳过低置信度 unknown 调用：{call.get('canonical_name') or call.get('display_name') or call.get('call_text')}")
                continue
            call_name = call.get("canonical_name", call.get("display_name", "library_call"))
            line_no = call.get("line_no")
            call_id = f"{function_id}_Lib_{_safe_node_id(call_name)}_{line_no or 'unknown'}"
            nodes.append(
                _make_node(
                    call_id,
                    call_name,
                    "function",
                    [_source_ref("function_analysis", file_path=call.get("file_path", function.get("file_path")), qualified_name=qualified_name, line_no=call.get("line_no"), evidence=[call.get("call_text", "")])],
                )
            )
            edges.append(_make_edge(previous_id, call_id, label="library call"))
            previous_id = call_id

        for output in (function.get("outputs") or ["输出"])[:2]:
            output_id = f"{function_id}_Output_{_safe_node_id(output)}"
            nodes.append(_make_node(output_id, f"输出 {output}", "unknown", [_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=qualified_name)]))
            edges.append(_make_edge(previous_id, output_id))

        diagrams.append(
            _diagram(
                diagram_id=f"function_logic_{_safe_node_id(qualified_name)}",
                title=f"函数逻辑图：{qualified_name}",
                diagram_type="function_logic",
                description="基于 function_analysis.json 的核心函数基础静态流程图。",
                direction="TD",
                nodes=nodes,
                edges=edges,
                warnings=warnings,
                source_refs=[_source_ref("function_analysis", file_path=function.get("file_path"), qualified_name=qualified_name)],
            )
        )
    return diagrams


def _build_paper_code_alignment_diagram(paper_analysis: dict, paper_code_alignment: dict) -> Diagram | None:
    if not paper_analysis.get("paper_provided"):
        return None

    nodes: list[DiagramNode] = []
    edges: list[DiagramEdge] = []
    warnings: list[str] = []
    alignment_items = paper_code_alignment.get("alignment_items", [])[:5]
    if not alignment_items:
        warnings.append("未发现论文-代码对齐结果，生成空论文对齐图。")

    unmatched_id = "Paper_Unmatched"
    has_unmatched = False
    for item in alignment_items:
        contribution_id = item.get("contribution_id", "")
        contribution_node_id = f"Contribution_{_safe_node_id(contribution_id or item.get('contribution_title', 'contribution'))}"
        nodes.append(
            _make_node(
                contribution_node_id,
                f"{contribution_id}: {item.get('contribution_title', '')}",
                "paper_contribution",
                [_source_ref("paper_analysis", contribution_id=contribution_id, evidence=item.get("evidence", []))],
                confidence=item.get("confidence", "low"),
                is_uncertain=item.get("confidence") == "low",
            )
        )
        if item.get("status") != "matched":
            has_unmatched = True
            edges.append(
                _make_edge(
                    contribution_node_id,
                    unmatched_id,
                    label="unmatched",
                    source_refs=[_source_ref("paper_code_alignment", contribution_id=contribution_id, evidence=[item.get("reason", "")])],
                    confidence="low",
                    is_uncertain=True,
                )
            )
            continue

        for target in item.get("matched_targets", [])[:5]:
            target_label = f"{target.get('target_type', '')}: {target.get('name', '')}"
            target_id = f"PaperTarget_{_safe_node_id(target_label + '_' + str(target.get('line_no') or ''))}"
            nodes.append(
                _make_node(
                    target_id,
                    target_label,
                    _node_type_for_target(target.get("target_type", "")),
                    [_source_ref("paper_code_alignment", file_path=target.get("file_path"), qualified_name=target.get("qualified_name"), line_no=target.get("line_no"), contribution_id=contribution_id, evidence=target.get("evidence", []))],
                    confidence=item.get("confidence", "low"),
                    is_uncertain=item.get("confidence") == "low",
                )
            )
            edges.append(
                _make_edge(
                    contribution_node_id,
                    target_id,
                    label=item.get("confidence", "low"),
                    source_refs=[_source_ref("paper_code_alignment", contribution_id=contribution_id, evidence=[item.get("reason", "")])],
                    confidence=item.get("confidence", "low"),
                    is_uncertain=item.get("confidence") == "low",
                )
            )

    if has_unmatched:
        nodes.append(_make_node(unmatched_id, "未匹配代码目标", "unknown", [], confidence="low", is_uncertain=True))

    return _diagram(
        diagram_id="paper_code_alignment",
        title="论文创新点到代码实现对应图",
        diagram_type="paper_code_alignment",
        description="基于 paper_analysis.json 和 paper_code_alignment.json 的启发式对应关系图。",
        direction="LR",
        nodes=nodes,
        edges=edges,
        warnings=warnings,
        source_refs=[_source_ref("paper_analysis"), _source_ref("paper_code_alignment")],
    )


def _nodes_for_forward_step(step: dict, layer_by_names: dict[str, dict], model: dict) -> list[DiagramNode]:
    nodes: list[DiagramNode] = []
    used_layers = step.get("uses_layers", [])
    for layer_name in used_layers:
        layer = layer_by_names.get(layer_name) or layer_by_names.get(layer_name.replace("self.", ""))
        if layer:
            nodes.append(_layer_node(layer, model))
    calls = [call for call in step.get("calls", []) if call not in used_layers]
    for call in calls[:2]:
        nodes.append(
            _make_node(
                f"Call_{_safe_node_id(str(step.get('order', '')) + '_' + call)}",
                call,
                "function",
                [_source_ref("model_analysis", file_path=model.get("file_path"), class_name=model.get("class_name"), line_no=step.get("line_no"), evidence=step.get("evidence", []))],
            )
        )
    if not nodes:
        nodes.append(
            _make_node(
                f"ForwardStep_{_safe_node_id(str(step.get('order', 'step')))}",
                step.get("explanation") or step.get("expression", "forward step"),
                "unknown",
                [_source_ref("model_analysis", file_path=model.get("file_path"), class_name=model.get("class_name"), line_no=step.get("line_no"), evidence=step.get("evidence", []))],
                confidence="low",
                is_uncertain=True,
            )
        )
    return nodes


def _layer_node(layer: dict, model: dict) -> DiagramNode:
    assigned_name = layer.get("assigned_name", layer.get("name", "layer"))
    return _make_node(
        f"Layer_{_safe_node_id(assigned_name)}",
        f"{assigned_name}<br/>{layer.get('layer_type', '')}",
        "layer",
        [_source_ref("model_analysis", file_path=model.get("file_path"), class_name=model.get("class_name"), line_no=layer.get("line_no"), evidence=layer.get("evidence", []))],
        confidence="medium",
    )


def _diagram(
    diagram_id: str,
    title: str,
    diagram_type: str,
    description: str,
    direction: str,
    nodes: list[DiagramNode],
    edges: list[DiagramEdge],
    source_refs: list[DiagramSourceRef] | None = None,
    warnings: list[str] | None = None,
    confidence: str = "medium",
) -> Diagram:
    deduped_nodes = _dedupe_nodes(nodes)
    deduped_edges = _dedupe_edges(edges, {node.id for node in deduped_nodes})
    diagram_warnings = list(warnings or [])
    if len(deduped_nodes) > MAX_DIAGRAM_NODES:
        diagram_warnings.append("图节点较多，v0.7 仅展示前 20 个节点。")
        keep_ids = {node.id for node in deduped_nodes[:MAX_DIAGRAM_NODES]}
        deduped_nodes = deduped_nodes[:MAX_DIAGRAM_NODES]
        deduped_edges = [edge for edge in deduped_edges if edge.source in keep_ids and edge.target in keep_ids]
    return Diagram(
        id=diagram_id,
        title=title,
        diagram_type=diagram_type,  # type: ignore[arg-type]
        description=description,
        mermaid=_render_mermaid(direction, deduped_nodes, deduped_edges),
        nodes=deduped_nodes,
        edges=deduped_edges,
        source_refs=source_refs or [],
        warnings=diagram_warnings,
        confidence=confidence,  # type: ignore[arg-type]
    )


def _make_node(
    node_id: str,
    label: str,
    node_type: str,
    source_refs: list[DiagramSourceRef] | None = None,
    confidence: str = "medium",
    is_uncertain: bool = False,
) -> DiagramNode:
    return DiagramNode(
        id=_safe_node_id(node_id),
        label=_escape_label(label or node_id),
        node_type=node_type,  # type: ignore[arg-type]
        source_refs=source_refs or [],
        confidence=confidence,  # type: ignore[arg-type]
        is_uncertain=is_uncertain,
    )


def _make_edge(
    source: str,
    target: str,
    label: str | None = None,
    source_refs: list[DiagramSourceRef] | None = None,
    confidence: str = "medium",
    is_uncertain: bool = False,
) -> DiagramEdge:
    return DiagramEdge(
        source=_safe_node_id(source),
        target=_safe_node_id(target),
        label=_escape_label(label) if label else None,
        source_refs=source_refs or [],
        confidence=confidence,  # type: ignore[arg-type]
        is_uncertain=is_uncertain,
    )


def _source_ref(
    source_type: str,
    file_path: str | None = None,
    qualified_name: str | None = None,
    class_name: str | None = None,
    function_name: str | None = None,
    line_no: int | None = None,
    contribution_id: str | None = None,
    evidence: list[str] | None = None,
) -> DiagramSourceRef:
    return DiagramSourceRef(
        source_type=source_type,  # type: ignore[arg-type]
        file_path=file_path,
        qualified_name=qualified_name,
        class_name=class_name,
        function_name=function_name,
        line_no=line_no,
        contribution_id=contribution_id,
        evidence=[item for item in (evidence or []) if item],
    )


def _render_mermaid(direction: str, nodes: list[DiagramNode], edges: list[DiagramEdge]) -> str:
    lines = [f"flowchart {direction}"]
    for node in nodes:
        lines.append(f'  {node.id}["{node.label}"]')
    for edge in edges:
        arrow = "-.->" if edge.is_uncertain else "-->"
        if edge.label:
            lines.append(f"  {edge.source} {arrow}|{edge.label}| {edge.target}")
        else:
            lines.append(f"  {edge.source} {arrow} {edge.target}")
    return "\n".join(lines)


def _dedupe_nodes(nodes: list[DiagramNode]) -> list[DiagramNode]:
    seen: set[str] = set()
    result: list[DiagramNode] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        result.append(node)
    return result


def _dedupe_edges(edges: list[DiagramEdge], node_ids: set[str]) -> list[DiagramEdge]:
    seen: set[tuple[str, str, str | None]] = set()
    result: list[DiagramEdge] = []
    for edge in edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            continue
        if edge.source == edge.target:
            continue
        key = (edge.source, edge.target, edge.label)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _is_low_confidence_unknown_call(call: dict) -> bool:
    return call.get("confidence") == "low" and call.get("category") == "unknown"


def _node_type_for_target(target_type: str) -> str:
    return {
        "file": "file",
        "class": "class",
        "function": "function",
        "model_module": "component",
    }.get(target_type, "unknown")


def _safe_node_id(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_]+", "_", str(value))
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = "N"
    if text[0].isdigit():
        text = f"N_{text}"
    return text[:80]


def _escape_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = text.replace('"', "'").replace("[", "(").replace("]", ")")
    if len(text) > 60:
        text = text[:57].rstrip() + "..."
    return text
