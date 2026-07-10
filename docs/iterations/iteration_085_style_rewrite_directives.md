# Iteration 085 - 文风偏离到定向改写建议

## Context

Iter083 已交付纯本地文风指纹 baseline，iter084 已交付 draft 与 baseline 的分维度 drift score、severity、meta 留痕和 Web 告警。当前 `style_drift.top_dimensions` 能说明“哪些统计偏了”，但尚未转成 reviewer/writer 能直接消费的具体改写指令。

本轮承接 `iteration_083_086_style_fingerprint_roadmap.md` 的 iter085：只做确定性 drift-to-directives 和既有 advisor 通道接线，不触发额外重写，不改变 verdict/hard reject/readiness；自动定向重写与复测留待 iter086。

## Plan

- 新增 `StyleRewriteDirective` schema，固定维度、severity、位置提示、目标指标、当前值、目标区间与可执行 guidance。
- 在 `src/style_drift.py` 中把 warn/red report 的可支持 top dimensions 映射为最多 5 条稳定排序 directive，目标区间为 baseline ± tolerance（下限 0）。
- 覆盖句长过长/过短、短句过密、对话占比过低/过高、解释连接词、对比句和 AI 腔词密度偏高。
- `reviewer.review_text()` 在既有 verdict 完成后追加 `_advisor="style_drift_advisor"` 的 `rewrite_suggestions`，补齐 `section/type` 兼容字段，不参与投票。
- writer 继续通过既有 `_review_feedback()` 前 5 条通道消费；Web 复用 Advisor tab，不新增 API 或生成入口。

## Acceptance

- red 合成 drift report 产生带完整 directive 字段和 `style_drift_advisor` 标识的 review JSON。
- 相同 report 多次生成顺序稳定，输出最多 5 条；`ok`/`skipped`、缺字段、非有限值和不支持维度不产生建议。
- 目标区间使用 baseline ± tolerance 且下限不为负；建议方向与 current/baseline 偏离方向一致。
- drift 建议不改变 `verdict`、`hard_reject`、票数、`agent_reviews` 或 writer 重写次数。
- writer feedback 包含 `style_drift_advisor` 和可执行 guidance，仍遵守既有前 5 条上限。
- Web Advisor tab 对新字段安全渲染，不泄露 baseline 样本或额外正文。
- 收官命令：`.venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`、`git diff --check`。

## Implementation Notes

- `src/schemas.py` 新增 `StyleTargetRange` 和 `StyleRewriteDirective`。区间固定 `min/max`，两端与 `current_value` 必须是非负有限数，且 `min <= max`；避免 NaN/Infinity 进入 review JSON。
- `style_drift.build_rewrite_directives()` 仅消费 `status=ok` 且 severity 为 warn/red 的 `top_dimensions`，按 `weighted_delta` 降序、dimension 升序稳定排序，最多 5 条。当前值必须严格越过 `baseline ± tolerance` 才产生建议，落在区间内或恰好命中边界均 no-op。
- 确定性映射覆盖平均句长过长/过短、短句过密、对话行/引号占比过低/过高、解释连接词、对比句和 AI 腔词密度偏高；guidance 统一要求不改剧情事实。
- `style_drift.rewrite_directives_for_text()` 复用现有本地 fingerprint/baseline/drift 链，缺 baseline 或分析不可比时返回空建议。
- `reviewer.review_text()` 在 verdict、票数与 hard-reject 状态已确定后运行 style advisor，不新增 LLM 调用。directive 保留完整数值依据，并补齐 `section/type/_advisor` 进入既有 `rewrite_suggestions` 通道。
- 为避免 writer 既有 `[:5]` 上限吞掉其他 advisor，新增合并配额：style 存在时，前 5 条为 `plan_compliance` 和原 advisor 各保留 1 席，style 使用剩余席位；完整 report/Web payload 仍保留所有建议。style 不存在时保持旧顺序。
- Web 继续复用章节详情 Advisor tab，只渲染经 `escapeHtml()` 的 `type/section/guidance`，不渲染 target range、baseline 或样本文本。

## Acceptance Result

- 聚焦回归：`tests.test_style_rewrite_directives tests.test_reviewer_advisor_consumption tests.test_writer_advisor_feedback tests.test_static_subscore_compat tests.test_style_drift tests.test_reviewer_plan_compliance` **54 tests OK**。
- `.venv/bin/python3 -m unittest discover -s tests`：**1738 tests OK**（288.003s）。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`：exit 0；内部 **1738 tests OK**（253.748s），随后 normalize/split/auto-pipeline/status/manifest/report/cost 全部通过。
- `.venv/bin/python3 main.py preflight`：`PREFLIGHT: warn`，无 FATAL；WARN 为当前真实配置态的 tiktoken model mapping、cache provider 与默认预算提示。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：`PREFLIGHT: ok`，无 WARN/FATAL。
- `git diff --check`：通过。真模型 smoke 未跑（铁律⑥）。
- correctness 只读 subagent 发现 2 项并已修：区间内维度误发 red directive；5 条 style 建议会吞掉 plan/legacy advisor。修后复核通过，无新 correctness blocker。
- security/boundary 只读 subagent 发现 1 项 P2 并已修：两个有限大数相加可溢出 Infinity，且旧 `target_range` dict 过宽。补 finite/order/schema 守门与真溢出回归后复核通过。
- 主线复核确认：新路径不记录正文/baseline 样本，不新增 LLM 调用或 Web 生成入口，不改 `verdict/approve_count/hard_reject/agent_reviews/rewrite_count`。未修风险仅为自动重写与复测未接，按路线图留 iter086。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/schemas.py` | 新增有限非负的目标区间与 `StyleRewriteDirective` schema。 |
| `src/style_drift.py` | 新增稳定、有界、容错的 drift-to-directives 映射。 |
| `src/reviewer.py` | 接入非投票 style advisor，并为 writer 前 5 条建议建立跨 advisor 配额。 |
| `tests/test_style_rewrite_directives.py` | 新增映射、方向、目标区间、排序、上限、schema 与溢出测试。 |
| `tests/test_reviewer_advisor_consumption.py` | 覆盖非投票接线、无新 LLM 调用与混合 advisor 配额。 |
| `tests/test_writer_advisor_feedback.py` / `tests/test_static_subscore_compat.py` | 覆盖 writer 回灌和 Web 安全渲染兼容。 |
| `docs/iterations/README.md` / `README.md` / `AGENTS.md` / `docs/AGENT_HANDOFF.md` | iter085 立项与收官 SOP 同步。 |

## 不在本轮范围

- iter086 的 red drift 自动定向重写、重写后复评分、`style_rewrite_count` 和 unresolved 状态。
- 任何新 LLM agent、真模型 smoke、`panel_block_policy`、readiness blocker 或 hard reject 接线。
- 重新设计 baseline/drift schema，或在 Web 增加新的生成入口。

## Notes

- 本轮立项显式使用 `iter-start` skill；收尾使用 `iter-finish`，并按项目约定记录 correctness 与 security/boundary 两个独立只读 subagent 审查结论。
- 仓库外 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在，本轮以仓库内路线图为权威规划。
- 不改 `.env`，不跑真模型，不读写用户私有样本或 `小说txt/`；未跟踪 `续写工作台.pptx` 保持不动。
- 开工前已按用户选择将 iter084 独立复验并提交为 `477c32c`，本轮 diff/commit 不混入 iter084。
- 本轮不根据统计指标定位具体原文段落，`section_hint` 是可执行的段落类型提示；精确定位需另起设计，本轮不虚构 anchor。
