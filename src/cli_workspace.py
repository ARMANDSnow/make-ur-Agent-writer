"""Iter 017: workspace management subcommands.

Backing implementations for:

* ``python3 main.py workspace-list``
* ``python3 main.py workspace-init <name>``
* ``python3 main.py workspace-import-current --to <name> [--dry-run]``
* ``python3 main.py workspace-show [--book <name>]``

Design contract:

* Never touches ``config/`` (those files are shared across workspaces).
* Never touches ``src/`` / ``tests/`` / ``docs/`` (those are code).
* ``workspace-import-current`` uses ``shutil.move`` (not copy) so the source
  novel only ever has one canonical copy on disk.
* All operations are idempotent and dry-runnable.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import ensure_dir


WORKSPACE_SUBDIRS = ("小说txt", "data", "outputs", "logs")
RESERVED_NAMES = {"legacy", "", ".", ".."}


def list_workspaces() -> List[str]:
    """Return the sorted names of existing per-book workspaces.

    Iter 026 code-review #6: a bare ``startswith('.')`` filter let
    tooling dirs like ``__pycache__`` / ``.pytest_cache`` show up as
    workspaces in the WebUI. We now also require at least one of
    ``data/`` or ``outputs/`` to exist — both are created by
    ``init_workspace`` so a real workspace always has one, and tooling
    caches never do.
    """
    if not paths.WORKSPACE_DIR.exists():
        return []
    names: List[str] = []
    for child in paths.WORKSPACE_DIR.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        # Filter out dev/tool cache dirs that share the parent.
        if not ((child / "data").is_dir() or (child / "outputs").is_dir()):
            continue
        names.append(child.name)
    return sorted(names)


def init_workspace(name: str) -> Dict[str, Any]:
    """Create ``workspaces/<name>/{小说txt,data,outputs,logs}/``."""
    _validate_name(name)
    target = paths.WORKSPACE_DIR / name
    if target.exists():
        raise FileExistsError(f"workspace already exists: {target}")
    ensure_dir(target)
    created: List[str] = []
    for sub in WORKSPACE_SUBDIRS:
        sub_path = target / sub
        ensure_dir(sub_path)
        # Render as a repo-relative path when possible (legacy aesthetic);
        # otherwise fall back to absolute (covers test sandboxes that point
        # paths.WORKSPACE_DIR outside the repo root).
        try:
            created.append(str(sub_path.relative_to(ROOT)))
        except ValueError:
            created.append(str(sub_path))
    return {
        "name": name,
        "path": str(target),
        "created": created,
    }


def import_current(to_name: str, dry_run: bool = False) -> Dict[str, Any]:
    """Move repo-root ``data/``, ``outputs/``, ``logs/``, ``小说txt/`` into
    ``workspaces/<to_name>/``.

    Uses ``shutil.move`` so the source text ends up in exactly one canonical
    location. ``config/`` and ``src/`` are never touched.
    """
    _validate_name(to_name)
    target = paths.WORKSPACE_DIR / to_name
    if target.exists():
        # Allow importing into an existing workspace only if its subdirs are
        # all empty — otherwise we'd overwrite real data silently.
        for sub in WORKSPACE_SUBDIRS:
            sub_path = target / sub
            if sub_path.exists() and any(sub_path.iterdir()):
                raise FileExistsError(
                    f"workspace '{to_name}' already has data in '{sub}/'. "
                    f"Refuse to overwrite; pick a new workspace name or clear it first."
                )

    operations: List[Dict[str, str]] = []
    for sub in WORKSPACE_SUBDIRS:
        src = ROOT / sub
        dst = target / sub
        if not src.exists():
            operations.append({"sub": sub, "src": str(src), "dst": str(dst), "action": "skip (src missing)"})
            continue
        if src.is_dir() and not any(src.iterdir()):
            operations.append({"sub": sub, "src": str(src), "dst": str(dst), "action": "skip (src empty)"})
            continue
        operations.append({"sub": sub, "src": str(src), "dst": str(dst), "action": "move"})

    if dry_run:
        return {"to": to_name, "dry_run": True, "operations": operations}

    ensure_dir(target)
    for op in operations:
        if op["action"] != "move":
            continue
        src = Path(op["src"])
        dst = Path(op["dst"])
        if dst.exists():
            # Merge: move each child into dst.
            ensure_dir(dst)
            for child in list(src.iterdir()):
                shutil.move(str(child), str(dst / child.name))
            # Remove the now-empty source dir (but keep src present as empty
            # placeholder so legacy mode still resolves cleanly).
            try:
                src.rmdir()
            except OSError:
                pass
        else:
            shutil.move(str(src), str(dst))
        # Re-create the legacy directory empty so subsequent legacy-mode
        # ``ls`` calls don't error and the gitignore rules keep working.
        ensure_dir(src)

    return {"to": to_name, "dry_run": False, "operations": operations}


def show_workspace(name: str | None = None) -> Dict[str, Any]:
    """Return a summary of the active or named workspace."""
    if name:
        _validate_name(name)
        root = paths.WORKSPACE_DIR / name
        label = name
    else:
        active = paths.workspace_name()
        root = paths.workspace_root()
        label = active or "legacy (repo root)"

    summary: Dict[str, Any] = {
        "name": label,
        "root": str(root),
        "exists": root.exists(),
    }
    if not root.exists():
        return summary

    raw = root / "小说txt"
    data = root / "data"
    outputs = root / "outputs"
    drafts = outputs / "drafts"
    manual = data / "manual_overrides"

    summary["raw_txt_count"] = len(list(raw.glob("*.txt"))) if raw.exists() else 0
    summary["normalized_count"] = len(list((data / "normalized_texts").glob("*.txt"))) if (data / "normalized_texts").exists() else 0
    summary["extracted_count"] = len(list((data / "extracted_jsons").glob("*.json"))) if (data / "extracted_jsons").exists() else 0
    summary["chapter_manifest_exists"] = (data / "chapter_manifest.json").exists()
    summary["entity_graph_exists"] = (data / "entity_graph.json").exists()
    summary["personas_applied"] = (manual / "personas.json").exists()
    summary["outline_exists"] = (outputs / "debate" / "outline.md").exists()
    summary["chapter_plan_exists"] = (outputs / "debate" / "chapter_plan.json").exists()
    summary["drafts"] = sorted(p.name for p in drafts.glob("chapter_*.md")) if drafts.exists() else []
    return summary


def _validate_name(name: str) -> None:
    if name in RESERVED_NAMES:
        raise ValueError(f"workspace name is reserved or empty: {name!r}")
    if "/" in name or "\\" in name:
        raise ValueError(f"workspace name must not contain path separators: {name!r}")
    if name.startswith("."):
        raise ValueError(f"workspace name must not start with '.': {name!r}")


def render_list(names: List[str]) -> str:
    if not names:
        return "(no workspaces found; create one with `python3 main.py workspace-init <name>`)\n"
    return "\n".join(names) + "\n"


def render_init(result: Dict[str, Any]) -> str:
    lines = [f"workspace-init {result['name']}: created at {result['path']}", "created:"]
    lines.extend(f"  - {item}" for item in result.get("created", []))
    return "\n".join(lines) + "\n"


def render_import(result: Dict[str, Any]) -> str:
    mode = "dry-run" if result.get("dry_run") else "applied"
    lines = [f"workspace-import-current --to {result['to']}: {mode}"]
    for op in result.get("operations", []):
        lines.append(f"  - [{op['action']}] {op['sub']}: {op['src']} -> {op['dst']}")
    if result.get("dry_run"):
        lines.append("")
        lines.append("Rerun without --dry-run to perform the move.")
    return "\n".join(lines) + "\n"


def render_show(summary: Dict[str, Any]) -> str:
    lines = [f"workspace: {summary['name']}", f"root: {summary['root']}", f"exists: {summary['exists']}"]
    if not summary.get("exists"):
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"raw_txt_count: {summary.get('raw_txt_count', 0)}",
            f"normalized_count: {summary.get('normalized_count', 0)}",
            f"extracted_count: {summary.get('extracted_count', 0)}",
            f"chapter_manifest: {summary.get('chapter_manifest_exists', False)}",
            f"entity_graph: {summary.get('entity_graph_exists', False)}",
            f"personas_applied: {summary.get('personas_applied', False)}",
            f"outline: {summary.get('outline_exists', False)}",
            f"chapter_plan: {summary.get('chapter_plan_exists', False)}",
            f"drafts: {', '.join(summary.get('drafts', [])) or '(none)'}",
        ]
    )
    return "\n".join(lines) + "\n"
