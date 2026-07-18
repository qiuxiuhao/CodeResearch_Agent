from __future__ import annotations

from backend.app.retrieval.embedder import Embedder, VectorProfile
from backend.app.retrieval.schemas import RawRetrievalHit, RetrievalFilter
from backend.app.retrieval.vector_store import VectorStore


class DenseRetriever:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedder: Embedder,
        profile: VectorProfile,
        collection_name: str,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.profile = profile
        self.collection_name = collection_name

    def retrieve(self, *, query_text: str, filters: RetrievalFilter, top_k: int) -> list[RawRetrievalHit]:
        vector = self.embedder.embed([query_text])[0]
        hits = self.vector_store.search(
            self.collection_name,
            vector,
            filters={
                "repo_id": filters.repo_id,
                "index_version_id": filters.index_version_id,
                "vector_profile_hash": self.profile.profile_hash,
            },
            top_k=top_k,
        )
        return [
            RawRetrievalHit(
                source="dense", chunk_id=str(hit.payload["chunk_id"]),
                entity_id=str(hit.payload["entity_id"]), source_score=hit.score,
                source_rank=rank, metadata={"point_id": hit.point_id},
            )
            for rank, hit in enumerate(hits, 1)
        ]
