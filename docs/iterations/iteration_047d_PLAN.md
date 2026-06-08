# Iteration 047d — reader/character 剧透细分轴（轻量 fail-open）

> iter047 子迭代 4/4（收尾）。总计划见 `iteration_047_PLAN.md`。

## Context

在 047b 的起点制（chapter_id）KB/实体/事实过滤之上，加**可选**「读者已知 vs 角色已知」细分轴，防止把读者尚未读到的反转写进某 POV。轻量 fail-open，**不建完整逐角色知识图**。

## Changes

- `entities._relationship_is_spoiler(rel, is_after_start, *, viewpoint=None)` + `render_active_state(..., viewpoint=None)`：active timeline 项可选 `reader_known`（读者获知章，`is_after_start` → 隐藏）；`character_known{char_id:章}`（viewpoint 给定且**明确**该 POV 起点后获知 → 隐藏，**缺该 char → 保留 fail-open**）。
- `manual_facts._fact_has_spoiler_evidence` + `schemas.GlobalFact.reader_known_after`：fact 可选 `reader_known_after`。
- 4 调用方默认 `viewpoint=None`（reader 视角，reader_known 全局生效）；character_known 仅 viewpoint 给定时激活（预留，当前无调用方传）。

## Acceptance Result

通过（mock-only）。

- `tests/test_reader_character_filter.py` → **5 passed**（缺新字段逐字不变；reader_known 起点后隐藏；character_known POV 知/不知/**缺 char fail-open**；无 start point 关过滤；fact reader_known_after 隐藏）。
- 全量回归（3.13）：`.venv/bin/python -m pytest tests/ -q` → **641 passed, 3 failed**（3 个既有、与本子迭代无关）。
- 子代理对抗 review = **fix-then-ship**：消费端 byte-identical 经 sha 实证；**H1**（character_known map 缺 char 时 fail-CLOSED，与 fail-open 原则/docstring 矛盾 → 改为「仅明确该 POV 起点后获知才隐藏」，缺 char 保留）已修；**L1**（补「缺 char fail-open」+「无 start point 时 reader_known 不生效」两条断言）已补。
- 记录备查（非阻塞）：**M1** `GlobalFact.reader_known_after` 进入 bootstrap `GlobalFactsProposal` 注入 schema → 真实模型可能脑补，建议后续在 auto_bootstrap instructions 注明「留空」；**M2** reader_known/character_known/reader_known_after **当前无生产者**，dormant（schema 先行、消费就绪，fail-open 保证零行为变化），待 extractor/人工 authoring 产出后才有端到端价值。
- 全程 mock，未跑真实模型，未 push。

## 已知后续

配套生产者（extractor 标注 reader_known / bootstrap reader_known_after / 人工 authoring）落地后本轴才产生端到端价值（reader_known 优先于 character_known）。
