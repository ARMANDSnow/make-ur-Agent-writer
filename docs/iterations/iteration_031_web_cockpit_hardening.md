# Iteration 031 - Web Cockpit Hardening + Handoff Refresh

## Context

Iteration 030 delivered the local Web beta writing cockpit, but a post-iteration subagent review found two structural bugs and one resource pattern that made the UI heavier than necessary on a MacBook Pro: a corrupt `chapter_plan.json` could still break the whole workspace overview, persisted job lookup had one path that ignored `paths.WORKSPACE_DIR`, and workspace page startup eagerly loaded hidden tabs plus repeated readiness checks.

This iteration treats those findings as a new hardening pass instead of rewriting the iter 030 record. The repo was clean and iter 030 was already committed.

## Plan

1. Make `/api/workspaces/overview` fail per workspace, not globally, when plan/manifest/start-point data is corrupt.
2. Fix persisted job lookup to use the same workspace root as job writes and recent-job reads.
3. Reduce WebUI startup and page-open load with a short overview TTL cache, lazy hidden-tab loading, and debounced readiness refresh.
4. Make the Web plan button explicitly say it overwrites the plan.
5. Add focused Web regressions and update handoff/SOP docs, including the stale `AGENTS.md` current-iteration anchor.

## Acceptance

- Corrupt `outputs/debate/chapter_plan.json` in one workspace returns `/api/workspaces/overview` 200; only that workspace is blocked and carries an error.
- `/api/workspace/<name>/job/<id>` can recover a persisted job when `paths.WORKSPACE_DIR` is patched away from the default repo path.
- Workspace page startup no longer fetches all hidden tab APIs; tab panels fetch on first click.
- Readiness refresh from write-book form input is debounced.
- Web plan action clearly says it regenerates and overwrites the plan.
- Mock-only verification passes; no true-model smoke, no `.env` edits, no `小说txt/` edits.

## Implementation Notes

- `src/web/routes.py` now wraps per-workspace overview collection defensively and adds a 3-second overview cache keyed by workspace root, workspace names, and key file/directory mtimes. Start-point writes invalidate the cache.
- `src/web/jobs.py::_load_persisted_job()` now scans `paths.WORKSPACE_DIR` instead of `ROOT / "workspaces"`.
- `src/web/static.py` replaces eager `loadSecondaryPanels()` with `loadTabPanel()` on tab click and adds `scheduleReadiness()` with a 500 ms debounce.
- `src/web/templates.py` changes the plan submit label to `重生成并覆盖计划`.
- Tests were extended in `tests/test_web_routes_get.py` and `tests/test_web_jobs_dispatch.py`.

## Acceptance Result

- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m py_compile src/web/routes.py src/web/jobs.py src/web/static.py src/web/templates.py tests/test_web_routes_get.py tests/test_web_jobs_dispatch.py` -> OK.
- `node --check /private/tmp/iter031_dashboard.js` -> OK.
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m unittest tests.test_web_routes_get tests.test_web_jobs_dispatch` -> 38 OK.
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests` -> normal sandbox hit the known 5 Web socket `PermissionError`; approved rerun passed 421 OK.
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` -> normal sandbox hit the same 5 Web socket `PermissionError`; approved rerun passed 421 tests OK + mock auto-pipeline OK.
- `PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` -> PREFLIGHT ok; FATAL none; WARN none.
- Non-true-model route timing sample: `/api/workspaces/overview` first call about 145 ms, TTL second call about 1.4 ms; `xueZhong` cost about 14.8 ms; `xueZhong` readiness about 10.0 ms. LiteLLM import still attempts/falls back from remote cost-map loading, so deeper lazy-import work remains a future optimization.

## 文件变更汇总

| File | Change |
|------|--------|
| `src/web/routes.py` | overview per-workspace fault isolation + short TTL cache |
| `src/web/jobs.py` | persisted job lookup respects `paths.WORKSPACE_DIR` |
| `src/web/static.py`, `src/web/templates.py` | lazy tabs, debounced readiness, overwrite-plan wording |
| `tests/test_web_routes_get.py`, `tests/test_web_jobs_dispatch.py` | corrupt plan, persisted job, JS regression coverage |
| `README.md`, `AGENTS.md`, `docs/AGENT_HANDOFF.md`, `docs/iterations/README.md` | iter 031 status and handoff refresh |

## 不在本轮范围

- No real-model smoke or long-running write.
- No `.env` edits and no provider/model switching.
- No changes to `小说txt/` or user-private workspace contents.
- No full cost-log indexer or LiteLLM lazy-import refactor; those remain follow-up performance work if Web startup heat persists.

## Notes

- The project handoff structure is still basically sound for multi-session agents: `AGENTS.md -> docs/AGENT_HANDOFF.md -> docs/iterations/README.md -> latest iteration -> README SOP`. The main problem was drift in `AGENTS.md`, which this iteration corrects.
- Recommended next Web performance candidates: lazy-import LiteLLM/preflight for `main.py web`, incremental cost summaries, and a small visible "server already running" helper for port/process hygiene.
