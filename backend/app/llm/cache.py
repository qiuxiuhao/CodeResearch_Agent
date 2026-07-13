from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class LLMCache:
    def __init__(self, path: str, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled

    def get(self, provider: str, model: str, prompt_version: str, task_type: str, input_hash: str) -> dict | None:
        if not self.enabled:
            return None
        self._ensure_schema()
        with sqlite3.connect(self.path, timeout=30) as conn:
            row = conn.execute(
                "SELECT response_json FROM llm_cache WHERE provider=? AND model=? AND prompt_version=? AND task_type=? AND input_hash=?",
                (provider, model, prompt_version, task_type, input_hash),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(
        self, provider: str, model: str, prompt_version: str, task_type: str, input_hash: str, response: dict
    ) -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute(
                """INSERT INTO llm_cache(provider, model, prompt_version, task_type, input_hash, response_json)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(provider, model, prompt_version, task_type, input_hash)
                DO UPDATE SET response_json=excluded.response_json""",
                (provider, model, prompt_version, task_type, input_hash, json.dumps(response, ensure_ascii=False)),
            )

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=30) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS llm_cache(
                provider TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                task_type TEXT NOT NULL, input_hash TEXT NOT NULL, response_json TEXT NOT NULL,
                PRIMARY KEY(provider, model, prompt_version, task_type, input_hash))"""
            )
