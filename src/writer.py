from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ROOT, load_config
from .linter import NovelLinter, count_chinese_chars
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .reviewer import review_text
from .state import log_event, write_text_atomic
from .style import load_style_examples
from .utils import ensure_dir, read_json, write_json


DRAFTS_DIR = ROOT / "outputs" / "drafts"
OUTLINE_PATH = ROOT / "outputs" / "debate" / "outline.md"
KB_PATH = ROOT / "data" / "knowledge_base" / "global_knowledge.md"
INDEX_PATH = ROOT / "data" / "knowledge_base" / "knowledge_index.json"


def write_chapters(
    chapters: int = 18,
    force: bool = False,
    max_attempts: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ensure_dir(DRAFTS_DIR)
    if not OUTLINE_PATH.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")
    knowledge = KB_PATH.read_text(encoding="utf-8") if KB_PATH.exists() else ""
    outline = OUTLINE_PATH.read_text(encoding="utf-8")
    index = read_json(INDEX_PATH, {})
    facts = global_facts_summary()
    style_examples = load_style_examples()
    client = LLMClient("write")
    agent_cfg = load_config("agents.yaml")
    if "max_review_attempts" not in agent_cfg:
        raise KeyError("agents.yaml missing required key 'max_review_attempts'")
    continuation_anchor = str(agent_cfg.get("continuation_anchor", "") or "").strip()
    configured_attempts = int(agent_cfg["max_review_attempts"])
    rewrite_limit = int(max_attempts) if max_attempts is not None else configured_attempts
    linter = NovelLinter()
    reports: List[Dict[str, Any]] = []
    previous_state = ""
    for chapter_no in range(1, chapters + 1):
        out_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.md"
        if out_path.exists() and not force:
            previous_state = out_path.read_text(encoding="utf-8")[-2000:]
            continue
        draft = ""
        report: Dict[str, Any] = {}
        feedback = ""
        lint_ok = False
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
                previous_state=previous_state,
                feedback=feedback,
            )
            draft = _complete_write_text(client, messages, cache_segments).strip()
            lint_issues = linter.lint(draft)
            if any(issue["severity"] == "error" for issue in lint_issues):
                feedback = "请修复 deterministic linter 问题:\n" + "\n".join(issue["message"] for issue in lint_issues)
                last_blocking_reasons = [
                    {"reviewer": "deterministic_linter", "severity": issue.get("severity"), "message": issue.get("message")}
                    for issue in lint_issues
                ]
                report = {"verdict": "Reject", "lint_issues": lint_issues, "attempt": attempt}
                continue
            lint_ok = True
            report = review_text(draft, out_path.name, precomputed_lint_issues=lint_issues, rewrite_round=attempt - 1)
            if report["verdict"] == "Approve":
                last_blocking_reasons = []
                break
            last_blocking_reasons = _blocking_reasons(report)
            feedback = _review_feedback(report)

        if not lint_ok:
            failure_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.failure.json"
            meta_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.meta.json"
            failure_report = {
                "chapter": chapter_no,
                "lint_issues": report.get("lint_issues", []),
                "last_attempt": attempt,
                "rewrite_count": max(0, attempt - 1),
                "chinese_char_count": count_chinese_chars(draft),
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
                "last_blocking_reasons": last_blocking_reasons,
                "failure_path": str(failure_path),
            }
            write_text_atomic(out_path, draft + "\n")
            write_json(meta_path, meta)
            previous_state = draft[-2000:]
            log_event("write", "failure", chapter=chapter_no, reason="lint_errors")
            reports.append({"chapter": chapter_no, "path": str(out_path), "failure_path": str(failure_path), "review": meta, "written": True})
        else:
            meta = dict(report)
            meta["rewrite_count"] = max(0, attempt - 1)
            meta["chinese_char_count"] = count_chinese_chars(draft)
            meta["needs_human_review"] = report.get("verdict") != "Approve"
            if report.get("verdict") != "Approve":
                meta["last_blocking_reasons"] = last_blocking_reasons
            write_text_atomic(out_path, draft + "\n")
            write_json(DRAFTS_DIR / f"chapter_{chapter_no:02d}.meta.json", meta)
            failure_path = DRAFTS_DIR / f"chapter_{chapter_no:02d}.failure.json"
            if failure_path.exists():
                failure_path.unlink()
            previous_state = draft[-2000:]
            reports.append({"chapter": chapter_no, "path": str(out_path), "review": report, "written": True})
            log_event("write", report.get("verdict", "unknown").lower(), chapter=chapter_no, output=str(out_path))
    return reports


def _index_stats(index: Dict[str, Any]) -> str:
    return ", ".join(f"{key}={len(value) if hasattr(value, '__len__') else 0}" for key, value in index.items())


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
    previous_state: str,
    feedback: str,
) -> tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    system_prompt = "你是长篇小说续写写作者。只输出正文，不要输出章节编号或解释。"
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
    anchor_context = f"# 续写起点（must-anchor）\n\n{continuation_anchor}\n\n" if continuation_anchor else ""
    dynamic_context = (
        f"{anchor_context}"
        "# 本章目标长度\n\n"
        "中文正文 3500-5500 字之间，过短会被自动重写。\n\n"
        f"续写第 {chapter_no} 章。\n\n"
        f"人工全局事实:\n{facts}\n\n"
        f"上一章状态:\n{previous_state}\n\n"
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


def _review_feedback(report: Dict[str, Any]) -> str:
    parts: List[str] = []
    for issue in report.get("lint_issues", []):
        parts.append(issue.get("message", ""))
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
