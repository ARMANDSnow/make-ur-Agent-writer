"""Iteration 095 season master/snapshot export contracts."""

from __future__ import annotations

import io
import json
import zipfile
from unittest import mock

from src import character_designer, drama_multimodal_smoke as multi, drama_reviewer, drama_season_export, drama_store, paths, storyboard_builder
from src.drama_schemas import character_paths, episode_paths
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaSeasonExportTests(DramaTestBase):
    def _assembled_episode_one(
        self,
        name: str = "season",
        *,
        episode_count: int = 1,
        reference_path: str | None = None,
        reference_bytes: bytes | None = None,
    ) -> None:
        self._make_drama_workspace(name, "霸总", episode_count=episode_count)
        self._write_setup(name, hook=True)
        write_json(episode_paths(name).storyboard_path, storyboard_builder.run(name, mock=True))
        sheet = character_designer.run(name, mock=True)
        if reference_path:
            sheet["characters"][0]["reference_images"] = [{"path": reference_path}]
            if reference_bytes is not None:
                reference_file = paths.WORKSPACE_DIR / name / reference_path
                reference_file.parent.mkdir(parents=True, exist_ok=True)
                reference_file.write_bytes(reference_bytes)
        write_json(character_paths(name).sheet_path, sheet)
        write_json(episode_paths(name).review_path, drama_reviewer.run(name, mock=True))
        drama_store.assemble_episode(name)

    def test_master_contains_manifest_four_exports_and_characters(self) -> None:
        self._assembled_episode_one()
        state = drama_season_export.public_season_export_readiness("season")
        self.assertTrue(state["master_ready"])
        self.assertTrue(state["snapshot_ready"])

        artifact = drama_season_export.export_season("season", mode="master")
        self.assertEqual(artifact.filename, "season_01_master.zip")
        self.assertEqual(artifact.content_type, "application/zip")
        self.assertEqual(artifact.path.read_bytes(), artifact.body)
        with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(
                names,
                [
                    "characters/season_01.json",
                    "episodes/episode_01.comfy.json",
                    "episodes/episode_01.json",
                    "episodes/episode_01.storyboard.csv",
                    "episodes/episode_01.storyboard.md",
                    "manifest.json",
                ],
            )
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["mode"], "master")
        self.assertEqual(manifest["included_episode_nos"], [1])
        self.assertEqual(manifest["excluded"], [])
        self.assertFalse(any("setup" in name or "review" in name or "hooks" in name for name in names))

    def test_snapshot_filters_missing_planned_episode_and_is_deterministic(self) -> None:
        self._assembled_episode_one(episode_count=2)
        state = drama_season_export.public_season_export_readiness("season")
        self.assertFalse(state["master_ready"])
        self.assertTrue(state["snapshot_ready"])
        self.assertEqual(state["excluded"], [{"episode_no": 2, "reason": "incomplete"}])
        with self.assertRaisesRegex(drama_season_export.SeasonExportConflict, "all planned"):
            drama_season_export.export_season("season", mode="master")

        first = drama_season_export.export_season("season", mode="snapshot")
        second = drama_season_export.export_season("season", mode="snapshot")
        self.assertEqual(first.body, second.body)
        self.assertEqual(first.filename, "season_01_snapshot.zip")
        self.assertEqual(first.manifest["excluded"], [{"episode_no": 2, "reason": "incomplete"}])
        self.assertFalse(list(first.path.parent.glob("*.tmp.*")))

    def test_tampered_episode_is_excluded_as_stale(self) -> None:
        self._assembled_episode_one()
        ep = episode_paths("season")
        payload = json.loads(ep.episode_path.read_text(encoding="utf-8"))
        payload["title"] = "篡改后的标题"
        write_json(ep.episode_path, payload)

        state = drama_season_export.public_season_export_readiness("season")
        self.assertEqual(state["excluded"], [{"episode_no": 1, "reason": "stale"}])
        self.assertFalse(state["master_ready"])
        self.assertFalse(state["snapshot_ready"])
        with self.assertRaisesRegex(drama_season_export.SeasonExportConflict, "at least one"):
            drama_season_export.export_season("season", mode="snapshot")

    def test_missing_reference_blocks_master_but_snapshot_records_it(self) -> None:
        rel = "data/character_refs/c001/missing.png"
        self._assembled_episode_one(reference_path=rel)
        state = drama_season_export.public_season_export_readiness("season")
        self.assertEqual(state["missing_reference_images"], [rel])
        self.assertFalse(state["master_ready"])
        self.assertTrue(state["snapshot_ready"])
        with self.assertRaisesRegex(drama_season_export.SeasonExportConflict, "all planned"):
            drama_season_export.export_season("season", mode="master")

        artifact = drama_season_export.export_season("season", mode="snapshot")
        self.assertEqual(artifact.manifest["missing_reference_images"], [rel])
        with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
            self.assertFalse(any(name.startswith("character_refs/") for name in archive.namelist()))

    def test_reference_symlink_fails_closed_for_both_modes(self) -> None:
        rel = "data/character_refs/c001/ref.png"
        self._assembled_episode_one(reference_path=rel)
        target = paths.WORKSPACE_DIR / "season" / "data" / "target.png"
        target.write_bytes(b"png")
        link = paths.WORKSPACE_DIR / "season" / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        state = drama_season_export.public_season_export_readiness("season")
        self.assertIn("reference_symlink_or_unreadable", state["asset_errors"])
        for mode in ("master", "snapshot"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(drama_season_export.SeasonExportConflict, "invalid"):
                    drama_season_export.export_season("season", mode=mode)

    def test_valid_reference_is_included_and_hashed(self) -> None:
        rel = "data/character_refs/c001/ref.png"
        self._assembled_episode_one(reference_path=rel, reference_bytes=multi._PNG_1X1)
        artifact = drama_season_export.export_season("season", mode="master")
        with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
            member = "character_refs/c001/ref.png"
            self.assertEqual(archive.read(member), multi._PNG_1X1)
        record = next(row for row in artifact.manifest["files"] if row["path"] == member)
        self.assertEqual(record["size"], len(multi._PNG_1X1))
        self.assertEqual(len(record["sha256"]), 64)

    def test_failed_rebuild_does_not_overwrite_previous_master(self) -> None:
        self._assembled_episode_one()
        first = drama_season_export.export_season("season", mode="master")
        before = first.path.read_bytes()
        wizard = paths.WORKSPACE_DIR / "season" / "data" / "wizard_input.json"
        payload = json.loads(wizard.read_text(encoding="utf-8"))
        payload["episode_count"] = 2
        write_json(wizard, payload)
        with self.assertRaises(drama_season_export.SeasonExportConflict):
            drama_season_export.export_season("season", mode="master")
        self.assertEqual(first.path.read_bytes(), before)

    def test_package_normalizes_episode_json_and_projects_character_secrets(self) -> None:
        rel = "data/character_refs/c001/ref.png"
        self._assembled_episode_one(reference_path=rel, reference_bytes=multi._PNG_1X1)
        sheet_path = character_paths("season").sheet_path
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        row = sheet["characters"][0]
        row["manual_override"] = True
        row["agent_suggestions"] = [{"secret": "REVIEW_SECRET_SENTINEL"}]
        row["reference_images"][0].update(
            {
                "prompt": "REFERENCE_PROMPT_SENTINEL",
                "generated_by": "internal-provider",
                "requested_model": "secret/model",
                "provider_size": "internal-size",
            }
        )
        sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        # Refresh the v2 fingerprint after the intentional pre-export edit.
        drama_store.assemble_episode("season")
        ep = episode_paths("season")
        episode = json.loads(ep.episode_path.read_text(encoding="utf-8"))
        episode["secret_extra"] = "EPISODE_SECRET_SENTINEL"
        ep.episode_path.write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")

        artifact = drama_season_export.export_season("season", mode="master")
        with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
            packaged_episode = json.loads(archive.read("episodes/episode_01.json"))
            packaged_characters = json.loads(archive.read("characters/season_01.json"))
        self.assertNotIn("secret_extra", packaged_episode)
        encoded = json.dumps(packaged_characters, ensure_ascii=False)
        for sentinel in (
            "REVIEW_SECRET_SENTINEL",
            "REFERENCE_PROMPT_SENTINEL",
            "internal-provider",
            "secret/model",
            "internal-size",
        ):
            self.assertNotIn(sentinel, encoded)
        public_row = packaged_characters["characters"][0]
        self.assertNotIn("manual_override", public_row)
        self.assertNotIn("agent_suggestions", public_row)
        self.assertNotIn("prompt_template_sd", public_row)

    def test_export_parent_symlink_is_rejected(self) -> None:
        self._assembled_episode_one()
        outside = paths.WORKSPACE_DIR / "outside"
        outside.mkdir()
        export_dir = episode_paths("season").outputs_dir / "exports"
        export_dir.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(
            drama_season_export.SeasonExportConflict,
            "unsafe",
        ):
            drama_season_export.export_season("season", mode="master")
        self.assertFalse((outside / "season_01_master.zip").exists())

    def test_episode_source_symlink_is_not_followed(self) -> None:
        self._assembled_episode_one()
        ep = episode_paths("season")
        outside = paths.WORKSPACE_DIR / "outside-episode.json"
        outside.write_text(ep.episode_path.read_text(encoding="utf-8"), encoding="utf-8")
        ep.episode_path.unlink()
        ep.episode_path.symlink_to(outside)
        state = drama_season_export.public_season_export_readiness("season")
        self.assertEqual(state["excluded"], [{"episode_no": 1, "reason": "incomplete"}])
        self.assertFalse(state["snapshot_ready"])

    def test_member_budget_fails_before_writing_package(self) -> None:
        self._assembled_episode_one()
        target = episode_paths("season").outputs_dir / "exports" / "season_01_master.zip"
        with mock.patch.object(drama_season_export, "MAX_SEASON_PACKAGE_BYTES", 128):
            with self.assertRaisesRegex(
                drama_season_export.SeasonExportConflict,
                "size limit",
            ):
                drama_season_export.export_season("season", mode="master")
        self.assertFalse(target.exists())

    def test_invalid_mode_season_and_wizard_count_are_rejected(self) -> None:
        self._assembled_episode_one()
        with self.assertRaisesRegex(ValueError, "mode must be"):
            drama_season_export.export_season("season", mode="../../")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "season_no must be 1"):
            drama_season_export.export_season("season", season_no=2, mode="master")
        wizard = paths.WORKSPACE_DIR / "season" / "data" / "wizard_input.json"
        payload = json.loads(wizard.read_text(encoding="utf-8"))
        payload["episode_count"] = "1"
        write_json(wizard, payload)
        with self.assertRaisesRegex(ValueError, "episode_count is invalid"):
            drama_season_export.public_season_export_readiness("season")


if __name__ == "__main__":
    import unittest

    unittest.main()
