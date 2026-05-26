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


def generate_chapter_plan(target_chapters: int = 18, force: bool = False) -> Dict[str, Any]:
    chapter_plan_path = _chapter_plan_path()
    outline_path = _outline_path()
    if chapter_plan_path.exists() and not force:
        raise FileExistsError("chapter_plan.json already exists; use --force to overwrite")
    if not outline_path.exists():
        raise FileNotFoundError("outline not found; run `python main.py debate` first")

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

    client = LLMClient("plot_planner")
    prompt = _build_planner_prompt(
        target_chapters=target_chapters,
        outline=outline,
        entity_state=entity_state,
        style_examples=style_examples,
        facts=facts,
        knowledge=knowledge,
        rolling_summary=rolling,
        continuation_anchor=anchor,
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
    data = model_to_dict(result)
    write_json(chapter_plan_path, data)
    return data


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
        "用户配置的起点是新一轮规划的真实出发点。\n\n"
        f"# ChapterPlan JSON schema\n\n{schema}\n\n"
        f"{knowledge_block}"
        f"{anchor_block}"
        f"{style_block}"
        f"{facts_block}"
        f"{entity_block}"
        f"{rolling_block}"
        f"# 辩论大纲\n\n{outline[:12000]}\n"
    )
