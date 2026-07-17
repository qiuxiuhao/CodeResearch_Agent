from __future__ import annotations

import sqlite3
from pathlib import Path


LATEST_SCHEMA_VERSION = 1
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migrate_database(path: str | Path) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(f"Structured index schema {current} is newer than supported {LATEST_SCHEMA_VERSION}.")
        for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
            migration = MIGRATIONS_DIR / f"{version:03d}_structured_index.sql"
            if not migration.is_file():
                raise RuntimeError(f"Missing structured index migration: {migration.name}")
            try:
                connection.executescript(migration.read_text(encoding="utf-8"))
            except Exception:
                connection.rollback()
                raise
        actual = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if actual != LATEST_SCHEMA_VERSION:
            raise RuntimeError(f"Structured index migration ended at unexpected version {actual}.")
