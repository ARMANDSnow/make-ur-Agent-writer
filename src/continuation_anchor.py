from __future__ import annotations

from pathlib import Path

from . import paths
from .config import ROOT, load_config


# Legacy constant — kept for iter 014-016 test backward compat.
CONTINUATION_ANCHOR_PATH = ROOT / "data" / "manual_overrides" / "continuation_anchor.txt"


def load_continuation_anchor(root: Path | None = None) -> str:
    """Load the gitignored continuation anchor, falling back to legacy config.

    Iter 017: ``root`` defaults to the active workspace root via ``paths``
    when None. Explicitly passing ``root=Path(tmp)`` keeps iter 015/016
    test override behavior.
    """
    if root is None:
        path = paths.continuation_anchor_path() if paths.workspace_name() else CONTINUATION_ANCHOR_PATH
        is_repo_root = not paths.workspace_name()
    else:
        path = root / "data" / "manual_overrides" / "continuation_anchor.txt"
        is_repo_root = root == ROOT
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    if is_repo_root:
        return str(load_config("agents.yaml").get("continuation_anchor", "") or "").strip()
    return ""
