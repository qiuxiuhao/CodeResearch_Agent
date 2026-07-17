from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _copy_script(name: str, target_root: Path) -> Path:
    scripts = target_root / "scripts"
    scripts.mkdir(parents=True)
    target = scripts / name
    shutil.copy2(ROOT / "scripts" / name, target)
    return target


def _write(path: Path, content: str = "keep") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_clean_removes_only_rebuildable_artifacts(tmp_path: Path):
    root = tmp_path / "repo"
    script = _copy_script("clean.sh", root)

    removable = [
        _write(root / "backend" / "__pycache__" / "module.cpython-311.pyc"),
        _write(root / "backend" / "orphan.pyc"),
        _write(root / ".pytest_cache" / "state"),
        _write(root / "code_research_agent.egg-info" / "PKG-INFO"),
        _write(root / "frontend" / "node_modules" / "package" / "index.js"),
        _write(root / "frontend" / "dist" / "index.html"),
        _write(root / "frontend" / ".vite" / "cache"),
        _write(root / "frontend" / "nested" / "tsconfig.tsbuildinfo"),
    ]
    protected = [
        _write(root / "data" / "cache.sqlite3", "database"),
        _write(root / "data" / "python_function_library.sqlite3", "knowledge"),
        _write(root / "outputs" / "task_123" / "report.md", "report"),
        _write(root / "outputs" / "task_123" / "teaching_diagram.png", "diagram"),
        _write(root / "outputs" / "task_123" / "source" / "__pycache__" / "module.pyc", "task cache"),
        _write(root / "outputs" / "task_123" / "source" / "package.egg-info" / "PKG-INFO", "task metadata"),
        _write(root / "outputs" / "user-report.md", "user report"),
        _write(root / ".coderesearch_agent" / "secrets.json", "provider secret"),
    ]

    result = subprocess.run(["bash", str(script)], cwd=root, check=True, capture_output=True, text=True)

    assert all(not path.exists() for path in removable)
    assert all(path.exists() for path in protected)
    assert "were preserved" in result.stdout


def test_runtime_reset_requires_exact_confirmation_and_preserves_secrets(tmp_path: Path):
    root = tmp_path / "repo"
    script = _copy_script("reset_runtime_data.sh", root)
    database = _write(root / "data" / "cache.sqlite3", "database")
    sidecar = _write(root / "data" / "cache.sqlite3-wal", "sidecar")
    knowledge = _write(root / "data" / "python_function_library.sqlite3", "knowledge")
    task_report = _write(root / "outputs" / "task_123" / "report.md", "report")
    task_diagram = _write(root / "outputs" / "task_123" / "diagram.png", "diagram")
    unrelated_data = _write(root / "data" / "keep.json")
    unrelated_output = _write(root / "outputs" / "user-report.md")
    provider_secret = _write(root / ".coderesearch_agent" / "secrets.json", "provider secret")

    refused = subprocess.run(["bash", str(script)], cwd=root, capture_output=True, text=True)
    assert refused.returncode == 2
    assert "Runtime data was NOT deleted" in refused.stderr
    assert all(path.exists() for path in (database, sidecar, knowledge, task_report, task_diagram))

    confirmed = subprocess.run(
        ["bash", str(script), "--confirm-delete-runtime-data"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "WARNING" in confirmed.stdout
    assert str(database.relative_to(root)) in confirmed.stdout
    assert str(task_report.parent.relative_to(root)) in confirmed.stdout
    assert all(not path.exists() for path in (database, sidecar, knowledge, task_report, task_diagram))
    assert all(path.exists() for path in (unrelated_data, unrelated_output, provider_secret))
