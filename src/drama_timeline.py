"""E3 single timeline projection and deterministic SRT export."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from . import paths
from .drama_audio import probe_mock_wav_fixture
from .drama_schemas import (
    AudioManifest,
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoContinuityReport,
    SrtArtifact,
    SubtitleCue,
    TimelineOptionalAudioClip,
    TimelineManifest,
    TtsAttemptRecord,
    _canonical_sha256,
)
from .drama_shot_video_candidate_store import (
    inspect_episode_shot_video_candidates,
)
from .drama_shot_video_continuity import (
    build_shot_video_continuity_report,
)
from .drama_shot_video_store import load_fresh_episode_shot_video_plan
from .drama_store import _read_strict_workspace_bytes
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


class DramaTimelineError(ValueError):
    pass


def _cue_payload(utterance: Any, *, start_ms: int, end_ms: int,
                 text: str | None = None, revision: int = 0) -> dict[str, Any]:
    payload = {
        "utterance_id": utterance.utterance_id,
        "source_text_sha256": hashlib.sha256(
            utterance.text.encode("utf-8")
        ).hexdigest(),
        "text": utterance.text if text is None else text,
        "revision": revision,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }
    fingerprint = _canonical_sha256(payload)
    return {
        "cue_id": f"cue_{fingerprint[:24]}",
        "cue_fingerprint": fingerprint,
        **payload,
    }


def _build_timeline_manifest_from_validated_sources(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    video_manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    continuity: ShotVideoContinuityReport | Mapping[str, Any],
    audio_manifest: AudioManifest | Mapping[str, Any],
    attempts: Sequence[TtsAttemptRecord | Mapping[str, Any]],
    *,
    bgm_policy: str = "optional",
    optional_audio_clips: Sequence[TimelineOptionalAudioClip | Mapping[str, Any]] = (),
) -> TimelineManifest:
    """Pure projection. Production callers must use require_workspace_timeline_manifest."""

    try:
        if not isinstance(attempts, (list, tuple)) or len(attempts) > 200:
            raise ValueError("attempts must be bounded")
        if not isinstance(optional_audio_clips, (list, tuple)) or len(optional_audio_clips) > 100:
            raise ValueError("optional audio clips must be bounded")
        current_plan = EpisodeShotVideoPlan(**(
            model_to_dict(plan) if isinstance(plan, EpisodeShotVideoPlan) else plan
        ))
        current_videos = EpisodeShotVideoCandidateManifest(**(
            model_to_dict(video_manifest)
            if isinstance(video_manifest, EpisodeShotVideoCandidateManifest)
            else video_manifest
        ))
        current_report = ShotVideoContinuityReport(**(
            model_to_dict(continuity)
            if isinstance(continuity, ShotVideoContinuityReport)
            else continuity
        ))
        current_audio = AudioManifest(**(
            model_to_dict(audio_manifest)
            if isinstance(audio_manifest, AudioManifest)
            else audio_manifest
        ))
        records = [
            TtsAttemptRecord(**(
                model_to_dict(item) if isinstance(item, TtsAttemptRecord) else item
            ))
            for item in attempts
        ]
        optional_clips = [
            TimelineOptionalAudioClip(**(
                model_to_dict(item) if isinstance(item, TimelineOptionalAudioClip)
                else item
            ))
            for item in optional_audio_clips
        ]
        optional_clips.sort(key=lambda item: (item.start_ms, item.end_ms, item.clip_id))
        rebuilt_report = build_shot_video_continuity_report(
            current_plan, current_videos
        )
        if current_report != rebuilt_report or not current_report.ready_for_compose:
            raise ValueError("D4 source is not production ready")
        if (
            current_audio.status != "ready"
            or current_audio.episode_no != current_plan.episode_no
            or current_audio.season_no != current_plan.season_no
            or current_audio.source_render_plan_fingerprint
            != current_plan.render_plan_fingerprint
        ):
            raise ValueError("audio manifest is stale or blocked")
        record_by_utterance = {item.spec.utterance_id: item for item in records}
        if len(record_by_utterance) != len(records):
            raise ValueError("duplicate TTS attempts")
        expected_ids = [item.utterance_id for item in current_audio.utterances]
        if set(record_by_utterance) != set(expected_ids):
            raise ValueError("TTS attempt coverage is incomplete")
        utterance_by_id = {item.utterance_id: item for item in current_audio.utterances}
        for utterance_id, record in record_by_utterance.items():
            utterance = utterance_by_id[utterance_id]
            if (
                record.status != "succeeded"
                or record.artifact is None
                or record.spec.episode_no != current_plan.episode_no
                or record.spec.utterance_spec_fingerprint
                != utterance.spec_fingerprint
                or record.spec.output_path != record.artifact.path
            ):
                raise ValueError("TTS attempt is stale or incomplete")

        pool_by_shot = {item.shot_id: item for item in current_videos.shots}
        video_clips: list[dict[str, Any]] = []
        video_by_shot: dict[str, tuple[int, int]] = {}
        cursor = 0
        for spec in current_plan.shot_specs:
            pool = pool_by_shot.get(spec.shot_id)
            if pool is None or pool.selected is None:
                raise ValueError("selected video is missing")
            candidate = next(
                (row for row in pool.candidates if row.candidate_id == pool.selected.candidate_id),
                None,
            )
            if candidate is None or candidate.is_placeholder:
                raise ValueError("selected video is not production ready")
            end = cursor + candidate.artifact.duration_milliseconds
            video_clips.append({
                "shot_id": spec.shot_id,
                "candidate_id": candidate.candidate_id,
                "artifact_path": candidate.artifact.path,
                "artifact_sha256": candidate.artifact.sha256,
                "artifact_duration_ms": candidate.artifact.duration_milliseconds,
                "start_ms": cursor,
                "end_ms": end,
            })
            video_by_shot[spec.shot_id] = (cursor, end)
            cursor = end

        audio_clips: list[dict[str, Any]] = []
        silence_clips: list[dict[str, Any]] = []
        subtitle_cues: list[dict[str, Any]] = []
        for spec in current_plan.shot_specs:
            shot_start, shot_end = video_by_shot[spec.shot_id]
            audio_cursor = shot_start
            utterances = [
                row for row in current_audio.utterances if row.shot_id == spec.shot_id
            ]
            for utterance in utterances:
                record = record_by_utterance[utterance.utterance_id]
                duration = record.artifact.duration_milliseconds
                end = audio_cursor + duration
                if end > shot_end:
                    raise ValueError("spoken audio exceeds its shot duration")
                audio_clips.append({
                    "utterance_id": utterance.utterance_id,
                    "segment_id": utterance.segment_id,
                    "shot_id": utterance.shot_id,
                    "kind": utterance.kind,
                    "artifact_path": record.artifact.path,
                    "artifact_sha256": record.artifact.sha256,
                    "artifact_duration_ms": duration,
                    "start_ms": audio_cursor,
                    "end_ms": end,
                })
                subtitle_cues.append(
                    _cue_payload(utterance, start_ms=audio_cursor, end_ms=end)
                )
                audio_cursor = end
            if audio_cursor < shot_end:
                silence_clips.append({
                    "shot_id": spec.shot_id,
                    "start_ms": audio_cursor,
                    "end_ms": shot_end,
                })
        if [item["utterance_id"] for item in audio_clips] != expected_ids:
            raise ValueError("audio utterance order or shot coverage is invalid")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "generator_version": "timeline-manifest-v1",
            "season_no": current_plan.season_no,
            "episode_no": current_plan.episode_no,
            "d4_report_fingerprint": current_report.report_fingerprint,
            "selected_bindings_fingerprint": current_report.selected_bindings_fingerprint,
            "audio_manifest_fingerprint": current_audio.manifest_fingerprint,
            "total_duration_ms": cursor,
            "video_clips": video_clips,
            "audio_clips": audio_clips,
            "silence_clips": silence_clips,
            "optional_audio_clips": [model_to_dict(item) for item in optional_clips],
            "subtitle_cues": subtitle_cues,
            "bgm_policy": bgm_policy,
            "warnings": (
                ["optional_bgm_missing"]
                if bgm_policy == "optional"
                and not any(item.kind == "bgm" for item in optional_clips)
                else []
            ),
        }
        payload["timeline_fingerprint"] = _canonical_sha256(payload)
        return TimelineManifest(**payload)
    except DramaTimelineError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaTimelineError("timeline input was rejected") from None


def require_workspace_timeline_manifest(
    workspace: str,
    audio_manifest: AudioManifest | Mapping[str, Any],
    attempts: Sequence[TtsAttemptRecord | Mapping[str, Any]],
    *,
    episode_no: int = 1,
    bgm_policy: str = "optional",
    optional_audio_clips: Sequence[TimelineOptionalAudioClip | Mapping[str, Any]] = (),
) -> TimelineManifest:
    """Production E3 gate: revalidate D4 and every succeeded WAV under the lock."""

    if not isinstance(attempts, (list, tuple)) or len(attempts) > 200:
        raise DramaTimelineError("TTS attempts must be bounded")
    if not isinstance(optional_audio_clips, (list, tuple)) or len(optional_audio_clips) > 100:
        raise DramaTimelineError("optional audio clips must be bounded")
    try:
        records = [
            TtsAttemptRecord(**(
                model_to_dict(item) if isinstance(item, TtsAttemptRecord) else item
            ))
            for item in attempts
        ]
        optional_clips = [
            TimelineOptionalAudioClip(**(
                model_to_dict(item) if isinstance(item, TimelineOptionalAudioClip)
                else item
            ))
            for item in optional_audio_clips
        ]
    except (RecursionError, TypeError, ValueError):
        raise DramaTimelineError("timeline artifact inputs were rejected") from None
    with use_workspace(workspace), acquire_write_lock(source="drama-timeline"):
        inspection = inspect_episode_shot_video_candidates(
            workspace, episode_no=episode_no
        )
        if inspection.state != "fresh" or inspection.manifest is None:
            raise DramaTimelineError("D4 source is not production ready")
        plan = load_fresh_episode_shot_video_plan(workspace, episode_no=episode_no)
        videos = inspection.manifest
        report = build_shot_video_continuity_report(plan, videos)
        if not report.ready_for_compose:
            raise DramaTimelineError("D4 source is not production ready")
        root = paths.workspace_root(workspace)
        for record in records:
            if record.status != "succeeded" or record.artifact is None:
                raise DramaTimelineError("TTS attempt is incomplete")
            try:
                data = _read_strict_workspace_bytes(
                    root,
                    root / record.artifact.path,
                    maximum=3_000_000,
                )
                probed = probe_mock_wav_fixture(data)
            except (OSError, TypeError, ValueError):
                raise DramaTimelineError("TTS artifact is invalid") from None
            if (
                probed["sha256"] != record.artifact.sha256
                or probed["size_bytes"] != record.artifact.size_bytes
                or probed["duration_milliseconds"]
                != record.artifact.duration_milliseconds
                or probed["sample_rate"] != record.artifact.sample_rate
            ):
                raise DramaTimelineError("TTS artifact is stale")
        for clip in optional_clips:
            try:
                data = _read_strict_workspace_bytes(
                    root, root / clip.artifact_path, maximum=10_000_000
                )
                probed = probe_mock_wav_fixture(data)
            except (OSError, TypeError, ValueError):
                raise DramaTimelineError("optional audio artifact is invalid") from None
            if (
                probed["sha256"] != clip.artifact_sha256
                or probed["size_bytes"] != clip.artifact_size_bytes
                or probed["duration_milliseconds"] != clip.artifact_duration_ms
                or probed["sample_rate"] != clip.sample_rate
            ):
                raise DramaTimelineError("optional audio artifact is stale")
        timeline = _build_timeline_manifest_from_validated_sources(
            plan, videos, report, audio_manifest, records,
            bgm_policy=bgm_policy, optional_audio_clips=optional_clips,
        )
        # E3 completion is also the durable F3 hand-off.  Import lazily to
        # avoid a module cycle at import time; the helper assumes this lock is
        # already held and never accepts arbitrary client TimelineManifest JSON.
        from .drama_compose_web import _persist_validated_timeline_under_lock

        return _persist_validated_timeline_under_lock(
            workspace,
            timeline,
            preserve_existing_revision=True,
        )


def revise_timeline_subtitles(
    manifest: TimelineManifest | Mapping[str, Any],
    revisions: Mapping[str, str],
) -> TimelineManifest:
    try:
        current = TimelineManifest(**(
            model_to_dict(manifest) if isinstance(manifest, TimelineManifest) else manifest
        ))
        if not isinstance(revisions, dict) or len(revisions) > 200:
            raise ValueError("subtitle revisions must be bounded")
        by_id = {item.cue_id: item for item in current.subtitle_cues}
        if not revisions or not set(revisions).issubset(by_id):
            raise ValueError("subtitle revision target is unknown")
        cues: list[dict[str, Any]] = []
        for cue in current.subtitle_cues:
            if cue.cue_id not in revisions:
                cues.append(model_to_dict(cue))
                continue
            payload = {
                "utterance_id": cue.utterance_id,
                "source_text_sha256": cue.source_text_sha256,
                "text": revisions[cue.cue_id],
                "revision": cue.revision + 1,
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
            }
            fingerprint = _canonical_sha256(payload)
            cues.append({
                "cue_id": f"cue_{fingerprint[:24]}",
                "cue_fingerprint": fingerprint,
                **payload,
            })
        payload = current.model_dump(exclude={"timeline_fingerprint"})
        payload["subtitle_cues"] = cues
        payload["timeline_fingerprint"] = _canonical_sha256(payload)
        return TimelineManifest(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaTimelineError("subtitle revision was rejected") from None


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def export_timeline_srt(
    manifest: TimelineManifest | Mapping[str, Any],
) -> SrtArtifact:
    try:
        current = TimelineManifest(**(
            model_to_dict(manifest) if isinstance(manifest, TimelineManifest) else manifest
        ))
        blocks = []
        for index, cue in enumerate(current.subtitle_cues, start=1):
            blocks.append(
                f"{index}\n{_srt_time(cue.start_ms)} --> {_srt_time(cue.end_ms)}\n{cue.text}\n"
            )
        content = "\n".join(blocks)
        return SrtArtifact(
            timeline_fingerprint=current.timeline_fingerprint,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            cue_count=len(current.subtitle_cues),
            content=content,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaTimelineError("SRT export was rejected") from None


def require_timeline_srt_artifact(
    manifest: TimelineManifest | Mapping[str, Any],
    artifact: SrtArtifact | Mapping[str, Any],
) -> SrtArtifact:
    """Authorize an SRT only by exact regeneration from its TimelineManifest."""

    try:
        expected = export_timeline_srt(manifest)
        supplied = SrtArtifact(**(
            model_to_dict(artifact) if isinstance(artifact, SrtArtifact) else artifact
        ))
        if supplied != expected:
            raise ValueError("SRT artifact does not match timeline")
        return expected
    except (DramaTimelineError, RecursionError, TypeError, ValueError):
        raise DramaTimelineError("SRT artifact was rejected") from None
