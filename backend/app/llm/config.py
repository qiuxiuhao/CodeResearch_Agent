from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator


AnalysisMode = Literal["rule", "hybrid"]


class ProviderSettings(BaseModel):
    name: str
    api_key: str = ""
    base_url: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


class LLMSettings(BaseModel):
    analysis_mode: AnalysisMode = "rule"
    deepseek: ProviderSettings
    qwen: ProviderSettings
    timeout_seconds: float = Field(default=45, ge=1, le=300)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_input_chars: int = Field(default=12000, ge=1000, le=200000)
    max_output_tokens: int = Field(default=1200, ge=128, le=16000)
    max_function_explanations: int = Field(default=20, ge=0, le=500)
    max_file_explanations: int = Field(default=10, ge=0, le=500)
    max_model_explanations: int = Field(default=5, ge=0, le=100)
    max_paper_alignments: int = Field(default=5, ge=0, le=100)
    max_total_entities: int = Field(default=30, ge=0, le=1000)
    max_provider_requests: int = Field(default=60, ge=0, le=4000)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    cache_enabled: bool = True
    cache_path: str = "data/llm_explanation_cache.sqlite3"

    @field_validator("analysis_mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: object) -> object:
        return str(value).strip().lower() if value is not None else value

    @classmethod
    def from_env(cls, analysis_mode: str | None = None) -> "LLMSettings":
        resolved_mode = analysis_mode if analysis_mode is not None else os.getenv("ANALYSIS_MODE", "rule")
        return cls(
            analysis_mode=resolved_mode,
            deepseek=ProviderSettings(
                name="deepseek",
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            ),
            qwen=ProviderSettings(
                name="qwen",
                api_key=os.getenv("QWEN_API_KEY", ""),
                base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                model=os.getenv("QWEN_MODEL", "qwen-plus"),
            ),
            timeout_seconds=_float_env("LLM_TIMEOUT_SECONDS", 45),
            max_retries=_int_env("LLM_MAX_RETRIES", 1),
            max_input_chars=_int_env("LLM_MAX_INPUT_CHARS", 12000),
            max_output_tokens=_int_env("LLM_MAX_OUTPUT_TOKENS", 1200),
            max_function_explanations=_int_env("LLM_MAX_FUNCTION_EXPLANATIONS", 20),
            max_file_explanations=_int_env("LLM_MAX_FILE_EXPLANATIONS", 10),
            max_model_explanations=_int_env("LLM_MAX_MODEL_EXPLANATIONS", 5),
            max_paper_alignments=_int_env("LLM_MAX_PAPER_ALIGNMENTS", 5),
            max_total_entities=_int_env("LLM_MAX_TOTAL_ENTITIES", 30),
            max_provider_requests=_int_env("LLM_MAX_PROVIDER_REQUESTS", 60),
            max_concurrency=_int_env("LLM_MAX_CONCURRENCY", 2),
            cache_enabled=_bool_env("LLM_CACHE_ENABLED", True),
            cache_path=os.getenv("LLM_CACHE_PATH", "data/llm_explanation_cache.sqlite3"),
        )

    def public_config(self) -> dict:
        return {
            "default_analysis_mode": self.analysis_mode,
            "max_function_explanations": self.max_function_explanations,
            "max_file_explanations": self.max_file_explanations,
            "max_model_explanations": self.max_model_explanations,
            "max_paper_alignments": self.max_paper_alignments,
            "max_total_entities": self.max_total_entities,
            "max_provider_requests": self.max_provider_requests,
            "max_concurrency": self.max_concurrency,
            "providers": {
                "deepseek": {"configured": self.deepseek.configured, "model": self.deepseek.model},
                "qwen": {"configured": self.qwen.configured, "model": self.qwen.model},
            },
            "external_model_notice": (
                "启用 AI 增强后，经过脱敏的代码片段、注释、docstring、结构化分析结果及可选论文文本片段"
                "可能被发送到外部模型服务商，并可能产生费用。"
            ),
        }


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
