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
from .drama_schemas import (
    CharacterSheet,
    DramaStoryboard,
    canonical_episode_identity,
    character_paths,
    episode_paths,
    normalize_episode_no,
)
from .llm_client import LLMClient
from .schemas import model_to_dict
from .utils import read_json_optional


MAX_AGENT_SUGGESTIONS = 12
MAX_REFERENCE_IMAGES = 8
MAX_CHARACTERS_PER_GENERATION = 8


def run(
    workspace: str,
    *,
    mock: bool | None = None,
    episode_no: int = 1,
    season_no: int = 1,
) -> Dict[str, Any]:
    """Run station 4 for ``workspace`` and return a validated character sheet."""

    episode_no = normalize_episode_no(episode_no)
    wizard_input = _load_wizard_input(workspace)
    setup = _load_completed_setup(workspace, episode_no=episode_no)
    storyboard = _load_completed_storyboard(workspace, episode_no=episode_no)
    existing = read_json_optional(character_paths(workspace).sheet_path, None)
    generation_limit = _character_generation_limit(existing, episode_no=episode_no)
    track, _target_duration = canonical_episode_identity(
        setup, wizard_input, storyboard, expected_episode_no=episode_no
    )
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    client = None if mock is True else LLMClient("drama_character")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    prompt = build_system_prompt(
        workspace,
        wizard_input=wizard_input,
        setup=setup,
        storyboard=storyboard,
        existing_characters=existing if isinstance(existing, dict) else None,
        episode_no=episode_no,
    )
    _log_prompt(workspace, "character_designer", prompt)

    if use_mock:
        payload = _load_fixture(track, "characters")
        if episode_no > 1 and isinstance(existing, dict):
            # The generic fixtures describe the initial protagonist/antagonist.
            # A continuation station explicitly means "introduce a new role",
            # so emit one deterministic proposal and let the collision-safe
            # merge allocate its season id.
            template_rows = payload.get("characters") or []
            if template_rows and isinstance(template_rows[0], dict):
                newcomer = dict(template_rows[0])
                newcomer.update({
                    "id": "c001",
                    "name": f"新增角色{episode_no}",
                    "role": "新角色",
                    "lora_token": f"new_character_{episode_no}",
                    "reference_images": [],
                    "visual_contrast_with": {},
                })
                payload["characters"] = [newcomer]
        payload["track"] = track
        payload["season_no"] = season_no
        payload["episode_no"] = episode_no
        payload["generated_episode_nos"] = [episode_no]
        _include_episode_in_appearances(payload, episode_no)
        payload["source_storyboard_title"] = str(storyboard.get("title") or payload.get("source_storyboard_title") or "")
        sheet = CharacterSheet(**payload)
    else:
        if client is None:
            client = LLMClient("drama_character")
        generated = client.complete_json(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "请输出站④角色设定表 JSON。不要输出 Markdown，不要解释。",
                },
            ],
            CharacterSheet,
        )
        payload = model_to_dict(generated)
        if len(payload.get("characters") or []) > generation_limit:
            raise ValueError(
                f"station 4 may generate at most {generation_limit} characters for this episode"
            )
        payload["episode_no"] = episode_no
        payload["season_no"] = season_no
        payload["generated_episode_nos"] = [episode_no]
        payload["track"] = track
        payload["source_storyboard_title"] = str(storyboard.get("title") or "")
        _include_episode_in_appearances(payload, episode_no)
        sheet = CharacterSheet(**payload)
    return model_to_dict(sheet)


def _include_episode_in_appearances(payload: Dict[str, Any], episode_no: int) -> None:
    episode_no = normalize_episode_no(episode_no)
    rows = payload.get("characters")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("appearances")
        appearances = list(raw) if isinstance(raw, list) else []
        appearances.append(episode_no)
        row["appearances"] = appearances


def merge_character_sheet(existing: Dict[str, Any] | CharacterSheet | None, incoming: Dict[str, Any] | CharacterSheet) -> Dict[str, Any]:
    """Merge newly generated characters into a user-editable character sheet.

    ``manual_override`` is the only persisted lock flag. Locked rows keep their
    current fields, while the fresh agent proposal is appended to
    ``agent_suggestions`` for review.
    """

    incoming_sheet = incoming if isinstance(incoming, CharacterSheet) else CharacterSheet(**incoming)
    if len(incoming_sheet.characters) > MAX_CHARACTERS_PER_GENERATION:
        raise ValueError("station 4 may generate at most 8 characters per invocation")
    if existing is None:
        result = model_to_dict(incoming_sheet)
        result["generated_episode_nos"] = sorted(_generated_episode_markers(incoming_sheet))
        return model_to_dict(CharacterSheet(**result))
    existing_sheet = existing if isinstance(existing, CharacterSheet) else CharacterSheet(**existing)
    revising_episode = incoming_sheet.episode_no in _generated_episode_markers(existing_sheet)
    incoming_sheet = _remap_continuation_id_collisions(
        existing_sheet, incoming_sheet, revising_episode=revising_episode
    )
    continuation = incoming_sheet.episode_no > 1
    existing_active = [
        row for row in existing_sheet.characters
        if incoming_sheet.episode_no in row.appearances
    ]
    carried_ids: set[str] = set()
    if continuation and not revising_episode and not existing_active:
        carry_slots = max(
            0, MAX_CHARACTERS_PER_GENERATION - len(incoming_sheet.characters)
        )
        previous_cast = [
            row for row in existing_sheet.characters
            if incoming_sheet.episode_no - 1 in row.appearances
        ]
        carried_ids = {row.id for row in previous_cast[:carry_slots]}

    incoming_by_id = {character.id: character for character in incoming_sheet.characters}
    merged: List[Dict[str, Any]] = []
    used_ids = set()
    merged_ids = set()
    for old_character in existing_sheet.characters:
        fresh = incoming_by_id.get(old_character.id)
        owned_by_episode = bool(
            old_character.appearances
            and min(old_character.appearances) == incoming_sheet.episode_no
        )
        if fresh is None:
            if (
                revising_episode
                and not old_character.manual_override
                and owned_by_episode
            ):
                # A rerun replaces unlocked roles first introduced by this
                # episode instead of accumulating a new role on every click.
                continue
            data = model_to_dict(old_character)
            if old_character.id in carried_ids:
                data["appearances"] = sorted(
                    set(data.get("appearances") or []) | {incoming_sheet.episode_no}
                )
            merged.append(data)
            merged_ids.add(data["id"])
            continue
        used_ids.add(old_character.id)
        if old_character.manual_override or (
            continuation and not (revising_episode and owned_by_episode)
        ):
            data = model_to_dict(old_character)
            appearances = list(data.get("appearances") or [])
            for number in fresh.appearances:
                if number not in appearances:
                    appearances.append(number)
            data["appearances"] = appearances
            if model_to_dict(fresh) != model_to_dict(old_character):
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
            data["appearances"] = sorted(
                set(old_character.appearances) | set(fresh.appearances)
            )
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
    existing_generated = _generated_episode_markers(existing_sheet)
    incoming_generated = _generated_episode_markers(incoming_sheet)
    result["generated_episode_nos"] = sorted(existing_generated | incoming_generated)
    validated = model_to_dict(CharacterSheet(**result))
    active_ids = {
        str(row.get("id") or "")
        for row in validated.get("characters", [])
        if incoming_sheet.episode_no in (row.get("appearances") or [])
    }
    if len(active_ids) > MAX_CHARACTERS_PER_GENERATION:
        raise ValueError("an episode may include at most 8 characters")
    return validated


def _remap_continuation_id_collisions(
    existing: CharacterSheet,
    incoming: CharacterSheet,
    *,
    revising_episode: bool = False,
) -> CharacterSheet:
    """Allocate fresh ids when a continuation model restarts at ``c001``.

    Same-name collisions are proposals about an existing identity and are
    preserved for the merge lock logic.  Different-name collisions are new
    identities and must never inherit an old character's reference images.
    """

    if incoming.episode_no <= 1:
        return incoming
    old_by_id = {character.id: character for character in existing.characters}
    occupied = set(old_by_id)
    assigned: set[str] = set()
    mapping: Dict[str, str] = {}
    payload = model_to_dict(incoming)

    def allocate() -> str:
        for number in range(1, 1000):
            candidate = f"c{number:03d}"
            if candidate not in occupied and candidate not in assigned:
                return candidate
        raise ValueError("character id space is exhausted")

    for row in payload.get("characters", []):
        desired = str(row.get("id") or "")
        old = old_by_id.get(desired)
        same_identity = bool(
            old is not None
            and str(old.name).strip().casefold() == str(row.get("name") or "").strip().casefold()
        )
        if (
            (desired in occupied and not same_identity and not revising_episode)
            or desired in assigned
        ):
            replacement = allocate()
            mapping[desired] = replacement
            row["id"] = replacement
            assigned.add(replacement)
        else:
            assigned.add(desired)
    for row in payload.get("characters", []):
        contrast = row.get("visual_contrast_with")
        if isinstance(contrast, dict) and contrast.get("target_id") in mapping:
            contrast["target_id"] = mapping[str(contrast["target_id"])]
    return CharacterSheet(**payload)


def character_sheet_generated_for_episode(
    sheet: Dict[str, Any] | CharacterSheet,
    *,
    episode_no: int,
) -> bool:
    """Return whether paid/mock station 4 actually ran for this episode."""

    number = normalize_episode_no(episode_no)
    model = sheet if isinstance(sheet, CharacterSheet) else CharacterSheet(**sheet)
    return number in _generated_episode_markers(model)


def _generated_episode_markers(sheet: CharacterSheet) -> set[int]:
    if sheet.generated_episode_nos:
        return set(sheet.generated_episode_nos)
    # Legacy appearances cannot prove station 4 ran: the old skip path added
    # appearances too. Episode 1 was mandatory; later ambiguous episodes must
    # rerun fail-closed before a setup is switched to "introduces new".
    return {1}


def reuse_character_sheet_for_episode(
    existing: Dict[str, Any] | CharacterSheet,
    *,
    episode_no: int,
) -> Dict[str, Any]:
    """Return an episode-scoped view of the existing season character sheet.

    The season file remains the source of truth.  Callers can use this view when
    a later episode introduces no new characters without persisting a top-level
    ``episode_no`` change that would make earlier episode fingerprints stale.
    """

    number = normalize_episode_no(episode_no)
    sheet = existing if isinstance(existing, CharacterSheet) else CharacterSheet(**existing)
    data = model_to_dict(sheet)
    data["generated_episode_nos"] = sorted(_generated_episode_markers(sheet))
    data["episode_no"] = number
    rows = [row for row in data.get("characters", []) if isinstance(row, dict)]
    already_active = [
        row for row in rows
        if number in (row.get("appearances") or [])
    ]
    if already_active:
        cast_ids = {str(row.get("id") or "") for row in already_active[:8]}
    else:
        previous = [
            row for row in rows
            if number > 1 and number - 1 in (row.get("appearances") or [])
        ]
        candidates = previous or rows
        cast_ids = {str(row.get("id") or "") for row in candidates[:8]}
    for row in rows:
        appearances = [item for item in (row.get("appearances") or []) if item != number]
        if str(row.get("id") or "") in cast_ids:
            appearances.append(number)
        row["appearances"] = sorted(set(appearances))
    return model_to_dict(CharacterSheet(**data))


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
    existing_characters: Dict[str, Any] | None = None,
    episode_no: int = 1,
) -> str:
    episode_no = normalize_episode_no(episode_no)
    data = dict(wizard_input if wizard_input is not None else _load_wizard_input(workspace))
    setup_data = setup if setup is not None else _load_completed_setup(workspace, episode_no=episode_no)
    storyboard_data = (
        storyboard if storyboard is not None else _load_completed_storyboard(workspace, episode_no=episode_no)
    )
    existing_data = (
        existing_characters
        if existing_characters is not None
        else read_json_optional(character_paths(workspace).sheet_path, None)
    )
    existing_projection = _character_prompt_projection(existing_data, episode_no=episode_no)
    revising_episode = False
    if isinstance(existing_data, dict):
        try:
            revising_episode = character_sheet_generated_for_episode(
                existing_data, episode_no=episode_no
            )
        except (TypeError, ValueError):
            revising_episode = False
    generation_limit = _character_generation_limit(
        existing_data, episode_no=episode_no
    )
    track, duration = canonical_episode_identity(
        setup_data, data, storyboard_data, expected_episode_no=episode_no
    )
    data["track"] = track
    data["episode_duration_seconds"] = duration
    template = _load_prompt_template("character_designer")
    snapshot = _load_snapshot(workspace)
    return template.format(
        snapshot=snapshot,
        topic=data.get("topic", ""),
        track=data.get("track", ""),
        episode_count=data.get("episode_count", 0),
        episode_duration_seconds=data.get("episode_duration_seconds", 0),
        episode_no=episode_no,
        generation_mode="revision" if revising_episode else "new_roles",
        generation_limit=generation_limit,
        generation_instruction=(
            "返修本集已生成角色；优先复用下方 revision_candidates 的 ID，输出替代后的本集角色集合，"
            "不要无故增加人物。"
            if revising_episode
            else "只输出本集真正新增的角色，并避开已有角色 ID。"
        ),
        setup_json=json.dumps(setup_data, ensure_ascii=False, indent=2),
        storyboard_json=json.dumps(_storyboard_prompt_view(storyboard_data), ensure_ascii=False, indent=2),
        existing_characters_json=json.dumps(
            existing_projection,
            ensure_ascii=False,
            indent=2,
        ),
    )


def _character_generation_limit(existing: Any, *, episode_no: int) -> int:
    """Return the provider output limit after accounting for the active cast."""

    number = normalize_episode_no(episode_no)
    if not isinstance(existing, dict):
        return MAX_CHARACTERS_PER_GENERATION
    try:
        sheet = CharacterSheet(**existing)
    except (TypeError, ValueError):
        # Invalid persisted state must fail before provider construction/prompt.
        raise ValueError("existing character sheet is invalid")
    if number in _generated_episode_markers(sheet):
        candidates = [
            row for row in sheet.characters
            if row.appearances and min(row.appearances) == number
        ]
        return max(1, min(MAX_CHARACTERS_PER_GENERATION, len(candidates)))
    current = [row for row in sheet.characters if number in row.appearances]
    remaining = MAX_CHARACTERS_PER_GENERATION - len(current)
    if remaining <= 0:
        raise ValueError("episode cast already uses all 8 character slots")
    return remaining


def _character_prompt_projection(existing: Any, *, episode_no: int) -> Dict[str, Any]:
    """Bounded provider view without references, prompts or review internals."""

    if not isinstance(existing, dict):
        return {"characters": [], "revision_candidates": []}
    number = normalize_episode_no(episode_no)
    rows: List[Dict[str, Any]] = []
    revisions: List[str] = []
    for raw in (existing.get("characters") or [])[:999]:
        if not isinstance(raw, dict):
            continue
        appearances = [
            item for item in (raw.get("appearances") or [])
            if isinstance(item, int) and not isinstance(item, bool)
        ][:100]
        row = {
            "id": str(raw.get("id") or "")[:16],
            "name": str(raw.get("name") or "")[:80],
            "role": str(raw.get("role") or "")[:80],
            "appearances": appearances,
        }
        rows.append(row)
        if appearances and min(appearances) == number:
            revisions.append(row["id"])
    raw_season = existing.get("season_no", 1)
    season_no = raw_season if isinstance(raw_season, int) and not isinstance(raw_season, bool) and raw_season > 0 else 1
    return {
        "season_no": season_no,
        "characters": rows,
        "revision_candidates": revisions[:8],
    }


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
    board = DramaStoryboard(**storyboard)
    if board.episode_no != episode_no:
        raise ValueError("station 3 storyboard episode does not match requested episode")
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
