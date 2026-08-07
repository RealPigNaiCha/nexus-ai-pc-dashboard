from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "coach.sqlite3", serve_static=False))


def test_coach_report_explains_weak_foundations_and_next_step(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        course = client.post(
            "/api/learning/courses",
            json={"title": "高等数学", "goal": "掌握极限与导数"},
        )
        course_id = course.json()["id"]
        prerequisite = client.post(
            "/api/learning/concepts",
            json={"course_id": course_id, "name": "数列极限"},
        ).json()
        concept = client.post(
            "/api/learning/concepts",
            json={
                "course_id": course_id,
                "name": "函数极限",
                "prerequisite_ids": [prerequisite["id"]],
            },
        ).json()
        client.post(
            "/api/learning/attempts",
            json={"concept_id": prerequisite["id"], "score": 0.3, "prompt": "诊断题"},
        )
        client.post(
            "/api/learning/attempts",
            json={"concept_id": concept["id"], "score": 0.9, "prompt": "练习题"},
        )

        report = client.get("/api/coach/report").json()

    assert report["summary"]["concept_count"] == 2
    assert report["summary"]["attempt_count"] == 2
    assert report["summary"]["weak_foundation_count"] == 1
    assert report["weak_foundations"][0]["concept_name"] == "函数极限"
    assert report["weak_foundations"][0]["missing_prerequisites"][0]["name"] == "数列极限"
    assert report["weak_foundations"][0]["missing_prerequisites"][0]["mastery"] < 60
    by_name = {item["name"]: item for item in report["concepts"]}
    assert by_name["数列极限"]["trend"] == "started"
    assert by_name["函数极限"]["trend"] == "started"
    assert report["next_step"]["kind"] in {"review", "new", "practice"}


def test_coach_report_empty_database_has_no_fabricated_state(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        report = client.get("/api/coach/report").json()

    assert report["summary"]["concept_count"] == 0
    assert report["summary"]["mastery"] is None
    assert report["weak_foundations"] == []
    assert report["next_step"] == {"kind": "none", "concept": None}


def test_coach_context_returns_citable_evidence(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text(
        "数列极限的定义是：对于任意正数 ε，存在正整数 N，使得当 n > N 时 |a_n - A| < ε。\n"
        "函数极限是数列极限的推广。",
        encoding="utf-8",
    )
    app = create_app(
        tmp_path / "coach-context.sqlite3",
        serve_static=False,
        allowed_library_roots=[tmp_path],
    )
    with TestClient(app) as client:
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201
        context = client.get(
            "/api/coach/context",
            params={"question": "数列极限", "limit": 5},
        ).json()

    assert context["question"] == "数列极限"
    assert len(context["evidence"]) >= 1
    hit = context["evidence"][0]
    assert hit["source_path"] == str(source)
    assert "数列极限" in hit["snippet"]
    assert "page" in hit or "paragraph" in hit
    assert context["learning_state"]["concept_count"] == 0


def test_coach_plan_schedules_reviews_new_concepts_and_foundations(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        course_id = client.post(
            "/api/learning/courses",
            json={"title": "高等数学", "goal": "掌握极限与导数"},
        ).json()["id"]
        limit_concept = client.post(
            "/api/learning/concepts",
            json={"course_id": course_id, "name": "数列极限"},
        ).json()
        function_limit = client.post(
            "/api/learning/concepts",
            json={
                "course_id": course_id,
                "name": "函数极限",
                "prerequisite_ids": [limit_concept["id"]],
            },
        ).json()
        derivative_base = client.post(
            "/api/learning/concepts",
            json={"course_id": course_id, "name": "导数基础"},
        ).json()
        continuity = client.post(
            "/api/learning/concepts",
            json={
                "course_id": course_id,
                "name": "连续",
                "prerequisite_ids": [derivative_base["id"]],
            },
        ).json()

        client.post(
            "/api/learning/attempts",
            json={"concept_id": limit_concept["id"], "score": 0.3, "prompt": "诊断"},
        )
        client.post(
            "/api/learning/attempts",
            json={"concept_id": derivative_base["id"], "score": 0.4, "prompt": "诊断"},
        )
        due_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
        client.app.state.database.execute(
            "UPDATE learning_concepts SET due_at = ? WHERE id = ?",
            (due_at, limit_concept["id"]),
        )
        overdue = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        client.app.state.database.execute(
            "UPDATE learning_concepts SET due_at = ? WHERE id = ?",
            (overdue, derivative_base["id"]),
        )

        plan = client.get("/api/coach/plan", params={"days": 7}).json()

    assert len(plan["days"]) == 7
    assert plan["start_date"] == datetime.now().date().isoformat()
    first_day = plan["days"][0]
    assert [item["name"] for item in first_day["reviews"]] == ["导数基础"]
    assert {item["name"] for item in first_day["new_concepts"]} == {"函数极限", "连续"}
    assert {item["name"] for item in first_day["foundation_concepts"]} == {"数列极限"}
    assert [item["name"] for item in plan["days"][1]["reviews"]] == ["数列极限"]
    assert plan["summary"]["planned_reviews"] == 2
    assert plan["summary"]["planned_new_concepts"] == 2
    assert plan["summary"]["planned_foundations"] == 1
    assert plan["summary"]["due_count"] == 1
    assert plan["summary"]["weak_foundation_count"] == 2
    assert plan["summary"]["estimated_minutes"] > 0
    assert function_limit["id"] in {
        item["id"] for day in plan["days"] for item in day["new_concepts"]
    }
    assert continuity["id"] in {
        item["id"] for day in plan["days"] for item in day["new_concepts"]
    }


def test_coach_plan_empty_database_has_no_fabricated_schedule(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        plan = client.get("/api/coach/plan").json()

    assert len(plan["days"]) == 7
    assert all(not day["reviews"] and not day["new_concepts"] and not day["foundation_concepts"] for day in plan["days"])
    assert plan["summary"]["planned_reviews"] == 0
    assert plan["summary"]["planned_new_concepts"] == 0
    assert plan["summary"]["estimated_minutes"] == 0
