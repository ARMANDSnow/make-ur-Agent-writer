from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from . import paths, style_fingerprint
from .schemas import StyleRewriteDirective
from .utils import read_json_optional, write_json


SCHEMA_VERSION = 1
MAX_NORMALIZED_DELTA = 3.0
WARN_THRESHOLD = 0.35
RED_THRESHOLD = 0.55
DEFAULT_REPORT_LIMIT = 10
TOP_DIMENSIONS_LIMIT = 5
MAX_REWRITE_DIRECTIVES = 5
DEFAULT_MIN_IMPROVEMENT = 0.08

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
    loaded = dict(data)
    fingerprint_version = str(loaded.get("fingerprint_version") or "")
    if fingerprint_version != style_fingerprint.FINGERPRINT_VERSION:
        loaded["status"] = "incompatible_version"
        return loaded
    if style_fingerprint.validate_baseline_hash(loaded) != "ok":
        loaded["status"] = "invalid_hash"
    return loaded


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
    aggregate_terms: list[tuple[float, float]] = []

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
        aggregate_terms.append((dimension_score, weight))

    if not dimensions or not aggregate_terms:
        return _skipped("no_comparable_dimensions", basis=basis, skipped_dimensions=skipped)

    # Scale by the largest weight before summing.  Adding several individually
    # finite ~1e308 weights otherwise overflows to Infinity; the subsequent
    # Infinity/Infinity becomes NaN and used to be coerced into a green 0.0.
    max_weight = max(weight for _dimension_score, weight in aggregate_terms)
    try:
        scaled_weights = [weight / max_weight for _dimension_score, weight in aggregate_terms]
        scaled_weighted = [
            dimension_score * scaled_weight
            for (dimension_score, _weight), scaled_weight in zip(aggregate_terms, scaled_weights)
        ]
        weight_sum = math.fsum(scaled_weights)
        weighted_sum = math.fsum(scaled_weighted)
        raw_score = weighted_sum / weight_sum
    except (ArithmeticError, OverflowError, ValueError, ZeroDivisionError):
        return _skipped("invalid_weight_aggregation", basis=basis, skipped_dimensions=skipped)
    if not all(math.isfinite(value) for value in (max_weight, weight_sum, weighted_sum, raw_score)):
        return _skipped("invalid_weight_aggregation", basis=basis, skipped_dimensions=skipped)

    score = _round(min(1.0, max(0.0, raw_score)))
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


def build_rewrite_directives(
    drift_report: Mapping[str, Any],
    *,
    limit: int = MAX_REWRITE_DIRECTIVES,
) -> list[StyleRewriteDirective]:
    """Translate comparable warn/red dimensions into deterministic advice.

    ``top_dimensions`` is the complete auditable input. Corrupt,
    unsupported, non-finite, or directionally non-actionable dimensions are
    skipped instead of being coerced to a misleading zero-value directive.
    """

    if str(drift_report.get("status") or "") != "ok":
        return []
    severity = str(drift_report.get("severity") or "")
    if severity not in {"warn", "red"}:
        return []
    top_dimensions = drift_report.get("top_dimensions")
    if not isinstance(top_dimensions, Sequence) or isinstance(top_dimensions, (str, bytes)):
        return []

    capped = max(0, min(_safe_int(limit, MAX_REWRITE_DIRECTIVES), MAX_REWRITE_DIRECTIVES))
    if capped == 0:
        return []

    comparable: list[tuple[float, str, Mapping[str, Any]]] = []
    for item in top_dimensions:
        if not isinstance(item, Mapping):
            continue
        dimension = str(item.get("dimension") or "")
        current = _finite_float(item.get("current_value"))
        baseline = _finite_float(item.get("baseline_value"))
        tolerance = _finite_float(item.get("tolerance"))
        weighted_delta = _finite_float(item.get("weighted_delta"))
        if (
            not dimension
            or current is None
            or baseline is None
            or tolerance is None
            or tolerance <= 0
            or weighted_delta is None
            or weighted_delta < 0
            or current < 0
            or baseline < 0
        ):
            continue
        comparable.append((weighted_delta, dimension, item))

    comparable.sort(key=lambda row: (-row[0], row[1]))
    directives: list[StyleRewriteDirective] = []
    for _weighted_delta, dimension, item in comparable:
        directive = _directive_for_dimension(dimension, severity, item)
        if directive is not None:
            directives.append(directive)
            if len(directives) >= capped:
                break
    return directives


def rewrite_directives_for_text(
    text: str,
    *,
    baseline_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    limit: int = MAX_REWRITE_DIRECTIVES,
) -> list[StyleRewriteDirective]:
    """Run the local fingerprint/drift path and return reviewer directives."""

    fingerprint = fingerprint_text(text, config=config)
    # Advisor needs the complete comparable set before unsupported dimensions
    # are filtered.  Persisted chapter drift keeps compare_to_baseline's top-5
    # default, while this transient path can still find an actionable sixth
    # (or later) dimension.
    drift = compare_to_baseline(
        fingerprint.get("metrics", {}),
        load_baseline(baseline_path),
        top_n=len(style_fingerprint.DRIFT_METRIC_KEYS),
    )
    return build_rewrite_directives(drift, limit=limit)


def analyze_text(
    text: str,
    *,
    chapter: int | None = None,
    baseline: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    top_n: int = TOP_DIMENSIONS_LIMIT,
) -> Dict[str, Any]:
    """Return one fingerprint/drift snapshot without reading the baseline twice.

    The writer passes the same in-memory baseline to the before/after calls so a
    concurrent baseline rebuild cannot make the rewrite comparison meaningless.
    """

    cfg = config or style_fingerprint.load_style_fingerprint_config()
    baseline_data = dict(load_baseline() if baseline is None else baseline)
    fingerprint = fingerprint_text(text, chapter=chapter, config=cfg)
    drift = compare_to_baseline(
        fingerprint.get("metrics", {}),
        baseline_data,
        top_n=top_n,
    )
    return {
        "style_fingerprint": fingerprint,
        "style_drift": drift,
        "baseline_hash": _basis_hash(drift),
    }


def parse_rewrite_policy(
    config: Mapping[str, Any] | None,
) -> tuple[Dict[str, Any], list[str]]:
    """Validate the optional red-only rewrite policy and fail closed.

    Iter087 deliberately accepts only zero or one extra rewrite.  A missing or
    malformed section disables the feature rather than guessing at a paid LLM
    action; preflight surfaces the returned warnings to the operator.
    """

    disabled = {
        "enabled": False,
        "trigger_severity": "red",
        "max_style_rewrites": 0,
        "min_improvement": DEFAULT_MIN_IMPROVEMENT,
    }
    raw = config.get("style_drift_rewrite") if isinstance(config, Mapping) else None
    if not isinstance(raw, Mapping):
        return disabled, ["style_fingerprint.yaml missing valid style_drift_rewrite mapping"]

    warnings: list[str] = []
    enabled = raw.get("enabled")
    trigger = raw.get("trigger_severity")
    max_rewrites = raw.get("max_style_rewrites")
    raw_min_improvement = raw.get("min_improvement")
    min_improvement = (
        _finite_float(raw_min_improvement)
        if isinstance(raw_min_improvement, (int, float)) and not isinstance(raw_min_improvement, bool)
        else None
    )

    if not isinstance(enabled, bool):
        warnings.append("style_drift_rewrite.enabled must be a boolean")
    if trigger != "red":
        warnings.append("style_drift_rewrite.trigger_severity must be 'red' in iter087")
    if isinstance(max_rewrites, bool) or not isinstance(max_rewrites, int) or max_rewrites not in {0, 1}:
        warnings.append("style_drift_rewrite.max_style_rewrites must be 0 or 1")
    if min_improvement is None or not 0.0 <= min_improvement <= 1.0:
        warnings.append("style_drift_rewrite.min_improvement must be a finite number between 0 and 1")
    if warnings:
        return disabled, warnings

    return {
        "enabled": enabled,
        "trigger_severity": trigger,
        "max_style_rewrites": max_rewrites,
        "min_improvement": min_improvement,
    }, []


def _directive_for_dimension(
    dimension: str,
    severity: str,
    item: Mapping[str, Any],
) -> StyleRewriteDirective | None:
    current = _finite_float(item.get("current_value"))
    baseline = _finite_float(item.get("baseline_value"))
    tolerance = _finite_float(item.get("tolerance"))
    if current is None or baseline is None or tolerance is None or tolerance <= 0:
        return None

    target_min_raw = max(0.0, baseline - tolerance)
    target_max_raw = max(target_min_raw, baseline + tolerance)
    if not math.isfinite(target_min_raw) or not math.isfinite(target_max_raw):
        return None
    target_min = _round(target_min_raw)
    target_max = _round(target_max_raw)
    above_target = current > target_max_raw and not math.isclose(
        current, target_max_raw, rel_tol=1e-12, abs_tol=1e-12
    )
    below_target = current < target_min_raw and not math.isclose(
        current, target_min_raw, rel_tol=1e-12, abs_tol=1e-12
    )

    section_hint = ""
    guidance = ""
    if dimension == "avg_sentence_length":
        section_hint = "全文句式节奏"
        if above_target:
            guidance = "拆分承载多个因果或说明层次的长句，删减解释性从句，用动作和停顿分开信息；只调整叙述节奏，不改变剧情事实。"
        elif below_target:
            guidance = "将连续碎句合并成完整的动作—感受—反应链，用必要从句恢复叙事流动；不新增或改动剧情事实。"
    elif dimension == "short_sentence_ratio" and above_target:
        section_hint = "短句密集段落"
        guidance = "合并连续的短句和同一主体的零碎动作，保留关键断句作节奏重音，其余恢复连贯叙述；不改剧情事实。"
    elif dimension in {"dialogue_line_ratio", "quote_span_ratio"}:
        section_hint = "信息密集段落"
        if below_target:
            guidance = "将部分解释性转述改由角色动作和必要对话承载，让信息在互动中显露；不添加新设定或改变剧情。"
        elif above_target:
            guidance = "在密集对白之间补入动作、环境反应和心理停顿，把可合并的问答收紧，避免对白堆叠；不改变事件结果。"
    elif dimension == "exposition_connector_density" and above_target:
        section_hint = "解释性总结句"
        guidance = "删去“因此/于是/这意味着”类总结性连接词，用角色的动作、感官细节或物件变化让因果自行显现；不改变原有逻辑。"
    elif dimension == "contrast_sentence_density" and above_target:
        section_hint = "对比句密集段落"
        guidance = "将重复的“不是…而是…”式对比改为动作选择、环境反应或前后细节落差，仅保留必要的一处对比重音。"
    elif dimension == "ai_cliche_density" and above_target:
        section_hint = "抽象概括与套话"
        guidance = "把抽象的 AI 腔概括换成具体动作、感官反应或可见物件，删去不推动画面的总结句；不新增剧情信息。"

    if not guidance:
        return None
    return StyleRewriteDirective(
        dimension=dimension,
        severity=severity,
        section_hint=section_hint,
        target_metric=dimension,
        current_value=_round(current),
        target_range={"min": target_min, "max": target_max},
        guidance=guidance,
    )


def annotate_meta(
    meta: Mapping[str, Any],
    draft_text: str,
    *,
    chapter: int,
    baseline_path: Path | None = None,
    config: Mapping[str, Any] | None = None,
    analysis: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    updated = dict(meta)
    try:
        if analysis is not None:
            fingerprint = analysis.get("style_fingerprint")
            drift = analysis.get("style_drift")
            if not isinstance(fingerprint, Mapping) or not isinstance(drift, Mapping):
                raise ValueError("invalid precomputed style analysis")
            fingerprint = dict(fingerprint)
            drift = dict(drift)
        else:
            snapshot = analyze_text(
                draft_text,
                chapter=chapter,
                baseline=load_baseline(baseline_path),
                config=config,
            )
            fingerprint = snapshot["style_fingerprint"]
            drift = snapshot["style_drift"]
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
            drift_status = str(drift.get("status") or "skipped")
            score = _finite_float(drift.get("style_drift_score"))
            reason = str(drift.get("reason") or "")
            severity = str(drift.get("severity") or "skipped")
            if drift_status == "ok" and score is None:
                drift_status = "skipped"
                severity = "skipped"
                reason = "invalid_style_drift_score"
            rows.append(
                {
                    "chapter": chapter_no,
                    "status": drift_status,
                    "severity": severity,
                    "style_drift_score": score,
                    "baseline_hash": _basis_hash(drift),
                    "top_dimensions": _sanitize_dimension_list(drift.get("top_dimensions")),
                    "reason": reason,
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
    status = str(baseline.get("status") or "")
    quality = baseline.get("baseline_quality") if isinstance(baseline.get("baseline_quality"), Mapping) else {}
    raw_schema_version = baseline.get("schema_version")
    schema_version = None if raw_schema_version is None else _safe_int(raw_schema_version, 0)
    return {
        "status": status,
        "schema_version": schema_version,
        "fingerprint_version": str(baseline.get("fingerprint_version") or ""),
        "language": str(baseline.get("language") or ""),
        # Invalid/incompatible artifacts must never propagate an untrusted hash
        # into chapter meta or the Web panel. Only a usable baseline may carry
        # its verified identity beyond this boundary.
        "baseline_hash": str(baseline.get("baseline_hash") or baseline.get("hash") or "") if status == "ok" else "",
        "sample_count": _safe_int(baseline.get("sample_count") or quality.get("sample_count"), 0),
        "baseline_quality_status": str(quality.get("status") or ""),
        "baseline_quality_confidence": _finite_float(quality.get("confidence")),
    }


def _basis_hash(drift: Mapping[str, Any]) -> str:
    basis = drift.get("basis")
    if not isinstance(basis, Mapping):
        return ""
    return str(basis.get("baseline_hash") or "")


def _sanitize_dimension_list(value: Any) -> list[Dict[str, Any]]:
    """Return a strict-JSON-safe list of dimension objects.

    Historical meta is user-editable and may contain ``[null]``, scalars, or
    Python's permissive NaN/Infinity values.  Reports are emitted with
    ``allow_nan=False``, so sanitize at the trust boundary instead of letting a
    single corrupt chapter crash the whole CLI.
    """

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    cleaned: list[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        dimension = item.get("dimension")
        if not isinstance(dimension, str) or not dimension.strip():
            continue
        safe = _json_safe(dict(item))
        if isinstance(safe, dict):
            cleaned.append(safe)
    return cleaned


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    return str(value)


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
