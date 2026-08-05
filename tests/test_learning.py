import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.learning import mastery_status, rating_for_attempt, update_mastery


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "learning.sqlite3", serve_static=False))


def test_learning_course_concepts_attempt_and_dashboard(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        empty = client.get("/api/learning/dashboard")
        assert empty.status_code == 200
        assert empty.json()["summary"] == {
            "concept_count": 0,
            "attempt_count": 0,
            "due_count": 0,
            "mastery": None,
            "study_seconds": 0,
        }

        course = client.post(
            "/api/learning/courses",
            json={
                "title": "高等数学",
                "goal": "理解极限、导数和积分，并独立完成综合题。",
                "target_date": "2026-12-31",
            },
        )
        assert course.status_code == 201
        course_id = course.json()["id"]

        limit_concept = client.post(
            "/api/learning/concepts",
            json={"course_id": course_id, "name": "数列极限", "description": "极限定义与运算"},
        )
        assert limit_concept.status_code == 201
        limit_id = limit_concept.json()["id"]

        derivative = client.post(
            "/api/learning/concepts",
            json={
                "course_id": course_id,
                "name": "导数",
                "description": "差商极限与导数定义",
                "prerequisite_ids": [limit_id],
            },
        )
        assert derivative.status_code == 201

        attempt = client.post(
            "/api/learning/attempts",
            json={
                "concept_id": limit_id,
                "score": 0.9,
                "prompt": "写出数列极限的 epsilon-N 定义",
                "answer": "对任意 epsilon 存在 N。",
                "feedback": "量词顺序正确，需补全绝对值条件。",
                "confidence": 0.7,
                "duration_seconds": 180,
                "hints_used": 1,
            },
        )
        assert attempt.status_code == 201
        payload = attempt.json()
        assert payload["rating"] == 3
        assert payload["concept"]["attempt_count"] == 1
        assert payload["concept"]["mastery"] > 0
        assert payload["concept"]["due_at"] == payload["due_at"]
        assert "fsrs_card_json" not in payload["concept"]

        dashboard = client.get("/api/learning/dashboard", params={"course_id": course_id}).json()
        assert dashboard["summary"]["concept_count"] == 2
        assert dashboard["summary"]["attempt_count"] == 1
        assert dashboard["summary"]["study_seconds"] == 180
        assert dashboard["next_concept"]["id"] == derivative.json()["id"]
        assert dashboard["recent_attempts"][0]["confidence"] == 0.7

        attempts = client.get("/api/learning/attempts", params={"concept_id": limit_id}).json()
        assert len(attempts) == 1
        assert attempts[0]["answer"].startswith("对任意")
        assert attempts[0]["rating"] == 3


def test_learning_validation_and_prerequisite_scope(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post("/api/learning/courses", json={"title": "课程一", "goal": "目标一"}).json()
        second = client.post("/api/learning/courses", json={"title": "课程二", "goal": "目标二"}).json()
        concept = client.post(
            "/api/learning/concepts",
            json={"course_id": first["id"], "name": "概念一"},
        ).json()

        cross_course = client.post(
            "/api/learning/concepts",
            json={"course_id": second["id"], "name": "概念二", "prerequisite_ids": [concept["id"]]},
        )
        assert cross_course.status_code == 404

        duplicate = client.post("/api/learning/courses", json={"title": "课程一", "goal": "另一个目标"})
        assert duplicate.status_code == 409


def test_learning_rules_are_bounded_and_hint_sensitive() -> None:
    assert int(rating_for_attempt(0.95, 0)) == 4
    assert int(rating_for_attempt(0.95, 2)) == 3
    assert int(rating_for_attempt(0.2, 0)) == 1
    assert 0 <= update_mastery(10, 1, 0) <= 100
    assert update_mastery(80, 0, 5) < 80
    assert mastery_status(0) == "not_started"
    assert mastery_status(85) == "stable"


def test_migration_adds_learning_evidence_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-learning.sqlite3"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE learning_concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            mastery REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'not_started',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE learning_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id INTEGER NOT NULL REFERENCES learning_concepts(id),
            score REAL NOT NULL,
            prompt TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO learning_concepts(name, mastery, status, updated_at)
        VALUES ('Legacy concept', 40, 'learning', '2026-08-06T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    with TestClient(create_app(database_path, serve_static=False)) as client:
        concept = client.get("/api/learning/progress").json()[0]
        assert concept["attempt_count"] == 0
        response = client.post("/api/learning/attempts", json={"concept_id": concept["id"], "score": 0.8})
        assert response.status_code == 201
        assert response.json()["concept"]["attempt_count"] == 1
