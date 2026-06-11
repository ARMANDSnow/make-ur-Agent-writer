"""Markdown rendering for chat replies (iter 049).

Pure functions: no client, no I/O. Aeloon's WebUI renders these as GFM
Markdown; the trailing deep-link is a clickable ``http://`` link that opens
the four-stage workbench in a new tab.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# workbench stage -> human label (mirrors src/web/routes.py api_workbench_status)
STAGE_LABELS = {
    "prepare": "① 设定准备",
    "outline": "② 故事大纲",
    "plan": "③ 章节细纲",
    "write": "④ 正文写作",
    "done": "✅ 全部完成",
}

# run step -> human label (mirrors src/web/jobs.py STEP_HANDLERS)
STEP_LABELS = {
    "prepare-greenfield": "设定准备",
    "debate": "故事大纲（多智能体辩论）",
    "plan-chapters": "章节细纲",
    "write-book": "正文写作",
}


def step_label(step: str) -> str:
    return STEP_LABELS.get(step, step)


def open_link(url: str, text: str = "在工作台中查看 / 精修") -> str:
    return f"[{text}]({url})"


def fmt_created(book: str, url: str) -> str:
    return (
        f"✅ 已创建《{book}》并完成**设定准备**。\n\n"
        f"下一步：`/novel outline` 生成章节细纲，或 `/novel auto` 一键续写到正文。\n\n"
        f"{open_link(url)}"
    )


def fmt_api_error(book: Optional[str], exc: Any) -> str:
    """Render a NovelApiError (duck-typed: ``.status_code`` / ``.message``)."""
    code = getattr(exc, "status_code", 0)
    msg = getattr(exc, "message", str(exc))
    if code == 0:
        return f"❌ 连不上续写服务。请确认已运行 `python3 main.py web`。\n\n> {msg}"
    if code == 404:
        return f"❌ 找不到工作区{f'《{book}》' if book else ''}。用 `/novel list` 看现有书单。"
    if code == 409:
        running = getattr(exc, "running_job_id", None)
        extra = f"（运行中的任务 id：`{running}`）" if running else ""
        return f"⏳ 《{book}》已有任务在跑{extra}，请等它结束再试。"
    return f"❌ 续写服务返回错误（HTTP {code}）：{msg}"


def fmt_need_book(names: List[str]) -> str:
    if not names:
        return "📭 还没有任何作品。用 `/novel new <一句话设定>` 开一本新书。"
    listed = "、".join(f"`{n}`" for n in names[:20])
    return (
        "请指定书名，例如 `/novel status <书名>`。当前作品：\n\n"
        f"{listed}"
    )


def fmt_list(names: List[str]) -> str:
    if not names:
        return "📭 还没有任何作品。用 `/novel new <一句话设定>` 开一本新书。"
    lines = "\n".join(f"- `{n}`" for n in names)
    return f"📚 当前共 {len(names)} 部作品：\n\n{lines}"


def fmt_status(book: str, wb: Dict[str, Any], url: str) -> str:
    stage = str(wb.get("stage") or "")
    label = STAGE_LABELS.get(stage, stage or "未知")
    drafts = wb.get("draft_count") or 0
    flags = []
    if wb.get("has_kb"):
        flags.append("设定✓")
    if wb.get("has_outline"):
        flags.append("大纲✓")
    if wb.get("has_plan"):
        flags.append("细纲✓")
    if drafts:
        flags.append(f"正文 {drafts} 章")
    trail = "（" + " · ".join(flags) + "）" if flags else ""
    return f"📖 《{book}》当前进度：**{label}**{trail}\n\n{open_link(url)}"


def fmt_job_failure(book: str, step: str, job: Dict[str, Any], url: str) -> str:
    """Render a non-succeeded terminal job (blocked / failed / aborted / …)."""
    status = str(job.get("status") or "")
    summary = job.get("result_summary") if isinstance(job.get("result_summary"), dict) else {}
    if status == "blocked":
        first = summary.get("first_blocked") if isinstance(summary, dict) else None
        reason = (first or {}).get("reason") if isinstance(first, dict) else None
        detail = (first or {}).get("error") if isinstance(first, dict) else None
        body = f"原因：`{reason}`" if reason else "（缺少前置条件）"
        if detail:
            body += f"\n\n> {detail}"
        return (
            f"⚠️ 《{book}》的「{step_label(step)}」被拦截。\n\n{body}\n\n"
            f"可在工作台里补齐后重试。{open_link(url)}"
        )
    if status == "budget_exceeded":
        return (
            f"💸 《{book}》的「{step_label(step)}」超出预算已停。"
            f"可调高预算后重试。\n\n{open_link(url)}"
        )
    err = job.get("error") or "未知错误"
    trace = job.get("trace_id")
    tail = f"\n\n> trace_id: `{trace}`" if trace else ""
    return f"❌ 《{book}》的「{step_label(step)}」{status}：{err}{tail}\n\n{open_link(url)}"


def fmt_write_result(book: str, job: Dict[str, Any], url: str) -> str:
    summary = job.get("result_summary") if isinstance(job.get("result_summary"), dict) else {}
    chapters = summary.get("chapters") or 0
    cost = summary.get("cost_cny")
    cost_str = f"，花费 ¥{cost:.2f}" if isinstance(cost, (int, float)) else ""
    partial = summary.get("partial")
    blocked = summary.get("blocked") or 0
    head = f"✅ 《{book}》新写 **{chapters} 章**{cost_str}。"
    if partial or blocked:
        head = f"⚠️ 《{book}》部分完成：写了 {chapters} 章{cost_str}，有 {blocked} 章被拦截。"
    return f"{head}\n\n{open_link(url, '在工作台中阅读 / 续写')}"


def fmt_outline_result(book: str, plan: Dict[str, Any], url: str) -> str:
    """Render the chapter plan returned by GET /plan (collect_plan)."""
    plan_obj = plan.get("plan") if isinstance(plan, dict) else None
    chapters = plan_obj.get("chapters") if isinstance(plan_obj, dict) else None
    if not isinstance(chapters, list) or not chapters:
        return f"✅ 《{book}》细纲已生成。\n\n{open_link(url, '在工作台中查看 / 精修细纲')}"
    lines = []
    for idx, ch in enumerate(chapters[:12], start=1):
        title = ""
        if isinstance(ch, dict):
            title = ch.get("title") or ch.get("name") or ch.get("summary") or ""
        lines.append(f"{idx}. {str(title)[:60]}" if title else f"{idx}. 第 {idx} 章")
    more = f"\n…… 共 {len(chapters)} 章" if len(chapters) > 12 else ""
    body = "\n".join(lines)
    return (
        f"✅ 《{book}》细纲已生成（{len(chapters)} 章）：\n\n{body}{more}\n\n"
        f"满意就 `/novel write` 开写；想改就 {open_link(url, '在工作台中精修细纲')}"
    )


def fmt_readiness_block(book: str, readiness: Dict[str, Any], url: str) -> str:
    blockers = readiness.get("blockers") or []
    recs = readiness.get("recommended_commands") or []
    blk = "\n".join(f"- {b}" for b in blockers) or "- （未知）"
    rec = "\n".join(f"- `{r}`" for r in recs)
    rec_block = f"\n\n建议：\n{rec}" if rec else ""
    return (
        f"⚠️ 《{book}》还不能写正文，缺少前置条件：\n\n{blk}{rec_block}\n\n"
        f"通常先 `/novel outline` 生成细纲。{open_link(url)}"
    )
