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


def test_manual_directory_import_indexes_and_reuses_changed_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("第一条本地笔记。\n", encoding="utf-8")
    client = make_client(tmp_path)
    with client:
        first = client.post("/api/library/import", json={"path": str(tmp_path)})
        assert first.status_code == 201
        payload = first.json()
        assert payload["documents_seen"] == 1
        assert payload["imported_count"] == 1
        assert payload["chunks_indexed"] >= 1

        reused = client.post("/api/library/import", json={"path": str(tmp_path)}).json()
        assert reused["imported_count"] == 0
        assert reused["reused_count"] == 1

        audit = client.app.state.database.query_all(
            "SELECT action, target, result FROM audit_events ORDER BY id"
        )
        assert [event["action"] for event in audit if event["action"] in {"index_document", "reuse_document"}] == [
            "index_document",
            "reuse_document",
        ]

        source.write_text("修改后的第二条本地笔记。\n", encoding="utf-8")
        changed = client.post("/api/library/import", json={"path": str(tmp_path)}).json()
        assert changed["imported_count"] == 1

        assert client.get("/api/library/auto/status").status_code == 404
        assert client.post("/api/library/auto/scan").status_code == 404
