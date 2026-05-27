"""Iter 023: scene-matched original-text excerpt library.

iter 021/022 fed writer + reviewer "起点前 K 章" of the source novel as
style anchor — but that's a hard time-slice. Writing a battle chapter
got injected with the 3 chapters before the start point regardless of
whether those were daily-life or fight scenes. This module solves the
mismatch:

1. A bootstrap LLM call (see `auto_bootstrap.bootstrap_source_excerpts`)
   produces 15-20 tagged excerpts spanning multiple scene archetypes
   (战斗, 心理, 对话, 场景描写, 异能, 情感).
2. Writer/reviewer call `select_for_chapter(plan_item, k=3)` to get
   archetype-matched excerpts based on the upcoming chapter's
   key_events + opening_scene.

The selector is deterministic keyword-overlap scoring (no LLM call per
chapter). Embedding-based selection is iter 026+ work — iter 023 just
needs a working v1.

API:

    load_excerpts() -> List[Dict]
    select_for_chapter(plan_item, k=3) -> List[Dict]
    format_excerpts_for_prompt(excerpts, limit_chars=8000) -> str

All workspace-aware via ``src.paths``. Backwards-compatible: when
``data/source_excerpts/excerpts.json`` is absent, `load_excerpts()`
returns ``[]`` and `select_for_chapter` returns ``[]`` — writer/reviewer
prompts then omit the excerpt block entirely (byte-identical to iter
022 behavior).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .utils import read_json


_EXCERPTS_DIR_NAME = "source_excerpts"
_EXCERPTS_FILE = "excerpts.json"


# Iter 023 keyword → scene_type heuristic mapping. Extend by adding to
# the dict; ordering doesn't matter (each scene_type can match multiple
# keyword groups). Keywords are matched as substrings against the
# combined text of plan_item.key_events + plan_item.opening_scene.
_KEYWORD_TO_SCENE: Dict[str, List[str]] = {
    "战斗": [
        "战斗", "对决", "对峙", "拔剑", "射击", "子弹", "火箭筒",
        "长枪", "枪", "斩", "杀", "刀", "格斗", "厮杀", "攻击",
        "防御", "出手", "交手", "炸", "爆炸", "弹头", "瞄准",
    ],
    "心理": [
        "梦", "回忆", "胸口", "闪回", "蹲守", "脑海", "幻觉",
        "幻象", "意识", "潜意识", "内心", "独白", "想起",
        "记忆", "感受", "情绪",
    ],
    "对话": [
        "说道", "问道", "答道", "回答", "开口", "低声", "交谈",
        "对话", "交流", "告诉", "解释", "询问",
    ],
    "场景描写": [
        "走进", "看见", "雨", "火", "暗", "黄昏", "黎明", "夜",
        "走廊", "教室", "礼堂", "广场", "天空", "建筑", "城市",
        "街道", "房间", "宿舍",
    ],
    "异能": [
        "言灵", "共鸣", "龙文", "血统", "血脉", "血之", "异能",
        "觉醒", "显现", "印记", "符文", "斯雷普尼尔", "昆古尼尔",
        "尼伯龙根", "皇帝", "黑王", "白王", "青铜", "弗里嘉",
    ],
    "情感": [
        "拥抱", "抱", "拥", "哭", "笑", "心动", "悸动", "羞涩",
        "温柔", "亲", "吻", "牵手", "依偎", "凝视", "对视",
        "心疼", "怜惜",
    ],
}


def _excerpts_path() -> Path:
    """Return per-workspace path to excerpts.json."""
    return paths.data_dir() / _EXCERPTS_DIR_NAME / _EXCERPTS_FILE


def load_excerpts() -> List[Dict[str, Any]]:
    """Return the full excerpt list from disk, or ``[]`` if absent / malformed."""
    p = _excerpts_path()
    if not p.exists():
        return []
    data = read_json(p, {})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("excerpts", [])
    return []


def _extract_text_for_matching(plan_item: Dict[str, Any]) -> str:
    """Join plan_item.key_events + opening_scene + ending_hook into a
    single matching string. Defensive against missing keys."""
    if not plan_item:
        return ""
    parts: List[str] = []
    op = plan_item.get("opening_scene")
    if isinstance(op, str):
        parts.append(op)
    for k in plan_item.get("key_events", []) or []:
        if isinstance(k, str):
            parts.append(k)
    eh = plan_item.get("ending_hook")
    if isinstance(eh, str):
        parts.append(eh)
    return " ".join(parts)


def _detect_scene_types(plan_text: str) -> List[str]:
    """Return scene_types whose keywords appear in plan_text, sorted by
    descending match count."""
    counts: Dict[str, int] = {}
    for scene_type, keywords in _KEYWORD_TO_SCENE.items():
        n = sum(1 for kw in keywords if kw and kw in plan_text)
        if n > 0:
            counts[scene_type] = n
    return [st for st, _ in sorted(counts.items(), key=lambda kv: -kv[1])]


def _score_excerpt(excerpt: Dict[str, Any], plan_text: str, detected_scenes: List[str]) -> int:
    """Score a single excerpt against the plan. Higher = better match.

    Scoring:
    * +5 if excerpt.scene_type appears in detected_scenes (top scene_type
      = +5, second = +4, etc., capped at 1)
    * +2 per character in excerpt.character_focus that appears in plan_text
    * +1 per tag in excerpt.tags that appears in plan_text
    """
    if not excerpt or not isinstance(excerpt, dict):
        return 0
    score = 0
    scene_type = excerpt.get("scene_type", "")
    if scene_type in detected_scenes:
        # Top-detected scene_type gets the most weight
        try:
            rank = detected_scenes.index(scene_type)
            score += max(1, 5 - rank)
        except ValueError:
            pass
    for char in excerpt.get("character_focus", []) or []:
        if isinstance(char, str) and char and char in plan_text:
            score += 2
    for tag in excerpt.get("tags", []) or []:
        if isinstance(tag, str) and tag and tag in plan_text:
            score += 1
    return score


def select_for_chapter(plan_item: Optional[Dict[str, Any]], k: int = 3) -> List[Dict[str, Any]]:
    """Return up to K excerpts matching the chapter plan's scene types.

    Returns empty list when:
    * plan_item is None / empty
    * excerpts.json doesn't exist
    * k <= 0
    * no excerpt scores above 0 (no overlap at all)

    The k-cap is a hard upper bound; fewer may be returned if matches
    are sparse.
    """
    if k <= 0 or not plan_item:
        return []
    excerpts = load_excerpts()
    if not excerpts:
        return []
    plan_text = _extract_text_for_matching(plan_item)
    if not plan_text:
        return []
    detected = _detect_scene_types(plan_text)
    scored = [
        (_score_excerpt(ex, plan_text, detected), ex) for ex in excerpts
    ]
    scored = [(s, ex) for s, ex in scored if s > 0]
    scored.sort(key=lambda pair: -pair[0])
    return [ex for _, ex in scored[:k]]


def format_excerpts_for_prompt(
    excerpts: List[Dict[str, Any]], limit_chars: int = 8000
) -> str:
    """Format selected excerpts as a single text block for prompt injection.

    Format per excerpt:
        ### {scene_type} | 来自 {source_chapter_id}
        ({description})

        {excerpt_text}

    Separator between excerpts: ``\\n\\n---\\n\\n``.
    Total output truncated to ``limit_chars`` characters.
    """
    if not excerpts:
        return ""
    parts: List[str] = []
    for ex in excerpts:
        scene_type = ex.get("scene_type", "未分类")
        chapter_id = ex.get("source_chapter_id", "?")
        description = ex.get("description", "").strip()
        text = ex.get("excerpt_text", "").strip()
        if not text:
            continue
        header = f"### {scene_type} | 来自 {chapter_id}"
        if description:
            header += f"\n（{description}）"
        parts.append(f"{header}\n\n{text}")
    if not parts:
        return ""
    out = "\n\n---\n\n".join(parts)
    return out[:limit_chars]
