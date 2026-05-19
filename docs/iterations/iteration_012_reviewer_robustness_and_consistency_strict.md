# Iteration 012 - Reviewer JSON Robustness + Debate Fallback + Consistency Strict

## Context

Iteration 011 brought entity graph state into write/debate/review and produced a higher-quality DeepSeek v4-pro draft, but the true-model smoke exposed three operational gaps: standalone review could crash when a reviewer returned non-JSON text, debate decisions could end up with `votes=[]`, and the new `关系一致性` reviewer could approve without proving it had checked active relationship state.

This iteration stays in the repair-and-strengthen lane. It does not change multi-chapter architecture, entity graph advancement, generalization, rolling-summary structure, or model selection.

## Plan

P1. Harden `review_text` when a reviewer response has no parseable JSON. Return a structured Approve fallback with `_fallback_reason="(parse_failed)"`, preserve lint issues, write the review report, and log `review/json_parse_fallback` instead of raising.

P2. Harden `build_decisions` when LLM-derived decisions contain no votes. Log `debate/votes_empty_fallback`, ask the model once for loose legacy-style votes, parse lenient JSON, and fall back to placeholder review votes if that also fails.

P3. Strengthen the `关系一致性` review-agent prompt so it must output a `对照清单`, compare draft interactions against active entity relationships, and avoid empty Approve responses that do not explain the comparison process.

P4. Add focused tests for reviewer fallback, debate empty-votes fallback, loose legacy vote parsing, relationship prompt requirements, and writer shadow-review compatibility with the fallback report.

P5. True-model `bash scripts/write_smoke.sh` is gated on explicit user confirmation and is not part of the first engineering commit.

P6. Add this iteration record, update the iteration index, and append the handoff entry.

## Acceptance

| # | Item | Target |
|---|------|--------|
| A1 | Unit tests | `python3 -m unittest discover -s tests` passes, around 108 tests |
| A2 | Verify | `bash scripts/verify.sh` exits 0 and remains mock-only |
| A3 | Preflight | `python3 main.py preflight` reports warn / FATAL none |
| B1 | Review fallback | Unparseable reviewer text returns Approve fallback with `_fallback_reason="(parse_failed)"` |
| B2 | Debate fallback | Empty LLM decisions produce non-empty `votes` |
| B3 | Relationship prompt | `config/agents.yaml` contains `对照清单` and forbids empty pure Approve |
| C1-D7 | True-model smoke | Pending user confirmation after engineering commit |
| F1-F3 | Docs | Iteration doc, README index, and handoff are updated |

## Implementation Notes

- Added `_empty_approve_fallback()` in `src/reviewer.py` and wrapped the per-agent JSON extraction point. This matches the actual crash site from iter 011: one reviewer response could be empty/plain text and previously escaped as `ValueError`.
- Added optional `comparison_checklist` to `AgentReview` in `src/schemas.py` so the strengthened relationship reviewer can return explicit comparison evidence without breaking other reviewers.
- Added `_legacy_llm_derived_votes()` in `src/debater.py`. It accepts JSON objects or lists, supports loose `supporters/opponents` aliases, caps fallback votes to three items, and uses placeholder abstain-style votes only when parsing/model fallback also fails.
- Updated only the `关系一致性` review-agent prompt. The other seven review agents were left unchanged.
- Added five focused tests across `tests/test_reviewer.py`, `tests/test_debater.py`, and `tests/test_writer.py`.

## Acceptance Result

Engineering validation completed before true-model smoke:

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 110 tests in 2.335s, OK

bash scripts/verify.sh
# Ran 110 tests in 2.048s, OK; script exited 0

PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN: tokenizer fallback for deepseek-v4-pro and longest-chapter context warning
```

Targeted tests also passed:

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest tests.test_reviewer tests.test_debater tests.test_writer
# Ran 37 tests in 0.216s, OK
```

True-model `bash scripts/write_smoke.sh` was not run in this engineering pass, per project rule. C1-D7 remain pending until the user replies `可以跑了`.

## 文件变更汇总

| File | Change |
|------|--------|
| [src/reviewer.py](../../src/reviewer.py) | Add review JSON parse fallback report and log event |
| [src/debater.py](../../src/debater.py) | Add empty-votes fallback and loose legacy vote parsing |
| [src/schemas.py](../../src/schemas.py) | Add optional `comparison_checklist` to `AgentReview` |
| [config/agents.yaml](../../config/agents.yaml) | Strengthen only the `关系一致性` reviewer prompt |
| [tests/test_reviewer.py](../../tests/test_reviewer.py) | Add parse fallback and relationship prompt tests |
| [tests/test_debater.py](../../tests/test_debater.py) | Add empty-votes and loose legacy parsing tests |
| [tests/test_writer.py](../../tests/test_writer.py) | Add shadow-review fallback compatibility test |
| [docs/iterations/README.md](./README.md) | Add iteration 012 index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | Append iteration 012 engineering status and next candidates |

## 不在本轮范围

- Multi-chapter continuation architecture and active relationship advancement.
- Generalization axis: workspace abstraction, multilingual splitter, persona abstraction, independent mode.
- B3 rolling summary foreshadowing table.
- C2 incremental compress.
- Model change, weighted voting, and DeepSeek cache-read follow-up.
- True-model smoke before explicit user confirmation.

## Notes

- `.env`, `data/`, `outputs/`, `logs/`, and `小说txt/` were not edited.
- The preflight run observed `deepseek/deepseek-v4-pro` from the local environment, but no true-model smoke script was executed.
- After this commit, the next step is to wait for the user to say `可以跑了`, then run `bash scripts/write_smoke.sh`, record C1-D7, and make the second documentation commit.
