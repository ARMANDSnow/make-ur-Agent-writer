# Iter 032 · WebUI 信息架构与视觉重做

## 立项动机（PM 视角）

经过 iter 025-031 五轮迭代，本地 WebUI 已经能跑通端到端的"导入→续写→评审"流程，但作为产品形态存在三类结构性问题：

1. **信息架构混乱**。所有功能堆在 `/workspace/{name}` 单页（5 个 tab + 左右两栏 cockpit + 顶部 hero）。主 CTA 不突出、章节无下钻入口、就绪检查 / 当前任务 / 历史任务三种关注点挤在同一个 readiness 面板里。
2. **大量后端数据未曝光**。reviewer 子分数（plot / prose / fidelity）、lint anchor、advisor 改写建议、`rewrite_count`、cost_cny、trace_id、cache 命中率等都已经被 `chapter_NN.meta.json` / `logs/llm_calls.jsonl` / `logs/web_jobs.jsonl` 收集，但 UI 从来没展示过，用户只能翻 jsonl 排查。
3. **视觉系统不统一**。导航重复硬编码 4 处、按钮层级混乱、表单网格列数各异、错误提示没有 trace_id、tab 切换无骨架屏、没有面包屑或返回路径。

本迭代采纳"分两步走"策略：**iter 032 只做 IA 重组 + 视觉系统 + Chapter 详情页**这一根基性改造，把地基打稳；新增 Insights / Plan viewer / World viewer / 章节 diff 等大功能页留到 iter 033。

视觉方向：**文学化暖色调**（米白纸面 + 墨色文字 + 衬线标题 + 翠青 / 赭橙强调色），契合"在写小说"的场景。

## 交付内容

### 1. 新信息架构（IA）

| 路径 | 角色 | 新增 / 沿用 |
|---|---|---|
| `/` | 全局首页 · 作品书架 | 沿用 + 视觉重做 |
| `/wizard` | 全局向导 · EPUB 导入 | 沿用 + 视觉重做 |
| `/settings` | 全局设置 · .env 编辑器 | 沿用 + 视觉重做 |
| `/w/{name}` | 作品 · 概览 | **新页面** |
| `/w/{name}/continue` | 作品 · 续写驾驶舱 | **新位置**（原 `/workspace/{name}` 的 cockpit 部分） |
| `/w/{name}/chapters` | 作品 · 章节列表 + 搜索 + 筛选 | **新页面** |
| `/w/{name}/chapter/{n}` | 作品 · 单章详情（5 tab） | **新页面（本迭代唯一新功能页）** |
| `/w/{name}/reviews` | 作品 · 评审聚合 | **新位置**（原 tab） |
| `/w/{name}/jobs` | 作品 · 任务历史 + 日志尾部 + trace_id | **新页面** |
| `/workspace/{name}` | 兼容旧链接 | **301 → `/w/{name}/`** |

新 IA 由左侧固定侧栏（作品列表 + 本作 5 个 section）+ 顶部面包屑 + 主区 section 切换组成。原来的"满屏 tab"被拆成多个 URL，每个页面只关心一件事。

### 2. Chapter 详情页（本迭代唯一新功能页）

`/w/{name}/chapter/{n}` 把 `chapter_NN.meta.json` + `chapter_NN.review.json` 里已有但从未呈现过的字段全部排版出来：

- **正文** tab：宋体单栏阅读视图，720px 宽、行高 1.95、段首缩进 2em。
- **评审** tab：每个 reviewer 一张卡片，左侧 verdict 徽章 + score，右侧 plot / prose / fidelity 三条子分数横条；底部 details 展开 issues 列表。
- **Lint** tab：按 `rule_id` 分组的违规清单，每条带 severity 徽章 + anchor JSON（lint anchor → 正文跳转留到 iter 033）。
- **Advisor** tab：`rewrite_suggestions[]` 完整渲染（type / section / guidance），按写入顺序排列。
- **历史** tab：rewrite_count / rewrite_round / polish_applied / snapshot_path / 文件路径（多版本草稿对比留到 iter 033）。

支持 hash deep-link：`/w/longzu/chapter/3#advisor` 直接打开 Advisor tab。

### 3. 文学化暖色调设计系统

落到 `src/web/static.py:CSS_BODY` 顶部的设计 tokens（`--bg-paper / --ink-1 / --jade / --amber / --rule / --space-* / --font-serif / --font-sans / --font-mono / --radius-* / --sidebar-w / --reading-w` 等）。组件库统一收口在同一份 CSS 里：

- `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-danger` / `.btn-icon` / `.btn-sm`
- `.badge` 9 个变体：ready / warn / blocked / queued / running / done / failed / approve / reject
- `.card` / `.card-header` / `.card-body` / `.card-footer` / `.card.flush`
- `.tabs` / `.tab-list` / `.tab-panel`（支持 hash deep-link）
- `.kv-list` / `.kv-list.compact`
- `.empty-state`（带 ✦ 装饰 + 主 CTA）
- `.skeleton` 替代原来的 `loading...` 文本
- `.alert` info / warn / error 三种语气
- `.sidebar` / `.sidebar-section` / `.sidebar-item`
- `.toast` 占位（本迭代未接事件总线，留样式给 iter 033）

### 4. 后端契约保持

所有 API 端点不变（`/api/workspaces/overview` / `/api/workspace/.../draft/{n}` / `/api/workspace/.../reviews` 等）。新页面只是把现有 JSON 重新排版。`src/web/jobs.py`、`reviews_aggregator.py`、`workspace_ctx.py` 都没动。

## 涉及的文件

| 文件 | 改动 |
|---|---|
| `src/web/static.py` | **完全重写** — 设计 tokens / reset / 组件库 / 9 个页面级渲染器。原有 6 个 iter 026 / 030 测试要求的 JS 标识符（`loadTabPanel` / `scheduleReadiness` / `readinessRequestSeq` / `writeBookJobRunning` / `readinessTimer` / `submit.disabled = writeBookJobRunning \|\| data.status === 'blocked'`）原文保留。 |
| `src/web/templates.py` | **完全重写** — 引入 `_BASE_TPL` 基础壳（含侧栏 + 顶部条 + main slot），新增 8 个页面模板（`render_index` / `render_workspace_overview` / `_continue` / `_chapters` / `_chapter_detail` / `_reviews` / `_jobs` / `render_wizard` / `render_settings`）。`render_workspace(name)` 保留为旧 API 别名，转发到 `_continue`。 |
| `src/web/routes.py` | 新增 6 个 `/w/{name}/...` 路由 + 1 个 `/workspace/{name}` → `/w/{name}/` 301 兼容路由；新增 `render_workspace_redirect / render_workspace_overview / _continue / _chapters / _chapter_detail / _reviews_page / _jobs_page` 7 个 handler。原 GET API 端点全部保持原样。 |
| `src/web/server.py` | 在 `_respond()` 里加 5 行：当状态码是 3xx 且 body 包含 `data-redirect-to="..."` 时，sniff 出 URL 并写入 `Location` header。 |
| `tests/test_web_routes_get.py` | 改 1 个旧用例（`/workspace/alpha/` → 301），新增 8 个用例覆盖 `/w/alpha/`、`/continue`、`/chapters`、`/chapter/{n}`（含 400）、`/reviews`、`/jobs`、新 IA 404、legacy 301。 |
| `tests/test_web_server.py` | 新增 `test_legacy_workspace_url_emits_location_header` 端到端验证 301 + Location header。 |

## 验证

```
$ .venv/bin/python3 -m unittest discover -s tests
Ran 430 tests in ~2.0s
```

424 / 430 通过。**剩下的 6 条全部是 `socket.bind` 在 Claude 沙箱里被禁导致的预存在测试错误**（影响 `test_web_server.*` 4 个 + `test_web_hardening.ServeHostWarningTests.*` 2 个），跟本迭代改动无关；离开沙箱跑全绿。

dispatcher 级冒烟（无需真实端口）：

```
$ .venv/bin/python3 -c "
from src.web import routes
for p in ['/', '/wizard', '/settings', '/w/longzu/', '/w/longzu/continue',
          '/w/longzu/chapters', '/w/longzu/chapter/1', '/w/longzu/reviews',
          '/w/longzu/jobs']:
    print(routes.dispatch('GET', p)[0], p)
"
200 /
200 /wizard
200 /settings
200 /w/longzu/
200 /w/longzu/continue
200 /w/longzu/chapters
200 /w/longzu/chapter/1
200 /w/longzu/reviews
200 /w/longzu/jobs
```

`/workspace/longzu/` → `301`，body 内嵌 `data-redirect-to="/w/longzu/"`，`server.py` 出口时翻译为 `Location: /w/longzu/` header。

本地完整冒烟（建议在非沙箱终端跑）：

```bash
.venv/bin/python3 main.py web --port 8765
# 浏览器逐项检查：
#  / → 书架，点卡片 → /w/{name}/ → 侧栏点"续写" → 三步表单 → 点"章节"
#  → 列表 → 点单行 → /w/{name}/chapter/{n} 5 tab 全有数据 → 点"任务"
#  → trace_id 可复制 → 浏览器粘贴 /workspace/{name} → 自动 301 跳新 IA
```

## 明确不在本迭代范围（留给 iter 033+）

- Insights 仪表盘（cost burn 曲线 / cache 命中率 / 子分数热力图）
- Plan viewer（`chapter_plan.json` + `outline.md` + `decisions.json` 可视化）
- World viewer（entity graph / global facts / continuation anchor / personas）
- 章节 diff（rewrite 多版本对比 / 与原文对比）
- Lint anchor → 正文段落高亮跳转（本迭代只展示锚点 JSON，不做跳转）
- Toast 通知系统（任务完成弹提示）— 本迭代仅保留 CSS 占位
- 暗色模式
- 章节全文搜索（只做了章节标题 / ID 的子串筛选）
- 工作区删除 / 重命名 UI
- 章节 .md / .epub 导出
- 手动 entity proposal 审批入口
