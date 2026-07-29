# Iteration 155 - 小说 Web Phase D 单章续写主流程重构

## Context

iter152 已形成小说 Web UI/UX 规范，iter153 已落地浅色设计系统、中文安全文案与共享组件，iter154 已完成五个公共页面。当前五个小说工作区主流程页面仍需生产级重构，以便用户从作品概览进入四阶段工作台、恢复持久任务、筛选与编辑章节，并在异常与窄屏环境中安全继续。本轮只实施 Phase D，保持后端四阶段、任务状态机、付费确认、编辑保护与小说/短剧隔离。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md`, `docs/iterations/iteration_153_novel_web_light_design_system_components.md`, `docs/iterations/iteration_154_novel_web_public_pages_phase_c.md`, `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/jobs.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_server.py`, `tests/test_web_ui_design_system.py`, `tests/test_workbench_e2e.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/jobs.py`, `tests/test_web_phase_d.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_ui_design_system.py`, `tests/test_workbench_e2e.py`, `docs/iterations/iteration_155_novel_web_phase_d_single_chapter_flow.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、私有 `workspaces/`、`data/`、`outputs/`、`logs/`、用户未跟踪文件、后端 API、小说流水线、任务状态机、Phase E 页面内容布局或短剧生产页面视觉；不调用真实文本、图片、视频、TTS 或任何计费服务。

1. 复用 iter153 的 `ui-novel`、集中中文安全投影和共享按钮、状态、表单、toast、确认、导航及阶段卡，重构作品概览、四阶段工作台、章节列表、章节详情和任务记录。
2. 保持现有路由、endpoint、字段、DOM hook、`data-ui-*`、兼容选择器、readiness、任务取消/恢复、`data-leave-guard`、自动保存与逐次计费确认；不伪造新阶段或后端能力。
3. 收紧动态章节、检查与任务公开投影，未知状态统一为“状态待确认”，路径、内部枚举、原始异常、未知对象和敏感技术细节不得进入用户页面。
4. 新增聚焦测试与静态检查，覆盖五页共享组件、导航唯一性、44px、四阶段、离页继续/持久恢复、编辑保护、busy 防重入、Paid 逐次确认和 workspace 类型隔离。
5. 使用 isolated synthetic workspace 与真实本地浏览器覆盖五页及 `1440×1024`、`1199×900`、`390×844`，走通概览→工作台、mock 任务→离页恢复、章节筛选/打开、续写编辑保存、未保存离开保护、原文只读和任务取消/安全恢复。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五页信息架构与既有路由/API/字段/DOM hook，四阶段事实、readiness、持久任务恢复/取消、编辑自动保存和离开保护、Paid 逐次确认、busy 防重入及小说/短剧隔离均不回归。
- `security_boundary`: 核对章节、检查和任务动态数据均经严格白名单安全投影，未知状态失败关闭，且路径、内部枚举、原始异常、stdout/stderr、请求头、完整 prompt、供应方响应、签名 URL 和未知对象不会进入页面。
- `extra_risk_view`: `Web/UIUX/响应式：核对三视口的信息层级、四阶段引导、390px 卡片/编辑器、44px 目标、焦点和 Tab 顺序、唯一当前导航、toast/modal 层级及 sticky/fixed 遮挡；任务持久恢复与计费入口另作风险复核`

- A155-01：作品概览首屏回答可否继续、最近完成/保存内容与下一步，最近章节可打开，旧结果失效有中文说明，类型不匹配失败关闭。
- A155-02：工作台严格保持准备设定、生成大纲、生成细纲、撰写正文四阶段；每卡一个主操作，已保存章节只提供打开，过期结果不自动覆盖，处理中可离页并从持久任务恢复。
- A155-03：章节列表显示标题、文字来源、状态、更新时间和主要操作；搜索/来源筛选/排序与空结果清除清楚，390px 可读且原文只读、续写可编辑。
- A155-04：章节详情区分正文、编辑、内容检查、文字检查、文风、建议与保存记录；保存四态、失败保留输入和重试、原文只读、续写自动保存及 `data-leave-guard` 语义正确，不新增删除能力。
- A155-05：任务记录按全部、处理中、已完成、需要处理筛选；持久状态为恢复真源，unknown/lost 只显示“状态待确认”和刷新，不自动重启，取消与 Paid 重试语义保持。
- A155-06：动态状态/错误/路径/未知对象安全投影与 workspace 类型隔离通过；用户页无禁止技术词、内部状态码、文件路径、原始异常或未知 JSON。
- A155-07：五页使用 `ui-novel` 与 iter153 共享组件；三视口无横向溢出或遮挡，当前导航唯一不可重复点击，所有可见目标至少 44×44px，核心操作、焦点、toast 和确认窗口在手机端可用。
- A155-08：聚焦测试与静态检查通过；correctness/behavior、security/boundary、Web/UIUX/响应式至少三个独立只读审查无未修 P1/P2，findings 修复后聚焦回归通过。
- A155-09：真实本地浏览器完成规定十项 synthetic/mock 操作且控制台无错误，证据等级仅为 `local-e2e`；公共页面和短剧页面回归不受影响。
- A155-10：implementation commit 上最终一次 `bash scripts/verify.sh` 通过，工程验收等级为 `mock-functional`；回填结果并创建 docs-only 收官提交，不调用真实 provider、不 push，用户已有索引/计划/体检报告及其他改动均保留。

## Implementation Notes

- 用户点名的 `src/web/workbench.py` 在当前仓库不存在；工作台行为实际位于 `src/web/routes.py`、`src/web/templates.py`、`src/web/static.py` 与 `src/web/jobs.py`，本轮按代码事实源实施，不为满足文件名新造平行模块。
- 五页继续使用 iter153 的 `ui-novel`、shell、导航、按钮、状态 badge、表单、toast、modal 与阶段卡；短剧任务页保留 legacy 分支，没有建立第二套小说私有组件。
- 工作台仍以服务端四阶段和持久任务为事实源；正文动作先请求 readiness，完成态只显示“打开章节”，运行态从 `/jobs/active` 投影，四个阶段表单统一设置 `aria-busy`。
- 章节详情补齐“继续编辑 / 放弃修改 / 保存并离开”三选项；保存失败保留输入，正文已保存但检查任务未启动时明确区分两种结果。
- correctness 审查发现侧栏离开保护、完成态生成按钮、readiness、最近章节、类型隔离与表单 busy 缺口；security 审查发现 review/meta 数值回显和 jobs unknown 类型缺口；Web/UIUX 审查发现任务空筛选、检查启动误报、空正文状态与阶段文案问题。主线程逐条复核后全部修复，并追加安全数值投影、空态委托和 `[hidden]` 规则。
- 聚焦回归为 176 项，通过 Python/JavaScript 语法、agent harness 与 `git diff --check`。真实 Chromium 在 `1440×1024`、`1199×900`、`390×844` 覆盖五页：15 个页面/视口组合均 `overflow=0`、唯一当前导航、可见交互目标均至少 44×44px，控制台 0 error/0 warning。
- 浏览器走通概览→工作台、四阶段、mock Paid 确认与任务记录恢复、章节筛选/打开、续写编辑保存、未保存三选项与焦点恢复、原文章节只读、失败任务安全重试入口；所有数据来自 isolated synthetic workspace。

## Acceptance Result

最终 canonical `verify.sh` 待 implementation commit 后唯一一次执行并回填；A155-01 至 A155-09 的实现、聚焦验证、三视角审查与 `local-e2e` 浏览器证据已完成，无未修 P1/P2。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮 findings 均属于 Phase D 页面实现与既有安全/工作流规则的具体落实，没有产生超出 AGENTS、UI/UX 规范或现有 workflow 的新长期规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 重构 Phase D 五页 IA、共享导航文案、最近章节、四阶段完成态、章节/任务卡和编辑保护 hook。 |
| `src/web/static.py` | 扩展安全状态映射、响应式卡片、readiness/busy、持久任务恢复、章节筛选/保存/离开保护与严格动态投影。 |
| `src/web/routes.py` | 任务页对损坏或未知 workspace 类型失败关闭。 |
| `tests/test_web_phase_d.py` | 新增 Phase D 页面、共享组件、状态、安全、恢复、保护与响应式契约。 |
| `tests/test_web_routes_get.py`、`tests/test_web_ui_design_system.py`、`tests/test_workbench_e2e.py` | 更新路由、状态文案、短剧兼容和工作台回归断言。 |
| `docs/iterations/iteration_155_novel_web_phase_d_single_chapter_flow.md`、`docs/iterations/README.md` | 建立并索引本轮审计记录。 |

## 不在本轮范围

- Phase E 的批量续写、故事规划、搜索、内容检查、创作数据页面与旧选择器清理。
- 后端 API、小说流水线、任务状态机及无现有契约的章节删除、检查项处理、自由文本写作要求。
- 短剧生产页面视觉与真实文本、图片、视频、TTS、计费/provider 验证。

## Notes

- Figma 为视觉与交互事实源之一；生产行为继续以代码、测试和 UI/UX 规范为准，原则上不修改 Figma。
- 浏览器证据最高只记为 `local-e2e`，mock 工程证据不能外推为真实 provider 验证。
