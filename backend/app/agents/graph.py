from __future__ import annotations

from collections.abc import Callable
from functools import partial

from backend.app.agents.nodes.code_parse_node import code_parse_node
from backend.app.agents.nodes.diagram_generate_node import diagram_generate_node
from backend.app.agents.nodes.file_analyze_node import file_analyze_node
from backend.app.agents.nodes.file_explain_llm_node import file_explain_llm_node
from backend.app.agents.nodes.function_analyze_node import function_analyze_node
from backend.app.agents.nodes.function_explain_llm_node import function_explain_llm_node
from backend.app.agents.nodes.library_call_extract_node import library_call_extract_node
from backend.app.agents.nodes.library_function_doc_node import library_function_doc_node
from backend.app.agents.nodes.model_analyze_node import model_analyze_node
from backend.app.agents.nodes.model_explain_llm_node import model_explain_llm_node
from backend.app.agents.nodes.paper_analyze_node import paper_analyze_node
from backend.app.agents.nodes.paper_figure_analyze_vlm_node import paper_figure_analyze_vlm_node
from backend.app.agents.nodes.paper_figure_extract_node import paper_figure_extract_node
from backend.app.agents.nodes.paper_code_align_node import paper_code_align_node
from backend.app.agents.nodes.paper_code_align_llm_node import paper_code_align_llm_node
from backend.app.agents.nodes.report_generate_node import report_generate_node
from backend.app.agents.nodes.structured_index_build_node import structured_index_build_node
from backend.app.agents.nodes.repo_scan_node import repo_scan_node
from backend.app.agents.nodes.teaching_diagram_generate_node import teaching_diagram_generate_node
from backend.app.agents.nodes.teaching_diagram_plan_node import teaching_diagram_plan_node
from backend.app.agents.nodes.teaching_diagram_review_vlm_node import teaching_diagram_review_vlm_node
from backend.app.agents.nodes.unzip_node import unzip_node
from backend.app.image_generation.runtime import ImageGenerationRuntime
from backend.app.schemas.state import AgentState
from backend.app.llm.runtime import LLMRuntime
from backend.app.observability.context import start_span_or_root
from backend.app.vision.runtime import VisionRuntime

ProgressCallback = Callable[[str, str, str, int, int, AgentState | None, BaseException | None], None]
CancelCheck = Callable[[], None]

ANALYSIS_GRAPH_STEPS: list[dict[str, str]] = [
    {"id": "unzip", "label": "解压项目"},
    {"id": "repo_scan", "label": "扫描仓库"},
    {"id": "code_parse", "label": "解析 Python AST"},
    {"id": "file_analyze", "label": "文件级分析"},
    {"id": "library_call_extract", "label": "提取库函数调用"},
    {"id": "function_analyze", "label": "函数级分析"},
    {"id": "model_analyze", "label": "模型结构分析"},
    {"id": "paper_analyze", "label": "论文解析"},
    {"id": "paper_figure_extract", "label": "提取论文 Figure"},
    {"id": "paper_code_align", "label": "论文代码对齐"},
    {"id": "structured_index_build", "label": "构建结构化索引"},
    {"id": "file_explain_llm", "label": "文件 AI 解释"},
    {"id": "function_explain_llm", "label": "函数 AI 解释"},
    {"id": "model_explain_llm", "label": "模型 AI 解释"},
    {"id": "paper_figure_analyze_vlm", "label": "Figure VLM 理解"},
    {"id": "paper_code_align_llm", "label": "论文对齐 AI 解释"},
    {"id": "diagram_generate", "label": "生成 Mermaid 图示"},
    {"id": "teaching_diagram_plan", "label": "教学图规划"},
    {"id": "teaching_diagram_generate", "label": "生成教学图"},
    {"id": "teaching_diagram_review_vlm", "label": "教学图 VLM 审查"},
    {"id": "library_function_doc", "label": "生成库函数说明"},
    {"id": "report_generate", "label": "生成报告"},
]


def build_analysis_graph(
    llm_runtime: LLMRuntime | None = None,
    vision_runtime: VisionRuntime | None = None,
    image_runtime: ImageGenerationRuntime | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
):
    file_llm = partial(file_explain_llm_node, llm_runtime=llm_runtime)
    function_llm = partial(function_explain_llm_node, llm_runtime=llm_runtime)
    model_llm = partial(model_explain_llm_node, llm_runtime=llm_runtime)
    paper_llm = partial(paper_code_align_llm_node, llm_runtime=llm_runtime)
    figure_extract = partial(paper_figure_extract_node, vision_runtime=vision_runtime)
    figure_vlm = partial(paper_figure_analyze_vlm_node, vision_runtime=vision_runtime)
    teaching_plan = partial(teaching_diagram_plan_node, llm_runtime=llm_runtime)
    teaching_generate = partial(teaching_diagram_generate_node, image_runtime=image_runtime)
    teaching_review = partial(
        teaching_diagram_review_vlm_node,
        vision_runtime=vision_runtime,
        image_runtime=image_runtime,
    )
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _SequentialGraph(_instrumented_nodes({
            "unzip": unzip_node,
            "repo_scan": repo_scan_node,
            "code_parse": code_parse_node,
            "file_analyze": file_analyze_node,
            "library_call_extract": library_call_extract_node,
            "function_analyze": function_analyze_node,
            "model_analyze": model_analyze_node,
            "paper_analyze": paper_analyze_node,
            "paper_figure_extract": figure_extract,
            "paper_code_align": paper_code_align_node,
            "structured_index_build": structured_index_build_node,
            "file_explain_llm": file_llm,
            "function_explain_llm": function_llm,
            "model_explain_llm": model_llm,
            "paper_figure_analyze_vlm": figure_vlm,
            "paper_code_align_llm": paper_llm,
            "diagram_generate": diagram_generate_node,
            "teaching_diagram_plan": teaching_plan,
            "teaching_diagram_generate": teaching_generate,
            "teaching_diagram_review_vlm": teaching_review,
            "library_function_doc": library_function_doc_node,
            "report_generate": report_generate_node,
        }, progress_callback, cancel_check))

    workflow = StateGraph(AgentState)
    nodes = _instrumented_node_map({
        "unzip": unzip_node,
        "repo_scan": repo_scan_node,
        "code_parse": code_parse_node,
        "file_analyze": file_analyze_node,
        "library_call_extract": library_call_extract_node,
        "function_analyze": function_analyze_node,
        "model_analyze": model_analyze_node,
        "paper_analyze": paper_analyze_node,
        "paper_figure_extract": figure_extract,
        "paper_code_align": paper_code_align_node,
        "structured_index_build": structured_index_build_node,
        "file_explain_llm": file_llm,
        "function_explain_llm": function_llm,
        "model_explain_llm": model_llm,
        "paper_figure_analyze_vlm": figure_vlm,
        "paper_code_align_llm": paper_llm,
        "diagram_generate": diagram_generate_node,
        "teaching_diagram_plan": teaching_plan,
        "teaching_diagram_generate": teaching_generate,
        "teaching_diagram_review_vlm": teaching_review,
        "library_function_doc": library_function_doc_node,
        "report_generate": report_generate_node,
    }, progress_callback, cancel_check)
    for name, node in nodes.items():
        workflow.add_node(name, node)

    workflow.add_edge(START, "unzip")
    workflow.add_edge("unzip", "repo_scan")
    workflow.add_edge("repo_scan", "code_parse")
    workflow.add_edge("code_parse", "file_analyze")
    workflow.add_edge("file_analyze", "library_call_extract")
    workflow.add_edge("library_call_extract", "function_analyze")
    workflow.add_edge("function_analyze", "model_analyze")
    workflow.add_edge("model_analyze", "paper_analyze")
    workflow.add_edge("paper_analyze", "paper_figure_extract")
    workflow.add_edge("paper_figure_extract", "paper_code_align")
    workflow.add_edge("paper_code_align", "structured_index_build")
    workflow.add_edge("structured_index_build", "file_explain_llm")
    workflow.add_edge("file_explain_llm", "function_explain_llm")
    workflow.add_edge("function_explain_llm", "model_explain_llm")
    workflow.add_edge("model_explain_llm", "paper_figure_analyze_vlm")
    workflow.add_edge("paper_figure_analyze_vlm", "paper_code_align_llm")
    workflow.add_edge("paper_code_align_llm", "diagram_generate")
    workflow.add_edge("diagram_generate", "teaching_diagram_plan")
    workflow.add_edge("teaching_diagram_plan", "teaching_diagram_generate")
    workflow.add_edge("teaching_diagram_generate", "teaching_diagram_review_vlm")
    workflow.add_edge("teaching_diagram_review_vlm", "library_function_doc")
    workflow.add_edge("library_function_doc", "report_generate")
    workflow.add_edge("report_generate", END)
    return workflow.compile()


class _SequentialGraph:
    def __init__(self, nodes: list[Callable[[AgentState], AgentState]]) -> None:
        self._nodes = nodes

    def invoke(self, state: AgentState) -> AgentState:
        current = state
        for node in self._nodes:
            current = node(current)
        return current


def _instrumented_node_map(
    nodes: dict[str, Callable[..., AgentState]],
    callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Callable[[AgentState], AgentState]]:
    total = len(ANALYSIS_GRAPH_STEPS)
    order = {step["id"]: index for index, step in enumerate(ANALYSIS_GRAPH_STEPS, start=1)}
    labels = {step["id"]: step["label"] for step in ANALYSIS_GRAPH_STEPS}
    return {
        node_id: _wrap_progress_node(
            node_id, labels[node_id], order[node_id], total, node, callback, cancel_check,
        )
        for node_id, node in nodes.items()
    }


def _instrumented_nodes(
    nodes: dict[str, Callable[..., AgentState]],
    callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
) -> list[Callable[[AgentState], AgentState]]:
    wrapped = _instrumented_node_map(nodes, callback, cancel_check)
    return [wrapped[step["id"]] for step in ANALYSIS_GRAPH_STEPS]


def _wrap_progress_node(
    node_id: str,
    label: str,
    index: int,
    total: int,
    node: Callable[..., AgentState],
    callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
) -> Callable[[AgentState], AgentState]:
    def wrapped(state: AgentState) -> AgentState:
        handle = start_span_or_root(
            operation=f"analysis.node.{node_id}"[:160],
            trace_type="analysis",
            component="analysis_graph",
            attributes={"cra.count": index},
        )
        with handle:
            if cancel_check is not None:
                cancel_check()
            _notify_progress(callback, "start", node_id, label, index, total, state, None)
            try:
                next_state = node(state)
            except BaseException as exc:
                _notify_progress(callback, "error", node_id, label, index, total, state, exc)
                raise
            if cancel_check is not None:
                cancel_check()
            _notify_progress(callback, "finish", node_id, label, index, total, next_state, None)
            return next_state

    return wrapped


def _notify_progress(
    callback: ProgressCallback | None,
    event: str,
    node_id: str,
    label: str,
    index: int,
    total: int,
    state: AgentState | None,
    exc: BaseException | None,
) -> None:
    if callback is None:
        return
    try:
        callback(event, node_id, label, index, total, state, exc)
    except Exception:
        pass
