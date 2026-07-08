from __future__ import annotations

from collections.abc import Callable

from backend.app.agents.nodes.code_parse_node import code_parse_node
from backend.app.agents.nodes.report_generate_node import report_generate_node
from backend.app.agents.nodes.repo_scan_node import repo_scan_node
from backend.app.agents.nodes.unzip_node import unzip_node
from backend.app.schemas.state import AgentState


def build_analysis_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _SequentialGraph([unzip_node, repo_scan_node, code_parse_node, report_generate_node])

    workflow = StateGraph(AgentState)
    workflow.add_node("unzip", unzip_node)
    workflow.add_node("repo_scan", repo_scan_node)
    workflow.add_node("code_parse", code_parse_node)
    workflow.add_node("report_generate", report_generate_node)

    workflow.add_edge(START, "unzip")
    workflow.add_edge("unzip", "repo_scan")
    workflow.add_edge("repo_scan", "code_parse")
    workflow.add_edge("code_parse", "report_generate")
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

