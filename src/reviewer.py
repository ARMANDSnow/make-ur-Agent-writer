from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT, load_config
from .entities import load_entity_graph, render_active_state
from .linter import NovelLinter
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .persona_loader import load_personas, render_agent_fields
from .schemas import AgentReview, RewriteSuggestion, model_to_dict
from .state import log_event
from .utils import ensure_dir, extract_json_object, write_json


# Legacy constant — kept for iter 014-016 test backward compat.
REVIEWS_DIR = ROOT / "outputs" / "reviews"


def _reviews_dir() -> Path:
    return paths.reviews_dir() if paths.workspace_name() else REVIEWS_DIR


def load_review_agents() -> List[Dict[str, Any]]:
    cfg = load_config("agents.yaml")
    return cfg.get("review_agents", [])


def load_advisor_agents() -> List[Dict[str, Any]]:
    """Iter 024 P1: advisor agents from config/agents.yaml.

    Mirror of load_review_agents but for the non-voting advisor list
    (iter 023 introduced ``advisor_agents`` key). When the key is
    absent (e.g. older agents.yaml or upstream merge wipes it), this
    returns ``[]`` and the rest of the review pipeline keeps working
    without any rewrite_suggestions output.
    """
    cfg = load_config("agents.yaml")
    return cfg.get("advisor_agents", []) or []


def _relationship_checklist_issue() -> Dict[str, str]:
    return {
        "message": "关系一致性 reviewer 未输出对照清单，需人工复核 active 关系状态。",
        "rule_id": "relationship_checklist_missing",
        "severity": "major",
        "anchor": "",
    }


def _repair_agent_review_dict(raw: Any, agent_name: str, enforce_relationship_checklist: Any = True) -> Dict[str, Any]:
    """Debug fix: ``enforce_relationship_checklist`` now accepts a third
    value ``"warn_only"`` in addition to True/False. In warn_only mode,
    the 关系一致性 agent's missing-checklist condition appends a
    suggestion to ``suggestions`` (and keeps the original verdict)
    instead of forcing Reject + issues. This lets ch with broad cast
    pass review while still surfacing the diagnostic.
    """

    if not isinstance(raw, dict):
        raw = {}
    repaired = dict(raw)
    repaired["agent_name"] = str(repaired.get("agent_name") or agent_name)
    verdict = str(repaired.get("verdict", "Reject")).strip().lower()
    verdict_aliases = {
        "approve": "Approve",
        "approved": "Approve",
        "pass": "Approve",
        "accept": "Approve",
        "reject": "Reject",
        "rejected": "Reject",
        "fail": "Reject",
        "needs_revision": "Reject",
        "needs revision": "Reject",
    }
    repaired["verdict"] = verdict_aliases.get(verdict, "Abstain")
    # Iter 022 B3: prefer sub-scores when LLM provides them; legacy score
    # field stays for backward-compat with iter 020/021 mock data + tests.
    # If the LLM returned a flat plot/prose/fidelity at the top level
    # (which is how the new prompt asks for it), nest them under `scores`
    # so pydantic AgentSubScores can consume.
    if "scores" not in repaired:
        top_level_subs = {
            k: repaired.pop(k)
            for k in ("plot", "prose", "fidelity")
            if k in repaired and isinstance(repaired.get(k), (int, float))
        }
        if top_level_subs:
            # Coerce to int, clamp to 0-10 defensively
            repaired["scores"] = {
                k: max(0, min(10, int(v))) for k, v in top_level_subs.items()
            }
    repaired.setdefault("score", 7)
    if not isinstance(repaired.get("issues"), list):
        repaired["issues"] = []
    if not isinstance(repaired.get("suggestions"), list):
        repaired["suggestions"] = []
    if not isinstance(repaired.get("comparison_checklist"), list):
        repaired["comparison_checklist"] = []
    if (
        enforce_relationship_checklist
        and agent_name == "关系一致性"
        and not repaired["issues"]
        and not repaired["comparison_checklist"]
    ):
        if enforce_relationship_checklist == "warn_only":
            # warn_only mode: surface the missing checklist as a
            # suggestion but DO NOT escalate to Reject. The agent's
            # original verdict (typically Approve when issues is empty)
            # is preserved.
            issue = _relationship_checklist_issue()
            repaired["suggestions"].append(
                f"[warn_only] {issue['message']} (rule_id={issue['rule_id']})"
            )
        else:
            repaired["verdict"] = "Reject"
            repaired["issues"] = [_relationship_checklist_issue()]
    return repaired


# Iter 019 audit: removed the previous ``_empty_approve_fallback`` helper.
# It returned ``verdict: "Approve"`` on a per-agent JSON parse failure and
# short-circuited the whole review, which silently auto-approved chapters
# whenever one reviewer call had a transient parse error. The fixed code
# inlines an Abstain vote in the per-agent loop and applies a fail-closed
# Reject when ALL agents abstain. See tests/test_reviewer.py for the
# regression coverage.


def _simple_verdict_fallback(
    *,
    client: LLMClient,
    agent: Dict[str, Any],
    draft: str,
    last_response_preview: str,
    target_name: str,
) -> Dict[str, Any] | None:
    """Debug fix: when the main review prompt produced JSON that failed
    to parse, retry the SAME agent with a stripped-down prompt that only
    asks for ``{"verdict": "Approve|Reject", "reason": "..."}``.

    The original prompt asks for nested fields (issues with
    rule_id/severity/anchor, suggestions, comparison_checklist) plus the
    relationship-consistency agent's mandatory checklist block — those
    are the most common JSON parse failure sources. The simplified
    prompt has a much higher success rate because the LLM only has to
    produce 2 fields.

    Returns:
      - ``{"verdict": "Approve" | "Reject", "reason": "..."}`` on success
      - ``None`` if this fallback ALSO failed to parse (caller then falls
        back to the iter 019 Abstain behavior).

    Logs both attempts so the per-fallback recovery rate is visible
    in ``logs/run_state.jsonl``.
    """
    try:
        content = client.complete_text(
            [
                {
                    "role": "system",
                    "content": (
                        "你是一个 review agent。前一次输出 JSON 格式有误已被丢弃。"
                        "本次请直接输出最简化的 JSON：{\"verdict\": \"Approve\" 或 \"Reject\", "
                        "\"reason\": \"一句话解释\"}。不要输出 markdown、不要其他字段。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"agent_name: {agent.get('name', 'agent')}\n"
                        f"你的视角: {agent.get('stance') or agent.get('system_prompt', '')[:300]}\n\n"
                        "请重新对下面续写章节给出最终 verdict。"
                        "只输出一个 JSON object，两个字段：verdict 和 reason。\n\n"
                        f"前次输出（已丢弃，仅供参考你的思路）:\n{last_response_preview}\n\n"
                        f"章节正文:\n{draft}"
                    ),
                },
            ],
        )
        raw = json.loads(extract_json_object(content))
    except (ValueError, json.JSONDecodeError) as exc:
        log_event(
            "review",
            "simple_fallback_also_failed",
            target=target_name,
            agent=agent.get("name", "?"),
            error=str(exc),
        )
        return None
    if not isinstance(raw, dict):
        return None
    verdict = str(raw.get("verdict", "")).strip().lower()
    if verdict not in ("approve", "reject"):
        log_event(
            "review",
            "simple_fallback_bad_verdict",
            target=target_name,
            agent=agent.get("name", "?"),
            raw_verdict=verdict,
        )
        return None
    log_event(
        "review",
        "simple_fallback_recovered",
        target=target_name,
        agent=agent.get("name", "?"),
        recovered_verdict=verdict.capitalize(),
    )
    # Iter 022 B3: fallback path uses neutral 6 across all sub-scores
    # (matching the legacy `score=6` default this used to return).
    return {
        "verdict": "Approve" if verdict == "approve" else "Reject",
        "reason": str(raw.get("reason", "")),
        "score": 6,
        "scores": {"plot": 6, "prose": 6, "fidelity": 6},
    }


def review_text(
    text: str,
    target_name: str = "draft",
    precomputed_lint_issues: List[Dict[str, Any]] | None = None,
    rewrite_round: int = 0,
    run_agents_on_lint_error: bool = False,
    enforce_relationship_checklist: Any = False,
    knowledge: str = "",
    source_chapters: str = "",
    scene_excerpts: str = "",
    run_context: Dict[str, Any] | None = None,
    draft_sha256: str = "",
) -> Dict[str, Any]:
    """Iter 022 B4 + iter 023 P3/P5:

    * ``knowledge`` (KB / global_knowledge.md content) — iter 022
    * ``source_chapters`` (K chapters before start point) — iter 022 (chronological)
    * ``scene_excerpts`` (archetype-matched original excerpts) — iter 023 (genre-matched)
    * After per-agent LLM calls, iter 023 also runs the deterministic
      ``relationship_auditor`` (no LLM) and appends its issues as a
      synthetic agent ``deterministic_relations`` so fail-closed verdict
      logic includes structural relationship conflicts.

    Backward compatible: all extra kwargs default to empty / off; when none
    are set + entity_graph clean, behavior matches iter 022.
    """
    reviews_dir = _reviews_dir()
    ensure_dir(reviews_dir)
    if precomputed_lint_issues is not None:
        lint_issues = precomputed_lint_issues
    else:
        linter = NovelLinter()
        lint_issues = linter.lint(text)
    if any(issue["severity"] == "error" for issue in lint_issues) and not run_agents_on_lint_error:
        report = {
            "target": target_name,
            "rewrite_round": rewrite_round,
            "lint_issues": lint_issues,
            "agent_reviews": [],
            "verdict": "Reject",
            "run_context": run_context or {},
            "draft_sha256": draft_sha256,
        }
        write_json(reviews_dir / f"{Path(target_name).stem}.review.json", report)
        return report

    agents = load_review_agents()
    # Iter 016: render review agents through persona binding.
    personas = load_personas()
    rendered_agents: List[Dict[str, Any]] = []
    legacy_to_rendered_name: Dict[str, str] = {}
    for agent in agents:
        legacy_name = str(agent.get("name") or "")
        name, system_prompt, stance = render_agent_fields(agent, personas, log_context="review")
        rendered = dict(agent)
        rendered["name"] = name or legacy_name or "agent"
        rendered["system_prompt"] = system_prompt
        rendered["stance"] = stance
        # Keep legacy_name so downstream logic that special-cases "关系一致性" still
        # works when persona binding replaces the display name.
        rendered["_legacy_name"] = legacy_name
        legacy_to_rendered_name[legacy_name] = rendered["name"]
        rendered_agents.append(rendered)
    agents = rendered_agents
    client = LLMClient("review")
    facts = global_facts_summary()
    entity_state = render_active_state(load_entity_graph())
    entity_block = f"{entity_state}\n" if entity_state else ""
    # Iter 022 B4: KB + source-chapter blocks if caller supplied them.
    # These are truncated to keep prompt size sane; the caller is
    # responsible for sending sensibly-sized chunks (typical: KB 6K
    # chars, source_chapters 8K chars).
    knowledge_block = (
        f"# 全局知识 (KB) — 反映原作世界观\n\n{knowledge[:6000]}\n\n"
        if knowledge
        else ""
    )
    source_block = (
        "# 原文风格参考（起点前 K 章节选）— 文笔贴合度判断基准\n\n"
        f"{source_chapters[:8000]}\n\n"
        "你的 fidelity 评分应明确对照上述原文风格。\n\n"
        if source_chapters
        else ""
    )
    # Iter 023 P3: scene-matched archetype excerpts (genre/scene-specific
    # rather than chronological). Helps fidelity scoring when the chapter
    # is e.g. a battle and source_chapters happens to be daily-life.
    scene_block = (
        "# 原作 archetype 参考（按本章 scene_type 匹配的原文片段）— 笔法/节奏锚点\n\n"
        f"{scene_excerpts[:8000]}\n\n"
        if scene_excerpts
        else ""
    )
    reviews = []
    for agent in agents:
        content = client.complete_text(
            [
                {"role": "system", "content": agent.get("system_prompt", agent.get("stance", ""))},
                {
                    "role": "user",
                    "content": (
                        f"agent_name: {agent['name']}\n"
                        "请审查下面续写章节。只输出 JSON object，包含以下字段：\n"
                        "  - verdict: 'Approve' 或 'Reject'\n"
                        "  - plot: 0-10 整数（情节推进力 — 本章是否推进主线/支线、节奏是否合理）\n"
                        "  - prose: 0-10 整数（文笔质感 — 句式变化、对话自然度、描写密度）\n"
                        "  - fidelity: 0-10 整数（与原作贴合度 — 人物声音、世界观术语、节奏是否像目标作者）\n"
                        "  - issues: 数组，可输出字符串，或对象 {message, rule_id, severity, anchor}；"
                        "severity 只能是 block、major、minor\n"
                        "  - suggestions: 数组，每条一句话改写建议\n"
                        "三个 sub-score 必须真实反映你的判断，禁止全部填 7 之类的偷懒值。"
                        "如果某一维度无法判断，使用 5 作为'不确定'信号，不要默认 7。\n\n"
                        f"{knowledge_block}"
                        f"{source_block}"
                        f"{scene_block}"
                        f"人工全局事实:\n{facts}\n\n"
                        f"{entity_block}"
                        f"{text[:18000]}"
                    ),
                },
            ],
        )
        try:
            raw = json.loads(extract_json_object(content))
        except (ValueError, json.JSONDecodeError) as exc:
            log_event(
                "review",
                "json_parse_fallback",
                target=target_name,
                agent=agent["name"],
                error=str(exc),
                content_preview=content[:200],
            )
            # Debug fix (post iter 019): before recording Abstain, try ONE
            # simplified-prompt fallback call. The original review prompt
            # asks for a structured object with optional sub-fields (the
            # 关系一致性 agent additionally demands a checklist block),
            # which is the most common reason JSON parsing fails. The
            # simplified prompt only asks for {verdict, reason} — much
            # more reliable. If THIS call also fails to parse, we keep
            # the iter 019 Abstain behavior (fail-closed still holds).
            simple_raw = _simple_verdict_fallback(
                client=client,
                agent=agent,
                draft=text[:18000],
                last_response_preview=content[:500],
                target_name=target_name,
            )
            if simple_raw is not None:
                simple_raw["agent_name"] = agent["name"]
                simple_raw.setdefault("issues", [])
                simple_raw["_fallback_reason"] = "(simple_prompt_recovery)"
                reviews.append(simple_raw)
                continue
            # Iter 019 audit fix: a single agent's malformed JSON must NOT
            # short-circuit the entire review with a silent Approve. Append
            # an Abstain vote for this agent and let the remaining agents
            # vote. The post-loop guard forces Reject if EVERY agent
            # abstains, so an entirely-broken review can't silently approve.
            reviews.append(
                {
                    "agent_name": agent["name"],
                    "verdict": "Abstain",
                    "issues": [],
                    "_fallback_reason": "(parse_failed)",
                }
            )
            continue
        # The relationship checklist enforcement keys off the legacy agent name
        # (a rule-semantic identifier), not the persona-rendered display name.
        repair_name = str(agent.get("_legacy_name") or agent.get("name") or "")
        repaired = _repair_agent_review_dict(raw, repair_name, enforce_relationship_checklist)
        # Display the rendered name in the final review report.
        repaired["agent_name"] = agent["name"]
        if repaired.get("verdict") not in ("Approve", "Reject"):
            log_event(
                "review",
                "bad_verdict_abstain",
                target=target_name,
                agent=agent["name"],
                raw_verdict=str(raw.get("verdict", ""))[:80] if isinstance(raw, dict) else "",
            )
            reviews.append(
                {
                    "agent_name": agent["name"],
                    "verdict": "Abstain",
                    "issues": [],
                    "_fallback_reason": "(bad_verdict)",
                }
            )
            continue
        try:
            result = AgentReview(**repaired)
        except Exception as exc:
            log_event(
                "review",
                "schema_invalid_fallback",
                target=target_name,
                agent=agent["name"],
                error=str(exc),
            )
            simple_raw = _simple_verdict_fallback(
                client=client,
                agent=agent,
                draft=text[:18000],
                last_response_preview=content[:500],
                target_name=target_name,
            )
            if simple_raw is not None:
                simple_raw["agent_name"] = agent["name"]
                simple_raw.setdefault("issues", [])
                simple_raw["_fallback_reason"] = "(schema_invalid_simple_prompt_recovery)"
                reviews.append(simple_raw)
                continue
            reviews.append(
                {
                    "agent_name": agent["name"],
                    "verdict": "Abstain",
                    "issues": [],
                    "_fallback_reason": "(schema_invalid)",
                }
            )
            continue
        data = model_to_dict(result)
        data["agent_name"] = agent["name"]
        reviews.append(data)
    # Iter 023 P5: deterministic relationship auditor. After LLM agents
    # finish, run a pure-Python check of (entity_graph active state vs
    # draft co-occurrence). Output a synthetic agent_review so fail-closed
    # verdict aggregation includes structural conflicts. Zero LLM cost.
    try:
        from . import relationship_auditor

        rel_issues = relationship_auditor.audit_relationships(
            text, load_entity_graph()
        )
    except Exception as exc:
        # Defensive: never let auditor failure crash the review pipeline.
        log_event(
            "review",
            "relationship_auditor_error",
            target=target_name,
            error=str(exc),
        )
        rel_issues = []
    if rel_issues:
        reviews.append(
            {
                "agent_name": "deterministic_relations",
                "verdict": "Reject",
                "scores": {"plot": 5, "prose": 5, "fidelity": 4},
                "score": 5,
                "issues": [
                    {
                        "message": iss.get("conflict_reason", ""),
                        "rule_id": "relationship_hard_conflict",
                        "severity": "block",
                        "anchor": iss.get("draft_excerpt", "")[:80],
                    }
                    for iss in rel_issues
                ],
                "suggestions": [],
                "_synthetic": True,
            }
        )

    # Iter 019 audit fix: aggregate over substantive verdicts only. Treat
    # all-abstain as Reject (fail-closed) so a fully-broken multi-agent
    # review cannot accidentally approve a chapter.
    substantive = [r for r in reviews if r.get("verdict") in ("Approve", "Reject")]
    if not substantive:
        verdict = "Reject"
    elif any(r.get("verdict") == "Reject" for r in substantive):
        verdict = "Reject"
    else:
        verdict = "Approve"
    # Iter 024 P1: advisor agents (non-voting). Run after voting agents
    # so they see lint + review issues as context. Output structured
    # RewriteSuggestion list joined into report["rewrite_suggestions"].
    # Failures are logged but never block — advisor degradation must not
    # affect verdict (which is already computed above).
    rewrite_suggestions: List[Dict[str, Any]] = []
    try:
        advisor_agents = load_advisor_agents()
    except Exception:
        advisor_agents = []
    if advisor_agents:
        advisor_context = _build_advisor_context_block(
            lint_issues=lint_issues, reviews=reviews
        )
        for advisor in advisor_agents:
            adv_name = str(advisor.get("name") or "advisor")
            try:
                # Render via persona binding so {protagonist_name} etc resolve
                name, system_prompt, _stance = render_agent_fields(
                    advisor, personas, log_context="advisor"
                )
                rendered_name = name or adv_name
                content = client.complete_text(
                    [
                        {"role": "system", "content": system_prompt or advisor.get("system_prompt", "")},
                        {
                            "role": "user",
                            "content": (
                                f"advisor_name: {rendered_name}\n"
                                "请基于下面的 lint 命中 + 其他 reviewer 的 issues + 章节正文，"
                                "给出 1-5 条结构化 RewriteSuggestion。**只输出 JSON object** "
                                '形如 {"suggestions": [{"section": "...", "type": "add|rewrite|cut", "guidance": "..."}, ...]}\n'
                                "字段约束：section ≤ 60 字（如 '第 3 段'/'开场'/'结尾 hook'）；"
                                "type 三选一；guidance ≤ 300 字，具体到改什么而非泛泛建议。\n\n"
                                f"{advisor_context}\n"
                                f"# 章节正文（截前 12000 字）\n\n{text[:12000]}"
                            ),
                        },
                    ],
                )
                try:
                    parsed = json.loads(extract_json_object(content))
                except (ValueError, json.JSONDecodeError) as exc:
                    log_event(
                        "review",
                        "advisor_parse_failed",
                        target=target_name,
                        advisor=rendered_name,
                        error=str(exc),
                    )
                    continue
                suggs = parsed.get("suggestions", []) if isinstance(parsed, dict) else []
                for s in (suggs or [])[:5]:
                    if not isinstance(s, dict):
                        continue
                    try:
                        rs = RewriteSuggestion(**s)
                        sug_dict = model_to_dict(rs)
                        sug_dict["_advisor"] = rendered_name
                        rewrite_suggestions.append(sug_dict)
                    except Exception as schema_exc:
                        log_event(
                            "review",
                            "advisor_schema_invalid",
                            target=target_name,
                            advisor=rendered_name,
                            error=str(schema_exc),
                        )
            except Exception as exc:
                log_event(
                    "review",
                    "advisor_runtime_error",
                    target=target_name,
                    advisor=adv_name,
                    error=str(exc),
                )
                continue

    report = {
        "target": target_name,
        "rewrite_round": rewrite_round,
        "lint_issues": lint_issues,
        "agent_reviews": reviews,
        "rewrite_suggestions": rewrite_suggestions,
        "verdict": verdict,
        "run_context": run_context or {},
        "draft_sha256": draft_sha256,
    }
    if reviews and not substantive:
        report["_fallback_reason"] = "(all_agents_parse_failed)"
    write_json(reviews_dir / f"{Path(target_name).stem}.review.json", report)
    log_event("review", verdict.lower(), target=target_name)
    return report


def _build_advisor_context_block(
    lint_issues: List[Dict[str, Any]], reviews: List[Dict[str, Any]]
) -> str:
    """Iter 024 P1: compact context summary for advisor prompts (lint
    + reviewer issues). Avoids dumping the full review json which is
    huge — advisor only needs structured signal of what other agents
    flagged."""
    parts = []
    if lint_issues:
        from collections import Counter as _Counter
        rule_counts = _Counter(i.get("rule", "?") for i in lint_issues)
        parts.append("# Lint 命中（不要重复触发同样规则）\n")
        for rule, n in rule_counts.most_common():
            parts.append(f"- {rule}: {n} 次")
    if reviews:
        parts.append("\n# 其他 agent 反馈摘要")
        for r in reviews:
            name = r.get("agent_name", "?")
            verdict = r.get("verdict", "?")
            scores = r.get("scores", {}) or {}
            sub = f"plot={scores.get('plot','?')}/prose={scores.get('prose','?')}/fidelity={scores.get('fidelity','?')}"
            parts.append(f"- **{name}** [{verdict}] {sub}")
            for issue in (r.get("issues") or [])[:1]:
                if isinstance(issue, dict):
                    msg = str(issue.get("message", ""))[:140]
                    if msg:
                        parts.append(f"    · {msg}")
                elif isinstance(issue, str):
                    parts.append(f"    · {issue[:140]}")
    return "\n".join(parts)


def review_target(target: Path, enforce_relationship_checklist: Any = False) -> List[Dict[str, Any]]:
    def _review_file(path: Path) -> Dict[str, Any]:
        meta_path = path.with_suffix(".meta.json")
        run_context: Dict[str, Any] = {}
        draft_sha256 = ""
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                meta = {}
            if isinstance(meta, dict):
                ctx = meta.get("run_context")
                if isinstance(ctx, dict):
                    run_context = ctx
                draft_sha256 = str(meta.get("draft_sha256") or "")
        return review_text(
            path.read_text(encoding="utf-8"),
            path.name,
            enforce_relationship_checklist=enforce_relationship_checklist,
            run_context=run_context,
            draft_sha256=draft_sha256,
        )

    if target.is_file():
        return [_review_file(target)]
    if target.is_dir():
        reports = []
        for path in sorted(target.glob("*.md")):
            reports.append(_review_file(path))
        return reports
    raise FileNotFoundError(f"review target not found: {target}")
