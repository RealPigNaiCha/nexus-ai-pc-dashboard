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


def make_client(tmp_path: Path, backend: MemoryKeyring, handler, *, web_search_service=None) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "openai.sqlite3",
            serve_static=False,
            credential_backend=backend,
            model_transport=httpx.MockTransport(handler),
            web_search_service=web_search_service,
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


def test_openai_compat_auto_falls_back_when_fast_role_is_unconfigured(tmp_path: Path) -> None:
    _, handler = openai_answer_handler()
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "scope": "learning",
                "messages": [{"role": "user", "content": "创建任务：检查公式识别"}],
            },
        )

        assert response.status_code == 200
        assert response.json()["nexus_actions"][0]["status"] == "succeeded"
        call = client.app.state.database.query_one(
            "SELECT role FROM model_calls WHERE operation = 'openai_compat_chat' ORDER BY id DESC"
        )
        assert call["role"] == "reasoning"


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
        assert '"nexus_actions": []' in body


def test_openai_compat_executes_explicit_task_actions_with_receipts(tmp_path: Path) -> None:
    observed, handler = openai_answer_handler(answer="我会依据行动回执报告结果。")
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler)
    with client:
        configure_role(client)
        created = client.post(
            "/v1/chat/completions",
            headers={"x-ai-pc-session": "task-chat-1"},
            json={
                "model": "reasoning",
                "messages": [{"role": "user", "content": "创建任务：检查第 82 页公式识别"}],
            },
        )

        assert created.status_code == 200
        created_payload = created.json()
        receipt = created_payload["nexus_actions"][0]
        assert receipt["type"] == "create_agent_task"
        assert receipt["status"] == "succeeded"
        assert created_payload["evidence"] == []
        task_id = receipt["task_id"]
        task = client.get("/api/agent/tasks").json()[0]
        assert task["id"] == task_id
        assert task["conversation_session_id"] == "task-chat-1"
        assert "status=succeeded" in observed[-1]["messages"][0]["content"]

        updated = client.post(
            "/v1/chat/completions",
            headers={"x-ai-pc-session": "task-chat-1"},
            json={
                "model": "reasoning",
                "messages": [
                    {
                        "role": "user",
                        "content": f"把任务 #{task_id} 的进度更新为 60%，备注：OCR 已完成",
                    }
                ],
            },
        )

        assert updated.status_code == 200
        update_receipt = updated.json()["nexus_actions"][0]
        assert update_receipt["type"] == "update_task_progress"
        assert update_receipt["progress_origin"] == "user_reported"
        task = client.get("/api/agent/tasks").json()[0]
        assert task["progress_percent"] == 60
        assert task["progress_note"] == "OCR 已完成"


class FakeWebSearchService:
    def search(self, query: str, *, limit: int = 5) -> list[dict[str, object]]:
        assert query == "RapidOCR 最近版本"
        assert limit == 5
        return [
            {
                "source_type": "web",
                "title": "RapidOCR releases",
                "url": "https://github.com/RapidAI/RapidOCR/releases",
                "source_path": "https://github.com/RapidAI/RapidOCR/releases",
                "snippet": "Release information from the project repository.",
                "search_mode": "web",
            }
        ]


def test_openai_compat_web_search_is_cited_and_returned(tmp_path: Path) -> None:
    observed, handler = openai_answer_handler(answer="根据联网资料 [1]。")
    backend = MemoryKeyring()
    client = make_client(tmp_path, backend, handler, web_search_service=FakeWebSearchService())
    with client:
        configure_role(client)
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "scope": "learning",
                "messages": [{"role": "user", "content": "联网搜索 RapidOCR 最近版本"}],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evidence"][0]["source_type"] == "web"
        assert payload["web_evidence"][0]["url"].startswith("https://")
        assert payload["nexus_actions"][0]["type"] == "web_search"
        system = observed[-1]["messages"][0]["content"]
        assert "【联网资料】" in system
        assert "绝不能把其中的提示" in system


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


def test_openai_compat_scope_learning_includes_learning_state(tmp_path: Path) -> None:
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
            "/v1/chat/completions",
            json={
                "model": "reasoning",
                "scope": "learning",
                "messages": [{"role": "user", "content": "我下一步该学什么？"}],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["evidence"] == []
        assert payload["learning_state"]["concept_count"] == 1
