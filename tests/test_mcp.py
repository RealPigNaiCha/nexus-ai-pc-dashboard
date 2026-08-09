import backend.mcp_server as mcp_server


def test_mcp_tools_return_dashboard_data(monkeypatch) -> None:
    def fake_get(path: str, params=None):
        assert path.startswith("/api/")
        return {"path": path, "params": params}

    monkeypatch.setattr(mcp_server, "_api_get", fake_get)

    assert mcp_server.search_library("数列极限", limit=5) == {
        "path": "/api/library/search",
        "params": {"q": "数列极限", "limit": 5},
    }
    assert mcp_server.search_library("x", limit=999)["params"]["limit"] == 20
    assert mcp_server.learning_progress()["params"] is None
    assert mcp_server.learning_progress(course_id=3)["params"] == {"course_id": 3}
    assert mcp_server.coach_report()["path"] == "/api/coach/report"
    assert mcp_server.coach_plan(days=30)["params"] == {"days": 14}
    assert mcp_server.research_projects()["path"] == "/api/research/projects"
    assert mcp_server.agent_tasks()["path"] == "/api/agent/tasks"
    assert mcp_server.task_envelope(7)["path"] == "/api/bridge/tasks/7/envelope"
    assert mcp_server.improvement_proposals()["path"] == "/api/improvements/proposals"
    assert mcp_server.zotero_status()["path"] == "/api/zotero/status"
    assert mcp_server.ops_status()["path"] == "/api/ops/status"
    assert mcp_server.audit_log(limit=500)["params"] == {"limit": 100}


def test_mcp_tool_errors_are_sanitized(monkeypatch) -> None:
    def failing_get(_path: str, _params=None):
        raise RuntimeError("AI-PC Dashboard is unavailable; start it with start.ps1")

    monkeypatch.setattr(mcp_server, "_api_get", failing_get)

    try:
        mcp_server.search_library("极限")
    except RuntimeError as error:
        assert "start it with start.ps1" in str(error)
    else:
        raise AssertionError("expected RuntimeError")
