"""iter107: pure character asset schemas and projections."""

from __future__ import annotations

from copy import deepcopy
import unittest

from pydantic import ValidationError

from src.drama_assets import (
    append_asset_version,
    build_asset_version,
    build_character_asset_catalog,
    build_episode_asset_manifest,
    select_asset_version,
)
from src.drama_schemas import (
    AssetArtifact,
    AssetVersion,
    CharacterAsset,
    CharacterAssetCatalog,
    EpisodeAssetManifest,
    RenderPlan,
    _canonical_sha256,
)
from src.schemas import model_to_dict


def _sheet() -> dict:
    return {
        "schema_version": 1,
        "season_no": 1,
        "episode_no": 1,
        "generated_episode_nos": [1],
        "track": "霸总",
        "source_storyboard_title": "测试",
        "characters": [
            {
                "id": "c001",
                "name": "甲",
                "role": "主角",
                "lora_token": "hero_a",
                "visual_signature": "黑发",
                "prompt_template_sd": "private prompt is hashed, not copied",
                "reference_images": [
                    {"path": "data/character_refs/c001/a.svg"},
                    {"path": "data/character_refs/c001/b.svg"},
                ],
                "appearances": [1],
                "manual_override": True,
                "agent_suggestions": [{"field": "wardrobe"}],
            },
            {
                "id": "c002",
                "name": "乙",
                "role": "配角",
                "lora_token": "support_b",
                "visual_signature": "短发",
                "reference_images": [],
                "appearances": [1],
            },
        ],
    }


def _artifacts() -> dict:
    return {
        "data/character_refs/c001/a.svg": {
            "path": "data/character_refs/c001/a.svg",
            "sha256": "a" * 64,
            "size_bytes": 10,
        },
        "data/character_refs/c001/b.svg": {
            "path": "data/character_refs/c001/b.svg",
            "sha256": "b" * 64,
            "size_bytes": 11,
        },
    }


def _render_plan(catalog: CharacterAssetCatalog) -> RenderPlan:
    from src.drama_schemas import _canonical_sha256

    shot = {
        "shot_id": "shot_" + "1" * 24,
        "source_shot_no": 1,
        "source_fingerprint": "2" * 64,
        "beat": "",
        "shot_size": "近景",
        "camera_movement": "固定",
        "target_duration_seconds": 3,
        "visual_action": "人物出现",
        "image_prompt": "",
        "transition_hint": "",
        "spoken_segment_ids": [],
        "audio_policy": "silent",
        "is_highlight": False,
        "source_event_ids": [],
    }
    payload = {
        "schema_version": 1,
        "generator_version": "render-plan-v1",
        "season_no": catalog.season_no,
        "episode_no": 1,
        "title": "测试",
        "target_duration_seconds": 60,
        "creative_revision": "3" * 64,
        "creative_revision_version": 2,
        "creative_fingerprint": "4" * 64,
        "source_episode_sha256": "5" * 64,
        "frozen_character_ids": ["c001", "c002"],
        "character_projection_fingerprint": "6" * 64,
        "art_direction_ref": None,
        "shots": [shot],
        "spoken_segments": [],
        "source_event_ids": [],
    }
    payload["plan_fingerprint"] = _canonical_sha256(payload)
    return RenderPlan(**payload)


def test_catalog_migrates_legacy_order_and_metadata_only_without_source_mutation() -> None:
    source = _sheet()
    before = deepcopy(source)
    catalog = build_character_asset_catalog(source, artifact_records=_artifacts())

    assert source == before
    assert [asset.asset_id for asset in catalog.assets] == ["c001", "c002"]
    first, second = catalog.assets
    assert len(first.versions) == 2
    assert first.selected_version_id == first.versions[0].asset_version_id
    assert first.selection_revision == 0
    assert first.versions[0].artifact.path.endswith("a.svg")
    assert second.versions[0].source_kind == "identity_snapshot"
    assert second.versions[0].artifact is None
    dumped = model_to_dict(catalog)
    assert "private prompt" not in str(dumped)
    assert catalog == build_character_asset_catalog(source, artifact_records=_artifacts())


def test_refresh_appends_new_identity_candidate_without_changing_selection() -> None:
    source = _sheet()
    catalog = build_character_asset_catalog(source, artifact_records=_artifacts())
    old_selected = catalog.assets[0].selected_version_id
    source["characters"][0]["visual_signature"] = "银发"
    refreshed = build_character_asset_catalog(
        source,
        artifact_records=_artifacts(),
        previous=catalog,
    )
    assert len(refreshed.assets[0].versions) == 4
    assert refreshed.assets[0].selected_version_id == old_selected
    assert refreshed.assets[0].selection_revision == 0


def test_append_and_select_are_immutable_and_cas_guarded() -> None:
    catalog = build_character_asset_catalog(_sheet(), artifact_records=_artifacts())
    asset = catalog.assets[0]
    candidate = build_asset_version(
        asset_id=asset.asset_id,
        identity_fingerprint=asset.identity_fingerprint,
        source_kind="appended_candidate",
        derived_from=asset.selected_version_id,
    )
    appended = append_asset_version(
        catalog,
        asset_id="c001",
        version=candidate,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
    )
    assert appended.assets[0].selected_version_id == asset.selected_version_id
    assert appended.assets[0].versions[:-1] == asset.versions
    assert append_asset_version(
        appended,
        asset_id="c001",
        version=candidate,
        expected_catalog_fingerprint=appended.catalog_fingerprint,
    ) == appended

    selected = select_asset_version(
        appended,
        asset_id="c001",
        asset_version_id=candidate.asset_version_id,
        expected_selection_revision=0,
        expected_selected_version_id=asset.selected_version_id,
    )
    assert selected.assets[0].selection_revision == 1
    assert selected.assets[0].selected_version_id == candidate.asset_version_id
    assert select_asset_version(
        selected,
        asset_id="c001",
        asset_version_id=candidate.asset_version_id,
        expected_selection_revision=1,
        expected_selected_version_id=candidate.asset_version_id,
    ) == selected
    try:
        select_asset_version(
            selected,
            asset_id="c001",
            asset_version_id=asset.selected_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=asset.selected_version_id,
        )
    except ValueError as exc:
        assert "selection changed" in str(exc)
    else:
        raise AssertionError("stale selection CAS must fail")


def test_episode_manifest_binds_only_active_selected_versions() -> None:
    catalog = build_character_asset_catalog(_sheet(), artifact_records=_artifacts())
    plan = _render_plan(catalog)
    manifest = build_episode_asset_manifest(plan, catalog)
    assert [ref.asset_id for ref in manifest.asset_refs] == ["c001", "c002"]
    assert manifest.asset_refs[0].artifact_sha256 == "a" * 64
    assert manifest.asset_refs[1].artifact_sha256 is None
    assert manifest.render_plan_fingerprint == plan.plan_fingerprint

    candidate = build_asset_version(
        asset_id=catalog.assets[0].asset_id,
        identity_fingerprint=catalog.assets[0].identity_fingerprint,
        source_kind="appended_candidate",
    )
    appended = append_asset_version(
        catalog,
        asset_id="c001",
        version=candidate,
        expected_catalog_fingerprint=catalog.catalog_fingerprint,
    )
    assert build_episode_asset_manifest(plan, appended) == manifest


def test_schema_rejects_tamper_extra_bool_and_cross_asset_parent() -> None:
    catalog = build_character_asset_catalog(_sheet(), artifact_records=_artifacts())
    raw = model_to_dict(catalog)
    raw["assets"][0]["selection_revision"] = True
    try:
        CharacterAssetCatalog(**raw)
    except ValidationError:
        pass
    else:
        raise AssertionError("bool selection revision must fail")

    raw = model_to_dict(catalog)
    raw["extra"] = "forbidden"
    try:
        CharacterAssetCatalog(**raw)
    except ValidationError:
        pass
    else:
        raise AssertionError("extra catalog member must fail")

    left = catalog.assets[0]
    right = catalog.assets[1]
    cross = build_asset_version(
        asset_id=left.asset_id,
        identity_fingerprint=left.identity_fingerprint,
        source_kind="appended_candidate",
        derived_from=right.selected_version_id,
    )
    try:
        CharacterAsset(
            asset_id=left.asset_id,
            identity_fingerprint=left.identity_fingerprint,
            versions=[*left.versions, cross],
            selected_version_id=left.selected_version_id,
            selection_revision=0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("cross-asset derived_from must fail")


def test_schema_rejects_content_address_tamper_duplicate_cycle_and_foreign_chain() -> None:
    catalog = build_character_asset_catalog(_sheet(), artifact_records=_artifacts())
    left, right = catalog.assets
    raw = model_to_dict(left.versions[0])
    raw["source_fingerprint"] = "f" * 64
    unsigned = dict(raw)
    unsigned.pop("asset_version_id")
    unsigned.pop("version_fingerprint")
    raw["version_fingerprint"] = _canonical_sha256(unsigned)
    raw["asset_version_id"] = f"av_{raw['version_fingerprint'][:24]}"
    try:
        AssetVersion(**raw)
    except ValidationError:
        pass
    else:
        raise AssertionError("forged source fingerprint must fail")

    try:
        CharacterAsset(
            asset_id=left.asset_id,
            identity_fingerprint=left.identity_fingerprint,
            versions=[left.versions[0], left.versions[0]],
            selected_version_id=left.selected_version_id,
            selection_revision=0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("duplicate asset versions must fail")

    v1 = AssetVersion.model_construct(
        asset_id=left.asset_id,
        asset_version_id="av_" + "1" * 24,
        version_fingerprint="1" * 64,
        derived_from="av_" + "2" * 24,
        source_kind="appended_candidate",
        identity_fingerprint=left.identity_fingerprint,
        source_fingerprint="2" * 64,
        artifact=None,
    )
    v2 = AssetVersion.model_construct(
        asset_id=left.asset_id,
        asset_version_id="av_" + "2" * 24,
        version_fingerprint="2" * 64,
        derived_from="av_" + "1" * 24,
        source_kind="appended_candidate",
        identity_fingerprint=left.identity_fingerprint,
        source_fingerprint="3" * 64,
        artifact=None,
    )
    try:
        CharacterAsset(
            asset_id=left.asset_id,
            identity_fingerprint=left.identity_fingerprint,
            versions=[v1, v2],
            selected_version_id=v1.asset_version_id,
            selection_revision=0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("derived-from cycle must fail")

    foreign = right.versions[0]
    child = build_asset_version(
        asset_id=left.asset_id,
        identity_fingerprint=left.identity_fingerprint,
        source_kind="appended_candidate",
        derived_from=foreign.asset_version_id,
    )
    try:
        CharacterAsset(
            asset_id=left.asset_id,
            identity_fingerprint=left.identity_fingerprint,
            versions=[*left.versions, foreign, child],
            selected_version_id=left.selected_version_id,
            selection_revision=0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("foreign parent and child injection must fail")


def test_schema_rejects_duplicate_manifest_refs_and_path_escape() -> None:
    catalog = build_character_asset_catalog(_sheet(), artifact_records=_artifacts())
    manifest = build_episode_asset_manifest(_render_plan(catalog), catalog)
    raw = model_to_dict(manifest)
    raw["asset_refs"] = [raw["asset_refs"][0], raw["asset_refs"][0]]
    raw["selection_fingerprint"] = _canonical_sha256(raw["asset_refs"])
    unsigned = dict(raw)
    unsigned.pop("manifest_fingerprint")
    raw["manifest_fingerprint"] = _canonical_sha256(unsigned)
    try:
        EpisodeAssetManifest(**raw)
    except ValidationError:
        pass
    else:
        raise AssertionError("duplicate episode asset refs must fail")

    for path in ("../secret.png", "/tmp/secret.png", "data/other/a.png"):
        try:
            AssetArtifact(path=path, sha256="a" * 64, size_bytes=1)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"asset path escape must fail: {path}")


class DramaAssetPureTests(unittest.TestCase):
    def test_catalog_migrates_legacy_order_and_metadata_only_without_source_mutation(self) -> None:
        test_catalog_migrates_legacy_order_and_metadata_only_without_source_mutation()

    def test_refresh_appends_new_identity_candidate_without_changing_selection(self) -> None:
        test_refresh_appends_new_identity_candidate_without_changing_selection()

    def test_append_and_select_are_immutable_and_cas_guarded(self) -> None:
        test_append_and_select_are_immutable_and_cas_guarded()

    def test_episode_manifest_binds_only_active_selected_versions(self) -> None:
        test_episode_manifest_binds_only_active_selected_versions()

    def test_schema_rejects_tamper_extra_bool_and_cross_asset_parent(self) -> None:
        test_schema_rejects_tamper_extra_bool_and_cross_asset_parent()

    def test_schema_rejects_content_address_tamper_duplicate_cycle_and_foreign_chain(self) -> None:
        test_schema_rejects_content_address_tamper_duplicate_cycle_and_foreign_chain()

    def test_schema_rejects_duplicate_manifest_refs_and_path_escape(self) -> None:
        test_schema_rejects_duplicate_manifest_refs_and_path_escape()
