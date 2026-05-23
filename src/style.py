from __future__ import annotations

from pathlib import Path

from . import paths
from .config import ROOT


def load_style_examples(root: Path | None = None) -> str:
    if root is None:
        examples_dir = paths.style_examples_dir() if paths.workspace_name() else (ROOT / "data" / "style_examples")
    else:
        examples_dir = root / "data" / "style_examples"
    if not examples_dir.exists():
        return ""
    parts = []
    for path in sorted(examples_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"### {path.stem}\n\n{text}")
    return "\n\n---\n\n".join(parts)
