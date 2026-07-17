from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from backend.app.agents.graph import ProgressCallback, build_analysis_graph
from backend.app.image_generation.config import ImageGenerationSettings
from backend.app.image_generation.runtime import ImageGenerationRuntime
from backend.app.llm.config import LLMSettings
from backend.app.llm.runtime import LLMRuntime
from backend.app.schemas.state import AgentState
from backend.app.services.ai_usage import build_ai_usage, build_ai_usage_from_outputs
from backend.app.services.analysis_options import (
    create_provider_runtime_context,
    resolve_analysis_options,
)
from backend.app.services.storage_service import ensure_output_root
from backend.app.vision.config import VisionSettings
from backend.app.vision.runtime import VisionRuntime


TASK_ID_PATTERN = re.compile(r"^task_[A-Za-z0-9]+$")
TASK_RESULT_FILES = {
    "repo_index": "repo_index.json",
    "parsed_files": "parsed_files.json",
    "file_analysis": "file_analysis.json",
    "library_calls": "library_calls.json",
    "function_analysis": "function_analysis.json",
    "model_analysis": "model_analysis.json",
    "paper_analysis": "paper_analysis.json",
    "paper_code_alignment": "paper_code_alignment.json",
    "diagrams": "diagrams.json",
    "library_function_docs": "library_function_docs.json",
    "llm_explanations": "llm_explanations.json",
    "ai_usage": "ai_usage.json",
    "paper_figure_analysis": "paper_figure_analysis.json",
    "teaching_diagrams": "teaching_diagrams/manifest.json",
    "index_manifest": "index_manifest.json",
}


def run_analysis(
    zip_path: str | Path,
    output_root: str | Path = "outputs",
    library_db_path: str | Path | None = None,
    paper_pdf_path: str | Path | None = None,
    analysis_mode: str | None = None,
    external_model_consent: bool = False,
    llm_runtime: LLMRuntime | None = None,
    *,
    text_llm_enabled: bool | None = None,
    teaching_narrative_llm_enabled: bool | None = None,
    vision_vlm_enabled: bool | None = None,
    external_text_consent: bool | None = None,
    external_vision_consent: bool = False,
    vision_runtime: VisionRuntime | None = None,
    teaching_diagrams_enabled: bool = True,
    image_generation_enabled: bool | None = None,
    external_image_consent: bool = False,
    teaching_review_vlm_enabled: bool | None = None,
    external_teaching_review_consent: bool = False,
    image_runtime: ImageGenerationRuntime | None = None,
    task_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
    structured_index_enabled: bool | None = None,
    repository_key: str | None = None,
    structured_index_db_path: str | Path | None = None,
) -> AgentState:
    ensure_output_root(output_root)
    options, provider_settings = resolve_analysis_options(
        analysis_mode=analysis_mode,
        external_model_consent=external_model_consent,
        text_llm_enabled=text_llm_enabled,
        teaching_narrative_llm_enabled=teaching_narrative_llm_enabled,
        vision_vlm_enabled=vision_vlm_enabled,
        external_text_consent=external_text_consent,
        external_vision_consent=external_vision_consent,
        teaching_diagrams_enabled=teaching_diagrams_enabled,
        image_generation_enabled=image_generation_enabled,
        external_image_consent=external_image_consent,
        teaching_review_vlm_enabled=teaching_review_vlm_enabled,
        external_teaching_review_consent=external_teaching_review_consent,
        llm_settings=llm_runtime.settings if llm_runtime else None,
        vision_settings=vision_runtime.settings if vision_runtime else None,
        image_settings=image_runtime.settings if image_runtime else None,
        structured_index_enabled=structured_index_enabled,
        repository_key=repository_key,
        structured_index_db_path=str(structured_index_db_path) if structured_index_db_path else None,
    )
    runtime_context = create_provider_runtime_context(
        provider_settings,
        llm_runtime=llm_runtime,
        vision_runtime=vision_runtime,
        image_runtime=image_runtime,
    )
    settings = provider_settings.llm
    vision_settings = provider_settings.vision
    image_settings = provider_settings.image
    runtime = runtime_context.llm
    resolved_vision_runtime = runtime_context.vision
    resolved_image_runtime = runtime_context.image
    resolved_library_db_path = str(library_db_path or os.getenv("LIBRARY_DB_PATH") or "data/python_function_library.sqlite3")
    graph = build_analysis_graph(runtime, resolved_vision_runtime, resolved_image_runtime, progress_callback)
    initial_state: AgentState = {
        "zip_path": str(zip_path),
        "output_dir": str(output_root),
        "library_db_path": resolved_library_db_path,
        "errors": [],
        **options.state_dump(),
        "file_llm_explanations": [],
        "function_llm_explanations": [],
        "model_llm_explanations": [],
        "paper_code_align_llm_explanations": [],
        "llm_evidence_catalog": [],
        "llm_skipped_entities": [],
        "llm_warnings": [],
        "llm_budget": runtime.budget.snapshot(),
        "paper_figure_analysis": {},
        "vision_budget": resolved_vision_runtime.budget.snapshot(),
        "teaching_diagram_specs": [],
        "teaching_diagram_skeletons": [],
        "teaching_diagram_manifest": {},
        "diagram_evidence_catalog": [],
        "teaching_diagram_warnings": [],
        "teaching_plan_budget": {
            "max_provider_requests": image_settings.teaching_plan_max_llm_requests,
            "sent_provider_requests": 0,
        },
        "teaching_image_budget": resolved_image_runtime.budget.snapshot(),
        "teaching_review_budget": {
            "max_provider_requests": image_settings.teaching_review_max_provider_requests,
            "sent_provider_requests": 0,
        },
        "ai_provider_config": _ai_provider_config(settings, vision_settings, image_settings),
        "ai_usage": {},
    }
    if task_id:
        initial_state["task_id"] = task_id
    if paper_pdf_path:
        initial_state["paper_pdf_path"] = str(paper_pdf_path)
    return graph.invoke(initial_state)


def list_task_summaries(output_root: str | Path = "outputs", limit: int = 50) -> list[dict[str, Any]]:
    root = Path(output_root)
    if not root.exists():
        return []
    task_dirs = [
        path
        for path in root.iterdir()
        if path.is_dir() and TASK_ID_PATTERN.match(path.name)
    ]
    task_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "task_id": task_dir.name,
            "output_dir": str(task_dir),
            "created_at": None,
            "has_report": (task_dir / "report.md").exists(),
            "has_diagrams": (task_dir / "diagrams.json").exists(),
        }
        for task_dir in task_dirs[:limit]
    ]


def load_task_result(task_id: str, output_root: str | Path = "outputs") -> dict[str, Any]:
    task_dir = _task_output_dir(task_id, output_root)
    errors: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "task_id": task_id,
        "summary": _summarize_output_dir(task_id, task_dir),
        "report_md": _read_report(task_dir, errors),
        "errors": errors,
    }
    for key, filename in TASK_RESULT_FILES.items():
        if key == "llm_explanations" and not (task_dir / filename).exists():
            result[key] = {"analysis_mode": "rule", "status": "disabled", "warnings": []}
        elif key == "ai_usage" and not (task_dir / filename).exists():
            result[key] = {}
        elif key == "paper_figure_analysis" and not (task_dir / filename).exists():
            result[key] = {
                "version": "1.2", "extraction_status": "not_applicable", "vision_status": "disabled",
                "vision_vlm_enabled": False, "figures": [], "warnings": [],
            }
        elif key == "teaching_diagrams" and not (task_dir / filename).exists():
            result[key] = {
                "version": "1.3.3", "status": "disabled", "diagrams": [], "warnings": [],
            }
        elif key == "index_manifest" and not (task_dir / filename).exists():
            result[key] = {}
        else:
            result[key] = _read_json(task_dir / filename, key, errors)
    return result


def load_task_report(task_id: str, output_root: str | Path = "outputs") -> dict[str, str]:
    task_dir = _task_output_dir(task_id, output_root)
    report_path = task_dir / "report.md"
    if not report_path.exists():
        return {"task_id": task_id, "report_md": ""}
    return {"task_id": task_id, "report_md": report_path.read_text(encoding="utf-8")}


def summarize_state(state: AgentState) -> dict[str, Any]:
    output_dir = state.get("output_dir", "")
    ai_usage = build_ai_usage(state)
    state["ai_usage"] = ai_usage
    return {
        "task_id": state.get("task_id"),
        "output_dir": output_dir,
        "repo_index_path": str(Path(output_dir) / "repo_index.json") if output_dir else None,
        "parsed_files_path": str(Path(output_dir) / "parsed_files.json") if output_dir else None,
        "file_analysis_path": str(Path(output_dir) / "file_analysis.json") if output_dir else None,
        "library_calls_path": str(Path(output_dir) / "library_calls.json") if output_dir else None,
        "function_analysis_path": str(Path(output_dir) / "function_analysis.json") if output_dir else None,
        "model_analysis_path": str(Path(output_dir) / "model_analysis.json") if output_dir else None,
        "paper_analysis_path": str(Path(output_dir) / "paper_analysis.json") if output_dir else None,
        "paper_code_alignment_path": str(Path(output_dir) / "paper_code_alignment.json") if output_dir else None,
        "paper_figure_analysis_path": str(Path(output_dir) / "paper_figure_analysis.json") if output_dir else None,
        "diagrams_path": str(Path(output_dir) / "diagrams.json") if output_dir else None,
        "teaching_diagrams_path": str(Path(output_dir) / "teaching_diagrams" / "manifest.json") if output_dir else None,
        "library_function_docs_path": str(Path(output_dir) / "library_function_docs.json") if output_dir else None,
        "report_path": str(Path(output_dir) / "report.md") if output_dir else None,
        "library_db_path": state.get("library_db_path"),
        "structured_index_enabled": state.get("structured_index_enabled", False),
        "structured_index_db_path": state.get("structured_index_db_path"),
        "repo_id": state.get("repo_id"),
        "index_version_id": state.get("index_version_id"),
        "index_manifest_path": (
            str(Path(output_dir) / "index_manifest.json") if output_dir and state.get("index_manifest") else None
        ),
        "index_status": state.get("index_manifest", {}).get("status", "disabled"),
        "paper_pdf_path": state.get("paper_pdf_path"),
        "paper_provided": bool(state.get("paper_analysis", {}).get("paper_provided")),
        "python_file_count": len(state.get("python_files", [])),
        "class_count": len(state.get("classes", [])),
        "function_count": len(state.get("functions", [])),
        "library_call_count": len(state.get("library_calls", [])),
        "library_function_doc_count": len(state.get("library_function_docs", [])),
        "function_analysis_count": len(state.get("function_analysis", [])),
        "model_count": len(state.get("model_analysis", [])),
        "main_model_count": len([
            item for item in state.get("model_analysis", []) if item.get("is_main_model_candidate")
        ]),
        "paper_contribution_count": len(state.get("paper_analysis", {}).get("contributions", [])),
        "paper_alignment_count": len([
            item
            for item in state.get("paper_code_alignment", {}).get("alignment_items", [])
            if item.get("status") == "matched"
        ]),
        "paper_unmatched_count": len(state.get("paper_code_alignment", {}).get("unmatched_contributions", [])),
        "diagram_count": len(state.get("diagrams", [])),
        "error_count": len(state.get("errors", [])),
        "analysis_mode": state.get("analysis_mode", "rule"),
        "external_model_consent": state.get("external_model_consent", False),
        "text_llm_enabled": state.get("text_llm_enabled", False),
        "teaching_narrative_llm_enabled": state.get("teaching_narrative_llm_enabled", False),
        "vision_vlm_enabled": state.get("vision_vlm_enabled", False),
        "external_text_consent": state.get("external_text_consent", False),
        "external_vision_consent": state.get("external_vision_consent", False),
        "teaching_diagrams_enabled": state.get("teaching_diagrams_enabled", True),
        "image_generation_enabled": state.get("image_generation_enabled", False),
        "teaching_review_vlm_enabled": state.get("teaching_review_vlm_enabled", False),
        "external_image_consent": state.get("external_image_consent", False),
        "external_teaching_review_consent": state.get("external_teaching_review_consent", False),
        "llm_status": _llm_status(state),
        "llm_explanation_count": _llm_count(state),
        "llm_warning_count": len(state.get("llm_warnings", [])),
        "llm_budget": state.get("llm_budget", {}),
        "vision_status": state.get("paper_figure_analysis", {}).get("vision_status", "disabled"),
        "figure_count": len(state.get("paper_figure_analysis", {}).get("figures", [])),
        "vision_budget": state.get("vision_budget", {}),
        "teaching_diagram_status": state.get("teaching_diagram_manifest", {}).get("status", "disabled"),
        "teaching_diagram_count": len(state.get("teaching_diagram_manifest", {}).get("diagrams", [])),
        "teaching_image_budget": state.get("teaching_image_budget", {}),
        "teaching_review_budget": state.get("teaching_review_budget", {}),
        "ai_usage": ai_usage,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CodeResearch Agent repository analysis.")
    parser.add_argument("zip_path", help="Path to a local project ZIP file.")
    parser.add_argument("--output-root", default="outputs", help="Directory for task outputs.")
    parser.add_argument("--library-db-path", default=None, help="Path to the global library function SQLite DB.")
    parser.add_argument("--paper-pdf-path", default=None, help="Optional path to a paper PDF for paper/code alignment.")
    parser.add_argument("--analysis-mode", choices=["rule", "hybrid"], default=None)
    parser.add_argument("--external-model-consent", action="store_true")
    parser.add_argument("--text-llm-enabled", action="store_true", default=None)
    parser.add_argument("--teaching-narrative-llm-enabled", action="store_true", default=None)
    parser.add_argument("--vision-vlm-enabled", action="store_true", default=None)
    parser.add_argument("--external-text-consent", action="store_true")
    parser.add_argument("--external-vision-consent", action="store_true")
    parser.add_argument("--no-teaching-diagrams", action="store_true")
    parser.add_argument("--image-generation-enabled", action="store_true", default=None)
    parser.add_argument("--external-image-consent", action="store_true")
    parser.add_argument("--teaching-review-vlm-enabled", action="store_true", default=None)
    parser.add_argument("--external-teaching-review-consent", action="store_true")
    parser.add_argument("--structured-index-enabled", action="store_true", default=None)
    parser.add_argument("--repository-key", default=None)
    parser.add_argument("--structured-index-db-path", default=None)
    args = parser.parse_args()

    state = run_analysis(
        args.zip_path, args.output_root, args.library_db_path, args.paper_pdf_path,
        args.analysis_mode, args.external_model_consent,
        text_llm_enabled=args.text_llm_enabled,
        teaching_narrative_llm_enabled=args.teaching_narrative_llm_enabled,
        vision_vlm_enabled=args.vision_vlm_enabled,
        external_text_consent=args.external_text_consent or None,
        external_vision_consent=args.external_vision_consent,
        teaching_diagrams_enabled=not args.no_teaching_diagrams,
        image_generation_enabled=args.image_generation_enabled,
        external_image_consent=args.external_image_consent,
        teaching_review_vlm_enabled=args.teaching_review_vlm_enabled,
        external_teaching_review_consent=args.external_teaching_review_consent,
        structured_index_enabled=args.structured_index_enabled,
        repository_key=args.repository_key,
        structured_index_db_path=args.structured_index_db_path,
    )
    print(json.dumps(summarize_state(state), ensure_ascii=False, indent=2))


def _task_output_dir(task_id: str, output_root: str | Path) -> Path:
    if not TASK_ID_PATTERN.match(task_id):
        raise ValueError("Invalid task_id.")
    root = Path(output_root)
    task_dir = (root / task_id).resolve()
    root_resolved = root.resolve()
    if root_resolved not in task_dir.parents and task_dir != root_resolved:
        raise ValueError("Invalid task output path.")
    return task_dir


def _read_json(path: Path, key: str, errors: list[dict[str, str]]) -> dict:
    if not path.exists():
        errors.append({"path": str(path), "error_type": "FileNotFoundError", "message": f"Missing {path.name}"})
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append({"path": str(path), "error_type": "JSONDecodeError", "message": str(exc)})
        return {}


def _read_report(task_dir: Path, errors: list[dict[str, str]]) -> str:
    report_path = task_dir / "report.md"
    if not report_path.exists():
        errors.append({"path": str(report_path), "error_type": "FileNotFoundError", "message": "Missing report.md"})
        return ""
    return report_path.read_text(encoding="utf-8")


def _summarize_output_dir(task_id: str, task_dir: Path) -> dict[str, Any]:
    repo_index = _safe_json(task_dir / "repo_index.json")
    parsed_files = _safe_json(task_dir / "parsed_files.json")
    library_calls = _safe_json(task_dir / "library_calls.json")
    function_analysis = _safe_json(task_dir / "function_analysis.json")
    model_analysis = _safe_json(task_dir / "model_analysis.json")
    paper_analysis = _safe_json(task_dir / "paper_analysis.json")
    diagrams = _safe_json(task_dir / "diagrams.json")
    llm = _safe_json(task_dir / "llm_explanations.json")
    figures = _safe_json(task_dir / "paper_figure_analysis.json")
    teaching = _safe_json(task_dir / "teaching_diagrams" / "manifest.json")
    ai_usage = _safe_json(task_dir / "ai_usage.json")
    index_manifest = _safe_json(task_dir / "index_manifest.json")
    return {
        "task_id": task_id,
        "output_dir": str(task_dir),
        "python_file_count": len(repo_index.get("python_files", [])),
        "class_count": len(parsed_files.get("classes", [])),
        "function_count": len(parsed_files.get("functions", [])),
        "library_call_count": len(library_calls.get("library_calls", [])),
        "function_analysis_count": len(function_analysis.get("function_analysis", [])),
        "model_count": len(model_analysis.get("model_analysis", [])),
        "paper_provided": bool(paper_analysis.get("paper_analysis", {}).get("paper_provided")),
        "diagram_count": len(diagrams.get("diagrams", [])),
        "analysis_mode": llm.get("analysis_mode", "rule"),
        "llm_status": llm.get("status", "disabled"),
        "llm_explanation_count": sum(len(llm.get(key, [])) for key in (
            "file_explanations", "function_explanations", "model_explanations", "paper_code_alignment_explanations"
        )),
        "llm_warning_count": len(llm.get("warnings", [])),
        "llm_budget": llm.get("budget", {}),
        "text_llm_enabled": llm.get("text_llm_enabled", llm.get("analysis_mode") == "hybrid"),
        "teaching_narrative_llm_enabled": teaching.get("teaching_narrative_llm_enabled", False),
        "vision_vlm_enabled": figures.get("vision_vlm_enabled", False),
        "vision_status": figures.get("vision_status", "disabled"),
        "figure_count": len(figures.get("figures", [])),
        "vision_budget": figures.get("budget", {}),
        "teaching_diagrams_enabled": teaching.get("teaching_diagrams_enabled", False),
        "image_generation_enabled": teaching.get("image_generation_enabled", False),
        "teaching_review_vlm_enabled": teaching.get("teaching_review_vlm_enabled", False),
        "external_image_consent": teaching.get("external_image_consent", False),
        "external_teaching_review_consent": teaching.get("external_teaching_review_consent", False),
        "teaching_diagram_status": teaching.get("status", "disabled"),
        "teaching_diagram_count": len(teaching.get("diagrams", [])),
        "teaching_image_budget": (teaching.get("budget", {}) or {}).get("teaching_image", {}),
        "teaching_review_budget": (teaching.get("budget", {}) or {}).get("teaching_review", {}),
        "structured_index_enabled": bool(index_manifest),
        "repo_id": index_manifest.get("repo_id"),
        "index_version_id": index_manifest.get("index_version_id"),
        "index_status": index_manifest.get("status", "disabled"),
        "ai_usage": ai_usage or build_ai_usage_from_outputs(llm, figures, teaching),
    }


def _safe_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _llm_count(state: AgentState) -> int:
    return sum(len(state.get(field, [])) for field in (
        "file_llm_explanations", "function_llm_explanations", "model_llm_explanations",
        "paper_code_align_llm_explanations",
    ))


def _llm_status(state: AgentState) -> str:
    if not state.get("text_llm_enabled", state.get("analysis_mode", "rule") == "hybrid"):
        return "disabled"
    count = _llm_count(state)
    warnings = state.get("llm_warnings", [])
    selected = state.get("llm_budget", {}).get("selected_entities", 0)
    if count and count < selected:
        return "partial"
    if count:
        return "success"
    if any(item.get("code") == "llm_provider_unconfigured" for item in warnings):
        return "skipped"
    return "failed" if warnings else "skipped"


def _ai_provider_config(
    settings: LLMSettings,
    vision_settings: VisionSettings,
    image_settings: ImageGenerationSettings,
) -> dict[str, dict[str, str | bool]]:
    return {
        "text_analysis": _configured_provider(settings.deepseek, settings.qwen),
        "teaching_narrative": _configured_provider(settings.deepseek, settings.qwen),
        "paper_vision": _configured_provider(vision_settings.qwen_vl, vision_settings.glm_v),
        "teaching_review": _configured_provider(vision_settings.qwen_vl, vision_settings.glm_v),
        "image_generation": _configured_provider(image_settings.qwen_image, image_settings.seedream),
    }


def _configured_provider(*providers) -> dict[str, str | bool]:
    for provider in providers:
        if provider.configured:
            return {"provider": provider.name, "model": provider.model, "configured": True}
    first = providers[0] if providers else None
    return {
        "provider": getattr(first, "name", "unknown"),
        "model": getattr(first, "model", ""),
        "configured": False,
    }


if __name__ == "__main__":
    main()
