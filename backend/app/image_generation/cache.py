from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class ImageGenerationCache:
    def __init__(self, db_path: str, asset_root: str, *, enabled: bool = True) -> None:
        self.db_path = Path(db_path)
        self.asset_root = Path(asset_root)
        self.enabled = enabled

    def get(self, key: dict[str, Any]) -> dict | None:
        if not self.enabled:
            return None
        self._ensure_schema()
        cache_key = _key_hash(key)
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM image_generation_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: dict[str, Any], image_bytes: bytes, metadata: dict[str, Any]) -> dict:
        if not self.enabled:
            return metadata
        self._ensure_schema()
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        asset_path = self.asset_root / sha256[:2] / f"{sha256}.png"
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(image_bytes)
        cache_key = _key_hash(key)
        value = {**metadata, "cached_asset_path": str(asset_path), "sha256": sha256}
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT OR REPLACE INTO image_generation_cache(cache_key, metadata_json)
                   VALUES (?, ?)""",
                (cache_key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )
        return value

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS image_generation_cache(
                    cache_key TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL
                )"""
            )


class TeachingDiagramReviewCache:
    def __init__(self, db_path: str, *, enabled: bool = True) -> None:
        self.db_path = Path(db_path)
        self.enabled = enabled

    def get(self, key: dict[str, Any]) -> dict | None:
        if not self.enabled:
            return None
        self._ensure_schema()
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT review_json FROM teaching_diagram_review_cache WHERE cache_key=?",
                (_key_hash(key),),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: dict[str, Any], review: dict) -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """INSERT OR REPLACE INTO teaching_diagram_review_cache(cache_key, review_json)
                   VALUES (?, ?)""",
                (_key_hash(key), json.dumps(review, ensure_ascii=False, sort_keys=True)),
            )

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS teaching_diagram_review_cache(
                    cache_key TEXT PRIMARY KEY,
                    review_json TEXT NOT NULL
                )"""
            )


def _key_hash(key: dict[str, Any]) -> str:
    canonical = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
