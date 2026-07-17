from __future__ import annotations

from pathlib import Path

from backend.app.indexing.index_service import build_structured_index
from backend.app.persistence.index_store import IndexBusyError
from backend.app.schemas.state import AgentState
from backend.app.utils.json_utils import save_json


def structured_index_build_node(state: AgentState) -> AgentState:
    if not state.get("structured_index_enabled", False):
        return {**state, "index_manifest": {}}
    try:
        manifest = build_structured_index(
            state,
            repository_key=state.get("index_repository_identity"),
            index_db_path=state.get("structured_index_db_path"),
        )
        return {
            **state,
            "repo_id": manifest.repo_id,
            "index_version_id": manifest.index_version_id,
            "index_manifest": manifest.model_dump(mode="json"),
        }
    except Exception as exc:
        retryable = isinstance(exc, IndexBusyError)
        error = {
            "error_code": "index_busy" if retryable else "structured_index_build_failed",
            "component": "structured_index_build",
            "message": str(exc),
            "retryable": retryable,
            "context": {"task_id": state.get("task_id")},
            "trace_id": None,
        }
        output_dir = state.get("output_dir")
        if output_dir:
            save_json(Path(output_dir) / "index_manifest.json", {
                "manifest_version": "1.4.0",
                "index_schema_version": "1.4.0",
                "status": "in_progress" if retryable else "failed",
                "warnings": [error],
            })
        return {
            **state,
            "index_manifest": {
                "manifest_version": "1.4.0",
                "status": "in_progress" if retryable else "failed",
                "warnings": [error],
            },
            "errors": [*state.get("errors", []), error],
        }
