from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.credentials import SERVICE_NAME


class MemoryKeyring:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        del self.secrets[(service, username)]


class FailingKeyring(MemoryKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError(f"backend accidentally included {password}")


def make_credential_client(
    tmp_path: Path,
    backend: MemoryKeyring,
) -> tuple[Path, TestClient]:
    database_path = tmp_path / "credentials.sqlite3"
    app = create_app(
        database_path,
        serve_static=False,
        credential_backend=backend,
    )
    return database_path, TestClient(app)


def test_write_and_status_never_expose_or_persist_secret(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    database_path, client = make_credential_client(tmp_path, backend)
    secret = "sk-test-super-secret-value"

    with client:
        written = client.put("/api/credentials/OpenAI", json={"api_key": secret})
        status = client.get("/api/credentials/openai")
        providers = client.get("/api/credentials")
        settings = client.get("/api/settings")
        audit = client.get("/api/audit")

        assert written.status_code == 200
        assert written.json() == {"provider": "openai", "configured": True}
        assert status.json() == {"provider": "openai", "configured": True}
        listed = {item["provider"]: item["configured"] for item in providers.json()["providers"]}
        assert listed["openai"] is True
        assert backend.secrets[(SERVICE_NAME, "api-key:openai")] == secret

        response_text = "".join(
            response.text for response in (written, status, providers, settings, audit)
        )
        assert secret not in response_text

    database_files = list(database_path.parent.glob(f"{database_path.name}*"))
    assert database_files
    assert all(secret.encode() not in path.read_bytes() for path in database_files)


def test_delete_is_idempotent_and_only_reports_configuration_state(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_credential_client(tmp_path, backend)
    provider = quote("Google Gemini", safe="")

    with client:
        client.put(f"/api/credentials/{provider}", json={"api_key": "gemini-secret"})
        deleted = client.delete(f"/api/credentials/{provider}")
        deleted_again = client.delete(f"/api/credentials/{provider}")

        assert deleted.json() == {"provider": "google-gemini", "configured": False}
        assert deleted_again.json() == {"provider": "google-gemini", "configured": False}
        assert (SERVICE_NAME, "api-key:google-gemini") not in backend.secrets
        assert "gemini-secret" not in deleted.text + deleted_again.text


def test_provider_is_allowlisted_before_keyring_target_is_built(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_credential_client(tmp_path, backend)

    with client:
        response = client.put(
            f"/api/credentials/{quote('openai:injected-target', safe='')}",
            json={"api_key": "must-not-be-written"},
        )

        assert response.status_code == 422
        assert backend.calls == []
        assert backend.secrets == {}
        assert "must-not-be-written" not in response.text


def test_invalid_payload_and_backend_errors_do_not_echo_secret(tmp_path: Path, caplog) -> None:
    invalid_backend = MemoryKeyring()
    _, invalid_client = make_credential_client(tmp_path / "invalid", invalid_backend)
    nested_secret = "nested-secret-must-not-leak"
    with invalid_client:
        invalid = invalid_client.put(
            "/api/credentials/openai",
            json={"api_key": {"value": nested_secret}},
        )
        assert invalid.status_code == 422
        assert nested_secret not in invalid.text
        assert invalid_backend.secrets == {}

    failing_backend = FailingKeyring()
    _, failing_client = make_credential_client(tmp_path / "failure", failing_backend)
    backend_secret = "backend-error-secret-must-not-leak"
    with failing_client:
        failed = failing_client.put(
            "/api/credentials/deepseek",
            json={"api_key": backend_secret},
        )
        assert failed.status_code == 503
        assert failed.json() == {"detail": "Credential storage is unavailable"}
        assert backend_secret not in failed.text
        assert backend_secret not in caplog.text
