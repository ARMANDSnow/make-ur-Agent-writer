from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal

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
