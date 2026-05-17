# Iteration 010 - Linter Thresholds + Polish Pass + Reviewer Bypass Safety

## Context

Iteration 009 improved prompt inputs but failed the writing-quality gate. The true-model run completed, yet the writer used all 3 attempts and remained blocked by deterministic lint: repeated `not_x_but_y` hits were treated as immediate errors, the rewrite feedback did not include anchors, and reviewer agents never ran while lint errors existed. Iteration 010 fixes that engineering bottleneck before another true-model smoke.

## Plan

### P1. Thresholded lint with anchors

- Add `warn_threshold: 2` and `error_threshold: 5` for `not_x_but_y` in [config/linter.yaml](../../config/linter.yaml).
- Change `not_x_but_y` from one-hit error to cumulative scoring:
  - 0-2 hits: no issue;
  - 3-4 hits: warning;
  - 5+ hits: error.
- Add `anchor` to every lint issue.
- Add `count` to cumulative `not_x_but_y` issues.
- Feed lint `anchor` and `count` back to writer rewrites.
- Add an explicit writer-system constraint to keep this contrast sentence pattern under 2 uses per chapter.

### P2. Polish pass

- Add `polish_pass: true` to [config/agents.yaml](../../config/agents.yaml).
- Add `_polish_draft` in [src/writer.py](../../src/writer.py).
- When the normal rewrite budget is exhausted and the draft is still Reject, run one final polish call.
- Polish receives the last draft, deterministic lint anchors, reviewer issues, style examples, and continuation anchor.
- Polish output is written directly; it does not recurse into another review loop.
- Meta now records `polish_applied` and `polish_diff_stats`.

### P3. Reviewer bypass safety

- Add `review_during_lint_block: true` to [config/agents.yaml](../../config/agents.yaml).
- When deterministic lint still blocks a draft, writer runs a shadow review in a best-effort `try/except`.
- Add `run_agents_on_lint_error` to `review_text`; default behavior is unchanged.
- Store shadow review reports in `meta["lint_blocked_reviews"]`.
- Shadow review failures log `write/shadow_review_error` but do not stop the writer.

### P4. Tests

- Add threshold and anchor tests for the linter.
- Add writer tests for polish enable/disable behavior.
- Add writer test for shadow review during lint blocking.
- Adjust pre-existing tests for the new thresholded behavior.

### P6. Documentation

- Add this iteration record.
- Update the iteration index.
- Update handoff with Iteration 010 status and pending P5 gate.

## Acceptance

| # | Check | P1-P4 Result |
|---|---|---|
| A1 | `python3 -m unittest discover -s tests` | Passed: `Ran 98 tests in 2.129s, OK` |
| A2 | `bash scripts/verify.sh` | Passed: `Ran 98 tests in 2.086s, OK`; log delta 117 rows, all mock |
| A3 | `python3 main.py preflight` | Passed: warn, FATAL none |
| B1 | thresholded lint tests | Added |
| B2 | lint `anchor` field | Added for all lint issue types |
| B3 | writer feedback uses anchor/count | Added |
| B4 | polish pass | Added with config switch and tests |
| B5 | shadow review on lint block | Added with config switch and tests |
| C1-D7 | P5 true-model smoke | Run on 2026-05-17; script exited 0; D1 still failed at 2694 Chinese chars |
| F1-F3 | docs/index/handoff | Updated |
| F4 | secret scan | Secret-like token regex scan returned no hits |

## Implementation Notes

- `not_x_but_y` now emits one issue per matched sentence only after the chapter-level threshold is exceeded. Each emitted issue carries the same `count` so feedback can tell the writer the total hit count.
- Lint anchors are capped at 100 chars. For match-based rules, the anchor is a local window around the matched phrase; for line/rule-level issues it falls back to a trimmed line or count marker.
- `_polish_draft` is deliberately a terminal operation. It may improve the final persisted draft, but it does not hide issues by running a second lint/review loop inside the same command.
- Shadow review exists to collect reviewer signal even when deterministic lint blocks normal review; it is observational and does not change the blocking verdict.
- `review_text(..., run_agents_on_lint_error=True)` is opt-in. Existing direct review behavior still returns deterministic Reject without calling reviewer agents when lint errors exist.

## Acceptance Result

P1-P4 engineering verification:

```bash
python3 -m unittest discover -s tests
# Ran 98 tests in 2.129s, OK

bash scripts/verify.sh
# Ran 98 tests in 2.086s, OK
# LLM log delta from row 2982: new_count=117, models={'mock': 117}, statuses={'ok': 117}

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN includes tokenizer fallback and longest-chapter context warning.
```

Secret-like token regex scan returned no hits in tracked source/docs/config/script files outside ignored runtime artifacts.

P5 true-model smoke result after user confirmation:

```bash
bash scripts/write_smoke.sh
# Snapshot saved: outputs/drafts/snapshots/20260517_155018
# Write smoke log written: logs/write_smoke_20260517_155018.log
```

P5 metrics:

- Snapshot: `outputs/drafts/snapshots/20260517_155018/`
- Log: `logs/write_smoke_20260517_155018.log`
- C1: script exited 0; head and tail preflight were `warn`, FATAL `none`.
- D1: `chapter_01.md` = 3378 total chars / 2694 Chinese chars. This misses the `>=3000` Chinese-char hard floor.
- D2: meta includes `chinese_char_count=2694`, `rewrite_count=2`, `needs_human_review=false`, `polish_applied=false`, `polish_diff_stats={}`, and `lint_blocked_reviews=[]`.
- D3: writer in-loop meta has 7 `agent_reviews`, all `Approve`, with 2 total issues. The standalone review file under `reviews/chapter_01.review.json` has 7 reviewer outputs with 6 `Approve` and 1 `Reject`, so reviewer signal is now available either way.
- D4: pending user read/score (`待用户评分`).
- D5: DeepSeek increment from line 3100 was 76/76 `ok`: 1 compress, 44 debate, 3 write, 28 review.
- D6: `data/extraction_failures/` stayed empty.
- D7: snapshot contains chapter, meta, debate decisions, debate outline, and reviews directory.
- E: rough DeepSeek-V3 token cost from logged prompt/response tokens was about `$0.18`; provider cache logs showed `cache_read_tokens=51840`, `cache_write_tokens=345940`.

Specific Iteration 010 gates:

- `not_x_but_y` no longer blocked the writer. Final meta has only one deterministic lint issue: `short_chapter_length` warning.
- `polish_applied=false` because the final in-loop writer review approved; this respects the trigger rule that polish only runs when the final result is still Reject.
- `lint_blocked_reviews=[]` because deterministic lint did not hard-block after thresholding. This is acceptable for this run and confirms the bypass safety was not needed.
- Reviewer keyword scan over snapshot reviewer JSON found zero hits for `风格` / `节奏` / `含蓄` / `言外之意` / `设定说明`. That means P5 did not provide evidence that reviewer feedback explicitly referenced the style-example axis.

Debate side result: decisions have 5 votes, 30 `agent_votes`, 5 fallback ballots, `for` lengths `[3, 3, 4, 5, 5]`, and `against` lengths `[2, 2, 1, 0, 0]`.

Conclusion: Iteration 010 fixed the three engineering bottlenecks from Iteration 009: `not_x_but_y` no longer causes a hard lint loop, reviewer signal is collected, and polish stays correctly gated. The remaining failure is length: the chapter is still under the 3000 Chinese-character hard floor despite 3 write attempts and reviewer approval. Next likely target is chunked writing or an explicit expansion pass keyed to `short_chapter_length`.

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [config/linter.yaml](../../config/linter.yaml) | `not_x_but_y` thresholds |
| [src/linter.py](../../src/linter.py) | thresholded `not_x_but_y`, `anchor`, cumulative `count` |
| [src/schemas.py](../../src/schemas.py) | `LintIssue.anchor`, `LintIssue.count` |
| [src/writer.py](../../src/writer.py) | anchored feedback, polish pass, shadow review |
| [src/reviewer.py](../../src/reviewer.py) | opt-in reviewer execution despite lint errors |
| [config/agents.yaml](../../config/agents.yaml) | `polish_pass`, `review_during_lint_block` |
| [tests/test_linter.py](../../tests/test_linter.py) | threshold and anchor tests |
| [tests/test_writer.py](../../tests/test_writer.py) | polish and shadow review tests |
| [docs/iterations/iteration_010_polish_and_linter_thresholds.md](./iteration_010_polish_and_linter_thresholds.md) | new iteration record |
| [docs/iterations/README.md](./README.md) | add index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | add Iteration 010 handoff |

## 不在本轮范围

- Running P5 true-model smoke before user confirmation.
- Chunked writing.
- Generalization axis work: workspaces, multilingual splitting, persona abstraction, or independent mode.
- Reviewer prompt tuning beyond collecting real reviewer data.
- Thresholding other lint rules before real-model evidence says which ones are too strict.
- DeepSeek cache-read follow-up.

## Notes

Next action after this commit:

1. User confirms `可以跑了`.
2. Run `bash scripts/write_smoke.sh`.
3. Analyze the new snapshot and log.
4. Update this document's Acceptance Result with true-model numbers and D4 placeholder.
5. Commit `Iteration 010: record write smoke results`.
