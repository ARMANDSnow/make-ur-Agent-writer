"""iter111: pure provider-neutral shot image request assembly."""

from __future__ import annotations

from src import drama_shot_image
from src.drama_schemas import EpisodeShotImagePlan, ShotImageReferencePolicy
from src.schemas import model_to_dict
from tests._drama_shot_image_base import DramaShotImageFixture


class DramaShotImagePureTests(DramaShotImageFixture):
    def test_plan_is_byte_stable_and_preserves_explicit_shot_order(self) -> None:
        sources = self._seed_shot_image_sources()
        first = self._build_pure(sources)
        second = self._build_pure(sources)
        self.assertEqual(first, second)
        self.assertEqual(
            [item.shot_id for item in first.shot_specs],
            [item.shot_id for item in sources["render_plan"].shots],
        )
        self.assertTrue(all(item.status == "assembled" for item in first.shot_specs))
        self.assertEqual(
            [item.kind for item in first.shot_specs[0].image_references],
            ["character", "scene"],
        )
        self.assertEqual(EpisodeShotImagePlan(**model_to_dict(first)), first)
        expected_binding_fingerprint = drama_shot_image._sha256(
            [
                {"shot_id": item.shot_id, "character_ids": item.character_ids}
                for item in sorted(
                    first.character_bindings,
                    key=lambda item: item.shot_id,
                )
            ]
        )
        self.assertEqual(
            first.character_binding_fingerprint,
            expected_binding_fingerprint,
        )

    def test_character_binding_is_complete_explicit_and_frozen_cast_only(self) -> None:
        sources = self._seed_shot_image_sources("bindings")
        mapping = dict(sources["character_mapping"])
        mapping.pop(next(iter(mapping)))
        sources["character_mapping"] = mapping
        with self.assertRaisesRegex(ValueError, "shot image plan build was rejected"):
            self._build_pure(sources)

        sources = self._seed_shot_image_sources("outside-cast")
        first = next(iter(sources["character_mapping"]))
        sources["character_mapping"][first] = ["c999"]
        with self.assertRaisesRegex(ValueError, "shot image plan build was rejected"):
            self._build_pure(sources)

    def test_reference_priority_and_truncation_are_deterministic(self) -> None:
        sources = self._seed_shot_image_sources(
            "truncate",
            prop_count=2,
            max_reference_images=3,
        )
        plan = self._build_pure(sources)
        first = plan.shot_specs[0]
        self.assertEqual(
            [(item.kind, item.position) for item in first.image_references],
            [("character", 1), ("scene", 2), ("prop", 3)],
        )
        self.assertEqual(first.dropped_reference_count, 1)
        self.assertIn("reference_limit_exceeded", first.warning_codes)
        self.assertEqual(self._build_pure(sources), plan)

    def test_missing_character_artifact_blocks_without_forging_reference(self) -> None:
        sources = self._seed_shot_image_sources(
            "metadata-character",
            character_artifacts=False,
        )
        plan = self._build_pure(sources)
        first = plan.shot_specs[0]
        self.assertEqual(first.status, "blocked")
        self.assertEqual(first.blocked_reasons, ["character_artifact_missing"])
        self.assertFalse(
            any(item.kind == "character" for item in first.image_references)
        )

    def test_metadata_scene_is_text_guidance_not_fake_image_reference(self) -> None:
        sources = self._seed_shot_image_sources(
            "metadata-scene",
            scene_artifact=False,
        )
        first = self._build_pure(sources).shot_specs[0]
        self.assertEqual(first.status, "assembled")
        self.assertIn("scene_artifact_missing", first.warning_codes)
        self.assertEqual(first.scene_version.spec.display_name, "天台")
        self.assertFalse(any(item.kind == "scene" for item in first.image_references))

    def test_policy_and_schema_reject_bool_extra_and_tampering(self) -> None:
        with self.assertRaisesRegex(ValueError, "reference policy build was rejected"):
            drama_shot_image.build_shot_image_reference_policy(
                max_reference_images=True,
            )
        sources = self._seed_shot_image_sources("tamper")
        plan = self._build_pure(sources)
        raw = model_to_dict(plan.reference_policy)
        raw["extra"] = "SECRET"
        with self.assertRaises(ValueError):
            ShotImageReferencePolicy(**raw)
        raw = model_to_dict(plan)
        raw["shot_specs"][0]["request_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            EpisodeShotImagePlan(**raw)

    def test_schema_rejects_rehashed_reference_reordering(self) -> None:
        sources = self._seed_shot_image_sources("rehash-reference")
        raw = model_to_dict(self._build_pure(sources))
        request = raw["shot_specs"][0]
        request["image_references"].reverse()
        for position, reference in enumerate(request["image_references"], start=1):
            reference["position"] = position
        request["request_fingerprint"] = drama_shot_image._sha256(
            {key: value for key, value in request.items() if key != "request_fingerprint"}
        )
        raw["plan_fingerprint"] = drama_shot_image._sha256(
            {key: value for key, value in raw.items() if key != "plan_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "exact priority prefix"):
            EpisodeShotImagePlan(**raw)

        raw = model_to_dict(self._build_pure(sources))
        request = raw["shot_specs"][0]
        request["character_refs"][0]["artifact_sha256"] = "0" * 64
        request["request_fingerprint"] = drama_shot_image._sha256(
            {key: value for key, value in request.items() if key != "request_fingerprint"}
        )
        raw["plan_fingerprint"] = drama_shot_image._sha256(
            {key: value for key, value in raw.items() if key != "plan_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "exact artifacts"):
            EpisodeShotImagePlan(**raw)

    def test_scene_and_prop_bindings_must_match_current_shot_source(self) -> None:
        sources = self._seed_shot_image_sources("stale-shot-source", prop_count=1)
        scene_manifest = sources["scene_manifest"].model_copy(deep=True)
        scene_manifest.shot_scene_refs[0].source_fingerprint = "0" * 64
        sources["scene_manifest"] = scene_manifest
        with self.assertRaisesRegex(ValueError, "shot image plan build was rejected"):
            self._build_pure(sources)

        sources = self._seed_shot_image_sources("stale-prop-source", prop_count=1)
        prop_manifest = sources["prop_manifest"].model_copy(deep=True)
        prop_manifest.shot_asset_refs[0].source_fingerprint = "0" * 64
        sources["prop_manifest"] = prop_manifest
        with self.assertRaisesRegex(ValueError, "shot image plan build was rejected"):
            self._build_pure(sources)

    def test_affected_shots_are_reported_without_mutating_upstream(self) -> None:
        sources = self._seed_shot_image_sources("affected")
        before = self._build_pure(sources)
        first_id = before.character_bindings[0].shot_id
        sources["character_mapping"][first_id] = []
        after = self._build_pure(sources, binding_revision=1)
        self.assertEqual(drama_shot_image.shot_image_affected_ids(before, after), [first_id])
        self.assertEqual(
            sources["render_plan"].plan_fingerprint,
            before.render_plan_fingerprint,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
