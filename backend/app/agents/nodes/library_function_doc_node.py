from __future__ import annotations

from pathlib import Path

from backend.app.schemas.state import AgentState
from backend.app.services.library_function_service import LibraryFunctionService


def library_function_doc_node(state: AgentState) -> AgentState:
    service = LibraryFunctionService(state.get("library_db_path"))
    library_calls = state.get("library_calls", [])
    errors = list(state.get("errors", []))
    project_name = _project_name(state)

    if not library_calls:
        return {
            **state,
            "library_function_docs": [],
            "new_library_functions": [],
            "skipped_low_confidence_library_calls": [],
        }

    result = service.process_library_calls(
        library_calls=library_calls,
        task_id=state.get("task_id", ""),
        project_name=project_name,
    )
    updated_library_calls = result.updated_library_calls
    updated_function_analysis = _sync_function_analysis_library_calls(
        state.get("function_analysis", []),
        updated_library_calls,
    )

    return {
        **state,
        "library_calls": updated_library_calls,
        "function_analysis": updated_function_analysis,
        "library_function_docs": [item.model_dump() for item in result.library_function_docs],
        "new_library_functions": [item.model_dump() for item in result.new_library_functions],
        "skipped_low_confidence_library_calls": result.skipped_low_confidence_calls,
        "low_confidence_library_calls": result.skipped_low_confidence_calls,
        "errors": [*errors, *result.errors],
    }


def _sync_function_analysis_library_calls(
    function_analysis: list[dict],
    updated_library_calls: list[dict],
) -> list[dict]:
    calls_by_identity = {
        _call_identity(call): call
        for call in updated_library_calls
    }
    synced: list[dict] = []
    for item in function_analysis:
        updated_item = dict(item)
        updated_calls = []
        for call in item.get("library_calls", []):
            updated_calls.append(calls_by_identity.get(_call_identity(call), call))
        updated_item["library_calls"] = updated_calls
        synced.append(updated_item)
    return synced


def _call_identity(call: dict) -> tuple:
    return (
        call.get("canonical_name"),
        call.get("file_path"),
        call.get("qualified_function_name"),
        call.get("line_no"),
        call.get("call_text"),
    )


def _project_name(state: AgentState) -> str | None:
    zip_path = state.get("zip_path")
    if zip_path:
        return Path(zip_path).stem
    repo_path = state.get("repo_path")
    if repo_path:
        return Path(repo_path).name
    return None
