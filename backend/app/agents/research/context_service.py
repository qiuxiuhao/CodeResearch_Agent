from __future__ import annotations

from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.context_builder import ContextBuilder
from backend.app.retrieval.schemas import RetrievalCandidate, RetrievalScore


class ResearchContextService:
    def __init__(self, read_store: RetrievalReadStore, builder: ContextBuilder | None = None) -> None:
        self.read_store = read_store
        self.builder = builder or ContextBuilder()

    def build(
        self,
        *,
        run_id: str,
        repo_id: str,
        index_version_id: str,
        query: str,
        chunk_ids: list[str],
        entity_ids: list[str],
        edge_notes: list[str],
        token_budget: int = 6_000,
        max_entities: int = 8,
    ):
        documents = self.read_store.documents_by_chunk_ids(
            repo_id=repo_id,
            index_version_id=index_version_id,
            chunk_ids=chunk_ids,
        )
        if len(documents) < len(set(chunk_ids)) and entity_ids:
            chunks = self.read_store.chunks_for_entities(
                repo_id=repo_id,
                index_version_id=index_version_id,
                entity_ids=entity_ids,
            )
            missing_entities = [entity for entity in entity_ids if not any(
                item.entity_id == entity for item in documents.values()
            )]
            fallback_ids = [items[0].id for entity in missing_entities for items in [chunks.get(entity, [])] if items]
            documents.update(self.read_store.documents_by_chunk_ids(
                repo_id=repo_id,
                index_version_id=index_version_id,
                chunk_ids=fallback_ids,
            ))
        ordered = [documents[item] for item in chunk_ids if item in documents]
        ordered.extend(item for key, item in sorted(documents.items()) if item not in ordered)
        evidence = self.read_store.evidence_for_entities(
            index_version_id=index_version_id,
            entity_ids=[item.entity_id for item in ordered],
        )
        candidates = [
            RetrievalCandidate(
                **item.model_dump(),
                score=RetrievalScore(final_rrf=1.0 / rank, final=1.0 / rank),
                sources=["graph"],
                evidence=evidence.get(item.entity_id, []),
            )
            for rank, item in enumerate(ordered, 1)
        ]
        notes = {entity_id: edge_notes for entity_id in entity_ids}
        return self.builder.build(
            repo_id=repo_id,
            index_version_id=index_version_id,
            query_id=run_id,
            query_text=query,
            candidates=candidates,
            token_budget=token_budget,
            max_entities=max_entities,
            relationship_notes=notes,
        )
