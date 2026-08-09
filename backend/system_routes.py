from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Query, Request

from .database import Database
from .tooling import ToolRegistry


def create_system_router(*, storage_root: Path, tool_registry: ToolRegistry) -> APIRouter:
    """Build the low-coupling system routes shared by every dashboard feature."""

    router = APIRouter()

    def database(request: Request) -> Database:
        return request.app.state.database

    @router.get("/api/health")
    def health(request: Request) -> dict[str, object]:
        database_ok = database(request).health()
        return {
            "status": "ok" if database_ok else "degraded",
            "version": request.app.version,
            "database": "ok" if database_ok else "error",
            "local_only": True,
        }

    @router.get("/api/overview")
    def overview(request: Request) -> dict[str, object]:
        counts = database(request).query_one(
            """
            SELECT
                (SELECT COUNT(*) FROM documents) AS documents,
                (SELECT COUNT(*) FROM research_projects) AS research_projects,
                (
                    SELECT COUNT(*) FROM agent_tasks
                    WHERE status IN ('queued', 'handoff_pending', 'handoff_requested')
                ) AS active_agent_tasks,
                (SELECT ROUND(AVG(mastery), 1) FROM learning_concepts) AS learning_mastery
            """
        )
        result: dict[str, object] = counts or {}
        usage = shutil.disk_usage(storage_root)
        result.update(
            {
                "storage_total_bytes": usage.total,
                "storage_used_bytes": usage.used,
                "storage_free_bytes": usage.free,
                "storage_root": str(storage_root),
            }
        )
        return result

    @router.get("/api/tools")
    def list_tools(request: Request) -> dict[str, list[dict[str, object]]]:
        return {"tools": tool_registry.list_tools(request.app.version)}

    @router.get("/api/audit")
    def list_audit(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict]:
        return database(request).query_all(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    return router
