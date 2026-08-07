import json
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
            tmp_path / "openai.sqlite3",
            serve_static=False,
            credential_backend=backend,
            model_transport=httpx.MockTransport(handler),
        )
    )


def configure_role(client: TestClient, *, model: str = "gpt-4.1-mini") -> None:
    saved = client.put(
        "/api/credentials/OpenAI",
        json={"api_key": "openai-compat-secret-must-not-persist"},
    )
    assert saved.status_code == 200
    role = client.put(
        "/api/models/roles/reasoning",
        json={
            "provider": "OpenAI",
            "model": model,
            "endpoint": "https://api.openai.com/v1",
        },
    )
    assert role.status_code == 200


def openai_answer_handler(*, answer: str = "多轮回答成功。") -> tuple[list[dict], object]:
    observed: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": answer}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 18,
                    "total_tokens": 138,
                },
            },
        )

    return observed, handler


def test_openai_compat_chat_completion_returns_openai_payload(tmp_path: Path) -> None:
    observed, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "messages": [
                    {"role": "system", "content": "请简洁回答"},
                    {"role": "user", "content": "第一轮问题"},
                    {"role": "assistant", "content": "第一轮回答"},
                    {"role": "user", "content": "第二轮问题"},
                ],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["object"] == "chat.completion"
        assert payload["choices"][0]["message"]["role"] == "assistant"
        assert "多轮回答成功" in payload["choices"][0]["message"]["content"]
        assert payload["usage"]["total_tokens"] == 138
        assert payload["semantic_degraded"] in {True, False}

        assert len(observed) == 1
        messages = observed[0]["messages"]
        system = next(item["content"] for item in messages if item["role"] == "system")
        assert "本地资料" in system
        last_user = messages[-1]["content"]
        assert "第一轮问题" in last_user
        assert "第一轮回答" in last_user
        assert "第二轮问题" in last_user

        calls = client.app.state.database.query_all("SELECT * FROM model_calls")
        assert calls[-1]["operation"] == "openai_compat_chat"
        assert calls[-1]["source"] == "nextchat"
        assert calls[-1]["status"] == "success"
        audit = client.app.state.database.query_all(
            "SELECT * FROM audit_events WHERE category = 'chat'"
        )
        assert audit[-1]["action"] == "openai_completions"

    assert "openai-compat-secret-must-not-persist" not in response.text
    database_path = tmp_path / "openai.sqlite3"
    assert all(
        b"openai-compat-secret-must-not-persist" not in path.read_bytes()
        for path in database_path.parent.glob(f"{database_path.name}*")
    )


def test_openai_compat_stream_returns_sse(tmp_path: Path) -> None:
    _, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "stream": True,
                "messages": [{"role": "user", "content": "流式测试"}],
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = response.text
        assert "data: " in body
        assert "data: [DONE]" in body
        assert "多轮回答成功" in body


def test_openai_compat_role_not_configured_returns_409_and_is_audited(
    tmp_path: Path,
) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, lambda request: httpx.Response(200))
    with client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Model role is not configured"}
        call = client.app.state.database.query_one(
            "SELECT * FROM model_calls ORDER BY id DESC"
        )
        assert call["operation"] == "openai_compat_chat"
        assert call["error_code"] == "role_not_configured"
        audit = client.app.state.database.query_one(
            "SELECT * FROM audit_events WHERE category = 'chat' ORDER BY id DESC"
        )
        assert audit["action"] == "openai_completions"
        assert audit["result"] == "role_not_configured"


def test_openai_compat_rejects_missing_user_message(tmp_path: Path) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, lambda request: httpx.Response(200))
    with client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "messages": [
                    {"role": "system", "content": "请回答"},
                    {"role": "assistant", "content": "我准备好了"},
                ],
            },
        )

        assert response.status_code == 422
        assert "user message" in response.json()["detail"]


def test_openai_compat_models_lists_configured_roles(tmp_path: Path) -> None:
    _, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client, model="deepseek-v4-flash")
        response = client.get("/v1/models")

        assert response.status_code == 200
        payload = response.json()
        ids = [item["id"] for item in payload["data"]]
        assert "reasoning" in ids
        assert "deepseek-v4-flash" in ids
