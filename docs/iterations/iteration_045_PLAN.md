# Iteration 045 — 投资人 demo 落地页 + demo 路径美化

## Context

产品要向投资人演示。此前根路由 `/` 直接是书架（`render_index`），书架里混着 15 个里一大半 `iter*/probe` 测试 workspace，第一眼不像成形产品；且全站无 logo / favicon / 品牌 hero，无法承载「介绍两大功能 → 点击进入」的 demo 叙事。

本轮新增一个投资人级**落地页**（`/`），用两张同等分量的卡片介绍【小说续写】与【剧本生成（Beta）】两大功能并分别进入；对 demo 会展示的几个页面做轻度美化。范围与决策已与用户确认：落地页 + demo 路径微调；drama 诚实标 Beta（4 站只开放前 2 站、且 mock）；沿用并提升现有「文学暖色·米纸」设计系统（jade `#3F6B5A` + amber `#C97B3D` + 米纸 `#FBF7F0`，标题衬线），不动后端业务逻辑，0 新前端依赖。

外部执行档案：`/Users/dingyuxuan/.claude/plans/splendid-skipping-trinket.md`（本轮 plan）。

## Plan

1. 路由骨架：`routes.py` 加 `render_landing` handler、`/` 改落地页、新增 `/library` → `render_index`（书架迁此）。
2. 锚点迁移：16 处书架面包屑/链接 `("书架","/")`/`href="/"` → `/library`（含侧栏 brand、wizard 取消、jobs drawer 两处「返回书架」、删除成功跳转）；更新/新增测试。
3. 落地页 HTML：`render_landing()`（hero + 双功能卡片 + 信任区大数字），`_LP_LOGO_SVG` 内联品牌 logo，`_BASE_TPL` 加 inline-SVG favicon。
4. 落地页 CSS：`.lp-*` 全套 + jade→amber 极淡 hero 渐变 + `lp-fade-up` 入场动画 + `prefers-reduced-motion`；`@media 768` 单列堆叠。
5. wizard `?type=drama` 深链：drama 卡片点进去直达 drama 表单。
6. demo 路径微调（纯 CSS，全局组件改进）：subscore track 6→8px、verdict badge 加粗、advisor 竖条。
7. 验收 + `/code-review`（high）+ iter 记录。

## Acceptance

- `.venv/bin/python3 -m pytest tests/test_web_routes_get.py tests/test_web_server.py` → 全绿；全量 `pytest tests/` 仅余 3 个**与本轮无关的既有失败**（`test_env_isolation` + `test_llm_client_cache`，已用 `git stash` 验证 baseline 同样失败）。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py web` 启动，`/api/preflight` → `is_mock:true`。
- curl 逐页：`/`(落地页, 含 `lp-hero`/`进入小说续写`/`Beta · 部分开放`/`PAGE_KIND="landing"`/favicon)、`/library`(书架)、`/wizard?type=drama`(含 `panel-drama`)、`/w/longzu/chapter/2`、`/reviews`、`/insights`、`/w/i38drama01/`、`/wizard`、`/settings` 全 200；无 500/Traceback。
- 全程 mock，不改 `.env`/`data/`/`outputs/`/`小说txt/`，不跑真实模型，不 push。

## Implementation Notes

- 单 commit 收口（前端改动内聚），message 建议 `Iteration 045: 投资人 demo 落地页 + demo 路径美化`。
- 关键实现：`_render_shell(sidebar_html="")` → `.app.no-context` 全屏脱离侧栏；落地页**纯 CSS 零 JS**（`<a>` 跳转 + CSS 动画），规避 `string.Template` 的 `$` 转义坑；favicon 用 inline-SVG data-URI（`#`→`%23`，✦ 用 `&#10022;` 实体）；wizard `?type=drama` 逻辑放外链 `/static/wizard.js`（不经 Template）。

## Acceptance Result

通过（mock-only，未跑真实模型 smoke；本环境 preview MCP 浏览器网关不可用，验证走 HTTP/API 层 + 自包含 HTML 预览，未做浏览器截图回归）。

- 本轮改动相关测试：`test_web_routes_get.py` + `test_web_server.py` → **64 passed**（新增 `test_landing_is_root`，原 `test_index_lists_workspaces` 改为 `test_library_lists_workspaces`）。
- 全量 `pytest tests/` → **588 passed**，3 failed 均为既有、与本轮无关（stash 验证）。
- curl 逐页自检：全 200，落地页关键 DOM 命中，`/library` 仍是书架，`app.css` 含 `lp-hero/lp-cards/lp-fade-up`，`wizard.js` 含 `applyTypeFromQuery`，无 500/Traceback。

## Code Review（/code-review high，按 iter 收官惯例）

3 个并行 finder（逐行+JS / 移除行为+跨文件 / 复用+altitude）→ 1 票 verify：

- **Blocker（已当 iter 修）**：`static.py` 删除 workspace 成功后 `setPendingToastAndNavigate(..., "/")` 仍指根 → `/` 现为落地页，删书后会落到落地页而非书架。已改为 `/library`，重启验证 served `app.js` 为 `/library`。这是「迁移漏改的 `/` 导航」典型遗漏；已全仓复查确认是唯一一处（另一处 `setPendingToastAndNavigate` 指 drama 写作页，正确）。
- **保留（无害）**：3 条「Review/advisor readability」CSS 是全局生效（subscore 加高 / verdict badge 加粗 / advisor 竖条），实为对应组件的通用改进，注释已从「Demo-path」改为「global」以诚实表达。
- **TDZ/favicon/类名冲突等候选**：均 REFUTED（const 定义在 IIFE 前、`show` 为 hoisted；favicon 无裸 `$`；`.tile` 仅 scoped 使用无冲突）。

## Code Review backlog（→ iter046+）

- `static.py` `.lp-metrics .tile` 与既有 `.metric-pair .tile` 近重复，可改为复用 + modifier。
- favicon inline-SVG 宜抽成模块常量 `_FAVICON_SVG`（与已抽出的 `_LP_LOGO_SVG` 并列），便于改品牌。
- 书架 URL `/library` 散落 ~19 处硬编码（已二次变更），宜抽 `_LIBRARY_URL` 常量。
- `test_web_server.py::test_index_html` 命名/语义已过期（仍 GET `/`，断言弱），宜重命名或补 `/library` 断言。

## 文件变更汇总

- `src/web/routes.py`：`render_landing` handler；`_ROUTES` `/` → 落地页、新增 `/library` → 书架。
- `src/web/templates.py`：`_BASE_TPL` favicon；`_LP_LOGO_SVG`；`render_landing()`；16 处书架锚点 `/` → `/library`。
- `src/web/static.py`：`.lp-*` 落地页 CSS + hero 渐变 + `lp-fade-up` 动画 + `@media 768` 堆叠；review/advisor 全局 polish CSS；`JS_WIZARD` `?type=drama` 深链；jobs drawer 两处 + 删除成功跳转 `/` → `/library`。
- `tests/test_web_routes_get.py`：`test_library_lists_workspaces`（原 index 测试迁 `/library`）+ 新增 `test_landing_is_root`。

## 不在本轮范围

- 不动后端业务逻辑（reviewer/writer/book_runner/drama_planner happy path）。
- 不开放 drama 站③④（仍 locked，落地页诚实标 Beta）。
- 全站视觉重做（仅落地页 + demo 路径微调）。
- PPT 生成：以「可粘到新 session 的提示词」形式交付，不在本仓实现。
- demo 前测试 workspace 软删清理：提供一键命令，**不自动执行**（改可见数据状态，留用户 demo 前自行运行，可恢复）。
- iter044 遗留 backlog（`_workspace_html_guard` 抽象等）：本轮是 demo 驱动的落地页轨道，未触碰。

## Notes

- 本环境 preview MCP 浏览器网关不可用（`gateway died`），前端验证统一走 HTTP/API 层（curl 逐页 + 关键 DOM）+ 自包含 HTML 预览，未做移动端浏览器截图回归；建议有浏览器环境时补一次落地页 + `?type=drama` + 章节详情的视觉回归。
- 关联：本轮之前的「前端功能实测」（只读，无代码改动）surface 了 4 个 ⚠️（auto-pipeline succeeded vs 章节 Reject 语义、被拒章节前端无 force 出口、blocked 运行不报告 cost、短中文样本 `en_` 前缀），与本轮落地页无关，记为后续 iter robustness backlog。
