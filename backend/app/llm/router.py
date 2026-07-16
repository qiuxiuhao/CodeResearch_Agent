from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Callable, Iterable

from pydantic import BaseModel, ValidationError

from backend.app.llm.budget import BudgetManager
from backend.app.llm.cache import LLMCache
from backend.app.llm.config import LLMSettings
from backend.app.llm.evidence import validate_evidence_refs
from backend.app.llm.exceptions import ProviderError
from backend.app.llm.privacy import sanitize_payload, truncate_payload
from backend.app.llm.providers.base_provider import BaseLLMProvider
from backend.app.llm.types import LLMTaskType, ProviderRequest, RouterResult
from backend.app.schemas.llm_explanation import EvidenceItem, LLMCallMetadata


class ModelRouter:
    def __init__(
        self,
        settings: LLMSettings,
        providers: Iterable[BaseLLMProvider],
        budget: BudgetManager,
        cache: LLMCache,
    ) -> None:
        self.settings = settings
        self.providers = list(providers)
        self.budget = budget
        self.cache = cache

    def generate_structured(
        self,
        *,
        task_type: LLMTaskType,
        context_id: str,
        system_prompt: str,
        input_payload: dict,
        response_model: type[BaseModel],
        evidence_catalog: list[EvidenceItem],
        prompt_version: str = "1.1",
        identity_validator: Callable[[BaseModel], bool] | None = None,
        result_validator: Callable[[BaseModel], None] | None = None,
    ) -> RouterResult:
        sanitized, redaction_count = sanitize_payload(input_payload)
        sanitized, input_truncated = truncate_payload(sanitized, self.settings.max_input_chars)
        canonical = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        warnings: list[dict] = []
        if redaction_count:
            warnings.append(_warning("llm_input_redacted", task_type, context_id, message=f"Redacted {redaction_count} sensitive value(s)."))
        if input_truncated:
            warnings.append(_warning("llm_input_truncated", task_type, context_id))
        available = [(index, provider) for index, provider in enumerate(self.providers) if provider.configured]
        if not available:
            return RouterResult(None, [*warnings, _warning("llm_provider_unconfigured", task_type, context_id)])

        total_attempts = 0
        for provider_index, provider in available:
            try:
                cached = self.cache.get(provider.name, provider.model, prompt_version, task_type, input_hash)
            except Exception:
                cached = None
                warnings.append(_warning(
                    "llm_cache_error", task_type, context_id, provider=provider.name,
                    message="LLM cache read failed; continuing without cache.",
                ))
            if cached is not None:
                try:
                    value = response_model.model_validate(cached)
                    if not validate_evidence_refs(_all_evidence_refs(value.model_dump()), evidence_catalog):
                        raise ValueError("invalid cached evidence refs")
                    if identity_validator is not None and not identity_validator(value):
                        raise ValueError("invalid cached entity identity")
                    if result_validator is not None:
                        result_validator(value)
                    self.budget.record_cache_hit()
                    metadata = _metadata(
                        task_type, "fallback" if provider_index else "success", provider.name, provider.model,
                        total_attempts, provider_index > 0, input_hash, prompt_version, input_truncated,
                        cache_hit=True, warning_codes=[warning["code"] for warning in warnings],
                    )
                    return RouterResult(value.model_copy(update={"metadata": metadata}), warnings)
                except Exception:
                    warnings.append(_warning("llm_cache_error", task_type, context_id, provider=provider.name))

            max_retries = int(getattr(provider, "max_retries", self.settings.max_retries))
            max_output_tokens = int(getattr(provider, "max_output_tokens", self.settings.max_output_tokens))
            for attempt in range(max_retries + 1):
                total_attempts += 1
                reservation = self.budget.try_reserve_provider_request(
                    provider.name, task_type, context_id, retry=attempt > 0, fallback=provider_index > 0 and attempt == 0
                )
                if not reservation.allowed:
                    warnings.append(_warning("llm_provider_request_budget_exceeded", task_type, context_id, provider=provider.name))
                    return RouterResult(None, warnings)
                try:
                    response = provider.generate(ProviderRequest(
                        task_type=task_type,
                        system_prompt=system_prompt,
                        input_payload=sanitized,
                        response_model=response_model,
                        max_output_tokens=max_output_tokens,
                    ))
                    value = response_model.model_validate(response.data)
                    if not validate_evidence_refs(_all_evidence_refs(value.model_dump()), evidence_catalog):
                        raise ProviderError("llm_invalid_evidence_reference", "Model returned an unknown evidence reference.")
                    if identity_validator is not None and not identity_validator(value):
                        raise ProviderError("llm_identity_validation_failed", "Model returned an unexpected entity identity.")
                    if result_validator is not None:
                        try:
                            result_validator(value)
                        except ValueError as exc:
                            raise ProviderError("llm_invalid_code_link", str(exc)) from exc
                    self.budget.record_request_result(reservation.reservation_id, "success")
                    status = "fallback" if provider_index else "success"
                    codes = [warning["code"] for warning in warnings]
                    metadata = _metadata(
                        task_type, status, provider.name, provider.model, total_attempts, provider_index > 0,
                        input_hash, prompt_version, input_truncated, latency_ms=response.latency_ms,
                        input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens, warning_codes=codes,
                    )
                    value = value.model_copy(update={"metadata": metadata})
                    try:
                        self.cache.set(
                            provider.name, provider.model, prompt_version, task_type, input_hash,
                            value.model_dump(mode="json"),
                        )
                    except Exception:
                        warnings.append(_warning(
                            "llm_cache_error", task_type, context_id, provider=provider.name,
                            message="LLM cache write failed; keeping the validated explanation.",
                        ))
                        metadata = metadata.model_copy(update={
                            "warning_codes": [*metadata.warning_codes, "llm_cache_error"]
                        })
                        value = value.model_copy(update={"metadata": metadata})
                    return RouterResult(value, warnings)
                except ValidationError:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning("llm_schema_validation_failed", task_type, context_id, provider=provider.name, attempt=attempt + 1))
                except ProviderError as exc:
                    self.budget.record_request_result(reservation.reservation_id, "failed")
                    warnings.append(_warning(exc.code, task_type, context_id, provider=provider.name, attempt=attempt + 1, message=str(exc)))
                    if not exc.recoverable:
                        break
        warnings.append(_warning("llm_all_providers_failed", task_type, context_id))
        return RouterResult(None, warnings)

    @property
    def has_available_provider(self) -> bool:
        return any(provider.configured for provider in self.providers)


def _metadata(
    task_type: str, status: str, provider: str, model: str, attempts: int, fallback_used: bool,
    input_hash: str, prompt_version: str, input_truncated: bool, *, cache_hit: bool = False,
    latency_ms: int | None = None, input_tokens: int | None = None, output_tokens: int | None = None,
    total_tokens: int | None = None, warning_codes: list[str] | None = None,
) -> LLMCallMetadata:
    return LLMCallMetadata(
        task_type=task_type, status=status, provider=provider, model=model, attempts=attempts,
        fallback_used=fallback_used, latency_ms=latency_ms, input_tokens=input_tokens,
        output_tokens=output_tokens, total_tokens=total_tokens, input_truncated=input_truncated,
        input_hash=input_hash, generated_at=datetime.now(UTC), cache_hit=cache_hit,
        prompt_version=prompt_version, warning_codes=warning_codes or [],
    )


def _warning(code: str, task_type: str, context_id: str, *, provider: str | None = None, attempt: int | None = None, message: str | None = None) -> dict:
    return {
        "code": code, "task_type": task_type, "context_id": context_id, "provider": provider,
        "attempt": attempt, "message": message or code.replace("_", " "), "recoverable": True,
    }


def _all_evidence_refs(payload: object) -> list[str]:
    refs: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"evidence_refs", "code_evidence_refs"} and isinstance(value, list):
                refs.extend(str(item) for item in value)
            else:
                refs.extend(_all_evidence_refs(value))
    elif isinstance(payload, list):
        for value in payload:
            refs.extend(_all_evidence_refs(value))
    return refs
