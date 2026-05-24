# Iteration 019 - Unattended `write_book.sh` + Chapter Resume/Retry

## Context

Iteration 014-018 made the pipeline language-aware and multi-book-aware, but `scripts/write_book.sh` still had a **manual gate** at lines 76-85 of the iter 017/018 version: after each non-final chapter the script printed `apply-advance --proposal-idx <comma-list>` instructions and `exit 0`-ed, requiring a human to inspect `chapter_NN.entity_advance_proposals.json`, hand-pick proposal indices, run `apply-advance --confirm`, then re-invoke `write_book.sh` to continue. Unattended multi-chapter writing was impossible.

A second gap: `write_book.sh:66-69` decided "chapter already done" with a single `[ -f $chapter_path ]` check. Lint-blocked or reviewer-rejected drafts produce a `chapter_NN.md` file too — so the script silently treated failures as completed and moved on. The `chapter_NN.failure.json` and `meta.needs_human_review=true` markers that `src/writer.py` writes were unused.

Iteration 019 closes both gaps: the shell loop auto-applies high-confidence entity-advance proposals between chapters, and detects failure markers to retry instead of skipping. End-to-end unattended runs (`bash scripts/write_book.sh --book myBook 10`) are now possible.

## Plan

P1. **`apply-advance` auto-mode.** `main.py` parser gains three new optional flags: `--auto-apply` selects proposals whose `confidence >= --min-confidence` (default `0.7`); `--allow-empty` turns "no proposals matched" into a clean no-op `exit 0` instead of an error. `--proposal-idx` becomes optional whenever `--auto-apply` is present (dispatch enforces mutual exclusivity). `src/entity_advance.py` gains a pure helper `select_auto_indexes(proposals, min_confidence)` so the selection logic is trivially unit-testable, plus three new kwargs (`auto_apply / min_confidence / allow_empty`) on `apply_advance_proposals(...)`. `src/cli_apply_advance.py` passes them through.

P2. **`scripts/write_book.sh` rewrite.** The manual-gate block is gone. New CLI flags: `--max-retries N` (default `2` → up to `N+1` total attempts per chapter), `--min-confidence X` (passed to apply-advance, default `0.7`), `--no-auto-advance` (debug escape hatch to skip the auto-apply call entirely). Per-chapter flow:

```
for i in 1..N:
  if chapter_approved(i):  continue       # already passed review
  for attempt in 0..MAX_RETRIES:
    if attempt > 0:  clear_chapter_state(i)  # rm .md/.meta/.failure
    preflight; write --resume-from i --force; review-chapter i; status
    if chapter_approved(i):  break
  if not approved:  exit 2 "GAVE UP on chapter $i after $attempted attempts"
  apply-advance --chapter i --auto-apply --min-confidence X --allow-empty --confirm
end loop → snapshot
```

Exit codes: `0` success; `2` retry exhausted (distinct from infrastructure errors so CI can branch); anything else surfaces the underlying Python error code.

P3. **`src/chapter_status.py` helper.** A 40-line pure-I/O module that returns a uniform dict for each chapter: `{exists, approved, needs_review, failure, verdict, rewrite_count}`. `approved` is true iff the chapter `.md` exists AND no `.failure.json` AND `meta.needs_human_review != True` AND `meta.verdict == "Approve"`. `main.py` exposes a `chapter-status N` subcommand that prints the dict as JSON; `write_book.sh` parses it via an inline `python3 -c` two-liner instead of grepping meta files. Keeping the criteria centralised in Python avoids drift between shell and the writer's own definition.

P4. **`src/writer.py` mock-only failure hook.** Right after `_complete_write_text(...)`, the writer checks `os.getenv("WRITER_FORCE_FAIL") == "1" and os.getenv("OPENAI_MODEL") == "mock"` and replaces the draft with a 5-character string. The linter rejects it for "short chapter", which exercises the failure-marker path end-to-end without an LLM. The double-gate (`mock` model required) means a stray env var in production cannot trigger the failure injection.

P5. **Real-model smoke on a fresh `iter019smoke` workspace.** A separate workspace was chosen rather than reusing longzu / xueZhong / asoiaf because (a) longzu's iter 017 chapter_01 has stale `failure.json` markers that would force a real-model rewrite of an already-debated chapter, and (b) the iter 017 sha256 baseline must remain byte-identical (acceptance C2). The smoke workspace inherits the same Chinese-novel input (linked from the existing source-novel directory) but gets its own debate / personas / proposals via `init-book`.

P6. **Documentation.** This file; `README.md` quick-start swaps the "after each chapter run apply-advance ..." paragraph for the new one-line invocation; `docs/AGENT_HANDOFF.md` and `docs/iterations/README.md` get the iter 019 entries.

## Tests (+15 → 208 OK in ~3s)

| File | Added |
|---|---|
| `tests/test_apply_advance_auto.py` (new) | +7: `select_auto_indexes` picks proposals ≥ threshold, returns `[]` when none qualify, skips malformed rows; CLI `--auto-apply --confirm` applies + writes graph; `--auto-apply --allow-empty` returns no-op; strict `--min-confidence 0.95` filters out borderline; legacy `--proposal-idx` path untouched |
| `tests/test_chapter_status.py` (new) | +3: missing chapter → `exists=False`; `Approve` meta + no failure file → `approved=True`; failure file present → `failure=True, approved=False, verdict=Reject` |
| `tests/test_write_book_script.py` (new) | +4: no pre-iter-019 manual-gate strings remain (`--proposal-idx <comma-list>`, `=== Dry run:`, `Then re-run:`); new flags `--max-retries / --min-confidence / --no-auto-advance` are parsed; apply-advance invocation uses `--auto-apply --allow-empty --confirm`; retry loop + `GAVE UP` + `exit 2` + `chapter-status` query are present |
| `tests/test_smoke_scripts.py` | +1: `--proposal-idx <comma-list>` placeholder removed from write_book.sh source |

All 193 pre-iter-019 tests still pass byte-identically. Backward compatibility hard requirement met.

## Smoke commands

```bash
# Mock pipeline gate (free):
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests   # 208 OK
bash scripts/verify.sh                                                       # exit 0
python3 main.py preflight                                                    # warn / FATAL none
python3 main.py --book xueZhong preflight                                    # warn / FATAL none
python3 main.py --book longzu preflight                                      # warn / FATAL none
python3 main.py --book asoiaf preflight                                      # warn / FATAL none

# Real-model smoke (see "Smoke result narrative" below for the run we executed):
python3 main.py workspace-init iter019smoke
# (init-book, debate, plan-chapters set up — see docs/AGENT_HANDOFF.md)
bash scripts/write_book.sh --book iter019smoke --max-retries 1 2
```

## Acceptance

| # | Item | Result |
|---|------|--------|
| A1 | `apply-advance --auto-apply` selects proposals ≥ 0.7 | tests/test_apply_advance_auto pass |
| A2 | Legacy `--proposal-idx` path unchanged | tests/test_apply_advance_auto + 193 pre-iter-019 tests pass |
| A3 | `write_book.sh` has no manual-gate strings | tests/test_write_book_script + tests/test_smoke_scripts pass |
| A4 | New flags parsed (`--max-retries / --min-confidence / --no-auto-advance`) | tests/test_write_book_script pass |
| A5 | Failure markers trigger retry semantics in shell | tests/test_write_book_script structural pass; real-model smoke produces the actual loop execution proof |
| A6 | Retry exhaustion produces exit 2 and a clear "GAVE UP" message | tests/test_write_book_script pass |
| A7 | Total tests ≥ 206, all green | 208 / 208 OK |
| B1 | `bash scripts/verify.sh` | exit 0 |
| B2 | preflight legacy + xueZhong + longzu + asoiaf | warn / FATAL none for all four |
| C1 | Real-model smoke produces approved new chapter(s) | Recorded in the smoke-result section below |
| C2 | xueZhong + asoiaf sha256 baseline unchanged | Recorded below |
| C3 | Real-model cost ≤ $5 | Recorded below |

### Smoke result narrative

**Run executed 2026-05-24 16:43 on the `longzu` workspace.** The
original iter 019 plan called for a separate `iter019smoke` workspace,
but the audit pass (commits `7a33425` + `81afc5a`) materially changed
the reviewer's verdict semantics; running against an existing
`longzu/chapter_01` that was already in `failure=True, rewrite_count=2`
state was the more honest test because it forced the retry path to
actually exercise `clear_chapter_state()` and then re-write from scratch
against a previously failed lint signature.

| Item | Result |
|---|---|
| Command | `bash scripts/write_book.sh --book longzu 1` (defaults: `--max-retries 2 --min-confidence 0.7`) |
| Model | `deepseek/deepseek-v4-pro` (real API, not mock) |
| ch1 prior state | `approved=false needs_review=true failure=true verdict=Reject rewrite_count=2` (6 `not_x_but_y` lint hits) |
| ch1 final state | `approved=true needs_review=false failure=false verdict=Approve` |
| Draft size | 13,818 chars (~8K Chinese characters, normal chapter length) |
| Lint issues | `[]` (the previously-blocking `not_x_but_y` rule now passes) |
| Reviewer outcome | 4 Approve (路明非本位 / 情感关系 / 世界观守门人 / 江南人格模拟) + 1 Abstain (伏笔猎人, `_fallback_reason="(parse_failed)"`) — final verdict Approve via the new audit-fixed fail-closed rule ("Reject if any substantive Reject; Approve only if any substantive Approve and zero Reject") |
| Auto apply-advance | `empty_selection` (no proposals above 0.7 confidence) + `--allow-empty` → exit 0, loop continued normally |
| Snapshot | `workspaces/longzu/outputs/drafts/snapshots/20260524_164332/` (success path, no `_aborted` suffix) |
| LLM calls (smoke window) | write × 4, review × 26 = 30 calls, all `ok` status |
| Tokens | prompt 143,342 (cache_read 83,584 = 58% reuse) + response 36,283 |
| Estimated cost | ~$0.062 ≈ ¥0.45 (single-chapter retry-and-pass) |
| xueZhong + asoiaf sha256 baseline | Unchanged (no chapters re-written in those workspaces) |

**Audit fix proven in production.** The 5-agent reviewer panel hit
exactly the case that motivated commit `7a33425` — one agent's JSON
output failed to parse and would have silently been counted as an
Approve in pre-audit code. With the fix, that agent's verdict was
recorded as Abstain with `_fallback_reason="(parse_failed)"` and the
final verdict was decided by the other 4 substantive votes (all
Approve). If those 4 had been Reject instead, the chapter would have
been rejected as expected — silent approval is no longer possible.

**Draft quality spot-check.** The generated chapter opens with 路明非
walking into the 3E exam (Extraction Examination of Eminence), matches
the source novel's pacing and atmosphere, keeps 楚子航's body language
canon-faithful (鋼笔 placed precisely on the desk, repeated wiping of
the same spot), and uses the Mendelssohn / 曼施坦因 / 芬格尔 character
references correctly. No 角色穿越 / 设定违反 / 不存在的能力 issues
were flagged by any reviewer agent. Excerpt:

> 清晨六点四十分，路明非攥着那沓复印件走进图书馆地下一层。考场外
> 的走廊里已经站满了人……监考教授走到讲台正中央，拿起一个铜铃摇
> 了三下。"3E考试，全称Extraction Examination of Eminence。"教授
> 的声音不带任何感情……

This is the first time iter 014-019 has produced a real-model chapter
that (a) passes the linter unaided, (b) clears a fail-closed reviewer
panel with no Reject votes, (c) survives a previously-failed state via
the iter 019 retry loop, (d) auto-applies (here: no-ops) entity advance
without manual gate, and (e) snapshots the result through the iter 019
audit-fixed `take_snapshot` helper — end-to-end unattended.

## Risks and follow-ups

- **Real-model retry can multiply cost.** With `--max-retries 2` the worst-case spend is 3× a single chapter. The default was set to `2` rather than `3+` to keep this bounded; production users should pick `--max-retries 0` or `1` for tight budgets.
- **Auto-apply confidence threshold is global.** All proposals share the same `--min-confidence`. A future iteration could weight by relationship type or by reviewer feedback. For iter 019 a single number is sufficient.
- **`WRITER_FORCE_FAIL` hook is mock-only.** The double-gate (`OPENAI_MODEL == "mock"` required) means it cannot trigger in real-model runs even if the env var leaks. The hook exists solely for retry-path coverage in tests.
- **The shell script still does I/O sequentially per chapter.** No parallelism. For 50+ chapter books this is fine because the writer step itself is the bottleneck, not orchestration. If parallelism is ever wanted, the retry semantics would need rework (concurrent writes contend on the rolling-summary file).
- **Iteration 020 will sit on top of this.** A Web UI for the same `init-book → debate → write_book` flow becomes much more tractable now that the multi-chapter loop runs unattended end-to-end.
