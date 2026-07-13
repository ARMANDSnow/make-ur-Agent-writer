"""Iteration 101: residual full-chain blocker regressions."""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

from src import (
    character_designer,
    ai_draw_client,
    drama_multimodal_smoke as multi,
    drama_reviewer,
    drama_season_export,
    drama_store,
    drama_video,
    drama_video_smoke,
    storyboard_builder,
)
from src.drama_schemas import CharacterSheet, DramaReview, character_paths, episode_paths
from src.schemas import model_to_dict
from src.utils import read_json, write_json
from src.web import jobs, routes
from src.web.server import WebHandler
from src.web.workspace_ctx import use_workspace
from tests._drama_base import DramaTestBase
from tests.test_drama_video import _FakeVideoClient


class Iter101DramaBlockerTests(DramaTestBase):
    def _assembled(self, name: str = "iter101", *, reference: bool = False) -> None:
        self._make_drama_workspace(name, "推理", episode_count=3)
        self._write_setup(name, hook=True)
        write_json(episode_paths(name).storyboard_path, storyboard_builder.run(name, mock=True))
        sheet = character_designer.run(name, mock=True)
        if reference:
            rel = "data/character_refs/c001/ref.png"
            path = character_paths(name).refs_dir / "c001" / "ref.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(multi._PNG_1X1)
            sheet["characters"][0]["reference_images"] = [{"path": rel}]
        write_json(character_paths(name).sheet_path, sheet)
        write_json(episode_paths(name).review_path, drama_reviewer.run(name, mock=True))
        drama_store.assemble_episode(name)

    def test_succeeded_text_attempt_can_start_explicit_new_revision(self) -> None:
        self._make_drama_workspace("text-revision", "推理")
        first = {"episode_no": 1, "title": "revision-1"}
        second = {"episode_no": 1, "title": "revision-2"}
        config = {
            "model": "provider/model-v1",
            "base_url": "https://provider.example/v1",
            "api_key": "account-a",
        }
        with use_workspace("text-revision"), patch(
            "src.config.get_model_config", return_value=config
        ):
            result, token = jobs._call_drama_text_model("drama-plan", {}, 1, lambda: first)
            jobs._bind_drama_text_artifact(token, result)
            write_json(episode_paths("text-revision").setup_path, result)
            jobs._mark_drama_text_attempt(token, "succeeded")

            wizard_path = multi.paths.workspace_root("text-revision") / "data" / "wizard_input.json"
            wizard = read_json(wizard_path)
            wizard["topic"] = "authorized revision"
            write_json(wizard_path, wizard)
            provider = Mock(return_value=second)
            revised, revised_token = jobs._call_drama_text_model(
                "drama-plan",
                {"confirm_real_text": True, "confirm_new_text_revision": True},
                1,
                provider,
            )
            jobs._bind_drama_text_artifact(revised_token, revised)
            write_json(episode_paths("text-revision").setup_path, revised)
            jobs._mark_drama_text_attempt(revised_token, "succeeded")
            row = jobs._load_drama_text_attempts("text-revision")["attempts"]["drama-plan:1"]

        provider.assert_called_once_with()
        self.assertEqual((row["attempt_count"], row["revision"]), (2, 2))
        self.assertEqual(len(row["completed_revisions"]), 1)
        self.assertEqual(row["completed_revisions"][0]["status"], "succeeded")

    def test_reject_review_is_saved_but_not_assembled(self) -> None:
        self._assembled("review-reject")
        ep = episode_paths("review-reject")
        approved = drama_reviewer.run("review-reject", mock=True)
        rejected = model_to_dict(DramaReview(**{
            **approved,
            "sub_scores": {
                "hook": 4,
                "pace": 8,
                "ai_friendly": 8,
                "character_consistency": 8,
                "cliffhanger": 8,
            },
        }))
        with use_workspace("review-reject"), patch(
            "src.drama_reviewer.run", return_value=rejected
        ):
            result = jobs._step_drama_review_assemble({}, lambda *_: None)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["verdict"], "Reject")
        self.assertFalse(result["assembled"])
        self.assertTrue(ep.review_path.is_file())
        self.assertFalse(ep.episode_path.exists())
        self.assertFalse(ep.meta_path.exists())
        with self.assertRaisesRegex(FileNotFoundError, "missing assembled episode"):
            drama_store.export_episode("review-reject", format="json")
        detail = drama_store.episode_detail("review-reject")
        self.assertIsNone(detail["episode"])
        self.assertEqual(detail["review"]["verdict"], "Reject")

    def test_manual_assemble_rejects_mixed_review_lineage(self) -> None:
        self._assembled("review-lineage")
        setup_path = episode_paths("review-lineage").setup_path
        setup = read_json(setup_path)
        setup["logline"] = "changed after review"
        write_json(setup_path, setup)
        with self.assertRaisesRegex(ValueError, "run review again"):
            drama_store.assemble_episode("review-lineage")
        self.assertTrue(drama_store.is_episode_stale("review-lineage"))

    def test_existing_web_workspace_can_be_adopted_for_real_image_phase(self) -> None:
        self._assembled("existing-media")
        observed = {}

        def stop_before_provider(workspace, state, _opts, *, real_image):
            observed["workspace"] = workspace
            observed["text"] = dict(state["phases"]["real_text"])
            observed["real_image"] = real_image
            state["status"] = "awaiting_test_image_provider"
            multi._save(state)
            return False

        with patch("src.drama_multimodal_smoke._run_images", side_effect=stop_before_provider):
            state = multi._run_claimed(
                "existing-media",
                real_text=False,
                real_image=True,
                real_video=False,
                options={},
            )
        self.assertEqual(state["status"], "awaiting_test_image_provider")
        self.assertEqual(observed["workspace"], "existing-media")
        self.assertTrue(observed["real_image"])
        self.assertEqual(observed["text"]["status"], "succeeded")
        self.assertTrue(observed["text"]["imported_existing_workspace"])
        self.assertTrue(multi._text_artifacts_current("existing-media", observed["text"]))

    def test_legacy_review_lineage_is_proven_and_migrated_before_images(self) -> None:
        self._assembled("legacy-review")
        ep = episode_paths("legacy-review")
        review = read_json(ep.review_path)
        review.pop("input_fingerprint", None)
        meta = read_json(ep.meta_path)
        meta["agent_reviews"] = [review]
        meta["input_fingerprint"] = drama_store.input_fingerprint(
            setup=read_json(ep.setup_path),
            storyboard=read_json(ep.storyboard_path),
            characters=read_json(character_paths("legacy-review").sheet_path),
            review=review,
            episode_no=1,
            version=meta["input_fingerprint_version"],
            character_ids=meta["character_fingerprint_ids"],
        )
        write_json(ep.review_path, review)
        write_json(ep.meta_path, meta)
        observed = {}

        def stop_before_provider(_workspace, _state, _opts, *, real_image):
            observed["review"] = read_json(ep.review_path)
            observed["real_image"] = real_image
            return False

        with patch("src.drama_multimodal_smoke._run_images", side_effect=stop_before_provider):
            multi._run_claimed(
                "legacy-review", real_text=False, real_image=True,
                real_video=False, options={},
            )
        self.assertTrue(observed["real_image"])
        self.assertRegex(observed["review"]["input_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertFalse(drama_store.is_episode_stale("legacy-review"))

    def test_legacy_review_migration_crash_before_state_save_is_recoverable(self) -> None:
        self._assembled("legacy-review-crash")
        ep = episode_paths("legacy-review-crash")
        review = read_json(ep.review_path)
        review.pop("input_fingerprint", None)
        meta = read_json(ep.meta_path)
        meta["agent_reviews"] = [review]
        meta["input_fingerprint"] = drama_store.input_fingerprint(
            setup=read_json(ep.setup_path),
            storyboard=read_json(ep.storyboard_path),
            characters=read_json(character_paths("legacy-review-crash").sheet_path),
            review=review,
            episode_no=1,
            version=meta["input_fingerprint_version"],
            character_ids=meta["character_fingerprint_ids"],
        )
        write_json(ep.review_path, review)
        write_json(ep.meta_path, meta)
        with patch("src.drama_multimodal_smoke._save", side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                multi._run_claimed(
                    "legacy-review-crash", real_text=False, real_image=True,
                    real_video=False, options={},
                )
        self.assertFalse(multi.state_path("legacy-review-crash").exists())
        self.assertRegex(read_json(ep.review_path)["input_fingerprint"], r"^[0-9a-f]{64}$")
        provider = Mock(return_value=False)
        with patch("src.drama_multimodal_smoke._run_images", provider):
            multi._run_claimed(
                "legacy-review-crash", real_text=False, real_image=True,
                real_video=False, options={},
            )
        provider.assert_called_once()

    def test_stale_existing_workspace_is_rejected_before_image_provider(self) -> None:
        self._assembled("stale-media")
        setup_path = episode_paths("stale-media").setup_path
        setup = read_json(setup_path)
        setup["logline"] = "changed after approval"
        write_json(setup_path, setup)
        provider = Mock()
        with patch("src.drama_multimodal_smoke._run_images", provider):
            with self.assertRaisesRegex(ValueError, "run review again"):
                multi._run_claimed(
                    "stale-media", real_text=False, real_image=True,
                    real_video=False, options={},
                )
        provider.assert_not_called()

    def test_existing_media_rejects_nested_symlink_before_state_or_image_write(self) -> None:
        self._assembled("symlink-media")
        root = multi.paths.workspace_root("symlink-media")
        logs = root / "logs"
        external = root.parent / "outside-logs"
        logs.rename(external)
        logs.symlink_to(external, target_is_directory=True)
        provider = Mock()
        with patch("src.drama_multimodal_smoke._run_images", provider):
            with self.assertRaisesRegex(ValueError, "symlink"):
                multi._run_claimed(
                    "symlink-media", real_text=False, real_image=True,
                    real_video=False, options={},
                )
        provider.assert_not_called()
        with self.assertRaises(OSError):
            ai_draw_client._atomic_write_bytes(logs / "escaped.png", multi._PNG_1X1)
        self.assertFalse((external / "escaped.png").exists())

    def test_continuation_collision_allocates_new_identity_and_keeps_history(self) -> None:
        self._make_drama_workspace("character-collision", "推理")
        self._write_setup("character-collision", hook=True)
        write_json(
            episode_paths("character-collision").storyboard_path,
            storyboard_builder.run("character-collision", mock=True),
        )
        existing = character_designer.run("character-collision", mock=True)
        old_name = existing["characters"][0]["name"]
        existing["characters"][0]["reference_images"] = [
            {"path": "data/character_refs/c001/old.png"}
        ]
        incoming = {
            **existing,
            "episode_no": 2,
            "generated_episode_nos": [2],
            "characters": [{
                **existing["characters"][0],
                "id": "c001",
                "name": "真正的新角色",
                "lora_token": "new_identity",
                "appearances": [2],
                "reference_images": [],
                "visual_contrast_with": {},
            }],
        }
        merged = character_designer.merge_character_sheet(existing, incoming)
        by_id = {row["id"]: row for row in merged["characters"]}
        self.assertEqual(by_id["c001"]["name"], old_name)
        newcomer = next(row for row in merged["characters"] if row["name"] == "真正的新角色")
        self.assertEqual(newcomer["id"], "c003")
        self.assertEqual(newcomer["reference_images"], [])
        self.assertEqual(merged["generated_episode_nos"], [1, 2])

        third = {
            **merged,
            "episode_no": 3,
            "generated_episode_nos": [3],
            "characters": [{
                **newcomer,
                "id": "c001",
                "name": "第三集角色",
                "lora_token": "third_identity",
                "appearances": [3],
            }],
        }
        merged = character_designer.merge_character_sheet(merged, third)
        self.assertTrue(character_designer.character_sheet_generated_for_episode(
            merged, episode_no=2
        ))
        self.assertEqual(merged["generated_episode_nos"], [1, 2, 3])

        legacy = dict(merged)
        legacy.pop("generated_episode_nos", None)
        legacy["episode_no"] = 3
        self.assertFalse(character_designer.character_sheet_generated_for_episode(
            legacy, episode_no=2
        ))

    def test_character_revision_replaces_episode_roles_and_single_run_caps_at_eight(self) -> None:
        rows = [
            {"id": f"c{number:03d}", "name": f"角色{number}", "lora_token": f"role_{number}"}
            for number in range(1, 10)
        ]
        with self.assertRaisesRegex(ValueError, "at most 8"):
            character_designer.merge_character_sheet(None, {"characters": rows})
        active_existing = {
            "episode_no": 2,
            "generated_episode_nos": [1],
            "characters": [
                {"id": "c001", "name": "主角", "lora_token": "lead", "appearances": [1, 2]},
                {"id": "c002", "name": "反派", "lora_token": "villain", "appearances": [1, 2]},
            ],
        }
        self.assertEqual(
            character_designer._character_generation_limit(active_existing, episode_no=2),
            6,
        )
        previous_eight = {
            "episode_no": 1,
            "generated_episode_nos": [1],
            "characters": [
                {
                    "id": f"c{number:03d}", "name": f"旧角色{number}",
                    "lora_token": f"old_{number}", "appearances": [1],
                }
                for number in range(1, 9)
            ],
        }
        self.assertEqual(
            character_designer._character_generation_limit(previous_eight, episode_no=2),
            8,
        )
        introduced = character_designer.merge_character_sheet(previous_eight, {
            "episode_no": 2,
            "generated_episode_nos": [2],
            "characters": [{
                "id": "c009", "name": "新登场", "lora_token": "new_nine",
                "appearances": [2],
            }],
        })
        self.assertEqual(
            len(drama_store.episode_character_fingerprint_ids(introduced, episode_no=2)),
            8,
        )
        self.assertIn("c009", drama_store.episode_character_fingerprint_ids(
            introduced, episode_no=2
        ))
        eight_new = {
            "episode_no": 2,
            "generated_episode_nos": [2],
            "characters": [
                {
                    "id": f"c{number:03d}", "name": f"新角色{number}",
                    "lora_token": f"new_{number}", "appearances": [2],
                }
                for number in range(3, 11)
            ],
        }
        with self.assertRaisesRegex(ValueError, "episode may include at most 8"):
            character_designer.merge_character_sheet(active_existing, eight_new)

        existing = {
            "episode_no": 2,
            "generated_episode_nos": [1, 2],
            "characters": [
                {"id": "c001", "name": "主角", "lora_token": "lead", "appearances": [1, 2]},
                {"id": "c003", "name": "旧新人", "lora_token": "old_new", "appearances": [2]},
            ],
        }
        incoming = {
            "episode_no": 2,
            "generated_episode_nos": [2],
            "characters": [
                {"id": "c001", "name": "被模型误改的主角", "lora_token": "wrong", "appearances": [2]},
                {"id": "c004", "name": "替代新人", "lora_token": "replacement", "appearances": [2]},
            ],
        }
        merged = character_designer.merge_character_sheet(existing, incoming)
        self.assertNotIn("旧新人", [row["name"] for row in merged["characters"]])
        self.assertEqual([row["name"] for row in merged["characters"]], ["主角", "替代新人"])
        sensitive = dict(existing)
        sensitive["characters"] = [dict(existing["characters"][0])]
        sensitive["characters"][0]["reference_images"] = [{"path": "x", "prompt": "PRIVATE_PROMPT"}]
        sensitive["characters"][0]["agent_suggestions"] = [{"reason": "PRIVATE_NOTE"}]
        projection = character_designer._character_prompt_projection(
            sensitive, episode_no=2
        )
        rendered = json.dumps(projection, ensure_ascii=False)
        self.assertNotIn("PRIVATE_PROMPT", rendered)
        self.assertNotIn("PRIVATE_NOTE", rendered)

    def test_nine_character_library_reuse_keeps_episode_cast_bounded(self) -> None:
        rows = [
            {
                "id": f"c{number:03d}", "name": f"角色{number}",
                "lora_token": f"role_{number}", "appearances": [2],
            }
            for number in range(1, 10)
        ]
        reused = character_designer.reuse_character_sheet_for_episode(
            {"episode_no": 2, "generated_episode_nos": [1, 2], "characters": rows},
            episode_no=2,
        )
        active = drama_store.episode_character_fingerprint_ids(reused, episode_no=2)
        self.assertEqual(len(active), 8)
        self.assertNotIn(2, reused["characters"][8]["appearances"])

        legacy = dict(reused)
        legacy.pop("generated_episode_nos", None)
        legacy["episode_no"] = 2
        skipped = character_designer.reuse_character_sheet_for_episode(legacy, episode_no=3)
        self.assertEqual(skipped["generated_episode_nos"], [1])
        self.assertFalse(character_designer.character_sheet_generated_for_episode(
            skipped, episode_no=2
        ))

    def test_season_character_library_accepts_ninth_identity(self) -> None:
        rows = [
            {"id": f"c{number:03d}", "name": f"角色{number}", "lora_token": f"role_{number}"}
            for number in range(1, 10)
        ]
        sheet = CharacterSheet(characters=rows)
        self.assertEqual(len(sheet.characters), 9)

    def test_submitted_video_resume_uses_durable_authorization(self) -> None:
        drama_video_smoke._prepare_mock_inputs("video-resume-ui")
        inputs = drama_video.load_video_inputs("video-resume-ui")
        client = _FakeVideoClient()
        client.get_task = Mock(return_value={"task": {
            "id": "video-task-1",
            "status": "completed",
            "video_url": "https://result.example.test/resumed.mp4",
            "cost_cny": 1.0,
        }})
        drama_video._write_video_submission("video-resume-ui", {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                client, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "result_hosts_fingerprint": drama_video.sha256_data(["result.example.test"]),
            "submission_count": 1,
            "task_id": "video-task-1",
            **drama_video._video_authorization(7.0, 9.0, 2.0),
            "updated_at": int(time.time()),
        })
        env = {
            "SD_VIDEO_MODE": "real",
            # Deliberately drift from the original estimate: a resume is a pure
            # poll and must use the durable authorization, not current UI/env.
            "SD_VIDEO_ESTIMATED_COST_CNY": "99",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video.download_video",
            return_value=(drama_video._MOCK_MP4, "video/mp4"),
        ), patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(5.0, 720, 1280),
        ):
            readiness = multi._video_readiness(
                "video-resume-ui", {"confirm_real_video": True}, real_video=True
            )
            self.assertEqual(readiness["estimated_cost_cny"], 2.0)
            self.assertEqual(readiness["budget_cny"], 7.0)
            self.assertTrue(readiness["resuming_submitted_task"])
            result = drama_video.run_video_job(
                "video-resume-ui",
                {"resume_submitted": True},
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["resumed"])
        self.assertEqual((client.uploads, client.submissions), (0, 0))

    def test_multimodal_video_smoke_forwards_pure_poll_resume(self) -> None:
        drama_video_smoke._prepare_mock_inputs("runner-video-resume")
        terminal = {"status": "succeeded", "result_summary": {"network_requests": 1}}
        meta = {
            "task_id": "task-resumed", "cost_cny": 1.0, "budget_cny": 7.0,
            "duration_seconds": 5, "ratio": "9:16", "resolution": "720p",
        }
        env = {
            "CONFIRM_REAL_VIDEO_SMOKE": drama_video_smoke.REAL_CONFIRMATION,
            "SD_VIDEO_MODE": "real",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            drama_video_smoke.jobs, "start_job", return_value={"job_id": "job-resume"}
        ) as start, patch.object(
            drama_video_smoke, "_wait", return_value=terminal
        ), patch.object(
            drama_video_smoke.drama_video, "read_video",
            return_value=(drama_video._MOCK_MP4, meta),
        ):
            drama_video_smoke.run_smoke(
                "runner-video-resume",
                real_video=True,
                confirm_real_video=True,
                budget_cny=0.0,
                timeout_seconds=9.0,
                prepare_inputs=False,
                reset_jobs=False,
                resume_submitted=True,
            )
        self.assertEqual(
            start.call_args.args,
            ("runner-video-resume", "drama-video", {"episode_no": 1, "resume_submitted": True}),
        )

    def test_submitted_video_is_not_hidden_or_overwritten_when_mode_drifts(self) -> None:
        drama_video_smoke._prepare_mock_inputs("video-mode-drift")
        inputs = drama_video.load_video_inputs("video-mode-drift")
        drama_video._run_mock_video(inputs, lambda *_: None)
        authorization = drama_video._video_authorization(7.0, 9.0, 2.0)
        drama_video._write_video_submission("video-mode-drift", {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": "a" * 64,
            "result_hosts_fingerprint": "b" * 64,
            "submission_count": 1,
            "task_id": "real-task-still-running",
            **authorization,
        })
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "mock"}, clear=False):
            status = drama_video.video_status("video-mode-drift")
            self.assertEqual(status["state"], "submitted")
            with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "restore"):
                drama_video.run_video_job(
                    "video-mode-drift", {}, lambda *_: None,
                )
            error, params = routes._validated_drama_video_params({
                "episode_no": 1, "resume_submitted": True,
            })
        self.assertIn("restore real video", error or "")
        self.assertEqual(params, {})

    def test_legacy_submitted_video_without_authorization_requires_reconciliation(self) -> None:
        drama_video_smoke._prepare_mock_inputs("legacy-video-ledger")
        inputs = drama_video.load_video_inputs("legacy-video-ledger")
        drama_video._write_video_submission("legacy-video-ledger", {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": "a" * 64,
            "result_hosts_fingerprint": "b" * 64,
            "submission_count": 1,
            "task_id": "legacy-task",
        })
        status = drama_video.video_status("legacy-video-ledger")
        self.assertEqual(status["state"], "blocked")
        self.assertTrue(status["requires_reconciliation"])

    def test_video_resume_route_requires_matching_durable_submission(self) -> None:
        with patch.dict(os.environ, {"SD_VIDEO_MODE": "real"}, clear=False):
            error, params = routes._validated_drama_video_params({
                "episode_no": 1,
                "resume_submitted": True,
            })
        self.assertIsNone(error)
        self.assertEqual(params, {"episode_no": 1, "resume_submitted": True})

    def test_callback_capability_is_redacted_from_access_log(self) -> None:
        token = "A" * 48
        fake = type("FakeHandler", (), {"address_string": lambda self: "127.0.0.1"})()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            WebHandler.log_message(
                fake,
                '"%s" %s %s',
                f"GET /media/drama-assets/{token} HTTP/1.1",
                "200",
                "123",
            )
        rendered = stderr.getvalue()
        self.assertNotIn(token, rendered)
        self.assertIn("/media/drama-assets/<redacted>", rendered)

    def test_exports_project_json_and_rewrite_reference_member_path(self) -> None:
        self._assembled("export-projection", reference=True)
        ep = episode_paths("export-projection")
        episode = read_json(ep.episode_path)
        episode["secret_extra"] = "DO_NOT_EXPORT"
        write_json(ep.episode_path, episode)
        exported = json.loads(drama_store.export_episode(
            "export-projection", format="json"
        ).body)
        self.assertNotIn("secret_extra", exported)
        drama_store.assemble_episode("export-projection")

        package = drama_season_export.export_season("export-projection", mode="snapshot")
        with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
            characters = json.loads(archive.read("characters/season_01.json"))
            ref_path = characters["characters"][0]["reference_images"][0]["path"]
            self.assertEqual(ref_path, "character_refs/c001/ref.png")
            self.assertIn(ref_path, archive.namelist())

    def test_season_export_rejects_fake_png_and_cross_character_path(self) -> None:
        self._assembled("bad-reference")
        sheet_path = character_paths("bad-reference").sheet_path
        sheet = read_json(sheet_path)
        wrong = "data/character_refs/c999/ref.png"
        path = multi.paths.workspace_root("bad-reference") / wrong
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not-a-png")
        sheet["characters"][0]["reference_images"] = [{"path": wrong}]
        write_json(sheet_path, sheet)
        state = drama_season_export.season_export_readiness("bad-reference")
        self.assertIn("reference_character_or_path_mismatch", state["asset_errors"])

        correct = "data/character_refs/c001/ref.png"
        correct_path = multi.paths.workspace_root("bad-reference") / correct
        correct_path.parent.mkdir(parents=True, exist_ok=True)
        correct_path.write_bytes(b"not-a-png")
        sheet["characters"][0]["reference_images"] = [{"path": correct}]
        write_json(sheet_path, sheet)
        state = drama_season_export.season_export_readiness("bad-reference")
        self.assertIn("invalid_reference_image", state["asset_errors"])

    def test_snapshot_omits_dangling_character_reference(self) -> None:
        self._assembled("missing-reference")
        sheet_path = character_paths("missing-reference").sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"][0]["reference_images"] = [{
            "path": "data/character_refs/c001/missing.png",
        }]
        write_json(sheet_path, sheet)
        drama_store.assemble_episode("missing-reference")
        package = drama_season_export.export_season("missing-reference", mode="snapshot")
        with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
            characters = json.loads(archive.read("characters/season_01.json"))
        self.assertEqual(characters["characters"][0]["reference_images"], [])
        self.assertIn(
            "data/character_refs/c001/missing.png",
            package.manifest["missing_reference_images"],
        )
