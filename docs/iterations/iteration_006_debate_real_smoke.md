# Iteration 006 - Preflight Provider Routing + Debate 真模型小样本

## Context

Stage 2 的第一轮目标是用真模型小样本探翻车。Iteration 005 已把 debate 决策升级为 agent ballot + majority 聚合，但此前真实模型联调踩到 LiteLLM 不识别裸 `deepseek-chat` 的 provider routing 问题。本轮先把这个错误前移到 preflight FATAL，再跑一次 DeepSeek debate smoke，观察真实输出质量。

本轮事实前置依赖是 `data/manual_overrides/global_facts.json`。该文件是本地运行输入，不进 git；用户已审阅确认 5 条 placeholder facts 后才继续执行 debate smoke。

## Plan

### P1. preflight provider routing FATAL

- [src/preflight.py](../../src/preflight.py) 新增 `_check_provider_routing`。
- 非 mock 模型下 lazy import `litellm.get_llm_provider`。
- 若 LiteLLM 无法解析 provider，preflight FATAL 提示使用 `deepseek/deepseek-chat` 或 `openai/gpt-4` 这类显式前缀。
- 调用点放在 `_check_agents_config` 之后、`_check_context_limits` 之前。

### P4. 测试

- [tests/test_preflight.py](../../tests/test_preflight.py) 新增 2 条：
  - 裸 `deepseek-chat` provider routing FATAL。
  - `deepseek/deepseek-chat` 不产生 routing FATAL。
- 测试中屏蔽真实 `.env`，避免单测被本地 DeepSeek 配置污染。

### P2. global_facts placeholder

- 写入本地 `data/manual_overrides/global_facts.json`，包含 5 条 placeholder facts。
- `fact_id` 唯一，`evidence_spans` 暂为空。
- 用户审阅确认后进入 P3。

### P3. debate 真模型小样本

- 第一次在普通沙箱中运行 `bash scripts/debate_smoke.sh`，脚本退出 0，但 44 条 DeepSeek 调用全部为 `Operation not permitted`，属于沙箱网络拦截导致的 fallback 假阳性。
- 按权限流程提权重跑同一脚本，日志写入 `logs/debate_smoke_20260514_195025.log`。
- 提权重跑完成：末尾 preflight 为 `warn`，FATAL 为 `- none`。

### P5. 文档

- 新建本文件。
- 更新 [docs/iterations/README.md](./README.md) 第 6 条索引。
- 更新 [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) 的 iteration 006 结果与 Next Candidates。

## Acceptance

| # | 检查项 | 产物 | 应满足 |
|---|--------|------|--------|
| A1 | 单测 | `OPENAI_MODEL=mock python3 -m unittest discover -s tests` | `Ran 75 tests`，`OK` |
| A2 | verify.sh | `OPENAI_MODEL=mock bash scripts/verify.sh` | 退出码 0 |
| A3 | mock preflight | `OPENAI_MODEL=mock python3 main.py preflight` | `warn`，FATAL `- none` |
| B1 | provider routing FATAL | 裸 `OPENAI_MODEL=deepseek-chat` preflight | FATAL 命中 `litellm cannot resolve provider`，退出码 1 |
| B2 | 正确 model 名通过 | `.env` 的 `deepseek/deepseek-chat` preflight | `warn`，无 routing FATAL |
| C1 | facts 已注入 | `data/manual_overrides/global_facts.json` | 5 条 fact，`fact_id` 唯一 |
| C2 | facts WARN 消失 | 真模型 preflight | WARN 不再含 `global_facts.json is missing or empty` |
| D1 | debate 真模型跑完 | `logs/debate_smoke_20260514_195025.log` | 退出码 0；末尾 preflight FATAL `- none` |
| D2 | 真模型 ballot 非全 fallback | `outputs/debate/debate_log.jsonl` | 部分通过：6 个 agent 都非 `(mock)` / `(parse_failed)`，但全部返回空 ballot 后补齐为 abstain |
| D3 | 多数决聚合真实 for/against | `outputs/debate/decisions.json` | 未通过：`for` / `against` 仍全空 |
| D4 | agent_votes 结构完整 | 同上 | 通过：每条 vote 的 `agent_votes` 长度为 6 |
| D5 | 真实 token 留痕 | `logs/llm_calls.jsonl` | 通过：提权真跑最后 48 条 DeepSeek 调用均 `ok` |
| D6 | 失败无残留 | `data/extraction_failures/` | 通过：空目录 |
| E | 成本受控 | token 增量 | 部分通过：粗估成本仍受控，但 prompt+response token 增量约 264,755，超过 200k 门槛 |
| F1-F3 | 文档同步 | 本文件、索引、handoff | 已完成 |
| F4 | 无 key 泄露 | 全仓 secret-prefix 扫描 | 见 Acceptance Result |

## Implementation Notes

- `_check_provider_routing` 使用 lazy import；mock 模式直接 return，不让普通 mock preflight 依赖 LiteLLM。
- 新增测试用 `types.SimpleNamespace` 注入 fake `litellm`，避免单测依赖本机 LiteLLM 版本行为，同时覆盖 FATAL/非 FATAL 两条路径。
- `test_missing_api_key_for_real_model_is_fatal` 也屏蔽了 `load_dotenv_if_available`，否则真实 `.env` 会补回 API key，破坏缺 key 场景。
- 因为当前 `.env` 是真实 DeepSeek 配置，验收中的单测和 verify 使用 `OPENAI_MODEL=mock` 显式覆盖；`python-dotenv` 默认不覆盖已有环境变量。
- 第一次未提权 smoke 的 44 条 `Operation not permitted` 记录保留在 `logs/llm_calls.jsonl`，但最终验收以提权后的 `logs/debate_smoke_20260514_195025.log` 和最后一段 DeepSeek ok 调用为准。
- 真实模型 ballot 调用没有 parse failure，但模型返回 `{"ballots": []}`；当前 `_collect_agent_votes` 对缺失 question_index 的补齐策略会写入 `(missing)` abstain。这是本轮最重要的翻车样式。

## Acceptance Result

通过项：

```bash
OPENAI_MODEL=mock python3 -m unittest discover -s tests
# Ran 75 tests in 2.299s, OK

OPENAI_MODEL=mock bash scripts/verify.sh
# exit code 0
# Ran 75 tests in 2.113s, OK

OPENAI_MODEL=mock python3 main.py preflight
# PREFLIGHT: warn
# FATAL: - none

OPENAI_MODEL=deepseek-chat OPENAI_API_KEY=test OPENAI_BASE_URL=https://x.com python3 main.py preflight
# exit code 1
# FATAL: litellm cannot resolve provider for OPENAI_MODEL='deepseek-chat'

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: - none
# model table uses deepseek/deepseek-chat

bash scripts/debate_smoke.sh
# rerun with approved network access
# Debate smoke log written: logs/debate_smoke_20260514_195025.log
```

真实 smoke 观测：

- `outputs/debate/debate_log.jsonl` 共 42 条，含 6 条 `round_name == "裁决投票"`。
- 最后 48 条真实 DeepSeek 调用：`model=deepseek/deepseek-chat`，`status=ok` 48/48。
- 真跑 token：prompt 220,833；response 43,922；合计 264,755；`cache_read_tokens=0`，`cache_write_tokens=220,833`。
- `data/extraction_failures/` 无残留。

未通过 / 需后续处理：

- D2 未完全达标：6 个 agent 的 ballot response 都不是 mock/parse_failed，但均为 `{"ballots": []}`，补齐后 position 全为 `abstain`、reason 为 `(missing)`。
- D3 未达标：`outputs/debate/decisions.json` 中 2 条 vote 的 `for` / `against` 都为空。
- E 的 token 门槛未达标：本次真跑 prompt+response 增量约 264,755，高于 200k 预期；同时 DeepSeek cache 只有 write、没有 read 命中。
- 普通未提权 smoke 曾被沙箱网络拦截，产生 44 条 `Operation not permitted` error 记录；已通过提权重跑获得真实结果。

Key 安全：

- 本轮没有写 `.env`，没有把 API key 写入 src/tests/docs。
- `global_facts.json`、logs、outputs 均为本地/忽略产物，不进入 commit。

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/preflight.py](../../src/preflight.py) | 新增 `_check_provider_routing`；接到 `run_preflight` |
| [tests/test_preflight.py](../../tests/test_preflight.py) | +2 条 routing 测试，并隔离真实 `.env` |
| [docs/iterations/iteration_006_debate_real_smoke.md](./iteration_006_debate_real_smoke.md) | 新建 |
| [docs/iterations/README.md](./README.md) | 追加第 6 条 |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | 追加 006 摘要 + 调整 Next Candidates |

## 不在本轮范围

- 真模型 write + review。
- B3 rolling summary 升级为结构化伏笔追踪表。
- C2 增量 compress。
- 加权投票 / veto。
- evidence_spans 回填。
- 本轮不修 ballot prompt；仅记录真实翻车样式。

## Notes

- Iteration 007 的优先候选：让 `AgentVoteBallot` prompt 更强约束“必须对每个 question_index 返回一条 ballot”，并考虑对空 ballots 做一次 JSON retry/repair。
- 当前 DeepSeek cache 观测为 `cache_write_tokens > 0` 且 `cache_read_tokens == 0`，需要后续单独调查 provider cache 是否真正命中。
- 如果继续跑 debate 真模型，建议先解决空 ballots，否则仍会得到全 abstain 的 majority 聚合。
