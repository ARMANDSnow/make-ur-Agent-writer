"""Workspace-local Global/Series/Episode ArtDirection resolution."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_art_direction_store import (
    _target_token,
    _target_token_at,
    art_direction_catalog_path,
    inspect_art_direction_catalog,
)
from .drama_assets import build_art_direction_version, selected_art_direction_ref
from .drama_schemas import (
    ArtDirectionCatalog,
    ArtDirectionRef,
    ArtDirectionResolution,
    ArtDirectionScope,
    ArtDirectionSpec,
    ArtDirectionVersion,
    ScopedArtDirectionCatalog,
    ScopedArtDirectionScope,
    _canonical_sha256,
    episode_paths,
    normalize_episode_no,
)
from .drama_store import (
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES = 2_000_000
ScopedCatalogState = Literal[
    "needs_scoped_art_direction_catalog",
    "fresh",
    "invalid",
]


class DramaArtDirectionScopeError(ValueError):
    pass


class _ScopedCatalogReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ScopedArtDirectionCatalogInspection:
    state: ScopedCatalogState
    reasons: tuple[str, ...]
    catalog: ScopedArtDirectionCatalog | None = None
    target_token: tuple[Any, ...] | None = None


def _strict_scope(value: Any) -> ScopedArtDirectionScope:
    if value not in ("global", "episode"):
        raise ValueError("scoped art direction scope must be global or episode")
    return value


def _scope_identity(
    scope: ScopedArtDirectionScope,
    *,
    season_no: int | None,
    episode_no: int | None,
) -> tuple[int | None, int | None]:
    validated = _strict_scope(scope)
    if validated == "global":
        if season_no is not None or episode_no is not None:
            raise ValueError("global art direction scope cannot bind an episode")
        return None, None
    if (
        not isinstance(season_no, int)
        or isinstance(season_no, bool)
        or season_no < 1
    ):
        raise ValueError("episode art direction season_no must be strict")
    return season_no, normalize_episode_no(episode_no)


def scoped_art_direction_catalog_path(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> Path:
    validated = _strict_scope(scope)
    season, episode = _scope_identity(
        validated,
        season_no=season_no,
        episode_no=episode_no,
    )
    root = paths.workspace_root(workspace)
    if validated == "global":
        return root / "data" / "assets" / "global.art_direction.json"
    ep = episode_paths(workspace, episode_no=episode or 1)
    if ep.root != root:
        raise ValueError("episode art direction path does not match workspace")
    return ep.episodes_dir / f"episode_{episode:02d}.art_direction.json"


def _resolution_source_tokens(
    workspace: str,
    *,
    season_no: int,
    episode_no: int,
) -> tuple[tuple[Any, ...], ...]:
    root = paths.workspace_root(workspace)
    source_paths = (
        scoped_art_direction_catalog_path(
            workspace,
            scope="episode",
            season_no=season_no,
            episode_no=episode_no,
        ),
        art_direction_catalog_path(workspace, season_no=season_no),
        scoped_art_direction_catalog_path(workspace, scope="global"),
    )
    return tuple(_target_token(root, path) for path in source_paths)


def _assert_scoped_version_selectable(
    workspace: str,
    *,
    catalog: ScopedArtDirectionCatalog,
    version_id: str,
) -> None:
    from .drama_asset_usage import (
        assert_asset_version_selectable,
        assert_asset_version_selectable_across_workspace,
    )

    if catalog.scope == "episode":
        if catalog.season_no is None:
            raise DramaArtDirectionScopeError(
                "episode art direction scope has no governance season"
            )
        assert_asset_version_selectable(
            workspace,
            kind="art_direction",
            asset_id=catalog.art_direction_id,
            version_id=version_id,
            season_no=catalog.season_no,
        )
        return
    assert_asset_version_selectable_across_workspace(
        workspace,
        kind="art_direction",
        asset_id=catalog.art_direction_id,
        version_id=version_id,
    )


def _catalog_payload(
    *,
    scope: ScopedArtDirectionScope,
    season_no: int | None,
    episode_no: int | None,
    art_direction_id: str,
    versions: list[ArtDirectionVersion],
    selected_version_id: str,
    selection_revision: int,
    enabled: bool,
    scope_revision: int,
) -> ScopedArtDirectionCatalog:
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "scope": scope,
        "season_no": season_no,
        "episode_no": episode_no,
        "art_direction_id": art_direction_id,
        "versions": [model_to_dict(item) for item in versions],
        "selected_version_id": selected_version_id,
        "selection_revision": selection_revision,
        "enabled": enabled,
        "scope_revision": scope_revision,
    }
    payload["catalog_fingerprint"] = _canonical_sha256(payload)
    return ScopedArtDirectionCatalog(**payload)


def build_scoped_art_direction_catalog(
    *,
    scope: ScopedArtDirectionScope,
    version: ArtDirectionVersion,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    validated_scope = _strict_scope(scope)
    season, episode = _scope_identity(
        validated_scope,
        season_no=season_no,
        episode_no=episode_no,
    )
    candidate = ArtDirectionVersion(**model_to_dict(version))
    return _catalog_payload(
        scope=validated_scope,
        season_no=season,
        episode_no=episode,
        art_direction_id=candidate.art_direction_id,
        versions=[candidate],
        selected_version_id=candidate.version_id,
        selection_revision=0,
        enabled=True,
        scope_revision=0,
    )


def _read_scoped_catalog(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    season_no: int | None,
    episode_no: int | None,
) -> ScopedArtDirectionCatalog:
    validated_scope = _strict_scope(scope)
    season, episode = _scope_identity(
        validated_scope,
        season_no=season_no,
        episode_no=episode_no,
    )
    root = paths.workspace_root(workspace)
    path = scoped_art_direction_catalog_path(
        workspace,
        scope=validated_scope,
        season_no=season,
        episode_no=episode,
    )
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _ScopedCatalogReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "catalog_fingerprint",
        "catalog",
    }:
        raise _ScopedCatalogReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ScopedCatalogReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_scoped_art_direction_catalog":
        raise _ScopedCatalogReadError("schema_invalid")
    if not isinstance(raw["catalog"], dict):
        raise _ScopedCatalogReadError("schema_invalid")
    try:
        catalog = ScopedArtDirectionCatalog(**raw["catalog"])
    except (TypeError, ValueError) as exc:
        raise _ScopedCatalogReadError("schema_invalid") from exc
    if (
        raw["catalog_fingerprint"] != catalog.catalog_fingerprint
        or catalog.scope != validated_scope
        or catalog.season_no != season
        or catalog.episode_no != episode
    ):
        raise _ScopedCatalogReadError("catalog_hash_mismatch")
    return catalog


def inspect_scoped_art_direction_catalog(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalogInspection:
    validated_scope = _strict_scope(scope)
    season, episode = _scope_identity(
        validated_scope,
        season_no=season_no,
        episode_no=episode_no,
    )
    root = paths.workspace_root(workspace)
    path = scoped_art_direction_catalog_path(
        workspace,
        scope=validated_scope,
        season_no=season,
        episode_no=episode,
    )
    token = _target_token(
        root,
        path,
    )
    if token == ("missing",):
        return ScopedArtDirectionCatalogInspection(
            "needs_scoped_art_direction_catalog",
            ("missing",),
            target_token=token,
        )
    if token == ("invalid",):
        return ScopedArtDirectionCatalogInspection(
            "invalid",
            ("schema_invalid",),
        )
    try:
        catalog = _read_scoped_catalog(
            workspace,
            scope=validated_scope,
            season_no=season,
            episode_no=episode,
        )
    except FileNotFoundError:
        return ScopedArtDirectionCatalogInspection(
            "invalid",
            ("changed_concurrently",),
        )
    except _ScopedCatalogReadError as exc:
        return ScopedArtDirectionCatalogInspection("invalid", (exc.reason,))
    final_token = _target_token(
        root,
        path,
    )
    if final_token != token:
        return ScopedArtDirectionCatalogInspection(
            "invalid",
            ("changed_concurrently",),
        )
    return ScopedArtDirectionCatalogInspection(
        "fresh",
        (),
        catalog,
        token,
    )


def load_fresh_scoped_art_direction_catalog(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    inspection = inspect_scoped_art_direction_catalog(
        workspace,
        scope=scope,
        season_no=season_no,
        episode_no=episode_no,
    )
    if inspection.state != "fresh" or inspection.catalog is None:
        raise DramaArtDirectionScopeError(
            f"scoped art direction catalog is not fresh: {inspection.state}"
        )
    return inspection.catalog


def _write_scoped_envelope(
    root: Path,
    path: Path,
    envelope: Dict[str, Any],
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    if (
        not payload
        or len(payload) > MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES
    ):
        raise DramaArtDirectionScopeError(
            "scoped art direction catalog exceeds its size limit"
        )
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaArtDirectionScopeError(
            "scoped art direction path escapes workspace"
        ) from exc
    if not relative.parts or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise DramaArtDirectionScopeError(
            "scoped art direction path is invalid"
        )
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaArtDirectionScopeError(
            "strict no-follow scoped writes are unavailable"
        )
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = (
        f".{relative.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    )
    try:
        directory_fd = os.open(
            str(root),
            os.O_RDONLY | directory | nofollow,
        )
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
            _target_token_at(directory_fd, relative.name)
            != expected_target_token
        ):
            raise DramaArtDirectionScopeError(
                "scoped art direction catalog changed concurrently"
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
                raise OSError("short scoped art direction write")
            view = view[written:]
        os.close(temp_fd)
        temp_fd = None
        if precommit_check is not None:
            precommit_check()
        if (
            _target_token_at(directory_fd, relative.name)
            != expected_target_token
        ):
            raise DramaArtDirectionScopeError(
                "scoped art direction catalog changed concurrently"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except DramaArtDirectionScopeError:
        raise
    except OSError as exc:
        raise DramaArtDirectionScopeError(
            "scoped art direction catalog could not be written safely"
        ) from exc
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


def _persist_catalog(
    workspace: str,
    catalog: ScopedArtDirectionCatalog,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check=None,
) -> ScopedArtDirectionCatalog:
    root = paths.workspace_root(workspace)
    path = scoped_art_direction_catalog_path(
        workspace,
        scope=catalog.scope,
        season_no=catalog.season_no,
        episode_no=catalog.episode_no,
    )
    _write_scoped_envelope(
        root,
        path,
        {
            "schema_version": 1,
            "artifact_type": "drama_scoped_art_direction_catalog",
            "catalog_fingerprint": catalog.catalog_fingerprint,
            "catalog": model_to_dict(catalog),
        },
        expected_target_token=expected_target_token,
        precommit_check=precommit_check,
    )
    persisted = _read_scoped_catalog(
        workspace,
        scope=catalog.scope,
        season_no=catalog.season_no,
        episode_no=catalog.episode_no,
    )
    if persisted != catalog:
        raise DramaArtDirectionScopeError(
            "persisted scoped art direction catalog failed verification"
        )
    return persisted


def _public_error(exc: BaseException, operation: str) -> None:
    if isinstance(exc, DramaArtDirectionScopeError):
        raise DramaArtDirectionScopeError(str(exc)) from None
    raise DramaArtDirectionScopeError(
        f"scoped art direction {operation} was rejected"
    ) from None


def create_scoped_art_direction_catalog(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    art_direction_id: str,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    try:
        validated_scope = _strict_scope(scope)
        season, episode = _scope_identity(
            validated_scope,
            season_no=season_no,
            episode_no=episode_no,
        )
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        version = build_art_direction_version(
            art_direction_id=art_direction_id,
            spec=spec,
            source_kind=source_kind,
        )
        desired = build_scoped_art_direction_catalog(
            scope=validated_scope,
            version=version,
            season_no=season,
            episode_no=episode,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-art-direction-scope"
        ):
            inspection = inspect_scoped_art_direction_catalog(
                workspace,
                scope=validated_scope,
                season_no=season,
                episode_no=episode,
            )
            if inspection.state == "invalid":
                raise DramaArtDirectionScopeError(
                    "invalid scoped catalog must be repaired explicitly"
                )
            if inspection.catalog is not None:
                if inspection.catalog == desired:
                    return inspection.catalog
                raise DramaArtDirectionScopeError(
                    "scoped art direction catalog already exists"
                )
            if inspection.target_token is None:
                raise DramaArtDirectionScopeError(
                    "scoped catalog target token is unavailable"
                )
            _assert_scoped_version_selectable(
                workspace,
                catalog=desired,
                version_id=desired.selected_version_id,
            )

            def precommit() -> None:
                _assert_scoped_version_selectable(
                    workspace,
                    catalog=desired,
                    version_id=desired.selected_version_id,
                )

            return _persist_catalog(
                workspace,
                desired,
                expected_target_token=inspection.target_token,
                precommit_check=precommit,
            )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _public_error(exc, "catalog creation")


def append_scoped_art_direction_candidate(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    expected_catalog_fingerprint: str,
    derived_from: str | None = None,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    try:
        validated_scope = _strict_scope(scope)
        season, episode = _scope_identity(
            validated_scope,
            season_no=season_no,
            episode_no=episode_no,
        )
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        with use_workspace(workspace), acquire_write_lock(
            source="drama-art-direction-scope"
        ):
            inspection = inspect_scoped_art_direction_catalog(
                workspace,
                scope=validated_scope,
                season_no=season,
                episode_no=episode,
            )
            if inspection.catalog is None or inspection.target_token is None:
                raise DramaArtDirectionScopeError(
                    "fresh scoped art direction catalog is required"
                )
            current = inspection.catalog
            if expected_catalog_fingerprint != current.catalog_fingerprint:
                raise DramaArtDirectionScopeError(
                    "scoped art direction catalog changed"
                )
            candidate = build_art_direction_version(
                art_direction_id=current.art_direction_id,
                spec=spec,
                source_kind=source_kind,
                derived_from=derived_from,
            )
            by_id = {item.version_id: item for item in current.versions}
            if candidate.version_id in by_id:
                if by_id[candidate.version_id] != candidate:
                    raise DramaArtDirectionScopeError(
                        "scoped content-addressed version conflicts"
                    )
                return current
            if (
                candidate.derived_from is not None
                and candidate.derived_from not in by_id
            ):
                raise DramaArtDirectionScopeError(
                    "scoped derived art direction version does not exist"
                )
            desired = _catalog_payload(
                scope=current.scope,
                season_no=current.season_no,
                episode_no=current.episode_no,
                art_direction_id=current.art_direction_id,
                versions=[*current.versions, candidate],
                selected_version_id=current.selected_version_id,
                selection_revision=current.selection_revision,
                enabled=current.enabled,
                scope_revision=current.scope_revision,
            )

            def precommit() -> None:
                if _read_scoped_catalog(
                    workspace,
                    scope=current.scope,
                    season_no=current.season_no,
                    episode_no=current.episode_no,
                ) != current:
                    raise DramaArtDirectionScopeError(
                        "scoped art direction catalog changed concurrently"
                    )
            return _persist_catalog(
                workspace,
                desired,
                expected_target_token=inspection.target_token,
                precommit_check=precommit,
            )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _public_error(exc, "candidate append")


def _strict_revision(value: Any, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > 2_147_483_647
    ):
        raise ValueError(f"{field} must be a strict revision")
    return value


def select_scoped_art_direction_version(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    try:
        expected_revision = _strict_revision(
            expected_selection_revision,
            "expected selection revision",
        )
        validated_scope = _strict_scope(scope)
        season, episode = _scope_identity(
            validated_scope,
            season_no=season_no,
            episode_no=episode_no,
        )
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        with use_workspace(workspace), acquire_write_lock(
            source="drama-art-direction-scope"
        ):
            inspection = inspect_scoped_art_direction_catalog(
                workspace,
                scope=validated_scope,
                season_no=season,
                episode_no=episode,
            )
            if inspection.catalog is None or inspection.target_token is None:
                raise DramaArtDirectionScopeError(
                    "fresh scoped art direction catalog is required"
                )
            current = inspection.catalog
            if (
                current.selection_revision != expected_revision
                or current.selected_version_id
                != expected_selected_version_id
            ):
                raise DramaArtDirectionScopeError(
                    "scoped art direction selection changed"
                )
            if version_id not in {
                item.version_id for item in current.versions
            }:
                raise DramaArtDirectionScopeError(
                    "scoped art direction version does not exist"
                )
            if version_id == current.selected_version_id:
                return current
            _assert_scoped_version_selectable(
                workspace,
                catalog=current,
                version_id=version_id,
            )
            desired = _catalog_payload(
                scope=current.scope,
                season_no=current.season_no,
                episode_no=current.episode_no,
                art_direction_id=current.art_direction_id,
                versions=current.versions,
                selected_version_id=version_id,
                selection_revision=current.selection_revision + 1,
                enabled=current.enabled,
                scope_revision=current.scope_revision,
            )

            def precommit() -> None:
                if _read_scoped_catalog(
                    workspace,
                    scope=current.scope,
                    season_no=current.season_no,
                    episode_no=current.episode_no,
                ) != current:
                    raise DramaArtDirectionScopeError(
                        "scoped art direction catalog changed concurrently"
                    )
                _assert_scoped_version_selectable(
                    workspace,
                    catalog=current,
                    version_id=version_id,
                )

            return _persist_catalog(
                workspace,
                desired,
                expected_target_token=inspection.target_token,
                precommit_check=precommit,
            )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _public_error(exc, "selection")


def set_scoped_art_direction_enabled(
    workspace: str,
    *,
    scope: ScopedArtDirectionScope,
    enabled: bool,
    expected_scope_revision: int,
    expected_enabled: bool,
    season_no: int | None = None,
    episode_no: int | None = None,
) -> ScopedArtDirectionCatalog:
    try:
        if type(enabled) is not bool or type(expected_enabled) is not bool:
            raise ValueError("scoped art direction enabled flags must be bool")
        expected_revision = _strict_revision(
            expected_scope_revision,
            "expected scope revision",
        )
        validated_scope = _strict_scope(scope)
        season, episode = _scope_identity(
            validated_scope,
            season_no=season_no,
            episode_no=episode_no,
        )
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        with use_workspace(workspace), acquire_write_lock(
            source="drama-art-direction-scope"
        ):
            inspection = inspect_scoped_art_direction_catalog(
                workspace,
                scope=validated_scope,
                season_no=season,
                episode_no=episode,
            )
            if inspection.catalog is None or inspection.target_token is None:
                raise DramaArtDirectionScopeError(
                    "fresh scoped art direction catalog is required"
                )
            current = inspection.catalog
            if (
                current.scope_revision != expected_revision
                or current.enabled is not expected_enabled
            ):
                raise DramaArtDirectionScopeError(
                    "scoped art direction activation changed"
                )
            if current.enabled is enabled:
                return current
            if current.scope_revision >= 2_147_483_647:
                raise DramaArtDirectionScopeError(
                    "scoped art direction revision exhausted"
                )
            if enabled:
                _assert_scoped_version_selectable(
                    workspace,
                    catalog=current,
                    version_id=current.selected_version_id,
                )
            desired = _catalog_payload(
                scope=current.scope,
                season_no=current.season_no,
                episode_no=current.episode_no,
                art_direction_id=current.art_direction_id,
                versions=current.versions,
                selected_version_id=current.selected_version_id,
                selection_revision=current.selection_revision,
                enabled=enabled,
                scope_revision=current.scope_revision + 1,
            )

            def precommit() -> None:
                if _read_scoped_catalog(
                    workspace,
                    scope=current.scope,
                    season_no=current.season_no,
                    episode_no=current.episode_no,
                ) != current:
                    raise DramaArtDirectionScopeError(
                        "scoped art direction catalog changed concurrently"
                    )
                if enabled:
                    _assert_scoped_version_selectable(
                        workspace,
                        catalog=current,
                        version_id=current.selected_version_id,
                    )

            return _persist_catalog(
                workspace,
                desired,
                expected_target_token=inspection.target_token,
                precommit_check=precommit,
            )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _public_error(exc, "activation")


def _scoped_selected_ref(catalog: ScopedArtDirectionCatalog) -> ArtDirectionRef:
    selected = next(
        item
        for item in catalog.versions
        if item.version_id == catalog.selected_version_id
    )
    return ArtDirectionRef(
        art_direction_id=catalog.art_direction_id,
        version_id=selected.version_id,
        fingerprint=selected.version_fingerprint,
    )


def _resolution(
    *,
    scope: ArtDirectionScope,
    season_no: int,
    episode_no: int,
    ref: ArtDirectionRef,
    source_selection_revision: int,
    source_scope_revision: int | None,
) -> ArtDirectionResolution:
    selection_payload: Dict[str, Any] = {
        "scope": scope,
        "season_no": (
            season_no if scope in ("series", "episode") else None
        ),
        "episode_no": episode_no if scope == "episode" else None,
        "ref": model_to_dict(ref),
        "selection_revision": source_selection_revision,
        "scope_revision": source_scope_revision,
    }
    payload: Dict[str, Any] = {
        "scope": scope,
        "season_no": season_no,
        "episode_no": episode_no,
        "ref": model_to_dict(ref),
        "source_selection_revision": source_selection_revision,
        "source_scope_revision": source_scope_revision,
        "source_selection_fingerprint": _canonical_sha256(
            selection_payload
        ),
    }
    payload["resolution_fingerprint"] = _canonical_sha256(payload)
    return ArtDirectionResolution(**payload)


def resolve_art_direction(
    workspace: str,
    *,
    season_no: int = 1,
    episode_no: int = 1,
) -> ArtDirectionResolution | None:
    """Resolve Episode > Series > workspace-Global without unsafe fallback."""

    if (
        not isinstance(season_no, int)
        or isinstance(season_no, bool)
        or season_no < 1
    ):
        raise ValueError("art direction resolution season_no must be strict")
    episode = normalize_episode_no(episode_no)
    initial_tokens = _resolution_source_tokens(
        workspace,
        season_no=season_no,
        episode_no=episode,
    )
    candidates: list[
        tuple[
            ArtDirectionScope,
            ScopedArtDirectionCatalogInspection
            | Any,
        ]
    ] = [
        (
            "episode",
            inspect_scoped_art_direction_catalog(
                workspace,
                scope="episode",
                season_no=season_no,
                episode_no=episode,
            ),
        ),
        (
            "series",
            inspect_art_direction_catalog(
                workspace,
                season_no=season_no,
            ),
        ),
        (
            "global",
            inspect_scoped_art_direction_catalog(
                workspace,
                scope="global",
            ),
        ),
    ]
    resolved: ArtDirectionResolution | None = None
    for scope, inspection in candidates:
        if inspection.state in (
            "needs_scoped_art_direction_catalog",
            "needs_art_direction_catalog",
        ):
            continue
        if inspection.state != "fresh" or inspection.catalog is None:
            raise DramaArtDirectionScopeError(
                f"{scope} art direction source is invalid"
            )
        catalog = inspection.catalog
        if isinstance(catalog, ScopedArtDirectionCatalog):
            if not catalog.enabled:
                continue
            ref = _scoped_selected_ref(catalog)
            selection_revision = catalog.selection_revision
            scope_revision: int | None = catalog.scope_revision
        else:
            validated = ArtDirectionCatalog(**model_to_dict(catalog))
            ref = selected_art_direction_ref(validated)
            selection_revision = validated.selection_revision
            scope_revision = None
        resolved = _resolution(
            scope=scope,
            season_no=season_no,
            episode_no=episode,
            ref=ref,
            source_selection_revision=selection_revision,
            source_scope_revision=scope_revision,
        )
        break
    if _resolution_source_tokens(
        workspace,
        season_no=season_no,
        episode_no=episode,
    ) != initial_tokens:
        raise DramaArtDirectionScopeError(
            "art direction sources changed concurrently"
        )
    return resolved
