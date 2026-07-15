"""Strict persistence and freshness inspection for drama RenderPlan artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_art_direction_store import (
    DramaArtDirectionStoreError,
    resolve_selected_art_direction_ref,
)
from .drama_render_plan import build_render_plan
from .drama_schemas import ArtDirectionRef, RenderPlan, episode_paths, normalize_episode_no
from .drama_store import (
    FreshEpisodeSnapshot,
    _read_strict_workspace_bytes,
    _validate_render_workspace_root,
    load_fresh_episode_for_render,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


MAX_RENDER_PLAN_BYTES = 2_000_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

RenderPlanState = Literal[
    "needs_render_plan",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class RenderPlanStoreError(ValueError):
    pass


class _RenderPlanReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RenderPlanInspection:
    state: RenderPlanState
    reasons: tuple[str, ...]
    plan: RenderPlan | None = None


def render_plan_path(workspace: str, *, episode_no: int = 1) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("render plan path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.render_plan.json"


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _RenderPlanReadError("schema_invalid")
        out[key] = value
    return out


def _reject_json_constant(_value: str) -> None:
    raise _RenderPlanReadError("schema_invalid")


def _parse_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _RenderPlanReadError("schema_invalid")
    return number


def _read_render_plan(workspace: str, *, episode_no: int) -> RenderPlan:
    path = render_plan_path(workspace, episode_no=episode_no)
    root = paths.workspace_root(workspace)
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_RENDER_PLAN_BYTES,
        )
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise _RenderPlanReadError("schema_invalid") from exc
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except _RenderPlanReadError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise _RenderPlanReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "plan_fingerprint",
        "plan",
    }:
        raise _RenderPlanReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _RenderPlanReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_render_plan":
        raise _RenderPlanReadError("schema_invalid")
    if not isinstance(raw["plan_fingerprint"], str) or _SHA256_RE.fullmatch(
        raw["plan_fingerprint"]
    ) is None:
        raise _RenderPlanReadError("plan_hash_mismatch")
    if not isinstance(raw["plan"], dict):
        raise _RenderPlanReadError("schema_invalid")
    try:
        plan = RenderPlan(**raw["plan"])
    except (TypeError, ValueError) as exc:
        raise _RenderPlanReadError("schema_invalid") from exc
    if raw["plan_fingerprint"] != plan.plan_fingerprint:
        raise _RenderPlanReadError("plan_hash_mismatch")
    return plan


def _source_snapshot(workspace: str, *, episode_no: int) -> FreshEpisodeSnapshot:
    return load_fresh_episode_for_render(workspace, episode_no=episode_no)


def inspect_render_plan(workspace: str, *, episode_no: int = 1) -> RenderPlanInspection:
    number = normalize_episode_no(episode_no)
    try:
        plan = _read_render_plan(workspace, episode_no=number)
    except FileNotFoundError:
        plan = None
    except _RenderPlanReadError as exc:
        return RenderPlanInspection("invalid", (exc.reason,))

    try:
        snapshot = _source_snapshot(workspace, episode_no=number)
    except FileNotFoundError:
        return RenderPlanInspection("blocked_source", ("source_missing",), plan)
    except (OSError, TypeError, ValueError):
        return RenderPlanInspection("blocked_source", ("source_stale",), plan)

    try:
        selected_art_ref = resolve_selected_art_direction_ref(
            workspace,
            season_no=snapshot.episode["season_no"],
        )
    except (OSError, TypeError, ValueError, DramaArtDirectionStoreError):
        return RenderPlanInspection(
            "blocked_source",
            ("art_direction_catalog_invalid",),
            plan,
        )
    if plan is not None and selected_art_ref is None and plan.art_direction_ref is not None:
        return RenderPlanInspection(
            "blocked_source",
            ("art_direction_catalog_missing",),
            plan,
        )

    try:
        expected = build_render_plan(
            snapshot,
            art_direction_ref=selected_art_ref,
        )
    except (TypeError, ValueError):
        return RenderPlanInspection("blocked_source", ("source_unrenderable",), plan)
    if plan is None:
        return RenderPlanInspection("needs_render_plan", ("missing",))
    if plan.episode_no != number or plan.season_no != snapshot.episode["season_no"]:
        return RenderPlanInspection("stale", ("episode_identity_mismatch",), plan)

    reasons: list[str] = []
    if plan.creative_fingerprint != expected.creative_fingerprint:
        reasons.append("creative_fingerprint_mismatch")
    if plan.source_episode_sha256 != expected.source_episode_sha256:
        reasons.append("creative_fingerprint_mismatch")
    if plan.character_projection_fingerprint != expected.character_projection_fingerprint:
        reasons.append("creative_fingerprint_mismatch")
    if plan.frozen_character_ids != expected.frozen_character_ids:
        reasons.append("creative_fingerprint_mismatch")
    if plan.art_direction_ref != expected.art_direction_ref:
        reasons.append("art_direction_ref_mismatch")
    if plan.plan_fingerprint != expected.plan_fingerprint:
        reasons.append("plan_source_mismatch")
    if reasons:
        return RenderPlanInspection("stale", tuple(dict.fromkeys(reasons)), plan)
    return RenderPlanInspection("fresh", (), plan)


def _render_plan_target_token(workspace: str, *, episode_no: int) -> tuple[Any, ...]:
    root = paths.workspace_root(workspace)
    path = render_plan_path(workspace, episode_no=episode_no)
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_RENDER_PLAN_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _write_render_plan(
    workspace: str,
    plan: RenderPlan,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_render_plan",
        "plan_fingerprint": plan.plan_fingerprint,
        "plan": model_to_dict(plan),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_RENDER_PLAN_BYTES:
        raise RenderPlanStoreError("render plan envelope exceeds its size limit")

    path = render_plan_path(workspace, episode_no=plan.episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RenderPlanStoreError("render plan path escapes the workspace") from exc

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise RenderPlanStoreError("strict no-follow render writes are unavailable")

    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = (
        f".{relative.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    )
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

        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise RenderPlanStoreError(
                "render plan changed concurrently; retry from inspection"
            )
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short render plan write")
            view = view[written:]
        os.close(temp_fd)
        temp_fd = None
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise RenderPlanStoreError(
                "render plan changed concurrently; retry from inspection"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except RenderPlanStoreError:
        raise
    except OSError as exc:
        raise RenderPlanStoreError("render plan could not be written safely") from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except OSError:
                pass
            try:
                os.close(directory_fd)
            except OSError:
                pass


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
            or info.st_size > MAX_RENDER_PLAN_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_RENDER_PLAN_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_RENDER_PLAN_BYTES:
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


def create_render_plan(
    workspace: str,
    *,
    episode_no: int = 1,
    art_direction_ref: ArtDirectionRef | Dict[str, Any] | None = None,
    replace_stale: bool = False,
) -> RenderPlan:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-render-plan"):
        return _create_render_plan_locked(
            workspace,
            episode_no=number,
            art_direction_ref=art_direction_ref,
            replace_stale=replace_stale,
        )


def _create_render_plan_locked(
    workspace: str,
    *,
    episode_no: int,
    art_direction_ref: ArtDirectionRef | Dict[str, Any] | None,
    replace_stale: bool,
) -> RenderPlan:
    target_token = _render_plan_target_token(workspace, episode_no=episode_no)
    inspection = inspect_render_plan(workspace, episode_no=episode_no)
    if inspection.state == "invalid":
        raise RenderPlanStoreError("invalid render plan must be repaired explicitly")
    if inspection.state == "blocked_source":
        raise RenderPlanStoreError("fresh render source is required")

    snapshot = _source_snapshot(workspace, episode_no=episode_no)
    try:
        selected_art_ref = resolve_selected_art_direction_ref(
            workspace,
            season_no=snapshot.episode["season_no"],
        )
    except (OSError, TypeError, ValueError, DramaArtDirectionStoreError) as exc:
        raise RenderPlanStoreError("valid art direction catalog is required") from exc
    if art_direction_ref is not None:
        expected_ref = (
            art_direction_ref
            if isinstance(art_direction_ref, ArtDirectionRef)
            else ArtDirectionRef(**art_direction_ref)
        )
        if selected_art_ref is None or expected_ref != selected_art_ref:
            raise RenderPlanStoreError(
                "art direction ref does not match the selected catalog version"
            )
    desired = build_render_plan(snapshot, art_direction_ref=selected_art_ref)

    if inspection.state == "fresh" and inspection.plan is not None:
        if inspection.plan.plan_fingerprint == desired.plan_fingerprint:
            return inspection.plan
        if not replace_stale:
            raise RenderPlanStoreError("render plan inputs changed; explicit replacement is required")
    elif inspection.state == "stale" and not replace_stale:
        raise RenderPlanStoreError("stale render plan requires explicit replacement")

    def precommit() -> None:
        final_snapshot = _source_snapshot(workspace, episode_no=episode_no)
        if final_snapshot.snapshot_fingerprint != snapshot.snapshot_fingerprint:
            raise RenderPlanStoreError(
                "render source changed concurrently; retry from inspection"
            )
        try:
            final_art_ref = resolve_selected_art_direction_ref(
                workspace,
                season_no=final_snapshot.episode["season_no"],
            )
        except (OSError, TypeError, ValueError, DramaArtDirectionStoreError) as exc:
            raise RenderPlanStoreError(
                "art direction source changed concurrently"
            ) from exc
        if final_art_ref != selected_art_ref:
            raise RenderPlanStoreError("art direction source changed concurrently")

    _write_render_plan(
        workspace,
        desired,
        expected_target_token=target_token,
        precommit_check=precommit,
    )
    persisted = _read_render_plan(workspace, episode_no=episode_no)
    if persisted.plan_fingerprint != desired.plan_fingerprint:
        raise RenderPlanStoreError("persisted render plan failed verification")
    return persisted


def load_fresh_render_plan(workspace: str, *, episode_no: int = 1) -> RenderPlan:
    inspection = inspect_render_plan(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.plan is None:
        raise RenderPlanStoreError(f"render plan is not fresh: {inspection.state}")
    return inspection.plan
