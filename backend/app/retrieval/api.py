from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.persistence.fts_generation_store import FTSGenerationError, FTSGenerationStore
from backend.app.persistence.retrieval_read_store import RetrievalReadError, RetrievalReadStore
from backend.app.retrieval.retrieval_service import RetrievalService
from backend.app.retrieval.schemas import ResearchQueryRequest, RetrievalSearchRequest
from backend.app.services.research_query_service import ResearchQueryService
from backend.app.services.research_answer_generator import ProviderAnswerGenerator
from backend.app.llm.config import LLMSettings
from backend.app.llm.runtime import create_llm_runtime
from backend.app.retrieval.embedder import FastEmbedEmbedder, VectorProfile
from backend.app.retrieval.reranker import FastEmbedCrossEncoderReranker
from backend.app.retrieval.sparse_vector import QdrantBM25SparseProvider
from backend.app.retrieval.sync_service import VectorSyncService
from backend.app.retrieval.vector_store import QdrantLocalVectorStore


router = APIRouter()


@lru_cache(maxsize=1)
def get_retrieval_service() -> RetrievalService:
    vector_sync_service = _optional_vector_sync_service()
    reranker = _optional_reranker()
    return RetrievalService(
        read_store=RetrievalReadStore(os.getenv("STRUCTURED_INDEX_DB_PATH", "data/structured_index.sqlite3")),
        fts_store=FTSGenerationStore(os.getenv("RETRIEVAL_FTS_DB_PATH", "data/retrieval_fts.sqlite3")),
        vector_sync_service=vector_sync_service,
        reranker=reranker,
    )


def _optional_vector_sync_service() -> VectorSyncService | None:
    if not _bool_env("RETRIEVAL_DENSE_ENABLED", False):
        return None
    model_id = os.getenv(
        "RETRIEVAL_DENSE_MODEL_ID",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    model_revision = os.getenv("RETRIEVAL_DENSE_MODEL_REVISION", "pinned-by-deployment")
    dimension = int(os.getenv("RETRIEVAL_DENSE_DIMENSION", "384"))
    try:
        embedder = FastEmbedEmbedder(
            model_id=model_id,
            model_revision=model_revision,
            dimension=dimension,
            cache_dir=os.getenv("RETRIEVAL_MODEL_CACHE_DIR", "data/models"),
            offline=_bool_env("RETRIEVAL_OFFLINE", True),
        )
        sparse_provider = (
            QdrantBM25SparseProvider()
            if _bool_env("RETRIEVAL_QDRANT_SPARSE_ENABLED", False)
            else None
        )
        profile = VectorProfile(
            model_id=model_id,
            model_revision=model_revision,
            dimension=dimension,
            sparse_model_id=(sparse_provider.model_id if sparse_provider else None),
            sparse_model_version=(sparse_provider.model_version if sparse_provider else None),
        )
        return VectorSyncService(
            vector_store=QdrantLocalVectorStore(os.getenv("QDRANT_LOCAL_PATH", "data/qdrant")),
            embedder=embedder,
            profile=profile,
            sparse_provider=sparse_provider,
            manifest_root=os.getenv("RETRIEVAL_MANIFEST_ROOT", "data/retrieval/manifests"),
        )
    except Exception:
        return None


def _optional_reranker():
    if not _bool_env("RETRIEVAL_RERANKER_ENABLED", False):
        return None
    try:
        return FastEmbedCrossEncoderReranker(
            model_id=os.getenv("RETRIEVAL_RERANKER_MODEL_ID", "BAAI/bge-reranker-base"),
            cache_dir=os.getenv("RETRIEVAL_MODEL_CACHE_DIR", "data/models"),
            offline=_bool_env("RETRIEVAL_OFFLINE", True),
        )
    except Exception:
        return None


@lru_cache(maxsize=1)
def get_answer_generator() -> ProviderAnswerGenerator | None:
    settings = LLMSettings.from_env(text_llm_enabled=True)
    runtime = create_llm_runtime(settings)
    if not runtime.router.has_available_provider:
        return None
    return ProviderAnswerGenerator(runtime.router)


@router.post("/repositories/{repo_id}/retrieval/search")
def retrieval_search(repo_id: str, request: RetrievalSearchRequest):
    disabled = _disabled_response()
    if disabled:
        return disabled
    try:
        return get_retrieval_service().search(repo_id, request)
    except (RetrievalReadError, FTSGenerationError) as exc:
        return _error_response(exc.error_code, str(exc), retryable=False, repo_id=repo_id)


@router.post("/repositories/{repo_id}/research/query")
def research_query(repo_id: str, request: ResearchQueryRequest):
    disabled = _disabled_response()
    if disabled:
        return disabled
    try:
        generator = get_answer_generator() if request.external_text_consent else None
        return ResearchQueryService(
            get_retrieval_service(), answer_generator=generator
        ).query(repo_id, request)
    except (RetrievalReadError, FTSGenerationError) as exc:
        return _error_response(exc.error_code, str(exc), retryable=False, repo_id=repo_id)


@router.get("/repositories/{repo_id}/retrieval/config")
def retrieval_config(repo_id: str):
    disabled = _disabled_response()
    if disabled:
        return disabled
    try:
        version_id = get_retrieval_service().read_store.resolve_version(repo_id)
    except RetrievalReadError as exc:
        return _error_response(exc.error_code, str(exc), retryable=False, repo_id=repo_id)
    return {
        "repo_id": repo_id,
        "active_index_version_id": version_id,
        "retrieval_enabled": True,
        "dense_enabled": (
            get_retrieval_service().dense_retriever is not None
            or get_retrieval_service().vector_sync_service is not None
        ),
        "reranker_enabled": get_retrieval_service().reranker is not None,
        "offline": _bool_env("RETRIEVAL_OFFLINE", True),
        "limits": {"top_k": 100, "graph_max_hops": 2, "token_budget": 6000},
    }


def _disabled_response() -> JSONResponse | None:
    if _bool_env("RETRIEVAL_ENABLED", False):
        return None
    return _error_response(
        "retrieval_disabled",
        "Retrieval is disabled. Set RETRIEVAL_ENABLED=true to enable it.",
        retryable=False,
    )


def _error_response(
    error_code: str,
    message: str,
    *,
    retryable: bool,
    repo_id: str | None = None,
) -> JSONResponse:
    status = 503 if error_code in {"retrieval_disabled", "retrieval_busy"} else 404
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "error_code": error_code,
                "component": "retrieval",
                "message": message,
                "retryable": retryable,
                "context": {"repo_id": repo_id} if repo_id else {},
                "trace_id": None,
            }
        },
    )


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
