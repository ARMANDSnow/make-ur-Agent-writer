"""Read-only drama workspace progress aggregation."""

from __future__ import annotations

from typing import Any, Dict

from ..drama_schemas import (
    CharacterSheet,
    DramaEpisode,
    DramaEpisodeMeta,
    DramaReview,
    DramaStoryboard,
    character_paths,
    episode_paths,
    normalize_episode_no,
    validate_storyboard_hard,
)
from ..utils import read_json_optional


STATIONS = ("setup", "hook", "storyboard", "characters", "review")


def collect_drama_progress(workspace: str, episode_no: int = 1) -> Dict[str, Any]:
    """Return the five-station drama progress shape for the WebUI."""

    episode_no = normalize_episode_no(episode_no)
    ep = episode_paths(workspace, episode_no=episode_no)
    wizard_input_path = ep.root / "data" / "wizard_input.json"
    setup_path = ep.setup_path
    storyboard_path = ep.storyboard_path
    character_sheet_path = character_paths(workspace).sheet_path

    wizard_input = read_json_optional(wizard_input_path, None)
    setup_data = read_json_optional(setup_path, None)
    storyboard_data = read_json_optional(storyboard_path, None)
    character_data = read_json_optional(character_sheet_path, None)
    review_data = read_json_optional(ep.review_path, None)
    setup_done = bool(
        isinstance(setup_data, dict)
        and isinstance(setup_data.get("core_setup"), dict)
        and setup_data["core_setup"].get("protagonist")
    )
    hook_done = setup_done and bool(
        isinstance(setup_data, dict)
        and isinstance(setup_data.get("hook"), dict)
        and setup_data["hook"].get("type")
    )
    storyboard_done = hook_done and _storyboard_done(storyboard_data, episode_no=episode_no)
    characters_done = _characters_done(character_data)
    introduces_new_characters = bool(
        isinstance(setup_data, dict) and setup_data.get("introduces_new_characters") is True
    )
    if characters_done and storyboard_done and episode_no == 1:
        characters_status = "done"
    elif characters_done and storyboard_done and not introduces_new_characters:
        characters_status = "skipped"
    elif characters_done and storyboard_done:
        characters_status = "done" if character_data.get("episode_no") == episode_no else "todo"
    else:
        characters_status = "todo" if storyboard_done else "locked"
    review_valid = characters_status in {"done", "skipped"} and _review_done(
        review_data, episode_no=episode_no
    )
    assembled = review_valid and _assembled_done(ep, episode_no=episode_no)
    if assembled:
        try:
            from ..drama_store import is_episode_stale

            assembled = not is_episode_stale(workspace, episode_no=episode_no)
        except Exception:
            assembled = False
    review_status = (
        "done"
        if review_valid and assembled
        else ("todo" if characters_status in {"done", "skipped"} else "locked")
    )

    return {
        "workspace": workspace,
        "episode_no": episode_no,
        "wizard_input": wizard_input if isinstance(wizard_input, dict) else None,
        "stations": [
            {
                "id": "setup",
                "label": "核心设定",
                "status": "done" if setup_done else "todo",
                "data": setup_data if setup_done else None,
            },
            {
                "id": "hook",
                "label": "钩子",
                "status": "done" if hook_done else ("todo" if setup_done else "locked"),
                "data": setup_data.get("hook") if isinstance(setup_data, dict) and hook_done else None,
            },
            {
                "id": "storyboard",
                "label": "分镜",
                "status": "done" if storyboard_done else ("todo" if hook_done else "locked"),
                "data": storyboard_data if storyboard_done else None,
            },
            {
                "id": "characters",
                "label": "角色",
                "status": characters_status,
                "data": character_data if characters_status in {"done", "skipped"} else None,
            },
            {
                "id": "review",
                "label": "评审组装",
                "status": review_status,
                "data": review_data if review_valid else None,
            },
        ],
    }


def _storyboard_done(data: Any, *, episode_no: int) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        board = DramaStoryboard(**data)
    except Exception:
        return False
    return board.episode_no == episode_no and not validate_storyboard_hard(board)


def _characters_done(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        CharacterSheet(**data)
    except Exception:
        return False
    return True


def _review_done(data: Any, *, episode_no: int) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        review = DramaReview(**data)
    except Exception:
        return False
    return review.episode_no == episode_no


def _assembled_done(ep: Any, *, episode_no: int) -> bool:
    episode_data = read_json_optional(ep.episode_path, None)
    meta_data = read_json_optional(ep.meta_path, None)
    if not isinstance(episode_data, dict) or not isinstance(meta_data, dict):
        return False
    try:
        episode = DramaEpisode(**episode_data)
        meta = DramaEpisodeMeta(**meta_data)
    except Exception:
        return False
    return episode.episode_no == episode_no and meta.episode_no == episode_no
