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
        if _canonical_sha256(payload) != self.plan_fingerprint:
            raise ValueError("render plan fingerprint does not match its payload")
        return self
