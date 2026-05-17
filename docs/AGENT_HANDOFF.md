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
- Iteration 010 linter thresholds + polish + reviewer bypass safety (P1-P4/P6 only):
  - `not_x_but_y` is now thresholded in `config/linter.yaml`: 0-2 hits no issue, 3-4 warning, 5+ error.
  - Every deterministic lint issue now carries an `anchor`; cumulative `not_x_but_y` issues also carry `count`.
  - Writer feedback now includes lint rule, count, and anchor, and the writer system prompt explicitly limits repeated `not_x_but_y` / `not_x_but_y`-style contrast sentences.
  - `config/agents.yaml` now has `polish_pass: true` and `review_during_lint_block: true`.
  - `write_chapters` runs one terminal `_polish_draft` call after the normal rewrite budget is exhausted and the draft is still Reject; polish output is persisted without a recursive review loop.
  - Meta/failure reports now include `polish_applied`, `polish_diff_stats`, and `lint_blocked_reviews`.
  - `review_text` has an opt-in `run_agents_on_lint_error=True` path so writer can collect shadow reviewer signal while deterministic lint still blocks the draft; default reviewer behavior is unchanged.
  - P5 true-model smoke has not been run. Wait for user to confirm `可以跑了`, then run `bash scripts/write_smoke.sh`, update the Iteration 010 Acceptance Result, and commit `Iteration 010: record write smoke results`.
- Iteration records are kept under `docs/iterations/`.

## Validation Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
```

## Next Candidates

- Iteration 010 P5: after user confirms budget/key readiness, run `bash scripts/write_smoke.sh` and record true-model results.
- If Iteration 010 P5 still misses D1/D3/D4, decide between chunked writing and reviewer prompt tuning using the new `lint_blocked_reviews` / `agent_reviews` evidence.
- Stage 3 generalization: workspace concept, multilingual splitter, agent persona abstraction, and `--mode independent` prompt flag.
- DeepSeek cache follow-up: decide whether to add a preflight/cost-report WARN because cache writes are logged but reads may remain 0.
- Deferred candidates: B3 rolling summary 升级伏笔表、C2 增量 compress。
- Add a lightweight terminal UI or dashboard if operator reports become too verbose.
