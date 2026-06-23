# Iteration 063 - codex iter062 复审 bug 收口 + 后端审查①-⑦ + readiness 目录合并 + 移动端导航 + iter061 登记

## Context

iter062 完成「前端 UX 重构」（报错收口 + 导航补全 + 假按钮上锁，commit `5715c0e`）后，codex 用 3 视角 subagent + Playwright 真浏览器复审，发现 **7 个回归/遗漏**（2×P1、4×P2、1×P3）；同时 iter062 把一批 **后端代码审查发现①-⑦** 与 **iter061 四处登记补全** 显式顺延本轮（见 `iteration_062_webui_ux_refactor.md`「不在本轮范围」+ `docs/AGENT_HANDOFF.md` 末尾）。

关键发现：**codex P2-3（timeout 校验后被丢弃）= 后端审查②**，两边独立复现同一 bug，本轮一处修复同时收口。

本轮把 iter062 前端重构暴露的 bug 全部收口，把顺延的后端审查①-⑦清零，合并三份 readiness 目录、补齐 iter062 新导航元素的移动端适配、补全 iter061 文档闭环。用户已确认范围：codex 7 bug + 后端①-⑦全收 + iter061 登记 + 移动端 drawer 响应式 + 三份 readiness 目录合并。**drama 站③④实做、KB 起点过滤升级不在本轮。**

## Plan

**Part A — codex 前端复审 bug（7）**
- `#A1` P1：plan-chapters 裸露 `ValueError: stale debate outline…` → jobs `_step_plan_chapters` 捕获转 `blocked(outline_stale)` + errors 目录 + 前端 `pollJob` 终态卡化
- `#A2` P1：部分按钮/后端仍绕过 error card → 后端剩余裸 `str(exc)` 收口为 card（drama/start_job/draft-meta）+ 前端 drama/草稿 handler 补强
- `#A3` P2：wizard 上传错误卡英文技术化 → `_UploadRejected` 加 code + errors 目录 `upload_no_chapters`/`upload_not_utf8`/`invalid_workspace_name`
- `#A4` P2：wizard `pattern` Chromium invalid regex → CJK unicode escape（退化可去 pattern）
- `#A5` P2（=后端②）：write-book/plan-chapters timeout 校验后丢弃 → 两 validator 携带 `timeout_minutes`
- `#A6` P2：章节页「点击任意一行」文案误导 → 改「续写行可点击」
- `#A7` P3：`/chapter/N#edit` 深链不进编辑 tab → `_ALLOWED_TAB_KEYS` 加 `edit`

**Part B — 后端审查①③④⑤⑥⑦（②已并入 A5）**
- `#B①` 孤儿版权样本取消即泄漏（中危·版权护栏）→ 上传前 glob 清扫 + read 后全程 try/finally
- `#B③` `/run` timeout 无 maximum → 顶层校验加 `maximum=1440.0`
- `#B④` 坏 meta 被覆盖 → 降级空 `{}` 时跳过写回
- `#B⑤` readiness clamp 静默截断 → 响应加 `clamped`/`warning`
- `#B⑥` iter061 token 非法回落固定路径（后门）→ 无合法 token/样本返回 blocked，不回落 clobber 路径
- `#B⑦` drama/plan reservation 窗口偏窄 → 扩大 reservation 覆盖 `drama_planner.run`

**Part C — 三份 readiness 目录合并**：抽核心层 `src/readiness_catalog.py`；`book_runner` + `web/errors.py` 改调；前端注入 `window.READINESS_CATALOG` + 漂移守卫测试。

**Part D — 移动端 iter062 新导航元素响应式**：preview 768/480px 实测 topbar/stepbar/error-card/drama tab + 抽屉，`@media` 微调。

**Part E — iter061 四处登记补全 + iter063 文档闭环**：新建 `iteration_061_PLAN.md`、补索引、README SOP 表、AGENT_HANDOFF Phase Status。

## Acceptance

- `OPENAI_MODEL=mock python3 -m unittest discover -s tests` 全绿（基线 1201 OK / skipped=6；新增断言后 ≥1201）
- `OPENAI_MODEL=mock bash scripts/verify.sh` exit 0（裸/空仓库 graceful degrade）
- `OPENAI_MODEL=mock python3 main.py preflight` 无 FATAL/WARN
- `node --check` JS_DASHBOARD / JS_WIZARD / JS_SETTINGS 三 bundle
- iter026 锁 6 标识符/表达式全保留
- preview 手测：stale-outline 友好卡 / bad txt 中文卡 / wizard console 无 regex error / 章节页文案与可点行一致 / `#edit` 深链 / drama 失败卡 / 768·480px 响应式
- 结果留给 iter-finish 回填

## Implementation Notes

**A1（stale outline）——真业务阻断，不自动放行**：`plot_planner` 的 stale-outline 是 052 跨时间线事故后**刻意的硬阻断**，自动 `--allow-stale-outline` 会重蹈"陈旧大纲污染续写"。故只做两件事：jobs `_step_plan_chapters` 把该 `ValueError` 捕获转 `blocked(outline_stale)`；前端 `pollJob` 终态非 succeeded 改渲 `renderJobFailureCard`（友好卡 + CTA），**顺带收口所有 blocked/failed job 的裸 `reason · error` 行**（不止 stale outline）。preview 实测 plan-chapters blocked → `#plan-status` 渲赭石卡「未设置续写起点」+「去设置起点」CTA，持久不被 `refreshReadiness` 冲掉。

**A2（裸 str(exc) 收口）——沿用 iter062 约定**：4xx/FNF 保 `error=str(exc)` + 加 `card`（drama 500 的 `creation_standard.snapshot` / `station 1` 明细对用户有用、substring 测试不破），前端 `errTitle(err)` 优先读 `payload.card.title`（17 处错误 toast 统一升级）。草稿保存改走 `#draft-edit-status` 的 `renderErrorCard`（有就近容器）；drama 各 mutation 保留 toast（非阻断、现已带友好 title）。

**A3（wizard 上传 card）**：`_UploadRejected` 加 `code`，仅 `start_upload`（小说上传）走 card；premise / drama-start 的"invalid workspace name"仍是英文串（scope 收敛，留后续一致化，见 Notes）。

**A4（pattern regex）——根因定位**：Chromium 以 RegExp `v` flag 编译 HTML `pattern`，字符类里**裸 `-`** 是 SyntaxError。最小修复=转义那个尾随连字符 `\-`，CJK 范围 `一-鿿` 本身合法保持不变（3 个 workspace 输入框）。preview 实测：`checkValidity()` 正确放行合法名/拒绝非法名，控制台零 regex error。

**A5+③（timeout）**：codex P2-3 = 后端审查②，一处修复同收。两个 validator 校验后把正 `timeout_minutes` 带回 `out`；顶层 `_validated_run_params` 加 `maximum=1440.0`（③，对齐 wizard，堵超大有限假死线）。

**①（孤儿版权样本）**：`_step_extract_style` 把 read→progress_cb→extract 全程包进 try/finally（cancel 仍 unlink）+ 上传前 glob 清扫 stale `.writer_style_sample.*.tmp`（job 持 workspace reservation，sweep all-but-mine 无竞态）。

**⑥（token 后门）**：无合法 32-hex token → 直接 `blocked`，删除回落固定 `.writer_style_sample.tmp` 的 clobber 后门。既有 iter061 测试本就期望 blocked，契约不破。

**④/⑤/⑦**：④ 坏 meta 降级 `{}` 时跳过写回（不用 verdict-only stub 覆盖 writer 历史）；⑤ readiness clamp 加 `clamped`（requested/applied）字段不再静默；⑦ drama/plan reservation 扩到包住 `drama_planner.run`（含 prompt-log append），与注释相符。

**Part C（三份目录合并）**：新建 `src/readiness_catalog.py`（核心层、仅 `typing`，避免 `book_runner`→`web` 反向依赖）；`book_runner._primary_blocker`/`_blocker_kind` 与 `errors._READINESS`/`readiness_kind` 全部派生自它；前端注入 `window.READINESS_CATALOG`（`_BASE_TPL` script 块），`CTA_ACTIONS` 改 IIFE 从注入目录构建（`plan_fingerprint_stale` 是 jobActionKind 合成的前端专属 kind，本地保留）。漂移由新增测试守。

**Part D（移动端）——审计结论：已适配，无需新增 @media**：iter044 已建抽屉（`.sidebar.open` + overlay + `nav-toggle` + `@media 768px`），iter062 新元素（topbar ⌂/breadcrumb 省略号、stepbar `flex-wrap`、单一 CTA、`.error-card` 列布局、`.tab-list overflow-x:auto`、drama 状态 pill/锁 tab）在 375px 实测全部正常、页面零横向溢出（drama 锁 tab 经 tab-list 横向滚动可达）。诚实记录：本轮 Part D 是**验证确认**而非新增 CSS（无破即不改，铁律⑦）。

## Acceptance Result

- **单测**：`OPENAI_MODEL=mock unittest discover -s tests` → **1214 tests OK**（基线 1201 + 本轮 +13：A1 blocked 1 / A3 card 断言更新 / A5·③ timeout 3 / ① 孤儿+取消 2 / ⑥（既有断言）/ ④ 坏 meta 不覆盖 1 / ⑤ clamped（既有测试加断言）/ Part C 漂移守 4 / 审查补漏 queued-cancel 清扫 1 / bundle 断言更新）。非沙箱执行；普通沙箱因 loopback bind 测试会误报 PermissionError（codex 复审已记录，非本轮引入）。
- **verify.sh**：`OPENAI_MODEL=mock bash scripts/verify.sh` exit 0（py_compile 含新 `readiness_catalog.py`；mock auto-pipeline 全链通；裸/空仓库 graceful degrade）。
- **preflight**：`python3 main.py preflight` 无 FATAL / WARN。
- **node --check**：JS_DASHBOARD / JS_WIZARD / JS_SETTINGS 三 bundle 语法全过；Python 无 SyntaxWarning。
- **preview 实景验证**（mock，建临时 demo_novel + demo_drama 后已清理）：
  - A4：wizard 页 workspace `pattern` `checkValidity()` 正确放行合法名/拒绝非法名，**控制台零 regex error**（375px）。
  - A3：bad txt 上传 → `{"error":"没找到章节标题","card":{code:"upload_no_chapters",cause:中文可操作}}`。
  - A1：continue 页「重生成并覆盖计划」blocked → `#plan-status` 渲赭石 error-card「未设置续写起点」+「去设置起点」CTA，跨轮询持久。
  - A5/⑤：`/readiness?chapters=99999&resume_from=88888` → `chapters` clamp 2000 + `clamped:{chapters:{requested:99999,applied:2000},resume_from:{...}}`。
  - A7：`/chapter/1#edit` → activeTab=edit、editPanelActive=true。
  - A6：章节页文案「续写行可点击查看详情（原文行仅供参照）」。
  - Part D：375px 实测 topbar/stepbar/error-card/novel 6-tab/drama 锁 tab + 状态 pill 全部正常，页面零横向溢出（drama 锁 tab 经 `overflow-x:auto` 横滚可达）。
- **代码审查（铁律⑨，web/runner/版权护栏高风险 → `/code-review high` 3 finder 角度 + `/security-review`）**：
  - `/code-review high` 3 条发现**全部处理**：① **F2-1/F2-2**（`renderJobFailureCard` + 终态 toast 对非目录 reason 回落 `retry_exhausted` 掩盖真实错误明细——本轮引入的回归）→ 重构为「直接 readiness-kind 命中才渲友好卡，否则保留真实 error line 作 cause + 经 jobActionKind 给重试 CTA」，toast 同步对齐；② **F3-1**（① 孤儿样本在 job 排队期被取消、handler 未跑时仍可残留——P0-A 护栏窗口）→ `_worker` finally 增 `_cleanup_extract_sample`（按 token 删本 job 样本，覆盖 queued-cancel，+1 测试）；③ **F2-3**（注入 JSON 未转义 `<`）→ `.replace("<","\\u003c")` 结构性防 `</script>` 突破。
  - **未修风险（诚实登记）**：**F3-2** drama `plan`/`hooks` 的 `FileNotFoundError` `error` 字段仍含绝对路径（`hook_designer` "missing {setup_path}"）——**iter062 既有行为**（本轮只多挂 card、未引入），运行面为 127.0.0.1 单用户本地工具、`card.technical` 默认不下发，低危；一致化到 card-only error 需改核心 drama 模块 + 动 substring 测试，留 backlog。**F3-3** A5 timeout 校验 `maximum=1440` 在 3 处重复（debt，可抽 helper）；**F3-4** `result["clamped"]` 未命名空间隔离（低，runner readiness 现无同名字段）；**F3-5** `_blocker_kind` 已是 `classify` 薄别名（待全仓引用切换后 iter064 可删）。
  - `/security-review`：**无 ≥MEDIUM 漏洞（本轮新引入）**。模板注入已 `<` 转义结构性防突破；extract token 32-hex 校验 + 路径在 data_dir 内重建、`_cleanup_extract_sample` 同校验，无穿越/任意删除；draft-meta 改 card 后原 exc 仅进 stderr（泄漏比改前更少）；④/⑤/⑦ 均 fail-safe/收紧无安全影响。
  - 回归确认干净：iter026 锁 6 标识符/表达式全保留（bundle 断言）；`error` 字段向后兼容（drama/start_job 4xx 保 str(exc)+加 card）；Part C 派生后 `_blocker_kind`/`readiness_card`/`_primary_blocker` 行为与原等价（classify 等价性 + 漂移守测试）。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/readiness_catalog.py`（新增） | Part C 核心层单一目录：`KINDS`（label/cause/cta_action/cta_label）+ `classify()` + `fields_for()`；仅 `typing` 依赖 |
| `src/web/errors.py` | A1 outline_stale + A3 三个上传/校验 code + A2 draft_meta_unsynced 进 `_CATALOG`；Part C `_READINESS`/`readiness_kind` 改派生自 `readiness_catalog`；导入 `readiness_catalog` |
| `src/web/jobs.py` | A1 `_step_plan_chapters` 捕获 stale outline→blocked；① 孤儿样本 try/finally + glob 清扫；⑥ 无效 token→blocked 不回落 |
| `src/web/routes.py` | A2 drama plan/hooks/start_job 加 card（保 error 串）+ draft-meta 改 card；A5 两 validator 携带 timeout；③ 顶层 timeout `maximum=1440`；⑤ readiness `clamped` 字段；⑦ drama/plan reservation 扩到包 run |
| `src/web/wizard.py` | A3 `_UploadRejected` 加 `code` + 两 raise 站带 code；上传/名校验走 `errors` card；导入 `errors` |
| `src/web/static.py` | A1 `renderJobFailureCard` + `pollJob` 终态卡化；A2 `errTitle` + 17 处错误 toast 改用它 + 草稿保存走 statusBox card；A7 `_ALLOWED_TAB_KEYS` 加 `edit`；Part C `CTA_ACTIONS` 改从 `window.READINESS_CATALOG` 构建 |
| `src/web/templates.py` | A4 pattern 转义连字符（3 处）；A6 章节页文案改「续写行可点击」；Part C 注入 `window.READINESS_CATALOG`（`_BASE_TPL` + `_render_shell`）；导入 `json`/`readiness_catalog` |
| `src/book_runner.py` | Part C `_primary_blocker`/`_blocker_kind` 改调 `readiness_catalog`；④ 坏 meta 降级时跳过写回；导入 `readiness_catalog` |
| `tests/*`（新增/更新） | test_web_errors（Part C 漂移守 + outline_stale + 上传 code）、test_web_jobs_dispatch（A1 blocked）、test_web_wizard_e2e（A3 card 断言）、test_float_finite_guard（A5/③ timeout）、test_int_finite_guard（⑤ clamped）、test_bad_json_blockers（④ 不覆盖）、test_web_writer_style（① 清扫+取消）、test_web_routes_get（bundle 断言更新） |
| `docs/iterations/iteration_061_PLAN.md`（新增） + `iteration_063_*.md`（新增） + `iterations/README.md` | Part E iter061 补登记 + iter063 本轮记录 + 索引 |

## 不在本轮范围

- drama 站③④（分镜/角色）实做。
- KB 起点过滤升级为主动 blocker。
- 真模型 capstone 复跑。
- `.env`/`data/`/`outputs/`/`小说txt/` 一律不碰。

## Notes

- **关键定性沉淀**：
  - codex P2-3（timeout 丢弃）与后端审查②是同一 bug，独立复现互相印证；一处修复同收。
  - A4 根因是 Chromium `v`-flag 把字符类里裸 `-` 当 SyntaxError——不是 CJK 范围的问题；最小修复只转义连字符。
  - A1 的 stale outline 是**刻意硬阻断**（052 事故护栏），正确做法是友好卡 + 重新生成大纲 CTA，**不能**自动 `--allow-stale-outline` 放行。
  - Part D 审计发现 iter062 新元素已被 iter044 抽屉 + `flex-wrap`/`overflow-x:auto`/省略号既有规则覆盖，375px 实测无破——本轮不新增 @media（无破即不改）。
- **后续候选**：premise / drama-start 的"invalid workspace name"仍是英文串，可一致化为 card（与 A3 同款，留 backlog）；drama 锁 tab 在移动端虽可横滚但缺明显滚动提示（低优）；drama 站③④实做、KB 起点过滤升级仍未做（用户本轮明确排除）。
- **已知 pre-existing flaky**：`test_web_draft_edit.test_busy_workspace_returns_409` 在满量 `discover`（~5min、负载高）下偶发 `workspace_busy`（`_drive_to_written_chapter` 的后台 job 在 line 182 抢锁前未及释放 reservation 的时序竞态）；单独跑稳定通过、与本轮改动无关（未触碰 write/draft job 路径）。登记备查。
- 对铁律的影响：无新增/修改铁律；Part E 补全 iter061 四处登记是对铁律⑧的事后闭环。
