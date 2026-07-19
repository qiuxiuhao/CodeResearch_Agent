from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from backend.app.retrieval.sparse_vector import SparseVectorData


@dataclass(frozen=True, slots=True)
class VectorPoint:
    point_id: str
    vector: list[float]
    payload: dict[str, object]
    sparse_vectors: dict[str, SparseVectorData] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    point_id: str
    score: float
    payload: dict[str, object]


class VectorStore(Protocol):
    def ensure_collection(
        self, collection_name: str, *, profile_hash: str, dimension: int,
        sparse_vector_name: str | None = None,
    ) -> None: ...
    def collection_profile_hash(self, collection_name: str) -> str | None: ...
    def upsert(self, collection_name: str, points: Sequence[VectorPoint]) -> None: ...
    def search(
        self, collection_name: str, vector: Sequence[float], *, filters: dict[str, object], top_k: int
    ) -> list[VectorSearchHit]: ...
    def delete(self, collection_name: str, *, filters: dict[str, object]) -> None: ...
    def count(self, collection_name: str, *, filters: dict[str, object]) -> int: ...
    def search_sparse(
        self, collection_name: str, vector_name: str, vector: SparseVectorData,
        *, filters: dict[str, object], top_k: int,
    ) -> list[VectorSearchHit]: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class _MemoryCollection:
    profile_hash: str
    dimension: int
    points: dict[str, VectorPoint] = field(default_factory=dict)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.collections: dict[str, _MemoryCollection] = {}

    def ensure_collection(
        self, collection_name: str, *, profile_hash: str, dimension: int,
        sparse_vector_name: str | None = None,
    ) -> None:
        existing = self.collections.get(collection_name)
        if existing is None:
            self.collections[collection_name] = _MemoryCollection(profile_hash, dimension)
            return
        if existing.profile_hash != profile_hash or existing.dimension != dimension:
            raise ValueError("Existing collection profile does not match the requested profile.")

    def collection_profile_hash(self, collection_name: str) -> str | None:
        collection = self.collections.get(collection_name)
        return collection.profile_hash if collection else None

    def upsert(self, collection_name: str, points: Sequence[VectorPoint]) -> None:
        collection = self.collections[collection_name]
        for point in points:
            if len(point.vector) != collection.dimension:
                raise ValueError("Vector dimension mismatch.")
            collection.points[point.point_id] = point

    def search(
        self, collection_name: str, vector: Sequence[float], *, filters: dict[str, object], top_k: int
    ) -> list[VectorSearchHit]:
        collection = self.collections[collection_name]
        hits = [
            VectorSearchHit(point.point_id, _cosine(vector, point.vector), point.payload)
            for point in collection.points.values()
            if _matches(point.payload, filters)
        ]
        return sorted(hits, key=lambda hit: (-hit.score, hit.point_id))[:top_k]

    def delete(self, collection_name: str, *, filters: dict[str, object]) -> None:
        collection = self.collections.get(collection_name)
        if collection is None:
            return
        for point_id in [
            point_id for point_id, point in collection.points.items() if _matches(point.payload, filters)
        ]:
            del collection.points[point_id]

    def count(self, collection_name: str, *, filters: dict[str, object]) -> int:
        collection = self.collections.get(collection_name)
        if collection is None:
            return 0
        return sum(_matches(point.payload, filters) for point in collection.points.values())

    def search_sparse(
        self, collection_name: str, vector_name: str, vector: SparseVectorData,
        *, filters: dict[str, object], top_k: int,
    ) -> list[VectorSearchHit]:
        query = dict(zip(vector.indices, vector.values, strict=True))
        hits = []
        for point in self.collections[collection_name].points.values():
            stored = point.sparse_vectors.get(vector_name)
            if stored is None or not _matches(point.payload, filters):
                continue
            score = sum(query.get(index, 0.0) * value for index, value in zip(stored.indices, stored.values, strict=True))
            hits.append(VectorSearchHit(point.point_id, score, point.payload))
        return sorted(hits, key=lambda hit: (-hit.score, hit.point_id))[:top_k]

    def close(self) -> None:
        return None


class QdrantLocalVectorStore:
    """Optional Qdrant adapter; importing this module never downloads a model."""

    def __init__(self, path: str | Path) -> None:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("Install the optional 'retrieval' dependencies to use Qdrant.") from exc
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(self.path))
        self._registry_path = self.path / ".cra_collection_profiles.json"

    def ensure_collection(
        self, collection_name: str, *, profile_hash: str, dimension: int,
        sparse_vector_name: str | None = None,
    ) -> None:
        from qdrant_client.models import Distance, SparseVectorParams, VectorParams

        registry = self._registry()
        existing_hash = registry.get(collection_name)
        if existing_hash is not None and existing_hash != profile_hash:
            raise ValueError("Existing Qdrant collection profile hash does not match.")
        if not self._client.collection_exists(collection_name):
            create_kwargs = dict(
                collection_name=collection_name,
                vectors_config={"dense": VectorParams(size=dimension, distance=Distance.COSINE)},
            )
            if sparse_vector_name:
                create_kwargs["sparse_vectors_config"] = {
                    sparse_vector_name: SparseVectorParams()
                }
            self._client.create_collection(**create_kwargs)
        registry[collection_name] = profile_hash
        self._write_registry(registry)

    def collection_profile_hash(self, collection_name: str) -> str | None:
        return self._registry().get(collection_name)

    def upsert(self, collection_name: str, points: Sequence[VectorPoint]) -> None:
        from qdrant_client.models import PointStruct, SparseVector

        self._client.upsert(
            collection_name=collection_name,
            points=[PointStruct(
                id=point.point_id,
                vector={
                    "dense": point.vector,
                    **{
                        name: SparseVector(indices=value.indices, values=value.values)
                        for name, value in point.sparse_vectors.items()
                    },
                },
                payload=point.payload,
            ) for point in points],
            wait=True,
        )

    def search(
        self, collection_name: str, vector: Sequence[float], *, filters: dict[str, object], top_k: int
    ) -> list[VectorSearchHit]:
        result = self._client.query_points(
            collection_name=collection_name,
            query=list(vector),
            using="dense",
            query_filter=_qdrant_filter(filters),
            limit=top_k,
        )
        return [VectorSearchHit(str(item.id), float(item.score), dict(item.payload or {})) for item in result.points]

    def delete(self, collection_name: str, *, filters: dict[str, object]) -> None:
        from qdrant_client.models import FilterSelector

        self._client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=_qdrant_filter(filters)),
            wait=True,
        )

    def count(self, collection_name: str, *, filters: dict[str, object]) -> int:
        return int(self._client.count(
            collection_name=collection_name, count_filter=_qdrant_filter(filters), exact=True
        ).count)

    def search_sparse(
        self, collection_name: str, vector_name: str, vector: SparseVectorData,
        *, filters: dict[str, object], top_k: int,
    ) -> list[VectorSearchHit]:
        from qdrant_client.models import SparseVector

        result = self._client.query_points(
            collection_name=collection_name,
            query=SparseVector(indices=vector.indices, values=vector.values),
            using=vector_name,
            query_filter=_qdrant_filter(filters),
            limit=top_k,
        )
        return [VectorSearchHit(str(item.id), float(item.score), dict(item.payload or {})) for item in result.points]

    def _registry(self) -> dict[str, str]:
        if not self._registry_path.exists():
            return {}
        return json.loads(self._registry_path.read_text(encoding="utf-8"))

    def _write_registry(self, value: dict[str, str]) -> None:
        temporary = self._registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self._registry_path)

    def close(self) -> None:
        self._client.close()


def resolve_collection_name(profile_hash: str, existing_profiles: dict[str, str]) -> str:
    for length in (12, 16, 24, 32, 64):
        name = f"cra_chunks_v1_{profile_hash[:length]}"
        existing = existing_profiles.get(name)
        if existing is None or existing == profile_hash:
            return name
    raise ValueError("Unable to resolve a collision-free collection name.")


def _matches(payload: dict[str, object], filters: dict[str, object]) -> bool:
    return all(payload.get(key) == value for key, value in filters.items())


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def _qdrant_filter(filters: dict[str, object]):
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[FieldCondition(key=key, match=MatchValue(value=value)) for key, value in filters.items()])
