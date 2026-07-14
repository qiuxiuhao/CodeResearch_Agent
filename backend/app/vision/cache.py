from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class VisionCache:
    def __init__(self, path: str, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled

    def get(
        self, provider: str, model: str, prompt_version: str, task_type: str,
        image_hash: str, caption_hash: str, input_hash: str, schema_version: str,
    ) -> dict | None:
        if not self.enabled:
            return None
        self._ensure_schema()
        with sqlite3.connect(self.path, timeout=30) as conn:
            row = conn.execute(
                "SELECT response_json FROM vision_cache_v2 WHERE provider=? AND model=? AND prompt_version=? AND task_type=? AND image_hash=? AND caption_hash=? AND input_hash=? AND schema_version=?",
                (provider, model, prompt_version, task_type, image_hash, caption_hash, input_hash, schema_version),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(
        self, provider: str, model: str, prompt_version: str, task_type: str,
        image_hash: str, caption_hash: str, input_hash: str, schema_version: str, response: dict,
    ) -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute(
                """INSERT INTO vision_cache_v2(provider, model, prompt_version, task_type, image_hash, caption_hash, input_hash, schema_version, response_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(provider, model, prompt_version, task_type, image_hash, caption_hash, input_hash, schema_version)
                DO UPDATE SET response_json=excluded.response_json""",
                (provider, model, prompt_version, task_type, image_hash, caption_hash, input_hash, schema_version, json.dumps(response, ensure_ascii=False)),
            )

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS vision_cache_v2(
                provider TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, task_type TEXT NOT NULL,
                image_hash TEXT NOT NULL, caption_hash TEXT NOT NULL, input_hash TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                response_json TEXT NOT NULL,
                PRIMARY KEY(provider, model, prompt_version, task_type, image_hash, caption_hash, input_hash, schema_version))"""
            )
