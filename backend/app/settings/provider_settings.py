from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.app.image_generation.config import ImageProviderSettings
from backend.app.image_generation.providers.qwen_image_provider import QwenImageProvider
from backend.app.image_generation.providers.seedream_provider import SeedreamProvider
from backend.app.image_generation.types import ImageGenerationRequest
from backend.app.llm.config import ProviderSettings as LLMProviderSettings
from backend.app.llm.providers.deepseek_provider import DeepSeekProvider
from backend.app.llm.providers.qwen_provider import QwenProvider
from backend.app.llm.types import ProviderRequest
from backend.app.schemas.provider_settings import (
    ProviderApiKeyDeleteRequest,
    ProviderPublicSettings,
    ProviderSettingsListResponse,
    ProviderSettingsUpdateRequest,
    ProviderTestResponse,
    ProviderValidateRequest,
    ProviderValidateResponse,
)
from backend.app.settings.secret_store import (
    SecretStore,
    SecretStoreConflictError,
    SecretStoreError,
    looks_like_masked_key,
    masked_key,
)
from backend.app.settings.provider_registry import (
    PROVIDERS,
    provider_definition,
    resolve_provider_values,
)
from backend.app.settings.ssrf_guard import is_custom_base_url, validate_base_url
from backend.app.vision.config import VisionProviderSettings
from backend.app.vision.providers.glm_v_provider import GLMVProvider
from backend.app.vision.providers.qwen_vl_provider import QwenVLProvider
from backend.app.vision.types import VisionRequest



class ProviderSettingsService:
    def __init__(self, store: SecretStore | None = None) -> None:
        self.store = store or SecretStore()

    def list_public_settings(self) -> ProviderSettingsListResponse:
        revision = self.store.current_revision()
        warnings: list[str] = []
        try:
            self.store.read()
        except SecretStoreError as exc:
            warnings.append(str(exc))
        providers = []
        for provider_id in PROVIDERS:
            try:
                providers.append(self.get_public_settings(provider_id, revision=revision))
            except SecretStoreError as exc:
                warnings.append(f"{provider_id}: {exc}")
        return ProviderSettingsListResponse(revision=revision, providers=providers, warnings=warnings)

    def get_public_settings(self, provider_id: str, *, revision: int | None = None) -> ProviderPublicSettings:
        definition = provider_definition(provider_id)
        warnings: list[str] = []
        values, source = self._resolved_values(provider_id, warnings=warnings)
        key = str(values.pop("api_key", "") or "")
        key_source = source.get("api_key")
        api_key_source = "UI" if key_source == "UI" else "Environment" if key_source == "Environment" else "None"
        configured = bool(key.strip() and str(values.get("model", "")).strip() and str(values.get("base_url", "")).strip())
        fields = {key_name: value for key_name, value in values.items() if key_name != "api_key"}
        if key_source == "Environment":
            warnings.append("API key comes from Environment and cannot be deleted from the UI.")
        return ProviderPublicSettings(
            id=provider_id,
            display_name=definition.display_name,
            group=definition.group,  # type: ignore[arg-type]
            enabled=bool(fields.get("enabled", True)),
            configured=configured,
            masked_key=masked_key(key),
            api_key_source=api_key_source,  # type: ignore[arg-type]
            revision=self.store.current_revision() if revision is None else revision,
            source={key_name: value for key_name, value in source.items() if key_name != "api_key"},
            fields=fields,
            warnings=warnings,
        )

    def runtime_provider_values(self, provider_id: str) -> dict[str, Any]:
        values, _source = self._resolved_values(provider_id)
        return values

    def runtime_provider_bundle(self, provider_id: str) -> tuple[dict[str, Any], dict[str, str]]:
        return self._resolved_values(provider_id)

    def validate_runtime_base_urls(self, provider_ids: list[str]) -> None:
        for provider_id in provider_ids:
            values, _source = self._resolved_values(provider_id)
            if values.get("enabled") is False or not str(values.get("api_key", "")).strip():
                continue
            base_url = str(values.get("base_url", "")).strip()
            if not base_url:
                continue
            custom = is_custom_base_url(provider_id, base_url)
            validate_base_url(
                provider_id,
                base_url,
                allow_custom_base_url=bool(values.get("allow_custom_base_url")),
                allow_local_endpoint=bool(values.get("allow_local_endpoint")),
                resolve_dns=custom or bool(values.get("allow_local_endpoint")),
            )

    def validate(
        self,
        provider_id: str,
        request: ProviderValidateRequest | ProviderSettingsUpdateRequest,
        *,
        require_configured_key: bool = False,
    ) -> ProviderValidateResponse:
        provider_definition(provider_id)
        values = request.model_dump(exclude_unset=True)
        resolved_values, _source = self._resolved_values(provider_id)
        effective_values = {**resolved_values, **{key: value for key, value in values.items() if value is not None}}
        errors: list[str] = []
        warnings: list[str] = []
        api_key = str(values.get("api_key") or resolved_values.get("api_key") or "")
        if values.get("api_key") and looks_like_masked_key(str(values["api_key"])):
            errors.append("masked_key is display-only and cannot be used as api_key.")
        if require_configured_key and bool(effective_values.get("enabled", True)) and not api_key.strip():
            errors.append("API Key is required before this provider can be used.")
        model = values.get("model")
        if model is not None and (not str(model).strip() or len(str(model)) > 120):
            errors.append("model must be non-empty and at most 120 characters.")
        if require_configured_key and not str(effective_values.get("model", "")).strip():
            errors.append("model is required before this provider can be used.")
        if require_configured_key and not str(effective_values.get("base_url", "")).strip():
            errors.append("base_url is required before this provider can be used.")
        timeout = values.get("timeout_seconds")
        if timeout is not None and not (1 <= float(timeout) <= 600):
            errors.append("timeout_seconds must be between 1 and 600.")
        retry = values.get("retry")
        if retry is not None and not (0 <= int(retry) <= 5):
            errors.append("retry must be between 0 and 5.")
        max_output_tokens = values.get("max_output_tokens")
        if max_output_tokens is not None and not (128 <= int(max_output_tokens) <= 16000):
            errors.append("max_output_tokens must be between 128 and 16000.")
        for name in ("request_width", "request_height"):
            value = values.get(name)
            if value is not None and not (64 <= int(value) <= 4096):
                errors.append(f"{name} must be between 64 and 4096.")
        domains = values.get("allowed_domains")
        if domains is not None:
            if provider_id in {"qwen_image", "seedream"} and not domains:
                errors.append("allowed_domains must keep at least one result domain.")
            elif any(not _valid_hostname(item) for item in domains):
                errors.append("allowed_domains contains an invalid hostname.")
        if values.get("supports_async") is True:
            raise ValueError("supports_async=true is no longer supported; use synchronous image generation.")
        base_url = values.get("base_url")
        if base_url:
            try:
                validate_base_url(
                    provider_id,
                    str(base_url),
                    allow_custom_base_url=bool(values.get("allow_custom_base_url")),
                    allow_local_endpoint=bool(values.get("allow_local_endpoint")),
                    resolve_dns=False,
                )
            except ValueError as exc:
                errors.append(str(exc))
        return ProviderValidateResponse(ok=not errors, errors=errors, warnings=warnings)

    def save(self, provider_id: str, request: ProviderSettingsUpdateRequest) -> ProviderPublicSettings:
        provider_definition(provider_id)
        if request.api_key and looks_like_masked_key(request.api_key):
            raise ValueError("masked_key is display-only and cannot be saved as api_key.")
        validation = self.validate(provider_id, request, require_configured_key=False)
        if not validation.ok:
            raise ValueError("; ".join(validation.errors))
        config = {
            key: value
            for key, value in request.model_dump(exclude_unset=True).items()
            if key not in {"expected_revision", "api_key", "supports_async"}
        }
        try:
            data = self.store.update_provider(
                provider_id,
                config=config,
                api_key=request.api_key.strip() if request.api_key else None,
                expected_revision=request.expected_revision,
            )
        except SecretStoreConflictError:
            raise
        return self.get_public_settings(provider_id, revision=int(data.get("revision", 0)))

    def delete_api_key(self, provider_id: str, request: ProviderApiKeyDeleteRequest) -> ProviderPublicSettings:
        provider_definition(provider_id)
        public = self.get_public_settings(provider_id)
        if public.api_key_source == "Environment":
            raise ValueError("API key is read-only because it comes from Environment.")
        try:
            data = self.store.delete_api_key(provider_id, expected_revision=request.expected_revision)
        except SecretStoreConflictError:
            raise
        return self.get_public_settings(provider_id, revision=int(data.get("revision", 0)))

    def test_provider(self, provider_id: str, *, confirm_cost: bool) -> ProviderTestResponse:
        if not confirm_cost:
            raise ValueError("confirm_cost=true is required before provider test.")
        values = self.runtime_provider_values(provider_id)
        validation = self.validate(provider_id, ProviderValidateRequest(
            base_url=values.get("base_url"),
            model=values.get("model"),
            api_key=values.get("api_key"),
            timeout_seconds=values.get("timeout_seconds"),
            retry=values.get("retry"),
            request_width=values.get("request_width"),
            request_height=values.get("request_height"),
            allowed_domains=values.get("allowed_domains"),
            endpoint_path=values.get("endpoint_path"),
            allow_custom_base_url=bool(values.get("allow_custom_base_url")),
            allow_local_endpoint=bool(values.get("allow_local_endpoint")),
        ), require_configured_key=True)
        if not validation.ok:
            return ProviderTestResponse(success=False, provider=provider_id, model=values.get("model"), warning=validation.errors[0])
        try:
            validate_base_url(
                provider_id,
                str(values.get("base_url", "")),
                allow_custom_base_url=bool(values.get("allow_custom_base_url")),
                allow_local_endpoint=bool(values.get("allow_local_endpoint")),
                resolve_dns=True,
            )
            started = time.monotonic()
            self._send_minimal_test(provider_id, values)
            latency_ms = int((time.monotonic() - started) * 1000)
            return ProviderTestResponse(success=True, provider=provider_id, model=values.get("model"), latency_ms=latency_ms)
        except Exception as exc:
            return ProviderTestResponse(success=False, provider=provider_id, model=values.get("model"), warning=type(exc).__name__)

    def _resolved_values(
        self,
        provider_id: str,
        *,
        warnings: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        return resolve_provider_values(provider_id, self.store, warnings=warnings)

    def _send_minimal_test(self, provider_id: str, values: dict[str, Any]) -> None:
        if provider_id in {"deepseek", "qwen"}:
            provider_settings = LLMProviderSettings(
                name=provider_id,
                api_key=str(values.get("api_key", "")),
                base_url=str(values.get("base_url", "")),
                model=str(values.get("model", "")),
            )
            provider = DeepSeekProvider(provider_settings, float(values.get("timeout_seconds", 45))) if provider_id == "deepseek" else QwenProvider(provider_settings, float(values.get("timeout_seconds", 45)))
            provider.generate(ProviderRequest(
                task_type="provider_test",
                system_prompt="Return JSON matching the schema.",
                input_payload={"test": "ping"},
                response_model=_ProviderTextTest,
                max_output_tokens=64,
            ))
            return
        if provider_id in {"qwen_vl", "glm_v"}:
            provider_settings = VisionProviderSettings(
                name=provider_id,
                api_key=str(values.get("api_key", "")),
                base_url=str(values.get("base_url", "")),
                model=str(values.get("model", "")),
                supports_json_object=bool(values.get("supports_json_object", False)),
                disable_thinking=bool(values.get("disable_thinking", False)),
            )
            provider = QwenVLProvider(provider_settings, float(values.get("timeout_seconds", 45))) if provider_id == "qwen_vl" else GLMVProvider(provider_settings, float(values.get("timeout_seconds", 45)))
            provider.analyze_figure(VisionRequest(
                context_id="provider_test",
                system_prompt="Return JSON matching the schema.",
                input_payload={"test": "ping"},
                image_bytes=_ONE_PIXEL_PNG,
                mime_type="image/png",
                response_model=_ProviderTextTest,
                max_output_tokens=64,
            ))
            return
        provider_settings = ImageProviderSettings(
            name=provider_id,
            api_key=str(values.get("api_key", "")),
            base_url=str(values.get("base_url", "")),
            model=str(values.get("model", "")),
            allowed_domains=list(values.get("allowed_domains") or []),
            endpoint_path=str(values.get("endpoint_path", "")),
            workspace=str(values.get("workspace", "")),
            request_width=int(values.get("request_width", 512)),
            request_height=int(values.get("request_height", 512)),
        )
        provider = QwenImageProvider(provider_settings, float(values.get("timeout_seconds", 60))) if provider_id == "qwen_image" else SeedreamProvider(provider_settings, float(values.get("timeout_seconds", 60)))
        with tempfile.TemporaryDirectory(prefix="coderesearch_provider_test_") as directory:
            provider.generate_image(ImageGenerationRequest(
                diagram_id="provider_test",
                public_spec={"public_spec_hash": "0" * 64, "modules": []},
                prompt_version="provider-test",
                schema_version="1.3.3",
                width=int(values.get("request_width", 512)),
                height=int(values.get("request_height", 512)),
                mime_type="image/png",
                max_output_bytes=1024 * 1024,
                output_dir=Path(directory),
            ))


class _ProviderTextTest(BaseModel):
    message: str | None = None


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00"
    b"\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _valid_hostname(value: str) -> bool:
    if not value or len(value) > 253 or "/" in value or ":" in value:
        return False
    labels = value.strip(".").split(".")
    return all(label and len(label) <= 63 and label.replace("-", "").isalnum() for label in labels)
