"""Operations helpers: automatic backup, retention, and backup settings.

The module keeps scheduled-backup logic outside ``app.py`` so it can be
tested directly and reused by the dashboard and future schedulers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .database import Database, utc_now


logger = logging.getLogger("nexus.ops")

BACKUP_SETTINGS_ENABLED = "ops.backup.enabled"
BACKUP_SETTINGS_INTERVAL = "ops.backup.interval_hours"
BACKUP_SETTINGS_KEEP = "ops.backup.keep_count"

DEFAULT_BACKUP_ENABLED = True
DEFAULT_BACKUP_INTERVAL_HOURS = 24
DEFAULT_BACKUP_KEEP_COUNT = 14
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 720
MIN_KEEP_COUNT = 1
MAX_KEEP_COUNT = 365

BACKUP_GLOB = "ai-pc-*.sqlite3"


def _clamp_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_backup_settings(database: Database) -> dict[str, object]:
    """Read backup settings from SQLite, falling back to safe defaults."""
    rows = database.query_all(
        "SELECT key, value FROM settings WHERE key IN (?, ?, ?) ORDER BY key",
        (
            BACKUP_SETTINGS_ENABLED,
            BACKUP_SETTINGS_INTERVAL,
            BACKUP_SETTINGS_KEEP,
        ),
    )
    values = {row["key"]: row["value"] for row in rows}
    enabled_value = str(values.get(BACKUP_SETTINGS_ENABLED, "1")).strip().lower()
    enabled = enabled_value not in {"0", "false", "no", "off"}
    return {
        "enabled": enabled,
        "interval_hours": _clamp_int(
            values.get(BACKUP_SETTINGS_INTERVAL),
            DEFAULT_BACKUP_INTERVAL_HOURS,
            MIN_INTERVAL_HOURS,
            MAX_INTERVAL_HOURS,
        ),
        "keep_count": _clamp_int(
            values.get(BACKUP_SETTINGS_KEEP),
            DEFAULT_BACKUP_KEEP_COUNT,
            MIN_KEEP_COUNT,
            MAX_KEEP_COUNT,
        ),
    }


def save_backup_settings(
    database: Database,
    *,
    enabled: bool,
    interval_hours: int,
    keep_count: int,
) -> dict[str, object]:
    """Persist backup settings and audit the change."""
    now = utc_now()
    database.execute_many(
        """
        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        [
            (BACKUP_SETTINGS_ENABLED, "1" if enabled else "0", now),
            (
                BACKUP_SETTINGS_INTERVAL,
                str(max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, int(interval_hours)))),
                now,
            ),
            (
                BACKUP_SETTINGS_KEEP,
                str(max(MIN_KEEP_COUNT, min(MAX_KEEP_COUNT, int(keep_count)))),
                now,
            ),
        ],
    )
    database.audit("ops", "backup_settings", "update")
    return read_backup_settings(database)


def prune_backups(storage_root: Path, keep_count: int) -> list[str]:
    """Delete backups beyond ``keep_count``; returns the pruned file names.

    Only files matching ``ai-pc-*.sqlite3`` inside the configured backup
    directory are considered, and each resolved target is re-checked before
    removal so a symlink cannot redirect deletion outside that directory.
    """
    backup_dir = storage_root / "backups" / "database"
    if not backup_dir.is_dir() or keep_count < 1:
        return []
    resolved_dir = backup_dir.resolve()
    candidates = sorted(
        (path for path in backup_dir.glob(BACKUP_GLOB) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    pruned: list[str] = []
    for stale in candidates[keep_count:]:
        try:
            resolved = stale.resolve()
            if resolved.parent != resolved_dir:
                logger.warning("Skipping backup outside configured directory: %s", resolved)
                continue
            stale.unlink()
            pruned.append(stale.name)
        except OSError:
            logger.exception("Failed to prune backup %s", stale)
    return pruned


def run_auto_backup(
    database: Database,
    storage_root: Path,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Create one verified online backup, then apply retention.

    Raises on backup failure after recording an error audit event; the
    scheduler catches the exception so the service keeps running.
    """
    current = settings or read_backup_settings(database)
    if not current.get("enabled", True):
        return {"enabled": False, "backup": None, "pruned": []}
    keep_count = int(current.get("keep_count") or DEFAULT_BACKUP_KEEP_COUNT)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = storage_root / "backups" / "database" / f"ai-pc-{stamp}.sqlite3"
    try:
        database.backup_to(destination)
        quick_check = database.verify_backup(destination)
    except Exception:
        database.audit("ops", "backup", "auto", result="error")
        raise
    if quick_check != "ok":
        database.audit("ops", "backup", "auto", result="error")
        raise RuntimeError("Automatic backup failed verification")
    pruned = prune_backups(storage_root, keep_count)
    database.audit("ops", "backup", destination.name)
    if pruned:
        database.audit("ops", "backup_prune", ",".join(sorted(pruned)))
    return {
        "enabled": True,
        "backup": {
            "path": str(destination),
            "name": destination.name,
            "size_bytes": destination.stat().st_size,
            "quick_check": quick_check,
        },
        "pruned": pruned,
    }
