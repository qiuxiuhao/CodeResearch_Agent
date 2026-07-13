from __future__ import annotations

from collections.abc import Callable
from functools import partial

from backend.app.agents.nodes.code_parse_node import code_parse_node
from backend.app.agents.nodes.diagram_generate_node import diagram_generate_node
from backend.app.agents.nodes.file_analyze_node import file_analyze_node
from backend.app.agents.nodes.file_explain_llm_node import file_explain_llm_node
from backend.app.agents.nodes.function_analyze_node import function_analyze_node
from backend.app.agents.nodes.function_explain_llm_node import function_explain_llm_node
from backend.app.agents.nodes.library_call_extract_node import library_call_extract_node
from backend.app.agents.nodes.library_function_doc_node import library_function_doc_node
from backend.app.agents.nodes.model_analyze_node import model_analyze_node
from backend.app.agents.nodes.model_explain_llm_node import model_explain_llm_node
from backend.app.agents.nodes.paper_analyze_node import paper_analyze_node
from backend.app.agents.nodes.paper_code_align_node import paper_code_align_node
from backend.app.agents.nodes.paper_code_align_llm_node import paper_code_align_llm_node
from backend.app.agents.nodes.report_generate_node import report_generate_node
from backend.app.agents.nodes.repo_scan_node import repo_scan_node
from backend.app.agents.nodes.unzip_node import unzip_node
from backend.app.schemas.state import AgentState
from backend.app.llm.runtime import LLMRuntime


def build_analysis_graph(llm_runtime: LLMRuntime | None = None):
    file_llm = partial(file_explain_llm_node, llm_runtime=llm_runtime)
    function_llm = partial(function_explain_llm_node, llm_runtime=llm_runtime)
    model_llm = partial(model_explain_llm_node, llm_runtime=llm_runtime)
    paper_llm = partial(paper_code_align_llm_node, llm_runtime=llm_runtime)
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _SequentialGraph([
            unzip_node,
            repo_scan_node,
            code_parse_node,
            file_analyze_node,
            library_call_extract_node,
            function_analyze_node,
            model_analyze_node,
            paper_analyze_node,
            paper_code_align_node,
            file_llm,
            function_llm,
            model_llm,
            paper_llm,
            diagram_generate_node,
            library_function_doc_node,
            report_generate_node,
        ])

    workflow = StateGraph(AgentState)
    workflow.add_node("unzip", unzip_node)
    workflow.add_node("repo_scan", repo_scan_node)
    workflow.add_node("code_parse", code_parse_node)
    workflow.add_node("file_analyze", file_analyze_node)
    workflow.add_node("library_call_extract", library_call_extract_node)
    workflow.add_node("function_analyze", function_analyze_node)
    workflow.add_node("model_analyze", model_analyze_node)
    workflow.add_node("paper_analyze", paper_analyze_node)
    workflow.add_node("paper_code_align", paper_code_align_node)
    workflow.add_node("file_explain_llm", file_llm)
    workflow.add_node("function_explain_llm", function_llm)
    workflow.add_node("model_explain_llm", model_llm)
    workflow.add_node("paper_code_align_llm", paper_llm)
    workflow.add_node("diagram_generate", diagram_generate_node)
    workflow.add_node("library_function_doc", library_function_doc_node)
    workflow.add_node("report_generate", report_generate_node)

    workflow.add_edge(START, "unzip")
    workflow.add_edge("unzip", "repo_scan")
    workflow.add_edge("repo_scan", "code_parse")
    workflow.add_edge("code_parse", "file_analyze")
    workflow.add_edge("file_analyze", "library_call_extract")
    workflow.add_edge("library_call_extract", "function_analyze")
    workflow.add_edge("function_analyze", "model_analyze")
    workflow.add_edge("model_analyze", "paper_analyze")
    workflow.add_edge("paper_analyze", "paper_code_align")
    workflow.add_edge("paper_code_align", "file_explain_llm")
    workflow.add_edge("file_explain_llm", "function_explain_llm")
    workflow.add_edge("function_explain_llm", "model_explain_llm")
    workflow.add_edge("model_explain_llm", "paper_code_align_llm")
    workflow.add_edge("paper_code_align_llm", "diagram_generate")
    workflow.add_edge("diagram_generate", "library_function_doc")
    workflow.add_edge("library_function_doc", "report_generate")
    workflow.add_edge("report_generate", END)
    return workflow.compile()


class _SequentialGraph:
    def __init__(self, nodes: list[Callable[[AgentState], AgentState]]) -> None:
        self._nodes = nodes

    def invoke(self, state: AgentState) -> AgentState:
        current = state
        for node in self._nodes:
            current = node(current)
        return current
