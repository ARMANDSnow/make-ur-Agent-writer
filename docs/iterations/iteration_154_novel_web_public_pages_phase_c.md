# Iteration 154 - 小说 Web Phase C 公共页面重构

## Context

iter152 已形成小说 Web UI/UX 规范，iter153 已将浅色设计变量、集中中文文案与共享组件落入生产前端，但 `/`、`/library`、`/wizard`、`/settings`、`/trash` 仍未完成生产级页面结构、信息层级、任务引导、响应式和异常恢复重构。本轮只实施 Phase C 五个公共页面，保持既有后端契约、小说与短剧 workspace 隔离及 mock-only 安全边界，并用 isolated synthetic workspace 做真实本地浏览器验收。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md`, `docs/iterations/iteration_153_novel_web_light_design_system_components.md`, `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/wizard.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_settings.py`, `tests/test_web_trash.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_wizard_e2e.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/wizard.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_settings.py`, `tests/test_web_trash.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_wizard_e2e.py`, `docs/iterations/iteration_154_novel_web_public_pages_phase_c.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、用户未跟踪文件、后端 API、小说流水线、任务状态机、小说 Phase D/E 页面内容布局或短剧生产页面视觉；不调用真实文本、图片、视频、TTS 或任何计费服务。

1. 复用 iter153 的 `ui-public`、中文安全投影和共享按钮/表单/提示/确认/导航组件，重构首页、作品列表、小说创建向导、设置和回收站的信息架构与响应式布局。
2. 保持现有 route、endpoint、字段、workspace 语义、DOM hook、`data-ui-*`、旧兼容选择器、readiness、离开保护、防重复提交、toast 与确认焦点恢复；仅在必要处收紧动态服务端数据的安全投影。
3. 新增或更新聚焦测试，覆盖五页共享组件、中文和失败关闭、导航唯一性、44px 目标、表单关联与 busy 状态、回收站语义/强确认及小说/短剧隔离。
4. 使用 mock-only isolated synthetic workspace 和真实本地浏览器，在 `1440×1024`、`1199×900`、`390×844` 下检查五页，并走通创建、列表进入、恢复、删除确认取消和设置契约。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五个公共页面的信息结构、现有 endpoint/字段/DOM hook、readiness、离开保护、防重复提交、导航唯一性、作品类型隔离、恢复与永久删除强确认是否保持兼容，并核对 synthetic/mock 创建真实走过生产 Web 路径。
- `security_boundary`: 核对动态未知状态、错误、路径和对象均经失败关闭安全投影，不泄漏内部术语、枚举、原始异常、凭据或文件系统路径；永久删除继续提交内部安全标识且只作用于选定 synthetic 作品。
- `extra_risk_view`: `Web/UIUX/响应式：核对 1440×1024、1199×900、390×844 下的信息层级、无横向溢出/遮挡、44px 触控目标、键盘焦点与 Tab 顺序、表单错误关联、导航唯一性、toast/确认窗口层级及 Escape/取消焦点恢复`

- A154-01：`/` 清楚说明产品能力并提供创建小说、打开已有作品、进入短剧作品三个主要入口；初始化空态/失败态有中文恢复说明，且不出现规定的内部术语或能力夸大。
- A154-02：`/library` 以非颜色唯一的名称、类型、更新时间、进度和主要操作呈现作品；空态与读取失败可恢复，未知动态值/路径/原始异常失败关闭，390px 使用可读窄屏结构。
- A154-03：`/wizard` 明确区分本地原文、原创故事和短剧入口，完整关联标签/必填/帮助/错误；readiness 可读，提交处理中整表防重入并设置 `aria-busy`，失败保留输入且不改变 endpoint/字段/workspace 语义。
- A154-04：`/settings` 只展示当前用户可理解的设置或明确只读投影，区分离线与未开始，保存/失败/未修改状态清楚，且不暴露模型、provider、环境变量、内部命令、路径、原始异常或敏感配置。
- A154-05：`/trash` 以不同层级呈现恢复和永久删除；永久删除要求输入可见作品名、说明影响与不可恢复性、提交内部安全标识，取消/Escape/关闭恢复焦点，失败明确内容仍保留且不泄漏内部术语。
- A154-06：五页共用 `ui-public` 与 iter153 组件；每页唯一且不可点击的 `aria-current="page"`，所有可见交互目标至少 44×44px，手机导航不遮挡正文、按钮、toast 或确认窗口，核心操作不靠隐藏解决。
- A154-07：聚焦测试和静态检查证明动态安全投影、兼容 DOM/API/readiness/leave-guard、防重复、短剧/小说隔离与 Phase D/E 非回归；correctness、security/boundary、Web/UIUX/响应式三个独立只读审查无未修 P1/P2。
- A154-08：真实本地浏览器覆盖五页 × 三视口，并完成首页进入向导、模式切换、synthetic/mock 创建、列表进入 synthetic 作品、回收站恢复、永久删除名称匹配/取消/焦点恢复及设置实际契约；无横向溢出、遮挡、关键截断、控制台错误或禁用技术词，证据等级仅为 `local-e2e`。
- A154-09：implementation commit 上最终一次 `bash scripts/verify.sh` 通过，工程验收等级为 `mock-functional`；回填证据并完成 docs-only 收官提交，全程不调用真实 provider、不 push，且用户已有 iteration 索引、短剧阶段计划、体检报告及其他改动均保留。

## Implementation Notes

- 首页收敛为“创建小说作品 / 打开已有作品 / 进入短剧作品”三个生产入口，并补初始化失败与下一步说明；作品列表改为可搜索卡片，显式呈现类型、最近更新、当前进度、内容概况和唯一主操作，390px 不再压缩为表格。
- 创建向导保留 `/api/wizard/start`、`/api/wizard/premise-start`、`/api/wizard/drama-start` 及全部字段/DOM hook，补齐三种模式说明、小说与短剧字段的 `label`/help/error 关联，并以整表 `aria-busy` 和 submit 锁防止重复提交；preflight 非 2xx 或非布尔投影失败关闭为“暂时无法确认”。
- 设置页保留既有 GET/PUT endpoint、白名单字段和验证逻辑；普通创作偏好在首屏，原连接字段移入中文折叠高级设置。GET secret 投影从首尾掩码收紧为“空值 + configured 布尔”，浏览器零凭据片段；读取失败禁用保存并提供重新加载，保存处理中锁定按钮，成功/失败/未修改均有礼貌播报。
- 回收站使用卡片与不同层级的恢复/永久删除确认；永久删除只接受可见作品名匹配，提交仍使用内部 `entry` 安全标识。不可逆请求发出后锁定取消、Escape 与遮罩，失败后恢复控件并明确内容仍保留。
- 公共 workspace overview 不再投影路径；更新时间从 verified root fd 逐级 `O_NOFOLLOW` 读取有界权威产物。缺 metadata 的 legacy workspace 继续按小说兼容，存在但损坏/未知/symlink metadata 则显示“类型待确认”并禁止进入域页面；unknown insights 在 collector 前安全阻断。
- CSS 继续复用 iter153 的 `ui-public`、按钮、表单、badge、toast、modal 与导航组件，仅新增公共卡片/toolbar/窄屏布局和关联响应式规则；所有可见控件保持至少 `44×44px`。
- isolated synthetic workspace 的真实浏览器覆盖五页 × `1440×1024`、`1199×900`、`390×844` 共 15 个组合：横向溢出均为 0、每页唯一不可点击 `aria-current`、目标尺寸与焦点样式通过、控制台无错误。实操走通首页→向导、三模式切换、mock 原创创建、列表进入作品、恢复确认、永久删除名称匹配/Escape/取消/焦点恢复（未执行 purge）以及设置未修改/保存；审查修复后又复核 390px 高级设置展开无溢出。
- iter-start 的 harness 暴露已验收 iter153 使用旧值 `not-promoted`，与当前 checker 只接受 `none|promoted` 不兼容；仅将该字段迁移为等价的 `none`，未改动 iter153 验收事实。Figma 节点无需读取，未修改 Figma。
- correctness、security/boundary、Web/UIUX/响应式三路只读审查提出的有效 P2 已全部修复并复核为 P1/P2 none；聚焦回归当前为 215 tests，Python/三段 JS 语法、harness 与 `git diff --check` 通过。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: `本轮关于凭据零片段、失败关闭、workspace 类型隔离、44px 与 modal 焦点/取消语义均已由 AGENTS、iter-finish 或现有产品规范覆盖；无需新增长期规则。`

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 重构五个公共页面结构、导航、表单关联、设置与未知类型安全页 |
| `src/web/static.py` | 公共页面卡片/响应式样式、列表/回收站/向导/设置交互和失败关闭 |
| `src/web/routes.py` | 路径零投影、可信更新时间、严格 workspace 类型与 unknown insights 阻断 |
| `src/web/settings.py` | secret GET 投影改为零片段与 configured 布尔，PUT 契约不变 |
| `tests/test_web_public_phase_c.py` | 新增 Phase C 公共页面、响应式/无障碍/安全投影与兼容契约测试 |
| `tests/test_web_routes_get.py` | 同步生产页面文案、入口和 overview 投影断言 |
| `tests/test_web_settings.py` | 收紧设置 GET 零 secret 片段测试 |
| `docs/iterations/iteration_153_novel_web_light_design_system_components.md` | 迁移旧 Knowledge Promotion 枚举为当前合法等价值 |
| `docs/iterations/README.md` | 追加 iter154 canonical 索引（保留用户既有改动） |
| `docs/iterations/iteration_154_novel_web_public_pages_phase_c.md` | 记录计划、实现、审查、验收与变更范围 |

## 不在本轮范围

- 小说 workspace Phase D/E 页面内容布局与短剧生产页面视觉。
- 后端 API、小说流水线、任务状态机、新导入/重命名/批量删除等无契约能力。
- 真实文本、图片、视频、TTS、计费请求与 provider 验证。

## Notes

- Figma 是视觉和交互参考；当前行为以生产代码与测试为准，本轮原则上不修改 Figma。
- 浏览器与工程证据均为 mock-only；浏览器部分最高只记为 `local-e2e`，不得外推为 provider 验证。
