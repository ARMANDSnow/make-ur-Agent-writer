from __future__ import annotations

from collections import Counter, defaultdict
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from . import paths
from .config import ROOT
from .utils import ensure_dir, read_json


SHORT_CHAPTER_CHAR_THRESHOLD = 2000


def _resolve_root(root: Path | None) -> Path:
    if root is not None:
        return root
    return paths.workspace_root() if paths.workspace_name() else ROOT


def collect_status(root: Path | None = None) -> Dict[str, Any]:
    root = _resolve_root(root)
    data_dir = root / "data"
    outputs_dir = root / "outputs"
    manifest = read_json(data_dir / "chapter_manifest.json", [])
    review_reports = list((outputs_dir / "reviews").glob("*.review.json"))
    draft_meta = list((outputs_dir / "drafts").glob("*.meta.json"))
    failure_files = list((data_dir / "extraction_failures").glob("*.json"))
    draft_failures = list((outputs_dir / "drafts").glob("*.failure.json"))

    return {
        "normalize": {
            "normalized_texts": len(list((data_dir / "normalized_texts").glob("*.txt"))),
            "source_maps": len(list((data_dir / "source_map").glob("*.json"))),
            "manifest": str(data_dir / "normalized_manifest.json"),
            "done": (data_dir / "normalized_manifest.json").exists(),
        },
        "split": {
            "chapters": len(manifest),
            "manifest": str(data_dir / "chapter_manifest.json"),
            "done": bool(manifest),
        },
        "extract": {
            "extracted_jsons": len(list((data_dir / "extracted_jsons").glob("*.json"))),
            "failures": len(failure_files),
            "output": str(data_dir / "extracted_jsons"),
            "failure_dir": str(data_dir / "extraction_failures"),
        },
        "compress": {
            "global_knowledge": str(data_dir / "knowledge_base" / "global_knowledge.md"),
            "knowledge_index": str(data_dir / "knowledge_base" / "knowledge_index.json"),
            "done": (data_dir / "knowledge_base" / "global_knowledge.md").exists()
            and (data_dir / "knowledge_base" / "knowledge_index.json").exists(),
        },
        "debate": {
            "outline": str(outputs_dir / "debate" / "outline.md"),
            "decisions": str(outputs_dir / "debate" / "decisions.json"),
            "log": str(outputs_dir / "debate" / "debate_log.jsonl"),
            "done": (outputs_dir / "debate" / "outline.md").exists()
            and (outputs_dir / "debate" / "decisions.json").exists(),
        },
        "write": {
            "drafts": len(list((outputs_dir / "drafts").glob("chapter_*.md"))),
            "meta": len(draft_meta),
            "failures": len(draft_failures),
            "output": str(outputs_dir / "drafts"),
        },
        "review": {
            "review_reports": len(review_reports),
            "output": str(outputs_dir / "reviews"),
            "done": bool(review_reports),
        },
    }


def render_status(status: Dict[str, Any]) -> str:
    lines = ["# Pipeline Status", ""]
    lines.append(
        f"- normalize: {'done' if status['normalize']['done'] else 'missing'} "
        f"({status['normalize']['normalized_texts']} texts, {status['normalize']['source_maps']} source maps)"
    )
    lines.append(
        f"- split: {'done' if status['split']['done'] else 'missing'} "
        f"({status['split']['chapters']} chapters) -> {status['split']['manifest']}"
    )
    lines.append(
        f"- extract: {status['extract']['extracted_jsons']} JSON files, "
        f"{status['extract']['failures']} failures -> {status['extract']['output']}"
    )
    lines.append(
        f"- compress: {'done' if status['compress']['done'] else 'missing'} "
        f"-> {status['compress']['global_knowledge']}"
    )
    lines.append(
        f"- debate: {'done' if status['debate']['done'] else 'missing'} "
        f"-> {status['debate']['outline']}"
    )
    lines.append(
        f"- write: {status['write']['drafts']} drafts, {status['write']['meta']} meta, "
        f"{status['write']['failures']} failures -> {status['write']['output']}"
    )
    lines.append(
        f"- review: {status['review']['review_reports']} reports -> {status['review']['output']}"
    )
    return "\n".join(lines) + "\n"


def status_report(root: Path | None = None) -> str:
    root = _resolve_root(root)
    return render_status(collect_status(root))


def build_manifest_markdown(
    manifest: List[Dict[str, Any]], short_threshold: int = SHORT_CHAPTER_CHAR_THRESHOLD
) -> str:
    by_volume: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in manifest:
        by_volume[str(entry.get("volume_id", "unknown"))].append(entry)

    lines = ["# Chapter Manifest", ""]
    for volume_id in sorted(by_volume):
        entries = by_volume[volume_id]
        lines.append(f"## {volume_id} ({len(entries)} chapters)")
        lines.append("")
        lines.append("| chapter_id | title | lines | chars | flags |")
        lines.append("|---|---|---:|---:|---|")
        for entry in entries:
            char_count = int(entry.get("char_count", 0))
            flags = []
            if char_count < short_threshold:
                flags.append("short")
            lines.append(
                f"| {entry.get('chapter_id')} | {entry.get('title')} | "
                f"{entry.get('start_line')}-{entry.get('end_line')} | {char_count} | {', '.join(flags)} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_manifest_report(root: Path | None = None, output_path: Path | None = None) -> Path:
    root = _resolve_root(root)
    manifest_path = root / "data" / "chapter_manifest.json"
    manifest = read_json(manifest_path, [])
    if not manifest:
        raise FileNotFoundError(f"chapter manifest not found: {manifest_path}")
    output_path = output_path or (root / "data" / "chapter_manifest.md")
    ensure_dir(output_path.parent)
    output_path.write_text(build_manifest_markdown(manifest), encoding="utf-8")
    return output_path


def collect_review_summary(root: Path | None = None) -> Dict[str, Any]:
    root = _resolve_root(root)
    reviews_dir = root / "outputs" / "reviews"
    drafts_dir = root / "outputs" / "drafts"
    review_reports = [read_json(path, {}) for path in sorted(reviews_dir.glob("*.review.json"))]
    meta_reports = [read_json(path, {}) for path in sorted(drafts_dir.glob("*.meta.json"))]

    linter_rules: Counter[str] = Counter()
    rejects = 0
    approvals = 0
    for report in review_reports:
        verdict = report.get("verdict")
        if verdict == "Reject":
            rejects += 1
        if verdict == "Approve":
            approvals += 1
        for issue in report.get("lint_issues", []):
            rule = issue.get("rule")
            if rule:
                linter_rules[str(rule)] += 1

    needs_human_review = sum(1 for meta in meta_reports if meta.get("needs_human_review"))
    return {
        "review_reports": len(review_reports),
        "draft_meta": len(meta_reports),
        "approvals": approvals,
        "rejects": rejects,
        "needs_human_review": needs_human_review,
        "linter_rules": dict(linter_rules.most_common()),
    }


def render_review_summary(summary: Dict[str, Any]) -> str:
    lines = [
        "# Review Summary",
        "",
        f"- review_reports: {summary['review_reports']}",
        f"- draft_meta: {summary['draft_meta']}",
        f"- approvals: {summary['approvals']}",
        f"- rejects: {summary['rejects']}",
        f"- needs_human_review: {summary['needs_human_review']}",
        "",
        "## Linter Rules",
    ]
    if summary["linter_rules"]:
        for rule, count in summary["linter_rules"].items():
            lines.append(f"- {rule}: {count}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def generate_review_summary(root: Path | None = None, output_path: Path | None = None) -> Tuple[Dict[str, Any], Path]:
    root = _resolve_root(root)
    summary = collect_review_summary(root)
    output_path = output_path or (root / "outputs" / "reviews" / "review_summary.md")
    ensure_dir(output_path.parent)
    output_path.write_text(render_review_summary(summary), encoding="utf-8")
    return summary, output_path


def expected_report_snapshots(root: Path | None = None) -> Dict[Path, str]:
    root = _resolve_root(root)
    manifest_path = root / "data" / "chapter_manifest.json"
    manifest = read_json(manifest_path, [])
    if not manifest:
        raise FileNotFoundError(f"chapter manifest not found: {manifest_path}")
    review_summary = collect_review_summary(root)
    return {
        root / "data" / "chapter_manifest.md": build_manifest_markdown(manifest),
        root / "outputs" / "reviews" / "review_summary.md": render_review_summary(review_summary),
    }


def check_report_snapshots(root: Path | None = None, update: bool = False) -> Dict[str, Any]:
    root = _resolve_root(root)
    expected = expected_report_snapshots(root)
    mismatches: Dict[str, str] = {}
    for path, expected_text in expected.items():
        if update:
            ensure_dir(path.parent)
            path.write_text(expected_text, encoding="utf-8")
            continue
        actual_text = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual_text != expected_text:
            label = str(path.relative_to(root))
            diff = unified_diff(
                actual_text.splitlines(keepends=True),
                expected_text.splitlines(keepends=True),
                fromfile=f"{label} (current)",
                tofile=f"{label} (expected)",
            )
            mismatches[label] = "".join(diff)
    return {
        "checked": [str(path.relative_to(root)) for path in expected],
        "updated": update,
        "ok": not mismatches,
        "mismatches": mismatches,
    }


def check_manifest_integrity(
    root: Path | None = None, short_threshold: int = SHORT_CHAPTER_CHAR_THRESHOLD, strict: bool = False
) -> Dict[str, Any]:
    root = _resolve_root(root)
    manifest_path = root / "data" / "chapter_manifest.json"
    manifest = read_json(manifest_path, [])
    if not manifest:
        raise FileNotFoundError(f"chapter manifest not found: {manifest_path}")

    errors: List[str] = []
    warnings: List[str] = []
    low_confidence: List[Dict[str, Any]] = []
    chapter_ids: Counter[str] = Counter()
    by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_volume: Counter[str] = Counter()
    required_fields = ("chapter_id", "volume_id", "normalized_file", "title", "start_line", "end_line", "char_count")

    for index, entry in enumerate(manifest, 1):
        label = str(entry.get("chapter_id") or f"entry#{index}")
        missing = [field for field in required_fields if field not in entry]
        if missing:
            errors.append(f"{label}: missing fields: {', '.join(missing)}")
            continue

        chapter_ids[str(entry["chapter_id"])] += 1
        volume_id = str(entry["volume_id"])
        by_volume[volume_id] += 1
        by_file[str(entry["normalized_file"])].append(entry)

        start_line = int(entry.get("start_line", 0))
        end_line = int(entry.get("end_line", 0))
        char_count = int(entry.get("char_count", 0))
        normalized_file = Path(str(entry["normalized_file"]))
        if not normalized_file.exists():
            errors.append(f"{label}: normalized file does not exist: {normalized_file}")
        if start_line <= 0 or end_line < start_line:
            errors.append(f"{label}: invalid line range {start_line}-{end_line}")
        if char_count <= 0:
            errors.append(f"{label}: non-positive char_count {char_count}")
        elif char_count < short_threshold:
            warnings.append(f"{label}: short chapter ({char_count} chars)")

        if "confidence" in entry:
            try:
                conf = float(entry["confidence"])
            except (TypeError, ValueError):
                errors.append(f"{label}: confidence is not a number ({entry['confidence']!r})")
            else:
                if conf < 0.0 or conf > 1.0:
                    errors.append(f"{label}: confidence={conf} out of range [0,1]")
                elif conf < 0.6:
                    low_confidence.append({"chapter_id": label, "confidence": conf})

    for chapter_id, count in chapter_ids.items():
        if count > 1:
            errors.append(f"{chapter_id}: duplicate chapter_id appears {count} times")

    for normalized_file, entries in by_file.items():
        ordered = sorted(entries, key=lambda item: int(item.get("start_line", 0)))
        previous = None
        for entry in ordered:
            if previous and int(entry["start_line"]) <= int(previous["end_line"]):
                errors.append(
                    f"{entry['chapter_id']}: overlaps {previous['chapter_id']} in {normalized_file} "
                    f"at line {entry['start_line']}"
                )
            previous = entry

    return {
        "chapters": len(manifest),
        "volumes": dict(sorted(by_volume.items())),
        "errors": errors,
        "warnings": warnings,
        "low_confidence_chapters": low_confidence,
        "strict": strict,
        "ok": not errors and (not strict or not warnings),
    }


def render_manifest_check(result: Dict[str, Any]) -> str:
    low_conf = result.get("low_confidence_chapters", [])
    lines = [
        "# Manifest Check",
        "",
        f"- chapters: {result['chapters']}",
        f"- strict: {result['strict']}",
        f"- errors: {len(result['errors'])}",
        f"- warnings: {len(result['warnings'])}",
        f"- low_confidence_chapters: {len(low_conf)}",
        "",
        "## Volumes",
    ]
    for volume_id, count in result["volumes"].items():
        lines.append(f"- {volume_id}: {count}")

    lines.append("")
    lines.append("## Errors")
    lines.extend(f"- {item}" for item in result["errors"]) if result["errors"] else lines.append("- none")
    lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {item}" for item in result["warnings"]) if result["warnings"] else lines.append("- none")
    lines.append("")
    lines.append("## Low Confidence (top 5)")
    if low_conf:
        for item in low_conf[:5]:
            lines.append(f"- {item['chapter_id']}: confidence={item['confidence']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
