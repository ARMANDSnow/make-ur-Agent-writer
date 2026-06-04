# Iteration 043 — WebUI UX Audit + UX 重构 Bundle 1+2

## Context

iter042 已让真实 `longzu` ch2 在 `tier=mid` 下 approved，主链路从“跑不通”进入“用不爽”阶段。用户明确要求本轮按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter043 §A plan 做 read-only WebUI UX Audit：不改代码、不提交，只新增 UX 报告和本执行档案。

## Plan

- 读仓库锚点、最新 handoff、iteration index、iter038/039/041/042、README SOP 与外部 iter043 §A plan。
- `OPENAI_MODEL=mock` 启动本地 Web，走 5 条 journey：冷启动、空起点、happy path、失败/partial、drama。
- 截图归档到 `/tmp/iter043_ux_screenshots_20260604_235600/`。
- 静态 audit 信息架构、视觉层级、错误态、空状态、表单、移动适配。
- 横向对标 Notion AI / Cursor / Sudowrite 的单维度实践。
- 新增 `docs/iterations/iteration_043_UX_AUDIT.md` 与本文件；不碰代码、不提交。
- 收官前启动 1 个 read-only subagent 审核报告完整性与边界合规。

## Acceptance

- `iteration_043_UX_AUDIT.md` 具备 §0-§6，且 §6 至少 4 个方向、ROI、2-3 个 bundle。
- 5 条 journey 均有走查记录；drama 章节非空，并确认 iter038 P3 backlog 6 项现状。
- 截图以 `![label](/tmp/...)` 引用。
- 工作树不出现本轮代码/css/js/config 改动；不 commit。
- 若 read-only 边界阻止某一步，报告中明确说明替代方法和影响。

## Implementation Notes

- Web server：`OPENAI_MODEL=mock .venv/bin/python3 main.py web --host 127.0.0.1 --port 8793`。首次普通沙箱启动因 `socket.bind` `PermissionError` 失败；按权限规则提权后成功，仅绑定 loopback。
- Browser skill：使用 Codex in-app Browser 后台打开 `http://127.0.0.1:8793/`，保存 full-page PNG。
- 冷启动上传：尝试通过 localhost POST 创建临时 audit workspace 时被安全审查拒绝，理由是会创建 workspace 并启动 pipeline，与 read-only audit scope 冲突；因此没有创建新 workspace，也没有绕过该限制。
- 静态 audit 覆盖 `src/web/templates.py`、`src/web/static.py`、`src/web/routes.py`、`src/web/jobs.py`、`src/web/wizard.py` 与相关 iteration 文档。
- 既有基线 untracked：`.claude/launch.json`、`docs/iterations/iteration_041_INVESTIGATION.md` 已在本轮开始前存在；本轮不触碰。

## Acceptance Result

- 截图目录：`/tmp/iter043_ux_screenshots_20260604_235600/`，共 17 张有效截图；另有一张 early skeleton `01_shelf.png` 保留在目录中但报告未引用，报告使用 `01_shelf_loaded.png`。
- 覆盖页面：`/`、`/wizard`、`/w/asoiaf/continue`、`/w/longzu/continue`、`/w/longzu/jobs`、`/w/longzu/chapter/2`、`/w/iter039smoke/chapters`、`/w/iter039smoke/jobs`、`/w/iter039blocked/jobs`、`/w/i38drama01/`、`/w/i38drama01/write`、`/w/i38drama01/jobs`、`/w/i38drama01/reviews`、移动宽度 `asoiaf/continue`。
- `longzu` ch2 静态证据：meta/review 均 `Approve`，`tier=mid`，`panel_score=7.58`，`approve_count=4`，`chinese_char_count=4213`。
- `iter039smoke` partial 证据：`chapter_01.partial.md` + `chapter_01.failure.json` 存在，failure stage `budget_check_write`。
- `iter039blocked` blocked 证据：`outline_missing · outline not found; run python main.py debate first`。
- Subagent read-only audit：James 做了只读结构/程序性审核，范围限定为 `iteration_043_UX_AUDIT.md` 与本 PLAN，不编辑文件、不跑 smoke。结论：UX_AUDIT §0-§6 齐备，§6 有 8 个方向 + ROI + 3 个 bundle，5 条 journey 与 drama 章节均已覆盖，read-only/upload limitation 已说明；无 accidental scope expansion。审核指出 2 点：本行原本仍为“待补”（已修），以及 Acceptance Result 需补最终 worktree 证据（已补）。未修风险：无 blocking。
- Worktree evidence：最终 `git status --short --untracked-files=all` 仅显示基线已有 `.claude/launch.json`、`docs/iterations/iteration_041_INVESTIGATION.md`，以及本轮新增 `docs/iterations/iteration_043_PLAN.md`、`docs/iterations/iteration_043_UX_AUDIT.md`；未出现本轮代码/css/js/config 改动。

## 文件变更汇总

- `docs/iterations/iteration_043_UX_AUDIT.md`：新增 UX audit 主报告。
- `docs/iterations/iteration_043_PLAN.md`：新增本轮执行档案。
- `/tmp/iter043_ux_screenshots_20260604_235600/`：截图归档，不进 git。

## 不在本轮范围

- 不改任何 `src/`、CSS、JS、模板、config。
- 不更新 README SOP、AGENT_HANDOFF、iterations README；本轮不提交，§B/收官时再决定是否纳入。
- 不运行真实模型 smoke，不改 `.env`。
- 不修改 `data/`、`outputs/`、`小说txt/`；没有创建新的 audit workspace。
- 不动 `docs/iterations/iteration_041_INVESTIGATION.md`。

## Notes

- 本轮报告把“新发现”与“已知 backlog 仍存在”分开，避免重复发现。
- read-only scope 与“完整上传/extract journey”存在天然冲突：真实点击上传会创建 workspace 并启动 job。本轮选择遵守 read-only，不做 workaround。
- §B 最建议从 UX_AUDIT 的 Bundle 1 或 Bundle 2 开始：前者修方向感和 tier/drama 文案，后者修失败可恢复与历史状态降权。

---

# Iteration 043 §B — UX 重构 Bundle 1+2（D-1/D-2/D-3/D-4/D-6）

## Context

§A audit 锁定 WebUI 的“下一步不可见 / 失败不可恢复 / drama 与小说混用 / tier 无入口 / 过期文案泄露”五类高 ROI 问题。用户拍板实施 Bundle 1+2，严格按同一外部 plan `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 §B 执行，不重新设计、不跑真实模型、不做 Bundle 3。

## Plan

- Prep：归档 `iteration_041_INVESTIGATION.md`、`iteration_043_UX_AUDIT.md` 与 §B plan draft。
- D-1：readiness 增加 `next_unapproved_chapter` / `primary_blocker`，前端改主 CTA + 紧凑状态 + 折叠诊断。
- D-2：jobs 表格增加 drawer、partial preview、同参数重试、`jobActionableSummary`。
- D-3：书架/overview/sidebar type-aware，drama 返回 `drama_progress`，历史 job 降权，清 type badge / metric inline。
- D-4：write-book 表单增加试写/生产/严格 preset、tier select，高级参数折叠；后端缺省 tier 归一为 `mid`。
- D-6：drama shell 收口、过期 iter 文案清理、novel-only drama 页面改 200 empty-state、toast dismiss、wizard placeholder。
- 阶段验收：全量 unittest、mock preflight、verify、Web 截图回归、read-only subagent 审核、最终 handoff 同步。

## Acceptance

- `.venv/bin/python -m unittest discover` → `OK (skipped=6)`。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- 截图回归目录 `/tmp/iter043B_screenshots_20260605_005741/` 覆盖 audit 关键 journey。
- `rg "placeholder, see creation_standard|iter 03[0-9]" src/web/` 无结果。
- 不跑真实模型、不 push；每个 D 段独立 commit。

## Implementation Notes

- Prep commit：`22962e1 Iteration 043 §B prep: plan + iter041/043 audit archive`。
- D-1 commit：`4bbf6d4 Iteration 043 §B D-1: readiness 分层 + 主 CTA`。
- D-2 commit：`cb6fc65 Iteration 043 §B D-2: jobs drawer + failure recovery`。
- D-3 commit：`820b0bf Iteration 043 §B D-3: 书架 type-aware + sidebar 历史降权 + inline style 清债`。
- D-4 commit：`39af25a Iteration 043 §B D-4: write-book preset + tier 选档器`。
- D-6 commit：`ed4539a Iteration 043 §B D-6: drama shell 收口 + 过期文案清理`。
- D-1 runner 内部调用 `check_write_readiness(..., include_next_unapproved=False)`，避免新增全书扫描改变 `run_write_book()` 主链路调用序；外部 readiness API 默认仍返回 `next_unapproved_chapter`。
- `next_unapproved_chapter` 对 `longzu` 这类历史 ch1 Reject / ch2 Approve 的状态优先取最新 approved 之后的下一章，因此 continue 默认落到 ch3。
- D-2 jobs drawer 只复用现有 `/run` 和 `/draft/<chapter>?variant=partial` 路由，不新增后端接口。
- D-6 为满足源码 grep，将 `src/web/` 内历史 `iter 03x` 注释/docstring 与两个 UI 文案一并改为中性描述。

## Acceptance Result

- 单测：`.venv/bin/python -m unittest discover` → 577 tests，`OK (skipped=6)`；audit follow-up 修复后复跑同命令仍为 577 tests，`OK (skipped=6)`。
- Preflight：`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`，FATAL none，WARN none；audit follow-up 后复跑仍为 `PREFLIGHT: ok`。
- Verify：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，577 tests `OK (skipped=6)` + mock auto-pipeline OK；audit follow-up 后复跑仍 exit 0。
- Web server：普通沙箱启动因 `socket.bind` `PermissionError` 失败；按权限规则提权后以 `OPENAI_MODEL=mock .venv/bin/python main.py web --port 8766` 仅绑定 loopback，用于截图回归；截图后已关闭 PID 70244。
- 截图目录：`/tmp/iter043B_screenshots_20260605_005741/`，共 9 张 PNG。
- Subagent follow-up targeted：`.venv/bin/python -m unittest tests.test_web_routes_get tests.test_workspace_overview_drama` → 58 tests OK；`rg "style=\"color:var\\(--amber-strong\\)|placeholder, see creation_standard|iter 03[0-9]" src/web/` → 无结果。

### Screenshot Regression

| Journey | §A 痛点 | §B 验收点 | 截图 |
|---|---|---|---|
| B 空起点 | 满屏 blockers，用户不知道先做什么 | `asoiaf/continue` 显示“下一步”主 CTA + 折叠诊断 | ![asoiaf readiness](/tmp/iter043B_screenshots_20260605_005741/03_asoiaf_continue_readiness_cta.png) |
| C happy path | `longzu` 默认 ch1 被历史失败拖住，tier 无入口 | `resume_from=3`，preset + `tier=mid` select 可见，sidebar 历史失败降权 | ![longzu continue](/tmp/iter043B_screenshots_20260605_005741/04_longzu_continue_preset_tier_next.png) |
| D 失败恢复 | Jobs 只显示截断 note，看不到 partial/snapshot/恢复动作 | drawer 展示 snapshot、partial 链接、查看 partial、重试按钮 | ![jobs drawer](/tmp/iter043B_screenshots_20260605_005741/05_iter039smoke_jobs_drawer.png) |
| E drama | drama 页面混 novel 404 / 过期 iter 文案 | drama reviews 返回 shell empty-state；write 页无 iter 文案，站点状态仍可见 | ![drama shell](/tmp/iter043B_screenshots_20260605_005741/09_i38drama01_reviews_empty_shell.png) |

## 文件变更汇总

- `src/book_runner.py`：readiness 派生字段 `next_unapproved_chapter`、`primary_blocker`；runner 内部跳过派生扫描。
- `src/web/static.py`：CTA_ACTIONS、readiness panel、jobs drawer/partial modal/retry、type-aware shelf/sidebar、preset/tier JS、toast dismiss、过期文案清理。
- `src/web/templates.py`：write-book preset/tier/advanced details、drama empty-state 文案、wizard placeholder、novel-only shell。
- `src/web/routes.py`：drama overview `drama_progress`、write-book tier 默认、drama novel-only shell 200、drama `/run` hint。
- `tests/test_book_runner.py`、`tests/test_jobs_drawer.py`、`tests/test_workspace_overview_drama.py`、`tests/test_routes_write_book_tier.py` 与 Web route tests：新增/更新覆盖。
- `docs/iterations/iteration_043B_PLAN_DRAFT.md`：归档外部 §B plan draft。

## 不在本轮范围

- 不做 Bundle 3 D-5/D-7/D-8；Insights `scores || sub_scores`、subscore inline、guard 抽象、AGENTS.md 全面刷新转 iter044。
- 不动 `chapter_status`、reviewer/writer 主 happy path、iter042 tier 阈值。
- 不跑真实模型 smoke，不改 `.env`，不 push。

## Notes

- Subagent read-only audit：Bacon 做了只读结构/程序性审核，结论 non-blocking。D-1/D-2 的 `CTA_ACTIONS` 与 backend `primary_blocker` / jobs drawer 恢复入口一致，`jobActionableSummary` 作为摘要层复用 `jobBlockedDetail` / `jobFailureLine`，未发现 failed/blocked/partial/succeeded 展示路径回退。
- drama novel-only 页面改 HTTP 200 shell 已有 route test 覆盖；主要剩余兼容风险是外部客户端若依赖旧 404 语义，需要同步预期。
- 审核发现 `templates.py` drama overview 仍有一处 type badge inline style，已按 D-3 范围补为 `badge-drama` 并用 targeted route tests + grep 复验；Insights/subscore inline style 继续留给 iter044 Bundle 3。
- legacy workspace 缺失/未知 `type` 仍默认 novel，测试覆盖存在。
- iter044 backlog 建议：Bundle 3（D-5 onboarding budget/timeout/cancel、D-7 form/mobile density、D-8 Insights scores/sub_scores + subscore inline）+ AGENTS.md 全面刷新。
