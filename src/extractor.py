from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

try:
    from tqdm import tqdm
except Exception:
    def tqdm(iterable, **_: object):  # type: ignore[no-redef]
        return iterable

from . import paths
from .chapter_splitter import chapter_text, load_manifest
from .config import ROOT, load_config
from .llm_client import LLMClient
from .schemas import ChapterExtraction, EvidenceSpan, model_to_dict, model_to_json_schema
from .state import log_event
from .utils import deep_merge, ensure_dir, read_json, write_json


# Legacy constants — kept for iter 014-016 test backward compat
# (``patch("src.extractor.FAILURES_DIR", ...)`` and friends still work).
EXTRACTED_DIR = ROOT / "data" / "extracted_jsons"
OVERRIDES_DIR = ROOT / "data" / "manual_overrides"
FAILURES_DIR = ROOT / "data" / "extraction_failures"
ROLLING_DIR = ROOT / "data" / "rolling_summaries"
SENTENCE_BOUNDARIES = "。！？\n"
DEFAULT_ROLLING_SUMMARY_CHARS = 4000
DEFAULT_ROLLING_SUMMARY_ITEMS = 12


def _extracted_dir() -> Path:
    return paths.extracted_dir() if paths.workspace_name() else EXTRACTED_DIR


def _overrides_dir() -> Path:
    return paths.manual_overrides_dir() if paths.workspace_name() else OVERRIDES_DIR


def _failures_dir() -> Path:
    return paths.extraction_failures_dir() if paths.workspace_name() else FAILURES_DIR


def _rolling_dir() -> Path:
    return paths.rolling_summaries_dir() if paths.workspace_name() else ROLLING_DIR


def _output_path(chapter_id: str) -> Path:
    return _extracted_dir() / f"{chapter_id}.json"


def _extract_settings() -> Dict[str, Any]:
    cfg = load_config("models.yaml")
    task_cfg = cfg.get("tasks", {}).get("extract", {})
    return {
        "rolling_summary_chars": int(task_cfg.get("rolling_summary_chars", DEFAULT_ROLLING_SUMMARY_CHARS)),
        "rolling_summary_items": int(task_cfg.get("rolling_summary_items", DEFAULT_ROLLING_SUMMARY_ITEMS)),
        "chunk_threshold_chars": int(task_cfg.get("chunk_threshold_chars", 24000)),
        "chunk_count": int(task_cfg.get("chunk_count", 3)),
        "chunk_overlap_chars": int(task_cfg.get("chunk_overlap_chars", 200)),
        # iter055 轨C: 单调用上限。文本 ≤ 此长度则强制单次抽取(绕过分块)——真实判定阈值
        # = max(chunk_threshold, bypass)。缺省 0 → max(threshold,0)=threshold,逐字节兼容。
        "chunk_bypass_max_chars": int(task_cfg.get("chunk_bypass_max_chars", 0)),
    }


def _tail_by_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    boundary_positions = [tail.find(mark) for mark in SENTENCE_BOUNDARIES if tail.find(mark) != -1]
    if boundary_positions:
        start = min(pos + 1 for pos in boundary_positions)
        trimmed = tail[start:].lstrip()
        if trimmed:
            return trimmed
    return tail.lstrip()


def _load_overrides() -> Dict[str, Dict[str, Any]]:
    overrides: Dict[str, Dict[str, Any]] = {}
    for path in sorted(_overrides_dir().glob("*.json")):
        data = read_json(path, {})
        items = data if isinstance(data, list) else [data]
        for item in items:
            chapter_id = item.get("chapter_id") if isinstance(item, dict) else None
            if chapter_id:
                item = dict(item)
                item.setdefault("manual_overrides_applied", []).append(path.name)
                overrides[chapter_id] = deep_merge(overrides.get(chapter_id, {}), item)
    return overrides


def _chapter_line_quote(entry: Dict[str, object], text: str) -> EvidenceSpan:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return EvidenceSpan(
        source_file=str(entry["source_file"]),
        chapter_id=str(entry["chapter_id"]),
        start_line=int(entry["start_line"]),
        end_line=min(int(entry["start_line"]) + 2, int(entry["end_line"])),
        quote=first_line[:280],
        note="chapter opening evidence",
    )


def build_extraction_prompt(entry: Dict[str, object], text: str, previous_summaries: List[str], volume_summary: str) -> List[Dict[str, str]]:
    schema = json.dumps(model_to_json_schema(ChapterExtraction), ensure_ascii=False)
    return [
        {
            "role": "system",
            "content": (
                "你是长篇小说知识提取器。只输出合法 JSON，不要输出 Markdown。"
                "重点提取角色状态、关系变化、伏笔/回收、世界观约束、风格样本和证据行。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"chapter_id: {entry['chapter_id']}\n"
                f"volume_id: {entry['volume_id']}\n"
                f"title: {entry['title']}\n"
                f"source_file: {entry['source_file']}\n"
                f"start_line: {entry['start_line']}\n"
                f"end_line: {entry['end_line']}\n\n"
                f"前 3 章摘要:\n{chr(10).join(previous_summaries[-3:])}\n\n"
                f"本卷累计摘要:\n{volume_summary}\n\n"
                f"输出 JSON Schema:\n{schema}\n\n"
                f"章节正文:\n{text}"
            ),
        },
    ]


def _chunk_text(text: str, chunk_count: int = 3, overlap_chars: int = 200) -> List[str]:
    if chunk_count <= 1 or len(text) <= chunk_count * overlap_chars:
        return [text]
    chunk_size = max(1, len(text) // chunk_count)
    chunks = []
    for index in range(chunk_count):
        start = max(0, index * chunk_size - overlap_chars)
        end = len(text) if index == chunk_count - 1 else min(len(text), (index + 1) * chunk_size + overlap_chars)
        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)
    return chunks


def _dedupe_evidence(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for item in sorted(items, key=lambda span: (str(span.get("source_file", "")), int(span.get("start_line", 0)), str(span.get("quote", "")))):
        key = (
            item.get("source_file"),
            item.get("chapter_id"),
            item.get("start_line"),
            item.get("end_line"),
            item.get("quote"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _merge_key(kind: str, item: Dict[str, Any]) -> tuple:
    if kind == "character_states":
        return (item.get("character", ""), item.get("status", ""), item.get("after", ""))
    if kind == "relationships":
        return tuple(sorted(item.get("characters", []))), item.get("after", "")
    if kind == "foreshadowing":
        return item.get("kind", ""), item.get("description", "")
    if kind == "worldbuilding":
        return item.get("topic", ""), item.get("detail", "")
    if kind == "style_samples":
        return item.get("quote", ""), item.get("note", "")
    return tuple(sorted(item.items()))


def _merge_items(kind: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple, Dict[str, Any]] = {}
    for chunk in chunks:
        for item in chunk.get(kind, []):
            key = _merge_key(kind, item)
            if key not in merged:
                merged[key] = dict(item)
                if "evidence_spans" in merged[key]:
                    merged[key]["evidence_spans"] = list(merged[key].get("evidence_spans", []))
                continue
            if "evidence_spans" in item:
                existing = list(merged[key].get("evidence_spans", []))
                merged[key]["evidence_spans"] = _dedupe_evidence(existing + list(item.get("evidence_spans", [])))
    return list(merged.values())


def _merge_chunk_extractions(
    entry: Dict[str, object],
    chunk_data: List[Dict[str, Any]],
    summarizer: LLMClient,
) -> Dict[str, Any]:
    summaries = "\n".join(data.get("summary", "") for data in chunk_data if data.get("summary"))
    rolling = "\n".join(data.get("rolling_summary", "") for data in chunk_data if data.get("rolling_summary"))
    compact_summary = summarizer.complete_text(
        [
            {"role": "system", "content": "你是章节摘要压缩器。输出 800 字以内中文摘要，不要 Markdown。"},
            {"role": "user", "content": f"章节: {entry['chapter_id']}\n分段摘要:\n{summaries}\n\n滚动摘要:\n{rolling}"},
        ],
        temperature=0,
    ).strip()
    merged = {
        "chapter_id": str(entry["chapter_id"]),
        "volume_id": str(entry["volume_id"]),
        "title": str(entry["title"]),
        "summary": compact_summary[:800],
        "rolling_summary": _tail_by_sentence((rolling or compact_summary)[:2000], 800),
        "character_states": _merge_items("character_states", chunk_data),
        "relationships": _merge_items("relationships", chunk_data),
        "foreshadowing": _merge_items("foreshadowing", chunk_data),
        "worldbuilding": _merge_items("worldbuilding", chunk_data),
        "style_samples": _merge_items("style_samples", chunk_data),
        "evidence_spans": _dedupe_evidence([span for data in chunk_data for span in data.get("evidence_spans", [])]),
    }
    return merged


def _extract_chapter_data(
    entry: Dict[str, object],
    text: str,
    previous_summaries: List[str],
    volume_summary: str,
    client: LLMClient,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    # iter055 轨C: bypass 把单调用上限抬到 max(threshold, bypass)。bypass=0 → 等于
    # threshold(逐字节兼容);--no-chunk 时 extract_all 把 bypass 设极大值 → 必走单调用。
    # settings.get(缺省 0):现存测试手工构造的 settings 无此键,subscript 会 KeyError。
    threshold = max(int(settings["chunk_threshold_chars"]), int(settings.get("chunk_bypass_max_chars", 0)))
    if len(text) <= threshold:
        extraction = client.complete_json(build_extraction_prompt(entry, text, previous_summaries, volume_summary), ChapterExtraction)
        return model_to_dict(extraction)

    chunks = _chunk_text(text, int(settings["chunk_count"]), int(settings["chunk_overlap_chars"]))
    chunk_data = []
    for index, chunk in enumerate(chunks, 1):
        chunk_entry = dict(entry)
        chunk_entry["title"] = f"{entry['title']} chunk {index}/{len(chunks)}"
        extraction = client.complete_json(build_extraction_prompt(chunk_entry, chunk, previous_summaries, volume_summary), ChapterExtraction)
        chunk_data.append(model_to_dict(extraction))
    return _merge_chunk_extractions(entry, chunk_data, LLMClient("compress"))


def _extract_chapter_with_retry(
    entry: Dict[str, object],
    text: str,
    previous_summaries: List[str],
    volume_summary: str,
    client: LLMClient,
    settings: Dict[str, Any],
    *,
    attempts: int,
    chapter_id: str,
) -> Dict[str, Any]:
    """iter055 轨D: 整章级重试。轨B 的 call 级 transient 重试在 complete_text 内救单次请求
    抖动;此层兜「分块合并失败」等整章故障——重跑全章(re-chunk + re-extract + re-merge),
    call 级救不了。attempts=1(per_chapter_attempts 缺省)→ 调一次不重试,逐字节兼容旧行为。"""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _extract_chapter_data(entry, text, previous_summaries, volume_summary, client, settings)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                log_event("extract", "chapter_retry", chapter_id=chapter_id, attempt=attempt, error=str(exc))
    assert last_exc is not None  # attempts>=1 → 循环未 return 必经 except,last_exc 必有值
    raise last_exc


def _rolling_path(volume_id: str) -> Path:
    return _rolling_dir() / f"{volume_id}.json"


def _load_rolling_state(volume_id: str) -> Dict[str, Any]:
    data = read_json(_rolling_path(volume_id), {})
    return {
        "previous_summaries": list(data.get("previous_summaries", [])),
        "previous_chapter_ids": list(data.get("previous_chapter_ids", [])),
        "volume_summary": str(data.get("volume_summary", "")),
    }


def _save_rolling_state(
    volume_id: str,
    previous_summaries: List[str],
    volume_summary: str,
    *,
    previous_chapter_ids: List[str] | None = None,
    max_items: int = DEFAULT_ROLLING_SUMMARY_ITEMS,
    max_chars: int = DEFAULT_ROLLING_SUMMARY_CHARS,
) -> None:
    write_json(
        _rolling_path(volume_id),
        {
            "volume_id": volume_id,
            "previous_summaries": previous_summaries[-max_items:],
            "previous_chapter_ids": (previous_chapter_ids or [])[-max_items:],
            "volume_summary": _tail_by_sentence(volume_summary, max_chars),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _write_failure(entry: Dict[str, object], text: str, exc: Exception, elapsed_ms: Optional[int] = None) -> None:
    failures_dir = _failures_dir()
    ensure_dir(failures_dir)
    chapter_id = str(entry["chapter_id"])
    existing = read_json(failures_dir / f"{chapter_id}.json", {})
    retry_count = int(existing.get("retry_count", 0)) + 1
    failure = {
        "chapter_id": chapter_id,
        "volume_id": str(entry["volume_id"]),
        "source_title": str(entry.get("title", "")),
        "retry_count": retry_count,
        "last_error": f"{type(exc).__name__}: {exc}",
        "error": f"{type(exc).__name__}: {exc}",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "prompt_summary": text[:500],
    }
    if elapsed_ms is not None:
        # iter055 轨D: 失败耗时。≈ per-call 超时值(如 120000ms) ⇒ tunnel 挂起撞超时的特征。
        failure["elapsed_ms"] = elapsed_ms
    write_json(failures_dir / f"{chapter_id}.json", failure)
    log_event(
        "extract", "failure", chapter_id=chapter_id, error=str(exc),
        retry_count=retry_count, elapsed_ms=elapsed_ms,
    )


def _clear_failure(chapter_id: str) -> None:
    path = _failures_dir() / f"{chapter_id}.json"
    if path.exists():
        path.unlink()


class ExtractionBatchFailure(RuntimeError):
    """iter054c: raised by ``extract_all(raise_on_failure=True)`` when one or
    more chapters failed to extract.

    Per-chapter failures are written to ``data/extraction_failures/`` and the
    batch otherwise continues ("extract as much as possible"). That silent-
    swallow left orchestrators blind: when the aetherheartpool relay's
    Cloudflare Tunnel went down (Error 1033 / HTTP 530), an entire
    ``rebuild-for-start`` window failed but ``extract_all`` returned normally
    with a short results list — the orchestrator then built the base on a
    silently-degraded extraction set. Opting into ``raise_on_failure`` lets a
    caller abort loudly instead. Chapters that DID extract are already on disk,
    so a resume re-runs only the failures.
    """

    def __init__(self, failed_ids: List[str], extracted: int) -> None:
        self.failed_ids = list(failed_ids)
        self.extracted = extracted
        preview = ", ".join(self.failed_ids[:5])
        more = f" (+{len(self.failed_ids) - 5} more)" if len(self.failed_ids) > 5 else ""
        super().__init__(
            f"extract_all: {len(self.failed_ids)} chapter(s) failed extraction "
            f"({extracted} ok): {preview}{more}. See data/extraction_failures/ for "
            "last_error (Cloudflare Tunnel 530 = relay outage; re-run resumes)."
        )


def extract_all(
    volume: str = "all",
    limit: Optional[int] = None,
    force: bool = False,
    chapter_ids: Optional[Set[str]] = None,
    raise_on_failure: bool = False,
    no_chunk: bool = False,
    per_chapter_attempts: Optional[int] = None,
) -> List[Dict[str, Any]]:
    ensure_dir(_extracted_dir())
    ensure_dir(_rolling_dir())
    manifest = load_manifest()
    if volume != "all":
        manifest = [entry for entry in manifest if str(entry["volume_id"]) == volume]
    if chapter_ids is not None:
        manifest = [entry for entry in manifest if str(entry["chapter_id"]) in chapter_ids]
    if limit:
        manifest = manifest[:limit]

    client = LLMClient("extract")
    extract_settings = _extract_settings()
    # iter055 轨C: --no-chunk 把 bypass 抬到极大值 → 每章必走单调用分支(规避分块边界
    # 漏抽/合并失真,用于诊断与短章实跑)。复用同一 effective_threshold 旋钮,不改下游签名。
    if no_chunk:
        extract_settings = dict(extract_settings)
        extract_settings["chunk_bypass_max_chars"] = 10 ** 9
    rolling_items = int(extract_settings["rolling_summary_items"])
    rolling_chars = int(extract_settings["rolling_summary_chars"])
    overrides = _load_overrides()
    previous_summaries_by_volume: Dict[str, Deque[str]] = {}
    previous_chapter_ids_by_volume: Dict[str, Deque[str]] = {}
    volume_summary: Dict[str, str] = {}
    results: List[Dict[str, Any]] = []
    failed_ids: List[str] = []

    for entry in tqdm(manifest, desc="extract"):
        chapter_id = str(entry["chapter_id"])
        out_path = _output_path(chapter_id)
        vid = str(entry["volume_id"])
        if vid not in previous_summaries_by_volume:
            rolling = _load_rolling_state(vid)
            previous_summaries_by_volume[vid] = deque(rolling["previous_summaries"], maxlen=rolling_items)
            previous_chapter_ids_by_volume[vid] = deque(rolling["previous_chapter_ids"], maxlen=rolling_items)
            volume_summary[vid] = rolling["volume_summary"]
        if out_path.exists() and not force:
            data = read_json(out_path, {})
            results.append(data)
            previous_summaries_by_volume.setdefault(vid, deque(maxlen=rolling_items)).append(data.get("summary", ""))
            previous_chapter_ids_by_volume.setdefault(vid, deque(maxlen=rolling_items)).append(chapter_id)
            volume_summary[vid] = _tail_by_sentence(volume_summary.get(vid, "") + "\n" + data.get("summary", ""), rolling_chars)
            _save_rolling_state(
                vid,
                list(previous_summaries_by_volume[vid]),
                volume_summary[vid],
                previous_chapter_ids=list(previous_chapter_ids_by_volume[vid]),
                max_items=rolling_items,
                max_chars=rolling_chars,
            )
            continue

        text = chapter_text(entry)
        started_at = time.monotonic()  # iter055 轨D: 每章计时,暴露慢/挂起章(tunnel 卡到超时)
        try:
            data = _extract_chapter_with_retry(
                entry,
                text,
                list(previous_summaries_by_volume.get(vid, [])),
                volume_summary.get(vid, ""),
                client,
                extract_settings,
                attempts=max(1, int(per_chapter_attempts or 1)),
                chapter_id=chapter_id,
            )
            data.setdefault("evidence_spans", [])
            if not data["evidence_spans"]:
                data["evidence_spans"].append(model_to_dict(_chapter_line_quote(entry, text)))
            if chapter_id in overrides:
                data = deep_merge(data, overrides[chapter_id])
                applied = data.setdefault("manual_overrides_applied", [])
                if isinstance(applied, list):
                    applied.extend(overrides[chapter_id].get("manual_overrides_applied", []))
            write_json(out_path, data)
            _clear_failure(chapter_id)
            log_event(
                "extract", "done", chapter_id=chapter_id, output=str(out_path),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            results.append(data)
            previous_summaries_by_volume.setdefault(vid, deque(maxlen=rolling_items)).append(data.get("summary", ""))
            previous_chapter_ids_by_volume.setdefault(vid, deque(maxlen=rolling_items)).append(chapter_id)
            volume_summary[vid] = _tail_by_sentence(volume_summary.get(vid, "") + "\n" + data.get("summary", ""), rolling_chars)
            _save_rolling_state(
                vid,
                list(previous_summaries_by_volume[vid]),
                volume_summary[vid],
                previous_chapter_ids=list(previous_chapter_ids_by_volume[vid]),
                max_items=rolling_items,
                max_chars=rolling_chars,
            )
        except Exception as exc:
            _write_failure(entry, text, exc, elapsed_ms=int((time.monotonic() - started_at) * 1000))
            failed_ids.append(chapter_id)
    # iter054c: surface the batch outcome so orchestrators aren't blind to a
    # silently-degraded extraction set (per-chapter failures are written to
    # data/extraction_failures/ and otherwise swallowed). Log a summary on any
    # failure; raise only when the caller opts in (rebuild-for-start), keeping
    # greenfield onboarding / retry_failures' "extract as much as possible"
    # semantics and the no-failure path byte-identical.
    if failed_ids:
        log_event(
            "extract",
            "batch_failures",
            extracted=len(results),
            failed=len(failed_ids),
            failed_ids=failed_ids,
        )
        if raise_on_failure:
            raise ExtractionBatchFailure(failed_ids, len(results))
    return results


def retry_failures() -> List[Dict[str, Any]]:
    failure_ids = {path.stem for path in _failures_dir().glob("*.json")}
    if not failure_ids:
        return []
    return extract_all(volume="all", force=True, chapter_ids=failure_ids)
