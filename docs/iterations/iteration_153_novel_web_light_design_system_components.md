# Iteration 153 - 小说 Web 浅色设计系统与共享组件落地

## Context

iter152 已完成小说续写 Web 的 Figma 浅色设计稿与可实施 UI/UX 规范，但当前生产模板和原生 CSS/JS 仍保留深色主按钮、分散的英文技术文案和不一致的组件状态。本轮落实 Phase A「设计变量与中文文案层」和 Phase B「共享组件」，为后续 Phase C–E 逐页布局重构建立稳定基础，同时保持现有 API、任务、授权与短剧界面边界。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_152_novel_web_uiux_redesign_spec.md`, `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/wizard.py`, `tests/test_web_server.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_trash.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_wizard_e2e.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `tests/test_web_ui_design_system.py`, `docs/iterations/iteration_153_novel_web_light_design_system_components.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、短剧生产视觉、后端 API、小说流水线、任务状态机或用户已有未跟踪文件；不调用真实文本、图片、视频、TTS 或任何计费服务。

1. 在公共与小说页面命名空间中落实浅色语义变量，统一 Primary、Secondary、Ghost、Paid、Danger、Icon Button、Status Badge、Field、Toast、Modal、Navigation 与 Stage Card，并保留短剧生产界面现有视觉和行为。
2. 建立集中且失败关闭的中文用户文案映射；未知状态显示“状态待确认”，清理公共与小说页面中的旧英文和内部技术词，不改变开发字段与接口枚举。
3. 按实际 endpoint、step 与授权链迁移真实生成、重新生成和真实重试入口为 Paid 样式，保留 readiness、逐次确认、任务记录、取消恢复、离开保护和现有 DOM hook。
4. 新增聚焦测试，证明变量、浅底深字、44px 点击目标、未知状态失败关闭、中文页面、计费样式与授权、原有交互 hook 及短剧隔离。
5. 在 mock-only synthetic 作品上完成 1440×1024、1199×900、390×844 三档真实本地浏览器验证，覆盖指定公共页与小说工作台、批量续写、任务记录。

## Acceptance

### Review Context
- `correctness_behavior`: 核对共享组件和中文映射是否覆盖公共与小说生产页面，Paid 分类是否基于真实 endpoint/step/授权链，且任务轮询、取消、恢复、readiness、表单防重复、标签页和离开保护无回归。
- `security_boundary`: 核对未知状态、错误与任务投影均失败关闭且不泄漏原始异常、内部状态、路径、prompt、凭据或 provider 信息；真实生成仍逐次授权，短剧与私有 workspace 边界不变。
- `extra_risk_view`: `Web/UIUX/响应式：核对 1440×1024、1199×900、390×844 的无溢出、44px 触控目标、键盘焦点、按钮层级、非颜色状态、弹窗焦点恢复和短剧样式隔离`

- A153-01：公共与小说页面使用指定浅色语义变量；Primary、Paid、Danger 均为浅底深字，深色不作大面积操作背景，短剧生产页面不被命名空间无意改造。
- A153-02：集中中文文案层覆盖指定状态与技术词；未知值统一“状态待确认”，公共及小说用户页面不直出旧英文、内部状态码、原始异常或文件系统路径。
- A153-03：共享文字按钮、图标按钮、状态标记、表单字段、提示消息、确认窗口、导航与固定四阶段卡均完成；按钮点击目标至少 44px，处理中防重复并设置 `aria-busy`，弹窗支持 Escape、焦点限制与恢复。
- A153-04：小说域真实生成、重新生成与真实重试按 endpoint、step 和授权流程使用 Paid 样式，逐次授权、额度确认、任务记录、失败恢复与现有 API 语义保持不变。
- A153-05：原有 DOM hook、`data-leave-guard`、标签页、任务轮询/取消/恢复、readiness 和 toast 礼貌播报通过聚焦回归，短剧页面行为不受影响。
- A153-06：真实本地浏览器覆盖 `/`、`/library`、`/wizard`、`/settings`、`/trash`、synthetic 小说的 `/workbench`、`/continue`、`/jobs`，在 1440×1024、1199×900、390×844 下无横向溢出、遮挡或关键截断，键盘焦点与 44px 触控目标成立；证据仅标记为 `local-e2e`。
- A153-07：聚焦测试、静态检查、correctness、security/boundary、Web/UIUX/响应式独立只读审查与最终一次 `bash scripts/verify.sh` 通过；统一工程验收等级为 `mock-functional`，不调用真实 provider。

## Implementation Notes

- 在现有 `templates.py` / `static.py` 单 bundle 契约内落地 `ui-public`、`ui-novel`、`ui-drama` 命名空间；公共与小说页使用指定的 10 个浅色语义变量，短剧生产页保留旧视觉。`/static/app.css` 和 `/static/app.js` 路由契约未变。
- 统一 Primary / Secondary / Ghost / Paid / Danger / Icon Button；按钮和图标按钮点击目标不小于 44px，加入 hover / focus / active / disabled / `aria-busy` 处理中状态。表单增加标签、必填说明与错误关联，但仅在公共/小说命名空间增强。
- 集中中文状态、步骤、readiness 与评审文案投影；未知状态失败关闭为“状态待确认”，小说页不再直出 raw blocker/warning/command、路径、原始异常、对象型评审结构或内部任务枚举。
- 新增共享计费确认窗口，在发起小说生成/重新生成/重试请求前说明人民币额度、覆盖范围与内容保留情况；重试分类使用显式小说计费 step allowlist，本地和短剧重试保持 Secondary 且不进入计费确认。API、任务状态机、取消和恢复契约未变。
- 回收站恢复/永久删除已中文化；用户以可见作品名确认，请求仍提交内部 entry，永久删除不使用纯图标。弹窗支持 Escape、焦点陷阱和触发器焦点恢复。
- 工作台固定四阶段为“准备设定 / 生成大纲 / 生成细纲 / 撰写正文”，每张真实阶段卡都显示独立中文状态；当前侧栏项改为 `aria-current="page"` 的非重复链接。
- 保留 `data-leave-guard`、标签页关联、任务轮询/取消/恢复、readiness 阻断、toast 礼貌播报和旧 DOM hook；补齐多提交按钮的整表防重入，轮询运输失败也会在 `finally` 中恢复。
- 三路独立只读审查：correctness/behavior、security/boundary、Web/UIUX/响应式。主线复核并修复了计费 step 漏项、轮询失败忙碌状态、弹窗命名空间、动态英文/内部投影、回收站确认、移动阶段卡标题和普通链接焦点环；最终复审无剩余 correctness/security/UIUX 代码 finding。
- 真实本地浏览器在 isolated synthetic workspace 与 mock 配置下覆盖 8 个指定页面 × 3 个视口（24 组）：无横向溢出、小于 44px 的可见操作、无标签图标按钮、禁用英文词命中或控制台错误。另验证 Paid/Danger 弹窗的浅底深字、44px、Escape 与焦点恢复，并保存 `/tmp/iter153-browser-evidence/final-*.png` 证据。

## Acceptance Result

- **A153-01 / A153-02：PASS。** `ui-public`、`ui-novel`、`ui-drama` 明确隔离；公共与小说 CSS 使用指定浅色语义值，Primary / Paid / Danger 均为浅底深字。集中 Python/JS 映射覆盖规定状态与旧技术词，未知状态统一为“状态待确认”，动态 blocker、异常、路径与对象型评审信息不再原样进入用户页面。
- **A153-03 / A153-04：PASS。** 文字按钮、44×44 图标按钮、中文状态、字段/错误关联、toast、三类确认语义、导航与固定四阶段卡已统一；处理中设置 `aria-busy` 并阻止重复提交。小说真实生成、重新生成与真实重试按显式 step allowlist 使用 Paid，并在发请求前确认人民币额度、覆盖范围和内容保留；本地/短剧重试不误分类。
- **A153-05：PASS。** `data-leave-guard`、标签页、任务轮询/取消/恢复、readiness、toast、既有 DOM hook 与 `/static/app.css`、`/static/app.js` 服务契约通过聚焦回归；短剧页面行为合同未回归。
- **A153-06：PASS（`local-e2e`）。** isolated synthetic workspace、`OPENAI_MODEL=mock`、`DRAGON_RAJA_SKIP_DOTENV=1` 下，`/`、`/library`、`/wizard`、`/settings`、`/trash`、`/w/synthetic/workbench`、`/w/synthetic/continue`、`/w/synthetic/jobs` 在 `1440×1024`、`1199×900`、`390×844` 共 24 组均无横向溢出、小于 44px 的可见操作、无标签图标按钮、禁用英文词命中或控制台错误。三档键盘抽查均显示 3px 焦点环；Paid/Danger 弹窗的浅底深字、44px、Escape 和焦点恢复通过。截图保存在 `/tmp/iter153-browser-evidence/final-*.png`，仅代表本地 UI/E2E。
- **A153-07：PASS。** 聚焦 Web 套件 403 tests OK；最终补充的 164 项目标回归与 11 项历史合同回归通过，`py_compile`、Node `--check`、`git diff --check` 通过。correctness/behavior、security/boundary、Web/UIUX/响应式三路独立只读复审最终无剩余代码 finding。
- **Implementation commit：** `082f0d7abd37b2e84e0e3e4e7e9352854b1468d5`（`feat(web): 落地小说浅色设计系统与共享组件`）。
- **Canonical：** 首次全量在 implementation 修订前暴露 5 failures + 1 error，均为旧测试仍断言英文/旧 active-link/raw 状态的合同漂移；修正测试合同并以 11 项聚焦回归确认后，按失败范围重验。最终在上述 implementation commit 的隔离 clean worktree 运行 `bash scripts/verify.sh`：**2926 tests OK / 15 steps / 474 秒 / exit 0**，run `f3d7e4e81805499c998b724351c399b3`，tree `bfe36226304a9ffd161515c65e4bc5afdd1a704d`，`tracked_scope_clean=true`，等级 `mock-functional` / `canonical-mock-offline`；mandatory `local_drama_e2e` 通过。
- 全程未读取 `.env`，未调用真实文本、图片、视频、TTS 或任何计费 provider；未触碰小说原文、私有 workspace、`data/`、`logs/` 或用户既有未跟踪文件。Phase C–E 的 15 页完整内容布局仍不在本轮范围。

### Knowledge Promotion
- `decision`: `not-promoted`
- `destination`: `none`
- `reason`: 本轮没有形成超出 iter152 规范的新长期设计规则；Phase A/B 当前实施状态已就地同步至 README、handoff 与项目历史，避免在 accepted implementation commit 后修改非收官白名单文档。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 公共/小说/短剧命名空间、中文文案、Paid 入口、四阶段卡与导航语义 |
| `src/web/static.py` | 浅色变量、共享组件状态、中文失败关闭投影、计费确认、弹窗/表单/任务交互与响应式修复 |
| `tests/test_web_ui_design_system.py` | 新增 iter153 设计系统、中文映射、Paid 分类、44px、旧 hook 和短剧隔离合同测试 |
| `tests/test_web_routes_get.py` | 更新向导中文文案契约 |
| `tests/test_jobs_drawer.py` | 更新任务抽屉的中文状态与操作契约 |
| `tests/test_budget_guard.py`、`tests/test_drama_iter088_web.py`、`tests/test_static_subscore_compat.py`、`tests/test_workbench_e2e.py` | 更新旧英文、active-link 与 raw 状态的历史前端合同 |
| `docs/iterations/iteration_153_novel_web_light_design_system_components.md` | 本轮实施、审查、验收与边界记录 |
| `docs/iterations/README.md` | 追加 iter153 索引（仅本轮单行） |

## 不在本轮范围

- 不重排 15 个页面的完整内容布局；Phase C–E 页面级重构顺延。
- 不修改后端 API、小说流水线、任务状态机或新增缺少后端契约的动作。
- 不改造短剧生产页面视觉，不删除尚有调用方的兼容选择器。
- 不调用真实文本、图片、视频、TTS 或任何计费服务。

## Notes

- Figma 与 iter152 规范提供视觉和交互参考；生产行为继续以当前代码、测试与既有 API 契约为准。
