from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.agents.research.schemas import ResearchRoute
from backend.app.retrieval.query_profiler import RuleBasedQueryProfiler
from backend.app.retrieval.schemas import QueryType


_COMPLEX_PATTERN = re.compile(
    r"调用链|调用路径|从.+到|架构|训练流程|推理流程|论文|对齐|比较|为什么|"
    r"call\s*(chain|path)|architecture|training\s+process|inference\s+process|paper|align|compare",
    re.I,
)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: ResearchRoute
    query_type: QueryType
    reasons: list[str]


class RuleBasedResearchRouter:
    def __init__(self) -> None:
        self.profiler = RuleBasedQueryProfiler()

    def route(self, query: str, explicit_type: QueryType | None = None) -> RouteDecision:
        query_type, rule = self.profiler.classify(query, explicit_type)
        complex_type = query_type in {
            "call_chain",
            "architecture",
            "training_process",
            "inference_process",
            "paper_alignment",
            "general_repository",
        }
        matched = bool(_COMPLEX_PATTERN.search(query))
        route: ResearchRoute = "planned" if complex_type or matched else "direct"
        reasons = [f"query_profile:{rule}", f"query_type:{query_type}"]
        reasons.append("complex_query_feature" if route == "planned" else "single_evidence_target")
        return RouteDecision(route, query_type, reasons)
