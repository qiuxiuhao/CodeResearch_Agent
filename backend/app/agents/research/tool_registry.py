from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from backend.app.agents.research.schemas import AgentError, ToolName
from backend.app.retrieval.schemas import PublicRetrievalFilter, QueryType


_SYNC_CAPACITY = max(1, int(os.getenv("RESEARCH_AGENT_SYNC_TOOL_CAPACITY", "4")))
_SYNC_EXECUTOR: ThreadPoolExecutor | None = None
_SYNC_SLOTS: BoundedSemaphore | None = None


def _sync_runtime() -> tuple[ThreadPoolExecutor, BoundedSemaphore]:
    global _SYNC_EXECUTOR, _SYNC_SLOTS
    if _SYNC_EXECUTOR is None or getattr(_SYNC_EXECUTOR, "_shutdown", False):
        _SYNC_EXECUTOR = ThreadPoolExecutor(
            max_workers=_SYNC_CAPACITY, thread_name_prefix="research-tool"
        )
        _SYNC_SLOTS = BoundedSemaphore(_SYNC_CAPACITY)
    return _SYNC_EXECUTOR, _SYNC_SLOTS


async def run_sync_tool(function, /, *args, **kwargs):
    executor, slots = _sync_runtime()
    if not slots.acquire(blocking=False):
        raise RuntimeError("tool_sync_capacity_exceeded")
    future = executor.submit(function, *args, **kwargs)
    future.add_done_callback(lambda _future: slots.release())
    return await asyncio.wrap_future(future)


def shutdown_sync_tool_executor() -> None:
    global _SYNC_EXECUTOR, _SYNC_SLOTS
    if _SYNC_EXECUTOR is not None:
        _SYNC_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _SYNC_EXECUTOR = None
    _SYNC_SLOTS = None


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchHybridInput(ToolInput):
    query: str = Field(min_length=1, max_length=8_000)
    query_type: QueryType | None = None
    filters: PublicRetrievalFilter = Field(default_factory=PublicRetrievalFilter)
    top_k: int = Field(default=10, ge=1, le=30)
    include_graph: bool = True
    include_reranker: bool = False


class GetSymbolSourceInput(ToolInput):
    entity_id: str | None = None
    qualified_name: str | None = None
    max_characters: int = Field(default=12_000, ge=100, le=12_000)

    def model_post_init(self, __context: object) -> None:
        if bool(self.entity_id) == bool(self.qualified_name):
            raise ValueError("exactly one of entity_id or qualified_name is required")


class GetGraphNeighborsInput(ToolInput):
    entity_ids: list[str] = Field(min_length=1, max_length=10)
    edge_types: list[str] = Field(min_length=1, max_length=20)
    direction: str = Field(default="both", pattern=r"^(incoming|outgoing|both)$")
    max_results: int = Field(default=20, ge=1, le=30)


class GetCallPathInput(ToolInput):
    source_entity_id: str
    target_entity_id: str
    max_hops: int = Field(default=2, ge=1, le=2)
    max_paths: int = Field(default=5, ge=1, le=5)


class GetModelFlowInput(ToolInput):
    entity_id: str
    direction: str = Field(default="both", pattern=r"^(incoming|outgoing|both)$")
    max_nodes: int = Field(default=20, ge=1, le=30)


class SearchPaperInput(ToolInput):
    query: str = Field(min_length=1, max_length=8_000)
    top_k: int = Field(default=10, ge=1, le=20)


class GetAlignmentInput(ToolInput):
    entity_id: str
    max_results: int = Field(default=10, ge=1, le=20)


class InspectConfigInput(ToolInput):
    query: str = Field(min_length=1, max_length=2_000)
    path: str | None = None
    max_results: int = Field(default=10, ge=1, le=10)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_ids: list[str] = Field(default_factory=list, max_length=100)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    edge_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    summary: str = Field(default="", max_length=2_000)
    warnings: list[str] = Field(default_factory=list, max_length=50)

    @property
    def result_count(self) -> int:
        return max(len(self.entity_ids), len(self.chunk_ids), len(self.edge_ids), len(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    run_id: str
    repo_id: str
    index_version_id: str
    trace_id: str | None = None
    cancel_check: Callable[[], bool] | None = None


ToolHandler = Callable[[BaseModel, ToolExecutionContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: ToolName
    input_model: type[BaseModel]
    handler: ToolHandler
    timeout_seconds: float
    max_results: int
    output_fields: frozenset[str] = frozenset({"entity_ids", "chunk_ids", "edge_ids", "evidence_ids"})


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    status: str
    result: ToolResult
    latency_ms: float
    error: AgentError | None = None


class ToolRegistry:
    def __init__(self, specs: Mapping[ToolName, ToolSpec] | None = None) -> None:
        self._specs = dict(specs or {})

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: ToolName) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ValueError(f"tool_not_found:{name}") from exc

    def has(self, name: str) -> bool:
        return name in self._specs

    async def invoke(
        self,
        name: ToolName,
        tool_input: BaseModel,
        context: ToolExecutionContext,
    ) -> ToolInvocationResult:
        spec = self.get(name)
        if context.cancel_check and context.cancel_check():
            return ToolInvocationResult(
                "failed",
                ToolResult(),
                0.0,
                AgentError(error_code="agent_cancelled", message="Run cancellation was requested."),
            )
        started = perf_counter()
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                result = await spec.handler(tool_input, context)
        except TimeoutError:
            return ToolInvocationResult(
                "timeout",
                ToolResult(),
                (perf_counter() - started) * 1000,
                AgentError(error_code="tool_timeout", message=f"Tool {name} timed out.", retryable=True),
            )
        except Exception as exc:
            return ToolInvocationResult(
                "failed",
                ToolResult(),
                (perf_counter() - started) * 1000,
                AgentError(error_code="tool_internal_error", message=str(exc), retryable=False),
            )
        if context.cancel_check and context.cancel_check():
            return ToolInvocationResult(
                "failed",
                ToolResult(),
                (perf_counter() - started) * 1000,
                AgentError(error_code="agent_cancelled", message="Late tool result was discarded."),
            )
        status = "success" if result.result_count else "empty"
        return ToolInvocationResult(status, result, (perf_counter() - started) * 1000)

    @property
    def specs(self) -> Mapping[ToolName, ToolSpec]:
        return dict(self._specs)
