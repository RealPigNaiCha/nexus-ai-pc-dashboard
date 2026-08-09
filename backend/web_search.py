from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class WebSearchError(RuntimeError):
    """Raised when the optional metasearch provider cannot return usable results."""


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str

    def as_evidence(self) -> dict[str, object]:
        return {
            "source_type": "web",
            "title": self.title,
            "url": self.url,
            "source_path": self.url,
            "snippet": self.snippet,
            "search_mode": "web",
        }


class WebSearchService:
    def __init__(self, *, timeout_seconds: float = 8.0) -> None:
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 20.0))

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, object]]:
        normalized_query = " ".join(query.split())
        if not 2 <= len(normalized_query) <= 500:
            raise WebSearchError("Web search query must contain 2 to 500 characters")
        bounded_limit = max(1, min(int(limit), 8))
        try:
            from ddgs import DDGS
            from ddgs.exceptions import DDGSException
        except ImportError as error:
            raise WebSearchError("Web search dependency is unavailable") from error
        try:
            raw_results: list[dict[str, Any]] = DDGS(timeout=self.timeout_seconds).text(
                normalized_query,
                region="cn-zh",
                safesearch="moderate",
                max_results=bounded_limit,
            )
        except (DDGSException, OSError, RuntimeError, TimeoutError) as error:
            raise WebSearchError("Web search is temporarily unavailable") from error

        results: list[dict[str, object]] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            url = _safe_result_url(str(item.get("href") or item.get("url") or ""))
            if not url or url in seen_urls:
                continue
            title = _clean_text(str(item.get("title") or "未命名网页"), 300)
            snippet = _clean_text(str(item.get("body") or item.get("snippet") or ""), 800)
            seen_urls.add(url)
            results.append(WebSearchResult(title=title, url=url, snippet=snippet).as_evidence())
            if len(results) >= bounded_limit:
                break
        return results


def _clean_text(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _safe_result_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if host == "localhost" or host.endswith(".localhost"):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return parsed.geturl()
    except ValueError:
        return None
