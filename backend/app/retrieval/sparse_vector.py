from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class SparseVectorData:
    indices: list[int]
    values: list[float]


class SparseVectorProvider(Protocol):
    model_id: str
    model_version: str

    def embed(self, texts: Sequence[str]) -> list[SparseVectorData]: ...


@dataclass(slots=True)
class FakeSparseVectorProvider:
    model_id: str = "fake-bm25"
    model_version: str = "1"

    def embed(self, texts: Sequence[str]) -> list[SparseVectorData]:
        return [_fake_sparse(text) for text in texts]


class QdrantBM25SparseProvider:
    def __init__(
        self, *, cache_dir: str, offline: bool = True,
        providers: list[str] | None = None,
        specific_model_path: str | None = None,
    ) -> None:
        self.model_id = "Qdrant/bm25"
        self.model_version = "v1"
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as exc:
            raise RuntimeError("Install the optional 'retrieval' dependencies to use Qdrant BM25.") from exc
        options = {
            "model_name": self.model_id, "cache_dir": cache_dir,
            "local_files_only": offline,
        }
        if specific_model_path is not None:
            options["specific_model_path"] = specific_model_path
        if providers is not None:
            options["providers"] = providers
        self._model = SparseTextEmbedding(**options)

    def embed(self, texts: Sequence[str]) -> list[SparseVectorData]:
        vectors = list(self._model.embed(list(texts)))
        return [
            SparseVectorData(indices=[int(value) for value in vector.indices], values=[float(value) for value in vector.values])
            for vector in vectors
        ]


def _fake_sparse(text: str) -> SparseVectorData:
    counts: dict[int, float] = {}
    for term in re.findall(r"[A-Za-z_][\w.]*|[\u3400-\u9fff]+", text.casefold()):
        index = int.from_bytes(hashlib.sha256(term.encode("utf-8")).digest()[:4], "big")
        counts[index] = counts.get(index, 0.0) + 1.0
    ordered = sorted(counts.items())
    return SparseVectorData(indices=[item[0] for item in ordered], values=[item[1] for item in ordered])
