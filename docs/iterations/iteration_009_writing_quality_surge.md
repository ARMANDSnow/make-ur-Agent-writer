# Iteration 009 - Writing Quality Surge

## Context

Iteration 008 proved the true-model write/review path but produced a 5/10 chapter: too short, weakly anchored in time, written from compressed summaries rather than source-style examples, and rejected by 4/7 reviewers. Iteration 009 starts Stage 3 on the writing-quality axis before generalizing the system to arbitrary books.

## Plan

### P1. Style examples

- Add [src/style.py](../../src/style.py) with `load_style_examples`.
- Add [data/style_examples/README.md](../../data/style_examples/README.md) with local-only instructions for user-selected source excerpts.
- Inject style examples into writer stable context and debate outline generation.
- Skip `README.md` when loading examples so instructions are not treated as prose style.

### P2. Continuation anchor

- Add top-level `continuation_anchor` to [config/agents.yaml](../../config/agents.yaml), defaulting to an empty string.
- Inject non-empty anchor into writer, debate decisions, and debate outline prompts.
- Add preflight WARN when anchor is empty; this is not FATAL.

### P3. Chapter length

- Raise `write.max_tokens` from 5000 to 8000 in [config/models.yaml](../../config/models.yaml).
- Add writer instruction: target Chinese正文 3500-5500 chars.
- Add `short_chapter_length` linter rule:
  - `<2500` Chinese chars -> error;
  - `2500-3499` Chinese chars -> warning;
  - `>=3500` -> no issue.
- Add `chinese_char_count` to draft meta and failure reports.

### P4. Rewrite attempts

- Raise `max_review_attempts` from 2 to 3 in [config/agents.yaml](../../config/agents.yaml).

### P5. Tests

- Add style loader tests.
- Add writer prompt tests for style examples and continuation anchor.
- Add linter short-chapter rule test.
- Add preflight empty-anchor WARN test.

### P7. Documentation

- New iteration record: this file.
- README index updated.
- AGENT_HANDOFF updated with P1-P5 status and the pending P6 gate.

## Acceptance

| # | Check | Current P1-P5 Result |
|---|---|---|
| A1 | `python3 -m unittest discover -s tests` | Passed: `Ran 92 tests in 1.760s, OK` |
| A2 | `bash scripts/verify.sh` | Passed: `Ran 92 tests in 1.888s, OK`; log delta 85 rows, all mock |
| A3 | `OPENAI_MODEL=mock python3 main.py preflight` | Passed: warn with empty `continuation_anchor`, FATAL none |
| B1 | style example files | P6 prereq passed locally: 8 ignored files, 19695 chars |
| B2 | style injection tests | Added |
| B3 | anchor injection tests | Added |
| B4 | short chapter lint rule | Added |
| B5 | agents.yaml | `max_review_attempts=3`, `continuation_anchor` filled locally for P6 |
| B6 | models.yaml | `write.max_tokens=8000` |
| C1-D7 | true-model P6 smoke | Run on 2026-05-17; script exited 0, D1 failed at 2924 Chinese chars |
| F1-F3 | docs/index/handoff | Updated |
| F4 | secret scan | secret-prefix scan only hit historical stage summary text |

## Implementation Notes

- `data/style_examples/README.md` is the only tracked file under `data/style_examples`; user-selected excerpts remain local ignored files.
- Empty style examples are a no-op, so mock verify can run before user preparation.
- Empty `continuation_anchor` only warns. Writer and debate prompts omit the anchor block when it is blank.
- The length rule counts CJK Unified Ideographs using `'一' <= ch <= '鿿'`.
- Rejected drafts still persist from Iteration 008 behavior; Iteration 009 adds `chinese_char_count` for both accepted and human-review outputs.

## Acceptance Result

P1-P5 engineering verification:

```bash
python3 -m unittest discover -s tests
# Ran 92 tests in 1.760s, OK

bash scripts/verify.sh
# Ran 92 tests in 1.888s, OK
# LLM log delta from row 2264: new_count=85, models={'mock': 85}, statuses={'ok': 85}

OPENAI_MODEL=mock python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN includes: continuation_anchor is empty; writer will lack temporal anchor.
```

Post-P6 local verification:

```bash
python3 -m unittest discover -s tests
# Ran 92 tests in 1.985s, OK

bash scripts/verify.sh
# Ran 92 tests in 2.093s, OK
# LLM log delta from row 2562: new_count=126, models={'mock': 126}, statuses={'ok': 126}

OPENAI_MODEL=mock python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN: longest chapter exceeds 90% context window; no empty-anchor WARN because P6 anchor is filled locally.
```

P6 true-model smoke result after user prepared local style examples and `continuation_anchor`:

```bash
bash scripts/write_smoke.sh
# Snapshot saved: outputs/drafts/snapshots/20260517_145845
# Write smoke log written: logs/write_smoke_20260517_145845.log
```

Key metrics:

- Prereqs: 8 ignored style example files, 19695 total chars; `continuation_anchor` non-empty.
- C1: script exited 0; head and tail preflight were `warn`, FATAL `none`.
- D1: `chapter_01.md` = 3478 total chars / 2924 Chinese chars. This is a clear improvement over Iteration 008's 1825 total chars, but misses the `>=3000` Chinese-char hard floor.
- D2: meta includes `chinese_char_count=2924`, `rewrite_count=2`, `needs_human_review=true`.
- D3: standalone `chapter_01.review.json` is deterministic-linter-only Reject: 6 `not_x_but_y` errors plus 1 `short_chapter_length` warning. No true reviewer-agent issues were produced because the writer stopped at lint failure after 3 attempts.
- D4: pending user read/score.
- D5: DeepSeek increment from line 2473 was 49/49 `ok`: 1 compress, 45 debate, 3 write attempts.
- D6: `data/extraction_failures/` stayed empty.
- D7: snapshot contains chapter, meta, debate decisions, debate outline, and reviews directory.
- E: rough DeepSeek-V3 token cost from logged prompt/response tokens was about `$0.16`; provider cache logs showed `cache_read_tokens=31488`, `cache_write_tokens=290351`.

Debate side result: 42 debate log rows; decisions have 2 votes, 12 `agent_votes`, 10 non-fallback ballots, 2 fallback ballots, `for` lengths `[4, 5]`, and `against` lengths `[0, 0]`.

Conclusion: Iteration 009 P6 improved length and anchoring inputs but did not pass the hard writing-quality gate. The next engineering target should be Iteration 010: reduce over-triggering / prompt attraction around `not_x_but_y`, then add either a polish pass or chunked writing to reliably cross 3000+ Chinese chars without deterministic lint failure.

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/style.py](../../src/style.py) | new style example loader |
| [src/writer.py](../../src/writer.py) | style + anchor + length prompt injection; `chinese_char_count` meta |
| [src/debater.py](../../src/debater.py) | anchor/style injection into decision/outline prompts |
| [src/linter.py](../../src/linter.py) | `short_chapter_length` rule and Chinese char counter |
| [src/preflight.py](../../src/preflight.py) | empty `continuation_anchor` WARN |
| [config/agents.yaml](../../config/agents.yaml) | `max_review_attempts=3`, `continuation_anchor` |
| [config/models.yaml](../../config/models.yaml) | `write.max_tokens=8000` |
| [config/linter.yaml](../../config/linter.yaml) | enable `short_chapter_length` |
| [tests/test_style.py](../../tests/test_style.py) | new style loader tests |
| [tests/test_writer.py](../../tests/test_writer.py) | style and anchor prompt tests |
| [tests/test_linter.py](../../tests/test_linter.py) | short chapter rule test |
| [tests/test_preflight.py](../../tests/test_preflight.py) | empty anchor WARN test |
| [data/style_examples/README.md](../../data/style_examples/README.md) | local excerpt instructions |
| [docs/iterations/iteration_009_writing_quality_surge.md](./iteration_009_writing_quality_surge.md) | new iteration record |
| [docs/iterations/README.md](./README.md) | add index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | add Iteration 009 handoff |

## 不在本轮范围

- Re-running P6 true-model smoke after the failed hard gate.
- Writing or committing copyrighted source excerpts.
- Polish pass.
- Chunked writing.
- Workspace / multilingual / persona generalization.
- Reviewer prompt tuning beyond using the new true-model issues as future inputs.

## Notes

After this commit, the next action is user-gated:

1. User picks 3-5 local style examples into `data/style_examples/*.md`.
2. User fills `continuation_anchor`.
3. User replies `可以跑了`.
4. Then run P6 `bash scripts/write_smoke.sh` and record the true-model result in a follow-up commit.
