from __future__ import annotations

import unicodedata

import pytest

from backend.app.indexing.input_fingerprint import build_input_payload, input_hash
from backend.app.indexing.stable_ids import (
    code_entity_id,
    knowledge_edge_id,
    model_module_entity_id,
    repository_identity,
    text_content_hash,
)


def test_repository_identity_is_explicit_or_task_scoped() -> None:
    composed = "caf\N{LATIN SMALL LETTER E WITH ACUTE}"
    decomposed = unicodedata.normalize("NFD", composed)
    explicit_a = repository_identity("task-a", f"  {composed}  ")
    explicit_b = repository_identity("task-b", decomposed)
    scoped_a = repository_identity("task-a")
    scoped_b = repository_identity("task-b")

    assert explicit_a == explicit_b
    assert explicit_a[1:] == ("explicit", composed)
    assert scoped_a[1] == "task_scoped"
    assert scoped_a[0] != scoped_b[0]
    with pytest.raises(ValueError):
        repository_identity("task", "  ")


def test_entity_and_edge_ids_ignore_content_and_line_changes() -> None:
    repo_id = repository_identity("task")[0]
    entity = code_entity_id(repo_id, "function", "pkg/mod.py", "pkg.mod.run")
    moved = code_entity_id(repo_id, "function", "pkg/new.py", "pkg.mod.run")
    duplicate = code_entity_id(repo_id, "function", "pkg/mod.py", "pkg.mod.run", 2)

    assert entity == code_entity_id(repo_id, "function", "pkg\\mod.py", "pkg.mod.run")
    assert entity != moved
    assert entity != duplicate
    assert model_module_entity_id(repo_id, entity, "layer") == model_module_entity_id(repo_id, entity, "layer")
    assert model_module_entity_id(repo_id, entity, "layer") != model_module_entity_id(repo_id, moved, "layer")
    assert knowledge_edge_id(entity, "CALLS", "target") == knowledge_edge_id(entity, "CALLS", "target")


def test_text_hash_only_normalizes_bom_and_newlines() -> None:
    assert text_content_hash("\ufeffa\r\nb\r") == text_content_hash("a\nb\n")
    assert text_content_hash("a\n") != text_content_hash("a")
    assert text_content_hash("a  \n") != text_content_hash("a\n")


def test_input_hash_is_canonical_and_version_sensitive() -> None:
    base = dict(
        repo_id="repo",
        repository_identity_mode="explicit",
        paper_content_hash=None,
        effective_options={
            "module_roots": ["src", "src"],
            "indexed_extensions": [".toml", ".py"],
            "ignored_directories": ["z", "a"],
            "max_file_bytes": 10,
            "paper_max_pages": 20,
            "paper_max_text_chars": 30,
            "chunk_policy_version": "1",
            "unresolved_policy_version": "1",
        },
    )
    files = [
        {"path": "b.py", "kind": "python", "size_bytes": 2, "content_hash": "b"},
        {"path": "a.py", "kind": "python", "size_bytes": 1, "content_hash": "a"},
    ]
    payload_a = build_input_payload(files=files, **base)
    payload_b = build_input_payload(files=list(reversed(files)), **base)

    assert input_hash(payload_a) == input_hash(payload_b)
    assert payload_a["effective_options"]["module_roots"] == ["src"]
    assert input_hash(payload_a) != input_hash(build_input_payload(files=files, index_schema_version="next", **base))
    assert input_hash(payload_a) != input_hash(build_input_payload(
        files=files, builder_versions={"code_entity": "next"}, **base
    ))
