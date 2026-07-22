from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from src import drama_video, drama_video_smoke, paths
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
        self.last_create_kwargs = None

    def upload_asset(self, **_kwargs):
        self.uploads += 1
        return {
            "success": True,
            "data": {
                "Id": f"asset-{self.uploads}",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        }

    def get_asset(self, asset_id):
        return {
            "success": True,
            "data": {
                "Id": asset_id,
                "Status": "Active",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        }

    def create_video_task(self, **kwargs):
        self.submissions += 1
        self.last_create_kwargs = dict(kwargs)
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

    def test_incomplete_submission_blocks_download_of_old_valid_video(self) -> None:
        self._prepare()
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "mock"}, clear=False):
            drama_video.run_video_job("video", {}, lambda *_: None)
        with patch(
            "src.drama_video.read_video_submission",
            return_value={"status": "submitted"},
        ):
            with self.assertRaisesRegex(ValueError, "not downloadable"):
                drama_video.read_video("video")
            status, _content_type, body = routes.api_drama_video_file("video")
        self.assertEqual(status, 409)
        self.assertNotIn(b"ftyp", body)

    def test_provider_outputs_list_has_one_bounded_unambiguous_result_url(self) -> None:
        url = "https://result.example.test/signed.mp4?token=upstream-only"
        self.assertEqual(
            drama_video._task_result_url(
                {"task": {"status": "completed", "outputs": [url]}}
            ),
            url,
        )
        self.assertEqual(
            drama_video._task_result_url(
                {
                    "task": {
                        "status": "completed",
                        "video_url": None,
                        "result_url": url,
                        "result": None,
                        "outputs": [url],
                        "output": None,
                    }
                }
            ),
            url,
        )
        for outputs in (None, [], [url, url], [123], ["x" * 4097]):
            with self.subTest(outputs=outputs):
                with self.assertRaises(drama_video.DramaVideoProviderError):
                    drama_video._task_result_url(
                        {"task": {"status": "completed", "outputs": outputs}}
                    )
        with self.assertRaisesRegex(
            drama_video.DramaVideoProviderError,
            "conflicting result URLs",
        ):
            drama_video._task_result_url(
                {
                    "task": {
                        "status": "completed",
                        "video_url": "https://one.example.test/video.mp4",
                        "outputs": ["https://two.example.test/video.mp4"],
                    }
                }
            )
        for bad_url in (
            "https://result.example.test/video.mp4?token=secret value",
            "https://result.example.test/video.mp4?token=secret\rvalue",
            "https://result.example.test:bad/video.mp4",
            "not-a-url",
        ):
            with self.subTest(bad_url=bad_url):
                with self.assertRaisesRegex(
                    drama_video.DramaVideoProviderError,
                    "invalid result URL",
                ) as caught:
                    drama_video._task_result_url(
                        {"task": {"status": "completed", "outputs": [bad_url]}}
                    )
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("bad", str(caught.exception))
        with self.assertRaisesRegex(
            drama_video.DramaVideoProviderError,
            "conflicting result URLs",
        ):
            drama_video._task_result_url(
                {
                    "task": {
                        "status": "completed",
                        "video_url": "https://one.example.test/video.mp4",
                        "result_url": "https://two.example.test/video.mp4",
                    }
                }
            )
        with self.assertRaisesRegex(
            drama_video.DramaVideoProviderError,
            "invalid result URL",
        ):
            drama_video._task_result_url(
                {
                    "task": {
                        "status": "completed",
                        "video_url": 123,
                        "outputs": [url],
                    }
                }
            )

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
                patch("src.drama_video.download_video", return_value=(mp4, "video/mp4")), \
                patch("src.drama_video._probe_mp4", return_value=drama_video.VideoSpec(5.0, 720, 1280)):
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
                patch("src.drama_video.download_video", return_value=(mp4, "video/mp4")), \
                patch("src.drama_video._probe_mp4", return_value=drama_video.VideoSpec(5.0, 720, 1280)):
            result = drama_video.run_video_job(
                "video", {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_: None, client=client, sleep=lambda _seconds: None,
            )
        self.assertEqual(result["status"], "budget_exceeded")
        with patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(5.0, 720, 1280),
        ):
            status = drama_video.video_status("video")
            self.assertTrue(status["download_ready"])
            self.assertEqual(status["state"], "budget_exceeded")

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

    def test_documented_asset_envelope_and_capitalized_id_are_supported(self) -> None:
        response = {
            "success": True,
            "data": {
                "Id": "asset-20260705003737-njxmg",
                "Status": "Active",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        }
        drama_video._validate_provider_envelope(response, "asset upload")
        self.assertEqual(
            drama_video._extract_resource_id(response, "asset"),
            "asset-20260705003737-njxmg",
        )

    def test_asset_envelope_errors_are_bounded_and_do_not_echo_provider_body(self) -> None:
        secret = "must-not-appear"
        cases = (
            {"success": False, "error": secret},
            {"success": True, "data": [secret]},
            {"success": True, "data": {"base_resp": secret}},
            {
                "success": True,
                "data": {
                    "base_resp": {
                        "status_code": 401,
                        "status_msg": secret,
                    }
                },
            },
        )
        for response in cases:
            with self.subTest(response=response):
                with self.assertRaises(drama_video.DramaVideoProviderError) as caught:
                    drama_video._validate_provider_envelope(response, "asset upload")
                rendered = str(caught.exception)
                self.assertNotIn(secret, rendered)
                self.assertLessEqual(len(rendered), 80)

    def test_conflicting_asset_query_aliases_fail_before_paid_submission(self) -> None:
        self._prepare()
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        conflicts = (
            {
                "data": {
                    "id": "asset-1",
                    "Id": "asset-other",
                    "status": "ready",
                }
            },
            {
                "asset": {"id": "asset-1", "status": "ready"},
                "data": {"Id": "asset-1", "Status": "failed"},
            },
            {
                "asset": {
                    "id": "asset-1",
                    "status": "ready",
                    "base_resp": {"status_code": 500},
                },
            },
        )
        for index, response in enumerate(conflicts):
            with self.subTest(index=index):
                self._prepare(f"video-conflict-{index}")
                client = _FakeVideoClient()
                client.get_asset = Mock(return_value=response)
                with patch.dict(os.environ, env, clear=False):
                    with self.assertRaises(drama_video.DramaVideoProviderError):
                        drama_video.run_video_job(
                            f"video-conflict-{index}",
                            {
                                "confirm_real_video": True,
                                "budget_cny": 3,
                                "timeout_minutes": 1,
                            },
                            lambda *_: None,
                            client=client,
                            sleep=lambda _seconds: None,
                        )
                self.assertEqual(client.submissions, 0)
                self.assertIsNone(
                    drama_video.read_video_submission(f"video-conflict-{index}")
                )

    def test_unknown_asset_upload_is_durable_bounded_and_never_reposted(self) -> None:
        self._prepare("video-upload-unknown")
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        params = {
            "confirm_real_video": True,
            "budget_cny": 3,
            "timeout_minutes": 1,
        }
        first = _FakeVideoClient()
        first.upload_asset = Mock(
            side_effect=RuntimeError("secret-provider-response-must-not-appear")
        )
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown) as caught:
                drama_video.run_video_job(
                    "video-upload-unknown",
                    params,
                    lambda *_: None,
                    client=first,
                    sleep=lambda _seconds: None,
                )
        self.assertNotIn("secret-provider", str(caught.exception))
        ledger = drama_video.read_video_asset_upload("video-upload-unknown")
        self.assertEqual(ledger["status"], "submitting")
        self.assertEqual(ledger["asset_ids"], [])
        self.assertIsNone(
            drama_video.read_video_submission("video-upload-unknown")
        )

        second = _FakeVideoClient()
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    "video-upload-unknown",
                    params,
                    lambda *_: None,
                    client=second,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(second.uploads, 0)
        self.assertEqual(second.submissions, 0)

    def test_duplicate_uploaded_asset_id_blocks_create_and_future_repost(self) -> None:
        self._prepare("video-upload-duplicate")
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        params = {
            "confirm_real_video": True,
            "budget_cny": 3,
            "timeout_minutes": 1,
        }
        first = _FakeVideoClient()
        first.upload_asset = Mock(
            return_value={
                "success": True,
                "data": {
                    "Id": "same-asset",
                    "base_resp": {"status_code": 0},
                },
            }
        )
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(
                drama_video.DramaVideoProviderError,
                "duplicate asset id",
            ):
                drama_video.run_video_job(
                    "video-upload-duplicate",
                    params,
                    lambda *_: None,
                    client=first,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(first.upload_asset.call_count, 2)
        self.assertEqual(first.submissions, 0)
        ledger = drama_video.read_video_asset_upload("video-upload-duplicate")
        self.assertEqual(ledger["status"], "submitting")
        self.assertEqual(ledger["asset_ids"], ["same-asset"])

        second = _FakeVideoClient()
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    "video-upload-duplicate",
                    params,
                    lambda *_: None,
                    client=second,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(second.uploads, 0)
        self.assertEqual(second.submissions, 0)

    def test_provider_helpers_reject_mapping_subclasses_without_calling_them(self) -> None:
        secret = "secret-mapping-payload"

        class HostileMapping(dict):
            def get(self, *_args, **_kwargs):
                raise RuntimeError(secret)

        for helper, args in (
            (drama_video._extract_resource_id, (HostileMapping(), "asset")),
            (
                drama_video._validate_provider_envelope,
                (HostileMapping(), "asset upload"),
            ),
            (drama_video._extract_asset_status, (HostileMapping(),)),
        ):
            with self.subTest(helper=helper.__name__):
                with self.assertRaises(drama_video.DramaVideoProviderError) as caught:
                    helper(*args)
                self.assertNotIn(secret, str(caught.exception))

    def test_submitted_ledger_resumes_polling_without_upload_or_second_post(self) -> None:
        self._prepare()
        fingerprint = drama_video.load_video_inputs("video").fingerprint
        drama_video._write_video_submission("video", {
            "status": "submitted",
            "input_fingerprint": fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                _FakeVideoClient(), drama_video.DEFAULT_VIDEO_MODEL
            ),
            "result_hosts_fingerprint": drama_video.sha256_data(["result.example.test"]),
            "submission_count": 1,
            "task_id": "video-task-1",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
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
        ), patch(
            "src.drama_video._probe_mp4", return_value=drama_video.VideoSpec(5.0, 720, 1280)
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

    def test_video_ledger_readers_keep_episode_one_boundary(self) -> None:
        with self.assertRaisesRegex(
            drama_video.DramaVideoInputError, "supports episode 1 only"
        ):
            drama_video.read_video_submission("video", episode_no=2)
        with self.assertRaisesRegex(
            drama_video.DramaVideoInputError, "supports episode 1 only"
        ):
            drama_video.read_video_asset_upload("video", episode_no=2)

    def test_video_ledgers_reject_symlinked_ancestors_for_read_and_write(self) -> None:
        workspace = "ledger-symlink"
        workspace_root = paths.WORKSPACE_DIR / workspace
        workspace_root.mkdir()
        logs = workspace_root / "logs"
        outside = Path(self._tmp.name) / "outside-ledgers"
        outside.mkdir()
        logs.symlink_to(outside, target_is_directory=True)
        writers = (
            (
                drama_video._write_video_submission,
                "drama_video_submission.json",
            ),
            (
                drama_video._write_video_asset_upload,
                "drama_video_asset_upload.json",
            ),
        )
        for writer, filename in writers:
            target = outside / filename
            target.write_text("{}\n", encoding="utf-8")
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, "written safely"):
                writer(workspace, {"status": "sentinel"})
            self.assertEqual(target.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_submission(workspace)
        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_asset_upload(workspace)

        logs.unlink()
        logs.mkdir()
        samples = logs / "drama_video_samples"
        samples.symlink_to(outside, target_is_directory=True)
        sample_id = drama_video.ITER143_QUALITY20_SAMPLE_ID
        for writer, filename in (
            (drama_video._write_video_submission, "submission.json"),
            (drama_video._write_video_asset_upload, "asset_upload.json"),
        ):
            target = outside / filename
            target.write_text("{}\n", encoding="utf-8")
            before = target.read_bytes()
            with self.assertRaisesRegex(ValueError, "written safely"):
                writer(workspace, {"status": "sentinel"}, sample_id=sample_id)
            self.assertEqual(target.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_submission(workspace, sample_id=sample_id)
        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_asset_upload(workspace, sample_id=sample_id)

        samples.unlink()
        samples.mkdir()
        sample_dir = samples / sample_id
        sample_dir.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "written safely"):
            drama_video._write_video_submission(
                workspace, {"status": "sentinel"}, sample_id=sample_id
            )
        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_submission(workspace, sample_id=sample_id)

    def test_video_ledger_cleanup_rejects_ancestor_swap(self) -> None:
        workspace = "ledger-cleanup-swap"
        root = paths.WORKSPACE_DIR / workspace
        root.mkdir()
        outside = Path(self._tmp.name) / "outside-cleanup"
        outside.mkdir()

        drama_video._write_video_submission(workspace, {"status": "marker"})
        original_logs = root / "logs"
        retained_logs = root / "logs-retained"
        original_logs.rename(retained_logs)
        outside_target = outside / "drama_video_submission.json"
        outside_target.write_text("outside-owned\n", encoding="utf-8")
        original_logs.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "removed safely"):
            drama_video._delete_video_ledger(
                workspace,
                sample_id=None,
                filename="drama_video_submission.json",
                label="video submission",
            )
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "outside-owned\n")
        self.assertTrue((retained_logs / "drama_video_submission.json").is_file())

        original_logs.unlink()
        retained_logs.rename(original_logs)
        sample_id = drama_video.ITER143_QUALITY20_SAMPLE_ID
        drama_video._write_video_asset_upload(
            workspace,
            {"status": "marker"},
            sample_id=sample_id,
        )
        samples = original_logs / "drama_video_samples"
        retained_samples = original_logs / "drama_video_samples-retained"
        samples.rename(retained_samples)
        outside_target = outside / "asset_upload.json"
        outside_target.write_text("outside-sample-owned\n", encoding="utf-8")
        samples.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "removed safely"):
            drama_video._delete_video_ledger(
                workspace,
                sample_id=sample_id,
                filename="asset_upload.json",
                label="video asset upload",
            )
        self.assertEqual(
            outside_target.read_text(encoding="utf-8"), "outside-sample-owned\n"
        )
        self.assertTrue((retained_samples / sample_id / "asset_upload.json").is_file())

    def test_video_ledger_final_symlink_and_oversize_are_rejected(self) -> None:
        workspace = "ledger-final-boundary"
        logs = paths.WORKSPACE_DIR / workspace / "logs"
        logs.mkdir(parents=True)
        outside = Path(self._tmp.name) / "outside-final-ledger.json"
        outside.write_text("outside-owned\n", encoding="utf-8")
        target = logs / "drama_video_submission.json"
        target.symlink_to(outside)

        with self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_submission(workspace)
        with self.assertRaisesRegex(ValueError, "written safely"):
            drama_video._write_video_submission(workspace, {"status": "sentinel"})
        with self.assertRaisesRegex(ValueError, "removed safely"):
            drama_video._delete_video_ledger(
                workspace,
                sample_id=None,
                filename="drama_video_submission.json",
                label="video submission",
            )
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside-owned\n")

        target.unlink()
        target.write_bytes(b"x" * (drama_video.MAX_VIDEO_LEDGER_BYTES + 1))
        with patch.object(
            drama_video.os,
            "read",
            side_effect=AssertionError("oversize ledger must not be read"),
        ), self.assertRaisesRegex(ValueError, "ledger is unreadable"):
            drama_video.read_video_submission(workspace)

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
            "result_hosts_fingerprint": drama_video.sha256_data(["result.example.test"]),
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

    def test_episode1_single_submit_profile_caps_authorization(self) -> None:
        profile = drama_video.EPISODE1_SINGLE_SUBMIT_PROFILE
        with patch.dict(
            os.environ,
            {"SD_VIDEO_ESTIMATED_COST_CNY": "1"},
            clear=False,
        ):
            self.assertEqual(
                drama_video.validate_real_video_gate({
                    "confirm_real_video": True,
                    "budget_cny": 20,
                    "timeout_minutes": 10,
                    "authorization_profile": profile,
                }),
                (20.0, 10.0, 1.0),
            )
            with self.assertRaisesRegex(PermissionError, "budget exceeds 20"):
                drama_video.validate_real_video_gate({
                    "confirm_real_video": True,
                    "budget_cny": 20.01,
                    "timeout_minutes": 10,
                    "authorization_profile": profile,
                })
            with self.assertRaisesRegex(PermissionError, "exceeds 600"):
                drama_video.validate_real_video_gate({
                    "confirm_real_video": True,
                    "budget_cny": 20,
                    "timeout_minutes": 10.01,
                    "authorization_profile": profile,
                })
            with self.assertRaisesRegex(PermissionError, "unknown"):
                drama_video.validate_real_video_gate({
                    "confirm_real_video": True,
                    "budget_cny": 20,
                    "timeout_minutes": 10,
                    "authorization_profile": "untrusted-profile",
                })

    def test_iter142_profile_is_bound_to_exact_workspace_before_client(self) -> None:
        self._prepare("other-workspace")
        params = {
            "confirm_real_video": True,
            "budget_cny": 20,
            "timeout_minutes": 10,
            "authorization_profile": drama_video.ITER142_SINGLE_SUBMIT_PROFILE,
        }
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "20",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.DramaVideoClient",
            side_effect=AssertionError("client must not be constructed"),
        ):
            with self.assertRaisesRegex(PermissionError, "different workspace"):
                drama_video.run_video_job(
                    "other-workspace",
                    params,
                    lambda *_: None,
                )

    def test_iter143_quality20_profile_is_exact_and_workspace_bound(self) -> None:
        params = {
            "confirm_real_video": True,
            "budget_cny": 80,
            "timeout_minutes": 30,
            "authorization_profile": drama_video.ITER143_QUALITY20_PROFILE,
        }
        with patch.dict(
            os.environ,
            {"SD_VIDEO_ESTIMATED_COST_CNY": "80"},
            clear=False,
        ):
            self.assertEqual(
                drama_video.validate_real_video_gate(
                    params,
                    workspace=drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE,
                ),
                (80.0, 30.0, 80.0),
            )
            for key, value, message in (
                ("budget_cny", 80.01, "must equal 80"),
                ("timeout_minutes", 29.99, "must equal 1800"),
            ):
                changed = dict(params)
                changed[key] = value
                with self.subTest(key=key), self.assertRaisesRegex(
                    PermissionError,
                    message,
                ):
                    drama_video.validate_real_video_gate(
                        changed,
                        workspace=drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE,
                    )
            with self.assertRaisesRegex(PermissionError, "different workspace"):
                drama_video.validate_real_video_gate(
                    params,
                    workspace="other-workspace",
                )

    def test_iter143_submission_reader_rejects_misplaced_sample_contracts(self) -> None:
        workspace = "misplaced-video-ledger"
        prompt_sha256 = "d" * 64
        common = {
            "status": "submitted",
            "input_fingerprint": "a" * 64,
            "provider_fingerprint": "b" * 64,
            "result_hosts_fingerprint": "c" * 64,
            "submission_count": 1,
            "task_id": "video-task-1",
            "updated_at": int(time.time()),
        }
        drama_video._write_video_submission(workspace, {
            **common,
            **drama_video._video_authorization(
                80.0,
                30.0,
                80.0,
                duration_seconds=20,
                sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
                prompt_sha256=prompt_sha256,
            ),
        })
        with self.assertRaisesRegex(ValueError, "different sample"):
            drama_video.read_video_submission(workspace)
        self.assertEqual(drama_video.video_status(workspace)["state"], "blocked")

        drama_video._write_video_submission(
            workspace,
            {
                **common,
                **drama_video._video_authorization(3.0, 1.0, 2.0),
            },
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        with self.assertRaisesRegex(ValueError, "different sample"):
            drama_video.read_video_submission(
                workspace,
                sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
            )
        self.assertEqual(
            drama_video.video_status(
                workspace,
                sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
            )["state"],
            "blocked",
        )

    def test_iter143_quality20_isolated_paths_payload_and_qa(self) -> None:
        workspace = drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE
        self._prepare(workspace)
        default_video = drama_video.video_paths(workspace)
        default_video.video_path.parent.mkdir(parents=True, exist_ok=True)
        default_video.video_path.write_bytes(b"legacy-five-second-video")
        default_video.meta_path.write_bytes(b"legacy-five-second-meta")
        default_submission = drama_video.video_submission_path(workspace)
        default_asset_upload = drama_video.video_asset_upload_path(workspace)
        default_submission.parent.mkdir(parents=True, exist_ok=True)
        default_submission.write_bytes(b"legacy-five-second-submission")
        default_asset_upload.write_bytes(b"legacy-five-second-assets")
        before = {
            path: path.read_bytes()
            for path in (
                default_video.video_path,
                default_video.meta_path,
                default_submission,
                default_asset_upload,
            )
        }
        params = {
            "confirm_real_video": True,
            "budget_cny": 80,
            "timeout_minutes": 30,
            "authorization_profile": drama_video.ITER143_QUALITY20_PROFILE,
        }
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "80",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        client = _FakeVideoClient()
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.download_video",
            return_value=(drama_video._MOCK_MP4, "video/mp4"),
        ), patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(20.0, 720, 1280),
        ):
            result = drama_video.run_video_job(
                workspace,
                params,
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
            _data, meta = drama_video.read_video(
                workspace,
                sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
            )
            quality_status = drama_video.video_status(
                workspace,
                sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
            )
        self.assertEqual(client.submissions, 1)
        self.assertEqual(client.last_create_kwargs["duration"], 20)
        self.assertFalse(client.last_create_kwargs["generate_audio"])
        self.assertEqual(result["target_duration_seconds"], 20)
        self.assertEqual(meta["sample_id"], drama_video.ITER143_QUALITY20_SAMPLE_ID)
        self.assertEqual(quality_status["state"], "succeeded")
        quality_paths = drama_video.video_paths(
            workspace,
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        self.assertNotEqual(quality_paths.video_path, default_video.video_path)
        self.assertTrue(quality_paths.video_path.is_file())
        for path, original in before.items():
            self.assertEqual(path.read_bytes(), original)
        quality_submission = drama_video.read_video_submission(
            workspace,
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        quality_assets = drama_video.read_video_asset_upload(
            workspace,
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        self.assertEqual(quality_submission["status"], "succeeded")
        self.assertEqual(quality_submission["target_duration_seconds"], 20)
        self.assertEqual(quality_assets["status"], "uploaded_all")
        drift_client = _FakeVideoClient()
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video._video_prompt",
            return_value="drifted quality prompt",
        ):
            with self.assertRaisesRegex(
                drama_video.DramaVideoProviderError,
                "authorization",
            ):
                drama_video.run_video_job(
                    workspace,
                    params,
                    lambda *_: None,
                    client=drift_client,
                )
        self.assertEqual(
            (drift_client.uploads, drift_client.submissions, drift_client.polls),
            (0, 0, 0),
        )

    def test_iter143_quality20_unknown_never_reposts_in_its_namespace(self) -> None:
        workspace = drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE
        self._prepare(workspace)
        params = {
            "confirm_real_video": True,
            "budget_cny": 80,
            "timeout_minutes": 30,
            "authorization_profile": drama_video.ITER143_QUALITY20_PROFILE,
        }
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "80",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        first = _FakeVideoClient()
        first.create_video_task = Mock(side_effect=TimeoutError("private upstream"))
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    workspace,
                    params,
                    lambda *_: None,
                    client=first,
                    sleep=lambda _seconds: None,
                )
        ledger = drama_video.read_video_submission(
            workspace,
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        self.assertEqual(ledger["status"], "submitting")
        second = _FakeVideoClient()
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    workspace,
                    params,
                    lambda *_: None,
                    client=second,
                    sleep=lambda _seconds: None,
                )
        self.assertEqual(second.uploads, 0)
        self.assertEqual(second.submissions, 0)

    def test_iter143_quality20_resume_polls_only_quality_namespace(self) -> None:
        workspace = drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE
        self._prepare(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        client = _FakeVideoClient()
        provider_fingerprint = drama_video._video_provider_fingerprint(
            client,
            drama_video.DEFAULT_VIDEO_MODEL,
        )
        result_hosts_fingerprint = drama_video.sha256_data(["result.example.test"])
        prompt_sha256 = hashlib.sha256(
            drama_video._video_prompt(
                inputs,
                duration_seconds=20,
            ).encode("utf-8")
        ).hexdigest()
        drama_video._write_video_submission(workspace, {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": provider_fingerprint,
            "result_hosts_fingerprint": result_hosts_fingerprint,
            "submission_count": 1,
            "task_id": "default-task",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        drama_video._write_video_submission(
            workspace,
            {
                "status": "submitted",
                "input_fingerprint": inputs.fingerprint,
                "provider_fingerprint": provider_fingerprint,
                "result_hosts_fingerprint": result_hosts_fingerprint,
                "submission_count": 1,
                "task_id": "video-task-1",
                **drama_video._video_authorization(
                    80.0,
                    30.0,
                    80.0,
                    duration_seconds=20,
                    sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
                    prompt_sha256=prompt_sha256,
                ),
                "updated_at": int(time.time()),
            },
            sample_id=drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "80",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.download_video",
            return_value=(drama_video._MOCK_MP4, "video/mp4"),
        ), patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(20.0, 720, 1280),
        ):
            result = drama_video.run_video_job(
                workspace,
                {
                    "resume_submitted": True,
                    "authorization_profile": drama_video.ITER143_QUALITY20_PROFILE,
                },
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["resumed"])
        self.assertEqual((client.uploads, client.submissions), (0, 0))
        self.assertGreater(client.polls, 0)
        self.assertEqual(
            drama_video.read_video_submission(workspace)["task_id"],
            "default-task",
        )

    def test_iter143_quality20_prompt_and_script_are_fixed(self) -> None:
        self._prepare()
        prompt = drama_video._video_prompt(
            drama_video.load_video_inputs("video"),
            duration_seconds=20,
        )
        self.assertIn("20秒连续质量测试", prompt)
        self.assertIn("手指", prompt)
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "drama_video_episode1_quality20_single_submit.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--budget-cny 80", script)
        self.assertIn("--timeout-seconds 1800", script)
        self.assertIn("SD_VIDEO_ESTIMATED_COST_CNY=80", script)
        self.assertIn(drama_video.ITER143_QUALITY20_PROFILE, script)

    def test_iter143_quality20_smoke_reads_exact_sample_namespace(self) -> None:
        terminal = {"status": "succeeded", "result_summary": {}}
        meta = {
            "task_id": "quality-task",
            "status": "succeeded",
            "cost_cny": None,
            "budget_cny": 80.0,
            "duration_seconds": 20.0,
            "target_duration_seconds": 20,
            "sample_id": drama_video.ITER143_QUALITY20_SAMPLE_ID,
            "ratio": "9:16",
            "resolution": "720x1280px",
        }
        start_job = Mock(return_value={"job_id": "job-quality"})
        read_video = Mock(return_value=(b"quality-video", meta))
        with patch.dict(
            os.environ,
            {"CONFIRM_REAL_VIDEO_SMOKE": "可以跑真实视频 smoke"},
            clear=False,
        ), patch("src.drama_video.load_video_inputs"), patch(
            "src.drama_video_smoke.jobs.start_job",
            start_job,
        ), patch(
            "src.drama_video_smoke._wait",
            return_value=terminal,
        ), patch(
            "src.drama_video.read_video",
            read_video,
        ), patch("src.drama_video_smoke.write_json"):
            result = drama_video_smoke.run_smoke(
                drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE,
                real_video=True,
                confirm_real_video=True,
                budget_cny=0,
                timeout_seconds=1800,
                resume_submitted=True,
                authorization_profile=drama_video.ITER143_QUALITY20_PROFILE,
            )
        self.assertEqual(
            start_job.call_args.args[2]["authorization_profile"],
            drama_video.ITER143_QUALITY20_PROFILE,
        )
        self.assertTrue(start_job.call_args.args[2]["resume_submitted"])
        self.assertEqual(
            read_video.call_args.kwargs["sample_id"],
            drama_video.ITER143_QUALITY20_SAMPLE_ID,
        )
        self.assertEqual(result["sample_id"], drama_video.ITER143_QUALITY20_SAMPLE_ID)

    def test_real_smoke_forwards_single_submit_profile_to_last_hop(self) -> None:
        terminal = {"status": "succeeded", "result_summary": {}}
        meta = {
            "task_id": "paid-task",
            "status": "succeeded",
            "cost_cny": 1.0,
            "budget_cny": 20.0,
            "duration_seconds": 5,
            "ratio": "9:16",
            "resolution": "720p",
        }
        start_job = Mock(return_value={"job_id": "job-1"})
        with patch.dict(
            os.environ,
            {"CONFIRM_REAL_VIDEO_SMOKE": "可以跑真实视频 smoke"},
            clear=False,
        ), patch("src.drama_video.load_video_inputs"), patch(
            "src.drama_video_smoke.jobs.start_job",
            start_job,
        ), patch(
            "src.drama_video_smoke._wait",
            return_value=terminal,
        ), patch(
            "src.drama_video.read_video",
            return_value=(b"paid-video", meta),
        ), patch("src.drama_video_smoke.write_json"):
            drama_video_smoke.run_smoke(
                "video",
                real_video=True,
                confirm_real_video=True,
                budget_cny=20,
                timeout_seconds=600,
                authorization_profile=drama_video.EPISODE1_SINGLE_SUBMIT_PROFILE,
            )
        self.assertEqual(
            start_job.call_args.args[2]["authorization_profile"],
            drama_video.EPISODE1_SINGLE_SUBMIT_PROFILE,
        )

    def test_real_smoke_needs_shell_and_cli_confirmation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                drama_video_smoke.run_smoke(
                    "existing", real_video=True, confirm_real_video=True, budget_cny=3
                )
