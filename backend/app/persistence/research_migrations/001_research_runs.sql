PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    repo_id TEXT NOT NULL,
    index_version_id TEXT NOT NULL,
    parent_run_id TEXT,
    continued_from_run_id TEXT,
    seed_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key_hash TEXT,
    caller_scope_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'queued','routing','planning','retrieving','executing','assessing','replanning',
        'building_context','generating','validating','verifying','finalizing','paused',
        'interrupted','cancelling','completed','partial','failed','cancelled'
    )),
    route TEXT CHECK(route IS NULL OR route IN ('direct','planned')),
    current_plan_id TEXT,
    current_plan_version TEXT,
    graph_version TEXT NOT NULL,
    state_schema_version TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    resume_count INTEGER NOT NULL DEFAULT 0,
    last_resumed_at TEXT,
    current_phase_before_pause TEXT,
    checkpoint_id TEXT,
    result_json TEXT,
    budget_json TEXT NOT NULL DEFAULT '{}',
    errors_json TEXT NOT NULL DEFAULT '[]',
    stop_reason TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0,1)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(parent_run_id) REFERENCES research_runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY(continued_from_run_id) REFERENCES research_runs(run_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_research_run_idempotency
ON research_runs(caller_scope_hash, idempotency_key_hash)
WHERE idempotency_key_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_research_runs_status_updated
ON research_runs(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_research_runs_repo_version
ON research_runs(repo_id, index_version_id, created_at);

CREATE TABLE IF NOT EXISTS research_run_leases (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id) ON DELETE CASCADE,
    lease_owner TEXT NOT NULL,
    lease_token_hash TEXT NOT NULL,
    lease_acquired_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_run_leases_expiry
ON research_run_leases(lease_expires_at);

CREATE TABLE IF NOT EXISTS research_plan_versions (
    plan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    plan_version TEXT NOT NULL,
    canonical_plan_json TEXT NOT NULL,
    planner_request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','superseded','rejected')),
    replaced_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, plan_version)
);
CREATE INDEX IF NOT EXISTS idx_research_plan_versions_run
ON research_plan_versions(run_id, created_at);

PRAGMA user_version = 1;
