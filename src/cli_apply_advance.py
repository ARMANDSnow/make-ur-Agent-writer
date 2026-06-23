from __future__ import annotations

from typing import Any, Dict

from .entity_advance import apply_advance_proposals


def apply_advance_cli(
    chapter: int,
    proposal_idx: str = "",
    confirm: bool = False,
    auto_apply: bool = False,
    min_confidence: float = 0.7,
    allow_empty: bool = False,
) -> Dict[str, Any]:
    """Iter 019: passes ``auto_apply / min_confidence / allow_empty`` through
    to ``apply_advance_proposals``. Legacy callers that pass only the first
    three positional / kwargs args keep working byte-identically.
    """
    return apply_advance_proposals(
        chapter_no=chapter,
        proposal_indexes=proposal_idx,
        confirm=confirm,
        auto_apply=auto_apply,
        min_confidence=min_confidence,
        allow_empty=allow_empty,
    )


def render_apply_advance_result(result: Dict[str, Any]) -> str:
    mode = "APPLIED" if result.get("confirm") else "DRY-RUN"
    skipped = result.get("skipped") or []
    skipped_note = ""
    if skipped:
        pairs = ", ".join(f"{s.get('src_id')} <-> {s.get('dst_id')}" for s in skipped)
        skipped_note = (
            f"WARNING: skipped {len(skipped)} proposal(s) referencing "
            f"unknown relationships: {pairs}\n"
        )
    # iter065 #6c: created edges (allow_creation path) are reported separately
    # from advances so applied_count=0 + a creation no longer reads as a no-op.
    created = result.get("created") or []
    created_note = ""
    if created:
        cpairs = ", ".join(f"{c.get('src_id')} <-> {c.get('dst_id')}" for c in created)
        created_note = f"CREATED {len(created)} new relationship(s): {cpairs}\n"
    if result.get("no_op_reason"):
        return (
            f"Apply advance {mode}: chapter {result.get('chapter_no')} "
            f"no-op ({result['no_op_reason']}) auto_apply={result.get('auto_apply', False)}\n"
            f"{skipped_note}"
            f"{created_note}"
        )
    diff = result.get("diff") or "(no changes)"
    auto_tag = ""
    if result.get("auto_apply"):
        auto_tag = f" auto_apply=True min_confidence={result.get('min_confidence')}"
    created_tag = f" created_count={result.get('created_count')}" if created else ""
    return (
        f"Apply advance {mode}: chapter {result.get('chapter_no')} "
        f"indexes={result.get('selected', [])} applied_count={result.get('applied_count', 0)}{created_tag}{auto_tag}\n"
        f"{skipped_note}"
        f"{created_note}"
        f"{diff}\n"
    )
