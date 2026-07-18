from __future__ import annotations

from backend.app.retrieval.query_profiler import RuleBasedQueryProfiler


def test_query_profiler_prioritizes_exact_symbol_and_explicit_type() -> None:
    profiler = RuleBasedQueryProfiler()
    assert profiler.classify("models.SimpleNet.forward")[0] == "symbol_lookup"
    assert profiler.classify("models.SimpleNet.forward", explicit="call_chain") == ("call_chain", "explicit")


def test_query_profile_reranker_weights_are_valid() -> None:
    config = RuleBasedQueryProfiler().config(
        "implementation_explanation", dense_enabled=True, reranker_enabled=True
    )
    assert config.hybrid_weight == 0.35
    assert config.reranker_weight == 0.65
    assert config.source_weights["graph"] == 0.8
