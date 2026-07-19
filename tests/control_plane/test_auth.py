from __future__ import annotations

import hashlib

import pytest

from backend.app.control_plane.auth import AuthenticationError, LocalIdentityService
from backend.app.control_plane.store import LocalControlPlaneStore


class FakeHasher:
    def hash(self, password: str) -> str:
        return "test$" + hashlib.sha256(password.encode()).hexdigest()

    def verify(self, encoded: str, password: str) -> bool:
        return encoded == self.hash(password)


def _service(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    service = LocalIdentityService(store, FakeHasher(), b"k" * 48)
    user_id = service.create_user("owner@example.test", "correct horse battery")
    return store, service, user_id


def test_refresh_token_rotates_on_every_use(tmp_path):
    _, service, _ = _service(tmp_path)
    first = service.login("owner@example.test", "correct horse battery")
    second = service.refresh(first.refresh_token, first.csrf_token)
    assert second.refresh_token != first.refresh_token
    assert second.session_id == first.session_id
    assert service.verify_access(second.access_token).session_id == first.session_id


def test_refresh_token_reuse_revokes_family(tmp_path):
    _, service, _ = _service(tmp_path)
    first = service.login("owner@example.test", "correct horse battery")
    second = service.refresh(first.refresh_token, first.csrf_token)
    with pytest.raises(AuthenticationError, match="refresh_reuse_detected"):
        service.refresh(first.refresh_token, first.csrf_token)
    with pytest.raises(AuthenticationError, match="refresh_invalid"):
        service.refresh(second.refresh_token, second.csrf_token)


def test_logout_revokes_current_session(tmp_path):
    _, service, _ = _service(tmp_path)
    tokens = service.login("owner@example.test", "correct horse battery")
    service.logout(tokens.session_id)
    with pytest.raises(AuthenticationError, match="access_revoked"):
        service.verify_access(tokens.access_token)


def test_password_change_style_revocation_revokes_old_sessions(tmp_path):
    _, service, user_id = _service(tmp_path)
    tokens = service.login("owner@example.test", "correct horse battery")
    service.revoke_all_sessions(user_id)
    with pytest.raises(AuthenticationError, match="access_revoked"):
        service.verify_access(tokens.access_token)


def test_password_change_revokes_old_sessions_and_accepts_new_password(tmp_path):
    _, service, user_id = _service(tmp_path)
    tokens = service.login("owner@example.test", "correct horse battery")
    service.change_password(user_id, "correct horse battery", "new correct horse battery")
    with pytest.raises(AuthenticationError, match="access_revoked"):
        service.verify_access(tokens.access_token)
    with pytest.raises(AuthenticationError):
        service.login("owner@example.test", "correct horse battery")
    assert service.login("owner@example.test", "new correct horse battery").session_id


def test_login_failures_are_rate_limited(tmp_path):
    _, service, _ = _service(tmp_path)
    for _ in range(5):
        with pytest.raises(AuthenticationError, match="authentication_failed"):
            service.login("owner@example.test", "wrong password")
    with pytest.raises(AuthenticationError, match="login_rate_limited"):
        service.login("owner@example.test", "correct horse battery")


def test_user_can_list_and_revoke_own_session(tmp_path):
    _, service, user_id = _service(tmp_path)
    tokens = service.login("owner@example.test", "correct horse battery")
    assert [item["session_id"] for item in service.list_sessions(user_id)] == [tokens.session_id]
    service.revoke_session(user_id, tokens.session_id)
    with pytest.raises(AuthenticationError, match="access_revoked"):
        service.verify_access(tokens.access_token)


def test_oidc_email_does_not_silently_merge_account(tmp_path):
    _, service, user_id = _service(tmp_path)
    service.link_oidc(user_id, "https://issuer.example", "subject-1", "same@example.test")
    other_id = service.create_user("other@example.test", "correct horse battery")
    with pytest.raises(AuthenticationError, match="oidc_identity_already_linked"):
        service.link_oidc(other_id, "https://issuer.example", "subject-1", "same@example.test")


def test_unknown_and_wrong_password_share_external_error(tmp_path):
    _, service, _ = _service(tmp_path)
    for username, password in [
        ("missing@example.test", "correct horse battery"),
        ("owner@example.test", "wrong password value"),
    ]:
        with pytest.raises(AuthenticationError) as error:
            service.login(username, password)
        assert error.value.code == "authentication_failed"


def test_bootstrap_token_is_single_use(tmp_path):
    store = LocalControlPlaneStore(tmp_path / "control.sqlite3")
    service = LocalIdentityService(
        store, FakeHasher(), b"k" * 48, bootstrap_token="one-time-bootstrap-token",
    )
    service.bootstrap_owner(
        "one-time-bootstrap-token", "owner@example.test", "correct horse battery",
    )
    with pytest.raises(AuthenticationError, match="bootstrap_invalid"):
        service.bootstrap_owner(
            "one-time-bootstrap-token", "other@example.test", "correct horse battery",
        )
