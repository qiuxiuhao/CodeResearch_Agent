from __future__ import annotations

from typing import Protocol

from backend.app.evaluation.schemas import EvaluationRun


class EvaluationRunProcessor(Protocol):
    async def process_run(self, run_id: str) -> EvaluationRun: ...


class EvaluationGraph:
    """Independent evaluation orchestration boundary.

    The graph deliberately owns no ResearchState or business checkpoint. Durable
    progress remains in the Evaluation Store, so a coordinator can resume the same
    run after a lease expires without coupling evaluation to the research graph.
    """

    stage_order = (
        "dataset",
        "adapter_execution",
        "metric_aggregation",
        "comparison",
        "regression_gate",
        "bad_case_analysis",
    )

    def __init__(self, processor: EvaluationRunProcessor) -> None:
        self._processor = processor

    async def invoke(self, run_id: str) -> EvaluationRun:
        return await self._processor.process_run(run_id)
