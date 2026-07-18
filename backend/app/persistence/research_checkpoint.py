from __future__ import annotations

import importlib.metadata
from pathlib import Path

from backend.app.agents.research import schemas as agent_schemas
from backend.app.retrieval import schemas as retrieval_schemas
from backend.app.observability.context import current_trace_context, get_default_recorder, start_span_or_root


MIN_LANGGRAPH_VERSION = (1, 0, 10)
MIN_SQLITE_CHECKPOINT_VERSION = (3, 0, 1)


class ResearchCheckpointError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ResearchCheckpointRuntime:
    """Owns the AsyncSqliteSaver context for the application lifespan."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.saver = None
        self._connection = None

    async def start(self):
        _require_safe_versions()
        try:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        except ImportError as exc:
            raise ResearchCheckpointError(
                "checkpoint_dependency_missing",
                "Install the optional agent dependency: pip install -e '.[agent]'.",
            ) from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(self.path))
        serializer = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_msgpack_modules=_allowed_checkpoint_types(),
        )
        self.saver = AsyncSqliteSaver(self._connection, serde=serializer)
        await self.saver.setup()
        _validate_serializer(self.saver)
        return self.saver

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self.saver = None

    async def checkpoint_exists(self, thread_id: str) -> bool:
        if self.saver is None:
            return False
        handle = _checkpoint_span("checkpoint.read")
        async with handle:
            config = {"configurable": {"thread_id": thread_id}}
            exists = await self.saver.aget_tuple(config) is not None
            handle.event("checkpoint.read.completed", attributes={"cra.status": "hit" if exists else "miss"})
            if exists:
                handle.artifact("checkpoint", thread_id, role="langgraph_checkpoint")
            return exists

    async def delete_thread(self, thread_id: str) -> None:
        if self.saver is None:
            raise ResearchCheckpointError("checkpoint_unavailable", "Checkpoint runtime is not started.")
        handle = _checkpoint_span("checkpoint.delete")
        async with handle:
            await self.saver.adelete_thread(thread_id)


def _checkpoint_span(operation: str):
    context = current_trace_context()
    if context is None:
        return get_default_recorder().noop_span()
    return start_span_or_root(
        operation=operation,
        trace_type=context.trace_type,
        component="checkpoint",
        attributes={"cra.checkpoint.operation": operation},
    )


def _require_safe_versions() -> None:
    _require_version("langgraph", MIN_LANGGRAPH_VERSION)
    _require_version("langgraph-checkpoint-sqlite", MIN_SQLITE_CHECKPOINT_VERSION)


def _require_version(distribution: str, minimum: tuple[int, ...]) -> None:
    try:
        installed = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ResearchCheckpointError(
            "checkpoint_dependency_missing", f"Required distribution {distribution} is not installed."
        ) from exc
    parsed = tuple(int(part) for part in installed.split("+")[0].split(".")[: len(minimum)])
    if parsed < minimum:
        wanted = ".".join(str(part) for part in minimum)
        raise ResearchCheckpointError(
            "checkpoint_version_unsafe", f"{distribution}>={wanted} is required; found {installed}."
        )


def _validate_serializer(saver) -> None:
    serde = getattr(saver, "serde", None)
    if serde is None:
        raise ResearchCheckpointError(
            "checkpoint_serializer_unsupported", "The selected saver does not expose its serializer."
        )
    # JsonPlusSerializer is the supported LangGraph serializer. State schemas contain only
    # project Pydantic models and JSON-compatible values; handlers, secrets and connections
    # are dependencies of graph closures and are never placed in ResearchState.
    name = type(serde).__name__
    if name not in {"JsonPlusSerializer", "JsonPlusSerializerCompat"}:
        raise ResearchCheckpointError(
            "checkpoint_serializer_unsupported", f"Unsupported checkpoint serializer: {name}."
        )
    if getattr(serde, "pickle_fallback", True):
        raise ResearchCheckpointError(
            "checkpoint_serializer_unsupported", "Checkpoint pickle fallback must be disabled."
        )
    allowed = getattr(serde, "_allowed_msgpack_modules", True)
    if allowed is True or allowed is None:
        raise ResearchCheckpointError(
            "checkpoint_serializer_unsupported", "An explicit msgpack type allowlist is required."
        )


def _allowed_checkpoint_types() -> list[type]:
    names = (
        "AgentError", "AgentTokenUsage", "ExpectedEvidence", "StepOutputRef",
        "ArgumentBinding", "PlanStep", "ResearchPlan", "PlanStepRuntime",
        "ToolObservation", "EvidenceCriterionResult", "EvidenceAssessment",
        "ReplanDecision", "DraftAnswerClaim", "DraftResearchAnswer",
        "ValidatedAnswerClaim", "ValidatedResearchAnswer", "AgentResearchAnswer",
    )
    retrieval_names = ("ContextBundle", "ContextItem", "RetrievalEvidence", "AnswerCitation")
    return [getattr(agent_schemas, name) for name in names] + [
        getattr(retrieval_schemas, name) for name in retrieval_names
    ]
