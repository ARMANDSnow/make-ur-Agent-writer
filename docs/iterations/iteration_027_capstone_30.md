# Iteration 027 — Capstone 30 章 真模型 smoke + 3 critical hardening

> 2026-05-28 · longzu 真模型 (中转站 GPT-5.5) · 3 hardening + watchdog + capstone

## Context

iter 020 跑过 longzu ch1-10 (deepseek)；iter 024 加 advisor 消费 / auto re-plan / budget ceiling / proposal 冲突检测；iter 025/026 加 WebUI dashboard + wizard + auto-pipeline。**所有这些都没在真模型 30+ 章长程上验过**。

iter 027 主题：**capstone real model 30 章 smoke**（验证长程稳定性 + 新模型联通）+ **3 critical hardening**（iter 026 code-review 留尾 _tail_jsonl partial / _naming module 抽离 / start_job 锁泄漏）。

用户新增 3 个硬要求：
- A. 换中转站模型 GPT-5.5（endpoint: https://aetherheartpool.top/v1）
- B. watchdog 防卡死（5 min WARN, 6 min ABORT）
- C. per-chapter readable + ch10/20/30 人工抽检评分

## Plan（P0-P7 sequential）

### P0 — commit iter 025/026 + 备份 .env

拆 2 commit 入仓：
- `a9d142a Iteration 025: stdlib-only WebUI dashboard (U.1)`（iter 025 marker 文件）
- `e61d67c Iteration 026: WebUI wizard + 模型切换 + auto-pipeline + 4 hardening + P5b fixes`（iter 026 全部 + 共享文件最终态）

`cp .env .env.backup_iter026_deepseek` 保留原 deepseek 配置。

### P1 — 中转站模型配置 + 连通性

第一次 endpoint `und-lodge-sample-cloud.trycloudflare.com` DNS 都不解析（cloudflare 临时 tunnel 失效）→ rollback `.env` → 用户提供新 endpoint `aetherheartpool.top` → smoke 通过：
- model `openai/gpt-5.5`
- 9.03 秒 round-trip · 437 prompt + 97 response tokens · 35 字回复

`scripts/iter027_model_smoke.py` + `logs/iter027_preflight.json` 留底。

### P2 — 3 critical hardening

| review # | 改动 | 文件 |
|---|---|---|
| #5 | `_tail_jsonl` partial first line drop（mid-file seek 时丢首行） | `src/web/routes.py` |
| #7 | 抽 `src/web/_naming.py`（routes/wizard 共享 workspace name 规则） | 新文件 + routes/wizard import |
| #8 | `start_job` thread.start() 失败回滚 `_WORKSPACE_JOBS` + `_JOBS` | `src/web/jobs.py` |

测试 +10：`tests/test_web_naming.py` (8) + tail partial-line (1) + thread-start rollback (1)。366 → 376 OK。

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

### P5 — Capstone 执行 ch2-30（TODO）

3 终端：watchdog + write_book.sh + dashboard。`--budget-cny 60` 硬上限。ch10/20/30 人工抽检评分 → `scratch_ratings.md`。

### P6 — 数据采集 + 报告（TODO）

`scripts/iter027_collect_data.py` 采每章 verdict / rewrite / lint / advisor / cost；写本报告 Acceptance + 失败模式分析。

### P7 — /code-review + 收尾 commit（TODO）

standing instruction：`/code-review high effort` → blocker 当 iter 修；其余写进 iter 028 plan。README SOP + AGENT_HANDOFF 更新。commit 不 push。

## Acceptance（TODO 跑完填）

| # | 项 | 结果 |
|---|---|---|
| A1 | P1 连通性 smoke OK | ✅ 9 秒 / 437+97 tokens |
| A2 | P2 hardening 3 项 +10 测试 → 376 OK | ✅ |
| A3 | P4 ch1 落盘 + 质量过 gate | ? |
| A4 | P5 30 章 verdict Approve ≥ 24/30 | ? |
| A5 | 总成本 ≤ ¥60 | ? |
| A6 | ch10/ch20/ch30 抽检评分均值 ≥ 7/10 | ? |
| A7 | P7 /code-review blocker 全修 | ? |

## 失败模式分析（TODO 跑完填，沿用 iter 020 模板 8 节）

1. outline 漂移
2. persona 漂移
3. lint 击穿
4. 重写次数分布
5. re-plan 成本
6. per-章 cost 曲线
7. 总成本 vs 预算
8. advisor rewrite_suggestions 实际效果

## 不在本轮范围（推 iter 028）

- longzu ch31-100
- iter 026 review 剩 5 项 hardening：.env 注释保留 / job_status workspace exists 一致性 / 未引号 multipart filename / wizard re-run apply_failed 噪音 / wizard except 吞 MemoryError
- WebUI 章节 Markdown 在线编辑器 / 雷达 / 甘特图
- KB 按起点过滤
- entity_graph timeline schema 升级
- phase 4 收官报告 `docs/stage_04_summary.md`
