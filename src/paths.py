"""Workspace-aware path resolution for iter 017.

Iter 014-016 left every src/ module with `XXX_DIR = ROOT / "..."` at import
time. That hard-codes the assumption that all books share one set of
directories under the repo root. iter 017 introduces ``workspaces/<book>/``
so multiple books can coexist in the same checkout.

This module is the single source of truth for per-workspace path resolution.

Contract:

* The active workspace is controlled by either ``WORKSPACE_NAME`` or
  ``BOOK`` env var. CLI ``--book <name>`` sets ``WORKSPACE_NAME`` before
  any path helper runs.
* When the env var is unset, empty, or equal to the reserved string
  ``legacy``, helpers fall back to the **repo root** paths the project
  used before iter 017. This preserves every iter 014-016 workflow,
  every existing test, and every existing shell script invocation.
* All helpers are **functions, not module-level constants**, so the env
  var is re-read on every call. A single process can therefore switch
  between workspaces by mutating the env (used in tests).
* Helpers never create directories. Callers do that on first write.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .config import ROOT


WORKSPACE_DIR = ROOT / "workspaces"

_LEGACY_SENTINEL = "legacy"


def _validate_workspace_name(name: str) -> None:
    """Iter 019 audit fix: reject workspace names that would escape
    ``workspaces/`` via path traversal.

    Pre-iter-019, ``WORKSPACE_NAME="../escaped"`` resolved to a path
    outside the workspaces/ tree, e.g. ``workspaces/../escaped``. Single-
    user local-dev usage means the threat actor (someone able to set
    env vars) already has shell access, so the practical impact is low
    — but a fat-fingered env var would silently scatter chapter drafts
    into unintended directories. We reject the obvious traversal
    patterns and accept anything else (Unicode workspace names like
    ``龙族`` stay supported).
    """

    if not name:
        return
    if "/" in name or "\\" in name:
        raise ValueError(
            f"workspace name {name!r} must not contain path separators"
        )
    if name.startswith(".") or ".." in name:
        raise ValueError(
            f"workspace name {name!r} must not start with '.' or contain '..'"
        )


def workspace_name() -> Optional[str]:
    """Return the active workspace name, or ``None`` for legacy mode.

    Reads ``WORKSPACE_NAME`` first, then ``BOOK``. Trims whitespace.
    ``"legacy"`` is reserved: it explicitly resolves to legacy mode the
    same way as an unset variable, so scripts can pass it through as a
    no-op default. Raises ``ValueError`` if the env var contains path
    separators or ``..`` (iter 019 audit fix).
    """

    raw = os.environ.get("WORKSPACE_NAME") or os.environ.get("BOOK") or ""
    name = raw.strip()
    if not name or name == _LEGACY_SENTINEL:
        return None
    _validate_workspace_name(name)
    return name


def workspace_root(name: Optional[str] = None) -> Path:
    """Return the root directory for ``name`` (or the active workspace).

    When the resolved name is empty / ``None`` / ``"legacy"`` this returns
    the repo ``ROOT`` so legacy callers keep working. Raises
    ``ValueError`` if ``name`` contains path separators or ``..`` (iter
    019 audit fix).
    """

    if name is None:
        target = workspace_name()
    else:
        candidate = name.strip()
        target = candidate if candidate and candidate != _LEGACY_SENTINEL else None
        if target:
            _validate_workspace_name(target)
    if not target:
        return ROOT
    return WORKSPACE_DIR / target


# ---- per-workspace directories ----------------------------------------------


def data_dir() -> Path:
    return workspace_root() / "data"


def normalized_dir() -> Path:
    return data_dir() / "normalized_texts"


def extracted_dir() -> Path:
    return data_dir() / "extracted_jsons"


def manual_overrides_dir() -> Path:
    return data_dir() / "manual_overrides"


def proposals_dir() -> Path:
    return data_dir() / "proposals"


def style_examples_dir() -> Path:
    return data_dir() / "style_examples"


def knowledge_base_dir() -> Path:
    return data_dir() / "knowledge_base"


def extraction_failures_dir() -> Path:
    return data_dir() / "extraction_failures"


def rolling_summaries_dir() -> Path:
    return data_dir() / "rolling_summaries"


def raw_txt_dir() -> Path:
    return workspace_root() / "小说txt"


def debate_dir() -> Path:
    return workspace_root() / "outputs" / "debate"


def drafts_dir() -> Path:
    return workspace_root() / "outputs" / "drafts"


def reviews_dir() -> Path:
    return workspace_root() / "outputs" / "reviews"


def logs_dir() -> Path:
    return workspace_root() / "logs"


# ---- per-workspace single files ---------------------------------------------


def entity_graph_path() -> Path:
    return data_dir() / "entity_graph.json"


def chapter_manifest_path() -> Path:
    return data_dir() / "chapter_manifest.json"


def chapter_manifest_md_path() -> Path:
    return data_dir() / "chapter_manifest.md"


def kb_path() -> Path:
    return knowledge_base_dir() / "global_knowledge.md"


def index_path() -> Path:
    return knowledge_base_dir() / "knowledge_index.json"


def global_facts_path() -> Path:
    return manual_overrides_dir() / "global_facts.json"


def continuation_anchor_path() -> Path:
    return manual_overrides_dir() / "continuation_anchor.txt"


def personas_path() -> Path:
    return manual_overrides_dir() / "personas.json"


def chapter_plan_path() -> Path:
    return debate_dir() / "chapter_plan.json"


def outline_path() -> Path:
    return debate_dir() / "outline.md"


def debate_decisions_path() -> Path:
    return debate_dir() / "decisions.json"


def debate_log_path() -> Path:
    return debate_dir() / "debate_log.jsonl"


def rolling_summary_path() -> Path:
    return drafts_dir() / "rolling_chapter_summary.json"


def review_summary_path() -> Path:
    return reviews_dir() / "review_summary.md"


def llm_calls_log_path() -> Path:
    return logs_dir() / "llm_calls.jsonl"


def run_state_log_path() -> Path:
    return logs_dir() / "run_state.jsonl"


# ---- shared (always repo root, regardless of workspace) ---------------------


def config_dir() -> Path:
    """`config/` is shared across workspaces. Never per-book."""
    return ROOT / "config"
