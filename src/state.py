from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config import ROOT
from .utils import append_jsonl, ensure_dir


# Legacy constant — kept for iter 014-016 test backward compat.
STATE_LOG = ROOT / "logs" / "run_state.jsonl"


def _state_log() -> Path:
    from . import paths
    return paths.run_state_log_path() if paths.workspace_name() else STATE_LOG


def log_event(step: str, status: str, **payload: Any) -> None:
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "status": status,
    }
    record.update(payload)
    append_jsonl(_state_log(), record)


def output_done(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def write_text_atomic(path: Path, text: str) -> None:
    # iter 048d (A5): per-writer tmp suffix prevents the collision where two
    # threads writing the same target (e.g. PUT /outline racing the debater
    # job, both go through write_text_atomic) would both target ``foo.md.tmp``
    # and corrupt each other mid-write before either could ``replace``. The
    # ``pid.tid`` suffix gives each in-flight writer its own private tmp;
    # ``replace`` is still POSIX-atomic at the destination, so the final
    # file is whoever finished last, intact.
    ensure_dir(path.parent)
    tmp = path.with_suffix(
        path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}"
    )
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

