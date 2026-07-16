"""Shared synthetic D3 shot-video attempt fixtures for iter117 tests."""

from __future__ import annotations

import hashlib

from src import drama_shot_video_attempts, drama_shot_video_candidate_store
from tests._drama_shot_video_candidate_base import DramaShotVideoCandidateFixture


class DramaShotVideoAttemptFixture(DramaShotVideoCandidateFixture):
    @staticmethod
    def _mp4_for_duration(duration_seconds: int, marker: int = 0) -> bytes:
        data = bytearray(DramaShotVideoCandidateFixture._MOCK_MP4)
        cache = {}
        budget = [0]
        top = drama_shot_video_candidate_store._mp4_boxes(
            data, 0, len(data), cache=cache, budget=budget
        )
        moov_start, moov_end = drama_shot_video_candidate_store._first_mp4_box(
            data, 0, len(data), b"moov", cache=cache, budget=budget
        )
        mvhd_start, _mvhd_end = drama_shot_video_candidate_store._first_mp4_box(
            data, moov_start, moov_end, b"mvhd", cache=cache, budget=budget
        )
        data[mvhd_start + 12 : mvhd_start + 16] = (1000).to_bytes(4, "big")
        data[mvhd_start + 16 : mvhd_start + 20] = (
            duration_seconds * 1000
        ).to_bytes(4, "big")
        for box_type, trak_start, trak_end in top:
            if box_type != b"moov":
                continue
            for child_type, child_start, child_end in drama_shot_video_candidate_store._mp4_boxes(
                data, trak_start, trak_end, cache=None, budget=[0]
            ):
                if child_type != b"trak":
                    continue
                mdia_start, mdia_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, child_start, child_end, b"mdia", cache=None, budget=[0]
                )
                hdlr_start, hdlr_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, mdia_start, mdia_end, b"hdlr", cache=None, budget=[0]
                )
                if data[hdlr_start:hdlr_end][8:12] != b"vide":
                    continue
                mdhd_start, _mdhd_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, mdia_start, mdia_end, b"mdhd", cache=None, budget=[0]
                )
                data[mdhd_start + 12 : mdhd_start + 16] = (1000).to_bytes(4, "big")
                data[mdhd_start + 16 : mdhd_start + 20] = (
                    duration_seconds * 1000
                ).to_bytes(4, "big")
                minf_start, minf_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, mdia_start, mdia_end, b"minf", cache=None, budget=[0]
                )
                stbl_start, stbl_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, minf_start, minf_end, b"stbl", cache=None, budget=[0]
                )
                stts_start, _stts_end = drama_shot_video_candidate_store._first_mp4_box(
                    data, stbl_start, stbl_end, b"stts", cache=None, budget=[0]
                )
                data[stts_start + 12 : stts_start + 16] = (
                    duration_seconds * 1000
                ).to_bytes(4, "big")
        return bytes(data) + (9).to_bytes(4, "big") + b"free" + bytes([marker % 256])

    @staticmethod
    def _capability(durations: list[int], *, max_references: int = 25, tail: bool = True):
        return drama_shot_video_attempts.build_shot_video_provider_capability(
            backend_id="fake-shot-video",
            capability_version="v1",
            supported_modes=["image_to_video", "reference_to_video"],
            supports_tail_frame=tail,
            max_reference_images=max_references,
            supported_durations_seconds=sorted(set(durations)),
            supported_resolutions=[(16, 16)],
        )

    @staticmethod
    def _gate(
        *,
        provider: str = "a",
        model: str = "e",
        budget: int = 1000,
        estimate: int = 0,
        episode_no: int = 1,
        shot_id: str = "shot_000000000000000000000000",
        request_fingerprint: str = "f" * 64,
        authorization_nonce: str = "default",
    ):
        authorization_id = "svauth_" + hashlib.sha256(
            f"{episode_no}:{shot_id}:{request_fingerprint}:{authorization_nonce}".encode()
        ).hexdigest()[:24]
        return drama_shot_video_attempts.build_shot_video_submission_gate(
            backend_id="fake-shot-video",
            authorization_id=authorization_id,
            authorized_episode_no=episode_no,
            authorized_shot_id=shot_id,
            authorized_request_fingerprint=request_fingerprint,
            provider_fingerprint=provider * 64,
            model_fingerprint=model * 64,
            account_fingerprint="b" * 64,
            endpoint_fingerprint="c" * 64,
            auth_fingerprint="d" * 64,
            estimated_cost_microunits=estimate,
            authorized_budget_microunits=budget,
        )

    def _seed_video_attempt_sources(self, name: str = "shot-video-attempts"):
        sources = self._seed_video_candidate_sources(name)
        durations = [item.target_duration_seconds for item in sources["video_plan"].shot_specs]
        sources["capability"] = self._capability(durations)
        sources["shot_id"] = sources["video_plan"].shot_specs[0].shot_id
        request = sources["video_plan"].shot_specs[0]
        sources["gate"] = self._gate(
            episode_no=sources["video_plan"].episode_no,
            shot_id=request.shot_id,
            request_fingerprint=request.spec_fingerprint,
        )
        return sources
