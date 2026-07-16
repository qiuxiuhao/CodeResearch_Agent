from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from backend.app.agents.graph import ANALYSIS_GRAPH_STEPS
from backend.app.schemas.state import AgentState


def new_task_id() -> str:
    return f"task_{uuid4().hex[:12]}"


class AnalysisProgressStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[str, dict] = {}

    def create(self, *, task_id: str | None = None, output_root: str = "outputs") -> dict:
        now = _now()
        resolved_task_id = task_id or new_task_id()
        with self._lock:
            task = {
                "task_id": resolved_task_id,
                "output_root": output_root,
                "status": "queued",
                "current_node": None,
                "current_label": "等待开始",
                "completed_nodes": 0,
                "total_nodes": len(ANALYSIS_GRAPH_STEPS),
                "percent": 0,
                "completed_node_ids": [],
                "failed_node": None,
                "error": None,
                "summary": None,
                "created_at": now,
                "started_at": None,
                "updated_at": now,
                "finished_at": None,
            }
            self._tasks[resolved_task_id] = task
            return _public_task(task)

    def mark_running(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            now = _now()
            task["status"] = "running"
            task["current_label"] = "准备运行分析图"
            task["started_at"] = task["started_at"] or now
            task["updated_at"] = now

    def update_node(
        self,
        task_id: str,
        event: str,
        node_id: str,
        label: str,
        index: int,
        total: int,
        state: AgentState | None = None,
        error: BaseException | None = None,
    ) -> None:
        del state
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            now = _now()
            task["total_nodes"] = total
            task["updated_at"] = now
            if event == "start":
                task["status"] = "running"
                task["current_node"] = node_id
                task["current_label"] = label
                task["completed_nodes"] = max(0, index - 1)
                task["percent"] = _percent(task["completed_nodes"], total)
                task["started_at"] = task["started_at"] or now
                return
            if event == "finish":
                completed = task.setdefault("completed_node_ids", [])
                if node_id not in completed:
                    completed.append(node_id)
                task["completed_nodes"] = min(total, max(index, len(completed)))
                task["percent"] = _percent(task["completed_nodes"], total)
                task["current_node"] = None
                task["current_label"] = label
                return
            if event == "error":
                task["status"] = "failed"
                task["failed_node"] = node_id
                task["current_node"] = node_id
                task["current_label"] = label
                task["error"] = str(error) if error else "分析节点失败"
                task["finished_at"] = now

    def complete(self, task_id: str, summary: dict) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            now = _now()
            task["status"] = "completed"
            task["current_node"] = None
            task["current_label"] = "分析完成"
            task["completed_nodes"] = len(ANALYSIS_GRAPH_STEPS)
            task["total_nodes"] = len(ANALYSIS_GRAPH_STEPS)
            task["percent"] = 100
            task["completed_node_ids"] = [step["id"] for step in ANALYSIS_GRAPH_STEPS]
            task["summary"] = summary
            task["updated_at"] = now
            task["finished_at"] = now

    def fail(self, task_id: str, error: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            now = _now()
            task["status"] = "failed"
            task["error"] = error
            task["updated_at"] = now
            task["finished_at"] = now

    def get(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(task_id)
            return _public_task(task)


progress_store = AnalysisProgressStore()


def _public_task(task: dict) -> dict:
    completed_ids = set(task.get("completed_node_ids", []))
    failed_node = task.get("failed_node")
    current_node = task.get("current_node")
    steps = []
    for step in ANALYSIS_GRAPH_STEPS:
        node_id = step["id"]
        status = "pending"
        if node_id in completed_ids:
            status = "done"
        if current_node == node_id and task.get("status") == "running" and node_id not in completed_ids:
            status = "running"
        if failed_node == node_id:
            status = "failed"
        steps.append({**step, "status": status})
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "current_node": task.get("current_node"),
        "current_label": task.get("current_label"),
        "completed_nodes": task.get("completed_nodes", 0),
        "total_nodes": task.get("total_nodes", len(ANALYSIS_GRAPH_STEPS)),
        "percent": task.get("percent", 0),
        "error": task.get("error"),
        "summary": task.get("summary"),
        "steps": steps,
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "updated_at": task.get("updated_at"),
        "finished_at": task.get("finished_at"),
    }


def _percent(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(completed / total * 100)))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
