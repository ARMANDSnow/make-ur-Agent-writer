from __future__ import annotations

import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import paths, readiness_catalog, review_tier, run_params, source_excerpts, start_point
from .chapter_summary import prune_from_chapter
from .chapter_status import (
    ChapterDisposition,
    chapter_status,
    classify_disposition,
    is_resumable_stale_reject,
)
from .config import is_mock_mode, load_config
from .cost_estimator import estimate_cost_since, estimate_next_chapter_cost
from .entity_advance import (
    apply_advance_proposals,
    proposal_path,
    select_auto_indexes,
    unapplied_auto_indexes,
)
from .preflight import run_preflight
from .proposal_validator import validate_proposals_against_plan
from .reviewer import review_target
from .utils import ensure_dir, read_json_optional, write_json
from .kb_view import start_safe_knowledge
from .workspace_lock import WorkspaceLocked, acquire_write_lock
from .writer import (
    ChapterPlanInvalid,
    _chapter_plan_item,
    _enforce_checklist_for_plan,
    _index_path,
    _kb_path,
    _load_chapter_plan,
    _review_feedback,
    _run_context,
    write_chapters,
)


class BookRunBlocked(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    def __init__(self, *, budget_cny: float, cost_cny: float) -> None:
        self.budget_cny = float(budget_cny)
        self.cost_cny = float(cost_cny)
        super().__init__(f"budget_cny exceeded: {self.cost_cny:.4f} > {self.budget_cny:.4f}")


def _panel_block_policy(*, emit_stderr: bool = True) -> Dict[str, Any]:
    """iter076 HIGH#1：读 agents.yaml 的 ``panel_block_policy``。

    缺失/坏值一律回落保守默认（halt / halt / 0 = 与历史行为一致：重试耗尽即停
    全书）。枚举值宽容 ``-``/``_`` 与大小写差异。

    iter077 P0-3：**显式给出但解析失败**的值不再静默回落——收集进返回值的
    ``config_warnings``（默认同时打一行 stderr），preflight 据此前置校验；
    「配了 caveat_continue 却 max_panel_rejections<=0」的自相矛盾组合（caveat
    永不触发、等效 halt）同样告警。键缺失走默认**不**告警。"""
    raw = load_config("agents.yaml").get("panel_block_policy") or {}
    config_warnings: List[str] = []
    if not isinstance(raw, dict):
        config_warnings.append(
            f"panel_block_policy 配置块应为 mapping，得到 {type(raw).__name__}：全部回落保守默认 halt/halt/0"
        )
        raw = {}

    def _enum(key: str, allowed: tuple, default: str) -> str:
        raw_val = raw.get(key)
        val = str(raw_val or default).strip().lower().replace("-", "_")
        if val in allowed:
            return val
        config_warnings.append(
            f"panel_block_policy.{key}={raw_val!r} 非法（可选 {'/'.join(allowed)}）：回落 '{default}'"
        )
        return default

    raw_max = raw.get("max_panel_rejections")
    if isinstance(raw_max, bool):
        # yaml 裸 true/false 会被 int() 静默变 1/0——这是配置手误不是配额。
        config_warnings.append(
            f"panel_block_policy.max_panel_rejections={raw_max!r} 是布尔值（yaml 手误？）：回落 0"
        )
        max_rejections = 0
    else:
        try:
            max_rejections = int(raw_max or 0)
        except (TypeError, ValueError):
            config_warnings.append(
                f"panel_block_policy.max_panel_rejections={raw_max!r} 无法解析为整数：回落 0"
            )
            max_rejections = 0
        if max_rejections < 0:
            config_warnings.append(
                f"panel_block_policy.max_panel_rejections={raw_max!r} 为负：按 0 处理"
            )
            max_rejections = 0
    policy: Dict[str, Any] = {
        "on_soft_reject": _enum("on_soft_reject", ("halt", "caveat_continue"), "halt"),
        "max_panel_rejections": max_rejections,
        "on_hard_reject": _enum(
            "on_hard_reject", ("halt", "force_once", "caveat_continue"), "halt"
        ),
    }
    if (
        "caveat_continue" in (policy["on_soft_reject"], policy["on_hard_reject"])
        and policy["max_panel_rejections"] <= 0
    ):
        config_warnings.append(
            "panel_block_policy: 配了 caveat_continue 但 max_panel_rejections<=0，"
            "caveat 永不触发（等效 halt）；两键需一起设"
        )
    policy["config_warnings"] = config_warnings
    if emit_stderr:
        for msg in config_warnings:
            print(f"[panel_block_policy] WARN: {msg}", file=sys.stderr)
    return policy


def _budget_reserve_cfg() -> Dict[str, float]:
    """iter076 HIGH#2：读 agents.yaml 的 ``budget_reserve``，坏值回落默认
    （safety_factor=1.5 / default_chapter_cost_cny=2.0）。"""
    raw = load_config("agents.yaml").get("budget_reserve") or {}
    if not isinstance(raw, dict):
        raw = {}

    def _finite(key: str, default: float, *, minimum_exclusive: float | None = None) -> float:
        try:
            val = float(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        if not math.isfinite(val):
            return default
        if minimum_exclusive is not None and val <= minimum_exclusive:
            return default
        return val

    # 审查 B L4：负 default = 坏值**回落默认 2.0**（与 agents.yaml note 口径一致），
    # 不再 clamp 成 0（0 是合法显式值=「首章不预留」，负数是配置手误）。
    default_cost = _finite("default_chapter_cost_cny", 2.0)
    if default_cost < 0:
        default_cost = 2.0
    return {
        "safety_factor": _finite("safety_factor", 1.5, minimum_exclusive=0.0),
        "default_chapter_cost_cny": default_cost,
    }


# iter078 技债-1：谓词与白名单下沉 chapter_status 单一真源（run/readiness 两条
# 平行链已第三次同步手改，iter077 谓词漏 failure 正是平行维护的实证）。旧名
# 保留为别名——test_iter077_stale_reject_resume 等既有 import 面零改动。
from .chapter_status import RESUMABLE_REJECT_FAILURES as _RESUMABLE_REJECT_FAILURES  # noqa: E402

_is_resumable_stale_reject = is_resumable_stale_reject


def _mark_panel_halted(drafts_dir: Path, chapter_no: int, *, reason: str) -> None:
    """iter077 审查修复：把「重试耗尽/硬拦 → halt 停机」的分诊结论落盘到 meta。

    只追加 ``panel_halted`` 字段；`_archive_chapter_artifacts`（force/caveat 后
    重写）搬走 meta 即自然清除。resume 时 `_is_resumable_stale_reject` 据此
    拒绝自动重写，保持 exhausted-halt 章的 BookRunBlocked 原语义。"""
    meta_path = Path(drafts_dir) / f"chapter_{chapter_no:02d}.meta.json"
    meta = read_json_optional(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    meta["panel_halted"] = {"reason": reason, "at": datetime.now(timezone.utc).isoformat()}
    write_json(meta_path, meta)


def _count_existing_caveats(drafts_dir: Path) -> int:
    """盘面上已被 caveat 放行的章数。

    审查 A2a：caveat 预算必须**跨 run 累计**——``caveats`` 列表随 run 重建、
    resume 时 caveat 章走 skipped_caveat 不计数，若不把盘面存量计入，
    crash→supervisor 自动 resume 每轮都重置配额，max_panel_rejections 形同虚设
    （cap=2 的过夜跑重启 3 次理论可放行 8 章）。"""
    count = 0
    try:
        for meta_path in Path(drafts_dir).glob("chapter_*.meta.json"):
            meta = read_json_optional(meta_path, {})
            if isinstance(meta, dict) and meta.get("caveat_approved"):
                count += 1
    except OSError:
        pass
    return count


def _mark_caveat_approved(drafts_dir: Path, chapter_no: int, *, reason: str) -> None:
    """iter076 HIGH#1：把重试耗尽仍被拒的章标记为 caveat 放行。

    只追加字段：verdict 仍 Reject、needs_human_review 仍 True（早晨复查入口不变、
    web 投影不受影响）、正文与 draft_sha256 不动。chapter_status 据 ``caveat_approved``
    在 resume 时跳过该章。

    iter077 P0-2 断点B：lint 终败章盘面带 ``failure.json``，而 chapter_status 要求
    ``not failure`` 才认 caveat_approved（failure = 未分诊的硬失败）。caveat 放行
    就是分诊——把 marker 原子改名归档（``*.failure.caveat.json``，审计内容保留），
    否则该章 resume 时永远进不了 skipped_caveat，直接 BookRunBlocked（exit 4 终态）。
    归档失败时让 OSError 直接抛出（宁可本 run failed，也不留「caveat_approved=True
    但 failure 仍在」的半标记状态——那会伪装成放行成功、下次 resume 才炸）。"""
    meta_path = Path(drafts_dir) / f"chapter_{chapter_no:02d}.meta.json"
    meta = read_json_optional(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    failure_path = Path(drafts_dir) / f"chapter_{chapter_no:02d}.failure.json"
    if failure_path.exists():
        archived = failure_path.with_name(f"chapter_{chapter_no:02d}.failure.caveat.json")
        os.replace(failure_path, archived)
        meta["caveat_archived_failure"] = archived.name
    meta["caveat_approved"] = True
    meta["caveat_reason"] = reason
    meta["caveat_at"] = datetime.now(timezone.utc).isoformat()
    write_json(meta_path, meta)


def run_write_book(*, lock_source: str = "cli-write-book", **kwargs: Any) -> Dict[str, Any]:
    """Production write entrypoint shared by CLI/Web wrappers.

    iter078 P1-7: the whole run holds the workspace write lock
    (src/workspace_lock.py) — CLI ``write-book``, driver step 子进程与
    Web job 三路写者互斥。拿不到锁包成 ``BookRunBlocked``（exit 4 家族 /
    driver blocked 终态 / Web job 失败路径沿用既有契约，零新退出码）。

    ``lock_source`` 只进 holder json 供被拒方诊断（``cli-write-book`` /
    ``web-job`` …）；其余参数见 :func:`_run_write_book_unlocked`。
    """
    try:
        with acquire_write_lock(source=lock_source):
            return _run_write_book_unlocked(**kwargs)
    except WorkspaceLocked as exc:
        raise BookRunBlocked(str(exc)) from exc


def _run_write_book_unlocked(
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
    tier: str | None = None,
) -> Dict[str, Any]:
    """run_write_book 的锁内实现（签名即公开参数表）。

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
        include_next_unapproved=False,
        # iter078 P1-6: readiness 与 run 用同一 tier 口径做指纹比对。
        tier=tier,
    )
    if readiness.get("status") == "blocked":
        commands = "; ".join(readiness.get("recommended_commands") or [])
        suffix = f"; next: {commands}" if commands else ""
        raise BookRunBlocked("; ".join(readiness.get("blockers") or ["write-book is blocked"]) + suffix)
    # iter059 #4: readiness (require_plan=True) already blocks a corrupt plan
    # before here; the require_plan=False path may not, so degrade a corrupt
    # plan to None rather than raising mid-run.
    try:
        plan = _load_chapter_plan()
    except ChapterPlanInvalid:
        plan = None

    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    initial_log_lines = _llm_log_line_count()
    written: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    advances: List[Dict[str, Any]] = []
    costs: List[Dict[str, Any]] = []
    max_retries = max(0, int(max_retries))
    replan_every = max(0, int(replan_every))
    budget_cny = float(budget_cny or 0.0)
    # iter064 #1: last-line defense for programmatic callers that bypass the
    # CLI/Web validators (src/run_params.py). A non-finite budget (NaN/Inf)
    # makes `current_cost > budget_cny` always False (IEEE-754), silently
    # disabling the cost gate — degrade it to 0.0 ("no budget cap", the
    # documented default) so the math below stays well-defined.
    if not math.isfinite(budget_cny):
        budget_cny = 0.0
    resolved_tier = review_tier.resolve_tier(tier)
    # iter078 P1-6: 章级指纹的 model 侧期望值（每 run 一次，非每章）。
    expected_model = _expected_write_model()
    # iter076 HIGH#1：面板拒稿整书策略（默认保守 = 现行为）。caveats 记录本 run 内
    # 被 caveat 放行的章，进 summary 供 CLI/jobs 透出；盘面存量另计（审查 A2a：
    # 配额跨 run 累计，supervisor 自动 resume 不重置）。
    panel_policy = _panel_block_policy()
    caveats: List[Dict[str, Any]] = []
    preexisting_caveats = (
        _count_existing_caveats(drafts_dir)
        if panel_policy["max_panel_rejections"] > 0
        else 0
    )
    # iter076 HIGH#2：每章预算预留配置（仅 budget_cny>0 时用到）。
    reserve_cfg = _budget_reserve_cfg()

    def _snap(status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # iter077 P0-3：每个快照回显生效的 panel_block_policy——配置手滑静默回落
        # halt 时，操作者能从任何 run 产物（含 jobs 投影）直接看出实际生效值，
        # 不用等凌晨第一章软拒才发现整套拒稿不停机没生效。
        payload.setdefault("panel_policy", panel_policy)
        return _snapshot(status, payload)

    def budget_check_cb() -> float:
        if budget_cny <= 0:
            return 0.0
        current_cost = float(estimate_cost_since(initial_log_lines).get("cost_cny", 0.0))
        if current_cost > budget_cny:
            raise BudgetExceeded(budget_cny=budget_cny, cost_cny=current_cost)
        return current_cost

    for offset, chapter_no in enumerate(range(int(resume_from), int(resume_from) + total), start=1):
        chapter_base = 0.1 + 0.8 * ((offset - 1) / total)
        chapter_span = 0.8 / total
        progress(f"chapter-{chapter_no}", chapter_base)
        _last_progress = chapter_base
        _current_retry = 0

        def _chapter_progress(sub_step: str, sub_fraction: float) -> None:
            nonlocal _last_progress
            raw_progress = chapter_base + chapter_span * float(sub_fraction)
            next_progress = max(_last_progress, raw_progress)
            _last_progress = next_progress
            prefix = f"retry-{_current_retry}/" if _current_retry > 0 else ""
            progress(f"chapter-{chapter_no}/{prefix}{sub_step}", next_progress)

        if budget_cny > 0:
            try:
                budget_check_cb()
            except BudgetExceeded as exc:
                progress("budget_exceeded", 1.0)
                return _snap(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "caveats": caveats,
                        "costs": costs,
                        "budget_cny": budget_cny,
                        "cost_cny": exc.cost_cny,
                    },
                )
        item = _chapter_plan_item(plan, chapter_no) if plan else None
        expected = _run_context(
            item,
            chapter_no=chapter_no,
            model=expected_model,
            review_tier=resolved_tier,
        )
        status = chapter_status(
            chapter_no,
            drafts_dir,
            validate_context=True,
            require_start_point=require_start_point,
            require_plan=require_plan,
            require_external_review=require_external_review,
            expected_context=expected,
        )
        # iter078 技债-1：处置五分类改消费 chapter_status.classify_disposition
        # 单一真源（判定收敛，动作留在本循环）。skip 分支语义 = iter076 HIGH#1
        # （caveat 放行残迹非 stale，resume 跳过不重写；force 仍可覆盖）。
        disposition = classify_disposition(
            status, force=force, require_external_review=require_external_review
        )
        if disposition in (
            ChapterDisposition.SKIP_APPROVED,
            ChapterDisposition.SKIP_CAVEAT,
        ):
            entry = {
                "chapter": chapter_no,
                "action": (
                    "skipped_approved"
                    if disposition is ChapterDisposition.SKIP_APPROVED
                    else "skipped_caveat"
                ),
                "status": status,
            }
            # iter078 P1-4①: skip 章的 advance 丢失补偿（sidecar 缺失 + 提案
            # 在盘才触发；锚点去重保 legacy 幂等；零 LLM）。
            if auto_advance:
                comp = _compensate_missing_advance(
                    drafts_dir, chapter_no, min_confidence=min_confidence
                )
                if comp is not None:
                    advances.append(comp)
                    entry["advance_compensated"] = True
            written.append(entry)
            continue
        stale_reject_rewrite = disposition is ChapterDisposition.STALE_REJECT_REWRITE
        md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
        if disposition is ChapterDisposition.SUPPLEMENT_EXTERNAL_REVIEW:
            review_target(
                md_path,
                # iter073 (codex A2): derive warn_only for broad-cast chapters
                # (>4 relationships) so the external review matches the main
                # review instead of hardcoding strict True.
                enforce_relationship_checklist=_enforce_checklist_for_plan(item),
                tier=resolved_tier,
                # iter073 (codex B3): plan-compliance also runs in external review.
                chapter_plan_item=item,
                **_build_review_context(item),
            )
            _sync_meta_with_external_review(drafts_dir, chapter_no)
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
                # iter078 收官审查修复：补审通过出口与 SKIP 分支同款补偿。
                # 「正文+meta+提案落盘 → 外审」窗口被杀的章正是走本分支，
                # advance/sidecar 双缺失；不当场补偿，本 run 后续章会全程
                # 注入停滞的实体状态（下次重启的 SKIP 补偿救不了本 run）。
                if auto_advance:
                    comp = _compensate_missing_advance(
                        drafts_dir, chapter_no, min_confidence=min_confidence
                    )
                    if comp is not None:
                        advances.append(comp)
                        written[-1]["advance_compensated"] = True
                continue
            # iter077 P0-5（审查 A3-F4 附带）：补外审被拒不再 blocked+break
            # 绕过 panel_block_policy——与重试耗尽同款分诊：可 caveat 则放行
            # 继续写后续章，否则照旧 blocked。
            hard = bool(status.get("hard_reject"))
            on_reject = panel_policy["on_hard_reject"] if hard else panel_policy["on_soft_reject"]
            if (
                on_reject == "caveat_continue"
                and (len(caveats) + preexisting_caveats)
                < panel_policy["max_panel_rejections"]
            ):
                _mark_caveat_approved(
                    drafts_dir,
                    chapter_no,
                    reason="panel_hard_reject" if hard else "panel_soft_reject",
                )
                written[-1]["action"] = "reviewed_existing_with_caveats"
                caveats.append(
                    {
                        "chapter": chapter_no,
                        "hard_reject": hard,
                        "verdict": status.get("verdict"),
                        "rewrite_count": status.get("rewrite_count"),
                    }
                )
                # 同上：caveat 放行出口也是「章尘埃落定不重写」，补偿对称。
                if auto_advance:
                    comp = _compensate_missing_advance(
                        drafts_dir, chapter_no, min_confidence=min_confidence
                    )
                    if comp is not None:
                        advances.append(comp)
                        written[-1]["advance_compensated"] = True
                progress(f"chapter-{chapter_no}/caveat_continue", _last_progress)
                continue
            _mark_panel_halted(
                drafts_dir,
                chapter_no,
                reason="hard_reject" if hard else "external_review_reject",
            )
            blocked.append(
                {
                    "chapter": chapter_no,
                    "reason": "hard_reject" if hard else "external_review_reject",
                    "status": status,
                }
            )
            break
        elif disposition is ChapterDisposition.BLOCK:
            raise BookRunBlocked(
                f"chapter_{chapter_no:02d} has existing non-approved or stale outputs; "
                "inspect them or rerun write-book with --force"
            )
        # STALE_REJECT_REWRITE（iter077 P0-5：同配置中断期拒稿残迹）与
        # FRESH_WRITE 都落进下方重试循环；stale 章 attempt 0 即归档+重写
        # （等价于跨进程死亡续接上一周期的 retry），而不是 BookRunBlocked 终态。
        # iter076 HIGH#2：章前预算预留——真正要**整章重写**的章，动笔前确认
        # 「剩余预算 ≥ safety_factor × 下一章预估成本」，不足则干净收场（已写各章
        # 完好、复用 exit 3 的 budget_exceeded 管道），而不是写到一半耗尽留半成品。
        # 位置（审查 A3）：skip 判断与 reviewed_existing 补外审分支**之后**——skip 章
        # 零花费、补外审只花外审零头，都不该被整章额度的预留闸误停；「已超支」由
        # 章循环开头的首道闸兜。此处 budget_check_cb 仍可能发现已超支（如上一章
        # 评审后越线，审查 B L5）——接住并走与首道闸一致的干净收场。
        if budget_cny > 0:
            try:
                current_cost = budget_check_cb()
            except BudgetExceeded as exc:
                progress("budget_exceeded", 1.0)
                return _snap(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "caveats": caveats,
                        "costs": costs,
                        "budget_cny": budget_cny,
                        "cost_cny": exc.cost_cny,
                    },
                )
            estimated_next = estimate_next_chapter_cost(
                costs, reserve_cfg["default_chapter_cost_cny"]
            )
            reserve_needed = reserve_cfg["safety_factor"] * estimated_next
            remaining = budget_cny - current_cost
            if remaining < reserve_needed:
                progress("budget_exceeded", 1.0)
                return _snap(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "caveats": caveats,
                        "costs": costs,
                        "budget_cny": budget_cny,
                        "cost_cny": current_cost,
                        "reserve_stop": True,
                        "estimated_next_chapter_cny": round(estimated_next, 4),
                        "reserve_needed_cny": round(reserve_needed, 4),
                        "remaining_cny": round(remaining, 4),
                    },
                )
        reports: List[Dict[str, Any]] = []
        status = {}
        attempt_summaries: List[Dict[str, Any]] = []
        try:
            # iter076 HIGH#1：for range(max_retries+1) → while——hard reject 且
            # on_hard_reject=force_once 时在耗尽后追加**一轮** bonus 重写（每章
            # 一次），其余语义与原 for 循环逐字节一致。
            attempt = 0
            attempts_allowed = max_retries + 1
            bonus_granted = False
            while attempt < attempts_allowed:
                _current_retry = attempt
                seed_feedback = ""
                if attempt > 0 or ((force or stale_reject_rewrite) and md_path.exists()):
                    # iter 053b（审查 B3）：归档之前先把上一周期的拒因收割成
                    # 播种 feedback——归档会连 review/meta 一起搬走，此后周期
                    # 内第一稿对上一周期的 block 拒因（gf_longzu_014/015 这类
                    # 外审命中）完全失忆，052 九稿横盘的周期间断链。只在
                    # retry（attempt>0）播种；force 重写是操作者主动行为，
                    # 不带历史包袱。iter077 P0-5：stale 拒稿续接**是**跨进程
                    # 死亡的 retry 延续——同样播种，别让重写重蹈上一稿拒因。
                    if attempt > 0 or stale_reject_rewrite:
                        seed_feedback = _cross_cycle_seed_feedback(drafts_dir, chapter_no)
                    archive_dir = _archive_chapter_artifacts(
                        drafts_dir,
                        chapter_no,
                        reason=(
                            f"retry_attempt_{attempt}"
                            if attempt > 0
                            else ("stale_reject_resume" if stale_reject_rewrite else "force_rewrite")
                        ),
                    )
                    prune_from_chapter(chapter_no)
                    attempt_summaries.append({"attempt": attempt, "archived_to": str(archive_dir)})
                elif not md_path.exists():
                    # iter078 P1-5（belt&suspenders）：fresh write 前清一次 rolling
                    # 尾巴——iter078 之前的落盘顺序（rolling 先于正文）死在窗口内
                    # 会留下「rolling 有本章摘要、正文不存在」的毒行；本章即将
                    # 重写，任何 >= 本章的 rolling 条目都是残迹。幂等零 LLM。
                    prune_from_chapter(chapter_no)
                write_reports = write_chapters(
                    chapters=1,
                    resume_from=chapter_no,
                    force=True,
                    progress_cb=_chapter_progress,
                    budget_check_cb=budget_check_cb,
                    tier=resolved_tier,
                    seed_feedback=seed_feedback,
                )
                reports.extend(write_reports if isinstance(write_reports, list) else [write_reports])
                if require_external_review and md_path.exists():
                    review_target(
                        md_path,
                        # iter073 (codex A2 + B3): warn_only for broad-cast chapters
                        # + plan-compliance in external review, matching main review.
                        enforce_relationship_checklist=_enforce_checklist_for_plan(item),
                        tier=resolved_tier,
                        chapter_plan_item=item,
                        **_build_review_context(item),
                    )
                    _sync_meta_with_external_review(drafts_dir, chapter_no)
                    budget_check_cb()
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
                # iter076 HIGH#1：最后一轮仍是 hard reject 且策略 force_once →
                # 追加一轮 bonus（每章仅一次），仍不过下方按 hard halt 收场。
                if (
                    attempt == attempts_allowed - 1
                    and not bonus_granted
                    and bool(status.get("hard_reject"))
                    and panel_policy["on_hard_reject"] == "force_once"
                ):
                    bonus_granted = True
                    attempts_allowed += 1
                    attempt_summaries.append(
                        {"attempt": attempt, "bonus_granted": True, "reason": "hard_reject_force_once"}
                    )
                attempt += 1
        except BudgetExceeded as exc:
            progress("budget_exceeded", 1.0)
            payload: Dict[str, Any] = {
                "chapters": written,
                "blocked": blocked,
                "advances": advances,
                "caveats": caveats,
                "costs": costs,
                "budget_cny": exc.budget_cny,
                "cost_cny": exc.cost_cny,
            }
            partial = _partial_artifact(drafts_dir, chapter_no)
            if partial:
                payload["partial"] = partial
            return _snap("budget_exceeded", payload)
        except Exception as exc:
            progress("failed", 1.0)
            payload: Dict[str, Any] = {
                "chapters": written,
                "blocked": blocked,
                "advances": advances,
                "caveats": caveats,
                "costs": costs,
                "error": f"{type(exc).__name__}: {exc}",
            }
            partial = _partial_artifact(drafts_dir, chapter_no)
            if partial:
                payload["partial"] = partial
            return _snap("failed", payload)
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
            # iter076 HIGH#1：重试耗尽后按 panel_block_policy 分诊——soft（面板
            # 投票分歧）可 caveat 放行继续写后续章（过夜不 halt），hard（synthetic
            # 确定性硬拦）默认必停；caveat 超出 max_panel_rejections 预算回落 halt。
            hard = bool(status.get("hard_reject"))
            on_reject = panel_policy["on_hard_reject"] if hard else panel_policy["on_soft_reject"]
            can_caveat = (
                on_reject == "caveat_continue"
                and (len(caveats) + preexisting_caveats)
                < panel_policy["max_panel_rejections"]
            )
            if can_caveat:
                _mark_caveat_approved(
                    drafts_dir,
                    chapter_no,
                    reason="panel_hard_reject" if hard else "panel_soft_reject",
                )
                if written and written[-1].get("chapter") == chapter_no:
                    written[-1]["action"] = "written_with_caveats"
                caveats.append(
                    {
                        "chapter": chapter_no,
                        "hard_reject": hard,
                        "verdict": status.get("verdict"),
                        "rewrite_count": status.get("rewrite_count"),
                    }
                )
                progress(f"chapter-{chapter_no}/caveat_continue", _last_progress)
                # fall through：auto_advance / costs / replan 照常——实体推进与
                # 滚动摘要必须跟上正文，否则后续章拿到断档上下文。
            else:
                _mark_panel_halted(
                    drafts_dir,
                    chapter_no,
                    reason="hard_reject" if hard else "retry_exhausted",
                )
                blocked.append(
                    {
                        "chapter": chapter_no,
                        "reason": "hard_reject" if hard else "retry_exhausted",
                        "status": status,
                    }
                )
                break
        if auto_advance:
            advance_result = _auto_apply_advances(chapter_no, min_confidence=min_confidence)
            advances.append(advance_result)
            # iter078 P1-4①: 处置完成即落盘 sidecar——resume 补偿只认它。
            _mark_advance_applied(drafts_dir, chapter_no, advance_result)
        if budget_cny > 0:
            cost = estimate_cost_since(initial_log_lines)
            costs.append({"chapter": chapter_no, **cost})
            if float(cost.get("cost_cny", 0.0)) > budget_cny:
                progress("budget_exceeded", 1.0)
                return _snap(
                    "budget_exceeded",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "caveats": caveats,
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
                return _snap(
                    "blocked",
                    {
                        "chapters": written,
                        "blocked": blocked,
                        "advances": advances,
                        "caveats": caveats,
                        "costs": costs,
                    },
                )

    final_status = "blocked" if blocked else "succeeded"
    progress(final_status, 1.0)
    return _snap(
        final_status,
        {"chapters": written, "blocked": blocked, "advances": advances, "caveats": caveats, "costs": costs},
    )


def check_write_readiness(
    *,
    chapters: int,
    resume_from: int = 1,
    replan_every: int = 0,
    require_start_point: bool = True,
    require_plan: bool = True,
    require_external_review: bool = True,
    allow_existing_blockers: bool = False,
    include_next_unapproved: bool = True,
    tier: str | None = None,
) -> Dict[str, Any]:
    """Return the user-facing production writing gate as JSON data."""

    # iter078 P1-6: 指纹比对的 model/tier 期望值。脏 tier（env 手滑）由
    # preflight FATAL 与 run 侧 resolve_tier raise 负责报错，readiness 这里
    # 宽容降级为空串（比对侧「双方非空才比对」→ 跳过 tier 指纹），不抢报。
    # iter078 收官审查修复：tier=None 且 env 未设 = 调用方根本没表达 tier 意图
    # （独立 write-readiness / Web readiness）——不得拿 DEFAULT_TIER 冒充期望值，
    # 否则 --tier high 写出的章会被误判 review_tier_mismatch → 逐章 BLOCK。
    # 置空串跳过 tier 指纹；run_write_book 内部调用始终显式传 tier，不受影响。
    try:
        if tier is None and not os.getenv("WRITE_REVIEW_TIER", "").strip():
            resolved_tier = ""
        else:
            resolved_tier = review_tier.resolve_tier(tier)
    except ValueError:
        resolved_tier = ""
    expected_model = _expected_write_model()
    total = max(1, int(chapters))
    resume_from = int(resume_from)
    replan_every = max(0, int(replan_every))
    plan_window = min(total, replan_every) if replan_every > 0 else total
    chapter_numbers = list(range(resume_from, resume_from + plan_window))
    blockers: List[str] = []
    warnings: List[str] = []
    recommended: List[str] = []
    cmd_prefix = _main_cmd_prefix()

    # iter 051b (F6): presence gate routed through the centralized
    # start_point.enforce_consistency (same entry-point plot_planner uses);
    # blocker string unchanged.
    if "start_point_missing" in start_point.enforce_consistency(
        require_start_point=require_start_point
    ):
        blockers.append("start_point_missing")
        recommended.append(f"{cmd_prefix} set-start-point <chapter_id>")

    raw_plan = _load_raw_chapter_plan()
    plan = None
    plan_invalid = False
    try:
        plan = _load_chapter_plan()
    except ChapterPlanInvalid:
        # iter059 #4 (Option B): a distinct chapter_plan_invalid blocker so the
        # user can tell a damaged plan from an absent one; same regenerate CTA.
        plan_invalid = True
    if require_plan and plan_invalid:
        blockers.append("chapter_plan_invalid")
        recommended.append(
            f"{cmd_prefix} plan-chapters --chapters {max(plan_window, 5)} --force --require-start-point"
        )
    elif require_plan and not plan:
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

    # iter 053a (审查 A4/A1): warn lane for debate-intermediate provenance.
    # The HARD gate lives at plan generation (plot_planner); but the writer
    # also injects the outline verbatim into every chapter prompt, so a stale
    # outline at write time still matters — surface it here as warnings
    # (never blockers: legacy workspaces without provenance stay fail-open).
    # Same lane checks plan↔outline lineage: after a debate rerun the old
    # plan goes stale while its F6 fingerprints stay green.
    outline_p = (
        paths.outline_path()
        if paths.workspace_name()
        else Path("outputs/debate/outline.md")
    )
    if outline_p.exists():
        try:
            outline_text = outline_p.read_text(encoding="utf-8")
        except OSError:
            outline_text = None
        if outline_text is not None:
            decisions_p = (
                paths.debate_decisions_path()
                if paths.workspace_name()
                else Path("outputs/debate/decisions.json")
            )
            decisions = read_json_optional(decisions_p, {})
            warnings.extend(
                f"debate_outline:{code}"
                for code in start_point.outline_consistency_failures(
                    decisions, outline_text=outline_text
                )
            )
            warnings.extend(
                f"chapter_plan:{code}"
                for code in start_point.plan_outline_lineage_failures(
                    raw_plan, outline_text=outline_text
                )
            )
            # iter057 P1-C: outline↔实际剧情语义漂移(确定性命中率探针)。上面的
            # provenance 守卫发现不了「outline 没变、但剧情走远了」;此处补可见性。
            # iter073 (codex I): SEVERE 持续漂移(大纲核心实体在最近 RECENT_K 章聚合
            # 窗口里几乎全部缺席,hit_rate<20% 且锚点≥5)对续写(require_start_point)
            # 升级为硬 blocker——过时大纲会逐字喂进每章 prompt 误导承接;新书保留
            # fail-open warn(铁律④),普通漂移仍只 warn。block 受 config 开关控制便于
            # 回退。best-effort:任何异常都不得让探针 block readiness(漏报优于误 block)。
            try:
                from . import outline_drift, chapter_summary, entities

                _rolling = chapter_summary.load_rolling_summary()
                _egraph = entities.load_entity_graph()
                _drift_codes = outline_drift.outline_drift_codes(
                    outline_text, _rolling, _egraph
                )
                _severity = outline_drift.outline_drift_severity(
                    outline_text, _rolling, _egraph
                )
                if (
                    _severity == "severe"
                    and require_start_point
                    and _outline_drift_block_enabled()
                ):
                    _drift_code = (_drift_codes or ["semantic_drift"])[0]
                    blockers.append(f"outline_severe_drift:{_drift_code}")
                    # NB: --force does NOT clear this blocker (allow_existing_blockers
                    # only suppresses existing_output_not_strict_approved). To
                    # override, regenerate the outline (run-debate) or disable the
                    # gate in config/agents.yaml (outline_drift_block.enabled=false).
                    recommended.append(
                        f"{cmd_prefix} run-debate  # 剧情已显著偏离大纲，重新生成大纲后再续写"
                        "（已写好的正文不受影响）；如确认要无视，改 config/agents.yaml 的 outline_drift_block.enabled=false"
                    )
                else:
                    warnings.extend(f"outline_{code}" for code in _drift_codes)
            except Exception:
                pass

    # iter 053g（053c 实跑根因③）：起点前最近章节的提取覆盖 warn——提取层
    # 是 KB/实体图的底座，没跟上起点时评审会拿旧状态当硬尺连拒正确稿件。
    missing_extraction = start_point.extraction_coverage_failures(k=10)
    if missing_extraction:
        preview = ",".join(missing_extraction[:5])
        more = f"(+{len(missing_extraction) - 5} more)" if len(missing_extraction) > 5 else ""
        signal = f"extraction:start_window_unextracted:{preview}{more}"
        # iter068 (Cluster E): for an existing-book continuation
        # (require_start_point) the start-window提取 gap is a hard BLOCKER, not a
        # warning — the KB/entity_graph base锚在旧状态会让评审拿旧尺连拒正确稿件
        # (053c 根因③ / 052 假基线). plot_planner already hard-raises the same gap
        # (iter054b); surfacing it on the continue page proactively lets the user
        # rebuild-for-start BEFORE spending on debate/plan. greenfield
        # (require_start_point=False) keeps the 053g fail-open warn lane (铁律④).
        if require_start_point:
            blockers.append(signal)
        else:
            warnings.append(signal)
        recommended.append(
            f"{cmd_prefix} rebuild-for-start  # 起点前最近章节缺提取，"
            "重建续写底座（补提取窗口 → 重建 KB/实体图/锚点）"
        )

    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    next_unapproved_chapter = None
    if include_next_unapproved:
        next_unapproved_chapter = _next_unapproved_chapter(
            raw_plan=raw_plan,
            plan=plan,
            drafts_dir=drafts_dir,
            resume_from=resume_from,
            require_start_point=require_start_point,
            require_plan=require_plan,
            require_external_review=require_external_review,
            expected_model=expected_model,
            expected_tier=resolved_tier,
        )
    # iter078 P1-5: rolling gap 可见性。新落盘顺序（正文先于 rolling）的
    # 良性窗口是「正文已 approved 落盘、rolling 缺该章条目」——下一章 prompt
    # 会丢失该章的承接摘要。只 WARN 不 block、不自动回填（回填需 LLM 调用，
    # 破坏 resume 零调用契约）；操作者可对该章 --force 重写补齐。rolling
    # 一次性读入内存做成员集，不逐章读盘。
    from .chapter_summary import load_rolling_summary

    _rolling_nos: set | None
    try:
        _rolling_data = load_rolling_summary()
        _rolling_nos = {
            int(item.get("chapter_no", 0))
            for lst in (_rolling_data.get("chapters"), _rolling_data.get("compressed_older"))
            for item in (lst or [])
            if isinstance(item, dict)
        }
        if not _rolling_nos:
            # rolling 完全为空（含文件不存在）不启用 gap 检查——手工搭建/
            # 迁移的 workspace 没有 rolling 属正常形态（铁律④ fail-open），
            # 真实长跑从 ch1 起就有条目，检查照常生效。
            _rolling_nos = None
    except Exception:
        _rolling_nos = None  # 读失败不误报 gap

    def _note_rolling_gap(no: int) -> None:
        if _rolling_nos is not None and no not in _rolling_nos:
            warnings.append(f"rolling_summary_gap:{no:02d}")

    def _note_entity_proposal_gap(no: int) -> None:
        if _advance_sidecar_path(drafts_dir, no).exists():
            return
        if proposal_path(no, drafts_dir).exists():
            return
        warnings.append(f"entity_proposal_gap:{no:02d}")

    # 窗口外但承接最关键的一章：resume_from-1（下一章 prompt 直接依赖它的
    # ending_state）。正文在盘才算 gap。
    _prev_no = resume_from - 1
    if _prev_no >= 1 and (drafts_dir / f"chapter_{_prev_no:02d}.md").exists():
        _note_rolling_gap(_prev_no)
        prev_status = chapter_status(
            _prev_no,
            drafts_dir,
            validate_context=False,
            require_start_point=require_start_point,
            require_plan=require_plan,
            require_external_review=require_external_review,
        )
        if prev_status.get("approved") or prev_status.get("caveat_approved"):
            # iter079 收官复核：resume_from-1 是下一章 prompt 最直接依赖的
            # ending_state；它若已 approved/caveat 但 proposal+sidecar 同丢，
            # 当前窗口循环不会再看见它，需在这里同口径 warn。
            _note_entity_proposal_gap(_prev_no)

    if plan:
        for chapter_no in chapter_numbers:
            try:
                item = _chapter_plan_item(plan, chapter_no)
            except ValueError as exc:
                blockers.append(f"chapter_{chapter_no:02d}:plan_item_missing:{exc}")
                continue
            expected = _run_context(
                item,
                chapter_no=chapter_no,
                model=expected_model,
                review_tier=resolved_tier,
            )
            status = chapter_status(
                chapter_no,
                drafts_dir,
                validate_context=True,
                require_start_point=require_start_point,
                require_plan=require_plan,
                require_external_review=require_external_review,
                expected_context=expected,
            )
            if status.get("approved") or status.get("caveat_approved"):
                # iter078 P1-5: 会被 run 跳过（skip_approved/skip_caveat）的章，
                # rolling 缺条目不会被重写自愈——在此透出。
                _note_rolling_gap(chapter_no)
                # iter079 P2 hardening: 正文/meta 已落盘但 entity proposal
                # 尚未生成的 kill 窗口无源补偿；只做可见性 warning，不 block、
                # 不触发 LLM 回填，保持 resume 零调用契约。
                _note_entity_proposal_gap(chapter_no)
            # iter078 技债-1：与 run_write_book 消费同一 classify_disposition
            # 单一真源（allow_existing_blockers 即 run 的 force 同义传入）。
            # 各分支语义原样：
            # - SKIP_CAVEAT = iter077 P0-2 断点A（caveat 放行残迹非 stale，
            #   readiness 与 run 的 skipped_caveat 同口径豁免，仅提示供复查）
            # - SUPPLEMENT = reviewed_existing 补外审路径（不重写、只补审）
            # - STALE_REJECT_REWRITE = iter077 P0-5（同配置中断期拒稿残迹会被
            #   归档+重写，readiness 不再抢先把整本书 block 死）
            disposition = classify_disposition(
                status,
                force=allow_existing_blockers,
                require_external_review=require_external_review,
            )
            if disposition is ChapterDisposition.SKIP_CAVEAT:
                warnings.append(f"chapter_{chapter_no:02d}:caveat_approved_present")
            elif disposition is ChapterDisposition.SUPPLEMENT_EXTERNAL_REVIEW:
                warnings.append(f"chapter_{chapter_no:02d}:external_review_missing")
            elif disposition is ChapterDisposition.STALE_REJECT_REWRITE:
                warnings.append(f"chapter_{chapter_no:02d}:stale_reject_will_rewrite")
            elif disposition is ChapterDisposition.BLOCK:
                failures = status.get("strict_failures") or []
                blockers.append(
                    f"chapter_{chapter_no:02d}:existing_output_not_strict_approved:"
                    f"verdict={status.get('verdict')};needs_review={status.get('needs_review')};"
                    f"strict_failures={','.join(failures)}"
                )
                recommended.append(
                    f"inspect {drafts_dir / f'chapter_{chapter_no:02d}.md'} and rerun write-book with --force if safe"
                )

    # iter047B2 M7: use the same workspace-aware paths the real KB injection uses.
    # _kb_path/_index_path resolve to ROOT in legacy mode; the old code used a
    # CWD-relative Path("."), so this spoiler warning silently checked the wrong
    # tree (and was suppressed) whenever the CWD wasn't the repo root.
    if (
        start_point.get_start_chapter_id()
        and _kb_path().exists()
        and not _index_path().exists()
    ):
        warnings.append(
            "knowledge_index.json 缺失：KB 无法按起点过滤，将回退注入全书原文（可能含起点后剧透）。运行 compress 生成 index。"
        )

    # iter 047c: must-resolve foreshadowing overdue at the resume chapter is a
    # fail-closed blocker. No registry -> overdue_must_resolve returns [] (no-op).
    from . import foreshadowing

    # current = continuation chapters elapsed since the boundary clue
    # (planted at 0): chapters 1..resume_from-1 are written, resume_from
    # not yet — so resume_from-1 chapters have gone by at check time.
    try:
        _fo_current = max(0, resume_from - 1)
        overdue = foreshadowing.overdue_must_resolve(_fo_current)
        boundary_overdue = foreshadowing.boundary_overdue_must_resolve(_fo_current)
    except Exception as exc:
        # iter047B2 H3: a fail-closed gate must never SILENTLY open. If the
        # registry read raises unexpectedly, surface a blocker rather than
        # swallowing it into an empty (passing) result.
        overdue = []
        boundary_overdue = []
        blockers.append(f"foreshadowing_gate_error:{type(exc).__name__}")
        recommended.append(
            "伏笔闸门检查异常（foreshadowing_registry.json 可能损坏）；修复或删除后重试"
        )
    if overdue:
        blockers.append(f"foreshadowing_must_resolve_overdue:{len(overdue)}")
        recommended.append(
            f"回收 {len(overdue)} 个超期的 must-resolve 伏笔后重试，或用 foreshadowing.resolve/gc 调整 registry"
        )
    # iter077 P0-1: source-boundary seeds (planted_chapter<=0) are advisory only —
    # they'd otherwise deterministically block every 14+-chapter continuation at
    # a segment boundary (the pipeline has no automatic resolve path for them).
    if boundary_overdue:
        warnings.append(f"foreshadowing_boundary_overdue:{len(boundary_overdue)}")
        recommended.append(
            f"{len(boundary_overdue)} 个源书遗留伏笔（planted_chapter=0）超期：仅提示不拦截；"
            "可用 foreshadowing.resolve/gc 回收，或手工将其 planted_chapter 设为正数章号以重新武装闸门"
        )

    status = "blocked" if blockers else "warn" if warnings else "ready"
    return {
        "status": status,
        "chapters": total,
        "resume_from": resume_from,
        "next_unapproved_chapter": next_unapproved_chapter,
        "plan_window": plan_window,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "recommended_commands": _dedupe(recommended),
        "primary_blocker": _primary_blocker(_dedupe(blockers)),
    }


def _next_unapproved_chapter(
    *,
    raw_plan: Dict[str, Any],
    plan: Dict[int, Dict[str, Any]],
    drafts_dir: Path,
    resume_from: int,
    require_start_point: bool,
    require_plan: bool,
    require_external_review: bool,
    expected_model: str = "",
    expected_tier: str = "",
) -> int | None:
    numbers: List[int] = []
    for item in raw_plan.get("chapters", []) or []:
        if isinstance(item, dict) and item.get("chapter_no") is not None:
            try:
                numbers.append(int(item["chapter_no"]))
            except (TypeError, ValueError):
                continue
    if not numbers and plan:
        numbers = [int(no) for no in plan.keys()]
    numbers = sorted(set(numbers))
    if not numbers:
        return max(1, int(resume_from))

    latest_approved: int | None = None
    first_unapproved: int | None = None
    for chapter_no in numbers:
        expected: Dict[str, Any] | None = None
        validate_context = False
        if plan:
            try:
                item = _chapter_plan_item(plan, chapter_no)
            except ValueError:
                item = None
            if item:
                expected = _run_context(
                    item,
                    chapter_no=chapter_no,
                    model=expected_model,
                    review_tier=expected_tier,
                )
                validate_context = True
        status = chapter_status(
            chapter_no,
            drafts_dir,
            validate_context=validate_context,
            require_start_point=require_start_point,
            require_plan=require_plan,
            require_external_review=require_external_review,
            expected_context=expected,
        )
        if status.get("approved"):
            latest_approved = chapter_no if latest_approved is None else max(latest_approved, chapter_no)
        elif first_unapproved is None:
            first_unapproved = chapter_no

    if latest_approved is not None:
        candidate = latest_approved + 1
        if candidate <= max(numbers):
            return candidate
        return None
    return first_unapproved or max(1, int(resume_from))


def _primary_blocker(blockers: List[str]) -> Dict[str, str] | None:
    # iter063 Part C: labels/CTA come from the shared readiness_catalog (one
    # source of truth, also feeding web/errors.py and the injected frontend
    # catalog) — was a private duplicate of errors._READINESS.
    if not blockers:
        return None
    raw = blockers[0]
    kind = readiness_catalog.classify(raw)
    fields = readiness_catalog.fields_for(kind)
    return {
        "kind": kind,
        "label": fields["label"],
        "cta_action": fields["cta_action"],
        "cta_label": fields["cta_label"],
        "raw": raw,
    }


def _blocker_kind(blocker: str) -> str:
    # iter063 Part C: thin alias kept for callers/tests; classification logic
    # now lives once in readiness_catalog.classify.
    return readiness_catalog.classify(blocker)


def _load_raw_chapter_plan() -> Dict[str, Any]:
    path = paths.chapter_plan_path() if paths.workspace_name() else Path("outputs/debate/chapter_plan.json")
    # iter059 #4: corrupt plan degrades to {} here (the metadata-failure path
    # keeps the gate closed); the typed ChapterPlanInvalid is raised separately
    # by the schema loader _load_chapter_plan, which readiness catches above.
    data = read_json_optional(path, {})
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
    # iter 051b (F6): the plan-vs-current-start agreement block moved verbatim
    # into start_point.enforce_consistency (codes byte-identical); this
    # function just splices the centralized result into its failure list.
    failures.extend(
        start_point.enforce_consistency(
            require_start_point=require_start_point, plan_data=data
        )
    )

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


def _cross_cycle_seed_feedback(drafts_dir: Path, chapter_no: int) -> str:
    """iter 053b（审查 B3）：在 ``_archive_chapter_artifacts`` 把上一重试周期
    的产物搬走**之前**，收割其评审拒因并用与周期内重写循环同一套分层模板
    （``_review_feedback``）渲染——否则下一周期第一稿对上一周期的 block 拒因
    （052 实跑中 gf_longzu_014/015 这类外审命中正是 053c 的回灌效果探针）
    完全失忆。优先读 reviews/chapter_XX.review.json（完整报告），缺失时退
    meta 的 agent_reviews。Fail-open：没有可收割的产物 → 空串，行为与 053
    前一致（铁律④）。"""
    drafts_dir = Path(drafts_dir)
    review = read_json_optional(
        drafts_dir.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json", None
    )
    # 铁律⑨ B-M4：只投 agent_reviews + rewrite_suggestions，**剥离 lint_issues**
    # ——lint 反馈带上一稿的违规行号（"请按行号回到正文定位"），而新周期第
    # 一稿还不存在，行号指向已归档的尸体，纯误导。
    report: Dict[str, Any] = {}
    if isinstance(review, dict) and review.get("agent_reviews"):
        report = {
            "agent_reviews": review.get("agent_reviews") or [],
            "rewrite_suggestions": review.get("rewrite_suggestions") or [],
        }
    if not report.get("agent_reviews"):
        meta = read_json_optional(drafts_dir / f"chapter_{chapter_no:02d}.meta.json", None)
        if isinstance(meta, dict) and meta.get("agent_reviews"):
            report = {"agent_reviews": meta["agent_reviews"]}
    if not report:
        return ""
    rendered = _review_feedback(report)
    if not rendered.strip():
        return ""
    return (
        "## 上一重试周期的评审拒因（产物已归档；本周期第一稿必须直接规避以下问题）\n"
        + rendered
    )


def _expected_write_model() -> str:
    """iter078 P1-6: 指纹比对用的当前 write 模型（与 writer 的
    ``LLMClient("write").model`` 同源 = ``get_model_config("write")["model"]``）。
    config 读取失败回空串——比对侧「双方非空才比对」自动跳过，readiness
    不为它不拥有的配置问题崩溃。"""
    try:
        from .config import get_model_config

        return str(get_model_config("write").get("model") or "")
    except Exception:
        return ""


def _archive_chapter_artifacts(drafts_dir: Path, chapter_no: int, *, reason: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_dir = ensure_dir(drafts_dir / "snapshots" / f"stale_chapter_{chapter_no:02d}_{stamp}")
    for suffix in (
        ".md",
        ".partial.md",
        ".meta.json",
        ".failure.json",
        # iter077 审查修复：caveat 放行归档的 lint 失败件也随章整体归档——否则
        # force 重写后旧世代审计残片留在 drafts 挂错世代、二次 caveat 时被覆写。
        ".failure.caveat.json",
        ".entity_advances.json",
        ".entity_advance_proposals.json",
        # iter078 P1-4①: advance 处置 sidecar 随章归档——force 重写后新周期
        # 重新处置，不残留旧世代标记（iter077 caveat.json 同款教训）。
        ".advance_applied.json",
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


def _sync_meta_with_external_review(drafts_dir: Path, chapter_no: int) -> Dict[str, Any]:
    """Mirror the external review verdict into writer meta for strict status.

    Writer-owned history fields stay untouched; the standalone review owns the
    final verdict surface once ``require_external_review`` is enabled.
    """

    drafts_dir = Path(drafts_dir)
    meta_path = drafts_dir / f"chapter_{chapter_no:02d}.meta.json"
    review_path = drafts_dir.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json"
    if not meta_path.exists() or not review_path.exists():
        return {}

    meta = read_json_optional(meta_path, {})
    review = read_json_optional(review_path, {})
    if not isinstance(meta, dict) or not isinstance(review, dict):
        return {}

    # iter063 ④: a corrupt meta.json degrades to {} via read_json_optional. If we
    # then merged the verdict into that empty base and wrote it back, we'd clobber
    # writer-owned history (snapshots, attempt log) with a verdict-only stub.
    # Preserve the file on disk instead — the chapter stays at draft_hash_mismatch
    # (fail-safe) until a re-save rebuilds a readable meta.
    if not meta:
        return {}

    verdict = str(review.get("verdict") or "")
    if not verdict:
        return meta

    meta["verdict"] = verdict
    if "needs_human_review" in review:
        meta["needs_human_review"] = bool(review.get("needs_human_review"))
    else:
        meta["needs_human_review"] = verdict != "Approve"
    agent_reviews = review.get("agent_reviews")
    meta["agent_reviews"] = agent_reviews if isinstance(agent_reviews, list) else []
    for key in ("tier", "panel_score", "approve_count", "tier_thresholds"):
        if key in review:
            meta[key] = review[key]
    meta["external_synced_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if verdict == "Approve":
        meta["last_blocking_reasons"] = []

    write_json(meta_path, meta)
    return meta


def _build_review_context(chapter_plan_item: Dict[str, Any] | None) -> Dict[str, str]:
    """Build the source-rich context external reviews need for fidelity checks."""

    kb_path = _kb_path()
    try:
        # iter 047b: external review must also see only start-safe KB, else the
        # reviewer judges fidelity against post-start canon (spoiler + bias).
        knowledge = start_safe_knowledge(kb_path=kb_path, index_path=_index_path())[:6000]
    except OSError:
        knowledge = ""
    try:
        review_source = start_point.format_chapters_before_start_for_anchor(
            k=3, limit_chars=8000
        )
    except Exception:
        review_source = ""
    try:
        scene_matches = (
            source_excerpts.select_for_chapter(chapter_plan_item, k=3)
            if chapter_plan_item
            else []
        )
        scene_excerpts_text = (
            source_excerpts.format_excerpts_for_prompt(scene_matches, limit_chars=8000)
            if scene_matches
            else ""
        )
    except Exception:
        scene_excerpts_text = ""
    return {
        "knowledge": knowledge,
        "source_chapters": review_source,
        "scene_excerpts": scene_excerpts_text,
    }


def _partial_artifact(drafts_dir: Path, chapter_no: int) -> Dict[str, Any] | None:
    partial_path = drafts_dir / f"chapter_{chapter_no:02d}.partial.md"
    if not partial_path.exists():
        return None
    failure_path = drafts_dir / f"chapter_{chapter_no:02d}.failure.json"
    failure = read_json_optional(failure_path, {}) if failure_path.exists() else {}
    if not isinstance(failure, dict):
        failure = {}
    return {
        "chapter": int(chapter_no),
        "stage": failure.get("stage") or "unknown",
        "draft_path": str(partial_path),
        "attempt": failure.get("attempt", 0),
        "last_error": failure.get("last_error", ""),
        "failure_path": str(failure_path) if failure_path.exists() else "",
    }


def _auto_apply_advances(
    chapter_no: int, *, min_confidence: float, compensation: bool = False
) -> Dict[str, Any]:
    drafts_dir = paths.drafts_dir() if paths.workspace_name() else Path("outputs/drafts")
    # iter059 #8: these reads sit BEFORE the try below (which catches
    # ValueError ⊇ JSONDecodeError). A corrupt proposal/entity_graph file —
    # encountered AFTER the chapter was approved and the prose persisted — used
    # to raise an uncaught JSONDecodeError that failed the whole job while the
    # content was already on disk (the "job failed but content on disk" split).
    # Degrade each to {} so auto-advance becomes a clean no-op instead.
    data = read_json_optional(proposal_path(chapter_no, drafts_dir), {})
    proposals = data.get("proposed_advances", data.get("proposals", [])) if isinstance(data, dict) else []
    if not isinstance(proposals, list):
        proposals = []
    plan = _load_raw_chapter_plan()
    graph = read_json_optional(paths.entity_graph_path() if paths.workspace_name() else Path("data/entity_graph.json"), {})
    if compensation:
        # iter078 P1-4①: 补偿路径（resume 对「approved 但 advance 未落」的
        # skip 章重放）——排除目标关系 timeline 已含本章锚点的 proposal，
        # legacy 已应用章收敛为零操作（幂等），真丢失章才补上。
        selected = unapplied_auto_indexes(
            proposals, graph, chapter_no, min_confidence=min_confidence
        )
    else:
        selected = select_auto_indexes(proposals, min_confidence=min_confidence)
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
    # iter065 #6c: opt-in NEW-relationship creation, read from config/agents.yaml
    # (default off → byte-identical legacy skip behavior). Only engaged on the
    # auto_advance path here; manual apply-advance keeps allow_creation=False.
    allow_creation = False
    creation_confidence = 0.85
    try:
        ea_cfg = load_config("agents.yaml").get("entity_advance", {}) or {}
        # iter066 #1: fail-closed config parsing. ``bool("false")`` is True (any
        # non-empty string is truthy), so a hand-edited ``allow_creation:
        # "false"`` (quoted) would silently ENABLE creation — require real bool
        # True. ``float("nan")`` also parses, and ``nan < creation_confidence``
        # is always False, so a bad creation_confidence would open the gate;
        # validate_float's isfinite + [0,1] range guard closes it.
        allow_creation = ea_cfg.get("allow_creation") is True
        cc_err, cc_val = run_params.validate_float(
            ea_cfg.get("creation_confidence", 0.85),
            "creation_confidence",
            0.85,
            minimum=0.0,
            maximum=1.0,
        )
        creation_confidence = 0.85 if cc_err else cc_val
    except Exception:
        allow_creation, creation_confidence = False, 0.85
    try:
        result = apply_advance_proposals(
            chapter_no=chapter_no,
            proposal_indexes=",".join(str(idx) for idx in safe_selected),
            confirm=True,
            auto_apply=False,
            allow_empty=True,
            allow_creation=allow_creation,
            creation_confidence=creation_confidence,
        )
    except (FileNotFoundError, IndexError, ValueError) as exc:
        return {
            "chapter_no": chapter_no,
            "selected": safe_selected,
            "applied_count": 0,
            "auto_apply": True,
            "min_confidence": min_confidence,
            "conflicts": conflicts,
            "no_op_reason": "apply_advance_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    result["auto_apply"] = True
    result["min_confidence"] = min_confidence
    result["conflicts"] = conflicts
    return result


def _advance_sidecar_path(drafts_dir: Path, chapter_no: int) -> Path:
    return drafts_dir / f"chapter_{chapter_no:02d}.advance_applied.json"


def _mark_advance_applied(drafts_dir: Path, chapter_no: int, result: Dict[str, Any]) -> None:
    """iter078 P1-4①: auto-advance 处置完成后落盘 sidecar 标记。

    语义 = 「runner 已对本章完成 auto-advance 处置」（含 no-op / 失败降级
    ——与 run 循环不重试失败 advance 的既有语义一致）；resume 的补偿路径
    只对「sidecar 缺失」的章重放。原子写（write_json）。"""
    write_json(
        _advance_sidecar_path(drafts_dir, chapter_no),
        {
            "chapter": chapter_no,
            "applied_count": result.get("applied_count", 0),
            "selected": result.get("selected", []),
            "no_op_reason": result.get("no_op_reason"),
            "compensated": bool(result.get("compensated")),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _compensate_missing_advance(
    drafts_dir: Path, chapter_no: int, *, min_confidence: float
) -> Dict[str, Any] | None:
    """iter078 P1-4①: skip 章（approved/caveat）的 advance 丢失补偿。

    旧窗口：正文+meta 落盘 → 分诊 → auto-advance 之间被杀 → 章 approved、
    resume 跳过、advance 永久丢失。补偿条件：sidecar 缺失 且 提案文件在盘
    （提案生成需 LLM，缺提案无从补偿——那属于 P1-5 良性缺口，不在此救）。
    重放走 compensation 模式（timeline 锚点去重，legacy 存量章零操作）。
    零 LLM 调用，不破坏 resume 零调用契约。"""
    if _advance_sidecar_path(drafts_dir, chapter_no).exists():
        return None
    if not proposal_path(chapter_no, drafts_dir).exists():
        return None
    result = _auto_apply_advances(
        chapter_no, min_confidence=min_confidence, compensation=True
    )
    result["compensated"] = True
    _mark_advance_applied(drafts_dir, chapter_no, result)
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


def _outline_drift_block_enabled() -> bool:
    """iter073 (codex I): whether SEVERE outline drift escalates to a blocker.

    Default OFF on config error / absence so a missing or corrupt agents.yaml
    can never *introduce* a block (fail-open, 铁律④). Ships enabled in the
    repo config; flip it off there to roll back to warn-only before a run.

    Never blocks in mock mode: the mock rolling summary is a deterministic
    fixture that needn't track the outline, so a severe-drift block would
    false-positive on mock continuations and break the mock pipeline (铁律④).
    The gate is a real-model quality guard; readiness tests patch this fn to
    force it on regardless of mock. ``is_mock_mode`` resolves the effective
    model (matching ``LLMClient.is_mock``), so an unset ``OPENAI_MODEL`` with a
    mock models.yaml default still reads as mock — a raw env check would not.
    """
    if is_mock_mode("write"):
        return False
    try:
        cfg = load_config("agents.yaml").get("outline_drift_block") or {}
    except Exception:
        return False
    return bool(cfg.get("enabled", False)) if isinstance(cfg, dict) else False


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
    # iter076（codex 审查低风险项）：快照路径以 workspace 相对形式外发（消费方仅
    # jobs/前端展示），不再把本机绝对路径写进 job result_summary。
    try:
        result["snapshot_path"] = str(path.relative_to(root))
    except ValueError:
        result["snapshot_path"] = str(path)
    return result
