# Iteration 064 - Codex findings 收口：CLI/Web 健壮性对齐 + 硬化

## Context

Codex 对仓库做了一轮只读调研，提出 2 条 P1 + 4 条 P2。本轮用 6 个只读 agent 逐条核验代码，**6 条全部属实（confirmed）**。核心问题：同一业务在 **Web 路径已有守门 / 友好出口，CLI/driver 路径却没有**——形成两套体验，且含真实的资源/安全风险（大章数 `list(range(...))` OOM、预算守门被 NaN 绕过、drama 错误卡泄漏绝对路径、前后端 workspace 名校验发散）。

本轮范围（与用户确认）：**只做前 5 条有界硬化 + Aeloon 文档登记一行**。第 6 条「语义闭环」（计划履约 reviewer / outline drift 行为闭环 / entity 新建关系）是 large 级核心写作循环设计改动，推迟到 iter065+（见「不在本轮范围」）。主题统一为 **操作者侧 CLI↔Web 健壮性对齐**。

铁律对照：① 不碰 `.env`/`sk-`；③ 单测 `OPENAI_MODEL=mock`；⑦ scope 收敛（语义闭环明确推迟）；⑧ 收官同步 README SOP；⑨ 收官跑 `/code-review high` + `/security-review`。

## Plan

- **#1（P1）CLI/driver 数值守门统一**：新建核心层 `src/run_params.py`（cap 表 + `validate_int`/`validate_float`/`validate_run_params`，仅依赖 `math`/`typing`）。Web 的 `routes._int_value`/`_float_param`、`wizard`、`jobs._float_param` 改薄包装复用（行为不变，回归门 `test_int/float_finite_guard.py` 保绿）。`main.py` 4 个 arm（write-book / write-readiness / write / plan-chapters）加硬拒绝校验（exit 2）。`book_driver._build_params` 加校验。`book_runner` 末线防御保留 + `budget_check_cb` 加 `math.isfinite` 守门。
- **#2（P1）plan-chapters stale-outline 出口统一**：`plot_planner` 定义 `OutlineStale(ValueError)`（message 不变），`jobs.py` 改 isinstance 分支，`main.py` plan-chapters 加 try/except 复用 `readiness_catalog` 文案 + exit 4。
- **#3（P2）移动端 `.topbar-actions` CSS 作用域**：`static.py` 三个移动选择器加 `.topbar-actions-wrap` 前缀，避免误伤内容区按钮（概览删除作品 / 章节详情返回链接）。
- **#4（P2）错误卡 cause 路径脱敏**：`errors.py` 加 `_redact_paths`，`card_for_exception` 对 detail 应用；`hook_designer` 源头改用 `setup_path.name`。
- **#5（P2）workspace HTML pattern 单源化**：`_naming.py` 暴露 `WORKSPACE_NAME_HTML_PATTERN`，`templates.py` 引用，杜绝前后端发散（`foo-` 一致拒绝）。
- **#6（文档）**：`docs/AELOON_INTEGRATION.md` 登记 vendored baseline=iter062、iter063 待下次同步。

## Acceptance

- `OPENAI_MODEL=mock python3 -m unittest discover -s tests`：≥1214 + 新增，OK (skipped=6)。
- `OPENAI_MODEL=mock bash scripts/verify.sh`：exit 0。
- `OPENAI_MODEL=mock python3 main.py preflight`：FATAL/WARN none。
- 端到端：`main.py write-book --chapters 999999999` → exit 2 不 OOM；`--budget-cny nan` → exit 2；plan-chapters stale outline → exit 4 + 友好文案无 traceback。
- 移动端 375px：概览「删除作品…」、章节详情「返回章节列表/回概览」可见。
- `node --check` 改动的 JS bundle（若有）。
- 收官 `/code-review high` + `/security-review` 结论回填本文件。

## Implementation Notes

**核验**：起轮前用 6 个只读 agent 逐条核验 codex findings，**6 条全部 confirmed**；第 6 条「语义闭环」large 级，与用户确认推迟 iter065+。

**Item 1（数值守门统一）**：
- 新建核心层 `src/run_params.py`（仅依赖 `math`/`typing`，镜像 `readiness_catalog.py` 无 web 反依赖）：`INT_CAPS`/`FLOAT_CAPS` cap 表 + `validate_int`/`validate_float`/`validate_run_params`。
- Web 侧改薄包装复用：`routes._int_value`/`_float_param` → 转调 `run_params.*`（保留原名+签名，回归门 `test_int/float_finite_guard.py` 不动即绿）；`routes._validate_write_book_params` 的 cap 元组改读 `run_params.INT_CAPS`（cap 真正单源）；`wizard._optional_float` → `validate_float(allow_blank=True)`。`routes.py`/`wizard.py` 移除因此空出来的 `import math`。
- **方案选择（scope 收敛）**：`jobs._float_param`（返回裸 float + 回退 default 的防御纵深层）**保持不动**——它契约不同（无 (err,val) 元组），强行套共享模块徒增风险，且它已自带 `math.isfinite` 守门。cap 表单源目标已达成。
- CLI：`main.py` 加 `_validate_cli_run_params(raw, *, fields)`，在 write-book/write-readiness/write/plan-chapters 四个 arm 顶部硬拒绝（`SystemExit(2)`，对齐 argparse 用法错误码，与 runner 的 1/3/4 不撞）。plan-chapters 的 `args.chapters` 按 `target_chapters`(1..200) 校验（传显式 dict，因 argparse dest 是 `chapters`）。
- driver：`book_driver._build_params` build 前校验——确认驱动器是 subprocess 重调 `main.py`，但 `plan_segments(chapters,...)` 在**驱动器进程内**分段，huge chapters 会在 spawn 前 OOM，故 driver 自身必须守门。校验「与 dict 同款 effective 值」（含 `nan or 0.0`=nan 的真值陷阱，会被 finite 守门拒）。
- runner：`book_runner` 加 `import math` + budget `if not math.isfinite(budget_cny): budget_cny = 0.0`（程序化调用方末线防御，降级为「无预算上限」既有默认路径，避免 NaN 传播）。

**Item 2（outline_stale 出口统一）**：`plot_planner` 定义 `OutlineStale(ValueError)`（带 `codes`/`kind`，message 字节级不变 → `test_iter053a` 的 `assertRaises(ValueError)` 全绿）。`jobs.py` 用 `isinstance(exc, OutlineStale) or "stale debate outline" in msg`——**踩坑**：`test_web_jobs_dispatch` 故意注入**裸 ValueError** 模拟，纯 isinstance 会漏，故保留字符串兜底作防御纵深，typed 路径用 `exc.kind`。`main.py` plan-chapters 加 `except OutlineStale` 复用 `readiness_catalog.KINDS["outline_stale"]` 文案 + `SystemExit(4)`。

**Item 3（CSS 作用域）**：grep 确认 `.topbar-actions-wrap` 仅壳层（templates:72 包 74；内容用法 341/892 在 wrap 外；JS closeTopbarMenu 也只认 wrap）。`static.py` 三个移动选择器加 `.topbar-actions-wrap ` 前缀，内容按钮在移动端落回桌面 flex（static:290）→ 可见。无需改 JS。

**Item 4（路径脱敏）**：`errors.py` 加 `_redact_paths`（正则 `/(?:[^/\s]+/){1,}[^/\s]+`，要求前导 `/`+≥2 段，避免误伤 `3/4`/`a/b`/`TCP/IP`），在 `card_for_exception` 对 `detail` 应用（`technical` 保持原始供维护者 stderr）。**方案选择**：**不改** `hook_designer.py` 源头——中央脱敏已完整覆盖且保留 stderr 全路径调试信息，源头改 `.name` 反而丢调试信息且扩大改动面。
- **收官审查补漏（同类泄漏）**：审查发现 codex 只点了 `card.cause`，但 routes.py **12 处** handler 返回 `{"error": str(exc), "card": card_for_exception(exc)}`——card 脱敏了，**裸 `error` 键仍是未脱敏 `str(exc)`**，路径经它照样进客户端 JSON。新增 `errors.exception_body(exc)`（两字段都脱敏）替换全部 12 处，彻底堵死。非路径 message 经 `_redact_paths` 是 no-op，向后兼容（断言 `error` 键的测试都 `assertIn` 无路径文案，不破）。wizard 的 3 处 `{"error": str(exc)}` 是受控 `_UploadRejected` 用户文案（无路径），不在范围。

**Item 5（pattern 单源）**：`_naming.py` 暴露 `WORKSPACE_NAME_HTML_PATTERN`（转义 `\-` 满足 Chromium `v` flag；非捕获可选组禁尾部连字符）。`templates.py` 3 处（都是 `name="workspace"` 输入）统一改 f-string 引用——发现不止 line 1104 一处，3 处同病同治。

**Item 6（文档）**：`docs/AELOON_INTEGRATION.md` 加 §11.4 登记 vendored baseline=iter062、iter063/064 待同步。**注意**：该文件含用户并行 PR #541 的 90 行在途未提交改动，iter064 代码提交**不纳入**此文件（留给用户的 Aeloon 提交，也是该 note 的天然归属）。

## Acceptance Result

**门禁（铁律③/④）**（注：本环境必须用 `.venv/bin/python3`，裸 `python3` 缺 pydantic 报 169 import error）：
- `OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests`：**1250 tests OK**（基线 1214 + 36 新增；skipped 同基线）。
- `OPENAI_MODEL=mock bash scripts/verify.sh`：**exit 0**。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：**PREFLIGHT_EXIT=0，无 FATAL**。
- 端到端坐实：`write-book --chapters 999999999` → exit 2（不再 OOM，`tests.test_run_params.CliRunParamGuardTests` 覆盖）；`--budget-cny nan`/`--min-confidence 2` → exit 2；plan-chapters typed `OutlineStale` → exit 4 + readiness 友好文案、无 traceback（`tests.test_iter053a_outline_guard` 覆盖）。
- 回归门：`test_int/float_finite_guard.py` 原样保绿（证 Web 行为不变）。

**审查（铁律⑨）**：3 维度 workflow（correctness/security/reuse）+ 对抗验证。
- **correctness：零真发现**（Web delegation 行为不变、exit 码不撞、f-string pattern 安全、CSS 作用域不破壳层 toggle 均经验证）。
- **reuse/simplify：零真发现**（导入全用上、无死代码、`math.isfinite` 仍在 `book_runner` 用、`_validate_cli_run_params` vs `_build_params` 不同入参形态不应合并、OutlineStale exit4 块单用清晰）。
- **security：1×P1 已修**——`_redact_paths` 原 `[^/\s]` 排空格，父目录含空格路径会从空格截断泄漏后续树 → 改 `[^/]`（过度脱敏 fail-safe）。**自查补漏**：codex 只点 `card.cause`，但 12 处 handler 裸 `error` 键同样泄漏（= 既有 backlog F3-2）→ `exception_body` 两字段脱敏全替换。
- 铁律①自查：无新增 `sk-`/`.env`/key 打印或读取路径。

**未修风险（诚实登记）**：F3-3 timeout 校验 3 处重复 debt（顺延）；`_blocker_kind` 薄别名（F3-5，顺延）；语义闭环 large 推迟 iter065+。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/run_params.py` | **新增**：cap 表 + `validate_int`/`validate_float`/`validate_run_params`（CLI/Web/driver 单一真源） |
| `src/web/routes.py` | `_int_value`/`_float_param` 转薄包装；write-book validator 改读 `run_params.INT_CAPS`；移除空 `import math` |
| `src/web/wizard.py` | `_optional_float` 转 `validate_float(allow_blank=True)`；移除空 `import math` |
| `src/web/jobs.py` | `OutlineStale` 导入；stale 分支改 `isinstance or 字符串兜底` + `exc.kind` |
| `main.py` | `run_params` 导入 + `_validate_cli_run_params`；4 个 arm 加硬拒绝校验；plan-chapters 加 `OutlineStale` 友好出口 |
| `src/book_driver.py` | `_build_params` 加 `validate_run_params`（OOM 点 plan_segments 前守门） |
| `src/book_runner.py` | `import math` + budget `math.isfinite` 末线守门 |
| `src/plot_planner.py` | 新增 `OutlineStale(ValueError)`；raise 点改用之 |
| `src/web/errors.py` | `_redact_paths` + `card_for_exception` 对 detail 脱敏 |
| `src/web/_naming.py` | 暴露 `WORKSPACE_NAME_HTML_PATTERN` 常量 |
| `src/web/templates.py` | 3 处 workspace 名输入改引用单源 pattern |
| `src/web/static.py` | 移动端 `.topbar-actions` 3 选择器加 `.topbar-actions-wrap` 作用域 |
| `docs/AELOON_INTEGRATION.md` | §11.4 待同步基线登记（不并入 iter064 代码提交） |
| `tests/test_run_params.py` | **新增**：validator 单测 + CLI 守门 SystemExit(2) 测试 |
| `tests/test_web_naming.py` | 新增 HTML pattern ↔ 后端 RE 等价性测试 |
| `tests/test_web_errors.py` | 新增路径脱敏 + prose 不误伤测试 |
| `tests/test_topbar_actions_scope.py` | **新增**：移动端 CSS 作用域断言 |
| `tests/test_iter053a_outline_guard.py` | 新增 typed `OutlineStale` + CLI exit4 映射测试 |
| `tests/test_web_jobs_dispatch.py` | 新增 typed `OutlineStale` dispatch 测试 |

## 不在本轮范围

**第 6 条「语义闭环」（large，已与用户确认推迟 → iter065+）**：
- (a) 计划履约 reviewer：现 5 个 review agent 无一检查本章是否履约 chapter_plan beats；需把 `chapter_plan_item` 穿进 `reviewer.review_text()` 或加后置确定性 beat-matcher。
- (b) outline drift 行为闭环：`outline_drift` 只 warn 从不 block，旧 outline 在 `writer.py:713` 烤进 `stable_context` 长期注入每章 prompt；需 drift 命中率低时重生成或改静态 bake 为动态滚动注入。
- (c) entity 新建关系：`entity_advance.py:238/284` 要求关系对预先存在，否则 `relationship_not_found` 跳过；需允许低置信度新建关系。

其余既有候选（KB 起点过滤安全视图、drama 站③④、章节 diff、全文搜索、真模型 capstone 等）维持原状。

## Notes

**教训**：
- **环境坑**：本机裸 `python3`（homebrew）缺 pydantic，`unittest discover` 报 ~169 个 `unittest.loader._FailedTest` import error，只「Ran 525 FAILED」而非真实 1214——是导入失败非断言失败，险些误判成代码回归。必须用仓库 `.venv/bin/python3`（已写 memory）。
- **并发坑**：两个 `unittest discover` 并发共享 `workspaces/unit*`/`data`/`outputs` fixture 与同一 `.pycache`，互撞出大量 error。要串行单跑。管道 `... | tail` 的 exit code 是 tail 的，不代表 unittest，要 `grep -E "^(Ran|OK|FAILED)"` 看真实结果。
- **审查价值**：收官 workflow 审查抓到 codex 未点的同类泄漏（12 处裸 `error` 键）+ 脱敏正则的空格漏洞（P1）——证明「只修 codex 点名处」不够，同类模式要扫一遍。

**对铁律的影响**：第 8 条/第 9 条按 SOP 执行（README SOP 表 + AGENT_HANDOFF + `/code-review` 等价 workflow + 安全自查）。新增 `src/run_params.py` 是 cap/finite 的单一真源，未来调 cap 只改一处即 CLI/Web/driver 同步。

**后续候选（iter065+）**：见「不在本轮范围」——语义闭环 (a)(b)(c) 为重点；另有 F3-3 timeout 校验抽 helper、`_blocker_kind` 别名清理等小债。
