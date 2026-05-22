# Agent Handoff

## Current Status

- Project: Dragon Raja AI Continuer MVP.
- Default mode: mock model, no API key required.
- Original source texts in `小说txt/` must not be modified.
- Recovery anchor: this file plus the test suite.

## Iteration Results

### Iteration 1-5 Implementation

- Added operator observability CLI:
  - `python3 main.py status`
  - `python3 main.py manifest-report`
  - `python3 main.py review-summary`
- Added extraction resume hardening:
  - persistent rolling summaries under `data/rolling_summaries/`
  - failure files under `data/extraction_failures/`
  - `python3 main.py retry-failures`
- Added global manual facts:
  - `data/manual_overrides/global_facts.json`
  - injected into compress, debate, write, and review prompts
- Added LLM hardening:
  - retry/backoff config
  - JSON repair path
  - lightweight `logs/llm_calls.jsonl`
  - `python3 main.py estimate-cost`
- Added fixed verification entrypoint:
  - `bash scripts/verify.sh`
- Added report snapshot guard:
  - `python3 main.py check-reports`
  - `python3 main.py check-reports --update`
  - `scripts/verify.sh` now fails if generated Markdown reports drift from JSON inputs.
- Added manifest integrity guard:
  - `python3 main.py check-manifest`
  - validates required fields, duplicate chapter IDs, line ranges, missing normalized files, and same-file overlaps.
- Added real-model hardening A+B1+C1:
  - rolling summaries use sentence-boundary tail trimming and config-limited history.
  - LLM logs include `request_hash`, prompt/response chars, prompt/response tokens, token method, and provider cache token fields.
  - LLM context overflow raises `LLMContextOverflowError` before making real calls.
  - long extract chapters chunk into front/middle/end windows and merge only after all chunks succeed.
  - reviewer issues can carry `rule_id`, `severity`, and `anchor`; writer feeds reject feedback into rewrites and stops at `max_review_attempts`.
  - writer marks stable system/knowledge/outline prompt segments for ephemeral prompt cache and downgrades if provider rejects cache metadata.
- Added real-model preflight:
  - `python3 main.py preflight`
  - `scripts/real_smoke.sh`
  - checks env, context limits, failure residue, rolling/extracted consistency, chunk trigger, cache provider support, global facts, and recent token logs without calling a remote model.
- Renamed writer attempt config:
  - `config/agents.yaml` now uses `max_review_attempts` for total attempts.
- Iteration 004 cleanup:
  - `max_review_attempts` is now a hard requirement; both `src/writer.py` and `python3 main.py preflight` raise/FATAL when the key is missing or non-positive.
  - `data/chapter_manifest.json` entries carry a `confidence` float in [0, 1] computed deterministically from heading pattern, char_count and dedup risk zone (see `src/chapter_splitter.py:_heading_confidence`).
  - `python3 main.py check-manifest` and `python3 main.py preflight` both surface low-confidence chapters (threshold < 0.6).
- Iteration 005 debate vote upgrade:
  - `src/schemas.py` now has `AgentVote`; debate decisions carry `aggregation_method: "majority"` and per-vote `agent_votes`.
  - `python3 main.py debate` keeps the six free-text debate rounds, then writes a structured `裁决投票` audit round to `outputs/debate/debate_log.jsonl`.
  - `build_decisions(..., agent_ballots=...)` explicitly recomputes `for` / `against` from agent ballots and marks `[平票]` or `[多数反对]` in `result` when needed.
  - `scripts/debate_smoke.sh` was added and verified in mock mode. Real DeepSeek extract smoke is still blocked until the user writes a rotated key into `.env`.
- Iteration 006 provider routing + debate real smoke:
  - `python3 main.py preflight` now FATALs when LiteLLM cannot resolve a non-mock model provider, catching bare `deepseek-chat` before any remote call.
  - Correct DeepSeek routing is `OPENAI_MODEL=deepseek/deepseek-chat`.
  - User-confirmed local `data/manual_overrides/global_facts.json` placeholder facts were used for debate smoke; this file remains ignored and local.
  - Real `bash scripts/debate_smoke.sh` completed with approved network access; 48/48 DeepSeek calls were `ok`, final preflight was warn with no FATAL.
  - Important observed failure: ballot JSON responses were `{"ballots": []}` for all 6 agents, so `agent_votes` were filled as `(missing)` abstain and final `for` / `against` stayed empty. Treat this as the next debate prompt hardening target.
  - Cache observation: `cache_write_tokens` increased but `cache_read_tokens` stayed 0.
- Iteration 007 test isolation + ballot hardening:
  - `python3 -m unittest discover -s tests` is now protected from `.env` real-model leakage; tests force `OPENAI_MODEL=mock` and `src/config.py` skips dotenv during unittest discovery.
  - `bash scripts/verify.sh` explicitly exports `OPENAI_MODEL=mock` and unsets `OPENAI_API_KEY` / `OPENAI_BASE_URL`; verify log delta was mock-only.
  - `_collect_agent_votes` now gives the model a numbered question list, requires ballots length to strictly equal question count, forbids empty arrays, and retries once before `(missing-after-retry)` fallback.
  - `scripts/debate_smoke.sh` saves `outputs/debate/snapshots/<ts>/` so true-model outputs survive later mock runs.
  - DeepSeek cache note added at `docs/notes/deepseek_cache_2026_05.md`; two identical cached calls still logged `cache_read_tokens=0`.
  - P6 true-model debate rerun completed: `logs/debate_smoke_20260514_205954.log`, snapshot `outputs/debate/snapshots/20260514_205954/`.
  - Result: 3/6 agents returned complete non-fallback ballots, all 4 votes have nonempty `for` lists, and the final 50 DeepSeek calls were 50/50 `ok`. Remaining issue: 3 agents returned near-correct JSON without `position`, causing `(parse_failed)` abstain.
- Iteration 008 ballot field repair + true-model write smoke:
  - `_collect_agent_vote_json` now uses `complete_text` + `extract_json_object` + `_repair_ballot_dict` instead of pydantic-validating directly into `AgentVoteBallot`.
  - Missing or invalid `position` is repaired from common alias fields (`answer`, `preference`, `verdict`, `vote`) or inferred from agree/reject language in `reason`.
  - JSON extraction/parsing errors still use `(parse_failed)`; incomplete parsed ballots still retry once and then use `(missing-after-retry)`.
  - `review_text` now repairs missing review `agent_name` before `AgentReview` validation; this was exposed by the first true-model review attempt.
  - `write_chapters` now persists rejected/lint-failed drafts as `chapter_XX.md` plus meta with `needs_human_review=true`, instead of leaving only a truncated failure preview.
  - Added `scripts/write_smoke.sh` for the gated true-model chain: preflight → compress → debate → write 1 chapter → review → status → estimate-cost → preflight, with snapshots under `outputs/drafts/snapshots/<ts>/`.
  - Local mock-only acceptance passed before the true run: `python3 -m unittest discover -s tests` ran 85 tests OK, `bash scripts/verify.sh` ran 85 tests OK, and `python3 main.py preflight` reported warn with FATAL none. Post-repair targeted tests ran 27 tests OK.
  - True-model result: initial `bash scripts/write_smoke.sh` wrote `logs/write_smoke_20260514_214854.log` but exited during standalone review due missing `agent_name`; after repairs, resumed write/review without re-running debate.
  - Final snapshot: `outputs/drafts/snapshots/20260514_220808/`. Debate produced 42 log items, 6/6 complete non-fallback ballot agents, 2 decisions with `for` lengths `[6, 6]`. Draft `chapter_01.md` is 1825 chars; meta has `rewrite_count=1`, `needs_human_review=true`, 7 reviewer outputs, and 16 structured issues. Measured DeepSeek block was 67/67 `ok`; `data/extraction_failures/` stayed empty.
- Iteration 009 writing quality surge:
  - Added `src/style.py::load_style_examples`, reading local `data/style_examples/*.md` except README and joining sorted examples for prompt injection.
  - Added tracked `data/style_examples/README.md` with instructions; real source excerpts must remain local ignored files.
  - Writer prompt now injects style examples, optional `continuation_anchor`, target length 3500-5500 Chinese chars, and writes `chinese_char_count` into meta/failure reports.
  - Debate decisions/outline prompts now receive non-empty `continuation_anchor`; outline prompt also receives style examples.
  - Linter has `short_chapter_length`: under 2500 Chinese chars is error, 2500-3499 warning, 3500+ clean.
  - `config/agents.yaml` now has `max_review_attempts=3`; `config/models.yaml` has `write.max_tokens=8000`. Empty `continuation_anchor` still WARNs in preflight, but the P6 run used a filled local anchor.
  - P1-P5 mock acceptance passed before P6: 92 unit tests OK, `scripts/verify.sh` mock-only, and empty-anchor preflight WARN tested.
  - P6 true-model smoke ran on 2026-05-17 after user confirmation. Snapshot: `outputs/drafts/snapshots/20260517_145845/`; log: `logs/write_smoke_20260517_145845.log`.
  - Result: script exited 0, DeepSeek increment was 49/49 `ok`, `data/extraction_failures/` stayed empty, and rough logged-token cost was about `$0.16`.
  - Draft length improved to 3478 total chars / 2924 Chinese chars, but missed the `>=3000` Chinese-char hard floor. Writer used all 3 attempts and persisted a human-review draft with `rewrite_count=2`, `needs_human_review=true`.
  - Blocking issue: deterministic linter rejected the final draft for 6 `not_x_but_y` errors plus 1 `short_chapter_length` warning; standalone review did not produce true reviewer-agent issues because the draft was already linter-rejected.
  - Debate side produced 42 log rows, 2 final votes, 12 `agent_votes`, 10 non-fallback ballots, 2 fallback ballots, `for` lengths `[4, 5]`, and `against` lengths `[0, 0]`.
- Iteration 010 linter thresholds + polish + reviewer bypass safety:
  - `not_x_but_y` is now thresholded in `config/linter.yaml`: 0-2 hits no issue, 3-4 warning, 5+ error.
  - Every deterministic lint issue now carries an `anchor`; cumulative `not_x_but_y` issues also carry `count`.
  - Writer feedback now includes lint rule, count, and anchor, and the writer system prompt explicitly limits repeated `not_x_but_y` / `not_x_but_y`-style contrast sentences.
  - `config/agents.yaml` now has `polish_pass: true` and `review_during_lint_block: true`.
  - `write_chapters` runs one terminal `_polish_draft` call after the normal rewrite budget is exhausted and the draft is still Reject; polish output is persisted without a recursive review loop.
  - Meta/failure reports now include `polish_applied`, `polish_diff_stats`, and `lint_blocked_reviews`.
  - `review_text` has an opt-in `run_agents_on_lint_error=True` path so writer can collect shadow reviewer signal while deterministic lint still blocks the draft; default reviewer behavior is unchanged.
  - P5 true-model smoke ran on 2026-05-17 after user confirmation. Snapshot: `outputs/drafts/snapshots/20260517_155018/`; log: `logs/write_smoke_20260517_155018.log`.
  - Result: script exited 0, DeepSeek increment was 76/76 `ok`, `data/extraction_failures/` stayed empty, and rough logged-token cost was about `$0.18`.
  - `not_x_but_y` no longer blocked the writer. Final meta has only `short_chapter_length` as a warning, not an error.
  - Writer meta says `verdict=Approve`, `needs_human_review=false`, `rewrite_count=2`, `chinese_char_count=2694`, `polish_applied=false`, and `lint_blocked_reviews=[]`.
  - Reviewer signal is now available: writer in-loop meta has 7 `agent_reviews`, all `Approve`; standalone review has 7 reviewer outputs with 6 `Approve` and 1 `Reject`.
  - Remaining failure: D1 still misses the 3000 Chinese-character hard floor (`2694`). Reviewer keyword scan for `风格` / `节奏` / `含蓄` / `言外之意` / `设定说明` found zero hits, so P5 did not prove reviewer feedback was explicitly style-example-aware.
- Iteration 011 entity graph + consistency reviewer + polish length floor:
  - Added optional `data/entity_graph.json` support through `src/entities.py`; missing graph returns `{}` and prompt injection degrades to empty state.
  - Added tracked `data/entity_graph.example.json` as schema v2 placeholders. It has `_meta.note`, per-entity `tags`, optional `description`, and intentionally contains no plot content or quoted source text.
  - Entity rendering now outputs entity list, automatic shared-tag reverse index, and active relationship state; only tags shared by at least two entities appear in the reverse index.
  - Writer stable prompt context now includes active entity relationships when present and explicitly requires role interactions and relationship descriptions to obey current active states.
  - Debate outline generation receives the same entity-state block; agent ballot prompts remain unchanged.
  - Reviewer prompts now receive entity state after global facts, and `config/agents.yaml` has an eighth review agent: `关系一致性`.
  - Polish now runs when enabled and the final draft is lint-blocked, reviewer-rejected, or under 3000 Chinese characters; short drafts get an expansion instruction targeting 3500-5500 Chinese characters.
  - User still owns `.env` model switching to `deepseek/deepseek-v4-pro`; do not run `scripts/write_smoke.sh` until the user fills `data/entity_graph.json` and replies `可以跑了`.
- Iteration 012 reviewer JSON robustness + debate fallback + consistency strict:
  - `review_text` now catches unparseable reviewer responses at the per-agent JSON extraction point, logs `review/json_parse_fallback`, writes a structured Approve fallback, and returns `_fallback_reason="(parse_failed)"` instead of crashing standalone review.
  - `AgentReview` now accepts optional `comparison_checklist` so the relationship-consistency reviewer can return explicit comparison evidence.
  - `关系一致性` reviews now have a local guard: if the model returns pure Approve with both `issues=[]` and `comparison_checklist=[]`, the result becomes a visible Reject issue with `rule_id=relationship_checklist_missing`.
  - `build_decisions` now detects empty LLM `votes`, logs `debate/votes_empty_fallback`, asks for loose legacy-style votes, parses flexible `for` / `against` aliases, and falls back to placeholder abstain-style review votes only if needed.
  - `config/agents.yaml` strengthens only the `关系一致性` reviewer: it must output a `对照清单`, compare draft interactions to active entity relationships, and may not produce an empty pure Approve without explaining the comparison process.
  - Added focused tests for review fallback, debate empty-votes fallback, loose legacy vote parsing, relationship prompt requirements, relationship checklist enforcement, and writer shadow-review compatibility.
  - Engineering validation after the guard: 112 unit tests OK, `bash scripts/verify.sh` OK, and `python3 main.py preflight` reported warn with FATAL none.
  - True-model `bash scripts/write_smoke.sh` ran after user confirmation on 2026-05-19. Snapshot: `outputs/drafts/snapshots/20260519_103436/`; log: `logs/write_smoke_20260519_103436.log`.
  - Smoke result: script exited 0, final preflight warn with FATAL none, snapshot auto-generated, `data/extraction_failures/` empty, approved network DeepSeek block 83/83 ok.
  - Debate fix held: `debate_decisions.json` has 3 votes, each with 6 agent ballots (`for` lengths `[6, 6, 6]`, `against` `[0, 0, 0]`).
  - Review crash fix held: standalone review completed. However the true `关系一致性` reviewer still returned pure empty Approve, so D3 failed for the smoke artifact; this directly triggered the local `relationship_checklist_missing` guard described above.
  - Draft result: 3921 Chinese chars, `rewrite_count=2`, `polish_applied=true`, but meta is still `Reject` / `needs_human_review=true` because deterministic lint reports repeated `not_x_but_y` errors and `name_drift` warnings. User self-review is still pending.
- Iteration 013 multi-chapter architecture engineering:
  - Added `src/chapter_summary.py` and runtime `outputs/drafts/rolling_chapter_summary.json` for per-chapter `{summary, key_events, ending_state}` accumulation.
  - Writer prompts no longer depend on raw previous-draft tail; they inject rendered recent chapter context, previous ending state, and an explicit opening-transition instruction when rolling state exists.
  - `write_chapters` now supports `resume_from` so `python3 main.py write --chapters 1 --resume-from N` can write one specific chapter for chapter-boundary workflows.
  - Added post-write `_summarize_chapter` and `_propose_entity_advance` hooks. Mock mode returns fixed summary data and empty proposals; real mode writes proposal JSON under `outputs/drafts/chapter_NN.entity_advance_proposals.json`.
  - Added `src/entity_advance.py`, `src/cli_apply_advance.py`, and `python3 main.py apply-advance --chapter NN --proposal-idx ... [--confirm]`. Dry-run prints a diff; `--confirm` flips old relationship timeline nodes inactive and appends the selected active state.
  - `review_text` now has `enforce_relationship_checklist=False` by default for compatibility; `main.py review`, `review-chapter`, and writer-internal review enable it.
  - Added `scripts/write_book.sh` for gated multi-chapter smoke. It skips existing chapters, writes one missing chapter, pauses before the next chapter for user apply-advance, and snapshots after all requested chapters exist.
  - Engineering validation: 120 unit tests OK, `bash scripts/verify.sh` exited 0 with mock-only new LLM logs, and `python3 main.py preflight` reported warn with FATAL none.
  - True-model `bash scripts/write_book.sh 2` ran after user confirmation on 2026-05-19. Chapter 1 run paused as designed; chapter 1 proposals were empty, so the user replied `继续` without applying advances; chapter 2 then completed and snapshot was saved at `outputs/drafts/snapshots/20260519_152801/`.
  - Smoke result: `chapter_01.md` has 4331 Chinese chars and `chapter_02.md` has 3765 Chinese chars. Both writer meta files have `verdict=Approve`, `needs_human_review=false`, `rewrite_count=0`, and no failures.
  - Continuity signal held: chapter 2 opens on the flight descending into Chicago and carries forward chapter 1's airport departure, the coin, and the "continue living" state.
  - DeepSeek approved block after the initial sandbox error was 38/38 ok (`write=6`, `review=32`), with logged prompt 375,949 / response 43,155 / cache_read 273,920 / cache_write 102,029 tokens.
  - Caveats for follow-up: chapter 1 entity proposal output was malformed and fell back to `proposed_advances=[]`, so C2/D3 relationship-advance workflow was not truly exercised; chapter 2 summary used local fallback because `ending_state` came back as an object instead of string.
- Iteration 014 plot planner + multi-provider LLM support:
  - Added task-level `api_key_env` / `base_url_env` support in model config and LLM client configuration. Existing write/extract/review tasks still inherit the current `OPENAI_*` route, while the new planner task uses `PLANNER_API_KEY` and `PLANNER_BASE_URL`.
  - Added `plot_planner` task in `config/models.yaml` with an OpenAI-compatible planner model route, 0.4 temperature, 16k max tokens, and 200k context limit.
  - Added `src/plot_planner.py` and `python3 main.py plan-chapters --chapters N [--force]`, writing `outputs/debate/chapter_plan.json`.
  - Added `ChapterPlanItem` / `ChapterPlan` schemas. Each chapter carries `title`, `opening_scene`, `key_events`, `relationships_in_play`, `ending_hook`, `target_chinese_chars`, and `plot_purpose`.
  - Mock planner mode writes a fixed five-chapter placeholder plan, keeping unit tests and verify fully local.
  - Writer now loads `outputs/debate/chapter_plan.json` when present and injects `## 本章计划（必须严格遵守）` into dynamic context. Prompt priority is explicit: already written rolling state > chapter plan > debate outline.
  - Missing plan remains backward compatible for direct `main.py write`; `scripts/write_book.sh` now requires a plan unless called with `--no-plan`.
  - P1-P6 + P8 engineering validation passed: 126 unit tests OK in 2.051s, `bash scripts/verify.sh` exited 0 with 126 tests OK in 2.071s and mock-only new LLM logs, and `python3 main.py preflight` reported warn with FATAL none.
  - True planner/write smoke ran after user confirmation. Planner wrote 5 chapters to `outputs/debate/chapter_plan.json`; the real planner log has `model=openai/claude-opus-4-5`, status `ok`, prompt 9,579 / response 2,173 tokens.
  - Chapter 3 smoke snapshot: `outputs/drafts/snapshots/20260522_232617/`. Chapter 3 has 6,912 Chinese chars; writer meta is `Approve`, `needs_human_review=false`, `rewrite_count=0`, `polish_applied=true`.
  - Local grep found evidence for all 3 planned chapter 3 key events: Fingerel's decrypted deep-sea coordinate/signal data, Zero bringing "boss" intelligence about an expanding Nibelungen rift, and Zero telling Lu Mingfei the deal is not over.
  - Standalone `review-chapter 3` rejected before agent review because deterministic lint found 8 `not_x_but_y` errors, so `agent_reviews=[]` in `outputs/reviews/chapter_03.review.json`. User scoring for D1/D3/D4 remains pending.
  - Caveat: current runtime `rolling_chapter_summary.json` had a mock chapter 1 summary from engineering verification plus the true chapter 2 summary, so the smoke proves plan adherence but not a perfectly clean iter 013 continuation state. The iter 013 snapshot was backed up at `/tmp/iter013_snapshot_backup`.
- Iteration records are kept under `docs/iterations/`.

## Validation Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
```

## Next Candidates

- Iteration 015: fuller `write_book.sh` automation, chapter failure resume/retry, and optional plan-aware entity advance workflow.
- Iteration 016: workspace concept for `workspaces/<book>/` and cleaner per-book runtime isolation.
- Iteration 017: auto-bootstrap entity graph, global facts, and continuation anchor from extracted data.
- Iteration 018+ generalization axis: multilingual splitter, agent persona abstraction, and `--mode independent` prompt flag.
- Reviewer prompt follow-up: decide whether to make reviewers explicitly evaluate style-example alignment and continuation-anchor adherence beyond the relationship checklist.
- DeepSeek cache follow-up: decide whether to add a preflight/cost-report WARN because cache writes are logged but reads may remain 0.
- Deferred candidates: B3 rolling summary 升级伏笔表、C2 增量 compress。
- Add a lightweight terminal UI or dashboard if operator reports become too verbose.
