from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel

from backend.app.llm.evidence import merge_evidence
from backend.app.llm.prompt_loader import load_prompt
from backend.app.llm.privacy import is_sensitive_path, sanitize_payload
from backend.app.llm.runtime import LLMRuntime
from backend.app.llm.types import LLMTaskType
from backend.app.schemas.llm_explanation import EvidenceItem


def run_selected_entities(
    *,
    state: dict,
    runtime: LLMRuntime | None,
    task_type: LLMTaskType,
    output_field: str,
    prompt_file: str,
    selected: list[dict],
    skipped: list[dict],
    response_model: type[BaseModel],
    prepare: Callable[[dict], tuple[str, dict[str, Any], list[EvidenceItem]]],
) -> dict:
    if runtime is None or state.get("analysis_mode", "rule") != "hybrid":
        return {**state, output_field: state.get(output_field, [])}
    sensitive = [item for item in selected if item.get("file_path") and is_sensitive_path(str(item["file_path"]))]
    selected = [item for item in selected if item not in sensitive]
    privacy_skips = [
        {"task_type": task_type, "context_id": _context(item), "reason": "sensitive_file"}
        for item in sensitive
    ]
    reservation = runtime.budget.try_reserve_entities(
        task_type, len(selected), reserve_for_future=_future_entity_reserve(state, task_type)
    )
    allowed = selected[: reservation.reserved]
    budget_skips = [
        {"task_type": task_type, "context_id": _context(item), "reason": "entity_budget_exceeded"}
        for item in selected[reservation.reserved :]
    ]
    all_skipped = [*state.get("llm_skipped_entities", []), *skipped, *privacy_skips, *budget_skips]
    runtime.budget.record_skipped(len(skipped) + len(privacy_skips))
    explanations = list(state.get(output_field, []))
    warnings = list(state.get("llm_warnings", []))
    catalog = list(state.get("llm_evidence_catalog", []))
    prompt = load_prompt(prompt_file)
    jobs = []
    for item in allowed:
        context_id, payload, evidence = prepare(item)
        sanitized_evidence = []
        evidence_redactions = 0
        for entry in evidence:
            clean, count = sanitize_payload(entry.model_dump())
            sanitized_evidence.append(EvidenceItem.model_validate(clean))
            evidence_redactions += count
        evidence = sanitized_evidence
        if evidence_redactions:
            warnings.append({
                "code": "llm_input_redacted", "task_type": task_type, "context_id": context_id,
                "provider": None, "attempt": None, "message": f"Redacted {evidence_redactions} evidence value(s).",
                "recoverable": True,
            })
        catalog = merge_evidence(catalog, evidence)
        payload["evidence_catalog"] = [entry.model_dump() for entry in evidence]
        jobs.append((context_id, payload, evidence))

    def execute(job):
        context_id, payload, evidence = job
        return context_id, runtime.router.generate_structured(
            task_type=task_type, context_id=context_id, system_prompt=prompt, input_payload=payload,
            response_model=response_model, evidence_catalog=evidence,
        )

    with ThreadPoolExecutor(max_workers=runtime.settings.max_concurrency) as executor:
        results = list(executor.map(execute, jobs))
    for context_id, result in results:
        warnings.extend(result.warnings)
        if result.value is not None:
            dumped = result.value.model_dump(mode="json")
            if _identity_matches(task_type, context_id, dumped):
                explanations.append(dumped)
            else:
                warnings.append({
                    "code": "llm_schema_validation_failed", "task_type": task_type,
                    "context_id": context_id, "provider": dumped.get("metadata", {}).get("provider"),
                    "attempt": None, "message": "LLM result identity does not match the requested entity.",
                    "recoverable": True,
                })
    return {
        **state,
        output_field: explanations,
        "llm_warnings": warnings,
        "llm_evidence_catalog": catalog,
        "llm_skipped_entities": all_skipped,
        "llm_budget": runtime.budget.snapshot(),
    }


def _context(item: dict) -> str:
    return str(item.get("qualified_name") or item.get("file_path") or item.get("class_name") or item.get("contribution_id") or "unknown")


def _identity_matches(task_type: str, context_id: str, value: dict) -> bool:
    if task_type == "file_explain":
        return value.get("file_path") == context_id
    if task_type == "function_explain":
        return value.get("qualified_name") == context_id
    if task_type == "model_explain":
        return f"{value.get('file_path')}:{value.get('class_name')}" == context_id
    if task_type == "paper_code_align":
        return value.get("contribution_id") == context_id
    return False


def _future_entity_reserve(state: dict, task_type: str) -> int:
    has_functions = bool(state.get("function_analysis"))
    has_models = bool(state.get("model_analysis"))
    has_paper = bool(state.get("paper_code_alignment", {}).get("alignment_items"))
    if task_type == "file_explain":
        return int(has_functions) + int(has_models) + int(has_paper)
    if task_type == "function_explain":
        return int(has_models) + int(has_paper)
    if task_type == "model_explain":
        return int(has_paper)
    return 0
