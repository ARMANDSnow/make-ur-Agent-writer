"""iter 025: aggregate per-chapter ``*.meta.json`` files into one blob.

The dashboard ``GET /api/workspace/<name>/reviews`` endpoint returns a JSON
that the browser can render directly. We deliberately keep the full
``agent_reviews[*]`` (with ``issues`` / ``suggestions`` / ``comparison_checklist``)
and the top-level ``rewrite_suggestions`` list produced by iter 024's
advisor — collapsing happens client-side, not here, so power users can
read everything without a second round-trip.

Filtering rule: we only treat ``chapter_NN.meta.json`` (two-digit) files
as canonical chapters. Demo / backup variants like
``chapter_01_iter023_5plus1_demo.meta.json`` carry a trailing suffix and
are intentionally skipped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


# Match ``chapter_NN.meta.json`` where NN is 2+ digits. The 2-digit
# minimum keeps the file name shape stable (``chapter_01`` not
# ``chapter_1``), while 3+ digits are accepted so iter 027+ capstone runs
# past chapter 99 stay visible. Anything with an additional suffix
# (``chapter_01_iter023_demo.meta.json``, ``chapter_01.meta_backup.json``,
# etc.) is still skipped so demos and backups don't pollute the dashboard.
_CHAPTER_META_RE = re.compile(r"^chapter_(\d{2,})\.meta\.json$")


def aggregate_reviews(drafts_dir: Path) -> Dict[str, Any]:
    """Load every canonical ``chapter_NN.meta.json`` under ``drafts_dir``
    and return ``{"chapters": [...], "stats": {...}}``.

    Missing or unreadable directories return an empty result rather than
    raising — that keeps the API honest about "no chapters yet" without
    forcing the caller to special-case fresh workspaces.
    """

    chapters: List[Dict[str, Any]] = []
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return {"chapters": [], "stats": _empty_stats()}

    for path in sorted(drafts_dir.iterdir()):
        if not path.is_file():
            continue
        match = _CHAPTER_META_RE.match(path.name)
        if match is None:
            continue
        chapter_no = int(match.group(1))
        try:
            with path.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        chapters.append(_normalize_chapter(chapter_no, meta))

    chapters.sort(key=lambda c: c["chapter"])
    return {"chapters": chapters, "stats": _compute_stats(chapters)}


def _normalize_chapter(chapter_no: int, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Project the meta.json down to dashboard-relevant fields while
    keeping each ``agent_reviews`` entry verbatim (full ``issues`` and
    ``suggestions``). The advisor list comes from the top-level
    ``rewrite_suggestions`` field that iter 024's reviewer pipeline
    started populating.
    """

    return {
        "chapter": chapter_no,
        "verdict": meta.get("verdict"),
        "rewrite_count": meta.get("rewrite_count", 0),
        "rewrite_round": meta.get("rewrite_round", 0),
        "chinese_char_count": meta.get("chinese_char_count", 0),
        "needs_human_review": bool(meta.get("needs_human_review", False)),
        "polish_applied": bool(meta.get("polish_applied", False)),
        # ``dict.get(k, [])`` only returns the default when the key is
        # MISSING; if the key is present but the value is JSON ``null``,
        # we get None back and ``list(None)`` is a TypeError. Use
        # ``... or []`` so an explicit ``null`` becomes an empty list
        # — the reviewer / advisor pipeline can short-circuit a section
        # by writing null and we should treat that as "no data".
        "lint_issues": list(meta.get("lint_issues") or []),
        "agent_reviews": list(meta.get("agent_reviews") or []),
        "rewrite_suggestions": list(meta.get("rewrite_suggestions") or []),
    }


def _empty_stats() -> Dict[str, Any]:
    return {
        "total": 0,
        "accepted": 0,
        "rewrite_max": 0,
        "needs_human_review": 0,
        "advisor_suggestions_total": 0,
    }


def _compute_stats(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    accepted = sum(1 for c in chapters if c.get("verdict") == "Approve")
    rewrite_max = max((c.get("rewrite_count", 0) for c in chapters), default=0)
    needs_review = sum(1 for c in chapters if c.get("needs_human_review"))
    advisor_total = sum(len(c.get("rewrite_suggestions", [])) for c in chapters)
    return {
        "total": len(chapters),
        "accepted": accepted,
        "rewrite_max": rewrite_max,
        "needs_human_review": needs_review,
        "advisor_suggestions_total": advisor_total,
    }
