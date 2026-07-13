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
    report_text = report.report_md + _llm_report_section(llm_payload)
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
    if state.get("analysis_mode", "rule") == "rule":
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
    if payload["status"] in {"disabled", "skipped", "failed"}:
        lines.extend(["", "当前任务保留并展示完整的规则分析结果。"])
    return "\n".join(lines) + "\n"
