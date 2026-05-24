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
from .schemas import AgentReview, model_to_dict
from .state import log_event
from .utils import ensure_dir, extract_json_object, write_json


# Legacy constant — kept for iter 014-016 test backward compat.
REVIEWS_DIR = ROOT / "outputs" / "reviews"


def _reviews_dir() -> Path:
    return paths.reviews_dir() if paths.workspace_name() else REVIEWS_DIR


def load_review_agents() -> List[Dict[str, Any]]:
    cfg = load_config("agents.yaml")
    return cfg.get("review_agents", [])


def _relationship_checklist_issue() -> Dict[str, str]:
    return {
        "message": "关系一致性 reviewer 未输出对照清单，需人工复核 active 关系状态。",
        "rule_id": "relationship_checklist_missing",
        "severity": "major",
        "anchor": "",
    }


def _repair_agent_review_dict(raw: Any, agent_name: str, enforce_relationship_checklist: bool = True) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    repaired = dict(raw)
    repaired["agent_name"] = str(repaired.get("agent_name") or agent_name)
    verdict = str(repaired.get("verdict", "Reject")).strip().lower()
    repaired["verdict"] = "Reject" if verdict == "reject" else "Approve"
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


def review_text(
    text: str,
    target_name: str = "draft",
    precomputed_lint_issues: List[Dict[str, Any]] | None = None,
    rewrite_round: int = 0,
    run_agents_on_lint_error: bool = False,
    enforce_relationship_checklist: bool = False,
) -> Dict[str, Any]:
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
    reviews = []
    for agent in agents:
        content = client.complete_text(
            [
                {"role": "system", "content": agent.get("system_prompt", agent.get("stance", ""))},
                {
                    "role": "user",
                    "content": (
                        f"agent_name: {agent['name']}\n"
                        "请审查下面续写章节。只输出 JSON，verdict 必须是 Approve 或 Reject。"
                        "issues 可输出字符串，或输出对象 {message, rule_id, severity, anchor}；"
                        "severity 只能是 block、major、minor。\n\n"
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
        result = AgentReview(**repaired)
        data = model_to_dict(result)
        data["agent_name"] = agent["name"]
        reviews.append(data)
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
    report = {
        "target": target_name,
        "rewrite_round": rewrite_round,
        "lint_issues": lint_issues,
        "agent_reviews": reviews,
        "verdict": verdict,
    }
    if reviews and not substantive:
        report["_fallback_reason"] = "(all_agents_parse_failed)"
    write_json(reviews_dir / f"{Path(target_name).stem}.review.json", report)
    log_event("review", verdict.lower(), target=target_name)
    return report


def review_target(target: Path, enforce_relationship_checklist: bool = False) -> List[Dict[str, Any]]:
    if target.is_file():
        return [
            review_text(
                target.read_text(encoding="utf-8"),
                target.name,
                enforce_relationship_checklist=enforce_relationship_checklist,
            )
        ]
    if target.is_dir():
        reports = []
        for path in sorted(target.glob("*.md")):
            reports.append(
                review_text(
                    path.read_text(encoding="utf-8"),
                    path.name,
                    enforce_relationship_checklist=enforce_relationship_checklist,
                )
            )
        return reports
    raise FileNotFoundError(f"review target not found: {target}")
