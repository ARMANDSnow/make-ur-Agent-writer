from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .config import ROOT
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

    client = LLMClient("plot_planner")
    prompt = _build_planner_prompt(
        target_chapters=target_chapters,
        outline=outline,
        entity_state=entity_state,
        style_examples=style_examples,
        facts=facts,
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


def _build_planner_prompt(
    *,
    target_chapters: int,
    outline: str,
    entity_state: str,
    style_examples: str,
    facts: str,
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
    return (
        f"请基于下列资料制定 {target_chapters} 章续写大纲。你不是写正文，而是给 writer 的执行计划。\n\n"
        "# 硬性要求\n\n"
        "1. 输出必须是一个 JSON object，完全符合 ChapterPlan schema。\n"
        "2. chapters 数量必须等于 target_chapters，chapter_no 从 1 连续递增。\n"
        "3. 每章 key_events 必须 2-5 条，都是 writer 必须写进正文的具体事件。\n"
        "4. opening_scene 必须是一句话具体场景，说明谁在什么地点做什么；不能写成抽象主题。\n"
        "5. ending_hook 必须暗示下一章可承接的动作、发现或关系变化。\n"
        "6. 不要安排计划外的大转向；每章 plot_purpose 说明它在全书节奏中的作用。\n"
        "7. 如实体关系状态与辩论大纲冲突，以实体关系状态和已发生事实优先。\n\n"
        f"# ChapterPlan JSON schema\n\n{schema}\n\n"
        f"{style_block}"
        f"{facts_block}"
        f"{entity_block}"
        f"# 辩论大纲\n\n{outline[:12000]}\n"
    )
