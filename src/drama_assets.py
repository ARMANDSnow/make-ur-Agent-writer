"""Pure drama asset versioning and episode selection projections."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Mapping

from .drama_schemas import (
    ArtDirectionCatalog,
    ArtDirectionRef,
    ArtDirectionSpec,
    ArtDirectionVersion,
    AssetArtifact,
    AssetRef,
    AssetVersion,
    CharacterAsset,
    CharacterAssetCatalog,
    CharacterSheet,
    DramaCharacter,
    EpisodeAssetManifest,
    EpisodePropOrClueAssetManifest,
    EpisodeSceneAssetManifest,
    PropOrClueArtifact,
    PropOrClueAsset,
    PropOrClueAssetCatalog,
    PropOrClueAssetRef,
    PropOrClueAssetVersion,
    PropOrClueSpec,
    RenderPlan,
    SceneAsset,
    SceneAssetArtifact,
    SceneAssetCatalog,
    SceneAssetRef,
    SceneAssetVersion,
    SceneSpec,
    ShotPropOrClueRefs,
    ShotSceneRef,
)
from .schemas import model_to_dict


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(data: Any) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_art_direction_version(
    *,
    art_direction_id: str,
    spec: ArtDirectionSpec | Dict[str, Any],
    source_kind: str,
    derived_from: str | None = None,
) -> ArtDirectionVersion:
    """Build one immutable local candidate without calling a provider."""

    validated_spec = spec if isinstance(spec, ArtDirectionSpec) else ArtDirectionSpec(**spec)
    payload: Dict[str, Any] = {
        "art_direction_id": art_direction_id,
        "derived_from": derived_from,
        "source_kind": source_kind,
        "spec": model_to_dict(validated_spec),
    }
    fingerprint = _sha256(payload)
    return ArtDirectionVersion(
        version_id=f"ad_{fingerprint[:24]}",
        version_fingerprint=fingerprint,
        **payload,
    )


def _art_direction_catalog_from_payload(
    payload: Dict[str, Any],
) -> ArtDirectionCatalog:
    data = dict(payload)
    data["catalog_fingerprint"] = _sha256(data)
    return ArtDirectionCatalog(**data)


def build_art_direction_catalog(
    version: ArtDirectionVersion | Dict[str, Any],
    *,
    season_no: int = 1,
) -> ArtDirectionCatalog:
    """Create a catalog whose initial candidate is explicitly selected."""

    candidate = (
        version if isinstance(version, ArtDirectionVersion) else ArtDirectionVersion(**version)
    )
    return _art_direction_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": season_no,
            "art_direction_id": candidate.art_direction_id,
            "versions": [model_to_dict(candidate)],
            "selected_version_id": candidate.version_id,
            "selection_revision": 0,
        }
    )


def append_art_direction_version(
    catalog: ArtDirectionCatalog | Dict[str, Any],
    *,
    version: ArtDirectionVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> ArtDirectionCatalog:
    """Append one candidate under whole-catalog CAS without selecting it."""

    current = (
        catalog if isinstance(catalog, ArtDirectionCatalog) else ArtDirectionCatalog(**catalog)
    )
    candidate = (
        version if isinstance(version, ArtDirectionVersion) else ArtDirectionVersion(**version)
    )
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("art direction catalog changed; refresh before append")
    if candidate.art_direction_id != current.art_direction_id:
        raise ValueError("art direction version belongs to another catalog")
    by_id = {item.version_id: item for item in current.versions}
    existing = by_id.get(candidate.version_id)
    if existing is not None:
        if existing != candidate:
            raise ValueError("content-addressed art direction version conflicts")
        return current
    if candidate.derived_from is not None and candidate.derived_from not in by_id:
        raise ValueError("derived art direction version does not exist")
    return _art_direction_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "art_direction_id": current.art_direction_id,
            "versions": [
                *[model_to_dict(item) for item in current.versions],
                model_to_dict(candidate),
            ],
            "selected_version_id": current.selected_version_id,
            "selection_revision": current.selection_revision,
        }
    )


def select_art_direction_version(
    catalog: ArtDirectionCatalog | Dict[str, Any],
    *,
    version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> ArtDirectionCatalog:
    """Select an existing candidate under revision/current-id double CAS."""

    if not isinstance(expected_selection_revision, int) or isinstance(
        expected_selection_revision, bool
    ):
        raise ValueError("expected art direction selection revision must be strict")
    current = (
        catalog if isinstance(catalog, ArtDirectionCatalog) else ArtDirectionCatalog(**catalog)
    )
    if (
        current.selection_revision != expected_selection_revision
        or current.selected_version_id != expected_selected_version_id
    ):
        raise ValueError("art direction selection changed; refresh before selecting")
    if version_id not in {item.version_id for item in current.versions}:
        raise ValueError("art direction version does not exist")
    if version_id == current.selected_version_id:
        return current
    return _art_direction_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "art_direction_id": current.art_direction_id,
            "versions": [model_to_dict(item) for item in current.versions],
            "selected_version_id": version_id,
            "selection_revision": current.selection_revision + 1,
        }
    )


def selected_art_direction_ref(
    catalog: ArtDirectionCatalog | Dict[str, Any],
) -> ArtDirectionRef:
    """Freeze the selected version into the existing RenderPlan v1 ref shape."""

    current = (
        catalog if isinstance(catalog, ArtDirectionCatalog) else ArtDirectionCatalog(**catalog)
    )
    selected = next(
        item for item in current.versions if item.version_id == current.selected_version_id
    )
    return ArtDirectionRef(
        art_direction_id=current.art_direction_id,
        version_id=selected.version_id,
        fingerprint=selected.version_fingerprint,
    )


def character_render_identity(
    character: DramaCharacter | Dict[str, Any],
) -> Dict[str, Any]:
    """Return only fields that define the character's reusable render identity."""

    validated = (
        character
        if isinstance(character, DramaCharacter)
        else DramaCharacter(**character)
    )
    payload = model_to_dict(validated)
    for field in (
        "reference_images",
        "appearances",
        "manual_override",
        "agent_suggestions",
    ):
        payload.pop(field, None)
    return payload


def character_render_identity_fingerprint(
    character: DramaCharacter | Dict[str, Any],
) -> str:
    return _sha256(character_render_identity(character))


def build_asset_version(
    *,
    asset_id: str,
    identity_fingerprint: str,
    source_kind: str,
    artifact: AssetArtifact | Dict[str, Any] | None = None,
    derived_from: str | None = None,
) -> AssetVersion:
    """Build one immutable version; no prompt or provider response is accepted."""

    if not isinstance(identity_fingerprint, str) or _SHA256_RE.fullmatch(
        identity_fingerprint
    ) is None:
        raise ValueError("asset identity fingerprint is invalid")
    artifact_model = None
    if artifact is not None:
        artifact_model = (
            artifact if isinstance(artifact, AssetArtifact) else AssetArtifact(**artifact)
        )
    source_payload = {
        "asset_id": asset_id,
        "identity_fingerprint": identity_fingerprint,
        "source_kind": source_kind,
        "artifact": model_to_dict(artifact_model) if artifact_model is not None else None,
    }
    payload: Dict[str, Any] = {
        "asset_id": asset_id,
        "derived_from": derived_from,
        "source_kind": source_kind,
        "identity_fingerprint": identity_fingerprint,
        "source_fingerprint": _sha256(source_payload),
        "artifact": model_to_dict(artifact_model) if artifact_model is not None else None,
    }
    fingerprint = _sha256(payload)
    return AssetVersion(
        asset_version_id=f"av_{fingerprint[:24]}",
        version_fingerprint=fingerprint,
        **payload,
    )


def _candidate_versions(
    character: DramaCharacter,
    artifact_records: Mapping[str, AssetArtifact | Dict[str, Any]],
) -> tuple[str, list[AssetVersion]]:
    identity_fingerprint = character_render_identity_fingerprint(character)
    if not character.reference_images:
        return identity_fingerprint, [
            build_asset_version(
                asset_id=character.id,
                identity_fingerprint=identity_fingerprint,
                source_kind="identity_snapshot",
            )
        ]

    versions: list[AssetVersion] = []
    seen_paths: set[str] = set()
    for reference in character.reference_images:
        if reference.path in seen_paths:
            raise ValueError("character reference image paths must be unique")
        seen_paths.add(reference.path)
        raw_artifact = artifact_records.get(reference.path)
        if raw_artifact is None:
            raise ValueError("character reference image has no verified artifact record")
        artifact = (
            raw_artifact
            if isinstance(raw_artifact, AssetArtifact)
            else AssetArtifact(**raw_artifact)
        )
        if artifact.path != reference.path:
            raise ValueError("character reference artifact path is inconsistent")
        versions.append(
            build_asset_version(
                asset_id=character.id,
                identity_fingerprint=identity_fingerprint,
                source_kind="legacy_reference",
                artifact=artifact,
            )
        )
    return identity_fingerprint, versions


def _catalog_from_payload(payload: Dict[str, Any]) -> CharacterAssetCatalog:
    data = dict(payload)
    data["catalog_fingerprint"] = _sha256(data)
    return CharacterAssetCatalog(**data)


def build_character_asset_catalog(
    character_sheet: CharacterSheet | Dict[str, Any],
    *,
    artifact_records: Mapping[str, AssetArtifact | Dict[str, Any]],
    previous: CharacterAssetCatalog | Dict[str, Any] | None = None,
) -> CharacterAssetCatalog:
    """Build or refresh a catalog without mutating source or prior versions."""

    sheet = (
        character_sheet
        if isinstance(character_sheet, CharacterSheet)
        else CharacterSheet(**character_sheet)
    )
    prior = None
    if previous is not None:
        prior = (
            previous
            if isinstance(previous, CharacterAssetCatalog)
            else CharacterAssetCatalog(**previous)
        )
        if prior.season_no != sheet.season_no:
            raise ValueError("character asset catalog belongs to another season")

    prior_by_id = {asset.asset_id: asset for asset in prior.assets} if prior else {}
    current_ids = {character.id for character in sheet.characters}
    removed_ids = set(prior_by_id) - current_ids
    if removed_ids:
        raise ValueError("character assets cannot be removed by catalog refresh")

    assets: list[CharacterAsset] = []
    source_rows: list[Dict[str, Any]] = []
    for character in sheet.characters:
        identity_fingerprint, candidates = _candidate_versions(
            character,
            artifact_records,
        )
        source_rows.append(
            {
                "asset_id": character.id,
                "identity_fingerprint": identity_fingerprint,
                "candidate_version_ids": [item.asset_version_id for item in candidates],
            }
        )
        existing = prior_by_id.get(character.id)
        if existing is None:
            versions = candidates
            selected_version_id = versions[0].asset_version_id
            selection_revision = 0
        else:
            versions = list(existing.versions)
            known = {item.asset_version_id: item for item in versions}
            for candidate in candidates:
                old = known.get(candidate.asset_version_id)
                if old is not None:
                    if old != candidate:
                        raise ValueError("content-addressed asset version conflicts")
                    continue
                versions.append(candidate)
                known[candidate.asset_version_id] = candidate
            selected_version_id = existing.selected_version_id
            selection_revision = existing.selection_revision
        assets.append(
            CharacterAsset(
                asset_id=character.id,
                identity_fingerprint=identity_fingerprint,
                versions=versions,
                selected_version_id=selected_version_id,
                selection_revision=selection_revision,
            )
        )

    source_fingerprint = _sha256(
        {
            "schema_version": 1,
            "season_no": sheet.season_no,
            "characters": source_rows,
        }
    )
    return _catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": sheet.season_no,
            "source_fingerprint": source_fingerprint,
            "assets": [model_to_dict(item) for item in assets],
        }
    )


def append_asset_version(
    catalog: CharacterAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    version: AssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> CharacterAssetCatalog:
    """Append an exact version under catalog-fingerprint CAS."""

    current = (
        catalog
        if isinstance(catalog, CharacterAssetCatalog)
        else CharacterAssetCatalog(**catalog)
    )
    candidate = version if isinstance(version, AssetVersion) else AssetVersion(**version)
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("character asset catalog changed; refresh before append")

    output: list[CharacterAsset] = []
    found = False
    for asset in current.assets:
        if asset.asset_id != asset_id:
            output.append(asset)
            continue
        found = True
        if candidate.identity_fingerprint != asset.identity_fingerprint:
            raise ValueError("asset version identity does not match the character")
        if candidate.asset_id != asset.asset_id:
            raise ValueError("asset version belongs to another character")
        by_id = {item.asset_version_id: item for item in asset.versions}
        existing = by_id.get(candidate.asset_version_id)
        if existing is not None:
            if existing != candidate:
                raise ValueError("content-addressed asset version conflicts")
            return current
        output.append(
            CharacterAsset(
                asset_id=asset.asset_id,
                identity_fingerprint=asset.identity_fingerprint,
                versions=[*asset.versions, candidate],
                selected_version_id=asset.selected_version_id,
                selection_revision=asset.selection_revision,
            )
        )
    if not found:
        raise ValueError("character asset does not exist")
    return _catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "source_fingerprint": current.source_fingerprint,
            "assets": [model_to_dict(item) for item in output],
        }
    )


def select_asset_version(
    catalog: CharacterAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    asset_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> CharacterAssetCatalog:
    """Select one existing version under per-character revision/current-id CAS."""

    if not isinstance(expected_selection_revision, int) or isinstance(
        expected_selection_revision, bool
    ):
        raise ValueError("expected selection revision must be a strict integer")
    current = (
        catalog
        if isinstance(catalog, CharacterAssetCatalog)
        else CharacterAssetCatalog(**catalog)
    )
    output: list[CharacterAsset] = []
    found = False
    for asset in current.assets:
        if asset.asset_id != asset_id:
            output.append(asset)
            continue
        found = True
        if (
            asset.selection_revision != expected_selection_revision
            or asset.selected_version_id != expected_selected_version_id
        ):
            raise ValueError("character asset selection changed; refresh before selecting")
        if asset_version_id not in {
            version.asset_version_id for version in asset.versions
        }:
            raise ValueError("selected asset version does not exist for this character")
        if asset.selected_version_id == asset_version_id:
            return current
        output.append(
            CharacterAsset(
                asset_id=asset.asset_id,
                identity_fingerprint=asset.identity_fingerprint,
                versions=asset.versions,
                selected_version_id=asset_version_id,
                selection_revision=asset.selection_revision + 1,
            )
        )
    if not found:
        raise ValueError("character asset does not exist")
    return _catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "source_fingerprint": current.source_fingerprint,
            "assets": [model_to_dict(item) for item in output],
        }
    )


def build_episode_asset_manifest(
    render_plan: RenderPlan | Dict[str, Any],
    catalog: CharacterAssetCatalog | Dict[str, Any],
) -> EpisodeAssetManifest:
    """Freeze selected character versions for exactly one RenderPlan cast."""

    plan = render_plan if isinstance(render_plan, RenderPlan) else RenderPlan(**render_plan)
    current = (
        catalog
        if isinstance(catalog, CharacterAssetCatalog)
        else CharacterAssetCatalog(**catalog)
    )
    if current.season_no != plan.season_no:
        raise ValueError("character asset catalog belongs to another season")
    by_id = {asset.asset_id: asset for asset in current.assets}
    refs: list[AssetRef] = []
    for asset_id in plan.frozen_character_ids:
        asset = by_id.get(asset_id)
        if asset is None:
            raise ValueError("frozen character has no asset entry")
        selected = next(
            (
                version
                for version in asset.versions
                if version.asset_version_id == asset.selected_version_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("frozen character selection is invalid")
        refs.append(
            AssetRef(
                asset_id=asset_id,
                asset_version_id=selected.asset_version_id,
                version_fingerprint=selected.version_fingerprint,
                artifact_sha256=(
                    selected.artifact.sha256 if selected.artifact is not None else None
                ),
            )
        )
    selection_fingerprint = _sha256([model_to_dict(ref) for ref in refs])
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "selection_fingerprint": selection_fingerprint,
        "asset_refs": [model_to_dict(ref) for ref in refs],
    }
    payload["manifest_fingerprint"] = _sha256(payload)
    return EpisodeAssetManifest(**payload)


def _build_scene_asset_version_impl(
    *,
    scene_id: str,
    spec: SceneSpec | Dict[str, Any],
    source_kind: str,
    artifact: SceneAssetArtifact | Dict[str, Any] | None = None,
    derived_from: str | None = None,
) -> SceneAssetVersion:
    """Build one immutable local scene candidate without network access."""

    validated_spec = spec if isinstance(spec, SceneSpec) else SceneSpec(**spec)
    validated_artifact = None
    if artifact is not None:
        validated_artifact = (
            artifact
            if isinstance(artifact, SceneAssetArtifact)
            else SceneAssetArtifact(**artifact)
        )
    source_payload = {
        "scene_id": scene_id,
        "source_kind": source_kind,
        "spec": model_to_dict(validated_spec),
        "artifact": (
            model_to_dict(validated_artifact)
            if validated_artifact is not None
            else None
        ),
    }
    payload: Dict[str, Any] = {
        "scene_id": scene_id,
        "derived_from": derived_from,
        "source_kind": source_kind,
        "source_fingerprint": _sha256(source_payload),
        "spec": model_to_dict(validated_spec),
        "artifact": (
            model_to_dict(validated_artifact)
            if validated_artifact is not None
            else None
        ),
    }
    fingerprint = _sha256(payload)
    return SceneAssetVersion(
        scene_version_id=f"sv_{fingerprint[:24]}",
        version_fingerprint=fingerprint,
        **payload,
    )


def _scene_catalog_from_payload(payload: Dict[str, Any]) -> SceneAssetCatalog:
    data = dict(payload)
    data["catalog_fingerprint"] = _sha256(data)
    return SceneAssetCatalog(**data)


def _build_scene_asset_catalog_impl(
    version: SceneAssetVersion | Dict[str, Any],
    *,
    season_no: int = 1,
) -> SceneAssetCatalog:
    """Create a catalog whose first scene candidate is explicitly selected."""

    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    if candidate.derived_from is not None:
        raise ValueError("initial scene version cannot derive from an absent version")
    return _scene_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": season_no,
            "assets": [
                {
                    "scene_id": candidate.scene_id,
                    "versions": [model_to_dict(candidate)],
                    "selected_version_id": candidate.scene_version_id,
                    "selection_revision": 0,
                }
            ],
        }
    )


def _add_scene_asset_impl(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> SceneAssetCatalog:
    """Add a new semantic scene under whole-catalog CAS."""

    current = (
        catalog if isinstance(catalog, SceneAssetCatalog) else SceneAssetCatalog(**catalog)
    )
    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("scene asset catalog changed; refresh before adding")
    if candidate.derived_from is not None:
        raise ValueError("initial scene version cannot derive from another scene")
    existing = next(
        (asset for asset in current.assets if asset.scene_id == candidate.scene_id),
        None,
    )
    if existing is not None:
        if (
            len(existing.versions) == 1
            and existing.versions[0] == candidate
            and existing.selected_version_id == candidate.scene_version_id
            and existing.selection_revision == 0
        ):
            return current
        raise ValueError("scene asset already exists")
    return _scene_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [
                *[model_to_dict(asset) for asset in current.assets],
                {
                    "scene_id": candidate.scene_id,
                    "versions": [model_to_dict(candidate)],
                    "selected_version_id": candidate.scene_version_id,
                    "selection_revision": 0,
                },
            ],
        }
    )


def _append_scene_asset_version_impl(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    scene_id: str,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> SceneAssetCatalog:
    """Append one scene candidate without changing the selected version."""

    current = (
        catalog if isinstance(catalog, SceneAssetCatalog) else SceneAssetCatalog(**catalog)
    )
    candidate = (
        version
        if isinstance(version, SceneAssetVersion)
        else SceneAssetVersion(**version)
    )
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("scene asset catalog changed; refresh before append")
    output: list[SceneAsset] = []
    found = False
    for asset in current.assets:
        if asset.scene_id != scene_id:
            output.append(asset)
            continue
        found = True
        if candidate.scene_id != asset.scene_id:
            raise ValueError("scene version belongs to another scene")
        by_id = {item.scene_version_id: item for item in asset.versions}
        existing = by_id.get(candidate.scene_version_id)
        if existing is not None:
            if existing != candidate:
                raise ValueError("content-addressed scene version conflicts")
            return current
        if candidate.derived_from is not None and candidate.derived_from not in by_id:
            raise ValueError("derived scene version does not exist")
        output.append(
            SceneAsset(
                scene_id=asset.scene_id,
                versions=[*asset.versions, candidate],
                selected_version_id=asset.selected_version_id,
                selection_revision=asset.selection_revision,
            )
        )
    if not found:
        raise ValueError("scene asset does not exist")
    return _scene_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [model_to_dict(asset) for asset in output],
        }
    )


def _select_scene_asset_version_impl(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    scene_id: str,
    scene_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> SceneAssetCatalog:
    """Select a scene candidate under revision/current-id double CAS."""

    if not isinstance(expected_selection_revision, int) or isinstance(
        expected_selection_revision, bool
    ):
        raise ValueError("expected scene selection revision must be a strict integer")
    current = (
        catalog if isinstance(catalog, SceneAssetCatalog) else SceneAssetCatalog(**catalog)
    )
    output: list[SceneAsset] = []
    found = False
    for asset in current.assets:
        if asset.scene_id != scene_id:
            output.append(asset)
            continue
        found = True
        if (
            asset.selection_revision != expected_selection_revision
            or asset.selected_version_id != expected_selected_version_id
        ):
            raise ValueError("scene asset selection changed; refresh before selecting")
        if scene_version_id not in {
            version.scene_version_id for version in asset.versions
        }:
            raise ValueError("selected scene version does not exist")
        if scene_version_id == asset.selected_version_id:
            return current
        output.append(
            SceneAsset(
                scene_id=asset.scene_id,
                versions=asset.versions,
                selected_version_id=scene_version_id,
                selection_revision=asset.selection_revision + 1,
            )
        )
    if not found:
        raise ValueError("scene asset does not exist")
    return _scene_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [model_to_dict(asset) for asset in output],
        }
    )


def _selected_scene_asset_ref_impl(asset: SceneAsset | Dict[str, Any]) -> SceneAssetRef:
    current = asset if isinstance(asset, SceneAsset) else SceneAsset(**asset)
    selected = next(
        item
        for item in current.versions
        if item.scene_version_id == current.selected_version_id
    )
    return SceneAssetRef(
        scene_id=current.scene_id,
        scene_version_id=selected.scene_version_id,
        version_fingerprint=selected.version_fingerprint,
        artifact_sha256=(
            selected.artifact.sha256 if selected.artifact is not None else None
        ),
    )


def _build_episode_scene_asset_manifest_impl(
    render_plan: RenderPlan | Dict[str, Any],
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    shot_scene_ids: Mapping[str, str],
    binding_revision: int = 0,
) -> EpisodeSceneAssetManifest:
    """Freeze explicit stable-shot scene bindings against current selections."""

    if not isinstance(shot_scene_ids, Mapping):
        raise ValueError("shot_scene_ids must be an explicit mapping")
    if not isinstance(binding_revision, int) or isinstance(binding_revision, bool):
        raise ValueError("binding revision must be a strict integer")
    if any(
        not isinstance(shot_id, str) or not isinstance(scene_id, str)
        for shot_id, scene_id in shot_scene_ids.items()
    ):
        raise ValueError("shot_scene_ids must contain string ids")
    plan = render_plan if isinstance(render_plan, RenderPlan) else RenderPlan(**render_plan)
    current = (
        catalog if isinstance(catalog, SceneAssetCatalog) else SceneAssetCatalog(**catalog)
    )
    if current.season_no != plan.season_no:
        raise ValueError("scene asset catalog belongs to another season")
    required_shots = [shot.shot_id for shot in plan.shots]
    if set(shot_scene_ids) != set(required_shots) or len(shot_scene_ids) != len(
        required_shots
    ):
        raise ValueError("every render shot must have exactly one explicit scene binding")
    assets = {asset.scene_id: asset for asset in current.assets}
    refs: list[ShotSceneRef] = []
    for shot in plan.shots:
        scene_id = shot_scene_ids[shot.shot_id]
        asset = assets.get(scene_id)
        if asset is None:
            raise ValueError("scene binding references an unknown scene")
        refs.append(
            ShotSceneRef(
                shot_id=shot.shot_id,
                source_fingerprint=shot.source_fingerprint,
                scene_ref=_selected_scene_asset_ref_impl(asset),
            )
        )
    usage_fingerprint = _sha256([model_to_dict(ref) for ref in refs])
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "binding_revision": binding_revision,
        "usage_fingerprint": usage_fingerprint,
        "shot_scene_refs": [model_to_dict(ref) for ref in refs],
    }
    payload["manifest_fingerprint"] = _sha256(payload)
    return EpisodeSceneAssetManifest(**payload)


def _scene_usage_index_impl(
    manifest: EpisodeSceneAssetManifest | Dict[str, Any],
) -> Dict[str, list[str]]:
    """Derive bounded episode-level used-by without scanning other workspaces."""

    current = (
        manifest
        if isinstance(manifest, EpisodeSceneAssetManifest)
        else EpisodeSceneAssetManifest(**manifest)
    )
    output: Dict[str, list[str]] = {}
    for binding in current.shot_scene_refs:
        output.setdefault(binding.scene_ref.scene_id, []).append(binding.shot_id)
    return output


class SceneAssetError(ValueError):
    """Bounded public error for local scene-asset pure operations."""


def _raise_scene_asset_error(operation: str) -> None:
    # Raise outside an active exception handler so private caller input is absent
    # from both the public message and the exception chain.
    raise SceneAssetError(f"scene asset {operation} was rejected")


def build_scene_asset_version(
    *,
    scene_id: str,
    spec: SceneSpec | Dict[str, Any],
    source_kind: str,
    artifact: SceneAssetArtifact | Dict[str, Any] | None = None,
    derived_from: str | None = None,
) -> SceneAssetVersion:
    try:
        return _build_scene_asset_version_impl(
            scene_id=scene_id,
            spec=spec,
            source_kind=source_kind,
            artifact=artifact,
            derived_from=derived_from,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("version build")


def build_scene_asset_catalog(
    version: SceneAssetVersion | Dict[str, Any],
    *,
    season_no: int = 1,
) -> SceneAssetCatalog:
    try:
        return _build_scene_asset_catalog_impl(version, season_no=season_no)
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("catalog build")


def add_scene_asset(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> SceneAssetCatalog:
    try:
        return _add_scene_asset_impl(
            catalog,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("addition")


def append_scene_asset_version(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    scene_id: str,
    version: SceneAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> SceneAssetCatalog:
    try:
        return _append_scene_asset_version_impl(
            catalog,
            scene_id=scene_id,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("candidate append")


def select_scene_asset_version(
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    scene_id: str,
    scene_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> SceneAssetCatalog:
    try:
        return _select_scene_asset_version_impl(
            catalog,
            scene_id=scene_id,
            scene_version_id=scene_version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("selection")


def selected_scene_asset_ref(asset: SceneAsset | Dict[str, Any]) -> SceneAssetRef:
    try:
        return _selected_scene_asset_ref_impl(asset)
    except (RecursionError, StopIteration, TypeError, ValueError):
        pass
    _raise_scene_asset_error("reference build")


def build_episode_scene_asset_manifest(
    render_plan: RenderPlan | Dict[str, Any],
    catalog: SceneAssetCatalog | Dict[str, Any],
    *,
    shot_scene_ids: Mapping[str, str],
    binding_revision: int = 0,
) -> EpisodeSceneAssetManifest:
    try:
        return _build_episode_scene_asset_manifest_impl(
            render_plan,
            catalog,
            shot_scene_ids=shot_scene_ids,
            binding_revision=binding_revision,
        )
    except (KeyError, RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("manifest build")


def scene_usage_index(
    manifest: EpisodeSceneAssetManifest | Dict[str, Any],
) -> Dict[str, list[str]]:
    try:
        return _scene_usage_index_impl(manifest)
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_scene_asset_error("usage projection")


def _prop_clue_catalog_from_payload(
    payload: Dict[str, Any],
) -> PropOrClueAssetCatalog:
    data = dict(payload)
    data["catalog_fingerprint"] = _sha256(data)
    return PropOrClueAssetCatalog(**data)


def _build_empty_prop_or_clue_asset_catalog_impl(
    *,
    season_no: int = 1,
) -> PropOrClueAssetCatalog:
    return _prop_clue_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": season_no,
            "assets": [],
        }
    )


def _build_prop_or_clue_asset_version_impl(
    *,
    asset_id: str,
    spec: PropOrClueSpec | Dict[str, Any],
    source_kind: str,
    artifact: PropOrClueArtifact | Dict[str, Any] | None = None,
    derived_from: str | None = None,
) -> PropOrClueAssetVersion:
    """Build one immutable local prop/clue candidate without network access."""

    validated_spec = (
        spec if isinstance(spec, PropOrClueSpec) else PropOrClueSpec(**spec)
    )
    validated_artifact = None
    if artifact is not None:
        validated_artifact = (
            artifact
            if isinstance(artifact, PropOrClueArtifact)
            else PropOrClueArtifact(**artifact)
        )
    source_payload = {
        "asset_id": asset_id,
        "source_kind": source_kind,
        "spec": model_to_dict(validated_spec),
        "artifact": (
            model_to_dict(validated_artifact)
            if validated_artifact is not None
            else None
        ),
    }
    payload: Dict[str, Any] = {
        "asset_id": asset_id,
        "derived_from": derived_from,
        "source_kind": source_kind,
        "source_fingerprint": _sha256(source_payload),
        "spec": model_to_dict(validated_spec),
        "artifact": (
            model_to_dict(validated_artifact)
            if validated_artifact is not None
            else None
        ),
    }
    fingerprint = _sha256(payload)
    return PropOrClueAssetVersion(
        asset_version_id=f"pcv_{fingerprint[:24]}",
        version_fingerprint=fingerprint,
        **payload,
    )


def _add_prop_or_clue_asset_impl(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    version: PropOrClueAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> PropOrClueAssetCatalog:
    """Add a semantic prop/clue whose root candidate starts selected."""

    current = (
        catalog
        if isinstance(catalog, PropOrClueAssetCatalog)
        else PropOrClueAssetCatalog(**catalog)
    )
    candidate = (
        version
        if isinstance(version, PropOrClueAssetVersion)
        else PropOrClueAssetVersion(**version)
    )
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("prop/clue catalog changed; refresh before adding")
    if candidate.derived_from is not None:
        raise ValueError("initial prop/clue version cannot derive from another asset")
    existing = next(
        (asset for asset in current.assets if asset.asset_id == candidate.asset_id),
        None,
    )
    if existing is not None:
        if (
            candidate.derived_from is None
            and existing.versions[0] == candidate
        ):
            return current
        raise ValueError("prop/clue asset already exists")
    return _prop_clue_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [
                *[model_to_dict(asset) for asset in current.assets],
                {
                    "asset_id": candidate.asset_id,
                    "kind": candidate.spec.kind,
                    "versions": [model_to_dict(candidate)],
                    "selected_version_id": candidate.asset_version_id,
                    "selection_revision": 0,
                },
            ],
        }
    )


def _append_prop_or_clue_asset_version_impl(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    version: PropOrClueAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> PropOrClueAssetCatalog:
    """Append a prop/clue candidate without changing the selected version."""

    current = (
        catalog
        if isinstance(catalog, PropOrClueAssetCatalog)
        else PropOrClueAssetCatalog(**catalog)
    )
    candidate = (
        version
        if isinstance(version, PropOrClueAssetVersion)
        else PropOrClueAssetVersion(**version)
    )
    if expected_catalog_fingerprint != current.catalog_fingerprint:
        raise ValueError("prop/clue catalog changed; refresh before append")
    output: list[PropOrClueAsset] = []
    found = False
    for asset in current.assets:
        if asset.asset_id != asset_id:
            output.append(asset)
            continue
        found = True
        if candidate.asset_id != asset.asset_id or candidate.spec.kind != asset.kind:
            raise ValueError("prop/clue version belongs to another asset or kind")
        by_id = {item.asset_version_id: item for item in asset.versions}
        existing = by_id.get(candidate.asset_version_id)
        if existing is not None:
            if existing != candidate:
                raise ValueError("content-addressed prop/clue version conflicts")
            return current
        if candidate.derived_from is not None and candidate.derived_from not in by_id:
            raise ValueError("derived prop/clue version does not exist")
        output.append(
            PropOrClueAsset(
                asset_id=asset.asset_id,
                kind=asset.kind,
                versions=[*asset.versions, candidate],
                selected_version_id=asset.selected_version_id,
                selection_revision=asset.selection_revision,
            )
        )
    if not found:
        raise ValueError("prop/clue asset does not exist")
    return _prop_clue_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [model_to_dict(asset) for asset in output],
        }
    )


def _select_prop_or_clue_asset_version_impl(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    asset_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> PropOrClueAssetCatalog:
    """Select a prop/clue candidate under revision/current-id double CAS."""

    if not isinstance(expected_selection_revision, int) or isinstance(
        expected_selection_revision,
        bool,
    ):
        raise ValueError("expected prop/clue selection revision must be strict")
    current = (
        catalog
        if isinstance(catalog, PropOrClueAssetCatalog)
        else PropOrClueAssetCatalog(**catalog)
    )
    output: list[PropOrClueAsset] = []
    found = False
    for asset in current.assets:
        if asset.asset_id != asset_id:
            output.append(asset)
            continue
        found = True
        if (
            asset.selection_revision != expected_selection_revision
            or asset.selected_version_id != expected_selected_version_id
        ):
            raise ValueError("prop/clue selection changed; refresh before selecting")
        if asset_version_id not in {
            version.asset_version_id for version in asset.versions
        }:
            raise ValueError("selected prop/clue version does not exist")
        if asset_version_id == asset.selected_version_id:
            return current
        output.append(
            PropOrClueAsset(
                asset_id=asset.asset_id,
                kind=asset.kind,
                versions=asset.versions,
                selected_version_id=asset_version_id,
                selection_revision=asset.selection_revision + 1,
            )
        )
    if not found:
        raise ValueError("prop/clue asset does not exist")
    return _prop_clue_catalog_from_payload(
        {
            "schema_version": 1,
            "season_no": current.season_no,
            "assets": [model_to_dict(asset) for asset in output],
        }
    )


def _selected_prop_or_clue_asset_ref_impl(
    asset: PropOrClueAsset | Dict[str, Any],
) -> PropOrClueAssetRef:
    current = (
        asset if isinstance(asset, PropOrClueAsset) else PropOrClueAsset(**asset)
    )
    selected = next(
        item
        for item in current.versions
        if item.asset_version_id == current.selected_version_id
    )
    return PropOrClueAssetRef(
        kind=current.kind,
        asset_id=current.asset_id,
        asset_version_id=selected.asset_version_id,
        version_fingerprint=selected.version_fingerprint,
        artifact_sha256=(
            selected.artifact.sha256 if selected.artifact is not None else None
        ),
    )


def _build_episode_prop_or_clue_asset_manifest_impl(
    render_plan: RenderPlan | Dict[str, Any],
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    shot_asset_ids: Mapping[str, list[str]],
    binding_revision: int = 0,
) -> EpisodePropOrClueAssetManifest:
    """Freeze explicit stable-shot prop/clue bindings against selections."""

    if not isinstance(shot_asset_ids, Mapping):
        raise ValueError("shot_asset_ids must be an explicit mapping")
    if not isinstance(binding_revision, int) or isinstance(binding_revision, bool):
        raise ValueError("binding revision must be a strict integer")
    plan = render_plan if isinstance(render_plan, RenderPlan) else RenderPlan(**render_plan)
    required_shots = [shot.shot_id for shot in plan.shots]
    if len(shot_asset_ids) != len(required_shots):
        raise ValueError("every render shot must have an explicit prop/clue binding")
    normalized: Dict[str, list[str]] = {}
    for shot_id, asset_ids in shot_asset_ids.items():
        if len(normalized) >= len(required_shots):
            raise ValueError("shot_asset_ids contains too many entries")
        if not isinstance(shot_id, str) or not isinstance(asset_ids, list):
            raise ValueError("shot_asset_ids must map string ids to lists")
        if len(asset_ids) > 16 or any(not isinstance(item, str) for item in asset_ids):
            raise ValueError("shot prop/clue refs must be bounded string lists")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("shot prop/clue refs must be unique")
        normalized[shot_id] = list(asset_ids)
    current = (
        catalog
        if isinstance(catalog, PropOrClueAssetCatalog)
        else PropOrClueAssetCatalog(**catalog)
    )
    if current.season_no != plan.season_no:
        raise ValueError("prop/clue catalog belongs to another season")
    if set(normalized) != set(required_shots) or len(normalized) != len(required_shots):
        raise ValueError("every render shot must have an explicit prop/clue binding")
    assets = {asset.asset_id: asset for asset in current.assets}
    bindings: list[ShotPropOrClueRefs] = []
    for shot in plan.shots:
        refs: list[PropOrClueAssetRef] = []
        for asset_id in normalized[shot.shot_id]:
            asset = assets.get(asset_id)
            if asset is None:
                raise ValueError("prop/clue binding references an unknown asset")
            refs.append(_selected_prop_or_clue_asset_ref_impl(asset))
        bindings.append(
            ShotPropOrClueRefs(
                shot_id=shot.shot_id,
                source_fingerprint=shot.source_fingerprint,
                asset_refs=refs,
            )
        )
    usage_fingerprint = _sha256([model_to_dict(item) for item in bindings])
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "binding_revision": binding_revision,
        "usage_fingerprint": usage_fingerprint,
        "shot_asset_refs": [model_to_dict(item) for item in bindings],
    }
    payload["manifest_fingerprint"] = _sha256(payload)
    return EpisodePropOrClueAssetManifest(**payload)


def _prop_or_clue_usage_index_impl(
    manifest: EpisodePropOrClueAssetManifest | Dict[str, Any],
) -> Dict[str, list[str]]:
    current = (
        manifest
        if isinstance(manifest, EpisodePropOrClueAssetManifest)
        else EpisodePropOrClueAssetManifest(**manifest)
    )
    output: Dict[str, list[str]] = {}
    for binding in current.shot_asset_refs:
        for ref in binding.asset_refs:
            output.setdefault(ref.asset_id, []).append(binding.shot_id)
    return output


class PropOrClueAssetError(ValueError):
    """Bounded public error for local prop/clue pure operations."""


def _raise_prop_or_clue_asset_error(operation: str) -> None:
    raise PropOrClueAssetError(f"prop/clue asset {operation} was rejected")


def build_empty_prop_or_clue_asset_catalog(
    *,
    season_no: int = 1,
) -> PropOrClueAssetCatalog:
    try:
        return _build_empty_prop_or_clue_asset_catalog_impl(season_no=season_no)
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("catalog build")


def build_prop_or_clue_asset_version(
    *,
    asset_id: str,
    spec: PropOrClueSpec | Dict[str, Any],
    source_kind: str,
    artifact: PropOrClueArtifact | Dict[str, Any] | None = None,
    derived_from: str | None = None,
) -> PropOrClueAssetVersion:
    try:
        return _build_prop_or_clue_asset_version_impl(
            asset_id=asset_id,
            spec=spec,
            source_kind=source_kind,
            artifact=artifact,
            derived_from=derived_from,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("version build")


def add_prop_or_clue_asset(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    version: PropOrClueAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> PropOrClueAssetCatalog:
    try:
        return _add_prop_or_clue_asset_impl(
            catalog,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("addition")


def append_prop_or_clue_asset_version(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    version: PropOrClueAssetVersion | Dict[str, Any],
    expected_catalog_fingerprint: str,
) -> PropOrClueAssetCatalog:
    try:
        return _append_prop_or_clue_asset_version_impl(
            catalog,
            asset_id=asset_id,
            version=version,
            expected_catalog_fingerprint=expected_catalog_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("candidate append")


def select_prop_or_clue_asset_version(
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    asset_id: str,
    asset_version_id: str,
    expected_selection_revision: int,
    expected_selected_version_id: str,
) -> PropOrClueAssetCatalog:
    try:
        return _select_prop_or_clue_asset_version_impl(
            catalog,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            expected_selection_revision=expected_selection_revision,
            expected_selected_version_id=expected_selected_version_id,
        )
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("selection")


def selected_prop_or_clue_asset_ref(
    asset: PropOrClueAsset | Dict[str, Any],
) -> PropOrClueAssetRef:
    try:
        return _selected_prop_or_clue_asset_ref_impl(asset)
    except (RecursionError, StopIteration, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("reference build")


def build_episode_prop_or_clue_asset_manifest(
    render_plan: RenderPlan | Dict[str, Any],
    catalog: PropOrClueAssetCatalog | Dict[str, Any],
    *,
    shot_asset_ids: Mapping[str, list[str]],
    binding_revision: int = 0,
) -> EpisodePropOrClueAssetManifest:
    try:
        return _build_episode_prop_or_clue_asset_manifest_impl(
            render_plan,
            catalog,
            shot_asset_ids=shot_asset_ids,
            binding_revision=binding_revision,
        )
    except (KeyError, RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("manifest build")


def prop_or_clue_usage_index(
    manifest: EpisodePropOrClueAssetManifest | Dict[str, Any],
) -> Dict[str, list[str]]:
    try:
        return _prop_or_clue_usage_index_impl(manifest)
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_prop_or_clue_asset_error("usage projection")
