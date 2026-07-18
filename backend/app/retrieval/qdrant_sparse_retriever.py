from __future__ import annotations

from backend.app.retrieval.embedder import VectorProfile
from backend.app.retrieval.schemas import RawRetrievalHit, RetrievalFilter
from backend.app.retrieval.sparse_vector import SparseVectorProvider
from backend.app.retrieval.vector_store import VectorStore


class QdrantSparseRetriever:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        sparse_provider: SparseVectorProvider,
        profile: VectorProfile,
        collection_name: str,
    ) -> None:
        self.vector_store = vector_store
        self.sparse_provider = sparse_provider
        self.profile = profile
        self.collection_name = collection_name

    def retrieve(self, *, query_text: str, filters: RetrievalFilter, top_k: int) -> list[RawRetrievalHit]:
        vector = self.sparse_provider.embed([query_text])[0]
        hits = self.vector_store.search_sparse(
            self.collection_name,
            "sparse_bm25_v1",
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
                source="sparse", chunk_id=str(hit.payload["chunk_id"]),
                entity_id=str(hit.payload["entity_id"]), source_score=hit.score,
                source_rank=rank, metadata={"point_id": hit.point_id, "sparse_backend": "qdrant_bm25"},
            )
            for rank, hit in enumerate(hits, 1)
        ]
