from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from backend.app.agents.graph import ANALYSIS_GRAPH_STEPS
from backend.app.services.analysis_service import run_analysis


def test_index_node_order_is_after_rule_alignment_before_model_enhancement() -> None:
    steps = [item["id"] for item in ANALYSIS_GRAPH_STEPS]
    assert steps.index("paper_code_align") < steps.index("structured_index_build")
    assert steps.index("structured_index_build") < steps.index("file_explain_llm")
    assert steps.index("structured_index_build") < steps.index("paper_figure_analyze_vlm")


def test_structured_index_is_opt_in_and_preserves_legacy_outputs(tmp_path) -> None:
    archive = Path("examples/small_pytorch_project.zip")
    disabled = run_analysis(archive, tmp_path / "disabled", tmp_path / "library.sqlite3")
    disabled_output = Path(disabled["output_dir"])
    assert not (disabled_output / "index_manifest.json").exists()

    db_path = tmp_path / "structured.sqlite3"
    enabled = run_analysis(
        archive, tmp_path / "enabled", tmp_path / "library.sqlite3",
        structured_index_enabled=True, repository_key="examples/small", structured_index_db_path=db_path,
    )
    output = Path(enabled["output_dir"])
    manifest = json.loads((output / "index_manifest.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "active"
    assert manifest["repository_identity_mode"] == "explicit"
    assert manifest["file_count"] > 0
    assert manifest["code_entity_count"] > 0
    assert manifest["chunk_count"] > 0
    for legacy in ("parsed_files.json", "file_analysis.json", "function_analysis.json", "report.md"):
        assert (output / legacy).exists()
    for legacy_json in ("parsed_files.json", "file_analysis.json", "function_analysis.json"):
        assert json.loads((output / legacy_json).read_text(encoding="utf-8")) == json.loads(
            (disabled_output / legacy_json).read_text(encoding="utf-8")
        )
    enabled_report = (output / "report.md").read_text(encoding="utf-8").replace(enabled["repo_path"], "<repo>")
    disabled_report = (disabled_output / "report.md").read_text(encoding="utf-8").replace(
        disabled["repo_path"], "<repo>"
    )
    assert enabled_report == disabled_report
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == manifest["file_count"]
        assert connection.execute("SELECT COUNT(*) FROM symbol_chunks").fetchone()[0] == manifest["chunk_count"]

    reused = run_analysis(
        archive, tmp_path / "enabled-reuse", tmp_path / "library.sqlite3",
        structured_index_enabled=True, repository_key="examples/small", structured_index_db_path=db_path,
    )
    assert reused["index_version_id"] == enabled["index_version_id"]
    assert reused["index_manifest"]["status"] == "reused"


def test_task_scoped_identity_does_not_merge_same_zip_across_tasks(tmp_path) -> None:
    archive = Path("examples/small_pytorch_project.zip")
    db_path = tmp_path / "structured.sqlite3"
    first = run_analysis(
        archive, tmp_path / "one", tmp_path / "library.sqlite3",
        structured_index_enabled=True, structured_index_db_path=db_path,
    )
    second = run_analysis(
        archive, tmp_path / "two", tmp_path / "library.sqlite3",
        structured_index_enabled=True, structured_index_db_path=db_path,
    )

    assert first["repo_id"] != second["repo_id"]
    assert first["index_manifest"]["repository_identity_mode"] == "task_scoped"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM repositories").fetchone()[0] == 2


def test_file_change_and_deletion_create_clean_active_snapshot(tmp_path) -> None:
    archive = tmp_path / "repo.zip"
    db_path = tmp_path / "structured.sqlite3"

    def write_archive(files: dict[str, str]) -> None:
        with zipfile.ZipFile(archive, "w") as handle:
            for name, content in files.items():
                handle.writestr(f"repo/{name}", content)

    write_archive({"a.py": "def a():\n    return 1\n", "deleted.py": "VALUE = 1\n"})
    first = run_analysis(
        archive, tmp_path / "first", tmp_path / "library.sqlite3",
        structured_index_enabled=True, repository_key="versioned/repo", structured_index_db_path=db_path,
    )
    write_archive({"a.py": "def a():\n    return 2\n", "new.py": "def new():\n    return 3\n"})
    second = run_analysis(
        archive, tmp_path / "second", tmp_path / "library.sqlite3",
        structured_index_enabled=True, repository_key="versioned/repo", structured_index_db_path=db_path,
    )

    assert first["index_version_id"] != second["index_version_id"]
    assert second["index_manifest"]["index_sequence"] == first["index_manifest"]["index_sequence"] + 1
    with sqlite3.connect(db_path) as connection:
        statuses = dict(connection.execute("SELECT index_version_id, status FROM index_versions"))
        active_paths = {
            row[0] for row in connection.execute(
                "SELECT path FROM indexed_files WHERE index_version_id=?", (second["index_version_id"],)
            )
        }
    assert statuses[first["index_version_id"]] == "superseded"
    assert statuses[second["index_version_id"]] == "active"
    assert not any(path.endswith("deleted.py") for path in active_paths)
    assert active_paths == {"repo/a.py", "repo/new.py"}
