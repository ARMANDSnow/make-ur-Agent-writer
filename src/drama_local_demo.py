"""One-workspace, zero-provider A-F short-drama production demonstration.

This is deliberately a local acceptance profile, not a production media
generator.  It may run only while the text model is ``mock`` and labels every
artifact as synthetic.  The normal production inspectors and compose gates
still validate all durable stores, fingerprints and media bytes.
"""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path
from typing import Any, Callable

from . import (
    drama_art_direction_store,
    drama_asset_versions,
    drama_assets,
    drama_audio,
    drama_compose_web,
    drama_compositor,
    drama_reviewer,
    drama_render_store,
    drama_shot_image,
    drama_shot_image_candidate_store,
    drama_shot_image_store,
    drama_shot_video_candidate_store,
    drama_shot_video_continuity,
    drama_shot_video_store,
    drama_store,
    drama_tts_attempts,
    paths,
)
from .config import get_model_config
from .drama_media_qa import _run_bounded_process
from .drama_schemas import CharacterSheet, character_paths, episode_paths, normalize_episode_no
from .drama_tts_attempt_store import (
    LocalFakeTtsAdapter,
    run_tts_attempt,
    tts_identity_from_authorization,
)
from .utils import read_json_optional, write_json


class DramaLocalDemoError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _png(rgba: bytes) -> bytes:
    if len(rgba) != 4:
        raise ValueError("RGBA fixture must contain four bytes")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + kind
            + payload
            + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    ihdr = (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 0))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" + rgba))
        + chunk(b"IEND", b"")
    )


def _write_artifact(root: Path, relative: str, data: bytes) -> dict[str, Any]:
    drama_compositor._atomic_write(root, relative, data, maximum=2_000_000)
    return {
        "path": relative,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _fixture_mp4(root: Path) -> bytes:
    relative = "outputs/drama/local_demo/fixture.mp4"
    drama_compositor._ensure_safe_parent(root, relative)
    completed = _run_bounded_process(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=#26344d:s=540x960:r=25:d=1",
            "-an", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", relative,
        ],
        cwd=root,
        timeout_seconds=60,
        stdout_limit=0,
        stderr_limit=16_384,
    )
    if completed.returncode != 0:
        raise DramaLocalDemoError("fixture_video_failed", "本地 FFmpeg 样片生成失败")
    target = root / relative
    data = target.read_bytes()
    target.unlink(missing_ok=True)
    return data


def _require_mock_profile() -> None:
    model = str(get_model_config("drama-plan").get("model") or "")
    if not model.lower().startswith("mock"):
        raise DramaLocalDemoError(
            "local_demo_requires_mock",
            "本地 A-F 演练仅在 mock 模型下开放，真实生产不会生成占位媒体",
        )


def _require_approved_episode(workspace: str, episode_no: int) -> None:
    from .web.drama_view import collect_drama_progress

    progress = collect_drama_progress(workspace, episode_no=episode_no)
    stations = progress.get("stations") or []
    review = next((row for row in stations if row.get("id") == "review"), None)
    if not review or review.get("status") != "done":
        raise DramaLocalDemoError(
            "creative_stage_incomplete", "请先完成站 ⑤ 评审组装，再开始本地制作演练"
        )


def inspect_synthetic_local_demo(workspace: str, *, episode_no: int = 1) -> dict[str, Any]:
    """Return a bounded UI action projection without mutating the workspace."""

    number = normalize_episode_no(episode_no)
    model = str(get_model_config("drama-plan").get("model") or "")
    if not model.lower().startswith("mock"):
        return {
            "state": "unavailable",
            "can_start": False,
            "label": "真实生产需逐阶段准备素材",
            "reason": "本地 A-F 演练只在 mock 模型下开放",
        }
    try:
        _require_approved_episode(workspace, number)
    except DramaLocalDemoError as exc:
        return {
            "state": "blocked",
            "can_start": False,
            "label": "完成创作后继续制作",
            "reason": str(exc),
        }
    try:
        compose = drama_compose_web.build_compose_web_overview_readonly(
            workspace, episode_no=number
        )
        if compose.get("state") == "complete":
            return {
                "state": "complete",
                "can_start": False,
                "label": "本地 A-F 演练已完成",
                "reason": "可在合成交付页下载 MP4、字幕和剪辑工程",
            }
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    if drama_render_store.render_plan_path(workspace, episode_no=number).exists():
        return {
            "state": "partial",
            "can_start": False,
            "label": "本地演练已有中间产物",
            "reason": "请在资产、镜头图片、镜头视频和合成交付页检查当前状态",
        }
    return {
        "state": "ready",
        "can_start": True,
        "label": "一键完成本地 A-F 演练",
        "reason": "生成合成素材、静音配音占位与本地交付；不会调用任何供应商",
    }


def _ensure_character_references(workspace: str, episode_no: int) -> CharacterSheet:
    root = paths.workspace_root(workspace)
    sheet_path = character_paths(workspace).sheet_path
    raw = read_json_optional(sheet_path, None)
    if not isinstance(raw, dict):
        raise DramaLocalDemoError("character_sheet_missing", "角色表不存在")
    sheet = CharacterSheet(**raw)
    changed = False
    for index, character in enumerate(raw.get("characters") or [], start=1):
        if character.get("reference_images"):
            continue
        relative = f"data/character_refs/{character['id']}/portrait_neutral.png"
        _write_artifact(
            root, relative, _png(bytes((40 + index, 70 + index, 110 + index, 255)))
        )
        character["reference_images"] = [
            {
                "path": relative,
                "generated_by": "synthetic-local-demo",
                "width": 1,
                "height": 1,
            }
        ]
        changed = True
    if changed:
        write_json(sheet_path, raw)
        ep = episode_paths(workspace, episode_no=episode_no)
        write_json(ep.review_path, drama_reviewer.run(workspace, mock=True, episode_no=episode_no))
        drama_store.assemble_episode(workspace, episode_no=episode_no)
        sheet = CharacterSheet(**read_json_optional(sheet_path, None))
    return sheet


def run_synthetic_local_demo(
    workspace: str,
    *,
    episode_no: int = 1,
    progress_cb: Callable[[str, float], None] = lambda _step, _fraction: None,
) -> dict[str, Any]:
    """Materialize A-F in one existing approved workspace and compose it."""

    number = normalize_episode_no(episode_no)
    _require_mock_profile()
    _require_approved_episode(workspace, number)
    root = paths.workspace_root(workspace)
    # Fail before creating any durable A-E state when FFmpeg is unavailable.
    base_mp4 = _fixture_mp4(root)
    progress_cb("local-demo-character-references", 0.04)
    _ensure_character_references(workspace, number)

    progress_cb("local-demo-render-plan", 0.10)
    drama_art_direction_store.create_art_direction_catalog(
        workspace,
        art_direction_id="season_default",
        spec={
            "preset": "cinematic",
            "positive_tokens": ["cinematic", "consistent character"],
            "negative_tokens": ["watermark", "text"],
            "palette": ["#26344d", "#c18a62"],
            "aspect_ratio": "9:16",
        },
        source_kind="preset",
        season_no=1,
    )
    render_plan = drama_render_store.create_render_plan(workspace, episode_no=number)

    progress_cb("local-demo-assets", 0.20)
    drama_asset_versions.create_character_asset_catalog(workspace, season_no=1)
    drama_asset_versions.create_episode_asset_manifest(workspace, episode_no=number)
    scene_record = _write_artifact(
        root, "data/scene_refs/s001/reference.png", _png(bytes((38, 52, 77, 255)))
    )
    scene_version = drama_assets.build_scene_asset_version(
        scene_id="s001",
        spec={
            "display_name": "本地演练场景",
            "location": "室内",
            "time_of_day": "夜",
            "weather": "晴",
            "spatial_anchors": ["入口", "主区域"],
            "visual_tokens": ["电影感", "冷暖对比"],
        },
        source_kind="identity_snapshot",
        artifact=scene_record,
    )
    drama_asset_versions.create_scene_asset_catalog(
        workspace, version=scene_version, season_no=1
    )
    drama_asset_versions.create_episode_scene_asset_manifest(
        workspace,
        episode_no=number,
        shot_scene_ids={shot.shot_id: "s001" for shot in render_plan.shots},
    )
    drama_asset_versions.create_prop_or_clue_asset_catalog(workspace, season_no=1)
    drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
        workspace,
        episode_no=number,
        shot_asset_ids={shot.shot_id: [] for shot in render_plan.shots},
    )

    progress_cb("local-demo-shot-images", 0.34)
    character_id = render_plan.frozen_character_ids[0]
    image_plan = drama_shot_image_store.create_episode_shot_image_plan(
        workspace,
        episode_no=number,
        shot_character_ids={shot.shot_id: [character_id] for shot in render_plan.shots},
        reference_policy=drama_shot_image.build_shot_image_reference_policy(
            max_reference_images=4
        ),
    )
    image_manifest = (
        drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
            workspace, episode_no=number
        )
    )
    for index, spec in enumerate(image_plan.shot_specs, start=1):
        image_manifest, candidate = (
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                workspace,
                episode_no=number,
                shot_id=spec.shot_id,
                png_bytes=_png(bytes((index, index + 20, index + 40, 255))),
                expected_manifest_fingerprint=image_manifest.manifest_fingerprint,
            )
        )
        pool = next(row for row in image_manifest.shots if row.shot_id == spec.shot_id)
        image_manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            workspace,
            episode_no=number,
            shot_id=spec.shot_id,
            frame="first",
            binding={
                "kind": "direct",
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            },
            expected_selection_revision=pool.selection_revision,
            expected_current_binding=None,
            expected_manifest_fingerprint=image_manifest.manifest_fingerprint,
        )

    progress_cb("local-demo-shot-videos", 0.50)
    video_plan = drama_shot_video_store.create_episode_shot_video_plan(
        workspace, episode_no=number
    )
    video_manifest = (
        drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
            workspace, episode_no=number
        )
    )
    for index, spec in enumerate(video_plan.shot_specs):
        variant = base_mp4 + (9).to_bytes(4, "big") + b"free" + bytes((index % 256,))
        video_manifest, candidate = (
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                workspace,
                episode_no=number,
                shot_id=spec.shot_id,
                mp4_bytes=variant,
                is_placeholder=False,
                expected_manifest_fingerprint=video_manifest.manifest_fingerprint,
            )
        )
        pool = next(row for row in video_manifest.shots if row.shot_id == spec.shot_id)
        video_manifest = (
            drama_shot_video_candidate_store.select_episode_shot_video_candidate(
                workspace,
                episode_no=number,
                shot_id=spec.shot_id,
                selection={
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=pool.selection_revision,
                expected_current_selection=None,
                expected_manifest_fingerprint=video_manifest.manifest_fingerprint,
            )
        )
    continuity = drama_shot_video_continuity.build_shot_video_continuity_report(
        video_plan, video_manifest
    )
    if not continuity.ready_for_compose:
        raise DramaLocalDemoError("video_continuity_blocked", "本地镜头视频连续性门禁未通过")

    progress_cb("local-demo-audio", 0.65)
    character_profile = drama_audio.build_voice_profile(
        scope="character",
        character_id=character_id,
        display_name="主角",
        language_tag="zh-CN",
        provider_id="synthetic-local",
        model_id="mock/tts-v1",
        voice_name="lead",
    )
    narrator_profile = drama_audio.build_voice_profile(
        scope="narrator",
        character_id=None,
        display_name="旁白",
        language_tag="zh-CN",
        provider_id="synthetic-local",
        model_id="mock/tts-v1",
        voice_name="narrator",
    )
    assignments = []
    for segment in render_plan.spoken_segments:
        narration = segment.kind == "narration"
        profile = narrator_profile if narration else character_profile
        assignments.append(
            drama_audio.build_voice_assignment(
                segment_id=segment.segment_id,
                profile=profile,
                speaker_character_id=None if narration else character_id,
            )
        )
    audio_manifest = drama_audio.build_audio_manifest(
        render_plan,
        profiles=[character_profile, narrator_profile],
        assignments=assignments,
    )
    capability = drama_tts_attempts.build_tts_provider_capability(
        backend_id="synthetic-local-tts",
        capability_version="v1",
        provider_id="synthetic-local",
        model_id="mock/tts-v1",
        sample_rate=16000,
    )
    wav = drama_audio.build_mock_wav_fixture(duration_milliseconds=20, sample_rate=16000)
    records = []
    for utterance in audio_manifest.utterances:
        authorization = drama_tts_attempts.build_tts_authorization(
            utterance,
            capability,
            provider_fingerprint="1" * 64,
            model_fingerprint="2" * 64,
            account_fingerprint="3" * 64,
            endpoint_fingerprint="4" * 64,
            auth_fingerprint="5" * 64,
        )
        records.append(
            run_tts_attempt(
                workspace,
                utterance,
                capability=capability,
                authorization=authorization,
                adapter=LocalFakeTtsAdapter(
                    identity=tts_identity_from_authorization(capability, authorization),
                    wav_bytes=wav,
                ),
            )
        )
    timeline = drama_compose_web.persist_workspace_timeline_manifest(
        workspace,
        audio_manifest,
        records,
        episode_no=number,
        bgm_policy="disabled",
    )

    progress_cb("local-demo-compose", 0.78)
    result = drama_compose_web.run_workspace_compose_job(
        workspace, episode_no=number, progress_cb=progress_cb
    )
    return {
        **result,
        "profile": "synthetic-local-a-f",
        "provider_validated": False,
        "shot_count": len(render_plan.shots),
        "timeline_fingerprint": timeline.timeline_fingerprint,
    }
