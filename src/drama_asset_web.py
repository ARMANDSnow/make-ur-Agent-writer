"""Strict, redacted Web projection for drama asset governance.

The domain catalogs deliberately contain creative specs, local artifact paths,
and provider-derived metadata.  None of those fields belong in a generic Web
response.  This module is therefore an allowlist projection rather than a
``model_dump`` wrapper.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import (
    drama_art_direction_scope,
    drama_art_direction_store,
    drama_asset_usage,
    drama_asset_versions,
    drama_render_store,
)
from .drama_schemas import (
    AssetRetirementState,
    AssetUsageBlocker,
    AssetUsageReference,
    SeasonAssetUsageIndex,
)

AssetKind = Literal["character", "art_direction", "scene", "prop", "clue"]
AssetScope = Literal["series", "global", "episode"]
CatalogState = Literal[
    "fresh",
    "missing",
    "stale",
    "blocked_source",
    "invalid",
]


class DramaAssetWebError(ValueError):
    """Public, already-sanitized asset Web error."""


class DramaAssetWebConflict(DramaAssetWebError):
    """Optimistic-concurrency conflict suitable for HTTP 409."""


class AssetWebReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=100)
    shot_ids: list[str] = Field(default_factory=list, max_length=100)


class AssetWebBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    season_no: Optional[int] = Field(default=None, ge=1)
    episode_no: Optional[int] = Field(default=None, ge=1, le=100)


class AssetWebVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version_id: str = Field(min_length=1, max_length=80)
    derived_from: Optional[str] = Field(default=None, min_length=1, max_length=80)
    selected: bool
    status: Literal["active", "disabled"]
    selection_allowed: bool
    references: list[AssetWebReference] = Field(default_factory=list, max_length=100)
    scope_references: list[AssetWebReference] = Field(
        default_factory=list,
        max_length=100,
    )


class AssetWebItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetKind
    asset_id: str = Field(min_length=1, max_length=64)
    scope: Optional[AssetScope] = None
    episode_no: Optional[int] = Field(default=None, ge=1, le=100)
    selected_version_id: str = Field(min_length=1, max_length=80)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    enabled: Optional[bool] = None
    scope_revision: Optional[int] = Field(
        default=None,
        ge=0,
        le=2_147_483_647,
    )
    impact_complete: bool
    versions: list[AssetWebVersion] = Field(min_length=1, max_length=256)
    stale_references: list[AssetWebReference] = Field(
        default_factory=list,
        max_length=100,
    )


class AssetWebSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    state: CatalogState
    reasons: list[str] = Field(default_factory=list, max_length=16)
    mutable: bool
    items: list[AssetWebItem] = Field(default_factory=list, max_length=999)


class DramaAssetWebOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: int = Field(ge=1)
    episode_no: int = Field(ge=1, le=100)
    retirement_revision: int = Field(ge=0, le=2_147_483_647)
    usage_index_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    scanned_episode_nos: list[int] = Field(default_factory=list, max_length=100)
    blockers: list[AssetWebBlocker] = Field(default_factory=list, max_length=512)
    mutation_allowed: bool
    sections: list[AssetWebSection] = Field(max_length=8)


class AssetSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetKind
    asset_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=80)
    expected_selection_revision: int = Field(ge=0, le=2_147_483_647)
    expected_selected_version_id: str = Field(min_length=1, max_length=80)
    season_no: int = Field(default=1, ge=1)
    scope: Optional[AssetScope] = None
    episode_no: Optional[int] = Field(default=None, ge=1, le=100)
    view_episode_no: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def _identity_is_consistent(self) -> "AssetSelectionRequest":
        if self.kind == "art_direction":
            if self.scope not in ("series", "global", "episode"):
                raise ValueError("art direction selection requires a scope")
            if (self.scope == "episode") != (self.episode_no is not None):
                raise ValueError("episode scope requires exactly one episode_no")
        elif self.scope is not None or self.episode_no is not None:
            raise ValueError("non-art assets cannot carry scope or episode_no")
        return self


class AssetStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: AssetKind
    asset_id: str = Field(min_length=1, max_length=64)
    version_id: str = Field(min_length=1, max_length=80)
    status: Literal["active", "disabled"]
    expected_revision: int = Field(ge=0, le=2_147_483_647)
    expected_current_status: Literal["active", "disabled"]
    season_no: int = Field(default=1, ge=1)
    view_episode_no: int = Field(default=1, ge=1, le=100)


class ArtDirectionScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope: Literal["global", "episode"]
    enabled: bool
    expected_scope_revision: int = Field(ge=0, le=2_147_483_647)
    expected_enabled: bool
    season_no: Optional[int] = Field(default=None, ge=1)
    episode_no: Optional[int] = Field(default=None, ge=1, le=100)
    view_episode_no: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def _scope_is_consistent(self) -> "ArtDirectionScopeRequest":
        if self.scope == "global":
            if self.season_no is not None or self.episode_no is not None:
                raise ValueError("global scope cannot bind an episode")
        elif self.season_no is None or self.episode_no is None:
            raise ValueError("episode scope requires season_no and episode_no")
        elif self.view_episode_no != self.episode_no:
            raise ValueError("episode scope must match the viewed episode")
        return self


class AssetMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    changed: bool
    affected_references: list[AssetWebReference] = Field(
        default_factory=list,
        max_length=100,
    )
    overview: DramaAssetWebOverview


def _public_state(state: str) -> CatalogState:
    if state == "fresh":
        return "fresh"
    if state == "stale":
        return "stale"
    if state == "blocked_source":
        return "blocked_source"
    if state == "invalid":
        return "invalid"
    return "missing"


def _public_reasons(reasons: Iterable[str]) -> list[str]:
    result: list[str] = []
    for reason in reasons:
        value = str(reason)
        if len(value) <= 64 and value.replace("_", "").isalnum():
            result.append(value)
        else:
            result.append("unavailable")
    return result[:16]


def _usage_map(
    index: SeasonAssetUsageIndex,
) -> Dict[tuple[str, str, str], list[AssetUsageReference]]:
    return {
        (entry.kind, entry.asset_id, entry.version_id): list(entry.references)
        for entry in index.entries
    }


def _references(
    usage: Dict[tuple[str, str, str], list[AssetUsageReference]],
    *,
    kind: str,
    asset_id: str,
    version_id: str,
    season_no: int,
) -> list[AssetWebReference]:
    return [
        AssetWebReference(
            season_no=season_no,
            episode_no=reference.episode_no,
            shot_ids=list(reference.shot_ids),
        )
        for reference in usage.get((kind, asset_id, version_id), ())
    ]


ScopeUsageKey = tuple[
    str,
    Optional[int],
    Optional[int],
    str,
    str,
    int,
    Optional[int],
]
_ART_USAGE_SOURCES = frozenset(
    {
        "episode_scan",
        "art_direction_catalog",
        "art_direction_global_catalog",
        "art_direction_episode_catalog",
        "render_plan",
    }
)


def _scoped_art_direction_usage(
    workspace: str,
) -> tuple[
    Dict[ScopeUsageKey, list[AssetWebReference]],
    list[AssetWebBlocker],
    set[int],
]:
    usage: Dict[ScopeUsageKey, list[AssetWebReference]] = {}
    blockers: list[AssetWebBlocker] = []
    seasons: set[int] = set()
    for episode_no in range(1, 101):
        inspection = drama_render_store.inspect_stored_render_plan(
            workspace,
            episode_no=episode_no,
        )
        if inspection.state == "needs_render_plan":
            continue
        if inspection.state != "fresh" or inspection.plan is None:
            blockers.append(
                AssetWebBlocker(
                    source="render_plan",
                    code="scope_resolution_invalid",
                    episode_no=episode_no,
                )
            )
            continue
        plan = inspection.plan
        seasons.add(plan.season_no)
        if plan.art_direction_ref is None:
            continue
        resolution = plan.art_direction_resolution
        if resolution is None:
            blockers.append(
                AssetWebBlocker(
                    source="render_plan",
                    code="scope_resolution_missing",
                    season_no=plan.season_no,
                    episode_no=episode_no,
                )
            )
            continue
        scope_season = (
            plan.season_no
            if resolution.scope in ("series", "episode")
            else None
        )
        scope_episode = episode_no if resolution.scope == "episode" else None
        key: ScopeUsageKey = (
            resolution.scope,
            scope_season,
            scope_episode,
            resolution.ref.art_direction_id,
            resolution.ref.version_id,
            resolution.source_selection_revision,
            resolution.source_scope_revision,
        )
        usage.setdefault(key, []).append(
            AssetWebReference(
                season_no=plan.season_no,
                episode_no=episode_no,
                shot_ids=sorted(shot.shot_id for shot in plan.shots),
            )
        )
    return usage, blockers, seasons


def _version(
    *,
    kind: AssetKind,
    asset_id: str,
    version_id: str,
    derived_from: Optional[str],
    selected_version_id: str,
    retirement: AssetRetirementState,
    usage: Dict[tuple[str, str, str], list[AssetUsageReference]],
    season_no: int,
    scope_references: list[AssetWebReference],
    selection_allowed_override: Optional[bool] = None,
) -> AssetWebVersion:
    status = drama_asset_usage.asset_version_status(
        retirement,
        kind=kind,
        asset_id=asset_id,
        version_id=version_id,
    )
    return AssetWebVersion(
        version_id=version_id,
        derived_from=derived_from,
        selected=version_id == selected_version_id,
        status=status,
        selection_allowed=(
            status == "active"
            if selection_allowed_override is None
            else selection_allowed_override
        ),
        references=_references(
            usage,
            kind=kind,
            asset_id=asset_id,
            version_id=version_id,
            season_no=season_no,
        ),
        scope_references=scope_references,
    )


def _item(
    *,
    kind: AssetKind,
    asset_id: str,
    selected_version_id: str,
    selection_revision: int,
    raw_versions: Iterable[Any],
    id_field: str,
    retirement: AssetRetirementState,
    usage: Dict[tuple[str, str, str], list[AssetUsageReference]],
    season_no: int,
    scoped_usage: Dict[ScopeUsageKey, list[AssetWebReference]],
    scope: Optional[AssetScope] = None,
    episode_no: Optional[int] = None,
    enabled: Optional[bool] = None,
    scope_revision: Optional[int] = None,
    selection_allowed: Optional[Dict[str, bool]] = None,
    impact_complete: bool = True,
) -> AssetWebItem:
    versions = [
        _version(
            kind=kind,
            asset_id=asset_id,
            version_id=getattr(version, id_field),
            derived_from=version.derived_from,
            selected_version_id=selected_version_id,
            retirement=retirement,
            usage=usage,
            season_no=season_no,
            scope_references=(
                list(
                    scoped_usage.get(
                        (
                            scope,
                            (
                                season_no
                                if scope in ("series", "episode")
                                else None
                            ),
                            episode_no if scope == "episode" else None,
                            asset_id,
                            getattr(version, id_field),
                            selection_revision,
                            scope_revision,
                        ),
                        (),
                    )
                )
                if kind == "art_direction" and scope is not None
                else _references(
                    usage,
                    kind=kind,
                    asset_id=asset_id,
                    version_id=getattr(version, id_field),
                    season_no=season_no,
                )
            ),
            selection_allowed_override=(
                (selection_allowed or {}).get(getattr(version, id_field))
                if selection_allowed is not None
                else None
            ),
        )
        for version in sorted(
            raw_versions,
            key=lambda candidate: getattr(candidate, id_field),
        )
    ]
    selected = next(version for version in versions if version.selected)
    return AssetWebItem(
        kind=kind,
        asset_id=asset_id,
        scope=scope,
        episode_no=episode_no,
        selected_version_id=selected_version_id,
        selection_revision=selection_revision,
        enabled=enabled,
        scope_revision=scope_revision,
        impact_complete=impact_complete,
        versions=versions,
        stale_references=list(selected.scope_references),
    )


def _blocker(
    blocker: AssetUsageBlocker,
    *,
    season_no: int,
) -> AssetWebBlocker:
    return AssetWebBlocker(
        source=blocker.source,
        code=blocker.code,
        season_no=season_no,
        episode_no=blocker.episode_no,
    )


def build_asset_web_overview(
    workspace: str,
    *,
    season_no: int = 1,
    episode_no: int = 1,
) -> DramaAssetWebOverview:
    """Build one bounded projection; missing optional catalogs are not errors."""

    if type(season_no) is not int or season_no < 1:
        raise DramaAssetWebError("season_no must be a positive integer")
    if type(episode_no) is not int or not 1 <= episode_no <= 100:
        raise DramaAssetWebError("episode_no must be between 1 and 100")

    try:
        index = drama_asset_usage.build_season_asset_usage_index(
            workspace,
            season_no=season_no,
        )
        retirement = drama_asset_usage.load_asset_retirement_state(
            workspace,
            season_no=season_no,
        )
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise DramaAssetWebError("asset governance state is invalid") from exc
    usage = _usage_map(index)
    scoped_usage, scoped_blockers, _plan_seasons = _scoped_art_direction_usage(
        workspace
    )
    current_art_blocked = bool(scoped_blockers) or any(
        blocker.source in _ART_USAGE_SOURCES for blocker in index.blockers
    )
    global_art_blocked = _global_governance_has_blockers(
        workspace,
        requested_season_no=season_no,
    )
    sections: list[AssetWebSection] = []

    character = drama_asset_versions.inspect_character_asset_catalog(
        workspace,
        season_no=season_no,
    )
    character_items: list[AssetWebItem] = []
    if character.state == "fresh" and character.catalog is not None:
        for asset in sorted(
            character.catalog.assets,
            key=lambda candidate: candidate.asset_id,
        ):
            character_items.append(
                _item(
                    kind="character",
                    asset_id=asset.asset_id,
                    selected_version_id=asset.selected_version_id,
                    selection_revision=asset.selection_revision,
                    raw_versions=asset.versions,
                    id_field="asset_version_id",
                    retirement=retirement,
                    usage=usage,
                    season_no=season_no,
                    scoped_usage=scoped_usage,
                    impact_complete=not index.blockers,
                )
            )
    sections.append(
        AssetWebSection(
            key="characters",
            state=_public_state(character.state),
            reasons=_public_reasons(character.reasons),
            mutable=character.state == "fresh",
            items=character_items,
        )
    )

    series = drama_art_direction_store.inspect_art_direction_catalog(
        workspace,
        season_no=season_no,
    )
    series_items: list[AssetWebItem] = []
    if series.state == "fresh" and series.catalog is not None:
        catalog = series.catalog
        series_items.append(
            _item(
                kind="art_direction",
                asset_id=catalog.art_direction_id,
                selected_version_id=catalog.selected_version_id,
                selection_revision=catalog.selection_revision,
                raw_versions=catalog.versions,
                id_field="version_id",
                retirement=retirement,
                usage=usage,
                season_no=season_no,
                scoped_usage=scoped_usage,
                scope="series",
                impact_complete=not current_art_blocked,
            )
        )
    sections.append(
        AssetWebSection(
            key="art_direction_series",
            state=_public_state(series.state),
            reasons=_public_reasons(series.reasons),
            mutable=series.state == "fresh",
            items=series_items,
        )
    )

    for scope, bound_season, bound_episode in (
        ("global", None, None),
        ("episode", season_no, episode_no),
    ):
        scoped = drama_art_direction_scope.inspect_scoped_art_direction_catalog(
            workspace,
            scope=scope,
            season_no=bound_season,
            episode_no=bound_episode,
        )
        scoped_items: list[AssetWebItem] = []
        if scoped.state == "fresh" and scoped.catalog is not None:
            catalog = scoped.catalog
            global_selection_allowed: Optional[Dict[str, bool]] = None
            if scope == "global":
                try:
                    governance_seasons = (
                        drama_asset_usage.list_asset_governance_season_nos(
                            workspace
                        )
                    )
                    if len(governance_seasons) > 100:
                        raise DramaAssetWebError(
                            "asset governance season capacity exceeded"
                        )
                    governance_states = [
                        drama_asset_usage.load_asset_retirement_state(
                            workspace,
                            season_no=governance_season,
                        )
                        for governance_season in governance_seasons
                    ]
                    global_selection_allowed = {
                        version.version_id: all(
                            drama_asset_usage.asset_version_status(
                                state,
                                kind="art_direction",
                                asset_id=catalog.art_direction_id,
                                version_id=version.version_id,
                            )
                            == "active"
                            for state in governance_states
                        )
                        for version in catalog.versions
                    }
                except (OSError, TypeError, ValueError, RecursionError):
                    global_selection_allowed = {
                        version.version_id: False
                        for version in catalog.versions
                    }
            scoped_items.append(
                _item(
                    kind="art_direction",
                    asset_id=catalog.art_direction_id,
                    selected_version_id=catalog.selected_version_id,
                    selection_revision=catalog.selection_revision,
                    raw_versions=catalog.versions,
                    id_field="version_id",
                    retirement=retirement,
                    usage=usage,
                    season_no=season_no,
                    scoped_usage=scoped_usage,
                    scope=scope,
                    episode_no=catalog.episode_no,
                    enabled=catalog.enabled,
                    scope_revision=catalog.scope_revision,
                    selection_allowed=global_selection_allowed,
                    impact_complete=(
                        not global_art_blocked
                        if scope == "global"
                        else not current_art_blocked
                    ),
                )
            )
        sections.append(
            AssetWebSection(
                key=f"art_direction_{scope}",
                state=_public_state(scoped.state),
                reasons=_public_reasons(scoped.reasons),
                mutable=scoped.state == "fresh",
                items=scoped_items,
            )
        )

    scene = drama_asset_versions.inspect_scene_asset_catalog(
        workspace,
        season_no=season_no,
    )
    scene_items: list[AssetWebItem] = []
    if scene.state == "fresh" and scene.catalog is not None:
        for asset in sorted(
            scene.catalog.assets,
            key=lambda candidate: candidate.scene_id,
        ):
            scene_items.append(
                _item(
                    kind="scene",
                    asset_id=asset.scene_id,
                    selected_version_id=asset.selected_version_id,
                    selection_revision=asset.selection_revision,
                    raw_versions=asset.versions,
                    id_field="scene_version_id",
                    retirement=retirement,
                    usage=usage,
                    season_no=season_no,
                    scoped_usage=scoped_usage,
                    impact_complete=not index.blockers,
                )
            )
    sections.append(
        AssetWebSection(
            key="scenes",
            state=_public_state(scene.state),
            reasons=_public_reasons(scene.reasons),
            mutable=scene.state == "fresh",
            items=scene_items,
        )
    )

    prop_clue = drama_asset_versions.inspect_prop_or_clue_asset_catalog(
        workspace,
        season_no=season_no,
    )
    prop_clue_items: list[AssetWebItem] = []
    if prop_clue.state == "fresh" and prop_clue.catalog is not None:
        for asset in sorted(
            prop_clue.catalog.assets,
            key=lambda candidate: candidate.asset_id,
        ):
            prop_clue_items.append(
                _item(
                    kind=asset.kind,
                    asset_id=asset.asset_id,
                    selected_version_id=asset.selected_version_id,
                    selection_revision=asset.selection_revision,
                    raw_versions=asset.versions,
                    id_field="asset_version_id",
                    retirement=retirement,
                    usage=usage,
                    season_no=season_no,
                    scoped_usage=scoped_usage,
                    impact_complete=not index.blockers,
                )
            )
    sections.append(
        AssetWebSection(
            key="props_and_clues",
            state=_public_state(prop_clue.state),
            reasons=_public_reasons(prop_clue.reasons),
            mutable=prop_clue.state == "fresh",
            items=prop_clue_items,
        )
    )

    return DramaAssetWebOverview(
        season_no=season_no,
        episode_no=episode_no,
        retirement_revision=retirement.revision,
        usage_index_fingerprint=index.index_fingerprint,
        scanned_episode_nos=list(index.scanned_episode_nos),
        blockers=(
            [
                *[
                    _blocker(item, season_no=season_no)
                    for item in index.blockers
                ],
                *scoped_blockers,
            ][:512]
        ),
        mutation_allowed=not index.blockers
        and not scoped_blockers
        and all(section.state != "invalid" for section in sections),
        sections=sections,
    )


def _raise_public_mutation_error(
    exc: BaseException,
    *,
    after_preflight: bool = False,
) -> None:
    message = str(exc).lower()
    if after_preflight or any(
        marker in message
        for marker in ("changed", "concurrent", "revision", "workspace locked")
    ):
        raise DramaAssetWebConflict("asset state changed; refresh and retry") from exc
    raise DramaAssetWebError("asset mutation was rejected") from exc


def _overview_item(
    overview: DramaAssetWebOverview,
    *,
    kind: AssetKind,
    asset_id: str,
    scope: Optional[AssetScope] = None,
    episode_no: Optional[int] = None,
) -> AssetWebItem:
    matches = [
        item
        for section in overview.sections
        for item in section.items
        if item.kind == kind
        and item.asset_id == asset_id
        and item.scope == scope
        and item.episode_no == episode_no
    ]
    if len(matches) != 1:
        raise DramaAssetWebError("asset identity is not available")
    return matches[0]


def _global_governance_has_blockers(
    workspace: str,
    *,
    requested_season_no: int,
) -> bool:
    try:
        _usage, scoped_blockers, plan_seasons = _scoped_art_direction_usage(
            workspace
        )
        seasons = set(
            drama_asset_usage.list_asset_governance_season_nos(workspace)
        )
        seasons.update(plan_seasons)
        seasons.add(requested_season_no)
        if len(seasons) > 100 or scoped_blockers:
            return True
        return any(
            any(
                blocker.source in _ART_USAGE_SOURCES
                for blocker in drama_asset_usage.build_season_asset_usage_index(
                    workspace,
                    season_no=season_no,
                ).blockers
            )
            for season_no in sorted(seasons)
        )
    except (OSError, TypeError, ValueError, RecursionError):
        return True


def select_asset_candidate(
    workspace: str,
    request: AssetSelectionRequest,
) -> AssetMutationResult:
    before = build_asset_web_overview(
        workspace,
        season_no=request.season_no,
        episode_no=(
            request.episode_no
            if request.scope == "episode"
            else request.view_episode_no
        ),
    )
    item_before = _overview_item(
        before,
        kind=request.kind,
        asset_id=request.asset_id,
        scope=request.scope,
        episode_no=request.episode_no,
    )
    if (
        item_before.selection_revision != request.expected_selection_revision
        or item_before.selected_version_id
        != request.expected_selected_version_id
    ):
        raise DramaAssetWebConflict("asset state changed; refresh and retry")
    target_before = next(
        (
            version
            for version in item_before.versions
            if version.version_id == request.version_id
        ),
        None,
    )
    if target_before is None:
        raise DramaAssetWebError("asset version is not available")
    exact_no_op = request.version_id == request.expected_selected_version_id
    if not exact_no_op and not target_before.selection_allowed:
        raise DramaAssetWebError("disabled asset version cannot be selected")
    if not exact_no_op and not item_before.impact_complete:
        raise DramaAssetWebError("asset usage scan is incomplete")
    affected = next(
        version.scope_references
        for version in item_before.versions
        if version.version_id == request.expected_selected_version_id
    )
    before_revision = request.expected_selection_revision
    try:
        if request.kind == "character":
            result = drama_asset_versions.select_character_asset_version(
                workspace,
                character_id=request.asset_id,
                asset_version_id=request.version_id,
                expected_selection_revision=request.expected_selection_revision,
                expected_selected_version_id=request.expected_selected_version_id,
                season_no=request.season_no,
            )
            item = next(asset for asset in result.assets if asset.asset_id == request.asset_id)
        elif request.kind == "scene":
            result = drama_asset_versions.select_scene_asset_version(
                workspace,
                scene_id=request.asset_id,
                scene_version_id=request.version_id,
                expected_selection_revision=request.expected_selection_revision,
                expected_selected_version_id=request.expected_selected_version_id,
                season_no=request.season_no,
            )
            item = next(asset for asset in result.assets if asset.scene_id == request.asset_id)
        elif request.kind in ("prop", "clue"):
            result = drama_asset_versions.select_prop_or_clue_asset_version(
                workspace,
                asset_id=request.asset_id,
                asset_version_id=request.version_id,
                expected_selection_revision=request.expected_selection_revision,
                expected_selected_version_id=request.expected_selected_version_id,
                season_no=request.season_no,
            )
            item = next(asset for asset in result.assets if asset.asset_id == request.asset_id)
        elif request.scope == "series":
            result = drama_art_direction_store.select_art_direction_version(
                workspace,
                version_id=request.version_id,
                expected_selection_revision=request.expected_selection_revision,
                expected_selected_version_id=request.expected_selected_version_id,
                season_no=request.season_no,
            )
            item = result
        else:
            result = drama_art_direction_scope.select_scoped_art_direction_version(
                workspace,
                scope=request.scope,  # type: ignore[arg-type]
                version_id=request.version_id,
                expected_selection_revision=request.expected_selection_revision,
                expected_selected_version_id=request.expected_selected_version_id,
                season_no=(
                    request.season_no if request.scope == "episode" else None
                ),
                episode_no=request.episode_no,
            )
            item = result
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError) as exc:
        _raise_public_mutation_error(exc, after_preflight=True)
    changed = (
        item.selection_revision != before_revision
        or item.selected_version_id != request.expected_selected_version_id
    )
    return AssetMutationResult(
        changed=changed,
        affected_references=affected if changed else [],
        overview=build_asset_web_overview(
            workspace,
            season_no=request.season_no,
            episode_no=(
                request.episode_no
                if request.scope == "episode"
                else request.view_episode_no
            ),
        ),
    )


def set_asset_status(
    workspace: str,
    request: AssetStatusRequest,
) -> AssetMutationResult:
    before = build_asset_web_overview(
        workspace,
        season_no=request.season_no,
        episode_no=request.view_episode_no,
    )
    matching_versions = [
        version
        for section in before.sections
        for item in section.items
        if item.kind == request.kind and item.asset_id == request.asset_id
        for version in item.versions
        if version.version_id == request.version_id
    ]
    if not matching_versions:
        raise DramaAssetWebError("asset version is not available")
    if before.retirement_revision != request.expected_revision or any(
        version.status != request.expected_current_status
        for version in matching_versions
    ):
        raise DramaAssetWebConflict("asset state changed; refresh and retry")
    if (
        request.status != request.expected_current_status
        and request.status == "disabled"
        and not before.mutation_allowed
    ):
        raise DramaAssetWebError("asset usage scan is incomplete")
    affected = matching_versions[0].references
    try:
        result = drama_asset_usage.set_asset_version_status(
            workspace,
            kind=request.kind,
            asset_id=request.asset_id,
            version_id=request.version_id,
            status=request.status,
            expected_revision=request.expected_revision,
            expected_current_status=request.expected_current_status,
            season_no=request.season_no,
        )
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError) as exc:
        _raise_public_mutation_error(exc, after_preflight=True)
    return AssetMutationResult(
        changed=result.revision != request.expected_revision,
        affected_references=(
            affected
            if result.revision != request.expected_revision
            else []
        ),
        overview=build_asset_web_overview(
            workspace,
            season_no=request.season_no,
            episode_no=request.view_episode_no,
        ),
    )


def set_art_direction_scope_enabled(
    workspace: str,
    request: ArtDirectionScopeRequest,
) -> AssetMutationResult:
    before_overview = build_asset_web_overview(
        workspace,
        season_no=request.season_no or 1,
        episode_no=request.view_episode_no,
    )
    section_key = f"art_direction_{request.scope}"
    section = next(
        (item for item in before_overview.sections if item.key == section_key),
        None,
    )
    if section is None or len(section.items) != 1:
        raise DramaAssetWebError("art direction scope is not available")
    before_item = section.items[0]
    if (
        before_item.scope_revision != request.expected_scope_revision
        or before_item.enabled is not request.expected_enabled
    ):
        raise DramaAssetWebConflict("asset state changed; refresh and retry")
    selected_before = next(
        version for version in before_item.versions if version.selected
    )
    if (
        request.enabled
        and request.enabled != request.expected_enabled
        and not selected_before.selection_allowed
    ):
        raise DramaAssetWebError("disabled asset version cannot be selected")
    if (
        request.enabled != request.expected_enabled
        and not before_item.impact_complete
    ):
        raise DramaAssetWebError("asset usage scan is incomplete")
    affected = selected_before.scope_references
    try:
        result = drama_art_direction_scope.set_scoped_art_direction_enabled(
            workspace,
            scope=request.scope,
            enabled=request.enabled,
            expected_scope_revision=request.expected_scope_revision,
            expected_enabled=request.expected_enabled,
            season_no=request.season_no,
            episode_no=request.episode_no,
        )
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError) as exc:
        _raise_public_mutation_error(exc, after_preflight=True)
    return AssetMutationResult(
        changed=result.scope_revision != request.expected_scope_revision,
        affected_references=(
            affected
            if result.scope_revision != request.expected_scope_revision
            else []
        ),
        overview=build_asset_web_overview(
            workspace,
            season_no=request.season_no or 1,
            episode_no=request.view_episode_no,
        ),
    )
