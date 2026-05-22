from __future__ import annotations

import difflib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .config import ROOT
from .utils import ensure_dir, read_json, write_json


BOOTSTRAP_NAMES = {"global_facts", "entity_graph", "continuation_anchor", "style_examples"}


def apply_bootstrap(name: str, confirm: bool = False, root: Path = ROOT) -> Dict[str, Any]:
    if name not in BOOTSTRAP_NAMES:
        raise ValueError(f"unknown bootstrap proposal '{name}'")
    proposal_path = root / "data" / "proposals" / f"{name}.proposal.json"
    proposal = read_json(proposal_path, None)
    if not isinstance(proposal, dict):
        raise FileNotFoundError(f"proposal not found: {proposal_path}")

    target_paths = _target_paths(name, root, proposal)
    diff = _render_diff(name, proposal, root)
    result: Dict[str, Any] = {
        "name": name,
        "confirm": confirm,
        "proposal_path": str(proposal_path),
        "target_paths": [str(path) for path in target_paths],
        "diff": diff,
    }
    if not confirm:
        result["status"] = "dry_run"
        return result

    backup_dir = _backup_existing(name, target_paths, root)
    if name == "global_facts":
        ensure_dir((root / "data" / "manual_overrides"))
        write_json(root / "data" / "manual_overrides" / "global_facts.json", {"facts": proposal.get("facts", [])})
    elif name == "entity_graph":
        write_json(
            root / "data" / "entity_graph.json",
            {
                "_meta": proposal.get("_meta", {}),
                "entities": proposal.get("entities", []),
                "relationships": proposal.get("relationships", []),
            },
        )
    elif name == "continuation_anchor":
        _write_anchor(root, proposal)
    elif name == "style_examples":
        _write_style_examples(root, proposal)
    result["status"] = "applied"
    result["backup_dir"] = str(backup_dir) if backup_dir else ""
    return result


def render_apply_bootstrap_result(result: Dict[str, Any]) -> str:
    lines = [
        f"apply-bootstrap {result['name']}: {result['status']}",
        f"proposal: {result['proposal_path']}",
    ]
    if result.get("target_paths"):
        lines.append("targets:")
        lines.extend(f"- {path}" for path in result["target_paths"])
    if result.get("backup_dir"):
        lines.append(f"backup: {result['backup_dir']}")
    lines.extend(["", result.get("diff", "").rstrip()])
    if result["status"] == "dry_run":
        lines.extend(
            [
                "",
                "Edit the proposal if needed, then rerun with --confirm to write the manual override files.",
            ]
        )
    return "\n".join(line for line in lines if line is not None).rstrip() + "\n"


def _target_paths(name: str, root: Path, proposal: Dict[str, Any]) -> List[Path]:
    if name == "global_facts":
        return [root / "data" / "manual_overrides" / "global_facts.json"]
    if name == "entity_graph":
        return [root / "data" / "entity_graph.json"]
    if name == "continuation_anchor":
        return [root / "data" / "manual_overrides" / "continuation_anchor.txt"]
    targets = []
    for item in proposal.get("examples", []) or []:
        targets.append(_safe_target_path(root, str(item.get("target_file") or "")))
    return targets


def _render_diff(name: str, proposal: Dict[str, Any], root: Path) -> str:
    current = _current_payload(name, root)
    proposed = _proposed_payload(name, proposal)
    if name == "global_facts":
        header = f"facts: current={len(current.get('facts', []) or [])}, proposed={len(proposed.get('facts', []) or [])}"
    elif name == "entity_graph":
        header = (
            f"entities: current={len(current.get('entities', []) or [])}, proposed={len(proposed.get('entities', []) or [])}; "
            f"relationships: current={len(current.get('relationships', []) or [])}, proposed={len(proposed.get('relationships', []) or [])}"
        )
    elif name == "continuation_anchor":
        header = f"anchor chars: current={len(current.get('anchor_text', ''))}, proposed={len(proposed.get('anchor_text', ''))}"
    else:
        header = f"style ranges: proposed={len(proposal.get('examples', []) or [])}"
    current_text = _stable_text(current)
    proposed_text = _stable_text(proposed)
    diff = "\n".join(
        difflib.unified_diff(
            current_text.splitlines(),
            proposed_text.splitlines(),
            fromfile=f"current/{name}",
            tofile=f"proposal/{name}",
            lineterm="",
        )
    )
    return f"{header}\n{diff or '(no textual diff)'}\n"


def _current_payload(name: str, root: Path) -> Dict[str, Any]:
    if name == "global_facts":
        data = read_json(root / "data" / "manual_overrides" / "global_facts.json", {})
        return data if isinstance(data, dict) else {"facts": data if isinstance(data, list) else []}
    if name == "entity_graph":
        return read_json(root / "data" / "entity_graph.json", {}) or {}
    if name == "continuation_anchor":
        path = root / "data" / "manual_overrides" / "continuation_anchor.txt"
        return {"anchor_text": path.read_text(encoding="utf-8").strip() if path.exists() else ""}
    return {"examples": []}


def _proposed_payload(name: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
    if name == "global_facts":
        return {"facts": proposal.get("facts", [])}
    if name == "entity_graph":
        return {"entities": proposal.get("entities", []), "relationships": proposal.get("relationships", [])}
    if name == "continuation_anchor":
        return {"anchor_text": proposal.get("anchor_text", ""), "key_state_points": proposal.get("key_state_points", [])}
    return {"examples": proposal.get("examples", [])}


def _stable_text(data: Dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _backup_existing(name: str, target_paths: List[Path], root: Path) -> Path | None:
    existing = [path for path in target_paths if path.exists()]
    if not existing:
        return None
    backup_dir = root / "data" / "proposals" / ".backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    ensure_dir(backup_dir)
    for path in existing:
        rel = path.relative_to(root)
        backup_path = backup_dir / rel
        ensure_dir(backup_path.parent)
        if path.is_dir():
            shutil.copytree(path, backup_path, dirs_exist_ok=True)
        else:
            shutil.copy2(path, backup_path)
    return backup_dir


def _write_anchor(root: Path, proposal: Dict[str, Any]) -> None:
    path = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    ensure_dir(path.parent)
    lines = [str(proposal.get("anchor_text", "")).strip(), ""]
    points = [str(item).strip() for item in proposal.get("key_state_points", []) or [] if str(item).strip()]
    if points:
        lines.append("关键状态点：")
        lines.extend(f"- {item}" for item in points)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _write_style_examples(root: Path, proposal: Dict[str, Any]) -> None:
    for item in proposal.get("examples", []) or []:
        source = _safe_source_path(root, str(item.get("source_file") or ""))
        target = _safe_target_path(root, str(item.get("target_file") or ""))
        start_line = int(item.get("start_line") or 1)
        end_line = int(item.get("end_line") or start_line)
        lines = source.read_text(encoding="utf-8").splitlines()
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), max(start_line, end_line))
        snippet = "\n".join(lines[start_idx:end_idx]).strip()
        rel_source = source.relative_to(root.resolve())
        ensure_dir(target.parent)
        target.write_text(
            f"<!-- source: {rel_source} lines {start_line}-{end_line} -->\n\n{snippet}\n",
            encoding="utf-8",
        )


def _safe_source_path(root: Path, source_file: str) -> Path:
    path = Path(source_file)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed = (root / "data" / "normalized_texts").resolve()
    if allowed not in resolved.parents and resolved != allowed:
        raise ValueError(f"style source must be under data/normalized_texts: {source_file}")
    if not resolved.exists():
        raise FileNotFoundError(f"style source not found: {source_file}")
    return resolved


def _safe_target_path(root: Path, target_file: str) -> Path:
    path = Path(target_file)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    allowed = (root / "data" / "style_examples").resolve()
    if allowed not in resolved.parents:
        raise ValueError(f"style target must be under data/style_examples: {target_file}")
    if resolved.suffix != ".md":
        raise ValueError(f"style target must be a markdown file: {target_file}")
    return resolved
