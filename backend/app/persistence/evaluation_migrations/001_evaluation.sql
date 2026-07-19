PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS evaluation_subjects (
    subject_id TEXT PRIMARY KEY,
    subject_hash TEXT NOT NULL UNIQUE,
    subject_type TEXT NOT NULL,
    subject_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_datasets (
    dataset_id TEXT PRIMARY KEY,
    dataset_family_id TEXT NOT NULL,
    status TEXT NOT NULL,
    dataset_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_dataset_versions (
    dataset_version_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    frozen_at TEXT,
    FOREIGN KEY(dataset_id) REFERENCES evaluation_datasets(dataset_id)
);
CREATE TABLE IF NOT EXISTS evaluation_cases (
    case_id TEXT PRIMARY KEY,
    stable_case_family_id TEXT NOT NULL,
    dataset_version_id TEXT NOT NULL,
    component TEXT NOT NULL,
    split TEXT NOT NULL,
    source TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    case_json TEXT NOT NULL,
    FOREIGN KEY(dataset_version_id) REFERENCES evaluation_dataset_versions(dataset_version_id)
);
CREATE TABLE IF NOT EXISTS evaluation_execution_environments (
    environment_id TEXT PRIMARY KEY,
    environment_hash TEXT NOT NULL UNIQUE,
    environment_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_plans (
    plan_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    FOREIGN KEY(dataset_version_id) REFERENCES evaluation_dataset_versions(dataset_version_id),
    FOREIGN KEY(subject_id) REFERENCES evaluation_subjects(subject_id)
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    dataset_version_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    run_fingerprint_hash TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    retry_of_run_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    caller_scope_hash TEXT NOT NULL DEFAULT '',
    run_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(plan_id) REFERENCES evaluation_plans(plan_id),
    FOREIGN KEY(subject_id) REFERENCES evaluation_subjects(subject_id),
    FOREIGN KEY(environment_id) REFERENCES evaluation_execution_environments(environment_id)
);
CREATE TABLE IF NOT EXISTS evaluation_run_leases (
    run_id TEXT PRIMARY KEY,
    lease_owner TEXT NOT NULL,
    lease_token_hash TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS evaluation_case_results (
    result_id TEXT PRIMARY KEY,
    evaluation_run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    evaluation_outcome TEXT,
    complete INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    FOREIGN KEY(evaluation_run_id) REFERENCES evaluation_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(case_id) REFERENCES evaluation_cases(case_id)
);
CREATE TABLE IF NOT EXISTS evaluation_metric_definitions (
    metric_definition_id TEXT PRIMARY KEY,
    component TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    definition_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_metric_results (
    metric_result_id TEXT PRIMARY KEY,
    evaluation_run_id TEXT NOT NULL,
    metric_definition_id TEXT NOT NULL,
    complete INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    FOREIGN KEY(evaluation_run_id) REFERENCES evaluation_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(metric_definition_id) REFERENCES evaluation_metric_definitions(metric_definition_id)
);
CREATE TABLE IF NOT EXISTS evaluation_comparisons (
    comparison_id TEXT PRIMARY KEY,
    baseline_run_id TEXT NOT NULL,
    candidate_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    comparison_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regression_gate_configs (
    gate_config_version TEXT PRIMARY KEY,
    profile_type TEXT NOT NULL,
    config_hash TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regression_gates (
    gate_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    gate_config_version TEXT NOT NULL,
    verdict TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    FOREIGN KEY(comparison_id) REFERENCES evaluation_comparisons(comparison_id),
    FOREIGN KEY(gate_config_version) REFERENCES regression_gate_configs(gate_config_version)
);
CREATE TABLE IF NOT EXISTS evaluation_baseline_bindings (
    baseline_binding_id TEXT PRIMARY KEY,
    dataset_version_id TEXT NOT NULL,
    component TEXT NOT NULL,
    evaluation_mode TEXT NOT NULL,
    gate_config_version TEXT NOT NULL,
    baseline_run_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL,
    binding_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    FOREIGN KEY(baseline_run_id) REFERENCES evaluation_runs(run_id),
    FOREIGN KEY(subject_id) REFERENCES evaluation_subjects(subject_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_evaluation_active_baseline
ON evaluation_baseline_bindings(dataset_version_id, component, evaluation_mode, gate_config_version)
WHERE status='active';
CREATE TABLE IF NOT EXISTS bad_cases (
    bad_case_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    component TEXT NOT NULL,
    case_id TEXT NOT NULL,
    bad_case_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bad_case_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    bad_case_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    case_result_id TEXT NOT NULL,
    occurrence_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(bad_case_id) REFERENCES bad_cases(bad_case_id)
);
CREATE TABLE IF NOT EXISTS bad_case_events (
    event_id TEXT PRIMARY KEY,
    bad_case_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(bad_case_id, sequence),
    FOREIGN KEY(bad_case_id) REFERENCES bad_cases(bad_case_id)
);
CREATE TABLE IF NOT EXISTS bad_case_verifications (
    verification_id TEXT PRIMARY KEY,
    bad_case_id TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    FOREIGN KEY(bad_case_id) REFERENCES bad_cases(bad_case_id)
);
CREATE TABLE IF NOT EXISTS bad_case_evidence_refs (
    bad_case_id TEXT NOT NULL,
    artifact_ref_id TEXT NOT NULL,
    PRIMARY KEY(bad_case_id, artifact_ref_id),
    FOREIGN KEY(bad_case_id) REFERENCES bad_cases(bad_case_id)
);
CREATE TABLE IF NOT EXISTS regression_case_promotions (
    promotion_id TEXT PRIMARY KEY,
    bad_case_id TEXT NOT NULL,
    target_dataset_version_id TEXT NOT NULL,
    reproduction_status TEXT NOT NULL,
    promotion_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(bad_case_id) REFERENCES bad_cases(bad_case_id)
);
CREATE TABLE IF NOT EXISTS evaluation_replay_manifests (
    replay_manifest_id TEXT PRIMARY KEY,
    source_evaluation_run_id TEXT NOT NULL,
    readiness TEXT NOT NULL,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_artifact_refs (
    artifact_ref_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    storage_kind TEXT NOT NULL,
    artifact_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_idempotency_keys (
    caller_scope_hash TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(caller_scope_hash, key_hash),
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_evaluation_cases_version ON evaluation_cases(dataset_version_id, component, split);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_status ON evaluation_runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_subject ON evaluation_runs(subject_id, dataset_version_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_results_run ON evaluation_case_results(evaluation_run_id, case_id);
CREATE INDEX IF NOT EXISTS idx_metric_results_run ON evaluation_metric_results(evaluation_run_id, metric_definition_id);
CREATE INDEX IF NOT EXISTS idx_bad_cases_status ON bad_cases(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_bad_occurrences_case ON bad_case_occurrences(bad_case_id, observed_at);

PRAGMA user_version = 1;
