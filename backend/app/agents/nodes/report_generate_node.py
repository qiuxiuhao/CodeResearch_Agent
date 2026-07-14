from __future__ import annotations

from pathlib import Path

from backend.app.schemas.state import AgentState
from backend.app.tools.report_tool import generate_report
from backend.app.utils.json_utils import save_json


def report_generate_node(state: AgentState) -> AgentState:
    output_dir = Path(state["output_dir"])
    repo_index = state.get("repo_index", {})
    parsed_files = state.get("parsed_files", [])
    functions = state.get("functions", [])
    classes = state.get("classes", [])
    file_analysis = state.get("file_analysis", [])
    library_calls = state.get("library_calls", [])
    low_confidence_library_calls = state.get("low_confidence_library_calls", [])
    function_analysis = state.get("function_analysis", [])
    model_analysis = state.get("model_analysis", [])
    paper_analysis = state.get("paper_analysis", {})
    paper_code_alignment = state.get("paper_code_alignment", {})
    diagrams = state.get("diagrams", [])
    diagram_warnings = state.get("diagram_warnings", [])
    library_function_docs = state.get("library_function_docs", [])
    new_library_functions = state.get("new_library_functions", [])
    skipped_low_confidence_library_calls = state.get("skipped_low_confidence_library_calls", [])
    errors = state.get("errors", [])
    llm_payload = {
        "analysis_mode": state.get("analysis_mode", "rule"),
        "external_model_consent": state.get("external_model_consent", False),
        "text_llm_enabled": state.get("text_llm_enabled", False),
        "external_text_consent": state.get("external_text_consent", False),
        "status": _llm_status(state),
        "budget": state.get("llm_budget", {}),
        "usage": _llm_usage(state),
        "selected_entities": state.get("llm_budget", {}).get("entities_by_type", {}),
        "skipped_entities": state.get("llm_skipped_entities", []),
        "evidence_catalog": state.get("llm_evidence_catalog", []),
        "function_explanations": state.get("function_llm_explanations", []),
        "file_explanations": state.get("file_llm_explanations", []),
        "model_explanations": state.get("model_llm_explanations", []),
        "paper_code_alignment_explanations": state.get("paper_code_align_llm_explanations", []),
        "warnings": state.get("llm_warnings", []),
    }

    save_json(output_dir / "repo_index.json", repo_index)
    save_json(
        output_dir / "parsed_files.json",
        {
            "parsed_files": parsed_files,
            "classes": classes,
            "functions": functions,
            "errors": errors,
        },
    )
    save_json(output_dir / "llm_explanations.json", llm_payload)
    figure_payload = state.get("paper_figure_analysis", {})
    save_json(output_dir / "paper_figure_analysis.json", figure_payload)
    teaching_payload = state.get("teaching_diagram_manifest", {})
    save_json(output_dir / "file_analysis.json", {"file_analysis": file_analysis, "errors": errors})
    save_json(
        output_dir / "library_calls.json",
        {
            "library_calls": library_calls,
            "low_confidence_library_calls": low_confidence_library_calls,
            "errors": errors,
        },
    )
    save_json(output_dir / "function_analysis.json", {"function_analysis": function_analysis, "errors": errors})
    save_json(output_dir / "model_analysis.json", {"model_analysis": model_analysis, "errors": errors})
    save_json(output_dir / "paper_analysis.json", {"paper_analysis": paper_analysis, "errors": errors})
    save_json(
        output_dir / "paper_code_alignment.json",
        {"paper_code_alignment": paper_code_alignment, "errors": errors},
    )
    save_json(output_dir / "diagrams.json", {"diagrams": diagrams, "warnings": diagram_warnings, "errors": errors})
    save_json(
        output_dir / "library_function_docs.json",
        {
            "library_function_docs": library_function_docs,
            "new_library_functions": new_library_functions,
            "skipped_low_confidence_calls": skipped_low_confidence_library_calls,
            "errors": errors,
        },
    )
    report = generate_report(
        output_dir,
        repo_index,
        parsed_files,
        functions,
        classes,
        errors,
        file_analysis,
        function_analysis,
        model_analysis,
        paper_analysis,
        paper_code_alignment,
        diagrams,
        diagram_warnings,
        library_calls,
        library_function_docs,
        skipped_low_confidence_library_calls,
    )
    report_text = (
        report.report_md
        + _llm_report_section(llm_payload)
        + _vision_report_section(figure_payload)
        + _teaching_diagram_report_section(teaching_payload)
    )
    (output_dir / "report.md").write_text(report_text, encoding="utf-8")
    return {**state, "report_md": report_text}


def _all_explanations(state: AgentState) -> list[dict]:
    return [
        *state.get("file_llm_explanations", []), *state.get("function_llm_explanations", []),
        *state.get("model_llm_explanations", []), *state.get("paper_code_align_llm_explanations", []),
    ]


def _llm_usage(state: AgentState) -> dict:
    metadata = [item.get("metadata") or {} for item in _all_explanations(state)]
    return {
        "input_tokens": sum(item.get("input_tokens") or 0 for item in metadata),
        "output_tokens": sum(item.get("output_tokens") or 0 for item in metadata),
        "total_tokens": sum(item.get("total_tokens") or 0 for item in metadata),
        "cache_hits": sum(1 for item in metadata if item.get("cache_hit")),
    }


def _llm_status(state: AgentState) -> str:
    if not state.get("text_llm_enabled", state.get("analysis_mode", "rule") == "hybrid"):
        return "disabled"
    explanations = _all_explanations(state)
    selected = state.get("llm_budget", {}).get("selected_entities", 0)
    if explanations and len(explanations) < selected:
        return "partial"
    if explanations:
        return "success"
    if any(item.get("code") == "llm_provider_unconfigured" for item in state.get("llm_warnings", [])):
        return "skipped"
    return "failed" if state.get("llm_warnings") else "skipped"


def _llm_report_section(payload: dict) -> str:
    lines = ["", "## AI 增强解释", "", f"- 模式：{payload['analysis_mode']}", f"- 状态：{payload['status']}"]
    budget = payload.get("budget", {})
    lines.append(f"- 逻辑实体：{budget.get('selected_entities', 0)} / {budget.get('max_total_entities', 0)}")
    lines.append(f"- Provider 请求：{budget.get('sent_provider_requests', 0)} / {budget.get('max_provider_requests', 0)}")
    groups = (
        ("文件解释", payload.get("file_explanations", []), "file_path"),
        ("函数解释", payload.get("function_explanations", []), "qualified_name"),
        ("模型解释", payload.get("model_explanations", []), "class_name"),
        ("论文代码对齐解释", payload.get("paper_code_alignment_explanations", []), "contribution_title"),
    )
    for title, items, key in groups:
        if not items:
            continue
        lines.extend(["", f"### {title}", ""])
        for item in items:
            summary = item.get("summary") or item.get("alignment_summary") or item.get("teaching_explanation", "")
            lines.extend([f"#### {item.get(key, '未命名')}", "", str(summary), ""])
            if item.get("evidence_refs"):
                lines.append("证据引用：" + ", ".join(item["evidence_refs"]))
            for link in item.get("possible_code_links", []):
                lines.append(
                    f"- AI 建议关联：Figure `{link.get('figure_id')}` → "
                    f"{', '.join(link.get('code_evidence_refs', []))} "
                    f"({link.get('confidence', 'low')}, suggested=true)"
                )
    if payload["status"] in {"disabled", "skipped", "failed"}:
        lines.extend(["", "当前任务保留并展示完整的规则分析结果。"])
    return "\n".join(lines) + "\n"


def _vision_report_section(payload: dict) -> str:
    lines = [
        "", "## 论文 Figure 理解", "",
        f"- VLM 开启：{payload.get('vision_vlm_enabled', False)}",
        f"- 外部图片授权：{payload.get('external_vision_consent', False)}",
        f"- 本地提取状态：{payload.get('extraction_status', 'not_applicable')}",
        f"- VLM 状态：{payload.get('vision_status', 'disabled')}",
    ]
    budget = payload.get("budget", {})
    lines.append(f"- Figure 实体：{budget.get('selected_entities', 0)} / {budget.get('max_total_entities', 0)}")
    lines.append(f"- Provider 请求：{budget.get('sent_provider_requests', 0)} / {budget.get('max_provider_requests', 0)}")
    for figure in payload.get("figures", []):
        caption = figure.get("caption", {})
        lines.extend([
            "", f"### {caption.get('label', figure.get('figure_id', 'Figure'))}", "",
            f"- 页码：{figure.get('page_number')}",
            f"- 图注：{caption.get('text', '')}",
        ])
        preview = figure.get("canonical_preview") or {}
        if preview.get("path"):
            lines.append(f"- Canonical preview：`{preview['path']}`")
        analysis = figure.get("vlm_analysis") or {}
        if analysis:
            metadata = analysis.get("metadata") or {}
            module_labels = "；".join(item.get("name", "") for item in analysis.get("modules", [])) or "无"
            flow_labels = "；".join(
                f"{item.get('source', '')} → {item.get('target', '')}" for item in analysis.get("flows", [])
            ) or "无"
            lines.extend([
                f"- Figure 类型：{analysis.get('figure_type', 'other')}",
                f"- AI 摘要：{analysis.get('summary', '')}",
                f"- 模块：{module_labels}",
                f"- 流程：{flow_labels}",
                f"- 输入：{'、'.join(analysis.get('inputs', [])) or '无'}",
                f"- 输出：{'、'.join(analysis.get('outputs', [])) or '无'}",
                f"- Provider：{metadata.get('provider') or '无'} / {metadata.get('model') or '无'}",
                f"- 缓存命中：{metadata.get('cache_hit', False)}；tokens：{metadata.get('total_tokens')}",
            ])
            if analysis.get("uncertainties"):
                lines.append("- 不确定性：" + "；".join(analysis["uncertainties"]))
            if analysis.get("contribution_candidates"):
                labels = [f"{item.get('contribution_id')}（候选）" for item in analysis["contribution_candidates"]]
                lines.append("- 论文贡献候选：" + "、".join(labels))
    if not payload.get("figures"):
        lines.extend(["", "未提取到可展示的论文 Figure；原论文文本解析和规则代码对齐不受影响。"])
    return "\n".join(lines) + "\n"


def _teaching_diagram_report_section(payload: dict) -> str:
    lines = [
        "", "## 教学图", "",
        f"- 状态：{payload.get('status', 'disabled')}",
        f"- 本地教学图开启：{payload.get('teaching_diagrams_enabled', False)}",
        f"- AI 图片生成开启：{payload.get('image_generation_enabled', False)}",
        f"- 图片外发授权：{payload.get('external_image_consent', False)}",
        f"- 教学图审查开启：{payload.get('teaching_review_vlm_enabled', False)}",
        f"- 视觉审查授权：{payload.get('external_vision_consent', False)}",
    ]
    budget = payload.get("budget", {})
    if budget:
        image_budget = budget.get("teaching_image", {})
        review_budget = budget.get("teaching_review", {})
        lines.append(
            f"- 图片 Provider 请求：{image_budget.get('sent_provider_requests', 0)} / "
            f"{image_budget.get('max_provider_requests', 0)}"
        )
        lines.append(
            f"- 审查 Provider 请求：{review_budget.get('sent_provider_requests', 0)} / "
            f"{review_budget.get('max_provider_requests', 0)}"
        )
    diagrams = payload.get("diagrams", [])
    if not diagrams:
        lines.append("")
        lines.append("未生成教学图；Mermaid 图和规则分析结果不受影响。")
        return "\n".join(lines) + "\n"
    for item in diagrams:
        lines.extend(["", f"### {item.get('title', item.get('diagram_id', '教学图'))}", ""])
        if item.get("related_mermaid_diagram_ids"):
            lines.append("- 对应 Mermaid：" + "、".join(item["related_mermaid_diagram_ids"]))
        if item.get("blueprint_png", {}).get("path"):
            lines.append(f"- Blueprint PNG：`{item['blueprint_png']['path']}`")
        if item.get("styled_composite", {}).get("path"):
            lines.append(f"- styled_composite：`{item['styled_composite']['path']}`")
        if item.get("final_asset", {}).get("path"):
            lines.append(f"- final：`{item['final_asset']['path']}`")
        lines.append(f"- 当前展示：{item.get('display_variant', 'blueprint')}")
        if item.get("fallback_reason"):
            lines.append(f"- 回退原因：{item['fallback_reason']}")
        review = item.get("review") or {}
        if review:
            lines.append(f"- 审查分数：{review.get('overall_score')}；通过：{review.get('passed')}")
    lines.extend(["", "AI 教学示意图可能做视觉简化，请以规则分析和本地 Blueprint 为准。"])
    return "\n".join(lines) + "\n"
