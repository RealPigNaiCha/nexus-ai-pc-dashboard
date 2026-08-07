from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from .database import Database, utc_now


ALLOWED_ACTIONS = ("open", "click", "type", "snapshot", "close")
MEDIUM_RISK_ACTIONS = ("open", "click", "type", "close")
LOW_RISK_ACTIONS = ("snapshot",)
ALLOWLIST_SETTING = "browser.allowlist"


class BrowserError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def normalize_domain(value: str) -> str | None:
    candidate = value.strip().lower()
    if not candidate:
        return None
    candidate = candidate.removeprefix("http://").removeprefix("https://")
    candidate = candidate.split("/", 1)[0].split(":", 1)[0]
    return candidate or None


def action_risk(action: str) -> str:
    if action in MEDIUM_RISK_ACTIONS:
        return "medium"
    if action in LOW_RISK_ACTIONS:
        return "low"
    return "high"


class BrowserExecutor(Protocol):
    def is_available(self) -> bool: ...

    async def execute(
        self,
        action: str,
        *,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        timeout_ms: int = 15_000,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class PlaywrightExecutor:
    """Lazy Playwright executor; degrades to unavailable until the browser is installed."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def is_available(self) -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    async def execute(
        self,
        action: str,
        *,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        timeout_ms: int = 15_000,
    ) -> dict[str, Any]:
        if action == "close":
            await self.close()
            return {"ok": True, "page": None}
        if self._page is None:
            await self._start()
        if action == "open":
            await self._page.goto(url or "", wait_until="domcontentloaded", timeout=timeout_ms)
            return await self._snapshot()
        if action == "click":
            await self._page.click(selector or "", timeout=timeout_ms)
            return await self._snapshot()
        if action == "type":
            await self._page.fill(selector or "", text or "")
            return await self._snapshot()
        if action == "snapshot":
            return await self._snapshot()
        raise BrowserError("unsupported_action", "Unsupported browser action")

    async def _start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            finally:
                self._browser = None
                self._page = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None

    async def _snapshot(self) -> dict[str, Any]:
        title = ""
        body_text = ""
        try:
            title = await self._page.title()
        except Exception:
            pass
        try:
            body_text = (await self._page.inner_text("body"))[:2000]
        except Exception:
            pass
        return {
            "title": title,
            "url": self._page.url,
            "body_text": body_text,
        }


@dataclass
class BrowserAction:
    id: str
    action: str
    risk: str
    status: str
    created_at: str
    updated_at: str
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    timeout_ms: int = 15_000
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "risk": self.risk,
            "status": self.status,
            "url": self.url,
            "selector": self.selector,
            "text": self.text,
            "timeout_ms": self.timeout_ms,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


class BrowserController:
    """Controlled browser automation: allowlist -> risk -> approval -> audit -> emergency stop."""

    def __init__(
        self,
        executor: BrowserExecutor,
        database: Database,
        *,
        audit: Callable[[str, str, str | None, str], None] | None = None,
    ) -> None:
        self._executor = executor
        self._database = database
        self._audit = audit or (lambda _category, _action, _target, _result: None)
        self._actions: dict[str, BrowserAction] = {}
        self._recent: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._emergency_stopped = False

    def allowlist(self) -> list[str]:
        row = self._database.query_one(
            "SELECT value FROM settings WHERE key = ?",
            (ALLOWLIST_SETTING,),
        )
        if not row or not row["value"]:
            return []
        return [item for item in (normalize_domain(value) for value in str(row["value"]).split(",")) if item]

    def set_allowlist(self, domains: list[str]) -> list[str]:
        normalized = sorted({item for item in (normalize_domain(value) for value in domains) if item})
        now = utc_now()
        self._database.execute(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (ALLOWLIST_SETTING, ",".join(normalized), now),
        )
        return normalized

    def status(self) -> dict[str, Any]:
        pending = sum(1 for item in self._actions.values() if item.status == "pending")
        running = any(item.status == "executing" for item in self._actions.values())
        return {
            "available": self._executor.is_available(),
            "allowlist": self.allowlist(),
            "pending_count": pending,
            "running": running,
            "emergency_stopped": self._emergency_stopped,
            "recent_count": len(self._recent),
        }

    def list_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        items = [
            item.to_dict()
            for item in sorted(
                self._actions.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )
        ]
        return (self._recent + items)[:max(1, limit)]

    async def submit(
        self,
        *,
        action: str,
        url: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        timeout_ms: int = 15_000,
        source: str = "dashboard",
    ) -> dict[str, Any]:
        if self._emergency_stopped:
            raise BrowserError("emergency_stopped", "Browser automation is emergency-stopped", 409)
        if action not in ALLOWED_ACTIONS:
            raise BrowserError("unsupported_action", "Unsupported browser action")
        if action == "open":
            parsed = urlsplit(url or "")
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in {"http", "https"} or not host:
                raise BrowserError("invalid_url", "Browser target must be an http(s) URL", 422)
            if host not in self.allowlist():
                raise BrowserError(
                    "domain_not_allowed",
                    f"Domain is not in the browser allowlist: {host}",
                    403,
                )
        elif action in {"click", "type"} and not selector:
            raise BrowserError("missing_selector", "Selector is required", 422)

        item = BrowserAction(
            id=uuid.uuid4().hex[:12],
            action=action,
            risk=action_risk(action),
            status="pending",
            created_at=utc_now(),
            updated_at=utc_now(),
            url=url,
            selector=selector,
            text=text,
            timeout_ms=max(1_000, min(120_000, timeout_ms)),
        )
        async with self._lock:
            self._actions[item.id] = item
        self._audit("browser", "submit", item.id, item.risk)
        if item.risk == "low":
            return await self.approve(item.id, source=source)
        return item.to_dict()

    async def approve(self, action_id: str, source: str = "dashboard") -> dict[str, Any]:
        async with self._lock:
            item = self._actions.get(action_id)
            if item is None:
                raise BrowserError("not_found", "Browser action not found", 404)
            if item.status != "pending":
                raise BrowserError("conflict", f"Browser action is {item.status}", 409)
            item.status = "executing"
            item.updated_at = utc_now()
        if not self._executor.is_available():
            async with self._lock:
                item.status = "failed"
                item.error = "Playwright browser is not installed"
                item.updated_at = utc_now()
            self._remember(item)
            self._audit("browser", "approve", item.id, "unavailable")
            raise BrowserError("unavailable", "Playwright browser is not installed", 503)
        try:
            result = await self._executor.execute(
                item.action,
                url=item.url,
                selector=item.selector,
                text=item.text,
                timeout_ms=item.timeout_ms,
            )
            async with self._lock:
                item.status = "succeeded"
                item.result = result
                item.updated_at = utc_now()
            self._audit("browser", "approve", item.id, "success")
        except BrowserError:
            raise
        except Exception:
            async with self._lock:
                item.status = "failed"
                item.error = "Browser action failed"
                item.updated_at = utc_now()
            self._remember(item)
            self._audit("browser", "approve", item.id, "error")
            raise BrowserError("execution_failed", "Browser action failed", 502) from None
        self._remember(item)
        return item.to_dict()

    async def reject(self, action_id: str, source: str = "dashboard") -> dict[str, Any]:
        async with self._lock:
            item = self._actions.get(action_id)
            if item is None:
                raise BrowserError("not_found", "Browser action not found", 404)
            if item.status != "pending":
                raise BrowserError("conflict", f"Browser action is {item.status}", 409)
            item.status = "rejected"
            item.updated_at = utc_now()
        self._audit("browser", "reject", item.id, "success")
        self._remember(item)
        return item.to_dict()

    async def stop(self) -> None:
        self._emergency_stopped = True
        async with self._lock:
            for item in self._actions.values():
                if item.status == "pending":
                    item.status = "stopped"
                    item.updated_at = utc_now()
                    self._remember(item)
        await self._executor.close()
        self._audit("browser", "stop", None, "success")

    async def resume(self) -> None:
        self._emergency_stopped = False
        self._audit("browser", "resume", None, "success")

    def _remember(self, item: BrowserAction) -> None:
        if item.status in {"succeeded", "failed", "rejected", "stopped"}:
            self._recent.insert(0, item.to_dict())
            del self._recent[30:]
