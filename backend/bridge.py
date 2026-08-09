from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


BRIDGE_SCHEMA = "nexus.task-envelope"
BRIDGE_VERSION = 1


def _json_list(value: object) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def task_result_payload(row: Mapping[str, Any]) -> dict[str, object]:
    return {
        "result_id": row["result_id"],
        "task_id": int(row["task_id"]),
        "contract_version": int(row["contract_version"]),
        "envelope_sha256": row["envelope_sha256"],
        "status": row["status"],
        "summary": row["summary"],
        "citations": _json_list(row.get("citations_json")),
        "artifacts": _json_list(row.get("artifacts_json")),
        "tests": _json_list(row.get("tests_json")),
        "questions": _json_list(row.get("questions_json")),
        "executor": row.get("executor"),
        "source_commit": row.get("source_commit"),
        "created_at": row["created_at"],
    }


def build_task_envelope(
    task: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    task_id = int(task["id"])
    base: dict[str, object] = {
        "schema": BRIDGE_SCHEMA,
        "version": BRIDGE_VERSION,
        "task_id": task_id,
        "revision": task.get("updated_at") or task.get("created_at"),
        "task": {
            "project": task["project"],
            "title": task["title"],
            "status": task["status"],
            "run_tests": bool(task.get("run_tests")),
            "generate_summary": bool(task.get("generate_summary")),
            "allow_dependencies": bool(task.get("allow_dependencies")),
            "progress_percent": int(task.get("progress_percent") or 0),
            "progress_note": task.get("progress_note"),
            "created_at": task["created_at"],
            "updated_at": task.get("updated_at") or task["created_at"],
        },
        "context": {
            "search_query": task["title"],
            "search_endpoint": "/api/library/search",
            "instruction": "Search the local library before relying on model knowledge; preserve document IDs and locations.",
        },
        "constraints": {
            "local_only": True,
            "no_secrets": True,
            "no_unapproved_side_effects": True,
            "report_only_verified_actions": True,
        },
        "report_endpoint": f"/api/bridge/tasks/{task_id}/results",
        "results": [task_result_payload(row) for row in results],
    }
    canonical = json.dumps(base, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**base, "content_sha256": hashlib.sha256(canonical).hexdigest()}
