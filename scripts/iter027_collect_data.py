"""iter 027 P6 — capstone data collection.

Sweeps every ``workspaces/<book>/outputs/drafts/chapter_NN.meta.json``,
plus the workspace's llm_calls.jsonl, and emits a single JSON summary
the iter 027 report consumes.

Output (stdout): JSON with per-chapter records + aggregate stats.

Usage:
  /usr/bin/python3 scripts/iter027_collect_data.py --book longzu \\
      > workspaces/longzu/outputs/drafts/iter027_capstone_summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src import paths  # noqa: E402
from src.cost_estimator import cost_cny  # noqa: E402

_CHAPTER_META_RE = re.compile(r"^chapter_(\d{2,})\.meta\.json$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    args = parser.parse_args()

    import os

    os.environ["WORKSPACE_NAME"] = args.book
    ws_root = paths.workspace_root()
    drafts = ws_root / "outputs" / "drafts"
    log_path = ws_root / "logs" / "llm_calls.jsonl"

    chapters = _per_chapter_meta(drafts)
    llm_calls = _per_chapter_llm_calls(log_path)
    for ch in chapters:
        ch.update(llm_calls.get(ch["chapter"], {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "cache_read_tokens": 0, "cny": 0.0}))

    summary = {
        "book": args.book,
        "total_chapters": len(chapters),
        "approved": sum(1 for c in chapters if c["verdict"] == "Approve"),
        "rejected": sum(1 for c in chapters if c["verdict"] == "Reject"),
        "needs_human_review": sum(1 for c in chapters if c["needs_human_review"]),
        "rewrite_distribution": _distribution(c["rewrite_count"] for c in chapters),
        "lint_rule_hits": _lint_rule_distribution(chapters),
        "advisor_suggestion_total": sum(c["advisor_suggestions"] for c in chapters),
        "advisor_then_approve_count": sum(
            1 for c in chapters if c["advisor_suggestions"] > 0 and c["verdict"] == "Approve"
        ),
        "total_prompt_tokens": sum(c["prompt_tokens"] for c in chapters),
        "total_response_tokens": sum(c["response_tokens"] for c in chapters),
        "total_cache_read_tokens": sum(c["cache_read_tokens"] for c in chapters),
        "total_cny": round(sum(c["cny"] for c in chapters), 4),
        "per_chapter": chapters,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _per_chapter_meta(drafts: Path) -> list[dict]:
    out: list[dict] = []
    if not drafts.is_dir():
        return out
    for path in sorted(drafts.iterdir()):
        if not path.is_file():
            continue
        match = _CHAPTER_META_RE.match(path.name)
        if match is None:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        chap = int(match.group(1))
        out.append(
            {
                "chapter": chap,
                "verdict": meta.get("verdict"),
                "rewrite_count": int(meta.get("rewrite_count", 0)),
                "rewrite_round": int(meta.get("rewrite_round", 0)),
                "chinese_char_count": int(meta.get("chinese_char_count", 0)),
                "needs_human_review": bool(meta.get("needs_human_review", False)),
                "polish_applied": bool(meta.get("polish_applied", False)),
                "lint_issues": [
                    {"rule": li.get("rule"), "severity": li.get("severity")}
                    for li in (meta.get("lint_issues") or [])
                ],
                "agent_verdicts": [
                    {"agent": ar.get("agent_name"), "verdict": ar.get("verdict"), "score": ar.get("score")}
                    for ar in (meta.get("agent_reviews") or [])
                ],
                "advisor_suggestions": len(meta.get("rewrite_suggestions") or []),
            }
        )
    out.sort(key=lambda c: c["chapter"])
    return out


def _per_chapter_llm_calls(log_path: Path) -> dict:
    """Bucket llm_calls.jsonl entries by chapter via the ``operation``
    or ``payload.chapter`` field where present; otherwise lump under
    chapter 0 (orchestration overhead)."""
    by_chapter: dict[int, dict] = defaultdict(
        lambda: {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "cache_read_tokens": 0, "cny": 0.0}
    )
    if not log_path.exists():
        return {}
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chap = _chapter_of_call(rec)
                bucket = by_chapter[chap]
                bucket["calls"] += 1
                pt = int(rec.get("prompt_tokens", 0) or 0)
                rt = int(rec.get("response_tokens", 0) or 0)
                ct = int(rec.get("cache_read_tokens", 0) or 0)
                bucket["prompt_tokens"] += pt
                bucket["response_tokens"] += rt
                bucket["cache_read_tokens"] += ct
                bucket["cny"] += cost_cny(pt, ct, rt)
    except OSError:
        return {}
    return dict(by_chapter)


def _chapter_of_call(rec: dict) -> int:
    """Best-effort: pull a chapter int from various log shapes."""
    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    for key in ("chapter", "chapter_no", "resume_from"):
        for src_dict in (rec, payload):
            v = src_dict.get(key)
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
    return 0


def _distribution(values) -> dict:
    counts: dict[int, int] = defaultdict(int)
    for v in values:
        counts[int(v)] += 1
    return {str(k): counts[k] for k in sorted(counts.keys())}


def _lint_rule_distribution(chapters: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for c in chapters:
        for li in c["lint_issues"]:
            rule = li.get("rule") or "?"
            counts[rule] += 1
    return dict(counts)


if __name__ == "__main__":
    sys.exit(main())
