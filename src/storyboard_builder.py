"""Drama station 3: storyboard generation and single-shot rewrite."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .drama_planner import (
    TRACK_PINYIN,
    _load_fixture,
    _load_prompt_template,
    _load_snapshot,
    _load_wizard_input,
    _log_prompt,
)
from .drama_schemas import (
    DramaStoryboard,
    StoryboardShot,
    episode_paths,
    normalize_storyboard_payload,
    validate_storyboard_hard,
    validate_storyboard_soft,
)
from .llm_client import LLMClient
from .schemas import model_to_dict
from .utils import read_json_optional


def run(workspace: str, *, mock: bool | None = None, episode_no: int = 1) -> Dict[str, Any]:
    """Run station 3 for ``workspace`` and return a validated storyboard."""

    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    track = str(wizard_input.get("track") or setup.get("track") or "")
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    client = None if mock is True else LLMClient("drama_storyboard")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    prompt = build_system_prompt(workspace, wizard_input=wizard_input, setup=setup)
    _log_prompt(workspace, "storyboard_builder", prompt)

    if use_mock:
        payload = _load_fixture(track, "storyboard")
        payload = _without_alt_shots(payload)
        payload["track"] = track
        payload["episode_no"] = episode_no
        payload["target_duration_seconds"] = int(
            wizard_input.get("episode_duration_seconds") or payload.get("target_duration_seconds") or 60
        )
        payload["hook"] = _hook_snapshot(setup)
        board = DramaStoryboard(**normalize_storyboard_payload(payload))
    else:
        if client is None:
            client = LLMClient("drama_storyboard")
        result = client.complete_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "请输出站③分镜 JSON。不要输出 Markdown，不要解释。",
                },
            ],
            DramaStoryboard,
        )
        board = result

    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    data = model_to_dict(board)
    data["hook"] = _hook_snapshot(setup)
    data["soft_warnings"] = validate_storyboard_soft(board)
    return data


def rewrite_shot(
    workspace: str,
    shot_no: int,
    *,
    mock: bool | None = None,
    episode_no: int = 1,
    storyboard: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a storyboard with exactly one shot replaced."""

    if isinstance(shot_no, bool) or int(shot_no) < 1:
        raise ValueError("shot_no must be a positive integer")
    number = int(shot_no)
    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    current = dict(storyboard) if storyboard is not None else _load_storyboard(workspace, episode_no=episode_no)
    current["hook"] = _hook_snapshot(setup)
    board = DramaStoryboard(**normalize_storyboard_payload(current))
    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    if number > len(board.shots):
        raise ValueError(f"shot_no out of range: {number}")

    track = str(wizard_input.get("track") or current.get("track") or setup.get("track") or "")
    client = None if mock is True else LLMClient("drama_storyboard")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)

    if use_mock:
        replacement = _mock_replacement_shot(track, number, board.shots[number - 1])
    else:
        if client is None:
            client = LLMClient("drama_storyboard")
        prompt = build_system_prompt(workspace, wizard_input=wizard_input, setup=setup)
        _log_prompt(workspace, "storyboard_builder.rewrite_shot", prompt)
        result = client.complete_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"请只重写第 {number} 镜，保持 shot_no={number}，"
                        "输出一个 StoryboardShot JSON。不要输出 Markdown。\n\n"
                        f"当前分镜上下文：\n{_rewrite_context_json(board, number)}"
                    ),
                },
            ],
            StoryboardShot,
        )
        replacement = result

    shots = [model_to_dict(shot) for shot in board.shots]
    replacement_data = model_to_dict(replacement)
    replacement_data["shot_no"] = number
    shots[number - 1] = replacement_data
    updated = model_to_dict(board)
    updated["shots"] = shots
    updated["hook"] = _hook_snapshot(setup)
    updated_board = DramaStoryboard(**normalize_storyboard_payload(updated))
    hard_errors = validate_storyboard_hard(updated_board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    data = model_to_dict(updated_board)
    data["soft_warnings"] = validate_storyboard_soft(updated_board)
    return data


def build_system_prompt(
    workspace: str,
    *,
    wizard_input: Dict[str, Any] | None = None,
    setup: Dict[str, Any] | None = None,
) -> str:
    data = wizard_input if wizard_input is not None else _load_wizard_input(workspace)
    setup_data = setup if setup is not None else _load_completed_setup(workspace)
    template = _load_prompt_template("storyboard_builder")
    snapshot = _load_snapshot(workspace)
    return template.format(
        snapshot=snapshot,
        topic=data.get("topic", ""),
        track=data.get("track", ""),
        episode_count=data.get("episode_count", 0),
        episode_duration_seconds=data.get("episode_duration_seconds", 0),
        setup_json=json.dumps(setup_data, ensure_ascii=False, indent=2),
    )


def _load_completed_setup(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).setup_path
    setup = read_json_optional(p, None)
    if not isinstance(setup, dict):
        raise FileNotFoundError(f"station 2 must complete before station 3; missing {p}")
    core = setup.get("core_setup")
    hook = setup.get("hook")
    if not isinstance(core, dict) or not core.get("protagonist"):
        raise ValueError("station 1 output missing core_setup.protagonist")
    if not isinstance(hook, dict) or not hook.get("type"):
        raise ValueError("station 2 must complete before station 3; missing selected hook")
    return setup


def _load_storyboard(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).storyboard_path
    data = read_json_optional(p, None)
    if not isinstance(data, dict):
        raise FileNotFoundError(f"missing storyboard: {p}")
    return data


def _without_alt_shots(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    data.pop("alt_shots", None)
    return data


def _hook_snapshot(setup: Dict[str, Any]) -> Dict[str, str]:
    hook = setup.get("hook") if isinstance(setup.get("hook"), dict) else {}
    snapshot: Dict[str, str] = {}
    for key, limit in (("type", 80), ("content", 500)):
        raw = hook.get(key)
        if raw is None or isinstance(raw, (dict, list)):
            continue
        text = str(raw)
        snapshot[key] = text[:limit]
    return snapshot


def _rewrite_context_json(board: DramaStoryboard, shot_no: int) -> str:
    shots = board.shots
    start = max(0, shot_no - 2)
    end = min(len(shots), shot_no + 1)
    context = {
        "title": board.title,
        "target_duration_seconds": board.target_duration_seconds,
        "narrative": board.narrative[:800],
        "target_shot": model_to_dict(shots[shot_no - 1]),
        "neighboring_shots": [model_to_dict(shot) for shot in shots[start:end]],
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


def _mock_replacement_shot(track: str, shot_no: int, current: StoryboardShot) -> StoryboardShot:
    fixture = _load_fixture(track, "storyboard")
    alt_shots: List[Any] = fixture.get("alt_shots") if isinstance(fixture.get("alt_shots"), list) else []
    for raw in alt_shots:
        if isinstance(raw, dict) and raw.get("shot_no") == shot_no:
            data = dict(raw)
            data.setdefault("is_highlight", current.is_highlight)
            return StoryboardShot(**data)
    data = model_to_dict(current)
    data["visual"] = f"{current.visual}（重生版）"
    if current.ai_draw_prompt:
        data["ai_draw_prompt"] = f"{current.ai_draw_prompt}，替代构图"
    return StoryboardShot(**data)
