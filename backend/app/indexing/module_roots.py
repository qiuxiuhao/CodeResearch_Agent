from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath

from backend.app.indexing.path_normalizer import normalize_index_path


def discover_module_roots(repo_path: str | Path) -> list[str]:
    root = Path(repo_path)
    configured = _configured_roots(root / "pyproject.toml")
    roots: list[str] = []
    configured = sorted(set(configured), key=lambda item: (-len(PurePosixPath(item).parts), item))
    for candidate in [*configured, "src", "."]:
        normalized = "." if candidate in {"", "."} else normalize_index_path(candidate)
        physical = root if normalized == "." else root / normalized
        if physical.is_dir() and normalized not in roots:
            roots.append(normalized)
    return roots or ["."]


def module_name_for_path(
    path: str,
    module_roots: list[str],
    repo_path: str | Path | None = None,
) -> tuple[str, list[str]]:
    normalized = normalize_index_path(path)
    candidates: list[str] = []
    for module_root in module_roots:
        relative = _relative_to_root(normalized, module_root)
        if relative is None or not relative.endswith(".py"):
            continue
        if module_root == "." and repo_path is not None and not _classic_package_is_valid(Path(repo_path), relative):
            continue
        module_path = relative[:-3]
        if module_path.endswith("/__init__"):
            module_path = module_path[: -len("/__init__")]
        module = module_path.replace("/", ".").strip(".")
        if module:
            candidates.append(module)
            # Roots are ordered by explicit configuration, src layout, then
            # repository root. The first valid match is authoritative; lower
            # priority roots must not create a false ambiguity (for example
            # ``src/pkg/a.py`` also being representable as ``src.pkg.a``).
            break
    if not candidates:
        fallback = normalized[:-3].replace("/", ".") if normalized.endswith(".py") else normalized.replace("/", ".")
        return fallback, [] if repo_path is not None else [fallback]
    return candidates[0], candidates


def _relative_to_root(path: str, module_root: str) -> str | None:
    if module_root == ".":
        return path
    root = PurePosixPath(module_root)
    candidate = PurePosixPath(path)
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return None


def _configured_roots(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    roots: list[str] = []
    setuptools_where = (
        payload.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("where", [])
    )
    if isinstance(setuptools_where, str):
        setuptools_where = [setuptools_where]
    if isinstance(setuptools_where, list):
        roots.extend(item for item in setuptools_where if isinstance(item, str))
    poetry_packages = payload.get("tool", {}).get("poetry", {}).get("packages", [])
    if isinstance(poetry_packages, list):
        for item in poetry_packages:
            if isinstance(item, dict) and isinstance(item.get("from"), str):
                roots.append(item["from"])
    return roots


def _classic_package_is_valid(repo_path: Path, relative_path: str) -> bool:
    parents = PurePosixPath(relative_path).parts[:-1]
    current = repo_path
    for part in parents:
        current /= part
        if not (current / "__init__.py").is_file():
            return False
    return True
