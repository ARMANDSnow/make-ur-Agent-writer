# Iteration 072 - leave-guard/jobs residual 收口 + 模态 a11y helper

## Context

iter071 收口了 leave-guard 的「全出口覆盖 + 活跃任务真源 + 模态焦点 + 空书架真测」。codex 对 iter071 的复审又发现一批 residual 缺口（2 个 P2 + 4 个 P3 + 1 个 a11y），集中在 **leave-guard 前端模态** 与 **jobs 后端真源** 两块代码。本轮把这批 residual，连同 iter070/071 deferred 的三项相关债（模态全局 focus-trap/去重、recent_jobs pending 优先、复制非 HTTPS 降级、debate --force CLI 文案泄漏）一并收口。

核心目标：让「当前作品有运行任务时离开/切换」在**所有出口**都触发三选一弹窗、弹窗文案与真实目的地一致、jobs 真源在并发下无 race、对外快照不泄漏内部字段、坏数据不致 500、所有模态满足键盘无障碍。

用户已确认 scope（AskUserQuestion）：focus-trap 抽**可复用 helper 应用到所有模态**；附带纳入 **recent_jobs pending 优先排序 + 复制按钮非 HTTPS 降级 + debate --force CLI 文案**；**批量中文化不在本轮**。

## Plan

- **#1 [P2] 侧栏切换作品绕过 leave guard** → `templates.py` `_sidebar()` 给非当前作品列表项加 `data-leave-guard`（当前作品项 + section 内导航不加）。
- **#2 [P3] 模态目的地文案错误** → `static.py` 抽 `leaveDestinationLabel(href)` 全映射（/、/library、/trash、/settings、/wizard、/w/{name}/），替换 line 2180 二元判断。
- **#3 [P2] /jobs/active 发布顺序 race** → `jobs.py` `start_job()` 在 `_WORKSPACE_LOCK` 内先嵌套 `_JOBS_LOCK` 写 `_JOBS` 再写 `_WORKSPACE_JOBS`（锁序已验证 WORKSPACE→JOBS 单向，无死锁）。
- **#4 [P3] active endpoint 暴露完整 job record** → `jobs.py` 加 `public_job_view()` 白名单；`routes.py` `api_workspace_active_jobs` 改用它（剔除 params 等）。
- **#5 [P3] recent_jobs() 坏 timestamp + pending 优先** → `jobs.py` 加 `_as_ts()` 安全转换；sort key 改 `(active, ts)` reverse。
- **#6 [a11y] trapFocus 可复用 helper** → `static.py` 抽 helper（记录触发元素 / Tab 循环 / Esc 关闭 / 焦点恢复 / 去重防叠层），应用到 delete/leave-guard/purge/partial 4 模态。
- **#7 [deferred] 复制按钮非 HTTPS 降级** → `static.py` `bindCopy` 抽 `copyText`，加 execCommand 回退 + 手动复制提示。
- **#8 [deferred] debate --force CLI 文案泄漏** → `static.py` `renderPlanSummary` 替换 CLI 文案为 Web 友好文案（先确认是否有应用内重新生成大纲入口）。

## Acceptance

- 单测：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`（基线 iter071 1333 OK；新增 active race / public_view 不含 params / `_as_ts` 坏 timestamp / pending 优先 / 侧栏 data-leave-guard 渲染断言）。
- `bash scripts/verify.sh`、`python3 main.py preflight` 通过。
- 前端 E2E（preview，desktop width:1280）：侧栏切作品弹窗主按钮「切到《…》」/ 设置「去设置」/ 模态内 Tab 循环 + Esc 焦点恢复 / 非安全上下文复制回退。

## Implementation Notes

- **#3 锁序**：先 grep 全模块 `_WORKSPACE_LOCK`/`_JOBS_LOCK`（行 56/60，使用点 188/199/210/231/245/288/318/324/338/346/987/1001/1166/1175/1192/1194/1204/1206）确认无 `JOBS⊃WORKSPACE` 反序嵌套（987→1001 是顺序非嵌套），才放心把 `_JOBS` 写挪进 `_WORKSPACE_LOCK` 嵌套。不变式：`_WORKSPACE_JOBS[ws]` 置位 ⟹ `_JOBS` 必已含 record；`active_jobs()` 扫 `_JOBS` 不再有"workspace busy 但 active 空"窗口。
- **#5 两项合并**：坏 timestamp 健壮（`_as_ts`）与 pending 优先排序同在 `recent_jobs` sort key 一处落地，`(active, _as_ts(finished) or _as_ts(started))` + `reverse=True`。代码审查补强：`_as_ts` 增 `math.isfinite` 守门（NaN/inf 不抛但会破坏排序总序，归零中和），对齐文件内既有 `_float_param`/`_timeout_deadline` 模式。
- **#6 helper 抽象**：4 个模态各自的 `closeModal/close + onKeyDown(Escape) + setTimeout(focus)` 收敛进 `mountModal(backdrop, opts)`（记录触发元素 / Tab 循环 / Esc 关 / 焦点恢复 / `_activeModalTeardown` 去重防叠层），返回 `close` 由各 call site 接线。`openPartialPreview` 顺带补齐它此前**完全缺失**的 Escape + 焦点管理。
- **#2 正则改字符串**：JS 内嵌于非 raw Python 字符串，`/^\/w\/.../` 的转义斜杠会触发 Python `SyntaxWarning`（与既有 `"\\n"` 双反斜杠惯例同源），故 `/w/{name}/` 用 `indexOf/slice` 解析而非 regex 字面量。
- **#7 防卡死**：代码审查指出 `copyText` 快速双击会把瞬时 "✓" 误记为原标签致卡死，改为 `btn._copyLabel` 一次性记真标签 + `clearTimeout` 在途恢复定时器。
- **#8**：确认 Web 已有应用内"② 大纲 · 生成大纲"（debate step）入口，文案指向它而非裸 CLI。

## Acceptance Result

- **单测**：`.venv/bin/python3 -m unittest discover -s tests` = **1341 OK**（iter071 基线 1333 + 8 新；含 `_as_ts` 非有限/坏值、pending 优先、public_job_view 白名单、start_job 写序探针、侧栏 data-leave-guard、active endpoint 字段收窄、JS residual 断言；iter071 的 `..._immune_to_recent_truncation` 因 #5 行为变更已据实改名/改判为 `..._surfaces_in_both_sources`）。必须用 `.venv/bin/python3`（裸 `python3` 缺 pydantic）。
- **JS 语法**：`node --check`（渲染后的 app.js）OK。
- **verify.sh**：本机环境**不可跑**——脚本第 41 行硬编码裸 `python3 -m unittest`，该解释器缺 pydantic，触发 259 个 `ImportError: Failed to import test module`（与本轮无关，跨 debater/extractor/book_runner 等未触及模块；裸 `python3 -c "import pydantic"` 即抛 ModuleNotFoundError）。等价闸门 = 上面 1341 OK 的 venv discover。`python3 main.py preflight` = exit 0。
- **铁律⑨ 代码审查**：`/code-review high`，3 finder（line-by-line / concurrency-backend / removed-behavior+cross-file）+ 对抗式核实。headline 风险（死锁、回滚、白名单、坏行 500、stale test）全 clean。3 个 LOW：① `copyText` 双击卡标签 → **已修**；② `_as_ts` 放行 NaN/inf → **已修**（isfinite 守门 + 新测）；③ `recent_jobs` pending 优先**透传**到 overview "最近任务"卡（routes 474/519，limit=1）使其从"最新完成"变"优先在跑"——判定为符合本轮意图的改进，**留作 Notes 记录不改**（一个在跑任务正是用户在卡片上想看到的）。
- **铁律⑨ 安全审查**：`/security-review`，聚焦本轮 4 源文件工作树 diff。**0 HIGH / 0 MEDIUM**，且净正向：`public_job_view` 收窄对外字段（剔除 `params` 用户 POST body）、`_as_ts` 硬化坏输入、锁序收紧守卫可观测性。唯一新建裸串路径 `leaveDestinationLabel` 在唯一 sink `escapeHtml(leaveLabel)` 处转义，XSS 链闭合。未碰 `.env`/`data/`/`小说txt/`。
- **前端 E2E（iter73 回填）**：iter072 收官时 Acceptance line 26 列了 preview E2E（侧栏切作品弹窗主按钮 / 设置「去设置」/ 模态 Tab 循环 + Esc 焦点恢复 / 复制回退），但当轮 Acceptance Result 漏记是否实跑——据实补记：**未实跑 preview E2E**，以 `node --check`（渲染后的 app.js）+ 单测对模态/焦点行为的字符串与逻辑断言（`mountModal` Tab/Esc/焦点恢复在单测覆盖）代偿，E2E 顺延。iter073 再次触及 `static.py`（leave-guard 竞态守卫 E 项），同样以 `node --check` + `STATIC_JS` 字符串断言代偿（leave-guard 的"快速双击"是时序竞态，preview 工具难稳定复现，故不强行 E2E、据实顺延，见 iter073 Notes）。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | `_sidebar` 非当前作品项加 `data-leave-guard`（#1，含 `is_active` 排除注释） |
| `src/web/static.py` | 新增 `leaveDestinationLabel`（#2）、`mountModal` focus-trap/去重 helper + 4 模态接入（#6）、`copyText`/`legacyCopy` 非 HTTPS 降级 + 双击防卡（#7）、`renderPlanSummary` debate 文案 Web 化（#8）；`showLeaveGuardModal` 改用 helper |
| `src/web/jobs.py` | `_as_ts`（坏值+非有限归零）、`public_job_view` 白名单（#4）、`recent_jobs` sort key `(active, ts)`（#5）、`start_job` 锁内嵌套写序（#3） |
| `src/web/routes.py` | `api_workspace_active_jobs` 改用 `public_job_view`（#4） |
| `tests/test_web_jobs_recent.py` | 新增 `Iter072JobsResidualTests`（_as_ts/pending/public_view/start_job 写序）+ 改判 iter071 truncation 测 |
| `tests/test_web_routes_get.py` | 新增 侧栏 guard / active 字段收窄 / JS residual 三测；更新 iter071 focus 断言为 `mountModal(... initialFocus: stayBtn)` |
| `docs/iterations/iteration_072_*.md` + `README.md` 索引/SOP + `docs/AGENT_HANDOFF.md` | iter 收尾文档（铁律⑧⑨） |

## 不在本轮范围

- 批量命名中文化（workspace→作品、表头、术语）——面广，单独成轮。
- 书架类型筛选/分组——量小，继续 deferred。
- `/jobs/recent` 端点字段收窄——drawer UI 依赖较多字段，未列入。

## Notes

- **行为变更登记（透传）**：#5 的 pending 优先排序经 `recent_jobs(limit=1)` 透传到 workspace overview「最近任务」卡（routes 474/519），使其从"时间上最新的任务"变为"有在跑任务则优先显示在跑的"。判定为期望改进（用户在卡片上最关心的就是正在跑的任务），与 jobs 列表/侧栏意图一致；未加专门测试 pin 该卡，留此记录。
- **active_jobs 仍保留**：#5 让 pending 也在 `recent_jobs` 置顶后，iter071 F2 的"pending 被截断"场景对 recent 不再发生，但 `active_jobs()` 作为权威源仍保留——它直读内存、零截断零排序、进程重启后正确返回 `[]`（fail-open），不依赖日志持久化时序，是 leave-guard 更稳的数据源。
- **后续候选（iter073+）**：overview「最近任务」卡若需明确区分"最新完成 vs 在跑"，可加 type-aware 文案 / 测试 pin；`/jobs/recent` 端点字段收窄（当前 drawer 依赖 result_summary/error/trace_id，需配套前端改）；批量命名中文化（本轮用户明确不纳入，单独成轮）。
- **教训**：JS 内嵌于非 raw Python 字符串时，正则字面量的 `\/` 会触发 `SyntaxWarning`（未来可能升级为错误）——内嵌 JS 写正则优先用字符串解析或 `new RegExp("...")`，避免转义斜杠。`py_compile -W error::SyntaxWarning` 可提前抓出。
