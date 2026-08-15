"""iter 036: workspace type metadata."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cli_workspace import init_workspace
from src.web import workspace_meta


class WorkspaceMetaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        self._tmp.cleanup()


    def test_missing_workspace_json_defaults_to_legacy_novel(self) -> None:
        (paths.WORKSPACE_DIR / "old" / "data").mkdir(parents=True)
        meta = workspace_meta.read("old")
        self.assertEqual(
            meta,
            {
                "type": "novel",
                "created_at": None,
                "schema_version": 0,
                "creation_mode": "continuation",
                "_metadata_status": "legacy",
            },
        )

    def test_non_dict_workspace_json_defaults_to_novel(self) -> None:
        path = paths.WORKSPACE_DIR / "bad" / "data" / "workspace.json"
        path.parent.mkdir(parents=True)
        path.write_text('"not an object"', encoding="utf-8")
        meta = workspace_meta.read("bad")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["schema_version"], 0)

    def test_unknown_workspace_type_is_treated_as_novel(self) -> None:
        path = paths.WORKSPACE_DIR / "unknown" / "data" / "workspace.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"type":"unknown","schema_version":1}', encoding="utf-8")
        meta = workspace_meta.read("unknown")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["schema_version"], 1)



    def test_init_workspace_defaults_to_novel_type(self) -> None:
        init_workspace("novel_box")
        meta = workspace_meta.read("novel_box")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["creation_mode"], "continuation")
        self.assertEqual(meta["schema_version"], 2)

    def test_greenfield_round_trip(self) -> None:
        init_workspace("green", creation_mode="greenfield")
        meta = workspace_meta.read("green")
        self.assertEqual(meta["creation_mode"], "greenfield")
        raw = workspace_meta.workspace_meta_path("green").read_text(encoding="utf-8")
        self.assertIn('"creation_mode": "greenfield"', raw)

    def test_legacy_seed_only_is_greenfield_without_mutating_metadata(self) -> None:
        raw = paths.WORKSPACE_DIR / "seeded" / "小说txt"
        data = paths.WORKSPACE_DIR / "seeded" / "data"
        raw.mkdir(parents=True)
        data.mkdir()
        (raw / "seed.txt").write_text("placeholder", encoding="utf-8")
        before = (raw / "seed.txt").stat().st_mtime_ns
        self.assertEqual(workspace_meta.read("seeded")["creation_mode"], "greenfield")
        self.assertFalse(workspace_meta.workspace_meta_path("seeded").exists())
        self.assertEqual((raw / "seed.txt").stat().st_mtime_ns, before)

    def test_legacy_ambiguous_or_uploaded_shapes_are_continuation(self) -> None:
        for name, entries in (
            ("empty", ()),
            ("uploaded", ("upload.txt",)),
            ("both", ("seed.txt", "upload.txt")),
        ):
            raw = paths.WORKSPACE_DIR / name / "小说txt"
            raw.mkdir(parents=True)
            for entry in entries:
                (raw / entry).write_text("placeholder", encoding="utf-8")
            self.assertEqual(
                workspace_meta.read(name)["creation_mode"],
                "continuation",
                name,
            )

    def test_legacy_symlink_entries_fail_closed_to_continuation(self) -> None:
        outside = paths.WORKSPACE_DIR / "outside.txt"
        outside.write_text("placeholder", encoding="utf-8")
        for name, entry in (("seed-link", "seed.txt"), ("upload-link", "upload.txt")):
            raw = paths.WORKSPACE_DIR / name / "小说txt"
            raw.mkdir(parents=True)
            if entry == "seed.txt":
                os.symlink(outside, raw / entry)
            else:
                (raw / "seed.txt").write_text("placeholder", encoding="utf-8")
                os.symlink(outside, raw / entry)
            self.assertEqual(workspace_meta.read(name)["creation_mode"], "continuation")

    def test_v2_missing_or_invalid_mode_fails_closed_without_legacy_inference(self) -> None:
        raw = paths.WORKSPACE_DIR / "invalid-v2" / "小说txt"
        raw.mkdir(parents=True)
        (raw / "seed.txt").write_text("placeholder", encoding="utf-8")
        meta_path = workspace_meta.workspace_meta_path("invalid-v2")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            '{"type":"novel","schema_version":2,"creation_mode":"other"}',
            encoding="utf-8",
        )
        before = meta_path.read_bytes()
        self.assertEqual(workspace_meta.read("invalid-v2")["creation_mode"], "continuation")
        self.assertEqual(meta_path.read_bytes(), before)



    def test_non_utf8_workspace_json_falls_back_to_novel(self) -> None:
        path = workspace_meta.workspace_meta_path("bad_utf8")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00")
        meta = workspace_meta.read("bad_utf8")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["schema_version"], 0)
        self.assertEqual(meta["creation_mode"], "continuation")

    def test_existing_bad_metadata_never_uses_seed_legacy_inference(self) -> None:
        for name, payload in (
            ("bad-with-seed", b"{"),
            ("list-with-seed", b"[]"),
        ):
            raw = paths.WORKSPACE_DIR / name / "小说txt"
            raw.mkdir(parents=True)
            (raw / "seed.txt").write_text("placeholder", encoding="utf-8")
            meta_path = workspace_meta.workspace_meta_path(name)
            meta_path.parent.mkdir(parents=True)
            meta_path.write_bytes(payload)
            self.assertEqual(workspace_meta.read(name)["creation_mode"], "continuation")

    def test_v1_ignores_creation_mode_field_and_uses_layout(self) -> None:
        raw = paths.WORKSPACE_DIR / "v1-upload" / "小说txt"
        raw.mkdir(parents=True)
        (raw / "upload.txt").write_text("placeholder", encoding="utf-8")
        meta_path = workspace_meta.workspace_meta_path("v1-upload")
        meta_path.parent.mkdir(parents=True)
        meta_path.write_text(
            '{"type":"novel","schema_version":1,"creation_mode":"greenfield"}',
            encoding="utf-8",
        )
        self.assertEqual(workspace_meta.read("v1-upload")["creation_mode"], "continuation")

    def test_metadata_symlink_and_oversize_fail_closed(self) -> None:
        outside = paths.WORKSPACE_DIR / "outside-meta.json"
        outside.write_text(
            '{"type":"novel","schema_version":2,"creation_mode":"greenfield"}',
            encoding="utf-8",
        )
        link = workspace_meta.workspace_meta_path("meta-link")
        link.parent.mkdir(parents=True)
        os.symlink(outside, link)
        self.assertEqual(workspace_meta.read("meta-link")["creation_mode"], "continuation")

        large = workspace_meta.workspace_meta_path("meta-large")
        large.parent.mkdir(parents=True)
        large.write_bytes(b" " * (64 * 1024 + 1))
        self.assertEqual(workspace_meta.read("meta-large")["creation_mode"], "continuation")


if __name__ == "__main__":
    unittest.main()
