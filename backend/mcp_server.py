"""Read-only Model Context Protocol server for the local AI-PC Dashboard.

Run with:
    .venv/Scripts/python.exe -m backend.mcp_server

The server talks to the already-running Dashboard at 127.0.0.1:8765 so every
tool shares the same data and audit trail. No tool writes or executes side
effects; browser actions remain behind the Dashboard approval API.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DASHBOARD_URL = os.getenv("AI_PC_DASHBOARD_URL", "http://127.0.0.1:8765")

mcp = FastMCP("nexus-ai-pc")


def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        response = httpx.get(
            f"{DASHBOARD_URL}{path}",
            params=params,
            timeout=15.0,
            follow_redirects=False,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f"AI-PC Dashboard returned HTTP {error.response.status_code}") from error
    except httpx.RequestError as error:
        raise RuntimeError("AI-PC Dashboard is unavailable; start it with start.ps1") from error
    return response.json()


@mcp.tool()
def search_library(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search local library files (hybrid keyword + semantic). Returns citable chunks."""
    return _api_get("/api/library/search", {"q": query, "limit": min(max(1, limit), 20)})


@mcp.tool()
def learning_progress(course_id: int | None = None) -> list[dict[str, Any]]:
    """List learning concepts with mastery, status, and next review time."""
    params = {"course_id": course_id} if course_id else None
    return _api_get("/api/learning/progress", params)


@mcp.tool()
def coach_report(course_id: int | None = None) -> dict[str, Any]:
    """Explainable learning report: mastery, trends, weak prerequisites, next step."""
    params = {"course_id": course_id} if course_id else None
    return _api_get("/api/coach/report", params)


@mcp.tool()
def coach_plan(days: int = 7) -> dict[str, Any]:
    """Return a daily study plan for the next N days based on FSRS evidence."""
    return _api_get("/api/coach/plan", {"days": min(max(1, days), 14)})


@mcp.tool()
def research_projects() -> list[dict[str, Any]]:
    """List research projects stored in the local dashboard."""
    return _api_get("/api/research/projects")


@mcp.tool()
def zotero_status() -> dict[str, Any]:
    """Report Zotero read-only sync state and item count."""
    return _api_get("/api/zotero/status")


@mcp.tool()
def ops_status() -> dict[str, Any]:
    """Report database integrity, disk space, and latest backup state."""
    return _api_get("/api/ops/status")


@mcp.tool()
def audit_log(limit: int = 20) -> list[dict[str, Any]]:
    """Read the latest local audit events (no secrets are ever stored)."""
    return _api_get("/api/audit", {"limit": min(max(1, limit), 100)})


if __name__ == "__main__":
    mcp.run()
