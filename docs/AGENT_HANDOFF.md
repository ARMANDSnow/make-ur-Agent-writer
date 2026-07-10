# Agent Handoff

## Current Status

- Project: Dragon Raja AI Continuer MVP.
- Default mode: mock model, no API key required.
- Original source texts in `小说txt/` must not be modified.
- Recovery anchor: this file plus the test suite.

### Aeloon 集成 → 权威文档 [`docs/AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md)

涉及 Aeloon 集成的迭代**先读 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md)**（唯一权威：三种部署法 / gateway 架构 / 已知坑 ①–④ / 进展时间线 §0.1）。本 handoff 不再重复集成细节，只留指针 + 最新状态。

- **时间线**：iter049（2026-06-10）插件 + MCP 双轨（workspace `.pth`，并入 main）→ 2026-06-16 bundled 内置法（快照分支 `dev/novel-ui`，§9）→ **PR #383（2026-06-19）bundled 进 `dev/ui`，已合入** → **PR #418（2026-06-20）Aeloon「小说续写」入口移到左侧栏「金融研究」下方（§10.3）**。
- **最新状态（2026-06-20）**：PR [#383](https://github.com/AetherHeart-AI/Aeloon-Pro/pull/383) 已合入 `dev/ui`（修了 ruff `extend-exclude novel_web` + pytest 命名空间包坑④）。入口按钮初版在概览页太隐蔽（长弹窗底部需滚动）→ **PR [#418](https://github.com/AetherHeart-AI/Aeloon-Pro/pull/418) 移到左侧栏（仿金融研究 `ScholarNavItem`，`window.open 127.0.0.1:8765` 新标签）**；rebase 到最新 dev/ui 解了与 #413 sidebar-polish 的冲突、CI 绿、mergeable。要真用仍需前端重建 + 起 8765 后端 + 配模型 key（详见 `AELOON_INTEGRATION.md` §10）。
- **dev/ui 既有前端测试红（与小说无关）**：`chat-layout` / `ChatCompose.pending-selector` / `ChatWorkspacePane`×2 共 4 个——陈旧单测（Agent 模式、发送/工作区面板等 UI 改了没更新测试），非功能 bug，`dev/ui` 无前端 CI 故没被拦；`repository` 那 2 个已被上游 9448bc8 修复。

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
  - Added per-task `api_key_env` / `base_url_env` support in model config and LLM client configuration. Existing write/extract/review tasks still inherit the current `OPENAI_*` route, while the new planner task uses `PLANNER_API_KEY` and `PLANNER_BASE_URL`.
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
- Iteration 015 auto-bootstrap pipeline for any novel:
  - Added `src/auto_bootstrap.py` with four proposal generators: global facts, entity graph, continuation anchor, and style examples. All use the existing `plot_planner` task route and write only ignored `data/proposals/*.proposal.json`.
  - Added proposal schemas in `src/schemas.py` and mock `LLMClient` responses so all bootstrap tests run locally with `OPENAI_MODEL=mock`.
  - Added `src/cli_apply_bootstrap.py` and `python3 main.py apply-bootstrap --name ... [--confirm]`. Dry-run shows current vs proposed diff; confirm writes manual files and backs up existing targets to `data/proposals/.backup/<ts>/`.
  - Style proposal safety: proposal stores source file, line range, target file, and `preview <= 100`; full excerpts are copied only on confirm into gitignored `data/style_examples/*.md` with `<!-- source: data/normalized_texts/<file>.txt lines X-Y -->`.
  - Added gitignored runtime continuation anchor path `data/manual_overrides/continuation_anchor.txt`; legacy `config/agents.yaml` anchor remains fallback for existing Dragon Raja workflow.
  - Added `python3 main.py init-book [--skip-extract] [--extract-limit N] [--force]`. It checks normalized state, optionally extracts, compresses, and generates the four proposals. It never auto-applies them.
  - Existing manual files are skipped by default unless `--force` is provided, preserving the current Dragon Raja workflow.
  - Engineering validation for Step 1 passed: 135 unit tests OK in 2.277s, `bash scripts/verify.sh` exited 0 with 135 tests OK in 2.164s, and `python3 main.py preflight` reported warn with FATAL none.
  - Step 1 engineering is ready for the commit `Iteration 015: auto-bootstrap pipeline for any novel`; cross-novel smoke waits for user preparation and explicit `可以跑 init-book`.
  - Cross-novel smoke (Step 2-4) ran 2026-05-23 against a user-provided Chinese novel. `init-book` produced four proposals; the user applied them and authorized the downstream pipeline. Bootstrap manual files: 15 facts, 12 entities, 6 relationships, anchor block with 7 entity states, single style example file with `<!-- source: ... lines X-Y -->` header — full excerpt stays in gitignored `data/style_examples/style.md`.
  - During the smoke, the six debate agents in `config/agents.yaml` were observed to anchor on the original validation corpus and produce an outline disconnected from the bootstrap manual files. The 6×6 agent outline was preserved as `outputs/debate/outline_longzu_fallback.md` and `outline.md` was rewritten to a source-novel-grounded outline before running `plan-chapters`. This is the documented caveat from the iter 015 plan (note #6) and remains an open follow-up for iter 019 (agent persona abstraction).
  - `src/debater.py` gained resume support: partial logs are not unlinked; previously-completed `(round, agent)` entries with non-empty responses and previously-completed ballots are skipped on rerun. This made the long debate survivable across externally-induced process resets.
  - Downstream pipeline: `plan-chapters --chapters 3` produced a coherent three-chapter plan whose chapter 3 plans a canonical major event from the source novel. `write --chapters 1` produced `outputs/drafts/chapter_01.md` with 5695 Chinese characters (above the iter 015 minimum of 3000), writer meta verdict `Approve`. `review-chapter 1` returned `Approve` with the same `_fallback_reason=(parse_failed)` reviewer fallback observed in iter 014.
  - Snapshot at `outputs/drafts/snapshots/20260523_120329/` includes chapter, meta, plan, debate decisions, both outlines, reviews, rolling summary, and the four bootstrap proposals.
  - Engineering: 135 unit tests still OK after the debater resume patch.
- Iteration 016 agent persona abstraction:
  - Closes the iter 015 caveat that left manual outline rewriting as the last cross-novel bottleneck.
  - Added `PersonasProposal` schema and `bootstrap_personas` in `src/auto_bootstrap.py`. `bootstrap_all` (and therefore `init-book`) now returns five proposal keys.
  - Added `python3 main.py bootstrap-personas` and extended `apply-bootstrap` with `--name personas`. Applied bindings land at gitignored `data/manual_overrides/personas.json`.
  - `config/agents.yaml` now carries `name_template` / `system_prompt_template` / `stance_template` on every debate and review agent, plus the legacy fields as fallback. The behavior contract is recorded in `_persona_template_note` inside the yaml itself.
  - New `src/persona_loader.py` renders templates via `str.format_map` with a default-empty mapping. `load_personas` returns `None` when the applied file is missing or `protagonist_name` is blank, so the original validation-corpus workflow is preserved untouched.
  - `src/debater.py` and `src/reviewer.py` now render agent prompts through persona binding when available; `build_outline` injects an explicit persona block forbidding drift to other corpora. The relationship-checklist guard still keys off the legacy reviewer name so 关系一致性 enforcement stays intact under any renaming.
  - Added `python3 main.py debate --topic "..."` so the smoke can override the legacy validation-corpus topic.
  - Tests +14 → 149 OK in under 5 seconds. `bash scripts/verify.sh` exited 0; `python3 main.py preflight` reported `warn` / `FATAL: none`.
  - Cross-novel re-smoke ran 2026-05-23 on the iter 015 source novel after deleting the manually-rewritten outline and any prior personas binding.
  - `bootstrap-personas` produced a faithful binding: protagonist matched the entity-graph entity with the highest degree, author was correctly inferred from the corpus, world_setting_brief stayed within the 400-char cap, core_relationships and core_setting_rules each pointed to canonical entities and rules already present in the manual override files.
  - `apply-bootstrap --name personas --confirm` wrote `data/manual_overrides/personas.json`, stripped `_meta`, and backed up the prior file to `data/proposals/.backup/<ts>/`.
  - `python3 main.py debate` completed all 6×6 agent rounds + 6 ballots + outline generation in a single uninterrupted process (~32 minutes). Every agent name in `debate_log.jsonl` was persona-rendered; no legacy validation-corpus name appeared.
  - **Critical acceptance**: the auto-generated `outputs/debate/outline.md` contains 33 hits of new-novel keywords (protagonist / locations / artefacts) and 0 hits of validation-corpus keywords. iter 015 needed a hand-rewritten outline to achieve the same effect; iter 016 reaches it automatically.
  - Downstream chain ran on the auto-generated outline: `plan-chapters --chapters 3 --force` produced a 3-chapter plan grounded in the new novel (each chapter title matches the outline section titles); `write --chapters 1 --resume-from 1 --force` produced `chapter_01.md` with 3466 Chinese characters, writer meta `verdict=Approve`; `review-chapter 1` returned `Approve` with the same `_fallback_reason=(parse_failed)` reviewer fallback observed in iter 014/015.
  - Snapshot at `outputs/drafts/snapshots/20260523_181110_iter016/` includes chapter, meta, plan, decisions, both outlines (the iter 016 auto-generated one is the active one), reviews, rolling summary, the five bootstrap proposals, and the applied personas binding.
  - Legacy validation-corpus workflow is preserved: `load_personas()` returns `None` when the personas file is missing or has a blank protagonist; `render_agent_fields` falls back to legacy `name` / `system_prompt` / `stance` per slot. The 135 unit tests in iter 015 covered the legacy path and still pass.
- Iteration 017 multi-book workspace isolation:
  - Introduced `workspaces/<book>/` layout. Multiple books coexist in the same checkout; switching is a single `--book <name>` CLI flag or `WORKSPACE_NAME` env var.
  - New `src/paths.py` is the single source of truth for per-book path resolution. ~20 helpers (`data_dir`, `debate_dir`, `drafts_dir`, `reviews_dir`, `raw_txt_dir`, `manual_overrides_dir`, `personas_path`, `outline_path`, `chapter_plan_path`, etc.) all derive from `workspace_root()` and re-read the env var on every call.
  - 22 modules in `src/` refactored. Module-level path constants are kept verbatim (so the ~30 iter 014-016 tests that `patch("src.module.CONSTANT", ...)` still work) and each gains `_resolved_*()` helpers that defer to `paths.*()` when a workspace is active, falling back to the legacy constant otherwise.
  - `main.py` now pre-parses a global `--book <name>` flag (anywhere in argv, also `--book=<name>` form) and exports it as `WORKSPACE_NAME` before argparse runs. Every existing subcommand works with `--book` unchanged.
  - New `src/cli_workspace.py` and four subcommands: `workspace-list`, `workspace-init <name>`, `workspace-import-current --to <name> [--dry-run]`, `workspace-show [--name <name>]`. `import-current` uses `shutil.move` (not copy) so the source novel only exists in one canonical location.
  - Shell scripts (`write_book.sh`, `verify.sh`, `debate_smoke.sh`, `write_smoke.sh`, `real_smoke.sh`) accept `--book` and `$WORKSPACE_NAME`, resolving per-book output paths via inline `python3 -c "from src import paths; ..."` calls.
  - `.gitignore` adds `workspaces/*/{小说txt,data,outputs,logs}/` rules and a `workspaces/.gitkeep` placeholder. Per-book content stays out of git on the same principle as legacy paths.
  - Tests +20 → 170 OK in under 5s. New files: `tests/test_paths.py` (+12 cases for `workspace_name` permutations, `workspace_root` resolution, per-helper derivation, mid-process env switch) and `tests/test_workspace_isolation.py` (+3 cases verifying every refactored module resolves correctly in both modes and that two workspaces can coexist in one process). `tests/test_cli_integration.py` +3 (`--book` env export, `workspace-init` directory creation, `workspace-import-current --dry-run` is read-only). `tests/test_smoke_scripts.py` +1.
  - Backward compatibility hard requirement: every iter 014-016 behavior is preserved when no workspace is active. All 149 tests from iter 016 still pass byte-identically.
  - Cross-workspace smoke ran 2026-05-23. The iter 016 source novel was migrated into `workspaces/workspace1/` via `workspace-import-current` (dry-run first, then real `shutil.move`); preflight clean; baseline sha256 recorded for chapter_01.md / outline.md / personas.json / entity_graph.json. A second workspace `workspaces/workspace2/` was created from a separate source novel and the full `init-book → apply 5 proposals → debate → plan → write → review` pipeline ran on it. Two engineering fixes landed alongside the smoke: `main.init_book_pipeline` was using hardcoded `Path("小说txt")` / `Path("data/...")` strings — now resolved through `paths.*()` in workspace mode while legacy mode keeps the cwd-relative strings; `main review-chapter` similarly resolves `chapter_NN.md` through `paths.drafts_dir()` in workspace mode.
  - workspace2 produced 5 proposals, debate completed with persona-rendered agents using workspace2's protagonist and author, outline had 22 keyword hits for workspace2's source and 0 for workspace1's, chapter_01.md was 4552 Chinese characters, and review returned Approve.
  - **Critical isolation acceptance (C4)**: every monitor tick during the workspace2 debate showed workspace1's chapter_01.md sha256 prefix unchanged. After the full smoke, all four baseline files were byte-identical — workspace1's chapter, outline, personas, and entity graph survived the entire workspace2 init-book → debate → plan → write → review pipeline untouched.
  - Snapshot at `workspaces/workspace2/outputs/drafts/snapshots/<ts>_iter017_workspace2/` contains the workspace2 chapter, meta, plan, decisions, outline, reviews, rolling summary, the five workspace2 bootstrap proposals, and the applied workspace2 personas binding.
- Iteration 018 multilingual splitter (English first):
  - Goal: any non-Chinese novel (English first scope) flows through `normalize → split → extract` cleanly. Previously the splitter regex was Chinese-only (`第N章 / 第N幕 / 楔子 / 序章`) and the normalizer's boilerplate blacklist targeted Chinese pirate-site cruft; any English text returned 0 chapters and kept the per-chapter banner lines that EPUB exports prefix.
  - New `src/lang_detect.py` — single `detect_language(text, sample_chars=4000, threshold=0.30)` returns `"zh"` or `"en"` from CJK-vs-ASCII-letter ratio in the first 4 KB. Mostly-Chinese with English notes still resolves `"zh"`; only genuinely English text crosses 0.30. Empty / whitespace / pure-symbol input returns `"en"` fallback.
  - `src/chapter_splitter.py` gained `HEADING_RE_EN` covering PROLOGUE / EPILOGUE / INTRODUCTION / FOREWORD / AFTERWORD, `CHAPTER` + roman or arabic + optional ` : Title`, `Chapter N` + optional title, and all-caps POV style (up to 3 ASCII-uppercase words of 3-15 letters each — matches e.g. `ALICE`, `BOB`, `ALICE SMITH`). A `LANG_HEADING_PATTERNS` dict fans out from a single `lang` kwarg that `is_heading`, `heading_allowed`, `candidate_headings`, `split_file`, `split_all` all accept (defaulting to `"zh"` / `None` for byte-identical legacy callers). `split_file(path, lang=None)` auto-detects via `lang_detect`. English `heading_allowed` accepts any non-blank heading — no `章` / `幕` constraint.
  - `src/text_normalizer.py` gained `BOILERPLATE_PATTERNS_EN` (Project Gutenberg, ISBN, Copyright / All rights reserved, URLs, ornament rules, `N-Book Bundle`, series-banner). Critically `clean_line` in `"en"` mode runs the boilerplate strip on **every** line, not just the first 120, because the series banner repeats throughout EPUB exports. `volume_id_for` ASCII filenames return `en_<slug>`; CJK filenames keep the validation-corpus mapping. `normalize_file(path, lang=None)` auto-detects.
  - New `src/epub_to_txt.py` (stdlib only — `zipfile` + `html.parser` + `xml.etree.ElementTree`). Follows `META-INF/container.xml` → `content.opf` → `<spine>` itemrefs → manifest hrefs to preserve reading order. `_TextExtractor(HTMLParser)` emits newlines around block tags, swallows `<script>` / `<style>` / `<head>`. `extract_epub(src, out, book_filter=None)` returns stats dict; optional `book_filter` regex filters spine entries by href for picking one book out of a multi-book bundle.
  - `main.py`: `normalize` and `split` accept `--lang {auto|zh|en}`; new `epub-import --src <path.epub> --out <name.txt> [--book-filter REGEX]` subcommand resolves output through `paths.raw_txt_dir()` so the extracted text drops into the active workspace's source-text directory.
  - Tests +23 → 193 OK in ~3s. New files: `tests/test_lang_detect.py` (+5), `tests/test_splitter_en.py` (+7), `tests/test_normalizer_en.py` (+8), `tests/test_epub_to_txt.py` (+3). All 170 pre-iter-018 tests still pass; backward-compat hard requirement met.
  - End-to-end mock smoke on workspace3 (English source novel via desktop EPUB): `workspace-init workspace3 → epub-import --book-filter 'part00(0[6-9]|[1-9][0-9])'` (100 spine entries → 1.83 MB UTF-8) → `normalize` (auto-detects `en`; produces 10 872 lines stripped of banners) → `split` (94 chapter manifest entries — far above the ≥40 acceptance floor) → `OPENAI_MODEL=mock extract --limit 2` (2 JSON files) → `compress` (`global_knowledge.md` + index) → `preflight` (warn / FATAL none). The first manifest entry is outsized (~337 K chars) because the EPUB's spine interleaves the appendix between Book 1's main text and the next book; entries 4-15 are appendix `HOUSE …` sections the all-caps POV regex correctly matches. The remaining ~80 entries are real POV chapters.
  - Critical isolation check: `sha256sum --check /tmp/xz_baseline.sha` (the iter 017 baseline for workspace1 chapter_01.md, outline.md, personas.json, entity_graph.json) → 4/4 OK after the full workspace3 pipeline. Chinese workspaces survived untouched.
  - Iteration 018 is mock-only by user decision; real-model writing on the English workspace is deferred to iteration 019. Agent prompt templates in `config/agents.yaml` are still Chinese — they work cross-lingually but may drift in tone; translation deferred to iter 020.
- Iteration 019 unattended `write_book.sh` + chapter resume/retry:
  - Goal: writing a multi-chapter book no longer needs a human between chapters. The pre-iter-019 `scripts/write_book.sh` printed `apply-advance --proposal-idx <comma-list>` reminders and `exit 0`-ed after every non-final chapter; the user had to hand-pick proposal indices, run `apply-advance --confirm`, and re-invoke the script. Second gap: the script's `[ -f $chapter_path ]` check ignored `chapter_NN.failure.json` and `meta.needs_human_review=true`, so reject / lint-blocked chapters were silently treated as done.
  - `main.py` `apply-advance` parser gained `--auto-apply` (selects proposals whose `confidence >= --min-confidence`, default `0.7`), `--allow-empty` (no-op exit 0 when nothing qualifies — write_book.sh always passes it), and made `--proposal-idx` optional whenever `--auto-apply` is set (mutual exclusivity enforced at dispatch). `src/entity_advance.py` gained pure helper `select_auto_indexes(proposals, min_confidence)` plus three new kwargs (`auto_apply / min_confidence / allow_empty`) on `apply_advance_proposals(...)`. `src/cli_apply_advance.py` passes them through.
  - New `src/chapter_status.py` returns `{exists, approved, needs_review, failure, verdict, rewrite_count}` for one chapter. `approved` is true iff the `.md` exists AND no `.failure.json` AND `meta.needs_human_review != True` AND `meta.verdict == "Approve"`. `main.py` exposes a `chapter-status N` subcommand that prints the dict as JSON. write_book.sh queries this via inline `python3 -c` instead of grepping meta files.
  - `scripts/write_book.sh` rewritten end-to-end. New flags: `--max-retries N` (default 2 → up to N+1 total attempts per chapter), `--min-confidence X` (passed to apply-advance), `--no-auto-advance` (debug escape hatch). Per-chapter flow: skip if already `approved`; else retry until approved or budget exhausted, clearing `.md/.meta/.failure` between attempts; on retry exhaustion exit 2 with a clear `GAVE UP on chapter $i after N attempts` message; on success call `apply-advance --auto-apply --allow-empty --confirm`. Exit codes: 0 success, 2 retry exhausted, anything else is the underlying Python error.
  - `src/writer.py` gained a mock-only failure injection hook: when `WRITER_FORCE_FAIL=1` AND `OPENAI_MODEL=mock`, the post-completion draft becomes a deliberately-short string the linter rejects, exercising the failure-marker / retry path without LLM cost. The double-gate (mock model required) means a stray env var in production cannot trigger the injection.
  - Tests +15 → 208 OK in ~3s. New files: `tests/test_apply_advance_auto.py` (+7), `tests/test_chapter_status.py` (+3), `tests/test_write_book_script.py` (+4). `tests/test_smoke_scripts.py` +1 (assertion that the `--proposal-idx <comma-list>` placeholder is gone from the script source). All 193 pre-iter-019 tests still pass byte-identically.
  - Engineering gates: `verify.sh` exit 0; preflight legacy / xueZhong / longzu / asoiaf all warn / FATAL none.
  - Real-model smoke planned on a fresh `iter019smoke` workspace (rather than longzu / xueZhong / asoiaf) so the iter 017 sha256 baseline stays untouched and the pre-existing chapter_01 of longzu (which has stale `failure.json` markers) doesn't force a costly real-model rewrite. Smoke result will land in a follow-up commit titled `Iteration 019: record unattended writer smoke results`.
- Iteration records are kept under `docs/iterations/`.

## Validation Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
```

## Next Candidates

- Iteration 020: hosted-product layer — web UI for the unattended write_book loop / SaaS / per-user workspace isolation. Now that iter 019 made the multi-chapter pipeline truly unattended, putting a UI on top of `workspace-init → init-book → debate → write_book.sh` is the natural next slice.
- Beyond iter 020: Japanese / Korean splitter heuristics; translating agent prompt templates from Chinese so non-Chinese workspaces don't rely on cross-lingual prompt comprehension; relationship-type-weighted confidence thresholds for `apply-advance --auto-apply`.
- Reviewer prompt follow-up: decide whether to make reviewers explicitly evaluate style-example alignment and continuation-anchor adherence beyond the relationship checklist.
- DeepSeek cache follow-up: decide whether to add a preflight/cost-report WARN because cache writes are logged but reads may remain 0.
- Deferred candidates: B3 rolling summary 升级伏笔表、C2 增量 compress。
- Add a lightweight terminal UI or dashboard if operator reports become too verbose.

---

## Phase 4 Status（iter 021，2026-05-25）

> Live progress dashboard for Phase 4. Source-of-truth status table is in
> [README.md「项目阶段 SOP（实时状态）」](../README.md#项目阶段-sop实时状态);
> this section is the more detailed per-iter rollup.

### Iteration 020 — Extended smoke + failure-mode report（已完成 / 已 commit）

- Ran longzu ch1-10 real-model smoke against deepseek-v3-pro.
- **ch1-9 all Approve** (9/10 = 90% pass rate); **ch10 GAVE UP** after 3 outer attempts (lint rule `not_x_but_y` cascade — 33 cumulative hits across 10 chapters, ch10 alone hit 11).
- Total cost ¥12.69, all iter 019 audit fixes validated in production (no silent approves, snapshots saved on the GAVE UP path, failed metas preserved).
- User code-review identified 2 root-bug categories: (a) start-point hardcoded to book 1 ch001 by `auto_bootstrap._recent_extractions_context`; (b) writer + reviewer never read source-novel text — all "style/detail" came from KB 141 lines + style_examples, an information retention rate of <1% from the original 1M-character source.
- Iter 020 report `docs/iterations/iteration_020_extended_smoke.md` ships 8-section failure-mode analysis + 11-item iter 21+ improvement roadmap reorganized into 3 stages.

### Iteration 021 — Algorithm root fix + SOP visualization（进行中）

**Goals**: kill the 4 root algorithm bugs iter 020 exposed; promote the 9-stage SOP table to README + AGENTS + AGENT_HANDOFF as a live status dashboard so future agents see at a glance what's wired and what isn't.

**4 root-bug fixes**:

| ID | Bug | Fix | Status |
|----|-----|-----|--------|
| A1 | 起点判断硬编码（书 1 ch001 锁死）| `src/start_point.py` 新模块 + CLI `set-start-point chapter_id\|volume_id` + `auto_bootstrap` 闭环 | ✅ done |
| A2 | writer 不读原文 | `src/writer.py:_write_prompt()` 注入起点前 K=3 章 × 3K chars 原文 | ✅ done |
| A3 | plot_planner 不读 KB/rolling | `src/plot_planner.py:_build_planner_prompt()` 注入 KB + 最近 3 章 rolling summary | ✅ done |
| A4 | 起点之后剧透泄漏 | `manual_facts.global_facts_summary` + `entities.render_active_state` 加 `respect_start_point` 参数；过滤 evidence_spans/chapter_id 晚于起点的 fact 和 relationship | ✅ done（KB 过滤推到 iter 022） |

**SOP 落地**：README 新增 60+ 行实时状态表（9 阶段 × 25 节点）；AGENTS.md 「当前阶段」section 改为指向 README SOP + 工程铁律加第 8 条（每 iter 必须同步 SOP 状态）；本文件追加本 Phase 4 Status 段。

**测试**: +14 → 239 OK 全绿（plan 估 +12 → 237，实际超 2）。新文件：
- `tests/test_start_point.py` (+7)
- `tests/test_writer_source_injection.py` (+2)
- `tests/test_plot_planner_kb_rolling.py` (+3)
- `tests/test_spoiler_filter.py` (+2)

**待办**：P9 longzu 真模型 smoke（设 start=longzu_4 跑 1 章新 ch1 验证 A1+A2 真生效）+ P10 commit。

### Iteration 022 — writer/reviewer 强化（已完成 / 已 commit）

Goal: 把 iter 020 报告 Stage B 6 条一次性收齐，让 iter 021 验证 ch1 写的"高架路火箭筒"草稿能突破 lint cascade 进入真内容审核阶段。

**6 项修复**:

| ID | Bug / 改进 | Fix | Status |
|----|-----|-----|--------|
| B1 | `not_x_but_y` 阈值固定 = 2/5 太严格 | `linter.yaml` base 调 3/10 + `linter.py` 加 `dynamic_scaling` 按字数缩放 | ✅ done |
| B2 | writer prompt 反例字面 prime 模型 | system_prompt 抽象化（去字面例）+ feedback 改报行号不报违规字面 | ✅ done |
| B3 | reviewer score 单 0-10 无区分度 | `AgentReview` 加 `scores: AgentSubScores`（plot/prose/fidelity）+ `score` legacy alias 从 sub 加权算出 | ✅ done |
| B4 | reviewer 不读原文不读 KB | `review_text()` 加 `knowledge` + `source_chapters` 参数；writer.py 调用点传入 | ✅ done |
| B5 | rolling 只有摘要 信息密度低 | `chapter_summary.append_chapter_summary` 加 `text_snippet`；`render_rolling_context` 输出最近 K 章片段 | ✅ done |
| B6 | `write_book.sh` exit code 被 tee mask | `exit "${PIPESTATUS[0]}"` 显式传播 | ✅ done |

**测试**: +15 → **257 OK** 全绿。

**P8 真模型 smoke 关键发现**（"切切实实解决问题"）：
- iter 020 ch10 / iter 021 ch1 都死在 lint cascade（reviewer 都没被调）
- iter 022 ch1 **首次突破 lint** → 8 agent 真审 → sub-score 真分化（路明非本位 plot=4 → Reject；读者代言人 plot=8/prose=9 → Approve；5 Approve + 3 Reject）
- 结果 verdict 仍 Reject，但是**因为真实内容判断**，不再是 lint 短路
- 中途学习：B2 我加的字面反例（"❌ 不是疼痛，是重量"）反 prime 模型让 hits 翻倍，priming-fix 后回落

**Smoke 成本**: ~¥1.5 实测（含 4 次重跑定位 priming bug）。

---

## Phase 4 Status（iter 023，2026-05-26）

### Iteration 023 — agent 8→5+1 精简 + 经典片段场景化 + 关系一致性程序化（已完成 / 已 commit）

**Goal**: 解决 iter 022 暴露的 2 个新瓶颈 — 8 agent 中 3 个职责重叠 + 经典片段没被场景化利用。承认 lint cascade 中 `not_x_but_y` 是江南本人笔法（不该一刀切阻断）。

**5 项实现**:

| ID | 改动 | 状态 |
|----|------|------|
| P1 | `src/source_excerpts.py` 新模块（select_for_chapter keyword-matching）| ✅ |
| P2 | `bootstrap_source_excerpts` + 4 个新 schemas | ✅ |
| P3 | writer + reviewer 注入 scene-matched 片段（按 plan_item.key_events 选段）| ✅ |
| P4 | 8 agent → 5 reviewer + 1 改写顾问；合并 3 重叠 agent；主角本位 / 原作风格模拟 改名通用化 | ✅ |
| P5 | `src/relationship_auditor.py` 程序化 + 合成 `deterministic_relations` agent；0 LLM 成本 | ✅ |

**新增临时修复（P8 smoke 中途学习）**:
- `not_x_but_y` lint 从 `error_threshold=10` 改 `999` = warning-only。原因：deepseek 在"高架路对决"产 12 hits/3.6K 字（密度 3.3/1K），但读起来质量好；江南龙族原作也大量使用此句式。lint 不应当 cascade reject，让 reviewer 判断。

**测试**: +17 → **274 OK**。新文件：test_source_excerpts / test_relationship_auditor / test_agents_5plus1 / test_writer_excerpt_injection / test_reviewer_deterministic_relations。

**P8 真模型 smoke 关键证据（iter 023 critical 成功）**:
- 5+1 agent panel 实测：3 Approve + 2 Reject → 最终 Reject（fail-closed）
- **第一次** reviewer 给出 actionable 内容反馈（而非 iter 022 全 7 笼统）：
  - 主角本位 plot=4 Reject：「主角路明非未在本章中出现或采取任何行动」← 真内容洞察
  - 世界观守门人 plot=8 Approve + 批评：「奥丁过早直呼其名削弱悬念」
  - 伏笔猎人 plot=8/prose=9/fidelity=9：「苏小妍昏迷中自主吟唱龙文 ... 需后续与'太子'伏笔关联」
- sub-score 区分度：plot 4-8（差 4）, prose 6-9, fidelity 5-9 — 5 agent 实现了 iter 022 8 agent 同等区分度
- bootstrap-source-excerpts 用 deepseek 产 10 段 6 类 scene_type 覆盖

**Smoke 成本**: ¥2.24（预算 ¥4，56% 用量）。

### Next iter（024）候选入口

- **WebUI**（iter 020 报告原计划，现可启动）
- plot_planner `--from-chapter N --append K` continuation
- write_book.sh 每 K 章自动 re-plan
- per-章 cost 实时报告 + budget ceiling
- 改写顾问输出消费链路（advisor agent 落配置但 writer 尚未消费 RewriteSuggestion）
- KB 按起点过滤（iter 023 推后；需 LLM 重写 KB）
- entity_graph timeline schema 升级（加 chapter_id 让程序化 auditor 检测更密集）
- iter 025 capstone：完整 longzu ~30-100 章 真模型 smoke（基于 iter 023 sub-score + advisor 信号驱动）

---

## Phase 4 Status（iter 024，2026-05-27）

### Iteration 024 — 长程稳定性 4 项（已完成 / 已 commit）

**Goal**: 为 iter 025 capstone（跑完整 30-100 章）做前置稳定性投资。iter 023 把 advisor 配置就绪却没接消费链路，iter 024 串通；同时补 plot_planner continuation、budget ceiling、proposal vs plan 冲突检测三项 SOP 待办。

**4 项实现**:

| ID | 改动 | 状态 |
|----|------|------|
| P1 | reviewer.load_advisor_agents + 调 advisor 产 rewrite_suggestions；writer._review_feedback 加专门 advisor section（cap 5 条）| ✅ |
| P2 | plot_planner.generate_chapter_plan 加 append_count / from_chapter；main.py 加 --append --from-chapter；write_book.sh 加 --replan-every K 每 K 章 trigger | ✅ |
| P3 | cost_estimator.estimate_cost_since + cost_cny 共享 pricing；write_book.sh --budget-cny N + exit 3 + per-章 cost 日志 | ✅ |
| P4 | src/proposal_validator.py（hard-conflict heuristic）+ write_book.sh apply-advance 前 dry-run，BLOCKED 时跳过自动应用 | ✅ |

**测试**: +22 → **296 OK**（plan 估 +15 → 289，超出 7 个）。新文件：
- `tests/test_cost_per_chapter.py` (+4)
- `tests/test_proposal_validator.py` (+3)
- `tests/test_plot_planner_append.py` (+2)
- `tests/test_reviewer_advisor_consumption.py` (+3)
- `tests/test_writer_advisor_feedback.py` (+3)
- `tests/test_write_book_replan_budget.py` (+7)

**P6 真模型 smoke 关键证据**:
- advisor 实战产 **5 条 actionable suggestions** 落到 chapter_01.meta.json：
  1. [rewrite 开场段落] 将开场视角改为路明非梦中惊醒，康斯坦丁低语"母亲"...
  2. [add 诺诺逃往B3停车场段落] 加入路明非视角的割裂叙事...
  3. [rewrite 神秘男人出场段落] 将"我等了十六年"台词改为朝向路明非...
  4. [add 文中插入段落] 教授会议室场景，古德里安察觉"尼伯龙根指数飙升"...
  5. [add 结尾 hook] 路明非接过短刀，刀身龙文与青铜封印阵产生共振...
- 这是 iter 020-023 reviewer 从未产出的**编辑级具体建议**（含 section + type + guidance）
- ch1 仍 Reject（同 iter 023：模型仍写诺诺视角而非主角），advisor 准确诊断
- 其它 3 项（re-plan / budget / validator）单测验证完整，真模型 smoke 未触发其成功路径（ch1 没 Approve 进 success path）

**Smoke 成本**: ¥1.53（预算 ¥3-5，30% 用量）。

### Next iter（025）候选入口

- **WebUI**（iter 020 报告原计划，长程稳定后可启动）
- **iter 025 capstone**：完整 longzu 30-100 章 真模型 smoke，利用 iter 024 budget ceiling + auto re-plan 跑得动
- KB 按起点过滤（需 LLM 重写 KB）
- entity_graph timeline schema 升级（让 deterministic_relations + proposal_validator 更密集）
- writer 真用 rewrite_suggestions 后效果验证（iter 024 P1 落地但未真模型验证下一稿改进效果）

---

## Phase 4 Status（iter 025，2026-05-28）

### Iteration 025 — WebUI U.1 只读 dashboard（已完成 / 待 commit）

**Goal**: 把 phase 4 SOP 仅剩 ❌ 的 `U.1 WebUI dashboard` 关掉。iter 020 plan 把 WebUI 拆成 iter021-024 P1-P4，但实际 iter 021-024 全用于算法稳定性。iter 025 走「拆 2 iter」路径：iter 025 落 P1（只读 dashboard）+ iter 020 plan P4 的 reviews 端点扩成「全量」（含 iter 024 advisor 的 `rewrite_suggestions`）；iter 026 接 U.2（wizard + 模型切换）。

**落地（4 P 项）**:

| ID | 改动 | 状态 |
|----|------|------|
| P1 | `src/web/{__init__,server,routes}.py` 骨架 + `main.py` 注册 `web` 子命令（`--host 127.0.0.1 --port 8765`） | ✅ |
| P2 | `src/web/workspace_ctx.py`（threading-safe `use_workspace` 上下文管理器）+ `src/web/reviews_aggregator.py`（严格 2 位数字 glob + stats）+ 9 个纯函数 handler | ✅ |
| P3 | `src/web/templates.py`（`string.Template` 不冲突 JS 模板字面量）+ `src/web/static.py`（内嵌 CSS/JS 字符串，0 外部资源）| ✅ |
| P4 | 4 个新测试文件 +26 → **322 OK**（baseline 296）；`docs/iterations/iteration_025_webui_dashboard.md`；README SOP U.1 ✅ + "Run the dashboard" 段；本文件本段；iterations README +1 行 | ✅ |

**路由表（GET-only）**：

| Method | Path | 作用 |
|---|---|---|
| GET | `/` | workspace 列表 HTML |
| GET | `/workspace/<name>/` | 4 panel HTML 骨架 |
| GET | `/static/{app.css,app.js}` | 内嵌字符串响应 |
| GET | `/api/workspaces` | `{"workspaces":[...]}` |
| GET | `/api/workspace/<name>/{status,cost,manifest,reviews}` | 4 个数据 panel |
| GET | `/api/workspace/<name>/logs/tail?n=N` | per-workspace `logs/llm_calls.jsonl` 尾 N 行 |

**测试**: +26 → **322 OK**（plan 估 +20 → 316，实际 +26 → 322）。新文件：
- `tests/test_web_routes_get.py` (+14)
- `tests/test_web_reviews_aggregator.py` (+6)
- `tests/test_web_workspace_ctx.py` (+3)
- `tests/test_web_server.py` (+3)

**真服务手测**：`/usr/bin/python3 main.py web --port 8765` 后用 urllib 实测 13 个路径状态码与 Content-Type 全部正确（含 4 个 404 路径 + 2 个 static 资源）。`bash scripts/verify.sh` exit 0；xueZhong / asoiaf / longzu sha256 baseline 不变。

**关键设计决定**：

1. **iter 025 全程 GET，0 副作用** —— POST/PUT 整段推到 iter 026，让 iter 025 测试不需要 mock LLM 调用，纯文件 I/O 跑得快。
2. **handler 是纯函数** —— `routes.dispatch(method, path) -> (status, content_type, body_bytes)` 与 HTTP server 解耦；单元测试不起 socket 就能跑全部 handler。
3. **reviews 全量保留 + 前端默认折叠** —— `aggregate_reviews` 保留每章完整 `agent_reviews[*]` + `lint_issues` + `rewrite_suggestions`；HTML 默认 collapsed，点行展开。iter 024 advisor 的 5 条 actionable rewrite_suggestions 终于在 UI 上能看到。
4. **stdlib-only 硬约束** —— `http.server.ThreadingHTTPServer` + `string.Template` + 内嵌 CSS/JS 字符串。`requirements.txt` 未动。
5. **JSON 默认 `default=str`** —— `collect_status()` / `estimate_cost()` 返回的 dict 嵌 `pathlib.Path`，统一 fallback 转字符串。

### Next iter（026）入口

- **U.2 wizard + 模型切换**：iter 026 在 `src/web/` 加 `do_POST` / `do_PUT` + `jobs.py`（threading worker + 409 同 workspace 并发保护）+ `wizard.py`（手写 multipart epub 上传 + 7 步状态机）+ `settings.py`（白名单 `.env` 编辑 + 原子写 + key 屏蔽）+ `WIZARD_TPL` / `SETTINGS_TPL` / `JS_WIZARD`。预计 +20 测试 → 342。
- **iter 027+ capstone**：iter 026 wizard 完成后跑完整 longzu 30-100 章真模型 smoke。iter 024 budget ceiling + auto re-plan + advisor 消费链路全部就绪。

---

## Phase 4 Status（iter 026，2026-05-28）

### Iteration 026 — U.2 wizard + 模型切换 + auto-pipeline + 4 hardening（已完成 / 已 commit）

**Goal**：(a) 把 SOP 9 步全编排进 `src/auto_pipeline.run_auto_pipeline`，让 CLI 一行命令 + wizard 后端 worker 共享同一段业务；(b) 浏览器上传 epub/txt → 自动跑出 ch1；(c) `.env` 编辑 panel + key 屏蔽；(d) iter 025 code-review 留尾 4 个 hardening 一并修。

**6 项实现**:

| ID | 改动 | 状态 |
|----|------|------|
| P2 | `src/auto_pipeline.py` 串接 9 步业务 + `main.py auto-pipeline` 子命令 + `verify.sh` 升级（`run-all → auto-pipeline`）| ✅ |
| P1 | `src/web/jobs.py` threading worker + step 白名单 dispatch + 409 同 workspace 保护 + `server.py do_POST/do_PUT` + routes POST 扩展 | ✅ |
| P3 | `src/web/wizard.py` 手写 multipart 解析（避 `cgi.FieldStorage`）+ 立即 `start_job(step="auto-pipeline")` + 前端 2 状态 JS | ✅ |
| P4 | `src/web/settings.py` 4 keys 白名单 + key 中段屏蔽 + 原子 `os.replace` 写 + restart banner | ✅ |
| P5 | #3 `_tail_jsonl` O(1) seek-tail / #6 `list_workspaces` 加 `(data/ or outputs/)` sanity / #7 dispatch catch-all 用 trace_id 不再泄 `str(exc)` / #10 非 loopback host 打 stderr WARNING | ✅ |
| P6 | +34 测试 → 363；新建 `iteration_026_wizard_settings.md`；README SOP U.2 ✅ + 新增 U.3 auto-pipeline；本段 | ✅ |

**测试**: 329 → **366 OK**（plan 估 +28；P6 落地 +34；P5b 再 +3 = 净 +37）。新文件：
- `tests/test_auto_pipeline.py` (+5) — 9 步端到端 mock + apply 失败非阻断
- `tests/test_web_jobs_dispatch.py` (+6) — step 白名单 + 409 + workspace 隔离
- `tests/test_web_wizard_e2e.py` (+5) — multipart 上传 + 端到端 ch1 落盘
- `tests/test_web_settings.py` (+5) — key 屏蔽 + 原子写 + 字段保留
- `tests/test_web_hardening.py` (+8) — 4 个 P5 fix 全覆盖
- `tests/test_web_routes_post.py` (+5) — POST/PUT/405 method-mismatch

**关键设计决定**:
- **auto_pipeline 是 CLI / wizard 共享单点**：业务在一个文件，wizard 前端只 2 状态（upload + polling），不可能漂移
- **per-proposal apply 失败非阻断**：mock 模式 style_examples 必然失败（`mock.txt` 不存在），不让一个 proposal 失败葬送整个 wizard onboarding
- **不引入新依赖**：`requirements.txt` byte-identical；multipart 解析手写 60 行
- **stdlib-only 守住**：`http.server` + `string.Template` + `json` + `email`，无新包

**Smoke 成本**: ¥0（mock-only）。

### P5b — code-review 4 blocker 当 iter 内修

iter 026 P6 末尾按 standing instruction（[[feedback-iter-codereview]]）跑 `/code-review high effort`，10 个 finding 中 4 个 blocker 当场修：

- **#1 dashboard 冻结**（HIGH，用户最 visible）：`workspace_ctx` 全 with-body 持 process-wide RLock 让 dashboard read 端点全冻结。改 `paths.py` 加 `_THREAD_OVERRIDE = threading.local()`，`workspace_name()` 优先读 thread-local；`workspace_ctx.use_workspace` 完全重写去 lock。CLI env-var fallback 保留。test_does_not_block_other_threads 实测 < 50ms（修前 ~500ms）
- **#2 wizard epub 失败 + 409 forever**（HIGH）：`wizard.start_upload` 上传段加 try/except + rollback + 400 友好错误，server-side log 完整 traceback
- **#3 source_excerpts 漏**（MED-HIGH）：`bootstrap_all` 加第 6 个 proposal，wizard / auto-pipeline 路径与 iter 023 设计对齐
- **#4 auto_pipeline 异常太宽**（MED）：收窄 `except (FileNotFoundError, ValueError)`，PermissionError / KeyError 传播以 trace_id 指向根因

P5b 二轮 delta review 再发现 1 个 MED（wizard tmp_path leak on write failure）当场修；2 个 LOW（re-run skip 噪音 / except 太宽吞 MemoryError）写进 iter 027。

### Next iter（027）候选入口

- **capstone 真模型**：iter 024 budget ceiling + auto re-plan + advisor 消费链路全部就绪；iter 026 `auto-pipeline` + wizard 让"零人工干预"成立；可以跑 longzu 30-100 章真模型 smoke 收 phase 4
- **iter 026 code-review carry-over 待 iter 027 处理**:
  - **MED**: #5 `_tail_jsonl` partial first line 未丢弃（mid-file seek 落在 JSON 中间产生 `{"raw":"..."}` 行）
  - **MED**: #6 `.env` 编辑销毁用户注释（PUT 后所有 `#` 行消失，无 undo）
  - **MED**: #7 workspace name 规则在 3 处复制（routes / wizard / cli_workspace）→ 抽 `src/web/_naming.py`
  - **LOW**: #8 `start_job` 线程启动失败时 `_WORKSPACE_JOBS` 锁泄漏（仅 OS 线程耗尽时触发）
  - **LOW**: #9 wizard 未引号 multipart filename 不识别
  - **LOW**: #10 `api_job_status` 不查 `_workspace_exists`（与其他 API 不一致）
  - **LOW（P5b 新发）**: re-run wizard 时所有 6 proposal 走 `_skip_result` → apply 全 `apply_failed` 噪音
  - **LOW（P5b 新发）**: wizard `except Exception` 吞 MemoryError → 进程内存损坏后仍接客
- KB 按起点过滤（需 LLM 重写 KB）
- entity_graph timeline schema 升级
- writer 真用 rewrite_suggestions 后效果验证（iter 024 P1 落地但未真模型验证）
- WebUI 章节 Markdown 在线编辑器（iter 020 plan 的 P2，整体未做）
- WebUI 可视化雷达图 / 甘特图（iter 020 plan 的 P3）

---

## Phase 4 Status（iter 027，2026-05-29）

### Iteration 027 — capstone 真模型暂停 + 起点/长生成 hardening（修复完成，续写仍暂停）

**用户指令**：暂停继续生成续写；先修复 iter27 过程中发现的 bug / 卡顿 / 守门缺口。用户确认后再从第三部后面重跑。用户提供的外部中转站/key 视为可信，看到明文 key/endpoint 时提醒即可，不再作为阻断条件。

**事故根因**：longzu workspace 缺 `data/manual_overrides/start_chapter.json`，旧 `continuation_anchor.txt` 和 `outputs/debate/chapter_plan.json` 仍锚在 Book 1 early admission arc，所以错误 run 继续写出了 3E 考试相关章节。错误起点产物只作证据，不作为目标续写。

**已确认的 debate 状态**：iter27 debate 已完成 6 轮自由辩论 + 第 7 轮裁决投票；`decisions.json` 中 3 个问题均 6:0 通过。

**本轮修复**：
- `scripts/write_book.sh` 默认 `REQUIRE_START_POINT=1`，支持 `--start-point <id>`；只有 intentional from-beginning 测试用 `--allow-missing-start-point`。
- `main.py plan-chapters --require-start-point` + `src/plot_planner.py`：缺起点直接失败；生成的 `chapter_plan.json` 写入 `start_chapter_id`；append 模式要求旧 plan metadata 与当前 start 一致。
- `write_book.sh` 在写作前校验 plan 的 `start_chapter_id` 与当前 start point 一致，旧无 metadata plan 会失败并要求重跑 `plan-chapters --force --require-start-point`。
- `plot_planner` prompt 注入 `resolved_start_chapter_id` 与起点前最近章节标题，明确禁止重新规划起点前入学/考试/训练/旅行/揭示事件。
- `chapter_summary.prune_from_chapter` + `write_book.sh` retry 清理，避免 rejected draft summary 污染 retry。
- `llm_client/config/models`：`litellm.drop_params=True` 兼容 GPT-5 temperature 限制；streaming gate 改为 base_url value；`DISABLE_PROMPT_CACHE=1` 真绕过 cache_segments；`WRITE_MAX_TOKENS` 支持运行时下调。
- `writer.py`：`WRITE_PROMPT_PROFILE=light` 轻量 prompt；已有上一章结尾时将过时 `opening_scene` 降级为短插叙，强制当前时间线为主体。
- `schemas/entity_advance.py`：容忍 `relationship_id` / `source_id,target_id` / `proposed_state` / `confidence=high|medium|low`；无法定位 src/dst 的高置信 proposal 在 auto-apply 下 no-op 跳过。

**验证**：
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests` → 394 OK（socket tests 需提权；普通沙箱 bind 127.0.0.1:0 会 PermissionError）。
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" bash scripts/verify.sh` → OK，mock-only，394 tests OK + auto-pipeline OK。
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 main.py preflight` → PREFLIGHT ok，FATAL none，WARN none。
- 进程检查：无残留 `write_book.sh` / `main.py write` / `plan-chapters` / `debate` 进程。

**下次从第三部后面重跑的注意点**：当前 `python3 main.py --book longzu show-start-point` 仍显示 no start point set。manifest volumes 包含 `longzu_1`, `longzu_2`, `longzu_3_1`, `longzu_3_2`, `longzu_3_3`, `longzu_4`, `龙族前传哀悼之翼`。如果用户说"第三部全部结束后"，候选命令是 `python3 main.py --book longzu set-start-point longzu_3_3`，然后重新生成 anchor / debate 或至少 `plan-chapters --force --require-start-point`，再 `write_book.sh --book longzu ...`。

### Iteration 027 P7 — bug-sweep code-review + 2 blocker 修复（2026-05-29 续）

对暂停后 bug-sweep diff(+713/-48, 21 改 + 2 新)按 standing instruction 跑 `/code-review high effort`(7 finder angles)。Dedup 后 8 项 finding,本轮闭环 2 个 blocker:

- **F1**(`src/auto_pipeline.py:174`)— `run_auto_pipeline()` 没把 `require_start_point` 传给 `generate_chapter_plan`,WebUI wizard + CLI auto-pipeline 都绕过 write_book.sh 起点门。修复:加 `require_start_point: bool = False` 参数(wizard 绿地启动保持 False);CLI `main.py auto-pipeline` 加 `--require-start-point` / `--allow-missing-start-point` 开关,power user 显式打开。
- **F2**(`scripts/write_book.sh:221`)— prune 失败被 `|| echo "[WARN]..."` 吞,retry 继续跑;改为 `if !; then exit 1; fi`,prune 失败即时退出。

**iter 028 待办(non-blocker)**:F3 config `int(WRITE_MAX_TOKENS)` 非数字崩 + try/except;F4 streaming gate base_url 规范化(trailing slash / scheme);F5 entity_advance invalid 高置信 proposal 静默跳过加日志;F6 起点一致性集中到 `src/start_point.py::enforce_consistency`;F7 一旦 F1/F6 落地,淘汰 writer.py opening scene 降级 prompt 这一 runtime 补丁;F8 抽 `_env_int` / `_env_bool` / `_env_choice` 到 config.py。

**测试**:395 tests 全跑(新增 1 个 F2 结构测试),5 个 socket sandbox 失败(无关,iter027 文档已记)。`tests.test_auto_pipeline` + `tests.test_smoke_scripts` 全绿。

**当前接力点**:longzu 仍 `no start point set`。等用户最终批准后,下一个 agent 的动作:
1. `python3 main.py --book longzu set-start-point longzu_3_3`
2. `python3 main.py --book longzu plan-chapters --chapters 30 --force --require-start-point`(真模型 gpt-5.5-high,~¥1-2)
3. 校验新 `chapter_plan.json` 的 `start_chapter_id` + 前 3 章 plot_purpose,确认起点正确
4. **不要**自己启动 `write_book.sh` 或 `auto-pipeline write` — 进真模型 30 章 write 前必须再向用户确认 budget / watchdog / dashboard 配置

---

## Phase 4 Status（iter 028，2026-05-30）

### Iteration 028 — 系统性 hardening（已完成，mock-only）

**目标**：把长程生产写作入口从 shell / WebUI / auto-pipeline 分叉收敛成可恢复、可审计、fail-closed 的稳定链路，避免 iter27 wrong-start、旧章节跳过、Reject 被当 done、真模型误跑和 reviewer fail-open。

**主要落地**：
- 新增 start point / plan / chapter item / draft / external review 指纹链：`start_point_fingerprint`、`plan_fingerprint`、`chapter_plan_item_fingerprint`、`draft_sha256`。
- `chapter_status()` 增加 strict mode：legacy meta、start/plan mismatch、draft hash mismatch、external review missing/reject/stale 都不算 approved。
- 新增 `src/book_runner.py::run_write_book()`：生产入口统一到 `write-book` 语义，做 start/plan/preflight gate、stale artifact archive、existing review recheck、blocked/succeeded/failed snapshot。
- Web 普通生产入口改为 `write-book`；raw writer 仅保留 `draft-once-dev`；wizard 绿地 onboarding 改为 `auto-pipeline-greenfield`；job 状态改为 `succeeded/blocked/failed/aborted/lost` 并落 `logs/web_jobs.jsonl`。
- reviewer fail-closed：`AgentReview.verdict` 收紧为 `Literal["Approve","Reject"]`；未知 verdict 不再默认 Approve；schema-invalid agent 走 simple fallback，否则 Abstain；全 Abstain 顶层 Reject。
- `LLMClient.complete_json()` 增加 schema-invalid repair；streaming base_url 做 URL normalization；polish 失败不阻断 draft/meta 落盘。
- 安全护栏：`.env.*` ignore（保留 `.env.example`）、tracked provider-key literal 清零、真实 smoke 需 `CONFIRM_REAL_MODEL_SMOKE=可以跑了` 或 `--confirm-real-smoke`、verify/test env scrub planner/runtime vars。
- optional data graceful degrade：坏 `entity_graph.json` → `{}`，坏 `global_facts.json` → `[]`，坏 personas → `None`，坏 style example 单文件跳过。
- KB 起点过滤只落 preflight WARN；未标成完全解决。

**验证**：
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock <bundled-python> -m unittest discover -s tests` → **404 OK**（本机 socket 权限；沙箱内 Web server bind 会 PermissionError）。
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` → **OK**，404 tests OK + mock auto-pipeline OK。
- `PATH="<bundled-python-dir>:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock python3 main.py preflight` → **PREFLIGHT ok**，FATAL none，WARN none。

**当前接力点**：
1. 真模型仍未跑；不要自动执行 `real_smoke.sh` / `debate_smoke.sh` / `write_smoke.sh`。
2. longzu 真长跑建议入口改为 `python3 main.py --book longzu write-book --chapters N` 或 Web `write-book`，而不是 raw `write` / generic `auto-pipeline`。
3. 如果继续从第三部后面重跑：先设置 start point、重生成/校验 plan fingerprints，再向用户确认 budget 后进 `write-book`。
4. 后续 P2：实现真正 `knowledge_for_start_point()` 安全 KB view + entity_graph timeline chapter marker schema WARN/升级。

---

## Phase 4 Status（iter 029，2026-06-02）

### Iteration 029 — 本地 Beta 上线入口：可靠“继续写书”按钮（mock-only）

**目标**：把 iter 028 的严格生产 runner 进一步产品化。本地单用户 Beta 不再要求用户理解 shell loop / Web step / strict status 的差异；入口统一为 `write-readiness → write-book`，先暴露阻塞原因与推荐命令，再启动续写。

**主要落地**：
- 新增 `python3 main.py write-readiness --chapters N [--resume-from M] [--replan-every K]`，输出 JSON：`status=ready|warn|blocked`、`blockers[]`、`warnings[]`、workspace-aware `recommended_commands[]`。
- `src/book_runner.py` 接管原 shell 生产语义：`max_retries`、budget ceiling、auto re-plan append、proposal-vs-plan 冲突检测、auto-advance、retry 归档与 rolling summary prune。iter029 code-review 后修复 replan window：readiness 只要求首个 replan window，runner 按 run offset 触发 append，append 成功后 reload plan，append 失败落 blocked snapshot。
- `scripts/write_book.sh` 改为薄 wrapper：兼容 `--book`、`--chapters`、`--max-retries`、`--budget-cny`、`--replan-every`、`--min-confidence`、`--no-auto-advance` 等参数，但不再包含 raw `main.py write` / `review-chapter` / `chapter-status` 循环。
- `write-book` CLI 扩展同一组参数；`budget_exceeded` 返回 exit 3，blocked 返回 exit 4。
- Web dashboard 增加“继续写书”主操作区：章节数、起始章、readiness 展示、阻塞原因、推荐命令、启动后 job polling。`draft-once-dev` 保留为开发 step，但不在普通 dashboard 主操作区展示。
- 既有 Reject / needs_human_review / stale external review 旧产物会让 readiness / write-book blocked；用户检查后可显式 `--force`，由 runner 归档后重写。

**验证进度**：
- Targeted Iter029 tests：`tests.test_book_runner tests.test_write_book_script tests.test_write_book_replan_budget tests.test_smoke_scripts tests.test_web_routes_get tests.test_web_jobs_dispatch` → 56 OK。
- `py_compile main.py src/*.py src/web/*.py tests/*.py` → OK。
- Full `unittest discover -s tests` → 412 OK（普通沙箱 5 个 Web socket bind 测试 PermissionError；提权后 OK）。
- `scripts/verify.sh` → OK，412 tests OK + mock auto-pipeline OK（普通沙箱 socket bind 失败；提权后 OK）。
- `python3 main.py preflight` → PREFLIGHT ok；FATAL none；WARN none。
- 本轮不跑真模型 smoke，不改 `.env`。

**当前推荐真模型长跑入口**：
1. `python3 main.py --book <name> write-readiness --chapters N`
2. 如 blocked 且原因是旧 plan / 指纹缺失：`python3 main.py --book <name> plan-chapters --chapters N --force --require-start-point`
3. 再跑 readiness，确认 `ready` 或只剩可接受 WARN。
4. 用户明确授权真模型与 budget 后：`python3 main.py --book <name> write-book --chapters N --budget-cny <ceiling> --replan-every K`

**后续候选**：
- 真模型 capstone（30-100 章）应从上述入口启动。
- 实现真正 `knowledge_for_start_point()` / KB 安全视图。
- entity_graph timeline schema 增加 chapter marker 并提供 preflight 升级提示。
- WebUI 下一步可做 draft review/edit、安全 KB view、长跑监控与成本仪表。

---

## Phase 4 Status（iter 030，2026-06-02）

### Iteration 030 — 本地 Beta 写作工作台（mock-only）

**目标**：把 iter 029 的可靠“继续写书”按钮升级成用户侧能理解的本地写作工作台。首页不再只是 workspace 链接列表；进入 workspace 后能按“设置起点 → 生成计划 → 检查就绪 → 继续写书 → 查看产出/阻塞原因”的顺序操作。

**主要落地**：
- 首页新增 `/api/workspaces/overview`：每本书显示原文章节数、起点、plan、草稿、review、最近 job、readiness。单本坏 plan/schema 错会显示 `blocked`，不会拖垮首页。
- workspace 详情页改为 cockpit：起点选择、plan job、write-book 参数、readiness、最近 job 置于首屏；status/cost/manifest/reviews/drafts 放入 tabs。
- 新增起点 API：`GET/POST /api/workspace/<name>/start-point`；保存后刷新 readiness。
- 新增只读产物 API：`/drafts` 与 `/draft/<chapter>`，展示章节正文、meta verdict、review verdict，不做在线编辑。
- 新增 `/jobs/recent`，从 `logs/web_jobs.jsonl` 恢复 terminal job；修复 job log 路径尊重 `paths.WORKSPACE_DIR`。
- Web `/run` 增加服务端参数校验；`write-book` 非法参数 400；`plan-chapters` 强制 `force=True` / `require_start_point=True`。缺起点/缺 outline 作为用户可修复 `blocked`，不标 `failed`。
- UI 从深色工程 dashboard 改成浅色紧凑工作台；普通页面仍不暴露 `draft-once-dev`。

**验证进度**：
- Targeted Web tests：`tests.test_web_routes_get tests.test_web_jobs_dispatch` → 36 OK。
- 其余全量验证见 iter 030 文档 Acceptance Result。
- 本轮不跑真模型 smoke，不改 `.env`。

**当前接力点**：
1. 用户体验入口：`.venv/bin/python3 main.py web` → `http://127.0.0.1:8765/`。
2. 从 workspace 页面设置起点后，可直接点“生成/重生成计划”；真模型配置下这一步可能产生费用，仍需用户自行确认 `.env` 与预算。
3. 真模型长跑仍建议先 CLI/Web readiness，确认只剩可接受 WARN 后再 `write-book --budget-cny <ceiling> --replan-every K`。
4. 后续候选：真模型 capstone、KB 安全视图、entity timeline schema、在线编辑/复审入口。

---

## Phase 4 Status（iter 031，2026-06-02）

### Iteration 031 — Web Cockpit hardening + handoff refresh（mock-only）

**目标**：按 post-iter030 subagent review 修复 Web cockpit 的两个结构性 bug，并降低本地 WebUI 打开/刷新时的 CPU/IO 峰值；同时校准 `AGENTS.md` 过期的当前迭代锚点。

**主要落地**：
- `/api/workspaces/overview` 现在做 per-workspace fault isolation：单本坏 `chapter_plan.json` / overview 采集异常只让该 workspace blocked，不拖垮首页。
- overview 增加 3 秒短 TTL cache，cache key 包含 workspace root、workspace 列表和关键文件/目录 mtime；设置起点后主动清 cache。
- `_load_persisted_job()` 改用 `paths.WORKSPACE_DIR`，与 `_job_log_path()` / `recent_jobs()` 保持 workspace isolation 一致。
- workspace 页面不再初始化时加载隐藏 tabs；reviews/manifest/status/cost 点击 tab 首次懒加载。write-book 参数输入改为 500ms debounce 后刷新 readiness。
- plan 按钮文案改为“重生成并覆盖计划”，避免误以为是 append/replan。
- `AGENTS.md` 当前阶段从 iter024 校准到 iter031；README badge / SOP、iteration index、iter031 文档同步。

**验证进度**：
- Targeted Web tests：`tests.test_web_routes_get tests.test_web_jobs_dispatch` → 38 OK。
- `py_compile` for touched Web/test modules → OK。
- `node --check /private/tmp/iter031_dashboard.js` → OK。
- Full `unittest discover -s tests` → 普通沙箱 5 个 Web socket bind `PermissionError`；提权后 421 OK。
- `scripts/verify.sh` → 普通沙箱同样 5 个 Web socket bind `PermissionError`；提权后 OK，421 tests OK + mock auto-pipeline OK。
- `python3 main.py preflight` → PREFLIGHT ok；FATAL none；WARN none。
- 非真模型计时样本：overview 首次约 145ms，TTL 内二次约 1.4ms；`xueZhong` cost 约 14.8ms，readiness 约 10.0ms。LiteLLM import 仍会尝试远程 cost map 后 fallback，是后续 lazy-import 候选。

**当前接力点**：
1. 用户体验入口仍是 `.venv/bin/python3 main.py web` → `http://127.0.0.1:8765/`。
2. 真模型长跑仍先跑 CLI/Web readiness，确认 `ready` 或只剩可接受 WARN 后，再由用户明确授权 budget 进入 `write-book`。
3. 后续候选：真模型 capstone、KB 起点安全视图、entity timeline schema、Web 在线编辑/复审、LiteLLM lazy-import + cost 增量索引。


---

## Phase 4 Status（iter 032，2026-06-02）

### Iteration 032 — WebUI 信息架构与视觉重做（mock-only）

**目标**：以产品经理视角审视 iter 025-031 累积的 WebUI 形态，把"所有功能堆在 `/workspace/{name}` 单页 + 5 个 tab"的混乱 IA 拆成结构清晰的多页 + 侧栏导航；同时引入一套统一的文学化暖色调设计系统，并新增 Chapter 详情页曝光已落盘但从未呈现的 reviewer 子分数 / lint anchor / advisor / rewrite 元数据。新功能页（Insights / Plan viewer / World viewer / 章节 diff）留给 iter 033。

**主要落地**：
- 新增 6 个工作区子路由：`/w/{name}/`、`/w/{name}/continue`、`/w/{name}/chapters`、`/w/{name}/chapter/{n}`、`/w/{name}/reviews`、`/w/{name}/jobs`。
- 旧 `/workspace/{name}` 保留为 **301 重定向**到 `/w/{name}/`；`server.py` sniff body 的 `data-redirect-to` 属性写出 `Location` header。
- `src/web/static.py` 完全重写：设计 tokens（米白纸面 + 墨色文字 + 翠青/赭橙 + 衬线标题）+ 统一组件库（btn / badge / card / tabs / breadcrumb / sidebar / kv-list / skeleton / empty-state / alert / toast）+ 9 个页面渲染器。保留 iter 026 / 030 测试要求的 6 个 JS 标识符（`loadTabPanel` / `scheduleReadiness` / `readinessRequestSeq` / `writeBookJobRunning` / `readinessTimer` / `submit.disabled = writeBookJobRunning || data.status === 'blocked'`）以减少改测试面积。
- `src/web/templates.py` 完全重写：引入 `_BASE_TPL` 基础壳（侧栏 + 顶部条 + main slot）+ 8 个页面模板 + `render_workspace(name)` 旧 API 别名转发到新 continue 页。
- 新增 **Chapter 详情页**（`/w/{name}/chapter/{n}`）：5 个 tab（正文 / 评审 / Lint / Advisor / 历史），把 `chapter_NN.meta.json` 全字段排版出来；reviewer 子分数横条（plot / prose / fidelity）、lint `rule_id` 分组、advisor type/section/guidance 卡片、rewrite_count 历史。支持 hash deep-link。
- `tests/test_web_routes_get.py`：改 1 用例（`/workspace` 现在 301）+ 新增 8 个 IA 覆盖用例；`tests/test_web_server.py` 新增 Location header 端到端测试。

**验证进度**：
- Targeted Web tests（沙箱安全集）→ 92 OK。
- Full `unittest discover -s tests` → 430 tests，**424 OK + 6 ERROR**（全部是沙箱 `socket.bind` `PermissionError`，影响 `test_web_server.*` 4 个 + `test_web_hardening.ServeHostWarningTests.*` 2 个，与本迭代改动无关；离开沙箱跑全绿）。
- dispatcher 级冒烟：9 个新页面路径全部返回 200；`/workspace/longzu/` → 301 且 `data-redirect-to` 正确。

**当前接力点**：
1. 用户体验入口仍是 `.venv/bin/python3 main.py web` → `http://127.0.0.1:8765/`；老书签 `/workspace/{name}` 会自动 301 到 `/w/{name}/`。
2. 真模型长跑仍先跑 CLI/Web readiness。
3. 后续候选（iter 033）：Insights 仪表盘（cost burn + cache 命中率 + 子分数热力图）、Plan viewer、World viewer、章节 diff、lint anchor → 正文跳转、Toast 通知接事件总线、暗色模式、章节全文搜索。


---

## Phase 4 Status（iter 033，2026-06-03）

### Iteration 033 — 工作区删除 + Insights + Lint 跳转 + Toast（mock-only）

**目标**：按 `docs/iterations/iteration_033_PLAN.md` §2 顺序补齐 WebUI 日常使用的 4 个缺口：工作区删除、Insights 数据页、lint anchor 跳正文、任务终态 toast。保持 iter 032 视觉 token，不引入真模型调用。

**主要落地**：
- 工作区删除：`POST /api/workspace/<name>/delete` 要求 confirm 字段逐字匹配 workspace 名；已有运行 job 时返回 409；成功后把 `workspaces/<name>/` 原子 rename 到 `workspaces/_trash/<name>__<ts>/`，清 overview cache，并由前端跳回书架显示 toast。Web/CLI 创建路径均把 `_trash` 设为保留名。
- Insights：新增 `/w/{name}/insights` 与 `/api/workspace/<name>/insights`，只读聚合 `llm_calls.jsonl` 的 per-chapter cost、按 model 的 cache_read/cache_write 命中率，以及 `chapter_NN.meta.json` / review JSON 的 reviewer sub_scores 热力表。
- Chapter 详情页 lint 跳转：正文渲染保留真实 source line 为 `data-line`；lint issue 优先读 deterministic linter 的 `line` 字段，fallback 到 numeric/object anchor；点击 lint 行切回正文并用 `.jump-highlight` 短暂高亮目标行。
- Toast：基础壳新增 `toast-stack`；job poll terminal status 和删除后跨页跳转都会显示通知。
- 修复一个既有生成 JS quote bug：`renderKV()` 拼接字符串现在通过 `node --check /tmp/iter033_app.js`。

**验证进度**：
- §4 四块命令原文输出已粘贴到 `docs/iterations/iteration_033_PLAN.md` §7；普通沙箱 `unittest discover` 仍为 446 tests + 6 个已知 `socket.bind PermissionError`。
- Targeted Web tests：`tests.test_web_routes_get tests.test_web_routes_post tests.test_web_insights tests.test_web_trash tests.test_web_naming` → 60 OK。
- Full `scripts/verify.sh`：普通沙箱同 6 个 socket bind error；提权后 446 tests OK + mock auto-pipeline OK。
- `python3 main.py preflight`（mock）→ PREFLIGHT ok；FATAL none；WARN none。
- Browser smoke：用 `/private/tmp` 临时 workspace 启动 WebUI，确认 `lint_issues: [{"line": 4, ...}]` 渲染成 `li[data-jump-line="4"]`；点击后 `#lint` → `#body`，目标 `data-line="4"` 为 `第二段有问题。`，并出现 `jump-highlight` 高亮。

**Subagent 审核**：
- Mendel 做了只读结构/程序审核，覆盖 soft delete、Insights、lint jump、toast、§7 输出。审核初始结论为 no-go，指出 lint jump 误读 `anchor` 而非真实 `line`；本轮已修复并补回测试/浏览器 smoke。
- 未修风险：删除 API 的 busy check 与并发 job start 之间仍有一个很窄的单用户本地竞态窗口。当前已拒绝已运行 job 的删除；未来若 Web 从单用户 Beta 升级，可在 jobs 层增加 delete reservation 做原子占位。

**当前接力点**：
1. 用户体验入口仍是 `.venv/bin/python3 main.py web` → `http://127.0.0.1:8765/`。
2. Web 现有主路径：`/` 书架 → `/w/{name}/` 概览 → 侧栏继续写 / 章节 / 评审 / 数据 / 任务；删除入口只放概览页，成功移入 `_trash`。
3. 下一步候选：Plan viewer、World viewer、章节 diff、全文搜索、暗色模式、Insights 增量索引/更多图表、真模型 capstone、删除与 job start 的原子 reservation。


---

## Phase 4 Status（iter 036，2026-06-03）

### Iteration 034-036 — Plan/Trash 收口 + drama module infrastructure（mock-only）

**目标**：iter 034/035 先把 Web Plan viewer、Trash restore/purge、delete race 与 P2/P3 防御纵深清干净；iter 036 在不触碰 drama 业务逻辑的前提下，让 WebUI 支持 type-aware workspace，为后续短剧模块开入口。

**主要落地**：
- iter 034：新增 `/w/{name}/plan` 只读 Plan viewer；Trash 页面支持 restore/purge；delete 与 job start 通过 reservation 收窄竞态。
- iter 035：trash helper 自防路径穿越/保留名；Plan viewer 5 处 `Array.isArray`；hash tab 白名单 `_ALLOWED_TAB_KEYS`；iter 034 Run Log 补 6-ERROR 沙箱注脚。
- iter 036：新增 `src/web/workspace_meta.py`，`workspaces/<name>/data/workspace.json` schema v1 记录 `type=novel|drama`；缺文件/坏 JSON 默认 legacy novel。
- `init_workspace(name, type="novel")` 会写 workspace meta；`type="drama"` 只额外创建 `data/tables/`、`outputs/{debate,episodes,reviews}/` 空目录。
- `/api/workspaces/overview` 返回 `type`，cache key 第一项加入 `workspace.json` mtime；书架卡片通过 `typeBadge` 显示 小说/短剧。
- `/wizard` 增加第 0 步类型选择；`POST /api/wizard/drama-start` 只创建空 drama 骨架，同步返回 `{name,type}`，不入 job 系统、不触发 LLM。
- `_WORKSPACE_SECTIONS` 保持 novel 7 项，新增 `_sections_for(type)`；drama 本轮只露 overview + jobs。
- drama overview 为占位页；continue/plan/chapters/chapter/reviews/insights 6 个 novel-only HTML 路由对 drama 返回 404；`POST /api/workspace/<drama>/run` 返回 400 + iter 037 hint。

**验证进度**：
- Targeted tests：`tests.test_workspace_meta tests.test_web_routes_get tests.test_web_routes_post tests.test_web_wizard_e2e` → 83 OK。
- Full `unittest discover -s tests` → 488 tests，仍为 6 个已知沙箱 `socket.bind PermissionError`。
- iter 036 §4 四块自检输出已粘贴到 `docs/iterations/iteration_036_PLAN.md` §7。
- 本轮不跑真模型 smoke，不改 `.env`，不触碰 drama agents/prompts/config 业务逻辑。

**当前接力点**：
1. drama workspace 当前只是空骨架 + 占位 overview；后续 iter 037 才接 drama bootstrap/plan。
2. novel workspace 仍按 legacy 缺 `workspace.json` 默认 novel；侧栏 7 项、wizard 上传、write-book 入口保持原行为。
3. Web 入口仍是 `.venv/bin/python3 main.py web` → `http://127.0.0.1:8765/`。


---

## Phase 4 Status（iter 037，2026-06-03）

### Iteration 037 — drama 4 站向导前 2 站 + 创作规范快照（mock-only）

**目标**：按 `docs/iterations/iteration_037_PLAN.md` §A 交付 drama 4 站审查向导前 2 站，让短剧 workspace 从“空骨架”推进到“可填 setup → 生成核心设定 → 生成/选择钩子”的 Web 本地闭环，同时把创作规范复制到 workspace 内做可复现 snapshot。

**主要落地**：
- `/wizard` 的 drama 分支升级为 5 字段表单：workspace 名、题材描述、5 赛道、集数、单集时长 30/60/90/120；提交后写 `data/wizard_input.json`，成功跳 `/w/<name>/write?step=setup`。
- drama workspace 创建时复制 `docs/product/short_drama_creation_standard.md` 到 `workspaces/<name>/data/creation_standard.snapshot.md`；后续 drama agents 只读 workspace 内 snapshot。
- 新增 `src/drama_planner.py`（站 ① 核心设定）与 `src/hook_designer.py`（站 ② 钩子），本轮仅 mock fixture-driven；`mock=False` 直接 `NotImplementedError("iter 040+")`，不接 `LLMClient`。
- 新增 `src/web/drama_view.py` 聚合 4 站状态；新增 `/w/<name>/write` 4 tab 页面，站 ③ 分镜 / 站 ④ 角色保持 “iter 038 起开放” empty-state。
- 新增 API：`GET /api/workspace/<name>/drama/progress`、`POST .../drama/plan`、`POST .../drama/hooks`、`PUT .../drama/setup`。
- `_SECTIONS_DRAMA` 升级为 overview / write / jobs；drama overview 升级为 4 站进度看板；`POST /api/workspace/<drama>/run` 继续 fail-closed 400。
- `config/agents.yaml` 新增 `drama_agents`（provider: `mock_only`）；新增 10 个 `tests/fixtures/drama/track_<pinyin>_<station>.json` 占位 fixture 和 2 个 `prompts/drama/*.txt` 占位 prompt。创作内容仍留给 Claude §B。

**验证进度**：
- Targeted tests：`tests.test_drama_planner tests.test_hook_designer tests.test_drama_view tests.test_drama_wizard_full_form` → 33 OK；`tests.test_web_routes_get tests.test_web_routes_post tests.test_web_wizard_e2e` → 90 OK。
- Full `.venv` unittest：536 tests OK。
- §4 dispatcher smoke：`/`, `/trash`, `/wizard`, `/settings`, novel overview/continue, drama overview/write/jobs 均 200；drama `/continue` 404。
- §4 JS string guard：30/30 identifiers present。
- §4 drama_planner + snapshot smoke：mock + snapshot OK；result track = 霸总。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0（536 tests OK + mock auto-pipeline OK）。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 main.py preflight` → PREFLIGHT warn；FATAL none。
- 裸 `bash scripts/verify.sh` 在本机系统 `python3` 下因缺 `pydantic` 出现 import errors；使用 `.venv` 路径后通过，判定为环境解释器问题。

**当前接力点**：
1. Claude §B 将在 Codex commit 后替换 10 个 fixture + 2 个 prompt 为真实创作内容；Codex 不读不改这些创作内容。
2. iter 038 候选：站 ③ 分镜、站 ④ 角色、AI 绘画 client / Comfy 导出。
3. 真模型接入仍 deferred 到 iter 040+；本轮 drama agents 保持 mock-only。


---

## Phase 4 Status（iter 038，2026-06-04）

### Iteration 038 — P1/P2 hardening pass（sandbox skip / hook leak / test fixture extraction）

**目标**：按 `docs/iterations/iteration_038_PLAN.md` §A 做纯工程修补，不新增页面/API/fixture/prompt，不触碰 drama 创作内容；核心是把连续 6 轮的沙箱 Web socket bind 6 ERROR 清零，并修掉 drama hook picker listener 堆叠与 rapid-click race。

**主要落地**：
- 新增 `tests/_socket_skip.py`，`ServerTests` 与 `ServeHostWarningTests` 用 `@skipIf` 在 socket bind 被 sandbox 禁止时优雅跳过；同时 probe loopback 与 wildcard bind，避免 `0.0.0.0` 单独被禁时仍 ERROR。
- `src/web/static.py` 的 hook picker 从每次 render 绑定 `pane.addEventListener("click")` 改为 `bindHookPickDelegate()` document-level 单次事件代理；候选 hooks 存到 `pane.__hooks`；点击候选后立即禁用所有 `[data-hook-pick]` 按钮，失败再恢复。
- `loadTabPanel` 保留函数名但改为 async/await，并对 JSON parse failure 给明确错误；pending toast 新增 `setPendingToastAndNavigate()`，替换删除 workspace 与 drama wizard 创建后的两处跨页 toast。
- `renderPlanChapters` 增加 `Array.isArray(draftChapters)` 外层兜底。
- 新增 `tests/_drama_base.py::DramaTestBase` + `_make_drama_workspace()`，抽掉 3 个 drama 测试文件重复 setUp/tearDown。
- `workspace_meta.write()` 改为临时文件 + atomic replace；测试补并发 read/write、BOM/截断 JSON、非 UTF-8 fallback。
- `_safe_entry_path` 补空串、null byte、过长、Unicode NFC 边界测试；`hook_designer.run()` 对 station ① 输出缺 `core_setup.protagonist` 明确 raise；`workspace_ctx` 增加 thread-safety contract 与路径级 thread isolation 测试。

**验证进度**：
- Full `.venv` unittest：549 tests，**OK (skipped=6)**；原 Web socket bind backlog 从 ERROR 变 skip。
- Targeted socket suite：14 tests，**OK (skipped=6)**。
- JS guard：33/33 identifiers present；`Array.isArray(` count = 6。
- Dispatcher smoke：`/`, `/trash`, `/wizard`, `/settings`, novel overview/continue, drama overview/write/jobs 均 200；drama `/continue` 404。
- `scripts/verify.sh`（mock env scrub）→ exit 0；`python3 main.py preflight`（mock env scrub）→ PREFLIGHT ok，FATAL none，WARN none。
- `node --check /private/tmp/iter038_app.js` 与 `/private/tmp/iter038_wizard.js` → OK。

**Subagent 审核**：
- Wegener 做了只读 diff/static review，覆盖 A1-A11。初始结论 Go，无 blocker。
- 审核指出 1 个 P3：socket skip helper 只 probe loopback，而 `ServeHostWarningTests` 也 bind `0.0.0.0`。本轮已补 `SOCKET_WILDCARD_BIND_BLOCKED` 并复跑 targeted suite。
- 未修风险：无本轮 blocker。drama 站 ③/④、AI 绘画、drama_reviewer、真模型接入仍不在本轮范围。

**当前接力点**：
1. 本轮纯工程已收口；不要 push，等用户按 V1-V12 验收。
2. 下一步功能候选仍是 drama 站 ③ 分镜 / 站 ④ 角色 / AI 绘画 client / Comfy 导出 / drama_reviewer。
3. 真模型接入仍 deferred 到 iter 040+；继续遵守真模型 smoke 必须等用户明确授权。

---

## Phase 4 Status（iter 039，2026-06-04）

### Iteration 039 — WebUI 小说续写真实链路修复（mock-only）

**目标**：严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 修复 WebUI 真实续写链路的 P0/P1 问题，让 `write-readiness -> write-book` 在前端可观测、失败可恢复、预算可章内止损。

**主要落地**：
- `recent_jobs()` 修复 persisted running/pending 的 lost 判定：内存中仍有 live job 时保留 running/progress，只有 process restart 后查不到内存 job 才标 lost。
- `writer.write_chapters()` 新增 `progress_cb` 与 `budget_check_cb`；章内最小进度点覆盖 write attempt、review attempt、review done、polish、finalize；book_runner 映射成 `chapter-N/sub_step` 全局 progress。
- writer 在异常路径维护最新非空 draft，写出 `chapter_NN.partial.md` 与 `chapter_NN.failure.json`（attempt、last_error、draft_sha256、stage、draft_path），book_runner 的 failed/budget_exceeded snapshot 与 Web job summary 透传 `partial`。
- 新增 `BudgetExceeded`，book_runner 用 `estimate_cost_since(initial_log_lines)` closure 在 write/review/polish 与外层 review_target 后检查预算，超限返回 `budget_exceeded`。
- Web 前端新增 `jobBlockedDetail()` / `jobFailureLine()`；sidebar、pollJob terminal alert/toast、jobs 页 note 优先展示 `result_summary.first_blocked`。
- `/api/workspace/<ws>/draft/<chapter>?variant=partial` 可读取 partial draft；`/drafts` 列出 final/partial variant；chapters 页显示 `partial` / `failure` 标签；terminal job box 展示 partial draft 链接。
- `WRITER_FORCE_FAIL=1` 的 mock-only hook 改成在 write 后抛出携带 partial draft 的异常，用于无成本 smoke partial artifact 路径；仍需 `OPENAI_MODEL=mock`。

**验证进度**：
- P0-A/B/C/D 每个子项后均跑 `.venv/bin/python -m unittest discover`，从 551 到 554 tests，均 `OK (skipped=6)`。
- 最终 full `.venv/bin/python -m unittest discover` → 557 tests，`OK (skipped=6)`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，557 tests `OK (skipped=6)` + mock auto-pipeline OK。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → PREFLIGHT ok，FATAL none，WARN none。
- `node --check /dev/stdin` for `JS_DASHBOARD` → OK。
- Mock Web smoke：`OPENAI_MODEL=mock WRITER_FORCE_FAIL=1` 启 Web，`iter039smoke` write-book 返回 failed + `result_summary.partial`，`chapter_01.partial.md` / `chapter_01.failure.json` 落盘，partial API 200；`iter039blocked` plan-chapters 显示 `outline_missing` blocked reason。截图：`/private/tmp/iter039_jobs_outline_missing.png`、`/private/tmp/iter039_chapters_partial.png`。
- 真模型 Web 验收（用户授权后）已跑 `longzu`：前端 `plan-chapters` 成功；`write-book chapters=1 resume_from=2 budget_cny=10 max_retries=2` 终态 `blocked`，`first_blocked.reason=retry_exhausted`，blocked reason 在 continue/jobs 等页面可见，running 期间未误标 lost，成本约 ¥4.6467。happy path approved 未通过。
- 真实验收暴露 P0-C 补丁：外层章节 retry 时 progress 会从 `finalize` 回到 `write-attempt-*` 造成视觉倒退；iter039 追加补丁在 `book_runner` 章节 progress 闭包内做单调钳位，并为 retry 子 step 加 `retry-K/` 前缀。

**Subagent 审核**：
- Gibbs 做了只读结构审核，覆盖 P0 recent_jobs/progress/partial/budget、P1 blocked/partial UI、测试与 protected scope。结论：无 blocking findings、无 protected scope 违规。
- 审核提出 3 点已修复：polish 路径预算检查缺口、write-book 返回式失败 summary 未透传 error、成功 final draft 后旧 `.partial.md` 孤儿文件会继续显示为 failure。修复后补回 targeted tests 与 JS syntax check。

**当前接力点**：
1. 不要 push，等用户验收。
2. 真模型 happy path approved 仍未通过；下一轮若继续真实链路，应从 `longzu` ch2 `retry_exhausted` 结果和 reviewer/meta 判定差异切入。
3. iter040 backlog：P2-A/B/C（Jobs 展开详情、sidebar lost 历史标记、onboarding budget/timeout/cancel）、drama 站 ③/④、AI 绘画 client / Comfy 导出、drama_reviewer、章节 diff、全文搜索、KB 起点过滤安全视图、真模型 capstone。
4. iter040 backlog 新增真实验收发现：`chapter_02.meta.json` 顶层 `verdict=Reject`，但 `outputs/reviews/chapter_02.review.json` 顶层 `verdict=Approve`，最终 strict `chapter_status` 仍判 blocked。证据 job `a9fe3502ed0e438a82ada58ea78b8982`；证据路径 `workspaces/longzu/outputs/drafts/chapter_02.meta.json` + `workspaces/longzu/outputs/reviews/chapter_02.review.json`。

---

## Phase 4 Status（iter 040，2026-06-04）

### Iteration 040 — meta/review verdict 同步 + 龙族 ch2 真实 incident 归因

**目标**：严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter040 plan，只修 P0-A：external review 完成后把最终 verdict 回写到 writer meta，消除 iter039 暴露的 `chapter_02.meta.json=Reject` / `outputs/reviews/chapter_02.review.json=Approve` 双文件不一致。

**主要落地**：
- `src/book_runner.py` 新增 `_sync_meta_with_external_review(drafts_dir, chapter_no)`，同步 `verdict`、`needs_human_review`、`agent_reviews`、`external_synced_at`。
- external review 缺 `needs_human_review` 时，`Approve -> False`，其他 verdict -> True；external `Approve` 时清空 `last_blocking_reasons`。
- 保留 writer 历史字段：`run_context`、`draft_sha256`、`polish_*`、`lint_blocked_reviews`、`chinese_char_count`、`rewrite_count` 等。
- 两个调用点均已接入：`reviewed_existing` 路径的 `review_target()` 后，以及每章新写路径的 external `review_target()` 后。Subagent audit 后把 normal write path 调整为先 sync 再做 post-review budget check，避免“review 已落盘但预算超限导致 meta 未同步”。
- 新增 `tests/test_book_runner_meta_sync.py`，用 subTest 覆盖 meta Reject + review Approve、meta Approve + review Reject、sync 后 strict `chapter_status(validate_context=True, require_external_review=True)`，以及 post-review budget_exceeded 仍先 sync meta。

**验证进度**：
- `.venv/bin/python -m unittest tests.test_book_runner_meta_sync` → 1 test OK。
- `.venv/bin/python -m unittest tests.test_chapter_status tests.test_book_runner tests.test_book_runner_retry_progress` → 17 tests OK。
- Audit follow-up targeted：`.venv/bin/python -m unittest tests.test_book_runner_meta_sync` → 1 test OK；`.venv/bin/python -m unittest tests.test_book_runner tests.test_book_runner_partial tests.test_book_runner_retry_progress tests.test_write_book_replan_budget` → 18 tests OK。
- `.venv/bin/python -m unittest discover` → 559 tests，`OK (skipped=6)`。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`，FATAL none，WARN none。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，559 tests `OK (skipped=6)` + mock auto-pipeline OK。

**真实模型验收（用户授权预算 < 10 元）**：
- 备份原 ch2 到 `/tmp/iter040_baseline_20260604_194612/`，删除指定 draft/meta/partial/failure/review 文件后，通过 Web API 跑 `longzu` `write-book chapters=1 resume_from=2 budget_cny=10 max_retries=2`。
- job_id `d526d330267648869006869de5a15872`，终态 `blocked`，`first_blocked.reason=retry_exhausted`，snapshot `workspaces/longzu/outputs/drafts/snapshots/write_book_blocked_20260604_210821.json`。
- 最终 meta/review verdict 均为 `Reject`，`draft_sha256` 一致，meta 写入 `external_synced_at=2026-06-04T13:08:21+00:00`。
- strict `chapter_status` 返回 `approved=false`，`strict_failures=["external_review_reject"]`。这证明 iter039 的 verdict 不一致 bug 已修；本次 blocked 是 external review 自身 Reject。
- 成本增量：以 run 前 `longzu` logs 899 行为 offset，83 calls，prompt 1,731,936 tokens，response 227,680 tokens，`cost_cny=5.1701`。低于授权 10 元，高于 happy-path 目标 5 元。
- 内容 incident：external review 票面 4 Approve / 1 Reject，但 reviewer fail-closed 规则使总体 Reject；主要 rule_ids 包括 `tone_balance`、`norma_authority_consistency`、`protagonist_agency`、`mystery_pacing`、`worldbuilding_logic`、`character_fidelity`。

**Subagent 审核**：
- Faraday 做了只读 diff/static review，覆盖 `book_runner` helper/call sites、`chapter_status`、`reviewer.review_target`、新测试与真实验收结论。结论：无 blocking findings。
- 审核确认 helper 保留 writer-owned meta 字段，测试覆盖核心 P0-A plan。
- 审核提出的 budget-after-review stale-meta 风险已修；未修风险为“已有历史 mismatch 不自动自愈”和“external Approve 清空 `last_blocking_reasons` 是设计取舍”。

**当前接力点**：
1. P0-A 已收口，不要回退 `chapter_status` / `writer` / `reviewer` 契约。
2. `longzu` ch2 happy path approved 仍未通过，但不再是 meta/review sync bug；后续若继续，应作为内容质量/reviewer 阈值/prompt 调整问题单独开 iter。
3. iter041 候选：P0-B writer pending_external_review 保险、龙族 ch2 内容 incident、iter039 P2-A/B/C、drama 站 ③/④、AI 绘画 client / Comfy 导出、drama_reviewer、章节 diff、全文搜索、KB 起点过滤安全视图。

---

## Phase 4 Status（iter 042，2026-06-04）

### Iteration 042 — happy path 跑通 + 打分制三档（兼容版）

**目标**：严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter042 plan，修复 external review source context 漏传，微调 `原作风格模拟` fail-closed prompt，引入兼容版 `high/mid/low` reviewer 阈值，并在真实 `longzu` ch2 上跑通 `tier=mid` happy path。

**主要落地**：
- `reviewer.review_target()` 扩展 `knowledge/source_chapters/scene_excerpts/tier` 参数，透传 `review_text()`；`book_runner._build_review_context()` 复用 writer 同款起点前 K 章 + scene excerpts 逻辑，external review 两个调用点与 writer shadow review 均补齐 source context。
- 仅调整 `config/agents.yaml` 的 `原作风格模拟` prompt：source_chapters 存在时先对照原文；明显 AI 腔、严重 voice drift、背离作者文风才 Reject，密度/留白/台词端正等主观项降级为 Approve + major issue。
- 新增 `src/review_tier.py`：`high` = 5 Approve + 8.5，`mid` = 4 Approve + 7.5，`low` = 3 Approve + 6.5；默认 `mid`，显式参数优先，`WRITE_REVIEW_TIER` 为兜底。
- reviewer 5-agent panel aggregation 改为 `approve_count + panel_score`；report 与 writer meta 同步写 `tier/panel_score/approve_count/tier_thresholds`；CLI `write-book --tier`、Web job param、`run_write_book()`、writer、external review 链路均透传。
- `book_runner._auto_apply_advances()` 在 approved chapter 后遇 `FileNotFoundError/IndexError/ValueError` 降级为 no-op，记录 `no_op_reason=apply_advance_failed`，避免缺失关系 proposal 把已通过章节拖成 failed。

**验证进度**：
- Targeted：`tests.test_book_runner_review_context` → 1 OK；§C targeted suite（review tier / aggregation / book_runner tier flow / web jobs / reviewer / writer / book_runner）→ 74 OK。
- `.venv/bin/python -m unittest discover` → 569 tests，`OK (skipped=6)`。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，569 tests `OK (skipped=6)` + mock auto-pipeline OK。
- Tier smoke：当前仓库无 `python -m src.cli --workspace` 入口，使用等价 `OPENAI_MODEL=mock WRITE_REVIEW_TIER=mid .venv/bin/python main.py --book iter029_beta_ok write-book --chapters 1` → `status=succeeded` strict skip。
- High regression：`OPENAI_MODEL=mock WORKSPACE_NAME=iter029_beta_ok WRITE_REVIEW_TIER=high` 对 approved ch1 跑 `review_text()` → `Approve`，`tier=high`，`panel_score=9.0`，`approve_count=5`。

**真实模型验收（用户授权预算 < 5 元）**：
- 备份原 ch2 到 `/tmp/iter042_baseline_20260604_231801/`，删除指定 draft/meta/partial/failure/review 文件后，通过 Web API 跑 `longzu` `write-book chapters=1 resume_from=2 budget_cny=10 max_retries=2 tier=mid`。
- 第一次 job `6cf6d93d3779438ab931ee287edd68c2` 的写作 + external review 本体已通过：meta/review verdict 均 `Approve`，`draft_sha256=6b3ce89672f0259bd0258801df179892ebf6d49c98297383a88d42929d864865`，`tier=mid`，`panel_score=7.58`，`approve_count=4`，阈值 `4 / 7.5`，strict `chapter_status` 为 `approved=true` / `strict_failures=[]`。
- 成本增量：以 run 前 `longzu` logs 982 行为 offset，15 calls，prompt 322,014 tokens，response 35,736 tokens，`cost_cny=0.909`。
- 第一次 job 在 approved 后 auto-advance tail 因缺失关系 `char_lu_mingfei <-> org_cassell_college` 抛 `ValueError`，status 被拖成 `failed`；本轮补 no-op 防御后，第二次 job `4e7a02d9a7334964818b503807460e1e` 复跑同参数走 `skipped_approved`，终态 `succeeded`，snapshot `workspaces/longzu/outputs/drafts/snapshots/write_book_succeeded_20260604_233443.json`。

**Subagent 审核**：
- Darwin 做了 §C read-only 审核，无 blocking findings。
- 审核确认 `reviewer.panel_score -> writer.meta.panel_score -> review_tier thresholds` 链路一致，`WRITE_REVIEW_TIER` / CLI / Web job param / `run_write_book` / writer / external review / `review_text` 参数链路一致，旧 workspace 缺 `tier/panel_score/approve_count` 不影响 `chapter_status` 与 Web aggregation 读取。
- 未修 P2：部分 Insights/UI 仍偏读 legacy `sub_scores` 命名，后续建议兼容 `scores || sub_scores`；本轮不改前端 UI。

**当前接力点**：
1. iter042 已让 `longzu` ch2 在 mid 档真实 approved；不要回退 source context、tier aggregation、meta/review sync 契约。
2. iter043 backlog：N3 WebUI 重构、drama UX、iter039 P2-A/B/C（Jobs 展开详情、sidebar lost 历史标记、onboarding budget/timeout/cancel）、tier UI 入口。
3. 其他候选：Insights/UI `scores || sub_scores` 兼容、auto-advance 缺失关系 proposal 的上游校验/清理、writer `pending_external_review` fallback、drama 站 ③/④、AI 绘画 client / Comfy 导出、章节 diff、全文搜索、真模型 capstone、KB 起点过滤安全视图。

---

## Phase 4 Status（iter 043，2026-06-05）

### Iteration 043 — WebUI UX Audit + UX 重构 Bundle 1+2（mock-only）

**目标**：先按 §A read-only audit 找出 WebUI 高 ROI UX 问题，再按用户选定的 Bundle 1+2 实施 D-1/D-2/D-3/D-4/D-6；全程 `OPENAI_MODEL=mock`，不跑真实模型，不 push。

**主要落地**：
- §A 新增 `docs/iterations/iteration_043_UX_AUDIT.md`，覆盖小说 continue/plan/chapters/reviews/jobs/dashboard 错误态、drama wizard/workspace/debate/subscore、新书 onboarding、导航/错误态/密度/表单/sidebar，并产出 D-1..D-8 方向与 3 个实施 bundle。
- D-1 readiness 增加 `next_unapproved_chapter` / `primary_blocker`，前端改为“主 CTA + 紧凑状态 + 折叠诊断”；`longzu` 这类历史 ch1 Reject / ch2 Approve 状态默认引导到 ch3。
- D-2 jobs 页增加展开 drawer、`jobActionableSummary`、snapshot/trace/partial 链接、partial preview modal 与“相同参数重试”，复用现有 `/run` 和 partial draft API。
- D-3 书架与 workspace overview type-aware；drama 返回 `drama_progress`；recent jobs sidebar 拆成当前/最近完成与历史，历史降权；顺手清掉 type badge / metric inline style。
- D-4 write-book 表单新增试写/生产/严格 preset、`tier=low/mid/high` 选档器与高级参数 `<details>`；后端缺省 tier 归一为 `mid`，非法 tier 返回 400。
- D-6 drama shell 收口：novel-only drama 页面改完整 shell empty-state HTTP 200，清过期 iter 文案，wizard placeholder 改实际示例，toast 支持 5000ms 可 dismiss。

**验证进度**：
- `.venv/bin/python -m unittest discover` → 577 tests，`OK (skipped=6)`。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0，577 tests `OK (skipped=6)` + mock auto-pipeline OK。
- `rg "placeholder, see creation_standard|iter 03[0-9]" src/web/` → 无结果。
- Web 截图回归目录：`/tmp/iter043B_screenshots_20260605_005741/`，覆盖 readiness CTA、write-book preset/tier、jobs drawer/partial modal、drama empty shell。

**Subagent 审核**：
- §A：James 做了只读结构/程序性审核，确认 UX_AUDIT §0-§6 齐备、5 条 journey 与 drama 章节均覆盖，read-only/upload limitation 已说明，无 blocking。
- §B：Bacon 做只读结构/程序性审核，范围覆盖 CTA_ACTIONS、jobs summary 职责、drama shell 200、iter038 P3 4 项清债、旧 workspace type fallback。结论 non-blocking；指出 drama overview type badge inline 残留，已补为 `badge-drama` 并用 targeted route tests + grep 复验。

**当前接力点**：
1. iter044 建议优先做 Bundle 3：D-5 onboarding budget/timeout/cancel、D-7 form/mobile density、D-8 Insights `scores || sub_scores` + subscore inline。
2. iter044 同步做 AGENTS.md 全面刷新，把 iter039-043 的 WebUI/tier/drama 状态纳入新入口锚点。
3. 本轮 deferred：subscore inline 剩余样式债、`_workspace_html_guard_novel_only` 抽象、真实模型 capstone、drama 站 ③/④、AI 绘画 client / Comfy 导出。

---

## Phase 4 Status（iter 044，2026-06-05）

### Iteration 044 — 收尾轮（D-5/D-7/D-8 + 文档刷新，mock-only）

**目标**：严格按 `/Users/dingyuxuan/.claude/plans/codex-iteration-039-webui-cozy-charm.md` 的 iter044 plan，把 iter043 §A audit 中剩余 Bundle 3 长尾收掉：onboarding critical path、移动响应式、subscore/UI schema 兼容，以及 AGENTS/README/HANDOFF/iteration index 文档刷新。

**主要落地**：
- D-5 后端协作式 cancel：`src/web/jobs.py` 新增 `cancel_requested` / `cancel_reason`、`JobCancelled` / `JobTimeout`、`request_cancel()`；worker 在开始、progress callback、handler 返回后三处检查，timeout 走同一 `aborted` 终态，不强 kill 线程。
- D-5 路由：`POST /api/workspace/<ws>/job/<id>/cancel` 只允许 `pending/running`，terminal job 返回 409，未知 job 404。
- D-5 wizard：小说 onboarding 增加 budget CNY / timeout minutes / extract limit；drama wizard 同步存 budget/timeout；进度页按 running/succeeded/failed/aborted 给 CTA 组，并提供取消按钮。
- D-7 mobile：共享 shell 增加 hamburger、sidebar overlay、topbar `...` actions menu；768px 以下 sidebar 改 drawer，jobs/chapters/reviews table 进入横向滚动容器并带滚动阴影提示。
- D-8 UI debt：Insights subscore table 的 inline cell style 改为 `.subscore-cell-*` class；chapter detail 与 Insights 聚合均兼容 `scores || sub_scores`，覆盖 iter042 schema 演进风险。
- 文档：AGENTS.md、README.md、docs/AGENT_HANDOFF.md、docs/iterations/README.md 对齐到 iter044；外部 plan 已归档为 `iteration_044_PLAN_DRAFT.md`，执行档案为 `iteration_044_PLAN.md`。

**Backlog 状态**：
- iter039 P2-C onboarding budget/timeout/cancel：✅ done（iter044 §A）。
- iter038 P3 / iter042 subscore UI debt：✅ done（iter044 §C）。
- `_workspace_html_guard` 抽象：保留 iter045+ backlog。本轮阅读后未发现低风险且收益明显的抽象点，未强行改。
- F1 二次 prompt 调优：仍 deferred，仅在后续真实 mid 档再次卡住时单独开。

**验证进度（截至文档刷新前）**：
- Targeted cancel/job route suites：`tests.test_jobs_cancel tests.test_routes_job_cancel tests.test_web_jobs_dispatch tests.test_web_routes_post` 通过。
- Targeted wizard/mobile/static suites：`tests.test_web_routes_get tests.test_web_wizard_e2e tests.test_drama_wizard_full_form tests.test_jobs_drawer tests.test_static_subscore_compat tests.test_web_insights` 通过。
- Final acceptance：`.venv/bin/python -m unittest discover` → `590 tests OK (skipped=6)`；`OPENAI_MODEL=mock .venv/bin/python main.py preflight` → `PREFLIGHT: ok`；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → exit 0。
- 移动 + cancel 截图回归：`/tmp/iter044_mobile_screenshots_20260605_020931/`，覆盖 iPhone 13 + iPad 的 B/C/D/E journeys；`iphone13_cancel_aborted.png` 显示 mock 模式、`aborted/cancelled`、取消原因与重新开始/返回书架 CTA。
- Subagent read-only audit：Laplace 初审发现 cancel terminal race、JS empty `scores` fallback、runtime mode label 与文档 placeholder；本轮 final patch 已修。保留的已知限制：cancel/timeout 为协作式，长时间无 progress 的 handler/provider call 仍要等下一 checkpoint 才进入 `aborted`，不强 kill worker。

**当前接力点**：
1. 本轮完成后不要 push，等用户验收。
2. Web 当前生产入口：`/` 书架 → `/w/{name}/continue` 的 `write-book` preset/tier；新建书走 `/wizard`，可设置高级选项并在进度页 cancel。
3. 后续功能面建议从 drama 站 ③/④ 或章节 diff / 全文搜索中选择；不要把 `_workspace_html_guard` 抽象当 blocker。

---

## Phase 4 Status（iter 045，2026-06-05）

### Iteration 045 — 投资人 demo 落地页 + demo 路径美化（mock-only）

**目标**：为投资人演示新增一个落地页（根 `/`），用两张同等卡片介绍【小说续写】与【剧本生成（Beta）】两大功能并分别进入；对 demo 路径页面做轻度美化。沿用「文学暖色·米纸」设计系统（jade `#3F6B5A` / amber `#C97B3D` / 米纸 `#FBF7F0`，标题衬线），不动后端逻辑，0 新前端依赖。执行档案 `iteration_045_PLAN.md`，外部 plan `~/.claude/plans/splendid-skipping-trinket.md`。

**主要落地**：
- 路由：`/` 改为新 `render_landing()` 落地页（全屏、无 sidebar）；书架迁到 `/library`（`render_index` 不变）。16 处书架面包屑/链接 + jobs drawer 两处「返回书架」+ 删除成功跳转，全部 `/` → `/library`。
- 落地页：`templates.render_landing()` = 品牌 hero（内联 SVG logo + slogan）+ 小说续写/剧本生成（Beta）双卡片 + 信任区 serif 大数字；`_LP_LOGO_SVG` 品牌标；`_BASE_TPL` 加 inline-SVG favicon。纯 CSS 零 JS，规避 `string.Template` 的 `$` 坑。
- CSS：`.lp-*` 全套 + jade→amber 极淡 hero 渐变 + `lp-fade-up` 入场动画（含 `prefers-reduced-motion`）+ `@media 768` 单列堆叠；review/advisor 全局可读性 polish（subscore 8px、verdict badge 700、advisor 竖条）。
- wizard `?type=drama` 深链（`JS_WIZARD`）：drama 卡片直达 drama 表单。

**Code review（/code-review high）**：1 个 blocker 当 iter 修——删除 workspace 成功跳转 `setPendingToastAndNavigate(..., "/")` 漏改、会落到落地页 → 已改 `/library`（全仓复查为唯一遗漏）。backlog（→iter046+）：`.lp-metrics .tile` 复用 `.metric-pair .tile`、favicon 抽 `_FAVICON_SVG` 常量、`/library` 抽 `_LIBRARY_URL` 常量、`test_web_server::test_index_html` 命名过期。

**验证进度**：
- 相关测试 `tests/test_web_routes_get.py tests/test_web_server.py` → 64 passed（新增 `test_landing_is_root`，原 index 测试迁 `test_library_lists_workspaces`）。
- 全量 `pytest tests/` → 588 passed；3 failed 均既有、与本轮无关（`test_env_isolation` + `test_llm_client_cache`，stash 验证 baseline 同样红）。
- curl 逐页自检：`/`(落地页)、`/library`(书架)、`/wizard?type=drama`、`/w/longzu/chapter/2`、`/reviews`、`/insights`、`/w/i38drama01/`、`/wizard`、`/settings` 全 200，无 500/Traceback。
- 本环境 preview MCP 浏览器网关不可用 → 验证走 HTTP/API 层 + 自包含 HTML 预览；未做浏览器截图回归，建议有浏览器时补落地页 + `?type=drama` + 章节详情视觉回归。

**当前接力点**：
1. **Web 生产入口已变**：根 `/` = 投资人落地页；书架迁到 `/library`；`/w/{name}/continue` 续写主流程不变。引用「`/` 是书架」的旧文案需按此更新。
2. demo 前测试 workspace 清理：提供一键软删命令（保留 longzu + i38drama01），未自动执行，留用户 demo 前运行（可恢复）。
3. PPT 以「可粘到新 session 的提示词」交付，不在本仓。
4. 关联 robustness backlog（来自本轮前的只读前端实测，与落地页无关）：auto-pipeline succeeded vs 章节 Reject 语义、被拒章节前端无 force 出口、blocked 运行不报告 cost、短中文样本 `en_` 前缀——择机进后续 iter。

## Phase 4 Status（iter 048a，2026-06-09）

### Iteration 048a — 小白四步工作台·后端骨架（premise + prepare 复合 step + 测 Key，mock-only）

**目标**：iter048「小白四步封装」经对抗红队拆为串行子迭代（048a 后端骨架 → 048b 前端工作台+大纲回写 → 048c 细纲只读+重生成+写书兼容）。048a 取最干净的后端三件——premise「一句话开书」入口、`prepare-greenfield` 复合 step（9 步 SOP 前 6 步封成单 job）、全 task 测 Key 矩阵。无前端、无指纹链。执行档案 `iteration_048a_PLAN.md`。

**主要落地**：
- `auto_pipeline._run_prepare_steps`：抽出前 6 步（normalize→apply-bootstrap），`total`/`emit_done` 参数化进度分母；`run_auto_pipeline` 调它传 `total=9,emit_done=False`，9 步契约 + `("done",1.0)` 哨兵 byte-identical（`test_auto_pipeline` 守门）。
- `jobs._step_prepare_greenfield`（`total=6,emit_done=True`，6 步重映射到自含 0→1.0 进度条，修正红队点名的「卡 5/9」分母 bug）+ `STEP_HANDLERS["prepare-greenfield"]`。
- `wizard.start_premise_workspace`：JSON 入口，premise 校验（1-2000 字）+ 包装为 `第一章 缘起\n\n{premise}` 写 `小说txt/seed.txt`（splitter 靠章节标题分章，裸 premise 会 0 章 → 这是计划「非空即≥1 章」假设的实测修正）+ 路径越界防御 → 202；routes 注册 `POST /api/wizard/premise-start`。
- `llm_client.ping()`（mock 短路零联网 / `max_tokens=1` / error redact api_key）+ `web/diag.collect_model_diagnostics()`（`TASKS` 去重各 ping 一次）+ routes 注册 `GET /api/diag/models`。

**对抗审核（铁律⑨，3 视角）**：视角A（subagent，pipeline 重构+进度契约）= 与 `HEAD~1` AST 逐行 diff 0 差异、fraction 复算精确，建议删 `base_index` 死参数（已采纳删除）；视角B（premise 入口安全）、视角C（测 Key + key 泄漏）由主对话只读核验，均无阻塞（path 防御+回滚干净；mock 零联网 + error 不泄漏 key）。

**验证进度**：
- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **674 OK**（基线 661 + 新增 13；删 base_index 后复跑仍 674 OK）。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → FATAL/WARN none。
- 未做浏览器/真模型（048a 纯后端；真模型铁律⑥需授权）。

**当前接力点**：
1. **048b**（前端工作台+大纲回写）务必兑现红队剩余两条修正：`templates._WORKSPACE_SECTIONS` 必须加 workbench 入口（否则侧栏无链接+高亮失效）；workbench 的 plan-chapters/write-book 调用必须显式传 `require_start_point:false`（不能复用 continue 页 bindWriteBook 的 `true`）。
2. **048c**（细纲）按「只读+重生成」做：重跑 plan-chapters 天然走 `_attach_plan_fingerprints` 重算指纹，绕开 write-book 的 `plan_fingerprint` 门禁；核心验证重生成后 write-book 不 blocked。
3. **premise 可行性**：几十字 seed 的 KB 偏空已用单章包装跑通 mock，但 049「premise 扩写」需正视「短种子→高质量多章」的真实落差。
4. **文档滞后**：README 索引与本 Handoff 此前均漏记 046/047 全系列（046/046B/047/047a-d/047B2），本轮仅补 048a，046/047 回填待办。
5. 验收命令需用 `.venv/bin/python`（系统 python3 缺 pydantic/litellm）。

## Phase 4 Status（iter 048b，2026-06-09）

### Iteration 048b — 小白四步工作台·前端四阶段页 + 大纲回写（mock-only）

**目标**：把 048a 的后端 step 接成用户可见的四阶段工作台页 `/w/{name}/workbench`（① 设定 → ② 大纲 → ③ 细纲 → ④ 正文），pollJob 驱动 + 产物 gate；交付最简单的大纲纯文本回写。兑现红队剩余两条修正。执行档案 `iteration_048b_PLAN.md`。

**主要落地**：
- `templates.render_workspace_workbench`（4 阶段卡片，复用 continue 页 flow-step/card/status-box）+ `_WORKSPACE_SECTIONS` 加 workbench 入口（**红队修正①**）+ `render_wizard` 独立 premise-form。
- `routes.api_workbench_status`：GET `/workbench` 用 **mtime 链**探测 `{stage,has_kb,has_outline,has_plan,draft_count}`——下游产物须不旧于上游，改 premise 重跑 stage① 刷新 KB mtime 后旧 outline/plan 自动失效（红队「旧产物误判」防护；亲验 `compressor.py:87` 确认 KB 无条件重写故防护可靠）。
- `routes.api_workspace_outline_save`：PUT `/outline` 纯文本原子写，`workspace_busy`→409 / 空→400。
- `static.initWorkbench`：`bindWorkbenchStage` 把 4 form 接 `/run`+pollJob，`refreshWorkbench` 做 gate + 回填大纲；plan-chapters/write-book 显式传 `require_start_point:false`（**红队修正②**）；PAGE_KIND 分发 + premiseForm 提交。
- `routes._validate_plan_chapters_params`：`require_start_point` 由硬编码 True 改为尊重 params（默认 True 保 continue 页）——否则 workbench 传的 false 被覆盖、greenfield plan-chapters 死锁（**红队 #2a 的具体化**）；配套更新守护测试。

**对抗审核（铁律⑨）**：Bash classifier 暂不可用 + 对抗 subagent 两次 ECONNRESET，本轮审核由**主对话只读自审**完成（A stage 探测 mtime 链 / B plan-chapters 行为变更安全 / C PUT 竞态 / D 前端 gate 绕过），均无阻塞；其中 A 亲验 compress 无条件重写 KB 钉牢防护。诚实记录：铁律⑨「≥1 subagent」本轮未由 subagent 满足（连接故障），待 API 稳定可补一轮。

**验证进度**：
- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **681 OK**（基线 674 + 新增 7；1 个 plan-chapters 守护测试按行为变更有意更新）。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → PREFLIGHT: ok，FATAL/WARN none。
- 未做浏览器实机 / 真模型（铁律⑥）。

**当前接力点**：
1. **048c**（细纲）：workbench 阶段③改「只读 + 重新生成细纲」（重跑 plan-chapters 天然重算指纹），核心验证重生成后 write-book 不撞 `plan_fingerprint` 门禁。
2. **write-book 在 mock 下 `retry_exhausted` 是固有行为**（mock reviewer 默认 Reject，`reviewer.py:68`）：workbench stage④ 用严格 write-book 是有意设计，draft 写出但未 approve、真实模型才 approve；048b 测试据此断言 draft 落盘 + stage=done，不强求 approved。
3. 046/047 README/Handoff 回填仍待办（沿 048a 接力点 4）。

## Phase 4 Status（iter 048c，2026-06-09）

### Iteration 048c — 小白四步工作台·细纲只读 + 重新生成 + 写书指纹链兼容回归（mock-only）

**目标**：iter048 串行子迭代终章。workbench stage③ 从「跳走查看细纲」升级为「就地只读展示 + 重生成按钮」；核心使命是**钉牢红队最深暗礁**——细纲改动走"重跑 plan-chapters"路径而非手改回写，让 `write-book` 的 `plan_fingerprint` / `chapter_plan_item_fingerprint` 严格门禁（`book_runner._plan_metadata_failures` `L561-606`）始终自洽。执行档案 `iteration_048c_PLAN.md`。

**主要落地**：
- `templates.render_workspace_workbench` stage③ 加 `#plan-chapters-preview` 占位容器（HTML +1 div）。
- `static.refreshWorkbench` 重构：单次 `/plan` 拉取里同时回填大纲 + 渲染细纲 `kv-list`（第 NN 章 / title / · 约 N 字）；新增 `renderPlanPreview(plan)`；按 `has_plan` 切换 `#plan-chapters-submit` 文案为「生成细纲」/「重新生成细纲」。
- **核心反陷阱测试** `test_workbench_replan.py`（3 测）：人为把 `plan_fingerprint` 置为 `"deadbeef"*8`、首章 `chapter_plan_item_fingerprint` 置为 `"cafebabe"*8`（模拟"假如有人手改了细纲"），再跑 plan-chapters → 所有指纹**自动恢复**到 `plan_fingerprint(data)` / `chapter_plan_item_fingerprint(item)` 的当前重算值；write-book 之后不撞 fingerprint mismatch（draft 落盘）；workbench status 仍正确。

**对抗审核（铁律⑨）**：三个测试本身就是对红队最深暗礁的反陷阱守门 + 实机端到端验证；UI 改动对 048b 现有契约零破坏（684 全绿即证据）。未额外 spawn subagent。

**验证进度**：
- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **684 OK**（基线 681 + 新增 3，零回归）。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → PREFLIGHT: ok。
- **浏览器实机**（CLAUDE.md 铁律）：dev server 上 livebook2 跑完 premise→prepare→debate→plan-chapters，workbench stage③ 卡片内细纲列表渲染（5 章，每行"第 NN 章 / mock 第 N 章 · 约 4000 字"），**按钮文案 = "重新生成细纲"**（has_plan 触发文案切换），console 零错误。

**iter048 完结总结**：
- 048a 后端骨架（674 OK）→ 048b 前端工作台+大纲回写（681 OK + 实机）→ 048c 细纲只读+重生成+指纹自洽（684 OK + 实机）。
- **红队对原计划的 7 条修正全部兑现**：①`_WORKSPACE_SECTIONS` 入口 ②`require_start_point:false` ③mtime 链防旧产物误判 ④prepare-greenfield 进度契约修正 ⑤premise 包装单章修复 splitter 假设 ⑥`_validate_plan_chapters_params` 行为变更 ⑦细纲"重生成"路径绕开指纹链陷阱。

**当前接力点**：
1. **049**：细纲结构化字段编辑（每章 7+ 字段 + 数组增删）+ 正文逐章深度编辑回写 + 重 review；premise 扩写质量增强（短种子→高质量多章）；设定（KB/entity_graph）编辑回写；真模型授权 + 测 Key 成本护栏深化。
2. **048 真模型端到端**：mock 已全链路跑通，真模型链路（铁律⑥需用户授权）尚未走一遍；建议 049 前用一次最低成本真模型 smoke 钉牢 workbench 真模型场景下「stage④可 Approve」假设。
3. 046/047 README/Handoff 回填仍待办（沿 048a/048b 接力点）。

## Phase 4 Status（iter 048d，2026-06-09）

### Iteration 048d — iter048 对抗审查 H/M 级修复（mock-only）

**目标**：iter048 三轮落地后按铁律⑨ spawn 4 路并行 subagent 对抗审查（视角 A 状态机/竞态、B 指纹链、C API 安全、D 前端 UX），共发现 1 H + 5 M + 多个 L 级风险。048d 集中修 H + 5 M；L 级 UX/a11y 推 049 摊销。**用户拍板**：C2(a) 正则加固（保留排错信息），A4 扫所有 prep step（一劳永逸）。执行档案 `iteration_048d_PLAN.md`。

**主要落地**：
- **A5（H 阻塞，跨轮遗留）**：`state.write_text_atomic` 的 tmp 后缀 `.tmp` → `.tmp.{pid}.{tid}`，解决并发写撞文件名的潜在竞态（048 让触发面变宽：PUT outline + debater + compress 都用 write_text_atomic）。同步加固 `web/settings.py:159` 自写 .tmp 同款，`test_web_settings` 两处断言改 glob。
- **A2（M，048b 引入）**：`api_workspace_outline_save` 把单点 `workspace_busy` check 升级为 `workspace_reserved` 上下文，捕 RuntimeError 映射 409，消除 busy check 到 write_text_atomic 之间的 TOCTOU 窗口。范式照抄 `api_workspace_trash`。
- **A4（M）**：新增 `_blocked()` helper；6 个 prep step（`split/extract/compress/bootstrap/apply-bootstrap/debate`）加前置产物 readiness check，缺产物时返 friendly `blocked{reason:xxx_missing}` 而非 `failed` + trace_id。红队点名的 `_step_debate` 缺 KB 路径被钉牢。
- **C2(a)（M）**：`LLMClient.ping()` redact 叠加 `Bearer\s+\S+` 和 `sk-[A-Za-z0-9_\-]{16,}` 两层正则，挡住 Authorization 头/裸露 sk- key 的编码形式泄漏路径；保留 `type(exc).__name__` 让用户能区分 401/429。
- **B-M-1（M，测试 gap）**：`test_workbench_replan` 补 3 测——`plan_fingerprint` 缺失 / 首章 item fp 缺失 / plan-vs-draft mtime 链失效，覆盖原 048c 只测 `*_mismatch` 的盲区。

**对抗审核（铁律⑨）**：本轮本身是上轮审查的修复回应，**不再 spawn 二次审查**避免无限镜厅。10 个新测试 + 实机验证就是答辩证据。

**验证进度**：
- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **694 OK**（基线 684 + 新增 10，零回归）。
- `OPENAI_MODEL=mock .venv/bin/python main.py preflight` → PREFLIGHT: ok。
- **浏览器实机**（CLAUDE.md 铁律）：
  - A4：premise→跳过 prepare 直点 debate → job 终态 `blocked` + summary `["blocked","status"]`（非 failed/trace_id）；
  - A2：debate job 启动后并发 PUT `/outline` → 409 `workspace busy` + `running_job_id` 字段；
  - workspace `a2test`/`a4test` 已清理。

**iter048 完整收官**：
- 048a 后端骨架（674 OK）→ 048b 前端+大纲（681 OK）→ 048c 细纲+重生成（684 OK）→ **048d 对抗审查 H/M 修复（694 OK）**。
- 红队对原计划 7 条修正 + 4 路对抗审查 1 H + 5 M 共 12 项全部兑现。
- 全部 mock 端到端 + 浏览器实机均验证；真模型端到端待 049 用户授权后跑。

**当前接力点（049）**：
1. **L 级 UX/a11y 集中修**：D1 友好 409 文案 / D4 stale plan loading 占位 / D7 `<label for>` 关联 / C3(c) 控制字符过滤 / B3-hint 提示 → 与正文/设定编辑前端一起做摊销。
2. **细纲结构化字段编辑**：兑现"全程可编辑"承诺最后一块（每章 7+ 字段 + 数组增删 + 范围校验）。
3. **正文逐章深度编辑回写 + 重 review**；设定（KB/entity_graph）编辑回写。
4. **premise 扩写质量增强**（短种子→高质量多章）。
5. **真模型端到端 smoke**（铁律⑥需用户授权）；测 Key 成本护栏深化。
6. **B-M-2 防御性重构**：`chapter_plan_item_fingerprint` 字段黑名单改白名单。
7. 046/047 README/Handoff 回填仍待办（沿 048a-c 接力点）。

---

## Phase 4 Status（iter 049，2026-06-10）

### Iteration 049 — Aeloon 插件 + MCP 双轨集成

**目标**：把续写系统以**插件形式**接入第三方 Agent 平台 Aeloon-Pro。用户拍板：插件 + MCP 双轨、交互做到「命令 + LLM 工具」、可实机验收；048d 预定的产品打磨包顺延 iter050。执行档案 `iteration_049_PLAN.md`。

**形态结论**（源码调研）：Aeloon WebUI 是 React 聊天窗口，插件输出渲染为 Markdown 消息流，链接可点（新标签页）；插件 SDK **无**自定义面板/iframe 扩展点 → 不做窗口内嵌子页，富交互走深链跳 `/w/{name}/workbench`。

**主要落地**（在已存在 95% 的 untracked `integrations/` 脚手架——`novel_client`+`novel_ops`+`mcp_server`，44 测——之上补缺口）：
- **`integrations/aeloon_plugin/`（新）**：`/novel` 命令族（new/outline/write/auto/status/open/list/prepare）+ 8 个 LLM 工具，复用 `novel_ops` 与 `mcp_server/tools.py` 的 `TOOL_SPECS`。`plugin.py` 薄胶水（唯一 import SDK），`commands.py`/`tool_adapter.py` host 无关可测。`install_into_aeloon.py` 用 `.pth`（repo→Aeloon venv path）+ 符号链接（→`~/.aeloon/plugins/`）一键安装、`--uninstall` 可逆。
- **`src/web/auth.py`（新）**：opt-in bearer token 闸（env `NOVEL_API_TOKEN`，默认关→零影响既有测）；只 gate `/api/*`，`/w/` 深链与 landing 豁免；接到 `routes.dispatch()` 单咽喉。
- **关键实测校准**：`PluginAPI` 不在 `_sdk.__init__` 导出，改 `TYPE_CHECKING` 下从 `_sdk.api` 引入；Aeloon loader 全程不碰 `sys.path`，故须 `.pth` 部署。

**验证**：
- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **758 OK**（694 + 64：44 既有集成测纳入 canonical + 20 新 plugin/auth），零回归；preflight ok。
- **Aeloon 轨实机**：Aeloon 自己的 `PluginDiscovery`+`PluginLoader` 从 `~/.aeloon/plugins` 发现并加载 `novel.continuer`（`load_plugin_class` **仅靠 .pth** import）；register = `novel` 命令 + 8 工具；真实 `CommandContext` 跑 handler 产出正确 Markdown。
- **MCP 轨实机**：真实 `mcp` 客户端启动我方 stdio server → `initialize`→`tools/list`=8→`call_tool` 命中实时 mock 服务出深链。
- 插件**已装**用户 Aeloon，可 `/novel help`；WebUI 聊天截图与真模型 smoke 留用户/后续。

**接力点（050）**：048d 顺延的产品打磨包（L级 UX/a11y、细纲结构化编辑、正文/设定编辑、premise 扩写质量、真模型 smoke、B-M-2）—— 执行档案 `iteration_050_PLAN.md`（计划稿）。

## Phase 4 Status（iter 050，2026-06-11）

### Iteration 050 — 全程可编辑闭环 + 预算护栏

**目标**：兑现「全程可编辑」最后一块拼图。用户拍板：编辑闭环优先（细纲结构化编辑 + 正文/设定编辑回写为核心，UX/a11y、B-M-2、文档回填摊销），授权小额真模型 smoke ≤15 元；premise 扩写质量顺延。执行档案 `iteration_050_PLAN.md`（已升级为执行版，含 L 级代号权威定义表）。

**核心设计**（与 048c 暗礁的关系）：048c 红队证伪的是「PUT 原始 JSON + 手搓/保留指纹」；050 的解法不是绕开编辑，而是把「重跑 plan-chapters」泛化为「复用 `_attach_plan_fingerprints` 唯一真源」——结构化字段 PUT → Pydantic 校验 → 同一入口重算指纹 → 原子写盘，门禁自洽 by construction。三个关键决策：① B-M-2 指纹黑名单改白名单 `_ITEM_FINGERPRINT_FIELDS`（canonical item 哈希逐字节兼容，未知字段免疫，测试钉死）；② 编辑路径 `refresh_start_point=False` 保留存储的起点指纹（重算会伪造新鲜度、骗过 `_plan_metadata_failures` 的起点变更检测）；③ 编辑任一章 → 全部已写章 strict 过期是**有意语义**（与重新生成一致），端点返回 `written_chapters_invalidated` + 前端确认弹窗 + B3-hint 恢复指引；非编辑章 item 字节不动 → item 级指纹幸存，恢复 = 重写/重评审受影响章。

**主要落地**：
- **050a（`f896f2f`）**：`plot_planner.apply_chapter_plan_item_edit`（纯 IO）+ `PUT /api/workspace/<n>/chapter-plan/<c>`（`workspace_reserved` + 409 映射）+ stage③ 内联编辑表单（7 字段 + key_events/relationships 动态增删 + 客户端预校验）；D4 细纲加载中/stale 灰显；B3-hint `plan_fingerprint_stale` CTA（jobActionKind 正则归一指纹失败全家族）。
- **050b（`d22a3af`）**：`PUT /draft/<c>` —— md+meta **同一 reserved 持有期双写**（`review_target` 只信 meta sha 从不重哈希，不同步即永久 `draft_hash_mismatch`；编辑后 `external_review_stale` 正确触发=「需重评审」自解释）+ jobs 新 step `review-chapter`（review_target → `_sync_meta_with_external_review` → strict chapter_status）+ 章节详情「编辑」tab（保存 / 保存并重新评审）；`GET/PUT /kb`（保留 048b mtime 链 stage 回退语义）+ `GET /entity-graph` + `PUT /entity/<id>`（白名单 name/aliases/tags/key_facts/description）+ `PUT /relationship/<idx>`（仅 active timeline `state`；无稳定 id，契约=当前数组下标+reserved 锁）+ stage① 按需设定面板；D1 `_httpError`（status+payload+友好 409）；D7 label-for 补全；C3c `_contains_control_chars` 挂全部文本入口（含 outline/premise 回填）。
- **050c（`07e8dbc`）**：README 回填（4.5→✅ 047d viewpoint 过滤、4.6→✅ 047b start_safe_knowledge、命令表补 6 行、状态表 049/050 行、U.14、SOP 头 iter050）；预算护栏——web write-book `budget_cny` 默认从 0.0（无上限）改 `NOVEL_DEFAULT_BUDGET_CNY`（缺省 10 元；显式 0 仍=无上限）+ stage④ 预算输入 + preflight `_check_budget_guard` WARN（mock 静默；真模型态实机目击）。
- **050d（`1e287ed`）**：铁律⑨ 收官对抗审查（零 H / 零 XSS）M×4+L×3 全修——M-1 `utils.write_json` 全局原子化（chapter_plan/meta/entity_graph 成用户可写路径后防截断 JSON）；M-2 relationship PUT 要求回显 src/dst → graph 重建后旧下标 409 stale_index；M-3 工作台预算 input 默认值改为渲染时注入 env（硬编码 10 使 env 形同虚设）；M-4 entity/plan item 字段长度闸；L-1 编辑路径空 start_point_fingerprint 不 live 兜底；L-2 删 entity_id 二次 unquote；L-3 预算 env nan/inf/负数 isfinite 拦截。
- **暗礁实录**：static.py 的 JS 字符串字面量换行必须 `"\\n"`（非 raw Python 字符串）；050b 初版 `renderEntityPanel` 误写 `"\n"` 撕裂整个 JS bundle（静默失效），浏览器实机走查抓到——铁律「UI 改动必实机」再次自证。verify.sh 须在 venv PATH 下跑。

**验证**：mock 全绿 **808 OK**（758→805→808，050d +3）+ verify.sh 全链；浏览器实机（ui050a/ui050d）：细纲编辑→指纹自洽→write-book 仅 `retry_exhausted` 零指纹失败；正文编辑→保存并重新评审→md/meta/review 三方 sha 一致；KB/实体编辑落盘；D4 灰显、relationship echo 防 TOCTOU、预算 input env 注入实测。**真模型 smoke（smoke050）实测**：编辑细纲后 write-book 零指纹失败 + Approve（4012 字，编辑的章末事件进正文），编辑正文→review-chapter 后 stale 族消失，总账 ¥2.75/15。详见 `iteration_050_PLAN.md` Acceptance + 050d 段。

**合并状态（2026-06-11）**：用户拍板 **Aeloon 一起进 main**，作废 `76695b3` 的「Aeloon 留 feature 分支」拆分。完整 `iter050-edit-loop`（含 iter049 Aeloon 全套 + iter050）已 merge 进 main（`32d4da9`，token 闸子集三路合并零冲突），并 push origin（`1288224`）。`.claude/` 整个目录已 gitignore。

**接力点（051 候选）**：premise 扩写质量增强（短种子→高质量多章，050 真模型 smoke 的种子质量数据可作输入）；KB 保存 stage 回退的交互软化（如实机反馈刺眼）；review-chapter 独立预算强拦；MCP server progress 通道 / `/novel write` 暴露 tier 参数（049 遗留）；iter040 backlog（章节 diff、全文搜索等）；feature 分支 `iter049-aeloon-integration` / `iter050-edit-loop` 已并入 main，可删。

## Phase 4 Status（iter 051，2026-06-11，mock 段收官）

### Iteration 051 — premise 扩写质量增强 + 评审预算强拦 + 技债清偿

**目标**：兑现 050 顺延的 #4 premise 扩写质量增强（主轨）+ review-chapter 独立预算强拦与 iter027 P7 carry-over F3–F8 清偿（副轨）。用户拍板：三轨照单采用、真模型 smoke ≤30 元（高于草案 15 元，留对照各 2 章 + 重试余量）、30–100 章 capstone 顺延 iter052 单独立项。执行档案 `iteration_051_PLAN.md`（已回填 Acceptance）。

**核心设计**：premise 与 prepare-greenfield 之间插入**显式可编辑的结构化扩写产物**（`data/premise_expansion.json`，6 字段 schema `PremiseExpansion`），不覆写 seed.txt（seed=用户原话，扩写=模型推断，单向消费无第二真源）；可编辑性完整复用 050 模式（Pydantic 校验 → `write_json` 原子写 → mtime 链过期提示——扩写稿挂 KB 上游，编辑即 stale 全链）；三个 prompt 消费点（compress/debate/bootstrap `_extractions_context`）统一走 `expansion_prompt_block()` 单点降级，**缺失时逐字节等价**（mock KB == `_mock_knowledge_markdown` verbatim 测试钉死）。

**主要落地**：
- **051a**：`src/premise_expansion.py`（expand_premise 幂等/force + load 三态降级 + save 创建/更新 + 渲染）；`PremiseExpansion` mock stub 确定性分支；`expand-premise` web job（seed 缺失 blocked、force 语义）；premise-start `expand` 参数——**设计偏离：API 缺省 false、wizard checkbox 默认勾选**（保 novel_client/MCP「create-only」契约 + 防 premise→prepare 链式 409 竞态；「默认开」落在 UI 层）；`GET/PUT /premise-expansion`（C3c + 字段长度闸走 schema max_length + 100k 外闸）；workbench `has_expansion`/`expansion_stale` + stage① 结构化编辑面板（保存/重新扩写）。
- **051b**：`config.parse_budget_cny`/`budget_cny_from_env` 成为 050 L-3 校验唯一真源（write/review/preflight 三处共用）；`NOVEL_REVIEW_BUDGET_CNY`（缺省 5 元，params.budget_cny 优先，0=无上限）→ `_step_review_chapter` 事后结算（llm_calls 行偏移 → `estimate_cost_since`），超限 → `budget_exceeded` 终态带 cost_cny/budget_cny（v1 语义：单章无章间断点，与 write-book 章末校验同款）。F3/F8：`_safe_int/_safe_float/_env_float` + config/llm_client/mcp_server 裸解析全迁（defaults 逐字保留）；F5：entity_advance 两处静默跳过加 `proposal_skipped` 审计日志；F6：`start_point.enforce_consistency` 集中 presence + plan-agreement 四码（与原 `_plan_metadata_failures` 内联块逐字节同码），plot_planner/book_runner 入口迁移、spoiler 消费点不动；F4 验证 iter027 已闭环（补 2 测试）；F7 显式顺延（依赖 F6 真模型落稳）。
- **051c 审查修复**：M-1 `_extractions_context` 截断改扩写稿长度预算扣减（防切坏 JSON）；L-1 渲染边界折叠字段内换行（兼消「伪造 prompt 段头」注入面——C3c 放行 \n 是多行编辑面的有意设计，立场与 KB 编辑一致）；L-2 残缺 artifact premise 键兜底。

**验证**：mock 全绿 **877 OK**（808→837→875→877，+69）+ verify.sh 全链 exit 0；浏览器实机（ui051）：开书自动扩写 → 面板回填 → 生成设定 → KB 含扩写 section → 手改字段保存 → 过期提示 + stage 回退 + 大纲禁用 → 重跑清除 + 手改内容进 KB → console 零报错；铁律⑨ 双视角（功能正确性 × API 安全/预算）H×0，M×1+L×2 当轮直修。**真模型对照 smoke（2026-06-12，gpt-5.5-high tier=mid，同句种子裸 seed vs 扩写路径各 1 章）**：扩写路径 panel_score 8.16→**8.50**、KB 2914→**7610** 字（+161%）、实体 12→14、章纲 plan_json 3637→**5467** 字符（+50%）、opening/hook 均长 +15%/+25%、正文 3757→**4745** 字（+26%），成本仅 +¥0.47（+17%），两路径均一次过 Approve / needs_human=False；裸路径复现 050 ¥2.75/76 calls 基线证明扩写链路对回退零回归；两路径合计 ¥5.96/30 元预算（耗 20%）。扩写假设由真模型对照证实。

**接力点（051 收尾 + 052 候选）**：① ✅ 真模型对照 smoke 已跑（2026-06-12，扩写 panel +0.34 / 成本 +17%，证据回填 051 计划档 Acceptance + 本档）；② F7 在 F6 真模型验证后拆补丁；③ 30–100 章 longzu capstone（iter052 单独立项 + 单独预算）；④ premise 扩写多轮自评精修（视 smoke 对照结果）；⑤ Aeloon 打磨 / KB stage 回退软化继续等实机反馈；⑥ **【结构性，052 应立项】真模型长流程驱动器正式化**——smoke051 实测暴露：用 agent 会话后台任务驱动 2 小时级真模型流程，会话 context 压缩/重启会**静默回收进程组**（无信号无 traceback，smoke051 死过一次；另一次中断是低估 gpt-5.5-high 单 call 1.5–3 分钟 × 36 debate calls 的量级把超时设短了）。macOS 无 `setsid` 命令，临时解法 = Python double-fork + `os.setsid()` 脱离到 launchd（ppid=1）。应把对照/capstone 驱动器正式化为 `scripts/` 下的**断点续跑 CLI**（幂等 gate 逻辑已在 smoke051 驱动脚本验证：premise-start 容忍 409 + workbench gate 跳过已完成阶段 + debate done_keys 续跑 + 项目自身 web_jobs/debate_log 落盘韧性，三次中断零数据损失），由用户终端或 launchd 跑、agent 只轮询产物文件——30–100 章 capstone 没有这个基建跑不完。

## Phase 5 Status（iter 052，2026-06-12，收官）

### Iteration 052 — 长程驱动器正式化 + F6/F7 清债（真模型双载体实跑）

**目标**：兑现 051 接力点⑥——把 smoke051 的临时 double-fork 驱动方案正式化为产品能力（2 小时级真模型流程脱离 agent 会话、断点续跑、可审计），同时清掉 F6 真模型验证与 F7 补丁拆除两笔旧账。用户拍板：三轨 = 驱动器主轨 + F6/F7 清债 + 实跑验证载体；D 轨三项全裁仅搭车收 timeline 证据；预算先 15 章 ¥20（后改 premise 书 ¥12）。执行档案 `iteration_052_PLAN.md`（已回填 Acceptance）。

**核心设计**：`src/book_driver.py` 子进程编排公开 CLI（崩溃隔离/CLI 即契约/中途换码/step 级超时杀进程组），**章节进度永远从盘面推导**（driver_state.json 只存参数与审计，防第二真源——050 指纹哲学同款）；`--detach` double-fork+setsid（ppid=1）+ caffeinate；预算双层（llm_calls 行偏移总账 + 段内剩余额度）；blocked 停人审不自动 --force；与 web_jobs 绕开（server 内线程生命周期错配），只共享底层幂等 gate（write-book skipped_approved / debate done_keys）。

**主要落地**：
- **052a（`5c4faff`）**：book_driver + `main.py drive-book` 五动作（start/status/resume/stop/report）+ `drive_book.sh`（CONFIRM_REAL_MODEL_SMOKE 闸映射 --confirm-real-run）；`MOCK_WRITER_CHARS` mock-only 钩子（mock 写稿 ~60 字必撞 short_chapter_length、write-book 历史必 Reject 的根源由此可绕，E2E 走通 approve 路径）；tests/test_book_driver.py +28（状态机 stub / 断点续跑 E2E：pause→WRITER_FORCE_FAIL 注入 resume 零重写→收口）。
- **052b（`89eaa84`）**：F7 开场覆写补丁拆除（writer.py 覆写块；iter013 ending_block 保留），test_writer 断言显式翻转 + 钉死「本章计划块不随 previous_chapter_ending 变化」；独立 commit 回滚单元。
- **052c（`d23e5db`）**：铁律⑨ 直修（A-M1 成本账失效留痕 / A-M2 detach 重定向失败显式退出 / B-M1 确认闸 bool / B-L1 钩子 clamp；A 视角 H-1「segments 跨 attempt 混合」复核为误报——`_run_steps` 每 attempt 重建已有断言钉死）+ drive_book.sh venv 自带解析（050/051 暗礁三度复现直修）。

**验证**：mock 全绿 **907 OK**（877→907）+ verify.sh 全链 exit 0。**真模型双载体（gpt-5.5-high tier=mid，全天 ≈¥18.1 收在 ¥20 信封）**：①longzu 15 章——驱动器无人值守 2h 零进程事故，ch1 九稿全拒（panel 5.68→6.16 横盘、fidelity 轴 block 级拒因）→ retry_exhausted → **blocked 停人审路径实弹验证**；F6 正路径全程零 fingerprint 失败 + 负路径两码 mismatch 实录。②shudian052 premise 书（旧书店种子+扩写路径开书）——**7/7 章 Approve（panel 8.04–8.72）**；段间 pause 实弹触发；**中断恢复演练**：stop（零残留）→工作树切 F7 删除版→resume（attempt 3, ppid=1）→**账本 206→206 行零重复花费**；未授权 resume 被确认闸 exit 64 实弹拒绝；F7 段间对照 8.31→**8.48** 零开场退化坐实拆除。**longzu 失败根因考古**：直接根因=5/30 陈旧「四部曲结局后」debate outline 在驱动器 ensure-plan --force 重 plan 时污染时间线（对照 6/5 起点修复后旧 plan「听力考试」贴起点可过）；深层根因=写手预训练记忆剧透泄露（start_safe_knowledge 管 KB 注入、管不住权重记忆）；评审团+手工反剧透规则逐稿精准命中，质量闸全程正确。timeline 证据包：20+ 条 0.91–0.98 高置信 advance 提案全因 `relationship_not_found` 跳过（76 条 F5 审计日志）——greenfield 实体图边稀疏，时间线全程未推进。

**接力点（053 候选，按优先级）**：① **中间产物起点一致性校验**（outline/decisions 不走起点过滤、F6 只管 plan↔start 指纹——plan 前需对 outline 做时效 gate 或缺 plan 强制重 debate）；② **canon 锚定增强**（写手 prompt 硬约束「KB 外原著知识当不存在」+ 评审 block 拒因结构化回灌；笼统反馈循环对剧透无效已实证）；③ timeline 高置信提案动态建边；④ 30–100 章 capstone（驱动器已就绪，待①②后用干净 plan 重战 longzu）；⑤ 票数闸阈值观察（premise 书重试全为 panel≥7.94 的边界拒，单次 ≈¥0.6）。**暗礁**：实跑期间外部人工 stop/resume 与 agent 节拍存在竞态（22:09 计划外 resume 跳过了 F7 切换步，靠中断演练补位）——驱动器无操作者锁，SOP 纪律先通气；扩写稿 schema 无非空校验（本次 genre_tone 等三字段空，personas 顶住了风格定调）。

## Phase 5 Status（iter 053，2026-06-13，实施段收官 / 真模型段待跑）

### Iteration 053 — 中间产物起点校验 + 写手 canon 锚定增强（053c longzu 复仇局待跑）

**目标**：兑现 052 接力点①②——治 longzu 失败主因（陈旧 debate outline 不受任何起点一致性校验、污染重 plan）与次因（写手预训练剧透泄露 + 笼统反馈回灌无效）。计划稿经四维 subagent 审核修订（代码锚点核实 × 052 文档口径核对 × 盘面实勘 × 对抗设计审查，采纳 A1-A9/B1-B4/C1-C4/D1-D2）；用户拍板④追加提速降本授权（票数闸 3/5 + 按任务换更快模型档）。执行档案 `iteration_053_PLAN.md`（mock 段已回填）。

**核心设计**：F6 指纹哲学推广到中间产物层——decisions.json 写盘前以 dict 键钉入起点指纹 + `outline_sha256`（**schema 不动**：DebateDecisions 是 complete_json 的 LLM 契约，加字段招幻觉假指纹）；写序倒置（outline 先、decisions 后作 commit 标记，防 SIGTERM 半写错配）；plan 落盘记 outline_sha256 成 **plan↔outline 血统链**（盘面实证：052 毒 chapter_plan.json 起点未变 F6 全绿，ensure-plan guard 会以 plan_sufficient 直接复用——审核期最大发现）；driver 遇陈旧 outline **缺省 blocked 停人审**（对齐 052"不自动 force"哲学）；反剧透用**时间锚定**（只禁起点之后、起点之前照常用——"未注入即不存在"会误杀截断窗口外的合法 canon，fidelity 反降）。

**主要落地**（四个独立回滚单元，审查 D2 纪律）：
- **053a（`78cdc75`）**：debater 元数据钉入 / `debate --force` 归档 snapshots / debate_log 指纹头 + resume 防洗白（旧起点时代 log 拒绝续跑）；`start_point.outline_consistency_failures` 四态（匹配/硬拦/无指纹 warn/decisions 缺失 warn 同道）+ `plan_outline_lineage_failures`；plot_planner 读 outline 前过闸（报错区分"起点真变"vs"行号漂移"）+ `--allow-stale-outline` 逃生门审计痕；driver debate 三态 + `--force-debate`（联动归档失效下游 chapter_plan.json，一次性旗标 resume 默认清零）+ 与 `--skip-debate` 互斥；write-readiness warnings 通道 + web plan 页陈旧大纲警示。
- **拍板④（`4dd1ed6`）**：`WRITE_REVIEW_MIN_APPROVE` 只降票数保 7.5 分线（052 实测票数闸边界拒 ≈¥0.6/次）；models.yaml write/review/debate `model_env` 钩子（OPENAI_MODEL=mock 测试隔离不破）。
- **053b（`27cdea9`）**：写手时间锚定块（条件注入 + `WRITER_CANON_ANCHOR` 开关，无起点/关闭逐字节不变——铁律④）；`_review_feedback` 分层模板（block 禁令置顶，修复 block-but-Approve 漏灌）；`_blocking_reasons` 同口径；**跨 retry 周期反馈播种**（book_runner 归档前收割上一周期拒因 → `write_chapters(seed_feedback=...)`——052 九稿横盘的"周期内有反馈、周期间失忆"断链闭合）。
- **premise 搭车（`0e2049b`）**：扩写 6 字段非空校验（空字段重试一次 + record 层 `_incomplete_fields` 标记不进 prompt 面 + stage① 建议补全提示 + 手工补全摘牌）。

**验证**：mock 全绿 **954 OK**（907→954，+47）+ verify.sh 全链 exit 0。**真模型段（053c longzu 复仇局，≤¥12）待跑**——跑前按铁律⑥与用户确认时点；配方与验收决策表见 iteration_053_PLAN.md：第 0 步清场断言（debate 三件套 + 毒 chapter_plan.json + ch1 残留 + rolling summary）→ 分段单变量（ch1 仅 053a 净图纸、人审后 ch2–5 开 053b 锚定）→ `WRITE_REVIEW_MIN_APPROVE=3`（拍板④）；票数闸边界拒形态不计入 053b 副作用判定。

## Phase 5 Status（iter 053，2026-06-13，全验收收官）

### Iteration 053 — 中间产物起点校验 + 写手 canon 锚定（053c longzu 复仇局 5/5 Approve 通过）

**最终结论**：longzu 干净图纸假说**铁证成立**——ch1–5 全 5/5 满票 Approve，panel 均值 7.59，机库/倒计时/心神原型机全章 0 次（052 时间线穿越毒彻底根除）。3/5 票闸全程未派上用场（approve_count 均 5/5），质量为真。capstone 立项解锁。

**核心发现：052"根因考古"只触达最外层**。053c 真模型实跑（拍板⑤ ¥50+ 授权，agent 自主"跑→取证→停→机制化修复→复跑"循环）剥出四层毒源：
1. **根因①（052 已识别）陈旧 outline 不受校验** → 053a 指纹+血统链（`78cdc75`）
2. **根因② debate 缺显式起点块** → 毒 anchor 以 must-anchor 满权威注入，id 级 provenance 拦不住内容毒 → 053e（`fa40b2e`）`_start_point_prompt_block` 注入三个 prompt 面
3. **根因③ anchor 采样 off-by-one** → 起点章 exclusive，时间跳跃尾声型起点系统性锚早一章（5/30 毒 anchor 由此成因，非一次性事故）→ 053f（`d9a0564`）include_start 闭区间
4. **根因④ 提取底座断层 + 截断毒** → extracted_jsons 只覆盖前 3 章、起点在第 ~100 章，KB/实体图锚死"入学初期"，评审拿旧状态当硬尺连拒贴起点的正确稿 → 053g（`9163a59`）覆盖 warn 护栏 + 运营补提取 24 章；补全后 bootstrap 截断毒（尾部截断只留早期章）→ 053h（`fda280a`）recent_first 窗口

**052 失败根因链修订**：052 主因（陈旧 outline）成立但是最外层；"6/5 旧 plan 贴起点可过 7.5"实为"贴旧底座可过"的假基线。底座断层是最深层。052 文档不改（历史记录），以 iter053_PLAN 的"053c 实跑实录"四层剥洋葱表为准。

**主要落地**（八个独立回滚单元）：053a 中间产物指纹/血统/防洗白 + 拍板④票数闸/模型档 env（`4dd1ed6`）+ 053b 写手时间锚定/回灌分层/跨周期播种（`27cdea9`）+ premise 非空校验（`0e2049b`）+ 053d 铁律⑨双视角直修（`3506b36`，1H+5M+3L）+ 053e/f/g/h 实跑发现直修。

**053b 实战印证**：ch4/ch5 各重试 1 次过审——同样的 retry 机制，052 是九稿横盘全灭，053 是带跨周期播种的"被拒→吸取拒因→下稿过"。分段单变量对照成立：ch1 anchor=False（纯 053a 净图纸）vs ch2–5 anchor=True（叠加 053b）。

**验证**：mock 全绿 **967 OK**（907→967，+60）+ verify.sh exit 0。真模型 ¥23.61（拍板⑤授权内，含一次性历史债清偿：两轮辩论/三轮 plan/ch1 三攻 + 24 章提取/KB/实体图重建）；**干净底座单 pass 5 章 ≈¥9.6 回原 ¥12 设计量级**——四层护栏不增边际成本。

**接力点（iter054 候选）**：① capstone 30–100 章（基建+底座全就绪，用 longzu 干净 plan）；② 053d 记入观察项的 M2/M3/M5（polish 路径吃 block 行 / Approve+block 出货无痕 / 3票闸×Abstain）+ A-M5（append/replan 丢审计痕）；③ timeline 动态建边（052 顺延）；④ 提取覆盖从 warn 升级为可选 block（053g 现为 warn）。

## 能力边界审查（2026-06-13，iter053 收官后三视角 subagent 代码审查）

收官时"任意起点无泄露续写"的乐观表述经代码审查需**降级**。两大断言的真实状态：

### 断言一「无泄露后续情节」→ 实为"有限硬保证 + 软兜底 + 已知残留口"
泄露硬过滤覆盖（`is_after_start` 全调用方仅 manual_facts/entities/kb_view 三处）：
- ✅ **KB**（`kb_view.start_safe_knowledge` 047b）+ **manual_facts**：硬过滤，剔除起点后（前提 index 存在，否则 fail-open 回退全书 KB + warn）
- ❌ **entity_graph 实体 key_facts/description**（`entities.py:104-118`）：**零起点过滤**——最大泄露口。`render_active_state(respect_start_point=True/False)` 在 longzu 上字节相同（过滤层 no-op）
- ⚠️ **entity_graph 关系**（`entities.py:94-100`）：仅当 active timeline 带 `chapter_id` 才过滤，bootstrap 不保证写该字段 → 缺字段 fail-open 漏过
- ❌ **source_excerpts/scene_excerpts**（`source_excerpts.py:89-186`）：从全书摘样，零过滤
- 共同上游：`extract_all`（`extractor.py:309-323`）+ 所有 bootstrap 生成端**零起点裁剪**；硬过滤只在部分消费端补救
- **评审端无任何反剧透硬拒因**（gf_longzu_014/015 是普通 canon 事实，非反剧透规则）；053b canon 锚定是 system_prompt 软约束，且会被"硬材料里的剧透"带偏
- **longzu 未爆剧透是数据巧合**：start=ch024 是结局章、只提取到 ch024，"生命交易"等属起点章自身（`is_after_start` 返 False）非严格之后。换深起点 + 提取含起点后 → 必泄露

### 断言二「任意起点端到端自动」→ 实为"数据模型层支持，底座编排层需人肉"
- init-book 默认 `--extract-limit=10`（`main.py:156`，全书前 10 章切片，非每卷/非起点窗口）→ 起点在深处时**根因④系统性必现**
- `set_start_point` 零自动失效重建（`start_point.py:74-106` 只写盘）
- entity_graph **无起点 stale 检测**（anchor 有 sidecar `_anchor_matches_current_start` 027，graph 没有——不对称缺口）
- 提取覆盖 053g warn 只在 readiness 报（`book_runner.py:425`），debate/plan 的钱已花完才知道；非 blocker、不自动修
- drive-book 不编排 extract/compress/bootstrap，假定底座就绪
- longzu 实跑 4 步救火（补提取→recompress→bootstrap-graph --force×2→bootstrap-anchor --force）**没一步被编排**，换书换深起点必重演

### iter054 必做项分析（代码硬 blocker = 0，但有 1 决策 blocker + 2 能力缺口）
- **B1 决策 blocker（capstone 立项前必答）**：longzu 起点 ch024 是 manifest 第 83/110 章，**起点后仅 26 章真实素材**（龙族四 17 + 前传哀悼之翼 9，前传是独立时间线）→ 凑不出 30 章原著后续。capstone 目标语义须先拍板：续写原著真实后续（≤26 章、尾部前传断裂）vs **自由生成 30+ 章原著不存在的剧情（推荐，系统本来语义，053c 的 ch1-5 即此）**。不答清楚连 `--chapters`/workspace 都定不了
- **能力缺口 A（任意起点真自动化）**：起点感知提取窗口（`extract_all` 已有 `chapter_ids` 参数可复用）+ entity_graph 起点 stale 检测（复制 anchor 的 sidecar）+ "换起点重建全链"编排命令 + 提取覆盖闸提前到 set-start-point/plan 前
- **能力缺口 B（无泄露真保证）**：entity_graph 实体描述/关系 + source_excerpts 的起点硬过滤；理想在提取/bootstrap 生成端按起点裁剪（治本），而非消费端补救
- **A-M5（可搭车修，非 blocker）**：write-book/driver 缺 `--allow-stale-outline` 透传 → capstone replan append 在重切章/手改 outline 边缘场景无逃生门（happy path 不触发，可降级绕过）。~4 处改动
- **M3（capstone 全自动放大）**：Approve+block 稿无痕出货，无人审兜底时危害上升
- **可延**：M2（polish 吃 block 行，章长 >3500 不触发）、M5（票闸×Abstain）、timeline 动态建边（052 顺延）

**iter054 主线建议**：两条路线——(甲) 直接上 30 章 capstone 验证长程一致性（B1 拍板后即可跑，A-M5/M3 搭车修），把缺口 A/B 留作"已知残留、操作纪律规避"；(乙) 先补缺口 A/B 把"深起点无泄露续写"从 demo 做成产品能力，再以 capstone 验证。(甲) 快、验证长程；(乙) 慢、补真能力。**取决于产品定位是"演示长程能写"还是"任意书任意起点安全可用"。** capstone 代码前置已就绪（驱动器/护栏/longzu 底座），无技术 blocker。

### 核查修订（2026-06-13，二次 workflow 对抗式核查 `wauup3r0p`，iter054 v2 依据）
上面「断言一」的泄露口清单经逐文件复核（11 agents / 完整性穷尽）有数处修订，详见 docs/iterations/iteration_054_PLAN.md「核实回填」段：
- **新增最严重口 style_examples（审查遗漏）**：bootstrap 从全书 normalized_texts 采样（`auto_bootstrap.py:528-551` 含 tail 窗）→ apply 逐字落盘（`cli_apply_bootstrap.py:244-259`）→ 4 处注入 prompt（`writer.py:676/1047`、`plot_planner.py:521`、`debater.py:644`），全程零 `is_after_start`。**verbatim_prose 级**，且**注入端不可过滤**（md 行号锚 normalized_texts，manifest 章号锚原始 txt，异坐标系），须在 bootstrap 采样端卡起点上界。
- **source_excerpts 修正**：① 落盘带合法 `source_chapter_id`（`schemas.py:392`）→ **可过滤**（047b 未利用）；② 注入点是 **3 处**（`writer.py:703` 写 + `writer.py:149`/`book_runner.py:794` 评审），非单点。
- **entity_graph 拆分**：关系（`entities.py:41-99`）消费层**已**过 `is_after_start`；实体 key_facts/description（`entities.py:104-118`）**确零过滤**——审查"最大泄露口"指后者，成立，054b 底座 start-aware 治本。
- **消费层澄清（审查低估）**：KB/manual_facts/anchor 进 prompt 时**已**过滤（`kb_view.py:61-122`、`manual_facts.py:40-94`、起点有界 anchor）；`knowledge_index` 只注入条目计数非内容。
- **降级**：debater 起点章尾（`debater.py:628`）→ **none**（每章行区间硬封闭 `chapter_splitter.py:145`，读的是合法起点章本身）。
- **`_load_extractions` 非唯一集中点**：另有 `compressor.py:30` 独立 glob；但 entity key_facts 只走 auto_bootstrap 这条，改一处即堵漏，compressor 那条是纵深（KB 已消费层过滤）。
- **关键定性**：**longzu 当前不前向泄露是文件名字典序 + 70k char cap 在 longzu_3_1 截断的巧合**（book4/前传从未被采样），非机制——与 ch024 同款，坐实"换深起点必触发"。

**iter054 已拍板（2026-06-13）**：① ingest-to-start（054d）本轮做、作主线机制；② 054a/b 过滤作测试台+纵深 backstop；③ write/debate 已切 `gpt-5.5-low`（`.env`，extract/review 保持 high），ping 验联通 ok。

## iter054 实施进度（2026-06-13，mock 半收官 / 真模型半待授权）

**mock 半全部完成**（965→986 单测，每提交独立 verify.sh exit 0 + auto-pipeline 跑通）。三条已核实泄露口 style_examples / source_excerpts / entity_graph key_facts 全部**从源头封死**，缺口 A 底座自动重建编排齐活，主线机制 ingest-to-start 落地。提交链（`1dda0a1..7cb11b6`）：

- **054a 泄露硬封**（前序会话）：`c67f517` source_excerpts 消费端三路过滤 → `058fb9c` style/source_excerpts bootstrap 采样端源头封堵（`_normalized_context` 起点上界 + `before_start_line_limit` + apply 守卫）。
- **054b 核心**（前序）：`857fec8` `_load_extractions(before_start_only=)` start-aware 封 entity_graph key_facts facts 级泄露（接 graph/global_facts/anchor-fallback 三路）+ 折叠 054a-4 关系 timeline chapter_id 强制。
- **054b 自动化半**（本会话）：`230a03a` entity_graph 起点 stale sidecar（补 anchor 027 不对称缺口）→ `3c860c5` 提取覆盖闸前移（plan-chapters 硬 blocker + set-start-point 即时报）→ `c823e87` `rebuild-for-start` 编排（填 longzu 4 步人肉救火洞）。
- **054d 主线机制**（本会话）：`7cb11b6` ingest-to-start 物理截断摄入——normalize→split 后按起点物理裁 normalized_texts + 重写 manifest，下游天然有界、过滤层退化为 no-op。
- 既存红门禁修复：`622f0c3` auto-pipeline debate 步透传 force。

**关键发现/定性沉淀**（勿 re-derive）：① source_excerpts 的 `source_chapter_id` 是 LLM 瞎标的（喂的采样无章节标记）→ 消费端按它过滤不可靠，源头裁剪/ingest-to-start 才可靠。② compress→KB 路径（`compressor.load_extractions` 独立 glob）**绝不**加 start 过滤：kb_view 需完整 index 算"距起点最近 pre-start 状态"，裁剪会破坏它。③ 既存 bug `task_95bdc0d5`：`load_chapter_text` 读 source_file（原始 txt）却用 normalized 行号（manifest 混坐标），非泄露、另案。④ 铁律④逐字节不变已守：graph sidecar 缺失→fresh、覆盖闸无起点→fail-open、rebuild/ingest 均 opt-in 不碰 greenfield 路径。

**真模型半（054c）待用户 `CONFIRM_REAL_MODEL_SMOKE` 授权（≤¥20，铁律⑥）**：换非结局深起点跑 `rebuild-for-start`→续写 ch1-3；diff oracle（ingest-to-start ↔ full+filter 注入材料逐字节一致）；泄露体检；A-M5/M3 搭车修。schema 升级（entity key_facts 结构化）已确认**不与真模型同轮**（052 纪律），本轮零 schema 改动。

## iter054c 真模型段（2026-06-13，diff oracle 收官 / 续写改日续跑）

用户授权 `CONFIRM_REAL_MODEL_SMOKE` 实跑深起点 **`longzu_2_ch001`（龙族II 开篇，起点后 98 章真实素材在场，破 ch024 旧巧合）**。

**✅ 核心泄露验收已机器证毕（零真模型成本）**：两个同源克隆 `longzu_054c_ingest`（物理截断）vs `longzu_054c_full`（全量+设起点）的 `_normalized_context`（style_examples + source_excerpts 采样源，最严重口）**逐字节一致**（123141 bytes，diff 空）；起点后专属标志两模式皆 0；ingest 截断实证 kept 13/dropped 97/删 5 卷。→ full+filter ≡ 物理截断，封口正确性闭环（叠加 986 单测）。

**⏳ 续写 ch1-3 改日续跑**：遇 aetherheartpool Cloudflare Tunnel `Error 1033/530` 宕机（provider 侧，已恢复但拥堵）+ longzu 章节巨大（20-30K 字）高档 extract 极慢（分块章 967s），窗口提取 2/10 后用户拍板**收于确定性 oracle**。真模型累计 ¥2.93（多为宕机 530 重试损耗）。克隆保留（workspaces gitignore），改日用 `/tmp/extract_window.py`（流式+超时重试+续跑+绕分块）补完 → rebuild 收尾 → drive-book 续写。

**运维发现（沉淀）**：① 绕分块（单调用，30K 仍在 128K context 内）远快于 3 子调用；② LLM 调用无 per-call 超时 → 挂起永久阻塞，实跑须超时+重试；③ **`extract_all` 静默吞每章异常进 failure 记录、不向编排层抛**（extractor.py:393）——宕机时 rebuild 表现为"0 提取无报错"；054b 覆盖闸 blocker 兜底拦"底座没建好"。该健壮性缺口已立背景任务另案。

## iter054 本会话收尾（2026-06-13，extract_all 修 + 三视角审核 + 环境清理）

**`extract_all` 失败可见化（`04eb8a0`，上文「另案」已落地）**：新增 `raise_on_failure: bool = False`（默认逐字节不变，绿地/retry_failures/web jobs 全走默认）——循环内收集 failed_ids、跑完整批后有失败即 `log_event("extract","batch_failures",…)`，opt-in 时抛 `ExtractionBatchFailure`（暴露 failed_ids/extracted）；`rebuild_for_start` 传 `raise_on_failure=True` → 提取失败即 abort，不在残缺集上 compress/bootstrap；`main.py` rebuild handler 扩 `except (ValueError, ExtractionBatchFailure)` 清退。+1 mock 测，verify.sh exit 0 / 987 单测 OK。

**三视角 subagent 代码审核（本会话全部 feat/fix）—— 全部 GO，无阻断/高/中级缺陷**：
- 054b 自动化（`230a03a`/`3c860c5`）：铁律④ 逐字节不变（sidecar 缺失→fresh、coverage 无起点 fail-open）、stale 语义与 anchor 027 逐行等价、coverage blocker 闸序正确（append-mismatch 先命中）、无 import 循环、sidecar reader/writer 路径一致、测试覆盖关键分支。
- 编排（`c823e87`/`7cb11b6`）：窗口数学与 coverage 闸逐元素对齐（穷举无 off-by-one）、ingest 截断坐标(1-based `lines[:limit]`)/顺序(重写 manifest 前算完所有卷 limit)/多卷删除/幂等正确、源 `小说txt/` 不动、greenfield raise 保护。
- `extract_all` 修（`04eb8a0`）：纯加性向后兼容、5 个既有调用点全走默认、raise 在循环后保留「尽量多提取」、传播链唯一调用方 `main.py` 闭环捕获。
- **审核 nits（非阻断，待选，未改）**：① `main.py` set-start-point 的 coverage WARNING 调用落在 `set_start_point` 的 `try/except ValueError` 块内——未来若 `extraction_coverage_failures` 新增 ValueError 路径会误报命令失败（当前无触发路径）；② 缺两条 ingest 边界回归测试（起点=末章零截断 / 同起点重跑幂等，审核已手测通过）；③ `ExtractionBatchFailure` 文案硬编码 530 成因（已引导查 last_error）。

**环境清理**：054c 临时克隆 `longzu_054c_full`/`longzu_054c_ingest` + 5 个空 `unit_driver_*` 测试遗留 + `/tmp` 本会话脚本/日志（含 `extract_window.py`）**已全部删除**。真实书 workspace（longzu/shudian052/tianlong/alpha/i38drama01）与 longzu 27 章提取均**未被触碰**，git 干净。**改日续跑真模型续写须从头重建**（克隆与 /tmp 驱动已不在）：重跑 ingest-to-start（免费）或按 memory `real-model-run-needs-timeout-retry-driver` 重写超时+重试驱动补提取 → `rebuild-for-start` 收尾 → drive-book 续写 ch1-3。

**iter054 全况**：四轨（054a 消费/采样封口 · 054b 底座 start-aware + 自动化 · 054c 验收 · 054d ingest-to-start 主线机制）**mock 半全部收官**（965→987 单测，每提交独立 verify.sh exit 0）；真模型**核心泄露验收（diff oracle）证毕**；真模型续写冒烟待拥堵缓解续跑。本会话 7 提交（`857fec8..HEAD`：5 feat/fix + 2 docs），全程只 commit 未 push（铁律⑤）。

## iter055 真模型驱动器加固专项（2026-06-17，mock 收官 + 真模型 V1-V4 验证 + 多视角审查）

承接 iter054。本轮主轴 = **真模型驱动器加固**（capstone 顺延；未来 capstone = 自由生成 30+ 章长程续写，故驱动器按长程规格加固）。详见 `docs/iterations/iteration_055_PLAN.md`（含计划稿 + 实现回填 + 真模型段实测）。

**计划审核纠出 3 处错误**（实现前）：① 轨A 靠 models.yaml default 块"自动透传"会**静默失效**（config.py 透传只透 task_cfg key，不含 default 块）→ 改 `get_model_config` 显式映射；② 轨B 误判"默认不重试"（实为 models.yaml default 写死 retry_attempts:5）→ 实为 5→3 下调；③ 全局 120s 误杀长生成 → 分任务超时。用户拍板：分任务超时 + retry 5→3。

**提交链（`1f024b2..a5d81f1`，12 提交，全程只 commit 未 push 铁律⑤）**：
- 轨A `6c7cd99`：per-call 超时（config.py 显式映射修 no-op bug + complete_text/ping 注入 `timeout`>0 才加 + models.yaml 分任务）。
- 轨B `907701a`：`_is_transient`（litellm 类名 + 错误串 530/1033/50x/timeout/tunnel/cloudflare + isinstance stdlib ConnectionError/TimeoutError）仅 transient 重试 + 指数退避 cap30/jitter1 + retry 5→3。
- 轨C `8bd8d4a` + 对齐 `fbd3268`：`chunk_bypass_max_chars`（effective_threshold=max(threshold,bypass)，`.get` 非下标）+ `--no-chunk`；默认 **48000**（24-30K 长章默认单调用，治根因②）。
- 轨D `674c253` + 补 `9d8d9ef`：每章 `elapsed_ms`（done+failure 事件 + failure JSON）+ `--no-chunk` CLI（extract/rebuild）+ `per_chapter_attempts` 整章重试（仅 extract 命令）。
- 收官 docs `5fea8db`。
- **真模型实测修正 `8973273`**（见下，最重要）。
- 审查修正 `a5d81f1`（见下）。

**真模型段（用户授权 ≤¥20，实花 <¥3；载体 `workspaces/longzu`，gpt-5.5-low via 中转站，with_proxy=direct 直连）**：
- V1/V3/V4 验证加固生效：30K 章单调用成功 **204s**（attempt=1，reasoning 延迟非重试，«历史分块 967s）；llm_calls 记 attempt/tokens；续跑 **6s 秒跳过、0 call**。
- **V2 抓到核心缺口 → 修复 `8973273`**：litellm **不把 `timeout` 落到流式 SSE read**——流式（生产 `OPENAI_STREAM=1`）下 `timeout=5` 仍跑满 294s 成功，**轨A 治本超时在生产路径形同虚设、iter054 mid-stream 卡死根因未治**；非流式则 litellm 遵守（实测 58s 失败）。mock 测不出（mock 只验 `timeout` 被传入）。修法（用户拍板"批处理关流式 + 调高超时"）：① 批处理任务（extract/compress/debate/review/premise/plot_planner）`stream:false` 强制非流式拿回超时；② `write` 不设 stream 键，跟随 env（生产流式 UX）；③ complete_text+ping 加 `num_retries=0`（禁 litellm 内部重试叠加放大墙钟，单 attempt 19s→5s）；④ **config 透传排除所有已显式映射的标量键**（修既有隐患：`**task_cfg` 在显式 env 映射之后、用原值压掉 `LLM_REQUEST_TIMEOUT`/`DISABLE_PROMPT_CACHE`/`JSON_REPAIR` 覆盖；extract 加 request_timeout 后暴露）；⑤ 超时按实测调高 default 240/extract 400/compress 400/write 480/plot 600。**复验**：生产 env（OPENAI_STREAM=1）extract 非流式 + timeout=5 → **22s `litellm.Timeout` 快失败**，治本对批处理任务真正生效。

**代码审查（3 subagent 多视角，结论：端到端可跑通、无 blocker、63 项相关测试全绿）→ 2 处修正 `a5d81f1`**：
- 报错文案 `failed after {attempts}`→`{attempt}/{attempts}`（非 transient 提前 break 时只试 1 次，旧文案让运维误判重试满 3 次）。
- 整章重试**跳过 transient**：transient 在 call 级（轨B）已重试耗尽，整章再重试与 call 级**相乘**放大卡死窗口（per_chapter_attempts=3 + 分块 4call × call级3 → 最坏数小时）且 tunnel 仍挂不会更快恢复 → 立即失败交 re-run；整章重试只救确定性失败（合并/解析，复用 `_is_transient`）。
- 审查确认无误（勿 re-derive）：`_is_transient` 分类/context 守卫顺序、退避公式无 off-by-one、config 透传排除集逐一核验**零丢失零误排**、所有 7 个 `extract_all` 调用点兼容（新参带默认值置签名末尾）、15 个 LLMClient 构造点不受影响、CLI dest 名/默认参数/models.yaml↔code key 双向闭环。

**关键发现/定性沉淀（勿 re-derive）**：
1. **litellm 流式不执行 read 超时** —— 这是 iter054 卡死根因的真正盖子；批处理用非流式拿回超时。`write` 流式的 **idle-deadline（async/watchdog 真流式超时）是下轮项**（write 当前仍无 per-call 超时，靠 driver 180min 兜底）。
2. **config.py 透传隐患（既有，本轮修）**：`**task_cfg` 在显式 env 映射之后会压掉 env 覆盖；修法=透传排除所有已显式映射的标量键（保留 stream/chunk_*/rolling_*/model_env 等额外键透传）。
3. **中转站+gpt-5.5-low(reasoning) 慢**：单章 extract 实测 204-294s（reasoning token 多，attempt=1 非重试），超时值据此调高。
4. **verify.sh 解释器陷阱**：脚本内裸 `python3`，未激活 venv 时落系统 Python 3.9（无 tiktoken/无 PEP604 运行期）伪报 3 error。正确跑法：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` 或先 `source .venv/bin/activate`。
5. **既有 flaky 测试** `test_web_draft_edit.test_busy_workspace_returns_409`（jobs.py job 状态更新 vs `_WORKSPACE_JOBS` 注销的进程内竞态，高负载偶发；与 iter055 无关，已派背景任务 `task_5ea88c78`）。

**门禁**：mock 段每轨独立 verify.sh exit 0；收官全量 **1029 unittest OK + verify.sh exit 0 + Report snapshots OK**（48000 默认未漂移流水线快照）。零 schema 改动（铁律）。新增 4 测试文件（timeout 更新/retry 11/no_chunk 9/resilience 12/stream-per-task 4）。

**剩 V5（rebuild + 写 ch1-3，≤¥15，补 iter054 欠账）—— 未跑**（用户选"先不跑，做代码审查 + 结构验证 + 写接力"）。续跑须知：① 需先 `set-start-point longzu_2_ch001` + `rebuild-for-start --no-chunk`（**会改 longzu 工作区起点/重建底座**——或用独立克隆避免动主工作区）；② `write` 仍流式无 per-call 超时（idle-deadline 下轮补，靠 driver 兜底）；③ 批处理步骤（extract/compress/debate/review/plot_planner）现已非流式 + 真超时保护，rebuild 的提取窗口受保护。

**数据状态**：longzu 工作区有本轮真模型测试遗留——`longzu_1_ch007` 成功提取（V1a）、`longzu_1_ch009` 成功（V2 294s）、`longzu_2_ch005` 失败记录（timeout=5 测试）。可 `extract --force` 覆盖或忽略。其余真实书工作区未触碰，git 干净（仅 docs/product/ 两文件未跟踪，符合预期）。

**下轮候选**：① `write` 流式 idle-deadline（async/watchdog 真流式超时，补齐 write 的 per-call 保护）；② V5 续写 ch1-3；③ flaky `test_busy_workspace` 修（已派背景任务）；④ verify.sh 钉 venv python（免解释器陷阱）；⑤ entity timeline/key_facts schema（052 起顺延）。

## iter056 作家风格卡（2026-06-18，mock 段收官 + 真模型 V1/V3/V5 完整 + 三维审查）

承接 iter055。本轮主轴 = **premise 自创书的轻量「作家风格卡」**（预置库 + 上传样本提取，仅 premise 注入）。详见 `docs/iterations/iteration_056_PLAN.md`（计划 + 三维 subagent 审查修正 + 实现回填 + 真模型 V1）。

**规划期三维对抗审查**（架构/前端/产品风险）暴露并修正：① 注入区非空地（style_examples 已占、premise 也可能有→共存+优先级）；② 缓存段污染（风格卡塞 stable 段→改卡失效 KB 缓存→改为**独立第 3 cache 段**）；③ 字节兼容（block 自带尾分隔 + cache_segments 条件不加空段）；④ polish 漂移（polish 也注入）；⑤ 戒律优先（系统戒律/linter/reviewer > 风格卡）；⑥ 前端 IA（折叠区 + 单漏斗 + cols-3 + pollJob 替代平铺过载）。用户拍板：完整做（含上传提取）+ 强护栏；真模型搭车 V5（但 V5 与风格卡解耦、实际未跑）。

**提交链（`40db504..acdd6a9`，6 提交，只 commit 未 push 铁律⑤）**：轨A `40db504`（WriterStyleCard schema + 预置库 6 张 + writer_style 模块，复刻 premise_expansion 范式）· 轨B `998c4cf`（style_extract task + _mock_json stub + extract + n-gram 反污染 + jobs step）· 轨C `fb3f94a`（_write_prompt 独立缓存段 + polish 注入 + 仅 premise + 字节兼容）· 轨D `c689041`（5 端点 + workbench has_start_point + 前端折叠区 + gitignore 护栏）· PLAN 文档 + 真模型 V1 修正 `acdd6a9`。

**真模型段（用户一并授权，直连中转站 gpt-5.5）**：
- **V1 提取 + 反污染 ✅**：280 字「冷峻硬汉」样本 → 9/9 标量 + 8 signatures + 8 taboo 全填充（18.6s），质量精准、`_scrubbed=[]`。**抓到并修复 mock 测不出的缺口**（`acdd6a9`）：`complete_json` 不注入 schema + extract prompt 缺英文 key → 首跑 9 维全空；prompt 显式列 JSON 字段后复验全填充。
- V2 快照 ✅（preview + mock 验证）；V4 缓存隔离由 `test_writer_style_inject` 逐字节钉死。
- **V3 端到端真写 ✅（2026-06-18 补跑）**：shudian052 激活「抒情纯文学」预置卡 → 写第 8 章 → **Approve 4/5、panel 8.38**、正文零指令泄露、文风明显匹配（长句绵密 / 意象稠密 / 心理留白 vs 原悬疑网文）、**lint 零违规 + 原作风格 agent fidelity 9** → 坐实风格卡不与系统戒律/linter 冲突（审查 P1-B 担心未发生）。
- **V5 续写欠账 ✅ ch1-3 完整 Approve（2026-06-18 搭车，彻底了结 iter054 欠账）**：`set-start-point longzu_2_ch001` + `rebuild-for-start --no-chunk`（8 章 extract 单调用、验证 iter055 加固）→ drive debate/plan/write → **ch1 Approve 5/5 panel 7.82 / ch2 Approve 3/5 panel 7.36 / ch3 Approve 5/5 panel 7.52**，三章共 17173 字、全部零污染零指令泄露（卡塞尔学院→宿舍调查→训练馆连贯）、真实 cost **¥7.54**。续写书不注入风格卡，M2 自检确认（顺验"仅 premise"边界）。**ch2/3 受阻→直连修复根因**：首跑 3 次 resume 撞 `InternalServerError/Connection error`，实测真因是 **Clash 系统代理路径不通**（`curl -x 7897`→HTTP 000、直连→401）；`with_proxy.sh` direct 分支 `NO_PROXY` 钉死 aetherheartpool.top 直连（`4cdd9bd`）后一次跑通。

**关键发现/定性沉淀（勿 re-derive）**：
1. **`complete_json`(llm_client.py:416) 不注入 JSON schema** —— 仅传 messages、靠 prompt 文字描述字段。任何用 complete_json 的新 response_model **必须在 prompt 显式列 key**（英文 key + 中文说明），否则 LLM 自拟 key → `response_model(**data)` 全回退默认值（额外 key 静默忽略、不触发 json_repair）。这是 premise_expansion.py:52 记录的 iter052「部分字段空落盘」同根因；本轮 WriterStyleCard 11 字段全不匹配 → 全空，已修。
2. **仅 premise 判定 = `start_point.get_start_chapter_id()`**（镜像 _canon_anchor_block）；风格卡（无起点注入）与 canon_anchor（有起点注入）完全互斥。
3. **快照非引用**：预置卡激活 = 快照 fields 入 `data/writer_style.json`，预置库升级不影响已激活卡（`preset_version` 仅审计）。
4. 风格卡**不接 mtime 失效链、不进 chapter fingerprint** —— 改卡只下一章生效、不回炉已写章。
5. **起点重置后必须连带清 rolling + 旧 drafts（V5 关键运维坑，2026-06-18 实测）**：`rebuild-for-start` 重置起点后，`outputs/drafts/` 残留的旧续写 `chapter_*`（verdict=Approve）+ `rolling_chapter_summary.json` 会**双重污染**新续写——① 旧 approved 章被 `skipped_approved` 跳过（write-book 从盘面推导进度，`book_driver.py:12`），新章不写、用旧章冒充；② 旧 rolling 被 writer 读作前情（`render_rolling_context` 不按 chapter_no 过滤，`chapter_summary.py:113`），把新 ch1 带偏写成旧情节。**修法**：write 前移走旧 `chapter_*` + `rolling_chapter_summary.json`（备份或 `prune_from_chapter`）。这是 iter054/055 V5 没跑通的隐藏坑之一。
6. **aetherheartpool 中转站必须直连、不能走 Clash/VPN 代理（2026-06-18 实测）**：走 Clash 系统代理(127.0.0.1:7897)→HTTP 000 不通；直连(`curl --noproxy`)→401 可达。`with_proxy.sh` direct 分支已 unset 全部 proxy + 显式 `export NO_PROXY` 含 `aetherheartpool.top`（`4cdd9bd`）。这是 ch2/3 续写撞 Connection error 的**真根因**（非中转站服务端，是本地 Clash 代理路径）。中转站恢复后仍偏慢（直连 ping 152s），直连可完成。直接 `python` 跑（不经 with_proxy）会带系统 `HTTPS_PROXY=7897` → 走 Clash → 失败；须 `env -u HTTP_PROXY -u HTTPS_PROXY` 或经 `with_proxy.sh`。

**门禁**：收官全量 **1079 unittest OK**（新增 4 测试文件 50 例：writer_style 22 / extract 7 / inject 7 / web 14）。前端 preview 实测（风格卡区渲染 / gate / 激活高亮 / 编辑器 / 零报错）。零既有 schema 改动（铁律）。

**数据状态**：测试遗留 workspace `style_real`（V1）+ `style_preview`（preview）——gitignored，可删。**longzu 起点已改为 `longzu_2_ch001`**（V5 续写）、`outputs/drafts/chapter_01-03.md` 为本轮 V5 产出（全 Approve）、旧 Jun13 续写已移到 `outputs/drafts/_backup_jun13_pre_v5/`（如需恢复 longzu 原状须 `clear-start-point` + 还原备份）。

**下轮候选**：① iter057 立 **capstone 本体**（30+ 章长程续写）——⚠ **capstone 前必先修长程结构性 bug（见下「长程审查」P0-A/P0-B）**；V5 仅证明 rebuild + 续写 3 章**功能链路打通**，长程稳定性**未验证、且审查证伪**（3 章测不出的 5 个 bug，30+ 章会爆）。② 风格卡端到端深验（文风量化对比 + 缓存计费隔离）；③ 风格卡增强（scope/多卡）；④ iter055 候选（write idle-deadline 等）。

## iter056 附：长程续写（capstone）结构性审查（2026-06-18，双 subagent 对抗 + 源码核验）

> **决策（用户拍板 2026-06-18）**：iter056 风格卡本轮**收官**、下列 5 bug **本轮不碰**；统一留作 **iter057 capstone 立项的前置专项**——P0-A 重构 + HIGH-2 实现是迭代级工作，宜与 capstone 设计一起系统做、避免碎修。立 iter057 时**先按本节末「前置顺序」修完 P0-A/P0-B（阻断器）+ 补 HIGH-2/P1-C，再谈 30+ 章真跑**。

V5 续写 3 章全 Approve **只证短链路功能打通，非长程稳定**。双 subagent（状态累积 + 驱动器可靠性）逐行源码 + 实测注入尺寸，发现 5 个「3 章测不出、30+ 章爆」的真 bug，**capstone 前必修**（均已 file:line 核验）：

- 🔴 **P0-A `plan_fingerprint` 全列表耦合**（`plot_planner.py:319-336` 哈希 chapters 全列表 + target_chapters）：开 `--replan-every`（30+ 章实际必开）+ 中途 resume → append 改写 fingerprint → 已写章 `plan_fingerprint_mismatch`（`chapter_status.py:100`）→ 非 `skipped_approved` → `on_blocked=stop` 卡死全程 / `--force` 重复写 + `entity_advance._apply_selected` 非幂等重复突变实体图（**重复计费 + 状态损坏**）。**修**：plan_fingerprint 按章独立、不哈希全列表。
- 🔴 **P0-B write 流式无 idle-deadline**（`models.yaml` write 无 `stream` 键 → 回落 `OPENAI_STREAM=1` 流式 → `request_timeout:480` 失效，`llm_client.py:179-183` 注释已实测；`_consume_stream` 无 per-chunk 超时）：中转站抖动下单章卡满 driver 180min 兜底 → 30 章累积数小时空等、detach 静默。**修（最省事）**：`models.yaml` write 加 `stream:false`（非流式 litellm 遵守 timeout，注释实测 58s 触发）。
- 🟠 **HIGH-2 rolling `compressed_older` 半成品**（`chapter_summary.py` 只读 line 22/33/38/140、**零写盘点**）：ch15+ 早期章退化成 ~10 条 12 字残片 → ch25+ 早期伏笔/设定对 writer 失忆 → 长程一致性地基崩。**修**：真正实现周期性 LLM 压缩并写盘累积，或显式把长程记忆托给 KB/entity、重定位 rolling 为纯近场。
- 🟠 **BLOCKER-1 `plan_target` 默认 10**（`book_driver.py:763`）：`--chapters 30` 用默认参数 → readiness 在 ch11+ 缺 plan → 规划阶段 block（fail-closed 不烧钱，但默认配置长程跑不动）。**修**：plan_target 默认随 chapters，或缺失时硬报错提示 `--plan-target`/`--replan-every` 二选一。
- 🟠 **P1-C outline 漂移不检测**（`book_driver.py:309` 只查起点指纹 + outline_sha256，无"剧情 vs outline 语义偏离"）：ch15-20+ 实际剧情偏离初始 outline，评审 fidelity 拿失真 outline 当基准 → 正确承接被误拒/漂移被放行。**修**：周期性 outline↔rolling 偏离检测 + fidelity 基准切到滚动上下文。

**认知纠偏**：上下文窗口膨胀**不是 bug**（实测 writer prompt 26K vs redline 107K，所有注入静态截断、无界增长路径不存在）。长程敌人是**信息饥饿/漂移**（ch30 看不到 ch3 伏笔），非溢出。entity render 是常量税（续写期只 append timeline、render 取 active）；成本账本 resume 不重复计费（安全）；编排骨架（断点幂等/预算双层/互斥/终态）在**不开 replan** 窄路径上可靠、单测覆盖到位。

**capstone 前置顺序**：先修 P0-A + P0-B（阻断器）→ 补 HIGH-2 + P1-C（一致性根基）→ `test_book_driver.py` 补「replan + 段间 resume + 流式卡死」三件（当前零覆盖）→ 先 mock 全跑 30 章 + 真模型 ch1-15 → 才谈 30+ 真跑。30 章保守配置需 2-5 次人工 resume；50 章评审全过 ~0.5%；100 章现机制不可能一次跑完。

## iter057：长程 5 bug 全修复（2026-06-18，subagent 审核 + 源码核验 → 实施）

**接力指令反转**：iter056 末拍板「5 bug 留 iter057」，本轮用户改为**现在修**。先派 3 个 general-purpose subagent 逐行复核根因/影响半径/向后兼容/测试缺口（修正原审查 2 处认知偏差），再按风险递增实施，**每个 bug 独立 commit**（`fix/feat(iter057)`）。

**5 bug 修复落地**：
- ✅ **BLOCKER-1**（`book_driver.py:764`）：删 `min(10,...)`，默认 plan_target = `chapters+resume_from-1` 覆盖全程，与 readiness 口径对齐。+3 单测（默认分支此前零覆盖）。
- ✅ **P0-B**（`models.yaml` write）：加 `stream:false`（**方案A止血，用户拍板**）。当前架构无流式真实消费者（产出落盘+人工审，detach stdout 进 DEVNULL），UX 损失≈零；非流式 litellm 遵守 480s timeout。改 `test_llm_client_stream_per_task` 断言。
- ✅ **P0-A**（`plot_planner.py:319`）：plan_fingerprint 收窄为只哈希全局上下文（overall_arc+start_chapter_id+start_point_fingerprint），章节级交给 `chapter_plan_item_fingerprint`。schema_version 1→2。
  - **向后兼容必配**：`scripts/migrate_plan_fingerprints.py`（幂等）已对 longzu/shudian052/tianlong/root 跑——4 plan + 15 meta + 17 review，迁移后 plan `stored==recompute`、各 meta 全对齐（实证）。
  - ⚠ **subagent 漏审的语义冲突**（已发现 + 用户拍板「接受新语义」）：plan_fingerprint 收窄**必然**改变 web 结构化编辑「编辑任意章→所有已写章 strict-expire」的旧 pin 语义（`test_workbench_replan.py:331` 明确 pin、警告勿削弱），新语义「**只 strict-expire 被编辑章**（via item 指纹）」。二者技术**不可兼得**（要 replan append 不卡死已写章，就不能让加章/改章翻转全局指纹）。`routes.written_chapters_invalidated` 同步改为只报被编辑章。
  - **真实回归**：补 `test_append_preserves_plan_fingerprint` + `chapter_status` 真实校验链（现有 replan 测试 mock 掉 chapter_status 是**伪覆盖**）+ 迁移脚本单测；更新 edit/workbench/web_plan_edit 旧全局 strict-expire 断言。
- ✅ **HIGH-2 MVP**（`chapter_summary.py`）：compressed_older 此前**零写盘**。新增确定性逐章 compact 写盘（滑出近场 5 章 → 一行 ≤60 字、上限 40 章），render 优先吃它、prune 同步回退；compressed_older 空时回落旧 12 字逻辑（向后兼容）。**周期性 LLM 二次压缩留完整版**。
- ✅ **P1-C MVP**（`src/outline_drift.py` 新 + `book_runner` readiness 接入）：outline 提及的实体锚点在最近 10 章 rolling 命中率 <0.4 → `outline_semantic_drift` warn（**只 warn 不 block**，best-effort 不让探针 block readiness）。**纠偏**：reviewer **不消费 outline**（fidelity 基准是源书原文风格），漂移真实危害在 **write-time 喂图纸**、非 review 误拒 → MVP 只做可见性，不碰 reviewer。LLM 语义判定 + write-time 基准切换留完整版。

**原审查 2 处认知纠偏（subagent 复核）**：① P0-A 比记录更严重——非「30 章后爆」而是「触发一次 replan → 下一段 resume 立刻 `BookRunBlocked` 卡死」（driver 每段重 walk 全盘）；② P1-C 因果链下半段**错**——reviewer 不消费 outline（`reviewer.py:247` 无 outline 参数），真实战场在 write-time prompt 注入（`writer.py:686`），不是 review 误拒。

**验证**：全量 `pytest` **1097 passed**（首跑 1096 passed + 1 failed——`test_openai_stream_env_enables_streaming_by_default` 用 write task 测 env 默认流式，P0-B 改 write→非流式后该断言过时；subagent B 漏看、**被全量回归抓到**，改用未配 stream 的 `default` task 复跑全绿）。分项：BLOCKER-1 `test_book_driver` 31 passed（含 E2E）、P0-A 影响范围（plot_planner/chapter_status/book_runner/workbench/web_plan/migrate）106 passed + 迁移对齐实证、HIGH-2 rolling 19 passed、P1-C+readiness 58 passed。**教训**：subagent 只读审到的「不受影响」测试清单不可全信，全量回归是兜底。

**留后续（完整版，均需真模型验证）**：P0-B 方案B（idle-deadline watchdog 保流式）、HIGH-2 周期性 LLM 压缩（融合伏笔链、控 token）、P1-C LLM 语义判定 + write-time 基准从静态 outline 切到滚动上下文。capstone 30+ 章真跑前仍按上节「前置顺序」：先 mock 全跑 30 章 + 真模型 ch1-15。`test_book_driver.py` 的「replan + 段间 resume + 流式卡死」三件已补 chapter_status 真实校验链层（subprocess 端到端层仍可加固）。

## iter058：前端用户路径 P0 修复——钱与静默错误（2026-06-22，审计取证 → 实施）

**来源**：`docs/FRONTEND_BUG_AUDIT_2026-06.md`——codex 三-subagent 审计报 14 条，Claude 用 3 个 Explore agent 逐行核对 + mock 隔离探针 + 一次真模型最小 onboarding 取证，13 条实锤 + 2 新发现（NEW-A/NEW-B）、无误报。审计 §4 划三轮：**iter058=P0（钱/静默错误）** / iter059=P1（崩溃卡死） / iter060=P2（并发体验）。本轮只做 P0 三条，沿用「复用已验证护栏、零新机制、默认路径 byte-identical、确定性单测兜底、按风险递增」铁律，全确定性不烧钱。

**三 bug 修复落地（执行序 #6b → #2 → #1，每条一轨）**：
- ✅ **#6b NaN·Infinity 穿透 float 校验**（`routes._float_param` / `wizard._optional_float`）：仅 `<min`/`>max` 比较，IEEE-754 下 NaN 全 False 穿过 → 下游 `nan>0`=False 绕过成本闸、`monotonic()>nan`=False 永不超时。修：`float()` 后插 `math.isfinite` 守卫（一道收 NaN+±Inf），对齐同文件 `_int_value`；两文件加 `import math`。**defense-in-depth**：`jobs._float_param`（同名但裸 float、money/timeout 数学前最后一跳）非有限回落 default。+14 单测/e2e（`tests/test_float_finite_guard.py`）。
- ✅ **#2 抽取失败静默吞**（`extract_all(raise_on_failure=False)` 默认吞错、两调用方不传）：**混合策略（用户拍板，覆盖 iter054c 的 onboarding-only「尽量多抽」）**——单步 `jobs._step_extract` 传 `raise_on_failure=True` + try/except `ExtractionBatchFailure` → `_blocked("extraction_failures", …)`（友好/可见/可重试、保留已抽章）；onboarding `auto_pipeline._run_prepare_steps` 传 `raise_on_failure=True` → loud raise（不在残缺 KB 上续跑 bootstrap/debate/写作，已抽章留盘 resume 补失败章）。与 `rebuild_for_start` 既有 True 对齐；retry_failures 路径不动。+6 单测（`tests/test_extract_failure_surface.py`）。
- ✅ **#1 onboarding 预算完全失效**（`run_auto_pipeline` 无 `budget_cny` 参数，`_step_auto_pipeline` 不读不传——真模型实测 ¥0.001 上限被无视、发 9 次真实调用 / 17.6k tokens / 293s 仍 running）：`run_auto_pipeline`/`_run_prepare_steps` 接 `budget_cny`，**复用 write-book 三件套**（`book_runner.BudgetExceeded` / `_llm_log_line_count` / `cost_estimator.estimate_cost_since`，lazy import）在每个 LLM 步后结算成本、超限早停 raise（debate 后超限即跳过 plan 的 6 次 plot_planner 调用 + write）；`_step_auto_pipeline` 读 `budget_cny`（缺省 `_default_budget_cny()`=10 元、显式 0=不设限，镜像 `_step_write_book`）、捕获 `BudgetExceeded` → write-book 同款 `budget_exceeded` 终态（已在 `TERMINAL_STATUSES`），`_summarize_result` 回显 cost/budget。+11 单测（`tests/test_auto_pipeline_budget.py`）。

**关键发现/定性沉淀（勿 re-derive）**：
1. **零日志格式变更**：审计 §3.1 担心「llm_calls.jsonl 只记 token 不记 cost_cny→预算无从计算」——**核验证伪**：`estimate_cost_since(line_offset)` 早已从 token 按单价（USD/M × 7.2）算出 cost_cny，write-book/review-chapter 都在用。#1 直接复用，不碰日志。
2. **review-chapter 是 #1 的现成范式**：`_step_review_chapter`（jobs.py:500）已示范「job 起点记 log 偏移 → 事后 `estimate_cost_since` 结算 → 超限置 `budget_exceeded` 终态」；但它「事后结算」是因**单章评审无 inter-chapter checkpoint**——auto-pipeline 有 9 个天然检查点，故本轮做**步间早停**（真止损）。
3. **默认路径 byte-identical 是硬约束**：`run_auto_pipeline` 加 `budget_cny` 后，`budget_cny≤0` 时 `_budget_check` 保持 `None`、所有检查点 `if … is not None` 短路——`test_auto_pipeline` 逐字断言 9 步进度标签 + `("done",1.0)` 不变。
4. **/run 的 params 是嵌套的**（`api_run_step` 从 `payload["params"]` 取，非 body 顶层）：首版 #6b e2e 误放顶层 → params 为空 → 202 假绿，自查抓到。`_validate_write_book_params`（走 `routes._float_param`）才是 /run write-book 的校验闸。
5. **两个同名 `_float_param`**：`routes._float_param`（校验、返 tuple、#6b 主目标）vs `jobs._float_param`（裸 float、内部解析）是不同函数。
6. **book_runner 不 import auto_pipeline**（无环），故 auto_pipeline lazy `from .book_runner import BudgetExceeded, _llm_log_line_count` 安全，且 jobs.py 早有同款 lazy import 先例。

**门禁**：全量 `.venv/bin/python -m unittest discover -s tests` **1128 passed / 0 failed**（347s；1097 基线 +31）。回归确认 `test_auto_pipeline`（进度契约）、`test_web_wizard_e2e`（mock onboarding 现带 10 元默认上限仍 succeeded）、`test_workbench_e2e`、`test_budget_guard`、extractor/iter055 resilience 全绿。零既有 schema 改动。**只 commit 不 push（push 待用户，用户常从终端自行 commit/resume）；本轮 commit hash 待入库**。

**数据状态**：纯代码 + 测试 + 文档改动，未触碰任何 workspace / 真实数据 / .env。审计探针在 `/tmp/audit_probes/`（throwaway）。

**下轮候选**：① **iter059（P1：崩溃卡死）**——坏 JSON 共因 #4/#5/#10/#13（裸 `read_json`→`read_json_optional`/`*_invalid` blocker，统一改法收四条）、#8 auto-advance 读移入 try、#3+NEW-B 上传 UTF-8 校验 + 0 章 manifest 回滚 workspace、#6a+NEW-A 整数上限 + catch `OverflowError`、#9 split gate 改认 `*.txt`；② iter060（P2：#7 start-point reservation / #11 writer-style 样本竞态 / #14 drama 原子写 / #12 协作式取消）；③ onboarding 专属预算 env 旋钮（按需）；④ #1 真模型复跑坐实 `budget_exceeded` 早停（本轮 mock 确定性为准、未跑真模型）。

## iter059：前端用户路径 P1 修复——崩溃与卡死（2026-06-22，实施）

**来源**：`docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 划定的 **iter059=P1 段（崩溃卡死）**，5 组共 9 条。承接 iter058（P0，1128 tests OK）。共同主线：关键状态文件用裸 `read_json`（存在但损坏→`JSONDecodeError`）、上传/整数边界缺校验。沿用 iter058 铁律：复用 `read_json_optional` 护栏、**逐调用点改不动底层**、默认路径 byte-identical、确定性单测兜底、按风险递增分 commit、全程不烧钱。

**5 组修复落地（commit 序：小→大 / 低→高风险）**：
- ✅ **#9 单步 split gate**（`jobs._step_split`）：gate glob `*.md` 但 `text_normalizer` 产 `*.txt` → 单步 split 永远 `blocked: normalized_missing`（auto-pipeline 直调 `split_all()` 不走 gate 故无感）。改同时认 `*.txt`/`*.md`。
- ✅ **#10 rolling summary**（`chapter_summary.load_rolling_summary`）：docstring 承诺 "malformed degrade to empty" 但用裸 `read_json` 抛错（文档↔实现矛盾）。→ `read_json_optional`，坏文件降级空态。
- ✅ **#6a+NEW-A 整数参数**（`routes._int_value` / `_validate_write_book_params`）：只 catch `(TypeError, ValueError)` → `chapters=Infinity`（JSON 字面量→`float('inf')`）走 `int(float('inf'))` 抛 `OverflowError` 漏成 **HTTP 500**；四参数无上限（999999999 被 202 接受）。加 `math.isfinite` 预检（对齐 iter058 #6b）+ `OverflowError`→400；chapters/resume_from/max_retries/replan_every 上限 2000/10000/20/2000。+13 单测/e2e（`tests/test_int_finite_guard.py`）。
- ✅ **#5 坏 draft meta/review**（`chapter_status`）：裸 `read_json` 读 meta(:52)/review(:116) → 坏文件击穿 resume/status。meta→`read_json_optional(.,{})`（approved=False/verdict=None）；review→`read_json_optional(.,None)`（落既有 `external_review_invalid`，`{}` 默认会是 dict 绕过检查误落 reject）。
- ✅ **#13 driver state/pid**（`book_driver`）：5 处裸 `read_json`（`load_state`/`_another_driver_running`/`cmd_status`/`cmd_stop` + ensure-plan 的 chapter_plan 读，`or {}` 只兜 None 不兜坏 JSON）→ `read_json_optional`；`cmd_status` 加 `driver_state_invalid` 诊断（state 文件存在但不可读≠缺失）。
- ✅ **#4 坏 chapter_plan（Option B，用户拍板）**：`writer._load_chapter_plan` 裸 read **且** `ChapterPlan(**data)` 对错 schema 抛 pydantic `ValidationError`（双抛路径，单换 `read_json_optional` 不够）→ 新 `ChapterPlanInvalid(ValueError)`，守 read + 构造；`book_runner.check_write_readiness` catch → **独立** `chapter_plan_invalid` blocker，`_blocker_kind`/`_primary_blocker` 加 kind + 标签「章节计划文件损坏 / 重新生成计划」（与「缺少章节计划」区分「损坏」vs「缺失」）；`_load_raw_chapter_plan`→`read_json_optional`；GET /readiness 不再经 `_safe_readiness` 泄 `readiness_error:JSONDecodeError`。
- ✅ **#8 auto-advance**（`book_runner._auto_apply_advances`）：proposal(:873)/entity_graph(:879) 读在 try（catch `ValueError⊇JSONDecodeError`）**之外** → 章节已 Approve、正文已落盘后命中坏文件抛未捕获 → job failed 而内容已在盘（割裂态）。两读→`read_json_optional` 降级 no-op（`applied_count=0`）。
- ✅ **#3+NEW-B 上传校验**（`wizard.start_upload` + `auto_pipeline._run_prepare_steps`）：`.txt` 裸 `write_bytes` 永不抛 → 非 UTF-8/0 章被 202 接受 → 后台 cryptic failed + workspace 滞留 + 同名重传 409。`.txt` 加 `decode("utf-8")` 校验 + `_has_detectable_chapters` 同步 0 章探针 → `_UploadRejected`→rmtree+400（**Option 1 同步预检**，对齐坏 EPUB UX、规避异步线程回滚竞态）；`auto_pipeline` split 后 0 章 `raise ValueError`（在 `extract_all(raise_on_failure)` 前，让「0 章」友好错误优先）作绕过 wizard 的权威后台兜底。+2 e2e 回滚测试（镜像 `test_corrupt_epub_rolls_back_workspace`）。

**关键发现/定性沉淀（勿 re-derive）**：
1. **`_load_chapter_plan` 双抛**：`read_json` 的 `JSONDecodeError` + `ChapterPlan(**data)` 对错 schema（缺 `target_chapters`/`overall_arc`/`chapters`）的 pydantic `ValidationError`，必须连守；空 `{}` plan 也从崩溃变干净 blocker（改进）。
2. **#4 调用方扇出（最高风险，已逐一审计）**：`_load_chapter_plan` 6 调用点——`run_write_book`(:82)/`writer.write_chapters`(:88) 兜成 None（require_plan=False 边缘）、readiness 入口 catch→blocker、`jobs._step_review_chapter` 兜成 `chapter_plan_invalid` blocked、replan(:304) 已在 `except Exception` 内；`ChapterPlanInvalid` 子类 `ValueError` 作安全网。
3. **`read_json` 仍在 `book_runner` 5 处用**（meta/review/failure，728/741/790/791/858）——**不在审计 P1 清单**，本轮不动避免 scope creep；底层 `read_json` 不降级（`write_json` 指纹门控等依赖 fail-loud）。
4. **两处测试因正确性更新（非回归）**：`test_web_routes_get` 旧断言坏 plan 产 `readiness_error` 泄漏（正是 #4 要修的 bug）→ 改断言干净 `chapter_plan_invalid`；`test_auto_pipeline_budget`/`test_extract_failure_surface` mock `split_all=[]`（占位）撞新 0 章 guard → 改非空 list（split 成功应≥1 章）。
5. **#3 同步探针 lenient**：仅「无任何 zh/en 标题行」才拒（防误拒合法上传），权威 0 章判定交后台 `auto_pipeline` split guard（绕过 wizard 的路径也覆盖）。

**门禁**：全量 `.venv/bin/python -m unittest discover -s tests` **1158 passed / 0 failed**（1128 基线 +30；test_bad_json_blockers 14 + test_int_finite_guard 13 + split 1 + wizard 2）。零既有 schema 改动，默认路径 byte-identical。**只 commit 不 push（push 待用户）**；本轮 8 个 fix commit + 1 docs commit（含先行补提的 iter058 commit `4785e39`）。

**数据状态**：纯代码 + 测试 + 文档改动，未触碰任何 workspace / 真实数据 / .env。

**下轮候选**：① **iter060（P2：并发与体验）**——#7 `set_start_point` 包 `workspace_reserved` / #11 writer-style 样本 per-job 唯一路径（TOCTOU）/ #14 drama 写端点 `write_json` 原子 + reservation / #12 长步骤协作式取消；② #4 真模型复跑坐实 `chapter_plan_invalid` 端到端；③ `book_runner` 剩余 5 处裸 `read_json`（meta/review/failure）按需收口。

## iter060：P2 收官 + Codex 复审补漏（2026-06-23，实施）

**来源**：`docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 划定的 **iter060=P2 段（并发与体验）** 4 条（#7/#11/#14/#12）+ 一轮 **Codex 复审补漏（A–F）**——补 iter058/059 finite 守卫与坏-JSON 降级未覆盖的**对称入口**。承接 iter059（P1，1158 tests OK）。**至此审计 16 条全部清零 open。** 沿用 iter058/059 铁律：复用已验证护栏（`workspace_reserved` / 原子 `write_json` / `read_json_optional` / `math.isfinite`）、零新机制、默认路径 byte-identical、确定性单测兜底、按风险递增分 commit、全程不烧钱。

**P2 4 条 + Codex A–F 修复落地（commit 序：低→高风险，每条一轨）**：
- ✅ **Codex-A /readiness 整数上限**（`api_workspace_readiness`，`routes.py`）：经 `_parse_int` 裸 `int()` 无上限 → `chapters=999999999` 流入 `book_runner` `list(range(...))` 物化近 10 亿元素（write-book 入口 iter059 已 clamp 2000/10000/2000，readiness 这个**对称入口**漏了）。handler 内 clamp `chapters`/`resume_from`/`replan_every` 到同上限（仿同文件 `api_workspace_logs_tail` 的 handler 内 clamp，只读探测 clamp 后继续跑非 400）。+2 单测（`tests/test_int_finite_guard.py`）。
- ✅ **Codex-B timeout 有限性（双层）**（`_validated_run_params` + `_timeout_deadline`，`jobs.py`）：仅 write-book/plan-chapters 校验 `timeout_minutes` 参数 → 其它 step 的 `NaN/inf` 穿到 `_timeout_deadline` 因 IEEE-754（`nan<=0`=False）产 `nan` deadline、`monotonic()>nan` 恒 False → **超时永不触发**（iter058 #6b 同类 bug 换入口）。① `_validated_run_params` 对**所有** step 用 `_float_param` 校验 `timeout_minutes`（NaN/inf/负→400）；② `_timeout_deadline` 加 `math.isfinite` 兜底（defense-in-depth，对齐 iter058「`jobs._float_param` 回落」范式）。+3 单测（`tests/test_float_finite_guard.py`）。
- ✅ **Codex-C/D/E web 读面坏 JSON 降级**（`routes.py`）：manifest(543)/草稿详情(1617/1620/1621)/草稿列表(1642/1655/1656)/entity·relationship PUT graph(1323/1398) 裸 `read_json` → 坏文件 `JSONDecodeError` → server.py 兜底返 **500 击穿读面**。裸 `read_json`→`read_json_optional`；PUT 两处坏 graph 降级 `{}` 后命中既有 `isinstance` 守卫返回 404『run prepare first』、在 `write_json` 前 return，**不覆盖坏文件**。+5 单测（`tests/test_bad_json_blockers.py`）。
- ✅ **Codex-F book_runner 残余裸读**（`book_runner.py`）：5 处裸 `read_json`（728/741/790/791/858，iter059 R6 主动 scope 外的残余）→`read_json_optional`：790/791 经 try 外路径冒泡出 `run_write_book` 击穿 resume、858 在异常善后中二次抛错顶替原始快照。`read_json` 至此 `book_runner` **全无裸读**，清理未用 import。+3 单测（`tests/test_bad_json_blockers.py`）。
- ✅ **#7 起点保存 reservation**（`api_workspace_set_start_point`，`routes.py`）：裸 `use_workspace`，reserved（write-book auto_advance 持锁）时仍穿过写入绕过 409 互斥。写块包 `jobs.workspace_reserved` + `use_workspace`（照搬 `draft_save` 范式），`workspace_busy`→409。+2 单测（`tests/test_iter060_p2.py`）。
- ✅ **#11 writer-style 唯一样本**（`routes.py` + `jobs.py` handler）：样本固定落 `.writer_style_sample.tmp` 且写在 `start_job` 抢锁前 → 两并发 extract 互相覆盖样本。路由改每请求唯一 uuid 路径 + `write_text_atomic` + `sample_path` 入 job params；handler 优先读 params 路径（回落固定名）并提取后删；job 起不来时清理暂存样本（防临时文件泄漏）。+3 单测（`tests/test_web_writer_style.py`）。
- ✅ **#14 drama 写端点原子化+reservation**（`api_drama_plan`/`api_drama_setup_save`，`routes.py`）：裸 `write_text`（非原子）+无 reservation，setup_save 读-改-写有竞争窗口可被并发 `/drama/plan` 冲掉。两端点写块包 `workspace_reserved` + 改 `write_json`（原子，同 `ensure_ascii=False`/`indent=2`），setup_save 整个 R-M-W 进 reservation；`workspace_busy`→409。+2 单测（`tests/test_web_routes_post.py`）。
- ✅ **#12 debate 协作式取消 checkpoint（方案A）**（`debater.run_debate` + `_step_debate`）：debate 是唯一无取消粒度的 step（`_step_debate` 没传 `progress_cb`、`run_debate` 无该参数）→ 整个 debate（N agents×M rounds+投票，~52s/call）期间 `_check_cancelled` 一次不跑，取消只在 step 结束后生效。`run_debate` 加可选 `progress_cb`，在每 agent LLM 调用前（**try 之外**，否则 `JobCancelled` 被 `except Exception` 吞）+ build_decisions/每选票/build_outline 前插检查点；`_step_debate` 传入。writer 章内 rewrite loop、book_runner 章间 chapter loop **已有 progress 检查点，无需改**。**不碰 `llm_client`/stream**——方案B（流式中断+debate 开 stream）显式推迟 iter061（触「真模型须超时重试驱动」红线）。+2 单测（`tests/test_iter060_p2.py`）。

**关键发现/定性沉淀（勿 re-derive）**：
1. **Codex「泄露文案」核验校正**：C/D/E 原报告称坏 JSON 会"泄露 `JSONDecodeError` 文案给用户"——**逐行核验不成立**：`server.py:60-73` 对任何未捕获异常统一返 `{"error":"internal server error"}`，原始异常串只进 stderr。真实后果是 `read_json` 抛错被兜底成 **HTTP 500 击穿读面**。修复理由据实更正为"500 击穿"而非"泄露文案"。
2. **#11 唯一路径需在 job 起不来时清理**：改 per-request uuid 样本路径后，若 `start_job` 抢锁失败（并发败者），暂存样本不会被 job handler 消费删除 → **临时文件泄漏**。路由层在 job 起不来分支显式清理暂存样本。
3. **#14 复用既有 `write_json` 而非新造原子写**：项目早有原子 `write_json`（写 tmp + rename，`ensure_ascii=False`/`indent=2`），drama 两端点直接换用即得原子性；setup_save 的整个读-改-写包进 reservation 才闭死并发 `/drama/plan` 冲掉的竞争窗口。
4. **writer/book_runner 已有取消粒度、#12 只需补 debate**：审计 #12 笼统说"长步骤无取消检查点"，但逐步核验——writer 章内（rewrite loop）、book_runner 章间（chapter loop）已有 `progress`/`_check_cancelled` 检查点；**唯一缺口是 debate**。故本轮只给 debate 补，scope 精准。
5. **Codex-B 双层防御**：参数层早拒（`_validated_run_params` 对所有 step 校验）本可独立修复，但 `_timeout_deadline` 再加 `math.isfinite` 兜底——任何未来漏网的非有限 timeout 不再产 nan deadline 致永不超时。
6. **Codex-F 收口 iter059 R6 的主动 scope 外残余**：iter059 R6 曾把 book_runner 5 处裸 `read_json`（728/741/790/791/858）划出 P1 scope 避免 creep；本轮 Codex 复审确认 790/791 击穿 resume、858 顶替善后快照属真 bug，一并收口。

**门禁**：全量 `.venv/bin/python -m unittest discover -s tests` **1180 passed / 0 failed**（1158 基线 +22；Codex-A 2 + Codex-B 3 + Codex-C/D/E 5 + Codex-F 3 + #7 2 + #11 3 + #14 2 + #12 2）。零既有 schema 改动，默认路径 byte-identical。**只 commit 不 push（push 待用户）**；本轮 8 个 fix commit + 1 docs commit。

**数据状态**：纯代码 + 测试 + 文档改动，未触碰任何 workspace / 真实数据 / .env。

**下轮候选**：① **#12 方案B（iter061）**——流式中断 + debate 开 `stream`（碰 `llm_client`/stream 配置），需真模型验证流式中断不破坏 SSE read 超时（触「真模型须超时重试驱动」红线，须谨慎驱动）；② #4/#1 真模型复跑坐实端到端（`chapter_plan_invalid` / `budget_exceeded`，前几轮 mock 确定性为准）；③ 审计 16 条已全部清零 open，后续为真模型验证与产品打磨，非 bugfix。

## iter061：#11 路径穿越 P0 热修 + iter060/061 代码审查发现登记（2026-06-23）

> 注：iter061 是一次 **P0 热修**（commit `bce579c`），**未走完整四处登记**——无 `iteration_061_PLAN.md`、不在 `iterations/README.md` / 根 README 状态表；本段是其唯一接力记录，下轮（iter062）若收尾可补全。`bce579c` 同时捎带：`AGENTS.md` 铁律⑨ 升级为内置 `/code-review`+`/security-review` skill、`docs/CLAUDE_CODE_WORKFLOW_OPTIMIZATION_2026-06.md` 调研报告。

**iter061 已落地（`bce579c`）**：iter060 #11 让路由把样本**绝对路径**塞进 `job params.sample_path`，handler 裸 `Path()` 信任并 `read_text`+`unlink`（`jobs.py`）；`/run` 又允许任意 params → 攻击者 `POST {step:extract-style, params:{sample_path:/任意路径}}` 即可让该 step **读取并删除 workspace 外任意文件**（实测外部文件被删、`writer_style.json` 被生成）。**修复**：路由只传随机 token（`uuid4().hex`），handler `re.fullmatch(r"[0-9a-f]{32}", token)` 校验后在 `data_dir` 内 `with_name` 重建路径——路径**永不取自调用方输入**，穿越不可能；非法/缺失 token 回落固定路径（仍在 `data_dir` 内）。+4 测试（含端到端 `/run` 恶意 `sample_path`/token → 外部文件存活）+ 既有 #11 测试改 token 契约。

**iter060+iter061 代码审查（`/code-review high`，3 finder 交叉验证 + 主 agent 复核 `b6a9938..bce579c`）发现 → iter062 待修**：P0 路径穿越已由 iter061 修复（上）；以下为 iter061 **未覆盖**的真实问题。

- **① 孤儿版权样本——取消即泄漏（中，finder×2 确认）**：`_step_extract_style`（`jobs.py`）——#11 改唯一 token 路径后，样本只在 handler `try/finally` 删；但 `progress_cb("extract",0.1)` 在该 `try` **之前**、取消会抛 `JobCancelled`，或 job 排队期被取消（handler 根本没跑）→ 样本永不删。**旧固定路径会被下次上传覆盖（至多 1 个孤儿），唯一路径方案让孤儿无限累积**，全仓无清扫 → 违反"样本不持久化（P0-A 版权护栏）"。**修法**：上传前在 `use_workspace` 内 glob 清扫 stale `.writer_style_sample.*.tmp`（workspace 锁保证至多一个 in-flight）+ handler 把 read 之后全程（含 `progress_cb`）包进 try/finally。
- **② write-book/plan-chapters 的 timeout 校验后被丢弃（中，finder×2 确认）**：`_validated_run_params`（`routes.py`）对所有 step 校验 `timeout_minutes`，但 write-book/plan-chapters 返回的 `out` dict **不含 `timeout_minutes`**（被 `_validate_write_book_params`/`_validate_plan_chapters_params` 重建时丢）→ `_timeout_deadline` 拿不到、超时永不 arm。**最该有超时的两个最长 step 反而静默无超时**，注释"applies to every step"误导（仅 plain step 走 `return None, params` 透传 + wizard 路径真生效）。**修法**：把合法 `timeout_minutes` 带进这两个 `out`。
- **③ `/run` 的 timeout 校验无 maximum（低，与②同源）**：顶层 `_float_param(..., minimum=0.0)` 无 `maximum`，而 wizard 两处都 `maximum=1440.0`（24h）。超大有限 timeout（如 `1e9`）= 永不触发的假死线——Codex-B 想堵那类的另一入口（从 NaN 换成超大有限值，双层都不拦）。**修法**：加 `maximum=1440.0` 对齐 wizard。
- **④ 坏 meta 被覆盖（低）**：`_sync_meta_with_external_review`（`book_runner.py` 790/813）——corrupt `meta.json` 降级 `{}` 后，若 `review.json` 有非空 verdict 则 `write_json(meta_path, meta)` 用最小 meta 覆盖，丢 writer-owned 历史（旧 `read_json` 抛错中止 sync 反而保留文件——但那是 Codex-F 要修的击穿 bug）。数据本已不可读，危害有限。**修法**：meta 降级 {} 时跳过写回、保留现场。
- **⑤ readiness clamp 静默截断 vs write-book 超限 400（低，一致性）**：同一非法大值，readiness 静默 clamp 到 2000、write-book 直接 400 拒绝；readiness 响应不告知被 clamp。**可选**：readiness 超限加 warning 字段或与 write-book 一致返错。
- **⑥ iter061 token 非法→回落固定路径（低，后门）**：绕过 route 的 caller（旧客户端/直接 `start_job` 不传 token）会回落固定 `.writer_style_sample.tmp`，重开 #11 clobber 窗口。注意 iter061 自身回归测试依赖该 fallback 在样本缺失时返 `blocked`，删除需同步改测试。
- **⑦ drama/plan reservation 窗口比注释窄（低）**：reservation 只包 `write_json`，`drama_planner.run`（含 prompt-log append）在锁外；注释"hold the reservation across the write"略夸大。低危（log append-only、result 源自只读输入），登记备查。

**审查确认干净（无需动）**：debate 检查点位置/fraction/取消传播（均在 `except Exception` 外、单调、干净传到 `_worker` 的 `except JobCancelled`）、readiness `int()`（恒喂 int）、drama/起点 reservation 的 `except RuntimeError`→`raise` 只吞 `workspace_busy`/`not_found`、`write_json`/`write_text_atomic` 的 `ensure_dir`、token 正则 + `with_name` 重建的穿越安全性、`read_json`→`read_json_optional` 下游 isinstance 守卫、PUT 坏 graph 在 `write_json` 前 404。

**iter062 建议范围**：**①②③ 同一类资源/泄漏先收**（一条 iter062、三 commit + 测试，仍只 commit 不 push）；④–⑦ 低优先随手或登记备查；**iter061 四处登记补全**（`iteration_061_PLAN.md` / 两处 README）可一并在 iter062 收尾。

## iter062：前端 UX 重构（报错收口 + 导航补全 + 假按钮上锁，2026-06-23 收官）

> **scope 注**：iter062 **未**做上面「iter062 建议范围」的后端 ①②③——用户接力指令改为「基于 iter043 重新设计前端」（三类痛点：假按钮/反人类导航/裸代码报错）。故 iter062=**前端 UX 重构**；后端 ①-⑦ + iter061 四处登记补全**顺延 iter063**。本轮只 commit 不 push（待用户验收）。

**已落地（Web，`src/web/`，纯 stdlib，零新依赖）**：
- **报错友好化（两端）**：新增 `src/web/errors.py` 错误目录——`code_for_exception`（子类序：JSONDecodeError/UnicodeDecodeError 在 ValueError 前、FileNotFoundError/PermissionError 在 OSError 前）/`build_card`/`card_for_exception`（`technical` 默认不下发，只进 stderr）/`readiness_kind`+`readiness_card`（文案与 `book_runner._primary_blocker.labels` 逐字对齐）/`error_body`（保留 `error` 字段向后兼容 + 加 `card`）。后端 ~15 处裸 `str(exc)`/`f"...{exc}"` 收口（含审查补的 outline/draft/kb/entity_graph×2/setup/settings.env 6 处 500 OSError）；degrade 路径（overview/drama/plan）`error`→card dict、blocker 收敛稳定 code、原异常写 `_log_degraded` stderr；顶层 dispatch 500 保留 `error=="internal server error"` + 加带 trace_id card。前端统一 `renderErrorCard`/`_normalizeErrorCard` 替换 ~23 处裸 `escapeHtml(err.message)`；`_fetchWrapped` 分类 网络/超时(AbortController 30s，轮询 URL `POLL_URL_RE` 豁免)/坏 JSON；全局 `window.onerror`+`unhandledrejection` toast。JS_WIZARD/JS_SETTINGS 各自独立 IIFE：wizard 补自洽精简 `renderErrorCard`，settings 改自洽友好文案。
- **导航**：`_BASE_TPL` topbar 常驻 ⌂ home→`/library`（CSS `.topbar .breadcrumb{margin-right:auto}` 把 actions 推右、home+面包屑左聚）；工作台 `renderStepbar` 可点回看步骤条（has_kb/has_outline/has_plan/stage → done/current/locked，done/current 锚 `#stage-*-card` + `scroll-behavior:smooth`，locked aria-disabled 不可点）+ stage pill 旁单一「下一步」CTA；章节详情加「回概览」。
- **假按钮**：drama ③④ tab `disabled aria-disabled`+🔒+`badge-soon`「即将上线」，`bindHashTabs` click 早退 disabled + 从 `_ALLOWED_TAB_KEYS` 移除 storyboard/characters（防 `#storyboard` deep-link 强切）。readiness 诊断区/书架卡/overview 阻断项经 `readinessReasonText` 翻人话（原始 code 折叠在括号）；禁用「开始续写」加 title 说明（`submit.disabled = writeBookJobRunning || data.status === 'blocked'` 逐字保留——iter026 锁）。
- **CSS**（复用现有 token，无新 hex）：`.error-card*` / `.stepbar`+`.step.*` / `.tab.locked` / `.home-btn` / `.badge-soon`。

**审查（铁律⑨，web 高风险 → 2 视角 subagent 并行 + /security-review；ultra 需用户授权未跑）发现并全修**：P0 wizard cancel 误用 dashboard-only `_httpError`（本轮引入，→ 自洽 carrying error）；P1 `bindCtaActions()` 仅 continue 调用致它页错误卡 CTA 死按钮（→ 提 `boot()` 无条件调用）；P2 errors.py `readiness_kind` 死代码删除、6 处残余 500 OSError 同类收口、overview hint/blockers 人话化 + `<h2>` 补 escapeHtml（闭 pre-existing latent XSS sink）。**/security-review 无 ≥MEDIUM 漏洞**，本轮净改进安全姿态。

**门禁**：`OPENAI_MODEL=mock unittest discover -s tests` **1201 tests OK**；web 子集 225 OK；verify.sh exit 0；preflight 无 FATAL；node --check 三 bundle 通过；iter026 锁 6 标识符/表达式全保留。新增 `tests/test_web_errors.py`(14) + `test_web_routes_get.py` +5 测试；更新 tab whitelist / loadTabPanel / overview 坏 plan / `_httpError` 计数断言。preview 实景验证 home/步骤条/上锁tab/readiness人话/错误卡均如设计（建临时 demo workspace 后已清理）。

**数据状态**：纯代码 + 测试 + 文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`。

**下轮候选（iter063）**：后端代码审查 ①-⑦（① 孤儿版权样本取消即泄漏=中危版权护栏，优先）；iter061 四处登记补全（`iteration_061_PLAN.md` + 索引/状态表）；移动端 drawer/导航响应式；drama 站③④ 实做；后端三份 readiness 目录合并。

## iter063：codex iter062 复审 bug 收口 + 后端审查①-⑦ + readiness 目录合并 + 移动端审计 + iter061 登记（2026-06-23，收官）

> **scope**：iter062 前端重构后，codex 用 3 视角 subagent + Playwright 真浏览器复审发现 7 个回归/遗漏（2×P1/4×P2/1×P3）；本轮全修 + 收掉 iter062 顺延的后端代码审查 ①-⑦ + 三份 readiness 目录合并 + 移动端导航审计 + iter061 四处登记补全。用户明确范围：codex 7 bug + 后端①-⑦全收 + iter061 登记 + 移动端 drawer 响应式 + 三份目录合并；**drama 站③④实做 / KB 起点过滤升级不在本轮**。只 commit 不 push。

**codex 复审 7 bug（全修）**：
- **A1**（P1）plan-chapters 裸露 `ValueError: stale debate outline`（052 跨时间线护栏的刻意硬阻断，**不能**自动 `--allow-stale-outline` 放行）→ `jobs._step_plan_chapters` 捕获 `"stale debate outline" in msg` 转 `blocked(outline_stale)`；前端 `pollJob` 终态非 succeeded 改渲新 `renderJobFailureCard` 友好卡（**顺带收口所有 blocked/failed job 的裸 `reason · error` 行**，不止 stale outline）。
- **A2**（P1）剩余裸 `str(exc)`（drama plan/hooks FNF+ValueError、start_job、draft-meta）→ 加 `card`（沿 iter062 4xx/FNF 约定保 `error=str(exc)`，substring 测试不破；draft-meta 改 card + 原 exc 进 stderr）；前端新增 `errTitle(err)`（优先 `payload.card.title`）替换 17 处错误 toast，草稿保存走 `#draft-edit-status` 卡。
- **A3**（P2）wizard 上传错误卡英文技术化 → `_UploadRejected` 加 `code`，errors 目录加 `upload_no_chapters`/`upload_not_utf8`/`invalid_workspace_name`（仅 `start_upload` 路径；premise/drama-start 仍英文串，留 backlog）。
- **A4**（P2）workspace `pattern` 在 Chromium `v`-flag 把字符类内**裸 `-`** 当 SyntaxError → 转义 `\-`（CJK 范围 `一-鿿` 本身合法不变，3 处输入框）。preview 实测控制台零 regex error。
- **A5**（P2，=后端审查②）write-book/plan-chapters `timeout_minutes` 校验后被 rebuild params 丢弃 → 两 validator 携带正值；顶层 `_validated_run_params` 加 `maximum=1440`（③）。
- **A6**（P2）章节页「点击任意一行」误导 → 「续写行可点击查看详情（原文行仅供参照）」。
- **A7**（P3）`/chapter/N#edit` 深链不进编辑 tab → `_ALLOWED_TAB_KEYS` 补 `edit`。

**后端代码审查 ①-⑦（②已并入 A5，其余全收）**：
- **①** 孤儿版权样本取消即泄漏（中危 P0-A 护栏）→ handler 把 read→progress_cb→extract 全程包 try/finally（running-cancel 也 unlink）+ 上传前 glob 清扫 stale `.writer_style_sample.*.tmp`（持 reservation，sweep all-but-mine 无竞态）+ **审查补漏**：`_worker` finally 增 `_cleanup_extract_sample` 按 token 删本 job 样本，覆盖 **queued-cancel**（handler 未跑）。
- **③** `/run` timeout 无上限 → `maximum=1440`（与 wizard 对齐）。
- **④** 坏 meta 降级 `{}` 时跳过写回，不用 verdict-only stub 覆盖 writer 历史。
- **⑤** readiness clamp 静默 → 加 `clamped:{key:{requested,applied}}` 字段（只读探针仍非 400，显式告知）。
- **⑥** iter061 无效 token 回落固定路径后门 → 无合法 32-hex token 直接 `blocked`，删除 fallback（既有测试本就期望 blocked，契约不破）。
- **⑦** drama/plan reservation 窗口偏窄 → 把 `drama_planner.run`（含 prompt-log append）一并纳入 `workspace_reserved`，与注释相符。

**Part C 三份 readiness 目录合并**：新建核心层 `src/readiness_catalog.py`（仅 `typing`，`KINDS`+`classify`+`fields_for`，避免 `book_runner`→`web` 反向依赖）；`book_runner._primary_blocker`/`_blocker_kind` 与 `errors._READINESS`/`readiness_kind` 全部派生自它；前端 `_BASE_TPL` 注入 `window.READINESS_CATALOG`（`json.dumps(...).replace("<","\\u003c")` 防 `</script>` 突破），`CTA_ACTIONS` 改 IIFE 从注入目录构建（`plan_fingerprint_stale` 是 jobActionKind 合成的前端专属 kind，本地保留）。漂移由新增测试守（注入 JSON==KINDS、errors/book_runner 派生一致）。

**Part D 移动端审计（结论：已适配，无需新增 @media）**：iter044 已建抽屉（`.sidebar.open`+overlay+`nav-toggle`+`@media 768px`），iter062 新元素（topbar ⌂/breadcrumb 省略号、stepbar `flex-wrap`、单一 CTA、`.error-card` 列布局、novel/drama `.tab-list overflow-x:auto`+状态 pill）在 375px preview 实测全部正常、页面零横向溢出（drama 锁 tab 经横滚可达）。诚实记录：本轮 Part D 是**验证确认**而非新增 CSS（无破即不改，铁律⑦）。

**Part E iter061 登记补全**：新建 `docs/iterations/iteration_061_PLAN.md`（8 段，记 `bce579c` #11 路径穿越热修）+ `iterations/README.md` 索引补 iter061/063 + 本表（README SOP 阶段 16 + 时间戳）。

**审查（铁律⑨）**：`/code-review high`（3 finder 角度）3 发现**全部处理**——F2-1/F2-2（本轮引入的 `renderJobFailureCard`/toast 对非目录 reason 回落 `retry_exhausted` 掩盖真实错误明细）→ 重构保留真实 error line + toast 对齐；F3-1（① queued-cancel 残留窗口）→ dispatch finally per-token 清扫；F2-3（注入未转义 `<`）→ 已加。`/security-review` **无 ≥MEDIUM（本轮）**。**未修风险**：F3-2 drama FNF `error` 含绝对路径（iter062 既有、127.0.0.1 单用户、`technical` 不下发、低危，留 backlog）；F3-3 timeout 校验 3 处重复（debt）；F3-4 `clamped` 未命名空间隔离（低）；F3-5 `_blocker_kind` 薄别名（iter064 可删）。

**门禁**：`OPENAI_MODEL=mock unittest discover -s tests` **1214 tests OK**（基线 1201 +13）；`verify.sh` exit 0；`preflight` 无 FATAL；`node --check` 三 bundle 通过；iter026 锁 6 串全保留。preview 实景验证 A1 卡/A3 中文卡/A4 零 regex/A6 文案/A7 深链/⑤ clamped/移动端均如设计（临时 demo workspace 已清理）。**已知 pre-existing flaky**：`test_web_draft_edit.test_busy_workspace_returns_409` 满量 discover 高负载下偶发 `workspace_busy`（`_drive_to_written_chapter` 后台 job 释放 reservation 的时序），单独跑稳定通过、与本轮无关，登记备查。

**数据状态**：纯代码 + 测试 + 文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`（临时 demo workspace 验证后已删）。

**下轮候选（iter064）**：premise/drama-start 名校验一致化为 card（同 A3）；drama FNF error 路径脱敏（F3-2）；timeout 校验抽 helper（F3-3）；`_blocker_kind` 别名清理（F3-5）；drama 站③④实做；KB 起点过滤升级为主动 blocker；真模型 capstone 复跑。

---

## iter 064（2026-06-23，收官）——Codex findings 收口：CLI/Web 健壮性对齐 + 硬化

**来源**：codex 一轮只读调研提 2×P1 + 4×P2。起轮用 6 个只读 agent 逐条核验代码，**6 条全部 confirmed**。第 6 条「语义闭环」large 级，与用户确认推迟 iter065+。前 5 条有界硬化主题 = **操作者侧 CLI↔Web 健壮性对齐**（同一业务 Web 有守门/友好出口、CLI/driver 没有）。

**#1（P1）CLI/driver 数值守门统一**：新建核心层 `src/run_params.py`（仅 `math`/`typing`，镜像 `readiness_catalog` 无 web 反依赖）——`INT_CAPS`/`FLOAT_CAPS` cap 表 + `validate_int`/`validate_float`/`validate_run_params`。Web 改薄包装复用：`routes._int_value`/`_float_param` 转调（保留原名签名，回归门 `test_int/float_finite_guard.py` 不动即绿）、`_validate_write_book_params` cap 改读 `INT_CAPS`、`wizard._optional_float` 转调（`allow_blank=True`）；`routes`/`wizard` 移除空出的 `import math`。`jobs._float_param` 防御纵深层契约不同**保持不动**（scope 收敛）。CLI：`main.py` 加 `_validate_cli_run_params`，write-book/write-readiness/write/plan-chapters 四 arm 顶部**硬拒绝 `SystemExit(2)`**（plan-chapters 的 `args.chapters` 按 `target_chapters`1..200 校验）。driver：`book_driver._build_params` build 前校验——驱动器虽 subprocess 重调 CLI，但 `plan_segments(chapters,...)` 在驱动器进程内分段，huge chapters spawn 前就 OOM，故 driver 自身必须守门。runner：`book_runner` 加 `math.isfinite` budget 末线（非 finite→0.0「无上限」，程序化调用方防御）。**坐实**：`write-book --chapters 999999999`→exit 2 不再 OOM；`--budget-cny nan`→exit 2。

**#2（P1）plan-chapters stale-outline 出口统一**：`plot_planner` 定义 `OutlineStale(ValueError)`（带 `codes`/`kind`，message 字节级不变 → `test_iter053a` 的 `assertRaises(ValueError)` 全绿）。`jobs.py` 改 `isinstance(exc, OutlineStale) or "stale debate outline" in msg`（**踩坑**：`test_web_jobs_dispatch` 故意注入裸 ValueError 模拟，纯 isinstance 漏 → 保留字符串兜底防御纵深，typed 路径用 `exc.kind`）。`main.py` plan-chapters 加 `except OutlineStale` 复用 `readiness_catalog.KINDS["outline_stale"]` 友好文案 + `SystemExit(4)`（不再裸 traceback）。

**#3（P2）移动端 `.topbar-actions` CSS 作用域**：grep 确认 `.topbar-actions-wrap` 仅壳层下拉（templates:72 包 74；内容用法 341/892 在 wrap 外；JS closeTopbarMenu 也只认 wrap）。`static.py` 三个移动选择器加 `.topbar-actions-wrap ` 前缀，内容按钮（概览删除作品 / 章节详情返回链接）移动端落回桌面 flex（static:290）→ 可见。纯 CSS，无需改 JS。

**#4（P2）错误卡路径脱敏**：`errors._redact_paths`（正则 `/(?:[^/]+/){1,}[^/]+`，前导 `/`+≥2 段；prose `3/4`/`a/b`/`TCP/IP` 无第二斜杠不误伤）在 `card_for_exception` 对 `detail` 脱敏（`technical` 保留原始供 stderr）。**收官审查补漏**：codex 只点 `card.cause`，但 routes.py **12 处** handler 返回 `{"error": str(exc), "card": ...}`——裸 `error` 键仍泄漏路径（**= 既有 F3-2 drama FNF**）→ 新增 `errors.exception_body(exc)`（两字段都脱敏）替换全部 12 处，彻底堵死。**P1（审查发现）**：正则原用 `[^/\s]` 排空格，父目录含空格的路径会从空格截断泄漏后续树 → 改 `[^/]`（含空格，过度脱敏 fail-safe）。**方案选择**：不改 `hook_designer.py` 源头（中央脱敏完整 + 保 stderr 全路径调试）；wizard 3 处 `{"error": str(exc)}` 是受控 `_UploadRejected` 用户文案无路径，不在范围。

**#5（P2）workspace HTML pattern 单源**：`_naming.py` 暴露 `WORKSPACE_NAME_HTML_PATTERN`（转义 `\-` 满足 Chromium `v` flag；非捕获可选组禁尾部连字符）。`templates.py` **3 处** workspace 名输入（不止 codex 点的 1 处）统一 f-string 引用，前后端 `foo-` 一致拒绝。

**#6 文档**：`docs/AELOON_INTEGRATION.md` §11.4 登记 vendored baseline=iter062、iter063/064 待下次同步（该文件含用户并行 PR #541 在途改动，**不并入 iter064 代码提交**，留用户 Aeloon 提交）。

**审查（铁律⑨）**：3 维度 workflow（correctness/security/reuse）+ 对抗验证。**correctness 零发现；reuse/simplify 两条均 is_real=false**（确认导入全用上、无死代码、`math.isfinite` 仍在 `book_runner` 用、`_validate_cli_run_params` vs `_build_params` 不同入参形态不应合并）；**security 1×P1 已修**（空格路径脱敏不全）+ 自查发现并修 12 处裸 `error` 键泄漏。**未修风险**：F3-3 timeout 校验 3 处重复 debt（顺延）；`_blocker_kind` 别名（F3-5，顺延）。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**，裸 python3 缺 pydantic 报 169 import error）`unittest discover -s tests` **1250 tests OK**（基线 1214 +36）；`verify.sh` exit 0；`preflight` 无 FATAL。

**数据状态**：纯代码 + 测试 + 文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter065）**：**语义闭环（large，本轮推迟）**——(a) 计划履约 reviewer（`chapter_plan_item` 穿进 `review_text` 或后置 beat-matcher）/ (b) outline drift 行为闭环（`writer.py:713` 旧 outline 长期注入，drift 命中率低时重生成/动态注入）/ (c) entity_advance 允许新建关系（现 `relationship_not_found` 跳过）；F3-3 timeout helper；`_blocker_kind` 别名清理；drama 站③④；KB 起点过滤主动 blocker；真模型 capstone 复跑。

---

## iter 065（2026-06-24，收官）——语义闭环 a/c：计划履约 reviewer + entity 新建关系

**来源**：iter064 收口 codex #1–#5 后，唯一剩 P2 #6「续写长程语义闭环」（large，iter064 与用户确认推迟）。#6 三子项：(a) 计划履约 reviewer、(b) outline-drift 行为闭环、(c) entity 新建关系。**与用户确认本轮只做 (a)+(c)**（都是确定性/纯增量、默认字节级不变、mock 全可测、不引入新 serialized block 契约）；**(b) 推迟 iter066**——它是三者中唯一把「原本能跑的长程 run」变成「中途拒绝」的改动（warn→block 在 `rolling_summary` 落后 drafts 时会误判 severe drift），需配 driver/Web 级联专项审查。

**(a) 计划履约 reviewer（确定性、非阻断建议级）**：`src/reviewer.py` 新增 `_plan_compliance_misses(draft, chapter_plan_item)`——取每个 `key_events` 的中文字符 bigram 集合，命中率 < `COVER_THRESHOLD`(0.15) 判「正文中几乎找不到」。`review_text()` 末位加 `chapter_plan_item=None`，`writer.py:266` 传入；None/无 key_events/key_events 非 list → 返回 `[]` 自跳过（铁律④ 字节级不变）。缺失 beat 作 `{section,type,guidance,_advisor:"plan_compliance"}` 进既有 `rewrite_suggestions` 通道（`_review_feedback` 的「改写顾问建议」段渲染，与 verdict 无关；写进 review.json），**仅当本就要重写时喂回写手、永不翻转 verdict / 不 block**。

**与计划的关键偏差（收官审查 P2 驱动，诚实记录）**：计划原写「漏多数 beat 才硬 block（synthetic Reject）」。收官 3 维度 workflow 对抗审查对**真实 `longzu/chapter_plan.json`** 实测证明：计划 beat 是 40–70 字名词密集句，「忠实但戏剧化」换句后 bigram 命中率掉到 0.1–0.4，硬 block 会**误拒忠实好稿、烧光 rewrite 预算**——正是把 (b) warn→block 推迟想避免的同一类误报。故 (a) 落地为**建议级非阻断**（同 (b) 的安全哲学一致；若 (a) 硬 block 上线就与推迟 (b) 自相矛盾）。

**(c) entity 新建关系（confidence-gated CREATE，默认关闭）**：`apply_advance_proposals`/`_apply_selected`（`entity_advance.py`）加 `allow_creation=False`/`creation_confidence=0.85`。`rel is None` 分支在 `allow_creation` 时按三闸创建新关系：**非空 new_state**（修审查 P2：explicit-index 路径绕过 `_is_applyable_proposal`，空 state 会建垃圾边）+ **非 hard-conflict**（复用 canonical `relationship_auditor._hard_conflict_markers`）+ **conf≥creation_confidence**；任一不满足带具体 reason 跳过（`creation_empty_state`/`creation_hard_conflict`/`creation_below_confidence`）。`created` 经可选 mutable 出参收集（保 `_apply_selected` 2-tuple 返回 → 既有测试字节级不变）；result 加 `created_count`/`created`，`applied_count` 减去 created（= 纯 advance 数）。`anchor_chapter` 严格沿用 `f"续写第{chapter_no:02d}章"`。上游 `book_runner._auto_apply_advances` 从 `config/agents.yaml` 的 `entity_advance` 段读配置透传（读取/float 全包 try → 坏配置 fail-closed 回默认）。`cli_apply_advance.render_apply_advance_result` 加 created 显示（前瞻补全；CLI 暂未暴露开关）。

**审查（铁律⑨，高风险=runner + 持久化数据文件改写）**：3 维度（correctness/security-data/reuse-ironlaw）workflow + 对抗逐条核验，**11 raw findings / 9 confirmed**；拆多 agent 独立视角对抗审（未跑 ultra，需用户授权计费）。处置：**2×P2 已修**（plan-compliance 硬 block→建议级；allow_creation 空 new_state 垃圾边→强制非空）；**reuse 已修**（`_hard_conflict_markers` 从派生副本 `proposal_validator` 改从 canonical `relationship_auditor` 导入，杜绝双副本漂移）；**P3 已修**（key_events 为字符串时逐字符误判 → isinstance 守门）；**nit 已修**（render 显示 created）。**未修（诚实登记）**：confidence Infinity/NaN 写入 entity_graph.json 是 **iter065 前既有**风险（legacy advance 路径同存，非本轮引入；select_auto_indexes 已用 `>=` 过滤 NaN）按铁律⑦顺延；plan-compliance bigram 是**粗略词法信号非语义履约判定**（局限在案，建议级已无 block 风险）。铁律①自查：diff 无 `sk-`/`.env`/key 读写；仅 `src/`/`config`/`tests`/`docs` 改动。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1269 tests OK**（基线 1250 +19）；`verify.sh` exit 0（**须 `PATH=$PWD/.venv/bin:$PATH`**，否则裸 python3 缺 pydantic 173 import error 误判 exit 1）；`preflight` 无 FATAL/WARN。

**数据状态**：纯代码 + 测试 + 文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter066）**：**(b) outline-drift warn→block**（本轮推迟的 #6 第三子项）——新 `outline_drift_severe` readiness kind + driver/Web 级联，配专项审查（注意 `rolling_summary` 落后 drafts 的误报风险，0.2 阈值 + MIN_ANCHORS 缓解）；plan-compliance 升级实体锚定/LLM 语义履约（仅当建议级实跑证明不够用时）；confidence 非有限值在 entity_graph 写入的统一 clamp（含 legacy advance，跨 iter）；F3-3 timeout helper；`_blocker_kind` 别名清理；drama 站③④；KB 起点过滤主动 blocker；真模型 capstone 复跑。

## iter 066（2026-06-24，收官）——codex iter065 复审 findings 收口（上）：fail-closed 数值/类型守门

**来源**：codex 对 iter064/065 做只读复审，提 8 findings（3×P1/4×P2/1×P3）。3 个 Explore subagent 逐条追数据流 + 主代码核读**全部属实**（6 完全/2 部分）。共因=输入边界没 fail-closed：`bool()`/`float()` 裸转配置与 proposal 字段，NaN/inf/空白/坏类型在 IEEE-754 下静默穿透阈值门。与用户确认**分 2 轮**：本轮 5 条 fail-closed 数值/类型守门（含全部 3×P1），iter067 收 #6/#7/#8（语义信号+Web 脱敏）。用户定 3 决策：#5 cap 解耦（CLI→2000/WebUI 留 200）、#4 扩到 legacy advance、#2 两端都须在 entities；并对 plan 给 6 条精炼（已并入）。

**#4（P2，confidence 非有限值）**：`entity_advance.py` 新增 `coerce_finite_confidence(value, default=0.0)`（`math.isfinite` 失败→默认）**仅用于写 timeline**——创建分支、legacy advance 写入、`timeline_not_a_list` 日志参数三处。`select_auto_indexes` **不用** coerce 而加 `if not math.isfinite(conf): continue`：`float("inf")` 解析成功后 `inf>=min_confidence` 恒 True 会被选中（nan 已被 `>=` 挡，inf 是漏网点）；coerce→0.0 会让 `--min-confidence 0` 复选坏值（契约倒退）。消掉 iter065 登记的「confidence 非有限值写入既有风险、legacy 同存、顺延」。

**#2（P1，src/dst 校验）**：`_apply_selected` src_id/dst_id 加 `.strip()`（`"  "` 落入 `missing src_id` raise）；创建分支新增 `creation_unknown_entity` 档——`entity_ids = {str(e.get("id")) for e in updated.get("entities",[]) ...}`（复用 `entities.py:101` 模式，循环外建一次），src/dst 任一不在则拒绝创建。reason 优先级在 empty_state/hard_conflict 后、below_confidence 前。新校验只在 `if allow_creation:` 内，allow_creation=False 时 iter052 稀疏边 `relationship_not_found` 路径字节级不变。

**#1（P1，配置 fail-closed）**：`book_runner.py` 加 `from . import run_params`；`allow_creation = ea_cfg.get("allow_creation") is True`（`bool("false")` 为 True 的坑——带引号 YAML 反开创建）；`creation_confidence` 用 `validate_float(..., minimum=0.0, maximum=1.0)` 清洗值，err 回 0.85。整块仍在既有 try/except 内。

**#3（P1，resume 守门）**：`book_driver.cmd_resume` 把 budget_cny/step_timeout_minutes 校验**前置到动 `state["params"]` 之前**（原 pause/force_debate 写入之前），任一 err→`print(err,file=sys.stderr); return 2`，此时 state 完全未触碰；通过后写 validate 的**清洗值**。budget_cny 走 `validate_float(minimum=0.0)`、step_timeout_minutes 走 `validate_int(minimum=0,maximum=1440)`。根因：resume 绕过 `_build_params` 的 `validate_run_params`，`--budget-cny nan` 让 `spent>=nan` 恒 False 成本闸失效。

**#5（P2，cap 解耦）**：`run_params.INT_CAPS["target_chapters"]` 200→2000（与 chapters/plan_target 对齐）。修长程 driver：默认 `plan_target=chapters+resume_from-1` 可达 249，driver 调 `plan-chapters --chapters <plan_target>` 撞旧 200 上限→`blocked` self-block。WebUI 单次上限由 `routes._validate_plan_chapters_params` **内联 200、不读 INT_CAPS** 自动保持（解耦零 blast radius）；`main.py:553` 注释更新。

**审查（铁律⑨，runner 高风险）**：拆 2 个独立视角只读 Explore subagent 并行审（未跑 ultra）。**正确性+契约**：五条实现正确完整、无 bug、无契约破坏（确认 allow_creation=False 稀疏边字节对齐）、测试覆盖三路径+state 不半改不变式 → 可提交。**安全+复用**：无 `sk-`/`.env`/密钥；日志与 JSON 经 coerce 硬化（不再写 NaN/Infinity 字面量）；`cmd_resume` 的 `print(err)` 来自 run_params 只含参数名+约束不回显原值；`coerce_finite_confidence` 与 `validate_float` 的 isfinite「重复」语义正当（透明清理 vs 守门）→ 安全可提交。**未修（诚实登记）**：cmd_resume 校验与 `_build_params` 可在未来覆盖命令增多时抽公共函数（scope 收敛顺延）。铁律①自查：diff 无 key/.env 读写，仅 src/main/tests/docs。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1281 tests OK**（基线 1269 +12）；`verify.sh` exit 0（**须 `PATH=$PWD/.venv/bin:$PATH`**）；`preflight` 无 FATAL。

**数据状态**：纯代码+测试+文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮（iter067）**：#6 plan_compliance 建议被 writer `[:5]` 截断（reviewer prepend）/ #7 standalone review 不传 chapter_plan_item（含 CLI review-chapter）/ #8 Web 路径脱敏（jobs.py:899 + wizard.py×4，复用 `errors._redact_paths`）；jobs.py:891 BookRunBlocked 同类一并评估。计划文件 `~/.claude/plans/codex-findings-p1-src-book-runner-py-lin-agile-bunny.md`。codex #6 (b) outline-drift warn→block 仍独立顺延。

## iter 067（2026-06-24，收官）——codex iter066 复审 residual 收口：fail-closed 数值/JSON 守门补全

**来源**：codex 在 iter066 commit 后做二次只读复审，又提 3 个 **residual fail-open 缝隙**（iter066 修了 #1–#5 主体，但每条都漏了一个钻入口）。读码逐条核验**全部属实**。用户指令：核实后起 iter067 一起修。共因主题=「fail-closed 数值守门要同时堵三类入口：本次输入 / 持久化历史态 / 类型混淆（bool）」。

**F1（creation_confidence-bool）**：`src/run_params.py` 的 `validate_int`/`validate_float` 在 coerce 前各加 `isinstance(value, bool)` 守门（`validate_float` 放在 `allow_blank` 早返回之后，保 `None`/`""` 仍走默认）。根因：`bool` 是 `int` 子类，`float(False)==0.0`/`float(True)==1.0` 过 isfinite+`[0,1]` 范围，`validate_float(False)` 返回 `(None, 0.0)`；配 `agents.yaml` 的 `allow_creation: true` + 误写 `creation_confidence: false`（YAML 裸 false=布尔 False），`book_runner.py:911` 创建闸被悄悄降到 0.0 = 任意 confidence 过闸全开。中心化一处堵死连带封 13 处调用方；`book_runner` 无需改——既有 `creation_confidence = 0.85 if cc_err else cc_val` 自动回落安全默认。

**F2（resume-persisted-budget）**：`book_driver.cmd_resume` 把「仅校验显式覆盖」改为「校验生效值」——`effective = override if override is not None else params.get(...)`，对 budget/timeout 始终 `validate_*`，失败 `return 2`，清洗值**无条件写回** params。根因：iter066 #3 只守显式 `--budget-cny`/`--step-timeout-minutes`；不传覆盖时 `driver_state.json` 里 pre-iter064/手改的 NaN budget 原样流过 `_run_steps:356` `nan or 0.0`=`nan` → 成本闸 `spent>=nan` 恒 False 失效。三处边界靠 `is not None`（非 falsy）守住：override `0.0`/`0` 是合法覆盖、持久化 `0.0` budget=无上限（`allow_blank=True` 只判 `None`/`""` 不吃 0.0）、老 state timeout `None`→`DEFAULT_STEP_TIMEOUT_MINUTES`。验证仍在写回前 → 失败不半改 state。

**F3（write_json-allow_nan）**：`src/utils.py` `write_json` 改 `json.dumps(..., allow_nan=False)`，且**先序列化再建 tmp 文件**（被拒 payload 不留 `.tmp.*` 残留）。根因：默认 `allow_nan=True` 会把 entity_graph 里别处既有的 NaN/Infinity（非标准 JSON）经 `_apply_selected` 深拷贝在 confirm 时原样回写；iter066 #4 只清洗了「当前 proposal 的 confidence」。这是全局后端兜底（entity_graph/driver_state/chapter_plan/*.meta 全覆盖）。腐败图 confirm 抛 `ValueError` → auto_advance 经 `book_runner.py:931` 既有 `except (FileNotFoundError, IndexError, ValueError)` 优雅降级 `apply_advance_failed`（安全 no-op）；手动 `apply-advance` CLI 显式报错。

**审查（铁律⑨）**：`/code-review high`——2 个独立只读 Explore 视角并行：① write_json `allow_nan=False` 全局回归面反查（grep 所有除零均值/比率落盘点：`_weighted_panel_score`/beat coverage/outline_drift hit_rate/lang_detect/book_runner 进度比例**全部分母有 0 守卫**，confidence 聚合走 `coerce_finite_confidence`/Pydantic `ge·le`，结论「no non-finite write_json path found」）；② F1/F2 逻辑边界（13 调用方零依赖 bool→1/0、`is not None` 守 0.0 无上限语义、allow_blank 不误判、老 state 不被误拒）。主对话 line-by-line。**survived findings = 0**。`/security-review`：diff secret 扫描无 `sk-`/key；未碰 `.env`/`data/`/`outputs/`/`小说txt/`/`settings.local`；本轮 fail-closed 硬化净提升安全姿态。**未修风险无**——F3 对既有腐败图采「拒绝写入」非自动清洗（腐败图会阻断后续 advance 至手动修，预期 fail-closed 取舍），auto-heal 列 iter068 debt。

**测试 seed 教训**：F2/F3 的「既有损坏数据」fixture 必须用 stdlib `json.dumps`（默认 `allow_nan=True`）直写裸文件——`_save_state`/`write_json` 现在自身就拒 NaN，无法用来制造 on-disk 腐败 fixture。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1294 tests OK**（基线 1281 +13：run_params bool ×2、write_json ×5、book_driver F2 ×4、entity_advance F3 ×2）；`verify.sh` exit 0（**须 `PATH=$PWD/.venv/bin:$PATH`**）；`preflight` 无 FATAL/WARN；`git diff --check` clean。

**数据状态**：纯代码+测试+文档；未碰 `.env`/`data/`/`outputs/`/`小说txt/`。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter068）**：entity_graph 读时 auto-heal 既有 NaN（让 advance 不被腐败图阻断）/ codex 早前 P3 Web path redaction（jobs.py async + wizard OSError 原始串，复用 `errors._redact_paths`）/ #6 plan_compliance writer `[:5]` 截断 / #7 standalone review 缺 chapter_plan_item / codex #6 (b) outline-drift warn→block / cmd_resume 与 `_build_params` 抽公共校验函数。

## iter 068（2026-06-25，收官）——续写底座重建 + 长任务可观测/可取消 + readiness 重做（codex 前端验证 P0/P1 收口）

**来源**：codex 通过前端验证（以 longzu1_clean 续写）发现一批 P0/P1：真实用户从《龙族1》中段续写时，Workbench 第①步把「已有起点的续写」错当成「开新书」（绑死 prepare-greenfield）、长任务进度卡 33% 像死了、当前卡片无法止损、prepare 任务**无预算守门**（真模型无上限烧钱）、readiness 提示指向只读 /plan / KB 缺失归为 unknown / 起点窗口未提取只当 warning。3 个 Explore agent 逐条读码核实**基本全属实**；用户又派 4 个 subagent 对修复计划二次只读审核，抓出**预算 fail-open**（validator 缺省注入 `budget_cny:0` 被 jobs 当无限额）、**硬删 workspace 触碰原文版权边界**等 P0，已并入本轮。

**A · rebuild-for-start Web job + 三 stage 切换**：CLI 已有 `auto_pipeline.rebuild_for_start`（补提取起点窗口→recompress→bootstrap entity_graph/anchor --force→apply）；包成 `jobs._step_rebuild_for_start`（**预检 `get_start_chapter_id()` 不 blanket-catch ValueError**，否则 apply/bootstrap 真错被误报 start_point_missing；in-loop 预算；BudgetExceeded/ExtractionBatchFailure 映射）+ STEP_HANDLERS 注册 + `_summarize_result` 分支。前端 `bindWorkbenchStage` 第 4/5 参支持运行时函数求值；`initWorkbench` 的 prepare/plan-chapters/write-book **三 stage 都按 `lastWorkbenchStatus.has_start_point` 切**——有起点 prepare 走 `rebuild-for-start`（`{window:10}` 不传 force/reextract=补齐底座非强制重提）、plan/write 传 `require_start_point:true` 不绕起点闸；`refreshWorkbench` 改 stage① 文案（`#prepare-subtitle/#prepare-hint` 钩子）。

**B · 阶段内进度透传（A/C 前置）**：`extract_all`/`compress_all`/`bootstrap_all` 加 `progress_cb=None`（向后兼容，新参数置末位）；extract 每 manifest entry **顶端**回调（含 cached/失败→checkpoint 均匀）；`bootstrap_all` 重构为 list 驱动 `_BOOTSTRAP_STEPS`（保 6 key 现序，回归断言钉死）；`_run_prepare_steps`/`rebuild_for_start` 把子进度映射进 stage slot（`_sub(stage_index)`），子标签带 `:` 前缀避污染 STEPS 全等契约（测试侧 `":" not in name` 过滤）。**关键**：`jobs._progress` 内部先 `_check_cancelled`（raise）再 `_update`，故底层多调 progress_cb 即同时获得「进度 + cooperative cancel + timeout」，无需单独 cancel 参数。

**C · pollJob 取消入口**：非终态加 `data-cancel-job` 取消按钮 + 任务页链接 + 诚实文案「已请求取消·当前步骤 X·最多再等当前一次 LLM 调用结束」（cancel 状态服务端驱动，下一轮 poll 反映 `cancel_requested`）+ dashboard 自有 document 级委托（JS_WIZARD 的同名委托在别 bundle 不可复用）。**边界**：线程内无法硬杀同步 litellm 调用，本轮 = cooperative cancel。

**D · prepare/rebuild 预算守门（含 fail-open 修复）**：`routes._validate_prepare_params` **validate-only-if-present**——`budget_cny` 只在显式传入时校验落字段，缺省不写 → jobs 层 `_float_param(...,_default_budget_cny())` 兜默认 cap、显式 0=uncapped（CLI 语义）；若照抄 write-book 的无条件 `out["budget_cny"]=budget` 会把缺省规范化成 0 被当无限额。`_step_prepare_greenfield` 接 budget_check + BudgetExceeded→budget_exceeded；预算闭包抽 `_budget_guard(params)` 共享 helper（消 `_step_prepare_greenfield`/`_step_rebuild_for_start` 重复，code-review 采纳）。

**E · readiness 真产 blocker**：`readiness_catalog` 加 `kb_missing`（run_prepare）/`extraction_coverage_missing`（run_rebuild_for_start）+ classify 映射 `extraction:start_window_unextracted`/`extraction coverage gap before start point`；`outline_missing`/`outline_stale` CTA `go_plan→run_debate`（旧 go_plan 指只读 /plan 生不了大纲）。`book_runner.check_write_readiness` start_window warn→**条件 blocker**（仅 require_start_point，greenfield 保 fail-open warn 避 052 过度阻断）+ recommended 改 rebuild-for-start；`_step_plan_chapters` 捕获 plot_planner 既有 coverage ValueError→`_blocked("extraction_coverage_missing")`。前端 `bindCtaActions` 加 run_prepare/run_rebuild_for_start/run_debate→`/workbench#stage-*`（Continue 页无 stage 卡须跨页跳）；`renderJobPageCta` 去硬编码 `/plan//continue` 改 `ctaActionHref(cfg.action)` + 新增 `gotoStage` helper。errors.py 自动派生无需手改。

**审查（铁律⑨）**：`/code-review high`（3 角度并行 finder）——3 个「进度分数不到 1.0」correctness finding 经核算**全部 refuted**（`:`-子标签报的是 slot 内进度，裸边界标签 + `("done",1.0)` 标记阶段完成，整体单调到 1.0；rebuild extract 是 stage 0 故 `frac/total`=`(0+frac)/total` 正确）；采纳 1 cleanup 抽 `_budget_guard`。`/security-review`：iter068 新攻击面（rebuild 参数/cancel 按钮/CTA 路由）无 HIGH/MEDIUM——参数服务端 `_validate_prepare_params` 校验且不拼文件路径（workspace 服务端从 URL 解析非 params）、DOM 动态值全 `escapeHtml`、导航锚点为常量、无 subprocess/eval/SQL；fail-open 修复属安全**净提升**（堵预算绕过）。

**前端 mock 验证**：`soft_delete_workspace("longzu1_clean")`→`_trash/longzu1_clean__20260624_234418`（可逆未硬删未碰原文）；从 longzu 基线复制 book-1 源建自包含 `longzu_half`，normalize→split→set-start-point `longzu_1_ch007`（半本起点），`source_file` 旧路径残留 **0**（修复审计 907 处不自包含）。preview mock：stage①「重建续写底座」截图存证、表单 POST `step:rebuild-for-start params:{window:10}`、rebuild 跑通建 KB→stage prepare→outline 推进、pollJob 渲 cancel 按钮、注入 catalog CTA 全对、rebuild 抽窗后 coverage blocker 正确清除（状态驱动）；debate→plan 成功、write-book 因 mock reviewer 确定性 Reject 落 retry_exhausted（draft 已出稿，与 iter068 无关）。Cluster B/D 由单测覆盖（mock 瞬时/成本≈0 无法实时抓）。

**未修风险（诚实记录，铁律⑦）**：`settings_missing` 当前无真实信号产出（entity_graph 缺失走 graceful-degrade 同 KB），加 dead KIND 会误导，未实现；`check_write_readiness` **不**新增 KB/settings 存在性 blocker——`test_strict_plan_ready` 钉死「start-point 已设 + 无 KB/entity_graph 文件 = ready」既有契约（铁律④），加存在性 blocker 会翻转该测试及多个共用 fixture（052 式过度阻断风险），KB 缺失继续在 debate 步骤兜底（现经 classify 渲染正常卡片）；供 codex 复审：若坚持继续页 readiness 直接暴露 kb_missing 需配套迁移 readiness 测试 fixture 并重审过度阻断边界。硬中断取消需 async/子进程（线程做不到）。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1319 tests OK**（基线 1294 +25：新 `test_iter068_rebuild_progress_cancel.py` 27 用例 - 调整 4 进度契约/1 CTA 断言）；`verify.sh` exit 0（**须 `PATH=$PWD/.venv/bin:$PATH`**，裸 python3 缺 pydantic 假失败）；`preflight` 无 FATAL/WARN。

**数据状态**：代码+测试+文档 + 软删 longzu1_clean（→_trash 可逆）+ 新建 longzu_half 验证 workspace（均 gitignored，不进 commit）；未碰 `.env`/`小说txt/` 原文。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter069）**：硬中断取消（async/子进程隔离）/ settings_missing 真信号 + readiness fixture 迁移 / workbench prepare 预算·timeout UI 控件（后端守门已就位前端仍用默认）/ rebuild 进度卡显示 window 章号明细 / 真模型 capstone 验证半本起点（铁律⑥需授权）/ iter067 顺延的 entity_graph 读时 auto-heal + Web path redaction + plan_compliance 截断。

## iter 069（2026-06-25，收官）——前端 UX 改版：三功能入口 + 顶栏精简 + 命名/叙事一致性

**来源**：用户报告书架/首页 5 类 UX 痛点（顶栏桌面端冗余按钮、首页重复入口、首页混入作品内导航、误以为只能跑 mock、premise「一句话开新书」后端早实现却被埋在向导 upload 面板底部）。先用 26-agent 多视角工作流（PM/IA · 视觉设计 · 代码 bug · 测试 + 完整性批判 + 对抗验证）审核计划，按审核结论 + 用户 2 项决策定稿 v2 再实现。计划档 `~/.claude/plans/ux-1-1-1-3-http-localhost-8765-http-loc-snug-bird.md`。

**用户 2 项决策（反转原计划）**：① **⌂ 保持指向 `/library`**（审核核实全站面包屑无一处指向首页 `/`、"跳转交给面包屑回首页"是空承诺；登录后用户的"家"是书架而非营销首页）→ 原「改动 4：⌂→首页」**取消**；② **按「有无原文」重命名 + 统一 drama 术语**（novel→导入续写、premise→一句话开新书、drama→短剧剧本）。

**改动（仅 `src/web/templates.py` + `src/web/static.py` + `tests/test_web_routes_get.py`，纯前端展示层，不动 9 阶段管线）**：hero「开始续写」→「开始创作」统一入口 + 叙事 lead 扩成兼容续写+开新书；首页新增第 3 张「一句话开新书」卡（badge 正式开放 / footer `/wizard?type=premise`）；`_render_shell` APP_CLASS 加 `page_kind=="landing"` 显式分支叠 `.lp-chrome`（**绝不复用 `sidebar_html` 三元**——否则泄漏到 wizard/settings 隐藏其 ☰/⋯）；顶栏精简删「＋ 新建」只留「⚙ 设置」；删底部 lp-secondary 重复链接 + 清死 CSS；trust 计数 2→3 + 术语；wizard 副标题「两类」→「三类」（修 premise 加入后计划自带的事实错误）+ novel/drama radio 与卡片改名；premise 表单从 upload 面板抽成独立 `#panel-premise`（含 card-header + 独立 `#premise-error`，`#upload-error` 留 upload 面板）；wizard JS 加 `panelPremise`/`premiseErrBox`、`show()` 数组纳入 panelPremise（三面板互斥）、applyTypeFromQuery+typeForm premise 三分流、premiseForm 三处错误渲染改指 premiseErrBox；真模型可发现性据实静态文案（需配 API key + 重启服务，不承诺一键，独立于被 JS innerHTML 覆盖的 `#wizard-mode-card`）。

**前端真实 E2E（preview MCP，mock，桌面 1280 / 中宽 800 / 移动 375）抓出并当场修掉 2 个计划静态推演没覆盖的真 bug**：
- **CSS 源顺序**：计划把 `.lp-cards{repeat(2)}` 放进既有 `@media(max-width:1024px)` 块，但它在基础 `.lp-cards{repeat(3)}` **之前**，同特异性下后者按源顺序胜出 → 800px 实测仍 3 列（挤）。**修复**：把 2 列媒体查询移到基础规则**之后**。复测 1280→3 / 800→2 / 375→1 列全对。
- **移动端 ⚙设置 不可达**：lp-chrome 原拟隐藏 ☰/⌂/⋯，但移动端 ⋯（`.topbar-menu-toggle`）是打开 `.topbar-actions` 下拉（内含唯一动作 ⚙设置）的唯一入口（桌面端 ⋯ 本就被 `:288` 隐藏、⚙设置 直接显示）→ 隐藏 ⋯ 致移动端 landing ⚙设置 不可达。**修复**：lp-chrome 收窄到只隐藏 `.nav-toggle`+`.home-btn`。

E2E 全绿：三功能入口 + hero「开始创作」+ 叙事；3 卡等宽等高；顶栏仅「⚙ 设置」（a11y 树确认 ⌂/☰/⋯ 因 `display:none` 不在树内，无需 aria-hidden）；wizard 3 选 1 副标题「三类」+ 真模型据实指引；深链 `?type=premise`/`?type=drama` 各唯一显示对应面板（互斥）；premise 提交（`requestSubmit`）→ 创建 workspace → 跳 `/w/<name>/workbench`；workspace 页 ⌂ `href="/library"` 可见、面包屑「书架」可点；移动端 landing 1 列、⋯ 可见点开 ⚙设置 可达、wizard `app no-context`（无 lp-chrome）⌂/⋯ 可见 ☰ 隐藏；console 无 error/warn。（工具备注：`preview_click` 在本环境不稳定触发表单 submit/下拉 toggle 的 JS handler，改用 `requestSubmit()`/`.click()` 派发真实事件验证；后端 `POST /api/wizard/premise-start` 实测 202。）

**审查（铁律⑨）**：`/code-review high`（4 视角 finder：逐行正确性 / 删除行为+跨文件 / 复用-简化-效率 / 铁律合规）——**0 个需修 bug**。Agent A 逐行零 bug；Agent B 6 候选全 REFUTED（均为「若未来误删 #upload-error/#premise-error」「若 page_kind 改错」「若响应式重排卡片」推测，本轮测试已断言两容器存在 + E2E 证否；library 空状态提示指向「＋ 新建」对 /library 正确——该页保留按钮，landing 无 empty_hint）；Agent C 仅 2 条低价值风格建议（clearErrorBox helper / premiseForm guard 去留）按铁律⑦ scope 收敛不做。合规：无铁律违反（无龙族原文、测试全 mock、scope 未扩散）。`/security-review`（对口铁律①）——**无 HIGH/MEDIUM**：premiseErrBox 错误渲染经 `renderErrorCard`→`escapeHtml`（转义 `&<>"'`）无 XSS；真模型指引静态文案不泄 key、不渲染 .env；premise 重定向用 `encodeURIComponent`；workspace 输入 pattern 仍单源 `WORKSPACE_NAME_HTML_PATTERN` 未削弱；搬运不改任何转义/数据流。**未修风险**：JS 错误容器守卫风格不一致（novelForm/dramaForm 无 `if` 守卫、premiseForm 有）属既存小债，因 `#upload-error`/`#drama-error` 始终随面板渲染、无 NPE 触发路径，本轮不扩 scope（铁律⑦），测试断言 `#upload-error` 存活兜底。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1319 tests OK**（基线 1319，`test_web_routes_get`/`test_topbar_actions_scope` 扩断言、无净增模块）；`verify.sh` exit 0（**须 `PATH=$PWD/.venv/bin:$PATH`**，裸 python3 缺 pydantic 假失败）；`preflight` 无 FATAL/WARN。

**数据状态**：仅代码+测试+文档；E2E 产生的 `workspaces/e2e069_*` 临时 workspace 已清理；未碰 `.env`/`小说txt/` 原文。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter070）**：premise「一句话开新书」首次访问 / 空状态 / onboarding 完整体验（mock 下扩写为占位的引导）/ settings 页给 `OPENAI_MODEL` 专属说明分区 + 模型变更触发 `#restart-banner` / JS 错误容器守卫风格统一（既存小债）/ 真模型走查 premise·novel 生成内容（铁律⑥需授权，用户本轮已授权但留作可选最终步）/ iter068 顺延的硬中断取消 + iter067 顺延的 entity_graph auto-heal + Web path redaction。

## iter 070（2026-06-25，收官）——首页导航重设计（⌂→首页 + 离开守卫）+ 桌面死按钮修复 + 三入口平等 + 书架接缝收口

**来源**：用户在 iter069 后继续实测，报 4 类导航/入口痛点。先用 **4 个只读 subagent 做全前端 UX 审计**（导航 chrome/响应式 · 入口与向导流程 · 假按钮/死控件 · 命名/工程词泄漏）核实，再与用户逐项讨论、用 AskUserQuestion 定 **3 项决策**后实现。计划档 `~/.claude/plans/a-iter070-radiant-wind.md`。仅 `src/web/templates.py`+`src/web/static.py`+`tests/test_web_routes_get.py`，纯前端展示层，不动 9 阶段管线。

**用户 3 项决策**：① 离开守卫**给三选一**（任务后端独立线程跑、离开不中断它——诚实告知；回首页/取消任务/留下）；② **⌂ 改指首页**（落地 iter069 按决策 A 推迟的方案 B；brand+面包屑保留指书架）；③ 守卫**仅应用内导航**（不加 beforeunload）。书架按 **option A**（保持单一书架，只收文案/徽章接缝，不拆分、不加筛选）。

**改动（4 任务）**：**①** ⌂ href `/library`→`/` + aria「回首页」+ `data-leave-guard`；brand（:191）+ `_crumbs` 首项（i==0 有 href，:240-250）加 `data-leave-guard`（各自保留 href）；新 `ensureLeaveGuardDelegate`/`checkLeaveGuard`/`showLeaveGuardModal`（文档级委托挂 `initShellControls` 末尾，**同步 preventDefault** → 异步查 `/jobs/recent` → `pending/running` 任务弹三选一模态，复用 `showDeleteModal` 结构 + `postJson(wsUrl("/job/"+id+"/cancel"))` best-effort 409 吞掉 + `setPendingToastAndNavigate`；fail-open + `!window.WORKSPACE_NAME` 短路）。**②** CSS 候选 A：`.nav-toggle,.topbar-menu-toggle{display:none}` 从 topbar 块顶移到 `.btn` 之后（同特异性 (0,1,0) 靠**源序**胜出，修死按钮；不碰移动重显/no-context/lp-chrome）+ lp-chrome 过时注释更正。**③** 导入续写卡 `/wizard`→`/wizard?type=novel`（hero 保持裸 `/wizard`）。**④** option A：空状态文案去 epub/txt 中性化（:260 + emptyState body）；`.badge-drama` 边框 `--amber-soft`→`--amber` + typeBadge drama 加 `🎬`（消与 `.badge.running/.pending` 撞色）。

**两个实现坑严格规避**：① **异步 preventDefault**——拦 `<a>` 必须同步先 `preventDefault` 再 async 查（否则 await 期间浏览器已跳）；② **`historicalJobStatus` 漏 `succeeded`**（探索发现：`static.py` terminal 集合缺 succeeded，与 `jobs.py:61` 不一致）→ 守卫**显式只认 `pending/running`、不复用** `historicalJobStatus`（否则刚成功的 job 被误判活跃而错误拦截）。**CSS 候选 A vs B**：B 要牵动移动重显/no-context/lp-chrome 共 4 组（媒查不增特异性，移动重显须跟着升），回归面大；A 只动 1 行、移动逻辑字面未变，故选 A。

**前端 E2E（preview MCP，mock，web-mock 8765）**：桌面 1280 → `.nav-toggle`/`.topbar-menu-toggle` computed `display:none`、`.home-btn` `display:flex`（截图证顶栏只剩 ⌂+面包屑+内联 actions，☰/⋯ 消失）；移动 375 → ☰/⋯ 重显（跨断点正确）；workspace 页 stub `/jobs/recent` 返 running job → 点 ⌂ **被同步拦截不跳转**（`pathname` 仍 `/w/longzu/`）、弹三选一模态「当前作品有任务正在运行」+「离开本页不会停止它们」+ 三按钮（截图存证）；landing 三卡 href `?type=novel/drama/premise` 对等、hero 裸 `/wizard`、「打开已有作品」→`/library`；`window.WORKSPACE_NAME=""` 短路；console 无 error/warn。`node --check` 渲染 app.js（159046 bytes）语法 OK；渲染 app.css 程序化核对死按钮规则唯一+在 `.btn` 后+旧位删+`.badge-drama` 边框 `var(--amber)`。未实景验证项（诚实记录）：drama 徽章 🎬+边框（本机无 drama workspace，静态测试覆盖）/ 空书架文案（本机 3 workspace 非空，`assertNotIn("epub")` 覆盖）/ cancel-and-leave 端到端（模态渲染 + cancel 调用已分别验证）。

**审查（铁律⑨）**：`/code-review high`（3 finder：逐行正确性 / 移除行为+跨文件 / 复用-简化-效率-高度-规约）——**0 个需修 bug、0 规则违反、0 达标简化项**。一致核实：⌂ 改向后书架仍可达、aria 同步、CSS 移位源序正确、`pending|running` 排除 succeeded、escapeHtml/fail-open/409 吞掉/ESC·遮罩关闭健全、`_crumbs` 仅 guard `/library` 首项（landing 首项无 href 安全跳过）、委托范式与 `ensureJobCancelDelegate`/`bindCtaActions` 一致、测试断言逐字符匹配。仅 2 个可忽略边角（双击叠模态 / 中途导航残留 keydown）——与既有 `showDeleteModal` 等**同款特性**、属现状约定，按铁律⑦不扩 scope。`/security-review`——**无 ≥MEDIUM**：模态 innerHTML 插值（WORKSPACE_NAME/step/leaveLabel/n）全 `escapeHtml`；`location.href=href` 的 href 来自自有静态模板串（`/`、`/library`）无开放重定向；cancel 的 job_id 受后端 `[a-f0-9]{32}` 校验；step 来自 `STEP_HANDLERS` 常量枚举；项目为 stdlib `string.Template`（非 Jinja2）、workspace 名受 `WORKSPACE_NAME_HTML_PATTERN` 约束 + 模态内再 escapeHtml。

**未修风险**（诚实登记，铁律⑦）：leave-guard 模态与既有所有内联模态共享 2 个可忽略特性——(a) 极快双击叠两模态（都能 ESC/导航关闭）、(b) 中途导航走它路时该模态 document keydown 监听到下页 unload 才 GC。两者在 `showDeleteModal`/purge/partial 模态同样存在，是"每模态各写内联、无通用 helper"约定的固有属性，本轮不为单一新模态引入新机制（避免与既有不一致），留作全局模态重构债。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1324 tests OK**（基线 1319 +5 iter070 用例，无净增模块）；聚焦集 `test_web_routes_get` 69 OK。

**数据状态**：仅代码+测试+文档；preview 用了用户既有的 longzu/alpha/tianlong workspace（只读渲染，未触发任务、未改数据），起的 web-mock 服务已 `preview_stop`、端口已还；未碰 `.env`/`小说txt/` 原文。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter071）**：`debate --force` CLI 文案泄漏（给 Web 用户看不可执行命令）/ 复制按钮非安全上下文降级（局域网 HTTP 访问 `navigator.clipboard` 静默失效）/ 批量命名中文化（`workspace→作品`、章节表/统计表英文表头 + `approve/reject` 徽章值中译、短剧"续写"用词收口）/ 书架类型筛选-分组（option B/C，作品量大时）/ 全局模态去重 helper（消双击叠加 + keydown 残留既存小债）/ 首页↔书架框架断点的产品判断 + iter069 顺延项。

---

## Phase Status — iter 071（2026-06-25，收官）

**主题**：codex 对 iter070 leave-guard 改动只读复审，提 4 findings（1 Medium + 1 P2 + 2 Low）；claude 逐项核实**全属实**，按优先级一轮收口；用户在 claude 的 preview MCP 真实点击验证中看到模态截图，当场又指出该模态自身 2 个 UX 问题（F5/F6），同源纳入本轮。纯前端展示层 + 一个只读后端端点，不动 9 阶段管线。

**来源**：用户转述 codex findings（带 file:line）→ claude 先读码核实 4/4 属实 → 用 1 个 Explore subagent 精确探查 `_topbar_actions` 调用点 / `/jobs/recent` 路由 / `recent_jobs` 的 4 个消费方 / 是否有 active 端点，定下"不动 recent_jobs、新增 active_jobs 真源"的零回归修法 → 实现 → preview MCP 真实点击 E2E（用户中途追加 F5/F6）→ 4 视角对抗式 workflow 审查。

**6 项 findings 收口**：
- **F1（Medium）topbar 三出口绕过守卫**：`_topbar_actions`（templates.py:205）的回收站/设置/新建无 `data-leave-guard`，运行任务时从这 3 个离开 workspace 不弹守卫 → 3 链接各加 guard（非 workspace 页 `WORKSPACE_NAME=""` 由 `ensureLeaveGuardDelegate` 短路、零副作用；`extra` 透传不动）。
- **F2（P2）守卫漏刚入队 pending**：`checkLeaveGuard` 查 `/jobs/recent?n=10`，但 `recent_jobs`（jobs.py:153）按 `finished_at||started_at||0` 倒序截断，刚入队 pending（`started_at=None`→键 0）排末尾被 ≥10 终态挤掉 → **不动 recent_jobs**（4 个依赖排序消费方：continue 侧栏 static:3513/jobs 表 static:4531/overview novel+drama routes:474,519），新增 `jobs.active_jobs(workspace)` 直读内存 `_JOBS`（`start_job` 入队即原子写 `_JOBS`+`_WORKSPACE_JOBS`、每 workspace 至多 1 活跃、零截断零排序）+ 新路由 `GET /api/workspace/{name}/jobs/active`（复用 `_workspace_error`），前端切到它（进程重启 `_JOBS` 空→[]→fail-open 放行，正确）。
- **F3（Low）模态焦点弱**：`showLeaveGuardModal` appendChild 后未移焦 → 取 `[data-modal-close]`（"留在本页"最安全）`setTimeout(focus,0)`，对齐 delete 模态范式（不引入完整 focus-trap，留全局 a11y 债）。
- **F4（Low）空书架测试/文档过度宣称**：iter070 的 `assertNotIn("epub")` 命中带 fixture 的 `/library`（`names` 非空、空文案不渲染、空跑通过）→ 旧测试改名 `..._populated_shelf_has_no_epub_copy` 并诚实化 + 新增 `render_index([])` 直测真渲空书架中性文案；订正 iter070 文档第 55 行。
- **F5（用户 E2E）step id 泄漏**：模态正文显示 `write-book` 等内部 step id → 新增共享 `stepLabel()`（覆盖全部 16 个 `STEP_HANDLERS` 键，`write-book→续写正文`/`extract→抽取设定`…，未知 id 回退），模态用 `stepLabel(j.step)`。本轮只接模态这一 surface；jobs 页/侧栏/toast 同类中文化属"批量命名中文化"大项另起一轮。
- **F6（用户 E2E）三按钮丑、大小不一**：footer `flex;justify-content:flex-end` 致 3 个长短不一标签按内容撑开、480px 里各自换行 → 新增 `.modal-footer-equal .btn{flex:1 1 0;min-width:0;white-space:nowrap}`（仅作用于这一三按钮 footer，不动共享 `.modal-footer`/delete 模态）+ 标签缩短（取消任务并离开→取消并离开、去 leave 按钮 `（后台继续）` 后缀）。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1333 tests OK**（基线 iter070 1324 +9：`ActiveJobsTests` 3 + `test_web_routes_get` 6 个 iter071 用例；重命名 1 旧用例净增 0）。`node --check` 渲染 app.js OK。`verify.sh` exit 0（须 `PATH=$PWD/.venv/bin`）。

**前端 E2E（preview MCP，web-mock 端口 8765，真实点击 + DOM 取证 + 桌面/移动截图）**：`/w/alpha/` 6 出口（⌂/brand/面包屑首项 + 回收站/设置/新建）全 `data-leave-guard`；stub `/jobs/active` 返回活跃 job 后真实点击回收站/设置/新建/⌂ **均弹三选一模态且不导航**（trace 证命中 `/api/workspace/alpha/jobs/active`、`defaultPrevented=true`）；恢复真实 fetch（alpha 无活跃→`{jobs:[]}`）点回收站**直达 `/trash` 不困人**；`/trash`(`WORKSPACE_NAME=""`)即便 stub 活跃也短路直接导航 `/settings` 不弹模态；焦点 `document.activeElement`="留在本页"、Esc/遮罩/留在本页均关；正文显「续写正文」「抽取设定」无 `write-book`；桌面 1280 三按钮等宽 **138px**/移动 375 等宽 **87px** 全单行；桌面 `.nav-toggle` 仍 `display:none`、移动 ☰/⋯ 重显（iter070 未回归）；`「回首页」`离开按钮真实导航 `/`；console warn 级**无 error/warn**。未实景验证：「取消并离开」cancel POST 端到端（需真实 running job，mock 秒级完成难命中；best-effort cancel + fail-through 接线 iter070 既验 + 本轮静态保留）。

**代码审查（铁律⑨）**：5-agent 对抗式 workflow（正确性/安全/回归/规约 4 独立视角 → HIGH/MEDIUM 逐条对抗式核验 → 综合，244K subagent tokens）→ **0 个 HIGH/MEDIUM/LOW 真问题，7 条非阻塞 NIT（全既有/已登记），放行可提交**。关键事实经核验：`STEP_LABELS`↔16 键对齐、`/jobs/active` 注册不遮蔽、F1 三链接落位、F6 scoped、前端切端点。`/security-review` 对口：无 ≥MEDIUM、模态插值全 `escapeHtml`、`/jobs/active` 复用 name 校验、未碰 `.env`/`data/`/`小说txt/`。

**数据状态**：仅代码+测试+文档；preview 用了用户既有的 alpha/longzu/tianlong workspace（只读渲染 + stub fetch，未真起任务、未改数据），web-mock 服务起在 8765（可 `preview_stop`）。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter072）**：批量命名中文化（jobs 页/侧栏/toast 的 raw step → 复用 `stepLabel`；`workspace→作品`、章节表/统计表英文表头 + `approve/reject` 徽章值中译、短剧"续写"用词收口）/ 全局模态去重 + focus-trap helper（消双击叠加 + keydown 残留 + 完整焦点陷阱，统一所有内联模态）/ `recent_jobs` 排序修正（pending 在通用列表也排前，需同步 4 消费方）/ `debate --force` CLI 文案泄漏 / 复制按钮非安全上下文降级 / 书架类型筛选-分组 / `workspace_busy`+`workspace_running_job` 重复函数合并 + iter069/070 顺延项。

---

## Phase Status — iter 072（2026-06-25，收官）

**主题**：codex iter071 复审 residual 收口（2×P2 + 4×P3 + 1×a11y）+ 把 iter070/071 deferred 的「全局 focus-trap + 模态去重 / recent_jobs pending 优先 / 复制非 HTTPS 降级 / debate --force CLI 文案」一并清掉。前端展示层 + jobs 后端真源/出口收窄，不动 9 阶段管线。

**来源**：用户转述 codex findings（带 file:line）→ 3 个 Explore subagent 并行精确探查（leave-guard 前端系统 / jobs 后端 race+snapshot / 模态·复制·debate 入口）→ Plan-mode 起草 + AskUserQuestion 定 2 scope（focus-trap 抽可复用 helper 应用所有模态 / 附带纳入 pending 优先+复制降级+debate 文案，批量中文化不纳入）→ 实现 → `/code-review high`（3 finder + 对抗）→ `/security-review`。

**8 项 findings 收口**：
- **#1（P2）侧栏切作品绕过守卫**：`_sidebar`（templates.py:160）作品列表项无 `data-leave-guard` → 非当前作品项补 guard（当前作品项 + section 内导航是同 workspace 跳转，不加）。委托 `static.py:2146` 已基于 `closest([data-leave-guard])`+`WORKSPACE_NAME` gate，加属性即生效。
- **#2（P3）模态目的地文案错**：`static.py:2180` `href==="/" ? "回首页" : "去书架"` 二元判断使 /trash/settings/wizard/`/w/{name}/` 全显「去书架」→ 抽 `leaveDestinationLabel(href)` 全映射（/w/{name}/→「切到《name》」用 `indexOf/slice` 解析避免内嵌 JS 正则字面量的转义斜杠触发 Python SyntaxWarning）。
- **#3（P2）/jobs/active 发布顺序 race**：`start_job`（jobs.py:1166）先写 `_WORKSPACE_JOBS` 后写 `_JOBS`、两分离锁间有窗口，`active_jobs` 只扫 `_JOBS` → workspace 已 busy 但 `/jobs/active` 短暂返回空 → 在 `_WORKSPACE_LOCK` 内先嵌套 `_JOBS_LOCK` 写 `_JOBS` 再写 `_WORKSPACE_JOBS`（grep 全模块两锁同现处均 WORKSPACE→JOBS 单向、987→1001 为顺序非嵌套、无反序、嵌套安全无死锁；不变式 slot 置位 ⟹ `_JOBS` 必已含）。
- **#4（P3）active endpoint 暴露完整 record**：`api_workspace_active_jobs`（routes.py:1698）返回全字段含用户 POST `params` → 新增 `jobs.public_job_view()` 8 字段白名单（job_id/workspace/step/status/current_step/progress/started_at/finished_at，剔除 params/trace_id/result_summary/cancel_*），endpoint 投影；`active_jobs()` 内部返回不变，仅收窄 HTTP 出口。
- **#5（P3）recent_jobs 坏 timestamp 致 500 + pending 优先**：`recent_jobs`（jobs.py:153）sort key `float(finished||started||0)` 遇 `"bad"` 抛 ValueError → jobs 页/侧栏/overview 全 500 → 新增 `_as_ts()`（try/except + `math.isfinite` 把坏值/NaN/inf 归零，对齐 `_float_param`/`_timeout_deadline` 模式）；sort key 改 `(active, _as_ts(finished) or _as_ts(started))` reverse → pending/running 置顶 + 组内倒序。波及 routes 474/519 overview、1695 recent endpoint，前端信任服务端序无重排。
- **#6（a11y）模态无 Tab trap/焦点恢复**：4 模态构造器各自 closeModal/close+Escape+初始 focus，`openPartialPreview` 更完全缺 → 抽 `mountModal(backdrop,opts)`（记录触发元素 / Tab·Shift+Tab 循环 / Esc 关 / 关闭恢复焦点到触发元素 / `_activeModalTeardown` 去重防叠层 / `close` 幂等 `closed` 标志）应用全部 4 模态（delete/leave-guard/purge/partial），`openPartialPreview` 顺带补齐 Esc+焦点。还清 iter071 deferred 的全局 focus-trap+模态去重债。
- **#7 复制非 HTTPS 降级**：`bindCopy`（static.py:1686）仅 `if(navigator.clipboard)`，局域网 http 下 undefined 静默失效 → 抽 `copyText`/`legacyCopy`（execCommand textarea 回退 + 失败显「手动复制」），代码审查补强双击防卡标签（`btn._copyLabel` 一次性记真标签 + `clearTimeout` 在途定时器）。
- **#8 debate --force CLI 文案泄漏**：`renderPlanSummary`（static.py:2280/2284）红框/info 框写 `请重跑 debate（--force）` → 确认 Web 已有应用内「② 大纲·生成大纲」(debate step) 入口，文案改指向它不暴露 CLI。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1341 tests OK**（基线 iter071 1333 +8：`Iter072JobsResidualTests` 5（_as_ts 非有限/坏值、pending 优先、public_view 白名单、start_job 写序探针）+ `test_web_routes_get` 3（侧栏 guard、active 字段收窄、JS residual）；iter071 的 `..._immune_to_recent_truncation` 因 #5 行为变更据实改名 `..._surfaces_in_both_sources` + 更新 focus 断言为 `mountModal(... initialFocus: stayBtn)`，净增 8）。`node --check` 渲染 app.js OK。`preflight` exit 0。`verify.sh` **本机不可跑**——脚本第 41 行硬编码裸 `python3 -m unittest`，该解释器缺 pydantic → 259 个 `ImportError: Failed to import test module`（跨 debater/extractor/book_runner 等未触及模块，与本轮无关；裸 `python3 -c "import pydantic"` 即 ModuleNotFoundError）；等价闸门 = 上面 venv discover 1341 OK（与记忆 `novel-tests-need-venv-python` 一致）。

**代码审查（铁律⑨）**：`/code-review high` 3 finder（line-by-line / concurrency-backend / removed-behavior+cross-file）+ 对抗核实。headline 风险（死锁、回滚、白名单、坏行 500、stale test、dangling closeModal 引用）全 clean。3 个 LOW：① `copyText` 双击卡标签 → **已修**；② `_as_ts` 放行 NaN/inf 破坏排序总序 → **已修**（isfinite 守门 + 新测）；③ `recent_jobs` pending 优先**透传**到 overview「最近任务」卡（routes 474/519，limit=1）使其从"最新完成"变"优先在跑"——判定为符合本轮意图的改进，留 Notes 记录不改。`/security-review`（聚焦 4 源文件工作树 diff）**0 HIGH / 0 MEDIUM**，且净正向：`public_job_view` 收窄对外字段（剔除用户 POST `params`）、`_as_ts` 硬化坏输入、锁序收紧守卫可观测性；唯一新建裸串路径 `leaveDestinationLabel` 在唯一 sink `escapeHtml(leaveLabel)` 转义，XSS 链闭合。未碰 `.env`/`data/`/`小说txt/`。

**数据状态**：仅代码+测试+文档（4 源文件 + 2 测试文件 + 3 处文档）。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter073）**：批量命名中文化（本轮用户明确不纳入，单独成轮）/ overview「最近任务」卡 type-aware 文案 + 测试 pin「最新完成 vs 在跑」/ `/jobs/recent` 端点字段收窄（drawer 依赖 result_summary/error/trace_id，需配套前端）/ `workspace_busy`+`workspace_running_job` 重复函数合并 / 书架类型筛选-分组 / drama 站③④ / 真模型 capstone + iter069/070 顺延项。

## Phase Status — iter 073（2026-06-25，收官）

**主题**：真模型长程实测前一轮硬化——codex 复审的一批已确认 P1（review 误拒 / 计划履约不阻断 / Web jobs 排序与字段 / leave-guard 竞态 / 非有限 JSON）+ outline-drift severe→block + 第二批 docs/校验。给真模型实跑铺地基。

**来源**：用户转述 codex findings（带 file:line）→ 3 Explore subagent 并行探查（reviewer/writer broad-cast+plan / web jobs 排序+字段+JSON / leave-guard+第二批）→ Plan subagent 起草 + Plan-mode AskUserQuestion 定 2 决策（B 默认开 ratio=1.0 / outline-drift 纳入但严格 gate）→ 实现（据 codex 二次复审修正 5 点：D1 持久化也清洗 / D3 详情页保 params 轻量档 / B 先迁移测试再加 block / E modal-open 语义 + 测试 / 持续措辞不过度承诺 / timeout=0 语义）→ `/code-review high`（5 角度 + 对抗）→ `/security-review`。

**收口项**：
- **A（误拒）** broad-cast warn_only 没进主/外审：`writer.py:271` 主审 + `book_runner` 两处外审硬编码 `enforce_relationship_checklist=True` → 改 `_enforce_checklist_for_plan(item)` 派生（无 plan→True 严格，字节兼容），10-20 人物章不再被关系清单缺失误 Reject。
- **B（不阻断）** plan-compliance 永不翻 verdict：config `plan_compliance_block`（默认 `enabled=true, miss_ratio=1.0`）+ `_plan_compliance_block_cfg(is_mock)`；`plan_misses` 上移到 panel 聚合前，severe（≥ceil(total*ratio) beats 字面零重合，ratio=1.0=全缺=整章抛弃）注入 `_synthetic` Reject 走既有 `hard_synthetic_reject`；advisory 复用同一 `plan_misses`。**先迁移旧 9 测试 patch `(False,1.0)` 锁 enabled=false 语义、再加 block**。**mock-skip**（`client.is_mock`）防误触 mock 流水线（铁律④）。
- **B3** `review_target` 加 keyword-only `chapter_plan_item`，外审 + Web 重评审（`_step_review_chapter`）也跑 plan-compliance。
- **C（排序）** `recent_jobs` 旧 lost 压新成功（overview limit=1 长显失联）：reconcile lost 提到 sort 之前（一次性快照 `_JOBS`），lost 视为 terminal(active=0) 不再压更新 succeeded。
- **D1（非有限 JSON）** `_finite_json_safe` 递归 NaN/±Inf→None，`routes._json` 响应 + `jobs._persist_job` 落盘双侧清洗（只清响应、日志仍落脏会被 recent_jobs 读回再外发）。
- **D2/D3（raw record）** 三档投影：overview→最小 `public_job_view`（剔 params/trace/result_summary，多 workspace 首页收益最大）/ `/jobs/recent`→`public_job_summary_view`（保 params 给 jobs 表 retry，丢 cancel_*）/ `/job/<id>`→`public_job_detail_view`（加 cancel_*）。用户选轻量档（详情保 params 零改前端 retry）。
- **E（竞态）** leave-guard：`leaveGuardSeq` 每点击 ++ 捕获、异步返回校验 `seq===leaveGuardSeq` 丢弃旧响应；`leaveGuardModalOpen` 单模态（保持原 href 绝不静默跳错）；`mountModal` 加 `onClose` 复位（Esc 走内部 close 故需 hook）。
- **I（outline drift）** `outline_drift_severity` 三态（severe=hit<0.2 且 anchors≥5，最近 10 章聚合「近似持续偏离」非严格逐章连续）；book_runner severe + `require_start_point` + `_outline_drift_block_enabled()`（默认开、mock-skip via `is_mock_mode`）→ `outline_severe_drift:` blocker（`run_write_book` 入口 `BookRunBlocked` 硬停），新书 + 普通 drift 仍 warn；`readiness_catalog` 加 `outline_drift_severe` kind（CTA run_debate）。
- **F/G/H** README venv 命令 + 测试数 590→1369 / iter072 E2E 缺记回填（据实「未实跑 preview，node --check + 字符串断言代偿，顺延」）/ `drive-book start` step-timeout `validate_int(0,1440)` 与 resume 对齐（0=默认 180 非禁用，测试钉死）。

**门禁**：`OPENAI_MODEL=mock`（**必须 `.venv/bin/python3`**）`unittest discover -s tests` **1369 tests OK**（基线 iter072 1341 +28）。`node --check` 渲染 `JS_DASHBOARD`/`JS_WIZARD` OK。`preflight` exit 0。`verify.sh` 本机裸 `python3` 缺 pydantic 不可跑（与本轮无关，等价闸 = venv discover 1369 OK）。前端 E2E：leave-guard 竞态属时序竞态 preview 难稳定复现 → `node --check` + `STATIC_JS` 字符串/逻辑断言代偿，据实顺延。

**代码审查（铁律⑨）**：`/code-review high` 5 角度（line-by-line / removed-behavior / cross-file / reuse-simplify-efficiency / altitude-conventions）+ 对抗核实。**3 actionable 全修**：① Web `_step_review_chapter` 第三处 `review_target` 漏改致 verdict 分叉 → 对齐 book_runner；② `outline_severe_drift` CTA 文案「--force 覆盖」错（force 清不掉它）→ 指向 `config/agents.yaml` 开关；③ mock 判定双机制（`client.is_mock` vs 裸 env）在「env 空+default mock」分歧、违铁律④ → 新增 `config.is_mock_mode()` 统一。+ 1 efficiency（`recent_jobs` 一次性快照 `_JOBS`）+ 修 `outline_drift` 过时 docstring。未采纳留 Notes：`_synthetic_reject` 工厂（动既有块，scope 收敛）/ `_finite_json_safe` 全 payload 递归（correctness 优先）/ `outline_drift_severity` 与 `_codes` 各算一遍（非热点）。`/security-review` **0 HIGH / 0 MEDIUM**，净降暴露——三档 job 投影是改前「raw 全字段」的严格子集（不可能新增外泄），overview 收紧剔 params；leave-guard JS 只处理 int/bool + `window.location.href` 导航（非 innerHTML sink）。未碰 `.env`/`data/`/`小说txt/`。

**数据状态**：仅代码+测试+文档（9 源文件 + 8 测试文件 + 4 处文档 + config）。aeloon 并行文件（`docs/AELOON_INTEGRATION.md`/`CLAUDE.md`/`aeloon超前部分实现指南/`/`scripts/aeloon_sync_check.sh`）**不并入本轮 commit**（铁律⑦）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter074）**：公开 job API 彻底零 params（后端 `/job/<id>/retry` 端点 + 章节号 result_summary 派生）/ `_synthetic_reject` 工厂统一两处合成 Reject / outline_drift LLM 语义版 / drive-book 前置预算守门 / 批量命名中文化 / drama 站③④ / 真模型 capstone。

## 真模型长程实测前置排查（session，2026-06-26）——长流程 bug 排查 + 20+ 章可行性 + 运维教训

> 用户 goal：「找任何影响长流程续写的 bug + 验证 20+ 章可行性，直到确定可上真模型」。本 session **未收成正式 iter**（真跑被环境问题打断、用户主动暂停）。结论 + 教训如下，给下一个真模型 capstone 轮直接用。

**判定**：结构 GO——四向排查未发现会让长流程**崩溃/静默损坏**的引擎 bug；真模型环境就绪（gpt-5.5-low 调用全 `status=ok`）。唯一暴露的引擎隐患（entity_state 无界注入）已加保险。**缺口**：未实际跑通 20+ 章真模型（被运维问题阻断，非引擎问题）。

**排查证据**：
- **编排骨架扛 25 章**：mock `write-book --chapters 25 --replan-every 5` 全 written+Approve，4 次自动 replan 零崩溃；prompt token 7798→11281 后**持平**（rolling 注入有界，ch5 后 ~34 tok/章）。
- **resume 实证**：对已完成 25 章 workspace 重跑 → 全 `skipped_approved`，**0 次新 llm_calls（零重复花费）**。
- **真实 prompt ground truth**（longzu 246 次真模型 write 调用）：prompt_tokens **min 4667 / max 48971 / avg 19766**，红线=128000×0.9-8000=**107200** → 余量 ~58K。context 溢出**非实际阻断**。
- rolling 压缩/prune/render **正确无 bug**（按 chapter_no 排序去重、prune 只在 retry 调用是对的、注入封顶 `recent[-5:]+compact[-40:]+residual[-10:]`）。
- lint cascade（iter020 ch10 死因 `not_x_but_y`）**已 iter023 改 warning-only**（error_threshold=999）。

**唯一引擎修复（已 commit `178ab62` "Guard entity state prompt size"）**：`entities.render_active_state` 加 `max_chars=None`（默认字节不变）+ 行边界截断；writer/reviewer/debater/plot_planner **四处**统一传 `PROMPT_ENTITY_STATE_LIMIT=16000`。此前四处全量无截断注入 entity_state，若 `allow_creation=True` 或巨型抽取使图增长，prompt 撞红线 → `LLMContextOverflowError`**确定性不重试硬 halt**。提交版比初版**加固**：`_truncate_state_text` 补了 `max_chars<=0` 与 `len(marker)>=max_chars`（cap 比 marker 还小）两道边界守门 + 第 7 个测试 `..._tiny_cap_still_respects_limit`。改动 6 文件：`src/{entities,writer,reviewer,debater,plot_planner}.py` + `tests/test_entities.py`（entity 单测 7 绿；全量 `unittest discover` **1372 OK**，基线 1369 +3，零回归）。

**教训①——mock 测不出真模型长流程风险（最重要）**：mock 下 `_propose_entity_advance` 因 `client.is_mock` 返回 `[]`（entity 图不递增）、reviewer `_mock_text` 永远 Approve。所以 mock 跑通 25 章是**假安心**——它不触发真正会 halt 长流程的两件事：(a) entity 增长撑 context、(b) panel 投票拒绝。**真模型 capstone 不可省**。

**教训②——真正会 halt 长流程的是 panel 投票，不是崩溃**：某章 `max_retries` 内达不到 `min_approve_count`（review_tier：HIGH=5/5+8.5 / MID=4/5+7.5 / LOW=3/5+6.5）→ book_runner `break` 整书停（但 graceful、产物保留、可零成本 resume）。长跑选 **MID 档**（HIGH 全票 halt 概率高）+ `max-retries 3`。`allow_creation` 默认 False → 自动跑中 entity 图其实**不增长**（只更新已有关系 active state，render 不增），所以 context 溢出在默认配置下**不是**实际威胁。

**教训③——endpoint 慢（~2.5 min/call）是真实约束**：debate=43 步（6 轮×6 agent + 6 裁决 + 1 大纲合成）≈ **90-108 min**；write 每章 ~10-15 次调用 ≈ **30-40 min/章**，10 章 ≈ **5-7 小时**。真跑是数小时级，**必须脱离会话跑**。

**教训④——绝不用 Claude Code 后台任务（`run_in_background`/Monitor）托管真模型长跑**：本 session 真跑三次都在中途**进程被静默杀**——LLM 调用全 `status=ok`、无 traceback、无 RC、harness 报 `No task found`，伴随 MCP 断连重连（环境 churn）。这是 **Claude Code 后台任务生命周期问题，不是 endpoint / .env / 引擎 bug**——**用户从自己终端发起的进程根本不是 Claude Code 后台任务，定义上就碰不到这个死法**。正确跑法：**`drive-book --detach`**（产品自带 double-fork + `os.setsid` + `caffeinate`，专为脱离会话设计；macOS **无 `setsid` 命令**、`nohup` 不换 session 照样被杀，故必须用产品的 Python 级 detach），由**用户从自己终端发起**，`drive-book status` 查、关终端不死、可 resume。⚠️ 注：`drive-book --detach` 在数小时真跑中的存活本 session **未端到端验证**（真跑被上述托管问题打断），但其 detach 机制（os.setsid 脱离会话）设计上即为此场景，下一轮 capstone 应实测确认。推荐命令：
```bash
python3 main.py --book <name> drive-book start \
  --chapters 10 --segment-size 1 --plan-target 10 \
  --tier mid --max-retries 3 --budget-cny 150 \
  --step-timeout-minutes 90 --detach --confirm-real-run
```

**教训⑤——从零搭 mock workspace 跑长流程的最短路径**（复现自 `tests/test_book_driver.py:DriverE2ETests`）：复制源 txt → `normalize/split`（确定性免费）→ `extract --limit 2 --force` → `compress` → `bootstrap-personas`+`apply-bootstrap --confirm` → `debate` → `plan-chapters` → `write-book`。`MOCK_WRITER_CHARS=4000` 让 mock writer 产出够长草稿过 `short_chapter_length` 闸；不设则 write prompt 含 `previous_review_feedback:` 的「review」字样命中 `_mock_text` 的 review 分支返回 JSON 当正文 → 0 中文字 → 卡死（mock 测试 artifact，非真 bug）。复用别的 workspace 的 `data/` 不污染（源派生 + 起点纯净态 + outputs 不复制即可），但**别复制 `outputs/`**（含续写 drafts + 跨章 rolling 这类运行态）。

## iter 074 Phase Status（2026-07-01，收官）——章节版本 diff（读者/编辑向质量复核工具）

**背景**：工程主链路 iter073 后 STRUCTURE GO，用户定后续路线图（`~/.claude/plans/logical-snuggling-gray.md`）：先交付主线读者/编辑向产品功能 → iter076 长跑可靠性硬化（用户「过夜不跑废」诉求正解）→ iter077 真模型 capstone（需授权）。本轮=路线图第一步。Plan-mode 3+3 Explore 探查可行性 + 2 轮 AskUserQuestion 定「新产品功能 / 章节 diff」+ 用户否掉 Aeloon 深色模式（sync 边界冲突）。

**做了什么**：
- **新增纯函数 `src/web/chapter_diff.py`**：`list_chapter_versions`（current+snapshots newest-first、无快照/坏 meta/缺 md graceful 降级）/ `resolve_version_text`（**路径穿越 fail-closed by construction**：`_STAMP_RE`=`^\d{8}_\d{6}$` 锚定 + `resolve().relative_to(<drafts>/snapshots)` 抗符号链接）/ `compute_diff`（`difflib.unified_diff` → `meta/hunk/add/del/ctx` 分类 + `identical`）。
- **2 GET 端点**（`routes.py`）：`/api/workspace/<name>/chapter/<n>/versions` + `/chapter/<n>/diff?v1=&v2=`（v2 缺省 current）。handler 第三重闸：v1/v2 必须落在 `list_chapter_versions` 的 `valid_ids` 集合，未知/穿越 id 触盘前 400。复用 `_archive_chapter_artifacts` 快照布局 + `read_json_optional` + edit 追踪 meta 字段。
- **前端**（`static.py`）：填充章节详情页「历史」tab 的 `#tab-diff` 占位（原 4297「将在后续版本开放」文案）为「多版本对比」——版本选择器 + `loadChapterDiffVersions/runChapterDiff`（默认最新快照→当前草稿、`<2 版本`中性文案、`onclick=` 无监听器堆积）+ diff CSS（`--jade-soft` add/`--sienna-soft` del，暗色天然兼容）。

**验收**：canonical **1385** tests OK（.venv，1369+13+，394s）；新增 `tests/test_web_chapter_diff.py` 13 例。实时 HTTP e2e（只读现有 `tianlong` ch4：`/versions` 4 版本 newest-first、`/diff` 分类行、`/diff?v1=../../../etc/passwd`→**400 fail-closed**）+ 浏览器截图（diff 红/绿 155 行渲染）。`preflight` exit 0；`verify.sh` 本机裸 python3 既有 import 错误（缺 pydantic/tiktoken）与本轮无关。

**铁律⑨ 审查**：2 独立视角 subagent 并行 + 安全自查。后端**无安全漏洞/崩溃/路由冲突/重复**（路径穿越三重闸、坏 meta 降级）；前端**无 XSS**（全 `escapeHtml`）；`sk-|.env|api_key|token` 零命中。**2 LOW 效率残留已记录未改**（scope 收敛）：① 在途 fetch 若重渲染，旧回调写脱离 DOM（无害）；② history tab 未开也随每次 render 预取（延续 eager 惯例）。可选优化：generation token / tab-active 懒加载。

**数据状态**：代码+测试+文档（`chapter_diff.py` + `routes.py` + `static.py` + `test_web_chapter_diff.py` + 迭代 doc + README 行 186 + 索引）。**顺带提交无渲染影响的 Aeloon drift**（`docs/AELOON_INTEGRATION.md` + `aeloon超前部分实现指南/深色模式实现指南.md` + `scripts/aeloon_sync_check.sh`，均 doc/工具不改 CSS）。**只 commit 不 push，等用户验收（铁律⑤）**。

**下轮候选（iter075）**：**全文搜索**（`src/search.py` 内存扫描 + 复用 `chapter_splitter.load_manifest/chapter_text`，跨章实体/伏笔/关键词检索）。**iter076 长跑可靠性硬化**（面板拒稿不 halt 整书 / 每章预算预留 / 每阶段超时 / 心跳文件 / crash 自恢复）是 **iter077 真模型 capstone 实跑**（10-20 章，需用户授权）的前置门。**Aeloon 深色模式对齐**留 backlog（跨仓库字节级对齐 + 跑 `aeloon_sync_check.sh` 验 ✅）。char-level diff / diff 缓存 / 版本选择器懒加载 / diff 面板复用到大纲·KB 对比为本功能延伸候选。

## iter 075 Phase Status（2026-07-02，收官）——全文搜索（跨章检索）

**背景**：iter074-077 路线图第二步。与 diff 同为读者/编辑向工具，但更净新增、更独立——做跨章正文内容检索（连贯性核查：实体/伏笔/关键词跨章定位 + 长书导航）。与章节列表页已有的 `#chapter-search`（只对已加载表格按 ID/标题本地过滤）互补：本轮读**正文内容**做真全文检索。Plan-mode 3 Explore（后端复用点 / Web 新页面模式 / 测试约定）+ 1 Plan agent 压测设计蓝图 + AskUserQuestion 定 3 scope 决策（三语料全搜 / iter074 diff 顺带轻度美化 / i18n 就近小清理）。

**做了什么**：
- **新增纯函数 `src/search.py`（~330 LOC）**：`search_workspace(query, *, sources=None)`——须在 `use_workspace(name)` 上下文内调（不接收 name，纯函数）。三语料 `original`(manifest 原文，复用 `chapter_splitter.load_manifest`)/`draft`(`drafts_dir().glob("chapter_*.md")`，正则 `^chapter_(\d+)$` 排除 `.partial`)/`kb`(`kb_view.start_safe_knowledge(respect_start_point=True)` 起点安全)。**安全匹配**：大小写不敏感**字面子串** `str.lower().find`，**不编译用户正则**（从根规避 ReDoS，元字符自然字面量）。`normalized_file` 级读缓存（多章共享一卷把 N 次全文件 IO 降 1 次）。有界收口常量集中（MIN/MAX_QUERY_LEN/CONTEXT_RADIUS/MAX_SNIPPET_LEN/MAX_SNIPPETS_PER_CHAPTER/MAX_CHAPTERS）+ `truncated_reasons`（query/snippets/chapters 三维、**从最终存活 hits 派生**无悬空 + 无静默截断）。`str.lower()` 长度不变式保 offset 精确高亮。dataclass `Snippet{text,offsets}`/`SearchHit`/`SearchResult`，`asdict` 直接 JSON 化。
- **后端**（`routes.py`）：`api_workspace_search(name,q,sources)` + `render_workspace_search_page`（`_workspace_html_guard_novel_only` novel-only）+ 2 路由（页 `/w/<name>/search`、API `/api/workspace/<name>/search?q=&sources=`）+ `from .. import search as search_mod`。空 q→200 空结果、最外层 try/except→`_log_degraded`+200 兜底（铁律④）；`sources` 逗号拆分透传做作用域检索。
- **前端**（`templates.py`+`static.py`）：`render_workspace_search`（page-header + `.search-hero` 大搜索框 + 三语料勾选 + 三态容器）+ 侧栏 `_WORKSPACE_SECTIONS` 加「搜索」（drama 不加）。`initSearch`（`pageKind==="search"` 门控）：`buildSnippet` **全 DOM textNode + offsets 高亮**（零 innerHTML 拼正文，XSS 后端零 HTML）、250ms 防抖、`seq` 竞态守卫、source 勾选→后端作用域重搜、全不勾→提示不请求。CSS `.search-*`（amber `<mark>` 高亮、三色 source badge）全复用设计 token。
- **顺带**：iter074 diff/历史 tab 轻度美化（`.diff-*`：面板分隔线 / 卡片式版本选择器 + focus ring / 带边框滚动 diff / 增删行 accent 竖条，不改数据流/端点）+ i18n 就近清 4 处（`作品名`×3 / `创建短剧作品`，未动表单 `name` 契约）。

**验收**：canonical **1415** tests OK（.venv Python 3.13，1385+30：`test_search.py` 19 module + `test_web_search.py` 11 route）。含正则特殊字符字面量 / ReDoS 输入秒回 / 大小写不敏感 offset 指原文 / 有界三维 + 悬空 reason 回归 / sources None-vs-空语义 / XSS 片段原样 / 读缓存 read_text=1 / lower 长度保险 / KB fail-open / route 端到端命中·空 q·非法名 400·drama guard·sources 作用域。Web e2e（`preview_*` + 合成 `sdemo` workspace 验完即删、零版权原文）搜「星火」→ 续写→原文→原文→知识库排序 / 三色 badge / `<mark>` DOM 高亮 / 取消勾选→后端 `sources=draft,kb` 作用域重搜（HTTP 日志实证）/ 全不勾→「请选择检索范围」/ 空态截图均过、console 净；iter074 历史 tab 美化后 diff 正常渲染。`preflight`(venv) 仅 WARN/INFO 无 FATAL；`verify.sh` 裸 `python3`(3.9) 3 既有 import 错误（`dict|None` PEP604 + 缺 tiktoken，本轮未碰文件）与 iter075 无关（等价闸=venv 1415 OK），新增文件系统 3.9 `py_compile` 通过。

**铁律⑨ 审查**：`/code-review high`（3 finder 并行）修 2 真实问题——① `truncated_reasons` 悬空引用（>200 章丢弃章留 reason）→ 从存活 hits 派生；② API 忽略 `sources`（客户端过滤致 truncated 误导+无谓全扫）→ sources 透传后端 —— + 1 顺带（source 防抖）；5 项误报/超范围附理由未采纳（showEmpty 实为 textContent 安全 / catch 竞态误读已有守卫 / chapter_no 后端派生+详情页已校验 / fail-open 铁律④已 `_log_degraded` / render 复用 8+ 函数更广重构铁律⑦）。`/security-review`（聚焦 sub-task）**无 HIGH/MEDIUM 漏洞**：XSS 全 DOM textNode（95%）/ 路径穿越读取路径全 pipeline 写 + glob + workspace 名校验（98%）/ 无正则·SQL·模板注入 query 只进 `str.find`（99%）/ workspace 线程隔离 / KB 起点剧透过滤 / 零 `.env`·key（铁律①）。**未修风险无**（真实问题全修+回归测试，安全无残留）。

**数据状态**：`src/search.py` + `routes.py`/`templates.py`/`static.py` + `test_search.py`/`test_web_search.py` + 迭代 doc + README 行 186 + 索引。**只 commit 不 push，等用户验收（铁律⑤）**。未碰 `.env`/`data/`/`outputs/`/`小说txt/`。

**下轮候选（iter076）**：**长跑可靠性硬化**（面板拒稿不 halt 整书 + 每章预算预留 + 每阶段超时 + 心跳文件 + crash 自恢复 = 用户「过夜不跑废」诉求正解），是 iter077 真模型 capstone（10-20 章，需授权）前置门。全文搜索延伸候选：SQLite FTS5（>500 章/>50M 字触发）/ 搜索结果分页 / 高亮跨片段 / KB 起点过滤视图 / char-level diff。

---

## Phase Status — iter 076（2026-07-02 收官）：长跑可靠性硬化 + iter074/075 codex 修复批（capstone 前置门）

**已完成（本轮）**：五个 HIGH 全落地——① `panel_block_policy`（soft 拒稿 `caveat_continue` 放行/hard `force_once` bonus/默认全保守=原行为；reviewer report 顶层 `hard_reject`；caveat 章 `skipped_caveat` resume 跳过；配额跨 run 累计计入盘面存量）；② 每章预算预留（`estimate_next_chapter_cost` 累计值差分+滑动均值 × `budget_reserve.safety_factor`，不足 → `budget_exceeded+reserve_stop` 干净停；闸位于 skip/补外审分支后零花费路径不误停）；③ drive-book 分档超时 `--debate/--plan/--write-timeout-minutes`（fallback step，双侧校验）；④ driver 30s 切片心跳 `logs/driver/driver_heartbeat.json`（epoch 整型秒）+ watchdog `--driver` 模式（心跳判活/abort 标记/TERM→30s→KILL 升级/abort 后留场/pid 命令行校验防误杀）；⑤ `scripts/drive_book_supervised.sh` crash 自动重启（决策表×paused_reason×标记新鲜度、指数退避、MAX_RESTARTS=5+MAX_ROUNDS=48 双上限、supervise.pid 互斥、真模型无预算 WARN、确认闸）。前置 A 部分（commit `476318c`）修 codex 六项主发现+低风险批（收容闸/keep_blank_values/前端 stale guard×2/total_matches/diff 上限/path 相对化/URL 恢复/a11y/≥2 字门槛）。

**铁律⑨**：双视角独立 subagent 并行审（正确性 + 安全）——3 MED（A3 预留闸误停补外审 / B-M1 慢崩绕过重启上限 / B-M2=A5b watchdog 一发即退无 KILL）+ A2a（caveat 配额跨 run 重置）+ LOW 批全修并回归钉死；残留仅理论性条目（meta symlink 内容 oracle / soft 标签失真 / GNU stat 探测）附理由记录于 iteration doc。铁律①②零命中。

**验收证据**：`.venv` unittest discover **1475 tests OK**（iter075 1415 → B 部分 +53 → 审查修复 +7）；verify.sh 仅 3 个既有环境性 error（系统 py3.9 口径同 iter074/075）；preflight 无 FATAL；mock 25 章回归三关全过（succeeded+25/25 Approve+心跳新鲜 / resume 零新 LLM 调用 369 行不变 / supervisor `--resume-first` 真 driver 集成 exit 0 零花费）。

**教训**：mock planner 固定输出 5 章（忽略 --chapters）——mock 长程回归必须走 `--segment-size 25 --replan-every 5` 滚动 append 路径（真模型无此形态）；心跳语义分层要反复讲清：心跳测 **driver 进程**、child 卡死由 step 超时兜（此时心跳仍在跳）。

**下轮候选（iter077）**：**真模型 capstone 实跑**（10-20 章，铁律⑥需用户授权）。建议配置：`on_soft_reject=caveat_continue + max_panel_rejections=2 + tier=mid + --budget-cny <软阈>`；入口 `nohup bash scripts/drive_book_supervised.sh --book longzu --confirm-real-smoke -- --chapters 20 --tier mid --budget-cny 300 ... &` + 另终端 `bash scripts/watchdog.sh --book longzu --driver`。其它 backlog（Aeloon 深色模式 / drama ③④ / SQLite FTS / char-level diff / mock planner --chapters）不变。

**数据状态**：只 commit 不 push，等用户验收（铁律⑤）。commit：`fix(iter076a)`=`476318c`（codex 修复批）+ `feat(iter076)`（本轮硬化+审查修复，待本 Phase Status 同 commit 落盘）。

---

## Phase Status — iter 077（2026-07-03 收官）：长跑审查修复批——六方审查 P0 五项（capstone 前置硬门）

**已完成（本轮）**：立项来源为六方并行只读审查（6 subagent 独立视角：断点续跑/无界增长/预算超时心跳/错误路径/并发信号进程/配置一致性 + codex 报告交叉对照，~40 项分级 P0×5 / P1×8 组 / P2），P0 全修——① **伏笔 TTL 闸门 ch16 确定性封死**：`build_registry` 把源书遗留伏笔全播种为 `planted_chapter=0, ttl=12, must_resolve=True` 且流水线无自动 resolve 路径 → `resume_from≥14` 必 blocker、`--force` 清不掉、mock 恒空零覆盖；修法=读取侧 `overdue_must_resolve` 默认豁免 `planted_chapter<=0` 边界项（存量 registry 零迁移）、readiness 降级 `foreshadowing_boundary_overdue` warning、preflight 分列闸门项/遗留项、unparseable/续写新种保持 fail-closed、mock extraction 补非空 fixture；② **caveat×resume 双断点**：readiness 逐章循环豁免 `caveat_approved`（此前 caveat 章任一重启后 resume 必 exit 4 终态）+ `_mark_caveat_approved` 原子归档 failure.json 为 `*.failure.caveat.json`（chapter_status 的 `not failure` 语义保持连贯）；③ **panel_block_policy 静默回落**：显式坏值/yaml bool/caveat_continue+max≤0 矛盾组合 → `config_warnings`+stderr、`_snap` 每快照回显生效策略、preflight `_check_panel_block_policy` 前置校验（惰性 import 避环形依赖）；④ **孤儿 write-book 双写**：`_reap_orphan_child`（TERM→宽限→KILL、cmdline 判别防 pid 复用误杀）挂入 `cmd_resume`/`cmd_start`；`_run_step` Popen 段 try/finally 无条件收割 + timeout 先杀后 emit + Popen 前/切片内 `_STOP_REQUESTED` 检查（三条成孤路径全堵）；⑤ **stale 拒稿残迹**：`_is_resumable_stale_reject` 白名单判定（指纹一致的中断期拒稿走 attempt>0 同款归档+重写+播种拒因；mismatch/legacy/human 保持 BookRunBlocked）+ readiness 同口径 `stale_reject_will_rewrite` warning + `reviewed_existing` 补外审被拒接入 panel_block_policy。

**铁律⑨（升级条款：runner/driver 高风险）**：`/code-review high` 8 finder 视角（6 完成、逐行/跨文件 2 个撞账号会话限额——被删行为视角已做逐 hunk 审计、跨文件已由立项前六方审查覆盖；候选本体 inline 核验）→ **1 bug 级 CONFIRMED 当轮直修批（+8 tests）**：`panel_halted` 落盘标记使 halt 分诊结论跨进程存活（lint 终败/retry 耗尽章 resume 不再静默重烧）、stale 谓词补 `failure`/`panel_halted`、`.failure.caveat.json` 进归档 suffix、reaper 记录 `state["child_cmd"]` 精确比对 + ps 失败不放行第二写者 + EPERM=非亲儿子、`cmd_stop` 孤儿收割统一走 reaper。`/security-review` **零发现**（subprocess argv list+int 强转 / killpg 目标全出自本方 state / 文件名 `:02d` 无穿越 / `sk-`·`.env` grep 零命中 / 无新反序列化面；铁律①②干净）。**未修技债**：处置五分类（skip_approved/skip_caveat/补外审/stale 重写/block）下沉 `chapter_status` 单一真源（本轮谓词漏 `failure` 即平行维护实证）、foreshadowing 播种改显式 `origin` 字段（防未来续写回灌 compress 使闸门静默失效）、caveat 分诊块两处同构、`_snap` 基底 payload、registry 双读等——全记 iteration_077 Notes/Acceptance Result。

**验收证据**：`.venv` unittest discover **1517 tests OK**（1475 → P0 批 1509 → 审查修复 +8；含 test_book_runner 2 用例语义迁移 + test_foreshadowing/047B2 共 7 用例 fixture 迁移，原命题全保留）；verify 仅 3 个既有环境性 error（system python3.9 PEP604 ×2 + 缺 tiktoken，同 iter076）；preflight ok（新增 panel_block_policy 生效值 info）；mock 25 章回归三关全过（succeeded 25/25 / resume 零新调用 369 行不变 / supervisor --resume-first exit 0）+ 新增 **PASS-1b**：对真 workspace `write-readiness --chapters 5 --resume-from 16` = `warn` + `foreshadowing_boundary_overdue:2` 零 blocker——修复前该形状确定性杀死 capstone。

**教训**：①mock 的 graceful degrade（铁律④）会让 fail-closed 闸门在 mock 回归中零覆盖——可选数据源的 mock fixture 应至少给一份非空样本，「25 章 mock 全过」才对相应闸门有背书力；②打桩过深的单测（`_load_chapter_plan`→None）同理绕过生产路径；③readiness 与 run_write_book 的处置逻辑是两条手工同步的平行链，第三次同步改动时果然漏了一个字段（`failure`）——下沉单一真源是结构解；④管道后 `$?` 取的是最后一个命令的退出码——查 verify.sh 这类脚本状态要 `pipefail` 或分开跑。

**下轮候选（iter078，路线图收官步）**：真模型 capstone 实跑（10-20 章，铁律⑥需用户授权；建议 `on_soft_reject=caveat_continue + max_panel_rejections=2 + tier=mid`；跑前按 iteration_077 Notes 清单：打印生效 policy / 清 WRITE_REVIEW_TIER 等 env 脏值 / 干净 workspace 或对 mock 排练章 --force / 确认 continuation_anchor.txt / `--budget-cny` 空格形式且 >0 / watchdog 用 --driver 不带 --pid / 长跑期间 dashboard 只读 / 人工干预先停 supervisor 再 stop）。或先修六方审查 P1 八组（reviewer NaN crash+字符串分数 fail-open / Web-CLI workspace 写锁 / 预算账本三重失真 / entity 三连 / rolling 落盘顺序 / 指纹补 model·tier / tiktoken 中文计数 / env·preflight 守门盲区）。

**数据状态**：只 commit 不 push，等用户验收（铁律⑤）。改动：src/{book_runner,book_driver,chapter_status,foreshadowing,llm_client,preflight}.py + 3 个新测试文件 + 4 个测试文件迁移 + iteration_077 + 索引 + README SOP + AGENTS.md + 本文件。

---

## Phase Status — iter 078（2026-07-05 收官）：六方审查 P1 修复批（8 组）+ 技债 2 项

**已完成（本轮）**：承接 iter077 六方审查 P0 后的 P1 清单，一轮清掉 capstone 前大部分人工规避项。八组 P1：① reviewer 分数护栏（NaN/Inf/bool 拒收，纯数字字符串 coerce，weighted/判定链路 isfinite，异常分数留 `score_warning`）；② workspace 写锁（`src/workspace_lock.py`，CLI/Web/auto-pipeline 写入口 flock 互斥 + holder 回显）；③ rolling summary 改 persist→rolling，readiness gap warning，fresh-write 前 prune；④ entity 三连（空 new_state fail-closed、第 5 注入点 16K 截断、`advance_applied` sidecar + skip 补偿）；⑤ run_context 指纹补 model + review_tier；⑥ 预算账本按 model 前缀逐 record 计价，retry_error 逐 attempt 入账，dirty_lines 计数；⑦ deepseek CJK token 估算只减不增 + 已知前缀 64K 动态 cap；⑧ preflight 补 tier/timeout/context/anchor 守门。两项技债：foreshadowing 播种显式 `origin`；处置五分类下沉 `chapter_status.classify_disposition` 单一真源。

**铁律⑨审查与追加修复**：8 finder 视角 + 主对话 inline verify，直修 8 项：reaper argv[1:] 尾部比对、readiness tier 意图、SUPPLEMENT 两出口补偿、entity recency 守门、缺 `planted_chapter` fail-closed、负 timeout 拒收、标量 JSON 残行计脏行、Web/auto-pipeline 写锁覆盖。高风险升级另跑 2 个独立视角：安全视角发现 `llm_client._log_call` 原始异常可能泄 key/prompt → `_sanitize_error_text` 脱敏 configured key/Bearer/sk/prompt/messages/input/content 并加测；并发/driver 视角确认 `cmd_stop` 收割结果 reload 前未落盘、`drive-book resume --tier` 被忽略、run-all/auto-pipeline/review 锁范围不足 → 全修并加测。`rg sk-` 命中均为测试假 key 或历史文档占位；未碰 `.env`/`data`/`outputs`/`小说txt`。

**验收证据**：`.venv/bin/python3 -m unittest discover -s tests` **1622 tests OK**（需允许本地 127.0.0.1 测试端口；裸沙箱会拦 `test_novel_client`）；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 1622 tests OK，随后 normalize/split/auto-pipeline/status/manifest/report/cost 全跑通）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL（WARN 为当前 `.env` 模型配置、cache provider、预算默认值提示）；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN；`git diff --check` 与 py_compile 均通过。mock 25 章五关回归全过：start / resume-from 16 readiness / resume 零新调用 / supervised resume-first / 双 write-book in vivo 竞锁。

**残留风险（P2/技债）**：writer persist 后、提案落盘前死亡窗口仍可能出现「章 approved 但提案缺失」（rolling 有 warning，entity 无源可补）；旧 halt 残迹无 `panel_halted` 一次性迁移形态需首跑前人工核查；mock 计价归零导致预算闸错接线只能在真模型暴露（候选：mock 假单价开关）；Web 手工编辑端点仍未桥接 flock；reaper argv[1:] 尾部匹配仍有极端 wrapper 边界；`_STOP_REQUESTED` 为进程级 flag，CLI 低风险、嵌入式复用可后续 reset；若干复用/简化/效率项见 iteration_078 Notes。

**下轮候选（iter079+）**：短剧（drama）模块批次按 `docs/iterations/iteration_079_083_drama_module_roadmap.md` 推进（079 分镜 grid / 080 角色+AI 绘画骨架 / 081 drama_reviewer+episodes / 082 导出+Insights / 083 真模型收口）。小说主链路 capstone 实跑仍是独立候选（10-20 章，铁律⑥需授权；建议 `on_soft_reject=caveat_continue + max_panel_rejections=2 + tier=mid`，跑前核查旧 Reject/halt 残迹、预算口径、workspace 清洁度、watchdog `--driver`）。

**数据状态**：iter077 与 iter078 改动历史上混在同一工作区，按用户拍板合并一个 commit；只 commit 不 push，等用户验收（铁律⑤）。

---

## Phase Status — iter 079（2026-07-06 收官）：Capstone 前写锁与预算硬化（P2）

**背景**：iter078 后 subagents + 本地核验结论一致：当前没有确认“已发现但未修”的 P1/High；本轮按 P2 hardening 包处理最贴近 capstone 长跑生产风险的边界，不把 P2 包装成 P1，也不跑真模型 smoke。

**已完成（本轮）**：① Web 手工写端点桥接 `workspace_lock`：draft/outline/KB/start-point/chapter-plan/entity/relationship/writer-style/premise/drama 保存等 `workspace_reserved` 写路径统一进入 `_workspace_write_guard`（进程内 reservation + 跨进程 flock），CLI/driver 写作期间返回 409 且文件不落盘；既有 Web job reservation `workspace busy` 409 shape 保持不变。收尾补线：writer-style/extract 上传暂存阶段也先拿 flock，CLI 长跑持锁时 409、不落临时样本、不排 job；extract-style worker 写 `writer_style.json` 前再拿 flock，锁冲突转 Web-safe blocker。② CLI `apply-advance` 获取写锁，与 write-book auto-advance 互斥；锁冲突打印本地诊断并 exit 4，不进入 `apply_advance_cli`，`entity_graph.json` 不变。③ readiness 对 approved/caveat skip 章新增 `entity_proposal_gap:NN` warning：缺 `advance_applied` sidecar 且缺 proposal 文件才提示；有任一补偿源不告警，只 warn、不 blocker、不触发 LLM；收尾补 `resume_from-1` 前章同口径检查。④ mock 预算演练开关 `MOCK_COST_CNY_PER_1K_TOKENS`：仅正有限值生效，默认 mock 成本仍为 0，坏值/NaN/0 回退 0。⑤ 审查修复：Web 409 lock holder 与 Web job JSON 不再回显 `WorkspaceLocked` 原始诊断（绝对 path/argv），只返回 `holder.source` / `holder.started_at` 摘要；完整诊断仍留 CLI/driver 本机路径。

**铁律⑨审查**：按用户要求起 2 个只读 subagent 收尾复核。Security 发现 1 个 Medium：Web job status/detail/recent 仍可能暴露 raw `WorkspaceLocked` 诊断（绝对 `write.lock` path/argv）→ 修为 `workspace locked` + `holder.source/started_at` allowlist，并覆盖 `write-book`、`review-chapter`、`draft-once-dev`、`extract-style`；此前 Web 手工 409 `holder` 原始诊断泄漏也已修。Correctness 发现 1 个 P2：`resume_from=2` 只检查前一章 rolling gap、不检查 entity proposal gap → 补 `resume_from-1` approved/caveat 章 warning。两项均已修并加测，无剩余 P1/P2 blocker。`rg` 本轮 diff 无 `sk-`/`.env`/真实 key 新增命中；未触碰 `.env`/`小说txt` 原文。真模型 smoke 未跑（铁律⑥）。

**验收证据**：`git diff --check` 通过；`py_compile` 覆盖 `main.py src/book_runner.py src/cost_estimator.py src/web/jobs.py src/web/routes.py tests/test_iter079_capstone_hardening.py tests/test_web_jobs_dispatch.py tests/test_web_writer_style.py` 通过；聚焦 `tests.test_iter079_capstone_hardening tests.test_web_jobs_dispatch tests.test_web_writer_style` **60 tests OK**；`.venv/bin/python3 -m unittest discover -s tests` **1633 tests OK**（skipped=6）；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1633 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN。

**残留风险（P2/技债）**：reaper nonce / heartbeat token 判别式、`_STOP_REQUESTED` 嵌入式复用 reset、旧 halt 残迹一次性迁移继续顺延；小说真模型 capstone 仍需用户授权实跑；drama 站③路线图未在本轮启动。

**数据状态**：改动集中在 `src/web/routes.py`、`main.py`、`src/book_runner.py`、`src/cost_estimator.py`、`tests/test_iter079_capstone_hardening.py` 与迭代文档/README/AGENT_HANDOFF；未跟踪 `续写工作台.pptx` 视为用户文件，保持不动；只 commit 不 push，等用户验收（铁律⑤）。

---

## Phase Status — iter 080（2026-07-08 收官）：短剧站③分镜生成 + Grid 编辑器

**背景**：Iteration 079 已被 capstone P2 占用并收官；短剧路线图原“079 站③分镜 + grid 编辑器”按仓库最新索引平移为实际 iter080。本轮不改路线图原文，不跑真模型 smoke，不触碰 `.env`/`小说txt` 原文。

**已完成（本轮）**：新增 `src/drama_schemas.py` 与 `src/storyboard_builder.py`，定义 `StoryboardShot` / `DramaStoryboard` / `DramaEpisodePaths` / `episode_paths()` / `validate_storyboard_soft()` / `validate_storyboard_hard()`，站③ runner 支持 5 赛道 mock fixture 与 `LLMClient("drama_storyboard").complete_json(...)` 真模型 wiring（未实跑）。新增 `prompts/drama/storyboard_builder.txt`、`config/models.yaml` 的 `drama_storyboard`、`config/agents.yaml` documentation-only 配置。Web/API 新增 GET/POST/PUT `/api/workspace/<name>/drama/storyboard` 与 POST `/rewrite-shot`，drama-only、站②缺失 400、写入走 `_workspace_write_guard` + `write_json`；站③ tab 解锁为原生 grid，支持景别/运镜/时长/画面/旁白/台词/高光、上移下移、保存整表、重生本镜与总时长 footer，站④继续 locked。新增 5 个原创 storyboard fixtures（6-9 镜、60±3 秒、首镜/末镜规则、单句台词长度、无龙族专名），mock 重生用 `alt_shots`，持久化不保留。

**铁律⑨审查与追加修复**：按用户要求使用 2 个只读 subagent 做 `/code-review high` 与 `/security-review`。代码审查确认并已修 4 项：Web 生成/重生在真实配置态可能误触真模型 → iter080 Web 站③固定 mock-only；`rewrite_shot()` 真模型 prompt 缺当前 storyboard 上下文 → 补 bounded current context；progress 只看 `shots>=6` 可能把双高光坏文件标 done → 改 schema + hard validation；双高光硬拒从 route 下沉为 `validate_storyboard_hard()` 并接入 builder/route/view。安全审查确认并已修 3 项：RuntimeError 可能把 provider/prompt/key-like 内容回 JSON → 改 generic `server_error` card + 日志脱敏；客户端可伪造/持久化超长 `hook` → schema 限长且 PUT/run/rewrite 统一使用站②服务端 hook snapshot；Web API 误触真模型风险同上改 mock-only。无剩余 P1/P2 blocker；残留仅为站③真模型 smoke、job 化与站①②真模型补课按路线图留 iter083。

**验收证据**：聚焦回归 `tests.test_drama_storyboard_builder tests.test_drama_storyboard_grid tests.test_drama_view tests.test_drama_fixture_lint tests.test_workspace_overview_drama tests.test_web_routes_get` **115 tests OK**；`py_compile src/drama_schemas.py src/storyboard_builder.py src/web/routes.py src/web/drama_view.py` OK；`.venv/bin/python3 -m unittest discover -s tests` **1661 tests OK**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1661 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok；`git diff --check` 通过；新增 diff 未发现 `sk-...` 形态。真模型 smoke 未跑（铁律⑥）。

**记忆更新**：`AGENTS.md` 新增迭代工作流约定：每轮 implementation iteration 必须显式使用 `iter-start` 与 `iter-finish` 两个 skill；实现时可适当使用 subagents 节约主窗口上下文，但 subagents 同样不得触碰 `.env`/`data`/`outputs`/`小说txt`，也不得跑真模型 smoke。

**下轮候选（iter081+）**：短剧站④角色 + 角色库 + AI 绘画骨架；drama_reviewer + episodes；导出 + Insights；iter083 真模型收口批（站①②补课、站③真模型 smoke、每站 job 化、`scripts/drama_smoke.sh`，需授权）。小说主链路 capstone 仍是独立候选，10-20 章真模型长跑需用户明确授权。

**数据状态**：本轮新增/修改集中在 drama schema/runner/prompt/config、Web route/static/template/view、测试 fixture 与迭代/README/AGENT_HANDOFF/AGENTS 文档；`verify.sh` 仅按既有流程写 gitignored `data/`/`outputs/` 验证产物；未跟踪 `续写工作台.pptx` 视为用户文件，保持不动；只 commit 不 push，等用户验收（铁律⑤）。

---

## Phase Status — iter 081（2026-07-09 收官）：短剧站④角色 + 角色库 + AI 绘画骨架

**背景**：Iteration 080 已交付短剧站③分镜 grid；本轮按路线图继续补站④角色设定表、角色库页面与 AI 绘画安全骨架。Web 生成/重画本轮仍固定 mock-only，不跑真模型 smoke，不调用真实绘图 API。

**已完成（本轮）**：新增 `character_paths()`、`ReferenceImage`、`DramaCharacter`、`CharacterSheet`，角色表固定落盘 `data/characters/season_01.json`，引用图限制在 workspace 内 `data/character_refs/<cid>/...`。新增 `src/character_designer.py` 与 `prompts/drama/character_designer.txt`，从站② setup + 站③ storyboard 生成角色设定；5 赛道 mock fixture 全原创，真模型仅 wiring 到 `LLMClient("drama_character").complete_json(CharacterSheet)`。`merge_character_sheet()` 按 id 合并：`manual_override=true` 的旧角色保留原字段，新 agent 结果进 `agent_suggestions[]`；未锁定角色允许覆盖但保留既有 `reference_images`；新角色追加。新增 `src/ai_draw_client.py`：`AI_DRAW_ENDPOINT` 缺省或 Web mock 路径零网络写 deterministic SVG placeholder；真实 endpoint 骨架含 http/https、30s timeout、5MB 上限、Authorization header 注入。Web/API 新增角色表 GET/POST/PUT、`POST /characters/<cid>/redraw`、`GET /character-ref/<cid>/<filename>`、`/w/<name>/characters` 角色库页；写作页解锁 `#characters` deep-link，渲染角色卡、prompt 编辑、锁定 checkbox、保存、重新生成与 placeholder 重画；settings allowlist/secret mask 接入 `DRAMA_MODEL`、`AI_DRAW_ENDPOINT`、`AI_DRAW_API_KEY`；`config/models.yaml` 增加 `drama_character`。

**铁律⑨审查与追加修复**：2 个只读 subagent 并行。Correctness 视角无 blocker，发现 2 个 P1 + 2 个 P2；已修 P1「锁定角色连续重生成导致 `agent_suggestions` 超 schema 上限后 400」与 P1「未锁定角色重跑丢 `reference_images`」，并修 P2「未知 content-type 写 `.bin`」。P2「Web redraw 固定 `mock=True`」与本轮计划一致，保留并文档化。Security 视角无 HIGH，发现 3 个 MED；已修 `AI_DRAW_ENDPOINT` SSRF 风险（公网地址校验）、真实绘图 SVG/未知类型落盘风险（仅 PNG/JPEG/WebP）、`character-ref` 一次性读取无限文件风险（扩展名白名单 + 5MB cap）。未发现 API key / `.env` 泄漏；未碰 `.env`/`小说txt` 原文；真模型/真绘图 smoke 未跑（铁律⑥）。

**验收证据**：聚焦站④回归 `tests.test_drama_character_designer tests.test_drama_characters_api tests.test_drama_fixture_lint tests.test_drama_view tests.test_web_routes_get tests.test_web_settings` **121 tests OK**；`py_compile` 覆盖触达模块 OK；`.venv/bin/python3 -m unittest discover -s tests` **1685 tests OK**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1685 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过；LiteLLM 远程 cost map timeout fallback 为非阻断 warning）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN；`node --check /tmp/iter081_app.js`、`git diff --check` 均通过。

**残留风险 / 下轮候选**：drama_reviewer + episodes、导出 + Insights、第 2 集重生、站①②/③/④真模型 smoke、每站 job 化、`scripts/drama_smoke.sh` 仍顺延到 drama 后续批；真实 AI 绘画 API 只完成安全骨架，未做可用性实测；小说主链路 capstone 真模型长跑仍需用户明确授权。

**数据状态**：本轮新增/修改集中在 drama schema/runner/prompt/config、Web routes/static/templates/view/settings、测试 fixture 与迭代/README/AGENT_HANDOFF 文档；`verify.sh` 仅按既有流程写 gitignored `data/`/`outputs/` 验证产物；未跟踪 `续写工作台.pptx` 视为用户文件，保持不动；只 commit 不 push，等用户验收（铁律⑤）。

---

## Phase Status — iter 082（2026-07-09 收官）：短剧 drama_reviewer + 整集组装 + episodes 页

**背景**：Iteration 081 已交付短剧站④角色、角色库与 AI 绘画安全骨架；本轮承接短剧路线图中原“drama_reviewer + 整集组装 + episodes 页”节点。因前序编号平移，路线图原“iter082 导出 + Insights + 第 2 集重生”顺延到后续。本轮不跑真模型 smoke，不调用真实绘图 API，不触碰 `.env`/`小说txt` 原文。

**已完成（本轮）**：新增 `DramaReview` / `DramaSubScores` / `AdvisorSuggestion` / `DramaEpisode` / `DramaEpisodeMeta`，5 维子分本地确定性 verdict（任一 `<5` Reject，全 `>=7` Approve，其余 Abstain），分数护栏覆盖 bool、非数字、NaN/Infinity 与越界 clamp，parse failed 特判 Abstain + `needs_human_review=true`。新增 `src/drama_reviewer.py` 与 `prompts/drama/drama_reviewer.txt`，mock 走 5 赛道原创 review fixtures，真模型仅 wiring 到 `LLMClient("drama_review")`（未实跑），Web review 端点固定 mock-only。新增 `src/drama_store.py`，把 setup/storyboard/characters/review 组装为 `outputs/episodes/episode_01.json` 与 `.meta.json`，meta 记录 input fingerprint 并支持 stale 检测。Web/API 新增 `/api/workspace/<name>/drama/{review,assemble,apply-suggestion,episodes,episode/1}`、`/w/<name>/episodes` 与 `/w/<name>/episode/1`，站④新增“评审并组装”CTA，episode detail 提供剧本/分镜/角色/评审/导出占位 tabs 与 suggestion apply。

**铁律⑨审查与追加修复**：2 个只读 subagent 并行完成 correctness 与 security/boundary review。Correctness 发现 2 项有效问题并已修：真实 reviewer exception fallback 原会把 `parse_failed_review()` dict 交给 `model_to_dict` 崩溃，已改为直接返回 Abstain payload 并补测；`episode_no=1.9` 原会被 `int()` 截断到 1，已改为 strict positive integer 解析并补测。Security/boundary 未发现 API key / `.env` 泄漏、未发现 tracked diff 触碰 `.env`/`data`/`outputs`/`小说txt` 或 Web 真模型误触；提醒未跟踪 `续写工作台.pptx` 是 61MB 二进制且有版权边界风险，本轮保持不 staged、不提交。

**验收证据**：聚焦回归 `tests.test_drama_reviewer tests.test_drama_store tests.test_drama_episodes_api tests.test_drama_fixture_lint tests.test_web_routes_get` **108 tests OK**；`py_compile` 覆盖触达模块 OK；`node --check /tmp/iter082_app.js` OK；`.venv/bin/python3 -m unittest discover -s tests` **1707 tests OK**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1707 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过；LiteLLM 远程 cost map timeout fallback 与 `botocore` 缺失为非阻断 warning）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN；`git diff --check` 通过。

**残留风险 / 下轮候选**：导出四格式、Insights、第 2 集重生、站①②/③/④/Reviewer 真模型 smoke、每站 job 化、`scripts/drama_smoke.sh` 仍顺延到 drama 后续批；真实 AI 绘画 API 仍未做可用性实测；小说主链路 capstone 真模型长跑仍需用户明确授权。

**数据状态**：本轮新增/修改集中在 drama schema/reviewer/store/prompt/config、Web routes/static/templates、测试 fixtures 与迭代/README/AGENT_HANDOFF 文档；`verify.sh` 仅按既有流程写 gitignored `data/`/`outputs/` 验证产物；未跟踪 `续写工作台.pptx` 视为用户文件，保持不动；只 commit 不 push，等用户验收（铁律⑤）。

---

## Phase Status — iter 083（2026-07-09 收官）：量化文风指纹 Baseline v1

**背景**：新路线图 `docs/iterations/iteration_083_086_style_fingerprint_roadmap.md` 要把“风格”从 prompt 软约束推进到可复测的量化闭环。本轮只做 iter083 baseline v1，不接 writer/reviewer，不做 drift severity，不做 Web UI，不跑真模型 smoke。

**已完成（本轮）**：新增 `src/style_fingerprint.py` 与 `config/style_fingerprint.yaml`，提供纯本地、确定性、版权安全的文风指标计算。`style-fingerprint build-baseline` 从用户本地 `data/style_examples/*.md` 读取样本，写 `data/style_fingerprint/baseline.json`；artifact 只存 `metrics`、`dimension_stats`、`dimension_reliability`、`tolerance`、`weights`、`baseline_quality`、`sample_count`、`source_labels`、`source_hashes`、`baseline_hash/hash`，不存原文片段。缺目录、无样本或样本不足时返回并写入 `status=insufficient_source`，不报错、不制造假 0 baseline。新增 `style-fingerprint inspect-draft --chapter N`，对 `outputs/drafts/chapter_NN.md` 输出与 baseline 同形指标，不依赖 baseline 存在。指标覆盖句长均值/p50/p90、短句/长句比例、段长、对话占比、标点密度、对比句频、AI 腔词密度、感官/意象词密度、解释连接词密度等维度。`src/paths.py` 新增 `style_fingerprint_dir()` 与 `style_fingerprint_baseline_path()`，兼容 legacy/workspace。

**铁律⑨审查**：只读 code review 未发现 blocker；核对重点为 baseline contract、insufficient source 不落假零、hash 稳定性、CLI 薄封装、path helper workspace 兼容、未接 writer/reviewer/Web/drift severity。security review 未发现 API key / `.env` 泄漏路径；无 LLM 调用；baseline JSON 不持久化 sample 文本、句子、段落或 excerpt；测试只用合成文本和临时目录。运行时唯一新增写入为用户显式执行 `build-baseline` 时的统计 artifact。

**验收证据**：聚焦 `tests.test_style_fingerprint tests.test_paths` **23 tests OK**；`.venv/bin/python3 -m unittest discover -s tests` **1712 tests OK**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1712 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过；本轮经用户授权，`verify.sh` 写 gitignored `data/`/`outputs/` 验证产物不视为手工触碰私有内容）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN；`py_compile` 与 `git diff --check` 均通过。真模型 smoke 未跑（铁律⑥）。

**接力点（iter084-086）**：iter084 可直接读取 `baseline.json` 的 `metrics/dimension_stats/tolerance/weights` 做 draft 对比、drift score/severity 与 meta 写入；样本不足时继续 graceful degrade。iter085 把偏离维度映射成 reviewer advisor / writer feedback 可消费的 rewrite directives，不要重做 baseline schema。iter086 只在 severity 明确时做 red drift 定向重写和复测。本轮没有任何自动重写入口。

**数据状态**：新增/修改集中在 `src/style_fingerprint.py`、`config/style_fingerprint.yaml`、`main.py`、`src/paths.py`、`tests/test_style_fingerprint.py`、`tests/test_paths.py` 与迭代/README/AGENT_HANDOFF/AGENTS 文档。`iteration_083_086_style_fingerprint_roadmap.md` 为路线图交接文档；未跟踪 `续写工作台.pptx` 是用户文件，保持不动；不 push。

---

## Phase Status — iter 084（2026-07-09 收官）：文风漂移检测 + 告警

**背景**：承接 `iteration_083_086_style_fingerprint_roadmap.md`。iter083 已有版权安全 baseline artifact 和 draft 指标检查；本轮只做 drift 检测、score/severity、meta 留痕、CLI 报告与 Web 只读展示。不做 rewrite directives、不自动重写、不阻断 readiness/write-book、不接 `panel_block_policy`，不跑真模型 smoke。

**已完成（本轮）**：新增 `src/style_drift.py`，读取 baseline 的 `metrics/tolerance/weights/dimension_reliability/baseline_hash`，按 `normalized_delta = min(abs(current - baseline) / tolerance, 3.0)` 与 `dimension_score = normalized_delta / 3.0` 计算 `style_drift_score`，severity 固定为 `ok <0.35`、`warn >=0.35`、`red >=0.55`。baseline 缺失、`insufficient_source`、字段不完整或无可比较维度均返回 `status/severity=skipped` 且 score 为 null；缺维度、低可靠度、缺 tolerance、缺/坏 weight、非有限值进入 `skipped_dimensions`，不当 0 分。新增 `style-drift --chapter N` 合并写入已有 `chapter_NN.meta.json`（不创建半 meta）与 `style-drift-report [--limit N]`（按 `chapter_no` 降序取最近窗口）。writer 成功与 lint-failure 两条持久化路径写入 `style_fingerprint/style_drift/baseline_hash`，但不改变 `verdict`、`needs_human_review`、`rewrite_count`、`draft_sha256`；skipped 复测会清理旧 `baseline_hash`。Web 章节详情增加文风 badge 与“文风”tab，只展示 severity、score、baseline hash、top/skipped dimensions 等数值指标。

**铁律⑨审查**：按用户要求补跑 2 个只读 subagents 并行审查，并把该要求固化进 `AGENTS.md` 与全局 `iter-finish` skill，后续每轮收官默认至少 correctness + security/boundary 两个 subagent。correctness subagent 发现 3 项有效问题并已修：缺/坏 `weights` 被默认 1.0、skipped 后旧 `baseline_hash` 可残留、`sample_count=Infinity` 可让 CLI 崩溃。security/boundary subagent 无安全 blocker，确认未改 `.env`、未跑真模型、未触碰 `小说txt/`，新增 meta 只保存统计量/hash/reason，不持久化 baseline 样本或 draft 原文，Web 动态字段 escape；残留提醒为 manual `style-drift --chapter` 设计上会写已有 meta，与 writer 并发时仍可能 last-writer-wins。

**验收证据**：`tests.test_style_drift` **10 tests OK**；受影响测试集 `tests.test_style_drift tests.test_writer tests.test_web_routes_get tests.test_static_subscore_compat` **115 tests OK**；`.venv/bin/python3 -m unittest discover -s tests` **1723 tests OK**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1723 tests OK**，随后 auto-pipeline/status/manifest/report/cost 全过）；`.venv/bin/python3 main.py preflight` = warn/无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN；`git diff --check` 通过。真模型 smoke 未跑（铁律⑥）。

**接力点（iter085-086）**：iter085 可消费 `style_drift.top_dimensions`、`skipped_dimensions` 与 `basis.baseline_hash` 映射 rewrite directives；skipped 不应当作绿灯。iter086 再做 red drift 定向重写与复测。短剧导出/Insights/第 2 集重生与小说主链路 10-20 章真模型 capstone 仍需用户授权后独立推进。

**数据状态**：新增/修改集中在 `src/style_drift.py`、`main.py`、`src/writer.py`、`src/web/{static,templates}.py`、`tests/test_style_drift.py`、writer/Web 测试与迭代/README/AGENT_HANDOFF/AGENTS 文档。`verify.sh` 仅按既有授权写 gitignored `data/`/`outputs/`/`logs` 验收产物；未跟踪 `续写工作台.pptx` 是用户文件，保持不动；不 push。

---

## Phase Status — iter 085（2026-07-10 收官）：文风偏离到定向改写建议

**背景**：iter083/084 已形成纯本地 baseline 和 drift score/severity/meta/Web 告警。本轮把“哪个统计维度偏了”转成 reviewer/writer 可直接消费的结构化 guidance，不自动增加重写轮，不改 verdict/hard reject/readiness。开工前 iter084 已独立复验并提交为 `477c32c`。

**已完成（本轮）**：新增 `StyleTargetRange` / `StyleRewriteDirective`，目标区间和当前值必须非负、有限且有序。`style_drift.build_rewrite_directives()` 对 warn/red `top_dimensions` 按 weighted delta 稳定排序，仅当 current 严格越过 baseline±tolerance 时生成最多 5 条 guidance；覆盖句长、短句、对话、解释连接词、对比句和 AI 腔。`reviewer.review_text()` 在投票已确定后追加 `_advisor=style_drift_advisor` 建议，不新增 LLM 调用；writer 既有前 5 条通道为 plan/style/原 advisor 保留配额，Web 复用 Advisor tab 安全渲染。

**铁律⑨审查与追加修复**：correctness 只读 subagent 发现 2 项：区间内维度会误发 red directive；5 条 style 建议会吞掉 `plan_compliance` 与原 advisor。已分别改为严格 tolerance 越界与跨 advisor 保留配额。security/boundary 只读 subagent 发现 1 项 P2：两个有限大数相加仍可溢出 Infinity，旧 target range dict 也过宽；已补算术后 finite 守门、固定 schema 和真溢出测试。两个 subagent 复核均通过，无残留 blocker/P2。

**验收证据**：聚焦 54 tests OK；`.venv/bin/python3 -m unittest discover -s tests` **1738 tests OK**（288.003s）；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部 **1738 tests OK** / 253.748s，随后 auto-pipeline/status/manifest/report/cost 全过）；真实配置 preflight = warn/无 FATAL；mock preflight = ok/无 WARN；`git diff --check` 通过。真模型 smoke 未跑（铁律⑥）。

**残留风险 / 下轮候选**：iter086 才实现 red drift 自动定向重写、重写后复评分与 unresolved 留痕；本轮 `section_hint` 是统计维度对应的段落类型提示，不伪造精确原文 anchor。短剧导出/Insights/第 2 集重生/真模型批和小说 10-20 章 capstone 仍是独立候选，真模型需用户授权。

**数据状态**：本轮改动集中在 `src/{schemas,style_drift,reviewer}.py`、directive/reviewer/writer/Web 测试与迭代/README/AGENT_HANDOFF/AGENTS 文档。`verify.sh` 仅写 gitignored 验收产物；未跟踪 `续写工作台.pptx` 是用户文件，保持不动；不 push。

---

## Phase Status — iter 086（2026-07-10 收官）：文风漂移可靠性修复与 Web 防御纵深

**背景**：iter083-085 已形成 baseline、drift score/severity/meta/Web 告警和确定性 advisor，但收官复现确认严重漂移仍可能被极大有限权重溢出误判为绿色，短单样本 baseline 会假成功，hash/version、手工 CLI 并发、历史坏 meta 与章节详情 Web 仍有防御缺口。本轮将原定 red 自动重写顺延，先修其可靠性前置。

**已完成（本轮）**：指纹升级为 `local-stat-v2`：单换行按非空物理段落统计；source 门槛通过但 reliability=low 时返回 `insufficient_source/low_reliability` 空指标；v1 baseline 明确 `incompatible_version` 并要求重建。baseline identity 使用 strict canonical JSON，`baseline_hash/hash` 双别名必须齐全、一致且匹配重算，缺失/分叉/篡改/NaN/Infinity 均 `invalid_hash`；新 artifact 不再记录样本文件名或逐样本原文 digest。drift 聚合按最大 weight 缩放并 `math.fsum`，多个 `1e308` 不再产生 `Infinity/NaN→0/ok`；Advisor 瞬时获取全维度后过滤、meta 仍 top-5；报告清洗坏历史 score/维度为严格 JSON；invalid/incompatible hash 不再传播到 meta；`style-drift --chapter` 在 CLI 外层持有完整读算写窗口的 workspace lock。Web 修复 `#style` 刷新、六面板失败态、编辑禁用、null/坏数组、未检测/已跳过、Advisor 来源，并为共享 tabs 补齐 ARIA/hidden 与 Home/End/四方向键 roving focus。

**铁律⑨审查与追加修复**：correctness、security/privacy、Web/integration 三个独立只读 subagent 完成首审与修后复核。Correctness 发现非有限 schema_version 穿透严格 JSON、invalid/incompatible hash 仍回写 meta、单 alias 未 fail-closed、`_safe_float` 超大整数 OverflowError；全部修复并复核 GO。Security/privacy 发现单 alias 接受与 baseline canonical JSON 允许 NaN/Infinity；改为双 alias 必需 + `allow_nan=False`，复核 PASS，确认 artifact 不含样本名/原文 digest、无 secret/XSS 新路径。Web 发现 roving tab 缺键盘导航、badge 对 `false/""/[]` 假显示 0.00；已统一 strict 数值解析并补键盘模型，复核无 blocker。

**验收证据**：聚焦回归 **130 tests OK**；`.venv/bin/python3 -m unittest discover -s tests` **1757 tests OK**（396.583s）；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部 **1757 tests OK** / 415.373s，随后 auto-pipeline/status/manifest/report/cost 全过）；真实配置 preflight = warn/无 FATAL；mock preflight = ok/无 WARN；`node --check`、`git diff --check` 通过。Playwright 临时 mock server 验证 `#style` 刷新、ARIA/方向键、null/false/`[null]`、Advisor escape、六 tab 失败态与编辑禁用；成功路径 console 0 error，故障路径仅预期 HTTP 500 resource error。真模型 smoke 未跑（铁律⑥）。

**残留风险 / 下轮候选**：red drift 自动定向重写、重写后复评分与 unresolved 留痕顺延 iter087+；现有本地 v1 baseline 必须运行 `python3 main.py style-fingerprint build-baseline` 重建。短剧导出/Insights/第 2 集重生/真模型批和小说 10-20 章 capstone 仍需用户明确授权。

**数据状态**：本轮改动集中在 `src/{style_fingerprint,style_drift}.py`、`src/web/static.py`、`config/style_fingerprint.yaml`、`main.py`、相关测试与迭代/README/AGENT_HANDOFF/AGENTS 文档。`verify.sh` 仅按既有授权写 gitignored 验收产物；未跟踪 `续写工作台.pptx` 是用户文件，保持不动；只 commit、不 push。
