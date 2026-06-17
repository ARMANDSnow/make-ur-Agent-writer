from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import paths, review_tier, source_excerpts, start_point, writer_style
from .chapter_summary import append_chapter_summary, latest_ending_state, render_rolling_context
from .config import ROOT, load_config
from .continuation_anchor import load_continuation_anchor
from .entities import load_entity_graph, render_active_state
from .entity_advance import active_relationships, save_entity_advance_proposals
from .kb_view import start_safe_knowledge
from .linter import NovelLinter, count_chinese_chars
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .reviewer import review_text
from .schemas import ChapterPlan, ChapterSummary, EntityAdvanceProposalSet, model_to_dict
from .state import log_event, write_text_atomic
from .style import load_style_examples
from .utils import ensure_dir, read_json, sha256_text, write_json


# Legacy constants — kept so iter 014-016 tests that ``patch("src.writer.DRAFTS_DIR", ...)``
# still work. In workspace mode the ``_resolved_*()`` helpers defer to ``paths``.
DRAFTS_DIR = ROOT / "outputs" / "drafts"
OUTLINE_PATH = ROOT / "outputs" / "debate" / "outline.md"
KB_PATH = ROOT / "data" / "knowledge_base" / "global_knowledge.md"
INDEX_PATH = ROOT / "data" / "knowledge_base" / "knowledge_index.json"
CHAPTER_PLAN_PATH = ROOT / "outputs" / "debate" / "chapter_plan.json"


def _drafts_dir() -> Path:
    return paths.drafts_dir() if paths.workspace_name() else DRAFTS_DIR


def _outline_path() -> Path:
    return paths.outline_path() if paths.workspace_name() else OUTLINE_PATH


def _kb_path() -> Path:
    return paths.kb_path() if paths.workspace_name() else KB_PATH


def _index_path() -> Path:
    return paths.index_path() if paths.workspace_name() else INDEX_PATH


def _chapter_plan_path() -> Path:
    return paths.chapter_plan_path() if paths.workspace_name() else CHAPTER_PLAN_PATH


def write_chapters(
    chapters: int = 18,
    force: bool = False,
    max_attempts: Optional[int] = None,
    resume_from: int = 1,
    progress_cb: Optional[Callable[[str, float], None]] = None,
    budget_check_cb: Optional[Callable[[], Any]] = None,
    tier: str | None = None,
    seed_feedback: str = "",
) -> List[Dict[str, Any]]:
    # iter 053b（审查 B3）seed_feedback：跨 retry 周期反馈播种。book_runner 的
    # 每个 retry 周期先归档全部产物（含 review.json）再调本函数，而本函数每章
    # feedback 从零起步——外审 block 拒因随归档消失，下一周期第一稿完全失忆
    # （052 九稿横盘的周期间断链）。book_runner 单章重试时把上一周期的 block
    # 清单（同一分层模板渲染）经此参数喂进第一稿。缺省 "" = 行为与 053 前
    # 逐字节一致（铁律④）。多章调用时每章同源播种——当前唯一播种方
    # book_runner 固定 chapters=1。
    progress = progress_cb or (lambda _step, _fraction: None)
    budget_check = budget_check_cb or (lambda: None)
    resolved_tier = review_tier.resolve_tier(tier)
    tier_thresholds = review_tier.thresholds_snapshot(resolved_tier)
    drafts_dir = _drafts_dir()
    outline_path = _outline_path()
    kb_path = _kb_path()
    index_path = _index_path()
    ensure_dir(drafts_dir)
    if not outline_path.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")
    # iter 047b: start-safe KB view — with a start point + index this drops
    # post-start canon from the KB; with neither it returns the raw KB verbatim
    # (byte-identical to pre-047b). Truncation to knowledge_limit stays in _write_prompt.
    knowledge = start_safe_knowledge(kb_path=kb_path, index_path=index_path)
    outline = outline_path.read_text(encoding="utf-8")
    index = read_json(index_path, {})
    chapter_plan = _load_chapter_plan()
    facts = global_facts_summary()
    style_examples = load_style_examples()
    client = LLMClient("write")
    agent_cfg = load_config("agents.yaml")
    if "max_review_attempts" not in agent_cfg:
        raise KeyError("agents.yaml missing required key 'max_review_attempts'")
    continuation_anchor = load_continuation_anchor()
    configured_attempts = int(agent_cfg["max_review_attempts"])
    rewrite_limit = int(max_attempts) if max_attempts is not None else configured_attempts
    polish_enabled = bool(agent_cfg.get("polish_pass", True))
    # Iter 046: AgentWrite-style segmented write. Off by default → byte-identical
    # single-shot behavior. On + a chapter_plan_item carrying `segments` →
    # generate the chapter segment-by-segment honoring per-segment word quotas.
    segmented_write_enabled = bool(agent_cfg.get("segmented_write", False))
    shadow_review_enabled = bool(agent_cfg.get("review_during_lint_block", True))
    linter = NovelLinter()
    reports: List[Dict[str, Any]] = []
    light_prompt = _write_prompt_profile() == "light"
    rolling_max_chapters = 1 if light_prompt else 5
    rolling_snippet_chapters = 0 if light_prompt else 3
    for chapter_no in range(int(resume_from), int(resume_from) + int(chapters)):
        out_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
        rolling_path = drafts_dir / "rolling_chapter_summary.json"
        rolling_context = render_rolling_context(
            max_chapters=rolling_max_chapters,
            path=rolling_path,
            snippet_chapters=rolling_snippet_chapters,
        )
        previous_chapter_ending = latest_ending_state(path=rolling_path)
        chapter_plan_item = _chapter_plan_item(chapter_plan, chapter_no)
        run_context = _run_context(chapter_plan_item, chapter_no=chapter_no)
        if out_path.exists() and not force:
            if run_context.get("start_point_fingerprint") or run_context.get("chapter_plan_item_fingerprint"):
                from .chapter_status import chapter_status

                status = chapter_status(
                    chapter_no,
                    drafts_dir,
                    validate_context=True,
                    require_start_point=bool(run_context.get("start_point_fingerprint")),
                    require_plan=bool(run_context.get("chapter_plan_item_fingerprint")),
                    expected_context=run_context,
                )
                if status.get("approved"):
                    continue
            else:
                continue
        # Debug fix: derive enforce_relationship_checklist from the plan.
        # The relationship-consistency agent's strict checklist mode is
        # right for chapters with a small, tight cast (≤ 4 relationships
        # in play — reviewer can fully enumerate them). For broader
        # chapters that introduce cross-system entities the strict mode
        # leads to false Reject because the entity_graph hasn't caught
        # up. Switch to "warn_only" so the agent still inspects but
        # missing checklist downgrades from Reject to a suggestion.
        enforce_checklist_mode = _enforce_checklist_for_plan(chapter_plan_item)
        review_source = start_point.format_chapters_before_start_for_anchor(
            k=3, limit_chars=8000
        )
        scene_matches_for_review = (
            source_excerpts.select_for_chapter(chapter_plan_item, k=3)
            if chapter_plan_item
            else []
        )
        scene_excerpts_text = (
            source_excerpts.format_excerpts_for_prompt(
                scene_matches_for_review, limit_chars=8000
            )
            if scene_matches_for_review
            else ""
        )
        draft = ""
        report: Dict[str, Any] = {}
        feedback = seed_feedback or ""
        lint_ok = False
        polish_applied = False
        polish_diff_stats: Dict[str, int] = {}
        lint_blocked_reviews: List[Dict[str, Any]] = []
        last_lint_issues: List[Dict[str, Any]] = []
        last_blocking_reasons: List[Dict[str, Any]] = []
        last_nonempty_draft = ""
        attempt = 0
        stage = "setup"
        try:
            for attempt in range(1, rewrite_limit + 1):
                stage = "write"
                progress(f"write-attempt-{attempt}", 0.05)
                prompt_kwargs = dict(
                    chapter_no=chapter_no,
                    knowledge=knowledge,
                    facts=facts,
                    style_examples=style_examples,
                    continuation_anchor=continuation_anchor,
                    index=index,
                    outline=outline,
                    chapter_plan_item=chapter_plan_item,
                    rolling_context=rolling_context,
                    previous_chapter_ending=previous_chapter_ending,
                    feedback=feedback,
                )
                seg_plan = (chapter_plan_item or {}).get("segments") or []
                try:
                    if segmented_write_enabled and seg_plan:
                        draft = _write_chapter_segmented(
                            client, seg_plan, prompt_kwargs
                        ).strip()
                    else:
                        messages, cache_segments = _write_prompt(**prompt_kwargs)
                        draft = _complete_write_text(client, messages, cache_segments).strip()
                except Exception as exc:
                    partial_draft = _partial_draft_from_exception(exc)
                    if partial_draft:
                        last_nonempty_draft = partial_draft
                    raise
                if draft:
                    last_nonempty_draft = draft
                stage = "budget_check_write"
                budget_check()
                # Mock-only failure injection. iter 039 uses this to exercise
                # the partial-artifact path without burning real-model budget.
                if (
                    os.getenv("WRITER_FORCE_FAIL") == "1"
                    and os.getenv("OPENAI_MODEL") == "mock"
                ):
                    forced = RuntimeError("WRITER_FORCE_FAIL forced partial write failure")
                    setattr(forced, "partial_draft", draft or "强制失败注入。")
                    raise forced
                stage = "lint"
                lint_issues = linter.lint(draft)
                last_lint_issues = lint_issues
                if any(issue["severity"] == "error" for issue in lint_issues):
                    if shadow_review_enabled:
                        try:
                            stage = "shadow_review"
                            shadow_review = review_text(
                                draft,
                                out_path.name,
                                precomputed_lint_issues=lint_issues,
                                rewrite_round=attempt - 1,
                                run_agents_on_lint_error=True,
                                enforce_relationship_checklist=enforce_checklist_mode,
                                knowledge=knowledge[:6000] if knowledge else "",
                                source_chapters=review_source,
                                scene_excerpts=scene_excerpts_text,
                                tier=resolved_tier,
                                run_context=run_context,
                                draft_sha256=_draft_file_sha256(draft),
                            )
                            lint_blocked_reviews.append({"attempt": attempt, "review": shadow_review})
                        except Exception as exc:
                            log_event("write", "shadow_review_error", chapter=chapter_no, error=str(exc))
                        stage = "budget_check_review"
                        budget_check()
                    feedback = "请修复 deterministic linter 问题:\n" + _format_lint_feedback(lint_issues)
                    last_blocking_reasons = [
                        {
                            "reviewer": "deterministic_linter",
                            "rule_id": issue.get("rule"),
                            "severity": issue.get("severity"),
                            "message": issue.get("message"),
                            "anchor": issue.get("anchor") or issue.get("excerpt", ""),
                        }
                        for issue in lint_issues
                    ]
                    report = {"verdict": "Reject", "lint_issues": lint_issues, "attempt": attempt}
                    continue
                lint_ok = True
                stage = "review"
                progress(f"review-attempt-{attempt}", 0.50)
                report = review_text(
                    draft,
                    out_path.name,
                    precomputed_lint_issues=lint_issues,
                    rewrite_round=attempt - 1,
                    enforce_relationship_checklist=True,
                    knowledge=knowledge[:6000] if knowledge else "",
                    source_chapters=review_source,
                    scene_excerpts=scene_excerpts_text,
                    tier=resolved_tier,
                    run_context=run_context,
                    draft_sha256=_draft_file_sha256(draft),
                )
                stage = "budget_check_review"
                budget_check()
                progress(f"review-done-attempt-{attempt}", 0.55 + 0.05 * attempt)
                if report["verdict"] == "Approve":
                    last_blocking_reasons = []
                    break
                last_blocking_reasons = _blocking_reasons(report)
                feedback = _review_feedback(report)

            chinese_chars = count_chinese_chars(draft)
            needs_polish = (
                polish_enabled
                and draft
                and (
                    not lint_ok
                    or report.get("verdict") != "Approve"
                    or chinese_chars < 3000
                )
            )
            if needs_polish:
                stage = "polish"
                progress("polish", 0.85)
                try:
                    polished = _polish_draft(
                        client=client,
                        draft=draft,
                        lint_issues=last_lint_issues,
                        review_report=report,
                        style_examples=style_examples,
                        continuation_anchor=continuation_anchor,
                        chinese_chars=chinese_chars,
                    )
                    if polished:
                        pre_chars = len(draft)
                        draft = polished.strip()
                        last_nonempty_draft = draft or last_nonempty_draft
                        polish_applied = True
                        polish_diff_stats = {"pre_chars": pre_chars, "post_chars": len(draft)}
                except Exception as exc:
                    report["polish_error"] = f"{type(exc).__name__}: {exc}"
                stage = "budget_check_polish"
                budget_check()

            stage = "summarize"
            chapter_summary = _summarize_chapter(client, chapter_no, draft)
            # Iter 022 B5: store an opening + ending snippet (~500 chars each
            # tail) alongside the LLM summary so render_rolling_context can
            # serve raw prose for the most-recent chapters. Empty when
            # draft itself is short to avoid duplicate / nonsense.
            text_snippet = ""
            if draft and len(draft) >= 800:
                text_snippet = (
                    f"{draft[:300].strip()}\n\n[…省略中段…]\n\n{draft[-300:].strip()}"
                )
            append_chapter_summary(
                chapter_no,
                chapter_summary.get("summary", ""),
                chapter_summary.get("key_events", []),
                chapter_summary.get("ending_state", ""),
                text_snippet=text_snippet,
                path=drafts_dir / "rolling_chapter_summary.json",
            )
            stage = "entity_advance"
            proposals = _propose_entity_advance(client, chapter_no, draft, load_entity_graph())
            proposal_path = save_entity_advance_proposals(chapter_no, proposals, drafts_dir=drafts_dir)

            stage = "persist"
            if not lint_ok:
                failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"
                meta_path = drafts_dir / f"chapter_{chapter_no:02d}.meta.json"
                failure_report = {
                    "chapter": chapter_no,
                    "lint_issues": report.get("lint_issues", []),
                    "last_attempt": attempt,
                    "rewrite_count": max(0, attempt - 1),
                    "chinese_char_count": count_chinese_chars(draft),
                    "polish_applied": polish_applied,
                    "polish_diff_stats": polish_diff_stats,
                    "polish_error": report.get("polish_error", ""),
                    "lint_blocked_reviews": lint_blocked_reviews,
                    "last_blocking_reasons": last_blocking_reasons,
                    "draft_preview": draft[:2000],
                    "run_context": run_context,
                    "draft_sha256": _draft_file_sha256(draft),
                }
                write_json(failure_path, failure_report)
                meta = {
                    "target": out_path.name,
                    "rewrite_round": max(0, attempt - 1),
                    "lint_issues": report.get("lint_issues", []),
                    "agent_reviews": [],
                    "verdict": "Reject",
                    "tier": resolved_tier,
                    "panel_score": 0.0,
                    "approve_count": 0,
                    "tier_thresholds": tier_thresholds,
                    "rewrite_count": max(0, attempt - 1),
                    "chinese_char_count": count_chinese_chars(draft),
                    "needs_human_review": True,
                    "polish_applied": polish_applied,
                    "polish_diff_stats": polish_diff_stats,
                    "polish_error": report.get("polish_error", ""),
                    "lint_blocked_reviews": lint_blocked_reviews,
                    "last_blocking_reasons": last_blocking_reasons,
                    "failure_path": str(failure_path),
                    "run_context": run_context,
                    "draft_sha256": _draft_file_sha256(draft),
                    # 铁律⑨ B-M1：锚定开关状态留痕——053c 分段单变量对照的
                    # 凭据（不进 run_context 指纹面，防 chapter_status 比对漂移）。
                    "canon_anchor_active": bool(_canon_anchor_block()),
                }
                write_text_atomic(out_path, draft + "\n")
                write_json(meta_path, meta)
                log_event("write", "failure", chapter=chapter_no, reason="lint_errors")
                reports.append(
                    {
                        "chapter": chapter_no,
                        "path": str(out_path),
                        "failure_path": str(failure_path),
                        "proposal_path": str(proposal_path),
                        "review": meta,
                        "written": True,
                    }
                )
            else:
                meta = dict(report)
                meta.setdefault("tier", resolved_tier)
                meta.setdefault("panel_score", 0.0)
                meta.setdefault("approve_count", 0)
                meta.setdefault("tier_thresholds", tier_thresholds)
                meta["rewrite_count"] = max(0, attempt - 1)
                meta["chinese_char_count"] = count_chinese_chars(draft)
                meta["needs_human_review"] = report.get("verdict") != "Approve"
                meta["polish_applied"] = polish_applied
                meta["polish_diff_stats"] = polish_diff_stats
                meta["polish_error"] = report.get("polish_error", "")
                meta["lint_blocked_reviews"] = lint_blocked_reviews
                meta["run_context"] = run_context
                meta["draft_sha256"] = _draft_file_sha256(draft)
                # 铁律⑨ B-M1：锚定开关状态留痕（053c 段间对照凭据）。
                meta["canon_anchor_active"] = bool(_canon_anchor_block())
                if report.get("verdict") != "Approve":
                    meta["last_blocking_reasons"] = last_blocking_reasons
                write_text_atomic(out_path, draft + "\n")
                write_json(drafts_dir / f"chapter_{chapter_no:02d}.meta.json", meta)
                failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"
                if failure_path.exists():
                    failure_path.unlink()
                partial_path = drafts_dir / f"chapter_{chapter_no:02d}.partial.md"
                if partial_path.exists():
                    partial_path.unlink()
                reports.append(
                    {
                        "chapter": chapter_no,
                        "path": str(out_path),
                        "proposal_path": str(proposal_path),
                        "review": report,
                        "written": True,
                    }
                )
                log_event("write", report.get("verdict", "unknown").lower(), chapter=chapter_no, output=str(out_path))
            progress("finalize", 0.95)
        except Exception as exc:
            if last_nonempty_draft:
                _write_partial_failure(
                    drafts_dir,
                    chapter_no,
                    last_nonempty_draft,
                    attempt=attempt,
                    last_error=f"{type(exc).__name__}: {exc}",
                    stage=stage,
                )
            raise
    return reports


def _index_stats(index: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={len(value) if hasattr(value, '__len__') else 0}" for key, value in index.items())


def _enforce_checklist_for_plan(chapter_plan_item: Optional[Dict[str, Any]]) -> Any:
    """Debug fix: pick strict vs warn-only mode for the 关系一致性
    reviewer based on chapter plan complexity.

    - No plan available → ``True`` (default to strict, preserves iter
      014-019 behavior for any caller that doesn't use chapter_plan).
    - ``len(relationships_in_play) <= 4`` → ``True`` (strict checklist
      enforcement; chapter has a small enough cast that the agent can
      enumerate all pairs).
    - ``> 4`` → ``"warn_only"`` (agent still inspects, missing checklist
      becomes a suggestion instead of a Reject).

    Threshold 4 was picked to match the chapter_plan schema's typical
    upper bound — `relationships_in_play` rarely exceeds 4 entries in
    iter 014-019 corpus. Chapters above that introduce cross-system
    entities that the entity_graph may not yet have captured.
    """

    if not chapter_plan_item:
        return True
    rels = chapter_plan_item.get("relationships_in_play") or []
    if not isinstance(rels, list):
        return True
    return True if len(rels) <= 4 else "warn_only"


def _load_chapter_plan() -> Optional[Dict[int, Dict[str, Any]]]:
    chapter_plan_path = _chapter_plan_path()
    if not chapter_plan_path.exists():
        return None
    data = read_json(chapter_plan_path, {})
    plan = ChapterPlan(**data)
    return {int(item.chapter_no): model_to_dict(item) for item in plan.chapters}


def _chapter_plan_item(chapter_plan: Optional[Dict[int, Dict[str, Any]]], chapter_no: int) -> Optional[Dict[str, Any]]:
    if chapter_plan is None:
        return None
    item = chapter_plan.get(int(chapter_no))
    if item is None:
        raise ValueError(f"chapter_plan.json exists but has no plan for chapter {chapter_no}")
    return item


def _run_context(chapter_plan_item: Optional[Dict[str, Any]], *, chapter_no: int) -> Dict[str, Any]:
    from .plot_planner import chapter_plan_item_fingerprint, plan_fingerprint

    start_chapter_id = start_point.get_start_chapter_id() or ""
    start_fp = start_point.start_point_fingerprint()
    plan_data: Dict[str, Any] = {}
    plan_path = _chapter_plan_path()
    if plan_path.exists():
        raw = read_json(plan_path, {})
        if isinstance(raw, dict):
            plan_data = raw
    item_fp = ""
    if chapter_plan_item:
        item_fp = str(
            chapter_plan_item.get("chapter_plan_item_fingerprint")
            or chapter_plan_item_fingerprint(chapter_plan_item)
        )
    return {
        "schema_version": 1,
        "chapter_no": int(chapter_no),
        "start_chapter_id": str(plan_data.get("start_chapter_id") or start_chapter_id),
        "start_point_fingerprint": str(
            plan_data.get("start_point_fingerprint") or start_fp
        ),
        "chapter_plan_item_fingerprint": item_fp,
        "plan_fingerprint": str(plan_data.get("plan_fingerprint") or (plan_fingerprint(plan_data) if plan_data else "")),
    }


def _draft_file_sha256(draft: str) -> str:
    """Hash the exact text writer persists to chapter_NN.md."""

    return sha256_text(draft + "\n")


def _partial_draft_from_exception(exc: Exception) -> str:
    for attr in ("partial_draft", "partial_text", "draft", "text"):
        value = getattr(exc, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _write_partial_failure(
    drafts_dir: Path,
    chapter_no: int,
    draft: str,
    *,
    attempt: int,
    last_error: str,
    stage: str,
) -> Dict[str, Any]:
    partial_path = drafts_dir / f"chapter_{chapter_no:02d}.partial.md"
    failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"
    draft_text = draft.strip()
    draft_sha = _draft_file_sha256(draft_text)
    failure = {
        "chapter": int(chapter_no),
        "attempt": int(attempt),
        "last_error": last_error,
        "draft_sha256": draft_sha,
        "stage": stage,
        "draft_path": str(partial_path),
    }
    write_text_atomic(partial_path, draft_text + "\n")
    write_text_atomic(
        failure_path,
        json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
    )
    return failure


def _complete_write_text(client: LLMClient, messages: List[Dict[str, str]], cache_segments: List[Dict[str, Any]]) -> str:
    try:
        return client.complete_text(messages, temperature=0.6, cache_segments=cache_segments)
    except TypeError as exc:
        if "cache_segments" not in str(exc):
            raise
        return client.complete_text(messages, temperature=0.6)


def _write_prompt_profile() -> str:
    profile = os.getenv("WRITE_PROMPT_PROFILE", "").strip().lower()
    return "light" if profile in {"light", "compact"} else "default"


def _canon_anchor_enabled() -> bool:
    """iter 053b: env kill-switch for the canon time-anchor block.
    ``WRITER_CANON_ANCHOR=0`` disables it — 053c 段一的单变量对照（ch1 只吃
    053a 净图纸）与紧急回退都走这里。Default on."""
    return os.getenv("WRITER_CANON_ANCHOR", "1").strip() != "0"


def _canon_anchor_block() -> str:
    """iter 053b（审查 B1）：反剧透时间锚定块。

    052 longzu 实跑的次因实证：写手把预训练记忆里的原著**后期**设定写进
    正文（"路鸣泽四分之一生命交易"——起点处只有"愿意交换么"悬念）；
    ``start_safe_knowledge``（047b）管 KB 注入、管不住权重记忆。

    锚定用**时间**而非**注入范围**："未注入的设定一律视为不存在"会把
    起点之前、但没挤进 knowledge 截断窗口的合法 canon（言灵细节、学院
    设定……正是 fidelity 评审拿预训练记忆核对的内容）一并误杀，质感与
    fidelity 反降。时间锚定只禁起点之后，起点之前照常使用。

    条件注入（铁律④回退契约）：无起点（premise 自创书，无"原著记忆"可
    泄露）或 env 关闭时返回空串——上游 prompt 逐字节不变。
    """
    if not _canon_anchor_enabled():
        return ""
    start_id = start_point.get_start_chapter_id()
    if not start_id:
        return ""
    return (
        "## 原著时间线锚定（硬约束，违反会被评审 block）\n"
        "\n"
        f"本次续写的起点为原著章节 `{start_id}`，你从这一点起接管故事：\n"
        f"1. 原著在 `{start_id}` **之后**才发生的事件、才揭示的设定、才出现的"
        "人物关系变化，在本故事里一律视为尚未发生/尚未揭示——禁止引用、"
        "转述或暗示，即使你的记忆里有这部作品的后续内容。\n"
        f"2. 原著在 `{start_id}` **之前**（含该章）已成立的事实、设定与人物"
        "关系可以正常使用，这是你写出原著质感的根基。\n"
        "3. 允许原创与既有设定不冲突的新事件、新细节；剧情自然推进不算剧透。\n"
        "4. 拿不准某设定在起点前是否已揭示时，以注入的知识库/章纲/起点片段"
        "为准；两者都查不到的，按未揭示处理。"
    )


def _write_prompt(
    *,
    chapter_no: int,
    knowledge: str,
    facts: str,
    style_examples: str,
    continuation_anchor: str,
    index: Dict[str, Any],
    outline: str,
    chapter_plan_item: Optional[Dict[str, Any]] = None,
    rolling_context: str = "",
    previous_chapter_ending: str = "",
    feedback: str = "",
    segment: Optional[Dict[str, Any]] = None,
    segment_index: int = 1,
    segment_total: int = 1,
    prior_segments_text: str = "",
) -> tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    light_prompt = _write_prompt_profile() == "light"
    knowledge_limit = 2500 if light_prompt else 9000
    outline_limit = 1500 if light_prompt else 6000
    scene_excerpt_limit = 0 if light_prompt else 8000
    scene_excerpt_count = 0 if light_prompt else 3
    source_chapter_limit = 0 if light_prompt else 3000
    source_chapter_count = 0 if light_prompt else 3
    system_prompt = (
        "你是长篇小说续写写作者。只输出正文，不要输出章节编号或解释。\n"
        "\n"
        "## 关键风格戒律（违反会被自动 reject）\n"
        "\n"
        "**避免 AI 标记性的对比强调句式**。具体来说，"
        "以否定词开头、紧接转折强调的二段式短句"
        "（形如否定一个事物 + 立即给出对立替代）—— 原作（江南龙族）"
        "整本书每 1000 字才出现 1 次以下，AI 模型却容易每段 1-2 次。\n"
        "\n"
        "如需表达对比 / 强调 / 转折，**优先**采用以下三种笔法（仅描述，不给字面例子以免污染你的输出）：\n"
        "1. **动作描述法**：用具体的肢体动作或环境反应替代抽象判断。"
        "   把'这是 X，不是 Y'类逻辑表达，重写成发生在身体或场景里的动作链。\n"
        "2. **感官比喻法**：把对比转换成一个新的感官印象。"
        "   不去否定 X 抬高 Y，而是直接给读者一个能唤起 Y 的画面、声音、温度或质地。\n"
        "3. **断句重复法**：用极短的独立句和重复词建立强调，"
        "   通过节奏而非逻辑标记表达递进。\n"
        "\n"
        "如果上一稿的 review feedback 显示这类句式被命中，"
        "**必须**把所有命中位置改写为以上三种笔法之一，再生成本稿。"
    )
    # iter 053b（审查 B1）：时间锚定反剧透块——条件注入；无起点 / env 关闭
    # 时 _canon_anchor_block() 返回空串，system_prompt 与 053 前逐字节一致
    # （铁律④，mock 测试钉死）。
    canon_anchor = _canon_anchor_block()
    if canon_anchor:
        system_prompt = f"{system_prompt}\n\n{canon_anchor}"
    style_context = ""
    if style_examples and not light_prompt:
        style_context = (
            "# 作者风格参考（重点匹配此节奏与含蓄度，不要复制具体情节/人名/场景）\n\n"
            f"{style_examples}\n\n"
            "写作时优先匹配上述风格参考的节奏、含蓄度与意象使用方式；不要复制具体情节、地名、人名或事件。\n\n"
        )
    stable_context = (
        f"{style_context}"
        f"全局知识:\n{knowledge[:knowledge_limit]}\n\n"
        f"机器索引统计:\n{_index_stats(index)}\n\n"
        f"辩论大纲:\n{outline[:outline_limit]}"
    )
    entity_state = render_active_state(load_entity_graph())
    if entity_state:
        stable_context = (
            f"{stable_context}\n\n"
            f"{entity_state}\n"
            "严格遵守'当前活跃关系'：任何角色互动、人物对彼此的认知、关系描述必须匹配上面 active 状态；"
            "不要编造未列出的关系；不要让角色行为与已确立关系冲突。"
        )
    # Iter 023: inject scene-matched source excerpts (archetype-specific
    # original text picked by `source_excerpts.select_for_chapter` based on
    # chapter_plan_item.key_events / opening_scene). Complements iter 021's
    # time-sliced "起点前 K 章" injection below: that's chronological context,
    # this is genre/scene context. Empty when no excerpts.json or no plan_item
    # → byte-identical to iter 022.
    if chapter_plan_item:
        scene_matches = source_excerpts.select_for_chapter(chapter_plan_item, k=scene_excerpt_count)
        if scene_matches:
            scene_block = source_excerpts.format_excerpts_for_prompt(
                scene_matches, limit_chars=scene_excerpt_limit
            )
            if scene_block:
                stable_context = (
                    f"{stable_context}\n\n"
                    "# 原作 archetype 参考（按本章 scene_type 匹配的原文片段；"
                    "仅参考笔法/节奏/细节密度，不复述情节）\n\n"
                    f"{scene_block}\n"
                )

    # Iter 021: inject K=3 chapters of authentic source text immediately
    # before the start point so writer sees real prose for style + detail
    # anchoring. When no start point is set (iter 020 default behavior),
    # `chapters_before_start` returns [] and this block stays empty —
    # prompt remains byte-identical to iter 020.
    src_chapters = start_point.chapters_before_start(k=source_chapter_count)
    if src_chapters:
        pieces = []
        for ch in src_chapters:
            body = start_point.load_chapter_text(ch.get("chapter_id", ""))[:source_chapter_limit]
            if not body:
                continue
            pieces.append(
                f"### {ch.get('chapter_id', '')} — {ch.get('title', '')}\n\n{body}"
            )
        if pieces:
            stable_context = (
                f"{stable_context}\n\n"
                f"# 原文片段参考（起点前 {len(pieces)} 章，用于风格 + 细节锚点；不要复述情节）\n\n"
                + "\n\n---\n\n".join(pieces)
                + "\n\n"
                "上述片段是原作者的真实文字，用于参考叙事节奏、用词、人物塑造的细节密度。"
                "续写不要复述上述情节，但写作风格、人物对话语气、环境刻画密度应向这些片段靠拢。"
            )
    anchor_context = (
        f"# 续写起点（must-anchor）\n\n{continuation_anchor}\n\n"
        if continuation_anchor and not light_prompt
        else ""
    )
    facts_for_prompt = "" if light_prompt else facts
    rolling_block = f"{rolling_context}\n" if rolling_context else ""
    ending_block = (
        "## 上一章结尾状态\n\n"
        f"{previous_chapter_ending}\n\n"
        "## 本章开场衔接提示\n\n"
        "本章开场必须自然衔接上述结尾状态；可以闪回但不能直接跳到不相关场景。\n\n"
        if previous_chapter_ending
        else ""
    )
    chapter_plan_block = ""
    if chapter_plan_item:
        key_events = "\n".join(f"- {event}" for event in chapter_plan_item.get("key_events", []))
        relationships = "\n".join(
            f"- {item}" for item in chapter_plan_item.get("relationships_in_play", [])
        )
        if not relationships:
            relationships = "- 无特别指定"
        # iter 052b: F7 淘汰。iter027 曾在这里对 opening_instruction 做
        # "上一章结尾优先级更高 / opening_scene 降级为回忆素材" 的覆写——
        # 那是起点一致性缺口的 prompt 创可贴。F6（start_point.enforce_consistency，
        # iter051b 集中、052 真模型验证）从源头钉死了起点四码一致性后，
        # 补丁按计划拆除：开场衔接语义仍由上方 ending_block（iter013）+
        # chapter_plan_block 的优先级声明承担。
        opening_instruction = (
            "严格按上述本章计划写。开场必须是 opening_scene 指定的场景；"
            "必须发生所有 key_events；不要引入计划之外的主要剧情节点。\n\n"
        )
        chapter_plan_block = (
            "## 本章计划（必须严格遵守）\n\n"
            "优先级：已写章节回顾/上一章结尾状态 > 本章计划 > 辩论大纲。"
            "如果本章计划与已发生内容冲突，优先承接已发生内容，并在正文中自然化解冲突。\n\n"
            f"title: {chapter_plan_item.get('title', '')}\n"
            f"opening_scene: {chapter_plan_item.get('opening_scene', '')}\n"
            f"target_chinese_chars: {chapter_plan_item.get('target_chinese_chars', 4000)}\n"
            f"plot_purpose: {chapter_plan_item.get('plot_purpose', '')}\n"
            f"ending_hook: {chapter_plan_item.get('ending_hook', '')}\n\n"
            "key_events（必须全部发生）：\n"
            f"{key_events}\n\n"
            "relationships_in_play：\n"
            f"{relationships}\n\n"
            f"{opening_instruction}"
        )
    light_style_block = (
        "## light prompt 写作约束\n\n"
        "- 本章按过渡章写：少解释机制，少回忆讲解，少系统日志，避免把设定一次讲透。\n"
        "- 每个比喻必须克制，连续比喻不要堆叠；优先用动作、停顿、对话和场景反应推进。\n"
        "- 神秘信息只给碎片和刺痛感，不给结论；不要用总结性金句收束人物处境。\n\n"
        if light_prompt
        else ""
    )
    # Iter 046: in segmented mode the per-章 length target is replaced by a
    # per-段 quota and a segment directive (suppress wrap-up on non-final
    # segments). When ``segment is None`` both blocks reproduce the original
    # strings exactly → single-shot prompt stays byte-identical.
    if segment is not None:
        seg_target = int(segment.get("target_chinese_chars", 1200) or 1200)
        length_block = (
            "# 本段目标长度\n\n"
            f"这是本章第 {segment_index}/{segment_total} 段，本段中文正文约 {seg_target} 字。\n\n"
        )
        segment_block = _segment_directive_block(
            segment=segment,
            segment_index=segment_index,
            segment_total=segment_total,
            prior_segments_text=prior_segments_text,
        )
    else:
        length_block = (
            "# 本章目标长度\n\n"
            "中文正文 3500-5500 字之间，过短会被自动重写。\n\n"
        )
        segment_block = ""
    dynamic_context = (
        f"{anchor_context}"
        f"{length_block}"
        f"续写第 {chapter_no} 章。\n\n"
        f"人工全局事实:\n{facts_for_prompt}\n\n"
        f"{rolling_block}"
        f"{ending_block}"
        f"{chapter_plan_block}"
        f"{segment_block}"
        f"{light_style_block}"
        f"previous_review_feedback:\n{feedback}"
    )
    # iter056: 作家风格卡——仅 premise 自创书（block 内判 start_id）、light 档不注入。
    # 独立成可缓存段且置于 stable 之后：改卡只失效本段、不动 KB 段缓存（HIGH-1）。
    # 续写书/无卡→"" → messages 空串拼接逐字节回退；cache_segments 条件不加空段（铁律④）。
    style_card_context = "" if light_prompt else writer_style.writer_style_prompt_block()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": stable_context + "\n\n" + style_card_context + dynamic_context},
    ]
    cache_segments = [
        {"role": "system", "content": system_prompt, "cache": True},
        {"role": "user", "content": stable_context, "cache": True},
    ]
    if style_card_context:
        cache_segments.append({"role": "user", "content": style_card_context, "cache": True})
    cache_segments.append({"role": "user", "content": dynamic_context, "cache": False})
    return messages, cache_segments


def _segment_directive_block(
    *,
    segment: Dict[str, Any],
    segment_index: int,
    segment_total: int,
    prior_segments_text: str,
) -> str:
    """Iter 046: per-segment instructions for the segmented write loop.

    Tells the writer which beat to cover, to weave on from prior segments
    (segment > 1 must not restart from opening_scene), and — crucially — to
    NOT wrap up the chapter / write an ending hook unless this is the final
    segment. Only ``_write_prompt`` calls this, and only when a segment is
    present; the single-shot path never emits this block.
    """

    beat = str(segment.get("beat", "")).strip()
    prior_block = ""
    if prior_segments_text:
        prior_block = (
            "## 本章已写前文（无缝衔接续写，不要重复已写内容）\n\n"
            f"{prior_segments_text[-4000:]}\n\n"
        )
    # iter047B2 M8: segment position is authoritative — only the last segment
    # wraps up. A plan that mis-flags a non-final segment is_final=True must NOT
    # trigger a premature in-chapter ending (+ a second next-chapter hook).
    is_final = segment_index >= segment_total
    if is_final:
        tail_instruction = (
            "本段是本章最后一段：自然收束全章，并写出 ending_hook 暗示的结尾钩子。"
        )
    else:
        tail_instruction = (
            "本段不是最后一段：只写完本段 beat 对应的情节，自然停在中途；"
            "不要收束全章、不要写章节结尾、不要写下一章钩子、不要做总结性收尾句。"
        )
    if segment_index == 1:
        position_instruction = "本段为开篇段，按本章计划的 opening_scene 开场。"
    else:
        position_instruction = (
            "本段衔接上面【本章已写前文】继续写，不要从 opening_scene 重新开场、不要重述已写情节。"
        )
    return (
        "# 分段写作（配额循环）\n\n"
        f"{prior_block}"
        f"本段 beat：{beat}\n\n"
        f"{position_instruction}\n"
        f"{tail_instruction}\n\n"
    )


def _write_chapter_segmented(
    client: LLMClient,
    segments: List[Dict[str, Any]],
    prompt_kwargs: Dict[str, Any],
) -> str:
    """Iter 046: AgentWrite-style segment loop. Generate the chapter one
    segment at a time — each honoring its word-count quota and (for non-final
    segments) suppressing premature wrap-up — then concatenate. The assembled
    chapter flows through the unchanged lint / review / polish / persist path.

    Stable context (style / KB / outline / entity state) stays ``cache:True``
    and constant across all segments of a chapter; only the per-segment
    dynamic block is ``cache:False`` — so segmentation stays cache-cost cheap.
    """

    total = len(segments)
    parts: List[str] = []
    for idx, segment in enumerate(segments, start=1):
        prior_text = "\n\n".join(parts)
        messages, cache_segments = _write_prompt(
            **prompt_kwargs,
            segment=segment,
            segment_index=idx,
            segment_total=total,
            prior_segments_text=prior_text,
        )
        piece = _complete_write_text(client, messages, cache_segments).strip()
        if piece:
            parts.append(piece)
    return "\n\n".join(parts)


def _summarize_chapter(client: LLMClient, chapter_no: int, draft: str) -> Dict[str, Any]:
    if client.is_mock:
        return {
            "summary": f"mock 第 {chapter_no} 章摘要：本章承接上一章状态并推进主要冲突。",
            "key_events": ["mock 事件推进", "mock 关系变化"],
            "ending_state": f"mock 第 {chapter_no} 章结尾状态",
        }
    try:
        result = client.complete_json(
            [
                {
                    "role": "system",
                    "content": "你是长篇续写的章节状态记录员。只输出 JSON。",
                },
                {
                    "role": "user",
                    "content": (
                        f"请总结续写第 {chapter_no} 章，输出字段 summary、key_events、ending_state。"
                        "summary 200-400 字；key_events 3-6 条；ending_state 描述本章结尾人物位置、状态和情绪基调。\n\n"
                        f"{draft[:20000]}"
                    ),
                },
            ],
            ChapterSummary,
        )
        return model_to_dict(result)
    except Exception as exc:
        log_event("write", "chapter_summary_fallback", chapter=chapter_no, error=str(exc))
        return {
            "summary": draft[:500],
            "key_events": ["summary_fallback"],
            "ending_state": draft[-300:] if draft else "",
        }


def _propose_entity_advance(
    client: LLMClient,
    chapter_no: int,
    draft: str,
    entity_graph: Dict[str, Any],
) -> List[Dict[str, Any]]:
    relationships = active_relationships(entity_graph)
    if client.is_mock or not relationships:
        return []
    try:
        result = client.complete_json(
            [
                {
                    "role": "system",
                    "content": "你是实体关系演进审查员。只输出 JSON，不要直接修改实体图。",
                },
                {
                    "role": "user",
                    "content": (
                        f"续写第 {chapter_no} 章已完成。请根据正文判断哪些 active relationship 需要提出演进建议。"
                        "只提出正文中有明确触发事件的变化；不确定则返回空 proposed_advances。"
                        "每条必须使用当前 relationship 的 src_id、dst_id；不要只写 relationship_id。"
                        "confidence 必须是 0.0-1.0 数字，不要写 high/medium/low。\n\n"
                        f"# 当前 active relationships\n{relationships}\n\n"
                        f"# 本章正文\n{draft[:20000]}"
                    ),
                },
            ],
            EntityAdvanceProposalSet,
        )
        return [model_to_dict(item) for item in result.proposed_advances]
    except Exception as exc:
        log_event("write", "entity_advance_fallback", chapter=chapter_no, error=str(exc))
        return []


def _format_lint_feedback(lint_issues: List[Dict[str, Any]]) -> str:
    """Iter 022 B2: lint feedback for writer rewrite loop.

    Groups not_x_but_y hits with explicit per-line line numbers + excerpts
    so the rewriter sees exactly which sentences to fix, not just an
    abstract "you hit the rule N times". Other rules keep their original
    one-line format.
    """
    nxy_issues = [i for i in lint_issues if i.get("rule") == "not_x_but_y"]
    other_issues = [i for i in lint_issues if i.get("rule") != "not_x_but_y"]
    parts: List[str] = []

    if nxy_issues:
        total = nxy_issues[0].get("count", len(nxy_issues))
        parts.append(
            f"【关键】上一稿命中 AI 对比强调句式 {total} 次，超过阈值。"
            f"必须把下列每一处都改写为：(a) 动作描述、(b) 感官比喻、或 (c) 断句+重复"
            f"——任选其一。注意：本反馈不重复违规字面以免污染你的输出，"
            f"请按行号回到正文定位并改写。"
        )
        # Iter 022 fix: list line numbers only (no excerpt content) to avoid
        # priming the rewriter on the literal "不是X是Y" pattern. Each
        # violation just gets its line number — the rewriter has the full
        # draft and can locate the line itself.
        line_nos = [str(issue.get("line", "?")) for issue in nxy_issues]
        parts.append(f"  违规行号: {', '.join(line_nos)}")

    for issue in other_issues:
        rule = issue.get("rule", "lint")
        count = issue.get("count")
        count_text = f"，命中 {count} 次" if isinstance(count, int) else ""
        anchor = issue.get("anchor") or issue.get("excerpt", "")
        parts.append(
            f"[规则 {rule}{count_text}] {issue.get('message', '')} "
            f"锚点：'{anchor}'。"
        )
    return "\n".join(parts)


def _polish_draft(
    *,
    client: LLMClient,
    draft: str,
    lint_issues: List[Dict[str, Any]],
    review_report: Dict[str, Any],
    style_examples: str,
    continuation_anchor: str,
    chinese_chars: int | None = None,
) -> str:
    review_feedback = _review_feedback(review_report)
    lint_feedback = _format_lint_feedback(lint_issues)
    style_context = (
        "# 作者风格参考（只学习节奏、含蓄度和意象使用，不复制具体内容）\n\n"
        f"{style_examples}\n\n"
        if style_examples
        else ""
    )
    anchor_context = f"# 续写起点\n\n{continuation_anchor}\n\n" if continuation_anchor else ""
    measured_chinese_chars = count_chinese_chars(draft) if chinese_chars is None else chinese_chars
    expansion_context = ""
    if measured_chinese_chars < 3000:
        expansion_context = (
            f"# 扩写要求\n\n当前 {measured_chinese_chars} 中文字，目标 3500-5500 中文字，"
            "扩充环境/动作/心理/对话。在保留现有情节和风格基础上增加环境与动作细节描写、"
            "深化心理活动、补充对话张力；不要改写为大纲，不要删减既有关键情节。\n\n"
        )
    system_prompt = (
        "你是长篇小说终稿修订者。只输出修订后的完整正文。"
        "不要解释，不要输出问题清单，不要加章节编号。"
    )
    dynamic_prompt = (
        f"{anchor_context}"
        "# 修订目标\n\n"
        "以下是被反复拒绝的草稿和完整问题清单。请做一次集中修订，重点解决："
        "lint anchor 提到的具体句子；reviewer 标的 rule_id/anchor。"
        "保持现有故事线和章节长度，不少于现稿。"
        "避免反复使用'不是X，是Y'/'不是X而是Y'句式；同章最多出现 2 次。"
        "如需对比，优先用动作/环境替代说明。\n\n"
        f"{expansion_context}"
        f"# deterministic linter 问题\n\n{lint_feedback}\n\n"
        f"# reviewer 问题\n\n{review_feedback}\n\n"
        f"# 最后一稿全文\n\n{draft}"
    )
    # iter056（HIGH-2）：polish 也注入风格卡，避免同章初稿带卡、终稿不带的漂移。
    # block 内判 premise/续写；续写书/无卡→"" 逐字节回退（cache_segments 不加空段）。
    style_card_context = writer_style.writer_style_prompt_block()
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": style_context + style_card_context + dynamic_prompt}]
    cache_segments = [
        {"role": "system", "content": system_prompt, "cache": True},
        {"role": "user", "content": style_context, "cache": True},
    ]
    if style_card_context:
        cache_segments.append({"role": "user", "content": style_card_context, "cache": True})
    cache_segments.append({"role": "user", "content": dynamic_prompt, "cache": False})
    return _complete_write_text(client, messages, cache_segments).strip()


def _review_feedback(report: Dict[str, Any]) -> str:
    """iter 053b: 分层回灌模板（审查 B2 + 052 九稿横盘实证）。

    052 实跑教训：现行实现把 block 级拒因和普通建议混拼成一段平文字，模型
    分不清"禁令"与"可选优化"，九稿 panel 5.68→6.16 横盘。本版分四层：

    1. lint 问题（保持置顶，与历史一致）；
    2. ``## 评审 block 级违例`` —— **不再限定该评审整体 verdict=Reject**：
       severity=block 但所在评审 Approve（整体因票数被拒）的 issue 此前被
       漏掉（block-but-Approve 漏灌缺陷）。``_blocking_reasons`` 同口径修改，
       两个出口不许分裂；
    3. ``## 必须处理的修改建议`` —— Reject 评审的 major/字符串 issue；
       改写顾问的结构化建议保留原节标题与 [:5] 截断惯例（iter 024 契约）；
    4. ``## 可选优化`` —— minor 级 issue 与评审 suggestions。
    """
    parts: List[str] = []
    for issue in report.get("lint_issues", []):
        parts.append(_format_lint_feedback([issue]))

    block_lines: List[str] = []
    major_lines: List[str] = []
    optional_lines: List[str] = []
    for review in report.get("agent_reviews", []):
        name = review.get("agent_name", "reviewer")
        is_reject = review.get("verdict") == "Reject"
        for issue in review.get("issues", []):
            if isinstance(issue, dict):
                severity = str(issue.get("severity", "major")).lower()
                line = (
                    f"[{name}] "
                    f"{issue.get('rule_id', 'issue')} / {issue.get('severity', 'major')} / "
                    f"{issue.get('anchor', '')}: {issue.get('message', '')}"
                )
                if severity == "block":
                    block_lines.append(line)
                elif is_reject and severity == "minor":
                    optional_lines.append(line)
                elif is_reject:
                    major_lines.append(line)
            elif is_reject:
                major_lines.append(f"[{name}] {issue}")
        if is_reject:
            for suggestion in review.get("suggestions", []):
                optional_lines.append(f"[{name}] suggestion: {suggestion}")

    if block_lines:
        parts.append("## 评审 block 级违例（逐条禁令，本稿必须全部规避）")
        for i, line in enumerate(block_lines, 1):
            parts.append(f"{i}. {line}")
    if major_lines:
        parts.append("## 必须处理的修改建议")
        parts.extend(major_lines)
    # Iter 024 P1: advisor's structured RewriteSuggestion list gets a
    # dedicated section so the rewriter prioritizes it. Empty list (or
    # missing key) → no advisor block. 节标题与 [:5] 截断是既有契约。
    suggs = report.get("rewrite_suggestions") or []
    if suggs:
        parts.append("## 改写顾问建议（按优先级，必须在下一稿处理）")
        for i, s in enumerate(suggs[:5], 1):
            if not isinstance(s, dict):
                continue
            advisor = s.get("_advisor", "改写顾问")
            section = str(s.get("section") or "").strip()
            op = str(s.get("type") or "rewrite").strip()
            guidance = str(s.get("guidance") or "").strip()
            parts.append(
                f"{i}. [{advisor}] [{op}] {section}: {guidance}"
            )
    if optional_lines:
        parts.append("## 可选优化")
        parts.extend(optional_lines)
    return "\n".join(p for p in parts if p)


def _blocking_reasons(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []
    for issue in report.get("lint_issues", []):
        if issue.get("severity") == "error":
            reasons.append(
                {
                    "reviewer": "deterministic_linter",
                    "rule_id": issue.get("rule"),
                    "severity": "block",
                    "anchor": issue.get("excerpt", ""),
                    "suggestion": issue.get("message", ""),
                }
            )
    for review in report.get("agent_reviews", []):
        # iter 053b（审查 B2）：与 _review_feedback 同口径——severity=block 的
        # issue 不再被"该评审整体 Approve"挡掉（整体因票数 Reject 时，Approve
        # 评审里的 block 违例此前进不了 last_failure/web 失败面，回灌与失败
        # 记录两套口径）。非 block 的 issue 仍只取 Reject 评审，行为不变。
        is_reject = review.get("verdict") == "Reject"
        suggestions = review.get("suggestions", [])
        for issue in review.get("issues", []):
            if isinstance(issue, dict):
                severity = str(issue.get("severity", "major")).lower()
                if not is_reject and severity != "block":
                    continue
                reasons.append(
                    {
                        "reviewer": review.get("agent_name", "reviewer"),
                        "rule_id": issue.get("rule_id"),
                        "severity": issue.get("severity", "major"),
                        "anchor": issue.get("anchor", ""),
                        "suggestion": issue.get("message") or (suggestions[0] if suggestions else ""),
                    }
                )
            elif is_reject:
                reasons.append(
                    {
                        "reviewer": review.get("agent_name", "reviewer"),
                        "rule_id": None,
                        "severity": "major",
                        "anchor": "",
                        "suggestion": str(issue),
                    }
                )
    return reasons
