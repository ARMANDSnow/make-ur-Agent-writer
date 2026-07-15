"""iter108: strict ArtDirection versions, catalogs, and selection CAS."""

from __future__ import annotations

from copy import deepcopy
import unittest

from pydantic import ValidationError

from src.drama_assets import (
    append_art_direction_version,
    build_art_direction_catalog,
    build_art_direction_version,
    select_art_direction_version,
    selected_art_direction_ref,
)
from src.drama_schemas import ArtDirectionCatalog, ArtDirectionVersion, _canonical_sha256
from src.schemas import model_to_dict


def _spec(*, preset: str = "cinematic") -> dict:
    return {
        "preset": preset,
        "positive_tokens": ["ink wash", "soft rim light"],
        "negative_tokens": ["watermark"],
        "palette": ["#112233", "#aabbcc"],
        "aspect_ratio": "9:16",
    }


def _catalog() -> ArtDirectionCatalog:
    version = build_art_direction_version(
        art_direction_id="season_default",
        spec=_spec(),
        source_kind="preset",
    )
    return build_art_direction_catalog(version, season_no=1)


class DramaArtDirectionPureTests(unittest.TestCase):
    def test_version_and_catalog_are_content_addressed_and_deterministic(self) -> None:
        spec = _spec()
        before = deepcopy(spec)
        first = build_art_direction_version(
            art_direction_id="season_default",
            spec=spec,
            source_kind="manual",
        )
        second = build_art_direction_version(
            art_direction_id="season_default",
            spec=spec,
            source_kind="manual",
        )
        self.assertEqual(spec, before)
        self.assertEqual(first, second)
        self.assertEqual(first.version_id, f"ad_{first.version_fingerprint[:24]}")

        catalog = build_art_direction_catalog(first)
        self.assertEqual(catalog.selected_version_id, first.version_id)
        self.assertEqual(catalog.selection_revision, 0)
        self.assertEqual(selected_art_direction_ref(catalog).fingerprint, first.version_fingerprint)

    def test_append_is_idempotent_and_does_not_change_selection(self) -> None:
        catalog = _catalog()
        selected = catalog.selected_version_id
        candidate = build_art_direction_version(
            art_direction_id=catalog.art_direction_id,
            spec=_spec(preset="graphic-novel"),
            source_kind="ai_suggestion",
            derived_from=selected,
        )
        appended = append_art_direction_version(
            catalog,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(appended.selected_version_id, selected)
        self.assertEqual(appended.selection_revision, 0)
        self.assertEqual(len(appended.versions), 2)
        self.assertEqual(
            append_art_direction_version(
                appended,
                version=candidate,
                expected_catalog_fingerprint=appended.catalog_fingerprint,
            ),
            appended,
        )

        with self.assertRaisesRegex(ValueError, "catalog changed"):
            append_art_direction_version(
                appended,
                version=build_art_direction_version(
                    art_direction_id=catalog.art_direction_id,
                    spec=_spec(preset="another"),
                    source_kind="manual",
                ),
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )

    def test_selection_double_cas_blocks_stale_and_aba(self) -> None:
        catalog = _catalog()
        original_id = catalog.selected_version_id
        candidate = build_art_direction_version(
            art_direction_id=catalog.art_direction_id,
            spec=_spec(preset="candidate"),
            source_kind="manual",
            derived_from=original_id,
        )
        appended = append_art_direction_version(
            catalog,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        selected = select_art_direction_version(
            appended,
            version_id=candidate.version_id,
            expected_selection_revision=0,
            expected_selected_version_id=original_id,
        )
        self.assertEqual(selected.selection_revision, 1)
        self.assertEqual(selected.selected_version_id, candidate.version_id)
        self.assertEqual(
            select_art_direction_version(
                selected,
                version_id=candidate.version_id,
                expected_selection_revision=1,
                expected_selected_version_id=candidate.version_id,
            ),
            selected,
        )
        restored = select_art_direction_version(
            selected,
            version_id=original_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.version_id,
        )
        self.assertEqual(restored.selection_revision, 2)
        self.assertEqual(restored.selected_version_id, original_id)
        with self.assertRaisesRegex(ValueError, "selection changed"):
            select_art_direction_version(
                restored,
                version_id=candidate.version_id,
                expected_selection_revision=0,
                expected_selected_version_id=original_id,
            )

    def test_schema_rejects_tamper_extra_bool_bad_tokens_palette_and_ratio(self) -> None:
        catalog = _catalog()
        cases = []
        raw = model_to_dict(catalog)
        raw["selection_revision"] = True
        cases.append(raw)
        raw = model_to_dict(catalog)
        raw["extra"] = "forbidden"
        cases.append(raw)
        for raw in cases:
            with self.assertRaises(ValidationError):
                ArtDirectionCatalog(**raw)

        for change in (
            {"positive_tokens": ["dup", "dup"]},
            {"negative_tokens": [""]},
            {"positive_tokens": [" padded "]},
            {"palette": ["#AABBCC"]},
            {"aspect_ratio": "0:16"},
        ):
            spec = _spec()
            spec.update(change)
            with self.assertRaises(ValidationError):
                build_art_direction_version(
                    art_direction_id="season_default",
                    spec=spec,
                    source_kind="manual",
                )

        blank = {
            "preset": "   ",
            "positive_tokens": [],
            "negative_tokens": [],
            "palette": [],
            "aspect_ratio": "9:16",
        }
        with self.assertRaises(ValidationError):
            build_art_direction_version(
                art_direction_id="season_default",
                spec=blank,
                source_kind="manual",
            )

        raw_version = model_to_dict(catalog.versions[0])
        raw_version["spec"]["preset"] = "forged"
        with self.assertRaises(ValidationError):
            ArtDirectionVersion(**raw_version)

    def test_catalog_rejects_duplicates_foreign_parent_and_cycle(self) -> None:
        catalog = _catalog()
        original = catalog.versions[0]
        duplicate_payload = {
            "schema_version": 1,
            "season_no": 1,
            "art_direction_id": catalog.art_direction_id,
            "versions": [model_to_dict(original), model_to_dict(original)],
            "selected_version_id": original.version_id,
            "selection_revision": 0,
        }
        duplicate_payload["catalog_fingerprint"] = _canonical_sha256(duplicate_payload)
        with self.assertRaises(ValidationError):
            ArtDirectionCatalog(**duplicate_payload)

        child = build_art_direction_version(
            art_direction_id=catalog.art_direction_id,
            spec=_spec(preset="orphan"),
            source_kind="manual",
            derived_from="ad_" + "f" * 24,
        )
        with self.assertRaisesRegex(ValueError, "derived art direction version"):
            append_art_direction_version(
                catalog,
                version=child,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )

        v1 = ArtDirectionVersion.model_construct(
            art_direction_id=catalog.art_direction_id,
            version_id="ad_" + "1" * 24,
            version_fingerprint="1" * 64,
            derived_from="ad_" + "2" * 24,
            source_kind="manual",
            spec=original.spec,
        )
        v2 = ArtDirectionVersion.model_construct(
            art_direction_id=catalog.art_direction_id,
            version_id="ad_" + "2" * 24,
            version_fingerprint="2" * 64,
            derived_from="ad_" + "1" * 24,
            source_kind="manual",
            spec=original.spec,
        )
        cycle_payload = {
            "schema_version": 1,
            "season_no": 1,
            "art_direction_id": catalog.art_direction_id,
            "versions": [model_to_dict(v1), model_to_dict(v2)],
            "selected_version_id": v1.version_id,
            "selection_revision": 0,
        }
        cycle = {
            **cycle_payload,
            "versions": [v1, v2],
            "catalog_fingerprint": _canonical_sha256(cycle_payload),
        }
        with self.assertRaises(ValidationError):
            ArtDirectionCatalog(**cycle)

        foreign = build_art_direction_version(
            art_direction_id="other_direction",
            spec=_spec(preset="foreign"),
            source_kind="manual",
        )
        with self.assertRaisesRegex(ValueError, "another catalog"):
            append_art_direction_version(
                catalog,
                version=foreign,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )

        missing_parent = "ad_" + "f" * 24
        orphan = build_art_direction_version(
            art_direction_id=catalog.art_direction_id,
            spec=_spec(preset="orphan-tail"),
            source_kind="manual",
            derived_from=missing_parent,
        )
        descendant = build_art_direction_version(
            art_direction_id=catalog.art_direction_id,
            spec=_spec(preset="orphan-head"),
            source_kind="manual",
            derived_from=orphan.version_id,
        )
        orphan_payload = {
            "schema_version": 1,
            "season_no": 1,
            "art_direction_id": catalog.art_direction_id,
            "versions": [model_to_dict(descendant), model_to_dict(orphan)],
            "selected_version_id": descendant.version_id,
            "selection_revision": 0,
        }
        orphan_payload["catalog_fingerprint"] = _canonical_sha256(orphan_payload)
        with self.assertRaises(ValidationError):
            ArtDirectionCatalog(**orphan_payload)


if __name__ == "__main__":
    unittest.main()
