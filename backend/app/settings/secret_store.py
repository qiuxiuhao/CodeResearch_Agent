from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
SERVICE_NAME = "coderesearch-agent"


class SecretStoreConflictError(RuntimeError):
    pass


class SecretStoreError(RuntimeError):
    pass


class SecretStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("CODE_RESEARCH_AGENT_SECRET_STORE_PATH", "~/.coderesearch_agent/secrets.json")).expanduser()
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._backup_corrupt_file()
            raise SecretStoreError("Secret store is unreadable or damaged.") from exc
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            self._backup_corrupt_file()
            raise SecretStoreError("Secret store schema is invalid.")
        data.setdefault("revision", 0)
        data.setdefault("providers", {})
        return data

    def current_revision(self) -> int:
        try:
            return int(self.read().get("revision", 0))
        except SecretStoreError:
            return 0

    def provider_config(self, provider_id: str) -> dict[str, Any]:
        try:
            provider = self.read().get("providers", {}).get(provider_id, {})
        except SecretStoreError:
            return {}
        config = provider.get("config", {})
        return dict(config) if isinstance(config, dict) else {}

    def provider_api_key(self, provider_id: str) -> str:
        try:
            provider = self.read().get("providers", {}).get(provider_id, {})
        except SecretStoreError:
            return ""
        if provider.get("api_key_source") == "keyring":
            value = _keyring_get(provider_id)
            if value:
                return value
        value = provider.get("api_key")
        return str(value) if isinstance(value, str) else ""

    def has_ui_api_key(self, provider_id: str) -> bool:
        return bool(self.provider_api_key(provider_id))

    def update_provider(
        self,
        provider_id: str,
        *,
        config: dict[str, Any],
        api_key: str | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        def mutate(data: dict[str, Any]) -> None:
            providers = data.setdefault("providers", {})
            provider = providers.setdefault(provider_id, {})
            current = dict(provider.get("config", {}))
            for key, value in config.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
            provider["config"] = current
            if api_key:
                if _keyring_set(provider_id, api_key):
                    provider.pop("api_key", None)
                    provider["api_key_source"] = "keyring"
                else:
                    provider["api_key"] = api_key
                    provider["api_key_source"] = "file"

        return self._write_mutation(expected_revision, mutate)

    def delete_api_key(self, provider_id: str, *, expected_revision: int) -> dict[str, Any]:
        def mutate(data: dict[str, Any]) -> None:
            provider = data.setdefault("providers", {}).setdefault(provider_id, {})
            if provider.get("api_key_source") == "keyring":
                _keyring_delete(provider_id)
            provider.pop("api_key", None)
            provider.pop("api_key_source", None)

        return self._write_mutation(expected_revision, mutate)

    def _write_mutation(self, expected_revision: int, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            self._ensure_parent()
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                _flock(lock_file)
                try:
                    data = self.read()
                except SecretStoreError:
                    raise
                if int(data.get("revision", 0)) != expected_revision:
                    raise SecretStoreConflictError("Provider settings revision conflict.")
                mutate(data)
                data["revision"] = int(data.get("revision", 0)) + 1
                self._atomic_write(data)
                return data

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.chmod(tmp_name, 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, self.path)
            try:
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except Exception as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise SecretStoreError("Secret store write failed.") from exc

    def _backup_corrupt_file(self) -> None:
        if not self.path.exists():
            return
        backup_path = self.path.with_suffix(self.path.suffix + ".corrupt")
        if backup_path.exists():
            return
        try:
            self._ensure_parent()
            shutil.copy2(self.path, backup_path)
            os.chmod(backup_path, 0o600)
        except Exception:
            return

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "revision": 0, "providers": {}}


class EncryptedSecretStore(SecretStore):
    """Fernet encrypted file store for headless deployments.

    The encryption key is deliberately stored separately from the encrypted payload so
    backup and restore policy can protect them independently.
    """

    def __init__(self, path: str | Path, key_path: str | Path) -> None:
        super().__init__(path)
        self.key_path = Path(key_path).expanduser()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = self._fernet(create=False).decrypt(self.path.read_bytes())
            data = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            self._backup_corrupt_file()
            raise SecretStoreError("Encrypted secret store is unreadable or damaged.") from exc
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            self._backup_corrupt_file()
            raise SecretStoreError("Secret store schema is invalid.")
        data.setdefault("revision", 0)
        data.setdefault("providers", {})
        return data

    def _atomic_write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        encrypted = self._fernet(create=True).encrypt(payload)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.chmod(tmp_name, 0o600)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, self.path)
        except Exception as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise SecretStoreError("Encrypted secret store write failed.") from exc

    def _fernet(self, *, create: bool):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise SecretStoreError("encrypted secret store requires cryptography") from exc
        if not self.key_path.exists():
            if not create:
                raise SecretStoreError("secret encryption key is missing")
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.key_path.parent, 0o700)
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        if self.key_path.stat().st_mode & 0o077:
            raise SecretStoreError("secret encryption key permissions must be 0600")
        return Fernet(self.key_path.read_bytes().strip())


class KeyringSecretStore(SecretStore):
    """Metadata file plus fail-closed operating-system keyring secrets."""

    def update_provider(
        self,
        provider_id: str,
        *,
        config: dict[str, Any],
        api_key: str | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        if api_key and not _keyring_set(provider_id, api_key):
            raise SecretStoreError("operating-system keyring is unavailable")

        def mutate(data: dict[str, Any]) -> None:
            providers = data.setdefault("providers", {})
            provider = providers.setdefault(provider_id, {})
            current = dict(provider.get("config", {}))
            for key, value in config.items():
                if value is None:
                    current.pop(key, None)
                else:
                    current[key] = value
            provider["config"] = current
            if api_key:
                provider.pop("api_key", None)
                provider["api_key_source"] = "keyring"

        return self._write_mutation(expected_revision, mutate)


def configured_secret_store() -> SecretStore:
    config_path = os.getenv("CRA_CONFIG_PATH")
    if not config_path:
        return SecretStore()
    from backend.app.config.application import ApplicationConfig

    config = ApplicationConfig.load(config_path)
    if config.security.secret_backend == "encrypted_file":
        assert config.security.secret_key_path is not None
        return EncryptedSecretStore(config.security.secret_store_path, config.security.secret_key_path)
    return KeyringSecretStore(config.security.secret_store_path)


def masked_key(value: str) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return None
    return "****" + value[-4:]


def looks_like_masked_key(value: str) -> bool:
    return "*" in value or value.startswith("****")


def _keyring_get(provider_id: str) -> str:
    try:
        import keyring  # type: ignore

        return keyring.get_password(SERVICE_NAME, provider_id) or ""
    except Exception:
        return ""


def _keyring_set(provider_id: str, value: str) -> bool:
    try:
        import keyring  # type: ignore

        keyring.set_password(SERVICE_NAME, provider_id, value)
        return True
    except Exception:
        return False


def _keyring_delete(provider_id: str) -> None:
    try:
        import keyring  # type: ignore

        keyring.delete_password(SERVICE_NAME, provider_id)
    except Exception:
        return


def _flock(file_obj) -> None:
    try:
        import fcntl

        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
    except Exception:
        return
