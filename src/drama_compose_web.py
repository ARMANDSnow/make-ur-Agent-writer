"""F3 Web-facing compose orchestration and exact deliverable reads.

The browser never supplies a TimelineManifest.  An E3 producer first calls
``persist_workspace_timeline_manifest`` with its AudioManifest and TTS attempt
records; this module reruns the production E3 gate and stores only that result.
All later Web operations revalidate the stored timeline against current D4 and
the exact source bytes before composing or authorizing downloads.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import drama_compositor, drama_edit_export, paths
from .drama_schemas import (
    AudioManifest,
    TimelineManifest,
    TimelineOptionalAudioClip,
    TtsAttemptRecord,
)
from .drama_shot_video_candidate_store import (
    inspect_episode_shot_video_candidates,
)
from .drama_shot_video_continuity import build_shot_video_continuity_report
from .drama_shot_video_store import load_fresh_episode_shot_video_plan
from .drama_store import _read_strict_workspace_bytes
from .drama_timeline import (
    require_workspace_timeline_manifest,
    revise_timeline_subtitles,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_TIMELINE_STORE_BYTES = 1_000_000
MAX_SUBTITLE_TRANSITION_BYTES = 2_000
MAX_WEB_COMPOSE_MP4_BYTES = drama_compositor.MAX_COMPOSE_OUTPUT_BYTES
MAX_DELIVERABLE_BYTES = {
    "mp4": MAX_WEB_COMPOSE_MP4_BYTES,
    "srt": 100_000,
    "ass": drama_edit_export.MAX_ASS_BYTES,
    "edit": drama_edit_export.MAX_EDIT_PROJECT_BYTES,
}
_COMPOSE_CAPACITY = threading.BoundedSemaphore(1)
DELIVERABLE_CONTENT_TYPES = {
    "mp4": "video/mp4",
    "srt": "application/x-subrip; charset=utf-8",
    "ass": "text/x-ssa; charset=utf-8",
    "edit": "application/json; charset=utf-8",
}
DELIVERABLE_FILENAMES = {
    "mp4": "episode_{episode_no:03d}.mp4",
    "srt": "episode_{episode_no:03d}.srt",
    "ass": "episode_{episode_no:03d}.ass",
    "edit": "episode_{episode_no:03d}.edit.json",
}


class DramaComposeWebError(ValueError):
    """Fail-closed F3 boundary with a stable, non-sensitive reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _timeline_path(episode_no: int) -> str:
    if not isinstance(episode_no, int) or isinstance(episode_no, bool):
        raise DramaComposeWebError("episode_invalid")
    if not 1 <= episode_no <= 100:
        raise DramaComposeWebError("episode_invalid")
    return f"outputs/drama/timeline/episode_{episode_no:03d}.timeline.json"


def _transition_path(episode_no: int) -> str:
    _timeline_path(episode_no)
    return (
        "outputs/drama/timeline/"
        f"episode_{episode_no:03d}.subtitle-transition.json"
    )


def _timeline_bytes(timeline: TimelineManifest) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "drama_timeline_manifest",
                "timeline_fingerprint": timeline.timeline_fingerprint,
                "timeline": model_to_dict(timeline),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _transition_request_fingerprint(
    expected_timeline_fingerprint: str,
    revisions: Mapping[str, str],
) -> str:
    if (
        not isinstance(expected_timeline_fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_timeline_fingerprint)
        or not isinstance(revisions, dict)
        or not 1 <= len(revisions) <= 200
        or any(
            not isinstance(cue_id, str) or not isinstance(text, str)
            for cue_id, text in revisions.items()
        )
    ):
        raise DramaComposeWebError("subtitle_revision_invalid")
    raw = json.dumps(
        {
            "expected_timeline_fingerprint": expected_timeline_fingerprint,
            "revisions": revisions,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _transition_bytes(
    *,
    episode_no: int,
    previous_timeline_fingerprint: str,
    request_fingerprint: str,
    result_timeline_fingerprint: str,
) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "drama_subtitle_transition",
                "episode_no": episode_no,
                "previous_timeline_fingerprint": previous_timeline_fingerprint,
                "request_fingerprint": request_fingerprint,
                "result_timeline_fingerprint": result_timeline_fingerprint,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_stored_timeline(root: Path, episode_no: int) -> TimelineManifest:
    relative = _timeline_path(episode_no)
    try:
        raw = _read_strict_workspace_bytes(
            root, root / relative, maximum=MAX_TIMELINE_STORE_BYTES
        )
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema_version",
                "artifact_type",
                "timeline_fingerprint",
                "timeline",
            }
            or payload.get("schema_version") != 1
            or payload.get("artifact_type") != "drama_timeline_manifest"
            or not isinstance(payload.get("timeline"), dict)
        ):
            raise ValueError("invalid envelope")
        timeline = TimelineManifest(**payload["timeline"])
        if (
            timeline.episode_no != episode_no
            or payload.get("timeline_fingerprint")
            != timeline.timeline_fingerprint
            or raw != _timeline_bytes(timeline)
        ):
            raise ValueError("timeline identity mismatch")
        return timeline
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, UnicodeDecodeError, ValueError):
        raise DramaComposeWebError("timeline_invalid") from None


def _read_subtitle_transition(
    root: Path,
    episode_no: int,
) -> dict[str, Any]:
    relative = _transition_path(episode_no)
    try:
        raw = _read_strict_workspace_bytes(
            root,
            root / relative,
            maximum=MAX_SUBTITLE_TRANSITION_BYTES,
        )
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema_version",
                "artifact_type",
                "episode_no",
                "previous_timeline_fingerprint",
                "request_fingerprint",
                "result_timeline_fingerprint",
            }
            or payload.get("schema_version") != 1
            or payload.get("artifact_type") != "drama_subtitle_transition"
            or payload.get("episode_no") != episode_no
            or any(
                not isinstance(payload.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", payload[key]) is None
                for key in (
                    "previous_timeline_fingerprint",
                    "request_fingerprint",
                    "result_timeline_fingerprint",
                )
            )
            or raw
            != _transition_bytes(
                episode_no=episode_no,
                previous_timeline_fingerprint=payload[
                    "previous_timeline_fingerprint"
                ],
                request_fingerprint=payload["request_fingerprint"],
                result_timeline_fingerprint=payload[
                    "result_timeline_fingerprint"
                ],
            )
        ):
            raise ValueError("invalid subtitle transition")
        return payload
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, UnicodeDecodeError, ValueError):
        raise DramaComposeWebError("subtitle_transition_invalid") from None


def _require_current_under_lock(
    workspace: str,
    timeline: TimelineManifest,
) -> None:
    inspection = inspect_episode_shot_video_candidates(
        workspace, episode_no=timeline.episode_no
    )
    if inspection.state != "fresh" or inspection.manifest is None:
        raise DramaComposeWebError("timeline_stale")
    try:
        plan = load_fresh_episode_shot_video_plan(
            workspace, episode_no=timeline.episode_no
        )
        report = build_shot_video_continuity_report(plan, inspection.manifest)
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaComposeWebError("timeline_stale") from None
    if (
        not report.ready_for_compose
        or report.report_fingerprint != timeline.d4_report_fingerprint
        or report.selected_bindings_fingerprint
        != timeline.selected_bindings_fingerprint
    ):
        raise DramaComposeWebError("timeline_stale")
    try:
        drama_compositor._validate_sources(paths.workspace_root(workspace), timeline)
    except drama_compositor.DramaComposeError:
        raise DramaComposeWebError("timeline_source_stale") from None


def _atomic_store_bytes(
    root: Path,
    relative: str,
    data: bytes,
    *,
    maximum: int,
) -> None:
    directory = str(Path(relative).parent)
    directory_fd: int | None = None
    try:
        directory_fd = drama_edit_export._open_output_directory(
            root, directory, create=True
        )
        identity = drama_edit_export._directory_identity(directory_fd)
        drama_edit_export._atomic_write_at(
            directory_fd,
            Path(relative).name,
            data,
            maximum=maximum,
        )
        drama_edit_export._require_current_output_directory(
            root, directory, expected=identity
        )
    except drama_edit_export.DramaEditExportError:
        raise DramaComposeWebError("timeline_store_failed") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _atomic_store_timeline(root: Path, timeline: TimelineManifest) -> None:
    _atomic_store_bytes(
        root,
        _timeline_path(timeline.episode_no),
        _timeline_bytes(timeline),
        maximum=MAX_TIMELINE_STORE_BYTES,
    )


def _timeline_is_subtitle_descendant(
    existing: TimelineManifest,
    generated: TimelineManifest,
) -> bool:
    existing_base = existing.model_dump(
        exclude={"subtitle_cues", "timeline_fingerprint"}
    )
    generated_base = generated.model_dump(
        exclude={"subtitle_cues", "timeline_fingerprint"}
    )
    if existing_base != generated_base or len(existing.subtitle_cues) != len(
        generated.subtitle_cues
    ):
        return False
    for current, base in zip(existing.subtitle_cues, generated.subtitle_cues):
        if (
            current.utterance_id != base.utterance_id
            or current.source_text_sha256 != base.source_text_sha256
            or current.start_ms != base.start_ms
            or current.end_ms != base.end_ms
            or current.revision < base.revision
        ):
            return False
    return True


def _prune_stale_deliverables_under_lock(
    root: Path,
    timeline: TimelineManifest,
) -> None:
    """Bound revision churn by deleting only unreachable content-addressed outputs."""

    current_stem = f"timeline_{timeline.timeline_fingerprint[:24]}"
    patterns = (
        (
            f"outputs/drama/compose/episode_{timeline.episode_no:03d}",
            re.compile(
                r"timeline_[0-9a-f]{24}\.(?:mp4|srt|qa\.json)\Z"
            ),
        ),
        (
            f"outputs/drama/edit/episode_{timeline.episode_no:03d}",
            re.compile(
                r"timeline_[0-9a-f]{24}\.(?:ass|edit\.json|complete\.json)\Z"
            ),
        ),
    )
    for relative_directory, pattern in patterns:
        directory_fd: int | None = None
        directory_path = root / relative_directory
        try:
            directory_info = directory_path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise DramaComposeWebError("deliverable_retention_failed") from None
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or stat.S_ISLNK(directory_info.st_mode)
        ):
            raise DramaComposeWebError("deliverable_retention_failed")
        try:
            directory_fd = drama_edit_export._open_output_directory(
                root, relative_directory, create=False
            )
        except drama_edit_export.DramaEditExportError:
            raise DramaComposeWebError("deliverable_retention_failed") from None
        try:
            identity = drama_edit_export._directory_identity(directory_fd)
            for name in os.listdir(directory_fd):
                if (
                    pattern.fullmatch(name) is None
                    or name.startswith(f"{current_stem}.")
                ):
                    continue
                try:
                    os.unlink(name, dir_fd=directory_fd)
                except FileNotFoundError:
                    continue
                except OSError:
                    raise DramaComposeWebError(
                        "deliverable_retention_failed"
                    ) from None
            os.fsync(directory_fd)
            drama_edit_export._require_current_output_directory(
                root, relative_directory, expected=identity
            )
        finally:
            os.close(directory_fd)


def _persist_validated_timeline_under_lock(
    workspace: str,
    timeline: TimelineManifest,
    *,
    preserve_existing_revision: bool = False,
) -> TimelineManifest:
    """Commit one already-schema-validated E3 timeline under the caller's lock."""

    _require_current_under_lock(workspace, timeline)
    root = paths.workspace_root(workspace)
    if preserve_existing_revision:
        try:
            existing = _read_stored_timeline(root, timeline.episode_no)
        except FileNotFoundError:
            existing = None
        except DramaComposeWebError:
            try:
                (root / _timeline_path(timeline.episode_no)).lstat()
            except FileNotFoundError:
                existing = None
            else:
                raise
        if existing is not None and _timeline_is_subtitle_descendant(
            existing, timeline
        ):
            _require_current_under_lock(workspace, existing)
            _prune_stale_deliverables_under_lock(root, existing)
            return existing
    _atomic_store_timeline(root, timeline)
    _prune_stale_deliverables_under_lock(root, timeline)
    return timeline


def persist_workspace_timeline_manifest(
    workspace: str,
    audio_manifest: AudioManifest | Mapping[str, Any],
    attempts: Sequence[TtsAttemptRecord | Mapping[str, Any]],
    *,
    episode_no: int = 1,
    bgm_policy: str = "optional",
    optional_audio_clips: Sequence[
        TimelineOptionalAudioClip | Mapping[str, Any]
    ] = (),
) -> TimelineManifest:
    """Production E3→F3 seam; arbitrary browser timeline JSON is never accepted."""

    timeline = require_workspace_timeline_manifest(
        workspace,
        audio_manifest,
        attempts,
        episode_no=episode_no,
        bgm_policy=bgm_policy,
        optional_audio_clips=optional_audio_clips,
    )
    # ``require_workspace_timeline_manifest`` commits the exact result inside
    # its E3 lock.  This named wrapper remains the explicit E3→F3 API.
    return timeline


def persist_workspace_revised_timeline(
    workspace: str,
    revisions: Mapping[str, str],
    *,
    episode_no: int = 1,
    expected_timeline_fingerprint: str,
) -> TimelineManifest:
    """CAS-commit subtitle-only revisions without accepting a client timeline."""

    request_fingerprint = _transition_request_fingerprint(
        expected_timeline_fingerprint, revisions
    )
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-compose-web-subtitles"
        ):
            root = paths.workspace_root(workspace)
            current = _read_stored_timeline(root, episode_no)
            if current.timeline_fingerprint != expected_timeline_fingerprint:
                try:
                    transition = _read_subtitle_transition(root, episode_no)
                except FileNotFoundError:
                    transition = None
                if transition is not None and (
                    transition["previous_timeline_fingerprint"]
                    == expected_timeline_fingerprint
                    and transition["request_fingerprint"]
                    == request_fingerprint
                    and transition["result_timeline_fingerprint"]
                    == current.timeline_fingerprint
                ):
                    _require_current_under_lock(workspace, current)
                    _prune_stale_deliverables_under_lock(root, current)
                    return current
                raise DramaComposeWebError("timeline_conflict")
            _require_current_under_lock(workspace, current)
            revised = revise_timeline_subtitles(current, revisions)
            _atomic_store_bytes(
                root,
                _transition_path(episode_no),
                _transition_bytes(
                    episode_no=episode_no,
                    previous_timeline_fingerprint=current.timeline_fingerprint,
                    request_fingerprint=request_fingerprint,
                    result_timeline_fingerprint=revised.timeline_fingerprint,
                ),
                maximum=MAX_SUBTITLE_TRANSITION_BYTES,
            )
            _persist_validated_timeline_under_lock(workspace, revised)
            return revised
    except FileNotFoundError:
        raise DramaComposeWebError("timeline_missing") from None
    except WorkspaceLocked:
        raise DramaComposeWebError("workspace_busy") from None


def require_current_workspace_timeline(
    workspace: str,
    *,
    episode_no: int = 1,
) -> TimelineManifest:
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-compose-web-read"
        ):
            root = paths.workspace_root(workspace)
            return _current_timeline_under_lock(workspace, root, episode_no)
    except FileNotFoundError:
        raise
    except WorkspaceLocked:
        raise DramaComposeWebError("workspace_busy") from None


def _current_timeline_under_lock(
    workspace: str,
    root: Path,
    episode_no: int,
) -> TimelineManifest:
    timeline = _read_stored_timeline(root, episode_no)
    _require_current_under_lock(workspace, timeline)
    return timeline


def _artifact_states(root: Path, paths_: Sequence[str]) -> list[str]:
    states: list[str] = []
    for relative in paths_:
        try:
            info = (root / relative).lstat()
            states.append(
                "file"
                if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                else "invalid"
            )
        except FileNotFoundError:
            states.append("missing")
        except OSError:
            states.append("invalid")
    return states


def _download_url(
    workspace: str,
    timeline: TimelineManifest,
    kind: str,
) -> str:
    return (
        f"/api/workspace/{workspace}/drama/compose/"
        f"{timeline.episode_no}/{timeline.timeline_fingerprint}/{kind}"
    )


def build_compose_web_overview(
    workspace: str,
    *,
    episode_no: int = 1,
) -> dict[str, Any]:
    """Project readiness from durable artifacts; job history is never truth."""

    base: dict[str, Any] = {
        "schema_version": 1,
        "episode_no": episode_no,
        "state": "needs_timeline",
        "ready_to_compose": False,
        "timeline_fingerprint": None,
        "duration_ms": None,
        "shot_count": 0,
        "subtitle_count": 0,
        "warnings": [],
        "qa": None,
        "deliverables": [],
    }
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-compose-web-overview"
        ):
            root = paths.workspace_root(workspace)
            timeline = _current_timeline_under_lock(
                workspace, root, episode_no
            )
            return _build_compose_web_overview_under_lock(
                workspace, root, timeline, base
            )
    except FileNotFoundError:
        return base
    except WorkspaceLocked:
        base["state"] = "busy"
        base["warnings"] = ["workspace_busy"]
        return base
    except DramaComposeWebError as exc:
        base["state"] = (
            "busy" if exc.code == "workspace_busy"
            else "invalid" if exc.code == "timeline_invalid"
            else "stale"
        )
        base["warnings"] = [exc.code]
        return base


def _build_compose_web_overview_under_lock(
    workspace: str,
    root: Path,
    timeline: TimelineManifest,
    base: dict[str, Any],
) -> dict[str, Any]:
    base.update(
        {
            "state": "ready",
            "ready_to_compose": True,
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "duration_ms": timeline.total_duration_ms,
            "shot_count": len(timeline.video_clips),
            "subtitle_count": len(timeline.subtitle_cues),
            "warnings": list(timeline.warnings),
        }
    )
    plan = drama_compositor.build_compose_plan(timeline)
    edit_paths = drama_edit_export._export_paths(timeline)
    compose_states = _artifact_states(
        root, [plan.output_path, plan.srt_path, plan.qa_path]
    )
    edit_states = _artifact_states(root, list(edit_paths))
    if compose_states == ["missing", "missing", "missing"] and edit_states == [
        "missing",
        "missing",
        "missing",
    ]:
        return base
    if "invalid" in compose_states or "invalid" in edit_states:
        base["state"] = "invalid"
        base["ready_to_compose"] = True
        base["warnings"].append("deliverable_namespace_invalid")
        return base
    if compose_states != ["file", "file", "file"] or edit_states != [
        "file",
        "file",
        "file",
    ]:
        base["state"] = "partial"
        base["ready_to_compose"] = True
        base["warnings"].append("deliverable_set_incomplete")
        return base
    try:
        qa, _output_bytes, _srt_bytes = (
            drama_compositor._require_workspace_compose_result_under_lock(
                root,
                timeline,
                maximum_output_bytes=MAX_WEB_COMPOSE_MP4_BYTES,
            )
        )
        edit, _ass_bytes, _project_bytes = (
            drama_edit_export._require_workspace_editable_sidecars_under_lock(
                workspace, timeline
            )
        )
    except (
        drama_compositor.DramaComposeError,
        drama_edit_export.DramaEditExportError,
        OSError,
        TypeError,
        ValueError,
    ):
        base["state"] = "invalid"
        base["ready_to_compose"] = True
        base["warnings"].append("deliverable_verification_failed")
        return base
    base["state"] = "complete"
    base["ready_to_compose"] = False
    base["qa"] = {
        "status": qa.status,
        "acceptance_level": qa.acceptance_level,
        "profile": qa.profile,
        "duration_ms": qa.duration_ms,
        "required_shot_count": len(qa.required_shot_ids),
        "covered_shot_count": len(qa.covered_shot_ids),
        "output_size_bytes": qa.output_size_bytes,
        "output_sha256": qa.output_sha256,
        "qa_fingerprint": qa.qa_fingerprint,
        "export_fingerprint": edit.export_fingerprint,
    }
    base["deliverables"] = [
        {
            "kind": kind,
            "filename": DELIVERABLE_FILENAMES[kind].format(
                episode_no=timeline.episode_no
            ),
            "url": _download_url(workspace, timeline, kind),
        }
        for kind in ("mp4", "srt", "ass", "edit")
    ]
    return base


def run_workspace_compose_job(
    workspace: str,
    *,
    episode_no: int,
    progress_cb: Any,
) -> dict[str, Any]:
    """Run local F1 then F2; only the exact four-file delivery is committed."""

    if not _COMPOSE_CAPACITY.acquire(blocking=False):
        raise DramaComposeWebError("compose_capacity_busy")
    try:
        progress_cb("validate-timeline", 0.05)
        timeline = require_current_workspace_timeline(
            workspace, episode_no=episode_no
        )
        cancel_check = getattr(progress_cb, "check_cancelled", lambda: None)

        def current_check() -> None:
            current = _current_timeline_under_lock(
                workspace,
                paths.workspace_root(workspace),
                episode_no,
            )
            if current != timeline:
                raise DramaComposeWebError("timeline_stale")

        progress_cb("compose-local", 0.15)
        drama_compositor.compose_workspace_timeline(
            workspace,
            timeline,
            precompose_check=current_check,
            checkpoint=cancel_check,
        )
        progress_cb("verify-compose", 0.72)
        qa = drama_compositor.require_workspace_compose_result(
            workspace,
            timeline,
            maximum_output_bytes=MAX_WEB_COMPOSE_MP4_BYTES,
        )
        progress_cb("export-edit-project", 0.80)
        drama_edit_export.export_workspace_editable_sidecars(
            workspace,
            timeline,
            preexport_check=current_check,
        )
        progress_cb("verify-delivery", 0.95)
        edit = drama_edit_export.require_workspace_editable_sidecars(
            workspace, timeline
        )
        # Never report committed until D4/E3/source are still current after
        # both independently locked F1/F2 commits.
        final_timeline = require_current_workspace_timeline(
            workspace, episode_no=episode_no
        )
        if final_timeline != timeline:
            raise DramaComposeWebError("timeline_stale")
        return {
            "status": "succeeded",
            "station": "compose",
            "episode_no": timeline.episode_no,
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "qa_fingerprint": qa.qa_fingerprint,
            "export_fingerprint": edit.export_fingerprint,
            "file_size_bytes": qa.output_size_bytes,
            "acceptance_level": qa.acceptance_level,
            "committed": True,
        }
    finally:
        _COMPOSE_CAPACITY.release()


def load_exact_compose_deliverable(
    workspace: str,
    *,
    episode_no: int,
    timeline_fingerprint: str,
    kind: str,
) -> tuple[bytes, str, str]:
    """Authorize a delivery only after exact F1/F2 regeneration checks."""

    if kind not in MAX_DELIVERABLE_BYTES:
        raise FileNotFoundError("deliverable not found")
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-compose-web-download"
        ):
            root = paths.workspace_root(workspace)
            timeline = _current_timeline_under_lock(
                workspace, root, episode_no
            )
            if timeline.timeline_fingerprint != timeline_fingerprint:
                raise FileNotFoundError("deliverable not found")
            _qa, output_bytes, srt_bytes = (
                drama_compositor._require_workspace_compose_result_under_lock(
                    root,
                    timeline,
                    maximum_output_bytes=MAX_WEB_COMPOSE_MP4_BYTES,
                )
            )
            _edit, ass_bytes, project_bytes = (
                drama_edit_export._require_workspace_editable_sidecars_under_lock(
                    workspace, timeline
                )
            )
            payload = {
                "mp4": output_bytes,
                "srt": srt_bytes,
                "ass": ass_bytes,
                "edit": project_bytes,
            }[kind]
    except FileNotFoundError:
        raise
    except WorkspaceLocked:
        raise DramaComposeWebError("workspace_busy") from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaComposeWebError("deliverable_unavailable") from None
    if len(payload) > MAX_DELIVERABLE_BYTES[kind]:
        raise DramaComposeWebError("deliverable_unavailable")
    return (
        payload,
        DELIVERABLE_CONTENT_TYPES[kind],
        DELIVERABLE_FILENAMES[kind].format(episode_no=episode_no),
    )
