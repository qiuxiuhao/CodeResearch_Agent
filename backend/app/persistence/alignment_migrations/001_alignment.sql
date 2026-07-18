PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS alignment_model_profiles (
    model_profile_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL UNIQUE,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alignment_runs (
    run_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    index_version_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model_profile_id TEXT NOT NULL REFERENCES alignment_model_profiles(model_profile_id),
    attempt_number INTEGER NOT NULL CHECK(attempt_number >= 1),
    retry_of_run_id TEXT REFERENCES alignment_runs(run_id) ON DELETE SET NULL,
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key_hash TEXT,
    caller_scope_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'queued','profiling','recalling','featurizing','scoring','verifying',
        'ready','active','failed','superseded','cancelled'
    )),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    current_stage TEXT,
    stage_manifest_json TEXT NOT NULL DEFAULT '{}',
    profile_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    decision_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    abstained_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    activated_at TEXT,
    finished_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_alignment_idempotency
ON alignment_runs(caller_scope_hash, idempotency_key_hash)
WHERE idempotency_key_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_alignment_successful_request
ON alignment_runs(repo_id,index_version_id,paper_id,input_hash,model_profile_id)
WHERE status IN ('ready','active','superseded');

CREATE UNIQUE INDEX IF NOT EXISTS uq_alignment_active_profile
ON alignment_runs(repo_id,index_version_id,paper_id,model_profile_id)
WHERE status='active';

CREATE INDEX IF NOT EXISTS idx_alignment_runs_status
ON alignment_runs(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_alignment_runs_identity
ON alignment_runs(repo_id,index_version_id,paper_id,model_profile_id,created_at);

CREATE TABLE IF NOT EXISTS alignment_run_leases (
    run_id TEXT PRIMARY KEY REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    lease_owner TEXT NOT NULL,
    lease_token_hash TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alignment_run_leases_expiry
ON alignment_run_leases(expires_at);

CREATE TABLE IF NOT EXISTS alignment_deployments (
    deployment_id TEXT PRIMARY KEY,
    deployment_name TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    index_version_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    model_profile_id TEXT NOT NULL REFERENCES alignment_model_profiles(model_profile_id),
    active_run_id TEXT NOT NULL REFERENCES alignment_runs(run_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(deployment_name,repo_id,index_version_id,paper_id)
);

CREATE TABLE IF NOT EXISTS paper_module_profiles (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL,
    profile_type TEXT NOT NULL,
    granularity TEXT NOT NULL,
    source_group_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    PRIMARY KEY(run_id,profile_id)
);

CREATE INDEX IF NOT EXISTS idx_alignment_profiles_type
ON paper_module_profiles(run_id,profile_type,granularity);

CREATE TABLE IF NOT EXISTS alignment_candidates (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    code_entity_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL CHECK(candidate_status IN ('recalled','scored','pruned')),
    candidate_json TEXT NOT NULL,
    PRIMARY KEY(run_id,candidate_id),
    UNIQUE(run_id,profile_id,code_entity_id),
    FOREIGN KEY(run_id,profile_id) REFERENCES paper_module_profiles(run_id,profile_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alignment_candidates_entity
ON alignment_candidates(run_id,code_entity_id);

CREATE TABLE IF NOT EXISTS alignment_feature_values (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    vector_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    PRIMARY KEY(run_id,vector_id),
    FOREIGN KEY(run_id,candidate_id) REFERENCES alignment_candidates(run_id,candidate_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alignment_candidate_scores (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    score_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    score_json TEXT NOT NULL,
    PRIMARY KEY(run_id,score_id),
    FOREIGN KEY(run_id,candidate_id) REFERENCES alignment_candidates(run_id,candidate_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alignment_decisions (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    decision_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    decision_version TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    effective_revision INTEGER NOT NULL DEFAULT 0,
    review_sequence INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(run_id,decision_id),
    UNIQUE(run_id,profile_id,decision_version),
    FOREIGN KEY(run_id,profile_id) REFERENCES paper_module_profiles(run_id,profile_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alignment_decisions_status
ON alignment_decisions(run_id,status,profile_id);

CREATE TABLE IF NOT EXISTS alignment_selections (
    run_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    selection_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    selection_json TEXT NOT NULL,
    PRIMARY KEY(run_id,selection_id),
    FOREIGN KEY(run_id,decision_id) REFERENCES alignment_decisions(run_id,decision_id) ON DELETE CASCADE,
    FOREIGN KEY(run_id,candidate_id) REFERENCES alignment_candidates(run_id,candidate_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alignment_verifications (
    run_id TEXT NOT NULL REFERENCES alignment_runs(run_id) ON DELETE CASCADE,
    verification_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    PRIMARY KEY(run_id,verification_id)
);

CREATE TABLE IF NOT EXISTS alignment_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    review_sequence INTEGER NOT NULL,
    based_on_effective_revision INTEGER NOT NULL,
    review_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id,decision_id,review_sequence),
    FOREIGN KEY(run_id,decision_id) REFERENCES alignment_decisions(run_id,decision_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alignment_reviews_decision
ON alignment_reviews(run_id,decision_id,review_sequence);

PRAGMA user_version = 1;
