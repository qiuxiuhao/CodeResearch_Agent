from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .schemas import FusedRetrievalCandidate
from .sparse_vector import SparseVectorData


class InferenceBackend(Protocol):
    def embed_dense(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_sparse(self, texts: Sequence[str]) -> list[SparseVectorData]: ...
    def rerank(self, query: str, texts: Sequence[str]) -> list[float]: ...
    def health(self) -> dict[str, object]: ...


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DenseRequest(StrictPayload):
    texts: list[str] = Field(min_length=1, max_length=256)


class DenseResponse(StrictPayload):
    vectors: list[list[float]]


class SparseRequest(DenseRequest):
    pass


class SparseItem(StrictPayload):
    indices: list[int]
    values: list[float]


class SparseResponse(StrictPayload):
    vectors: list[SparseItem]


class RerankRequest(StrictPayload):
    query: str = Field(min_length=1, max_length=16_384)
    texts: list[str] = Field(min_length=1, max_length=256)


class RerankResponse(StrictPayload):
    scores: list[float]


class UnixSocketInferenceClient:
    def __init__(self, socket_path: str | Path, *, timeout_seconds: float = 120) -> None:
        self.socket_path = Path(socket_path)
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        self._client = httpx.Client(
            transport=transport, base_url="http://cra-inference", timeout=timeout_seconds,
        )

    def embed_dense(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._post("/v1/embed/dense", DenseRequest(texts=list(texts)))
        return DenseResponse.model_validate(response).vectors

    def embed_sparse(self, texts: Sequence[str]) -> list[SparseVectorData]:
        response = SparseResponse.model_validate(
            self._post("/v1/embed/sparse", SparseRequest(texts=list(texts)))
        )
        return [SparseVectorData(indices=item.indices, values=item.values) for item in response.vectors]

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        response = self._post("/v1/rerank", RerankRequest(query=query, texts=list(texts)))
        return RerankResponse.model_validate(response).scores

    def health(self) -> dict[str, object]:
        response = self._client.get("/health")
        response.raise_for_status()
        return dict(response.json())

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, payload: BaseModel) -> object:
        response = self._client.post(path, json=payload.model_dump(mode="json"))
        response.raise_for_status()
        return response.json()


@dataclass(slots=True)
class RemoteEmbedder:
    client: UnixSocketInferenceClient
    model_id: str
    model_revision: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.client.embed_dense(texts)
        if any(len(item) != self.dimension for item in vectors):
            raise RuntimeError("inference_dimension_mismatch")
        return vectors


@dataclass(slots=True)
class RemoteSparseProvider:
    client: UnixSocketInferenceClient
    model_id: str = "Qdrant/bm25"
    model_version: str = "v1"

    def embed(self, texts: Sequence[str]) -> list[SparseVectorData]:
        return self.client.embed_sparse(texts)


class RemoteReranker:
    def __init__(self, client: UnixSocketInferenceClient) -> None:
        self.client = client

    def score(self, query_text: str, candidates: Sequence[FusedRetrievalCandidate]):
        from .reranker import _candidate_text

        texts = [str(_candidate_text(candidate)) for candidate in candidates]
        scores = self.client.rerank(query_text, texts)
        if len(scores) != len(candidates):
            raise RuntimeError("inference_rerank_count_mismatch")
        return {candidate.chunk_id: float(score) for candidate, score in zip(candidates, scores, strict=True)}
