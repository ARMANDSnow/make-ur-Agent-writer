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

- `.venv/bin/python -m unittest discover` → `OK (skipped=6)`，期望约 590 tests。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- Chrome DevTools / browser 回归：iPhone 13 + iPad 各跑 B/C/D/E journey，截图归档到 `/tmp/iter044_mobile_screenshots_<ts>/`。
- Mock cancel 流程：wizard 上传 mock workspace → 进度页点 cancel → aborted 状态 + CTA 组截图。
- 文档 grep：过期 iter040-043 “下一步候选”文案检查 → 0 命中；`rg "TODO|FIXME" AGENTS.md README.md` 人工确认无过期 todo。
- 收官前至少 1 个 read-only subagent 审核 cancel 并发/timeout、移动 drawer、subscore class、文档一致性、旧 workspace/schema 兼容；结论写回本 PLAN。
- 全程不跑真实模型，不改 `.env`、`data/`、`outputs/`、`小说txt/`，不 push。

## Implementation Notes

- Prep commit：`f4e9fbf` — `Iteration 044 prep: plan + draft archive`。
- §A.1 commit：`bb4f2fd` — `Iteration 044 §A.1 D-5: 后端 cancel + timeout 协作式机制`。
- §A.2 commit：`88d3bc7` — `Iteration 044 §A.2 D-5: cancel 路由 + 校验`。
- §A.3 commit：`9aac38e` — `Iteration 044 §A.3 D-5: wizard 高级选项 + panel-progress CTA`。
- §B.1 commit：`52bc668` — `Iteration 044 §B.1 D-7: sidebar drawer + topbar 折叠`。
- §B.2 commit：`b41ae88` — `Iteration 044 §B.2 D-7: 表格移动响应式`。
- §C.1 commit：`1cf788c` — `Iteration 044 §C.1 D-8: subscore inline style → CSS class`。
- §C.2 commit：`135e676` — `Iteration 044 §C.2 D-8: Insights scores/sub_scores 兼容`。
- §D commit：`29d7cf5` — `Iteration 044 §D: 文档刷新对齐到 iter044`。
- Final commit：本文件收口后提交，message 为 `Iteration 044: 收尾轮（D-5/D-7/D-8 + 文档刷新）`。

Final audit patch（收进 final commit）：

- `src/web/jobs.py`：`request_cancel()` 在 `_JOBS_LOCK` 内重查 `pending/running`，并用 `_complete_job()` 防止 late cancel 被 success 覆盖。
- `src/web/static.py`：chapter detail fallback 改为非空 `scores` 优先，否则落回 `sub_scores`，修复 `{}` truthy 兼容洞。
- `src/web/routes.py` + `JS_WIZARD`：新增 secret-free `/api/preflight` runtime mode endpoint，wizard mode card 改读运行时 `OPENAI_MODEL`，避免 `.env` profile 与 `OPENAI_MODEL=mock` 进程覆盖不一致。
- 新增/更新测试：terminal cancel reject、runtime preflight endpoint、empty `scores` fallback 断言。

## Acceptance Result

通过（mock-only，未跑真实模型 smoke）。

命令验收：

- `.venv/bin/python -m unittest discover` → `Ran 590 tests ... OK (skipped=6)`。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`，FATAL/WARN 均 none。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，内部 unittest 同为 `590 tests OK (skipped=6)`。

截图回归：

| 项 | Before | After / Evidence |
|---|---|---|
| 移动 sidebar | 768px 以下硬隐藏 | iPhone 13 + iPad drawer 可开关，遮罩可见：`/tmp/iter044_mobile_screenshots_20260605_020931/*_drawer.png` |
| 表格移动端 | jobs/chapters/reviews 易挤压 | B/C/D/E journeys manifest 均 `overflowX=false`，table 页面有 `.table-scroll` 容器 |
| wizard cancel | 只有等待 worker 占位 | `iphone13_cancel_aborted.png` 显示 `mock`、`status=aborted`、`current_step=cancelled`、取消原因与“重新开始 / 返回书架” CTA |
| mock/real 标识 | 初版读 `/api/settings`，会显示持久 `.env` profile | final patch 改读 `/api/preflight` runtime endpoint；截图显示 `OPENAI_MODEL=mock，本次不会消耗真实 token` |

截图目录：`/tmp/iter044_mobile_screenshots_20260605_020931/`。

文档 grep：

- 过期 iter040-043 “下一步候选”文案检查：0 命中。
- `rg "TODO|FIXME" AGENTS.md README.md`：0 命中。

Subagent read-only audit：

- 审核 agent：Laplace（read-only；未修改文件、未跑真实模型、未触碰 `.env` / `data/` / `outputs/` / `小说txt/`）。
- 初审发现并已修：cancel terminal TOCTOU、JS empty `scores` masking `sub_scores`、iteration docs placeholder、wizard mode card 读 persisted settings 而非 runtime。
- 初审 clean：mobile drawer resize/Escape/topbar 恢复逻辑、workspace type fallback、Python Insights `scores or sub_scores` 聚合。
- 保留未修风险：timeout/cancel 仍是协作式 checkpoint 语义；长 handler/provider call 无 progress 时不会强 kill，只会在下一 checkpoint 或 handler 返回后进入 `aborted`。这符合本轮“不强制 kill worker 线程”边界，后续若要 wall-clock hard timeout 需单独设计 worker isolation。

## 文件变更汇总

计划变更：

- `docs/iterations/iteration_044_PLAN_DRAFT.md`：归档外部 iter044 草稿。
- `docs/iterations/iteration_044_PLAN.md`：本轮执行档案。

预期实施变更：

- `src/web/jobs.py`：协作式 cancel、timeout、`request_cancel()`；final patch 补 terminal recheck 与 late cancel completion guard。
- `src/web/routes.py`：job cancel API；final patch 新增 secret-free `/api/preflight` runtime mode endpoint。
- `src/web/templates.py`：wizard 高级选项、提示卡、mobile shell 元素。
- `src/web/static.py`：panel-progress CTA/cancel、mobile drawer/table CSS、subscore class、非空 `scores` / legacy `sub_scores` fallback、wizard runtime mode card。
- `tests/test_jobs_cancel.py`、`tests/test_routes_job_cancel.py`、`tests/test_static_subscore_compat.py`、`tests/test_web_routes_get.py`：新增/更新测试。
- `AGENTS.md`、`README.md`、`docs/AGENT_HANDOFF.md`、`docs/iterations/README.md`：文档刷新到 iter044 / 590 tests。

## 不在本轮范围

- 不动 `chapter_status` / `reviewer` / `writer` / `book_runner` 核心 happy path。
- 不动 iter042 打分制阈值与 iter043 §B UX 主框架。
- 不做 F1 二次 prompt 调优。
- 不强制 kill worker 线程，只做协作式取消。
- `_workspace_html_guard` 抽象作为可选 stretch goal，不阻塞收官。
- 不跑真实模型 smoke，不 push。

## Notes

- Bundle 3 的目标是清历史长尾，不展开新功能面。
- `_workspace_html_guard` 抽象已阅读，未发现明显低风险且收益足够的抽象点，本轮不动，记录到 iter045+ backlog。
- 本轮结束时 README SOP 的“最近一次更新”、AGENTS 当前 iter 与 HANDOFF Phase Status 已全部对齐 iter044。
- Playwright wrapper 因 npm 网络/权限失败未用；改用本机 headless Chrome + DevTools Protocol 截图，产物归档到 `/tmp/iter044_mobile_screenshots_20260605_020931/`。
- 真实模型 smoke 未跑；wizard cancel 截图使用 `OPENAI_MODEL=mock` 进程，取消发生在 extract checkpoint 后、LLM-bearing 后续步骤前。
