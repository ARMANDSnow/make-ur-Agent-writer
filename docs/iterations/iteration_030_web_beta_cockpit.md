# Iteration 030 - Web Beta Writing Cockpit

## Context

iter 029 把生产写作入口收敛为 `write-readiness -> write-book`，但 WebUI 仍像工程调试页：首页只是 workspace 链接列表，进入后是平铺 panel，用户无法一眼判断哪本书能继续写、卡在哪里、下一步点什么。本轮目标是把本地单用户 Beta 做成可用的写作工作台，同时继续修 Web 入口的结构性问题。

## Plan

1. 首页改成作品总览，展示每个 workspace 的章节、起点、计划、草稿、评审、最近 job 与 readiness。
2. workspace 详情页改成“设置起点 -> 生成计划 -> 检查就绪 -> 继续写书 -> 查看产出”的主流程。
3. 新增只读 draft 列表/预览、起点 API、最近 job API，并把 plan/write 参数校验前移到 HTTP 层。
4. 保持 stdlib `http.server + string.Template + vanilla JS`，不引入前端框架，不跑真模型，不改 `.env`。
5. 更新 README SOP、handoff、iteration 索引和测试。

## Acceptance

- `/api/workspaces/overview` 对空/blocked/ready-ish workspace 返回稳定 JSON，单本坏 plan 不拖垮首页。
- Web 起点 API 能保存 chapter/volume 起点，非法 id 返回 400，保存后 readiness 刷新。
- Web `plan-chapters` 强制 `force=True` 与 `require_start_point=True`；缺起点返回 blocked，不标 failed。
- Web `write-book` 非法参数返回 400，合法参数完整透传 runner。
- 最近 job 从 `logs/web_jobs.jsonl` 恢复展示，刷新页面后仍可见。
- Draft API 只读、安全处理不存在章节，不读取 workspace 外路径。
- HTML 不再出现过时 `iter 026` 主文案；普通页面不展示 `draft-once-dev` 主入口。

## Implementation Notes

- `src/web/routes.py` 新增 overview/start-point/recent-jobs/drafts/draft API；overview 和 dashboard readiness 都走同一个 `_safe_readiness()`，将坏 plan/schema 错转换成 `blocked`。
- `/api/workspace/<name>/run` 对 `write-book` 与 `plan-chapters` 做服务端参数规范化；`plan-chapters` 无视客户端传入的 `force=False` / `require_start_point=False`，固定为生产语义。
- `src/web/jobs.py` 新增 `recent_jobs()`，并修复 job log 路径尊重 `paths.WORKSPACE_DIR`；`plan-chapters` 的缺起点/缺 outline 视为用户可修复 blocked。
- Web 模板改为首页书架 + workspace cockpit；第一屏只放起点、计划、就绪、继续写书和最近结果，status/cost/manifest/reviews/drafts 放到 tabs。
- CSS 从深色调试页改为浅色紧凑工作台；JS 按 `window.PAGE_KIND` 渲染首页或 workspace。

## Acceptance Result

- `node --check /private/tmp/iter030_dashboard.js` → OK（从 `src.web.static.JS_DASHBOARD` 导出到临时文件）。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m py_compile main.py src/*.py src/web/*.py tests/*.py` → OK。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m unittest tests.test_web_routes_get tests.test_web_jobs_dispatch` → 36 OK。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests` → 419 OK（普通沙箱 5 个 Web socket bind 测试 PermissionError；提权后 OK）。
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` → OK，419 tests OK + mock auto-pipeline OK（普通沙箱同样需 socket 权限）。
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` → PREFLIGHT ok；FATAL none；WARN none。
- Browser check: `main.py web --port 8766`（8765 已被旧服务占用）打开首页，overview 正常显示 7 个 workspace、ready/warn/blocked 汇总；进入 `iter029_beta_ok` 后，cockpit 首屏显示起点/plan/write/readiness，draft 只读预览可打开。

## 文件变更汇总

| File | Change |
|------|--------|
| `src/web/routes.py` | overview/start-point/recent-jobs/drafts API + run 参数校验 + readiness 容错 |
| `src/web/jobs.py` | persisted recent jobs + plan-chapters blocked semantics |
| `src/web/templates.py`, `src/web/static.py` | WebUI 从调试 dashboard 改为写作工作台 |
| `tests/test_web_routes_get.py`, `tests/test_web_jobs_dispatch.py` | Web API / job 参数 / UI regression coverage |
| `README.md`, `docs/AGENT_HANDOFF.md`, `docs/iterations/README.md` | SOP 与交接状态更新 |

## 不在本轮范围

- 不跑 `real_smoke.sh` / `debate_smoke.sh` / `write_smoke.sh`，不启动真模型长跑。
- 不实现完整在线编辑器、富文本 diff、权限、多用户、前端框架迁移。
- 不实现真正 `knowledge_for_start_point()` / KB 安全视图；本轮只展示相关 readiness/preflight 警告。
- 不删除旧产物；旧 draft/review 仍由 strict runner 与用户显式 `--force` 管理。

## Notes

- 迭代重点从“按钮能启动”推进到“用户知道为什么不能启动、下一步该做什么”。
- 后续优先级建议：真模型 capstone、KB 安全视图、entity timeline schema 升级、只读预览之后的人工编辑/复审入口。
