"""Model routing rules: task -> preferred role resolution with user override.

Each generation entry point can accept the pseudo-role ``auto``. The router
keeps a per-task rule in SQLite settings:

- ``mode``: ``auto`` (heuristic), or a fixed ``reasoning`` / ``fast`` role.
- ``prefer_low_cost``: when the monthly budget is nearly exhausted, prefer
  ``fast`` even for complex questions.

An explicit ``reasoning`` or ``fast`` request always wins (user override).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .database import Database, utc_now
from .usage import month_usage, read_monthly_budget


ROUTING_TASKS: dict[str, str] = {
    "chat": "统一 AI 对话",
    "openai_compat": "兼容对话（NextChat 等）",
    "paperqa": "论文问答",
    "deeptutor": "DeepTutor",
    "generate": "最小生成调用",
}

VALID_MODES = ("auto", "reasoning", "fast")
DEFAULT_MODE = "auto"

ROUTING_PREFIX = "routing.task."

COMPLEXITY_KEYWORDS = (
    "为什么",
    "比较",
    "对比",
    "分析",
    "设计",
    "推导",
    "证明",
    "批判",
    "综述",
    "综合",
    "冲突",
    "证据",
    "解释",
    "差异",
    "优缺点",
    "是否",
    "假设",
    "反例",
    "评估",
    "评价",
    "研究",
    "方案",
    "影响",
)

COMPLEXITY_THRESHOLD = 2
LOW_BUDGET_REMAINING_RATIO = 0.25


def _normalized_mode(value: object) -> str:
    mode = str(value or DEFAULT_MODE).strip().lower()
    return mode if mode in VALID_MODES else DEFAULT_MODE


def _normalized_bool(value: object) -> bool:
    return str(value or "0").strip().lower() in {"1", "true", "yes", "on"}


def get_routing_rules(database: Database) -> list[dict[str, object]]:
    """Return the current routing rule for every known task."""
    rows = database.query_all(
        "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
        (ROUTING_PREFIX + "%",),
    )
    values = {row["key"]: row["value"] for row in rows}
    rules: list[dict[str, object]] = []
    for task, label in ROUTING_TASKS.items():
        rules.append(
            {
                "task": task,
                "label": label,
                "mode": _normalized_mode(values.get(f"{ROUTING_PREFIX}{task}.mode")),
                "prefer_low_cost": _normalized_bool(
                    values.get(f"{ROUTING_PREFIX}{task}.prefer_low_cost")
                ),
            }
        )
    return rules


def save_routing_rule(
    database: Database,
    *,
    task: str,
    mode: str,
    prefer_low_cost: bool,
) -> dict[str, object]:
    """Persist one routing rule and record an audit event."""
    if task not in ROUTING_TASKS:
        raise LookupError("Routing task not found")
    normalized_mode = _normalized_mode(mode)
    if normalized_mode != mode:
        raise ValueError("Unsupported routing mode")
    now = utc_now()
    database.execute_many(
        """
        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        [
            (f"{ROUTING_PREFIX}{task}.mode", normalized_mode, now),
            (
                f"{ROUTING_PREFIX}{task}.prefer_low_cost",
                "1" if prefer_low_cost else "0",
                now,
            ),
        ],
    )
    database.audit("routing", "update_rule", task)
    return next(rule for rule in get_routing_rules(database) if rule["task"] == task)


def complexity_score(text: str | None) -> int:
    """Heuristic complexity used by ``auto`` mode."""
    value = (text or "").strip()
    if not value:
        return 0
    score = sum(1 for keyword in COMPLEXITY_KEYWORDS if keyword in value)
    if len(value) >= 120:
        score += 1
    if value.count("?") + value.count("？") >= 2:
        score += 1
    return score


def remaining_budget_ratio(database: Database) -> float | None:
    """Return remaining budget ratio (0..1), or None when no budget is set."""
    budget = read_monthly_budget(database)
    if budget <= 0:
        return None
    spent = month_usage(database)["spent_usd"]
    return max(0.0, 1.0 - spent / budget)


def resolve_role(
    database: Database,
    task: str,
    requested_role: str | None,
    *,
    text: str | None = None,
) -> str:
    """Resolve an effective ``reasoning`` / ``fast`` role.

    An explicit role always wins; ``auto`` or an unknown value falls through
    to the per-task routing rule.
    """
    requested = (requested_role or "").strip().lower()
    if requested in {"reasoning", "fast"}:
        return requested
    rules = {rule["task"]: rule for rule in get_routing_rules(database)}
    rule = rules.get(task) or {"mode": DEFAULT_MODE, "prefer_low_cost": False}
    mode = str(rule.get("mode") or DEFAULT_MODE)
    if mode in {"reasoning", "fast"}:
        return mode
    if rule.get("prefer_low_cost"):
        remaining = remaining_budget_ratio(database)
        if remaining is not None and remaining < LOW_BUDGET_REMAINING_RATIO:
            return "fast"
    return "reasoning" if complexity_score(text) >= COMPLEXITY_THRESHOLD else "fast"


def routing_rules_payload(rules: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    return {"rules": [dict(rule) for rule in rules]}
