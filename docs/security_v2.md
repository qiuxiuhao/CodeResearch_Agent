# v2 security contract

## Identity and authorization

Local accounts use Argon2id. Access tokens are short-lived; refresh tokens are random, hashed, rotated on every use, protected by Secure/HttpOnly/SameSite cookies plus CSRF double-submit, and grouped into revocable families. Reuse of a spent refresh token revokes the family. OIDC linking requires an authenticated explicit action and the unique identity is issuer plus subject, never email alone.

Authorization is enforced at the v2 API and service layers. Workspace membership alone does not grant Project access to ordinary members/viewers. Provider settings, diagnostic traces, backup, restore, maintenance, delete, and artifact materialization need explicit scoped permission. Frontend visibility, request headers, client address, caller hashes, and Trace context never grant access.

## Local workspace scope

The maintained v2.0 profile is Local single-node. SQLite stores are selected from validated YAML configuration; clients cannot submit arbitrary database paths. HTTP business routes outside `/api/v2` are hidden from OpenAPI and fail closed unless an explicit loopback-only internal test switch is enabled.

## Input and artifacts

Objects are staged, quarantined, validated, and only then made available. Analysis cannot start from any other state. Archive validation blocks traversal, absolute paths, links/devices, nested archives, bombs, excessive depth/count/size/ratio, and long names. Git import requires a full commit SHA, rejects local/dangerous protocols and SSRF targets, and disables hooks/submodules/LFS by default. PDF/image readers verify magic and resource limits.

Secrets, full source, prompts, paper content, arbitrary Python objects, and credentials are forbidden in job payloads, Trace metadata, and logs. Pickle is not accepted by checkpoint serializers.
