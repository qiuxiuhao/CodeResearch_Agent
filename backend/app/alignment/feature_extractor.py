from __future__ import annotations

import re

from backend.app.alignment.paper_module_extractor import normalize_concept
from backend.app.alignment.schemas import (
    AlignmentCandidate,
    AlignmentFeatureValue,
    AlignmentFeatureVector,
    PaperModuleProfile,
)
from backend.app.alignment.stable_ids import content_hash, feature_vector_id
from backend.app.domain.entities import CodeEntity
from backend.app.domain.index_manifest import SymbolChunk


FEATURE_SCHEMA_VERSION = "alignment-features-v1"
FEATURE_NAMES = (
    "name",
    "semantic",
    "role",
    "structure",
    "input_output",
    "shape",
    "formula_variable",
    "figure_topology",
    "evidence_quality",
)
FEATURE_WEIGHTS = {
    "name": 0.22,
    "semantic": 0.16,
    "role": 0.12,
    "structure": 0.12,
    "input_output": 0.10,
    "shape": 0.08,
    "formula_variable": 0.08,
    "figure_topology": 0.05,
    "evidence_quality": 0.07,
}


def extract_feature_vector(
    *,
    profile: PaperModuleProfile,
    candidate: AlignmentCandidate,
    entity: CodeEntity,
    chunks: list[SymbolChunk] | None = None,
    required_weight_ratio: float = 0.65,
) -> AlignmentFeatureVector:
    text = " ".join(
        [entity.name, entity.qualified_name, entity.path, entity.signature or "", entity.docstring or "", entity.source_code or ""]
        + [chunk.text for chunk in (chunks or [])]
    )
    features = [
        _available("name", _name_score(profile, entity), profile.evidence_ids + candidate.code_evidence_ids, "normalized name/token overlap"),
        _available_or_missing("semantic", _lexical_score(profile.description, text), bool(text), candidate.retrieval_chunk_ids, "deterministic lexical semantic baseline"),
        _available_or_missing("role", _role_score(profile.role, entity, text), profile.role is not None, candidate.code_evidence_ids, "profile role compatibility"),
        _available_or_missing("structure", _source_score(candidate, "code_graph"), _has_source(candidate, "code_graph"), _source_evidence(candidate, "code_graph"), "graph candidate contribution"),
        _available_or_missing("input_output", _io_score(profile, entity, text), bool(profile.inputs or profile.outputs), candidate.code_evidence_ids, "input/output token overlap"),
        _available_or_missing("shape", _shape_score(profile.description, text), _has_shape(profile.description), candidate.code_evidence_ids, "shape/dimension overlap"),
        _not_applicable_or_value("formula_variable", _formula_score(profile.formula_symbols, text), bool(profile.formula_symbols), candidate.code_evidence_ids, "formula symbol overlap"),
        _not_applicable_or_value("figure_topology", _source_score(candidate, "figure_vlm"), bool(profile.figure_neighbor_ids), _source_evidence(candidate, "figure_vlm"), "figure topology candidate contribution"),
        _available("evidence_quality", _evidence_score(profile, candidate), profile.evidence_ids + candidate.code_evidence_ids, "paper/code evidence completeness"),
    ]
    applicable = [item for item in features if item.status != "not_applicable"]
    available = [item for item in applicable if item.status == "available"]
    applicable_weight = sum(FEATURE_WEIGHTS[item.feature_name] for item in applicable)
    available_weight = sum(FEATURE_WEIGHTS[item.feature_name] for item in available)
    ratio = available_weight / applicable_weight if applicable_weight else 0.0
    penalty = min(1.0, ratio / required_weight_ratio)
    payload = [item.model_dump(mode="json") for item in features]
    return AlignmentFeatureVector(
        vector_id=feature_vector_id(
            profile_id_value=profile.profile_id,
            candidate_id_value=candidate.candidate_id,
            schema_version=FEATURE_SCHEMA_VERSION,
        ),
        alignment_run_id=profile.alignment_run_id,
        profile_id=profile.profile_id,
        candidate_id=candidate.candidate_id,
        features=features,
        available_weight_ratio=ratio,
        required_weight_ratio=required_weight_ratio,
        coverage_penalty=penalty,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        content_hash=content_hash(payload),
    )


def _available(name: str, value: float, evidence: list[str], explanation: str) -> AlignmentFeatureValue:
    return AlignmentFeatureValue(
        feature_name=name,
        value=_clamp(value),
        normalized_value=_clamp(value),
        status="available",
        evidence_ids=sorted(set(evidence)),
        explanation=explanation,
        extractor_version=FEATURE_SCHEMA_VERSION,
    )


def _available_or_missing(
    name: str, value: float, available: bool, evidence: list[str], explanation: str
) -> AlignmentFeatureValue:
    if available:
        return _available(name, value, evidence, explanation)
    return AlignmentFeatureValue(
        feature_name=name,
        status="missing",
        missing_reason=f"{name}_input_missing",
        evidence_ids=[],
        explanation=explanation,
        extractor_version=FEATURE_SCHEMA_VERSION,
    )


def _not_applicable_or_value(
    name: str, value: float, applicable: bool, evidence: list[str], explanation: str
) -> AlignmentFeatureValue:
    if applicable:
        return _available(name, value, evidence, explanation)
    return AlignmentFeatureValue(
        feature_name=name,
        status="not_applicable",
        missing_reason=f"{name}_not_applicable",
        evidence_ids=[],
        explanation=explanation,
        extractor_version=FEATURE_SCHEMA_VERSION,
    )


def _name_score(profile: PaperModuleProfile, entity: CodeEntity) -> float:
    paper = _tokens(" ".join([profile.canonical_name, *profile.aliases, *profile.abbreviations]))
    code = _tokens(" ".join([entity.name, entity.qualified_name, entity.path]))
    if profile.normalized_name in {normalize_concept(entity.name), normalize_concept(entity.qualified_name)}:
        return 1.0
    return _jaccard(paper, code)


def _lexical_score(left: str, right: str) -> float:
    return _jaccard(_tokens(left), _tokens(right))


def _role_score(role: str | None, entity: CodeEntity, text: str) -> float:
    if not role:
        return 0.0
    normalized = normalize_concept(f"{entity.entity_type} {text}")
    return 1.0 if normalize_concept(role) in normalized else 0.0


def _io_score(profile: PaperModuleProfile, entity: CodeEntity, text: str) -> float:
    return _jaccard(_tokens(" ".join([*profile.inputs, *profile.outputs])), _tokens(f"{entity.signature or ''} {text}"))


def _shape_score(left: str, right: str) -> float:
    pattern = r"\b(?:\d+d|[bchwnd]|batch|channel|dimension|shape|tensor)\b"
    return _jaccard(set(re.findall(pattern, left.lower())), set(re.findall(pattern, right.lower())))


def _has_shape(text: str) -> bool:
    return bool(re.search(r"\b(?:\d+d|batch|channel|dimension|shape|tensor)\b", text.lower()))


def _formula_score(symbols: list[str], text: str) -> float:
    if not symbols:
        return 0.0
    code_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return len(set(symbols) & code_tokens) / len(set(symbols))


def _evidence_score(profile: PaperModuleProfile, candidate: AlignmentCandidate) -> float:
    return min(1.0, (0.5 if profile.evidence_ids else 0.0) + (0.5 if candidate.code_evidence_ids else 0.0))


def _has_source(candidate: AlignmentCandidate, source: str) -> bool:
    return any(item.source == source for item in candidate.source_contributions)


def _source_score(candidate: AlignmentCandidate, source: str) -> float:
    return max((item.normalized_contribution or 0.0 for item in candidate.source_contributions if item.source == source), default=0.0)


def _source_evidence(candidate: AlignmentCandidate, source: str) -> list[str]:
    return sorted({evidence for item in candidate.source_contributions if item.source == source for evidence in item.evidence_ids})


def _tokens(text: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9]+", normalize_concept(text)) if len(item) > 1}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
