#!/usr/bin/env python3
"""Fail when the novel-only branch regains removed runtime surfaces."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNED_PREFIXES = ("src/", "config/", "scripts/", "tests/", "prompts/")
SCANNED_FILES = {"main.py", ".env.example", ".gitignore"}
SELF = "scripts/check_novel_only_boundary.py"
REMOVED_SURFACE = re.compile(
    r"(?i)(?<![a-z])drama(?![a-z])|short[-_ ]?drama|短剧|DRAMA_|AI_DRAW|SD_API|SD_VIDEO"
)
GENERIC_REMOVED_SURFACE = re.compile(
    r"(?i)character-ref|shot-(?:image|video)|media-shot|asset-governance|"
    r"storyboard|hook_designer|outputs/episodes|episodes\{|episode_\d{2,3}|"
    r"(?:paid|real)_image|production-(?:shot|canvas|node|view)"
)
FORBIDDEN_PATH = re.compile(
    r"(?i)(?:^|/)(?:drama|short_drama)(?:/|_|\.)|"
    r"tests/fixtures/provider_contracts/.*(?:image|video)"
)


def _controlled_reference(rel: str, line: str) -> bool:
    if rel in {"scripts/check_agent_harness.py", "tests/test_agent_harness.py"}:
        return line.strip().strip(",").strip('"') in {
            "docs/product/short_drama_creation_standard.md",
            "docs/product/short_drama_module.md",
        }
    if rel == "tests/test_iter167_novel_only_split.py":
        return True
    if rel == ".gitignore":
        return line.strip() == "workspaces/.*.drama_multimodal_smoke.lock"
    if rel == "src/cli_workspace.py":
        return "legacy drama data" in line
    if rel == "src/web/workspace_meta.py":
        return any(token in line for token in ('"drama"', '``drama``'))
    if rel == "src/web/templates.py":
        return "短剧模块暂未开放" in line or "短剧模块" in line or "不提供短剧创建" in line
    return False


def scan_text(rel: str, value: str) -> list[str]:
    findings: list[str] = []
    for line_no, line in enumerate(value.splitlines(), 1):
        controlled = _controlled_reference(rel, line)
        if REMOVED_SURFACE.search(line) and not controlled:
            findings.append(f"{rel}:{line_no}: removed short-drama surface reference")
        if GENERIC_REMOVED_SURFACE.search(line) and not controlled:
            findings.append(f"{rel}:{line_no}: removed media/production surface reference")
    return findings


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for rel in tracked_files():
        if rel == SELF:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        if rel not in SCANNED_FILES and not rel.startswith(SCANNED_PREFIXES):
            continue
        if FORBIDDEN_PATH.search(rel):
            findings.append(f"{rel}: removed short-drama path remains tracked")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(rel, text))

    templates = (ROOT / "src/web/templates.py").read_text(encoding="utf-8")
    disabled_copy = "短剧模块暂未开放"
    if templates.count(disabled_copy) != 2:
        findings.append("src/web/templates.py: disabled entry count must stay exactly two")
    for line_no, line in enumerate(templates.splitlines(), 1):
        if disabled_copy in line and not (
            "<button" in line and " disabled" in line and 'aria-disabled="true"' in line
        ):
            findings.append(f"src/web/templates.py:{line_no}: disabled entry must be a native disabled button")
    for forbidden in (
        "?type=drama",
        "data-drama",
        "ui-drama",
        "panel-drama",
        "drama-form",
        "/api/wizard/drama-start",
    ):
        if forbidden in templates:
            findings.append(f"src/web/templates.py: forbidden navigation/runtime fragment {forbidden!r}")

    if findings:
        print("novel-only boundary check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("novel-only boundary OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
