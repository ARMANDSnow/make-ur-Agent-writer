from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

from src import ai_draw_client, drama_multimodal_smoke as multi
from src.drama_schemas import character_paths
from src.utils import read_json
from src.secure_http import BoundedResponse
from src.web import routes
from tests._drama_base import DramaTestBase


class DramaMultimodalSmokeTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        # These orchestration tests intentionally simulate "real mode" with
        # mock providers.  Production core-entry guards are covered separately.
        ready = patch(
            "src.drama_multimodal_smoke.drama_smoke.real_text_tasks_ready",
            return_value=True,
        )
        ready.start()
        self.addCleanup(ready.stop)
        media_env = patch.dict(os.environ, {
            "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
            "AI_DRAW_API_KEY": "iter98-fake-image-key",
            "AI_DRAW_MODEL": "gpt-image-2",
        }, clear=False)
        media_env.start()
        self.addCleanup(media_env.stop)
        image_provider = patch(
            "src.drama_multimodal_smoke._image_provider_fingerprint",
            return_value="f" * 64,
        )
        image_provider.start()
        self.addCleanup(image_provider.stop)

    def _prepare_real_text(self, name: str) -> None:
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了", "DRAMA_MODEL": "mock"}, clear=False):
            state = multi.run(name, real_text=True, options={
                "confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20,
            })
        self.assertEqual(state["status"], "awaiting_image_authorization")

    def test_mock_full_chain_covers_all_characters_and_resume_is_noop(self) -> None:
        state = multi.run("multi")
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(tuple(state["phases"]), multi.PHASES)
        self.assertEqual(state["phases"]["all_character_images"]["character_count"], 2)
        self.assertEqual(state["phases"]["real_video"]["network_requests"], 0)
        self.assertEqual(state["phases"]["real_video"]["automatic_retries"], 0)
        before = multi.state_path("multi").read_bytes()
        with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=AssertionError("reran text")), \
                patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=AssertionError("reran image")), \
                patch("src.drama_multimodal_smoke.run_video_smoke", side_effect=AssertionError("reran video")):
            resumed = multi.run("multi")
        self.assertEqual(resumed["status"], "succeeded")
        self.assertEqual(read_json(multi.state_path("multi"))["image_attempts"], state["image_attempts"])
        self.assertNotEqual(before, b"")

    def test_calibration_report_separates_mock_from_real_evidence(self) -> None:
        multi.run("calibration-mock")
        report = multi.calibration_report("calibration-mock")
        self.assertFalse(report["real_sample_complete"])
        self.assertEqual(report["status"], "real_sample_incomplete")
        self.assertEqual(
            {row["evidence_level"] for row in report["stages"].values()},
            {"engineering_mock_verified"},
        )
        rendered = json.dumps(report, ensure_ascii=False).lower()
        for forbidden in ("prompt_sha256", "artifact_path", "api_key", "signed_url", "authorization"):
            self.assertNotIn(forbidden, rendered)
        image_metrics = report["stages"]["images"]["metrics"]
        self.assertEqual(image_metrics["request_count"], 0)
        self.assertEqual(image_metrics["successful_character_count"], 2)

    def test_report_only_is_zero_paid_provider_and_does_not_create_workspace(self) -> None:
        self.assertFalse(multi.state_path("report-missing").parent.parent.exists())
        with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as text, \
                patch("src.drama_multimodal_smoke.redraw_character_reference") as image, \
                patch("src.drama_multimodal_smoke.run_video_smoke") as video, \
                patch.object(sys, "argv", ["drama_multimodal_smoke", "--book", "report-missing", "--report-only"]):
            self.assertEqual(multi.main(), 0)
        text.assert_not_called()
        image.assert_not_called()
        video.assert_not_called()
        self.assertFalse(multi.state_path("report-missing").parent.parent.exists())

    def test_report_only_rejects_paid_mode_combination_before_network(self) -> None:
        with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network, \
                patch.object(sys, "argv", [
                    "drama_multimodal_smoke", "--book", "conflict", "--report-only",
                    "--real-text", "--confirm-real-text", "--text-budget-cny", "1",
                    "--text-timeout-seconds", "10",
                ]):
            self.assertEqual(multi.main(), 64)
        network.assert_not_called()

    def test_real_mode_with_mock_provider_is_not_real_sample_evidence(self) -> None:
        self._prepare_real_text("cal-real-mock")
        report = multi.calibration_report("cal-real-mock")
        self.assertEqual(
            report["stages"]["text"]["evidence_level"],
            "real_mode_without_provider_evidence",
        )
        self.assertFalse(report["real_sample_complete"])

    def test_calibration_report_keeps_local_real_records_unverified(self) -> None:
        state = multi.run("cal-real-proof")
        real_model_sha = multi._model_sha256("provider/model-v1")
        state["phases"]["real_text"].update({
            "real": True,
            "llm_calls": 5,
            "model_fingerprints": {step: real_model_sha for step in multi.TEXT_STEP_TASKS},
            "station_evidence": {
                step: {
                    "status": "succeeded", "call_count": 1,
                    "non_mock_call_count": 1, "pinned_model_call_count": 1,
                    "model_sha256": real_model_sha,
                }
                for step in multi.TEXT_STEP_TASKS
            },
        })
        state["phases"]["all_character_images"]["real"] = True
        for rows in state["image_attempts"].values():
            rows[-1]["generated_by"] = "image-provider/model-v1"
        state["phases"]["real_video"].update({
            "real": True,
            "submission_consumed": True,
            "attempt": 1,
            "paid_submission_count": 1,
        })
        multi._save(state)
        report = multi.calibration_report("cal-real-proof")
        self.assertTrue(report["real_execution_recorded"])
        self.assertFalse(report["real_sample_complete"])
        self.assertEqual(report["status"], "real_execution_recorded_pending_operator_review")
        self.assertEqual(report["evidence_integrity"], "local_records_unverified")
        self.assertEqual(
            {row["evidence_level"] for row in report["stages"].values()},
            {"real_execution_recorded_unverified"},
        )
        self.assertEqual(report["stages"]["video"]["metrics"]["request_count"], 1)

    def test_calibration_report_downgrades_stale_real_image_evidence(self) -> None:
        state = multi.run("cal-stale-proof")
        state["phases"]["real_text"].update({"real": True, "llm_calls": 5})
        state["phases"]["all_character_images"]["real"] = True
        for rows in state["image_attempts"].values():
            rows[-1]["generated_by"] = "image-provider/model-v1"
        state["phases"]["real_video"].update({
            "real": True, "submission_consumed": True, "attempt": 1,
            "paid_submission_count": 1,
        })
        multi._save(state)
        first = next(iter(state["image_attempts"].values()))[-1]
        (multi.paths.workspace_root("cal-stale-proof") / first["artifact_path"]).write_bytes(b"tampered")
        report = multi.calibration_report("cal-stale-proof")
        self.assertEqual(
            report["stages"]["images"]["evidence_level"],
            "real_mode_without_provider_evidence",
        )
        self.assertFalse(report["real_sample_complete"])

    def test_resume_modes_cannot_upgrade_mock_authorization(self) -> None:
        multi.run("modes")
        with patch("src.drama_multimodal_smoke.redraw_character_reference") as network:
            with self.assertRaisesRegex(ValueError, "cannot upgrade"):
                multi.run("modes", real_image=True, options={
                    "confirm_real_image": True, "image_budget_cny": 10,
                    "image_estimated_cost_cny": 1, "image_timeout_seconds": 120,
                })
        network.assert_not_called()

    def test_each_real_stage_requires_strict_independent_authorization(self) -> None:
        for modes, options in (
            ({"real_text": True}, {"confirm_real_text": 1, "text_budget_cny": 1, "text_timeout_seconds": 5}),
            ({"real_image": True}, {"confirm_real_image": 1, "image_budget_cny": 1, "image_estimated_cost_cny": 1, "image_timeout_seconds": 5}),
        ):
            with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as text, \
                    patch("src.drama_multimodal_smoke.redraw_character_reference") as image:
                with self.assertRaises(multi.MultimodalAuthorizationError):
                    multi.run("strict-" + next(iter(modes)), options=options, **modes)
            if modes.get("real_text"):
                text.assert_not_called()
            image.assert_not_called()

    def test_image_failure_waits_for_new_billing_confirmation_and_uses_simplified_retry(self) -> None:
        self._prepare_real_text("retry")
        options = {
            "confirm_real_image": True, "image_budget_cny": 10,
            "image_estimated_cost_cny": 1, "image_timeout_seconds": 121,
        }
        with patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=ai_draw_client.AIDrawTimeout("slow")) as draw:
            state = multi.run("retry", real_image=True, options=options)
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(state["status"], "awaiting_retry_authorization")
        self.assertEqual(
            multi.calibration_report("retry")["stages"]["images"]["metrics"]["request_count"], 1
        )
        first = state["image_attempts"]["c001"][0]
        self.assertEqual(first["timeout_seconds"], 121)
        self.assertEqual(first["prompt_profile"], "initial_complete_v1")

        with patch("src.drama_multimodal_smoke.redraw_character_reference") as draw:
            state = multi.run("retry", real_image=True, options=options)
        draw.assert_not_called()
        self.assertEqual(state["status"], "awaiting_retry_authorization")

        retry_options = {**options, "confirm_image_retry": True, "confirm_upstream_status_and_billing_checked": True}
        with patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=ai_draw_client.AIDrawNetworkError("offline")):
            state = multi.run("retry", real_image=True, options=retry_options)
        second = state["image_attempts"]["c001"][1]
        self.assertEqual(second["timeout_seconds"], 180)
        self.assertEqual(second["prompt_profile"], "retry_simplified_v1")
        self.assertNotEqual(first["prompt_sha256"], second["prompt_sha256"])

    def test_three_failed_image_submissions_are_the_hard_limit(self) -> None:
        self._prepare_real_text("limit")
        options = {
            "confirm_real_image": True, "confirm_image_retry": True,
            "confirm_upstream_status_and_billing_checked": True,
            "image_budget_cny": 10, "image_estimated_cost_cny": 1,
            "image_timeout_seconds": 120,
        }
        calls = 0
        for _ in range(3):
            with patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=ai_draw_client.AIDrawProviderError("bad")) as draw:
                state = multi.run("limit", real_image=True, options=options)
                calls += draw.call_count
        self.assertEqual(calls, 3)
        self.assertEqual(state["status"], "failed")
        with patch("src.drama_multimodal_smoke.redraw_character_reference") as draw:
            state = multi.run("limit", real_image=True, options=options)
        draw.assert_not_called()
        self.assertEqual(state["status"], "failed")

    def test_original_character_prompt_is_not_mutated_or_logged(self) -> None:
        multi.run("redact")
        sheet = read_json(character_paths("redact").sheet_path)
        original = sheet["characters"][0]["prompt_template_sd"]
        rendered = multi.state_path("redact").read_text(encoding="utf-8")
        self.assertTrue(original)
        self.assertNotIn(original, rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("API_KEY", rendered)
        self.assertIn("prompt_sha256", rendered)

    def test_image_budget_blocks_before_network(self) -> None:
        self._prepare_real_text("budget")
        options = {
            "confirm_real_image": True, "image_budget_cny": 0.5,
            "image_estimated_cost_cny": 1, "image_timeout_seconds": 120,
        }
        with patch("src.drama_multimodal_smoke.redraw_character_reference") as draw:
            state = multi.run("budget", real_image=True, options=options)
        draw.assert_not_called()
        self.assertEqual(state["phases"]["all_character_images"]["error_code"], "image_budget_exhausted")

    def test_ai_client_preserves_timeout_vs_network_vs_provider(self) -> None:
        character = {"id": "c001", "name": "A", "lora_token": "char_a", "visual_signature": "coat", "prompt_template_sd": "long prompt"}
        with patch.dict(os.environ, {"AI_DRAW_BASE_URL": "https://api.example.test", "AI_DRAW_API_KEY": "test-key", "AI_DRAW_MODEL": "image"}, clear=False), \
                patch("src.ai_draw_client._validate_public_endpoint"), \
                patch("src.ai_draw_client.request_bytes", side_effect=socket.timeout()):
            with self.assertRaises(ai_draw_client.AIDrawTimeout):
                ai_draw_client.redraw_character_reference("x", character, mock=False, timeout_seconds=12)

    def test_image_url_download_only_receives_attempt_deadline_remainder(self) -> None:
        character = {"id": "c001", "name": "A", "lora_token": "char_a", "visual_signature": "coat", "prompt_template_sd": "long prompt"}
        response = BoundedResponse(
            200, "application/json", b'{"data":[{"url":"https://result.example.test/x.png"}]}'
        )
        with patch.dict(os.environ, {"AI_DRAW_BASE_URL": "https://api.example.test", "AI_DRAW_API_KEY": "test-key", "AI_DRAW_MODEL": "image"}, clear=False), \
                patch("src.ai_draw_client._validate_public_endpoint"), \
                patch("src.ai_draw_client.request_bytes", return_value=response), \
                patch("src.ai_draw_client.time.monotonic", side_effect=[10.0, 189.0]), \
                patch("src.ai_draw_client._download_generated_image", return_value=(multi._PNG_1X1, "image/png", ".png")) as download:
            ai_draw_client.redraw_character_reference("deadline", character, mock=False, timeout_seconds=180)
        self.assertEqual(download.call_args.kwargs["timeout_seconds"], 1.0)

    def test_video_readiness_requires_same_process_callback_confirmation(self) -> None:
        multi.run("ready-base")
        with patch("src.drama_multimodal_smoke.drama_video.load_video_inputs"), \
                patch("src.drama_multimodal_smoke.drama_video.validate_real_video_gate") as gate:
            with self.assertRaises(multi.MultimodalAuthorizationError):
                multi._video_readiness("ready-base", {
                    "confirm_real_video": True, "video_budget_cny": 10,
                    "video_timeout_seconds": 300,
                }, real_video=True)
        gate.assert_not_called()

    def test_state_public_projection_contains_no_credentials_or_full_prompt(self) -> None:
        state = multi.run("projection")
        rendered = json.dumps(state, ensure_ascii=False).lower()
        for forbidden in ("authorization", "api_key", "signed_url", "upstream_response", "完整角色提示"):
            self.assertNotIn(forbidden, rendered)

    def test_calibration_report_does_not_project_free_form_model_or_provider_labels(self) -> None:
        state = multi.run("report-redact")
        attempt = next(iter(state["image_attempts"].values()))[-1]
        attempt.update({
            "requested_model": "sk-this-must-not-leak",
            "provider_model": "Bearer must-not-leak",
            "provider_size": "secret-size-label",
        })
        state["phases"]["real_video"].update({
            "ratio": "sk-video-secret", "resolution": "Bearer video-secret",
        })
        multi._save(state)
        rendered = json.dumps(multi.calibration_report("report-redact"), ensure_ascii=False)
        for forbidden in ("sk-this-must-not-leak", "Bearer must-not-leak", "secret-size-label", "sk-video-secret", "Bearer video-secret"):
            self.assertNotIn(forbidden, rendered)

    def test_public_projection_filters_free_form_error_and_character_fields(self) -> None:
        state = multi.run("projection-fields")
        state["phases"]["all_character_images"].update({
            "error_code": "Bearer must-not-leak",
            "character_id": "sk-must-not-leak",
        })
        multi._save(state)
        rendered = json.dumps(multi.public_status("projection-fields"), ensure_ascii=False)
        self.assertNotIn("Bearer must-not-leak", rendered)
        self.assertNotIn("sk-must-not-leak", rendered)

    def test_web_projects_safe_read_only_state(self) -> None:
        multi.run("web-multi")
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/web-multi/drama/multimodal-smoke"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload.get("status"), "succeeded")
        rendered = json.dumps(payload).lower()
        self.assertNotIn("prompt", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertEqual(payload["phases"]["real_video"]["automatic_retries"], 0)
        self.assertEqual(payload["calibration"]["status"], "real_sample_incomplete")
        self.assertFalse(payload["calibration"]["real_sample_complete"])

    def test_real_text_uses_one_total_budget_and_deadline_projection(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了", "DRAMA_MODEL": "mock"}, clear=False):
            state = multi.run("text-total", real_text=True, options={
                "confirm_real_text": True, "text_budget_cny": 5,
                "text_timeout_seconds": 20,
            })
        text = state["phases"]["real_text"]
        self.assertEqual(text["actual_cost_cny"], 0.0)
        self.assertEqual(text["remaining_budget_cny"], 5.0)
        self.assertGreater(text["remaining_seconds"], 0)
        self.assertEqual(state["status"], "awaiting_image_authorization")

    def test_text_station_progress_is_durable_and_resume_skips_completed(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}

        def fail_after_one(*_args, **kwargs):
            self._write_setup("text-resume", hook=False)
            kwargs["on_step_complete"]("drama-plan", {"status": "succeeded", "actual_cost_cny": 4.0})
            raise RuntimeError("station two failed")

        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._insight_cost", side_effect=[0.0, 0.0, 4.0, 4.0]), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=fail_after_one):
            with self.assertRaises(RuntimeError):
                multi.run("text-resume", real_text=True, options=opts)
        self.assertEqual(read_json(multi.state_path("text-resume"))["phases"]["real_text"]["completed_steps"], ["drama-plan"])

        seen = {}
        def resume(*_args, **kwargs):
            seen["completed"] = list(kwargs["completed_steps"])
            seen["budget"] = kwargs["budget_cny"]
            return {"cost_cny": 0.5, "remaining_budget_cny": 0.5, "remaining_seconds": 10.0}
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=4.5), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=resume):
            state = multi.run("text-resume", real_text=True, options=opts)
        self.assertEqual(seen["completed"], ["drama-plan"])
        self.assertEqual(seen["budget"], 0.5)
        self.assertEqual(state["phases"]["real_text"]["actual_cost_cny"], 4.5)
        self.assertEqual(state["phases"]["real_text"]["remaining_budget_cny"], 0.5)
        self.assertEqual(state["status"], "awaiting_image_authorization")

    def test_staged_text_then_image_authorization_uses_same_state(self) -> None:
        self._prepare_real_text("staged")
        options = {"confirm_real_image": True, "image_budget_cny": 5, "image_estimated_cost_cny": 1, "image_timeout_seconds": 120}
        with patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=ai_draw_client.AIDrawProviderError("stop")):
            state = multi.run("staged", real_image=True, options=options)
        self.assertEqual(state["phases"]["real_text"]["status"], "succeeded")
        self.assertEqual(state["status"], "awaiting_retry_authorization")

    def test_video_pre_submit_failure_is_not_misreported_and_can_retry(self) -> None:
        state = multi.run("video-once")
        # Convert the mock fixture into the staged pre-video state for a focused
        # one-shot ledger test without any provider/network activity.
        state["phases"]["real_video"] = {"status": "pending"}
        state["phases"]["video_readiness"] = {"status": "awaiting_real_video_authorization"}
        state["status"] = "awaiting_video_authorization"
        multi._save(state)
        opts = {
            "confirm_real_video": True, "confirm_asset_callback_same_process": True,
            "video_budget_cny": 10, "video_timeout_seconds": 300,
        }
        with patch("src.drama_multimodal_smoke._video_readiness", return_value={"reference_count": 2}), \
                patch("src.drama_multimodal_smoke.run_video_smoke", side_effect=TimeoutError("ambiguous")) as submit:
            with self.assertRaises(TimeoutError):
                multi.run("video-once", real_video=True, options=opts)
        self.assertEqual(submit.call_count, 1)
        failed_report = multi.calibration_report("video-once")
        self.assertEqual(failed_report["stages"]["video"]["metrics"]["request_count"], 0)
        self.assertIn("elapsed_seconds", failed_report["stages"]["video"]["metrics"])
        with patch("src.drama_multimodal_smoke._video_readiness", return_value={"reference_count": 2}), \
                patch("src.drama_multimodal_smoke.run_video_smoke", side_effect=TimeoutError("pre-submit again")) as submit:
            with self.assertRaises(TimeoutError):
                multi.run("video-once", real_video=True, options=opts)
        submit.assert_called_once()

    def test_corrupt_paid_state_fails_closed(self) -> None:
        multi.run("corrupt")
        multi.state_path("corrupt").write_text("{bad", encoding="utf-8")
        with patch("src.drama_multimodal_smoke.redraw_character_reference") as network:
            with self.assertRaises(json.JSONDecodeError):
                multi.run("corrupt")
        network.assert_not_called()

    def test_semantically_corrupt_billing_state_fails_closed(self) -> None:
        state = multi.run("corrupt-semantic")
        mutations = (
            lambda row: row.__setitem__("image_estimated_spend_cny", float("nan")),
            lambda row: row["image_attempts"]["c001"][0].__setitem__("attempt", 2),
            lambda row: row["image_attempts"]["c001"][0].__setitem__("artifact_path", "../../outside.png"),
            lambda row: row["image_attempts"]["c001"][0].__setitem__("artifact_sha256", "not-a-sha256"),
            lambda row: row["phases"]["real_video"].update({"submission_consumed": "yes", "attempt": 1}),
            lambda row: row["phases"]["real_text"].update({"status": "Bearer must-not-leak"}),
        )
        for mutate in mutations:
            broken = json.loads(json.dumps(state))
            mutate(broken)
            multi.state_path("corrupt-semantic").write_text(
                json.dumps(broken, allow_nan=True), encoding="utf-8"
            )
            with patch("src.drama_multimodal_smoke.run_video_smoke") as network:
                with self.assertRaises(ValueError):
                    multi.run("corrupt-semantic")
            network.assert_not_called()
        multi._save(state)

    def test_failed_text_cost_exhausts_total_budget_before_resume_network(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        def billed_failure(*_args, **_kwargs):
            _kwargs["on_step_start"]("drama-plan")
            log = multi.paths.workspace_root("text-billed-fail") / "logs" / "llm_calls.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"task": "drama_plan", "model": "deepseek/deepseek-chat"}) + "\n")
            time.sleep(0.01)
            raise RuntimeError("provider failed after billing")
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._insight_cost", side_effect=[0.0, 0.0, 5.0]), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=billed_failure):
            with self.assertRaises(RuntimeError):
                multi.run("text-billed-fail", real_text=True, options=opts)
        self.assertEqual(read_json(multi.state_path("text-billed-fail"))["phases"]["real_text"]["spent_cost_cny"], 5.0)
        report = multi.calibration_report("text-billed-fail")
        self.assertEqual(report["stages"]["text"]["metrics"]["request_count"], 1)
        self.assertGreater(report["stages"]["text"]["metrics"]["elapsed_seconds"], 0)
        failed_station = report["stages"]["text"]["metrics"]["stations"]["drama-plan"]
        self.assertEqual(failed_station["status"], "failed")
        self.assertEqual(failed_station["call_count"], 1)
        self.assertGreater(failed_station["elapsed_seconds"], 0)
        self.assertEqual(failed_station["cumulative_cost_cny"], 5.0)
        with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
            awaiting = multi.run("text-billed-fail", real_text=True, options=opts)
            self.assertEqual(awaiting["status"], "awaiting_text_retry_authorization")
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                multi.run("text-billed-fail", real_text=True, options={
                    **opts,
                    "confirm_text_retry": True,
                    "confirm_upstream_status_and_billing_checked": True,
                })
        network.assert_not_called()

    def test_real_text_resume_rejects_model_identity_drift_before_network(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        model_a = {step: multi._model_sha256("provider/model-a") for step in multi.TEXT_STEP_TASKS}
        model_b = {step: multi._model_sha256("provider/model-b") for step in multi.TEXT_STEP_TASKS}
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._text_model_fingerprints", return_value=model_a), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=0.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=RuntimeError("stop")):
            with self.assertRaises(RuntimeError):
                multi.run("text-model-pin", real_text=True, options=opts)
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._text_model_fingerprints", return_value=model_b), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=0.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
            with self.assertRaisesRegex(ValueError, "model identity"):
                multi.run("text-model-pin", real_text=True, options=opts)
        network.assert_not_called()

    def test_real_text_resume_rejects_provider_account_or_endpoint_drift(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        provider_a = {step: "a" * 64 for step in multi.TEXT_STEP_TASKS}
        provider_b = {step: "b" * 64 for step in multi.TEXT_STEP_TASKS}
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._text_provider_fingerprints", return_value=provider_a), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=0.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=RuntimeError("stop")):
            with self.assertRaises(RuntimeError):
                multi.run("text-provider-pin", real_text=True, options=opts)
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._text_provider_fingerprints", return_value=provider_b), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=0.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
            with self.assertRaisesRegex(ValueError, "provider identity"):
                multi.run("text-provider-pin", real_text=True, options=opts)
        network.assert_not_called()

    def test_calibration_uses_durable_video_ledger_across_state_crash_window(self) -> None:
        state = multi.run("video-ledger-report")
        state["phases"]["real_video"] = {"status": "running", "real": True}
        state["status"] = "running"
        multi._save(state)
        client = Mock(base_url="https://video.example.test", api_key="account-secret")
        multi.drama_video._write_video_submission("video-ledger-report", {
            "status": "submitted",
            "input_fingerprint": multi.drama_video.load_video_inputs("video-ledger-report").fingerprint,
            "provider_fingerprint": multi.drama_video._video_provider_fingerprint(
                client, multi.drama_video.DEFAULT_VIDEO_MODEL
            ),
            "submission_count": 1,
            "task_id": "video-task-1",
            "updated_at": int(time.time()),
        })
        metrics = multi.calibration_report("video-ledger-report")["stages"]["video"]["metrics"]
        self.assertEqual(metrics["request_count"], 1)
        self.assertEqual(metrics["submission_status"], "submitted")

    def test_repeated_text_station_failures_refresh_cumulative_evidence(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 10, "text_timeout_seconds": 20}

        def fail_station(*_args, **kwargs):
            kwargs["on_step_start"]("drama-plan")
            log = multi.paths.workspace_root("text-repeat-fail") / "logs" / "llm_calls.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"task": "drama_plan", "model": "deepseek/deepseek-chat"}) + "\n")
            time.sleep(0.01)
            raise RuntimeError("provider failed")

        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=0.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", side_effect=fail_station):
            with self.assertRaises(RuntimeError):
                multi.run("text-repeat-fail", real_text=True, options=opts)
            first = multi.calibration_report("text-repeat-fail")["stages"]["text"]["metrics"]["stations"]["drama-plan"]
            awaiting = multi.run("text-repeat-fail", real_text=True, options=opts)
            self.assertEqual(awaiting["status"], "awaiting_text_retry_authorization")
            with self.assertRaises(RuntimeError):
                multi.run("text-repeat-fail", real_text=True, options={
                    **opts,
                    "confirm_text_retry": True,
                    "confirm_upstream_status_and_billing_checked": True,
                })
        second = multi.calibration_report("text-repeat-fail")["stages"]["text"]["metrics"]["stations"]["drama-plan"]
        self.assertEqual(first["call_count"], 1)
        self.assertEqual(second["call_count"], 2)
        self.assertGreaterEqual(second["elapsed_seconds"], first["elapsed_seconds"])
        persisted = read_json(multi.state_path("text-repeat-fail"))["phases"]["real_text"]
        self.assertNotIn("active_step", persisted)

    def test_crash_active_text_station_reconciles_before_budget_gate(self) -> None:
        workspace = "text-crash-ledger"
        multi.drama_smoke._create_workspace(workspace, "推理")
        state = multi._new_state(workspace)
        baseline = multi._drama_call_counts(workspace)
        state["phases"]["real_text"] = {
            "status": "running", "real": True, "completed_steps": [],
            "spent_cost_cny": 0.0, "cost_baseline_cny": 0.0,
            "total_budget_cny": 5.0, "deadline_epoch": time.time() + 60,
            "elapsed_seconds": 0.0, "llm_calls": 0,
            "station_evidence": {}, "call_baseline": baseline,
            "model_fingerprints": multi._text_model_fingerprints(),
            "active_step": "drama-plan", "active_step_started_at": time.time() - 0.01,
        }
        multi._save(state)
        log = multi.paths.workspace_root(workspace) / "logs" / "llm_calls.jsonl"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"task": "drama_plan", "model": "deepseek/deepseek-chat"}) + "\n")
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        with patch("src.drama_multimodal_smoke._insight_cost", return_value=5.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
            awaiting = multi.run(workspace, real_text=True, options=opts)
            self.assertEqual(awaiting["status"], "awaiting_text_retry_authorization")
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                multi.run(workspace, real_text=True, options={
                    **opts,
                    "confirm_text_retry": True,
                    "confirm_upstream_status_and_billing_checked": True,
                })
        network.assert_not_called()
        station = multi.calibration_report(workspace)["stages"]["text"]["metrics"]["stations"]["drama-plan"]
        self.assertEqual(station["status"], "failed")
        self.assertEqual(station["call_count"], 1)
        self.assertGreater(station["elapsed_seconds"], 0)

    def test_calibration_report_rejects_tampered_video_bytes_as_real_evidence(self) -> None:
        state = multi.run("cal-video-stale")
        state["phases"]["real_video"].update({
            "real": True, "submission_consumed": True, "attempt": 1,
            "paid_submission_count": 1,
        })
        multi._save(state)
        multi.drama_video.video_paths("cal-video-stale").video_path.write_bytes(b"tampered")
        report = multi.calibration_report("cal-video-stale")
        self.assertEqual(
            report["stages"]["video"]["evidence_level"],
            "real_mode_without_provider_evidence",
        )

    def test_text_spend_never_decreases_when_insight_total_regresses(self) -> None:
        multi.drama_smoke._create_workspace("text-monotonic", "推理")
        state = multi._new_state("text-monotonic")
        state["phases"]["real_text"] = {
            "status": "running", "real": True, "completed_steps": ["drama-plan"],
            "spent_cost_cny": 4.0, "cost_baseline_cny": 0.0,
            "total_budget_cny": 5.0, "deadline_epoch": time.time() + 60,
        }
        multi._save(state)
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), \
                patch("src.drama_multimodal_smoke._insight_cost", return_value=3.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke", return_value={"cost_cny": 0.0, "remaining_seconds": 10.0}):
            resumed = multi.run("text-monotonic", real_text=True, options=opts)
        self.assertEqual(resumed["phases"]["real_text"]["spent_cost_cny"], 4.0)

    def test_crash_cost_is_reconciled_before_resume_network(self) -> None:
        multi.drama_smoke._create_workspace("text-crash-cost", "推理")
        state = multi._new_state("text-crash-cost")
        state["phases"]["real_text"] = {
            "status": "running", "real": True, "completed_steps": [],
            "spent_cost_cny": 0.0, "cost_baseline_cny": 0.0,
            "total_budget_cny": 5.0, "deadline_epoch": time.time() + 60,
        }
        multi._save(state)
        opts = {"confirm_real_text": True, "text_budget_cny": 5, "text_timeout_seconds": 20}
        with patch("src.drama_multimodal_smoke._insight_cost", return_value=5.0), \
                patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                multi.run("text-crash-cost", real_text=True, options=opts)
        network.assert_not_called()
        self.assertEqual(read_json(multi.state_path("text-crash-cost"))["phases"]["real_text"]["spent_cost_cny"], 5.0)

    def test_cross_process_claim_blocks_second_resume_before_network(self) -> None:
        with multi._orchestrator_lock("claimed"):
            with patch("src.drama_multimodal_smoke.drama_smoke.run_smoke") as network:
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    multi.run("claimed")
            network.assert_not_called()


class DramaMultimodalShellTests(DramaTestBase):
    def test_shell_has_three_independent_confirmation_gates(self) -> None:
        source = (Path(__file__).parents[1] / "scripts" / "drama_multimodal_smoke.sh").read_text(encoding="utf-8")
        self.assertIn("real_text_confirmation_required", source)
        self.assertIn("real_image_confirmation_required", source)
        self.assertIn("real_video_confirmation_required", source)
        self.assertNotIn("for attempt", source)
