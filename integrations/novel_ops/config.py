"""Defaults for the host-agnostic operations (iter 049)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NovelOpsConfig:
    """Operation-level defaults, distinct from transport config (which lives
    on :class:`~integrations.novel_client.NovelClient`).

    Creation mode and the start-point requirement are not derived from client
    defaults.  They are workspace facts projected by the server's
    workbench/readiness APIs, not caller-selectable preferences.
    """

    default_book: Optional[str] = None
    write_tier: str = "mid"
    write_budget_cny: float = 5.0
    outline_chapters: int = 3
    write_chapters: int = 1
    # Compatibility-only constructor field for existing hosts.  Operations do
    # not consume it: the workspace policy comes from workbench/readiness.
    require_start_point: Optional[bool] = None
