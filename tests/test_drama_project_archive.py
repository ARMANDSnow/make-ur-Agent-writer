"""iter148: deterministic portable project archive and safe import."""

from __future__ import annotations

import io
import json
import os
import stat
import zipfile
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_audio,
    drama_project_archive,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.utils import sha256_data, write_json
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from tests._drama_base import DramaTestBase


class DramaProjectArchiveTests(DramaTestBase):
    def _assembled(self, name: str = "archive-source") -> None:
        self._make_drama_workspace(name, episode_count=1)
        self._write_setup(name, hook=True)
        write_json(episode_paths(name).storyboard_path, storyboard_builder.run(name, mock=True))
        write_json(character_paths(name).sheet_path, character_designer.run(name, mock=True))
        write_json(episode_paths(name).review_path, drama_reviewer.run(name, mock=True))
        drama_store.assemble_episode(name)

    @staticmethod
    def _zip_info(name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (0o100644 & 0xFFFF) << 16
        return info

    def test_export_is_deterministic_sanitized_and_strictly_preflighted(self) -> None:
        self._assembled()
        episode_file = episode_paths("archive-source").episode_path
        episode_payload = json.loads(episode_file.read_text(encoding="utf-8"))
        episode_payload["storyboard"][0]["ai_draw_prompt"] = "PROMPT_SENTINEL"
        episode_payload["storyboard"][0]["notes"] = "INNOCENT_KEY_PRIVATE_SENTINEL"
        episode_payload["core_setup"]["notes"] = "INNOCENT_KEY_PRIVATE_SENTINEL"
        write_json(episode_file, episode_payload)
        meta_file = episode_paths("archive-source").meta_path
        meta_payload = json.loads(meta_file.read_text(encoding="utf-8"))
        meta_payload["episode_sha256"] = sha256_data(episode_payload)
        meta_payload["agent_reviews"][0]["issues"] = ["REVIEW_SENTINEL"]
        write_json(meta_file, meta_payload)
        review = episode_paths("archive-source").review_path
        payload = json.loads(review.read_text(encoding="utf-8"))
        payload["internal_secret"] = "sk-secret PROMPT_SENTINEL signed_url"
        review.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        first = drama_project_archive.export_project_archive("archive-source")
        second = drama_project_archive.export_project_archive("archive-source")
        self.assertEqual(first.body, second.body)
        self.assertEqual(first.path.read_bytes(), first.body)
        manifest = drama_project_archive.preflight_project_archive(first.body)
        self.assertEqual(manifest, first.manifest)
        self.assertEqual([item.episode_no for item in manifest.episodes], [1])
        self.assertTrue(all(item.archive_path.startswith(item.partition + "/") for item in manifest.members))
        with zipfile.ZipFile(io.BytesIO(first.body)) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertNotIn("outputs/episodes/episode_01.review.json", "\n".join(names))
            evidence = json.loads(archive.read("evidence/episode_001.json"))
            portable_episode = json.loads(
                archive.read("creative/outputs/episodes/episode_01.json")
            )
            portable_meta = json.loads(
                archive.read("creative/outputs/episodes/episode_01.meta.json")
            )
        self.assertEqual(evidence["artifact_type"], "drama_project_archive_evidence")
        self.assertNotIn("tasks", json.dumps(evidence["tasks"]))
        self.assertNotIn("url", json.dumps(evidence))
        self.assertFalse(
            any("prompt" in key.casefold() for shot in portable_episode["storyboard"] for key in shot)
        )
        self.assertNotIn("PROMPT_SENTINEL", json.dumps(portable_episode))
        self.assertNotIn("INNOCENT_KEY_PRIVATE_SENTINEL", json.dumps(portable_episode))
        self.assertEqual(portable_meta["agent_reviews"], [])
        self.assertNotIn("REVIEW_SENTINEL", json.dumps(portable_meta))

    def test_import_and_reexport_preserve_member_and_project_identity(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        result = drama_project_archive.import_project_archive(
            exported.body,
            target_workspace="archive-imported",
        )
        self.assertEqual(result.project_id, exported.manifest.project_id)
        self.assertEqual(result.member_count, len(exported.manifest.members))
        self.assertEqual(
            (result.target / "data/workspace.json").read_text(encoding="utf-8"),
            '{\n  "created_at": null,\n  "schema_version": 1,\n  "type": "drama"\n}\n',
        )
        for record in exported.manifest.members:
            installed = result.target / record.target_path
            self.assertTrue(installed.is_file())
            self.assertEqual(
                __import__("hashlib").sha256(installed.read_bytes()).hexdigest(),
                record.sha256,
            )
        reexported = drama_project_archive.export_project_archive("archive-imported")
        self.assertEqual(reexported.body, exported.body)
        self.assertEqual(reexported.manifest, exported.manifest)

    def test_import_never_overwrites_existing_workspace(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        self._make_drama_workspace("occupied")
        marker = paths.WORKSPACE_DIR / "occupied" / "data" / "marker.txt"
        marker.write_text("owned", encoding="utf-8")
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "target_workspace_exists",
        ):
            drama_project_archive.import_project_archive(
                exported.body,
                target_workspace="occupied",
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "owned")
        self.assertFalse(list(paths.WORKSPACE_DIR.glob(".occupied.archive-import.*")))

    def test_export_fails_closed_while_a_cooperating_writer_holds_the_lock(self) -> None:
        self._assembled()
        with use_workspace("archive-source"), acquire_write_lock(source="archive-test-writer"):
            with self.assertRaisesRegex(
                drama_project_archive.DramaProjectArchiveError,
                "workspace_busy",
            ):
                drama_project_archive.export_project_archive("archive-source")

    def test_atomic_noreplace_preserves_a_concurrently_created_target(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        original = drama_project_archive._rename_directory_noreplace

        def race(source: Path, target: Path) -> None:
            target.mkdir()
            (target / "owner.txt").write_text("concurrent", encoding="utf-8")
            original(source, target)

        with patch.object(
            drama_project_archive,
            "_rename_directory_noreplace",
            side_effect=race,
        ), self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "target_workspace_exists",
        ):
            drama_project_archive.import_project_archive(
                exported.body, target_workspace="archive-raced"
            )
        raced = paths.WORKSPACE_DIR / "archive-raced"
        self.assertEqual((raced / "owner.txt").read_text(encoding="utf-8"), "concurrent")
        self.assertFalse(list(paths.WORKSPACE_DIR.glob(".archive-raced.archive-import.*")))

    def test_parent_fsync_failure_returns_committed_with_uncertain_durability(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        renamed = False
        original_rename = drama_project_archive._rename_directory_noreplace
        original_fsync = os.fsync

        def rename(source: Path, target: Path) -> None:
            nonlocal renamed
            original_rename(source, target)
            renamed = True

        def fsync(fd: int) -> None:
            if renamed:
                raise OSError("parent fsync unavailable")
            original_fsync(fd)

        with patch.object(
            drama_project_archive,
            "_rename_directory_noreplace",
            side_effect=rename,
        ), patch.object(drama_project_archive.os, "fsync", side_effect=fsync):
            result = drama_project_archive.import_project_archive(
                exported.body, target_workspace="archive-commit-uncertain"
            )
        self.assertEqual(result.durability, "commit_uncertain")
        self.assertTrue(result.target.is_dir())
        self.assertTrue(
            (result.target / "data/drama_project_archive/import_manifest.json").is_file()
        )

    def test_shared_optional_audio_member_is_idempotently_deduplicated(self) -> None:
        payloads = {}
        records = []
        target = "outputs/drama/optional_audio/shared_bgm.wav"
        wav = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=20, sample_rate=16000
        )
        drama_project_archive._add_payload(
            payloads, records, target=target, payload=wav
        )
        drama_project_archive._add_payload(
            payloads, records, target=target, payload=wav
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(payloads), 1)
        changed = bytearray(wav)
        changed[-1] ^= 1
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "source_member_duplicate",
        ):
            drama_project_archive._add_payload(
                payloads, records, target=target, payload=bytes(changed)
            )
        self.assertIsNone(
            drama_project_archive._episode_number_from_target(
                "outputs/drama/optional_audio/episode_099.wav"
            )
        )

    def test_asset_members_require_real_metadata_free_png(self) -> None:
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "target_path_not_allowed",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/key.txt", payload=b"secret"
            )
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "png_invalid",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/fake.png", payload=b"not png"
            )

        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                len(payload).to_bytes(4, "big")
                + kind
                + payload
                + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        ihdr = (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
        idat = chunk(b"IDAT", zlib.compress(b"\x00\x11\x22\x33\xff"))
        tagged = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"tEXt", b"prompt\x00PRIVATE_SENTINEL")
            + idat
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "png_private_metadata",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/tagged.png", payload=tagged
            )
        custom = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"prIv", b"credential=PRIVATE_SENTINEL")
            + idat
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "png_private_metadata",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/custom.png", payload=custom
            )
        missing_pixels = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "png_invalid",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/no-idat.png", payload=missing_pixels
            )
        valid = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + idat
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "png_invalid",
        ):
            drama_project_archive._add_payload(
                {}, [], target="data/character_refs/c001/bad-signature.png",
                payload=b"NOT_A_PN" + valid[8:],
            )

    def test_typed_selection_schema_rejects_noncanonical_identity(self) -> None:
        with self.assertRaises(ValueError):
            drama_project_archive.ArchiveSelectedShot(
                shot_id="not-a-shot",
                image={
                    "manifest_fingerprint": "0" * 64,
                    "current_request_fingerprint": "1" * 64,
                    "selection_revision": -1,
                    "tail_binding_revision": 0,
                    "first": None,
                    "tail": None,
                },
                video=None,
            )

    def test_bad_hash_and_extra_member_fail_before_target_creation(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        source = zipfile.ZipFile(io.BytesIO(exported.body))
        records = [(info, source.read(info)) for info in source.infolist()]
        source.close()

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for info, payload in records:
                if info.filename != "manifest.json" and info.filename.endswith(".json"):
                    payload += b" "
                archive.writestr(info, payload)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "member_(?:size|hash)_mismatch",
        ):
            drama_project_archive.import_project_archive(
                stream.getvalue(), target_workspace="bad-hash"
            )
        self.assertFalse((paths.WORKSPACE_DIR / "bad-hash").exists())

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for info, payload in records:
                archive.writestr(info, payload)
            archive.writestr(self._zip_info("media/unlisted.json"), b"{}")
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "manifest_member_set_mismatch",
        ):
            drama_project_archive.preflight_project_archive(stream.getvalue())

    def test_semantic_selection_tamper_is_rejected_even_with_rehashed_manifest(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        with zipfile.ZipFile(io.BytesIO(exported.body)) as source:
            members = {info.filename: source.read(info) for info in source.infolist()}
        manifest = json.loads(members["manifest.json"])
        evidence_name = "evidence/episode_001.json"
        evidence = json.loads(members[evidence_name])
        forged = "0" * 64
        evidence["selection_fingerprint"] = forged
        members[evidence_name] = drama_project_archive._json_bytes(evidence)
        manifest["episodes"][0]["selection_fingerprint"] = forged
        evidence_record = next(
            item for item in manifest["members"] if item["archive_path"] == evidence_name
        )
        evidence_record["size"] = len(members[evidence_name])
        evidence_record["sha256"] = __import__("hashlib").sha256(
            members[evidence_name]
        ).hexdigest()
        identity = [
            {
                "target_path": item["target_path"],
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in manifest["members"]
        ]
        manifest["project_id"] = f"dpa_{drama_project_archive._fingerprint(identity)[:24]}"
        manifest["archive_fingerprint"] = drama_project_archive._fingerprint(
            {key: value for key, value in manifest.items() if key != "archive_fingerprint"}
        )
        members["manifest.json"] = drama_project_archive._json_bytes(manifest)
        forged_archive = drama_project_archive._build_archive_zip(members)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "selection_fingerprint_mismatch",
        ):
            drama_project_archive.preflight_project_archive(forged_archive)

    def test_zip_slip_duplicate_case_collision_and_symlink_are_rejected(self) -> None:
        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        source = zipfile.ZipFile(io.BytesIO(exported.body))
        records = [(info, source.read(info)) for info in source.infolist()]
        source.close()

        for name in ("../escape", "/absolute", "media\\windows"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                for info, payload in records:
                    archive.writestr(info, payload)
                archive.writestr(self._zip_info(name), b"x")
            with self.subTest(name=name), self.assertRaisesRegex(
                drama_project_archive.DramaProjectArchiveError,
                "member_path_invalid",
            ):
                drama_project_archive.preflight_project_archive(stream.getvalue())

        for extra_name in (records[0][0].filename, records[0][0].filename.upper()):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                for info, payload in records:
                    archive.writestr(info, payload)
                archive.writestr(self._zip_info(extra_name), b"x")
            with self.subTest(extra_name=extra_name), self.assertRaisesRegex(
                drama_project_archive.DramaProjectArchiveError,
                "member_duplicate",
            ):
                drama_project_archive.preflight_project_archive(stream.getvalue())

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for info, payload in records:
                archive.writestr(info, payload)
            link = self._zip_info("media/link")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, b"target")
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "member_attributes_invalid",
        ):
            drama_project_archive.preflight_project_archive(stream.getvalue())

    def test_compression_ratio_and_unknown_schema_are_rejected(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest_info = self._zip_info("manifest.json")
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            bomb_info = self._zip_info("media/bomb.bin")
            bomb_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(manifest_info, b"{}")
            archive.writestr(bomb_info, b"0" * 200_000)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "compression_ratio_invalid",
        ):
            drama_project_archive.preflight_project_archive(stream.getvalue())

        self._assembled()
        exported = drama_project_archive.export_project_archive("archive-source")
        with zipfile.ZipFile(io.BytesIO(exported.body)) as source:
            records = [(info, source.read(info)) for info in source.infolist()]
        manifest = json.loads(next(payload for info, payload in records if info.filename == "manifest.json"))
        manifest["schema_version"] = 2
        changed = json.dumps(manifest, ensure_ascii=False).encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for info, payload in records:
                archive.writestr(info, changed if info.filename == "manifest.json" else payload)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "manifest_invalid",
        ):
            drama_project_archive.preflight_project_archive(stream.getvalue())

    def test_source_and_input_archive_symlinks_are_not_followed(self) -> None:
        self._assembled()
        episode = episode_paths("archive-source").episode_path
        outside = paths.WORKSPACE_DIR / "outside.json"
        outside.write_bytes(episode.read_bytes())
        episode.unlink()
        episode.symlink_to(outside)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "source_member_invalid",
        ):
            drama_project_archive.export_project_archive("archive-source")

        real = paths.WORKSPACE_DIR / "archive.zip"
        real.write_bytes(b"zip")
        link = paths.WORKSPACE_DIR / "archive-link.zip"
        link.symlink_to(real)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "archive_file_invalid",
        ):
            drama_project_archive.read_project_archive_file(link)

        canonical_root = paths.WORKSPACE_DIR.resolve()
        real_parent = canonical_root / "archive-real-parent"
        real_parent.mkdir()
        (real_parent / "inside.zip").write_bytes(b"zip")
        parent_link = canonical_root / "archive-parent-link"
        parent_link.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(
            drama_project_archive.DramaProjectArchiveError,
            "archive_file_invalid",
        ):
            drama_project_archive.read_project_archive_file(
                parent_link / "inside.zip"
            )

    def test_cli_parser_exposes_export_preflight_and_import(self) -> None:
        import main

        parser = main.build_parser()
        self.assertEqual(
            parser.parse_args(["drama-project-archive", "export"]).drama_archive_command,
            "export",
        )
        parsed = parser.parse_args(
            ["drama-project-archive", "import", "--archive", "x.zip", "--to", "new"]
        )
        self.assertEqual(parsed.to_name, "new")

    def test_cli_export_preflight_and_import_roundtrip(self) -> None:
        import main

        self._assembled("archive-cli-source")
        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "main.py", "--book", "archive-cli-source",
                "drama-project-archive", "export",
            ],
        ), redirect_stdout(output):
            main.main()
        exported = json.loads(output.getvalue())
        self.assertEqual(exported["status"], "exported")

        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "main.py", "drama-project-archive", "preflight",
                "--archive", exported["path"],
            ],
        ), redirect_stdout(output):
            main.main()
        preflight = json.loads(output.getvalue())
        self.assertEqual(preflight["status"], "valid")
        self.assertEqual(preflight["project_id"], exported["project_id"])

        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "main.py", "drama-project-archive", "import",
                "--archive", exported["path"], "--to", "archive-cli-imported",
            ],
        ), redirect_stdout(output):
            main.main()
        imported = json.loads(output.getvalue())
        self.assertEqual(imported["status"], "imported")
        self.assertEqual(imported["project_id"], exported["project_id"])
        self.assertTrue((paths.WORKSPACE_DIR / "archive-cli-imported").is_dir())


if __name__ == "__main__":
    import unittest

    unittest.main()
