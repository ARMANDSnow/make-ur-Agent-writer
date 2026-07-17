"""Cross-episode asset usage and non-destructive retirement governance."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_art_direction_store import (
    MAX_ART_DIRECTION_CATALOG_BYTES,
    _read_catalog as _read_art_direction_catalog,
    art_direction_catalog_path,
)
from .drama_art_direction_scope import (
    MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES,
    _read_scoped_catalog,
    scoped_art_direction_catalog_path,
)
from .drama_asset_versions import (
    MAX_ASSET_CATALOG_BYTES,
    MAX_ASSET_MANIFEST_BYTES,
    MAX_PROP_CLUE_CATALOG_BYTES,
    MAX_PROP_CLUE_MANIFEST_BYTES,
    MAX_SCENE_CATALOG_BYTES,
    MAX_SCENE_MANIFEST_BYTES,
    _read_catalog as _read_character_catalog,
    _read_manifest as _read_character_manifest,
    _read_prop_clue_catalog,
    _read_prop_clue_manifest,
    _read_scene_catalog,
    _read_scene_manifest,
    _target_token,
    _write_envelope,
    character_asset_catalog_path,
    episode_asset_manifest_path,
    episode_prop_or_clue_asset_manifest_path,
    episode_scene_asset_manifest_path,
    prop_or_clue_asset_catalog_path,
    scene_asset_catalog_path,
)
from .drama_render_store import (
    MAX_RENDER_PLAN_BYTES,
    _read_render_plan,
    render_plan_path,
)
from .drama_schemas import (
    AssetRetirementDecision,
    AssetRetirementEntry,
    AssetRetirementState,
    AssetRetirementStatus,
    AssetUsageBlocker,
    AssetUsageKind,
    AssetUsageReference,
    AssetUsageSourceKind,
    AssetUsageSourceSnapshot,
    AssetVersionUsage,
    SeasonAssetUsageIndex,
    _canonical_sha256,
    _validate_asset_usage_identity,
    episode_paths,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_ASSET_RETIREMENT_STATE_BYTES = 2_000_000
MAX_USAGE_SCAN_ENTRIES = 2048
MAX_USAGE_VERSIONS = 4096
_EPISODE_FILE_RE = re.compile(
    r"^episode_([0-9]{2,3})\."
    r"(render_plan|art_direction|asset_manifest|scene_asset_manifest|"
    r"prop_clue_asset_manifest)\.json$"
)
_CANONICAL_EPISODE_FILE_RE = re.compile(r"^episode_([0-9]{2,3})\.json$")

AssetRetirementInspectionState = Literal[
    "needs_asset_retirement_state",
    "fresh",
    "invalid",
]


class DramaAssetUsageError(ValueError):
    pass


class _RetirementReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AssetRetirementInspection:
    state: AssetRetirementInspectionState
    reasons: tuple[str, ...]
    value: AssetRetirementState | None = None
    target_token: tuple[Any, ...] | None = None


def _strict_season_no(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("season_no must be a strict positive integer")
    return value


def asset_retirement_state_path(
    workspace: str,
    *,
    season_no: int = 1,
) -> Path:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    return (
        root
        / "data"
        / "assets"
        / f"season_{season:02d}.asset_retirement.json"
    )


def build_asset_retirement_state(
    *,
    season_no: int,
    revision: int = 0,
    entries: list[AssetRetirementEntry] | None = None,
) -> AssetRetirementState:
    season = _strict_season_no(season_no)
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
        or revision > 2_147_483_647
    ):
        raise ValueError("asset retirement revision must be a strict integer")
    if entries is not None and not isinstance(entries, list):
        raise TypeError("asset retirement entries must be a list")
    validated = [
        AssetRetirementEntry(**model_to_dict(item))
        for item in (entries or [])
    ]
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": season,
        "revision": revision,
        "entries": [
            model_to_dict(item)
            for item in sorted(
                validated,
                key=lambda row: (row.kind, row.asset_id, row.version_id),
            )
        ],
    }
    payload["state_fingerprint"] = _canonical_sha256(payload)
    return AssetRetirementState(**payload)


def _read_retirement_state(
    workspace: str,
    *,
    season_no: int,
) -> AssetRetirementState:
    root = paths.workspace_root(workspace)
    path = asset_retirement_state_path(workspace, season_no=season_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_ASSET_RETIREMENT_STATE_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise _RetirementReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "state_fingerprint",
        "state",
    }:
        raise _RetirementReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _RetirementReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_asset_retirement":
        raise _RetirementReadError("schema_invalid")
    if not isinstance(raw["state"], dict):
        raise _RetirementReadError("schema_invalid")
    try:
        state = AssetRetirementState(**raw["state"])
    except (TypeError, ValueError) as exc:
        raise _RetirementReadError("schema_invalid") from exc
    if (
        raw["state_fingerprint"] != state.state_fingerprint
        or state.season_no != season_no
    ):
        raise _RetirementReadError("state_hash_mismatch")
    return state


def inspect_asset_retirement_state(
    workspace: str,
    *,
    season_no: int = 1,
) -> AssetRetirementInspection:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    path = asset_retirement_state_path(workspace, season_no=season)
    token = _target_token(
        root,
        path,
        maximum=MAX_ASSET_RETIREMENT_STATE_BYTES,
    )
    if token == ("missing",):
        return AssetRetirementInspection(
            "needs_asset_retirement_state",
            ("missing",),
            target_token=token,
        )
    if token == ("invalid",):
        return AssetRetirementInspection("invalid", ("schema_invalid",))
    try:
        state = _read_retirement_state(workspace, season_no=season)
    except FileNotFoundError:
        return AssetRetirementInspection("invalid", ("changed_concurrently",))
    except _RetirementReadError as exc:
        return AssetRetirementInspection("invalid", (exc.reason,))
    final_token = _target_token(
        root,
        path,
        maximum=MAX_ASSET_RETIREMENT_STATE_BYTES,
    )
    if final_token != token:
        return AssetRetirementInspection("invalid", ("changed_concurrently",))
    return AssetRetirementInspection("fresh", (), state, token)


def load_asset_retirement_state(
    workspace: str,
    *,
    season_no: int = 1,
) -> AssetRetirementState:
    season = _strict_season_no(season_no)
    inspection = inspect_asset_retirement_state(
        workspace,
        season_no=season,
    )
    if inspection.state == "needs_asset_retirement_state":
        return build_asset_retirement_state(season_no=season)
    if inspection.state != "fresh" or inspection.value is None:
        raise DramaAssetUsageError("asset retirement state is invalid")
    return inspection.value


def asset_version_status(
    state: AssetRetirementState,
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
) -> AssetRetirementStatus:
    validated = AssetRetirementState(**model_to_dict(state))
    _validate_asset_usage_identity(
        kind=kind,
        asset_id=asset_id,
        version_id=version_id,
    )
    entry = next(
        (
            item
            for item in validated.entries
            if (
                item.kind == kind
                and item.asset_id == asset_id
                and item.version_id == version_id
            )
        ),
        None,
    )
    return entry.status if entry is not None else "active"


def assert_asset_version_selectable(
    workspace: str,
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
    season_no: int = 1,
) -> None:
    state = load_asset_retirement_state(workspace, season_no=season_no)
    if (
        asset_version_status(
            state,
            kind=kind,
            asset_id=asset_id,
            version_id=version_id,
        )
        == "disabled"
    ):
        raise DramaAssetUsageError("disabled asset version cannot be selected")


def _workspace_retirement_season_nos(workspace: str) -> tuple[int, ...]:
    """List canonical retirement ledgers without following workspace symlinks."""

    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaAssetUsageError(
            "strict no-follow retirement inspection is unavailable"
        )
    opened: list[int] = []
    try:
        current_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        opened.append(current_fd)
        for part in ("data", "assets"):
            try:
                current_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                return (1,)
            opened.append(current_fd)
        names = os.listdir(current_fd)
    except OSError as exc:
        raise DramaAssetUsageError(
            "retirement ledger namespace is invalid"
        ) from exc
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass
    if len(names) > MAX_USAGE_SCAN_ENTRIES:
        raise DramaAssetUsageError("retirement ledger namespace is too large")
    seasons = {1}
    for name in names:
        if not (
            name.startswith("season_")
            and name.endswith(".asset_retirement.json")
        ):
            continue
        match = re.fullmatch(
            r"season_([0-9]+)\.asset_retirement\.json",
            name,
        )
        if match is None:
            raise DramaAssetUsageError("retirement ledger name is invalid")
        season = int(match.group(1))
        if season < 1 or name != (
            f"season_{season:02d}.asset_retirement.json"
        ):
            raise DramaAssetUsageError("retirement ledger name is invalid")
        seasons.add(season)
    return tuple(sorted(seasons))


def list_asset_governance_season_nos(workspace: str) -> tuple[int, ...]:
    """Public bounded view of seasons participating in global governance."""

    return _workspace_retirement_season_nos(workspace)


def assert_asset_version_selectable_across_workspace(
    workspace: str,
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
) -> None:
    """Guard a workspace-global selection against every known season ledger."""

    for season_no in _workspace_retirement_season_nos(workspace):
        assert_asset_version_selectable(
            workspace,
            kind=kind,
            asset_id=asset_id,
            version_id=version_id,
            season_no=season_no,
        )


def _snapshot_token(
    root: Path,
    path: Path,
    *,
    maximum: int,
) -> tuple[Any, ...]:
    return _target_token(root, path, maximum=maximum)


def _read_snapshot(
    *,
    root: Path,
    path: Path,
    maximum: int,
    reader: Callable[[], Any],
) -> tuple[Any | None, str | None, str | None]:
    before = _snapshot_token(root, path, maximum=maximum)
    if before == ("missing",):
        return None, None, None
    if before == ("invalid",):
        return None, None, "source_invalid"
    try:
        value = reader()
    except FileNotFoundError:
        return None, None, "source_changed"
    except (OSError, TypeError, ValueError, RecursionError):
        return None, None, "source_invalid"
    after = _snapshot_token(root, path, maximum=maximum)
    if after != before:
        return None, None, "source_changed"
    return value, str(before[2]), None


def _add_blocker(
    blockers: set[tuple[str, int | None, str]],
    *,
    source: AssetUsageSourceKind,
    code: str,
    episode_no: int | None = None,
) -> None:
    if len(blockers) < 512:
        blockers.add((source, episode_no, code))


def _episode_directory_snapshot(
    root: Path,
) -> tuple[str, tuple[int, int, tuple[str, ...]] | None]:
    """Pin the root-relative outputs/episodes namespace without symlink hops."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        return "invalid", None
    opened: list[int] = []
    try:
        current_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        opened.append(current_fd)
        for component in ("outputs", "episodes"):
            current_fd = os.open(
                component,
                os.O_RDONLY | directory | nofollow,
                dir_fd=current_fd,
            )
            opened.append(current_fd)
        pinned = os.fstat(current_fd)
        names = tuple(sorted(os.listdir(current_fd)))
        return "present", (pinned.st_dev, pinned.st_ino, names)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "invalid", None
    finally:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _episode_source_names(
    workspace: str,
) -> tuple[list[str], Callable[[], bool], bool]:
    root = paths.workspace_root(workspace)
    initial = _episode_directory_snapshot(root)
    if initial[0] == "invalid":
        return [], lambda: False, False
    names = list(initial[1][2]) if initial[1] is not None else []

    def unchanged() -> bool:
        return _episode_directory_snapshot(root) == initial

    return names, unchanged, len(names) > MAX_USAGE_SCAN_ENTRIES


def build_season_asset_usage_index(
    workspace: str,
    *,
    season_no: int = 1,
) -> SeasonAssetUsageIndex:
    season = _strict_season_no(season_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    inventory: Dict[tuple[str, str, str], str] = {}
    usage: Dict[tuple[str, str, str], Dict[int, set[str]]] = {}
    source_rows: set[tuple[str, int | None, str]] = set()
    blocker_rows: set[tuple[str, int | None, str]] = set()

    def source_snapshot(
        source: AssetUsageSourceKind,
        sha256: str,
        episode_no: int | None = None,
    ) -> None:
        source_rows.add((source, episode_no, sha256))

    def add_inventory(
        kind: AssetUsageKind,
        asset_id: str,
        version_id: str,
        fingerprint: str,
    ) -> None:
        key = (kind, asset_id, version_id)
        existing = inventory.get(key)
        if existing is not None:
            if existing != fingerprint:
                _add_blocker(
                    blocker_rows,
                    source="episode_scan",
                    code="version_identity_conflict",
                )
            return
        if len(inventory) >= MAX_USAGE_VERSIONS:
            _add_blocker(
                blocker_rows,
                source="episode_scan",
                code="version_capacity_exceeded",
            )
            return
        inventory[key] = fingerprint

    catalog_specs = [
        (
            "character_catalog",
            character_asset_catalog_path(workspace, season_no=season),
            MAX_ASSET_CATALOG_BYTES,
            lambda: _read_character_catalog(workspace, season_no=season),
        ),
        (
            "art_direction_catalog",
            art_direction_catalog_path(workspace, season_no=season),
            MAX_ART_DIRECTION_CATALOG_BYTES,
            lambda: _read_art_direction_catalog(workspace, season_no=season),
        ),
        (
            "art_direction_global_catalog",
            scoped_art_direction_catalog_path(
                workspace,
                scope="global",
            ),
            MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES,
            lambda: _read_scoped_catalog(
                workspace,
                scope="global",
                season_no=None,
                episode_no=None,
            ),
        ),
        (
            "scene_catalog",
            scene_asset_catalog_path(workspace, season_no=season),
            MAX_SCENE_CATALOG_BYTES,
            lambda: _read_scene_catalog(workspace, season_no=season),
        ),
        (
            "prop_clue_catalog",
            prop_or_clue_asset_catalog_path(workspace, season_no=season),
            MAX_PROP_CLUE_CATALOG_BYTES,
            lambda: _read_prop_clue_catalog(workspace, season_no=season),
        ),
    ]
    catalogs: Dict[str, Any] = {}
    for source, path, maximum, reader in catalog_specs:
        value, sha256, error = _read_snapshot(
            root=root,
            path=path,
            maximum=maximum,
            reader=reader,
        )
        if error is not None:
            _add_blocker(blocker_rows, source=source, code=error)
            continue
        if value is None or sha256 is None:
            continue
        catalogs[source] = value
        source_snapshot(source, sha256)

    character_catalog = catalogs.get("character_catalog")
    if character_catalog is not None:
        for asset in character_catalog.assets:
            for version in asset.versions:
                add_inventory(
                    "character",
                    asset.asset_id,
                    version.asset_version_id,
                    version.version_fingerprint,
                )
    art_catalog = catalogs.get("art_direction_catalog")
    if art_catalog is not None:
        for version in art_catalog.versions:
            add_inventory(
                "art_direction",
                art_catalog.art_direction_id,
                version.version_id,
                version.version_fingerprint,
            )
    global_art_catalog = catalogs.get("art_direction_global_catalog")
    if global_art_catalog is not None:
        for version in global_art_catalog.versions:
            add_inventory(
                "art_direction",
                global_art_catalog.art_direction_id,
                version.version_id,
                version.version_fingerprint,
            )
    scene_catalog = catalogs.get("scene_catalog")
    if scene_catalog is not None:
        for asset in scene_catalog.assets:
            for version in asset.versions:
                add_inventory(
                    "scene",
                    asset.scene_id,
                    version.scene_version_id,
                    version.version_fingerprint,
                )
    prop_catalog = catalogs.get("prop_clue_catalog")
    if prop_catalog is not None:
        for asset in prop_catalog.assets:
            for version in asset.versions:
                add_inventory(
                    asset.kind,
                    asset.asset_id,
                    version.asset_version_id,
                    version.version_fingerprint,
                )

    names, directory_unchanged, too_many_names = _episode_source_names(workspace)
    if too_many_names:
        _add_blocker(
            blocker_rows,
            source="episode_scan",
            code="entry_capacity_exceeded",
        )
        names = names[:MAX_USAGE_SCAN_ENTRIES]
    episode_sources: Dict[int, set[str]] = {}
    for name in names:
        canonical_match = _CANONICAL_EPISODE_FILE_RE.fullmatch(name)
        if canonical_match is not None:
            episode_no = int(canonical_match.group(1))
            if (
                1 <= episode_no <= 100
                and name == f"episode_{episode_no:02d}.json"
            ):
                episode_sources.setdefault(episode_no, set())
            else:
                _add_blocker(
                    blocker_rows,
                    source="episode_scan",
                    code="noncanonical_episode_name",
                )
            continue
        match = _EPISODE_FILE_RE.fullmatch(name)
        if match is None:
            if name.startswith("episode_") and any(
                name.endswith(f".{suffix}.json")
                for suffix in (
                    "render_plan",
                    "art_direction",
                    "asset_manifest",
                    "scene_asset_manifest",
                    "prop_clue_asset_manifest",
                )
            ):
                _add_blocker(
                    blocker_rows,
                    source="episode_scan",
                    code="noncanonical_episode_name",
                )
            continue
        episode_no = int(match.group(1))
        if (
            episode_no < 1
            or episode_no > 100
            or name
            != f"episode_{episode_no:02d}.{match.group(2)}.json"
        ):
            _add_blocker(
                blocker_rows,
                source="episode_scan",
                code="noncanonical_episode_name",
            )
            continue
        episode_sources.setdefault(episode_no, set()).add(match.group(2))

    expected_sources = {
        "render_plan",
        "asset_manifest",
        "scene_asset_manifest",
        "prop_clue_asset_manifest",
    }
    missing_source_names = {
        "render_plan": "render_plan",
        "asset_manifest": "character_manifest",
        "scene_asset_manifest": "scene_manifest",
        "prop_clue_asset_manifest": "prop_clue_manifest",
    }
    for episode_no, present_sources in sorted(episode_sources.items()):
        for missing in sorted(expected_sources - present_sources):
            _add_blocker(
                blocker_rows,
                source=missing_source_names[missing],
                episode_no=episode_no,
                code="source_missing",
            )

    reader_specs = {
        "render_plan": (
            "render_plan",
            MAX_RENDER_PLAN_BYTES,
            render_plan_path,
            _read_render_plan,
        ),
        "art_direction": (
            "art_direction_episode_catalog",
            MAX_SCOPED_ART_DIRECTION_CATALOG_BYTES,
            lambda workspace, episode_no: scoped_art_direction_catalog_path(
                workspace,
                scope="episode",
                season_no=season,
                episode_no=episode_no,
            ),
            lambda workspace, episode_no: _read_scoped_catalog(
                workspace,
                scope="episode",
                season_no=season,
                episode_no=episode_no,
            ),
        ),
        "asset_manifest": (
            "character_manifest",
            MAX_ASSET_MANIFEST_BYTES,
            episode_asset_manifest_path,
            _read_character_manifest,
        ),
        "scene_asset_manifest": (
            "scene_manifest",
            MAX_SCENE_MANIFEST_BYTES,
            episode_scene_asset_manifest_path,
            _read_scene_manifest,
        ),
        "prop_clue_asset_manifest": (
            "prop_clue_manifest",
            MAX_PROP_CLUE_MANIFEST_BYTES,
            episode_prop_or_clue_asset_manifest_path,
            _read_prop_clue_manifest,
        ),
    }
    scanned_episodes: list[int] = []
    for episode_no in sorted(episode_sources):
        scanned_episodes.append(episode_no)
        for file_kind in sorted(episode_sources[episode_no]):
            source, maximum, path_builder, reader = reader_specs[file_kind]
            path = path_builder(workspace, episode_no=episode_no)
            value, sha256, error = _read_snapshot(
                root=root,
                path=path,
                maximum=maximum,
                reader=lambda reader=reader, episode_no=episode_no: reader(
                    workspace,
                    episode_no=episode_no,
                ),
            )
            if error is not None or value is None or sha256 is None:
                _add_blocker(
                    blocker_rows,
                    source=source,
                    episode_no=episode_no,
                    code=error or "source_invalid",
                )
                continue
            source_snapshot(source, sha256, episode_no)
            if value.episode_no != episode_no:
                _add_blocker(
                    blocker_rows,
                    source=source,
                    episode_no=episode_no,
                    code="episode_identity_mismatch",
                )
                continue
            if file_kind == "art_direction":
                if value.season_no != season:
                    continue
                for version in value.versions:
                    add_inventory(
                        "art_direction",
                        value.art_direction_id,
                        version.version_id,
                        version.version_fingerprint,
                    )
                continue
            if value.season_no != season:
                continue
            if file_kind == "render_plan":
                if value.art_direction_ref is None:
                    continue
                key = (
                    "art_direction",
                    value.art_direction_ref.art_direction_id,
                    value.art_direction_ref.version_id,
                )
                expected = inventory.get(key)
                if expected != value.art_direction_ref.fingerprint:
                    _add_blocker(
                        blocker_rows,
                        source=source,
                        episode_no=episode_no,
                        code="reference_not_in_catalog",
                    )
                    continue
                usage.setdefault(key, {}).setdefault(episode_no, set()).update(
                    shot.shot_id for shot in value.shots
                )
            elif file_kind == "asset_manifest":
                for ref in value.asset_refs:
                    key = ("character", ref.asset_id, ref.asset_version_id)
                    if inventory.get(key) != ref.version_fingerprint:
                        _add_blocker(
                            blocker_rows,
                            source=source,
                            episode_no=episode_no,
                            code="reference_not_in_catalog",
                        )
                        continue
                    usage.setdefault(key, {}).setdefault(episode_no, set())
            elif file_kind == "scene_asset_manifest":
                for binding in value.shot_scene_refs:
                    ref = binding.scene_ref
                    key = ("scene", ref.scene_id, ref.scene_version_id)
                    if inventory.get(key) != ref.version_fingerprint:
                        _add_blocker(
                            blocker_rows,
                            source=source,
                            episode_no=episode_no,
                            code="reference_not_in_catalog",
                        )
                        continue
                    usage.setdefault(key, {}).setdefault(episode_no, set()).add(
                        binding.shot_id
                    )
            else:
                for binding in value.shot_asset_refs:
                    for ref in binding.asset_refs:
                        key = (ref.kind, ref.asset_id, ref.asset_version_id)
                        if inventory.get(key) != ref.version_fingerprint:
                            _add_blocker(
                                blocker_rows,
                                source=source,
                                episode_no=episode_no,
                                code="reference_not_in_catalog",
                            )
                            continue
                        usage.setdefault(key, {}).setdefault(
                            episode_no,
                            set(),
                        ).add(binding.shot_id)
    if not directory_unchanged():
        _add_blocker(
            blocker_rows,
            source="episode_scan",
            code="source_changed",
        )

    entries = [
        AssetVersionUsage(
            kind=key[0],
            asset_id=key[1],
            version_id=key[2],
            references=[
                AssetUsageReference(
                    episode_no=episode_no,
                    shot_ids=sorted(shot_ids),
                )
                for episode_no, shot_ids in sorted(
                    usage.get(key, {}).items()
                )
            ],
        )
        for key in sorted(inventory)
    ]
    sources = [
        AssetUsageSourceSnapshot(
            source=source,
            episode_no=episode_no,
            sha256=sha256,
        )
        for source, episode_no, sha256 in sorted(
            source_rows,
            key=lambda row: (row[0], row[1] or 0, row[2]),
        )
    ]
    blockers = [
        AssetUsageBlocker(
            source=source,
            episode_no=episode_no,
            code=code,
        )
        for source, episode_no, code in sorted(
            blocker_rows,
            key=lambda row: (row[0], row[1] or 0, row[2]),
        )
    ]
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": season,
        "scanned_episode_nos": scanned_episodes,
        "entries": [model_to_dict(item) for item in entries],
        "source_snapshots": [model_to_dict(item) for item in sources],
        "blockers": [model_to_dict(item) for item in blockers],
    }
    payload["index_fingerprint"] = _canonical_sha256(payload)
    return SeasonAssetUsageIndex(**payload)


def build_asset_retirement_decision(
    workspace: str,
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
    season_no: int = 1,
    usage_index: SeasonAssetUsageIndex | None = None,
    retirement_state: AssetRetirementState | None = None,
) -> AssetRetirementDecision:
    season = _strict_season_no(season_no)
    _validate_asset_usage_identity(
        kind=kind,
        asset_id=asset_id,
        version_id=version_id,
    )
    index = (
        build_season_asset_usage_index(workspace, season_no=season)
        if usage_index is None
        else SeasonAssetUsageIndex(**model_to_dict(usage_index))
    )
    state = (
        load_asset_retirement_state(workspace, season_no=season)
        if retirement_state is None
        else AssetRetirementState(**model_to_dict(retirement_state))
    )
    if index.season_no != season or state.season_no != season:
        raise ValueError("asset retirement inputs belong to another season")
    entry = next(
        (
            item
            for item in index.entries
            if (
                item.kind == kind
                and item.asset_id == asset_id
                and item.version_id == version_id
            )
        ),
        None,
    )
    if entry is None:
        raise DramaAssetUsageError("asset version is not available for retirement")
    payload: Dict[str, Any] = {
        "kind": kind,
        "asset_id": asset_id,
        "version_id": version_id,
        "current_status": asset_version_status(
            state,
            kind=kind,
            asset_id=asset_id,
            version_id=version_id,
        ),
        "references": [model_to_dict(item) for item in entry.references],
        "blockers": [model_to_dict(item) for item in index.blockers],
        "can_disable": not index.blockers,
        "can_physically_delete": False,
    }
    payload["decision_fingerprint"] = _canonical_sha256(payload)
    return AssetRetirementDecision(**payload)


def set_asset_version_status(
    workspace: str,
    *,
    kind: AssetUsageKind,
    asset_id: str,
    version_id: str,
    status: AssetRetirementStatus,
    expected_revision: int,
    expected_current_status: AssetRetirementStatus,
    season_no: int = 1,
) -> AssetRetirementState:
    season = _strict_season_no(season_no)
    _validate_asset_usage_identity(
        kind=kind,
        asset_id=asset_id,
        version_id=version_id,
    )
    if status not in ("active", "disabled") or expected_current_status not in (
        "active",
        "disabled",
    ):
        raise ValueError("asset retirement status is invalid")
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
        or expected_revision > 2_147_483_647
    ):
        raise ValueError("expected retirement revision must be a strict integer")
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-asset-retirement"
        ):
            inspection = inspect_asset_retirement_state(
                workspace,
                season_no=season,
            )
            if inspection.state == "invalid":
                raise DramaAssetUsageError("asset retirement state is invalid")
            if inspection.target_token is None:
                raise DramaAssetUsageError(
                    "asset retirement inspection token is unavailable"
                )
            current = (
                inspection.value
                if inspection.value is not None
                else build_asset_retirement_state(season_no=season)
            )
            if current.revision != expected_revision:
                raise DramaAssetUsageError("asset retirement revision changed")
            current_status = asset_version_status(
                current,
                kind=kind,
                asset_id=asset_id,
                version_id=version_id,
            )
            if current_status != expected_current_status:
                raise DramaAssetUsageError("asset retirement status changed")
            index = build_season_asset_usage_index(
                workspace,
                season_no=season,
            )
            decision = build_asset_retirement_decision(
                workspace,
                kind=kind,
                asset_id=asset_id,
                version_id=version_id,
                season_no=season,
                usage_index=index,
                retirement_state=current,
            )
            if status == current_status:
                return current
            if status == "disabled" and not decision.can_disable:
                raise DramaAssetUsageError(
                    "asset usage index is incomplete; retirement is blocked"
                )
            if current.revision >= 2_147_483_647:
                raise DramaAssetUsageError("asset retirement revision exhausted")
            next_revision = current.revision + 1
            entries = [
                item
                for item in current.entries
                if not (
                    item.kind == kind
                    and item.asset_id == asset_id
                    and item.version_id == version_id
                )
            ]
            entries.append(
                AssetRetirementEntry(
                    kind=kind,
                    asset_id=asset_id,
                    version_id=version_id,
                    status=status,
                    status_revision=next_revision,
                    usage_index_fingerprint=(
                        index.index_fingerprint
                        if status == "disabled"
                        else None
                    ),
                )
            )
            desired = build_asset_retirement_state(
                season_no=season,
                revision=next_revision,
                entries=entries,
            )

            def precommit() -> None:
                if status != "disabled":
                    return
                final_index = build_season_asset_usage_index(
                    workspace,
                    season_no=season,
                )
                if (
                    final_index.blockers
                    or final_index.index_fingerprint
                    != index.index_fingerprint
                ):
                    raise DramaAssetUsageError(
                        "asset usage changed concurrently"
                    )

            _write_envelope(
                root=root,
                path=asset_retirement_state_path(
                    workspace,
                    season_no=season,
                ),
                envelope={
                    "schema_version": 1,
                    "artifact_type": "drama_asset_retirement",
                    "state_fingerprint": desired.state_fingerprint,
                    "state": model_to_dict(desired),
                },
                maximum=MAX_ASSET_RETIREMENT_STATE_BYTES,
                expected_target_token=inspection.target_token,
                precommit_check=precommit,
            )
            persisted = _read_retirement_state(
                workspace,
                season_no=season,
            )
            if persisted != desired:
                raise DramaAssetUsageError(
                    "persisted asset retirement state failed verification"
                )
            return persisted
    except DramaAssetUsageError:
        raise
    except WorkspaceLocked:
        raise DramaAssetUsageError("asset retirement workspace is busy") from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaAssetUsageError("asset retirement mutation was rejected") from None
