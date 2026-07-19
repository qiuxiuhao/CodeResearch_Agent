# v2 security contract

## Identity and authorization

Local accounts use Argon2id. Access tokens are short-lived; refresh tokens are random, hashed, rotated on every use, protected by Secure/HttpOnly/SameSite cookies plus CSRF double-submit, and grouped into revocable families. Reuse of a spent refresh token revokes the family. OIDC linking requires an authenticated explicit action and the unique identity is issuer plus subject, never email alone.

Authorization is enforced at API/service and database layers. Workspace membership alone does not grant Project access to ordinary members/viewers. Gold, audit, Provider settings, diagnostic traces, backup, and restore need explicit sensitive permission. Frontend visibility, request headers, client address, caller hashes, Trace context, Celery envelopes, and Redis state never grant access.

## PostgreSQL

Runtime roles are `cra_api`, `cra_worker`, `cra_scheduler`, `cra_migrator`, and `cra_auditor`. API/Worker tables use forced RLS. Scheduler can only execute fixed-search-path, public-revoked security-definer claim/recovery functions returning minimum scheduling metadata. Workspace context must be transaction-local and pooled connections are reset and checked before reuse.

## Input and artifacts

Objects are staged, quarantined, validated, and only then made available. Analysis cannot start from any other state. Archive validation blocks traversal, absolute paths, links/devices, nested archives, bombs, excessive depth/count/size/ratio, and long names. Git import requires a full commit SHA, rejects local/dangerous protocols and SSRF targets, and disables hooks/submodules/LFS by default. PDF/image readers verify magic and resource limits.

Secrets, full source, prompts, paper content, arbitrary Python objects, and credentials are forbidden in Celery payloads, Trace metadata, and logs. Pickle is not accepted by Celery or checkpoint serializers.

