import sqlite3
from pathlib import Path

import pytest

from backend.database import Database, DatabaseVersionError, SCHEMA_VERSION


def test_database_records_current_schema_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "versioned.sqlite3")
    database.initialize()

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert version == SCHEMA_VERSION


def test_database_rejects_newer_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(DatabaseVersionError, match="newer than this application supports"):
        Database(path).initialize()


def test_migration_adds_conversation_progress_to_existing_agent_tasks(tmp_path: Path) -> None:
    path = tmp_path / "agent-progress.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE agent_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                run_tests INTEGER NOT NULL DEFAULT 1,
                generate_summary INTEGER NOT NULL DEFAULT 1,
                allow_dependencies INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
            INSERT INTO agent_tasks(project, title, created_at, updated_at)
            VALUES ('Legacy', 'Existing task', '2026-08-08T00:00:00+00:00', '2026-08-08T00:00:00+00:00');
            PRAGMA user_version = 2;
            """
        )

    database = Database(path)
    database.initialize()
    task = database.query_one("SELECT * FROM agent_tasks WHERE id = 1")

    assert task is not None
    assert task["progress_percent"] == 0
    assert task["progress_note"] is None
    assert task["conversation_session_id"] is None
