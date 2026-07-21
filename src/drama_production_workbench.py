"""Bounded, read-only projection for the short-drama production workbench.

The workbench is a view over existing domain inspectors.  It never reads raw
provider responses or prompts, never submits work, and never becomes another
source of truth.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .drama_asset_web import build_asset_web_overview
from .drama_compose_web import build_compose_web_overview_readonly
from .drama_event_graph import select_event_projection
from .drama_media_tasks import build_media_task_projection
from .drama_render_plan import inspect_render_plan_source_events
from .drama_render_store import inspect_render_plan
from .drama_schemas import normalize_episode_no
from .drama_shot_image_web import build_shot_image_web_overview
from .drama_shot_video_web import build_shot_video_web_overview
from .drama_source_adapter import load_production_source_event_graph
from .schemas import model_to_dict


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SHOT_ID_PATTERN = r"^shot_[0-9a-f]{24}$"
_TASK_ID_PATTERN = r"^dmt_[0-9a-f]{24}$"
MAX_WORKBENCH_ASSETS = 256
MAX_WORKBENCH_TASKS = 256
MAX_WORKBENCH_CANVAS_NODES = 700
MAX_WORKBENCH_CANVAS_EDGES = 1500

WorkbenchState = Literal["ready", "incomplete", "stale", "blocked", "busy"]
ComponentState = Literal["ready", "missing", "incomplete", "stale", "blocked", "invalid", "busy"]


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class WorkbenchRenderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: ComponentState
    reasons: List[str] = Field(default_factory=list, max_length=8)
    season_no: Optional[int] = Field(default=None, ge=1)
    creative_revision: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    plan_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    shot_count: int = Field(ge=0, le=100)
    spoken_segment_count: int = Field(ge=0, le=200)
    source_event_binding_state: Literal["unbound", "fresh", "stale", "blocked"]
    source_event_counts: Dict[Literal["source_derived", "invented", "mixed"], int]


class WorkbenchAssetItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["character", "art_direction", "scene", "prop", "clue"]
    asset_id: str = Field(min_length=1, max_length=64)
    scope: Optional[Literal["global", "series", "episode"]] = None
    selected_version_id: str = Field(min_length=1, max_length=80)
    selected_status: Literal["active", "disabled"]
    reference_count: int = Field(ge=0, le=10_000)
    impact_complete: bool


class WorkbenchAssetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: ComponentState
    blocker_count: int = Field(ge=0, le=512)
    selected_count: int = Field(ge=0, le=9999)
    omitted_count: int = Field(ge=0, le=9999)
    items: List[WorkbenchAssetItem] = Field(max_length=MAX_WORKBENCH_ASSETS)


class WorkbenchTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str = Field(pattern=_TASK_ID_PATTERN)
    media_kind: Literal["image", "video", "audio", "compose", "export"]
    stage: Literal["image-generate", "video-generate", "tts-synthesize", "compose", "edit-export"]
    subject_id: Optional[str] = Field(default=None, pattern=_SHOT_ID_PATTERN)
    dependency_task_ids: List[str] = Field(max_length=100)
    blocked_dependency_ids: List[str] = Field(max_length=100)
    state: Literal[
        "planned", "ready", "claimed", "submitting", "submitted", "polling",
        "submission_unknown", "downloading", "validating", "succeeded", "failed",
        "cancelling", "cancelled"
    ]
    revision: int = Field(ge=0, le=2_147_483_647)
    outcome_code: Optional[str] = Field(default=None, max_length=80)
    backend_binding_status: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class WorkbenchTaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: ComponentState
    ledger_revision: int = Field(ge=0, le=2_147_483_647)
    ledger_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    task_count: int = Field(ge=0, le=1000)
    omitted_count: int = Field(ge=0, le=1000)
    unknown_count: int = Field(ge=0, le=1000)
    failed_count: int = Field(ge=0, le=1000)
    tasks: List[WorkbenchTask] = Field(max_length=MAX_WORKBENCH_TASKS)


class WorkbenchVideoAttemptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: Literal[
        "needs_attempts",
        "fresh",
        "reconciliation_required",
        "stale",
        "invalid",
    ]
    not_sent_count: int = Field(ge=0, le=100)
    unknown_count: int = Field(ge=0, le=100)
    submitted_count: int = Field(ge=0, le=100)
    terminal_count: int = Field(ge=0, le=100)


class WorkbenchQaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    acceptance_level: Literal["safe-blocked", "mock-functional", "local-e2e", "provider-validated"]
    profile: str = Field(min_length=1, max_length=80)
    required_shot_count: int = Field(ge=0, le=100)
    covered_shot_count: int = Field(ge=0, le=100)
    output_size_bytes: int = Field(ge=0, le=100_000_000)
    output_sha256: str = Field(pattern=_SHA256_PATTERN)
    qa_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class WorkbenchDeliverable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["mp4", "srt", "ass", "edit"]
    filename: str = Field(min_length=1, max_length=160)
    url: str = Field(pattern=r"^/api/workspace/[^\s]{1,480}$", max_length=500)


class WorkbenchTimelineSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: ComponentState
    ready_to_compose: bool
    timeline_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    duration_ms: Optional[int] = Field(default=None, ge=1, le=3_600_000)
    shot_count: int = Field(ge=0, le=100)
    subtitle_count: int = Field(ge=0, le=200)
    warnings: List[str] = Field(default_factory=list, max_length=32)
    qa: Optional[WorkbenchQaSummary] = None
    deliverables: List[WorkbenchDeliverable] = Field(max_length=4)


class WorkbenchShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    sequence: int = Field(ge=1, le=100)
    target_duration_seconds: Optional[int] = Field(default=None, ge=1, le=30)
    is_highlight: bool
    spoken_segment_count: int = Field(ge=0, le=2)
    source_event_count: int = Field(ge=0, le=64)
    image_state: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    image_candidate_count: int = Field(ge=0, le=32)
    first_frame_selected: bool
    tail_frame_selected: bool
    video_state: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    video_candidate_count: int = Field(ge=0, le=32)
    video_selected: bool
    latest_attempt_outcome: Optional[Literal["not_sent", "unknown", "submitted", "terminal"]] = None


class WorkbenchCanvasNode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    node_id: str = Field(min_length=1, max_length=180)
    kind: Literal["asset", "shot", "task", "timeline"]
    ref_id: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    selected: bool


class WorkbenchCanvasEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    edge_id: str = Field(min_length=1, max_length=220)
    source_node_id: str = Field(min_length=1, max_length=180)
    target_node_id: str = Field(min_length=1, max_length=180)
    kind: Literal["depends_on", "subject", "feeds_timeline"]


class DramaProductionWorkbench(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=100)
    state: WorkbenchState
    reasons: List[str] = Field(default_factory=list, max_length=16)
    render: WorkbenchRenderSummary
    assets: WorkbenchAssetSummary
    image_state: ComponentState
    video_state: ComponentState
    video_attempts: WorkbenchVideoAttemptSummary
    tasks: WorkbenchTaskSummary
    timeline: WorkbenchTimelineSummary
    shots: List[WorkbenchShot] = Field(max_length=100)
    canvas_nodes: List[WorkbenchCanvasNode] = Field(max_length=MAX_WORKBENCH_CANVAS_NODES)
    canvas_edges: List[WorkbenchCanvasEdge] = Field(max_length=MAX_WORKBENCH_CANVAS_EDGES)
    canvas_omitted_edge_count: int = Field(ge=0, le=32_000)
    source_projection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    list_projection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    canvas_projection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    projection_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _fingerprints_are_consistent(self) -> "DramaProductionWorkbench":
        if not (
            self.source_projection_fingerprint
            == self.list_projection_fingerprint
            == self.canvas_projection_fingerprint
        ):
            raise ValueError("workbench views must share one source projection")
        source_payload = {
            "episode_no": self.episode_no,
            "state": self.state,
            "reasons": list(self.reasons),
            "render": model_to_dict(self.render),
            "assets": model_to_dict(self.assets),
            "image_state": self.image_state,
            "video_state": self.video_state,
            "video_attempts": model_to_dict(self.video_attempts),
            "tasks": model_to_dict(self.tasks),
            "timeline": model_to_dict(self.timeline),
            "shots": [model_to_dict(item) for item in self.shots],
        }
        if _fingerprint(source_payload) != self.source_projection_fingerprint:
            raise ValueError("workbench source projection fingerprint is invalid")
        payload = self.model_dump(exclude={"projection_fingerprint"})
        if _fingerprint(payload) != self.projection_fingerprint:
            raise ValueError("workbench projection fingerprint is invalid")
        node_ids = [item.node_id for item in self.canvas_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workbench canvas nodes must be unique")
        known = set(node_ids)
        edge_ids = [item.edge_id for item in self.canvas_edges]
        if len(edge_ids) != len(set(edge_ids)) or any(
            item.source_node_id not in known or item.target_node_id not in known
            for item in self.canvas_edges
        ):
            raise ValueError("workbench canvas edges are invalid")
        return self


def _component_state(value: str, *, ready: set[str], missing: set[str] = set()) -> ComponentState:
    if value in ready:
        return "ready"
    if value in missing:
        return "missing"
    if value == "busy":
        return "busy"
    if value in {"stale", "partial"}:
        return "stale" if value == "stale" else "incomplete"
    if value in {"invalid", "blocked_source"}:
        return "blocked" if value == "blocked_source" else "invalid"
    return "incomplete"


def _safe_asset_summary(workspace: str, season_no: int, episode_no: int) -> WorkbenchAssetSummary:
    try:
        overview = build_asset_web_overview(
            workspace, season_no=season_no, episode_no=episode_no
        )
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
        return WorkbenchAssetSummary(
            state="invalid", blocker_count=1, selected_count=0, omitted_count=0, items=[]
        )
    all_rows: list[WorkbenchAssetItem] = []
    total = 0
    invalid = bool(overview.blockers)
    stale = False
    incomplete = False
    for section in overview.sections:
        if section.state in {"invalid", "blocked_source"}:
            invalid = True
        elif section.state == "stale":
            stale = True
        elif section.state != "fresh":
            incomplete = True
        for item in section.items:
            total += 1
            selected = next(
                (
                    version
                    for version in item.versions
                    if version.version_id == item.selected_version_id
                ),
                None,
            )
            if selected is None:
                invalid = True
                continue
            all_rows.append(
                WorkbenchAssetItem(
                    kind=item.kind,
                    asset_id=item.asset_id,
                    scope=item.scope,
                    selected_version_id=item.selected_version_id,
                    selected_status=selected.status,
                    reference_count=sum(len(ref.shot_ids) or 1 for ref in selected.references),
                    impact_complete=item.impact_complete,
                )
            )
    all_rows.sort(key=lambda item: (item.kind, item.scope or "", item.asset_id))
    rows = all_rows[:MAX_WORKBENCH_ASSETS]
    return WorkbenchAssetSummary(
        state=(
            "blocked"
            if invalid
            else "stale"
            if stale
            else "incomplete"
            if incomplete and total
            else "missing"
            if not total
            else "ready"
        ),
        blocker_count=len(overview.blockers),
        selected_count=len(all_rows),
        omitted_count=max(0, len(all_rows) - len(rows)),
        items=rows,
    )


def _safe_task_summary(
    workspace: str,
    episode_no: int,
    *,
    allowed_subject_ids: set[str],
) -> WorkbenchTaskSummary:
    try:
        raw = build_media_task_projection(workspace, episode_no=episode_no)
        ordered = sorted(raw["tasks"], key=lambda item: item["task_id"])
        visible = ordered[:MAX_WORKBENCH_TASKS]
        tasks = [
            WorkbenchTask(
                task_id=item["task_id"],
                media_kind=item["media_kind"],
                stage=item["stage"],
                subject_id=(
                    item["subject_id"]
                    if item["subject_id"] in allowed_subject_ids
                    else None
                ),
                dependency_task_ids=item["dependency_task_ids"],
                blocked_dependency_ids=item["blocked_dependency_ids"],
                state=item["state"],
                revision=item["revision"],
                outcome_code=item["outcome_code"],
                backend_binding_status=item["backend_binding_status"],
            )
            for item in visible
        ]
        unknown = sum(item["state"] == "submission_unknown" for item in ordered)
        failed = sum(item["state"] in {"failed", "cancelled"} for item in ordered)
        active = sum(
            item["state"] not in {"succeeded", "failed", "cancelled", "submission_unknown"}
            for item in ordered
        )
        state: ComponentState = (
            "blocked"
            if unknown
            else "incomplete"
            if failed or active
            else "ready"
            if tasks
            else "missing"
        )
        return WorkbenchTaskSummary(
            state=state,
            ledger_revision=raw["ledger_revision"],
            ledger_fingerprint=raw["ledger_fingerprint"],
            task_count=raw["task_count"],
            omitted_count=max(0, len(ordered) - len(visible)),
            unknown_count=unknown,
            failed_count=failed,
            tasks=tasks,
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, RecursionError):
        return WorkbenchTaskSummary(
            state="invalid",
            ledger_revision=0,
            ledger_fingerprint=_fingerprint({"invalid": True, "episode_no": episode_no}),
            task_count=0,
            omitted_count=0,
            unknown_count=0,
            failed_count=0,
            tasks=[],
        )


def _safe_timeline_summary(workspace: str, episode_no: int) -> WorkbenchTimelineSummary:
    try:
        raw = build_compose_web_overview_readonly(workspace, episode_no=episode_no)
        qa = raw.get("qa")
        return WorkbenchTimelineSummary(
            state=_component_state(
                str(raw.get("state") or "needs_timeline"),
                ready={"ready", "complete"},
                missing={"needs_timeline"},
            ),
            ready_to_compose=bool(raw.get("ready_to_compose") is True),
            timeline_fingerprint=raw.get("timeline_fingerprint"),
            duration_ms=raw.get("duration_ms"),
            shot_count=int(raw.get("shot_count") or 0),
            subtitle_count=int(raw.get("subtitle_count") or 0),
            warnings=list(raw.get("warnings") or [])[:32],
            qa=(WorkbenchQaSummary(**qa) if qa is not None else None),
            deliverables=[WorkbenchDeliverable(**item) for item in (raw.get("deliverables") or [])],
        )
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
        return WorkbenchTimelineSummary(
            state="invalid",
            ready_to_compose=False,
            timeline_fingerprint=None,
            duration_ms=None,
            shot_count=0,
            subtitle_count=0,
            warnings=["timeline_projection_invalid"],
            qa=None,
            deliverables=[],
        )


def _render_summary(workspace: str, episode_no: int) -> tuple[WorkbenchRenderSummary, Any]:
    try:
        inspection = inspect_render_plan(workspace, episode_no=episode_no)
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
        return WorkbenchRenderSummary(
            state="invalid",
            reasons=["render_projection_invalid"],
            season_no=None,
            creative_revision=None,
            plan_fingerprint=None,
            shot_count=0,
            spoken_segment_count=0,
            source_event_binding_state="blocked",
            source_event_counts={"source_derived": 0, "invented": 0, "mixed": 0},
        ), None
    plan = inspection.plan
    counts: Counter[str] = Counter()
    if inspection.state == "fresh" and plan is not None and plan.source_event_graph_family_id:
        try:
            current = load_production_source_event_graph(
                workspace=workspace,
                graph_family_id=plan.source_event_graph_family_id,
                max_spoiler_boundary=plan.source_event_spoiler_boundary or 100_000,
            )
            projection = select_event_projection(
                current.graph,
                selected_event_ids=plan.source_event_ids,
                allowed_source_chapter_ids=plan.source_event_allowed_chapter_ids or [],
                max_spoiler_boundary=plan.source_event_spoiler_boundary or 100_000,
            )
            if (
                current.source_snapshot_fingerprint != plan.source_event_snapshot_fingerprint
                or inspect_render_plan_source_events(
                    plan, projection, current.source_snapshot_fingerprint
                )
                != "fresh"
            ):
                raise ValueError("source event projection changed")
            counts.update(item.source_kind for item in projection.events)
        except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
            return WorkbenchRenderSummary(
                state="stale",
                reasons=["source_event_projection_changed"],
                season_no=plan.season_no,
                creative_revision=plan.creative_revision,
                plan_fingerprint=plan.plan_fingerprint,
                shot_count=len(plan.shots),
                spoken_segment_count=len(plan.spoken_segments),
                source_event_binding_state="stale",
                source_event_counts={"source_derived": 0, "invented": 0, "mixed": 0},
            ), plan
    state = _component_state(
        inspection.state,
        ready={"fresh"},
        missing={"needs_render_plan"},
    )
    return WorkbenchRenderSummary(
        state=state,
        reasons=list(inspection.reasons)[:8],
        season_no=plan.season_no if plan is not None else None,
        creative_revision=plan.creative_revision if plan is not None else None,
        plan_fingerprint=plan.plan_fingerprint if plan is not None else None,
        shot_count=len(plan.shots) if plan is not None else 0,
        spoken_segment_count=len(plan.spoken_segments) if plan is not None else 0,
        source_event_binding_state=(
            "blocked"
            if inspection.state in {"blocked_source", "invalid"}
            else "stale"
            if inspection.state == "stale"
            else "fresh"
            if plan is not None and plan.source_event_graph_family_id is not None
            else "unbound"
        ),
        source_event_counts={
            "source_derived": counts["source_derived"],
            "invented": counts["invented"],
            "mixed": counts["mixed"],
        },
    ), plan


def build_production_workbench(
    workspace: str,
    *,
    episode_no: int = 1,
) -> DramaProductionWorkbench:
    """Rebuild a redacted workbench projection from current durable facts."""

    number = normalize_episode_no(episode_no)
    render, plan = _render_summary(workspace, number)
    season_no = render.season_no or 1
    assets = _safe_asset_summary(workspace, season_no, number)
    try:
        image = build_shot_image_web_overview(workspace, episode_no=number)
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
        image = None
    image_state: ComponentState = (
        "invalid"
        if image is None
        else _component_state(
            image.state,
            ready={"fresh"},
            missing={"needs_shot_image_assets"},
        )
    )
    video_failure_state: ComponentState = "invalid"
    try:
        video = build_shot_video_web_overview(workspace, episode_no=number)
    except RuntimeError:
        video = None
        video_failure_state = "busy"
    except (OSError, TypeError, ValueError, RecursionError):
        video = None
    video_state: ComponentState = (
        video_failure_state
        if video is None
        else _component_state(
            video.state,
            ready={"fresh"},
            missing={"needs_shot_video_assets"},
        )
    )
    video_attempts = WorkbenchVideoAttemptSummary(
        state=(video.attempts.state if video is not None else "invalid"),
        not_sent_count=(video.attempts.not_sent_count if video is not None else 0),
        unknown_count=(video.attempts.unknown_count if video is not None else 0),
        submitted_count=(video.attempts.submitted_count if video is not None else 0),
        terminal_count=(video.attempts.terminal_count if video is not None else 0),
    )
    image_by_id = {item.shot_id: item for item in (image.shots if image else [])}
    video_by_id = {item.shot_id: item for item in (video.shots if video else [])}
    if plan is not None:
        ordered_ids = [item.shot_id for item in plan.shots]
    else:
        ordered_ids = sorted(set(image_by_id) | set(video_by_id))
    tasks = _safe_task_summary(
        workspace,
        number,
        allowed_subject_ids=set(ordered_ids),
    )
    timeline = _safe_timeline_summary(workspace, number)
    plan_by_id = {item.shot_id: item for item in (plan.shots if plan is not None else [])}
    shots: list[WorkbenchShot] = []
    for sequence, shot_id in enumerate(ordered_ids, 1):
        planned = plan_by_id.get(shot_id)
        image_shot = image_by_id.get(shot_id)
        video_shot = video_by_id.get(shot_id)
        shots.append(
            WorkbenchShot(
                shot_id=shot_id,
                sequence=sequence,
                target_duration_seconds=(planned.target_duration_seconds if planned else None),
                is_highlight=bool(planned.is_highlight) if planned else False,
                spoken_segment_count=len(planned.spoken_segment_ids) if planned else 0,
                source_event_count=len(planned.source_event_ids) if planned else 0,
                image_state=(image_shot.coverage_state if image_shot else "missing"),
                image_candidate_count=len(image_shot.candidates) if image_shot else 0,
                first_frame_selected=bool(image_shot and image_shot.first_binding),
                tail_frame_selected=bool(
                    image_shot and (image_shot.tail_binding or {}).get("kind") != "none"
                ),
                video_state=(video_shot.coverage_state if video_shot else "missing"),
                video_candidate_count=(video_shot.candidate_count if video_shot else 0),
                video_selected=bool(video_shot and video_shot.selected),
                latest_attempt_outcome=(
                    video_shot.attempt.outcome
                    if video_shot is not None and video_shot.attempt is not None
                    else None
                ),
            )
        )

    nodes: list[WorkbenchCanvasNode] = []
    edges: list[WorkbenchCanvasEdge] = []
    for item in assets.items:
        node_id = f"asset:{item.kind}:{item.scope or 'season'}:{item.asset_id}"
        nodes.append(
            WorkbenchCanvasNode(
                node_id=node_id,
                kind="asset",
                ref_id=item.asset_id,
                state=item.selected_status,
                selected=True,
            )
        )
    for item in shots:
        nodes.append(
            WorkbenchCanvasNode(
                node_id=f"shot:{item.shot_id}",
                kind="shot",
                ref_id=item.shot_id,
                state=(
                    "blocked"
                    if item.image_state in {"blocked", "broken"}
                    or item.video_state in {"blocked", "invalid"}
                    else "stale"
                    if item.image_state == "stale" or item.video_state == "stale"
                    else "ready"
                    if item.image_state == "covered" and item.video_state == "ready"
                    else "incomplete"
                ),
                selected=item.first_frame_selected or item.video_selected,
            )
        )
    known_shots = {item.shot_id for item in shots}
    for item in tasks.tasks:
        task_node = f"task:{item.task_id}"
        nodes.append(
            WorkbenchCanvasNode(
                node_id=task_node,
                kind="task",
                ref_id=item.task_id,
                state=item.state,
                selected=False,
            )
        )
        if item.subject_id is not None and item.subject_id in known_shots:
            edges.append(
                WorkbenchCanvasEdge(
                    edge_id=f"subject:{item.subject_id}:{item.task_id}",
                    source_node_id=f"shot:{item.subject_id}",
                    target_node_id=task_node,
                    kind="subject",
                )
            )
        for dependency in item.dependency_task_ids:
            if any(candidate.task_id == dependency for candidate in tasks.tasks):
                edges.append(
                    WorkbenchCanvasEdge(
                        edge_id=f"dependency:{dependency}:{item.task_id}",
                        source_node_id=f"task:{dependency}",
                        target_node_id=task_node,
                        kind="depends_on",
                    )
                )
    timeline_node = f"timeline:episode:{number}"
    nodes.append(
        WorkbenchCanvasNode(
            node_id=timeline_node,
            kind="timeline",
            ref_id=str(number),
            state=timeline.state,
            selected=timeline.state == "ready",
        )
    )
    for item in tasks.tasks:
        if item.state == "succeeded":
            edges.append(
                WorkbenchCanvasEdge(
                    edge_id=f"timeline:{item.task_id}:{number}",
                    source_node_id=f"task:{item.task_id}",
                    target_node_id=timeline_node,
                    kind="feeds_timeline",
                )
            )
    nodes.sort(key=lambda item: item.node_id)
    edges.sort(key=lambda item: item.edge_id)
    if len(nodes) > MAX_WORKBENCH_CANVAS_NODES:
        raise ValueError("workbench canvas node projection exceeds its limit")
    omitted_edge_count = max(0, len(edges) - MAX_WORKBENCH_CANVAS_EDGES)
    edges = edges[:MAX_WORKBENCH_CANVAS_EDGES]

    reasons: list[str] = []
    components = (
        render.state,
        assets.state,
        image_state,
        video_state,
        tasks.state,
        timeline.state,
    )
    attempt_submission_unknown = (
        video_attempts.unknown_count > 0
        or video_attempts.submitted_count > 0
        or any(item.latest_attempt_outcome == "unknown" for item in shots)
    )
    attempt_ledger_blocked = video_attempts.state in {
        "invalid",
        "reconciliation_required",
    }
    if "busy" in components:
        state: WorkbenchState = "busy"
        reasons.append("component_busy")
    elif attempt_submission_unknown or attempt_ledger_blocked or any(
        item in {"blocked", "invalid"} for item in components
    ):
        state = "blocked"
        reasons.append(
            "attempt_submission_unknown"
            if attempt_submission_unknown
            else "attempt_ledger_blocked"
            if attempt_ledger_blocked
            else "component_blocked"
        )
    elif video_attempts.state == "stale" or "stale" in components or (
        image is not None and image.state == "stale"
    ) or (video is not None and video.state == "stale"):
        state = "stale"
        reasons.append("component_stale")
    elif (
        render.state == "ready"
        and assets.state == "ready"
        and tasks.state in {"ready", "missing"}
        and timeline.state == "ready"
        and all(item.image_state == "covered" and item.video_state == "ready" for item in shots)
    ):
        state = "ready"
    else:
        state = "incomplete"
        reasons.append("production_incomplete")

    source_payload = {
        "episode_no": number,
        "state": state,
        "reasons": reasons,
        "render": model_to_dict(render),
        "assets": model_to_dict(assets),
        "image_state": image_state,
        "video_state": video_state,
        "video_attempts": model_to_dict(video_attempts),
        "tasks": model_to_dict(tasks),
        "timeline": model_to_dict(timeline),
        "shots": [model_to_dict(item) for item in shots],
    }
    source_fingerprint = _fingerprint(source_payload)
    payload = {
        "schema_version": 1,
        **source_payload,
        "canvas_nodes": [model_to_dict(item) for item in nodes],
        "canvas_edges": [model_to_dict(item) for item in edges],
        "canvas_omitted_edge_count": omitted_edge_count,
        "source_projection_fingerprint": source_fingerprint,
        "list_projection_fingerprint": source_fingerprint,
        "canvas_projection_fingerprint": source_fingerprint,
    }
    payload["projection_fingerprint"] = _fingerprint(payload)
    return DramaProductionWorkbench(**payload)
