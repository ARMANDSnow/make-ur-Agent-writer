"""iter106: strict RenderPlan store and stale-boundary tests."""

from __future__ import annotations

import json
import socket
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.utils import read_json, write_json
from tests._drama_base import DramaTestBase


class DramaRenderStoreTests(DramaTestBase):
    def _assembled(self, name: str = "render-store", *, episode_no: int = 1) -> None:
        if episode_no == 1:
            self._make_drama_workspace(name, "霸总", episode_count=2)
            self._write_setup(name, hook=True)
            write_json(
                episode_paths(name).storyboard_path,
                storyboard_builder.run(name, mock=True),
            )
            write_json(
                character_paths(name).sheet_path,
                character_designer.run(name, mock=True),
            )
            write_json(
                episode_paths(name).review_path,
                drama_reviewer.run(name, mock=True),
            )
            drama_store.assemble_episode(name)
            return

        self._assembled(name)
        self._write_setup(name, hook=True, episode_no=episode_no)
        write_json(
            episode_paths(name, episode_no=episode_no).storyboard_path,
            storyboard_builder.run(name, mock=True, episode_no=episode_no),
        )
        sheet_path = character_paths(name).sheet_path
        sheet = read_json(sheet_path)
        sheet["episode_no"] = episode_no
        sheet["generated_episode_nos"] = sorted(
            set(sheet.get("generated_episode_nos", [])) | {episode_no}
        )
        for row in sheet["characters"]:
            row["appearances"] = sorted(set(row.get("appearances", [])) | {episode_no})
        write_json(sheet_path, sheet)
        write_json(
            episode_paths(name, episode_no=episode_no).review_path,
            drama_reviewer.run(name, mock=True, episode_no=episode_no),
        )
        drama_store.assemble_episode(name, episode_no=episode_no)

    def _make_ambiguous_render_source(self, name: str) -> None:
        storyboard_path = episode_paths(name).storyboard_path
        storyboard = read_json(storyboard_path)
        first = storyboard["shots"][0]
        second = storyboard["shots"][1]
        for key in ("beat", "visual", "narration", "dialogue"):
            second[key] = first[key]
        second["duration_seconds"] = (
            first["duration_seconds"] + 1
            if first["duration_seconds"] < 30
            else first["duration_seconds"] - 1
        )
        write_json(storyboard_path, storyboard)
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)

    def test_missing_create_load_and_idempotent_bytes(self) -> None:
        self._assembled()
        self.assertEqual(
            drama_render_store.inspect_render_plan("render-store").state,
            "needs_render_plan",
        )
        first = drama_render_store.create_render_plan("render-store")
        path = drama_render_store.render_plan_path("render-store")
        before = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns
        second = drama_render_store.create_render_plan("render-store")
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)
        self.assertEqual(
            drama_render_store.inspect_render_plan("render-store").state,
            "fresh",
        )
        self.assertEqual(
            drama_render_store.load_fresh_render_plan("render-store"),
            first,
        )

        path.unlink()
        rebuilt = drama_render_store.create_render_plan("render-store")
        self.assertEqual(rebuilt, first)
        self.assertEqual(path.read_bytes(), before)

    def test_episode_two_uses_its_frozen_projection(self) -> None:
        self._assembled("episode-two", episode_no=2)
        plan = drama_render_store.create_render_plan("episode-two", episode_no=2)
        meta = read_json(episode_paths("episode-two", episode_no=2).meta_path)
        self.assertEqual(plan.episode_no, 2)
        self.assertEqual(plan.frozen_character_ids, meta["character_fingerprint_ids"])
        self.assertEqual(
            drama_render_store.inspect_render_plan("episode-two", episode_no=2).state,
            "fresh",
        )

    def test_v2_plan_preserves_meta_cast_order_after_season_rows_reorder(self) -> None:
        name = "cast-order"
        self._assembled(name)
        sheet_path = character_paths(name).sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"].reverse()
        write_json(sheet_path, sheet)
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)

        meta_ids = read_json(episode_paths(name).meta_path)["character_fingerprint_ids"]
        snapshot = drama_store.load_fresh_episode_for_render(name)
        projection_ids = [
            row["id"] for row in snapshot.character_projection["characters"]
        ]
        self.assertNotEqual(projection_ids, meta_ids)
        self.assertEqual(list(snapshot.frozen_character_ids), meta_ids)
        self.assertEqual(
            drama_render_store.create_render_plan(name).frozen_character_ids,
            meta_ids,
        )

    def test_unassembled_drift_blocks_then_reassembly_makes_plan_stale(self) -> None:
        self._assembled("stale")
        original = drama_render_store.create_render_plan("stale")
        path = drama_render_store.render_plan_path("stale")
        before = path.read_bytes()

        storyboard_path = episode_paths("stale").storyboard_path
        storyboard = read_json(storyboard_path)
        storyboard["title"] = "新的创作版本"
        write_json(storyboard_path, storyboard)
        blocked = drama_render_store.inspect_render_plan("stale")
        self.assertEqual(blocked.state, "blocked_source")
        self.assertEqual(path.read_bytes(), before)

        write_json(
            episode_paths("stale").review_path,
            drama_reviewer.run("stale", mock=True),
        )
        drama_store.assemble_episode("stale")
        stale = drama_render_store.inspect_render_plan("stale")
        self.assertEqual(stale.state, "stale")
        with self.assertRaisesRegex(
            drama_render_store.RenderPlanStoreError,
            "explicit replacement",
        ):
            drama_render_store.create_render_plan("stale")
        self.assertEqual(path.read_bytes(), before)

        replaced = drama_render_store.create_render_plan("stale", replace_stale=True)
        self.assertNotEqual(replaced.plan_fingerprint, original.plan_fingerprint)
        self.assertEqual(
            drama_render_store.inspect_render_plan("stale").state,
            "fresh",
        )

    def test_invalid_artifacts_are_classified_and_never_overwritten(self) -> None:
        self._assembled("invalid")
        drama_render_store.create_render_plan("invalid")
        path = drama_render_store.render_plan_path("invalid")

        cases = [
            b"{not json",
            b'{"schema_version":1e999}',
            ('{"schema_version":' + "9" * 5000 + "}").encode(),
            ("[" * 1200 + "]" * 1200).encode(),
            json.dumps(
                {
                    "schema_version": 99,
                    "artifact_type": "drama_render_plan",
                    "plan_fingerprint": "0" * 64,
                    "plan": {},
                }
            ).encode(),
        ]
        for payload in cases:
            path.write_bytes(payload)
            before = path.read_bytes()
            self.assertEqual(
                drama_render_store.inspect_render_plan("invalid").state,
                "invalid",
            )
            with self.assertRaises(drama_render_store.RenderPlanStoreError):
                drama_render_store.create_render_plan("invalid", replace_stale=True)
            self.assertEqual(path.read_bytes(), before)

    def test_bad_envelope_hash_and_duplicate_members_are_invalid(self) -> None:
        self._assembled("bad-hash")
        drama_render_store.create_render_plan("bad-hash")
        path = drama_render_store.render_plan_path("bad-hash")
        envelope = read_json(path)
        envelope["plan_fingerprint"] = "0" * 64
        write_json(path, envelope)
        inspection = drama_render_store.inspect_render_plan("bad-hash")
        self.assertEqual(inspection.state, "invalid")
        self.assertEqual(inspection.reasons, ("plan_hash_mismatch",))

        path.write_text(
            '{"schema_version":1,"schema_version":1,"artifact_type":"drama_render_plan",'
            '"plan_fingerprint":"' + "0" * 64 + '","plan":{}}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("bad-hash").state,
            "invalid",
        )

    def test_symlink_non_regular_and_workspace_escape_are_invalid(self) -> None:
        self._assembled("symlink")
        path = drama_render_store.render_plan_path("symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        target = path.parent / "target.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
        self.assertEqual(
            drama_render_store.inspect_render_plan("symlink").state,
            "invalid",
        )
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")

        path.unlink()
        path.mkdir()
        self.assertEqual(
            drama_render_store.inspect_render_plan("symlink").state,
            "invalid",
        )
        with self.assertRaises(ValueError):
            drama_render_store.render_plan_path("../escape")

    def test_missing_or_bad_source_is_blocked_before_write(self) -> None:
        self._make_drama_workspace("blocked", "霸总")
        inspection = drama_render_store.inspect_render_plan("blocked")
        self.assertEqual(inspection.state, "blocked_source")
        with self.assertRaises(drama_render_store.RenderPlanStoreError):
            drama_render_store.create_render_plan("blocked")
        self.assertFalse(drama_render_store.render_plan_path("blocked").exists())

    def test_source_reader_rejects_directory_and_non_finite_or_complex_json(self) -> None:
        self._assembled("source-directory")
        episode_path = episode_paths("source-directory").episode_path
        episode_path.unlink()
        episode_path.mkdir()
        self.assertEqual(
            drama_render_store.inspect_render_plan("source-directory").state,
            "blocked_source",
        )

        self._assembled("source-duplicate")
        duplicate_path = episode_paths("source-duplicate").episode_path
        duplicate_path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("source-duplicate").state,
            "blocked_source",
        )

        self._assembled("source-nan")
        nan_path = episode_paths("source-nan").episode_path
        for payload in (
            '{"schema_version":NaN}',
            '{"schema_version":1e999}',
            '{"schema_version":' + "9" * 5000 + "}",
            "[" * 1200 + "]" * 1200,
        ):
            with self.subTest(payload=payload[:40]):
                nan_path.write_text(payload, encoding="utf-8")
                self.assertEqual(
                    drama_render_store.inspect_render_plan("source-nan").state,
                    "blocked_source",
                )

        self._assembled("source-link")
        setup_path = episode_paths("source-link").setup_path
        target = setup_path.with_name("setup-target.json")
        target.write_bytes(setup_path.read_bytes())
        setup_path.unlink()
        setup_path.symlink_to(target)
        self.assertEqual(
            drama_render_store.inspect_render_plan("source-link").state,
            "blocked_source",
        )

    def test_workspace_root_symlink_is_rejected_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as external:
            linked_root = paths.WORKSPACE_DIR / "linked-root"
            linked_root.symlink_to(external, target_is_directory=True)
            self.assertEqual(
                drama_render_store.inspect_render_plan("linked-root").state,
                "invalid",
            )
            with self.assertRaises(ValueError):
                drama_render_store.create_render_plan("linked-root")
            self.assertEqual(list(Path(external).iterdir()), [])

    def test_replace_stale_requires_a_real_bool(self) -> None:
        self._assembled("strict-bool")
        for value in ("false", 0, 1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "replace_stale must be bool"):
                    drama_render_store.create_render_plan(
                        "strict-bool",
                        replace_stale=value,  # type: ignore[arg-type]
                    )
        self.assertFalse(
            drama_render_store.render_plan_path("strict-bool").exists()
        )

    def test_target_and_source_compare_and_swap_fail_closed(self) -> None:
        self._assembled("target-race")
        with patch.object(
            drama_render_store,
            "_target_token_at",
            return_value=("file", 1, "changed"),
        ):
            with self.assertRaisesRegex(
                drama_render_store.RenderPlanStoreError,
                "changed concurrently",
            ):
                drama_render_store.create_render_plan("target-race")
        self.assertFalse(
            drama_render_store.render_plan_path("target-race").exists()
        )

        self._assembled("source-race")
        snapshot = drama_store.load_fresh_episode_for_render("source-race")
        changed = replace(snapshot, snapshot_fingerprint="0" * 64)
        with patch.object(
            drama_render_store,
            "_source_snapshot",
            side_effect=[snapshot, snapshot, changed],
        ):
            with self.assertRaisesRegex(
                drama_render_store.RenderPlanStoreError,
                "source changed concurrently",
            ):
                drama_render_store.create_render_plan("source-race")
        self.assertFalse(
            drama_render_store.render_plan_path("source-race").exists()
        )

    def test_unrenderable_fresh_source_is_always_blocked(self) -> None:
        self._assembled("ambiguous-missing")
        self._make_ambiguous_render_source("ambiguous-missing")
        self.assertEqual(
            drama_render_store.inspect_render_plan("ambiguous-missing").state,
            "blocked_source",
        )
        with self.assertRaises(drama_render_store.RenderPlanStoreError):
            drama_render_store.create_render_plan("ambiguous-missing")
        self.assertFalse(
            drama_render_store.render_plan_path("ambiguous-missing").exists()
        )

        self._assembled("ambiguous-existing")
        drama_render_store.create_render_plan("ambiguous-existing")
        path = drama_render_store.render_plan_path("ambiguous-existing")
        before = path.read_bytes()
        self._make_ambiguous_render_source("ambiguous-existing")
        self.assertEqual(
            drama_render_store.inspect_render_plan("ambiguous-existing").state,
            "blocked_source",
        )
        with self.assertRaises(drama_render_store.RenderPlanStoreError):
            drama_render_store.create_render_plan(
                "ambiguous-existing",
                replace_stale=True,
            )
        self.assertEqual(path.read_bytes(), before)

    def test_ambiguous_legacy_episode_two_is_blocked_before_write(self) -> None:
        name = "legacy-v1-ambiguous"
        self._assembled(name, episode_no=2)
        sheet_path = character_paths(name).sheet_path
        sheet = read_json(sheet_path)
        for row in sheet["characters"]:
            row["appearances"] = [1]
        write_json(sheet_path, sheet)

        ep = episode_paths(name, episode_no=2)
        meta = read_json(ep.meta_path)
        meta["input_fingerprint_version"] = 1
        meta["character_fingerprint_ids"] = []
        meta["input_fingerprint"] = drama_store.input_fingerprint(
            setup=read_json(ep.setup_path),
            storyboard=read_json(ep.storyboard_path),
            characters=sheet,
            review=read_json(ep.review_path),
            episode_no=2,
            version=1,
        )
        write_json(ep.meta_path, meta)
        self.assertFalse(drama_store.is_episode_stale(name, episode_no=2))
        self.assertEqual(
            drama_render_store.inspect_render_plan(name, episode_no=2).state,
            "blocked_source",
        )
        with self.assertRaises(drama_render_store.RenderPlanStoreError):
            drama_render_store.create_render_plan(name, episode_no=2)
        self.assertFalse(
            drama_render_store.render_plan_path(name, episode_no=2).exists()
        )

    def test_create_and_inspect_are_strictly_offline(self) -> None:
        self._assembled("offline")
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            plan = drama_render_store.create_render_plan("offline")
            inspection = drama_render_store.inspect_render_plan("offline")
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.plan, plan)


if __name__ == "__main__":
    import unittest

    unittest.main()
