import pytest

from backend.app.alignment.alignment_service import AlignmentService, default_model_profile
from backend.app.alignment.fact_reader import AlignmentFactReader
from backend.app.alignment.paper_module_extractor import extract_paper_module_profiles
from backend.app.alignment.read_service import AlignmentReadService
from backend.app.domain.edges import KnowledgeEdge
from backend.app.domain.entities import CodeEntity, PaperEntity
from backend.app.domain.evidence import EvidenceRef
from backend.app.domain.index_manifest import IndexedFile, SymbolChunk
from backend.app.indexing.stable_ids import text_content_hash
from backend.app.persistence.alignment_store import AlignmentStore, AlignmentStoreError
from backend.app.persistence.index_store import IndexArtifacts, StructuredIndexStore
from backend.app.schemas.paper import PaperAnalysis, PaperContribution


def _structured_index(path):
    store = StructuredIndexStore(path)
    lease = store.begin_version(
        repo_id="repo",
        identity_mode="explicit",
        repository_key="repo-key",
        display_name="repo",
        input_hash="input-hash",
    )
    code = CodeEntity(
        id="code-attention",
        repo_id="repo",
        entity_type="class",
        path="model.py",
        name="AttentionModule",
        qualified_name="AttentionModule",
        source_code="class AttentionModule: pass",
        content_hash=text_content_hash("class AttentionModule: pass"),
        evidence_refs=["code-evidence"],
    )
    paper = PaperEntity(
        id="paper-contribution",
        paper_id="paper",
        entity_type="contribution",
        title="Attention Module",
        text="We introduce an Attention Module.",
        page_number=2,
        module_names=["Attention Module"],
        content_hash=text_content_hash("Attention Module"),
        evidence_refs=["paper-evidence"],
    )
    edge = KnowledgeEdge(
        id="legacy-edge",
        repo_id="repo",
        source_id=paper.id,
        target_id=code.id,
        edge_type="ALIGNS_WITH",
        confidence=0.9,
        resolution_type="exact",
        evidence_refs=["paper-evidence"],
    )
    artifacts = IndexArtifacts(
        indexed_files=[
            IndexedFile(
                path="model.py", kind="python", content_hash=code.content_hash, size_bytes=10,
                parse_status="success", entity_count=1, edge_count=1, chunk_count=1,
            )
        ],
        code_entities=[code],
        paper_entities=[paper],
        edges=[edge],
        evidence=[
            EvidenceRef(
                id="code-evidence", source_type="code", entity_id=code.id,
                file_path="model.py", start_line=1, end_line=1,
            ),
            EvidenceRef(
                id="paper-evidence", source_type="paper", entity_id=paper.id,
                paper_id="paper", page_number=2,
            ),
        ],
        chunks=[
            SymbolChunk(
                id="chunk-attention", repo_id="repo", entity_id=code.id, entity_kind="code",
                chunk_type="class", path="model.py", start_line=1, end_line=1,
                text="class AttentionModule: pass", content_hash=code.content_hash, char_count=27,
            )
        ],
    )
    store.mark_ready(lease)
    store.activate(lease, artifacts)
    return lease.index_version_id


def test_alignment_service_builds_versioned_active_run(tmp_path):
    structured_path = tmp_path / "structured.sqlite3"
    version = _structured_index(structured_path)
    alignment_store = AlignmentStore(tmp_path / "alignment.sqlite3")
    service = AlignmentService(
        store=alignment_store,
        fact_reader=AlignmentFactReader(structured_path),
    )
    run, reused = service.prepare_run(
        repo_id="repo",
        index_version_id=version,
        paper_id="paper",
        request={"paper_id": "paper", "model_profile_id": "alignment-default-v1"},
        caller_scope="caller",
        idempotency_key="key",
    )
    assert reused is False
    completed = service.process_run(run["run_id"])
    assert completed["status"] == "active"
    assert completed["profile_count"] >= 1
    assert completed["candidate_count"] >= 1
    assert completed["decision_count"] == completed["profile_count"]

    profile = default_model_profile()
    deployment = alignment_store.set_deployment(
        deployment_name="default",
        repo_id="repo",
        index_version_id=version,
        paper_id="paper",
        model_profile_id=profile.model_profile_id,
        active_run_id=run["run_id"],
    )
    assert deployment.active_run_id == run["run_id"]

    items = AlignmentReadService(alignment_store).get_for_entity(
        repo_id="repo", index_version_id=version, entity_id="code-attention"
    )
    assert items
    assert all(item.authority_level in {"derived_scorer", "human_reviewed"} for item in items)
    paper_items = AlignmentReadService(alignment_store).get_for_entity(
        repo_id="repo", index_version_id=version, entity_id="paper-contribution"
    )
    assert {item.entity_id for item in paper_items} == {"code-attention"}


def test_cancelled_run_can_retry_same_input(tmp_path):
    structured_path = tmp_path / "structured.sqlite3"
    version = _structured_index(structured_path)
    store = AlignmentStore(tmp_path / "alignment.sqlite3")
    service = AlignmentService(store=store, fact_reader=AlignmentFactReader(structured_path))
    first, _ = service.prepare_run(
        repo_id="repo", index_version_id=version, paper_id="paper",
        request={"paper_id": "paper", "model_profile_id": "alignment-default-v1"},
        caller_scope="caller", idempotency_key="first",
    )
    store.request_cancel(first["run_id"])
    store.update_status(first["run_id"], "cancelled", allowed_from=["queued"])
    second, reused = service.prepare_run(
        repo_id="repo", index_version_id=version, paper_id="paper",
        request={"paper_id": "paper", "model_profile_id": "alignment-default-v1", "retry_of_run_id": first["run_id"]},
        caller_scope="caller", idempotency_key="second", retry_of_run_id=first["run_id"],
    )
    assert reused is False
    assert second["attempt_number"] == 2


def test_lost_lease_cannot_commit_late_alignment_stage(tmp_path):
    structured_path = tmp_path / "structured.sqlite3"
    version = _structured_index(structured_path)
    store = AlignmentStore(tmp_path / "alignment.sqlite3")
    service = AlignmentService(store=store, fact_reader=AlignmentFactReader(structured_path))
    run, _ = service.prepare_run(
        repo_id="repo",
        index_version_id=version,
        paper_id="paper",
        request={"paper_id": "paper", "model_profile_id": "alignment-default-v1"},
        caller_scope="caller",
        idempotency_key="lease-test",
    )
    lease = store.acquire_lease(run["run_id"], "coordinator")
    assert lease is not None
    store.release_lease(lease)
    with pytest.raises(AlignmentStoreError) as error:
        service.process_run(run["run_id"], lease)
    assert error.value.error_code == "alignment_lease_lost"
    latest = store.get_run(run["run_id"])
    assert latest["status"] == "queued"
    assert latest["profile_count"] == 0


def test_alignment_run_resumes_from_last_persisted_stage(tmp_path):
    structured_path = tmp_path / "structured.sqlite3"
    version = _structured_index(structured_path)
    store = AlignmentStore(tmp_path / "alignment.sqlite3")
    service = AlignmentService(store=store, fact_reader=AlignmentFactReader(structured_path))
    run, _ = service.prepare_run(
        repo_id="repo",
        index_version_id=version,
        paper_id="paper",
        request={"paper_id": "paper", "model_profile_id": "alignment-default-v1"},
        caller_scope="caller",
        idempotency_key="resume-stage",
    )
    profiles = extract_paper_module_profiles(
        alignment_run_id=run["run_id"],
        repo_id="repo",
        index_version_id=version,
        paper_id="paper",
        paper_analysis=PaperAnalysis(
            paper_provided=True,
            contributions=[
                PaperContribution(
                    id="paper-contribution",
                    title="Attention Module",
                    description="Attention Module",
                    evidence=["paper-evidence"],
                )
            ],
            module_names=["Attention Module"],
        ),
    )
    store.save_profiles(run["run_id"], profiles)
    store.update_status(run["run_id"], "recalling", allowed_from=["queued"])
    completed = service.process_run(run["run_id"])
    assert completed["status"] == "active"
    assert completed["candidate_count"] >= 1
