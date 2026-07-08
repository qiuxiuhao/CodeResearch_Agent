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
    library_calls: list[dict] | None = None,
) -> ReportResult:
    report_md = build_report_markdown(
        repo_index,
        parsed_files,
        functions,
        classes,
        errors or [],
        file_analysis or [],
        function_analysis or [],
        library_calls or [],
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
    library_calls: list[dict] | None = None,
) -> str:
    lines = [
        "# CodeResearch Agent v0.3 Report",
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
            "## v0.3 Notes",
            "",
            "This report is generated from deterministic ZIP extraction, repository scanning, Python AST parsing, file-level analysis, function-level analysis, and basic library call extraction. Global library documentation, paper analysis, model graph generation, frontend views, and PDF export are reserved for later stages.",
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
