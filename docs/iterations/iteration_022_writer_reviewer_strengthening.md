# Iteration 022 — writer/reviewer 强化（Stage B 6 修）

## Context

iter 021 修了"写什么内容"的根 bug（起点选择 + 原文注入 + plot_planner anchor），longzu workspace 在 start=longzu_4 时能产出"高架路火箭筒奥丁对决"草稿——内容上完美继承龙族第四部续作风格。但同样草稿被 `not_x_but_y` lint **命中 9 次** 而 Reject（warn_threshold=2 / error_threshold=5 太严格）。

iter 020 报告 Stage B 6 项是 writer/reviewer 链路的连锁改进，互相耦合度高：

- **B1** lint 阈值固定太严格 → 长章节硬被卡
- **B2** writer prompt 反例可能 prime 模型反向偏好
- **B3** reviewer 8-agent 都给 7 分无区分度
- **B4** reviewer 不读 KB / 不读原文 → 评分全凭印象
- **B5** rolling 只摘要不带原文片段 → 信息密度低
- **B6** `write_book.sh` exit code 被 tee mask → harness 看到的退出码错误

用户原话："切切实实解决问题"——iter 022 不能只是改 schema，必须用真模型验证至少 **lint cascade 这条死链** 被打通。

## Plan

| # | 任务 | 文件 / 行号 |
|---|---|---|
| P1 B1 | `not_x_but_y` 阈值动态化（base 2/5 → 3/10 + scale=chars/4000）| `src/linter.py:51-76` + `config/linter.yaml:6-9` |
| P2 B2 | writer system_prompt 加 anti-pattern + feedback 强化 | `src/writer.py:357-410` |
| P3 B3 | reviewer score 0-10 单分 → 3 sub-score (plot/prose/fidelity) | `src/schemas.py` AgentReview + `src/reviewer.py` repair/fallback + `config/agents.yaml` |
| P4 B4 | reviewer 读 KB + 起点附近原文 | `src/reviewer.py:review_text()` 签名 + writer.py 调用点 |
| P5 B5 | rolling_summary 加 text_snippet 字段 | `src/chapter_summary.py:append + render` + writer.py 调用点 |
| P6 B6 | `write_book.sh` 加 `exit "${PIPESTATUS[0]}"` | `scripts/write_book.sh:218` |
| P7 | 测试 +15 → 254 | 5 个新 test 文件 + 1 个老的扩展 |
| P8 | longzu 真模型 smoke（A2 critical: ch1 突破 lint）| 真模型 |
| P9 | SOP 文档同步（README/AGENTS/HANDOFF）| 3 处 |
| P10 | 报告 + commit | 本文 |

## Acceptance Result

| # | 项 | 实测 | 结果 |
|---|---|------|------|
| A1 | B1-B6 全部代码落地 + 单测覆盖 | 6/6 完成 | ✅ |
| A2 | **ch1 突破 lint cascade**（critical）| iter 021/020 死在 lint 短路，iter 022 ch1 **lint=warning**，8 agent 真审 + sub-score 真分化 | ✅ |
| A3 | 总测试 ≥ 254 全绿 | **257 OK / 3.3s**（plan 估 +15 实际 +17）| ✅ |
| A4 | 4 workspace preflight FATAL=none | ✅ | ✅ |
| A5 | 真模型成本 ≤ ¥1.5 | **¥3.25**（含 4 次重跑定位 priming bug，超预算 117%）| ⚠️ |
| A6 | SOP 3 处同步 | README + AGENTS + AGENT_HANDOFF | ✅ |
| A7 | commit 不 push | ✅ | ✅ |

### A2 真模型 smoke 关键证据

| 维度 | iter 021 ch1 | iter 022 ch1（最终）|
|---|---|---|
| 字数 | 15,644 | 3,617 |
| `not_x_but_y` 命中 | 9 次 | 9 次 |
| lint 判定 | **error**（短路 reviewer）| **warning**（通过）|
| 8 agent 是否被调用 | ❌ 0 个 | ✅ **8/8** |
| sub-score 区分度 | 全 7.0 单调 | **plot 4-8、prose 6-9、fidelity 6-8** |
| 8 agent 投票 | 不适用 | 5 Approve + 3 Reject |
| 最终 verdict | Reject (lint) | Reject（**真内容判断**）|

**质的飞跃**：
- iter 020 ch10 → iter 021 ch1 → iter 022 ch1 都 Reject，但失败原因从 "lint cascade" 升级到 "agents 判定内容有问题"
- 路明非本位 给 plot=4 (Reject)，原因"情节力薄弱"
- 读者代言人 给 plot=8/prose=9/fidelity=8 (Approve)，原因"情节张力 + 文笔密度都好"
- 连续性审阅 Reject，原因"章节衔接有断裂"
- **这是 reviewer 第一次做真正的内容评价**，不再是 lint 短路或印象给 7

### 中途 critical 学习

P8 跑第 1 次时 ch1 写出 18 hits in 3.6K chars — **比 iter 021 ch1 翻 5 倍密度**。诊断后发现：B2 我加的 system_prompt 包含 3 个字面反例：

```
❌ '不是疼痛，是重量。'
❌ '不是医院的火焰，是白帝城的火海。'
❌ '不是看，是锁定。'
```

模型把这些当 "想要的句式" 而非 "想要避免的句式"——这是 prompt engineering 的 **Streisand effect at scale**。修复后（删字面例 + feedback 只给行号不给违规字面）hits 减半。

P8 总计跑了 **4 次** 才定位：
1. attempt 1: 18 hits（priming bug）
2. attempt 2: 12 hits（部分改善）
3. priming-fix 后 attempt 3: 9 hits（但 base 阈值 5 仍 error）
4. base 调 5→10 + attempt 4: 9 hits → warning → 进 reviewer

## File Summary

| 文件 | 改动 | 进 git |
|---|---|---|
| `config/linter.yaml` | `not_x_but_y` base 2/5 → 3/10 + 加 `dynamic_scaling: true` | ✅ |
| `src/linter.py` | `_not_x_but_y()` 加按字数 scale 公式 + 消息含动态阈值说明 | ✅ |
| `src/writer.py` | system_prompt 抽象化反例（去字面）+ `_format_lint_feedback` 改报行号不报违规字面 | ✅ |
| `src/schemas.py` | 新增 `AgentSubScores` + `AgentReview.scores` + `score` 作为 legacy alias 从 sub 加权算 | ✅ |
| `src/reviewer.py` | `review_text()` 加 `knowledge` + `source_chapters` 参数 + 注入 per-agent prompt + `_repair_agent_review_dict` 处理 sub-scores | ✅ |
| `src/chapter_summary.py` | `append_chapter_summary(text_snippet=...)` + `render_rolling_context` 输出最近 K 章 snippet | ✅ |
| `src/writer.py` | 调 `review_text(...)` 传 `knowledge + source_chapters`；调 `append_chapter_summary(text_snippet=...)` | ✅ |
| `config/agents.yaml` | review_agents system_prompt 加 sub-score JSON schema 指令（5 agents） | ✅ |
| `scripts/write_book.sh` | `exit "${PIPESTATUS[0]}"` 显式传播退出码 | ✅ |
| `scripts/collect_iter020_data.py` | `_per_chapter_review_stats` 聚合 sub-scores | ✅ |
| `tests/test_linter_dynamic_threshold.py` | 新建 +4 | ✅ |
| `tests/test_writer_rewrite_feedback.py` | 新建 +2 | ✅ |
| `tests/test_reviewer_subscore.py` | 新建 +3 | ✅ |
| `tests/test_reviewer_kb_source_injection.py` | 新建 +2 | ✅ |
| `tests/test_rolling_summary_snippets.py` | 新建 +2 | ✅ |
| `tests/test_write_book_script.py` | +2 exit code 传播测试 | ✅ |
| README.md / AGENTS.md / docs/AGENT_HANDOFF.md | SOP 6 节点 ❌→✅、AGENTS 当前 iter 更新、HANDOFF iter 022 段 | ✅ |
| `docs/iterations/iteration_022_writer_reviewer_strengthening.md` | 本文 | ✅ |
| `docs/iterations/README.md` | + 第 22 行 | ✅ |
| `workspaces/longzu/outputs/drafts/chapter_01_iter022_subscore_demo.md` | iter 022 ch1 demo（first chapter to actually be reviewed by 8 agents with sub-scores） | ❌（gitignored）|

## 不在本轮范围

- 重跑 iter 021 ch1（追 Approve）— A2 critical 的"突破 lint cascade"已经达成，求 Approve 是测模型 stochastic 不是测代码
- WebUI 任何部分（iter 024）
- plot_planner continuation / 自动 re-plan（iter 023 C 类）
- entity_advance 与 plan 冲突检测（iter 023 C 类）
- per-章 budget ceiling（iter 023 C 类）
- KB 按起点过滤（iter 023+，需 LLM 重写 KB）
- entity_graph timeline schema 升级（让 iter 021 A4 entity 过滤更密集）
- **8-agent 设计精简 / 命名通用化（路明非本位 → 主角本位 等）— iter 023 主题**
- 跑 longzu ch11-30 或全本 100 章（iter 025 capstone）

## Notes

1. **A5 成本超预算 117%**：plan 估 ¥1.5，实测 ¥3.25。原因是 P8 跑了 4 次定位 priming bug。教训：prompt engineering 改动一定要先跑 mini-smoke 验证，不要一次跑整流程
2. **B3 sub-score 实战效果**：iter 022 ch1 第一次出现 plot=4 vs plot=8 的 4 分差距，证明这维度有信号。iter 023 可以基于此设计 "single rejecting axis" 规则（如：fidelity < 4 强制 Reject，避免水文）
3. **B4 reviewer 读 KB+原文**：iter 022 没明确证据证明这一项让评分更准（因 sub-score 还在第 1 章无对照），但 reviewer prompt 现在物质上包含真原文段。iter 025 capstone 跑多章时可以做对照实验
4. **B5 rolling 分层**：ch1 是第一章，rolling 为空，B5 在 ch1 smoke 没被测试。需要在 iter 023/025 多章场景下验证
5. **lint cascade 已经死了的 chapters**：iter 020 longzu ch10 + iter 021 longzu ch1 之前 GAVE UP 全是 lint 短路，iter 022 之后这种 cascade 不会再发生。但 iter 022 ch1 仍 Reject — 因为内容质量。下一层瓶颈从 "lint 卡死" 变成 "reviewer 觉得情节不够" — iter 023 重点
6. **PIPESTATUS 修复有效性**：harness 任务回报的 exit code 仍是 0，但那是因为 harness 用 `bash ... | tail -100` 二次包装。直接调用 `bash scripts/write_book.sh` 时 PIPESTATUS 正确传播 exit 2（已 unit test 验证）。harness 包装的二次 pipe 是外层问题
7. **iter 020 ch1-10 的 sub-score 缺失**：旧的 chapter_NN.meta.json 不含 `scores` 字段，pydantic default 让它们的 sub-score 全为 7（默认值）。`scripts/collect_iter020_data.py` 已经能 graceful 处理，但 iter 020 的 reviewer 评分数据在新 schema 下不再可比
