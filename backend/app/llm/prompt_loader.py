from pathlib import Path


PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(filename: str) -> str:
    return (PROMPT_ROOT / filename).read_text(encoding="utf-8")
