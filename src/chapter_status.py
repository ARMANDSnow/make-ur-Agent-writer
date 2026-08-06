"""Iter 019: per-chapter status helper for the unattended write loop.

write_book.sh used to detect "chapter done" with a single ``[ -f
chapter_NN.md ]`` test, which silently accepted lint-blocked and
reviewer-rejected drafts as if they were approved. iter 019 centralises
the success / failure / needs-rewrite triage here so the shell script
can branch on a single JSON answer instead of grepping meta files.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from .utils import read_json_optional, sha256_file


class ChapterDisposition(str, Enum):
    """iter078 技债-1：一章盘面在 write run / readiness 中的处置五分类。

    此前该判定散在 ``run_write_book`` 章节循环与 ``check_write_readiness``
    逐章循环两条平行链（iter077 已第三次同步手改，谓词漏 ``failure``
    正是平行维护的实证）。下沉到 chapter_status 单一真源；两侧的**动作**
    （skip/补外审/归档重写/blocker 文案）留在原地，只有**判定**收敛。
    """

    SKIP_APPROVED = "skip_approved"
    SKIP_CAVEAT = "skip_caveat"
    SUPPLEMENT_EXTERNAL_REVIEW = "supplement_external_review"
    STALE_REJECT_REWRITE = "stale_reject_rewrite"
    FRESH_WRITE = "fresh_write"
    BLOCK = "block"


RESUMABLE_REJECT_FAILURES = frozenset(
    {
        "external_review_missing",
        "external_review_reject",
        "external_review_needs_human",
        "external_review_stale",
    }
)


def is_resumable_stale_reject(status: Dict[str, Any]) -> bool:
    """iter077 P0-5（iter078 技债-1 迁自 book_runner）：判定「中断期拒稿残迹」
    ——同一 run 配置下被 kill 打断的重试周期留下的非 approved 完整产物。

    此前这类章在 fresh resume 的 attempt 0 直接 BookRunBlocked → write-book
    exit 4 → supervisor 按终态退出，iter076 的「step 超时→自动 resume」恢复链
    在此自我终结（真模型 mid tier 下主审 Reject 常见，命中概率不可忽略）。
    判定为 True 的章走 attempt>0 同款「归档+重写」（残迹进 snapshots 可溯）。

    fail-closed 边界：verdict 缺失（meta 损坏/缺失）、任何 mismatch/legacy/
    human 类 strict failure → False（保持 BookRunBlocked，人审或 --force）。

    iter077 审查修复（铁律⑨ finder 命中，capstone 前直修）：
    * ``failure`` marker 在盘 = lint 终败「未分诊硬失败」（P0-2 自设边界），
      其 strict_failures 恰好落在白名单内——不看该字段会让每次 resume 重烧
      一整轮注定再终败的重试。
    * ``panel_halted`` marker = 上一 run 重试耗尽后按 halt 策略停机的分诊结论
      ——「停下等人」必须跨进程存活，否则 halt 残迹与 kill 中断残迹盘面同形，
      resume 会静默重写被 halt 的章（halt 语义只活一个进程生命周期）。
    """
    if not status.get("exists") or status.get("approved"):
        return False
    if status.get("failure") or status.get("panel_halted"):
        return False
    if status.get("verdict") not in ("Reject", "Approve"):
        return False
    failures = status.get("strict_failures") or []
    return all(f in RESUMABLE_REJECT_FAILURES for f in failures)


def classify_disposition(
    status: Dict[str, Any], *, force: bool, require_external_review: bool
) -> ChapterDisposition:
    """iter078 技债-1：处置五分类单一真源（纯函数，零 I/O 零 LLM）。

    输入是 ``chapter_status()`` 的产物 dict + 两个调用侧旗标（readiness 的
    ``allow_existing_blockers`` 即 run 的 ``force`` 同义传入）。判定顺序与
    run_write_book 章节循环逐分支等价：

    1. ``force`` → FRESH_WRITE（重写路径；是否先归档由 run 侧动作层决定）
    2. approved → SKIP_APPROVED
    3. caveat_approved → SKIP_CAVEAT（iter076/077：策略放行残迹非 stale）
    4. 存在的非 approved 产物：
       a. 外审缺失且主审 Approve → SUPPLEMENT_EXTERNAL_REVIEW（只补审不重写）
       b. :func:`is_resumable_stale_reject` → STALE_REJECT_REWRITE（归档重写）
       c. 其余 → BLOCK（fail-closed，人审或 --force）
    5. 无产物 → FRESH_WRITE
    """
    if force:
        return ChapterDisposition.FRESH_WRITE
    if status.get("approved"):
        return ChapterDisposition.SKIP_APPROVED
    if status.get("caveat_approved"):
        return ChapterDisposition.SKIP_CAVEAT
    if status.get("exists"):
        if (
            require_external_review
            and status.get("verdict") == "Approve"
            and (status.get("strict_failures") or []) == ["external_review_missing"]
        ):
            return ChapterDisposition.SUPPLEMENT_EXTERNAL_REVIEW
        if is_resumable_stale_reject(status):
            return ChapterDisposition.STALE_REJECT_REWRITE
        return ChapterDisposition.BLOCK
    return ChapterDisposition.FRESH_WRITE


def _has_hard_synthetic_reject(report: Any) -> bool:
    """iter076 HIGH#1：与 ``reviewer.has_hard_synthetic_reject`` 同语义的内联版
    （chapter_status 保持零重依赖——不 import reviewer；改语义时两处同步）。"""
    if not isinstance(report, dict):
        return False
    if isinstance(report.get("hard_reject"), bool):
        return report["hard_reject"]
    reviews = report.get("agent_reviews")
    if not isinstance(reviews, list):
        return False
    return any(
        isinstance(r, dict) and r.get("_synthetic") and r.get("verdict") == "Reject"
        for r in reviews
    )


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
          "style_rewrite_count": int, # independent iter087 style pass count
          "style_drift_unresolved": bool, # advisory only; never changes approved
        }

    Pure I/O of three known file paths — no LLM, no network.
    """

    drafts_dir = Path(drafts_dir)
    md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
    meta_path = drafts_dir / f"chapter_{chapter_no:02d}.meta.json"
    failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"

    exists = md_path.exists()
    failure = failure_path.exists()
    # iter059 #5: a corrupt chapter_NN.meta.json must not crash resume/status.
    # read_json_optional degrades it to {} (approved=False, verdict=None), same
    # as a missing meta; the bare read_json raised JSONDecodeError.
    meta: Dict[str, Any] = read_json_optional(meta_path, {}) if meta_path.exists() else {}
    strict_failures: list[str] = []

    verdict: Optional[str] = None
    if isinstance(meta, dict):
        raw_verdict = meta.get("verdict")
        if isinstance(raw_verdict, str) and raw_verdict:
            verdict = raw_verdict

    needs_review = bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False
    rewrite_count = 0
    style_rewrite_count = 0
    style_drift_unresolved = False
    if isinstance(meta, dict):
        raw_rc = meta.get("rewrite_count", 0)
        try:
            rewrite_count = int(raw_rc)
        except (TypeError, ValueError):
            rewrite_count = 0
        raw_style_rc = meta.get("style_rewrite_count", 0)
        if not isinstance(raw_style_rc, bool):
            try:
                style_rewrite_count = max(0, int(raw_style_rc))
            except (TypeError, ValueError, OverflowError):
                style_rewrite_count = 0
        style_drift_unresolved = meta.get("style_drift_unresolved") is True

    approved = (
        exists
        and not failure
        and not needs_review
        and verdict == "Approve"
    )
    # iter076 HIGH#1：hard/soft 拒稿区分 + caveat 放行标记的透出。
    # - hard_reject：meta 即主审 report 的拷贝（writer.py meta=dict(report)），synthetic
    #   硬拦直接可派生；开外审时下方分支再 OR 外审 report（外审也跑 plan-compliance）。
    # - caveat_approved：panel_block_policy=caveat_continue 放行过的章（verdict 仍
    #   Reject、needs_review 仍 True——早晨复查入口不变），book_runner 据此在 resume
    #   时跳过而不是重写。独立于 approved / strict_failures（用户手改过的 caveat 章
    #   同样跳过——那是操作者主动行为）。
    hard_reject = _has_hard_synthetic_reject(meta)
    caveat_approved = (
        exists
        and not failure
        and isinstance(meta, dict)
        and bool(meta.get("caveat_approved"))
    )
    # iter077 审查修复：重试耗尽后按 halt 停机的分诊结论（book_runner._mark_panel_halted
    # 落盘），resume 的 stale-reject 自动重写据此让路——halt 语义跨进程存活。
    panel_halted_raw = meta.get("panel_halted") if isinstance(meta, dict) else None
    panel_halted = bool(panel_halted_raw)
    panel_halt_reason = ""
    if isinstance(panel_halted_raw, dict):
        candidate = panel_halted_raw.get("reason")
        if candidate in {"retry_exhausted", "hard_reject", "external_review_reject"}:
            panel_halt_reason = str(candidate)
        elif candidate:
            panel_halt_reason = "unknown"
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
            # iter078 P1-6: model/review_tier 配置指纹。与上面 4 键不同，
            # 采用「双方都非空才比对」——旧 meta（iter078 前）没有这两键，
            # actual 为空不算 mismatch（存量零迁移）；两侧都有且不同 →
            # fail-closed block（mock 残迹混真书从静默跳过变显式拦截，
            # 且天然不在 stale-reject 白名单）。
            for key in ("model", "review_tier"):
                expected = str(expected_context.get(key) or "")
                actual = str(run_context.get(key) or "")
                if expected and actual and actual != expected:
                    strict_failures.append(f"{key}_mismatch")
        if require_external_review:
            review_path = drafts_dir.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json"
            if not review_path.exists():
                strict_failures.append("external_review_missing")
            else:
                # iter059 #5: corrupt review JSON degrades to None so it joins
                # the existing external_review_invalid strict-failure path
                # (a {} default would be a dict and slip through to reject).
                review = read_json_optional(review_path, None)
                if not isinstance(review, dict):
                    strict_failures.append("external_review_invalid")
                else:
                    hard_reject = hard_reject or _has_hard_synthetic_reject(review)
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
                        # iter078 P1-6: 同 meta 侧口径（双方非空才比对）。
                        for key in ("model", "review_tier"):
                            expected = str(expected_context.get(key) or "")
                            actual = str(review_ctx.get(key) or "")
                            if expected and actual and actual != expected:
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
        "style_rewrite_count": style_rewrite_count,
        "style_drift_unresolved": style_drift_unresolved,
        "draft_sha256": draft_sha,
        "strict_failures": strict_failures,
        "hard_reject": hard_reject,
        "caveat_approved": caveat_approved,
        "panel_halted": panel_halted,
        "panel_halt_reason": panel_halt_reason,
    }
