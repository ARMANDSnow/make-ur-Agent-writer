# Iteration 012 - Reviewer JSON Robustness + Debate Fallback + Consistency Strict

## Context

Iteration 011 brought entity graph state into write/debate/review and produced a higher-quality DeepSeek v4-pro draft, but the true-model smoke exposed three operational gaps: standalone review could crash when a reviewer returned non-JSON text, debate decisions could end up with `votes=[]`, and the new `关系一致性` reviewer could approve without proving it had checked active relationship state.

This iteration stays in the repair-and-strengthen lane. It does not change multi-chapter architecture, entity graph advancement, generalization, rolling-summary structure, or model selection.

## Plan

P1. Harden `review_text` when a reviewer response has no parseable JSON. Return a structured Approve fallback with `_fallback_reason="(parse_failed)"`, preserve lint issues, write the review report, and log `review/json_parse_fallback` instead of raising.

P2. Harden `build_decisions` when LLM-derived decisions contain no votes. Log `debate/votes_empty_fallback`, ask the model once for loose legacy-style votes, parse lenient JSON, and fall back to placeholder review votes if that also fails.

P3. Strengthen the `关系一致性` review-agent prompt so it must output a `对照清单`, compare draft interactions against active entity relationships, and avoid empty Approve responses that do not explain the comparison process. After the true smoke showed v4-pro could still ignore this instruction, add a local guard that turns a pure empty relationship Approve into a visible `relationship_checklist_missing` review issue.

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
- Added `_repair_agent_review_dict()` enforcement for `关系一致性`: if both `issues` and `comparison_checklist` are empty, the review becomes Reject with rule_id `relationship_checklist_missing`. This preserves real checklist approvals but prevents silent pure Approve.
- Added seven focused tests across `tests/test_reviewer.py`, `tests/test_debater.py`, and `tests/test_writer.py`.

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

True-model smoke was then run after the user replied `可以跑了`:

```bash
bash scripts/write_smoke.sh
# Initial sandbox attempt failed before remote access: Operation not permitted
# Re-run with approved network access exited 0
# Snapshot saved: outputs/drafts/snapshots/20260519_103436
# Write smoke log written: logs/write_smoke_20260519_103436.log
```

Acceptance details from snapshot `outputs/drafts/snapshots/20260519_103436/`:

| Item | Result |
|------|--------|
| C1 smoke full run | Passed: preflight → compress → debate → write → review → status → estimate-cost → preflight → snapshot |
| D1 snapshot | Passed: `chapter_01.md`, `chapter_01.meta.json`, `reviews/`, `debate_decisions.json`, `debate_outline.md` present |
| D2 Chinese length | Passed: 3921 Chinese chars |
| D3 relationship reviewer | Failed in this true run: standalone `关系一致性` returned pure Approve with `issues=[]` and `comparison_checklist=[]`; local guard was added afterward so this cannot remain invisible in future runs |
| D4 debate votes | Passed: `votes` length 3, each with 6 agent ballots |
| D5 DeepSeek ok rate | Passed for approved network run: 83/83 ok (`compress=1`, `debate=46`, `write=4`, `review=32`) |
| D6 user self-review | Pending user reading |
| D7 extraction failures | Passed: `data/extraction_failures/` empty |
| E cost | Token block: prompt 662,679 / response 110,958 / cache_read 196,096 / cache_write 466,583; same order as previous v4-pro smoke, exact bill left to provider console |

The final draft is usable as a human-review artifact but not an automatic pass: meta has `verdict=Reject`, `needs_human_review=true`, `rewrite_count=2`, `polish_applied=true`, and deterministic lint still reports repeated `not_x_but_y` errors plus `name_drift` warnings. The standalone review itself completed without the iter 011 crash.

Post-guard mock validation:

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 112 tests in 1.992s, OK

bash scripts/verify.sh
# Ran 112 tests in 2.060s, OK; script exited 0

PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
```

## 文件变更汇总

| File | Change |
|------|--------|
| [src/reviewer.py](../../src/reviewer.py) | Add review JSON parse fallback report and log event |
| [src/debater.py](../../src/debater.py) | Add empty-votes fallback and loose legacy vote parsing |
| [src/schemas.py](../../src/schemas.py) | Add optional `comparison_checklist` to `AgentReview` |
| [config/agents.yaml](../../config/agents.yaml) | Strengthen only the `关系一致性` reviewer prompt |
| [tests/test_reviewer.py](../../tests/test_reviewer.py) | Add parse fallback, relationship prompt, and relationship checklist guard tests |
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

- `.env` and `小说txt/` were not edited. True-model smoke wrote ignored `logs/`, `outputs/`, and generated `data/` artifacts as expected.
- `bash scripts/verify.sh` later overwrote current `outputs/` with mock artifacts; the true-model artifact to inspect is the snapshot `outputs/drafts/snapshots/20260519_103436/`.
- The first sandboxed smoke attempt left one expected `Operation not permitted` error row before approved network access. The approved network block itself was 83/83 ok.
