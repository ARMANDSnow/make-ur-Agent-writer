# Iteration 007 - Ballot Hardening + Test Isolation

## Context

Iteration 006 proved provider routing and true-model debate execution, but exposed three immediate issues: direct `unittest discover` could still inherit `.env` and burn DeepSeek quota; true-model ballot calls returned `{"ballots": []}` and collapsed majority voting into all-abstain; and `outputs/debate` could be overwritten by later mock runs before inspection.

This iteration fixes the two P0s first, adds smoke snapshots, time-boxes DeepSeek cache investigation, and prepares for a final true-model debate rerun after the user confirms a fresh `.env` key is ready.

## Plan

### P1. 测试隔离修复

- Added [tests/__init__.py](../../tests/__init__.py) to force `OPENAI_MODEL=mock` and remove real key/base URL in packaged test imports.
- Updated [scripts/verify.sh](../../scripts/verify.sh) to export `OPENAI_MODEL=mock` and unset real-model credentials before any Python command.
- Added a unittest-discover guard in [src/config.py](../../src/config.py), because `python3 -m unittest discover -s tests` imports test modules as top-level files and does not reliably import `tests/__init__.py`.

### P2. Ballot Prompt 加固

- Strengthened `_collect_agent_votes` prompt in [src/debater.py](../../src/debater.py):
  - ballots length must strictly equal the number of questions;
  - empty arrays are forbidden;
  - `question_index` must be unique and cover `0..N-1`;
  - questions are rendered as a numbered list.
- Added one retry on empty/incomplete/duplicate ballot output.
- Retry success uses the recovered ballots.
- Retry failure logs `ballot_empty_after_retry` and falls back to `(missing-after-retry)` abstain.

### P3. Real Outputs Snapshot

- Updated [scripts/debate_smoke.sh](../../scripts/debate_smoke.sh) to copy `decisions.json`, `debate_log.jsonl`, and `outline.md` into `outputs/debate/snapshots/${ts}/` before printing the final log line.

### P4. cache_read=0 调研

- Read project cache injection and local LiteLLM DeepSeek adapter behavior.
- Checked DeepSeek official Context Caching docs.
- Ran one controlled pair of identical `LLMClient("write")` calls.
- Wrote [docs/notes/deepseek_cache_2026_05.md](../notes/deepseek_cache_2026_05.md).

### P5. 测试

- Added 5 tests:
  - 2 ballot retry/fallback tests in [tests/test_debater.py](../../tests/test_debater.py);
  - 1 env isolation test in [tests/test_env_isolation.py](../../tests/test_env_isolation.py);
  - 2 script guard/snapshot tests in [tests/test_smoke_scripts.py](../../tests/test_smoke_scripts.py).

### P6. 真模型复跑

- User confirmed `.env` contains the rotated DeepSeek key.
- Ran `bash scripts/debate_smoke.sh` with approved network access.
- Log path: `logs/debate_smoke_20260514_205954.log`.
- Snapshot path: `outputs/debate/snapshots/20260514_205954/`.

### P7. 文档

- New iteration record: this file.
- README index updated.
- AGENT_HANDOFF updated.

## Acceptance

| # | 检查项 | 产物 | 应满足 |
|---|--------|------|--------|
| A1 | 单测，无 env 覆盖 | `python3 -m unittest discover -s tests` | `Ran 80 tests`，`OK`，< 5 秒 |
| A2 | verify.sh | `bash scripts/verify.sh` | 退出码 0，新增 LLM logs 全为 `mock` |
| A3 | mock preflight | `OPENAI_MODEL=mock python3 main.py preflight` | `warn`，FATAL `- none` |
| B1 | 测试 env 隔离 | `tests/__init__.py` / `src/config.py` | 强制 mock，清 key/base URL |
| B2 | verify.sh 防护 | `scripts/verify.sh` | export mock + unset key/base URL |
| C1 | ballot prompt 硬约束 | `src/debater.py` | 含严格等于/禁止空数组/numbered list |
| C2 | retry 路径 | `tests/test_debater.py` | retry success/fallback 测试通过 |
| D1 | snapshot 落盘 | `scripts/debate_smoke.sh` | 含 `outputs/debate/snapshots/${ts}` 拷贝块 |
| E1-E4 | 真模型 smoke 复跑 | `logs/debate_smoke_20260514_205954.log` + snapshot | 通过，见 Acceptance Result |
| F1 | cache 调研 note | `docs/notes/deepseek_cache_2026_05.md` | 已写入调研结论 |
| F2-F4 | 文档同步 | iteration doc / README / handoff | 已完成 |
| F5 | 无 key 泄露 | secret-prefix scan | 无新增 secret |

## Implementation Notes

- `tests/__init__.py` alone did not fire under this repository's `unittest discover -s tests` invocation, so `src/config.py` gained `_running_under_unittest_discover()` as an extra guard. It only trips when `unittest` is loaded and argv contains `discover`/`unittest`, so normal CLI and true smoke still read `.env`.
- `_collect_agent_votes` retries only when the parsed JSON shape is structurally incomplete; parse errors still use the existing `(parse_failed)` fallback path.
- The retry prompt is intentionally shorter than the first prompt, reducing the chance that the model ignores the output contract.
- Snapshot logic uses `cp ... 2>/dev/null || true` so a partially failed smoke still writes whatever artifacts exist.
- Cache experiment result: two identical prompts returned `cache_read_tokens=0` and `cache_write_tokens=504` both times. The note records this as unresolved/provider best-effort rather than changing code.

## Acceptance Result

Completed before P6:

```bash
python3 -m unittest discover -s tests
# Ran 80 tests in 1.926s, OK

bash scripts/verify.sh
# exit code 0
# Ran 80 tests in 2.014s, OK

# verify log delta from pre-verify row 1314:
# new_count=90, model_counts={'mock': 90}
```

Cache experiment:

```text
call 1: status=ok, prompt_tokens=504, response_tokens=1, cache_read_tokens=0, cache_write_tokens=504
call 2: status=ok, prompt_tokens=504, response_tokens=1, cache_read_tokens=0, cache_write_tokens=504
```

P6 true-model rerun:

```bash
bash scripts/debate_smoke.sh
# exit code 0
# Debate smoke log written: logs/debate_smoke_20260514_205954.log
# Snapshot saved: outputs/debate/snapshots/20260514_205954
```

Snapshot acceptance:

- `outputs/debate/snapshots/20260514_205954/debate_log.jsonl` has 42 items and 6 `裁决投票` entries.
- 3/6 agents returned complete non-fallback ballots of length 4: `路明非本位`, `江南人格模拟`, `读者代言人`.
- 3/6 agents still parse-failed because they returned ballot objects without `position`: `情感关系`, `伏笔猎人`, `世界观守门人`.
- `outputs/debate/snapshots/20260514_205954/decisions.json` has 4 votes; every vote has `agent_votes` length 6.
- `for` list lengths are `[3, 3, 2, 3]`; `against` list lengths are `[0, 0, 0, 0]`; therefore E3 passed.
- Last 50 DeepSeek calls: `model=deepseek/deepseek-chat`, `status=ok` 50/50.
- Token totals for the final 50-call block: prompt 231,581; response 56,294; total 287,875; `cache_read_tokens=0`; `cache_write_tokens=231,581`.
- `data/extraction_failures/` remained empty.

Residual:

- Ballot hardening fixed empty `ballots: []` for half the agents, but 3 agents still returned near-correct JSON with an invalid field name instead of `position`. Next step should normalize/repair obvious `answer`/`preference`-style fields or add schema-enforced JSON mode.
- Cost exceeded the original soft budget because retry/long responses made the final block 287,875 tokens. No key material was written to tracked files.

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [tests/__init__.py](../../tests/__init__.py) | 新建：测试环境强制 mock，清理真实 key/base URL |
| [src/config.py](../../src/config.py) | unittest discover 下跳过 `.env` 并强制 mock |
| [scripts/verify.sh](../../scripts/verify.sh) | 顶部 export/unset 防护 |
| [src/debater.py](../../src/debater.py) | ballot prompt 硬约束 + empty/incomplete retry |
| [tests/test_debater.py](../../tests/test_debater.py) | +2 retry 测试 |
| [tests/test_env_isolation.py](../../tests/test_env_isolation.py) | 新建 env isolation 测试 |
| [tests/test_smoke_scripts.py](../../tests/test_smoke_scripts.py) | 新建 smoke script 字符串断言 |
| [scripts/debate_smoke.sh](../../scripts/debate_smoke.sh) | 增加 outputs/debate snapshot |
| [docs/notes/deepseek_cache_2026_05.md](../notes/deepseek_cache_2026_05.md) | 新建 cache 调研 note |
| [docs/iterations/iteration_007_ballot_hardening_and_test_isolation.md](./iteration_007_ballot_hardening_and_test_isolation.md) | 新建 |
| [docs/iterations/README.md](./README.md) | 追加第 7 条 |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | 追加 iteration 007 结果 |

## 不在本轮范围

- B3 rolling summary 升级为结构化伏笔追踪表。
- C2 增量 compress。
- agent 加权投票 / veto 策略。
- 修 DeepSeek cache_read=0；本轮只调研。
- 真模型 write + review。
- evidence_spans 回填。

## Notes

- P6 rerun should be the first thing after user confirmation. The expected artifact is `outputs/debate/snapshots/<new ts>/`.
- If true-model ballots still come back empty after retry, the next step is schema-enforced JSON mode or provider/model switch, not another prompt-only tweak.
- Do not commit `.env`, `logs/`, `outputs/`, or `data/manual_overrides/global_facts.json`.
