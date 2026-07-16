from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

from scripts.build_example_zip import build_example_zip


SOURCE = Path("examples/small_pytorch_project")
COMMITTED_ZIP = Path("examples/small_pytorch_project.zip")


def _source_hashes() -> dict[str, str]:
    return {
        path.relative_to(SOURCE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(SOURCE.rglob("*"))
        if path.is_file()
    }


def _zip_hashes(path: Path) -> dict[str, str]:
    with ZipFile(path) as archive:
        return {
            info.filename: hashlib.sha256(archive.read(info)).hexdigest()
            for info in archive.infolist()
            if not info.is_dir()
        }


def test_committed_zip_content_matches_expanded_source():
    assert _zip_hashes(COMMITTED_ZIP) == _source_hashes()


def test_example_zip_generation_is_byte_deterministic(tmp_path: Path):
    first = build_example_zip(SOURCE, tmp_path / "first.zip")
    second = build_example_zip(SOURCE, tmp_path / "second.zip")

    assert first.read_bytes() == second.read_bytes()
    assert _zip_hashes(first) == _source_hashes()
