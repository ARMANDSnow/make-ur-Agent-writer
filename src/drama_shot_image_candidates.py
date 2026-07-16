"""Pure C2 shot-image candidate, selection, lineage, and coverage logic."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Literal, Mapping

from .drama_schemas import (
    DirectShotImageBinding,
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    FirstShotImageBinding,
    NoTailShotImageBinding,
    PreviousTailShotImageBinding,
    ShotImageArtifact,
    ShotImageCandidate,
    ShotImageCandidatePool,
    ShotImageCoverageReport,
    TailShotImageBinding,
)
from .schemas import model_to_dict


class DramaShotImageCandidateError(ValueError):
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


def _as_plan(value: EpisodeShotImagePlan | Mapping[str, Any]) -> EpisodeShotImagePlan:
    return value if isinstance(value, EpisodeShotImagePlan) else EpisodeShotImagePlan(**value)


def _as_manifest(
    value: EpisodeShotImageCandidateManifest | Mapping[str, Any],
) -> EpisodeShotImageCandidateManifest:
    return (
        value
        if isinstance(value, EpisodeShotImageCandidateManifest)
        else EpisodeShotImageCandidateManifest(**value)
    )


def _pool_payload(
    *,
    shot_id: str,
    source_status: str,
    current_request_fingerprint: str,
    candidates: list[ShotImageCandidate],
    selection_revision: int,
    tail_binding_revision: int,
    last_selection_request_fingerprint: str | None,
    first_binding: FirstShotImageBinding | None,
    tail_binding: TailShotImageBinding,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shot_id": shot_id,
        "source_status": source_status,
        "current_request_fingerprint": current_request_fingerprint,
        "candidates": [model_to_dict(item) for item in candidates],
        "selection_revision": selection_revision,
        "tail_binding_revision": tail_binding_revision,
        "last_selection_request_fingerprint": last_selection_request_fingerprint,
        "first_binding": (
            model_to_dict(first_binding) if first_binding is not None else None
        ),
        "tail_binding": model_to_dict(tail_binding),
    }
    payload["pool_fingerprint"] = _sha256(payload)
    return payload


def _manifest_payload(
    *,
    season_no: int,
    episode_no: int,
    source_plan_fingerprint: str,
    shots: list[ShotImageCandidatePool],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-image-candidates-v1",
        "season_no": season_no,
        "episode_no": episode_no,
        "source_plan_fingerprint": source_plan_fingerprint,
        "shots": [model_to_dict(item) for item in shots],
    }
    payload["manifest_fingerprint"] = _sha256(payload)
    return payload


def _build_pool(
    *,
    shot_id: str,
    source_status: str,
    current_request_fingerprint: str,
    candidates: list[ShotImageCandidate] | None = None,
    selection_revision: int = 0,
    tail_binding_revision: int = 0,
    last_selection_request_fingerprint: str | None = None,
    first_binding: FirstShotImageBinding | None = None,
    tail_binding: TailShotImageBinding | None = None,
) -> ShotImageCandidatePool:
    payload = _pool_payload(
        shot_id=shot_id,
        source_status=source_status,
        current_request_fingerprint=current_request_fingerprint,
        candidates=list(candidates or []),
        selection_revision=selection_revision,
        tail_binding_revision=tail_binding_revision,
        last_selection_request_fingerprint=last_selection_request_fingerprint,
        first_binding=first_binding,
        tail_binding=tail_binding or NoTailShotImageBinding(),
    )
    return ShotImageCandidatePool(**payload)


def _build_manifest(
    plan: EpisodeShotImagePlan,
    shots: list[ShotImageCandidatePool],
) -> EpisodeShotImageCandidateManifest:
    return EpisodeShotImageCandidateManifest(
        **_manifest_payload(
            season_no=plan.season_no,
            episode_no=plan.episode_no,
            source_plan_fingerprint=plan.plan_fingerprint,
            shots=shots,
        )
    )


def _assert_manifest_identity(
    manifest: EpisodeShotImageCandidateManifest,
    plan: EpisodeShotImagePlan,
) -> None:
    if (
        manifest.season_no != plan.season_no
        or manifest.episode_no != plan.episode_no
    ):
        raise DramaShotImageCandidateError("shot image manifest belongs to another episode")


def _assert_current_manifest(
    manifest: EpisodeShotImageCandidateManifest,
    plan: EpisodeShotImagePlan,
) -> None:
    _assert_manifest_identity(manifest, plan)
    if manifest.source_plan_fingerprint != plan.plan_fingerprint:
        raise DramaShotImageCandidateError("shot image manifest must be reconciled first")
    if [item.shot_id for item in manifest.shots] != [
        item.shot_id for item in plan.shot_specs
    ]:
        raise DramaShotImageCandidateError("shot image manifest shot order is stale")
    for pool, spec in zip(manifest.shots, plan.shot_specs):
        if (
            pool.current_request_fingerprint != spec.request_fingerprint
            or pool.source_status != spec.status
        ):
            raise DramaShotImageCandidateError("shot image manifest request is stale")


def _candidate_basis(
    *,
    plan: EpisodeShotImagePlan,
    shot_id: str,
    request_fingerprint: str,
    artifact_sha256: str,
    artifact_size_bytes: int,
    width: int,
    height: int,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "shot_id": shot_id,
        "source_plan_fingerprint": plan.plan_fingerprint,
        "request_fingerprint": request_fingerprint,
        "source_kind": "local_png",
        "artifact": {
            "media_type": "image/png",
            "sha256": artifact_sha256,
            "size_bytes": artifact_size_bytes,
            "width": width,
            "height": height,
        },
    }


def build_episode_shot_image_candidate_manifest(
    plan: EpisodeShotImagePlan | Mapping[str, Any],
) -> EpisodeShotImageCandidateManifest:
    current = _as_plan(plan)
    shots = [
        _build_pool(
            shot_id=spec.shot_id,
            source_status=spec.status,
            current_request_fingerprint=spec.request_fingerprint,
        )
        for spec in current.shot_specs
    ]
    return _build_manifest(current, shots)


def build_shot_image_candidate(
    plan: EpisodeShotImagePlan | Mapping[str, Any],
    *,
    shot_id: str,
    artifact_sha256: str,
    artifact_size_bytes: int,
    width: int,
    height: int,
) -> ShotImageCandidate:
    current = _as_plan(plan)
    spec = next((item for item in current.shot_specs if item.shot_id == shot_id), None)
    if spec is None:
        raise DramaShotImageCandidateError("shot image candidate uses an unknown shot")
    if spec.status != "assembled":
        raise DramaShotImageCandidateError("blocked shot cannot accept image candidates")
    basis = _candidate_basis(
        plan=current,
        shot_id=shot_id,
        request_fingerprint=spec.request_fingerprint,
        artifact_sha256=artifact_sha256,
        artifact_size_bytes=artifact_size_bytes,
        width=width,
        height=height,
    )
    fingerprint = _sha256(basis)
    candidate_id = f"sic_{fingerprint[:24]}"
    artifact = ShotImageArtifact(
        path=(
            f"outputs/episodes/episode_{current.episode_no:02d}.shot_images/"
            f"{shot_id}/{candidate_id}.png"
        ),
        **basis["artifact"],
    )
    return ShotImageCandidate(
        candidate_id=candidate_id,
        season_no=current.season_no,
        episode_no=current.episode_no,
        shot_id=shot_id,
        source_plan_fingerprint=current.plan_fingerprint,
        request_fingerprint=spec.request_fingerprint,
        source_kind="local_png",
        artifact=artifact,
        candidate_fingerprint=fingerprint,
    )


def append_shot_image_candidate(
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotImagePlan | Mapping[str, Any],
    candidate: ShotImageCandidate | Mapping[str, Any],
    *,
    expected_manifest_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    item = candidate if isinstance(candidate, ShotImageCandidate) else ShotImageCandidate(**candidate)
    _assert_current_manifest(stored, current)
    if (
        item.season_no != current.season_no
        or item.episode_no != current.episode_no
        or item.source_plan_fingerprint != current.plan_fingerprint
    ):
        raise DramaShotImageCandidateError("shot image candidate source is stale")
    shots = list(stored.shots)
    index = next((i for i, pool in enumerate(shots) if pool.shot_id == item.shot_id), -1)
    if index < 0:
        raise DramaShotImageCandidateError("shot image candidate uses an unknown shot")
    pool = shots[index]
    if pool.source_status != "assembled" or item.request_fingerprint != pool.current_request_fingerprint:
        raise DramaShotImageCandidateError("shot image candidate request is stale")
    previous = next(
        (existing for existing in pool.candidates if existing.candidate_id == item.candidate_id),
        None,
    )
    if previous is not None:
        if previous != item:
            raise DramaShotImageCandidateError("shot image candidate id collision")
        return stored
    if expected_manifest_fingerprint != stored.manifest_fingerprint:
        raise DramaShotImageCandidateError("shot image manifest changed; refresh before append")
    if len(pool.candidates) >= 32:
        raise DramaShotImageCandidateError("shot image candidate limit reached")
    shots[index] = _build_pool(
        shot_id=pool.shot_id,
        source_status=pool.source_status,
        current_request_fingerprint=pool.current_request_fingerprint,
        candidates=[*pool.candidates, item],
        selection_revision=pool.selection_revision,
        tail_binding_revision=pool.tail_binding_revision,
        last_selection_request_fingerprint=pool.last_selection_request_fingerprint,
        first_binding=pool.first_binding,
        tail_binding=pool.tail_binding,
    )
    return _build_manifest(current, shots)


def _binding_payload(binding: Any) -> Any:
    if binding is None:
        return None
    if isinstance(binding, Mapping):
        return dict(binding)
    return model_to_dict(binding)


def _selection_request_fingerprint(
    *,
    shot_id: str,
    frame: str,
    expected_selection_revision: int,
    expected_current_binding: Any,
    desired_binding: Any,
    expected_manifest_fingerprint: str,
) -> str:
    return _sha256(
        {
            "operation": "select-shot-image-frame-v1",
            "shot_id": shot_id,
            "frame": frame,
            "expected_selection_revision": expected_selection_revision,
            "expected_current_binding": expected_current_binding,
            "desired_binding": desired_binding,
            "expected_manifest_fingerprint": expected_manifest_fingerprint,
        }
    )


def _parse_first_binding(value: Any) -> FirstShotImageBinding | None:
    if value is None:
        return None
    if isinstance(value, (DirectShotImageBinding, PreviousTailShotImageBinding)):
        return value
    if not isinstance(value, Mapping):
        raise DramaShotImageCandidateError("first binding is invalid")
    if value.get("kind") == "direct":
        return DirectShotImageBinding(**value)
    if value.get("kind") == "previous_tail":
        return PreviousTailShotImageBinding(**value)
    raise DramaShotImageCandidateError("first binding is invalid")


def _parse_tail_binding(value: Any) -> TailShotImageBinding:
    if isinstance(value, (DirectShotImageBinding, NoTailShotImageBinding)):
        return value
    if not isinstance(value, Mapping):
        raise DramaShotImageCandidateError("tail binding is invalid")
    if value.get("kind") == "direct":
        return DirectShotImageBinding(**value)
    if value.get("kind") == "none":
        return NoTailShotImageBinding(**value)
    raise DramaShotImageCandidateError("tail binding is invalid")


def select_shot_image_frame(
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotImagePlan | Mapping[str, Any],
    *,
    shot_id: str,
    frame: Literal["first", "tail"],
    binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_binding: FirstShotImageBinding | TailShotImageBinding | Mapping[str, Any] | None,
    expected_manifest_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    if frame not in {"first", "tail"}:
        raise DramaShotImageCandidateError("shot image frame is invalid")
    if (
        not isinstance(expected_selection_revision, int)
        or isinstance(expected_selection_revision, bool)
        or not 0 <= expected_selection_revision <= 2_147_483_647
    ):
        raise DramaShotImageCandidateError(
            "selection revision must be a bounded strict integer"
        )
    _assert_current_manifest(stored, current)
    shots = list(stored.shots)
    index = next((i for i, pool in enumerate(shots) if pool.shot_id == shot_id), -1)
    if index < 0:
        raise DramaShotImageCandidateError("shot image selection uses an unknown shot")
    pool = shots[index]
    if pool.source_status != "assembled":
        raise DramaShotImageCandidateError("blocked shot cannot select image candidates")
    current_binding = pool.first_binding if frame == "first" else pool.tail_binding
    desired = _parse_first_binding(binding) if frame == "first" else _parse_tail_binding(binding)
    candidates = {item.candidate_id: item for item in pool.candidates}
    if isinstance(desired, DirectShotImageBinding):
        candidate = candidates.get(desired.candidate_id)
        if (
            candidate is None
            or candidate.candidate_fingerprint != desired.candidate_fingerprint
            or candidate.request_fingerprint != pool.current_request_fingerprint
        ):
            raise DramaShotImageCandidateError("shot image selection is not a fresh exact candidate")
    if isinstance(desired, PreviousTailShotImageBinding):
        if frame != "first" or index == 0:
            raise DramaShotImageCandidateError("previous tail lineage is invalid")
        previous_pool = shots[index - 1]
        previous_tail = previous_pool.tail_binding
        if (
            desired.source_shot_id != previous_pool.shot_id
            or desired.source_tail_revision != previous_pool.tail_binding_revision
            or desired.target_request_fingerprint
            != pool.current_request_fingerprint
            or not isinstance(previous_tail, DirectShotImageBinding)
            or previous_tail.candidate_id != desired.candidate_id
            or previous_tail.candidate_fingerprint != desired.candidate_fingerprint
        ):
            raise DramaShotImageCandidateError("previous tail lineage is not current")
        previous_candidate = next(
            (
                item
                for item in previous_pool.candidates
                if item.candidate_id == desired.candidate_id
            ),
            None,
        )
        if (
            previous_candidate is None
            or previous_candidate.candidate_fingerprint
            != desired.candidate_fingerprint
            or previous_candidate.request_fingerprint
            != previous_pool.current_request_fingerprint
        ):
            raise DramaShotImageCandidateError("previous tail candidate is stale")
    current_payload = _binding_payload(current_binding)
    desired_payload = _binding_payload(desired)
    expected_payload = _binding_payload(expected_current_binding)
    request_fingerprint = _selection_request_fingerprint(
        shot_id=shot_id,
        frame=frame,
        expected_selection_revision=expected_selection_revision,
        expected_current_binding=expected_payload,
        desired_binding=desired_payload,
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
        raise DramaShotImageCandidateError("shot image manifest changed; refresh before selection")
    if pool.selection_revision != expected_selection_revision:
        raise DramaShotImageCandidateError("shot image selection revision changed")
    if current_payload != expected_payload:
        raise DramaShotImageCandidateError("shot image current binding changed")
    shots[index] = _build_pool(
        shot_id=pool.shot_id,
        source_status=pool.source_status,
        current_request_fingerprint=pool.current_request_fingerprint,
        candidates=list(pool.candidates),
        selection_revision=pool.selection_revision + 1,
        tail_binding_revision=(
            pool.tail_binding_revision + 1
            if frame == "tail"
            else pool.tail_binding_revision
        ),
        last_selection_request_fingerprint=request_fingerprint,
        first_binding=(desired if frame == "first" else pool.first_binding),
        tail_binding=(desired if frame == "tail" else pool.tail_binding),
    )
    return _build_manifest(current, shots)


def reconcile_shot_image_candidate_manifest(
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotImagePlan | Mapping[str, Any],
    *,
    expected_manifest_fingerprint: str,
) -> EpisodeShotImageCandidateManifest:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    if expected_manifest_fingerprint != stored.manifest_fingerprint:
        raise DramaShotImageCandidateError("shot image manifest changed; refresh before reconcile")
    _assert_manifest_identity(stored, current)
    previous = {item.shot_id: item for item in stored.shots}
    shots: list[ShotImageCandidatePool] = []
    for spec in current.shot_specs:
        old = previous.get(spec.shot_id)
        if old is None:
            shots.append(
                _build_pool(
                    shot_id=spec.shot_id,
                    source_status=spec.status,
                    current_request_fingerprint=spec.request_fingerprint,
                )
            )
            continue
        shots.append(
            _build_pool(
                shot_id=spec.shot_id,
                source_status=spec.status,
                current_request_fingerprint=spec.request_fingerprint,
                candidates=list(old.candidates),
                selection_revision=old.selection_revision,
                tail_binding_revision=old.tail_binding_revision,
                last_selection_request_fingerprint=(
                    old.last_selection_request_fingerprint
                ),
                first_binding=old.first_binding,
                tail_binding=old.tail_binding,
            )
        )
    return _build_manifest(current, shots)


def shot_image_candidate_affected_ids(
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotImagePlan | Mapping[str, Any],
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
        != item.request_fingerprint
        or by_id[item.shot_id].source_status != item.status
    }
    affected.update(item.shot_id for item in stored.shots if item.shot_id not in current_ids)
    stored_order = [item.shot_id for item in stored.shots]
    current_order = [item.shot_id for item in current.shot_specs]
    stored_previous = {
        shot_id: (stored_order[index - 1] if index else None)
        for index, shot_id in enumerate(stored_order)
    }
    current_previous = {
        shot_id: (current_order[index - 1] if index else None)
        for index, shot_id in enumerate(current_order)
    }
    for shot_id in set(stored_previous) & set(current_previous):
        if stored_previous[shot_id] != current_previous[shot_id]:
            affected.add(shot_id)
    return sorted(affected)


def shot_image_coverage(
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    plan: EpisodeShotImagePlan | Mapping[str, Any],
) -> ShotImageCoverageReport:
    stored = _as_manifest(manifest)
    current = _as_plan(plan)
    _assert_manifest_identity(stored, current)
    pools = {item.shot_id: item for item in stored.shots}
    required = [item.shot_id for item in current.shot_specs]
    covered: list[str] = []
    missing: list[str] = []
    blocked: list[str] = []
    stale: list[str] = []
    broken: list[str] = []
    ordered_pools = stored.shots
    stored_index = {item.shot_id: index for index, item in enumerate(ordered_pools)}
    for spec in current.shot_specs:
        pool = pools.get(spec.shot_id)
        if spec.status != "assembled":
            blocked.append(spec.shot_id)
            continue
        if pool is None or pool.first_binding is None:
            missing.append(spec.shot_id)
            continue
        if (
            pool.current_request_fingerprint != spec.request_fingerprint
            or pool.source_status != spec.status
        ):
            stale.append(spec.shot_id)
            continue
        binding = pool.first_binding
        if isinstance(binding, DirectShotImageBinding):
            candidate = next(
                (item for item in pool.candidates if item.candidate_id == binding.candidate_id),
                None,
            )
            if (
                candidate is None
                or candidate.candidate_fingerprint != binding.candidate_fingerprint
                or candidate.request_fingerprint != spec.request_fingerprint
            ):
                stale.append(spec.shot_id)
                continue
            covered.append(spec.shot_id)
            continue
        index = stored_index.get(spec.shot_id, -1)
        if index <= 0 or binding.source_shot_id != ordered_pools[index - 1].shot_id:
            broken.append(spec.shot_id)
            continue
        previous = ordered_pools[index - 1]
        previous_tail = previous.tail_binding
        previous_candidate = next(
            (
                item
                for item in previous.candidates
                if item.candidate_id == binding.candidate_id
            ),
            None,
        )
        if (
            not isinstance(previous_tail, DirectShotImageBinding)
            or binding.source_tail_revision != previous.tail_binding_revision
            or binding.target_request_fingerprint != spec.request_fingerprint
            or previous_tail.candidate_id != binding.candidate_id
            or previous_tail.candidate_fingerprint != binding.candidate_fingerprint
            or previous_candidate is None
            or previous_candidate.candidate_fingerprint != binding.candidate_fingerprint
            or previous_candidate.request_fingerprint
            != previous.current_request_fingerprint
        ):
            broken.append(spec.shot_id)
            continue
        covered.append(spec.shot_id)
    source_plan_matches = (
        stored.source_plan_fingerprint == current.plan_fingerprint
        and [item.shot_id for item in stored.shots] == required
    )
    if blocked:
        status = "blocked_source"
    elif broken or stale or not source_plan_matches:
        status = "stale"
    elif missing:
        status = "incomplete"
    else:
        status = "ready"
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "episode_no": current.episode_no,
        "source_plan_fingerprint": current.plan_fingerprint,
        "source_plan_matches": source_plan_matches,
        "status": status,
        "required_shot_ids": required,
        "covered_shot_ids": covered,
        "missing_first_shot_ids": missing,
        "blocked_source_shot_ids": blocked,
        "stale_candidate_shot_ids": stale,
        "broken_lineage_shot_ids": broken,
    }
    payload["coverage_fingerprint"] = _sha256(payload)
    return ShotImageCoverageReport(**payload)
