"""Drama episode assembly and read helpers."""

from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from . import paths as workspace_paths
from .comfy_workflow_exporter import build_workflow
from .drama_schemas import (
    CharacterSheet,
    DramaEpisode,
    DramaEpisodeMeta,
    DramaReview,
    DramaStoryboard,
    episode_paths,
    character_paths,
    normalize_episode_no,
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

INPUT_FINGERPRINT_VERSION = 2
MAX_RENDER_SOURCE_BYTES = 16_000_000


@dataclass(frozen=True)
class EpisodeExport:
    format: str
    filename: str
    content_type: str
    path: Path
    body: bytes
    stale: bool


@dataclass(frozen=True)
class FreshEpisodeSnapshot:
    """Validated creative inputs that may safely cross into the render layer."""

    workspace: str
    episode: Dict[str, Any]
    meta: Dict[str, Any]
    characters: Dict[str, Any]
    character_projection: Dict[str, Any]
    creative_revision: str
    creative_revision_version: int
    source_episode_sha256: str
    frozen_character_ids: tuple[str, ...]
    character_projection_fingerprint: str
    snapshot_fingerprint: str


def _validate_render_workspace_root(root: Path) -> None:
    try:
        info = root.lstat()
    except FileNotFoundError:
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("render workspace root must be a real directory")
    try:
        root.resolve(strict=True).relative_to(
            workspace_paths.WORKSPACE_DIR.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise ValueError("render workspace root escapes the workspace directory") from exc


def _read_strict_workspace_bytes(
    root: Path,
    path: Path,
    *,
    maximum: int,
) -> bytes:
    """Read one bounded regular file through no-follow directory descriptors."""

    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
        raise ValueError("strict workspace read maximum is invalid")
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("render source path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("render source path is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if nofollow is None or directory is None:
        raise ValueError("strict no-follow workspace reads are unavailable")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        for part in relative.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | directory | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=directory_fd,
        )
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > maximum:
            raise ValueError("render source file shape or size is invalid")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > maximum:
            raise ValueError("render source file changed or exceeded its size limit")
        return payload
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError("render source file cannot be read safely") from exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _reject_render_json_duplicates(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("render source JSON contains duplicate members")
        output[key] = value
    return output


def _reject_render_json_constant(_value: str) -> None:
    raise ValueError("render source JSON contains a non-finite number")


def _parse_render_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("render source JSON contains a non-finite number")
    return number


def _validate_render_json_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("render source JSON contains a non-finite number")
    if isinstance(value, dict):
        for nested in value.values():
            _validate_render_json_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_render_json_finite(nested)


def _read_strict_workspace_json(root: Path, path: Path, *, maximum: int) -> Any:
    try:
        text = _read_strict_workspace_bytes(root, path, maximum=maximum).decode("utf-8")
        data = json.loads(
            text,
            object_pairs_hook=_reject_render_json_duplicates,
            parse_constant=_reject_render_json_constant,
            parse_float=_parse_render_json_float,
        )
        _validate_render_json_finite(data)
        return data
    except FileNotFoundError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("render source JSON is invalid") from exc


def _fresh_snapshot_fingerprint(
    *,
    episode: Dict[str, Any],
    meta: Dict[str, Any],
    character_projection: Dict[str, Any],
    frozen_character_ids: tuple[str, ...],
) -> str:
    return sha256_data(
        {
            "snapshot_version": 1,
            "episode": episode,
            "approval_lineage": {
                "creative_revision": meta["input_fingerprint"],
                "creative_revision_version": meta["input_fingerprint_version"],
                "source_episode_sha256": meta["episode_sha256"],
                "verdict": meta["verdict"],
                "frozen_character_ids": list(frozen_character_ids),
            },
            "character_projection": character_projection,
        }
    )


def load_fresh_episode_for_render(
    workspace: str,
    *,
    episode_no: int = 1,
) -> FreshEpisodeSnapshot:
    """Return one approved, hash-bound episode and its frozen cast.

    This is intentionally stricter than the historical detail reader: render
    facts must never be derived from a stale assembled episode or an unproven
    season-wide character fallback.
    """

    number = normalize_episode_no(episode_no)
    root = workspace_paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("drama episode path does not match the workspace")

    raw_episode = _read_strict_workspace_json(
        root,
        ep.episode_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    raw_meta = _read_strict_workspace_json(
        root,
        ep.meta_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    raw_characters = _read_strict_workspace_json(
        root,
        character_paths(workspace).sheet_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    raw_setup = _read_strict_workspace_json(
        root,
        ep.setup_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    raw_storyboard = _read_strict_workspace_json(
        root,
        ep.storyboard_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    raw_review = _read_strict_workspace_json(
        root,
        ep.review_path,
        maximum=MAX_RENDER_SOURCE_BYTES,
    )
    missing = []
    if not isinstance(raw_episode, dict):
        missing.append("episode")
    if not isinstance(raw_meta, dict):
        missing.append("episode meta")
    if not isinstance(raw_characters, dict):
        missing.append("character sheet")
    if not isinstance(raw_setup, dict):
        missing.append("episode setup")
    if not isinstance(raw_storyboard, dict):
        missing.append("episode storyboard")
    if not isinstance(raw_review, dict):
        missing.append("episode review")
    if missing:
        raise FileNotFoundError("fresh render source is missing: " + ", ".join(missing))

    try:
        episode = model_to_dict(DramaEpisode.model_validate(raw_episode, strict=True))
        meta = model_to_dict(DramaEpisodeMeta.model_validate(raw_meta, strict=True))
        characters = model_to_dict(CharacterSheet.model_validate(raw_characters, strict=True))
        storyboard_model = DramaStoryboard.model_validate(raw_storyboard, strict=True)
        review_model = DramaReview.model_validate(raw_review, strict=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("fresh render source schema is invalid") from exc

    # Pre-v2 setup files did not always persist these two identity fields.
    # Their approved meta fingerprint still binds the exact file, while the
    # episode/storyboard/review carry the requested identity explicitly.
    setup_episode_no = raw_setup.get("episode_no", number)
    setup_season_no = raw_setup.get("season_no", 1)
    setup_duration = raw_setup.get("target_duration_seconds")
    setup_core = raw_setup.get("core_setup")
    setup_hook = raw_setup.get("hook")
    if (
        type(setup_episode_no) is not int
        or type(setup_season_no) is not int
        or type(setup_duration) is not int
        or not isinstance(raw_setup.get("track"), str)
        or not isinstance(setup_core, dict)
        or not setup_core.get("protagonist")
        or not isinstance(setup_hook, dict)
        or not setup_hook.get("type")
    ):
        raise ValueError("fresh render source schema is invalid")

    if (
        episode["episode_no"] != number
        or meta["episode_no"] != number
        or setup_episode_no != number
        or storyboard_model.episode_no != number
        or review_model.episode_no != number
        or episode["season_no"] != meta["season_no"]
        or setup_season_no != episode["season_no"]
        or storyboard_model.season_no != episode["season_no"]
        or review_model.season_no != episode["season_no"]
        or characters["season_no"] != episode["season_no"]
        or storyboard_model.track != raw_setup["track"]
        or storyboard_model.target_duration_seconds != setup_duration
    ):
        raise ValueError("fresh render source identity does not match")
    if meta["verdict"] != "Approve" or review_model.verdict != "Approve":
        raise ValueError("fresh render source must have an Approve verdict")
    if (
        not meta["episode_sha256"]
        or meta["episode_sha256"] != sha256_data(episode)
    ):
        raise ValueError("assembled episode content does not match its metadata")
    frozen_ids = (
        list(meta["character_fingerprint_ids"])
        if meta["input_fingerprint_version"] == INPUT_FINGERPRINT_VERSION
        else None
    )
    try:
        projection = episode_character_projection(
            characters,
            episode_no=number,
            character_ids=frozen_ids,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("assembled episode character projection is invalid") from exc
    projection_ids = tuple(
        str(row["id"])
        for row in projection.get("characters", [])
        if isinstance(row, dict)
    )
    if not 1 <= len(projection_ids) <= 8 or len(projection_ids) != len(set(projection_ids)):
        raise ValueError("assembled episode character projection is invalid")
    if frozen_ids is not None:
        if len(frozen_ids) != len(projection_ids) or set(frozen_ids) != set(projection_ids):
            raise ValueError("assembled episode character projection is invalid")
        bound_ids = tuple(frozen_ids)
    else:
        bound_ids = projection_ids

    expected_review_fingerprint = review_input_fingerprint(
        setup=raw_setup,
        storyboard=raw_storyboard,
        characters=raw_characters,
        episode_no=number,
        character_ids=list(bound_ids),
    )
    if review_model.input_fingerprint and (
        review_model.input_fingerprint != expected_review_fingerprint
    ):
        raise ValueError("assembled episode review lineage is stale")
    if frozen_ids is not None and not review_model.input_fingerprint:
        raise ValueError("assembled episode review lineage is stale")
    expected_input_fingerprint = input_fingerprint(
        setup=raw_setup,
        storyboard=raw_storyboard,
        characters=raw_characters,
        review=raw_review,
        episode_no=number,
        version=int(meta["input_fingerprint_version"]),
        character_ids=(list(bound_ids) if frozen_ids is not None else None),
    )
    if (
        not meta["input_fingerprint"]
        or meta["input_fingerprint"] != expected_input_fingerprint
    ):
        raise ValueError("assembled episode is stale; review and assemble it again")

    return FreshEpisodeSnapshot(
        workspace=workspace,
        episode=episode,
        meta=meta,
        characters=characters,
        character_projection=projection,
        creative_revision=str(meta["input_fingerprint"]),
        creative_revision_version=int(meta["input_fingerprint_version"]),
        source_episode_sha256=str(meta["episode_sha256"]),
        frozen_character_ids=bound_ids,
        character_projection_fingerprint=sha256_data(projection),
        snapshot_fingerprint=_fresh_snapshot_fingerprint(
            episode=episode,
            meta=meta,
            character_projection=projection,
            frozen_character_ids=bound_ids,
        ),
    )


def assemble_episode(
    workspace: str,
    *,
    episode_no: int = 1,
    character_ids: List[str] | None = None,
) -> Dict[str, Any]:
    """Assemble station outputs into the episode JSON export source of truth."""

    setup = _load_setup(workspace, episode_no=episode_no)
    storyboard = _load_storyboard(workspace, episode_no=episode_no)
    characters = _load_characters(workspace)
    review = _load_review(workspace, episode_no=episode_no)
    review_model = DramaReview(**review)
    if review_model.verdict != "Approve":
        raise ValueError("drama review verdict must be Approve before episode assembly")
    fingerprint_ids = (
        list(character_ids)
        if character_ids is not None
        else episode_character_fingerprint_ids(
            characters, episode_no=episode_no
        )
    )
    character_projection = episode_character_projection(
        characters,
        episode_no=episode_no,
        character_ids=fingerprint_ids,
    )
    expected_review_fingerprint = review_input_fingerprint(
        setup=setup,
        storyboard=storyboard,
        characters=characters,
        episode_no=episode_no,
        character_ids=fingerprint_ids,
    )
    upgrading_legacy_review = False
    if not review_model.input_fingerprint:
        if not _legacy_review_matches_assembled_episode(
            workspace,
            episode_no=episode_no,
            setup=setup,
            storyboard=storyboard,
            characters=characters,
            review=review,
        ):
            raise ValueError("drama review is missing its input fingerprint; run review again")
        review = model_to_dict(review_model)
        review["input_fingerprint"] = expected_review_fingerprint
        review_model = DramaReview(**review)
        review = model_to_dict(review_model)
        upgrading_legacy_review = True
    if review_model.input_fingerprint != expected_review_fingerprint:
        raise ValueError("drama review inputs changed; run review again before episode assembly")
    fingerprint = input_fingerprint(
        setup=setup,
        storyboard=storyboard,
        characters=characters,
        review=review,
        episode_no=episode_no,
        version=INPUT_FINGERPRINT_VERSION,
        character_ids=fingerprint_ids,
    )

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
        ai_friendly_constraints=_ai_friendly_constraints(
            storyboard, character_projection
        ),
        narrative=str(storyboard.get("narrative") or ""),
        storyboard=[_episode_shot(row) for row in storyboard.get("shots", []) if isinstance(row, dict)],
        ending_hook=hook,
        self_check={
            "hook_match_track": True,
            "highlight_shot_no": highlight_shot_no,
            "duration_within_tolerance": abs(estimated_duration - target) <= 3,
        },
    )
    episode_data = model_to_dict(episode)
    meta = _episode_meta(
        episode_no=episode_no,
        season_no=episode.season_no,
        review=review,
        highlight_shot_no=highlight_shot_no,
        target=target,
        estimate=estimated_duration,
        fingerprint=fingerprint,
        character_fingerprint_ids=fingerprint_ids,
        episode_sha256=sha256_data(episode_data),
    )

    paths = episode_paths(workspace, episode_no=episode_no)
    meta_data = model_to_dict(meta)
    targets = (paths.review_path, paths.episode_path, paths.meta_path)
    snapshots = {
        path: path.read_bytes() if path.is_file() else None
        for path in targets
    }
    try:
        if upgrading_legacy_review:
            write_json(paths.review_path, review)
        write_json(paths.episode_path, episode_data)
        write_json(paths.meta_path, meta_data)
    except BaseException:
        for path, payload in snapshots.items():
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                _write_bytes_atomic(path, payload)
        raise
    return {"episode": episode_data, "meta": meta_data, "stale": False}


def _legacy_review_matches_assembled_episode(
    workspace: str,
    *,
    episode_no: int,
    setup: Dict[str, Any],
    storyboard: Dict[str, Any],
    characters: Dict[str, Any],
    review: Dict[str, Any],
) -> bool:
    """Prove an old approved review was already assembled with these inputs.

    Iterations before review-lineage hashes persisted an assembly fingerprint
    that included the raw review.  That signed local relationship is the only
    safe basis for an in-place compatibility upgrade; missing, stale or
    hand-mixed artifacts must be reviewed again.
    """

    paths = episode_paths(workspace, episode_no=episode_no)
    episode = read_json_optional(paths.episode_path, None)
    meta = read_json_optional(paths.meta_path, None)
    if not isinstance(episode, dict) or not isinstance(meta, dict):
        return False
    try:
        episode_data = model_to_dict(DramaEpisode(**episode))
        meta_model = DramaEpisodeMeta(**meta)
    except (TypeError, ValueError):
        return False
    if (
        meta_model.episode_no != episode_no
        or meta_model.verdict != "Approve"
        or meta_model.episode_sha256 != sha256_data(episode_data)
        or not meta_model.input_fingerprint
    ):
        return False
    version = meta_model.input_fingerprint_version
    try:
        current = input_fingerprint(
            setup=setup,
            storyboard=storyboard,
            characters=characters,
            review=review,
            episode_no=episode_no,
            version=version,
            character_ids=(
                meta_model.character_fingerprint_ids
                if version == INPUT_FINGERPRINT_VERSION
                else None
            ),
        )
    except (TypeError, ValueError):
        return False
    return current == meta_model.input_fingerprint


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
    review = _load_review(workspace, episode_no=episode_no)
    if DramaReview(**review).verdict != "Approve" or is_episode_stale(
        workspace, episode_no=episode_no
    ):
        raise ValueError("assembled episode is stale or no longer approved")

    stem = f"episode_{episode_no:02d}"
    if format == "json":
        target = ep.episode_path
        # Never pass through unmodelled fields from a hand-edited or legacy
        # source file.  All public JSON exports use the same schema projection
        # as the other formats and the season package.
        payload = (
            json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode("utf-8")
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
        meta_raw = read_json_optional(ep.meta_path, None)
        if not isinstance(meta_raw, dict):
            raise ValueError("assembled episode metadata is missing")
        meta = DramaEpisodeMeta(**meta_raw)
        if meta.episode_no != episode_no:
            raise ValueError("episode meta number does not match requested episode")
        frozen_ids = (
            list(meta.character_fingerprint_ids)
            if meta.input_fingerprint_version == INPUT_FINGERPRINT_VERSION
            else None
        )
        projection = episode_character_projection(
            characters,
            episode_no=episode_no,
            character_ids=frozen_ids,
        )
        workflow = build_workflow(validated, projection)
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
    meta = read_json_optional(paths.meta_path, None)
    review = read_json_optional(paths.review_path, None)
    characters = read_json_optional(character_paths(workspace).sheet_path, None)
    if not isinstance(episode, dict) and not isinstance(review, dict):
        raise FileNotFoundError(f"missing assembled episode: {paths.episode_path}")
    if isinstance(episode, dict):
        episode_model = DramaEpisode(**episode)
        if episode_model.episode_no != episode_no:
            raise ValueError("assembled episode_no does not match requested episode")
        episode = model_to_dict(episode_model)
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
    stale = True if not isinstance(episode, dict) else is_episode_stale(
        workspace, episode_no=episode_no
    )
    return {
        "episode": episode if isinstance(episode, dict) else None,
        "meta": meta if isinstance(meta, dict) else None,
        "review": review if isinstance(review, dict) else None,
        "characters": characters if isinstance(characters, dict) else None,
        "stale": stale,
    }


def is_episode_stale(workspace: str, *, episode_no: int = 1) -> bool:
    paths = episode_paths(workspace, episode_no=episode_no)
    meta_raw = read_json_optional(paths.meta_path, None)
    if not isinstance(meta_raw, dict):
        return True
    try:
        meta = DramaEpisodeMeta(**meta_raw)
    except (TypeError, ValueError):
        return True
    if (
        meta.episode_no != episode_no
        or meta.verdict != "Approve"
        or not meta.input_fingerprint
    ):
        return True
    try:
        setup = _load_setup(workspace, episode_no=episode_no)
        storyboard = _load_storyboard(workspace, episode_no=episode_no)
        characters = _load_characters(workspace)
        review = _load_review(workspace, episode_no=episode_no)
    except (FileNotFoundError, ValueError):
        return True
    if meta.season_no != int(characters.get("season_no") or 1):
        return True
    version = meta.input_fingerprint_version
    try:
        current = input_fingerprint(
            setup=setup,
            storyboard=storyboard,
            characters=characters,
            review=review,
            episode_no=episode_no,
            version=version,
            character_ids=(
                list(meta.character_fingerprint_ids)
                if version == INPUT_FINGERPRINT_VERSION
                else None
            ),
        )
    except (TypeError, ValueError):
        return True
    return current != meta.input_fingerprint


def input_fingerprint(
    *,
    setup: Dict[str, Any],
    storyboard: Dict[str, Any],
    characters: Dict[str, Any],
    review: Dict[str, Any],
    episode_no: int | None = None,
    version: int = 1,
    character_ids: List[str] | None = None,
) -> str:
    if not isinstance(version, int) or isinstance(version, bool) or version not in (1, INPUT_FINGERPRINT_VERSION):
        raise ValueError("unsupported drama input fingerprint version")
    character_payload = characters
    if version == INPUT_FINGERPRINT_VERSION:
        if episode_no is None:
            raise ValueError("episode_no is required for fingerprint v2")
        character_payload = _episode_character_fingerprint_view(
            characters,
            episode_no=episode_no,
            character_ids=character_ids,
        )
    return sha256_data(
        {
            "setup": setup,
            "storyboard": storyboard,
            "characters": character_payload,
            "review": review,
        }
    )


def review_input_fingerprint(
    *,
    setup: Dict[str, Any],
    storyboard: Dict[str, Any],
    characters: Dict[str, Any],
    episode_no: int,
    character_ids: List[str] | None = None,
) -> str:
    """Hash inputs that the text reviewer actually evaluates.

    Reference-image provenance is intentionally excluded: it is generated only
    after text approval and does not change the reviewed character identity.
    Season-level bookkeeping is also excluded by the episode-scoped view.
    """

    number = normalize_episode_no(episode_no)
    character_view = _episode_character_fingerprint_view(
        characters,
        episode_no=number,
        character_ids=character_ids,
    )
    for row in character_view.get("characters", []):
        if isinstance(row, dict):
            row.pop("reference_images", None)
    return sha256_data({
        "setup": setup,
        "storyboard": storyboard,
        "characters": character_view,
        "episode_no": number,
    })


def _episode_character_fingerprint_view(
    characters: Dict[str, Any], *, episode_no: int, character_ids: List[str] | None = None
) -> Dict[str, Any]:
    """Return only character inputs capable of changing one episode."""

    return episode_character_projection(
        characters,
        episode_no=episode_no,
        character_ids=character_ids,
    )


def episode_character_projection(
    characters: Dict[str, Any],
    *,
    episode_no: int,
    character_ids: List[str] | None = None,
) -> Dict[str, Any]:
    """Return the validated, immutable cast projection for one episode.

    ``character_ids`` is the frozen assembly lineage when present.  It is
    validated strictly instead of being treated as a hint: a missing or
    duplicated id must never widen the projection back to the season library.
    """

    number = normalize_episode_no(episode_no)
    sheet = model_to_dict(CharacterSheet(**characters))
    rows = sheet["characters"]
    if character_ids is None:
        selected_ids = episode_character_fingerprint_ids(
            sheet, episode_no=number
        )
    else:
        if not isinstance(character_ids, list):
            raise ValueError("episode character ids must be a list")
        if not character_ids:
            raise ValueError("episode character ids must not be empty")
        if any(not isinstance(item, str) for item in character_ids):
            raise ValueError("episode character ids must contain character ids")
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("episode character ids must be unique")
        if len(character_ids) > 8:
            raise ValueError("an episode may include at most 8 characters")
        selected_ids = list(character_ids)

    selected_set = set(selected_ids)
    known_ids = {str(row["id"]) for row in rows}
    missing = selected_set - known_ids
    if missing:
        raise ValueError(
            "episode character ids not found: " + ", ".join(sorted(missing))
        )

    active: List[Dict[str, Any]] = []
    for raw in rows:
        if raw.get("id") not in selected_set:
            continue
        row = dict(raw)
        # Later appearance bookkeeping must not invalidate this episode.
        row["appearances"] = [number]
        # Review-only suggestions and lock state do not change rendered
        # character identity; future locked merges may update both.
        row.pop("agent_suggestions", None)
        row.pop("manual_override", None)
        contrast = row.get("visual_contrast_with")
        if (
            isinstance(contrast, dict)
            and contrast.get("target_id")
            and contrast.get("target_id") not in selected_set
        ):
            # A valid season-level contrast may point at a character that does
            # not participate in this episode.  Keeping that dangling id would
            # make the projected CharacterSheet invalid and leak another
            # episode's identity into review/export inputs.
            row["visual_contrast_with"] = {}
        active.append(row)
    if len(active) != len(selected_ids):
        raise ValueError("episode character projection is incomplete")
    return {
        "schema_version": sheet.get("schema_version", 1),
        "season_no": sheet.get("season_no", 1),
        "track": sheet.get("track", ""),
        "characters": active,
    }


def episode_character_fingerprint_ids(
    characters: Dict[str, Any], *, episode_no: int
) -> List[str]:
    """Freeze the cast that participates in one episode fingerprint."""

    episode_no = normalize_episode_no(episode_no)
    rows = characters.get("characters")
    if not isinstance(rows, list):
        return []
    valid_rows = [
        row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    ]
    active = [
        str(row["id"])
        for row in valid_rows
        if isinstance(row.get("appearances"), list)
        and episode_no in row.get("appearances", [])
    ]
    # Older or manually edited episode-1 sheets may use [] for the default
    # cast.  Only those unassigned rows are a safe legacy fallback; rows marked
    # exclusively for future episodes must never enter episode 1.
    if active:
        selected = sorted(set(active))
    elif episode_no == 1:
        selected = sorted({
            str(row["id"])
            for row in valid_rows
            if not row.get("appearances")
        })
        if not selected:
            raise ValueError(
                "episode character cast is ambiguous; rerun station 4 before review"
            )
    else:
        raise ValueError(
            "episode character cast is ambiguous; rerun station 4 before review"
        )
    if len(selected) > 8:
        raise ValueError("an episode may include at most 8 characters")
    return selected


def migrate_fresh_episode_fingerprints_v2(workspace: str) -> List[int]:
    """Migrate fresh legacy episode meta before the season sheet is changed.

    Callers must invoke this while holding the workspace write lock and before
    persisting character-table edits. Stale or malformed legacy episodes are
    deliberately left on v1 so migration cannot bless already-diverged data.
    """

    try:
        characters = _load_characters(workspace)
    except (FileNotFoundError, ValueError):
        # A manual save may be repairing an invalid or missing legacy sheet.
        # In that case no legacy meta can be proven fresh, so migrate none and
        # let the subsequent validated write make existing episodes stale.
        return []
    migrated: List[int] = []
    for item in list_episodes(workspace):
        episode_no = item["episode_no"]
        paths = episode_paths(workspace, episode_no=episode_no)
        meta = read_json_optional(paths.meta_path, None)
        if not isinstance(meta, dict):
            continue
        raw_version = meta.get("input_fingerprint_version", 1)
        if (
            not isinstance(raw_version, int)
            or isinstance(raw_version, bool)
            or raw_version != 1
            or is_episode_stale(workspace, episode_no=episode_no)
        ):
            continue
        try:
            fingerprint_ids = episode_character_fingerprint_ids(
                characters, episode_no=episode_no
            )
            fingerprint = input_fingerprint(
                setup=_load_setup(workspace, episode_no=episode_no),
                storyboard=_load_storyboard(workspace, episode_no=episode_no),
                characters=characters,
                review=_load_review(workspace, episode_no=episode_no),
                episode_no=episode_no,
                version=INPUT_FINGERPRINT_VERSION,
                character_ids=fingerprint_ids,
            )
            updated = model_to_dict(
                DramaEpisodeMeta(
                    **{
                        **meta,
                        "input_fingerprint": fingerprint,
                        "input_fingerprint_version": INPUT_FINGERPRINT_VERSION,
                        "character_fingerprint_ids": fingerprint_ids,
                    }
                )
            )
        except (FileNotFoundError, ValueError):
            continue
        write_json(paths.meta_path, updated)
        migrated.append(episode_no)
    return migrated


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
    character_fingerprint_ids: List[str],
    episode_sha256: str,
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
        input_fingerprint_version=INPUT_FINGERPRINT_VERSION,
        character_fingerprint_ids=character_fingerprint_ids,
        episode_sha256=episode_sha256,
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
