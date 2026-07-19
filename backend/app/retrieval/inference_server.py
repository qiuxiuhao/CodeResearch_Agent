from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

from fastapi import FastAPI, HTTPException

from backend.app.config.application import ApplicationConfig

from .inference_backend import (
    DenseRequest, DenseResponse, RerankRequest, RerankResponse,
    SparseItem, SparseRequest, SparseResponse,
)
from .model_manager import load_manifest, model_snapshot_path, verify_models


class InferenceRuntime:
    def __init__(self, config: ApplicationConfig) -> None:
        self.config = config
        self.dense = None
        self.sparse = None
        self.reranker = None
        # One CUDA execution group owns the loaded models. Extra callers receive a stable
        # overload response instead of multiplying model copies or exhausting VRAM.
        self._slots = BoundedSemaphore(value=1)
        self._counter_lock = Lock()
        self._active_requests = 0

    def start(self) -> None:
        errors = verify_models(self.config.compute.model_cache)
        if errors:
            raise RuntimeError(errors[0])
        if self.config.compute.device == "cuda":
            import onnxruntime as ort
            providers = ort.get_available_providers()
            if not providers or providers[0] != "CUDAExecutionProvider":
                raise RuntimeError("cuda_execution_provider_unavailable")
        manifest = load_manifest(self.config.model_manifest)
        by_role = {item.role: item for item in manifest.models}
        providers = self.config.compute.execution_providers
        try:
            from fastembed import SparseTextEmbedding, TextEmbedding
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:
            raise RuntimeError("retrieval_runtime_not_installed") from exc
        self.dense = TextEmbedding(
            model_name=by_role["dense"].model_id,
            cache_dir=str(self.config.compute.model_cache), providers=providers,
            local_files_only=True,
            specific_model_path=str(model_snapshot_path(
                self.config.compute.model_cache, by_role["dense"].model_id,
            )),
        )
        self.sparse = SparseTextEmbedding(
            model_name=by_role["sparse"].model_id,
            cache_dir=str(self.config.compute.model_cache),
            providers=["CPUExecutionProvider"], local_files_only=True,
            specific_model_path=str(model_snapshot_path(
                self.config.compute.model_cache, by_role["sparse"].model_id,
            )),
        )
        self.reranker = TextCrossEncoder(
            model_name=by_role["reranker"].model_id,
            cache_dir=str(self.config.compute.model_cache), providers=providers,
            local_files_only=True,
            specific_model_path=str(model_snapshot_path(
                self.config.compute.model_cache, by_role["reranker"].model_id,
            )),
        )

    def health(self) -> dict[str, object]:
        return {
            "status": "ok" if all((self.dense, self.sparse, self.reranker)) else "starting",
            "device": self.config.compute.device,
            "execution_providers": self.config.compute.execution_providers,
            "model_cache": str(self.config.compute.model_cache),
            "active_requests": self._active_requests,
            "max_concurrency": 1,
            "max_batch_size": self.config.compute.batch_size,
        }

    @contextmanager
    def execution_slot(self):
        if not self._slots.acquire(blocking=False):
            raise HTTPException(429, detail="inference_queue_full")
        with self._counter_lock:
            self._active_requests += 1
        try:
            yield
        finally:
            with self._counter_lock:
                self._active_requests -= 1
            self._slots.release()


def create_app(config: ApplicationConfig) -> FastAPI:
    runtime = InferenceRuntime(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        yield

    app = FastAPI(title="CodeResearch Inference Runtime", version="1", lifespan=lifespan)

    @app.get("/health")
    def health():
        return runtime.health()

    @app.post("/v1/embed/dense", response_model=DenseResponse)
    def dense(payload: DenseRequest):
        _bounded(payload.texts, runtime.config.compute.batch_size)
        if runtime.dense is None:
            raise HTTPException(503, detail="inference_not_ready")
        with runtime.execution_slot():
            return DenseResponse(vectors=[list(item) for item in runtime.dense.embed(payload.texts)])

    @app.post("/v1/embed/sparse", response_model=SparseResponse)
    def sparse(payload: SparseRequest):
        _bounded(payload.texts, runtime.config.compute.batch_size)
        if runtime.sparse is None:
            raise HTTPException(503, detail="inference_not_ready")
        with runtime.execution_slot():
            values = list(runtime.sparse.embed(payload.texts))
        return SparseResponse(vectors=[
            SparseItem(indices=[int(v) for v in item.indices], values=[float(v) for v in item.values])
            for item in values
        ])

    @app.post("/v1/rerank", response_model=RerankResponse)
    def rerank(payload: RerankRequest):
        _bounded(payload.texts, runtime.config.compute.batch_size)
        if runtime.reranker is None:
            raise HTTPException(503, detail="inference_not_ready")
        with runtime.execution_slot():
            return RerankResponse(scores=[
                float(v) for v in runtime.reranker.rerank(payload.query, payload.texts)
            ])

    return app


def _bounded(texts: list[str], max_batch_size: int) -> None:
    if len(texts) > max_batch_size:
        raise HTTPException(413, detail="inference_batch_too_large")
    if any(len(value) > 65_536 for value in texts) or sum(len(value) for value in texts) > 2_000_000:
        raise HTTPException(413, detail="inference_payload_too_large")


def _config_from_environment() -> ApplicationConfig:
    path = os.getenv("CRA_CONFIG_PATH")
    if not path:
        raise RuntimeError("CRA_CONFIG_PATH is required for inference runtime")
    return ApplicationConfig.load(path)


app = create_app(_config_from_environment())
