from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.agent import AgentHandoff, AgentHandoffError
from backend.app import create_app
from backend.database import Database
from backend.tooling import ToolRegistry


HANDOFF_HEADERS = {
    "Origin": "http://127.0.0.1:8765",
    "Sec-Fetch-Site": "same-origin",
    "X-AI-PC-Action": "agent-handoff",
}


def make_runtime(
    tmp_path: Path,
    *,
    workspace: Path | None = None,
    code_available: bool = True,
    cline_available: bool = True,
    uri_opener=None,
) -> tuple[AgentHandoff, list[tuple[list[str], Path]], list[str]]:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)
    active_workspace = workspace or (workspace_root / "ai-pc-dashboard")
    active_workspace.mkdir(parents=True, exist_ok=True)
    code_executable = tmp_path / "apps" / "Code.exe"
    if code_available:
        code_executable.parent.mkdir(parents=True, exist_ok=True)
        code_executable.write_bytes(b"test executable")

    extension_root = tmp_path / "extensions"
    if cline_available:
        extension = extension_root / "saoudrizwan.claude-dev-4.1.4"
        extension.mkdir(parents=True, exist_ok=True)
        (extension / "package.json").write_text(
            json.dumps({"publisher": "saoudrizwan", "name": "claude-dev", "version": "4.1.4"}),
            encoding="utf-8",
        )

    launches: list[tuple[list[str], Path]] = []
    opened_uris: list[str] = []

    def launch(arguments: list[str], cwd: Path) -> None:
        launches.append((arguments, cwd))

    def open_uri(uri: str) -> None:
        opened_uris.append(uri)
        if uri_opener:
            uri_opener(uri)

    runtime = AgentHandoff(
        active_workspace,
        tmp_path / "data" / "agent" / "tasks with spaces",
        allowed_workspace_root=workspace_root,
        code_executable=code_executable,
        process_launcher=launch,
        uri_opener=open_uri,
        extension_root=extension_root,
    )
    return runtime, launches, opened_uris


def make_client(tmp_path: Path, runtime: AgentHandoff) -> TestClient:
    registry = ToolRegistry(
        tmp_path,
        runtime,
        local_app_data=tmp_path / "local-app-data",
        program_files=tmp_path / "program-files",
    )
    app = create_app(
        tmp_path / "agent.sqlite3",
        serve_static=False,
        agent_handoff=runtime,
        tool_registry=registry,
    )
    return TestClient(app, base_url="http://127.0.0.1:8765")


def create_task(client: TestClient, title: str = "Add a verified Agent handoff") -> dict:
    response = client.post(
        "/api/agent/tasks",
        json={
            "project": "AI-PC Dashboard",
            "title": title,
            "run_tests": True,
            "generate_summary": True,
            "allow_dependencies": False,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_agent_status_detects_cline_and_approved_workspace(tmp_path: Path) -> None:
    runtime, _, _ = make_runtime(tmp_path)
    with make_client(tmp_path, runtime) as client:
        status = client.get("/api/agent/status")
        assert status.status_code == 200
        assert status.json()["available"] is True
        assert status.json()["workspace_approved"] is True
        assert status.json()["cline_version"] == "4.1.4"

        tools = {item["id"]: item for item in client.get("/api/tools").json()["tools"]}
        assert tools["nexus-core"]["status"] == "ready"
        assert tools["vscode"]["status"] == "ready"
        assert tools["cline"]["version"] == "4.1.4"
        assert tools["paperqa2"]["status"] == "planned"


def test_handoff_writes_integrity_checked_task_and_minimal_uri(tmp_path: Path) -> None:
    runtime, launches, opened_uris = make_runtime(tmp_path)
    title = "Handle query characters ?x=1&unsafe=title without leaking the title"
    with make_client(tmp_path, runtime) as client:
        task = create_task(client, title)
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "handoff_requested"
        assert payload["task"]["status"] == "handoff_requested"
        assert len(payload["task_sha256"]) == 64
        assert len(launches) == 1
        assert len(opened_uris) == 1

        task_file = Path(payload["task_file"])
        content = task_file.read_text(encoding="utf-8")
        assert title in content
        assert str(runtime.workspace_path.resolve()) in content
        assert hashlib.sha256(task_file.read_bytes()).hexdigest() == payload["task_sha256"]

        uri = opened_uris[0]
        assert uri.startswith("vscode://saoudrizwan.claude-dev/task?")
        prompt = parse_qs(urlsplit(uri).query)["prompt"][0]
        assert f"#{task['id']}" in prompt
        assert str(task_file) in prompt
        assert title not in prompt
        assert str(runtime.workspace_path.resolve()) not in prompt

        repeated = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)
        assert repeated.status_code == 409
        assert len(launches) == 1
        assert len(opened_uris) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://127.0.0.1:8765", "X-AI-PC-Action": "wrong-action"},
        {"Origin": "https://untrusted.example", "X-AI-PC-Action": "agent-handoff"},
        {
            "Origin": "http://127.0.0.1:8765",
            "Sec-Fetch-Site": "cross-site",
            "X-AI-PC-Action": "agent-handoff",
        },
    ],
)
def test_unconfirmed_or_cross_site_handoff_is_rejected(
    tmp_path: Path,
    headers: dict[str, str],
) -> None:
    runtime, launches, opened_uris = make_runtime(tmp_path)
    with make_client(tmp_path, runtime) as client:
        task = create_task(client)
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=headers)
        assert response.status_code == 403
        assert client.get("/api/agent/tasks").json()[0]["status"] == "queued"
        assert launches == []
        assert opened_uris == []


def test_non_loopback_host_is_rejected(tmp_path: Path) -> None:
    runtime, launches, _ = make_runtime(tmp_path)
    with make_client(tmp_path, runtime) as client:
        task = create_task(client)
        headers = {
            "Host": "remote.example:8765",
            "Origin": "http://remote.example:8765",
            "X-AI-PC-Action": "agent-handoff",
        }
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=headers)
        assert response.status_code == 403
        assert launches == []


def test_missing_tool_keeps_task_queued(tmp_path: Path) -> None:
    runtime, launches, opened_uris = make_runtime(tmp_path, code_available=False)
    with make_client(tmp_path, runtime) as client:
        task = create_task(client)
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)
        assert response.status_code == 503
        assert client.get("/api/agent/tasks").json()[0]["status"] == "queued"
        assert launches == []
        assert opened_uris == []


def test_workspace_outside_approved_root_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "app" / "dashboard"
    runtime, launches, _ = make_runtime(tmp_path, workspace=workspace)
    with make_client(tmp_path, runtime) as client:
        assert client.get("/api/agent/status").json()["workspace_approved"] is False
        task = create_task(client)
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)
        assert response.status_code == 503
        assert client.get("/api/agent/tasks").json()[0]["status"] == "queued"
        assert launches == []


def test_uri_open_failure_is_recorded_without_retrying(tmp_path: Path) -> None:
    def fail_open(_uri: str) -> None:
        raise AgentHandoffError("Cline task URI could not be opened")

    runtime, launches, opened_uris = make_runtime(tmp_path, uri_opener=fail_open)
    with make_client(tmp_path, runtime) as client:
        task = create_task(client)
        response = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)
        assert response.status_code == 503
        failed = client.get("/api/agent/tasks").json()[0]
        assert failed["status"] == "handoff_failed"
        assert failed["last_error"] == "agent_handoff_failed"
        assert len(launches) == 1
        assert len(opened_uris) == 1

        repeated = client.post(f"/api/agent/tasks/{task['id']}/handoff", headers=HANDOFF_HEADERS)
        assert repeated.status_code == 409
        assert len(launches) == 1


def test_task_file_outside_approved_directory_is_rejected(tmp_path: Path) -> None:
    runtime, _, _ = make_runtime(tmp_path)
    runtime.task_root.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.md"
    outside.write_text("not approved", encoding="utf-8")
    task = {
        "id": 1,
        "project": "Dashboard",
        "title": "Test",
        "created_at": "2026-08-06T00:00:00+00:00",
    }
    with pytest.raises(AgentHandoffError, match="outside the approved task directory"):
        runtime.open_in_cline(task, outside)


def test_tool_registry_detects_installed_external_projects(tmp_path: Path) -> None:
    runtime, _, _ = make_runtime(tmp_path)
    deeptutor = tmp_path / "tools" / "deeptutor"
    (deeptutor / "deeptutor").mkdir(parents=True)
    (deeptutor / "pyproject.toml").write_text('[project]\nname = "deeptutor"\n', encoding="utf-8")
    (deeptutor / "deeptutor" / "__version__.py").write_text('__version__ = "1.5.9"\n', encoding="utf-8")
    codex = tmp_path / "tools" / "codex"
    codex.mkdir(parents=True)
    (codex / "codex.exe").write_bytes(b"codex")
    (codex / "VERSION").write_text("0.146.1\n", encoding="utf-8")
    (tmp_path / "vault").mkdir()
    obsidian = tmp_path / "local" / "Programs" / "Obsidian" / "Obsidian.exe"
    obsidian.parent.mkdir(parents=True)
    obsidian.write_bytes(b"obsidian")
    zotero = tmp_path / "programs" / "Zotero" / "zotero.exe"
    zotero.parent.mkdir(parents=True)
    zotero.write_bytes(b"zotero")
    (zotero.parent / "application.ini").write_text("[App]\nVersion=9.0.6\n", encoding="utf-8")

    registry = ToolRegistry(
        tmp_path,
        runtime,
        local_app_data=tmp_path / "local",
        program_files=tmp_path / "programs",
    )
    tools = {item["id"]: item for item in registry.list_tools("0.1.0")}
    assert tools["deeptutor"]["version"] == "1.5.9"
    assert tools["deeptutor"]["integration"] == "adapter_pending"
    assert tools["codex-cli"]["version"] == "0.146.1"
    assert tools["obsidian"]["status"] == "ready"
    assert tools["zotero"]["version"] == "9.0.6"


def test_agent_task_migration_preserves_legacy_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE agent_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                run_tests INTEGER NOT NULL DEFAULT 1,
                generate_summary INTEGER NOT NULL DEFAULT 1,
                allow_dependencies INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agent_tasks(
                project, title, status, run_tests, generate_summary, allow_dependencies, created_at
            ) VALUES (?, ?, 'queued', 1, 1, 0, ?)
            """,
            ("Legacy", "Keep this task", "2026-08-06T00:00:00+00:00"),
        )
        connection.commit()

    database = Database(database_path)
    database.initialize()
    row = database.query_one("SELECT * FROM agent_tasks WHERE id = 1")
    assert row is not None
    assert row["title"] == "Keep this task"
    assert row["updated_at"] == row["created_at"]
    assert row["task_file"] is None
    assert row["task_sha256"] is None
