"""Pure stage-D1 shot-video plan assembly with no file or network access."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from .drama_schemas import (
    DirectShotImageBinding,
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    EpisodeShotVideoPlan,
    NoTailShotImageBinding,
    PreviousTailShotImageBinding,
    RenderPlan,
    ShotImageCandidate,
    ShotImageCandidatePool,
    ShotVideoFrameRef,
    ShotVideoRequestSpec,
)
from .drama_shot_image_candidates import shot_image_coverage
from .schemas import model_to_dict


class DramaShotVideoError(ValueError):
    """Bounded public error for caller-controlled D1 inputs."""


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _raise_public_error(operation: str) -> None:
    raise DramaShotVideoError(f"shot video {operation} was rejected")


def _candidate_for_binding(
    pool: ShotImageCandidatePool,
    binding: DirectShotImageBinding | PreviousTailShotImageBinding,
) -> ShotImageCandidate:
    matches = [
        item
        for item in pool.candidates
        if item.candidate_id == binding.candidate_id
        and item.candidate_fingerprint == binding.candidate_fingerprint
    ]
    if len(matches) != 1:
        raise ValueError("selected frame is not an exact candidate")
    return matches[0]


def _frame_ref(
    *,
    frame_role: str,
    binding_kind: str,
    candidate: ShotImageCandidate,
    source_shot_id: str,
    selection_revision: int,
    source_tail_revision: int | None = None,
    target_request_fingerprint: str | None = None,
) -> ShotVideoFrameRef:
    payload: Dict[str, Any] = {
        "frame_role": frame_role,
        "binding_kind": binding_kind,
        "season_no": candidate.season_no,
        "episode_no": candidate.episode_no,
        "source_shot_id": source_shot_id,
        "candidate_source_plan_fingerprint": candidate.source_plan_fingerprint,
        "candidate_request_fingerprint": candidate.request_fingerprint,
        "candidate_id": candidate.candidate_id,
        "candidate_fingerprint": candidate.candidate_fingerprint,
        "artifact": model_to_dict(candidate.artifact),
        "selection_revision": selection_revision,
        "source_tail_revision": source_tail_revision,
        "target_request_fingerprint": target_request_fingerprint,
    }
    payload["frame_fingerprint"] = _sha256(payload)
    return ShotVideoFrameRef(**payload)


def _build_episode_shot_video_plan_impl(
    render_plan: RenderPlan | Dict[str, Any],
    shot_image_plan: EpisodeShotImagePlan | Dict[str, Any],
    candidate_manifest: EpisodeShotImageCandidateManifest | Dict[str, Any],
) -> EpisodeShotVideoPlan:
    render = (
        render_plan
        if isinstance(render_plan, RenderPlan)
        else RenderPlan(**render_plan)
    )
    image_plan = (
        shot_image_plan
        if isinstance(shot_image_plan, EpisodeShotImagePlan)
        else EpisodeShotImagePlan(**shot_image_plan)
    )
    manifest = (
        candidate_manifest
        if isinstance(candidate_manifest, EpisodeShotImageCandidateManifest)
        else EpisodeShotImageCandidateManifest(**candidate_manifest)
    )
    if (
        render.season_no != image_plan.season_no
        or render.season_no != manifest.season_no
        or render.episode_no != image_plan.episode_no
        or render.episode_no != manifest.episode_no
        or image_plan.render_plan_fingerprint != render.plan_fingerprint
        or manifest.source_plan_fingerprint != image_plan.plan_fingerprint
    ):
        raise ValueError("shot video sources do not share one episode lineage")

    coverage = shot_image_coverage(manifest, image_plan)
    if coverage.status != "ready":
        raise ValueError("shot image coverage is not ready")

    render_ids = [item.shot_id for item in render.shots]
    image_ids = [item.shot_id for item in image_plan.shot_specs]
    pool_ids = [item.shot_id for item in manifest.shots]
    if render_ids != image_ids or render_ids != pool_ids:
        raise ValueError("shot video sources do not preserve stable shot order")

    image_specs = {item.shot_id: item for item in image_plan.shot_specs}
    pools = {item.shot_id: item for item in manifest.shots}
    video_specs: list[ShotVideoRequestSpec] = []
    for index, render_shot in enumerate(render.shots):
        image_spec = image_specs[render_shot.shot_id]
        pool = pools[render_shot.shot_id]
        if (
            image_spec.status != "assembled"
            or image_spec.source_fingerprint != render_shot.source_fingerprint
            or pool.source_status != "assembled"
            or pool.current_request_fingerprint != image_spec.request_fingerprint
            or pool.first_binding is None
            or pool.selection_revision < 1
        ):
            raise ValueError("shot video source is not assembled and selected")

        first_binding = pool.first_binding
        if isinstance(first_binding, DirectShotImageBinding):
            first_candidate = _candidate_for_binding(pool, first_binding)
            first_frame = _frame_ref(
                frame_role="first",
                binding_kind="direct",
                candidate=first_candidate,
                source_shot_id=pool.shot_id,
                selection_revision=pool.selection_revision,
            )
        elif isinstance(first_binding, PreviousTailShotImageBinding):
            if index == 0 or first_binding.source_shot_id != render_ids[index - 1]:
                raise ValueError("previous-tail source is not the immediately prior shot")
            source_pool = pools[first_binding.source_shot_id]
            source_tail = source_pool.tail_binding
            if (
                not isinstance(source_tail, DirectShotImageBinding)
                or source_pool.tail_binding_revision
                != first_binding.source_tail_revision
                or source_tail.candidate_id != first_binding.candidate_id
                or source_tail.candidate_fingerprint
                != first_binding.candidate_fingerprint
                or first_binding.target_request_fingerprint
                != image_spec.request_fingerprint
            ):
                raise ValueError("previous-tail source is no longer current")
            first_candidate = _candidate_for_binding(source_pool, first_binding)
            first_frame = _frame_ref(
                frame_role="first",
                binding_kind="previous_tail",
                candidate=first_candidate,
                source_shot_id=source_pool.shot_id,
                selection_revision=pool.selection_revision,
                source_tail_revision=first_binding.source_tail_revision,
                target_request_fingerprint=first_binding.target_request_fingerprint,
            )
        else:
            raise ValueError("shot video first binding is invalid")

        tail_binding = pool.tail_binding
        tail_frame: ShotVideoFrameRef | None
        if isinstance(tail_binding, NoTailShotImageBinding):
            tail_frame = None
        elif isinstance(tail_binding, DirectShotImageBinding):
            tail_candidate = _candidate_for_binding(pool, tail_binding)
            tail_frame = _frame_ref(
                frame_role="tail",
                binding_kind="direct",
                candidate=tail_candidate,
                source_shot_id=pool.shot_id,
                selection_revision=pool.selection_revision,
                source_tail_revision=pool.tail_binding_revision,
            )
        else:
            raise ValueError("shot video tail binding is invalid")

        spec_payload: Dict[str, Any] = {
            "shot_id": render_shot.shot_id,
            "render_shot_fingerprint": render_shot.source_fingerprint,
            "shot_image_request_fingerprint": image_spec.request_fingerprint,
            "selection_revision": pool.selection_revision,
            "target_duration_seconds": render_shot.target_duration_seconds,
            "shot_size": render_shot.shot_size,
            "camera_movement": render_shot.camera_movement,
            "visual_action": render_shot.visual_action,
            "image_prompt": render_shot.image_prompt,
            "transition_hint": render_shot.transition_hint,
            "first_frame": model_to_dict(first_frame),
            "tail_frame": model_to_dict(tail_frame) if tail_frame is not None else None,
            "ordered_references": [
                model_to_dict(item) for item in image_spec.image_references
            ],
        }
        spec_payload["spec_fingerprint"] = _sha256(spec_payload)
        video_specs.append(ShotVideoRequestSpec(**spec_payload))

    selected_payload = [
        {
            "shot_id": item.shot_id,
            "selection_revision": item.selection_revision,
            "first_frame_fingerprint": item.first_frame.frame_fingerprint,
            "tail_frame_fingerprint": (
                item.tail_frame.frame_fingerprint if item.tail_frame is not None else None
            ),
        }
        for item in video_specs
    ]
    plan_payload: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-video-plan-v1",
        "season_no": render.season_no,
        "episode_no": render.episode_no,
        "render_plan_fingerprint": render.plan_fingerprint,
        "shot_image_plan_fingerprint": image_plan.plan_fingerprint,
        "selected_bindings_fingerprint": _sha256(selected_payload),
        "image_coverage_fingerprint": coverage.coverage_fingerprint,
        "shot_specs": [model_to_dict(item) for item in video_specs],
    }
    plan_payload["plan_fingerprint"] = _sha256(plan_payload)
    return EpisodeShotVideoPlan(**plan_payload)


def build_episode_shot_video_plan(
    render_plan: RenderPlan | Dict[str, Any],
    shot_image_plan: EpisodeShotImagePlan | Dict[str, Any],
    candidate_manifest: EpisodeShotImageCandidateManifest | Dict[str, Any],
) -> EpisodeShotVideoPlan:
    try:
        return _build_episode_shot_video_plan_impl(
            render_plan,
            shot_image_plan,
            candidate_manifest,
        )
    except DramaShotVideoError:
        raise
    except (RecursionError, TypeError, ValueError):
        _raise_public_error("plan build")


def shot_video_plan_affected_ids(
    stored: EpisodeShotVideoPlan | Dict[str, Any],
    current: EpisodeShotVideoPlan | Dict[str, Any],
) -> list[str]:
    try:
        before = stored if isinstance(stored, EpisodeShotVideoPlan) else EpisodeShotVideoPlan(**stored)
        after = current if isinstance(current, EpisodeShotVideoPlan) else EpisodeShotVideoPlan(**current)
        if before.episode_no != after.episode_no or before.season_no != after.season_no:
            raise ValueError("shot video plans belong to different episodes")
        before_ids = [item.shot_id for item in before.shot_specs]
        after_ids = [item.shot_id for item in after.shot_specs]
        before_by_id = {item.shot_id: item for item in before.shot_specs}
        after_by_id = {item.shot_id: item for item in after.shot_specs}
        affected = {
            shot_id
            for shot_id in set(before_ids) | set(after_ids)
            if shot_id not in before_by_id
            or shot_id not in after_by_id
            or before_by_id[shot_id].spec_fingerprint
            != after_by_id[shot_id].spec_fingerprint
            or before_ids.index(shot_id) != after_ids.index(shot_id)
        }
        if (
            not affected
            and (
                before.render_plan_fingerprint != after.render_plan_fingerprint
                or before.shot_image_plan_fingerprint
                != after.shot_image_plan_fingerprint
            )
        ):
            affected.update(after_ids)
        return [shot_id for shot_id in after_ids if shot_id in affected] + sorted(
            affected - set(after_ids)
        )
    except DramaShotVideoError:
        raise
    except (RecursionError, TypeError, ValueError):
        _raise_public_error("affected-shot analysis")
