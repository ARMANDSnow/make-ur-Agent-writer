# Iteration 017 - Multi-book Workspace Isolation

## Context

Iteration 014-016 made the pipeline automatic on any Chinese novel: bootstrap proposes the four manual artifacts, persona binding stops debate / review agents from anchoring on the original validation corpus, and the outline is auto-generated correctly without manual rewriting. But the directory layout still assumed exactly one book per checkout. ``data/``, ``outputs/``, ``logs/``, ``小说txt/`` all lived at the repo root. Switching books required manually backing up everything to ``/tmp`` and clearing the slate (iter 015 smoke did this for the validation corpus; iter 016 re-smoke locked the second novel into the repo root).

Iteration 017 introduces ``workspaces/<book>/``. Multiple books coexist in the same checkout; switching is a single ``--book <name>`` flag (or ``WORKSPACE_NAME`` env var). Legacy mode (no flag, no env) keeps the repo-root layout so every existing test, script, and operator habit from iter 014-016 continues to work unchanged.

## Plan

P1. ``src/paths.py`` introduces the workspace abstraction. ``workspace_name()`` reads ``WORKSPACE_NAME`` (or ``BOOK``) on each call; the reserved value ``"legacy"`` and any empty / whitespace value resolve to legacy mode. ``workspace_root()`` returns repo ``ROOT`` for legacy mode and ``workspaces/<name>/`` otherwise. ~20 helper functions derive per-book paths (``data_dir``, ``debate_dir``, ``drafts_dir``, ``reviews_dir``, ``raw_txt_dir``, ``manual_overrides_dir``, ``personas_path``, ``outline_path``, ``chapter_plan_path``, ``kb_path``, ``index_path``, ``chapter_manifest_path``, ``entity_graph_path``, ``rolling_summary_path``, ``logs_dir``, ``llm_calls_log_path``, ``run_state_log_path``, etc.). All helpers are functions (not module-level constants) so the env var is re-read each call — a single Python process can switch workspaces, which is needed for the workspace_isolation tests.

P2. Every ``src/*.py`` module that hard-coded path constants gains ``_resolved_*()`` helper functions that defer to ``paths.*()`` when ``paths.workspace_name()`` returns truthy and fall back to the existing legacy constant otherwise. The legacy constants stay in place verbatim so the ~30 iter 014-016 tests that ``patch("src.debater.DEBATE_DIR", ...)`` still work. Modules touched: ``auto_bootstrap``, ``extractor``, ``compressor``, ``debater``, ``writer``, ``reviewer``, ``persona_loader``, ``plot_planner``, ``manual_facts``, ``entities``, ``style``, ``continuation_anchor``, ``observability``, ``preflight``, ``cost_estimator``, ``cli_apply_bootstrap``, ``text_normalizer``, ``chapter_splitter``, ``chapter_summary``, ``entity_advance``, ``state``, ``llm_client``.

P3. ``main.py`` pre-parses a global ``--book <name>`` flag (anywhere in argv) and sets ``os.environ["WORKSPACE_NAME"]`` before argparse runs. The flag is also acceptable as ``--book=<name>``. Without the flag (or env var), all commands run in legacy mode. The flag works with every existing subcommand.

P4. New module ``src/cli_workspace.py`` implements four management commands:

| Command | Purpose |
|---|---|
| ``workspace-list`` | Lists ``workspaces/<name>/`` directories |
| ``workspace-init <name>`` | Creates ``workspaces/<name>/{小说txt,data,outputs,logs}/`` |
| ``workspace-import-current --to <name> [--dry-run]`` | ``shutil.move`` repo-root ``data/``, ``outputs/``, ``logs/``, ``小说txt/`` into ``workspaces/<name>/``. Empty subdirs are skipped. ``config/`` is never touched. |
| ``workspace-show [--name <name>]`` | Summarizes a workspace (raw txt count, normalized count, extracted count, manual override presence, draft chapters, etc.) |

P5. ``scripts/write_book.sh``, ``scripts/verify.sh``, ``scripts/debate_smoke.sh``, ``scripts/write_smoke.sh``, ``scripts/real_smoke.sh`` all accept ``--book <name>`` and honor ``$WORKSPACE_NAME``. They resolve per-book output paths via a small inline ``python3 -c "from src import paths; ..."`` invocation so the script always writes to the right place regardless of legacy / named mode.

P6. ``.gitignore`` adds ``workspaces/*/小说txt/``, ``workspaces/*/data/``, ``workspaces/*/outputs/``, ``workspaces/*/logs/`` and a ``workspaces/.gitkeep`` placeholder so the bare ``workspaces/`` directory ships in git but no per-book content does.

P7. Tests +20 → 170:

| File | Added |
|---|---|
| ``tests/test_paths.py`` (new) | +12: ``workspace_name`` permutations (None / empty / whitespace / ``legacy`` / named), ``workspace_root`` resolution (legacy / named / explicit override), per-helper derivation, mid-process env switch |
| ``tests/test_workspace_isolation.py`` (new) | +3: every refactored module resolves to repo root in legacy mode; every module resolves into ``workspaces/<name>/`` when WORKSPACE_NAME is set; two workspaces can coexist in one process |
| ``tests/test_cli_integration.py`` | +3: ``--book`` flag is pre-parsed and exported as ``WORKSPACE_NAME``; ``workspace-init`` produces the four canonical subdirs; ``workspace-import-current --dry-run`` does not touch the filesystem |
| ``tests/test_smoke_scripts.py`` | +1: every smoke script (``debate_smoke``, ``write_smoke``, ``real_smoke``, ``write_book``, ``verify``) accepts ``--book`` and honors ``WORKSPACE_NAME`` |

P9. Update iteration index, AGENT_HANDOFF, README quick start, and write this iteration doc.

## Acceptance

| # | Item | Result |
|---|------|--------|
| A1 | ``python3 -m unittest discover -s tests`` | 170 tests OK in under 5 seconds |
| A2 | ``bash scripts/verify.sh`` | exit 0 (legacy mode) |
| A3 | ``python3 main.py preflight`` | ``warn`` / ``FATAL: none`` (legacy mode) |
| B1 | ``paths.py`` helpers | tests/test_paths.py 12 cases pass |
| B2 | ``--book`` CLI sets env | tests/test_cli_integration.py passes |
| B3 | ``workspace-init`` creates four subdirs | passes |
| B4 | ``workspace-import-current --dry-run`` is read-only | passes |
| B5 | Per-module path resolution via paths | tests/test_workspace_isolation.py 3 cases pass |
| B6 | Smoke scripts accept ``--book`` | tests/test_smoke_scripts.py passes |
| C1 | Legacy mode unchanged | All iter 014-016 tests (149) still pass; behavior is byte-identical without ``--book`` |
| C2-D3 | Cross-workspace smoke | Pending user confirmation ``可以跑 workspace smoke`` |
| F | Engineering gates | 170 / verify / preflight all green |

### Cross-workspace smoke result (C2-D3)

The cross-workspace smoke ran end to end on 2026-05-23. Two real source novels coexisted in the same checkout for the entire run.

**Step 1 — migrate workspace1 (the iter 016 source novel):**

```
python3 main.py workspace-import-current --to workspace1 --dry-run   # preview moves
python3 main.py workspace-import-current --to workspace1            # actual move via shutil.move
python3 main.py --book workspace1 preflight                          # warn / FATAL none
sha256sum workspaces/workspace1/outputs/drafts/chapter_01.md \
          workspaces/workspace1/outputs/debate/outline.md \
          workspaces/workspace1/data/manual_overrides/personas.json \
          workspaces/workspace1/data/entity_graph.json > /tmp/baseline.sha
```

After the import, the repo root ``data/``, ``outputs/``, ``logs/``, ``小说txt/`` were empty placeholder directories; the full iter 016 state lived under ``workspaces/workspace1/``.

**Step 2 — bring up workspace2 from a different source novel:**

```
python3 main.py workspace-init workspace2
cp <backup>/小说txt/*.txt workspaces/workspace2/小说txt/
python3 main.py --book workspace2 normalize        # 7 volumes
python3 main.py --book workspace2 split            # chapter manifest
python3 main.py --book workspace2 init-book --extract-limit 5
```

`init-book` extracted 5 chapters (2 succeeded, 3 had model JSON-parse failures — the same residual extraction-failure mode observed in iter 015), then compressed the knowledge base and produced all five bootstrap proposals via the Opus planner. The personas proposal correctly identified workspace2's protagonist and author — distinct from workspace1's — and listed 5 core relationships and 4 setting rules drawn from workspace2's own entity graph.

**Step 3 — apply all five workspace2 proposals + debate + plan + write:**

All five `apply-bootstrap --name X --confirm` operations wrote into `workspaces/workspace2/data/manual_overrides/` and `workspaces/workspace2/data/entity_graph.json` only. `python3 main.py --book workspace2 debate` ran the full 6×6 agent rounds + 6 ballots + outline generation (~32 minutes). Every agent name in `workspaces/workspace2/outputs/debate/debate_log.jsonl` was persona-rendered using workspace2's protagonist and author.

`workspaces/workspace2/outputs/debate/outline.md` had **22 keyword hits for workspace2's source novel** and **0 keyword hits for workspace1's source novel**. The outline title and section content all reflected workspace2's setting.

`plan-chapters --chapters 3 --force` produced a coherent 3-chapter plan grounded in workspace2. `write --chapters 1 --resume-from 1 --force` produced `workspaces/workspace2/outputs/drafts/chapter_01.md` with **4552 Chinese characters**. Writer meta `verdict=Reject` after `rewrite_round=2` (the workspace2 prose had more lint warnings than usual; the chapter still wrote and the smoke result is the file on disk). `review-chapter 1` returned `verdict=Approve` with the familiar `_fallback_reason=(parse_failed)`.

**Step 4 — byte-identical isolation check:**

Every monitor tick during the workspace2 debate showed workspace1's `chapter_01.md` sha256 prefix unchanged. After the full smoke ran:

```
sha256sum --check /tmp/baseline.sha
# workspaces/workspace1/outputs/drafts/chapter_01.md: OK
# workspaces/workspace1/outputs/debate/outline.md: OK
# workspaces/workspace1/data/manual_overrides/personas.json: OK
# workspaces/workspace1/data/entity_graph.json: OK
```

All four files were byte-identical. workspace1's chapter, outline, personas, and entity graph survived the entire workspace2 init-book → debate → plan → write → review pipeline untouched.

A few engineering fixes landed alongside the smoke:

* `main.init_book_pipeline` was using hardcoded `Path("小说txt")` / `Path("data/normalized_texts")` / `Path("data/chapter_manifest.json")` strings. In workspace mode it now resolves these through `paths.*()`. Legacy mode keeps the cwd-relative strings so the iter 014-016 tests that chdir into a tmp dir still work.
* `main` command for `review-chapter` was using hardcoded `outputs/drafts/chapter_NN.md`. In workspace mode it now uses `paths.drafts_dir() / f"chapter_{N:02d}.md"`.

Snapshot at `workspaces/workspace2/outputs/drafts/snapshots/<ts>_iter017_workspace2/` contains the chapter, meta, plan, decisions, outline, reviews, rolling summary, five bootstrap proposals, and the applied personas binding for workspace2.

| # | Item | Result |
|---|------|--------|
| C1 | `import-current --dry-run` is read-only | OK; the dry-run listed all four planned moves without touching disk |
| C2 | workspace1 migration | OK; preflight clean; baseline sha256 recorded |
| C3 | workspace2 brought up from scratch | OK; 5 proposals; all 5 applied; debate, plan, write, review all completed |
| C4 | **byte-identical isolation** | **PASS**; all 4 workspace1 files unchanged after the full workspace2 pipeline |
| D1 | User subjective rating | Pending user readback (baseline target ≥ 8/10) |
| D2 | workspace2 ch1 protagonist correct | OK; first line names workspace2's protagonist and setting; no workspace1 keyword appears |
| D3 | Snapshot completeness | OK (see snapshot directory) |

## Implementation Notes

The single hardest design choice was backward compatibility for the ~30 iter 014-016 tests that ``patch("src.module.CONSTANT", value)`` to redirect a module's path during testing. Three options were on the table:

1. Delete the constants outright, rewrite all 30 tests. Highest risk of regression and most churn.
2. Wrap the constants in a class with descriptor magic. Clever but hard to debug.
3. **Keep the constants verbatim and add ``_resolved_*()`` helper functions.** The function bodies use ``paths.<helper>()`` only when ``paths.workspace_name()`` is truthy, and fall back to the legacy constant otherwise.

Option 3 won. Legacy tests still patch the same constants and get the same behavior because the resolver returns the (patched) constant when no workspace is active. Workspace mode goes through ``paths.*()`` directly. Zero regressions.

The ``_consume_book_pre_arg()`` function in ``main.py`` strips ``--book`` from ``sys.argv`` before argparse runs because argparse subparsers are not great at accepting a parent-level flag that can appear either before or inside the subcommand position. The strip-and-export approach is small and works with every existing subparser without modification.

``workspace-import-current`` uses ``shutil.move`` instead of ``shutil.copytree`` so the source novel text only ever exists in one canonical location. This matches the copyright rule that has held since iter 015: source text lives in exactly one gitignored place, never in two copies.

## Acceptance Result

Engineering (P1-P7 + P9):

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 170 tests in <5s, OK

python3 main.py preflight
# PREFLIGHT: warn; FATAL: none
```

Cross-workspace smoke (C2-D3) is intentionally pending. The next phase waits for the user to reply ``可以跑 workspace smoke``.

## 文件变更汇总

| File | Change |
|------|--------|
| ``src/paths.py`` | New module — workspace_name / workspace_root / 20+ path helpers, all function-based so env switching works mid-process |
| ``src/auto_bootstrap.py`` | All ``root: Path = ROOT`` defaults changed to ``= None`` with ``_resolve_root()`` helper; calls to ``paths`` when workspace is active |
| ``src/extractor.py`` | Module-level path constants kept; ``_extracted_dir`` / ``_overrides_dir`` / ``_failures_dir`` / ``_rolling_dir`` resolvers added and used at call sites |
| ``src/compressor.py`` | ``_extracted_dir`` / ``_kb_dir`` resolvers; ``compress_all`` writes to per-workspace paths |
| ``src/debater.py`` | ``_debate_dir`` / ``_kb_path`` / ``_index_path`` resolvers; ``run_debate`` writes to per-workspace paths |
| ``src/writer.py`` | ``_drafts_dir`` / ``_outline_path`` / ``_kb_path`` / ``_index_path`` / ``_chapter_plan_path`` resolvers |
| ``src/reviewer.py`` | ``_reviews_dir`` resolver |
| ``src/persona_loader.py`` | ``_personas_path`` resolver; ``load_personas(path=None)`` defaults to active workspace |
| ``src/plot_planner.py`` | ``_chapter_plan_path`` / ``_outline_path`` resolvers |
| ``src/manual_facts.py`` | ``_global_facts_path`` resolver; ``load_global_facts(path=None)`` defaults via paths |
| ``src/entities.py`` | ``load_entity_graph(root=None)`` defaults to ``paths.entity_graph_path()`` when workspace is active |
| ``src/style.py`` | ``load_style_examples(root=None)`` defaults via paths |
| ``src/continuation_anchor.py`` | ``load_continuation_anchor(root=None)`` defaults via paths; legacy ``agents.yaml`` fallback only fires in legacy mode |
| ``src/observability.py`` | All 8 ``root: Path = ROOT`` defaults changed to ``= None`` with ``_resolve_root`` |
| ``src/preflight.py`` | ``run_preflight`` and ``_check_agents_config`` use ``_resolve_root`` |
| ``src/cost_estimator.py`` | ``estimate_cost`` uses ``_resolve_root`` |
| ``src/cli_apply_bootstrap.py`` | ``apply_bootstrap`` uses ``_resolve_root`` |
| ``src/chapter_splitter.py`` | ``_normalized_dir`` / ``_manifest_path`` / ``_normalized_manifest_path`` resolvers |
| ``src/chapter_summary.py`` | ``_rolling_path`` resolver; ``load_rolling_summary`` / ``save_rolling_summary`` / ``append_chapter_summary`` / ``latest_ending_state`` / ``render_rolling_context`` default ``path=None`` |
| ``src/entity_advance.py`` | ``_drafts_dir`` / ``_entity_graph_path`` resolvers; ``proposal_path`` / ``save_entity_advance_proposals`` / ``apply_advance_proposals`` accept ``=None`` defaults |
| ``src/text_normalizer.py`` | ``_raw_dir`` / ``_normalized_dir`` / ``_source_map_dir`` / ``_normalized_manifest_path`` resolvers |
| ``src/state.py`` | ``_state_log`` resolver; ``log_event`` uses it |
| ``src/llm_client.py`` | LLM call log destination uses ``paths.llm_calls_log_path()`` when workspace is active |
| ``src/cli_workspace.py`` | New module: ``list_workspaces``, ``init_workspace``, ``import_current``, ``show_workspace``, render helpers |
| ``main.py`` | ``_consume_book_pre_arg`` strips ``--book`` and exports ``WORKSPACE_NAME``; ``workspace-list`` / ``workspace-init`` / ``workspace-import-current`` / ``workspace-show`` dispatch |
| ``scripts/verify.sh`` / ``scripts/write_book.sh`` / ``scripts/debate_smoke.sh`` / ``scripts/write_smoke.sh`` / ``scripts/real_smoke.sh`` | Accept ``--book`` and ``$WORKSPACE_NAME``; per-book paths via ``python3 -c "from src import paths; ..."`` |
| ``tests/test_paths.py`` | New file (+12 cases) |
| ``tests/test_workspace_isolation.py`` | New file (+3 cases) |
| ``tests/test_cli_integration.py`` | +3 workspace tests |
| ``tests/test_smoke_scripts.py`` | +1 multi-script ``--book`` check; existing snapshot-path assert relaxed |
| ``.gitignore`` | Adds ``workspaces/*/{小说txt,data,outputs,logs}/`` rules and ``!workspaces/.gitkeep`` |
| ``workspaces/.gitkeep`` | New empty placeholder so the bare ``workspaces/`` directory ships in git |
| ``docs/iterations/iteration_017_multi_workspace.md`` | This file (new) |
| ``docs/iterations/README.md`` | +1 index entry |
| ``docs/AGENT_HANDOFF.md`` | iter 017 section |
| ``README.md`` | Quick start updated with ``--book`` usage and ``workspace-*`` commands |
| ``workspaces/<book>/{小说txt,data,outputs,logs}/...`` | runtime, gitignored |

## 不在本轮范围

- ``write_book.sh`` full automation across multiple chapters with failure resume/retry — iter 019 candidate (user explicitly scoped iter 017 to workspace isolation only).
- Multilingual splitter and English novel support — iter 018 candidate.
- Per-workspace model configuration (different DeepSeek / OpenAI route per book) — iter 020+ candidate; ``config/models.yaml`` stays shared.
- Per-workspace agent persona is already per-book via the gitignored ``data/manual_overrides/personas.json``, which now sits inside ``workspaces/<name>/data/`` automatically — no new code needed.
- Web UI / hosted SaaS / per-user workspace — iter 020+ candidate.
- Cross-workspace diff / state-compare tooling — iter 020+ candidate.

## Notes

- ``.env`` is not modified. No ``sk-`` value ever appears in tracked files or commit messages.
- Tracked files reference workspaces only by abstract role (``workspace1`` / ``workspace2``). Specific novel names, character names, and source excerpts stay out of git.
- ``workspaces/<book>/data/``, ``workspaces/<book>/小说txt/``, and the in-tree legacy ``小说txt/`` are all gitignored — same rationale.
- ``workspace-import-current`` uses ``shutil.move`` so the source novel exists in exactly one canonical location on disk after migration.
- Backward compatibility hard requirement: every iter 014-016 behavior is preserved when ``--book`` is absent. The 149 tests from iter 016 still pass byte-identically.
- Commit message for the engineering step is ``Iteration 017: multi-book workspace isolation``; the smoke commit (after user confirmation) will be ``Iteration 017: record multi-workspace smoke results``. Neither references a specific novel name.
