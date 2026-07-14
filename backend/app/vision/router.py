from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Iterable

from pydantic import ValidationError

from backend.app.llm.budget import BudgetManager
from backend.app.schemas.paper_figure import FigureAnalysis, VisionCallMetadata, VisionEvidenceItem
from backend.app.vision.cache import VisionCache
from backend.app.vision.config import VisionSettings
from backend.app.vision.exceptions import VisionProviderError
from backend.app.vision.providers.base_provider import BaseVisionProvider
from backend.app.vision.types import VisionRequest, VisionRouterResult


class VisionModelRouter:
    def __init__(self, settings: VisionSettings, providers: Iterable[BaseVisionProvider], budget: BudgetManager, cache: VisionCache) -> None:
        self.settings = settings
        self.providers = list(providers)
        self.budget = budget
        self.cache = cache

    @property
    def has_available_provider(self) -> bool:
        return any(provider.configured for provider in self.providers)

    def analyze(
        self,
        *,
        context_id: str,
        system_prompt: str,
        input_payload: dict,
        image_bytes: bytes,
        mime_type: str,
        evidence_catalog: list[VisionEvidenceItem],
    ) -> VisionRouterResult:
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        caption = str(input_payload.get("caption", {}).get("text", ""))
        caption_hash = hashlib.sha256(caption.encode("utf-8")).hexdigest()
        canonical = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        valid_evidence = {item.evidence_id for item in evidence_catalog}
        valid_contributions = {
            str(item.get("id")) for item in input_payload.get("contribution_catalog", []) if item.get("id")
        }
        warnings: list[dict] = []
        available = [(index, provider) for index, provider in enumerate(self.providers) if provider.configured]
        if not available:
            return VisionRouterResult(None, [_warning("vlm_provider_unconfigured", context_id)])

        attempts = 0
        for provider_index, provider in available:
            try:
                cached = self.cache.get(
                    provider.name, provider.model, self.settings.prompt_version, "paper_figure_analyze",
                    image_hash, caption_hash, input_hash, self.settings.schema_version,
                )
            except Exception:
                cached = None
                warnings.append(_warning(
                    "vlm_cache_error", context_id, provider=provider.name,
                    message="Vision cache read failed; continuing without cache.",
                ))
            if cached is not None:
                try:
                    value = FigureAnalysis.model_validate(cached)
                    _validate_value(value, context_id, valid_evidence, valid_contributions)
                    self.budget.record_cache_hit()
                    metadata = _metadata(
                        "fallback" if provider_index else "success", provider.name, provider.model, attempts,
                        provider_index > 0, image_hash, self.settings.prompt_version, cache_hit=True,
                    )
                    return VisionRouterResult(value.model_copy(update={"metadata": metadata}), warnings)
                except (ValidationError, ValueError):
                    warnings.append(_warning("vlm_cache_error", context_id, provider=provider.name))

            for attempt in range(self.settings.max_retries + 1):
                attempts += 1
                reservation = self.budget.try_reserve_provider_request(
                    provider.name, "paper_figure_analyze", context_id,
                    retry=attempt > 0, fallback=provider_index > 0 and attempt == 0,
                )
                if not reservation.allowed:
                    warnings.append(_warning("vlm_provider_request_budget_exceeded", context_id, provider=provider.name))
                    return VisionRouterResult(None, warnings)
                try:
                    response = provider.analyze_figure(VisionRequest(
                        context_id=context_id, system_prompt=system_prompt, input_payload=input_payload,
                        image_bytes=image_bytes, mime_type=mime_type, response_model=FigureAnalysis,
                        max_output_tokens=self.settings.max_output_tokens,
                    ))
                    value = FigureAnalysis.model_validate(response.data)
                    _validate_value(value, context_id, valid_evidence, valid_contributions)
                    self.budget.record_request_result(reservation.reservation_id, "success")
                    metadata = _metadata(
                        "fallback" if provider_index else "success", provider.name, provider.model, attempts,
                        provider_index > 0, image_hash, self.settings.prompt_version,
                        latency_ms=response.latency_ms, input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens, total_tokens=response.total_tokens,
                        warning_codes=[item["code"] for item in warnings],
                    )
                    value = value.model_copy(update={"metadata": metadata})
                    try:
                        self.cache.set(
                            provider.name, provider.model, self.settings.prompt_version, "paper_figure_analyze",
                            image_hash, caption_hash, input_hash, self.settings.schema_version,
                            value.model_dump(mode="json"),
                        )
                    except Exception:
                        warnings.append(_warning(
                            "vlm_cache_error", context_id, provider=provider.name,
                            message="Vision cache write failed; keeping the validated analysis result.",
                        ))
                        metadata = metadata.model_copy(update={
                            "warning_codes": [*metadata.warning_codes, "vlm_cache_error"]
                        })
                        value = value.model_copy(update={"metadata": metadata})
                    return VisionRouterResult(value, warnings)
                except ValidationError:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning("vlm_schema_validation_failed", context_id, provider=provider.name, attempt=attempt + 1))
                except ValueError as exc:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning("vlm_evidence_validation_failed", context_id, provider=provider.name, attempt=attempt + 1, message=str(exc)))
                except VisionProviderError as exc:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning(exc.code, context_id, provider=provider.name, attempt=attempt + 1, message=str(exc)))
                    if not exc.recoverable:
                        break
                except Exception:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning(
                        "vlm_unexpected_provider_error", context_id, provider=provider.name,
                        attempt=attempt + 1,
                        message="Unexpected Vision Provider failure; retry or fallback may continue.",
                    ))
        warnings.append(_warning("vlm_all_providers_failed", context_id))
        return VisionRouterResult(None, warnings)


def _validate_value(value: FigureAnalysis, context_id: str, valid_evidence: set[str], valid_contributions: set[str]) -> None:
    if value.figure_id != context_id:
        raise ValueError("VLM returned an unexpected figure_id.")
    if any(ref not in valid_evidence for ref in value.evidence_refs):
        raise ValueError("VLM returned an unknown evidence reference.")
    if any(item.contribution_id not in valid_contributions for item in value.contribution_candidates):
        raise ValueError("VLM returned an unknown contribution candidate.")


def _metadata(
    status: str, provider: str, model: str, attempts: int, fallback_used: bool,
    image_hash: str, prompt_version: str, *, cache_hit: bool = False,
    latency_ms: int | None = None, input_tokens: int | None = None,
    output_tokens: int | None = None, total_tokens: int | None = None,
    warning_codes: list[str] | None = None,
) -> VisionCallMetadata:
    return VisionCallMetadata(
        status=status, provider=provider, model=model, attempts=attempts, fallback_used=fallback_used,
        latency_ms=latency_ms, input_tokens=input_tokens, output_tokens=output_tokens,
        total_tokens=total_tokens, image_hash=image_hash, generated_at=datetime.now(UTC),
        cache_hit=cache_hit, prompt_version=prompt_version, warning_codes=warning_codes or [],
    )


def _warning(code: str, context_id: str, *, provider: str | None = None, attempt: int | None = None, message: str | None = None) -> dict:
    return {
        "code": code, "task_type": "paper_figure_analyze", "context_id": context_id,
        "provider": provider, "attempt": attempt, "message": message or code.replace("_", " "),
        "recoverable": True,
    }
