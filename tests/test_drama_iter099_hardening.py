"""Iteration 099: third-pass real short-drama chain hardening regressions."""

from __future__ import annotations

import json
import os
import time
import zlib
from unittest.mock import Mock, patch

from src import ai_draw_client, drama_multimodal_smoke as multi
from src import character_designer, drama_planner, drama_reviewer, hook_designer
from src import drama_smoke, drama_video, drama_video_smoke, preflight, storyboard_builder
from src.utils import read_json, write_json
from src.web import jobs, routes
from src.web.workspace_ctx import use_workspace
from tests._drama_base import DramaTestBase
from tests.test_drama_video import _FakeVideoClient


class Iter099DramaHardeningTests(DramaTestBase):
    def test_real_text_readiness_rejects_bad_routing_before_attempt_offset(self) -> None:
        invalid = {
            "model": "providerless-model",
            "api_key": "",
            "base_url": "not-a-url",
            "context_limit": 1000,
            "max_tokens": 950,
        }
        with patch("src.drama_smoke.get_model_config", return_value=invalid):
            errors = drama_smoke.real_text_readiness_errors()
        self.assertTrue(any("provider_prefix" in error for error in errors))
        self.assertTrue(any("api_key_missing" in error for error in errors))
        self.assertTrue(any("base_url_invalid" in error for error in errors))
        self.assertTrue(any("context_or_max_tokens_invalid" in error for error in errors))

        with patch("src.config.get_model_config", return_value=invalid), patch(
            "src.drama_smoke.get_model_config", return_value=invalid
        ), patch(
            "src.book_runner._llm_log_line_count", side_effect=AssertionError("attempt offset captured")
        ):
            with self.assertRaisesRegex(RuntimeError, "real_text_readiness_failed"):
                jobs._drama_budget_start(
                    "drama-plan",
                    {"confirm_real_text": True, "budget_cny": 1, "timeout_minutes": 1},
                )

    def test_real_text_readiness_rejects_remote_plain_http(self) -> None:
        config = {
            "model": "provider/model", "api_key": "secret",
            "base_url": "http://provider.example/v1",
            "context_limit": 64000, "max_tokens": 2000,
        }
        with patch("src.drama_smoke.get_model_config", return_value=config):
            self.assertTrue(any(
                error.endswith(":base_url_invalid")
                for error in drama_smoke.real_text_readiness_errors()
            ))

    def test_succeeded_text_attempt_does_not_recover_after_input_drift(self) -> None:
        self._make_drama_workspace("attempt-drift", "推理")
        result = {"episode_no": 1, "title": "已付费结果"}
        config = {
            "model": "provider/model-v1", "base_url": "https://provider.example/v1",
            "api_key": "account-a", "context_limit": 64000, "max_tokens": 2000,
        }
        with use_workspace("attempt-drift"), patch("src.config.get_model_config", return_value=config):
            returned, token = jobs._call_drama_text_model("drama-plan", {}, 1, lambda: result)
            jobs._bind_drama_text_artifact(token, returned)
            write_json(multi.episode_paths("attempt-drift").setup_path, returned)
            jobs._mark_drama_text_attempt(token, "succeeded")
            wizard_path = multi.paths.workspace_root("attempt-drift") / "data" / "wizard_input.json"
            wizard = read_json(wizard_path)
            wizard["topic"] = "edited upstream topic"
            write_json(wizard_path, wizard)
            provider = Mock(side_effect=AssertionError("provider called"))
            with self.assertRaisesRegex(ValueError, "provider or input identity changed"):
                jobs._call_drama_text_model("drama-plan", {}, 1, provider)
        provider.assert_not_called()

    def test_multimodal_crash_adopt_rejects_durable_attempt_input_drift(self) -> None:
        self._make_drama_workspace("adopt-drift", "推理")
        result = {"episode_no": 1, "title": "crash-committed"}
        config = {
            "model": "provider/model-v1", "base_url": "https://provider.example/v1",
            "api_key": "account-a", "context_limit": 64000, "max_tokens": 2000,
        }
        with use_workspace("adopt-drift"), patch("src.config.get_model_config", return_value=config):
            returned, token = jobs._call_drama_text_model("drama-plan", {}, 1, lambda: result)
            jobs._bind_drama_text_artifact(token, returned)
            write_json(multi.episode_paths("adopt-drift").setup_path, returned)
            ledger = jobs._load_drama_text_attempts("adopt-drift")
            row = ledger["attempts"]["drama-plan:1"]
            phase = {
                "provider_fingerprints": {"drama-plan": row["provider_fingerprint"]},
                "model_fingerprints": {"drama-plan": multi._model_sha256("provider/model-v1")},
                "completed_steps": [], "artifact_fingerprints": {}, "station_evidence": {},
            }
            wizard_path = multi.paths.workspace_root("adopt-drift") / "data" / "wizard_input.json"
            wizard = read_json(wizard_path)
            wizard["topic"] = "changed-after-crash"
            write_json(wizard_path, wizard)
            with self.assertRaisesRegex(ValueError, "identity changed"):
                multi._adopt_durable_text_station("adopt-drift", phase, "drama-plan")

    def test_setup_identity_blocks_wizard_track_and_duration_drift(self) -> None:
        self._make_drama_workspace("identity-drift", "推理", episode_duration_seconds=60)
        self._write_setup("identity-drift", hook=True)
        wizard_path = multi.paths.workspace_root("identity-drift") / "data" / "wizard_input.json"
        wizard = read_json(wizard_path)
        wizard.update({"track": "霸总", "episode_duration_seconds": 90})
        write_json(wizard_path, wizard)
        with self.assertRaisesRegex(ValueError, "wizard track drifted"):
            storyboard_builder.run("identity-drift", mock=True)

    def test_setup_identity_rejects_wrong_episode_file(self) -> None:
        self._make_drama_workspace("episode-identity", "推理")
        source = self._write_setup("episode-identity", hook=True, episode_no=1)
        wrong_target = multi.episode_paths("episode-identity", episode_no=2).setup_path
        wrong_target.parent.mkdir(parents=True, exist_ok=True)
        wrong_target.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(ValueError, "different episode"):
            storyboard_builder.run("episode-identity", mock=True, episode_no=2)

    def test_prompts_use_canonical_non_sixty_second_duration(self) -> None:
        self._make_drama_workspace("dynamic-duration", "推理", episode_duration_seconds=90)
        planner_prompt = drama_planner.build_system_prompt("dynamic-duration", "drama_planner")
        planner_task = planner_prompt.rsplit("\n# 你的身份", 1)[-1]
        self.assertIn("90 秒内完成", planner_task)
        self.assertNotIn("60 秒内完成", planner_task)
        self._write_setup("dynamic-duration", hook=True)
        board_prompt = storyboard_builder.build_system_prompt("dynamic-duration")
        board_task = board_prompt.rsplit("你是短剧站③分镜导演", 1)[-1]
        self.assertIn("本集 90 秒内", board_task)
        self.assertNotIn("本集 60 秒内", board_task)
        board = storyboard_builder.run("dynamic-duration", mock=True)
        write_json(multi.episode_paths("dynamic-duration").storyboard_path, board)
        character_prompt = character_designer.build_system_prompt("dynamic-duration")
        self.assertIn("单集目标时长：90 秒", character_prompt)
        sheet = character_designer.run("dynamic-duration", mock=True)
        sheet_path = multi.character_paths("dynamic-duration").sheet_path
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(sheet_path, sheet)
        reviewer_prompt = drama_reviewer.build_system_prompt("dynamic-duration")
        self.assertIn("第 1 集是否适合 90 秒", reviewer_prompt)
        episode_two_setup = drama_planner.run("dynamic-duration", episode_no=2)
        hook_prompt = hook_designer.build_system_prompt(
            "dynamic-duration", setup=episode_two_setup, episode_no=2
        )
        self.assertIn("为第 2 集设计", hook_prompt)

    def test_dirty_cost_interval_fails_closed(self) -> None:
        with patch(
            "src.cost_estimator.estimate_cost_since",
            return_value={"cost_cny": 0.0, "dirty_lines": 1},
        ):
            with self.assertRaisesRegex(ValueError, "billing evidence is invalid"):
                jobs._drama_settle_budget(1.0, 0, lambda *_args: None)

    def test_dirty_cost_after_resume_baseline_blocks_next_text_station(self) -> None:
        workspace = "dirty-resume"
        multi.drama_smoke._create_workspace(workspace, "推理")
        state = multi._new_state(workspace)
        state["phases"]["real_text"] = {
            "status": "running", "real": True, "completed_steps": [],
            "spent_cost_cny": 0.0, "cost_baseline_cny": 0.0,
            "dirty_line_baseline": 0, "total_budget_cny": 5.0,
            "deadline_epoch": time.time() + 60, "station_evidence": {},
            "call_baseline": multi._drama_call_counts(workspace),
            "artifact_fingerprints": {},
            "model_fingerprints": multi._text_model_fingerprints(),
            "provider_fingerprints": multi._text_provider_fingerprints(),
        }
        multi._save(state)
        options = {
            "confirm_real_text": True, "text_budget_cny": 5,
            "text_timeout_seconds": 20,
        }
        with patch.object(drama_smoke, "real_text_tasks_ready", return_value=True), patch(
            "src.drama_multimodal_smoke._insight_billing", return_value=(0.0, 1)
        ), patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as provider:
            with self.assertRaisesRegex(ValueError, "became dirty"):
                multi.run(workspace, real_text=True, options=options)
        provider.assert_not_called()

    def test_image_structure_validation_rejects_magic_only_files(self) -> None:
        for payload in (
            b"\x89PNG\r\n\x1a\n",
            b"\xff\xd8\xff\xd9",
            b"RIFF\x04\x00\x00\x00WEBP",
        ):
            with self.subTest(payload=payload[:12]):
                with self.assertRaises(ValueError):
                    ai_draw_client._detect_image_type(payload)
        self.assertEqual(ai_draw_client._detect_image_type(multi._PNG_1X1), ("image/png", ".png"))

    def test_image_structure_rejects_empty_pixel_containers(self) -> None:
        def png_chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                len(payload).to_bytes(4, "big") + kind + payload
                + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
        empty_png = (
            b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", b"") + png_chunk(b"IEND", b"")
        )
        empty_jpeg = (
            b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xff\xd9"
        )
        vp8x = b"VP8X" + (10).to_bytes(4, "little") + b"\x00" * 10
        empty_webp = b"RIFF" + (len(vp8x) + 4).to_bytes(4, "little") + b"WEBP" + vp8x
        for payload in (empty_png, empty_jpeg, empty_webp):
            with self.assertRaises(ValueError):
                ai_draw_client._detect_image_type(payload)

    def test_reference_metadata_drift_invalidates_paid_image_currentness(self) -> None:
        state = multi.run("image-record-drift")
        sheet_path = multi.character_paths("image-record-drift").sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"][0]["reference_images"][0]["generated_by"] = "tampered-provider"
        write_json(sheet_path, sheet)
        self.assertFalse(multi._all_completed_images_are_current("image-record-drift", state))

    def test_legacy_image_state_without_metadata_hash_blocks_before_retry(self) -> None:
        state = multi.run("image-provenance-upgrade")
        state["phases"]["all_character_images"]["status"] = "pending"
        state["status"] = "running"
        state["image_attempts"]["c001"][-1].pop("artifact_record_sha256")
        multi._save(state)
        with patch("src.drama_multimodal_smoke._atomic_write_bytes") as write_image:
            blocked = multi.run("image-provenance-upgrade")
        write_image.assert_not_called()
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(
            blocked["phases"]["all_character_images"]["error_code"],
            "image_provenance_upgrade_required",
        )

    def test_final_attempt_bookkeeping_is_not_counted_as_provider_call(self) -> None:
        self._make_drama_workspace("call-count")
        path = multi.paths.workspace_root("call-count") / "logs" / "llm_calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"task": "drama_plan", "model": "provider/model", "attempt": 1}) + "\n"
            + json.dumps({"task": "drama_plan", "model": "provider/model", "final_of_attempts": 1}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(multi._drama_call_counts("call-count")["drama_plan"]["calls"], 1)

    def test_submitted_video_resume_needs_no_callback_base_or_upload(self) -> None:
        drama_video_smoke._prepare_mock_inputs("resume-no-callback")
        inputs = drama_video.load_video_inputs("resume-no-callback")
        client = _FakeVideoClient()
        drama_video._write_video_submission("resume-no-callback", {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                client, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "submission_count": 1,
            "task_id": "video-task-1",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        client.get_task = Mock(return_value={"task": {
            "id": "video-task-1", "status": "completed",
            "video_url": "https://result.example.test/resume.mp4", "cost_cny": 1.0,
        }})
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.download_video", return_value=(drama_video._MOCK_MP4, "video/mp4")
        ), patch(
            "src.drama_video._probe_mp4", return_value=drama_video.VideoSpec(5.0, 720, 1280)
        ):
            result = drama_video.run_video_job(
                "resume-no-callback",
                {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_args: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["committed"])
        self.assertEqual(client.uploads, 0)
        self.assertEqual(client.submissions, 0)

    def test_video_inputs_reject_reference_symlink(self) -> None:
        drama_video_smoke._prepare_mock_inputs("video-ref-link")
        sheet = read_json(multi.character_paths("video-ref-link").sheet_path)
        rel = sheet["characters"][0]["reference_images"][0]["path"]
        target = multi.paths.workspace_root("video-ref-link") / rel
        real_copy = target.with_name("real-copy.png")
        real_copy.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(real_copy.name)
        with self.assertRaisesRegex(drama_video.DramaVideoInputError, "symbolic links"):
            drama_video.load_video_inputs("video-ref-link")

    def test_web_recent_failure_does_not_override_durable_submitted_state(self) -> None:
        self._make_drama_workspace("web-durable-video")
        recent = {
            "job_id": "job-old", "workspace": "web-durable-video", "step": "drama-video",
            "status": "failed", "current_step": "failed", "params": {},
        }
        with patch("src.drama_video.video_status", return_value={
            "state": "submitted", "resumable_poll": True, "download_ready": False,
        }), patch("src.drama_video.real_video_enabled", return_value=True), patch(
            "src.web.jobs.active_jobs", return_value=[]
        ), patch("src.web.jobs.recent_jobs", return_value=[recent]):
            _status, _ct, body = routes.api_drama_video_status("web-durable-video")
        payload = json.loads(body)
        self.assertEqual(payload["state"], "submitted")
        self.assertEqual(payload["latest_attempt_state"], "failed")
        self.assertIn('state === "submission_unknown" ? \'\'', routes.static.JS_DASHBOARD)
        self.assertIn("继续查询", routes.static.JS_DASHBOARD)

    def test_unreported_video_cost_stays_unknown_in_report(self) -> None:
        state = multi.run("video-cost-unknown")
        state["phases"]["real_video"].update({
            "cost_cny": 0.0, "cost_unreported": True,
        })
        multi._save(state)
        metrics = multi.calibration_report("video-cost-unknown")["stages"]["video"]["metrics"]
        self.assertIsNone(metrics["cost_cny"])
        self.assertEqual(metrics["cost_status"], "unreported")

    def test_multimodal_state_symlink_is_rejected(self) -> None:
        self._make_drama_workspace("state-link")
        path = multi.state_path("state-link")
        path.parent.mkdir(parents=True, exist_ok=True)
        target = path.with_name("real-state.json")
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target.name)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            multi.load_state("state-link")

    def test_preflight_reports_drama_model_hidden_by_global_mock(self) -> None:
        with patch("src.preflight.load_dotenv_if_available"), patch.dict(
            os.environ,
            {"OPENAI_MODEL": "mock", "DRAMA_MODEL": "provider/model"},
            clear=False,
        ):
            report = preflight.run_preflight(multi.paths.workspace_root("preflight-conflict"))
        self.assertTrue(any("global mock guard overrides" in item for item in report["fatal"]))
