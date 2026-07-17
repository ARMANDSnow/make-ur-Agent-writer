"""Visual-only override versions, guarded selection, and stale propagation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal

from . import paths
from .drama_render_store import (
    RenderPlanStoreError,
    _render_plan_target_token,
    load_fresh_render_plan,
)
from .drama_schemas import (
    DRAMA_STALE_DEPENDENCY_NODES,
    DRAMA_STALE_DEPENDENCY_ROWS,
    EpisodeVisualOverrideManifest,
    RenderPlan,
    StaleDependencyChange,
    StaleDependencyImpact,
    VisualOverrideCatalog,
    VisualOverrideSelection,
    VisualOverrideSelectionImpact,
    VisualOverrideSelectionResult,
    VisualOverrideSelectionTransition,
    VisualOverrideSourceKind,
    VisualOverrideSpec,
    VisualOverrideState,
    VisualOverrideVersion,
    episode_paths,
    normalize_episode_no,
)
from .drama_store import _read_strict_workspace_bytes, _validate_render_workspace_root
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_VISUAL_OVERRIDE_STATE_BYTES = 4_000_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_ID_RE = re.compile(r"^vo_[0-9a-f]{24}$")

VisualOverrideInspectionState = Literal[
    "needs_visual_overrides",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaVisualOverrideError(ValueError):
    pass


class _VisualOverrideReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VisualOverrideInspection:
    state: VisualOverrideInspectionState
    reasons: tuple[str, ...]
    value: VisualOverrideState | None = None
    target_token: tuple[Any, ...] | None = None


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def visual_override_state_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("visual override path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.visual_overrides.json"


def build_visual_override_version(
    plan: RenderPlan,
    *,
    shot_id: str,
    spec: VisualOverrideSpec | Dict[str, Any],
    source_kind: VisualOverrideSourceKind,
    derived_from: str | None = None,
) -> VisualOverrideVersion:
    plan = _revalidate_plan(plan)
    shot_by_id = {item.shot_id: item for item in plan.shots}
    shot = shot_by_id.get(shot_id)
    if shot is None:
        raise ValueError("visual override shot does not exist")
    validated_spec = (
        spec if isinstance(spec, VisualOverrideSpec) else VisualOverrideSpec(**spec)
    )
    payload = {
        "shot_id": shot.shot_id,
        "source_fingerprint": shot.source_fingerprint,
        "derived_from": derived_from,
        "source_kind": source_kind,
        "spec": model_to_dict(validated_spec),
    }
    fingerprint = _canonical_sha256(payload)
    return VisualOverrideVersion(
        version_id=f"vo_{fingerprint[:24]}",
        version_fingerprint=fingerprint,
        **payload,
    )


def _catalog_payload(
    *,
    plan: RenderPlan,
    versions: list[VisualOverrideVersion],
    selections: list[VisualOverrideSelection],
    selection_revision: int,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "versions": [
            model_to_dict(item)
            for item in sorted(versions, key=lambda row: (row.shot_id, row.version_id))
        ],
        "selections": [
            model_to_dict(item)
            for item in sorted(selections, key=lambda row: row.shot_id)
        ],
        "selection_revision": selection_revision,
    }


def build_visual_override_catalog(
    plan: RenderPlan,
    *,
    versions: list[VisualOverrideVersion] | None = None,
    selections: list[VisualOverrideSelection] | None = None,
    selection_revision: int = 0,
) -> VisualOverrideCatalog:
    plan = _revalidate_plan(plan)
    if (
        not isinstance(selection_revision, int)
        or isinstance(selection_revision, bool)
        or selection_revision < 0
        or selection_revision > 2_147_483_647
    ):
        raise ValueError("selection_revision must be a strict bounded integer")
    if versions is not None and not isinstance(versions, list):
        raise TypeError("versions must be a list")
    if selections is not None and not isinstance(selections, list):
        raise TypeError("selections must be a list")
    candidates = list(versions or [])
    selected = list(selections or [])
    shot_by_id = {item.shot_id: item for item in plan.shots}
    for version in candidates:
        shot = shot_by_id.get(version.shot_id)
        if shot is None or version.source_fingerprint != shot.source_fingerprint:
            raise ValueError("visual override version is stale for this render plan")
    payload = _catalog_payload(
        plan=plan,
        versions=candidates,
        selections=selected,
        selection_revision=selection_revision,
    )
    payload["catalog_fingerprint"] = _canonical_sha256(payload)
    return VisualOverrideCatalog(**payload)


def append_visual_override_candidate(
    plan: RenderPlan,
    catalog: VisualOverrideCatalog,
    *,
    shot_id: str,
    spec: VisualOverrideSpec | Dict[str, Any],
    source_kind: VisualOverrideSourceKind,
    derived_from: str | None = None,
) -> tuple[VisualOverrideCatalog, VisualOverrideVersion]:
    plan, catalog = _validate_catalog_against_plan(plan, catalog)
    version = build_visual_override_version(
        plan,
        shot_id=shot_id,
        spec=spec,
        source_kind=source_kind,
        derived_from=derived_from,
    )
    existing_by_id = {item.version_id: item for item in catalog.versions}
    existing = existing_by_id.get(version.version_id)
    if existing is not None:
        if existing != version:
            raise ValueError("visual override version id collision")
        return catalog, existing
    if derived_from is not None:
        parent = existing_by_id.get(derived_from)
        if parent is None or parent.shot_id != shot_id:
            raise ValueError("visual override parent is invalid")
    updated = build_visual_override_catalog(
        plan,
        versions=[*catalog.versions, version],
        selections=catalog.selections,
        selection_revision=catalog.selection_revision,
    )
    return updated, version


def select_visual_override_candidate(
    plan: RenderPlan,
    catalog: VisualOverrideCatalog,
    *,
    shot_id: str,
    version_id: str | None,
    expected_selection_revision: int,
    expected_current_version_id: str | None,
) -> VisualOverrideCatalog:
    plan, catalog = _validate_catalog_against_plan(plan, catalog)
    if (
        not isinstance(expected_selection_revision, int)
        or isinstance(expected_selection_revision, bool)
    ):
        raise ValueError("expected_selection_revision must be a strict integer")
    if expected_selection_revision != catalog.selection_revision:
        raise DramaVisualOverrideError("visual override selection revision changed")
    if version_id is not None and (
        not isinstance(version_id, str)
        or _VERSION_ID_RE.fullmatch(version_id) is None
    ):
        raise ValueError("visual override version id is invalid")
    if expected_current_version_id is not None and (
        not isinstance(expected_current_version_id, str)
        or _VERSION_ID_RE.fullmatch(expected_current_version_id) is None
    ):
        raise ValueError("expected current visual override id is invalid")
    selected_by_shot = {
        item.shot_id: item.version_id for item in catalog.selections
    }
    current = selected_by_shot.get(shot_id)
    if current != expected_current_version_id:
        raise DramaVisualOverrideError("visual override current selection changed")
    shot_by_id = {item.shot_id: item for item in plan.shots}
    if shot_id not in shot_by_id:
        raise ValueError("visual override shot does not exist")
    if version_id is not None:
        version = next(
            (item for item in catalog.versions if item.version_id == version_id),
            None,
        )
        if version is None or version.shot_id != shot_id:
            raise ValueError("visual override selection is invalid")
    if current == version_id:
        return catalog
    if catalog.selection_revision >= 2_147_483_647:
        raise DramaVisualOverrideError("visual override selection revision exhausted")
    selected_by_shot.pop(shot_id, None)
    if version_id is not None:
        selected_by_shot[shot_id] = version_id
    selections = [
        VisualOverrideSelection(shot_id=key, version_id=value)
        for key, value in selected_by_shot.items()
    ]
    return build_visual_override_catalog(
        plan,
        versions=catalog.versions,
        selections=selections,
        selection_revision=catalog.selection_revision + 1,
    )


def build_effective_visual_override_manifest(
    plan: RenderPlan,
    catalog: VisualOverrideCatalog,
) -> EpisodeVisualOverrideManifest:
    plan, catalog = _validate_catalog_against_plan(plan, catalog)
    version_by_id = {item.version_id: item for item in catalog.versions}
    selected: list[Dict[str, Any]] = []
    for selection in sorted(catalog.selections, key=lambda row: row.shot_id):
        version = version_by_id[selection.version_id]
        selected.append(
            {
                "shot_id": version.shot_id,
                "source_fingerprint": version.source_fingerprint,
                "version_id": version.version_id,
                "version_fingerprint": version.version_fingerprint,
                "spec": model_to_dict(version.spec),
            }
        )
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "selection_revision": catalog.selection_revision,
        "selected_overrides": selected,
    }
    payload["manifest_fingerprint"] = _canonical_sha256(payload)
    return EpisodeVisualOverrideManifest(**payload)


def build_visual_override_state(
    plan: RenderPlan,
    catalog: VisualOverrideCatalog,
    *,
    selection_transitions: list[VisualOverrideSelectionTransition] | None = None,
) -> VisualOverrideState:
    plan, catalog = _validate_catalog_against_plan(plan, catalog)
    if selection_transitions is not None and not isinstance(
        selection_transitions,
        list,
    ):
        raise TypeError("selection_transitions must be a list")
    transitions = [
        VisualOverrideSelectionTransition(**model_to_dict(item))
        for item in (selection_transitions or [])
    ]
    manifest = build_effective_visual_override_manifest(plan, catalog)
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "catalog": model_to_dict(catalog),
        "manifest": model_to_dict(manifest),
        "selection_transitions": [model_to_dict(item) for item in transitions],
    }
    payload["state_fingerprint"] = _canonical_sha256(payload)
    return VisualOverrideState(**payload)


def _revalidate_plan(plan: RenderPlan) -> RenderPlan:
    if not isinstance(plan, RenderPlan):
        raise TypeError("plan must be a RenderPlan")
    return RenderPlan(**model_to_dict(plan))


def _validate_catalog_against_plan(
    plan: RenderPlan,
    catalog: VisualOverrideCatalog,
) -> tuple[RenderPlan, VisualOverrideCatalog]:
    if not isinstance(plan, RenderPlan) or not isinstance(
        catalog,
        VisualOverrideCatalog,
    ):
        raise TypeError("plan and catalog must be validated models")
    plan = _revalidate_plan(plan)
    catalog = VisualOverrideCatalog(**model_to_dict(catalog))
    if (
        catalog.season_no != plan.season_no
        or catalog.episode_no != plan.episode_no
        or catalog.render_plan_fingerprint != plan.plan_fingerprint
    ):
        raise ValueError("visual override catalog belongs to another render plan")
    shot_by_id = {item.shot_id: item for item in plan.shots}
    for version in catalog.versions:
        shot = shot_by_id.get(version.shot_id)
        if shot is None or version.source_fingerprint != shot.source_fingerprint:
            raise ValueError("visual override version is stale for this render plan")
    return plan, catalog


def classify_stale_dependency(
    change: StaleDependencyChange,
    *,
    shot_id: str | None = None,
) -> StaleDependencyImpact:
    if change not in DRAMA_STALE_DEPENDENCY_ROWS:
        raise ValueError("unsupported stale dependency change")
    shot_scoped = change not in {"creative_revision", "bgm_selection"}
    if shot_scoped:
        if not isinstance(shot_id, str) or re.fullmatch(
            r"shot_[0-9a-f]{24}",
            shot_id,
        ) is None:
            raise ValueError("shot-scoped dependency change requires a valid shot id")
    elif shot_id is not None:
        raise ValueError("episode-scoped dependency change does not accept a shot id")
    affected = list(DRAMA_STALE_DEPENDENCY_ROWS[change])
    unaffected = [
        item for item in DRAMA_STALE_DEPENDENCY_NODES if item not in affected
    ]
    payload: Dict[str, Any] = {
        "matrix_version": "drama-stale-matrix-v1",
        "change": change,
        "scope": "shot" if shot_scoped else "episode",
        "shot_id": shot_id,
        "affected_nodes": affected,
        "unaffected_nodes": unaffected,
    }
    payload["impact_fingerprint"] = _canonical_sha256(payload)
    return StaleDependencyImpact(**payload)


def classify_visual_selection_change(
    *,
    shot_id: str,
    old_version: VisualOverrideVersion | None,
    new_version: VisualOverrideVersion | None,
) -> VisualOverrideSelectionImpact:
    if not isinstance(shot_id, str) or re.fullmatch(
        r"shot_[0-9a-f]{24}",
        shot_id,
    ) is None:
        raise ValueError("visual selection impact requires a valid shot id")

    def validated(
        value: VisualOverrideVersion | None,
    ) -> VisualOverrideVersion | None:
        if value is None:
            return None
        if not isinstance(value, VisualOverrideVersion):
            raise TypeError("visual selection versions must be validated models")
        result = VisualOverrideVersion(**model_to_dict(value))
        if result.shot_id != shot_id:
            raise ValueError("visual selection version belongs to another shot")
        return result

    old = validated(old_version)
    new = validated(new_version)
    old_spec = old.spec if old is not None else None
    new_spec = new.spec if new is not None else None
    fields = ("camera_movement", "lighting", "negative_prompt", "transition")
    changed_fields = [
        field
        for field in fields
        if (
            getattr(old_spec, field) if old_spec is not None else None
        )
        != (
            getattr(new_spec, field) if new_spec is not None else None
        )
    ]
    field_changes: Dict[str, StaleDependencyChange] = {
        "camera_movement": "override_camera",
        "lighting": "override_lighting",
        "negative_prompt": "override_negative_prompt",
        "transition": "override_transition",
    }
    affected_set = {
        node
        for field in changed_fields
        for node in DRAMA_STALE_DEPENDENCY_ROWS[field_changes[field]]
    }
    affected = [
        item for item in DRAMA_STALE_DEPENDENCY_NODES if item in affected_set
    ]
    unaffected = [
        item for item in DRAMA_STALE_DEPENDENCY_NODES if item not in affected_set
    ]
    payload: Dict[str, Any] = {
        "matrix_version": "drama-stale-matrix-v1",
        "shot_id": shot_id,
        "old_version": model_to_dict(old) if old is not None else None,
        "new_version": model_to_dict(new) if new is not None else None,
        "changed_fields": changed_fields,
        "affected_nodes": affected,
        "unaffected_nodes": unaffected,
    }
    payload["impact_fingerprint"] = _canonical_sha256(payload)
    return VisualOverrideSelectionImpact(**payload)


def build_visual_selection_transition(
    *,
    plan: RenderPlan,
    before_state: VisualOverrideState,
    after_catalog: VisualOverrideCatalog,
    after_manifest: EpisodeVisualOverrideManifest,
    impact: VisualOverrideSelectionImpact,
) -> VisualOverrideSelectionTransition:
    plan = _revalidate_plan(plan)
    if not isinstance(before_state, VisualOverrideState):
        raise TypeError("before_state must be a VisualOverrideState")
    if not isinstance(after_catalog, VisualOverrideCatalog):
        raise TypeError("after_catalog must be a VisualOverrideCatalog")
    if not isinstance(after_manifest, EpisodeVisualOverrideManifest):
        raise TypeError("after_manifest must be an EpisodeVisualOverrideManifest")
    if not isinstance(impact, VisualOverrideSelectionImpact):
        raise TypeError("impact must be a VisualOverrideSelectionImpact")
    before = VisualOverrideState(**model_to_dict(before_state))
    after = VisualOverrideCatalog(**model_to_dict(after_catalog))
    manifest = EpisodeVisualOverrideManifest(**model_to_dict(after_manifest))
    validated_impact = VisualOverrideSelectionImpact(**model_to_dict(impact))
    if (
        before.catalog.season_no != after.season_no
        or before.catalog.episode_no != after.episode_no
        or before.catalog.render_plan_fingerprint
        != after.render_plan_fingerprint
        or before.catalog.versions != after.versions
    ):
        raise ValueError("visual override transition catalog is inconsistent")
    expected_manifest = build_effective_visual_override_manifest(plan, after)
    if manifest != expected_manifest:
        raise ValueError("visual override transition manifest is inconsistent")
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "before_state_fingerprint": before.state_fingerprint,
        "before_selection_revision": before.catalog.selection_revision,
        "after_selection_revision": after.selection_revision,
        "impact": model_to_dict(validated_impact),
        "before_manifest": model_to_dict(before.manifest),
        "after_manifest": model_to_dict(manifest),
    }
    fingerprint = _canonical_sha256(payload)
    return VisualOverrideSelectionTransition(
        transition_id=f"vot_{fingerprint[:24]}",
        transition_fingerprint=fingerprint,
        **payload,
    )


def build_visual_selection_result(
    state: VisualOverrideState,
    *,
    transition_id: str | None,
) -> VisualOverrideSelectionResult:
    if not isinstance(state, VisualOverrideState):
        raise TypeError("state must be a VisualOverrideState")
    validated = VisualOverrideState(**model_to_dict(state))
    status: Literal["target_current", "superseded", "no_op"] = "no_op"
    if transition_id is not None:
        transition = next(
            (
                item
                for item in validated.selection_transitions
                if item.transition_id == transition_id
            ),
            None,
        )
        if transition is None:
            raise ValueError("visual override selection transition is missing")
        selected_by_shot = {
            item.shot_id: item
            for item in validated.manifest.selected_overrides
        }
        selected = selected_by_shot.get(transition.impact.shot_id)
        expected = transition.impact.new_version
        is_current = (
            (expected is None and selected is None)
            or (
                expected is not None
                and selected is not None
                and selected.source_fingerprint == expected.source_fingerprint
                and selected.version_id == expected.version_id
                and selected.version_fingerprint == expected.version_fingerprint
                and selected.spec == expected.spec
            )
        )
        status = "target_current" if is_current else "superseded"
    payload: Dict[str, Any] = {
        "state": model_to_dict(validated),
        "transition_id": transition_id,
        "status": status,
    }
    payload["result_fingerprint"] = _canonical_sha256(payload)
    return VisualOverrideSelectionResult(**payload)


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _VisualOverrideReadError("schema_invalid")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise _VisualOverrideReadError("schema_invalid")


def _parse_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _VisualOverrideReadError("schema_invalid")
    return number


def _read_state_with_token(
    workspace: str,
    *,
    episode_no: int,
) -> tuple[VisualOverrideState, tuple[Any, ...]]:
    root = paths.workspace_root(workspace)
    path = visual_override_state_path(workspace, episode_no=episode_no)
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_VISUAL_OVERRIDE_STATE_BYTES,
        )
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise _VisualOverrideReadError("schema_invalid") from exc
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except _VisualOverrideReadError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise _VisualOverrideReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "state_fingerprint",
        "state",
    }:
        raise _VisualOverrideReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _VisualOverrideReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_visual_overrides":
        raise _VisualOverrideReadError("schema_invalid")
    if (
        not isinstance(raw["state_fingerprint"], str)
        or _SHA256_RE.fullmatch(raw["state_fingerprint"]) is None
        or not isinstance(raw["state"], dict)
    ):
        raise _VisualOverrideReadError("state_hash_mismatch")
    try:
        state = VisualOverrideState(**raw["state"])
    except (TypeError, ValueError) as exc:
        raise _VisualOverrideReadError("schema_invalid") from exc
    if raw["state_fingerprint"] != state.state_fingerprint:
        raise _VisualOverrideReadError("state_hash_mismatch")
    return state, ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _read_state(workspace: str, *, episode_no: int) -> VisualOverrideState:
    state, _target_token = _read_state_with_token(
        workspace,
        episode_no=episode_no,
    )
    return state


def inspect_visual_override_state(
    workspace: str,
    *,
    episode_no: int = 1,
) -> VisualOverrideInspection:
    number = normalize_episode_no(episode_no)
    try:
        state, target_token = _read_state_with_token(
            workspace,
            episode_no=number,
        )
    except FileNotFoundError:
        state = None
        target_token = ("missing",)
    except _VisualOverrideReadError as exc:
        return VisualOverrideInspection("invalid", (exc.reason,))
    try:
        plan = load_fresh_render_plan(workspace, episode_no=number)
    except (OSError, TypeError, ValueError, RenderPlanStoreError):
        return VisualOverrideInspection(
            "blocked_source",
            ("render_plan_not_fresh",),
            state,
            target_token,
        )
    if state is None:
        return VisualOverrideInspection(
            "needs_visual_overrides",
            ("missing",),
            target_token=target_token,
        )
    if (
        state.catalog.season_no != plan.season_no
        or state.catalog.episode_no != plan.episode_no
    ):
        return VisualOverrideInspection(
            "stale",
            ("episode_identity_mismatch",),
            state,
            target_token,
        )
    if state.catalog.render_plan_fingerprint != plan.plan_fingerprint:
        return VisualOverrideInspection(
            "stale",
            ("render_plan_changed",),
            state,
            target_token,
        )
    try:
        expected = build_visual_override_state(
            plan,
            state.catalog,
            selection_transitions=state.selection_transitions,
        )
    except (TypeError, ValueError):
        return VisualOverrideInspection(
            "stale",
            ("override_source_changed",),
            state,
            target_token,
        )
    if expected != state:
        return VisualOverrideInspection(
            "invalid",
            ("derived_manifest_mismatch",),
            state,
        )
    return VisualOverrideInspection("fresh", (), state, target_token)


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
            or info.st_size > MAX_VISUAL_OVERRIDE_STATE_BYTES
        ):
            return ("invalid",)
        digest = hashlib.sha256()
        read_size = 0
        while read_size <= MAX_VISUAL_OVERRIDE_STATE_BYTES:
            chunk = os.read(file_fd, 65536)
            if not chunk:
                break
            read_size += len(chunk)
            digest.update(chunk)
        if read_size != info.st_size or read_size > MAX_VISUAL_OVERRIDE_STATE_BYTES:
            return ("invalid",)
        return ("file", read_size, digest.hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _write_state(
    workspace: str,
    state: VisualOverrideState,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None],
    postcommit_check: Callable[[], None],
) -> None:
    if expected_target_token == ("invalid",):
        raise DramaVisualOverrideError(
            "invalid visual override state cannot be overwritten"
        )
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_visual_overrides",
        "state_fingerprint": state.state_fingerprint,
        "state": model_to_dict(state),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_VISUAL_OVERRIDE_STATE_BYTES:
        raise DramaVisualOverrideError("visual override state exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = visual_override_state_path(workspace, episode_no=state.catalog.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaVisualOverrideError("visual override path escapes workspace") from exc
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaVisualOverrideError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = f".{relative.name}.tmp.{os.getpid()}.{threading.get_ident()}"

    def assert_output_namespace() -> None:
        if directory_fd is None:
            raise DramaVisualOverrideError("visual override output is unavailable")
        try:
            pinned = os.fstat(directory_fd)
            current = os.stat(path.parent, follow_symlinks=False)
        except OSError as exc:
            raise DramaVisualOverrideError(
                "visual override output namespace changed"
            ) from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise DramaVisualOverrideError(
                "visual override output namespace changed"
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
        current_target_token = _target_token_at(directory_fd, relative.name)
        if current_target_token == ("invalid",):
            raise DramaVisualOverrideError(
                "invalid visual override state cannot be overwritten"
            )
        if current_target_token != expected_target_token:
            raise DramaVisualOverrideError(
                "visual override state changed concurrently"
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
                raise OSError("short visual override write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        precommit_check()
        assert_output_namespace()
        current_target_token = _target_token_at(directory_fd, relative.name)
        if current_target_token == ("invalid",):
            raise DramaVisualOverrideError(
                "invalid visual override state cannot be overwritten"
            )
        if current_target_token != expected_target_token:
            raise DramaVisualOverrideError(
                "visual override state changed concurrently"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        assert_output_namespace()
        postcommit_check()
        os.fsync(directory_fd)
    except DramaVisualOverrideError:
        raise
    except OSError as exc:
        raise DramaVisualOverrideError(
            "visual override state could not be written safely"
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


def _persist_for_plan(
    workspace: str,
    *,
    plan: RenderPlan,
    state: VisualOverrideState,
    target_token: tuple[Any, ...],
) -> VisualOverrideState:
    source_token = _render_plan_target_token(
        workspace,
        episode_no=plan.episode_no,
    )
    if source_token in {("missing",), ("invalid",)}:
        raise DramaVisualOverrideError("render plan source is invalid")
    initial_plan = load_fresh_render_plan(
        workspace,
        episode_no=plan.episode_no,
    )
    if initial_plan.plan_fingerprint != plan.plan_fingerprint:
        raise DramaVisualOverrideError("render plan changed concurrently")

    def check_source() -> None:
        if (
            _render_plan_target_token(
                workspace,
                episode_no=plan.episode_no,
            )
            != source_token
        ):
            raise DramaVisualOverrideError("render plan changed concurrently")
        current = load_fresh_render_plan(
            workspace,
            episode_no=plan.episode_no,
        )
        if current.plan_fingerprint != plan.plan_fingerprint:
            raise DramaVisualOverrideError("render plan changed concurrently")

    _write_state(
        workspace,
        state,
        expected_target_token=target_token,
        precommit_check=check_source,
        postcommit_check=check_source,
    )
    persisted = _read_state(workspace, episode_no=plan.episode_no)
    if persisted != state:
        raise DramaVisualOverrideError(
            "persisted visual override state failed verification"
        )
    check_source()
    return persisted


@contextmanager
def _visual_override_write_lock():
    try:
        with acquire_write_lock(source="drama-visual-override"):
            yield
    except WorkspaceLocked:
        raise DramaVisualOverrideError(
            "visual override workspace is busy"
        ) from None


def ensure_visual_override_state(
    workspace: str,
    *,
    episode_no: int = 1,
) -> VisualOverrideState:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), _visual_override_write_lock():
        inspection = inspect_visual_override_state(workspace, episode_no=number)
        if inspection.state == "fresh" and inspection.value is not None:
            return inspection.value
        if inspection.state != "needs_visual_overrides":
            raise DramaVisualOverrideError(
                f"visual override state is not creatable: {inspection.state}"
            )
        plan = load_fresh_render_plan(workspace, episode_no=number)
        state = build_visual_override_state(
            plan,
            build_visual_override_catalog(plan),
        )
        return _persist_for_plan(
            workspace,
            plan=plan,
            state=state,
            target_token=inspection.target_token or ("missing",),
        )


def add_visual_override_candidate(
    workspace: str,
    *,
    shot_id: str,
    spec: VisualOverrideSpec | Dict[str, Any],
    source_kind: VisualOverrideSourceKind,
    derived_from: str | None = None,
    episode_no: int = 1,
) -> VisualOverrideVersion:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), _visual_override_write_lock():
        inspection = inspect_visual_override_state(workspace, episode_no=number)
        if inspection.state == "needs_visual_overrides":
            plan = load_fresh_render_plan(workspace, episode_no=number)
            current = build_visual_override_state(
                plan,
                build_visual_override_catalog(plan),
            )
            target_token = inspection.target_token or ("missing",)
        elif inspection.state == "fresh" and inspection.value is not None:
            plan = load_fresh_render_plan(workspace, episode_no=number)
            current = inspection.value
            if inspection.target_token is None:
                raise DramaVisualOverrideError(
                    "visual override inspection token is unavailable"
                )
            target_token = inspection.target_token
        else:
            raise DramaVisualOverrideError(
                f"visual override state is not writable: {inspection.state}"
            )
        catalog, version = append_visual_override_candidate(
            plan,
            current.catalog,
            shot_id=shot_id,
            spec=spec,
            source_kind=source_kind,
            derived_from=derived_from,
        )
        desired = build_visual_override_state(
            plan,
            catalog,
            selection_transitions=current.selection_transitions,
        )
        if desired == current:
            return version
        _persist_for_plan(
            workspace,
            plan=plan,
            state=desired,
            target_token=target_token,
        )
        return version


def select_visual_override(
    workspace: str,
    *,
    shot_id: str,
    version_id: str | None,
    expected_selection_revision: int,
    expected_current_version_id: str | None,
    episode_no: int = 1,
) -> VisualOverrideSelectionResult:
    if (
        not isinstance(shot_id, str)
        or re.fullmatch(r"shot_[0-9a-f]{24}", shot_id) is None
    ):
        raise ValueError("visual override shot id is invalid")
    if (
        not isinstance(expected_selection_revision, int)
        or isinstance(expected_selection_revision, bool)
        or expected_selection_revision < 0
        or expected_selection_revision > 2_147_483_647
    ):
        raise ValueError("expected_selection_revision must be a strict integer")
    for field, value in (
        ("version_id", version_id),
        ("expected_current_version_id", expected_current_version_id),
    ):
        if value is not None and (
            not isinstance(value, str)
            or _VERSION_ID_RE.fullmatch(value) is None
        ):
            raise ValueError(f"{field} is invalid")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), _visual_override_write_lock():
        inspection = inspect_visual_override_state(workspace, episode_no=number)
        if inspection.state != "fresh" or inspection.value is None:
            raise DramaVisualOverrideError(
                f"visual override state is not selectable: {inspection.state}"
            )
        if inspection.target_token is None:
            raise DramaVisualOverrideError(
                "visual override inspection token is unavailable"
            )
        plan = load_fresh_render_plan(workspace, episode_no=number)
        version_by_id = {
            item.version_id: item for item in inspection.value.catalog.versions
        }
        selected_by_shot = {
            item.shot_id: item.version_id
            for item in inspection.value.catalog.selections
        }
        actual_current_version_id = selected_by_shot.get(shot_id)
        recovered = next(
            (
                item
                for item in inspection.value.selection_transitions
                if _transition_matches_selection_request(
                    item,
                    shot_id=shot_id,
                    version_id=version_id,
                    expected_selection_revision=expected_selection_revision,
                    expected_current_version_id=expected_current_version_id,
                )
            ),
            None,
        )
        if recovered is not None:
            return build_visual_selection_result(
                inspection.value,
                transition_id=recovered.transition_id,
            )
        if (
            expected_selection_revision
            == inspection.value.catalog.selection_revision
            and expected_current_version_id == actual_current_version_id
            and actual_current_version_id == version_id
        ):
            return build_visual_selection_result(
                inspection.value,
                transition_id=None,
            )

        old_version = (
            version_by_id.get(actual_current_version_id)
            if actual_current_version_id is not None
            else None
        )
        new_version = version_by_id.get(version_id) if version_id is not None else None
        catalog = select_visual_override_candidate(
            plan,
            inspection.value.catalog,
            shot_id=shot_id,
            version_id=version_id,
            expected_selection_revision=expected_selection_revision,
            expected_current_version_id=expected_current_version_id,
        )
        impact = classify_visual_selection_change(
            shot_id=shot_id,
            old_version=old_version,
            new_version=new_version,
        )
        after_manifest = build_effective_visual_override_manifest(plan, catalog)
        transition = build_visual_selection_transition(
            plan=plan,
            before_state=inspection.value,
            after_catalog=catalog,
            after_manifest=after_manifest,
            impact=impact,
        )
        if len(inspection.value.selection_transitions) >= 512:
            raise DramaVisualOverrideError(
                "visual override transition receipt ledger is full"
            )
        desired = build_visual_override_state(
            plan,
            catalog,
            selection_transitions=[
                *inspection.value.selection_transitions,
                transition,
            ],
        )
        persisted = _persist_for_plan(
            workspace,
            plan=plan,
            state=desired,
            target_token=inspection.target_token,
        )
        return build_visual_selection_result(
            persisted,
            transition_id=transition.transition_id,
        )


def _transition_matches_selection_request(
    transition: VisualOverrideSelectionTransition | None,
    *,
    shot_id: str,
    version_id: str | None,
    expected_selection_revision: int,
    expected_current_version_id: str | None,
) -> bool:
    if transition is None:
        return False
    old_id = (
        transition.impact.old_version.version_id
        if transition.impact.old_version is not None
        else None
    )
    new_id = (
        transition.impact.new_version.version_id
        if transition.impact.new_version is not None
        else None
    )
    return (
        transition.impact.shot_id == shot_id
        and transition.before_selection_revision == expected_selection_revision
        and old_id == expected_current_version_id
        and new_id == version_id
    )


def load_last_visual_selection_result(
    workspace: str,
    *,
    episode_no: int = 1,
) -> VisualOverrideSelectionResult:
    inspection = inspect_visual_override_state(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.value is None:
        raise DramaVisualOverrideError(
            f"visual override state is not fresh: {inspection.state}"
        )
    if not inspection.value.selection_transitions:
        raise DramaVisualOverrideError(
            "visual override state has no selection transition"
        )
    transition = inspection.value.selection_transitions[-1]
    return build_visual_selection_result(
        inspection.value,
        transition_id=transition.transition_id,
    )


def acknowledge_visual_selection_transition(
    workspace: str,
    *,
    transition_id: str,
    episode_no: int = 1,
) -> VisualOverrideState:
    if not isinstance(transition_id, str) or re.fullmatch(
        r"vot_[0-9a-f]{24}",
        transition_id,
    ) is None:
        raise ValueError("visual override transition id is invalid")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), _visual_override_write_lock():
        inspection = inspect_visual_override_state(workspace, episode_no=number)
        if inspection.state != "fresh" or inspection.value is None:
            raise DramaVisualOverrideError(
                f"visual override state is not acknowledgeable: {inspection.state}"
            )
        if inspection.target_token is None:
            raise DramaVisualOverrideError(
                "visual override inspection token is unavailable"
            )
        remaining = [
            item
            for item in inspection.value.selection_transitions
            if item.transition_id != transition_id
        ]
        if len(remaining) == len(inspection.value.selection_transitions):
            return inspection.value
        plan = load_fresh_render_plan(workspace, episode_no=number)
        desired = build_visual_override_state(
            plan,
            inspection.value.catalog,
            selection_transitions=remaining,
        )
        return _persist_for_plan(
            workspace,
            plan=plan,
            state=desired,
            target_token=inspection.target_token,
        )


def reconcile_visual_override_state(
    workspace: str,
    *,
    episode_no: int = 1,
) -> VisualOverrideState:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), _visual_override_write_lock():
        inspection = inspect_visual_override_state(workspace, episode_no=number)
        if inspection.state == "fresh" and inspection.value is not None:
            return inspection.value
        if inspection.state != "stale" or inspection.value is None:
            raise DramaVisualOverrideError(
                f"visual override state is not reconcilable: {inspection.state}"
            )
        if inspection.target_token is None:
            raise DramaVisualOverrideError(
                "visual override inspection token is unavailable"
            )
        plan = load_fresh_render_plan(workspace, episode_no=number)
        shot_by_id = {item.shot_id: item for item in plan.shots}
        versions = [
            item
            for item in inspection.value.catalog.versions
            if item.shot_id in shot_by_id
            and item.source_fingerprint
            == shot_by_id[item.shot_id].source_fingerprint
        ]
        valid_ids = {item.version_id for item in versions}
        selections = [
            item
            for item in inspection.value.catalog.selections
            if item.version_id in valid_ids
        ]
        revision = inspection.value.catalog.selection_revision
        if revision >= 2_147_483_647:
            raise DramaVisualOverrideError(
                "visual override selection revision exhausted"
            )
        catalog = build_visual_override_catalog(
            plan,
            versions=versions,
            selections=selections,
            selection_revision=revision + 1,
        )
        desired = build_visual_override_state(plan, catalog)
        return _persist_for_plan(
            workspace,
            plan=plan,
            state=desired,
            target_token=inspection.target_token,
        )


def load_fresh_visual_override_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeVisualOverrideManifest:
    inspection = inspect_visual_override_state(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.value is None:
        raise DramaVisualOverrideError(
            f"visual override state is not fresh: {inspection.state}"
        )
    return inspection.value.manifest
