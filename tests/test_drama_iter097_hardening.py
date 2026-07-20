from __future__ import annotations

import os
import time
from unittest.mock import Mock, patch

from src import (
    character_designer,
    drama_multimodal_smoke as multi,
    drama_reviewer,
    drama_smoke,
    drama_video,
    preflight,
    storyboard_builder,
)
from src.drama_schemas import (
    CharacterSheet,
    DramaReview,
    DramaStoryboard,
    character_paths,
    episode_paths,
)
from src.llm_client import LLMClient, llm_deadline_scope
from src.utils import read_json, write_json
from src.web import jobs
from tests._drama_base import DramaTestBase


class DramaIter097BoundaryTests(DramaTestBase):
    def test_job_history_never_projects_one_shot_confirmation(self) -> None:
        record = jobs._new_job_record("paid", "drama-plan", {
            "episode_no": 1,
            "confirm_real_text": True,
            "confirm_real_video": True,
            "budget_cny": 5,
            "timeout_minutes": 2,
        })
        for view in (jobs.public_job_summary_view(record), jobs.public_job_detail_view(record)):
            self.assertEqual(view["params"]["budget_cny"], 5)
            self.assertFalse(any(key.startswith("confirm_") for key in view["params"]))

    def test_media_dotenv_load_happens_only_after_strict_authorization(self) -> None:
        opts = {
            "confirm_real_image": True,
            "image_budget_cny": 5,
            "image_estimated_cost_cny": 1,
            "image_timeout_seconds": 120,
        }
        with patch("src.drama_multimodal_smoke.load_dotenv_if_available") as load, \
                patch("src.drama_multimodal_smoke._run_claimed", return_value={"status": "blocked"}):
            multi.run("dotenv-order", real_image=True, options=opts)
        load.assert_called_once_with()

        with patch.dict(os.environ, {
            "AI_DRAW_BASE_URL": "https://example.com/v1",
            "AI_DRAW_API_KEY": "injected-key",
        }, clear=False), patch(
            "src.drama_multimodal_smoke.load_dotenv_if_available"
        ) as load, patch(
            "src.drama_multimodal_smoke._run_claimed", return_value={"status": "blocked"}
        ):
            multi.run("dotenv-mixed-image", real_image=True, options=opts)
        load.assert_called_once_with()

        video_opts = {
            "confirm_real_video": True,
            "video_budget_cny": 5,
            "video_timeout_seconds": 120,
        }
        with patch.dict(os.environ, {"SD_API_KEY": "injected-key"}, clear=False), patch(
            "src.drama_multimodal_smoke.load_dotenv_if_available"
        ) as load, patch(
            "src.drama_multimodal_smoke._run_claimed", return_value={"status": "blocked"}
        ):
            multi.run("dotenv-mixed-video", real_video=True, options=video_opts)
        load.assert_called_once_with()

        with patch("src.drama_multimodal_smoke.load_dotenv_if_available") as load, \
                patch("src.drama_multimodal_smoke._run_claimed") as claimed:
            with self.assertRaises(multi.MultimodalAuthorizationError):
                multi.run("dotenv-denied", real_image=True, options={**opts, "confirm_real_image": 1})
        load.assert_not_called()
        claimed.assert_not_called()

    def test_preflight_task_catalog_includes_all_paid_drama_text_stations(self) -> None:
        self.assertEqual(set(preflight.DRAMA_TEXT_TASKS), {
            "drama_plan", "drama_hooks", "drama_storyboard", "drama_character", "drama_review"
        })
        fatal: list[str] = []
        with patch.dict(os.environ, {}, clear=True), patch(
            "src.preflight.get_model_config",
            return_value={
                "model": "deepseek/deepseek-chat",
                "api_key_env": "DRAMA_TEST_KEY",
                "base_url_env": "DRAMA_TEST_BASE",
            },
        ):
            preflight._check_env(fatal, [], False)
        self.assertTrue(any("drama_plan" in row and "DRAMA_TEST_KEY" in row for row in fatal))
        self.assertTrue(any("drama_review" in row and "DRAMA_TEST_BASE" in row for row in fatal))

    def test_cli_real_text_refuses_mock_task_configuration(self) -> None:
        with patch.object(drama_smoke, "real_text_tasks_ready", return_value=False), patch(
            "sys.argv",
            ["drama_smoke", "--book", "not-real", "--real-text", "--budget-cny", "1"],
        ), patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), patch(
            "src.drama_smoke.run_smoke"
        ) as run:
            self.assertEqual(drama_smoke.main(), 64)
        run.assert_not_called()

    def test_core_real_text_entry_refuses_mock_tasks_before_workspace_creation(self) -> None:
        opts = {"confirm_real_text": True, "text_budget_cny": 1, "text_timeout_seconds": 10}
        with patch.object(drama_smoke, "real_text_tasks_ready", return_value=False), patch(
            "src.drama_multimodal_smoke._run_claimed"
        ) as claimed:
            with self.assertRaisesRegex(RuntimeError, "real_text_tasks_still_mock"):
                multi.run("core-not-real", real_text=True, options=opts)
        claimed.assert_not_called()
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False), patch.object(
            drama_smoke, "real_text_tasks_ready", return_value=False
        ), patch("src.drama_smoke._create_workspace") as create:
            with self.assertRaisesRegex(RuntimeError, "real_text_tasks_still_mock"):
                drama_smoke.run_smoke(
                    "core-smoke-not-real", real_text=True, budget_cny=1, timeout_seconds=10
                )
        create.assert_not_called()

    def test_server_owned_storyboard_and_character_identity_overrides_model(self) -> None:
        self._make_drama_workspace("identity", track="推理", episode_duration_seconds=60)
        self._write_setup("identity")
        baseline_board = storyboard_builder.run("identity", mock=True)
        wrong_board = {**baseline_board, "season_no": 99, "track": "错误赛道", "target_duration_seconds": 120}
        board_client = Mock(is_mock=False)
        board_client.complete_json.return_value = DramaStoryboard(**wrong_board)
        with patch("src.storyboard_builder.LLMClient", return_value=board_client):
            board = storyboard_builder.run("identity", mock=False, season_no=1)
        self.assertEqual((board["season_no"], board["track"], board["target_duration_seconds"]), (1, "推理", 60))
        write_json(episode_paths("identity").storyboard_path, board)

        baseline_chars = character_designer.run("identity", mock=True)
        wrong_chars = {**baseline_chars, "season_no": 77, "track": "错误赛道", "source_storyboard_title": "伪造来源"}
        char_client = Mock(is_mock=False)
        char_client.complete_json.return_value = CharacterSheet(**wrong_chars)
        with patch("src.character_designer.LLMClient", return_value=char_client):
            sheet = character_designer.run("identity", mock=False, season_no=1)
        self.assertEqual(sheet["season_no"], 1)
        self.assertEqual(sheet["track"], "推理")
        self.assertEqual(sheet["source_storyboard_title"], board["title"])

    def test_empty_real_review_is_parse_failed_and_server_owned(self) -> None:
        drama_smoke.run_smoke("review-strict", timeout_seconds=30)
        client = Mock(is_mock=False)
        client.complete_json.return_value = DramaReview(**{"season_no": 99})
        with patch("src.drama_reviewer.LLMClient", return_value=client):
            result = drama_reviewer.run("review-strict", mock=False)
        self.assertTrue(result["parse_failed"])
        self.assertEqual(result["verdict"], "Abstain")
        self.assertEqual(result["season_no"], 1)
        self.assertEqual(result["agent_name"], "drama_reviewer")

        canonical = read_json(episode_paths("review-strict").review_path)
        canonical["agent_name"] = "spoofed-reviewer"
        client.complete_json.return_value = DramaReview(**canonical)
        with patch("src.drama_reviewer.LLMClient", return_value=client):
            result = drama_reviewer.run("review-strict", mock=False)
        self.assertEqual(result["agent_name"], "drama_reviewer")

    def test_llm_attempt_timeout_is_clamped_to_outer_job_deadline(self) -> None:
        client = LLMClient("drama_plan")
        client.model = "provider/model"
        client.config.update({"request_timeout": 400, "retry_attempts": 1})
        response = {"choices": [{"message": {"content": "ok"}}]}
        with patch("litellm.completion", return_value=response) as completion, patch.object(
            client, "_log_call"
        ):
            with llm_deadline_scope(time.monotonic() + 2):
                self.assertEqual(client.complete_text([{"role": "user", "content": "x"}]), "ok")
        timeout = completion.call_args.kwargs["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 2)


class DramaIter097VideoLedgerTests(DramaTestBase):
    def _prepare(self) -> None:
        from src import drama_video_smoke

        drama_video_smoke._prepare_mock_inputs("ledger")

    def _env(self) -> dict[str, str]:
        return {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }

    def test_post_response_loss_persists_unknown_and_blocks_resubmit(self) -> None:
        self._prepare()
        client = Mock(base_url="https://video.example.test", request_timeout_seconds=30)
        client.upload_asset.side_effect = [
            {"asset": {"id": "asset-1"}},
            {"asset": {"id": "asset-2"}},
        ]
        client.get_asset.side_effect = lambda asset_id: {
            "asset": {"id": asset_id, "status": "ready"}
        }
        client.create_video_task.side_effect = TimeoutError("response lost")
        params = {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1}
        with patch.dict(os.environ, self._env(), clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job("ledger", params, lambda *_: None, client=client)
            ledger = drama_video.read_video_submission("ledger")
            self.assertEqual(ledger["status"], "submitting")
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job("ledger", params, lambda *_: None, client=client)
        client.create_video_task.assert_called_once()
