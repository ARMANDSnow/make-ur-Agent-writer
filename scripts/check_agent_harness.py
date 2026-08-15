#!/usr/bin/env python3
"""Validate the repository-local agent workflow without touching private data."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


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
HANDOFF_COMMIT_RE = re.compile(
    r"\|\s*Accepted implementation commit\s*\|\s*`?([0-9a-f]{40})`?\s*\|"
)
README_ITER_RE = re.compile(r"最近一次更新：\*\*iter\s+(\d{3})\*\*")
ACCEPTANCE_ID_RE = re.compile(r"\bA\d{3}-\d{2}\b")
STRUCTURED_CONTEXT_FROM_ITER = 112
STRUCTURED_CONTEXT_BLOCKS = {
    "Implementation Context": (
        "Plan",
        ("must_read", "expected_changes", "do_not_touch"),
    ),
    "Review Context": (
        "Acceptance",
        ("correctness_behavior", "security_boundary", "extra_risk_view"),
    ),
    "Knowledge Promotion": (
        "Acceptance Result",
        ("decision", "destination", "reason"),
    ),
}
STRUCTURED_FIELD_RE = re.compile(
    r"^[ ]{0,3}- `(?P<key>[a-z_]+)`:\s*(?P<value>.*?)\s*$", re.MULTILINE
)
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
ATX_HEADING_RE = re.compile(
    r"^[ ]{0,3}(?P<marker>#{1,6})(?:[ \t]+(?P<content>.*?))?[ \t]*$"
)
PRIVATE_CONTEXT_ROOTS = {
    ".git",
    ".venv",
    "data",
    "outputs",
    "logs",
    "workspaces",
    "小说txt",
}
PROMOTION_TARGETS = {
    "AGENTS.md",
    ".agents/skills/iter-start/SKILL.md",
    ".agents/skills/iter-finish/SKILL.md",
    "docs/PROJECT_HISTORY.md",
}
ALLOWED_CLOSURE_FILES = {
    "AGENTS.md",
    "README.md",
    "README_EN.md",
    "docs/AGENT_HANDOFF.md",
    "docs/PROJECT_HISTORY.md",
    "docs/iterations/README.md",
    "docs/product/GETTING_STARTED.md",
    "docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md",
    "docs/product/PRODUCT_SPEC.md",
    "docs/product/short_drama_creation_standard.md",
    "docs/product/short_drama_module.md",
}


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


def _fence_open(line: str) -> tuple[str, int] | None:
    match = FENCE_OPEN_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    if marker[0] == "`" and "`" in match.group("info"):
        return None
    return marker[0], len(marker)


def _fence_closes(line: str, fence: tuple[str, int]) -> bool:
    char, minimum = fence
    return re.fullmatch(rf"[ ]{{0,3}}{re.escape(char)}{{{minimum},}}[ \t]*", line) is not None


def _atx_heading(line: str) -> tuple[int, str] | None:
    match = ATX_HEADING_RE.fullmatch(line)
    if not match:
        return None
    content = match.group("content") or ""
    content = re.sub(r"[ \t]+#+[ \t]*$", "", content).strip()
    return len(match.group("marker")), content


def _h2_sections(text: str) -> list[tuple[str, str]]:
    """Split Markdown into real H2 bodies while ignoring fenced examples."""

    sections: list[tuple[str, str]] = []
    current_name: str | None = None
    current_body: list[str] = []
    fence: tuple[str, int] | None = None

    def flush() -> None:
        if current_name is not None:
            sections.append((current_name, "\n".join(current_body)))

    for line in text.splitlines():
        if fence is not None:
            if _fence_closes(line, fence):
                fence = None
            if current_name is not None:
                current_body.append(line)
            continue
        opening = _fence_open(line)
        if opening is not None:
            fence = opening
            if current_name is not None:
                current_body.append(line)
            continue
        heading = _atx_heading(line)
        if heading is not None and heading[0] == 2:
            flush()
            current_name = heading[1]
            current_body = []
            continue
        if current_name is not None:
            current_body.append(line)
    flush()
    return sections


def _h2_headings(text: str) -> list[str]:
    return [name for name, _body in _h2_sections(text)]


def _section(text: str, name: str) -> str:
    for heading, body in _h2_sections(text):
        if heading == name:
            return body
    return ""


def _h3_sections(text: str, name: str) -> list[str]:
    """Return matching H3 bodies while ignoring headings inside code fences."""

    matches: list[str] = []
    current_name: str | None = None
    current_body: list[str] = []
    fence: tuple[str, int] | None = None

    def flush() -> None:
        if current_name == name:
            matches.append("\n".join(current_body))

    for line in text.splitlines():
        if fence is not None:
            if _fence_closes(line, fence):
                fence = None
            if current_name is not None:
                current_body.append(line)
            continue
        opening = _fence_open(line)
        if opening is not None:
            fence = opening
            if current_name is not None:
                current_body.append(line)
            continue
        heading = _atx_heading(line)
        if heading is not None and heading[0] == 3:
            flush()
            current_name = heading[1]
            current_body = []
            continue
        if current_name is not None:
            current_body.append(line)
    flush()
    return matches


def _structured_fields(body: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    fence: tuple[str, int] | None = None
    for line in body.splitlines():
        if fence is not None:
            if _fence_closes(line, fence):
                fence = None
            continue
        opening = _fence_open(line)
        if opening is not None:
            fence = opening
            continue
        match = STRUCTURED_FIELD_RE.fullmatch(line)
        if match:
            fields.setdefault(match.group("key"), []).append(
                match.group("value").strip()
            )
    return fields


def _is_placeholder(value: str) -> bool:
    return not value.strip() or PLACEHOLDER_RE.search(value) is not None


def _inline_paths(value: str, label: str, errors: list[str]) -> list[str]:
    if re.fullmatch(r"`[^`\n]+`(?:,\s*`[^`\n]+`)*", value) is None:
        errors.append(f"{label} must be a comma-separated list of backtick paths")
        return []
    paths = re.findall(r"`([^`\n]+)`", value)
    if len(paths) != len(set(paths)):
        errors.append(f"{label} paths must be unique")
    return paths


def _safe_context_path(
    root: Path,
    raw: str,
    label: str,
    errors: list[str],
    *,
    must_exist: bool,
    must_be_tracked: bool = False,
) -> Path | None:
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith("~")
        or re.match(r"^[A-Za-z]:", raw)
    ):
        errors.append(f"{label} path must be repository-relative and canonical: {raw!r}")
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label} path must not be absolute or traverse parents: {raw!r}")
        return None
    if not relative.parts:
        errors.append(f"{label} path must not be empty")
        return None
    canonical = relative.as_posix()
    if raw != canonical:
        errors.append(f"{label} path must be canonical POSIX syntax: {raw!r}")
        return None
    first = relative.parts[0].casefold()
    if first.startswith(".env") or first in PRIVATE_CONTEXT_ROOTS:
        errors.append(f"{label} path points to a protected location: {raw!r}")
        return None
    candidate = root / Path(*relative.parts)
    try:
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                errors.append(f"{label} path must not contain symlinks: {raw!r}")
                return None
        resolved = candidate.resolve(strict=False)
        resolved_relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        errors.append(f"{label} path cannot be resolved safely: {raw!r}")
        return None
    resolved_first = resolved_relative.parts[0].casefold() if resolved_relative.parts else ""
    if resolved_first.startswith(".env") or resolved_first in PRIVATE_CONTEXT_ROOTS:
        errors.append(f"{label} path resolves to a protected location: {raw!r}")
        return None
    try:
        is_file = candidate.is_file()
        exists = candidate.exists()
    except (OSError, RuntimeError, ValueError):
        errors.append(f"{label} path cannot be inspected safely: {raw!r}")
        return None
    if must_exist and not is_file:
        errors.append(f"{label} path must reference an existing file: {raw!r}")
        return None
    if not must_exist and exists and not is_file:
        errors.append(f"{label} path must be a regular file when it exists: {raw!r}")
        return None
    if must_be_tracked:
        tracked = _git(
            root,
            "ls-files",
            "--error-unmatch",
            "--",
            f":(literal){canonical}",
        )
        if tracked is None or tracked.returncode != 0:
            errors.append(f"{label} path must be a Git-tracked regular file: {raw!r}")
            return None
    if must_exist and not resolved.is_file():
        # The lexical candidate was already checked; this closes unusual platform races.
        errors.append(f"{label} path must remain an existing file: {raw!r}")
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"{label} path escapes the repository: {raw!r}")
        return None
    return resolved


def _inline_scalar(value: str) -> str | None:
    match = re.fullmatch(r"`([^`\n]+)`", value.strip())
    return match.group(1) if match else None


def _allowed_promotion_target(raw: str) -> bool:
    path = PurePosixPath(raw)
    return raw in PROMOTION_TARGETS or (
        path.parent == PurePosixPath("docs/product") and path.suffix == ".md"
    )


def _check_knowledge_promotion(
    root: Path,
    fields: dict[str, list[str]],
    *,
    is_active: bool,
    errors: list[str],
) -> None:
    values = {key: fields[key][0] for key in ("decision", "destination", "reason")}
    placeholders = {key for key, value in values.items() if _is_placeholder(value)}
    if placeholders:
        if is_active and len(placeholders) == len(values):
            return
        errors.append(
            "Knowledge Promotion must be either entirely pending in an active iteration "
            "or fully completed"
        )
        return

    decision = _inline_scalar(values["decision"])
    if decision not in {"none", "promoted"}:
        errors.append("Knowledge Promotion decision must be `none` or `promoted`")
        return
    if decision == "none":
        if _inline_scalar(values["destination"]) != "none":
            errors.append("Knowledge Promotion decision `none` requires destination `none`")
        return

    targets = _inline_paths(
        values["destination"], "Knowledge Promotion destination", errors
    )
    for raw in targets:
        resolved = _safe_context_path(
            root,
            raw,
            "Knowledge Promotion destination",
            errors,
            must_exist=True,
            must_be_tracked=True,
        )
        if resolved is not None and not _allowed_promotion_target(raw):
            errors.append(
                "Knowledge Promotion destination is not an allowed authority document: "
                f"{raw!r}"
            )


def _check_structured_context(
    root: Path,
    text: str,
    iteration: str,
    *,
    is_active: bool,
    errors: list[str],
) -> None:
    if not iteration.isdigit() or int(iteration) < STRUCTURED_CONTEXT_FROM_ITER:
        return

    block_fields: dict[str, dict[str, list[str]]] = {}
    for block_name, (parent, required_fields) in STRUCTURED_CONTEXT_BLOCKS.items():
        matches_by_parent = {
            section: _h3_sections(_section(text, section), block_name)
            for section in EXPECTED_ITERATION_SECTIONS
        }
        total = sum(len(matches) for matches in matches_by_parent.values())
        correct = matches_by_parent[parent]
        if total != 1 or len(correct) != 1:
            errors.append(
                f"{block_name} must appear exactly once under ## {parent} "
                f"(found {total} total, {len(correct)} in the required section)"
            )
            continue
        fields = _structured_fields(correct[0])
        block_fields[block_name] = fields
        for field in required_fields:
            values = fields.get(field, [])
            if len(values) != 1:
                errors.append(
                    f"{block_name} field {field!r} must appear exactly once "
                    f"(found {len(values)})"
                )
                continue
            if block_name != "Knowledge Promotion" and _is_placeholder(values[0]):
                errors.append(f"{block_name} field {field!r} must not be empty or pending")

    implementation = block_fields.get("Implementation Context", {})
    for field, must_exist in (("must_read", True), ("expected_changes", False)):
        values = implementation.get(field, [])
        if len(values) != 1 or _is_placeholder(values[0]):
            continue
        for raw in _inline_paths(values[0], f"Implementation Context {field}", errors):
            _safe_context_path(
                root,
                raw,
                f"Implementation Context {field}",
                errors,
                must_exist=must_exist,
                must_be_tracked=must_exist,
            )

    promotion = block_fields.get("Knowledge Promotion", {})
    if all(len(promotion.get(field, [])) == 1 for field in ("decision", "destination", "reason")):
        _check_knowledge_promotion(
            root, promotion, is_active=is_active, errors=errors
        )


def _check_iteration_document(
    root: Path,
    path: Path,
    iteration: str,
    *,
    is_active: bool,
    label: str,
    errors: list[str],
) -> None:
    text = _read(path, errors)
    headings = _h2_headings(text)
    if headings != EXPECTED_ITERATION_SECTIONS:
        errors.append(
            f"{label} must have exactly the 8 canonical sections; found {headings}"
        )
    acceptance_ids = ACCEPTANCE_ID_RE.findall(_section(text, "Acceptance"))
    if len(acceptance_ids) != len(set(acceptance_ids)):
        errors.append(f"{label} Acceptance IDs must be unique")
    require_ids = iteration.isdigit() and int(iteration) >= 102
    expected_prefix = f"A{iteration}-"
    if require_ids and not acceptance_ids:
        errors.append(f"{label} must define at least one Acceptance ID")
    if any(not value.startswith(expected_prefix) for value in acceptance_ids):
        errors.append(f"{label} Acceptance IDs must match its iteration number")
    if not is_active and acceptance_ids:
        result_id_list = ACCEPTANCE_ID_RE.findall(
            _section(text, "Acceptance Result")
        )
        if len(result_id_list) != len(set(result_id_list)):
            errors.append(f"{label} Acceptance Result IDs must be unique")
        if set(acceptance_ids) != set(result_id_list):
            errors.append(
                f"{label} Acceptance and Result ID sets must match"
            )
    _check_structured_context(
        root,
        text,
        iteration,
        is_active=is_active,
        errors=errors,
    )


def _frontmatter_name(text: str) -> str | None:
    match = re.match(r"\A---\s*\n.*?^name:\s*([^\n]+)\n.*?^---\s*$", text, re.M | re.S)
    return match.group(1).strip().strip('"\'') if match else None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_paths(root: Path, *args: str) -> tuple[int, list[str]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, []
    return result.returncode, [
        value.decode("utf-8", errors="surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    ]


def _allowed_closure_path(path: str, accepted_target: str | None) -> bool:
    if path in ALLOWED_CLOSURE_FILES:
        return True
    return bool(accepted_target and path == f"docs/iterations/{accepted_target}")


def _check_accepted_baseline(
    root: Path,
    accepted_target: str | None,
    accepted_commit: str | None,
    active: str | None,
    errors: list[str],
) -> None:
    if not accepted_commit:
        return
    exists = _git(root, "cat-file", "-e", f"{accepted_commit}^{{commit}}")
    if exists is None or exists.returncode != 0:
        errors.append("accepted implementation commit does not exist")
        return
    ancestor = _git(root, "merge-base", "--is-ancestor", accepted_commit, "HEAD")
    if ancestor is None or ancestor.returncode != 0:
        errors.append("accepted implementation commit must be an ancestor of HEAD")
        return
    if active is not None:
        return

    changed_rc, changed_paths = _git_paths(
        root, "diff", "--name-only", "-z", accepted_commit, "--"
    )
    if changed_rc:
        errors.append("cannot compare accepted implementation commit to worktree")
        return
    forbidden = [
        path for path in changed_paths if not _allowed_closure_path(path, accepted_target)
    ]
    untracked_rc, untracked_paths = _git_paths(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if untracked_rc:
        errors.append("cannot inspect untracked repository paths")
        return
    forbidden.extend(
        path for path in untracked_paths if not path.startswith("docs/")
    )
    if forbidden:
        errors.append(
            "implementation drift exists after the accepted commit: "
            + ", ".join(sorted(set(forbidden))[:10])
        )


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
        "Review Context",
        "Knowledge Promotion",
        "git diff --check HEAD",
    ):
        if finish and required not in finish:
            errors.append(f"iter-finish is missing required workflow marker: {required!r}")

    start = texts.get("iter-start", "")
    for required in (
        "8 段",
        "docs/iterations/README.md",
        "不要 commit",
        "不要 push",
        "Implementation Context",
        "Review Context",
        "Knowledge Promotion",
    ):
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
    accepted_commit = _single_match(
        HANDOFF_COMMIT_RE, handoff_text, "handoff accepted implementation commit", errors
    )
    readme_iter = _single_match(
        README_ITER_RE, readme_text, "README latest iteration", errors
    )
    if accepted and readme_iter and accepted != readme_iter:
        errors.append(
            f"accepted iteration mismatch: handoff={accepted}, README={readme_iter}"
        )

    active: str | None = None
    accepted_target: str | None = None
    if entries and accepted:
        latest = entries[-1]
        accepted_entries = [entry for entry in entries if entry.iteration == accepted]
        accepted_entry: IndexEntry | None = None
        if len(accepted_entries) != 1:
            errors.append(
                f"accepted iteration {accepted} must appear exactly once in the index "
                f"(found {len(accepted_entries)})"
            )
        else:
            accepted_entry = accepted_entries[0]
            accepted_target = accepted_entry.target
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
        if accepted_entry is not None:
            accepted_path = valid_targets.get(accepted_entry.target)
            if accepted_path is not None:
                _check_iteration_document(
                    root,
                    accepted_path,
                    accepted,
                    is_active=False,
                    label=(
                        "latest indexed iteration"
                        if latest.iteration == accepted
                        else "accepted indexed iteration"
                    ),
                    errors=errors,
                )
        if latest.iteration != accepted:
            latest_path = valid_targets.get(latest.target)
            if latest_path is not None:
                _check_iteration_document(
                    root,
                    latest_path,
                    latest.iteration,
                    is_active=True,
                    label="latest indexed iteration",
                    errors=errors,
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
    _check_accepted_baseline(root, accepted_target, accepted_commit, active, errors)
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
