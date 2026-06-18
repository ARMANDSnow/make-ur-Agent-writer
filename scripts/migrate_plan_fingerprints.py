"""iter057 P0-A: 迁移现存 plan_fingerprint 到新算法(全局上下文哈希)。

plan_fingerprint 在 iter057 从「哈希 chapters 全列表 + target_chapters」收窄为
「只哈希全局上下文(overall_arc + start_chapter_id + start_point_fingerprint)」,
使 --replan-every append 模式不再误伤已写章——详见
``src/plot_planner.py:plan_fingerprint`` 与 docs/AGENT_HANDOFF.md「P0-A」。

算法换代后,现存 workspace 里冻结的旧指纹会与新算法 mismatch
(``chapter_status`` 报 ``plan_fingerprint_mismatch`` → readiness/写章 block →
升级即跑不动)。本脚本一次性把下列文件的旧指纹刷成新算法值:

* ``outputs/debate/chapter_plan.json``         —— plan 自身的 ``plan_fingerprint``
* ``outputs/drafts/chapter_NN.meta.json``      —— ``run_context.plan_fingerprint``
* ``outputs/reviews/chapter_NN.review.json``   —— ``run_context.plan_fingerprint``

新算法下同一个 plan 的所有章共享同一个 plan_fingerprint(只依赖全局上下文),所以
meta/review 一律刷成 ``plan_fingerprint(plan)``。**幂等**:重复跑无改动(已是新值则跳过)。
仅刷 ``plan_fingerprint``,不碰 ``chapter_plan_item_fingerprint``(按章,算法未变)与
``start_point_fingerprint``(起点身份,另有独立校验)。``snapshots/`` 与 ``_`` 开头的
目录(备份/隔离/_trash)不在遍历内。纯 I/O,无 LLM 调用。

用法:
    python3 scripts/migrate_plan_fingerprints.py --workspace longzu
    python3 scripts/migrate_plan_fingerprints.py --all
    python3 scripts/migrate_plan_fingerprints.py --all --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.plot_planner import plan_fingerprint  # noqa: E402
from src.utils import read_json, write_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "workspaces"


def _refresh_run_context_fp(
    json_path: Path, new_fp: str, dry_run: bool
) -> bool:
    """把一个 meta/review 文件的 run_context.plan_fingerprint 刷成 new_fp。

    仅当该文件已有**非空、且不等于 new_fp** 的旧指纹时才改(不给本来没有 plan_fingerprint
    的 legacy 文件强加)。返回是否改动。"""
    data = read_json(json_path, {})
    if not isinstance(data, dict):
        return False
    rc = data.get("run_context")
    if not isinstance(rc, dict):
        return False
    old = rc.get("plan_fingerprint")
    if not old or old == new_fp:
        return False
    rc["plan_fingerprint"] = new_fp
    if not dry_run:
        write_json(json_path, data)
    return True


def migrate_outputs(outputs_dir: Path, dry_run: bool) -> Optional[Dict[str, Any]]:
    """迁移一个 ``outputs/`` 目录(单 workspace 或根)。

    无 ``debate/chapter_plan.json`` 则返回 None(跳过)。"""
    plan_path = outputs_dir / "debate" / "chapter_plan.json"
    if not plan_path.exists():
        return None
    plan = read_json(plan_path, {})
    if not isinstance(plan, dict) or not plan.get("chapters"):
        return None

    # 新算法只读 overall_arc/start_chapter_id/start_point_fingerprint(现存 plan 都有)。
    new_fp = plan_fingerprint(plan)
    old_fp = str(plan.get("plan_fingerprint") or "")
    stats = {
        "plan": 0,
        "meta": 0,
        "review": 0,
        "old_fp": old_fp[:12] or "(none)",
        "new_fp": new_fp[:12],
    }

    # 1) chapter_plan.json 自身
    if old_fp != new_fp:
        plan["plan_fingerprint"] = new_fp
        if not dry_run:
            write_json(plan_path, plan)
        stats["plan"] = 1

    # 2) drafts/chapter_NN.meta.json —— glob 非递归,不进 snapshots/_backup 子目录
    drafts = outputs_dir / "drafts"
    if drafts.is_dir():
        for meta_path in sorted(drafts.glob("chapter_*.meta.json")):
            if _refresh_run_context_fp(meta_path, new_fp, dry_run):
                stats["meta"] += 1

    # 3) reviews/chapter_NN.review.json
    reviews = outputs_dir / "reviews"
    if reviews.is_dir():
        for rev_path in sorted(reviews.glob("chapter_*.review.json")):
            if _refresh_run_context_fp(rev_path, new_fp, dry_run):
                stats["review"] += 1

    return stats


def iter_active_outputs() -> Iterator[Tuple[str, Path]]:
    """所有活跃 workspace 的 outputs/ + 根 outputs/。跳过 ``_`` / ``.`` 开头(备份/隔离/trash)。"""
    if (ROOT / "outputs" / "debate").exists():
        yield "(root)", ROOT / "outputs"
    if WORKSPACES.is_dir():
        for ws in sorted(WORKSPACES.iterdir()):
            if not ws.is_dir() or ws.name.startswith(("_", ".")):
                continue
            outputs = ws / "outputs"
            if outputs.is_dir():
                yield ws.name, outputs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="迁移 plan_fingerprint 到 iter057 P0-A 新算法(全局上下文哈希)"
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--workspace", help="单个 workspace 名(workspaces/<name>/outputs)")
    grp.add_argument("--all", action="store_true", help="所有活跃 workspace + 根 outputs")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写盘")
    args = ap.parse_args(argv)

    if args.workspace:
        targets = [(args.workspace, WORKSPACES / args.workspace / "outputs")]
    else:
        targets = list(iter_active_outputs())

    tag = "[dry-run] " if args.dry_run else ""
    total = {"plan": 0, "meta": 0, "review": 0}
    touched = 0
    for name, outputs in targets:
        stats = migrate_outputs(outputs, args.dry_run)
        if stats is None:
            print(f"{tag}{name}: 跳过(无 chapter_plan.json)")
            continue
        touched += 1
        for key in ("plan", "meta", "review"):
            total[key] += stats[key]
        print(
            f"{tag}{name}: plan_fp {stats['old_fp']}→{stats['new_fp']} "
            f"| plan={stats['plan']} meta={stats['meta']} review={stats['review']}"
        )
    print(
        f"\n{tag}完成: 处理 {touched} 个 workspace,"
        f" 刷新 plan={total['plan']} meta={total['meta']} review={total['review']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
