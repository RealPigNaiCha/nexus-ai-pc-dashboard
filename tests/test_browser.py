from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


class FakeExecutor:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[dict] = []
        self.closed = False

    def is_available(self) -> bool:
        return self.available

    async def execute(
        self,
        action: str,
        *,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        timeout_ms: int = 15_000,
    ) -> dict:
        self.calls.append(
            {"action": action, "url": url, "selector": selector, "text": text, "timeout_ms": timeout_ms}
        )
        return {"ok": True, "action": action, "url": url}

    async def close(self) -> None:
        self.closed = True


def make_client(tmp_path: Path, executor: FakeExecutor) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "browser.sqlite3",
            serve_static=False,
            browser_executor=executor,
        )
    )


def test_browser_open_requires_allowlist(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        response = client.post(
            "/api/browser/actions",
            json={"action": "open", "url": "https://example.com/"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Domain is not in the browser allowlist: example.com"}
    assert executor.calls == []


def test_browser_approval_flow_executes_and_audits(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        saved = client.put(
            "/api/browser/allowlist",
            json={"domains": ["example.com", "https://docs.python.org"]},
        )
        submitted = client.post(
            "/api/browser/actions",
            json={"action": "open", "url": "https://example.com/page"},
        )
        action_id = submitted.json()["id"]
        approved = client.post(f"/api/browser/actions/{action_id}/approve")
        audit = client.get("/api/audit", params={"limit": 20}).json()

    assert saved.status_code == 200
    assert saved.json()["allowlist"] == ["docs.python.org", "example.com"]
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "pending"
    assert submitted.json()["risk"] == "medium"
    assert approved.status_code == 200
    assert approved.json()["status"] == "succeeded"
    assert executor.calls == [
        {"action": "open", "url": "https://example.com/page", "selector": None, "text": None, "timeout_ms": 15000}
    ]
    browser_audit = [item["action"] for item in audit if item["category"] == "browser"]
    assert sorted(action for action in browser_audit if action in {"submit", "approve"}) == ["approve", "submit"]


def test_browser_snapshot_is_low_risk_and_auto_runs(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        response = client.post(
            "/api/browser/actions",
            json={"action": "snapshot"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "succeeded"
    assert response.json()["risk"] == "low"
    assert executor.calls == [
        {"action": "snapshot", "url": None, "selector": None, "text": None, "timeout_ms": 15000}
    ]


def test_browser_reject_and_duplicate_approve_conflict(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        client.put("/api/browser/allowlist", json={"domains": ["example.com"]})
        submitted = client.post(
            "/api/browser/actions",
            json={"action": "open", "url": "https://example.com/"},
        )
        action_id = submitted.json()["id"]
        rejected = client.post(f"/api/browser/actions/{action_id}/reject")
        duplicate = client.post(f"/api/browser/actions/{action_id}/approve")
        listing = client.get("/api/browser/actions").json()

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert duplicate.status_code == 409
    assert executor.calls == []
    assert any(item["id"] == action_id and item["status"] == "rejected" for item in listing)


def test_browser_emergency_stop_blocks_until_resume(tmp_path: Path) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        stopped = client.post("/api/browser/stop")
        blocked = client.post(
            "/api/browser/actions",
            json={"action": "snapshot"},
        )
        resumed = client.post("/api/browser/resume")
        allowed = client.post(
            "/api/browser/actions",
            json={"action": "snapshot"},
        )

    assert stopped.status_code == 200
    assert stopped.json()["stopped"] is True
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Browser automation is emergency-stopped"
    assert executor.closed is True
    assert resumed.json()["stopped"] is False
    assert allowed.status_code == 202


def test_browser_unavailable_executor_returns_503(tmp_path: Path) -> None:
    executor = FakeExecutor(available=False)
    with make_client(tmp_path, executor) as client:
        client.put("/api/browser/allowlist", json={"domains": ["example.com"]})
        submitted = client.post(
            "/api/browser/actions",
            json={"action": "open", "url": "https://example.com/"},
        )
        action_id = submitted.json()["id"]
        approved = client.post(f"/api/browser/actions/{action_id}/approve")
        status = client.get("/api/browser/status").json()

    assert approved.status_code == 503
    assert approved.json()["detail"] == "Playwright browser is not installed"
    assert status["available"] is False
    assert status["pending_count"] == 0


@pytest.mark.parametrize(
    ("payload", "expected_status", "detail"),
    [
        ({"action": "open", "url": "ftp://example.com/file"}, 422, "Browser target must be an http(s) URL"),
        ({"action": "click"}, 422, "Selector is required"),
        ({"action": "hover"}, 422, None),
    ],
)
def test_browser_input_validation(
    tmp_path: Path,
    payload: dict,
    expected_status: int,
    detail: str | None,
) -> None:
    executor = FakeExecutor()
    with make_client(tmp_path, executor) as client:
        response = client.post("/api/browser/actions", json=payload)

    assert response.status_code == expected_status
    if detail:
        assert response.json()["detail"] == detail
