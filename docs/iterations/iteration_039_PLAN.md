# Iteration 039 — WebUI 小说续写真实链路修复

## Context

iter038 把沙箱 `socket.bind` 6 ERROR 清零后，本轮按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 处理 WebUI 真实续写链路的 P0/P1 问题，不重新设计。

用户侧的核心痛点是：running job 被误标 lost；write-book 一章内长时间没有细粒度进度；失败时真实模型已生成 draft 没有 partial artifact；预算只在章节边界止损；blocked job 的真实原因没有在前端露出；partial draft 即使落盘也没有 Web 入口。

本轮保持 mock-only 默认验收，不触碰 `.env`、`data/`、`outputs/`、`小说txt/`，不改 `litellm` / `llm_client.py` 核心调用栈。

## Plan

- P0-A：修复 `src/web/jobs.py::recent_jobs()` lost 判定，只有 persisted pending/running 且内存里查不到时才标 lost。
- P0-C：`src/writer.py::write_chapters()` 新增 `progress_cb`，按 `write-attempt` / `review-attempt` / `review-done-attempt` / `polish` / `finalize` 上报章内进度；`src/book_runner.py` 映射到全局 progress。
- P0-B：writer 异常时把最新非空 draft 落到 `chapter_NN.partial.md` + `chapter_NN.failure.json`；book_runner 捕获失败并在 result/result_summary 中透传 `partial`。
- P0-D：新增 `BudgetExceeded` 与章内 `budget_check_cb`，在 write/review 后及时检查预算，超预算走 `budget_exceeded` snapshot 并复用 partial artifact。
- P1-A：Web 前端新增 `jobBlockedDetail()` / `jobFailureLine()`，sidebar、pollJob、jobs 页展示 `result_summary.first_blocked`。
- P1-B：新增 partial draft API 入口，pollJob terminal 分支展示 partial 链接，chapters 页识别 `.partial.md` 并打 `partial / failure` 标签。
- P2-A/B/C：不做，转 iter040 backlog。

## Acceptance

- 每个 P0 子项后跑 `.venv/bin/python -m unittest discover`，保持 `OK (skipped=6)`。
- P0 全部完成后跑 mock Web 链路：`OPENAI_MODEL=mock WRITER_FORCE_FAIL=1` 触发 write-book 失败，验证 `chapter_NN.partial.md` + `chapter_NN.failure.json` 落盘；另用 plan-chapters blocked 验证前端 blocked reason 可见。
- 完成后跑基线：`.venv/bin/python -m unittest discover`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`OPENAI_MODEL=mock .venv/bin/python main.py preflight`。
- 真实模型验收（龙族前 3-5 章起点，plan-chapters + write-book chapter=1 至少 1 章 approved）需要用户明确授权，本轮不主动执行。
- 收官前执行至少 1 个 subagent 只读审核，并把结论写入本文件。

## Implementation Notes

- P0-A 已提交：`cd42972 Iteration 039 §A P0-A: recent_jobs lost 判定修复`。新增 `tests/test_web_jobs_recent.py` 覆盖 live running 与 process restart lost 两路。
- P0-C 已提交：`eccb5bc Iteration 039 §B P0-C: write-book 细粒度 progress`。新增 `tests/test_writer_progress.py`，验证 step 序列与 fraction 单调递增。
- P0-B 已提交：`b1eaa62 Iteration 039 §C P0-B: 失败 partial artifact 落盘`。新增 `tests/test_book_runner_partial.py`，覆盖 write exception partial 落盘与 `_summarize_result()` partial 透传；`chapter_status` 使用精确 `chapter_NN.md`，不会把 `.partial.md` 判成 approved。
- P0-D 已提交：`6499489 Iteration 039 §D P0-D: 章内预算止损`。`BudgetExceeded` 由 book_runner closure 抛出，writer 在 write/review 后检查；最终收口时补充 polish 后与外层 `review_target()` 后也立即检查同一预算闭包。
- P1-A/P1-B 在最终提交收口：`src/web/routes.py` 支持 `variant=partial`，`/drafts` 列出 final + partial 两种 variant；`src/web/static.py` 展示 blocked reason、terminal partial 链接、chapters 页 partial/failure row。
- `WRITER_FORCE_FAIL=1` 的 mock-only hook 从“注入短章 lint failure”调整为“在 write 后抛出携带 `partial_draft` 的异常”，用于无 token 成本地验证 partial artifact 路径；仍需同时满足 `OPENAI_MODEL=mock`。
- P0-C 补丁：真实 Web 验收暴露外层章节 retry 会让 progress 从 `finalize` 回到 `write-attempt-*`，本补丁在 `book_runner` 章节 progress 闭包内增加 `_last_progress` 单调钳位，并让 retry 子 step 增加 `retry-K/` 前缀。

## Acceptance Result

- P0-A 后：`.venv/bin/python -m unittest discover` → 551 tests，`OK (skipped=6)`。
- P0-C 后：`.venv/bin/python -m unittest discover` → 552 tests，`OK (skipped=6)`。
- P0-B 后：`.venv/bin/python -m unittest discover` → 553 tests，`OK (skipped=6)`。
- P0-D 后：`.venv/bin/python -m unittest discover` → 554 tests，`OK (skipped=6)`。
- P1 收口前 targeted：`.venv/bin/python -m py_compile src/web/routes.py src/web/static.py` → OK；`.venv/bin/python -m unittest tests.test_web_routes_get tests.test_web_jobs_dispatch tests.test_book_runner_partial` → 74 tests OK；`node --check /private/tmp/iter039_dashboard.js` → OK。
- 最终 full：`.venv/bin/python -m unittest discover` → 557 tests，`OK (skipped=6)`；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，557 tests `OK (skipped=6)` + mock auto-pipeline OK；`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`，FATAL none，WARN none；`node --check /dev/stdin` for `JS_DASHBOARD` → OK。
- Mock Web smoke：`OPENAI_MODEL=mock WRITER_FORCE_FAIL=1 .venv/bin/python main.py web --host 127.0.0.1 --port 8789`；`write-book` on `iter039smoke` 返回 `status=failed` 且 `result_summary.partial` 存在；`workspaces/iter039smoke/outputs/drafts/chapter_01.partial.md` 与 `chapter_01.failure.json` 落盘；`/api/workspace/iter039smoke/draft/1?variant=partial` 返回 200。
- Blocked reason smoke：`plan-chapters` on `iter039blocked` 返回 `first_blocked.reason=outline_missing`；Browser 验证 `/w/iter039blocked/jobs` 显示 `outline_missing · outline not found; run \`python main.py debate\` first`，截图 `/private/tmp/iter039_jobs_outline_missing.png`；`/w/iter039smoke/chapters` 显示 partial/failure row，截图 `/private/tmp/iter039_chapters_partial.png`。
- 真实模型 Web 验收（用户授权后执行）：`longzu` 先从前端重跑 `plan-chapters --chapters 3 --force` 成功；随后 `write-book chapters=1 resume_from=2 budget_cny=10 max_retries=2` 终态为 `blocked`，`first_blocked.reason=retry_exhausted`，前端 continue/jobs/chapters/chapter/reviews 页面均可读展示，未误标 lost，成本增量约 ¥4.6467，未超过 ¥10。该验收暴露 P0-C progress 倒退问题，本补丁已修；happy path approved 未通过。
- P0-C 补丁 targeted：`.venv/bin/python -m unittest tests.test_book_runner_retry_progress` → 1 test OK；`.venv/bin/python -m unittest tests.test_book_runner tests.test_book_runner_partial tests.test_writer_progress` → 15 tests OK。
- P0-C 补丁 full：`.venv/bin/python -m unittest discover` → 558 tests，`OK (skipped=6)`。
- Subagent 只读审核：Gibbs 结论为无 blocking findings、无 protected scope 违规。审核提出 3 点已修复：polish 路径预算检查缺口、write-book 返回式失败 summary 未透传 error、成功 final draft 后旧 `.partial.md` 孤儿文件会继续显示为 failure。修复后补跑 `.venv/bin/python -m unittest tests.test_writer_progress tests.test_book_runner_partial tests.test_web_routes_get tests.test_web_jobs_dispatch` → 76 tests OK；`node --check /dev/stdin` for `JS_DASHBOARD` → OK。

## 文件变更汇总

- `src/web/jobs.py`：recent_jobs lost 判定修复；write-book result summary 透传 `partial`。
- `src/writer.py`：新增 `progress_cb` / `budget_check_cb`；异常 partial 落盘；mock-only `WRITER_FORCE_FAIL` 改为 partial path 触发器。
- `src/book_runner.py`：新增 `BudgetExceeded`；章节内 progress 映射；write/review 失败与预算超限返回 snapshot；stale archive 包含 `.partial.md`。
- `src/web/routes.py`：partial draft variant API；draft list 支持 final/partial variant。
- `src/web/static.py`：blocked/failure note helper；pollJob/jobs/sidebar 展示 blocked reason；terminal partial 链接；chapters 页 partial/failure row。
- `tests/test_web_jobs_recent.py`、`tests/test_writer_progress.py`、`tests/test_book_runner_partial.py`、`tests/test_web_routes_get.py`：新增/扩展 P0/P1 覆盖。
- `tests/test_book_runner_retry_progress.py`：覆盖外层章节 retry 下 progress 单调不减与 `retry-K/` step 前缀。
- `README.md`、`AGENTS.md`、`docs/AGENT_HANDOFF.md`、`docs/iterations/README.md`、本文件：同步 iter039 状态与交接。

## 不在本轮范围

- P2-A：Jobs 页 80 字截断改成可展开详情，trace_id badge 优化。
- P2-B：sidebar 区分历史 lost 与当前状态，lost 行加历史标记与视觉降权。
- P2-C：onboarding 增加 budget/timeout/cancel，包括 job cancel POST 路由与 greenfield budget 输入。
- drama 模块 P3 backlog、站 ③ 分镜、站 ④ 角色、AI 绘画 client、Comfy 导出、drama_reviewer。
- onboarding 表单大改。
- `litellm` / `llm_client.py` 核心调用栈改造。

## Notes

- P0 提交顺序与计划依赖一致，但提交标签沿用 `§A/§B/§C/§D`：其中 `§B` 对应 P0-C，`§C` 对应 P0-B。
- 由于 mock Web smoke 需要本机 socket bind，Web server 启动使用了已获批准的提权路径；测试套件自身仍在普通沙箱内保持 `OK (skipped=6)`。
- `workspaces/iter039smoke` 与 `workspaces/iter039blocked` 为 ignored smoke workspace，不纳入 git。
- iter040 backlog 应优先考虑 P2-A/B/C、章节 diff、全文搜索、真模型 capstone、KB 起点过滤安全视图。
- iter040 backlog 新增真实验收发现：`chapter_02.meta.json` 顶层 `verdict=Reject`，但 `outputs/reviews/chapter_02.review.json` 顶层 `verdict=Approve`，最终 strict `chapter_status` 仍判 blocked。证据 job `a9fe3502ed0e438a82ada58ea78b8982`；证据路径 `workspaces/longzu/outputs/drafts/chapter_02.meta.json` + `workspaces/longzu/outputs/reviews/chapter_02.review.json`。
