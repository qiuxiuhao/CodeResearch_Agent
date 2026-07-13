from __future__ import annotations

from backend.app.llm.evidence import make_evidence
from backend.app.llm.node_support import run_selected_entities
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

    def prepare(item: dict):
        contribution_id = str(item.get("contribution_id", ""))
        evidence = [make_evidence(
            f"alignment:{contribution_id}:rule", "paper_alignment_rule", str(item.get("reason", "论文代码规则对齐")),
            rule_field="paper_code_alignment.reason", confidence=item.get("confidence", "low"),
        )]
        payload = {
            "contribution": contributions.get(contribution_id, {}),
            "rule_alignment": item,
            "instruction": "解释规则对齐证据，不得改变 targets、status 或 confidence。",
        }
        return contribution_id, payload, evidence

    return run_selected_entities(
        state=state, runtime=llm_runtime, task_type="paper_code_align", output_field="paper_code_align_llm_explanations",
        prompt_file="paper_code_align_llm.md", selected=selected, skipped=skipped,
        response_model=PaperCodeAlignLLMExplanation, prepare=prepare,
    )
