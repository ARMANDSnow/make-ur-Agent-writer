"""Strict local persistence for C2 shot-image candidates and frame bindings."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping

from . import paths
from .drama_schemas import (
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    FirstShotImageBinding,
    ShotImageCandidate,
    ShotImageCoverageReport,
    TailShotImageBinding,
    episode_paths,
    normalize_episode_no,
)
from .drama_shot_image_candidates import (
    DramaShotImageCandidateError,
    append_shot_image_candidate,
    build_episode_shot_image_candidate_manifest,
    build_shot_image_candidate,
    reconcile_shot_image_candidate_manifest,
    select_shot_image_frame,
    shot_image_candidate_affected_ids,
    shot_image_coverage,
)
from .drama_shot_image_store import load_fresh_episode_shot_image_plan
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES = 6_000_000
MAX_SHOT_IMAGE_CANDIDATE_BYTES = 5 * 1024 * 1024
MAX_SHOT_IMAGE_DECODED_BYTES = 64 * 1024 * 1024
MAX_SHOT_IMAGE_PIXELS = 40_000_000

ShotImageCandidateState = Literal[
    "needs_shot_image_assets",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaShotImageCandidateStoreError(ValueError):
    pass


class _ManifestReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShotImageCandidateInspection:
    state: ShotImageCandidateState
    reasons: tuple[str, ...]
    manifest: EpisodeShotImageCandidateManifest | None = None
    affected_shot_ids: tuple[str, ...] = ()
    coverage: ShotImageCoverageReport | None = None


def shot_image_candidate_manifest_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("shot image candidate path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.shot_image_assets.json"


def _read_manifest(
    workspace: str,
    *,
    episode_no: int,
) -> EpisodeShotImageCandidateManifest:
    root = paths.workspace_root(workspace)
    path = shot_image_candidate_manifest_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, ValueError) as exc:
        raise _ManifestReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "manifest_fingerprint",
        "manifest",
    }:
        raise _ManifestReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ManifestReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_shot_image_assets":
        raise _ManifestReadError("schema_invalid")
    if not isinstance(raw["manifest"], dict):
        raise _ManifestReadError("schema_invalid")
    try:
        manifest = EpisodeShotImageCandidateManifest(**raw["manifest"])
    except (TypeError, ValueError) as exc:
        raise _ManifestReadError("schema_invalid") from exc
    if raw["manifest_fingerprint"] != manifest.manifest_fingerprint:
        raise _ManifestReadError("manifest_hash_mismatch")
    if manifest.episode_no != episode_no:
        raise _ManifestReadError("schema_invalid")
    return manifest


def _validate_png(data: bytes) -> tuple[int, int]:
    if (
        type(data) is not bytes
        or not data
        or len(data) > MAX_SHOT_IMAGE_CANDIDATE_BYTES
        or not data.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise DramaShotImageCandidateStoreError("candidate artifact is not a bounded PNG")
    offset = 8
    saw_ihdr = saw_plte = saw_idat = saw_iend = False
    left_idat_sequence = False
    dimensions: tuple[int, int] | None = None
    bits_per_pixel = 0
    bit_depth = 0
    color_type = -1
    interlace = 0
    idat_chunks: list[bytes] = []
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > MAX_SHOT_IMAGE_CANDIDATE_BYTES or end > len(data):
            raise DramaShotImageCandidateStoreError("candidate PNG chunk is invalid")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(data[offset + 8 + length : end], "big")
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
            raise DramaShotImageCandidateStoreError("candidate PNG checksum is invalid")
        if not saw_ihdr:
            if kind != b"IHDR" or length != 13:
                raise DramaShotImageCandidateStoreError("candidate PNG IHDR is invalid")
            width = int.from_bytes(payload[:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            if (
                width <= 0
                or height <= 0
                or width > 100_000
                or height > 100_000
                or width * height > MAX_SHOT_IMAGE_PIXELS
            ):
                raise DramaShotImageCandidateStoreError("candidate PNG dimensions are invalid")
            dimensions = (width, height)
            bit_depth = payload[8]
            color_type = payload[9]
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
            if (
                color_type not in valid_depths
                or bit_depth not in valid_depths[color_type]
                or payload[10] != 0
                or payload[11] != 0
                or payload[12] not in {0, 1}
            ):
                raise DramaShotImageCandidateStoreError("candidate PNG encoding is unsupported")
            bits_per_pixel = bit_depth * channels[color_type]
            interlace = payload[12]
            saw_ihdr = True
        elif kind == b"IHDR":
            raise DramaShotImageCandidateStoreError("candidate PNG has duplicate IHDR")
        elif kind not in {b"PLTE", b"IDAT", b"IEND"} and 65 <= kind[0] <= 90:
            raise DramaShotImageCandidateStoreError("candidate PNG critical chunk is unsupported")
        if kind == b"PLTE":
            if saw_plte or saw_idat or color_type in {0, 4}:
                raise DramaShotImageCandidateStoreError("candidate PNG palette is invalid")
            if length == 0 or length > 768 or length % 3 != 0:
                raise DramaShotImageCandidateStoreError("candidate PNG palette is invalid")
            if color_type == 3 and length // 3 > 2**bit_depth:
                raise DramaShotImageCandidateStoreError("candidate PNG palette is invalid")
            saw_plte = True
        if kind == b"IDAT":
            if left_idat_sequence or (color_type == 3 and not saw_plte):
                raise DramaShotImageCandidateStoreError("candidate PNG IDAT sequence is invalid")
            saw_idat = True
            idat_chunks.append(payload)
        elif saw_idat and kind != b"IEND":
            left_idat_sequence = True
        if kind == b"IEND":
            if length != 0 or end != len(data):
                raise DramaShotImageCandidateStoreError("candidate PNG IEND is invalid")
            saw_iend = True
            break
        offset = end
    if not saw_ihdr or not saw_idat or not saw_iend or dimensions is None:
        raise DramaShotImageCandidateStoreError("candidate PNG is structurally incomplete")
    width, height = dimensions
    passes = (
        ((0, 0, 1, 1),)
        if interlace == 0
        else (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        )
    )
    row_layout: list[tuple[int, int]] = []
    expected_decoded = 0
    for start_x, start_y, step_x, step_y in passes:
        pass_width = 0 if width <= start_x else (width - start_x + step_x - 1) // step_x
        pass_height = 0 if height <= start_y else (height - start_y + step_y - 1) // step_y
        if pass_width == 0 or pass_height == 0:
            continue
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        row_layout.append((pass_height, row_bytes))
        expected_decoded += pass_height * (row_bytes + 1)
    if expected_decoded <= 0 or expected_decoded > MAX_SHOT_IMAGE_DECODED_BYTES:
        raise DramaShotImageCandidateStoreError("candidate PNG decoded size is invalid")
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(b"".join(idat_chunks), expected_decoded + 1)
    except zlib.error as exc:
        raise DramaShotImageCandidateStoreError("candidate PNG pixels are invalid") from exc
    if (
        len(decoded) != expected_decoded
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        raise DramaShotImageCandidateStoreError("candidate PNG pixels are incomplete")
    row_offset = 0
    for pass_height, row_bytes in row_layout:
        for _ in range(pass_height):
            if decoded[row_offset] > 4:
                raise DramaShotImageCandidateStoreError("candidate PNG filter is invalid")
            row_offset += row_bytes + 1
    return dimensions


def _candidate_payload_identity(data: bytes) -> tuple[str, int, int, int]:
    width, height = _validate_png(data)
    return hashlib.sha256(data).hexdigest(), len(data), width, height


def _validate_manifest_artifacts(
    workspace: str,
    manifest: EpisodeShotImageCandidateManifest,
    *,
    skip_artifact_path: str | None = None,
) -> None:
    root = paths.workspace_root(workspace)
    by_path: Dict[str, tuple[str, int, int, int]] = {}
    for pool in manifest.shots:
        for candidate in pool.candidates:
            artifact = candidate.artifact
            if artifact.path == skip_artifact_path:
                continue
            identity = (
                artifact.sha256,
                artifact.size_bytes,
                artifact.width,
                artifact.height,
            )
            previous = by_path.get(artifact.path)
            if previous is not None:
                if previous != identity:
                    raise DramaShotImageCandidateStoreError(
                        "candidate artifact path identifies inconsistent bytes"
                    )
                continue
            payload = _read_strict_workspace_bytes(
                root,
                root / artifact.path,
                maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
            )
            if _candidate_payload_identity(payload) != identity:
                raise DramaShotImageCandidateStoreError("candidate artifact bytes changed")
            by_path[artifact.path] = identity


def inspect_episode_shot_image_candidates(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotImageCandidateInspection:
    try:
        number = normalize_episode_no(episode_no)
        stored = _read_manifest(workspace, episode_no=number)
    except FileNotFoundError:
        stored = None
    except _ManifestReadError as exc:
        return ShotImageCandidateInspection("invalid", (exc.reason,))
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImageCandidateInspection("invalid", ("request_invalid",))
    try:
        plan = load_fresh_episode_shot_image_plan(workspace, episode_no=number)
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImageCandidateInspection(
            "blocked_source",
            ("source_not_fresh",),
            stored,
        )
    if stored is None:
        return ShotImageCandidateInspection("needs_shot_image_assets", ("missing",))
    try:
        _validate_manifest_artifacts(workspace, stored)
        affected = shot_image_candidate_affected_ids(stored, plan)
        coverage = shot_image_coverage(stored, plan)
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImageCandidateInspection("invalid", ("artifact_or_manifest_invalid",), stored)
    if stored.source_plan_fingerprint != plan.plan_fingerprint or affected:
        return ShotImageCandidateInspection(
            "stale",
            ("source_plan_mismatch",),
            stored,
            tuple(affected),
            coverage,
        )
    if coverage.status == "blocked_source":
        return ShotImageCandidateInspection(
            "blocked_source",
            ("shot_source_blocked",),
            stored,
            tuple(coverage.blocked_source_shot_ids),
            coverage,
        )
    if coverage.status == "stale":
        affected_coverage = sorted(
            set(coverage.stale_candidate_shot_ids)
            | set(coverage.broken_lineage_shot_ids)
        )
        return ShotImageCandidateInspection(
            "stale",
            ("selection_or_lineage_stale",),
            stored,
            tuple(affected_coverage),
            coverage,
        )
    return ShotImageCandidateInspection("fresh", (), stored, (), coverage)


def load_fresh_episode_shot_image_candidates(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotImageCandidateManifest:
    inspection = inspect_episode_shot_image_candidates(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.manifest is None:
        raise DramaShotImageCandidateStoreError(
            f"shot image candidates are not fresh: {inspection.state}"
        )
    return inspection.manifest


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _target_token_at(directory_fd: int, name: str) -> tuple[Any, ...]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    file_fd: int | None = None
    try:
        file_fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=directory_fd)
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES:
            return ("invalid",)
        return ("file", len(payload), hashlib.sha256(payload).hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _open_parent_dir(root: Path, relative: Path, *, create: bool) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaShotImageCandidateStoreError("strict no-follow writes are unavailable")
    directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except BaseException:
        try:
            os.close(directory_fd)
        except OSError:
            pass
        raise


def _write_manifest(
    workspace: str,
    manifest: EpisodeShotImageCandidateManifest,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_image_assets",
        "manifest_fingerprint": manifest.manifest_fingerprint,
        "manifest": model_to_dict(manifest),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_IMAGE_CANDIDATE_MANIFEST_BYTES:
        raise DramaShotImageCandidateStoreError("candidate manifest exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = shot_image_candidate_manifest_path(workspace, episode_no=manifest.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotImageCandidateStoreError("candidate manifest path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaShotImageCandidateStoreError("candidate manifest path is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DramaShotImageCandidateStoreError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_created = False
    temp_identity: tuple[int, int] | None = None
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotImageCandidateStoreError(
                "candidate manifest changed concurrently; retry from inspection"
            )
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        temp_created = True
        initial = os.fstat(temp_fd)
        temp_identity = (initial.st_dev, initial.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short candidate manifest write")
            view = view[written:]
        os.fsync(temp_fd)
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotImageCandidateStoreError(
                "candidate manifest changed concurrently; retry from inspection"
            )
        opened = os.fstat(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise DramaShotImageCandidateStoreError("candidate temporary file changed concurrently")
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except DramaShotImageCandidateStoreError:
        raise
    except OSError as exc:
        raise DramaShotImageCandidateStoreError("candidate manifest could not be written safely") from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_created and temp_identity is not None:
            try:
                cleanup = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISREG(cleanup.st_mode)
                    and (cleanup.st_dev, cleanup.st_ino) == temp_identity
                ):
                    try:
                        os.unlink(temp_name, dir_fd=directory_fd)
                    except OSError:
                        pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _write_artifact_create_only(
    workspace: str,
    candidate: ShotImageCandidate,
    data: bytes,
) -> tuple[int, int] | None:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    path = root / candidate.artifact.path
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotImageCandidateStoreError("candidate artifact path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaShotImageCandidateStoreError("candidate artifact path is invalid")
    try:
        existing = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
        )
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing != data or _candidate_payload_identity(existing) != (
            candidate.artifact.sha256,
            candidate.artifact.size_bytes,
            candidate.artifact.width,
            candidate.artifact.height,
        ):
            raise DramaShotImageCandidateStoreError("candidate artifact path is occupied")
        return None
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DramaShotImageCandidateStoreError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_identity: tuple[int, int] | None = None
    artifact_linked = False
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _target_token_at(directory_fd, relative.name) != ("missing",):
            raise DramaShotImageCandidateStoreError("candidate artifact path changed concurrently")
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        info = os.fstat(temp_fd)
        temp_identity = (info.st_dev, info.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short candidate artifact write")
            view = view[written:]
        os.fsync(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != temp_identity:
            raise DramaShotImageCandidateStoreError("candidate artifact temporary file changed")
        try:
            os.link(
                temp_name,
                relative.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise DramaShotImageCandidateStoreError("candidate artifact path changed concurrently") from exc
        linked = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(linked.st_mode)
            or (linked.st_dev, linked.st_ino) != temp_identity
        ):
            raise DramaShotImageCandidateStoreError("candidate artifact link changed concurrently")
        artifact_linked = True
        os.unlink(temp_name, dir_fd=directory_fd)
    except DramaShotImageCandidateStoreError:
        if directory_fd is not None and artifact_linked and temp_identity is not None:
            try:
                linked = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    stat.S_ISREG(linked.st_mode)
                    and (linked.st_dev, linked.st_ino) == temp_identity
                ):
                    os.unlink(relative.name, dir_fd=directory_fd)
            except OSError:
                pass
        raise
    except OSError as exc:
        if directory_fd is not None and artifact_linked and temp_identity is not None:
            try:
                linked = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
                if (
                    stat.S_ISREG(linked.st_mode)
                    and (linked.st_dev, linked.st_ino) == temp_identity
                ):
                    os.unlink(relative.name, dir_fd=directory_fd)
            except OSError:
                pass
        raise DramaShotImageCandidateStoreError("candidate artifact could not be written safely") from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_identity is not None:
            try:
                cleanup = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISREG(cleanup.st_mode)
                    and (cleanup.st_dev, cleanup.st_ino) == temp_identity
                ):
                    try:
                        os.unlink(temp_name, dir_fd=directory_fd)
                    except OSError:
                        pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass
    persisted = _read_strict_workspace_bytes(
        root,
        path,
        maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
    )
    if persisted != data or _candidate_payload_identity(persisted) != (
        candidate.artifact.sha256,
        candidate.artifact.size_bytes,
        candidate.artifact.width,
        candidate.artifact.height,
    ):
        raise DramaShotImageCandidateStoreError("candidate artifact persistence check failed")
    return temp_identity


def _cleanup_unreferenced_artifact(
    workspace: str,
    candidate: ShotImageCandidate,
    expected_identity: tuple[int, int],
) -> None:
    """Best-effort cleanup for a normal failed append, never a crash orphan."""

    try:
        current = _read_manifest(workspace, episode_no=candidate.episode_no)
        if any(
            item.artifact.path == candidate.artifact.path
            for pool in current.shots
            for item in pool.candidates
        ):
            return
        root = paths.workspace_root(workspace)
        relative = (root / candidate.artifact.path).relative_to(root)
        directory_fd = _open_parent_dir(root, relative, create=False)
    except (OSError, RecursionError, TypeError, ValueError):
        return
    try:
        info = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            stat.S_ISREG(info.st_mode)
            and (info.st_dev, info.st_ino) == expected_identity
        ):
            os.unlink(relative.name, dir_fd=directory_fd)
    except OSError:
        pass
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _precommit_check(
    workspace: str,
    *,
    episode_no: int,
    source_plan_fingerprint: str,
    manifest: EpisodeShotImageCandidateManifest,
) -> None:
    latest = load_fresh_episode_shot_image_plan(workspace, episode_no=episode_no)
    if latest.plan_fingerprint != source_plan_fingerprint:
        raise DramaShotImageCandidateStoreError("shot image plan changed during candidate operation")
    _validate_manifest_artifacts(workspace, manifest)


def _persist_manifest(
    workspace: str,
    manifest: EpisodeShotImageCandidateManifest,
    *,
    target_token: tuple[Any, ...],
    source_plan_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    _write_manifest(
        workspace,
        manifest,
        expected_target_token=target_token,
        precommit_check=lambda: _precommit_check(
            workspace,
            episode_no=manifest.episode_no,
            source_plan_fingerprint=source_plan_fingerprint,
            manifest=manifest,
        ),
    )
    persisted = _read_manifest(workspace, episode_no=manifest.episode_no)
    if persisted.manifest_fingerprint != manifest.manifest_fingerprint:
        raise DramaShotImageCandidateStoreError("candidate manifest persistence check failed")
    return persisted


def _create_manifest_impl(
    workspace: str,
    *,
    episode_no: int,
    replace_stale: bool,
    expected_manifest_fingerprint: str | None,
) -> EpisodeShotImageCandidateManifest:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-assets"):
        path = shot_image_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError:
            current = None
        except _ManifestReadError as exc:
            raise DramaShotImageCandidateStoreError(
                "invalid candidate manifest must be repaired explicitly"
            ) from exc
        plan = load_fresh_episode_shot_image_plan(workspace, episode_no=number)
        if current is None:
            desired = build_episode_shot_image_candidate_manifest(plan)
        else:
            _validate_manifest_artifacts(workspace, current)
            affected = shot_image_candidate_affected_ids(current, plan)
            source_matches = current.source_plan_fingerprint == plan.plan_fingerprint
            if source_matches and not affected:
                return current
            if not replace_stale:
                raise DramaShotImageCandidateStoreError(
                    "stale candidate manifest requires explicit confirmation"
                )
            if expected_manifest_fingerprint != current.manifest_fingerprint:
                raise DramaShotImageCandidateStoreError(
                    "candidate manifest changed; refresh before replacement"
                )
            desired = reconcile_shot_image_candidate_manifest(
                current,
                plan,
                expected_manifest_fingerprint=current.manifest_fingerprint,
            )
        return _persist_manifest(
            workspace,
            desired,
            target_token=token,
            source_plan_fingerprint=plan.plan_fingerprint,
        )


def create_episode_shot_image_candidate_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_manifest_fingerprint: str | None = None,
) -> EpisodeShotImageCandidateManifest:
    try:
        return _create_manifest_impl(
            workspace,
            episode_no=episode_no,
            replace_stale=replace_stale,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotImageCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked) as exc:
        raise DramaShotImageCandidateStoreError("candidate manifest operation was rejected") from None


def _append_candidate_impl(
    workspace: str,
    *,
    shot_id: str,
    png_bytes: bytes,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> tuple[EpisodeShotImageCandidateManifest, ShotImageCandidate]:
    identity = _candidate_payload_identity(png_bytes)
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-assets"):
        path = shot_image_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError as exc:
            raise DramaShotImageCandidateStoreError("candidate manifest must be created first") from exc
        except _ManifestReadError as exc:
            raise DramaShotImageCandidateStoreError("candidate manifest is invalid") from exc
        plan = load_fresh_episode_shot_image_plan(workspace, episode_no=number)
        if current.source_plan_fingerprint != plan.plan_fingerprint or shot_image_candidate_affected_ids(
            current, plan
        ):
            raise DramaShotImageCandidateStoreError("candidate manifest must be reconciled first")
        candidate = build_shot_image_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        existing = next(
            (
                item
                for pool in current.shots
                for item in pool.candidates
                if item.candidate_id == candidate.candidate_id
            ),
            None,
        )
        _validate_manifest_artifacts(
            workspace,
            current,
            skip_artifact_path=(
                candidate.artifact.path if existing == candidate else None
            ),
        )
        desired = append_shot_image_candidate(
            current,
            plan,
            candidate,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
        created_identity = _write_artifact_create_only(workspace, candidate, png_bytes)
        if desired.manifest_fingerprint == current.manifest_fingerprint:
            _validate_manifest_artifacts(workspace, current)
            return current, candidate
        try:
            persisted = _persist_manifest(
                workspace,
                desired,
                target_token=token,
                source_plan_fingerprint=plan.plan_fingerprint,
            )
        except BaseException:
            if created_identity is not None:
                _cleanup_unreferenced_artifact(
                    workspace,
                    candidate,
                    created_identity,
                )
            raise
        return persisted, candidate


def append_local_shot_image_candidate(
    workspace: str,
    *,
    shot_id: str,
    png_bytes: bytes,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> tuple[EpisodeShotImageCandidateManifest, ShotImageCandidate]:
    try:
        if type(png_bytes) is not bytes:
            raise ValueError("png_bytes must be bytes")
        return _append_candidate_impl(
            workspace,
            shot_id=shot_id,
            png_bytes=png_bytes,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotImageCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotImageCandidateStoreError("candidate append was rejected") from None


def _repair_candidate_artifact_impl(
    workspace: str,
    *,
    candidate_id: str,
    png_bytes: bytes,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> ShotImageCandidate:
    identity = _candidate_payload_identity(png_bytes)
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-assets"):
        path = shot_image_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError as exc:
            raise DramaShotImageCandidateStoreError(
                "candidate manifest must be created first"
            ) from exc
        except _ManifestReadError as exc:
            raise DramaShotImageCandidateStoreError(
                "candidate manifest is invalid"
            ) from exc
        if expected_manifest_fingerprint != current.manifest_fingerprint:
            raise DramaShotImageCandidateStoreError(
                "candidate manifest changed; refresh before artifact repair"
            )
        matches = [
            candidate
            for pool in current.shots
            for candidate in pool.candidates
            if candidate.candidate_id == candidate_id
        ]
        if len(matches) != 1:
            raise DramaShotImageCandidateStoreError(
                "candidate artifact repair target is unknown"
            )
        candidate = matches[0]
        artifact = candidate.artifact
        if identity != (
            artifact.sha256,
            artifact.size_bytes,
            artifact.width,
            artifact.height,
        ):
            raise DramaShotImageCandidateStoreError(
                "candidate artifact repair bytes do not match the manifest"
            )
        created_identity = _write_artifact_create_only(workspace, candidate, png_bytes)
        try:
            if _target_token(root, path) != token:
                raise DramaShotImageCandidateStoreError(
                    "candidate manifest changed during artifact repair"
                )
            persisted = _read_manifest(workspace, episode_no=number)
            persisted_matches = [
                item
                for pool in persisted.shots
                for item in pool.candidates
                if item.candidate_id == candidate_id
            ]
            if (
                persisted.manifest_fingerprint != expected_manifest_fingerprint
                or persisted_matches != [candidate]
            ):
                raise DramaShotImageCandidateStoreError(
                    "candidate artifact repair target changed"
                )
            return candidate
        except BaseException:
            if created_identity is not None:
                _cleanup_unreferenced_artifact(
                    workspace,
                    candidate,
                    created_identity,
                )
            raise


def repair_referenced_shot_image_candidate_artifact(
    workspace: str,
    *,
    candidate_id: str,
    png_bytes: bytes,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> ShotImageCandidate:
    """Restore exact bytes for one manifest-referenced missing artifact."""

    try:
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError("candidate_id must be a non-empty string")
        if type(png_bytes) is not bytes:
            raise ValueError("png_bytes must be bytes")
        return _repair_candidate_artifact_impl(
            workspace,
            candidate_id=candidate_id,
            png_bytes=png_bytes,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotImageCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotImageCandidateStoreError(
            "candidate artifact repair was rejected"
        ) from None


def _select_frame_impl(
    workspace: str,
    *,
    shot_id: str,
    frame: Literal["first", "tail"],
    binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-assets"):
        path = shot_image_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError as exc:
            raise DramaShotImageCandidateStoreError("candidate manifest must be created first") from exc
        except _ManifestReadError as exc:
            raise DramaShotImageCandidateStoreError("candidate manifest is invalid") from exc
        _validate_manifest_artifacts(workspace, current)
        plan = load_fresh_episode_shot_image_plan(workspace, episode_no=number)
        desired = select_shot_image_frame(
            current,
            plan,
            shot_id=shot_id,
            frame=frame,
            binding=binding,
            expected_selection_revision=expected_selection_revision,
            expected_current_binding=expected_current_binding,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
        if desired.manifest_fingerprint == current.manifest_fingerprint:
            return current
        return _persist_manifest(
            workspace,
            desired,
            target_token=token,
            source_plan_fingerprint=plan.plan_fingerprint,
        )


def select_episode_shot_image_frame(
    workspace: str,
    *,
    shot_id: str,
    frame: Literal["first", "tail"],
    binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    try:
        return _select_frame_impl(
            workspace,
            shot_id=shot_id,
            frame=frame,
            binding=binding,
            expected_selection_revision=expected_selection_revision,
            expected_current_binding=expected_current_binding,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotImageCandidateStoreError:
        raise
    except (DramaShotImageCandidateError, OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotImageCandidateStoreError("candidate selection was rejected") from None
