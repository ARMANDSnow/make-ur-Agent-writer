#!/usr/bin/env python3
"""Validate the repository-local agent workflow without touching private data."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


EXPECTED_ITERATION_SECTIONS = [
    "Context",
    "Plan",
    "Acceptance",
    "Implementation Notes",
    "Acceptance Result",
    "文件变更汇总",
    "不在本轮范围",
    "Notes",
]

INDEX_ENTRY_RE = re.compile(
    r"^(?P<ordinal>\d+)\. \[Iteration (?P<iteration>[0-9A-Za-z]+) - .+\]"
    r"\(\./(?P<target>[^)]+)\)$",
    re.MULTILINE,
)
HANDOFF_ITER_RE = re.compile(r"\|\s*更新时间\s*\|\s*iter\s+(\d{3})\b")
README_ITER_RE = re.compile(r"最近一次更新：\*\*iter\s+(\d{3})\*\*")


@dataclass(frozen=True)
class IndexEntry:
    ordinal: int
    iteration: str
    target: str


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {path}: {exc}")
        return ""


def _single_match(
    pattern: re.Pattern[str], text: str, label: str, errors: list[str]
) -> str | None:
    matches = pattern.findall(text)
    if len(matches) != 1:
        errors.append(f"{label} must appear exactly once (found {len(matches)})")
        return None
    return matches[0]


def _h2_headings(text: str) -> list[str]:
    headings: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None and line.startswith("## "):
            headings.append(line[3:].strip())
    return headings


def _section(text: str, name: str) -> str:
    match = re.search(
        rf"^## {re.escape(name)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _frontmatter_name(text: str) -> str | None:
    match = re.match(r"\A---\s*\n.*?^name:\s*([^\n]+)\n.*?^---\s*$", text, re.M | re.S)
    return match.group(1).strip().strip('"\'') if match else None


def _check_skills(root: Path, errors: list[str]) -> None:
    skills = {
        "iter-start": root / ".agents/skills/iter-start/SKILL.md",
        "iter-finish": root / ".agents/skills/iter-finish/SKILL.md",
    }
    texts: dict[str, str] = {}
    for name, path in skills.items():
        text = _read(path, errors)
        texts[name] = text
        if text and _frontmatter_name(text) != name:
            errors.append(f"{path} frontmatter name must be {name!r}")

    finish = texts.get("iter-finish", "")
    for forbidden in (
        "追加 AGENT_HANDOFF Phase Status",
        "### 4. 追加 AGENT_HANDOFF Phase Status",
        'python3 -m unittest discover -s tests\nbash scripts/verify.sh',
        "并把上一轮整段降级",
    ):
        if forbidden in finish:
            errors.append(f"iter-finish contains obsolete workflow text: {forbidden!r}")
    for required in (
        "聚焦",
        "只读",
        "bash scripts/verify.sh",
        "就地更新",
        "不得新增逐轮",
    ):
        if finish and required not in finish:
            errors.append(f"iter-finish is missing required workflow marker: {required!r}")

    start = texts.get("iter-start", "")
    for required in ("8 段", "docs/iterations/README.md", "不要 commit", "不要 push"):
        if start and required not in start:
            errors.append(f"iter-start is missing required workflow marker: {required!r}")


def check_harness(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    iterations_dir = root / "docs/iterations"

    index_text = _read(iterations_dir / "README.md", errors)
    entries = [
        IndexEntry(int(m.group("ordinal")), m.group("iteration"), m.group("target"))
        for m in INDEX_ENTRY_RE.finditer(index_text)
    ]
    if not entries:
        errors.append("iteration index has no canonical entries")
    else:
        ordinals = [entry.ordinal for entry in entries]
        expected = list(range(1, len(entries) + 1))
        if ordinals != expected:
            errors.append(
                "iteration index ordinals must be consecutive from 1 "
                f"(found {ordinals[:3]}...{ordinals[-3:]})"
            )

    iterations_root = iterations_dir.resolve()
    valid_targets: dict[str, Path] = {}
    for entry in entries:
        target = (iterations_dir / entry.target).resolve()
        try:
            target.relative_to(iterations_root)
        except ValueError:
            errors.append(f"iteration index target escapes docs/iterations: {entry.target}")
            continue
        if not target.is_file():
            errors.append(f"iteration index target is missing: {entry.target}")
            continue
        valid_targets[entry.target] = target

    handoff_text = _read(root / "docs/AGENT_HANDOFF.md", errors)
    readme_text = _read(root / "README.md", errors)
    accepted = _single_match(
        HANDOFF_ITER_RE, handoff_text, "handoff accepted iteration", errors
    )
    readme_iter = _single_match(
        README_ITER_RE, readme_text, "README latest iteration", errors
    )
    if accepted and readme_iter and accepted != readme_iter:
        errors.append(
            f"accepted iteration mismatch: handoff={accepted}, README={readme_iter}"
        )

    active: str | None = None
    if entries and accepted:
        latest = entries[-1]
        accepted_entries = [entry for entry in entries if entry.iteration == accepted]
        if len(accepted_entries) != 1:
            errors.append(
                f"accepted iteration {accepted} must appear exactly once in the index "
                f"(found {len(accepted_entries)})"
            )
        else:
            accepted_entry = accepted_entries[0]
            if not accepted_entry.target.startswith(f"iteration_{accepted}_"):
                errors.append(
                    f"accepted index target must start with iteration_{accepted}_: "
                    f"{accepted_entry.target}"
                )

        if latest.iteration == accepted:
            active = None
        elif (
            latest.iteration.isdigit()
            and len(latest.iteration) == 3
            and int(latest.iteration) == int(accepted) + 1
        ):
            active = latest.iteration
        else:
            errors.append(
                f"index latest must be accepted iter {accepted} or one active next iter; "
                f"found {latest.iteration}"
            )

        if not latest.target.startswith(f"iteration_{latest.iteration}_"):
            errors.append(
                f"latest index target must start with iteration_{latest.iteration}_: "
                f"{latest.target}"
            )
        latest_path = valid_targets.get(latest.target)
        if latest_path is not None:
            headings = _h2_headings(_read(latest_path, errors))
            if headings != EXPECTED_ITERATION_SECTIONS:
                errors.append(
                    f"latest indexed iteration must have exactly the 8 canonical sections; "
                    f"found {headings}"
                )

    agents_text = _read(root / "AGENTS.md", errors)
    validation = _section(agents_text, "标准验证")
    if not validation:
        errors.append("AGENTS.md is missing the 标准验证 section")
    else:
        if "bash scripts/verify.sh" not in validation:
            errors.append("AGENTS.md standard validation must call scripts/verify.sh")
        for duplicate in ("unittest discover -s tests", "main.py preflight"):
            if duplicate in validation:
                errors.append(
                    f"AGENTS.md standard validation duplicates verify.sh step: {duplicate}"
                )

    quick_start = _section(readme_text, "快速开始")
    if quick_start and "unittest discover -s tests" in quick_start:
        errors.append("README quick start duplicates the unittest run inside verify.sh")

    _check_skills(root, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args()
    errors = check_harness(args.root)
    if errors:
        for error in errors:
            print(f"HARNESS ERROR: {error}", file=sys.stderr)
        return 1

    index_text = (args.root / "docs/iterations/README.md").read_text(encoding="utf-8")
    count = len(list(INDEX_ENTRY_RE.finditer(index_text)))
    handoff_text = (args.root / "docs/AGENT_HANDOFF.md").read_text(encoding="utf-8")
    accepted = HANDOFF_ITER_RE.search(handoff_text)
    accepted_label = accepted.group(1) if accepted else "unknown"
    entries = list(INDEX_ENTRY_RE.finditer(index_text))
    latest_label = entries[-1].group("iteration") if entries else "unknown"
    active_label = latest_label if latest_label != accepted_label else "none"
    print(
        f"agent harness OK (accepted iter {accepted_label}, active iter {active_label}, "
        f"{count} index entries)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
