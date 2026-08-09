from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from .database import Database


def improvement_proposal_payload(row: dict[str, Any]) -> dict[str, object]:
    try:
        evidence = json.loads(str(row.get("evidence_json") or "{}"))
    except ValueError:
        evidence = {}
    return {
        "id": int(row["id"]),
        "fingerprint": row["fingerprint"],
        "signal_type": row["signal_type"],
        "title": row["title"],
        "rationale": row["rationale"],
        "priority": row["priority"],
        "evidence": evidence if isinstance(evidence, dict) else {},
        "status": row["status"],
        "agent_task_id": row.get("agent_task_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def collect_improvement_signals(database: Database) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    model_rows = database.query_all(
        """
        SELECT
            operation,
            COUNT(*) AS total_count,
            SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS failure_count,
            GROUP_CONCAT(DISTINCT error_code) AS error_codes
        FROM model_calls
        WHERE julianday(created_at) >= julianday('now', '-30 days')
        GROUP BY operation
        HAVING SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) >= 2
        ORDER BY failure_count DESC, operation
        """
    )
    for row in model_rows:
        total = int(row["total_count"])
        failures = int(row["failure_count"])
        signals.append(
            {
                "type": "model_failure_rate",
                "target": row["operation"],
                "priority": "high" if total and failures / total >= 0.5 else "medium",
                "evidence": {
                    "window_days": 30,
                    "total_count": total,
                    "failure_count": failures,
                    "failure_rate": round(failures / total, 4) if total else 0,
                    "error_codes": sorted(filter(None, str(row.get("error_codes") or "").split(","))),
                },
            }
        )

    audit_rows = database.query_all(
        """
        SELECT category, action, result, COUNT(*) AS failure_count
        FROM audit_events
        WHERE result != 'success'
          AND julianday(created_at) >= julianday('now', '-30 days')
        GROUP BY category, action, result
        HAVING COUNT(*) >= 3
        ORDER BY failure_count DESC, category, action
        """
    )
    for row in audit_rows:
        signals.append(
            {
                "type": "repeated_operation_failure",
                "target": f"{row['category']}/{row['action']}",
                "priority": "medium",
                "evidence": {
                    "window_days": 30,
                    "failure_count": int(row["failure_count"]),
                    "result": row["result"],
                },
            }
        )
    return signals


def proposal_for_signal(signal: dict[str, object]) -> dict[str, object]:
    canonical = json.dumps(signal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    target = str(signal["target"])
    signal_type = str(signal["type"])
    if signal_type == "model_failure_rate":
        title = f"调查模型调用失败：{target}"
        rationale = "近 30 天该模型操作出现重复失败；需要复现错误、评估回退策略并补充测试。"
    else:
        title = f"调查重复操作失败：{target}"
        rationale = "审计记录显示同类操作重复失败；需要定位共同原因并减少重复人工处理。"
    return {
        "fingerprint": fingerprint,
        "signal_type": signal_type,
        "title": title,
        "rationale": rationale,
        "priority": signal["priority"],
        "evidence": signal["evidence"],
    }


def scan_improvements(database: Database) -> dict[str, object]:
    signals = collect_improvement_signals(database)
    proposals: list[dict[str, Any]] = []
    created_count = 0
    for signal in signals:
        proposal = proposal_for_signal(signal)
        saved, created = database.save_improvement_proposal(
            fingerprint=str(proposal["fingerprint"]),
            signal_type=str(proposal["signal_type"]),
            title=str(proposal["title"]),
            rationale=str(proposal["rationale"]),
            priority=str(proposal["priority"]),
            evidence=cast(dict[str, Any], proposal["evidence"]),
        )
        proposals.append(improvement_proposal_payload(saved))
        created_count += int(created)
    return {
        "signal_count": len(signals),
        "created_count": created_count,
        "proposals": proposals,
    }
