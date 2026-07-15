"""Strict persistence, CAS selection, and episode freezing for drama assets."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping

from . import paths
from .drama_assets import (
    add_scene_asset as add_scene_asset_pure,
    append_asset_version,
    append_scene_asset_version as append_scene_asset_version_pure,
    build_character_asset_catalog,
    build_episode_asset_manifest,
    build_episode_scene_asset_manifest,
    build_scene_asset_catalog,
    character_render_identity_fingerprint,
    select_asset_version,
    select_scene_asset_version as select_scene_asset_version_pure,
)
from .drama_render_store import inspect_render_plan, load_fresh_render_plan
from .drama_schemas import (
    AssetArtifact,
    AssetVersion,
    CharacterAssetCatalog,
    CharacterSheet,
    EpisodeAssetManifest,
    EpisodeSceneAssetManifest,
    SceneAssetCatalog,
    SceneAssetVersion,
    character_paths,
    episode_paths,
    normalize_episode_no,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_ASSET_CATALOG_BYTES = 4_000_000
MAX_ASSET_MANIFEST_BYTES = 1_000_000
MAX_ASSET_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_SCENE_CATALOG_BYTES = 4_000_000
MAX_SCENE_MANIFEST_BYTES = 2_000_000
MAX_SCENE_ARTIFACT_BYTES = 5 * 1024 * 1024

AssetCatalogState = Literal[
    "needs_asset_catalog",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]
AssetManifestState = Literal[
    "needs_asset_manifest",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]
SceneCatalogState = Literal[
    "needs_scene_catalog",
    "fresh",
    "invalid",
]
SceneManifestState = Literal[
    "needs_scene_manifest",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaAssetStoreError(ValueError):
    pass


class _ArtifactReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _ActiveAssetSourceError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AssetCatalogInspection:
    state: AssetCatalogState
    reasons: tuple[str, ...]
    catalog: CharacterAssetCatalog | None = None


@dataclass(frozen=True)
class AssetManifestInspection:
    state: AssetManifestState
    reasons: tuple[str, ...]
    manifest: EpisodeAssetManifest | None = None


@dataclass(frozen=True)
class SceneCatalogInspection:
    state: SceneCatalogState
    reasons: tuple[str, ...]
    catalog: SceneAssetCatalog | None = None


@dataclass(frozen=True)
class SceneManifestInspection:
    state: SceneManifestState
    reasons: tuple[str, ...]
    manifest: EpisodeSceneAssetManifest | None = None


def _strict_season_no(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("season_no must be a strict positive integer")
    return value


def character_asset_catalog_path(workspace: str, *, season_no: int = 1) -> Path:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    cp = character_paths(workspace, season_no=season)
    if cp.root != root:
        raise ValueError("character asset catalog path does not match the workspace")
    return root / "data" / "assets" / f"season_{season:02d}.character_assets.json"


def episode_asset_manifest_path(workspace: str, *, episode_no: int = 1) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("episode asset manifest path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.asset_manifest.json"


def scene_asset_catalog_path(workspace: str, *, season_no: int = 1) -> Path:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    return root / "data" / "assets" / f"season_{season:02d}.scene_assets.json"


def episode_scene_asset_manifest_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("scene manifest path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.scene_asset_manifest.json"


def _read_catalog(workspace: str, *, season_no: int) -> CharacterAssetCatalog:
    root = paths.workspace_root(workspace)
    path = character_asset_catalog_path(workspace, season_no=season_no)
    try:
        raw = _read_strict_workspace_json(root, path, maximum=MAX_ASSET_CATALOG_BYTES)
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "catalog_fingerprint",
        "catalog",
    }:
        raise _ArtifactReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ArtifactReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_character_asset_catalog":
        raise _ArtifactReadError("schema_invalid")
    if not isinstance(raw["catalog"], dict):
        raise _ArtifactReadError("schema_invalid")
    try:
        catalog = CharacterAssetCatalog(**raw["catalog"])
    except (TypeError, ValueError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if raw["catalog_fingerprint"] != catalog.catalog_fingerprint:
        raise _ArtifactReadError("catalog_hash_mismatch")
    if catalog.season_no != season_no:
        raise _ArtifactReadError("schema_invalid")
    return catalog


def _read_manifest(workspace: str, *, episode_no: int) -> EpisodeAssetManifest:
    root = paths.workspace_root(workspace)
    path = episode_asset_manifest_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(root, path, maximum=MAX_ASSET_MANIFEST_BYTES)
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "manifest_fingerprint",
        "manifest",
    }:
        raise _ArtifactReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ArtifactReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_asset_manifest":
        raise _ArtifactReadError("schema_invalid")
    if not isinstance(raw["manifest"], dict):
        raise _ArtifactReadError("schema_invalid")
    try:
        manifest = EpisodeAssetManifest(**raw["manifest"])
    except (TypeError, ValueError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if raw["manifest_fingerprint"] != manifest.manifest_fingerprint:
        raise _ArtifactReadError("manifest_hash_mismatch")
    if manifest.episode_no != episode_no:
        raise _ArtifactReadError("schema_invalid")
    return manifest


def _read_scene_catalog(workspace: str, *, season_no: int) -> SceneAssetCatalog:
    root = paths.workspace_root(workspace)
    path = scene_asset_catalog_path(workspace, season_no=season_no)
    try:
        raw = _read_strict_workspace_json(root, path, maximum=MAX_SCENE_CATALOG_BYTES)
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "catalog_fingerprint",
        "catalog",
    }:
        raise _ArtifactReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ArtifactReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_scene_asset_catalog":
        raise _ArtifactReadError("schema_invalid")
    if not isinstance(raw["catalog"], dict):
        raise _ArtifactReadError("schema_invalid")
    try:
        catalog = SceneAssetCatalog(**raw["catalog"])
    except (TypeError, ValueError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if raw["catalog_fingerprint"] != catalog.catalog_fingerprint:
        raise _ArtifactReadError("catalog_hash_mismatch")
    if catalog.season_no != season_no:
        raise _ArtifactReadError("schema_invalid")
    return catalog


def _read_scene_manifest(
    workspace: str,
    *,
    episode_no: int,
) -> EpisodeSceneAssetManifest:
    root = paths.workspace_root(workspace)
    path = episode_scene_asset_manifest_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(root, path, maximum=MAX_SCENE_MANIFEST_BYTES)
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "manifest_fingerprint",
        "manifest",
    }:
        raise _ArtifactReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ArtifactReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_scene_asset_manifest":
        raise _ArtifactReadError("schema_invalid")
    if not isinstance(raw["manifest"], dict):
        raise _ArtifactReadError("schema_invalid")
    try:
        manifest = EpisodeSceneAssetManifest(**raw["manifest"])
    except (TypeError, ValueError) as exc:
        raise _ArtifactReadError("schema_invalid") from exc
    if raw["manifest_fingerprint"] != manifest.manifest_fingerprint:
        raise _ArtifactReadError("manifest_hash_mismatch")
    if manifest.episode_no != episode_no:
        raise _ArtifactReadError("schema_invalid")
    return manifest


def _load_character_source(
    workspace: str,
    *,
    season_no: int,
) -> tuple[CharacterSheet, Dict[str, AssetArtifact]]:
    root = paths.workspace_root(workspace)
    cp = character_paths(workspace, season_no=season_no)
    raw = _read_strict_workspace_json(
        root,
        cp.sheet_path,
        maximum=MAX_ASSET_CATALOG_BYTES,
    )
    sheet = CharacterSheet(**raw)
    if sheet.season_no != season_no:
        raise ValueError("character sheet belongs to another season")
    artifacts: Dict[str, AssetArtifact] = {}
    for character in sheet.characters:
        for reference in character.reference_images:
            path = root / reference.path
            payload = _read_strict_workspace_bytes(
                root,
                path,
                maximum=MAX_ASSET_ARTIFACT_BYTES,
            )
            artifact = AssetArtifact(
                path=reference.path,
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            )
            previous = artifacts.get(reference.path)
            if previous is not None and previous != artifact:
                raise ValueError("character reference path resolves inconsistently")
            artifacts[reference.path] = artifact
    return sheet, artifacts


def _expected_catalog(
    workspace: str,
    *,
    season_no: int,
    previous: CharacterAssetCatalog | None,
) -> CharacterAssetCatalog:
    sheet, artifacts = _load_character_source(workspace, season_no=season_no)
    return build_character_asset_catalog(
        sheet,
        artifact_records=artifacts,
        previous=previous,
    )


def inspect_character_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> AssetCatalogInspection:
    season = _strict_season_no(season_no)
    try:
        catalog = _read_catalog(workspace, season_no=season)
    except FileNotFoundError:
        catalog = None
    except _ArtifactReadError as exc:
        return AssetCatalogInspection("invalid", (exc.reason,))

    try:
        expected = _expected_catalog(
            workspace,
            season_no=season,
            previous=catalog,
        )
    except FileNotFoundError:
        return AssetCatalogInspection("blocked_source", ("source_missing",), catalog)
    except (OSError, TypeError, ValueError, RecursionError):
        return AssetCatalogInspection("blocked_source", ("source_invalid",), catalog)
    if catalog is None:
        return AssetCatalogInspection("needs_asset_catalog", ("missing",))
    if catalog.source_fingerprint != expected.source_fingerprint:
        return AssetCatalogInspection("stale", ("source_fingerprint_mismatch",), catalog)
    return AssetCatalogInspection("fresh", (), catalog)


def _target_token(
    root: Path,
    path: Path,
    *,
    maximum: int,
) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(root, path, maximum=maximum)
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _target_token_at(directory_fd: int, name: str, *, maximum: int) -> tuple[Any, ...]:
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
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > maximum:
            return ("invalid",)
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


def _write_envelope(
    *,
    root: Path,
    path: Path,
    envelope: Dict[str, Any],
    maximum: int,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > maximum:
        raise DramaAssetStoreError("drama asset envelope exceeds its size limit")
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaAssetStoreError("drama asset path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaAssetStoreError("drama asset path is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaAssetStoreError("strict no-follow drama asset writes are unavailable")

    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = f".{relative.name}.tmp.{os.getpid()}.{threading.get_ident()}"
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
        if (
            _target_token_at(directory_fd, relative.name, maximum=maximum)
            != expected_target_token
        ):
            raise DramaAssetStoreError(
                "drama asset changed concurrently; retry from inspection"
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
                raise OSError("short drama asset write")
            view = view[written:]
        os.close(temp_fd)
        temp_fd = None
        if precommit_check is not None:
            precommit_check()
        if (
            _target_token_at(directory_fd, relative.name, maximum=maximum)
            != expected_target_token
        ):
            raise DramaAssetStoreError(
                "drama asset changed concurrently; retry from inspection"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except DramaAssetStoreError:
        raise
    except OSError as exc:
        raise DramaAssetStoreError("drama asset could not be written safely") from exc
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


def _write_catalog(
    workspace: str,
    catalog: CharacterAssetCatalog,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    root = paths.workspace_root(workspace)
    _write_envelope(
        root=root,
        path=character_asset_catalog_path(workspace, season_no=catalog.season_no),
        envelope={
            "schema_version": 1,
            "artifact_type": "drama_character_asset_catalog",
            "catalog_fingerprint": catalog.catalog_fingerprint,
            "catalog": model_to_dict(catalog),
        },
        maximum=MAX_ASSET_CATALOG_BYTES,
        expected_target_token=expected_target_token,
        precommit_check=precommit_check,
    )


def _write_manifest(
    workspace: str,
    manifest: EpisodeAssetManifest,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    root = paths.workspace_root(workspace)
    _write_envelope(
        root=root,
        path=episode_asset_manifest_path(workspace, episode_no=manifest.episode_no),
        envelope={
            "schema_version": 1,
            "artifact_type": "drama_episode_asset_manifest",
            "manifest_fingerprint": manifest.manifest_fingerprint,
            "manifest": model_to_dict(manifest),
        },
        maximum=MAX_ASSET_MANIFEST_BYTES,
        expected_target_token=expected_target_token,
        precommit_check=precommit_check,
    )


def _write_scene_catalog(
    workspace: str,
    catalog: SceneAssetCatalog,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    root = paths.workspace_root(workspace)
    _write_envelope(
        root=root,
        path=scene_asset_catalog_path(workspace, season_no=catalog.season_no),
        envelope={
            "schema_version": 1,
            "artifact_type": "drama_scene_asset_catalog",
            "catalog_fingerprint": catalog.catalog_fingerprint,
            "catalog": model_to_dict(catalog),
        },
        maximum=MAX_SCENE_CATALOG_BYTES,
        expected_target_token=expected_target_token,
        precommit_check=precommit_check,
    )


def _write_scene_manifest(
    workspace: str,
    manifest: EpisodeSceneAssetManifest,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    root = paths.workspace_root(workspace)
    _write_envelope(
        root=root,
        path=episode_scene_asset_manifest_path(
            workspace,
            episode_no=manifest.episode_no,
        ),
        envelope={
            "schema_version": 1,
            "artifact_type": "drama_episode_scene_asset_manifest",
            "manifest_fingerprint": manifest.manifest_fingerprint,
            "manifest": model_to_dict(manifest),
        },
        maximum=MAX_SCENE_MANIFEST_BYTES,
        expected_target_token=expected_target_token,
        precommit_check=precommit_check,
    )


def create_character_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> CharacterAssetCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-character-assets"):
        path = character_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_ASSET_CATALOG_BYTES)
        inspection = inspect_character_asset_catalog(workspace, season_no=season)
        if inspection.state == "fresh" and inspection.catalog is not None:
            return inspection.catalog
        if inspection.state == "stale":
            raise DramaAssetStoreError("stale character asset catalog requires explicit refresh")
        if inspection.state == "invalid":
            raise DramaAssetStoreError("invalid character asset catalog must be repaired explicitly")
        if inspection.state == "blocked_source":
            raise DramaAssetStoreError("valid character sheet and references are required")
        desired = _expected_catalog(workspace, season_no=season, previous=None)

        def precommit() -> None:
            final = _expected_catalog(workspace, season_no=season, previous=None)
            if final.source_fingerprint != desired.source_fingerprint:
                raise DramaAssetStoreError("character asset source changed concurrently")

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_catalog(workspace, season_no=season)
        if persisted.catalog_fingerprint != desired.catalog_fingerprint:
            raise DramaAssetStoreError("persisted character asset catalog failed verification")
        return persisted


def refresh_character_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> CharacterAssetCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-character-assets"):
        path = character_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_ASSET_CATALOG_BYTES)
        inspection = inspect_character_asset_catalog(workspace, season_no=season)
        if inspection.state == "fresh" and inspection.catalog is not None:
            return inspection.catalog
        if inspection.state == "invalid":
            raise DramaAssetStoreError("invalid character asset catalog must be repaired explicitly")
        if inspection.state == "blocked_source":
            raise DramaAssetStoreError("valid character sheet and references are required")
        previous = inspection.catalog
        desired = _expected_catalog(workspace, season_no=season, previous=previous)
        if previous is not None and desired.catalog_fingerprint == previous.catalog_fingerprint:
            return previous

        def precommit() -> None:
            final = _expected_catalog(workspace, season_no=season, previous=previous)
            if final.source_fingerprint != desired.source_fingerprint:
                raise DramaAssetStoreError("character asset source changed concurrently")

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_catalog(workspace, season_no=season)


def load_fresh_character_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> CharacterAssetCatalog:
    inspection = inspect_character_asset_catalog(workspace, season_no=season_no)
    if inspection.state != "fresh" or inspection.catalog is None:
        raise DramaAssetStoreError(
            f"character asset catalog is not fresh: {inspection.state}"
        )
    return inspection.catalog


def _verify_version_artifact(workspace: str, version: AssetVersion) -> None:
    if version.artifact is None:
        return
    root = paths.workspace_root(workspace)
    payload = _read_strict_workspace_bytes(
        root,
        root / version.artifact.path,
        maximum=MAX_ASSET_ARTIFACT_BYTES,
    )
    if (
        len(payload) != version.artifact.size_bytes
        or hashlib.sha256(payload).hexdigest() != version.artifact.sha256
    ):
        raise DramaAssetStoreError("asset version artifact does not match local bytes")


def _find_version(
    catalog: CharacterAssetCatalog,
    *,
    character_id: str,
    asset_version_id: str,
) -> AssetVersion:
    asset = next(
        (item for item in catalog.assets if item.asset_id == character_id),
        None,
    )
    if asset is None:
        raise DramaAssetStoreError("character asset does not exist")
    version = next(
        (
            item
            for item in asset.versions
            if item.asset_version_id == asset_version_id
        ),
        None,
    )
    if version is None:
        raise DramaAssetStoreError("asset version does not exist for this character")
    return version


def _validate_active_selected_assets(
    workspace: str,
    *,
    plan: Any,
    catalog: CharacterAssetCatalog,
) -> None:
    """Validate only frozen cast identities and selected artifact bytes."""

    root = paths.workspace_root(workspace)
    try:
        raw = _read_strict_workspace_json(
            root,
            character_paths(workspace, season_no=plan.season_no).sheet_path,
            maximum=MAX_ASSET_CATALOG_BYTES,
        )
        sheet = CharacterSheet(**raw)
    except (FileNotFoundError, OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ActiveAssetSourceError("active_character_source_invalid") from exc
    current_by_id = {item.id: item for item in sheet.characters}
    catalog_by_id = {item.asset_id: item for item in catalog.assets}
    for character_id in plan.frozen_character_ids:
        current = current_by_id.get(character_id)
        asset = catalog_by_id.get(character_id)
        if current is None or asset is None:
            raise _ActiveAssetSourceError("active_character_asset_missing")
        if character_render_identity_fingerprint(current) != asset.identity_fingerprint:
            raise _ActiveAssetSourceError("active_character_identity_mismatch")
        try:
            selected = _find_version(
                catalog,
                character_id=character_id,
                asset_version_id=asset.selected_version_id,
            )
            _verify_version_artifact(workspace, selected)
        except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
            raise _ActiveAssetSourceError("selected_artifact_mismatch") from exc


def append_character_asset_version(
    workspace: str,
    *,
    character_id: str,
    version: AssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
    season_no: int = 1,
) -> CharacterAssetCatalog:
    season = _strict_season_no(season_no)
    candidate = version if isinstance(version, AssetVersion) else AssetVersion(**version)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-character-assets"):
        path = character_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_ASSET_CATALOG_BYTES)
        current = load_fresh_character_asset_catalog(workspace, season_no=season)
        _verify_version_artifact(workspace, candidate)
        desired = append_asset_version(
            current,
            asset_id=character_id,
            version=candidate,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
        if desired.catalog_fingerprint == current.catalog_fingerprint:
            return current

        def precommit() -> None:
            final_source = _expected_catalog(
                workspace,
                season_no=season,
                previous=current,
            )
            if final_source.source_fingerprint != current.source_fingerprint:
                raise DramaAssetStoreError("character asset source changed concurrently")
            # Keep appended artifacts as the last source-side read before the
            # target CAS.  They are not projected from CharacterSheet, so a
            # final catalog refresh alone cannot detect their mutation.
            _verify_version_artifact(workspace, candidate)

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_catalog(workspace, season_no=season)


def select_character_asset_version(
    workspace: str,
    *,
    character_id: str,
    asset_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int = 1,
) -> CharacterAssetCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-character-assets"):
        path = character_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_ASSET_CATALOG_BYTES)
        current = load_fresh_character_asset_catalog(workspace, season_no=season)
        target_version = _find_version(
            current,
            character_id=character_id,
            asset_version_id=asset_version_id,
        )
        _verify_version_artifact(workspace, target_version)
        desired = select_asset_version(
            current,
            asset_id=character_id,
            asset_version_id=asset_version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
        )
        if desired.catalog_fingerprint == current.catalog_fingerprint:
            return current

        def precommit() -> None:
            final_source = _expected_catalog(
                workspace,
                season_no=season,
                previous=current,
            )
            if final_source.source_fingerprint != current.source_fingerprint:
                raise DramaAssetStoreError("character asset source changed concurrently")
            _verify_version_artifact(workspace, target_version)

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_catalog(workspace, season_no=season)


def inspect_episode_asset_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
) -> AssetManifestInspection:
    number = normalize_episode_no(episode_no)
    try:
        manifest = _read_manifest(workspace, episode_no=number)
    except FileNotFoundError:
        manifest = None
    except _ArtifactReadError as exc:
        return AssetManifestInspection("invalid", (exc.reason,))
    render = inspect_render_plan(workspace, episode_no=number)
    if render.state == "stale":
        if manifest is not None:
            return AssetManifestInspection("stale", ("render_plan_stale",), manifest)
        return AssetManifestInspection("blocked_source", ("render_plan_stale",))
    if render.state != "fresh" or render.plan is None:
        return AssetManifestInspection(
            "blocked_source",
            (f"render_plan_{render.state}",),
            manifest,
        )
    plan = render.plan
    try:
        catalog = _read_catalog(workspace, season_no=plan.season_no)
        _validate_active_selected_assets(
            workspace,
            plan=plan,
            catalog=catalog,
        )
        expected = build_episode_asset_manifest(plan, catalog)
    except FileNotFoundError:
        return AssetManifestInspection("blocked_source", ("source_missing",), manifest)
    except _ActiveAssetSourceError as exc:
        if manifest is not None:
            return AssetManifestInspection("stale", (exc.reason,), manifest)
        return AssetManifestInspection("blocked_source", (exc.reason,))
    except (OSError, TypeError, ValueError, RecursionError):
        return AssetManifestInspection("blocked_source", ("source_invalid",), manifest)
    if manifest is None:
        return AssetManifestInspection("needs_asset_manifest", ("missing",))
    reasons: list[str] = []
    if manifest.render_plan_fingerprint != expected.render_plan_fingerprint:
        reasons.append("render_plan_fingerprint_mismatch")
    if manifest.selection_fingerprint != expected.selection_fingerprint:
        reasons.append("selection_fingerprint_mismatch")
    if manifest.manifest_fingerprint != expected.manifest_fingerprint:
        reasons.append("manifest_source_mismatch")
    if reasons:
        return AssetManifestInspection("stale", tuple(reasons), manifest)
    return AssetManifestInspection("fresh", (), manifest)


def create_episode_asset_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
    replace_stale: bool = False,
) -> EpisodeAssetManifest:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-asset-manifest"):
        path = episode_asset_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path, maximum=MAX_ASSET_MANIFEST_BYTES)
        inspection = inspect_episode_asset_manifest(workspace, episode_no=number)
        if inspection.state == "invalid":
            raise DramaAssetStoreError("invalid episode asset manifest must be repaired explicitly")
        if inspection.state == "blocked_source":
            raise DramaAssetStoreError("fresh RenderPlan and character assets are required")
        if inspection.state == "fresh" and inspection.manifest is not None:
            return inspection.manifest
        if inspection.state == "stale" and not replace_stale:
            raise DramaAssetStoreError("stale episode asset manifest requires explicit replacement")

        plan = load_fresh_render_plan(workspace, episode_no=number)
        catalog = load_fresh_character_asset_catalog(
            workspace,
            season_no=plan.season_no,
        )
        _validate_active_selected_assets(
            workspace,
            plan=plan,
            catalog=catalog,
        )
        desired = build_episode_asset_manifest(plan, catalog)
        def precommit() -> None:
            final_plan = load_fresh_render_plan(workspace, episode_no=number)
            final_catalog = load_fresh_character_asset_catalog(
                workspace,
                season_no=final_plan.season_no,
            )
            _validate_active_selected_assets(
                workspace,
                plan=final_plan,
                catalog=final_catalog,
            )
            final = build_episode_asset_manifest(final_plan, final_catalog)
            if final.manifest_fingerprint != desired.manifest_fingerprint:
                raise DramaAssetStoreError("episode asset sources changed concurrently")

        _write_manifest(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_manifest(workspace, episode_no=number)
        if persisted.manifest_fingerprint != desired.manifest_fingerprint:
            raise DramaAssetStoreError("persisted episode asset manifest failed verification")
        return persisted


def load_fresh_episode_asset_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeAssetManifest:
    inspection = inspect_episode_asset_manifest(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.manifest is None:
        raise DramaAssetStoreError(
            f"episode asset manifest is not fresh: {inspection.state}"
        )
    return inspection.manifest


def inspect_scene_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> SceneCatalogInspection:
    season = _strict_season_no(season_no)
    try:
        catalog = _read_scene_catalog(workspace, season_no=season)
    except FileNotFoundError:
        return SceneCatalogInspection("needs_scene_catalog", ("missing",))
    except _ArtifactReadError as exc:
        return SceneCatalogInspection("invalid", (exc.reason,))
    return SceneCatalogInspection("fresh", (), catalog)


def load_fresh_scene_asset_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> SceneAssetCatalog:
    inspection = inspect_scene_asset_catalog(workspace, season_no=season_no)
    if inspection.state != "fresh" or inspection.catalog is None:
        raise DramaAssetStoreError(
            f"scene asset catalog is not fresh: {inspection.state}"
        )
    return inspection.catalog


def _verify_scene_version_artifact(
    workspace: str,
    version: SceneAssetVersion,
) -> None:
    if version.artifact is None:
        return
    root = paths.workspace_root(workspace)
    payload = _read_strict_workspace_bytes(
        root,
        root / version.artifact.path,
        maximum=MAX_SCENE_ARTIFACT_BYTES,
    )
    if (
        len(payload) != version.artifact.size_bytes
        or hashlib.sha256(payload).hexdigest() != version.artifact.sha256
    ):
        raise DramaAssetStoreError("scene artifact does not match local bytes")


def _find_scene_version(
    catalog: SceneAssetCatalog,
    *,
    scene_id: str,
    scene_version_id: str,
) -> SceneAssetVersion:
    asset = next(
        (item for item in catalog.assets if item.scene_id == scene_id),
        None,
    )
    if asset is None:
        raise DramaAssetStoreError("scene asset does not exist")
    version = next(
        (
            item
            for item in asset.versions
            if item.scene_version_id == scene_version_id
        ),
        None,
    )
    if version is None:
        raise DramaAssetStoreError("scene version does not exist")
    return version


def _create_scene_asset_catalog_impl(
    workspace: str,
    *,
    version: SceneAssetVersion | Dict[str, Any],
    season_no: int = 1,
) -> SceneAssetCatalog:
    season = _strict_season_no(season_no)
    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-scene-assets"):
        path = scene_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_SCENE_CATALOG_BYTES)
        inspection = inspect_scene_asset_catalog(workspace, season_no=season)
        if inspection.state == "invalid":
            raise DramaAssetStoreError("invalid scene catalog must be repaired explicitly")
        if inspection.state == "fresh" and inspection.catalog is not None:
            existing = next(
                (
                    asset
                    for asset in inspection.catalog.assets
                    if asset.scene_id == candidate.scene_id
                ),
                None,
            )
            if (
                existing is inspection.catalog.assets[0]
                and candidate.derived_from is None
                and existing.versions[0] == candidate
            ):
                _verify_scene_version_artifact(workspace, candidate)
                return inspection.catalog
            raise DramaAssetStoreError("scene catalog already exists; add explicitly")
        desired = build_scene_asset_catalog(candidate, season_no=season)
        _verify_scene_version_artifact(workspace, candidate)

        def precommit() -> None:
            _verify_scene_version_artifact(workspace, candidate)

        _write_scene_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_scene_catalog(workspace, season_no=season)
        if persisted.catalog_fingerprint != desired.catalog_fingerprint:
            raise DramaAssetStoreError("persisted scene catalog failed verification")
        return persisted


def _add_scene_asset_impl(
    workspace: str,
    *,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    season = _strict_season_no(season_no)
    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-scene-assets"):
        path = scene_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_SCENE_CATALOG_BYTES)
        current = load_fresh_scene_asset_catalog(workspace, season_no=season)
        _verify_scene_version_artifact(workspace, candidate)
        desired = add_scene_asset_pure(
            current,
            version=candidate,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
        if desired.catalog_fingerprint == current.catalog_fingerprint:
            return current

        def precommit() -> None:
            final = _read_scene_catalog(workspace, season_no=season)
            if final.catalog_fingerprint != current.catalog_fingerprint:
                raise DramaAssetStoreError("scene catalog changed concurrently")
            _verify_scene_version_artifact(workspace, candidate)

        _write_scene_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_scene_catalog(workspace, season_no=season)


def _append_scene_asset_version_impl(
    workspace: str,
    *,
    scene_id: str,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    season = _strict_season_no(season_no)
    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-scene-assets"):
        path = scene_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_SCENE_CATALOG_BYTES)
        current = load_fresh_scene_asset_catalog(workspace, season_no=season)
        _verify_scene_version_artifact(workspace, candidate)
        desired = append_scene_asset_version_pure(
            current,
            scene_id=scene_id,
            version=candidate,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
        if desired.catalog_fingerprint == current.catalog_fingerprint:
            return current

        def precommit() -> None:
            final = _read_scene_catalog(workspace, season_no=season)
            if final.catalog_fingerprint != current.catalog_fingerprint:
                raise DramaAssetStoreError("scene catalog changed concurrently")
            _verify_scene_version_artifact(workspace, candidate)

        _write_scene_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_scene_catalog(workspace, season_no=season)


def _select_scene_asset_version_impl(
    workspace: str,
    *,
    scene_id: str,
    scene_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-scene-assets"):
        path = scene_asset_catalog_path(workspace, season_no=season)
        token = _target_token(root, path, maximum=MAX_SCENE_CATALOG_BYTES)
        current = load_fresh_scene_asset_catalog(workspace, season_no=season)
        target_version = _find_scene_version(
            current,
            scene_id=scene_id,
            scene_version_id=scene_version_id,
        )
        _verify_scene_version_artifact(workspace, target_version)
        desired = select_scene_asset_version_pure(
            current,
            scene_id=scene_id,
            scene_version_id=scene_version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
        )
        if desired.catalog_fingerprint == current.catalog_fingerprint:
            return current

        def precommit() -> None:
            final = _read_scene_catalog(workspace, season_no=season)
            if final.catalog_fingerprint != current.catalog_fingerprint:
                raise DramaAssetStoreError("scene catalog changed concurrently")
            _verify_scene_version_artifact(workspace, target_version)

        _write_scene_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        return _read_scene_catalog(workspace, season_no=season)


def _scene_mapping_from_manifest(
    manifest: EpisodeSceneAssetManifest,
) -> Dict[str, str]:
    return {
        binding.shot_id: binding.scene_ref.scene_id
        for binding in manifest.shot_scene_refs
    }


def _validate_used_scene_artifacts(
    workspace: str,
    *,
    catalog: SceneAssetCatalog,
    shot_scene_ids: Mapping[str, str],
) -> None:
    for scene_id in sorted(set(shot_scene_ids.values())):
        asset = next(
            (item for item in catalog.assets if item.scene_id == scene_id),
            None,
        )
        if asset is None:
            raise DramaAssetStoreError("scene binding references an unknown scene")
        selected = _find_scene_version(
            catalog,
            scene_id=scene_id,
            scene_version_id=asset.selected_version_id,
        )
        _verify_scene_version_artifact(workspace, selected)


def inspect_episode_scene_asset_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
) -> SceneManifestInspection:
    number = normalize_episode_no(episode_no)
    try:
        manifest = _read_scene_manifest(workspace, episode_no=number)
    except FileNotFoundError:
        manifest = None
    except _ArtifactReadError as exc:
        return SceneManifestInspection("invalid", (exc.reason,))

    render = inspect_render_plan(workspace, episode_no=number)
    if render.state == "stale":
        if manifest is not None:
            return SceneManifestInspection("stale", ("render_plan_stale",), manifest)
        return SceneManifestInspection("blocked_source", ("render_plan_stale",))
    if render.state != "fresh" or render.plan is None:
        return SceneManifestInspection(
            "blocked_source",
            (f"render_plan_{render.state}",),
            manifest,
        )
    plan = render.plan
    try:
        catalog = _read_scene_catalog(workspace, season_no=plan.season_no)
    except FileNotFoundError:
        return SceneManifestInspection(
            "blocked_source",
            ("scene_catalog_missing",),
            manifest,
        )
    except _ArtifactReadError:
        return SceneManifestInspection(
            "blocked_source",
            ("scene_catalog_invalid",),
            manifest,
        )
    if manifest is None:
        return SceneManifestInspection("needs_scene_manifest", ("missing",))
    mapping = _scene_mapping_from_manifest(manifest)
    try:
        _validate_used_scene_artifacts(
            workspace,
            catalog=catalog,
            shot_scene_ids=mapping,
        )
        expected = build_episode_scene_asset_manifest(
            plan,
            catalog,
            shot_scene_ids=mapping,
            binding_revision=manifest.binding_revision,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError, RecursionError):
        return SceneManifestInspection("stale", ("scene_source_invalid",), manifest)

    reasons: list[str] = []
    if manifest.season_no != plan.season_no or manifest.episode_no != plan.episode_no:
        reasons.append("episode_identity_mismatch")
    if manifest.render_plan_fingerprint != expected.render_plan_fingerprint:
        reasons.append("render_plan_fingerprint_mismatch")
    if manifest.usage_fingerprint != expected.usage_fingerprint:
        reasons.append("scene_selection_mismatch")
    if manifest.manifest_fingerprint != expected.manifest_fingerprint:
        reasons.append("manifest_source_mismatch")
    if reasons:
        return SceneManifestInspection("stale", tuple(dict.fromkeys(reasons)), manifest)
    return SceneManifestInspection("fresh", (), manifest)


def _create_episode_scene_asset_manifest_impl(
    workspace: str,
    *,
    shot_scene_ids: Mapping[str, str] | None = None,
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_manifest_fingerprint: str | None = None,
) -> EpisodeSceneAssetManifest:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    if expected_manifest_fingerprint is not None and not isinstance(
        expected_manifest_fingerprint, str
    ):
        raise ValueError("expected manifest fingerprint must be a string")
    if shot_scene_ids is not None and not isinstance(shot_scene_ids, Mapping):
        raise ValueError("shot_scene_ids must be an explicit mapping")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-scene-manifest"):
        path = episode_scene_asset_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path, maximum=MAX_SCENE_MANIFEST_BYTES)
        inspection = inspect_episode_scene_asset_manifest(
            workspace,
            episode_no=number,
        )
        if inspection.state == "invalid":
            raise DramaAssetStoreError("invalid scene manifest must be repaired explicitly")
        if inspection.state == "blocked_source":
            raise DramaAssetStoreError("fresh RenderPlan and scene catalog are required")
        current = inspection.manifest
        if current is None:
            if expected_manifest_fingerprint is not None:
                raise DramaAssetStoreError("scene manifest CAS expected an existing manifest")
            if shot_scene_ids is None:
                raise DramaAssetStoreError("explicit shot scene bindings are required")
            mapping = dict(shot_scene_ids)
            revision = 0
        else:
            if (
                expected_manifest_fingerprint is not None
                and expected_manifest_fingerprint != current.manifest_fingerprint
            ):
                raise DramaAssetStoreError("scene manifest changed; refresh before replacing")
            existing_mapping = _scene_mapping_from_manifest(current)
            mapping = (
                existing_mapping
                if shot_scene_ids is None
                else dict(shot_scene_ids)
            )
            revision = current.binding_revision + (
                1 if mapping != existing_mapping else 0
            )

        plan = load_fresh_render_plan(workspace, episode_no=number)
        catalog = load_fresh_scene_asset_catalog(
            workspace,
            season_no=plan.season_no,
        )
        _validate_used_scene_artifacts(
            workspace,
            catalog=catalog,
            shot_scene_ids=mapping,
        )
        desired = build_episode_scene_asset_manifest(
            plan,
            catalog,
            shot_scene_ids=mapping,
            binding_revision=revision,
        )
        if current is not None and desired.manifest_fingerprint == current.manifest_fingerprint:
            return current
        if current is not None:
            if not replace_stale:
                raise DramaAssetStoreError("scene manifest replacement must be explicit")
            if expected_manifest_fingerprint != current.manifest_fingerprint:
                raise DramaAssetStoreError("scene manifest CAS is required for replacement")

        def precommit() -> None:
            final_plan = load_fresh_render_plan(workspace, episode_no=number)
            final_catalog = load_fresh_scene_asset_catalog(
                workspace,
                season_no=final_plan.season_no,
            )
            _validate_used_scene_artifacts(
                workspace,
                catalog=final_catalog,
                shot_scene_ids=mapping,
            )
            final = build_episode_scene_asset_manifest(
                final_plan,
                final_catalog,
                shot_scene_ids=mapping,
                binding_revision=revision,
            )
            if final.manifest_fingerprint != desired.manifest_fingerprint:
                raise DramaAssetStoreError("scene manifest sources changed concurrently")

        _write_scene_manifest(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_scene_manifest(workspace, episode_no=number)
        if persisted.manifest_fingerprint != desired.manifest_fingerprint:
            raise DramaAssetStoreError("persisted scene manifest failed verification")
        return persisted


def load_fresh_episode_scene_asset_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeSceneAssetManifest:
    inspection = inspect_episode_scene_asset_manifest(
        workspace,
        episode_no=episode_no,
    )
    if inspection.state != "fresh" or inspection.manifest is None:
        raise DramaAssetStoreError(
            f"episode scene manifest is not fresh: {inspection.state}"
        )
    return inspection.manifest


def _scene_public_mutation_error_message(
    exc: BaseException,
    *,
    operation: str,
) -> str:
    if isinstance(exc, DramaAssetStoreError):
        return str(exc)
    return f"scene asset {operation} was rejected"


def create_scene_asset_catalog(
    workspace: str,
    *,
    version: SceneAssetVersion | Dict[str, Any],
    season_no: int = 1,
) -> SceneAssetCatalog:
    try:
        return _create_scene_asset_catalog_impl(
            workspace,
            version=version,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        message = _scene_public_mutation_error_message(
            exc, operation="catalog creation"
        )
    raise DramaAssetStoreError(message)


def add_scene_asset(
    workspace: str,
    *,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    try:
        return _add_scene_asset_impl(
            workspace,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        message = _scene_public_mutation_error_message(exc, operation="scene addition")
    raise DramaAssetStoreError(message)


def append_scene_asset_version(
    workspace: str,
    *,
    scene_id: str,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    try:
        return _append_scene_asset_version_impl(
            workspace,
            scene_id=scene_id,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        message = _scene_public_mutation_error_message(
            exc, operation="candidate append"
        )
    raise DramaAssetStoreError(message)


def select_scene_asset_version(
    workspace: str,
    *,
    scene_id: str,
    scene_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int = 1,
) -> SceneAssetCatalog:
    try:
        return _select_scene_asset_version_impl(
            workspace,
            scene_id=scene_id,
            scene_version_id=scene_version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        message = _scene_public_mutation_error_message(exc, operation="selection")
    raise DramaAssetStoreError(message)


def create_episode_scene_asset_manifest(
    workspace: str,
    *,
    shot_scene_ids: Mapping[str, str] | None = None,
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_manifest_fingerprint: str | None = None,
) -> EpisodeSceneAssetManifest:
    try:
        return _create_episode_scene_asset_manifest_impl(
            workspace,
            shot_scene_ids=shot_scene_ids,
            episode_no=episode_no,
            replace_stale=replace_stale,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        message = _scene_public_mutation_error_message(
            exc, operation="manifest update"
        )
    raise DramaAssetStoreError(message)
