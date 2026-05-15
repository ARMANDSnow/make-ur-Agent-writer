# Iteration 008 - Write Smoke + Ballot Field Repair

## Context

Iteration 007 hardened ballot prompts enough to stop empty true-model ballots, but 3/6 agents still fell to `(parse_failed)` because their JSON objects were structurally close yet omitted the required `position` field. Stage 2 also still lacked a true-model `write --chapters 1 --force` run. This iteration repaired the ballot field path, ran the first true-model write/review sample, and kept the resulting draft inspectable even when reviewers rejected it.

## Plan

### P1. Ballot field repair

- Switched `_collect_agent_vote_json` in [src/debater.py](../../src/debater.py) from `complete_json(..., AgentVoteBallot)` to `complete_text` plus `extract_json_object`.
- Added `_repair_ballot_dict` and `_infer_position_from_reason`.
- Missing or invalid `position` is repaired from alias fields (`answer`, `preference`, `verdict`, `vote`) or obvious agree/reject language in `reason`.
- Existing fallback meanings remain distinct: `(mock)`, `(missing-after-retry)`, and `(parse_failed)`.

### P2. True-model write smoke

- Added [scripts/write_smoke.sh](../../scripts/write_smoke.sh): preflight -> compress -> debate -> write 1 chapter -> review -> status -> estimate-cost -> preflight -> snapshot.
- The first true-model run exposed two additional real-output hardening points:
  - [src/reviewer.py](../../src/reviewer.py) now repairs missing review `agent_name` before `AgentReview` validation.
  - [src/writer.py](../../src/writer.py) now persists rejected/lint-failed drafts as human-review artifacts instead of leaving only a truncated failure preview.
- Final artifacts were snapshotted under `outputs/drafts/snapshots/20260514_220808/`.

### P3. Tests

- Added 5 ballot repair tests in [tests/test_debater.py](../../tests/test_debater.py).
- Added reviewer repair coverage for missing `agent_name`.
- Updated writer lint-failure coverage so rejected drafts remain inspectable with `needs_human_review=true`.

### P4. Documentation

- New iteration record: this file.
- [docs/iterations/README.md](./README.md) updated.
- [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) updated with the true-model result and Stage 3 candidates.

## Acceptance

| # | Check | Result |
|---|---|---|
| A1 | `python3 -m unittest discover -s tests` | Passed before true run: `Ran 85 tests in 1.896s, OK` |
| A2 | `bash scripts/verify.sh` | Passed before true run: `Ran 85 tests in 2.090s, OK`; inspected LLM log rows were `model=mock` |
| A3 | `python3 main.py preflight` | Passed before and after true run: `PREFLIGHT: warn`, FATAL `none` |
| B1 | ballot repair helper/integration tests | Passed |
| B2 | `_collect_agent_vote_json` no longer pydantic-validates `AgentVoteBallot` directly | Passed: uses `complete_text` + `_repair_ballot_dict` |
| B3 | fallback compatibility | Passed: mock/retry/parse failure paths still distinct |
| C1 | `scripts/write_smoke.sh` syntax + snapshot block | Passed: `bash -n` OK; contains `outputs/drafts/snapshots/${ts}` |
| D1 | true-model smoke execution | Partial: initial script reached debate/write path but exited 1 in standalone review due missing `agent_name`; repaired and resumed from write/review |
| D2 | ballot repair true-model effect | Passed: 6/6 agents produced complete non-fallback ballots |
| D3 | `chapter_01.md` length | Passed: 1825 characters |
| D4 | meta structure | Passed: `rewrite_count=1`, `needs_human_review=true`, `last_blocking_reasons` length 14, 7 reviewer outputs |
| D5 | actionable review issue | Passed: 16 structured issues with `rule_id`, `severity`, and `anchor`; final verdict `Reject` |
| D6 | DeepSeek ok rate | Passed for measured block: 67/67 `ok` |
| D7 | extraction failures | Passed: `data/extraction_failures/` empty |
| D8 | snapshot completeness | Passed: draft, meta, reviews, debate decisions, debate outline, and failed initial smoke log are in the snapshot |
| E | cost budget | Dollar billing not measured locally; token volume recorded below |
| F1-F5 | docs / handoff / secret scan | Passed; no new secret-prefix diff |

## Implementation Notes

- Repair happens before completeness checks, so ballot length and `question_index` coverage still decide retry/fallback.
- Reviewer repair is deliberately narrow: fill `agent_name`, normalize `verdict`, preserve `AgentReview` validation for issues.
- Writer still records rejected output truthfully. The new behavior only ensures the generated prose is inspectable at `chapter_01.md` with `needs_human_review=true`.
- `scripts/write_smoke.sh` remains the intended one-shot entrypoint, but this run required recovery because the first real review output exposed a missing-field path.

## Acceptance Result

Local checks:

```bash
python3 -m unittest tests.test_debater
# Ran 19 tests in 0.111s, OK

python3 -m unittest discover -s tests
# Ran 85 tests in 1.896s, OK

bash scripts/verify.sh
# Ran 85 tests in 2.090s, OK

python3 -m unittest tests.test_debater tests.test_reviewer tests.test_reviewer_structured tests.test_writer tests.test_writer_rewrite_loop
# Ran 27 tests in 0.105s, OK
```

True-model commands and recovery:

```bash
bash scripts/write_smoke.sh
# logs/write_smoke_20260514_214854.log
# exited 1 during standalone review: AgentReview.agent_name missing

python3 main.py write --chapters 1 --force
# exposed lint-failure draft persistence gap

python3 main.py write --chapters 1 --force
# after writer persistence repair, exit code 0

python3 main.py status
# write: 1 drafts, 1 meta, 0 failures

python3 main.py estimate-cost
# llm_logged_calls=1893
# actual_prompt_tokens=3587150
# actual_response_tokens=423482

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
```

True-model artifact metrics:

- Initial failed log: `logs/write_smoke_20260514_214854.log`.
- Final snapshot: `outputs/drafts/snapshots/20260514_220808/`.
- Debate log: 42 items; 6 `裁决投票` entries.
- Ballots: 6/6 non-fallback agents (`路明非本位`, `情感关系`, `伏笔猎人`, `世界观守门人`, `江南人格模拟`, `读者代言人`).
- Decisions: 2 votes; `agent_votes` lengths `[6, 6]`; `for` lengths `[6, 6]`; `against` lengths `[0, 0]`.
- Draft: `outputs/drafts/chapter_01.md`, 1825 characters.
- Meta: `rewrite_count=1`, `needs_human_review=true`, `last_blocking_reasons` length 14.
- Review: 7 agent reviews, 4 rejecting reviewers, 16 structured issues.
- Example issue: `情感关系 / relationship_progression / major` flagged the unexplained source of 绘梨衣's diary as an emotional-continuity weakness.
- Measured DeepSeek block from this run/recovery: 67 calls, 67 `ok`; task counts `compress=1`, `debate=45`, `write=6`, `review=15`.
- Token sums for that block: prompt 319,183; response 69,615; cache_read 18,048; cache_write 301,135.
- `data/extraction_failures/` stayed empty.

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/debater.py](../../src/debater.py) | ballot text JSON parsing + repair helpers |
| [src/reviewer.py](../../src/reviewer.py) | review text JSON parsing + missing `agent_name` repair |
| [src/writer.py](../../src/writer.py) | persist rejected/lint-failed drafts as human-review artifacts |
| [tests/test_debater.py](../../tests/test_debater.py) | repair tests; retry tests now mock `complete_text` |
| [tests/test_reviewer.py](../../tests/test_reviewer.py) | reviewer text JSON path + missing `agent_name` test |
| [tests/test_reviewer_structured.py](../../tests/test_reviewer_structured.py) | structured review test updated for text JSON path |
| [tests/test_writer.py](../../tests/test_writer.py) | lint-failure draft persistence test |
| [scripts/write_smoke.sh](../../scripts/write_smoke.sh) | true-model write smoke entrypoint + draft snapshot |
| [docs/iterations/iteration_008_write_smoke_and_ballot_repair.md](./iteration_008_write_smoke_and_ballot_repair.md) | new iteration record |
| [docs/iterations/README.md](./README.md) | add index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | add Iteration 008 result |

## 不在本轮范围

- Generalization: workspace concept, multilingual splitter, agent persona abstraction, independent continuation mode.
- DeepSeek cache behavior changes.
- Rolling summary structured foreshadowing table.
- Incremental compress.
- Polishing the generated chapter into a finished chapter.

## Notes

### Stage 2 数字快照草稿

- Stage 2 has now run true-model extract for 2 chapters, multiple debate smokes, repaired majority ballots, and one true-model write/review sample.
- Iteration 007 final debate status: 50/50 recent DeepSeek calls `ok`, 3/6 complete non-fallback ballots, 4 decisions, no extraction failures.
- Iteration 008 final true-model status: measured block 67/67 DeepSeek calls `ok`, 6/6 complete non-fallback ballots, 1 chapter draft at 1825 chars, 7 reviewer outputs with 16 structured issues, no extraction failures.
- Top issues:
  - DeepSeek can omit required identity fields in otherwise useful JSON (`position`, `agent_name`); repaired locally.
  - Cache behavior is mixed: debate still mostly logs `cache_read_tokens=0`, while write/review showed some cache reads.
  - True write quality bottleneck: the draft is long enough and reviewable, but reviewers reject it for weak diary provenance, under-supported contract/bloodline logic, and overly direct exposition.
