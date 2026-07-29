# Iteration 156 - 小说 Web Phase E 高级与辅助页面重构

## Context

Phase A-D 已完成小说 Web 规范、浅色共享设计系统、公共页面和单章续写主流程。本轮完成最后五个高级与辅助页面，明确高级入口、只读边界、数据安全投影与响应式行为，并仅在调用方证据充分时清理旧样式或兼容选择器；同时回归 Phase C/D 与短剧页面，确保全站兼容收口。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md`, `docs/iterations/iteration_153_novel_web_light_design_system_components.md`, `docs/iterations/iteration_154_novel_web_public_pages_phase_c.md`, `docs/iterations/iteration_155_novel_web_phase_d_single_chapter_flow.md`, `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/jobs.py`, `tests/test_web_plan_edit.py`, `tests/test_web_search.py`, `tests/test_web_reviews_aggregator.py`, `tests/test_web_insights.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_public_phase_c.py`, `tests/test_web_phase_d.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `tests/test_web_phase_e.py`, `tests/test_web_plan_edit.py`, `tests/test_web_search.py`, `tests/test_web_reviews_aggregator.py`, `tests/test_web_insights.py`, `tests/test_web_ui_design_system.py`, `docs/iterations/iteration_156_novel_web_phase_e_advanced_auxiliary_pages.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、真实模型/生图/视频/TTS 与计费入口、`小说txt/`、私有 workspace、`data/`、`logs/`、运行产物、用户未跟踪文件、短剧生产页面视觉及无证据的兼容选择器清理；全程固定 `OPENAI_MODEL=mock`。

1. 重构批量续写页为明确的高级入口，完整呈现范围与设置；保持 readiness 先行、Paid 逐次确认、额度不足可调整、失败保留输入和提交 busy 语义，不新增自由文本写作要求。
2. 重构故事规划页，仅允许章节计划按现有契约编辑、取消与保存；大纲和创作决定只读，保留离开保护并在已有正文时说明检查状态可能更新。
3. 重构内容搜索页，支持现有范围与组合筛选，空输入不请求；安全展示来源、标题、片段和打开入口，提供条件化空结果、清除与失败重试。
4. 重构内容检查页，聚合既有检查结果并以直白文案、安全严重程度和处理状态呈现；仅保留查看位置，不伪造处理或重新检查能力。
5. 重构创作数据页为严格只读统计，按已保存记录展示各章使用额度、复用情况和检查分项；缺失与未知费用失败关闭，不暴露模型、字段、日志或推理数据。
6. 审计旧样式、移动端覆盖和行为选择器的模板、脚本与测试调用方；只删除证明确无调用方的条目，不明确者保留并记录。
7. 补齐共享导航、44px、窄屏、表单关联、安全投影与 Phase C/D、短剧兼容回归测试；使用 isolated synthetic workspace 完成五页三视口真实浏览器操作验收。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五页既有路由、表单字段、DOM hook、readiness/Paid、计划保存与离开保护、空搜索、检查定位和统计只读语义，并回归 Phase C/D 与短剧页面。
- `security_boundary`: 核对动态异常、路径、未知对象、索引/模型/provider/token/日志/prompt 等只经白名单安全投影；小说与短剧 workspace 类型失败关闭，未知状态与费用不伪造。
- `extra_risk_view`: Web/UIUX/响应式视角覆盖三个视口、导航唯一性、44px、焦点/Tab、遮挡溢出与表单关联；compatibility/cleanup 视角逐项核对旧选择器调用方证据。

- **A156-01**：批量续写明确为高级入口，设置与额度信息完整；启动顺序为 readiness 后 Paid 逐次确认，提交具备 `aria-busy` 与防重复，失败保留输入。
- **A156-02**：故事规划只允许章节计划编辑，大纲与创作决定只读；取消不写入、失败保留输入、`data-leave-guard` 和保存契约不回归。
- **A156-03**：搜索支持既有范围和组合筛选，空输入不发请求；结果、空态、清除与重试均有安全且不只依赖颜色的用户语义。
- **A156-04**：内容检查只展示安全投影的问题、位置、严重程度与状态，仅提供现有查看位置能力，不出现无契约处理动作。
- **A156-05**：创作数据严格只读且仅来自已保存记录；缺失记录和未知费用不伪造为零，不暴露内部技术数据。
- **A156-06**：五页复用 `ui-novel` 和 iter153 共享组件，当前导航唯一不可重复点击，交互目标不少于 44px，390px 无关键隐藏、遮挡或横向溢出。
- **A156-07**：旧样式与兼容选择器逐项完成调用方审计；仅删除有测试证明的无调用方条目，其余保留并记录原因。
- **A156-08**：聚焦测试与静态检查覆盖安全投影、workspace 隔离、Phase C/D 和短剧兼容；correctness、security、Web/UIUX 与 compatibility/cleanup 多视角只读审查 finding 均闭环。
- **A156-09**：isolated synthetic workspace 真实浏览器覆盖五页 × `1440×1024`、`1199×900`、`390×844`，完成指定操作及 Phase C/D、短剧抽查，控制台无错误；该证据最高标记 `local-e2e`。
- **A156-10**：implementation commit 上最终仅运行一次 `bash scripts/verify.sh` 并达到 `mock-functional`；随后回填本文件并就地同步 README、handoff 与 PROJECT_HISTORY，创建 docs-only 收官提交，不 push、不调用真实 provider。

## Implementation Notes

- 五个页面继续复用 iter153/155 的 `ui-novel`、共享按钮/状态/表单/modal/toast/导航及旧 DOM hook；没有引入新框架或修改后端任务状态机。
- 批量续写保留 `start-point-form`、`plan-form`、`write-book-form` 与 preset hook，提交时强制重新读取 readiness，仅允许明确 `ready`/`warn` 进入 Paid 确认；unknown 失败关闭。增加超时、额度与范围说明，表单 busy 时禁止重复提交。
- 故事规划把既有章节计划 PUT 契约带到本页；大纲与创作决定仍只读。新增独立计划编辑器、输入保留、取消不写入、应用内离开保护、`beforeunload` 与焦点恢复；不增加重新生成入口。
- 搜索继续使用 `original/draft/kb` 后端范围值，但界面改为“原文章节 / 续写章节 / 人物与故事资料”；空输入在 fetch 前返回，结果以 DOM 文本节点构建并提供安全“打开”去向。
- 内容检查从保存的 review 聚合逐项派生人物、时间、地点、设定、文字或前后文卡片，只显示类别化说明、章节位置、白名单严重程度与状态；不渲染规则名、内部角色、原始分析文本，也不提供处理写操作。
- 创作数据仍读取既有 endpoint，但费用聚合改为保留 unknown（任一记录费用缺失/非法时返回 `null`），前端严格数字白名单并显示“费用待确认”；检查分项改为移动端可读卡片，全页无写操作。
- 审查确认 Phase E novel-only API 的类型边界也需失败关闭，因此合理扩展到 `src/web/insights.py` 与既有 route 测试；未修改 API 路径、字段名或状态机。
- compatibility/cleanup 调用方审计后仅删除 `a.search-hit-title:hover`、`.search-hit-title.muted-link` 与无消费者的 `data-leave-guard-scope="plan"`。工作台 `plan-edit-*`、三组批量表单、`search-*`、`reviews-panel`、`insights-*`、`data-ui-*`、`data-leave-guard` 均有生产/测试/规范调用，全部保留；共享 `.subscore-bar` 重复声明因短剧调用方存在而未动。
- correctness、security、Web/UIUX、compatibility 四视角 finding 已全部修复并经聚焦回归；未留 P1/P2。isolated synthetic workspace 的真实 Chromium 覆盖五页 × 三视口，并抽查 Phase C/D 与短剧页；只运行 mock。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮安全投影、只读边界、兼容选择器调用方审计和浏览器验收均是既有 Web 规范与 AGENTS 工作流的具体落实，没有新增需要独立晋升的长期规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 重构 Phase E 五页信息架构、用户文案、表单关联与只读标识。 |
| `src/web/static.py` | 实现 readiness/Paid 顺序、计划编辑保护、安全搜索/检查/统计投影、响应式样式与精确死选择器清理。 |
| `src/web/routes.py` | 为 plan/reviews/search/readiness 小说 API 增加 workspace 类型失败关闭。 |
| `src/web/insights.py` | 保留未知费用，不再把缺失或非法记录聚合为零。 |
| `tests/test_web_phase_e.py` | 新增五页共享组件、行为、安全、只读和响应式合同。 |
| `tests/test_web_insights.py` | 覆盖未知费用不归零。 |
| `tests/test_web_routes_get.py` | 更新批量页文案合同并覆盖 Phase E API 类型隔离。 |
| `tests/test_web_search.py` | 更新内容搜索页面文案合同。 |
| `tests/test_web_ui_design_system.py` | 更新搜索来源安全投影断言。 |
| `docs/iterations/iteration_156_novel_web_phase_e_advanced_auxiliary_pages.md` | 记录计划、实施、审查、验收与收官证据。 |
| `docs/iterations/README.md` | 追加 Iteration 156 canonical 索引。 |

## 不在本轮范围

- 后端 API、小说流水线、任务状态机及短剧生产页面视觉改造。
- 自由文本写作要求、检查项处理、采用建议、章节删除等无现有契约能力。
- 任何真实 provider、真实生图、真视频、TTS 或计费验证。

## Notes

- Figma 文件继续作为视觉事实源；本轮原则上不修改 Figma，只有确需读取节点时才先加载并遵守 `figma-design-to-code`。
- 立项提交信息草稿：`docs(iter156): 迭代计划 156 立项（小说 Web Phase E 高级与辅助页面重构）`。
- 实施完成后必须显式使用仓库内 `iter-finish` 收官。
