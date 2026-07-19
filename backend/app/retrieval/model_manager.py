from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["dense", "sparse", "reranker", "code_dense"]
    model_id: str
    source_repo: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    dimension: int | None = None
    license: str
    required: bool
    allowed_devices: list[Literal["cpu", "cuda"]]


class ModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"] = "1"
    models: list[ModelSpec]


def load_manifest(path: str | Path) -> ModelManifest:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ModelManifest.model_validate(value)


def prefetch_models(
    manifest_path: str | Path, cache_dir: str | Path, *, device: Literal["cpu", "cuda"],
    include_optional: bool = False,
) -> Path:
    manifest = load_manifest(manifest_path)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
    locked_models: list[dict[str, object]] = []
    for spec in manifest.models:
        if not spec.required and not include_optional:
            continue
        if device not in spec.allowed_devices:
            effective_device = "cpu"
        else:
            effective_device = device
        effective_providers = providers if effective_device == "cuda" else ["CPUExecutionProvider"]
        snapshot = _load_for_download(spec, cache, effective_providers)
        locked_models.append({
            **spec.model_dump(mode="json"),
            "snapshot_path": snapshot.relative_to(cache.resolve()).as_posix(),
        })
    lock_path = cache / "model-manifest.lock.json"
    lock_path.write_text(json.dumps({
        "schema_version": "1",
        "source_manifest": str(Path(manifest_path).resolve()),
        "device": device,
        "created_at": datetime.now(UTC).isoformat(),
        "models": locked_models,
        "files": _hash_files(cache, exclude={lock_path.name}),
    }, indent=2, sort_keys=True), encoding="utf-8")
    return lock_path


def verify_models(cache_dir: str | Path) -> list[str]:
    cache = Path(cache_dir)
    lock_path = cache / "model-manifest.lock.json"
    if not lock_path.is_file():
        return ["model_manifest_lock_missing"]
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = payload.get("files", {})
    if not isinstance(expected, dict):
        return ["model_manifest_lock_invalid"]
    actual = _hash_files(cache, exclude={lock_path.name})
    errors = [f"model_file_missing:{name}" for name in expected if name not in actual]
    errors.extend(f"model_hash_mismatch:{name}" for name, digest in expected.items() if actual.get(name) not in {None, digest})
    return sorted(errors)


def model_snapshot_path(cache_dir: str | Path, model_id: str) -> Path:
    cache = Path(cache_dir).resolve()
    lock_path = cache / "model-manifest.lock.json"
    if not lock_path.is_file():
        raise RuntimeError("model_manifest_lock_missing")
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    for model in payload.get("models", []):
        if isinstance(model, dict) and model.get("model_id") == model_id:
            relative = model.get("snapshot_path")
            if not isinstance(relative, str):
                break
            candidate = (cache / relative).resolve()
            if cache not in candidate.parents or not candidate.is_dir():
                break
            return candidate
    raise RuntimeError(f"model_snapshot_missing:{model_id}")


def _load_for_download(spec: ModelSpec, cache: Path, providers: list[str]) -> Path:
    try:
        from huggingface_hub import snapshot_download

        snapshot = snapshot_download(
            repo_id=spec.source_repo,
            revision=spec.revision,
            cache_dir=str(cache),
            allow_patterns=["*.json", "*.onnx", "*.txt", "*.model"],
            local_files_only=False,
        )
        snapshot_path = Path(snapshot).resolve()
        common = {
            "model_name": spec.model_id,
            "cache_dir": str(cache),
            "specific_model_path": str(snapshot_path),
            "local_files_only": True,
        }
        if spec.role in {"dense", "code_dense"}:
            from fastembed import TextEmbedding
            TextEmbedding(**common, providers=providers)
        elif spec.role == "sparse":
            from fastembed import SparseTextEmbedding
            SparseTextEmbedding(**common, providers=["CPUExecutionProvider"])
        else:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            TextCrossEncoder(**common, providers=providers)
        return snapshot_path
    except ImportError as exc:
        raise RuntimeError("install the matching CPU or CUDA retrieval requirements first") from exc


def _hash_files(root: Path, *, exclude: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name not in exclude):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result
