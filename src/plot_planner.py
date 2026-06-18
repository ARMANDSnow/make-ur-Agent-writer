from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .continuation_anchor import load_continuation_anchor
from .entities import load_entity_graph, render_active_state
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .schemas import ChapterPlan, ChapterPlanItem, model_to_dict, model_to_json_schema
from . import start_point
from .state import log_event
from .style import load_style_examples
from .utils import read_json_optional, sha256_data, sha256_text, write_json


# Legacy constants — kept for iter 014-016 test backward compat
# (``patch("src.plot_planner.OUTLINE_PATH", ...)`` still works).
CHAPTER_PLAN_PATH = ROOT / "outputs" / "debate" / "chapter_plan.json"
OUTLINE_PATH = ROOT / "outputs" / "debate" / "outline.md"
DECISIONS_PATH = ROOT / "outputs" / "debate" / "decisions.json"


def _chapter_plan_path() -> Path:
    return paths.chapter_plan_path() if paths.workspace_name() else CHAPTER_PLAN_PATH


def _outline_path() -> Path:
    return paths.outline_path() if paths.workspace_name() else OUTLINE_PATH


def _decisions_path() -> Path:
    return paths.debate_decisions_path() if paths.workspace_name() else DECISIONS_PATH


def _stale_outline_message(codes: List[str]) -> str:
    """iter 053a (审查 A7): the hard-block message must tell apart "the start
    point truly changed" from "probably just a re-split moved line numbers",
    or users get trained into reflexively passing --allow-stale-outline."""
    if "outline_start_chapter_id_mismatch" in codes:
        detail = (
            "辩论大纲生成时的起点 chapter_id 与当前起点不同——起点已真正变更，"
            "旧大纲跨时间线（052 事故场景）。请重跑 `python main.py debate --force` "
            "生成新大纲后再规划。"
        )
    elif "outline_content_mismatch" in codes:
        detail = (
            "outline.md 与 decisions.json 不是同批产物（outline 被手改，或上次 "
            "debate 写盘中断）。请重跑 `python main.py debate --force`。"
        )
    else:
        detail = (
            "起点 chapter_id 未变但起点指纹变化（常见于重跑 normalize/split 后"
            "行号漂移）。若确认起点语义未变，可加 `--allow-stale-outline` 显式"
            "放行（会在 chapter_plan.json 留审计痕）；否则重跑 `debate --force`。"
        )
    return f"stale debate outline ({', '.join(codes)}): {detail}"


def generate_chapter_plan(
    target_chapters: int = 18,
    force: bool = False,
    *,
    append_count: int = 0,
    from_chapter: int = 0,
    require_start_point: bool = False,
    allow_stale_outline: bool = False,
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
    existing_start_chapter_id = ""
    if append_count > 0:
        if not chapter_plan_path.exists():
            raise FileNotFoundError(
                "cannot --append without existing chapter_plan.json; run plan-chapters first"
            )
        from .utils import read_json as _read_json
        existing = _read_json(chapter_plan_path, {})
        existing_start_chapter_id = str(existing.get("start_chapter_id") or "")
        all_existing = existing.get("chapters", []) or []
        existing_chapters = all_existing[:from_chapter] if from_chapter > 0 else all_existing
    elif chapter_plan_path.exists() and not force:
        raise FileExistsError("chapter_plan.json already exists; use --force to overwrite")

    outline = outline_path.read_text(encoding="utf-8")
    # iter 053a: before trusting the outline, check its provenance against the
    # CURRENT start point (the 052 accident: a "四部曲结局后"-era outline was
    # trusted verbatim after the start moved to ch024 — nine drafts dead).
    # Hard mismatch → refuse unless --allow-stale-outline; no metadata at all
    # (legacy / missing decisions.json) → warn and proceed, fail-open.
    decisions = read_json_optional(_decisions_path(), {})
    stale_codes = start_point.outline_consistency_failures(
        decisions, outline_text=outline
    )
    hard_codes = [
        c for c in stale_codes if c != start_point.OUTLINE_METADATA_MISSING
    ]
    acknowledged_codes: List[str] = []
    if hard_codes:
        if allow_stale_outline:
            acknowledged_codes = hard_codes
            log_event(
                "plot_planner", "stale_outline_acknowledged", codes=hard_codes
            )
            print(
                "[plan-chapters] warn: --allow-stale-outline 放行陈旧大纲 "
                f"({', '.join(hard_codes)})，审计痕已写入 chapter_plan.json。"
            )
        else:
            raise ValueError(_stale_outline_message(hard_codes))
    elif start_point.OUTLINE_METADATA_MISSING in stale_codes:
        log_event("plot_planner", "outline_start_metadata_missing")
        print(
            "[plan-chapters] warn: debate 产物没有起点指纹（指纹机制之前的存量，"
            "或 decisions.json 缺失）。建议重跑 `python main.py debate --force` "
            "刷新大纲指纹后再规划。"
        )
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
    start_chapter_id = start_point.get_start_chapter_id()
    # iter 051b (F6): both gates now go through the centralized
    # start_point.enforce_consistency (single entry-point shared with
    # book_runner) — this function only maps codes to its historical
    # ValueError messages, byte-identical to the pre-051b inline checks.
    if "start_point_missing" in start_point.enforce_consistency(
        require_start_point=require_start_point
    ):
        raise ValueError(
            "start point is required before plan-chapters; run `set-start-point` first"
        )
    if append_count > 0 and require_start_point:
        plan_failures = start_point.enforce_consistency(
            require_start_point=True,
            plan_data={"start_chapter_id": existing_start_chapter_id},
        )
        if "start_chapter_id_missing" in plan_failures:
            raise ValueError(
                "existing chapter_plan.json has no start_chapter_id; regenerate it "
                "with --force --require-start-point before appending"
            )
        if "start_chapter_id_mismatch" in plan_failures:
            raise ValueError(
                "existing chapter_plan.json start_chapter_id does not match the "
                "current start point; regenerate the plan before appending"
            )
    # iter 054b: extraction coverage闸 promoted from readiness warn (053g) to a
    # hard blocker HERE. The K chapters before the start (incl. start) feed the
    # KB/entity_graph base via extract→compress→bootstrap; a gap there锚 the
    # plan (and the debate spend that precedes it) on stale state — exactly the
    # 052 "听力考试假基线" root cause. Block before committing to a plan rather
    # than warning after the LLM money is gone. Sits after the append-mismatch
    # gate so a moved start surfaces the more fundamental mismatch first.
    # greenfield/no-start fail-open: extraction_coverage_failures returns []
    # without a start point (铁律④).
    missing_extraction = start_point.extraction_coverage_failures(k=10)
    if missing_extraction:
        preview = ",".join(missing_extraction[:5])
        more = f" (+{len(missing_extraction) - 5} more)" if len(missing_extraction) > 5 else ""
        raise ValueError(
            f"extraction coverage gap before start point: {preview}{more}; "
            "run `extract --volume <起点所在卷>` (or `rebuild-for-start`) so the "
            "KB/entity_graph base is current before planning"
        )
    start_point_context = _format_start_point_context(start_chapter_id)

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
        start_point_context=start_point_context,
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
            "start_chapter_id": old.get("start_chapter_id", start_chapter_id),
            "generated_by": (
                f"plot_planner_v1_append (existing 1..{from_chapter} preserved, "
                f"ch{from_chapter+1}..{from_chapter+append_count} new)"
            ),
        }
    else:
        data = new_data
        data["start_chapter_id"] = start_chapter_id or ""
    # iter 053a (审查 A1): record which outline this plan was generated from —
    # the plan↔outline lineage link, checked warn-level by
    # start_point.plan_outline_lineage_failures. Without it a debate rerun
    # leaves the old plan silently stale while its F6 fingerprints stay green
    # (盘面实证：052 的毒 chapter_plan.json 四码全绿). Not part of the
    # plan_fingerprint whitelist, so existing chapter meta fingerprints are
    # untouched.
    data["outline_sha256"] = sha256_text(outline)
    if acknowledged_codes:
        # 审查 A9: an escape-hatch pass must leave an audit trail — the plan
        # produced under an acknowledged-stale outline carries clean F6 codes,
        # so without this field the lineage pollution would be untraceable.
        data["stale_outline_acknowledged"] = {
            "codes": acknowledged_codes,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
        }
    _attach_plan_fingerprints(data, start_chapter_id=start_chapter_id)
    write_json(chapter_plan_path, data)
    return data


# Iter 050 (B-M-2): the fingerprint input is an explicit whitelist of the
# semantic fields of ``ChapterPlanItem``. Previously a blacklist excluded
# bookkeeping fields ({chapter_plan_item_fingerprint, plan_fingerprint,
# start_point_fingerprint}) plus ``segments`` (iter 046: writing-time
# decomposition, not plan semantics) — meaning any future schema field would
# silently enter the hash and invalidate every written chapter's stored
# fingerprint. With the whitelist, adding a field to the fingerprint is an
# explicit decision here. For canonical (model-produced) plan items the two
# filters select the same keys, so hashes are byte-identical — no migration.
_ITEM_FINGERPRINT_FIELDS: tuple = (
    "chapter_no",
    "title",
    "opening_scene",
    "key_events",
    "relationships_in_play",
    "ending_hook",
    "target_chinese_chars",
    "plot_purpose",
)

# Iter 050: fields the structured edit endpoint may change. ``chapter_no``
# stays immutable (renumbering breaks append mode + draft filename mapping)
# and ``segments`` is not exposed in v1 (regenerate instead).
EDITABLE_PLAN_ITEM_FIELDS = frozenset(_ITEM_FINGERPRINT_FIELDS) - {"chapter_no"}


def chapter_plan_item_fingerprint(item: Dict[str, Any]) -> str:
    """Stable fingerprint for a single chapter plan item."""

    stable = {key: item[key] for key in _ITEM_FINGERPRINT_FIELDS if key in item}
    return sha256_data(stable)


def plan_fingerprint(data: Dict[str, Any]) -> str:
    """Stable fingerprint for the GLOBAL plan context consumed by writer/reviewer.

    iter057 (P0-A fix): the ``chapters`` whole-list and ``target_chapters`` were
    removed from the hash. Per-chapter consistency is owned by
    ``chapter_plan_item_fingerprint`` (checked per chapter in
    ``book_runner._plan_metadata_failures``); ``plan_fingerprint`` now covers only
    the plan-wide context that is NOT specific to any single chapter (overall_arc +
    start-point identity). This makes ``--replan-every`` append-mode safe: an
    appended tail no longer rewrites the fingerprint frozen in already-written
    chapters' meta (which used to flip every written chapter to
    ``plan_fingerprint_mismatch`` → not ``skipped_approved`` → ``BookRunBlocked``
    on the next segment's re-walk, or ``--force`` re-writes that double-mutate the
    entity graph). Global edits (overall_arc / start point moved) still flip it, so
    "start point moved → old plan stale" detection is preserved. schema_version
    1→2 marks the algorithm change (migrate existing data with
    ``scripts/migrate_plan_fingerprints.py``).
    """

    payload = {
        "schema_version": 2,
        "overall_arc": data.get("overall_arc", ""),
        "start_chapter_id": data.get("start_chapter_id", ""),
        "start_point_fingerprint": data.get("start_point_fingerprint", ""),
    }
    return sha256_data(payload)


def _attach_plan_fingerprints(
    data: Dict[str, Any],
    *,
    start_chapter_id: str | None,
    refresh_start_point: bool = True,
) -> None:
    # Iter 050: the structured edit path passes refresh_start_point=False —
    # it must keep the plan's *stored* start_point_fingerprint so that
    # book_runner._plan_metadata_failures can still detect "plan was
    # generated under a different start point". Recomputing from live state
    # here would forge freshness the plan content doesn't have. 050d (L-1):
    # that includes the EMPTY case — back-filling a missing/empty stored
    # fingerprint with the live value would bless a plan that was never
    # generated under the current start point; leave it empty and let the
    # gate fail-safe with start_point_fingerprint_missing.
    data["start_chapter_id"] = start_chapter_id or data.get("start_chapter_id") or ""
    if refresh_start_point:
        data["start_point_fingerprint"] = start_point.start_point_fingerprint()
    else:
        data["start_point_fingerprint"] = data.get("start_point_fingerprint") or ""
    data["schema_version"] = int(data.get("schema_version") or 1)
    for item in data.get("chapters", []) or []:
        if isinstance(item, dict):
            item["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(item)
    data["plan_fingerprint"] = plan_fingerprint(data)


def apply_chapter_plan_item_edit(chapter_no: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Iter 050: structured per-chapter plan edit — no LLM, pure IO.

    Merges whitelisted fields into one chapter's plan item, validates the
    item (Pydantic range checks) and the whole plan, then re-derives every
    fingerprint via ``_attach_plan_fingerprints`` — the same single entry
    used by plan generation, so the write-book gate stays self-consistent
    (the 048c rule: no write path may hand-craft fingerprints).

    Non-edited items are kept byte-identical (no model round-trip of the
    whole plan), so their stored fingerprints in already-written chapters'
    meta survive an edit of a *different* chapter at the item level. The
    plan-level ``plan_fingerprint`` still changes — written chapters going
    strict-stale after any plan edit is the accepted product semantics.

    Raises ``FileNotFoundError`` (no plan), ``KeyError`` (chapter not in
    plan), ``ValueError`` (non-editable field or validation failure).
    """

    from pydantic import ValidationError

    from .utils import read_json

    chapter_plan_path = _chapter_plan_path()
    if not chapter_plan_path.exists():
        raise FileNotFoundError("chapter_plan.json not found; run plan-chapters first")
    data = read_json(chapter_plan_path, {})
    if not isinstance(data, dict):
        raise ValueError("chapter_plan.json is not a JSON object")
    chapters = data.get("chapters", []) or []

    unknown = set(fields) - EDITABLE_PLAN_ITEM_FIELDS
    if unknown:
        raise ValueError(
            "non-editable fields: " + ", ".join(sorted(str(k) for k in unknown))
        )
    if not fields:
        raise ValueError("no editable fields provided")

    idx = next(
        (
            i
            for i, item in enumerate(chapters)
            if isinstance(item, dict) and item.get("chapter_no") == chapter_no
        ),
        None,
    )
    if idx is None:
        raise KeyError(f"chapter {chapter_no} not found in chapter_plan")

    merged = {**chapters[idx], **fields}
    try:
        validated = ChapterPlanItem(**merged)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in exc.errors()
        )
        raise ValueError(f"validation failed: {details}") from exc

    chapters[idx] = model_to_dict(validated)
    try:
        ChapterPlan(**{**data, "chapters": chapters})
    except ValidationError as exc:
        raise ValueError(f"plan validation failed: {exc}") from exc

    data["chapters"] = chapters
    _attach_plan_fingerprints(data, start_chapter_id=None, refresh_start_point=False)
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


def _format_start_point_context(start_chapter_id: str | None) -> str:
    """Render explicit start metadata for the planner prompt.

    The human-readable continuation anchor can be stale; the persisted
    start_chapter.json is the operator's actual selection. This compact block
    gives the planner a second, machine-derived guardrail and prevents long
    capstone plans from silently drifting back to the beginning of the book.
    """
    if not start_chapter_id:
        return ""
    before = start_point.chapters_before_start(k=3)
    lines = [
        "# 显式续写起点（来自 start_chapter.json，最高优先级）",
        "",
        f"- resolved_start_chapter_id: {start_chapter_id}",
        "- 续写第 1 章必须发生在该章节/卷结束之后。",
        "- 不得重新规划该起点之前已经发生的入学、考试、训练、相遇、旅行或揭示事件。",
    ]
    if before:
        lines.append("- 起点前最近章节（只作方位校验，不要复述）：")
        for ch in before:
            lines.append(
                f"  - {ch.get('chapter_id', '')}: {ch.get('title', '')} "
                f"(volume={ch.get('volume_id', '')})"
            )
    return "\n".join(lines)


def _load_knowledge() -> str:
    """Iter 021 / 047b: start-safe KB view, truncated to 5000 chars.

    Delegates to ``kb_view.start_safe_knowledge`` so a configured start point
    gets a spoiler-filtered structured block; with no start point / no index it
    returns the original ``global_knowledge.md`` verbatim (byte-identical to
    iter 021).
    """
    from .kb_view import start_safe_knowledge

    return start_safe_knowledge()[:5000]


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
    start_point_context: str = "",
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
    # Iter 027 bugfix: anchor was previously also labeled "最高优先级",
    # creating a head-on conflict with start_point_block (which is also
    # the highest priority). When anchor was stale (the iter 027 capstone
    # trial drift), the planner couldn't tell which to trust. Demote
    # anchor to "narrative supplement" — start_chapter.json (operator
    # selection) is the single source of truth; anchor only fills in
    # narrative color (recent events, key state points).
    anchor_block = (
        "# 续写起点叙事 (anchor — 背景补充)\n\n"
        f"{continuation_anchor}\n\n"
        "本节是续写起点的叙事补充（最近发生的事件、关键状态点）。如果本节"
        "描述的时空 / 角色状态与上面【显式续写起点】(start_chapter.json) "
        "不一致，**以显式起点 chapter_id 为准** — anchor 可能是过期的旧版本。"
        "第 1 章的 opening_scene 必须发生在显式起点 chapter_id 之后的时空。\n\n"
        if continuation_anchor
        else ""
    )
    start_point_block = f"{start_point_context}\n\n" if start_point_context else ""
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
        "9. 起点优先级：显式起点 (start_chapter.json 解析的 chapter_id) > "
        "anchor 叙事补充 > 辩论大纲 > 其它。若 anchor 与 显式起点 不一致，"
        "anchor 视为过期，按显式起点 chapter_id 之后的时空规划。\n"
        "10. 如已存在 plan 末尾章节给出（append 模式），新规划必须从其 ending_hook 自然承接。\n\n"
        "11. （可选）配额循环：可为每章提供 segments 分段写作计划，用于长章字数控制。"
        "若提供，segments 为 2-6 段，每段含 segment_no（从 1 连续递增）、beat（本段情节一句话）、"
        "target_chinese_chars（本段目标中文字数）、is_final（仅最后一段为 true）；"
        "各段 target_chinese_chars 之和应≈本章 target_chinese_chars。不需要分段则留空数组 []。\n\n"
        f"# ChapterPlan JSON schema\n\n{schema}\n\n"
        f"{knowledge_block}"
        f"{start_point_block}"
        f"{anchor_block}"
        f"{style_block}"
        f"{facts_block}"
        f"{entity_block}"
        f"{rolling_block}"
        f"{existing_tail_block}"
        f"# 辩论大纲\n\n{outline[:12000]}\n"
    )
