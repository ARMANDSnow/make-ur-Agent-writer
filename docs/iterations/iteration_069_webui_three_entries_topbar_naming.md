# Iteration 069 - 前端 UX 改版：三功能入口 + 顶栏精简 + 命名/叙事一致性

## Context

用户在书架页（`/library`）与首页（`/`）暴露 5 类 UX 问题：① 顶栏 `☰`/`⌂`/`⋯` 桌面端冗余；② 首页「打开已有作品」与底部「打开书架」重复；③ 首页混入了"作品内导航"按钮；④ 误以为前端只能跑 mock（其实能跑真模型，由服务端 `OPENAI_MODEL` 决定，默认 mock）；⑤ 产品其实有三个功能（导入续写 / 一句话开新书 / 短剧剧本），但 premise「一句话开新书」后端早已实现、前端却被埋在向导「第1步·上传」面板底部，首页无卡、step0 类型选择也没它。

本轮把三功能在首页与向导里平等暴露，精简顶栏，给真模型切换加可发现性指引（**不碰 `.env`、不跑真模型做实现/单测**），并修掉因扩范围而自相矛盾的命名/叙事文案。

计划经 26-agent 多视角审核（PM/IA · 视觉设计 · 代码 bug · 测试 + 完整性批判 + 对抗验证）后定稿 v2，落地档为 `~/.claude/plans/ux-1-1-1-3-http-localhost-8765-http-loc-snug-bird.md`。两项用户决策：**(A) `⌂` 保持指向书架 `/library`（不改首页）**——审核核实全站面包屑无一处指向首页，"交给面包屑回首页"是空承诺；**(B) 按「有无原文」重命名 + 统一 drama 术语**。

## Plan

命名规范（单一真实来源）：novel→**导入续写**、premise→**一句话开新书**、drama→**短剧剧本**。

- **改动 1** hero 改名 + 叙事同步 → `templates.py:1333`「开始续写」→「开始创作」；`:1329-1331` h1/lead 扩成兼容「续写 + 开新书」（修 ux-5 自相矛盾）。
- **改动 2** 首页新增第 3 卡「一句话开新书」→ `templates.py:1363` 后插同骨架 `<article>`（badge 正式开放 / 3 feats / footer `btn-secondary` → `/wizard?type=premise`）；CSS `.lp-cards` 固定 3 列 + 1024/768 分段降级（不用 auto-fit）；新增 `.fade-up-4` + 补 reduced-motion，第 3 卡用 `fade-up-3`、trust 顺延 `fade-up-4`。
- **改动 3** 顶栏精简 → `templates.py:1390-1393` 删「＋ 新建」只留「⚙ 设置」；`:111` `APP_CLASS` **新增 `page_kind=="landing"` 显式分支**叠 `lp-chrome`（绝不复用 sidebar_html 三元）；`static.py:1183` 附近加 `.lp-chrome .nav-toggle/.home-btn/.topbar-menu-toggle{display:none}`；landing `⌂` 加 aria-hidden。
- **~~改动 4~~ 取消**（决策 A，`⌂` 保持 `/library`）。
- **改动 5** 删底部重复链接 → `templates.py:1380-1381` 删 `.lp-secondary` 段 + `static.py:1072` 清死 CSS。
- **改动 6** trust 计数 → `templates.py:1371-1372`「2」→「3」、sub 用新命名「导入续写 + 一句话开新书 + 短剧剧本」。
- **改动 7** 向导 2→3 选 1 + 抽 premise 面板 → 7a 加 premise radio（`:1080` 后）；7b 把 `#premise-form`（`:1140-1166`，含 workspace 输入与 expand checkbox 整段）搬出包成 `#panel-premise`（含 card-header/card-body + `#premise-error`），`#upload-error` 留在 upload 面板；7c JS：`panelPremise` 定义 + `show()` 数组加 panelPremise + applyTypeFromQuery/typeForm 三分流 + premiseErrBox 改三处引用 + form 作用域取字段 + errBox/dramaErrBox 守卫统一。
- **改动 8** 真模型可发现性 → `templates.py:1067` 后插独立静态 `<p>`，文案据实（需配 API key + 重启服务），避开 `#wizard-mode-card`（被 JS innerHTML 覆盖）。
- **改动 9** 命名统一 + wizard 副标题修正 → novel 卡 `:1340`/`:1349` + drama 卡 `:1353`/`:1362` 改新名；wizard 副标题 `:1064`「两类」→「三类」（修 ux-5 硬 bug）。

## Acceptance

- 全量单测 `OPENAI_MODEL=mock`：`.venv/bin/python3 -m unittest discover -s tests` 全绿（基线 iter068 后 590+ tests）。
- 重点单测：`test_web_routes_get`（landing 三功能/新命名/无旧文案、wizard premise 面板/radio/真模型链接/`#upload-error` 存活/JS_WIZARD 含 panelPremise·premise-error）、`test_topbar_actions_scope`（不触发 bare 正则）。
- `bash scripts/verify.sh` + `python3 main.py preflight` 通过。
- 前端全方位 E2E（preview MCP，mock）：桌面/中宽/移动三档；hero/三卡/顶栏/trust/三深链/premise 提交/⌂→library/真模型文案/console 无报错（见计划 §验证）。
- 铁律⑨：`/code-review high` + `/security-review` 结论与未修风险回填。
- （可选，用户授权真模型）premise/novel 生成内容走查一次——需 `.env` 已配 key，跑前确认。

## Implementation Notes

9 处改动按计划落地（原改动 4「⌂→首页」按用户决策取消，⌂ 保持 `/library`）。命名规范统一：novel→导入续写、premise→一句话开新书、drama→短剧剧本（含 wizard novel radio `:1075` 一并改齐，计划补漏）。

**计划假设被真实浏览器 E2E 推翻、当场修掉的 2 个真 bug**（这正是 mock E2E 的价值——计划的纯静态推演没覆盖到）：

1. **CSS 源顺序导致 3 列不降级**（grid）。计划把 `.lp-cards{repeat(2)}` 放进 `static.py:921` 既有响应式 `@media(max-width:1024px)` 块——但它在基础 `.lp-cards{repeat(3)}`(`:980`) **之前**；同特异性下后者按源顺序胜出，媒体查询被覆盖。E2E 在 800px 实测到仍是 3 列（224px 挤）。**修复**：把 2 列媒体查询移到基础规则**之后**（`:981+` 新增独立 `@media(max-width:1024px)`）。复测 1280→3 / 800→2 / 375→1 列全对。
2. **移动端 ⚙设置 被连带隐藏不可达**（lp-chrome 过宽）。计划让 lp-chrome 隐藏 ☰/⌂/⋯。但桌面端 ☰/⋯ 本就被 `:288` 隐藏、⚙设置 直接显示；移动端 ⋯（`.topbar-menu-toggle`）是打开 `.topbar-actions` 下拉（内含唯一动作 ⚙设置）的**唯一入口**。lp-chrome 把 ⋯ 在移动端也隐藏 → ⚙设置 不可达。**修复**：lp-chrome 只隐藏 `.nav-toggle`+`.home-btn`，**放过 `.topbar-menu-toggle`**。复测移动端 landing ⋯ 可见、点开下拉 ⚙设置 可达。

**核实后无需改动的审核担忧**（盲区 4/6）：
- 三 form 共用 `name="workspace"`：所有 handler 已是 form 作用域（`new FormData(novelForm/premiseForm/dramaForm)`），无全局 `querySelector`——**已安全**，未改。
- errBox/dramaErrBox 无守卫引用：`#upload-error`/`#drama-error` 始终随面板渲染、无 NPE 风险；本轮仅 premiseErrBox 新增独立守卫引用（`:4696/4714/4724`），不回头改既有两处（铁律⑦），测试断言 `#upload-error` 存活兜底。pre-existing 守卫风格不一致记为小债。
- a11y：`display:none` 已把 ⌂/☰ 从无障碍树移除（a11y snapshot 实测 landing 顶栏只剩「续写工作台」+「⚙ 设置」，⌂/☰/⋯ 不在树内），**无需 aria-hidden**，批判者的「读屏语义噪音」担忧由机制本身解决。

**工具备注**：`preview_click` 在本环境不稳定触发表单 submit / 下拉 toggle 的 JS handler（点击报成功但 handler 未跑）；改用 `requestSubmit()` / `.click()`（派发真实事件）验证，结果正常；后端 `POST /api/wizard/premise-start` 实测 202。

## Acceptance Result

- **全量单测（权威）**：`.venv/bin/python3 -m unittest discover -s tests`（`OPENAI_MODEL=mock`）→ **1319 tests OK**。重点单测 `test_web_routes_get`+`test_topbar_actions_scope` CSS 修复后 **66 OK**；含五文件聚焦集 **103 OK**。
- **preflight**：`OPENAI_MODEL=mock python3 main.py preflight` → FATAL/WARN 均 none。
- **verify.sh**：`PATH="$PWD/.venv/bin:$PATH" OPENAI_MODEL=mock bash scripts/verify.sh` → **exit 0**（`Ran 1319 tests ... OK` + 全 pipeline normalize/split/auto-pipeline/drive-book 跑通）。注意：**必须把 `.venv/bin` 放进 PATH**，否则裸 `python3` 缺 pydantic 会产 170 个 `_FailedTest` 导入错误致 exit 1（既存环境现象，memory `novel-tests-need-venv-python` + iter068 门禁均记录，非本轮 bug）。
- **前端 E2E（preview MCP，mock，三档视口）**：
  - 桌面 1280：hero「开始创作」+「打开已有作品」+ 新叙事；顶栏仅「⚙ 设置」（a11y 树确认无 ⌂/☰/⋯）；3 卡（导入续写/短剧剧本/一句话开新书）等宽等高；trust「3 / 导入续写 + 一句话开新书 + 短剧剧本」；无底部重复链接；**3 列**。
  - 中宽 800：**2 列**（348px 等宽，无挤压 3 列孤行）。
  - 移动 375：landing **1 列**；⌂/☰ 隐藏、⋯ 可见且点开下拉 **⚙设置可达**；wizard `app no-context`（无 lp-chrome）→ ⌂/⋯ 可见、☰ 隐藏（无侧栏）。
  - wizard 3 选 1：radio novel/drama/premise；副标题「…三类工作流相互隔离」；真模型据实指引 + `/settings`；`#upload-error`/`#premise-error` 双容器。
  - 深链：`?type=premise`/`?type=drama` 各**唯一显示**对应面板（三面板互斥验证）；radio 同步选中；premise 面板含 card-header「第 1 步 · 一句话开书」+ workspace 输入 + expand(checked 保留) + 返回按钮。
  - premise 提交（mock，`requestSubmit`）→ 创建 workspace → 跳 `/w/<name>/workbench`（pageKind workbench）。
  - workspace 页 ⌂ `href="/library"`、aria「返回书架」、可见；面包屑首项「书架」→/library 可点。
  - `preview_console_logs` 全程无 error/warn。
- **代码审查（铁律⑨）**：
  - `/code-review high`（4 视角 finder：逐行正确性 / 删除行为 + 跨文件 / 复用-简化-效率 / 铁律合规）→ **0 个需修 bug**。Agent A 逐行零 bug；Agent B 的 6 条候选全 REFUTED（均为「若有人未来误删 #upload-error/#premise-error」「若 page_kind 改错」「若响应式重排卡片」之类推测，且本轮测试已断言两容器存在 + E2E 已证当前逻辑正确；library 空状态提示指向「＋ 新建」对 /library 正确——该页保留该按钮，landing 无 empty_hint）；Agent C 仅 2 条低价值风格建议（clearErrorBox helper / premiseForm guard 去留），按铁律⑦ scope 收敛不做。**合规：无铁律违反**（无龙族原文、测试全 mock、scope 未扩散）。
  - `/security-review`（对口铁律①）→ **无 HIGH/MEDIUM 安全发现**。核实：premiseErrBox 错误渲染经 `renderErrorCard`→`escapeHtml`（转义 `&<>"'`）完整转义，无 XSS；真模型指引为静态文案、不泄漏 key、不渲染 .env；premise 重定向用 `encodeURIComponent`；workspace 输入 pattern 仍单源自后端 `WORKSPACE_NAME_HTML_PATTERN`、未削弱；搬运 premise 面板不改任何转义/数据流。
  - **未修风险**：JS 错误容器守卫风格不一致（novelForm/dramaForm 无 `if` 守卫、premiseForm 有）属既存小债，因 `#upload-error`/`#drama-error` 始终随面板渲染、无 NPE 触发路径，本轮不扩 scope 修（铁律⑦），测试断言 `#upload-error` 存活兜底。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | landing hero 改名+叙事/3 卡（含 drama 卡改名）/trust 计数+术语/顶栏精简删＋新建/删 lp-secondary + `_render_shell` APP_CLASS 加 `page_kind=="landing"` lp-chrome 分支 + wizard 副标题两类→三类/novel·premise radio/premise 面板抽出(`#panel-premise`+`#premise-error`)/真模型据实指引（改动 1/2/3/5/6/7a-7b/8/9） |
| `src/web/static.py` | CSS：`.lp-cards` 固定 3 列 + 独立 `@media(1024)` 2 列降级（源顺序修复）+ `.lp-chrome`（仅隐藏 ☰/⌂）+ `.fade-up-4`(+reduced-motion) + 删 `.lp-secondary`；wizard JS：`panelPremise`/`premiseErrBox` 定义、`show()` 数组、applyTypeFromQuery+typeForm premise 三分流、premiseForm 三处改指 `premiseErrBox`（改动 2/3/7c） |
| `tests/test_web_routes_get.py` | `test_landing_is_root` 命名+新覆盖（开始创作/导入续写/一句话开新书/进入开新书/`?type=premise`/trust 3/否定 `>开始续写</a>`·lp-secondary·＋新建/lp-chrome）；`test_wizard_renders_type_choice_panels` premise radio+面板+三类+真模型链接+双错误容器+否定 lp-chrome+JS_WIZARD(panelPremise/premiseErrBox/premise-error/三面板互斥) |

## 不在本轮范围

- premise「一句话开新书」首次访问 / 空状态 / onboarding 完整体验（mock 下扩写为占位的引导）。
- settings 页给 `OPENAI_MODEL` 专属说明分区 + 模型变更触发 `#restart-banner`。
- 方案 B（`⌂`→首页 + 面包屑加首页节点）——本轮按决策 A 不做。
- hero 改名 / 卡片重命名对外部截图、教程的迁移成本（文档侧）。

## Notes

- 审核挡掉的假 bug（bug-1 blocker / bug-2/4/6/7）是"假想实现者违背计划"的稻草人，计划照写不触发，未纳入实现。
- ia-2（hero 与卡片冗余）按用户已敲定"两条路都留"保留，仅记录。
- v1→v2 修订对照见计划文末「修订说明」。
