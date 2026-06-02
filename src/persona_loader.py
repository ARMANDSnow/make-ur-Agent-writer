"""Persona binding loader for iter 016.

Iter 015 made `manual_overrides` bootstrap-able. Iter 016 adds one more file:
``data/manual_overrides/personas.json`` which binds variables that fill the
``*_template`` fields in ``config/agents.yaml``.

Behavior contract:

* ``load_personas()`` returns ``None`` when ``personas.json`` is missing or
  unreadable. Callers MUST fall back to the legacy ``name`` /
  ``system_prompt`` fields in ``agents.yaml`` in that case, preserving the
  original validation-corpus workflow.
* ``render_agent_fields(agent, personas)`` returns ``(name, system_prompt)``
  and the optional ``stance`` for debate. When ``personas`` is ``None`` it
  returns the legacy fields verbatim. When ``personas`` is present it renders
  ``*_template`` fields via :func:`render_template` and **only on render
  failure** falls back to legacy. The fallback is logged so missing template
  variables surface during integration.

The template engine intentionally uses Python ``str.format_map`` with a
default-empty mapping — no jinja2 dependency, easy to reason about, and
``{undefined_var}`` collapses to ``""`` rather than raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import paths
from .config import ROOT
from .state import log_event
from .utils import read_json_optional


# Legacy constant — kept for iter 014-016 test backward compat
# (``patch("src.persona_loader.PERSONAS_PATH", ...)`` still works).
PERSONAS_PATH = ROOT / "data" / "manual_overrides" / "personas.json"


def _personas_path() -> Path:
    return paths.personas_path() if paths.workspace_name() else PERSONAS_PATH

PERSONAS_FIELDS = (
    "protagonist_name",
    "protagonist_role",
    "author_name",
    "style_short_descriptor",
    "world_setting_brief",
    "core_relationships",
    "core_setting_rules",
)


class _SafeDefaultDict(dict):
    """Mapping used with str.format_map that returns '' for missing keys."""

    def __missing__(self, key: str) -> str:  # noqa: D401  (dict protocol)
        return ""


def load_personas(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the applied personas dict, or ``None`` when not available.

    A persona is considered "available" only when the file exists, parses as
    a dict, and has a non-empty ``protagonist_name``. An empty protagonist is
    treated as not-yet-applied so that prompt rendering does not produce
    obviously broken templates like ``"本位"`` with no name.

    When ``path`` is None the loader resolves the active workspace via
    ``paths.personas_path()`` (or the legacy ``PERSONAS_PATH`` when no
    workspace is active).
    """

    if path is None:
        path = _personas_path()
    data = read_json_optional(path, None)
    if not isinstance(data, dict):
        return None
    if not str(data.get("protagonist_name") or "").strip():
        return None
    return data


def _personas_context(personas: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten list fields into newline-joined text for template injection."""

    ctx: Dict[str, Any] = {}
    for field in PERSONAS_FIELDS:
        value = personas.get(field, "")
        if field in ("core_relationships", "core_setting_rules"):
            items = [str(item).strip() for item in (value or []) if str(item).strip()]
            ctx[field] = items
            ctx[f"{field}_text"] = "\n".join(f"- {item}" for item in items) if items else "（未配置）"
        else:
            ctx[field] = str(value or "").strip()
    return ctx


def render_template(template: str, personas: Dict[str, Any]) -> str:
    """Render ``{field}`` placeholders using personas; missing fields → ``""``."""

    ctx = _personas_context(personas)
    return template.format_map(_SafeDefaultDict(ctx))


def render_agent_fields(
    agent: Dict[str, Any],
    personas: Optional[Dict[str, Any]],
    *,
    log_context: str = "",
) -> Tuple[str, str, str]:
    """Return ``(name, system_prompt, stance)`` honoring persona binding.

    Behavior:

    * ``personas is None`` → return legacy ``name`` / ``system_prompt`` / ``stance``
      verbatim. No log event.
    * ``personas`` provided → render ``*_template`` variants. If a template
      field is missing on the agent, fall back to the legacy field for that
      slot. Render exceptions are caught and logged via ``state.log_event``
      so integration surfaces broken templates.
    """

    legacy_name = str(agent.get("name") or "").strip()
    legacy_prompt = str(agent.get("system_prompt") or "").strip()
    legacy_stance = str(agent.get("stance") or "").strip()

    if personas is None:
        return legacy_name, legacy_prompt, legacy_stance

    name_tpl = agent.get("name_template")
    prompt_tpl = agent.get("system_prompt_template")
    stance_tpl = agent.get("stance_template")

    name = legacy_name
    if isinstance(name_tpl, str) and name_tpl.strip():
        try:
            name = render_template(name_tpl, personas).strip() or legacy_name
        except Exception as exc:  # pragma: no cover - defensive
            log_event("persona", "render_failure", field="name", agent=legacy_name, error=str(exc), context=log_context)

    prompt = legacy_prompt
    if isinstance(prompt_tpl, str) and prompt_tpl.strip():
        try:
            prompt = render_template(prompt_tpl, personas).strip() or legacy_prompt
        except Exception as exc:  # pragma: no cover - defensive
            log_event("persona", "render_failure", field="system_prompt", agent=legacy_name, error=str(exc), context=log_context)

    stance = legacy_stance
    if isinstance(stance_tpl, str) and stance_tpl.strip():
        try:
            stance = render_template(stance_tpl, personas).strip() or legacy_stance
        except Exception as exc:  # pragma: no cover - defensive
            log_event("persona", "render_failure", field="stance", agent=legacy_name, error=str(exc), context=log_context)

    return name, prompt, stance
