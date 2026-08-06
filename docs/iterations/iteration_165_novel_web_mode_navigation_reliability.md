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

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `<iter-finish 回填：none|promoted>`
- `destination`: `<iter-finish 回填：none|既有长期权威文档>`
- `reason`: `<iter-finish 回填人工判断>`

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

## 不在本轮范围

- 真实文本、图片、视频、TTS provider 验证与任何付费提交。
- 旧 workspace 的自动迁移、强制用户选择模式或读取原文内容进行模式识别。
- 与本轮交互问题无关的短剧生产协议、媒体任务、archive 与计费逻辑改造。

## Notes

- 当前工作树已有两份用户未跟踪体检报告；本轮不读取、不修改、不暂存、不提交。
