from __future__ import annotations

from backend.app.persistence.fts_generation_store import FTSGenerationStore, FTS_PROFILE_VERSION
from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.schemas import RawRetrievalHit, RetrievalFilter


class SparseRetriever:
    def __init__(self, read_store: RetrievalReadStore, fts_store: FTSGenerationStore) -> None:
        self.read_store = read_store
        self.fts_store = fts_store

    def sync(self, filters: RetrievalFilter, *, profile_hash: str = FTS_PROFILE_VERSION) -> tuple[str, bool]:
        documents = self.read_store.list_documents(filters)
        return self.fts_store.sync(
            repo_id=filters.repo_id,
            index_version_id=filters.index_version_id,
            profile_hash=profile_hash,
            documents=documents,
        )

    def retrieve(
        self,
        *,
        query_text: str,
        filters: RetrievalFilter,
        top_k: int,
        profile_hash: str = FTS_PROFILE_VERSION,
    ) -> list[RawRetrievalHit]:
        return self.fts_store.search(
            query_text=query_text,
            filters=filters,
            profile_hash=profile_hash,
            top_k=top_k,
        )
