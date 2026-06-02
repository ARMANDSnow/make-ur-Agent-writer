from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import paths, start_point
from .chapter_summary import prune_from_chapter
from .chapter_status import chapter_status
from .cost_estimator import estimate_cost_since
from .entity_advance import apply_advance_proposals, proposal_path, select_auto_indexes
from .preflight import run_preflight
from .proposal_validator import validate_proposals_against_plan
from .reviewer import review_target
from .utils import ensure_dir, read_json, write_json
from .writer import _chapter_plan_item, _load_chapter_plan, _run_context, write_chapters


class BookRunBlocked(RuntimeError):
    pass


def run_write_book(
    *,
    chapters: int,
    resume_from: int = 1,
    force: bool = False,
    max_retries: int = 2,
    budget_cny: float = 0.0,
    replan_every: int = 0,
    min_confidence: float = 0.7,
    auto_advance: bool = True,
    require_start_point: bool = True,
    require_plan: bool = True,
    require_external_review: bool = True,
    progress_cb: Callable[[str, float], None] | None = None,
) -> Dict[str, Any]:
    """Production write entrypoint shared by CLI/Web wrappers.

    The runner is deliberately fail-closed: an old approved chapter without
    run-context metadata is treated as stale in strict mode, archived, and
    rewritten instead of skipped.
    """

    progress = progress_cb or (lambda _step, _fraction: None)
    progress("preflight", 0.05)
    total = max(1, int(chapters))
    chapter_numbers = list(range(int(resume_from), int(resume_from) + total))
    readiness = check_write_readiness(
        chapters=total,
        resume_from=resume_from,
        replan_every=replan_every,
        require_start_point=require_start_point,
        require_plan=require_plan,
        require_external_review=require_external_review,
        allow_existing_blockers=force,
    )
    if readiness.get("status") == "blocked":
        commands = "; ".join(readiness.get("recommended_commands") or [])
        suffix = f"; next: {commands}" if commands else ""
        raise BookRunBlocked("; ".join(readiness.get("blockers") or ["write-book is blocked"]) + suffix)
    plan = _load_chapter_plan()

    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    initial_log_lines = _llm_log_line_count()
    written: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    advances: List[Dict[str, Any]] = []
    costs: List[Dict[str, Any]] = []
    max_retries = max(0, int(max_retries))
    replan_every = max(0, int(replan_every))
    budget_cny = float(budget_cny or 0.0)
    for offset, chapter_no in enumerate(range(int(resume_from), int(resume_from) + total), start=1):
        progress(f"chapter-{chapter_no}", 0.1 + 0.8 * ((offset - 1) / total))
        if budget_cny > 0:
            current_cost = estimate_cost_since(initial_log_lines).get("cost_cny", 0.0)
            if float(current_cost) > budget_cny:
                progress("budget_exceeded", 1.0)
                return _snapshot(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "costs": costs,
                        "budget_cny": budget_cny,
                        "cost_cny": current_cost,
                    },
                )
        item = _chapter_plan_item(plan, chapter_no) if plan else None
        expected = _run_context(item, chapter_no=chapter_no)
        status = chapter_status(
            chapter_no,
            drafts_dir,
            validate_context=True,
            require_start_point=require_start_point,
            require_plan=require_plan,
            require_external_review=require_external_review,
            expected_context=expected,
        )
        if status.get("approved") and not force:
            written.append({"chapter": chapter_no, "action": "skipped_approved", "status": status})
            continue
        md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
        if md_path.exists() and not force:
            if (
                require_external_review
                and status.get("exists")
                and status.get("verdict") == "Approve"
                and status.get("strict_failures") == ["external_review_missing"]
            ):
                review_target(md_path, enforce_relationship_checklist=True)
                status = chapter_status(
                    chapter_no,
                    drafts_dir,
                    validate_context=True,
                    require_start_point=require_start_point,
                    require_plan=require_plan,
                    require_external_review=require_external_review,
                    expected_context=expected,
                )
                written.append({"chapter": chapter_no, "action": "reviewed_existing", "status": status})
                if status.get("approved"):
                    continue
                blocked.append({"chapter": chapter_no, "status": status})
                break
            else:
                raise BookRunBlocked(
                    f"chapter_{chapter_no:02d} has existing non-approved or stale outputs; "
                    "inspect them or rerun write-book with --force"
                )
        reports: List[Dict[str, Any]] = []
        status = {}
        attempt_summaries: List[Dict[str, Any]] = []
        for attempt in range(max_retries + 1):
            if attempt > 0 or (force and md_path.exists()):
                archive_dir = _archive_chapter_artifacts(
                    drafts_dir,
                    chapter_no,
                    reason=f"retry_attempt_{attempt}" if attempt > 0 else "force_rewrite",
                )
                prune_from_chapter(chapter_no)
                attempt_summaries.append({"attempt": attempt, "archived_to": str(archive_dir)})
            write_reports = write_chapters(chapters=1, resume_from=chapter_no, force=True)
            reports.extend(write_reports if isinstance(write_reports, list) else [write_reports])
            if require_external_review and md_path.exists():
                review_target(md_path, enforce_relationship_checklist=True)
            status = chapter_status(
                chapter_no,
                drafts_dir,
                validate_context=True,
                require_start_point=require_start_point,
                require_plan=require_plan,
                require_external_review=require_external_review,
                expected_context=expected,
            )
            attempt_summaries.append({"attempt": attempt, "status": status})
            if status.get("approved"):
                break
        written.append(
            {
                "chapter": chapter_no,
                "action": "written",
                "status": status,
                "reports": reports,
                "attempts": attempt_summaries,
            }
        )
        if not status.get("approved"):
            blocked.append({"chapter": chapter_no, "reason": "retry_exhausted", "status": status})
            break
        if auto_advance:
            advances.append(_auto_apply_advances(chapter_no, min_confidence=min_confidence))
        if budget_cny > 0:
            cost = estimate_cost_since(initial_log_lines)
            costs.append({"chapter": chapter_no, **cost})
            if float(cost.get("cost_cny", 0.0)) > budget_cny:
                progress("budget_exceeded", 1.0)
                return _snapshot(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "costs": costs,
                        "budget_cny": budget_cny,
                        "cost_cny": cost.get("cost_cny", 0.0),
                    },
                )
        if replan_every > 0 and offset < total and offset % replan_every == 0:
            progress(f"replan-after-{chapter_no}", 0.1 + 0.8 * (offset / total))
            from .plot_planner import generate_chapter_plan

            try:
                generate_chapter_plan(
                    append_count=replan_every,
                    from_chapter=chapter_no,
                    force=True,
                    require_start_point=require_start_point,
                )
                plan = _load_chapter_plan()
            except Exception as exc:
                blocked.append(
                    {
                        "chapter": chapter_no,
                        "reason": "replan_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                progress("blocked", 1.0)
                return _snapshot(
                    "blocked",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "costs": costs,
                    },
                )

    final_status = "blocked" if blocked else "succeeded"
    progress(final_status, 1.0)
    return _snapshot(final_status, {"chapters": written, "blocked": blocked, "advances": advances, "costs": costs})


def check_write_readiness(
    *,
    chapters: int,
    resume_from: int = 1,
    replan_every: int = 0,
    require_start_point: bool = True,
    require_plan: bool = True,
    require_external_review: bool = True,
    allow_existing_blockers: bool = False,
) -> Dict[str, Any]:
    """Return the user-facing production writing gate as JSON data."""

    total = max(1, int(chapters))
    resume_from = int(resume_from)
    replan_every = max(0, int(replan_every))
    plan_window = min(total, replan_every) if replan_every > 0 else total
    chapter_numbers = list(range(resume_from, resume_from + plan_window))
    blockers: List[str] = []
    warnings: List[str] = []
    recommended: List[str] = []
    cmd_prefix = _main_cmd_prefix()

    if require_start_point and not start_point.get_start_chapter_id():
        blockers.append("start_point_missing")
        recommended.append(f"{cmd_prefix} set-start-point <chapter_id>")

    raw_plan = _load_raw_chapter_plan()
    plan = _load_chapter_plan()
    if require_plan and not plan:
        blockers.append("chapter_plan_missing")
        recommended.append(
            f"{cmd_prefix} plan-chapters --chapters {max(plan_window, 5)} --force --require-start-point"
        )
    elif require_plan:
        failures = _plan_metadata_failures(
            raw_plan,
            chapter_numbers=chapter_numbers,
            require_start_point=require_start_point,
        )
        blockers.extend(f"chapter_plan:{failure}" for failure in failures)
        if failures:
            recommended.append(
                f"{cmd_prefix} plan-chapters --chapters {max(plan_window, len(raw_plan.get('chapters', []) or []), 5)} --force --require-start-point"
            )

    preflight = run_preflight()
    for fatal in preflight.get("fatal", []) or []:
        blockers.append(f"preflight:{fatal}")
    for warn in preflight.get("warn", []) or []:
        warnings.append(f"preflight:{warn}")

    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    if plan:
        for chapter_no in chapter_numbers:
            try:
                item = _chapter_plan_item(plan, chapter_no)
            except ValueError as exc:
                blockers.append(f"chapter_{chapter_no:02d}:plan_item_missing:{exc}")
                continue
            expected = _run_context(item, chapter_no=chapter_no)
            status = chapter_status(
                chapter_no,
                drafts_dir,
                validate_context=True,
                require_start_point=require_start_point,
                require_plan=require_plan,
                require_external_review=require_external_review,
                expected_context=expected,
            )
            if status.get("exists") and not status.get("approved") and not allow_existing_blockers:
                failures = status.get("strict_failures") or []
                if failures == ["external_review_missing"]:
                    warnings.append(f"chapter_{chapter_no:02d}:external_review_missing")
                else:
                    blockers.append(
                        f"chapter_{chapter_no:02d}:existing_output_not_strict_approved:"
                        f"verdict={status.get('verdict')};needs_review={status.get('needs_review')};"
                        f"strict_failures={','.join(failures)}"
                    )
                    recommended.append(
                        f"inspect {drafts_dir / f'chapter_{chapter_no:02d}.md'} and rerun write-book with --force if safe"
                    )

    kb_path = (paths.workspace_root() if paths.workspace_name() else Path(".")) / "data" / "knowledge_base" / "global_knowledge.md"
    if start_point.get_start_chapter_id() and kb_path.exists():
        warnings.append("knowledge_base is still global; start-point-filtered KB is not implemented in iter029")

    status = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "status": status,
        "chapters": total,
        "resume_from": resume_from,
        "plan_window": plan_window,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "recommended_commands": _dedupe(recommended),
    }


def _load_raw_chapter_plan() -> Dict[str, Any]:
    path = paths.chapter_plan_path() if paths.workspace_name() else Path("outputs/debate/chapter_plan.json")
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def _plan_metadata_failures(
    data: Dict[str, Any],
    *,
    chapter_numbers: List[int],
    require_start_point: bool,
) -> List[str]:
    failures: List[str] = []
    if not data:
        return ["plan_missing"]
    if not data.get("plan_fingerprint"):
        failures.append("plan_fingerprint_missing")
    else:
        from .plot_planner import plan_fingerprint

        if str(data.get("plan_fingerprint")) != plan_fingerprint(data):
            failures.append("plan_fingerprint_mismatch")
    if require_start_point:
        current_start = start_point.get_start_chapter_id() or ""
        current_fp = start_point.start_point_fingerprint()
        if not data.get("start_chapter_id"):
            failures.append("start_chapter_id_missing")
        elif current_start and str(data.get("start_chapter_id")) != current_start:
            failures.append("start_chapter_id_mismatch")
        if not data.get("start_point_fingerprint"):
            failures.append("start_point_fingerprint_missing")
        elif current_fp and str(data.get("start_point_fingerprint")) != current_fp:
            failures.append("start_point_fingerprint_mismatch")

    by_no = {
        int(item.get("chapter_no")): item
        for item in data.get("chapters", []) or []
        if isinstance(item, dict) and item.get("chapter_no") is not None
    }
    for chapter_no in chapter_numbers:
        item = by_no.get(int(chapter_no))
        if not item:
            failures.append(f"chapter_{chapter_no:02d}_plan_missing")
            continue
        if not item.get("chapter_plan_item_fingerprint"):
            failures.append(f"chapter_{chapter_no:02d}_plan_item_fingerprint_missing")
            continue
        from .plot_planner import chapter_plan_item_fingerprint

        if str(item.get("chapter_plan_item_fingerprint")) != chapter_plan_item_fingerprint(item):
            failures.append(f"chapter_{chapter_no:02d}_plan_item_fingerprint_mismatch")
    return failures


def _archive_chapter_artifacts(drafts_dir: Path, chapter_no: int, *, reason: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_dir = ensure_dir(drafts_dir / "snapshots" / f"stale_chapter_{chapter_no:02d}_{stamp}")
    for suffix in (
        ".md",
        ".meta.json",
        ".failure.json",
        ".entity_advances.json",
        ".entity_advance_proposals.json",
    ):
        path = drafts_dir / f"chapter_{chapter_no:02d}{suffix}"
        if path.exists():
            shutil.move(str(path), str(archive_dir / path.name))
    reviews_dir = drafts_dir.parent / "reviews"
    review_path = reviews_dir / f"chapter_{chapter_no:02d}.review.json"
    if review_path.exists():
        shutil.move(str(review_path), str(archive_dir / review_path.name))
    write_json(archive_dir / "archive_reason.json", {"reason": reason, "chapter": chapter_no})
    return archive_dir


def _auto_apply_advances(chapter_no: int, *, min_confidence: float) -> Dict[str, Any]:
    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    data = read_json(proposal_path(chapter_no, drafts_dir), {})
    proposals = data.get("proposed_advances", data.get("proposals", [])) if isinstance(data, dict) else []
    if not isinstance(proposals, list):
        proposals = []
    selected = select_auto_indexes(proposals, min_confidence=min_confidence)
    plan = _load_raw_chapter_plan()
    graph = read_json(paths.entity_graph_path() if paths.workspace_name() else Path("data/entity_graph.json"), {})
    conflicts = validate_proposals_against_plan(proposals, chapter_no, plan, graph)
    conflict_indexes = {int(item.get("proposal_index")) for item in conflicts if item.get("proposal_index") is not None}
    safe_selected = [idx for idx in selected if idx not in conflict_indexes]
    if not safe_selected:
        return {
            "chapter_no": chapter_no,
            "selected": [],
            "applied_count": 0,
            "auto_apply": True,
            "min_confidence": min_confidence,
            "conflicts": conflicts,
            "no_op_reason": "conflicts_or_empty_selection" if conflicts else "empty_selection",
        }
    result = apply_advance_proposals(
        chapter_no=chapter_no,
        proposal_indexes=",".join(str(idx) for idx in safe_selected),
        confirm=True,
        auto_apply=False,
        allow_empty=True,
    )
    result["auto_apply"] = True
    result["min_confidence"] = min_confidence
    result["conflicts"] = conflicts
    return result


def _llm_log_line_count() -> int:
    path = paths.llm_calls_log_path() if paths.workspace_name() else Path("logs/llm_calls.jsonl")
    if not path.exists():
        return 0
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


def _main_cmd_prefix() -> str:
    name = paths.workspace_name()
    if name:
        return f"python3 main.py --book {name}"
    return "python3 main.py"


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _snapshot(status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    root = paths.workspace_root() if paths.workspace_name() else Path(".")
    snap_dir = ensure_dir(root / "outputs" / "drafts" / "snapshots")
    path = snap_dir / f"write_book_{status}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    result = {"status": status, **payload}
    write_json(path, result)
    result["snapshot_path"] = str(path)
    return result
