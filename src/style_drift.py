from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from . import paths, style_fingerprint
from .utils import read_json_optional, write_json


SCHEMA_VERSION = 1
MAX_NORMALIZED_DELTA = 3.0
WARN_THRESHOLD = 0.35
RED_THRESHOLD = 0.55
DEFAULT_REPORT_LIMIT = 10
TOP_DIMENSIONS_LIMIT = 5

_META_RE = re.compile(r"^chapter_(\d{2,})\.meta\.json$")


def fingerprint_text(
    text: str,
    *,
    chapter: int | None = None,
    config: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    cfg = config or style_fingerprint.load_style_fingerprint_config()
    payload: Dict[str, Any] = {
        "status": "ok",
        "schema_version": style_fingerprint.SCHEMA_VERSION,
        "fingerprint_version": str(cfg.get("fingerprint_version") or style_fingerprint.FINGERPRINT_VERSION),
        "language": str(cfg.get("language") or "zh"),
        "metrics": style_fingerprint.calculate_metrics(text, cfg),
    }
    if chapter is not None:
        payload["chapter"] = int(chapter)
    return payload


def load_baseline(path: Path | None = None) -> Dict[str, Any]:
    baseline_path = path or paths.style_fingerprint_baseline_path()
    data = read_json_optional(baseline_path, None)
    if not isinstance(data, dict):
        return {
            "status": "missing",
            "baseline_path": str(baseline_path),
            "metrics": {},
            "tolerance": {},
            "weights": {},
            "dimension_reliability": {},
        }
    return data


def compare_to_baseline(
    current_metrics: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    top_n: int = TOP_DIMENSIONS_LIMIT,
) -> Dict[str, Any]:
    baseline_data = dict(load_baseline() if baseline is None else baseline)
    basis = _basis(baseline_data)
    status = str(baseline_data.get("status") or "")
    if status != "ok":
        reason = "baseline_missing" if status in {"", "missing"} else f"baseline_{status}"
        return _skipped(reason, basis=basis)

    baseline_metrics = baseline_data.get("metrics")
    tolerance = baseline_data.get("tolerance")
    weights = baseline_data.get("weights")
    reliability = baseline_data.get("dimension_reliability")
    if not isinstance(baseline_metrics, Mapping) or not isinstance(tolerance, Mapping) or not isinstance(weights, Mapping):
        return _skipped("baseline_incomplete", basis=basis)
    if not isinstance(reliability, Mapping):
        return _skipped("baseline_reliability_missing", basis=basis)

    dimensions: list[Dict[str, Any]] = []
    skipped: list[Dict[str, str]] = []
    weighted_sum = 0.0
    weight_sum = 0.0

    for key in style_fingerprint.DRIFT_METRIC_KEYS:
        current_value = _finite_float(current_metrics.get(key))
        baseline_value = _finite_float(baseline_metrics.get(key))
        tol = _finite_float(tolerance.get(key))
        weight = _finite_float(weights.get(key))
        rel = reliability.get(key)

        reason = ""
        if current_value is None:
            reason = "current_missing_or_nonfinite"
        elif baseline_value is None:
            reason = "baseline_missing_or_nonfinite"
        elif tol is None or tol <= 0:
            reason = "tolerance_missing_or_nonpositive"
        elif weight is None or weight <= 0:
            reason = "weight_missing_or_nonpositive"
        elif not _reliable(rel):
            reason = "low_reliability"
        if reason:
            skipped.append({"dimension": key, "reason": reason})
            continue

        normalized_delta = min(abs(current_value - baseline_value) / tol, MAX_NORMALIZED_DELTA)
        dimension_score = normalized_delta / MAX_NORMALIZED_DELTA
        weighted_delta = dimension_score * weight
        dimensions.append(
            {
                "dimension": key,
                "current_value": _round(current_value),
                "baseline_value": _round(baseline_value),
                "tolerance": _round(tol),
                "normalized_delta": _round(normalized_delta),
                "dimension_score": _round(dimension_score),
                "weight": _round(weight),
                "weighted_delta": _round(weighted_delta),
                "reliability": _reliability_summary(rel),
            }
        )
        weighted_sum += weighted_delta
        weight_sum += weight

    if not dimensions or weight_sum <= 0:
        return _skipped("no_comparable_dimensions", basis=basis, skipped_dimensions=skipped)

    score = _round(min(1.0, max(0.0, weighted_sum / weight_sum)))
    top_dimensions = sorted(
        dimensions,
        key=lambda item: (-float(item.get("weighted_delta", 0.0)), str(item.get("dimension", ""))),
    )[: max(1, _safe_int(top_n, TOP_DIMENSIONS_LIMIT))]
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "severity": _severity(score),
        "style_drift_score": score,
        "top_dimensions": top_dimensions,
        "skipped_dimensions": skipped,
        "basis": basis,
    }


def annotate_meta(
    meta: Mapping[str, Any],
    draft_text: str,
    *,
    chapter: int,
    baseline_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    updated = dict(meta)
    try:
        fingerprint = fingerprint_text(draft_text, chapter=chapter, config=config)
        drift = compare_to_baseline(fingerprint.get("metrics", {}), load_baseline(baseline_path))
    except Exception as exc:  # style drift must never block writer persistence.
        fingerprint = {
            "status": "skipped",
            "schema_version": style_fingerprint.SCHEMA_VERSION,
            "chapter": int(chapter),
            "metrics": {},
            "reason": "analysis_failed",
            "error_type": type(exc).__name__,
        }
        drift = _skipped("analysis_failed", basis={"status": "unknown", "baseline_hash": ""})
    updated["style_fingerprint"] = fingerprint
    updated["style_drift"] = drift
    baseline_hash = drift.get("basis", {}).get("baseline_hash") if isinstance(drift.get("basis"), Mapping) else ""
    if baseline_hash:
        updated["baseline_hash"] = baseline_hash
    else:
        updated.pop("baseline_hash", None)
    return updated


def analyze_chapter(
    chapter: int,
    *,
    drafts_dir: Path | None = None,
    baseline_path: Path | None = None,
    write_meta: bool = True,
    config: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    draft_dir = drafts_dir or paths.drafts_dir()
    if chapter <= 0:
        return {"status": "invalid_chapter", "chapter": chapter, "style_drift": _skipped("invalid_chapter")}
    draft_path = draft_dir / f"chapter_{chapter:02d}.md"
    if not draft_path.exists():
        return {"status": "missing_draft", "chapter": chapter, "path": str(draft_path), "style_drift": _skipped("missing_draft")}
    try:
        text = draft_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "status": "read_failed",
            "chapter": chapter,
            "path": str(draft_path),
            "error": type(exc).__name__,
            "style_drift": _skipped("read_failed"),
        }

    fingerprint = fingerprint_text(text, chapter=chapter, config=config)
    drift = compare_to_baseline(fingerprint["metrics"], load_baseline(baseline_path))
    result: Dict[str, Any] = {
        "status": str(drift.get("status") or "ok"),
        "chapter": chapter,
        "style_fingerprint": fingerprint,
        "style_drift": drift,
        "baseline_hash": _basis_hash(drift),
        "meta_written": False,
    }

    meta_path = draft_dir / f"chapter_{chapter:02d}.meta.json"
    if write_meta and meta_path.exists():
        meta = read_json_optional(meta_path, {})
        if isinstance(meta, dict) and meta:
            merged = dict(meta)
            merged["style_fingerprint"] = fingerprint
            merged["style_drift"] = drift
            if result["baseline_hash"]:
                merged["baseline_hash"] = result["baseline_hash"]
            else:
                merged.pop("baseline_hash", None)
            write_json(meta_path, merged)
            result["meta_written"] = True
            result["meta_path"] = str(meta_path)
    return result


def style_drift_report(
    *,
    limit: int = DEFAULT_REPORT_LIMIT,
    drafts_dir: Path | None = None,
) -> Dict[str, Any]:
    draft_dir = drafts_dir or paths.drafts_dir()
    capped = max(1, min(_safe_int(limit, DEFAULT_REPORT_LIMIT), 200))
    rows: list[Dict[str, Any]] = []
    if draft_dir.exists():
        for path in draft_dir.glob("chapter_*.meta.json"):
            match = _META_RE.match(path.name)
            if not match:
                continue
            chapter_no = int(match.group(1))
            meta = read_json_optional(path, {})
            if not isinstance(meta, dict):
                meta = {}
            drift_present = isinstance(meta.get("style_drift"), dict)
            drift = meta.get("style_drift") if drift_present else None
            if not drift_present:
                drift = _skipped("missing_style_drift")
            rows.append(
                {
                    "chapter": chapter_no,
                    "status": drift.get("status", "skipped"),
                    "severity": drift.get("severity", "skipped"),
                    "style_drift_score": drift.get("style_drift_score"),
                    "baseline_hash": _basis_hash(drift),
                    "top_dimensions": drift.get("top_dimensions", []),
                    "reason": drift.get("reason", ""),
                }
            )
    rows.sort(key=lambda item: int(item.get("chapter", 0)), reverse=True)
    window = rows[:capped]
    severity_counts: Dict[str, int] = {}
    for row in window:
        key = str(row.get("severity") or "skipped")
        severity_counts[key] = severity_counts.get(key, 0) + 1
    return {
        "status": "ok",
        "limit": capped,
        "window_order": "chapter_no_desc",
        "chapters_considered": [row["chapter"] for row in window],
        "severity_counts": severity_counts,
        "chapters": window,
    }


def _skipped(
    reason: str,
    *,
    basis: Mapping[str, Any] | None = None,
    skipped_dimensions: Sequence[Mapping[str, str]] | None = None,
) -> Dict[str, Any]:
    return {
        "status": "skipped",
        "schema_version": SCHEMA_VERSION,
        "severity": "skipped",
        "style_drift_score": None,
        "reason": reason,
        "top_dimensions": [],
        "skipped_dimensions": list(skipped_dimensions or []),
        "basis": dict(basis or {}),
    }


def _basis(baseline: Mapping[str, Any]) -> Dict[str, Any]:
    quality = baseline.get("baseline_quality") if isinstance(baseline.get("baseline_quality"), Mapping) else {}
    return {
        "status": str(baseline.get("status") or ""),
        "schema_version": baseline.get("schema_version"),
        "fingerprint_version": str(baseline.get("fingerprint_version") or ""),
        "language": str(baseline.get("language") or ""),
        "baseline_hash": str(baseline.get("baseline_hash") or baseline.get("hash") or ""),
        "sample_count": _safe_int(baseline.get("sample_count") or quality.get("sample_count"), 0),
        "baseline_quality_status": str(quality.get("status") or ""),
        "baseline_quality_confidence": _finite_float(quality.get("confidence")),
    }


def _basis_hash(drift: Mapping[str, Any]) -> str:
    basis = drift.get("basis")
    if not isinstance(basis, Mapping):
        return ""
    return str(basis.get("baseline_hash") or "")


def _severity(score: float) -> str:
    if score >= RED_THRESHOLD:
        return "red"
    if score >= WARN_THRESHOLD:
        return "warn"
    return "ok"


def _reliable(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    level = str(value.get("level") or "").lower()
    confidence = _finite_float(value.get("confidence"))
    if level == "low":
        return False
    if confidence is None:
        return False
    return confidence >= 0.5


def _reliability_summary(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "level": str(value.get("level") or ""),
        "confidence": _finite_float(value.get("confidence")),
    }


def _finite_float(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _round(value: float) -> float:
    return round(float(value), 6)
