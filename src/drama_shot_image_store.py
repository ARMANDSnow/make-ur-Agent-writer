"""Strict local persistence and freshness for stage-C1 shot image plans."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping

from . import paths
from .drama_art_direction_store import load_fresh_art_direction_catalog
from .drama_asset_versions import (
    inspect_episode_asset_manifest,
    load_fresh_character_asset_catalog,
    load_fresh_episode_prop_or_clue_asset_manifest,
    load_fresh_episode_scene_asset_manifest,
    load_fresh_prop_or_clue_asset_catalog,
    load_fresh_scene_asset_catalog,
)
from .drama_render_store import load_fresh_render_plan
from .drama_schemas import (
    ArtDirectionCatalog,
    CharacterAssetCatalog,
    EpisodeAssetManifest,
    EpisodePropOrClueAssetManifest,
    EpisodeSceneAssetManifest,
    EpisodeShotImagePlan,
    PropOrClueAssetCatalog,
    RenderPlan,
    SceneAssetCatalog,
    ShotImageReferencePolicy,
    episode_paths,
    normalize_episode_no,
)
from .drama_shot_image import (
    build_episode_shot_image_plan,
    shot_image_affected_ids,
    shot_image_character_mapping,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_IMAGE_PLAN_BYTES = 4_000_000
MAX_SHOT_IMAGE_REFERENCE_BYTES = 5 * 1024 * 1024

ShotImagePlanState = Literal[
    "needs_shot_image_plan",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaShotImageStoreError(ValueError):
    pass


class _PlanReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShotImagePlanInspection:
    state: ShotImagePlanState
    reasons: tuple[str, ...]
    plan: EpisodeShotImagePlan | None = None
    affected_shot_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ShotImageSources:
    render_plan: RenderPlan
    character_catalog: CharacterAssetCatalog
    character_manifest: EpisodeAssetManifest
    character_manifest_stale: bool
    art_direction_catalog: ArtDirectionCatalog | None
    scene_catalog: SceneAssetCatalog
    scene_manifest: EpisodeSceneAssetManifest
    prop_clue_catalog: PropOrClueAssetCatalog
    prop_clue_manifest: EpisodePropOrClueAssetManifest


def shot_image_plan_path(workspace: str, *, episode_no: int = 1) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("shot image plan path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.shot_image_plan.json"


def _read_plan(workspace: str, *, episode_no: int) -> EpisodeShotImagePlan:
    root = paths.workspace_root(workspace)
    path = shot_image_plan_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_PLAN_BYTES,
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
    if raw["artifact_type"] != "drama_episode_shot_image_plan":
        raise _PlanReadError("schema_invalid")
    if not isinstance(raw["plan"], dict):
        raise _PlanReadError("schema_invalid")
    try:
        plan = EpisodeShotImagePlan(**raw["plan"])
    except (TypeError, ValueError) as exc:
        raise _PlanReadError("schema_invalid") from exc
    if raw["plan_fingerprint"] != plan.plan_fingerprint:
        raise _PlanReadError("plan_hash_mismatch")
    if plan.episode_no != episode_no:
        raise _PlanReadError("schema_invalid")
    return plan


def _load_sources(workspace: str, *, episode_no: int) -> _ShotImageSources:
    render_plan = load_fresh_render_plan(workspace, episode_no=episode_no)
    character_catalog = load_fresh_character_asset_catalog(
        workspace,
        season_no=render_plan.season_no,
    )
    character_manifest_inspection = inspect_episode_asset_manifest(
        workspace,
        episode_no=episode_no,
    )
    if (
        character_manifest_inspection.manifest is None
        or character_manifest_inspection.state not in {"fresh", "stale"}
        or "render_plan_fingerprint_mismatch" in character_manifest_inspection.reasons
        or "render_plan_stale" in character_manifest_inspection.reasons
    ):
        raise DramaShotImageStoreError("character manifest source is unavailable")
    character_manifest = character_manifest_inspection.manifest
    scene_catalog = load_fresh_scene_asset_catalog(
        workspace,
        season_no=render_plan.season_no,
    )
    scene_manifest = load_fresh_episode_scene_asset_manifest(
        workspace,
        episode_no=episode_no,
    )
    prop_clue_catalog = load_fresh_prop_or_clue_asset_catalog(
        workspace,
        season_no=render_plan.season_no,
    )
    prop_clue_manifest = load_fresh_episode_prop_or_clue_asset_manifest(
        workspace,
        episode_no=episode_no,
    )
    art_direction_catalog = None
    if render_plan.art_direction_ref is not None:
        art_direction_catalog = load_fresh_art_direction_catalog(
            workspace,
            season_no=render_plan.season_no,
        )
    return _ShotImageSources(
        render_plan=render_plan,
        character_catalog=character_catalog,
        character_manifest=character_manifest,
        character_manifest_stale=character_manifest_inspection.state == "stale",
        art_direction_catalog=art_direction_catalog,
        scene_catalog=scene_catalog,
        scene_manifest=scene_manifest,
        prop_clue_catalog=prop_clue_catalog,
        prop_clue_manifest=prop_clue_manifest,
    )


def _build_from_sources(
    sources: _ShotImageSources,
    *,
    shot_character_ids: Mapping[str, list[str]],
    reference_policy: ShotImageReferencePolicy | Dict[str, Any],
    character_binding_revision: int,
) -> EpisodeShotImagePlan:
    return build_episode_shot_image_plan(
        sources.render_plan,
        sources.character_catalog,
        sources.character_manifest,
        sources.scene_catalog,
        sources.scene_manifest,
        sources.prop_clue_catalog,
        sources.prop_clue_manifest,
        art_direction_catalog=sources.art_direction_catalog,
        shot_character_ids=shot_character_ids,
        reference_policy=reference_policy,
        character_binding_revision=character_binding_revision,
    )


def _validate_plan_artifacts(workspace: str, plan: EpisodeShotImagePlan) -> None:
    root = paths.workspace_root(workspace)
    by_path: Dict[str, tuple[int, str]] = {}
    for shot in plan.shot_specs:
        for reference in shot.image_references:
            identity = (reference.artifact_size_bytes, reference.artifact_sha256)
            previous = by_path.get(reference.artifact_path)
            if previous is not None:
                if previous != identity:
                    raise DramaShotImageStoreError(
                        "shot image artifact path identifies inconsistent bytes"
                    )
                continue
            payload = _read_strict_workspace_bytes(
                root,
                root / reference.artifact_path,
                maximum=MAX_SHOT_IMAGE_REFERENCE_BYTES,
            )
            if len(payload) != reference.artifact_size_bytes or hashlib.sha256(
                payload
            ).hexdigest() != reference.artifact_sha256:
                raise DramaShotImageStoreError("shot image artifact bytes changed")
            by_path[reference.artifact_path] = identity


def inspect_episode_shot_image_plan(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotImagePlanInspection:
    try:
        number = normalize_episode_no(episode_no)
        stored = _read_plan(workspace, episode_no=number)
    except FileNotFoundError:
        stored = None
    except _PlanReadError as exc:
        return ShotImagePlanInspection("invalid", (exc.reason,))
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImagePlanInspection("invalid", ("request_invalid",))

    try:
        sources = _load_sources(workspace, episode_no=number)
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImagePlanInspection(
            "blocked_source",
            ("source_not_fresh",),
            stored,
        )
    if stored is None:
        return ShotImagePlanInspection("needs_shot_image_plan", ("missing",))
    try:
        expected = _build_from_sources(
            sources,
            shot_character_ids=shot_image_character_mapping(stored),
            reference_policy=stored.reference_policy,
            character_binding_revision=stored.character_binding_revision,
        )
        _validate_plan_artifacts(workspace, expected)
    except (OSError, RecursionError, TypeError, ValueError):
        if sources.character_manifest_stale:
            return ShotImagePlanInspection(
                "blocked_source",
                ("source_not_fresh",),
                stored,
            )
        return ShotImagePlanInspection(
            "stale",
            ("stored_binding_or_source_mismatch",),
            stored,
        )
    reasons: list[str] = []
    if stored.render_plan_fingerprint != expected.render_plan_fingerprint:
        reasons.append("render_plan_fingerprint_mismatch")
    if stored.used_character_fingerprint != expected.used_character_fingerprint:
        reasons.append("used_character_fingerprint_mismatch")
    if (
        stored.art_direction_version_fingerprint
        != expected.art_direction_version_fingerprint
    ):
        reasons.append("art_direction_fingerprint_mismatch")
    if stored.scene_manifest_fingerprint != expected.scene_manifest_fingerprint:
        reasons.append("scene_manifest_fingerprint_mismatch")
    if (
        stored.prop_clue_manifest_fingerprint
        != expected.prop_clue_manifest_fingerprint
    ):
        reasons.append("prop_clue_manifest_fingerprint_mismatch")
    if stored.plan_fingerprint != expected.plan_fingerprint:
        reasons.append("plan_source_mismatch")
    if reasons:
        return ShotImagePlanInspection(
            "stale",
            tuple(reasons),
            stored,
            tuple(shot_image_affected_ids(stored, expected)),
        )
    return ShotImagePlanInspection("fresh", (), stored)


def load_fresh_episode_shot_image_plan(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotImagePlan:
    inspection = inspect_episode_shot_image_plan(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.plan is None:
        raise DramaShotImageStoreError(
            f"shot image plan is not fresh: {inspection.state}"
        )
    return inspection.plan


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_PLAN_BYTES,
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
            or info.st_size > MAX_SHOT_IMAGE_PLAN_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_IMAGE_PLAN_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_IMAGE_PLAN_BYTES:
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
    plan: EpisodeShotImagePlan,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_image_plan",
        "plan_fingerprint": plan.plan_fingerprint,
        "plan": model_to_dict(plan),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_IMAGE_PLAN_BYTES:
        raise DramaShotImageStoreError("shot image plan exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = shot_image_plan_path(workspace, episode_no=plan.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotImageStoreError("shot image plan path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaShotImageStoreError("shot image plan path is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaShotImageStoreError("strict no-follow shot image writes are unavailable")

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
            raise DramaShotImageStoreError(
                "shot image plan changed concurrently; retry from inspection"
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
                raise OSError("short shot image plan write")
            view = view[written:]
        os.fsync(temp_fd)
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotImageStoreError(
                "shot image plan changed concurrently; retry from inspection"
            )
        opened_info = os.fstat(temp_fd)
        named_info = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_info.st_mode)
            or not stat.S_ISREG(named_info.st_mode)
            or (opened_info.st_dev, opened_info.st_ino)
            != (named_info.st_dev, named_info.st_ino)
        ):
            raise DramaShotImageStoreError(
                "shot image temporary file changed concurrently"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except DramaShotImageStoreError:
        raise
    except OSError as exc:
        raise DramaShotImageStoreError(
            "shot image plan could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if (
            directory_fd is not None
            and temp_created
            and temp_identity is not None
        ):
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


def _create_episode_shot_image_plan_impl(
    workspace: str,
    *,
    shot_character_ids: Mapping[str, list[str]],
    reference_policy: ShotImageReferencePolicy | Dict[str, Any],
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_plan_fingerprint: str | None = None,
) -> EpisodeShotImagePlan:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-plan"):
        path = shot_image_plan_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_plan(workspace, episode_no=number)
        except FileNotFoundError:
            current = None
        except _PlanReadError as exc:
            raise DramaShotImageStoreError(
                "invalid shot image plan must be repaired explicitly"
            ) from exc

        sources = _load_sources(workspace, episode_no=number)
        base_revision = current.character_binding_revision if current is not None else 0
        desired = _build_from_sources(
            sources,
            shot_character_ids=shot_character_ids,
            reference_policy=reference_policy,
            character_binding_revision=base_revision,
        )
        if (
            current is not None
            and current.character_binding_fingerprint
            != desired.character_binding_fingerprint
        ):
            desired = _build_from_sources(
                sources,
                shot_character_ids=shot_character_ids,
                reference_policy=reference_policy,
                character_binding_revision=current.character_binding_revision + 1,
            )
        _validate_plan_artifacts(workspace, desired)
        if current is not None and current.plan_fingerprint == desired.plan_fingerprint:
            return current
        if current is not None:
            if not replace_stale:
                raise DramaShotImageStoreError(
                    "shot image plan replacement requires explicit confirmation"
                )
            if expected_plan_fingerprint != current.plan_fingerprint:
                raise DramaShotImageStoreError(
                    "shot image plan changed; refresh before replacement"
                )
        elif expected_plan_fingerprint is not None:
            raise DramaShotImageStoreError(
                "expected shot image plan fingerprint requires an existing plan"
            )

        desired_mapping = shot_image_character_mapping(desired)
        desired_policy = desired.reference_policy
        desired_revision = desired.character_binding_revision

        def precommit() -> None:
            final_sources = _load_sources(workspace, episode_no=number)
            final = _build_from_sources(
                final_sources,
                shot_character_ids=desired_mapping,
                reference_policy=desired_policy,
                character_binding_revision=desired_revision,
            )
            _validate_plan_artifacts(workspace, final)
            if final.plan_fingerprint != desired.plan_fingerprint:
                raise DramaShotImageStoreError(
                    "shot image plan sources changed concurrently"
                )

        _write_plan(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_plan(workspace, episode_no=number)
        if persisted.plan_fingerprint != desired.plan_fingerprint:
            raise DramaShotImageStoreError(
                "persisted shot image plan failed verification"
            )
        return persisted


def create_episode_shot_image_plan(
    workspace: str,
    *,
    shot_character_ids: Mapping[str, list[str]],
    reference_policy: ShotImageReferencePolicy | Dict[str, Any],
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_plan_fingerprint: str | None = None,
) -> EpisodeShotImagePlan:
    try:
        return _create_episode_shot_image_plan_impl(
            workspace,
            shot_character_ids=shot_character_ids,
            reference_policy=reference_policy,
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
        if isinstance(exc, DramaShotImageStoreError):
            raise DramaShotImageStoreError(str(exc)) from None
        raise DramaShotImageStoreError("shot image plan creation was rejected") from None
