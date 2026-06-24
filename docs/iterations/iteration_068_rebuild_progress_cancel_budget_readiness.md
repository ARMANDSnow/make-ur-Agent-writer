# Iteration 068 - 续写底座重建 + 长任务可观测/可取消 + readiness 重做（codex 前端验证 P0/P1 收口）

## Context

codex 通过前端验证（以 longzu1_clean 续写）暴露一批 P0/P1：真实用户从《龙族1》中段往后续写时，Workbench 第①步把"已有起点的续写"错当成"开新书"（绑死 `prepare-greenfield`），长任务进度卡在 33% 像死了，当前卡片无法止损，且 prepare 任务**无预算守门**（真模型下无上限烧钱）；readiness 提示指向只读 `/plan`、KB 缺失被笼统归为 `unknown`、起点窗口未提取只当 warning。

3 个 Explore agent 逐条读代码核实**基本全属实**；用户又派 4 个 subagent 对修复计划二次只读审核，抓出**预算 fail-open**（validator 缺省注入 `budget_cny:0` 被 jobs 当无限额）、**硬删 workspace 触碰原文版权边界**等 P0，已并入本轮。

关键复用点：CLI 已有 `auto_pipeline.rebuild_for_start`（补提取起点窗口→重建 KB/实体图/锚点→应用）；`jobs._progress` 内部已先调 `_check_cancelled` 再 `_update`，故底层多调 `progress_cb` 即免费获得 cooperative cancel；readiness 三处（core/errors/前端）已从 `readiness_catalog.KINDS` 自动派生；`web/trash.soft_delete_workspace` 现成。

## Plan

- **A · rebuild-for-start Web job**：`rebuild_for_start` 加 `budget_check` 参数（in-loop 早停）；新增 `jobs._step_rebuild_for_start`（预检起点、不 blanket-catch ValueError）+ `STEP_HANDLERS` 注册 + `_summarize_result` 分支；前端 `bindWorkbenchStage` 运行时求值，prepare/plan-chapters/write-book **三个 stage 都按 `has_start_point` 切**（含 `require_start_point`）；模板加文案钩子 + `refreshWorkbench` 改文案。
- **B · 阶段内进度透传**：`extract_all`/`compress_all`/`bootstrap_all` 加 `progress_cb=None`（向后兼容）；`extract_all` **每个 manifest entry 都回调**（含 cached/失败，checkpoint 均匀）；`_run_prepare_steps`/`rebuild_for_start` 区间映射子进度（带 `:` 前缀避免污染 STEPS 契约）；保 `bootstrap_all` 6 key 现序。
- **C · pollJob 取消**：非终态加「取消任务」按钮 + 任务页链接 + 诚实文案（"最多再等当前一次 LLM 调用"）；document 级 `[data-cancel-job]` 委托调既有 cancel API。
- **D · prepare/rebuild 预算守门（含 fail-open 修复）**：`routes._validate_prepare_params` **validate-only-if-present**（缺省不写 budget_cny → jobs 层兜默认 cap；explicit 0 = uncapped）；`_step_prepare_greenfield` 接 `budget_check` 闭包 + `BudgetExceeded`→`budget_exceeded`。
- **E · readiness 真产 blocker**：`readiness_catalog` 加 `kb_missing`/`settings_missing`/`extraction_coverage_missing` + classify 映射 + outline CTA 改 `run_debate`；`book_runner.check_write_readiness` 真 append KB/settings/start_window blocker（start_window 仅 `require_start_point` 时升）；`_step_plan_chapters` 起点窗口 ValueError→`_blocked("extraction_coverage_missing")`；`static` CTA 跳 `/workbench#stage-*` + `renderJobPageCta` 去硬编码。

## Acceptance

- `unittest discover -s tests` 全绿（更新进度契约/catalog 测试 + 新增 rebuild job/预算 fail-open/readiness/进度/cancel 测试）。
- `bash scripts/verify.sh`、`python3 main.py preflight` 通过。
- mock 前端验证（longzu_half 半本起点）：stage ① 文案="重建续写底座" 且 job=`rebuild-for-start`；进度显示 `extract:章号` 子进度；取消按钮可用→aborted；`budget_cny:0.001`→`budget_exceeded`、不传→默认 cap；缺 KB/起点窗口→结构化 blocker + CTA 跳 `/workbench#stage-*`；happy path 出 1 章。
- `/code-review high` + `/security-review` 结论与未修风险记入下方。

## Implementation Notes

**实施顺序**：D（含 fail-open）→ B（进度透传，A/C 前置）→ A 后端（含 in-loop 预算）→ A 前端（三 stage 切换）→ E（readiness）→ C（pollJob 取消）。

**取消免费搭车（已验证）**：`jobs._progress` 内部先 `_check_cancelled` 再 `_update`，故底层只要多调 `progress_cb` 就同时获得进度 + cooperative cancel + timeout，无需给 extract/compress/bootstrap 加单独 cancel 参数。

**fail-open 修复（审核 P0-1）**：`routes._validate_prepare_params` 采用 **validate-only-if-present**——缺省不写 `budget_cny` 字段，让 jobs 层 `_float_param(...,_default_budget_cny())` 兜默认 cap；显式 `0` 才是 uncapped（CLI 语义）。回归测试覆盖 omitted/explicit-0/explicit-value 三态。

**进度契约（头号风险，已化解）**：子进度标签统一带 `:` 前缀（`extract:chXXX` / `compress:llm` / `bootstrap:entity_graph`），落在各 stage 的 `[i,i+1)/total` 区间；测试侧用 `":" not in s` 过滤后断言 6 个裸边界标签 == STEPS。改了 `test_auto_pipeline.py` 1 处 + `test_premise_prepare_diag.py` 3 处（其中 2 处的 `seen[5]` 索引断言改为先过滤再索引 `bare[5]`）。

**rebuild 预算改 in-loop（审核 P1-4）**：给 `auto_pipeline.rebuild_for_start` 加 `budget_check` 参数，在 extract/compress/bootstrap-graph/bootstrap-anchor 各阶段后结算，超额早停——否决了原"后置结算"方案。`_step_rebuild_for_start` **预检起点**（`get_start_chapter_id()` 为空→`_blocked`）而非 blanket-catch ValueError，故 apply/bootstrap 的真实 ValueError 照常 propagate 成 failed（有专门测试）。

**三 stage 切换（审核 P1-3）**：`bindWorkbenchStage` 第 4/5 参支持运行时函数求值；prepare/plan-chapters/write-book 都按 `lastWorkbenchStatus.has_start_point` 切——有起点时 prepare 走 `rebuild-for-start`（params `{window:10}`，**不传 force/reextract**，补齐底座非强制重提，审核 P1-8），plan/write 传 `require_start_point:true` 不绕过起点闸。

**CTA 全链（审核 P1-7）**：`renderJobPageCta` 去掉硬编码 `/plan//continue`，改 `ctaActionHref(cfg.action)`；新增 `run_prepare`/`run_rebuild_for_start`→`/workbench#stage-prepare-card`、`run_debate`→`/workbench#stage-outline-card` 的 dispatch（Continue 页无 stage 卡，必须跨页跳 workbench）。pollJob 取消按钮用 dashboard 自有的 document 级 `[data-cancel-job]` 委托（JS_WIZARD 的同名委托在别的 bundle，不可复用）。

**readiness scope 决策（审核 P1-5，诚实记录见 Notes）**：extraction_coverage_missing 全链落地（book_runner 条件 blocker + plot_planner 既有 ValueError 映射 + classify + CTA）；kb_missing 复用 `_step_debate` 既有 `_blocked` 信号 + classify 渲染；**settings_missing 与"check_write_readiness 新增 KB/settings 存在性 blocker"未做**——见 Notes 的范围说明。

## Acceptance Result

**单测**：`unittest discover -s tests` → **1319 tests OK**（基线 1294 + 25：新增 `test_iter068_rebuild_progress_cancel.py` 27 用例，调整 4 处进度契约 + 1 处 outline CTA 断言）。新增覆盖：rebuild job 注册/无起点 _blocked/默认 cap/explicit-0 uncapped/budget_exceeded/真错不误报/extraction_failures、prepare 预算 fail-open（omitted→默认 cap、explicit-0→uncapped）、`_validate_prepare_params` validate-only-if-present、bootstrap_all 进度+6 key 序、plan-chapters coverage→extraction_coverage_missing、新 readiness kinds classify/card。

**verify.sh**：venv python 下 exit 0（1319 OK + CLI normalize→split→auto-pipeline→status… 全链通过）。注：裸 `python3` 缺 pydantic 会假失败（环境 quirk，非回归），需 `PATH=.venv/bin:$PATH`。

**preflight**：FATAL/WARN 均 none。

**前端 mock 验证（longzu_half 半本起点 = longzu_1_ch007）**：
- Cluster A ✓ 工作台 stage ① 文案/按钮 = "重建续写底座"（截图存证），表单 POST `step:"rebuild-for-start", params:{window:10}`（不传 force/reextract）；rebuild 跑通建 KB → stage prepare→outline 推进；plan-chapters/write-book 携带 `require_start_point:true`；debate→plan 成功（write-book 因 mock reviewer 确定性 Reject 落 retry_exhausted，draft 已出稿，与 iter068 无关）。
- Cluster C ✓ pollJob 渲染 `data-cancel-job` 取消按钮 + 任务页链接。
- Cluster E ✓ 注入的 `window.READINESS_CATALOG`：kb_missing→run_prepare、extraction_coverage_missing→run_rebuild_for_start、outline_missing/stale→run_debate；rebuild 抽取窗口后 coverage blocker 正确清除（状态驱动）。
- 自包含 ✓ longzu_half `source_file` 旧路径残留 = **0**（修复审计的 907 处不自包含问题）。
- Cluster B/D 由单测覆盖（mock 瞬时完成无法实时抓子进度；mock 成本≈0 无法实地触发预算超额）。

**workspace 清理**：`soft_delete_workspace("longzu1_clean")` → `_trash/longzu1_clean__20260624_234418`（可逆，未硬删，未碰原文）。

**/code-review high**：3 角度并行 finder。3 个"correctness"finding（进度分数不到 1.0）经核算**全部 refuted**——`:`-子标签报的是 slot 内进度，裸边界标签 + `("done",1.0)` 标记阶段完成，整体单调到 1.0。采纳 1 个 cleanup：抽出 `_budget_guard(params)` 共享 helper，消除 `_step_prepare_greenfield`/`_step_rebuild_for_start` 重复的预算闭包。其余（CTA 路由 scroll vs href、timeout-carry、`:` 约定、signal 字符串）评估为语义不同或可接受，记录不改。refactor 后 1319 仍 OK。

**/security-review**：iter068 新攻击面（rebuild 参数、cancel 按钮、CTA 路由）无 HIGH/MEDIUM 漏洞——参数服务端校验且不拼路径、DOM 动态值全 `escapeHtml`、导航锚点为常量、无 subprocess/eval。fail-open 修复属安全**净提升**（堵预算绕过）。

**未修风险**：见 Notes 的 readiness scope 决策（settings_missing 无真信号未做、check_write_readiness 不新增 KB/settings 存在性 blocker，避免 052 式过度阻断）。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| src/web/routes.py | 新增 `_validate_prepare_params`（validate-only-if-present 修 fail-open）+ `_validated_run_params` 路由 prepare/rebuild |
| src/web/jobs.py | `_step_prepare_greenfield` 接 budget_check + budget_exceeded；新增 `_step_rebuild_for_start`（预检起点/in-loop 预算/错误映射）+ STEP_HANDLERS 注册；`_summarize_result` 加 prepare-greenfield/rebuild-for-start 分支；`_step_plan_chapters` 映射 coverage ValueError→extraction_coverage_missing |
| src/auto_pipeline.py | `_run_prepare_steps` 子进度区间映射 `_sub`；`rebuild_for_start` 加 `budget_check` 参数 + 阶段间结算 + extract 子进度 |
| src/extractor.py | `extract_all` 加 `progress_cb`（每 manifest entry 顶端回调，含 cached/失败）|
| src/compressor.py | `compress_all` 加 `progress_cb`（index/llm/write 三 checkpoint）|
| src/auto_bootstrap.py | `bootstrap_all` 加 `progress_cb` + list 驱动 `_BOOTSTRAP_STEPS`（保 6 key 现序）|
| src/readiness_catalog.py | KINDS 加 kb_missing/extraction_coverage_missing；outline_missing/stale CTA→run_debate；classify 加 extraction-coverage 映射 |
| src/book_runner.py | check_write_readiness 的 start_window warn→条件 blocker（仅 require_start_point）+ recommended 改 rebuild-for-start |
| src/web/templates.py | stage-prepare-card 加 `#prepare-subtitle`/`#prepare-hint` 钩子 |
| src/web/static.py | bindWorkbenchStage 运行时 step 求值；initWorkbench 三 stage 按 has_start_point 切；refreshWorkbench 改 stage① 文案；bindCtaActions 加 run_prepare/run_rebuild_for_start/run_debate；新增 gotoStage/ctaActionHref；renderJobPageCta 去硬编码；pollJob 加取消按钮+任务页+诚实文案+ensureJobCancelDelegate |
| tests/test_iter068_rebuild_progress_cancel.py | 新增：rebuild job/prepare 预算 fail-open/validate_prepare/bootstrap 进度+key 序/plan-chapters coverage/readiness kinds（27 用例）|
| tests/test_auto_pipeline.py、tests/test_premise_prepare_diag.py | 进度契约断言改为过滤 `:` 子标签 + 子进度发火断言 |
| tests/test_web_errors.py | outline_stale CTA 断言 go_plan→run_debate |
| docs/iterations/README.md、docs/iterations/iteration_068_*.md | 索引 + 本轮 8 段文档 |

## 不在本轮范围

- 用子进程/async **硬杀**正在跑的同步 litellm 调用——线程做不到，本轮只做 cooperative cancel（当前调用结束后不再启动下一次），UI 文案诚实说明。
- workspace 自包含 **sed 迁移**（907 处 source_file）——由 Part 2「软删脏副本、从 longzu 重建干净起点」替代。
- **真模型**验证——本轮 mock；管线确认后另起授权（铁律⑥）。
- iter067 的 corrupt entity_graph **auto-heal**——本轮未触碰。

## Notes

**readiness scope 诚实记录（铁律⑦）**：审核 P1-5 要求 check_write_readiness 真产 `kb_missing`/`settings_missing`/`extraction_coverage_missing` blocker。实施时发现 `test_strict_plan_ready` 钉死了一个**既有契约**：start-point 已设 + 无 KB 文件 + 无 entity_graph 文件 → `status == "ready"`（铁律④ graceful-degrade）。若给 check_write_readiness 加 KB/entity_graph **存在性** blocker，会翻转该测试及多个共用 `_common_patches` 的 fixture（052 式过度阻断风险）。故本轮：
- ✅ `extraction_coverage_missing`：全链落地（book_runner 条件 blocker 仅 require_start_point + plot_planner 既有 hard ValueError 映射 + classify + rebuild CTA）。这是 fixture 返回 `[]` coverage 时不触发、真有缺口时才 block 的安全信号。
- ✅ `kb_missing`：复用 `web/jobs._step_debate` 既有 `_blocked("kb_missing")`（debate 是 KB 的真硬前置），现经新增 classify 渲染为专用卡片而非 `unknown`。
- ⏸ **`settings_missing` 未实现**：当前无任何真实信号产出它（entity_graph 缺失走 graceful-degrade，与 KB 同），加一个 dead KIND 会误导。留待后续：若要 entity_graph 缺失阻断，需先确立其 fail-closed 语义与 fixture 迁移。
- ⏸ **check_write_readiness 不新增 KB/settings 存在性 blocker**：与既有 ready 契约冲突，KB 缺失继续在 debate 步骤兜底（现渲染正常卡片）。供 codex 复审：若坚持要继续页 readiness 直接暴露 kb_missing，需配套迁移 readiness 测试 fixture（建 KB/entity_graph 文件）并重审 052 过度阻断边界。

**取消的真实边界**：Python 线程内无法硬杀同步 litellm 调用；本轮取消 = cooperative（当前调用结束后不再启动下一次），UI 文案如实写"最多再等当前一次 LLM 调用结束"。真正的硬中断需 async/子进程隔离，记入后续候选。

**后续候选（iter069+）**：硬中断取消（async/子进程）/ settings_missing 真信号 + readiness fixture 迁移 / workbench prepare 预算·timeout UI 控件（本轮后端守门已就位，前端仍用默认值）/ rebuild-for-start 进度卡显示 window 章号明细 / 真模型 capstone 验证半本起点（铁律⑥需授权）。
