# Iteration 042 — happy path 跑通 + 打分制三档（兼容版）

## Context

iter040 已修复 external review verdict 回写 meta 的同步问题，但 `longzu` ch2 真实复跑仍一致 `Reject`。iter041 诊断指出优先根因是 external `review_target()` 漏传 source context，导致 `原作风格模拟` 在缺少原文对照时以 fail-closed veto 卡住 4/5 Approve 的章节；同时现有聚合规则没有开发期节流档位。本轮严格按外部 plan `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter042 方案执行：F3 + F1 + N1/N2，目标是让 mid 档真实 happy path 跑通。

## Plan

- Prep：归档外部 draft 到 `iteration_040_PLAN_DRAFT.md` 与 `iteration_042_PLAN_DRAFT.md`，新增本执行档案并单独提交。
- §A F3：`reviewer.review_target()` 扩展 source context 参数；`book_runner` 抽 `_build_review_context()`，两处 external review 调用与 `writer.py` shadow review 均传入 `knowledge/source_chapters/scene_excerpts`。
- §B F1：只调整 `原作风格模拟` reviewer prompt，要求 source_chapters 存在时先对照原文；风格硬伤才 Reject，密度/留白/台词端正等主观项降级为 Approve + major issue。
- §C N1/N2：新增 `review_tier` 三档阈值；review aggregation 改为 `approve_count + panel_score` 组合判定；review report 与 writer meta 写入 `tier/panel_score/approve_count/tier_thresholds`；book_runner/web job 支持 tier 参数。
- §C 后、真实验收前：启动 1 个 read-only subagent 审核 score/tier 链路和历史兼容性，结论写入本文件。
- 阶段 1+2：跑 full unittest、mock preflight、verify、mock write-book tier 透传 smoke、high 档 regression。
- 阶段 3：用户已授权预算 < 5 元，备份并清理 `longzu` ch2 指定产物，通过 Web write-book 跑 chapter 2 `tier=mid budget=10`，记录 verdict、成本、job_id、tier、panel_score、approve_count。

## Acceptance

- `.venv/bin/python -m unittest discover` → `OK (skipped=6)`，约 563 tests。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- `OPENAI_MODEL=mock WRITE_REVIEW_TIER=mid .venv/bin/python -m src.cli write-book --chapters 1 --workspace iter029_beta_ok` → tier 透传成功。
- `iter029_beta_ok` approved 章节在 `WRITE_REVIEW_TIER=high` mock review 下仍 `Approve`。
- 真实 `longzu` ch2 mid 档目标：job `succeeded`；meta/review verdict 均 `Approve`；meta 含 `tier=mid`、`panel_score >= 7.5`、`approve_count >= 4`；成本 < 3 元。
- 若 mid 仍 Reject：`panel_score >= 7.5` 但 `approve_count=3` 记录 incident 后允许收官；`panel_score < 7.5` 转 iter043 调查 writer 质量。

## Implementation Notes

- Prep commit：pending。
- §A / §B / §C commits：pending。
- Source context helper 必须复用 writer 同款 `start_point.format_chapters_before_start_for_anchor(k=3, limit_chars=8000)` 与 `source_excerpts.select_for_chapter(..., k=3)` / `format_excerpts_for_prompt(..., limit_chars=8000)` 逻辑。
- Tier 默认值为 `mid`；env `WRITE_REVIEW_TIER` 是兜底，显式参数链路是 Web per-job override 的主路径。
- `chapter_status.py`、前端 UI、其他 4 个 reviewer prompt、iter039 P2/drama/N3 backlog 均不在本轮范围。

## Acceptance Result

- Prep：pending。
- §A targeted/full：pending。
- §B regression smoke：pending。
- §C targeted/full：pending。
- Subagent read-only audit：pending。
- 阶段 1+2 mock 验收：pending。
- 阶段 3 `longzu` ch2 真实验收：pending。
- 阶段 4 high 档 regression：pending。

## 文件变更汇总

- `docs/iterations/iteration_040_PLAN_DRAFT.md`：补归档外部 draft。
- `docs/iterations/iteration_042_PLAN_DRAFT.md`：归档本轮外部 draft。
- `docs/iterations/iteration_042_PLAN.md`：本轮 Codex 执行档案。
- 代码与测试变更待后续提交记录。

## 不在本轮范围

- 不改 `chapter_status.py` 主判定。
- 不改除 `原作风格模拟` 外的 reviewer agent prompt。
- 不改前端 UI；tier 只做 API/job 参数入口。
- 不做 iter039 P2 三件套、drama P3/N3 WebUI 重构、writer pending_external_review fallback。
- 不 push。

## Notes

- 外部 plan 文件名沿用 iter039 草稿盒路径，但内容为 iter042 plan。
- `docs/iterations/iteration_041_INVESTIGATION.md` 当前作为诊断输入存在；本轮 prep 提交不主动纳入该未跟踪文件。
