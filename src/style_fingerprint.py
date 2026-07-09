from __future__ import annotations

import math
import re
from copy import deepcopy
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import load_config
from .utils import sha256_data, sha256_text, write_json


SCHEMA_VERSION = 1
FINGERPRINT_VERSION = "local-stat-v1"

METRIC_KEYS = [
    "char_count",
    "chinese_char_count",
    "sentence_count",
    "avg_sentence_length",
    "sentence_p50",
    "sentence_p90",
    "short_sentence_ratio",
    "long_sentence_ratio",
    "paragraph_count",
    "avg_paragraph_chars",
    "dialogue_line_ratio",
    "quote_span_ratio",
    "punctuation_density",
    "question_exclaim_density",
    "ellipsis_density",
    "contrast_sentence_density",
    "ai_cliche_density",
    "sensory_imagery_density",
    "exposition_connector_density",
]

DRIFT_METRIC_KEYS = [
    key for key in METRIC_KEYS if key not in {"char_count", "chinese_char_count", "sentence_count", "paragraph_count"}
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "fingerprint_version": FINGERPRINT_VERSION,
    "language": "zh",
    "source": {
        "min_samples": 1,
        "min_total_chars": 500,
        "good_sample_count": 3,
        "good_total_chars": 4000,
    },
    "sentence": {
        "short_chars_max": 12,
        "long_chars_min": 45,
    },
    "tolerance": {
        "stdev_multiplier": 1.5,
        "relative_floor_ratio": 0.12,
        "default_floor": 0.01,
        "metric_floors": {},
    },
    "weights": {key: 1.0 for key in DRIFT_METRIC_KEYS},
    "lexicons": {
        "ai_cliche_terms": [],
        "sensory_imagery_terms": [],
        "exposition_connector_terms": [],
        "contrast_patterns": [],
    },
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CONTENT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+|…+|\.{2,}|\n+")
_PUNCT_RE = re.compile(r"[，。！？；：、,.!?;:《》“”‘’\"'（）()\[\]【】—…-]")
_QUOTE_SPAN_RE = re.compile(r"[“\"「『](.*?)[”\"」』]", re.S)
_DIALOGUE_LINE_RE = re.compile(r"^\s*[“\"「『\-—]|[“\"「『].+[”\"」』]")


def load_style_fingerprint_config() -> Dict[str, Any]:
    loaded = load_config("style_fingerprint.yaml")
    merged = _deep_merge(DEFAULT_CONFIG, loaded)
    linter_terms = _load_linter_ai_cliche_terms()
    current_terms = _string_list(merged.get("lexicons", {}).get("ai_cliche_terms"))
    if not current_terms and linter_terms:
        merged.setdefault("lexicons", {})["ai_cliche_terms"] = linter_terms
    return merged


def calculate_metrics(text: str, config: Mapping[str, Any] | None = None) -> Dict[str, float | int]:
    cfg = config or load_style_fingerprint_config()
    sentence_cfg = cfg.get("sentence", {}) if isinstance(cfg.get("sentence"), Mapping) else {}
    short_max = _safe_int(sentence_cfg.get("short_chars_max"), 12)
    long_min = _safe_int(sentence_cfg.get("long_chars_min"), 45)
    lexicons = cfg.get("lexicons", {}) if isinstance(cfg.get("lexicons"), Mapping) else {}

    normalized = _normalize_text(text)
    char_count = len(normalized)
    chinese_char_count = len(_CJK_RE.findall(normalized))
    content_chars = _content_char_count(normalized)
    sentences = _split_sentences(normalized)
    sentence_lengths = [_content_char_count(sentence) for sentence in sentences]
    sentence_lengths = [length for length in sentence_lengths if length > 0]
    sentence_count = len(sentence_lengths)
    paragraphs = _paragraphs(normalized)
    paragraph_lengths = [_content_char_count(paragraph) for paragraph in paragraphs]
    paragraph_count = len(paragraph_lengths)
    lines = [line.strip() for line in normalized.splitlines() if _content_char_count(line) > 0]
    dialogue_lines = sum(1 for line in lines if _DIALOGUE_LINE_RE.search(line))
    dialogue_line_count = len(lines) or paragraph_count
    quote_chars = sum(_content_char_count(match.group(1)) for match in _QUOTE_SPAN_RE.finditer(normalized))

    contrast_patterns = _compile_patterns(lexicons.get("contrast_patterns"))
    contrast_hits = sum(1 for sentence in sentences if any(pattern.search(sentence) for pattern in contrast_patterns))

    metrics: Dict[str, float | int] = {
        "char_count": char_count,
        "chinese_char_count": chinese_char_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": _round(_mean(sentence_lengths)),
        "sentence_p50": _round(_percentile(sentence_lengths, 0.50)),
        "sentence_p90": _round(_percentile(sentence_lengths, 0.90)),
        "short_sentence_ratio": _round(_ratio(sum(1 for n in sentence_lengths if n <= short_max), sentence_count)),
        "long_sentence_ratio": _round(_ratio(sum(1 for n in sentence_lengths if n >= long_min), sentence_count)),
        "paragraph_count": paragraph_count,
        "avg_paragraph_chars": _round(_mean(paragraph_lengths)),
        "dialogue_line_ratio": _round(_ratio(dialogue_lines, dialogue_line_count)),
        "quote_span_ratio": _round(_ratio(quote_chars, content_chars)),
        "punctuation_density": _round(_ratio(len(_PUNCT_RE.findall(normalized)), content_chars)),
        "question_exclaim_density": _round(_ratio(len(re.findall(r"[！？!?]", normalized)), content_chars)),
        "ellipsis_density": _round(_ratio(len(re.findall(r"…|\.{3}", normalized)), content_chars)),
        "contrast_sentence_density": _round(_ratio(contrast_hits, sentence_count)),
        "ai_cliche_density": _round(_ratio(_term_hits(normalized, lexicons.get("ai_cliche_terms")), content_chars)),
        "sensory_imagery_density": _round(_ratio(_term_hits(normalized, lexicons.get("sensory_imagery_terms")), content_chars)),
        "exposition_connector_density": _round(_ratio(_term_hits(normalized, lexicons.get("exposition_connector_terms")), content_chars)),
    }
    return metrics


def build_baseline(
    *,
    style_examples_dir: Path | None = None,
    output_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    write: bool = True,
) -> Dict[str, Any]:
    cfg = dict(config or load_style_fingerprint_config())
    source_dir = style_examples_dir or paths.style_examples_dir()
    baseline_path = output_path or paths.style_fingerprint_baseline_path()
    samples = _load_samples(source_dir)
    total_chars = sum(sample["char_count"] for sample in samples)
    source_cfg = cfg.get("source", {}) if isinstance(cfg.get("source"), Mapping) else {}
    min_samples = _safe_int(source_cfg.get("min_samples"), 1)
    min_total_chars = _safe_int(source_cfg.get("min_total_chars"), 500)

    if len(samples) < min_samples or total_chars < min_total_chars:
        reason = _insufficient_reason(len(samples), total_chars, min_samples, min_total_chars)
        artifact = _baseline_base(cfg, samples, status="insufficient_source")
        artifact.update(
            {
                "metrics": {},
                "dimension_stats": {},
                "dimension_reliability": {},
                "tolerance": {},
                "baseline_quality": {
                    "sample_count": len(samples),
                    "distinct_source_count": len({sample["label"] for sample in samples}),
                    "total_sample_chars": total_chars,
                    "confidence": 0.0,
                    "status": "insufficient_source",
                    "insufficient_reason": reason,
                },
            }
        )
        digest = _baseline_hash(artifact)
        artifact["baseline_hash"] = digest
        artifact["hash"] = digest
        if write:
            write_json(baseline_path, artifact)
        return artifact

    sample_metrics = [calculate_metrics(sample["text"], cfg) for sample in samples]
    combined_text = "\n\n".join(sample["text"] for sample in samples)
    combined_metrics = calculate_metrics(combined_text, cfg)
    stats = _dimension_stats(sample_metrics)
    reliability = _dimension_reliability(cfg, len(samples), total_chars)
    artifact = _baseline_base(cfg, samples, status="ok")
    artifact.update(
        {
            "metrics": combined_metrics,
            "dimension_stats": stats,
            "dimension_reliability": {key: reliability for key in DRIFT_METRIC_KEYS},
            "tolerance": _dimension_tolerance(cfg, stats),
            "baseline_quality": {
                "sample_count": len(samples),
                "distinct_source_count": len({sample["label"] for sample in samples}),
                "total_sample_chars": total_chars,
                "confidence": reliability["confidence"],
                "status": "ok",
                "insufficient_reason": None,
            },
        }
    )
    digest = _baseline_hash(artifact)
    artifact["baseline_hash"] = digest
    artifact["hash"] = digest
    if write:
        write_json(baseline_path, artifact)
    return artifact


def inspect_draft(
    chapter: int,
    *,
    drafts_dir: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    if chapter <= 0:
        return {"status": "invalid_chapter", "chapter": chapter, "metrics": {}}
    draft_dir = drafts_dir or paths.drafts_dir()
    draft_path = draft_dir / f"chapter_{chapter:02d}.md"
    if not draft_path.exists():
        return {"status": "missing_draft", "chapter": chapter, "path": str(draft_path), "metrics": {}}
    try:
        text = draft_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "read_failed", "chapter": chapter, "path": str(draft_path), "error": type(exc).__name__, "metrics": {}}
    cfg = config or load_style_fingerprint_config()
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "fingerprint_version": str(cfg.get("fingerprint_version") or FINGERPRINT_VERSION),
        "language": str(cfg.get("language") or "zh"),
        "chapter": chapter,
        "metrics": calculate_metrics(text, cfg),
    }


def _baseline_base(cfg: Mapping[str, Any], samples: Sequence[Mapping[str, Any]], *, status: str) -> Dict[str, Any]:
    source_hashes = [
        {"label": sample["label"], "sha256": sample["sha256"], "char_count": sample["char_count"]}
        for sample in samples
    ]
    return {
        "status": status,
        "schema_version": SCHEMA_VERSION,
        "fingerprint_version": str(cfg.get("fingerprint_version") or FINGERPRINT_VERSION),
        "language": str(cfg.get("language") or "zh"),
        "sample_count": len(samples),
        "source_labels": [sample["label"] for sample in samples],
        "source_hashes": source_hashes,
        "weights": _weights(cfg),
    }


def _load_samples(style_examples_dir: Path) -> List[Dict[str, Any]]:
    if not style_examples_dir.exists():
        return []
    samples: List[Dict[str, Any]] = []
    for path in sorted(style_examples_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if not text:
            continue
        samples.append(
            {
                "label": _source_label(path),
                "text": text,
                "sha256": sha256_text(text),
                "char_count": len(text),
            }
        )
    return samples


def _source_label(path: Path) -> str:
    label = re.sub(r"\s+", "_", path.stem.strip())
    return label[:80] or "style_sample"


def _baseline_hash(artifact: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in artifact.items() if key not in {"baseline_hash", "hash"}}
    return sha256_data(payload)


def _dimension_stats(sample_metrics: Sequence[Mapping[str, float | int]]) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for key in DRIFT_METRIC_KEYS:
        values = [float(metrics.get(key, 0.0)) for metrics in sample_metrics]
        stats[key] = {
            "mean": _round(_mean(values)),
            "stdev": _round(_stdev(values)),
            "min": _round(min(values) if values else 0.0),
            "max": _round(max(values) if values else 0.0),
            "p50": _round(_percentile(values, 0.50)),
            "p90": _round(_percentile(values, 0.90)),
        }
    return stats


def _dimension_tolerance(cfg: Mapping[str, Any], stats: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
    tol_cfg = cfg.get("tolerance", {}) if isinstance(cfg.get("tolerance"), Mapping) else {}
    floors = tol_cfg.get("metric_floors", {}) if isinstance(tol_cfg.get("metric_floors"), Mapping) else {}
    stdev_multiplier = _safe_float(tol_cfg.get("stdev_multiplier"), 1.5)
    relative_floor_ratio = _safe_float(tol_cfg.get("relative_floor_ratio"), 0.12)
    default_floor = _safe_float(tol_cfg.get("default_floor"), 0.01)
    tolerance: Dict[str, float] = {}
    for key in DRIFT_METRIC_KEYS:
        item = stats.get(key, {})
        mean = float(item.get("mean", 0.0))
        stdev = float(item.get("stdev", 0.0))
        floor = _safe_float(floors.get(key), default_floor)
        tolerance[key] = _round(max(stdev * stdev_multiplier, abs(mean) * relative_floor_ratio, floor))
    return tolerance


def _dimension_reliability(cfg: Mapping[str, Any], sample_count: int, total_chars: int) -> Dict[str, Any]:
    source_cfg = cfg.get("source", {}) if isinstance(cfg.get("source"), Mapping) else {}
    good_sample_count = _safe_int(source_cfg.get("good_sample_count"), 3)
    good_total_chars = _safe_int(source_cfg.get("good_total_chars"), 4000)
    if sample_count >= good_sample_count and total_chars >= good_total_chars:
        return {"level": "high", "confidence": 0.85}
    if sample_count >= 2 or total_chars >= good_total_chars:
        return {"level": "medium", "confidence": 0.65}
    return {"level": "low", "confidence": 0.45}


def _weights(cfg: Mapping[str, Any]) -> Dict[str, float]:
    weights = cfg.get("weights", {}) if isinstance(cfg.get("weights"), Mapping) else {}
    return {key: _round(_safe_float(weights.get(key), 1.0)) for key in DRIFT_METRIC_KEYS}


def _insufficient_reason(sample_count: int, total_chars: int, min_samples: int, min_total_chars: int) -> str:
    if sample_count < min_samples:
        return f"sample_count<{min_samples}"
    return f"total_sample_chars<{min_total_chars}"


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [part.strip() for part in parts if _content_char_count(part) > 0]


def _paragraphs(text: str) -> List[str]:
    raw = re.split(r"\n\s*\n+", text)
    paragraphs = [part.strip() for part in raw if _content_char_count(part) > 0]
    if paragraphs:
        return paragraphs
    return [line.strip() for line in text.splitlines() if _content_char_count(line) > 0]


def _content_char_count(text: str) -> int:
    return len(_CONTENT_RE.findall(text))


def _term_hits(text: str, terms: Any) -> int:
    return sum(text.count(term) for term in _string_list(terms))


def _compile_patterns(patterns: Any) -> List[re.Pattern[str]]:
    compiled: List[re.Pattern[str]] = []
    for pattern in _string_list(patterns):
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            continue
    return compiled


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [str(item) for item in value if str(item)]


def _mean(values: Sequence[float | int]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _stdev(values: Sequence[float | int]) -> float:
    if not values:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((float(value) - mean) ** 2 for value in values) / len(values))


def _percentile(values: Sequence[float | int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def _ratio(numerator: float | int, denominator: float | int) -> float:
    denom = float(denominator)
    return float(numerator) / denom if denom > 0 else 0.0


def _round(value: float | int) -> float:
    return round(float(value), 6)


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_linter_ai_cliche_terms() -> List[str]:
    cfg = load_config("linter.yaml")
    rules = cfg.get("rules", {}) if isinstance(cfg.get("rules"), Mapping) else {}
    terms_cfg = rules.get("ai_cliche_terms", {}) if isinstance(rules.get("ai_cliche_terms"), Mapping) else {}
    return _string_list(terms_cfg.get("terms"))
