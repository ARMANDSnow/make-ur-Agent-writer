"""Aggregate chapter_plan.json + outline.md + decisions.json.

Pure read-only aggregation for the Plan viewer page. No LLM calls, no
writes. Caller enters the workspace context.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import paths
from ..utils import read_json_optional


def collect_plan() -> Dict[str, Any]:
    plan = read_json_optional(paths.chapter_plan_path(), {})
    if not isinstance(plan, dict):
        plan = {}
    decisions = read_json_optional(paths.debate_decisions_path(), {})
    if not isinstance(decisions, dict):
        decisions = {}
    outline_md = ""
    outline_path = paths.outline_path()
    if outline_path.exists():
        try:
            outline_md = outline_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            outline_md = ""
    return {
        "plan": plan,
        "outline_md": outline_md,
        "decisions": decisions,
        "draft_chapters": _draft_chapter_numbers(),
        "draft_verdicts": _draft_verdicts(),
    }


def _draft_chapter_numbers() -> List[int]:
    drafts = paths.drafts_dir()
    if not drafts.exists():
        return []
    nums: List[int] = []
    for md in drafts.glob("chapter_*.md"):
        try:
            nums.append(int(md.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(nums)


def _draft_verdicts() -> Dict[str, str]:
    drafts = paths.drafts_dir()
    if not drafts.exists():
        return {}
    out: Dict[str, str] = {}
    for md in drafts.glob("chapter_*.md"):
        try:
            num = int(md.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        meta = read_json_optional(md.with_suffix(".meta.json"), {})
        if isinstance(meta, dict) and meta.get("verdict"):
            out[str(num)] = str(meta["verdict"])
    return out
