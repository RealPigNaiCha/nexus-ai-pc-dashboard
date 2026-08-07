import json
from pathlib import Path

import httpx
import pytest
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


def make_client(
    tmp_path: Path,
    backend: MemoryKeyring,
    handler,
    *,
    allowed_roots: list[Path] | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "chat.sqlite3",
            serve_static=False,
            credential_backend=backend,
            model_transport=httpx.MockTransport(handler),
            allowed_library_roots=allowed_roots,
        )
    )


def configure_role(client: TestClient, *, model: str = "gpt-4.1-mini") -> None:
    saved = client.put(
        "/api/credentials/OpenAI",
        json={"api_key": "chat-secret-must-not-persist"},
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


def openai_answer_handler(*, answer: str = "数列极限的定义见 [1]。") -> tuple[list[dict], object]:
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


def test_chat_ask_returns_answer_with_citable_library_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.md"
    source.write_text(
        "数列极限的定义是：对于任意正数 ε，存在正整数 N，使得当 n > N 时 |a_n - A| < ε。\n"
        "函数极限是数列极限的推广。",
        encoding="utf-8",
    )
    observed, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler, allowed_roots=[tmp_path])
    with client:
        configure_role(client)
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201

        response = client.post(
            "/api/chat/ask",
            json={"question": "数列极限的 ε-N 定义是什么？", "scope": "all"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert "数列极限的定义见 [1]" in payload["answer"]
        assert len(payload["evidence"]) >= 1
        hit = payload["evidence"][0]
        assert hit["source_path"] == str(source)
        assert "数列极限" in hit["snippet"]
        assert payload["learning_state"]["concept_count"] == 0
        assert payload["semantic_degraded"] in {True, False}

        assert len(observed) == 1
        messages = observed[0]["messages"]
        system = next(item["content"] for item in messages if item["role"] == "system")
        assert "【本地资料】" in system
        assert "[1]《" in system

        calls = client.app.state.database.query_all("SELECT * FROM model_calls")
        assert calls[-1]["operation"] == "chat"
        assert calls[-1]["source"] == "dashboard_chat"
        assert calls[-1]["status"] == "success"
        audit = client.app.state.database.query_all(
            "SELECT * FROM audit_events WHERE category = 'chat'"
        )
        assert audit[-1]["action"] == "ask"

    assert "chat-secret-must-not-persist" not in response.text
    database_path = tmp_path / "chat.sqlite3"
    assert all(
        b"chat-secret-must-not-persist" not in path.read_bytes()
        for path in database_path.parent.glob(f"{database_path.name}*")
    )


def test_chat_ask_learning_scope_includes_learning_state(tmp_path: Path) -> None:
    _, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        course = client.post(
            "/api/learning/courses",
            json={"title": "高等数学", "goal": "掌握极限"},
        ).json()
        client.post(
            "/api/learning/concepts",
            json={"course_id": course["id"], "name": "数列极限", "description": "ε-N 定义"},
        )

        response = client.post(
            "/api/chat/ask",
            json={"question": "我下一步该学什么？", "scope": "learning"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evidence"] == []
        state = payload["learning_state"]
        assert state["concept_count"] == 1
        assert state["due_count"] == 0
        assert state["next_step"]["kind"] == "new"
        assert state["next_step"]["concept_name"] == "数列极限"
        assert state["concepts"][0]["name"] == "数列极限"


def test_chat_ask_without_evidence_still_answers_without_fabrication(
    tmp_path: Path,
) -> None:
    _, handler = openai_answer_handler(
        answer="本地资料里没有找到相关证据，以下是我基于常识的推测。"
    )
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        response = client.post(
            "/api/chat/ask",
            json={"question": "不存在的主题", "scope": "all"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evidence"] == []
        assert "推测" in payload["answer"]


def test_chat_ask_role_not_configured_returns_409_and_is_audited(
    tmp_path: Path,
) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, lambda request: httpx.Response(200))
    with client:
        response = client.post(
            "/api/chat/ask",
            json={"question": "你好", "scope": "all"},
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Model role is not configured"}
        call = client.app.state.database.query_one(
            "SELECT * FROM model_calls ORDER BY id DESC"
        )
        assert call["operation"] == "chat"
        assert call["error_code"] == "role_not_configured"
        audit = client.app.state.database.query_one(
            "SELECT * FROM audit_events WHERE category = 'chat' ORDER BY id DESC"
        )
        assert audit["result"] == "role_not_configured"


@pytest.mark.parametrize("role", ["embedding", "vision", "unknown"])
def test_chat_ask_rejects_unsupported_roles(tmp_path: Path, role: str) -> None:
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, lambda request: httpx.Response(200))
    with client:
        response = client.post(
            "/api/chat/ask",
            json={"question": "你好", "role": role},
        )

    assert response.status_code == 422
    assert "reasoning" in response.json()["detail"]
