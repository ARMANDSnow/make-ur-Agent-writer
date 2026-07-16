"""Strict local persistence and freshness for stage-D1 shot-video plans."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_render_store import load_fresh_render_plan
from .drama_schemas import (
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    EpisodeShotVideoPlan,
    RenderPlan,
    episode_paths,
    normalize_episode_no,
)
from .drama_shot_image_candidate_store import (
    load_fresh_episode_shot_image_candidates,
)
from .drama_shot_image_store import load_fresh_episode_shot_image_plan
from .drama_shot_video import (
    build_episode_shot_video_plan,
    shot_video_plan_affected_ids,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_VIDEO_PLAN_BYTES = 4_000_000

ShotVideoPlanState = Literal[
    "needs_shot_video_plan",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaShotVideoStoreError(ValueError):
    pass


class _PlanReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShotVideoPlanInspection:
    state: ShotVideoPlanState
    reasons: tuple[str, ...]
    plan: EpisodeShotVideoPlan | None = None
    affected_shot_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ShotVideoSources:
    render_plan: RenderPlan
    shot_image_plan: EpisodeShotImagePlan
    candidate_manifest: EpisodeShotImageCandidateManifest


def shot_video_plan_path(workspace: str, *, episode_no: int = 1) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("shot video plan path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.shot_video_plan.json"


def _read_plan(workspace: str, *, episode_no: int) -> EpisodeShotVideoPlan:
    root = paths.workspace_root(workspace)
    path = shot_video_plan_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_PLAN_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, ValueError) as exc:
        raise _PlanReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "plan_fingerprint",
        "plan",
    }:
        raise _PlanReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _PlanReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_shot_video_plan":
        raise _PlanReadError("schema_invalid")
    if not isinstance(raw["plan"], dict):
        raise _PlanReadError("schema_invalid")
    try:
        plan = EpisodeShotVideoPlan(**raw["plan"])
    except (TypeError, ValueError) as exc:
        raise _PlanReadError("schema_invalid") from exc
    if raw["plan_fingerprint"] != plan.plan_fingerprint:
        raise _PlanReadError("plan_hash_mismatch")
    if plan.episode_no != episode_no:
        raise _PlanReadError("schema_invalid")
    return plan


def _load_sources(workspace: str, *, episode_no: int) -> _ShotVideoSources:
    render_plan = load_fresh_render_plan(workspace, episode_no=episode_no)
    shot_image_plan = load_fresh_episode_shot_image_plan(
        workspace,
        episode_no=episode_no,
    )
    candidate_manifest = load_fresh_episode_shot_image_candidates(
        workspace,
        episode_no=episode_no,
    )
    return _ShotVideoSources(
        render_plan=render_plan,
        shot_image_plan=shot_image_plan,
        candidate_manifest=candidate_manifest,
    )


def _build_from_sources(sources: _ShotVideoSources) -> EpisodeShotVideoPlan:
    return build_episode_shot_video_plan(
        sources.render_plan,
        sources.shot_image_plan,
        sources.candidate_manifest,
    )


def inspect_episode_shot_video_plan(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoPlanInspection:
    try:
        number = normalize_episode_no(episode_no)
        stored = _read_plan(workspace, episode_no=number)
    except FileNotFoundError:
        stored = None
    except _PlanReadError as exc:
        return ShotVideoPlanInspection("invalid", (exc.reason,))
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotVideoPlanInspection("invalid", ("request_invalid",))

    try:
        expected = _build_from_sources(_load_sources(workspace, episode_no=number))
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotVideoPlanInspection(
            "blocked_source",
            ("source_not_ready",),
            stored,
        )
    if stored is None:
        return ShotVideoPlanInspection("needs_shot_video_plan", ("missing",))
    if stored.plan_fingerprint != expected.plan_fingerprint:
        return ShotVideoPlanInspection(
            "stale",
            ("plan_source_mismatch",),
            stored,
            tuple(shot_video_plan_affected_ids(stored, expected)),
        )
    return ShotVideoPlanInspection("fresh", (), stored)


def load_fresh_episode_shot_video_plan(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotVideoPlan:
    inspection = inspect_episode_shot_video_plan(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.plan is None:
        raise DramaShotVideoStoreError(
            f"shot video plan is not fresh: {inspection.state}"
        )
    return inspection.plan


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_PLAN_BYTES,
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
        file_fd = os.open(
            name,
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_SHOT_VIDEO_PLAN_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_VIDEO_PLAN_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_VIDEO_PLAN_BYTES:
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


def _write_plan(
    workspace: str,
    plan: EpisodeShotVideoPlan,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_video_plan",
        "plan_fingerprint": plan.plan_fingerprint,
        "plan": model_to_dict(plan),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_VIDEO_PLAN_BYTES:
        raise DramaShotVideoStoreError("shot video plan exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = shot_video_plan_path(workspace, episode_no=plan.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotVideoStoreError("shot video plan path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaShotVideoStoreError("shot video plan path is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaShotVideoStoreError("strict no-follow shot video writes are unavailable")

    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_created = False
    temp_identity: tuple[int, int] | None = None
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoStoreError(
                "shot video plan changed concurrently; retry from inspection"
            )
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        temp_created = True
        initial_temp_info = os.fstat(temp_fd)
        temp_identity = (initial_temp_info.st_dev, initial_temp_info.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short shot video plan write")
            view = view[written:]
        os.fsync(temp_fd)
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoStoreError(
                "shot video plan changed concurrently; retry from inspection"
            )
        opened_info = os.fstat(temp_fd)
        named_info = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or not stat.S_ISREG(named_info.st_mode)
            or (opened_info.st_dev, opened_info.st_ino)
            != (named_info.st_dev, named_info.st_ino)
        ):
            raise DramaShotVideoStoreError(
                "shot video temporary file changed concurrently"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except DramaShotVideoStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoStoreError(
            "shot video plan could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_created and temp_identity is not None:
            try:
                cleanup_info = os.stat(
                    temp_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError:
                pass
            else:
                if (
                    stat.S_ISREG(cleanup_info.st_mode)
                    and (cleanup_info.st_dev, cleanup_info.st_ino) == temp_identity
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


def _create_episode_shot_video_plan_impl(
    workspace: str,
    *,
    episode_no: int,
    replace_stale: bool,
    expected_plan_fingerprint: str | None,
) -> EpisodeShotVideoPlan:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-plan"):
        path = shot_video_plan_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_plan(workspace, episode_no=number)
        except FileNotFoundError:
            current = None
        except _PlanReadError as exc:
            raise DramaShotVideoStoreError(
                "invalid shot video plan must be repaired explicitly"
            ) from exc

        desired = _build_from_sources(_load_sources(workspace, episode_no=number))
        if current is not None and current.plan_fingerprint == desired.plan_fingerprint:
            if _target_token(root, path) != token:
                raise DramaShotVideoStoreError(
                    "shot video plan changed concurrently; retry from inspection"
                )
            persisted = _read_plan(workspace, episode_no=number)
            if (
                persisted.plan_fingerprint != current.plan_fingerprint
                or _target_token(root, path) != token
            ):
                raise DramaShotVideoStoreError(
                    "shot video plan changed concurrently; retry from inspection"
                )
            return persisted
        if current is not None:
            if not replace_stale:
                raise DramaShotVideoStoreError(
                    "shot video plan replacement requires explicit confirmation"
                )
            if expected_plan_fingerprint != current.plan_fingerprint:
                raise DramaShotVideoStoreError(
                    "shot video plan changed; refresh before replacement"
                )
        elif expected_plan_fingerprint is not None:
            raise DramaShotVideoStoreError(
                "expected shot video plan fingerprint requires an existing plan"
            )

        def precommit() -> None:
            final = _build_from_sources(_load_sources(workspace, episode_no=number))
            if final.plan_fingerprint != desired.plan_fingerprint:
                raise DramaShotVideoStoreError(
                    "shot video plan sources changed concurrently"
                )

        _write_plan(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_plan(workspace, episode_no=number)
        if persisted.plan_fingerprint != desired.plan_fingerprint:
            raise DramaShotVideoStoreError(
                "persisted shot video plan failed verification"
            )
        return persisted


def create_episode_shot_video_plan(
    workspace: str,
    *,
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_plan_fingerprint: str | None = None,
) -> EpisodeShotVideoPlan:
    try:
        return _create_episode_shot_video_plan_impl(
            workspace,
            episode_no=episode_no,
            replace_stale=replace_stale,
            expected_plan_fingerprint=expected_plan_fingerprint,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        if isinstance(exc, DramaShotVideoStoreError):
            raise DramaShotVideoStoreError(str(exc)) from None
        raise DramaShotVideoStoreError("shot video plan creation was rejected") from None
