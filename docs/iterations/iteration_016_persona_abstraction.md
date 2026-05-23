# Iteration 016 - Agent Persona Abstraction

## Context

Iteration 015 bootstrap-ed `global_facts`, `entity_graph`, `continuation_anchor`, and `style_examples` from the source novel itself. The cross-novel smoke proved the data side could be onboarded with about thirty minutes of user review. It also exposed a residual blocker: the six debate agents and eight review agents in `config/agents.yaml` were anchored on the original validation corpus. When run against another novel, all six debate agents produced an outline disconnected from the new bootstrap manual files; the smoke only completed because a person rewrote `outputs/debate/outline.md` by hand before `plan-chapters`.

Iteration 016 closes the last manual step on the generalization axis. It adds a fifth bootstrap output — persona bindings — and wires every debate and review prompt to render those bindings at runtime, while keeping the original validation-corpus workflow alive through legacy fallbacks.

## Plan

P1. Refactor `config/agents.yaml`. Every debate and review agent keeps its legacy `name` / `system_prompt` / `stance` fields and gains parallel `*_template` fields with `{protagonist_name}`, `{author_name}`, `{world_setting_brief}`, `{core_relationships_text}`, `{core_setting_rules_text}` placeholders.

P2. Add `PersonasProposal` schema and `bootstrap_personas` to `src/auto_bootstrap.py`. The function reads applied manual data (entity_graph, global_facts, continuation_anchor) plus a small normalized-text head sample and asks the planner LLM to fill seven binding fields. The proposal stays under `data/proposals/personas.proposal.json` and never touches the applied manual file.

P3. Extend `src/cli_apply_bootstrap.py` with `--name personas`. The dry-run, diff, backup, and `--confirm` path mirror the other four proposals. Applied bindings land at `data/manual_overrides/personas.json`.

P4. Add `src/persona_loader.py`. `load_personas()` returns the applied dict when present and `protagonist_name` is non-empty; otherwise returns `None`. `render_agent_fields(agent, personas)` produces `(name, system_prompt, stance)` — rendering `*_template` fields when personas exist, falling back to legacy fields per-slot on render failure. The renderer uses `str.format_map` with a default-empty mapping so undefined variables collapse to `""` rather than raise.

P5. Wire the loader into `src/debater.py` and `src/reviewer.py`. The debate transcript log now shows persona-rendered agent names; the outline prompt gets an explicit persona block ("主角 / 作者 / 世界观骨架 / 核心关系 / 硬规则") so the LLM cannot drift back to the validation corpus. The reviewer keeps relationship-checklist enforcement keyed on the legacy name so 关系一致性 still gets its hard guard regardless of rendering.

P6. Plumb the persona pipeline into `init-book` (free via `bootstrap_all`) and add `python3 main.py bootstrap-personas` plus `python3 main.py debate --topic "..."`.

P7. Tests +14 → 149 (plan target was 141).

| File | Added |
|---|---|
| `tests/test_auto_bootstrap.py` | +1: `bootstrap_personas` writes proposal but not applied manual |
| `tests/test_apply_bootstrap.py` | +1: dry-run then `--confirm` for personas, with backup of existing file |
| `tests/test_persona_loader.py` (new) | +8: load None when missing / blank protagonist, render templates and unknown vars, fallback paths |
| `tests/test_debater.py` | +1: with personas present, debate log agent names contain `{protagonist_name}本位` and `{author_name}人格模拟`; legacy validation-corpus names do not leak |
| `tests/test_reviewer.py` | +1: persona-rendered reviewer prompt actually receives the bound protagonist name |
| `tests/test_cli_integration.py` | +2: `debate --topic` forwards the topic to `run_debate`; `bootstrap_all` produces all five proposal keys |

P9. Update iteration index, AGENT_HANDOFF, README quick start, and write this iteration doc.

## Acceptance

| # | Item | Result |
|---|------|--------|
| A1 | `python3 -m unittest discover -s tests` | 149 tests OK in under 5 seconds |
| A2 | `bash scripts/verify.sh` | exit 0 |
| A3 | `python3 main.py preflight` | `warn` / `FATAL: none` |
| B1 | `bootstrap_personas` mock test | passes; proposal file has all seven binding fields; applied manual untouched |
| B2 | `apply-bootstrap --name personas` dry-run / confirm | passes; existing applied file is backed up; `_meta` stripped on apply |
| B3 | persona_loader fallback to legacy | passes; missing / blank-protagonist personas return `None` and legacy fields are returned verbatim |
| B4 | debater renders persona into prompt | passes; legacy names absent from log when personas applied |
| B5 | reviewer renders persona into prompt | passes; rendered name in report; legacy name absent from system prompt |
| B6 | `debate --topic` CLI override | passes; absent `--topic` keeps default kwarg |
| C1 | personas proposal data shape | enforced via `PersonasProposal` schema: `protagonist_name` ≤ 40, `world_setting_brief` ≤ 400, lists default to `[]` |
| C2-C6 | Cross-novel re-smoke against the iter 015 corpus | pending user confirmation `可以跑 persona smoke` |
| D1 | User subjective evaluation | pending user readback after re-smoke |
| D2 | LLM call OK rate during smoke | pending |
| D3 | Snapshot completeness post-smoke | pending |
| E | Cost | bootstrap +1 ≈ $0.5 over iter 015's ≈ $4 envelope |
| F1 | Iteration doc | this file |
| F2 | README quick start | adds the personas step |
| F3 | HANDOFF | iter 016 section appended below the existing iter 015 record |
| F4 | No key leak, no source-novel excerpt in tracked files, commit message novel-name-free | enforced via grep before commit |

## Implementation Notes

The persona renderer keeps three invariants that surfaced during integration:

* **Legacy fallback is per-slot, not all-or-nothing.** An agent can have only `name_template` defined; its `system_prompt` should still come from the legacy field. `render_agent_fields` evaluates each slot independently.

* **Relationship-checklist enforcement keys off the legacy name.** When personas rename `关系一致性` to something else, the rule-semantic match still needs to find that reviewer. The reviewer call stores the legacy name in a `_legacy_name` field on the rendered agent dict so `_repair_agent_review_dict` matches the right reviewer even when the display name has changed.

* **Persona binding must short-circuit on blank protagonist.** A file with `protagonist_name=""` would render `"{protagonist_name}本位"` to `"本位"` and silently destroy agent identity. `load_personas` treats blank-protagonist as not-applied so the legacy path takes over.

The outline prompt explicitly forbids drifting back to other corpora when personas are present:

```
# 本书 persona 绑定（大纲严格遵守，禁止引用其他小说角色或世界观）
- 主角：{protagonist_name}（{protagonist_role}）
- 作者风格参考：{author_name}（{style_short_descriptor}）
- 世界观骨架：{world_setting_brief}
- 核心关系：...
- 世界观硬规则：...
```

This block sits between the topic and the entity-state block in `build_outline`. The hardcoded outline fallback path (used on LLM failure and mock mode) is intentionally unchanged — it still serves the original validation-corpus story so unit tests stay stable. Operationally, the LLM path is what matters for the cross-novel smoke.

## Acceptance Result

Engineering (P1-P7 + P9):

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 149 tests in <5s, OK

bash scripts/verify.sh
# exit 0; 149 tests OK; mock-only LLM calls

python3 main.py preflight
# PREFLIGHT: warn; FATAL: none
```

Cross-novel re-smoke (C2-D3) is intentionally pending. The next phase waits for the user to delete the iter 015 cross-novel `outputs/debate/outline.md` and `data/manual_overrides/personas.json` and reply `可以跑 persona smoke`.

## 文件变更汇总

| File | Change |
|------|--------|
| `config/agents.yaml` | Add `name_template` / `system_prompt_template` / `stance_template` to every debate and review agent; keep legacy fields for fallback; add `_persona_template_note` explaining the contract |
| `src/persona_loader.py` | New module: `load_personas`, `render_template`, `render_agent_fields` |
| `src/auto_bootstrap.py` | New `bootstrap_personas` + `_personas_context` + `proposal_summary` branch; `bootstrap_all` now returns five entries |
| `src/cli_apply_bootstrap.py` | New `personas` path: target, diff, backup, applied-payload sanitization (strip `_meta`, coerce missing list/string defaults) |
| `src/debater.py` | Wire `load_personas` + `render_agent_fields` in `run_debate`; inject persona block into `build_outline` |
| `src/reviewer.py` | Wire `load_personas` + `render_agent_fields` in `review_text`; preserve legacy-name-keyed relationship-checklist enforcement |
| `src/schemas.py` | New `PersonasProposal` model |
| `src/llm_client.py` | Mock `PersonasProposal` response so all bootstrap tests run with `OPENAI_MODEL=mock` |
| `main.py` | New `bootstrap-personas` subcommand; new `debate --topic` argument |
| `tests/test_auto_bootstrap.py` | +1 personas test |
| `tests/test_apply_bootstrap.py` | +1 personas dry-run/confirm test |
| `tests/test_persona_loader.py` | New file: +8 loader and render tests |
| `tests/test_debater.py` | +1 persona rendering test for run_debate |
| `tests/test_reviewer.py` | +1 persona rendering test for review_text |
| `tests/test_cli_integration.py` | +2: debate --topic forwarding and bootstrap_all returning five keys |
| `docs/iterations/iteration_016_persona_abstraction.md` | New iteration doc |
| `docs/iterations/README.md` | New index entry |
| `docs/AGENT_HANDOFF.md` | Append iter 016 section |
| `README.md` | Add personas step to the quick start |
| `data/proposals/personas.proposal.json` | runtime, gitignored |
| `data/manual_overrides/personas.json` | runtime, gitignored |
| `data/proposals/.backup/<ts>/personas.json` | runtime, gitignored |

## 不在本轮范围

- Multi-book workspace isolation under `workspaces/<book>/` (iter 017 candidate).
- Multilingual splitter and English novel support (iter 018 candidate).
- Fully automated `write_book.sh` with chapter resume/retry and plan-aware advance (iter 019 candidate).
- Plot planner dynamic mid-arc re-planning (iter 020 candidate).
- Auto-merge UI when the bootstrapped protagonist disagrees with the entity_graph protagonist; in iter 016 the user reconciles by editing the proposal file before `--confirm`.

## Notes

- `.env` is not modified. No `sk-` ever appears in tracked files or commit messages.
- Persona proposal stores only short binding strings — protagonist name, author name, world brief, relationships, rules. It never quotes source text.
- The 关系一致性 reviewer's long system prompt still includes the relationship-checklist contract; the template version only swaps an example line so the rule-semantic identifier stays stable.
- Commit message for the engineering step is `Iteration 016: agent persona abstraction`; the smoke commit (after user confirmation) will be `Iteration 016: record persona re-smoke results`. Neither references a specific novel name.
