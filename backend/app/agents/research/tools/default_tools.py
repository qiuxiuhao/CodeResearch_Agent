from __future__ import annotations

import asyncio
from collections import deque

from backend.app.agents.research.tool_registry import (
    GetAlignmentInput,
    GetCallPathInput,
    GetGraphNeighborsInput,
    GetModelFlowInput,
    GetSymbolSourceInput,
    InspectConfigInput,
    SearchHybridInput,
    SearchPaperInput,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    run_sync_tool,
)
from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.retrieval_service import RetrievalService
from backend.app.retrieval.schemas import PublicRetrievalFilter, RetrievalFilter, RetrievalSearchRequest


def build_default_tool_registry(
    retrieval_service: RetrievalService,
    read_store: RetrievalReadStore,
    alignment_read_service=None,
) -> ToolRegistry:
    registry = ToolRegistry()

    async def search_hybrid(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = SearchHybridInput.model_validate(tool_input)
        result = await run_sync_tool(
            retrieval_service.search,
            context.repo_id,
            RetrievalSearchRequest(
                text=value.query,
                index_version_id=context.index_version_id,
                query_type=value.query_type,
                filters=value.filters,
                top_k=value.top_k,
                include_graph=value.include_graph,
                include_reranker=value.include_reranker,
            ),
        )
        candidates = result.candidates[: value.top_k]
        return ToolResult(
            entity_ids=_unique(item.entity_id for item in candidates),
            chunk_ids=_unique(item.chunk_id for item in candidates),
            evidence_ids=_unique(ev.evidence_id for item in candidates for ev in item.evidence),
            summary=_candidate_summary(candidates),
            warnings=result.warnings,
        )

    async def get_symbol_source(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = GetSymbolSourceInput.model_validate(tool_input)
        filters = RetrievalFilter(
            repo_id=context.repo_id,
            index_version_id=context.index_version_id,
            qualified_names=[value.qualified_name] if value.qualified_name else [],
        )
        documents = await run_sync_tool(read_store.list_documents, filters)
        if value.entity_id:
            documents = [item for item in documents if item.entity_id == value.entity_id]
        documents = documents[:1]
        evidence = await run_sync_tool(
            read_store.evidence_for_entities,
            index_version_id=context.index_version_id,
            entity_ids=[item.entity_id for item in documents],
        )
        return ToolResult(
            entity_ids=[item.entity_id for item in documents],
            chunk_ids=[item.chunk_id for item in documents],
            evidence_ids=_unique(
                ev.evidence_id for item in documents for ev in evidence.get(item.entity_id, [])
            ),
            summary="\n\n".join(item.text[: value.max_characters] for item in documents)[:2_000],
        )

    async def get_graph_neighbors(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = GetGraphNeighborsInput.model_validate(tool_input)
        edges = await run_sync_tool(
            read_store.graph_neighbors,
            repo_id=context.repo_id,
            index_version_id=context.index_version_id,
            entity_ids=value.entity_ids,
            edge_types=value.edge_types,
            include_incoming=value.direction != "outgoing",
        )
        if value.direction == "incoming":
            wanted = set(value.entity_ids)
            edges = [edge for edge in edges if edge.target_id in wanted]
        edges = edges[: value.max_results]
        entities = _unique(
            item for edge in edges for item in (edge.source_id, edge.target_id) if item
        )
        unresolved = [edge.unresolved_symbol for edge in edges if edge.target_id is None]
        return ToolResult(
            entity_ids=entities,
            edge_ids=[edge.id for edge in edges],
            evidence_ids=_unique(ref for edge in edges for ref in edge.evidence_refs),
            summary=(
                "; ".join(
                    f"{edge.source_id} --{edge.edge_type}--> {edge.target_id or edge.unresolved_symbol}"
                    for edge in edges
                )[:1_800]
                + (f"; unresolved={','.join(item for item in unresolved if item)}" if unresolved else "")
            )[:2_000],
        )

    async def get_call_path(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = GetCallPathInput.model_validate(tool_input)
        paths = await _call_paths(read_store, context, value)
        if not paths:
            return ToolResult(summary="No resolved call path was found.", warnings=["path_unreachable"])
        selected = paths[: value.max_paths]
        edges = [edge for path in selected for edge in path]
        return ToolResult(
            entity_ids=_unique(
                item for edge in edges for item in (edge.source_id, edge.target_id) if item
            ),
            edge_ids=_unique(edge.id for edge in edges),
            evidence_ids=_unique(ref for edge in edges for ref in edge.evidence_refs),
            summary=" | ".join(
                " -> ".join([path[0].source_id, *[edge.target_id or "unresolved" for edge in path]])
                for path in selected
            )[:2_000],
        )

    async def get_model_flow(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = GetModelFlowInput.model_validate(tool_input)
        delegated = GetGraphNeighborsInput(
            entity_ids=[value.entity_id],
            edge_types=["DEFINES", "CONTAINS", "CALLS", "INSTANTIATES", "NEXT_MODULE"],
            direction=value.direction,
            max_results=value.max_nodes,
        )
        return await get_graph_neighbors(delegated, context)

    async def search_paper(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = SearchPaperInput.model_validate(tool_input)
        return await search_hybrid(
            SearchHybridInput(
                query=value.query,
                query_type="paper_alignment",
                filters=PublicRetrievalFilter(entity_kinds=["paper"]),
                top_k=value.top_k,
            ),
            context,
        )

    async def get_alignment(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = GetAlignmentInput.model_validate(tool_input)
        legacy = await get_graph_neighbors(
            GetGraphNeighborsInput(
                entity_ids=[value.entity_id],
                edge_types=["ALIGNS_WITH"],
                direction="both",
                max_results=value.max_results,
            ),
            context,
        )
        legacy_items = [
            {
                "entity_id": entity_id,
                "source": "legacy",
                "authority_level": "legacy_heuristic",
                "evidence_role": "alignment_hypothesis",
                "evidence_ids": legacy.evidence_ids,
            }
            for entity_id in legacy.entity_ids
            if entity_id != value.entity_id
        ]
        derived_items: list[dict] = []
        warnings = list(legacy.warnings)
        if alignment_read_service is not None:
            try:
                items = await run_sync_tool(
                    alignment_read_service.get_for_entity,
                    repo_id=context.repo_id,
                    index_version_id=context.index_version_id,
                    entity_id=value.entity_id,
                    max_results=value.max_results,
                )
                derived_items = [item.model_dump(mode="json") for item in items]
            except Exception:
                warnings.append("v1.7_alignment_unavailable_fallback_legacy")
        combined = [*legacy_items, *derived_items][: value.max_results]
        summaries = [legacy.summary, *[str(item.get("summary", "")) for item in derived_items]]
        derived_entity_ids = [
            str(item["entity_id"])
            for item in derived_items
            if item.get("entity_id")
        ]
        derived_evidence_ids = [
            str(evidence_id)
            for item in derived_items
            for evidence_id in item.get("evidence_ids", [])
        ]
        return legacy.model_copy(
            update={
                "alignment_items": combined,
                "entity_ids": list(dict.fromkeys([*legacy.entity_ids, *derived_entity_ids]))[
                    : value.max_results
                ],
                "evidence_ids": list(
                    dict.fromkeys([*legacy.evidence_ids, *derived_evidence_ids])
                ),
                "warnings": warnings,
                "summary": "\n".join(item for item in summaries if item)[:2_000],
            }
        )

    async def inspect_config(tool_input, context: ToolExecutionContext) -> ToolResult:
        value = InspectConfigInput.model_validate(tool_input)
        filters = PublicRetrievalFilter(
            entity_types=["config"],
            paths=[value.path] if value.path else [],
        )
        return await search_hybrid(
            SearchHybridInput(
                query=value.query,
                query_type="configuration",
                filters=filters,
                top_k=value.max_results,
            ),
            context,
        )

    specs = [
        ToolSpec("search_hybrid", SearchHybridInput, search_hybrid, 8.0, 30),
        ToolSpec("get_symbol_source", GetSymbolSourceInput, get_symbol_source, 3.0, 1),
        ToolSpec("get_graph_neighbors", GetGraphNeighborsInput, get_graph_neighbors, 3.0, 30),
        ToolSpec("get_call_path", GetCallPathInput, get_call_path, 4.0, 5),
        ToolSpec("get_model_flow", GetModelFlowInput, get_model_flow, 4.0, 30),
        ToolSpec("search_paper", SearchPaperInput, search_paper, 8.0, 20),
        ToolSpec("get_alignment", GetAlignmentInput, get_alignment, 3.0, 20),
        ToolSpec("inspect_config", InspectConfigInput, inspect_config, 3.0, 10),
    ]
    for spec in specs:
        registry.register(spec)
    return registry


async def _call_paths(read_store, context, value):
    queue = deque([(value.source_entity_id, [])])
    paths = []
    best_depth = {value.source_entity_id: 0}
    while queue and len(paths) < value.max_paths:
        current, path = queue.popleft()
        if len(path) >= value.max_hops:
            continue
        edges = await run_sync_tool(
            read_store.graph_neighbors,
            repo_id=context.repo_id,
            index_version_id=context.index_version_id,
            entity_ids=[current],
            edge_types=["CALLS", "INSTANTIATES"],
            include_incoming=False,
        )
        for edge in edges:
            if not edge.target_id:
                continue
            next_path = [*path, edge]
            if edge.target_id == value.target_entity_id:
                paths.append(next_path)
                continue
            depth = len(next_path)
            if depth < value.max_hops and best_depth.get(edge.target_id, 99) > depth:
                best_depth[edge.target_id] = depth
                queue.append((edge.target_id, next_path))
    return paths


def _unique(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _candidate_summary(candidates) -> str:
    return "\n".join(
        f"{item.qualified_name or item.path or item.entity_id}: {item.text[:240]}"
        for item in candidates
    )[:2_000]
