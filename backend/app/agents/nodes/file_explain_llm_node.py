from __future__ import annotations

from backend.app.llm.evidence import make_evidence
from backend.app.llm.node_support import run_selected_entities
from backend.app.llm.runtime import LLMRuntime
from backend.app.llm.selection import select_files
from backend.app.schemas.llm_explanation import FileLLMExplanation
from backend.app.schemas.state import AgentState


def file_explain_llm_node(state: AgentState, llm_runtime: LLMRuntime | None = None) -> AgentState:
    limit = llm_runtime.settings.max_file_explanations if llm_runtime else 0
    selected, skipped = select_files(state.get("file_analysis", []), limit)
    parsed = {item.get("file_path"): item for item in state.get("parsed_files", [])}

    def prepare(item: dict):
        path = str(item.get("file_path", ""))
        evidence = [make_evidence(
            f"file:{path}", "file_rule", str(item.get("purpose", "文件规则分析")), file_path=path,
            rule_field="file_analysis.purpose", confidence=item.get("confidence", "medium"),
        )]
        parsed_item = parsed.get(path, {})
        structure = {
            "file_path": path,
            "imports": parsed_item.get("imports", []),
            "classes": parsed_item.get("classes", []),
            "functions": [
                {key: fn.get(key) for key in ("function_name", "class_name", "args", "start_line", "end_line")}
                for fn in parsed_item.get("functions", [])
            ],
        }
        payload = {"file_analysis": item, "parsed_structure": structure, "instruction": "解释文件职责、架构位置和阅读顺序。"}
        return path, payload, evidence

    return run_selected_entities(
        state=state, runtime=llm_runtime, task_type="file_explain", output_field="file_llm_explanations",
        prompt_file="file_explain_llm.md", selected=selected, skipped=skipped,
        response_model=FileLLMExplanation, prepare=prepare,
    )
