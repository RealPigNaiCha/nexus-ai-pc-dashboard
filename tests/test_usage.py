from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.app import create_app


class MemoryKeyring:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop((service, username), None)


def make_client(tmp_path: Path, backend: MemoryKeyring, handler) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "usage.sqlite3",
            serve_static=False,
            credential_backend=backend,
            model_transport=httpx.MockTransport(handler),
        )
    )


def configure_role(client: TestClient) -> None:
    assert (
        client.put(
            "/api/credentials/OpenAI",
            json={"api_key": "usage-secret-must-not-persist"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/models/roles/reasoning",
            json={
                "provider": "OpenAI",
                "model": "gpt-4.1-mini",
                "endpoint": "https://api.openai.com/v1",
            },
        ).status_code
        == 200
    )


def answer_handler() -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 18,
                    "total_tokens": 138,
                },
            },
        )

    return handler


def test_usage_reports_monthly_cost_and_operations(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, answer_handler())
    with client:
        configure_role(client)
        response = client.post(
            "/api/chat/ask",
            json={"question": "你好", "scope": "all"},
        )
        assert response.status_code == 200

        usage = client.get("/api/usage").json()
        assert usage["calls"] == 1
        assert usage["total_tokens"] == 138
        assert usage["spent_usd"] > 0
        assert usage["budget_usd"] == 0
        operations = {item["operation"] for item in usage["by_operation"]}
        assert "chat" in operations
        assert usage["sessions"] == []


def test_usage_budget_blocks_further_generation(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, answer_handler())
    with client:
        configure_role(client)
        assert client.post(
            "/api/chat/ask",
            json={"question": "第一次", "scope": "all"},
        ).status_code == 200

        saved = client.put(
            "/api/usage/budget",
            json={"monthly_budget_usd": 0.000001},
        )
        assert saved.status_code == 200
        assert saved.json()["budget_usd"] == 0.000001

        blocked = client.post(
            "/api/chat/ask",
            json={"question": "第二次", "scope": "all"},
        )
        assert blocked.status_code == 429
        assert blocked.json() == {"detail": "Monthly model budget exceeded"}
        audit = client.app.state.database.query_one(
            "SELECT * FROM audit_events WHERE category = 'usage' ORDER BY id DESC"
        )
        assert audit["action"] == "budget_blocked"

        cleared = client.put(
            "/api/usage/budget",
            json={"monthly_budget_usd": 0},
        )
        assert cleared.status_code == 200
        assert client.post(
            "/api/chat/ask",
            json={"question": "第三次", "scope": "all"},
        ).status_code == 200


def test_usage_sessions_track_nextchat_session(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, answer_handler())
    with client:
        configure_role(client)
        response = client.post(
            "/v1/chat/completions",
            headers={"X-AI-PC-Session": "sess-abc-123"},
            json={
                "model": "reasoning",
                "messages": [{"role": "user", "content": "会话用量"}],
            },
        )
        assert response.status_code == 200

        usage = client.get("/api/usage").json()
        assert len(usage["sessions"]) == 1
        session = usage["sessions"][0]
        assert session["session_id"] == "sess-abc-123"
        assert session["calls"] == 1
        assert session["total_tokens"] == 138

    assert b"usage-secret-must-not-persist" not in (tmp_path / "usage.sqlite3").read_bytes()
