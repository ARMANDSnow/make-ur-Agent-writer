"""iter130: strict C2 shot-image Web projection, media route, and CAS."""

from __future__ import annotations

import json
import zlib
from unittest.mock import patch

from src import (
    drama_shot_image_candidate_store,
    drama_shot_image_candidates,
    drama_shot_image_web,
    paths,
)
from src.web import routes
from tests._drama_shot_image_candidate_base import DramaShotImageCandidateFixture


class DramaShotImageWebTests(DramaShotImageCandidateFixture):
    _HEADERS = {
        "content-type": "application/json",
        "x-drama-shot-image-intent": "mutate-v1",
        "sec-fetch-site": "same-origin",
        "origin": "http://127.0.0.1:8765",
        "host": "127.0.0.1:8765",
    }

    @staticmethod
    def _decode(response: tuple) -> tuple[int, dict]:
        status, content_type, body = response[:3]
        assert "application/json" in content_type
        return status, json.loads(body)

    def _get(self, name: str) -> tuple[int, dict]:
        return self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/shot-images?episode_no=1",
            )
        )

    def _post(self, name: str, payload: dict, *, headers: dict | None = None):
        return self._decode(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/shot-images/select",
                json.dumps(payload).encode(),
                headers if headers is not None else self._HEADERS,
            )
        )

    def _seed_two_candidates(self, name: str):
        sources = self._seed_candidate_sources(name)
        manifest = self._create_manifest(name)
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        manifest, first = self._append_candidate(name, manifest, shot_id)
        manifest, second = self._append_candidate(
            name,
            manifest,
            shot_id,
            rgba=b"\xaa\xbb\xcc\xff",
        )
        return sources, manifest, first, second

    def test_page_and_missing_manifest_are_graceful(self) -> None:
        self._seed_candidate_sources("shot-image-web-empty")
        status, _content_type, body = routes.dispatch(
            "GET",
            "/w/shot-image-web-empty/shot-images",
        )
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("镜头图片候选", html)
        self.assertIn('window.PAGE_KIND = "drama_shot_images"', html)
        self.assertIn("shot-images-page-root", html)
        self.assertIn("candidate.current", routes.static.JS_DASHBOARD)
        self.assertIn("overview.mutation_allowed", routes.static.JS_DASHBOARD)
        self.assertIn('aria-label="', routes.static.JS_DASHBOARD)
        self.assertIn("清除镜头 ", routes.static.JS_DASHBOARD)
        status, data = self._get("shot-image-web-empty")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "needs_shot_image_assets")
        self.assertEqual(data["shots"], [])
        self.assertIsNone(data["manifest_fingerprint"])
        self.assertFalse(data["mutation_allowed"])

    def test_projection_is_allowlisted_sorted_and_does_not_leak_paths(self) -> None:
        _sources, manifest, first, second = self._seed_two_candidates(
            "shot-image-web-projection"
        )
        status, data = self._get("shot-image-web-projection")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "fresh")
        self.assertEqual(data["manifest_fingerprint"], manifest.manifest_fingerprint)
        shot = data["shots"][0]
        self.assertEqual(
            [item["candidate_id"] for item in shot["candidates"]],
            sorted([first.candidate_id, second.candidate_id]),
        )
        self.assertTrue(
            all(item["preview_url"].startswith("/api/workspace/") for item in shot["candidates"])
        )
        self.assertTrue(all(item["current"] is True for item in shot["candidates"]))
        encoded = json.dumps(data)
        for forbidden in (
            "artifact.path",
            "outputs/episodes",
            "positive_tokens",
            "negative_tokens",
            "prompt",
            "provider",
            "signed_url",
            str(paths.workspace_root("shot-image-web-projection")),
        ):
            self.assertNotIn(forbidden, encoded)

    def test_exact_png_route_revalidates_manifest_and_bytes(self) -> None:
        _sources, _manifest, first, _second = self._seed_two_candidates(
            "shot-image-web-png"
        )
        status, data = self._get("shot-image-web-png")
        self.assertEqual(status, 200)
        preview = next(
            item["preview_url"]
            for item in data["shots"][0]["candidates"]
            if item["candidate_id"] == first.candidate_id
        )
        response = routes.dispatch("GET", preview)
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1], "image/png")
        self.assertEqual(response[2], self._png())
        self.assertEqual(response[3]["X-Content-Type-Options"], "nosniff")

        artifact = paths.workspace_root("shot-image-web-png") / first.artifact.path
        artifact.write_bytes(self._png(rgba=b"\x00\x00\x00\xff"))
        status, payload = self._decode(routes.dispatch("GET", preview))
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "shot image candidate is unavailable")

    def test_png_preview_strips_text_and_unknown_ancillary_metadata(self) -> None:
        sources = self._seed_candidate_sources("shot-image-web-metadata")
        manifest = self._create_manifest("shot-image-web-metadata")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        original = self._png()
        secret = b"prompt\x00signed=https://secret.invalid/path?token=abc"
        text_chunk = (
            len(secret).to_bytes(4, "big")
            + b"tEXt"
            + secret
            + (zlib.crc32(b"tEXt" + secret) & 0xFFFFFFFF).to_bytes(4, "big")
        )
        transparency_secret = b"provider-token-and-local-path"
        transparency_chunk = (
            len(transparency_secret).to_bytes(4, "big")
            + b"tRNS"
            + transparency_secret
            + (
                zlib.crc32(b"tRNS" + transparency_secret) & 0xFFFFFFFF
            ).to_bytes(4, "big")
        )
        payload = (
            original[:33]
            + text_chunk
            + transparency_chunk
            + original[33:]
        )
        manifest, candidate = (
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "shot-image-web-metadata",
                shot_id=shot_id,
                png_bytes=payload,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        status, data = self._get("shot-image-web-metadata")
        self.assertEqual(status, 200)
        preview = data["shots"][0]["candidates"][0]["preview_url"]
        response = routes.dispatch("GET", preview)
        self.assertEqual(response[0], 200)
        self.assertNotIn(secret, response[2])
        self.assertNotIn(transparency_secret, response[2])
        self.assertNotIn(b"tEXt", response[2])
        self.assertNotIn(b"tRNS", response[2])
        self.assertNotEqual(response[2], payload)
        self.assertEqual(
            drama_shot_image_candidate_store._validate_png(response[2]),
            (1, 1),
        )
        self.assertEqual(
            manifest.shots[0].candidates[0].candidate_id,
            candidate.candidate_id,
        )

    def test_png_preview_preserves_strict_legal_grayscale_transparency(self) -> None:
        sources = self._seed_candidate_sources("shot-image-web-transparency")
        manifest = self._create_manifest("shot-image-web-transparency")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id

        def chunk(kind: bytes, value: bytes) -> bytes:
            return (
                len(value).to_bytes(4, "big")
                + kind
                + value
                + (zlib.crc32(kind + value) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        ihdr = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes(
            [8, 0, 0, 0, 0]
        )
        transparent_sample = b"\x00\x00"
        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"tRNS", transparent_sample)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
            + chunk(b"IEND", b"")
        )
        _manifest, _candidate = (
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "shot-image-web-transparency",
                shot_id=shot_id,
                png_bytes=payload,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        status, data = self._get("shot-image-web-transparency")
        self.assertEqual(status, 200)
        response = routes.dispatch(
            "GET",
            data["shots"][0]["candidates"][0]["preview_url"],
        )
        self.assertEqual(response[0], 200)
        self.assertIn(chunk(b"tRNS", transparent_sample), response[2])
        self.assertEqual(
            drama_shot_image_candidate_store._validate_png(response[2]),
            (1, 1),
        )

    def test_projection_marks_retained_old_request_candidate_read_only(self) -> None:
        sources = self._seed_candidate_sources("shot-image-web-retained")
        plan = sources["shot_image_plan"]
        manifest = self._create_manifest("shot-image-web-retained")
        shot_id = plan.shot_specs[0].shot_id
        manifest, old_candidate = self._append_candidate(
            "shot-image-web-retained",
            manifest,
            shot_id,
        )
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        changed_mapping[shot_id] = []
        sources["character_mapping"] = changed_mapping
        new_plan = self._build_pure(sources, binding_revision=1)
        reconciled = drama_shot_image_candidates.reconcile_shot_image_candidate_manifest(
            manifest,
            new_plan,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        coverage = drama_shot_image_candidates.shot_image_coverage(
            reconciled,
            new_plan,
        )
        inspection = drama_shot_image_candidate_store.ShotImageCandidateInspection(
            "fresh",
            (),
            reconciled,
            (),
            coverage,
        )
        with patch.object(
            drama_shot_image_web,
            "inspect_episode_shot_image_candidates",
            return_value=inspection,
        ):
            overview = drama_shot_image_web.build_shot_image_web_overview(
                "shot-image-web-retained"
            )
        candidate = overview.shots[0].candidates[0]
        self.assertEqual(candidate.candidate_id, old_candidate.candidate_id)
        self.assertFalse(candidate.current)
        self.assertTrue(overview.mutation_allowed)

    def test_source_plan_stale_projection_is_compare_only(self) -> None:
        self._seed_two_candidates("shot-image-web-source-stale")
        inspection = drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
            "shot-image-web-source-stale"
        )
        stale = drama_shot_image_candidate_store.ShotImageCandidateInspection(
            "stale",
            ("source_plan_mismatch",),
            inspection.manifest,
            (inspection.manifest.shots[0].shot_id,),
            inspection.coverage,
        )
        with patch.object(
            drama_shot_image_web,
            "inspect_episode_shot_image_candidates",
            return_value=stale,
        ):
            overview = drama_shot_image_web.build_shot_image_web_overview(
                "shot-image-web-source-stale"
            )
        self.assertFalse(overview.mutation_allowed)
        self.assertTrue(overview.shots)

    def test_first_selection_and_exact_lost_response_replay(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-image-web-first"
        )
        shot_id = manifest.shots[0].shot_id
        payload = {
            "episode_no": 1,
            "shot_id": shot_id,
            "frame": "first",
            "candidate_id": first.candidate_id,
            "expected_selection_revision": 0,
            "expected_current_binding": None,
            "expected_manifest_fingerprint": manifest.manifest_fingerprint,
        }
        status, result = self._post("shot-image-web-first", payload)
        self.assertEqual(status, 200)
        self.assertTrue(result["changed"])
        self.assertEqual(
            result["overview"]["shots"][0]["first_binding"]["candidate_id"],
            first.candidate_id,
        )
        status, replay = self._post("shot-image-web-first", payload)
        self.assertEqual(status, 200)
        self.assertFalse(replay["changed"])

        stale = dict(payload)
        stale["candidate_id"] = result["overview"]["shots"][0]["candidates"][1][
            "candidate_id"
        ]
        status, _error = self._post("shot-image-web-first", stale)
        self.assertEqual(status, 409)

    def test_tail_selection_and_clear_use_current_revision(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-image-web-tail"
        )
        shot_id = manifest.shots[0].shot_id
        select_payload = {
            "episode_no": 1,
            "shot_id": shot_id,
            "frame": "tail",
            "candidate_id": first.candidate_id,
            "expected_selection_revision": 0,
            "expected_current_binding": {"kind": "none"},
            "expected_manifest_fingerprint": manifest.manifest_fingerprint,
        }
        status, selected = self._post("shot-image-web-tail", select_payload)
        self.assertEqual(status, 200)
        shot = selected["overview"]["shots"][0]
        self.assertEqual(shot["tail_binding"]["candidate_id"], first.candidate_id)
        clear_payload = {
            "episode_no": 1,
            "shot_id": shot_id,
            "frame": "tail",
            "candidate_id": None,
            "expected_selection_revision": shot["selection_revision"],
            "expected_current_binding": shot["tail_binding"],
            "expected_manifest_fingerprint": selected["overview"]["manifest_fingerprint"],
        }
        status, cleared = self._post("shot-image-web-tail", clear_payload)
        self.assertEqual(status, 200)
        self.assertTrue(cleared["changed"])
        self.assertEqual(cleared["overview"]["shots"][0]["tail_binding"], {"kind": "none"})

    def test_tail_change_replay_and_broken_next_lineage_are_repairable(self) -> None:
        sources = self._seed_candidate_sources("shot-image-web-lineage")
        manifest = self._create_manifest("shot-image-web-lineage")
        first_shot = sources["shot_image_plan"].shot_specs[0]
        second_shot = sources["shot_image_plan"].shot_specs[1]
        manifest, tail_a = self._append_candidate(
            "shot-image-web-lineage",
            manifest,
            first_shot.shot_id,
        )
        manifest, tail_b = self._append_candidate(
            "shot-image-web-lineage",
            manifest,
            first_shot.shot_id,
            rgba=b"\xaa\xbb\xcc\xff",
        )
        manifest, second_direct = self._append_candidate(
            "shot-image-web-lineage",
            manifest,
            second_shot.shot_id,
        )
        first_tail_binding = {
            "kind": "direct",
            "candidate_id": tail_a.candidate_id,
            "candidate_fingerprint": tail_a.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "shot-image-web-lineage",
            shot_id=first_shot.shot_id,
            frame="tail",
            binding=first_tail_binding,
            expected_selection_revision=0,
            expected_current_binding={"kind": "none"},
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        previous_tail_binding = {
            "kind": "previous_tail",
            "source_shot_id": first_shot.shot_id,
            "candidate_id": tail_a.candidate_id,
            "candidate_fingerprint": tail_a.candidate_fingerprint,
            "source_tail_revision": 1,
            "target_request_fingerprint": second_shot.request_fingerprint,
        }
        manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "shot-image-web-lineage",
            shot_id=second_shot.shot_id,
            frame="first",
            binding=previous_tail_binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        change_tail = {
            "episode_no": 1,
            "shot_id": first_shot.shot_id,
            "frame": "tail",
            "candidate_id": tail_b.candidate_id,
            "expected_selection_revision": 1,
            "expected_current_binding": first_tail_binding,
            "expected_manifest_fingerprint": manifest.manifest_fingerprint,
        }
        status, changed = self._post("shot-image-web-lineage", change_tail)
        self.assertEqual(status, 200)
        self.assertTrue(changed["changed"])
        self.assertEqual(changed["overview"]["state"], "stale")
        self.assertIn(
            second_shot.shot_id,
            changed["overview"]["coverage"]["broken_lineage_shot_ids"],
        )

        status, replay = self._post("shot-image-web-lineage", change_tail)
        self.assertEqual(status, 200)
        self.assertFalse(replay["changed"])
        stale_second = next(
            item
            for item in replay["overview"]["shots"]
            if item["shot_id"] == second_shot.shot_id
        )
        repair = {
            "episode_no": 1,
            "shot_id": second_shot.shot_id,
            "frame": "first",
            "candidate_id": second_direct.candidate_id,
            "expected_selection_revision": stale_second["selection_revision"],
            "expected_current_binding": stale_second["first_binding"],
            "expected_manifest_fingerprint": replay["overview"]["manifest_fingerprint"],
        }
        status, repaired = self._post("shot-image-web-lineage", repair)
        self.assertEqual(status, 200)
        self.assertTrue(repaired["changed"])
        self.assertEqual(repaired["overview"]["state"], "fresh")

    def test_mutation_headers_body_and_identity_fail_closed(self) -> None:
        _sources, manifest, first, _second = self._seed_two_candidates(
            "shot-image-web-boundary"
        )
        payload = {
            "episode_no": 1,
            "shot_id": manifest.shots[0].shot_id,
            "frame": "first",
            "candidate_id": first.candidate_id,
            "expected_selection_revision": 0,
            "expected_current_binding": None,
            "expected_manifest_fingerprint": manifest.manifest_fingerprint,
        }
        for headers, expected in (
            ({}, 415),
            ({"content-type": "application/json"}, 403),
            (
                {
                    **self._HEADERS,
                    "origin": "https://evil.invalid",
                },
                403,
            ),
        ):
            status, _data = self._post(
                "shot-image-web-boundary",
                payload,
                headers=headers,
            )
            self.assertEqual(status, expected)
        status, _data = self._post(
            "shot-image-web-boundary",
            {**payload, "unknown": True},
        )
        self.assertEqual(status, 400)
        status, _data = self._post(
            "shot-image-web-boundary",
            {**payload, "candidate_id": "sic_" + "0" * 24},
        )
        self.assertEqual(status, 400)

    def test_invalid_manifest_does_not_project_candidate_details(self) -> None:
        _sources, manifest, _first, _second = self._seed_two_candidates(
            "shot-image-web-invalid"
        )
        path = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "shot-image-web-invalid"
        )
        path.write_text("{", encoding="utf-8")
        status, data = self._get("shot-image-web-invalid")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "invalid")
        self.assertEqual(data["shots"], [])
        self.assertIsNone(data["manifest_fingerprint"])
        self.assertFalse(data["mutation_allowed"])
        self.assertNotIn(manifest.manifest_fingerprint, json.dumps(data))

    def test_novel_workspace_is_rejected(self) -> None:
        from src.cli_workspace import init_workspace

        init_workspace("shot-image-web-novel", type="novel")
        status, _data = self._decode(
            routes.dispatch(
                "GET",
                "/api/workspace/shot-image-web-novel/drama/shot-images",
            )
        )
        self.assertEqual(status, 400)
