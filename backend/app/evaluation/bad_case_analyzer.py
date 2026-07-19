from __future__ import annotations

from datetime import UTC, datetime

from backend.app.evaluation.schemas import (
    BadCase,
    BadCaseEvent,
    BadCaseOccurrence,
    BadCaseRootCause,
    BadCaseSymptom,
    CaseResult,
    EvaluationCase,
    RootCauseSuggestion,
)
from backend.app.evaluation.stable_ids import stable_hash, stable_id
from backend.app.evaluation.store_protocol import EvaluationStoreProtocol


class BadCaseAnalyzer:
    version = "1"

    def __init__(self, store: EvaluationStoreProtocol) -> None:
        self.store = store

    def analyze(
        self, *, case: EvaluationCase, result: CaseResult, subject_id: str
    ) -> BadCase | None:
        trigger = _trigger_type(result)
        if trigger is None:
            return None
        symptom = _symptom(case, result)
        failure_code = _normalized_failure_code(result)
        fingerprint = stable_hash(
            [case.stable_case_family_id, case.component, symptom, failure_code]
        )
        now = result.finished_at or datetime.now(UTC)
        occurrence_id = stable_id(
            "occurrence", [stable_id("bad_case", fingerprint), result.result_id]
        )
        previous_occurrence = self.store.get_bad_case_occurrence(occurrence_id)
        if previous_occurrence is not None:
            return self.store.get_bad_case(previous_occurrence.bad_case_id)
        existing = self.store.find_bad_case_by_fingerprint(fingerprint)
        if existing is None:
            suggestion = _suggest_root_cause(case, result, failure_code, self.version)
            bad_case = BadCase(
                bad_case_id=stable_id("bad_case", fingerprint),
                fingerprint=fingerprint,
                source_result_id=result.result_id,
                source_evaluation_run_id=result.evaluation_run_id,
                source_trace_id=result.trace_id,
                stable_case_family_id=case.stable_case_family_id,
                case_id=case.case_id,
                component=case.component,
                symptom=symptom,
                trigger_type=trigger,
                suggested_root_causes=[suggestion],
                status="open",
                severity="high" if trigger in {"execution_error", "quality_failure"} else "medium",
                first_seen_run_id=result.evaluation_run_id,
                last_seen_run_id=result.evaluation_run_id,
                created_at=now,
                updated_at=now,
            )
        else:
            reopened = existing.status == "closed"
            bad_case = existing.model_copy(
                update={
                    "status": "open" if reopened else existing.status,
                    "last_seen_run_id": result.evaluation_run_id,
                    "occurrence_count": existing.occurrence_count + 1,
                    "revision": existing.revision + 1,
                    "updated_at": now,
                }
            )
            if reopened:
                self.store.append_bad_case_event(
                    BadCaseEvent(
                        event_id=stable_id("bad_case_event", [bad_case.bad_case_id, bad_case.revision]),
                        bad_case_id=bad_case.bad_case_id,
                        sequence=bad_case.revision,
                        from_status="closed",
                        to_status="open",
                        actor_scope_hash=stable_hash("automatic-recurrence"),
                        based_on_revision=existing.revision,
                        reason_code="bad_case_recurred",
                        created_at=now,
                    )
                )
        self.store.save_bad_case(bad_case)
        occurrence = BadCaseOccurrence(
            occurrence_id=occurrence_id,
            bad_case_id=bad_case.bad_case_id,
            evaluation_run_id=result.evaluation_run_id,
            case_result_id=result.result_id,
            trace_id=result.trace_id,
            subject_id=subject_id,
            observed_at=now,
        )
        self.store.append_bad_case_occurrence(occurrence)
        return bad_case


def _trigger_type(result: CaseResult) -> str | None:
    if result.execution_status == "error":
        return "execution_error"
    if result.evaluation_outcome == "failed":
        return "quality_failure"
    if result.evaluation_outcome == "not_evaluable":
        return "not_evaluable"
    if result.evaluation_outcome == "indeterminate" or not result.complete:
        return "telemetry_incomplete"
    return None


def _symptom(case: EvaluationCase, result: CaseResult) -> BadCaseSymptom:
    codes = set(result.quality_failure_codes + result.incomplete_reason_codes)
    if result.execution_error_code and "timeout" in result.execution_error_code:
        return "timeout"
    if case.component == "alignment":
        if "alignment_selection_mismatch" in codes:
            return "wrong_alignment"
        return "unexpected_abstention"
    if case.component == "observability" or not result.complete:
        return "trace_incomplete"
    if case.component == "answer":
        return "partial_answer" if "answer_partial_mismatch" in codes else "wrong_answer"
    if any("empty" in code for code in codes):
        return "empty_result"
    return "wrong_answer"


def _normalized_failure_code(result: CaseResult) -> str:
    codes = result.quality_failure_codes or result.incomplete_reason_codes
    return result.execution_error_code or (sorted(codes)[0] if codes else "not_evaluable")


def _suggest_root_cause(
    case: EvaluationCase, result: CaseResult, failure_code: str, version: str
) -> RootCauseSuggestion:
    root: BadCaseRootCause = "unknown"
    mapping = {
        "retrieval": "retrieval_miss",
        "alignment": "alignment_scoring_error",
        "agent": "tool_selection_error",
        "observability": "telemetry_drop",
    }
    root = mapping.get(case.component, root)  # type: ignore[assignment]
    if result.execution_error_code:
        root = "provider_error" if "provider" in result.execution_error_code else "unknown"
    return RootCauseSuggestion(
        root_cause=root,
        confidence=0.5,
        reason_codes=[failure_code],
        evidence_ref_ids=[item.artifact_ref_id for item in result.output_artifact_refs],
        analyzer_version=version,
    )
