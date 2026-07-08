from __future__ import annotations

from pathlib import Path


SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".ipynb_checkpoints",
    "outputs",
    "logs",
    "checkpoints",
    "weights",
}

SKIP_DIR_PARTS = {
    ("data", "raw"),
    ("datasets", "raw"),
}

SKIP_EXTENSIONS = {
    ".pt",
    ".pth",
    ".ckpt",
    ".onnx",
    ".mp4",
    ".avi",
    ".mov",
    ".png",
    ".jpg",
    ".jpeg",
    ".npy",
    ".npz",
    ".zip",
    ".tar",
    ".gz",
}

DANGEROUS_EXTENSIONS = SKIP_EXTENSIONS


def resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_within_directory(base_dir: str | Path, target: str | Path) -> bool:
    base = resolve_path(base_dir)
    candidate = resolve_path(target)
    return candidate == base or base in candidate.parents


def normalize_relative_path(path: str | Path) -> str:
    return Path(path).as_posix()


def should_skip_dir(relative_parts: tuple[str, ...]) -> bool:
    if not relative_parts:
        return False
    if any(part in SKIP_DIR_NAMES for part in relative_parts):
        return True
    return any(_contains_sequence(relative_parts, sequence) for sequence in SKIP_DIR_PARTS)


def should_skip_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SKIP_EXTENSIONS


def _contains_sequence(parts: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    if len(sequence) > len(parts):
        return False
    for index in range(0, len(parts) - len(sequence) + 1):
        if parts[index : index + len(sequence)] == sequence:
            return True
    return False
