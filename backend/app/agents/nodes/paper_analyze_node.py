from __future__ import annotations

from backend.app.schemas.state import AgentState
from backend.app.tools.paper_parse_tool import empty_paper_analysis, parse_paper_pdf


def paper_analyze_node(state: AgentState) -> AgentState:
    paper_pdf_path = state.get("paper_pdf_path")
    if not paper_pdf_path:
        return {
            **state,
            "paper_analysis": empty_paper_analysis().model_dump(),
        }

    analysis = parse_paper_pdf(paper_pdf_path)
    return {
        **state,
        "paper_analysis": analysis.model_dump(),
        "errors": [*state.get("errors", []), *analysis.errors],
    }
