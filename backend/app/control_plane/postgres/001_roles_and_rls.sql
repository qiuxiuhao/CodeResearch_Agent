-- Run as the database owner. Runtime services never use the owner role.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$ BEGIN CREATE ROLE cra_api NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE cra_worker NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE cra_scheduler NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE cra_migrator NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE cra_auditor NOINHERIT LOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE SCHEMA IF NOT EXISTS cra_control AUTHORIZATION CURRENT_USER;
REVOKE ALL ON SCHEMA cra_control FROM PUBLIC;
GRANT USAGE ON SCHEMA cra_control TO cra_api, cra_worker, cra_scheduler, cra_auditor;

CREATE TABLE IF NOT EXISTS cra_control.jobs (
  job_id text PRIMARY KEY,
  workspace_id text NOT NULL,
  project_id text,
  job_type text NOT NULL,
  domain_run_id text NOT NULL,
  queue_name text NOT NULL,
  resource_class text NOT NULL,
  status text NOT NULL,
  priority integer NOT NULL,
  task_schema_version integer NOT NULL,
  handler_version text NOT NULL,
  idempotency_key_hash text NOT NULL,
  request_hash text NOT NULL,
  current_attempt_number integer NOT NULL,
  execution_token_hash text,
  worker_id_hash text,
  lease_until timestamptz,
  job_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_workspace_idempotency
  ON cra_control.jobs(workspace_id,idempotency_key_hash);
CREATE TABLE IF NOT EXISTS cra_control.job_attempts (
  attempt_id text PRIMARY KEY,
  job_id text NOT NULL REFERENCES cra_control.jobs(job_id),
  workspace_id text NOT NULL,
  project_id text,
  attempt_number integer NOT NULL,
  status text NOT NULL,
  execution_token_hash text NOT NULL,
  worker_id_hash text,
  lease_until timestamptz,
  task_schema_version integer NOT NULL,
  attempt_json jsonb NOT NULL,
  UNIQUE(job_id, attempt_number)
);
CREATE TABLE IF NOT EXISTS cra_control.job_requests (
  job_id text PRIMARY KEY REFERENCES cra_control.jobs(job_id),
  workspace_id text NOT NULL,
  project_id text,
  request_hash text NOT NULL,
  request_json jsonb NOT NULL,
  created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS cra_control.outbox_events (
  outbox_event_id text PRIMARY KEY,
  job_id text NOT NULL REFERENCES cra_control.jobs(job_id),
  attempt_id text NOT NULL REFERENCES cra_control.job_attempts(attempt_id),
  status text NOT NULL,
  task_schema_version integer NOT NULL,
  message_deduplication_key text NOT NULL UNIQUE,
  claim_token_hash text,
  lease_owner_hash text,
  lease_until timestamptz,
  publish_attempt integer NOT NULL DEFAULT 0,
  last_publish_error_code text,
  published_message_id text,
  next_retry_at timestamptz,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL
);
ALTER TABLE cra_control.outbox_events
  ADD COLUMN IF NOT EXISTS last_publish_error_code text;
ALTER TABLE cra_control.outbox_events
  ADD COLUMN IF NOT EXISTS published_message_id text;
CREATE TABLE IF NOT EXISTS cra_control.artifacts (
  artifact_id text PRIMARY KEY,
  workspace_id text NOT NULL,
  project_id text,
  status text NOT NULL,
  storage_key text NOT NULL,
  content_hash text NOT NULL,
  artifact_json jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS cra_control.worker_registry (
  worker_id_hash text PRIMARY KEY,
  worker_version text NOT NULL,
  min_task_schema_version integer NOT NULL,
  max_task_schema_version integer NOT NULL,
  capabilities jsonb NOT NULL,
  queue_names jsonb NOT NULL,
  heartbeat_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS cra_control.periodic_windows (
  schedule_name text NOT NULL,
  scheduled_window timestamptz NOT NULL,
  job_type text NOT NULL,
  workspace_scope text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(schedule_name, scheduled_window, job_type, workspace_scope)
);

ALTER TABLE cra_control.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cra_control.jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE cra_control.job_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE cra_control.job_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE cra_control.job_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE cra_control.job_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE cra_control.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE cra_control.artifacts FORCE ROW LEVEL SECURITY;

CREATE POLICY jobs_api_scope ON cra_control.jobs TO cra_api
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY jobs_worker_scope ON cra_control.jobs TO cra_worker
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY attempts_api_scope ON cra_control.job_attempts TO cra_api
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY attempts_worker_scope ON cra_control.job_attempts TO cra_worker
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY requests_api_scope ON cra_control.job_requests TO cra_api
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY requests_worker_scope ON cra_control.job_requests TO cra_worker
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY artifacts_api_scope ON cra_control.artifacts TO cra_api
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
)
WITH CHECK (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);
CREATE POLICY artifacts_worker_scope ON cra_control.artifacts TO cra_worker
USING (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
)
WITH CHECK (
  workspace_id = current_setting('app.workspace_id', true)
  AND (project_id IS NULL OR project_id = current_setting('app.project_id', true))
);

REVOKE ALL ON ALL TABLES IN SCHEMA cra_control FROM cra_scheduler;
GRANT SELECT, INSERT, UPDATE ON cra_control.jobs, cra_control.job_attempts,
  cra_control.job_requests, cra_control.artifacts TO cra_api;
GRANT SELECT, UPDATE ON cra_control.jobs, cra_control.job_attempts,
  cra_control.job_requests TO cra_worker;
GRANT SELECT, INSERT, UPDATE ON cra_control.artifacts TO cra_worker;
GRANT SELECT, INSERT, UPDATE ON cra_control.worker_registry TO cra_worker;
GRANT SELECT, INSERT, UPDATE ON cra_control.jobs, cra_control.job_attempts, cra_control.job_requests,
  cra_control.outbox_events, cra_control.worker_registry TO cra_migrator;
