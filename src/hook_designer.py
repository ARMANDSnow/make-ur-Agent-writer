"""iter 037: drama station 2, hook design.

The station consumes the station 1 setup file and returns three mock hook
candidates. Real-model wiring arrives in iter 040+.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .drama_schemas import DramaHookCandidates, episode_paths, normalize_episode_no
from .drama_planner import (
    _load_fixture,
    _load_wizard_input,
    build_system_prompt as _build_base_system_prompt,
    _log_prompt,
)
from .llm_client import LLMClient
from .schemas import model_to_dict


MAX_USED_HOOKS_IN_PROMPT = 20
MAX_USED_HOOK_CONTENT_CHARS = 240


def run(workspace: str, *, mock: bool | None = None, episode_no: int = 1) -> Dict[str, Any]:
    """Run station 2 for ``workspace`` and return hook candidates."""

    episode_no = normalize_episode_no(episode_no)
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
    client = None if mock is True else LLMClient("drama_hooks")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    if use_mock:
        result = _load_fixture(track, "hooks_ep2" if episode_no > 1 else "hooks")
        if episode_no > 2:
            result = _derive_mock_hooks_for_episode(result, episode_no=episode_no)
    else:
        if client is None:
            client = LLMClient("drama_hooks")
        generated = client.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请输出恰好 3 个站②钩子候选 JSON。不要输出 Markdown，不要解释。"},
            ],
            DramaHookCandidates,
        )
        result = model_to_dict(generated)
    hooks = result.get("hooks")
    if not isinstance(hooks, list):
        raise ValueError("hook fixture must contain a hooks list")
    used_keys = {_hook_key(item) for item in used_hooks}
    fresh = [item for item in hooks if isinstance(item, dict) and _hook_key(item) not in used_keys]
    if episode_no > 1 and len(fresh) != 3:
        raise ValueError("later episode hook fixture must provide 3 unused candidates")
    return model_to_dict(DramaHookCandidates(hooks=fresh))


def collect_used_hooks(workspace: str, *, before_episode_no: int) -> list[Dict[str, Any]]:
    """Return every valid earlier selected hook for exact local de-duplication.

    Prompt construction applies its own 20-row bound. Keeping the full list
    here prevents episode 22+ from reusing a hook merely because it fell out of
    the model context window.
    """

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
        # Keep the full local value for exact de-duplication. Prompt shaping is
        # the only place where hook content is truncated.
        content = str(raw_content or "")
        if hook_type or content:
            hooks.append({"episode_no": number, "type": hook_type, "content": content})
    return hooks


def _derive_mock_hooks_for_episode(result: Dict[str, Any], *, episode_no: int) -> Dict[str, Any]:
    """Derive deterministic ep3+ mock candidates from the ep2 fixture."""

    hooks = result.get("hooks")
    if not isinstance(hooks, list):
        return result
    suffix = f"（第 {episode_no} 集候选）"
    derived: list[Dict[str, Any]] = []
    for raw in hooks:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "")
        derived.append(
            {
                **raw,
                "content": content[: max(0, 600 - len(suffix))] + suffix,
            }
        )
    return {**result, "hooks": derived}


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
