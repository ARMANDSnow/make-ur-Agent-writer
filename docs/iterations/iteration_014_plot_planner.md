# Iteration 014 - Plot Planner + Multi-Provider LLM Support

## Context

Iteration 013 proved that the project can write two connected chapters, but the plot direction was still too open-ended. The debate outline constrained theme and ending direction, while the writer still decided concrete chapter events during generation. That makes long-form continuation expensive and hard to steer.

This iteration adds a chapter-level plot planner: a stronger planner model produces an editable `outputs/debate/chapter_plan.json`, and the writer treats each chapter plan as a hard execution contract.

## Plan

P1. Add task-level LLM routing fields so `plot_planner` can use `PLANNER_API_KEY` and `PLANNER_BASE_URL` while existing writing tasks keep their `OPENAI_*` route.

P2. Add `src/plot_planner.py` and `ChapterPlan` / `ChapterPlanItem` schemas.

P3. Add `python3 main.py plan-chapters --chapters N [--force]`.

P4. Inject the matching chapter plan into writer prompts, with priority `rolling_summary > chapter_plan > outline`.

P5. Make `scripts/write_book.sh` require `chapter_plan.json` for multi-chapter runs, with `--no-plan` as an explicit bypass.

P6. Add six focused mock tests for planner generation, writer injection, backward compatibility, LLM env routing, and preflight env checks.

P8. Add this iteration record, update the iteration index, and append the handoff.

## Acceptance

| # | Item | Target |
|---|------|--------|
| A1 | Unit tests | `python3 -m unittest discover -s tests` passes with 126 tests, under 5 seconds |
| A2 | Verify | `bash scripts/verify.sh` exits 0 and new LLM log rows remain mock-only |
| A3 | Preflight | `python3 main.py preflight` reports warn / FATAL none |
| B1 | LLMClient routing | task-level `api_key_env` / `base_url_env` are honored |
| B2 | Plot planner mock | mock planner writes a complete five-chapter `chapter_plan.json` |
| B3 | Writer plan injection | prompt contains `本章计划（必须严格遵守）`, `opening_scene`, and `key_events` |
| B4 | Writer fallback | missing chapter plan keeps outline-only write compatibility |
| B5 | Preflight planner env | missing planner key is FATAL in real-model mode |
| C1-D7 | True planner/write smoke | Pending user confirmation and chapter plan editing |
| F1-F3 | Docs | Iteration doc, README index, and handoff are updated |

## Implementation Notes

- `config/models.yaml` now has a `plot_planner` task using `openai/claude-opus-4-5`, `PLANNER_API_KEY`, and `PLANNER_BASE_URL`.
- `get_model_config()` now supports per-task `api_key_env` and `base_url_env`. `OPENAI_MODEL=mock` still globally forces mock mode for tests and verify.
- Non-mock task routing now prefers an explicit task model over global `OPENAI_MODEL`, so planner can use its own model while existing extract/compress/debate/write/review tasks inherit the existing default route.
- `src/plot_planner.py` reads the debate outline, optional entity state, style examples, and manual facts, then writes `outputs/debate/chapter_plan.json`.
- Mock planner output is fixed to five placeholder chapters so tests and local engineering validation never need a real planner call.
- Writer prompts now include `## 本章计划（必须严格遵守）` when a plan exists. The prompt explicitly states `已写章节回顾/上一章结尾状态 > 本章计划 > 辩论大纲`.
- `scripts/write_book.sh` now checks for `outputs/debate/chapter_plan.json` unless the caller passes `--no-plan`.

## Acceptance Result

Engineering validation completed for P1-P6 + P8:

```bash
python3 -m unittest discover -s tests
# Ran 126 tests in 2.051s, OK

bash scripts/verify.sh
# Ran 126 tests in 2.071s, OK; script exited 0

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN: tokenizer fallback for configured real models and longest-chapter context warning
```

`logs/llm_calls.jsonl` tail after verification was mock-only (`model="mock"`). LiteLLM local routing sanity returned `('claude-opus-4-5', 'openai', None, None)` for `openai/claude-opus-4-5`.

True-model planner/write smoke ran after user confirmation and manual `chapter_plan.json` review:

```bash
python3 main.py plan-chapters --chapters 5
# chapter_plan.json written: 5 chapters

cp -r outputs/drafts/snapshots/20260519_152801 /tmp/iter013_snapshot_backup
python3 main.py write --chapters 1 --resume-from 3 --force
python3 main.py review-chapter 3
```

Snapshot: `outputs/drafts/snapshots/20260522_232617/`.

| Item | Result |
|------|--------|
| C1 chapter plan | Passed: `outputs/debate/chapter_plan.json` contains 5 chapters |
| C2 planner call | Passed after one sandbox/network failure: real planner log has `model=openai/claude-opus-4-5`, status `ok`, prompt 9,579 / response 2,173 tokens |
| D1 key events | 待用户评分; local grep found evidence for 3/3 planned chapter 3 key events |
| D2 chapter 3 length | Passed: 6,912 Chinese chars |
| D3 opening scene match | 待用户评分; opening is the tactical meeting around the deep-sea coordinate, but user should judge exact scene fidelity |
| D4 user self-review | 待用户评分 |
| D5 cost | Planner logged prompt 9,579 / response 2,173 tokens, expected around `$1.5`; writer/reviewer block logged 159,890 prompt / 20,638 response tokens across 12 ok calls plus one sandbox/network error, exact bill left to provider console |
| D6 failure residue | Passed: `data/extraction_failures/` is empty |
| D7 snapshot | Passed: snapshot contains chapter 3, meta, proposals, reviews, debate artifacts, and `chapter_plan.json` |

Chapter 3 plan key-event check:

| Planned key event | Local evidence in `chapter_03.md` |
|---|---|
| Finch/Fingerel shows decrypted data: Chu Zihang's coordinate points to a deep-sea trench, with frequent non-official signal access and Black Swan Harbor archive overlap | Appears: lines mention Fingerel presenting the coordinate, heat/signal data, Black Swan Harbor archive comparison, three-month access, and six non-official signal sources |
| Zero joins as Executive Department special delegate with anonymous intelligence from "the boss" about an unclosed Nibelungen rift expanding | Appears: Zero enters the meeting, brings "boss" intelligence, and states the rift is slowly expanding near the coordinate |
| Lu Mingfei later asks Zero about "the boss" and the text message; Zero says the deal is not over, but this time he is not looking for him | Appears nearly verbatim: Zero tells him "交易还没结束，但这次不是他找你" |

Smoke caveats:

- The current runtime `rolling_chapter_summary.json` had a mock chapter 1 summary from engineering verification plus the true chapter 2 summary. This smoke proves chapter-plan injection and event adherence, but it is not a perfectly clean continuation from the iter 013 two-chapter runtime state. The original iter 013 snapshot was backed up at `/tmp/iter013_snapshot_backup`.
- Writer-internal meta approved chapter 3 (`verdict=Approve`, `needs_human_review=false`, `rewrite_count=0`, `polish_applied=true`). Standalone `review-chapter 3` rejected before agent review because deterministic lint found 8 `not_x_but_y` errors, so `agent_reviews=[]` in `outputs/reviews/chapter_03.review.json`.

## 文件变更汇总

| File | Change |
|------|--------|
| [src/plot_planner.py](../../src/plot_planner.py) | New chapter-level plot planner |
| [src/config.py](../../src/config.py) | Add task-level env routing and preserve mock test isolation |
| [src/llm_client.py](../../src/llm_client.py) | Add mock `ChapterPlan` JSON response |
| [src/preflight.py](../../src/preflight.py) | Validate env and provider routing across all tasks |
| [src/writer.py](../../src/writer.py) | Load and inject chapter plans as writer constraints |
| [src/schemas.py](../../src/schemas.py) | Add `ChapterPlanItem` and `ChapterPlan` |
| [config/models.yaml](../../config/models.yaml) | Add `plot_planner` task |
| [main.py](../../main.py) | Add `plan-chapters` subcommand |
| [scripts/write_book.sh](../../scripts/write_book.sh) | Add plan existence guard and `--no-plan` bypass |
| [tests/test_plot_planner.py](../../tests/test_plot_planner.py) | New planner tests |
| [tests/test_writer.py](../../tests/test_writer.py) | Add chapter plan prompt and fallback tests |
| [tests/test_llm_client.py](../../tests/test_llm_client.py) | Add task env routing test |
| [tests/test_preflight.py](../../tests/test_preflight.py) | Add planner key FATAL test |
| [docs/iterations/README.md](./README.md) | Add iteration 014 index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | Append iteration 014 status and next candidates |

## 不在本轮范围

- Running `plan-chapters` before user confirmation.
- Running chapter 3 smoke before the user edits or approves `chapter_plan.json`.
- Fully automatic `write_book.sh --auto` mode.
- Chapter failure resume/retry beyond existing `--resume-from`.
- Workspace abstraction and cross-book generalization.
- Auto-bootstrap of entity graph, global facts, or continuation anchor.
- Web UI editing for `chapter_plan.json`.

## Notes

- `.env` was not edited.
- Runtime outputs under `outputs/`, `logs/`, and ignored `data/` files are not committed.
- The planner route is intentionally OpenAI compatible and configured only through generic planner env names.
- The first commit for this iteration covers engineering P1-P6 + P8 only. The true planner/write smoke will be recorded in a follow-up commit after user confirmation.
