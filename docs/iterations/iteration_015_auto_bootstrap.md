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

Cross-novel validation is intentionally pending. The next phase waits for the user to back up current runtime data, provide another Chinese novel txt, clear existing manual overrides, and reply `可以跑 init-book`.

## 文件变更汇总

| File | Change |
|------|--------|
| `src/auto_bootstrap.py` | New four-proposal bootstrap module |
| `src/cli_apply_bootstrap.py` | New dry-run/confirm apply workflow |
| `src/continuation_anchor.py` | New gitignored continuation-anchor loader with legacy fallback |
| `src/schemas.py` | Add bootstrap proposal schemas |
| `src/llm_client.py` | Add mock proposal responses |
| `src/writer.py` | Load continuation anchor through the new helper |
| `src/debater.py` | Load continuation anchor through the new helper |
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
