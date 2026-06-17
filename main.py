from __future__ import annotations

import argparse
from pathlib import Path

import os
import sys

from src.auto_bootstrap import (
    bootstrap_all,
    bootstrap_continuation_anchor,
    bootstrap_entity_graph,
    bootstrap_global_facts,
    bootstrap_personas,
    bootstrap_style_examples,
    proposal_summary,
)
from src.chapter_splitter import split_all
from src.cli_apply_bootstrap import apply_bootstrap, render_apply_bootstrap_result
from src.cli_apply_advance import apply_advance_cli, render_apply_advance_result
from src.cli_workspace import (
    import_current,
    init_workspace,
    list_workspaces,
    render_import,
    render_init,
    render_list,
    render_show,
    show_workspace,
)
from src.compressor import compress_all
from src.cost_estimator import estimate_cost, render_cost_estimate
from src.debater import run_debate
from src.extractor import extract_all, retry_failures
from src.observability import (
    check_manifest_integrity,
    check_report_snapshots,
    generate_manifest_report,
    generate_review_summary,
    render_manifest_check,
    status_report,
)
from src.epub_to_txt import extract_epub, render_extract_result
from src.preflight import render_preflight, run_preflight
from src.reviewer import review_target
from src.text_normalizer import normalize_all
from src.writer import write_chapters


def _consume_book_pre_arg() -> None:
    """Iter 017: pre-parse a global ``--book <name>`` flag.

    argparse subparsers are not great at accepting a parent-level flag both
    before and inside subcommand position. We strip ``--book`` from sys.argv
    here and set ``WORKSPACE_NAME`` so every ``src.paths.*`` call downstream
    sees the active workspace. ``--book`` may appear anywhere in argv.
    """
    argv = sys.argv[1:]
    book: str | None = None
    keep: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--book":
            if i + 1 >= len(argv):
                raise SystemExit("--book requires a value")
            book = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--book="):
            book = arg.split("=", 1)[1]
            i += 1
            continue
        keep.append(arg)
        i += 1
    if book is not None:
        os.environ["WORKSPACE_NAME"] = book
    sys.argv = [sys.argv[0], *keep]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dragon Raja AI Continuer MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    normalize_cmd = sub.add_parser("normalize")
    normalize_cmd.add_argument(
        "--lang",
        default=None,
        help="Force script language (zh/en). Default: auto-detect per file.",
    )
    split_cmd = sub.add_parser("split")
    split_cmd.add_argument(
        "--lang",
        default=None,
        help="Force script language (zh/en). Default: auto-detect per file.",
    )

    epub_import_cmd = sub.add_parser("epub-import")
    epub_import_cmd.add_argument("--src", required=True, help="Path to source .epub file.")
    epub_import_cmd.add_argument("--out", required=True, help="Output txt filename (written under <workspace>/小说txt/).")
    epub_import_cmd.add_argument(
        "--book-filter",
        default=None,
        help="Optional regex; only spine entries whose path matches are extracted (e.g. 'part00(09|1[0-9])' to pick Book 1 out of a bundle).",
    )
    sub.add_parser("status")
    sub.add_parser("manifest-report")
    sub.add_parser("review-summary")
    check_reports = sub.add_parser("check-reports")
    check_reports.add_argument("--update", action="store_true")
    check_manifest = sub.add_parser("check-manifest")
    check_manifest.add_argument("--strict", action="store_true")
    sub.add_parser("retry-failures")
    sub.add_parser("estimate-cost")
    sub.add_parser("preflight")

    extract = sub.add_parser("extract")
    extract.add_argument("--volume", default="all")
    extract.add_argument("--limit", type=int, default=None)
    extract.add_argument("--force", action="store_true")
    extract.add_argument(
        "--no-chunk", action="store_true",
        help="iter055: 每章强制单次抽取(绕过分块),诊断分块边界漏抽/合并失真",
    )
    extract.add_argument(
        "--per-chapter-attempts", type=int, default=None,
        help="iter055: 整章级重试次数(救分块合并失败,在 call 级超时重试之上);缺省不整章重试",
    )

    sub.add_parser("compress")
    debate_cmd = sub.add_parser("debate")
    debate_cmd.add_argument(
        "--topic",
        default=None,
        help="Override the debate topic; defaults to the legacy validation-corpus topic.",
    )
    debate_cmd.add_argument(
        "--force",
        action="store_true",
        help="iter 053a: archive the existing outline/decisions/log trio to "
        "outputs/debate/snapshots/<ts>/ and debate from scratch (a plain rerun "
        "would resume via done_keys and silently change nothing)",
    )

    bootstrap_facts = sub.add_parser("bootstrap-facts")
    bootstrap_facts.add_argument("--force", action="store_true")
    bootstrap_graph = sub.add_parser("bootstrap-graph")
    bootstrap_graph.add_argument("--force", action="store_true")
    bootstrap_anchor = sub.add_parser("bootstrap-anchor")
    bootstrap_anchor.add_argument("--force", action="store_true")
    bootstrap_style = sub.add_parser("bootstrap-style")
    bootstrap_style.add_argument("--force", action="store_true")
    bootstrap_personas_cmd = sub.add_parser("bootstrap-personas")
    bootstrap_personas_cmd.add_argument("--force", action="store_true")
    bootstrap_source_excerpts_cmd = sub.add_parser("bootstrap-source-excerpts")
    bootstrap_source_excerpts_cmd.add_argument("--force", action="store_true")

    apply_bootstrap_cmd = sub.add_parser("apply-bootstrap")
    apply_bootstrap_cmd.add_argument("--name", required=True)
    apply_bootstrap_cmd.add_argument("--confirm", action="store_true")

    # iter 054b: one-shot 底座 rebuild after set-start-point moves the start —
    # extract window → compress → bootstrap-graph/anchor --force → apply.
    # Fills the longzu 4-step manual firefight (AGENT_HANDOFF 缺口 A).
    rebuild_cmd = sub.add_parser("rebuild-for-start")
    rebuild_cmd.add_argument(
        "--window", type=int, default=10,
        help="K-chapter window before+incl start to ensure extracted (default 10, matches coverage 闸)",
    )
    rebuild_cmd.add_argument(
        "--reextract", action="store_true",
        help="re-extract window chapters even if already extracted (default: fill gaps only)",
    )
    rebuild_cmd.add_argument(
        "--no-apply", action="store_true",
        help="build entity_graph/anchor proposals but don't auto-apply (review then apply-bootstrap)",
    )
    rebuild_cmd.add_argument(
        "--no-chunk", action="store_true",
        help="iter055: 窗口章节强制单次抽取(绕过分块),配合 --reextract 诊断分块漏抽",
    )

    # iter 054d: ingest-to-start (主线机制) — normalize→split then physically
    # truncate normalized_texts + manifest to <= the start, so downstream has
    # no post-start content to leak (filters degrade to no-ops). Source txt
    # under 小说txt/ is untouched (full corpus recoverable by re-running).
    ingest_cmd = sub.add_parser("ingest-to-start")
    ingest_cmd.add_argument(
        "start",
        help="chapter_id or volume_id to bound ingestion at; corpus is physically truncated to <= this",
    )

    init_book = sub.add_parser("init-book")
    init_book.add_argument("--skip-extract", action="store_true")
    init_book.add_argument("--extract-limit", type=int, default=10)
    init_book.add_argument("--force", action="store_true")

    plan_chapters = sub.add_parser("plan-chapters")
    plan_chapters.add_argument("--chapters", type=int, default=18)
    plan_chapters.add_argument("--force", action="store_true", help="overwrite existing chapter_plan.json")
    # Iter 024 P2: append mode — preserve ch1..from_chapter, append append_count new
    plan_chapters.add_argument("--append", type=int, default=0, dest="append_count",
                               help="iter 024: append K new chapters instead of overwriting")
    plan_chapters.add_argument("--from-chapter", type=int, default=0, dest="from_chapter",
                               help="iter 024: index after which to append (0 = current plan length)")
    plan_chapters.add_argument(
        "--require-start-point",
        action="store_true",
        help="iter 027: fail if start_chapter.json is missing before planning",
    )
    plan_chapters.add_argument(
        "--allow-stale-outline",
        action="store_true",
        help="iter 053a: escape hatch — plan from an outline whose recorded "
        "start point mismatches the current one (audit trail is written into "
        "chapter_plan.json). Default is to refuse (the 052 accident).",
    )

    write = sub.add_parser("write")
    write.add_argument("--chapters", type=int, default=18)
    write.add_argument("--resume-from", type=int, default=1)
    write.add_argument("--force", action="store_true")

    write_book = sub.add_parser("write-book")
    write_book.add_argument("--chapters", type=int, default=1)
    write_book.add_argument("--resume-from", type=int, default=1)
    write_book.add_argument("--force", action="store_true")
    write_book.add_argument("--max-retries", type=int, default=2)
    write_book.add_argument("--budget-cny", type=float, default=0.0)
    write_book.add_argument("--replan-every", type=int, default=0)
    write_book.add_argument("--min-confidence", type=float, default=0.7)
    write_book.add_argument("--tier", choices=["high", "mid", "low"], default=None)
    write_book.add_argument("--no-auto-advance", action="store_true")
    write_book.add_argument("--allow-missing-start-point", action="store_true")
    write_book.add_argument("--allow-missing-plan", action="store_true")
    write_book.add_argument("--skip-external-review", action="store_true")

    write_readiness = sub.add_parser("write-readiness")
    write_readiness.add_argument("--chapters", type=int, required=True)
    write_readiness.add_argument("--resume-from", type=int, default=1)
    write_readiness.add_argument("--replan-every", type=int, default=0)
    write_readiness.add_argument("--allow-missing-start-point", action="store_true")
    write_readiness.add_argument("--allow-missing-plan", action="store_true")
    write_readiness.add_argument("--skip-external-review", action="store_true")

    review = sub.add_parser("review")
    review.add_argument("--target", default="outputs/drafts")
    review_chapter = sub.add_parser("review-chapter")
    review_chapter.add_argument("chapter", type=int)

    apply_advance = sub.add_parser("apply-advance")
    apply_advance.add_argument("--chapter", type=int, required=True)
    # iter 019: --proposal-idx becomes optional when --auto-apply is set.
    # We do the mutual-exclusivity check at dispatch time so backward-compat
    # callers (proposal-idx as required) still emit the same error class.
    apply_advance.add_argument("--proposal-idx", default=None)
    apply_advance.add_argument("--confirm", action="store_true")
    apply_advance.add_argument(
        "--auto-apply",
        action="store_true",
        help="Iter 019: select proposals whose confidence >= --min-confidence.",
    )
    apply_advance.add_argument(
        "--min-confidence",
        type=float,
        default=0.7,
        help="Iter 019: confidence threshold for --auto-apply (default 0.7).",
    )
    apply_advance.add_argument(
        "--allow-empty",
        action="store_true",
        help="Iter 019: exit 0 instead of erroring when no proposals are selected.",
    )

    # iter 019: chapter-status returns the failure / approval markers for a
    # chapter as JSON, so write_book.sh can branch on it without grepping.
    chapter_status_cmd = sub.add_parser("chapter-status")
    chapter_status_cmd.add_argument("chapter", type=int)
    chapter_status_cmd.add_argument("--json", action="store_true", default=True)
    chapter_status_cmd.add_argument("--validate-context", action="store_true")
    chapter_status_cmd.add_argument("--require-start-point", action="store_true")
    chapter_status_cmd.add_argument("--require-plan", action="store_true")
    chapter_status_cmd.add_argument("--require-external-review", action="store_true")

    # iter 021: start point — let users pick a chapter_id or volume_id from
    # chapter_manifest as the "continue from here" anchor instead of the
    # default first-extracted-chapter sampling. See src/start_point.py.
    set_start_cmd = sub.add_parser("set-start-point")
    set_start_cmd.add_argument(
        "name",
        help="chapter_id (e.g. longzu_3_3_ch020) or volume_id (e.g. longzu_4)",
    )
    sub.add_parser("show-start-point")
    sub.add_parser("clear-start-point")

    # iter 017: multi-book workspace management
    sub.add_parser("workspace-list")
    workspace_init_cmd = sub.add_parser("workspace-init")
    workspace_init_cmd.add_argument("name")
    workspace_import_cmd = sub.add_parser("workspace-import-current")
    workspace_import_cmd.add_argument("--to", required=True, dest="to_name")
    workspace_import_cmd.add_argument("--dry-run", action="store_true")
    workspace_show_cmd = sub.add_parser("workspace-show")
    workspace_show_cmd.add_argument("--name", default=None)

    run_all = sub.add_parser("run-all")
    run_all.add_argument("--chapters", type=int, default=18)
    run_all.add_argument("--extract-limit", type=int, default=None)
    run_all.add_argument("--force", action="store_true")

    # iter 025: read-only WebUI dashboard. Defaults to localhost binding;
    # use --host 0.0.0.0 only for LAN access since the dashboard has no
    # auth.
    web_cmd = sub.add_parser("web")
    web_cmd.add_argument("--host", default="127.0.0.1")
    web_cmd.add_argument("--port", type=int, default=8765)

    # iter 026: end-to-end SOP one-liner. Upgrades ``run-all`` (which
    # skipped bootstrap-apply + plan-chapters) into a true 9-step
    # pipeline; the WebUI wizard's worker calls the same function so
    # GUI / CLI never drift on step ordering.
    auto_cmd = sub.add_parser("auto-pipeline")
    auto_cmd.add_argument("--chapters", type=int, default=1)
    auto_cmd.add_argument("--extract-limit", type=int, default=5)
    auto_cmd.add_argument("--skip-extract", action="store_true")
    auto_cmd.add_argument("--force", action="store_true")
    auto_cmd.add_argument(
        "--plan-chapters",
        type=int,
        default=None,
        help="Override chapter_plan size. None lets the planner default to max(chapters, 5).",
    )
    # Iter 027 bug-sweep F1: opt-in start-point gate for CLI auto-pipeline.
    # Power users resuming an existing book should pass --require-start-point
    # so the planner refuses to silently regenerate plans rooted at Book 1.
    auto_cmd.add_argument(
        "--require-start-point",
        action="store_true",
        help=(
            "Refuse to plan/write if no start_chapter.json is set. Recommended"
            " when resuming an existing book; not needed for greenfield first runs."
        ),
    )
    auto_cmd.add_argument(
        "--allow-missing-start-point",
        action="store_true",
        help="Explicitly opt out of the start-point gate (default behavior).",
    )

    # iter 052: long-run driver. Orchestrates write-book/plan-chapters/debate
    # as subprocesses with checkpoint-resume, so 30-100 chapter real-model
    # runs survive session recycling (smoke051 lesson). See src/book_driver.py.
    drive_cmd = sub.add_parser("drive-book")
    drive_cmd.add_argument("action", choices=["start", "status", "resume", "stop", "report"])
    drive_cmd.add_argument("--chapters", type=int, default=30)
    drive_cmd.add_argument("--resume-from", type=int, default=1)
    drive_cmd.add_argument("--segment-size", type=int, default=5)
    drive_cmd.add_argument("--replan-every", type=int, default=0)
    drive_cmd.add_argument(
        "--plan-target",
        type=int,
        default=0,
        help="initial chapter_plan length when missing (0 = min(10, last chapter))",
    )
    # None-defaults let resume distinguish "explicitly overridden" from "keep stored".
    drive_cmd.add_argument("--budget-cny", type=float, default=None, help="driver-level total budget; <=0 = no cap")
    drive_cmd.add_argument("--tier", choices=["high", "mid", "low"], default=None)
    drive_cmd.add_argument("--max-retries", type=int, default=2)
    drive_cmd.add_argument("--skip-debate", action="store_true")
    drive_cmd.add_argument(
        "--force-debate",
        action="store_true",
        help="iter 053a: archive the old debate trio + rerun debate from "
        "scratch, then archive the downstream chapter_plan.json so ensure-plan "
        "regenerates it from the fresh outline. Mutually exclusive with "
        "--skip-debate. One-shot: a later resume does NOT re-force unless "
        "passed again.",
    )
    drive_cmd.add_argument("--require-start-point", action="store_true")
    drive_cmd.add_argument("--allow-missing-start-point", action="store_true")
    drive_cmd.add_argument("--allow-missing-plan", action="store_true")
    drive_cmd.add_argument("--skip-external-review", action="store_true")
    drive_cmd.add_argument("--pause-after-segment", type=int, default=None)
    drive_cmd.add_argument("--step-timeout-minutes", type=int, default=None)
    drive_cmd.add_argument("--on-blocked", choices=["stop", "force-once"], default=None)
    drive_cmd.add_argument("--detach", action="store_true")
    drive_cmd.add_argument("--confirm-real-run", action="store_true")
    drive_cmd.add_argument("--json", action="store_true")
    drive_cmd.add_argument(
        "--cmd-prefix",
        default=None,
        help="test hook: replace 'python main.py [--book X]' subprocess prefix",
    )
    return parser


def main() -> None:
    _consume_book_pre_arg()
    args = build_parser().parse_args()
    if args.command == "workspace-list":
        print(render_list(list_workspaces()), end="")
        return
    if args.command == "workspace-init":
        result = init_workspace(args.name)
        print(render_init(result), end="")
        return
    if args.command == "workspace-import-current":
        result = import_current(args.to_name, dry_run=args.dry_run)
        print(render_import(result), end="")
        return
    if args.command == "workspace-show":
        summary = show_workspace(args.name)
        print(render_show(summary), end="")
        return
    if args.command == "normalize":
        normalize_all(lang=getattr(args, "lang", None))
    elif args.command == "split":
        split_all(lang=getattr(args, "lang", None))
    elif args.command == "epub-import":
        from src import paths
        out_path = paths.raw_txt_dir() / args.out if paths.workspace_name() else Path("小说txt") / args.out
        result = extract_epub(Path(args.src).expanduser(), out_path, book_filter=args.book_filter)
        print(render_extract_result(result), end="")
    elif args.command == "status":
        print(status_report(), end="")
    elif args.command == "manifest-report":
        path = generate_manifest_report()
        print(f"Manifest report written: {path}")
    elif args.command == "review-summary":
        summary, path = generate_review_summary()
        print(path.read_text(encoding="utf-8"), end="")
        print(f"\nReview summary written: {path}")
    elif args.command == "check-reports":
        result = check_report_snapshots(update=args.update)
        if args.update:
            print(f"Report snapshots updated: {', '.join(result['checked'])}")
        elif result["ok"]:
            print(f"Report snapshots OK: {', '.join(result['checked'])}")
        else:
            print("Report snapshots differ:")
            for diff in result["mismatches"].values():
                print(diff, end="" if diff.endswith("\n") else "\n")
            raise SystemExit(1)
    elif args.command == "check-manifest":
        result = check_manifest_integrity(strict=args.strict)
        print(render_manifest_check(result), end="")
        if not result["ok"]:
            raise SystemExit(1)
    elif args.command == "retry-failures":
        results = retry_failures()
        print(f"Retried failure chapters: {len(results)}")
    elif args.command == "estimate-cost":
        print(render_cost_estimate(estimate_cost()), end="")
    elif args.command == "preflight":
        report = run_preflight()
        print(render_preflight(report), end="")
        if report["status"] == "fail":
            raise SystemExit(1)
    elif args.command == "extract":
        extract_all(
            volume=args.volume, limit=args.limit, force=args.force,
            no_chunk=args.no_chunk, per_chapter_attempts=args.per_chapter_attempts,
        )
    elif args.command == "compress":
        compress_all()
    elif args.command == "debate":
        topic = getattr(args, "topic", None)
        force = bool(getattr(args, "force", False))
        if topic:
            run_debate(topic=topic, force=force)
        else:
            run_debate(force=force)
    elif args.command == "bootstrap-facts":
        result = bootstrap_global_facts(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "bootstrap-graph":
        result = bootstrap_entity_graph(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "bootstrap-anchor":
        result = bootstrap_continuation_anchor(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "bootstrap-style":
        result = bootstrap_style_examples(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "bootstrap-personas":
        result = bootstrap_personas(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "bootstrap-source-excerpts":
        from src.auto_bootstrap import bootstrap_source_excerpts
        result = bootstrap_source_excerpts(force=args.force)
        print(_render_bootstrap_result(result), end="")
    elif args.command == "apply-bootstrap":
        print(render_apply_bootstrap_result(apply_bootstrap(args.name, confirm=args.confirm)), end="")
    elif args.command == "rebuild-for-start":
        from src.auto_pipeline import rebuild_for_start
        from src.extractor import ExtractionBatchFailure

        def _rebuild_progress(step: str, fraction: float) -> None:
            print(f"[rebuild-for-start] {int(fraction * 100):3d}% {step}")

        try:
            result = rebuild_for_start(
                window=args.window,
                reextract=args.reextract,
                apply=not args.no_apply,
                no_chunk=args.no_chunk,
                progress_cb=_rebuild_progress,
            )
        except (ValueError, ExtractionBatchFailure) as exc:
            # iter054c: ExtractionBatchFailure aborts before compress/bootstrap so
            # we never build the base on a silently-degraded extraction set.
            print(f"ERROR: {exc}")
            raise SystemExit(1)
        print(
            f"[rebuild-for-start] done · start={result['start_chapter_id']!r} "
            f"window={result['window_chapter_ids']}"
        )
    elif args.command == "ingest-to-start":
        from src.auto_pipeline import ingest_to_start

        try:
            result = ingest_to_start(args.start)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            raise SystemExit(1)
        print(
            f"ingest-to-start done · start={result['start_chapter_id']!r} "
            f"kept={result['kept_chapters']} dropped={result['dropped_chapters']} "
            f"truncated={result['truncated_volumes']} deleted={result['deleted_volumes']}"
        )
    elif args.command == "init-book":
        results = init_book_pipeline(skip_extract=args.skip_extract, extract_limit=args.extract_limit, force=args.force)
        print(_render_init_book_results(results), end="")
    elif args.command == "plan-chapters":
        from src.plot_planner import generate_chapter_plan

        # Iter 024: if --append is set without explicit --from-chapter,
        # auto-resolve to current plan length so common usage doesn't
        # need to track the chapter count manually.
        from_chapter = args.from_chapter
        if args.append_count > 0 and from_chapter == 0:
            from src import paths as _paths
            from src.utils import read_json as _rj
            _p = _paths.chapter_plan_path() if _paths.workspace_name() else Path("outputs/debate/chapter_plan.json")
            from_chapter = len((_rj(_p, {}) or {}).get("chapters", []))
        data = generate_chapter_plan(
            target_chapters=args.chapters,
            force=args.force,
            append_count=args.append_count,
            from_chapter=from_chapter,
            require_start_point=args.require_start_point,
            allow_stale_outline=args.allow_stale_outline,
        )
        mode = f"append +{args.append_count} from ch{from_chapter}" if args.append_count > 0 else "fresh"
        print(f"chapter_plan.json written ({mode}): {len(data['chapters'])} chapters")
        print(f"overall_arc: {str(data['overall_arc'])[:200]}")
    elif args.command == "write":
        write_chapters(chapters=args.chapters, force=args.force, resume_from=args.resume_from)
    elif args.command == "write-book":
        from src.book_runner import BookRunBlocked, run_write_book
        import json as _json

        try:
            result = run_write_book(
                chapters=args.chapters,
                resume_from=args.resume_from,
                force=args.force,
                max_retries=args.max_retries,
                budget_cny=args.budget_cny,
                replan_every=args.replan_every,
                min_confidence=args.min_confidence,
                auto_advance=not args.no_auto_advance,
                require_start_point=not args.allow_missing_start_point,
                require_plan=not args.allow_missing_plan,
                require_external_review=not args.skip_external_review,
                tier=args.tier,
            )
        except BookRunBlocked as exc:
            print(_json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
            raise SystemExit(4)
        print(_json.dumps(result, ensure_ascii=False))
        if result.get("status") == "blocked":
            raise SystemExit(4)
        if result.get("status") == "budget_exceeded":
            raise SystemExit(3)
        if result.get("status") == "failed":
            raise SystemExit(1)
    elif args.command == "write-readiness":
        from src.book_runner import check_write_readiness
        import json as _json

        result = check_write_readiness(
            chapters=args.chapters,
            resume_from=args.resume_from,
            replan_every=args.replan_every,
            require_start_point=not args.allow_missing_start_point,
            require_plan=not args.allow_missing_plan,
            require_external_review=not args.skip_external_review,
        )
        print(_json.dumps(result, ensure_ascii=False))
        if result.get("status") == "blocked":
            raise SystemExit(4)
    elif args.command == "review":
        review_target(Path(args.target), enforce_relationship_checklist=True)
    elif args.command == "review-chapter":
        # iter 017: resolve drafts dir via paths.py so review-chapter honors
        # --book. Legacy mode keeps the same outputs/drafts/ path.
        from src import paths

        drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
        review_target(drafts_dir / f"chapter_{args.chapter:02d}.md", enforce_relationship_checklist=True)
    elif args.command == "apply-advance":
        # iter 019: validate flag combinations. --auto-apply and --proposal-idx
        # are mutually exclusive; one of them must be provided.
        if args.auto_apply and args.proposal_idx is not None:
            raise SystemExit("--auto-apply and --proposal-idx are mutually exclusive")
        if not args.auto_apply and args.proposal_idx is None:
            raise SystemExit("--proposal-idx is required unless --auto-apply is set")
        result = apply_advance_cli(
            args.chapter,
            args.proposal_idx or "",
            confirm=args.confirm,
            auto_apply=args.auto_apply,
            min_confidence=args.min_confidence,
            allow_empty=args.allow_empty,
        )
        print(render_apply_advance_result(result), end="")
    elif args.command == "chapter-status":
        # iter 019: thin wrapper around src.chapter_status. Always prints JSON
        # so write_book.sh can parse it deterministically.
        import json as _json

        from src.chapter_status import chapter_status
        from src import paths

        drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
        status = chapter_status(
            args.chapter,
            drafts_dir,
            validate_context=args.validate_context,
            require_start_point=args.require_start_point,
            require_plan=args.require_plan,
            require_external_review=args.require_external_review,
        )
        print(_json.dumps(status, ensure_ascii=False))
    elif args.command == "set-start-point":
        from src import start_point

        try:
            start_point.set_start_point(args.name)
            resolved = start_point.get_start_chapter_id()
            print(f"start point set: {args.name!r} → resolved chapter_id = {resolved!r}")
            # iter 054b: surface the extraction coverage闸 here, the earliest
            # point a stale base can be detected, instead of only at readiness
            # (053g, after debate/plan money is gone). Non-fatal report — the
            # hard blocker lives in plan-chapters; this just tells the user now.
            missing = start_point.extraction_coverage_failures(k=10)
            if missing:
                preview = ",".join(missing[:5])
                more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
                print(
                    f"WARNING: extraction coverage gap before start: {preview}{more}\n"
                    f"  run `python main.py extract --volume <起点所在卷>` "
                    "(or `rebuild-for-start`) before plan-chapters — it will hard-block otherwise"
                )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            raise SystemExit(1)
    elif args.command == "show-start-point":
        from src import start_point

        resolved = start_point.get_start_chapter_id()
        if resolved is None:
            print("no start point set (default behavior: iter 020 first-extracted-chapter sampling)")
        else:
            print(f"resolved chapter_id: {resolved}")
            before = start_point.chapters_before_start(3)
            if before:
                print(f"  chapters before start (3): {[c.get('chapter_id') for c in before]}")
    elif args.command == "clear-start-point":
        from src import start_point

        start_point.clear_start_point()
        print("start point cleared (now using iter 020 default behavior)")
    elif args.command == "run-all":
        normalize_all()
        split_all()
        extract_all(volume="all", limit=args.extract_limit, force=args.force)
        compress_all()
        run_debate()
        write_chapters(chapters=args.chapters, force=args.force)
    elif args.command == "web":
        from src.web.server import serve

        serve(host=args.host, port=args.port)
    elif args.command == "auto-pipeline":
        from src.auto_pipeline import run_auto_pipeline

        def _cli_progress(step: str, fraction: float) -> None:
            # 0..1 → 0..100 with a fixed-width label so successive
            # lines stack readably in a terminal.
            print(f"[auto-pipeline] {int(fraction * 100):3d}% {step}")

        results = run_auto_pipeline(
            target_chapters=args.chapters,
            progress_cb=_cli_progress,
            skip_extract=args.skip_extract,
            extract_limit=args.extract_limit,
            force=args.force,
            plan_chapters_target=args.plan_chapters,
            require_start_point=bool(args.require_start_point),
        )
        # Print a one-line summary of the write step so CI / verify.sh
        # can grep for it without parsing the per-step output.
        write_summary = results.get("write") or []
        print(f"[auto-pipeline] done · chapters_written={len(write_summary)}")
    elif args.command == "drive-book":
        from src.book_driver import main as drive_book_main

        raise SystemExit(drive_book_main(args))


def init_book_pipeline(skip_extract: bool = False, extract_limit: int | None = 10, force: bool = False):
    # iter 017: in workspace mode, resolve raw/normalized/manifest paths
    # through paths.py so init-book honors --book / WORKSPACE_NAME. In legacy
    # mode (no workspace), keep cwd-relative paths so iter 014-016 tests that
    # chdir into a tmp dir still work without modification.
    from src import paths

    if paths.workspace_name():
        raw_dir = paths.raw_txt_dir()
        normalized_dir = paths.normalized_dir()
        manifest_path = paths.chapter_manifest_path()
    else:
        raw_dir = Path("小说txt")
        normalized_dir = Path("data/normalized_texts")
        manifest_path = Path("data/chapter_manifest.json")
    if not raw_dir.exists() or not any(raw_dir.glob("*.txt")):
        raise FileNotFoundError(f"no txt files found in {raw_dir}")
    if not normalized_dir.exists() or not any(normalized_dir.glob("*.txt")):
        normalize_all()
    if not manifest_path.exists():
        split_all()
    if not skip_extract:
        extract_all(volume="all", limit=extract_limit, force=force)
    compress_all()
    return bootstrap_all(force=force)


def _render_bootstrap_result(result) -> str:
    lines = [f"{result['name']}: {result['status']}", f"path: {result['path']}"]
    if result.get("message"):
        lines.append(result["message"])
    else:
        lines.append(proposal_summary(result))
    return "\n".join(lines) + "\n"


def _render_init_book_results(results) -> str:
    lines = ["init-book proposals:"]
    for name, result in results.items():
        line = f"- {name}: {result['status']} ({result['path']})"
        if result.get("message"):
            line += f" - {result['message']}"
        else:
            line += f" - {proposal_summary(result)}"
        lines.append(line)
    lines.extend(
        [
            "",
            "Review and edit data/proposals/*.proposal.json, then apply each proposal explicitly:",
            "python3 main.py apply-bootstrap --name global_facts",
            "python3 main.py apply-bootstrap --name global_facts --confirm",
            "(repeat for entity_graph, continuation_anchor, style_examples, personas)",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
