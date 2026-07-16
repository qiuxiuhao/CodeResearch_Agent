#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


FIXED_TIMESTAMP = (2020, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644 << 16


def build_example_zip(source: Path, destination: Path) -> Path:
    """Build a byte-for-byte deterministic ZIP from the expanded example source."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in source.rglob("*") if path.is_file())
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = ZipInfo(path.relative_to(source).as_posix(), date_time=FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = FILE_MODE
            info.create_system = 3
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the deterministic example project ZIP.")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path("examples/small_pytorch_project"))
    args = parser.parse_args()
    build_example_zip(args.source, args.destination)


if __name__ == "__main__":
    main()
