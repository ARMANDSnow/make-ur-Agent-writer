"""iter 037: drama station 2, hook design.

The station consumes the station 1 setup file and returns three mock hook
candidates. Real-model wiring arrives in iter 040+.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .drama_schemas import episode_paths, normalize_episode_no
from .drama_planner import (
    _load_fixture,
    _load_wizard_input,
    build_system_prompt as _build_base_system_prompt,
    _log_prompt,
)


MAX_USED_HOOKS_IN_PROMPT = 20
MAX_USED_HOOK_CONTENT_CHARS = 240


def run(workspace: str, *, mock: bool = True, episode_no: int = 1) -> Dict[str, Any]:
    """Run station 2 for ``workspace`` and return hook candidates."""

    episode_no = normalize_episode_no(episode_no)
    if not mock:
        raise NotImplementedError("iter 040+")

    setup_path = episode_paths(workspace, episode_no=episode_no).setup_path
    if not setup_path.is_file():
        raise FileNotFoundError(f"station 1 must complete before station 2; missing {setup_path}")
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    if not isinstance(setup, dict):
        raise ValueError(f"setup must be a JSON object: {setup_path}")
    core_setup = setup.get("core_setup")
    if not isinstance(core_setup, dict) or "protagonist" not in core_setup:
        raise ValueError(
            f"station 1 output for {workspace!r} missing core_setup.protagonist; "
            "station 2 cannot proceed"
        )

    wizard_input = _load_wizard_input(workspace)
    track = str(setup.get("track") or wizard_input["track"])
    used_hooks = collect_used_hooks(workspace, before_episode_no=episode_no)
    system_prompt = build_system_prompt(workspace, wizard_input=wizard_input, used_hooks=used_hooks)
    _log_prompt(workspace, "hook_designer", system_prompt)
    result = _load_fixture(track, "hooks_ep2" if episode_no > 1 else "hooks")
    hooks = result.get("hooks")
    if not isinstance(hooks, list):
        raise ValueError("hook fixture must contain a hooks list")
    used_keys = {_hook_key(item) for item in used_hooks}
    fresh = [item for item in hooks if isinstance(item, dict) and _hook_key(item) not in used_keys]
    if episode_no > 1 and len(fresh) != 3:
        raise ValueError("later episode hook fixture must provide 3 unused candidates")
    return {**result, "hooks": fresh}


def collect_used_hooks(workspace: str, *, before_episode_no: int) -> list[Dict[str, Any]]:
    """Return a bounded, prompt-safe view of earlier selected hooks."""

    before_episode_no = normalize_episode_no(before_episode_no)
    hooks: list[Dict[str, Any]] = []
    for number in range(1, before_episode_no):
        path = episode_paths(workspace, episode_no=number).setup_path
        try:
            setup = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(setup, dict) or not isinstance(setup.get("hook"), dict):
            continue
        hook = setup["hook"]
        raw_type = hook.get("type")
        raw_content = hook.get("content")
        if isinstance(raw_type, (dict, list)) or isinstance(raw_content, (dict, list)):
            continue
        hook_type = str(raw_type or "")[:80]
        content = str(raw_content or "")[:MAX_USED_HOOK_CONTENT_CHARS]
        if hook_type or content:
            hooks.append({"episode_no": number, "type": hook_type, "content": content})
    return hooks[-MAX_USED_HOOKS_IN_PROMPT:]


def build_system_prompt(
    workspace: str,
    *,
    wizard_input: Dict[str, Any] | None = None,
    used_hooks: list[Dict[str, Any]] | None = None,
) -> str:
    """Build the station-2 prompt with a bounded no-repeat history."""

    data = wizard_input if wizard_input is not None else _load_wizard_input(workspace)
    prompt = _build_base_system_prompt(workspace, "hook_designer", data)
    bounded = _bounded_used_hook_view(used_hooks or [])
    if not bounded:
        return prompt
    return (
        prompt
        + "\n\n## 已使用钩子（本集候选不得重复）\n"
        + json.dumps(bounded, ensure_ascii=False, indent=2)
    )


def _hook_key(hook: Dict[str, Any]) -> tuple[str, str]:
    return str(hook.get("type") or "").strip(), str(hook.get("content") or "").strip()


def _bounded_used_hook_view(hooks: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    bounded: list[Dict[str, Any]] = []
    for hook in hooks[-MAX_USED_HOOKS_IN_PROMPT:]:
        if not isinstance(hook, dict):
            continue
        row: Dict[str, Any] = {
            "type": str(hook.get("type") or "")[:80],
            "content": str(hook.get("content") or "")[:MAX_USED_HOOK_CONTENT_CHARS],
        }
        raw_episode_no = hook.get("episode_no")
        if isinstance(raw_episode_no, int) and not isinstance(raw_episode_no, bool):
            row["episode_no"] = raw_episode_no
        bounded.append(row)
    return bounded
