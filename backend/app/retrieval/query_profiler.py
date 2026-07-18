from __future__ import annotations

import re

from backend.app.retrieval.schemas import QueryType, RetrievalConfig


_PROFILE_RULES: list[tuple[QueryType, re.Pattern[str]]] = [
    ("call_chain", re.compile(r"调用链|谁调用|调用了谁|call\s*(chain|path|graph)|caller|callee", re.I)),
    ("paper_alignment", re.compile(r"论文|paper|figure|公式|贡献|对齐|alignment", re.I)),
    ("training_process", re.compile(r"训练|train(?:ing)?|loss|optimizer|backward", re.I)),
    ("inference_process", re.compile(r"推理|inference|predict|decode|generation", re.I)),
    ("configuration", re.compile(r"配置|config|yaml|toml|参数设置", re.I)),
    ("tensor_shape", re.compile(r"shape|tensor|维度|尺寸|input_dim|output_dim", re.I)),
    ("architecture", re.compile(r"架构|结构|architecture|模块|继承|数据流", re.I)),
    ("implementation_explanation", re.compile(r"如何实现|实现原理|解释|explain|implementation|怎么做", re.I)),
]


class RuleBasedQueryProfiler:
    def classify(self, text: str, explicit: QueryType | None = None) -> tuple[QueryType, str]:
        if explicit:
            return explicit, "explicit"
        stripped = text.strip()
        if _looks_like_symbol(stripped):
            return "symbol_lookup", "exact_symbol_or_path"
        for profile, pattern in _PROFILE_RULES:
            if pattern.search(stripped):
                return profile, f"rule:{profile}"
        return "general_repository", "fallback"

    def config(
        self,
        profile: QueryType,
        *,
        dense_enabled: bool,
        reranker_enabled: bool,
    ) -> RetrievalConfig:
        values = _PROFILE_CONFIG[profile]
        hybrid_weight, reranker_weight = values["final_weights"] if reranker_enabled else (1.0, 0.0)
        return RetrievalConfig(
            profile=profile,
            dense_enabled=dense_enabled,
            graph_enabled=values["hops"] > 0,
            reranker_enabled=reranker_enabled,
            dense_top_k=values["dense_top_k"],
            sparse_top_k=values["sparse_top_k"],
            graph_max_hops=values["hops"],
            source_weights=values["source_weights"],
            graph_edge_weights={edge: 1.0 for edge in values["edges"]},
            hybrid_weight=hybrid_weight,
            reranker_weight=reranker_weight,
        )


_PROFILE_CONFIG: dict[QueryType, dict] = {
    "symbol_lookup": dict(dense_top_k=15, sparse_top_k=40, hops=1, edges=("DEFINES", "CONTAINS"),
                          source_weights={"dense": 0.5, "sparse": 1.5, "graph": 0.5}, final_weights=(0.7, 0.3)),
    "implementation_explanation": dict(dense_top_k=30, sparse_top_k=30, hops=1,
        edges=("DEFINES", "CONTAINS", "CALLS", "INSTANTIATES"),
        source_weights={"dense": 1.0, "sparse": 1.0, "graph": 0.8}, final_weights=(0.35, 0.65)),
    "call_chain": dict(dense_top_k=20, sparse_top_k=30, hops=2,
        edges=("CALLS", "INSTANTIATES", "DEFINES"),
        source_weights={"dense": 0.6, "sparse": 1.0, "graph": 1.6}, final_weights=(0.5, 0.5)),
    "architecture": dict(dense_top_k=30, sparse_top_k=20, hops=2,
        edges=("CONTAINS", "DEFINES", "INHERITS", "INSTANTIATES", "IMPORTS"),
        source_weights={"dense": 1.0, "sparse": 0.7, "graph": 1.5}, final_weights=(0.5, 0.5)),
    "tensor_shape": dict(dense_top_k=30, sparse_top_k=30, hops=1,
        edges=("CALLS", "CONTAINS", "DEFINES"),
        source_weights={"dense": 1.1, "sparse": 1.0, "graph": 0.8}, final_weights=(0.4, 0.6)),
    "configuration": dict(dense_top_k=15, sparse_top_k=40, hops=1,
        edges=("CONTAINS", "DEFINES", "IMPORTS"),
        source_weights={"dense": 0.6, "sparse": 1.5, "graph": 0.7}, final_weights=(0.7, 0.3)),
    "training_process": dict(dense_top_k=30, sparse_top_k=25, hops=2,
        edges=("CALLS", "INSTANTIATES", "CONTAINS", "DEFINES"),
        source_weights={"dense": 1.0, "sparse": 0.8, "graph": 1.4}, final_weights=(0.5, 0.5)),
    "inference_process": dict(dense_top_k=30, sparse_top_k=25, hops=2,
        edges=("CALLS", "INSTANTIATES", "CONTAINS", "DEFINES"),
        source_weights={"dense": 1.0, "sparse": 0.8, "graph": 1.4}, final_weights=(0.5, 0.5)),
    "paper_alignment": dict(dense_top_k=35, sparse_top_k=25, hops=2,
        edges=("ALIGNS_WITH", "CONTAINS", "DEFINES"),
        source_weights={"dense": 1.2, "sparse": 0.8, "graph": 1.5}, final_weights=(0.4, 0.6)),
    "general_repository": dict(dense_top_k=30, sparse_top_k=30, hops=1,
        edges=("CONTAINS", "DEFINES", "IMPORTS", "CALLS"),
        source_weights={"dense": 1.0, "sparse": 1.0, "graph": 0.8}, final_weights=(0.5, 0.5)),
}


def _looks_like_symbol(text: str) -> bool:
    if "/" in text or "\\" in text or text.endswith(".py"):
        return True
    return bool(re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+", text))
