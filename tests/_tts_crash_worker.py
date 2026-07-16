"""Subprocess helper for iter121 real os._exit crash windows."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src import paths
from src.drama_schemas import TtsAuthorization, TtsProviderCapability, UtteranceSpec
from src.drama_tts_attempt_store import (
    TtsAdapterIdentity,
    TtsAttemptReconciliationRequired,
    run_tts_attempt,
)


def _counter(path: Path, key: str) -> None:
    current = json.loads(path.read_text()) if path.exists() else {"synthesis": 0, "download": 0}
    current[key] += 1
    path.write_text(json.dumps(current))


class Adapter:
    def __init__(self, bundle: dict) -> None:
        self.identity = TtsAdapterIdentity(**bundle["identity"])
        self.counter = Path(bundle["counter"])
        self.wav = bytes.fromhex(bundle["wav_hex"])

    def synthesize(self, spec, *, text: str) -> str:
        _counter(self.counter, "synthesis")
        return f"worker-{spec.input_fingerprint[:24]}"

    def download(self, spec, *, provider_request_id: str) -> bytes:
        _counter(self.counter, "download")
        return self.wav


def main() -> int:
    bundle = json.loads(Path(sys.argv[1]).read_text())
    phase = sys.argv[2]
    paths.WORKSPACE_DIR = Path(bundle["workspace_root"])
    utterance = UtteranceSpec(**bundle["utterance"])
    capability = TtsProviderCapability(**bundle["capability"])
    authorization = TtsAuthorization(**bundle["authorization"])

    def crash(current: str) -> None:
        if current == phase:
            os._exit(73)

    try:
        run_tts_attempt(
            bundle["workspace"], utterance,
            capability=capability, authorization=authorization,
            adapter=Adapter(bundle), crash_hook=crash,
        )
    except TtsAttemptReconciliationRequired:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
