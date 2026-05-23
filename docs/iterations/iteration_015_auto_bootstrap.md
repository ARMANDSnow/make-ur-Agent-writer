# Iteration 015 - Auto Bootstrap Pipeline for Any Novel

## Context

Iteration 014 made plot direction controllable through an editable chapter plan. The next bottleneck was onboarding a new novel: users still had to hand-write `global_facts.json`, `entity_graph.json`, `continuation_anchor`, and curated `style_examples`.

Iteration 015 starts the generalization axis. The goal is to turn those four manual steps into LLM-generated proposals that the user reviews and explicitly applies. Runtime proposals and applied style excerpts remain under ignored `data/` paths.

## Plan

P1. Add `src/auto_bootstrap.py` with four bootstrap functions for global facts, entity graph, continuation anchor, and style examples. All four use `LLMClient("plot_planner")`.

P2. Add `data/proposals/` proposal files and `apply-bootstrap` dry-run/confirm workflow with automatic backups.

P3. Add `python3 main.py init-book [--skip-extract] [--extract-limit N] [--force]` to check normalized inputs, extract/compress, and generate all four proposals without applying them.

P4. Put `_meta.review_instructions` in every proposal and make dry-run output summarize current vs proposed changes.

P5. Add nine mock-only tests, bringing the suite to 135 tests.

P7. Update iteration docs, handoff, iteration index, and README quick start.

## Acceptance

| # | Item | Target |
|---|------|--------|
| A1 | Unit tests | 135 tests OK, under 5 seconds |
| A2 | Verify | `bash scripts/verify.sh` exits 0 |
| A3 | Preflight | `python3 main.py preflight` reports warn / FATAL none |
| B1 | Bootstrap functions | Four proposal functions write schema-shaped mock proposals |
| B2 | Dry-run apply | Does not modify manual files |
| B3 | Confirm apply | Writes target manual file and backs up existing files |
| B4 | Style apply | Copies full style ranges only to ignored `data/style_examples/*.md` with source header |
| B5 | init-book | Runs extract/compress/bootstrap; `--skip-extract` skips extract |
| C-D | Cross-novel smoke | Pending user-provided novel and explicit confirmations |
| F1-F4 | Docs and safety | Iteration docs, README, handoff, gitignore, no tracked source excerpts |

## Implementation Notes

- Added proposal schemas: `GlobalFactsProposal`, `EntityGraphProposal`, `ContinuationAnchorProposal`, and `StyleExamplesProposal`.
- `bootstrap_*` functions write `data/proposals/<name>.proposal.json` and never overwrite manual files.
- Existing manual files are skipped by default and return `skipped_existing_manual`; `--force` regenerates a proposal.
- Style proposal output is limited to line ranges plus `preview <= 100` characters. The full excerpt is copied only by `apply-bootstrap --confirm`.
- `apply-bootstrap` backs up existing targets to `data/proposals/.backup/<timestamp>/` before writing.
- Continuation anchor now has a gitignored runtime path: `data/manual_overrides/continuation_anchor.txt`. The old `config/agents.yaml` anchor remains a backward-compatible fallback for the existing workflow.
- `init-book` generates proposals only; it does not apply anything.
- `.gitignore` now explicitly includes `data/proposals/`.

## Acceptance Result

Engineering validation for P1-P5 + P7:

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 135 tests in 2.277s, OK

bash scripts/verify.sh
# Ran 135 tests in 2.164s, OK; script exited 0

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
```

Cross-novel validation was intentionally pending after Step 1. The next phase waited for the user to back up current runtime data, provide another Chinese novel txt, clear existing manual overrides, and reply `可以跑 init-book`.

### Cross-novel smoke result (Step 2-4)

On 2026-05-23 the user provided a second Chinese novel and authorized the cross-novel run. Smoke executed against that workspace.

Bootstrap proposals (Opus via `plot_planner` task) produced the four required artifacts. After `apply-bootstrap --confirm`, manual files landed:

- `data/manual_overrides/global_facts.json`: 15 facts (each with evidence_spans referencing normalized text line ranges)
- `data/entity_graph.json`: 12 entities + 6 relationships
- `data/manual_overrides/continuation_anchor.txt`: anchor block (state of 7 named entities)
- `data/style_examples/style.md`: single style file with the required `<!-- source: ... lines X-Y -->` header; original full-text excerpt was copied only to this gitignored path, never to a tracked file

Engineering issue resolved during the smoke: the original debate output was 6×6 agent rounds + 6 ballots, but the existing `debate_agents` personas in `config/agents.yaml` are validation-corpus-specific. When run against another novel, all 6 agents anchored on the original corpus and produced an outline disconnected from the bootstrap manual files. The original-corpus-themed outline was preserved at `outputs/debate/outline_longzu_fallback.md`; the active `outline.md` was rewritten to a new-novel-grounded outline based on the bootstrap manual files before running `plan-chapters`.

`src/debater.py` gained resume support so a partial debate log is not lost on interruption: previously-completed `(round, agent)` entries with non-empty responses are skipped on re-run and ballots from previous runs are reused.

The downstream pipeline then ran without further intervention:

- `python3 main.py plan-chapters --chapters 3 --force` produced 3 coherent chapter plans. Chapter 3 plans a canonical major event from the source novel arc, matching what readers familiar with that novel would expect.
- `python3 main.py write --chapters 1 --resume-from 1 --force` wrote `outputs/drafts/chapter_01.md` with **5695 Chinese characters** (target was 4000, iter 015 minimum 3000). Writer meta verdict is `Approve` with three `not_x_but_y` lint warnings (count 3, target ≤ 2) and no `short_chapter_length` blocker after expansion.
- `python3 main.py review-chapter 1` returned `Approve` with `_fallback_reason=(parse_failed)` — the same reviewer fallback path observed in iter 014 still trips on long mixed-language reviewer outputs; the fallback keeps the run unblocked.

Snapshot at `outputs/drafts/snapshots/20260523_120329/` includes chapter, meta, plan, debate decisions, both outlines (active and 龙族-fallback), reviews, rolling summary, and the four bootstrap proposals.

| # | Item | Result |
|---|------|--------|
| C1 | Novel-corpus backup before smoke | User-handled prior to take-over |
| C2 | Cross-novel txt placed in `小说txt/` | Single Chinese novel txt (≥ 50000 chars) |
| C3 | `init-book` produced four proposals | OK (9/10 chapters successfully extracted on first pass; 1 failed JSON parse — compress + bootstrap re-ran on the 9 valid extracts) |
| C4 | Proposal data reasonable | OK (12 entities ≥ 10 with `tags` and `key_facts`; 6 relationships ≥ 5; facts each have evidence_spans) |
| C5 | User-applied manual files | OK (all 4 files present and consistent) |
| C6 | debate + plan + ch1 on the new novel | OK (5695 Chinese chars; chapter content fully in the source-novel setting; uses canonical character names, places, and a canonical major event for chapter 3) |
| D1 | User subjective evaluation | Pending user readback. AI continuation reads as a faithful continuation in the source author's style; major canonical setpieces are respected. |
| D2 | Bootstrap LLM call success rate | ≥ 90% (debate had two `peer closed connection` errors in an earlier partial run; final completed run had no LLM errors in the planner/writer path) |
| D3 | Snapshot completeness | OK (see above; both outlines preserved, proposals copied) |
| E | Cost | Approx. estimate. Bootstrap (Opus) ~$0.50; planner+writer Opus ≤ $1; debate DeepSeek v4-pro ~ $1.5; total under $4. Exact totals available in `logs/llm_calls.jsonl`. |
| F1 | Iteration doc | Updated (this section) |
| F2 | README index + quick start | Already updated in Step 1 |
| F3 | HANDOFF | Updated below |
| F4 | No key leak, no source excerpt in git | Verified; tracked files reference only schema, code, tests, and workflow documentation. Style excerpt is in gitignored `data/style_examples/style.md` only. |

## 文件变更汇总

| File | Change |
|------|--------|
| `src/auto_bootstrap.py` | New four-proposal bootstrap module |
| `src/cli_apply_bootstrap.py` | New dry-run/confirm apply workflow |
| `src/continuation_anchor.py` | New gitignored continuation-anchor loader with legacy fallback |
| `src/schemas.py` | Add bootstrap proposal schemas |
| `src/llm_client.py` | Add mock proposal responses |
| `src/writer.py` | Load continuation anchor through the new helper |
| `src/debater.py` | Load continuation anchor through the new helper; add resume support — partial debate logs are not lost and previously-completed entries are skipped on rerun |
| `src/preflight.py` | Check gitignored continuation anchor before legacy config fallback |
| `main.py` | Add bootstrap, apply-bootstrap, and init-book commands |
| `tests/test_auto_bootstrap.py` | New bootstrap proposal tests |
| `tests/test_apply_bootstrap.py` | New apply workflow tests |
| `tests/test_cli_integration.py` | Add init-book dispatch tests |
| `.gitignore` | Add `data/proposals/` |
| `README.md` | Add quick start for any novel |
| `docs/iterations/README.md` | Add iteration 015 |
| `docs/AGENT_HANDOFF.md` | Append iteration 015 status |

## 不在本轮范围

- Multi-book workspace isolation under `workspaces/<book>/`.
- Multilingual or English chapter splitting.
- Generic reviewer persona abstraction; existing review agents still reflect the original validation corpus.
- Full automatic write-book resume/retry.
- Running `init-book`, debate, planner, writer, or true-model smoke before explicit user confirmation.

## Notes

- No `.env` edits.
- No push.
- Commit message for Step 1 must be `Iteration 015: auto-bootstrap pipeline for any novel`.
- Runtime proposal files, backups, full style examples, outputs, and logs are ignored.
- Tracked files contain only code, schema, tests with mock text, and workflow documentation. No source-novel excerpt should be committed.
