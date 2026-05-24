"""Iter 019: per-chapter status helper for the unattended write loop.

write_book.sh used to detect "chapter done" with a single ``[ -f
chapter_NN.md ]`` test, which silently accepted lint-blocked and
reviewer-rejected drafts as if they were approved. iter 019 centralises
the success / failure / needs-rewrite triage here so the shell script
can branch on a single JSON answer instead of grepping meta files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .utils import read_json


def chapter_status(chapter_no: int, drafts_dir: Path) -> Dict[str, Any]:
    """Return the post-write triage signals for one chapter.

    The returned dict always has the same shape::

        {
          "chapter_no": int,
          "exists": bool,             # chapter_NN.md present
          "approved": bool,           # verdict == Approve AND no failure marker
          "needs_review": bool,       # meta.needs_human_review == True
          "failure": bool,            # chapter_NN.failure.json present
          "verdict": str | None,      # meta.verdict (may be None when meta missing)
          "rewrite_count": int,       # meta.rewrite_count (0 when missing)
        }

    Pure I/O of three known file paths — no LLM, no network.
    """

    drafts_dir = Path(drafts_dir)
    md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
    meta_path = drafts_dir / f"chapter_{chapter_no:02d}.meta.json"
    failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"

    exists = md_path.exists()
    failure = failure_path.exists()
    meta: Dict[str, Any] = read_json(meta_path, {}) if meta_path.exists() else {}

    verdict: Optional[str] = None
    if isinstance(meta, dict):
        raw_verdict = meta.get("verdict")
        if isinstance(raw_verdict, str) and raw_verdict:
            verdict = raw_verdict

    needs_review = bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False
    rewrite_count = 0
    if isinstance(meta, dict):
        raw_rc = meta.get("rewrite_count", 0)
        try:
            rewrite_count = int(raw_rc)
        except (TypeError, ValueError):
            rewrite_count = 0

    approved = (
        exists
        and not failure
        and not needs_review
        and verdict == "Approve"
    )

    return {
        "chapter_no": int(chapter_no),
        "exists": exists,
        "approved": approved,
        "needs_review": needs_review,
        "failure": failure,
        "verdict": verdict,
        "rewrite_count": rewrite_count,
    }
