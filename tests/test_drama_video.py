from __future__ import annotations

import json
import os
import threading
import time
from unittest.mock import Mock, patch

from src import drama_video, drama_video_smoke
from src.drama_schemas import character_paths
from src.utils import read_json, write_json
from src.web import routes
from tests._drama_base import DramaTestBase


class _FakeVideoClient:
    base_url = "https://video.example.test"

    def __init__(self) -> None:
        self.uploads = 0
        self.submissions = 0
        self.polls = 0

    def upload_asset(self, **_kwargs):
        self.uploads += 1
        return {"asset": {"id": f"asset-{self.uploads}"}}

    def get_asset(self, asset_id):
        return {"asset": {"id": asset_id, "status": "ready"}}

    def create_video_task(self, **kwargs):
        self.submissions += 1
        assert kwargs["allow_real_video"] is True
        return {"task": {"id": "video-task-1", "status": "pending"}}

    def get_task(self, _task_id):
        self.polls += 1
        if self.polls == 1:
            return {"task": {"id": "video-task-1", "status": "processing"}}
        return {
            "task": {
                "id": "video-task-1",
                "status": "completed",
                "video_url": "https://result.example.test/signed.mp4?token=redacted-upstream-only",
                "cost_cny": 1.25,
            }
        }


class DramaVideoPipelineTests(DramaTestBase):
    def _prepare(self, name: str = "video") -> None:
        drama_video_smoke._prepare_mock_inputs(name)

    def test_mock_pipeline_is_network_free_and_persists_safe_metadata(self) -> None:
        self._prepare()
        progress = []
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "mock"}, clear=False), \
                patch("src.drama_video.DramaVideoClient", side_effect=AssertionError("network client built")):
            result = drama_video.run_video_job("video", {}, lambda step, frac: progress.append((step, frac)))
        self.assertTrue(result["committed"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(progress[-1], ("succeeded", 1.0))
        _data, meta = drama_video.read_video("video")
        self.assertEqual(meta["provider"], "mock")
        self.assertNotIn("url", json.dumps(meta).lower())
        self.assertNotIn("authorization", json.dumps(meta).lower())

    def test_stale_or_wrong_episode_inputs_fail_closed(self) -> None:
        self._prepare()
        sheet_path = character_paths("video").sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"][0]["name"] = "已改名"
        write_json(sheet_path, sheet)
        with self.assertRaisesRegex(drama_video.DramaVideoInputError, "stale"):
            drama_video.load_video_inputs("video")
        with self.assertRaisesRegex(drama_video.DramaVideoInputError, "episode 1"):
            drama_video.load_video_inputs("video", episode_no=2)

    def test_shared_character_sheet_episode_marker_does_not_break_episode_one_video(self) -> None:
        self._prepare()
        before = drama_video.load_video_inputs("video").fingerprint
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "mock"}, clear=False):
            drama_video.run_video_job("video", {}, lambda *_: None)
        sheet_path = character_paths("video").sheet_path
        sheet = read_json(sheet_path)
        sheet["episode_no"] = 2
        sheet["characters"][0]["appearances"] = [1, 2]
        future = dict(sheet["characters"][0])
        future.update({"id": "c099", "name": "未来角色", "appearances": [2], "reference_images": []})
        sheet["characters"].append(future)
        write_json(sheet_path, sheet)
        after = drama_video.load_video_inputs("video")
        self.assertTrue(after.references)
        self.assertEqual(after.fingerprint, before)
        _video, persisted_meta = drama_video.read_video("video")
        self.assertEqual(persisted_meta["status"], "succeeded")

        self._prepare("video-hash")
        episode_path = drama_video.episode_paths("video-hash").episode_path
        episode = read_json(episode_path)
        episode["title"] = "schema-valid but no longer assembled"
        write_json(episode_path, episode)
        with self.assertRaisesRegex(drama_video.DramaVideoInputError, "content does not match"):
            drama_video.load_video_inputs("video-hash")

    def test_real_gate_rejects_before_client_or_dns(self) -> None:
        for params in (
            {},
            {"confirm_real_video": True, "budget_cny": 1, "timeout_minutes": 1},
            {"confirm_real_video": True, "budget_cny": float("nan"), "timeout_minutes": 1},
        ):
            with patch.dict(os.environ, {"SD_VIDEO_ESTIMATED_COST_CNY": "2"}, clear=False), \
                    patch("src.drama_video.DramaVideoClient", side_effect=AssertionError("network attempted")):
                with self.assertRaises((PermissionError, ValueError)):
                    drama_video.validate_real_video_gate(params)

    def test_real_flow_submits_once_polls_downloads_and_drops_signed_url(self) -> None:
        self._prepare()
        client = _FakeVideoClient()
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2\x00\x00\x00\x08mdat"
        with patch.dict(os.environ, env, clear=False), \
                patch("src.drama_video.download_video", return_value=(mp4, "video/mp4")):
            result = drama_video.run_video_job(
                "video",
                {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertEqual(client.submissions, 1)
        self.assertGreaterEqual(client.uploads, 1)
        self.assertEqual(result["task_id"], "video-task-1")
        self.assertEqual(result["cost_cny"], 1.25)
        persisted = read_json(drama_video.video_paths("video").meta_path)
        rendered = json.dumps(persisted)
        self.assertNotIn("signed.mp4", rendered)
        self.assertNotIn("token", rendered)

    def test_actual_cost_over_budget_is_visible_but_paid_video_is_preserved(self) -> None:
        self._prepare()
        client = _FakeVideoClient()
        client.get_task = Mock(return_value={"task": {
            "id": "video-task-1", "status": "completed",
            "video_url": "https://result.example.test/v.mp4", "cost_cny": 4.0,
        }})
        env = {
            "SD_VIDEO_MODE": "real", "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2\x00\x00\x00\x08mdat"
        with patch.dict(os.environ, env, clear=False), \
                patch("src.drama_video.download_video", return_value=(mp4, "video/mp4")):
            result = drama_video.run_video_job(
                "video", {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_: None, client=client, sleep=lambda _seconds: None,
            )
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertTrue(drama_video.video_status("video")["download_ready"])
        self.assertEqual(drama_video.video_status("video")["state"], "budget_exceeded")

    def test_asset_missing_status_fails_before_paid_submission(self) -> None:
        self._prepare()
        client = _FakeVideoClient()
        client.get_asset = Mock(return_value={"asset": {"id": "asset-1"}})
        env = {
            "SD_VIDEO_MODE": "real", "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "missing status"):
                drama_video.run_video_job(
                    "video", {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                    lambda *_: None, client=client, sleep=lambda _seconds: None,
                )
        self.assertEqual(client.submissions, 0)
        self.assertIsNone(drama_video.read_video_submission("video"))

    def test_submitted_ledger_resumes_polling_without_upload_or_second_post(self) -> None:
        self._prepare()
        fingerprint = drama_video.load_video_inputs("video").fingerprint
        drama_video._write_video_submission("video", {
            "status": "submitted",
            "input_fingerprint": fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                _FakeVideoClient(), drama_video.DEFAULT_VIDEO_MODEL
            ),
            "submission_count": 1,
            "task_id": "video-task-1",
            "updated_at": int(time.time()),
        })
        client = _FakeVideoClient()
        client.get_task = Mock(return_value={"task": {
            "id": "video-task-1",
            "status": "completed",
            "video_url": "https://result.example.test/resumed.mp4",
            "cost_cny": 1.0,
        }})
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.download_video", return_value=(drama_video._MOCK_MP4, "video/mp4")
        ):
            result = drama_video.run_video_job(
                "video",
                {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["committed"])
        self.assertEqual(client.uploads, 0)
        self.assertEqual(client.submissions, 0)
        self.assertEqual(drama_video.read_video_submission("video")["status"], "succeeded")

    def test_corrupt_submission_ledger_fails_closed_without_provider_calls(self) -> None:
        self._prepare()
        drama_video.video_submission_path("video").write_text("{bad", encoding="utf-8")
        client = _FakeVideoClient()
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
                drama_video.run_video_job(
                    "video",
                    {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                    lambda *_: None,
                    client=client,
                )
        self.assertEqual((client.uploads, client.submissions, client.polls), (0, 0, 0))

    def test_resume_rejects_provider_account_change_before_poll(self) -> None:
        self._prepare()
        first = _FakeVideoClient()
        first.api_key = "account-a-secret"
        fingerprint = drama_video.load_video_inputs("video").fingerprint
        drama_video._write_video_submission("video", {
            "status": "submitted",
            "input_fingerprint": fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                first, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "submission_count": 1,
            "task_id": "video-task-1",
            "updated_at": int(time.time()),
        })
        second = _FakeVideoClient()
        second.api_key = "account-b-secret"
        env = {
            "SD_VIDEO_MODE": "real", "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "provider configuration"):
                drama_video.run_video_job(
                    "video",
                    {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                    lambda *_: None,
                    client=second,
                )
        self.assertEqual(second.polls, 0)

    def test_conflicting_provider_task_ids_fail_closed(self) -> None:
        with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "conflicting task ids"):
            drama_video._extract_resource_id(
                {"id": "task-a", "task": {"id": "task-b", "status": "completed"}},
                "task",
            )

    def test_boolean_provider_cost_is_not_accepted_as_currency(self) -> None:
        self.assertIsNone(drama_video._task_cost_cny({"task": {"cost_cny": True}}))

    def test_prompt_newlines_are_normalized_before_upload(self) -> None:
        self._prepare()
        inputs = drama_video.load_video_inputs("video")
        changed = dict(inputs.episode)
        changed["storyboard"] = [{"is_highlight": True, "visual_content": "first\nsecond\rthird"}]
        prompt = drama_video._video_prompt(inputs.__class__(
            inputs.workspace, changed, inputs.meta, inputs.storyboard, inputs.characters,
            inputs.references, inputs.fingerprint,
        ))
        self.assertNotIn("\n", prompt)
        self.assertNotIn("\r", prompt)

    def test_web_video_uses_202_job_status_and_download(self) -> None:
        self._prepare()
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "mock"}, clear=False):
            status, _ct, body = routes.dispatch(
                "POST", "/api/workspace/video/drama/video", b'{"episode_no":1}'
            )
            self.assertEqual(status, 202, body.decode())
            record = self._wait_drama_job(json.loads(body)["job_id"])
            self.assertEqual(record["status"], "succeeded")
            status, _ct, body = routes.dispatch("GET", "/api/workspace/video/drama/video")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["state"], "succeeded")
            response = routes.dispatch("GET", "/api/workspace/video/drama/video/file")
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1], "video/mp4")

    def test_real_web_request_requires_independent_confirmation_before_job(self) -> None:
        self._prepare()
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
        }
        with patch.dict(os.environ, env, clear=False), patch("src.web.jobs.start_job") as start:
            status, _ct, _body = routes.dispatch(
                "POST",
                "/api/workspace/video/drama/video",
                b'{"episode_no":1,"confirm_real_text":true,"budget_cny":3,"timeout_minutes":5}',
            )
        self.assertEqual(status, 400)
        start.assert_not_called()

    def test_episode_two_page_does_not_expose_episode_one_video(self) -> None:
        from src.web.templates import render_workspace_episode_detail

        html = render_workspace_episode_detail("video", ["video"], 2)
        self.assertNotIn('data-tab="video"', html)
        self.assertNotIn('id="tab-video"', html)

    def test_timeout_and_cancel_have_distinct_status_projection(self) -> None:
        from src.web import jobs

        self._prepare()
        for current_step, expected in (("timeout", "timeout"), ("cancelled", "cancelled")):
            jobs.reset_for_tests()
            record = jobs._new_job_record("video", "drama-video", {"episode_no": 1})
            record.update({"status": "aborted", "current_step": current_step, "finished_at": time.time()})
            jobs._JOBS[record["job_id"]] = record
            jobs._persist_job(record)
            status, _ct, body = routes.dispatch("GET", "/api/workspace/video/drama/video")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["state"], expected)

    def test_latest_failed_attempt_is_visible_without_hiding_old_video(self) -> None:
        from src.web import jobs

        self._prepare()
        drama_video.run_video_job("video", {}, lambda *_: None)
        record = jobs._new_job_record("video", "drama-video", {"episode_no": 1})
        record.update({"status": "failed", "current_step": "generating", "finished_at": time.time()})
        jobs._JOBS[record["job_id"]] = record
        jobs._persist_job(record)
        status, _ct, body = routes.dispatch("GET", "/api/workspace/video/drama/video")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["state"], "succeeded")
        self.assertEqual(payload["latest_attempt_state"], "failed")
        self.assertTrue(payload["download_ready"])

    def test_video_job_cooperative_cancel_and_timeout(self) -> None:
        self._prepare()
        entered = threading.Event()

        def long_run(_workspace, _params, progress_cb):
            entered.set()
            while True:
                progress_cb("generating", 0.5)
                time.sleep(0.005)

        with patch("src.drama_video.run_video_job", side_effect=long_run):
            from src.web import jobs

            started = jobs.start_job("video", "drama-video", {"episode_no": 1})
            self.assertTrue(entered.wait(1))
            jobs.request_cancel(started["job_id"])
            record = self._wait_drama_job(started["job_id"])
            self.assertEqual(record["status"], "aborted")
            self.assertEqual(record["current_step"], "cancelled")

        entered.clear()
        with patch("src.drama_video.run_video_job", side_effect=long_run):
            started = jobs.start_job(
                "video", "drama-video", {"episode_no": 1, "timeout_minutes": 0.0001}
            )
            self.assertTrue(entered.wait(1))
            record = self._wait_drama_job(started["job_id"])
            self.assertEqual(record["status"], "aborted")
            self.assertEqual(record["current_step"], "timeout")

    def test_download_requires_allowlist_content_type_and_magic(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            drama_video.download_video(
                "https://other.example.test/v.mp4",
                allowed_hosts={"result.example.test"},
                timeout_seconds=5,
            )
        response = Mock(status=200)
        response.getheader.side_effect = lambda key, default=None: {
            "content-type": "text/html", "content-length": "12",
        }.get(key, default)
        response.read.return_value = b"not-a-video"
        connection = Mock()
        connection.sock.getpeername.return_value = ("93.184.216.34", 443)
        connection.getresponse.return_value = response
        with patch("src.drama_video._validate_public_endpoint"), \
                patch("src.drama_video.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "container"):
                drama_video.download_video(
                    "https://result.example.test/v.mp4",
                    allowed_hosts={"result.example.test"},
                    timeout_seconds=5,
                )
        connection.connect.assert_called_once()
        connection.request.assert_called_once()

    def test_video_pair_write_failure_restores_previous_pair(self) -> None:
        self._prepare()
        inputs = drama_video.load_video_inputs("video")
        drama_video._run_mock_video(inputs, lambda *_: None)
        out = drama_video.video_paths("video")
        before = (out.video_path.read_bytes(), out.meta_path.read_bytes())
        with patch("src.drama_video.write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                drama_video._commit_video_pair(out, b"different bytes", {"status": "succeeded"})
        self.assertEqual((out.video_path.read_bytes(), out.meta_path.read_bytes()), before)

    def test_remaining_timeout_shrinks_to_authorized_deadline(self) -> None:
        self.assertAlmostEqual(drama_video._remaining_timeout(10.0, lambda: 9.75), 0.25)
        with self.assertRaises(drama_video.DramaVideoTimedOut):
            drama_video._remaining_timeout(10.0, lambda: 10.0)

    def test_public_asset_token_is_exact_short_lived_and_revocable(self) -> None:
        self._prepare()
        asset = drama_video.load_video_inputs("video").references[0][2]
        token = drama_video.register_public_asset(asset, expires_at=time.monotonic() + 30)
        response = routes.dispatch("GET", f"/media/drama-assets/{token}")
        self.assertEqual(response[0], 200)
        self.assertTrue(response[1].startswith("image/"))
        drama_video.revoke_public_assets([token])
        response = routes.dispatch("GET", f"/media/drama-assets/{token}")
        self.assertEqual(response[0], 404)
        self.assertNotIn("video", response[2].decode().lower())

    def test_public_asset_capability_freezes_registered_bytes(self) -> None:
        self._prepare()
        asset = drama_video.load_video_inputs("video").references[0][2]
        original = asset.read_bytes()
        token = drama_video.register_public_asset(asset, expires_at=time.monotonic() + 30)
        asset.write_bytes(b"replaced-after-registration")
        data, _content_type = drama_video.read_public_asset(token)
        self.assertEqual(data, original)
        drama_video.revoke_public_assets([token])

    def test_default_smoke_reports_zero_network_and_no_retries(self) -> None:
        result = drama_video_smoke.run_smoke("smoke-video", timeout_seconds=30)
        self.assertTrue(result["ok"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(result["duration_seconds"], 5)
        self.assertEqual(result["resolution"], "720p")
        self.assertGreater(result["file_size_bytes"], 100)

    def test_smoke_reports_paid_video_when_provider_cost_exceeds_budget(self) -> None:
        terminal = {"status": "budget_exceeded", "result_summary": {}}
        meta = {
            "task_id": "paid-task", "status": "budget_exceeded", "cost_cny": 4.0,
            "budget_cny": 3.0, "duration_seconds": 5, "ratio": "9:16", "resolution": "720p",
        }
        with patch.dict(os.environ, {"CONFIRM_REAL_VIDEO_SMOKE": "可以跑真实视频 smoke"}, clear=False), \
                patch("src.drama_video.load_video_inputs"), \
                patch("src.drama_video_smoke.jobs.start_job", return_value={"job_id": "job-1"}), \
                patch("src.drama_video_smoke._wait", return_value=terminal), \
                patch("src.drama_video.read_video", return_value=(b"paid-video", meta)), \
                patch("src.drama_video_smoke.write_json"):
            result = drama_video_smoke.run_smoke(
                "video", real_video=True, confirm_real_video=True, budget_cny=3, timeout_seconds=300,
            )
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["cost_cny"], 4.0)
        self.assertEqual(result["file_size_bytes"], len(b"paid-video"))
        self.assertEqual(result["automatic_retries"], 0)

    def test_real_smoke_needs_shell_and_cli_confirmation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                drama_video_smoke.run_smoke(
                    "existing", real_video=True, confirm_real_video=True, budget_cny=3
                )
