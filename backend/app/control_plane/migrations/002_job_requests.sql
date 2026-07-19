PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS job_requests (
  job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
  workspace_id TEXT NOT NULL,
  project_id TEXT,
  request_hash TEXT NOT NULL,
  request_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

PRAGMA user_version = 2;
