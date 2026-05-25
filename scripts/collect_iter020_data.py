"""iter 020: collect smoke data from longzu workspace.

Scans all chapter_*.meta.json files in workspaces/longzu/outputs/drafts/
and llm_calls.jsonl to produce a per-chapter summary table used by the
iter 020 failure-mode analysis.

Output: stdout markdown table + a JSON summary at
workspaces/longzu/outputs/drafts/iter020_summary.json.

Usage:
    python3 scripts/collect_iter020_data.py [--book longzu]

No LLM calls. Pure I/O + aggregation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Make src importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _set_book(book: str) -> None:
    os.environ["WORKSPACE_NAME"] = book


def _load_metas(drafts_dir: Path) -> list[dict]:
    metas = []
    for p in sorted(drafts_dir.glob("chapter_*.meta.json")):
        try:
            with p.open(encoding="utf-8") as f:
                d = json.load(f)
            d["_path"] = str(p)
            d["_chapter_no"] = int(p.stem.replace("chapter_", "").replace(".meta", ""))
            metas.append(d)
        except Exception as exc:
            print(f"WARN: skipping {p}: {exc}", file=sys.stderr)
    return metas


def _load_llm_calls(logs_dir: Path) -> list[dict]:
    calls = []
    p = logs_dir / "llm_calls.jsonl"
    if not p.exists():
        return calls
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return calls


# DeepSeek V3-pro est. pricing (USD per 1M tokens)
PROMPT_USD_PER_M = 0.27
CACHE_READ_USD_PER_M = 0.07
RESPONSE_USD_PER_M = 1.10
USD_TO_CNY = 7.2


def _cost_cny(prompt_tokens: int, cache_read: int, response_tokens: int) -> float:
    non_cache = max(prompt_tokens - cache_read, 0)
    usd = (
        non_cache * PROMPT_USD_PER_M / 1e6
        + cache_read * CACHE_READ_USD_PER_M / 1e6
        + response_tokens * RESPONSE_USD_PER_M / 1e6
    )
    return usd * USD_TO_CNY


def _per_chapter_review_stats(meta: dict) -> dict:
    reviews = meta.get("agent_reviews", [])
    scores = [r.get("score") for r in reviews if isinstance(r.get("score"), (int, float))]
    verdicts = Counter(r.get("verdict", "?") for r in reviews)
    abstains = [r for r in reviews if r.get("verdict") == "Abstain"]
    return {
        "n_agents": len(reviews),
        "scores": scores,
        "score_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "verdicts": dict(verdicts),
        "n_abstain_parse_failed": sum(
            1 for r in abstains if r.get("_fallback_reason") == "(parse_failed)"
        ),
    }


def _lint_breakdown(metas: list[dict]) -> Counter:
    """Count lint rule hits across all chapters (current + blocked)."""
    counter: Counter = Counter()
    for m in metas:
        for issue in m.get("lint_issues", []):
            counter[issue.get("rule", "?")] += 1
        for blocked in m.get("lint_blocked_reviews", []):
            for issue in blocked.get("lint_issues", []):
                counter[issue.get("rule", "?")] += 1
    return counter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", default="longzu")
    args = parser.parse_args()

    _set_book(args.book)
    from src import paths  # noqa: E402 — must come after env is set

    drafts_dir = paths.drafts_dir()
    logs_dir = paths.logs_dir()
    metas = _load_metas(drafts_dir)
    calls = _load_llm_calls(logs_dir)

    print(f"# iter 020 smoke summary — book={args.book}\n")
    print(f"drafts found: {len(metas)} chapter(s)")
    print(f"llm_calls total: {len(calls)} call(s)\n")

    # Per-chapter table
    print("## Per-chapter table\n")
    print("| ch | verdict | rewrite | chars | lint_n | review_n | score_avg | parse_fail |")
    print("|----|---------|---------|-------|--------|----------|-----------|------------|")
    rows = []
    for m in metas:
        stats = _per_chapter_review_stats(m)
        row = {
            "chapter_no": m["_chapter_no"],
            "verdict": m.get("verdict", "?"),
            "rewrite_count": m.get("rewrite_count", "?"),
            "chinese_chars": m.get("chinese_char_count", "?"),
            "lint_issues_n": len(m.get("lint_issues", [])),
            **stats,
        }
        rows.append(row)
        print(
            f"| {row['chapter_no']:>2} | {row['verdict']:>7} | "
            f"{row['rewrite_count']:>7} | {row['chinese_chars']:>5} | "
            f"{row['lint_issues_n']:>6} | {row['n_agents']:>8} | "
            f"{row['score_avg'] if row['score_avg'] is not None else '?':>9} | "
            f"{row['n_abstain_parse_failed']:>10} |"
        )

    # Approved %
    approved = sum(1 for r in rows if r["verdict"] == "Approve")
    print(f"\n**Approval rate: {approved}/{len(rows)}**")

    # Lint breakdown
    print("\n## Lint rule hits (current + blocked attempts)\n")
    breakdown = _lint_breakdown(metas)
    for rule, n in breakdown.most_common():
        print(f"- {rule}: {n}")

    # Cost summary by task
    print("\n## LLM cost summary (full log — not per-iter-020-window)\n")
    by_task: dict[str, dict] = defaultdict(lambda: {"calls": 0, "prompt": 0, "cache": 0, "resp": 0})
    for c in calls:
        t = c.get("task", "?")
        by_task[t]["calls"] += 1
        by_task[t]["prompt"] += c.get("prompt_tokens", 0)
        by_task[t]["cache"] += c.get("cache_read_tokens", 0)
        by_task[t]["resp"] += c.get("response_tokens", 0)
    print("| task | calls | prompt_tok | cache_read | resp_tok | cost ¥ |")
    print("|------|-------|------------|------------|----------|--------|")
    total_cny = 0.0
    for t, s in sorted(by_task.items()):
        cost = _cost_cny(s["prompt"], s["cache"], s["resp"])
        total_cny += cost
        print(
            f"| {t} | {s['calls']} | {s['prompt']} | {s['cache']} | {s['resp']} | {cost:.3f} |"
        )
    print(f"\n**Total estimated cost: ¥{total_cny:.2f}**")

    # Persona / agent score trend
    print("\n## Per-agent score across chapters\n")
    by_agent: dict[str, list[int]] = defaultdict(list)
    for m in metas:
        for r in m.get("agent_reviews", []):
            score = r.get("score")
            if isinstance(score, (int, float)):
                by_agent[r.get("agent_name", "?")].append((m["_chapter_no"], score))
    for agent, points in sorted(by_agent.items()):
        scores_only = [s for _, s in points]
        avg = round(sum(scores_only) / len(scores_only), 2) if scores_only else "?"
        print(f"- **{agent}** ({len(points)} reviews, avg={avg}): "
              f"{', '.join(f'ch{c}={s}' for c, s in points)}")

    # Dump JSON
    summary = {
        "book": args.book,
        "n_chapters": len(rows),
        "approval_rate": approved / len(rows) if rows else 0.0,
        "rows": rows,
        "lint_breakdown": dict(breakdown),
        "cost_by_task": {t: dict(s) for t, s in by_task.items()},
        "total_cny": round(total_cny, 2),
    }
    out_path = drafts_dir / "iter020_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON summary written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
