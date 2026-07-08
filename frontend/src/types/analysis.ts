export type Mode = "normal" | "beginner";

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

export type Diagram = {
  id?: string;
  title?: string;
  diagram_type?: string;
  description?: string;
  mermaid?: string;
  warnings?: string[];
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
  library_function_docs?: { library_function_docs?: LibraryFunctionDoc[] };
  report_md?: string;
  errors?: Array<Record<string, unknown>>;
};
