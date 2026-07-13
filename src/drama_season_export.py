"""Deterministic, fail-closed season package exports for short drama workspaces."""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Literal, Tuple

from . import drama_store, paths
from .ai_draw_client import _detect_image_type
from .comfy_workflow_exporter import build_workflow
from .drama_schemas import (
    CharacterSheet,
    DramaEpisode,
    DramaEpisodeMeta,
    character_paths,
    episode_paths,
    normalize_episode_no,
)
from .schemas import model_to_dict
from .utils import read_json_optional, sha256_data


SEASON_EXPORT_GENERATOR_VERSION = "drama-season-export-v1"
SEASON_EXPORT_MODES = frozenset({"master", "snapshot"})
MAX_REFERENCE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_EPISODE_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SEASON_PACKAGE_BYTES = 64 * 1024 * 1024
_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
_EPISODE_FORMATS = ("json", "md", "csv", "comfy")


class SeasonExportConflict(ValueError):
    """The requested package is structurally valid but not ready yet."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SeasonExport:
    mode: Literal["master", "snapshot"]
    filename: str
    content_type: str
    path: Path
    body: bytes
    manifest: Dict[str, Any]


def season_export_readiness(workspace: str, *, season_no: int = 1) -> Dict[str, Any]:
    """Classify planned episodes and referenced character assets for season export."""

    _validate_season_no(season_no)
    planned = _planned_episode_count(workspace)
    eligible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for episode_no in range(1, planned + 1):
        item, reason = _classify_episode(workspace, episode_no=episode_no, season_no=season_no)
        if item is None:
            excluded.append({"episode_no": episode_no, "reason": reason})
        else:
            eligible.append(item)

    sheet, references, missing_references, asset_errors = _character_assets(workspace)
    blockers: List[str] = []
    if any(item["reason"] == "incomplete" for item in excluded):
        blockers.append("incomplete_episode")
    if any(item["reason"] == "stale" for item in excluded):
        blockers.append("stale_episode")
    if missing_references:
        blockers.append("missing_reference_image")
    if asset_errors:
        blockers.append("invalid_reference_asset")

    return {
        "season_no": season_no,
        "planned_episode_count": planned,
        "eligible_episode_nos": [item["episode_no"] for item in eligible],
        "excluded": excluded,
        "missing_reference_images": missing_references,
        "asset_errors": asset_errors,
        "master_blockers": blockers,
        "master_ready": not excluded and not missing_references and not asset_errors,
        "snapshot_ready": bool(eligible) and not asset_errors,
        "_eligible": eligible,
        "_character_sheet": sheet,
        "_references": references,
    }


def public_season_export_readiness(workspace: str, *, season_no: int = 1) -> Dict[str, Any]:
    """Return the bounded, JSON-safe readiness projection exposed by the Web API."""

    state = season_export_readiness(workspace, season_no=season_no)
    return {key: value for key, value in state.items() if not key.startswith("_")}


def export_season(
    workspace: str,
    *,
    season_no: int = 1,
    mode: Literal["master", "snapshot"],
) -> SeasonExport:
    """Build and atomically persist a deterministic master or snapshot ZIP."""

    if not isinstance(mode, str) or mode not in SEASON_EXPORT_MODES:
        raise ValueError("mode must be one of: master, snapshot")
    state = season_export_readiness(workspace, season_no=season_no)
    if state["asset_errors"]:
        raise SeasonExportConflict("invalid_reference_asset", "referenced character assets are invalid")
    if mode == "master" and not state["master_ready"]:
        raise SeasonExportConflict("master_not_ready", "all planned episodes and references must be fresh and complete")
    if mode == "snapshot" and not state["snapshot_ready"]:
        raise SeasonExportConflict("snapshot_not_ready", "at least one fresh complete episode is required")

    sheet = state["_character_sheet"]
    if not isinstance(sheet, dict):
        raise SeasonExportConflict("character_sheet_missing", "season character sheet is required")

    members: Dict[str, bytes] = {}
    member_bytes = 0
    episode_summaries: List[Dict[str, Any]] = []
    for item in state["_eligible"]:
        episode_no = int(item["episode_no"])
        file_rows: List[Dict[str, Any]] = []
        for export_format in _EPISODE_FORMATS:
            filename, payload = _render_episode_member(
                episode_no=episode_no,
                export_format=export_format,
                episode=item["_episode"],
                characters=sheet,
            )
            member = f"episodes/{filename}"
            _validate_member_name(member)
            member_bytes = _add_member(
                members, member, payload, current_size=member_bytes
            )
            file_rows.append(_member_record(member, payload))
        episode_summaries.append(
            {
                "episode_no": episode_no,
                "title": item["title"],
                "verdict": item["verdict"],
                "needs_human_review": item["needs_human_review"],
                "episode_sha256": item["episode_sha256"],
                "files": sorted(file_rows, key=lambda row: row["path"]),
            }
        )

    packaged_reference_members = {member for member, _payload in state["_references"]}
    character_payload = _json_bytes(
        _season_character_projection(
            sheet, packaged_reference_members=packaged_reference_members
        )
    )
    member_bytes = _add_member(
        members,
        "characters/season_01.json",
        character_payload,
        current_size=member_bytes,
    )
    for member, payload in state["_references"]:
        member_bytes = _add_member(
            members, member, payload, current_size=member_bytes
        )

    file_manifest = [_member_record(name, payload) for name, payload in sorted(members.items())]
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": SEASON_EXPORT_GENERATOR_VERSION,
        "mode": mode,
        "season_no": season_no,
        "planned_episode_count": state["planned_episode_count"],
        "included_episode_nos": list(state["eligible_episode_nos"]),
        "excluded": list(state["excluded"]),
        "episodes": episode_summaries,
        "missing_reference_images": list(state["missing_reference_images"]),
        "files": file_manifest,
    }
    member_bytes = _add_member(
        members,
        "manifest.json",
        _json_bytes(manifest),
        current_size=member_bytes,
    )
    body = _build_zip(members)
    if len(body) > MAX_SEASON_PACKAGE_BYTES:
        raise SeasonExportConflict("package_too_large", "season package exceeds the size limit")

    filename = f"season_{season_no:02d}_{'master' if mode == 'master' else 'snapshot'}.zip"
    target = episode_paths(workspace).outputs_dir / "exports" / filename
    _write_bytes_atomic(
        target,
        body,
        workspace_root=paths.WORKSPACE_DIR / workspace,
    )
    return SeasonExport(
        mode=mode,
        filename=filename,
        content_type="application/zip",
        path=target,
        body=body,
        manifest=manifest,
    )


def _validate_season_no(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value != 1:
        raise ValueError("season_no must be 1")
    return value


def _planned_episode_count(workspace: str) -> int:
    wizard = read_json_optional(paths.WORKSPACE_DIR / workspace / "data" / "wizard_input.json", None)
    if not isinstance(wizard, dict):
        raise ValueError("wizard episode_count is invalid")
    raw = wizard.get("episode_count")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("wizard episode_count is invalid")
    try:
        return normalize_episode_no(raw)
    except ValueError as exc:
        raise ValueError("wizard episode_count is invalid") from exc


def _classify_episode(
    workspace: str,
    *,
    episode_no: int,
    season_no: int,
) -> Tuple[Dict[str, Any] | None, str]:
    ep = episode_paths(workspace, episode_no=episode_no)
    root = paths.WORKSPACE_DIR / workspace
    try:
        raw_episode = _read_json_safely(
            root,
            PurePosixPath(*ep.episode_path.relative_to(root).parts),
            max_bytes=MAX_EPISODE_SOURCE_BYTES,
        )
        raw_meta = _read_json_safely(
            root,
            PurePosixPath(*ep.meta_path.relative_to(root).parts),
            max_bytes=MAX_EPISODE_SOURCE_BYTES,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "incomplete"
    if not isinstance(raw_episode, dict) or not isinstance(raw_meta, dict):
        return None, "incomplete"
    try:
        episode = DramaEpisode(**raw_episode)
        meta = DramaEpisodeMeta(**raw_meta)
    except Exception:
        return None, "incomplete"
    if (
        episode.episode_no != episode_no
        or meta.episode_no != episode_no
        or episode.season_no != season_no
        or meta.season_no != season_no
        or not meta.input_fingerprint
    ):
        return None, "incomplete"
    episode_data = model_to_dict(episode)
    if meta.episode_sha256 != sha256_data(episode_data):
        return None, "stale"
    if drama_store.is_episode_stale(workspace, episode_no=episode_no):
        return None, "stale"
    return (
        {
            "episode_no": episode_no,
            "title": episode.title,
            "verdict": meta.verdict,
            "needs_human_review": meta.needs_human_review,
            "episode_sha256": meta.episode_sha256,
            "_episode": episode_data,
        },
        "",
    )


def _character_assets(
    workspace: str,
) -> Tuple[Dict[str, Any] | None, List[Tuple[str, bytes]], List[str], List[str]]:
    root = paths.WORKSPACE_DIR / workspace
    sheet_path = character_paths(workspace).sheet_path
    try:
        raw = _read_json_safely(
            root,
            PurePosixPath(*sheet_path.relative_to(root).parts),
            max_bytes=MAX_EPISODE_SOURCE_BYTES,
        )
    except FileNotFoundError:
        return None, [], [], []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, [], [], ["invalid_character_sheet"]
    if not isinstance(raw, dict):
        return None, [], [], []
    try:
        sheet_model = CharacterSheet(**raw)
        if sheet_model.season_no != 1:
            return None, [], [], ["character_sheet_season_mismatch"]
        sheet = model_to_dict(sheet_model)
    except Exception:
        return None, [], [], ["invalid_character_sheet"]

    if root.is_symlink():
        return sheet, [], [], ["workspace_symlink"]
    references: List[Tuple[str, bytes]] = []
    missing: List[str] = []
    errors: List[str] = []
    seen_paths = set()
    seen_members = set()
    total_size = 0
    for character in sheet.get("characters", []):
        character_id = str(character.get("id") or "")
        for ref in character.get("reference_images", []):
            rel = str(ref.get("path") or "")
            if not rel or rel in seen_paths:
                continue
            seen_paths.add(rel)
            pure = PurePosixPath(rel)
            if (
                len(pure.parts) != 4
                or pure.parts[:3] != ("data", "character_refs", character_id)
                or pure.suffix.lower() != ".png"
            ):
                errors.append("reference_character_or_path_mismatch")
                continue
            try:
                payload = _read_reference_safely(root, pure)
            except FileNotFoundError:
                missing.append(rel)
                continue
            except ValueError as exc:
                errors.append(str(exc))
                continue
            except OSError:
                errors.append("reference_symlink_or_unreadable")
                continue
            try:
                _detect_image_type(payload)
            except ValueError:
                errors.append("invalid_reference_image")
                continue
            total_size += len(payload)
            if total_size > MAX_SEASON_PACKAGE_BYTES:
                errors.append("references_too_large")
                continue
            member = f"character_refs/{character_id}/{pure.name}"
            try:
                _validate_member_name(member)
            except ValueError:
                errors.append("unsafe_reference_member")
                continue
            if member in seen_members:
                errors.append("reference_member_collision")
                continue
            seen_members.add(member)
            references.append((member, payload))
    references.sort(key=lambda item: item[0])
    return sheet, references, sorted(missing), sorted(set(errors))


def _read_reference_safely(root: Path, relative: PurePosixPath) -> bytes:
    """Read one bounded regular file without following any symlink component."""

    try:
        return _read_workspace_file_safely(
            root, relative, max_bytes=MAX_REFERENCE_IMAGE_BYTES
        )
    except ValueError as exc:
        if str(exc) == "file_not_regular":
            raise ValueError("reference_not_regular_file") from exc
        if str(exc) == "file_too_large":
            raise ValueError("reference_too_large") from exc
        raise ValueError("reference_outside_workspace") from exc


def _read_json_safely(
    root: Path,
    relative: PurePosixPath,
    *,
    max_bytes: int,
) -> Any:
    payload = _read_workspace_file_safely(root, relative, max_bytes=max_bytes)
    return json.loads(payload.decode("utf-8"))


def _read_workspace_file_safely(
    root: Path,
    relative: PurePosixPath,
    *,
    max_bytes: int,
) -> bytes:
    """Open path components relative to stable dirfds and perform one bounded read."""

    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("file_outside_workspace")
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened: List[int] = []
    try:
        current = os.open(root, flags_dir)
        opened.append(current)
        for part in relative.parts[:-1]:
            current = os.open(part, flags_dir, dir_fd=current)
            opened.append(current)
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        opened.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("file_not_regular")
        if info.st_size > max_bytes:
            raise ValueError("file_too_large")
        chunks: List[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError("file_too_large")
        return payload
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass


def _season_character_projection(
    sheet: Dict[str, Any], *, packaged_reference_members: set[str] | None = None
) -> Dict[str, Any]:
    """Expose deliverable character data without prompts, provider state or review notes."""

    characters: List[Dict[str, Any]] = []
    for raw in sheet.get("characters", []):
        if not isinstance(raw, dict):
            continue
        row = {
            key: raw.get(key)
            for key in (
                "id",
                "name",
                "role",
                "age_range",
                "gender",
                "lora_token",
                "visual_features",
                "wardrobe_default",
                "expression_keywords",
                "visual_signature",
                "appearances",
                "visual_contrast_with",
            )
        }
        projected_references = [
            {
                **{
                    "path": f"character_refs/{raw.get('id', '')}/{PurePosixPath(str(ref.get('path') or '')).name}",
                },
                **{
                    key: ref.get(key)
                    for key in ("width", "height")
                    if ref.get(key) is not None
                },
            }
            for ref in raw.get("reference_images", [])
            if isinstance(ref, dict)
        ]
        if packaged_reference_members is not None:
            projected_references = [
                ref for ref in projected_references
                if ref["path"] in packaged_reference_members
            ]
        row["reference_images"] = projected_references
        characters.append(row)
    return {
        "schema_version": sheet.get("schema_version", 1),
        "season_no": sheet.get("season_no", 1),
        "track": sheet.get("track", ""),
        "characters": characters,
    }


def _render_episode_member(
    *,
    episode_no: int,
    export_format: str,
    episode: Dict[str, Any],
    characters: Dict[str, Any],
) -> Tuple[str, bytes]:
    stem = f"episode_{episode_no:02d}"
    if export_format == "json":
        return f"{stem}.json", _json_bytes(episode)
    if export_format == "md":
        return f"{stem}.storyboard.md", drama_store.to_markdown_table(episode).encode("utf-8")
    if export_format == "csv":
        return f"{stem}.storyboard.csv", drama_store.to_csv(episode)
    if export_format == "comfy":
        workflow = build_workflow(episode, characters)
        return f"{stem}.comfy.json", _json_bytes(workflow)
    raise ValueError("unsupported episode export format")


def _add_member(
    members: Dict[str, bytes],
    name: str,
    payload: bytes,
    *,
    current_size: int,
) -> int:
    _validate_member_name(name)
    if name in members:
        raise SeasonExportConflict("duplicate_member", "season package contains a duplicate member")
    new_size = current_size + len(payload)
    if new_size > MAX_SEASON_PACKAGE_BYTES:
        raise SeasonExportConflict("package_too_large", "season package exceeds the size limit")
    members[name] = payload
    return new_size


def _validate_member_name(name: str) -> None:
    pure = PurePosixPath(name)
    if not name or pure.is_absolute() or ".." in pure.parts or "\\" in name:
        raise ValueError("unsafe ZIP member name")
    if str(pure) != name:
        raise ValueError("unsafe ZIP member name")


def _member_record(name: str, payload: bytes) -> Dict[str, Any]:
    return {
        "path": name,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _build_zip(members: Dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(members.items()):
            _validate_member_name(name)
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATETIME)
            compression = (
                zipfile.ZIP_STORED
                if name.startswith("character_refs/")
                else zipfile.ZIP_DEFLATED
            )
            info.compress_type = compression
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(
                info,
                payload,
                compress_type=compression,
                compresslevel=9 if compression == zipfile.ZIP_DEFLATED else None,
            )
    return stream.getvalue()


def _write_bytes_atomic(path: Path, payload: bytes, *, workspace_root: Path) -> None:
    try:
        relative_parent = path.parent.relative_to(workspace_root)
    except ValueError as exc:
        raise SeasonExportConflict("unsafe_export_path", "workspace export path is unsafe") from exc
    if ".." in relative_parent.parts or "/" in path.name or "\\" in path.name:
        raise SeasonExportConflict("unsafe_export_path", "workspace export path is unsafe")

    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened_dirs: List[int] = []
    file_fd: int | None = None
    temp_name: str | None = None
    try:
        current_fd = os.open(workspace_root, flags_dir)
        opened_dirs.append(current_fd)
        for part in relative_parent.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags_dir, dir_fd=current_fd)
            opened_dirs.append(next_fd)
            current_fd = next_fd

        for _ in range(16):
            candidate = f".{path.name}.tmp.{secrets.token_hex(16)}"
            try:
                file_fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=current_fd,
                )
                temp_name = candidate
                break
            except FileExistsError:
                continue
        if file_fd is None or temp_name is None:
            raise SeasonExportConflict("export_temp_collision", "could not allocate export temp file")

        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = os.write(file_fd, view[offset:])
            if written <= 0:
                raise OSError("short write while creating season export")
            offset += written
        os.fchmod(file_fd, 0o644)
        os.fsync(file_fd)
        os.close(file_fd)
        file_fd = None
        os.replace(
            temp_name,
            path.name,
            src_dir_fd=current_fd,
            dst_dir_fd=current_fd,
        )
        temp_name = None
        os.fsync(current_fd)
    except SeasonExportConflict:
        raise
    except OSError as exc:
        raise SeasonExportConflict(
            "unsafe_export_path", "season export path is unsafe or unavailable"
        ) from exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if temp_name is not None and opened_dirs:
            try:
                os.unlink(temp_name, dir_fd=opened_dirs[-1])
            except OSError:
                pass
        for dir_fd in reversed(opened_dirs):
            try:
                os.close(dir_fd)
            except OSError:
                pass
