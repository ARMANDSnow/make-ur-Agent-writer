"""Drama episode assembly and read helpers."""

from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .comfy_workflow_exporter import build_workflow
from .drama_schemas import (
    CharacterSheet,
    DramaEpisode,
    DramaEpisodeMeta,
    DramaReview,
    DramaStoryboard,
    episode_paths,
    character_paths,
)
from .schemas import model_to_dict
from .utils import read_json_optional, sha256_data, write_json


EXPORT_FORMATS = frozenset({"json", "md", "csv", "comfy"})
_EPISODE_FILENAME_RE = re.compile(r"^episode_(\d+)\.json$")
_STORYBOARD_FIELDS = (
    "shot_no",
    "shot_size",
    "camera_move",
    "duration_seconds",
    "visual_content",
    "voiceover",
    "dialogue",
    "ai_draw_prompt",
    "is_highlight",
)


@dataclass(frozen=True)
class EpisodeExport:
    format: str
    filename: str
    content_type: str
    path: Path
    body: bytes
    stale: bool


def assemble_episode(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    """Assemble station outputs into the episode JSON export source of truth."""

    setup = _load_setup(workspace, episode_no=episode_no)
    storyboard = _load_storyboard(workspace, episode_no=episode_no)
    characters = _load_characters(workspace)
    review = _load_review(workspace, episode_no=episode_no)
    fingerprint = input_fingerprint(setup=setup, storyboard=storyboard, characters=characters, review=review)

    board = DramaStoryboard(**storyboard)
    core = setup.get("core_setup") if isinstance(setup.get("core_setup"), dict) else {}
    hook = setup.get("hook") if isinstance(setup.get("hook"), dict) else {}
    highlight_shot_no = _highlight_shot_no(storyboard)
    estimated_duration = sum(int(shot.duration_seconds) for shot in board.shots)
    target = int(board.target_duration_seconds)
    episode = DramaEpisode(
        episode_no=episode_no,
        season_no=int(storyboard.get("season_no") or characters.get("season_no") or 1),
        title=str(storyboard.get("title") or setup.get("title") or f"第 {episode_no} 集"),
        logline=str(setup.get("logline") or ""),
        track=str(storyboard.get("track") or setup.get("track") or ""),
        target_duration_seconds=target,
        estimated_duration_seconds=estimated_duration,
        core_setup=core,
        ai_friendly_constraints=_ai_friendly_constraints(storyboard, characters),
        narrative=str(storyboard.get("narrative") or ""),
        storyboard=[_episode_shot(row) for row in storyboard.get("shots", []) if isinstance(row, dict)],
        ending_hook=hook,
        self_check={
            "hook_match_track": True,
            "highlight_shot_no": highlight_shot_no,
            "duration_within_tolerance": abs(estimated_duration - target) <= 3,
        },
    )
    meta = _episode_meta(
        episode_no=episode_no,
        season_no=episode.season_no,
        review=review,
        highlight_shot_no=highlight_shot_no,
        target=target,
        estimate=estimated_duration,
        fingerprint=fingerprint,
    )

    paths = episode_paths(workspace, episode_no=episode_no)
    episode_data = model_to_dict(episode)
    meta_data = model_to_dict(meta)
    write_json(paths.episode_path, episode_data)
    write_json(paths.meta_path, meta_data)
    return {"episode": episode_data, "meta": meta_data, "stale": False}


def list_episodes(workspace: str) -> List[Dict[str, Any]]:
    ep_dir = episode_paths(workspace).episodes_dir
    if not ep_dir.is_dir():
        return []
    items: List[Dict[str, Any]] = []
    for path in ep_dir.glob("episode_*.json"):
        match = _EPISODE_FILENAME_RE.fullmatch(path.name)
        if match is None:
            continue
        episode = read_json_optional(path, None)
        if not isinstance(episode, dict):
            continue
        no = episode.get("episode_no")
        if not isinstance(no, int) or isinstance(no, bool):
            continue
        try:
            episode_no = int(no)
            expected = episode_paths(workspace, episode_no=episode_no).episode_path
        except (TypeError, ValueError):
            continue
        if path != expected:
            continue
        meta = read_json_optional(episode_paths(workspace, episode_no=episode_no).meta_path, None)
        stale = is_episode_stale(workspace, episode_no=episode_no)
        items.append(
            {
                "episode_no": episode_no,
                "title": episode.get("title", ""),
                "track": episode.get("track", ""),
                "estimated_duration_seconds": episode.get("estimated_duration_seconds", 0),
                "verdict": meta.get("verdict") if isinstance(meta, dict) else "",
                "needs_human_review": bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False,
                "stale": stale,
            }
        )
    return sorted(items, key=lambda item: item["episode_no"])


def to_markdown_table(episode: Dict[str, Any]) -> str:
    """Render one assembled episode as a deterministic Markdown document."""

    data = model_to_dict(DramaEpisode(**episode))
    hook = data.get("ending_hook") if isinstance(data.get("ending_hook"), dict) else {}
    title = data.get("title") or f"第 {data['episode_no']} 集"
    lines = [
        f"# {_markdown_cell(title)}",
        "",
        f"- episode_no: {data['episode_no']}",
        f"- season_no: {data['season_no']}",
        f"- track: {_markdown_cell(data.get('track', ''))}",
        f"- duration: {data['estimated_duration_seconds']}s / {data['target_duration_seconds']}s",
        f"- ending_hook: {_markdown_cell(hook.get('type', ''))} - {_markdown_cell(hook.get('content', ''))}",
        "",
        "## Narrative",
        "",
        html.escape(str(data.get("narrative") or ""), quote=False),
        "",
        "## Storyboard",
        "",
        "| " + " | ".join(_STORYBOARD_FIELDS) + " |",
        "| " + " | ".join("---" for _ in _STORYBOARD_FIELDS) + " |",
    ]
    for raw in data.get("storyboard", []):
        row = raw if isinstance(raw, dict) else {}
        lines.append(
            "| "
            + " | ".join(_markdown_cell(_export_cell(row.get(field))) for field in _STORYBOARD_FIELDS)
            + " |"
        )
    return "\n".join(lines) + "\n"


def to_csv(episode: Dict[str, Any]) -> bytes:
    """Render storyboard CSV with an Excel-friendly UTF-8 BOM."""

    data = model_to_dict(DramaEpisode(**episode))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(_STORYBOARD_FIELDS),
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    writer.writeheader()
    for raw in data.get("storyboard", []):
        row = raw if isinstance(raw, dict) else {}
        writer.writerow({field: _csv_cell(row.get(field)) for field in _STORYBOARD_FIELDS})
    return stream.getvalue().encode("utf-8-sig")


def export_episode(
    workspace: str, *, episode_no: int = 1, format: str
) -> EpisodeExport:
    """Generate one whitelisted export from the assembled episode source.

    Derived formats are atomically persisted beside ``episode_NN.json``.
    The JSON export is the already-assembled source file itself and is never
    reconstructed from mutable station artifacts.
    """

    if not isinstance(format, str) or format not in EXPORT_FORMATS:
        raise ValueError("format must be one of: json, md, csv, comfy")
    ep = episode_paths(workspace, episode_no=episode_no)
    episode_no = ep.episode_no
    try:
        source_payload = ep.episode_path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError(f"missing assembled episode: {ep.episode_path}") from exc
    try:
        episode = json.loads(source_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("assembled episode must be valid UTF-8 JSON") from exc
    if not isinstance(episode, dict):
        raise FileNotFoundError(f"missing assembled episode: {ep.episode_path}")
    source_episode_no = episode.get("episode_no")
    if (
        not isinstance(source_episode_no, int)
        or isinstance(source_episode_no, bool)
        or source_episode_no != episode_no
    ):
        raise ValueError("assembled episode_no does not match requested episode")
    validated = model_to_dict(DramaEpisode(**episode))

    stem = f"episode_{episode_no:02d}"
    if format == "json":
        target = ep.episode_path
        payload = source_payload
        content_type = "application/json; charset=utf-8"
    elif format == "md":
        target = ep.episodes_dir / f"{stem}.storyboard.md"
        payload = to_markdown_table(validated).encode("utf-8")
        content_type = "text/markdown; charset=utf-8"
        _write_bytes_atomic(target, payload)
    elif format == "csv":
        target = ep.episodes_dir / f"{stem}.storyboard.csv"
        payload = to_csv(validated)
        content_type = "text/csv; charset=utf-8"
        _write_bytes_atomic(target, payload)
    else:
        target = ep.episodes_dir / f"{stem}.comfy.json"
        characters = read_json_optional(character_paths(workspace).sheet_path, None)
        if not isinstance(characters, dict):
            raise FileNotFoundError("station 4 must complete before Comfy export")
        workflow = build_workflow(validated, characters)
        payload = (
            json.dumps(workflow, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
        content_type = "application/json; charset=utf-8"
        _write_bytes_atomic(target, payload)

    return EpisodeExport(
        format=format,
        filename=target.name,
        content_type=content_type,
        path=target,
        body=payload,
        stale=is_episode_stale(workspace, episode_no=episode_no),
    )


def _export_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _csv_cell(value: Any) -> str:
    """Neutralize spreadsheet formulas while preserving visible text."""

    text = _export_cell(value)
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _markdown_cell(value: Any) -> str:
    return (
        html.escape(_export_cell(value), quote=False)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(
        path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}"
    )
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def episode_detail(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    paths = episode_paths(workspace, episode_no=episode_no)
    episode = read_json_optional(paths.episode_path, None)
    if not isinstance(episode, dict):
        raise FileNotFoundError(f"missing assembled episode: {paths.episode_path}")
    episode_model = DramaEpisode(**episode)
    if episode_model.episode_no != episode_no:
        raise ValueError("assembled episode_no does not match requested episode")
    episode = model_to_dict(episode_model)
    meta = read_json_optional(paths.meta_path, None)
    review = read_json_optional(paths.review_path, None)
    characters = read_json_optional(character_paths(workspace).sheet_path, None)
    if isinstance(meta, dict):
        meta_model = DramaEpisodeMeta(**meta)
        if meta_model.episode_no != episode_no:
            raise ValueError("episode meta number does not match requested episode")
        meta = model_to_dict(meta_model)
    if isinstance(review, dict):
        review_model = DramaReview(**review)
        if review_model.episode_no != episode_no:
            raise ValueError("episode review number does not match requested episode")
        review = model_to_dict(review_model)
    stale = is_episode_stale(workspace, episode_no=episode_no)
    return {
        "episode": episode,
        "meta": meta if isinstance(meta, dict) else None,
        "review": review if isinstance(review, dict) else None,
        "characters": characters if isinstance(characters, dict) else None,
        "stale": stale,
    }


def is_episode_stale(workspace: str, *, episode_no: int = 1) -> bool:
    paths = episode_paths(workspace, episode_no=episode_no)
    meta = read_json_optional(paths.meta_path, None)
    if not isinstance(meta, dict):
        return True
    previous = str(meta.get("input_fingerprint") or "")
    if not previous:
        return True
    try:
        setup = _load_setup(workspace, episode_no=episode_no)
        storyboard = _load_storyboard(workspace, episode_no=episode_no)
        characters = _load_characters(workspace)
        review = _load_review(workspace, episode_no=episode_no)
    except (FileNotFoundError, ValueError):
        return True
    return input_fingerprint(setup=setup, storyboard=storyboard, characters=characters, review=review) != previous


def input_fingerprint(
    *,
    setup: Dict[str, Any],
    storyboard: Dict[str, Any],
    characters: Dict[str, Any],
    review: Dict[str, Any],
) -> str:
    return sha256_data(
        {
            "setup": setup,
            "storyboard": storyboard,
            "characters": characters,
            "review": review,
        }
    )


def _load_setup(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    path = episode_paths(workspace, episode_no=episode_no).setup_path
    data = read_json_optional(path, None)
    if not isinstance(data, dict):
        raise FileNotFoundError("station 2 must complete before episode assembly")
    core = data.get("core_setup")
    hook = data.get("hook")
    if not isinstance(core, dict) or not core.get("protagonist"):
        raise ValueError("station 1 output missing core_setup.protagonist")
    if not isinstance(hook, dict) or not hook.get("type"):
        raise ValueError("station 2 must complete before episode assembly")
    return data


def _load_storyboard(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    path = episode_paths(workspace, episode_no=episode_no).storyboard_path
    data = read_json_optional(path, None)
    if not isinstance(data, dict):
        raise FileNotFoundError("station 3 must complete before episode assembly")
    board = DramaStoryboard(**data)
    if board.episode_no != episode_no:
        raise ValueError("station 3 storyboard episode does not match requested episode")
    return data


def _load_characters(workspace: str) -> Dict[str, Any]:
    path = character_paths(workspace).sheet_path
    data = read_json_optional(path, None)
    if not isinstance(data, dict):
        raise FileNotFoundError("station 4 must complete before episode assembly")
    CharacterSheet(**data)
    return data


def _load_review(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    path = episode_paths(workspace, episode_no=episode_no).review_path
    data = read_json_optional(path, None)
    if not isinstance(data, dict):
        raise FileNotFoundError("drama review must complete before episode assembly")
    DramaReview(**data)
    return data


def _episode_meta(
    *,
    episode_no: int,
    season_no: int,
    review: Dict[str, Any],
    highlight_shot_no: int | None,
    target: int,
    estimate: int,
    fingerprint: str,
) -> DramaEpisodeMeta:
    review_model = DramaReview(**review)
    return DramaEpisodeMeta(
        episode_no=episode_no,
        season_no=season_no,
        verdict=review_model.verdict,
        rewrite_count=0,
        needs_human_review=review_model.needs_human_review,
        cost_cny=0,
        agent_reviews=[review_model],
        highlight_shot_no=highlight_shot_no,
        duration_estimate_vs_target={"target": target, "estimate": estimate, "delta": estimate - target},
        input_fingerprint=fingerprint,
        stale=False,
    )


def _highlight_shot_no(storyboard: Dict[str, Any]) -> int | None:
    for raw in storyboard.get("shots", []):
        if isinstance(raw, dict) and raw.get("is_highlight"):
            try:
                return int(raw.get("shot_no"))
            except (TypeError, ValueError):
                return None
    return None


def _ai_friendly_constraints(storyboard: Dict[str, Any], characters: Dict[str, Any]) -> Dict[str, Any]:
    shots = storyboard.get("shots") if isinstance(storyboard.get("shots"), list) else []
    character_rows = characters.get("characters") if isinstance(characters.get("characters"), list) else []
    return {
        "scene_count": min(len(shots), 9),
        "main_character_count": len(character_rows),
        "max_dialog_chars_per_line": 15,
        "narrative_mode": "纯画面驱动",
    }


def _episode_shot(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "shot_no": raw.get("shot_no"),
        "shot_size": raw.get("shot_size"),
        "camera_move": raw.get("camera_movement"),
        "duration_seconds": raw.get("duration_seconds"),
        "visual_content": raw.get("visual"),
        "voiceover": raw.get("narration") or "",
        "dialogue": raw.get("dialogue") or "",
        "ai_draw_prompt": raw.get("ai_draw_prompt") or "",
        "motion_prompt": None,
        "camera_movement_for_video": None,
        "is_highlight": bool(raw.get("is_highlight")),
    }
