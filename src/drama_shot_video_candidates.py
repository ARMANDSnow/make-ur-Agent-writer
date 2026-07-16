"""Pure D2 shot-video candidate, selection, reconcile, and coverage logic."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Sequence

from .drama_schemas import (
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoArtifact,
    ShotVideoCandidate,
    ShotVideoCandidatePool,
    ShotVideoCoverageReport,
    ShotVideoSelection,
)
from .schemas import model_to_dict


class DramaShotVideoCandidateError(ValueError):
    pass


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _as_plan(value: EpisodeShotVideoPlan | Mapping[str, Any]) -> EpisodeShotVideoPlan:
    return value if isinstance(value, EpisodeShotVideoPlan) else EpisodeShotVideoPlan(**value)


def _as_manifest(
    value: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
) -> EpisodeShotVideoCandidateManifest:
    return (
        value
        if isinstance(value, EpisodeShotVideoCandidateManifest)
        else EpisodeShotVideoCandidateManifest(**value)
    )


def _selection_payload(value: ShotVideoSelection | Mapping[str, Any] | None) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return model_to_dict(value)


def _parse_selection(
    value: ShotVideoSelection | Mapping[str, Any] | None,
) -> ShotVideoSelection | None:
    if value is None or isinstance(value, ShotVideoSelection):
        return value
    if not isinstance(value, Mapping):
        raise DramaShotVideoCandidateError("shot video selection is invalid")
    return ShotVideoSelection(**value)


def _pool_payload(
    *,
    shot_id: str,
    current_request_fingerprint: str,
    candidates: list[ShotVideoCandidate],
    selection_revision: int,
    last_selection_request_fingerprint: str | None,
    selected: ShotVideoSelection | None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shot_id": shot_id,
        "current_request_fingerprint": current_request_fingerprint,
        "candidates": [model_to_dict(item) for item in candidates],
        "selection_revision": selection_revision,
        "last_selection_request_fingerprint": last_selection_request_fingerprint,
        "selected": model_to_dict(selected) if selected is not None else None,
    }
    payload["pool_fingerprint"] = _sha256(payload)
    return payload


def _build_pool(
    *,
    shot_id: str,
    current_request_fingerprint: str,
    candidates: list[ShotVideoCandidate] | None = None,
    selection_revision: int = 0,
    last_selection_request_fingerprint: str | None = None,
    selected: ShotVideoSelection | None = None,
) -> ShotVideoCandidatePool:
    return ShotVideoCandidatePool(
        **_pool_payload(
            shot_id=shot_id,
            current_request_fingerprint=current_request_fingerprint,
            candidates=list(candidates or []),
            selection_revision=selection_revision,
            last_selection_request_fingerprint=last_selection_request_fingerprint,
            selected=selected,
        )
    )


def _manifest_payload(
    plan: EpisodeShotVideoPlan,
    shots: list[ShotVideoCandidatePool],
    retired_shots: list[ShotVideoCandidatePool] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-video-candidates-v1",
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "source_plan_fingerprint": plan.plan_fingerprint,
        "shots": [model_to_dict(item) for item in shots],
        "retired_shots": [model_to_dict(item) for item in (retired_shots or [])],
    }
    payload["manifest_fingerprint"] = _sha256(payload)
    return payload


def _build_manifest(
    plan: EpisodeShotVideoPlan,
    shots: list[ShotVideoCandidatePool],
    retired_shots: list[ShotVideoCandidatePool] | None = None,
) -> EpisodeShotVideoCandidateManifest:
    return EpisodeShotVideoCandidateManifest(
        **_manifest_payload(plan, shots, retired_shots)
    )


def _assert_manifest_identity(
    manifest: EpisodeShotVideoCandidateManifest,
    plan: EpisodeShotVideoPlan,
) -> None:
    if (
        manifest.season_no != plan.season_no
        or manifest.episode_no != plan.episode_no
    ):
        raise DramaShotVideoCandidateError(
            "shot video manifest belongs to another episode"
        )


def _assert_current_manifest(
    manifest: EpisodeShotVideoCandidateManifest,
    plan: EpisodeShotVideoPlan,
) -> None:
    _assert_manifest_identity(manifest, plan)
    if manifest.source_plan_fingerprint != plan.plan_fingerprint:
        raise DramaShotVideoCandidateError("shot video manifest must be reconciled first")
    if [item.shot_id for item in manifest.shots] != [
        item.shot_id for item in plan.shot_specs
    ]:
        raise DramaShotVideoCandidateError("shot video manifest shot order is stale")
    for pool, spec in zip(manifest.shots, plan.shot_specs):
        if pool.current_request_fingerprint != spec.spec_fingerprint:
            raise DramaShotVideoCandidateError("shot video manifest request is stale")


def build_episode_shot_video_candidate_manifest(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
) -> EpisodeShotVideoCandidateManifest:
    current = _as_plan(plan)
    return _build_manifest(
        current,
        [
            _build_pool(
                shot_id=spec.shot_id,
                current_request_fingerprint=spec.spec_fingerprint,
            )
            for spec in current.shot_specs
        ],
    )


def build_shot_video_candidate(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    *,
    shot_id: str,
    artifact_sha256: str,
    artifact_size_bytes: int,
    duration_milliseconds: int,
    width: int,
    height: int,
    has_audio_track: bool,
    is_placeholder: bool = False,
) -> ShotVideoCandidate:
    current = _as_plan(plan)
    spec = next((item for item in current.shot_specs if item.shot_id == shot_id), None)
    if spec is None:
        raise DramaShotVideoCandidateError("shot video candidate uses an unknown shot")
    basis: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": current.season_no,
        "episode_no": current.episode_no,
        "shot_id": shot_id,
        "source_plan_fingerprint": current.plan_fingerprint,
        "request_fingerprint": spec.spec_fingerprint,
        "source_kind": "local_mp4",
        "is_placeholder": is_placeholder,
        "artifact": {
            "media_type": "video/mp4",
            "sha256": artifact_sha256,
            "size_bytes": artifact_size_bytes,
            "duration_milliseconds": duration_milliseconds,
            "width": width,
            "height": height,
            "has_audio_track": has_audio_track,
        },
    }
    fingerprint = _sha256(basis)
    candidate_id = f"svc_{fingerprint[:24]}"
    artifact = ShotVideoArtifact(
        path=(
            f"outputs/episodes/episode_{current.episode_no:02d}.shot_videos/"
            f"{shot_id}/{candidate_id}.mp4"
        ),
        **basis["artifact"],
    )
    return ShotVideoCandidate(
        candidate_id=candidate_id,
        season_no=current.season_no,
        episode_no=current.episode_no,
        shot_id=shot_id,
        source_plan_fingerprint=current.plan_fingerprint,
        request_fingerprint=spec.spec_fingerprint,
        source_kind="local_mp4",
        is_placeholder=is_placeholder,
        artifact=artifact,
        candidate_fingerprint=fingerprint,
    )


def append_shot_video_candidate(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    candidate: ShotVideoCandidate | Mapping[str, Any],
    *,
    expected_manifest_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    item = (
        candidate
        if isinstance(candidate, ShotVideoCandidate)
        else ShotVideoCandidate(**candidate)
    )
    _assert_current_manifest(stored, current)
    if (
        item.season_no != current.season_no
        or item.episode_no != current.episode_no
        or item.source_plan_fingerprint != current.plan_fingerprint
    ):
        raise DramaShotVideoCandidateError("shot video candidate source is stale")
    shots = list(stored.shots)
    index = next((i for i, pool in enumerate(shots) if pool.shot_id == item.shot_id), -1)
    if index < 0:
        raise DramaShotVideoCandidateError("shot video candidate uses an unknown shot")
    pool = shots[index]
    if item.request_fingerprint != pool.current_request_fingerprint:
        raise DramaShotVideoCandidateError("shot video candidate request is stale")
    previous = next(
        (existing for existing in pool.candidates if existing.candidate_id == item.candidate_id),
        None,
    )
    if previous is not None:
        if previous != item:
            raise DramaShotVideoCandidateError("shot video candidate id collision")
        return stored
    if expected_manifest_fingerprint != stored.manifest_fingerprint:
        raise DramaShotVideoCandidateError(
            "shot video manifest changed; refresh before append"
        )
    if len(pool.candidates) >= 32:
        raise DramaShotVideoCandidateError("shot video candidate limit reached")
    shots[index] = _build_pool(
        shot_id=pool.shot_id,
        current_request_fingerprint=pool.current_request_fingerprint,
        candidates=[*pool.candidates, item],
        selection_revision=pool.selection_revision,
        last_selection_request_fingerprint=pool.last_selection_request_fingerprint,
        selected=pool.selected,
    )
    return _build_manifest(current, shots, list(stored.retired_shots))


def _selection_request_fingerprint(
    *,
    shot_id: str,
    expected_selection_revision: int,
    expected_current_selection: Any,
    desired_selection: Any,
    expected_manifest_fingerprint: str,
) -> str:
    return _sha256(
        {
            "operation": "select-shot-video-candidate-v1",
            "shot_id": shot_id,
            "expected_selection_revision": expected_selection_revision,
            "expected_current_selection": expected_current_selection,
            "desired_selection": desired_selection,
            "expected_manifest_fingerprint": expected_manifest_fingerprint,
        }
    )


def select_shot_video_candidate(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    *,
    shot_id: str,
    selection: ShotVideoSelection | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_selection: ShotVideoSelection | Mapping[str, Any] | None,
    expected_manifest_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    if (
        not isinstance(expected_selection_revision, int)
        or isinstance(expected_selection_revision, bool)
        or not 0 <= expected_selection_revision <= 2_147_483_647
    ):
        raise DramaShotVideoCandidateError(
            "selection revision must be a bounded strict integer"
        )
    _assert_current_manifest(stored, current)
    shots = list(stored.shots)
    index = next((i for i, pool in enumerate(shots) if pool.shot_id == shot_id), -1)
    if index < 0:
        raise DramaShotVideoCandidateError("shot video selection uses an unknown shot")
    pool = shots[index]
    desired = _parse_selection(selection)
    if desired is not None:
        candidate = next(
            (item for item in pool.candidates if item.candidate_id == desired.candidate_id),
            None,
        )
        if (
            candidate is None
            or candidate.candidate_fingerprint != desired.candidate_fingerprint
            or candidate.request_fingerprint != pool.current_request_fingerprint
        ):
            raise DramaShotVideoCandidateError(
                "shot video selection is not a fresh exact candidate"
            )
    current_payload = _selection_payload(pool.selected)
    desired_payload = _selection_payload(desired)
    expected_payload = _selection_payload(expected_current_selection)
    request_fingerprint = _selection_request_fingerprint(
        shot_id=shot_id,
        expected_selection_revision=expected_selection_revision,
        expected_current_selection=expected_payload,
        desired_selection=desired_payload,
        expected_manifest_fingerprint=expected_manifest_fingerprint,
    )
    if current_payload == desired_payload:
        if (
            pool.selection_revision == expected_selection_revision
            and expected_payload == current_payload
            and expected_manifest_fingerprint == stored.manifest_fingerprint
        ) or (
            pool.selection_revision == expected_selection_revision + 1
            and pool.last_selection_request_fingerprint == request_fingerprint
        ):
            return stored
    if expected_manifest_fingerprint != stored.manifest_fingerprint:
        raise DramaShotVideoCandidateError(
            "shot video manifest changed; refresh before selection"
        )
    if pool.selection_revision != expected_selection_revision:
        raise DramaShotVideoCandidateError("shot video selection revision changed")
    if current_payload != expected_payload:
        raise DramaShotVideoCandidateError("shot video current selection changed")
    shots[index] = _build_pool(
        shot_id=pool.shot_id,
        current_request_fingerprint=pool.current_request_fingerprint,
        candidates=list(pool.candidates),
        selection_revision=pool.selection_revision + 1,
        last_selection_request_fingerprint=request_fingerprint,
        selected=desired,
    )
    return _build_manifest(current, shots, list(stored.retired_shots))


def reconcile_shot_video_candidate_manifest(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    *,
    expected_manifest_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    if expected_manifest_fingerprint != stored.manifest_fingerprint:
        raise DramaShotVideoCandidateError(
            "shot video manifest changed; refresh before reconcile"
        )
    _assert_manifest_identity(stored, current)
    previous_active = {item.shot_id: item for item in stored.shots}
    previous_retired = {item.shot_id: item for item in stored.retired_shots}
    current_ids = {item.shot_id for item in current.shot_specs}
    shots: list[ShotVideoCandidatePool] = []
    for spec in current.shot_specs:
        old = previous_active.get(spec.shot_id) or previous_retired.get(spec.shot_id)
        if old is None:
            shots.append(
                _build_pool(
                    shot_id=spec.shot_id,
                    current_request_fingerprint=spec.spec_fingerprint,
                )
            )
            continue
        shots.append(
            _build_pool(
                shot_id=spec.shot_id,
                current_request_fingerprint=spec.spec_fingerprint,
                candidates=list(old.candidates),
                selection_revision=old.selection_revision,
                last_selection_request_fingerprint=(
                    old.last_selection_request_fingerprint
                ),
                selected=old.selected,
            )
        )
    retired = [
        pool
        for pool in [*stored.retired_shots, *stored.shots]
        if pool.shot_id not in current_ids
    ]
    return _build_manifest(current, shots, retired)


def shot_video_candidate_affected_ids(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
) -> list[str]:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    _assert_manifest_identity(stored, current)
    by_id = {item.shot_id: item for item in stored.shots}
    current_ids = {item.shot_id for item in current.shot_specs}
    affected = {
        item.shot_id
        for item in current.shot_specs
        if item.shot_id not in by_id
        or by_id[item.shot_id].current_request_fingerprint
        != item.spec_fingerprint
    }
    affected.update(item.shot_id for item in stored.shots if item.shot_id not in current_ids)
    return sorted(affected)


def shot_video_coverage(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    *,
    invalid_artifact_shot_ids: Sequence[str] = (),
    blocked_source_shot_ids: Sequence[str] = (),
) -> ShotVideoCoverageReport:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    _assert_manifest_identity(stored, current)
    required = [item.shot_id for item in current.shot_specs]
    invalid = set(invalid_artifact_shot_ids)
    blocked = set(blocked_source_shot_ids)
    if (
        any(not isinstance(item, str) for item in invalid | blocked)
        or not (invalid | blocked).issubset(set(required))
        or invalid & blocked
    ):
        raise DramaShotVideoCandidateError("shot video coverage input is invalid")
    pools = {item.shot_id: item for item in stored.shots}
    selected_fresh: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    invalid_ids: list[str] = []
    non_production: list[str] = []
    blocked_ids: list[str] = []
    for spec in current.shot_specs:
        shot_id = spec.shot_id
        if shot_id in blocked:
            blocked_ids.append(shot_id)
            continue
        pool = pools.get(shot_id)
        if pool is None or pool.selected is None:
            missing.append(shot_id)
            continue
        if pool.current_request_fingerprint != spec.spec_fingerprint:
            stale.append(shot_id)
            continue
        candidate = next(
            (
                item
                for item in pool.candidates
                if item.candidate_id == pool.selected.candidate_id
            ),
            None,
        )
        if (
            candidate is None
            or candidate.candidate_fingerprint
            != pool.selected.candidate_fingerprint
            or candidate.request_fingerprint != spec.spec_fingerprint
        ):
            stale.append(shot_id)
            continue
        if shot_id in invalid:
            invalid_ids.append(shot_id)
        elif candidate.is_placeholder:
            non_production.append(shot_id)
        else:
            selected_fresh.append(shot_id)
    source_matches = (
        stored.source_plan_fingerprint == current.plan_fingerprint
        and [item.shot_id for item in stored.shots] == required
    )
    if blocked_ids:
        status = "blocked_source"
    elif stale or not source_matches:
        status = "stale"
    elif invalid_ids or non_production:
        status = "invalid"
    elif missing:
        status = "incomplete"
    else:
        status = "ready"
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "episode_no": current.episode_no,
        "source_plan_fingerprint": current.plan_fingerprint,
        "source_plan_matches": source_matches,
        "status": status,
        "required_shot_ids": required,
        "selected_fresh_shot_ids": selected_fresh,
        "missing_selection_shot_ids": missing,
        "stale_candidate_shot_ids": stale,
        "invalid_artifact_shot_ids": invalid_ids,
        "non_production_shot_ids": non_production,
        "blocked_source_shot_ids": blocked_ids,
    }
    payload["coverage_fingerprint"] = _sha256(payload)
    return ShotVideoCoverageReport(**payload)


def blocked_shot_video_coverage(
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
) -> ShotVideoCoverageReport:
    """Project stable per-shot blockers when D1 cannot currently be loaded."""

    stored = _as_manifest(manifest)
    required = [item.shot_id for item in stored.shots]
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "episode_no": stored.episode_no,
        "source_plan_fingerprint": stored.source_plan_fingerprint,
        "source_plan_matches": False,
        "status": "blocked_source",
        "required_shot_ids": required,
        "selected_fresh_shot_ids": [],
        "missing_selection_shot_ids": [],
        "stale_candidate_shot_ids": [],
        "invalid_artifact_shot_ids": [],
        "non_production_shot_ids": [],
        "blocked_source_shot_ids": required,
    }
    payload["coverage_fingerprint"] = _sha256(payload)
    return ShotVideoCoverageReport(**payload)
