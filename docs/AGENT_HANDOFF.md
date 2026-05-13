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
- Iteration records are kept under `docs/iterations/`.

## Validation Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
```

## Next Candidates

- Run the real-model smoke path once the user writes the rotated DeepSeek key into `.env`, then inspect `logs/real_smoke_<timestamp>.log` and `logs/llm_calls.jsonl`.
- Deferred candidates: B3 rolling summary 升级伏笔表、C2 增量 compress。优先级建议在跑过真模型小样本后按真实翻车样式排序。
- Debate true-model联调 can use `bash scripts/debate_smoke.sh` after extract smoke is clean.
- Add a lightweight terminal UI or dashboard if operator reports become too verbose.
