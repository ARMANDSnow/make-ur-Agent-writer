# Iteration 062 - 前端重构：报错收口 + 导航补全 + 假按钮上锁

## Context

用户基于 iter043 WebUI UX audit 提出「重新设计前端」，痛点三类（用户原话）：
1. **假按钮**：部分按钮看着能点但无实际行为 / 只有空状态（drama ③分镜 ④角色 tab）。
2. **反人类导航**：无法一键回主页、深层页出不来、页面跳转反直觉、工作台单向。
3. **裸代码报错**：异常 `str(e)` / `JSONDecodeError: ...` 直接甩给用户，看不懂、不知道下一步。

iter043 审计是历史起点，多数项在 iter044-060 已修，但上述三类仍有真实残留。本轮先用 visualize 出 3 个「现状 vs 重构后」对比 demo（error_card / navigation / fake_buttons）供用户参考，确认方向后实施：
- **力度**：针对性修复，保留现有 `src/web` 手写架构（ThreadingHTTPServer + string.Template + 单 JS bundle，零外部前端依赖）。
- **错误落点**：两端都做——后端错误目录 + 前端兜底网络/超时/JS 崩溃。
- **范围**：三类全做；移动端 drawer + drama 站文案收口顺延。

> **编号说明**：git 最新到 iter061，但 iter061 是一次未完整登记的 P0 热修（commit `bce579c`，#11 路径穿越；无 PLAN 文件、不在索引）。handoff 末尾原为「iter062」预留的是后端代码审查 7 条发现（①-⑦）。本轮按用户批准，iter062 用于**前端重构**；后端 ①-⑦ + iter061 登记补全顺延 iter063（见「不在本轮范围」）。

## Plan

- **报错友好化 → 预期改动**：新增 `src/web/errors.py` 错误目录（code→人话标题/原因/推荐操作/技术详情）；收口 `routes.py` 约 8 处裸 `str(exc)`，顶层 dispatch 走目录；前端统一 `renderErrorCard` 替换 11 处裸 `escapeHtml(err.message)`；`_fetchWrapped` 分类网络/超时/坏 JSON；`window.onerror`+`unhandledrejection` 全局边界。
- **导航+工作台步骤条 → 预期改动**：`_BASE_TPL` topbar 常驻「书架/首页」按钮；工作台四阶段 → 可点回看步骤条（done/current/locked）；章节详情统一「← 章节列表 + 回概览」；continue/workbench 单一「下一步」CTA（多为复用既有 readiness/workbench 逻辑）。
- **假按钮+就绪 CTA → 预期改动**：drama ③④ tab 明确上锁（disabled+aria+🔒+即将上线），`bindHashTabs` 早退 + 从 `_ALLOWED_TAB_KEYS` 移除；readiness 诊断区裸 code 翻人话、禁用按钮加旁注（保留 iter026 锁定表达式 `submit.disabled = writeBookJobRunning || data.status === 'blocked'`）。
- **新增 CSS**：`.error-card*` / `.stepbar`+`.step.*` / `.tab.locked` / `.home-btn`，复用现有 token。
- **测试**：新增 `tests/test_web_errors.py`；坏 JSON 反向断言无裸异常；bundle/CSS 新断言；核对现有 `data["error"]` 等值断言。

## Acceptance

- `OPENAI_MODEL=mock python3 -m unittest discover -s tests` 全绿（基线 1180，新增 errors + 断言后预期 ≥1180）。
- `bash scripts/verify.sh` + `python3 main.py preflight` 通过（裸/空仓库 graceful degrade）。
- iter026 锁 6 串全保留。
- preview 手测：报错卡渲染 / topbar home / 工作台步骤跳转 / drama 上锁 tab / readiness 人话。
- 结果留给 iter-finish 回填。

## Implementation Notes

**模块 A 报错（两端）**
- 新增 `src/web/errors.py`：纯数据+纯函数错误目录。`code_for_exception` 的 isinstance 顺序刻意把 JSONDecodeError/UnicodeDecodeError（ValueError 子类）、FileNotFoundError/PermissionError（OSError 子类）放在父类前。`technical` 默认不下发客户端（`expose_technical=False`），延续 server.py 顶层「不泄露 traceback」铁律。readiness 文案与 `book_runner._primary_blocker.labels` 逐字对齐（不强行合并三处目录，靠测试守漂移）。
- 后端收口：**约 15 处**裸 `str(exc)`/`f"...{exc}"` 走目录。degrade 路径（overview/drama/plan）`error` 改 card dict、blocker 收敛为稳定 code（`overview_error`/`readiness_error`/`drama_progress_error`），原异常改写 stderr（新 `_log_degraded`）。语义 4xx（ValueError/FNF）保留 `error=str(exc)` + 新增 `card` 向后兼容（测试 `assertIn` 子串不破）。顶层 dispatch 500 保留 `error=="internal server error"`（test_web_hardening 锁）+ 新增带 trace_id 的 card。
- 前端：统一 `renderErrorCard`+`_normalizeErrorCard`（payload.card→card→code→error/message 兜底）替换 **~23 处**裸 `escapeHtml(err.message)`。`_fetchWrapped` 分类 网络/超时(AbortController 30s，轮询 URL 白名单豁免)/坏 JSON；`fetchJson/postJson/putJson` 转调它（DRY，`_httpError` 由 3 处内联收成 1 处）。全局 `window.onerror`+`unhandledrejection` → 轻量 toast。
- **踩坑**：三个 JS bundle（JS_DASHBOARD/JS_WIZARD/JS_SETTINGS）各自独立 IIFE、helper 不共享。JS_WIZARD 无 `renderErrorCard`/`_httpError`，按项目「每 bundle 自带 helper」惯例补了一份精简 `renderErrorCard`；JS_SETTINGS 无该 helper，改自洽友好文案。

**模块 B 导航**：`_BASE_TPL` topbar 加常驻「书架/首页」⌂ 按钮（CSS `.topbar .breadcrumb{margin-right:auto}` 把 actions 推右、home+面包屑左聚）；工作台加可点回看步骤条（`renderStepbar` 用 has_kb/has_outline/has_plan/stage 判 done/current/locked，`#stage-*-card` 锚点 + `scroll-behavior:smooth`）+ 单一「下一步」CTA；章节详情加「回概览」。

**模块 C 假按钮**：drama ③④ tab `disabled aria-disabled` + 🔒 + 即将上线 pill；`bindHashTabs` click 早退 disabled + 从 `_ALLOWED_TAB_KEYS` 移除 storyboard/characters 防 hash 强切。readiness 诊断区 + 书架卡 + overview 阻断项经 `readinessReasonText` 翻人话（原始 code 折叠在括号）；禁用「开始续写」加 title 说明（`submit.disabled = writeBookJobRunning || data.status === 'blocked'` 逐字保留）。

**审查后修补（铁律⑨ 两视角 subagent + /security-review）**：① P0 wizard cancel 误用 dashboard-only 的 `_httpError`（我引入）→ 改自洽 carrying error；② P1 `bindCtaActions()` 只在 continue 调用→错误卡 CTA 在其它页是死按钮→提到 `boot()` 无条件调用；③ errors.py `readiness_kind` 删 2 行死代码；④ 审查发现另有 **6+ 处** 500 OSError（outline/draft/kb/entity_graph×2/setup/settings.env）仍裸漏 `{exc}` → 同类收口为 card（完成「报错裸代码」目标）；⑤ overview 页阻断项/hint 走人话 + `<h2>` 补 escapeHtml（闭 pre-existing latent XSS sink）。

**与计划偏差**：计划写「约 8 处后端收口」，实际审查暴露同类裸漏共 ~15 处（含 6 处计划外但同 class），全部收口——属完成既定目标而非 scope 蔓延，诚实记录于此（铁律⑦）。

## Acceptance Result

- **单测**：`OPENAI_MODEL=mock unittest discover -s tests` → **1201 tests OK**（exit 0）；web 子集（errors/routes_get/routes_post/settings/plan_edit/writer_style/premise/hardening/bad_json/jobs_dispatch/wizard_e2e）**225 OK**。iter026 锁定 6 标识符/表达式全保留（新增 `test_static_js_iter062_error_and_nav` 复测锁定表达式，双保险）。
- **verify.sh**：exit 0（py_compile 含新 errors.py；mock auto-pipeline 全链路通；裸/空仓库 graceful degrade）。
- **preflight**：无 FATAL。
- **node --check**：JS_DASHBOARD / JS_WIZARD / JS_SETTINGS 三 bundle 语法全过；Python 无 SyntaxWarning。
- **preview 实景验证**（mock，建临时 demo_novel/demo_drama 后清理）：① 顶栏 ⌂ home 渲染并指向 `/library`、无 console error；② drama ③④ tab `disabled+aria-disabled`、点击不切换面板（停 tab-setup）；③ workbench 步骤条 `①current·可点 / ②③④🔒locked`、pill「下一步：生成设定」CTA；④ readiness 主标题「未设置续写起点」、诊断「未设置续写起点 (start_point_missing)」人话+原始码、禁用按钮 title「前置未就绪…」；⑤ 错误卡实景渲染（赭石卡+⚠+人话标题/原因+操作按钮+可复制编号+折叠技术详情）。
- **代码审查（铁律⑨，web 高风险 → 2 独立视角 subagent 并行；ultra 需用户授权未跑）**：发现并**全部修复**——P0 wizard cancel 误用 dashboard-only `_httpError`（本轮引入）；P1 `bindCtaActions` 仅 continue 调用致它页 CTA 死按钮 → 提 boot；P2 errors.py 死代码、6+ 处 500 OSError 仍裸漏 → 同类收口、overview 阻断项/hint 人话化。回归确认干净：iter026 锁全保、`error` 字段向后兼容、无 scope 蔓延、零新依赖。
- **/security-review**：**无 ≥MEDIUM 漏洞**。本轮净改进安全姿态（technical 默认不下发、移除 ~15 处 `str(exc)` 裸漏、settings 不再泄漏 .env 路径、错误卡全字段 escapeHtml）。审查提示的 pre-existing `overview <h2>` 未转义 sink 已顺手补 escapeHtml 闭掉。
- **未修风险**：本轮无遗留 web 缺陷。后端 ①-⑦（孤儿版权样本等，见「不在本轮范围」）顺延 iter063。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/web/errors.py`（新增） | 错误目录：exception/readiness → `{code,title,cause,actions,trace_id,technical}`；`code_for_exception`/`build_card`/`card_for_exception`/`readiness_kind`/`readiness_card`/`error_body`；technical 默认不下发 |
| `src/web/routes.py` | import errors + `_log_degraded`；~15 处裸 `str(exc)` 收口为 card（degrade 路径 error→card dict + 稳定 code；4xx 保 error+加 card；顶层 dispatch 500 加 card）；9 处 500 OSError 走目录 |
| `src/web/settings.py` | import errors；.env 写失败 500 改 card（不再泄漏 .env 路径） |
| `src/web/static.py` | `renderErrorCard`/`_normalizeErrorCard`/`FRONT_ERROR_CATALOG`/`readinessReasonText`；`_fetchWrapped`（网络/超时/坏JSON 分类）；全局错误边界；替换 ~23 处裸渲染；workbench `renderStepbar`+下一步 CTA；drama tab 上锁早退；readiness 诊断/overview/书架卡人话；`bindCtaActions` 提到 boot；新增 CSS（`.error-card*`/`.stepbar`/`.tab.locked`/`.home-btn`/`.badge-soon`）；JS_WIZARD 自带精简 renderErrorCard；JS_SETTINGS 友好文案 |
| `src/web/templates.py` | `_BASE_TPL` topbar 加 ⌂ home 按钮；workbench 加 `#workbench-stepbar` 壳；章节详情加「回概览」；drama ③④ tab `disabled`+🔒+即将上线 |
| `tests/test_web_errors.py`（新增） | 14 测试：exception→code（含子类序）、build_card/trace_id/降级、technical 不下发、readiness 映射、error_body |
| `tests/test_web_routes_get.py` | +5 测试（iter062 bundle/CSS/home/wizard card/坏JSON 无泄漏）；更新 tab whitelist（去 storyboard/characters）+ loadTabPanel（bad_json）+ overview 坏 plan（card.code=bad_json + 无 JSONDecodeError 泄漏） |
| `tests/test_web_plan_edit.py` | 更新 `_httpError` 计数断言（3 内联→1，经 `_fetchWrapped` ×4） |
| `docs/iterations/iteration_062_*.md`（新增） + `docs/iterations/README.md` | 本轮 8 段记录 + 索引 |

## 不在本轮范围

- 移动端 drawer / 移动端导航改造。
- drama 站内正文文案收口（仅做 tab 上锁）。
- 后端三份 readiness 目录合并 + `book_runner._primary_blocker` 改调 errors。
- jobs.py 内 blocked reason 走目录。
- **iter060/061 代码审查 7 条发现（①-⑦）顺延 iter063**：① 孤儿版权样本取消即泄漏（中，版权护栏）② write-book/plan-chapters timeout 校验后被丢弃（中）③ `/run` timeout 无 maximum（低）④ 坏 meta 被覆盖（低）⑤ readiness clamp 静默截断（低）⑥ iter061 token 非法回落固定路径（低）⑦ drama/plan reservation 窗口偏窄（低）。详见 `docs/AGENT_HANDOFF.md` 末尾。
- **iter061 四处登记补全**（iteration_061_PLAN.md + 两处 README）顺延 iter063。
- `.env`/`data/`/`outputs/`/`小说txt/` 一律不碰。

## Notes

- demo 阶段产出 3 个 visualize 对比图，沿用项目米纸/墨/玉/琥珀/赭石配色，保证「在现有壳里改」。
- 关键发现：很多功能已有现成零件（readiness 单一 CTA、409 busy 翻译、workbench stage 数据源），本轮大量是「接线」而非「重写」。
- 后续候选：本轮顺延的后端 ①-⑦；移动端导航；drama 站③④实做。
