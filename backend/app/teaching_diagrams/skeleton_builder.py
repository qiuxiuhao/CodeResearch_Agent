from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from backend.app.schemas.teaching_diagram import (
    SCHEMA_VERSION,
    TeachingDiagramConnection,
    TeachingDiagramEvidenceItem,
    TeachingDiagramFormula,
    TeachingDiagramLegendItem,
    TeachingDiagramModule,
    TeachingDiagramSection,
    TeachingDiagramShape,
    TeachingDiagramSkeleton,
    TeachingDiagramSourceEntity,
)


MAX_TEACHING_DIAGRAMS = 4


@dataclass(slots=True)
class SkeletonBuildResult:
    skeletons: list[TeachingDiagramSkeleton] = field(default_factory=list)
    evidence_catalog: list[TeachingDiagramEvidenceItem] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


def build_teaching_diagram_skeletons(
    *,
    repo_index: dict,
    file_analysis: list[dict],
    function_analysis: list[dict],
    library_calls: list[dict],
    model_analysis: list[dict],
    paper_analysis: dict,
    paper_code_alignment: dict,
    diagrams: list[dict],
    llm_explanations: dict | None = None,
    paper_figure_analysis: dict | None = None,
    max_diagrams: int = MAX_TEACHING_DIAGRAMS,
) -> SkeletonBuildResult:
    del repo_index, library_calls, paper_analysis, paper_code_alignment, llm_explanations, paper_figure_analysis
    catalog: dict[str, TeachingDiagramEvidenceItem] = {}
    result = SkeletonBuildResult()
    selected: list[TeachingDiagramSkeleton] = []
    diagram_ids_by_type = _diagram_ids_by_type(diagrams)

    for model in _rank_models(model_analysis):
        if len(selected) >= max_diagrams:
            break
        skeleton = _build_model_skeleton(model, diagram_ids_by_type, catalog)
        if skeleton:
            selected.append(skeleton)

    for function in _rank_functions(function_analysis):
        if len(selected) >= max_diagrams:
            break
        skeleton = _build_function_skeleton(function, diagram_ids_by_type, catalog)
        if skeleton and skeleton.skeleton_id not in {item.skeleton_id for item in selected}:
            selected.append(skeleton)

    if len(selected) < max_diagrams:
        data_flow = _build_data_flow_skeleton(file_analysis, diagram_ids_by_type, catalog)
        if data_flow:
            selected.append(data_flow)

    result.skeletons = selected[:max_diagrams]
    result.evidence_catalog = sorted(catalog.values(), key=lambda item: item.evidence_id)
    if not result.skeletons:
        result.warnings.append({
            "code": "teaching_diagram_no_eligible_entity",
            "message": "No high-quality rule-backed entity was eligible for teaching diagrams.",
        })
    return result


def _rank_models(model_analysis: list[dict]) -> list[dict]:
    return sorted(
        [item for item in model_analysis if item.get("layers") or item.get("forward_steps")],
        key=lambda item: (
            not item.get("is_main_model_candidate"),
            -len(item.get("forward_steps", [])),
            -len(item.get("layers", [])),
            item.get("class_name", ""),
        ),
    )


def _rank_functions(function_analysis: list[dict]) -> list[dict]:
    candidates = [
        item for item in function_analysis
        if item.get("implementation_logic") or item.get("called_internal_functions") or item.get("library_calls")
    ]
    return sorted(
        candidates,
        key=lambda item: (
            not item.get("is_core_function"),
            "forward" not in item.get("qualified_name", "").lower(),
            "train" not in item.get("qualified_name", "").lower(),
            item.get("qualified_name", ""),
        ),
    )[:MAX_TEACHING_DIAGRAMS]


def _build_model_skeleton(
    model: dict,
    diagram_ids_by_type: dict[str, list[str]],
    catalog: dict[str, TeachingDiagramEvidenceItem],
) -> TeachingDiagramSkeleton | None:
    class_name = str(model.get("class_name") or "Model")
    source = TeachingDiagramSourceEntity(
        entity_type="model",
        entity_id=f"model:{class_name}",
        title=f"{class_name} 模型数据流",
        file_path=model.get("file_path"),
        class_name=class_name,
    )
    related = [*diagram_ids_by_type.get("model_flow", []), *diagram_ids_by_type.get("core_modules", [])]
    evidence_id = _add_evidence(
        catalog,
        "model_analysis",
        f"model:{_safe_id(class_name)}",
        f"模型类 {class_name} 来自规则 model_analysis。",
        file_path=model.get("file_path"),
        class_name=class_name,
        line_no=model.get("start_line"),
        confidence="high" if model.get("is_main_model_candidate") else "medium",
    )
    sections = [TeachingDiagramSection(id="model_flow", title="模型计算路径", evidence_refs=[evidence_id])]
    modules: list[TeachingDiagramModule] = []
    connections: list[TeachingDiagramConnection] = []
    shapes: list[TeachingDiagramShape] = []
    formulas: list[TeachingDiagramFormula] = []
    inputs = [str(item) for item in (model.get("model_inputs") or ["input"])[:3]]
    outputs = [str(item) for item in (model.get("model_outputs") or ["output"])[:3]]

    previous_ids: list[str] = []
    for index, input_name in enumerate(inputs, start=1):
        module_id = f"input_{index}"
        modules.append(TeachingDiagramModule(
            id=module_id, label=f"输入 {input_name}", kind="input", section_id="model_flow",
            evidence_refs=[evidence_id],
        ))
        previous_ids.append(module_id)

    step_modules: list[str] = []
    layer_by_name = {item.get("assigned_name") or item.get("name"): item for item in model.get("layers", [])}
    for step in sorted(model.get("forward_steps", []), key=lambda item: item.get("order", 0))[:8]:
        step_evidence = _add_evidence(
            catalog,
            "model_analysis",
            f"model:{_safe_id(class_name)}:forward:{step.get('order', len(step_modules) + 1)}",
            str(step.get("explanation") or step.get("expression") or "forward step"),
            file_path=model.get("file_path"),
            class_name=class_name,
            line_no=step.get("line_no"),
        )
        used_layers = step.get("uses_layers") or []
        label = used_layers[0] if used_layers else (step.get("target") or step.get("expression") or f"step {len(step_modules) + 1}")
        layer = layer_by_name.get(str(label).replace("self.", "")) or layer_by_name.get(label)
        role = layer.get("role") if isinstance(layer, dict) else None
        module_id = f"step_{len(step_modules) + 1}_{_safe_id(str(label))}"
        modules.append(TeachingDiagramModule(
            id=module_id,
            label=str(label)[:80],
            kind="layer" if layer else "operation",
            section_id="model_flow",
            role=role,
            evidence_refs=[step_evidence],
        ))
        step_modules.append(module_id)
        for previous in previous_ids or [step_modules[-2] if len(step_modules) > 1 else module_id]:
            if previous == module_id:
                continue
            connections.append(TeachingDiagramConnection(
                id=f"edge_{previous}_{module_id}",
                source_module_id=previous,
                target_module_id=module_id,
                label="forward",
                evidence_refs=[step_evidence],
            ))
        previous_ids = [module_id]

    if not step_modules:
        for layer in model.get("layers", [])[:8]:
            layer_id = f"layer_{_safe_id(layer.get('assigned_name') or layer.get('name') or 'layer')}"
            layer_evidence = _add_evidence(
                catalog,
                "model_analysis",
                f"model:{_safe_id(class_name)}:layer:{_safe_id(layer_id)}",
                f"模型层 {layer.get('assigned_name') or layer.get('name')} 类型为 {layer.get('layer_type') or 'unknown'}。",
                file_path=model.get("file_path"),
                class_name=class_name,
                line_no=layer.get("line_no"),
            )
            modules.append(TeachingDiagramModule(
                id=layer_id, label=str(layer.get("assigned_name") or layer.get("name") or "layer"),
                kind="layer", section_id="model_flow", role=layer.get("role"), evidence_refs=[layer_evidence],
            ))
            for previous in previous_ids:
                connections.append(TeachingDiagramConnection(
                    id=f"edge_{previous}_{layer_id}", source_module_id=previous, target_module_id=layer_id,
                    label="layer", evidence_refs=[layer_evidence],
                ))
            previous_ids = [layer_id]

    for index, output_name in enumerate(outputs, start=1):
        module_id = f"output_{index}"
        modules.append(TeachingDiagramModule(
            id=module_id, label=f"输出 {output_name}", kind="output", section_id="model_flow",
            evidence_refs=[evidence_id],
        ))
        for previous in previous_ids:
            connections.append(TeachingDiagramConnection(
                id=f"edge_{previous}_{module_id}", source_module_id=previous, target_module_id=module_id,
                label="return", evidence_refs=[evidence_id],
            ))

    for module in modules:
        if module.kind in {"input", "output"}:
            shapes.append(TeachingDiagramShape(module_id=module.id, label="shape: 规则未确认", evidence_refs=module.evidence_refs))
    for step in model.get("forward_steps", [])[:3]:
        expression = str(step.get("expression") or "")
        if expression and any(token in expression for token in ("+", "-", "*", "/", "matmul", "softmax")):
            formulas.append(TeachingDiagramFormula(
                id=f"formula_{len(formulas) + 1}",
                text=expression[:120],
                evidence_refs=[modules[min(len(formulas) + len(inputs), len(modules) - 1)].evidence_refs[0]],
            ))

    if len(modules) < 2:
        return None
    return _finalize_skeleton(source, related, sections, modules, connections, shapes, formulas, [evidence_id])


def _build_function_skeleton(
    function: dict,
    diagram_ids_by_type: dict[str, list[str]],
    catalog: dict[str, TeachingDiagramEvidenceItem],
) -> TeachingDiagramSkeleton | None:
    qualified_name = str(function.get("qualified_name") or function.get("function_name") or "function")
    source = TeachingDiagramSourceEntity(
        entity_type="function", entity_id=f"function:{qualified_name}", title=f"{qualified_name} 函数逻辑",
        file_path=function.get("file_path"), qualified_name=qualified_name,
        class_name=function.get("class_name"),
    )
    related = diagram_ids_by_type.get("function_logic", [])
    evidence_id = _add_evidence(
        catalog, "function_analysis", f"function:{_safe_id(qualified_name)}",
        f"函数 {qualified_name} 来自规则 function_analysis。",
        file_path=function.get("file_path"), qualified_name=qualified_name,
        function_name=function.get("function_name"), line_no=function.get("start_line"),
        confidence="high" if function.get("is_core_function") else "medium",
    )
    sections = [TeachingDiagramSection(id="function_steps", title="函数执行步骤", evidence_refs=[evidence_id])]
    modules = [TeachingDiagramModule(
        id="function_start", label=qualified_name, kind="function", section_id="function_steps",
        evidence_refs=[evidence_id],
    )]
    connections: list[TeachingDiagramConnection] = []
    previous = "function_start"
    for index, step in enumerate(function.get("implementation_logic", [])[:6], start=1):
        module_id = f"step_{index}"
        modules.append(TeachingDiagramModule(
            id=module_id, label=str(step)[:90], kind="operation", section_id="function_steps",
            evidence_refs=[evidence_id],
        ))
        connections.append(TeachingDiagramConnection(
            id=f"edge_{previous}_{module_id}", source_module_id=previous, target_module_id=module_id,
            label=f"步骤 {index}", evidence_refs=[evidence_id],
        ))
        previous = module_id
    for index, output in enumerate((function.get("outputs") or ["输出"])[:2], start=1):
        module_id = f"output_{index}"
        modules.append(TeachingDiagramModule(
            id=module_id, label=f"输出 {output}", kind="output", section_id="function_steps",
            evidence_refs=[evidence_id],
        ))
        connections.append(TeachingDiagramConnection(
            id=f"edge_{previous}_{module_id}", source_module_id=previous, target_module_id=module_id,
            label="return", evidence_refs=[evidence_id],
        ))
    if len(modules) < 3:
        return None
    return _finalize_skeleton(source, related, sections, modules, connections, [], [], [evidence_id])


def _build_data_flow_skeleton(
    file_analysis: list[dict],
    diagram_ids_by_type: dict[str, list[str]],
    catalog: dict[str, TeachingDiagramEvidenceItem],
) -> TeachingDiagramSkeleton | None:
    useful = [item for item in file_analysis if item.get("file_type") in {"dataset", "training", "model", "entry"}]
    if len(useful) < 2:
        return None
    source = TeachingDiagramSourceEntity(entity_type="data_flow", entity_id="data_flow:project", title="项目数据流概览")
    modules: list[TeachingDiagramModule] = []
    connections: list[TeachingDiagramConnection] = []
    evidence_refs: list[str] = []
    for item in sorted(useful, key=lambda row: {"entry": 0, "dataset": 1, "model": 2, "training": 3}.get(row.get("file_type"), 9))[:4]:
        evidence_id = _add_evidence(
            catalog, "file_analysis", f"file:{_safe_id(item.get('file_path', 'file'))}",
            f"{item.get('file_path')} 被规则识别为 {item.get('file_type')}。",
            file_path=item.get("file_path"), confidence=item.get("confidence", "medium"),
        )
        evidence_refs.append(evidence_id)
        modules.append(TeachingDiagramModule(
            id=f"file_{len(modules) + 1}", label=str(item.get("file_path")), kind="module",
            section_id="project_data_flow", role=item.get("file_type"), evidence_refs=[evidence_id],
        ))
    for first, second in zip(modules, modules[1:]):
        connections.append(TeachingDiagramConnection(
            id=f"edge_{first.id}_{second.id}", source_module_id=first.id, target_module_id=second.id,
            label="项目结构顺序", evidence_refs=[*first.evidence_refs, *second.evidence_refs],
        ))
    sections = [TeachingDiagramSection(id="project_data_flow", title="项目数据流", module_ids=[item.id for item in modules], evidence_refs=evidence_refs)]
    return _finalize_skeleton(source, diagram_ids_by_type.get("project_structure", []), sections, modules, connections, [], [], evidence_refs)


def _finalize_skeleton(
    source: TeachingDiagramSourceEntity,
    related_mermaid_diagram_ids: list[str],
    sections: list[TeachingDiagramSection],
    modules: list[TeachingDiagramModule],
    connections: list[TeachingDiagramConnection],
    shapes: list[TeachingDiagramShape],
    formulas: list[TeachingDiagramFormula],
    evidence_refs: list[str],
) -> TeachingDiagramSkeleton:
    module_ids = {item.id for item in modules}
    section_ids = {item.id for item in sections}
    sections = [
        item.model_copy(update={"module_ids": [module.id for module in modules if module.section_id == item.id]})
        for item in sections
    ]
    warnings = []
    if not related_mermaid_diagram_ids:
        warnings.append("未找到可直接映射的 Mermaid 图，Blueprint 仍按规则事实生成。")
    if any(item.section_id and item.section_id not in section_ids for item in modules):
        warnings.append("存在未映射分区的模块。")
    if any(connection.source_module_id not in module_ids or connection.target_module_id not in module_ids for connection in connections):
        raise ValueError("Illegal teaching diagram connection.")
    legend = [
        TeachingDiagramLegendItem(label="输入", color="#dbeafe", meaning="进入该流程的数据或参数"),
        TeachingDiagramLegendItem(label="计算", color="#dcfce7", meaning="规则识别到的层、函数或操作"),
        TeachingDiagramLegendItem(label="输出", color="#fef3c7", meaning="模型或函数返回的结果"),
    ]
    payload = {
        "source_entity": source.model_dump(),
        "related_mermaid_diagram_ids": related_mermaid_diagram_ids,
        "sections": [item.model_dump() for item in sections],
        "modules": [item.model_dump() for item in modules],
        "connections": [item.model_dump() for item in connections],
        "shapes": [item.model_dump() for item in shapes],
        "formulas": [item.model_dump() for item in formulas],
        "schema_version": SCHEMA_VERSION,
    }
    skeleton_hash = _hash(payload)
    skeleton_id = f"td_{_hash({'source': source.model_dump(), 'skeleton_hash': skeleton_hash, 'schema_version': SCHEMA_VERSION})[:20]}"
    return TeachingDiagramSkeleton(
        skeleton_id=skeleton_id,
        source_entity=source,
        related_mermaid_diagram_ids=related_mermaid_diagram_ids,
        sections=sections,
        modules=modules,
        inputs=[item.id for item in modules if item.kind == "input"],
        outputs=[item.id for item in modules if item.kind == "output"],
        connections=connections,
        shapes=shapes,
        formulas=formulas,
        legend_items=legend,
        evidence_refs=sorted(set(evidence_refs)),
        warnings=warnings,
        skeleton_hash=skeleton_hash,
    )


def _add_evidence(
    catalog: dict[str, TeachingDiagramEvidenceItem],
    evidence_type: str,
    evidence_id: str,
    fact_summary: str,
    *,
    file_path: str | None = None,
    class_name: str | None = None,
    function_name: str | None = None,
    qualified_name: str | None = None,
    line_no: int | None = None,
    diagram_id: str | None = None,
    confidence: str = "medium",
) -> str:
    stable_id = evidence_id[:220]
    catalog[stable_id] = TeachingDiagramEvidenceItem(
        evidence_id=stable_id,
        evidence_type=evidence_type,  # type: ignore[arg-type]
        fact_summary=fact_summary[:1000],
        file_path=file_path,
        class_name=class_name,
        function_name=function_name,
        qualified_name=qualified_name,
        line_no=line_no,
        diagram_id=diagram_id,
        confidence=confidence if confidence in {"high", "medium", "low"} else "medium",  # type: ignore[arg-type]
    )
    return stable_id


def _diagram_ids_by_type(diagrams: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for diagram in diagrams:
        grouped.setdefault(str(diagram.get("diagram_type") or "unknown"), []).append(str(diagram.get("id") or ""))
    return {key: [item for item in value if item] for key, value in grouped.items()}


def _hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "item")).strip("_")
    return text[:80] or "item"
