from __future__ import annotations

import os
import logging
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
from backend.app.observability.context import current_trace_context


router = APIRouter()
logger = logging.getLogger(__name__)


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


def shutdown_retrieval_runtime() -> None:
    if get_retrieval_service.cache_info().currsize:
        service = get_retrieval_service()
        if service.vector_sync_service is not None:
            service.vector_sync_service.vector_store.close()
    get_retrieval_service.cache_clear()
    get_answer_generator.cache_clear()


def _optional_vector_sync_service() -> VectorSyncService | None:
    if not _bool_env("RETRIEVAL_DENSE_ENABLED", False):
        return None
    model_id = os.getenv(
        "RETRIEVAL_DENSE_MODEL_ID",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    model_revision = os.getenv("RETRIEVAL_DENSE_MODEL_REVISION", "pinned-by-deployment")
    dimension = int(os.getenv("RETRIEVAL_DENSE_DIMENSION", "384"))
    cache_dir = os.getenv("RETRIEVAL_MODEL_CACHE_DIR", "data/models")
    providers = _execution_providers()
    try:
        client = _inference_client()
        if client is not None:
            from backend.app.retrieval.inference_backend import RemoteEmbedder
            embedder = RemoteEmbedder(client, model_id, model_revision, dimension)
        else:
            embedder = FastEmbedEmbedder(
                model_id=model_id,
                model_revision=model_revision,
                dimension=dimension,
                cache_dir=cache_dir,
                offline=_bool_env("RETRIEVAL_OFFLINE", True),
                providers=providers,
                specific_model_path=_snapshot_path(cache_dir, model_id),
            )
        sparse_provider = (
            _sparse_provider(client, cache_dir)
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
    except Exception as exc:
        logger.exception("dense/vector retrieval runtime initialization failed")
        if os.getenv("CRA_CONFIG_PATH"):
            raise RuntimeError("retrieval_vector_runtime_unavailable") from exc
        return None


def _optional_reranker():
    if not _bool_env("RETRIEVAL_RERANKER_ENABLED", False):
        return None
    try:
        client = _inference_client()
        if client is not None:
            from backend.app.retrieval.inference_backend import RemoteReranker
            return RemoteReranker(client)
        return FastEmbedCrossEncoderReranker(
            model_id=(model_id := os.getenv(
                "RETRIEVAL_RERANKER_MODEL_ID", "BAAI/bge-reranker-base"
            )),
            cache_dir=os.getenv("RETRIEVAL_MODEL_CACHE_DIR", "data/models"),
            offline=_bool_env("RETRIEVAL_OFFLINE", True),
            providers=_execution_providers(),
            specific_model_path=str(_snapshot_path(
                os.getenv("RETRIEVAL_MODEL_CACHE_DIR", "data/models"), model_id,
            )),
        )
    except Exception as exc:
        logger.exception("reranker runtime initialization failed")
        if os.getenv("CRA_CONFIG_PATH"):
            raise RuntimeError("retrieval_reranker_runtime_unavailable") from exc
        return None


def _execution_providers() -> list[str]:
    config_path = os.getenv("CRA_CONFIG_PATH")
    if config_path:
        from backend.app.config.application import ApplicationConfig
        return ApplicationConfig.load(config_path).compute.execution_providers
    return ["CPUExecutionProvider"]


def _inference_client():
    config_path = os.getenv("CRA_CONFIG_PATH")
    if not config_path:
        return None
    from backend.app.config.application import ApplicationConfig
    from backend.app.retrieval.inference_backend import UnixSocketInferenceClient

    socket_path = ApplicationConfig.load(config_path).compute.inference_socket
    return UnixSocketInferenceClient(socket_path) if socket_path else None


def _sparse_provider(client, cache_dir: str):
    if client is not None:
        from backend.app.retrieval.inference_backend import RemoteSparseProvider
        return RemoteSparseProvider(client)
    return QdrantBM25SparseProvider(
        cache_dir=cache_dir, offline=_bool_env("RETRIEVAL_OFFLINE", True),
        providers=["CPUExecutionProvider"],
        specific_model_path=str(_snapshot_path(cache_dir, "Qdrant/bm25")),
    )


def _snapshot_path(cache_dir: str, model_id: str):
    from backend.app.retrieval.model_manager import model_snapshot_path, verify_models

    errors = verify_models(cache_dir)
    if errors:
        raise RuntimeError(errors[0])
    return model_snapshot_path(cache_dir, model_id)


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
    context = current_trace_context()
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
                "trace_id": context.trace_id if context else None,
            }
        },
    )


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
