from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid4

from backend.app.persistence.fts_generation_store import FTSGenerationError, FTSGenerationStore, FTS_PROFILE_VERSION
from backend.app.persistence.retrieval_read_store import RetrievalReadStore
from backend.app.retrieval.context_builder import ContextBuilder
from backend.app.retrieval.dense_retriever import DenseRetriever
from backend.app.retrieval.fusion import final_rrf, preliminary_rrf
from backend.app.retrieval.graph_retriever import GraphRetriever
from backend.app.retrieval.query_profiler import RuleBasedQueryProfiler
from backend.app.retrieval.reranker import Reranker, fuse_reranker
from backend.app.retrieval.schemas import (
    PublicRetrievalFilter,
    RetrievalCandidate,
    RetrievalConfig,
    RetrievalFilter,
    RetrievalQuery,
    RetrievalResult,
    RetrievalScore,
    RetrievalSearchRequest,
)
from backend.app.retrieval.sparse_retriever import SparseRetriever
from backend.app.retrieval.qdrant_sparse_retriever import QdrantSparseRetriever
from backend.app.retrieval.sync_service import VectorSyncService
from backend.app.observability.context import start_span_or_root


class RetrievalService:
    def __init__(
        self,
        *,
        read_store: RetrievalReadStore,
        fts_store: FTSGenerationStore,
        dense_retriever: DenseRetriever | None = None,
        reranker: Reranker | None = None,
        vector_sync_service: VectorSyncService | None = None,
    ) -> None:
        self.read_store = read_store
        self.fts_store = fts_store
        self.sparse_retriever = SparseRetriever(read_store, fts_store)
        self.dense_retriever = dense_retriever
        self.reranker = reranker
        self.vector_sync_service = vector_sync_service
        self.profiler = RuleBasedQueryProfiler()
        self.graph_retriever = GraphRetriever(read_store)
        self.context_builder = ContextBuilder()

    def search(
        self,
        repo_id: str,
        request: RetrievalSearchRequest,
        *,
        execution: "RetrievalExecutionOverrides | None" = None,
    ) -> RetrievalResult:
        handle = start_span_or_root(
            operation="retrieval.search",
            trace_type="retrieval",
            component="retrieval",
            repo_id=repo_id,
            index_version_id=request.index_version_id,
            attributes={
                "cra.repo.id": repo_id,
                **(
                    {"cra.index.version_id": request.index_version_id}
                    if request.index_version_id else {}
                ),
            },
        )
        with handle:
            result = self._search_impl(repo_id, request, execution=execution)
            handle.event(
                "retrieval.completed",
                attributes={
                    "cra.candidate.count": len(result.candidates),
                    "cra.retrieval.empty": not result.candidates,
                },
            )
            for phase, duration_ms in result.latency_ms.items():
                if phase == "total":
                    continue
                handle.completed_child(
                    _retrieval_operation(phase),
                    component="retrieval",
                    duration_ms=duration_ms,
                    attributes={"cra.latency.phase": phase},
                )
            return result

    def _search_impl(
        self,
        repo_id: str,
        request: RetrievalSearchRequest,
        *,
        execution: "RetrievalExecutionOverrides | None" = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        version_id = self.read_store.resolve_version(repo_id, request.index_version_id)
        filters = _internal_filters(repo_id, version_id, request.filters)
        profile, profile_rule = self.profiler.classify(request.text, request.query_type)
        reranker_enabled = bool(request.include_reranker and self.reranker is not None)
        config = self.profiler.config(
            profile,
            dense_enabled=(self.dense_retriever is not None or self.vector_sync_service is not None),
            reranker_enabled=reranker_enabled,
        )
        config = _apply_request_overrides(config, request)
        config = _apply_execution_overrides(config, execution)
        query = RetrievalQuery(
            query_id=f"query_{uuid4().hex}",
            text=request.text,
            query_type=profile,
            filters=filters,
            top_k=request.top_k,
            include_graph=request.include_graph,
            include_reranker=request.include_reranker,
        )
        warnings: list[str] = []
        vector_generation: str | None = None
        latency: dict[str, float] = {"profile": _elapsed(started)}
        documents = self.read_store.list_documents(filters)
        dense_retriever = self.dense_retriever
        qdrant_sparse_retriever = None
        if self.vector_sync_service is not None:
            vector_started = time.perf_counter()
            try:
                manifest = self.vector_sync_service.sync(
                    repo_id=repo_id,
                    index_version_id=version_id,
                    documents=documents,
                )
                vector_generation = manifest.generation_id
                dense_retriever = DenseRetriever(
                    vector_store=self.vector_sync_service.vector_store,
                    embedder=self.vector_sync_service.embedder,
                    profile=self.vector_sync_service.profile,
                    collection_name=manifest.collection_name,
                )
                if self.vector_sync_service.sparse_provider is not None:
                    qdrant_sparse_retriever = QdrantSparseRetriever(
                        vector_store=self.vector_sync_service.vector_store,
                        sparse_provider=self.vector_sync_service.sparse_provider,
                        profile=self.vector_sync_service.profile,
                        collection_name=manifest.collection_name,
                    )
            except Exception:
                warnings.append("vector_index_unavailable_fallback_to_fts5")
            latency["vector_sync"] = _elapsed(vector_started)
        if config.sparse_enabled and self.fts_store.ready_generation(
            repo_id=repo_id, index_version_id=version_id, profile_hash=FTS_PROFILE_VERSION
        ) is None:
            sync_started = time.perf_counter()
            self.fts_store.sync(
                repo_id=repo_id,
                index_version_id=version_id,
                profile_hash=FTS_PROFILE_VERSION,
                documents=documents,
            )
            latency["sparse_sync"] = _elapsed(sync_started)
        sparse_started = time.perf_counter()
        raw_sparse_hits = []
        if config.sparse_enabled:
            raw_sparse_hits = self.sparse_retriever.retrieve(
                query_text=request.text,
                filters=filters,
                top_k=config.sparse_top_k,
            )
        if qdrant_sparse_retriever is not None:
            try:
                raw_sparse_hits = qdrant_sparse_retriever.retrieve(
                    query_text=request.text,
                    filters=filters,
                    top_k=config.sparse_top_k,
                )
            except Exception:
                warnings.append("qdrant_sparse_unavailable_fallback_to_fts5")
        latency["sparse"] = _elapsed(sparse_started)
        raw_dense_hits = []
        if config.dense_enabled and dense_retriever is not None:
            dense_started = time.perf_counter()
            try:
                raw_dense_hits = dense_retriever.retrieve(
                    query_text=request.text, filters=filters, top_k=config.dense_top_k
                )
            except Exception:
                warnings.append("dense_unavailable_fallback_to_sparse")
            latency["dense"] = _elapsed(dense_started)
        document_map = {document.chunk_id: document for document in documents}
        raw_sparse_hits = _attach_document_text(raw_sparse_hits, document_map)
        raw_dense_hits = _attach_document_text(raw_dense_hits, document_map)
        pre_started = time.perf_counter()
        pre_fusion_candidates = preliminary_rrf(raw_dense_hits, raw_sparse_hits, config)
        latency["preliminary_rrf"] = _elapsed(pre_started)
        graph_hits = []
        relationship_notes: list[str] = []
        if config.graph_enabled and request.include_graph is not False:
            graph_started = time.perf_counter()
            graph_result = self.graph_retriever.expand(
                query=query,
                config=config,
                graph_seed_candidates=pre_fusion_candidates[: config.graph_seed_k],
            )
            graph_hits = graph_result.hits
            graph_hits = _attach_document_text(graph_hits, document_map)
            relationship_notes = graph_result.relationship_notes
            latency["graph"] = _elapsed(graph_started)
        final_started = time.perf_counter()
        final_fusion_candidates = final_rrf(raw_dense_hits, raw_sparse_hits, graph_hits, config)
        final_candidates, reranker_warnings = fuse_reranker(
            query_text=request.text,
            candidates=final_fusion_candidates,
            config=config,
            reranker=self.reranker,
        )
        latency["final_rrf_and_reranker"] = _elapsed(final_started)
        warnings.extend(reranker_warnings)
        entity_ids = [candidate.candidate.entity_id for candidate in final_candidates]
        evidence_map = self.read_store.evidence_for_entities(
            index_version_id=version_id, entity_ids=entity_ids
        )
        candidates = [
            _public_candidate(item, document_map, evidence_map)
            for item in final_candidates
            if item.candidate.chunk_id in document_map
        ]
        latency["total"] = _elapsed(started)
        if relationship_notes:
            warnings.append(f"graph_relationship_notes:{len(relationship_notes)}")
        warnings.append(f"query_profile_rule:{profile_rule}")
        return RetrievalResult(
            query=query,
            effective_config=config,
            candidates=candidates,
            total_candidates=len(final_fusion_candidates),
            active_index_version_id=version_id,
            vector_index_generation=vector_generation,
            latency_ms=latency,
            warnings=warnings,
        )


def _retrieval_operation(phase: str) -> str:
    return {
        "profile": "retrieval.profile",
        "vector_sync": "retrieval.vector_sync",
        "sparse_sync": "retrieval.fts_sync",
        "sparse": "retrieval.sparse",
        "dense": "retrieval.dense",
        "preliminary_rrf": "retrieval.preliminary_rrf",
        "graph": "retrieval.graph",
        "final_rrf_and_reranker": "retrieval.final_rrf_rerank",
    }.get(phase, f"retrieval.{phase}"[:160])


def _internal_filters(
    repo_id: str, index_version_id: str, public: PublicRetrievalFilter
) -> RetrievalFilter:
    return RetrievalFilter(
        repo_id=repo_id,
        index_version_id=index_version_id,
        **public.model_dump(),
    )


def _apply_request_overrides(config: RetrievalConfig, request: RetrievalSearchRequest) -> RetrievalConfig:
    updates: dict[str, object] = {}
    if request.top_k is not None:
        updates["final_top_k"] = request.top_k
    if request.include_graph is False:
        updates["graph_enabled"] = False
    if request.include_reranker is False and config.reranker_enabled:
        updates.update(reranker_enabled=False, hybrid_weight=1.0, reranker_weight=0.0)
    return config.model_copy(update=updates)


@dataclass(frozen=True, slots=True)
class RetrievalExecutionOverrides:
    dense_enabled: bool | None = None
    sparse_enabled: bool | None = None
    graph_enabled: bool | None = None
    reranker_enabled: bool | None = None


def _apply_execution_overrides(
    config: RetrievalConfig,
    execution: RetrievalExecutionOverrides | None,
) -> RetrievalConfig:
    if execution is None:
        return config
    updates = {
        name: value
        for name, value in (
            ("dense_enabled", execution.dense_enabled),
            ("sparse_enabled", execution.sparse_enabled),
            ("graph_enabled", execution.graph_enabled),
            ("reranker_enabled", execution.reranker_enabled),
        )
        if value is not None
    }
    if updates.get("reranker_enabled") is False:
        updates.update(hybrid_weight=1.0, reranker_weight=0.0)
    return config.model_copy(update=updates)


def _public_candidate(item, documents, evidence_map) -> RetrievalCandidate:
    fused = item.candidate
    document = documents[fused.chunk_id]
    source_values = {hit.source: hit.source_score for hit in fused.hits}
    source_ranks = {hit.source: hit.source_rank for hit in fused.hits}
    sources = sorted({hit.source for hit in fused.hits})
    return RetrievalCandidate(
        **document.model_dump(),
        score=RetrievalScore(
            dense=source_values.get("dense"),
            sparse=source_values.get("sparse"),
            graph=source_values.get("graph"),
            preliminary_rrf=fused.preliminary_rrf,
            final_rrf=fused.final_rrf or 0.0,
            reranker=item.reranker_score,
            reranker_normalized=item.reranker_normalized,
            final=item.final_score,
            source_ranks=source_ranks,
            contributions=item.contributions,
        ),
        sources=sources,
        graph_path_edge_ids=fused.graph_path_edge_ids,
        evidence=evidence_map.get(fused.entity_id, []),
    )


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _attach_document_text(hits, documents):
    enriched = []
    for hit in hits:
        document = documents.get(hit.chunk_id)
        if document is None:
            enriched.append(hit)
            continue
        enriched.append(hit.model_copy(update={
            "metadata": {**hit.metadata, "text": document.text},
        }))
    return enriched
