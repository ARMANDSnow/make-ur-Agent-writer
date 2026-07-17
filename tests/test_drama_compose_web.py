"""iter132 F3 Web compose, durable QA truth, and exact delivery."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from src import (
    drama_audio,
    drama_asset_versions,
    drama_compose_web,
    drama_compositor,
    drama_edit_export,
    drama_render_store,
    drama_reviewer,
    drama_shot_image_candidate_store,
    drama_shot_image_store,
    drama_shot_video_continuity,
    drama_shot_video_candidate_store,
    drama_shot_video_store,
    drama_store,
    drama_timeline,
    drama_tts_attempts,
    paths,
    storyboard_builder,
)
from src.drama_media_qa import (
    DramaMediaQaError,
    build_compose_qa_report,
    probe_media,
)
from src.drama_schemas import character_paths, episode_paths
from src.drama_tts_attempt_store import (
    LocalFakeTtsAdapter,
    run_tts_attempt,
    tts_identity_from_authorization,
)
from src.web import jobs, routes
from src.utils import read_json, write_json
from tests._drama_shot_video_candidate_base import (
    DramaShotVideoCandidateFixture,
)


class DramaComposeWebTests(DramaShotVideoCandidateFixture):
    _COMPOSE_HEADERS = {
        "content-type": "application/json",
        "x-drama-compose-intent": "run-local-v1",
    }
    @staticmethod
    def _json(response: tuple) -> tuple[int, dict]:
        status, content_type, body = response[:3]
        assert "application/json" in content_type
        return status, json.loads(body)

    def _episode_two_video_sources(self, name: str):
        sources = self._seed_video_candidate_sources(name)
        self._write_setup(name, hook=True, episode_no=2)
        write_json(
            episode_paths(name, episode_no=2).storyboard_path,
            storyboard_builder.run(name, mock=True, episode_no=2),
        )
        sheet_path = character_paths(name).sheet_path
        sheet = read_json(sheet_path)
        sheet["episode_no"] = 2
        sheet["generated_episode_nos"] = sorted(
            set(sheet.get("generated_episode_nos", [])) | {2}
        )
        for row in sheet["characters"]:
            row["appearances"] = sorted(set(row.get("appearances", [])) | {2})
        write_json(sheet_path, sheet)
        write_json(
            episode_paths(name, episode_no=2).review_path,
            drama_reviewer.run(name, mock=True, episode_no=2),
        )
        drama_store.assemble_episode(name, episode_no=2)
        render_plan = drama_render_store.create_render_plan(
            name, episode_no=2
        )
        drama_asset_versions.create_episode_asset_manifest(
            name, episode_no=2
        )
        scene_mapping = {shot.shot_id: "s001" for shot in render_plan.shots}
        drama_asset_versions.create_episode_scene_asset_manifest(
            name,
            episode_no=2,
            shot_scene_ids=scene_mapping,
        )
        drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            name,
            episode_no=2,
            shot_asset_ids={shot.shot_id: [] for shot in render_plan.shots},
        )
        character_mapping = {
            shot.shot_id: [render_plan.frozen_character_ids[0]]
            for shot in render_plan.shots
        }
        image_plan = drama_shot_image_store.create_episode_shot_image_plan(
            name,
            episode_no=2,
            shot_character_ids=character_mapping,
            reference_policy=sources["policy"],
        )
        images = (
            drama_shot_image_candidate_store
            .create_episode_shot_image_candidate_manifest(
                name, episode_no=2
            )
        )
        for index, spec in enumerate(image_plan.shot_specs):
            images, candidate = (
                drama_shot_image_candidate_store
                .append_local_shot_image_candidate(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    png_bytes=self._png(
                        rgba=bytes((index + 1, index + 2, index + 3, 255))
                    ),
                    expected_manifest_fingerprint=images.manifest_fingerprint,
                )
            )
            pool = next(
                item for item in images.shots if item.shot_id == spec.shot_id
            )
            images = (
                drama_shot_image_candidate_store
                .select_episode_shot_image_frame(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    frame="first",
                    binding={
                        "kind": "direct",
                        "candidate_id": candidate.candidate_id,
                        "candidate_fingerprint": candidate.candidate_fingerprint,
                    },
                    expected_selection_revision=pool.selection_revision,
                    expected_current_binding=None,
                    expected_manifest_fingerprint=images.manifest_fingerprint,
                )
            )
        video_plan = drama_shot_video_store.create_episode_shot_video_plan(
            name, episode_no=2
        )
        videos = (
            drama_shot_video_candidate_store
            .create_episode_shot_video_candidate_manifest(
                name, episode_no=2
            )
        )
        for index, spec in enumerate(video_plan.shot_specs):
            videos, candidate = (
                drama_shot_video_candidate_store
                .append_local_shot_video_candidate(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    mp4_bytes=self._mp4_variant(index),
                    expected_manifest_fingerprint=videos.manifest_fingerprint,
                )
            )
            pool = next(
                item for item in videos.shots if item.shot_id == spec.shot_id
            )
            videos = (
                drama_shot_video_candidate_store
                .select_episode_shot_video_candidate(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    selection={
                        "candidate_id": candidate.candidate_id,
                        "candidate_fingerprint": candidate.candidate_fingerprint,
                    },
                    expected_selection_revision=pool.selection_revision,
                    expected_current_selection=None,
                    expected_manifest_fingerprint=videos.manifest_fingerprint,
                )
            )
        sources.update(
            {
                "render_plan": render_plan,
                "video_plan": video_plan,
                "video_candidate_manifest": videos,
            }
        )
        return sources

    def _timeline_sources(self, name: str, *, episode_no: int = 1):
        if episode_no == 2:
            sources = self._episode_two_video_sources(name)
        else:
            sources = self._seed_video_candidate_sources(name)
        plan = sources["video_plan"]
        videos = sources["video_candidate_manifest"]
        if episode_no == 1:
            for index, spec in enumerate(plan.shot_specs):
                videos, candidate = self._append_video_candidate(
                    name, videos, spec.shot_id, marker=index
                )
                videos = self._select_video_candidate(name, videos, candidate)
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, videos
        )
        render_plan = sources["render_plan"]
        character = drama_audio.build_voice_profile(
            scope="character",
            character_id=render_plan.frozen_character_ids[0],
            display_name="主角",
            language_tag="zh-CN",
            provider_id="fixture",
            model_id="mock/tts-v1",
            voice_name="lead",
        )
        narrator = drama_audio.build_voice_profile(
            scope="narrator",
            character_id=None,
            display_name="旁白",
            language_tag="zh-CN",
            provider_id="fixture",
            model_id="mock/tts-v1",
            voice_name="narrator",
        )
        assignments = []
        for segment in render_plan.spoken_segments:
            profile = narrator if segment.kind == "narration" else character
            assignments.append(
                drama_audio.build_voice_assignment(
                    segment_id=segment.segment_id,
                    profile=profile,
                    speaker_character_id=(
                        None
                        if segment.kind == "narration"
                        else render_plan.frozen_character_ids[0]
                    ),
                )
            )
        audio_manifest = drama_audio.build_audio_manifest(
            render_plan,
            profiles=[character, narrator],
            assignments=assignments,
        )
        capability = drama_tts_attempts.build_tts_provider_capability(
            backend_id="fake-tts",
            capability_version="v1",
            provider_id="fixture",
            model_id="mock/tts-v1",
            sample_rate=16000,
        )
        wav = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=20, sample_rate=16000
        )
        records = []
        for utterance in audio_manifest.utterances:
            authorization = drama_tts_attempts.build_tts_authorization(
                utterance,
                capability,
                provider_fingerprint="1" * 64,
                model_fingerprint="2" * 64,
                account_fingerprint="3" * 64,
                endpoint_fingerprint="4" * 64,
                auth_fingerprint="5" * 64,
            )
            records.append(
                run_tts_attempt(
                    name,
                    utterance,
                    capability=capability,
                    authorization=authorization,
                    adapter=LocalFakeTtsAdapter(
                        identity=tts_identity_from_authorization(
                            capability, authorization
                        ),
                        wav_bytes=wav,
                    ),
                )
            )
        return plan, videos, report, audio_manifest, records

    def _persist(self, name: str, *, episode_no: int = 1):
        _, _, _, audio_manifest, records = self._timeline_sources(
            name, episode_no=episode_no
        )
        timeline = drama_compose_web.persist_workspace_timeline_manifest(
            name,
            audio_manifest,
            records,
            episode_no=episode_no,
        )
        return timeline

    def test_only_production_e3_inputs_can_create_the_web_timeline(self) -> None:
        name = "compose-web-store"
        timeline = self._persist(name)
        loaded = drama_compose_web.require_current_workspace_timeline(name)
        self.assertEqual(loaded, timeline)
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "ready")
        self.assertTrue(overview["ready_to_compose"])
        stored = (
            paths.workspace_root(name)
            / "outputs/drama/timeline/episode_001.timeline.json"
        )
        envelope = json.loads(stored.read_text("utf-8"))
        self.assertEqual(envelope["timeline_fingerprint"], timeline.timeline_fingerprint)
        self.assertEqual(envelope["timeline"], timeline.model_dump())

        status, payload = self._json(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/compose",
                json.dumps({"episode_no": 1, "timeline": timeline.model_dump()}).encode(),
                self._COMPOSE_HEADERS,
            )
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown drama compose params", payload["error"])
        self.assertEqual(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/compose",
                b'{"episode_no":1}',
            )[0],
            415,
        )
        self.assertEqual(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/compose",
                b"{}" + b" " * (32 * 1024),
                self._COMPOSE_HEADERS,
            )[0],
            413,
        )
        generic = self._json(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/run",
                b'{"step":"drama-compose","params":{"episode_no":1}}',
            )
        )
        self.assertEqual(generic[0], 400)

    def test_e3_gate_auto_persists_and_subtitle_revision_is_cas_bound(self) -> None:
        name = "compose-web-e3"
        _, _, _, audio_manifest, records = self._timeline_sources(name)
        timeline = drama_timeline.require_workspace_timeline_manifest(
            name, audio_manifest, records
        )
        self.assertEqual(
            drama_compose_web.require_current_workspace_timeline(name),
            timeline,
        )
        cue = timeline.subtitle_cues[0]
        revised = drama_compose_web.persist_workspace_revised_timeline(
            name,
            {cue.cue_id: "同源修订字幕"},
            expected_timeline_fingerprint=timeline.timeline_fingerprint,
        )
        replayed = drama_compose_web.persist_workspace_revised_timeline(
            name,
            {cue.cue_id: "同源修订字幕"},
            expected_timeline_fingerprint=timeline.timeline_fingerprint,
        )
        self.assertEqual(replayed, revised)
        regenerated = drama_timeline.require_workspace_timeline_manifest(
            name, audio_manifest, records
        )
        self.assertEqual(regenerated, revised)
        self.assertEqual(
            drama_compose_web.require_current_workspace_timeline(name),
            revised,
        )
        self.assertIn(
            "同源修订字幕",
            drama_timeline.export_timeline_srt(revised).content,
        )
        self.assertIn(
            "同源修订字幕",
            drama_edit_export.export_timeline_ass(revised).content,
        )
        self.assertEqual(
            drama_edit_export.build_editable_timeline_project(revised)
            .subtitles[0]
            .text,
            "同源修订字幕",
        )
        with self.assertRaisesRegex(
            drama_compose_web.DramaComposeWebError,
            "timeline_conflict",
        ):
            drama_compose_web.persist_workspace_revised_timeline(
                name,
                {revised.subtitle_cues[0].cue_id: "旧 CAS 不得覆盖"},
                expected_timeline_fingerprint=timeline.timeline_fingerprint,
            )

    def test_timeline_revision_prunes_unreachable_episode_deliverables(self) -> None:
        name = "compose-web-retention"
        timeline = self._persist(name)
        root = paths.workspace_root(name)
        stale_paths = [
            drama_compositor.build_compose_plan(timeline).output_path,
            drama_compositor.build_compose_plan(timeline).srt_path,
            drama_compositor.build_compose_plan(timeline).qa_path,
            *drama_edit_export._export_paths(timeline),
        ]
        for relative in stale_paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"stale")
        cue = timeline.subtitle_cues[0]
        revised = drama_compose_web.persist_workspace_revised_timeline(
            name,
            {cue.cue_id: "清理旧交付"},
            expected_timeline_fingerprint=timeline.timeline_fingerprint,
        )
        self.assertNotEqual(revised.timeline_fingerprint, timeline.timeline_fingerprint)
        self.assertTrue(all(not (root / relative).exists() for relative in stale_paths))

    def test_subtitle_replay_completes_pruning_after_interrupted_commit(self) -> None:
        name = "compose-web-retention-replay"
        timeline = self._persist(name)
        root = paths.workspace_root(name)
        stale_path = drama_compositor.build_compose_plan(timeline).output_path
        target = root / stale_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"stale")
        cue = timeline.subtitle_cues[0]
        original_prune = (
            drama_compose_web._prune_stale_deliverables_under_lock
        )
        with patch(
            "src.drama_compose_web._prune_stale_deliverables_under_lock",
            side_effect=drama_compose_web.DramaComposeWebError(
                "deliverable_retention_failed"
            ),
        ):
            with self.assertRaisesRegex(
                drama_compose_web.DramaComposeWebError,
                "deliverable_retention_failed",
            ):
                drama_compose_web.persist_workspace_revised_timeline(
                    name,
                    {cue.cue_id: "中断后重放"},
                    expected_timeline_fingerprint=timeline.timeline_fingerprint,
                )
        self.assertTrue(target.exists())
        with patch(
            "src.drama_compose_web._prune_stale_deliverables_under_lock",
            wraps=original_prune,
        ) as prune:
            replayed = drama_compose_web.persist_workspace_revised_timeline(
                name,
                {cue.cue_id: "中断后重放"},
                expected_timeline_fingerprint=timeline.timeline_fingerprint,
            )
        self.assertNotEqual(
            replayed.timeline_fingerprint, timeline.timeline_fingerprint
        )
        prune.assert_called_once()
        self.assertFalse(target.exists())

    def test_timeline_store_rejects_symlinked_parent(self) -> None:
        name = "compose-web-timeline-symlink"
        _, _, _, audio_manifest, records = self._timeline_sources(name)
        root = paths.workspace_root(name)
        owned = root / "owned"
        owned.mkdir()
        timeline_dir = root / "outputs/drama/timeline"
        timeline_dir.parent.mkdir(parents=True, exist_ok=True)
        timeline_dir.symlink_to(owned)
        with self.assertRaisesRegex(
            drama_compose_web.DramaComposeWebError,
            "timeline_store_failed",
        ):
            drama_timeline.require_workspace_timeline_manifest(
                name, audio_manifest, records
            )
        self.assertEqual(list(owned.iterdir()), [])

    def test_upstream_or_source_change_marks_timeline_stale(self) -> None:
        name = "compose-web-stale"
        timeline = self._persist(name)
        source = paths.workspace_root(name) / timeline.video_clips[0].artifact_path
        source.write_bytes(b"tampered")
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "stale")
        self.assertFalse(overview["ready_to_compose"])
        self.assertIn(overview["warnings"][0], {"timeline_stale", "timeline_source_stale"})

    def test_partial_invalid_and_symlink_namespaces_never_become_complete(self) -> None:
        name = "compose-web-partial"
        timeline = self._persist(name)
        plan = drama_compositor.build_compose_plan(timeline)
        partial = paths.workspace_root(name) / plan.srt_path
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text("partial", encoding="utf-8")
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "partial")

        partial.unlink()
        owned = partial.with_suffix(".owned")
        owned.write_text("owned", encoding="utf-8")
        partial.symlink_to(owned.name)
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "invalid")
        self.assertEqual(overview["deliverables"], [])

    def test_local_compose_survives_job_memory_loss_and_downloads_exact_files(self) -> None:
        name = "compose-web-e2e"
        timeline = self._persist(name)
        progress: list[tuple[str, float]] = []
        result = drama_compose_web.run_workspace_compose_job(
            name,
            episode_no=1,
            progress_cb=lambda step, fraction: progress.append((step, fraction)),
        )
        self.assertTrue(result["committed"])
        self.assertEqual(result["acceptance_level"], "local-e2e")
        self.assertEqual(progress[-1][0], "verify-delivery")
        jobs.reset_for_tests()

        status, overview = self._json(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/compose?episode_no=1",
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(overview["state"], "complete")
        self.assertIsNone(overview["job"])
        self.assertEqual(timeline.total_duration_ms, 402)
        self.assertEqual(overview["qa"]["duration_ms"], 440)
        self.assertEqual(
            [item["kind"] for item in overview["deliverables"]],
            ["mp4", "srt", "ass", "edit"],
        )
        plan = drama_compositor.build_compose_plan(timeline)
        root = paths.workspace_root(name)
        output_bytes = (root / plan.output_path).read_bytes()
        srt_bytes = (root / plan.srt_path).read_bytes()
        probe = probe_media(root, plan.output_path)
        with self.assertRaises(DramaMediaQaError):
            build_compose_qa_report(
                plan,
                replace(probe, video_duration_ms=480),
                output_bytes=output_bytes,
                srt_bytes=srt_bytes,
            )

        base = (
            f"/api/workspace/{name}/drama/compose/1/"
            f"{timeline.timeline_fingerprint}"
        )
        mp4 = routes.dispatch("GET", f"{base}/mp4")
        self.assertEqual(mp4[0], 200)
        self.assertEqual(mp4[1], "video/mp4")
        self.assertEqual(mp4[3]["Content-Disposition"], 'attachment; filename="episode_001.mp4"')
        head = routes.dispatch("HEAD", f"{base}/mp4")
        self.assertEqual(head[0], 200)
        self.assertEqual(head[2], b"")
        ranged = routes.dispatch(
            "GET",
            f"{base}/mp4",
            headers={"range": "bytes=0-31"},
        )
        self.assertEqual(ranged[0], 206)
        self.assertEqual(len(ranged[2]), 32)
        self.assertTrue(ranged[3]["Content-Range"].startswith("bytes 0-31/"))
        for kind, suffix in (
            ("srt", ".srt"),
            ("ass", ".ass"),
            ("edit", ".edit.json"),
        ):
            response = routes.dispatch("GET", f"{base}/{kind}")
            self.assertEqual(response[0], 200)
            self.assertTrue(response[3]["Content-Disposition"].endswith(f'{suffix}"'))
        wrong = routes.dispatch(
            "GET",
            f"/api/workspace/{name}/drama/compose/1/{'0' * 64}/mp4",
        )
        self.assertEqual(wrong[0], 404)

        self.assertEqual(
            drama_compose_web.MAX_WEB_COMPOSE_MP4_BYTES,
            drama_compositor.MAX_COMPOSE_OUTPUT_BYTES,
        )
        qa_path = root / plan.qa_path
        oversized = json.loads(qa_path.read_text("utf-8"))
        oversized["output_size_bytes"] = (
            drama_compose_web.MAX_WEB_COMPOSE_MP4_BYTES + 1
        )
        oversized["qa_fingerprint"] = drama_compositor._canonical_sha256(
            {
                key: value
                for key, value in oversized.items()
                if key != "qa_fingerprint"
            }
        )
        qa_path.write_text(
            json.dumps(oversized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            drama_compositor.DramaComposeError,
            "compose result was rejected",
        ):
            drama_compositor.require_workspace_compose_result(
                name,
                timeline,
                maximum_output_bytes=drama_compose_web.MAX_WEB_COMPOSE_MP4_BYTES,
            )

    def test_tampered_delivery_is_409_and_never_streamed(self) -> None:
        name = "compose-web-tamper"
        timeline = self._persist(name)
        drama_compose_web.run_workspace_compose_job(
            name, episode_no=1, progress_cb=lambda *_: None
        )
        plan = drama_compositor.build_compose_plan(timeline)
        (paths.workspace_root(name) / plan.srt_path).write_text(
            "forged", encoding="utf-8"
        )
        response = routes.dispatch(
            "GET",
            (
                f"/api/workspace/{name}/drama/compose/1/"
                f"{timeline.timeline_fingerprint}/srt"
            ),
        )
        self.assertEqual(response[0], 409)
        self.assertNotIn(b"forged", response[2])

    def test_source_change_during_f1_f2_never_reports_committed(self) -> None:
        name = "compose-web-race"
        timeline = self._persist(name)
        source = paths.workspace_root(name) / timeline.video_clips[0].artifact_path

        def finish_then_tamper(*_args, **_kwargs):
            source.write_bytes(b"changed-after-export")
            return SimpleNamespace(export_fingerprint="3" * 64)

        with (
            patch("src.drama_compositor.compose_workspace_timeline"),
            patch(
                "src.drama_compositor.require_workspace_compose_result",
                return_value=SimpleNamespace(
                    qa_fingerprint="2" * 64,
                    output_size_bytes=123,
                    acceptance_level="local-e2e",
                ),
            ),
            patch("src.drama_edit_export.export_workspace_editable_sidecars"),
            patch(
                "src.drama_edit_export.require_workspace_editable_sidecars",
                side_effect=finish_then_tamper,
            ),
        ):
            with self.assertRaisesRegex(
                drama_compose_web.DramaComposeWebError,
                "timeline_(?:source_)?stale",
            ):
                drama_compose_web.run_workspace_compose_job(
                    name,
                    episode_no=1,
                    progress_cb=lambda *_: None,
                )

    def test_timeline_switch_before_f1_or_f2_is_rejected_inside_stage_lock(self) -> None:
        for station in ("f1", "f2"):
            name = f"compose-web-timeline-race-{station}"
            timeline = self._persist(name)
            cue = timeline.subtitle_cues[0]

            def revise_then_check(*_args, **kwargs):
                drama_compose_web.persist_workspace_revised_timeline(
                    name,
                    {cue.cue_id: f"{station}-new"},
                    expected_timeline_fingerprint=timeline.timeline_fingerprint,
                )
                kwargs[
                    "precompose_check"
                    if station == "f1"
                    else "preexport_check"
                ]()

            compose_patch = (
                patch(
                    "src.drama_compositor.compose_workspace_timeline",
                    side_effect=revise_then_check,
                )
                if station == "f1"
                else patch("src.drama_compositor.compose_workspace_timeline")
            )
            export_patch = (
                patch("src.drama_edit_export.export_workspace_editable_sidecars")
                if station == "f1"
                else patch(
                    "src.drama_edit_export.export_workspace_editable_sidecars",
                    side_effect=revise_then_check,
                )
            )
            with (
                compose_patch,
                patch(
                    "src.drama_compositor.require_workspace_compose_result",
                    return_value=SimpleNamespace(
                        qa_fingerprint="2" * 64,
                        output_size_bytes=123,
                        acceptance_level="local-e2e",
                    ),
                ),
                export_patch,
            ):
                with self.assertRaisesRegex(
                    drama_compose_web.DramaComposeWebError,
                    "timeline_stale",
                ):
                    drama_compose_web.run_workspace_compose_job(
                        name,
                        episode_no=1,
                        progress_cb=lambda *_: None,
                    )

    def test_ffmpeg_checkpoint_cancels_and_global_capacity_is_bounded(self) -> None:
        name = "compose-web-cancel"
        timeline = self._persist(name)

        def progress(*_args):
            return None

        def cancelled():
            raise jobs.JobCancelled("cancelled in ffmpeg")

        progress.check_cancelled = cancelled
        started = time.monotonic()
        with self.assertRaisesRegex(jobs.JobCancelled, "cancelled in ffmpeg"):
            drama_compose_web.run_workspace_compose_job(
                name,
                episode_no=1,
                progress_cb=progress,
            )
        self.assertLess(time.monotonic() - started, 5)
        plan = drama_compositor.build_compose_plan(timeline)
        self.assertFalse((paths.workspace_root(name) / plan.output_path).exists())
        self.assertFalse((paths.workspace_root(name) / plan.qa_path).exists())

        self.assertTrue(drama_compose_web._COMPOSE_CAPACITY.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(
                drama_compose_web.DramaComposeWebError,
                "compose_capacity_busy",
            ):
                drama_compose_web.run_workspace_compose_job(
                    name,
                    episode_no=1,
                    progress_cb=lambda *_: None,
                )
        finally:
            drama_compose_web._COMPOSE_CAPACITY.release()

    def test_compose_source_set_has_aggregate_cap(self) -> None:
        name = "compose-web-source-cap"
        timeline = self._persist(name)
        with patch("src.drama_compositor.MAX_COMPOSE_SOURCE_SET_BYTES", 1):
            with self.assertRaisesRegex(
                drama_compositor.DramaComposeError,
                "source set exceeds",
            ):
                drama_compositor._validate_sources(
                    paths.workspace_root(name), timeline
                )

    def test_job_route_is_allowlisted_and_reports_durable_completion(self) -> None:
        name = "compose-web-job"
        self._persist(name)
        with patch(
            "src.drama_compose_web.run_workspace_compose_job",
            return_value={
                "status": "succeeded",
                "station": "compose",
                "episode_no": 1,
                "timeline_fingerprint": "1" * 64,
                "qa_fingerprint": "2" * 64,
                "export_fingerprint": "3" * 64,
                "file_size_bytes": 123,
                "acceptance_level": "local-e2e",
                "committed": True,
            },
        ):
            status, payload = self._json(
                routes.dispatch(
                    "POST",
                    f"/api/workspace/{name}/drama/compose",
                    b'{"episode_no":1}',
                    self._COMPOSE_HEADERS,
                )
            )
            self.assertEqual(status, 202)
            deadline = time.time() + 3
            while time.time() < deadline:
                job = jobs.get_job(payload["job_id"])
                if job and job["status"] not in {"pending", "running"}:
                    break
                time.sleep(0.01)
        job = jobs.get_job(payload["job_id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(
            job["result_summary"]["timeline_fingerprint"],
            "1" * 64,
        )
        page = routes.dispatch("GET", f"/w/{name}/compose")
        self.assertEqual(page[0], 200)
        self.assertIn(b"compose-page-root", page[2])

    def test_job_blocker_reason_and_execution_failure_taxonomy(self) -> None:
        missing = "compose-web-missing-job"
        self._make_drama_workspace(missing)
        status, payload = self._json(
            routes.dispatch(
                "POST",
                f"/api/workspace/{missing}/drama/compose",
                b'{"episode_no":1}',
                self._COMPOSE_HEADERS,
            )
        )
        self.assertEqual(status, 202)
        deadline = time.time() + 3
        while time.time() < deadline:
            blocked = jobs.get_job(payload["job_id"])
            if blocked and blocked["status"] not in {"pending", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(
            blocked["result_summary"]["first_blocked"]["reason"],
            "drama_timeline_missing",
        )

        failed_name = "compose-web-failed-job"
        self._persist(failed_name)
        with patch(
            "src.drama_compose_web.run_workspace_compose_job",
            side_effect=drama_compositor.DramaComposeError(
                "ffmpeg composition failed"
            ),
        ):
            failed = jobs.start_job(
                failed_name, "drama-compose", {"episode_no": 1}
            )
            deadline = time.time() + 3
            while time.time() < deadline:
                failure = jobs.get_job(failed["job_id"])
                if failure and failure["status"] not in {"pending", "running"}:
                    break
                time.sleep(0.01)
        self.assertEqual(failure["status"], "failed")
        self.assertNotIn(str(paths.workspace_root(failed_name)), failure["error"])

    def test_compose_job_projection_is_episode_scoped(self) -> None:
        name = "compose-web-episode-job"
        self._persist(name)
        started = threading.Event()
        release = threading.Event()

        def slow_job(*_args, **_kwargs):
            started.set()
            release.wait(timeout=3)
            return {
                "status": "succeeded",
                "station": "compose",
                "episode_no": 1,
                "committed": True,
            }

        with patch(
            "src.drama_compose_web.run_workspace_compose_job",
            side_effect=slow_job,
        ):
            job = jobs.start_job(name, "drama-compose", {"episode_no": 1})
            self.assertTrue(started.wait(timeout=2))
            try:
                status, episode_two = self._json(
                    routes.dispatch(
                        "GET",
                        f"/api/workspace/{name}/drama/compose?episode_no=2",
                    )
                )
                self.assertEqual(status, 200)
                self.assertIsNone(episode_two["job"])
            finally:
                release.set()
            deadline = time.time() + 3
            while time.time() < deadline:
                current = jobs.get_job(job["job_id"])
                if current and current["status"] not in {"pending", "running"}:
                    break
                time.sleep(0.01)

    def test_episode_two_paths_overview_and_exact_download_identity(self) -> None:
        name = "compose-web-episode-two"
        timeline = self._persist(name, episode_no=2)
        self.assertEqual(
            drama_compose_web.require_current_workspace_timeline(
                name, episode_no=2
            ),
            timeline,
        )
        plan = drama_compositor.build_compose_plan(timeline)
        self.assertIn("/episode_002/", plan.output_path)
        self.assertIn("/episode_002/", plan.srt_path)
        self.assertTrue(
            all(
                "/episode_002/" in path
                for path in drama_edit_export._export_paths(timeline)
            )
        )
        status, overview = self._json(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/compose?episode_no=2",
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(overview["state"], "ready")
        self.assertEqual(overview["episode_no"], 2)
        self.assertEqual(
            overview["timeline_fingerprint"], timeline.timeline_fingerprint
        )
        result = drama_compose_web.run_workspace_compose_job(
            name, episode_no=2, progress_cb=lambda *_: None
        )
        self.assertEqual(result["episode_no"], 2)
        self.assertTrue(result["committed"])
        status, complete = self._json(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/compose?episode_no=2",
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(complete["state"], "complete")
        self.assertTrue(
            all("/2/" in item["url"] for item in complete["deliverables"])
        )
        base = (
            f"/api/workspace/{name}/drama/compose/2/"
            f"{timeline.timeline_fingerprint}"
        )
        for kind, filename in (
            ("mp4", "episode_002.mp4"),
            ("srt", "episode_002.srt"),
            ("ass", "episode_002.ass"),
            ("edit", "episode_002.edit.json"),
        ):
            response = routes.dispatch("GET", f"{base}/{kind}")
            self.assertEqual(response[0], 200)
            self.assertIn(
                f'filename="{filename}"',
                response[3]["Content-Disposition"],
            )
        wrong_episode = routes.dispatch(
            "GET",
            (
                f"/api/workspace/{name}/drama/compose/1/"
                f"{timeline.timeline_fingerprint}/mp4"
            ),
        )
        self.assertEqual(wrong_episode[0], 404)
