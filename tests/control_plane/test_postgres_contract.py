from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
ROLE_SQL = (ROOT / "backend/app/control_plane/postgres/001_roles_and_rls.sql").read_text()
FUNCTION_SQL = (ROOT / "backend/app/control_plane/postgres/002_scheduler_functions.sql").read_text()


def test_force_rls_applies_to_api_and_worker_roles():
    assert "FORCE ROW LEVEL SECURITY" in ROLE_SQL
    assert "TO cra_api" in ROLE_SQL
    assert "TO cra_worker" in ROLE_SQL


def test_scheduler_cannot_read_domain_content():
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA cra_control FROM cra_scheduler" in ROLE_SQL
    assert "GRANT EXECUTE" in FUNCTION_SQL
    assert "TO cra_scheduler" in FUNCTION_SQL


def test_scheduler_claim_returns_minimal_metadata():
    signature = FUNCTION_SQL.split("CREATE OR REPLACE FUNCTION cra_control.claim_next_job", 1)[1]
    signature = signature.split("LANGUAGE plpgsql", 1)[0]
    for forbidden in ("gold", "prompt", "artifact_content", "trace_event", "checkpoint"):
        assert forbidden not in signature.casefold()
    for required in ("job_id text", "workspace_id text", "attempt_id text", "request_hash text"):
        assert required in signature


def test_scheduler_functions_fix_search_path_and_revoke_public():
    assert FUNCTION_SQL.count("SECURITY DEFINER") >= 4
    assert FUNCTION_SQL.count("SET search_path = pg_catalog, cra_control") >= 4
    assert FUNCTION_SQL.count("REVOKE ALL ON FUNCTION") >= 4


def test_outbox_claim_contains_lease_and_deduplication_contract():
    for field in (
        "claim_token_hash", "lease_owner_hash", "lease_until",
        "message_deduplication_key", "publish_attempt",
    ):
        assert field in ROLE_SQL + FUNCTION_SQL
