from __future__ import annotations

from dataclasses import dataclass

from backend.app.evaluation.schemas import AlignmentGold, EvaluationCase


@dataclass(frozen=True, slots=True)
class AlignmentGoldAudit:
    status: str
    pair_count: int
    dev_pair_count: int
    locked_pair_count: int
    positive_count: int
    negative_count: int
    reason_codes: tuple[str, ...]


def audit_alignment_gold(
    cases: list[EvaluationCase],
    *,
    require_release_shape: bool = False,
) -> AlignmentGoldAudit:
    """Validate human Alignment Gold without accepting model/system predictions as labels."""

    reasons: list[str] = []
    alignment_cases = [case for case in cases if case.component == "alignment"]
    if not alignment_cases:
        reasons.append("ALIGNMENT_BENCHMARK_PENDING")
    if any(case.source != "human_authored" for case in alignment_cases):
        reasons.append("alignment_gold_not_human_authored")
    if any(len(set(case.annotator_scope_hashes)) < 2 for case in alignment_cases):
        reasons.append("alignment_gold_double_review_missing")
    if any(
        case.adjudication_status not in {"agreed", "adjudicated"}
        for case in alignment_cases
    ):
        reasons.append("alignment_gold_adjudication_incomplete")
    pairs_by_split: dict[str, set[tuple[str, str]]] = {"dev": set(), "locked_test": set()}
    for case in alignment_cases:
        if not case.paper_id:
            reasons.append("alignment_gold_paper_missing")
            continue
        if case.split in pairs_by_split:
            pairs_by_split[case.split].add((case.repo_id, case.paper_id))
        if not isinstance(case.gold, AlignmentGold):
            reasons.append("alignment_gold_schema_invalid")
    if pairs_by_split["dev"] & pairs_by_split["locked_test"]:
        reasons.append("alignment_pair_split_leakage")
    positive = sum(
        bool(case.gold.gold_selections)
        for case in alignment_cases if isinstance(case.gold, AlignmentGold)
    )
    negative = sum(
        not case.gold.gold_selections and not case.gold.acceptable_alternative_sets
        for case in alignment_cases if isinstance(case.gold, AlignmentGold)
    )
    pair_count = len(pairs_by_split["dev"] | pairs_by_split["locked_test"])
    if require_release_shape:
        if len(pairs_by_split["dev"]) != 4 or len(pairs_by_split["locked_test"]) != 2:
            reasons.append("alignment_pair_count_incomplete")
        if len(alignment_cases) != 92 or positive != 72 or negative != 20:
            reasons.append("alignment_case_count_incomplete")
    unique_reasons = tuple(sorted(set(reasons)))
    return AlignmentGoldAudit(
        status="ready" if not unique_reasons else "ALIGNMENT_BENCHMARK_PENDING",
        pair_count=pair_count,
        dev_pair_count=len(pairs_by_split["dev"]),
        locked_pair_count=len(pairs_by_split["locked_test"]),
        positive_count=positive,
        negative_count=negative,
        reason_codes=unique_reasons,
    )
