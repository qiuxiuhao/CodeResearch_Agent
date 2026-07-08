from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.schemas.paper import (
    PaperCodeAlignment,
    PaperCodeAlignmentItem,
    PaperCodeTarget,
    UnmatchedContribution,
)


GENERIC_TERMS = {
    "architecture",
    "approach",
    "deep",
    "framework",
    "learning",
    "method",
    "model",
    "module",
    "net",
    "network",
    "paper",
    "proposed",
    "simple",
}
STRONG_ROLE_TERMS = {
    "attention",
    "backbone",
    "classifier",
    "conv",
    "conv2d",
    "decoder",
    "encoder",
    "head",
    "linear",
    "loss",
    "relu",
}


@dataclass
class CodeTargetCandidate:
    target: PaperCodeTarget
    terms: set[str]
    exact_names: set[str]
    role_terms: set[str]


def empty_paper_code_alignment(warning: str | None = None) -> PaperCodeAlignment:
    warnings = [warning] if warning else []
    return PaperCodeAlignment(paper_provided=False, warnings=warnings)


def align_paper_to_code(
    paper_analysis: dict,
    repo_index: dict,
    file_analysis: list[dict],
    classes: list[dict],
    functions: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
    library_calls: list[dict],
) -> PaperCodeAlignment:
    if not paper_analysis.get("paper_provided"):
        return empty_paper_code_alignment("未提供论文 PDF，跳过论文代码对齐。")

    targets = _build_code_targets(
        repo_index,
        file_analysis,
        classes,
        functions,
        function_analysis,
        model_analysis,
        library_calls,
    )
    alignment_items: list[PaperCodeAlignmentItem] = []
    unmatched: list[UnmatchedContribution] = []

    for contribution in paper_analysis.get("contributions", []):
        query_terms = _terms_from_contribution(contribution, paper_analysis.get("module_names", []))
        scored = [
            _score_target(contribution, query_terms, target)
            for target in targets
        ]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: item[0], reverse=True)
        best = scored[:5]
        top_score = best[0][0] if best else 0
        has_strong_evidence = any(item[4] for item in best if item[0] >= 3)
        status = "matched" if top_score >= 3 and has_strong_evidence else "unmatched"
        confidence = _confidence_from_score(top_score, best)

        if status == "unmatched":
            reason = (
                "仅存在泛化词或弱关键词重叠，缺少可确认的代码名称、模块角色或库函数证据。"
                if top_score > 0
                else "未找到达到最低阈值的代码目标。"
            )
            unmatched.append(
                UnmatchedContribution(
                    contribution_id=contribution.get("id", ""),
                    contribution_title=contribution.get("title", ""),
                    reason=reason,
                )
            )
            alignment_items.append(
                PaperCodeAlignmentItem(
                    contribution_id=contribution.get("id", ""),
                    contribution_title=contribution.get("title", ""),
                    status="unmatched",
                    matched_targets=[],
                    matched_keywords=[],
                    reason=reason,
                    confidence="low",
                    evidence=["仅基于论文关键词和代码结构做启发式匹配，当前无可靠对应关系。"],
                )
            )
            continue

        matched_targets = _dedupe_targets([target.target for score, target, _keywords, _evidence, strong in best if score >= 3 and strong])
        matched_keywords = _dedupe([
            keyword
            for score, _target, keywords, _evidence, strong in best
            if score >= 3 and strong
            for keyword in keywords
        ])
        evidence = [
            evidence
            for score, _target, _keywords, evidences, strong in best
            if score >= 3 and strong
            for evidence in evidences
        ]
        alignment_items.append(
            PaperCodeAlignmentItem(
                contribution_id=contribution.get("id", ""),
                contribution_title=contribution.get("title", ""),
                status="matched",
                matched_targets=matched_targets,
                matched_keywords=matched_keywords,
                reason=f"最高启发式匹配分数为 {top_score}，匹配到 {len(matched_targets)} 个代码目标。",
                confidence=confidence,  # type: ignore[arg-type]
                evidence=evidence,
            )
        )

    return PaperCodeAlignment(
        paper_provided=True,
        alignment_items=alignment_items,
        unmatched_contributions=unmatched,
    )


def _build_code_targets(
    repo_index: dict,
    file_analysis: list[dict],
    classes: list[dict],
    functions: list[dict],
    function_analysis: list[dict],
    model_analysis: list[dict],
    library_calls: list[dict],
) -> list[CodeTargetCandidate]:
    candidates: list[CodeTargetCandidate] = []
    file_analysis_by_path = {item.get("file_path"): item for item in file_analysis}
    function_analysis_by_key = {
        (item.get("file_path", ""), item.get("qualified_name", "")): item
        for item in function_analysis
    }

    for file_path in repo_index.get("python_files", []):
        file_info = file_analysis_by_path.get(file_path, {})
        text = " ".join([
            file_path,
            file_info.get("file_type", ""),
            file_info.get("purpose", ""),
            " ".join(file_info.get("main_classes", [])),
            " ".join(file_info.get("main_functions", [])),
        ])
        candidates.append(_candidate("file", file_path, file_path, None, None, text, [f"文件路径和文件分析：{file_path}"]))

    for class_info in classes:
        name = class_info.get("class_name", "")
        text = " ".join([name, class_info.get("file_path", ""), " ".join(class_info.get("base_classes", []))])
        candidates.append(_candidate("class", name, class_info.get("file_path"), name, class_info.get("start_line"), text, [f"类 {name} 位于 {class_info.get('file_path')}"]))

    for function in functions:
        class_name = function.get("class_name")
        qualified_name = f"{class_name}.{function.get('function_name')}" if class_name else function.get("function_name", "")
        analysis = function_analysis_by_key.get((function.get("file_path", ""), qualified_name), {})
        library_call_names = " ".join(call.get("canonical_name", "") for call in analysis.get("library_calls", []))
        text = " ".join([
            qualified_name,
            function.get("file_path", ""),
            analysis.get("purpose", ""),
            analysis.get("model_position") or "",
            library_call_names,
        ])
        candidates.append(_candidate("function", qualified_name, function.get("file_path"), qualified_name, function.get("start_line"), text, [f"函数 {qualified_name} 位于 {function.get('file_path')}"]))

    for model in model_analysis:
        for layer in model.get("layers", []):
            name = layer.get("assigned_name", layer.get("name", ""))
            text = " ".join([name, layer.get("layer_type", ""), layer.get("role", ""), model.get("class_name", "")])
            candidates.append(_candidate("model_module", name, model.get("file_path"), model.get("class_name"), layer.get("line_no"), text, layer.get("evidence", [])))
        for component in model.get("component_candidates", []):
            name = component.get("name", "")
            text = " ".join([name, component.get("role", ""), model.get("class_name", "")])
            candidates.append(_candidate("model_module", name, component.get("file_path"), model.get("class_name"), component.get("line_no"), text, component.get("evidence", [])))

    for call in library_calls:
        name = call.get("canonical_name", "")
        if not name:
            continue
        candidates.append(_candidate("function", name, call.get("file_path"), call.get("qualified_function_name"), call.get("line_no"), name, [f"库函数调用 {name}"]))

    return candidates


def _candidate(
    target_type: str,
    name: str,
    file_path: str | None,
    qualified_name: str | None,
    line_no: int | None,
    text: str,
    evidence: list[str],
) -> CodeTargetCandidate:
    terms = set(_normalize_terms(text))
    exact_names = {name.lower(), *(term.lower() for term in re.split(r"[./:]", name) if term)}
    role_terms = terms & (STRONG_ROLE_TERMS | {"activation", "embedding", "normalization", "transformer", "fusion"})
    return CodeTargetCandidate(
        target=PaperCodeTarget(
            target_type=target_type,  # type: ignore[arg-type]
            name=name,
            file_path=file_path,
            qualified_name=qualified_name,
            line_no=line_no,
            evidence=evidence or [f"代码目标：{name}"],
        ),
        terms=terms,
        exact_names=exact_names,
        role_terms=role_terms,
    )


def _terms_from_contribution(contribution: dict, module_names: list[str]) -> set[str]:
    text = " ".join([
        contribution.get("title", ""),
        contribution.get("description", ""),
        " ".join(contribution.get("keywords", [])),
        " ".join(module_names),
    ])
    return set(_normalize_terms(text))


def _score_target(
    contribution: dict,
    query_terms: set[str],
    target: CodeTargetCandidate,
) -> tuple[int, CodeTargetCandidate, list[str], list[str], bool]:
    score = 0
    evidence: list[str] = []
    has_strong_evidence = False
    matched_terms = sorted((query_terms & target.terms) - GENERIC_TERMS)
    contribution_text = f"{contribution.get('title', '')} {contribution.get('description', '')}".lower()

    exact_matches = [
        name
        for name in target.exact_names
        if name and name not in GENERIC_TERMS and name in contribution_text
    ]
    if exact_matches:
        score += 5
        has_strong_evidence = True
        evidence.append(f"论文贡献文本精确包含代码目标名称：{', '.join(exact_matches[:3])}。")

    if matched_terms:
        score += len(matched_terms)
        evidence.append(f"关键词重叠：{', '.join(matched_terms[:8])}。")

    role_matches = sorted((query_terms & target.role_terms) & STRONG_ROLE_TERMS)
    if role_matches:
        score += 3
        has_strong_evidence = True
        evidence.append(f"模块角色匹配：{', '.join(role_matches)}。")

    if "loss" in query_terms and "loss" in target.terms:
        score += 2
        has_strong_evidence = True
        evidence.append("论文贡献和代码目标均命中 loss。")

    return score, target, _dedupe([*matched_terms, *role_matches, *exact_matches]), evidence, has_strong_evidence


def _confidence_from_score(score: int, scored_targets: list[tuple[int, CodeTargetCandidate, list[str], list[str], bool]]) -> str:
    evidence_count = sum(len(evidence) for item_score, _target, _keywords, evidence, strong in scored_targets if item_score >= 3 and strong)
    if score >= 7 and evidence_count >= 2:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _normalize_terms(text: str) -> list[str]:
    split_text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.replace("_", " "))
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+-]*", split_text)
    terms: list[str] = []
    for token in raw_tokens:
        normalized = token.lower()
        if len(normalized) < 3:
            continue
        if normalized.endswith("s") and len(normalized) > 4:
            normalized = normalized[:-1]
        terms.append(normalized)
    return _dedupe(terms)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_targets(targets: list[PaperCodeTarget]) -> list[PaperCodeTarget]:
    seen: set[tuple[str, str, str | None, int | None]] = set()
    result: list[PaperCodeTarget] = []
    for target in targets:
        key = (target.target_type, target.name, target.file_path, target.line_no)
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
    return result
