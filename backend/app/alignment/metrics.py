from __future__ import annotations

import math

from backend.app.alignment.benchmark import AlignmentBenchmarkCase, AlignmentPrediction


def candidate_recall(ranked_ids: list[str], gold_ids: set[str], k: int) -> float:
    if not gold_ids:
        return 1.0
    return len(set(ranked_ids[:k]) & gold_ids) / len(gold_ids)


def reciprocal_rank(ranked_ids: list[str], gold_ids: set[str]) -> float:
    for rank, entity_id in enumerate(ranked_ids, start=1):
        if entity_id in gold_ids:
            return 1.0 / rank
    return 0.0


def exact_set_match(predicted: set[tuple[str, str]], gold: set[tuple[str, str]]) -> float:
    return float(predicted == gold)


def selection_f1(predicted: set[tuple[str, str]], gold: set[tuple[str, str]]) -> float:
    if not predicted and not gold:
        return 1.0
    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(gold) if gold else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def brier_score(probabilities: list[float], labels: list[int]) -> float:
    if len(probabilities) != len(labels) or not labels:
        raise ValueError("Brier score requires equal non-empty probability and label lists.")
    return sum((probability - label) ** 2 for probability, label in zip(probabilities, labels)) / len(labels)


def expected_calibration_error(
    probabilities: list[float], labels: list[int], *, bin_count: int = 10
) -> tuple[float, list[dict[str, float | int]]]:
    if len(probabilities) != len(labels) or not labels:
        raise ValueError("ECE requires equal non-empty probability and label lists.")
    bins: list[dict[str, float | int]] = []
    total = len(labels)
    error = 0.0
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        selected = [
            (probability, label)
            for probability, label in zip(probabilities, labels)
            if lower <= probability <= upper and (index == bin_count - 1 or probability < upper)
        ]
        confidence = sum(item[0] for item in selected) / len(selected) if selected else 0.0
        accuracy = sum(item[1] for item in selected) / len(selected) if selected else 0.0
        error += len(selected) / total * abs(confidence - accuracy)
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "sample_count": len(selected),
                "confidence": confidence,
                "accuracy": accuracy,
            }
        )
    return error, bins


def evaluate_alignment_predictions(
    cases: list[AlignmentBenchmarkCase], predictions: list[AlignmentPrediction]
) -> dict:
    prediction_by_id = {item.case_id: item for item in predictions}
    expected_ids = {item.case_id for item in cases}
    if set(prediction_by_id) != expected_ids:
        missing = sorted(expected_ids - set(prediction_by_id))
        extra = sorted(set(prediction_by_id) - expected_ids)
        raise ValueError(f"Prediction coverage mismatch; missing={missing}, extra={extra}")
    output = {
        "all": _evaluate_split(cases, prediction_by_id),
        "dev": _evaluate_split([item for item in cases if item.split == "dev"], prediction_by_id),
        "locked_test": _evaluate_split(
            [item for item in cases if item.split == "locked_test"], prediction_by_id
        ),
    }
    return output


def _evaluate_split(
    cases: list[AlignmentBenchmarkCase],
    prediction_by_id: dict[str, AlignmentPrediction],
    *,
    include_pair_breakdown: bool = True,
) -> dict:
    if not cases:
        return {"case_count": 0}
    recalls = {5: [], 10: [], 20: []}
    reciprocal_ranks: list[float] = []
    exact_matches: list[float] = []
    f1_values: list[float] = []
    top1_values: list[float] = []
    top3_values: list[float] = []
    micro_true_positive = micro_predicted = micro_gold = 0
    paper_precisions: list[float] = []
    code_precisions: list[float] = []
    abstain_true_positive = abstain_predicted = abstain_gold = 0
    no_impl_true_positive = no_impl_predicted = no_impl_gold = 0
    covered = correct_covered = unsupported = 0
    probabilities: list[float] = []
    labels: list[int] = []
    latencies: list[float] = []
    fallback_count = 0
    for case in cases:
        prediction = prediction_by_id[case.case_id]
        gold_entities = {item.code_entity_id for item in case.gold_selections}
        gold_set = {(item.code_entity_id, item.relation_type) for item in case.gold_selections}
        predicted_set = {
            (item.code_entity_id, item.relation_type) for item in prediction.predicted_selections
        }
        for k in recalls:
            recalls[k].append(candidate_recall(prediction.ranked_code_entity_ids, gold_entities, k))
        reciprocal_ranks.append(reciprocal_rank(prediction.ranked_code_entity_ids, gold_entities))
        exact_matches.append(exact_set_match(predicted_set, gold_set))
        f1_values.append(selection_f1(predicted_set, gold_set))
        if len(gold_entities) == 1:
            top1_values.append(float(bool(prediction.ranked_code_entity_ids) and prediction.ranked_code_entity_ids[0] in gold_entities))
        top3_values.append(float(bool(set(prediction.ranked_code_entity_ids[:3]) & gold_entities)) if gold_entities else 1.0)
        micro_true_positive += len(predicted_set & gold_set)
        micro_predicted += len(predicted_set)
        micro_gold += len(gold_set)
        paper_precisions.append(_evidence_precision(prediction.paper_evidence_ids, case.paper_evidence_ids))
        code_precisions.append(
            _evidence_precision(prediction.code_evidence_ids, case.required_code_evidence_ids)
        )
        should_abstain = not case.alignable and not case.no_implementation_confirmed
        predicted_abstain = prediction.status in {"abstained", "needs_review"}
        abstain_true_positive += int(should_abstain and predicted_abstain)
        abstain_predicted += int(predicted_abstain)
        abstain_gold += int(should_abstain)
        predicted_no_impl = prediction.status == "no_implementation"
        no_impl_true_positive += int(case.no_implementation_confirmed and predicted_no_impl)
        no_impl_predicted += int(predicted_no_impl)
        no_impl_gold += int(case.no_implementation_confirmed)
        is_covered = prediction.status in {"accepted", "no_implementation"}
        if is_covered:
            covered += 1
            correct = (
                exact_matches[-1] == 1.0
                if prediction.status == "accepted"
                else case.no_implementation_confirmed
            )
            correct_covered += int(correct)
        if prediction.status == "accepted" and (
            not set(case.paper_evidence_ids) <= set(prediction.paper_evidence_ids)
            or not set(case.required_code_evidence_ids) <= set(prediction.code_evidence_ids)
        ):
            unsupported += 1
        for entity_id, probability in prediction.candidate_probabilities.items():
            probabilities.append(probability)
            labels.append(int(entity_id in gold_entities))
        if prediction.latency_ms is not None:
            latencies.append(prediction.latency_ms)
        fallback_count += int(prediction.fallback_used)
    ece, bins = (
        expected_calibration_error(probabilities, labels) if probabilities else (None, [])
    )
    micro_precision = _safe_div(micro_true_positive, micro_predicted) or 0.0
    micro_recall = _safe_div(micro_true_positive, micro_gold) or 0.0
    report = {
        "case_count": len(cases),
        "candidate_recall_at_5": _mean(recalls[5]),
        "candidate_recall_at_10": _mean(recalls[10]),
        "candidate_recall_at_20": _mean(recalls[20]),
        "mrr": _mean(reciprocal_ranks),
        "top_1_accuracy": _mean(top1_values) if top1_values else None,
        "top_3_recall": _mean(top3_values),
        "exact_set_match": _mean(exact_matches),
        "relation_selection_macro_f1": _mean(f1_values),
        "relation_selection_micro_f1": (
            2 * micro_precision * micro_recall / (micro_precision + micro_recall)
            if micro_precision + micro_recall
            else 0.0
        ),
        "abstention_precision": _safe_div(abstain_true_positive, abstain_predicted),
        "abstention_recall": _safe_div(abstain_true_positive, abstain_gold),
        "no_implementation_precision": _safe_div(no_impl_true_positive, no_impl_predicted),
        "no_implementation_recall": _safe_div(no_impl_true_positive, no_impl_gold),
        "selective_accuracy": _safe_div(correct_covered, covered),
        "coverage": covered / len(cases),
        "paper_evidence_precision": _mean(paper_precisions),
        "code_evidence_precision": _mean(code_precisions),
        "unsupported_alignment_rate": unsupported / len(cases),
        "brier_score": brier_score(probabilities, labels) if probabilities else None,
        "ece": ece,
        "calibration_bins": bins,
        "average_latency_ms": _mean(latencies) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95) if latencies else None,
        "fallback_rate": fallback_count / len(cases),
    }
    if include_pair_breakdown:
        pair_reports = {
            pair_id: _evaluate_split(
                [item for item in cases if item.repo_paper_pair_id == pair_id],
                prediction_by_id,
                include_pair_breakdown=False,
            )
            for pair_id in sorted({item.repo_paper_pair_id for item in cases})
        }
        macro_keys = (
            "candidate_recall_at_20",
            "mrr",
            "exact_set_match",
            "relation_selection_macro_f1",
            "selective_accuracy",
            "coverage",
        )
        report["pair_metrics"] = pair_reports
        report["pair_macro"] = {
            key: _mean_optional(
                [
                    float(item[key])
                    for item in pair_reports.values()
                    if item.get(key) is not None
                ]
            )
            for key in macro_keys
        }
    return report


def _evidence_precision(predicted: list[str], gold: list[str]) -> float:
    if not predicted:
        return 1.0 if not gold else 0.0
    return len(set(predicted) & set(gold)) / len(set(predicted))


def _safe_div(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _mean_optional(values: list[float]) -> float | None:
    return _mean(values) if values else None


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]
