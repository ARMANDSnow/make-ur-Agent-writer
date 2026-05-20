from __future__ import annotations

import argparse
from pathlib import Path

from src.chapter_splitter import split_all
from src.cli_apply_advance import apply_advance_cli, render_apply_advance_result
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
from src.preflight import render_preflight, run_preflight
from src.reviewer import review_target
from src.text_normalizer import normalize_all
from src.writer import write_chapters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dragon Raja AI Continuer MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("normalize")
    sub.add_parser("split")
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
    sub.add_parser("debate")

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
    apply_advance.add_argument("--proposal-idx", required=True)
    apply_advance.add_argument("--confirm", action="store_true")

    run_all = sub.add_parser("run-all")
    run_all.add_argument("--chapters", type=int, default=18)
    run_all.add_argument("--extract-limit", type=int, default=None)
    run_all.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "normalize":
        normalize_all()
    elif args.command == "split":
        split_all()
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
        run_debate()
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
        review_target(Path(f"outputs/drafts/chapter_{args.chapter:02d}.md"), enforce_relationship_checklist=True)
    elif args.command == "apply-advance":
        result = apply_advance_cli(args.chapter, args.proposal_idx, confirm=args.confirm)
        print(render_apply_advance_result(result), end="")
    elif args.command == "run-all":
        normalize_all()
        split_all()
        extract_all(volume="all", limit=args.extract_limit, force=args.force)
        compress_all()
        run_debate()
        write_chapters(chapters=args.chapters, force=args.force)


if __name__ == "__main__":
    main()
