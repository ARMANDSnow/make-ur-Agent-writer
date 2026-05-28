# Iteration 025 — WebUI U.1 dashboard（只读）

## Context

SOP 表 phase 4 仍剩两个 ❌：`U.1 WebUI dashboard` 与 `U.2 模型切换 panel + onboarding wizard`。iter 020 plan（`/Users/dingyuxuan/.claude/plans/dapper-conjuring-mochi.md` 行 135-305）原本把 WebUI 拆成 iter 021-024 四段，实际 iter 021-024 都拿去做算法稳定性，UI 一直没动。

日常使用 CLI 摩擦仍大：查 status / cost / chapter / review 都得 `python3 main.py --book X <verb>`，多 workspace 切换繁琐。

iter 025 落 **只读 dashboard**：浏览器 `http://127.0.0.1:8765/` 看 workspace 列表 + 4 panel（status / cost / manifest / reviews 全量）。所有数据来源只读，**0 副作用、0 LLM 调用、0 新依赖**。POST/PUT（wizard、settings、step dispatch）整段推到 iter 026。

iter 020 plan 中的 P2 章节 Markdown 编辑器、P3 雷达图/甘特图可视化均跳过，留待 iter 028+。

## Plan

| P | 任务 | 文件 |
|---|------|------|
| P1 | `src/web/` 骨架 + 路由分发 | `src/web/__init__.py`, `server.py`, `routes.py`；`main.py` 注册 `web` 子命令 |
| P2 | 只读 5 GET API + workspace_ctx + reviews_aggregator | `src/web/workspace_ctx.py`, `reviews_aggregator.py`；5 个纯函数 handler |
| P3 | HTML 渲染层（templates + 内嵌 CSS/JS）| `src/web/templates.py`, `static.py` |
| P4 | 测试 +26 → 322 + docs + verify | `tests/test_web_*.py`（4 个）+ 本文 + SOP / HANDOFF 同步 |

## 路由表（GET only）

| Method | Path | Handler | 返回 |
|---|---|---|---|
| GET | `/` | `render_index` | HTML workspace 列表 |
| GET | `/workspace/<name>/` | `render_workspace` | HTML 4 panel skeleton |
| GET | `/static/app.css` | `render_static_css` | text/css |
| GET | `/static/app.js` | `render_static_js` | application/javascript |
| GET | `/api/workspaces` | `api_workspaces` | `{"workspaces": [...]}` |
| GET | `/api/workspace/<name>/status` | `api_workspace_status` | `collect_status()` 输出 |
| GET | `/api/workspace/<name>/cost` | `api_workspace_cost` | `estimate_cost()` 输出 |
| GET | `/api/workspace/<name>/manifest` | `api_workspace_manifest` | `{"chapters": [...]}` 来自 `data/chapter_manifest.json` |
| GET | `/api/workspace/<name>/reviews` | `api_workspace_reviews` | 全量 reviews + stats（见下）|
| GET | `/api/workspace/<name>/logs/tail?n=N` | `api_workspace_logs_tail` | `{"lines": [...]}` per-workspace `logs/llm_calls.jsonl` 尾部 |

## 关键设计决定

1. **iter 025 全程 GET，0 副作用**：不接受 POST/PUT/DELETE。任何写操作（wizard、step 触发、.env 编辑）整段推到 iter 026。让 iter 025 测试不需要 mock LLM 调用 + 没有并发资源竞争问题。
2. **handler 纯函数**：所有 5 个 API handler 是 `(name) -> (status, content_type, body_bytes)` 纯函数，不依赖 HTTP server 实例 — 可直接在 unittest 里 `routes.dispatch(method, path)` 调用。`server.py` 只是 `BaseHTTPRequestHandler` ↔ `dispatch` 的 wire 转换。
3. **workspace 切换上下文管理器**：`with use_workspace(name)` 临时设 `os.environ["WORKSPACE_NAME"]`，`finally` 还原。process-wide `threading.Lock()` 守住 env 切换，避免 `ThreadingHTTPServer` 并发请求踩 env。
4. **reviews 全量 + 前端默认折叠**：API 返回完整 `agent_reviews[*]`（含 `issues` / `suggestions` / `comparison_checklist` / `sub_scores`）+ top-level `rewrite_suggestions`（iter 024 advisor 字段名）+ `lint_issues`。HTML 默认 collapsed，点行展开。10 章约 60KB；30 章 100-200KB，浏览器可接受。
5. **stdlib-only 硬约束**：`http.server.ThreadingHTTPServer` + `string.Template` + 内嵌 CSS/JS 字符串。`requirements.txt` 未动。HTML 不引外部 JS/CSS（CDN 都不行，离线可用）。
6. **chapter_NN.meta.json 严格 2 位数字匹配**：`re.compile(r"^chapter_(\d{2})\.meta\.json$")` 排除 `chapter_01_iter023_demo.meta.json` / `chapter_01.meta_backup.json` 等变体，dashboard 只显示正式章节。
7. **JSON 序列化用 `default=str`**：`collect_status()` / `estimate_cost()` 返回的 dict 嵌 `pathlib.Path`，统一 fallback 转字符串，避免每个 handler post-process。

## reviews API 形态

```json
{
  "chapters": [
    {
      "chapter": 1,
      "verdict": "Approve",
      "rewrite_count": 2,
      "rewrite_round": 1,
      "chinese_char_count": 4123,
      "needs_human_review": false,
      "polish_applied": true,
      "lint_issues": [...],
      "agent_reviews": [
        {
          "agent_name": "PlotMaster",
          "verdict": "Approve",
          "score": 7,
          "sub_scores": {"plot": 7, "prose": 6, "fidelity": 8},
          "issues": [...],
          "suggestions": [...],
          "comparison_checklist": [...]
        }
      ],
      "rewrite_suggestions": [
        {"section": "开场段落", "type": "rewrite", "guidance": "...", "_advisor": "改写顾问"}
      ]
    }
  ],
  "stats": {
    "total": 10,
    "accepted": 9,
    "rewrite_max": 2,
    "needs_human_review": 1,
    "advisor_suggestions_total": 0
  }
}
```

## Acceptance Result

| # | 项 | 实测 |
|---|---|---|
| A1 | `python3 main.py web` 起 server 不 crash | ✅ `[web] serving on http://127.0.0.1:8765` |
| A2 | 8 条 GET 路由全部正确状态码 + content-type | ✅ 13 路径 urllib 实测全绿（`/`, `/workspace/<n>/`, `/api/*`, `/static/*`, 404 路径）|
| A3 | longzu 4 panel API 返回非空 + 字段完整 | ✅ `/api/workspace/longzu/reviews` 聚合 10 章；first chapter 含 `agent_reviews` × 8、`rewrite_suggestions`、`lint_issues` |
| A4 | reviews stats 正确 | ✅ longzu: total=10, accepted=9, rewrite_max=2, needs_human_review=1, advisor=0（正式章节没 advisor，符合 iter 024 demo-only 状态）|
| A5 | demo 文件被严格过滤 | ✅ `chapter_01_iter024_advisor_demo.meta.json` / `chapter_01.meta_backup.json` 不进结果 |
| A6 | 测试增量 +26 → 322 全绿 | ✅ `unittest discover -s tests` 322 OK |
| A7 | `bash scripts/verify.sh` 通过 | ✅ Report snapshots OK + check-manifest OK + Cost Estimate 输出 |
| A8 | 0 新依赖 | ✅ `requirements.txt` 未动 |
| A9 | 向后兼容：iter 014-024 行为 byte-identical | ✅ verify.sh + 全部 296 baseline 测试不变 |

## File Summary

**新建（10 个）**：
- `src/web/__init__.py` —— 模块文档
- `src/web/server.py` —— `serve(host, port)` + `WebHandler(BaseHTTPRequestHandler)`
- `src/web/routes.py` —— 10 条路由 + 6 个纯 handler + dispatcher
- `src/web/workspace_ctx.py` —— `use_workspace` 上下文管理器
- `src/web/reviews_aggregator.py` —— `aggregate_reviews(drafts_dir)` + 严格 2 位数字 glob + stats
- `src/web/templates.py` —— `render_index` / `render_workspace`（`string.Template`）
- `src/web/static.py` —— `CSS_BODY` + `JS_DASHBOARD` 字符串常量
- `tests/test_web_routes_get.py` —— 15 个 GET 路由测试（happy + 404 + 400 + 静态资源）
- `tests/test_web_reviews_aggregator.py` —— 6 个聚合测试（demo 过滤 / 全字段保留 / stats）
- `tests/test_web_workspace_ctx.py` —— 3 个 ctx 测试（设置-还原 / 异常路径 / None 清除）
- `tests/test_web_server.py` —— 3 个 server 集成测试（free-port bind / GET / 404）
- 本文档

**改动**：
- `main.py` —— 注册 `web` 子命令（`--host 127.0.0.1 --port 8765`）+ dispatch 调 `src.web.server.serve`
- `README.md` —— SOP U.1 改 ✅；顶部加 "Run the dashboard" 段
- `docs/AGENT_HANDOFF.md` —— Phase 4 Status iter 025 段
- `docs/iterations/README.md` —— +1 行索引

## 不在本轮范围

iter 020 plan 提到、本 iter **不做**：

- 所有 POST/PUT 端点（wizard、step dispatch、settings PUT）→ iter 026
- threading worker / job 状态管理 → iter 026
- onboarding wizard 7 步前端 + 后端 → iter 026
- `.env` 编辑面板（模型切换）→ iter 026
- 上传 epub multipart 解析 → iter 026
- 章节 Markdown 在线编辑器（iter 020 plan P2）→ iter 028+
- 雷达图 / 甘特图 / chart.js（iter 020 plan P3）→ iter 028+
- capstone 真模型 30-100 章 smoke → iter 027+
- auth / login / token / WebSocket / Docker / HTTPS → 永远不做（单用户本地工具定位）

## Notes（给 iter 026 设计师）

1. **`web` 子命令已是纯加法**：iter 026 在 `src/web/server.py` 加 `do_POST` / `do_PUT`、扩 `_ROUTES`、新加 `jobs.py` / `wizard.py` / `settings.py` 即可。无需改 iter 025 的 GET handler。
2. **JSON `default=str` 是个口子**：embeddings / np.ndarray 之类的非 str 值也会被 silently 转成 repr。如果将来 reviews payload 体积爆了，再考虑 stream / cursor，而不是收缩字段。
3. **handler 纯函数模式可直接复用**：iter 026 的 POST handler 也写成 `(name, body_bytes) -> (status, ct, body)` 纯函数，方便 unittest 不起 server 直接 call。
4. **`use_workspace` lock 已经够 iter 026**：threading worker 持有 lock 跑整个 job 也行，因为 **同一 workspace 同时只跑 1 job**（409 规则），实际不会自锁。
5. **`api_workspace_logs_tail` 已支持 `?n=N`**：iter 026 job polling 可以复用，无需另外造轮子。
