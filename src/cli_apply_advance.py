from __future__ import annotations

from typing import Any, Dict

from .entity_advance import apply_advance_proposals


def apply_advance_cli(chapter: int, proposal_idx: str, confirm: bool = False) -> Dict[str, Any]:
    return apply_advance_proposals(chapter_no=chapter, proposal_indexes=proposal_idx, confirm=confirm)


def render_apply_advance_result(result: Dict[str, Any]) -> str:
    mode = "APPLIED" if result.get("confirm") else "DRY-RUN"
    diff = result.get("diff") or "(no changes)"
    return (
        f"Apply advance {mode}: chapter {result.get('chapter_no')} "
        f"indexes={result.get('selected', [])} applied_count={result.get('applied_count', 0)}\n"
        f"{diff}\n"
    )
