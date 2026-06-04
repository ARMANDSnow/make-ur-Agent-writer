from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import paths, source_excerpts, start_point
from .chapter_summary import append_chapter_summary, latest_ending_state, render_rolling_context
from .config import ROOT, load_config
from .continuation_anchor import load_continuation_anchor
from .entities import load_entity_graph, render_active_state
from .entity_advance import active_relationships, save_entity_advance_proposals
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
) -> List[Dict[str, Any]]:
    progress = progress_cb or (lambda _step, _fraction: None)
    budget_check = budget_check_cb or (lambda: None)
    drafts_dir = _drafts_dir()
    outline_path = _outline_path()
    kb_path = _kb_path()
    index_path = _index_path()
    ensure_dir(drafts_dir)
    if not outline_path.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")
    knowledge = kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""
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
        draft = ""
        report: Dict[str, Any] = {}
        feedback = ""
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
                messages, cache_segments = _write_prompt(
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
                try:
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
                # Iter 019: mock-only failure injection so the write_book.sh retry
                # path is testable without burning real-model budget. Gated by
                # OPENAI_MODEL=mock so production runs cannot trigger this branch
                # even if WRITER_FORCE_FAIL leaks into the environment.
                if (
                    os.getenv("WRITER_FORCE_FAIL") == "1"
                    and os.getenv("OPENAI_MODEL") == "mock"
                ):
                    # Inject content guaranteed to trigger linter "short chapter"
                    # error so the chapter is recorded as a failure.
                    draft = "强制失败注入。" * 5
                    last_nonempty_draft = draft
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
                # Iter 022 B4: pass KB + start-point source chapters into reviewer
                # so the 8-agent panel can judge fidelity against actual source
                # prose, not just persona impressions. Both args are graceful
                # — start_point.format_chapters_before_start_for_anchor returns
                # empty string when no start point is configured (iter 020 behavior).
                review_source = start_point.format_chapters_before_start_for_anchor(
                    k=3, limit_chars=8000
                )
                # Iter 023 P3: pass scene-matched excerpts so reviewer fidelity
                # scoring has the same archetype anchor as the writer prompt.
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
                report = review_text(
                    draft,
                    out_path.name,
                    precomputed_lint_issues=lint_issues,
                    rewrite_round=attempt - 1,
                    enforce_relationship_checklist=True,
                    knowledge=knowledge[:6000] if knowledge else "",
                    source_chapters=review_source,
                    scene_excerpts=scene_excerpts_text,
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
                meta["rewrite_count"] = max(0, attempt - 1)
                meta["chinese_char_count"] = count_chinese_chars(draft)
                meta["needs_human_review"] = report.get("verdict") != "Approve"
                meta["polish_applied"] = polish_applied
                meta["polish_diff_stats"] = polish_diff_stats
                meta["polish_error"] = report.get("polish_error", "")
                meta["lint_blocked_reviews"] = lint_blocked_reviews
                meta["run_context"] = run_context
                meta["draft_sha256"] = _draft_file_sha256(draft)
                if report.get("verdict") != "Approve":
                    meta["last_blocking_reasons"] = last_blocking_reasons
                write_text_atomic(out_path, draft + "\n")
                write_json(drafts_dir / f"chapter_{chapter_no:02d}.meta.json", meta)
                failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"
                if failure_path.exists():
                    failure_path.unlink()
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
        opening_instruction = (
            "严格按上述本章计划写。开场必须是 opening_scene 指定的场景；"
            "必须发生所有 key_events；不要引入计划之外的主要剧情节点。\n\n"
        )
        if previous_chapter_ending:
            opening_instruction = (
                "严格按上述本章计划写，但上一章结尾状态优先级更高。"
                "如果 opening_scene 发生在上一章结尾之前，不能把它当作本章主时间线开场；"
                "必须先从上一章结尾后的当前状态开场，并让当前时间线占正文 70% 以上。"
                "opening_scene 只能作为短回忆/插叙素材，总量不得超过正文 25%，"
                "不能连续铺成完整回忆章，不能复述交通流程、入学背景、社团设定或上一章已经交代的信息。"
                "每段回忆都必须被当前时间线的动作、对话或倒计时打断，并直接推动当前人物做出一个决定。"
                "本章结尾必须回到当前时间线并推进上一章留下的即时危机。"
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
    dynamic_context = (
        f"{anchor_context}"
        "# 本章目标长度\n\n"
        "中文正文 3500-5500 字之间，过短会被自动重写。\n\n"
        f"续写第 {chapter_no} 章。\n\n"
        f"人工全局事实:\n{facts_for_prompt}\n\n"
        f"{rolling_block}"
        f"{ending_block}"
        f"{chapter_plan_block}"
        f"{light_style_block}"
        f"previous_review_feedback:\n{feedback}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": stable_context + "\n\n" + dynamic_context},
    ]
    cache_segments = [
        {"role": "system", "content": system_prompt, "cache": True},
        {"role": "user", "content": stable_context, "cache": True},
        {"role": "user", "content": dynamic_context, "cache": False},
    ]
    return messages, cache_segments


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
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": style_context + dynamic_prompt}]
    cache_segments = [
        {"role": "system", "content": system_prompt, "cache": True},
        {"role": "user", "content": style_context, "cache": True},
        {"role": "user", "content": dynamic_prompt, "cache": False},
    ]
    return _complete_write_text(client, messages, cache_segments).strip()


def _review_feedback(report: Dict[str, Any]) -> str:
    parts: List[str] = []
    for issue in report.get("lint_issues", []):
        parts.append(_format_lint_feedback([issue]))
    for review in report.get("agent_reviews", []):
        if review.get("verdict") == "Reject":
            for issue in review.get("issues", []):
                if isinstance(issue, dict):
                    parts.append(
                        f"[{review.get('agent_name', 'reviewer')}] "
                        f"{issue.get('rule_id', 'issue')} / {issue.get('severity', 'major')} / "
                        f"{issue.get('anchor', '')}: {issue.get('message', '')}"
                    )
                else:
                    parts.append(f"[{review.get('agent_name', 'reviewer')}] {issue}")
            for suggestion in review.get("suggestions", []):
                parts.append(f"[{review.get('agent_name', 'reviewer')}] suggestion: {suggestion}")
    # Iter 024 P1: advisor's structured RewriteSuggestion list gets a
    # dedicated trailing section so the rewriter prioritizes it. Empty
    # list (or missing key) → no advisor block → behavior matches iter 023.
    suggs = report.get("rewrite_suggestions") or []
    if suggs:
        parts.append("")
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
        if review.get("verdict") != "Reject":
            continue
        suggestions = review.get("suggestions", [])
        for issue in review.get("issues", []):
            if isinstance(issue, dict):
                reasons.append(
                    {
                        "reviewer": review.get("agent_name", "reviewer"),
                        "rule_id": issue.get("rule_id"),
                        "severity": issue.get("severity", "major"),
                        "anchor": issue.get("anchor", ""),
                        "suggestion": issue.get("message") or (suggestions[0] if suggestions else ""),
                    }
                )
            else:
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
