from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


ALIGNMENT_ID_VERSION = "1"


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(value: Any) -> str:
    return _digest("content", canonical_json(value))


def profile_id(
    *,
    paper_id: str,
    profile_type: str,
    granularity: str,
    source_group_key: str,
    profile_generation_version: str,
) -> str:
    return _digest(
        "profile",
        paper_id,
        profile_type,
        granularity,
        source_group_key,
        profile_generation_version,
    )


def candidate_id(*, profile_id_value: str, index_version_id: str, code_entity_id: str) -> str:
    return _digest("candidate", profile_id_value, index_version_id, code_entity_id)


def feature_vector_id(*, profile_id_value: str, candidate_id_value: str, schema_version: str) -> str:
    return _digest("feature", profile_id_value, candidate_id_value, schema_version)


def score_id(*, candidate_id_value: str, scorer_version: str) -> str:
    return _digest("score", candidate_id_value, scorer_version)


def selection_id(*, decision_id_value: str, candidate_id_value: str, relation_type: str) -> str:
    return _digest("selection", decision_id_value, candidate_id_value, relation_type)


def decision_id(*, run_id: str, profile_id_value: str, decision_version: str) -> str:
    return _digest("decision", run_id, profile_id_value, decision_version)


def run_id(*, repo_id: str, index_version_id: str, paper_id: str, input_hash: str, attempt: int) -> str:
    return _digest("run", repo_id, index_version_id, paper_id, input_hash, str(attempt))


def model_profile_id(config: Mapping[str, Any]) -> tuple[str, str]:
    config_hash = content_hash(config)
    return _digest("model-profile", config_hash), config_hash


def deployment_id(*, name: str, repo_id: str, index_version_id: str, paper_id: str) -> str:
    return _digest("deployment", name, repo_id, index_version_id, paper_id)


def review_id(*, decision_id_value: str, review_sequence: int, payload: Any) -> str:
    return _digest("review", decision_id_value, str(review_sequence), canonical_json(payload))


def _digest(kind: str, *parts: str) -> str:
    payload = "\0".join([f"alignment:{ALIGNMENT_ID_VERSION}", kind, *(_text(item) for item in parts)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, Mapping):
        return {_text(str(key)): _normalize(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted((_normalize(item) for item in value), key=lambda item: canonical_json(item))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize(item) for item in value]
    return value


def _text(value: str) -> str:
    return unicodedata.normalize("NFC", value)
