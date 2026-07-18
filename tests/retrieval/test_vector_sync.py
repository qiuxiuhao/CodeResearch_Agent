from __future__ import annotations

from backend.app.retrieval.embedder import FakeEmbedder, VectorProfile
from backend.app.retrieval.schemas import RetrievalDocument
from backend.app.retrieval.sync_service import VectorSyncService, vector_point_id
from backend.app.retrieval.sparse_vector import FakeSparseVectorProvider
from backend.app.retrieval.vector_store import InMemoryVectorStore, resolve_collection_name


def _document(repo: str, version: str, chunk_id: str = "chunk-stable") -> RetrievalDocument:
    return RetrievalDocument(
        chunk_id=chunk_id, entity_id="entity-1", repo_id=repo, index_version_id=version,
        entity_kind="code", entity_type="function", chunk_type="function",
        path="model.py", qualified_name="model.forward", text="def forward(x): return x",
        content_hash="content-1",
    )


def _service(tmp_path, store: InMemoryVectorStore, profile: VectorProfile | None = None):
    profile = profile or VectorProfile(model_id="fake", model_revision="1", dimension=8)
    return VectorSyncService(
        vector_store=store,
        embedder=FakeEmbedder(dimension=profile.dimension),
        profile=profile,
        manifest_root=tmp_path / "manifests",
    )


def test_same_chunk_id_across_versions_does_not_overwrite(tmp_path) -> None:
    store = InMemoryVectorStore()
    service = _service(tmp_path, store)
    first = service.sync(repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")])
    second = service.sync(repo_id="repo-a", index_version_id="idx-2", documents=[_document("repo-a", "idx-2")])
    assert first.collection_name == second.collection_name
    assert store.count(first.collection_name, filters={"repo_id": "repo-a"}) == 2
    assert vector_point_id(
        vector_profile_hash=service.profile.profile_hash, repo_id="repo-a",
        index_version_id="idx-1", chunk_id="chunk-stable",
    ) != vector_point_id(
        vector_profile_hash=service.profile.profile_hash, repo_id="repo-a",
        index_version_id="idx-2", chunk_id="chunk-stable",
    )


def test_same_chunk_id_across_repositories_isolated(tmp_path) -> None:
    store = InMemoryVectorStore()
    service = _service(tmp_path, store)
    first = service.sync(repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")])
    service.sync(repo_id="repo-b", index_version_id="idx-1", documents=[_document("repo-b", "idx-1")])
    assert store.count(first.collection_name, filters={"repo_id": "repo-a"}) == 1
    assert store.count(first.collection_name, filters={"repo_id": "repo-b"}) == 1


def test_delete_one_version_keeps_other_versions(tmp_path) -> None:
    store = InMemoryVectorStore()
    service = _service(tmp_path, store)
    first = service.sync(repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")])
    service.sync(repo_id="repo-a", index_version_id="idx-2", documents=[_document("repo-a", "idx-2")])
    service.delete_version(repo_id="repo-a", index_version_id="idx-1")
    assert store.count(first.collection_name, filters={"repo_id": "repo-a", "index_version_id": "idx-1"}) == 0
    assert store.count(first.collection_name, filters={"repo_id": "repo-a", "index_version_id": "idx-2"}) == 1


def test_repeated_vector_sync_is_idempotent(tmp_path) -> None:
    store = InMemoryVectorStore()
    service = _service(tmp_path, store)
    first = service.sync(repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")])
    second = service.sync(repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")])
    assert first == second
    assert store.count(first.collection_name, filters={"repo_id": "repo-a", "index_version_id": "idx-1"}) == 1


def test_collection_short_hash_collision_is_detected() -> None:
    first = "a" * 12 + "b" * 52
    second = "a" * 12 + "c" * 52
    short_name = f"cra_chunks_v1_{first[:12]}"
    resolved = resolve_collection_name(second, {short_name: first})
    assert resolved != short_name
    assert resolved.startswith("cra_chunks_v1_")
    assert len(resolved) > len(short_name)


def test_model_revision_changes_vector_profile_and_collection(tmp_path) -> None:
    store = InMemoryVectorStore()
    first_service = _service(tmp_path, store, VectorProfile(model_id="fake", model_revision="1", dimension=8))
    second_service = _service(tmp_path, store, VectorProfile(model_id="fake", model_revision="2", dimension=8))
    first = first_service.sync(
        repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")]
    )
    second = second_service.sync(
        repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")]
    )
    assert first.vector_profile_hash != second.vector_profile_hash
    assert first.collection_name != second.collection_name


def test_optional_sparse_vector_shares_versioned_point_without_blocking_dense(tmp_path) -> None:
    store = InMemoryVectorStore()
    profile = VectorProfile(
        model_id="fake", model_revision="1", dimension=8,
        sparse_model_id="Qdrant/bm25", sparse_model_version="v1",
    )
    service = VectorSyncService(
        vector_store=store,
        embedder=FakeEmbedder(dimension=8),
        profile=profile,
        manifest_root=tmp_path / "manifests",
        sparse_provider=FakeSparseVectorProvider(),
    )
    manifest = service.sync(
        repo_id="repo-a", index_version_id="idx-1", documents=[_document("repo-a", "idx-1")]
    )
    vector = FakeSparseVectorProvider().embed(["forward"])[0]
    hits = store.search_sparse(
        manifest.collection_name,
        "sparse_bm25_v1",
        vector,
        filters={
            "repo_id": "repo-a", "index_version_id": "idx-1",
            "vector_profile_hash": profile.profile_hash,
        },
        top_k=5,
    )
    assert hits[0].payload["chunk_id"] == "chunk-stable"
