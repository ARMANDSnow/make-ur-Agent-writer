# Iteration 044 — 收尾轮（D-5/D-7/D-8 + 文档刷新）

## Context

iter043 §B 已收完 WebUI UX 重构 Bundle 1+2（D-1/D-2/D-3/D-4/D-6）：readiness 主 CTA、jobs drawer、type-aware IA、write-book preset/tier、drama shell 与过期 Web 文案均已落地。剩余历史 UX 长尾集中在 Bundle 3：

- D-5 onboarding critical path：wizard 上传后缺少预算、超时、extract limit、mock/real 提示与真 cancel。
- D-7 移动响应式：sidebar 在移动端硬隐藏，topbar/table 密度不足。
- D-8 UI debt：Insights subscore 仍有 inline style，且需兼容 iter042 schema 演进的 `scores || sub_scores`。
- 文档刷新：AGENTS/README/HANDOFF 仍停在 iter042/043 候选语义，SOP 实时状态需要对齐 iter044。

本轮严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 执行；该外部草稿已归档为 `docs/iterations/iteration_044_PLAN_DRAFT.md`。

## Plan

1. Prep：归档外部草稿，创建本 PLAN，单独提交。
2. §A D-5：后端协作式 cancel/timeout、cancel API 路由、wizard 高级选项与 panel-progress CTA/cancel。
3. §B D-7：移动端 sidebar drawer/hamburger/topbar 折叠与 jobs/chapters/reviews 表格响应式。
4. §C D-8：subscore inline style 改 CSS class，Insights `scores || sub_scores` 兼容；`_workspace_html_guard` 仅明显划算时做，否则记录 iter045 backlog。
5. §D 文档刷新：AGENTS.md、README.md、docs/AGENT_HANDOFF.md、docs/iterations/README.md 对齐 iter044。
6. 验收：全量 unittest、mock preflight、verify、移动 + cancel 截图回归、文档 grep、subagent 只读审核。
7. Final：追加实施笔记、截图回归与 subagent 结论，最终收尾 commit；不 push。

## Acceptance

- `.venv/bin/python -m unittest discover` → `OK (skipped=6)`，期望约 582 tests。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- Chrome DevTools / browser 回归：iPhone 13 + iPad 各跑 B/C/D/E journey，截图归档到 `/tmp/iter044_mobile_screenshots_<ts>/`。
- Mock cancel 流程：wizard 上传 mock workspace → 进度页点 cancel → aborted 状态 + CTA 组截图。
- 文档 grep：`rg "iter 04[0-2].*下一步|iter 043.*下一步" AGENTS.md README.md docs/` → 0 命中；`rg "TODO|FIXME" AGENTS.md README.md` 人工确认无过期 todo。
- 收官前至少 1 个 read-only subagent 审核 cancel 并发/timeout、移动 drawer、subscore class、文档一致性、旧 workspace/schema 兼容；结论写回本 PLAN。
- 全程不跑真实模型，不改 `.env`、`data/`、`outputs/`、`小说txt/`，不 push。

## Implementation Notes

- Prep commit：待记录。
- §A.1 commit：待记录。
- §A.2 commit：待记录。
- §A.3 commit：待记录。
- §B.1 commit：待记录。
- §B.2 commit：待记录。
- §C.1 commit：待记录。
- §C.2 commit：待记录。
- §D commit：待记录。
- Final commit：待记录。

## Acceptance Result

待实施后填写。

## 文件变更汇总

计划变更：

- `docs/iterations/iteration_044_PLAN_DRAFT.md`：归档外部 iter044 草稿。
- `docs/iterations/iteration_044_PLAN.md`：本轮执行档案。

预期实施变更：

- `src/web/jobs.py`：协作式 cancel、timeout、`request_cancel()`。
- `src/web/routes.py`：job cancel API。
- `src/web/templates.py`：wizard 高级选项、提示卡、mobile shell 元素。
- `src/web/static.py`：panel-progress CTA/cancel、mobile drawer/table CSS、subscore class、scores fallback。
- `tests/test_jobs_cancel.py`、`tests/test_routes_job_cancel.py`、`tests/test_static_subscore_compat.py`：新增/更新测试。
- `AGENTS.md`、`README.md`、`docs/AGENT_HANDOFF.md`、`docs/iterations/README.md`：文档刷新。

## 不在本轮范围

- 不动 `chapter_status` / `reviewer` / `writer` / `book_runner` 核心 happy path。
- 不动 iter042 打分制阈值与 iter043 §B UX 主框架。
- 不做 F1 二次 prompt 调优。
- 不强制 kill worker 线程，只做协作式取消。
- `_workspace_html_guard` 抽象作为可选 stretch goal，不阻塞收官。
- 不跑真实模型 smoke，不 push。

## Notes

- Bundle 3 的目标是清历史长尾，不展开新功能面。
- 若阅读 `_workspace_html_guard` 后未发现明显低风险抽象点，记录到 iter045 backlog 即可。
- 本轮结束时 README SOP 的“最近一次更新”、AGENTS 当前 iter 与 HANDOFF Phase Status 必须全部对齐 iter044。
