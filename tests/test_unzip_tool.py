from __future__ import annotations

import zipfile

from backend.app.tools.unzip_tool import unzip_project


def test_unzip_project_extracts_safe_files(tmp_path):
    zip_path = tmp_path / "project.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("main.py", "def main():\n    return 1\n")
        archive.writestr("weights/model.pth", "binary")

    result = unzip_project(zip_path, tmp_path / "outputs", task_id="task_test")

    assert result.success
    assert result.extracted_file_count == 1
    assert (tmp_path / "outputs" / "task_test" / "source" / "main.py").exists()
    assert result.skipped_files == [{"path": "weights/model.pth", "reason": "dangerous_extension"}]


def test_unzip_project_skips_path_traversal(tmp_path):
    zip_path = tmp_path / "project.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../evil.py", "print('bad')\n")
        archive.writestr("safe.py", "print('ok')\n")

    result = unzip_project(zip_path, tmp_path / "outputs", task_id="task_test")

    assert result.success
    assert result.extracted_file_count == 1
    assert not (tmp_path / "outputs" / "evil.py").exists()
    assert {"path": "../evil.py", "reason": "path_traversal"} in result.skipped_files

