"""Defaults for the host-agnostic operations (iter 049)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NovelOpsConfig:
    """Operation-level defaults, distinct from transport config (which lives
    on :class:`~integrations.novel_client.NovelClient`).

    ``require_start_point`` defaults to ``False`` to match the greenfield
    workbench (src/web/static.py): a premise-seeded book has no prior
    published start point, so the plan-chapters / write-book start-point gate
    must be relaxed or those steps hard-block on ``start_point_missing``.
    """

    default_book: Optional[str] = None
    write_tier: str = "mid"
    write_budget_cny: float = 5.0
    outline_chapters: int = 3
    write_chapters: int = 1
    require_start_point: bool = False
