# Iteration 071 - codex iter070 复审 residual 收口：leave-guard 全出口覆盖 + 活跃任务真源 + 模态焦点 + 空书架真测

## Context

iter070 落地「⌂→首页 + 离开守卫三选一模态」后，codex 对本轮改动做复审，报告 4 项 findings（1 Medium + 1 P2 + 2 Low）。本轮（claude）先逐项核实**全部属实**，再按优先级一轮收口。4 项同源——都是 iter070 leave-guard 的 residual。

**核实结论（4/4 属实，均带 file:line 证据）**：

1. **Medium — topbar 三出口绕过离开守卫**：[`_topbar_actions`](../../src/web/templates.py)（templates.py:205-211）渲染的「♻ 回收站 / ⚙ 设置 / ＋ 新建」三链接（`/trash` `/settings` `/wizard`）**无 `data-leave-guard`**。它们与 ⌂/brand/面包屑首项一样是「离开当前 workspace」的出口，但 JS 委托 [`ensureLeaveGuardDelegate`](../../src/web/static.py)（static.py:2125）只拦 `[data-leave-guard]`。后果：任务运行中，用户从「回收站/设置/新建」离开**不触发**三选一模态——守卫存在覆盖洞。

2. **P2 — 守卫可能漏掉刚入队的 pending 任务**：守卫 [`checkLeaveGuard`](../../src/web/static.py)（static.py:2138）查 `/jobs/recent?n=10`；后端 [`recent_jobs`](../../src/web/jobs.py)（jobs.py:153-159）按 `finished_at || started_at || 0` 倒序后截断 `n`。刚入队的 pending 任务 `started_at=None`（[`_new_job_record`](../../src/web/jobs.py) jobs.py:85）→排序键 0→排到列表**末尾**，当历史终态任务 ≥10 条时被 `?n=10` 截掉。codex 复现：10 条终态 + 1 条 `started_at=None` 的活跃 pending → `recent10` 看不到（`recent50` 能看到）。

3. **Low — 离开守卫模态键盘焦点弱**：[`showLeaveGuardModal`](../../src/web/static.py)（static.py:2174）`appendChild` 后**未移焦**进模态，键盘用户仍停在背景链接上（可 Tab 出模态、Enter 误触背景）。对照 delete 模态（static.py:2109）至少 `setTimeout(()=>input.focus(),0)`。

4. **Low — 空书架测试/文档过度宣称覆盖**：[`test_iter070_library_empty_hint_is_type_neutral`](../../tests/test_web_routes_get.py)（test:731）命中带 alpha/beta fixture 的 `/library`，`names` 非空→空状态文案（templates.py:265 的 `empty_hint`）**根本不渲染**，`assertNotIn("epub")` 空跑通过，未真正校验中性文案。iter070 文档第 55 行「空书架文案由 `assertNotIn` 覆盖」**过度宣称**。

**修法定调（关键决策）**：

- F2 **不动 `recent_jobs`**。探查确认它有 4 个依赖排序的消费方（continue 侧栏 `refreshRecentJobsSidebar` static:3513 / jobs 表 `initJobs` static:4531 / overview novel+drama recent_job limit=1 routes:474,519），改排序会波及它们的展示顺序。改用**新增 `jobs.active_jobs(workspace)` 直读内存 `_JOBS`**：`start_job`（jobs.py:1141-1152）入队即原子写 `_JOBS[job_id]`（status=pending）+ `_WORKSPACE_JOBS[workspace]`，且每 workspace **至多 1 个活跃任务**（第二个并发 start 409）。故 `active_jobs` 直接 filter `_JOBS` 里本 workspace 的 `pending|running`——零截断、零排序依赖、零回归。进程重启后 `_JOBS` 空→返回 []→守卫 fail-open 放行，这正确：重启后那些 job 已不在跑，warn「离开不会停止它们」反而是假的。

**用户 E2E 现场追加（F5 + F6）**：claude 完成 F1-F4 后用 preview MCP 真实点击验证，用户看到模态截图，当场指出**这一模态自身**的两个 UX 问题（直接在本轮新建的 surface 上，按铁律⑦属"被触碰面的真实缺陷"，纳入本轮）：

5. **F5 — 内部 step id 泄漏给用户**：模态正文 `还有 N 个任务在跑（write-book）` 把内部 step id（`jobs.py` `STEP_HANDLERS` 键，如 `write-book`/`extract`）直接显示给用户，未中文化。
6. **F6 — 三选一按钮丑、大小形状不一**：footer 用 `display:flex;justify-content:flex-end`，3 个长短差异大的标签（`留在本页`/`取消任务并离开`/`去书架（后台继续）`）按内容撑开，在 480px 模态里各自换行成 2 行、宽度参差。

## Plan

仅改 `src/web/{templates,jobs,routes,static}.py` + `tests/` + 文档，纯前端展示层 + 一个只读后端端点，不动 9 阶段管线。

- **F1（Medium）** topbar 出口纳入守卫：`_topbar_actions` 的 3 个 base 链接（`/trash` `/settings` `/wizard`）各加 `data-leave-guard`。`extra` 参数透传不动（page 内动作不该被守卫）。非 workspace 页 `WORKSPACE_NAME=""` 自然短路，零副作用。
- **F2（P2）** 活跃任务真源：
  - `jobs.py` 新增 `active_jobs(workspace)`：`_JOBS_LOCK` 下 filter 本 workspace `status in {pending,running}` 的快照（list，对齐 `/jobs/recent` 形状，虽至多 1 个）。
  - `routes.py` 新增 `api_workspace_active_jobs` + 路由 `GET /api/workspace/{name}/jobs/active` → `{"jobs": active_jobs(name)}`，紧邻 `/jobs/recent` 注册。
  - `static.py` `checkLeaveGuard` 把 `wsUrl("/jobs/recent?n=10")` → `wsUrl("/jobs/active")`；返回已是活跃集，前端 filter 可保留（双保险，端点已只返活跃）。
- **F3（Low）** 模态焦点：`showLeaveGuardModal` 取 `[data-modal-close]`（「留在本页」最安全默认），`setTimeout(()=>stayBtn.focus(),0)` 移焦进模态。不引入完整 focus-trap（与 delete 模态约定一致，避免单模态新机制——见 iter070 既存模态债）。
- **F4（Low）** 空书架真测 + 文档订正：
  - `tests` 新增 `render_index([])` 直测：断言中性文案在 `data-empty` 里 + `assertNotIn("epub")`（真正渲染空态）。保留原 route 级 `assertNotIn` 作非空书架回归护栏。
  - 订正 iter070 文档第 55 行的过度宣称为「空书架文案由 iter071 `render_index([])` 直测补齐覆盖」。
- **F5（用户 E2E）** step 中文化：新增共享 `stepLabel(step)` JS 助手，覆盖全部 16 个 `STEP_HANDLERS` 键（`write-book→续写正文`/`extract→抽取设定`…），未知 id fallback 回 id（新 step 仍可读、不空白）；模态 `steps` 由 `j.step` 改 `stepLabel(j.step)`。本轮只改模态这一 surface；jobs 页/侧栏/toast 的同类中文化属 iter070 已记的"批量命名中文化"大项，仍另起一轮。
- **F6（用户 E2E）** 模态 footer 等宽：新增 `.modal-footer-equal .btn{flex:1 1 0;min-width:0;white-space:nowrap}`（仅作用于 leave-guard 这一三按钮 footer，不动共享 `.modal-footer` 与 delete 模态两按钮）；模态 footer 加 `modal-footer-equal` class，标签缩短（`取消任务并离开→取消并离开`、去掉 leave 按钮的 `（后台继续）` 后缀——"任务后台继续"正文已说明）。

## Acceptance

- 全量单测 `OPENAI_MODEL=mock`（`.venv/bin/python3 -m unittest discover -s tests`）全绿（基线 iter070 = 1324，预期净增新用例）。
- 重点单测 `test_web_routes_get` / 相关 jobs 测试：F1 三 topbar 链接带 guard / F2 `/jobs/active` 端点返回活跃集且不受 recent 截断影响 + 前端 JS 调 `/jobs/active` / F3 模态 JS 含 stay 按钮 focus / F4 `render_index([])` 真渲染中性文案。
- `node --check` 渲染 app.js 语法。
- **前端 E2E（preview MCP，mock，桌面/移动，真实全方位点击）**：F1 任务运行中点「回收站/设置/新建」均弹三选一模态（非仅 ⌂/brand/面包屑）；F2 刚入队 pending（`started_at=None`）+ 多条历史终态时守卫仍能检出活跃；F3 模态出现键盘焦点落「留在本页」、Tab 循环、Esc 关闭；landing/library 无 workspace 时 3 链接不误触；console 无 error/warn。
- 铁律⑨：`/code-review high` + `/security-review` 结论与未修风险回填。
- 铁律⑧：同步 README SOP 表「最近一次更新」时间戳 + AGENT_HANDOFF Phase Status。

## Implementation Notes

6 项（F1-F6）按计划落地，改 4 个源文件 + 2 个测试文件 + 1 个文档订正 + 本迭代新文件。

**关键实现取舍**：
- **F2 用内存真源而非旁路截断**：放弃"前端把 `?n=10` 提到 `?n=50`"的 band-aid（50+ 历史终态时同样会截断刚入队 pending），改用后端 `active_jobs` 直读 `_JOBS`。这把"是否有任务在跑"从"最近列表的副产品"提升为"内存活跃池的一等查询"，逻辑上对（pending 任务入队即在 `_JOBS`），且对 `recent_jobs` 的 4 个消费方零触碰。
- **F2 fail-open 链路双保险**：前端 `checkLeaveGuard` 即使端点已只返活跃，仍保留 `filter(pending|running)`（防未来 shape drift）；fetch 抛错 / 进程重启返回空 → 直接导航不困住用户（沿用 iter070 决策③）。
- **F3 移焦最安全项**：聚焦 `[data-modal-close]`（"留在本页"），而非主操作"回首页/去书架"——误触 Enter 的代价是"留下"而非"离开/取消任务"。未引入完整 focus-trap（与 delete 等既有模态约定一致，避免单模态新机制；记为全局 a11y 债）。
- **F5 共享 `stepLabel` + fallback**：映射覆盖全部 16 个 `STEP_HANDLERS` 键；未知 id 回退到 id 本身（新增后端 step 仍可读、不空白）。本轮只接到模态这一 surface；jobs 页/侧栏/toast 的 raw step 仍在（属 iter070 已登记的"批量命名中文化"大项，单独一轮）。
- **F6 局部 footer 变体**：`.modal-footer-equal` 只作用于 leave-guard 三按钮 footer（`flex:1 1 0` 等宽 + `white-space:nowrap` 单行），共享 `.modal-footer` 与 delete 模态两按钮 footer 字面未动。标签缩短把"后台继续"语义交给正文承担。

**安全自查（铁律①）**：本轮 diff 仅 `src/web/{templates,jobs,routes,static}.py` + `tests/` + `docs/`，未碰 `.env`/`data/`/`小说txt/`；无 `sk-` 串。模态所有插值（`WORKSPACE_NAME`/`stepLabel(j.step)`/`leaveLabel`/`n`）均 `escapeHtml`——`stepLabel` 对未知 id 返回原始 `j.step`，但 `steps` 在 innerHTML 前整体经 `escapeHtml(steps)`，无 XSS 缺口。新路由 `/jobs/active` 复用 `_workspace_error(name)` 做 name 校验，与 `/jobs/recent` 同款。

**aeloon 并行文件**（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）是用户并行操作产物，不并入本轮 commit（铁律⑦）。

## Acceptance Result

- **全量单测（权威）**：`OPENAI_MODEL=mock` `.venv/bin/python3 -m unittest discover -s tests` → **1333 tests OK**（基线 iter070 = 1324，+9 新用例：`ActiveJobsTests` 3 + `test_web_routes_get` 6 个 iter071 用例；重命名 1 个旧用例净增 0）。聚焦集快速回归 8/8 OK。
- **JS 语法**：`node --check`（渲染出的 `/static/app.js`，~160KB）→ **OK**。
- **前端 E2E（preview MCP，web-mock 端口 8765，真实点击 + DOM 取证 + 截图）**：
  - **F1**：`/w/alpha/` 上 ⌂/brand/面包屑首项 + 回收站/设置/新建 6 个出口全部 `data-leave-guard=true`（DOM 实测）；stub `/jobs/active` 返回 1 个活跃 job 后，**真实点击回收站/设置/新建/⌂ 均弹三选一模态且不导航**（`location.pathname` 仍 `/w/alpha/`）。
  - **F2**：守卫实际请求命中 `/api/workspace/alpha/jobs/active`（trace 取证）；恢复真实 fetch（alpha 无活跃任务→`{jobs:[]}`）后点回收站**直达 `/trash` 不弹模态、不困人**；新增单测 `test_pending_with_null_started_at_is_immune_to_recent_truncation` 证明 12 终态 + 1 `started_at=None` pending 时 `recent_jobs?n=10` 漏掉而 `active_jobs` 命中。
  - **F3**：模态出现后 `document.activeElement` = "留在本页"（`focusIsStay=true`）；Esc / 遮罩点击 / 留在本页均关闭。
  - **F5**：模态正文显示「续写正文」「抽取设定」等中文，`write-book` 不再出现（`bodyHasWriteBook=false`）。
  - **F6**：三按钮桌面 1280px 等宽 **138px**、移动 375px 等宽 **87px**、全部单行不换行（截图存证，对比用户原截图的 2 行错位已消除）；⌂ 离开按钮动态显示「回首页」、面包屑出口显示「去书架」。
  - **非 workspace 短路**：`/trash`（`WORKSPACE_NAME=""`）即便 stub 活跃任务，点设置仍**直接导航 `/settings` 不弹模态**（守卫只在 workspace 内生效）。
  - **iter070 回归**：桌面 `.nav-toggle` 仍 `display:none`（死按钮修复未回归）；移动 375px ☰/⋯ 重显 `display:flex`。
  - `preview_console_logs`（warn 级）全程**无 error/warn**。
  - 未实景验证项（诚实记录）：「取消并离开」端到端 cancel POST（需真实 running job；mock job 秒级完成难命中，best-effort cancel + fail-through 导航的接线由 iter070 既验 + 本轮静态保留）。
- **代码审查（铁律⑨）**：`/code-review` 等价的对抗式多视角 workflow（5 agent：正确性 / 安全 / 回归 / 规约 4 独立视角 → HIGH/MEDIUM 逐条对抗式核验 → 综合；244K subagent tokens）→ **0 个 HIGH/MEDIUM/LOW 真问题，仅 7 条非阻塞 NIT，放行可提交**。
  - **四视角一致收敛**，关键事实经对抗式核验：`STEP_LABELS`↔`STEP_HANDLERS` 16 键对齐、`/jobs/active` 注册于 `/jobs/recent` 之后正则不遮蔽、F1 三链接 `data-leave-guard` 落位、F6 CSS scoped 在 `.modal-footer-equal`、前端切到 `/jobs/active`。
  - **安全**（铁律①）：无 ≥MEDIUM 发现；未触碰 `.env`/`data/`/`小说txt/`；模态插值全 `escapeHtml`；`/jobs/active` 复用 `_workspace_error` 校验。
  - **7 条 NIT（全部非本轮新引入 / 已登记，不修）**：① `checkLeaveGuard` 无双击重入保护（与 `showDeleteModal` 等所有内联模态同款，iter070 已登记全局模态债）；② `active_jobs` 整记录直出含 `params`（当前不含凭据、与 `recent_jobs` 暴露面一致，记为"勿往 params 塞敏感值"约束）；③ 数据源分裂（`active_jobs` 读 `_JOBS` / jobs 表读 `recent_jobs`，非回归、守卫语义反更准，recent_jobs 排序修正另起一轮）；④ `active_jobs` docstring 偏长（注释/代码比高，但解释了"为何不复用 recent_jobs"的非显然性，保留）；⑤ 前端 `filter(pending|running)` 冗余二次防御（自承 shape-drift 保险，非 bug）；⑥ F4 docstring 措辞精度（本轮已收：明确命中 `data-empty` 属性）；⑦ `assertNotIn("第一本书")` 守的旧文案全树已不存在（属防旧 novel-only 文案回归的护栏，保留）。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | F1：`_topbar_actions` 的 3 个 base 链接（/trash、/settings、/wizard）各加 `data-leave-guard`（`extra` 透传不动）+ 说明注释 |
| `src/web/jobs.py` | F2：新增 `active_jobs(workspace)`——`_JOBS_LOCK` 下 filter 本 workspace `pending\|running` 快照（零截断/零排序/零回归，附长注释解释为何不复用 recent_jobs） |
| `src/web/routes.py` | F2：新增 `api_workspace_active_jobs(name)`（复用 `_workspace_error`）+ 路由 `GET /api/workspace/{name}/jobs/active`（紧邻 `/jobs/recent` 注册） |
| `src/web/static.py` | F2：`checkLeaveGuard` `wsUrl("/jobs/recent?n=10")`→`wsUrl("/jobs/active")`；F3：`showLeaveGuardModal` 取 `stayBtn=[data-modal-close]` + `setTimeout(stayBtn.focus,0)`；F5：新增 `STEP_LABELS`+`stepLabel()`，`steps` 用 `stepLabel(j.step)`；F6：CSS 新增 `.modal-footer-equal .btn{flex:1 1 0;min-width:0;white-space:nowrap}`，footer 加 `modal-footer-equal` class + 标签缩短（取消并离开 / 去 `（后台继续）` 后缀） |
| `tests/test_web_jobs_recent.py` | 新增 `ActiveJobsTests` 3 用例（本 workspace pending+running 过滤 / 截断免疫回归 / 重启 fail-open 空） |
| `tests/test_web_routes_get.py` | 加 `jobs`+`templates` import；旧 `test_iter070_library_empty_hint_is_type_neutral` 改名 `..._populated_shelf_has_no_epub_copy` 并诚实化 docstring；新增 6：空书架真测 / topbar guard / 前端用 active 端点+focus / active 路由 / step 中文化 / footer 等宽 |
| `docs/iterations/iteration_070_home_nav_leave_guard.md` | F4：订正第 55 行"空书架文案由 assertNotIn 覆盖"的过度宣称，指向 iter071 真测 |

## 不在本轮范围

- **全局模态去重 helper**（消除双击叠加模态 + 中途导航残留 keydown 监听的 iter070 既存小债）——属全局重构，非本轮单一新模态责任，沿用 iter070 结论。
- **完整 focus-trap**（Tab 真正环回模态内 + 焦点恢复到触发元素）——本仓库所有内联模态均无完整 trap，单独为 leave-guard 引入会与既有不一致；F3 只做「移焦进模态」最小修复对齐 delete 模态。本轮记为全局 a11y 债。
- **`recent_jobs` 排序修正**（让 pending 在通用列表也排前）——会波及 4 个消费方展示顺序，且 F2 已用 `active_jobs` 旁路解决守卫的真实需求，排序修正属独立 UX 判断，不在本轮。
- iter070「不在本轮范围」沿用项：`debate --force` CLI 文案泄漏 / 复制按钮非安全上下文降级 / 批量命名中文化 / 书架类型筛选分组。

## Notes

- 本轮是 iter070 的 residual 收口，承接 codex 复审。4 项同源，单轮一次性收掉守卫的「覆盖洞（F1）+ 数据源洞（F2）+ a11y（F3）+ 测试诚实度（F4）」。
- F2 的关键非显然事实：每 workspace 至多 1 个活跃任务（`_WORKSPACE_JOBS` 槽 + 409），故 `active_jobs` 返回 list 但实际 0 或 1 个；保留 list 形状是为对齐 `/jobs/recent` 的 `{jobs:[...]}` 契约、前端 filter 逻辑零改。
- F2 fail-open 语义：进程重启 / fetch 失败 → 守卫放行不困住用户（沿用 iter070 决策③：不加 beforeunload，守卫只为诚实告知 + 顺手取消）。
- **aeloon 并行文件**（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）是用户并行操作产物，**不并入本轮 commit**（铁律⑦）。
