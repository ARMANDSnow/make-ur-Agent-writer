"""Shared synthetic C2 shot-image candidate fixtures for iter113 tests."""

from __future__ import annotations

import zlib

from src import drama_shot_image_candidate_store, drama_shot_image_store
from tests._drama_shot_image_base import DramaShotImageFixture


class DramaShotImageCandidateFixture(DramaShotImageFixture):
    @staticmethod
    def _png(
        *,
        width: int = 1,
        height: int = 1,
        rgba: bytes = b"\x11\x22\x33\xff",
    ) -> bytes:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                len(payload).to_bytes(4, "big")
                + kind
                + payload
                + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        ihdr = (
            width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
            + bytes([8, 6, 0, 0, 0])
        )
        rows = b"".join(b"\x00" + rgba * width for _ in range(height))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b"")
        )

    def _seed_candidate_sources(
        self,
        name: str = "shot-candidates",
        *,
        character_artifacts: bool = True,
    ):
        sources = self._seed_shot_image_sources(
            name,
            character_artifacts=character_artifacts,
        )
        plan = drama_shot_image_store.create_episode_shot_image_plan(
            name,
            shot_character_ids=sources["character_mapping"],
            reference_policy=sources["policy"],
        )
        sources["shot_image_plan"] = plan
        return sources

    @staticmethod
    def _create_manifest(name: str):
        return drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
            name
        )

    def _append_candidate(
        self,
        name: str,
        manifest,
        shot_id: str,
        *,
        rgba: bytes = b"\x11\x22\x33\xff",
    ):
        return drama_shot_image_candidate_store.append_local_shot_image_candidate(
            name,
            shot_id=shot_id,
            png_bytes=self._png(rgba=rgba),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
