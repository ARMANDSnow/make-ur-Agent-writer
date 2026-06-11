"""Iter 021: tests for src/start_point.py.

Covers:
* get_start_chapter_id round-trip with set/clear
* is_after_start strict ordering (start itself returns False)
* chapters_before_start window math
* load_chapter_text reads source_file by line range
* set_start_point accepts both chapter_id and volume_id
* unknown name → ValueError
* All functions degrade gracefully when no start set
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class StartPointTests(unittest.TestCase):
    def setUp(self) -> None:
        # Build a self-contained workspace under a tempdir so we can mutate
        # start_chapter.json + chapter_manifest without polluting any real
        # book workspace.
        self.tmpdir = tempfile.mkdtemp(prefix="iter021_start_point_")
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter021test"
        # Build workspace tree: workspaces/iter021test/data/...
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter021test"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "小说txt").mkdir(parents=True, exist_ok=True)

        # Synthesise 5 chapters across 2 volumes
        source_path = self.ws_root / "小说txt" / "iter021test_v1.txt"
        source_path.write_text(
            "\n".join(f"line {i}" for i in range(1, 31)) + "\n", encoding="utf-8"
        )
        source_v2 = self.ws_root / "小说txt" / "iter021test_v2.txt"
        source_v2.write_text(
            "\n".join(f"v2 line {i}" for i in range(1, 21)) + "\n", encoding="utf-8"
        )

        manifest = [
            {"chapter_id": "v1_ch001", "volume_id": "v1",
             "source_file": str(source_path), "title": "first",
             "start_line": 1, "end_line": 5, "char_count": 30},
            {"chapter_id": "v1_ch002", "volume_id": "v1",
             "source_file": str(source_path), "title": "second",
             "start_line": 6, "end_line": 10, "char_count": 30},
            {"chapter_id": "v1_ch003", "volume_id": "v1",
             "source_file": str(source_path), "title": "third",
             "start_line": 11, "end_line": 15, "char_count": 30},
            {"chapter_id": "v2_ch001", "volume_id": "v2",
             "source_file": str(source_v2), "title": "v2-first",
             "start_line": 1, "end_line": 5, "char_count": 30},
            {"chapter_id": "v2_ch002", "volume_id": "v2",
             "source_file": str(source_v2), "title": "v2-second",
             "start_line": 6, "end_line": 10, "char_count": 30},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        from src import start_point
        self.start_point = start_point

    def tearDown(self) -> None:
        # Remove temp workspace tree
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_no_start_returns_none(self) -> None:
        self.assertIsNone(self.start_point.get_start_chapter_id())
        self.assertFalse(self.start_point.is_after_start("v1_ch003"))
        self.assertEqual(self.start_point.chapters_before_start(3), [])

    def test_set_chapter_id_round_trip(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        self.assertEqual(self.start_point.get_start_chapter_id(), "v1_ch003")

    def test_set_volume_id_resolves_to_last_chapter(self) -> None:
        self.start_point.set_start_point("v1")
        # Should resolve to v1_ch003 (last chapter of v1)
        self.assertEqual(self.start_point.get_start_chapter_id(), "v1_ch003")

    def test_unknown_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.start_point.set_start_point("bogus_id")

    def test_is_after_start_is_strict(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        # Start itself is NOT after start
        self.assertFalse(self.start_point.is_after_start("v1_ch003"))
        # Before start
        self.assertFalse(self.start_point.is_after_start("v1_ch001"))
        # After start
        self.assertTrue(self.start_point.is_after_start("v2_ch001"))
        # Unknown chapter id → False
        self.assertFalse(self.start_point.is_after_start("nonexistent"))

    def test_chapters_before_start_and_load_text(self) -> None:
        self.start_point.set_start_point("v2_ch001")
        before = self.start_point.chapters_before_start(3)
        self.assertEqual([c["chapter_id"] for c in before],
                         ["v1_ch001", "v1_ch002", "v1_ch003"])
        # load_chapter_text reads source_file by line range
        body = self.start_point.load_chapter_text("v1_ch001")
        # 5 lines from "line 1" to "line 5"
        self.assertIn("line 1\n", body)
        self.assertIn("line 5\n", body)
        # Line 6 (next chapter) should NOT appear
        self.assertNotIn("line 6\n", body)

    def test_clear_restores_default(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        self.assertIsNotNone(self.start_point.get_start_chapter_id())
        self.start_point.clear_start_point()
        self.assertIsNone(self.start_point.get_start_chapter_id())
        # idempotent — second clear doesn't raise
        self.start_point.clear_start_point()

    def test_start_point_fingerprint_is_stable_and_manifest_sensitive(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        first = self.start_point.start_point_fingerprint()
        self.assertEqual(first, self.start_point.start_point_fingerprint())
        manifest_path = self.ws_root / "data" / "chapter_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest[2]["title"] = "third revised"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        self.assertNotEqual(first, self.start_point.start_point_fingerprint())


class EnforceConsistencyTests(unittest.TestCase):
    """iter 051b (F6, carry-over from the iter 027 code review): behavior
    matrix for the centralized start-point consistency gate, plus proof that
    the historical call sites (plot_planner presence/append gates,
    book_runner._plan_metadata_failures) route through this one function
    instead of re-implementing the checks inline."""

    def setUp(self) -> None:
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter051btest"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter051btest"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        manifest = [
            {"chapter_id": "b1_ch001", "volume_id": "b1", "source_file": "",
             "title": "one", "start_line": 1, "end_line": 2, "char_count": 10},
            {"chapter_id": "b1_ch002", "volume_id": "b1", "source_file": "",
             "title": "two", "start_line": 3, "end_line": 4, "char_count": 10},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        from src import start_point

        self.start_point = start_point

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env

    # ---- presence mode (plan_data=None) -------------------------------------

    def test_missing_start_blocks_when_required(self) -> None:
        self.assertEqual(
            self.start_point.enforce_consistency(require_start_point=True),
            ["start_point_missing"],
        )

    def test_gate_off_when_not_required(self) -> None:
        self.assertEqual(
            self.start_point.enforce_consistency(require_start_point=False), []
        )

    def test_present_start_passes(self) -> None:
        self.start_point.set_start_point("b1_ch001")
        self.assertEqual(
            self.start_point.enforce_consistency(require_start_point=True), []
        )

    # ---- plan-agreement mode (plan_data given) -------------------------------

    def test_matching_plan_passes(self) -> None:
        self.start_point.set_start_point("b1_ch001")
        plan = {
            "start_chapter_id": "b1_ch001",
            "start_point_fingerprint": self.start_point.start_point_fingerprint(),
        }
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=True, plan_data=plan
            ),
            [],
        )

    def test_plan_missing_fields(self) -> None:
        self.start_point.set_start_point("b1_ch001")
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=True, plan_data={}
            ),
            ["start_chapter_id_missing", "start_point_fingerprint_missing"],
        )

    def test_plan_id_mismatch(self) -> None:
        self.start_point.set_start_point("b1_ch001")
        plan = {
            "start_chapter_id": "b1_ch002",
            "start_point_fingerprint": self.start_point.start_point_fingerprint(),
        }
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=True, plan_data=plan
            ),
            ["start_chapter_id_mismatch"],
        )

    def test_plan_fingerprint_mismatch(self) -> None:
        self.start_point.set_start_point("b1_ch001")
        plan = {"start_chapter_id": "b1_ch001", "start_point_fingerprint": "stale"}
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=True, plan_data=plan
            ),
            ["start_point_fingerprint_mismatch"],
        )

    def test_plan_mode_fails_open_without_current_start(self) -> None:
        # No workspace start point → a stored plan id/fp can't contradict it
        # (mismatch needs both sides) — byte-identical to the pre-051b inline
        # block in book_runner._plan_metadata_failures.
        plan = {"start_chapter_id": "b1_ch002", "start_point_fingerprint": "anything"}
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=True, plan_data=plan
            ),
            [],
        )

    def test_plan_mode_never_emits_start_point_missing(self) -> None:
        codes = self.start_point.enforce_consistency(
            require_start_point=True, plan_data={}
        )
        self.assertNotIn("start_point_missing", codes)

    def test_not_required_skips_plan_checks_too(self) -> None:
        self.assertEqual(
            self.start_point.enforce_consistency(
                require_start_point=False, plan_data={}
            ),
            [],
        )

    # ---- call-site unity ------------------------------------------------------

    def test_book_runner_plan_metadata_routes_through_gate(self) -> None:
        from src import book_runner

        data = {"plan_fingerprint": "x", "chapters": []}
        with patch(
            "src.start_point.enforce_consistency",
            return_value=["start_point_fingerprint_mismatch"],
        ) as gate:
            failures = book_runner._plan_metadata_failures(
                data, chapter_numbers=[], require_start_point=True
            )
        self.assertIn("start_point_fingerprint_mismatch", failures)
        gate.assert_called_once_with(require_start_point=True, plan_data=data)

    def test_plot_planner_presence_gate_routes_through_gate(self) -> None:
        from src import paths, plot_planner

        outline = paths.outline_path()
        outline.parent.mkdir(parents=True, exist_ok=True)
        outline.write_text("# outline", encoding="utf-8")
        with patch(
            "src.start_point.enforce_consistency",
            return_value=["start_point_missing"],
        ) as gate:
            with self.assertRaises(ValueError) as ctx:
                plot_planner.generate_chapter_plan(
                    target_chapters=3, require_start_point=True
                )
        self.assertIn("start point is required", str(ctx.exception))
        gate.assert_called_once_with(require_start_point=True)

    def test_plot_planner_append_mismatch_via_gate_end_to_end(self) -> None:
        # No patching here: the real centralized gate must surface the
        # historical append-mode error verbatim.
        from src import paths, plot_planner

        self.start_point.set_start_point("b1_ch001")
        outline = paths.outline_path()
        outline.parent.mkdir(parents=True, exist_ok=True)
        outline.write_text("# outline", encoding="utf-8")
        plan_path = paths.chapter_plan_path()
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {"start_chapter_id": "b1_ch002", "chapters": [{"chapter_no": 1}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as ctx:
            plot_planner.generate_chapter_plan(
                append_count=1, from_chapter=1, require_start_point=True
            )
        self.assertIn("does not match", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
