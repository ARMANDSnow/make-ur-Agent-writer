# Iteration 044 · 收尾轮（D-5 / D-7 / D-8 + 文档刷新）

> 文件名沿用草稿盒路径；iter039/040/042/043§A/043§B plan 已归档到 `docs/iterations/iteration_*_PLAN_DRAFT.md`。

## Context

**为什么这一轮做这个**：iter043 §B 收完 Bundle 1+2 后，桌面上剩余 UX 长尾（Bundle 3：D-5 onboarding / D-7 移动响应式 / D-8 剩余 UI debt）+ 累了 5 轮没动的文档（AGENTS.md / README / HANDOFF）。iter044 定位**收尾轮**：把所有历史 backlog 一次性扫清，让代码 / 文档语义距离归零，给下一阶段的功能轮（drama 模块开放？多 workspace 协作？）一个干净起点。

**用户视角痛点**（来自 iter043 §A audit + 探查）：
- onboarding 上传后只看到"等待 worker…"，不知道发生什么 / 该不该等 / 出错了能不能取消
- 手机/iPad 上 sidebar 直接消失没 drawer，表格被挤压
- subscore 表格还有 inline style + Insights `sub_scores` 没 fallback（iter042 subagent 留的兼容风险）
- AGENTS.md 还说"下一步候选（iter 043）" —— 实际已 iter043 §B 收官

**iter044 目标**：
1. P2-C onboarding 三件套（预算 / timeout / **真 cancel**）落地 —— 这条从 iter039 拖到 iter044，必须真收
2. 移动响应式从"硬隐藏"升级到"drawer + 表格 card"
3. iter038 P3 剩余 + iter042 subagent 留的兼容风险清掉
4. 文档对齐到 iter044 状态，给下一阶段一个清晰起点

**预算**：UI + 文档层改动 + 1 个后端 cancel 路由；不动 LLM 链路；mock 链路验证零真实 token；预计 10-12 commits / 100-150k tokens / 折人民币 ~¥2-3。

---

## 修复方案

### §A · D-5 Onboarding critical path（含真 cancel）

**根因**（探查 1）：
- `templates.py:823-844` wizard panel-upload 仅 workspace 名 + 文件，无预算 / timeout / cancel / mock 提示
- `templates.py:895-898` panel-progress 仅"等待 worker…"占位
- `routes.py` 零 cancel/abort 关键字；`jobs.py:57 _JOBS` 无取消标志
- 成功 / 失败 terminal 状态无主 CTA

**实施**：

1. **后端 cancel 机制（核心）**：
   - `src/web/jobs.py` _JOBS 字典每个 job dict 加 `cancel_requested: bool = False` 字段
   - 新增 `request_cancel(job_id)` helper：原子设置标志位
   - **worker 检查点**：在 `_progress` callback 内（每次进度更新时）检查 `cancel_requested`，若 True 抛 `JobCancelled(RuntimeError)`
   - jobs.py worker 主循环 `except JobCancelled` 分支：`_update(status="aborted", current_step="cancelled", error="user requested cancel")`
   - 不强制 kill 线程（Python 线程安全考虑）—— 用"协作式取消"，让正在跑的 LLM 调用完成后才生效（可接受，因为 progress callback 每章 / 每 sub-step 都触发）

2. **后端 cancel 路由**：
   - `src/web/routes.py` 新增 `POST /api/workspace/<ws>/job/<id>/cancel` → 调 `jobs.request_cancel(job_id)`，返回 `{ requested_at, status }`
   - 路由调用前校验 job 状态：仅 running / pending 可取消，其他状态返回 409
   - 加 routes test 覆盖：取消未启动 / 取消已完成 / 取消成功路径

3. **前端 wizard 表单扩展**（`templates.py:823-844` 小说 + `:846-893` drama）：
   - 加可选字段（默认折叠到"高级选项"）：
     - 预算 CNY（透传到后续 write-book 默认值）
     - 超时分钟（job-level timeout，超时后自动 cancel，worker 端用 cancel_requested 路径）
     - extract limit（小说专用，章节数上限）
   - 顶部加"会发生什么"提示卡（产品文案）：3 步流水线 / 预计时长 / mock vs real 标识
   - mock 检测：调 `/preflight` 拿当前 server config，显示 "当前 server 模式：mock，本次不消耗真实 token"

4. **前端 panel-progress 改造**：
   - terminal 状态用 §A iter043 的 CTA_ACTIONS 复用：
     - running：显示"可以做什么"提示组（继续浏览书架 / 查看 logs / **取消任务**按钮）
     - succeeded：CTA 组（设置起点 / 查看章节 / 开始续写）
     - failed：CTA 组（查看失败详情 / 回到 wizard 重试）
     - aborted：CTA 组（重新开始 / 返回书架）+ 显示"任务已取消"
   - 取消按钮点击 → POST cancel 路由 → 显示"取消请求已发送，等待 worker 响应"

5. **超时机制**：
   - jobs.py worker 启动时如 params 含 `timeout_minutes`，记录 `deadline = time.monotonic() + timeout * 60`
   - 每次 `_progress` 检查 `time.monotonic() > deadline`，超时 raise `JobTimeout(JobCancelled)`
   - terminal 状态显示 "超时自动取消（N 分钟）"

6. **drama wizard 同步**：drama wizard 也加预算 / cancel（统一行为）

**验收**：
- 单测 `tests/test_jobs_cancel.py`（新建）：
  - request_cancel 设标志位
  - worker 主循环检测到标志 → status=aborted
  - 超时 deadline 触发 → status=aborted
- 路由测试：cancel 路由 4 路用例（pending / running / succeeded / unknown）
- mock 链路：起 web，wizard 上传一个 mock workspace → 进度页点 cancel → 看到 aborted 状态 + CTA 组

---

### §B · D-7 移动响应式

**根因**（探查 2）：
- `static.py:875-886` `@media (max-width: 768px)` 把 sidebar `display: none` 硬隐藏
- 无 drawer / hamburger / topbar 折叠
- 表格无 card rows 变体

**实施**：

1. **Sidebar drawer + hamburger**：
   - templates.py 主 shell 加 hamburger 按钮（CSS class `.nav-toggle`，仅移动可见）
   - 768px 以下 sidebar 改 `position: fixed; transform: translateX(-100%)`，drawer 模式
   - hamburger 点击 toggle `.sidebar.open` class
   - 加遮罩层 `.sidebar-overlay`，点击关闭
   - 桌面端不变

2. **Topbar 移动折叠**：
   - 768px 以下 topbar actions（回收站 / 设置 / 新建）折叠到右侧"⋯"菜单
   - 面包屑保留但截短（只显示当前 + 上一级）

3. **表格响应式**：
   - jobs / chapters / reviews 表格在 768px 以下转 card rows：每行变 `<div class="row-card">`，关键字段堆叠显示
   - 或保留 `<table>` 加 `overflow-x: auto` + 渐变提示（轻量方案）—— 优先轻量方案，仅 jobs / chapters 必要时升级 card

4. **continue 页 step card**：
   - 移动端保持单列但压缩标题字号
   - readiness panel 主 CTA 卡片 + 折叠诊断结构本来就适合移动

**验收**：
- 截图回归：使用 chrome devtools 模拟 iPhone 13 + iPad 各跑 5 条 journey 截图
- 视觉验收点：sidebar drawer 可开关 / topbar 不溢出 / 表格不挤压
- 加 `tests/test_templates_mobile_classes.py`（轻量，可选）：grep 验证关键 CSS class 存在

---

### §C · D-8 剩余 UI debt

**实施**（3 个独立子项，单独 commit）：

1. **subscore inline → CSS class**：
   - `static.py:2634-2650 renderSubscores()` 抽 `.subscore-cell-approve` / `.subscore-cell-warn` / `.subscore-cell-fail` / `.subscore-cell-empty` CSS class
   - 颜色阈值（v >= 7 jade / 否则 default）通过 class 控制
   - 字体 mono 同样改 class
   - 不改 schema，纯 CSS 重构

2. **Insights scores/sub_scores fallback（兼容 iter042 schema 演进）**：
   - `static.py:2512 renderAgentReview` `a.sub_scores || {}` → `a.scores || a.sub_scores || {}`
   - `static.py:2589 initInsights` `data.subscores || []` → 保持，但 fetch 接口若返回 `scores` 字段也兼容
   - 加注释说明 "iter042 schema 引入 score 字段（panel_score），UI 同时兼容 legacy sub_scores"
   - 单测 `tests/test_static_subscore_compat.py`（如有 JS 测试基础则加，否则跳过）

3. **`_workspace_html_guard` 抽象（视情况）**：
   - 探查报告说"9+ 处调用但可能难抽象空间"
   - 本轮**不强制做**：只在阅读时若发现明显冗余才动；否则记录到 iter045 backlog
   - 这条作为可选 stretch goal，不阻塞 §C 收官

---

### §D · 文档刷新

**实施**：

1. **AGENTS.md 全面刷新**：
   - 删除/改写 L108-110 "iter 039 修 recent_jobs lost..." / "下一步候选（iter 043）"
   - 加 iter043 §A audit / §B 重构 / iter044 收尾的 phase status
   - "最近一次更新"对齐到 iter044
   - 命令清单 / SOP 表对齐当前能力（tier select / cancel / mock 提示等新功能）

2. **README.md 刷新**：
   - TL;DR 表加 iter043 audit / iter044 收尾条目
   - 功能清单加 tier 三档 / cancel / 移动响应式
   - 移除任何"iter 037 之前"的 todo 文案

3. **docs/AGENT_HANDOFF.md 刷新**：
   - Phase Status 补 iter043 / iter044
   - Backlog 清单：把 iter039 P2-C 标 done（本轮 §A 收）/ iter038 P3 标 done（本轮 §C 收）
   - 剩余 backlog 真实只有 `_workspace_html_guard 抽象`（如未做）+ F1 二次调优（按需）

4. **docs/iterations/README.md 索引刷新**（如存在）：
   - 加 iter036-044 索引行
   - 每行简短一句话描述"这一轮干了什么"

**验收**：grep 检查
- `iter 03[0-9]` 在 AGENTS.md / README.md 出现只能是历史叙述（如"iter 039 引入 partial"），不能是 "下一步候选" 这种过期 todo
- 4 个文档头部都有 "最后更新：iter 044" 或类似标记

---

## 关键文件清单

| 文件 | 改动 |
|---|---|
| `src/web/jobs.py` | 加 cancel_requested 标志 + JobCancelled 异常 + worker 检查点 + request_cancel helper + deadline 超时 |
| `src/web/routes.py` | 新增 POST cancel 路由 + 校验 + 测试 |
| `src/web/templates.py` | wizard 高级选项（预算/超时/extract limit）+ "会发生什么"提示卡 + sidebar drawer + hamburger + topbar 折叠 + 表格 card 类 |
| `src/web/static.py` | panel-progress CTA 重构 + cancel 按钮 JS + subscore CSS class 抽 + scores fallback + 移动 @media drawer 逻辑 |
| `tests/test_jobs_cancel.py`（新建） | cancel + timeout 单测 |
| `tests/test_routes_job_cancel.py`（新建） | 路由 4 路用例 |
| `tests/test_static_subscore_compat.py`（如可行） | sub_scores fallback |
| `AGENTS.md` | 全面刷新到 iter044 |
| `README.md` | TL;DR + 功能 + SOP 对齐 |
| `docs/AGENT_HANDOFF.md` | Phase Status 补 + Backlog 收尾 |
| `docs/iterations/README.md` | 索引刷新 |
| `docs/iterations/iteration_044_PLAN.md`（新建） | codex 执行档案 |
| `docs/iterations/iteration_044_PLAN_DRAFT.md`（新建） | 草稿盒副本归档 |

## 已有可复用工具

- `src/web/jobs.py _update / _progress` —— cancel/timeout 检查点直接挂这里
- `src/web/static.py CTA_ACTIONS`（iter043 §B 加的）—— panel-progress terminal CTA 直接复用
- `src/web/routes.py` partial draft / write-book retry 路由 —— terminal succeeded/failed CTA 跳转复用
- `tests/test_book_runner_*` / `tests/test_routes_*` —— fixture 风格

## 验收（顺序）

### 阶段 1 · 单测
```bash
.venv/bin/python -m unittest discover
```
基线：OK (skipped=6)，期望 ~582 tests（577 + 5 类新增）。

### 阶段 2 · mock 链路
```bash
OPENAI_MODEL=mock .venv/bin/python main.py preflight
PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
```

### 阶段 3 · 移动 + cancel 截图回归
- chrome devtools 模拟 iPhone 13 + iPad 各跑 4 条 journey（B 空起点 / C happy path / D 失败 / E drama），归档 `/tmp/iter044_mobile_screenshots_*/`
- mock cancel 流程：wizard 上传 → 进度页点 cancel → 截图 aborted 状态
- panel 末尾贴 before/after 对比小表

### 阶段 4 · 文档 grep
- 过期“下一步” grep（覆盖 iter040-043 旧候选文案）→ 0 命中
- `rg "TODO|FIXME" AGENTS.md README.md` → 检查是否仍有过期 todo

### 阶段 5 · subagent 只读审核
全部 commit 完成后，启动 1 个 read-only subagent 审核：
- cancel 协作式取消的并发安全（_JOBS 字典访问是否加锁）
- timeout deadline 在 worker 长时间无 progress 时是否触发（边界场景）
- 移动 drawer 在大屏 resize 时是否正确恢复
- subscore CSS class 命名规范是否与项目其他 class 一致
- 文档刷新后 AGENTS.md / README / HANDOFF 三者之间无矛盾
- 历史 workspace 兼容（无 type / 旧 schema）仍可加载
审核结论写入 iter044_PLAN.md 末尾

### 阶段 6 · 真实模型不跑
本轮全是 UI + 文档 + 1 个后端路由，不涉及 LLM 链路；**不跑真实模型**，节流。

---

## 边界 / 不在本轮做

- 不动 chapter_status / reviewer / writer / book_runner 核心 happy path（cancel 用 worker 协作式，不动 runner）
- 不动 iter042 打分制 / iter043 §B UX 主框架
- 不做 F1 二次 prompt 调优（按 iter043 §B Notes：仅在 mid 档下次卡住才开，当前不需要）
- `_workspace_html_guard` 抽象作为 §C 可选 stretch goal，不阻塞收官
- 不强制 kill worker 线程（用协作式取消）
- 不 push 任何 commit

---

## iter045+ 预告（不在本轮）

- 取决于用户优先级：
  - drama 站③④（分镜 + 角色设定）功能开放
  - 多 workspace 协作 / 版本对照
  - chapter_summary / KB 自动更新链路
  - F1 二次调优（如真实跑 mid 档再次卡住）
- 文档已对齐，进下一阶段时不再有"先刷新文档"的隐性税
