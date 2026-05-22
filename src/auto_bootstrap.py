from __future__ import annotations

"""Generate reviewable bootstrap proposals from local novel data."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import ROOT
from .llm_client import LLMClient
from .schemas import (
    ContinuationAnchorProposal,
    EntityGraphProposal,
    GlobalFactsProposal,
    StyleExamplesProposal,
    model_to_dict,
    model_to_json_schema,
)
from .utils import ensure_dir, read_json, write_json


PROPOSALS_DIR = ROOT / "data" / "proposals"
EXTRACTED_DIR = ROOT / "data" / "extracted_jsons"
NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
GLOBAL_FACTS_PATH = ROOT / "data" / "manual_overrides" / "global_facts.json"
ENTITY_GRAPH_PATH = ROOT / "data" / "entity_graph.json"
CONTINUATION_ANCHOR_PATH = ROOT / "data" / "manual_overrides" / "continuation_anchor.txt"
STYLE_EXAMPLES_DIR = ROOT / "data" / "style_examples"


def bootstrap_global_facts(force: bool = False, root: Path = ROOT) -> Dict[str, Any]:
    path = _proposal_path("global_facts", root)
    existing = root / "data" / "manual_overrides" / "global_facts.json"
    if _has_manual_json(existing) and not force:
        return _skip_result("global_facts", path)

    prompt = _build_json_prompt(
        title="global_facts",
        schema=model_to_json_schema(GlobalFactsProposal),
        instructions=(
            "请从章节抽取 JSON 中客观提炼 5-15 条全局事实 proposal。只写已经发生或明确成立的事实，"
            "关注角色当前状态、关键事件、死亡/失踪、重要物品和世界观硬约束。"
            "evidence_spans 只能保留 source_file/chapter_id/start_line/end_line/note，quote 必须为空字符串。"
        ),
        context=_extractions_context(root, limit_chars=50000),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), GlobalFactsProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "global_facts",
        "审核 fact 是否客观、当前有效、没有模型脑补；可编辑后再 apply。",
    )
    data = _strip_quotes(data)
    write_json(path, data)
    return {"name": "global_facts", "status": "written", "path": str(path), "data": data}


def bootstrap_entity_graph(force: bool = False, root: Path = ROOT) -> Dict[str, Any]:
    path = _proposal_path("entity_graph", root)
    existing = root / "data" / "entity_graph.json"
    if _has_manual_json(existing) and not force:
        return _skip_result("entity_graph", path)

    prompt = _build_json_prompt(
        title="entity_graph",
        schema=model_to_json_schema(EntityGraphProposal),
        instructions=(
            "请从章节抽取 JSON 中客观生成 entity_graph proposal，不要创作新设定。"
            "至少 10 个 entities、5 个 relationships；实体含 id/name/type/aliases/tags/key_facts/description。"
            "tags 用 #名词；relationship timeline 最后一个节点 active=true，其余 active=false。"
            "所有 key_facts/state/description 都用自己的话概括，不要复制原文。"
        ),
        context=_extractions_context(root, limit_chars=65000),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), EntityGraphProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "entity_graph",
        "重点审核实体是否抓对、关系是否已有证据、active 状态是否适合作为续写起点。",
    )
    data = _strip_quotes(data)
    write_json(path, data)
    return {"name": "entity_graph", "status": "written", "path": str(path), "data": data}


def bootstrap_continuation_anchor(force: bool = False, root: Path = ROOT) -> Dict[str, Any]:
    path = _proposal_path("continuation_anchor", root)
    existing = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    if existing.exists() and existing.read_text(encoding="utf-8").strip() and not force:
        return _skip_result("continuation_anchor", path)

    prompt = _build_json_prompt(
        title="continuation_anchor",
        schema=model_to_json_schema(ContinuationAnchorProposal),
        instructions=(
            "请根据最后 2-3 个章节抽取结果生成续写起点 proposal。anchor_text 写 3-5 句，"
            "key_state_points 写当前角色/组织/物品状态。只能概括，不要复制原文。"
        ),
        context=_recent_extractions_context(root, count=3, limit_chars=24000),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), ContinuationAnchorProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "continuation_anchor",
        "审核续写起点是否接在当前文本之后，关键状态点是否足够具体。",
    )
    data = _strip_quotes(data)
    write_json(path, data)
    return {"name": "continuation_anchor", "status": "written", "path": str(path), "data": data}


def bootstrap_style_examples(force: bool = False, root: Path = ROOT) -> Dict[str, Any]:
    path = _proposal_path("style_examples", root)
    examples_dir = root / "data" / "style_examples"
    existing_examples = [p for p in examples_dir.glob("*.md") if p.name.lower() != "readme.md"] if examples_dir.exists() else []
    if existing_examples and not force:
        return _skip_result("style_examples", path)

    prompt = _build_json_prompt(
        title="style_examples",
        schema=model_to_json_schema(StyleExamplesProposal),
        instructions=(
            "请从带行号的 normalized_texts 摘样中标出 3-5 段最适合做风格参考的位置。"
            "每条只输出 category、source_file、start_line、end_line、preview、target_file。"
            "preview 必须 <=100 字；不要输出完整片段。target_file 放在 data/style_examples/ 下。"
        ),
        context=_normalized_context(root, limit_chars=70000),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), StyleExamplesProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "style_examples",
        "审核行号范围是否适合作为风格样例；proposal 只含短 preview，完整片段只会在 confirm 后写入 gitignored 路径。",
    )
    for item in data.get("examples", []):
        item["preview"] = str(item.get("preview", ""))[:100]
        item["target_file"] = _safe_style_target(str(item.get("category") or "style"), str(item.get("target_file") or ""))
    write_json(path, data)
    return {"name": "style_examples", "status": "written", "path": str(path), "data": data}


def bootstrap_all(force: bool = False, root: Path = ROOT) -> Dict[str, Dict[str, Any]]:
    return {
        "global_facts": bootstrap_global_facts(force=force, root=root),
        "entity_graph": bootstrap_entity_graph(force=force, root=root),
        "continuation_anchor": bootstrap_continuation_anchor(force=force, root=root),
        "style_examples": bootstrap_style_examples(force=force, root=root),
    }


def proposal_summary(data: Dict[str, Any]) -> str:
    name = str(data.get("name") or "")
    payload = data.get("data") if isinstance(data.get("data"), dict) else read_json(Path(str(data.get("path", ""))), {})
    if name == "global_facts":
        return f"facts={len(payload.get('facts', []) or [])}"
    if name == "entity_graph":
        return f"entities={len(payload.get('entities', []) or [])}, relationships={len(payload.get('relationships', []) or [])}"
    if name == "continuation_anchor":
        anchor = str(payload.get("anchor_text", ""))[:100]
        return f"anchor_preview={anchor}"
    if name == "style_examples":
        return f"ranges={len(payload.get('examples', []) or [])}"
    return str(data.get("status", "unknown"))


def _proposal_path(name: str, root: Path) -> Path:
    return root / "data" / "proposals" / f"{name}.proposal.json"


def _skip_result(name: str, path: Path) -> Dict[str, Any]:
    return {
        "name": name,
        "status": "skipped_existing_manual",
        "path": str(path),
        "message": "已有 manual，propose-merge 留给 user；如需重新生成请使用 --force。",
    }


def _has_manual_json(path: Path) -> bool:
    data = read_json(path, None)
    if data is None:
        return False
    if isinstance(data, dict):
        return bool(data)
    if isinstance(data, list):
        return bool(data)
    return True


def _json_messages(prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": "你是小说工程化 bootstrap agent。只输出符合 schema 的 JSON object。"},
        {"role": "user", "content": prompt},
    ]


def _build_json_prompt(title: str, schema: Dict[str, Any], instructions: str, context: str) -> str:
    return (
        f"# Task: {title}\n\n"
        "# Instructions\n"
        f"{instructions}\n\n"
        "# JSON schema\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "# Local source context\n"
        f"{context}"
    )


def _with_meta(data: Dict[str, Any], name: str, instructions: str) -> Dict[str, Any]:
    meta = dict(data.get("_meta") or {})
    meta.update(
        {
            "generated_by": "auto_bootstrap_v1",
            "proposal_name": name,
            "review_instructions": instructions,
        }
    )
    data["_meta"] = meta
    return data


def _strip_quotes(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: _strip_quotes(item) for key, item in value.items()}
        if "quote" in cleaned:
            cleaned["quote"] = ""
        if "preview" in cleaned:
            cleaned["preview"] = str(cleaned["preview"])[:100]
        return cleaned
    if isinstance(value, list):
        return [_strip_quotes(item) for item in value]
    return value


def _extractions_context(root: Path, limit_chars: int) -> str:
    items = _load_extractions(root)
    if not items:
        return "No extracted JSON found."
    compact = []
    for item in items:
        compact.append(
            {
                "chapter_id": item.get("chapter_id"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "character_states": _without_quotes(item.get("character_states", [])),
                "relationships": _without_quotes(item.get("relationships", [])),
                "foreshadowing": _without_quotes(item.get("foreshadowing", [])),
                "worldbuilding": _without_quotes(item.get("worldbuilding", [])),
            }
        )
    return json.dumps(compact, ensure_ascii=False, indent=2)[:limit_chars]


def _recent_extractions_context(root: Path, count: int, limit_chars: int) -> str:
    items = _load_extractions(root)[-count:]
    if not items:
        return "No recent extracted JSON found."
    compact = [
        {
            "chapter_id": item.get("chapter_id"),
            "title": item.get("title"),
            "summary": item.get("summary"),
            "rolling_summary": item.get("rolling_summary"),
            "character_states": _without_quotes(item.get("character_states", [])),
            "relationships": _without_quotes(item.get("relationships", [])),
            "foreshadowing": _without_quotes(item.get("foreshadowing", [])),
        }
        for item in items
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2)[:limit_chars]


def _load_extractions(root: Path) -> List[Dict[str, Any]]:
    paths = sorted((root / "data" / "extracted_jsons").glob("*.json"))
    return [read_json(path, {}) for path in paths if path.is_file()]


def _without_quotes(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_quotes(item) for key, item in value.items() if key != "quote"}
    if isinstance(value, list):
        return [_without_quotes(item) for item in value]
    return value


def _normalized_context(root: Path, limit_chars: int) -> str:
    parts: List[str] = []
    for path in sorted((root / "data" / "normalized_texts").glob("*.txt")):
        rel = path.relative_to(root)
        lines = path.read_text(encoding="utf-8").splitlines()
        parts.append(f"## {rel}")
        for line_no, line in _sample_numbered_lines(lines):
            parts.append(f"{line_no}: {line[:160]}")
        text = "\n".join(parts)
        if len(text) >= limit_chars:
            return text[:limit_chars]
    return "\n".join(parts)[:limit_chars] if parts else "No normalized text found."


def _sample_numbered_lines(lines: List[str]) -> List[Tuple[int, str]]:
    if len(lines) <= 420:
        indexes = range(len(lines))
    else:
        windows = [(0, 140), (max(0, len(lines) // 2 - 70), min(len(lines), len(lines) // 2 + 70)), (max(0, len(lines) - 140), len(lines))]
        selected = []
        for start, end in windows:
            selected.extend(range(start, end))
        indexes = sorted(set(selected))
    return [(idx + 1, lines[idx]) for idx in indexes if lines[idx].strip()]


def _safe_style_target(category: str, target_file: str) -> str:
    name = Path(target_file).name if target_file else ""
    if not name.endswith(".md"):
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", category).strip("_") or "style"
        name = f"{slug}.md"
    return f"data/style_examples/{name}"
