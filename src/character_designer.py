"""Drama station 4: character sheet generation and merge rules."""

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
from .drama_schemas import CharacterSheet, DramaStoryboard, episode_paths
from .llm_client import LLMClient
from .schemas import model_to_dict
from .utils import read_json_optional


MAX_AGENT_SUGGESTIONS = 12
MAX_REFERENCE_IMAGES = 8


def run(
    workspace: str,
    *,
    mock: bool | None = None,
    episode_no: int = 1,
    season_no: int = 1,
) -> Dict[str, Any]:
    """Run station 4 for ``workspace`` and return a validated character sheet."""

    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    storyboard = _load_completed_storyboard(workspace, episode_no=episode_no)
    track = str(wizard_input.get("track") or storyboard.get("track") or setup.get("track") or "")
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    client = None if mock is True else LLMClient("drama_character")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    prompt = build_system_prompt(
        workspace,
        wizard_input=wizard_input,
        setup=setup,
        storyboard=storyboard,
    )
    _log_prompt(workspace, "character_designer", prompt)

    if use_mock:
        payload = _load_fixture(track, "characters")
        payload["track"] = track
        payload["season_no"] = season_no
        payload["episode_no"] = episode_no
        payload["source_storyboard_title"] = str(storyboard.get("title") or payload.get("source_storyboard_title") or "")
        sheet = CharacterSheet(**payload)
    else:
        if client is None:
            client = LLMClient("drama_character")
        sheet = client.complete_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "请输出站④角色设定表 JSON。不要输出 Markdown，不要解释。",
                },
            ],
            CharacterSheet,
        )
    return model_to_dict(sheet)


def merge_character_sheet(existing: Dict[str, Any] | CharacterSheet | None, incoming: Dict[str, Any] | CharacterSheet) -> Dict[str, Any]:
    """Merge newly generated characters into a user-editable character sheet.

    ``manual_override`` is the only persisted lock flag. Locked rows keep their
    current fields, while the fresh agent proposal is appended to
    ``agent_suggestions`` for review.
    """

    incoming_sheet = incoming if isinstance(incoming, CharacterSheet) else CharacterSheet(**incoming)
    if existing is None:
        return model_to_dict(incoming_sheet)
    existing_sheet = existing if isinstance(existing, CharacterSheet) else CharacterSheet(**existing)

    incoming_by_id = {character.id: character for character in incoming_sheet.characters}
    merged: List[Dict[str, Any]] = []
    used_ids = set()
    merged_ids = set()
    for old_character in existing_sheet.characters:
        fresh = incoming_by_id.get(old_character.id)
        if fresh is None:
            data = model_to_dict(old_character)
            merged.append(data)
            merged_ids.add(data["id"])
            continue
        used_ids.add(old_character.id)
        if old_character.manual_override:
            data = model_to_dict(old_character)
            suggestions = list(data.get("agent_suggestions") or [])
            suggestions.append(
                {
                    "source": "character_designer",
                    "character": model_to_dict(fresh),
                }
            )
            data["agent_suggestions"] = suggestions[-MAX_AGENT_SUGGESTIONS:]
            merged.append(data)
        else:
            data = model_to_dict(fresh)
            refs = _merge_reference_images(
                [model_to_dict(ref) for ref in old_character.reference_images],
                list(data.get("reference_images") or []),
            )
            if refs:
                data["reference_images"] = refs
            merged.append(data)
        merged_ids.add(old_character.id)

    for character in incoming_sheet.characters:
        if character.id not in used_ids and character.id not in merged_ids:
            data = model_to_dict(character)
            merged.append(data)
            merged_ids.add(character.id)

    result = model_to_dict(incoming_sheet)
    result["characters"] = merged
    return model_to_dict(CharacterSheet(**result))


def _merge_reference_images(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for ref in [*existing, *incoming]:
        path = ref.get("path") if isinstance(ref, dict) else None
        if not path or path in seen:
            continue
        merged.append(ref)
        seen.add(path)
        if len(merged) >= MAX_REFERENCE_IMAGES:
            break
    return merged


def build_system_prompt(
    workspace: str,
    *,
    wizard_input: Dict[str, Any] | None = None,
    setup: Dict[str, Any] | None = None,
    storyboard: Dict[str, Any] | None = None,
) -> str:
    data = wizard_input if wizard_input is not None else _load_wizard_input(workspace)
    setup_data = setup if setup is not None else _load_completed_setup(workspace)
    storyboard_data = storyboard if storyboard is not None else _load_completed_storyboard(workspace)
    template = _load_prompt_template("character_designer")
    snapshot = _load_snapshot(workspace)
    return template.format(
        snapshot=snapshot,
        topic=data.get("topic", ""),
        track=data.get("track", ""),
        episode_count=data.get("episode_count", 0),
        episode_duration_seconds=data.get("episode_duration_seconds", 0),
        setup_json=json.dumps(setup_data, ensure_ascii=False, indent=2),
        storyboard_json=json.dumps(_storyboard_prompt_view(storyboard_data), ensure_ascii=False, indent=2),
    )


def _load_completed_setup(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).setup_path
    setup = read_json_optional(p, None)
    if not isinstance(setup, dict):
        raise FileNotFoundError(f"station 2 must complete before station 4; missing {p}")
    core = setup.get("core_setup")
    hook = setup.get("hook")
    if not isinstance(core, dict) or not core.get("protagonist"):
        raise ValueError("station 1 output missing core_setup.protagonist")
    if not isinstance(hook, dict) or not hook.get("type"):
        raise ValueError("station 2 must complete before station 4; missing selected hook")
    return setup


def _load_completed_storyboard(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).storyboard_path
    storyboard = read_json_optional(p, None)
    if not isinstance(storyboard, dict):
        raise FileNotFoundError(f"station 3 must complete before station 4; missing {p}")
    DramaStoryboard(**storyboard)
    return storyboard


def _storyboard_prompt_view(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    shots = storyboard.get("shots") if isinstance(storyboard.get("shots"), list) else []
    return {
        "title": storyboard.get("title", ""),
        "narrative": str(storyboard.get("narrative") or "")[:1200],
        "shots": [
            {
                "shot_no": raw.get("shot_no"),
                "beat": raw.get("beat"),
                "visual": raw.get("visual"),
                "dialogue": raw.get("dialogue"),
                "ai_draw_prompt": raw.get("ai_draw_prompt"),
                "is_highlight": raw.get("is_highlight"),
            }
            for raw in shots
            if isinstance(raw, dict)
        ],
    }
