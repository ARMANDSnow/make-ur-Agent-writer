# Iteration 074 - 章节版本 diff（读者/编辑向质量复核工具）

## Context

截至 iter 073（2026-06-25，1369 tests OK / venv），工程主链路 Stage 1-18 全绿、P0/P1 codex findings 全收口，2026-06-26 真模型前置排查结论 STRUCTURE GO。用户定的后续方向（计划稿 `~/.claude/plans/logical-snuggling-gray.md`）是先交付主线读者/编辑向产品功能，再硬化 capstone 过夜可靠性，最后授权真模型 capstone 实跑（iter 074→077 路线图）。

本轮（iter 074）是路线图第一步：**章节版本 diff**。选它打头因为基础设施 ~70% 现成——章节详情页已有 `正文|编辑|评审|Lint|Advisor|历史` tab 结构与 `#tab-diff` 骨架，`static.py:4297` 还留着占位文案「多版本草稿对比（diff）将在后续版本开放」；快照归档（`book_runner.py:786-805` `_archive_chapter_artifacts` → `outputs/drafts/snapshots/stale_chapter_<nn>_<ts>/`）、编辑追踪字段（`edited/edited_at/draft_sha256/rewrite_count`）、`difflib.unified_diff`（已在 `cli_apply_bootstrap.py:167`/`entity_advance.py:226`/`observability.py:239` 使用）都已存在。等于「填坑」而非从零，纯 mock、风险最低。草稿版本对比直接服务长程续写的质量复核，与用户对 capstone 产出质量的关注同源。

**Aeloon 深色模式本轮不做**（用户确认）：它压在 sync 边界——`static.py`/`templates.py` 正是上次同步（PR #541）里为保留 Aeloon vendored 深色模式而 auto-merge + 人工处理的两个最敏感文件；本仓库再往同区域加深色模式会引起三方 diff 冲突/深色块重复注入。故拆为独立跨仓库协调任务（见「不在本轮范围」）。本轮 Aeloon 侧只提交无渲染影响的文档/工具 drift。

## Plan

**前置（工作树归位，不碰 sync 边界）**
- 提交无渲染影响的 drift：`scripts/aeloon_sync_check.sh`（同步工具，只存在于本仓库）+ `docs/AELOON_INTEGRATION.md` + `aeloon超前部分实现指南/深色模式实现指南.md`（均为文档/工具，不改任何 CSS/模板）。

**主任务：章节 diff（后端）**
- 新增 `GET /api/workspace/<name>/chapter/<n>/versions` — glob `snapshots/stale_chapter_<n>_*/` + 当前草稿，返回各版本 `{ts, rewrite_count, verdict, edited_at, path}` 列表（无快照时 graceful 返回仅当前草稿）。
- 新增 `GET /api/workspace/<name>/chapter-diff/<n>?v1=<ts|current>&v2=<ts|current>` — 载入两版本文本，`difflib.unified_diff(a.splitlines(keepends=True), b.splitlines(keepends=True), n=3)`，返回 `{versions:[...], diff_lines:[...]}`。
- 路由登记进 `_ROUTES`；复用现有 workspace name 校验 + 路径穿越守卫（`v1/v2` 只接受 `current` 或 glob 命中的时间戳目录名，拒绝任意路径）。
- diff 逻辑可抽到新文件 `src/web/chapter_diff.py`（~130 LOC）便于单测隔离。

**主任务：章节 diff（前端）**
- 填充 `#tab-diff`（替换 `static.py:4297` 占位文案）：版本选择器（对比目标 vs 当前草稿）+ unified diff 渲染（`.diff-line context/added/removed` 高亮）。
- 复用现有 `fetchJson/wsUrl` 与 tab 切换框架（`static.py:4064-4299`）。

**可选顺带**：批量 i18n 就近清一部分（如涉及 diff/版本文案），如做需在本文件如实标注范围（铁律⑦）。

## Acceptance

- 新增单测：versions 列举（含无快照 graceful / 坏 meta 降级）、diff 计算（增/删/上下文行）、非法 `v1/v2` 参数 fail-closed（拒路径穿越）、mock 裸仓库不报错（铁律④）。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 -m unittest discover -s tests` 全绿（≥1369 + 新增）。
- `bash scripts/verify.sh`；`python3 main.py preflight`。
- Web 端到端（preview 工具，mock）：造 1 章 + 触发一次 retry 生成快照 → 章节详情页 diff tab 选版本对比，截图为证。
- 收官 `/code-review high` + `/security-review`（重点：diff 端点文件读取的路径穿越校验）。结果回填本段/Acceptance Result（由 `/iter-finish 074`）。

## Implementation Notes

- **纯函数后端 `src/web/chapter_diff.py`**（易单测、无 HTTP/workspace 依赖）：
  - `list_chapter_versions(drafts_dir, chapter_no)` — 当前草稿（`current`）在前，snapshots 按时间戳 newest→oldest；无 snapshots 目录 / 坏 meta / 缺 md graceful 降级（裸仓库不报错，铁律④）。
  - `resolve_version_text(...)` — **路径穿越 fail-closed by construction**：version_id 只接受 `current` 或 `\d{8}_\d{6}`（`_STAMP_RE`），任何 `../`/绝对路径不匹配即返回 None；外加 `resolve().relative_to(<drafts>/snapshots)` 二次守卫（defense-in-depth）。
  - `compute_diff(...)` — `difflib.unified_diff(keepends, n=3)`，输出按前缀分类为 `meta/hunk/add/del/ctx` 供前端上色；`identical` = 无差异。
- **两个 GET handler + 路由**（`routes.py`）：`/chapter/<n>/versions` 与 `/chapter/<n>/diff?v1=&v2=`。handler 层再加**第三重闸**——v1/v2 必须落在 `list_chapter_versions` 枚举出的 `valid_ids` 集合，未知 id（含穿越串）在触盘前即 400。query 参数走既有 `_query` inline 模式（对齐 `variant`）；v2 缺省 `current`。
- **前端**（`static.py`）：替换 4297 占位文案为「多版本对比」面板（版本选择器 + `对比` 按钮 + `#diff-output`）；`loadChapterDiffVersions/runChapterDiff` 默认「最新快照 → 当前草稿」自动对比，版本 <2 时隐藏控件给中性文案。diff CSS 全用现有 token（`--jade-soft` add / `--sienna-soft` del / `--bg-sunken` hunk）加在 advisor-item 之后，暗色天然兼容。
- **复用未重造**：`_archive_chapter_artifacts` 快照布局、`difflib.unified_diff`、meta 编辑追踪字段、`fetchJson/wsUrl/escapeHtml/renderErrorCard/bindHashTabs`。
- **偏差**：Aeloon 深色模式按用户决策未做（sync 边界冲突，见「不在本轮范围」）；仅提交无渲染影响的 Aeloon doc/sync 工具 drift。未做批量 i18n（本轮无顺带触点）。

## Acceptance Result

- **单测**：新增 `tests/test_web_chapter_diff.py` 13 例（module 6 + route 7，含版本枚举/排序、无快照 graceful、坏 meta 降级、畸形快照目录忽略、路径穿越 fail-closed、diff identical/add/del、未知 version id 400、缺省 v2、坏章号 400）。全量 `.venv` `unittest discover` **1385 tests OK**（394s，含本轮 +13）。
- **verify.sh**：系统 python 下 `FAILED (errors=3)` 为**既有环境问题**（`test_book_runner`/`test_book_runner_retry_progress` 缺 pydantic、`test_estimate_branch_when_tiktoken_unavailable` 缺 tiktoken），与本轮 `chapter_diff/routes/static` 改动无关（三者均不 import pydantic/tiktoken）。`preflight` 正常。
- **实时 HTTP 端到端**（mock web :8765，只读现有 `tianlong` ch4）：`/versions` 返回 current(Approve)+3 Reject 快照 newest-first；`/diff?v1=<stamp>&v2=current` 返回分类 diff_lines；`/diff?v1=../../../etc/passwd` → **400 `unknown version id`**（真 HTTP 路径 fail-closed 验证）。
- **浏览器视觉**（preview 工具截图）：章节详情页「历史」tab「多版本对比」——版本选择器 4 版本带 verdict、默认最新快照→当前、diff 视图红/绿高亮 155 行（151 add/1 del）、等宽渲染。
- **代码审查（铁律⑨，2 独立视角 subagent 并行 + 安全自查）**：
  - **后端（正确性 + 安全）**：无安全漏洞、无崩溃路径、无路由冲突、无重复。路径穿越三重 fail-closed 确认（dispatch `unquote` 后 `\d+` 章号正则不匹配 `..` / handler `valid_ids` 集合闸 / `resolve_version_text` `_STAMP_RE` 锚定 + `resolve().relative_to(snapshots)` 抗符号链接）；坏 meta → `read_json_optional` 降级 `{}` 不崩；`**result` 无键冲突。仅「风格性耦合」观察（`_format_stamp` 定宽切片依赖正则锚定；`compute_diff(context=)` 未从端点透传），均不需改。
  - **前端（XSS + 复用）**：无 XSS——option 的 `v.id/v.label/v.verdict` 与 diff 行的 `ln.type/ln.text`（模型/用户 prose）全部 `escapeHtml`；后端 `ln.type` 本就限定枚举（双重保险）。默认选择器、`<2 版本`分支、`v1===v2` 与 `identical` 守卫、null 守卫均正确；重渲染用 `onclick=` 赋值（非 `addEventListener`）无监听器堆积/泄漏。
  - **安全自查（铁律①）**：`chapter_diff.py` 与新 handler diff 内 `grep sk-|.env|api_key|secret|token` 零命中。
  - **已接受 LOW 残留（未改，scope 收敛铁律⑦）**：① fetch 在途时若 `renderChapterDetail` 重渲染，旧回调写入已脱离的 DOM 节点——不抛错、不污染在用 UI，仅浪费；② history tab 未打开也会随每次 render 预取 `/versions`+`/diff`（延续本文件「eager 渲染各 tab」惯例）。两条均为可选效率优化，非正确性缺陷；若未来 save→review 高频往返感到冗余，可加 generation token 或 tab-active 懒加载。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/web/chapter_diff.py` | 新增：纯函数模块（版本枚举 + 路径穿越 fail-closed 解析 + unified diff 分类） |
| `src/web/routes.py` | 新增 2 handler（`api_workspace_chapter_versions/_diff`）+ 2 路由登记 + import `chapter_diff` |
| `src/web/static.py` | history tab 填充多版本 diff UI（替换占位）+ `loadChapterDiffVersions/runChapterDiff` + diff CSS |
| `tests/test_web_chapter_diff.py` | 新增：13 例 module + route 契约测试 |
| `docs/iterations/iteration_074_chapter_version_diff.md` | 本迭代文档 |
| `docs/iterations/README.md` | 索引第 86 行 |
| `docs/AELOON_INTEGRATION.md` / `aeloon超前部分实现指南/深色模式实现指南.md` / `scripts/aeloon_sync_check.sh` | 归位提交既有未入库 drift（doc/工具，无渲染影响） |

## 不在本轮范围

- **Aeloon 深色模式对齐**——压在 sync 边界，必须作为独立跨仓库协调任务：先核对 Aeloon `dev/ui` vendored 拷贝当前深色实现 → 本仓库改动字节级一致 → 落地后立即跑 `aeloon_sync_check.sh` 确认判 ✅/干净 auto-merge。待用户择期。
- **全文搜索**（iter 075）、**长跑可靠性硬化**（iter 076）、**真模型 capstone 实跑**（iter 077，需用户授权）。
- drama 站③④、AI 绘画 client、char-level diff、diff 缓存等——按需后置。

## Notes

- **教训**：功能选型对了——`#tab-diff` 骨架 + 占位文案 + 快照归档 + `difflib` + edit 追踪字段让这轮是「填坑」，后端纯函数 + 三重路径穿越闸让审查零真问题。用现有 `tianlong`/`longzu` 带快照的真实章节做**只读** e2e，避免造数据、也避免碰 `data/outputs`。
- **路线图**：本轮是 iter074-077 路线图（计划稿 `~/.claude/plans/logical-snuggling-gray.md`）第一步。下一步 **iter 075 全文搜索**（`src/search.py` 内存扫描 + 复用 `chapter_splitter.load_manifest/chapter_text`）。
- **capstone 前置**：**iter 076 长跑可靠性硬化**是用户「过夜不跑废」诉求的正解（面板拒稿不 halt 整书 / 每章预算预留 / 每阶段超时 / 心跳 / crash 自恢复），必须在 **iter 077 真模型 capstone 实跑**（10-20 章，需用户授权）之前完成。
- **Aeloon 深色模式**仍挂 backlog（sync 边界冲突，需跨仓库字节级对齐后跑 `aeloon_sync_check.sh` 验 ✅）。
- **后续候选（本功能延伸）**：char-level diff（当前行级）/ diff 结果缓存 / 版本选择器懒加载（见 LOW 残留②）/ 把 diff 面板复用到大纲·KB 版本对比。
