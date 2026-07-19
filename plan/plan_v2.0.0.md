# CodeResearch Agent v2.0.0: production infrastructure implementation plan

Status: implementation in progress

Baseline: `v1.9.0` / `d869f88e2c0132fae7cf52adc7def28f946751c1`

Release blocker: `ALIGNMENT_BENCHMARK_PENDING`

## 1. Supported profiles

`local` remains a first-class deployment: FastAPI, bundled frontend, SQLite control plane and derived stores, local artifacts, an in-process job backend, SQLite checkpoints, and local Qdrant. `team` uses separate PostgreSQL control/observability/checkpoint connections, Redis, Celery workers, S3/MinIO, and Qdrant Server. `CRA_DEPLOYMENT_PROFILE` is mandatory in production; Team startup never falls back to Local.

## 2. Authority and transaction boundaries

- Control plane: run lifecycle, Job, Attempt, Outbox, quota, audit, membership, and artifact metadata.
- Domain stores: staged and derived analysis/index/research/alignment/evaluation facts.
- Artifact store: staged/finalized external objects managed with compensation.
- Checkpoint store: graph recovery, never job authority.
- Trace store: best-effort diagnostics, never transaction authority.

Local control records share `data/control_plane.sqlite3`. Team creates the control run, Job, initial Attempt, Outbox, quota reservation, and audit event in one PostgreSQL transaction. Files/S3, trace, checkpoints, and derived stores are not part of that transaction.

## 3. Security model

Team PostgreSQL roles are `cra_api`, `cra_worker`, `cra_scheduler`, `cra_migrator`, and `cra_auditor`. Workspace tables use forced RLS. Scheduler access is restricted to fixed-search-path security-definer claim/recovery functions returning minimal metadata. API and Worker transaction context is validated and reset before a pooled connection is reused.

Authorization combines Workspace roles (`owner`, `admin`, `member`, `viewer`) with Project roles (`project_owner`, `editor`, `reviewer`, `viewer`) and explicit sensitive grants. Caller hashes, headers, client addresses, frontend visibility, Redis, and Celery are never authorization sources.

Authentication uses Argon2id-compatible password hashing, short access tokens, rotating hashed refresh tokens with reuse-family revocation, CSRF for cookie writes, one-use bootstrap, and OIDC Authorization Code + PKCE. OIDC identities are keyed by issuer and subject and are never silently merged by email.

## 4. Job Runtime

`JobBackend` has Local `InProcessJobBackend` and Team `CeleryJobBackend` implementations. Job execution and Attempt execution have separate state machines. Automatic retry creates a new Attempt in the same Job; manual retry creates a new Job and domain run. Execution tokens and attempt numbers reject late writes.

The transactional Outbox is claimed in a short transaction, published outside all database transactions, then acknowledged in a second short transaction. A stable deduplication key plus worker claim guards makes uncertain or repeated publication safe.

Provider calls execute directly in Research/Alignment/Evaluation workers. PostgreSQL reservations and usage ledger are authoritative; Redis semaphores are only fast coordination. Per-job policies enforce business deadline < soft limit < hard limit < broker visibility timeout.

## 5. Data and artifact safety

Artifacts move through `staging -> quarantined -> validating -> available`; rejected/orphaned objects are compensated. ZIP extraction rejects traversal, links, devices, bombs, excessive depth/count/ratio, and nested archives. Git import fixes a commit, blocks unsafe protocols and SSRF, disables hooks, submodules, and LFS by default. PDF/image parsing verifies format and resource limits.

Workspace/Project resources use soft deletion and non-reusable IDs. Frozen Gold, baselines, bad cases, release artifacts, legal holds, and backups have reference-aware retention.

## 6. Operations and compatibility

Workers register job types, handler versions, task/database schema ranges, capabilities, and queues. Incompatible jobs wait for a compatible worker without consuming an Attempt. Rolling upgrades follow expand, dual-compatible deployment, drain, generation switch, contract, and old-field removal.

Production backup combines PostgreSQL logical/base backups and WAL/PITR with an independent artifact backup and encrypted secret recovery. A versioned manifest aligns application, API, schema, WAL position, artifact hash catalog, secret reference, and Qdrant rebuild inputs. Restore is verified in isolation before cutover.

Local-to-Team migration is staged, resumable, hash-verified, dry-runnable, rollback-capable, and never long-term dual-write. Trace is archived rather than imported online; Qdrant is rebuilt.

## 7. Phases

1. **v2.0-a** — freeze v1.9 baseline, release contract, profiles, state machines, compatibility, retention, backup, and E2E contract.
2. **v2.0-b** — identity, sessions, Workspace/Project authorization, and audit.
3. **v2.0-c** — catalog, local/S3 artifacts, quarantine, input security, and deletion foundations.
4. **v2.0-d1** — PostgreSQL roles, RLS, claim functions, pools, migrations, checkpointer, and import foundation.
5. **v2.0-d2** — Redis, Celery, Job/Attempt, Outbox, worker registry, quota/provider reservations, retries, cancellation, recovery, Beat, and dead jobs.
6. **v2.0-d3** — migrate Analysis, Index, Research, Alignment, Evaluation, Replay, Export, Backup, Restore, and Maintenance in order, with Local/Team equivalence and no double scheduling.
7. **v2.0-e** — PITR, artifacts/secrets recovery, retention/deletion, Local-to-Team migration, DR, and version-skew runbooks.
8. **v2.0-f** — stable `/api/v2`, OpenAPI, SDK/types, CLI, deprecation, and bounded plugin contracts.
9. **v2.0-g** — unified Workspace/Project frontend, session UX, Job Center, workers, quota, provider usage, audit, and removal of caller-scope clients.
10. **v2.0-h** — load/fault tests, two E2E journeys, restore and rolling-upgrade drills, supply-chain gates, real Alignment Gold, RC, and GA.

Each phase must specify migrations, rollback, deterministic tests, security tests, failure injection, and compatibility evidence. Domain behavior may not be altered to improve infrastructure metrics.

## 8. Release gate

GA requires Local and Team E2E journeys, Redis loss recovery from authoritative stores, duplicate-message and worker-kill safety, late-result rejection, classified retry/cancel/dead behavior, PITR plus artifact/secret restore, rolling upgrades, Local/Team business equivalence, SBOM/SAST/secret/dependency/container gates, full backend/frontend/build/validate, and closure of `ALIGNMENT_BENCHMARK_PENDING` with authorized double-annotated Gold.

Kubernetes, Kafka, service mesh, multi-region operation, online training, automatic code/prompt changes, and Celery result state as business authority are out of scope.
