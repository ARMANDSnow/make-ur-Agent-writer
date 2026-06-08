import json
import unittest
import tempfile
from unittest.mock import patch

from pathlib import Path

from src.book_runner import (
    BookRunBlocked,
    _archive_chapter_artifacts,
    _auto_apply_advances,
    _plan_metadata_failures,
    check_write_readiness,
    run_write_book,
)
from src.plot_planner import chapter_plan_item_fingerprint, plan_fingerprint


def _strict_plan(chapters: int = 2) -> dict:
    data = {
        "target_chapters": chapters,
        "overall_arc": "arc",
        "start_chapter_id": "v1_ch003",
        "start_point_fingerprint": "start-fp",
        "chapters": [
            {
                "chapter_no": i,
                "title": f"第 {i} 章",
                "opening_scene": "开场",
                "key_events": ["事件"],
                "relationships_in_play": [],
                "ending_hook": "钩子",
                "target_chinese_chars": 4000,
                "plot_purpose": "用途",
            }
            for i in range(1, chapters + 1)
        ],
        "schema_version": 1,
    }
    for item in data["chapters"]:
        item["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(item)
    data["plan_fingerprint"] = plan_fingerprint(data)
    return data


class BookRunnerPlanMetadataTests(unittest.TestCase):
    def test_strict_plan_metadata_passes(self) -> None:
        with patch("src.book_runner.start_point.get_start_chapter_id", return_value="v1_ch003"), patch(
            "src.book_runner.start_point.start_point_fingerprint", return_value="start-fp"
        ):
            failures = _plan_metadata_failures(
                _strict_plan(),
                chapter_numbers=[1, 2],
                require_start_point=True,
            )
        self.assertEqual(failures, [])

    def test_legacy_plan_without_fingerprints_blocks(self) -> None:
        data = _strict_plan()
        data.pop("plan_fingerprint")
        data.pop("start_point_fingerprint")
        data["chapters"][0].pop("chapter_plan_item_fingerprint")
        with patch("src.book_runner.start_point.get_start_chapter_id", return_value="v1_ch003"), patch(
            "src.book_runner.start_point.start_point_fingerprint", return_value="start-fp"
        ):
            failures = _plan_metadata_failures(
                data,
                chapter_numbers=[1],
                require_start_point=True,
            )
        self.assertIn("plan_fingerprint_missing", failures)
        self.assertIn("start_point_fingerprint_missing", failures)
        self.assertIn("chapter_01_plan_item_fingerprint_missing", failures)

    def test_start_point_fingerprint_mismatch_blocks(self) -> None:
        with patch("src.book_runner.start_point.get_start_chapter_id", return_value="v1_ch003"), patch(
            "src.book_runner.start_point.start_point_fingerprint", return_value="new-start-fp"
        ):
            failures = _plan_metadata_failures(
                _strict_plan(),
                chapter_numbers=[1],
                require_start_point=True,
            )
        self.assertIn("start_point_fingerprint_mismatch", failures)


class BookRunnerReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "outputs" / "drafts").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _common_patches(self, raw_plan: dict, parsed_plan: dict | None = None):
        parsed = parsed_plan
        if parsed is None:
            parsed = {
                int(item["chapter_no"]): dict(item)
                for item in raw_plan.get("chapters", [])
                if isinstance(item, dict) and item.get("chapter_no") is not None
            }
        return [
            patch("src.book_runner.start_point.get_start_chapter_id", return_value="v1_ch003"),
            patch("src.book_runner.start_point.start_point_fingerprint", return_value="start-fp"),
            patch("src.book_runner._load_raw_chapter_plan", return_value=raw_plan),
            patch("src.book_runner._load_chapter_plan", return_value=parsed),
            patch("src.book_runner.paths.workspace_name", return_value="unit"),
            patch("src.book_runner.paths.workspace_root", return_value=self.root),
            patch("src.book_runner.paths.drafts_dir", return_value=self.root / "outputs" / "drafts"),
            patch("src.book_runner.paths.entity_graph_path", return_value=self.root / "data" / "entity_graph.json"),
            patch("src.book_runner.paths.llm_calls_log_path", return_value=self.root / "logs" / "llm_calls.jsonl"),
            patch("src.book_runner.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": []}),
            patch(
                "src.book_runner.chapter_status",
                return_value={
                    "chapter_no": 1,
                    "exists": False,
                    "approved": False,
                    "needs_review": False,
                    "failure": False,
                    "verdict": None,
                    "rewrite_count": 0,
                    "strict_failures": [],
                },
            ),
        ]

    def test_legacy_plan_blocks_readiness_and_write_book(self) -> None:
        data = _strict_plan()
        data.pop("plan_fingerprint")
        data["chapters"][0].pop("chapter_plan_item_fingerprint")
        managers = self._common_patches(data)
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], managers[10]:
            readiness = check_write_readiness(chapters=1)
            self.assertEqual(readiness["status"], "blocked")
            self.assertTrue(any("plan_fingerprint_missing" in item for item in readiness["blockers"]))
            with self.assertRaises(BookRunBlocked):
                run_write_book(chapters=1)

    def test_strict_plan_ready(self) -> None:
        managers = self._common_patches(_strict_plan())
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], managers[10]:
            readiness = check_write_readiness(chapters=1)
        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(readiness["blockers"], [])

    def test_replan_readiness_only_requires_first_window(self) -> None:
        data = _strict_plan(chapters=1)
        managers = self._common_patches(data)
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], managers[10]:
            readiness = check_write_readiness(chapters=3, replan_every=1)
        self.assertNotIn("chapter_plan:chapter_02_plan_missing", readiness["blockers"])
        self.assertEqual(readiness["plan_window"], 1)

    def test_readiness_primary_blocker_for_missing_start_point(self) -> None:
        with patch("src.book_runner.start_point.get_start_chapter_id", return_value=None), patch(
            "src.book_runner._load_raw_chapter_plan", return_value={}
        ), patch("src.book_runner._load_chapter_plan", return_value={}), patch(
            "src.book_runner.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": []}
        ):
            readiness = check_write_readiness(chapters=1)

        self.assertEqual(readiness["next_unapproved_chapter"], 1)
        self.assertEqual(readiness["primary_blocker"]["kind"], "start_point_missing")
        self.assertEqual(readiness["primary_blocker"]["cta_action"], "scroll_to_start_point")

    def test_readiness_next_unapproved_prefers_after_latest_approved(self) -> None:
        def status_for(chapter_no, *_args, **_kwargs):
            if chapter_no == 1:
                return {
                    "chapter_no": 1,
                    "exists": True,
                    "approved": False,
                    "needs_review": True,
                    "failure": False,
                    "verdict": "Reject",
                    "rewrite_count": 2,
                    "strict_failures": ["external_review_reject"],
                }
            if chapter_no == 2:
                return {
                    "chapter_no": 2,
                    "exists": True,
                    "approved": True,
                    "needs_review": False,
                    "failure": False,
                    "verdict": "Approve",
                    "rewrite_count": 0,
                    "strict_failures": [],
                }
            return {
                "chapter_no": chapter_no,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            }

        managers = self._common_patches(_strict_plan(chapters=3))
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], patch(
            "src.book_runner.chapter_status", side_effect=status_for
        ):
            readiness = check_write_readiness(chapters=1, resume_from=1)

        self.assertEqual(readiness["next_unapproved_chapter"], 3)
        self.assertEqual(readiness["primary_blocker"]["kind"], "retry_exhausted")

    def test_readiness_next_unapproved_none_when_plan_done(self) -> None:
        def approved_status(chapter_no, *_args, **_kwargs):
            return {
                "chapter_no": chapter_no,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "rewrite_count": 0,
                "strict_failures": [],
            }

        managers = self._common_patches(_strict_plan(chapters=2))
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], patch(
            "src.book_runner.chapter_status", side_effect=approved_status
        ):
            readiness = check_write_readiness(chapters=1, resume_from=1)

        self.assertIsNone(readiness["next_unapproved_chapter"])
        self.assertIsNone(readiness["primary_blocker"])

    def test_existing_reject_blocks_entry(self) -> None:
        reject_status = {
            "chapter_no": 1,
            "exists": True,
            "approved": False,
            "needs_review": False,
            "failure": False,
            "verdict": "Reject",
            "rewrite_count": 1,
            "strict_failures": ["external_review_reject"],
        }
        managers = self._common_patches(_strict_plan())
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], patch(
            "src.book_runner.chapter_status", return_value=reject_status
        ):
            readiness = check_write_readiness(chapters=1)
            self.assertEqual(readiness["status"], "blocked")
            with self.assertRaises(BookRunBlocked):
                run_write_book(chapters=1)

    def test_budget_exceeded_has_distinct_status(self) -> None:
        managers = self._common_patches(_strict_plan())
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], managers[10], patch(
            "src.book_runner.estimate_cost_since", return_value={"cost_cny": 9.9}
        ), patch("src.book_runner._llm_log_line_count", return_value=0), patch(
            "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
        ):
            result = run_write_book(chapters=1, budget_cny=1.0)
        self.assertEqual(result["status"], "budget_exceeded")

    def test_retry_archives_failed_attempt_before_rewrite(self) -> None:
        statuses = [
            {
                "chapter_no": 1,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 1,
                "exists": True,
                "approved": False,
                "needs_review": True,
                "failure": False,
                "verdict": "Reject",
                "rewrite_count": 1,
                "strict_failures": ["external_review_needs_human"],
            },
            {
                "chapter_no": 1,
                "exists": True,
                "approved": False,
                "needs_review": True,
                "failure": False,
                "verdict": "Reject",
                "rewrite_count": 1,
                "strict_failures": ["external_review_needs_human"],
            },
            {
                "chapter_no": 1,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "rewrite_count": 1,
                "strict_failures": [],
            },
        ]
        managers = self._common_patches(_strict_plan())
        with managers[0], managers[1], managers[2], managers[3], managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], patch(
            "src.book_runner.chapter_status", side_effect=statuses
        ), patch("src.book_runner.write_chapters", return_value=[]), patch(
            "src.book_runner.review_target", return_value=None
        ), patch("src.book_runner._archive_chapter_artifacts", return_value=Path("archive")) as archive, patch(
            "src.book_runner.prune_from_chapter", return_value=None
        ), patch(
            "src.book_runner._auto_apply_advances", return_value={"applied_count": 0}
        ), patch(
            "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
        ):
            result = run_write_book(chapters=1, max_retries=1)
        self.assertEqual(result["status"], "succeeded")
        archive.assert_called_once()

    def test_replan_uses_run_offset_and_reloads_plan(self) -> None:
        data = _strict_plan(chapters=3)
        data_after_replan = _strict_plan(chapters=4)
        parsed = {
            int(item["chapter_no"]): dict(item)
            for item in data.get("chapters", [])
            if isinstance(item, dict) and item.get("chapter_no") is not None
        }
        parsed_after_replan = {
            int(item["chapter_no"]): dict(item)
            for item in data_after_replan.get("chapters", [])
            if isinstance(item, dict) and item.get("chapter_no") is not None
        }
        statuses = [
            {
                "chapter_no": 2,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 3,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 2,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 2,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 3,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 3,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 4,
                "exists": False,
                "approved": False,
                "needs_review": False,
                "failure": False,
                "verdict": None,
                "rewrite_count": 0,
                "strict_failures": [],
            },
            {
                "chapter_no": 4,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "rewrite_count": 0,
                "strict_failures": [],
            },
        ]
        managers = self._common_patches(data)
        with managers[0], managers[1], managers[2], patch(
            "src.book_runner._load_chapter_plan",
            side_effect=[parsed, parsed, parsed_after_replan],
        ) as load_plan, managers[4], managers[5], managers[6], managers[7], managers[8], managers[9], patch(
            "src.book_runner.chapter_status", side_effect=statuses
        ), patch("src.book_runner.write_chapters", return_value=[]), patch(
            "src.book_runner.review_target", return_value=None
        ), patch(
            "src.book_runner._auto_apply_advances", return_value={"applied_count": 0}
        ), patch(
            "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
        ), patch(
            "src.plot_planner.generate_chapter_plan", return_value=data
        ) as replan:
            result = run_write_book(chapters=3, resume_from=2, replan_every=2)
        self.assertEqual(result["status"], "succeeded")
        replan.assert_called_once()
        self.assertEqual(replan.call_args.kwargs["from_chapter"], 3)
        self.assertGreaterEqual(load_plan.call_count, 2)

    def test_archive_moves_entity_advance_proposals_file(self) -> None:
        drafts = self.root / "outputs" / "drafts"
        reviews = self.root / "outputs" / "reviews"
        reviews.mkdir(parents=True, exist_ok=True)
        for suffix in (".md", ".meta.json", ".failure.json", ".entity_advance_proposals.json"):
            (drafts / f"chapter_01{suffix}").write_text("x", encoding="utf-8")
        (reviews / "chapter_01.review.json").write_text("{}", encoding="utf-8")

        archive = _archive_chapter_artifacts(drafts, 1, reason="unit")

        self.assertFalse((drafts / "chapter_01.entity_advance_proposals.json").exists())
        self.assertTrue((archive / "chapter_01.entity_advance_proposals.json").exists())
        self.assertTrue((archive / "chapter_01.review.json").exists())

    def test_auto_apply_advance_missing_relationship_skips_not_fails(self) -> None:
        # Regression: a proposal referencing a relationship absent from the
        # graph (the real-model ``ent_wuliang_east <-> ent_wuliang_west`` ch4
        # case) must be SKIPPED while the remaining valid proposals still
        # apply — not abort the whole auto-apply batch. Pre-fix the stale row
        # raised ValueError, which surfaced as no_op_reason="apply_advance_failed"
        # with applied_count=0 and the entity graph left un-advanced.
        drafts = self.root / "outputs" / "drafts"
        graph_path = self.root / "data" / "entity_graph.json"
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        graph_path.write_text(
            '{"relationships":[{"src_id":"c","dst_id":"d","timeline":[{"state":"old","active":true}]}]}',
            encoding="utf-8",
        )
        # First proposal points at a relationship the graph never had; second
        # is a valid advance for the existing c<->d edge.
        (drafts / "chapter_01.entity_advance_proposals.json").write_text(
            (
                '{"proposed_advances":['
                '{"src_id":"a","dst_id":"b","new_state":"new_ab",'
                '"trigger_event":"evt","confidence":0.95},'
                '{"src_id":"c","dst_id":"d","new_state":"new_cd",'
                '"trigger_event":"evt","confidence":0.95}]}'
            ),
            encoding="utf-8",
        )

        with patch("src.book_runner.paths.workspace_name", return_value="unit"), patch(
            "src.book_runner.paths.drafts_dir", return_value=drafts
        ), patch("src.book_runner.paths.entity_graph_path", return_value=graph_path), patch(
            "src.book_runner._load_raw_chapter_plan", return_value={}
        ):
            result = _auto_apply_advances(1, min_confidence=0.7)

        # The valid c<->d advance applied; the stale a<->b row was skipped and
        # the batch did NOT degrade to apply_advance_failed.
        self.assertEqual(result["applied_count"], 1)
        self.assertEqual(result["selected"], [0, 1])
        self.assertIsNone(result.get("no_op_reason"))
        self.assertNotIn("error", result)
        skipped = result.get("skipped") or []
        self.assertEqual(len(skipped), 1)
        self.assertEqual({skipped[0]["src_id"], skipped[0]["dst_id"]}, {"a", "b"})
        self.assertEqual(skipped[0]["reason"], "relationship_not_found")

        # Graph actually advanced for c<->d; the unknown a<->b was not injected.
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        self.assertEqual(len(graph["relationships"]), 1)
        cd_timeline = graph["relationships"][0]["timeline"]
        self.assertFalse(cd_timeline[0]["active"])
        self.assertEqual(cd_timeline[-1]["state"], "new_cd")
        self.assertTrue(cd_timeline[-1]["active"])


if __name__ == "__main__":
    unittest.main()
