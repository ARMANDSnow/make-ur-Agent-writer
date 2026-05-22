from __future__ import annotations

from pathlib import Path

from .config import ROOT, load_config


CONTINUATION_ANCHOR_PATH = ROOT / "data" / "manual_overrides" / "continuation_anchor.txt"


def load_continuation_anchor(root: Path = ROOT) -> str:
    """Load the gitignored continuation anchor, falling back to legacy config."""
    path = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    if root == ROOT:
        return str(load_config("agents.yaml").get("continuation_anchor", "") or "").strip()
    return ""
