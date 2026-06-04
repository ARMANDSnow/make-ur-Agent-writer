# iter043 §A · WebUI UX Audit

## 0. 调查范围 + 方法回顾

本轮按 iter043 §A plan 对小说模块、drama 模块、新书 onboarding、跨页面通用元素做 read-only UX audit：`OPENAI_MODEL=mock` 启动本地 Web 于 `http://127.0.0.1:8793/`，用 Browser 走查 5 条 journey，截图归档到 `/tmp/iter043_ux_screenshots_20260604_235600/`；同时静态阅读 `src/web/templates.py` / `src/web/static.py` / `src/web/routes.py` 与 iter038/039/041/042 记录。因“上传并启动 pipeline”会创建 workspace 并写 ignored 产物，和本轮 read-only 边界冲突，本轮没有重新 POST 上传；冷启动 journey 覆盖到 wizard 上传前，并用既有 greenfield/失败 workspace 观察后续状态。Web/UI 相关技能实际使用 Browser skill + 静态 UI audit；当前环境没有独立的“UI audit”专用 skill。

## 1. user journey 走查 · 5 条路径

### Journey A · 冷启动：书架 → 新建 → 小说 wizard → 上传前

| 步骤 | 现状 | 困惑点 | 严重度 | 截图 |
|---|---|---|---|---|
| 进入书架 | 书架展示 13 个本地 workspace，顶部只有总数/就绪/警示/受阻统计；短剧卡片也显示小说指标。 | 新用户若不是空书架，会先看到大量 `blocked`，不知道哪个是“可继续”的示例；短剧被小说 readiness 污染。 | P1 | ![书架](/tmp/iter043_ux_screenshots_20260604_235600/01_shelf_loaded.png) |
| 点击新建 | 第 0 步先选“小说续写 / 短剧剧本”，文案清晰但没有说明后续会启动 9 步流水线、耗时、是否可取消。 | 用户不知道“开始”后会等多久、是否烧真 token、失败是否会留下半成品。 | P1 | ![wizard 类型选择](/tmp/iter043_ux_screenshots_20260604_235600/02_wizard_type.png) |
| 小说上传表单 | 表单只有 workspace 名和文件，没有预算、timeout、取消、mock/real 提醒；上传按钮叫“开始”。 | “开始”语义过宽，用户无法判断是只导入、还是会 extract/write；缺少必填/可跳过说明。 | P1 | ![wizard 上传小说](/tmp/iter043_ux_screenshots_20260604_235600/03_wizard_novel_upload.png) |
| 上传 + extract | 本轮未重新触发，原因见 §0；历史 greenfield workspace 显示 lost/blocked 后用户只能回到 workspace 排障。 | 成功后的“下一步做什么”与失败后的恢复路径不集中在 wizard terminal。 | P2 | 同上 |

### Journey B · 空起点：已有 workspace 但未设起点 → 续写页

| 步骤 | 现状 | 困惑点 | 严重度 | 截图 |
|---|---|---|---|---|
| 打开 `asoiaf/continue` | 页面顶部是 3 个操作卡：起点、章节计划、继续写书；就绪面板在下方显示 `blocked`。 | 主操作看起来都可用，但“继续写书”按钮被禁用，真正原因要往下看。 | P1 | ![空起点续写页](/tmp/iter043_ux_screenshots_20260604_235600/06_empty_start_continue_asoiaf.png) |
| 查看 blockers | 红色 alert 同时显示 `start_point_missing`、`chapter_plan_missing`；黄色 alert 塞入超长 preflight 文案。 | 错误态压过任务步骤，且英文内部字段直接暴露；用户不知道先处理哪一个。 | P1 | 同上 |
| 推荐命令 | 面板给 CLI 命令：`set-start-point <chapter_id>` 与 `plan-chapters --force`。 | Web 用户刚在 UI 里点操作，却被引导回 CLI；“保存起点”按钮与推荐命令重复但没有串起来。 | P1 | 同上 |
| 移动宽度 | 顶部导航被挤成竖排字，full-page 截图中 sticky topbar 重复出现；侧栏没有真正折叠成菜单。 | 手机上关键路径可读性明显下降，导航占用过多首屏。 | P2 | ![移动续写页](/tmp/iter043_ux_screenshots_20260604_235600/19_mobile_continue_asoiaf.png) |

### Journey C · 续写 happy path：起点 + 大纲齐备 → write-book → 终态

| 步骤 | 现状 | 困惑点 | 严重度 | 截图 |
|---|---|---|---|---|
| 打开 `longzu/continue` | 起点和计划存在，右侧最近任务有 `succeeded`；但 readiness 仍因旧 ch1 strict failures 显示全页 blocked。 | ch2 已 approved，但页面默认 `resume_from=1` 让旧 ch1 问题挡住当前 happy path；用户需要知道应改成 ch2/ch3。 | P1 | ![longzu continue](/tmp/iter043_ux_screenshots_20260604_235600/07_happy_continue_longzu.png) |
| 表单参数 | write-book 表单暴露 6 个数字 + auto advance；iter042 的 `tier=mid/high/low` 没有 UI 入口。 | 新用户无法理解“推进置信度 / 每几章重规划 / 最大重试”，也无法选择评审档位。 | P1 | 同上 |
| 任务历史 | `longzu/jobs` 显示 latest `succeeded`、之前 `failed`、`blocked`；note 一列只有一行摘要。 | 成功与失败混排但没有“当前有效结果”/“历史 incident”分层；failed 的已修 tail incident 仍抢注意。 | P2 | ![longzu jobs](/tmp/iter043_ux_screenshots_20260604_235600/08_happy_jobs_longzu.png) |
| 章节详情 | ch2 meta/review 均 `Approve`，`tier=mid`、`panel_score=7.58`、`approve_count=4` 已落盘；页面 header 只显示 Approve、字数、rewrite。 | 关键的 tier、panel_score、approve_count 不在前端展示，用户无法理解“为什么通过”。 | P1 | ![longzu ch2](/tmp/iter043_ux_screenshots_20260604_235600/09_happy_chapter2_longzu.png) |

### Journey D · 续写失败：blocked / partial → 错误可行动性

| 步骤 | 现状 | 困惑点 | 严重度 | 截图 |
|---|---|---|---|---|
| partial 草稿 | `iter039smoke/chapters` 能看到 `chapter_01.partial`，带 `partial` + `failure` badge。 | 入口存在，这是优点；但用户只能“查看”，没有“用 partial 恢复 / 复制为草稿 / 重试本章”的按钮。 | P1 | ![partial chapters](/tmp/iter043_ux_screenshots_20260604_235600/10_failure_partial_chapters_iter039smoke.png) |
| failed jobs | `iter039smoke/jobs` 只显示 `write-book failed`，note 空；partial 路径在 job summary 里存在但 Jobs 页没露出。 | 失败页看不出最后产物在哪里，也不知道下一步该去 chapters。 | P1 | ![failed jobs](/tmp/iter043_ux_screenshots_20260604_235600/11_failure_jobs_iter039smoke.png) |
| blocked jobs | `iter039blocked/jobs` 显示 `outline_missing · outline not found; run python main.py debate first`。 | 这是可行动信息，但仍是 CLI-first；没有“去计划页/先跑 debate”的 Web CTA。 | P1 | ![blocked jobs](/tmp/iter043_ux_screenshots_20260604_235600/12_blocked_jobs_iter039blocked.png) |
| trace / copy | job_id、trace_id 有复制按钮；note 被 120 字截断。 | 调试友好但用户恢复不友好；长错误没展开，iter039 P2-A 仍存在。 | P2 | 同上 |

### Journey E · drama：wizard → workspace → station → debate/subscore 缺口

| 步骤 | 现状 | 困惑点 | 严重度 | 截图 |
|---|---|---|---|---|
| drama wizard | 表单有 workspace、题材、赛道、集数、时长；textarea placeholder 仍是 `placeholder, see creation_standard`。 | 这是内部工程占位，不是用户语言；会降低可信度。 | P2 | ![wizard drama 入口同页](/tmp/iter043_ux_screenshots_20260604_235600/02_wizard_type.png) |
| drama overview | `i38drama01` 显示 4 站进度，站①/② done，站③/④ locked；下一步写“等待 iter 038 解锁分镜”。 | 当前已 iter043，文案过期；用户不知道是未实现、没权限、还是数据缺失。 | P1 | ![drama overview](/tmp/iter043_ux_screenshots_20260604_235600/13_drama_overview_i38drama01.png) |
| drama write | 站①表单可编辑，站②已 done；站③/④ tab 可点但只有 empty-state。 | “可点但不可做”的 tab 容易制造误期望；没有明确 roadmap/返回建议。 | P2 | ![drama write](/tmp/iter043_ux_screenshots_20260604_235600/14_drama_write_i38drama01.png) |
| storyboard locked | Empty-state 仍写 `iter 038 起开放`。 | 过期文案是最直观的产品未打磨信号。 | P1 | ![drama storyboard locked](/tmp/iter043_ux_screenshots_20260604_235600/15_drama_storyboard_locked.png) |
| debate/subscore | drama 侧没有 debate/subscore 页面；`/reviews`、`/insights`、`/continue` 返回裸 404。 | 裸 404 断掉统一 shell；用户无法判断 drama 评审/打分是“不支持”还是“页面坏了”。 | P1 | ![drama reviews 404](/tmp/iter043_ux_screenshots_20260604_235600/18_drama_reviews_404.png) |

## 2. 跨页面通用问题

### 2.1 导航

侧栏信息架构在桌面上可用，但缺少“下一步”优先级：同一页同时出现 breadcrumbs、sidebar、topbar actions、flow steps、recent jobs。移动宽度下侧栏没有折叠策略，topbar actions 被挤成竖排字，首屏被导航占掉。短剧只显示 overview/write/jobs，但书架卡片仍按小说 readiness 算 blocked，跨类型入口不一致。

### 2.2 错误态视觉

错误态主要是红/黄 alert 直出内部字段。空起点页一次性展示 blocker、preflight warn、recommended CLI commands，像诊断面板而不是工作流引导。裸 404 没有套统一 shell；drama novel-only 页面直接跳出产品视觉。历史 failed/lost 与当前 actionable blocked 视觉权重相近。

### 2.3 信息密度（toast / blocked reason / tier panel_score）

Jobs 页 note 仍截断到 120 字，terminal toast 截 80 字，缺少展开详情。ch2 的 `tier/panel_score/approve_count` 已在 meta/review 存在，但 chapter detail/reviews/insights 没有显式展示；用户只能看到 Approve。LLM logs tail 直接展示 JSON 行，适合开发者，不适合普通用户排障。

### 2.4 表单控件

write-book 表单暴露工程参数，缺少 preset：例如“快速试写 / 正常生产 / 严格评审”。`tier` 后端入口已存在但前端没有 select。wizard 小说路径缺预算、timeout、cancel；drama topic placeholder 仍是工程占位；多个按钮仍使用文本符号箭头/加号而非统一 icon 体系。

### 2.5 sidebar 最近任务

recent jobs 能显示 succeeded/failed/blocked，但没有“历史 incident 降权”。在 `longzu` happy path 中，最新 succeeded 下方紧跟已修 failed 和 blocked，使用户误以为当前仍不稳定。书架卡片也把 recent lost/blocked 放入卡片摘要，缺少“历史”标签。

## 3. drama 模块 UX 现状

drama 当前和小说模块共用视觉底座，但用户心智不一致：小说是 production runner，drama 是 4 站向导前 2 站。书架仍用小说指标判定短剧 `blocked`；短剧 overview/write 页面里的 done/locked 状态清楚，但文案停在 iter038，且站③/④看起来像“应该已开放”。drama 没有 reviews/insights/debate/subscore 的 shell 内空状态，访问相关页是裸 404；`POST /run` 的 hint 也仍写 “drama bootstrap arrives in iter 037”。

iter038 P3 backlog 6 项现状：

| P3 项 | 现状 |
|---|---|
| hardcoded inline color in type badge | 仍存在：`templates.py` drama badge、`static.py::typeBadge()` 继续写 inline style。 |
| subscore table inline style | 仍存在：`renderSubscores()` 仍内联 background / font / text-align。 |
| workspace card metric inline font-size | 仍存在：书架卡片起点/计划/最近任务用 `style="font-size:14px"`。 |
| `_workspace_html_guard_novel_only` 与 `_workspace_html_guard` 抽象 | 仍存在；且 drama novel-only 页是裸 404。 |
| toast 5000ms 硬编码无 dismiss | 仍存在：`showToast()` 5s 自动消失，无关闭按钮。 |
| drama wizard textarea placeholder | 仍存在：`placeholder, see creation_standard`。 |

## 4. 横向对标摘要

Notion AI 的 Plan Mode 强调“先出计划，用户审阅/批准后再执行”，参考 [Notion help](https://www.notion.com/help/review-and-approve-plans-before-notion-ai-runs)；Cursor Background Agents 把长任务放到可查看状态、可 follow-up、可 take over 的后台任务语境，参考 [Cursor docs](https://docs.cursor.com/background-agent)。对比下来，本项目的底层 job/progress 能力已经接近，但 UI 还落后在“等待时我能做什么”和“失败后下一步按钮”上。

Sudowrite 的 Write 入口把自动/引导式写作包装成低参数选择，生成结果以可插入/保留/丢弃的创作卡片呈现，参考 [Sudowrite docs](https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/write/6JmxspPSKDf6y7K5PVBZxa)。对比下来，本项目在工程透明度上领先，但在 onboarding 的“必填 vs 可跳过”和写作参数分层上落后。

## 5. 已知 backlog 整合（不重复发现，只标“仍存在”）

| Backlog | 状态 |
|---|---|
| iter039 P2-A jobs 80/120 字截断、trace_id badge 优化、展开详情 | 仍存在。Jobs 页 note 截断，失败详情和 partial 链接没有 drawer。 |
| iter039 P2-B sidebar 历史 lost 视觉降权 | 仍存在。书架/侧栏/recent jobs 没区分历史 incident 与当前状态。 |
| iter039 P2-C onboarding budget/timeout/cancel 控件 | 仍存在。wizard 上传前没有预算、timeout、cancel；运行中无取消入口。 |
| iter042 §C 留的 tier UI 入口 | 仍存在。后端支持 `tier`，前端 write-book 表单没有选档器。 |
| iter042 subagent 留的 Insights/UI `scores || sub_scores` 兼容 | 仍存在风险。UI 仍主要读 legacy `sub_scores`。 |

## 6. 修复方向候选 + ROI 排序

### D-1 · Readiness 分层 + 下一步主 CTA

**覆盖问题**：Journey B 全部、Journey C 默认 `resume_from=1` 误阻塞、§2.2。

**修复策略**：把 readiness 从“诊断列表”改成“当前阶段卡”：P0 blocker 只显示首要下一步，例如“先设置续写起点”；其他 warnings 折叠到“诊断详情”。把 CLI recommended command 映射成 Web CTA：去起点选择、生成计划、查看草稿、重试本章。默认 `resume_from` 可根据下一个未 approved 章节预填，避免 ch2 happy path 被旧 ch1 卡住。

**工作量**：中（2 commit）。**用户感受改善**：高。**依赖**：无。**ROI 综合**：高。

### D-2 · Jobs 详情 drawer + failure recovery

**覆盖问题**：Journey D、iter039 P2-A、§2.3。

**修复策略**：Jobs 表格保留摘要，但每行可展开：完整 `result_summary`、trace_id、snapshot_path、partial draft link、blocked reason、推荐下一步。对 partial/failed 提供“查看 partial”“回到章节”“用相同参数重试”的按钮；对 `outline_missing` 提供“去计划/先运行 debate”的 Web 入口或明确说明当前只能 CLI。

**工作量**：中（2 commit）。**用户感受改善**：高。**依赖**：D-1 的 CTA 文案规范可复用。**ROI 综合**：高。

### D-3 · Sidebar/书架状态 type-aware + 历史 incident 降权

**覆盖问题**：Journey A 书架、Journey C recent jobs、Journey E 短剧 blocked 污染、§2.5。

**修复策略**：书架卡片按 workspace type 渲染指标：novel 显示起点/计划/草稿，drama 显示站①-④进度。recent jobs 加“当前运行/最近完成/历史失败”层级，lost/failed 如果不是最新 actionable 状态则降权显示。卡片上的 blocked reason 只展示当前 readiness，不用历史 job 覆盖。

**工作量**：中（2 commit）。**用户感受改善**：高。**依赖**：无。**ROI 综合**：高。

### D-4 · write-book 表单 preset + tier 选档器

**覆盖问题**：Journey C 表单参数、iter042 tier UI、§2.4。

**修复策略**：保留高级参数，但默认折叠；顶部改成 3 个 preset：试写、生产、严格。新增 `tier` segmented/select：low/mid/high，并解释成本/通过门槛。预算输入改成人类语言，例如“本次最多花费 CNY”，默认 mock 下显示“mock 不消耗真实 token”。

**工作量**：轻到中（1-2 commit）。**用户感受改善**：高。**依赖**：后端已有 tier 参数。**ROI 综合**：高。

### D-5 · Onboarding critical path：预算 / timeout / cancel / terminal 下一步

**覆盖问题**：Journey A、iter039 P2-C、§2.4。

**修复策略**：wizard 上传页增加“会发生什么”步骤条和可选参数：目标章节数、extract limit、预算上限、timeout、运行后是否自动进入 workspace。运行中 terminal 显示“可以做什么”：继续浏览书架、查看日志、取消任务。成功后给“设置起点 / 查看章节 / 继续写”三个下一步；失败后给“查看失败详情 / 回滚重试”。

**工作量**：重（3 commit）。**用户感受改善**：高。**依赖**：如果要真 cancel，需要新增 job cancel POST；只做展示和 timeout 可先轻量。**ROI 综合**：中。

### D-6 · drama shell 收口：过期文案、站③④、404 空状态

**覆盖问题**：Journey E、§3。

**修复策略**：把 `iter 038 起开放` 等内部迭代文案改成产品态：“分镜站尚未开放，本地 Beta 暂只支持核心设定和钩子”。drama novel-only 404 改为统一 shell 内 empty-state，说明该页面属于小说模块，并给回 drama overview/write/jobs 的 CTA。`POST /run` hint 更新或隐藏。

**工作量**：轻（1 commit）。**用户感受改善**：中。**依赖**：无。**ROI 综合**：高。

### D-7 · 移动导航与表格响应式

**覆盖问题**：Journey B 移动截图、§2.1。

**修复策略**：移动端把 sidebar 改成顶部 workspace switcher / drawer；topbar actions 合并为菜单；continue flow 的 step card 保持单列但压缩标题。表格在移动端改成 card rows 或允许横向滚动提示，避免 job/chapter 表格挤压。

**工作量**：中到重（2-3 commit）。**用户感受改善**：中。**依赖**：D-3 若改 sidebar，可合并做。**ROI 综合**：中。

### D-8 · UI debt cleanup：inline style → component classes

**覆盖问题**：iter038 P3 6 项中 type badge/subscore/metric/toast/placeholder，§3。

**修复策略**：抽 `.badge-drama/.badge-novel`、`.metric-small`、`.subscore-cell-*`、toast dismiss/timeout 常量，替换工程 placeholder。这个方向偏设计系统清债，不直接改变流程，但能降低后续 UX 改动成本。

**工作量**：中（2 commit）。**用户感受改善**：低到中。**依赖**：无。**ROI 综合**：中。

### §B 实施建议捆绑

| Bundle | 包含方向 | 建议 commit 数 | token 预算 | ROI 判断 |
|---|---|---:|---:|---|
| Bundle 1：方向感急救 | D-1 + D-4 + D-6 | 3-4 | 30k-45k | 最高。最小改动改善“下一步在哪”、tier 入口、短剧过期文案。 |
| Bundle 2：失败可恢复 | D-2 + D-3 | 3-4 | 35k-55k | 高。把 iter039 P2-A/B 正式收掉，让 blocked/partial 从“能看到”变成“能处理”。 |
| Bundle 3：onboarding + responsive | D-5 + D-7 + D-8 | 5-7 | 60k-90k | 中。体验上限最高，但依赖更多；适合 §B 后半或 iter044。 |

