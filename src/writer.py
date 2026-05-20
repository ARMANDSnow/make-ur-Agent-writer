from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .chapter_summary import append_chapter_summary, latest_ending_state, render_rolling_context
from .config import ROOT, load_config
from .entities import load_entity_graph, render_active_state
from .entity_advance import active_relationships, save_entity_advance_proposals
from .linter import NovelLinter, count_chinese_chars
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .reviewer import review_text
from .schemas import ChapterPlan, ChapterSummary, EntityAdvanceProposalSet, model_to_dict
from .state import log_event, write_text_atomic
from .style import load_style_examples
from .utils import ensure_dir, read_json, write_json


DRAFTS_DIR = ROOT / "outputs" / "drafts"
OUTLINE_PATH = ROOT / "outputs" / "debate" / "outline.md"
KB_PATH = ROOT / "data" / "knowledge_base" / "global_knowledge.md"
INDEX_PATH = ROOT / "data" / "knowledge_base" / "knowledge_index.json"
CHAPTER_PLAN_PATH = ROOT / "outputs" / "debate" / "chapter_plan.json"


def write_chapters(
    chapters: int = 18,
    force: bool = False,
    max_attempts: Optional[int] = None,
    resume_from: int = 1,
) -> List[Dict[str, Any]]:
    ensure_dir(DRAFTS_DIR)
    if not OUTLINE_PATH.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")
    knowledge = KB_PATH.read_text(encoding="utf-8") if KB_PATH.exists() else ""
    outline = OUTLINE_PATH.read_text(encoding="utf-8")
    index = read_json(INDEX_PATH, {})
    chapter_plan = _load_chapter_plan()
    facts = global_facts_summary()
    style_examples = load_style_examples()
    client = LLMClient("write")
    agent_cfg = load_config("agents.yaml")
    if "max_review_attempts" not in agent_cfg:
        raise KeyError("agents.yaml missing required key 'max_review_attempts'")
    continuation_anchor = str(agent_cfg.get("continuation_anchor", "") or "").strip()
    configured_attempts = int(agent_cfg["max_review_attempts"])
    rewrite_limit = int(max_attempts) if max_attempts is not None else configured_attempts
    polish_enabled = bool(agent_cfg.get("polish_pass", True))
    shadow_review_enabled = bool(agent_cfg.get("review_during_lint_block", True))
    linter = NovelLinter()
    reports: List[Dict[str, Any]] = []
    for chapter_no in range(int(resume_from), int(resume_from) + int(chapters)):
        out_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.md"
        if out_path.exists() and not force:
            continue
        rolling_path = DRAFTS_DIR / "rolling_chapter_summary.json"
        rolling_context = render_rolling_context(max_chapters=5, path=rolling_path)
        previous_chapter_ending = latest_ending_state(path=rolling_path)
        chapter_plan_item = _chapter_plan_item(chapter_plan, chapter_no)
        draft = ""
        report: Dict[str, Any] = {}
        feedback = ""
        lint_ok = False
        polish_applied = False
        polish_diff_stats: Dict[str, int] = {}
        lint_blocked_reviews: List[Dict[str, Any]] = []
        last_lint_issues: List[Dict[str, Any]] = []
        last_blocking_reasons: List[Dict[str, Any]] = []
        for attempt in range(1, rewrite_limit + 1):
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
            draft = _complete_write_text(client, messages, cache_segments).strip()
            lint_issues = linter.lint(draft)
            last_lint_issues = lint_issues
            if any(issue["severity"] == "error" for issue in lint_issues):
                if shadow_review_enabled:
                    try:
                        shadow_review = review_text(
                            draft,
                            out_path.name,
                            precomputed_lint_issues=lint_issues,
                            rewrite_round=attempt - 1,
                            run_agents_on_lint_error=True,
                            enforce_relationship_checklist=True,
                        )
                        lint_blocked_reviews.append({"attempt": attempt, "review": shadow_review})
                    except Exception as exc:
                        log_event("write", "shadow_review_error", chapter=chapter_no, error=str(exc))
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
            report = review_text(
                draft,
                out_path.name,
                precomputed_lint_issues=lint_issues,
                rewrite_round=attempt - 1,
                enforce_relationship_checklist=True,
            )
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
                polish_applied = True
                polish_diff_stats = {"pre_chars": pre_chars, "post_chars": len(draft)}

        chapter_summary = _summarize_chapter(client, chapter_no, draft)
        append_chapter_summary(
            chapter_no,
            chapter_summary.get("summary", ""),
            chapter_summary.get("key_events", []),
            chapter_summary.get("ending_state", ""),
            path=DRAFTS_DIR / "rolling_chapter_summary.json",
        )
        proposals = _propose_entity_advance(client, chapter_no, draft, load_entity_graph())
        proposal_path = save_entity_advance_proposals(chapter_no, proposals, drafts_dir=DRAFTS_DIR)

        if not lint_ok:
            failure_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.failure.json"
            meta_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.meta.json"
            failure_report = {
                "chapter": chapter_no,
                "lint_issues": report.get("lint_issues", []),
                "last_attempt": attempt,
                "rewrite_count": max(0, attempt - 1),
                "chinese_char_count": count_chinese_chars(draft),
                "polish_applied": polish_applied,
                "polish_diff_stats": polish_diff_stats,
                "lint_blocked_reviews": lint_blocked_reviews,
                "last_blocking_reasons": last_blocking_reasons,
                "draft_preview": draft[:2000],
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
                "lint_blocked_reviews": lint_blocked_reviews,
                "last_blocking_reasons": last_blocking_reasons,
                "failure_path": str(failure_path),
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
            meta["lint_blocked_reviews"] = lint_blocked_reviews
            if report.get("verdict") != "Approve":
                meta["last_blocking_reasons"] = last_blocking_reasons
            write_text_atomic(out_path, draft + "\n")
            write_json(DRAFTS_DIR / f"chapter_{chapter_no:02d}.meta.json", meta)
            failure_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.failure.json"
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
    return reports


def _index_stats(index: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={len(value) if hasattr(value, '__len__') else 0}" for key, value in index.items())


def _load_chapter_plan() -> Optional[Dict[int, Dict[str, Any]]]:
    if not CHAPTER_PLAN_PATH.exists():
        return None
    data = read_json(CHAPTER_PLAN_PATH, {})
    plan = ChapterPlan(**data)
    return {int(item.chapter_no): model_to_dict(item) for item in plan.chapters}


def _chapter_plan_item(chapter_plan: Optional[Dict[int, Dict[str, Any]]], chapter_no: int) -> Optional[Dict[str, Any]]:
    if chapter_plan is None:
        return None
    item = chapter_plan.get(int(chapter_no))
    if item is None:
        raise ValueError(f"chapter_plan.json exists but has no plan for chapter {chapter_no}")
    return item


def _complete_write_text(client: LLMClient, messages: List[Dict[str, str]], cache_segments: List[Dict[str, Any]]) -> str:
    try:
        return client.complete_text(messages, temperature=0.6, cache_segments=cache_segments)
    except TypeError as exc:
        if "cache_segments" not in str(exc):
            raise
        return client.complete_text(messages, temperature=0.6)


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
    system_prompt = (
        "你是长篇小说续写写作者。只输出正文，不要输出章节编号或解释。"
        "避免反复使用'不是X，是Y'/'不是X而是Y'句式；同章最多出现 2 次。"
        "如需对比，优先用动作/环境替代说明。"
    )
    style_context = ""
    if style_examples:
        style_context = (
            "# 作者风格参考（重点匹配此节奏与含蓄度，不要复制具体情节/人名/场景）\n\n"
            f"{style_examples}\n\n"
            "写作时优先匹配上述风格参考的节奏、含蓄度与意象使用方式；不要复制具体情节、地名、人名或事件。\n\n"
        )
    stable_context = (
        f"{style_context}"
        f"全局知识:\n{knowledge[:9000]}\n\n"
        f"机器索引统计:\n{_index_stats(index)}\n\n"
        f"辩论大纲:\n{outline[:6000]}"
    )
    entity_state = render_active_state(load_entity_graph())
    if entity_state:
        stable_context = (
            f"{stable_context}\n\n"
            f"{entity_state}\n"
            "严格遵守'当前活跃关系'：任何角色互动、人物对彼此的认知、关系描述必须匹配上面 active 状态；"
            "不要编造未列出的关系；不要让角色行为与已确立关系冲突。"
        )
    anchor_context = f"# 续写起点（must-anchor）\n\n{continuation_anchor}\n\n" if continuation_anchor else ""
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
            "严格按上述本章计划写。开场必须是 opening_scene 指定的场景；"
            "必须发生所有 key_events；不要引入计划之外的主要剧情节点。\n\n"
        )
    dynamic_context = (
        f"{anchor_context}"
        "# 本章目标长度\n\n"
        "中文正文 3500-5500 字之间，过短会被自动重写。\n\n"
        f"续写第 {chapter_no} 章。\n\n"
        f"人工全局事实:\n{facts}\n\n"
        f"{rolling_block}"
        f"{ending_block}"
        f"{chapter_plan_block}"
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
                        "只提出正文中有明确触发事件的变化；不确定则返回空 proposed_advances。\n\n"
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
    parts: List[str] = []
    for issue in lint_issues:
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
