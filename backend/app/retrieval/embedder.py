from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


class Embedder(Protocol):
    model_id: str
    model_revision: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(slots=True)
class FakeEmbedder:
    dimension: int = 8
    model_id: str = "fake-embedder"
    model_revision: str = "1"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [_fake_vector(text, self.dimension) for text in texts]


class FastEmbedEmbedder:
    def __init__(
        self,
        *,
        model_id: str,
        model_revision: str,
        dimension: int,
        cache_dir: str | Path,
        offline: bool = True,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision
        self.dimension = dimension
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("Install the optional 'retrieval' dependencies to use FastEmbed.") from exc
        self._model = TextEmbedding(
            model_name=model_id,
            cache_dir=str(cache_dir),
            local_files_only=offline,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [list(vector) for vector in self._model.embed(list(texts))]
        if any(len(vector) != self.dimension for vector in vectors):
            raise ValueError("Embedding dimension does not match the vector profile.")
        return vectors


@dataclass(frozen=True, slots=True)
class VectorProfile:
    model_id: str
    model_revision: str
    dimension: int
    distance: str = "cosine"
    embedder_version: str = "fastembed-v1"
    preprocessing_version: str = "symbol-chunk-v1"
    chunk_schema_version: str = "1.4.0"
    sparse_model_id: str | None = None
    sparse_model_version: str | None = None

    @property
    def profile_hash(self) -> str:
        payload = json.dumps(
            {
                "chunk_schema_version": self.chunk_schema_version,
                "dimension": self.dimension,
                "distance": self.distance,
                "embedder_version": self.embedder_version,
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "preprocessing_version": self.preprocessing_version,
                "sparse_model_id": self.sparse_model_id,
                "sparse_model_version": self.sparse_model_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fake_vector(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dimension)]
    magnitude = sum(value * value for value in raw) ** 0.5 or 1.0
    return [value / magnitude for value in raw]
