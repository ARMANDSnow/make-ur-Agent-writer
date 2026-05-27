from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .config import ROOT
from .continuation_anchor import load_continuation_anchor
from .entities import load_entity_graph, render_active_state
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .schemas import ChapterPlan, model_to_dict, model_to_json_schema
from .style import load_style_examples
from .utils import write_json


# Legacy constants — kept for iter 014-016 test backward compat
# (``patch("src.plot_planner.OUTLINE_PATH", ...)`` still works).
CHAPTER_PLAN_PATH = ROOT / "outputs" / "debate" / "chapter_plan.json"
OUTLINE_PATH = ROOT / "outputs" / "debate" / "outline.md"


def _chapter_plan_path() -> Path:
    return paths.chapter_plan_path() if paths.workspace_name() else CHAPTER_PLAN_PATH


def _outline_path() -> Path:
    return paths.outline_path() if paths.workspace_name() else OUTLINE_PATH


def generate_chapter_plan(
    target_chapters: int = 18,
    force: bool = False,
    *,
    append_count: int = 0,
    from_chapter: int = 0,
) -> Dict[str, Any]:
    """Iter 024 P2: append mode. When ``append_count > 0``, preserves
    chapters 1..from_chapter from the existing chapter_plan.json and
    appends ``append_count`` new chapters numbered
    ``from_chapter+1 .. from_chapter+append_count``.

    The LLM call now gets the existing plan tail + rolling_summary so
    the new chapters continue from what has actually been written, not
    from a fresh outline read. Updates ``target_chapters`` to the new
    total (existing kept + new appended).

    Default (append_count=0) = iter 023 behavior: write a fresh
    ``target_chapters``-length plan.
    """
    chapter_plan_path = _chapter_plan_path()
    outline_path = _outline_path()
    if not outline_path.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")

    # Iter 024: append mode pre-reads existing plan, preserves head.
    existing_chapters: list = []
    if append_count > 0:
        if not chapter_plan_path.exists():
            raise FileNotFoundError(
                "cannot --append without existing chapter_plan.json; run plan-chapters first"
            )
        from .utils import read_json as _read_json
        existing = _read_json(chapter_plan_path, {})
        all_existing = existing.get("chapters", []) or []
        existing_chapters = all_existing[:from_chapter] if from_chapter > 0 else all_existing
    elif chapter_plan_path.exists() and not force:
        raise FileExistsError("chapter_plan.json already exists; use --force to overwrite")

    outline = outline_path.read_text(encoding="utf-8")
    entity_state = render_active_state(load_entity_graph())
    style_examples = load_style_examples()[:3000]
    facts = global_facts_summary()
    # Iter 021: plot_planner used to plan a 30-chapter arc without ever
    # seeing the KB (compress output), the rolling chapter summary from
    # already-written chapters, or the continuation_anchor. Result:
    # re-plans were "blind" — same plot beats invented over and over,
    # and changing start_point + bootstrap-anchor still produced plans
    # rooted in the old outline / KB. Inject all three so re-planning
    # can respond to actual story progress AND honor the configured
    # start point. The anchor in particular is the iter 021 fix for
    # "I set start=longzu_4 but plan still says 3E exam".
    knowledge = _load_knowledge()
    rolling = _load_rolling_summary()
    anchor = load_continuation_anchor()

    # Iter 024: when in append mode, ask LLM for exactly `append_count`
    # chapters numbered starting at `from_chapter + 1`. The prompt also
    # includes a compact summary of the kept chapters so the LLM produces
    # genuine continuation.
    if append_count > 0:
        llm_target = append_count
        existing_tail_block = _format_existing_tail(existing_chapters)
        starting_chapter_no = from_chapter + 1
    else:
        llm_target = target_chapters
        existing_tail_block = ""
        starting_chapter_no = 1

    client = LLMClient("plot_planner")
    prompt = _build_planner_prompt(
        target_chapters=llm_target,
        outline=outline,
        entity_state=entity_state,
        style_examples=style_examples,
        facts=facts,
        knowledge=knowledge,
        rolling_summary=rolling,
        continuation_anchor=anchor,
        existing_tail=existing_tail_block,
        starting_chapter_no=starting_chapter_no,
    )
    result = client.complete_json(
        [
            {
                "role": "system",
                "content": "你是长篇小说总编。你只制定章节级写作计划，不写正文。",
            },
            {"role": "user", "content": prompt},
        ],
        ChapterPlan,
    )
    new_data = model_to_dict(result)
    if append_count > 0:
        # Merge: existing head + LLM-produced tail. Renumber new chapters
        # to start at from_chapter + 1 in case the LLM ignored the hint.
        new_chapters = list(new_data.get("chapters", []) or [])
        for offset, ch in enumerate(new_chapters):
            ch["chapter_no"] = from_chapter + 1 + offset
        merged_chapters = list(existing_chapters) + new_chapters
        # Preserve overall_arc from existing (don't let LLM rewrite the
        # global arc just because it's appending a tail).
        from .utils import read_json as _read_json
        old = _read_json(chapter_plan_path, {})
        data: Dict[str, Any] = {
            "target_chapters": len(merged_chapters),
            "overall_arc": old.get("overall_arc", new_data.get("overall_arc", "")),
            "chapters": merged_chapters,
            "generated_by": (
                f"plot_planner_v1_append (existing 1..{from_chapter} preserved, "
                f"ch{from_chapter+1}..{from_chapter+append_count} new)"
            ),
        }
    else:
        data = new_data
    write_json(chapter_plan_path, data)
    return data


def _format_existing_tail(existing_chapters: list, k: int = 5) -> str:
    """Iter 024: compact summary of the last K existing chapters for the
    re-plan LLM, so it produces real continuation. Empty when no existing."""
    if not existing_chapters:
        return ""
    tail = existing_chapters[-k:]
    lines = ["# 已存在 plan 章节末尾（最近 {} 章）— 新规划必须从这之后接续：".format(len(tail))]
    for ch in tail:
        if not isinstance(ch, dict):
            continue
        no = ch.get("chapter_no", "?")
        title = str(ch.get("title", ""))[:30]
        hook = str(ch.get("ending_hook", ""))[:200]
        lines.append(f"- ch{no} 「{title}」 末钩：{hook}")
    return "\n".join(lines) + "\n"


def _load_knowledge() -> str:
    """Iter 021: read global_knowledge.md, truncated. Empty string if absent."""
    p = paths.kb_path() if paths.workspace_name() else ROOT / "data" / "knowledge_base" / "global_knowledge.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")[:5000]


def _load_rolling_summary() -> str:
    """Iter 021: read last 3 rolling-summary entries as compact block. Empty
    string if rolling_chapter_summary.json doesn't exist or has no entries.

    Handles both ``{"chapters": [...]}`` (current schema produced by
    ``chapter_summary.append_chapter_summary``) and the legacy
    ``{"entries": [...]}`` form just in case.
    """
    p = paths.rolling_summary_path() if paths.workspace_name() else ROOT / "outputs" / "drafts" / "rolling_chapter_summary.json"
    if not p.exists():
        return ""
    from .utils import read_json
    data = read_json(p, {})
    if not isinstance(data, dict):
        return ""
    entries = data.get("chapters") or data.get("entries") or []
    if not entries:
        return ""
    last_n = entries[-3:]
    pieces = []
    for e in last_n:
        ch_no = e.get("chapter_no", "?")
        summary = (e.get("summary") or e.get("rolling_summary") or "")[:1000]
        if summary:
            pieces.append(f"### ch{ch_no}\n{summary}")
    return "\n\n".join(pieces)


def _build_planner_prompt(
    *,
    target_chapters: int,
    outline: str,
    entity_state: str,
    style_examples: str,
    facts: str,
    knowledge: str = "",
    rolling_summary: str = "",
    continuation_anchor: str = "",
    existing_tail: str = "",
    starting_chapter_no: int = 1,
) -> str:
    schema = json.dumps(model_to_json_schema(ChapterPlan), ensure_ascii=False, indent=2)
    style_block = (
        "# 作者风格参考（只用于节奏和含蓄度，不要复制原句或具体情节）\n\n"
        f"{style_examples}\n\n"
        if style_examples
        else ""
    )
    entity_block = f"# 当前实体关系状态\n\n{entity_state}\n\n" if entity_state else ""
    facts_block = f"# 人工全局事实\n\n{facts}\n\n" if facts else ""
    # Iter 021: KB + rolling summary + continuation anchor blocks. KB gives
    # the planner the same world-knowledge window the writer sees; rolling
    # summary lets re-plans respond to chapters that have actually been
    # written; anchor pins the plan to the configured start point so
    # `set-start-point + bootstrap-anchor + plan-chapters` is a coherent
    # pipeline instead of three disconnected steps.
    knowledge_block = (
        f"# 全局知识 (KB)\n\n{knowledge}\n\n" if knowledge else ""
    )
    rolling_block = (
        "# 已写章节滚动摘要（最近 3 章）\n\n"
        f"{rolling_summary}\n\n"
        "新规划必须接续上述已写章节，不与已发生事件冲突。\n\n"
        if rolling_summary
        else ""
    )
    anchor_block = (
        "# 续写起点 (must-anchor — 最高优先级)\n\n"
        f"{continuation_anchor}\n\n"
        "本次规划必须从上述起点状态继续。如果辩论大纲与起点状态描述不同的"
        "时空 / 角色状态，**以起点状态为准** — 大纲在起点之前的内容不要"
        "重新规划。第 1 章的 opening_scene 必须明确发生在起点状态之后的"
        "时空。\n\n"
        if continuation_anchor
        else ""
    )
    # Iter 024: append mode adds existing chapter tail summaries so the
    # LLM-produced new chapters genuinely continue. Also requests
    # chapter_no to start at starting_chapter_no instead of 1.
    existing_tail_block = (
        f"{existing_tail}\n\n"
        f"新规划的 ch1 实际对应整书第 {starting_chapter_no} 章；ch2 对应"
        f"第 {starting_chapter_no + 1} 章，依此类推。chapter_no 字段在"
        f"输出 JSON 中**仍从 1 开始连续编号**（merge 时由后处理重编号），"
        f"但情节必须从『{starting_chapter_no - 1} 章末状态』承接。\n\n"
        if existing_tail
        else ""
    )
    return (
        f"请基于下列资料制定 {target_chapters} 章续写大纲。你不是写正文，而是给 writer 的执行计划。\n\n"
        "# 硬性要求\n\n"
        "1. 输出必须是一个 JSON object，完全符合 ChapterPlan schema。\n"
        "2. chapters 数量必须等于 target_chapters，chapter_no 从 1 连续递增。\n"
        "3. 每章 key_events 必须 2-5 条，都是 writer 必须写进正文的具体事件。\n"
        "4. opening_scene 必须是一句话具体场景，说明谁在什么地点做什么；不能写成抽象主题。\n"
        "5. ending_hook 必须暗示下一章可承接的动作、发现或关系变化。\n"
        "6. 不要安排计划外的大转向；每章 plot_purpose 说明它在全书节奏中的作用。\n"
        "7. 如实体关系状态与辩论大纲冲突，以实体关系状态和已发生事实优先。\n"
        "8. 如已写章节滚动摘要与辩论大纲冲突，以已写章节为准（已发生 > 计划）。\n"
        "9. 如续写起点 (must-anchor) 与辩论大纲冲突，以起点状态为准 — "
        "用户配置的起点是新一轮规划的真实出发点。\n"
        "10. 如已存在 plan 末尾章节给出（append 模式），新规划必须从其 ending_hook 自然承接。\n\n"
        f"# ChapterPlan JSON schema\n\n{schema}\n\n"
        f"{knowledge_block}"
        f"{anchor_block}"
        f"{style_block}"
        f"{facts_block}"
        f"{entity_block}"
        f"{rolling_block}"
        f"{existing_tail_block}"
        f"# 辩论大纲\n\n{outline[:12000]}\n"
    )
