# Iteration 013 - Multi-Chapter Architecture Engineering

## Context

Iterations 011 and 012 stabilized the single-chapter writer around the entity graph and the relationship-consistency reviewer, but the writer still had no durable multi-chapter memory. Its only chapter-to-chapter signal was a raw tail from the previous draft, while `entity_graph.json` remained static and chapter openings had no explicit transition contract.

This iteration moves the project from one-off chapter generation toward a controlled multi-chapter workflow: summarize each completed chapter, feed recent chapter state into the next prompt, propose relationship advances, and pause for user-approved entity graph updates between chapters.

## Plan

P1. Add a rolling chapter summary module and post-write chapter summarization hook.

P2. Replace raw previous-draft tail prompt injection with rolling context, previous ending state, and a chapter-opening transition instruction.

P3. Add entity advance proposal generation after each chapter, persist proposals, and add a dry-run-by-default `apply-advance` CLI that only writes `entity_graph.json` with `--confirm`.

P4. Add optional `enforce_relationship_checklist=True` to standalone review and make `main.py review` / `review-chapter` enforce it by default.

P5. Add `scripts/write_book.sh` for two-chapter smoke control with a chapter boundary pause for user approval.

P6. Add eight focused tests, bringing the suite to 120 tests.

P8. Add this iteration record, update the index, and append the handoff.

## Acceptance

| # | Item | Target |
|---|------|--------|
| A1 | Unit tests | `python3 -m unittest discover -s tests` passes with 120 tests, under 5 seconds |
| A2 | Verify | `bash scripts/verify.sh` exits 0 and remains mock-only |
| A3 | Preflight | `python3 main.py preflight` reports warn / FATAL none |
| B1 | Rolling summary | Load/save/append/render works; missing file gracefully degrades |
| B2 | Writer prompt | Prompt contains `已写章节回顾`, `上一章结尾状态`, and `本章开场衔接提示` when rolling state exists |
| B3 | Entity proposals | Post-write proposal file is produced and mock path returns an empty proposal list |
| B4 | Apply advance | Dry-run prints diff; `--confirm` switches old timeline active=false and appends active=true state |
| B5 | Review guard | Standalone review can enforce relationship checklist and reject empty pure Approve |
| C1-D6 | Two-chapter true smoke | Pending user confirmation and chapter-boundary intervention |
| F1-F3 | Docs | Iteration doc, README index, and handoff are updated |

## Implementation Notes

- Added `src/chapter_summary.py` with `load_rolling_summary`, `save_rolling_summary`, `append_chapter_summary`, `latest_ending_state`, and `render_rolling_context`. Runtime state lives at `outputs/drafts/rolling_chapter_summary.json`.
- Added `ChapterSummary`, `EntityAdvanceProposal`, and `EntityAdvanceProposalSet` schemas.
- `write_chapters()` now supports `resume_from`, reads recent rolling context before each chapter, and writes summary/proposal artifacts after the final draft or human-review draft is produced.
- `_summarize_chapter()` returns fixed mock data in mock mode; real mode asks the writer model for `{summary, key_events, ending_state}` and falls back to a local preview if parsing fails.
- `_propose_entity_advance()` returns no proposals in mock mode. In real mode it sees only active relationships and persists model-suggested changes to `chapter_NN.entity_advance_proposals.json`; it never mutates `entity_graph.json`.
- Added `src/entity_advance.py` and `src/cli_apply_advance.py`. `apply-advance` is dry-run by default and prints a unified diff; `--confirm` writes the selected proposal indexes.
- `review_text()` keeps `enforce_relationship_checklist=False` by default for compatibility, while `main.py review`, `review-chapter`, and writer-internal review use strict enforcement.
- Added `scripts/write_book.sh`; it skips existing chapters, writes one missing chapter, pauses before the next chapter, and snapshots artifacts only after all requested chapters exist.

## Acceptance Result

Engineering validation completed before true-model smoke:

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 120 tests in 2.143s, OK

bash scripts/verify.sh
# Ran 120 tests in 2.102s, OK; script exited 0

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN: tokenizer fallback for deepseek-v4-pro and longest-chapter context warning
```

New LLM log rows from the validation tail are mock-only (`model="mock"`).

True-model P7 is intentionally pending user confirmation. The chapter 1 smoke must not run until the user says `可以跑了`.

## 文件变更汇总

| File | Change |
|------|--------|
| [src/chapter_summary.py](../../src/chapter_summary.py) | New rolling chapter summary loader/renderer |
| [src/entity_advance.py](../../src/entity_advance.py) | New proposal persistence and user-approved apply logic |
| [src/cli_apply_advance.py](../../src/cli_apply_advance.py) | New CLI rendering wrapper |
| [src/writer.py](../../src/writer.py) | Add rolling prompt context, `resume_from`, post-write summary/proposal hooks |
| [src/reviewer.py](../../src/reviewer.py) | Add optional relationship checklist enforcement |
| [src/schemas.py](../../src/schemas.py) | Add chapter summary and entity advance schemas |
| [main.py](../../main.py) | Add `--resume-from`, `review-chapter`, and `apply-advance` |
| [scripts/write_book.sh](../../scripts/write_book.sh) | New gated multi-chapter smoke script |
| [tests/test_chapter_summary.py](../../tests/test_chapter_summary.py) | New rolling summary tests |
| [tests/test_entity_advance.py](../../tests/test_entity_advance.py) | New active relationship and apply tests |
| [tests/test_writer.py](../../tests/test_writer.py) | Add prompt and post-write artifact tests |
| [tests/test_reviewer.py](../../tests/test_reviewer.py) | Add standalone enforcement test |
| [docs/iterations/README.md](./README.md) | Add iteration 013 index entry |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | Append iteration 013 status and next candidates |

## 不在本轮范围

- Full automatic whole-book writing without chapter-boundary user intervention.
- Chapter plan generation from debate outline into N chapter beats.
- Failure resume/retry for partially failed chapter generation.
- Generalization axis: workspace abstraction, multilingual splitter, persona abstraction, independent mode.
- Running true-model smoke before explicit user confirmation.
- Automatically applying relationship advances without user review.

## Notes

- `.env`, `小说txt/`, and source text artifacts were not edited.
- Runtime files under `outputs/`, `logs/`, and local `data/entity_graph.json` remain ignored and outside the engineering commit.
- `apply-advance` is intentionally destructive only with `--confirm`; dry-run mode is the expected review step.
- P7 will be recorded after the user confirms true-model execution and manually chooses any chapter 1 relationship advances.
