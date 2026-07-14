"""Drama episode reviewer.

This is intentionally separate from the novel reviewer: drama review is one
agent with five local sub-scores, not a panel vote with novel-specific lint,
entity, persona, and tier behavior.
"""

from __future__ import annotations

import json
from typing import Any, Dict

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
    DramaReview,
    DramaStoryboard,
    canonical_episode_identity,
    episode_paths,
    normalize_episode_no,
)
from .llm_client import LLMClient
from .schemas import model_to_dict
from .utils import read_json_optional


def run(
    workspace: str,
    *,
    mock: bool | None = None,
    episode_no: int = 1,
    character_ids: list[str] | None = None,
) -> Dict[str, Any]:
    """Run the lightweight drama reviewer and return a validated review."""

    episode_no = normalize_episode_no(episode_no)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    storyboard = _load_completed_storyboard(workspace, episode_no=episode_no)
    characters = _load_completed_characters(workspace)
    wizard_input = _load_wizard_input(workspace)
    track, _target_duration = canonical_episode_identity(
        setup, wizard_input, storyboard, expected_episode_no=episode_no
    )
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    client = None if mock is True else LLMClient("drama_review")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    prompt = build_system_prompt(
        workspace,
        wizard_input=wizard_input,
        setup=setup,
        storyboard=storyboard,
        characters=characters,
        episode_no=episode_no,
        character_ids=character_ids,
    )
    _log_prompt(workspace, "drama_reviewer", prompt)

    if use_mock:
        payload = _load_fixture(track, "review")
        payload["episode_no"] = episode_no
        payload["season_no"] = int(characters.get("season_no") or payload.get("season_no") or 1)
        review = DramaReview(**payload)
    else:
        if client is None:
            client = LLMClient("drama_review")
        try:
            generated = client.complete_json(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": "请输出 drama_reviewer JSON。不要输出 Markdown，不要解释。",
                    },
                ],
                DramaReview,
            )
            payload = model_to_dict(generated)
            payload["episode_no"] = episode_no
            payload["season_no"] = int(characters.get("season_no") or 1)
            payload["agent_name"] = "drama_reviewer"
            score_warnings = (
                (payload.get("sub_scores") or {}).get("score_warnings")
                if isinstance(payload.get("sub_scores"), dict)
                else []
            )
            if any(
                isinstance(item, str) and item.endswith(":missing")
                for item in (score_warnings or [])
            ):
                review = DramaReview(**parse_failed_review(
                    episode_no=episode_no,
                    season_no=int(characters.get("season_no") or 1),
                ))
            else:
                review = DramaReview(**payload)
        except Exception:
            review = DramaReview(**parse_failed_review(
                episode_no=episode_no,
                season_no=int(characters.get("season_no") or 1),
            ))

    # Bind the review to the exact text/character identity it evaluated.  The
    # assembler independently recomputes this value, so stale or hand-mixed
    # station files cannot be blessed by a manual assemble call.
    from .drama_store import review_input_fingerprint

    result = model_to_dict(review)
    result["input_fingerprint"] = review_input_fingerprint(
        setup=setup,
        storyboard=storyboard,
        characters=characters,
        episode_no=episode_no,
        character_ids=character_ids,
    )
    return model_to_dict(DramaReview(**result))


def parse_failed_review(*, episode_no: int = 1, season_no: int = 1) -> Dict[str, Any]:
    episode_no = normalize_episode_no(episode_no)
    review = DramaReview(
        episode_no=episode_no,
        season_no=season_no,
        verdict="Abstain",
        sub_scores={},
        issues=["review_parse_failed"],
        suggestions=[],
        parse_failed=True,
        needs_human_review=True,
    )
    return model_to_dict(review)


def build_system_prompt(
    workspace: str,
    *,
    wizard_input: Dict[str, Any] | None = None,
    setup: Dict[str, Any] | None = None,
    storyboard: Dict[str, Any] | None = None,
    characters: Dict[str, Any] | None = None,
    episode_no: int = 1,
    character_ids: list[str] | None = None,
) -> str:
    episode_no = normalize_episode_no(episode_no)
    data = dict(wizard_input if wizard_input is not None else _load_wizard_input(workspace))
    setup_data = setup if setup is not None else _load_completed_setup(workspace, episode_no=episode_no)
    storyboard_data = (
        storyboard if storyboard is not None else _load_completed_storyboard(workspace, episode_no=episode_no)
    )
    character_data = characters if characters is not None else _load_completed_characters(workspace)
    track, duration = canonical_episode_identity(
        setup_data, data, storyboard_data, expected_episode_no=episode_no
    )
    data["track"] = track
    data["episode_duration_seconds"] = duration
    template = _load_prompt_template("drama_reviewer")
    snapshot = _load_snapshot(workspace)
    from .drama_store import episode_character_projection

    character_projection = episode_character_projection(
        character_data,
        episode_no=episode_no,
        character_ids=character_ids,
    )
    return template.format(
        snapshot=snapshot,
        topic=data.get("topic", ""),
        track=data.get("track", ""),
        episode_count=data.get("episode_count", 0),
        episode_duration_seconds=data.get("episode_duration_seconds", 0),
        episode_no=episode_no,
        setup_json=json.dumps(setup_data, ensure_ascii=False, indent=2),
        storyboard_json=json.dumps(_storyboard_prompt_view(storyboard_data), ensure_ascii=False, indent=2),
        characters_json=json.dumps(
            _characters_prompt_view(character_projection),
            ensure_ascii=False,
            indent=2,
        ),
    )


def _load_completed_setup(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).setup_path
    setup = read_json_optional(p, None)
    if not isinstance(setup, dict):
        raise FileNotFoundError(f"station 2 must complete before drama review; missing {p}")
    core = setup.get("core_setup")
    hook = setup.get("hook")
    if not isinstance(core, dict) or not core.get("protagonist"):
        raise ValueError("station 1 output missing core_setup.protagonist")
    if not isinstance(hook, dict) or not hook.get("type"):
        raise ValueError("station 2 must complete before drama review; missing selected hook")
    return setup


def _load_completed_storyboard(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    p = episode_paths(workspace, episode_no=episode_no).storyboard_path
    storyboard = read_json_optional(p, None)
    if not isinstance(storyboard, dict):
        raise FileNotFoundError(f"station 3 must complete before drama review; missing {p}")
    board = DramaStoryboard(**storyboard)
    if board.episode_no != episode_no:
        raise ValueError("station 3 storyboard episode does not match requested episode")
    return storyboard


def _load_completed_characters(workspace: str) -> Dict[str, Any]:
    from .drama_schemas import character_paths

    p = character_paths(workspace).sheet_path
    sheet = read_json_optional(p, None)
    if not isinstance(sheet, dict):
        raise FileNotFoundError(f"station 4 must complete before drama review; missing {p}")
    CharacterSheet(**sheet)
    return sheet


def _storyboard_prompt_view(storyboard: Dict[str, Any]) -> Dict[str, Any]:
    shots = storyboard.get("shots") if isinstance(storyboard.get("shots"), list) else []
    return {
        "title": storyboard.get("title", ""),
        "target_duration_seconds": storyboard.get("target_duration_seconds"),
        "narrative": str(storyboard.get("narrative") or "")[:1600],
        "shots": [
            {
                "shot_no": raw.get("shot_no"),
                "shot_size": raw.get("shot_size"),
                "camera_movement": raw.get("camera_movement"),
                "duration_seconds": raw.get("duration_seconds"),
                "visual": raw.get("visual"),
                "dialogue": raw.get("dialogue"),
                "ai_draw_prompt": raw.get("ai_draw_prompt"),
                "is_highlight": raw.get("is_highlight"),
            }
            for raw in shots
            if isinstance(raw, dict)
        ],
    }


def _characters_prompt_view(characters: Dict[str, Any]) -> Dict[str, Any]:
    rows = characters.get("characters") if isinstance(characters.get("characters"), list) else []
    return {
        "season_no": characters.get("season_no"),
        "characters": [
            {
                "id": raw.get("id"),
                "name": raw.get("name"),
                "role": raw.get("role"),
                "visual_signature": raw.get("visual_signature"),
                "lora_token": raw.get("lora_token"),
                "appearances": raw.get("appearances"),
            }
            for raw in rows
            if isinstance(raw, dict)
        ],
    }
