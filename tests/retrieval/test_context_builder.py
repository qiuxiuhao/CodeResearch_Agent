from __future__ import annotations

from backend.app.retrieval.context_builder import ContextBuilder, conservative_code_token_count
from backend.app.retrieval.schemas import RetrievalCandidate, RetrievalScore


def _candidate(chunk_id: str, text: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id, entity_id=f"entity-{chunk_id}", repo_id="repo", index_version_id="idx",
        entity_kind="code", entity_type="function", chunk_type="function", path=f"{chunk_id}.py",
        qualified_name=f"module.{chunk_id}", start_line=1, end_line=text.count("\n") + 1,
        text=text, content_hash=f"hash-{chunk_id}",
        score=RetrievalScore(final_rrf=score, final=score), sources=["sparse"],
    )


def test_code_token_estimate_is_conservative() -> None:
    assert conservative_code_token_count("中文测试") == 4
    assert conservative_code_token_count("abcdefghij") == 4
    assert conservative_code_token_count("x = tensor[:, :]") >= 6


def test_single_context_item_does_not_monopolize_budget() -> None:
    long_text = "\n".join(f"value_{index} = tensor[{index}]" for index in range(200))
    bundle = ContextBuilder().build(
        repo_id="repo", index_version_id="idx", query_id="query", query_text="value_50",
        candidates=[_candidate("long", long_text, 1.0), _candidate("short", "return value", 0.5)],
        token_budget=100, max_entities=8,
    )
    assert bundle.items[0].token_count <= 40
    assert bundle.estimated_tokens <= 100


def test_provider_validation_reduces_context_deterministically() -> None:
    bundle = ContextBuilder().build(
        repo_id="repo", index_version_id="idx", query_id="query", query_text="value",
        candidates=[_candidate("a", "return value_a", 1.0), _candidate("b", "return value_b", 0.5)],
        token_budget=100, max_entities=8,
    )
    validated = ContextBuilder().validate_provider_budget(
        bundle,
        prompt_token_counter=lambda items: 20 + 20 * len(items),
        provider_context_limit=55,
        reserved_output_tokens=10,
    )
    assert [item.chunk_ids for item in validated.items] == [["a"]]
    assert validated.provider_validated_tokens == 40
    assert "b" in validated.omitted_candidate_ids
    assert validated.items[0].evidence[0].path == "a.py"
