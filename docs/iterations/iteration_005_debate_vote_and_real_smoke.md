# Iteration 005 - Debate 结构化投票 + DeepSeek 真模型小样本

## Context

Iteration 004 完成了 `max_review_attempts` 硬要求与 splitter confidence。本轮从候选项里取 B2 和真模型小样本：先把 debate 的 `for` / `against` 从“事后让模型猜”改为 agent 自报 ballot 后显式多数决聚合；再为 DeepSeek 小样本保留 `real_smoke.sh` 路径与独立 debate smoke 入口。

安全约束：真实 DeepSeek key 只允许由用户手工写入项目根 `.env`，不得写入任何 git tracked 文件、Markdown、测试或注释。本次执行期间未写入任何 key。

## Plan

### P1. schemas 增加 AgentVote，DebateVote 加 agent_votes

- [src/schemas.py](../../src/schemas.py) 新增 `AgentVote`。
- `DebateVote` 新增默认空列表 `agent_votes`，保持旧 `decisions.json` 反序列化兼容。
- `DebateDecisions` 新增 `aggregation_method: "majority"`。

### P2. debater.py 最后一轮后收集结构化 vote

- 保留原 6 轮自由文本辩论。
- 6 轮结束后先生成议题清单，再逐 agent 调 `_collect_agent_votes`。
- 新增临时 schema `AgentVoteBallot` / `AgentVoteBallotItem`。
- mock 模式生成确定性 abstain ballot，reason 为 `(mock)`。
- JSON 解析失败或调用失败时落 abstain，reason 为 `(parse_failed)`，并写 `log_event("debate", "ballot_fallback", ...)`。
- `outputs/debate/debate_log.jsonl` 新增 `round_name == "裁决投票"` 的 ballot 轨迹。

### P3. build_decisions 显式多数决聚合

- `build_decisions(..., agent_ballots=None)` 增加可选 keyword-only 参数。
- 不传 `agent_ballots` 时保留旧行为，包括 LLM 返回的 `for` alias。
- 传入 `agent_ballots` 时忽略 LLM 自带 `for` / `against`，按 `agree` / `reject` 重算。
- 平票给 `result` 加 `[平票] ` 前缀；多数反对给 `result` 加 `[多数反对] ` 前缀；原 result 文本保留。

### P5. 测试

- [tests/test_debater.py](../../tests/test_debater.py) 增加 5 条覆盖：
  - 多数决产出 `for` / `against`；
  - 平票 result 前缀；
  - ballot parse fallback 落 abstain 并 log_event；
  - 旧路径不传 ballots 时保留 LLM votes；
  - mock `run_debate` 输出 `agent_votes` 与“裁决投票”日志。

### P4. DeepSeek 真模型小样本与 debate smoke

- 新增 [scripts/debate_smoke.sh](../../scripts/debate_smoke.sh)，用于下轮单独验证 debate。
- `bash -n scripts/debate_smoke.sh` 通过。
- `OPENAI_MODEL=mock bash scripts/debate_smoke.sh` 通过，日志写入 `logs/debate_smoke_20260513_221403.log`。
- 真模型 `bash scripts/real_smoke.sh` 未执行：项目根 `.env` 尚未包含用户手工写入的新 DeepSeek key。

## Acceptance

| # | 检查项 | 产物 | 应满足 |
|---|--------|------|--------|
| A1 | 单测通过 | `python3 -m unittest discover -s tests` | `Ran 73 tests`，`OK` |
| A2 | verify.sh 通过 | `bash scripts/verify.sh` | 退出码 0 |
| A3 | preflight mock 模式 | `python3 main.py preflight` | `PREFLIGHT: warn`，FATAL 为 `- none` |
| B1 | decisions schema 升级 | `outputs/debate/decisions.json` | 顶层 `aggregation_method: "majority"`；vote 含 `agent_votes` |
| B2 | mock agent_votes 填充 | 同上 | 每条 vote 的 `agent_votes` 长度为 6 |
| B3 | for/against 与 agent_votes 一致 | 同上 | `for` 等于 agree agent；`against` 等于 reject agent |
| B4 | 投票日志留痕 | `outputs/debate/debate_log.jsonl` | `round_name == "裁决投票"` 条目 6 条 |
| B5 | 向后兼容 | 旧 `build_decisions` 调用与旧测试 | 保留通过 |
| C1-C7 | DeepSeek 真模型小样本 | `.env` + `logs/real_smoke_<ts>.log` | blocked：等待用户手工写入新 key |
| D1 | debate smoke 语法 | `bash -n scripts/debate_smoke.sh` | 退出码 0 |
| D2 | debate smoke mock | `OPENAI_MODEL=mock bash scripts/debate_smoke.sh` | 退出码 0，无真实 token |
| E1-E4 | 文档与 key 安全 | 本文件、索引、handoff、全仓扫描 | 文档已更新；未写真实 key |

## Implementation Notes

- `run_debate` 仍只把前 6 轮自由文本计入 `transcript_items`，投票轮作为审计日志写入 `debate_log.jsonl`。
- mock ballot 选择 abstain 而不是 agree，是为了遵循计划中“mock 或解析失败走 fallback”的规则；因此 mock decisions 的 `for` / `against` 都为空，并带 `[平票]` 前缀。
- `build_decisions` 的旧签名兼容保留为 `build_decisions(agents, transcript, client, global_facts=None, *, agent_ballots=None)`，旧调用方无需改动。
- `_apply_agent_ballots` 是私有聚合 helper，`run_debate` 复用首次生成的议题清单，不额外重复调用一次 LLM 生成 question/result。
- 本地目录不是 git worktree，`git status` 无法用于 C1；已确认 `.gitignore` 包含 `.env`，并用内容扫描避免 key 进入项目文件。

## Acceptance Result

通过：

```bash
python3 -m unittest discover -s tests
# Ran 73 tests in 1.084s, OK

bash scripts/verify.sh
# exit code 0
# Ran 73 tests in 1.065s, OK

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: - none

bash -n scripts/debate_smoke.sh
# exit code 0

OPENAI_MODEL=mock bash scripts/debate_smoke.sh
# exit code 0
# Debate smoke log written: logs/debate_smoke_20260513_221403.log
```

B2 mock 验收：

- `outputs/debate/decisions.json` 含 `aggregation_method: "majority"`。
- 每条 vote 含 6 条 `agent_votes`，字段为 `agent_name` / `position` / `reason`。
- 当前 mock ballot 全部为 `abstain`，所以 `for == []` 且 `against == []`，与 `agent_votes` 一致。
- `outputs/debate/debate_log.jsonl` 末尾有 6 条 `round_name == "裁决投票"` 记录。

DeepSeek 真模型小样本 C1-C7（用户手工写 `.env` 后由 claude 执行）：

```
.env:
OPENAI_API_KEY=<rotated by user, never logged>
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek/deepseek-chat
```

> **litellm 1.83.9 provider 路由踩坑**：裸 `deepseek-chat` 在该版本里**不被识别为 deepseek provider**，必须显式前缀 `deepseek/deepseek-chat`。`litellm.get_llm_provider("deepseek/deepseek-chat")` 返回 `('deepseek-chat', 'deepseek', None, 'https://api.deepseek.com/beta')`。之前两次跑挂（`deepseek-v4-pro` + 裸 `deepseek-chat`）都未真正发出 HTTP，0 真实 token 消耗。

```bash
bash scripts/real_smoke.sh
# 日志: logs/real_smoke_20260513_224648.log
```

| # | 验收项 | 结果 |
|---|--------|------|
| C1 | `.env` 不进 git | ✅ `.gitignore` 含 `.env`；本目录未 init git，沿用 .gitignore 验证 |
| C2 | 首次 preflight | ✅ `PREFLIGHT: warn`，FATAL `- none`，task model table 出现 `deepseek/deepseek-chat` |
| C3 | extract 2 章成功 | ✅ `2 JSON files, 0 failures`；ch001 触发 chunked extraction（3 chunk + merge），ch002 单次 |
| C4 | 真打到 DeepSeek | ✅ 本次 7 个调用 `model=deepseek/deepseek-chat`，全部 `status=ok`，token 实数 |
| C5 | 无失败残留 | ✅ `data/extraction_failures/` 空 |
| C6 | 末尾二次 preflight | ✅ `PREFLIGHT: warn`，FATAL `- none` |
| C7 | 成本估算 | ✅ 累计 `actual_prompt_tokens` 增长可见；`cache_*` 字段非负 |

**本次真实消耗**：
- 7 个调用：4× chunk extract (ch001) + 1× extract (ch002) + 2× preflight dummy
- prompt_tokens = 41,877；response_tokens = 17,107
- 估算成本 ≈ **$0.030**（DeepSeek-V3，输入 $0.27/M，输出 $1.10/M，未触发 cache hit）
- 耗时 2 分 25 秒

**日志清理**：本次执行前残留 4 条早期失败记录（model=`deepseek-v4-pro` 与裸 `deepseek-chat`，均为 litellm 本地拒错），已剔除并备份为 `logs/llm_calls.jsonl.bak_<ts>`。清理后 `python3 main.py preflight` 的 `last10` 显示 `{'ok': 10}`，混淆已消除。

环境备注：本目录不是 git worktree，无法用 `git status` 验证 `.env` 是否 tracked；改用 `.gitignore` 检查和内容扫描作为替代。

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/schemas.py](../../src/schemas.py) | 新增 `AgentVote`；`DebateVote` 加 `agent_votes`；`DebateDecisions` 加 `aggregation_method` |
| [src/debater.py](../../src/debater.py) | 新增 ballot schema、`_collect_agent_votes`、多数决聚合和“裁决投票”日志 |
| [tests/test_debater.py](../../tests/test_debater.py) | +5 条 debate vote 测试 |
| [scripts/debate_smoke.sh](../../scripts/debate_smoke.sh) | 新增 debate mock/real smoke 入口 |
| [docs/iterations/README.md](./README.md) | 索引追加 iteration 005 |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | 追加 005 结果，Next Candidates 移除 B2 |
| 本文件 | 新建 iteration 005 记录 |

## 不在本轮范围

- B3 rolling summary 升级为结构化伏笔追踪表。
- C2 增量 compress。
- 加权投票 / veto 策略。
- debate 真模型联调。
- 改写 mock 兜底 decisions 的硬编码议题内容。

## Notes

- `.env` 需要用户手工写入新 DeepSeek key 后再跑 `bash scripts/real_smoke.sh`。
- 真模型小样本跑完后，需要回填本文件 C1-C7 的具体日志路径、token 结果和 failure residue 状态。
- 下一轮若做 debate 真模型联调，可直接从 `scripts/debate_smoke.sh` 开始；预计调用量显著高于 extract 小样本。
