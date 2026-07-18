from __future__ import annotations

from backend.app.llm.config import LLMSettings
from backend.app.llm.providers.mock_provider import MockProvider
from backend.app.llm.runtime import create_llm_runtime
from backend.app.retrieval.schemas import ContextBundle, ContextItem, RetrievalEvidence
from backend.app.services.research_answer_generator import ProviderAnswerGenerator


def test_provider_answer_generator_uses_fixed_structured_call(tmp_path) -> None:
    provider = MockProvider("deepseek", responses={
        "research_answer": {
            "answer": "forward 返回输入。",
            "claims": [{
                "claim_id": "claim-1",
                "text": "forward 返回输入。",
                "citation_ids": ["citation-1"],
                "supported": True,
            }],
            "citations": [{
                "citation_id": "citation-1",
                "context_id": "ctx-1",
                "evidence_id": "ev-1",
                "entity_id": "entity-1",
                "path": "model.py",
                "start_line": 1,
                "end_line": 2,
            }],
            "unsupported_claims": [],
            "confidence": 0.9,
        }
    })
    settings = LLMSettings.from_env("hybrid").model_copy(update={
        "cache_path": str(tmp_path / "llm-cache.sqlite3"),
    })
    generator = ProviderAnswerGenerator(create_llm_runtime(settings, [provider]).router)
    context = ContextBundle(
        repo_id="repo",
        index_version_id="idx",
        query_id="query",
        items=[ContextItem(
            context_id="ctx-1",
            entity_id="entity-1",
            chunk_ids=["chunk-1"],
            title="model.forward",
            text="def forward(x):\n    return x",
            token_count=12,
            truncated=False,
            rank=1,
            evidence=[RetrievalEvidence(
                evidence_id="ev-1",
                source_type="code",
                path="model.py",
                start_line=1,
                end_line=2,
            )],
        )],
        estimated_tokens=12,
        token_count_method="conservative_code_estimate",
        token_budget=100,
    )
    answer = generator.generate(query="forward 做什么？", context=context)
    assert answer.citations[0].evidence_id == "ev-1"
    assert provider.calls[0].task_type == "research_answer"
    assert provider.calls[0].input_payload["contexts"][0]["context_id"] == "ctx-1"
