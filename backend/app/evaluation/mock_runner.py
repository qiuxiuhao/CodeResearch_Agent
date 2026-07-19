from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.evaluation.adapter import EvaluationExecutionContext
from backend.app.evaluation.artifact_resolver import ControlledArtifactResolver, EvaluationAccessContext
from backend.app.evaluation.dataset_catalog import DatasetCatalog
from backend.app.evaluation.evaluation_service import EvaluationService
from backend.app.evaluation.in_memory_store import InMemoryEvaluationStore
from backend.app.evaluation.schemas import (
    AgentEvaluationInput,
    AgentGold,
    AgentOutcome,
    AlignmentEvaluationInput,
    AlignmentGold,
    AlignmentGoldSelection,
    AlignmentOutcome,
    AnswerEvaluationInput,
    AnswerGold,
    AnswerOutcome,
    EvaluationCase,
    EvaluationDataset,
    EvaluationDatasetVersion,
    EvaluationFixtureBinding,
    EvaluationProvenance,
    EvaluationRunCreateRequest,
    ExecutionEnvironment,
    IndexEvaluationInput,
    IndexGold,
    IndexOutcome,
    ObservabilityEvaluationInput,
    ObservabilityGold,
    ObservabilityOutcome,
    RetrievalEvaluationInput,
    RetrievalGold,
    RetrievalOutcome,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id
from backend.app.evaluation.subjects import build_evaluation_subject


V1_8_COMMIT = "db6685a45baa5f75e4856cbc406e410ad313f332"


@dataclass(slots=True)
class SyntheticSuite:
    store: InMemoryEvaluationStore
    service: EvaluationService
    request: EvaluationRunCreateRequest
    outcomes: dict[str, object]


def build_synthetic_suite(*, candidate_commit: str = V1_8_COMMIT) -> SyntheticSuite:
    """Create a six-component, no-network suite for CI contract regression only."""

    store = InMemoryEvaluationStore()
    now = datetime.now(UTC)
    subject = build_evaluation_subject(
        subject_type="code_commit",
        code_commit_sha=candidate_commit,
        code_tag="v1.8.0" if candidate_commit == V1_8_COMMIT else None,
        worktree_patch_hash=None,
        config_hash=stable_hash("synthetic-config-v1"),
        dependency_lock_hash=stable_hash("synthetic-lock-v1"),
        created_at=now,
    )
    store.save_subject(subject)
    provenance = EvaluationProvenance(
        subject_id=subject.subject_id,
        dataset_version_id="synthetic-regression-v1",
        fixture_version="synthetic-fixtures-v1",
        created_at=now,
    )
    dataset = EvaluationDataset(
        dataset_id="synthetic-regression",
        dataset_family_id="synthetic-regression",
        name="v1.9 deterministic contract suite",
        description="Synthetic fixtures only; not an Alignment quality benchmark.",
        component_scope=["index", "retrieval", "agent", "alignment", "answer", "observability"],
        owner_scope_hash=stable_hash("local-ci"),
        created_at=now,
        updated_at=now,
    )
    store.save_dataset(dataset)
    version = EvaluationDatasetVersion(
        dataset_version_id="synthetic-regression-v1",
        dataset_id=dataset.dataset_id,
        version="1",
        status="draft",
        schema_hash=stable_hash("evaluation-schema-v1"),
        gold_hash=stable_hash([]),
        fixture_hash=stable_hash("synthetic-fixtures-v1"),
        content_hash=stable_hash([]),
        annotation_policy_version="synthetic-no-human-gold-v1",
        authorization_scope_hash=stable_hash("local-ci"),
        provenance=provenance,
        created_at=now,
    )
    store.save_dataset_version(version)

    fixture = EvaluationFixtureBinding(
        repository_fixture_id="repo-synthetic",
        repository_content_hash=stable_hash("repo-synthetic"),
        paper_fixture_id="paper-synthetic",
        paper_content_hash=stable_hash("paper-synthetic"),
        reference_index_version_id="index-reference-v1",
        reference_index_manifest_hash=stable_hash("index-reference-v1"),
        candidate_index_namespace="evaluation-isolated",
        fixture_version="synthetic-fixtures-v1",
    )
    specs = _case_specs()
    outcomes: dict[str, object] = {}
    for component, input_model, gold, outcome in specs:
        case_id = f"synthetic-{component}-001"
        case_payload = [component, input_model.model_dump(mode="json"), gold.model_dump(mode="json")]
        case = EvaluationCase(
            case_id=case_id,
            stable_case_family_id=case_id,
            dataset_version_id=version.dataset_version_id,
            split="regression",
            source="synthetic_fixture",
            component=component,
            fixture=fixture,
            repo_id="repo-synthetic",
            reference_index_version_id="index-reference-v1",
            paper_id="paper-synthetic" if component == "alignment" else None,
            input=input_model,
            gold=gold,
            difficulty="easy",
            tags=["ci", "synthetic", component],
            adjudication_status="not_required",
            provenance=provenance,
            content_hash=stable_hash(case_payload),
        )
        store.save_case(case)
        outcomes[case_id] = outcome
    DatasetCatalog(store).validate_and_freeze(version.dataset_version_id)

    environment_payload = {
        "python_version": "3.11",
        "dependency_lock_hash": subject.dependency_lock_hash,
        "os_name": "deterministic",
        "os_version": "fixture",
        "cpu_profile": "single-threaded-fixture",
        "gpu_profile": None,
        "memory_profile": None,
        "provider_region": None,
        "cache_profile": "not_applicable",
        "case_concurrency": 1,
        "provider_concurrency": 0,
    }
    environment = ExecutionEnvironment(
        environment_id=stable_id("environment", environment_payload),
        environment_hash=stable_hash(environment_payload),
        **environment_payload,
    )
    store.save_environment(environment)

    def context_factory(run, _cases):
        return EvaluationExecutionContext(
            evaluation_run_id=run.run_id,
            resolver=ControlledArtifactResolver(),
            access_context=EvaluationAccessContext("local-ci", local_admin=True),
            fixed_outcomes=outcomes,  # type: ignore[arg-type]
        )

    service = EvaluationService(store, context_factory=context_factory)
    request = EvaluationRunCreateRequest(
        dataset_version_id=version.dataset_version_id,
        subject_id=subject.subject_id,
        environment_id=environment.environment_id,
        mode="deterministic_fixture",
        components=["index", "retrieval", "agent", "alignment", "answer", "observability"],
        case_concurrency=1,
        provider_concurrency=0,
        random_seed=0,
    )
    return SyntheticSuite(store=store, service=service, request=request, outcomes=outcomes)


def _case_specs():
    selection = AlignmentGoldSelection(code_entity_id="ent_encoder", relation_type="implements")
    return [
        (
            "index",
            IndexEvaluationInput(
                repository_artifact_ref_ids=["repo-fixture"],
                build_profile_id="index-profile-v1",
                candidate_namespace_policy="temporary_database",
            ),
            IndexGold(
                required_entity_ids=["ent_encoder"], required_edge_ids=["edge_defines"],
                required_evidence_ids=["ev_code"], required_chunk_ids=["chunk_encoder"],
            ),
            IndexOutcome(
                candidate_index_version_id="candidate-index-isolated-v1",
                entity_ids=["ent_encoder"], edge_ids=["edge_defines"],
                evidence_ids=["ev_code"], chunk_ids=["chunk_encoder"],
                manifest_hash=stable_hash("candidate-index-isolated-v1"),
            ),
        ),
        (
            "retrieval",
            RetrievalEvaluationInput(
                query_artifact_ref_ids=["query-fixture"], retrieval_profile_id="hybrid-v1",
            ),
            RetrievalGold(
                required_entity_ids=["ent_encoder"], required_chunk_ids=["chunk_encoder"],
                relevance_by_entity={"ent_encoder": 1.0},
            ),
            RetrievalOutcome(
                ranked_entity_ids=["ent_encoder"], ranked_chunk_ids=["chunk_encoder"],
                channel_status={"sparse": "success", "dense": "skipped"},
            ),
        ),
        (
            "agent",
            AgentEvaluationInput(
                task_artifact_ref_ids=["task-fixture"], run_profile_id="agent-v1",
                budget_profile_id="ci-budget-v1",
            ),
            AgentGold(
                expected_route="research", required_tools=["retrieve_code"],
                required_evidence_ids=["ev_code"], expected_sufficient=True,
                expected_terminal_status="completed",
            ),
            AgentOutcome(
                route="research", plan_steps=["retrieve"],
                tool_calls=[{"tool_name": "retrieve_code"}], evidence_ids=["ev_code"],
                sufficient=True, terminal_status="completed",
            ),
        ),
        (
            "alignment",
            AlignmentEvaluationInput(
                paper_artifact_ref_ids=["paper-fixture"], profile_ids=["profile_encoder"],
                alignment_model_profile_id="alignment-fixture-v1",
            ),
            AlignmentGold(
                profile_id="profile_encoder", gold_selections=[selection], alignable=True,
                required_paper_evidence_ids=["ev_paper"], required_code_evidence_ids=["ev_code"],
                relation_types=["implements"],
            ),
            AlignmentOutcome(
                profile_id="profile_encoder", candidate_ids=["ent_encoder"], selections=[selection],
                decision_status="accepted", paper_evidence_ids=["ev_paper"],
                code_evidence_ids=["ev_code"], candidate_probabilities={"ent_encoder": 0.9},
            ),
        ),
        (
            "answer",
            AnswerEvaluationInput(
                answer_artifact_ref_ids=["answer-fixture"], answer_profile_id="answer-v1",
            ),
            AnswerGold(required_answer_points=["point_encoder"], required_evidence_ids=["ev_code"]),
            AnswerOutcome(
                answer_point_ids=["point_encoder"], evidence_ids=["ev_code"],
                citation_ids=["citation-1"],
            ),
        ),
        (
            "observability",
            ObservabilityEvaluationInput(
                trace_artifact_ref_ids=["trace-fixture"], recorder_profile_id="metadata-v1",
                operation_taxonomy_version="cra-operations-v1",
            ),
            ObservabilityGold(
                required_operations=["api.request", "retrieval.search"],
                required_parent_child_edges=[("api.request", "retrieval.search")],
                forbidden_attributes=["prompt", "authorization"],
                required_integrity_state="complete",
            ),
            ObservabilityOutcome(
                operation_names=["api.request", "retrieval.search"],
                parent_child_edges=[("api.request", "retrieval.search")],
                completeness="complete",
            ),
        ),
    ]
