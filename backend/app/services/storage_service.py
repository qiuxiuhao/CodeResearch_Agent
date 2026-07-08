from __future__ import annotations

from pathlib import Path


def ensure_output_root(output_root: str | Path = "outputs") -> Path:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def task_output_dir(output_root: str | Path, task_id: str) -> Path:
    return Path(output_root) / task_id

