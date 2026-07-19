PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS workspaces (
  workspace_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_memberships (
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  membership_json TEXT NOT NULL,
  PRIMARY KEY(workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS project_memberships (
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  workspace_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  membership_json TEXT NOT NULL,
  PRIMARY KEY(project_id, user_id)
);
CREATE TABLE IF NOT EXISTS project_access_grants (
  grant_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  permission TEXT NOT NULL,
  grant_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  username_normalized TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  token_version INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  refresh_family_id TEXT NOT NULL,
  csrf_token_hash TEXT NOT NULL,
  user_agent_hash TEXT,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
  token_id TEXT PRIMARY KEY,
  family_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES user_sessions(session_id),
  token_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  revoked_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oidc_identity_links (
  link_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  issuer TEXT NOT NULL,
  subject TEXT NOT NULL,
  email_hash TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(issuer, subject)
);
CREATE TABLE IF NOT EXISTS bootstrap_tokens (
  token_hash TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
  attempt_id TEXT PRIMARY KEY,
  identity_hash TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  outcome TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS domain_runs (
  domain_run_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  job_type TEXT NOT NULL,
  queue_name TEXT NOT NULL,
  priority INTEGER NOT NULL,
  status TEXT NOT NULL,
  current_attempt_number INTEGER NOT NULL,
  idempotency_key_hash TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  revision INTEGER NOT NULL,
  job_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(workspace_id, idempotency_key_hash)
);
CREATE TABLE IF NOT EXISTS job_requests (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_attempts (
  attempt_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  attempt_number INTEGER NOT NULL,
  status TEXT NOT NULL,
  execution_token_hash TEXT NOT NULL,
  attempt_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(job_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS outbox_events (
  outbox_event_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  attempt_id TEXT NOT NULL REFERENCES job_attempts(attempt_id),
  status TEXT NOT NULL,
  message_deduplication_key TEXT NOT NULL UNIQUE,
  claim_token_hash TEXT,
  lease_owner_hash TEXT,
  lease_until TEXT,
  publish_attempt INTEGER NOT NULL,
  last_publish_error_code TEXT,
  next_retry_at TEXT,
  outbox_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  audit_event_id TEXT PRIMARY KEY,
  workspace_id TEXT,
  project_id TEXT,
  actor_id_hash TEXT NOT NULL,
  action TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  event_json TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  status TEXT NOT NULL,
  storage_key TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL,
  artifact_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_reservations (
  reservation_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  status TEXT NOT NULL,
  lease_until TEXT NOT NULL,
  reservation_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_registry (
  worker_id_hash TEXT PRIMARY KEY,
  worker_version TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL,
  worker_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS periodic_windows (
  schedule_name TEXT NOT NULL,
  scheduled_window TEXT NOT NULL,
  job_type TEXT NOT NULL,
  workspace_scope TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(schedule_name, scheduled_window, job_type, workspace_scope)
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, queue_name, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_job ON job_attempts(job_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events(status, next_retry_at, lease_until);
CREATE INDEX IF NOT EXISTS idx_audit_scope ON audit_events(workspace_id, project_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_refresh_family ON refresh_tokens(family_id, status);

PRAGMA user_version = 1;
