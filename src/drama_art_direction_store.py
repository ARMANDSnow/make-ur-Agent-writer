"""Strict local persistence for season-level ArtDirection catalogs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_assets import (
    append_art_direction_version,
    build_art_direction_catalog,
    build_art_direction_version,
    select_art_direction_version as select_art_direction_version_pure,
    selected_art_direction_ref,
)
from .drama_schemas import (
    ArtDirectionCatalog,
    ArtDirectionRef,
    ArtDirectionSpec,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_ART_DIRECTION_CATALOG_BYTES = 2_000_000

ArtDirectionCatalogState = Literal[
    "needs_art_direction_catalog",
    "fresh",
    "invalid",
]


class DramaArtDirectionStoreError(ValueError):
    pass


class _CatalogReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ArtDirectionCatalogInspection:
    state: ArtDirectionCatalogState
    reasons: tuple[str, ...]
    catalog: ArtDirectionCatalog | None = None


def _strict_season_no(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("season_no must be a strict positive integer")
    return value


def art_direction_catalog_path(workspace: str, *, season_no: int = 1) -> Path:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    return root / "data" / "assets" / f"season_{season:02d}.art_direction.json"


def _read_catalog(workspace: str, *, season_no: int) -> ArtDirectionCatalog:
    root = paths.workspace_root(workspace)
    path = art_direction_catalog_path(workspace, season_no=season_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_ART_DIRECTION_CATALOG_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _CatalogReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "catalog_fingerprint",
        "catalog",
    }:
        raise _CatalogReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _CatalogReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_art_direction_catalog":
        raise _CatalogReadError("schema_invalid")
    if not isinstance(raw["catalog"], dict):
        raise _CatalogReadError("schema_invalid")
    try:
        catalog = ArtDirectionCatalog(**raw["catalog"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _CatalogReadError("schema_invalid") from exc
    if raw["catalog_fingerprint"] != catalog.catalog_fingerprint:
        raise _CatalogReadError("catalog_hash_mismatch")
    if catalog.season_no != season_no:
        raise _CatalogReadError("schema_invalid")
    return catalog


def inspect_art_direction_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> ArtDirectionCatalogInspection:
    season = _strict_season_no(season_no)
    try:
        catalog = _read_catalog(workspace, season_no=season)
    except FileNotFoundError:
        return ArtDirectionCatalogInspection(
            "needs_art_direction_catalog",
            ("missing",),
        )
    except _CatalogReadError as exc:
        return ArtDirectionCatalogInspection("invalid", (exc.reason,))
    return ArtDirectionCatalogInspection("fresh", (), catalog)


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_ART_DIRECTION_CATALOG_BYTES,
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
            or info.st_size > MAX_ART_DIRECTION_CATALOG_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_ART_DIRECTION_CATALOG_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_ART_DIRECTION_CATALOG_BYTES:
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


def _write_catalog(
    workspace: str,
    catalog: ArtDirectionCatalog,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "drama_art_direction_catalog",
        "catalog_fingerprint": catalog.catalog_fingerprint,
        "catalog": model_to_dict(catalog),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_ART_DIRECTION_CATALOG_BYTES:
        raise DramaArtDirectionStoreError("art direction catalog exceeds its size limit")

    root = paths.workspace_root(workspace)
    path = art_direction_catalog_path(workspace, season_no=catalog.season_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaArtDirectionStoreError("art direction path escapes the workspace") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise DramaArtDirectionStoreError("art direction path is invalid")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaArtDirectionStoreError("strict no-follow writes are unavailable")
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
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaArtDirectionStoreError(
                "art direction catalog changed concurrently; retry from inspection"
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
                raise OSError("short art direction catalog write")
            view = view[written:]
        os.close(temp_fd)
        temp_fd = None
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaArtDirectionStoreError(
                "art direction catalog changed concurrently; retry from inspection"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except DramaArtDirectionStoreError:
        raise
    except OSError as exc:
        raise DramaArtDirectionStoreError(
            "art direction catalog could not be written safely"
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


def _raise_public_mutation_error(exc: BaseException, *, operation: str) -> None:
    if isinstance(exc, DramaArtDirectionStoreError):
        raise DramaArtDirectionStoreError(str(exc)) from None
    raise DramaArtDirectionStoreError(f"art direction {operation} was rejected") from None


def _create_art_direction_catalog_impl(
    workspace: str,
    *,
    art_direction_id: str,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    initial = build_art_direction_version(
        art_direction_id=art_direction_id,
        spec=spec,
        source_kind=source_kind,
    )
    desired = build_art_direction_catalog(initial, season_no=season)
    with use_workspace(workspace), acquire_write_lock(source="drama-art-direction"):
        path = art_direction_catalog_path(workspace, season_no=season)
        token = _target_token(root, path)
        inspection = inspect_art_direction_catalog(workspace, season_no=season)
        if inspection.state == "invalid":
            raise DramaArtDirectionStoreError(
                "invalid art direction catalog must be repaired explicitly"
            )
        if inspection.state == "fresh" and inspection.catalog is not None:
            if inspection.catalog == desired:
                return inspection.catalog
            raise DramaArtDirectionStoreError("art direction catalog already exists")
        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
        )
        persisted = _read_catalog(workspace, season_no=season)
        if persisted.catalog_fingerprint != desired.catalog_fingerprint:
            raise DramaArtDirectionStoreError(
                "persisted art direction catalog failed verification"
            )
        return persisted


def create_art_direction_catalog(
    workspace: str,
    *,
    art_direction_id: str,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    try:
        return _create_art_direction_catalog_impl(
            workspace,
            art_direction_id=art_direction_id,
            spec=spec,
            source_kind=source_kind,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _raise_public_mutation_error(exc, operation="catalog creation")


def load_fresh_art_direction_catalog(
    workspace: str,
    *,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    inspection = inspect_art_direction_catalog(workspace, season_no=season_no)
    if inspection.state != "fresh" or inspection.catalog is None:
        raise DramaArtDirectionStoreError(
            f"art direction catalog is not fresh: {inspection.state}"
        )
    return inspection.catalog


def _append_art_direction_candidate_impl(
    workspace: str,
    *,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    expected_catalog_fingerprint: str,
    derived_from: str | None = None,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-art-direction"):
        path = art_direction_catalog_path(workspace, season_no=season)
        token = _target_token(root, path)
        current = load_fresh_art_direction_catalog(workspace, season_no=season)
        candidate = build_art_direction_version(
            art_direction_id=current.art_direction_id,
            spec=spec,
            source_kind=source_kind,
            derived_from=derived_from,
        )
        desired = append_art_direction_version(
            current,
            version=candidate,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
        if desired == current:
            return current

        def precommit() -> None:
            final = _read_catalog(workspace, season_no=season)
            if final.catalog_fingerprint != current.catalog_fingerprint:
                raise DramaArtDirectionStoreError(
                    "art direction catalog changed concurrently"
                )

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_catalog(workspace, season_no=season)
        if persisted.catalog_fingerprint != desired.catalog_fingerprint:
            raise DramaArtDirectionStoreError(
                "persisted art direction catalog failed verification"
            )
        return persisted


def append_art_direction_candidate(
    workspace: str,
    *,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    expected_catalog_fingerprint: str,
    derived_from: str | None = None,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    try:
        return _append_art_direction_candidate_impl(
            workspace,
            spec=spec,
            source_kind=source_kind,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
            derived_from=derived_from,
            season_no=season_no,
        )
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ) as exc:
        _raise_public_mutation_error(exc, operation="candidate append")


def _select_art_direction_version_impl(
    workspace: str,
    *,
    version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-art-direction"):
        path = art_direction_catalog_path(workspace, season_no=season)
        token = _target_token(root, path)
        current = load_fresh_art_direction_catalog(workspace, season_no=season)
        desired = select_art_direction_version_pure(
            current,
            version_id=version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
        )
        if desired == current:
            return current
        from .drama_asset_usage import assert_asset_version_selectable

        assert_asset_version_selectable(
            workspace,
            kind="art_direction",
            asset_id=current.art_direction_id,
            version_id=version_id,
            season_no=season,
        )

        def precommit() -> None:
            final = _read_catalog(workspace, season_no=season)
            if final.catalog_fingerprint != current.catalog_fingerprint:
                raise DramaArtDirectionStoreError(
                    "art direction catalog changed concurrently"
                )
            assert_asset_version_selectable(
                workspace,
                kind="art_direction",
                asset_id=current.art_direction_id,
                version_id=version_id,
                season_no=season,
            )

        _write_catalog(
            workspace,
            desired,
            expected_target_token=token,
            precommit_check=precommit,
        )
        persisted = _read_catalog(workspace, season_no=season)
        if persisted.catalog_fingerprint != desired.catalog_fingerprint:
            raise DramaArtDirectionStoreError(
                "persisted art direction catalog failed verification"
            )
        return persisted


def select_art_direction_version(
    workspace: str,
    *,
    version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    try:
        return _select_art_direction_version_impl(
            workspace,
            version_id=version_id,
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
        _raise_public_mutation_error(exc, operation="selection")


def load_selected_art_direction_ref(
    workspace: str,
    *,
    season_no: int = 1,
) -> ArtDirectionRef:
    return selected_art_direction_ref(
        load_fresh_art_direction_catalog(workspace, season_no=season_no)
    )


def resolve_selected_art_direction_ref(
    workspace: str,
    *,
    season_no: int = 1,
) -> ArtDirectionRef | None:
    """Return None only for a genuinely missing optional legacy catalog."""

    inspection = inspect_art_direction_catalog(workspace, season_no=season_no)
    if inspection.state == "needs_art_direction_catalog":
        return None
    if inspection.state != "fresh" or inspection.catalog is None:
        raise DramaArtDirectionStoreError("art direction catalog is invalid")
    return selected_art_direction_ref(inspection.catalog)
