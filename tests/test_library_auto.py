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


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "auto.sqlite3",
            serve_static=False,
            credential_backend=MemoryKeyring(),
            model_transport=httpx.MockTransport(lambda request: httpx.Response(200)),
            allowed_library_roots=[tmp_path],
        )
    )


def test_library_auto_scan_imports_new_and_reuses_changed_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("第一条本地笔记。\n", encoding="utf-8")
    client = make_client(tmp_path)
    with client:
        first = client.post("/api/library/auto/scan")
        assert first.status_code == 201
        payload = first.json()
        assert payload["seen_count"] == 1
        assert payload["imported_count"] == 1
        assert payload["chunks_indexed"] >= 1

        status = client.get("/api/library/auto/status").json()
        assert status["enabled"] is True
        assert status["interval_seconds"] == 300
        assert status["last_scan"]
        assert status["last_summary"]["imported_count"] == 1

        reused = client.post("/api/library/auto/scan").json()
        assert reused["imported_count"] == 0
        assert reused["reused_count"] == 1

        source.write_text("修改后的第二条本地笔记。\n", encoding="utf-8")
        changed = client.post("/api/library/auto/scan").json()
        assert changed["imported_count"] == 1

        updated = client.put(
            "/api/library/auto/status",
            json={"enabled": False, "interval_seconds": 120},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False
        assert updated.json()["interval_seconds"] == 120


def test_library_auto_scan_returns_error_for_missing_root(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    with client:
        response = client.post("/api/library/auto/scan")
        assert response.status_code == 201
        payload = response.json()
        assert payload["seen_count"] == 0
        assert payload["imported_count"] == 0
