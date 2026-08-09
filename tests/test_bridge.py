from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.bridge import BRIDGE_SCHEMA, BRIDGE_VERSION
from backend.cli import NexusClient


def create_task(client: TestClient) -> dict:
    response = client.post(
        "/api/agent/tasks",
        json={"project": "Bridge", "title": "Use local evidence and report the tested result"},
    )
    assert response.status_code == 201
    return response.json()


def result_payload(envelope_hash: str) -> dict[str, object]:
    return {
        "envelope_sha256": envelope_hash,
        "status": "completed",
        "summary": "Implemented the bridge and verified it.",
        "citations": [
            {"kind": "library", "resource_id": "document:7", "title": "Design", "page": 3}
        ],
        "artifacts": [{"path": r"C:\AI-PC\workspaces\ai-pc-dashboard\backend\bridge.py"}],
        "tests": [{"command": "uv run pytest tests/test_bridge.py", "status": "passed"}],
        "questions": [],
        "executor": "codex-cli",
        "source_commit": "abcdef1",
    }


def test_versioned_envelope_and_result_round_trip(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "bridge.sqlite3", serve_static=False), base_url="http://127.0.0.1:8765") as client:
        task = create_task(client)
        envelope = client.get(f"/api/bridge/tasks/{task['id']}/envelope").json()
        assert envelope["schema"] == BRIDGE_SCHEMA
        assert envelope["version"] == BRIDGE_VERSION
        assert len(envelope["content_sha256"]) == 64
        assert envelope["context"]["search_query"] == task["title"]

        rejected = client.post(
            f"/api/bridge/tasks/{task['id']}/results",
            json=result_payload(envelope["content_sha256"]),
        )
        assert rejected.status_code == 403

        reported = client.post(
            f"/api/bridge/tasks/{task['id']}/results",
            headers={"X-AI-PC-Action": "bridge-result"},
            json=result_payload(envelope["content_sha256"]),
        )
        assert reported.status_code == 201
        body = reported.json()
        assert body["result"]["status"] == "completed"
        assert body["result"]["citations"][0]["resource_id"] == "document:7"
        assert body["next_envelope"]["content_sha256"] != envelope["content_sha256"]
        saved = client.get("/api/agent/tasks").json()[0]
        assert saved["status"] == "completed"
        assert saved["progress_percent"] == 100

        stale = client.post(
            f"/api/bridge/tasks/{task['id']}/results",
            headers={"X-AI-PC-Action": "bridge-result"},
            json=result_payload(envelope["content_sha256"]),
        )
        assert stale.status_code == 409


def test_cli_client_fetches_latest_hash_before_reporting() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"content_sha256": "a" * 64})
        return httpx.Response(201, json={"result": {"status": "partial"}})

    client = NexusClient(transport=httpx.MockTransport(handler))
    try:
        result = client.report_task(9, {"status": "partial", "summary": "Still working"})
    finally:
        client.close()

    assert result["result"]["status"] == "partial"
    assert [request.method for request in observed] == ["GET", "POST"]
    assert observed[1].headers["x-ai-pc-action"] == "bridge-result"
    assert b'"envelope_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"' in observed[1].content
