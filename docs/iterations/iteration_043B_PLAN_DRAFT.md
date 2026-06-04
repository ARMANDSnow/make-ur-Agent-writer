# Iteration 043 §B · UX 重构 Bundle 1+2（D-1/D-2/D-3/D-4/D-6）

> 文件名沿用草稿盒路径；iter039/040/042/043§A plan 已归档到 `docs/iterations/iteration_*_PLAN_DRAFT.md`。iter041 INVESTIGATION + iter043 UX_AUDIT 在 prep commit 一并 git add。

## Context

**为什么这一轮做这个**：iter043 §A audit（`docs/iterations/iteration_043_UX_AUDIT.md`）锁定 8 个 UX 修复方向。用户拍板 Bundle 1+2 合并：D-1 readiness 主 CTA / D-2 jobs drawer / D-3 sidebar type-aware / D-4 write-book preset+tier / D-6 drama shell 收口。一轮扫清 5 个历史 backlog（iter039 P2-A/B + iter042 tier UI + drama 内部文案 + 空起点满屏报错）。

**用户视角痛点**（来自 §A audit 实测）：
- 进 asoiaf 续写页 → 红黄 alert 满屏暴露 `start_point_missing` / `chapter_plan_missing` 等内部字段
- 进 longzu 续写页 → ch2 已 approved 但默认 `resume_from=1` 让旧 ch1 strict failures 把整页拖成 blocked
- iter042 后端有 tier 参数，前端无入口，mid 档要靠 env 切
- drama 写着 "iter 038 起开放"（实际已 iter043），文案泄露内部状态
- partial draft 落盘了但 jobs 页看不到入口

**iter043 §B 目标**：让"真实用户在前端能看出下一步做什么"——空起点能直接点 CTA 而不是看红 alert，happy path 不被旧 ch 卡住，failed/blocked 在 jobs 页能展开恢复，tier 在表单里能选，drama shell 不再泄露 iter 编号。

**预算**：全 UI 层改动，mock 链路验证零真实 token；预计 8-9 commits / 65-100k tokens / 折人民币 ~¥1。

---

## 修复方案

### §A · D-1 Readiness 分层 + 下一步主 CTA

**根因**（audit Journey B/C + 探查报告）：
- `src/web/static.py:1681-1699 renderReadinessPanel()` 把 blockers/warnings/commands 混排为诊断列表，无主 CTA
- `src/web/static.py:1663` 默认 `resume_from=1` 不看下一个未 approved 章节
- `src/book_runner.check_write_readiness()` 返回 blockers 包含内部字段（如 `chapter_02:existing_output_not_strict_approved:verdict=Reject...`），前端直出

**实施**：

1. **后端：`src/book_runner.py check_write_readiness()` 新增字段**：
   - `next_unapproved_chapter: int | None` —— 扫描 chapter_status 找第一个非 approved 章节，给前端 resume_from 默认值
   - `primary_blocker: dict | None` —— 把 blockers 数组里的"首要下一步"提取出来，结构 `{kind, label, cta_action, cta_label}`，例如 `{kind: "start_point_missing", label: "未设置续写起点", cta_action: "scroll_to_start_point", cta_label: "去设置起点"}`
   - 现有 blockers/warnings/recommended_commands 保留作为"诊断详情"

2. **前端：`src/web/static.py renderReadinessPanel()` 改造**：
   - 顶部主 CTA 卡片：根据 `primary_blocker.kind` 渲染对应 CTA 按钮（点击触发已有逻辑：scroll to 起点 / 调用 plan-chapters / 切换 resume_from）
   - 中部紧凑状态行：status + chapters + resume_from + plan_window 保留为 1 行 KV
   - 底部折叠"诊断详情"（默认收起）：放完整 blockers + warnings + recommended_commands

3. **前端：`src/web/static.py:1663 refreshReadiness()` 改默认 resume_from**：
   - 优先用 `data.next_unapproved_chapter`，没有时 fallback `data.resume_from`
   - write-book 表单同步默认值

4. **CTA 文案规范**（给 D-2 复用）：
   - 在 static.py 顶部新增 `CTA_ACTIONS` 常量映射表：`{ "start_point_missing": {...}, "outline_missing": {...}, "chapter_plan_missing": {...}, "retry_exhausted": {...} }`
   - 每条含 label / action / cta_label

**验收**：
- 单测 `tests/test_book_runner_readiness.py` 已存在则扩展，否则新建：断言 next_unapproved_chapter / primary_blocker 字段在 blocked / partial-approved / fully-approved 三种 fixture 下计算正确
- mock 链路：asoiaf workspace（空起点）打开 continue 页，截图对比 before/after，红 alert → 主 CTA 卡片
- mock 链路：longzu workspace 打开 continue 页，resume_from 自动预填到 ch3（ch2 已 approved）

---

### §B · D-2 Jobs drawer + failure recovery

**根因**（audit Journey D + 探查报告）：
- `src/web/static.py:2433-2461 initJobs()` 表格 6 列（step/status/job_id/trace_id/started/note）
- note 走 `jobFailureLine()` 截断 120 字（L2454），iter039 P2-A backlog 仍存在
- `result_summary` / `snapshot_path` / partial draft 链接 backend 都有，前端不展示
- iter039 加的 `GET /api/workspace/<ws>/draft/<chapter>?variant=partial` 路由（routes.py L718-737）健在但 jobs 页没集成

**实施**：

1. **前端：jobs 表格每行加展开 drawer**：
   - 每行 `<tr>` 旁加 "▸" 切换按钮，点击展开下方 `<tr class="drawer">` 详情
   - drawer 内容：
     - 完整 `result_summary` 美化展示（key/value 表）
     - trace_id + snapshot_path + partial draft 链接
     - 根据 status 渲染 action 按钮组（复用 §A 的 CTA_ACTIONS）：
       - `failed + result_summary.partial` → "查看 partial draft" / "用相同参数重试"
       - `blocked + outline_missing` → "去计划页"
       - `blocked + retry_exhausted` → "回到章节" / "用相同参数重试"
       - `succeeded` → "查看章节"

2. **"用相同参数重试" 实现**：
   - 复用 job.params，构造同样 POST 到 write-book/plan-chapters API
   - 不新增后端路由（用现有的 step 入口）

3. **note 列改造**：
   - 保留 120 字摘要作为表格行展示（drawer 已经提供完整信息，不必去掉截断）
   - 摘要文案用新 helper `jobActionableSummary(job)`（在 jobFailureLine 基础上加 status icon + 关键 reason）

4. **partial 链接路径**：
   - drawer 里直接调 `/api/workspace/<ws>/draft/<chapter>?variant=partial`（routes.py L718-737 已存在）
   - 新增轻量"partial preview modal"：fetch 后展示文本前 2000 字 + "下载完整" 按钮

**验收**：
- mock 链路：iter039smoke workspace 打开 jobs 页，看到 failed job 展开有 partial 链接；点击可见草稿
- 截图对比 before/after Journey D 4 个步骤
- 单测：`tests/test_jobs_drawer.py` 新建，断言 jobActionableSummary 在 4 种 status × 2 种 first_blocked.reason 下输出正确

---

### §C · D-3 Sidebar/书架 type-aware + 历史 incident 降权

**根因**（audit Journey A/C/E + 探查报告）：
- `src/web/static.py:1004-1037 renderWorkspaceCard()` 用 typeBadge 显示 type 但卡片内容全用 novel 指标（起点/计划/最近任务）
- `src/web/static.py:1700-1721 refreshRecentJobsSidebar()` recent jobs 平铺，无"当前 / 历史 / 失败" 分层
- 短剧卡片显示小说 readiness（i38drama01 显示"blocked"是因为吃了 novel 路径）
- iter038 P3 backlog `style="font-size:14px"` inline style 仍在

**实施**：

1. **书架卡片 type-aware 渲染**：
   - `renderWorkspaceCard()` 拆成两个分支：
     - `type === "novel"`：现有 起点/计划/最近任务 三行
     - `type === "drama"`：站①设定 / 站②钩子 / 站③④锁定 三行（数据从 drama overview 接口拿，已存在）
   - 整体卡片样式保持一致，只换数据 schema

2. **后端：`_workspace_overview()` 接口扩展（routes.py L400-464）**：
   - novel 路径不变
   - drama 路径返回 `drama_progress: { station1, station2, station3, station4 }` 替代 novel 的 readiness/manifest

3. **sidebar 历史 incident 降权**：
   - `refreshRecentJobsSidebar()` 把 recent jobs 分两段：
     - "当前 / 最近完成"：最新一条非 lost/failed 或最新一条 succeeded
     - "历史"：其他 lost/failed/blocked，视觉降权（opacity 0.6 + 灰色 badge）
   - 书架卡片的 "最近任务" 字段也走同样降权逻辑

4. **顺手清债（iter038 P3）**：
   - `renderWorkspaceCard()` 里 `style="font-size:14px"` inline → 新增 CSS class `.metric-small`，放 templates.py 内联 style 块
   - typeBadge() inline color → `.badge-novel` / `.badge-drama` CSS class

**验收**：
- mock 链路：书架页同时看到 longzu (novel) / i38drama01 (drama) 卡片，drama 卡片显示站①②③④ 不再显示 "blocked"
- 截图对比 before/after Journey A 书架 + Journey C sidebar + Journey E drama 入口
- 单测：`tests/test_workspace_overview_drama.py` 新建，断言 drama type 返回 drama_progress 字段

---

### §D · D-4 Write-book preset + tier 选档器

**根因**（audit Journey C + 探查报告）：
- `src/web/templates.py:462-475` 表单 7 个工程参数裸暴露
- iter042 后端已支持 tier（`src/web/jobs.py:316`），前端无 select
- routes.py L949-970 参数校验未列 tier

**实施**：

1. **表单顶部新增 3 个 preset segmented control**：
   - 试写：tier=low, chapters=1, max_retries=1, budget_cny=2, auto_advance=false
   - 生产：tier=mid, chapters=1, max_retries=2, budget_cny=10, auto_advance=true（默认选中）
   - 严格：tier=high, chapters=1, max_retries=3, budget_cny=30, auto_advance=true
   - 选择 preset 自动填充下方各字段

2. **新增 tier 字段**：
   - 表单加 `<select name="tier">` 含 low/mid/high 三选项 + 解释文案：
     - low: "快速试写，宽松通过（成本最低）"
     - mid: "日常生产，平衡通过（默认）"
     - high: "严格评审，发布门槛"
   - 提交时透传到 `_step_write_book` params

3. **高级参数折叠**：
   - chapters / resume_from / tier 保持显示
   - budget_cny / replan_every / max_retries / min_confidence / auto_advance 默认折叠到 "高级参数" `<details>` 块

4. **budget_cny 人话化**：
   - label 改为 "本次最多花费 CNY"
   - 占位符 "0 = 不限制；mock 模式不消耗真实 token"
   - mock 检测（前端 `OPENAI_MODEL` 不可见，改成只在底部加提示文案 "当前 server 配置见 /preflight"）

5. **routes.py L949-970 `_validate_write_book_params` 加 tier 校验**：
   - 合法值 low/mid/high
   - 缺失则按 mid 默认

**验收**：
- mock 链路：write-book 表单看到 3 preset + tier select + 高级折叠
- 选 "试写" preset 后字段自动填充，提交后 job params 含 tier=low
- 单测：`tests/test_routes_write_book_tier.py` 扩展，断言 tier=invalid 返回 400、缺失透传默认

---

### §E · D-6 Drama shell 收口

**根因**（audit Journey E + 探查报告）：
- templates.py L382/388-389 + static.py L1178 出现 "iter 038 起开放" / "等待 iter 038 解锁分镜"
- routes.py L157-171 `_workspace_html_guard_novel_only()` 返回裸 HTML 404，不走 shell
- routes.py L901 `POST /run` hint 写 "drama bootstrap arrives in iter 037"

**实施**：

1. **过期文案改产品态**：
   - "iter 038 起开放" → "分镜站尚未开放，本地 Beta 暂只支持核心设定与钩子站"
   - "等待 iter 038 解锁分镜" → "已完成前 2 站。分镜与角色设定将在后续版本上线"
   - "drama bootstrap arrives in iter 037" → 删掉这个 hint 或改 "drama 模块已可用"

2. **drama novel-only 404 改 shell empty-state**：
   - `_workspace_html_guard_novel_only()` 改为返回完整 shell HTML（套 templates.py 主结构），内容为 empty-state 卡片：
     - 标题 "此页面属于小说模块"
     - 说明 "当前 workspace 是短剧。该功能不适用于短剧模块。"
     - CTA 按钮组：返回 drama overview / write / jobs
   - 状态码改 200（用户视角不是错误）

3. **iter038 P3 backlog 顺手清掉的剩余几项**（不在 §C 已清的之外的）：
   - drama wizard textarea placeholder 从 `placeholder, see creation_standard` → 实际填写示例（如 "示例：复仇 → 救赎，单线发展，强冲突"）
   - toast 5000ms 加可选 dismiss 按钮（小改动，与 D-6 一起做）

**验收**：
- mock 链路：访问 `i38drama01/reviews` → 看到统一 shell + empty-state，不再裸 404
- 截图对比 Journey E storyboard locked 文案
- grep "iter 03[0-9]" 在 src/web/ 下无残留（除 docs 之外）

---

## 关键文件清单

| 文件 | 改动 |
|---|---|
| `src/web/static.py` | 主战场：CTA_ACTIONS / renderReadinessPanel / refreshReadiness / initJobs + drawer / refreshRecentJobsSidebar / renderWorkspaceCard / jobActionableSummary |
| `src/web/templates.py` | write-book 表单 preset + tier select + 高级折叠；drama 过期文案；drama wizard placeholder；新增 `.metric-small` / `.badge-novel` / `.badge-drama` CSS |
| `src/web/routes.py` | `_workspace_overview` drama 路径加 drama_progress；`_workspace_html_guard_novel_only` 改 shell empty-state；`_validate_write_book_params` 加 tier 校验；drama `POST /run` hint 文案 |
| `src/book_runner.py` | `check_write_readiness` 加 next_unapproved_chapter + primary_blocker 字段 |
| `tests/test_book_runner_readiness.py`（扩展或新建） | next_unapproved_chapter / primary_blocker 单测 |
| `tests/test_jobs_drawer.py`（新建） | jobActionableSummary 输出单测 |
| `tests/test_workspace_overview_drama.py`（新建） | drama type drama_progress 字段单测 |
| `tests/test_routes_write_book_tier.py`（扩展或新建） | tier 校验单测 |
| `docs/iterations/iteration_043_PLAN.md` | iter043 §A plan 升级为 §A+§B 全轮档案，补 §B 实施笔记 |
| `docs/iterations/iteration_041_INVESTIGATION.md` | prep commit 一并 git add（iter041 漏归档） |
| `docs/iterations/iteration_043_UX_AUDIT.md` | prep commit 一并 git add |

## 已有可复用工具

- `src/book_runner.check_write_readiness` —— blockers/warnings/recommended_commands 已传，只加新字段
- `src/web/routes.py:718-737` —— partial draft API 已存在，drawer 直接 fetch
- `src/web/jobs.py:316` —— tier 参数后端通路已经做完
- `src/web/templates.py:265` + meta.type 读取 —— type-aware 渲染基础
- `tests/test_book_runner_*` —— 现有 fixture 风格

## 验收（顺序）

### 阶段 1 · 单测
```bash
.venv/bin/python -m unittest discover
```
基线：OK (skipped=6)，期望 ~573 tests（569 + 4 类新增）。

### 阶段 2 · mock 链路 + 截图回归
```bash
OPENAI_MODEL=mock .venv/bin/python main.py preflight  # PREFLIGHT: ok
PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh   # exit 0
```

mock 起 web，按 audit 5 条 journey 重跑一遍并截图，保存 `/tmp/iter043B_screenshots_$(date +%Y%m%d_%H%M%S)/`，在 iter043_PLAN.md 末尾贴 before/after 对比小表：
- Journey B：空起点 → 主 CTA 卡片（不再红 alert 满屏）
- Journey C：longzu happy path → resume_from 自动到 ch3 + tier 选档器可见
- Journey D：iter039smoke jobs → drawer 展开 + partial 链接
- Journey E：i38drama01 → 过期文案清理 + drama_progress 卡片 + reviews 不再 404

### 阶段 3 · subagent 只读审核
全部 commit 完成后，启动 1 个 read-only subagent 审核：
- CTA_ACTIONS 常量在 D-1 和 D-2 用法一致
- jobActionableSummary 与 jobBlockedDetail（iter039 留的）无功能重复或冲突
- `_workspace_html_guard_novel_only` 改 shell 后状态码改 200 不破坏现有 client/test 假设
- iter038 P3 backlog 6 项中本轮覆盖的 4 项确认清除（type badge / metric inline / placeholder / toast）
- 历史 workspace 兼容：meta 里没有 type 字段的旧 workspace 默认走 novel 渲染
审核结论写入 iter043_PLAN.md 末尾

### 阶段 4 · 真实模型不跑
本轮全是 UI 层改动，不涉及 LLM 链路。**不跑真实模型**，节流给 iter044。

---

## 边界 / 不在本轮做

- 不动 chapter_status / reviewer / writer / book_runner 核心 happy path（只在 check_write_readiness 加新字段，不改判定）
- 不动 iter042 打分制 / tier 阈值（只暴露 UI）
- 不做 Bundle 3：D-5 onboarding 重构 / D-7 移动响应式 / D-8 全量 UI debt clean → iter044
- iter038 P3 backlog 6 项里只清本轮自然覆盖的 4 项（type badge / metric inline / placeholder / toast），剩 2 项（subscore inline / _workspace_html_guard 抽象）转 iter044
- 不 push 任何 commit

---

## iter044 预告（不在本轮）

- D-5 Onboarding critical path（wizard 加预算/timeout/cancel + 运行中 terminal 下一步）
- D-7 移动响应式（sidebar drawer + 表格 card rows）
- D-8 剩余 UI debt（subscore inline / _workspace_html_guard 抽象 / 其他 P3）
- AGENTS.md / README / SOP 全面刷新
- F1 reviewer prompt 二次调优（如发现需要）
