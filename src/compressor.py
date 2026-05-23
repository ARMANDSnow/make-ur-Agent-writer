from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from pathlib import Path

from . import paths
from .config import ROOT
from .llm_client import LLMClient
from .manual_facts import global_facts_summary, load_global_facts
from .state import log_event, write_text_atomic
from .utils import ensure_dir, read_json, write_json


# Legacy constants — kept for iter 014-016 test backward compat.
EXTRACTED_DIR = ROOT / "data" / "extracted_jsons"
KB_DIR = ROOT / "data" / "knowledge_base"


def _extracted_dir() -> Path:
    return paths.extracted_dir() if paths.workspace_name() else EXTRACTED_DIR


def _kb_dir() -> Path:
    return paths.knowledge_base_dir() if paths.workspace_name() else KB_DIR


def load_extractions() -> List[Dict[str, Any]]:
    return [read_json(path, {}) for path in sorted(_extracted_dir().glob("*.json"))]


def build_knowledge_index(extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
    index: Dict[str, Any] = {
        "characters": defaultdict(list),
        "relationships": [],
        "foreshadowing": [],
        "worldbuilding": [],
        "style_samples": [],
        "chapters": {},
        "manual_global_facts": load_global_facts(),
    }
    for item in extractions:
        chapter_id = item.get("chapter_id")
        index["chapters"][chapter_id] = {
            "volume_id": item.get("volume_id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
        }
        for state in item.get("character_states", []):
            index["characters"][state.get("character", "")].append({"chapter_id": chapter_id, **state})
        index["relationships"].extend({"chapter_id": chapter_id, **rel} for rel in item.get("relationships", []))
        index["foreshadowing"].extend({"chapter_id": chapter_id, **fo} for fo in item.get("foreshadowing", []))
        index["worldbuilding"].extend({"chapter_id": chapter_id, **wb} for wb in item.get("worldbuilding", []))
        index["style_samples"].extend({"chapter_id": chapter_id, **sample} for sample in item.get("style_samples", []))
    index["characters"] = dict(index["characters"])
    return index


def compress_all() -> Dict[str, Any]:
    kb_dir = _kb_dir()
    ensure_dir(kb_dir)
    extractions = load_extractions()
    if not extractions:
        raise FileNotFoundError("no extracted JSON files found; run `python main.py extract --volume all` first")
    index = build_knowledge_index(extractions)
    client = LLMClient("compress")
    if client.is_mock:
        text = _mock_knowledge_markdown(extractions, index)
    else:
        summaries = "\n".join(f"- {item.get('chapter_id')}: {item.get('summary')}" for item in extractions)
        facts = global_facts_summary()
        text = client.complete_text(
            [
                {"role": "system", "content": "你是长篇小说知识库压缩器，输出 Markdown。"},
                {
                    "role": "user",
                    "content": (
                        "请根据章节 JSON 摘要压缩成全局叙事知识文档，包含角色档案、关系网络、"
                        "未闭合伏笔、世界观硬约束和写作风格规则。\n\n"
                        f"{facts}\n\n"
                        f"{summaries[:24000]}"
                    ),
                },
            ]
        )
    write_text_atomic(kb_dir / "global_knowledge.md", text.strip() + "\n")
    write_json(kb_dir / "knowledge_index.json", index)
    log_event("compress", "done", chapters=len(extractions), output=str(kb_dir / "global_knowledge.md"))
    return index


def _mock_knowledge_markdown(extractions: List[Dict[str, Any]], index: Dict[str, Any]) -> str:
    by_volume: Dict[str, int] = defaultdict(int)
    for item in extractions:
        by_volume[str(item.get("volume_id"))] += 1
    lines = [
        "# 龙族全局叙事知识文档",
        "",
        "## 卷级覆盖",
    ]
    for volume_id, count in sorted(by_volume.items()):
        lines.append(f"- {volume_id}: 已提取 {count} 个章节。")
    lines.extend(
        [
            "",
            "## 角色档案",
            f"- 已索引角色状态变更 {sum(len(v) for v in index['characters'].values())} 条。",
            "",
            "## 人工全局事实",
            f"- 已加载人工全局事实 {len(index.get('manual_global_facts', []))} 条。",
            "",
            "## 关系网络",
            f"- 已索引关系变化 {len(index['relationships'])} 条。",
            "",
            "## 未闭合伏笔",
            f"- 已索引伏笔/回收 {len(index['foreshadowing'])} 条。",
            "",
            "## 世界观硬约束",
            f"- 已索引世界观规则 {len(index['worldbuilding'])} 条。",
            "",
            "## 江南写作特征",
            f"- 已索引风格样本 {len(index['style_samples'])} 条。",
        ]
    )
    return "\n".join(lines)
