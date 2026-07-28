# Iteration 152 - 小说续写 Web UIUX 全量重设计规范

## Context

现有 Figma 文件已经定义文学暖色视觉基础、4 个核心组件，以及桌面/移动端“当前创作”首页，但尚未覆盖小说续写域的完整页面、按钮状态、异步任务、失败恢复与响应式交互。用户要求在现有稿基础上补齐全部可能页面和交互逻辑，并交付可直接指导后续前端重构的 UI/UX 设计文档。

## Plan

### Implementation Context
- `must_read`: `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/wizard.py`, `docs/product/GETTING_STARTED.md`
- `expected_changes`: `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 Web 生产代码、API 契约、测试、私有输入、workspace 数据、运行输出或用户自有未跟踪文件；不运行真模型、真生图、真视频或 TTS。

1. 以现有 Figma 视觉系统和当前 Web 代码为双重事实源，完成页面、操作、状态与响应式全量盘点。
2. 在 Figma 中补齐小说续写域的信息架构、组件状态、桌面/移动关键页面及交互注释，不改动短剧生产域。
3. 新建前端可实施的 UI/UX 规范，包含路由地图、页面规格、按钮矩阵、状态机、模态与反馈、响应式、无障碍、数据契约映射和重构分期。
4. 保持现有安全边界：mock/local 状态显式、真实调用逐次授权、付费动作二次确认、错误与任务投影继续脱敏。

## Acceptance

### Review Context
- `correctness_behavior`: 核对设计文档是否覆盖当前所有小说与公共 Web 路由、现存按钮/任务动作、加载空态错误态阻断态与恢复路径，且页面到现有 API/DOM hook 的映射可实施。
- `security_boundary`: 核对设计是否保持本地单用户、原文只读、真实调用逐次授权、费用可见、任务可取消/恢复、日志和错误脱敏以及离开保护边界。
- `extra_risk_view`: `Web/UIUX：核对桌面、平板、390px 移动端信息架构、触控尺寸、键盘焦点、模态与异步反馈的一致性`

- A152-01：设计范围清单覆盖公共入口、建书流程、小说 workspace 全部页面及跨页状态，不把短剧生产页混入本轮。
- A152-02：Figma 至少包含 Foundations、组件状态矩阵、桌面核心流程、移动核心流程和交互说明；所有新增画布内容沿用现有 token、字体与命名。
- A152-03：`docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md` 提供路由级页面规格、操作级按钮矩阵、状态与反馈规则、响应式和无障碍要求、前端/API 映射与可分阶段重构依据。
- A152-04：安全/费用/隐私文案不夸大能力，不以 mock 验收宣称真实 provider 已验证，所有真实请求与付费动作仍要求逐次确认。
- A152-05：聚焦文档/结构检查、多视角只读审查和最终一次 `bash scripts/verify.sh` 通过；验收等级仅为 `mock-functional`，不调用真实 provider。

## Implementation Notes

- 以当前 `src/web/routes.py`、`src/web/templates.py`、`src/web/static.py` 与 `src/web/wizard.py` 为行为事实源，确认公共 5 页与小说工作区 10 页，共 15 个页面；短剧专属页面不纳入本轮。
- 在原 Figma 文件中保留既有稿并新增 `07–12` 页面组：信息架构、全部桌面页面、平板自适应、手机核心流程、交互与状态、开发映射。
- 根据用户复核，将原先偏深的墨绿/酒红操作色改为浅色体系：主操作为浅玉底，计费操作为浅杏底，危险操作为浅桃底；计费和危险按钮统一使用高对比深色文字与语义边框。
- 新增并验证 6 个本地组件集：30 变体文字按钮、18 变体图标按钮、14 变体状态标记、16 变体表单字段、6 变体阶段卡片、3 变体响应式导航。文字按钮与图标按钮交互尺寸均不小于 44px。
- Figma 完成 15 个 `1440×1024` 桌面页面、3 个 `1199×900` 平板关键页面、6 个 `390×844` 手机核心页面；另补齐空内容、加载、失败、阻断、页面不存在、模块不适用、提示消息、计费确认、危险确认和未保存离开。
- 对新增用户视图执行英文词扫描：桌面稿仅发现并移除了“TXT”缩写，手机、平板与交互状态稿均无连续英文词；开发交付页保留路由和组件属性等实施术语。
- 新增 `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`，记录浅色视觉、中文文案映射、路由级页面规格、逐页异常状态矩阵、操作级按钮/API/DOM hook 矩阵、异步状态机、确认窗口、响应式、无障碍、安全边界与分期重构建议。
- correctness 只读审查指出起点方法、四/五阶段、任务枚举、一句话开书、Insights 语义、未实现动作和按钮矩阵缺口；已改为当前四阶段，修正起点为 POST，补 `pending/aborted` 归一化与 premise 分支，将 Insights 改为只读“创作数据”，隐藏无后端契约按钮并补 30+ 行操作能力矩阵。
- security/boundary 只读审查指出凭据片段、技术详情白名单和模块不匹配三项失败关闭缺口；已规定设置读取只返回 configured/更新时间、秘密输入始终为空，技术详情只渲染安全四字段，类型不匹配后停止小说域请求与轮询。
- Web/UIUX 只读审查指出逐页异常态、阶段名/离线误标、额度不足动作、真实重试计费、处理中按钮、44px 导航与侧栏选中问题；Figma 和规范均已修正并重新结构验证。
- correctness 回归进一步指出章节计划编辑 hook 实际位于工作台、已有正文时保存需确认，以及“检查并继续”和重新扩写覆盖确认链不完整；规范已区分现有 hook 与重构目标，补齐读取就绪状态、计费确认、启动任务和失败保留的完整顺序。
- Web/UIUX 回归发现 `1280px` 平板示例超出规范断点；三个平板画板已改为 `1199px` 并同步收窄导航、卡片和任务区，截图复核无横向溢出或遮挡。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `<iter-finish 回填：none|promoted>`
- `destination`: `<iter-finish 回填：none|既有长期权威文档>`
- `reason`: `<iter-finish 回填人工判断>`

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md` | 建立本轮设计与验收记录 |
| `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md` | 新增小说续写 Web UI/UX 前端实施规范 |
| Figma `续写工作台 · Web UIUX 重设计` | 新增浅色变量、组件状态、15 个桌面页、3 个平板页、6 个手机页、交互状态与开发映射 |

## 不在本轮范围

- 不实施 `src/web/templates.py`、`src/web/static.py` 或路由/API 重构。
- 不设计短剧生产工作台、资产、逐镜媒体、合成与交付页面。
- 不触发真实文本、图片、视频、TTS 或任何计费调用。

## Notes

- Figma 文件是交互与视觉参考；生产行为仍以当前代码、测试与本规范中的映射表为准。
- 本轮先完成设计系统 Phase 0 范围确认，再进入 Figma 写入。
