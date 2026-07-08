from __future__ import annotations

from pathlib import Path

from backend.app.schemas.report import ReportResult


def generate_report(
    output_dir: str | Path,
    repo_index: dict,
    parsed_files: list[dict],
    functions: list[dict],
    classes: list[dict],
    errors: list[dict] | None = None,
    file_analysis: list[dict] | None = None,
    function_analysis: list[dict] | None = None,
    model_analysis: list[dict] | None = None,
    paper_analysis: dict | None = None,
    paper_code_alignment: dict | None = None,
    diagrams: list[dict] | None = None,
    diagram_warnings: list[str] | None = None,
    library_calls: list[dict] | None = None,
    library_function_docs: list[dict] | None = None,
    skipped_low_confidence_library_calls: list[dict] | None = None,
) -> ReportResult:
    report_md = build_report_markdown(
        repo_index,
        parsed_files,
        functions,
        classes,
        errors or [],
        file_analysis or [],
        function_analysis or [],
        model_analysis or [],
        paper_analysis or {},
        paper_code_alignment or {},
        diagrams or [],
        diagram_warnings or [],
        library_calls or [],
        library_function_docs or [],
        skipped_low_confidence_library_calls or [],
    )
    report_path = Path(output_dir) / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    return ReportResult(report_md=report_md, report_path=str(report_path))


def build_report_markdown(
    repo_index: dict,
    parsed_files: list[dict],
    functions: list[dict],
    classes: list[dict],
    errors: list[dict],
    file_analysis: list[dict] | None = None,
    function_analysis: list[dict] | None = None,
    model_analysis: list[dict] | None = None,
    paper_analysis: dict | None = None,
    paper_code_alignment: dict | None = None,
    diagrams: list[dict] | None = None,
    diagram_warnings: list[str] | None = None,
    library_calls: list[dict] | None = None,
    library_function_docs: list[dict] | None = None,
    skipped_low_confidence_library_calls: list[dict] | None = None,
) -> str:
    lines = [
        "# CodeResearch Agent v0.8.1 Report",
        "",
        "## Project Overview",
        "",
        f"- Repository path: `{repo_index.get('repo_path', '')}`",
        f"- Python files: {len(repo_index.get('python_files', []))}",
        f"- Classes: {len(classes)}",
        f"- Functions and methods: {len(functions)}",
        "",
        "## Candidate Files",
        "",
        _list_section("Entry files", repo_index.get("entry_file_candidates", [])),
        _list_section("Model files", repo_index.get("model_file_candidates", [])),
        _list_section("Training files", repo_index.get("train_file_candidates", [])),
        _list_section("Inference files", repo_index.get("infer_file_candidates", [])),
        _list_section("Config files", repo_index.get("config_file_candidates", [])),
        "",
        "## Python Files",
        "",
    ]

    python_files = repo_index.get("python_files", [])
    lines.extend(f"- `{path}`" for path in python_files)
    if not python_files:
        lines.append("- No Python files found.")

    lines.extend(["", "## Classes", ""])
    if classes:
        for class_info in classes:
            bases = ", ".join(class_info.get("base_classes", [])) or "None"
            lines.append(
                f"- `{class_info['class_name']}` in `{class_info['file_path']}` "
                f"(lines {class_info.get('start_line')}-{class_info.get('end_line')}, bases: {bases})"
            )
    else:
        lines.append("- No classes found.")

    lines.extend(["", "## Functions and Methods", ""])
    if functions:
        for function in functions:
            owner = f"{function['class_name']}." if function.get("class_name") else ""
            lines.append(
                f"- `{owner}{function['function_name']}` in `{function['file_path']}` "
                f"(lines {function.get('start_line')}-{function.get('end_line')})"
            )
    else:
        lines.append("- No functions found.")

    lines.extend(["", "## 逐文件分析", ""])
    if file_analysis:
        for item in file_analysis:
            lines.extend(
                [
                    f"### {item.get('file_path', '')}",
                    "",
                    f"- 文件类型：{_file_type_label(item.get('file_type', 'unknown'))}",
                    f"- 文件作用：{item.get('purpose', '')}",
                    f"- 项目位置：{item.get('project_position', '')}",
                    f"- 主要类：{_join_or_none(item.get('main_classes', []))}",
                    f"- 主要函数：{_join_or_none(item.get('main_functions', []))}",
                    f"- 判断依据：{_join_or_none(item.get('evidence', []), separator='；')}",
                    "",
                ]
            )
    else:
        lines.append("- No file-level analysis available.")

    lines.extend(["", "## 逐函数分析", ""])
    if function_analysis:
        for item in function_analysis:
            lines.extend(
                [
                    f"### {item.get('file_path', '')}::{item.get('qualified_name', item.get('function_name', ''))}",
                    "",
                    f"- 函数作用：{item.get('purpose', '')}",
                    f"- 输入：{_join_or_none(item.get('inputs', []))}",
                    f"- 输出：{_join_or_none(item.get('outputs', []))}",
                    f"- 是否核心函数：{'是' if item.get('is_core_function') else '否'}",
                    f"- 核心依据：{item.get('core_reason') or '无'}",
                    f"- 调用的库函数：{_join_or_none([call.get('canonical_name', '') for call in item.get('library_calls', [])])}",
                    "- 实现逻辑：",
                    *[f"  - {line}" for line in item.get("implementation_logic", [])],
                    "",
                ]
            )
    else:
        lines.append("- No function-level analysis available.")

    lines.extend(["", "## 模型网络结构分析", ""])
    if model_analysis:
        for item in model_analysis:
            layers = item.get("layers", [])
            forward_steps = item.get("forward_steps", [])
            component_candidates = item.get("component_candidates", [])
            lines.extend(
                [
                    f"### {item.get('file_path', '')}::{item.get('class_name', '')}",
                    "",
                    f"- 是否 nn.Module：{'是' if item.get('is_nn_module') else '否'}",
                    f"- 是否主模型候选：{'是' if item.get('is_main_model_candidate') else '否'}",
                    f"- 主模型依据：{item.get('main_model_reason') or '无'}",
                    f"- 输入：{_join_or_none(item.get('model_inputs', []))}",
                    f"- 输出：{_join_or_none(item.get('model_outputs', []))}",
                    "- 网络层：",
                    *[
                        f"  - {layer.get('assigned_name', '')}：{layer.get('layer_type', '')}，"
                        f"角色：{layer.get('role', 'unknown')}，行号：{layer.get('line_no') or '未知'}"
                        for layer in layers
                    ],
                    *([] if layers else ["  - 无"]),
                    "- forward 主要流程：",
                    *[
                        f"  - {step.get('order', index + 1)}. {step.get('explanation', '')}"
                        for index, step in enumerate(forward_steps)
                    ],
                    *([] if forward_steps else ["  - 无"]),
                    f"- 模块候选：{_join_or_none(_component_candidate_labels(component_candidates), separator='；')}",
                    "- 注意：v0.5 为静态基础识别，不代表完整运行时图。",
                    "",
                ]
            )
    else:
        lines.append("- No model structure analysis available.")

    lines.extend(["", "## 论文解析与论文代码对齐", ""])
    if not paper_analysis or not paper_analysis.get("paper_provided"):
        lines.append("- 未提供论文 PDF，跳过论文解析与论文代码对齐。")
    else:
        contributions = paper_analysis.get("contributions", [])
        keywords = [item.get("text", "") for item in paper_analysis.get("keywords", [])]
        module_names = paper_analysis.get("module_names", [])
        alignment_items = (paper_code_alignment or {}).get("alignment_items", [])
        unmatched = (paper_code_alignment or {}).get("unmatched_contributions", [])
        lines.extend(
            [
                f"- 论文标题：{paper_analysis.get('title') or '未识别'}",
                f"- 摘要预览：{_trim_report_text(paper_analysis.get('abstract') or '未识别', 240)}",
                f"- 关键词：{_join_or_none(keywords[:12])}",
                f"- 模块名：{_join_or_none(module_names[:10])}",
                "",
                "### 核心创新点",
                "",
            ]
        )
        if contributions:
            for contribution in contributions:
                lines.append(
                    f"- `{contribution.get('id', '')}` {contribution.get('title', '')} "
                    f"({contribution.get('confidence', 'low')}): "
                    f"{_trim_report_text(contribution.get('description', ''), 180)}"
                )
        else:
            lines.append("- 未识别到明确创新点。")
        lines.extend(["", "### 论文-代码对齐", ""])
        if alignment_items:
            for item in alignment_items:
                target_labels = _paper_target_labels(item.get("matched_targets", []))
                lines.extend(
                    [
                        f"- `{item.get('contribution_id', '')}` {item.get('status', 'unmatched')} "
                        f"({item.get('confidence', 'low')})",
                        f"  - 目标：{_join_or_none(target_labels)}",
                        f"  - 理由：{item.get('reason', '')}",
                    ]
                )
        else:
            lines.append("- 无对齐结果。")
        if unmatched:
            lines.append(f"- 未匹配创新点：{_join_or_none(_unmatched_contribution_labels(unmatched), separator='；')}")
        lines.append("- 注意：论文解析与论文代码对齐为启发式 MVP，不代表完整论文理解。")

    lines.extend(["", "## 图示分析", ""])
    if diagrams:
        for diagram in diagrams:
            lines.extend(
                [
                    f"### {diagram.get('title', diagram.get('id', '图'))}",
                    "",
                    diagram.get("description", ""),
                    "",
                    "```mermaid",
                    diagram.get("mermaid", ""),
                    "```",
                    "",
                ]
            )
            if diagram.get("warnings"):
                lines.append(f"- 注意：{_join_or_none(diagram.get('warnings', []), separator='；')}")
            source_summary = _diagram_source_summary(diagram)
            if source_summary:
                lines.append(f"- 来源：{source_summary}")
            lines.append("")
        if diagram_warnings:
            lines.append(f"- 图生成提示：{_join_or_none(diagram_warnings, separator='；')}")
    else:
        lines.append("- No diagrams generated.")

    lines.extend(["", "## Python 库函数说明", ""])
    if library_function_docs:
        for doc in library_function_docs:
            lines.extend(
                [
                    f"### {doc.get('canonical_name', '')}",
                    "",
                    f"- 一句话作用：{doc.get('summary', '')}",
                    f"- 通俗解释：{doc.get('beginner_explanation', '')}",
                    f"- 常见用途：{doc.get('common_usage') or '需结合调用上下文确认。'}",
                    f"- 注意事项：{doc.get('shape_or_tensor_note') or _join_or_none(doc.get('common_mistakes', []), separator='；')}",
                    "",
                ]
            )
    else:
        lines.append("- No library function documentation available.")
    if skipped_low_confidence_library_calls:
        lines.append("")
        lines.append(
            f"- 另有 {len(skipped_low_confidence_library_calls)} 个低置信度或 unknown 调用未写入全局库。"
        )

    lines.extend(["", "## Parse Errors", ""])
    if errors:
        for error in errors:
            lines.append(
                f"- `{error.get('path', '')}`: {error.get('error_type', 'Error')} - {error.get('message', '')}"
            )
    else:
        lines.append("- No parse errors recorded.")

    lines.extend(
        [
            "",
            "## v0.8.1 Notes",
            "",
            "This report is generated from deterministic ZIP extraction, repository scanning, Python AST parsing, file-level analysis, function-level analysis, basic library call extraction, model structure analysis, optional paper parsing and paper-code alignment, Mermaid diagram generation, and global library function documentation. The v0.8 frontend provides an interactive viewer for these outputs; complex RAG, rendered graph export, global library management pages, and PDF export are reserved for later stages.",
            "",
        ]
    )
    return "\n".join(lines)


def _list_section(title: str, items: list[str]) -> str:
    if not items:
        return f"- {title}: none"
    joined = ", ".join(f"`{item}`" for item in items)
    return f"- {title}: {joined}"


def _join_or_none(items: list[str], separator: str = ", ") -> str:
    return separator.join(items) if items else "无"


def _trim_report_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _component_candidate_labels(candidates: list[dict]) -> list[str]:
    labels: list[str] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        name = candidate.get("name", "")
        role = candidate.get("role", "")
        if not name or not role:
            continue
        key = (name, role)
        if key in seen:
            continue
        labels.append(f"{name}：{role}")
        seen.add(key)
    return labels


def _paper_target_labels(targets: list[dict]) -> list[str]:
    labels: list[str] = []
    seen: set[tuple[str, str, str | None, int | None]] = set()
    for target in targets:
        key = (
            target.get("target_type", ""),
            target.get("name", ""),
            target.get("file_path"),
            target.get("line_no"),
        )
        if key in seen:
            continue
        seen.add(key)
        labels.append(f"{target.get('target_type', '')}:{target.get('name', '')}")
    return labels


def _unmatched_contribution_labels(unmatched: list[dict | str]) -> list[str]:
    labels: list[str] = []
    for item in unmatched:
        if isinstance(item, str):
            labels.append(item)
            continue
        contribution_id = item.get("contribution_id", "")
        title = item.get("contribution_title", "")
        reason = item.get("reason", "")
        labels.append(f"{contribution_id} {title}：{reason}".strip())
    return labels


def _diagram_source_summary(diagram: dict) -> str:
    source_types: list[str] = []
    for source_ref in diagram.get("source_refs", []):
        source_type = source_ref.get("source_type", "")
        if source_type and source_type not in source_types:
            source_types.append(source_type)
    for node in diagram.get("nodes", []):
        for source_ref in node.get("source_refs", []):
            source_type = source_ref.get("source_type", "")
            if source_type and source_type not in source_types:
                source_types.append(source_type)
    return ", ".join(source_types[:5])


def _file_type_label(file_type: str) -> str:
    labels = {
        "entry": "入口文件",
        "model": "模型文件",
        "training": "训练文件",
        "inference": "推理文件",
        "dataset": "数据集文件",
        "config_related": "配置相关文件",
        "utility": "工具文件",
        "package_init": "包初始化文件",
        "ordinary_module": "普通模块",
        "unknown": "未知类型",
    }
    return labels.get(file_type, "未知类型")
