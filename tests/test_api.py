from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "test.sqlite3", serve_static=True))


def test_health_and_overview(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "version": "0.1.0",
            "database": "ok",
            "local_only": True,
        }

        overview = client.get("/api/overview")
        assert overview.status_code == 200
        assert overview.json()["documents"] == 0
        assert overview.json()["research_projects"] == 0
        assert overview.json()["active_agent_tasks"] == 0
        assert overview.json()["learning_mastery"] is None
        assert overview.json()["storage_total_bytes"] > 0
        assert overview.json()["storage_free_bytes"] > 0


def test_new_database_has_no_fictitious_activity(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/library/documents").json() == []
        assert client.get("/api/learning/progress").json() == []
        assert client.get("/api/research/projects").json() == []
        assert client.get("/api/agent/tasks").json() == []


def test_learning_attempt_updates_mastery(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        concept_id = client.app.state.database.execute(
            """
            INSERT INTO learning_concepts(name, mastery, status, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("Continuity", 52, "review", "2026-08-06T00:00:00+00:00"),
        )
        before = client.get("/api/learning/progress").json()[0]
        response = client.post(
            "/api/learning/attempts",
            json={"concept_id": concept_id, "score": 1, "prompt": "Intermediate value theorem exercise"},
        )
        assert response.status_code == 201
        updated = response.json()["concept"]
        assert updated["mastery"] > before["mastery"]


def test_research_project_and_note(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        project = client.post(
            "/api/research/projects",
            json={"name": "测试项目", "question": "测试问题", "research_type": "文献综述"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        note = client.post(
            f"/api/research/projects/{project_id}/notes",
            json={"body": "记录检索条件和筛选决定。"},
        )
        assert note.status_code == 201
        assert note.json()["project_id"] == project_id


def test_reinitialization_preserves_existing_domain_records(tmp_path: Path) -> None:
    database_path = tmp_path / "preserve.sqlite3"
    app = create_app(database_path, serve_static=False)
    with TestClient(app) as client:
        client.app.state.database.execute(
            """
            INSERT INTO learning_concepts(name, mastery, status, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            ("Existing concept", 30, "learning", "2026-08-06T00:00:00+00:00"),
        )
        project = client.post(
            "/api/research/projects",
            json={"name": "Existing project", "question": "Keep it?", "research_type": "Test"},
        )
        task = client.post(
            "/api/agent/tasks",
            json={"project": "Existing project", "title": "Existing task"},
        )
        assert project.status_code == 201
        assert task.status_code == 201

    reopened = create_app(database_path, serve_static=False)
    with TestClient(reopened) as client:
        assert [item["name"] for item in client.get("/api/learning/progress").json()] == ["Existing concept"]
        assert [item["name"] for item in client.get("/api/research/projects").json()] == ["Existing project"]
        assert [item["title"] for item in client.get("/api/agent/tasks").json()] == ["Existing task"]


def test_settings_reject_api_key(tmp_path: Path) -> None:
    secret = "must-not-be-accepted"
    with make_client(tmp_path) as client:
        response = client.put(
            "/api/settings",
            json={
                "provider": "OpenAI",
                "endpoint": "https://api.openai.com/v1",
                "data_path": "C:\\AI-PC",
                "api_key": secret,
            },
        )
        assert response.status_code == 422
        assert secret not in response.text
        settings = client.get("/api/settings").json()
        assert "api_key" not in settings


def test_static_dashboard(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Nexus AI-PC" in response.text
