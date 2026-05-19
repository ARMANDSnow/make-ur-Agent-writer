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

### P7 真模型 smoke (DeepSeek v4-pro)

执行：`bash scripts/write_smoke.sh`。前置：用户切 `.env` 到 `deepseek/deepseek-v4-pro`，并手工补齐 14 条 active=false 关系（路明非↔绘梨衣等核心关系的 timeline 最后一节点设 active=true）。

- log: `logs/write_smoke_20260518_234246.log`
- snapshot（脚本崩在 snapshot 之前，手工补救）: `outputs/drafts/snapshots/20260518_234246_recovered/`

| # | 项 | 结果 |
|---|---|---|
| D1 | 中文字数 ≥ 3000 | ✅ **4507**（远超 hard floor） |
| D2 | meta 字段完整 | ✅ `chinese_char_count=4507`, `polish_applied=false`, `rewrite_count=0`, `agent_reviews=8` |
| D3 | 新 reviewer 真跑 | ✅ "关系一致性" 在 review pipeline 内，verdict=Approve, issues=0 |
| D4 | 关系一致性反馈 | ⚠️ 薄弱 —— Approve 但 issues=0，没明确说明对照过 entity_graph；用户主观读章未发现 OOC（关系层无"旅游景点"类错位） |
| D5 | meta 含 polish_applied/lint_blocked_reviews | ✅ |
| D6 | 用户自评 | ✅ **8/10**（语言/对话有"活人感"、人物刻画合理、出现"江南式幽默"、关系层无 OOC、文笔质感提升） |
| D7 | DeepSeek ok 率 | ✅ **60/60 = 100%**（compress 1 + debate 47 + write 1 + review 11） |
| D8 | 失败无残留 | ✅ |
| D9 | snapshot 完整 | ⚠️ 脚本崩在 snapshot 之前，**手工补救**至 `snapshots/20260518_234246_recovered/` |
| E | 成本受控 | ✅ ~$0.42（按 v3 单价 2x 估算；447k prompt / 80k response tokens） |

**新暴露的两个工程坑（iter 012 必修）**：

1. **`scripts/write_smoke.sh` 崩在 standalone review**：`python3 main.py review` 调 `review_target → review_text → extract_json_object` 抛 `ValueError: No JSON object found in LLM response`，因 reviewer 二次跑时一个 agent 返回不可解析 JSON。`set -e` 导致脚本未执行后续 status/estimate-cost/preflight/snapshot 步骤。
2. **`outputs/debate/decisions.json` votes=[]**：v4-pro 在 structured ballot JSON 上不稳，build_decisions 拿到空数组未走 fallback，最终 `votes=0`（但 outline.md 内容正常）。

**模型选择结论**：v4-pro 在文笔质量上明显优于 v3（用户主观验收 5 → 6+ → 8），但在 structured JSON 输出（debate ballot / standalone review）上系统性不稳。iter 012 修两个坑后保留 v4-pro，结构层加 fallback。

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
