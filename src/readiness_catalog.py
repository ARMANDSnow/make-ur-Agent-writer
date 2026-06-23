"""Single source of truth for readiness-blocker presentation (iter063 Part C).

Three catalogs used to drift independently and were only kept in sync by tests:

  * ``book_runner._primary_blocker`` labels + ``_blocker_kind`` (core)
  * ``web/errors.py`` ``_READINESS`` + ``readiness_kind`` (web error cards)
  * ``web/static.py`` ``CTA_ACTIONS`` / ``readinessReasonText`` (frontend JS)

They are now derived from ``KINDS`` + ``classify()`` here. This module lives at
the **core** (``src/``) level and imports only ``typing`` so ``book_runner`` can
use it without a backwards core→web dependency; ``web/errors.py`` builds its
cards from it, and the frontend reads an injected JSON copy
(``window.READINESS_CATALOG``) so all three render the same text.

Per-kind record:
  * ``label``      — short human title (card title / frontend reason label)
  * ``cause``      — one-line explanation (card cause / frontend hint)
  * ``cta_action`` — frontend ``bindCtaActions`` dispatch key for the next step
  * ``cta_label``  — button text for that step
"""

from __future__ import annotations

from typing import Dict

# kind -> presentation. Order is documentation only.
KINDS: Dict[str, Dict[str, str]] = {
    "start_point_missing": {
        "label": "未设置续写起点",
        "cause": "先选定从原作哪一章之后开始续写，之后才能生成章节计划。",
        "cta_action": "scroll_to_start_point",
        "cta_label": "去设置起点",
    },
    "outline_missing": {
        "label": "缺少全书大纲",
        "cause": "先生成或检查全书走向，再进入章节续写。",
        "cta_action": "go_plan",
        "cta_label": "去计划页",
    },
    "outline_stale": {
        # iter063 A1: existing debate outline built against a different start
        # point — regenerating the plan is blocked on purpose (052 accident).
        "label": "大纲与当前起点不一致",
        "cause": "现有大纲是按之前的起点生成的，需要先重新生成大纲，再规划章节，已写好的正文不受影响。",
        "cta_action": "go_plan",
        "cta_label": "去计划页重新生成大纲",
    },
    "chapter_plan_missing": {
        "label": "缺少章节计划",
        "cause": "续写需要本章计划，可先用默认目标章数生成。",
        "cta_action": "run_plan_chapters",
        "cta_label": "生成章节计划",
    },
    "chapter_plan_invalid": {
        "label": "章节计划文件损坏",
        "cause": "章节计划文件无法读取，重新生成即可修复，已写好的正文不受影响。",
        "cta_action": "run_plan_chapters",
        "cta_label": "重新生成计划",
    },
    "retry_exhausted": {
        "label": "已有草稿未通过",
        "cause": "本章已有草稿但未达通过门槛，可查看后重试。",
        "cta_action": "retry_write_book",
        "cta_label": "查看并重试",
    },
    "preflight_failed": {
        "label": "工程预检未通过",
        "cause": "上游配置或数据预检没通过，先看诊断再续写。",
        "cta_action": "show_diagnostics",
        "cta_label": "查看诊断",
    },
    "foreshadowing_overdue": {
        "label": "有 must-resolve 伏笔超期未回收",
        "cause": "存在标记为必须回收的伏笔超期未回收。",
        "cta_action": "show_diagnostics",
        "cta_label": "查看诊断",
    },
    "unknown": {
        "label": "续写入口受阻",
        "cause": "续写前置条件未满足，查看诊断了解详情。",
        "cta_action": "show_diagnostics",
        "cta_label": "查看诊断",
    },
}

DEFAULT_KIND = "unknown"


def classify(blocker: str) -> str:
    """Map a raw readiness-blocker string to a known kind.

    Supersedes the (previously duplicated) ``book_runner._blocker_kind`` and
    ``errors.readiness_kind``. Exact catalog keys pass through; prefixed /
    substring variants (``chapter_plan:ch3``, ``preflight:models``,
    ``foreshadowing_must_resolve_overdue:3``, the raw ``stale debate
    outline (…)`` message, …) classify to their kind.
    """
    b = blocker or ""
    if b in KINDS:
        return b
    if b.startswith("chapter_plan:") or "plan_item_missing" in b:
        return "chapter_plan_missing"
    if b.startswith("outline_missing") or "outline_missing" in b:
        return "outline_missing"
    if "stale debate outline" in b:
        return "outline_stale"
    if "retry_exhausted" in b or "existing_output_not_strict_approved" in b:
        return "retry_exhausted"
    if b.startswith("preflight:"):
        return "preflight_failed"
    if b.startswith("foreshadowing_must_resolve_overdue") or b.startswith("foreshadowing_gate_error"):
        return "foreshadowing_overdue"
    return DEFAULT_KIND


def fields_for(kind: str) -> Dict[str, str]:
    """Return the presentation record for a kind, degrading to ``unknown``."""
    return KINDS.get(kind, KINDS[DEFAULT_KIND])
