#!/usr/bin/env python3
"""iter027 smoke test: gpt-5.5 long-generation under streaming.

The 中转站 endpoint recently added a "send a blank character every 45s to keep
the Cloudflare channel alive" feature. Before that fix, gpt-5.5 long-extract
calls reliably hit Cloudflare 524 around the 100s mark when not streamed.

This script reproduces that exact shape:
  - extract-task config (max_tokens=3500, temperature=0.1)
  - ~3000-token Chinese chapter as the user content
  - asks for a verbose JSON-shaped extraction (entities + relationships +
    foreshadowing) so the response itself is long enough to push past 120s
  - explicit stream=True so we exercise the keep-alive path

It overrides OPENAI_MODEL via os.environ BEFORE importing LLMClient so the
.env file (currently set to mini for the live auto-pipeline) is left alone.

Run:
    OPENAI_STREAM=1 /usr/bin/python3 scripts/iter027_smoke_55_longgen.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# --- Env override BEFORE importing LLMClient -------------------------------
# OPENAI_API_KEY and OPENAI_BASE_URL stay as .env already configures them
# (user-provided 中转站 endpoint, valid for both gpt-5.5 and mini). We only
# swap the model so this script doesn't fight the live auto-pipeline (which
# is using mini via .env).
os.environ["OPENAI_MODEL"] = "openai/gpt-5.5"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing after env tweak so get_model_config sees the new model.
from src.llm_client import LLMClient  # noqa: E402


CHAPTER_PATH = (
    ROOT
    / "workspaces"
    / "longzu"
    / "data"
    / "normalized_texts"
    / "longzu_1.txt"  # = 龙族Ⅰ火之晨曦
)
OUTPUT_PATH = ROOT / "logs" / "iter027_gpt55_longgen_smoke.json"
PROMPT_CHARS = 6000  # ~3000 tokens of Chinese


def build_messages() -> list[dict[str, str]]:
    chapter_text = CHAPTER_PATH.read_text(encoding="utf-8")[:PROMPT_CHARS]
    system = (
        "你是一个龙族小说设定提取助手。给定一段章节正文，输出尽量详尽的中文 JSON "
        "提取，覆盖：人物（含别名、状态、能力）、关系（包含双向）、伏笔/悬念、"
        "世界观设定（学院、血统、组织）、关键道具/事件。"
        "字段尽量丰富、描述尽量长（每条 description 不少于 80 字），目标是让"
        "整段输出 ≥ 3000 字，用来压测长生成。"
        "格式：返回一个 JSON 对象，键包括 entities/relationships/foreshadowing/"
        "worldbuilding/items/events，每个键下是对象数组。"
    )
    user = (
        "以下是章节正文，请按要求提取（输出尽量详细，不要省略）：\n\n"
        f"<<<CHAPTER>>>\n{chapter_text}\n<<<END>>>"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def main() -> int:
    summary: dict = {
        "script": "iter027_smoke_55_longgen",
        "model_requested": os.environ["OPENAI_MODEL"],
        "stream_explicit": True,
        "openai_stream_env": os.environ.get("OPENAI_STREAM", ""),
        "chapter_source": str(CHAPTER_PATH.relative_to(ROOT)),
        "prompt_chars": 0,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    if not CHAPTER_PATH.exists():
        summary["status"] = "error"
        summary["error_class"] = "FileNotFoundError"
        summary["error_msg"] = f"chapter source missing: {CHAPTER_PATH}"
        _write_summary(summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 2

    messages = build_messages()
    summary["prompt_chars"] = sum(len(m["content"]) for m in messages)

    client = LLMClient("extract")
    summary["model_resolved"] = client.model
    summary["max_tokens"] = client.config.get("max_tokens")
    summary["base_url"] = client.config.get("base_url")
    summary["stream_default"] = client.stream_default

    started = time.monotonic()
    try:
        response = client.complete_text(messages, stream=True)
    except Exception as exc:  # noqa: BLE001 — we want everything
        elapsed = time.monotonic() - started
        err_text = f"{type(exc).__name__}: {exc}"
        summary["status"] = "error"
        summary["elapsed_seconds"] = round(elapsed, 2)
        summary["error_class"] = type(exc).__name__
        summary["error_msg"] = str(exc)[:1000]
        summary["traceback_tail"] = traceback.format_exc().splitlines()[-6:]
        # Classify common Cloudflare / mid-stream failure modes.
        lowered = err_text.lower()
        if "524" in err_text:
            summary["failure_mode"] = "cloudflare_524"
        elif "midstreamfallback" in lowered or "incomplete chunked read" in lowered:
            summary["failure_mode"] = "mid_stream_peer_closed"
        elif "timeout" in lowered or "timed out" in lowered:
            summary["failure_mode"] = "timeout_other"
        elif "connection" in lowered and ("reset" in lowered or "closed" in lowered):
            summary["failure_mode"] = "connection_closed"
        else:
            summary["failure_mode"] = "other"
        _write_summary(summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 1

    elapsed = time.monotonic() - started
    summary["status"] = "ok"
    summary["elapsed_seconds"] = round(elapsed, 2)
    summary["response_chars"] = len(response)
    summary["response_tokens_est"] = max(1, round(len(response) / 1.6))
    preview = response.strip().replace("\n", " ")[:100]
    summary["response_preview"] = preview
    summary["streaming_held_connection"] = elapsed > 100  # past Cloudflare's 100s edge
    _write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def _write_summary(summary: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
