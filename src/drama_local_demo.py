"""Isolated-workspace, zero-provider A-F short-drama acceptance demonstration.

This is deliberately a local acceptance profile, not a production media
generator.  User-facing runs always create a ``localdemo_*`` workspace so
synthetic artifacts can never contaminate the source project's production
state.  Normal inspectors and compose gates still validate the isolated
workspace's durable stores, fingerprints and media bytes.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
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


def _scaled_progress(
    callback: Callable[[str, float], None],
    *,
    start: float,
    span: float,
) -> Callable[[str, float], None]:
    def emit(step: str, fraction: float) -> None:
        callback(step, start + span * max(0.0, min(1.0, float(fraction))))

    check = getattr(callback, "check_cancelled", None)
    if callable(check):
        emit.check_cancelled = check  # type: ignore[attr-defined]
    return emit


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


def _fixture_mp4(root: Path, *, duration_seconds: float, ordinal: int) -> bytes:
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(float(duration_seconds))
        or not 0.2 <= float(duration_seconds) <= 120.0
    ):
        raise DramaLocalDemoError("fixture_duration_invalid", "本地样片时长无效")
    relative = f"outputs/drama/local_demo/fixture_{ordinal:03d}.mp4"
    drama_compositor._ensure_safe_parent(root, relative)
    completed = _run_bounded_process(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i",
            f"color=c=#26344d:s=540x960:r=5:d={float(duration_seconds):.3f}",
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
    return {
        "state": "ready",
        "can_start": True,
        "label": "新建隔离项目完成 A-F 演练",
        "reason": "当前项目保持不变；隔离项目只生成合成占位和本地交付，不调用供应商",
    }


def allocate_synthetic_demo_workspace(source_workspace: str, *, episode_no: int) -> str:
    """Allocate a bounded, visibly synthetic workspace name without writing it."""

    number = normalize_episode_no(episode_no)
    source_hash = hashlib.sha256(source_workspace.encode("utf-8")).hexdigest()[:8]
    for _attempt in range(16):
        candidate = f"localdemo_{source_hash}_{number}_{secrets.token_hex(4)}"
        if not paths.workspace_root(candidate).exists():
            return candidate
    raise DramaLocalDemoError("local_demo_name_exhausted", "无法分配隔离验收项目名称")


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
    progress_start: float = 0.0,
    progress_span: float = 1.0,
) -> dict[str, Any]:
    """Materialize A-F inside one dedicated ``localdemo_*`` workspace."""

    number = normalize_episode_no(episode_no)
    if not re.fullmatch(r"localdemo_[a-f0-9_]+", workspace):
        raise DramaLocalDemoError(
            "local_demo_workspace_required",
            "本地 A-F 演练只能写入 localdemo_ 隔离验收项目",
        )
    _require_mock_profile()
    _require_approved_episode(workspace, number)
    emit = _scaled_progress(
        progress_cb,
        start=progress_start,
        span=progress_span,
    )
    root = paths.workspace_root(workspace)
    # Fail before creating any durable A-E state when FFmpeg is unavailable.
    _fixture_mp4(root, duration_seconds=0.2, ordinal=0)
    emit("local-demo-character-references", 0.04)
    _ensure_character_references(workspace, number)

    emit("local-demo-render-plan", 0.10)
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

    emit("local-demo-assets", 0.20)
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

    emit("local-demo-shot-images", 0.34)
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

    emit("local-demo-shot-videos", 0.50)
    video_plan = drama_shot_video_store.create_episode_shot_video_plan(
        workspace, episode_no=number
    )
    video_manifest = (
        drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
            workspace, episode_no=number
        )
    )
    fixture_by_duration: dict[float, bytes] = {}
    for index, spec in enumerate(video_plan.shot_specs, start=1):
        duration = round(float(spec.target_duration_seconds), 3)
        base_mp4 = fixture_by_duration.get(duration)
        if base_mp4 is None:
            base_mp4 = _fixture_mp4(
                root,
                duration_seconds=duration,
                ordinal=index,
            )
            fixture_by_duration[duration] = base_mp4
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

    emit("local-demo-audio", 0.65)
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

    emit("local-demo-compose", 0.78)
    result = drama_compose_web.run_workspace_compose_job(
        workspace,
        episode_no=number,
        progress_cb=_scaled_progress(
            progress_cb,
            start=progress_start + progress_span * 0.78,
            span=progress_span * 0.22,
        ),
    )
    return {
        **result,
        "profile": "synthetic-local-a-f",
        "provider_validated": False,
        "shot_count": len(render_plan.shots),
        "timeline_fingerprint": timeline.timeline_fingerprint,
    }


def run_isolated_synthetic_local_demo(
    source_workspace: str,
    *,
    demo_workspace: str,
    source_episode_no: int = 1,
    progress_cb: Callable[[str, float], None] = lambda _step, _fraction: None,
) -> dict[str, Any]:
    """Create a fresh mock creative baseline, then run A-F in isolation."""

    source_number = normalize_episode_no(source_episode_no)
    _require_mock_profile()
    _require_approved_episode(source_workspace, source_number)
    if not re.fullmatch(r"localdemo_[a-f0-9_]+", demo_workspace):
        raise DramaLocalDemoError("local_demo_target_invalid", "隔离验收项目名称无效")
    if paths.workspace_root(demo_workspace).exists():
        raise DramaLocalDemoError("local_demo_target_exists", "隔离验收项目已存在")

    wizard_input = read_json_optional(
        paths.workspace_root(source_workspace) / "data" / "wizard_input.json",
        {},
    )
    requested_duration = (
        wizard_input.get("episode_duration_seconds")
        if isinstance(wizard_input, dict)
        else 60
    )
    if requested_duration not in {30, 60, 90, 120}:
        requested_duration = 60

    progress_cb("local-demo-isolated-creative", 0.01)
    from . import drama_smoke

    creative_steps = {
        "drama-plan": 0.02,
        "drama-hooks": 0.05,
        "drama-storyboard": 0.08,
        "drama-characters": 0.11,
        "drama-review-assemble": 0.14,
    }

    def creative_start(step: str) -> None:
        progress_cb("local-demo-creative-" + step, creative_steps[step])

    def creative_complete(step: str, _result: dict[str, Any]) -> None:
        progress_cb("local-demo-creative-" + step, creative_steps[step] + 0.025)

    cancel_check = getattr(progress_cb, "check_cancelled", None)

    drama_smoke.run_smoke(
        demo_workspace,
        track="推理",
        real_text=False,
        real_image=False,
        timeout_seconds=300,
        budget_cny=0,
        reset_jobs=False,
        create_workspace=True,
        episode_duration_seconds=int(requested_duration),
        pin_mock_environment=False,
        cancel_check=cancel_check if callable(cancel_check) else None,
        on_step_start=creative_start,
        on_step_complete=creative_complete,
    )
    result = run_synthetic_local_demo(
        demo_workspace,
        episode_no=1,
        progress_cb=progress_cb,
        progress_start=0.20,
        progress_span=0.80,
    )
    return {
        **result,
        "workspace": demo_workspace,
        "source_episode_no": source_number,
        "profile": "synthetic-local-a-f-isolated",
    }
