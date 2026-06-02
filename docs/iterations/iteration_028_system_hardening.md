# Iteration 028 - Systemic Hardening for Production Write Entry

## Context

iter 027 暴露了长程续写入口分叉问题：`write_book.sh`、WebUI raw `write`、`auto-pipeline`、旧 chapter meta / review 报告对"是否已完成"的判断不一致，导致 wrong-start、旧章节跳过、Reject 被当 done、真模型 smoke 易误跑、reviewer 能 parse 但语义坏时 fail-open。

本轮目标是把生产写作链路收敛成可恢复、可审计、fail-closed 的 mock-only 稳定入口，同时保留现有未提交改动，不跑真模型，不删除旧产物。

## Plan

1. 增加 start point / plan / draft / review 的运行上下文指纹，严格模式下旧 meta 不再算 approved。
2. 新增 Python `book_runner.run_write_book()`，让 Web 生产入口走 `write-book` 语义。
3. WebUI 去掉普通生产 raw `write` / generic `auto-pipeline`，绿地 onboarding 改名 `auto-pipeline-greenfield`。
4. reviewer / LLM JSON schema repair fail-closed：未知 verdict 不再默认为 Approve。
5. 增加真模型 smoke 确认门、env scrub、secret placeholder 清理、optional JSON graceful degrade。
6. 更新测试、README SOP、handoff 与本 iteration 记录。

## Acceptance

- Mock-only 单测全绿。
- `verify.sh` mock-only 全绿。
- `preflight` mock-only FATAL none。
- tracked 文件不再含 literal provider API key-like 片段。
- 真模型 smoke 无确认门时 exit 64。
- Web 生产入口必须使用 `write-book`，Reject / needs_human_review 不能映射为 success。

## Implementation Notes

- `src/start_point.py` 增加 `get_start_point_metadata()` / `start_point_fingerprint()`；`plot_planner` 写入 `start_point_fingerprint`、`plan_fingerprint`、每章 `chapter_plan_item_fingerprint`。
- `writer.write_chapters()` 在 meta / failure / review 中写 `run_context` 和 `draft_sha256`；polish 出错保留原 draft 并记录 `polish_error`。
- `chapter_status()` 增加 `validate_context`、`require_start_point`、`require_plan`、`require_external_review`；严格模式下 legacy / hash mismatch / stale review 都不 approved。
- 新增 `src/book_runner.py`：start/plan/preflight gate、严格 status、stale artifact archive、existing external review recheck、blocked/succeeded/failed snapshot。
- Web job status 扩为 `succeeded` / `blocked` / `failed` / `aborted` / `lost`；job 状态 append 到 workspace `logs/web_jobs.jsonl`；wizard 使用 `auto-pipeline-greenfield`。
- `AgentReview.verdict` 收紧为 `Literal["Approve", "Reject"]`；`_repair_agent_review_dict()` 只接受明确 alias，未知 verdict 变 Abstain；schema-invalid agent 尝试 simple fallback，否则 Abstain；全 Abstain 顶层 Reject。
- `LLMClient.complete_json()` 对 valid JSON but schema-invalid 增加 schema repair；streaming base_url 比较做 URL normalization；缺 `litellm` 时提供可 patch 的本地 stub，mock tests 不再依赖全局安装。
- `.gitignore` 覆盖 `.env.*` 且保留 `.env.example`；Web settings 白名单扩展 `PLANNER_*` / streaming / prompt profile，masked secret 不写回 `.env`。
- `verify.sh` / `tests/__init__.py` scrub planner/runtime env；`config` 增加 `_env_int/_env_bool/_env_choice`，非法 `WRITE_MAX_TOKENS` 回退默认并由 preflight WARN。
- optional loaders 对坏 JSON / 坏文件降级：entity graph `{}`、global facts `[]`、personas `None`、style example 单文件跳过。
- KB 起点过滤未宣称完成：本轮只在 preflight 对 start point + global_knowledge 同时存在给 WARN，真实 KB view / schema 升级留后续。

## Acceptance Result

- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 -m py_compile main.py src/*.py src/web/*.py tests/*.py` → OK
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock <bundled-python> -m unittest discover -s tests` → 404 OK（需本机 socket 权限；沙箱内 5 个 Web server bind 测试会 PermissionError）
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` → OK，404 tests OK + mock auto-pipeline OK
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 main.py preflight` → PREFLIGHT ok，FATAL none，WARN none

## 文件变更汇总

| File | Change |
|------|--------|
| `src/start_point.py` | start metadata + fingerprint |
| `src/plot_planner.py` | plan/item fingerprints |
| `src/chapter_status.py` | strict context / external review validation |
| `src/writer.py` | run_context / draft hash / polish_error persistence |
| `src/book_runner.py` | Python production write runner |
| `src/web/jobs.py`, `src/web/wizard.py`, `src/web/static.py`, `src/web/settings.py` | write-book入口、job状态、持久化、settings 白名单与 secret mask |
| `src/reviewer.py`, `src/schemas.py`, `src/llm_client.py` | fail-closed reviewer + schema repair + URL normalization |
| `src/config.py`, `src/preflight.py`, `src/utils.py`, optional loaders | env helper、graceful degrade、preflight next steps/WARN |
| `scripts/*.sh`, `.gitignore` | smoke 确认门、verify scrub、write_book shell 修复、env ignore |
| `tests/*` | context/status/reviewer/LLM/Web/safety regression coverage |
| `README.md`, `README_EN.md`, docs | SOP / key placeholder / iteration docs |

## 不在本轮范围

- 不跑真模型，不改 `.env`，不 push。
- 不删除 iter 027 wrong-start 旧产物；严格 runner 会归档 stale artifact。
- KB 按起点过滤只落 WARN / 后续接口意识，未完成真实安全 KB view。
- entity_graph timeline schema 仍待升级；缺 chapter marker 的精细 preflight 规则留后续。

## Notes

- 本轮按用户要求使用 3 个 subagent 做只读审查：Web/runner、reviewer/LLM、safety/env。主线程集成并修复。
- 当前生产长跑建议入口：`python3 main.py --book <name> write-book --chapters N` 或 Web step `write-book`。绿地 onboarding 仍走 `auto-pipeline-greenfield`。
- 继续 longzu 真模型前仍需用户明确授权；真 smoke 脚本现在需要 `CONFIRM_REAL_MODEL_SMOKE=可以跑了` 或 `--confirm-real-smoke`。
