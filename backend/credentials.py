from __future__ import annotations

import os
import threading
import unicodedata
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError


SERVICE_NAME = "Nexus AI-PC API Credentials v1"
EXPECTED_WINDOWS_BACKEND = "keyring.backends.Windows.WinVaultKeyring"
SUPPORTED_PROVIDERS = (
    "openai",
    "openai-compatible",
    "anthropic",
    "google-gemini",
    "deepseek",
    "alibaba-bailian",
)

_PROVIDER_ALIASES = {
    "openai": "openai",
    "openai-compatible": "openai-compatible",
    "openai compatible": "openai-compatible",
    "兼容 openai 的服务": "openai-compatible",
    "anthropic": "anthropic",
    "google-gemini": "google-gemini",
    "google gemini": "google-gemini",
    "gemini": "google-gemini",
    "deepseek": "deepseek",
    "alibaba-bailian": "alibaba-bailian",
    "alibaba bailian": "alibaba-bailian",
    "bailian": "alibaba-bailian",
    "阿里云百炼": "alibaba-bailian",
}


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class CredentialStorageError(RuntimeError):
    """A deliberately detail-free credential backend failure."""


def normalize_provider(provider: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", provider).strip().casefold()
    return _PROVIDER_ALIASES.get(normalized)


class ApiCredentialStore:
    def __init__(self, backend: KeyringBackend | None = None) -> None:
        if backend is None:
            backend = keyring.get_keyring()
            backend_name = f"{type(backend).__module__}.{type(backend).__name__}"
            if os.name == "nt" and backend_name != EXPECTED_WINDOWS_BACKEND:
                raise RuntimeError("Secure Windows credential backend is unavailable")
        self._backend = backend
        self._lock = threading.RLock()

    def is_configured(self, provider: str) -> bool:
        return self.get(provider) is not None

    def get(self, provider: str) -> str | None:
        """Read a secret for immediate use without exposing it through the API."""
        username = self._username(provider)
        try:
            with self._lock:
                return self._backend.get_password(SERVICE_NAME, username)
        except Exception:
            raise CredentialStorageError from None

    def set(self, provider: str, secret: str) -> None:
        username = self._username(provider)
        try:
            with self._lock:
                self._backend.set_password(SERVICE_NAME, username, secret)
        except Exception:
            raise CredentialStorageError from None

    def delete(self, provider: str) -> None:
        username = self._username(provider)
        try:
            with self._lock:
                if self._backend.get_password(SERVICE_NAME, username) is None:
                    return
                self._backend.delete_password(SERVICE_NAME, username)
        except PasswordDeleteError:
            return
        except Exception:
            raise CredentialStorageError from None

    @staticmethod
    def _username(provider: str) -> str:
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError("Unsupported provider")
        return f"api-key:{provider}"
