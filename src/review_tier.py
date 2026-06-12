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


def _min_approve_override() -> int | None:
    """iter 053 拍板④: ``WRITE_REVIEW_MIN_APPROVE`` 单独覆写票数闸。

    052 段二实测：tier=mid 的 4/5 票对 premise 书偏严——首稿 panel ≥7.94 全
    过分数线仍被 2/5 票打回（首过率 2/7，每次边界重试 ≈¥0.6）。整体换
    ``--tier low`` 会把分数线连降到 6.5，违背"不影响质量"前提；这个覆写只
    动 min_approve_count，min_panel_score 仍随 tier。

    缺省/空/非法值回退 tier 预设（铁律④回退契约）；合法值夹紧 1-5。
    """
    raw = os.getenv("WRITE_REVIEW_MIN_APPROVE", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return max(1, min(5, value))


def thresholds_for(tier: str | None = None) -> TierThresholds:
    base = _THRESHOLDS[resolve_tier(tier)]
    override = _min_approve_override()
    if override is None:
        return base
    return TierThresholds(
        min_approve_count=override, min_panel_score=base.min_panel_score
    )


def thresholds_snapshot(tier: str | None = None) -> dict[str, float | int]:
    thresholds = thresholds_for(tier)
    return {
        "min_approve_count": thresholds.min_approve_count,
        "min_panel_score": thresholds.min_panel_score,
    }
