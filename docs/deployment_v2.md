# v2 deployment profiles

## Local

Install the base package and run:

```bash
export CRA_BOOTSTRAP_TOKEN='a one-use random secret'
cra serve --profile local
```

Local uses `data/control_plane.sqlite3`, domain-specific SQLite stores, local artifacts, and the in-process Job backend. It is a supported long-term single-node profile. Back up the control and domain databases, artifact directory, signing key, and required active checkpoints together.

## Team

Install the `team` extra or build the supplied images. Copy deployment secrets into a protected environment file, select immutable image versions/digests, then run:

```bash
docker compose --env-file .env.team -f compose.team.yml up --build
```

The Compose stack separates API, Outbox dispatcher, domain workers, maintenance worker, one Beat process, PostgreSQL, Redis, MinIO, Qdrant, frontend, and reverse proxy. API, Worker, Scheduler, Migrator, and Auditor must use distinct database credentials. Team startup fails if PostgreSQL, Redis, S3/MinIO, or Qdrant configuration is absent; it never silently uses Local stores.

Celery transports only IDs, hashes, schema version, and attempt identity. PostgreSQL control/domain stores are authoritative. Redis loss is recovered from pending/expired Outbox and Job/Attempt records. The Celery result backend is not read for business state.

## Operations

- Use one Beat leader and database idempotency windows.
- Monitor Redis memory (warning 80%, shed non-critical work 90%, reject non-maintenance work 95%), queue age, Outbox backlog, dead jobs, worker heartbeat, Provider reservations, and database pools.
- Restore PostgreSQL, artifacts, and secrets into an isolated environment using the same Backup Manifest, then rebuild Qdrant and verify business hashes before cutover.
- Rolling upgrades use expand/dual-compatible/drain/contract. Never run contract migration while old workers or task envelopes remain.

Docker is not available in the 2026-07-19 development environment, so Compose and failure-injection validation remain release-gate work rather than a claimed passing result.

