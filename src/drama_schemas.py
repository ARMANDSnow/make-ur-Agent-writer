from __future__ import annotations

import json
import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import paths


ShotSize = Literal["特写", "近景", "中景", "全景", "远景"]
CameraMovement = Literal["固定", "推", "拉", "摇", "移", "跟", "升降"]


MAX_DRAMA_EPISODE_NO = 100


def normalize_episode_no(value: Any) -> int:
    """Return a fail-closed drama episode number.

    API query parameters arrive as strings, while internal callers normally use
    integers.  Accept those two exact shapes only: bools, floats (including
    integral-looking values), whitespace/sign-prefixed strings, and out-of-range
    values are rejected rather than coerced.
    """

    if isinstance(value, bool):
        raise ValueError(f"episode_no must be an integer between 1 and {MAX_DRAMA_EPISODE_NO}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        digits = value.lstrip("0") or "0"
        if len(digits) > len(str(MAX_DRAMA_EPISODE_NO)):
            raise ValueError(f"episode_no must be an integer between 1 and {MAX_DRAMA_EPISODE_NO}")
        number = int(digits)
    else:
        raise ValueError(f"episode_no must be an integer between 1 and {MAX_DRAMA_EPISODE_NO}")
    if number < 1 or number > MAX_DRAMA_EPISODE_NO:
        raise ValueError(f"episode_no must be an integer between 1 and {MAX_DRAMA_EPISODE_NO}")
    return number


def _strict_schema_episode_no(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("episode_no must be a strict integer")
    return normalize_episode_no(value)


@dataclass(frozen=True)
class DramaEpisodePaths:
    workspace: str
    episode_no: int
    root: Path
    outputs_dir: Path
    episodes_dir: Path
    setup_path: Path
    hook_candidates_path: Path
    storyboard_path: Path
    review_path: Path
    episode_path: Path
    meta_path: Path


@dataclass(frozen=True)
class DramaCharacterPaths:
    workspace: str
    season_no: int
    root: Path
    data_dir: Path
    characters_dir: Path
    refs_dir: Path
    sheet_path: Path


class DramaCoreSetup(BaseModel):
    protagonist: str = Field(min_length=1, max_length=800)
    antagonist: str = Field(default="", max_length=800)
    emotional_hook: str = Field(default="", max_length=800)


class DramaSetup(BaseModel):
    episode_no: int = Field(default=1, ge=1, le=MAX_DRAMA_EPISODE_NO)
    season_no: int = Field(default=1, ge=1)
    title: str = Field(default="", max_length=120)
    logline: str = Field(min_length=1, max_length=1200)
    track: str = Field(min_length=1, max_length=20)
    target_duration_seconds: int = Field(default=60, ge=10, le=600)
    core_setup: DramaCoreSetup

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)


def canonical_episode_identity(
    setup: Dict[str, Any],
    wizard_input: Dict[str, Any],
    storyboard: Dict[str, Any] | None = None,
    *,
    expected_episode_no: int | None = None,
) -> tuple[str, int]:
    """Bind downstream stations to the completed episode setup.

    Wizard input remains useful topic context, but it may be edited after a
    paid station-1 result exists.  Such drift must stop before another model
    call instead of silently creating a mixed-identity episode.
    """
    setup_track = str(setup.get("track") or "").strip()
    setup_duration = setup.get("target_duration_seconds")
    setup_episode_no = setup.get("episode_no")
    if expected_episode_no is not None and setup_episode_no != expected_episode_no:
        raise ValueError("completed episode setup belongs to a different episode")
    if not setup_track or len(setup_track) > 20:
        raise ValueError("completed episode setup has an invalid track")
    if (
        isinstance(setup_duration, bool)
        or not isinstance(setup_duration, int)
        or not 10 <= setup_duration <= 600
    ):
        raise ValueError("completed episode setup has an invalid target duration")
    wizard_track = str(wizard_input.get("track") or "").strip()
    wizard_duration = wizard_input.get("episode_duration_seconds")
    if wizard_track and wizard_track != setup_track:
        raise ValueError("wizard track drifted from completed episode setup")
    if wizard_duration is not None and (
        isinstance(wizard_duration, bool)
        or not isinstance(wizard_duration, int)
        or wizard_duration != setup_duration
    ):
        raise ValueError("wizard duration drifted from completed episode setup")
    if storyboard is not None:
        board = DramaStoryboard(**storyboard)
        if expected_episode_no is not None and board.episode_no != expected_episode_no:
            raise ValueError("storyboard belongs to a different episode")
        if board.track != setup_track or board.target_duration_seconds != setup_duration:
            raise ValueError("storyboard identity drifted from completed episode setup")
    return setup_track, setup_duration


class DramaHookCandidate(BaseModel):
    type: Literal["情绪钩", "悬念钩", "反差钩"]
    content: str = Field(min_length=1, max_length=600)


class DramaHookCandidates(BaseModel):
    hooks: List[DramaHookCandidate] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _hooks_are_unique(self) -> "DramaHookCandidates":
        keys = {(item.type.strip(), item.content.strip()) for item in self.hooks}
        if len(keys) != len(self.hooks):
            raise ValueError("hook candidates must be unique")
        if [item.type for item in self.hooks] != ["情绪钩", "悬念钩", "反差钩"]:
            raise ValueError("hook candidates must be ordered as emotion, suspense, contrast")
        return self


def episode_paths(workspace: str, *, episode_no: int = 1) -> DramaEpisodePaths:
    episode_no = normalize_episode_no(episode_no)
    root = paths.WORKSPACE_DIR / workspace
    outputs_dir = root / "outputs"
    episodes_dir = outputs_dir / "episodes"
    stem = f"episode_{episode_no:02d}"
    return DramaEpisodePaths(
        workspace=workspace,
        episode_no=episode_no,
        root=root,
        outputs_dir=outputs_dir,
        episodes_dir=episodes_dir,
        setup_path=episodes_dir / f"{stem}.setup.json",
        hook_candidates_path=episodes_dir / f"{stem}.hooks.json",
        storyboard_path=episodes_dir / f"{stem}.storyboard.json",
        review_path=episodes_dir / f"{stem}.review.json",
        episode_path=episodes_dir / f"{stem}.json",
        meta_path=episodes_dir / f"{stem}.meta.json",
    )


def character_paths(workspace: str, *, season_no: int = 1) -> DramaCharacterPaths:
    if not isinstance(season_no, int) or isinstance(season_no, bool) or season_no < 1:
        raise ValueError("season_no must be a positive integer")
    root = paths.WORKSPACE_DIR / workspace
    data_dir = root / "data"
    characters_dir = data_dir / "characters"
    refs_dir = data_dir / "character_refs"
    return DramaCharacterPaths(
        workspace=workspace,
        season_no=season_no,
        root=root,
        data_dir=data_dir,
        characters_dir=characters_dir,
        refs_dir=refs_dir,
        sheet_path=characters_dir / f"season_{season_no:02d}.json",
    )


class StoryboardShot(BaseModel):
    shot_no: int = Field(ge=1)
    beat: str = Field(default="", max_length=80)
    shot_size: ShotSize
    camera_movement: CameraMovement = "固定"
    duration_seconds: int = Field(ge=1, le=30)
    visual: str = Field(min_length=1, max_length=500)
    narration: str = Field(default="", max_length=220)
    dialogue: str = Field(default="", max_length=120)
    ai_draw_prompt: str = Field(default="", max_length=800)
    is_highlight: bool = False

    @field_validator("shot_no", "duration_seconds", mode="before")
    @classmethod
    def _reject_bool_ints(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("integer fields must not be bool")
        return value


class DramaStoryboard(BaseModel):
    schema_version: int = 1
    season_no: int = Field(default=1, ge=1)
    episode_no: int = Field(default=1, ge=1, le=MAX_DRAMA_EPISODE_NO)
    track: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=80)
    target_duration_seconds: int = Field(default=60, ge=30, le=180)
    hook: Dict[str, Any] = Field(default_factory=dict)
    narrative: str = Field(default="", max_length=2000)
    shots: List[StoryboardShot] = Field(min_length=6, max_length=9)
    soft_warnings: List[str] = Field(default_factory=list)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("hook", mode="before")
    @classmethod
    def _bound_hook_snapshot(cls, value: Any) -> Dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("hook must be an object")
        cleaned: Dict[str, str] = {}
        limits = {"type": 80, "content": 500}
        for key, limit in limits.items():
            raw = value.get(key)
            if raw is None:
                continue
            if isinstance(raw, (dict, list)):
                raise ValueError(f"hook.{key} must be scalar")
            text = str(raw)
            if len(text) > limit:
                raise ValueError(f"hook.{key} must be <= {limit} chars")
            cleaned[key] = text
        return cleaned

    @model_validator(mode="after")
    def _shot_numbers_are_contiguous(self) -> "DramaStoryboard":
        expected = list(range(1, len(self.shots) + 1))
        actual = [shot.shot_no for shot in self.shots]
        if actual != expected:
            raise ValueError("shot_no must be contiguous from 1")
        return self


def normalize_storyboard_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    shots = data.get("shots")
    if not isinstance(shots, list):
        raise ValueError("storyboard.shots must be a list")
    normalized = []
    for idx, raw in enumerate(shots, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each storyboard shot must be an object")
        item = dict(raw)
        item["shot_no"] = idx
        normalized.append(item)
    data["shots"] = normalized
    data["schema_version"] = int(data.get("schema_version") or 1)
    return data


def validate_storyboard_soft(storyboard: DramaStoryboard | Dict[str, Any]) -> List[str]:
    board = storyboard if isinstance(storyboard, DramaStoryboard) else DramaStoryboard(**storyboard)
    warnings: List[str] = []
    highlights = [shot for shot in board.shots if shot.is_highlight]
    if not highlights:
        warnings.append("highlight_missing")

    total = sum(shot.duration_seconds for shot in board.shots)
    delta = total - board.target_duration_seconds
    if abs(delta) > 3:
        warnings.append(f"duration_delta:{delta:+d}")

    first = board.shots[0]
    if first.duration_seconds not in (2, 3) or first.shot_size not in ("特写", "近景"):
        warnings.append("first_shot_hook_shape")

    last = board.shots[-1]
    if not 8 <= last.duration_seconds <= 10:
        warnings.append("last_shot_duration")

    for shot in board.shots:
        lines = [part.strip() for part in shot.dialogue.replace("；", "。").replace("！", "。").replace("？", "。").split("。")]
        if any(len(line) > 15 for line in lines if line):
            warnings.append(f"dialogue_too_long:{shot.shot_no}")
            break
    return warnings


def validate_storyboard_hard(storyboard: DramaStoryboard | Dict[str, Any]) -> List[str]:
    board = storyboard if isinstance(storyboard, DramaStoryboard) else DramaStoryboard(**storyboard)
    errors: List[str] = []
    if sum(1 for shot in board.shots if shot.is_highlight) > 1:
        errors.append("highlight_multiple")
    # Keep a small serialized ceiling even after hook shaping so future schema
    # additions cannot turn storyboard payloads into oversized Web artifacts.
    if len(json.dumps(board.hook, ensure_ascii=False)) > 800:
        errors.append("hook_too_large")
    return errors


class ReferenceImage(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    generated_by: str = Field(default="", max_length=80)
    prompt: str = Field(default="", max_length=1000)
    seed: Optional[int] = None
    requested_model: str = Field(default="", max_length=80)
    requested_size: str = Field(default="", max_length=40)
    provider_size: str = Field(default="", max_length=40)
    width: Optional[int] = Field(default=None, ge=1, le=16384)
    height: Optional[int] = Field(default=None, ge=1, le=16384)

    @field_validator("path")
    @classmethod
    def _path_is_workspace_relative(cls, value: str) -> str:
        text = value.replace("\\", "/")
        if text.startswith("/") or text.startswith("../") or "/../" in text or text == "..":
            raise ValueError("reference image path must stay inside workspace")
        if text.startswith("./"):
            text = text[2:]
        if not text.startswith("data/character_refs/"):
            raise ValueError("reference image path must live under data/character_refs")
        return text

    @field_validator("seed", mode="before")
    @classmethod
    def _reject_bool_seed(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("seed must not be bool")
        return value

    @field_validator("width", "height", mode="before")
    @classmethod
    def _reject_bool_dimensions(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("reference image dimensions must not be bool")
        return value


class DramaCharacter(BaseModel):
    id: str = Field(pattern=r"^c\d{3}$")
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(default="", max_length=80)
    age_range: str = Field(default="", max_length=40)
    gender: str = Field(default="", max_length=20)
    lora_token: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    visual_features: Dict[str, str] = Field(default_factory=dict)
    wardrobe_default: str = Field(default="", max_length=180)
    expression_keywords: List[str] = Field(default_factory=list, max_length=8)
    visual_signature: str = Field(default="", max_length=120)
    prompt_template_sd: str = Field(default="", max_length=1200)
    reference_images: List[ReferenceImage] = Field(default_factory=list, max_length=8)
    appearances: List[int] = Field(default_factory=list, max_length=MAX_DRAMA_EPISODE_NO)
    manual_override: bool = False
    visual_contrast_with: Dict[str, Any] = Field(default_factory=dict)
    agent_suggestions: List[Dict[str, Any]] = Field(default_factory=list, max_length=12)

    @field_validator("visual_features", mode="before")
    @classmethod
    def _visual_features_are_strings(cls, value: Any) -> Dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("visual_features must be an object")
        cleaned: Dict[str, str] = {}
        for key, raw in value.items():
            text = str(raw)
            if len(text) > 180:
                raise ValueError("visual feature value too long")
            cleaned[str(key)[:40]] = text
        return cleaned

    @field_validator("expression_keywords", mode="before")
    @classmethod
    def _expression_keywords_are_strings(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expression_keywords must be a list")
        return [str(item)[:24] for item in value]

    @field_validator("appearances", mode="before")
    @classmethod
    def _appearances_are_strict_episode_numbers(cls, value: Any) -> List[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("appearances must be a list")
        out = set()
        for raw in value:
            if not isinstance(raw, int) or isinstance(raw, bool):
                raise ValueError("appearance episode numbers must be strict integers")
            if raw < 1 or raw > MAX_DRAMA_EPISODE_NO:
                raise ValueError(
                    f"appearance episode numbers must be between 1 and {MAX_DRAMA_EPISODE_NO}"
                )
            out.add(raw)
        return sorted(out)

    @field_validator("visual_contrast_with", mode="before")
    @classmethod
    def _contrast_shape(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("visual_contrast_with must be an object")
        target = value.get("target_id")
        if target is not None and not isinstance(target, str):
            raise ValueError("visual_contrast_with.target_id must be a string")
        rules = value.get("rules")
        if rules is not None and not isinstance(rules, dict):
            raise ValueError("visual_contrast_with.rules must be an object")
        return value


class CharacterSheet(BaseModel):
    schema_version: int = 1
    season_no: int = Field(default=1, ge=1)
    episode_no: int = Field(default=1, ge=1, le=MAX_DRAMA_EPISODE_NO)
    generated_episode_nos: List[int] = Field(default_factory=list, max_length=MAX_DRAMA_EPISODE_NO)
    track: str = Field(default="", max_length=20)
    source_storyboard_title: str = Field(default="", max_length=80)
    # A single station invocation is checked separately at the station boundary.
    # This model is the season-wide library; c001-c999 is the durable id space.
    characters: List[DramaCharacter] = Field(min_length=1, max_length=999)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("generated_episode_nos", mode="before")
    @classmethod
    def _generated_episode_nos_are_strict(cls, value: Any) -> List[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("generated_episode_nos must be a list")
        numbers = [_strict_schema_episode_no(item) for item in value]
        return sorted(set(numbers))

    @model_validator(mode="after")
    def _ids_unique_and_contrast_targets_exist(self) -> "CharacterSheet":
        ids = [character.id for character in self.characters]
        if len(ids) != len(set(ids)):
            raise ValueError("character ids must be unique")
        id_set = set(ids)
        for character in self.characters:
            target = character.visual_contrast_with.get("target_id")
            if target and target not in id_set:
                raise ValueError(f"visual_contrast_with target not found: {target}")
        return self


DramaVerdict = Literal["Approve", "Reject", "Abstain"]
DramaReviewStation = Literal["setup", "hook", "storyboard", "characters"]

REJECT_STATION_MAP: Dict[str, DramaReviewStation] = {
    "hook": "hook",
    "pace": "storyboard",
    "ai_friendly": "storyboard",
    "character_consistency": "characters",
    "cliffhanger": "hook",
}

DRAMA_REVIEW_SCORE_FIELDS = (
    "hook",
    "pace",
    "ai_friendly",
    "character_consistency",
    "cliffhanger",
)


def _clean_drama_score(field: str, value: Any) -> tuple[float, List[str]]:
    warnings: List[str] = []
    if isinstance(value, bool):
        return 0.0, [f"{field}:invalid_bool"]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0, [f"{field}:invalid_number"]
    if not math.isfinite(number):
        return 0.0, [f"{field}:invalid_nonfinite"]
    if number < 0:
        warnings.append(f"{field}:clamped_low")
        number = 0.0
    elif number > 10:
        warnings.append(f"{field}:clamped_high")
        number = 10.0
    return number, warnings


class DramaSubScores(BaseModel):
    hook: float = 0
    pace: float = 0
    ai_friendly: float = 0
    character_consistency: float = 0
    cliffhanger: float = 0
    score_warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_scores(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        data = dict(value)
        warnings = list(data.get("score_warnings") or [])
        for field in DRAMA_REVIEW_SCORE_FIELDS:
            if field not in data:
                warnings.append(f"{field}:missing")
            number, field_warnings = _clean_drama_score(field, data.get(field, 0))
            data[field] = number
            warnings.extend(field_warnings)
        data["score_warnings"] = warnings
        return data

    def values(self) -> List[float]:  # type: ignore[override]
        return [float(getattr(self, field)) for field in DRAMA_REVIEW_SCORE_FIELDS]


def derive_verdict(sub_scores: DramaSubScores | Dict[str, Any]) -> DramaVerdict:
    scores = sub_scores if isinstance(sub_scores, DramaSubScores) else DramaSubScores(**sub_scores)
    values = scores.values()
    if any(score < 5 for score in values):
        return "Reject"
    if all(score >= 7 for score in values):
        return "Approve"
    return "Abstain"


def reject_station_for_scores(sub_scores: DramaSubScores | Dict[str, Any]) -> Optional[DramaReviewStation]:
    scores = sub_scores if isinstance(sub_scores, DramaSubScores) else DramaSubScores(**sub_scores)
    lowest_field = min(DRAMA_REVIEW_SCORE_FIELDS, key=lambda field: float(getattr(scores, field)))
    if float(getattr(scores, lowest_field)) >= 5:
        return None
    return REJECT_STATION_MAP[lowest_field]


class AdvisorSuggestion(BaseModel):
    station: DramaReviewStation
    field: str = Field(default="", max_length=80)
    shot_no: Optional[int] = None
    character_id: str = Field(default="", max_length=16)
    new_value: str = Field(default="", max_length=1200)
    reason: str = Field(default="", max_length=400)

    @field_validator("shot_no", mode="before")
    @classmethod
    def _reject_bool_shot_no(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("shot_no must not be bool")
        return value


class DramaReview(BaseModel):
    schema_version: int = 1
    episode_no: int = Field(default=1, ge=1, le=MAX_DRAMA_EPISODE_NO)
    season_no: int = Field(default=1, ge=1)
    agent_name: str = "drama_reviewer"
    verdict: DramaVerdict = "Abstain"
    score: float = 0
    sub_scores: DramaSubScores = Field(default_factory=DramaSubScores)
    issues: List[str] = Field(default_factory=list, max_length=20)
    suggestions: List[AdvisorSuggestion] = Field(default_factory=list, max_length=20)
    needs_human_review: bool = False
    reject_station: Optional[DramaReviewStation] = None
    verdict_warning: str = ""
    parse_failed: bool = False
    # Hash of the exact setup/storyboard/episode-cast identity reviewed by the
    # agent.  It deliberately excludes generated reference-image metadata so a
    # paid image phase can reassemble without pretending the text was re-read.
    input_fingerprint: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _derive_local_verdict(self) -> "DramaReview":
        if self.parse_failed:
            object.__setattr__(self, "verdict", "Abstain")
            object.__setattr__(self, "reject_station", None)
            object.__setattr__(self, "score", 0.0)
            object.__setattr__(self, "needs_human_review", True)
            return self
        supplied = self.verdict
        derived = derive_verdict(self.sub_scores)
        object.__setattr__(self, "verdict", derived)
        object.__setattr__(self, "reject_station", reject_station_for_scores(self.sub_scores))
        if supplied and supplied != derived:
            object.__setattr__(self, "verdict_warning", f"model_verdict_mismatch:{supplied}->{derived}")
        values = self.sub_scores.values()
        object.__setattr__(self, "score", round(sum(values) / len(values), 2))
        if derived != "Approve" or self.parse_failed:
            object.__setattr__(self, "needs_human_review", True)
        return self


class DurationEstimate(BaseModel):
    target: int
    estimate: int
    delta: int


class DramaEpisodeMeta(BaseModel):
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    season_no: int = Field(default=1, ge=1)
    verdict: DramaVerdict
    rewrite_count: int = 0
    needs_human_review: bool = False
    cost_cny: float = 0
    agent_reviews: List[DramaReview] = Field(default_factory=list)
    highlight_shot_no: Optional[int] = None
    duration_estimate_vs_target: DurationEstimate
    input_fingerprint: str = ""
    input_fingerprint_version: int = Field(default=1, ge=1, le=2)
    character_fingerprint_ids: List[str] = Field(default_factory=list, max_length=8)
    episode_sha256: str = Field(default="", pattern=r"^(?:|[0-9a-f]{64})$")
    stale: bool = False

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("input_fingerprint_version", mode="before")
    @classmethod
    def _fingerprint_version_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value not in (1, 2):
            raise ValueError("input_fingerprint_version must be 1 or 2")
        return value

    @field_validator("character_fingerprint_ids", mode="before")
    @classmethod
    def _character_fingerprint_ids_are_strict(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("character_fingerprint_ids must be a list")
        ids: List[str] = []
        for raw in value:
            if not isinstance(raw, str) or re.fullmatch(r"c\d{3}", raw) is None:
                raise ValueError("character_fingerprint_ids must contain character ids")
            ids.append(raw)
        if len(ids) != len(set(ids)):
            raise ValueError("character_fingerprint_ids must be unique")
        return sorted(ids)


class DramaEpisode(BaseModel):
    schema_version: int = 1
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    season_no: int = Field(default=1, ge=1)
    title: str = Field(default="", max_length=120)
    logline: str = Field(default="", max_length=500)
    track: str = Field(default="", max_length=20)
    target_duration_seconds: int = Field(ge=1, le=300)
    estimated_duration_seconds: int = Field(ge=0, le=600)
    core_setup: Dict[str, Any] = Field(default_factory=dict)
    ai_friendly_constraints: Dict[str, Any] = Field(default_factory=dict)
    narrative: str = Field(default="", max_length=5000)
    storyboard: List[Dict[str, Any]] = Field(default_factory=list)
    ending_hook: Dict[str, Any] = Field(default_factory=dict)
    self_check: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHOT_ID_PATTERN = r"^shot_[0-9a-f]{24}$"
_SEGMENT_ID_PATTERN = r"^segment_[0-9a-f]{24}$"
_ASSET_VERSION_ID_PATTERN = r"^av_[0-9a-f]{24}$"
_ART_DIRECTION_VERSION_ID_PATTERN = r"^ad_[0-9a-f]{24}$"
_SCENE_ID_PATTERN = r"^s[0-9]{3}$"
_SCENE_VERSION_ID_PATTERN = r"^sv_[0-9a-f]{24}$"
_PROP_OR_CLUE_ID_PATTERN = r"^(?:p|l)[0-9]{3}$"
_PROP_OR_CLUE_VERSION_ID_PATTERN = r"^pcv_[0-9a-f]{24}$"


def _canonical_sha256(data: Any) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ArtDirectionRef(BaseModel):
    """Optional immutable art-direction selection supplied by a later stage."""

    model_config = ConfigDict(extra="forbid", strict=True)

    art_direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$")
    fingerprint: str = Field(pattern=_SHA256_PATTERN)


class ArtDirectionSpec(BaseModel):
    """Bounded season-level visual direction without provider/prompt evidence."""

    model_config = ConfigDict(extra="forbid", strict=True)

    preset: str = Field(default="", max_length=80)
    positive_tokens: List[str] = Field(default_factory=list, max_length=32)
    negative_tokens: List[str] = Field(default_factory=list, max_length=32)
    palette: List[str] = Field(default_factory=list, max_length=8)
    aspect_ratio: str = Field(pattern=r"^[1-9][0-9]?:[1-9][0-9]?$", max_length=5)

    @field_validator("preset", mode="before")
    @classmethod
    def _preset_is_canonical(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("art direction preset must be a string")
        if value and (not value.strip() or value != value.strip()):
            raise ValueError("art direction preset must use canonical whitespace")
        return value

    @field_validator("positive_tokens", "negative_tokens", mode="before")
    @classmethod
    def _tokens_are_bounded_unique_strings(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("art direction tokens must be a list")
        if any(
            not isinstance(item, str)
            or not item
            or not item.strip()
            or item != item.strip()
            or len(item) > 80
            for item in value
        ):
            raise ValueError("art direction tokens must be non-empty bounded strings")
        if len(value) != len(set(value)):
            raise ValueError("art direction tokens must be unique")
        return value

    @field_validator("palette", mode="before")
    @classmethod
    def _palette_is_canonical_hex(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("art direction palette must be a list")
        if any(
            not isinstance(item, str)
            or re.fullmatch(r"#[0-9a-f]{6}", item) is None
            for item in value
        ):
            raise ValueError("art direction palette must use lowercase #rrggbb colors")
        if len(value) != len(set(value)):
            raise ValueError("art direction palette entries must be unique")
        return value

    @model_validator(mode="after")
    def _spec_has_visual_content(self) -> "ArtDirectionSpec":
        if not (
            self.preset
            or self.positive_tokens
            or self.negative_tokens
            or self.palette
        ):
            raise ValueError("art direction spec must contain visual guidance")
        return self


ArtDirectionVersionSource = Literal[
    "preset",
    "manual",
    "ai_suggestion",
    "imported",
]


class ArtDirectionVersion(BaseModel):
    """One immutable, content-addressed art-direction candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    art_direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version_id: str = Field(pattern=_ART_DIRECTION_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    derived_from: Optional[str] = Field(
        default=None,
        pattern=_ART_DIRECTION_VERSION_ID_PATTERN,
    )
    source_kind: ArtDirectionVersionSource
    spec: ArtDirectionSpec

    @model_validator(mode="after")
    def _version_is_content_addressed(self) -> "ArtDirectionVersion":
        if self.derived_from == self.version_id:
            raise ValueError("art direction version cannot derive from itself")
        payload = self.model_dump(exclude={"version_id", "version_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if fingerprint != self.version_fingerprint:
            raise ValueError("art direction version fingerprint is invalid")
        if self.version_id != f"ad_{fingerprint[:24]}":
            raise ValueError("art direction version id is invalid")
        return self


class ArtDirectionCatalog(BaseModel):
    """Season-level candidates plus one explicit selected version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    art_direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    versions: List[ArtDirectionVersion] = Field(min_length=1, max_length=256)
    selected_version_id: str = Field(pattern=_ART_DIRECTION_VERSION_ID_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "selection_revision", mode="before")
    @classmethod
    def _catalog_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        if info.field_name == "season_no" and value < 1:
            raise ValueError("season_no must be positive")
        return value

    @model_validator(mode="after")
    def _catalog_is_consistent(self) -> "ArtDirectionCatalog":
        if any(
            version.art_direction_id != self.art_direction_id
            for version in self.versions
        ):
            raise ValueError("art direction versions must belong to the catalog")
        ids = [version.version_id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("art direction version ids must be unique")
        if self.selected_version_id not in set(ids):
            raise ValueError("selected art direction version does not exist")
        parents = {
            version.version_id: version.derived_from for version in self.versions
        }
        for parent in parents.values():
            if parent is not None and parent not in parents:
                raise ValueError("derived art direction version does not exist")
        for version_id in parents:
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("art direction derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("art direction catalog fingerprint is invalid")
        return self


ArtDirectionScope = Literal["global", "series", "episode"]
ScopedArtDirectionScope = Literal["global", "episode"]


class ScopedArtDirectionCatalog(BaseModel):
    """Workspace-global or episode override catalog with explicit activation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    scope: ScopedArtDirectionScope
    season_no: Optional[int] = Field(default=None, ge=1)
    episode_no: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_DRAMA_EPISODE_NO,
    )
    art_direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    versions: List[ArtDirectionVersion] = Field(min_length=1, max_length=256)
    selected_version_id: str = Field(pattern=_ART_DIRECTION_VERSION_ID_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    enabled: bool = True
    scope_revision: int = Field(ge=0, le=2_147_483_647)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "season_no",
        "episode_no",
        "selection_revision",
        "scope_revision",
        mode="before",
    )
    @classmethod
    def _scoped_catalog_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> Optional[int]:
        if value is None and info.field_name in ("season_no", "episode_no"):
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _scoped_catalog_is_consistent(self) -> "ScopedArtDirectionCatalog":
        if self.scope == "global":
            if self.season_no is not None or self.episode_no is not None:
                raise ValueError("global art direction scope cannot bind an episode")
        elif self.season_no is None or self.episode_no is None:
            raise ValueError("episode art direction scope requires season and episode")
        if any(
            version.art_direction_id != self.art_direction_id
            for version in self.versions
        ):
            raise ValueError("art direction versions must belong to the scope")
        ids = [version.version_id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("scoped art direction version ids must be unique")
        if self.selected_version_id not in set(ids):
            raise ValueError("scoped selected art direction version does not exist")
        parents = {
            version.version_id: version.derived_from for version in self.versions
        }
        for parent in parents.values():
            if parent is not None and parent not in parents:
                raise ValueError("scoped derived art direction version does not exist")
        for version_id in parents:
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("scoped art direction derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("scoped art direction catalog fingerprint is invalid")
        return self


class ArtDirectionResolution(BaseModel):
    """Exact scoped selection frozen into one episode RenderPlan."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scope: ArtDirectionScope
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    ref: ArtDirectionRef
    source_selection_revision: int = Field(ge=0, le=2_147_483_647)
    source_scope_revision: Optional[int] = Field(
        default=None,
        ge=0,
        le=2_147_483_647,
    )
    source_selection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    resolution_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "season_no",
        "episode_no",
        "source_selection_revision",
        "source_scope_revision",
        mode="before",
    )
    @classmethod
    def _resolution_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> Optional[int]:
        if value is None and info.field_name == "source_scope_revision":
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _resolution_is_content_addressed(self) -> "ArtDirectionResolution":
        if (self.scope == "series") != (self.source_scope_revision is None):
            raise ValueError(
                "art direction resolution scope revision is inconsistent"
            )
        selection_payload = {
            "scope": self.scope,
            "season_no": (
                self.season_no
                if self.scope in ("series", "episode")
                else None
            ),
            "episode_no": self.episode_no if self.scope == "episode" else None,
            "ref": self.ref.model_dump(),
            "selection_revision": self.source_selection_revision,
            "scope_revision": self.source_scope_revision,
        }
        if (
            _canonical_sha256(selection_payload)
            != self.source_selection_fingerprint
        ):
            raise ValueError(
                "art direction source selection fingerprint is invalid"
            )
        payload = self.model_dump(exclude={"resolution_fingerprint"})
        if _canonical_sha256(payload) != self.resolution_fingerprint:
            raise ValueError("art direction resolution fingerprint is invalid")
        return self


class AssetArtifact(BaseModel):
    """Bounded local artifact identity without provider or prompt data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def _asset_path_is_character_reference(cls, value: str) -> str:
        text = value.replace("\\", "/")
        if (
            text.startswith("/")
            or text.startswith("../")
            or "/../" in text
            or text == ".."
        ):
            raise ValueError("asset artifact path must stay inside the workspace")
        if text.startswith("./"):
            text = text[2:]
        if not text.startswith("data/character_refs/"):
            raise ValueError("asset artifact path must live under data/character_refs")
        return text

    @field_validator("size_bytes", mode="before")
    @classmethod
    def _asset_size_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("asset artifact size must be a strict integer")
        return value


AssetVersionSource = Literal[
    "identity_snapshot",
    "legacy_reference",
    "appended_candidate",
]


class AssetVersion(BaseModel):
    """One immutable, content-addressed character asset version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    asset_id: str = Field(pattern=r"^c\d{3}$")
    asset_version_id: str = Field(pattern=_ASSET_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    derived_from: Optional[str] = Field(default=None, pattern=_ASSET_VERSION_ID_PATTERN)
    source_kind: AssetVersionSource
    identity_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact: Optional[AssetArtifact] = None

    @model_validator(mode="after")
    def _asset_version_is_content_addressed(self) -> "AssetVersion":
        if self.derived_from == self.asset_version_id:
            raise ValueError("asset version cannot derive from itself")
        source_payload = {
            "asset_id": self.asset_id,
            "identity_fingerprint": self.identity_fingerprint,
            "source_kind": self.source_kind,
            "artifact": (
                self.artifact.model_dump() if self.artifact is not None else None
            ),
        }
        if _canonical_sha256(source_payload) != self.source_fingerprint:
            raise ValueError("asset version source fingerprint is invalid")
        payload = self.model_dump(
            exclude={"asset_version_id", "version_fingerprint"}
        )
        fingerprint = _canonical_sha256(payload)
        if fingerprint != self.version_fingerprint:
            raise ValueError("asset version fingerprint does not match its payload")
        if self.asset_version_id != f"av_{fingerprint[:24]}":
            raise ValueError("asset version id does not match its fingerprint")
        return self


class CharacterAsset(BaseModel):
    """Version history and explicit selection for one stable character id."""

    model_config = ConfigDict(extra="forbid", strict=True)

    asset_id: str = Field(pattern=r"^c\d{3}$")
    identity_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    versions: List[AssetVersion] = Field(min_length=1, max_length=256)
    selected_version_id: str = Field(pattern=_ASSET_VERSION_ID_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)

    @field_validator("selection_revision", mode="before")
    @classmethod
    def _selection_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("selection revision must be a strict integer")
        return value

    @model_validator(mode="after")
    def _character_asset_history_is_consistent(self) -> "CharacterAsset":
        if any(version.asset_id != self.asset_id for version in self.versions):
            raise ValueError("asset versions must belong to the same character asset")
        ids = [version.asset_version_id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("asset version ids must be unique")
        if self.selected_version_id not in set(ids):
            raise ValueError("selected asset version does not exist")
        parents = {
            version.asset_version_id: version.derived_from
            for version in self.versions
        }
        for version_id, parent in parents.items():
            if parent is not None and parent not in parents:
                raise ValueError("derived asset version does not exist")
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("asset version derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        return self


class AssetRef(BaseModel):
    """Frozen reference to one exact character asset version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["character"] = "character"
    asset_id: str = Field(pattern=r"^c\d{3}$")
    asset_version_id: str = Field(pattern=_ASSET_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact_sha256: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)


class CharacterAssetCatalog(BaseModel):
    """Season-level render-side character asset truth."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    assets: List[CharacterAsset] = Field(min_length=1, max_length=999)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _catalog_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict positive integer")
        return value

    @model_validator(mode="after")
    def _catalog_is_internally_consistent(self) -> "CharacterAssetCatalog":
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("character asset ids must be unique")
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("character asset catalog fingerprint does not match its payload")
        return self


class EpisodeAssetManifest(BaseModel):
    """Episode-scoped frozen selections bound to one fresh RenderPlan."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    asset_refs: List[AssetRef] = Field(min_length=1, max_length=8)
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _manifest_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict positive integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _manifest_is_internally_consistent(self) -> "EpisodeAssetManifest":
        ids = [ref.asset_id for ref in self.asset_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("episode asset refs must be unique")
        selection_payload = [ref.model_dump() for ref in self.asset_refs]
        if _canonical_sha256(selection_payload) != self.selection_fingerprint:
            raise ValueError("episode asset selection fingerprint is invalid")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("episode asset manifest fingerprint does not match its payload")
        return self


class SceneSpec(BaseModel):
    """Bounded reusable scene identity without prompts or provider state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    display_name: str = Field(min_length=1, max_length=80)
    location: str = Field(min_length=1, max_length=120)
    time_of_day: str = Field(default="", max_length=40)
    weather: str = Field(default="", max_length=40)
    spatial_anchors: List[str] = Field(default_factory=list, max_length=16)
    visual_tokens: List[str] = Field(default_factory=list, max_length=32)

    @field_validator("display_name", "location", "time_of_day", "weather", mode="before")
    @classmethod
    def _scene_strings_are_canonical(cls, value: Any, info: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string")
        if value != value.strip() or (info.field_name in {"display_name", "location"} and not value):
            raise ValueError(f"{info.field_name} must use canonical non-empty text")
        if value and not value.strip():
            raise ValueError(f"{info.field_name} must use canonical text")
        return value

    @field_validator("spatial_anchors", "visual_tokens", mode="before")
    @classmethod
    def _scene_lists_are_canonical(cls, value: Any, info: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        maximum = 120 if info.field_name == "spatial_anchors" else 80
        if any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > maximum
            for item in value
        ):
            raise ValueError(f"{info.field_name} must contain bounded canonical strings")
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} entries must be unique")
        return value


class SceneAssetArtifact(BaseModel):
    """One verified local scene reference under its stable semantic id."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)

    @field_validator("path", mode="before")
    @classmethod
    def _scene_artifact_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("scene artifact path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"data/scene_refs/s[0-9]{3}/"
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}"
                r"(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,119})*",
                value,
            )
            is None
        ):
            raise ValueError("scene artifact path must stay under data/scene_refs/sNNN")
        return value

    @field_validator("size_bytes", mode="before")
    @classmethod
    def _scene_artifact_size_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("scene artifact size must be a strict integer")
        return value


SceneAssetVersionSource = Literal[
    "identity_snapshot",
    "appended_candidate",
    "imported",
]


class SceneAssetVersion(BaseModel):
    """One immutable, content-addressed scene candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scene_id: str = Field(pattern=_SCENE_ID_PATTERN)
    scene_version_id: str = Field(pattern=_SCENE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    derived_from: Optional[str] = Field(default=None, pattern=_SCENE_VERSION_ID_PATTERN)
    source_kind: SceneAssetVersionSource
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    spec: SceneSpec
    artifact: Optional[SceneAssetArtifact] = None

    @model_validator(mode="after")
    def _scene_version_is_content_addressed(self) -> "SceneAssetVersion":
        if self.derived_from == self.scene_version_id:
            raise ValueError("scene version cannot derive from itself")
        if self.artifact is not None and not self.artifact.path.startswith(
            f"data/scene_refs/{self.scene_id}/"
        ):
            raise ValueError("scene artifact belongs to another scene")
        source_payload = {
            "scene_id": self.scene_id,
            "source_kind": self.source_kind,
            "spec": self.spec.model_dump(),
            "artifact": self.artifact.model_dump() if self.artifact is not None else None,
        }
        if _canonical_sha256(source_payload) != self.source_fingerprint:
            raise ValueError("scene version source fingerprint is invalid")
        payload = self.model_dump(exclude={"scene_version_id", "version_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if fingerprint != self.version_fingerprint:
            raise ValueError("scene version fingerprint is invalid")
        if self.scene_version_id != f"sv_{fingerprint[:24]}":
            raise ValueError("scene version id is invalid")
        return self


class SceneAsset(BaseModel):
    """Append-only versions and explicit selected version for one scene."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scene_id: str = Field(pattern=_SCENE_ID_PATTERN)
    versions: List[SceneAssetVersion] = Field(min_length=1, max_length=256)
    selected_version_id: str = Field(pattern=_SCENE_VERSION_ID_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)

    @field_validator("selection_revision", mode="before")
    @classmethod
    def _scene_selection_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("scene selection revision must be a strict integer")
        return value

    @model_validator(mode="after")
    def _scene_asset_history_is_consistent(self) -> "SceneAsset":
        if any(version.scene_id != self.scene_id for version in self.versions):
            raise ValueError("scene versions must belong to the same scene")
        ids = [version.scene_version_id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("scene version ids must be unique")
        artifacts_by_path: Dict[str, SceneAssetArtifact] = {}
        for version in self.versions:
            if version.artifact is None:
                continue
            previous = artifacts_by_path.get(version.artifact.path)
            if previous is not None and previous != version.artifact:
                raise ValueError(
                    "scene artifact paths cannot identify different immutable bytes"
                )
            artifacts_by_path[version.artifact.path] = version.artifact
        if self.selected_version_id not in set(ids):
            raise ValueError("selected scene version does not exist")
        parents = {
            version.scene_version_id: version.derived_from for version in self.versions
        }
        for version_id, parent in parents.items():
            if parent is not None and parent not in parents:
                raise ValueError("derived scene version does not exist")
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("scene version derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        return self


class SceneAssetRef(BaseModel):
    """Frozen reference to one exact selected scene version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["scene"] = "scene"
    scene_id: str = Field(pattern=_SCENE_ID_PATTERN)
    scene_version_id: str = Field(pattern=_SCENE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact_sha256: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)


class SceneAssetCatalog(BaseModel):
    """Season-level scene candidates without an external creative source."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    assets: List[SceneAsset] = Field(min_length=1, max_length=999)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _scene_catalog_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict positive integer")
        return value

    @model_validator(mode="after")
    def _scene_catalog_is_consistent(self) -> "SceneAssetCatalog":
        ids = [asset.scene_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("scene asset ids must be unique")
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("scene catalog fingerprint is invalid")
        return self


class ShotSceneRef(BaseModel):
    """One explicit stable-shot to frozen-scene binding."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    scene_ref: SceneAssetRef


class EpisodeSceneAssetManifest(BaseModel):
    """Episode-scoped explicit scene bindings and selected versions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    binding_revision: int = Field(ge=0, le=2_147_483_647)
    usage_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_scene_refs: List[ShotSceneRef] = Field(min_length=1, max_length=100)
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "binding_revision", mode="before")
    @classmethod
    def _scene_manifest_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _scene_manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _scene_manifest_is_consistent(self) -> "EpisodeSceneAssetManifest":
        shot_ids = [ref.shot_id for ref in self.shot_scene_refs]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("scene manifest shot ids must be unique")
        usage_payload = [ref.model_dump() for ref in self.shot_scene_refs]
        if _canonical_sha256(usage_payload) != self.usage_fingerprint:
            raise ValueError("scene manifest usage fingerprint is invalid")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("scene manifest fingerprint is invalid")
        return self


PropOrClueKind = Literal["prop", "clue"]


class PropOrClueSpec(BaseModel):
    """Bounded reusable prop/clue identity without inferred provenance."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: PropOrClueKind
    display_name: str = Field(min_length=1, max_length=80)
    owner_character_id: Optional[str] = Field(default=None, pattern=r"^c\d{3}$")
    state_label: str = Field(default="", max_length=80)
    first_seen_episode_no: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_DRAMA_EPISODE_NO,
    )
    visual_tokens: List[str] = Field(default_factory=list, max_length=32)

    @field_validator("display_name", "state_label", mode="before")
    @classmethod
    def _prop_clue_strings_are_canonical(cls, value: Any, info: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string")
        if value != value.strip() or (
            info.field_name == "display_name" and not value
        ):
            raise ValueError(f"{info.field_name} must use canonical text")
        if value and not value.strip():
            raise ValueError(f"{info.field_name} must use canonical text")
        return value

    @field_validator("first_seen_episode_no", mode="before")
    @classmethod
    def _first_seen_is_strict(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        return _strict_schema_episode_no(value)

    @field_validator("visual_tokens", mode="before")
    @classmethod
    def _prop_clue_tokens_are_canonical(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("visual_tokens must be a list")
        if any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > 80
            for item in value
        ):
            raise ValueError("visual_tokens must contain bounded canonical strings")
        if len(value) != len(set(value)):
            raise ValueError("visual_tokens entries must be unique")
        return value


class PropOrClueArtifact(BaseModel):
    """One verified local prop/clue reference under its semantic id."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)

    @field_validator("path", mode="before")
    @classmethod
    def _prop_clue_artifact_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("prop/clue artifact path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"data/prop_clue_refs/(?:p|l)[0-9]{3}/"
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}"
                r"(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,119})*",
                value,
            )
            is None
        ):
            raise ValueError(
                "prop/clue artifact path must stay under data/prop_clue_refs/<asset_id>"
            )
        return value

    @field_validator("size_bytes", mode="before")
    @classmethod
    def _prop_clue_artifact_size_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("prop/clue artifact size must be a strict integer")
        return value


PropOrClueAssetVersionSource = Literal[
    "identity_snapshot",
    "appended_candidate",
    "imported",
]


class PropOrClueAssetVersion(BaseModel):
    """One immutable, content-addressed prop/clue candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    asset_id: str = Field(pattern=_PROP_OR_CLUE_ID_PATTERN)
    asset_version_id: str = Field(pattern=_PROP_OR_CLUE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    derived_from: Optional[str] = Field(
        default=None,
        pattern=_PROP_OR_CLUE_VERSION_ID_PATTERN,
    )
    source_kind: PropOrClueAssetVersionSource
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    spec: PropOrClueSpec
    artifact: Optional[PropOrClueArtifact] = None

    @model_validator(mode="after")
    def _prop_clue_version_is_content_addressed(self) -> "PropOrClueAssetVersion":
        expected_prefix = "p" if self.spec.kind == "prop" else "l"
        if not self.asset_id.startswith(expected_prefix):
            raise ValueError("prop/clue kind does not match its semantic id")
        if self.derived_from == self.asset_version_id:
            raise ValueError("prop/clue version cannot derive from itself")
        if self.artifact is not None and not self.artifact.path.startswith(
            f"data/prop_clue_refs/{self.asset_id}/"
        ):
            raise ValueError("prop/clue artifact belongs to another asset")
        source_payload = {
            "asset_id": self.asset_id,
            "source_kind": self.source_kind,
            "spec": self.spec.model_dump(),
            "artifact": self.artifact.model_dump() if self.artifact is not None else None,
        }
        if _canonical_sha256(source_payload) != self.source_fingerprint:
            raise ValueError("prop/clue version source fingerprint is invalid")
        payload = self.model_dump(
            exclude={"asset_version_id", "version_fingerprint"}
        )
        fingerprint = _canonical_sha256(payload)
        if fingerprint != self.version_fingerprint:
            raise ValueError("prop/clue version fingerprint is invalid")
        if self.asset_version_id != f"pcv_{fingerprint[:24]}":
            raise ValueError("prop/clue version id is invalid")
        return self


class PropOrClueAsset(BaseModel):
    """Append-only versions and explicit selection for one prop/clue."""

    model_config = ConfigDict(extra="forbid", strict=True)

    asset_id: str = Field(pattern=_PROP_OR_CLUE_ID_PATTERN)
    kind: PropOrClueKind
    versions: List[PropOrClueAssetVersion] = Field(min_length=1, max_length=256)
    selected_version_id: str = Field(pattern=_PROP_OR_CLUE_VERSION_ID_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)

    @field_validator("selection_revision", mode="before")
    @classmethod
    def _prop_clue_selection_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("prop/clue selection revision must be a strict integer")
        return value

    @model_validator(mode="after")
    def _prop_clue_asset_history_is_consistent(self) -> "PropOrClueAsset":
        expected_prefix = "p" if self.kind == "prop" else "l"
        if not self.asset_id.startswith(expected_prefix):
            raise ValueError("prop/clue kind does not match its semantic id")
        if any(
            version.asset_id != self.asset_id or version.spec.kind != self.kind
            for version in self.versions
        ):
            raise ValueError("prop/clue versions must belong to the same asset and kind")
        ids = [version.asset_version_id for version in self.versions]
        if len(ids) != len(set(ids)):
            raise ValueError("prop/clue version ids must be unique")
        artifacts_by_path: Dict[str, PropOrClueArtifact] = {}
        for version in self.versions:
            if version.artifact is None:
                continue
            previous = artifacts_by_path.get(version.artifact.path)
            if previous is not None and previous != version.artifact:
                raise ValueError(
                    "prop/clue artifact paths cannot identify different immutable bytes"
                )
            artifacts_by_path[version.artifact.path] = version.artifact
        if self.selected_version_id not in set(ids):
            raise ValueError("selected prop/clue version does not exist")
        parents = {
            version.asset_version_id: version.derived_from for version in self.versions
        }
        for version_id, parent in parents.items():
            if parent is not None and parent not in parents:
                raise ValueError("derived prop/clue version does not exist")
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("prop/clue version derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        return self


class PropOrClueAssetRef(BaseModel):
    """Frozen reference to one exact selected prop/clue version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: PropOrClueKind
    asset_id: str = Field(pattern=_PROP_OR_CLUE_ID_PATTERN)
    asset_version_id: str = Field(pattern=_PROP_OR_CLUE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact_sha256: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _prop_clue_ref_matches_kind(self) -> "PropOrClueAssetRef":
        expected_prefix = "p" if self.kind == "prop" else "l"
        if not self.asset_id.startswith(expected_prefix):
            raise ValueError("prop/clue ref kind does not match its semantic id")
        return self


class PropOrClueAssetCatalog(BaseModel):
    """Season-level prop/clue candidates; an explicit empty catalog is valid."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    assets: List[PropOrClueAsset] = Field(max_length=999)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _prop_clue_catalog_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict positive integer")
        return value

    @model_validator(mode="after")
    def _prop_clue_catalog_is_consistent(self) -> "PropOrClueAssetCatalog":
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("prop/clue asset ids must be unique")
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("prop/clue catalog fingerprint is invalid")
        return self


class ShotPropOrClueRefs(BaseModel):
    """One explicit stable-shot to ordered prop/clue reference list."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    asset_refs: List[PropOrClueAssetRef] = Field(max_length=16)

    @model_validator(mode="after")
    def _shot_prop_clue_refs_are_unique(self) -> "ShotPropOrClueRefs":
        ids = [ref.asset_id for ref in self.asset_refs]
        if len(ids) != len(set(ids)):
            raise ValueError("shot prop/clue refs must be unique")
        return self


class EpisodePropOrClueAssetManifest(BaseModel):
    """Episode-scoped explicit prop/clue bindings and selected versions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    binding_revision: int = Field(ge=0, le=2_147_483_647)
    usage_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_asset_refs: List[ShotPropOrClueRefs] = Field(min_length=1, max_length=100)
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "binding_revision", mode="before")
    @classmethod
    def _prop_clue_manifest_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _prop_clue_manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _prop_clue_manifest_is_consistent(
        self,
    ) -> "EpisodePropOrClueAssetManifest":
        shot_ids = [binding.shot_id for binding in self.shot_asset_refs]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("prop/clue manifest shot ids must be unique")
        usage_payload = [binding.model_dump() for binding in self.shot_asset_refs]
        if _canonical_sha256(usage_payload) != self.usage_fingerprint:
            raise ValueError("prop/clue manifest usage fingerprint is invalid")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("prop/clue manifest fingerprint is invalid")
        return self


AssetUsageKind = Literal["character", "art_direction", "scene", "prop", "clue"]
AssetRetirementStatus = Literal["active", "disabled"]
AssetUsageSourceKind = Literal[
    "episode_scan",
    "character_catalog",
    "art_direction_catalog",
    "art_direction_global_catalog",
    "art_direction_episode_catalog",
    "scene_catalog",
    "prop_clue_catalog",
    "render_plan",
    "character_manifest",
    "scene_manifest",
    "prop_clue_manifest",
]


def _validate_asset_usage_identity(
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
) -> None:
    identity_patterns = {
        "character": (r"^c\d{3}$", _ASSET_VERSION_ID_PATTERN),
        "art_direction": (
            r"^[a-z][a-z0-9_-]{0,63}$",
            _ART_DIRECTION_VERSION_ID_PATTERN,
        ),
        "scene": (_SCENE_ID_PATTERN, _SCENE_VERSION_ID_PATTERN),
        "prop": (r"^p\d{3}$", _PROP_OR_CLUE_VERSION_ID_PATTERN),
        "clue": (r"^l\d{3}$", _PROP_OR_CLUE_VERSION_ID_PATTERN),
    }
    if kind not in identity_patterns:
        raise ValueError("asset usage kind is invalid")
    if not isinstance(asset_id, str) or not isinstance(version_id, str):
        raise ValueError("asset usage identity must use strings")
    asset_pattern, version_pattern = identity_patterns[kind]
    if re.fullmatch(asset_pattern, asset_id) is None:
        raise ValueError("asset usage id does not match its kind")
    if re.fullmatch(version_pattern, version_id) is None:
        raise ValueError("asset usage version id does not match its kind")


class AssetUsageReference(BaseModel):
    """One frozen episode/shot use of an exact immutable asset version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    shot_ids: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _usage_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("shot_ids", mode="before")
    @classmethod
    def _usage_shot_ids_are_canonical(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("asset usage shot_ids must be a list")
        if any(
            not isinstance(item, str)
            or re.fullmatch(_SHOT_ID_PATTERN, item) is None
            for item in value
        ):
            raise ValueError("asset usage contains an invalid shot id")
        if value != sorted(value) or len(value) != len(set(value)):
            raise ValueError("asset usage shot ids must be unique and sorted")
        return value


class AssetVersionUsage(BaseModel):
    """Reverse references for one catalog version, including explicit zero use."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetUsageKind
    asset_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=80)
    references: List[AssetUsageReference] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def _asset_version_usage_is_canonical(self) -> "AssetVersionUsage":
        _validate_asset_usage_identity(
            kind=self.kind,
            asset_id=self.asset_id,
            version_id=self.version_id,
        )
        keys = [
            (item.episode_no, tuple(item.shot_ids)) for item in self.references
        ]
        if keys != sorted(keys) or len({item.episode_no for item in self.references}) != len(
            self.references
        ):
            raise ValueError("asset usage references must be unique and sorted")
        return self


class AssetUsageSourceSnapshot(BaseModel):
    """Bounded source byte identity used to build a reverse index."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: AssetUsageSourceKind
    episode_no: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_DRAMA_EPISODE_NO,
    )
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _usage_source_episode_is_strict(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _usage_source_scope_is_valid(self) -> "AssetUsageSourceSnapshot":
        episode_sources = {
            "render_plan",
            "character_manifest",
            "art_direction_episode_catalog",
            "scene_manifest",
            "prop_clue_manifest",
        }
        if (self.source in episode_sources) != (self.episode_no is not None):
            raise ValueError("asset usage source scope is inconsistent")
        return self


class AssetUsageBlocker(BaseModel):
    """Sanitized reason why a cross-episode scan is not complete."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source: AssetUsageSourceKind
    episode_no: Optional[int] = Field(
        default=None,
        ge=1,
        le=MAX_DRAMA_EPISODE_NO,
    )
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @field_validator("episode_no", mode="before")
    @classmethod
    def _usage_blocker_episode_is_strict(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _usage_blocker_scope_is_valid(self) -> "AssetUsageBlocker":
        episode_sources = {
            "render_plan",
            "character_manifest",
            "art_direction_episode_catalog",
            "scene_manifest",
            "prop_clue_manifest",
        }
        if self.source == "episode_scan":
            if self.episode_no is not None:
                raise ValueError("episode scan blocker cannot name one episode")
        elif (self.source in episode_sources) != (self.episode_no is not None):
            raise ValueError("asset usage blocker scope is inconsistent")
        return self


class SeasonAssetUsageIndex(BaseModel):
    """Content-addressed cross-episode reverse index for all B-stage assets."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    scanned_episode_nos: List[int] = Field(default_factory=list, max_length=100)
    entries: List[AssetVersionUsage] = Field(default_factory=list, max_length=4096)
    source_snapshots: List[AssetUsageSourceSnapshot] = Field(
        default_factory=list,
        max_length=512,
    )
    blockers: List[AssetUsageBlocker] = Field(default_factory=list, max_length=512)
    index_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _usage_index_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("asset usage season_no must be a strict integer")
        return value

    @field_validator("scanned_episode_nos", mode="before")
    @classmethod
    def _scanned_episodes_are_canonical(cls, value: Any) -> List[int]:
        if not isinstance(value, list):
            raise ValueError("scanned_episode_nos must be a list")
        normalized = [_strict_schema_episode_no(item) for item in value]
        if normalized != sorted(normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("scanned episode numbers must be unique and sorted")
        return normalized

    @model_validator(mode="after")
    def _usage_index_is_content_addressed(self) -> "SeasonAssetUsageIndex":
        entry_keys = [
            (item.kind, item.asset_id, item.version_id) for item in self.entries
        ]
        if entry_keys != sorted(entry_keys) or len(entry_keys) != len(set(entry_keys)):
            raise ValueError("asset usage entries must be unique and sorted")
        source_keys = [
            (item.source, item.episode_no or 0, item.sha256)
            for item in self.source_snapshots
        ]
        if source_keys != sorted(source_keys) or len(source_keys) != len(set(source_keys)):
            raise ValueError("asset usage sources must be unique and sorted")
        blocker_keys = [
            (item.source, item.episode_no or 0, item.code)
            for item in self.blockers
        ]
        if blocker_keys != sorted(blocker_keys) or len(blocker_keys) != len(
            set(blocker_keys)
        ):
            raise ValueError("asset usage blockers must be unique and sorted")
        payload = self.model_dump(exclude={"index_fingerprint"})
        if _canonical_sha256(payload) != self.index_fingerprint:
            raise ValueError("asset usage index fingerprint is invalid")
        return self


class AssetRetirementEntry(BaseModel):
    """Non-destructive lifecycle state for one exact catalog version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetUsageKind
    asset_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=80)
    status: AssetRetirementStatus
    status_revision: int = Field(ge=1, le=2_147_483_647)
    usage_index_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )

    @field_validator("status_revision", mode="before")
    @classmethod
    def _retirement_entry_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("asset retirement entry revision must be strict")
        return value

    @model_validator(mode="after")
    def _retirement_entry_is_consistent(self) -> "AssetRetirementEntry":
        _validate_asset_usage_identity(
            kind=self.kind,
            asset_id=self.asset_id,
            version_id=self.version_id,
        )
        if self.status == "disabled" and self.usage_index_fingerprint is None:
            raise ValueError("disabled asset version must bind a usage index")
        return self


class AssetRetirementState(BaseModel):
    """Season-scoped active/disabled ledger; no physical-delete state exists."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    revision: int = Field(ge=0, le=2_147_483_647)
    entries: List[AssetRetirementEntry] = Field(default_factory=list, max_length=4096)
    state_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "revision", mode="before")
    @classmethod
    def _retirement_state_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _retirement_state_is_content_addressed(self) -> "AssetRetirementState":
        keys = [(item.kind, item.asset_id, item.version_id) for item in self.entries]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("asset retirement entries must be unique and sorted")
        if any(item.status_revision > self.revision for item in self.entries):
            raise ValueError("asset retirement entry revision exceeds state revision")
        payload = self.model_dump(exclude={"state_fingerprint"})
        if _canonical_sha256(payload) != self.state_fingerprint:
            raise ValueError("asset retirement state fingerprint is invalid")
        return self


class AssetRetirementDecision(BaseModel):
    """Read-only retirement projection; physical deletion is always forbidden."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetUsageKind
    asset_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=80)
    current_status: AssetRetirementStatus
    references: List[AssetUsageReference] = Field(default_factory=list, max_length=100)
    blockers: List[AssetUsageBlocker] = Field(default_factory=list, max_length=512)
    can_disable: bool
    can_physically_delete: Literal[False] = False
    decision_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _retirement_decision_is_content_addressed(
        self,
    ) -> "AssetRetirementDecision":
        _validate_asset_usage_identity(
            kind=self.kind,
            asset_id=self.asset_id,
            version_id=self.version_id,
        )
        if self.can_disable != (not self.blockers):
            raise ValueError("asset retirement disable decision is inconsistent")
        payload = self.model_dump(exclude={"decision_fingerprint"})
        if _canonical_sha256(payload) != self.decision_fingerprint:
            raise ValueError("asset retirement decision fingerprint is invalid")
        return self


ShotImageReferenceKind = Literal["character", "scene", "prop", "clue"]
ShotImageRequestStatus = Literal["assembled", "blocked"]
ShotImageWarningCode = Literal[
    "reference_limit_exceeded",
    "scene_artifact_missing",
    "prop_clue_artifact_missing",
]
ShotImageBlockedReason = Literal["character_artifact_missing"]


class ShotImageReference(BaseModel):
    """One exact local image reference frozen for a shot request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: ShotImageReferenceKind
    asset_id: str = Field(pattern=r"^(?:c|s|p|l)[0-9]{3}$")
    asset_version_id: str = Field(
        pattern=r"^(?:av|sv|pcv)_[0-9a-f]{24}$",
    )
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)
    position: int = Field(ge=1, le=25)

    @field_validator("artifact_path", mode="before")
    @classmethod
    def _shot_image_artifact_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("shot image reference path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"data/(?:character_refs/c[0-9]{3}|scene_refs/s[0-9]{3}|"
                r"prop_clue_refs/(?:p|l)[0-9]{3})/"
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}"
                r"(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,119})*",
                value,
            )
            is None
        ):
            raise ValueError("shot image reference path must stay inside the workspace")
        return value

    @field_validator("artifact_size_bytes", "position", mode="before")
    @classmethod
    def _shot_image_reference_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _shot_image_reference_matches_kind(self) -> "ShotImageReference":
        expected = {
            "character": ("c", "av_", "data/character_refs/"),
            "scene": ("s", "sv_", "data/scene_refs/"),
            "prop": ("p", "pcv_", "data/prop_clue_refs/"),
            "clue": ("l", "pcv_", "data/prop_clue_refs/"),
        }[self.kind]
        if not self.asset_id.startswith(expected[0]) or not self.asset_version_id.startswith(
            expected[1]
        ):
            raise ValueError("shot image reference id does not match its kind")
        if not self.artifact_path.startswith(
            f"{expected[2]}{self.asset_id}/"
        ):
            raise ValueError("shot image reference artifact belongs to another asset")
        return self


class ShotImageReferencePolicy(BaseModel):
    """Provider-neutral, versioned reference ordering and truncation policy."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    max_reference_images: int = Field(ge=1, le=25)
    priority_version: Literal["character_scene_prop_clue_v1"] = (
        "character_scene_prop_clue_v1"
    )
    policy_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("max_reference_images", mode="before")
    @classmethod
    def _shot_image_reference_limit_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("max_reference_images must be a strict integer")
        return value

    @model_validator(mode="after")
    def _shot_image_policy_is_content_addressed(self) -> "ShotImageReferencePolicy":
        payload = self.model_dump(exclude={"policy_fingerprint"})
        if _canonical_sha256(payload) != self.policy_fingerprint:
            raise ValueError("shot image reference policy fingerprint is invalid")
        return self


class ShotCharacterBinding(BaseModel):
    """Explicit stable-shot character participation; never inferred from text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    character_ids: List[str] = Field(max_length=8)

    @field_validator("character_ids", mode="before")
    @classmethod
    def _shot_character_ids_are_strict(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("character_ids must be a list")
        if any(
            not isinstance(item, str) or re.fullmatch(r"c[0-9]{3}", item) is None
            for item in value
        ):
            raise ValueError("character_ids contain an invalid id")
        if len(value) != len(set(value)):
            raise ValueError("character_ids must be unique")
        return value


class ShotImageRequestSpec(BaseModel):
    """Pure, provider-neutral image input for one stable RenderShot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    status: ShotImageRequestStatus
    shot_size: ShotSize
    camera_movement: CameraMovement
    visual_action: str = Field(min_length=1, max_length=500)
    image_prompt: str = Field(default="", max_length=800)
    transition_hint: str = Field(default="", max_length=120)
    art_direction_ref: Optional[ArtDirectionRef] = None
    art_direction_version: Optional[ArtDirectionVersion] = None
    reference_policy_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    character_refs: List[AssetRef] = Field(max_length=8)
    character_versions: List[AssetVersion] = Field(max_length=8)
    scene_ref: SceneAssetRef
    scene_version: SceneAssetVersion
    prop_clue_refs: List[PropOrClueAssetRef] = Field(max_length=16)
    prop_clue_versions: List[PropOrClueAssetVersion] = Field(max_length=16)
    image_references: List[ShotImageReference] = Field(max_length=25)
    warning_codes: List[ShotImageWarningCode] = Field(max_length=3)
    dropped_reference_count: int = Field(ge=0, le=25)
    blocked_reasons: List[ShotImageBlockedReason] = Field(max_length=8)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("warning_codes", "blocked_reasons", mode="before")
    @classmethod
    def _shot_image_codes_are_unique_lists(cls, value: Any, info: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be unique")
        return value

    @field_validator("dropped_reference_count", mode="before")
    @classmethod
    def _dropped_reference_count_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("dropped_reference_count must be a strict integer")
        return value

    @model_validator(mode="after")
    def _shot_image_request_is_consistent(self) -> "ShotImageRequestSpec":
        if (self.status == "blocked") != bool(self.blocked_reasons):
            raise ValueError("shot image request status does not match blocked reasons")
        if [item.position for item in self.image_references] != list(
            range(1, len(self.image_references) + 1)
        ):
            raise ValueError("shot image reference positions must be contiguous")
        ref_keys = [(item.kind, item.asset_id) for item in self.image_references]
        if len(ref_keys) != len(set(ref_keys)):
            raise ValueError("shot image references must be unique")
        character_pairs = [
            (item.asset_id, item.asset_version_id, item.version_fingerprint)
            for item in self.character_refs
        ]
        character_version_pairs = [
            (item.asset_id, item.asset_version_id, item.version_fingerprint)
            for item in self.character_versions
        ]
        if character_pairs != character_version_pairs:
            raise ValueError("shot image character refs do not match exact versions")
        if [item.artifact_sha256 for item in self.character_refs] != [
            item.artifact.sha256 if item.artifact is not None else None
            for item in self.character_versions
        ]:
            raise ValueError("shot image character refs do not match exact artifacts")
        if self.scene_ref.scene_id != self.scene_version.scene_id or (
            self.scene_ref.scene_version_id != self.scene_version.scene_version_id
            or self.scene_ref.version_fingerprint
            != self.scene_version.version_fingerprint
            or self.scene_ref.artifact_sha256
            != (
                self.scene_version.artifact.sha256
                if self.scene_version.artifact is not None
                else None
            )
        ):
            raise ValueError("shot image scene ref does not match its exact version")
        prop_pairs = [
            (item.asset_id, item.asset_version_id, item.version_fingerprint)
            for item in self.prop_clue_refs
        ]
        version_pairs = [
            (item.asset_id, item.asset_version_id, item.version_fingerprint)
            for item in self.prop_clue_versions
        ]
        if prop_pairs != version_pairs:
            raise ValueError("shot image prop/clue refs do not match exact versions")
        if [item.artifact_sha256 for item in self.prop_clue_refs] != [
            item.artifact.sha256 if item.artifact is not None else None
            for item in self.prop_clue_versions
        ]:
            raise ValueError("shot image prop/clue refs do not match exact artifacts")
        if (self.art_direction_ref is None) != (self.art_direction_version is None):
            raise ValueError("art direction ref and exact version must be present together")
        if self.art_direction_ref is not None:
            version = self.art_direction_version
            assert version is not None
            if (
                self.art_direction_ref.art_direction_id != version.art_direction_id
                or self.art_direction_ref.version_id != version.version_id
                or self.art_direction_ref.fingerprint != version.version_fingerprint
            ):
                raise ValueError("art direction ref does not match its exact version")
        expected_references: list[dict[str, Any]] = []
        missing_character = False
        for version in self.character_versions:
            if version.artifact is None:
                missing_character = True
                continue
            expected_references.append(
                {
                    "kind": "character",
                    "asset_id": version.asset_id,
                    "asset_version_id": version.asset_version_id,
                    "version_fingerprint": version.version_fingerprint,
                    "artifact_path": version.artifact.path,
                    "artifact_sha256": version.artifact.sha256,
                    "artifact_size_bytes": version.artifact.size_bytes,
                }
            )
        scene_missing = self.scene_version.artifact is None
        if not scene_missing:
            artifact = self.scene_version.artifact
            assert artifact is not None
            expected_references.append(
                {
                    "kind": "scene",
                    "asset_id": self.scene_version.scene_id,
                    "asset_version_id": self.scene_version.scene_version_id,
                    "version_fingerprint": self.scene_version.version_fingerprint,
                    "artifact_path": artifact.path,
                    "artifact_sha256": artifact.sha256,
                    "artifact_size_bytes": artifact.size_bytes,
                }
            )
        prop_missing = False
        for version in self.prop_clue_versions:
            if version.artifact is None:
                prop_missing = True
                continue
            expected_references.append(
                {
                    "kind": version.spec.kind,
                    "asset_id": version.asset_id,
                    "asset_version_id": version.asset_version_id,
                    "version_fingerprint": version.version_fingerprint,
                    "artifact_path": version.artifact.path,
                    "artifact_sha256": version.artifact.sha256,
                    "artifact_size_bytes": version.artifact.size_bytes,
                }
            )
        actual_references = [
            item.model_dump(exclude={"position"}) for item in self.image_references
        ]
        if actual_references != expected_references[: len(actual_references)]:
            raise ValueError("shot image references are not an exact priority prefix")
        expected_dropped = len(expected_references) - len(actual_references)
        if expected_dropped != self.dropped_reference_count:
            raise ValueError("shot image dropped reference count is invalid")
        expected_warnings: list[str] = []
        if scene_missing:
            expected_warnings.append("scene_artifact_missing")
        if prop_missing:
            expected_warnings.append("prop_clue_artifact_missing")
        if expected_dropped:
            expected_warnings.append("reference_limit_exceeded")
        if self.warning_codes != expected_warnings:
            raise ValueError("shot image warning codes are invalid")
        expected_blocked = ["character_artifact_missing"] if missing_character else []
        if self.blocked_reasons != expected_blocked:
            raise ValueError("shot image blocked reasons are invalid")
        expected_status = "blocked" if expected_blocked else "assembled"
        if self.status != expected_status:
            raise ValueError("shot image request status is invalid")
        payload = self.model_dump(exclude={"request_fingerprint"})
        if _canonical_sha256(payload) != self.request_fingerprint:
            raise ValueError("shot image request fingerprint is invalid")
        return self


class EpisodeShotImagePlan(BaseModel):
    """Episode-level frozen C1 inputs, independent of provider task state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-image-plan-v1"] = "shot-image-plan-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    used_character_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    art_direction_version_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    scene_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    prop_clue_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    reference_policy: ShotImageReferencePolicy
    character_binding_revision: int = Field(ge=0, le=2_147_483_647)
    character_binding_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    character_bindings: List[ShotCharacterBinding] = Field(min_length=1, max_length=100)
    shot_specs: List[ShotImageRequestSpec] = Field(min_length=1, max_length=100)
    plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "season_no",
        "character_binding_revision",
        mode="before",
    )
    @classmethod
    def _shot_image_plan_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_image_episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _shot_image_plan_is_consistent(self) -> "EpisodeShotImagePlan":
        binding_ids = [item.shot_id for item in self.character_bindings]
        spec_ids = [item.shot_id for item in self.shot_specs]
        if len(binding_ids) != len(set(binding_ids)) or binding_ids != spec_ids:
            raise ValueError("shot image bindings and specs must share one stable order")
        for binding, spec in zip(self.character_bindings, self.shot_specs):
            if binding.source_fingerprint != spec.source_fingerprint:
                raise ValueError("shot image binding source does not match request source")
            if binding.character_ids != [item.asset_id for item in spec.character_refs]:
                raise ValueError("shot image character refs do not match explicit binding")
            if (
                spec.reference_policy_fingerprint
                != self.reference_policy.policy_fingerprint
            ):
                raise ValueError("shot image request uses another reference policy")
            spec_art_fingerprint = (
                spec.art_direction_version.version_fingerprint
                if spec.art_direction_version is not None
                else None
            )
            if spec_art_fingerprint != self.art_direction_version_fingerprint:
                raise ValueError("shot image request uses another art direction")
            raw_reference_count = sum(
                item.artifact is not None for item in spec.character_versions
            )
            raw_reference_count += int(spec.scene_version.artifact is not None)
            raw_reference_count += sum(
                item.artifact is not None for item in spec.prop_clue_versions
            )
            if len(spec.image_references) != min(
                raw_reference_count,
                self.reference_policy.max_reference_images,
            ):
                raise ValueError("shot image request does not apply the reference limit")
        binding_payload = [
            {"shot_id": item.shot_id, "character_ids": item.character_ids}
            for item in sorted(self.character_bindings, key=lambda item: item.shot_id)
        ]
        if _canonical_sha256(binding_payload) != self.character_binding_fingerprint:
            raise ValueError("shot image character binding fingerprint is invalid")
        used_versions: dict[str, tuple[AssetRef, AssetVersion]] = {}
        for spec in self.shot_specs:
            for ref, version in zip(spec.character_refs, spec.character_versions):
                previous = used_versions.get(ref.asset_id)
                current = (ref, version)
                if previous is not None and previous != current:
                    raise ValueError("used character dependency changed between shots")
                used_versions.setdefault(ref.asset_id, current)
        used_character_payload = [
            {
                "asset_ref": ref.model_dump(),
                "asset_version": version.model_dump(),
            }
            for ref, version in used_versions.values()
        ]
        if _canonical_sha256(used_character_payload) != self.used_character_fingerprint:
            raise ValueError("used character fingerprint is invalid")
        payload = self.model_dump(exclude={"plan_fingerprint"})
        if _canonical_sha256(payload) != self.plan_fingerprint:
            raise ValueError("shot image plan fingerprint is invalid")
        return self


ShotImageCandidateSource = Literal["local_png"]
ShotImageSourceStatus = Literal["assembled", "blocked"]


class ShotImageArtifact(BaseModel):
    """One bounded local PNG artifact owned by the C2 candidate store."""

    model_config = ConfigDict(extra="forbid", strict=True)

    media_type: Literal["image/png"] = "image/png"
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)

    @field_validator("path", mode="before")
    @classmethod
    def _candidate_artifact_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("shot image candidate path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"outputs/episodes/episode_[0-9]{2,3}\.shot_images/"
                r"shot_[0-9a-f]{24}/sic_[0-9a-f]{24}\.png",
                value,
            )
            is None
        ):
            raise ValueError("shot image candidate path must stay in its artifact root")
        return value

    @field_validator("size_bytes", "width", "height", mode="before")
    @classmethod
    def _candidate_artifact_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _candidate_artifact_is_bounded(self) -> "ShotImageArtifact":
        if self.width * self.height > 40_000_000:
            raise ValueError("shot image candidate pixel count exceeds its limit")
        return self


class ShotImageCandidate(BaseModel):
    """One immutable C2 image candidate bound to its exact C1 request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_kind: ShotImageCandidateSource = "local_png"
    artifact: ShotImageArtifact
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _candidate_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _candidate_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _candidate_is_content_addressed(self) -> "ShotImageCandidate":
        payload = self.model_dump(exclude={"candidate_id", "candidate_fingerprint"})
        payload["artifact"] = dict(payload["artifact"])
        payload["artifact"].pop("path", None)
        fingerprint = _canonical_sha256(payload)
        if self.candidate_fingerprint != fingerprint:
            raise ValueError("shot image candidate fingerprint is invalid")
        if self.candidate_id != f"sic_{fingerprint[:24]}":
            raise ValueError("shot image candidate id is invalid")
        expected_path = (
            f"outputs/episodes/episode_{self.episode_no:02d}.shot_images/"
            f"{self.shot_id}/{self.candidate_id}.png"
        )
        if self.artifact.path != expected_path:
            raise ValueError("shot image candidate artifact path is not canonical")
        return self


class DirectShotImageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["direct"] = "direct"
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class PreviousTailShotImageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["previous_tail"] = "previous_tail"
    source_shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_tail_revision: int = Field(ge=1, le=2_147_483_647)
    target_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("source_tail_revision", mode="before")
    @classmethod
    def _source_tail_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("source_tail_revision must be a strict integer")
        return value


class NoTailShotImageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["none"] = "none"


FirstShotImageBinding = Annotated[
    Union[DirectShotImageBinding, PreviousTailShotImageBinding],
    Field(discriminator="kind"),
]
TailShotImageBinding = Annotated[
    Union[DirectShotImageBinding, NoTailShotImageBinding],
    Field(discriminator="kind"),
]


class ShotImageCandidatePool(BaseModel):
    """Append-only candidates plus explicit frame selections for one shot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_status: ShotImageSourceStatus
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    candidates: List[ShotImageCandidate] = Field(max_length=32)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    tail_binding_revision: int = Field(ge=0, le=2_147_483_647)
    last_selection_request_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    first_binding: Optional[FirstShotImageBinding] = None
    tail_binding: TailShotImageBinding
    pool_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("candidates", mode="before")
    @classmethod
    def _candidate_pool_list_is_strict(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot image candidates must be a list")
        return value

    @field_validator("selection_revision", "tail_binding_revision", mode="before")
    @classmethod
    def _candidate_pool_revisions_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _candidate_pool_is_consistent(self) -> "ShotImageCandidatePool":
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("shot image candidate ids must be unique")
        by_id = {item.candidate_id: item for item in self.candidates}
        for candidate in self.candidates:
            if candidate.shot_id != self.shot_id:
                raise ValueError("shot image candidate belongs to another shot")
        for binding in (self.first_binding, self.tail_binding):
            if isinstance(binding, DirectShotImageBinding):
                candidate = by_id.get(binding.candidate_id)
                if (
                    candidate is None
                    or candidate.candidate_fingerprint
                    != binding.candidate_fingerprint
                ):
                    raise ValueError("direct shot image binding is not an exact candidate")
        payload = self.model_dump(exclude={"pool_fingerprint"})
        if _canonical_sha256(payload) != self.pool_fingerprint:
            raise ValueError("shot image candidate pool fingerprint is invalid")
        return self


class EpisodeShotImageCandidateManifest(BaseModel):
    """Episode-scoped C2 candidate, selection, and first/tail binding truth."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-image-candidates-v1"] = (
        "shot-image-candidates-v1"
    )
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shots: List[ShotImageCandidatePool] = Field(min_length=1, max_length=100)
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _candidate_manifest_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _candidate_manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _candidate_manifest_is_consistent(
        self,
    ) -> "EpisodeShotImageCandidateManifest":
        shot_ids = [item.shot_id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot image candidate manifest shot ids must be unique")
        for index, pool in enumerate(self.shots):
            for candidate in pool.candidates:
                if (
                    candidate.season_no != self.season_no
                    or candidate.episode_no != self.episode_no
                ):
                    raise ValueError("shot image candidate belongs to another episode")
            lineage = pool.first_binding
            if isinstance(lineage, PreviousTailShotImageBinding):
                source_pool = next(
                    (
                        item
                        for item in self.shots
                        if item.shot_id == lineage.source_shot_id
                    ),
                    None,
                )
                if source_pool is not None:
                    previous = {
                        item.candidate_id: item for item in source_pool.candidates
                    }.get(lineage.candidate_id)
                    if (
                        previous is None
                        or previous.candidate_fingerprint
                        != lineage.candidate_fingerprint
                    ):
                        raise ValueError("shot image lineage is not an exact source candidate")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("shot image candidate manifest fingerprint is invalid")
        return self


ShotImageCoverageStatus = Literal["ready", "incomplete", "stale", "blocked_source"]


class ShotImageCoverageReport(BaseModel):
    """Deterministic C2 first-frame coverage and continuity projection."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_plan_matches: bool
    status: ShotImageCoverageStatus
    required_shot_ids: List[str] = Field(min_length=1, max_length=100)
    covered_shot_ids: List[str] = Field(max_length=100)
    missing_first_shot_ids: List[str] = Field(max_length=100)
    blocked_source_shot_ids: List[str] = Field(max_length=100)
    stale_candidate_shot_ids: List[str] = Field(max_length=100)
    broken_lineage_shot_ids: List[str] = Field(max_length=100)
    coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _coverage_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("source_plan_matches", mode="before")
    @classmethod
    def _coverage_source_match_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("source_plan_matches must be bool")
        return value

    @field_validator(
        "required_shot_ids",
        "covered_shot_ids",
        "missing_first_shot_ids",
        "blocked_source_shot_ids",
        "stale_candidate_shot_ids",
        "broken_lineage_shot_ids",
        mode="before",
    )
    @classmethod
    def _coverage_shot_ids_are_unique(cls, value: Any, info: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        if len(value) != len(set(value)) or any(
            not isinstance(item, str) or re.fullmatch(_SHOT_ID_PATTERN, item) is None
            for item in value
        ):
            raise ValueError(f"{info.field_name} must contain unique shot ids")
        return value

    @model_validator(mode="after")
    def _coverage_is_content_addressed(self) -> "ShotImageCoverageReport":
        required = set(self.required_shot_ids)
        categories = (
            self.covered_shot_ids,
            self.missing_first_shot_ids,
            self.blocked_source_shot_ids,
            self.stale_candidate_shot_ids,
            self.broken_lineage_shot_ids,
        )
        if any(not set(items).issubset(required) for items in categories):
            raise ValueError("shot image coverage contains an unknown shot")
        category_sets = [set(items) for items in categories]
        if any(
            category_sets[left] & category_sets[right]
            for left in range(len(category_sets))
            for right in range(left + 1, len(category_sets))
        ) or set().union(*category_sets) != required:
            raise ValueError("shot image coverage categories must partition required shots")
        if self.blocked_source_shot_ids:
            expected_status = "blocked_source"
        elif (
            not self.source_plan_matches
            or self.stale_candidate_shot_ids
            or self.broken_lineage_shot_ids
        ):
            expected_status = "stale"
        elif self.missing_first_shot_ids:
            expected_status = "incomplete"
        else:
            expected_status = "ready"
        if self.status != expected_status:
            raise ValueError("shot image coverage status is inconsistent")
        payload = self.model_dump(exclude={"coverage_fingerprint"})
        if _canonical_sha256(payload) != self.coverage_fingerprint:
            raise ValueError("shot image coverage fingerprint is invalid")
        return self


AudioPolicy = Literal[
    "silent",
    "narration_only",
    "dialogue_only",
    "mixed",
]


class NarrationSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["narration"] = "narration"
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    sequence: int = Field(ge=1, le=200)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    text: str = Field(min_length=1, max_length=220)


class DialogueSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["dialogue"] = "dialogue"
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    sequence: int = Field(ge=1, le=200)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    text: str = Field(min_length=1, max_length=120)
    speaker_character_id: Literal[None] = None


SpokenSegment = Annotated[
    Union[NarrationSegment, DialogueSegment],
    Field(discriminator="kind"),
]


class RenderShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_shot_no: int = Field(ge=1, le=100)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    beat: str = Field(default="", max_length=80)
    shot_size: ShotSize
    camera_movement: CameraMovement
    target_duration_seconds: int = Field(ge=1, le=30)
    visual_action: str = Field(min_length=1, max_length=500)
    image_prompt: str = Field(default="", max_length=800)
    transition_hint: str = Field(default="", max_length=120)
    spoken_segment_ids: List[str] = Field(default_factory=list, max_length=2)
    audio_policy: AudioPolicy
    is_highlight: bool = False
    source_event_ids: List[str] = Field(default_factory=list, max_length=64)

    @field_validator("spoken_segment_ids", mode="before")
    @classmethod
    def _spoken_ids_are_unique(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("spoken_segment_ids must be a list")
        if any(
            not isinstance(item, str)
            or re.fullmatch(_SEGMENT_ID_PATTERN, item) is None
            for item in value
        ):
            raise ValueError("spoken_segment_ids contain an invalid id")
        if len(value) != len(set(value)):
            raise ValueError("spoken_segment_ids must be unique")
        return value

    @field_validator("source_event_ids", mode="before")
    @classmethod
    def _shot_event_ids_are_unique(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("source_event_ids must be a list")
        if any(not isinstance(item, str) or not item or len(item) > 80 for item in value):
            raise ValueError("source_event_ids contain an invalid id")
        if len(value) != len(set(value)):
            raise ValueError("source_event_ids must be unique")
        return value


class RenderPlan(BaseModel):
    """Canonical creative-to-render contract for one approved episode."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["render-plan-v1"] = "render-plan-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    title: str = Field(default="", max_length=120)
    target_duration_seconds: int = Field(ge=1, le=300)
    creative_revision: str = Field(pattern=_SHA256_PATTERN)
    creative_revision_version: int = Field(ge=1, le=2)
    creative_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_episode_sha256: str = Field(pattern=_SHA256_PATTERN)
    frozen_character_ids: List[str] = Field(min_length=1, max_length=8)
    character_projection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    art_direction_ref: Optional[ArtDirectionRef] = None
    art_direction_resolution: Optional[ArtDirectionResolution] = None
    shots: List[RenderShot] = Field(min_length=1, max_length=100)
    spoken_segments: List[SpokenSegment] = Field(default_factory=list, max_length=200)
    source_event_ids: List[str] = Field(default_factory=list, max_length=256)
    plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _render_episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("creative_revision_version", mode="before")
    @classmethod
    def _render_revision_version_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value not in (1, 2):
            raise ValueError("creative_revision_version must be 1 or 2")
        return value

    @field_validator("frozen_character_ids", mode="before")
    @classmethod
    def _render_character_ids_are_strict(cls, value: Any) -> List[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("frozen_character_ids must be a non-empty list")
        if any(
            not isinstance(item, str) or re.fullmatch(r"c\d{3}", item) is None
            for item in value
        ):
            raise ValueError("frozen_character_ids contain an invalid id")
        if len(value) != len(set(value)):
            raise ValueError("frozen_character_ids must be unique")
        return value

    @field_validator("source_event_ids", mode="before")
    @classmethod
    def _plan_event_ids_are_unique(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("source_event_ids must be a list")
        if any(not isinstance(item, str) or not item or len(item) > 80 for item in value):
            raise ValueError("source_event_ids contain an invalid id")
        if len(value) != len(set(value)):
            raise ValueError("source_event_ids must be unique")
        return value

    @model_validator(mode="after")
    def _render_plan_is_internally_consistent(self) -> "RenderPlan":
        if self.art_direction_resolution is not None:
            resolution = self.art_direction_resolution
            if (
                self.art_direction_ref != resolution.ref
                or resolution.season_no != self.season_no
                or resolution.episode_no != self.episode_no
            ):
                raise ValueError(
                    "render plan art direction resolution is inconsistent"
                )
        shot_ids = [shot.shot_id for shot in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("render shot ids must be unique")
        source_numbers = [shot.source_shot_no for shot in self.shots]
        if len(source_numbers) != len(set(source_numbers)):
            raise ValueError("source shot numbers must be unique")

        segment_ids = [segment.segment_id for segment in self.spoken_segments]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("spoken segment ids must be unique")
        if [segment.sequence for segment in self.spoken_segments] != list(
            range(1, len(self.spoken_segments) + 1)
        ):
            raise ValueError("spoken segment sequence must be contiguous from 1")

        segment_by_id = {segment.segment_id: segment for segment in self.spoken_segments}
        referenced: List[str] = []
        for segment in self.spoken_segments:
            if segment.shot_id not in set(shot_ids):
                raise ValueError("spoken segment refers to an unknown shot")
            if isinstance(segment, DialogueSegment) and segment.speaker_character_id is not None:
                raise ValueError("render plan v1 dialogue speaker must remain unresolved")

        for shot in self.shots:
            kinds: List[str] = []
            for segment_id in shot.spoken_segment_ids:
                segment = segment_by_id.get(segment_id)
                if segment is None or segment.shot_id != shot.shot_id:
                    raise ValueError("render shot refers to an invalid spoken segment")
                kinds.append(segment.kind)
                referenced.append(segment_id)
            if len(kinds) != len(set(kinds)):
                raise ValueError("a render shot may contain at most one segment per kind")
            kind_set = set(kinds)
            valid_policy = {
                frozenset(): {"silent"},
                frozenset({"narration"}): {"narration_only"},
                frozenset({"dialogue"}): {"dialogue_only"},
                frozenset({"narration", "dialogue"}): {"mixed"},
            }
            if shot.audio_policy not in valid_policy[frozenset(kind_set)]:
                raise ValueError("audio policy does not match spoken segments")
        if referenced != segment_ids:
            raise ValueError("spoken segments must be referenced once in plan order")

        payload = self.model_dump(exclude={"plan_fingerprint"})
        valid_fingerprint = _canonical_sha256(payload) == self.plan_fingerprint
        if not valid_fingerprint and self.art_direction_resolution is None:
            legacy_payload = dict(payload)
            legacy_payload.pop("art_direction_resolution", None)
            valid_fingerprint = (
                _canonical_sha256(legacy_payload) == self.plan_fingerprint
            )
        if not valid_fingerprint:
            raise ValueError("render plan fingerprint does not match its payload")
        return self


_VISUAL_OVERRIDE_VERSION_ID_PATTERN = r"^vo_[0-9a-f]{24}$"


class VisualOverrideSpec(BaseModel):
    """Visual-only shot adjustments that never mutate creative facts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    camera_movement: Optional[CameraMovement] = None
    lighting: Optional[str] = Field(default=None, max_length=120)
    negative_prompt: Optional[str] = Field(default=None, max_length=400)
    transition: Optional[str] = Field(default=None, max_length=120)

    @field_validator("lighting", "negative_prompt", "transition", mode="before")
    @classmethod
    def _visual_override_text_is_canonical(
        cls,
        value: Any,
        info: Any,
    ) -> Optional[str]:
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError(f"{info.field_name} must be canonical bounded text")
        return value

    @model_validator(mode="after")
    def _visual_override_is_not_empty(self) -> "VisualOverrideSpec":
        if all(
            value is None
            for value in (
                self.camera_movement,
                self.lighting,
                self.negative_prompt,
                self.transition,
            )
        ):
            raise ValueError("visual override must set at least one visual-only field")
        return self


VisualOverrideSourceKind = Literal["manual", "ai_suggestion", "imported"]


class VisualOverrideVersion(BaseModel):
    """One immutable visual-only candidate bound to an exact RenderShot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version_id: str = Field(pattern=_VISUAL_OVERRIDE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    derived_from: Optional[str] = Field(
        default=None,
        pattern=_VISUAL_OVERRIDE_VERSION_ID_PATTERN,
    )
    source_kind: VisualOverrideSourceKind
    spec: VisualOverrideSpec

    @model_validator(mode="after")
    def _visual_override_version_is_content_addressed(
        self,
    ) -> "VisualOverrideVersion":
        if self.derived_from == self.version_id:
            raise ValueError("visual override version cannot derive from itself")
        payload = self.model_dump(exclude={"version_id", "version_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if fingerprint != self.version_fingerprint:
            raise ValueError("visual override version fingerprint is invalid")
        if self.version_id != f"vo_{fingerprint[:24]}":
            raise ValueError("visual override version id is invalid")
        return self


class VisualOverrideSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    version_id: str = Field(pattern=_VISUAL_OVERRIDE_VERSION_ID_PATTERN)


class VisualOverrideCatalog(BaseModel):
    """Episode candidates plus explicit selections for one RenderPlan."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    versions: List[VisualOverrideVersion] = Field(default_factory=list, max_length=512)
    selections: List[VisualOverrideSelection] = Field(
        default_factory=list,
        max_length=100,
    )
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    catalog_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _visual_override_episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("season_no", "selection_revision", mode="before")
    @classmethod
    def _visual_override_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _visual_override_catalog_is_consistent(self) -> "VisualOverrideCatalog":
        version_ids = [item.version_id for item in self.versions]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("visual override version ids must be unique")
        if [
            (item.shot_id, item.version_id) for item in self.versions
        ] != sorted((item.shot_id, item.version_id) for item in self.versions):
            raise ValueError("visual override versions must use canonical order")
        version_by_id = {item.version_id: item for item in self.versions}
        for item in self.versions:
            if item.derived_from is not None:
                parent = version_by_id.get(item.derived_from)
                if parent is None or parent.shot_id != item.shot_id:
                    raise ValueError("visual override parent is invalid")
        parents = {
            item.version_id: item.derived_from for item in self.versions
        }
        for version_id in parents:
            seen: set[str] = set()
            current: Optional[str] = version_id
            while current is not None:
                if current in seen:
                    raise ValueError("visual override derivation contains a cycle")
                seen.add(current)
                current = parents[current]
        shot_ids = [item.shot_id for item in self.selections]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("visual override selections must be unique per shot")
        if shot_ids != sorted(shot_ids):
            raise ValueError("visual override selections must use canonical order")
        for selection in self.selections:
            version = version_by_id.get(selection.version_id)
            if version is None or version.shot_id != selection.shot_id:
                raise ValueError("visual override selection is invalid")
        payload = self.model_dump(exclude={"catalog_fingerprint"})
        if _canonical_sha256(payload) != self.catalog_fingerprint:
            raise ValueError("visual override catalog fingerprint is invalid")
        return self


class SelectedVisualOverride(BaseModel):
    """Effective selected candidate embedded for deterministic consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    version_id: str = Field(pattern=_VISUAL_OVERRIDE_VERSION_ID_PATTERN)
    version_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    spec: VisualOverrideSpec


class EpisodeVisualOverrideManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    selected_overrides: List[SelectedVisualOverride] = Field(
        default_factory=list,
        max_length=100,
    )
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _visual_manifest_episode_no_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("season_no", "selection_revision", mode="before")
    @classmethod
    def _visual_manifest_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _visual_manifest_is_content_addressed(
        self,
    ) -> "EpisodeVisualOverrideManifest":
        shot_ids = [item.shot_id for item in self.selected_overrides]
        if shot_ids != sorted(shot_ids) or len(shot_ids) != len(set(shot_ids)):
            raise ValueError("selected visual overrides must use unique shot-id order")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("visual override manifest fingerprint is invalid")
        return self


class VisualOverrideState(BaseModel):
    """Single-file atomic state for catalog plus its derived manifest."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    catalog: VisualOverrideCatalog
    manifest: EpisodeVisualOverrideManifest
    selection_transitions: List["VisualOverrideSelectionTransition"] = Field(
        default_factory=list,
        max_length=512,
    )
    state_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _visual_override_state_is_consistent(self) -> "VisualOverrideState":
        if (
            self.catalog.season_no != self.manifest.season_no
            or self.catalog.episode_no != self.manifest.episode_no
            or self.catalog.render_plan_fingerprint
            != self.manifest.render_plan_fingerprint
            or self.catalog.selection_revision != self.manifest.selection_revision
        ):
            raise ValueError("visual override state identity is inconsistent")
        transition_ids = [
            item.transition_id for item in self.selection_transitions
        ]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("visual override transition ids must be unique")
        after_revisions = [
            item.after_selection_revision for item in self.selection_transitions
        ]
        if after_revisions != sorted(set(after_revisions)):
            raise ValueError(
                "visual override transitions must use increasing revisions"
            )
        if (
            after_revisions
            and after_revisions[-1] > self.catalog.selection_revision
        ):
            raise ValueError("visual override transition revision is inconsistent")
        for previous, current in zip(
            self.selection_transitions,
            self.selection_transitions[1:],
        ):
            if (
                previous.after_selection_revision
                == current.before_selection_revision
                and previous.after_manifest != current.before_manifest
            ):
                raise ValueError(
                    "visual override transition manifest chain is inconsistent"
                )
        version_by_id = {
            item.version_id: item for item in self.catalog.versions
        }
        for transition in self.selection_transitions:
            for version in (
                transition.impact.old_version,
                transition.impact.new_version,
            ):
                if (
                    version is not None
                    and version_by_id.get(version.version_id) != version
                ):
                    raise ValueError(
                        "visual override transition version is not in the catalog"
                    )
            for manifest in (
                transition.before_manifest,
                transition.after_manifest,
            ):
                if (
                    manifest.season_no != self.catalog.season_no
                    or manifest.episode_no != self.catalog.episode_no
                    or manifest.render_plan_fingerprint
                    != self.catalog.render_plan_fingerprint
                ):
                    raise ValueError(
                        "visual override transition manifest belongs to another state"
                    )
                for selected in manifest.selected_overrides:
                    version = version_by_id.get(selected.version_id)
                    if version is None or selected.model_dump() != {
                        "shot_id": version.shot_id,
                        "source_fingerprint": version.source_fingerprint,
                        "version_id": version.version_id,
                        "version_fingerprint": version.version_fingerprint,
                        "spec": version.spec.model_dump(),
                    }:
                        raise ValueError(
                            "visual override transition manifest version "
                            "is not in the catalog"
                        )
        if (
            self.selection_transitions
            and self.selection_transitions[-1].after_selection_revision
            == self.catalog.selection_revision
        ):
            transition = self.selection_transitions[-1]
            if transition.after_manifest != self.manifest:
                raise ValueError(
                    "latest visual override transition manifest is inconsistent"
                )
        payload = self.model_dump(exclude={"state_fingerprint"})
        if _canonical_sha256(payload) != self.state_fingerprint:
            raise ValueError("visual override state fingerprint is invalid")
        return self


StaleDependencyChange = Literal[
    "creative_revision",
    "override_camera",
    "override_lighting",
    "override_negative_prompt",
    "override_transition",
    "bgm_selection",
    "selected_first_frame",
]
StaleDependencyNode = Literal[
    "render_plan",
    "shot_image_request",
    "shot_image_candidate",
    "shot_video_plan",
    "shot_video_candidate",
    "audio_plan",
    "timeline",
    "composite",
    "edit_export",
    "media_qa",
]

DRAMA_STALE_DEPENDENCY_NODES: tuple[StaleDependencyNode, ...] = (
    "render_plan",
    "shot_image_request",
    "shot_image_candidate",
    "shot_video_plan",
    "shot_video_candidate",
    "audio_plan",
    "timeline",
    "composite",
    "edit_export",
    "media_qa",
)
DRAMA_STALE_DEPENDENCY_ROWS: Dict[
    StaleDependencyChange,
    tuple[StaleDependencyNode, ...],
] = {
    "creative_revision": DRAMA_STALE_DEPENDENCY_NODES,
    "override_camera": (
        "shot_image_request",
        "shot_image_candidate",
        "shot_video_plan",
        "shot_video_candidate",
        "timeline",
        "composite",
        "edit_export",
        "media_qa",
    ),
    "override_lighting": (
        "shot_image_request",
        "shot_image_candidate",
        "shot_video_plan",
        "shot_video_candidate",
        "timeline",
        "composite",
        "edit_export",
        "media_qa",
    ),
    "override_negative_prompt": (
        "shot_image_request",
        "shot_image_candidate",
        "shot_video_plan",
        "shot_video_candidate",
        "timeline",
        "composite",
        "edit_export",
        "media_qa",
    ),
    "override_transition": (
        "timeline",
        "composite",
        "edit_export",
        "media_qa",
    ),
    "bgm_selection": ("timeline", "composite", "edit_export", "media_qa"),
    "selected_first_frame": (
        "shot_video_plan",
        "shot_video_candidate",
        "timeline",
        "composite",
        "edit_export",
        "media_qa",
    ),
}
DRAMA_STALE_DEPENDENCY_SCOPES: Dict[
    StaleDependencyChange,
    Literal["episode", "shot"],
] = {
    "creative_revision": "episode",
    "override_camera": "shot",
    "override_lighting": "shot",
    "override_negative_prompt": "shot",
    "override_transition": "shot",
    "bgm_selection": "episode",
    "selected_first_frame": "shot",
}


class StaleDependencyImpact(BaseModel):
    """Versioned, content-addressed result of one dependency invalidation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    matrix_version: Literal["drama-stale-matrix-v1"] = "drama-stale-matrix-v1"
    change: StaleDependencyChange
    scope: Literal["episode", "shot"]
    shot_id: Optional[str] = Field(default=None, pattern=_SHOT_ID_PATTERN)
    affected_nodes: List[StaleDependencyNode] = Field(min_length=1, max_length=10)
    unaffected_nodes: List[StaleDependencyNode] = Field(max_length=10)
    impact_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _stale_dependency_impact_is_consistent(self) -> "StaleDependencyImpact":
        if (self.scope == "shot") != (self.shot_id is not None):
            raise ValueError("stale dependency scope and shot id are inconsistent")
        if (
            len(self.affected_nodes) != len(set(self.affected_nodes))
            or len(self.unaffected_nodes) != len(set(self.unaffected_nodes))
            or set(self.affected_nodes) & set(self.unaffected_nodes)
        ):
            raise ValueError("stale dependency node partition is invalid")
        if (
            set(self.affected_nodes) | set(self.unaffected_nodes)
            != set(DRAMA_STALE_DEPENDENCY_NODES)
        ):
            raise ValueError("stale dependency node partition is incomplete")
        if (
            self.scope != DRAMA_STALE_DEPENDENCY_SCOPES[self.change]
            or self.affected_nodes != list(DRAMA_STALE_DEPENDENCY_ROWS[self.change])
            or self.unaffected_nodes
            != [
                item
                for item in DRAMA_STALE_DEPENDENCY_NODES
                if item not in DRAMA_STALE_DEPENDENCY_ROWS[self.change]
            ]
        ):
            raise ValueError("stale dependency row does not match matrix version")
        payload = self.model_dump(exclude={"impact_fingerprint"})
        if _canonical_sha256(payload) != self.impact_fingerprint:
            raise ValueError("stale dependency impact fingerprint is invalid")
        return self


VisualOverrideChangedField = Literal[
    "camera_movement",
    "lighting",
    "negative_prompt",
    "transition",
]


class VisualOverrideSelectionImpact(BaseModel):
    """Exact old/new selected-spec diff and dependency-union result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    matrix_version: Literal["drama-stale-matrix-v1"] = "drama-stale-matrix-v1"
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    old_version: Optional[VisualOverrideVersion] = None
    new_version: Optional[VisualOverrideVersion] = None
    changed_fields: List[VisualOverrideChangedField] = Field(max_length=4)
    affected_nodes: List[StaleDependencyNode] = Field(max_length=10)
    unaffected_nodes: List[StaleDependencyNode] = Field(max_length=10)
    impact_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _visual_selection_impact_is_consistent(
        self,
    ) -> "VisualOverrideSelectionImpact":
        if (
            self.old_version is not None
            and self.old_version.shot_id != self.shot_id
        ) or (
            self.new_version is not None
            and self.new_version.shot_id != self.shot_id
        ):
            raise ValueError("visual override impact version belongs to another shot")
        old_spec = self.old_version.spec if self.old_version is not None else None
        new_spec = self.new_version.spec if self.new_version is not None else None
        expected_changed_fields = [
            item
            for item in (
                "camera_movement",
                "lighting",
                "negative_prompt",
                "transition",
            )
            if (
                getattr(old_spec, item) if old_spec is not None else None
            )
            != (
                getattr(new_spec, item) if new_spec is not None else None
            )
        ]
        if self.changed_fields != expected_changed_fields:
            raise ValueError("visual override changed fields are not canonical")
        field_changes: Dict[VisualOverrideChangedField, StaleDependencyChange] = {
            "camera_movement": "override_camera",
            "lighting": "override_lighting",
            "negative_prompt": "override_negative_prompt",
            "transition": "override_transition",
        }
        affected_set = {
            node
            for field in self.changed_fields
            for node in DRAMA_STALE_DEPENDENCY_ROWS[field_changes[field]]
        }
        expected_affected = [
            item for item in DRAMA_STALE_DEPENDENCY_NODES if item in affected_set
        ]
        expected_unaffected = [
            item for item in DRAMA_STALE_DEPENDENCY_NODES if item not in affected_set
        ]
        if (
            self.affected_nodes != expected_affected
            or self.unaffected_nodes != expected_unaffected
        ):
            raise ValueError("visual override selection impact is inconsistent")
        payload = self.model_dump(exclude={"impact_fingerprint"})
        if _canonical_sha256(payload) != self.impact_fingerprint:
            raise ValueError("visual override selection impact fingerprint is invalid")
        return self


_VISUAL_OVERRIDE_TRANSITION_ID_PATTERN = r"^vot_[0-9a-f]{24}$"


class VisualOverrideSelectionTransition(BaseModel):
    """Durable receipt atomically committed with a selection mutation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    transition_id: str = Field(pattern=_VISUAL_OVERRIDE_TRANSITION_ID_PATTERN)
    before_state_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    before_selection_revision: int = Field(ge=0, le=2_147_483_647)
    after_selection_revision: int = Field(ge=0, le=2_147_483_647)
    impact: VisualOverrideSelectionImpact
    before_manifest: EpisodeVisualOverrideManifest
    after_manifest: EpisodeVisualOverrideManifest
    transition_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "before_selection_revision",
        "after_selection_revision",
        mode="before",
    )
    @classmethod
    def _visual_transition_revisions_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _visual_transition_is_content_addressed(
        self,
    ) -> "VisualOverrideSelectionTransition":
        old_id = (
            self.impact.old_version.version_id
            if self.impact.old_version is not None
            else None
        )
        new_id = (
            self.impact.new_version.version_id
            if self.impact.new_version is not None
            else None
        )
        if old_id == new_id:
            raise ValueError("no-op visual selection must not create a transition")
        expected_after = self.before_selection_revision + 1
        if self.after_selection_revision != expected_after:
            raise ValueError("visual override transition revision is invalid")
        if self.before_manifest.selection_revision != self.before_selection_revision:
            raise ValueError("visual override transition before revision is invalid")
        if self.after_manifest.selection_revision != self.after_selection_revision:
            raise ValueError("visual override transition manifest revision is invalid")
        if (
            self.before_manifest.season_no != self.after_manifest.season_no
            or self.before_manifest.episode_no != self.after_manifest.episode_no
            or self.before_manifest.render_plan_fingerprint
            != self.after_manifest.render_plan_fingerprint
        ):
            raise ValueError("visual override transition manifest identity changed")
        before_by_shot = {
            item.shot_id: item for item in self.before_manifest.selected_overrides
        }
        after_by_shot = {
            item.shot_id: item for item in self.after_manifest.selected_overrides
        }
        before_selected = before_by_shot.pop(self.impact.shot_id, None)
        after_selected = after_by_shot.pop(self.impact.shot_id, None)
        if before_by_shot != after_by_shot:
            raise ValueError(
                "visual override transition changed an unrelated shot"
            )
        old = self.impact.old_version
        expected = self.impact.new_version
        if old is None:
            if before_selected is not None:
                raise ValueError("visual override transition old target is inconsistent")
        elif (
            before_selected is None
            or before_selected.source_fingerprint != old.source_fingerprint
            or before_selected.version_id != old.version_id
            or before_selected.version_fingerprint != old.version_fingerprint
            or before_selected.spec != old.spec
        ):
            raise ValueError("visual override transition old target is inconsistent")
        if expected is None:
            if after_selected is not None:
                raise ValueError("visual override transition clear was not applied")
        elif (
            after_selected is None
            or after_selected.source_fingerprint != expected.source_fingerprint
            or after_selected.version_id != expected.version_id
            or after_selected.version_fingerprint != expected.version_fingerprint
            or after_selected.spec != expected.spec
        ):
            raise ValueError("visual override transition target is inconsistent")
        payload = self.model_dump(
            exclude={"transition_id", "transition_fingerprint"}
        )
        fingerprint = _canonical_sha256(payload)
        if self.transition_fingerprint != fingerprint:
            raise ValueError("visual override transition fingerprint is invalid")
        if self.transition_id != f"vot_{fingerprint[:24]}":
            raise ValueError("visual override transition id is invalid")
        return self


class VisualOverrideSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: VisualOverrideState
    transition_id: Optional[str] = Field(
        default=None,
        pattern=_VISUAL_OVERRIDE_TRANSITION_ID_PATTERN,
    )
    status: Literal["target_current", "superseded", "no_op"]
    result_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _visual_selection_result_is_content_addressed(
        self,
    ) -> "VisualOverrideSelectionResult":
        transition_ids = {
            item.transition_id for item in self.state.selection_transitions
        }
        if (self.status == "no_op") != (self.transition_id is None):
            raise ValueError("visual override selection result kind is invalid")
        if self.transition_id is not None and self.transition_id not in transition_ids:
            raise ValueError("visual override selection result transition is missing")
        if self.transition_id is not None:
            transition = next(
                item
                for item in self.state.selection_transitions
                if item.transition_id == self.transition_id
            )
            selected_by_shot = {
                item.shot_id: item
                for item in self.state.manifest.selected_overrides
            }
            selected = selected_by_shot.get(transition.impact.shot_id)
            expected = transition.impact.new_version
            is_current = (
                (expected is None and selected is None)
                or (
                    expected is not None
                    and selected is not None
                    and selected.source_fingerprint
                    == expected.source_fingerprint
                    and selected.version_id == expected.version_id
                    and selected.version_fingerprint
                    == expected.version_fingerprint
                    and selected.spec == expected.spec
                )
            )
            expected_status = "target_current" if is_current else "superseded"
            if self.status != expected_status:
                raise ValueError(
                    "visual override selection result status is inconsistent"
                )
        payload = self.model_dump(exclude={"result_fingerprint"})
        if _canonical_sha256(payload) != self.result_fingerprint:
            raise ValueError("visual override selection result fingerprint is invalid")
        return self

    @property
    def manifest(self) -> EpisodeVisualOverrideManifest:
        if self.transition_id is None:
            return self.state.manifest
        return next(
            item.after_manifest
            for item in self.state.selection_transitions
            if item.transition_id == self.transition_id
        )

    @property
    def impact(self) -> VisualOverrideSelectionImpact:
        if self.transition_id is None:
            raise ValueError("no-op visual selection has no stale impact")
        return next(
            item.impact
            for item in self.state.selection_transitions
            if item.transition_id == self.transition_id
        )


ShotImageAttemptStatus = Literal[
    "started",
    "artifact_received",
    "succeeded",
    "timeout",
    "network_error",
    "provider_error",
    "local_error",
]
ShotImageAttemptInspectionState = Literal[
    "needs_attempts",
    "fresh",
    "reconciliation_required",
    "stale",
    "invalid",
]


class ShotImageProviderCapability(BaseModel):
    """Static, content-addressed capability used to lower one C1 request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    backend_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    capability_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
    supports_reference_images: bool
    max_reference_images: int = Field(ge=0, le=25)
    supported_media_types: List[Literal["image/png"]] = Field(
        min_length=1,
        max_length=1,
    )
    response_mode: Literal["sync_png"] = "sync_png"
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("supports_reference_images", mode="before")
    @classmethod
    def _provider_reference_support_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("supports_reference_images must be bool")
        return value

    @field_validator("max_reference_images", mode="before")
    @classmethod
    def _provider_reference_limit_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("max_reference_images must be a strict integer")
        return value

    @field_validator("supported_media_types", mode="before")
    @classmethod
    def _provider_media_types_are_strict(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("supported_media_types must be a list")
        return value

    @model_validator(mode="after")
    def _provider_capability_is_consistent(self) -> "ShotImageProviderCapability":
        if self.supports_reference_images != (self.max_reference_images > 0):
            raise ValueError("provider reference support does not match its limit")
        if self.supported_media_types != ["image/png"]:
            raise ValueError("provider media types must be the canonical PNG list")
        payload = self.model_dump(exclude={"capability_fingerprint"})
        if _canonical_sha256(payload) != self.capability_fingerprint:
            raise ValueError("provider capability fingerprint is invalid")
        return self


class ShotImageAttemptSpec(BaseModel):
    """One provider-neutral, attempt-frozen lowering of a fresh C1 request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    pre_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    backend_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    capability: ShotImageProviderCapability
    prompt_sha256: str = Field(pattern=_SHA256_PATTERN)
    references: List[ShotImageReference] = Field(max_length=25)
    references_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    output_media_type: Literal["image/png"] = "image/png"
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _attempt_spec_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _attempt_spec_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("references", mode="before")
    @classmethod
    def _attempt_references_are_strict(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("attempt references must be a list")
        return value

    @model_validator(mode="after")
    def _attempt_spec_is_consistent(self) -> "ShotImageAttemptSpec":
        if self.backend_id != self.capability.backend_id:
            raise ValueError("attempt backend does not match its capability")
        if len(self.references) > self.capability.max_reference_images:
            raise ValueError("attempt references exceed provider capability")
        if self.references and not self.capability.supports_reference_images:
            raise ValueError("provider does not support attempt references")
        if [item.position for item in self.references] != list(
            range(1, len(self.references) + 1)
        ):
            raise ValueError("attempt references must keep C1 order")
        reference_payload = [item.model_dump() for item in self.references]
        if _canonical_sha256(reference_payload) != self.references_fingerprint:
            raise ValueError("attempt references fingerprint is invalid")
        payload = self.model_dump(exclude={"input_fingerprint"})
        if _canonical_sha256(payload) != self.input_fingerprint:
            raise ValueError("shot image attempt input fingerprint is invalid")
        return self


class ShotImageAttemptArtifactReceipt(BaseModel):
    """Bounded private PNG receipt recorded before candidate publication."""

    model_config = ConfigDict(extra="forbid", strict=True)

    media_type: Literal["image/png"] = "image/png"
    staging_path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("staging_path", mode="before")
    @classmethod
    def _attempt_staging_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("attempt staging path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"logs/drama_shot_images/episode_[0-9]{2,3}/"
                r"shot_[0-9a-f]{24}/sia_[0-9a-f]{24}\.png",
                value,
            )
            is None
        ):
            raise ValueError("attempt staging path must stay in its private root")
        return value

    @field_validator("size_bytes", "width", "height", mode="before")
    @classmethod
    def _attempt_receipt_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _attempt_receipt_is_consistent(self) -> "ShotImageAttemptArtifactReceipt":
        if self.width * self.height > 40_000_000:
            raise ValueError("attempt artifact pixel count exceeds its limit")
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("attempt artifact receipt fingerprint is invalid")
        return self


class ShotImageAttemptRecord(BaseModel):
    """Current durable state for one once-only shot image attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    attempt_id: str = Field(pattern=r"^sia_[0-9a-f]{24}$")
    attempt_no: int = Field(ge=1, le=32)
    spec: ShotImageAttemptSpec
    status: ShotImageAttemptStatus
    staging_path: str = Field(min_length=1, max_length=240)
    artifact_receipt: Optional[ShotImageAttemptArtifactReceipt] = None
    candidate_id: Optional[str] = Field(default=None, pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    post_manifest_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("attempt_no", mode="before")
    @classmethod
    def _attempt_number_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("attempt_no must be a strict integer")
        return value

    @field_validator("staging_path", mode="before")
    @classmethod
    def _attempt_record_staging_path_is_strict(cls, value: Any) -> str:
        return ShotImageAttemptArtifactReceipt._attempt_staging_path_is_strict(value)

    @model_validator(mode="after")
    def _attempt_record_is_consistent(self) -> "ShotImageAttemptRecord":
        basis = {
            "input_fingerprint": self.spec.input_fingerprint,
            "attempt_no": self.attempt_no,
        }
        expected_attempt_id = f"sia_{_canonical_sha256(basis)[:24]}"
        if self.attempt_id != expected_attempt_id:
            raise ValueError("shot image attempt id is invalid")
        expected_path = (
            f"logs/drama_shot_images/episode_{self.spec.episode_no:02d}/"
            f"{self.spec.shot_id}/{self.attempt_id}.png"
        )
        if self.staging_path != expected_path:
            raise ValueError("shot image attempt staging path is not canonical")
        receipt_required = self.status in {"artifact_received", "succeeded"}
        if receipt_required != (self.artifact_receipt is not None):
            raise ValueError("shot image attempt receipt does not match its status")
        if self.artifact_receipt is not None and (
            self.artifact_receipt.staging_path != self.staging_path
        ):
            raise ValueError("shot image attempt receipt uses another staging path")
        candidate_values = (
            self.candidate_id,
            self.candidate_fingerprint,
            self.post_manifest_fingerprint,
        )
        if (self.status == "succeeded") != all(item is not None for item in candidate_values):
            raise ValueError("shot image candidate identity does not match attempt status")
        if self.status != "succeeded" and any(item is not None for item in candidate_values):
            raise ValueError("unfinished shot image attempt cannot bind a candidate")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("shot image attempt record fingerprint is invalid")
        return self


class EpisodeShotImageAttemptLedger(BaseModel):
    """Episode-scoped execution facts; separate from C1 and C2 render truth."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-image-attempts-v1"] = "shot-image-attempts-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    revision: int = Field(ge=0, le=2_147_483_647)
    attempts: List[ShotImageAttemptRecord] = Field(max_length=3200)
    ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "revision", mode="before")
    @classmethod
    def _attempt_ledger_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _attempt_ledger_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("attempts", mode="before")
    @classmethod
    def _attempt_ledger_list_is_strict(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot image attempts must be a list")
        return value

    @model_validator(mode="after")
    def _attempt_ledger_is_consistent(self) -> "EpisodeShotImageAttemptLedger":
        attempt_ids = [item.attempt_id for item in self.attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("shot image attempt ids must be unique")
        per_shot: Dict[str, List[int]] = {}
        for attempt in self.attempts:
            if (
                attempt.spec.season_no != self.season_no
                or attempt.spec.episode_no != self.episode_no
            ):
                raise ValueError("shot image attempt belongs to another episode")
            per_shot.setdefault(attempt.spec.shot_id, []).append(attempt.attempt_no)
        if any(numbers != list(range(1, len(numbers) + 1)) for numbers in per_shot.values()):
            raise ValueError("shot image attempt numbers must be contiguous per shot")
        payload = self.model_dump(exclude={"ledger_fingerprint"})
        if _canonical_sha256(payload) != self.ledger_fingerprint:
            raise ValueError("shot image attempt ledger fingerprint is invalid")
        return self


class ShotImageAttemptInspection(BaseModel):
    """Safe bounded projection of the attempt ledger state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    state: ShotImageAttemptInspectionState
    reasons: List[str] = Field(max_length=16)
    ledger_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    outstanding_attempt_ids: List[str] = Field(max_length=100)

    @field_validator("reasons", "outstanding_attempt_ids", mode="before")
    @classmethod
    def _attempt_inspection_lists_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> List[str]:
        if not isinstance(value, list) or len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be a unique list")
        if info.field_name == "reasons":
            if any(
                not isinstance(item, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) is None
                for item in value
            ):
                raise ValueError("inspection reasons must be bounded codes")
        elif any(
            not isinstance(item, str)
            or re.fullmatch(r"sia_[0-9a-f]{24}", item) is None
            for item in value
        ):
            raise ValueError("outstanding attempt ids are invalid")
        return value


ShotVideoFrameRole = Literal["first", "tail"]
ShotVideoFrameBindingKind = Literal["direct", "previous_tail"]


class ShotVideoFrameRef(BaseModel):
    """Exact selected C2 image artifact frozen as one D1 video frame input."""

    model_config = ConfigDict(extra="forbid", strict=True)

    frame_role: ShotVideoFrameRole
    binding_kind: ShotVideoFrameBindingKind
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    candidate_source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    candidate_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact: ShotImageArtifact
    selection_revision: int = Field(ge=1, le=2_147_483_647)
    source_tail_revision: Optional[int] = Field(
        default=None,
        ge=1,
        le=2_147_483_647,
    )
    target_request_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    frame_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "selection_revision", "source_tail_revision", mode="before")
    @classmethod
    def _shot_video_frame_revisions_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> Optional[int]:
        if value is None and info.field_name == "source_tail_revision":
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_video_frame_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _shot_video_frame_is_consistent(self) -> "ShotVideoFrameRef":
        lineage_values = (
            self.source_tail_revision,
            self.target_request_fingerprint,
        )
        if self.binding_kind == "previous_tail":
            if self.frame_role != "first" or any(item is None for item in lineage_values):
                raise ValueError("previous-tail video frame lineage is incomplete")
        elif self.frame_role == "tail":
            if self.source_tail_revision is None or self.target_request_fingerprint is not None:
                raise ValueError("direct tail frame revision is incomplete")
        elif any(item is not None for item in lineage_values):
            raise ValueError("direct first frame cannot claim tail lineage")
        expected_path = (
            f"outputs/episodes/episode_{self.episode_no:02d}.shot_images/"
            f"{self.source_shot_id}/{self.candidate_id}.png"
        )
        if self.artifact.path != expected_path:
            raise ValueError("shot video frame artifact path is not canonical")
        candidate_payload = {
            "schema_version": 1,
            "season_no": self.season_no,
            "episode_no": self.episode_no,
            "shot_id": self.source_shot_id,
            "source_plan_fingerprint": self.candidate_source_plan_fingerprint,
            "request_fingerprint": self.candidate_request_fingerprint,
            "source_kind": "local_png",
            "artifact": self.artifact.model_dump(),
        }
        candidate_payload["artifact"].pop("path", None)
        candidate_fingerprint = _canonical_sha256(candidate_payload)
        if (
            self.candidate_fingerprint != candidate_fingerprint
            or self.candidate_id != f"sic_{candidate_fingerprint[:24]}"
        ):
            raise ValueError("shot video frame candidate identity is invalid")
        payload = self.model_dump(exclude={"frame_fingerprint"})
        if _canonical_sha256(payload) != self.frame_fingerprint:
            raise ValueError("shot video frame fingerprint is invalid")
        return self


class ShotVideoRequestSpec(BaseModel):
    """Provider-neutral D1 video input for one stable RenderShot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    render_shot_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_image_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=1, le=2_147_483_647)
    target_duration_seconds: int = Field(ge=1, le=30)
    shot_size: ShotSize
    camera_movement: CameraMovement
    visual_action: str = Field(min_length=1, max_length=500)
    image_prompt: str = Field(default="", max_length=800)
    transition_hint: str = Field(default="", max_length=120)
    first_frame: ShotVideoFrameRef
    tail_frame: Optional[ShotVideoFrameRef] = None
    ordered_references: List[ShotImageReference] = Field(max_length=25)
    spec_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("selection_revision", "target_duration_seconds", mode="before")
    @classmethod
    def _shot_video_spec_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("ordered_references", mode="before")
    @classmethod
    def _shot_video_references_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video references must be a list")
        return value

    @model_validator(mode="after")
    def _shot_video_spec_is_consistent(self) -> "ShotVideoRequestSpec":
        if self.first_frame.frame_role != "first":
            raise ValueError("shot video first frame has the wrong role")
        if self.tail_frame is not None and self.tail_frame.frame_role != "tail":
            raise ValueError("shot video tail frame has the wrong role")
        if (
            self.first_frame.selection_revision != self.selection_revision
            or (
                self.tail_frame is not None
                and self.tail_frame.selection_revision != self.selection_revision
            )
        ):
            raise ValueError("shot video frame selection revision is inconsistent")
        if [item.position for item in self.ordered_references] != list(
            range(1, len(self.ordered_references) + 1)
        ):
            raise ValueError("shot video reference positions must be contiguous")
        reference_keys = [(item.kind, item.asset_id) for item in self.ordered_references]
        if len(reference_keys) != len(set(reference_keys)):
            raise ValueError("shot video references must be unique")
        payload = self.model_dump(exclude={"spec_fingerprint"})
        if _canonical_sha256(payload) != self.spec_fingerprint:
            raise ValueError("shot video request fingerprint is invalid")
        return self


class EpisodeShotVideoPlan(BaseModel):
    """Episode-scoped D1 plan; provider execution facts belong to later stages."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-video-plan-v1"] = "shot-video-plan-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_image_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selected_bindings_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    image_coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shot_specs: List[ShotVideoRequestSpec] = Field(min_length=1, max_length=100)
    plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _shot_video_plan_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_video_plan_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("shot_specs", mode="before")
    @classmethod
    def _shot_video_specs_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video specs must be a list")
        return value

    @model_validator(mode="after")
    def _shot_video_plan_is_consistent(self) -> "EpisodeShotVideoPlan":
        shot_ids = [item.shot_id for item in self.shot_specs]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot video plan shot ids must be unique")
        for index, spec in enumerate(self.shot_specs):
            frames = [spec.first_frame]
            if spec.tail_frame is not None:
                frames.append(spec.tail_frame)
            if any(
                frame.season_no != self.season_no
                or frame.episode_no != self.episode_no
                for frame in frames
            ):
                raise ValueError("shot video frame belongs to another image plan")
            if spec.first_frame.binding_kind == "direct":
                if (
                    spec.first_frame.source_shot_id != spec.shot_id
                    or spec.first_frame.candidate_request_fingerprint
                    != spec.shot_image_request_fingerprint
                ):
                    raise ValueError("direct first frame belongs to another shot")
            else:
                previous_tail = self.shot_specs[index - 1].tail_frame
                if (
                    index == 0
                    or spec.first_frame.source_shot_id
                    != self.shot_specs[index - 1].shot_id
                    or spec.first_frame.target_request_fingerprint
                    != spec.shot_image_request_fingerprint
                    or previous_tail is None
                    or previous_tail.candidate_id != spec.first_frame.candidate_id
                    or previous_tail.candidate_fingerprint
                    != spec.first_frame.candidate_fingerprint
                    or previous_tail.candidate_request_fingerprint
                    != spec.first_frame.candidate_request_fingerprint
                    or previous_tail.candidate_request_fingerprint
                    != self.shot_specs[index - 1].shot_image_request_fingerprint
                    or previous_tail.artifact != spec.first_frame.artifact
                    or previous_tail.source_tail_revision
                    != spec.first_frame.source_tail_revision
                ):
                    raise ValueError("previous-tail first frame lineage is invalid")
            if spec.tail_frame is not None and (
                spec.tail_frame.source_shot_id != spec.shot_id
                or spec.tail_frame.candidate_request_fingerprint
                != spec.shot_image_request_fingerprint
            ):
                raise ValueError("tail frame belongs to another shot")
        selected_payload = [
            {
                "shot_id": item.shot_id,
                "selection_revision": item.selection_revision,
                "first_frame_fingerprint": item.first_frame.frame_fingerprint,
                "tail_frame_fingerprint": (
                    item.tail_frame.frame_fingerprint
                    if item.tail_frame is not None
                    else None
                ),
            }
            for item in self.shot_specs
        ]
        if _canonical_sha256(selected_payload) != self.selected_bindings_fingerprint:
            raise ValueError("shot video selected bindings fingerprint is invalid")
        payload = self.model_dump(exclude={"plan_fingerprint"})
        if _canonical_sha256(payload) != self.plan_fingerprint:
            raise ValueError("shot video plan fingerprint is invalid")
        return self


ShotVideoCandidateSource = Literal["local_mp4"]


class ShotVideoArtifact(BaseModel):
    """One bounded local MP4 artifact owned by the D2 candidate store."""

    model_config = ConfigDict(extra="forbid", strict=True)

    media_type: Literal["video/mp4"] = "video/mp4"
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    duration_milliseconds: int = Field(ge=1, le=300_000)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    has_audio_track: bool

    @field_validator("path", mode="before")
    @classmethod
    def _shot_video_artifact_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("shot video candidate path must be a POSIX relative path")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"outputs/episodes/episode_[0-9]{2,3}\.shot_videos/"
                r"shot_[0-9a-f]{24}/svc_[0-9a-f]{24}\.mp4",
                value,
            )
            is None
        ):
            raise ValueError("shot video candidate path must stay in its artifact root")
        return value

    @field_validator(
        "size_bytes",
        "duration_milliseconds",
        "width",
        "height",
        mode="before",
    )
    @classmethod
    def _shot_video_artifact_integers_are_strict(
        cls,
        value: Any,
        info: Any,
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("has_audio_track", mode="before")
    @classmethod
    def _shot_video_audio_flag_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("has_audio_track must be bool")
        return value

    @model_validator(mode="after")
    def _shot_video_artifact_is_bounded(self) -> "ShotVideoArtifact":
        if self.width * self.height > 40_000_000:
            raise ValueError("shot video candidate pixel count exceeds its limit")
        return self


class ShotVideoCandidate(BaseModel):
    """One immutable D2 video candidate bound to its exact D1 request."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^svc_[0-9a-f]{24}$")
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_kind: ShotVideoCandidateSource = "local_mp4"
    is_placeholder: bool
    artifact: ShotVideoArtifact
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _shot_video_candidate_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_video_candidate_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("is_placeholder", mode="before")
    @classmethod
    def _shot_video_placeholder_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("is_placeholder must be bool")
        return value

    @model_validator(mode="after")
    def _shot_video_candidate_is_content_addressed(self) -> "ShotVideoCandidate":
        payload = self.model_dump(exclude={"candidate_id", "candidate_fingerprint"})
        payload["artifact"] = dict(payload["artifact"])
        payload["artifact"].pop("path", None)
        fingerprint = _canonical_sha256(payload)
        if self.candidate_fingerprint != fingerprint:
            raise ValueError("shot video candidate fingerprint is invalid")
        if self.candidate_id != f"svc_{fingerprint[:24]}":
            raise ValueError("shot video candidate id is invalid")
        expected_path = (
            f"outputs/episodes/episode_{self.episode_no:02d}.shot_videos/"
            f"{self.shot_id}/{self.candidate_id}.mp4"
        )
        if self.artifact.path != expected_path:
            raise ValueError("shot video candidate artifact path is not canonical")
        return self


class ShotVideoSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=r"^svc_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class ShotVideoCandidatePool(BaseModel):
    """Append-only video candidates plus one explicit selected candidate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    candidates: List[ShotVideoCandidate] = Field(max_length=32)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    last_selection_request_fingerprint: Optional[str] = Field(
        default=None,
        pattern=_SHA256_PATTERN,
    )
    selected: Optional[ShotVideoSelection] = None
    pool_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("candidates", mode="before")
    @classmethod
    def _shot_video_candidates_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video candidates must be a list")
        return value

    @field_validator("selection_revision", mode="before")
    @classmethod
    def _shot_video_selection_revision_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("selection_revision must be a strict integer")
        return value

    @model_validator(mode="after")
    def _shot_video_pool_is_consistent(self) -> "ShotVideoCandidatePool":
        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("shot video candidate ids must be unique")
        for candidate in self.candidates:
            if candidate.shot_id != self.shot_id:
                raise ValueError("shot video candidate belongs to another shot")
        if self.selected is not None:
            selected = next(
                (
                    item
                    for item in self.candidates
                    if item.candidate_id == self.selected.candidate_id
                ),
                None,
            )
            if (
                selected is None
                or selected.candidate_fingerprint
                != self.selected.candidate_fingerprint
            ):
                raise ValueError("shot video selection is not an exact candidate")
        payload = self.model_dump(exclude={"pool_fingerprint"})
        if _canonical_sha256(payload) != self.pool_fingerprint:
            raise ValueError("shot video candidate pool fingerprint is invalid")
        return self


class EpisodeShotVideoCandidateManifest(BaseModel):
    """Episode-scoped D2 candidate and selection truth."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-video-candidates-v1"] = (
        "shot-video-candidates-v1"
    )
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    shots: List[ShotVideoCandidatePool] = Field(min_length=1, max_length=100)
    retired_shots: List[ShotVideoCandidatePool] = Field(
        default_factory=list,
        max_length=100,
    )
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _shot_video_manifest_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_video_manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("shots", "retired_shots", mode="before")
    @classmethod
    def _shot_video_manifest_shots_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video candidate shots must be a list")
        return value

    @model_validator(mode="after")
    def _shot_video_manifest_is_consistent(
        self,
    ) -> "EpisodeShotVideoCandidateManifest":
        all_pools = [*self.shots, *self.retired_shots]
        shot_ids = [item.shot_id for item in all_pools]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot video candidate shot ids must be unique")
        candidates = [candidate for pool in all_pools for candidate in pool.candidates]
        if len(candidates) > 256:
            raise ValueError("shot video candidate manifest exceeds its candidate budget")
        if sum(item.artifact.size_bytes for item in candidates) > 4 * 1024**3:
            raise ValueError("shot video candidate manifest exceeds its byte budget")
        selected_bytes = 0
        for pool in self.shots:
            if pool.selected is not None:
                selected_bytes += next(
                    item.artifact.size_bytes
                    for item in pool.candidates
                    if item.candidate_id == pool.selected.candidate_id
                )
        if selected_bytes > 512 * 1024**2:
            raise ValueError("selected shot videos exceed their inspection byte budget")
        for pool in all_pools:
            for candidate in pool.candidates:
                if (
                    candidate.season_no != self.season_no
                    or candidate.episode_no != self.episode_no
                ):
                    raise ValueError("shot video candidate belongs to another episode")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("shot video candidate manifest fingerprint is invalid")
        return self


ShotVideoCoverageStatus = Literal[
    "ready",
    "incomplete",
    "stale",
    "invalid",
    "blocked_source",
]


class ShotVideoCoverageReport(BaseModel):
    """Deterministic D2 production-compose coverage projection."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_plan_matches: bool
    status: ShotVideoCoverageStatus
    required_shot_ids: List[str] = Field(min_length=1, max_length=100)
    selected_fresh_shot_ids: List[str] = Field(max_length=100)
    missing_selection_shot_ids: List[str] = Field(max_length=100)
    stale_candidate_shot_ids: List[str] = Field(max_length=100)
    invalid_artifact_shot_ids: List[str] = Field(max_length=100)
    non_production_shot_ids: List[str] = Field(max_length=100)
    blocked_source_shot_ids: List[str] = Field(max_length=100)
    coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _shot_video_coverage_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("source_plan_matches", mode="before")
    @classmethod
    def _shot_video_coverage_source_match_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("source_plan_matches must be bool")
        return value

    @field_validator(
        "required_shot_ids",
        "selected_fresh_shot_ids",
        "missing_selection_shot_ids",
        "stale_candidate_shot_ids",
        "invalid_artifact_shot_ids",
        "non_production_shot_ids",
        "blocked_source_shot_ids",
        mode="before",
    )
    @classmethod
    def _shot_video_coverage_ids_are_unique(
        cls,
        value: Any,
        info: Any,
    ) -> List[str]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        if len(value) != len(set(value)) or any(
            not isinstance(item, str)
            or re.fullmatch(_SHOT_ID_PATTERN, item) is None
            for item in value
        ):
            raise ValueError(f"{info.field_name} must contain unique shot ids")
        return value

    @model_validator(mode="after")
    def _shot_video_coverage_is_consistent(self) -> "ShotVideoCoverageReport":
        required = set(self.required_shot_ids)
        categories = (
            self.selected_fresh_shot_ids,
            self.missing_selection_shot_ids,
            self.stale_candidate_shot_ids,
            self.invalid_artifact_shot_ids,
            self.non_production_shot_ids,
            self.blocked_source_shot_ids,
        )
        if any(not set(items).issubset(required) for items in categories):
            raise ValueError("shot video coverage contains an unknown shot")
        category_sets = [set(items) for items in categories]
        if any(
            category_sets[left] & category_sets[right]
            for left in range(len(category_sets))
            for right in range(left + 1, len(category_sets))
        ) or set().union(*category_sets) != required:
            raise ValueError("shot video coverage categories must partition required shots")
        if self.blocked_source_shot_ids:
            expected_status = "blocked_source"
        elif not self.source_plan_matches or self.stale_candidate_shot_ids:
            expected_status = "stale"
        elif self.invalid_artifact_shot_ids or self.non_production_shot_ids:
            expected_status = "invalid"
        elif self.missing_selection_shot_ids:
            expected_status = "incomplete"
        else:
            expected_status = "ready"
        if self.status != expected_status:
            raise ValueError("shot video coverage status is inconsistent")
        payload = self.model_dump(exclude={"coverage_fingerprint"})
        if _canonical_sha256(payload) != self.coverage_fingerprint:
            raise ValueError("shot video coverage fingerprint is invalid")
        return self


ShotVideoContinuityStatus = Literal["ready", "degraded_preview", "blocked"]


class ShotVideoContinuityReport(BaseModel):
    """Deterministic D4 continuity and production-compose gate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-video-continuity-v1"] = (
        "shot-video-continuity-v1"
    )
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selected_bindings_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_plan_matches: bool
    status: ShotVideoContinuityStatus
    ready_for_compose: bool
    blocked_shot_ids: List[str] = Field(max_length=100)
    degraded_preview_shot_ids: List[str] = Field(max_length=100)
    broken_lineage_shot_ids: List[str] = Field(max_length=100)
    character_version_change_shot_ids: List[str] = Field(max_length=100)
    scene_version_change_shot_ids: List[str] = Field(max_length=100)
    camera_reversal_shot_ids: List[str] = Field(max_length=100)
    report_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _continuity_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _continuity_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("ready_for_compose", "source_plan_matches", mode="before")
    @classmethod
    def _continuity_ready_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("ready_for_compose must be bool")
        return value

    @field_validator(
        "blocked_shot_ids",
        "degraded_preview_shot_ids",
        "broken_lineage_shot_ids",
        "character_version_change_shot_ids",
        "scene_version_change_shot_ids",
        "camera_reversal_shot_ids",
        mode="before",
    )
    @classmethod
    def _continuity_ids_are_unique(cls, value: Any, info: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        if len(value) != len(set(value)) or any(
            not isinstance(item, str)
            or re.fullmatch(_SHOT_ID_PATTERN, item) is None
            for item in value
        ):
            raise ValueError(f"{info.field_name} must contain unique shot ids")
        return value

    @model_validator(mode="after")
    def _continuity_report_is_consistent(self) -> "ShotVideoContinuityReport":
        if set(self.blocked_shot_ids) & set(self.degraded_preview_shot_ids):
            raise ValueError("blocked and degraded preview shots must be disjoint")
        expected_status = (
            "blocked"
            if (
                not self.source_plan_matches
                or self.blocked_shot_ids
                or self.broken_lineage_shot_ids
            )
            else "degraded_preview"
            if self.degraded_preview_shot_ids
            else "ready"
        )
        if self.status != expected_status:
            raise ValueError("shot video continuity status is inconsistent")
        if self.ready_for_compose != (self.status == "ready"):
            raise ValueError("shot video compose readiness is inconsistent")
        payload = self.model_dump(exclude={"report_fingerprint"})
        if _canonical_sha256(payload) != self.report_fingerprint:
            raise ValueError("shot video continuity fingerprint is invalid")
        return self


VoiceProfileScope = Literal["narrator", "character"]
AudioManifestStatus = Literal["ready", "blocked"]
AudioBlockedReason = Literal[
    "assignment_missing",
    "profile_missing",
    "scope_mismatch",
    "speaker_not_frozen",
]


class VoiceProfile(BaseModel):
    """Immutable provider-neutral voice identity; secrets never belong here."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    profile_id: str = Field(pattern=r"^vp_[0-9a-f]{24}$")
    scope: VoiceProfileScope
    character_id: Optional[str] = Field(default=None, pattern=r"^c[0-9]{3}$")
    display_name: str = Field(min_length=1, max_length=80)
    language_tag: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    provider_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    model_id: str = Field(min_length=1, max_length=120)
    voice_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
    instructions: str = Field(default="", max_length=400)
    profile_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("model_id", mode="before")
    @classmethod
    def _voice_model_id_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", value) is None
            or ".." in value
            or "//" in value
        ):
            raise ValueError("voice model id is invalid")
        return value

    @model_validator(mode="after")
    def _voice_profile_is_content_addressed(self) -> "VoiceProfile":
        if (self.scope == "narrator") != (self.character_id is None):
            raise ValueError("voice profile scope and character id disagree")
        payload = self.model_dump(exclude={"profile_id", "profile_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if self.profile_fingerprint != fingerprint:
            raise ValueError("voice profile fingerprint is invalid")
        if self.profile_id != f"vp_{fingerprint[:24]}":
            raise ValueError("voice profile id is invalid")
        return self


class VoiceAssignment(BaseModel):
    """Explicit segment-to-voice mapping; dialogue speakers are never guessed."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    voice_profile_id: str = Field(pattern=r"^vp_[0-9a-f]{24}$")
    voice_profile_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    speaker_character_id: Optional[str] = Field(default=None, pattern=r"^c[0-9]{3}$")
    assignment_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _voice_assignment_is_content_addressed(self) -> "VoiceAssignment":
        payload = self.model_dump(exclude={"assignment_fingerprint"})
        if _canonical_sha256(payload) != self.assignment_fingerprint:
            raise ValueError("voice assignment fingerprint is invalid")
        return self


class UtteranceSpec(BaseModel):
    """One exact E1 synthesis input derived from one spoken segment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    sequence: int = Field(ge=1, le=200)
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    kind: Literal["narration", "dialogue"]
    text: str = Field(min_length=1, max_length=220)
    speaker_character_id: Optional[str] = Field(default=None, pattern=r"^c[0-9]{3}$")
    voice_profile_id: str = Field(pattern=r"^vp_[0-9a-f]{24}$")
    voice_profile_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    model_id: str = Field(min_length=1, max_length=120)
    voice_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
    instructions_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_segment_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    spec_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _utterance_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("sequence", mode="before")
    @classmethod
    def _utterance_sequence_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("utterance sequence must be a strict integer")
        return value

    @field_validator("model_id", mode="before")
    @classmethod
    def _utterance_model_id_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", value) is None
            or ".." in value
            or "//" in value
        ):
            raise ValueError("utterance model id is invalid")
        return value

    @model_validator(mode="after")
    def _utterance_is_content_addressed(self) -> "UtteranceSpec":
        if (self.kind == "narration") != (self.speaker_character_id is None):
            raise ValueError("utterance kind and speaker disagree")
        payload = self.model_dump(exclude={"utterance_id", "spec_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if self.spec_fingerprint != fingerprint:
            raise ValueError("utterance fingerprint is invalid")
        if self.utterance_id != f"utt_{fingerprint[:24]}":
            raise ValueError("utterance id is invalid")
        return self


class AudioBlockedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    reason: AudioBlockedReason


class MockWavFixture(BaseModel):
    """Bounded local-only WAV descriptor used by E1 tests and offline demos."""

    model_config = ConfigDict(extra="forbid", strict=True)

    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=45, le=3_000_000)
    duration_milliseconds: int = Field(ge=1, le=30_000)
    sample_rate: int = Field(ge=8000, le=48_000)
    channels: Literal[1] = 1

    @field_validator("path", mode="before")
    @classmethod
    def _mock_wav_path_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(
                r"data/drama/audio_fixtures/episode_[0-9]{3}/utt_[0-9a-f]{24}\.wav",
                value,
            )
            is None
        ):
            raise ValueError("mock WAV path must use the local fixture namespace")
        return value

    @field_validator(
        "episode_no", "size_bytes", "duration_milliseconds", "sample_rate", mode="before"
    )
    @classmethod
    def _mock_wav_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _mock_wav_path_matches_utterance(self) -> "MockWavFixture":
        expected = (
            f"data/drama/audio_fixtures/episode_{self.episode_no:03d}/"
            f"{self.utterance_id}.wav"
        )
        if self.path != expected:
            raise ValueError("mock WAV path belongs to another episode or utterance")
        return self


class AudioManifest(BaseModel):
    """Episode-scoped E1 voice resolution and ordered utterance truth."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["audio-manifest-v1"] = "audio-manifest-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    source_render_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    frozen_character_ids: List[str] = Field(min_length=1, max_length=8)
    source_segment_ids: List[str] = Field(max_length=200)
    status: AudioManifestStatus
    profiles: List[VoiceProfile] = Field(max_length=32)
    assignments: List[VoiceAssignment] = Field(max_length=200)
    utterances: List[UtteranceSpec] = Field(max_length=200)
    blocked_segments: List[AudioBlockedSegment] = Field(max_length=200)
    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", mode="before")
    @classmethod
    def _audio_manifest_season_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("season_no must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _audio_manifest_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator(
        "source_segment_ids",
        "frozen_character_ids",
        "profiles",
        "assignments",
        "utterances",
        "blocked_segments",
        mode="before",
    )
    @classmethod
    def _audio_manifest_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _audio_manifest_is_consistent(self) -> "AudioManifest":
        source_ids = self.source_segment_ids
        if len(self.frozen_character_ids) != len(set(self.frozen_character_ids)):
            raise ValueError("audio manifest frozen character ids must be unique")
        if any(
            not isinstance(item, str) or re.fullmatch(r"c[0-9]{3}", item) is None
            for item in self.frozen_character_ids
        ):
            raise ValueError("audio manifest frozen character ids are invalid")
        profile_ids = [item.profile_id for item in self.profiles]
        assignment_ids = [item.segment_id for item in self.assignments]
        utterance_segment_ids = [item.segment_id for item in self.utterances]
        blocked_ids = [item.segment_id for item in self.blocked_segments]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("audio manifest source segments must be unique")
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("audio manifest voice profiles must be unique")
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("audio manifest assignments must be unique")
        if len(utterance_segment_ids) != len(set(utterance_segment_ids)):
            raise ValueError("audio manifest utterances must be unique")
        if len(blocked_ids) != len(set(blocked_ids)):
            raise ValueError("audio manifest blocked segments must be unique")
        if set(utterance_segment_ids) & set(blocked_ids):
            raise ValueError("resolved and blocked audio segments must be disjoint")
        if assignment_ids != utterance_segment_ids:
            raise ValueError("audio assignments and utterances must share stable order")
        outcome_by_id = {segment_id: "resolved" for segment_id in utterance_segment_ids}
        outcome_by_id.update({segment_id: "blocked" for segment_id in blocked_ids})
        if set(outcome_by_id) != set(source_ids):
            raise ValueError("audio manifest must cover every source segment exactly once")
        if [segment_id for segment_id in source_ids if outcome_by_id[segment_id] == "resolved"] != utterance_segment_ids:
            raise ValueError("resolved utterances must preserve source order")
        if [segment_id for segment_id in source_ids if outcome_by_id[segment_id] == "blocked"] != blocked_ids:
            raise ValueError("blocked segments must preserve source order")
        profile_by_id = {item.profile_id: item for item in self.profiles}
        assignment_by_id = {item.segment_id: item for item in self.assignments}
        used_profile_ids: list[str] = []
        for utterance in self.utterances:
            assignment = assignment_by_id[utterance.segment_id]
            profile = profile_by_id.get(assignment.voice_profile_id)
            if profile is None or assignment.voice_profile_fingerprint != profile.profile_fingerprint:
                raise ValueError("audio assignment references an absent voice profile")
            if (
                utterance.voice_profile_id != profile.profile_id
                or utterance.voice_profile_fingerprint != profile.profile_fingerprint
                or utterance.speaker_character_id != assignment.speaker_character_id
                or utterance.provider_id != profile.provider_id
                or utterance.model_id != profile.model_id
                or utterance.voice_name != profile.voice_name
                or utterance.instructions_fingerprint
                != _canonical_sha256(profile.instructions)
            ):
                raise ValueError("utterance does not match its voice assignment")
            if utterance.episode_no != self.episode_no:
                raise ValueError("utterance belongs to another episode")
            if utterance.kind == "narration":
                if profile.scope != "narrator" or profile.character_id is not None:
                    raise ValueError("narration must use a narrator profile")
            elif (
                profile.scope != "character"
                or profile.character_id != assignment.speaker_character_id
                or assignment.speaker_character_id not in self.frozen_character_ids
            ):
                raise ValueError("dialogue must use its assigned character profile")
            if profile.profile_id not in used_profile_ids:
                used_profile_ids.append(profile.profile_id)
        if used_profile_ids != profile_ids:
            raise ValueError("audio manifest profiles must be used in stable order")
        expected_sequence_by_id = {
            segment_id: index
            for index, segment_id in enumerate(source_ids, start=1)
        }
        if any(
            item.sequence != expected_sequence_by_id[item.segment_id]
            for item in self.utterances
        ):
            raise ValueError("audio utterance sequence must match its source position")
        if self.status != ("blocked" if blocked_ids else "ready"):
            raise ValueError("audio manifest status is inconsistent")
        payload = self.model_dump(exclude={"manifest_fingerprint"})
        if _canonical_sha256(payload) != self.manifest_fingerprint:
            raise ValueError("audio manifest fingerprint is invalid")
        return self


TtsAttemptStatus = Literal[
    "started",
    "not_sent",
    "submission_unknown",
    "submitted",
    "artifact_received",
    "succeeded",
    "provider_failed",
]


class TtsProviderCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    backend_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    capability_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    provider_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")
    task_kind: Literal["text_to_speech"] = "text_to_speech"
    output_media_type: Literal["audio/wav"] = "audio/wav"
    sample_rate: int = Field(ge=8000, le=48000)
    max_text_characters: int = Field(ge=1, le=1000)
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("sample_rate", "max_text_characters", mode="before")
    @classmethod
    def _tts_capability_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("model_id", mode="before")
    @classmethod
    def _tts_model_id_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or ".." in value
            or "//" in value
            or value.startswith("/")
        ):
            raise ValueError("TTS model id is invalid")
        return value

    @model_validator(mode="after")
    def _tts_capability_is_content_addressed(self) -> "TtsProviderCapability":
        lowered = self.model_id.lower().rsplit("/", 1)[-1]
        if "gpt-image" in lowered or lowered == "gpt-5.5-medium":
            raise ValueError("non-audio model cannot declare TTS capability")
        payload = self.model_dump(exclude={"capability_fingerprint"})
        if _canonical_sha256(payload) != self.capability_fingerprint:
            raise ValueError("TTS capability fingerprint is invalid")
        return self


class TtsAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    authorization_id: str = Field(pattern=r"^ttsauth_[0-9a-f]{24}$")
    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    utterance_spec_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    account_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    endpoint_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    auth_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    authorization_scope: Literal["utterance_tts_once"] = "utterance_tts_once"
    confirmed: Literal[True] = True
    max_synthesis_posts: Literal[1] = 1
    authorization_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _tts_authorization_is_content_addressed(self) -> "TtsAuthorization":
        payload = self.model_dump(
            exclude={"authorization_id", "authorization_fingerprint"}
        )
        fingerprint = _canonical_sha256(payload)
        if self.authorization_fingerprint != fingerprint:
            raise ValueError("TTS authorization fingerprint is invalid")
        if self.authorization_id != f"ttsauth_{fingerprint[:24]}":
            raise ValueError("TTS authorization id is invalid")
        return self


class TtsAttemptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    utterance_spec_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    model_id: str = Field(min_length=1, max_length=120)
    text_sha256: str = Field(pattern=_SHA256_PATTERN)
    output_path: str = Field(min_length=1, max_length=240)
    capability: TtsProviderCapability
    authorization: TtsAuthorization
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _tts_spec_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("output_path", mode="before")
    @classmethod
    def _tts_output_path_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(
                r"outputs/drama/audio/episode_[0-9]{3}/utt_[0-9a-f]{24}\.wav",
                value,
            )
            is None
        ):
            raise ValueError("TTS output path is invalid")
        return value

    @model_validator(mode="after")
    def _tts_spec_is_consistent(self) -> "TtsAttemptSpec":
        expected_path = (
            f"outputs/drama/audio/episode_{self.episode_no:03d}/"
            f"{self.utterance_id}.wav"
        )
        if self.output_path != expected_path:
            raise ValueError("TTS output path belongs to another utterance")
        if (
            self.authorization.utterance_id != self.utterance_id
            or self.authorization.utterance_spec_fingerprint
            != self.utterance_spec_fingerprint
            or self.authorization.capability_fingerprint
            != self.capability.capability_fingerprint
        ):
            raise ValueError("TTS authorization does not match its input")
        if (
            self.provider_id != self.capability.provider_id
            or self.model_id != self.capability.model_id
        ):
            raise ValueError("TTS capability does not match the utterance voice")
        payload = self.model_dump(exclude={"input_fingerprint"})
        if _canonical_sha256(payload) != self.input_fingerprint:
            raise ValueError("TTS attempt input fingerprint is invalid")
        return self


class TtsSubmissionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    provider_request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _tts_submission_receipt_is_addressed(self) -> "TtsSubmissionReceipt":
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("TTS submission receipt fingerprint is invalid")
        return self


class TtsAudioArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=45, le=3_000_000)
    duration_milliseconds: int = Field(ge=1, le=30_000)
    sample_rate: int = Field(ge=8000, le=48000)
    channels: Literal[1] = 1
    artifact_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("path", mode="before")
    @classmethod
    def _tts_artifact_path_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(
                r"outputs/drama/audio/episode_[0-9]{3}/utt_[0-9a-f]{24}\.wav",
                value,
            )
            is None
        ):
            raise ValueError("TTS artifact path is invalid")
        return value

    @field_validator("size_bytes", "duration_milliseconds", "sample_rate", mode="before")
    @classmethod
    def _tts_artifact_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _tts_artifact_is_addressed(self) -> "TtsAudioArtifact":
        payload = self.model_dump(exclude={"artifact_fingerprint"})
        if _canonical_sha256(payload) != self.artifact_fingerprint:
            raise ValueError("TTS artifact fingerprint is invalid")
        return self


class TtsAttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    attempt_id: str = Field(pattern=r"^ttsattempt_[0-9a-f]{24}$")
    spec: TtsAttemptSpec
    status: TtsAttemptStatus
    submission: Optional[TtsSubmissionReceipt] = None
    artifact: Optional[TtsAudioArtifact] = None
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _tts_attempt_record_is_consistent(self) -> "TtsAttemptRecord":
        if self.status in {"started", "not_sent", "submission_unknown"} and (
            self.submission is not None or self.artifact is not None
        ):
            raise ValueError("pre-submission TTS state cannot have receipts")
        if self.status in {"submitted", "provider_failed"} and (
            self.submission is None or self.artifact is not None
        ):
            raise ValueError("submitted TTS state has invalid receipts")
        if self.status in {"artifact_received", "succeeded"} and (
            self.submission is None or self.artifact is None
        ):
            raise ValueError("completed TTS state requires both receipts")
        if self.artifact is not None and self.artifact.path != self.spec.output_path:
            raise ValueError("TTS attempt artifact belongs to another input")
        if (
            self.artifact is not None
            and self.artifact.sample_rate != self.spec.capability.sample_rate
        ):
            raise ValueError("TTS artifact sample rate does not match capability")
        payload = self.model_dump(exclude={"attempt_id", "record_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if self.record_fingerprint != fingerprint:
            raise ValueError("TTS attempt record fingerprint is invalid")
        if self.attempt_id != f"ttsattempt_{self.spec.input_fingerprint[:24]}":
            raise ValueError("TTS attempt id is invalid")
        return self


TimelineTrackKind = Literal["dialogue", "narration"]


class TimelineVideoClip(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    candidate_id: str = Field(pattern=r"^svc_[0-9a-f]{24}$")
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_duration_ms: int = Field(ge=1, le=300_000)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)

    @field_validator("artifact_duration_ms", "start_ms", "end_ms", mode="before")
    @classmethod
    def _timeline_video_times_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _timeline_video_bounds_are_valid(self) -> "TimelineVideoClip":
        if self.end_ms <= self.start_ms or self.end_ms - self.start_ms != self.artifact_duration_ms:
            raise ValueError("timeline video clip must have positive duration")
        if re.fullmatch(
            r"outputs/episodes/episode_[0-9]{2}\.shot_videos/shot_[0-9a-f]{24}/svc_[0-9a-f]{24}\.mp4",
            self.artifact_path,
        ) is None:
            raise ValueError("timeline video path is invalid")
        return self


class TimelineAudioClip(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    kind: TimelineTrackKind
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_duration_ms: int = Field(ge=1, le=30_000)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)

    @field_validator("artifact_duration_ms", "start_ms", "end_ms", mode="before")
    @classmethod
    def _timeline_audio_times_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _timeline_audio_bounds_are_valid(self) -> "TimelineAudioClip":
        if self.end_ms <= self.start_ms or self.end_ms - self.start_ms != self.artifact_duration_ms:
            raise ValueError("timeline audio clip must have positive duration")
        if re.fullmatch(
            r"outputs/drama/audio/episode_[0-9]{3}/utt_[0-9a-f]{24}\.wav",
            self.artifact_path,
        ) is None:
            raise ValueError("timeline audio path is invalid")
        return self


class TimelineOptionalAudioClip(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    clip_id: str = Field(pattern=r"^opt_[0-9a-f]{24}$")
    kind: Literal["bgm", "sfx"]
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    artifact_size_bytes: int = Field(ge=45, le=10_000_000)
    artifact_duration_ms: int = Field(ge=1, le=300_000)
    sample_rate: int = Field(ge=8000, le=192000)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)
    loop: bool = False
    clip_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "artifact_size_bytes", "artifact_duration_ms", "sample_rate",
        "start_ms", "end_ms", mode="before",
    )
    @classmethod
    def _optional_audio_times_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("loop", mode="before")
    @classmethod
    def _optional_audio_loop_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("optional audio loop must be bool")
        return value

    @model_validator(mode="after")
    def _optional_audio_is_content_addressed(self) -> "TimelineOptionalAudioClip":
        if self.end_ms <= self.start_ms:
            raise ValueError("optional audio clip must have positive duration")
        if not self.loop and self.end_ms - self.start_ms > self.artifact_duration_ms:
            raise ValueError("non-looping optional audio exceeds source duration")
        if re.fullmatch(
            r"outputs/drama/optional_audio/[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.wav",
            self.artifact_path,
        ) is None:
            raise ValueError("optional audio path is invalid")
        payload = self.model_dump(exclude={"clip_id", "clip_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if self.clip_fingerprint != fingerprint or self.clip_id != f"opt_{fingerprint[:24]}":
            raise ValueError("optional audio fingerprint is invalid")
        return self


class TimelineSilenceClip(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)

    @field_validator("start_ms", "end_ms", mode="before")
    @classmethod
    def _timeline_silence_times_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _timeline_silence_bounds_are_valid(self) -> "TimelineSilenceClip":
        if self.end_ms <= self.start_ms:
            raise ValueError("timeline silence must have positive duration")
        return self


class SubtitleCue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    cue_id: str = Field(pattern=r"^cue_[0-9a-f]{24}$")
    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    source_text_sha256: str = Field(pattern=_SHA256_PATTERN)
    text: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=0, le=2_147_483_647)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)
    cue_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("text", mode="before")
    @classmethod
    def _subtitle_text_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or not value
            or any(ord(char) < 32 and char not in {"\n"} for char in value)
            or "\r" in value
            or "\n" in value
            or "-->" in value
        ):
            raise ValueError("subtitle text is invalid")
        return value

    @field_validator("revision", "start_ms", "end_ms", mode="before")
    @classmethod
    def _subtitle_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _subtitle_cue_is_content_addressed(self) -> "SubtitleCue":
        if self.end_ms <= self.start_ms:
            raise ValueError("subtitle cue must have positive duration")
        payload = self.model_dump(exclude={"cue_id", "cue_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if self.cue_fingerprint != fingerprint:
            raise ValueError("subtitle cue fingerprint is invalid")
        if self.cue_id != f"cue_{fingerprint[:24]}":
            raise ValueError("subtitle cue id is invalid")
        return self


class TimelineManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["timeline-manifest-v1"] = "timeline-manifest-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    d4_report_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selected_bindings_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    audio_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    total_duration_ms: int = Field(ge=1, le=3_600_000)
    video_clips: List[TimelineVideoClip] = Field(min_length=1, max_length=100)
    audio_clips: List[TimelineAudioClip] = Field(max_length=200)
    silence_clips: List[TimelineSilenceClip] = Field(max_length=100)
    optional_audio_clips: List[TimelineOptionalAudioClip] = Field(max_length=100)
    subtitle_cues: List[SubtitleCue] = Field(max_length=200)
    bgm_policy: Literal["disabled", "optional"] = "optional"
    warnings: List[Literal["optional_bgm_missing"]] = Field(max_length=1)
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "total_duration_ms", mode="before")
    @classmethod
    def _timeline_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _timeline_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator(
        "video_clips", "audio_clips", "silence_clips", "optional_audio_clips",
        "subtitle_cues", "warnings",
        mode="before",
    )
    @classmethod
    def _timeline_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _timeline_is_consistent(self) -> "TimelineManifest":
        shot_ids = [item.shot_id for item in self.video_clips]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("timeline video shots must be unique")
        cursor = 0
        video_by_shot: Dict[str, TimelineVideoClip] = {}
        for clip in self.video_clips:
            if clip.start_ms != cursor:
                raise ValueError("timeline video clips must be contiguous")
            cursor = clip.end_ms
            video_by_shot[clip.shot_id] = clip
            expected_path = (
                f"outputs/episodes/episode_{self.episode_no:02d}.shot_videos/"
                f"{clip.shot_id}/{clip.candidate_id}.mp4"
            )
            if clip.artifact_path != expected_path:
                raise ValueError("timeline video artifact identity is invalid")
        if cursor != self.total_duration_ms:
            raise ValueError("timeline duration does not match video coverage")
        utterance_ids = [item.utterance_id for item in self.audio_clips]
        if len(utterance_ids) != len(set(utterance_ids)):
            raise ValueError("timeline utterances must be unique")
        if [(item.start_ms, item.end_ms) for item in self.audio_clips] != sorted(
            (item.start_ms, item.end_ms) for item in self.audio_clips
        ):
            raise ValueError("timeline audio clips must be chronological")
        cue_ids = [item.cue_id for item in self.subtitle_cues]
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("subtitle cue ids must be unique")
        if [item.utterance_id for item in self.subtitle_cues] != utterance_ids:
            raise ValueError("subtitle cues must match audio clip order")
        for audio, cue in zip(self.audio_clips, self.subtitle_cues):
            expected_audio_path = (
                f"outputs/drama/audio/episode_{self.episode_no:03d}/"
                f"{audio.utterance_id}.wav"
            )
            if audio.artifact_path != expected_audio_path:
                raise ValueError("timeline audio artifact identity is invalid")
            video = video_by_shot.get(audio.shot_id)
            if (
                video is None
                or audio.start_ms < video.start_ms
                or audio.end_ms > video.end_ms
            ):
                raise ValueError("timeline audio crosses its shot bounds")
            if (
                cue.start_ms != audio.start_ms
                or cue.end_ms != audio.end_ms
                or cue.utterance_id != audio.utterance_id
            ):
                raise ValueError("subtitle cue does not match its utterance timing")
        partitions: Dict[str, List[tuple[int, int]]] = {shot_id: [] for shot_id in shot_ids}
        for clip in self.audio_clips:
            partitions.setdefault(clip.shot_id, []).append((clip.start_ms, clip.end_ms))
        silence_ids = [item.shot_id for item in self.silence_clips]
        if len(silence_ids) != len(set(silence_ids)):
            raise ValueError("timeline allows at most one silence tail per shot")
        for clip in self.silence_clips:
            if clip.shot_id not in video_by_shot:
                raise ValueError("timeline silence belongs to an unknown shot")
            partitions[clip.shot_id].append((clip.start_ms, clip.end_ms))
        for shot_id, video in video_by_shot.items():
            ranges = sorted(partitions[shot_id])
            expected = video.start_ms
            for start, end in ranges:
                if start != expected or end <= start or end > video.end_ms:
                    raise ValueError("timeline audio and silence must partition each shot")
                expected = end
            if expected != video.end_ms:
                raise ValueError("timeline shot audio coverage is incomplete")
        optional_ids = [item.clip_id for item in self.optional_audio_clips]
        if len(optional_ids) != len(set(optional_ids)) or any(
            item.end_ms > self.total_duration_ms for item in self.optional_audio_clips
        ):
            raise ValueError("optional audio clips are invalid or out of bounds")
        optional_order = [
            (item.start_ms, item.end_ms, item.clip_id)
            for item in self.optional_audio_clips
        ]
        if optional_order != sorted(optional_order):
            raise ValueError("optional audio clips must be in canonical order")
        bgm_end = 0
        for item in (row for row in self.optional_audio_clips if row.kind == "bgm"):
            if item.start_ms < bgm_end:
                raise ValueError("BGM clips must not overlap")
            bgm_end = item.end_ms
        has_bgm = any(item.kind == "bgm" for item in self.optional_audio_clips)
        if self.bgm_policy == "disabled" and has_bgm:
            raise ValueError("BGM is disabled for this timeline")
        expected_warnings = (
            ["optional_bgm_missing"]
            if self.bgm_policy == "optional" and not has_bgm
            else []
        )
        if self.warnings != expected_warnings:
            raise ValueError("timeline BGM warning is inconsistent")
        payload = self.model_dump(exclude={"timeline_fingerprint"})
        if _canonical_sha256(payload) != self.timeline_fingerprint:
            raise ValueError("timeline fingerprint is invalid")
        return self


class SrtArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    cue_count: int = Field(ge=0, le=200)
    content: str = Field(max_length=100_000)

    @field_validator("cue_count", mode="before")
    @classmethod
    def _srt_count_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("SRT cue count must be a strict integer")
        return value

    @model_validator(mode="after")
    def _srt_artifact_is_hash_bound(self) -> "SrtArtifact":
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("SRT content hash is invalid")
        if self.content.count(" --> ") != self.cue_count:
            raise ValueError("SRT cue count is invalid")
        return self


class AssArtifact(BaseModel):
    """Deterministic UTF-8 ASS sidecar derived from one TimelineManifest."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    style_profile: Literal["vertical-1080x1920-zh-v1"] = (
        "vertical-1080x1920-zh-v1"
    )
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    cue_count: int = Field(ge=0, le=200)
    content: str = Field(max_length=100_000)

    @field_validator("cue_count", mode="before")
    @classmethod
    def _ass_count_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("ASS cue count must be a strict integer")
        return value

    @model_validator(mode="after")
    def _ass_artifact_is_hash_bound(self) -> "AssArtifact":
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("ASS content hash is invalid")
        dialogue_count = sum(
            1 for line in self.content.splitlines() if line.startswith("Dialogue: ")
        )
        if dialogue_count != self.cue_count:
            raise ValueError("ASS cue count is invalid")
        if (
            "[Script Info]" not in self.content
            or "[V4+ Styles]" not in self.content
            or "[Events]" not in self.content
        ):
            raise ValueError("ASS sections are incomplete")
        return self


EditMaterialKind = Literal["video", "dialogue", "narration", "bgm", "sfx"]


class EditableTimelineMaterial(BaseModel):
    """One exact immutable media input in the generic editable export."""

    model_config = ConfigDict(extra="forbid", strict=True)

    material_id: str = Field(pattern=r"^mat_[0-9a-f]{24}$")
    kind: EditMaterialKind
    source_id: str = Field(min_length=1, max_length=96)
    artifact_path: str = Field(min_length=1, max_length=240)
    artifact_sha256: str = Field(pattern=_SHA256_PATTERN)
    source_duration_ms: int = Field(ge=1, le=3_600_000)
    material_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("source_duration_ms", mode="before")
    @classmethod
    def _edit_material_duration_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("editable material duration must be a strict integer")
        return value

    @field_validator("artifact_path")
    @classmethod
    def _edit_material_path_is_safe(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(char) < 32 for char in value)
            or not value.startswith("outputs/")
        ):
            raise ValueError("editable material path is unsafe")
        return value

    @model_validator(mode="after")
    def _edit_material_is_content_addressed(self) -> "EditableTimelineMaterial":
        payload = self.model_dump(exclude={"material_id", "material_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if (
            self.material_fingerprint != fingerprint
            or self.material_id != f"mat_{fingerprint[:24]}"
        ):
            raise ValueError("editable material fingerprint is invalid")
        return self


EditableTrackKind = Literal[
    "video",
    "dialogue",
    "narration",
    "bgm",
    "sfx",
    "silence",
]


class EditableTimelineSegment(BaseModel):
    """One timeline segment; silence is the only material-free kind."""

    model_config = ConfigDict(extra="forbid", strict=True)

    segment_id: str = Field(pattern=r"^editseg_[0-9a-f]{24}$")
    kind: EditableTrackKind
    source_id: str = Field(min_length=1, max_length=96)
    material_id: Optional[str] = Field(default=None, pattern=r"^mat_[0-9a-f]{24}$")
    timeline_start_ms: int = Field(ge=0, le=3_600_000)
    timeline_end_ms: int = Field(ge=1, le=3_600_000)
    source_in_ms: int = Field(ge=0, le=3_600_000)
    source_out_ms: int = Field(ge=0, le=3_600_000)
    loop: bool = False
    gain_permille: int = Field(ge=0, le=2_000)
    fade_in_ms: int = Field(ge=0, le=60_000)
    fade_out_ms: int = Field(ge=0, le=60_000)
    segment_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "timeline_start_ms",
        "timeline_end_ms",
        "source_in_ms",
        "source_out_ms",
        "gain_permille",
        "fade_in_ms",
        "fade_out_ms",
        mode="before",
    )
    @classmethod
    def _edit_segment_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _edit_segment_is_consistent(self) -> "EditableTimelineSegment":
        duration = self.timeline_end_ms - self.timeline_start_ms
        if duration <= 0:
            raise ValueError("editable segment must have positive duration")
        if self.kind == "silence":
            if (
                self.material_id is not None
                or self.source_in_ms != 0
                or self.source_out_ms != 0
                or self.loop
                or self.gain_permille != 0
                or self.fade_in_ms != 0
                or self.fade_out_ms != 0
            ):
                raise ValueError("editable silence segment is invalid")
        else:
            if self.material_id is None or self.source_out_ms <= self.source_in_ms:
                raise ValueError("editable media segment is invalid")
            if not self.loop and self.source_out_ms - self.source_in_ms != duration:
                raise ValueError("editable media segment duration is inconsistent")
            if self.kind == "video" and (
                self.fade_in_ms != 0 or self.fade_out_ms != 0
            ):
                raise ValueError("editable video fades are not defined by profile v1")
            if self.fade_in_ms + self.fade_out_ms > duration:
                raise ValueError("editable audio fades exceed segment duration")
        payload = self.model_dump(exclude={"segment_id", "segment_fingerprint"})
        fingerprint = _canonical_sha256(payload)
        if (
            self.segment_fingerprint != fingerprint
            or self.segment_id != f"editseg_{fingerprint[:24]}"
        ):
            raise ValueError("editable segment fingerprint is invalid")
        return self


class EditableTimelineTrack(BaseModel):
    """Ordered non-overlapping segments for one explicit track kind."""

    model_config = ConfigDict(extra="forbid", strict=True)

    track_id: str = Field(pattern=r"^(?:video|dialogue|narration|bgm|sfx|silence)-v1$")
    kind: EditableTrackKind
    segments: List[EditableTimelineSegment] = Field(max_length=200)
    track_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("segments", mode="before")
    @classmethod
    def _edit_track_segments_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("editable track segments must be a list")
        return value

    @model_validator(mode="after")
    def _edit_track_is_consistent(self) -> "EditableTimelineTrack":
        if self.track_id != f"{self.kind}-v1":
            raise ValueError("editable track id does not match its kind")
        if any(item.kind != self.kind for item in self.segments):
            raise ValueError("editable track contains another segment kind")
        ids = [item.segment_id for item in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("editable track segment ids must be unique")
        ordering = [
            (
                item.timeline_start_ms,
                item.timeline_end_ms,
                item.source_id,
                item.segment_id,
            )
            for item in self.segments
        ]
        if ordering != sorted(ordering):
            raise ValueError("editable track segments must use canonical order")
        if self.kind != "sfx":
            previous_end = 0
            for item in self.segments:
                if item.timeline_start_ms < previous_end:
                    raise ValueError("editable track segments must not overlap")
                previous_end = item.timeline_end_ms
        payload = self.model_dump(exclude={"track_fingerprint"})
        if _canonical_sha256(payload) != self.track_fingerprint:
            raise ValueError("editable track fingerprint is invalid")
        return self


class EditableTimelineSubtitle(BaseModel):
    """One editable subtitle event retaining its canonical cue identity."""

    model_config = ConfigDict(extra="forbid", strict=True)

    cue_id: str = Field(pattern=r"^cue_[0-9a-f]{24}$")
    utterance_id: str = Field(pattern=r"^utt_[0-9a-f]{24}$")
    source_text_sha256: str = Field(pattern=_SHA256_PATTERN)
    cue_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    text: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=0, le=2_147_483_647)
    start_ms: int = Field(ge=0, le=3_600_000)
    end_ms: int = Field(ge=1, le=3_600_000)
    style_token: Literal["zh-primary-v1"] = "zh-primary-v1"

    @field_validator("revision", "start_ms", "end_ms", mode="before")
    @classmethod
    def _edit_subtitle_times_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _edit_subtitle_bounds_are_valid(self) -> "EditableTimelineSubtitle":
        if self.end_ms <= self.start_ms:
            raise ValueError("editable subtitle must have positive duration")
        payload = {
            "utterance_id": self.utterance_id,
            "source_text_sha256": self.source_text_sha256,
            "text": self.text,
            "revision": self.revision,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }
        fingerprint = _canonical_sha256(payload)
        if (
            self.cue_fingerprint != fingerprint
            or self.cue_id != f"cue_{fingerprint[:24]}"
        ):
            raise ValueError("editable subtitle fingerprint is invalid")
        return self


class EditableTimelineProject(BaseModel):
    """Version-locked generic edit project; not a vendor-specific NLE format."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    exporter_version: Literal["drama-edit-export-v1"] = "drama-edit-export-v1"
    profile: Literal["vertical-1080x1920-25-v1"] = "vertical-1080x1920-25-v1"
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[25] = 25
    fps_denominator: Literal[1] = 1
    audio_sample_rate: Literal[48000] = 48000
    audio_layout: Literal["stereo"] = "stereo"
    audio_codec_profile: Literal["aac-128k-v1"] = "aac-128k-v1"
    total_duration_ms: int = Field(ge=1, le=3_600_000)
    materials: List[EditableTimelineMaterial] = Field(max_length=400)
    tracks: List[EditableTimelineTrack] = Field(min_length=6, max_length=6)
    subtitles: List[EditableTimelineSubtitle] = Field(max_length=200)
    project_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "total_duration_ms", mode="before")
    @classmethod
    def _edit_project_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _edit_project_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("materials", "tracks", "subtitles", mode="before")
    @classmethod
    def _edit_project_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _edit_project_is_consistent(self) -> "EditableTimelineProject":
        material_ids = [item.material_id for item in self.materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("editable project material ids must be unique")
        materials = {item.material_id: item for item in self.materials}
        expected_kinds = ["video", "dialogue", "narration", "bgm", "sfx", "silence"]
        if [item.kind for item in self.tracks] != expected_kinds:
            raise ValueError("editable project track order is invalid")
        segment_ids: set[str] = set()
        for track in self.tracks:
            for segment in track.segments:
                if segment.segment_id in segment_ids:
                    raise ValueError("editable project segment ids must be unique")
                segment_ids.add(segment.segment_id)
                if segment.timeline_end_ms > self.total_duration_ms:
                    raise ValueError("editable segment exceeds project duration")
                if segment.material_id is None:
                    if segment.kind != "silence":
                        raise ValueError("editable media segment lacks material")
                    continue
                material = materials.get(segment.material_id)
                if material is None or material.kind != segment.kind:
                    raise ValueError("editable segment material kind is invalid")
                if segment.source_out_ms > material.source_duration_ms:
                    raise ValueError("editable segment exceeds source material")
        video = self.tracks[0].segments
        cursor = 0
        for segment in video:
            if segment.timeline_start_ms != cursor:
                raise ValueError("editable video track must be contiguous")
            cursor = segment.timeline_end_ms
        if cursor != self.total_duration_ms:
            raise ValueError("editable video track does not cover the project")
        subtitle_ids = [item.cue_id for item in self.subtitles]
        if len(subtitle_ids) != len(set(subtitle_ids)):
            raise ValueError("editable subtitle ids must be unique")
        if any(item.end_ms > self.total_duration_ms for item in self.subtitles):
            raise ValueError("editable subtitle exceeds project duration")
        payload = self.model_dump(exclude={"project_fingerprint"})
        if _canonical_sha256(payload) != self.project_fingerprint:
            raise ValueError("editable project fingerprint is invalid")
        return self


class DramaEditExportResult(BaseModel):
    """Hashes and paths for one atomically persisted F2 export pair."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    ass_path: str = Field(pattern=r"^outputs/drama/edit/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.ass$")
    ass_sha256: str = Field(pattern=_SHA256_PATTERN)
    project_path: str = Field(pattern=r"^outputs/drama/edit/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.edit\.json$")
    project_sha256: str = Field(pattern=_SHA256_PATTERN)
    completion_path: str = Field(pattern=r"^outputs/drama/edit/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.complete\.json$")
    export_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", mode="before")
    @classmethod
    def _edit_result_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @model_validator(mode="after")
    def _edit_result_is_content_addressed(self) -> "DramaEditExportResult":
        expected_stem = f"timeline_{self.timeline_fingerprint[:24]}"
        expected_base = f"outputs/drama/edit/episode_{self.episode_no:03d}"
        if (
            self.ass_path != f"{expected_base}/{expected_stem}.ass"
            or self.project_path != f"{expected_base}/{expected_stem}.edit.json"
            or self.completion_path
            != f"{expected_base}/{expected_stem}.complete.json"
        ):
            raise ValueError("editable export paths do not match the timeline")
        payload = self.model_dump(exclude={"export_fingerprint"})
        if _canonical_sha256(payload) != self.export_fingerprint:
            raise ValueError("editable export fingerprint is invalid")
        return self


class DramaComposePlan(BaseModel):
    """Deterministic argv-only F1 plan derived from one TimelineManifest."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["drama-compose-plan-v1"] = "drama-compose-plan-v1"
    profile: Literal["vertical-1080x1920-25-v1"] = "vertical-1080x1920-25-v1"
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[25] = 25
    fps_denominator: Literal[1] = 1
    video_time_base_numerator: Literal[1] = 1
    video_time_base_denominator: Literal[25000] = 25000
    audio_sample_rate: Literal[48000] = 48000
    audio_layout: Literal["stereo"] = "stereo"
    total_duration_ms: int = Field(ge=1, le=3_600_000)
    required_shot_ids: List[str] = Field(min_length=1, max_length=100)
    input_paths: List[str] = Field(min_length=1, max_length=300)
    srt_path: str = Field(min_length=1, max_length=240)
    output_path: str = Field(min_length=1, max_length=240)
    qa_path: str = Field(min_length=1, max_length=240)
    filter_graph: str = Field(min_length=1, max_length=100_000)
    ffmpeg_argv: List[str] = Field(min_length=10, max_length=1000)
    plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "episode_no", "total_duration_ms", mode="before"
    )
    @classmethod
    def _compose_plan_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("required_shot_ids", "input_paths", "ffmpeg_argv", mode="before")
    @classmethod
    def _compose_plan_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _compose_plan_is_safe_and_content_addressed(self) -> "DramaComposePlan":
        if len(self.required_shot_ids) != len(set(self.required_shot_ids)) or any(
            re.fullmatch(_SHOT_ID_PATTERN, item) is None
            for item in self.required_shot_ids
        ):
            raise ValueError("compose required shots are invalid")
        path_pattern = r"outputs/drama/compose/episode_[0-9]{3}/[A-Za-z0-9._-]{1,160}"
        for value in [*self.input_paths, self.srt_path, self.output_path, self.qa_path]:
            if (
                not isinstance(value, str)
                or value.startswith("/")
                or "\\" in value
                or any(part in {"", ".", ".."} for part in value.split("/"))
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("compose path is unsafe")
        if re.fullmatch(path_pattern + r"\.srt", self.srt_path) is None:
            raise ValueError("compose SRT path is invalid")
        if re.fullmatch(path_pattern + r"\.mp4", self.output_path) is None:
            raise ValueError("compose MP4 path is invalid")
        if re.fullmatch(path_pattern + r"\.qa\.json", self.qa_path) is None:
            raise ValueError("compose QA path is invalid")
        if self.ffmpeg_argv[0] != "ffmpeg" or self.ffmpeg_argv[-1] != "{output_temp}":
            raise ValueError("compose argv executable or output token is invalid")
        if self.ffmpeg_argv.count("-filter_complex") != 1 or self.filter_graph not in self.ffmpeg_argv:
            raise ValueError("compose filter graph is not bound to argv")
        forbidden = {"-filter_script", "-filter_complex_script", "-report", "-progress"}
        if any(
            not isinstance(arg, str)
            or not arg
            or any(ord(char) < 32 for char in arg)
            or (arg.startswith("/") and arg != "/dev/null")
            or arg in forbidden
            for arg in self.ffmpeg_argv
        ):
            raise ValueError("compose argv is unsafe")
        payload = self.model_dump(exclude={"plan_fingerprint"})
        if _canonical_sha256(payload) != self.plan_fingerprint:
            raise ValueError("compose plan fingerprint is invalid")
        return self


class DramaComposeQaReport(BaseModel):
    """Post-probe evidence for one completed F1 MP4/SRT pair."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["drama-compose-qa-v1"] = "drama-compose-qa-v1"
    status: Literal["passed"] = "passed"
    acceptance_level: Literal["local-e2e"] = "local-e2e"
    provider_validated: Literal[False] = False
    profile: Literal["vertical-1080x1920-25-v1"]
    plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    output_path: str = Field(min_length=1, max_length=240)
    output_sha256: str = Field(pattern=_SHA256_PATTERN)
    output_size_bytes: int = Field(ge=1, le=500_000_000)
    srt_path: str = Field(min_length=1, max_length=240)
    srt_sha256: str = Field(pattern=_SHA256_PATTERN)
    required_shot_ids: List[str] = Field(min_length=1, max_length=100)
    covered_shot_ids: List[str] = Field(min_length=1, max_length=100)
    container: Literal["mp4"] = "mp4"
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[25] = 25
    fps_denominator: Literal[1] = 1
    sample_aspect_ratio: Literal["1:1"] = "1:1"
    video_time_base: Literal["1/25000"] = "1/25000"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    audio_sample_rate: Literal[48000] = 48000
    audio_channels: Literal[2] = 2
    audio_layout: Literal["stereo"] = "stereo"
    audio_time_base: Literal["1/48000"] = "1/48000"
    expected_duration_ms: int = Field(ge=1, le=3_600_000)
    duration_ms: int = Field(ge=1, le=3_600_000)
    metadata_timeline_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    qa_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "episode_no", "output_size_bytes", "expected_duration_ms", "duration_ms",
        mode="before",
    )
    @classmethod
    def _compose_qa_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("required_shot_ids", "covered_shot_ids", mode="before")
    @classmethod
    def _compose_qa_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _compose_qa_is_complete(self) -> "DramaComposeQaReport":
        expected_base = f"outputs/drama/compose/episode_{self.episode_no:03d}"
        expected_stem = f"timeline_{self.timeline_fingerprint[:24]}"
        if (
            self.output_path != f"{expected_base}/{expected_stem}.mp4"
            or self.srt_path != f"{expected_base}/{expected_stem}.srt"
        ):
            raise ValueError("compose QA artifact paths are invalid")
        if (
            len(self.required_shot_ids) != len(set(self.required_shot_ids))
            or any(re.fullmatch(_SHOT_ID_PATTERN, item) is None for item in self.required_shot_ids)
        ):
            raise ValueError("compose QA shot ids are invalid")
        if self.required_shot_ids != self.covered_shot_ids:
            raise ValueError("compose QA required-shot coverage is incomplete")
        if abs(self.duration_ms - self.expected_duration_ms) > 160:
            raise ValueError("compose QA duration is out of tolerance")
        if self.metadata_timeline_fingerprint != self.timeline_fingerprint:
            raise ValueError("compose MP4 metadata does not match timeline")
        payload = self.model_dump(exclude={"qa_fingerprint"})
        if _canonical_sha256(payload) != self.qa_fingerprint:
            raise ValueError("compose QA fingerprint is invalid")
        return self


ShotVideoGenerationMode = Literal["image_to_video", "reference_to_video"]
ShotVideoAttemptStatus = Literal[
    "started",
    "not_sent",
    "submission_unknown",
    "submitted",
    "provider_succeeded",
    "provider_failed",
    "artifact_received",
    "succeeded",
    "closed_unknown",
]
ShotVideoAttemptOutcome = Literal["not_sent", "unknown", "submitted", "terminal"]
ShotVideoAttemptInspectionState = Literal[
    "needs_attempts",
    "fresh",
    "reconciliation_required",
    "stale",
    "invalid",
]


class ShotVideoResolution(BaseModel):
    """One exact output profile accepted by a D3 backend capability."""

    model_config = ConfigDict(extra="forbid", strict=True)

    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)

    @field_validator("width", "height", mode="before")
    @classmethod
    def _resolution_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _resolution_is_bounded(self) -> "ShotVideoResolution":
        if self.width * self.height > 40_000_000:
            raise ValueError("shot video resolution exceeds its pixel limit")
        return self


class ShotVideoProviderCapability(BaseModel):
    """Static provider-neutral capabilities frozen into every D3 attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    backend_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    capability_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
    supported_modes: List[ShotVideoGenerationMode] = Field(min_length=1, max_length=2)
    supports_async_submission: Literal[True] = True
    supports_poll_resume: Literal[True] = True
    supports_tail_frame: bool
    max_reference_images: int = Field(ge=0, le=25)
    supported_durations_seconds: List[int] = Field(min_length=1, max_length=30)
    supported_resolutions: List[ShotVideoResolution] = Field(min_length=1, max_length=16)
    output_media_type: Literal["video/mp4"] = "video/mp4"
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("supports_tail_frame", mode="before")
    @classmethod
    def _tail_support_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("supports_tail_frame must be bool")
        return value

    @field_validator("max_reference_images", mode="before")
    @classmethod
    def _reference_limit_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("max_reference_images must be a strict integer")
        return value

    @field_validator(
        "supported_modes",
        "supported_durations_seconds",
        "supported_resolutions",
        mode="before",
    )
    @classmethod
    def _capability_lists_are_strict(cls, value: Any, info: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _capability_is_canonical(self) -> "ShotVideoProviderCapability":
        mode_order = ["image_to_video", "reference_to_video"]
        if self.supported_modes != [
            item for item in mode_order if item in self.supported_modes
        ] or len(self.supported_modes) != len(set(self.supported_modes)):
            raise ValueError("shot video modes must use canonical unique order")
        if any(
            not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 30
            for item in self.supported_durations_seconds
        ) or self.supported_durations_seconds != sorted(set(self.supported_durations_seconds)):
            raise ValueError("shot video durations must be sorted unique strict integers")
        profiles = [(item.width, item.height) for item in self.supported_resolutions]
        if profiles != sorted(set(profiles)):
            raise ValueError("shot video resolutions must be sorted and unique")
        payload = self.model_dump(exclude={"capability_fingerprint"})
        if _canonical_sha256(payload) != self.capability_fingerprint:
            raise ValueError("shot video capability fingerprint is invalid")
        return self


class ShotVideoSubmissionGate(BaseModel):
    """Last-hop authorization snapshot; values are bounded and secret-free."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    backend_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    authorization_id: str = Field(pattern=r"^svauth_[0-9a-f]{24}$")
    authorized_episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    authorized_shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    authorized_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    account_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    endpoint_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    auth_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    authorization_scope: Literal["shot_video_once"] = "shot_video_once"
    confirmed: Literal[True] = True
    currency: Literal["CNY"] = "CNY"
    estimated_cost_microunits: int = Field(ge=0, le=1_000_000_000_000)
    authorized_budget_microunits: int = Field(ge=0, le=1_000_000_000_000)
    max_submit_calls: Literal[1] = 1
    authorization_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "authorized_episode_no",
        "estimated_cost_microunits",
        "authorized_budget_microunits",
        "max_submit_calls",
        mode="before",
    )
    @classmethod
    def _gate_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _gate_is_authorized(self) -> "ShotVideoSubmissionGate":
        if self.estimated_cost_microunits > self.authorized_budget_microunits:
            raise ValueError("shot video estimate exceeds its authorized budget")
        payload = self.model_dump(exclude={"authorization_fingerprint"})
        if _canonical_sha256(payload) != self.authorization_fingerprint:
            raise ValueError("shot video authorization fingerprint is invalid")
        return self


class ShotVideoAttemptSpec(BaseModel):
    """One exact D1 request lowered under a D2 and provider authorization snapshot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_plan_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    pre_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    mode: ShotVideoGenerationMode
    target_duration_seconds: int = Field(ge=1, le=30)
    output_width: int = Field(ge=1, le=8192)
    output_height: int = Field(ge=1, le=8192)
    prompt_sha256: str = Field(pattern=_SHA256_PATTERN)
    first_frame: ShotVideoFrameRef
    tail_frame: Optional[ShotVideoFrameRef] = None
    ordered_references: List[ShotImageReference] = Field(max_length=25)
    references_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    capability: ShotVideoProviderCapability
    submission_gate: ShotVideoSubmissionGate
    output_media_type: Literal["video/mp4"] = "video/mp4"
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "season_no",
        "target_duration_seconds",
        "output_width",
        "output_height",
        mode="before",
    )
    @classmethod
    def _attempt_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _attempt_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("ordered_references", mode="before")
    @classmethod
    def _attempt_references_are_strict(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video attempt references must be a list")
        return value

    @model_validator(mode="after")
    def _attempt_is_compatible(self) -> "ShotVideoAttemptSpec":
        if self.capability.backend_id != self.submission_gate.backend_id:
            raise ValueError("shot video gate and capability backend differ")
        if (
            self.episode_no != self.submission_gate.authorized_episode_no
            or self.shot_id != self.submission_gate.authorized_shot_id
            or self.request_fingerprint
            != self.submission_gate.authorized_request_fingerprint
        ):
            raise ValueError("shot video gate does not authorize this exact request")
        if self.mode not in self.capability.supported_modes:
            raise ValueError("shot video mode is unsupported")
        if self.target_duration_seconds not in self.capability.supported_durations_seconds:
            raise ValueError("shot video duration is unsupported")
        if (self.output_width, self.output_height) not in {
            (item.width, item.height) for item in self.capability.supported_resolutions
        }:
            raise ValueError("shot video resolution is unsupported")
        if self.tail_frame is not None and not self.capability.supports_tail_frame:
            raise ValueError("shot video tail frame is unsupported")
        if len(self.ordered_references) > self.capability.max_reference_images:
            raise ValueError("shot video references exceed capability")
        if self.mode == "reference_to_video" and not self.ordered_references:
            raise ValueError("reference-to-video requires exact references")
        if self.first_frame.frame_role != "first" or (
            self.tail_frame is not None and self.tail_frame.frame_role != "tail"
        ):
            raise ValueError("shot video attempt frame roles are invalid")
        reference_payload = [item.model_dump() for item in self.ordered_references]
        if _canonical_sha256(reference_payload) != self.references_fingerprint:
            raise ValueError("shot video attempt references fingerprint is invalid")
        if self.output_width * self.output_height > 40_000_000:
            raise ValueError("shot video attempt resolution exceeds its pixel limit")
        payload = self.model_dump(exclude={"input_fingerprint"})
        if _canonical_sha256(payload) != self.input_fingerprint:
            raise ValueError("shot video attempt fingerprint is invalid")
        return self


class ShotVideoSubmissionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempt_id: str = Field(pattern=r"^sva_[0-9a-f]{24}$")
    backend_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    account_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    authorization_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("provider_task_id", mode="before")
    @classmethod
    def _task_id_is_opaque(cls, value: Any) -> str:
        if not isinstance(value, str) or "://" in value:
            raise ValueError("provider task id must be a bounded opaque id")
        return value

    @model_validator(mode="after")
    def _submission_receipt_is_valid(self) -> "ShotVideoSubmissionReceipt":
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("shot video submission receipt fingerprint is invalid")
        return self


class ShotVideoTerminalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    submission_receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    provider_task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    terminal_status: Literal["succeeded", "failed"]
    result_token: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    cost_reported: bool
    actual_cost_microunits: Optional[int] = Field(
        default=None,
        ge=0,
        le=1_000_000_000_000,
    )
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("provider_task_id", "result_token", mode="before")
    @classmethod
    def _terminal_ids_are_opaque(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or "://" in value:
            raise ValueError("provider result identity must be a bounded opaque id")
        return value

    @field_validator("cost_reported", mode="before")
    @classmethod
    def _cost_reported_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("cost_reported must be bool")
        return value

    @field_validator("actual_cost_microunits", mode="before")
    @classmethod
    def _actual_cost_is_strict(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("actual_cost_microunits must be a strict integer")
        return value

    @model_validator(mode="after")
    def _terminal_receipt_is_valid(self) -> "ShotVideoTerminalReceipt":
        if (self.terminal_status == "succeeded") != (self.result_token is not None):
            raise ValueError("shot video terminal result token is inconsistent")
        if self.cost_reported != (self.actual_cost_microunits is not None):
            raise ValueError("shot video terminal cost state is inconsistent")
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("shot video terminal receipt fingerprint is invalid")
        return self


class ShotVideoAttemptClosureReceipt(BaseModel):
    """Bounded operator reconciliation fact; it never asserts not-sent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    resolution: Literal["operator_abandoned", "provider_case_closed"]
    evidence_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _closure_receipt_is_valid(self) -> "ShotVideoAttemptClosureReceipt":
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("shot video closure receipt fingerprint is invalid")
        return self


class ShotVideoAttemptArtifactReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    media_type: Literal["video/mp4"] = "video/mp4"
    staging_path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    duration_milliseconds: int = Field(ge=1, le=300_000)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    has_audio_track: bool
    receipt_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("staging_path", mode="before")
    @classmethod
    def _staging_path_is_strict(cls, value: Any) -> str:
        if not isinstance(value, str) or "\\" in value:
            raise ValueError("shot video staging path must be POSIX relative")
        if (
            value.startswith("/")
            or value.startswith("./")
            or "//" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.fullmatch(
                r"logs/drama_shot_videos/episode_[0-9]{2,3}/"
                r"shot_[0-9a-f]{24}/sva_[0-9a-f]{24}\.mp4",
                value,
            )
            is None
        ):
            raise ValueError("shot video staging path must stay in its private root")
        return value

    @field_validator(
        "size_bytes",
        "duration_milliseconds",
        "width",
        "height",
        mode="before",
    )
    @classmethod
    def _artifact_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("has_audio_track", mode="before")
    @classmethod
    def _artifact_audio_flag_is_strict(cls, value: Any) -> bool:
        if type(value) is not bool:
            raise ValueError("has_audio_track must be bool")
        return value

    @model_validator(mode="after")
    def _artifact_receipt_is_valid(self) -> "ShotVideoAttemptArtifactReceipt":
        if self.width * self.height > 40_000_000:
            raise ValueError("shot video artifact pixel count exceeds its limit")
        payload = self.model_dump(exclude={"receipt_fingerprint"})
        if _canonical_sha256(payload) != self.receipt_fingerprint:
            raise ValueError("shot video artifact receipt fingerprint is invalid")
        return self


class ShotVideoAttemptRecord(BaseModel):
    """Durable once-only execution fact for one stable D1 shot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    attempt_id: str = Field(pattern=r"^sva_[0-9a-f]{24}$")
    attempt_no: int = Field(ge=1, le=32)
    spec: ShotVideoAttemptSpec
    status: ShotVideoAttemptStatus
    staging_path: str = Field(min_length=1, max_length=240)
    submission_receipt: Optional[ShotVideoSubmissionReceipt] = None
    terminal_receipt: Optional[ShotVideoTerminalReceipt] = None
    artifact_receipt: Optional[ShotVideoAttemptArtifactReceipt] = None
    closure_receipt: Optional[ShotVideoAttemptClosureReceipt] = None
    candidate_id: Optional[str] = Field(default=None, pattern=r"^svc_[0-9a-f]{24}$")
    candidate_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    post_manifest_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("attempt_no", mode="before")
    @classmethod
    def _attempt_number_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("attempt_no must be a strict integer")
        return value

    @field_validator("staging_path", mode="before")
    @classmethod
    def _record_staging_path_is_strict(cls, value: Any) -> str:
        return ShotVideoAttemptArtifactReceipt._staging_path_is_strict(value)

    @model_validator(mode="after")
    def _record_is_consistent(self) -> "ShotVideoAttemptRecord":
        attempt_basis = {
            "input_fingerprint": self.spec.input_fingerprint,
            "attempt_no": self.attempt_no,
        }
        if self.attempt_id != f"sva_{_canonical_sha256(attempt_basis)[:24]}":
            raise ValueError("shot video attempt id is invalid")
        expected_path = (
            f"logs/drama_shot_videos/episode_{self.spec.episode_no:02d}/"
            f"{self.spec.shot_id}/{self.attempt_id}.mp4"
        )
        if self.staging_path != expected_path:
            raise ValueError("shot video attempt staging path is not canonical")
        needs_submission = self.status in {
            "submitted", "provider_succeeded", "provider_failed", "artifact_received", "succeeded"
        }
        needs_terminal = self.status in {
            "provider_succeeded", "provider_failed", "artifact_received", "succeeded"
        }
        needs_artifact = self.status in {"artifact_received", "succeeded"}
        if needs_submission != (self.submission_receipt is not None):
            raise ValueError("shot video submission receipt does not match status")
        if needs_terminal != (self.terminal_receipt is not None):
            raise ValueError("shot video terminal receipt does not match status")
        if needs_artifact != (self.artifact_receipt is not None):
            raise ValueError("shot video artifact receipt does not match status")
        if (self.status == "closed_unknown") != (self.closure_receipt is not None):
            raise ValueError("shot video closure receipt does not match status")
        if self.submission_receipt is not None and self.terminal_receipt is not None:
            if self.submission_receipt.provider_task_id != self.terminal_receipt.provider_task_id:
                raise ValueError("shot video task identity changed")
            if (
                self.submission_receipt.receipt_fingerprint
                != self.terminal_receipt.submission_receipt_fingerprint
            ):
                raise ValueError("shot video submission receipt identity changed")
            if (self.status == "provider_failed") != (
                self.terminal_receipt.terminal_status == "failed"
            ):
                raise ValueError("shot video provider terminal status is inconsistent")
        if self.artifact_receipt is not None and self.artifact_receipt.staging_path != self.staging_path:
            raise ValueError("shot video artifact receipt uses another staging path")
        if self.submission_receipt is not None and (
            self.submission_receipt.attempt_id != self.attempt_id
            or self.submission_receipt.backend_id != self.spec.submission_gate.backend_id
            or self.submission_receipt.account_fingerprint
            != self.spec.submission_gate.account_fingerprint
            or self.submission_receipt.authorization_fingerprint
            != self.spec.submission_gate.authorization_fingerprint
            or self.submission_receipt.input_fingerprint != self.spec.input_fingerprint
        ):
            raise ValueError("shot video submission receipt binding changed")
        candidate_values = (
            self.candidate_id,
            self.candidate_fingerprint,
            self.post_manifest_fingerprint,
        )
        if (self.status == "succeeded") != all(item is not None for item in candidate_values):
            raise ValueError("shot video candidate identity does not match status")
        if self.status != "succeeded" and any(item is not None for item in candidate_values):
            raise ValueError("unfinished shot video attempt cannot bind a candidate")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("shot video attempt record fingerprint is invalid")
        return self


class EpisodeShotVideoAttemptLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["shot-video-attempts-v1"] = "shot-video-attempts-v1"
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    revision: int = Field(ge=0, le=2_147_483_647)
    attempts: List[ShotVideoAttemptRecord] = Field(max_length=3200)
    ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("season_no", "revision", mode="before")
    @classmethod
    def _ledger_integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("episode_no", mode="before")
    @classmethod
    def _ledger_episode_is_strict(cls, value: Any) -> int:
        return _strict_schema_episode_no(value)

    @field_validator("attempts", mode="before")
    @classmethod
    def _ledger_attempts_are_strict(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("shot video attempts must be a list")
        return value

    @model_validator(mode="after")
    def _ledger_is_consistent(self) -> "EpisodeShotVideoAttemptLedger":
        ids = [item.attempt_id for item in self.attempts]
        if len(ids) != len(set(ids)):
            raise ValueError("shot video attempt ids must be unique")
        per_shot: Dict[str, List[int]] = {}
        paid_authorizations: set[str] = set()
        provider_tasks: set[tuple[str, str, str]] = set()
        provider_results: set[tuple[str, str, str]] = set()
        for attempt in self.attempts:
            if attempt.spec.season_no != self.season_no or attempt.spec.episode_no != self.episode_no:
                raise ValueError("shot video attempt belongs to another episode")
            per_shot.setdefault(attempt.spec.shot_id, []).append(attempt.attempt_no)
            authorization = attempt.spec.submission_gate.authorization_fingerprint
            if attempt.status != "not_sent":
                if authorization in paid_authorizations:
                    raise ValueError("shot video paid authorization was reused")
                paid_authorizations.add(authorization)
            if attempt.submission_receipt is not None:
                task_key = (
                    attempt.spec.submission_gate.backend_id,
                    attempt.spec.submission_gate.account_fingerprint,
                    attempt.submission_receipt.provider_task_id,
                )
                if task_key in provider_tasks:
                    raise ValueError("shot video provider task identity was reused")
                provider_tasks.add(task_key)
            if (
                attempt.terminal_receipt is not None
                and attempt.terminal_receipt.result_token is not None
            ):
                result_key = (
                    attempt.spec.submission_gate.backend_id,
                    attempt.spec.submission_gate.account_fingerprint,
                    attempt.terminal_receipt.result_token,
                )
                if result_key in provider_results:
                    raise ValueError("shot video provider result identity was reused")
                provider_results.add(result_key)
        if any(values != list(range(1, len(values) + 1)) for values in per_shot.values()):
            raise ValueError("shot video attempt numbers must be contiguous per shot")
        payload = self.model_dump(exclude={"ledger_fingerprint"})
        if _canonical_sha256(payload) != self.ledger_fingerprint:
            raise ValueError("shot video attempt ledger fingerprint is invalid")
        return self


class ShotVideoAttemptInspection(BaseModel):
    """Safe four-way recovery projection over the latest attempt per shot."""

    model_config = ConfigDict(extra="forbid", strict=True)

    state: ShotVideoAttemptInspectionState
    reasons: List[str] = Field(max_length=16)
    ledger_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    not_sent_attempt_ids: List[str] = Field(max_length=100)
    unknown_attempt_ids: List[str] = Field(max_length=100)
    submitted_attempt_ids: List[str] = Field(max_length=100)
    terminal_attempt_ids: List[str] = Field(max_length=100)

    @field_validator(
        "reasons",
        "not_sent_attempt_ids",
        "unknown_attempt_ids",
        "submitted_attempt_ids",
        "terminal_attempt_ids",
        mode="before",
    )
    @classmethod
    def _inspection_lists_are_bounded(cls, value: Any, info: Any) -> List[str]:
        if not isinstance(value, list) or len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must be a unique list")
        if info.field_name == "reasons":
            if any(
                not isinstance(item, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item) is None
                for item in value
            ):
                raise ValueError("shot video inspection reasons are invalid")
        elif any(
            not isinstance(item, str)
            or re.fullmatch(r"sva_[0-9a-f]{24}", item) is None
            for item in value
        ):
            raise ValueError("shot video inspection attempt ids are invalid")
        return value

    @model_validator(mode="after")
    def _inspection_partitions_attempts(self) -> "ShotVideoAttemptInspection":
        groups = (
            set(self.not_sent_attempt_ids),
            set(self.unknown_attempt_ids),
            set(self.submitted_attempt_ids),
            set(self.terminal_attempt_ids),
        )
        if any(
            groups[left] & groups[right]
            for left in range(len(groups))
            for right in range(left + 1, len(groups))
        ):
            raise ValueError("shot video attempt outcomes overlap")
        return self


DramaMediaKind = Literal["image", "video", "audio", "compose", "export"]
DramaMediaStage = Literal[
    "image-generate",
    "video-generate",
    "tts-synthesize",
    "compose",
    "edit-export",
]
DramaMediaTaskState = Literal[
    "planned",
    "ready",
    "claimed",
    "submitting",
    "submitted",
    "polling",
    "submission_unknown",
    "downloading",
    "validating",
    "succeeded",
    "failed",
    "cancelling",
    "cancelled",
]
DramaMediaTaskOutcomeCode = Literal[
    "local_failure",
    "provider_rejected",
    "provider_failed",
    "transport_unknown",
    "poll_failed",
    "download_failed",
    "validation_failed",
    "cancel_confirmed",
    "cancel_failed",
    "deadline_exceeded",
    "capacity_exhausted",
    "dependency_failed",
]

_DRAMA_MEDIA_STAGE_KIND = {
    "image-generate": "image",
    "video-generate": "video",
    "tts-synthesize": "audio",
    "compose": "compose",
    "edit-export": "export",
}
_DRAMA_MEDIA_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


class DramaMediaTask(BaseModel):
    """One generic orchestration record; paid receipts remain separate artifacts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    media_kind: DramaMediaKind
    stage: DramaMediaStage
    subject_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    input_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    backend_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    account_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    endpoint_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    dependency_task_ids: List[str] = Field(max_length=32)
    dedupe_key: str = Field(pattern=_SHA256_PATTERN)
    attempt_no: int = Field(ge=1, le=1000)
    state: DramaMediaTaskState
    revision: int = Field(ge=0, le=10_000)
    created_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    updated_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    result_fingerprint: Optional[str] = Field(
        default=None, pattern=_SHA256_PATTERN
    )
    outcome_code: Optional[DramaMediaTaskOutcomeCode] = None
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "episode_no",
        "attempt_no",
        "revision",
        "created_at_ms",
        "updated_at_ms",
        mode="before",
    )
    @classmethod
    def _media_task_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("dependency_task_ids", mode="before")
    @classmethod
    def _media_task_dependencies_are_canonical(cls, value: Any) -> List[str]:
        if (
            not isinstance(value, list)
            or value != sorted(value)
            or len(value) != len(set(value))
            or any(
                not isinstance(item, str)
                or re.fullmatch(r"dmt_[0-9a-f]{24}", item) is None
                for item in value
            )
        ):
            raise ValueError("media task dependencies must be a canonical list")
        return value

    def dedupe_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_no": self.episode_no,
            "media_kind": self.media_kind,
            "stage": self.stage,
            "subject_id": self.subject_id,
            "input_fingerprint": self.input_fingerprint,
            "backend_id": self.backend_id,
            "provider_fingerprint": self.provider_fingerprint,
            "model_fingerprint": self.model_fingerprint,
            "account_fingerprint": self.account_fingerprint,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "dependency_task_ids": self.dependency_task_ids,
        }

    @model_validator(mode="after")
    def _media_task_is_content_addressed(self) -> "DramaMediaTask":
        if _DRAMA_MEDIA_STAGE_KIND[self.stage] != self.media_kind:
            raise ValueError("media task stage does not match its media kind")
        if self.task_id in self.dependency_task_ids:
            raise ValueError("media task cannot depend on itself")
        if self.updated_at_ms < self.created_at_ms:
            raise ValueError("media task update time precedes creation")
        dedupe_key = _canonical_sha256(self.dedupe_payload())
        if self.dedupe_key != dedupe_key:
            raise ValueError("media task dedupe key is invalid")
        task_payload = {
            **self.dedupe_payload(),
            "attempt_no": self.attempt_no,
        }
        task_id = f"dmt_{_canonical_sha256(task_payload)[:24]}"
        if self.task_id != task_id:
            raise ValueError("media task id is invalid")
        if self.state == "succeeded":
            if self.result_fingerprint is None or self.outcome_code is not None:
                raise ValueError("succeeded media task result is invalid")
        elif self.state == "submission_unknown":
            if (
                self.result_fingerprint is not None
                or self.outcome_code != "transport_unknown"
            ):
                raise ValueError("unknown media submission outcome is invalid")
        elif self.state == "cancelled":
            if (
                self.result_fingerprint is not None
                or self.outcome_code != "cancel_confirmed"
            ):
                raise ValueError("cancelled media task outcome is invalid")
        elif self.state == "failed":
            if (
                self.result_fingerprint is not None
                or self.outcome_code is None
                or self.outcome_code in {"transport_unknown", "cancel_confirmed"}
            ):
                raise ValueError("media task outcome is incomplete")
        elif self.result_fingerprint is not None or self.outcome_code is not None:
            raise ValueError("active media task cannot carry a terminal outcome")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("media task record fingerprint is invalid")
        return self


class DramaMediaTaskLedger(BaseModel):
    """Episode-scoped task DAG with strict active-dedupe and cycle checks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    revision: int = Field(ge=0, le=1_000_000)
    tasks: List[DramaMediaTask] = Field(max_length=1000)
    ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", "revision", mode="before")
    @classmethod
    def _media_ledger_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("tasks", mode="before")
    @classmethod
    def _media_ledger_tasks_are_a_list(cls, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError("media task ledger tasks must be a list")
        return value

    @model_validator(mode="after")
    def _media_ledger_is_a_canonical_dag(self) -> "DramaMediaTaskLedger":
        task_ids = [item.task_id for item in self.tasks]
        if task_ids != sorted(task_ids) or len(task_ids) != len(set(task_ids)):
            raise ValueError("media task ledger order or identity is invalid")
        by_id = {item.task_id: item for item in self.tasks}
        active_dedupe: set[str] = set()
        attempts_by_dedupe: Dict[str, List[int]] = {}
        for task in self.tasks:
            if task.episode_no != self.episode_no:
                raise ValueError("media task episode identity is invalid")
            if any(item not in by_id for item in task.dependency_task_ids):
                raise ValueError("media task dependency is missing")
            if any(
                task.created_at_ms < by_id[item].created_at_ms
                for item in task.dependency_task_ids
            ):
                raise ValueError("media task predates its dependency")
            dependencies_succeeded = all(
                by_id[item].state == "succeeded"
                for item in task.dependency_task_ids
            )
            if task.state == "planned":
                if (
                    not task.dependency_task_ids
                    or dependencies_succeeded
                    or any(
                        by_id[item].state in {"failed", "cancelled", "cancelling"}
                        for item in task.dependency_task_ids
                    )
                ):
                    raise ValueError("planned media task is not dependency-blocked")
            elif (
                task.state == "failed"
                and task.outcome_code == "dependency_failed"
            ):
                if not any(
                    by_id[item].state == "failed"
                    for item in task.dependency_task_ids
                ):
                    raise ValueError("dependency failure has no failed dependency")
            elif (
                task.state not in {"cancelling", "cancelled"}
                and not dependencies_succeeded
            ):
                raise ValueError("active media task has incomplete dependencies")
            if task.state not in _DRAMA_MEDIA_TERMINAL_STATES:
                if task.dedupe_key in active_dedupe:
                    raise ValueError("active media task dedupe key is duplicated")
                active_dedupe.add(task.dedupe_key)
            attempts_by_dedupe.setdefault(task.dedupe_key, []).append(
                task.attempt_no
            )
        if any(
            sorted(attempts) != list(range(1, len(attempts) + 1))
            for attempts in attempts_by_dedupe.values()
        ):
            raise ValueError("media task attempts must be contiguous")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("media task dependency cycle is invalid")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency_id in by_id[task_id].dependency_task_ids:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_ids:
            visit(task_id)
        payload = self.model_dump(exclude={"ledger_fingerprint"})
        if _canonical_sha256(payload) != self.ledger_fingerprint:
            raise ValueError("media task ledger fingerprint is invalid")
        return self


_DRAMA_MEDIA_LEASED_STATES = frozenset(
    {
        "claimed",
        "submitting",
        "submitted",
        "polling",
        "downloading",
        "validating",
    }
)


class DramaMediaWorkerLease(BaseModel):
    """Opaque worker ownership bound to one current task revision and lane."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    task_revision: int = Field(ge=1, le=10_000)
    worker_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lease_token_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lane_key: str = Field(pattern=_SHA256_PATTERN)
    lane_capacity: int = Field(ge=1, le=64)
    lease_revision: int = Field(ge=0, le=10_000)
    claimed_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    heartbeat_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    expires_at_ms: int = Field(ge=1, le=9_999_999_999_999)
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "task_revision",
        "lane_capacity",
        "lease_revision",
        "claimed_at_ms",
        "heartbeat_at_ms",
        "expires_at_ms",
        mode="before",
    )
    @classmethod
    def _lease_numbers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _lease_is_canonical(self) -> "DramaMediaWorkerLease":
        if not (
            self.claimed_at_ms
            <= self.heartbeat_at_ms
            < self.expires_at_ms
        ):
            raise ValueError("media worker lease time range is invalid")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("media worker lease fingerprint is invalid")
        return self


class DramaMediaWorkerReleaseReceipt(BaseModel):
    """Content-addressed evidence for one authenticated lease release."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    from_task_revision: int = Field(ge=1, le=10_000)
    to_task_revision: int = Field(ge=1, le=10_000)
    worker_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lease_token_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lease_revision: int = Field(ge=0, le=10_000)
    released_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    before_ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    released_task_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "from_task_revision",
        "to_task_revision",
        "lease_revision",
        "released_at_ms",
        mode="before",
    )
    @classmethod
    def _release_receipt_numbers_are_strict(
        cls, value: Any, info: Any
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _release_receipt_is_canonical(
        self,
    ) -> "DramaMediaWorkerReleaseReceipt":
        if self.to_task_revision != self.from_task_revision + 1:
            raise ValueError("media worker release revision is invalid")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("media worker release fingerprint is invalid")
        return self


class DramaMediaWorkerTransitionReceipt(BaseModel):
    """Authenticated exact-replay evidence for one worker state transition."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    from_task_revision: int = Field(ge=1, le=10_000)
    to_task_revision: int = Field(ge=1, le=10_000)
    from_state: DramaMediaTaskState
    to_state: DramaMediaTaskState
    worker_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lease_token_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    lease_revision: int = Field(ge=0, le=10_000)
    transitioned_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    before_ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    result_fingerprint: Optional[str] = Field(
        default=None, pattern=_SHA256_PATTERN
    )
    outcome_code: Optional[DramaMediaTaskOutcomeCode] = None
    transitioned_task_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    record_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "from_task_revision",
        "to_task_revision",
        "lease_revision",
        "transitioned_at_ms",
        mode="before",
    )
    @classmethod
    def _transition_receipt_numbers_are_strict(
        cls, value: Any, info: Any
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _transition_receipt_is_canonical(
        self,
    ) -> "DramaMediaWorkerTransitionReceipt":
        if self.to_task_revision != self.from_task_revision + 1:
            raise ValueError("media worker transition revision is invalid")
        payload = self.model_dump(exclude={"record_fingerprint"})
        if _canonical_sha256(payload) != self.record_fingerprint:
            raise ValueError("media worker transition fingerprint is invalid")
        return self


class DramaMediaTaskLedgerV2(BaseModel):
    """G2 task ledger: G1 DAG plus atomically committed worker leases."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[2] = 2
    episode_no: int = Field(ge=1, le=MAX_DRAMA_EPISODE_NO)
    revision: int = Field(ge=0, le=1_000_000)
    tasks: List[DramaMediaTask] = Field(max_length=1000)
    leases: List[DramaMediaWorkerLease] = Field(max_length=1000)
    release_receipts: List[DramaMediaWorkerReleaseReceipt] = Field(
        max_length=1000
    )
    transition_receipts: List[DramaMediaWorkerTransitionReceipt] = Field(
        max_length=1000
    )
    ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", "revision", mode="before")
    @classmethod
    def _media_ledger_v2_numbers_are_strict(
        cls, value: Any, info: Any
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator(
        "tasks",
        "leases",
        "release_receipts",
        "transition_receipts",
        mode="before",
    )
    @classmethod
    def _media_ledger_v2_lists_are_strict(
        cls, value: Any, info: Any
    ) -> List[Any]:
        if not isinstance(value, list):
            raise ValueError(f"media task ledger {info.field_name} must be a list")
        return value

    @model_validator(mode="after")
    def _media_ledger_v2_is_canonical(self) -> "DramaMediaTaskLedgerV2":
        legacy_payload = {
            "schema_version": 1,
            "episode_no": self.episode_no,
            "revision": self.revision,
            "tasks": [item.model_dump() for item in self.tasks],
        }
        DramaMediaTaskLedger(
            **legacy_payload,
            ledger_fingerprint=_canonical_sha256(legacy_payload),
        )
        lease_ids = [item.task_id for item in self.leases]
        if lease_ids != sorted(lease_ids) or len(lease_ids) != len(set(lease_ids)):
            raise ValueError("media worker lease order or identity is invalid")
        by_id = {item.task_id: item for item in self.tasks}
        for lease in self.leases:
            task = by_id.get(lease.task_id)
            if (
                task is None
                or task.state not in _DRAMA_MEDIA_LEASED_STATES
                or lease.task_revision != task.revision
            ):
                raise ValueError("media worker lease task binding is invalid")
            lane_payload = {
                "schema_version": 1,
                "provider_fingerprint": task.provider_fingerprint,
                "media_kind": task.media_kind,
            }
            if lease.lane_key != _canonical_sha256(lane_payload):
                raise ValueError("media worker lease lane is invalid")
        leased = set(lease_ids)
        if any(
            task.state in _DRAMA_MEDIA_LEASED_STATES
            and task.task_id not in leased
            for task in self.tasks
        ):
            raise ValueError("active media task has no worker lease")
        receipt_ids = [item.task_id for item in self.release_receipts]
        if (
            receipt_ids != sorted(receipt_ids)
            or len(receipt_ids) != len(set(receipt_ids))
        ):
            raise ValueError("media worker release receipt order is invalid")
        if leased.intersection(receipt_ids):
            raise ValueError("media worker ownership evidence is ambiguous")
        for receipt in self.release_receipts:
            task = by_id.get(receipt.task_id)
            if (
                task is None
                or task.state != "ready"
                or task.revision != receipt.to_task_revision
                or task.record_fingerprint
                != receipt.released_task_fingerprint
            ):
                raise ValueError("media worker release receipt binding is invalid")
        transition_ids = [item.task_id for item in self.transition_receipts]
        if (
            transition_ids != sorted(transition_ids)
            or len(transition_ids) != len(set(transition_ids))
            or set(receipt_ids).intersection(transition_ids)
        ):
            raise ValueError("media worker transition receipt order is invalid")
        for receipt in self.transition_receipts:
            task = by_id.get(receipt.task_id)
            if (
                task is None
                or task.state != receipt.to_state
                or task.revision != receipt.to_task_revision
                or task.result_fingerprint != receipt.result_fingerprint
                or task.outcome_code != receipt.outcome_code
                or task.record_fingerprint
                != receipt.transitioned_task_fingerprint
            ):
                raise ValueError(
                    "media worker transition receipt binding is invalid"
                )
        payload = self.model_dump(exclude={"ledger_fingerprint"})
        if _canonical_sha256(payload) != self.ledger_fingerprint:
            raise ValueError("media task ledger v2 fingerprint is invalid")
        return self


DramaMediaBackendKind = Literal["image", "video", "audio"]
DramaMediaBackendSubmissionMode = Literal["synchronous", "asynchronous"]
DramaMediaBackendMode = Literal[
    "image_generation",
    "image_to_video",
    "reference_to_video",
    "text_to_speech",
]


class DramaMediaBackendResolution(BaseModel):
    """Deep-frozen output dimensions for one generic video capability."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)

    @field_validator("width", "height", mode="before")
    @classmethod
    def _backend_resolution_is_strict(
        cls, value: Any, info: Any
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _backend_resolution_is_bounded(
        self,
    ) -> "DramaMediaBackendResolution":
        if self.width * self.height > 40_000_000:
            raise ValueError("media backend resolution exceeds its pixel limit")
        return self


class DramaMediaBackendCapability(BaseModel):
    """Secret-free G3 capability normalized from one existing C/D/E contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    backend_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    capability_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,31}$")
    media_kind: DramaMediaBackendKind
    stage: Literal["image-generate", "video-generate", "tts-synthesize"]
    submission_mode: DramaMediaBackendSubmissionMode
    supports_poll: bool
    supports_resume: bool
    supports_download: bool
    supports_tail_frame: bool
    max_reference_images: int = Field(ge=0, le=25)
    supported_modes: tuple[DramaMediaBackendMode, ...] = Field(
        min_length=1, max_length=2
    )
    supported_durations_seconds: tuple[int, ...] = Field(max_length=30)
    supported_resolutions: tuple[DramaMediaBackendResolution, ...] = Field(
        max_length=16
    )
    output_media_types: tuple[
        Literal["image/png", "video/mp4", "audio/wav"], ...
    ] = Field(min_length=1, max_length=1)
    sample_rates: tuple[int, ...] = Field(max_length=8)
    max_text_characters: Optional[int] = Field(default=None, ge=1, le=1000)
    source_capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator(
        "supports_poll",
        "supports_resume",
        "supports_download",
        "supports_tail_frame",
        mode="before",
    )
    @classmethod
    def _backend_capability_bools_are_strict(
        cls, value: Any, info: Any
    ) -> bool:
        if type(value) is not bool:
            raise ValueError(f"{info.field_name} must be bool")
        return value

    @field_validator("max_reference_images", mode="before")
    @classmethod
    def _backend_reference_limit_is_strict(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("max_reference_images must be a strict integer")
        return value

    @field_validator("max_text_characters", mode="before")
    @classmethod
    def _backend_text_limit_is_strict(cls, value: Any) -> Optional[int]:
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise ValueError("max_text_characters must be a strict integer")
        return value

    @field_validator(
        "supported_modes",
        "supported_durations_seconds",
        "supported_resolutions",
        "output_media_types",
        "sample_rates",
        mode="before",
    )
    @classmethod
    def _backend_capability_lists_are_strict(
        cls, value: Any, info: Any
    ) -> tuple[Any, ...]:
        if not isinstance(value, list):
            raise ValueError(f"{info.field_name} must be a list")
        return tuple(value)

    @model_validator(mode="after")
    def _backend_capability_is_canonical(
        self,
    ) -> "DramaMediaBackendCapability":
        mode_order = [
            "image_generation",
            "image_to_video",
            "reference_to_video",
            "text_to_speech",
        ]
        if self.supported_modes != tuple(
            item for item in mode_order if item in self.supported_modes
        ) or len(self.supported_modes) != len(set(self.supported_modes)):
            raise ValueError("media backend modes are not canonical")
        if (
            any(
                not isinstance(item, int)
                or isinstance(item, bool)
                or not 1 <= item <= 30
                for item in self.supported_durations_seconds
            )
            or self.supported_durations_seconds
            != tuple(sorted(set(self.supported_durations_seconds)))
        ):
            raise ValueError("media backend durations are not canonical")
        profiles = [
            (item.width, item.height) for item in self.supported_resolutions
        ]
        if profiles != sorted(set(profiles)):
            raise ValueError("media backend resolutions are not canonical")
        if (
            any(
                not isinstance(item, int)
                or isinstance(item, bool)
                or not 8000 <= item <= 48000
                for item in self.sample_rates
            )
            or self.sample_rates != tuple(sorted(set(self.sample_rates)))
        ):
            raise ValueError("media backend sample rates are not canonical")
        expected_stage = {
            "image": "image-generate",
            "video": "video-generate",
            "audio": "tts-synthesize",
        }[self.media_kind]
        if self.stage != expected_stage:
            raise ValueError("media backend stage does not match media kind")
        expected_output = {
            "image": ("image/png",),
            "video": ("video/mp4",),
            "audio": ("audio/wav",),
        }[self.media_kind]
        if self.output_media_types != expected_output:
            raise ValueError("media backend output type is invalid")
        if self.media_kind == "image":
            valid = (
                self.submission_mode == "synchronous"
                and not self.supports_poll
                and not self.supports_resume
                and not self.supports_download
                and not self.supports_tail_frame
                and self.supported_modes == ("image_generation",)
                and not self.supported_durations_seconds
                and not self.supported_resolutions
                and not self.sample_rates
                and self.max_text_characters is None
            )
        elif self.media_kind == "video":
            valid = (
                self.submission_mode == "asynchronous"
                and self.supports_poll
                and self.supports_resume
                and self.supports_download
                and "image_to_video" in self.supported_modes
                and bool(self.supported_durations_seconds)
                and bool(self.supported_resolutions)
                and not self.sample_rates
                and self.max_text_characters is None
            )
        else:
            valid = (
                self.submission_mode == "synchronous"
                and not self.supports_poll
                and not self.supports_resume
                and self.supports_download
                and not self.supports_tail_frame
                and self.max_reference_images == 0
                and self.supported_modes == ("text_to_speech",)
                and not self.supported_durations_seconds
                and not self.supported_resolutions
                and len(self.sample_rates) == 1
                and self.max_text_characters is not None
            )
        if not valid:
            raise ValueError("media backend capability is inconsistent")
        payload = self.model_dump(exclude={"capability_fingerprint"})
        if _canonical_sha256(payload) != self.capability_fingerprint:
            raise ValueError("media backend capability fingerprint is invalid")
        return self


class DramaMediaBackendRegistration(BaseModel):
    """One explicit code-owned `(provider, media, model)` registration."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    media_kind: DramaMediaBackendKind
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,119}$")
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    backend_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    capability: DramaMediaBackendCapability
    registration_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("model_id", mode="before")
    @classmethod
    def _registered_model_id_is_safe(cls, value: Any) -> str:
        if (
            not isinstance(value, str)
            or ".." in value
            or "//" in value
            or value.startswith("/")
            or value.endswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("registered media model id is invalid")
        return value

    @model_validator(mode="after")
    def _registration_is_content_addressed(
        self,
    ) -> "DramaMediaBackendRegistration":
        if (
            self.backend_id != self.capability.backend_id
            or self.media_kind != self.capability.media_kind
        ):
            raise ValueError("media backend registration is inconsistent")
        payload = self.model_dump(exclude={"registration_fingerprint"})
        if _canonical_sha256(payload) != self.registration_fingerprint:
            raise ValueError("media backend registration fingerprint is invalid")
        return self


class DramaMediaBackendRegistrySnapshot(BaseModel):
    """Immutable deterministic registry; it never imports backend code."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    registrations: tuple[DramaMediaBackendRegistration, ...] = Field(
        min_length=1, max_length=256
    )
    registry_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("registrations", mode="before")
    @classmethod
    def _registry_entries_are_strict(
        cls, value: Any
    ) -> tuple[Any, ...]:
        if not isinstance(value, list):
            raise ValueError("media backend registrations must be a list")
        return tuple(value)

    @model_validator(mode="after")
    def _registry_is_canonical(self) -> "DramaMediaBackendRegistrySnapshot":
        keys = [
            (item.provider_id, item.media_kind, item.model_id)
            for item in self.registrations
        ]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("media backend registry key order is invalid")
        backend_owners: Dict[str, set[tuple[str, str]]] = {}
        for item in self.registrations:
            backend_owners.setdefault(item.backend_id, set()).add(
                (item.provider_id, item.media_kind)
            )
        if any(len(owners) != 1 for owners in backend_owners.values()):
            raise ValueError("media backend identity has ambiguous ownership")
        provider_ids: Dict[str, set[str]] = {}
        provider_fingerprints: Dict[str, set[str]] = {}
        model_ids: Dict[tuple[str, str, str], set[str]] = {}
        model_fingerprints: Dict[tuple[str, str, str], set[str]] = {}
        for item in self.registrations:
            provider_ids.setdefault(item.provider_id, set()).add(
                item.provider_fingerprint
            )
            provider_fingerprints.setdefault(
                item.provider_fingerprint, set()
            ).add(item.provider_id)
            owner = (item.provider_id, item.media_kind)
            model_ids.setdefault((*owner, item.model_id), set()).add(
                item.model_fingerprint
            )
            model_fingerprints.setdefault(
                (*owner, item.model_fingerprint), set()
            ).add(item.model_id)
        if (
            any(len(values) != 1 for values in provider_ids.values())
            or any(
                len(values) != 1
                for values in provider_fingerprints.values()
            )
            or any(len(values) != 1 for values in model_ids.values())
            or any(
                len(values) != 1
                for values in model_fingerprints.values()
            )
        ):
            raise ValueError("media backend identity fingerprints are ambiguous")
        payload = self.model_dump(exclude={"registry_fingerprint"})
        if _canonical_sha256(payload) != self.registry_fingerprint:
            raise ValueError("media backend registry fingerprint is invalid")
        return self


class DramaMediaBackendBinding(BaseModel):
    """Attempt-frozen registry resolution bound to one exact generic task."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    task_input_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    backend_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    media_kind: DramaMediaBackendKind
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,119}$")
    provider_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    model_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    capability_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    registration_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    registry_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    registration: DramaMediaBackendRegistration
    binding_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _binding_is_content_addressed(self) -> "DramaMediaBackendBinding":
        if (
            ".." in self.model_id
            or "//" in self.model_id
            or self.model_id.startswith("/")
            or self.model_id.endswith("/")
            or any(
                part in {"", ".", ".."} for part in self.model_id.split("/")
            )
        ):
            raise ValueError("bound media model id is invalid")
        if (
            self.backend_id != self.registration.backend_id
            or self.provider_id != self.registration.provider_id
            or self.media_kind != self.registration.media_kind
            or self.model_id != self.registration.model_id
            or self.provider_fingerprint
            != self.registration.provider_fingerprint
            or self.model_fingerprint
            != self.registration.model_fingerprint
            or self.source_capability_fingerprint
            != self.registration.capability.source_capability_fingerprint
            or self.capability_fingerprint
            != self.registration.capability.capability_fingerprint
            or self.registration_fingerprint
            != self.registration.registration_fingerprint
        ):
            raise ValueError("media backend binding snapshot is inconsistent")
        payload = self.model_dump(exclude={"binding_fingerprint"})
        if _canonical_sha256(payload) != self.binding_fingerprint:
            raise ValueError("media backend binding fingerprint is invalid")
        return self
