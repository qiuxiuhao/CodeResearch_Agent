export type EvaluationRun = {
  run_id: string;
  dataset_version_id: string;
  subject_id: string;
  mode: string;
  status: string;
  complete: boolean;
  incomplete_reason_codes: string[];
  case_counts: Record<string, number>;
  created_at: string;
  finished_at?: string | null;
};

export type EvaluationDataset = {
  dataset_id: string;
  name: string;
  description: string;
  component_scope: string[];
  status: string;
  active_version_id?: string | null;
};

export type BaselineBinding = {
  baseline_binding_id: string;
  dataset_version_id: string;
  component: string;
  evaluation_mode: string;
  baseline_run_id: string;
  status: string;
};

export type Comparison = {
  comparison_id: string;
  baseline_run_id: string;
  candidate_run_id: string;
  status: string;
  scope: { compatibility: string; common_case_ids: string[]; incompatibility_reasons: string[] };
};

export type BadCase = {
  bad_case_id: string;
  component: string;
  symptom: string;
  status: string;
  severity: string;
  occurrence_count: number;
  source_trace_id?: string | null;
  confirmed_root_cause?: string | null;
};
