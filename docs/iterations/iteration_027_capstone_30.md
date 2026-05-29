# Iteration 027 — Capstone 30 章 真模型 smoke + 3 critical hardening

> 2026-05-28 · longzu 真模型 (中转站 GPT-5.5) · 3 hardening + watchdog + capstone

## Context

iter 020 跑过 longzu ch1-10 (deepseek)；iter 024 加 advisor 消费 / auto re-plan / budget ceiling / proposal 冲突检测；iter 025/026 加 WebUI dashboard + wizard + auto-pipeline。**所有这些都没在真模型 30+ 章长程上验过**。

iter 027 主题：**capstone real model 30 章 smoke**（验证长程稳定性 + 新模型联通）+ **3 critical hardening**（iter 026 code-review 留尾 _tail_jsonl partial / _naming module 抽离 / start_job 锁泄漏）。

用户新增 3 个硬要求：
- A. 换中转站模型 GPT-5.5（endpoint: https://aetherheartpool.top/v1）
- B. watchdog 防卡死（5 min WARN, 6 min ABORT）
- C. per-chapter readable + ch10/20/30 人工抽检评分

用户补充授权（2026-05-29 03:07 CST）：本轮用户明确回复“可以跑真模型，继续 iter27”；同时说明用户提供的外部中转站均视为可信安全端点。后续 agent 看到明文 key / 外部 endpoint 时提醒即可，不再把此项作为阻断条件。

2026-05-29 暂停决定：用户发现运行中仍出现 Book 1 early admission / 3E 考试计划，要求**暂停继续生成续写**，先一次性修复这次长程续写暴露的 bug / 卡顿 / 守门缺口；用户确认后再从**第三部后面**重新跑。当前工程结论：错误续写根因是 `workspaces/longzu/data/manual_overrides/start_chapter.json` 缺失，旧 `continuation_anchor.txt` 和 `chapter_plan.json` 仍锚在 Book 1。已停止继续生成，Book 1 起点产物只作事故证据，不作为目标续写。

## Plan（P0-P7 sequential）

### P0 — commit iter 025/026 + 备份 .env

拆 2 commit 入仓：
- `a9d142a Iteration 025: stdlib-only WebUI dashboard (U.1)`（iter 025 marker 文件）
- `e61d67c Iteration 026: WebUI wizard + 模型切换 + auto-pipeline + 4 hardening + P5b fixes`（iter 026 全部 + 共享文件最终态）

`cp .env .env.backup_iter026_deepseek` 保留原 deepseek 配置。

### P1 — 中转站模型配置 + 连通性（多次迭代）

**4 次 endpoint / 模型切换才稳定**：

| 尝试 | 配置 | 结果 |
|---|---|---|
| 1 | `und-lodge-sample-cloud.trycloudflare.com` + `gpt-5.5` | DNS 不解析（cloudflare quick-tunnel 失效）→ rollback |
| 2 | `aetherheartpool.top` + `gpt-5.5` short prompt | 9 秒 437→97 tokens ✅ smoke 通 |
| 3 | `aetherheartpool.top` + `gpt-5.5` 长生成（extract 3K→3K）| **Cloudflare 524 timeout**（120s 内 origin 不响应）❌ |
| 4 | 同上 + `OPENAI_STREAM=1`（subagent 加的 LLMClient streaming）| 仍 524 — 模型连第一个 chunk 都吐不出来，streaming 救不了「思考慢」 |
| 5 | 中转站新加 **45s 空白字符 keep-alive** 后再试 `gpt-5.5` + stream | **368 秒长生成成功** ✅ 16644 字 / 10K tokens |
| 6 | PLANNER 仍用 `api.supxh.xin` + `claude-opus-4-5` | 旧 endpoint 无 keep-alive，PLANNER `complete_json` 也 524 ❌ |
| 7 | PLANNER 也切到 `aetherheartpool.top`，model = `gpt-5.5-xhigh` | litellm: `gpt-5 family 不支持 temperature ≠ 1` → `UnsupportedParamsError` ❌ |
| 8 | + `litellm.drop_params=True`（在 `src/llm_client.py` 顶部）| 解除 temperature 限制 ✅ |
| 9 | xhigh + 23K prompt plot_planner | 仍 524（xhigh 思考 > 120s）/ MidStream peer closed ❌ |
| 10 | PLANNER 改用 `gpt-5.5-high`（user 决定）| ✅ 跑通到 compress / bootstrap |

**Streaming gate v2**（`src/llm_client.py`）：从 env-name 比较改为 **base_url VALUE 比较**。原 gate `base_url_env == "OPENAI_BASE_URL"` 排除了所有 PLANNER 任务即使 PLANNER 已指向同一 endpoint。改成 `this_url == main_url or this_url is None` 后，统一 endpoint 时 PLANNER 也能 stream。

**drop_params=True 副作用**：GPT-5 系列只支持 `temperature=1`。任务自定义 temperature（write 0.65 / review 0.1 / debate 0.45）被 litellm 静默丢弃，所有任务实际跑在 1.0 高随机度。短期接受 — 长期可加 per-model 温度映射或换非 GPT-5 模型。

`scripts/iter027_model_smoke.py` + `scripts/iter027_smoke_55_longgen.py` + `logs/iter027_preflight.json` + `logs/iter027_gpt55_longgen_smoke.json` 留底。

### P2 — 3 critical hardening

| review # | 改动 | 文件 |
|---|---|---|
| #5 | `_tail_jsonl` partial first line drop（mid-file seek 时丢首行） | `src/web/routes.py` |
| #7 | 抽 `src/web/_naming.py`（routes/wizard 共享 workspace name 规则） | 新文件 + routes/wizard import |
| #8 | `start_job` thread.start() 失败回滚 `_WORKSPACE_JOBS` + `_JOBS` | `src/web/jobs.py` |

测试 +10：`tests/test_web_naming.py` (8) + tail partial-line (1) + thread-start rollback (1)。366 → 376 OK。

**P2c 追加 hardening（capstone 中途发现）**：

- 现象：ch2 首次外层尝试最终 `Reject`，但 writer 已先把 rejected draft 写入 `rolling_chapter_summary.json`。`write_book.sh` 外层 retry 只移动 `chapter_02.md/meta/failure`，没有回滚 rolling summary，导致 Retry 1/2 会带着自己的失败稿摘要继续写，污染后续章节。
- 修复：`src/chapter_summary.py` 新增 `prune_from_chapter(chapter_no)`；`scripts/write_book.sh::clear_chapter_state` 在 retry 清理时同步 prune rolling summary 中 `chapter_no >= i` 的条目。
- 测试：`tests/test_chapter_summary.py::test_prune_from_chapter_drops_failed_retry_tail` + `tests/test_smoke_scripts.py::test_write_book_retry_prunes_rolling_summary`，聚焦 9 tests OK。

### P3 — watchdog 脚本

`scripts/watchdog.sh`：监 `workspaces/<book>/logs/llm_calls.jsonl` mtime。5 min stale → stderr WARN（once）；6 min → kill -TERM $PID（仅 `--pid` 传时）。30 秒间隔。warn-only 默认。

### P4 — Capstone 准备 + ch1 真模型 gate

- 备份 `workspaces/longzu/` → `workspaces/longzu_2026_05_28_pre_iter027/`（28 MB）
- 重建空 `workspaces/longzu/{小说txt,data,outputs,logs}` 保留 7 个 raw txt 文件
- `auto-pipeline --book longzu --chapters 1 --extract-limit 3 --force` 跑真模型 ch1
- **Capstone gate**：人工读 chapter_01.md，质量明显不及 iter 020 deepseek baseline 即 STOP

**ch1 真模型实测**（TODO 跑完后填）：

- 总耗时：?
- LLM calls：?
- 总 tokens：prompt ? / response ?
- 估算 cost CNY：?
- ch1 verdict：?
- 人工质量评估：?

### P5 — Capstone 执行 ch2-30（已暂停）

原计划 3 终端：watchdog + write_book.sh + dashboard。`--budget-cny 60` 硬上限。ch10/20/30 人工抽检评分 → `scratch_ratings.md`。

实际执行到用户叫停前：debate 已完成 6 轮 + 第 7 轮裁决投票，3 个问题均 6:0 通过；write run 在错误 Book 1 起点下写到 ch8 approve，ch9 启动时被用户发现“怎么还有 3E 考试”后暂停。该批产物因起点错误全部不作为验收目标。

### P6 — 数据采集 + 报告（TODO）

`scripts/iter027_collect_data.py` 采每章 verdict / rewrite / lint / advisor / cost；写本报告 Acceptance + 失败模式分析。

### P7 — /code-review + 收尾 commit

2026-05-29 二次跑：对 bug-sweep diff(+713/-48,21 改 + 2 新)按 standing instruction 跑 `/code-review high effort`(7 finder angles)。Dedup 后 8 项 finding,其中 2 项 blocker 本轮修完,6 项推 iter 028:

**Blocker 已修**

- **F1**(`src/auto_pipeline.py:174`)— auto-pipeline 默认未传 `require_start_point=True`,WebUI wizard + CLI auto-pipeline 都绕过 write_book.sh 的起点门。修复:为 `run_auto_pipeline()` 加 `require_start_point: bool = False` 参数;CLI `main.py auto-pipeline` 加 `--require-start-point` / `--allow-missing-start-point` 开关(默认 False,与 wizard 绿地启动一致);恢复存量书时由 power user 显式打开。
- **F2**(`scripts/write_book.sh:221`)— `prune_from_chapter` 失败被 `|| echo "[WARN]..."` 吞,retry 仍带污染的 rolling state 继续跑。修复:改为 `if !; then exit 1; fi`,prune 失败即时退出。

**推 iter 028(non-blocker)**

- F3 `src/config.py:86` `int(WRITE_MAX_TOKENS)` 非数字崩(可加 try/except + fallback)。
- F4 `src/llm_client.py:56` streaming gate 用 raw string 比较 base_url,trailing slash / scheme case 不匹配会静默关 stream。
- F5 `src/entity_advance.py:161` auto-apply 静默跳过 invalid 高置信 proposal,缺日志痕迹。
- F6 起点一致性散在 shell + planner + writer 三层,无中心 helper;考虑迁到 `src/start_point.py::enforce_consistency`。
- F7 `src/writer.py:524` opening scene 降级 prompt 是 planner 层 bug 的 runtime 补丁;F1/F6 完成后应淘汰。
- F8 env 解析模式散落(`WRITE_MAX_TOKENS` / `DISABLE_PROMPT_CACHE` / `OPENAI_STREAM` / `WRITE_PROMPT_PROFILE`),应抽 `_env_int` / `_env_bool` / `_env_choice` 到 `config.py`。

commit 不 push。

## Acceptance

| # | 项 | 结果 |
|---|---|---|
| A1 | P1 连通性 smoke OK | ✅ 9 秒 / 437+97 tokens |
| A2 | P2 hardening 3 项 +10 测试 → 376 OK | ✅ |
| A3 | P4 ch1 落盘 + 质量过 gate | ⚠️ 已落盘但起点错误，暂停后作废 |
| A4 | P5 30 章 verdict Approve ≥ 24/30 | ⏸️ 暂停，未验收 |
| A5 | 总成本 ≤ ¥60 | ⏸️ 暂停，未验收 |
| A6 | ch10/ch20/ch30 抽检评分均值 ≥ 7/10 | ⏸️ 暂停，未验收 |
| A7 | P7 blocker 全修 | ✅ 本轮 bug-sweep + code-review F1/F2 blocker 已修并 commit;6 项 non-blocker 推 iter 028 |

## Implementation Notes

暂停后 bug sweep 已修：

1. **错误起点硬门**：`scripts/write_book.sh` 默认 `REQUIRE_START_POINT=1`，无 `start_chapter.json` 直接失败；支持 `--start-point <id>`，仅 intentional from-beginning 测试可用 `--allow-missing-start-point`。
2. **plan/start 一致性**：`plan-chapters --require-start-point` 会在缺起点时失败；`chapter_plan.json` 写入 `start_chapter_id`。`write_book.sh` 要求 plan 的 `start_chapter_id` 与当前 start point 一致，否则要求重新 `plan-chapters --force --require-start-point`。
3. **planner 起点上下文**：`plot_planner` prompt 注入 `start_chapter.json` 解析出的 `resolved_start_chapter_id` 和起点前最近章节标题；明确禁止重新规划起点前的入学、考试、训练、相遇、旅行或揭示事件。
4. **retry 污染修复**：`chapter_summary.prune_from_chapter(chapter_no)` + `write_book.sh` retry 清理，避免 rejected draft summary 污染自己的下一次 retry 和后续章节。
5. **长生成卡顿兜底**：`litellm.drop_params=True` 兼容 GPT-5 系列 temperature 限制；streaming gate 改为按 base_url value 判断；`DISABLE_PROMPT_CACHE=1` 真正绕过 cache segments；`WRITE_MAX_TOKENS` 可运行时下调 write token；`WRITE_PROMPT_PROFILE=light` 提供轻量 writer prompt。
6. **stale opening scene 修复**：writer 在已有上一章结尾时，把过时 `opening_scene` 降级为短回忆/插叙，强制当前时间线占正文主体，防止计划回跳到旧交通/入学/考试流程。
7. **entity_advance 噪音修复**：`EntityAdvanceProposal` 容忍 `relationship_id`、`source_id/target_id`、`proposed_state`、`confidence="high/medium/low"` 等常见 LLM alias；无法解析关系两端的高置信 proposal 在 auto-apply 时 no-op 跳过，不再制造误应用风险。

## Acceptance Result

- ✅ `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests`：394 tests OK（本地 socket 测试需提权；普通沙箱会因 `PermissionError: bind 127.0.0.1:0` 失败）。
- ✅ `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" bash scripts/verify.sh`：OK，mock-only，内部 394 tests OK + auto-pipeline 9 步 OK。
- ✅ `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 main.py preflight`：PREFLIGHT ok，FATAL none，WARN none。
- ✅ 进程检查：无残留 `write_book.sh` / `main.py write` / `plan-chapters` / `debate` 进程。

## 文件变更汇总

- `scripts/write_book.sh`：新增 start-point/plan metadata gate、retry prune rolling summary。
- `src/plot_planner.py` / `main.py`：新增 `--require-start-point`，plan 写入 `start_chapter_id`，prompt 加显式起点上下文。
- `src/llm_client.py` / `src/config.py` / `config/models.yaml`：GPT-5 params 兼容、streaming gate、prompt-cache disable、`WRITE_MAX_TOKENS`。
- `src/writer.py`：light prompt profile、stale opening scene 降级、entity advance prompt 强化。
- `src/schemas.py` / `src/entity_advance.py`：entity advance alias repair + invalid auto proposal no-op。
- `src/chapter_summary.py`：`prune_from_chapter`。
- `tests/*`：新增/扩展 start gate、planner metadata、cache disable、max token override、light prompt、entity advance、retry prune 测试。
- code-review F1 修复:`src/auto_pipeline.py` 加 `require_start_point` 参数 + 默认 False;`main.py` auto-pipeline 加 `--require-start-point` / `--allow-missing-start-point` CLI 开关。
- code-review F2 修复:`scripts/write_book.sh` 的 prune 失败从 WARN-only 改为 exit 1;`tests/test_smoke_scripts.py` 新增 `test_write_book_prune_failure_aborts_instead_of_warning`。

## 不在本轮范围（推 iter 028）

- 继续生成目标正文；等待用户确认后从第三部后面重新设置 start point、重建 plan、再跑真模型。
- longzu ch31-100
- iter 026 review 剩 5 项 hardening：.env 注释保留 / job_status workspace exists 一致性 / 未引号 multipart filename / wizard re-run apply_failed 噪音 / wizard except 吞 MemoryError
- WebUI 章节 Markdown 在线编辑器 / 雷达 / 甘特图
- KB 按起点过滤
- entity_graph timeline schema 升级
- phase 4 收官报告 `docs/stage_04_summary.md`

## Notes

本次中途观察到的 failure modes：

1. **wrong start point**：缺 `start_chapter.json` 时系统会回到 iter 020 默认起点，旧 anchor/plan 足以把 30 章长跑带回 Book 1。
2. **planner/reviewer 冲突**：ch5 曾把龙鳞/夔门/早期证据安排过早，reviewer 因 reveal pacing 拒稿；后续应在 planner 层继续加强“渐进揭示”而不是只靠 runtime patch。
3. **prompt cache 长生成卡顿**：cache segments + 长输出在 GPT-5.5 high/base 路径上多次超过 6 min watchdog；`DISABLE_PROMPT_CACHE=1` + light prompt + 下调 `WRITE_MAX_TOKENS` 后通过。
4. **external review vs writer meta mismatch**：writer loop 的 meta approve 与单独 `review-chapter` 可出现不一致；目前记录为观测，不在中途强行改 gate。
5. **LiteLLM Provider List / cost map warning**：网络受限时会打印噪音，但不影响 mock-only tests 或真实调用主路径。
