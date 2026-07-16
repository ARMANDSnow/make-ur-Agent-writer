"""Shared synthetic D2 shot-video candidate fixtures for iter116 tests."""

from __future__ import annotations

import base64

from src import (
    drama_shot_video,
    drama_shot_video_candidate_store,
    drama_shot_video_store,
)
from src.drama_schemas import EpisodeShotVideoPlan
from src.schemas import model_to_dict
from tests._drama_shot_video_base import DramaShotVideoFixture


class DramaShotVideoCandidateFixture(DramaShotVideoFixture):
    _MOCK_MP4 = base64.b64decode(
        "AAAAHGZ0eXBtcDQyAAAAAWlzb21tcDQxbXA0MgAAAAFtZGF0AAAAAAAAAH8AAAA1BgUtR1ZK3FxMQz+U78URPNFDqAEAAAMAAQMAAAMAAQIAAeYACwAAAwAAAwAACVYMA5EIAIAAAAAyJbggH94I5Uz/gswem1JEAFF721iPegoZHua5g6fVtrKB82GsqGNvqOenAAA2gBXDPRgAAAKnbW9vdgAAAGxtdmhkAAAAAOZ5GRPmeRkUAAACWAAAACgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAjN0cmFrAAAAXHRraGQAAAAB5nkZFOZ5GRQAAAABAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAAoAAAAAAABAAAAAAGrbWRpYQAAACBtZGhkAAAAAOZ5GRTmeRkUAAACWAAAAChVxAAAAAAAMWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABDb3JlIE1lZGlhIFZpZGVvAAAAAVJtaW5mAAAAFHZtaGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAESc3RibAAAAKFzdHNkAAAAAAAAAAEAAACRYXZjMQAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAQABAASAAAAEgAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABj//wAAACdhdmNDAWQAC//hAAwnZAALrFZQw3gWYKUBAAQo7jyw/fj4AAAAAApmaWVsAQAAAAAKY2hybQAAAAAAGHN0dHMAAAAAAAAAAQAAAAEAAAAoAAAADXNkdHAAAAAAIAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAABvAAAAAQAAABRzdGNvAAAAAAAAAAEAAAAs"
    )

    @staticmethod
    def _mp4_variant(marker: int = 0) -> bytes:
        marker_payload = bytes([marker % 256])
        return (
            DramaShotVideoCandidateFixture._MOCK_MP4
            + (9).to_bytes(4, "big")
            + b"free"
            + marker_payload
        )

    def _seed_video_candidate_sources(
        self,
        name: str = "shot-video-candidates",
    ):
        sources = self._seed_shot_video_sources(name, previous_tail=True)
        video_plan = drama_shot_video_store.create_episode_shot_video_plan(name)
        manifest = (
            drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                name
            )
        )
        sources["video_plan"] = video_plan
        sources["video_candidate_manifest"] = manifest
        return sources

    @staticmethod
    def _episode_plan_variant(plan, episode_no: int) -> EpisodeShotVideoPlan:
        payload = model_to_dict(plan)
        payload["episode_no"] = episode_no
        for spec in payload["shot_specs"]:
            for frame_name in ("first_frame", "tail_frame"):
                frame = spec[frame_name]
                if frame is None:
                    continue
                frame["episode_no"] = episode_no
                candidate_basis = {
                    "schema_version": 1,
                    "season_no": frame["season_no"],
                    "episode_no": episode_no,
                    "shot_id": frame["source_shot_id"],
                    "source_plan_fingerprint": frame[
                        "candidate_source_plan_fingerprint"
                    ],
                    "request_fingerprint": frame[
                        "candidate_request_fingerprint"
                    ],
                    "source_kind": "local_png",
                    "artifact": {
                        key: value
                        for key, value in frame["artifact"].items()
                        if key != "path"
                    },
                }
                candidate_fingerprint = drama_shot_video._sha256(candidate_basis)
                frame["candidate_fingerprint"] = candidate_fingerprint
                frame["candidate_id"] = f"sic_{candidate_fingerprint[:24]}"
                frame["artifact"]["path"] = (
                    f"outputs/episodes/episode_{episode_no:02d}.shot_images/"
                    f"{frame['source_shot_id']}/{frame['candidate_id']}.png"
                )
                frame["frame_fingerprint"] = drama_shot_video._sha256(
                    {
                        key: value
                        for key, value in frame.items()
                        if key != "frame_fingerprint"
                    }
                )
            spec["spec_fingerprint"] = drama_shot_video._sha256(
                {
                    key: value
                    for key, value in spec.items()
                    if key != "spec_fingerprint"
                }
            )
        payload["selected_bindings_fingerprint"] = drama_shot_video._sha256(
            [
                {
                    "shot_id": spec["shot_id"],
                    "selection_revision": spec["selection_revision"],
                    "first_frame_fingerprint": spec["first_frame"][
                        "frame_fingerprint"
                    ],
                    "tail_frame_fingerprint": (
                        spec["tail_frame"]["frame_fingerprint"]
                        if spec["tail_frame"] is not None
                        else None
                    ),
                }
                for spec in payload["shot_specs"]
            ]
        )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        return EpisodeShotVideoPlan(**payload)

    def _append_video_candidate(
        self,
        name: str,
        manifest,
        shot_id: str,
        *,
        marker: int = 0,
        is_placeholder: bool = False,
    ):
        return drama_shot_video_candidate_store.append_local_shot_video_candidate(
            name,
            shot_id=shot_id,
            mp4_bytes=self._mp4_variant(marker),
            is_placeholder=is_placeholder,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )

    def _select_video_candidate(self, name: str, manifest, candidate):
        pool = next(
            item for item in manifest.shots if item.shot_id == candidate.shot_id
        )
        return drama_shot_video_candidate_store.select_episode_shot_video_candidate(
            name,
            shot_id=candidate.shot_id,
            selection={
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            },
            expected_selection_revision=pool.selection_revision,
            expected_current_selection=(
                model_to_dict(pool.selected) if pool.selected is not None else None
            ),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
