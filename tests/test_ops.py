import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import Database
from backend.ops import prune_backups, read_backup_settings, run_auto_backup


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "ops.sqlite3", serve_static=False))


def test_ops_status_reports_database_storage_and_backup_state(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        status = client.get("/api/ops/status").json()

    assert status["ok"] is False
    assert status["database"]["quick_check"] == "ok"
    assert status["database"]["size_bytes"] > 0
    assert status["storage"]["free_bytes"] > 0
    assert status["storage"]["free_percent"] > 0
    assert status["backup"] is None
    assert any("备份" in warning for warning in status["warnings"])


def test_ops_backup_creates_verified_online_backup(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/ops/backup")
        status = client.get("/api/ops/status").json()
        audit = client.get("/api/audit", params={"limit": 10}).json()

    assert response.status_code == 201
    backup_path = Path(response.json()["path"])
    assert backup_path.is_file()
    assert backup_path.parent == tmp_path / "backups" / "database"
    assert backup_path.name.startswith("ai-pc-")
    assert response.json()["quick_check"] == "ok"
    assert status["backup"]["path"] == str(backup_path)
    assert status["backup"]["age_days"] == 0
    assert any(item["action"] == "backup" and item["result"] == "success" for item in audit)


def test_backup_settings_defaults_update_and_validation(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        defaults = client.get("/api/ops/backup/settings").json()
        status = client.get("/api/ops/status").json()

    assert defaults == {"enabled": True, "interval_hours": 24, "keep_count": 14}
    assert status["backup_settings"] == defaults

    with make_client(tmp_path) as client:
        updated = client.put(
            "/api/ops/backup/settings",
            json={"enabled": False, "interval_hours": 12, "keep_count": 5},
        )
        after = client.get("/api/ops/backup/settings").json()
        audit = client.get("/api/audit", params={"limit": 10}).json()
        invalid = client.put(
            "/api/ops/backup/settings",
            json={"enabled": True, "interval_hours": 0, "keep_count": 5},
        )

    assert updated.status_code == 200
    assert updated.json() == {"enabled": False, "interval_hours": 12, "keep_count": 5}
    assert after == {"enabled": False, "interval_hours": 12, "keep_count": 5}
    assert any(item["action"] == "backup_settings" for item in audit)
    assert invalid.status_code == 422


def test_auto_backup_creates_verified_backup_and_prunes_old(tmp_path: Path) -> None:
    database = Database(tmp_path / "unit.sqlite3")
    database.initialize()
    backup_dir = tmp_path / "backups" / "database"
    backup_dir.mkdir(parents=True)
    stale = backup_dir / "ai-pc-20260101-000000.sqlite3"
    stale.write_bytes(b"stale")

    result = run_auto_backup(
        database,
        tmp_path,
        settings={"enabled": True, "interval_hours": 24, "keep_count": 1},
    )

    assert result["enabled"] is True
    assert result["pruned"] == [stale.name]
    assert not stale.exists()
    backup = Path(result["backup"]["path"])
    assert backup.is_file()
    assert result["backup"]["quick_check"] == "ok"
    assert backup.name.startswith("ai-pc-")
    audit = database.query_all("SELECT action, result FROM audit_events ORDER BY id DESC LIMIT 5")
    assert any(item["action"] == "backup" and item["result"] == "success" for item in audit)
    assert any(item["action"] == "backup_prune" for item in audit)


def test_auto_backup_disabled_skips(tmp_path: Path) -> None:
    database = Database(tmp_path / "unit-disabled.sqlite3")
    database.initialize()

    result = run_auto_backup(
        database,
        tmp_path,
        settings={"enabled": False, "interval_hours": 24, "keep_count": 14},
    )

    assert result == {"enabled": False, "backup": None, "pruned": []}
    backup_dir = tmp_path / "backups" / "database"
    if backup_dir.is_dir():
        assert list(backup_dir.glob("ai-pc-*.sqlite3")) == []


def test_prune_keeps_newest_and_ignores_other_names(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups" / "database"
    backup_dir.mkdir(parents=True)
    names = ["ai-pc-1.sqlite3", "ai-pc-2.sqlite3", "ai-pc-3.sqlite3", "manual-other.sqlite3"]
    for index, name in enumerate(names):
        path = backup_dir / name
        path.write_bytes(b"x")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))

    pruned = prune_backups(tmp_path, keep_count=2)

    assert pruned == ["ai-pc-1.sqlite3"]
    assert (backup_dir / "ai-pc-2.sqlite3").is_file()
    assert (backup_dir / "ai-pc-3.sqlite3").is_file()
    assert (backup_dir / "manual-other.sqlite3").is_file()


def test_read_backup_settings_falls_back_to_defaults(tmp_path: Path) -> None:
    database = Database(tmp_path / "unit-fallback.sqlite3")
    database.initialize()
    database.execute("DELETE FROM settings WHERE key LIKE 'ops.backup.%'")

    settings = read_backup_settings(database)

    assert settings == {"enabled": True, "interval_hours": 24, "keep_count": 14}
