from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config import ROOT
from .utils import append_jsonl, ensure_dir


STATE_LOG = ROOT / "logs" / "run_state.jsonl"


def log_event(step: str, status: str, **payload: Any) -> None:
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "step": step,
        "status": status,
    }
    record.update(payload)
    append_jsonl(STATE_LOG, record)


def output_done(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def write_text_atomic(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)

