# Iteration 048b — 小白四步工作台·前端四阶段页 + 大纲回写

> iter048 串行子迭代 2/3（048a 后端骨架 → **048b 前端工作台+大纲回写** → 048c 细纲只读+重生成+写书兼容）。承接 048a，兑现红队点名的剩余两条修正（`_WORKSPACE_SECTIONS` 入口 + `require_start_point:false`）。本轮做前端页 + stage 探测 + 纯文本大纲回写；细纲仍只读、不碰指纹链。

## Context

048a 已交付后端三件（premise 入口 / `prepare-greenfield` 复合 step / 测 Key 矩阵），但用户还看不到工作台——后端 step 只能用 API 触发。048b 把这些后端积木接成用户可见的**四阶段工作台页** `/w/{name}/workbench`：① 设定 → ② 大纲 → ③ 细纲 → ④ 正文，每阶段一张卡片、`pollJob` 驱动、前一阶段产物就绪才解锁下一张卡。本轮还交付最简单的回写——大纲是纯文本（无 schema、无指纹链），是验证"全程可编辑"承诺的最小切口；细纲/正文阶段复用现有只读视图（细纲的结构化编辑 + 指纹链留 048c）。

红队对初版计划的两条剩余修正在本轮兑现：(1) `_WORKSPACE_SECTIONS` 必须加 workbench 入口（否则侧栏无链接、active 高亮失效）；(2) workbench 的 plan-chapters/write-book 调用必须显式传 `require_start_point:false`（greenfield premise 无前作起点，不能复用 continue 页硬编码的 `true`）。

## Plan

1. **`src/web/templates.py`**：`render_workspace_workbench(name, workspaces)`（4 阶段卡片，仿 `render_workspace_continue` 的 flow-step/card/status-box 结构，stage② 内嵌可编辑大纲 textarea + 保存按钮）；`_WORKSPACE_SECTIONS` 加 `("workbench","工作台","workbench")`；`render_wizard` novel 面板加独立"一句话开书" `premise-form`。
2. **`src/web/routes.py`**：`api_workbench_status`（GET `/workbench`，mtime 链探测 `{stage,has_kb,has_outline,has_plan,draft_count}`）；`api_workspace_outline_save`（PUT `/outline`，`workspace_busy`→409 / 空→400 / `write_text_atomic` 原子写）；`render_workspace_workbench_page`（novel-only guard）；`api_wizard_premise_start` 已在 048a 注册；`_ROUTES` 加 3 行（GET workbench page / GET workbench status / PUT outline）。
3. **`src/web/static.py`**：`initWorkbench`（通用 `bindWorkbenchStage` 把 4 个 form 各接 `POST /run` + `pollJob`；`refreshWorkbench` 拉 `/workbench` 状态做 gate enable/disable + 回填大纲；plan-chapters/write-book 显式传 `require_start_point:false`）；`PAGE_KIND==="workbench"` 分发；`premiseForm` 提交（JSON → `/api/wizard/premise-start` → 导航 `/workbench`，仿 dramaForm）。
4. **`src/web/routes.py` `_validate_plan_chapters_params`**：`require_start_point` 从硬编码 `True` 改为 `_bool_param(params, "require_start_point", True)`（默认 True 保 continue 页行为，workbench 可显式 False）；`force` 仍强制 True。
5. **`tests/test_workbench_e2e.py`（新）** + 更新 `tests/test_web_jobs_dispatch.py` 的 plan-chapters 守护测试反映行为变更。

## Acceptance

- `OPENAI_MODEL=mock` 下 `.venv/bin/python -m unittest discover -s tests` 全绿（基线 674 → **681**，+7）。
- `OPENAI_MODEL=mock python main.py preflight` → FATAL/WARN none。
- workbench 页：`GET /w/<name>/workbench` 200 + `PAGE_KIND="workbench"` + 侧栏含 `/w/<name>/workbench` 入口；drama workspace 走 novel-only guard（非 workbench 页）。
- stage 探测：premise 后 `prepare→outline→plan→write→done` 逐级推进、各 `has_*` 正确；改 premise 重跑 stage①（KB 变新）后旧 outline/plan **自动失效**、stage 回退（mtime 链防旧产物误判）。
- 大纲回写：`PUT /outline` 合法 200 + `GET /plan` 反映；空/纯空白 → 400；job running → 409。

## Implementation Notes

- **stage 探测用 mtime 链而非裸存在性（红队"旧产物误判"防护）**：`api_workbench_status` 判定下游产物有效的条件是"不旧于上游"——`has_outline = outline_m≥kb_m`、`has_plan = plan_m≥outline_m≥kb_m`、`has_drafts = draft_m≥plan_m`。自审关键质疑：`_run_prepare_steps` 里 `compress_all()` 不带 force，重跑 prepare 时 KB mtime 会更新吗？**核验 `compressor.py:87` 确认 `compress_all` 无条件 `write_text_atomic(global_knowledge.md)`**（不检测跳过），故重跑 stage① 必刷新 KB mtime → 旧 outline/plan 正确失效。防护可靠。
- **plan-chapters `require_start_point` 行为变更（红队 #2a）**：`_validate_plan_chapters_params` 原硬编码 `require_start_point:True`，会把 workbench 前端传的 `false` 覆盖掉 → greenfield plan-chapters 被 `start_point_missing` 死锁、chapter_plan 不生成。改为尊重 params（默认 True）。安全性：continue 页 `bindPlan` 不传该字段 → 默认 True 保持原行为；CLI 不经此路径；且 write-book 的 readiness gate 独立校验起点，绕过 plan-chapters gate 也过不了 write-book（多层防护）。配套更新守护测试 `test_plan_chapters_forces_force_but_honors_require_start_point`。
- **write-book 在 mock 下 `retry_exhausted` 是固有行为，非 bug**：workbench stage④ 走 `write-book`（严格生产 gate，与 auto-pipeline 的 `write_chapters` 不同——后者不 gate，故 048a 没遇到）。mock reviewer 默认 Reject（`reviewer.py:68`），chapter draft 写出但拿不到 strict-approved → rewrite 耗尽 blocked。真实模型可 Approve。现有 `test_book_runner.py:211` 正是测这个 `retry_exhausted`。048b 测试据此断言：draft 落盘 + stage=done + write-book 到达终态（succeeded 或 blocked 均可），不强求 approved。
- **premise 前端入口做成独立 form**：在 novel 上传面板内加独立 `premise-form`（自带 workspace 名 + premise textarea），不与 multipart 上传表单混逻辑——避免红队 #3 担心的"两套互斥提交挤在一个表单"。提交走 dramaForm 同款 JSON+navigate 范式。
- **大纲编辑器复用 continue 页结构**：workbench HTML 直接复用 `render_workspace_continue` 的 `.flow-step/.card/.status-box` 类与 `pollJob` hook；细纲阶段仅留"查看细纲详情 →"链到现有只读 `/plan`，正文阶段链到 `/chapters`，不复制只读渲染逻辑。

## Acceptance Result

- **测试**：`unittest discover` = **681 OK**（基线 674 + 新增 7 workbench 测试），零回归。其中 1 个现有测试（`test_web_jobs_dispatch` 的 plan-chapters 守护）按行为变更**有意更新**——旧测试断言 `require_start_point` 被强制 True，新测试断言被尊重为 False（默认仍 True，由 `test_plan_chapters_missing_start_point_is_blocked` 守）。
- **preflight**：048a 已验 FATAL/WARN none，048b 未改 preflight 逻辑；最终复核待跑（API 暂时不稳定，见 Notes）。
- **收官对抗审核（铁律⑨）**：本轮收官时 Bash classifier 暂不可用、对抗 subagent 两次 ECONNRESET，审核由**主对话只读自审**完成，结论如下：
  - **A（stage 探测 mtime 链）**：核验 `compressor.py:87` 确认 KB 无条件重写 → 重跑 stage① 刷新 mtime → 防护可靠；边界（mtime 相等用 `≥`、文件缺失 `_mtime_ns=0`）正确。**对"改 premise"真实场景，extract 产物变化也强制 compress 重算，防护双重成立**。
  - **B（plan-chapters 行为变更安全性）**：continue 页/CLI 不受影响（默认 True），workbench 显式 False；write-book readiness gate 独立兜底无起点场景。无阻塞。
  - **C（PUT outline 竞态/校验）**：`workspace_busy`→409 + 前端 running 禁用两道防护；TOCTOU 窗口小且 `write_text_atomic` 原子（不损坏文件）；空/非 str/超 200k 校验完整。无阻塞。
  - **D（前端 gate 绕过）**：gate 仅 UX，后端 `blocked{outline_missing}` 等兜底，绕不过。无阻塞。
  - **诚实记录**：铁律⑨「≥1 subagent」本轮**未由 subagent 满足**（连接故障），全部为主对话自审；待 API 恢复后补一轮 subagent 复核更稳妥。
- **浏览器实机验证（补做，CLAUDE.md 铁律：UI 改动须实机走过）**：`web-mock` dev server 上 `/wizard` → 选小说 → 一句话开书表单（workspace=livebook, premise=少年觉醒上古血脉，逆天改命踏破苍穹）→ 跳 `/w/livebook/workbench`（`PAGE_KIND="workbench"`、侧栏含"工作台"高亮、面包屑正确）→ 实跑四阶段：stage① 设定 succeeded + 进度条 **100%**（红队修正：不卡 5/6）→ stage② 大纲 0.5s succeeded 且 textarea 自动回填 mock 大纲 → 用户编辑大纲 → 保存 → `GET /plan` 读到编辑后内容 ✓ → stage③ plan-chapters 0.5s succeeded → stage pill 切到"④ 正文"。`console` 全程零错误；`GET /api/diag/models` mock 下 `is_mock:true`/`all_ok:true`/6 task 去重为 1 个 mock 探测；drama workspace 访问 `/workbench` 触发 novel-only guard（不返回 workbench 内容）。截图与 server log 留存于本轮实机回话。实机测试 workspace `livebook` 已清理。

## 文件变更汇总

- `src/web/routes.py`（改）：`api_workbench_status`（mtime 链 stage 探测）+ `api_workspace_outline_save`（PUT 大纲）+ `render_workspace_workbench_page` + `_validate_plan_chapters_params` 行为变更 + `_ROUTES` 加 3 行。
- `src/web/templates.py`（改）：`render_workspace_workbench`（4 阶段卡片）+ `_WORKSPACE_SECTIONS` 加 workbench + `render_wizard` premise-form。
- `src/web/static.py`（改）：`initWorkbench`/`bindWorkbenchStage`/`refreshWorkbench` + PAGE_KIND 分发 + `premiseForm` 提交。
- `tests/test_workbench_e2e.py`（新）：7 个 mock 测试（页面+nav / stage 进展 / 大纲 PUT / 空 400 / busy 409 / mtime 链防误判 / drama guard）。
- `tests/test_web_jobs_dispatch.py`（改）：plan-chapters 守护测试随 `require_start_point` 行为变更更新。

## 不在本轮范围

- **048c**：细纲只读展示 + "重新生成细纲"（重跑 plan-chapters 天然重算指纹）+ write-book 兼容回归（greenfield 指纹链自洽验证）。
- **049**：正文逐章深度编辑 + 重 review；premise 扩写质量增强；设定（KB/entity_graph）编辑回写；真模型授权与测 Key 成本护栏深化。
- 本轮不跑真模型（铁律⑥）；细纲不做结构化编辑/回写（不碰指纹链）。

## Notes

- **write-book 在 mock 下不出 approved 章**是 mock reviewer 固有限制（非 048b bug），真实模型才能 Approve。小白工作台 stage④ 用严格的 write-book 是有意设计（出版级正文）；UI 上 blocked 会显示 retry_exhausted，用户可在真实模型下重试。
- **git 状态已核对（健康）**：本对话经历 context 压缩一度让"何时 commit 048a"失忆，但 `git log/diff` 证实状态干净——HEAD=`1133e4c`（048a，含全部 048a 代码 + 文档，674 OK 已 commit），working tree 改动**仅 048b**（routes/static/templates/test_web_jobs_dispatch 改 + test_workbench_e2e/本文档新），048a 文件零 diff。无重复、无遗漏；`681 = 048a 的 674 + 048b 的 7`。
- **收尾待办**：① 更新 `docs/iterations/README.md` 索引加 048b 行 + `docs/AGENT_HANDOFF.md` Phase Status（铁律⑧）；② commit（不 push，铁律⑤）等用户验收；③（可选）API 稳定后补一轮 subagent 对抗复核——本轮自审已覆盖 A/B/C/D，subagent 因连接故障未跑成。
- 验收命令需用项目 `.venv/bin/python`（系统 python3 缺 pydantic/litellm）。
