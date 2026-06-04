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

待实施。

## Acceptance Result

待补充。

## 文件变更汇总

待补充。

## 不在本轮范围

- 不动 `writer.py` 内嵌 review 逻辑。
- 不动 `chapter_status.py` 判定。
- 不动 `reviewer.review_target` / `review_text` 契约。
- 不做 P0-B writer pending/external review meta 契约调整。
- 不做 iter039 P2 三件套、drama backlog、章节 diff、全文搜索、KB 起点过滤安全视图。
- 不 push。

## Notes

- 本文件为 Codex 执行单；完整方案仍以外部 plan 文件为准。
