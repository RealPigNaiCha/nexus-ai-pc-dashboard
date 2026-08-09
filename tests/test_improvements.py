from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import create_app


def test_failure_signals_create_deduplicated_proposal_and_experiment_task(tmp_path) -> None:
    with TestClient(
        create_app(tmp_path / "improvements.sqlite3", serve_static=False),
        base_url="http://127.0.0.1:8765",
    ) as client:
        database = client.app.state.database
        for index in range(4):
            database.record_model_call(
                provider="openai",
                operation="paperqa_ask",
                source="test",
                duration_ms=10,
                status="error" if index < 3 else "success",
                error_code="timeout" if index < 3 else None,
            )

        signals = client.get("/api/improvements/signals")
        assert signals.status_code == 200
        assert signals.json()["signals"][0]["type"] == "model_failure_rate"
        assert signals.json()["signals"][0]["evidence"]["failure_rate"] == 0.75

        rejected = client.post("/api/improvements/scan")
        assert rejected.status_code == 403
        scanned = client.post(
            "/api/improvements/scan",
            headers={"X-AI-PC-Action": "improvement-scan"},
        )
        assert scanned.status_code == 200
        assert scanned.json()["created_count"] == 1
        repeated = client.post(
            "/api/improvements/scan",
            headers={"X-AI-PC-Action": "improvement-scan"},
        )
        assert repeated.json()["created_count"] == 0

        proposal = client.get("/api/improvements/proposals").json()["proposals"][0]
        experiment = client.post(
            f"/api/improvements/proposals/{proposal['id']}/experiment",
            headers={"X-AI-PC-Action": "improvement-experiment"},
        )
        assert experiment.status_code == 201
        body = experiment.json()
        assert body["proposal"]["status"] == "experiment_requested"
        assert body["proposal"]["agent_task_id"] == body["task"]["id"]
        assert body["task"]["status"] == "queued"
        assert body["task"]["run_tests"] == 1

        conflict = client.post(
            f"/api/improvements/proposals/{proposal['id']}/experiment",
            headers={"X-AI-PC-Action": "improvement-experiment"},
        )
        assert conflict.status_code == 409
