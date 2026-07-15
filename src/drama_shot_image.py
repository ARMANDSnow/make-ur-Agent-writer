"""Pure stage-C1 shot image input assembly with no file or network access."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from .drama_schemas import (
    ArtDirectionCatalog,
    ArtDirectionVersion,
    AssetRef,
    AssetVersion,
    CharacterAssetCatalog,
    EpisodeAssetManifest,
    EpisodePropOrClueAssetManifest,
    EpisodeSceneAssetManifest,
    EpisodeShotImagePlan,
    PropOrClueAssetCatalog,
    PropOrClueAssetRef,
    PropOrClueAssetVersion,
    RenderPlan,
    SceneAssetCatalog,
    SceneAssetRef,
    SceneAssetVersion,
    ShotCharacterBinding,
    ShotImageReference,
    ShotImageReferencePolicy,
    ShotImageRequestSpec,
)
from .schemas import model_to_dict


class DramaShotImageError(ValueError):
    """Bounded public error for caller-controlled shot image inputs."""


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _raise_public_error(operation: str) -> None:
    raise DramaShotImageError(f"shot image {operation} was rejected")


def build_shot_image_reference_policy(
    *,
    max_reference_images: int,
) -> ShotImageReferencePolicy:
    try:
        payload: Dict[str, Any] = {
            "schema_version": 1,
            "max_reference_images": max_reference_images,
            "priority_version": "character_scene_prop_clue_v1",
        }
        payload["policy_fingerprint"] = _sha256(payload)
        return ShotImageReferencePolicy(**payload)
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_public_error("reference policy build")


def _normalize_character_mapping(
    plan: RenderPlan,
    shot_character_ids: Mapping[str, list[str]],
) -> Dict[str, list[str]]:
    if not isinstance(shot_character_ids, Mapping):
        raise ValueError("shot_character_ids must be an explicit mapping")
    required = [shot.shot_id for shot in plan.shots]
    if len(shot_character_ids) != len(required):
        raise ValueError("every render shot must have an explicit character binding")
    normalized: Dict[str, list[str]] = {}
    frozen = set(plan.frozen_character_ids)
    for shot_id, character_ids in shot_character_ids.items():
        if len(normalized) >= len(required):
            raise ValueError("shot_character_ids contains too many entries")
        if not isinstance(shot_id, str) or not isinstance(character_ids, list):
            raise ValueError("shot_character_ids must map string ids to lists")
        if len(character_ids) > 8 or any(
            not isinstance(item, str) for item in character_ids
        ):
            raise ValueError("shot character bindings must be bounded string lists")
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("shot character bindings must be unique")
        if any(item not in frozen for item in character_ids):
            raise ValueError("shot character binding is outside the frozen cast")
        normalized[shot_id] = list(character_ids)
    if set(normalized) != set(required) or len(normalized) != len(required):
        raise ValueError("every render shot must have an explicit character binding")
    return normalized


def _selected_art_direction_version(
    plan: RenderPlan,
    catalog: ArtDirectionCatalog | None,
) -> ArtDirectionVersion | None:
    if plan.art_direction_ref is None:
        if catalog is not None and catalog.season_no != plan.season_no:
            raise ValueError("art direction catalog belongs to another season")
        return None
    if catalog is None or catalog.season_no != plan.season_no:
        raise ValueError("selected art direction catalog is required")
    ref = plan.art_direction_ref
    if catalog.art_direction_id != ref.art_direction_id:
        raise ValueError("art direction ref belongs to another catalog")
    if catalog.selected_version_id != ref.version_id:
        raise ValueError("art direction selected version changed")
    selected = next(
        (item for item in catalog.versions if item.version_id == ref.version_id),
        None,
    )
    if selected is None or selected.version_fingerprint != ref.fingerprint:
        raise ValueError("art direction ref does not match its exact version")
    return selected


def _character_versions(
    catalog: CharacterAssetCatalog,
    manifest: EpisodeAssetManifest,
    used_character_ids: list[str],
) -> tuple[Dict[str, AssetRef], Dict[str, AssetVersion]]:
    assets = {item.asset_id: item for item in catalog.assets}
    manifest_refs = {item.asset_id: item for item in manifest.asset_refs}
    refs: Dict[str, AssetRef] = {}
    versions: Dict[str, AssetVersion] = {}
    for character_id in used_character_ids:
        ref = manifest_refs.get(character_id)
        if ref is None:
            raise ValueError("used character is missing from the episode manifest")
        asset = assets.get(ref.asset_id)
        if asset is None or asset.selected_version_id != ref.asset_version_id:
            raise ValueError("character manifest does not match selected assets")
        version = next(
            (
                item
                for item in asset.versions
                if item.asset_version_id == ref.asset_version_id
            ),
            None,
        )
        if version is None or version.version_fingerprint != ref.version_fingerprint:
            raise ValueError("character ref does not match its exact version")
        artifact_sha = version.artifact.sha256 if version.artifact is not None else None
        if artifact_sha != ref.artifact_sha256:
            raise ValueError("character ref artifact does not match its exact version")
        refs[ref.asset_id] = ref
        versions[ref.asset_id] = version
    return refs, versions


def _scene_versions(
    catalog: SceneAssetCatalog,
    manifest: EpisodeSceneAssetManifest,
) -> tuple[Dict[str, SceneAssetRef], Dict[str, SceneAssetVersion]]:
    assets = {item.scene_id: item for item in catalog.assets}
    refs: Dict[str, SceneAssetRef] = {}
    versions: Dict[str, SceneAssetVersion] = {}
    for binding in manifest.shot_scene_refs:
        ref = binding.scene_ref
        asset = assets.get(ref.scene_id)
        if asset is None or asset.selected_version_id != ref.scene_version_id:
            raise ValueError("scene manifest does not match selected assets")
        version = next(
            (
                item
                for item in asset.versions
                if item.scene_version_id == ref.scene_version_id
            ),
            None,
        )
        if version is None or version.version_fingerprint != ref.version_fingerprint:
            raise ValueError("scene ref does not match its exact version")
        artifact_sha = version.artifact.sha256 if version.artifact is not None else None
        if artifact_sha != ref.artifact_sha256:
            raise ValueError("scene ref artifact does not match its exact version")
        refs[binding.shot_id] = ref
        versions[binding.shot_id] = version
    return refs, versions


def _prop_clue_versions(
    catalog: PropOrClueAssetCatalog,
    manifest: EpisodePropOrClueAssetManifest,
) -> tuple[
    Dict[str, list[PropOrClueAssetRef]],
    Dict[str, list[PropOrClueAssetVersion]],
]:
    assets = {item.asset_id: item for item in catalog.assets}
    refs_by_shot: Dict[str, list[PropOrClueAssetRef]] = {}
    versions_by_shot: Dict[str, list[PropOrClueAssetVersion]] = {}
    for binding in manifest.shot_asset_refs:
        refs: list[PropOrClueAssetRef] = []
        versions: list[PropOrClueAssetVersion] = []
        for ref in binding.asset_refs:
            asset = assets.get(ref.asset_id)
            if asset is None or asset.selected_version_id != ref.asset_version_id:
                raise ValueError("prop/clue manifest does not match selected assets")
            version = next(
                (
                    item
                    for item in asset.versions
                    if item.asset_version_id == ref.asset_version_id
                ),
                None,
            )
            if version is None or version.version_fingerprint != ref.version_fingerprint:
                raise ValueError("prop/clue ref does not match its exact version")
            artifact_sha = (
                version.artifact.sha256 if version.artifact is not None else None
            )
            if artifact_sha != ref.artifact_sha256:
                raise ValueError("prop/clue ref artifact does not match its exact version")
            refs.append(ref)
            versions.append(version)
        refs_by_shot[binding.shot_id] = refs
        versions_by_shot[binding.shot_id] = versions
    return refs_by_shot, versions_by_shot


def _reference_payload(
    *,
    kind: str,
    asset_id: str,
    asset_version_id: str,
    version_fingerprint: str,
    artifact: Any,
) -> Dict[str, Any]:
    return {
        "kind": kind,
        "asset_id": asset_id,
        "asset_version_id": asset_version_id,
        "version_fingerprint": version_fingerprint,
        "artifact_path": artifact.path,
        "artifact_sha256": artifact.sha256,
        "artifact_size_bytes": artifact.size_bytes,
    }


def _build_episode_shot_image_plan_impl(
    render_plan: RenderPlan | Dict[str, Any],
    character_catalog: CharacterAssetCatalog | Dict[str, Any],
    character_manifest: EpisodeAssetManifest | Dict[str, Any],
    scene_catalog: SceneAssetCatalog | Dict[str, Any],
    scene_manifest: EpisodeSceneAssetManifest | Dict[str, Any],
    prop_clue_catalog: PropOrClueAssetCatalog | Dict[str, Any],
    prop_clue_manifest: EpisodePropOrClueAssetManifest | Dict[str, Any],
    *,
    art_direction_catalog: ArtDirectionCatalog | Dict[str, Any] | None,
    shot_character_ids: Mapping[str, list[str]],
    reference_policy: ShotImageReferencePolicy | Dict[str, Any],
    character_binding_revision: int = 0,
) -> EpisodeShotImagePlan:
    if not isinstance(character_binding_revision, int) or isinstance(
        character_binding_revision,
        bool,
    ):
        raise ValueError("character binding revision must be a strict integer")
    plan = render_plan if isinstance(render_plan, RenderPlan) else RenderPlan(**render_plan)
    char_catalog = (
        character_catalog
        if isinstance(character_catalog, CharacterAssetCatalog)
        else CharacterAssetCatalog(**character_catalog)
    )
    char_manifest = (
        character_manifest
        if isinstance(character_manifest, EpisodeAssetManifest)
        else EpisodeAssetManifest(**character_manifest)
    )
    current_scene_catalog = (
        scene_catalog
        if isinstance(scene_catalog, SceneAssetCatalog)
        else SceneAssetCatalog(**scene_catalog)
    )
    current_scene_manifest = (
        scene_manifest
        if isinstance(scene_manifest, EpisodeSceneAssetManifest)
        else EpisodeSceneAssetManifest(**scene_manifest)
    )
    current_prop_catalog = (
        prop_clue_catalog
        if isinstance(prop_clue_catalog, PropOrClueAssetCatalog)
        else PropOrClueAssetCatalog(**prop_clue_catalog)
    )
    current_prop_manifest = (
        prop_clue_manifest
        if isinstance(prop_clue_manifest, EpisodePropOrClueAssetManifest)
        else EpisodePropOrClueAssetManifest(**prop_clue_manifest)
    )
    current_art_catalog = (
        art_direction_catalog
        if isinstance(art_direction_catalog, ArtDirectionCatalog)
        or art_direction_catalog is None
        else ArtDirectionCatalog(**art_direction_catalog)
    )
    policy = (
        reference_policy
        if isinstance(reference_policy, ShotImageReferencePolicy)
        else ShotImageReferencePolicy(**reference_policy)
    )

    sources = (char_manifest, current_scene_manifest, current_prop_manifest)
    if any(
        item.season_no != plan.season_no
        or item.episode_no != plan.episode_no
        or item.render_plan_fingerprint != plan.plan_fingerprint
        for item in sources
    ):
        raise ValueError("shot image sources do not belong to the RenderPlan")
    if any(
        item.season_no != plan.season_no
        for item in (char_catalog, current_scene_catalog, current_prop_catalog)
    ):
        raise ValueError("shot image catalogs belong to another season")
    if [item.asset_id for item in char_manifest.asset_refs] != plan.frozen_character_ids:
        raise ValueError("character manifest does not preserve the frozen cast order")

    normalized_mapping = _normalize_character_mapping(plan, shot_character_ids)
    used_character_ids = list(
        dict.fromkeys(
            character_id
            for shot in plan.shots
            for character_id in normalized_mapping[shot.shot_id]
        )
    )
    art_version = _selected_art_direction_version(plan, current_art_catalog)
    character_refs, character_versions = _character_versions(
        char_catalog,
        char_manifest,
        used_character_ids,
    )
    scene_refs, scene_versions = _scene_versions(
        current_scene_catalog,
        current_scene_manifest,
    )
    prop_refs, prop_versions = _prop_clue_versions(
        current_prop_catalog,
        current_prop_manifest,
    )
    required_shot_ids = [shot.shot_id for shot in plan.shots]
    if (
        list(scene_refs) != required_shot_ids
        or list(prop_refs) != required_shot_ids
    ):
        raise ValueError("asset manifests do not preserve RenderPlan shot order")
    scene_bindings = {
        item.shot_id: item.source_fingerprint
        for item in current_scene_manifest.shot_scene_refs
    }
    prop_bindings = {
        item.shot_id: item.source_fingerprint
        for item in current_prop_manifest.shot_asset_refs
    }
    if any(
        scene_bindings[shot.shot_id] != shot.source_fingerprint
        or prop_bindings[shot.shot_id] != shot.source_fingerprint
        for shot in plan.shots
    ):
        raise ValueError("asset manifest shot source fingerprints are stale")

    bindings: list[ShotCharacterBinding] = []
    shot_specs: list[ShotImageRequestSpec] = []
    for shot in plan.shots:
        character_ids = normalized_mapping[shot.shot_id]
        bindings.append(
            ShotCharacterBinding(
                shot_id=shot.shot_id,
                source_fingerprint=shot.source_fingerprint,
                character_ids=character_ids,
            )
        )
        selected_character_refs = [character_refs[item] for item in character_ids]
        selected_scene_ref = scene_refs[shot.shot_id]
        selected_scene_version = scene_versions[shot.shot_id]
        selected_prop_refs = prop_refs[shot.shot_id]
        selected_prop_versions = prop_versions[shot.shot_id]

        raw_references: list[Dict[str, Any]] = []
        blocked_reasons: list[str] = []
        warning_codes: list[str] = []
        for character_id in character_ids:
            version = character_versions[character_id]
            if version.artifact is None:
                if "character_artifact_missing" not in blocked_reasons:
                    blocked_reasons.append("character_artifact_missing")
                continue
            raw_references.append(
                _reference_payload(
                    kind="character",
                    asset_id=character_id,
                    asset_version_id=version.asset_version_id,
                    version_fingerprint=version.version_fingerprint,
                    artifact=version.artifact,
                )
            )
        if selected_scene_version.artifact is None:
            warning_codes.append("scene_artifact_missing")
        else:
            raw_references.append(
                _reference_payload(
                    kind="scene",
                    asset_id=selected_scene_version.scene_id,
                    asset_version_id=selected_scene_version.scene_version_id,
                    version_fingerprint=selected_scene_version.version_fingerprint,
                    artifact=selected_scene_version.artifact,
                )
            )
        missing_prop_artifact = False
        for version in selected_prop_versions:
            if version.artifact is None:
                missing_prop_artifact = True
                continue
            raw_references.append(
                _reference_payload(
                    kind=version.spec.kind,
                    asset_id=version.asset_id,
                    asset_version_id=version.asset_version_id,
                    version_fingerprint=version.version_fingerprint,
                    artifact=version.artifact,
                )
            )
        if missing_prop_artifact:
            warning_codes.append("prop_clue_artifact_missing")

        dropped = max(0, len(raw_references) - policy.max_reference_images)
        if dropped:
            warning_codes.append("reference_limit_exceeded")
        image_references = [
            ShotImageReference(**{**item, "position": index})
            for index, item in enumerate(
                raw_references[: policy.max_reference_images],
                start=1,
            )
        ]
        request_payload: Dict[str, Any] = {
            "shot_id": shot.shot_id,
            "source_fingerprint": shot.source_fingerprint,
            "status": "blocked" if blocked_reasons else "assembled",
            "shot_size": shot.shot_size,
            "camera_movement": shot.camera_movement,
            "visual_action": shot.visual_action,
            "image_prompt": shot.image_prompt,
            "transition_hint": shot.transition_hint,
            "art_direction_ref": (
                model_to_dict(plan.art_direction_ref)
                if plan.art_direction_ref is not None
                else None
            ),
            "art_direction_version": (
                model_to_dict(art_version) if art_version is not None else None
            ),
            "reference_policy_fingerprint": policy.policy_fingerprint,
            "character_refs": [model_to_dict(item) for item in selected_character_refs],
            "character_versions": [
                model_to_dict(character_versions[item]) for item in character_ids
            ],
            "scene_ref": model_to_dict(selected_scene_ref),
            "scene_version": model_to_dict(selected_scene_version),
            "prop_clue_refs": [model_to_dict(item) for item in selected_prop_refs],
            "prop_clue_versions": [
                model_to_dict(item) for item in selected_prop_versions
            ],
            "image_references": [model_to_dict(item) for item in image_references],
            "warning_codes": warning_codes,
            "dropped_reference_count": dropped,
            "blocked_reasons": blocked_reasons,
        }
        request_payload["request_fingerprint"] = _sha256(request_payload)
        shot_specs.append(ShotImageRequestSpec(**request_payload))

    binding_fingerprint_payload = [
        {"shot_id": item.shot_id, "character_ids": item.character_ids}
        for item in sorted(bindings, key=lambda item: item.shot_id)
    ]
    used_character_payload = [
        {
            "asset_ref": model_to_dict(character_refs[item]),
            "asset_version": model_to_dict(character_versions[item]),
        }
        for item in used_character_ids
    ]
    plan_payload: Dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-image-plan-v1",
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "used_character_fingerprint": _sha256(used_character_payload),
        "art_direction_version_fingerprint": (
            plan.art_direction_ref.fingerprint
            if plan.art_direction_ref is not None
            else None
        ),
        "scene_manifest_fingerprint": current_scene_manifest.manifest_fingerprint,
        "prop_clue_manifest_fingerprint": current_prop_manifest.manifest_fingerprint,
        "reference_policy": model_to_dict(policy),
        "character_binding_revision": character_binding_revision,
        "character_binding_fingerprint": _sha256(binding_fingerprint_payload),
        "character_bindings": [model_to_dict(item) for item in bindings],
        "shot_specs": [model_to_dict(item) for item in shot_specs],
    }
    plan_payload["plan_fingerprint"] = _sha256(plan_payload)
    return EpisodeShotImagePlan(**plan_payload)


def build_episode_shot_image_plan(
    render_plan: RenderPlan | Dict[str, Any],
    character_catalog: CharacterAssetCatalog | Dict[str, Any],
    character_manifest: EpisodeAssetManifest | Dict[str, Any],
    scene_catalog: SceneAssetCatalog | Dict[str, Any],
    scene_manifest: EpisodeSceneAssetManifest | Dict[str, Any],
    prop_clue_catalog: PropOrClueAssetCatalog | Dict[str, Any],
    prop_clue_manifest: EpisodePropOrClueAssetManifest | Dict[str, Any],
    *,
    art_direction_catalog: ArtDirectionCatalog | Dict[str, Any] | None,
    shot_character_ids: Mapping[str, list[str]],
    reference_policy: ShotImageReferencePolicy | Dict[str, Any],
    character_binding_revision: int = 0,
) -> EpisodeShotImagePlan:
    try:
        return _build_episode_shot_image_plan_impl(
            render_plan,
            character_catalog,
            character_manifest,
            scene_catalog,
            scene_manifest,
            prop_clue_catalog,
            prop_clue_manifest,
            art_direction_catalog=art_direction_catalog,
            shot_character_ids=shot_character_ids,
            reference_policy=reference_policy,
            character_binding_revision=character_binding_revision,
        )
    except (KeyError, RecursionError, StopIteration, TypeError, ValueError):
        pass
    _raise_public_error("plan build")


def shot_image_character_mapping(
    plan: EpisodeShotImagePlan | Dict[str, Any],
) -> Dict[str, list[str]]:
    try:
        current = (
            plan if isinstance(plan, EpisodeShotImagePlan) else EpisodeShotImagePlan(**plan)
        )
        return {
            item.shot_id: list(item.character_ids)
            for item in current.character_bindings
        }
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_public_error("character mapping projection")


def shot_image_affected_ids(
    before: EpisodeShotImagePlan | Dict[str, Any],
    after: EpisodeShotImagePlan | Dict[str, Any],
) -> list[str]:
    try:
        old = (
            before
            if isinstance(before, EpisodeShotImagePlan)
            else EpisodeShotImagePlan(**before)
        )
        new = (
            after
            if isinstance(after, EpisodeShotImagePlan)
            else EpisodeShotImagePlan(**after)
        )
        old_by_id = {item.shot_id: item.request_fingerprint for item in old.shot_specs}
        new_by_id = {item.shot_id: item.request_fingerprint for item in new.shot_specs}
        ordered = [item.shot_id for item in new.shot_specs]
        ordered.extend(item.shot_id for item in old.shot_specs if item.shot_id not in new_by_id)
        return [shot_id for shot_id in ordered if old_by_id.get(shot_id) != new_by_id.get(shot_id)]
    except (RecursionError, TypeError, ValueError):
        pass
    _raise_public_error("affected-shot projection")
