from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from backend.app.alignment.schemas import PaperModuleProfile, ProfileGranularity, ProfileType
from backend.app.alignment.stable_ids import content_hash, profile_id
from backend.app.domain.entities import PaperEntity
from backend.app.schemas.paper import PaperAnalysis


PROFILE_EXTRACTOR_VERSION = "paper-profile-rules-v1"
PROFILE_GENERATION_VERSION = "profile-generation-v1"


@dataclass
class _ProfileCandidate:
    profile_type: ProfileType
    granularity: ProfileGranularity
    canonical_name: str
    description: str
    source_locator: str
    contribution_ids: list[str] = field(default_factory=list)
    paper_entity_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    formula_symbols: list[str] = field(default_factory=list)
    figure_neighbor_ids: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    role: str | None = None


def extract_paper_module_profiles(
    *,
    alignment_run_id: str,
    repo_id: str,
    index_version_id: str,
    paper_id: str,
    paper_analysis: PaperAnalysis | dict,
    paper_entities: list[PaperEntity] | None = None,
    extractor_version: str = PROFILE_EXTRACTOR_VERSION,
    generation_version: str = PROFILE_GENERATION_VERSION,
) -> list[PaperModuleProfile]:
    analysis = (
        paper_analysis
        if isinstance(paper_analysis, PaperAnalysis)
        else PaperAnalysis.model_validate(paper_analysis)
    )
    if not analysis.paper_provided:
        return []
    candidates = _from_contributions(analysis)
    candidates.extend(_from_paper_entities(paper_entities or []))
    merged = _merge_candidates(candidates, paper_id, generation_version)
    profiles = [
        _build_profile(
            item,
            alignment_run_id=alignment_run_id,
            repo_id=repo_id,
            index_version_id=index_version_id,
            paper_id=paper_id,
            extractor_version=extractor_version,
            generation_version=generation_version,
        )
        for item in merged
    ]
    return sorted(profiles, key=lambda item: item.profile_id)


def normalize_concept(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"[_./:-]+", " ", value)
    return " ".join(value.lower().split())


def _from_contributions(analysis: PaperAnalysis) -> list[_ProfileCandidate]:
    result: list[_ProfileCandidate] = []
    module_names = sorted(set(analysis.module_names), key=lambda item: (-len(item), item.lower()))
    for contribution in analysis.contributions:
        text = f"{contribution.title} {contribution.description}"
        matching_modules = [item for item in module_names if normalize_concept(item) in normalize_concept(text)]
        names = matching_modules or [contribution.title]
        for name in names:
            profile_type = _profile_type(name, text)
            result.append(
                _ProfileCandidate(
                    profile_type=profile_type,
                    granularity="contribution",
                    canonical_name=_clean_name(name),
                    description=contribution.description,
                    source_locator=f"contribution:{contribution.id}",
                    contribution_ids=[contribution.id],
                    evidence_ids=list(contribution.evidence),
                    aliases=_explicit_aliases(text),
                    formula_symbols=_formula_symbols(text),
                    inputs=_io_terms(text, "input"),
                    outputs=_io_terms(text, "output"),
                    role=_role(text),
                )
            )
    if not result and analysis.method_text:
        result.append(
            _ProfileCandidate(
                profile_type="general_contribution",
                granularity="section",
                canonical_name=analysis.title or "paper method",
                description=analysis.method_text,
                source_locator="section:method",
                evidence_ids=[item for section in analysis.sections if section.name == "method" for item in section.evidence],
            )
        )
    return result


def _from_paper_entities(entities: list[PaperEntity]) -> list[_ProfileCandidate]:
    result: list[_ProfileCandidate] = []
    for entity in entities:
        if entity.entity_type not in {"formula", "figure", "method_module"}:
            continue
        if entity.entity_type == "formula":
            profile_type: ProfileType = "formula"
            granularity: ProfileGranularity = "formula"
        elif entity.entity_type == "figure":
            profile_type = "figure_module"
            granularity = "figure_node"
        else:
            profile_type = "module"
            granularity = "section"
        name = entity.title or (entity.module_names[0] if entity.module_names else entity.text[:80])
        result.append(
            _ProfileCandidate(
                profile_type=profile_type,
                granularity=granularity,
                canonical_name=_clean_name(name),
                description=entity.text,
                source_locator=f"entity:{entity.id}",
                paper_entity_ids=[entity.id],
                evidence_ids=list(entity.evidence_refs),
                aliases=list(entity.module_names),
                formula_symbols=_formula_symbols(entity.text),
                figure_neighbor_ids=[entity.id] if entity.entity_type == "figure" else [],
                inputs=_io_terms(entity.text, "input"),
                outputs=_io_terms(entity.text, "output"),
                role=_role(entity.text),
            )
        )
    return result


def _merge_candidates(
    candidates: list[_ProfileCandidate], paper_id: str, generation_version: str
) -> list[_ProfileCandidate]:
    groups: dict[str, list[_ProfileCandidate]] = {}
    for candidate in candidates:
        concept = normalize_concept(candidate.canonical_name)
        type_group = (
            "module_family"
            if candidate.profile_type in {"module", "figure_module"}
            else candidate.profile_type
        )
        key = f"{paper_id}:{type_group}:{concept}:{generation_version}"
        groups.setdefault(key, []).append(candidate)
    result: list[_ProfileCandidate] = []
    for key, items in sorted(groups.items()):
        first = items[0]
        profile_type = (
            "module"
            if {item.profile_type for item in items} == {"module", "figure_module"}
            else first.profile_type
        )
        granularities = {item.granularity for item in items}
        granularity = first.granularity if len(granularities) == 1 else _preferred_granularity(granularities)
        result.append(
            _ProfileCandidate(
                profile_type=profile_type,
                granularity=granularity,
                canonical_name=first.canonical_name,
                description="\n".join(dict.fromkeys(item.description for item in items if item.description)),
                source_locator=key,
                contribution_ids=_sorted_unique(item for entry in items for item in entry.contribution_ids),
                paper_entity_ids=_sorted_unique(item for entry in items for item in entry.paper_entity_ids),
                evidence_ids=_sorted_unique(item for entry in items for item in entry.evidence_ids),
                aliases=_sorted_unique(item for entry in items for item in [entry.canonical_name, *entry.aliases]),
                formula_symbols=_sorted_unique(item for entry in items for item in entry.formula_symbols),
                figure_neighbor_ids=_sorted_unique(item for entry in items for item in entry.figure_neighbor_ids),
                inputs=_sorted_unique(item for entry in items for item in entry.inputs),
                outputs=_sorted_unique(item for entry in items for item in entry.outputs),
                role=next((item.role for item in items if item.role), None),
            )
        )
    return result


def _build_profile(
    item: _ProfileCandidate,
    *,
    alignment_run_id: str,
    repo_id: str,
    index_version_id: str,
    paper_id: str,
    extractor_version: str,
    generation_version: str,
) -> PaperModuleProfile:
    normalized = normalize_concept(item.canonical_name)
    source_group_key = item.source_locator
    identifier = profile_id(
        paper_id=paper_id,
        profile_type=item.profile_type,
        granularity=item.granularity,
        source_group_key=source_group_key,
        profile_generation_version=generation_version,
    )
    missing = [name for name, value in (("canonical_name", normalized), ("description", item.description), ("role", item.role)) if not value]
    quality = max(0.2, 1.0 - 0.2 * len(missing))
    payload = {
        "name": item.canonical_name,
        "description": item.description,
        "entities": sorted(item.paper_entity_ids),
        "evidence": sorted(item.evidence_ids),
        "generation": generation_version,
    }
    return PaperModuleProfile(
        profile_id=identifier,
        alignment_run_id=alignment_run_id,
        repo_id=repo_id,
        index_version_id=index_version_id,
        paper_id=paper_id,
        profile_type=item.profile_type,
        granularity=item.granularity,
        source_group_key=source_group_key,
        paper_entity_ids=sorted(item.paper_entity_ids),
        canonical_name=item.canonical_name,
        normalized_name=normalized,
        aliases=_sorted_unique(alias for alias in item.aliases if normalize_concept(alias) != normalized),
        abbreviations=_sorted_unique(_explicit_aliases(" ".join(item.aliases))),
        role=item.role,
        description=item.description,
        inputs=sorted(item.inputs),
        outputs=sorted(item.outputs),
        formula_symbols=sorted(item.formula_symbols),
        figure_neighbor_ids=sorted(item.figure_neighbor_ids),
        contribution_ids=sorted(item.contribution_ids),
        evidence_ids=sorted(item.evidence_ids),
        extraction_sources=["deterministic_rule"],
        content_hash=content_hash(payload),
        extractor_version=extractor_version,
        profile_generation_version=generation_version,
        profile_quality=quality,
        missing_fields=missing,
    )


def _profile_type(name: str, text: str) -> ProfileType:
    value = normalize_concept(f"{name} {text}")
    if any(token in value for token in ("training", "optimization", "curriculum")):
        return "training_strategy"
    if any(token in value for token in ("inference", "decoding", "prediction")):
        return "inference_strategy"
    if any(token in value for token in ("configuration", "hyperparameter", "learning rate")):
        return "configuration"
    if any(token in value for token in ("formula", "equation", "objective")):
        return "formula"
    if name.strip():
        return "module"
    return "general_contribution"


def _role(text: str) -> str | None:
    value = normalize_concept(text)
    for role in ("encoder", "decoder", "attention", "loss", "backbone", "head", "configuration", "training", "inference"):
        if role in value:
            return role
    return None


def _explicit_aliases(text: str) -> list[str]:
    pairs = re.findall(r"([A-Za-z][A-Za-z0-9 -]{2,60})\s*\(([A-Z][A-Z0-9-]{1,12})\)", text)
    return _sorted_unique(alias for long_name, short_name in pairs for alias in (long_name.strip(), short_name))


def _formula_symbols(text: str) -> list[str]:
    symbols = set(re.findall(r"\b[A-Za-z]_[A-Za-z0-9]+\b", text))
    math_spans = re.findall(r"\$([^$]+)\$|\\\(([^)]+)\\\)", text)
    for groups in math_spans:
        span = " ".join(item for item in groups if item)
        symbols.update(re.findall(r"(?<![A-Za-z0-9_])[A-Za-z](?![A-Za-z0-9_])", span))
    for left, right in re.findall(
        r"\b([A-Za-z])\s*(?:=|\+|-|\*|/|∈)\s*([A-Za-z])?", text
    ):
        symbols.add(left)
        if right:
            symbols.add(right)
    return _sorted_unique(symbols)


def _io_terms(text: str, kind: str) -> list[str]:
    pattern = rf"\b{kind}s?\s*(?:is|are|:)?\s*([A-Za-z][A-Za-z0-9_ -]{{1,40}})"
    values = []
    for value in re.findall(pattern, text, flags=re.IGNORECASE):
        value = re.split(r"\b(?:and|to|from|with|that|which)\b|[.,;:]", value, maxsplit=1)[0]
        cleaned = _clean_name(value)
        if cleaned:
            values.append(cleaned)
    return _sorted_unique(values)


def _clean_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())[:200]


def _preferred_granularity(values: set[ProfileGranularity]) -> ProfileGranularity:
    order: list[ProfileGranularity] = ["formula", "figure_node", "contribution", "section", "paper"]
    return next(item for item in order if item in values)


def _sorted_unique(values) -> list[str]:
    return sorted({str(value) for value in values if value})
