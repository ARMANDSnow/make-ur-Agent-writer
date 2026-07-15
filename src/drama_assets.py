"""Pure character asset versioning and episode selection projections."""

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
    RenderPlan,
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
