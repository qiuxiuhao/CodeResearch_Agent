from __future__ import annotations

from pathlib import Path
from types import MappingProxyType


PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"

PROMPT_REGISTRY = MappingProxyType({
    "file_explain": "file_explain_llm.md",
    "function_explain": "function_explain_llm.md",
    "model_explain": "model_explain_llm.md",
    "paper_code_align": "paper_code_align_llm.md",
    "paper_figure_analyze": "paper_figure_analyze_vlm.md",
})


def load_registered_prompt(task_key: str) -> str:
    """Load a prompt through its stable task key, never an arbitrary filename."""
    try:
        filename = PROMPT_REGISTRY[task_key]
    except KeyError as exc:
        raise KeyError(f"Unknown prompt task key: {task_key}") from exc
    return (PROMPT_ROOT / filename).read_text(encoding="utf-8")


def registered_prompt_files() -> frozenset[str]:
    return frozenset(PROMPT_REGISTRY.values())
