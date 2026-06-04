# Iteration 040 — meta/review verdict 同步 + happy path 跑通

## Context

iter039 真实 Web 验收中，`longzu` ch2 的 write-book 链路功能已通过，但最终 job 仍 blocked：`chapter_02.meta.json` 为 `Reject`，而外部 `outputs/reviews/chapter_02.review.json` 为 `Approve`。严格 `chapter_status(require_external_review=True)` 同时看 meta 与 external review，meta 未同步导致 approved 判定失败。

本轮严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter040 plan 执行，只做 P0-A：在 `book_runner` 外部 review 完成后，把 external review verdict 强制同步回 writer meta，使 external review 成为 require_external_review 模式下最终 verdict 的 source of truth。

## Plan

- Prep：归档已有 `docs/iterations/iteration_039_PLAN_DRAFT.md`，新增本 iter040 执行计划文件并单独提交。
- P0-A：在 `src/book_runner.py` 新增 `_sync_meta_with_external_review(drafts_dir, chapter_no)`，同步 `verdict` / `needs_human_review` / `agent_reviews` / `external_synced_at`；external Approve 时清空 `last_blocking_reasons`。
- 在 `reviewed_existing` 路径和每章 `review_target()` 后调用 sync helper。
- 新增 `tests/test_book_runner_meta_sync.py`，覆盖 Approve 正向同步、Reject 反向同步、`chapter_status(validate_context=True, require_external_review=True)` 兼容性。
- 跑单测、mock preflight、`scripts/verify.sh`。
- 按用户授权预算跑 `longzu` ch2 真实模型 happy path：备份旧 ch2 产物，删除 ch2 draft/meta/partial/failure/review，通过 Web write-book 跑 chapter=2 budget=10，并记录 verdict / 成本 / job_id。
- 收官前做至少 1 个 subagent 只读审核，并把结论写入本文件。

## Acceptance

- `.venv/bin/python -m unittest discover` → 期望 `OK (skipped=6)`，约 559 tests。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → 期望 `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- 真实模型 `longzu` ch2：目标 job `succeeded`，`chapter_02.meta.json` 与 `chapter_02.review.json` verdict 均为 `Approve`，成本 < 5 元。
- 若真实跑仍 blocked：若 meta/review 一致 `Reject`，判定为 LLM 漂移内容问题并记录 incident；若仍不一致，继续修 P0-A。

## Implementation Notes

- Prep commit：`42aa5a6 Iteration 040 prep: plan + iter039 draft archive`，归档 `iteration_039_PLAN_DRAFT.md` 并新增本文件。
- P0-A commit：`eaad0ce Iteration 040 §A P0-A: sync meta with external review`。
- `src/book_runner.py` 新增 `_sync_meta_with_external_review(drafts_dir, chapter_no)`：
  - 读取 `drafts/chapter_NN.meta.json` 与 `reviews/chapter_NN.review.json`。
  - 只覆盖 external review 拥有的 `verdict` / `needs_human_review` / `agent_reviews` / `external_synced_at`。
  - external review 未给 `needs_human_review` 时，`Approve -> False`，其他 verdict -> True。
  - external `Approve` 时清空 `last_blocking_reasons`。
  - 保留 writer 历史字段：`run_context` / `draft_sha256` / `polish_*` / `lint_blocked_reviews` / `chinese_char_count` / `rewrite_count` 等。
- 调用点：
  - `reviewed_existing` 路径在 `review_target()` 后立即 sync，再重新算 `chapter_status()`。
  - 每章新写路径在 `review_target()` 后先 sync，再 `budget_check_cb()`，最后重新算 `chapter_status()`。
- 新增 `tests/test_book_runner_meta_sync.py`，用 1 个 unittest 方法 + subTest 覆盖正向 Approve、反向 Reject、strict `chapter_status(validate_context=True, require_external_review=True)` 兼容性。
- Subagent 审核 follow-up：Faraday 指出 normal write path 若 external review 后 budget check 立刻超限，会跳过 sync。已把 sync 调到 post-review budget check 前，并在同一 unittest 方法里新增 subTest 覆盖“review 写完后预算超限也已同步 meta”。

## Acceptance Result

- Targeted：`.venv/bin/python -m unittest tests.test_book_runner_meta_sync` → 1 test OK。
- Targeted：`.venv/bin/python -m unittest tests.test_chapter_status tests.test_book_runner tests.test_book_runner_retry_progress` → 17 tests OK。
- Audit follow-up targeted：`.venv/bin/python -m unittest tests.test_book_runner_meta_sync` → 1 test OK；`.venv/bin/python -m unittest tests.test_book_runner tests.test_book_runner_partial tests.test_book_runner_retry_progress tests.test_write_book_replan_budget` → 18 tests OK。
- 最终 full：`.venv/bin/python -m unittest discover` → 559 tests，`OK (skipped=6)`。
- 最终 preflight：`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`，FATAL none，WARN none。
- 最终 verify：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，559 tests `OK (skipped=6)` + mock auto-pipeline OK。
- 阶段 3 准备：备份原 ch2 产物到 `/tmp/iter040_baseline_20260604_194612/`，删除 `chapter_02.md` / `chapter_02.meta.json` / `chapter_02.partial.md` / `chapter_02.failure.json` / `chapter_02.review.json`；保留 `chapter_02.entity_advance_proposals.json`（不在 plan 删除清单）。
- 阶段 3 Web run：提权启动 `http://127.0.0.1:8790`，POST `/api/workspace/longzu/run`，payload `write-book chapters=1 resume_from=2 budget_cny=10 max_retries=2 require_external_review=true`，job_id `d526d330267648869006869de5a15872`。
- 阶段 3 结果：job 终态 `blocked`，`first_blocked.reason=retry_exhausted`，snapshot `workspaces/longzu/outputs/drafts/snapshots/write_book_blocked_20260604_210821.json`。
- 阶段 3 verdict：最终 `chapter_02.meta.json` verdict=`Reject` / `needs_human_review=true`；`outputs/reviews/chapter_02.review.json` verdict=`Reject`；两者 `draft_sha256=59e0594217704bc3ae093c7759078405c0ea486f265327acb4a38df982e80862` 一致；meta 写入 `external_synced_at=2026-06-04T13:08:21+00:00`。
- 阶段 3 strict status：`chapter_status(validate_context=True, require_start_point=True, require_plan=True, require_external_review=True)` 返回 `approved=false`，`strict_failures=["external_review_reject"]`。这证明本轮 sync 生效，blocked 原因从 iter039 的 meta/review 不一致收敛为 external review 自身 Reject。
- 阶段 3 cost：以 run 前 `longzu` `llm_calls.jsonl` 899 行为 offset，`WORKSPACE_NAME=longzu estimate_cost_since(899)` → 83 calls，prompt 1,731,936 tokens，response 227,680 tokens，`cost_cny=5.1701`。低于用户授权预算 10 元，高于 happy-path 目标 5 元。
- Incident note：最终 external review 票面为 4 Approve / 1 Reject，但 reviewer fail-closed 规则（任一 substantive Reject -> overall Reject）使 external verdict=Reject；top rule_ids 包括 `tone_balance`、`norma_authority_consistency`、`protagonist_agency`、`mystery_pacing`、`worldbuilding_logic`、`character_fidelity` 等。按 plan 判定为内容质量/LLM 漂移 incident，不继续扩大 P0-A 范围。
- Subagent 只读审核：Faraday 结论为无 blocking findings；确认 helper 正确同步 `verdict` / `needs_human_review` / `agent_reviews` / `external_synced_at`，并保留 writer-owned meta 字段；确认核心 P0-A 测试覆盖符合 plan。审核提出 3 个 non-blocking risks，其中 budget check 在 sync 前抛出的边角风险已修并补测试；历史已有 external review mismatch 不自动自愈、Approve 时清空 `last_blocking_reasons` 属设计取舍，记录为未修风险。

## 文件变更汇总

- `src/book_runner.py`：新增 external review -> meta sync helper；两处 `review_target()` 后调用；audit follow-up 调整 normal write path 为先 sync 后 post-review budget check。
- `tests/test_book_runner_meta_sync.py`：新增正向、反向、strict status 兼容性覆盖；补 budget_exceeded-after-review 仍 sync 的 subTest。
- `docs/iterations/iteration_039_PLAN_DRAFT.md`：归档 iter039 草稿盒计划。
- `docs/iterations/iteration_040_PLAN.md`、`docs/iterations/README.md`、`README.md`、`AGENTS.md`、`docs/AGENT_HANDOFF.md`：同步 iter040 状态与真实验收结果。

## 不在本轮范围

- 不动 `writer.py` 内嵌 review 逻辑。
- 不动 `chapter_status.py` 判定。
- 不动 `reviewer.review_target` / `review_text` 契约。
- 不做 P0-B writer pending/external review meta 契约调整。
- 不做 iter039 P2 三件套、drama backlog、章节 diff、全文搜索、KB 起点过滤安全视图。
- 不 push。

## Notes

- 本文件为 Codex 执行单；完整方案仍以外部 plan 文件为准。
- P0-A 目标已完成：external review 成为最终 verdict source of truth，并可观察地回写 meta。
- Happy path approved 未达成；本次不再追进 writer/reviewer/prompt，因为 plan 明确一致 Reject 属于内容质量 incident，可收官记录。
- iter041 可选：P0-B writer pending_external_review 保险、龙族 ch2 内容质量 incident（reviewer fail-closed 阈值 / prompt 过度揭谜 / 主角能动性）、iter039 P2-A/B/C。
