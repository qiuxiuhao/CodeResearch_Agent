export type Mode = "normal" | "beginner";
export type AnalysisMode = "rule" | "hybrid";

export type ResultTab =
  | "overview"
  | "files"
  | "functions"
  | "libraries"
  | "globalLibrary"
  | "models"
  | "paper"
  | "diagrams"
  | "report";

export type TaskSummary = {
  task_id?: string;
  output_dir?: string;
  has_report?: boolean;
  has_diagrams?: boolean;
  python_file_count?: number;
  class_count?: number;
  function_count?: number;
  library_call_count?: number;
  library_function_doc_count?: number;
  model_count?: number;
  paper_contribution_count?: number;
  diagram_count?: number;
  error_count?: number;
  analysis_mode?: AnalysisMode;
  external_model_consent?: boolean;
  llm_status?: string;
  llm_explanation_count?: number;
  llm_warning_count?: number;
  llm_budget?: LLMBudget;
  text_llm_enabled?: boolean;
  teaching_narrative_llm_enabled?: boolean;
  vision_vlm_enabled?: boolean;
  external_text_consent?: boolean;
  external_vision_consent?: boolean;
  vision_status?: string;
  figure_count?: number;
  vision_budget?: LLMBudget;
  teaching_diagrams_enabled?: boolean;
  image_generation_enabled?: boolean;
  teaching_review_vlm_enabled?: boolean;
  external_image_consent?: boolean;
  external_teaching_review_consent?: boolean;
  teaching_diagram_status?: string;
  teaching_diagram_count?: number;
  teaching_image_budget?: LLMBudget;
  teaching_review_budget?: LLMBudget;
  ai_usage?: AIUsage;
};

export type TaskProgressStep = {
  id: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
};

export type TaskProgress = {
  task_id: string;
  status: "queued" | "running" | "completed" | "failed";
  current_node?: string | null;
  current_label?: string | null;
  completed_nodes: number;
  total_nodes: number;
  percent: number;
  error?: string | null;
  summary?: TaskSummary | null;
  steps: TaskProgressStep[];
  created_at?: string | null;
  started_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
};

export type LibraryCall = {
  canonical_name?: string;
  display_name?: string;
  category?: string;
  confidence?: string;
  call_text?: string;
  line_no?: number | null;
  is_recorded_in_global_library?: boolean;
};

export type LibraryFunctionDoc = {
  id?: number | null;
  canonical_name: string;
  display_name?: string;
  package_name?: string | null;
  category?: string | null;
  source_type?: string;
  summary?: string;
  beginner_explanation?: string;
  parameters_explanation?: string[];
  return_explanation?: string | null;
  common_usage?: string | null;
  code_example?: string | null;
  shape_or_tensor_note?: string | null;
  common_mistakes?: string[];
  related_functions?: string[];
  official_doc_url?: string | null;
  confidence?: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type GlobalLibraryFunction = LibraryFunctionDoc;

export type GlobalLibraryFilters = {
  packages: string[];
  categories: string[];
  confidences: string[];
};

export type GlobalLibraryListResponse = {
  items: GlobalLibraryFunction[];
  total: number;
  limit: number;
  offset: number;
  filters: GlobalLibraryFilters;
};

export type GlobalLibraryDetailResponse = {
  function: GlobalLibraryFunction;
};

export type GlobalLibraryStats = {
  function_count: number;
  package_counts: Array<{ name: string; count: number }>;
  category_counts: Array<{ name: string; count: number }>;
  confidence_counts: Array<{ name: string; count: number }>;
};

export type FunctionAnalysis = {
  file_path?: string;
  qualified_name?: string;
  function_name?: string;
  purpose?: string;
  inputs?: string[];
  outputs?: string[];
  implementation_logic?: string[];
  computation_logic?: string[];
  beginner_explanation?: string | null;
  is_core_function?: boolean;
  core_reason?: string | null;
  library_calls?: LibraryCall[];
};

export type LLMCallMetadata = {
  task_type?: string;
  status?: string;
  provider?: string | null;
  model?: string | null;
  latency_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  cache_hit?: boolean;
  generated_at?: string;
};

export type LLMExplanation = {
  file_path?: string;
  qualified_name?: string;
  class_name?: string;
  contribution_id?: string;
  contribution_title?: string;
  summary?: string;
  architecture_role?: string;
  alignment_summary?: string;
  teaching_explanation?: string;
  logic_summary?: string[];
  reading_guide?: string[];
  key_relationships?: string[];
  data_flow_explanation?: string[];
  module_explanations?: string[];
  learning_notes?: string[];
  evidence_interpretation?: string[];
  evidence_refs?: string[];
  uncertainties?: string[];
  needs_review?: boolean;
  metadata?: LLMCallMetadata | null;
  possible_code_links?: Array<{
    figure_id: string;
    contribution_id: string;
    code_evidence_refs: string[];
    reason: string;
    confidence: string;
    uncertainties?: string[];
    suggested: true;
  }>;
};

export type LLMBudget = {
  max_total_entities?: number;
  selected_entities?: number;
  max_provider_requests?: number;
  reserved_provider_requests?: number;
  sent_provider_requests?: number;
  successful_provider_requests?: number;
  cache_hits?: number;
  retries?: number;
  fallbacks?: number;
};

export type AIUsageGroup = {
  enabled?: boolean;
  consent?: boolean;
  provider?: string | null;
  model?: string | null;
  configured?: boolean | null;
  request_count?: number;
  budget_limit?: number;
  selected_entities?: number;
  cache_hits?: number;
  fallbacks?: number;
  failures?: number;
  warnings?: string[];
};

export type AIUsage = {
  text_analysis?: AIUsageGroup;
  teaching_narrative?: AIUsageGroup;
  paper_vision?: AIUsageGroup;
  image_generation?: AIUsageGroup;
  teaching_review?: AIUsageGroup;
};

export type LLMExplanations = {
  analysis_mode?: AnalysisMode;
  external_model_consent?: boolean;
  text_llm_enabled?: boolean;
  external_text_consent?: boolean;
  status?: string;
  budget?: LLMBudget;
  usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number; cache_hits?: number };
  function_explanations?: LLMExplanation[];
  file_explanations?: LLMExplanation[];
  model_explanations?: LLMExplanation[];
  paper_code_alignment_explanations?: LLMExplanation[];
  warnings?: Array<Record<string, unknown>>;
};

export type LLMPublicConfig = {
  default_analysis_mode: AnalysisMode;
  max_function_explanations: number;
  max_file_explanations: number;
  max_model_explanations: number;
  max_paper_alignments: number;
  max_total_entities: number;
  max_provider_requests: number;
  max_concurrency: number;
  providers: Record<string, { configured: boolean; model: string }>;
  external_model_notice: string;
  default_text_llm_enabled?: boolean;
  default_teaching_narrative_llm_enabled?: boolean;
  vision?: VisionPublicConfig;
  image_generation?: ImageGenerationPublicConfig;
};

export type VisionPublicConfig = {
  default_vision_vlm_enabled: boolean;
  max_figure_analyses: number;
  max_provider_requests: number;
  max_concurrency: number;
  providers: Record<string, { configured: boolean; model: string }>;
  external_vision_notice: string;
};

export type ImageGenerationPublicConfig = {
  default_image_generation_enabled: boolean;
  default_teaching_review_vlm_enabled: boolean;
  max_provider_requests: number;
  max_concurrency: number;
  providers: Record<string, { configured: boolean; model: string }>;
  external_image_notice: string;
  async_supported?: boolean;
  async_notice?: string;
};

export type FigureAnalysis = {
  figure_id: string;
  figure_type: string;
  summary: string;
  modules?: Array<{ name: string; role: string }>;
  flows?: Array<{ source: string; target: string; relation: string }>;
  inputs?: string[];
  outputs?: string[];
  visual_relations?: Array<{ subject: string; relation: string; object: string }>;
  contribution_candidates?: Array<{ contribution_id: string; reason: string; confidence: string }>;
  uncertainties?: string[];
  evidence_refs?: string[];
  metadata?: LLMCallMetadata | null;
};

export type PaperFigure = {
  figure_id: string;
  page_number: number;
  page_width: number;
  page_height: number;
  page_rotation: number;
  bbox: number[];
  normalized_bbox: number[];
  caption: { label: string; text: string; confidence: string };
  original_assets?: Array<{
    asset_id: string;
    kind: string;
    path: string;
    mime_type: string;
    byte_size: number;
    sha256: string;
  }>;
  canonical_preview?: { path: string; width: number; height: number; byte_size: number; sha256: string } | null;
  selection?: { selected: boolean; score: number; reasons: string[]; skip_reason?: string | null };
  vlm_analysis?: FigureAnalysis | null;
};

export type PaperFigureAnalysis = {
  extraction_status?: string;
  vision_status?: string;
  vision_vlm_enabled?: boolean;
  external_vision_consent?: boolean;
  budget?: LLMBudget;
  figures?: PaperFigure[];
  skipped_figures?: Array<Record<string, unknown>>;
  warnings?: Array<Record<string, unknown>>;
};

export type Diagram = {
  id?: string;
  title?: string;
  diagram_type?: string;
  description?: string;
  mermaid?: string;
  warnings?: string[];
};

export type TeachingDiagramAsset = {
  path: string;
  mime_type: string;
  width: number;
  height: number;
  byte_size: number;
  sha256: string;
};

export type TeachingDiagramItem = {
  diagram_id: string;
  title: string;
  related_mermaid_diagram_ids?: string[];
  source_entity?: {
    entity_type?: string;
    entity_id?: string;
    title?: string;
    file_path?: string | null;
    qualified_name?: string | null;
    class_name?: string | null;
  };
  spec_path?: string;
  blueprint_svg?: TeachingDiagramAsset | null;
  blueprint_png?: TeachingDiagramAsset | null;
  generated_raw?: TeachingDiagramAsset | null;
  styled_composite?: TeachingDiagramAsset | null;
  final_asset?: TeachingDiagramAsset | null;
  display_variant?: "blueprint" | "ai";
  display_asset?: TeachingDiagramAsset | null;
  fallback_reason?: string | null;
  review?: { passed?: boolean; overall_score?: number } | null;
  warnings?: string[];
};

export type TeachingDiagramManifest = {
  version?: string;
  status?: string;
  teaching_diagrams_enabled?: boolean;
  teaching_narrative_llm_enabled?: boolean;
  image_generation_enabled?: boolean;
  teaching_review_vlm_enabled?: boolean;
  external_image_consent?: boolean;
  external_vision_consent?: boolean;
  external_teaching_review_consent?: boolean;
  budget?: {
    teaching_plan?: LLMBudget;
    teaching_image?: LLMBudget;
    teaching_review?: LLMBudget;
  };
  diagrams?: TeachingDiagramItem[];
  warnings?: Array<Record<string, unknown> | string>;
};

export type ProviderFieldSource = "UI" | "Environment" | "Default";

export type ProviderPublicSettings = {
  id: string;
  display_name: string;
  group: "text_llm" | "vision_vlm" | "image_generation";
  enabled: boolean;
  configured: boolean;
  masked_key?: string | null;
  revision: number;
  source: Record<string, ProviderFieldSource>;
  fields: Record<string, unknown>;
  warnings?: string[];
};

export type ProviderSettingsResponse = {
  revision: number;
  providers: ProviderPublicSettings[];
  warnings?: string[];
};

export type ProviderSettingsPayload = {
  expected_revision: number;
  enabled?: boolean;
  api_key?: string;
  base_url?: string;
  model?: string;
  timeout_seconds?: number;
  retry?: number;
  max_output_tokens?: number;
  request_width?: number;
  request_height?: number;
  allowed_domains?: string[];
  endpoint_path?: string;
  workspace?: string;
  supports_async?: boolean;
  supports_json_object?: boolean;
  disable_thinking?: boolean;
  allow_custom_base_url?: boolean;
  allow_local_endpoint?: boolean;
};

export type ProviderValidateResponse = {
  ok: boolean;
  errors: string[];
  warnings: string[];
};

export type ProviderTestResponse = {
  success: boolean;
  provider: string;
  model?: string | null;
  latency_ms?: number | null;
  warning?: string | null;
};

export type AnalysisResult = {
  task_id: string;
  summary?: TaskSummary;
  repo_index?: Record<string, unknown>;
  parsed_files?: {
    classes?: Array<Record<string, unknown>>;
    functions?: Array<Record<string, unknown>>;
    parsed_files?: Array<Record<string, unknown>>;
  };
  file_analysis?: { file_analysis?: Array<Record<string, unknown>> };
  library_calls?: { library_calls?: LibraryCall[]; low_confidence_library_calls?: LibraryCall[] };
  function_analysis?: { function_analysis?: FunctionAnalysis[] };
  model_analysis?: { model_analysis?: Array<Record<string, unknown>> };
  paper_analysis?: { paper_analysis?: Record<string, unknown> };
  paper_code_alignment?: { paper_code_alignment?: Record<string, unknown> };
  diagrams?: { diagrams?: Diagram[]; warnings?: string[] };
  teaching_diagrams?: TeachingDiagramManifest;
  library_function_docs?: { library_function_docs?: LibraryFunctionDoc[] };
  llm_explanations?: LLMExplanations;
  paper_figure_analysis?: PaperFigureAnalysis;
  ai_usage?: AIUsage;
  report_md?: string;
  errors?: Array<Record<string, unknown>>;
};
