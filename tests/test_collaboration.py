from __future__ import annotations

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


def test_collaboration_uses_fast_draft_then_reasoning_review(tmp_path: Path) -> None:
    observed: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed.append(body)
        model = body["model"]
        content = "整理草稿" if model == "cheap-model" else "经独立核查的最终答案"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    keyring = MemoryKeyring()
    app = create_app(
        tmp_path / "collaboration.sqlite3",
        serve_static=False,
        credential_backend=keyring,
        model_transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        assert client.put("/api/credentials/OpenAI", json={"api_key": "collaboration-secret"}).status_code == 200
        for role, model in (("fast", "cheap-model"), ("reasoning", "strong-model")):
            assert client.put(
                f"/api/models/roles/{role}",
                json={"provider": "OpenAI", "model": model, "endpoint": "https://api.openai.com/v1"},
            ).status_code == 200

        response = client.post(
            "/api/collaboration/run",
            json={"prompt": "比较两种方法，并核查证据边界", "web_search": "off"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "经独立核查的最终答案"
        assert payload["draft"] == "整理草稿"
        assert payload["distinct_models"] is True
        assert [stage["role"] for stage in payload["stages"]] == ["fast", "reasoning"]
        assert [item["model"] for item in observed] == ["cheap-model", "strong-model"]
        assert "整理草稿" in observed[1]["messages"][-1]["content"]

        calls = client.app.state.database.query_all(
            "SELECT operation, role, session_id FROM model_calls WHERE source = 'dashboard_collaboration' ORDER BY id"
        )
        assert [call["operation"] for call in calls] == ["collaboration_draft", "collaboration_review"]
        assert calls[0]["session_id"] == calls[1]["session_id"] == payload["run_id"]
