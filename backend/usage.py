from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database


BUDGET_SETTING_KEY = "usage.monthly_budget_usd"
DEFAULT_INPUT_PER_MILLION = 0.50
DEFAULT_OUTPUT_PER_MILLION = 1.50

# (provider, model substring, input USD per 1M tokens, output USD per 1M tokens)
# Values are approximate list prices and are only used for the local budget estimate.
PRICING_RULES: tuple[tuple[str, str, float, float], ...] = (
    ("openai", "gpt-4o-mini", 0.15, 0.60),
    ("openai", "gpt-4o", 2.50, 10.00),
    ("openai", "gpt-4.1-mini", 0.40, 1.60),
    ("openai", "gpt-4.1", 2.00, 8.00),
    ("openai", "o4-mini", 1.10, 4.40),
    ("openai", "o3", 2.00, 8.00),
    ("deepseek", "deepseek-reasoner", 0.55, 2.19),
    ("deepseek", "deepseek-chat", 0.27, 1.10),
    ("deepseek", "deepseek-v", 0.27, 1.10),
    ("anthropic", "claude-3-5-haiku", 0.80, 4.00),
    ("anthropic", "claude-3-5-sonnet", 3.00, 15.00),
    ("anthropic", "claude-3-7-sonnet", 3.00, 15.00),
    ("google-gemini", "gemini-2.5-flash", 0.30, 2.50),
    ("google-gemini", "gemini-2.5-pro", 1.25, 10.00),
    ("alibaba-bailian", "qwen", 0.40, 1.20),
)


def estimate_cost_usd(
    provider: str | None,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float:
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    if prompt_tokens == 0 and completion_tokens == 0:
        return 0.0
    provider_key = (provider or "").casefold()
    model_key = (model or "").casefold()
    input_rate = DEFAULT_INPUT_PER_MILLION
    output_rate = DEFAULT_OUTPUT_PER_MILLION
    for rule_provider, rule_model, input_price, output_price in PRICING_RULES:
        if provider_key == rule_provider and rule_model in model_key:
            input_rate = input_price
            output_rate = output_price
            break
    cost = (
        prompt_tokens / 1_000_000 * input_rate
        + completion_tokens / 1_000_000 * output_rate
    )
    return round(cost, 6)


def current_month_start() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat(timespec="seconds")


def read_monthly_budget(database: Database) -> float:
    row = database.query_one(
        "SELECT value FROM settings WHERE key = ?",
        (BUDGET_SETTING_KEY,),
    )
    if not row:
        return 0.0
    try:
        value = float(row["value"])
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value)


def save_monthly_budget(database: Database, amount: float) -> float:
    amount = max(0.0, float(amount))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    database.execute(
        """
        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (BUDGET_SETTING_KEY, f"{amount:.6f}", now),
    )
    return amount


def month_usage(database: Database, *, since: str | None = None) -> dict[str, Any]:
    since = since or current_month_start()
    row = database.query_one(
        """
        SELECT
            COUNT(*) AS calls,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd
        FROM model_calls
        WHERE status = 'success' AND created_at >= ?
        """,
        (since,),
    )
    by_operation = database.query_all(
        """
        SELECT
            operation,
            source,
            COUNT(*) AS calls,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd
        FROM model_calls
        WHERE status = 'success' AND created_at >= ?
        GROUP BY operation, source
        ORDER BY cost_usd DESC, calls DESC
        """,
        (since,),
    )
    sessions = database.query_all(
        """
        SELECT
            session_id,
            COUNT(*) AS calls,
            COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS cost_usd,
            MAX(created_at) AS last_used_at
        FROM model_calls
        WHERE status = 'success' AND session_id IS NOT NULL AND created_at >= ?
        GROUP BY session_id
        ORDER BY last_used_at DESC
        LIMIT 20
        """,
        (since,),
    )
    return {
        "month": since[:7],
        "budget_usd": read_monthly_budget(database),
        "calls": int(row["calls"]),
        "prompt_tokens": int(row["prompt_tokens"]),
        "completion_tokens": int(row["completion_tokens"]),
        "total_tokens": int(row["total_tokens"]),
        "spent_usd": round(float(row["cost_usd"]), 6),
        "by_operation": by_operation,
        "sessions": sessions,
    }


def budget_exceeded(database: Database) -> tuple[bool, float, float]:
    budget = read_monthly_budget(database)
    spent = month_usage(database)["spent_usd"]
    return (budget > 0 and spent >= budget), spent, budget
