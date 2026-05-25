"""iter 020: merge longzu ch1-10 (and ch10 final failed draft) into a
single .md file for human inspection.

Output:
    workspaces/longzu/outputs/drafts/iter020_chapters_1_to_10.md

Format per chapter:
    ## ch01 — 标题（来自 chapter_plan.json）
    状态：✅ Approve / ❌ Reject（rewrite N，lint M issues）

    <正文>

ch10 explicitly labelled as "FAILED DRAFT (3 attempts exhausted)".

Run from repo root:
    python3 scripts/merge_iter020_chapters.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# bootstrap workspace
os.environ["WORKSPACE_NAME"] = "longzu"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import paths  # noqa: E402

DRAFTS = paths.drafts_dir()
CHAPTER_PLAN = paths.chapter_plan_path()
OUT = DRAFTS / "iter020_chapters_1_to_10.md"


def _load_plan_titles() -> dict[int, str]:
    plan = json.loads(CHAPTER_PLAN.read_text(encoding="utf-8"))
    return {c["chapter_no"]: c.get("title", "(no title)") for c in plan["chapters"]}


def _chapter_meta(i: int) -> dict:
    p = DRAFTS / f"chapter_{i:02d}.meta.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _status_line(i: int, meta: dict) -> str:
    if not meta:
        return "状态：未知（meta 缺失）"
    verdict = meta.get("verdict", "?")
    rewrite = meta.get("rewrite_round", "?")
    lint_n = len(meta.get("lint_issues", []))
    chars = meta.get("chinese_char_count", "?")
    blocked = len(meta.get("lint_blocked_reviews", []))
    if verdict == "Approve":
        icon = "✅"
    elif verdict == "Reject":
        icon = "❌"
    else:
        icon = "⚠️"
    parts = [
        f"{icon} **{verdict}**",
        f"rewrite={rewrite}",
        f"中文字数={chars}",
        f"lint_issues={lint_n}",
    ]
    if blocked:
        parts.append(f"lint_blocked_attempts={blocked}")
    return "状态：" + "，".join(parts)


def _per_agent_scores(meta: dict) -> str:
    reviews = meta.get("agent_reviews", [])
    if not reviews:
        return ""
    parts = []
    for r in reviews:
        name = r.get("agent_name", "?")
        v = r.get("verdict", "?")
        score = r.get("score")
        score_str = f"{score}" if score is not None else "—"
        # mark abstain reasons
        fallback = r.get("_fallback_reason")
        if fallback:
            parts.append(f"{name}: {v}({score_str}, {fallback})")
        else:
            parts.append(f"{name}: {v}({score_str})")
    return "8-agent 评分：" + " | ".join(parts)


def _lint_summary(meta: dict) -> str:
    issues = meta.get("lint_issues", [])
    if not issues:
        return ""
    from collections import Counter
    rules = Counter(i.get("rule", "?") for i in issues)
    return "Lint 命中：" + ", ".join(f"{r}×{n}" for r, n in rules.most_common())


def main() -> int:
    titles = _load_plan_titles()
    out_lines: list[str] = []
    out_lines.append("# iter 020 longzu 续写 ch1-10 合并稿")
    out_lines.append("")
    out_lines.append("> 本文件由 `scripts/merge_iter020_chapters.py` 自动生成。")
    out_lines.append("> ch1-9 均通过 8-agent reviewer 审核（Approve）。")
    out_lines.append("> ch10 包含的是最终失败稿（3 次 outer attempt 全部 Reject）。")
    out_lines.append("> 失败的 attempt 1-2 在 `chapter_10.last_failure_attempt[12].md` 仍保留供对比。")
    out_lines.append("")

    for i in range(1, 11):
        title = titles.get(i, "(no title)")
        meta = _chapter_meta(i)
        md_path = DRAFTS / f"chapter_{i:02d}.md"
        if not md_path.exists():
            out_lines.append(f"\n---\n\n## ch{i:02d} — {title}")
            out_lines.append("\n（无草稿文件）\n")
            continue

        body = md_path.read_text(encoding="utf-8").strip()
        out_lines.append("\n---\n")
        out_lines.append(f"## ch{i:02d} — {title}")
        out_lines.append("")
        out_lines.append(_status_line(i, meta))
        agent_line = _per_agent_scores(meta)
        if agent_line:
            out_lines.append("")
            out_lines.append(agent_line)
        lint_line = _lint_summary(meta)
        if lint_line:
            out_lines.append("")
            out_lines.append(lint_line)
        if i == 10:
            out_lines.append("")
            out_lines.append("> ⚠️ **以下是 ch10 第 3 次也是最后一次 attempt 的正文，未通过审核。**")
            out_lines.append("> 仅供阅读对比，不应作为正式定稿。")
        out_lines.append("")
        out_lines.append(body)
        out_lines.append("")

    OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"OK: wrote {OUT}")
    print(f"  total chars: {len(''.join(out_lines))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
