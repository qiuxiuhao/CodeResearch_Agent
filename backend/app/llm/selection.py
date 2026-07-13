from __future__ import annotations

import ast


IMPORTANT_NAMES = ("forward", "__init__", "__getitem__", "main")
IMPORTANT_PREFIXES = ("train", "infer", "predict", "loss")
FILE_PRIORITY = {"entry": 0, "model": 1, "training": 2, "inference": 3, "dataset": 4}


def select_functions(function_analysis: list[dict], functions: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    source_by_key = {
        (item.get("file_path"), _qualified(item)): item
        for item in functions
    }
    scored: list[tuple[tuple, dict]] = []
    skipped: list[dict] = []
    for item in function_analysis:
        raw = source_by_key.get((item.get("file_path"), item.get("qualified_name")), {})
        if _is_simple(item, raw):
            skipped.append({"task_type": "function_explain", "context_id": function_entity_key(item), "reason": "simple_entity"})
            continue
        name = str(item.get("function_name", ""))
        important = name in IMPORTANT_NAMES or name.startswith(IMPORTANT_PREFIXES)
        score = (
            0 if item.get("is_core_function") else 1,
            0 if important else 1,
            -len(item.get("called_internal_functions", [])),
            -len(item.get("library_calls", [])),
            item.get("file_path", ""),
            item.get("start_line") or 0,
        )
        scored.append((score, item))
    ordered = [item for _, item in sorted(scored, key=lambda pair: pair[0])]
    for item in ordered[limit:]:
        skipped.append({"task_type": "function_explain", "context_id": function_entity_key(item), "reason": "type_limit"})
    return ordered[:limit], skipped


def function_entity_key(item: dict) -> str:
    return f"{item.get('file_path', '')}:{item.get('qualified_name') or _qualified(item)}"


def select_files(items: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    ordered = sorted(items, key=lambda item: (FILE_PRIORITY.get(item.get("file_type"), 9), -item.get("function_count", 0), item.get("file_path", "")))
    return ordered[:limit], _limit_skips("file_explain", ordered[limit:], "file_path")


def select_models(items: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    ordered = sorted(items, key=lambda item: (not item.get("is_main_model_candidate"), -len(item.get("forward_steps", [])), item.get("file_path", "")))
    return ordered[:limit], _limit_skips("model_explain", ordered[limit:], "class_name")


def select_alignments(items: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    confidence = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(items, key=lambda item: (item.get("status") != "matched", confidence.get(item.get("confidence"), 3), item.get("contribution_id", "")))
    return ordered[:limit], _limit_skips("paper_code_align", ordered[limit:], "contribution_id")


def _qualified(item: dict) -> str:
    return f"{item['class_name']}.{item['function_name']}" if item.get("class_name") else str(item.get("function_name", ""))


def _is_simple(analysis: dict, raw: dict) -> bool:
    name = str(analysis.get("function_name", ""))
    if analysis.get("is_core_function") or name in IMPORTANT_NAMES or name.startswith(IMPORTANT_PREFIXES):
        return False
    if analysis.get("called_internal_functions") or analysis.get("library_calls"):
        return False
    source = raw.get("source_code") or ""
    try:
        node = ast.parse(source).body[0]
        statements = list(getattr(node, "body", []))
        if statements and isinstance(statements[0], ast.Expr) and isinstance(getattr(statements[0], "value", None), ast.Constant):
            statements = statements[1:]
        complex_node = any(isinstance(item, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match)) for item in ast.walk(node))
        return len(statements) <= 3 and not complex_node
    except (SyntaxError, IndexError):
        return False


def _limit_skips(task_type: str, items: list[dict], key: str) -> list[dict]:
    return [{"task_type": task_type, "context_id": item.get(key), "reason": "type_limit"} for item in items]
