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
) -> ReportResult:
    report_md = build_report_markdown(repo_index, parsed_files, functions, classes, errors or [])
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
) -> str:
    lines = [
        "# CodeResearch Agent v0.1 Report",
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
            "## v0.1 Notes",
            "",
            "This report is generated only from deterministic ZIP extraction, repository scanning, and Python AST parsing. Paper analysis, model graph generation, frontend views, and global library documentation are reserved for later stages.",
            "",
        ]
    )
    return "\n".join(lines)


def _list_section(title: str, items: list[str]) -> str:
    if not items:
        return f"- {title}: none"
    joined = ", ".join(f"`{item}`" for item in items)
    return f"- {title}: {joined}"

