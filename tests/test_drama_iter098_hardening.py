"""Iteration 098: second-pass real drama chain hardening regressions."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import Mock, patch

from pydantic import ValidationError

from src import drama_multimodal_smoke as multi
from src import drama_video, hook_designer
from src.drama_schemas import DramaHookCandidates, character_paths, episode_paths
from src.secure_http import RequestNotSentError, request_bytes
from src.utils import read_json, write_json
from src.web import jobs
from src.web.workspace_ctx import use_workspace
from tests._drama_base import DramaTestBase


class Iter098DramaHardeningTests(DramaTestBase):
    def _prepare_text_only(self, name: str) -> None:
        with patch("src.drama_multimodal_smoke.drama_smoke.real_text_tasks_ready", return_value=True), \
                patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了", "DRAMA_MODEL": "mock"}, clear=False):
            state = multi.run(name, real_text=True, options={
                "confirm_real_text": True,
                "text_budget_cny": 5,
                "text_timeout_seconds": 20,
            })
        self.assertEqual(state["status"], "awaiting_image_authorization")

    def test_hook_prompt_contains_station_one_setup_and_schema_rejects_wrong_order(self) -> None:
        self._make_drama_workspace("hook-context", "推理")
        setup = {
            "episode_no": 1, "season_no": 1, "title": "唯一标题标记",
            "logline": "唯一梗概标记", "track": "推理", "target_duration_seconds": 60,
            "core_setup": {
                "protagonist": "唯一主角标记", "antagonist": "唯一反派标记",
                "emotional_hook": "唯一情绪标记",
            },
        }
        path = episode_paths("hook-context").setup_path
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, setup)
        prompt = hook_designer.build_system_prompt("hook-context", setup=setup)
        for marker in ("唯一标题标记", "唯一主角标记", "唯一反派标记", "唯一情绪标记"):
            self.assertIn(marker, prompt)
        with self.assertRaises(ValidationError):
            DramaHookCandidates(hooks=[
                {"type": "悬念钩", "content": "a"},
                {"type": "情绪钩", "content": "b"},
                {"type": "反差钩", "content": "c"},
            ])
        with self.assertRaises(ValidationError):
            DramaHookCandidates(hooks=[
                {"type": "任意钩", "content": "a"},
                {"type": "悬念钩", "content": "b"},
                {"type": "反差钩", "content": "c"},
            ])

    def test_text_artifact_drift_blocks_cross_stage_resume_before_provider(self) -> None:
        multi.run("text-drift")
        board_path = episode_paths("text-drift").storyboard_path
        board = read_json(board_path)
        board["title"] = "合法但已人工改动"
        write_json(board_path, board)
        with patch("src.drama_multimodal_smoke.redraw_character_reference") as provider:
            state = multi.run("text-drift")
        provider.assert_not_called()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["phases"]["real_text"]["error_code"], "text_artifact_drift")
        self.assertNotEqual(
            multi.calibration_report("text-drift")["stages"]["text"]["evidence_level"],
            "real_execution_recorded_unverified",
        )

    def test_secure_transport_rejects_private_actual_peer_before_sensitive_request(self) -> None:
        connection = Mock()
        connection.sock.getpeername.return_value = ("127.0.0.1", 443)
        with patch("src.secure_http.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(RequestNotSentError) as caught:
                request_bytes(
                    "https://93.184.216.34/v1/images/generations",
                    method="POST", body=b'{"prompt":"secret"}',
                    headers={"Authorization": "Bearer secret"}, timeout_seconds=5,
                    max_response_bytes=100,
                    peer_validator=multi._validate_public_endpoint,
                )
        self.assertIn("public address", str(caught.exception.__cause__))
        connection.connect.assert_called_once()
        connection.request.assert_not_called()

    def test_image_provider_identity_drift_blocks_before_retry_network(self) -> None:
        self._prepare_text_only("image-provider-drift")
        options = {
            "confirm_real_image": True, "image_budget_cny": 10,
            "image_estimated_cost_cny": 1, "image_timeout_seconds": 120,
        }

        def fake_draw(workspace, character, **_kwargs):
            if character["id"] == "c002":
                raise multi.AIDrawTimeout("slow")
            rel = f"data/character_refs/{character['id']}/portrait_neutral.png"
            target = multi.paths.workspace_root(workspace) / rel
            multi._atomic_write_bytes(target, multi._PNG_1X1)
            return {"path": rel, "generated_by": "provider-a", "prompt": "x"}

        with patch("src.drama_multimodal_smoke._image_provider_fingerprint", return_value="a" * 64), \
                patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=fake_draw):
            state = multi.run("image-provider-drift", real_image=True, options=options)
        self.assertEqual(state["status"], "awaiting_retry_authorization")
        retry = {**options, "confirm_image_retry": True,
                 "confirm_upstream_status_and_billing_checked": True}
        with patch("src.drama_multimodal_smoke._image_provider_fingerprint", return_value="b" * 64), \
                patch("src.drama_multimodal_smoke.redraw_character_reference") as provider:
            with self.assertRaisesRegex(ValueError, "provider identity"):
                multi.run("image-provider-drift", real_image=True, options=retry)
        provider.assert_not_called()

    def test_image_request_rejected_before_send_does_not_consume_attempt_or_budget(self) -> None:
        self._prepare_text_only("image-not-sent")
        options = {
            "confirm_real_image": True, "image_budget_cny": 10,
            "image_estimated_cost_cny": 1, "image_timeout_seconds": 120,
        }
        with patch("src.drama_multimodal_smoke._image_provider_fingerprint", return_value="a" * 64), \
                patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=RequestNotSentError("no send")):
            state = multi.run("image-not-sent", real_image=True, options=options)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["image_attempts"]["c001"], [])
        self.assertEqual(state["image_estimated_spend_cny"], 0.0)
        report = multi.calibration_report("image-not-sent")
        self.assertEqual(report["stages"]["images"]["metrics"]["request_count"], 0)

    def test_received_image_crash_resumes_commit_without_second_provider_call(self) -> None:
        self._prepare_text_only("image-crash")
        options = {
            "confirm_real_image": True, "image_budget_cny": 10,
            "image_estimated_cost_cny": 1, "image_timeout_seconds": 120,
        }

        def fake_draw(workspace, character, **kwargs):
            target = kwargs["output_path"]
            multi._atomic_write_bytes(target, multi._PNG_1X1)
            rel = str(target.relative_to(multi.paths.workspace_root(workspace)))
            return {"path": rel, "generated_by": "provider-a", "prompt": "x"}

        original_replace = multi._replace_character_reference
        with patch("src.drama_multimodal_smoke._image_provider_fingerprint", return_value="a" * 64), \
                patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=fake_draw), \
                patch("src.drama_multimodal_smoke._replace_character_reference", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                multi.run("image-crash", real_image=True, options=options)
        state = read_json(multi.state_path("image-crash"))
        self.assertEqual(state["image_attempts"]["c001"][-1]["status"], "artifact_received")
        with patch("src.drama_multimodal_smoke._image_provider_fingerprint", return_value="a" * 64), \
                patch("src.drama_multimodal_smoke.redraw_character_reference", side_effect=fake_draw) as provider, \
                patch("src.drama_multimodal_smoke._replace_character_reference", side_effect=original_replace):
            state = multi.run("image-crash", real_image=True, options=options)
        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[1]["id"], "c002")
        self.assertEqual(state["image_attempts"]["c001"][-1]["status"], "succeeded")

    def test_video_authorization_drift_and_ledger_status_are_fail_closed(self) -> None:
        from src import drama_video_smoke

        drama_video_smoke._prepare_mock_inputs("video-auth")
        inputs = drama_video.load_video_inputs("video-auth")
        client = Mock(base_url="https://video.example.test")
        provider = drama_video._video_provider_fingerprint(client, drama_video.DEFAULT_VIDEO_MODEL)
        drama_video._write_video_submission("video-auth", {
            "status": "submitted", "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": provider, "submission_count": 1,
            "result_hosts_fingerprint": drama_video.sha256_data(["result.example.test"]),
            "task_id": "task-one", **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        status = drama_video.video_status("video-auth")
        self.assertEqual(status["state"], "submitted")
        self.assertTrue(status["resumable_poll"])
        env = {
            "SD_VIDEO_MODE": "real", "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "different authorization"):
                drama_video.run_video_job(
                    "video-auth",
                    {"confirm_real_video": True, "budget_cny": 4, "timeout_minutes": 1},
                    lambda *_: None, client=client,
                )
        client.get_task.assert_not_called()

    def test_image_report_uses_frozen_cast_and_latest_success_per_character(self) -> None:
        provider_fingerprint = multi._model_sha256("provider/image-v1")
        state = multi.run("image-report")
        state["phases"]["all_character_images"]["real"] = True
        state["phases"]["all_character_images"]["provider_fingerprint"] = provider_fingerprint
        for rows in state["image_attempts"].values():
            rows[-1]["generated_by"] = "provider-image-v1"
            rows[-1]["provider_fingerprint"] = provider_fingerprint
        multi._save(state)
        sheet_path = character_paths("image-report").sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"][1]["appearances"] = [2]
        write_json(sheet_path, sheet)
        self.assertNotEqual(
            multi.calibration_report("image-report")["stages"]["images"]["evidence_level"],
            "real_execution_recorded_unverified",
        )

        state = multi.run("image-report-latest")
        state["phases"]["all_character_images"]["real"] = True
        state["phases"]["all_character_images"]["provider_fingerprint"] = provider_fingerprint
        for rows in state["image_attempts"].values():
            rows[-1]["generated_by"] = "provider-image-v1"
            rows[-1]["provider_fingerprint"] = provider_fingerprint
        repeated = dict(state["image_attempts"]["c001"][-1])
        repeated["attempt"] = 2
        repeated["generated_by"] = "provider-image-v2"
        repeated["prompt_profile"] = "retry_simplified_v1"
        current_sheet = read_json(character_paths("image-report-latest").sheet_path)
        repeated["prompt_sha256"] = multi._profile_prompt(
            current_sheet["characters"][0], simplified=True
        )[2]
        state["image_attempts"]["c001"].append(repeated)
        multi._save(state)
        report = multi.calibration_report("image-report-latest")
        self.assertEqual(
            report["stages"]["images"]["evidence_level"],
            "real_execution_recorded_unverified",
        )
        self.assertEqual(report["stages"]["images"]["metrics"]["request_count"], 3)
        self.assertEqual(report["stages"]["images"]["metrics"]["successful_character_count"], 2)

    def test_truncated_mp4_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ftyp, moov, and mdat"):
            drama_video._probe_mp4(b"\x00\x00\x00\x0cftypisom")

    def test_web_text_unknown_attempt_requires_reconciliation_and_binds_provider(self) -> None:
        self._make_drama_workspace("text-attempt", "推理")
        params = {"confirm_real_text": True, "budget_cny": 5, "timeout_minutes": 1}
        config = {"model": "provider/model", "base_url": "https://provider.example", "api_key": "key-a"}
        with use_workspace("text-attempt"), patch("src.config.get_model_config", return_value=config):
            jobs._begin_drama_text_attempt("drama-plan", params, 1)
            with self.assertRaisesRegex(ValueError, "reconciliation"):
                jobs._begin_drama_text_attempt("drama-plan", params, 1)
            retry = {**params, "confirm_text_retry": True,
                     "confirm_upstream_status_and_billing_checked": True}
            with patch("src.config.get_model_config", return_value={**config, "api_key": "key-b"}):
                with self.assertRaisesRegex(ValueError, "provider or input identity"):
                    jobs._begin_drama_text_attempt("drama-plan", retry, 1)

    def test_persisted_job_drops_one_shot_confirmations(self) -> None:
        self._make_drama_workspace("job-consent", "推理")
        job = jobs._new_job_record("job-consent", "drama-plan", {
            "episode_no": 1, "confirm_real_text": True,
            "confirm_text_retry": True, "budget_cny": 5,
        })
        jobs._persist_job(job)
        row = json.loads(jobs._job_log_path("job-consent").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(row["params"], {})
        self.assertFalse(row["retryable"])

    def test_corrupt_web_text_attempt_ledger_fails_closed(self) -> None:
        self._make_drama_workspace("text-ledger-corrupt", "推理")
        path = jobs._drama_text_attempt_path("text-ledger-corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{bad", encoding="utf-8")
        config = {"model": "provider/model", "base_url": "https://provider.example", "api_key": "key-a"}
        with use_workspace("text-ledger-corrupt"), patch("src.config.get_model_config", return_value=config):
            with self.assertRaisesRegex(ValueError, "unreadable"):
                jobs._begin_drama_text_attempt(
                    "drama-plan",
                    {"confirm_real_text": True, "budget_cny": 5, "timeout_minutes": 1},
                    1,
                )

    def test_committed_text_artifact_is_recovered_without_second_provider_call(self) -> None:
        self._make_drama_workspace("text-commit-recover", "推理")
        config = {"model": "provider/model", "base_url": "https://provider.example", "api_key": "key-a"}
        result = {"episode_no": 1, "title": "已提交"}
        with use_workspace("text-commit-recover"), patch("src.config.get_model_config", return_value=config):
            first, token = jobs._call_drama_text_model("drama-plan", {}, 1, lambda: result)
            jobs._bind_drama_text_artifact(token, first)
            write_json(multi.episode_paths("text-commit-recover").setup_path, first)
            operation = Mock(side_effect=AssertionError("provider called twice"))
            recovered, recovered_token = jobs._call_drama_text_model("drama-plan", {}, 1, operation)
            jobs._mark_drama_text_attempt(recovered_token, "succeeded")
        operation.assert_not_called()
        self.assertEqual(recovered, result)

    def test_text_attempt_symlink_fails_closed(self) -> None:
        self._make_drama_workspace("text-ledger-link", "推理")
        path = jobs._drama_text_attempt_path("text-ledger-link")
        path.parent.mkdir(parents=True, exist_ok=True)
        target = path.parent / "other.json"
        target.write_text('{"schema_version":1,"attempts":{}}', encoding="utf-8")
        path.symlink_to(target.name)
        with self.assertRaisesRegex(ValueError, "regular file"):
            jobs._load_drama_text_attempts("text-ledger-link")

    def test_text_report_includes_unknown_durable_submission(self) -> None:
        self._make_drama_workspace("text-report-unknown", "推理")
        state = multi._new_state("text-report-unknown")
        state["phases"]["real_text"].update({"status": "failed", "real": True, "llm_calls": 0})
        multi._save(state)
        config = {"model": "provider/model", "base_url": "https://provider.example", "api_key": "key-a"}
        with use_workspace("text-report-unknown"), patch("src.config.get_model_config", return_value=config):
            jobs._begin_drama_text_attempt("drama-plan", {}, 1)
        metrics = multi.calibration_report("text-report-unknown")["stages"]["text"]["metrics"]
        self.assertEqual(metrics["request_count"], 1)
        self.assertEqual(metrics["submission_unknown_count"], 1)

    def test_review_station_fingerprint_includes_assembled_episode(self) -> None:
        multi.run("review-artifact-drift")
        path = multi.episode_paths("review-artifact-drift").episode_path
        episode = read_json(path)
        episode["title"] = "tampered"
        write_json(path, episode)
        resumed = multi.run("review-artifact-drift")
        self.assertEqual(resumed["phases"]["real_text"]["error_code"], "text_artifact_drift")

    def test_video_request_not_sent_does_not_consume_single_submission(self) -> None:
        from src import drama_video_smoke

        drama_video_smoke._prepare_mock_inputs("video-not-sent")
        env = {
            "SD_VIDEO_MODE": "real", "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        options = {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1}
        first = Mock(base_url="https://video.example.test")
        first.api_key = "stable-test-account"
        first.upload_asset.side_effect = [
            {"asset": {"id": "asset-1"}}, {"asset": {"id": "asset-2"}},
        ]
        first.get_asset.side_effect = lambda asset_id: {"asset": {"id": asset_id, "status": "ready"}}
        first.create_video_task.side_effect = RequestNotSentError("peer rejected")
        with patch.dict(os.environ, env, clear=False), self.assertRaises(RequestNotSentError):
            drama_video.run_video_job("video-not-sent", options, lambda *_: None, client=first, sleep=lambda _: None)
        marker = drama_video.read_video_submission("video-not-sent")
        self.assertEqual(marker["status"], "request_not_sent")
        self.assertEqual(marker["submission_count"], 0)

        second = Mock(base_url="https://video.example.test")
        second.api_key = "stable-test-account"
        second.upload_asset.side_effect = [
            {"asset": {"id": "asset-1"}}, {"asset": {"id": "asset-2"}},
        ]
        second.get_asset.side_effect = lambda asset_id: {"asset": {"id": asset_id, "status": "ready"}}
        second.create_video_task.return_value = {"task": {"id": "task-1"}}
        second.get_task.return_value = {"task": {
            "id": "task-1", "status": "completed",
            "video_url": "https://result.example.test/video.mp4", "cost_cny": 1.0,
        }}
        with patch.dict(os.environ, env, clear=False), \
                patch("src.drama_video.download_video", return_value=(drama_video._MOCK_MP4, "video/mp4")), \
                patch("src.drama_video._probe_mp4", return_value=drama_video.VideoSpec(5.0, 720, 1280)):
            result = drama_video.run_video_job(
                "video-not-sent", options, lambda *_: None, client=second, sleep=lambda _: None,
            )
        self.assertTrue(result["committed"])
        second.create_video_task.assert_called_once()


if __name__ == "__main__":
    import unittest
    unittest.main()
