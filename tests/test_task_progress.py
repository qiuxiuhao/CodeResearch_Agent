from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.agents.graph import ANALYSIS_GRAPH_STEPS
from backend.app.services.task_progress import AnalysisProgressStore


class _InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return _DoneFuture()

    def shutdown(self, wait=True, cancel_futures=False):
        del wait, cancel_futures
        return None


class _DoneFuture:
    def result(self, timeout=None):
        del timeout
        return None


def test_progress_store_tracks_langgraph_node_statuses():
    store = AnalysisProgressStore()
    task = store.create(task_id="task_progress_unit")

    assert task["status"] == "queued"
    assert task["percent"] == 0

    store.update_node("task_progress_unit", "start", "repo_scan", "扫描仓库", 2, len(ANALYSIS_GRAPH_STEPS))
    running = store.get("task_progress_unit")

    assert running["status"] == "running"
    assert running["current_node"] == "repo_scan"
    assert running["completed_nodes"] == 1
    assert running["percent"] == round(1 / len(ANALYSIS_GRAPH_STEPS) * 100)
    assert running["steps"][1]["status"] == "running"

    store.update_node("task_progress_unit", "finish", "repo_scan", "扫描仓库", 2, len(ANALYSIS_GRAPH_STEPS))
    finished = store.get("task_progress_unit")

    assert finished["completed_nodes"] == 2
    assert finished["steps"][1]["status"] == "done"


def test_async_analysis_endpoint_exposes_background_progress(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    def fake_run_analysis(zip_path, output_root="outputs", library_db_path=None, paper_pdf_path=None, **kwargs):
        del zip_path, library_db_path, paper_pdf_path
        task_id = kwargs["task_id"]
        progress_callback = kwargs["progress_callback"]
        captured["task_id"] = task_id
        progress_callback("start", "unzip", "解压项目", 1, len(ANALYSIS_GRAPH_STEPS), {}, None)
        progress_callback("finish", "unzip", "解压项目", 1, len(ANALYSIS_GRAPH_STEPS), {}, None)
        progress_callback("start", "repo_scan", "扫描仓库", 2, len(ANALYSIS_GRAPH_STEPS), {}, None)
        progress_callback("finish", "repo_scan", "扫描仓库", 2, len(ANALYSIS_GRAPH_STEPS), {}, None)
        return {
            "task_id": task_id,
            "output_dir": str(tmp_path / task_id),
            "library_db_path": None,
            "errors": [],
            "analysis_mode": "rule",
            "ai_usage": {},
        }

    monkeypatch.setattr(main, "_analysis_executor", _InlineExecutor())
    monkeypatch.setattr(main, "run_analysis", fake_run_analysis)

    with TestClient(main.app) as client:
        response = client.post(
            "/analysis/tasks/async",
            json={
                "zip_path": "examples/small_pytorch_project.zip",
                "output_root": str(tmp_path),
                "analysis_mode": "rule",
                "text_llm_enabled": False,
                "teaching_narrative_llm_enabled": False,
                "vision_vlm_enabled": False,
                "image_generation_enabled": False,
                "teaching_review_vlm_enabled": False,
            },
        )

        assert response.status_code == 200
        created = response.json()
        assert created["status"] == "queued"
        assert created["task_id"] == captured["task_id"]

        progress_response = client.get(f"/analysis/tasks/{created['task_id']}/progress", params={"output_root": str(tmp_path)})
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["status"] == "completed"
    assert progress["percent"] == 100
    assert progress["current_label"] == "分析完成"
    assert progress["summary"]["task_id"] == created["task_id"]
    assert all(step["status"] == "done" for step in progress["steps"])
