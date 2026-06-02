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

from .utils import read_json, sha256_file


def chapter_status(
    chapter_no: int,
    drafts_dir: Path,
    *,
    validate_context: bool = False,
    require_start_point: bool = False,
    require_plan: bool = False,
    require_external_review: bool = False,
    expected_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
    strict_failures: list[str] = []

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
    draft_sha = ""
    if exists:
        try:
            draft_sha = sha256_file(md_path)
        except OSError:
            strict_failures.append("draft_hash_unreadable")

    if validate_context:
        if not isinstance(meta, dict) or not meta:
            strict_failures.append("meta_missing")
        run_context = meta.get("run_context") if isinstance(meta, dict) else None
        if not isinstance(run_context, dict):
            strict_failures.append("legacy_missing_context")
            run_context = {}
        if bool(meta.get("human_review")) or bool(meta.get("human_review_required")):
            strict_failures.append("human_review_present")
        if require_start_point and not run_context.get("start_point_fingerprint"):
            strict_failures.append("start_point_missing")
        if require_plan and not run_context.get("chapter_plan_item_fingerprint"):
            strict_failures.append("plan_missing")
        if draft_sha and meta.get("draft_sha256") and meta.get("draft_sha256") != draft_sha:
            strict_failures.append("draft_hash_mismatch")
        elif draft_sha and not meta.get("draft_sha256"):
            strict_failures.append("draft_hash_missing")
        if expected_context:
            for key in (
                "start_chapter_id",
                "start_point_fingerprint",
                "chapter_plan_item_fingerprint",
                "plan_fingerprint",
            ):
                expected = str(expected_context.get(key) or "")
                actual = str(run_context.get(key) or "")
                if expected and actual != expected:
                    strict_failures.append(f"{key}_mismatch")
        if require_external_review:
            review_path = drafts_dir.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json"
            if not review_path.exists():
                strict_failures.append("external_review_missing")
            else:
                review = read_json(review_path, {})
                if not isinstance(review, dict):
                    strict_failures.append("external_review_invalid")
                else:
                    if review.get("verdict") != "Approve":
                        strict_failures.append("external_review_reject")
                    if review.get("needs_human_review"):
                        strict_failures.append("external_review_needs_human")
                    if draft_sha and review.get("draft_sha256") and review.get("draft_sha256") != draft_sha:
                        strict_failures.append("external_review_stale")
                    elif draft_sha and not review.get("draft_sha256"):
                        strict_failures.append("external_review_missing_draft_hash")
                    review_ctx = review.get("run_context")
                    if not isinstance(review_ctx, dict):
                        strict_failures.append("external_review_missing_context")
                    elif expected_context:
                        for key in (
                            "start_chapter_id",
                            "start_point_fingerprint",
                            "chapter_plan_item_fingerprint",
                            "plan_fingerprint",
                        ):
                            expected = str(expected_context.get(key) or "")
                            actual = str(review_ctx.get(key) or "")
                            if expected and actual != expected:
                                strict_failures.append(f"external_review_{key}_mismatch")
        approved = approved and not strict_failures

    return {
        "chapter_no": int(chapter_no),
        "exists": exists,
        "approved": approved,
        "needs_review": needs_review,
        "failure": failure,
        "verdict": verdict,
        "rewrite_count": rewrite_count,
        "draft_sha256": draft_sha,
        "strict_failures": strict_failures,
    }
