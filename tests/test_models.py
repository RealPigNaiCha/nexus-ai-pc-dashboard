import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.credentials import ApiCredentialStore, SERVICE_NAME
from backend.model_gateway import (
    ModelGateway,
    ModelProbeCancelled,
    ModelRequestCancelled,
    build_chat_url,
    build_probe_url,
)


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
        self.secrets.pop((service, username), None)


def make_client(
    tmp_path: Path,
    backend: MemoryKeyring,
    handler,
) -> tuple[Path, TestClient]:
    database_path = tmp_path / "models.sqlite3"
    app = create_app(
        database_path,
        serve_static=False,
        credential_backend=backend,
        model_transport=httpx.MockTransport(handler),
    )
    return database_path, TestClient(app)


@pytest.mark.parametrize(
    ("provider", "endpoint", "header_name", "expected_path"),
    [
        ("OpenAI", "https://api.openai.com/v1", "authorization", "/v1/models"),
        ("Anthropic", "https://api.anthropic.com/v1", "x-api-key", "/v1/models"),
        (
            "Google Gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "x-goog-api-key",
            "/v1beta/models",
        ),
        ("DeepSeek", "https://api.deepseek.com", "authorization", "/models"),
        (
            "阿里云百炼",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "authorization",
            "/compatible-mode/v1/models",
        ),
    ],
)
def test_connection_probe_uses_provider_auth_without_persisting_secret(
    tmp_path: Path,
    provider: str,
    endpoint: str,
    header_name: str,
    expected_path: str,
) -> None:
    backend = MemoryKeyring()
    secret = "model-secret-must-not-persist"
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        assert request.url.path == expected_path
        assert secret in request.headers[header_name]
        return httpx.Response(200, json={"data": []})

    database_path, client = make_client(tmp_path, backend, handler)
    with client:
        saved = client.put(f"/api/credentials/{provider}", json={"api_key": secret})
        response = client.post(
            "/api/models/test",
            json={"provider": provider, "endpoint": endpoint},
        )
        calls = client.app.state.database.query_all("SELECT * FROM model_calls")

        assert saved.status_code == 200
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["latency_ms"] >= 0
        assert len(observed) == 1
        assert calls[0]["status"] == "success"
        assert calls[0]["operation"] == "connection_test"
        assert calls[0]["source"] == "dashboard_settings"
        assert secret not in response.text + str(calls)

    assert all(
        secret.encode() not in path.read_bytes()
        for path in database_path.parent.glob(f"{database_path.name}*")
    )


def test_missing_credential_is_reported_and_audited(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    _, client = make_client(tmp_path, backend, handler)
    with client:
        response = client.post(
            "/api/models/test",
            json={"provider": "OpenAI", "endpoint": "https://api.openai.com/v1"},
        )
        call = client.app.state.database.query_one("SELECT * FROM model_calls")

    assert response.status_code == 409
    assert response.json() == {"detail": "Model credential is not configured"}
    assert requests == []
    assert call is not None
    assert call["error_code"] == "credential_missing"


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "error_code", "detail"),
    [
        (401, 401, "authentication_failed", "Model service rejected the credential"),
        (403, 401, "authentication_failed", "Model service rejected the credential"),
        (429, 429, "rate_limited", "Model service quota or rate limit was reached"),
        (500, 502, "upstream_error", "Model service rejected the connection test"),
    ],
)
def test_upstream_failures_are_sanitized_and_audited(
    tmp_path: Path,
    upstream_status: int,
    expected_status: int,
    error_code: str,
    detail: str,
) -> None:
    backend = MemoryKeyring()
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = "upstream-error-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, text="upstream body must not be returned")

    _, client = make_client(tmp_path, backend, handler)
    with client:
        response = client.post(
            "/api/models/test",
            json={"provider": "OpenAI", "endpoint": "https://api.openai.com/v1"},
        )
        call = client.app.state.database.query_one("SELECT * FROM model_calls")

    assert response.status_code == expected_status
    assert response.json() == {"detail": detail}
    assert "upstream body" not in response.text
    assert call is not None
    assert call["status"] == "error"
    assert call["error_code"] == error_code


def test_timeout_is_sanitized_and_audited(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = "timeout-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request included timeout-secret", request=request)

    _, client = make_client(tmp_path, backend, handler)
    with client:
        response = client.post(
            "/api/models/test",
            json={"provider": "OpenAI", "endpoint": "https://api.openai.com/v1"},
        )
        call = client.app.state.database.query_one("SELECT * FROM model_calls")

    assert response.status_code == 504
    assert response.json() == {"detail": "Model service timed out"}
    assert "timeout-secret" not in response.text
    assert call is not None
    assert call["error_code"] == "timeout"


@pytest.mark.parametrize(
    ("provider", "endpoint"),
    [
        ("OpenAI", "https://example.com/v1"),
        ("OpenAI", "http://api.openai.com/v1"),
        ("兼容 OpenAI 的服务", "http://example.com/v1"),
    ],
)
def test_unsafe_endpoint_is_rejected_before_credential_read(
    tmp_path: Path,
    provider: str,
    endpoint: str,
) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        response = client.post(
            "/api/models/test",
            json={"provider": provider, "endpoint": endpoint},
        )

    assert response.status_code == 422
    assert backend.calls == []


def test_compatible_provider_allows_loopback_http() -> None:
    assert (
        build_probe_url("openai-compatible", "http://127.0.0.1:11434/v1")
        == "http://127.0.0.1:11434/v1/models"
    )


def test_gateway_preserves_cancellation() -> None:
    backend = MemoryKeyring()
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = "cancel-secret"

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async def run() -> None:
        gateway = ModelGateway(ApiCredentialStore(backend), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ModelProbeCancelled):
                await gateway.probe("openai", "https://api.openai.com/v1")
        finally:
            await gateway.close()

    asyncio.run(run())


def test_model_roles_have_local_safe_defaults(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        response = client.get("/api/models/roles")

    assert response.status_code == 200
    roles = {item["role"]: item for item in response.json()["roles"]}
    assert set(roles) == {"reasoning", "fast", "vision", "embedding"}
    for role in ("reasoning", "fast", "vision"):
        assert roles[role]["provider"] == "openai"
        assert roles[role]["model"] == ""
        assert roles[role]["ready"] is False
        assert roles[role]["credential_configured"] is False
    assert roles["embedding"]["provider"] == "local"
    assert roles["embedding"]["ready"] is True
    assert roles["embedding"]["local_only"] is True


def test_model_role_update_is_validated_and_persisted(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        invalid = client.put(
            "/api/models/roles/not-a-role",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        embedding = client.put(
            "/api/models/roles/embedding",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        bad_endpoint = client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://example.com/v1"},
        )
        updated = client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        roles = {item["role"]: item for item in client.get("/api/models/roles").json()["roles"]}
        settings = client.app.state.database.get_model_roles()

    assert invalid.status_code == 422
    assert embedding.status_code == 422
    assert bad_endpoint.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["model"] == "gpt-test"
    assert roles["reasoning"]["model"] == "gpt-test"
    assert roles["reasoning"]["provider"] == "OpenAI"
    reasoning_setting = next(item for item in settings if item["role"] == "reasoning")
    assert reasoning_setting["model"] == "gpt-test"


def test_model_role_ready_reflects_model_and_credential(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        client.put("/api/credentials/OpenAI", json={"api_key": "ready-secret"})
        client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        roles = {item["role"]: item for item in client.get("/api/models/roles").json()["roles"]}

    assert roles["reasoning"]["ready"] is True
    assert roles["reasoning"]["credential_configured"] is True
    assert roles["fast"]["ready"] is False


def test_embedding_role_cannot_generate_or_use_external_route(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        configure = client.put(
            "/api/models/roles/embedding",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        generate = client.post(
            "/api/models/generate",
            json={"role": "embedding", "prompt": "Explain limits"},
        )
        roles = {item["role"]: item for item in client.get("/api/models/roles").json()["roles"]}

    assert configure.status_code == 422
    assert generate.status_code == 422
    assert roles["embedding"]["local_only"] is True
    assert roles["embedding"]["provider"] == "local"


def test_generation_requires_configured_role_and_credential(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    _, client = make_client(tmp_path, backend, lambda _request: httpx.Response(200))

    with client:
        missing_role = client.post(
            "/api/models/generate",
            json={"role": "reasoning", "prompt": "Explain limits"},
        )
        missing_role_call = client.app.state.database.query_one(
            "SELECT * FROM model_calls WHERE operation = 'generate'"
        )

        client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        missing_credential = client.post(
            "/api/models/generate",
            json={"role": "reasoning", "prompt": "Explain limits"},
        )
        missing_credential_call = client.app.state.database.query_one(
            "SELECT * FROM model_calls WHERE operation = 'generate' ORDER BY id DESC"
        )

    assert missing_role.status_code == 409
    assert missing_role.json() == {"detail": "Model role is not configured"}
    assert missing_role_call["error_code"] == "role_not_configured"
    assert missing_credential.status_code == 409
    assert missing_credential.json() == {"detail": "Model credential is not configured"}
    assert missing_credential_call["error_code"] == "credential_missing"


def test_generation_openai_compatible_audits_without_persisting_secret(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    secret = "generation-secret-must-not-persist"
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {secret}"
        assert body["model"] == "gpt-test"
        assert body["messages"][0] == {"role": "system", "content": "Be concise and cite evidence"}
        assert body["messages"][1] == {"role": "user", "content": "Explain limits"}
        assert body["max_tokens"] == 128
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "A concise explanation."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            },
        )

    database_path, client = make_client(tmp_path, backend, handler)
    with client:
        client.put("/api/credentials/OpenAI", json={"api_key": secret})
        client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        response = client.post(
            "/api/models/generate",
            json={
                "role": "reasoning",
                "prompt": "Explain limits",
                "system": "Be concise and cite evidence",
                "max_tokens": 128,
                "temperature": 0.1,
            },
        )
        call = client.app.state.database.query_one(
            "SELECT * FROM model_calls WHERE operation = 'generate'"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["content"] == "A concise explanation."
    assert body["model"] == "gpt-test"
    assert body["usage"] == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    assert call["role"] == "reasoning"
    assert call["prompt_tokens"] == 12
    assert call["completion_tokens"] == 8
    assert call["total_tokens"] == 20
    assert len(observed) == 1
    assert secret not in response.text + str(call)
    assert all(
        secret.encode() not in path.read_bytes()
        for path in database_path.parent.glob(f"{database_path.name}*")
    )


def test_generation_anthropic_request_format(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    secret = "anthropic-generation-secret"
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == secret
        assert body["model"] == "claude-test"
        assert body["system"] == "Be concise"
        assert body["messages"] == [{"role": "user", "content": "Explain limits"}]
        assert body["max_tokens"] == 256
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "First "},
                    {"type": "text", "text": "part."},
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )

    _, client = make_client(tmp_path, backend, handler)
    with client:
        client.put("/api/credentials/Anthropic", json={"api_key": secret})
        client.put(
            "/api/models/roles/fast",
            json={
                "provider": "Anthropic",
                "model": "claude-test",
                "endpoint": "https://api.anthropic.com/v1",
            },
        )
        response = client.post(
            "/api/models/generate",
            json={
                "role": "fast",
                "prompt": "Explain limits",
                "system": "Be concise",
                "max_tokens": 256,
            },
        )

    assert response.status_code == 200
    assert response.json()["content"] == "First part."
    assert response.json()["usage"]["prompt_tokens"] == 5
    assert response.json()["usage"]["total_tokens"] == 8
    assert len(observed) == 1


def test_generation_gemini_request_format(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    secret = "gemini-generation-secret"
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1beta/models/gemini-test:generateContent"
        assert request.headers["x-goog-api-key"] == secret
        assert body["contents"][0]["parts"][0]["text"] == "Explain limits"
        assert body["systemInstruction"]["parts"][0]["text"] == "Be concise"
        assert body["generationConfig"]["maxOutputTokens"] == 128
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2, "totalTokenCount": 6},
            },
        )

    _, client = make_client(tmp_path, backend, handler)
    with client:
        client.put("/api/credentials/Google Gemini", json={"api_key": secret})
        client.put(
            "/api/models/roles/vision",
            json={
                "provider": "Google Gemini",
                "model": "gemini-test",
                "endpoint": "https://generativelanguage.googleapis.com/v1beta",
            },
        )
        response = client.post(
            "/api/models/generate",
            json={
                "role": "vision",
                "prompt": "Explain limits",
                "system": "Be concise",
                "max_tokens": 128,
            },
        )

    assert response.status_code == 200
    assert response.json()["content"] == "Gemini answer"
    assert response.json()["usage"]["total_tokens"] == 6
    assert len(observed) == 1


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "error_code", "detail"),
    [
        (401, 401, "authentication_failed", "Model service rejected the credential"),
        (403, 401, "authentication_failed", "Model service rejected the credential"),
        (429, 429, "rate_limited", "Model service quota or rate limit was reached"),
        (500, 502, "upstream_error", "Model service rejected the generation request"),
    ],
)
def test_generation_failures_are_sanitized_and_audited(
    tmp_path: Path,
    upstream_status: int,
    expected_status: int,
    error_code: str,
    detail: str,
) -> None:
    backend = MemoryKeyring()
    secret = "generation-error-secret"
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = secret

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, text="upstream generation body must not be returned")

    _, client = make_client(tmp_path, backend, handler)
    with client:
        client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        response = client.post(
            "/api/models/generate",
            json={"role": "reasoning", "prompt": "Explain limits"},
        )
        call = client.app.state.database.query_one(
            "SELECT * FROM model_calls WHERE operation = 'generate'"
        )

    assert response.status_code == expected_status
    assert response.json() == {"detail": detail}
    assert "upstream generation body" not in response.text
    assert secret not in response.text
    assert call is not None
    assert call["status"] == "error"
    assert call["error_code"] == error_code
    assert call["role"] == "reasoning"


def test_generation_timeout_is_sanitized_and_audited(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    secret = "generation-timeout-secret"
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = secret

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request included generation-timeout-secret", request=request)

    _, client = make_client(tmp_path, backend, handler)
    with client:
        client.put(
            "/api/models/roles/reasoning",
            json={"provider": "OpenAI", "model": "gpt-test", "endpoint": "https://api.openai.com/v1"},
        )
        response = client.post(
            "/api/models/generate",
            json={"role": "reasoning", "prompt": "Explain limits"},
        )
        call = client.app.state.database.query_one(
            "SELECT * FROM model_calls WHERE operation = 'generate'"
        )

    assert response.status_code == 504
    assert response.json() == {"detail": "Model service timed out"}
    assert "generation-timeout-secret" not in response.text
    assert call is not None
    assert call["error_code"] == "timeout"


def test_gateway_generation_preserves_cancellation() -> None:
    backend = MemoryKeyring()
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = "cancel-secret"

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async def run() -> None:
        gateway = ModelGateway(ApiCredentialStore(backend), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ModelRequestCancelled):
                await gateway.generate(
                    provider="openai",
                    endpoint="https://api.openai.com/v1",
                    model="gpt-test",
                    prompt="Explain limits",
                )
        finally:
            await gateway.close()

    asyncio.run(run())


def test_build_chat_url_provider_shapes() -> None:
    assert (
        build_chat_url("openai", "https://api.openai.com/v1")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        build_chat_url("anthropic", "https://api.anthropic.com/v1")
        == "https://api.anthropic.com/v1/messages"
    )
    assert (
        build_chat_url("google-gemini", "https://generativelanguage.googleapis.com/v1beta", "gemini-test")
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    )
    assert (
        build_chat_url("deepseek", "https://api.deepseek.com")
        == "https://api.deepseek.com/chat/completions"
    )
