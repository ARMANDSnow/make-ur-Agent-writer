# Iteration 070 - 首页导航重设计（⌂→首页 + 离开守卫）+ 桌面死按钮修复 + 三入口平等 + 书架接缝收口

## Context

用户在 iter069 收官后继续实测前端，报告 4 类导航/入口痛点（先用 4 个只读 subagent 做全前端 UX 审计核实，再与用户逐项讨论定方向）：

1. **回不去首页**：真正的首页是 landing 页 `/`（`render_landing()`，hero + 三入口卡），但应用内**没有任何入口指向它**——⌂、侧栏 brand、面包屑首项全部指 `/library`（书架）。iter069 曾按"决策 A"把 ⌂ 留在 `/library`、把「⌂→首页」列为不在范围；本轮落地它（方案 B）。
2. **桌面端 ☰/⋯ 是死按钮**：`static.py:288` 的 `.nav-toggle,.topbar-menu-toggle{display:none}` 被 `static.py:313` `.btn{display:inline-flex}` 以**同特异性 (0,1,0) + 更晚源顺序**覆盖，桌面端 ☰（汉堡）和 ⋯（页面操作）仍显示却点了无可见反馈。iter069 lp-chrome 注释里"桌面端 ⋯ 已被 :288 隐藏"的假设不成立——这正是本 bug。
3. **三入口不平等**：首页"导入续写"卡跳裸 `/wizard`（要再选一次类型），而短剧/开新书卡直达 `?type=drama`/`?type=premise`。`/wizard?type=novel` 前端早已支持。
4. **书架接缝**：书架混装 novel(含 premise) + drama 两类（卡片已有类型徽章 + 按类型分流，**合理保留**），但空状态文案是 novel-only（"上传 epub/txt""第一本书"），且短剧徽章与运行态徽章撞色。

**3 项用户决策**（AskUserQuestion 定）：① 离开守卫**给三选一**（任务后端独立线程跑、离开不中断它——诚实告知；回首页/取消任务/留下）；② **⌂ 改指首页**（brand+面包屑保留指书架）；③ 守卫**仅应用内导航**（不加 beforeunload，关标签页/刷新不拦）。书架按 **option A**（保持单一书架，只收文案/徽章接缝，不拆分、不加筛选）。计划档 `~/.claude/plans/a-iter070-radiant-wind.md`。

## Plan

仅改 `src/web/templates.py` + `src/web/static.py` + `tests/test_web_routes_get.py`，纯前端展示层，不动 9 阶段管线。

- **任务1** ⌂→首页 + 离开守卫：⌂ href `/library`→`/`、aria「返回书架」→「回首页」+ `data-leave-guard`；brand/面包屑首项加 `data-leave-guard`（各自保留 href）；新 `ensureLeaveGuardDelegate`（文档级委托，挂 `initShellControls` 末尾）：点 `[data-leave-guard]` 链接**同步 preventDefault** → 异步查 `/jobs/recent` → 有 `pending/running` 任务则弹三选一模态 `showLeaveGuardModal`（复用 `showDeleteModal` 结构 + `ensureJobCancelDelegate` cancel 调用 + `setPendingToastAndNavigate`）。
- **任务2** CSS 候选 A：把 `.nav-toggle,.topbar-menu-toggle{display:none}` 从 topbar 块顶部移到 `.btn` 规则之后，特异性不变 (0,1,0)、靠源顺序赢 `.btn`；不碰移动端重显/no-context/lp-chrome；更新 lp-chrome 过时注释。
- **任务3** 导入续写卡 `/wizard`→`/wizard?type=novel`（hero「开始创作」保持裸 `/wizard`）。
- **任务4** option A：空状态文案中性化（去 epub/txt、第一本书）；`.badge-drama` 边框 `--amber-soft`→`--amber` + typeBadge drama 加 `🎬` 前缀（消与 `.badge.running/.pending` 撞色）。

## Acceptance

- 全量单测 `OPENAI_MODEL=mock`（`.venv/bin/python3 -m unittest discover -s tests`）全绿（基线 iter069 = 1319）。
- 重点单测 `test_web_routes_get`：home-btn `href="/"`+guard / 三卡 type 对齐 / 空态无 epub / leave-guard JS 存在 + `pending|running` 过滤 + `🎬` / drama 徽章 `--amber` 边框 / 面包屑首项 guard。
- `node --check` 渲染 app.js 语法（Python 单测抓不到 JS 语法错）。
- 前端 E2E（preview MCP，mock，桌面/移动）：桌面 ☰/⋯ 隐藏·⌂ 显示；移动端 ☰/⋯ 重显；leave-guard 拦截 + 三选一模态；三入口直达；landing 短路不误触；console 无报错。
- 铁律⑨：`/code-review high` + `/security-review` 结论与未修风险回填。

## Implementation Notes

4 任务按计划落地，5 处 templates.py 编辑 + 8 处 static.py 编辑（CSS 4 + JS 4）+ 测试更新 1 改 5 增。

**两个实现坑（计划阶段预判、实现时严格规避）**：
1. **异步 preventDefault**：拦的是 `<a>`，`ev.preventDefault()` 必须**同步**先执行再 async 查 `/jobs/recent`，否则 await 期间浏览器已开始跳转。修饰键/中键点击放行（保留"新标签页打开"）。
2. **`historicalJobStatus` 漏 `succeeded`**（探索阶段发现：`static.py` 的 terminal 集合缺 `succeeded`，与后端 `jobs.py:61` `TERMINAL_STATUSES` 不一致）→ 守卫**显式只认 `status==="pending"||"running"`**，**不复用** `historicalJobStatus`，否则刚成功的 job 会被误判为活跃而错误拦截。

**CSS 候选 A vs B 取舍**：候选 B（基础 + 移动重显都提到 (0,2,0) 加 `.topbar` 前缀）会牵动移动重显/no-context/lp-chrome 共 4 组规则——"媒体查询不增特异性"导致移动重显必须跟着升特异性才不消失，回归面大。候选 A 只动 1 行、特异性全程 (0,1,0)、移动逻辑字面未变，破坏面最小，故选 A。

**cancel best-effort**：job 可能在"检测到活跃"与"点取消"之间已自然终止，cancel 端点（`routes.py:2156`）会 409 → `Promise.all` 内每个 cancel `.catch(()=>{})` 吞掉、照常 `setPendingToastAndNavigate` 导航（用户意图是离开）。fetch 失败 fail-open（直接导航不困住用户）。

**aeloon 并行文件**（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）是用户并行操作产物，**不并入本轮 commit**（铁律⑦）。

## Acceptance Result

- **全量单测（权威）**：`OPENAI_MODEL=mock` `.venv/bin/python3 -m unittest discover -s tests` → **1324 tests OK**（基线 1319 +5 新 iter070 用例，无净增模块）。聚焦集 `test_web_routes_get` → **69 OK**（原 64 +5）。
- **JS 语法**：`node --check`（渲染出的 `/static/app.js`，159046 bytes）→ **OK**（leave-guard 新增 JS 无语法错）。
- **CSS 落地校验**：渲染 `/static/app.css` 程序化核对——死按钮隐藏规则全文件**唯一**、位置在 `.btn{` **之后**（源序胜出）、旧位置已删、`.badge-drama` 边框 = `var(--amber)`。
- **前端 E2E（preview MCP，mock，web-mock 端口 8765）**：
  - **任务2**：桌面 1280px → `.nav-toggle`/`.topbar-menu-toggle` computed `display:none`、`.home-btn` `display:flex`（截图证桌面顶栏只剩 ⌂+面包屑+内联 actions，☰/⋯ 消失）；移动 375px → ☰/⋯ 重显 `display:flex`（响应式跨断点正确）。
  - **任务1**：workspace 页 stub `/jobs/recent` 返回 1 个 `running` job → 程序化点 ⌂ → **被同步拦截不跳转**（`location.pathname` 仍 `/w/longzu/`），弹三选一模态：标题「当前作品有任务正在运行」、正文含「离开本页不会停止它们」、按钮 ["留在本页","取消任务并离开","回首页（后台继续）"]（截图存证）；`window.WORKSPACE_NAME=""` 在 landing/library 上短路不误触（核实）。
  - **任务3**：landing 三卡 footer href = `/wizard?type=novel` / `?type=drama` / `?type=premise`（**三入口对等**）；hero「开始创作」保持裸 `/wizard`、「打开已有作品」→`/library`（正确保留）。
  - `preview_console_logs`（warn 级）全程**无 error/warn**。
  - 未能实景验证项（诚实记录）：drama 徽章 🎬+边框（本机无 drama workspace，由静态 JS/CSS 测试覆盖）；空书架文案（本机有 3 个 workspace 非空）；cancel-and-leave 端到端（需真实 running job，模态渲染 + cancel 调用已分别静态验证）。
    - **iter071 (codex F4) 订正**：原文此处曾称空书架文案「由 `assertNotIn("epub")` 测试覆盖」，**过度宣称**——`test_iter070_library_empty_hint_is_type_neutral` 命中带 fixture 的 `/library`，`names` 非空、空状态文案根本不渲染，该断言只是空跑通过（仅能护栏「非空书架不泄漏 epub」）。真正的空书架文案覆盖由 iter071 新增的 `test_iter071_empty_shelf_renders_neutral_hint`（直渲 `render_index([])`）补齐。
- **代码审查（铁律⑨）**：
  - `/code-review high`（3 独立 finder：逐行正确性 / 移除行为+跨文件 / 复用-简化-效率-高度-规约）→ **0 个需修 bug、0 规则违反、0 达标简化项**。三 finder 一致核实：⌂ 改向后书架仍可达（brand+面包屑）、aria 同步、CSS 移位源序正确、`pending|running` 正确排除 succeeded、escapeHtml/fail-open/409 吞掉/ESC·遮罩关闭均健全、`_crumbs` 仅 guard `/library` 首项（landing 首项无 href 安全跳过）、`ensureLeaveGuardDelegate` 与既有 `ensureJobCancelDelegate`/`bindCtaActions` 委托范式一致、测试断言逐字符匹配渲染。**仅 2 个可忽略边角**（双击叠加模态 / 中途导航残留 keydown 监听）——与既有 `showDeleteModal` 等模态**同款特性**、属现状约定，按铁律⑦不扩 scope 修，记为既存小债。合规：无铁律违反（无龙族原文、测试全 mock、仅 3 文件未扩散）。
  - `/security-review`（对口铁律①）→ **无 ≥MEDIUM 安全发现**。核实：模态 `innerHTML` 全部插值（`window.WORKSPACE_NAME`/`steps`(job.step)/`leaveLabel`/`n`）经 `escapeHtml` 转义、与 `showDeleteModal` 约定一致；`window.location.href=href` 的 href 来自我们自有静态模板串（`/`、`/library`），非用户可控、无开放重定向；cancel 用的 `job_id` 来自后端 + 路由 `[a-f0-9]{32}` 校验兜底；`job.step` 来自后端常量枚举（`STEP_HANDLERS`）。本项目为 stdlib `string.Template`（非 Jinja2），workspace 名受后端 `WORKSPACE_NAME_HTML_PATTERN` 约束 + 模态内再 escapeHtml，无 XSS。
- **未修风险**（诚实登记，铁律⑦）：leave-guard 模态与既有所有内联模态共享两个可忽略特性——(a) 极快双击同一 guard 链接会叠两个模态（都能 ESC/导航关闭）、(b) 中途导航走它路时该模态的 document keydown 监听到下个页面 unload 才 GC。两者在 `showDeleteModal`/purge/partial 模态中同样存在，是本仓库"每模态各写内联、无通用 helper"约定的固有属性；本轮不为单一新模态引入新机制（避免与既有不一致），留作全局模态重构债。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | ⌂ href `/library`→`/` + aria「回首页」+ `data-leave-guard`（:70）；brand 加 `data-leave-guard`（:191）；`_crumbs` 首项（i==0 有 href）加 `data-leave-guard`（:240-250）；空状态 `empty_hint` 去 epub/txt 中性化（:260）；导入续写卡 `/wizard`→`/wizard?type=novel`（:1365） |
| `src/web/static.py` | CSS：`.nav-toggle,.topbar-menu-toggle{display:none}` 从 topbar 块顶移到 `.btn` 之后（源序修死按钮）+ lp-chrome 注释更新 + `.badge-drama` 边框 `--amber-soft`→`--amber`；JS：新增 `ensureLeaveGuardDelegate`/`checkLeaveGuard`/`showLeaveGuardModal` 三函数（文档级委托 + 同步 preventDefault + `pending\|running` 活跃判定 + 三选一模态复用 showDeleteModal 结构 + cancel best-effort 409 吞掉 + fail-open）+ `initShellControls` 末尾调用 + emptyState body 文案中性化 + typeBadge drama 加 `🎬` |
| `tests/test_web_routes_get.py` | `test_shell_has_topbar_home_button` 改断言 home-btn `href="/"`+guard；新增 5：`test_iter070_landing_import_card_carries_type`（三卡 type）/ `_library_empty_hint_is_type_neutral`（无 epub）/ `_workspace_shell_marks_leave_guard_exits`（⌂/brand/首项三触点）/ `_static_js_has_leave_guard`（委托+模态+`pending\|running`+🎬）/ `_static_css_drama_badge_border`（`--amber` 边框） |

## 不在本轮范围

- **`debate --force` CLI 文案泄漏**（`static.py` 警告框给 Web 用户看不可执行的命令）——需配套确认 Web 内「重新生成大纲」动作，独立处理更稳。
- **复制按钮非安全上下文降级**（局域网 HTTP 访问时 `navigator.clipboard` 静默失效）——独立健壮性修复。
- **批量命名中文化**（`workspace→作品`、章节表/统计表英文表头 `verdict/review/rewrite/agents/job_id/...` 中译、`approve/reject` 徽章值中译、短剧"续写"用词收口）——面广、要逐个核对可见性，单独一轮更稳。
- **书架类型筛选/分组**（option B/C）——当前作品量小，暂不需要。
- **全局模态去重 helper**（消除双击叠加 + keydown 残留的既存小债）——属全局重构，非本轮单一新模态的责任。

## Notes

- 本轮承接 iter069 明确推迟的"方案 B（⌂→首页）"。iter069 当时按决策 A 的理由是"全站面包屑无一处指向首页、交给面包屑回首页是空承诺"；本轮直接给 ⌂ 一个回首页入口、并补上 brand+面包屑回书架，两条家路（首页 vs 书架）分工清晰，顺带消解了 iter069 审计指出的"回书架 4 重冗余入口"中的一重。
- 关键非显然事实（讨论阶段向用户澄清）：续写任务是**后端独立线程跑、离开页面不中断**（`jobs.py:957`），取消是协作式 checkpoint 标志（`jobs.py:197`）非强杀。故"离开守卫"的提示本质是诚实告知 + 给"顺手取消"的选项，而非"离开会停任务"。
- 书架审查结论：混装 novel+drama **不算反人性**（卡片已有类型徽章 + 按类型分流概览/侧栏），真正硌人的是 3 处接缝（首页摆 3 产品却塌成 1 堆 / drama 是 Beta 异构线 / 空状态 novel-only 文案）。本轮 option A 收掉其中"空状态文案 + 徽章撞色"两项；"首页↔书架框架断点"留作产品判断（未拆分）。
- preview 工具备注：`preview_resize` 的 "desktop" preset 在本环境复位成窄原生视口（316px，落进移动断点），必须显式 `width:1280` 才测得到桌面行为——一度误读为"桌面端死按钮没修好"，显式设宽后确认正确。
