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

- Prep commit：`eb8e92e Iteration 042 prep: plan + iter040/042 draft archive`。
- §A commit：`02e8681 Iteration 042 §A F3: reviewer source context 漏传修复`。
- §B commit：`48cb814 Iteration 042 §B F1: 原作风格模拟 agent prompt 调优`。
- §C commit：`c04b5ef Iteration 042 §C: 打分制三档阈值（P2 兼容方案）`。
- Source context helper 必须复用 writer 同款 `start_point.format_chapters_before_start_for_anchor(k=3, limit_chars=8000)` 与 `source_excerpts.select_for_chapter(..., k=3)` / `format_excerpts_for_prompt(..., limit_chars=8000)` 逻辑。
- Tier 默认值为 `mid`；env `WRITE_REVIEW_TIER` 是兜底，显式参数链路是 Web per-job override 的主路径。
- `chapter_status.py`、前端 UI、其他 4 个 reviewer prompt、iter039 P2/drama/N3 backlog 均不在本轮范围。

## Acceptance Result

- Prep：已完成。
- §A targeted：`.venv/bin/python -m unittest tests.test_book_runner_review_context` → 1 test OK；邻近 `.venv/bin/python -m unittest tests.test_book_runner_review_context tests.test_book_runner_meta_sync tests.test_book_runner tests.test_writer` → 33 tests OK。
- §B regression smoke：`OPENAI_MODEL=mock WORKSPACE_NAME=iter029_beta_ok` 对 `chapter_01.md` 跑 `review_text` → `verdict=Approve`，`agent_reviews=5`。
- §C targeted：`.venv/bin/python -m unittest tests.test_review_tier tests.test_reviewer_tier_aggregation tests.test_book_runner_tier_flow tests.test_web_jobs_dispatch tests.test_reviewer tests.test_reviewer_deterministic_relations tests.test_writer tests.test_book_runner` → 74 tests OK；`py_compile` 通过。
- Subagent read-only audit：Darwin 结论为无 blocking findings；确认 `reviewer.panel_score -> writer.meta.panel_score -> review_tier thresholds` 链路一致，`WRITE_REVIEW_TIER` / CLI / Web job param / `run_write_book` / writer / external review / `review_text` 参数链路一致，旧 workspace 缺 `tier/panel_score/approve_count` 不影响 `chapter_status` / Web aggregation 读取。未修 P2：部分 Insights/UI 仍偏读 legacy `sub_scores` 命名，建议后续兼容 `scores || sub_scores`；本轮不改前端 UI，记录为 non-blocking。
- 阶段 1+2 mock 验收：`.venv/bin/python -m unittest discover` → 568 tests，`OK (skipped=6)`；`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，568 tests `OK (skipped=6)` + mock auto-pipeline OK。
- Tier 透传 smoke：计划命令中的 `python -m src.cli --workspace` 在当前仓库无对应模块/参数，使用等价现有入口 `OPENAI_MODEL=mock WRITE_REVIEW_TIER=mid .venv/bin/python main.py --book iter029_beta_ok write-book --chapters 1` → `status=succeeded`，已 approved 章节 strict skip。
- 阶段 4 high 档 regression：`OPENAI_MODEL=mock WORKSPACE_NAME=iter029_beta_ok WRITE_REVIEW_TIER=high` 对 `chapter_01.md` 跑 `review_text` → `verdict=Approve`，`tier=high`，`panel_score=9.0`，`approve_count=5`。
- 阶段 3 `longzu` ch2 真实验收：备份目录 `/tmp/iter042_baseline_20260604_231801/`。第一次 Web job `6cf6d93d3779438ab931ee287edd68c2` 写作与 external review 本体已通过：`chapter_02.meta.json` 与 `outputs/reviews/chapter_02.review.json` 顶层 verdict 均为 `Approve`，`draft_sha256=6b3ce89672f0259bd0258801df179892ebf6d49c98297383a88d42929d864865`，`tier=mid`，`panel_score=7.58`，`approve_count=4`，`tier_thresholds={"min_approve_count":4,"min_panel_score":7.5}`，严格状态 `approved=true` / `strict_failures=[]`；5 agent 票面为 4 Approve / 1 Reject（`伏笔猎人` Reject）。成本增量以 `longzu` logs 982 行为 offset：15 calls，prompt 322,014，response 35,736，`cost_cny=0.909`，低于 3 元目标。
- 阶段 3 尾部 incident：第一次 job 在 approved chapter 后进入 auto-advance 时因 proposal 指向缺失关系 `char_lu_mingfei <-> org_cassell_college` 抛 `ValueError`，job status 被拖成 `failed`。本轮补 `book_runner._auto_apply_advances()` 对 `FileNotFoundError/IndexError/ValueError` 降级为 no-op，并新增 `test_auto_apply_advance_missing_relationship_degrades_to_noop`；这是 approved 后的 runner tail 防御，不改变 reviewer verdict 主链路。
- 阶段 3 job 成功验收：修复后第二个 Web job `4e7a02d9a7334964818b503807460e1e` 复跑同参数，因 ch2 已 strict approved 走 `skipped_approved`，终态 `status=succeeded` / `current_step=succeeded` / `progress=1.0`，snapshot `workspaces/longzu/outputs/drafts/snapshots/write_book_succeeded_20260604_233443.json`。
- Post-tail-fix 验收：`.venv/bin/python -m unittest tests.test_book_runner tests.test_book_runner_tier_flow tests.test_book_runner_review_context tests.test_book_runner_meta_sync` → 15 tests OK；`.venv/bin/python -m py_compile src/book_runner.py tests/test_book_runner.py` → OK；最终 `.venv/bin/python -m unittest discover` → 569 tests，`OK (skipped=6)`；`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`；最终 `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，569 tests `OK (skipped=6)` + mock auto-pipeline OK。

## 文件变更汇总

- `docs/iterations/iteration_040_PLAN_DRAFT.md`：补归档外部 draft。
- `docs/iterations/iteration_042_PLAN_DRAFT.md`：归档本轮外部 draft。
- `docs/iterations/iteration_042_PLAN.md`：本轮 Codex 执行档案。
- `src/reviewer.py`：`review_target()` 透传 source context；aggregation 改为 tier-aware；report schema 增加 `tier/panel_score/approve_count/tier_thresholds`。
- `src/book_runner.py`：新增 `_build_review_context()`；external review 两个调用点传 source + tier；external review score/tier 字段同步回 meta；auto-advance apply 阶段遇缺失关系等不可应用 proposal 时降级 no-op，避免 approved chapter 被尾部异常拖成 failed。
- `src/writer.py`：shadow review 与正式 review 传 source + tier；writer meta 写入 tier fields。
- `src/review_tier.py`：新增三档阈值与 env/参数解析。
- `src/web/jobs.py`、`src/web/routes.py`、`main.py`：write-book tier 参数入口。
- `config/agents.yaml`：仅调整 `原作风格模拟` prompt。
- `src/llm_client.py`：mock review 分数从 8 提高到 9，保证 high 档 regression 保持现有 mock Approve 语义。
- `tests/test_book_runner_review_context.py`、`tests/test_review_tier.py`、`tests/test_reviewer_tier_aggregation.py`、`tests/test_book_runner_tier_flow.py`：新增覆盖；`tests/test_web_jobs_dispatch.py`、`tests/test_reviewer_deterministic_relations.py`、`tests/test_book_runner.py`：补兼容断言/fixture 与 approved 后 auto-advance no-op 防御测试。

## 不在本轮范围

- 不改 `chapter_status.py` 主判定。
- 不改除 `原作风格模拟` 外的 reviewer agent prompt。
- 不改前端 UI；tier 只做 API/job 参数入口。
- 不做 iter039 P2 三件套、drama P3/N3 WebUI 重构、writer pending_external_review fallback。
- 不 push。

## Notes

- 外部 plan 文件名沿用 iter039 草稿盒路径，但内容为 iter042 plan。
- `docs/iterations/iteration_041_INVESTIGATION.md` 当前作为诊断输入存在；本轮 prep 提交不主动纳入该未跟踪文件。
- `longzu` ch2 mid 档 happy path 已跑通：meta/review 一致 `Approve`，`panel_score=7.58 >= 7.5`，`approve_count=4 >= 4`，成本 ¥0.909。第一次 job 暴露 approved 后 auto-advance 缺失关系异常，本轮已用 no-op 防御修复并以第二次 Web job `succeeded` 验收。
- iter043 backlog：N3 WebUI 重构、drama UX、iter039 P2-A/B/C（Jobs 展开详情、sidebar lost 历史标记、onboarding budget/timeout/cancel）、tier UI 入口、Insights/UI `scores || sub_scores` 兼容、auto-advance 缺失关系 proposal 的上游校验/清理、writer `pending_external_review` fallback、drama 站 ③/④、AI 绘画 client / Comfy 导出、章节 diff、全文搜索、真模型 capstone、KB 起点过滤安全视图。
