from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ChatActionType = Literal["create_agent_task", "update_task_progress"]


@dataclass(frozen=True)
class ChatActionIntent:
    action: ChatActionType
    title: str | None = None
    project: str = "Nexus AI-PC"
    task_id: int | None = None
    progress_percent: int | None = None
    progress_note: str | None = None


_CREATE_TASK = re.compile(
    r"^\s*(?:请|麻烦|请你|麻烦你|帮我)?\s*"
    r"(?:创建|新建|添加|记录)\s*(?:一个|一条)?\s*"
    r"(?:(?:Agent|代理|编程|开发)\s*)?任务\s*[：:,，]?\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
_TASK_ID = re.compile(r"任务\s*#?\s*(?P<task_id>\d+)", re.IGNORECASE)
_PROGRESS_INTENT = re.compile(r"(?:更新|设置|改成|改为|同步).{0,12}进度|进度.{0,12}(?:更新|设置|改成|改为|同步)")
_PROGRESS_VALUE = re.compile(r"(?P<percent>\d{1,3})\s*(?:%|％|百分比?)")
_PROGRESS_AFTER = re.compile(r"(?:进度|更新为|设置为|改成|改为)\D{0,8}(?P<percent>\d{1,3})(?:\s*(?:%|％))?")
_NOTE = re.compile(r"(?:备注|说明|进展)\s*[：:]\s*(?P<note>.+?)\s*$")
_PROJECT = re.compile(r"(?:^|[，,；;])\s*项目\s*[：:]\s*(?P<project>[^，,；;]+)")

_WEB_SEARCH_PATTERNS = (
    re.compile(
        r"^\s*(?:请|麻烦|请你|麻烦你|帮我)?\s*"
        r"(?:联网|上网|网络|网上|互联网)\s*(?:搜索|检索|查找|查询|搜一下|查一下|搜|查)"
        r"\s*[：:,，]?\s*(?P<query>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|麻烦|请你|麻烦你|帮我)?\s*"
        r"(?:搜索|检索|查找|查询|搜一下|查一下)\s*(?:网络|网页|互联网|网上)"
        r"\s*[：:,，]?\s*(?P<query>.+?)\s*$",
        re.IGNORECASE,
    ),
)

_AUTO_WEB_SEARCH_KEYWORDS = (
    "最新",
    "近期",
    "今年",
    "当前版本",
    "截至",
    "现行",
    "事实核查",
    "查证",
    "研究证据",
    "是否有新",
    "争议",
)
_SENSITIVE_WEB_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/(?:Users|home)/", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|gho|github_pat)-?[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)1\d{10}(?!\d)"),
)


def parse_chat_actions(message: str) -> list[ChatActionIntent]:
    """Parse explicit, low-risk local commands from the latest user message."""

    text = message.strip()
    if not text:
        return []

    progress = _parse_progress_update(text)
    if progress is not None:
        return [progress]

    created = _parse_task_create(text)
    return [created] if created is not None else []


def extract_web_search_query(message: str) -> str | None:
    """Return a query only when the latest message begins with an explicit web-search command."""

    for pattern in _WEB_SEARCH_PATTERNS:
        matched = pattern.match(message)
        if not matched:
            continue
        query = matched.group("query").strip(" \t\r\n。.!！?？")
        if 2 <= len(query) <= 500:
            return query
    return None


def auto_web_search_query(message: str, *, local_evidence_count: int = 0) -> str | None:
    """Select a generic, verification-oriented query without exporting likely private text."""

    text = " ".join(message.split()).strip(" 。.!！?？")
    if not 2 <= len(text) <= 500:
        return None
    if any(pattern.search(text) for pattern in _SENSITIVE_WEB_PATTERNS):
        return None
    if not any(keyword in text for keyword in _AUTO_WEB_SEARCH_KEYWORDS):
        return None
    freshness = any(keyword in text for keyword in ("最新", "近期", "今年", "截至", "当前版本"))
    if local_evidence_count > 0 and not freshness:
        return None
    return text


def _parse_task_create(text: str) -> ChatActionIntent | None:
    matched = _CREATE_TASK.match(text)
    if not matched:
        return None
    title = matched.group("title").strip(" \t\r\n。.!！")
    project = "Nexus AI-PC"
    project_match = _PROJECT.search(title)
    if project_match:
        project = project_match.group("project").strip()
        title = _PROJECT.sub("", title).strip(" \t\r\n，,；;。.!！")
    if not title or len(title) > 2000 or not project or len(project) > 200:
        return None
    return ChatActionIntent(action="create_agent_task", title=title, project=project)


def _parse_progress_update(text: str) -> ChatActionIntent | None:
    if not _PROGRESS_INTENT.search(text):
        return None
    task_match = _TASK_ID.search(text)
    percent_match = _PROGRESS_VALUE.search(text) or _PROGRESS_AFTER.search(text)
    if not task_match or not percent_match:
        return None
    percent = int(percent_match.group("percent"))
    if not 0 <= percent <= 100:
        return None
    note_match = _NOTE.search(text)
    note = note_match.group("note").strip() if note_match else None
    if note and len(note) > 2000:
        return None
    return ChatActionIntent(
        action="update_task_progress",
        task_id=int(task_match.group("task_id")),
        progress_percent=percent,
        progress_note=note,
    )
