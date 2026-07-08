from __future__ import annotations

from pathlib import Path

from backend.app.schemas.repo import RepoIndex
from backend.app.utils.path_utils import (
    normalize_relative_path,
    resolve_path,
    should_skip_dir,
    should_skip_file,
)


CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def scan_repository(repo_path: str | Path, task_id: str | None = None) -> RepoIndex:
    root = resolve_path(repo_path)
    skipped_files: list[dict] = []
    python_files: list[str] = []
    config_file_candidates: list[str] = []

    file_tree = _build_tree(root, root, skipped_files, python_files, config_file_candidates)
    repo_index = RepoIndex(
        task_id=task_id,
        repo_path=str(root),
        file_tree=file_tree,
        python_files=sorted(python_files),
        entry_file_candidates=_filter_candidates(python_files, _is_entry_file),
        model_file_candidates=_filter_candidates(python_files, _is_model_file),
        train_file_candidates=_filter_candidates(python_files, _is_train_file),
        infer_file_candidates=_filter_candidates(python_files, _is_infer_file),
        config_file_candidates=sorted(config_file_candidates),
        skipped_files=skipped_files,
    )
    return repo_index


def _build_tree(
    path: Path,
    root: Path,
    skipped_files: list[dict],
    python_files: list[str],
    config_file_candidates: list[str],
) -> dict:
    relative = "." if path == root else normalize_relative_path(path.relative_to(root))
    if path.is_file():
        if should_skip_file(path):
            skipped_files.append({"path": relative, "reason": "skipped_extension"})
        else:
            if path.suffix == ".py":
                python_files.append(relative)
            if path.suffix.lower() in CONFIG_EXTENSIONS or _looks_like_config(relative):
                config_file_candidates.append(relative)
        return {"name": path.name, "path": relative, "type": "file"}

    children: list[dict] = []
    for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        child_relative_parts = child.relative_to(root).parts
        if child.is_dir() and should_skip_dir(child_relative_parts):
            skipped_files.append({"path": normalize_relative_path(child.relative_to(root)), "reason": "skipped_directory"})
            continue
        if child.is_file() and should_skip_file(child):
            skipped_files.append({"path": normalize_relative_path(child.relative_to(root)), "reason": "skipped_extension"})
            continue
        children.append(_build_tree(child, root, skipped_files, python_files, config_file_candidates))
    return {"name": path.name, "path": relative, "type": "directory", "children": children}


def _filter_candidates(paths: list[str], predicate) -> list[str]:
    return sorted(path for path in paths if predicate(path))


def _is_entry_file(path: str) -> bool:
    name = Path(path).name.lower()
    return name in {"main.py", "app.py", "run.py", "cli.py", "__main__.py"}


def _is_model_file(path: str) -> bool:
    lowered = path.lower()
    name = Path(path).name.lower()
    if name == "__init__.py":
        return False
    return (
        "model" in lowered
        or "models/" in lowered
        or "network" in name
        or "module" in name
        or "backbone" in name
    )


def _is_train_file(path: str) -> bool:
    name = Path(path).name.lower()
    return "train" in name or name in {"trainer.py", "fit.py"}


def _is_infer_file(path: str) -> bool:
    name = Path(path).name.lower()
    return any(keyword in name for keyword in ("infer", "predict", "demo", "eval", "test"))


def _looks_like_config(path: str) -> bool:
    name = Path(path).name.lower()
    return "config" in name or "settings" in name
