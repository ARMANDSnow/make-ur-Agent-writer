from __future__ import annotations

"""Generate reviewable bootstrap proposals from local novel data."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import paths
from .config import ROOT
from .llm_client import LLMClient
from .schemas import (
    ContinuationAnchorProposal,
    EntityGraphProposal,
    GlobalFactsProposal,
    PersonasProposal,
    SourceExcerptsProposal,
    StyleExamplesProposal,
    model_to_dict,
    model_to_json_schema,
)
from .utils import ensure_dir, read_json, write_json


# Legacy constants — kept for iter 015/016 test backward compat
# (tests that pass ``root=Path(tmp)`` still work).
PROPOSALS_DIR = ROOT / "data" / "proposals"
EXTRACTED_DIR = ROOT / "data" / "extracted_jsons"
NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
GLOBAL_FACTS_PATH = ROOT / "data" / "manual_overrides" / "global_facts.json"
ENTITY_GRAPH_PATH = ROOT / "data" / "entity_graph.json"
CONTINUATION_ANCHOR_PATH = ROOT / "data" / "manual_overrides" / "continuation_anchor.txt"
STYLE_EXAMPLES_DIR = ROOT / "data" / "style_examples"


def _resolve_root(root: Path | None) -> Path:
    """Iter 017: when caller doesn't supply ``root``, default to the active
    workspace root (or repo ROOT in legacy mode). Callers that pass
    ``root=Path(tmp)`` keep iter 015/016 test override behavior unchanged.
    """
    if root is not None:
        return root
    return paths.workspace_root() if paths.workspace_name() else ROOT


def bootstrap_global_facts(force: bool = False, root: Path = None) -> Dict[str, Any]:
    root = _resolve_root(root)
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


def bootstrap_entity_graph(force: bool = False, root: Path = None) -> Dict[str, Any]:
    root = _resolve_root(root)
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


def _anchor_state_sidecar(root: Path) -> Path:
    return root / "data" / "manual_overrides" / ".continuation_anchor.meta.json"


def _anchor_matches_current_start(root: Path) -> bool:
    """Iter 027 bugfix: return True iff the on-disk continuation_anchor.txt
    is fresh relative to the currently-set start_chapter.json.

    Sidecar missing → treat as fresh (legacy / hand-written anchors don't
    have the sidecar yet; user can pass --force if they suspect stale).
    Sidecar present with mismatching start_chapter_id → STALE; caller must
    regenerate even when ``force=False``. This is the entire point of the
    fix: set-start-point changing the anchor's intended start chapter
    should invalidate any auto-generated anchor that referenced a different
    start.
    """
    from . import start_point as _start_point

    sidecar = _anchor_state_sidecar(root)
    if not sidecar.exists():
        return True
    meta = read_json(sidecar, {}) or {}
    recorded = meta.get("start_chapter_id")
    current = _start_point.get_start_chapter_id() or ""
    return recorded == current


def bootstrap_continuation_anchor(force: bool = False, root: Path = None) -> Dict[str, Any]:
    root = _resolve_root(root)
    path = _proposal_path("continuation_anchor", root)
    existing = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    # Iter 027 bugfix: also require sidecar metadata to match the current
    # start_chapter_id. Without this, set-start-point changing the start
    # to e.g. "longzu_3_3_ch024" silently leaves a龙族 I 开头 anchor in
    # place (the exact race condition that broke capstone trials).
    if (
        existing.exists()
        and existing.read_text(encoding="utf-8").strip()
        and not force
        and _anchor_matches_current_start(root)
    ):
        return _skip_result("continuation_anchor", path)

    # Iter 021: if user has explicitly set a start point, sample the K
    # chapters of authentic source text immediately before it. This is
    # the fix for the iter 020 "anchor locked to book 1 ch001" bug.
    # Falls back to the iter 020 default (last 3 extracted_jsons) when
    # no start point is set, so existing workspaces are byte-identical.
    from . import start_point

    if start_point.get_start_chapter_id() is not None:
        # iter 053f: 采样窗口含起点章自身（(start-k, start] 闭区间）——续写
        # 的交接点是起点章的结尾。旧 exclusive 窗口在起点章为时间跳跃尾声时
        # 让 anchor 系统性锚早一章（053c 实跑：ch024 尾声 vs ch021-023 高潮，
        # 重新生成多少次都是机库倒计时毒）。
        context = start_point.format_chapters_before_start_for_anchor(
            k=3, limit_chars=24000, include_start=True
        )
        instructions = (
            "请根据下方'截至起点章的 K 章原文'生成续写起点 proposal。anchor_text 写 3-5 句，"
            "key_state_points 写当前角色/组织/物品状态。anchor_text 必须明确指出此续写"
            "是接在 *最后一章（起点章）结束之后* 开始的，不要复述原文，但要让起点状态与"
            "最后一章的末尾自然衔接。若最后一章与它之前的章节之间存在时间跳跃或场景收束"
            "（例如尾声），一律以最后一章结尾的时空状态为准——更早章节里的战斗、危机、"
            "倒计时如果在最后一章已收束，必须当作已经过去的事件，不得写成正在进行。"
        )
    else:
        context = _recent_extractions_context(root, count=3, limit_chars=24000)
        instructions = (
            "请根据最后 2-3 个章节抽取结果生成续写起点 proposal。anchor_text 写 3-5 句，"
            "key_state_points 写当前角色/组织/物品状态。只能概括，不要复制原文。"
        )

    prompt = _build_json_prompt(
        title="continuation_anchor",
        schema=model_to_json_schema(ContinuationAnchorProposal),
        instructions=instructions,
        context=context,
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


def bootstrap_style_examples(force: bool = False, root: Path = None) -> Dict[str, Any]:
    root = _resolve_root(root)
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


def bootstrap_source_excerpts(force: bool = False, root: Path = None) -> Dict[str, Any]:
    """Iter 023: produce 15-20 tagged source-text excerpts covering multiple
    scene archetypes (战斗 / 心理 / 对话 / 场景描写 / 异能 / 情感).

    Writer/reviewer later use ``src.source_excerpts.select_for_chapter`` to
    pick K=3 archetype-matched excerpts per chapter — fixing iter 022's "起点前
    K 章硬切" mismatch (the 3 chapters before start aren't necessarily of
    the same scene type as the chapter being written).

    LLM is called once. Proposal goes to data/proposals/source_excerpts.proposal.json
    for review; apply path is data/source_excerpts/excerpts.json.
    """
    root = _resolve_root(root)
    path = _proposal_path("source_excerpts", root)
    existing = root / "data" / "source_excerpts" / "excerpts.json"
    if existing.exists() and not force:
        return _skip_result("source_excerpts", path)

    prompt = _build_json_prompt(
        title="source_excerpts",
        schema=model_to_json_schema(SourceExcerptsProposal),
        instructions=(
            "从下方章节摘样中挑出 8-12 段最能代表作者风格 + 场景多样性的片段。"
            "目标覆盖：战斗、心理、对话、场景描写、异能、情感 中至少 4-5 种。\n\n"
            "每段输出 JSON 含：\n"
            "- id（ex_001 / ex_002 ...）\n"
            "- source_chapter_id（输入中出现的章节 id 形如 longzu_1_ch001）\n"
            "- start_line / end_line（1-indexed）\n"
            "- scene_type（战斗/心理/对话/场景描写/异能/情感）\n"
            "- character_focus（≤5 个角色名）\n"
            "- excerpt_text（**完整原文片段 300-800 字**，从摘样复制）\n"
            "- description（一句话 ≤ 80 字）\n"
            "- tags（≤5 个标签）\n\n"
            "请直接输出合法 JSON，不要添加说明文字。"
        ),
        # Iter 023 fix: 30K char context (was 80K) — claude-opus-4-5 was
        # returning ~70-token responses to 80K-token prompts (refusal or
        # capped output). 30K leaves plenty of room for the 8-12 excerpts.
        context=_normalized_context(root, limit_chars=30000),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), SourceExcerptsProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "source_excerpts",
        "审核 15-20 段是否覆盖 6 类 scene_type、原文是否未改写、tags 是否合理。",
    )
    write_json(path, data)
    return {"name": "source_excerpts", "status": "written", "path": str(path), "data": data}


def bootstrap_personas(force: bool = False, root: Path = None) -> Dict[str, Any]:
    """Iter 016: derive persona binding from already-bootstrapped manual data.

    Reads entity_graph (manual or proposal fallback), global_facts (same),
    continuation_anchor, and a short normalized-text sample. Asks the planner
    LLM to fill `PersonasProposal`: protagonist name/role, author name, style
    descriptor, world setting brief, core relationships, core setting rules.

    The proposal binds variables that `data/manual_overrides/personas.json`
    will hold after `apply-bootstrap --name personas`. Those variables fill
    `*_template` fields in `config/agents.yaml` so that debate and review
    agents stop being anchored on the original validation corpus.
    """
    root = _resolve_root(root)
    path = _proposal_path("personas", root)
    existing = root / "data" / "manual_overrides" / "personas.json"
    if _has_manual_json(existing) and not force:
        return _skip_result("personas", path)

    prompt = _build_json_prompt(
        title="personas",
        schema=model_to_json_schema(PersonasProposal),
        instructions=(
            "请基于已有 manual 数据为本部小说推断 persona 绑定。绑定字段会被注入到 debate/review agent 的 prompt 模板，"
            "所以每个字段都必须精炼。\n"
            "硬规则：\n"
            "1. protagonist_name 必须出现在 entity_graph 中（不要凭空创造主角）。\n"
            "2. protagonist_role 用一句话写主角的身份/位置（≤120 字符）。\n"
            "3. author_name 优先从 normalized 文本头部 metadata 或常识推断；推不出就留空字符串。\n"
            "4. style_short_descriptor 用 ≤80 字符描述作者笔法（如 \"白话+反讽\" / \"长短句交错+含蓄叙事\"）。\n"
            "5. world_setting_brief ≤400 字符；只写世界观骨架，不写情节。\n"
            "6. core_relationships 列 3-5 条最关键的关系，每条形如 \"<entity_a> 与 <entity_b> 的 <type> 关系\"，必须出自 entity_graph。\n"
            "7. core_setting_rules 列 2-5 条世界观硬规则；如果原作的设定不涉及硬规则（如纯写实作品）则留空数组。\n"
            "8. 所有字符串只能用自己的话总结，禁止复制原文片段。"
        ),
        context=_personas_context(root),
    )
    proposal = LLMClient("plot_planner").complete_json(_json_messages(prompt), PersonasProposal)
    data = _with_meta(
        model_to_dict(proposal),
        "personas",
        (
            "审核 protagonist_name 是否准确（必须出自 entity_graph）；author_name 是否对得上；"
            "world_setting_brief 不超过 400 字且不写情节；core_relationships/core_setting_rules 条数适中。"
        ),
    )
    write_json(path, data)
    return {"name": "personas", "status": "written", "path": str(path), "data": data}


def bootstrap_all(force: bool = False, root: Path = None) -> Dict[str, Dict[str, Any]]:
    """Run all six bootstrap proposals.

    Iter 026 code-review #3: ``source_excerpts`` was historically omitted
    from this call site even though ``cli_apply_bootstrap.BOOTSTRAP_NAMES``
    knows about it. That meant the wizard / ``auto-pipeline`` path silently
    skipped the iter 023 ``K=3 archetype-matched excerpts`` feature, while
    the standalone CLI ``bootstrap-source-excerpts`` subcommand still
    worked. Including it here keeps the orchestration aligned with the
    rest of the pipeline.
    """

    root = _resolve_root(root)
    return {
        "global_facts": bootstrap_global_facts(force=force, root=root),
        "entity_graph": bootstrap_entity_graph(force=force, root=root),
        "continuation_anchor": bootstrap_continuation_anchor(force=force, root=root),
        "style_examples": bootstrap_style_examples(force=force, root=root),
        "personas": bootstrap_personas(force=force, root=root),
        "source_excerpts": bootstrap_source_excerpts(force=force, root=root),
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
    if name == "personas":
        return (
            f"protagonist={payload.get('protagonist_name') or '?'}, "
            f"author={payload.get('author_name') or '?'}, "
            f"relationships={len(payload.get('core_relationships', []) or [])}, "
            f"rules={len(payload.get('core_setting_rules', []) or [])}"
        )
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
    payload = json.dumps(compact, ensure_ascii=False, indent=2)
    # iter 051a: global_facts / entity_graph proposals consume the premise
    # expansion when present (greenfield extractions from a one-sentence seed
    # are too thin on their own). Empty block when absent → byte-identical.
    # iter 051c (review M-1): budget the cap against the payload only — a
    # combined-then-truncate would cut mid-JSON when expansion + payload
    # exceed limit_chars, feeding the LLM a broken structure.
    from .premise_expansion import expansion_prompt_block

    expansion = expansion_prompt_block()
    return expansion + payload[: max(0, limit_chars - len(expansion))]


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


def _personas_context(root: Path) -> str:
    """Compact context for persona bootstrap: existing entity_graph + facts +
    anchor + outline + a small normalized-text head sample. Stays well under
    the planner context limit and never quotes long source excerpts.
    """

    parts: List[str] = []

    # Entity graph — prefer applied manual, fall back to proposal.
    graph_path = root / "data" / "entity_graph.json"
    if not graph_path.exists():
        graph_path = root / "data" / "proposals" / "entity_graph.proposal.json"
    graph = read_json(graph_path, {}) if graph_path.exists() else {}
    if graph:
        compact_graph = {
            "entities": [
                {
                    "id": e.get("id"),
                    "canonical_name": e.get("canonical_name") or e.get("name"),
                    "type": e.get("type"),
                    "tags": e.get("tags") or [],
                    "key_facts": (e.get("key_facts") or [])[:3],
                    "description": (e.get("description") or "")[:200],
                }
                for e in (graph.get("entities") or [])
            ],
            "relationships": [
                {
                    "source": r.get("source") or r.get("from"),
                    "target": r.get("target") or r.get("to"),
                    "relation_type": r.get("relation_type") or r.get("type"),
                    "active": r.get("active", True),
                }
                for r in (graph.get("relationships") or [])
            ],
        }
        parts.append("## entity_graph (compact)\n" + json.dumps(compact_graph, ensure_ascii=False, indent=2))

    # Global facts — prefer applied manual, fall back to proposal.
    facts_path = root / "data" / "manual_overrides" / "global_facts.json"
    if not facts_path.exists():
        facts_path = root / "data" / "proposals" / "global_facts.proposal.json"
    facts = read_json(facts_path, {}) if facts_path.exists() else {}
    if facts:
        compact_facts = [
            {"fact_id": f.get("fact_id"), "statement": (f.get("statement") or "")[:300]}
            for f in (facts.get("facts") or [])
        ]
        parts.append("## global_facts (compact)\n" + json.dumps(compact_facts, ensure_ascii=False, indent=2))

    # Continuation anchor (already-applied or proposal).
    anchor_path = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    if anchor_path.exists():
        parts.append("## continuation_anchor\n" + anchor_path.read_text(encoding="utf-8")[:2000])
    else:
        anchor_proposal = read_json(root / "data" / "proposals" / "continuation_anchor.proposal.json", {})
        if anchor_proposal:
            anchor_text = anchor_proposal.get("anchor_text") or ""
            if anchor_text:
                parts.append("## continuation_anchor (proposal)\n" + anchor_text[:2000])

    # Outline if present (helps author voice inference).
    outline_path = root / "outputs" / "debate" / "outline.md"
    if outline_path.exists():
        parts.append("## outline (excerpt)\n" + outline_path.read_text(encoding="utf-8")[:2000])

    # Normalized text head sample for author voice / setting clues.
    norm_dir = root / "data" / "normalized_texts"
    if norm_dir.exists():
        head_parts: List[str] = []
        for path in sorted(norm_dir.glob("*.txt"))[:2]:
            rel = path.relative_to(root)
            head_lines = path.read_text(encoding="utf-8").splitlines()[:80]
            head_parts.append(f"### {rel}\n" + "\n".join(line[:160] for line in head_lines if line.strip()))
        if head_parts:
            parts.append("## normalized_text head sample (≤80 lines per file)\n" + "\n\n".join(head_parts))

    text = "\n\n".join(parts) if parts else "No source data found."
    return text[:60000]


def _safe_style_target(category: str, target_file: str) -> str:
    name = Path(target_file).name if target_file else ""
    if not name.endswith(".md"):
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", category).strip("_") or "style"
        name = f"{slug}.md"
    return f"data/style_examples/{name}"
