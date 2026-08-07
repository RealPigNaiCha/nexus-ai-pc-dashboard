import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.credentials import ApiCredentialStore
from backend.database import Database
from backend.paperqa import (
    PaperQAError,
    PaperQAService,
    _router_config,
)


class FakePaperQAService:
    def __init__(
        self,
        *,
        status_payload: dict | None = None,
        ask_result: dict | None = None,
        ask_error: PaperQAError | None = None,
    ) -> None:
        self.status_payload = status_payload or {
            "ready": True,
            "llm": {
                "role": "reasoning",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "endpoint": "https://api.openai.com/v1",
                "ready": True,
                "error": None,
            },
            "index": {
                "built": True,
                "document_count": 2,
                "built_at": "2026-08-06T00:00:00+00:00",
                "files": [],
            },
            "embedding": {"provider": "local", "model": "BAAI/bge-small-zh-v1.5", "ready": True},
            "index_path": "C:\\AI-PC\\data\\index\\paperqa",
        }
        self.ask_result = ask_result or {
            "question": "Test question",
            "answer": "A grounded answer.",
            "formatted_answer": "Question: Test question\n\nA grounded answer.",
            "context": "Evidence context",
            "references": "",
            "sources": [
                {
                    "citation": "sample.txt",
                    "docname": "sample",
                    "text": "Relevant evidence",
                    "score": 5,
                }
            ],
            "model": "gpt-4o-mini",
            "latency_ms": 123,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        self.ask_error = ask_error
        self.build_calls: list[list[Path]] = []
        self.ask_calls: list[dict] = []

    def status(self) -> dict:
        return self.status_payload

    async def build_index(self, paths) -> dict:
        self.build_calls.append(list(paths))
        return {
            "status": "ok",
            "document_count": len(paths),
            "files": [{"path": str(path), "docname": path.stem} for path in paths],
            "index_path": "C:\\AI-PC\\data\\index\\paperqa",
            "latency_ms": 42,
        }

    async def ask(self, question, role="reasoning", max_tokens=1024, temperature=0.2) -> dict:
        self.ask_calls.append(
            {
                "question": question,
                "role": role,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self.ask_error is not None:
            raise self.ask_error
        return self.ask_result


def make_client(
    tmp_path: Path,
    service: FakePaperQAService | None = None,
) -> tuple[Path, TestClient]:
    library_root = tmp_path / "library"
    library_root.mkdir()
    app = create_app(
        tmp_path / "paperqa.sqlite3",
        serve_static=False,
        allowed_library_roots=[library_root],
        paperqa_service=service or FakePaperQAService(),
    )
    return library_root, TestClient(app)


def test_paperqa_status_endpoint(tmp_path: Path) -> None:
    service = FakePaperQAService()
    _, client = make_client(tmp_path, service)
    with client:
        response = client.get("/api/paperqa/status")
        assert response.status_code == 200
        assert response.json()["ready"] is True
        assert response.json()["index"]["document_count"] == 2


def test_paperqa_index_whitelist_and_audit(tmp_path: Path) -> None:
    library_root, client = make_client(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("forbidden", encoding="utf-8")
    valid = library_root / "paper.txt"
    valid.write_text("A useful paper body.", encoding="utf-8")

    with client:
        forbidden = client.post("/api/paperqa/index", json={"path": str(outside)})
        assert forbidden.status_code == 403

        created = client.post("/api/paperqa/index", json={"path": str(valid)})
        assert created.status_code == 201
        assert created.json()["document_count"] == 1

        service = client.app.state.paperqa_service
        assert service.build_calls == [[valid.resolve()]]
        audit = client.app.state.database.query_all(
            "SELECT category, action, result FROM audit_events ORDER BY id"
        )
        assert ("paperqa", "index", "path_forbidden") in {
            (row["category"], row["action"], row["result"]) for row in audit
        }
        assert ("paperqa", "index", "success") in {
            (row["category"], row["action"], row["result"]) for row in audit
        }


def test_paperqa_ask_success_records_model_call(tmp_path: Path) -> None:
    _, client = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/paperqa/ask",
            json={"question": "Test question", "role": "reasoning"},
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "A grounded answer."
        service = client.app.state.paperqa_service
        assert service.ask_calls == [
            {
                "question": "Test question",
                "role": "reasoning",
                "max_tokens": 1024,
                "temperature": 0.2,
            }
        ]
        calls = client.app.state.database.query_all(
            "SELECT * FROM model_calls ORDER BY id"
        )
        assert len(calls) == 1
        assert calls[0]["operation"] == "paperqa_ask"
        assert calls[0]["source"] == "dashboard_paperqa"
        assert calls[0]["status"] == "success"
        assert calls[0]["role"] == "reasoning"
        assert calls[0]["total_tokens"] == 15


def test_paperqa_ask_maps_role_error_and_audits(tmp_path: Path) -> None:
    service = FakePaperQAService(
        ask_error=PaperQAError(
            "role_not_configured", "该模型角色尚未配置", 409
        )
    )
    _, client = make_client(tmp_path, service)
    with client:
        response = client.post(
            "/api/paperqa/ask",
            json={"question": "Any question", "role": "fast"},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "该模型角色尚未配置"
        calls = client.app.state.database.query_all(
            "SELECT * FROM model_calls ORDER BY id"
        )
        assert calls[0]["status"] == "error"
        assert calls[0]["error_code"] == "role_not_configured"
        assert calls[0]["role"] == "fast"
        audit = client.app.state.database.query_all(
            "SELECT category, action, result FROM audit_events ORDER BY id"
        )
        assert ("paperqa", "ask", "role_not_configured") in {
            (row["category"], row["action"], row["result"]) for row in audit
        }


def test_paperqa_ask_rejects_extra_fields(tmp_path: Path) -> None:
    _, client = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/paperqa/ask",
            json={"question": "Test", "unexpected": "value"},
        )
        assert response.status_code == 422


class MemoryKeyring:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop((service, username), None)


def test_service_status_ready_false_without_role(tmp_path: Path) -> None:
    database = Database(tmp_path / "service.sqlite3")
    database.initialize()
    service = PaperQAService(
        database=database,
        credential_store=ApiCredentialStore(MemoryKeyring()),
        index_root=tmp_path / "index",
        allowed_roots=[tmp_path],
    )
    status = service.status()
    assert status["ready"] is False
    assert status["index"]["built"] is False
    assert status["llm"]["error"] == "role_not_configured"


def test_service_rejects_paths_outside_roots(tmp_path: Path) -> None:
    database = Database(tmp_path / "service.sqlite3")
    database.initialize()
    allowed = tmp_path / "library"
    allowed.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("forbidden", encoding="utf-8")
    service = PaperQAService(
        database=database,
        credential_store=ApiCredentialStore(MemoryKeyring()),
        index_root=tmp_path / "index",
        allowed_roots=[allowed],
    )
    with pytest.raises(PaperQAError) as excinfo:
        asyncio.run(service.build_index([outside]))
    assert excinfo.value.code == "path_forbidden"
    assert excinfo.value.status_code == 403


def test_service_ask_requires_index_before_llm(tmp_path: Path) -> None:
    database = Database(tmp_path / "service.sqlite3")
    database.initialize()
    keyring = MemoryKeyring()
    keyring.set_password("Nexus AI-PC API Credentials v1", "api-key:openai", "secret")
    database.save_model_role(
        role="reasoning",
        provider="openai",
        model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1",
    )
    service = PaperQAService(
        database=database,
        credential_store=ApiCredentialStore(keyring),
        index_root=tmp_path / "index",
        allowed_roots=[tmp_path / "library"],
    )
    with pytest.raises(PaperQAError) as excinfo:
        asyncio.run(service.ask("What is this paper about?"))
    assert excinfo.value.code == "index_not_built"
    assert excinfo.value.status_code == 409


def test_router_config_builds_litellm_params() -> None:
    config = _router_config(
        provider="openai-compatible",
        model="local-model",
        endpoint="http://127.0.0.1:8000/v1",
        api_key="temporary-secret",
        temperature=0.2,
        max_tokens=1024,
        timeout_seconds=30,
    )
    params = config["model_list"][0]["litellm_params"]
    assert params["model"] == "openai/local-model"
    assert params["api_base"] == "http://127.0.0.1:8000/v1"
    assert params["api_key"] == "temporary-secret"
