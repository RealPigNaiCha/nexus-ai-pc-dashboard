from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.routing import (
    ROUTING_TASKS,
    complexity_score,
    resolve_role,
)


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
    backend: MemoryKeyring | None = None,
    handler=None,
) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "routing.sqlite3",
            serve_static=False,
            credential_backend=backend,
            model_transport=httpx.MockTransport(handler) if handler else None,
        )
    )


def openai_handler() -> tuple[list[dict], object]:
    observed: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    return observed, handler


def configure_roles(client: TestClient) -> None:
    client.put("/api/credentials/OpenAI", json={"api_key": "routing-secret"})
    for role, model in (("reasoning", "gpt-4.1"), ("fast", "gpt-4.1-mini")):
        saved = client.put(
            f"/api/models/roles/{role}",
            json={
                "provider": "OpenAI",
                "model": model,
                "endpoint": "https://api.openai.com/v1",
            },
        )
        assert saved.status_code == 200


def test_routing_rules_defaults_update_and_audit(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        listed = client.get("/api/routing/rules")
        assert listed.status_code == 200
        rules = listed.json()["rules"]
        assert {rule["task"] for rule in rules} == set(ROUTING_TASKS)
        assert all(rule["mode"] == "auto" for rule in rules)
        assert all(rule["prefer_low_cost"] is False for rule in rules)

        updated = client.put(
            "/api/routing/rules/chat",
            json={"mode": "fast", "prefer_low_cost": True},
        )
        assert updated.status_code == 200
        assert updated.json()["mode"] == "fast"
        assert updated.json()["prefer_low_cost"] is True

        after = client.get("/api/routing/rules").json()["rules"]
        chat_rule = next(rule for rule in after if rule["task"] == "chat")
        assert chat_rule["mode"] == "fast"
        assert chat_rule["prefer_low_cost"] is True

        audit = client.app.state.database.query_all(
            "SELECT * FROM audit_events WHERE category = 'routing' AND action = 'update_rule'"
        )
        assert len(audit) == 1
        assert audit[0]["target"] == "chat"

        missing = client.put(
            "/api/routing/rules/nope",
            json={"mode": "fast", "prefer_low_cost": False},
        )
        assert missing.status_code == 404
        invalid = client.put(
            "/api/routing/rules/chat",
            json={"mode": "ultra", "prefer_low_cost": False},
        )
        assert invalid.status_code == 422


def test_resolve_role_explicit_override_and_complexity_heuristic(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        database = client.app.state.database
        assert resolve_role(database, "chat", "reasoning") == "reasoning"
        assert resolve_role(database, "chat", "fast") == "fast"
        assert resolve_role(database, "chat", "auto", text="1+1 等于多少？") == "fast"
        assert (
            resolve_role(
                database,
                "chat",
                "auto",
                text="为什么需要比较这两种方法的差异，并评估对研究结论的影响？",
            )
            == "reasoning"
        )
        assert complexity_score("简短问题") == 0
        assert complexity_score("分析并证明这个结论，然后评估反例的影响") >= 2


def test_resolve_role_prefers_fast_when_budget_nearly_exhausted(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        database = client.app.state.database
        budget = client.put("/api/usage/budget", json={"monthly_budget_usd": 1.0})
        assert budget.status_code == 200
        database.record_model_call(
            provider="openai",
            operation="routing_test",
            source="test",
            duration_ms=1,
            status="success",
            model="gpt-4o",
            prompt_tokens=200_000,
            completion_tokens=50_000,
        )
        client.put(
            "/api/routing/rules/chat",
            json={"mode": "auto", "prefer_low_cost": True},
        )
        role = resolve_role(
            database,
            "chat",
            "auto",
            text="为什么需要比较这两种方法的差异，并评估对研究结论的影响？",
        )
        assert role == "fast"


def test_chat_auto_role_records_resolved_role(tmp_path: Path) -> None:
    observed, handler = openai_handler()
    backend = MemoryKeyring()
    with make_client(tmp_path, backend, handler) as client:
        configure_roles(client)
        complex_question = "请分析并比较这两种复习方法的差异，评估它们对长期记忆的影响？"
        simple_question = "什么是极限？"

        complex_call = client.post(
            "/api/chat/ask",
            json={"question": complex_question, "role": "auto"},
        )
        assert complex_call.status_code == 200
        simple_call = client.post(
            "/api/chat/ask",
            json={"question": simple_question, "role": "auto"},
        )
        assert simple_call.status_code == 200

        calls = client.app.state.database.query_all(
            "SELECT operation, role, model FROM model_calls WHERE operation = 'chat' ORDER BY id"
        )
        assert [call["role"] for call in calls] == ["reasoning", "fast"]
        assert len(observed) == 2
