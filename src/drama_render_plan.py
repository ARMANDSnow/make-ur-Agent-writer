"""Deterministic creative-to-render projection for approved drama episodes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable

from .drama_schemas import (
    ArtDirectionResolution,
    ArtDirectionRef,
    CameraMovement,
    DialogueSegment,
    NarrationSegment,
    RenderPlan,
    RenderShot,
    ShotSize,
)
from .drama_store import FreshEpisodeSnapshot, _fresh_snapshot_fingerprint
from .schemas import model_to_dict


RENDER_PLAN_GENERATOR_VERSION = "render-plan-v1"
CREATIVE_FINGERPRINT_VERSION = 1

_SHOT_SIZES = frozenset({"特写", "近景", "中景", "全景", "远景"})
_CAMERA_MOVEMENTS = frozenset({"固定", "推", "拉", "摇", "移", "跟", "升降"})
_SOURCE_SHOT_KEYS = frozenset(
    {
        "shot_no",
        "beat",
        "shot_size",
        "camera_move",
        "duration_seconds",
        "visual_content",
        "voiceover",
        "dialogue",
        "ai_draw_prompt",
        "motion_prompt",
        "camera_movement_for_video",
        "is_highlight",
    }
)


def _strict_sha256(data: Any) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strict_int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"render source {field} must be a strict integer")
    if value < minimum or value > maximum:
        raise ValueError(f"render source {field} is out of range")
    return value


def _strict_string(
    value: Any,
    field: str,
    *,
    maximum: int,
    required: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"render source {field} must be a string")
    if required and not value:
        raise ValueError(f"render source {field} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"render source {field} is too long")
    return value


def _optional_string(value: Any, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _strict_string(value, field, maximum=maximum)


def _normalize_source_shot(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("render source storyboard rows must be objects")
    extra = set(raw) - _SOURCE_SHOT_KEYS
    if extra:
        raise ValueError("render source storyboard contains unsupported fields")

    shot_size = raw.get("shot_size")
    if not isinstance(shot_size, str) or shot_size not in _SHOT_SIZES:
        raise ValueError("render source shot_size is invalid")
    camera_movement = raw.get("camera_move")
    if not isinstance(camera_movement, str) or camera_movement not in _CAMERA_MOVEMENTS:
        raise ValueError("render source camera_move is invalid")
    highlight = raw.get("is_highlight", False)
    if not isinstance(highlight, bool):
        raise ValueError("render source is_highlight must be bool")

    return {
        "shot_no": _strict_int(raw.get("shot_no"), "shot_no", minimum=1, maximum=100),
        "beat": _strict_string(raw.get("beat", ""), "beat", maximum=80),
        "shot_size": shot_size,
        "camera_move": camera_movement,
        "duration_seconds": _strict_int(
            raw.get("duration_seconds"),
            "duration_seconds",
            minimum=1,
            maximum=30,
        ),
        "visual_content": _strict_string(
            raw.get("visual_content"),
            "visual_content",
            maximum=500,
            required=True,
        ),
        "voiceover": _strict_string(raw.get("voiceover", ""), "voiceover", maximum=220),
        "dialogue": _strict_string(raw.get("dialogue", ""), "dialogue", maximum=120),
        "ai_draw_prompt": _strict_string(
            raw.get("ai_draw_prompt", ""),
            "ai_draw_prompt",
            maximum=800,
        ),
        "motion_prompt": _optional_string(
            raw.get("motion_prompt"),
            "motion_prompt",
            maximum=800,
        ),
        "camera_movement_for_video": _optional_string(
            raw.get("camera_movement_for_video"),
            "camera_movement_for_video",
            maximum=120,
        ),
        "is_highlight": highlight,
    }


def _shot_identity_projection(source: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "beat": source["beat"],
        "visual_content": source["visual_content"],
        "voiceover": source["voiceover"],
        "dialogue": source["dialogue"],
    }


def _shot_source_projection(source: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in source.items() if key != "shot_no"}


def _segment_id(*, episode_no: int, shot_id: str, kind: str, text: str) -> str:
    digest = _strict_sha256(
        {
            "version": 1,
            "episode_no": episode_no,
            "shot_id": shot_id,
            "kind": kind,
            "text": text,
        }
    )
    return f"segment_{digest[:24]}"


def _audio_policy(kinds: Iterable[str]) -> str:
    values = frozenset(kinds)
    if not values:
        return "silent"
    if values == {"narration"}:
        return "narration_only"
    if values == {"dialogue"}:
        return "dialogue_only"
    if values == {"narration", "dialogue"}:
        return "mixed"
    raise ValueError("unsupported spoken segment combination")


def _validate_snapshot(snapshot: FreshEpisodeSnapshot) -> None:
    episode = snapshot.episode
    meta = snapshot.meta
    if _strict_sha256(episode) != snapshot.source_episode_sha256:
        raise ValueError("render snapshot episode content does not match its lineage")
    if _strict_sha256(snapshot.character_projection) != snapshot.character_projection_fingerprint:
        raise ValueError("render snapshot character projection does not match its lineage")
    if (
        meta.get("verdict") != "Approve"
        or meta.get("input_fingerprint") != snapshot.creative_revision
        or meta.get("input_fingerprint_version") != snapshot.creative_revision_version
        or meta.get("episode_sha256") != snapshot.source_episode_sha256
        or meta.get("episode_no") != episode.get("episode_no")
        or meta.get("season_no") != episode.get("season_no")
    ):
        raise ValueError("render snapshot approval lineage is inconsistent")
    if snapshot.creative_revision_version == 2 and meta.get(
        "character_fingerprint_ids"
    ) != list(snapshot.frozen_character_ids):
        raise ValueError("render snapshot frozen cast does not match its lineage")
    projection_ids = [
        row.get("id")
        for row in snapshot.character_projection.get("characters", [])
        if isinstance(row, dict)
    ]
    if len(projection_ids) != len(snapshot.frozen_character_ids) or set(
        projection_ids
    ) != set(snapshot.frozen_character_ids):
        raise ValueError("render snapshot frozen cast does not match its projection")
    expected_snapshot_fingerprint = _fresh_snapshot_fingerprint(
        episode=episode,
        meta=meta,
        character_projection=snapshot.character_projection,
        frozen_character_ids=snapshot.frozen_character_ids,
    )
    if expected_snapshot_fingerprint != snapshot.snapshot_fingerprint:
        raise ValueError("render snapshot fingerprint is invalid")


def build_render_plan(
    snapshot: FreshEpisodeSnapshot,
    *,
    art_direction_ref: ArtDirectionRef | Dict[str, Any] | None = None,
    art_direction_resolution: (
        ArtDirectionResolution | Dict[str, Any] | None
    ) = None,
) -> RenderPlan:
    """Build a byte-stable RenderPlan without file or network access."""

    if not isinstance(snapshot, FreshEpisodeSnapshot):
        raise TypeError("snapshot must be a FreshEpisodeSnapshot")
    _validate_snapshot(snapshot)
    episode = snapshot.episode
    storyboard = episode.get("storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        raise ValueError("render source storyboard must be a non-empty list")

    art_ref = None
    resolution = None
    if art_direction_resolution is not None:
        resolution = (
            art_direction_resolution
            if isinstance(art_direction_resolution, ArtDirectionResolution)
            else ArtDirectionResolution(**art_direction_resolution)
        )
        if (
            resolution.season_no != episode["season_no"]
            or resolution.episode_no != episode["episode_no"]
        ):
            raise ValueError("art direction resolution belongs to another episode")
        art_ref = resolution.ref
    if art_direction_ref is not None:
        supplied_ref = (
            art_direction_ref
            if isinstance(art_direction_ref, ArtDirectionRef)
            else ArtDirectionRef(**art_direction_ref)
        )
        if art_ref is not None and supplied_ref != art_ref:
            raise ValueError("art direction ref does not match its resolution")
        art_ref = supplied_ref

    normalized_sources = [_normalize_source_shot(row) for row in storyboard]
    source_numbers = [row["shot_no"] for row in normalized_sources]
    if len(source_numbers) != len(set(source_numbers)):
        raise ValueError("render source shot numbers must be unique")

    identity_sources: Dict[str, set[str]] = {}
    for source in normalized_sources:
        identity_hash = _strict_sha256(_shot_identity_projection(source))
        identity_sources.setdefault(identity_hash, set()).add(
            _strict_sha256(_shot_source_projection(source))
        )
    if any(len(variants) > 1 for variants in identity_sources.values()):
        raise ValueError(
            "duplicate semantic shots with different execution inputs require persistent shot ids"
        )

    occurrence_by_identity: Dict[str, int] = {}
    shot_ids: set[str] = set()
    segment_ids: set[str] = set()
    shots: list[Dict[str, Any]] = []
    spoken_segments: list[Dict[str, Any]] = []
    sequence = 1

    for source in normalized_sources:
        identity_hash = _strict_sha256(_shot_identity_projection(source))
        occurrence = occurrence_by_identity.get(identity_hash, 0) + 1
        occurrence_by_identity[identity_hash] = occurrence
        shot_digest = _strict_sha256(
            {
                "version": 1,
                "episode_no": snapshot.episode["episode_no"],
                "identity_hash": identity_hash,
                "occurrence": occurrence,
            }
        )
        shot_id = f"shot_{shot_digest[:24]}"
        if shot_id in shot_ids:
            raise ValueError("render shot id collision")
        shot_ids.add(shot_id)

        shot_segment_ids: list[str] = []
        shot_kinds: list[str] = []
        for kind, text in (
            ("narration", source["voiceover"]),
            ("dialogue", source["dialogue"]),
        ):
            if not text:
                continue
            sid = _segment_id(
                episode_no=snapshot.episode["episode_no"],
                shot_id=shot_id,
                kind=kind,
                text=text,
            )
            if sid in segment_ids:
                raise ValueError("spoken segment id collision")
            segment_ids.add(sid)
            segment: Dict[str, Any] = {
                "kind": kind,
                "segment_id": sid,
                "sequence": sequence,
                "shot_id": shot_id,
                "text": text,
            }
            if kind == "dialogue":
                segment["speaker_character_id"] = None
            spoken_segments.append(segment)
            shot_segment_ids.append(sid)
            shot_kinds.append(kind)
            sequence += 1

        shots.append(
            {
                "shot_id": shot_id,
                "source_shot_no": source["shot_no"],
                "source_fingerprint": _strict_sha256(_shot_source_projection(source)),
                "beat": source["beat"],
                "shot_size": source["shot_size"],
                "camera_movement": source["camera_move"],
                "target_duration_seconds": source["duration_seconds"],
                "visual_action": source["visual_content"],
                "image_prompt": source["ai_draw_prompt"],
                "transition_hint": "",
                "spoken_segment_ids": shot_segment_ids,
                "audio_policy": _audio_policy(shot_kinds),
                "is_highlight": source["is_highlight"],
                "source_event_ids": [],
            }
        )

    creative_payload = {
        "fingerprint_version": CREATIVE_FINGERPRINT_VERSION,
        "episode": {
            "season_no": episode["season_no"],
            "episode_no": episode["episode_no"],
            "title": episode["title"],
            "logline": episode["logline"],
            "track": episode["track"],
            "target_duration_seconds": episode["target_duration_seconds"],
            "core_setup": episode["core_setup"],
            "narrative": episode["narrative"],
            "storyboard": normalized_sources,
            "ending_hook": episode["ending_hook"],
        },
        "approval_lineage": {
            "creative_revision": snapshot.creative_revision,
            "creative_revision_version": snapshot.creative_revision_version,
            "source_episode_sha256": snapshot.source_episode_sha256,
            "frozen_character_ids": list(snapshot.frozen_character_ids),
        },
        "character_projection_fingerprint": snapshot.character_projection_fingerprint,
    }
    plan_payload: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": RENDER_PLAN_GENERATOR_VERSION,
        "season_no": episode["season_no"],
        "episode_no": episode["episode_no"],
        "title": episode["title"],
        "target_duration_seconds": episode["target_duration_seconds"],
        "creative_revision": snapshot.creative_revision,
        "creative_revision_version": snapshot.creative_revision_version,
        "creative_fingerprint": _strict_sha256(creative_payload),
        "source_episode_sha256": snapshot.source_episode_sha256,
        "frozen_character_ids": list(snapshot.frozen_character_ids),
        "character_projection_fingerprint": snapshot.character_projection_fingerprint,
        "art_direction_ref": model_to_dict(art_ref) if art_ref is not None else None,
        "shots": shots,
        "spoken_segments": spoken_segments,
        "source_event_ids": [],
    }
    if resolution is not None:
        plan_payload["art_direction_resolution"] = model_to_dict(resolution)
    plan_payload["plan_fingerprint"] = _strict_sha256(plan_payload)
    return RenderPlan(**plan_payload)


def spoken_segments_to_legacy(plan: RenderPlan | Dict[str, Any]) -> list[Dict[str, Any]]:
    """Project the ordered union back to the current voiceover/dialogue shape."""

    validated = plan if isinstance(plan, RenderPlan) else RenderPlan(**plan)
    by_id = {segment.segment_id: segment for segment in validated.spoken_segments}
    output: list[Dict[str, Any]] = []
    for shot in validated.shots:
        voiceover = ""
        dialogue = ""
        for segment_id in shot.spoken_segment_ids:
            segment = by_id[segment_id]
            if isinstance(segment, NarrationSegment):
                voiceover = segment.text
            elif isinstance(segment, DialogueSegment):
                dialogue = segment.text
        output.append(
            {
                "shot_id": shot.shot_id,
                "shot_no": shot.source_shot_no,
                "voiceover": voiceover,
                "dialogue": dialogue,
            }
        )
    return output
