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

    sub.add_parser("compress")
    debate_cmd = sub.add_parser("debate")
    debate_cmd.add_argument(
        "--topic",
        default=None,
        help="Override the debate topic; defaults to the legacy validation-corpus topic.",
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

    apply_bootstrap_cmd = sub.add_parser("apply-bootstrap")
    apply_bootstrap_cmd.add_argument("--name", required=True)
    apply_bootstrap_cmd.add_argument("--confirm", action="store_true")

    init_book = sub.add_parser("init-book")
    init_book.add_argument("--skip-extract", action="store_true")
    init_book.add_argument("--extract-limit", type=int, default=10)
    init_book.add_argument("--force", action="store_true")

    plan_chapters = sub.add_parser("plan-chapters")
    plan_chapters.add_argument("--chapters", type=int, default=18)
    plan_chapters.add_argument("--force", action="store_true", help="overwrite existing chapter_plan.json")

    write = sub.add_parser("write")
    write.add_argument("--chapters", type=int, default=18)
    write.add_argument("--resume-from", type=int, default=1)
    write.add_argument("--force", action="store_true")

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
        extract_all(volume=args.volume, limit=args.limit, force=args.force)
    elif args.command == "compress":
        compress_all()
    elif args.command == "debate":
        topic = getattr(args, "topic", None)
        if topic:
            run_debate(topic=topic)
        else:
            run_debate()
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
    elif args.command == "apply-bootstrap":
        print(render_apply_bootstrap_result(apply_bootstrap(args.name, confirm=args.confirm)), end="")
    elif args.command == "init-book":
        results = init_book_pipeline(skip_extract=args.skip_extract, extract_limit=args.extract_limit, force=args.force)
        print(_render_init_book_results(results), end="")
    elif args.command == "plan-chapters":
        from src.plot_planner import generate_chapter_plan

        data = generate_chapter_plan(target_chapters=args.chapters, force=args.force)
        print(f"chapter_plan.json written: {len(data['chapters'])} chapters")
        print(f"overall_arc: {str(data['overall_arc'])[:200]}")
    elif args.command == "write":
        write_chapters(chapters=args.chapters, force=args.force, resume_from=args.resume_from)
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
        status = chapter_status(args.chapter, drafts_dir)
        print(_json.dumps(status, ensure_ascii=False))
    elif args.command == "set-start-point":
        from src import start_point

        try:
            start_point.set_start_point(args.name)
            resolved = start_point.get_start_chapter_id()
            print(f"start point set: {args.name!r} → resolved chapter_id = {resolved!r}")
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
