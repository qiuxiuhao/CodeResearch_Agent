from __future__ import annotations

from backend.app.llm.evidence import make_evidence
from backend.app.llm.node_support import run_selected_entities
from backend.app.llm.runtime import LLMRuntime
from backend.app.llm.selection import select_models
from backend.app.schemas.llm_explanation import ModelLLMExplanation
from backend.app.schemas.state import AgentState


def model_explain_llm_node(state: AgentState, llm_runtime: LLMRuntime | None = None) -> AgentState:
    limit = llm_runtime.settings.max_model_explanations if llm_runtime else 0
    selected, skipped = select_models(state.get("model_analysis", []), limit)

    def prepare(item: dict):
        path = str(item.get("file_path", ""))
        class_name = str(item.get("class_name", ""))
        evidence = [make_evidence(
            f"rule:model:{path}:{class_name}:summary", "model_rule", str(item.get("summary", "模型规则分析")),
            file_path=path, class_name=class_name, start_line=item.get("start_line"), end_line=item.get("end_line"),
            rule_field="model_analysis.summary", confidence=item.get("confidence", "medium"),
        )]
        payload = {"model_analysis": item, "instruction": "解释模型结构、数据流、模块职责和学习重点，不推断未知 shape。"}
        return f"{path}:{class_name}", payload, evidence

    return run_selected_entities(
        state=state, runtime=llm_runtime, task_type="model_explain", output_field="model_llm_explanations",
        prompt_file="model_explain_llm.md", selected=selected, skipped=skipped,
        response_model=ModelLLMExplanation, prepare=prepare,
    )
