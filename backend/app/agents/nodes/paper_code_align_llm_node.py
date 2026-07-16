from __future__ import annotations

import hashlib

from backend.app.llm.evidence import make_evidence
from backend.app.llm.node_support import run_selected_entities
from backend.app.llm.paper_code_link_validator import PaperCodeLinkValidator
from backend.app.llm.runtime import LLMRuntime
from backend.app.llm.selection import select_alignments
from backend.app.schemas.llm_explanation import PaperCodeAlignLLMExplanation
from backend.app.schemas.state import AgentState


def paper_code_align_llm_node(state: AgentState, llm_runtime: LLMRuntime | None = None) -> AgentState:
    if not state.get("paper_analysis", {}).get("paper_provided"):
        return {**state, "paper_code_align_llm_explanations": []}
    items = state.get("paper_code_alignment", {}).get("alignment_items", [])
    limit = llm_runtime.settings.max_paper_alignments if llm_runtime else 0
    selected, skipped = select_alignments(items, limit)
    contributions = {item.get("id"): item for item in state.get("paper_analysis", {}).get("contributions", [])}
    figure_analyses = [
        item.get("vlm_analysis") for item in state.get("paper_figure_analysis", {}).get("figures", [])
        if item.get("vlm_analysis")
    ]

    def prepare(item: dict):
        contribution_id = str(item.get("contribution_id", ""))
        evidence = [make_evidence(
            f"alignment:{contribution_id}:rule", "paper_alignment_rule", str(item.get("reason", "论文代码规则对齐")),
            rule_field="paper_code_alignment.reason", confidence=item.get("confidence", "low"),
        )]
        for target in item.get("matched_targets", []):
            evidence.append(make_evidence(
                _target_evidence_id(contribution_id, target), "paper_code_target",
                f"规则对齐目标 {target.get('target_type')}:{target.get('name')}",
                file_path=target.get("file_path"), function_name=target.get("qualified_name"),
                start_line=target.get("line_no"), rule_field="paper_code_alignment.matched_targets",
                confidence=item.get("confidence", "low"),
            ))
        code_evidence = [entry for entry in evidence if entry.evidence_type == "paper_code_target"]
        related_figures = [
            figure for figure in figure_analyses
            if any(candidate.get("contribution_id") == contribution_id for candidate in figure.get("contribution_candidates", []))
        ]
        for figure in related_figures:
            evidence.append(make_evidence(
                f"figure:{figure.get('figure_id')}:analysis", "paper_figure_analysis",
                str(figure.get("summary") or "已校验的 Figure 分析"),
                rule_field="paper_figure_analysis.vlm_analysis", confidence="medium",
            ))
        payload = {
            "contribution": contributions.get(contribution_id, {}),
            "rule_alignment": item,
            "figure_analyses": related_figures,
            "code_evidence_catalog": [entry.model_dump(mode="json") for entry in code_evidence],
            "instruction": (
                "解释规则对齐证据，不得改变 targets、status 或 confidence。possible_code_links 只能作为建议，"
                "且只能引用 code_evidence_catalog 中已有 ID；不得新增代码目标。"
            ),
        }
        validator = PaperCodeLinkValidator(
            contribution_id=contribution_id,
            allowed_figure_ids=[str(figure.get("figure_id")) for figure in related_figures],
            code_evidence_catalog=code_evidence,
        )
        return contribution_id, payload, evidence, validator.validate

    return run_selected_entities(
        state=state, runtime=llm_runtime, task_type="paper_code_align", output_field="paper_code_align_llm_explanations",
        prompt_key="paper_code_align", selected=selected, skipped=skipped,
        response_model=PaperCodeAlignLLMExplanation, prepare=prepare,
    )


def _target_evidence_id(contribution_id: str, target: dict) -> str:
    identity = ":".join(str(target.get(key) or "") for key in ("file_path", "qualified_name", "name", "line_no"))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"alignment:{contribution_id}:target:{digest}"
