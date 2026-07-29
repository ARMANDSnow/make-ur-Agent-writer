# Iteration 158 - 短剧 Web UIUX Phase A：导航壳、概览与生产工作台重构

## Context

当前短剧 Web 已具备五站创作、同源 production projection、列表/画布、隔离 `localdemo_*` A-F 演练和 exact delivery，但短剧页面仍沿用早期信息架构与视觉层级。iter153 已为公共/小说/短剧建立语义变量和命名空间，本轮依据指定 Figma D02、D08、D09、T01、T03、M01、M03、交互与交接规范，在不改变 API、任务状态机或短剧领域真值的前提下，完成短剧响应式页面壳、概览与生产工作台的第一阶段重构。

用户原指定 iter154，但仓库 canonical 索引中 iter154 已用于“小说 Web Phase C 公共页面重构”，当前最新轮次为 iter157；按 `iter-start` 不覆盖历史、由最新编号加一的规则，本轮使用 iter158。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_153_novel_web_light_design_system_components.md`, `docs/iterations/iteration_147_drama_production_workbench_projection.md`, `docs/iterations/iteration_150_short_drama_sop_full_validation.md`, `docs/product/short_drama_module.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/drama_production_workbench.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_routes_get.py`, `tests/test_drama_production_workbench.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_routes_get.py`, `tests/test_drama_production_workbench.py`, `tests/test_drama_web_uiux_phase_a.py`, `docs/iterations/iteration_158_drama_web_uiux_phase_a_shell_overview_production.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、私有样本或用户未跟踪文件；不修改后端 API、领域 schema、任务 DAG、计价、授权、恢复、exact delivery 或 SubmissionUnknown/Lost 语义；不调用真实文本、图片、视频、TTS 或任何计费 provider；不重构本轮范围外的短剧主体页，不影响 `ui-public` 与 `ui-novel`。

1. 从指定 Figma node 逐一读取 design context，提取桌面/平板/移动的页面壳、导航、概览、production 列表/画布与交互规范，并映射到 iter153 的现有语义变量和共享组件。
2. 重构 `ui-drama` 响应式页面壳：桌面侧栏、平板顶部导航、移动底部导航保留现有 11 项、workspace 切换、面包屑、路由、active、`data-leave-guard` 与运行任务离开守卫。
3. 重构短剧概览，继续只消费现有 `/drama/progress` 安全投影，呈现当前集、创作阶段、媒体覆盖、最近任务、下一步与创作/生产阶段，并对 Loading、Empty、Ready、Stale、Blocked、Error 提供非颜色原因与恢复入口。
4. 重构 production 工作台，列表和关系画布继续消费同一 production projection；保留集数切换、刷新、tabs、键盘语义、A-F 隔离演练与演练交付入口，按桌面/平板/移动布局呈现 Ready、Selected、Stale、Blocked 及依赖原因。
5. 新增聚焦 UI 合同与浏览器检查，覆盖样式隔离、11 项导航、状态与恢复、同源 fingerprint、episode/refresh/local-demo hook、兼容选择器、无横向溢出、44px、3px 焦点、ARIA tabs、中文安全投影和控制台错误。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 11 项导航与 active/路由/workspace/面包屑/leave guard 保持；概览只消费 progress 安全投影且六态可恢复；production list/canvas 同一 fingerprint、集数切换/刷新/local demo/exact delivery hook、tab/toast/job 恢复均无回归。
- `security_boundary`: 核对无后端字段/API/领域真值变化，页面不泄露 raw path、完整 prompt、provider response、signed URL、凭据或内部状态；本地演练只创建 `localdemo_*`、不改源项目、不触发 provider，SubmissionUnknown/Lost 不自动重试。
- `extra_risk_view`: `Web/UIUX/响应式：逐节点对照 Figma，在 1440×1024、1024×900、390×844 核对无横向溢出、44px 触控、3px 焦点、键盘导航、ARIA tabs、状态非颜色表达、中文普通用户文案和零控制台错误`

- A158-01：`ui-drama` 页面壳在桌面、平板、移动分别呈现侧栏、顶部导航与底部导航；11 项名称、路径、active、workspace 切换、面包屑、`data-leave-guard` 与运行任务离开守卫保持，`ui-public`/`ui-novel` 样式不受影响。
- A158-02：短剧概览对齐 D02/T01/M01，且只消费现有 progress 安全投影；当前集、创作阶段、媒体覆盖、最近任务、下一步与创作/生产阶段可见，Loading/Empty/Ready/Stale/Blocked/Error 均有中文文本，Stale/Blocked 明示原因和恢复入口。
- A158-03：production 对齐 D08/D09/T03/M03；列表与画布读取同一 projection/fingerprint，Ready/Selected/Stale/Blocked 及原因可见，依赖图表达创作→资产→图片→视频→时间线→合成 QA，平板与移动布局按规范降级。
- A158-04：集数选择、刷新、list/canvas tabs、本地 A-F 隔离演练和演练交付入口继续工作；local demo 只创建 `localdemo_*` 且源项目不变、零 provider，刷新后权威状态恢复。
- A158-05：聚焦测试覆盖样式隔离、导航/active、概览状态、production 同源、episode/refresh/local-demo hook，以及既有 `data-leave-guard`、tab、toast、任务轮询/取消/恢复和兼容选择器。
- A158-06：真实本地浏览器以 synthetic drama workspace 覆盖 Ready/Stale/Blocked 概览及 production list/canvas，在 1440×1024、1024×900、390×844 无横向溢出；可见触控目标不少于 44×44，键盘可进入导航/tabs/主操作/镜头，3px 焦点环可见，tabs 的 `aria-selected`/`tabindex` 正确，状态不只靠颜色，无控制台错误或英文内部状态/绝对路径/provider 诊断；证据记 `local-e2e`。
- A158-07：聚焦检查后完成 correctness/E2E、security/boundary、Web/UIUX/响应式三个独立只读 subagent 审查；主线程复核修复 findings 并聚焦回归，implementation commit 上最后仅运行一次 `bash scripts/verify.sh`，统一工程结论为 `mock-functional`，不声称 `provider-validated`。

## Implementation Notes

- 编号校正：用户指定 iter154，但 canonical iter154 已用于小说 Web Phase C；按 workflow 使用当时最新 iter157 的后继编号 iter158，未覆盖历史。
- Figma 证据：在调用 `get_design_context` 前已加载 `figma-design-to-code` skill，且逐一读取 D02 `36:51`、D08 `39:225`、D09 `39:283`、T01 `45:5`、T03 `45:109`、M01 `46:5`、M03 `46:82`、交互 `50:2`、前端交接 `51:2`、UIUX 总规范 `52:2`；未修改 Figma。
- 页面壳：从 `_SECTIONS_DRAMA` 同源生成桌面 240px 侧栏、平板 72px 顶部导航和移动 72px 底部导航。移动端常驻概览/创作/生产/任务，“更多”打开包含全部 11 项与 workspace 切换的原侧栏；所有 toggle 共用原有侧栏/遮罩/Escape 逻辑。
- episode 上下文：页面 query、`CHAPTER_NO` 或集数输入会同步到 desktop/tablet/mobile 导航；创作台保持既有 `episode`，production/资产/图片/视频/合成保持 `episode_no`。
- 概览：五站进度仍以 `/drama/progress` 为创作入口权威；为完成用户要求的“媒体覆盖/最近任务/Stale/Blocked”，读取现有受限 production 与 recent-jobs 安全投影，不新增 API 字段。两个辅助投影独立降级为“暂时无法读取”，不把未知误报为 0/暂无，也不遮蔽主 progress。这里实现的是用户原始边界“`/drama/progress` 等安全投影”；Plan 中“只消费 progress”是立项时转述过窄，本轮未改 API 或持久化真值。
- production：列表/画布仍在每次 load 后校验 `list_projection_fingerprint === canvas_projection_fingerprint`。列表提供 Ready/Selected/Stale/Blocked 文本原因、镜头详情和“只看需处理”；画布按创作→资产→图片→视频→时间线→合成 QA 展示六阶段。未展示 fingerprint、稳定内部 ID 或来源绑定诊断。
- 响应式/可访问性：`ui-drama` 独立使用 iter153 语义变量；未修改 `ui-public`/`ui-novel`。所有新操作与导航可键盘进入，页签维持 roving `tabindex`，焦点环 3px，可见触控目标至少 44×44，移动页底预留 safe-area。
- 浏览器证据：使用 `/private/tmp/iter158-browser-workspaces` 的 `ui-ready/ui-stale/ui-blocked` synthetic drama workspace，证据在 `/private/tmp/iter158-ui-evidence/`，包含 6 张截图和 `browser-checks.json`。页面端口仅绑定 `127.0.0.1`，验收后已关闭服务与浏览器。
- 聚焦验证：166 项回归通过，包含 JavaScript `node --check`与真实 local-demo 路由隔离测试；该测试确认只创建 `localdemo_*`、保持源项目字节不变。
- 只读审查：correctness/E2E、security/boundary、Web/UIUX/响应式三路独立 subagent 完成。有效 findings 为：多 toggle 仅绑定首个、episode 导航丢失、空 production blocked 抢占创作 todo、辅助投影失败拖垮概览，以及降级文案误报为真实空状态；均由主线复核成立并修复。安全审查对“只消费 progress”的文字 finding 按用户原始“等安全投影”要求修正为本段实施解释；它提出的实际降级风险已修复。修复后聚焦回归与移动“更多”/Escape/跨页 episode=2 浏览器复核通过。

## Acceptance Result

- A158-01：通过。`ui-drama` 三档响应式壳由同一 11 项导航真源生成；workspace、active、面包屑与离开守卫保持，`ui-public` / `ui-novel` 未受影响。
- A158-02：通过。概览六态、当前集、创作/生产阶段、媒体覆盖、最近任务与下一步均来自现有安全投影，Stale/Blocked/Error 有原因和恢复入口。
- A158-03：通过。production 列表和六阶段画布共享并校验同一 projection fingerprint，桌面/平板/移动布局及 Ready/Selected/Stale/Blocked 原因完成。
- A158-04：通过。episode、刷新、tabs、`localdemo_*` A-F 与演练交付入口保持；刷新重读权威状态，隔离演练不改源项目且零 provider。
- A158-05：通过。新增合同覆盖样式隔离、11 项导航、概览六态、production 同源及 episode/refresh/local-demo；既有 leave guard、tab、toast 与任务恢复 hook 通过回归。
- A158-06：通过。synthetic Ready/Stale/Blocked 与 production list/canvas 完成三视口真实浏览器、键盘、触控、ARIA、焦点、溢出、中文投影和 console 检查。
- 浏览器 `local-e2e`：以 synthetic `ui-ready` / `ui-stale` / `ui-blocked` workspace 在 1440×1024、1024×900、390×844 验证概览 Ready/Stale/Blocked、production list/canvas、跨页 episode=2、移动“更多”与 Escape。页面无横向溢出；可见触控目标均不小于 44×44；3px focus ring、键盘导航、tabs `aria-selected` / roving `tabindex`、状态文本与恢复入口符合要求；目标页面无 console error/warning，未出现绝对路径、provider 诊断或英文内部状态。证据：`/private/tmp/iter158-ui-evidence/`（6 张截图与 `browser-checks.json`，gitignored 临时目录）。
- 本地隔离演练：聚焦 route test 实际创建 `localdemo_*`，源 workspace 关键文件字节不变且没有 provider 调用；刷新重新读取权威投影。
- 聚焦验证：最终 166 项 UI/Web/production/local-demo 回归通过；标准验收发现旧合同要求的“只展示服务端已保存状态”文案缺失后，补回该兼容语义，18 项定向回归通过。
- A158-07：通过。correctness/E2E、security/boundary、Web/UIUX/响应式三个独立只读 subagent 共提出 5 个有效 finding：多 toggle 绑定、episode 导航保持、空 production 优先级、辅助投影独立降级、未知不得误报为空；均由主线程修复并复核，无剩余已知 finding。
- Canonical：accepted implementation commit `91b9fe6da6206dd5b1fc913c9ffe97a46aaa6015` 上 `bash scripts/verify.sh` exit 0；schema v2，15 steps，**2981 tests OK**，483 秒，run `f823073be7a34846a71e9af3db4dce3d`，`tracked_scope_clean=true`，`verification_profile=canonical-mock-offline`。
- 验收运行说明：首次在受限沙箱运行时，23 个 loopback `socket.bind` 测试因 `EPERM` 报错，同时捕获上述 1 个真实兼容文案 failure；修复并更新 implementation commit 后，在获批环境按相同 mock/offline 配置完整重验通过。这是失败范围修复后的 canonical 重验，不调用真实 provider。
- 最终结论：工程验收为 `mock-functional`；浏览器与隔离本地演练证据为 `local-e2e`。本轮未调用真实文本、图片、视频或 TTS provider，不是 `provider-validated`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮的可复用规则（同源投影、隔离 local demo、响应式可访问性、审查后单次验收）已在 `AGENTS.md`、`iter-finish` 与既有产品协议中覆盖；本轮没有需要晋升的新长期工程规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 短剧三档响应式导航壳、概览信息架构与 production 结构标识 |
| `src/web/static.py` | `ui-drama` 响应式 CSS，概览六态/降级，production 列表/画布/键盘，导航与 episode 同步 |
| `tests/test_drama_web_uiux_phase_a.py` | iter158 壳、概览、production、可访问性与恢复 hook 合同 |
| `docs/iterations/README.md` | 追加 canonical iter158 索引 |
| `docs/iterations/iteration_158_drama_web_uiux_phase_a_shell_overview_production.md` | 立项、实施、审查、验收与范围记录 |
| `README.md` | 更新短剧 Web Phase A 状态与实时 SOP |
| `docs/AGENT_HANDOFF.md` | 就地更新当前快照、验收证据与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | 追加 iter158 阶段里程碑与实现索引 |

## 不在本轮范围

- 不重构五站创作、角色库、资产治理、逐镜图片/视频候选、合成交付、剧集、Insights 或 Jobs 的主体布局。
- 不修改后端 API、领域 schema、任务 DAG、计价、授权、恢复、exact delivery 或 SubmissionUnknown/Lost 语义。
- 不迁移 React/Vue 等框架，不写入 Figma，不调用真实 provider。

## Notes

- Figma 是视觉与交互依据；当前代码、API 与测试仍是行为真源。
- 计划提交信息：`docs(iter158): 迭代计划 158 立项（短剧 Web UIUX Phase A）`。
