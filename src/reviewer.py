from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .config import ROOT, load_config
from .linter import NovelLinter
from .llm_client import LLMClient
from .manual_facts import global_facts_summary
from .schemas import AgentReview, model_to_dict
from .state import log_event
from .utils import ensure_dir, extract_json_object, write_json


REVIEWS_DIR = ROOT / "outputs" / "reviews"


def load_review_agents() -> List[Dict[str, Any]]:
    cfg = load_config("agents.yaml")
    return cfg.get("review_agents", [])


def _repair_agent_review_dict(raw: Any, agent_name: str) -> Dict[str, Any]:
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
    return repaired


def review_text(
    text: str,
    target_name: str = "draft",
    precomputed_lint_issues: List[Dict[str, Any]] | None = None,
    rewrite_round: int = 0,
) -> Dict[str, Any]:
    ensure_dir(REVIEWS_DIR)
    if precomputed_lint_issues is not None:
        lint_issues = precomputed_lint_issues
    else:
        linter = NovelLinter()
        lint_issues = linter.lint(text)
    if any(issue["severity"] == "error" for issue in lint_issues):
        report = {
            "target": target_name,
            "rewrite_round": rewrite_round,
            "lint_issues": lint_issues,
            "agent_reviews": [],
            "verdict": "Reject",
        }
        write_json(REVIEWS_DIR / f"{Path(target_name).stem}.review.json", report)
        return report

    agents = load_review_agents()
    client = LLMClient("review")
    facts = global_facts_summary()
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
                        f"{text[:18000]}"
                    ),
                },
            ],
        )
        raw = json.loads(extract_json_object(content))
        result = AgentReview(**_repair_agent_review_dict(raw, agent["name"]))
        data = model_to_dict(result)
        data["agent_name"] = agent["name"]
        reviews.append(data)
    verdict = "Reject" if any(r.get("verdict") == "Reject" for r in reviews) else "Approve"
    report = {
        "target": target_name,
        "rewrite_round": rewrite_round,
        "lint_issues": lint_issues,
        "agent_reviews": reviews,
        "verdict": verdict,
    }
    write_json(REVIEWS_DIR / f"{Path(target_name).stem}.review.json", report)
    log_event("review", verdict.lower(), target=target_name)
    return report


def review_target(target: Path) -> List[Dict[str, Any]]:
    if target.is_file():
        return [review_text(target.read_text(encoding="utf-8"), target.name)]
    if target.is_dir():
        reports = []
        for path in sorted(target.glob("*.md")):
            reports.append(review_text(path.read_text(encoding="utf-8"), path.name))
        return reports
    raise FileNotFoundError(f"review target not found: {target}")
