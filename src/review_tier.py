from __future__ import annotations

import os
from dataclasses import dataclass


TIER_HIGH = "high"
TIER_MID = "mid"
TIER_LOW = "low"
DEFAULT_TIER = TIER_MID


@dataclass(frozen=True)
class TierThresholds:
    min_approve_count: int
    min_panel_score: float


_THRESHOLDS = {
    TIER_HIGH: TierThresholds(min_approve_count=5, min_panel_score=8.5),
    TIER_MID: TierThresholds(min_approve_count=4, min_panel_score=7.5),
    TIER_LOW: TierThresholds(min_approve_count=3, min_panel_score=6.5),
}


def resolve_tier(value: str | None = None) -> str:
    raw = value if value is not None else os.getenv("WRITE_REVIEW_TIER", "")
    tier = str(raw or DEFAULT_TIER).strip().lower()
    if tier not in _THRESHOLDS:
        allowed = ", ".join(sorted(_THRESHOLDS))
        raise ValueError(f"invalid WRITE_REVIEW_TIER={raw!r}; expected one of: {allowed}")
    return tier


def thresholds_for(tier: str | None = None) -> TierThresholds:
    return _THRESHOLDS[resolve_tier(tier)]


def thresholds_snapshot(tier: str | None = None) -> dict[str, float | int]:
    thresholds = thresholds_for(tier)
    return {
        "min_approve_count": thresholds.min_approve_count,
        "min_panel_score": thresholds.min_panel_score,
    }
