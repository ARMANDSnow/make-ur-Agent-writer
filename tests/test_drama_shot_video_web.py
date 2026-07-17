"""iter131: strict D2-D4 shot-video Web projection, media, and CAS."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from src import (
    drama_shot_image_candidate_store,
    drama_shot_video_store,
    drama_shot_video_web,
    paths,
)
from src.cli_workspace import init_workspace
from src.schemas import model_to_dict
from src.web import routes
from tests._drama_shot_video_candidate_base import DramaShotVideoCandidateFixture


class DramaShotVideoWebTests(DramaShotVideoCandidateFixture):
    _HEADERS = {
        "content-type": "application/json",
        "x-drama-shot-video-intent": "mutate-v1",
        "sec-fetch-site": "same-origin",
        "origin": "http://127.0.0.1:8765",
        "host": "127.0.0.1:8765",
    }

    @staticmethod
    def _decode(response: tuple) -> tuple[int, dict]:
        status, content_type, body = response[:3]
        assert "application/json" in content_type
        return status, json.loads(body)

    def _get(self, name: str, episode_no: int = 1) -> tuple[int, dict]:
        return self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/shot-videos?episode_no={episode_no}",
            )
        )

    def _post(self, name: str, payload: dict, *, headers: dict | None = None):
        return self._decode(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/shot-videos/select",
                json.dumps(payload).encode(),
                headers if headers is not None else self._HEADERS,
            )
        )

    def _seed_two_candidates(self, name: str):
        sources = self._seed_video_candidate_sources(name)
        manifest = sources["video_candidate_manifest"]
        shot_id = sources["video_plan"].shot_specs[0].shot_id
        manifest, first = self._append_video_candidate(
            name,
            manifest,
            shot_id,
            marker=1,
        )
        manifest, second = self._append_video_candidate(
            name,
            manifest,
            shot_id,
            marker=2,
        )
        return sources, manifest, first, second

    def test_page_and_missing_manifest_are_graceful(self) -> None:
        self._seed_shot_video_sources("shot-video-web-empty", previous_tail=True)
        drama_shot_video_store.create_episode_shot_video_plan(
            "shot-video-web-empty"
        )
        status, _content_type, body = routes.dispatch(
            "GET",
            "/w/shot-video-web-empty/shot-videos",
        )
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("镜头视频候选", html)
        self.assertIn('window.PAGE_KIND = "drama_shot_videos"', html)
        self.assertIn("shot-videos-page-root", html)
        self.assertIn("data-shot-video-select", routes.static.JS_DASHBOARD)
        self.assertIn('preload="none"', routes.static.JS_DASHBOARD)
        self.assertIn("data-shot-video-load-preview", routes.static.JS_DASHBOARD)
        self.assertIn("安全派生预览：静音，最长 30 秒", routes.static.JS_DASHBOARD)
        self.assertIn("此页不会提交视频任务", html)

        status, data = self._get("shot-video-web-empty")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "needs_shot_video_assets")
        self.assertEqual(data["shots"], [])
        self.assertIsNone(data["manifest_fingerprint"])
        self.assertFalse(data["mutation_allowed"])
        self.assertEqual(data["attempts"]["state"], "needs_attempts")

    def test_projection_is_allowlisted_sorted_and_does_not_leak_paid_state(self) -> None:
        _sources, manifest, first, second = self._seed_two_candidates(
            "shot-video-web-projection"
        )
        status, data = self._get("shot-video-web-projection")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "fresh")
        self.assertEqual(data["manifest_fingerprint"], manifest.manifest_fingerprint)
        shot = data["shots"][0]
        self.assertEqual(
            [item["candidate_id"] for item in shot["candidates"]],
            sorted([first.candidate_id, second.candidate_id]),
        )
        self.assertTrue(
            all(
                item["preview_url"].startswith("/api/workspace/")
                for item in shot["candidates"]
            )
        )
        self.assertTrue(all(item["current"] for item in shot["candidates"]))
        encoded = json.dumps(data)
        for forbidden in (
            "artifact.path",
            "outputs/episodes",
            "provider_task_id",
            "result_token",
            "submission_gate",
            "prompt_sha256",
            "backend_id",
            "account_fingerprint",
            "signed_url",
            str(paths.workspace_root("shot-video-web-projection")),
        ):
            self.assertNotIn(forbidden, encoded)

    def test_exact_mp4_route_revalidates_bytes_and_supports_head_and_range(self) -> None:
        _sources, _manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-mp4"
        )
        _status, data = self._get("shot-video-web-mp4")
        preview = next(
            item["preview_url"]
            for item in data["shots"][0]["candidates"]
            if item["candidate_id"] == first.candidate_id
        )
        response = routes.dispatch("GET", preview)
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1], "video/mp4")
        derived = response[2]
        self.assertNotEqual(derived, self._mp4_variant(1))
        self.assertLessEqual(
            len(derived),
            drama_shot_video_web.MAX_WEB_VIDEO_PREVIEW_BYTES,
        )
        drama_shot_video_web._assert_mp4_web_safe(derived)
        self.assertEqual(response[3]["Accept-Ranges"], "bytes")
        self.assertEqual(response[3]["X-Content-Type-Options"], "nosniff")

        response = routes.dispatch("HEAD", preview)
        self.assertEqual(response[0], 200)
        self.assertEqual(response[2], b"")
        self.assertEqual(
            response[3]["Content-Length"],
            str(len(derived)),
        )
        response = routes.dispatch("GET", preview, headers={"range": "bytes=0-15"})
        self.assertEqual(response[0], 206)
        self.assertEqual(response[2], derived[:16])
        self.assertEqual(
            response[3]["Content-Range"],
            f"bytes 0-15/{len(derived)}",
        )
        status, payload = self._decode(
            routes.dispatch("GET", preview, headers={"range": "bytes=999999-"})
        )
        self.assertEqual(status, 416)
        self.assertEqual(payload["error"], "invalid media range")
        head_error = routes.dispatch(
            "HEAD",
            preview,
            headers={"range": "bytes=999999-"},
        )
        self.assertEqual(head_error[0], 416)
        self.assertEqual(head_error[2], b"")
        self.assertEqual(
            head_error[3]["Content-Length"],
            str(len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))),
        )

        artifact = paths.workspace_root("shot-video-web-mp4") / first.artifact.path
        artifact.write_bytes(self._mp4_variant(9))
        status, payload = self._decode(routes.dispatch("GET", preview))
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "shot video candidate is unavailable")

    def test_preview_admission_precedes_manifest_read_and_uses_web_sample_cap(self) -> None:
        _sources, _manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-admission"
        )
        _status, data = self._get("shot-video-web-admission")
        preview = next(
            item["preview_url"]
            for item in data["shots"][0]["candidates"]
            if item["candidate_id"] == first.candidate_id
        )
        admitted = False
        real_read = drama_shot_video_web._read_manifest
        real_identity = drama_shot_video_web._candidate_payload_identity
        test_case = self

        class Admission:
            def acquire(self, *, timeout):
                nonlocal admitted
                test_case.assertEqual(timeout, 1.0)
                admitted = True
                return True

            def release(self):
                nonlocal admitted
                admitted = False

        def guarded_read(*args, **kwargs):
            self.assertTrue(admitted)
            return real_read(*args, **kwargs)

        identity_limits = []

        def bounded_identity(payload, **kwargs):
            if kwargs:
                identity_limits.append(kwargs.get("maximum_video_samples"))
            return real_identity(payload, **kwargs)

        with (
            patch.object(drama_shot_video_web, "_PREVIEW_SEMAPHORE", Admission()),
            patch.object(
                drama_shot_video_web,
                "_read_manifest",
                side_effect=guarded_read,
            ),
            patch.object(
                drama_shot_video_web,
                "_candidate_payload_identity",
                side_effect=bounded_identity,
            ),
            patch.object(
                drama_shot_video_web,
                "inspect_episode_shot_video_candidates",
                side_effect=AssertionError("preview must not inspect unrelated artifacts"),
            ),
        ):
            self.assertEqual(routes.dispatch("GET", preview)[0], 200)
        self.assertIn(
            drama_shot_video_web.MAX_WEB_VIDEO_PREVIEW_SAMPLES,
            identity_limits,
        )

    def test_same_sha_preview_derivation_is_deduplicated(self) -> None:
        artifact_sha256 = "f" * 64
        payload = b"source"
        derived = b"derived"
        started = threading.Event()
        release = threading.Event()

        def derive(_payload):
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return derived

        with drama_shot_video_web._PREVIEW_CACHE_LOCK:
            drama_shot_video_web._PREVIEW_CACHE.clear()
            drama_shot_video_web._PREVIEW_INFLIGHT.clear()
        with (
            patch.object(
                drama_shot_video_web,
                "_derive_safe_mp4_preview",
                side_effect=derive,
            ) as derive_call,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(
                drama_shot_video_web._safe_preview_for_candidate,
                artifact_sha256,
                payload,
            )
            self.assertTrue(started.wait(timeout=2))
            second = pool.submit(
                drama_shot_video_web._safe_preview_for_candidate,
                artifact_sha256,
                payload,
            )
            release.set()
            self.assertEqual(first.result(timeout=2), derived)
            self.assertEqual(second.result(timeout=2), derived)
        derive_call.assert_called_once_with(payload)

    def test_web_oversize_selection_stays_visible_and_can_be_cleared(self) -> None:
        from src import drama_shot_video_candidate_store

        sources = self._seed_video_candidate_sources("shot-video-web-oversize")
        manifest, candidate = self._append_video_candidate(
            "shot-video-web-oversize",
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
            marker=7,
        )
        manifest = self._select_video_candidate(
            "shot-video-web-oversize",
            manifest,
            candidate,
        )
        artifact_suffix = candidate.artifact.path
        real_read = drama_shot_video_candidate_store._read_strict_workspace_bytes

        def reject_artifact_read(root, path, *, maximum):
            if str(path).endswith(artifact_suffix):
                raise AssertionError("Web clear must not read an oversize artifact")
            return real_read(root, path, maximum=maximum)

        with (
            patch.object(
                drama_shot_video_web,
                "MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES",
                1,
            ),
            patch.object(
                drama_shot_video_candidate_store,
                "_read_strict_workspace_bytes",
                side_effect=reject_artifact_read,
            ),
        ):
            status, data = self._get("shot-video-web-oversize")
            self.assertEqual(status, 200)
            self.assertEqual(data["state"], "fresh")
            self.assertTrue(data["mutation_allowed"])
            self.assertEqual(data["coverage"]["status"], "web_unverified")
            self.assertEqual(
                data["coverage"]["web_unverified_shot_ids"],
                [candidate.shot_id],
            )
            shot = data["shots"][0]
            self.assertEqual(shot["coverage_state"], "web_unverified")
            self.assertFalse(shot["candidates"][0]["preview_available"])
            status, cleared = self._post(
                "shot-video-web-oversize",
                {
                    "episode_no": 1,
                    "shot_id": shot["shot_id"],
                    "candidate_id": None,
                    "expected_selection_revision": shot["selection_revision"],
                    "expected_current_selection": shot["selected"],
                    "expected_manifest_fingerprint": manifest.manifest_fingerprint,
                },
            )
        self.assertEqual(status, 200)
        self.assertTrue(cleared["changed"])
        self.assertIsNone(cleared["overview"]["shots"][0]["selected"])

    def test_overview_busy_is_explicit_503(self) -> None:
        self._seed_two_candidates("shot-video-web-overview-busy")
        busy = SimpleNamespace(acquire=lambda **_kwargs: False)
        with patch.object(drama_shot_video_web, "_OVERVIEW_SEMAPHORE", busy):
            status, data = self._get("shot-video-web-overview-busy")
        self.assertEqual(status, 503)
        self.assertEqual(data["error"], "shot video overview is busy; retry shortly")

    def test_mutation_busy_is_explicit_503(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-mutation-busy"
        )
        _status, data = self._get("shot-video-web-mutation-busy")
        shot = data["shots"][0]
        busy = SimpleNamespace(acquire=lambda **_kwargs: False)
        with patch.object(drama_shot_video_web, "_MUTATION_SEMAPHORE", busy):
            status, response = self._post(
                "shot-video-web-mutation-busy",
                {
                    "episode_no": 1,
                    "shot_id": shot["shot_id"],
                    "candidate_id": first.candidate_id,
                    "expected_selection_revision": shot["selection_revision"],
                    "expected_current_selection": shot["selected"],
                    "expected_manifest_fingerprint": manifest.manifest_fingerprint,
                },
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            response["error"],
            "shot video mutation is busy; retry shortly",
        )

    def test_web_identity_rejects_multiple_video_tracks(self) -> None:
        from src import drama_shot_video_candidate_store

        payload = self._mp4_variant(4)
        top = drama_shot_video_candidate_store._mp4_boxes(
            payload,
            0,
            len(payload),
        )
        cursor = 0
        moov = None
        for kind, payload_start, box_end in top:
            if kind == b"moov":
                moov = (cursor, payload_start, box_end)
                break
            cursor = box_end
        self.assertIsNotNone(moov)
        moov_start, moov_payload_start, moov_end = moov
        child_cursor = moov_payload_start
        track = None
        for kind, _payload_start, box_end in (
            drama_shot_video_candidate_store._mp4_boxes(
                payload,
                moov_payload_start,
                moov_end,
            )
        ):
            if kind == b"trak":
                track = payload[child_cursor:box_end]
                break
            child_cursor = box_end
        self.assertIsNotNone(track)
        doubled_payload = payload[moov_payload_start:moov_end] + track
        doubled_moov = (
            (len(doubled_payload) + 8).to_bytes(4, "big")
            + b"moov"
            + doubled_payload
        )
        multiple_tracks = payload[:moov_start] + doubled_moov + payload[moov_end:]
        with self.assertRaises(ValueError):
            drama_shot_video_candidate_store._candidate_payload_identity(
                multiple_tracks,
                maximum_video_samples=(
                    drama_shot_video_web.MAX_WEB_VIDEO_PREVIEW_SAMPLES
                ),
                require_single_video_track=True,
            )

    def test_metadata_bearing_mp4_is_transcoded_to_safe_preview(self) -> None:
        sources = self._seed_video_candidate_sources("shot-video-web-metadata")
        manifest = sources["video_candidate_manifest"]
        shot_id = sources["video_plan"].shot_specs[0].shot_id
        payload = (
            self._mp4_variant(3)
            + (16).to_bytes(4, "big")
            + b"uuid"
            + b"metadata"
        )
        from src import drama_shot_video_candidate_store

        manifest, candidate = (
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                "shot-video-web-metadata",
                shot_id=shot_id,
                mp4_bytes=payload,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        status, data = self._get("shot-video-web-metadata")
        self.assertEqual(status, 200)
        preview = data["shots"][0]["candidates"][0]["preview_url"]
        response = routes.dispatch("GET", preview)
        self.assertEqual(response[0], 200)
        self.assertNotEqual(response[2], payload)
        self.assertNotIn(b"metadata", response[2])
        self.assertNotIn(b"provider_job_secret", response[2])
        drama_shot_video_web._assert_mp4_web_safe(response[2])
        self.assertEqual(
            manifest.shots[0].candidates[0].candidate_id,
            candidate.candidate_id,
        )

    def test_guarded_selection_clear_and_exact_lost_response_replay(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-select"
        )
        _status, data = self._get("shot-video-web-select")
        shot = data["shots"][0]
        payload = {
            "episode_no": 1,
            "shot_id": shot["shot_id"],
            "candidate_id": first.candidate_id,
            "expected_selection_revision": shot["selection_revision"],
            "expected_current_selection": shot["selected"],
            "expected_manifest_fingerprint": manifest.manifest_fingerprint,
        }
        status, selected = self._post("shot-video-web-select", payload)
        self.assertEqual(status, 200)
        self.assertTrue(selected["changed"])
        selected_shot = selected["overview"]["shots"][0]
        self.assertEqual(selected_shot["selected"]["candidate_id"], first.candidate_id)

        status, replay = self._post("shot-video-web-select", payload)
        self.assertEqual(status, 200)
        self.assertFalse(replay["changed"])
        selected_shot = replay["overview"]["shots"][0]
        clear = {
            "episode_no": 1,
            "shot_id": selected_shot["shot_id"],
            "candidate_id": None,
            "expected_selection_revision": selected_shot["selection_revision"],
            "expected_current_selection": selected_shot["selected"],
            "expected_manifest_fingerprint": replay["overview"]["manifest_fingerprint"],
        }
        status, cleared = self._post("shot-video-web-select", clear)
        self.assertEqual(status, 200)
        self.assertTrue(cleared["changed"])
        self.assertIsNone(cleared["overview"]["shots"][0]["selected"])

    def test_placeholder_selection_is_degraded_not_production_ready(self) -> None:
        sources = self._seed_video_candidate_sources("shot-video-web-placeholder")
        manifest = sources["video_candidate_manifest"]
        for index, spec in enumerate(sources["video_plan"].shot_specs):
            manifest, candidate = self._append_video_candidate(
                "shot-video-web-placeholder",
                manifest,
                spec.shot_id,
                marker=index + 10,
                is_placeholder=index == 0,
            )
            manifest = self._select_video_candidate(
                "shot-video-web-placeholder",
                manifest,
                candidate,
            )
        status, data = self._get("shot-video-web-placeholder")
        self.assertEqual(status, 200)
        self.assertEqual(data["coverage"]["status"], "invalid")
        self.assertEqual(data["continuity"]["status"], "degraded_preview")
        self.assertFalse(data["continuity"]["ready_for_compose"])
        self.assertEqual(
            data["continuity"]["degraded_preview_shot_ids"],
            [sources["video_plan"].shot_specs[0].shot_id],
        )

    def test_source_plan_stale_is_playable_but_compare_only(self) -> None:
        sources, manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-source-stale"
        )
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        image_manifest, image_candidate = self._append_candidate(
            "shot-video-web-source-stale",
            sources["candidate_manifest"],
            shot_id,
            rgba=b"\x44\x55\x66\xff",
        )
        image_pool = next(
            item for item in image_manifest.shots if item.shot_id == shot_id
        )
        drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "shot-video-web-source-stale",
            shot_id=shot_id,
            frame="first",
            binding={
                "kind": "direct",
                "candidate_id": image_candidate.candidate_id,
                "candidate_fingerprint": image_candidate.candidate_fingerprint,
            },
            expected_selection_revision=image_pool.selection_revision,
            expected_current_binding=model_to_dict(image_pool.first_binding),
            expected_manifest_fingerprint=image_manifest.manifest_fingerprint,
        )
        drama_shot_video_store.create_episode_shot_video_plan(
            "shot-video-web-source-stale",
            replace_stale=True,
            expected_plan_fingerprint=sources["video_plan"].plan_fingerprint,
        )
        status, data = self._get("shot-video-web-source-stale")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "stale")
        self.assertFalse(data["mutation_allowed"])
        self.assertEqual(data["shots"][0]["candidates"][0]["preview_url"].split("/")[-1][-4:], ".mp4")
        self.assertTrue(
            all(
                not candidate["current"]
                for candidate in data["shots"][0]["candidates"]
            )
        )
        shot = data["shots"][0]
        status, _body = self._post(
            "shot-video-web-source-stale",
            {
                "episode_no": 1,
                "shot_id": shot["shot_id"],
                "candidate_id": first.candidate_id,
                "expected_selection_revision": shot["selection_revision"],
                "expected_current_selection": shot["selected"],
                "expected_manifest_fingerprint": manifest.manifest_fingerprint,
            },
        )
        self.assertEqual(status, 409)

    def test_projection_caps_candidates_and_keeps_selected_visible(self) -> None:
        sources = self._seed_video_candidate_sources("shot-video-web-cap")
        manifest = sources["video_candidate_manifest"]
        shot_id = sources["video_plan"].shot_specs[0].shot_id
        selected = None
        for marker in range(10):
            manifest, candidate = self._append_video_candidate(
                "shot-video-web-cap",
                manifest,
                shot_id,
                marker=marker,
            )
            if marker == 0:
                manifest = self._select_video_candidate(
                    "shot-video-web-cap",
                    manifest,
                    candidate,
                )
                selected = candidate
        status, data = self._get("shot-video-web-cap")
        self.assertEqual(status, 200)
        shot = data["shots"][0]
        self.assertEqual(shot["candidate_count"], 10)
        self.assertEqual(shot["omitted_candidate_count"], 2)
        self.assertEqual(len(shot["candidates"]), 8)
        self.assertIn(
            selected.candidate_id,
            [item["candidate_id"] for item in shot["candidates"]],
        )

    def test_attempt_projection_fingerprint_mismatch_degrades_as_one_snapshot(self) -> None:
        self._seed_two_candidates("shot-video-web-attempt-race")
        actual = drama_shot_video_web.inspect_episode_shot_video_attempts(
            "shot-video-web-attempt-race"
        )
        fake_inspection = SimpleNamespace(
            state="fresh",
            reasons=[],
            ledger_fingerprint="a" * 64,
            not_sent_attempt_ids=[],
            unknown_attempt_ids=[],
            submitted_attempt_ids=[],
            terminal_attempt_ids=[],
        )
        fake_ledger = SimpleNamespace(
            ledger_fingerprint="b" * 64,
            attempts=[],
        )
        self.assertEqual(actual.state, "needs_attempts")
        with (
            patch.object(
                drama_shot_video_web,
                "inspect_episode_shot_video_attempts",
                return_value=fake_inspection,
            ),
            patch.object(
                drama_shot_video_web,
                "load_episode_shot_video_attempts",
                return_value=fake_ledger,
            ),
        ):
            overview = drama_shot_video_web.build_shot_video_web_overview(
                "shot-video-web-attempt-race"
            )
        self.assertEqual(overview.attempts.state, "invalid")
        self.assertIsNone(overview.attempts.ledger_fingerprint)
        self.assertTrue(all(shot.attempt is None for shot in overview.shots))

    def test_attempt_statuses_are_safe_and_bound_to_latest_shot(self) -> None:
        sources, _manifest, _first, _second = self._seed_two_candidates(
            "shot-video-web-attempt-states"
        )
        shot_id = sources["video_plan"].shot_specs[0].shot_id
        cases = {
            "not_sent": "not_sent",
            "submission_unknown": "unknown",
            "submitted": "submitted",
            "provider_failed": "terminal",
            "closed_unknown": "terminal",
            "succeeded": "terminal",
        }
        for index, (status, outcome) in enumerate(cases.items(), start=1):
            attempt_id = f"sva_{index:024x}"
            inspection = SimpleNamespace(
                state=(
                    "reconciliation_required"
                    if status in {"submission_unknown", "submitted"}
                    else "needs_attempts"
                ),
                reasons=[],
                ledger_fingerprint="a" * 64,
                not_sent_attempt_ids=[attempt_id] if status == "not_sent" else [],
                unknown_attempt_ids=(
                    [attempt_id] if status == "submission_unknown" else []
                ),
                submitted_attempt_ids=(
                    [attempt_id] if status == "submitted" else []
                ),
                terminal_attempt_ids=(
                    [attempt_id]
                    if status
                    in {"provider_failed", "closed_unknown", "succeeded"}
                    else []
                ),
            )
            record = SimpleNamespace(
                attempt_id=attempt_id,
                status=status,
                spec=SimpleNamespace(shot_id=shot_id),
            )
            ledger = SimpleNamespace(
                ledger_fingerprint="a" * 64,
                attempts=[record],
            )
            with (
                patch.object(
                    drama_shot_video_web,
                    "inspect_episode_shot_video_attempts",
                    return_value=inspection,
                ),
                patch.object(
                    drama_shot_video_web,
                    "load_episode_shot_video_attempts",
                    return_value=ledger,
                ),
            ):
                overview = drama_shot_video_web.build_shot_video_web_overview(
                    "shot-video-web-attempt-states"
                )
            shot = next(item for item in overview.shots if item.shot_id == shot_id)
            self.assertEqual(shot.attempt.status, status)
            self.assertEqual(shot.attempt.outcome, outcome)
            encoded = json.dumps(model_to_dict(overview))
            self.assertNotIn("provider_task_id", encoded)
            self.assertNotIn("result_token", encoded)
            self.assertNotIn("submission_gate", encoded)

    def test_read_and_selection_routes_never_enter_provider_execution(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-zero-provider"
        )
        from src import drama_shot_video_attempt_store

        with (
            patch.object(
                drama_shot_video_attempt_store,
                "run_shot_video_attempt_with_adapter",
                side_effect=AssertionError("provider execution must stay unreachable"),
            ) as run_attempt,
            patch.object(
                drama_shot_video_attempt_store,
                "resume_shot_video_attempt",
                side_effect=AssertionError("provider resume must stay unreachable"),
            ) as resume_attempt,
        ):
            _status, data = self._get("shot-video-web-zero-provider")
            shot = data["shots"][0]
            preview = next(
                item["preview_url"]
                for item in shot["candidates"]
                if item["candidate_id"] == first.candidate_id
            )
            self.assertEqual(routes.dispatch("HEAD", preview)[0], 200)
            self.assertEqual(
                routes.dispatch("GET", preview, headers={"range": "bytes=0-7"})[0],
                206,
            )
            status, _result = self._post(
                "shot-video-web-zero-provider",
                {
                    "episode_no": 1,
                    "shot_id": shot["shot_id"],
                    "candidate_id": first.candidate_id,
                    "expected_selection_revision": shot["selection_revision"],
                    "expected_current_selection": shot["selected"],
                    "expected_manifest_fingerprint": manifest.manifest_fingerprint,
                },
            )
            self.assertEqual(status, 200)
        run_attempt.assert_not_called()
        resume_attempt.assert_not_called()

    def test_mutation_headers_body_and_identity_fail_closed(self) -> None:
        _sources, _manifest, first, _second = self._seed_two_candidates(
            "shot-video-web-guard"
        )
        _status, data = self._get("shot-video-web-guard")
        shot = data["shots"][0]
        payload = {
            "episode_no": 1,
            "shot_id": shot["shot_id"],
            "candidate_id": first.candidate_id,
            "expected_selection_revision": shot["selection_revision"],
            "expected_current_selection": None,
            "expected_manifest_fingerprint": data["manifest_fingerprint"],
        }
        status, _body = self._post("shot-video-web-guard", payload, headers={})
        self.assertEqual(status, 415)
        status, _body = self._post(
            "shot-video-web-guard",
            payload,
            headers={
                **self._HEADERS,
                "sec-fetch-site": "cross-site",
            },
        )
        self.assertEqual(status, 403)
        response = routes.dispatch(
            "POST",
            "/api/workspace/shot-video-web-guard/drama/shot-videos/select",
            b"{" + b"x" * (32 * 1024) + b"}",
            self._HEADERS,
        )
        self.assertEqual(response[0], 413)
        status, _body = self._post(
            "shot-video-web-guard",
            {**payload, "candidate_id": "svc_" + "0" * 24},
        )
        self.assertEqual(status, 400)

    def test_novel_workspace_is_rejected(self) -> None:
        init_workspace("shot-video-web-novel", type="novel")
        response = routes.dispatch(
            "GET",
            "/api/workspace/shot-video-web-novel/drama/shot-videos?episode_no=1",
        )
        self.assertEqual(response[0], 400)
        response = routes.dispatch(
            "GET",
            "/w/shot-video-web-novel/shot-videos",
        )
        self.assertEqual(response[0], 404)

    def test_mp4_safety_scan_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            drama_shot_video_web._assert_mp4_web_safe(
                (16).to_bytes(4, "big") + b"uuid" + b"metadata"
            )
        secret = b"provider_job_secret"
        with self.assertRaises(ValueError):
            drama_shot_video_web._assert_mp4_web_safe(
                (8 + len(secret)).to_bytes(4, "big") + b"abcd" + secret
            )
