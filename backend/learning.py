from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fsrs import Card, Rating, Scheduler


SCHEDULER = Scheduler(desired_retention=0.9, enable_fuzzing=False)


@dataclass(frozen=True)
class LearningReview:
    mastery: float
    status: str
    rating: int
    due_at: str
    card_json: str
    review_log_json: str


def rating_for_attempt(score: float, hints_used: int = 0) -> Rating:
    adjusted = max(0.0, min(1.0, score - min(hints_used, 4) * 0.08))
    if adjusted < 0.5:
        return Rating.Again
    if adjusted < 0.75:
        return Rating.Hard
    if adjusted < 0.93:
        return Rating.Good
    return Rating.Easy


def update_mastery(current: float, score: float, attempt_count: int, hints_used: int = 0) -> float:
    adjusted = max(0.0, min(1.0, score - min(hints_used, 4) * 0.08)) * 100
    evidence_weight = max(0.16, 0.36 / (1 + attempt_count * 0.08))
    return round(max(0.0, min(100.0, current + (adjusted - current) * evidence_weight)), 1)


def mastery_status(mastery: float) -> str:
    if mastery >= 80:
        return "stable"
    if mastery >= 45:
        return "learning"
    if mastery > 0:
        return "review"
    return "not_started"


def review_concept(
    concept: dict[str, Any],
    *,
    score: float,
    hints_used: int = 0,
    review_datetime: datetime | None = None,
    duration_seconds: int | None = None,
) -> LearningReview:
    reviewed_at = review_datetime or datetime.now(timezone.utc)
    if reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)

    card_payload = concept.get("fsrs_card_json")
    if card_payload:
        card = Card.from_dict(json.loads(card_payload))
    else:
        card = Card(card_id=int(concept["id"]), due=reviewed_at)

    rating = rating_for_attempt(score, hints_used)
    updated_card, review_log = SCHEDULER.review_card(
        card,
        rating,
        review_datetime=reviewed_at,
        review_duration=duration_seconds * 1000 if duration_seconds is not None else None,
    )
    mastery = update_mastery(
        float(concept.get("mastery") or 0),
        score,
        int(concept.get("attempt_count") or 0),
        hints_used,
    )
    return LearningReview(
        mastery=mastery,
        status=mastery_status(mastery),
        rating=int(rating),
        due_at=updated_card.due.astimezone(timezone.utc).isoformat(timespec="seconds"),
        card_json=json.dumps(updated_card.to_dict(), ensure_ascii=True, separators=(",", ":")),
        review_log_json=json.dumps(review_log.to_dict(), ensure_ascii=True, separators=(",", ":")),
    )
