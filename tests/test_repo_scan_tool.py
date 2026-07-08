from __future__ import annotations

from backend.app.tools.repo_scan_tool import scan_repository


def test_scan_repository_finds_candidates_and_skips_dirs(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "models" / "__init__.py").write_text("from .simple_model import M\n", encoding="utf-8")
    (tmp_path / "models" / "simple_model.py").write_text("class M:\n    pass\n", encoding="utf-8")
    (tmp_path / "data" / "dataset.py").write_text("class D:\n    pass\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("def train():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    (tmp_path / "data" / "raw").mkdir()
    (tmp_path / "data" / "raw" / "ignored.py").write_text("bad = True\n", encoding="utf-8")
    (tmp_path / "weights").mkdir()
    (tmp_path / "weights" / "model.py").write_text("bad = True\n", encoding="utf-8")

    result = scan_repository(tmp_path, task_id="task_scan")

    assert result.python_files == ["data/dataset.py", "main.py", "models/__init__.py", "models/simple_model.py", "train.py"]
    assert result.entry_file_candidates == ["main.py"]
    assert result.model_file_candidates == ["models/simple_model.py"]
    assert "models/__init__.py" not in result.model_file_candidates
    assert result.train_file_candidates == ["train.py"]
    assert result.config_file_candidates == ["config.yaml"]
    assert {"path": "data/raw", "reason": "skipped_directory"} in result.skipped_files
    assert {"path": "weights", "reason": "skipped_directory"} in result.skipped_files
