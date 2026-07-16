"""Pure D4 continuity projection and production-compose gate."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .drama_schemas import (
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoContinuityReport,
)
from .drama_shot_video_candidates import shot_video_coverage


class DramaShotVideoContinuityError(ValueError):
    """Bounded public error for invalid or non-production D4 inputs."""


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _refs_by_kind(spec: Any, kind: str) -> dict[str, str]:
    return {
        item.asset_id: item.asset_version_id
        for item in spec.ordered_references
        if item.kind == kind
    }


def _changed_shared_version(before: Any, after: Any, kind: str) -> bool:
    left = _refs_by_kind(before, kind)
    right = _refs_by_kind(after, kind)
    return any(left[asset_id] != right[asset_id] for asset_id in left.keys() & right.keys())


def _lineage_is_exact(before: Any, after: Any) -> bool:
    first = after.first_frame
    if first.binding_kind != "previous_tail":
        return True
    tail = before.tail_frame
    return bool(
        tail is not None
        and first.source_shot_id == before.shot_id
        and first.candidate_id == tail.candidate_id
        and first.candidate_fingerprint == tail.candidate_fingerprint
        and first.candidate_request_fingerprint == tail.candidate_request_fingerprint
        and first.artifact == tail.artifact
        and first.source_tail_revision == tail.source_tail_revision
        and first.target_request_fingerprint == after.shot_image_request_fingerprint
    )


def _bounded_shot_ids(value: Sequence[str], label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) > 100
        or len(value) != len(set(value))
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"shot_[0-9a-f]{24}", item) is None
            for item in value
        )
    ):
        raise DramaShotVideoContinuityError(f"{label} was rejected")
    return tuple(value)


def _selected_bindings_fingerprint(
    plan: EpisodeShotVideoPlan,
    manifest: EpisodeShotVideoCandidateManifest,
) -> str:
    pools = {item.shot_id: item for item in manifest.shots}
    payload: list[dict[str, Any]] = []
    for spec in plan.shot_specs:
        pool = pools.get(spec.shot_id)
        selected = pool.selected if pool is not None else None
        candidate = (
            next(
                (
                    item
                    for item in pool.candidates
                    if selected is not None
                    and item.candidate_id == selected.candidate_id
                    and item.candidate_fingerprint == selected.candidate_fingerprint
                ),
                None,
            )
            if pool is not None
            else None
        )
        payload.append(
            {
                "shot_id": spec.shot_id,
                "request_fingerprint": spec.spec_fingerprint,
                "selection_revision": pool.selection_revision if pool is not None else None,
                "candidate_id": candidate.candidate_id if candidate is not None else None,
                "candidate_fingerprint": (
                    candidate.candidate_fingerprint if candidate is not None else None
                ),
                "artifact_sha256": (
                    candidate.artifact.sha256 if candidate is not None else None
                ),
            }
        )
    return _sha256(payload)


def build_shot_video_continuity_report(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    *,
    invalid_artifact_shot_ids: Sequence[str] = (),
    blocked_source_shot_ids: Sequence[str] = (),
) -> ShotVideoContinuityReport:
    """Project D1+D2 facts into one content-addressed D4 report."""

    try:
        current = plan if isinstance(plan, EpisodeShotVideoPlan) else EpisodeShotVideoPlan(**plan)
        stored = (
            manifest
            if isinstance(manifest, EpisodeShotVideoCandidateManifest)
            else EpisodeShotVideoCandidateManifest(**manifest)
        )
        invalid_ids = _bounded_shot_ids(
            invalid_artifact_shot_ids, "invalid artifact shot ids"
        )
        blocked_ids = _bounded_shot_ids(
            blocked_source_shot_ids, "blocked source shot ids"
        )
        coverage = shot_video_coverage(
            stored,
            current,
            invalid_artifact_shot_ids=invalid_ids,
            blocked_source_shot_ids=blocked_ids,
        )
        broken_lineage: list[str] = []
        character_changes: list[str] = []
        scene_changes: list[str] = []
        camera_reversals: list[str] = []
        reverse_pairs = {("推", "拉"), ("拉", "推")}
        for before, after in zip(current.shot_specs, current.shot_specs[1:]):
            if not _lineage_is_exact(before, after):
                broken_lineage.append(after.shot_id)
            if _changed_shared_version(before, after, "character"):
                character_changes.append(after.shot_id)
            if _changed_shared_version(before, after, "scene"):
                scene_changes.append(after.shot_id)
            if (before.camera_movement, after.camera_movement) in reverse_pairs:
                camera_reversals.append(after.shot_id)

        hard_blocked = [
            *coverage.missing_selection_shot_ids,
            *coverage.stale_candidate_shot_ids,
            *coverage.invalid_artifact_shot_ids,
            *coverage.blocked_source_shot_ids,
        ]
        blocked = list(dict.fromkeys(hard_blocked))
        degraded = list(coverage.non_production_shot_ids)
        status = (
            "blocked"
            if not coverage.source_plan_matches or blocked or broken_lineage
            else "degraded_preview"
            if degraded
            else "ready"
        )
        payload = {
            "schema_version": 1,
            "generator_version": "shot-video-continuity-v1",
            "season_no": current.season_no,
            "episode_no": current.episode_no,
            "source_plan_fingerprint": current.plan_fingerprint,
            "selected_bindings_fingerprint": _selected_bindings_fingerprint(
                current, stored
            ),
            "coverage_fingerprint": coverage.coverage_fingerprint,
            "source_plan_matches": coverage.source_plan_matches,
            "status": status,
            "ready_for_compose": status == "ready",
            "blocked_shot_ids": blocked,
            "degraded_preview_shot_ids": degraded,
            "broken_lineage_shot_ids": broken_lineage,
            "character_version_change_shot_ids": character_changes,
            "scene_version_change_shot_ids": scene_changes,
            "camera_reversal_shot_ids": camera_reversals,
        }
        payload["report_fingerprint"] = _sha256(payload)
        return ShotVideoContinuityReport(**payload)
    except DramaShotVideoContinuityError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoContinuityError(
            "shot video continuity input was rejected"
        ) from None


def _require_projected_compose_ready(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    *,
    invalid_artifact_shot_ids: Sequence[str] = (),
    blocked_source_shot_ids: Sequence[str] = (),
) -> ShotVideoContinuityReport:
    """Gate already-validated facts; production callers use the workspace entry."""

    report = build_shot_video_continuity_report(
        plan,
        manifest,
        invalid_artifact_shot_ids=invalid_artifact_shot_ids,
        blocked_source_shot_ids=blocked_source_shot_ids,
    )
    if not report.ready_for_compose:
        raise DramaShotVideoContinuityError(
            "shot video composition is not production ready"
        )
    return report


def require_workspace_production_compose_ready(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoContinuityReport:
    """Authoritative store-facing gate that validates selected MP4 bytes first."""

    try:
        from .drama_shot_video_candidate_store import (
            inspect_episode_shot_video_candidates,
        )
        from .drama_shot_video_store import load_fresh_episode_shot_video_plan
        from .web.workspace_ctx import use_workspace
        from .workspace_lock import WorkspaceLocked, acquire_write_lock

        with use_workspace(workspace):
            with acquire_write_lock(source="drama-shot-video-compose-readiness"):
                inspection = inspect_episode_shot_video_candidates(
                    workspace,
                    episode_no=episode_no,
                )
                if (
                    inspection.state != "fresh"
                    or inspection.manifest is None
                    or inspection.coverage is None
                ):
                    raise DramaShotVideoContinuityError(
                        "shot video composition is not production ready"
                    )
                plan = load_fresh_episode_shot_video_plan(
                    workspace,
                    episode_no=episode_no,
                )
                return _require_projected_compose_ready(plan, inspection.manifest)
    except WorkspaceLocked:
        raise DramaShotVideoContinuityError(
            "shot video continuity workspace is busy"
        ) from None
    except DramaShotVideoContinuityError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaShotVideoContinuityError(
            "shot video continuity workspace was rejected"
        ) from None
