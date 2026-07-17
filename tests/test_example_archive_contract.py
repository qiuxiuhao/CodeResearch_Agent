from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

from scripts.build_example_zip import build_example_zip


SOURCE = Path("examples/small_pytorch_project")
COMMITTED_ZIP = Path("examples/small_pytorch_project.zip")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_generated_zip_is_byte_identical_to_committed_zip(tmp_path: Path):
    generated = build_example_zip(SOURCE, tmp_path / "small_pytorch_project.zip")

    assert generated.read_bytes() == COMMITTED_ZIP.read_bytes()
    assert _sha256(generated) == _sha256(COMMITTED_ZIP)
    assert _zip_hashes(generated) == _source_hashes()
