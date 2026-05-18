# Iteration 011 - Entity Graph + Consistency Reviewer + Polish Length Floor

## Context

Iteration 010 made reviewer signal available and loosened the over-strict deterministic lint loop, but the final approved chapter still had only 2694 Chinese characters and the user identified a deeper relationship-state problem. Static facts told the writer who entities are, but not the current dynamic relationship between them. Iteration 011 adds an optional entity graph, injects its active relationship state into write/debate/review prompts, adds a dedicated relationship-consistency reviewer, and forces polish to run when a draft is approved but still below the 3000 Chinese-character floor.

## P1 Entity Graph

Added [src/entities.py](../../src/entities.py) with `load_entity_graph()`, `_build_tag_index()`, and `render_active_state()`. `load_entity_graph()` reads `data/entity_graph.json` when present and returns `{}` when absent, so existing workflows degrade gracefully. `render_active_state()` renders three prompt sections: entity list, shared-tag reverse index, and only `active: true` relationship timeline nodes. Added [data/entity_graph.example.json](../../data/entity_graph.example.json) as schema v2 placeholder data with `_meta.note`, entity `tags`, optional `description`, `<用户填写>` values, and no source plot content or quoted text.

Schema v2: `tags` uses `#xxx` keywords and triggers an automatic reverse index when at least two entities share a tag. `description` is optional and is reserved for the user to summarize current state in their own words.

## P2 Prompt Injection

[src/writer.py](../../src/writer.py) now appends rendered entity state to the stable cached prompt context when an entity graph exists, followed by the explicit instruction to strictly obey the current active relationships. [src/debater.py](../../src/debater.py) injects the same active state into `build_outline()` so chapter direction respects relationship constraints early. Agent ballot prompts deliberately remain unchanged to avoid bloating the voting phase.

## P3 Reviewer Agent

[config/agents.yaml](../../config/agents.yaml) now includes an eighth review agent, `关系一致性`, focused on relationship drift and unknown entity/relationship use. [src/reviewer.py](../../src/reviewer.py) injects entity state into every reviewer prompt immediately after `人工全局事实`, giving all reviewers the same relationship ground truth while keeping the deterministic lint short-circuit behavior unchanged unless the caller opts into reviewer execution.

## P4 Polish Length Floor

[src/writer.py](../../src/writer.py) now computes `chinese_chars` after the normal rewrite loop and runs `_polish_draft` when polish is enabled and the draft is lint-blocked, reviewer-rejected, or below 3000 Chinese characters. `_polish_draft` adds an expansion branch for short drafts: current count, target 3500-5500 Chinese characters, and directions to expand environment, action, psychology, and dialogue while preserving the story line.

## P6 Tests

Added [tests/test_entities.py](../../tests/test_entities.py) with four entity tests: missing-file graceful degrade, active-timeline filtering, shared-tag reverse index rendering, and optional description rendering. Added writer tests for entity-state prompt/cache injection and polish triggering on approved short drafts. Added a reviewer pipeline test proving the `关系一致性` agent is loaded and receives the rendered active state. Total planned test growth is +7, from 98 to 105. Existing debate-agent count tests were unaffected because only review agents changed.

## Acceptance Result

Engineering verification for P1-P4 + P6 + P8:

```bash
python3 -m unittest discover -s tests
# Ran 103 tests in 2.249s, OK

bash scripts/verify.sh
# Ran 103 tests in 2.275s, OK; script exited 0

python3 main.py preflight
# PREFLIGHT: warn
# FATAL: none
# WARN: tokenizer fallback and longest-chapter context warning
```

The most recent 200 LLM log rows after `verify.sh` were mock-only. A secret-like token scan for `sk-` followed by 20 or more token characters returned no hits.

The DeepSeek v4-pro switch is intentionally user-owned and was not applied by Codex in this iteration. Current preflight still sees `deepseek/deepseek-chat` from the existing environment and reports warn / FATAL none. Routing validation for `deepseek/deepseek-v4-pro` will happen after the user edits `.env`; if LiteLLM does not recognize it, the fallback note should be recorded separately before any true-model write smoke.

## File Summary

| File | Change |
|------|--------|
| [src/entities.py](../../src/entities.py) | optional entity graph loader and active-state renderer |
| [data/entity_graph.example.json](../../data/entity_graph.example.json) | schema-only placeholder example |
| [src/writer.py](../../src/writer.py) | entity-state prompt injection and short-draft polish trigger |
| [src/debater.py](../../src/debater.py) | entity-state outline injection |
| [src/reviewer.py](../../src/reviewer.py) | entity-state reviewer injection |
| [config/agents.yaml](../../config/agents.yaml) | add `关系一致性` review agent |
| [tests/test_entities.py](../../tests/test_entities.py) | new entity helper tests |
| [tests/test_writer.py](../../tests/test_writer.py) | writer injection and polish floor tests |
| [tests/test_reviewer.py](../../tests/test_reviewer.py) | relationship reviewer pipeline test |

Before the true-model write smoke, the user should copy the example to `data/entity_graph.json`, fill at least 5 entities and 3 relationships with at least 2 timeline nodes per relationship, switch `.env` to the requested model, then reply `可以跑了`. Codex should not run `scripts/write_smoke.sh` or modify `.env` before that confirmation.
