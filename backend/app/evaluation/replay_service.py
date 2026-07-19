from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pvariance

from backend.app.evaluation.artifact_resolver import (
    ArtifactResolverError,
    EvaluationAccessContext,
    EvaluationArtifactResolver,
)
from backend.app.evaluation.schemas import (
    EvaluationArtifactRef,
    EvaluationProviderBudget,
    LiveTrialSpec,
    ReplayManifest,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id


class ReplayService:
    def __init__(self, resolver: EvaluationArtifactResolver) -> None:
        self.resolver = resolver

    def build_manifest(
        self,
        *,
        replay_type: str,
        source_evaluation_run_id: str,
        source_subject_id: str,
        replay_subject_id: str,
        artifacts: list[EvaluationArtifactRef],
        access_context: EvaluationAccessContext,
        source_business_run_id: str | None = None,
        source_trace_id: str | None = None,
        source_checkpoint_id: str | None = None,
        external_model_consent: bool = False,
        budget: EvaluationProviderBudget | None = None,
        trial_spec: LiveTrialSpec | None = None,
    ) -> ReplayManifest:
        reasons: list[str] = []
        for artifact in artifacts:
            try:
                self.resolver.resolve(artifact, access_context)
            except ArtifactResolverError as exc:
                reasons.append(exc.error_code)
        if replay_type == "live" and not external_model_consent:
            readiness = "consent_required"
            reasons.append("live_consent_required")
        elif replay_type == "live" and (budget is None or trial_spec is None):
            readiness = "not_ready"
            reasons.append("live_budget_or_trial_missing")
        elif reasons:
            readiness = "artifact_missing"
        else:
            readiness = "ready"
        payload = [source_evaluation_run_id, replay_subject_id, replay_type, [a.content_hash for a in artifacts]]
        return ReplayManifest(
            replay_manifest_id=stable_id("replay", payload),
            replay_type=replay_type,
            source_evaluation_run_id=source_evaluation_run_id,
            source_business_run_id=source_business_run_id,
            source_subject_id=source_subject_id,
            replay_subject_id=replay_subject_id,
            source_trace_id=source_trace_id,
            source_checkpoint_id=source_checkpoint_id,
            required_artifact_ref_ids=[item.artifact_ref_id for item in artifacts],
            readiness=readiness,
            reason_codes=sorted(set(reasons)),
            external_model_consent=external_model_consent,
            budget=budget,
            trial_spec=trial_spec,
            content_hash=stable_hash(payload),
        )


@dataclass(frozen=True, slots=True)
class LiveTrialSummary:
    trial_group_id: str
    repeat_count: int
    mean_score: float
    variance: float
    success_rate: float
    provider_failure_rate: float


def summarize_live_trials(
    trial_group_id: str, scores: list[float | None], provider_failures: list[bool]
) -> LiveTrialSummary:
    if len(scores) != len(provider_failures) or not scores:
        raise ValueError("live trial inputs must have equal non-empty lengths")
    values = [score for score in scores if score is not None]
    return LiveTrialSummary(
        trial_group_id=trial_group_id,
        repeat_count=len(scores),
        mean_score=mean(values) if values else 0.0,
        variance=pvariance(values) if len(values) > 1 else 0.0,
        success_rate=len(values) / len(scores),
        provider_failure_rate=sum(provider_failures) / len(provider_failures),
    )
