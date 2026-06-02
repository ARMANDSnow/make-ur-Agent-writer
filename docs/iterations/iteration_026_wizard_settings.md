# Iteration 026 — WebUI wizard + 模型切换 + auto-pipeline + 4 hardening

> 2026-05-28 · mock-only · 0 LLM 成本 · stdlib-only

## Context

iter 025 收尾 code-review 暴露三件事，正好对应 iter 026 的入口：

1. **全 SOP 零人工干预跑不通**：`write_book.sh` 只覆盖写作循环；`run-all` 跳过 bootstrap-apply + plan-chapters；`tests/` 无从空 workspace 到 ch1 的真集成测试。iter 026 wizard 的本质就是把缺的 ~10 条 CLI 编排成一键流程。
2. **iter 025 留尾 4 个 hardening bug**：#3 `_tail_jsonl` OOM、#6 `list_workspaces` 不过滤 `__pycache__`、#7 `except Exception` 直接返回 `str(exc)`、#10 `--host 0.0.0.0` 无 warning。都跟 iter 026 即将动的模块同主题，一并修代价最低。
3. **iter 025 没污染续写模块**（git diff 确认纯加法），iter 026 可以放心继续扩 `src/web/`。

目标：
- (a) `auto-pipeline` 子命令：CLI 一行从 raw txt 跑到 ch1
- (b) wizard 7 步前端 + 后端（后端复用 auto-pipeline 函数，前端只 2 状态）
- (c) 模型切换 panel：.env 读 / 写 + key 屏蔽
- (d) 4 hardening bug 一并修

## Plan（P1 → P6 sequential）

### P2 · `src/auto_pipeline.py` + `auto-pipeline` 子命令

新建纯 business 函数 `run_auto_pipeline(...)` 串接 9 步：
normalize → split → extract → compress → bootstrap_all → apply 5 proposal → debate → plan-chapters → write。每步前调 `progress_cb(step_name, fraction)`。

main.py 注册 `auto-pipeline` 子命令；verify.sh 把 `run-all --chapters 1` 升级为 `auto-pipeline --chapters 1`（9 步真 e2e）。

`apply 5 proposal` 每个单独 try/except —— mock 模式下 style_examples 引用 `data/normalized_texts/mock.txt`（不存在），改成 per-proposal 失败不阻断后续步骤，failure 记录到 results。

### P1 · `src/web/jobs.py` + `do_POST/PUT` + POST 路由

- 模块级 `_JOBS: dict[job_id -> record]` + `_WORKSPACE_JOBS: dict[workspace -> job_id]`
- `start_job(workspace, step, params)` 起 daemon Thread，worker 内部 `use_workspace(workspace)` 跑 step
- 同 workspace 已有 running → 409，避免 entity_graph 竞争写
- step 白名单 dispatch 表（10 个 step，含 `auto-pipeline`）
- routes 加 POST `/api/workspace/<n>/run` + GET `/api/workspace/<n>/job/<job_id>`
- server.py 加 `do_POST` / `do_PUT`，body 64 MB 硬上限

### P3 · `src/web/wizard.py` + 2 状态前端

- POST `/api/wizard/start`：手写 multipart 解析（避免 3.13 deprecated `cgi.FieldStorage`），MIME 白名单 epub/txt，50 MB 上限
- 上传后调 `init_workspace` 建目录骨架 + `extract_epub`（如是 epub）或直接落 txt
- 立即 `start_job(workspace, step="auto-pipeline")` 起 worker
- 前端 JS（`JS_WIZARD`）只 2 状态：upload + polling，不需要 7 次 POST

### P4 · `src/web/settings.py`

- GET `/api/settings`：读项目根 `.env`，4 个白名单 key（`OPENAI_MODEL` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL_PROFILE`）。API key 屏蔽中段（`***` mask）
- PUT `/api/settings`：白名单 + 值字符过滤 + 原子写（`os.replace`）。返回 `{"restart_required": true}`
- 前端 banner 提示重启

### P5 · 4 hardening fix

| # | 改 | 文件 |
|---|---|---|
| #3 | `_tail_jsonl` 改 seek-from-end 块状反读（O(N) → O(1) memory） | `src/web/routes.py:131-188` |
| #6 | `list_workspaces` 加 sanity（要求 `data/` 或 `outputs/` 存在）→ `__pycache__` 等 dev dir 不再当成 workspace | `src/cli_workspace.py:34-54` |
| #7 | dispatch catch-all 改用 `trace_id` + server-side log，response body 只返回 `{"error":"internal server error","trace_id":...}` | `src/web/routes.py:283-300` |
| #10 | `serve()` 非 loopback host 打 stderr 多行 WARNING（列出无认证 + 敏感端点） | `src/web/server.py:60-94` |

### P6 · 测试 + 文档 + code-review

新增测试（329 → 363，+34，超过 plan 估的 +28）：
- `tests/test_auto_pipeline.py` (+5)
- `tests/test_web_jobs_dispatch.py` (+6)
- `tests/test_web_wizard_e2e.py` (+5)
- `tests/test_web_settings.py` (+5)
- `tests/test_web_hardening.py` (+8)
- `tests/test_web_routes_post.py` (+5)

## Acceptance

| # | 项 | 结果 |
|---|---|---|
| A1 | `auto-pipeline --chapters 1 --extract-limit 2 --force` mock 模式跑 9 步产 `chapter_01.md` | ✅ |
| A2 | `python3 main.py web --port 8765` → 浏览器 `/wizard` 上传 txt → 2 状态推进到 done → ch1 落盘 | ✅（urllib + dispatch 测试覆盖）|
| A3 | `/settings` GET 屏蔽 API key 中段；PUT 原子写 + 未列字段保留 | ✅ |
| A4 | `--host 0.0.0.0` 起服务时 stderr 出 WARNING（3 行 + 列敏感端点） | ✅ |
| A5 | `_tail_jsonl` 在 100K-line / 3MB 文件上 < 100 ms | ✅（实测 0 ms）|
| A6 | `list_workspaces` 过滤掉 `__pycache__` / empty dir | ✅ |
| A7 | dispatch 异常 body 不含 `str(exc)`，含 `trace_id` | ✅ |
| A8 | 363 个测试全绿（296 baseline + 33 iter 025 + 34 iter 026） | ✅ |
| A9 | `bash scripts/verify.sh` exit 0（含升级后的 `auto-pipeline` 9 步） | ✅ |
| A10 | iter 014-025 行为 byte-identical（纯加法 + `cli_workspace.list_workspaces` 仅收紧不破坏 schema） | ✅ |

## File Summary

**新建**:
- `src/auto_pipeline.py` (~155 行) — 9 步编排
- `src/web/jobs.py` (~240 行) — threading worker + step dispatch
- `src/web/wizard.py` (~190 行) — multipart + sanitize + start_job
- `src/web/settings.py` (~125 行) — .env read/write + key mask
- `tests/test_auto_pipeline.py` (+5)
- `tests/test_web_jobs_dispatch.py` (+6)
- `tests/test_web_wizard_e2e.py` (+5)
- `tests/test_web_settings.py` (+5)
- `tests/test_web_hardening.py` (+8)
- `tests/test_web_routes_post.py` (+5)
- `docs/iterations/iteration_026_wizard_settings.md`（本文档）

**改动**:
- `main.py` —— 注册 `auto-pipeline` 子命令 + handler
- `src/web/server.py` —— `do_POST` / `do_PUT` + body 读取 + 64 MB cap + host warning + fallback 500 body 固定（不再含 `str(exc)`）
- `src/web/routes.py` —— 扩 `_ROUTES`（POST/PUT/wizard/settings）+ dispatcher signature 加 body/headers + #3 `_tail_jsonl` seek-tail + #7 catch-all trace_id
- `src/web/templates.py` —— + `WIZARD_TPL` / `SETTINGS_TPL` + index 顶栏链接
- `src/web/static.py` —— + `JS_WIZARD` / `JS_SETTINGS` + progress-bar CSS
- `src/cli_workspace.py` —— #6 `list_workspaces` 加 `(data/ or outputs/)` sanity 检查
- `scripts/verify.sh` —— `run-all --chapters 1` → `auto-pipeline --chapters 1` + 同时 `py_compile` 加 `src/web/*.py`
- `README.md` —— SOP 表 U.2 ✅ + 新增 U.3（auto-pipeline）
- `docs/AGENT_HANDOFF.md` —— Phase 4 Status iter 026 段

## 不在本轮范围

- 章节 Markdown 在线编辑器 / 雷达图 / 甘特图（iter 020 plan P2/P3，留 iter 028+）
- capstone 真模型 30-100 章 smoke（留 iter 027）
- auth / login / token（127.0.0.1 单用户；`--host 0.0.0.0` 给 WARNING 不做认证）
- WebSocket / SSE / Docker / HTTPS
- 修改 iter 014-025 业务行为

## P5b — code-review 第一轮 4 blocker 修复（用户确认当 iter 内修）

iter 026 P6 末尾按 standing instruction 跑 `/code-review high effort`，3 angle agent 共回收 10 个 finding，按严重度修了前 4 个 blocker：

| # | bug | 修法 | 影响 |
|---|---|---|---|
| #1 | `workspace_ctx` RLock + 全 with-body 持锁导致 worker 跑 auto-pipeline 期间所有 dashboard read 端点冻结 | `src/paths.py` 加 `_THREAD_OVERRIDE = threading.local()` + `workspace_name()` 优先读 thread-local；`src/web/workspace_ctx.py` 完全重写去 lock，每线程独立 override | 用户最 visible 的修复：浏览 dashboard 时 wizard job 不再卡死 UI。test_does_not_block_other_threads 实测 < 50ms 完成（修前 ~500ms） |
| #2 | wizard `extract_epub` 异常无 rollback，半创建 workspace 加 409 forever，用户无 UI 路径恢复 | `wizard.start_upload` 上传段加 try/except (Exception) → `shutil.rmtree(target_root)` + 400 友好错误 + server-side traceback log | 损坏 epub 上传后同名重试立刻成功（test_corrupt_epub_rolls_back_workspace 覆盖） |
| #3 | `bootstrap_all` 只返回 5 个 proposal 漏 `source_excerpts`，wizard / auto-pipeline 路径下 iter 023 K=3 archetype excerpts 永远不可用 | `auto_bootstrap.bootstrap_all` 加 `"source_excerpts": bootstrap_source_excerpts(...)`；`test_init_book_bootstrap_all_returns_six_proposal_keys` 同步从 5 → 6 keys | iter 023 设计与实际行为对齐 |
| #4 | `auto_pipeline` apply 循环 `bare except Exception` 吞 PermissionError / KeyError 等系统级异常，root cause 被掩盖 | 收窄 `except (FileNotFoundError, ValueError)` —— `json.JSONDecodeError` 是 ValueError 子类已覆盖；PermissionError / OSError 等正常传播 | 真实 fs 权限问题不再被诊断成 "debate 失败"（test_apply_bootstrap_permission_error_propagates 覆盖） |

测试: 363 → **366**（plan 估 +28，实际 +37：6 P6 原测 + 1 #4 fix 测 + 1 #2 fix 测 + 1 #1 thread isolation 测 — 原 5 个 workspace_ctx 测试中 1 个等价替换）。

### P5b 二轮 code-review（增量）

修完 4 blocker 后再跑一次单 agent delta review 确认无回归：

- **MED 当场修**：`wizard.py` tmp_path leak —— write 失败时未赋值，外层 except cleanup 漏 tmp 文件。改成 NamedTemporaryFile `__enter__` 后立即 `tmp_path = Path(tmp.name)`，并加 finally 兜底 unlink。
- **LOW 推迟到 iter 027**：(a) 同 workspace 再次 wizard run 时所有 6 proposal 走 _skip_result → apply_failed 噪音；(b) `wizard.py` `except Exception` 吞 MemoryError —— 单用户本地工具影响小。

## Notes（执行提示）

1. **mock 模式 style_examples 失败是已知约束**：mock LLM 返回 `source_file: data/normalized_texts/mock.txt`（不存在），apply_bootstrap 抛 FileNotFoundError → auto_pipeline 记 `apply_failed` 状态后继续。真模式 LLM 看实际 normalized 文件名不触发。
2. **wizard 前端简化到 2 状态的关键**：编排完全在后端 `run_auto_pipeline`，前端只 upload + polling，避免了 plan 原本设计的"前端 7 步状态机"复杂度。任何前后端编排顺序漂移都是不可能的（同一个函数）。
3. **`use_workspace` 是 RLock + finally**：iter 025 fix #2 改的；iter 026 worker 长持锁不会 deadlock，同 workspace 内多请求串行（acceptable，因为业务本来就只 1 job）。
4. **code-review 是 standing instruction**：本 iter 末尾按用户 standing instruction 必跑 `/code-review high effort`。survive 的 finding 当场分类（blocker → iter 026 内修；其余 → 写进 iter 027 plan）。
