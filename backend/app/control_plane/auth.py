from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from .store import LocalControlPlaneStore


class AuthenticationError(PermissionError):
    def __init__(self, code: str = "authentication_failed") -> None:
        super().__init__(code)
        self.code = code


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, encoded: str, password: str) -> bool: ...


class Argon2PasswordHasher:
    def __init__(self) -> None:
        try:
            from argon2 import PasswordHasher as Hasher
        except ImportError as exc:
            raise RuntimeError("identity support requires argon2-cffi") from exc
        self._hasher = Hasher(time_cost=3, memory_cost=65536, parallelism=4)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return bool(self._hasher.verify(encoded, password))
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    session_id: str
    refresh_family_id: str


@dataclass(frozen=True, slots=True)
class AccessPrincipal:
    user_id: str
    session_id: str
    token_version: int


class LocalIdentityService:
    def __init__(
        self,
        store: LocalControlPlaneStore,
        password_hasher: PasswordHasher,
        signing_key: bytes,
        *,
        access_minutes: int = 15,
        refresh_days: int = 30,
        signing_key_id: str = "local-v1",
        bootstrap_token: str | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        self.store = store
        self.password_hasher = password_hasher
        self.signing_key = signing_key
        self.access_minutes = access_minutes
        self.refresh_days = refresh_days
        self.signing_key_id = signing_key_id
        self.store.migrate()
        if bootstrap_token:
            now = datetime.now(UTC)
            with self.store._connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO bootstrap_tokens VALUES(?,?,?,?)",
                    (_hash(bootstrap_token), "active", _iso(now + timedelta(hours=24)), None),
                )

    def bootstrap_owner(self, bootstrap_token: str, username: str, password: str) -> str:
        normalized = username.strip().casefold()
        if len(normalized) < 3 or len(password) < 12:
            raise AuthenticationError("invalid_registration")
        now = datetime.now(UTC)
        token_hash = _hash(bootstrap_token)
        user_id = f"user_{uuid4().hex}"
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            token = connection.execute(
                "SELECT status,expires_at FROM bootstrap_tokens WHERE token_hash=?", (token_hash,)
            ).fetchone()
            existing_owner = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if (
                existing_owner or not token or token["status"] != "active"
                or datetime.fromisoformat(token["expires_at"]) <= now
            ):
                raise AuthenticationError("bootstrap_invalid")
            connection.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                (
                    user_id, normalized, self.password_hasher.hash(password), 1,
                    "active", _iso(now), _iso(now),
                ),
            )
            connection.execute(
                "UPDATE bootstrap_tokens SET status='used',used_at=? WHERE token_hash=?",
                (_iso(now), token_hash),
            )
            connection.commit()
        return user_id

    def create_bootstrap_token(self, *, ttl_hours: int = 24) -> str:
        if not 1 <= ttl_hours <= 168:
            raise ValueError("bootstrap token ttl must be between 1 and 168 hours")
        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise AuthenticationError("bootstrap_already_completed")
            connection.execute(
                "INSERT INTO bootstrap_tokens VALUES(?,?,?,?)",
                (_hash(token), "active", _iso(now + timedelta(hours=ttl_hours)), None),
            )
        return token

    def create_user(self, username: str, password: str) -> str:
        normalized = username.strip().casefold()
        if len(normalized) < 3 or len(password) < 12:
            raise AuthenticationError("invalid_registration")
        now = datetime.now(UTC)
        user_id = f"user_{uuid4().hex}"
        with self.store._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                    (
                        user_id, normalized, self.password_hasher.hash(password), 1,
                        "active", _iso(now), _iso(now),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthenticationError("invalid_registration") from exc
        return user_id

    def create_local_session(
        self, *, username: str = "local", user_agent: str = "",
    ) -> tuple[str, SessionTokens]:
        normalized = username.strip().casefold()
        if len(normalized) < 3:
            raise AuthenticationError("invalid_registration")
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT user_id,token_version,status FROM users WHERE username_normalized=?",
                (normalized,),
            ).fetchone()
            if row:
                if row["status"] != "active":
                    raise AuthenticationError("authentication_failed")
                user_id = row["user_id"]
                token_version = int(row["token_version"])
            else:
                user_id = f"user_{uuid4().hex}"
                token_version = 1
                connection.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                    (
                        user_id, normalized,
                        self.password_hasher.hash(secrets.token_urlsafe(48)),
                        token_version, "active", _iso(now), _iso(now),
                    ),
                )
            connection.commit()
        return user_id, self._create_session(user_id, token_version, user_agent)

    def login(self, username: str, password: str, *, user_agent: str = "") -> SessionTokens:
        normalized = username.strip().casefold()
        identity_hash = _hash(normalized)
        source_hash = _hash(user_agent or "unknown")
        self._enforce_login_limit(identity_hash)
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT user_id,password_hash,token_version,status FROM users WHERE username_normalized=?",
                (normalized,),
            ).fetchone()
        # The same external error is used for unknown and invalid credentials.
        if not row or row["status"] != "active" or not self.password_hasher.verify(row["password_hash"], password):
            self._record_login(identity_hash, source_hash, "failed")
            raise AuthenticationError()
        self._record_login(identity_hash, source_hash, "succeeded")
        return self._create_session(row["user_id"], int(row["token_version"]), user_agent)

    def list_sessions(self, user_id: str) -> list[dict[str, str | None]]:
        with self.store._connect() as connection:
            rows = connection.execute(
                """SELECT session_id,status,expires_at,created_at,updated_at,user_agent_hash
                   FROM user_sessions WHERE user_id=? ORDER BY created_at DESC""",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_session(self, user_id: str, session_id: str) -> None:
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM user_sessions WHERE session_id=?", (session_id,),
            ).fetchone()
        if not row or row["user_id"] != user_id:
            raise AuthenticationError("session_not_found")
        self.logout(session_id)

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        if len(new_password) < 12:
            raise AuthenticationError("invalid_password")
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE user_id=? AND status='active'", (user_id,),
            ).fetchone()
        if not row or not self.password_hasher.verify(row["password_hash"], current_password):
            raise AuthenticationError("authentication_failed")
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE users SET password_hash=?,token_version=token_version+1,updated_at=?
                   WHERE user_id=?""",
                (self.password_hasher.hash(new_password), _iso(now), user_id),
            )
            connection.execute(
                "UPDATE user_sessions SET status='revoked',updated_at=? WHERE user_id=?",
                (_iso(now), user_id),
            )
            connection.execute(
                """UPDATE refresh_tokens SET status='revoked',revoked_at=?
                   WHERE session_id IN (SELECT session_id FROM user_sessions WHERE user_id=?)
                     AND status='active'""",
                (_iso(now), user_id),
            )
            connection.commit()

    def refresh(self, refresh_token: str, csrf_token: str) -> SessionTokens:
        token_hash = _hash(refresh_token)
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT r.*,s.user_id,s.csrf_token_hash,s.status AS session_status,
                          u.token_version,u.status AS user_status
                   FROM refresh_tokens r JOIN user_sessions s ON s.session_id=r.session_id
                   JOIN users u ON u.user_id=s.user_id WHERE r.token_hash=?""",
                (token_hash,),
            ).fetchone()
            if not row:
                raise AuthenticationError("refresh_invalid")
            family_id = row["family_id"]
            if row["status"] == "used":
                self._revoke_family_in(connection, family_id, now)
                connection.commit()
                raise AuthenticationError("refresh_reuse_detected")
            if (
                row["status"] != "active" or row["session_status"] != "active"
                or row["user_status"] != "active" or datetime.fromisoformat(row["expires_at"]) <= now
                or not hmac.compare_digest(row["csrf_token_hash"], _hash(csrf_token))
            ):
                raise AuthenticationError("refresh_invalid")
            connection.execute(
                "UPDATE refresh_tokens SET status='used',used_at=? WHERE token_id=?",
                (_iso(now), row["token_id"]),
            )
            tokens = self._issue_tokens_in(
                connection, row["user_id"], row["session_id"], family_id,
                int(row["token_version"]), now,
            )
            connection.commit()
        return tokens

    def verify_access(self, access_token: str) -> AccessPrincipal:
        payload = self._decode_access(access_token)
        now_timestamp = int(datetime.now(UTC).timestamp())
        if int(payload.get("exp", 0)) <= now_timestamp:
            raise AuthenticationError("access_expired")
        user_id = str(payload.get("sub", ""))
        session_id = str(payload.get("sid", ""))
        with self.store._connect() as connection:
            row = connection.execute(
                """SELECT s.status,u.status AS user_status,u.token_version
                   FROM user_sessions s JOIN users u ON u.user_id=s.user_id
                   WHERE s.session_id=? AND s.user_id=?""",
                (session_id, user_id),
            ).fetchone()
        if (
            not row or row["status"] != "active" or row["user_status"] != "active"
            or int(row["token_version"]) != int(payload.get("ver", -1))
        ):
            raise AuthenticationError("access_revoked")
        return AccessPrincipal(user_id, session_id, int(row["token_version"]))

    def logout(self, session_id: str) -> None:
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT refresh_family_id FROM user_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE user_sessions SET status='revoked',updated_at=? WHERE session_id=?",
                    (_iso(now), session_id),
                )
                self._revoke_family_in(connection, row["refresh_family_id"], now)
            connection.commit()

    def revoke_all_sessions(self, user_id: str) -> None:
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE user_sessions SET status='revoked',updated_at=? WHERE user_id=?",
                (_iso(now), user_id),
            )
            connection.execute(
                """UPDATE refresh_tokens SET status='revoked',revoked_at=?
                   WHERE session_id IN (SELECT session_id FROM user_sessions WHERE user_id=?)
                     AND status='active'""",
                (_iso(now), user_id),
            )
            connection.execute(
                "UPDATE users SET token_version=token_version+1,updated_at=? WHERE user_id=?",
                (_iso(now), user_id),
            )
            connection.commit()

    def link_oidc(self, user_id: str, issuer: str, subject: str, email: str | None = None) -> str:
        if not issuer.startswith("https://") or not subject:
            raise AuthenticationError("oidc_identity_invalid")
        link_id = f"oidc_{uuid4().hex}"
        now = datetime.now(UTC)
        with self.store._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO oidc_identity_links VALUES(?,?,?,?,?,?)",
                    (link_id, user_id, issuer, subject, _hash(email.casefold()) if email else None, _iso(now)),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthenticationError("oidc_identity_already_linked") from exc
        return link_id

    def _create_session(self, user_id: str, token_version: int, user_agent: str) -> SessionTokens:
        now = datetime.now(UTC)
        session_id = f"session_{uuid4().hex}"
        family_id = f"family_{uuid4().hex}"
        csrf = secrets.token_urlsafe(32)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO user_sessions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    session_id, user_id, family_id, _hash(csrf), _hash(user_agent) if user_agent else None,
                    "active", _iso(now + timedelta(days=self.refresh_days)), _iso(now), _iso(now),
                ),
            )
            tokens = self._issue_tokens_in(
                connection, user_id, session_id, family_id, token_version, now, csrf,
            )
            connection.commit()
        return tokens

    def _issue_tokens_in(
        self, connection: sqlite3.Connection, user_id: str, session_id: str,
        family_id: str, token_version: int, now: datetime, csrf: str | None = None,
    ) -> SessionTokens:
        refresh = secrets.token_urlsafe(48)
        csrf = csrf or secrets.token_urlsafe(32)
        token_id = f"refresh_{uuid4().hex}"
        expires = now + timedelta(days=self.refresh_days)
        connection.execute(
            "INSERT INTO refresh_tokens VALUES(?,?,?,?,?,?,?,?,?)",
            (token_id, family_id, session_id, _hash(refresh), "active", _iso(expires), None, None, _iso(now)),
        )
        connection.execute(
            "UPDATE user_sessions SET csrf_token_hash=?,updated_at=? WHERE session_id=?",
            (_hash(csrf), _iso(now), session_id),
        )
        access = self._encode_access(
            {
                "sub": user_id, "sid": session_id, "ver": token_version,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=self.access_minutes)).timestamp()),
                "kid": self.signing_key_id,
            }
        )
        return SessionTokens(access, refresh, csrf, session_id, family_id)

    def _revoke_family_in(self, connection: sqlite3.Connection, family_id: str, now: datetime) -> None:
        connection.execute(
            "UPDATE refresh_tokens SET status='revoked',revoked_at=? WHERE family_id=? AND status!='revoked'",
            (_iso(now), family_id),
        )
        connection.execute(
            "UPDATE user_sessions SET status='revoked',updated_at=? WHERE refresh_family_id=?",
            (_iso(now), family_id),
        )

    def _enforce_login_limit(self, identity_hash: str) -> None:
        cutoff = _iso(datetime.now(UTC) - timedelta(minutes=15))
        with self.store._connect() as connection:
            failures = connection.execute(
                """SELECT count(*) FROM login_attempts
                   WHERE identity_hash=? AND outcome='failed' AND occurred_at>=?""",
                (identity_hash, cutoff),
            ).fetchone()[0]
        if failures >= 5:
            raise AuthenticationError("login_rate_limited")

    def _record_login(self, identity_hash: str, source_hash: str, outcome: str) -> None:
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO login_attempts VALUES(?,?,?,?,?)",
                (f"login_{uuid4().hex}", identity_hash, source_hash, outcome, _iso(datetime.now(UTC))),
            )

    def _encode_access(self, payload: dict[str, object]) -> str:
        body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _b64(hmac.new(self.signing_key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def _decode_access(self, token: str) -> dict[str, object]:
        try:
            body, signature = token.split(".", 1)
            expected = _b64(hmac.new(self.signing_key, body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise AuthenticationError("access_invalid")
            return json.loads(base64.urlsafe_b64decode(_pad(body)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationError("access_invalid") from exc


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _pad(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
