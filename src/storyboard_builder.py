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
    CharacterSheet,
    DramaStoryboard,
    StoryboardShot,
    canonical_episode_identity,
    character_paths,
    episode_paths,
    normalize_storyboard_payload,
    normalize_episode_no,
    validate_storyboard_hard,
    validate_storyboard_soft,
)
from .llm_client import LLMClient
from .schemas import model_to_dict
from .utils import read_json_optional


def run(
    workspace: str,
    *,
    mock: bool | None = None,
    episode_no: int = 1,
    season_no: int = 1,
) -> Dict[str, Any]:
    """Run station 3 for ``workspace`` and return a validated storyboard."""

    episode_no = normalize_episode_no(episode_no)
    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    track, target_duration = canonical_episode_identity(
        setup, wizard_input, expected_episode_no=episode_no
    )
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    client = None if mock is True else LLMClient("drama_storyboard")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    prompt = build_system_prompt(
        workspace,
        wizard_input=wizard_input,
        setup=setup,
        episode_no=episode_no,
    )
    _log_prompt(workspace, "storyboard_builder", prompt)

    if use_mock:
        payload = _load_fixture(track, "storyboard")
        if episode_no > 1:
            payload = _derive_mock_storyboard_for_episode(
                payload,
                setup=setup,
                episode_no=episode_no,
            )
        payload = _without_alt_shots(payload)
        payload["track"] = track
        payload["episode_no"] = episode_no
        payload["season_no"] = season_no
        payload["target_duration_seconds"] = target_duration
        payload = _retime_mock_storyboard(payload, target_duration)
        payload["hook"] = _hook_snapshot(setup)
        board = DramaStoryboard(**normalize_storyboard_payload(payload))
    else:
        if client is None:
            client = LLMClient("drama_storyboard")
        generated = client.complete_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "请输出站③分镜 JSON。不要输出 Markdown，不要解释。",
                },
            ],
            DramaStoryboard,
        )
        payload = model_to_dict(generated)
        payload["episode_no"] = episode_no
        payload["season_no"] = season_no
        payload["track"] = track
        payload["target_duration_seconds"] = target_duration
        board = DramaStoryboard(**normalize_storyboard_payload(payload))

    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    data = model_to_dict(board)
    data["hook"] = _hook_snapshot(setup)
    data["soft_warnings"] = validate_storyboard_soft(board)
    return data


def _retime_mock_storyboard(payload: Dict[str, Any], target_duration: int) -> Dict[str, Any]:
    """Retarget the deterministic fixture without lying about total duration."""

    data = dict(payload)
    shots = [dict(item) for item in data.get("shots", []) if isinstance(item, dict)]
    if len(shots) < 2:
        return data
    first_duration = min(3, max(2, target_duration - (len(shots) - 1)))
    last_duration = min(10, max(8, target_duration - first_duration - (len(shots) - 2)))
    middle_target = target_duration - first_duration - last_duration
    middle = shots[1:-1]
    if middle_target < len(middle):
        raise ValueError("target duration is too short for storyboard fixture")
    weights = [max(1, int(item.get("duration_seconds") or 1)) for item in middle]
    durations = [1 for _item in middle]
    remaining = middle_target - len(middle)
    order = sorted(range(len(middle)), key=lambda index: weights[index], reverse=True)
    cursor = 0
    while remaining:
        index = order[cursor % len(order)]
        cursor += 1
        if durations[index] >= 30:
            if all(value >= 30 for value in durations):
                raise ValueError("target duration exceeds storyboard fixture capacity")
            continue
        durations[index] += 1
        remaining -= 1
    shots[0]["duration_seconds"] = first_duration
    shots[-1]["duration_seconds"] = last_duration
    for item, duration in zip(middle, durations):
        item["duration_seconds"] = duration
    data["shots"] = shots
    data["target_duration_seconds"] = target_duration
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

    episode_no = normalize_episode_no(episode_no)
    if isinstance(shot_no, bool) or int(shot_no) < 1:
        raise ValueError("shot_no must be a positive integer")
    number = int(shot_no)
    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    current = dict(storyboard) if storyboard is not None else _load_storyboard(workspace, episode_no=episode_no)
    current["episode_no"] = episode_no
    current["hook"] = _hook_snapshot(setup)
    board = DramaStoryboard(**normalize_storyboard_payload(current))
    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    if number > len(board.shots):
        raise ValueError(f"shot_no out of range: {number}")

    track, _target_duration = canonical_episode_identity(
        setup, wizard_input, current, expected_episode_no=episode_no
    )
    client = None if mock is True else LLMClient("drama_storyboard")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)

    if use_mock:
        replacement = _mock_replacement_shot(track, number, board.shots[number - 1])
        if episode_no > 1:
            replacement = _localize_mock_shot(
                replacement,
                setup=setup,
                episode_no=episode_no,
                opening=number == 1,
            )
    else:
        if client is None:
            client = LLMClient("drama_storyboard")
        prompt = build_system_prompt(
            workspace,
            wizard_input=wizard_input,
            setup=setup,
            episode_no=episode_no,
        )
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
    episode_no: int = 1,
) -> str:
    episode_no = normalize_episode_no(episode_no)
    data = dict(wizard_input if wizard_input is not None else _load_wizard_input(workspace))
    setup_data = setup if setup is not None else _load_completed_setup(workspace, episode_no=episode_no)
    track, duration = canonical_episode_identity(
        setup_data, data, expected_episode_no=episode_no
    )
    data["track"] = track
    data["episode_duration_seconds"] = duration
    template = _load_prompt_template("storyboard_builder")
    snapshot = _load_snapshot(workspace)
    prompt = template.format(
        snapshot=snapshot,
        topic=data.get("topic", ""),
        track=data.get("track", ""),
        episode_count=data.get("episode_count", 0),
        episode_duration_seconds=data.get("episode_duration_seconds", 0),
        episode_no=episode_no,
        setup_json=json.dumps(setup_data, ensure_ascii=False, indent=2),
    )
    signatures = _season_character_signature_view(workspace) if episode_no > 1 else []
    if not signatures:
        return prompt
    return (
        prompt
        + "\n\n## 本季角色视觉签名（后续集必须保持一致）\n"
        + json.dumps(signatures, ensure_ascii=False, indent=2)
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


def _season_character_signature_view(workspace: str) -> List[Dict[str, str]]:
    data = read_json_optional(character_paths(workspace).sheet_path, None)
    if not isinstance(data, dict):
        return []
    try:
        sheet = CharacterSheet(**data)
    except Exception:
        return []
    return [
        {
            "id": character.id,
            "name": character.name[:80],
            "visual_signature": character.visual_signature[:300],
        }
        for character in sheet.characters[:8]
    ]


def _without_alt_shots(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    data.pop("alt_shots", None)
    return data


def _derive_mock_storyboard_for_episode(
    payload: Dict[str, Any],
    *,
    setup: Dict[str, Any],
    episode_no: int,
) -> Dict[str, Any]:
    """Derive a visibly episode-local mock board for continuation UX tests.

    The canonical fixtures describe episode 1.  Reusing them byte-for-byte for
    later episodes made the Web flow claim that a fresh storyboard had been
    generated while showing the previous episode again.  Keep fixture timing
    and schema coverage, but bind the mock result to the current episode's
    operator-authored mainline and selected hook.
    """

    data = dict(payload)
    tag = f"第 {episode_no} 集"
    base_title = str(payload.get("title") or "续篇")
    data["title"] = f"{base_title} · 续篇 {episode_no}"[:80]
    mainline = str(setup.get("episode_mainline") or "").strip()
    logline = str(setup.get("logline") or "").strip()
    data["narrative"] = (mainline or logline or f"{tag}继续推进上一集冲突。")[:2000]

    source_shots = payload.get("shots")
    if not isinstance(source_shots, list):
        return data
    shots = [dict(item) for item in source_shots if isinstance(item, dict)]
    alternatives = payload.get("alt_shots")
    if isinstance(alternatives, list) and alternatives:
        replacement = alternatives[0]
        if isinstance(replacement, dict):
            raw_no = replacement.get("shot_no")
            if isinstance(raw_no, int) and not isinstance(raw_no, bool) and 1 <= raw_no <= len(shots):
                shots[raw_no - 1] = dict(replacement)

    hook = setup.get("hook") if isinstance(setup.get("hook"), dict) else {}
    hook_content = str(hook.get("content") or "").strip()
    for index, shot in enumerate(shots):
        shot["beat"] = f"{shot.get('beat') or '推进'} · {tag}"[:80]
        if index == 0 and hook_content:
            shot["visual"] = f"{tag}开场：{hook_content}"[:500]
        else:
            visual = str(shot.get("visual") or "")
            shot["visual"] = f"{visual}（{tag}推进）"[:500]
        prompt = str(shot.get("ai_draw_prompt") or "")
        shot["ai_draw_prompt"] = f"{prompt}，{tag}连续剧情"[:800]
    data["shots"] = shots
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


def _localize_mock_shot(
    shot: StoryboardShot,
    *,
    setup: Dict[str, Any],
    episode_no: int,
    opening: bool,
) -> StoryboardShot:
    """Keep a mock single-shot rewrite inside the requested later episode."""

    data = model_to_dict(shot)
    tag = f"第 {episode_no} 集"
    data["beat"] = f"{shot.beat} · {tag}"[:80]
    hook = setup.get("hook") if isinstance(setup.get("hook"), dict) else {}
    hook_content = str(hook.get("content") or "").strip()
    if opening and hook_content:
        data["visual"] = f"{tag}开场：{hook_content}"[:500]
    else:
        data["visual"] = f"{shot.visual}（{tag}重生镜头）"[:500]
    prompt = str(shot.ai_draw_prompt or "")
    data["ai_draw_prompt"] = f"{prompt}，{tag}连续剧情"[:800]
    return StoryboardShot(**data)
