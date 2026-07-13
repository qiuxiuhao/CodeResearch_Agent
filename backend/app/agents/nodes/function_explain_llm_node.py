from __future__ import annotations

from backend.app.llm.evidence import make_evidence
from backend.app.llm.node_support import run_selected_entities
from backend.app.llm.runtime import LLMRuntime
from backend.app.llm.selection import select_functions
from backend.app.schemas.llm_explanation import FunctionLLMExplanation
from backend.app.schemas.state import AgentState


def function_explain_llm_node(state: AgentState, llm_runtime: LLMRuntime | None = None) -> AgentState:
    limit = llm_runtime.settings.max_function_explanations if llm_runtime else 0
    selected, skipped = select_functions(state.get("function_analysis", []), state.get("functions", []), limit)
    raw_by_name = {_qualified(item): item for item in state.get("functions", [])}

    def prepare(item: dict):
        qualified = str(item.get("qualified_name", ""))
        path = str(item.get("file_path", ""))
        evidence = [make_evidence(
            f"function:{path}:{qualified}:{item.get('start_line') or 0}-{item.get('end_line') or 0}",
            "function_rule", str(item.get("purpose", "函数规则分析")), file_path=path,
            class_name=item.get("class_name"), function_name=item.get("function_name"),
            start_line=item.get("start_line"), end_line=item.get("end_line"),
            rule_field="function_analysis.purpose", confidence=item.get("confidence", "medium"),
        )]
        related_models = [model for model in state.get("model_analysis", []) if model.get("file_path") == path]
        payload = {
            "function_analysis": item,
            "source": raw_by_name.get(qualified, {}).get("source_code", ""),
            "model_context": related_models,
            "instruction": "解释函数逻辑、输入输出和它在模型或项目中的位置。",
        }
        return qualified, payload, evidence

    return run_selected_entities(
        state=state, runtime=llm_runtime, task_type="function_explain", output_field="function_llm_explanations",
        prompt_file="function_explain_llm.md", selected=selected, skipped=skipped,
        response_model=FunctionLLMExplanation, prepare=prepare,
    )


def _qualified(item: dict) -> str:
    return f"{item['class_name']}.{item['function_name']}" if item.get("class_name") else str(item.get("function_name", ""))
