from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    zip_path: str
    paper_pdf_path: str
    repo_path: str
    output_dir: str

    file_tree: dict
    python_files: list[str]
    repo_index: dict

    parsed_files: list[dict]
    functions: list[dict]
    classes: list[dict]
    file_analysis: list[dict]
    library_calls: list[dict]
    low_confidence_library_calls: list[dict]
    function_analysis: list[dict]
    model_analysis: list[dict]
    paper_analysis: dict
    paper_code_alignment: dict
    diagrams: list[dict]
    diagram_warnings: list[str]
    library_db_path: str
    structured_index_enabled: bool
    structured_index_db_path: str
    index_repository_identity: str | None
    repo_id: str
    index_version_id: str
    index_manifest: dict
    library_function_docs: list[dict]
    new_library_functions: list[dict]
    skipped_low_confidence_library_calls: list[dict]

    analysis_mode: str
    external_model_consent: bool
    text_llm_enabled: bool
    teaching_narrative_llm_enabled: bool
    vision_vlm_enabled: bool
    external_text_consent: bool
    external_vision_consent: bool
    file_llm_explanations: list[dict]
    function_llm_explanations: list[dict]
    model_llm_explanations: list[dict]
    paper_code_align_llm_explanations: list[dict]
    llm_evidence_catalog: list[dict]
    llm_skipped_entities: list[dict]
    llm_warnings: list[dict]
    llm_budget: dict
    paper_figure_analysis: dict
    vision_budget: dict
    teaching_diagrams_enabled: bool
    image_generation_enabled: bool
    teaching_review_vlm_enabled: bool
    external_image_consent: bool
    external_teaching_review_consent: bool
    teaching_diagram_specs: list[dict]
    teaching_diagram_skeletons: list[dict]
    teaching_diagram_manifest: dict
    diagram_evidence_catalog: list[dict]
    teaching_diagram_warnings: list[dict]
    teaching_plan_budget: dict
    teaching_image_budget: dict
    teaching_review_budget: dict
    ai_provider_config: dict
    ai_usage: dict

    report_md: str
    errors: list[dict]
