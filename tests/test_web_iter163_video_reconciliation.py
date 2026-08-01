from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from src import drama_video_smoke
from src.web import routes
from tests._drama_base import DramaTestBase


class WebIter163VideoReconciliationTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.workspace = "web-iter163-video"
        drama_video_smoke._prepare_mock_inputs(self.workspace)

    def test_public_video_status_is_a_defense_in_depth_allowlist(self) -> None:
        internal = {
            "state": "provider_rejected",
            "error_code": "video_create_provider_rejected",
            "submission_consumed": True,
            "download_ready": False,
            "task_id": "provider-task-private",
            "request_id": "provider-request-private",
            "response_body": "private-response-body",
            "asset_ids": ["material-private"],
            "evidence_fingerprint": "a" * 64,
            "video": {
                "status": "succeeded",
                "duration_seconds": 5,
                "ratio": "9:16",
                "resolution": "720x1280px",
                "file_size_bytes": 123,
                "task_id": "provider-task-private",
                "sample_id": "material-private",
                "prompt_sha256": "b" * 64,
                "provider_fingerprint": "c" * 64,
            },
        }
        with patch(
            "src.drama_video.video_status",
            return_value=internal,
        ), patch(
            "src.web.routes.jobs.active_jobs",
            return_value=[],
        ), patch(
            "src.web.routes.jobs.recent_jobs",
            return_value=[{
                "step": "drama-video",
                "status": "failed",
                "error": "private-response-body",
            }],
        ):
            status, _content_type, body = routes.api_drama_video_status(
                self.workspace
            )
        self.assertEqual(status, 200)
        public = json.loads(body)
        self.assertEqual(public["state"], "provider_rejected")
        rendered = json.dumps(public, sort_keys=True)
        for private in (
            "provider-task-private",
            "provider-request-private",
            "private-response-body",
            "material-private",
            "evidence_fingerprint",
            "provider_fingerprint",
            "prompt_sha256",
            "task_id",
            "request_id",
            "response_body",
            "asset_ids",
            "sample_id",
        ):
            self.assertNotIn(private, rendered)

    def test_video_panel_explains_three_states_and_hides_consumed_submit(self) -> None:
        source = Path("src/web/static.py").read_text(encoding="utf-8")
        self.assertIn('request_not_sent: "请求确定未发送"', source)
        self.assertIn('provider_rejected: "Provider 已拒绝"', source)
        self.assertIn('submission_unknown: "提交结果待对账"', source)
        self.assertIn(
            '["provider_rejected", "submission_unknown"].includes(state)',
            source,
        )
        self.assertIn("费用不推断为 0，页面不会重提", source)
        self.assertIn("必须重新明确授权", source)

    def test_reconciled_submitted_status_can_start_poll_only_resume(self) -> None:
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.video_status",
            return_value={"state": "submitted", "resumable_poll": True},
        ), patch(
            "src.web.routes.jobs.start_job",
            return_value={"job_id": "local-job", "status": "pending"},
        ) as start:
            status, _content_type, body = routes.api_drama_video_generate(
                self.workspace,
                b'{"episode_no":1,"resume_submitted":true}',
            )
        self.assertEqual(status, 202, body.decode())
        self.assertEqual(
            start.call_args.args,
            (self.workspace, "drama-video", {"episode_no": 1, "resume_submitted": True}),
        )
