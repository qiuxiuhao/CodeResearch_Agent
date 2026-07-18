from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence
from uuid import UUID, uuid5

from backend.app.retrieval.embedder import Embedder, VectorProfile
from backend.app.retrieval.schemas import RetrievalDocument
from backend.app.retrieval.sparse_vector import SparseVectorProvider
from backend.app.retrieval.vector_store import VectorPoint, VectorStore, resolve_collection_name


CRA_RETRIEVAL_NAMESPACE = UUID("6589941c-eef8-5b6c-8dc0-f4660ef84e84")


@dataclass(frozen=True, slots=True)
class VectorGenerationManifest:
    generation_id: str
    status: str
    repo_id: str
    index_version_id: str
    vector_profile_hash: str
    collection_name: str
    point_count: int
    created_at: str
    activated_at: str | None = None
    error_code: str | None = None


def vector_point_id(
    *, vector_profile_hash: str, repo_id: str, index_version_id: str, chunk_id: str
) -> str:
    return str(uuid5(
        CRA_RETRIEVAL_NAMESPACE,
        f"{vector_profile_hash}:{repo_id}:{index_version_id}:{chunk_id}",
    ))


class VectorSyncService:
    def __init__(
        self,
        *,
        vector_store: VectorStore,
        embedder: Embedder,
        profile: VectorProfile,
        manifest_root: str | Path,
        sparse_provider: SparseVectorProvider | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.profile = profile
        self.manifest_root = Path(manifest_root)
        self.sparse_provider = sparse_provider

    def sync(
        self,
        *,
        repo_id: str,
        index_version_id: str,
        documents: Sequence[RetrievalDocument],
    ) -> VectorGenerationManifest:
        if self.embedder.dimension != self.profile.dimension:
            raise ValueError("Embedder and vector profile dimensions differ.")
        generation_id = _generation_id(repo_id, index_version_id, self.profile.profile_hash, documents)
        existing = self._read_manifest(repo_id, index_version_id, generation_id)
        if existing and existing.status == "ready":
            return existing
        profiles = self._known_collection_profiles()
        collection_name = resolve_collection_name(self.profile.profile_hash, profiles)
        self.vector_store.ensure_collection(
            collection_name,
            profile_hash=self.profile.profile_hash,
            dimension=self.profile.dimension,
            sparse_vector_name="sparse_bm25_v1" if self.sparse_provider else None,
        )
        if self.vector_store.collection_profile_hash(collection_name) != self.profile.profile_hash:
            raise ValueError("Collection full profile hash validation failed.")
        building = VectorGenerationManifest(
            generation_id=generation_id, status="building", repo_id=repo_id,
            index_version_id=index_version_id, vector_profile_hash=self.profile.profile_hash,
            collection_name=collection_name, point_count=0, created_at=_now(),
        )
        self._write_manifest(building)
        try:
            vectors = self.embedder.embed([item.text for item in documents])
            if len(vectors) != len(documents):
                raise ValueError("Embedder returned an unexpected vector count.")
            sparse_vectors = self.sparse_provider.embed([item.text for item in documents]) if self.sparse_provider else None
            if sparse_vectors is not None and len(sparse_vectors) != len(documents):
                raise ValueError("Sparse provider returned an unexpected vector count.")
            points = [
                VectorPoint(
                    point_id=vector_point_id(
                        vector_profile_hash=self.profile.profile_hash,
                        repo_id=repo_id,
                        index_version_id=index_version_id,
                        chunk_id=document.chunk_id,
                    ),
                    vector=vector,
                    payload=_payload(document, self.profile.profile_hash),
                    sparse_vectors=(
                        {"sparse_bm25_v1": sparse_vectors[index]} if sparse_vectors is not None else {}
                    ),
                )
                for index, (document, vector) in enumerate(zip(documents, vectors, strict=True))
            ]
            self.vector_store.upsert(collection_name, points)
            point_count = self.vector_store.count(collection_name, filters=_scope(
                repo_id, index_version_id, self.profile.profile_hash
            ))
            if point_count != len(documents):
                raise ValueError(f"Vector point count mismatch: expected {len(documents)}, got {point_count}.")
            ready = VectorGenerationManifest(
                generation_id=generation_id, status="ready", repo_id=repo_id,
                index_version_id=index_version_id, vector_profile_hash=self.profile.profile_hash,
                collection_name=collection_name, point_count=point_count,
                created_at=building.created_at, activated_at=_now(),
            )
            self._write_manifest(ready)
            return ready
        except Exception as exc:
            failed = VectorGenerationManifest(
                generation_id=generation_id, status="failed", repo_id=repo_id,
                index_version_id=index_version_id, vector_profile_hash=self.profile.profile_hash,
                collection_name=collection_name, point_count=0, created_at=building.created_at,
                error_code=getattr(exc, "error_code", "vector_sync_failed"),
            )
            self._write_manifest(failed)
            raise

    def delete_version(self, *, repo_id: str, index_version_id: str) -> None:
        root = self.manifest_root / repo_id / index_version_id
        if not root.exists():
            return
        for path in root.glob("*.json"):
            manifest = VectorGenerationManifest(**json.loads(path.read_text(encoding="utf-8")))
            self.vector_store.delete(
                manifest.collection_name,
                filters=_scope(repo_id, index_version_id, manifest.vector_profile_hash),
            )
            path.unlink()

    def _known_collection_profiles(self) -> dict[str, str]:
        profiles: dict[str, str] = {}
        if not self.manifest_root.exists():
            return profiles
        for path in self.manifest_root.glob("*/*/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                profiles[payload["collection_name"]] = payload["vector_profile_hash"]
            except (KeyError, json.JSONDecodeError):
                continue
        return profiles

    def _manifest_path(self, repo_id: str, index_version_id: str, generation_id: str) -> Path:
        return self.manifest_root / repo_id / index_version_id / f"{generation_id}.json"

    def _read_manifest(
        self, repo_id: str, index_version_id: str, generation_id: str
    ) -> VectorGenerationManifest | None:
        path = self._manifest_path(repo_id, index_version_id, generation_id)
        if not path.exists():
            return None
        return VectorGenerationManifest(**json.loads(path.read_text(encoding="utf-8")))

    def _write_manifest(self, manifest: VectorGenerationManifest) -> None:
        path = self._manifest_path(manifest.repo_id, manifest.index_version_id, manifest.generation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)


def _generation_id(
    repo_id: str,
    index_version_id: str,
    profile_hash: str,
    documents: Sequence[RetrievalDocument],
) -> str:
    chunks = [(item.chunk_id, item.content_hash) for item in sorted(documents, key=lambda item: item.chunk_id)]
    canonical = json.dumps(chunks, sort_keys=True, separators=(",", ":"))
    value = f"vector:v1\0{profile_hash}\0{repo_id}\0{index_version_id}\0{canonical}"
    return "vec_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload(document: RetrievalDocument, profile_hash: str) -> dict[str, object]:
    return {
        "vector_profile_hash": profile_hash,
        "repo_id": document.repo_id,
        "index_version_id": document.index_version_id,
        "chunk_id": document.chunk_id,
        "entity_id": document.entity_id,
        "entity_kind": document.entity_kind,
        "entity_type": document.entity_type,
        "chunk_type": document.chunk_type,
        "path": document.path or "",
        "qualified_name": document.qualified_name or "",
        "parent_entity_id": document.parent_entity_id or "",
        "content_hash": document.content_hash,
        "ordinal": document.ordinal,
        "start_line": document.start_line or 0,
        "end_line": document.end_line or 0,
        "index_schema_version": "1.4.0",
    }


def _scope(repo_id: str, index_version_id: str, profile_hash: str) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "index_version_id": index_version_id,
        "vector_profile_hash": profile_hash,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
