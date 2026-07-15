"""iter110: pure prop/clue versioning and explicit zero-to-many bindings."""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from src import drama_assets
from src.drama_schemas import (
    PropOrClueAsset,
    PropOrClueAssetCatalog,
    PropOrClueAssetVersion,
    PropOrClueSpec,
    ShotPropOrClueRefs,
)
from src.schemas import model_to_dict


def _spec(
    kind: str = "prop",
    name: str = "旧怀表",
    *,
    state_label: str = "完好",
) -> dict:
    return {
        "kind": kind,
        "display_name": name,
        "owner_character_id": "c001",
        "state_label": state_label,
        "first_seen_episode_no": 1,
        "visual_tokens": ["黄铜", "划痕"],
    }


class DramaPropClueAssetPureTests(unittest.TestCase):
    def test_empty_catalog_add_append_select_and_aba_are_explicit(self) -> None:
        catalog = drama_assets.build_empty_prop_or_clue_asset_catalog()
        self.assertEqual(catalog.assets, [])

        first = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(),
            source_kind="identity_snapshot",
        )
        catalog = drama_assets.add_prop_or_clue_asset(
            catalog,
            version=first,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(catalog.assets[0].selected_version_id, first.asset_version_id)
        self.assertEqual(catalog.assets[0].selection_revision, 0)
        self.assertEqual(
            drama_assets.add_prop_or_clue_asset(
                catalog,
                version=first,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            ),
            catalog,
        )

        clue = drama_assets.build_prop_or_clue_asset_version(
            asset_id="l001",
            spec=_spec("clue", "密室钥匙"),
            source_kind="identity_snapshot",
        )
        catalog = drama_assets.add_prop_or_clue_asset(
            catalog,
            version=clue,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        candidate = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(state_label="停走"),
            source_kind="appended_candidate",
            derived_from=first.asset_version_id,
        )
        appended = drama_assets.append_prop_or_clue_asset_version(
            catalog,
            asset_id="p001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(appended.assets[0].selected_version_id, first.asset_version_id)
        self.assertEqual(
            drama_assets.add_prop_or_clue_asset(
                appended,
                version=first,
                expected_catalog_fingerprint=appended.catalog_fingerprint,
            ),
            appended,
        )
        self.assertEqual(
            drama_assets.append_prop_or_clue_asset_version(
                appended,
                asset_id="p001",
                version=candidate,
                expected_catalog_fingerprint=appended.catalog_fingerprint,
            ),
            appended,
        )
        selected = drama_assets.select_prop_or_clue_asset_version(
            appended,
            asset_id="p001",
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.asset_version_id,
        )
        returned = drama_assets.select_prop_or_clue_asset_version(
            selected,
            asset_id="p001",
            asset_version_id=first.asset_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.asset_version_id,
        )
        self.assertEqual(returned.assets[0].selection_revision, 2)
        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "selection was rejected",
        ):
            drama_assets.select_prop_or_clue_asset_version(
                returned,
                asset_id="p001",
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=first.asset_version_id,
            )

    def test_schema_rejects_kind_id_extra_bool_tamper_and_bad_path(self) -> None:
        with self.assertRaises(ValidationError):
            PropOrClueSpec(**{**_spec(), "extra": "no"})
        with self.assertRaises(ValidationError):
            PropOrClueSpec(**{**_spec(), "first_seen_episode_no": True})
        with self.assertRaises(ValidationError):
            PropOrClueSpec(**{**_spec(), "visual_tokens": ["x", "x"]})

        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "version build was rejected",
        ):
            drama_assets.build_prop_or_clue_asset_version(
                asset_id="l001",
                spec=_spec("prop"),
                source_kind="identity_snapshot",
            )
        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "version build was rejected",
        ):
            drama_assets.build_prop_or_clue_asset_version(
                asset_id="p001",
                spec=_spec(),
                source_kind="identity_snapshot",
                artifact={
                    "path": "data/prop_clue_refs/l001/wrong.png",
                    "sha256": "1" * 64,
                    "size_bytes": 10,
                },
            )

        version = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(),
            source_kind="identity_snapshot",
        )
        raw = model_to_dict(version)
        raw["version_fingerprint"] = "0" * 64
        with self.assertRaises(ValidationError):
            PropOrClueAssetVersion(**raw)

        catalog = drama_assets.build_empty_prop_or_clue_asset_catalog()
        raw_catalog = model_to_dict(catalog)
        raw_catalog["season_no"] = True
        with self.assertRaises(ValidationError):
            PropOrClueAssetCatalog(**raw_catalog)

    def test_cross_asset_derivation_and_kind_drift_fail_closed(self) -> None:
        prop = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(),
            source_kind="identity_snapshot",
        )
        catalog = drama_assets.build_empty_prop_or_clue_asset_catalog()
        catalog = drama_assets.add_prop_or_clue_asset(
            catalog,
            version=prop,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        orphan = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(state_label="损坏"),
            source_kind="appended_candidate",
            derived_from="pcv_" + "1" * 24,
        )
        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "candidate append was rejected",
        ):
            drama_assets.append_prop_or_clue_asset_version(
                catalog,
                asset_id="p001",
                version=orphan,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "version build was rejected",
        ):
            drama_assets.build_prop_or_clue_asset_version(
                asset_id="p001",
                spec=_spec("clue"),
                source_kind="appended_candidate",
                derived_from=prop.asset_version_id,
            )

    def test_explicit_empty_fields_cycle_and_artifact_path_reuse_fail_closed(self) -> None:
        empty = drama_assets.build_empty_prop_or_clue_asset_catalog()
        raw_empty = model_to_dict(empty)
        del raw_empty["assets"]
        with self.assertRaises(ValidationError):
            PropOrClueAssetCatalog(**raw_empty)
        with self.assertRaises(ValidationError):
            ShotPropOrClueRefs(
                shot_id="shot_" + "1" * 24,
                source_fingerprint="2" * 64,
            )

        first = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(),
            source_kind="identity_snapshot",
            artifact={
                "path": "data/prop_clue_refs/p001/ref.png",
                "sha256": "1" * 64,
                "size_bytes": 10,
            },
        )
        second = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec=_spec(state_label="停走"),
            source_kind="appended_candidate",
            derived_from=first.asset_version_id,
            artifact={
                "path": "data/prop_clue_refs/p001/ref.png",
                "sha256": "2" * 64,
                "size_bytes": 11,
            },
        )
        catalog = drama_assets.add_prop_or_clue_asset(
            empty,
            version=first,
            expected_catalog_fingerprint=empty.catalog_fingerprint,
        )
        with self.assertRaisesRegex(
            drama_assets.PropOrClueAssetError,
            "candidate append was rejected",
        ):
            drama_assets.append_prop_or_clue_asset_version(
                catalog,
                asset_id="p001",
                version=second,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )

        first_id = "pcv_" + "a" * 24
        second_id = "pcv_" + "b" * 24
        cyclic_first = first.model_copy(
            update={"asset_version_id": first_id, "derived_from": second_id}
        )
        cyclic_second = second.model_copy(
            update={"asset_version_id": second_id, "derived_from": first_id}
        )
        with self.assertRaises(ValidationError):
            PropOrClueAsset(
                asset_id="p001",
                kind="prop",
                versions=[cyclic_first, cyclic_second],
                selected_version_id=first_id,
                selection_revision=0,
            )

    def test_public_errors_redact_private_inputs_without_exception_chain(self) -> None:
        secret = "SECRET_PROP_TOKEN_110"
        with self.assertRaises(drama_assets.PropOrClueAssetError) as caught:
            drama_assets.build_prop_or_clue_asset_version(
                asset_id="p001",
                spec={**_spec(), "visual_tokens": [secret, secret]},
                source_kind="identity_snapshot",
                artifact={
                    "path": "data/prop_clue_refs/p001/SECRET_PATH.png",
                    "sha256": "1" * 64,
                    "size_bytes": 1,
                },
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn("SECRET_PATH", rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_catalog_json_is_finite_and_deterministic(self) -> None:
        first = drama_assets.build_empty_prop_or_clue_asset_catalog()
        second = drama_assets.build_empty_prop_or_clue_asset_catalog()
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(model_to_dict(first), sort_keys=True, allow_nan=False),
            json.dumps(model_to_dict(second), sort_keys=True, allow_nan=False),
        )


if __name__ == "__main__":
    unittest.main()
