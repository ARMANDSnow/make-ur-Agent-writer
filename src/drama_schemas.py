from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import paths


ShotSize = Literal["特写", "近景", "中景", "全景", "远景"]
CameraMovement = Literal["固定", "推", "拉", "摇", "移", "跟", "升降"]


@dataclass(frozen=True)
class DramaEpisodePaths:
    workspace: str
    episode_no: int
    root: Path
    outputs_dir: Path
    episodes_dir: Path
    setup_path: Path
    storyboard_path: Path


@dataclass(frozen=True)
class DramaCharacterPaths:
    workspace: str
    season_no: int
    root: Path
    data_dir: Path
    characters_dir: Path
    refs_dir: Path
    sheet_path: Path


def episode_paths(workspace: str, *, episode_no: int = 1) -> DramaEpisodePaths:
    if not isinstance(episode_no, int) or isinstance(episode_no, bool) or episode_no < 1:
        raise ValueError("episode_no must be a positive integer")
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
        storyboard_path=episodes_dir / f"{stem}.storyboard.json",
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
    episode_no: int = Field(default=1, ge=1)
    track: str = Field(default="", max_length=20)
    title: str = Field(default="", max_length=80)
    target_duration_seconds: int = Field(default=60, ge=30, le=180)
    hook: Dict[str, Any] = Field(default_factory=dict)
    narrative: str = Field(default="", max_length=2000)
    shots: List[StoryboardShot] = Field(min_length=6, max_length=9)
    soft_warnings: List[str] = Field(default_factory=list)

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
    appearances: List[int] = Field(default_factory=list, max_length=80)
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
    def _appearances_are_positive_ints(cls, value: Any) -> List[int]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("appearances must be a list")
        out: List[int] = []
        for raw in value:
            if isinstance(raw, bool):
                raise ValueError("appearance episode numbers must not be bool")
            number = int(raw)
            if number < 1:
                raise ValueError("appearance episode numbers must be positive")
            out.append(number)
        return out

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
    episode_no: int = Field(default=1, ge=1)
    track: str = Field(default="", max_length=20)
    source_storyboard_title: str = Field(default="", max_length=80)
    characters: List[DramaCharacter] = Field(min_length=1, max_length=8)

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
