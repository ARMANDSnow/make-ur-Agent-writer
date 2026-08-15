# Continuator

A local multi-agent pipeline for original fiction and novel continuation. It separates knowledge extraction, plotting, drafting, review, and state advancement into recoverable steps. Development and canonical verification default to an offline mock model.

[中文](README.md) · English

> Since iteration 167, `main` is novel-only. The complete pre-split short-drama implementation is preserved on `codex/short-drama`. Main keeps only disabled UI entry cards and never creates, lists, migrates, or deletes legacy drama workspaces.

## Highlights

- Server-authoritative original/continuation modes and start-safe knowledge views.
- Debate, chapter planning, drafting, 5+1 review, deterministic linting, and controlled retries.
- Long-running recovery with workspace locks, supervisor, heartbeat, watchdog, and budgets.
- Local Web workbench for setup, outlines, chapter plans, drafts, jobs, search, versions, and metrics.
- Fail-closed isolation for legacy `type=drama`, invalid metadata, and unsafe workspace paths.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
bash scripts/verify.sh
```

The canonical verifier accepts no arguments, forces mock/offline execution in an isolated synthetic workspace, and writes schema-v3 evidence to `outputs/harness/acceptance.json`. It proves only the `mock-functional` level.

## Run the Web UI

```bash
python3 main.py web
python3 main.py web --port 9999
```

The Web UI manages novel workspaces only. Short-drama cards are native disabled controls with no link or click handler. Direct access to legacy drama workspaces fails closed with 404.

## Novel pipeline

1. Import and normalize source text.
2. Split chapters and build source maps.
3. Extract entities, events, relations, and facts.
4. Compress and approve knowledge proposals.
5. Debate directions and plan chapters.
6. Draft with bounded retries and recovery.
7. Review; only strict approval completes a chapter.
8. Apply relationship and state proposals.
9. Roll summaries forward and continue under runner/supervisor control.

## Current baseline

Iteration 167 preserved the full baseline on `codex/short-drama` and made main novel-only. Canonical evidence on implementation `bd1be59`: schema v3, profile `canonical-novel-mock-offline`, 1849 tests, 15 steps, 78 seconds, `mock-functional`, tracked scope clean. This does not validate real providers, long-form quality, or an SLA.

See [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) for current state, [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) for historical decisions, and [`docs/product/GETTING_STARTED.md`](docs/product/GETTING_STARTED.md) for usage.

Private source text and runtime artifacts remain ignored. Never edit original files under `小说txt/`; use proposals or manual overrides for maintained state.
