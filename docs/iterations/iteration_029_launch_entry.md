# Iteration 029 - Local Beta Launch Entry

## Context

iter 028 已把生产写作入口收敛到 Python `write-book` runner，但用户侧仍缺一个可上线的本地 Beta 起点：在真正写作前明确告诉用户能不能写、为什么不能写、下一步该跑什么命令。本轮不跑真模型，不改 `.env`，不删除旧产物，目标是把“继续写书”从工程链路变成单用户本地产品入口。

## Plan

1. 将 `scripts/write_book.sh` 降级为薄 wrapper，只负责兼容参数并委托 `python3 main.py write-book`。
2. 在 `src/book_runner.py` 内补齐生产语义：`--max-retries`、`--budget-cny`、`--replan-every`、`--min-confidence`、`--no-auto-advance`。
3. 新增 `python3 main.py write-readiness --chapters N [--resume-from M]`，输出 ready / warn / blocked JSON。
4. Web dashboard 增加“继续写书”主操作区，展示 readiness、阻塞原因和推荐命令，启动同一套 `write-book` runner。
5. 更新测试、README SOP、handoff 与 iteration 索引。

## Acceptance

- 旧缺指纹 `chapter_plan.json` 会让 `write-readiness` 和 `write-book` blocked。
- 指纹完整的新 plan readiness 返回 ready。
- `scripts/write_book.sh` 不再包含 raw `main.py write` / `review-chapter` / `chapter-status` 生产循环。
- retry 失败进入下一轮前归档旧 draft/meta/review 并保留 blocked snapshot。
- budget ceiling 返回 `budget_exceeded` / CLI exit 3，不标 succeeded。
- Web `write-book` 对 Reject / needs_human_review / stale review 返回 blocked，并向用户展示下一步命令。

## Implementation Notes

- `check_write_readiness()` 统一检查 start point、plan 存在性、plan/start/item 指纹、目标章节 plan item、preflight fatal、既有非 strict-approved draft/review、KB 起点过滤 WARN，并返回 workspace-aware `recommended_commands`。
- `run_write_book()` 先消费 readiness；blocked 时抛 `BookRunBlocked`，CLI / Web job 都显示原因。`force=True` 只跳过既有旧稿阻塞，不跳过 start/plan/preflight 硬门。
- retry 清理从 shell 迁入 runner：失败尝试会通过 `_archive_chapter_artifacts()` 归档 chapter `.md/.meta/.failure/.entity_advances` 和 external review，再 `prune_from_chapter()` 回滚 rolling summary。
- budget 使用 `estimate_cost_since()` 计算本次 run 的累计成本，超限返回 `status="budget_exceeded"` 并落 snapshot。
- auto-advance 在 runner 内先用 `validate_proposals_against_plan()` 过滤高风险冲突提案，再应用非冲突且达 `min_confidence` 的 proposal。
- replan append 在 runner 内按本次 run 的 `offset % --replan-every K` 触发；readiness 只要求首个 replan window 的 plan 完整，append 成功后 reload plan，append 失败返回 blocked snapshot。
- Web dashboard 新增 readiness endpoint 与“继续写书”表单；`draft-once-dev` 保留在 step whitelist，但不展示在普通 dashboard 主操作区。

## Acceptance Result

- Targeted tests: `PYTHONPYCACHEPREFIX="$PWD/.pycache" <bundled-python> -m unittest tests.test_book_runner tests.test_write_book_script tests.test_write_book_replan_budget tests.test_smoke_scripts tests.test_web_routes_get tests.test_web_jobs_dispatch` → 56 OK。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock <bundled-python> -m py_compile main.py src/*.py src/web/*.py tests/*.py` → OK。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock <bundled-python> -m unittest discover -s tests` → 412 OK（普通沙箱 5 个 Web socket bind 测试 PermissionError；提权后 OK）。
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` → OK，412 tests OK + mock auto-pipeline OK（同样需 socket 权限）。
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 main.py preflight` → PREFLIGHT ok，FATAL none，WARN none。
- 临时 workspace `iter029_beta_tmp`：`write-readiness --chapters 1` 在缺 start/plan 时返回 `blocked`，blockers 为 `start_point_missing` + `chapter_plan_missing`。
- 临时 workspace `iter029_beta_ok`：mock 生成 plan 后，strict-approved 本地 draft/review 下 `write-readiness` 返回 `warn`（仅 KB 起点过滤提示，无 blockers），`write-book --chapters 1` 返回 `succeeded` / `skipped_approved`。

## 文件变更汇总

| File | Change |
|------|--------|
| `src/book_runner.py` | readiness JSON、统一 retry/budget/replan/auto-advance 生产语义 |
| `main.py` | 新增 `write-readiness` CLI；扩展 `write-book` 参数与 budget exit 3 |
| `scripts/write_book.sh` | 改为薄 wrapper，兼容旧参数并委托 Python runner |
| `src/web/jobs.py` | Web `write-book` 透传 runner 参数，识别 `budget_exceeded` |
| `src/web/routes.py` | 新增 `/api/workspace/<name>/readiness` |
| `src/web/templates.py`, `src/web/static.py` | dashboard 增加“继续写书”入口、readiness 展示、job polling |
| `tests/*write_book*`, `tests/test_book_runner.py`, `tests/test_web_routes_get.py` | Iter029 runner / wrapper / Web regression coverage |
| `README.md`, `docs/AGENT_HANDOFF.md`, `docs/iterations/README.md` | SOP 与交接状态更新 |

## 不在本轮范围

- 不跑 `real_smoke.sh` / `debate_smoke.sh` / `write_smoke.sh`，不启动真模型长跑。
- 不实现完整 `knowledge_for_start_point()`；KB 起点过滤继续作为 readiness / preflight warning。
- 不做 WebUI 美化、在线编辑器、图表或多人权限。
- 不删除旧产物；既有旧稿需要用户检查或显式 `--force` 后由 runner 归档。

## Notes

- 下一次真模型长跑建议入口：`write-readiness → plan-chapters --force --require-start-point → write-book`。
- 产品排序上，本轮优先本地单用户 Beta 的“可靠继续写书按钮”；后续再排真模型 capstone、KB 安全视图、entity timeline schema 和更完整 Web UI。
