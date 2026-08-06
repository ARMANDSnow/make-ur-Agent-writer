# Iteration 165 - 小说 Web 模式语义与交互可靠性修复

## Context

用户在“一句话开书”与作品内导航中发现三类直接影响使用体验的问题：原创书被误报“未设置续写起点”、运行任务期间同作品切页反复弹离开提示、同类警示重复展示。多视角只读审查进一步确认，根因是小说 workspace 未持久化原创/续写模式、overview/readiness/run-step 的起点策略不一致，以及 active-job、未保存编辑两类导航守卫被耦合复用；同源缺口还包括工作台 hydration 失败开放、运行任务恢复不完整、多个编辑器未纳入 dirty 保护、Toast 堆叠与移动菜单焦点语义不足。本轮在 mock-only、isolated synthetic workspace 边界内一次闭环这些高置信 P1/P2，不调用真实 provider，不读取或修改私有样本。

## Plan

### Implementation Context
- `must_read`: `src/web/workspace_meta.py`, `src/web/wizard.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `src/cli_workspace.py`, `src/book_runner.py`, `tests/test_workspace_meta.py`, `tests/test_web_routes_get.py`, `tests/test_workbench_e2e.py`
- `expected_changes`: `src/web/workspace_meta.py`, `src/web/wizard.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `src/cli_workspace.py`, `tests/test_workspace_meta.py`, `tests/test_web_routes_get.py`, `tests/test_workbench_e2e.py`, `tests/test_premise_prepare_diag.py`, `docs/iterations/iteration_165_novel_web_mode_navigation_reliability.md`, `docs/iterations/README.md`
- `do_not_touch`: `.env`、`小说txt/` 原文与内容、`data/`、`outputs/`、`logs/`、真实 provider/smoke、现有未跟踪体检报告；旧 workspace 的 GET 只读探测不得迁移或改盘

- 将小说 workspace metadata 升至 schema v2，以 `creation_mode=greenfield|continuation` 持久化新建来源；旧 workspace 只在 no-follow regular `seed.txt` 存在且 `upload.txt` 不存在时只读推断 greenfield，其余保守 continuation。
- 抽取服务端权威小说模式策略，统一 overview、workbench、readiness 与 run-step 的 `creation_mode` / `requires_start_point`；原创书不要求续写起点，导入书不得因尚未设置起点误走 greenfield 步骤，显式冲突参数返回友好 409 且不启动任务。
- 概览改为当前工作台阶段优先，greenfield 使用原创创作文案并隐藏不适用的续写起点/原文章节信息；最终写作 readiness 只在进入正文阶段后作为主状态呈现。
- 将导航分类为 same-document、same-workspace、leave-workspace、switch-workspace；dirty 守卫与 active-job 守卫分层串联，同作品导航不查询 active job，跨作品/全局导航先处理未保存内容再处理运行任务。
- 建立页面级 dirty registry，覆盖正文、独立计划、KB、扩写稿、风格卡、大纲、实体、关系和内嵌细纲；支持继续编辑、放弃、保存全部后继续，部分失败保留输入；仅 dirty 状态触发 beforeunload。
- 工作台 mutation 初始 fail-closed，hydration 成功后按权威阶段解锁；恢复唯一 active job 的进度/取消/任务入口并锁住冲突操作，终态刷新，lost/404/坏状态停止且零重提。
- 共用 readiness 展示分组，primary 单点呈现、同类多章按数量聚合；Toast 相同消息合并且最多三条；移动菜单补齐 aria-expanded/controls、焦点进入/恢复、Escape 与背景交互隔离。

## Acceptance

### Review Context
- `correctness_behavior`: 复核 creation_mode 的新建/旧 workspace 推断、overview/workbench/readiness/run-step 同源，原创正文不被起点误拦、导入书不误走 greenfield；导航 dirty→active 组合顺序、运行任务恢复、聚合展示与零自动重提必须有行为证据
- `security_boundary`: 复核旧 workspace 探测 no-follow/regular-file 与歧义 fail-closed，GET 零写入，公开投影不泄漏路径/原文/raw job 私有字段；run-step 模式冲突在任务创建前拒绝，mock/offline、付费授权与 workspace 隔离不回归
- `extra_risk_view`: Web/UX/响应式专项：三视口、键盘/焦点/ARIA、全部编辑器 dirty、任务页与短剧同作品导航、Toast 上限和错误恢复

- **A165-01**：workspace metadata v2、新建入口与旧 workspace 安全推断测试通过；歧义、symlink、坏 metadata 保守 continuation，所有只读接口零迁移写入。
- **A165-02**：overview/workbench/readiness/run-step 统一 `creation_mode` 与 `requires_start_point`；greenfield 第④步可启动 mock job，continuation 无起点仍阻断且不能派发 greenfield 步骤，冲突请求在创建 job 前返回友好 409。
- **A165-03**：概览按阶段展示，greenfield 无“未设置续写起点/原文章节”误导；readiness primary 不重复，同类多章提示只展示一次并带正确数量。
- **A165-04**：active job 下 same-workspace/same-document 导航零弹窗零 cancel；leave/switch 只弹一次；dirty 与 active 严格按先保存/放弃再检查任务的顺序组合，编码名称、query/hash 与快速双击无竞态。
- **A165-05**：全部目标编辑器接入 dirty registry；保存失败保留未保存输入，beforeunload 仅在 dirty 时触发。
- **A165-06**：工作台 hydration 未完成/失败保持 mutation 禁用并可重试；pending/running 可恢复进度并锁定冲突操作，终态刷新，lost/404/坏状态停止轮询且不重提。
- **A165-07**：Toast 相同消息合并且最多三条；移动侧栏/顶部菜单 aria、焦点、Escape 和背景隔离通过 1440×1024、1199×900、390×844 isolated synthetic mock 浏览器复核，无横向溢出、遮挡或控制台错误，证据等级 `local-e2e`。
- **A165-08**：聚焦 Python/JS/harness/diff 检查通过；correctness、security/boundary、Web/UX 三个独立只读审查无未处理有效 finding。
- **A165-09**：implementation commit 上最终仅运行一次 `bash scripts/verify.sh` 并通过，canonical 测试数不低于 iter164 的 3043，`acceptance.json` 为 `mock-functional` / `canonical-mock-offline`；不产生 provider-validated 宣称。

## Implementation Notes

- `workspace.json` 升至 schema v2；novel 新增 `creation_mode`，drama 保持原结构。一句话开书显式写 `greenfield`，上传显式写 `continuation`。旧 workspace 仅在真实目录中的 regular `seed.txt` 且 `upload.txt` 目录项完全不存在时只读推断 greenfield；symlink、坏链接、v2 非法字段与其它歧义均 continuation，GET 不迁移。
- 新增服务端权威创作策略与同源 `creation_stage`；overview/workbench/readiness 均投影 `creation_mode`、`requires_start_point`。`/run` 与 `jobs.start_job()` 双层拒绝模式冲突，并在 job record/slot/log 创建前失败；plan/write 省略参数时注入权威默认。
- 上传入口由会继续生成正文的 `auto-pipeline-greenfield` 改为 continuation-only `prepare-import`，只做本地 normalize/split，不做设定、大纲、计划或正文生成；导入完成后进入续写起点选择。
- NovelOps/Aeloon 集成改为读取服务端模式：原创走 `prepare-greenfield`，导入书有起点才走 `rebuild-for-start`，无起点给出友好提示；旧服务端缺字段时保守 continuation。
- 前端统一 `requestNavigation()`：same-document 直接处理，same-workspace 只处理 dirty，leave/switch 才查询 active jobs；序列号与单 modal guard 保留快速点击竞态保护。
- 页面级 dirty registry 覆盖正文、独立细纲、KB、扩写稿、风格卡、大纲、实体、关系、内嵌细纲；站内离开支持继续、放弃、保存全部，逐项保存并保留失败输入；全局只在 registry 确有 dirty 时触发 `beforeunload`。
- 工作台 mutation 首屏 disabled，workbench 与 active-job 两个请求都成功后才按阶段解锁；恢复 pending/running 的任务入口、取消操作和受控轮询，lost/404/坏状态停止且不自动重提。
- Overview 按当前阶段优先，原创书改用原创文案并隐藏续写起点/原文章节；Readiness 友好文案分组计数且 primary 不进入详情重复展示；Toast 同 key 合并且最多三条。
- 移动侧栏/顶部菜单补 `aria-controls/expanded`、首焦点、Escape/关闭焦点恢复与背景 inert；`metric-small` 修复 1199px 概览指标换行过大的问题。
- 聚焦验证：JS `node --check` 与 Python `py_compile` 通过；核心前后端、NovelOps/Aeloon/MCP 等 256 tests OK。Playwright 使用 `/private/tmp/iter165-browser.*` isolated synthetic workspace，在 390×844、1199×900、1440×1024 验证原创、导入、dirty modal、菜单焦点与概览布局；控制台 0 errors / 0 warnings，未调用真实 provider。
- 多视角只读审查完成 correctness、security/boundary、Web/UX 三路。主线程修复了起点变化未传递作废下游、损坏 metadata 任务准入、novel/drama family 漏口、重启 lost 投影、内联细纲增删未标脏、部分保存重复写入及移动菜单背景焦点等 findings；三路最终复核均无剩余高置信 P1/P2。

## Acceptance Result

- **A165-01 通过**：小说 workspace schema v2、新建入口显式模式与 legacy no-follow/regular-file 只读保守推断均有回归；GET 不迁移、不改盘。
- **A165-02 通过**：overview/workbench/readiness/run 共用服务端权威模式与阶段；原创正文不受续写起点误拦，导入作品与冲突参数在 job 创建前失败关闭。
- **A165-03 通过**：概览按当前阶段优先，greenfield 隐藏续写口径；readiness primary 单点展示，同类多章提示聚合计数。
- **A165-04 通过**：same-document/same-workspace/leave/switch 分类、dirty→active-job 顺序、编码名称、query/hash 与快速双击竞态均有行为回归。
- **A165-05 通过**：正文、独立计划、KB、扩写稿、风格卡、大纲、实体、关系与内嵌细纲全部接入 dirty registry；部分保存失败保留输入，beforeunload 仅在 dirty 时生效。
- **A165-06 通过**：工作台 hydration 与 active-job 状态未知时 mutation 禁用；pending/running 可恢复，终态刷新，lost/404/坏状态停止轮询且零自动重提。
- **A165-07 通过**：Toast 合并且最多三条；移动菜单 ARIA、焦点、Escape 与背景隔离通过三视口 isolated synthetic mock 浏览器复核。
- **A165-08 通过**：聚焦 Python/JS/harness/diff 检查和 correctness、security/boundary、Web/UX 三路只读审查完成，最终无剩余高置信 P1/P2。
- **A165-09 通过**：最终 implementation commit 上 canonical 3072 tests 与 15 steps 通过，超过 iter164 的 3043 基线，回执为 `mock-functional` / `canonical-mock-offline`，未作 provider-validated 宣称。
- **聚焦验收**：初始核心前后端、NovelOps/Aeloon/MCP 共 256 tests OK，JS `node --check`、Python `py_compile`、harness 与 `git diff --check` 通过。第一次 canonical 暴露 legacy drama metadata 与旧步骤分类兼容问题后，213 项失败域回归通过；随后 483 项 Web/static/drama-media 广域回归仅发现 1 个旧静态合同，修复后 125 项终检通过。第二次 canonical 暴露 `/run` 数值参数校验被模式门禁遮蔽，调整校验优先级并将数值测试 fixture 显式标记 greenfield 后，47 项聚焦回归通过。
- **浏览器证据**：Playwright 仅使用 `/private/tmp/iter165-browser.*` isolated synthetic workspace 与 mock，在 390×844、1199×900、1440×1024 覆盖原创、导入、active job、dirty modal、Toast、菜单键盘/焦点和概览布局；0 console errors、0 warnings，无横向溢出或关键控件遮挡，等级 `local-e2e`，provider calls=0。
- **独立审查**：correctness、security/boundary、Web/UX 三路只读审查完成。审查 findings 经主线程复核并修复，包含模式/阶段与下游 stale 传播、metadata/novel-drama family 准入、重启 lost 投影、内联细纲 dirty、部分保存、移动菜单背景焦点等；三路最终复核均无剩余高置信 P1/P2。
- **Canonical**：最终 accepted implementation `e718200da399c25c198f239b874bf669f1de963b` 上 `bash scripts/verify.sh` exit 0；schema v2，3072 tests、15 completed steps、502 秒，run `615a5147bb994c6f8179c1899dc0b055`，`status=passed`、`tracked_scope_clean=true`、`mock_offline=true`，等级 `mock-functional` / `canonical-mock-offline`。完整链包含 `local_drama_e2e`、mock pipeline 与 preflight。
- **失败后重验记录**：首次 full gate 在 implementation `3240671` 上 3072 tests 出现 40 failures / 181 errors，定位为 schema v2 对既有 drama metadata 与步骤分类的兼容回归；修复后 implementation `6651156` 上 3072 tests 仅余 6 个 `/run` 校验优先级失败（run `7630ad0d2d4d420ca700292c1bbcc43e`）。两次失败均未越过 unittest，也未产生 provider 请求；按失败范围聚焦修复后在最终 implementation 上完整重验通过。更早一次 clean-scope 预检因 iteration 文档未并入 commit 而立即停止，未运行测试。
- **边界**：全程未 push，未读取或修改 `.env`、`小说txt/`、私有 workspace、用户运行产物，未调用或查询真实 provider。`docs/2026-8-5体检报告.md` 与 `docs/2026-8-6体检报告.md` 保持未跟踪且未读取、修改、暂存或提交。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 本轮形成跨迭代长期合同：小说创作来源必须由持久 metadata 与服务端投影/执行守门统一决定，legacy 只读保守推断且 GET 不迁移；导航必须把 dirty 与 active-job 分层，same-workspace 不查询任务，hydration 或任务状态未知时 mutation 保持 fail-closed。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/workspace_meta.py`, `src/cli_workspace.py` | schema v2、创作模式写入与 legacy no-follow 推断 |
| `src/web/wizard.py`, `src/web/jobs.py`, `src/web/routes.py` | continuation-only 导入准备、权威模式守门、同源 Web 投影与 cache invalidation |
| `src/web/templates.py`, `src/web/static.py` | 阶段文案、导航/dirty 状态机、fail-closed 工作台、任务恢复、提示去重与菜单无障碍 |
| `integrations/novel_ops/{config.py,ops.py}` | 集成消费服务端创作模式与起点策略 |
| `tests/test_workspace_meta.py`, `tests/test_web_jobs_dispatch.py`, `tests/test_web_wizard_e2e.py` | 元数据、任务冲突与导入流程测试 |
| `tests/test_web_iter165_ux_reliability.py`, `tests/test_web_phase_d.py`, `tests/test_web_routes_get.py` | 前端可靠性、概览与静态合同测试 |
| `tests/test_novel_ops.py`, `tests/test_aeloon_plugin.py` | NovelOps/Aeloon 模式行为回归 |
| `src/drama_media_tasks.py`, `tests/test_int_finite_guard.py`, `tests/test_web_phase_e.py` | schema v2 与既有参数/静态合同兼容修复 |
| `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/iterations/README.md`, 本文档 | SOP、当前快照、长期决策、索引与验收回执收官同步 |

## 不在本轮范围

- 真实文本、图片、视频、TTS provider 验证与任何付费提交。
- 旧 workspace 的自动迁移、强制用户选择模式或读取原文内容进行模式识别。
- 与本轮交互问题无关的短剧生产协议、媒体任务、archive 与计费逻辑改造。

## Notes

- 当前工作树两份用户未跟踪体检报告保持原样；本轮未读取、修改、暂存或提交。
