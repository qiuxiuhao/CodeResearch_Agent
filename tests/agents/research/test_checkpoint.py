from __future__ import annotations

import asyncio
from pydantic import BaseModel

from backend.app.persistence.research_checkpoint import ResearchCheckpointRuntime


def test_sqlite_checkpoint_safe_versions_and_round_trip(tmp_path) -> None:
    asyncio.run(_round_trip(tmp_path))


async def _round_trip(tmp_path) -> None:
    runtime = ResearchCheckpointRuntime(tmp_path / "checkpoint.sqlite3")
    saver = await runtime.start()
    try:
        assert saver is not None
        assert await runtime.checkpoint_exists("missing") is False
    finally:
        await runtime.close()


class _UnapprovedCheckpointType(BaseModel):
    value: str


def test_checkpoint_rejects_unapproved_msgpack_type(tmp_path) -> None:
    asyncio.run(_reject_unapproved(tmp_path))


async def _reject_unapproved(tmp_path) -> None:
    runtime = ResearchCheckpointRuntime(tmp_path / "checkpoint.sqlite3")
    saver = await runtime.start()
    try:
        serializer = saver.serde
        payload = serializer.dumps_typed(_UnapprovedCheckpointType(value="secret"))
        restored = serializer.loads_typed(payload)
        assert not isinstance(restored, _UnapprovedCheckpointType)
        assert serializer._allowed_msgpack_modules is not True
        assert serializer.pickle_fallback is False
    finally:
        await runtime.close()
