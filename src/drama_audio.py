"""Pure E1 voice resolution, utterance planning, and bounded mock WAV fixtures."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import wave
from typing import Any, Mapping, Sequence

from .drama_schemas import (
    AudioManifest,
    DialogueSegment,
    MockWavFixture,
    RenderPlan,
    VoiceAssignment,
    VoiceProfile,
)
from .schemas import model_to_dict


class DramaAudioError(ValueError):
    """Bounded public E1 validation error."""


def _sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_voice_profile(
    *,
    scope: str,
    character_id: str | None,
    display_name: str,
    language_tag: str,
    provider_id: str,
    model_id: str,
    voice_name: str,
    instructions: str = "",
) -> VoiceProfile:
    try:
        raw_strings = (
            scope,
            display_name,
            language_tag,
            provider_id,
            model_id,
            voice_name,
            instructions,
        )
        if any(not isinstance(item, str) for item in raw_strings) or (
            character_id is not None and not isinstance(character_id, str)
        ):
            raise ValueError("voice profile values must be strings")
        payload = {
            "schema_version": 1,
            "scope": scope,
            "character_id": character_id,
            "display_name": display_name,
            "language_tag": language_tag,
            "provider_id": provider_id,
            "model_id": model_id,
            "voice_name": voice_name,
            "instructions": instructions,
        }
        fingerprint = _sha256(payload)
        return VoiceProfile(
            profile_id=f"vp_{fingerprint[:24]}",
            profile_fingerprint=fingerprint,
            **payload,
        )
    except (TypeError, ValueError):
        raise DramaAudioError("voice profile was rejected") from None


def build_voice_assignment(
    *,
    segment_id: str,
    profile: VoiceProfile | Mapping[str, Any],
    speaker_character_id: str | None,
) -> VoiceAssignment:
    try:
        current = profile if isinstance(profile, VoiceProfile) else VoiceProfile(**profile)
        payload = {
            "schema_version": 1,
            "segment_id": segment_id,
            "voice_profile_id": current.profile_id,
            "voice_profile_fingerprint": current.profile_fingerprint,
            "speaker_character_id": speaker_character_id,
        }
        payload["assignment_fingerprint"] = _sha256(payload)
        return VoiceAssignment(**payload)
    except (TypeError, ValueError):
        raise DramaAudioError("voice assignment was rejected") from None


def _utterance_payload(plan: RenderPlan, segment: Any, profile: VoiceProfile, assignment: VoiceAssignment) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "episode_no": plan.episode_no,
        "sequence": segment.sequence,
        "segment_id": segment.segment_id,
        "shot_id": segment.shot_id,
        "kind": segment.kind,
        "text": segment.text,
        "speaker_character_id": assignment.speaker_character_id,
        "voice_profile_id": profile.profile_id,
        "voice_profile_fingerprint": profile.profile_fingerprint,
        "provider_id": profile.provider_id,
        "model_id": profile.model_id,
        "voice_name": profile.voice_name,
        "instructions_fingerprint": _sha256(profile.instructions),
        "source_segment_fingerprint": _sha256(model_to_dict(segment)),
    }
    fingerprint = _sha256(payload)
    return {
        "utterance_id": f"utt_{fingerprint[:24]}",
        "spec_fingerprint": fingerprint,
        **payload,
    }


def build_audio_manifest(
    render_plan: RenderPlan | Mapping[str, Any],
    *,
    profiles: Sequence[VoiceProfile | Mapping[str, Any]],
    assignments: Sequence[VoiceAssignment | Mapping[str, Any]],
) -> AudioManifest:
    try:
        if not isinstance(profiles, (list, tuple)) or len(profiles) > 32:
            raise ValueError("profiles must be bounded")
        if not isinstance(assignments, (list, tuple)) or len(assignments) > 200:
            raise ValueError("assignments must be bounded")
        plan = render_plan if isinstance(render_plan, RenderPlan) else RenderPlan(**render_plan)
        profile_rows = [
            item if isinstance(item, VoiceProfile) else VoiceProfile(**item)
            for item in profiles
        ]
        assignment_rows = [
            item if isinstance(item, VoiceAssignment) else VoiceAssignment(**item)
            for item in assignments
        ]
        profile_by_id = {item.profile_id: item for item in profile_rows}
        if len(profile_by_id) != len(profile_rows):
            raise ValueError("duplicate voice profiles")
        assignment_by_segment = {item.segment_id: item for item in assignment_rows}
        if len(assignment_by_segment) != len(assignment_rows):
            raise ValueError("duplicate voice assignments")
        known_segments = {item.segment_id for item in plan.spoken_segments}
        if not set(assignment_by_segment).issubset(known_segments):
            raise ValueError("assignment uses unknown segment")

        used_profiles: dict[str, VoiceProfile] = {}
        resolved_assignments: list[VoiceAssignment] = []
        utterances: list[dict[str, Any]] = []
        blocked: list[dict[str, str]] = []
        frozen = set(plan.frozen_character_ids)
        for segment in plan.spoken_segments:
            assignment = assignment_by_segment.get(segment.segment_id)
            if assignment is None:
                blocked.append({"segment_id": segment.segment_id, "reason": "assignment_missing"})
                continue
            profile = profile_by_id.get(assignment.voice_profile_id)
            if (
                profile is None
                or profile.profile_fingerprint != assignment.voice_profile_fingerprint
            ):
                blocked.append({"segment_id": segment.segment_id, "reason": "profile_missing"})
                continue
            if isinstance(segment, DialogueSegment):
                if assignment.speaker_character_id not in frozen:
                    blocked.append({"segment_id": segment.segment_id, "reason": "speaker_not_frozen"})
                    continue
                if (
                    profile.scope != "character"
                    or profile.character_id != assignment.speaker_character_id
                ):
                    blocked.append({"segment_id": segment.segment_id, "reason": "scope_mismatch"})
                    continue
            elif (
                assignment.speaker_character_id is not None
                or profile.scope != "narrator"
                or profile.character_id is not None
            ):
                blocked.append({"segment_id": segment.segment_id, "reason": "scope_mismatch"})
                continue
            used_profiles.setdefault(profile.profile_id, profile)
            resolved_assignments.append(assignment)
            utterances.append(_utterance_payload(plan, segment, profile, assignment))

        manifest_payload = {
            "schema_version": 1,
            "generator_version": "audio-manifest-v1",
            "season_no": plan.season_no,
            "episode_no": plan.episode_no,
            "source_render_plan_fingerprint": plan.plan_fingerprint,
            "frozen_character_ids": list(plan.frozen_character_ids),
            "source_segment_ids": [item.segment_id for item in plan.spoken_segments],
            "status": "blocked" if blocked else "ready",
            "profiles": [model_to_dict(item) for item in used_profiles.values()],
            "assignments": [model_to_dict(item) for item in resolved_assignments],
            "utterances": utterances,
            "blocked_segments": blocked,
        }
        manifest_payload["manifest_fingerprint"] = _sha256(manifest_payload)
        return AudioManifest(**manifest_payload)
    except DramaAudioError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaAudioError("audio manifest input was rejected") from None


def build_mock_wav_fixture(*, duration_milliseconds: int = 1000, sample_rate: int = 16000) -> bytes:
    if (
        not isinstance(duration_milliseconds, int)
        or isinstance(duration_milliseconds, bool)
        or not 1 <= duration_milliseconds <= 30_000
        or not isinstance(sample_rate, int)
        or isinstance(sample_rate, bool)
        or not 8000 <= sample_rate <= 48_000
    ):
        raise DramaAudioError("mock WAV fixture parameters were rejected")
    frames = duration_milliseconds * sample_rate // 1000
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
    return output.getvalue()


def probe_mock_wav_fixture(data: bytes) -> dict[str, int | str]:
    if type(data) is not bytes or not 44 <= len(data) <= 3_000_000:
        raise DramaAudioError("mock WAV fixture was rejected")
    try:
        audio_format, header_channels, header_rate, byte_rate, block_align, bits = (
            struct.unpack("<HHIIHH", data[20:36])
        )
        if (
            len(data) < 44
            or data[:4] != b"RIFF"
            or struct.unpack("<I", data[4:8])[0] != len(data) - 8
            or data[8:12] != b"WAVE"
            or data[12:16] != b"fmt "
            or struct.unpack("<I", data[16:20])[0] != 16
            or audio_format != 1
            or header_channels != 1
            or not 8000 <= header_rate <= 48_000
            or bits != 16
            or block_align != 2
            or byte_rate != header_rate * block_align
            or data[36:40] != b"data"
            or struct.unpack("<I", data[40:44])[0] != len(data) - 44
        ):
            raise ValueError("non-canonical WAV")
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            compression = handle.getcomptype()
            frames = handle.readframes(frame_count + 1)
        if (
            channels != 1
            or sample_width != 2
            or not 8000 <= sample_rate <= 48_000
            or not 1 <= frame_count <= sample_rate * 30
            or compression != "NONE"
            or len(frames) != frame_count * channels * sample_width
        ):
            raise ValueError("unsupported WAV")
        return {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "duration_milliseconds": frame_count * 1000 // sample_rate,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "frame_count": frame_count,
        }
    except (EOFError, OSError, ValueError, wave.Error):
        raise DramaAudioError("mock WAV fixture was rejected") from None


def describe_mock_wav_fixture(
    utterance: Any,
    data: bytes,
) -> MockWavFixture:
    """Validate bytes and bind their digest to one deterministic local path."""

    try:
        utterance_id = utterance.utterance_id
        episode_no = utterance.episode_no
        if not isinstance(episode_no, int) or isinstance(episode_no, bool):
            raise ValueError("invalid episode")
        probed = probe_mock_wav_fixture(data)
        return MockWavFixture(
            utterance_id=utterance_id,
            episode_no=episode_no,
            path=(
                f"data/drama/audio_fixtures/episode_{episode_no:03d}/"
                f"{utterance_id}.wav"
            ),
            sha256=probed["sha256"],
            size_bytes=probed["size_bytes"],
            duration_milliseconds=probed["duration_milliseconds"],
            sample_rate=probed["sample_rate"],
            channels=probed["channels"],
        )
    except (AttributeError, TypeError, ValueError):
        raise DramaAudioError("mock WAV descriptor was rejected") from None
