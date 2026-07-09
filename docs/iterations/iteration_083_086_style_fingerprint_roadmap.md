# Iteration 083-086 - 文风指纹路线图（PlotPilot VoiceFingerprint 对比后）

## Context

本文件是 2026-07-09 只读分析 session 的交接文档，不是单轮实现记录。具体实现应从 `iter083` 开始，每轮仍按 `AGENTS.md` 要求先使用 `iter-start` 建标准 8 段 iteration 文档，收尾使用 `iter-finish` 同步验收、审查、README SOP 与 `docs/AGENT_HANDOFF.md`。

用户要求对比同类开源项目 PlotPilot 的 VoiceFingerprint 能力，补齐本项目当前缺失的三件事：

- 量化文风指纹：句长、段长、对话占比、对比句频、AI 腔词密度等可复测指标。
- 风格漂移检测 + 告警：章节草稿与 baseline 的分维度偏离、总分和 severity。
- 偏离自动定向重写闭环：检测到严重偏离后，生成具体 rewrite directive，复用现有 writer/reviewer 重写链并复评分。

当前仓库真实最新迭代是 `iter082`，用户贴入的 AGENTS 快照停在 `iter080`。路线应接在 `iter082` 后，规划为 `iter083-086`。

## PlotPilot 对比结论

只读检查对象：

- 仓库：`shenminglinyi/PlotPilot`
- 分支：`master`
- commit：`0011e503ce577489eac6e4ee8f4eeedc7f3bc2b5`
- 关键参考：
  - `application/analyst/services/voice_sample_service.py`
  - `application/analyst/services/voice_fingerprint_service.py`
  - `application/analyst/services/voice_drift_service.py`
  - `application/analyst/services/llm_voice_analysis_service.py`
  - `infrastructure/persistence/database/sqlite_chapter_style_score_repository.py`
  - `engine/runtime/daemon_host.py`
  - `engine/runtime/audit_delegate.py`
  - `infrastructure/ai/prompt_packages/nodes/voice-rewrite/package.yaml`

PlotPilot 默认统计模式：

- 样本入口：保存 `ai_original + author_refined`，以作者改稿 `author_refined` 聚合为 voice fingerprint。
- 默认指纹字段：`adjective_density`、`avg_sentence_length`、`sentence_count`。
- 指纹重算阈值：每 10 个样本重算一次。
- 相似度：函数名叫 `_cosine_similarity`，但实际是形容词密度和平均句长两个维度的相对接近度平均；`sentence_count` 存储但不参与相似度。
- 告警：连续 5 章低于 `0.75` 触发 drift alert；但 `list_by_novel(limit=10)` 按 `chapter_number ASC LIMIT 10` 取前 10 章，再取 `valid_scores[-5:]`，长篇场景会固定检查早期窗口而非真正最近窗口。
- 自动修文：实际主路径在 runtime audit 层，`audit_delegate.run_chapter_audit()` 先 `_score_voice_only()`，再由 `daemon_host._apply_voice_rewrite_loop()` 最多 3 轮定向修文并复评分，之后才进入章后审计/索引；`engine/pipeline/base.py::_apply_voice_rewrite_loop()` 只是占位。
- 自动修文触发条件：`_should_attempt_voice_rewrite()` 只看 `similarity_score < 0.68`，不强依赖 `drift_alert=True`；`drift_alert` 更像 operator-facing warning。

PlotPilot LLM 模式：

- 8 维向量：`narrative_voice`、`dialogue_ratio`、`description_depth`、`emotional_intensity`、`pacing`、`sensory_richness`、`metaphor_usage`、`sentence_variety`。
- baseline/tolerance：少样本时均值 + 标准差，多样本时可用 LLM baseline。
- JSON 解析失败会回退中性 0.5 向量，避免阻断但也可能掩盖分析失败。
- 默认依赖装配未启用 LLM 模式，且持久化仍压到旧三列（把部分 LLM 维度映射成 `adjective_density` / `avg_sentence_length` / `sentence_count`），信息损失明显。

可借鉴点：

- 样本、baseline、章节评分三层边界清楚。
- 先评分，再严重偏离时有限次定向修文，再复评分，再章后索引，工程顺序合理；这点比单纯事后报告更接近生产闭环。
- 漂移先告警和有限修正，不轻易删除章节。
- rewrite prompt 明确“不改剧情事实，只改叙述语气、句式节奏与措辞密度”。

不应照搬点：

- 默认指标太粗，不能代表作者文风。
- `None` 基准被落盘为 `0.0` 容易误报样本不足为低分。
- 告警窗口取早期章节而非最近章节，存在长篇实现 bug 风险；本项目必须显式按章号取最近窗口并加测试。
- `engine/pipeline/base.py` 的 voice rewrite loop 是占位，不能把注释当主实现；应以 runtime audit path 为准。
- 数据契约存在扁平/嵌套结构缝隙，真实 DB 路径可能拿不到 prompt style summary。
- LLM 失败回退中性向量虽然稳定，但不应无痕吞掉；本项目至少要在 meta/report 里显式记录 `skipped` / `analysis_failed`。

## 本仓库现状

已有可复用能力：

- `src/style.py::load_style_examples()`：加载 `data/style_examples/*.md`，缺失目录、坏编码、空文件均 graceful degrade。
- `src/writer_style.py`：已有作家风格卡体系、预置库、上传样本提取、反污染 n-gram 护栏、prompt 注入。注意该卡仅用于 premise 自创书；续写书有起点时不注入。
- `src/linter.py::NovelLinter`：已有 deterministic lint，包括章节标记、`not_x_but_y`、开头短句过密、称谓漂移、AI 腔词、章节过短。
- `src/reviewer.py::review_text()`：已有 `rewrite_suggestions` 通道，advisor agent 不投票，只输出结构化建议。
- `src/writer.py::_review_feedback()`：已有分层回灌模板，会把 `rewrite_suggestions` 放进“改写顾问建议”并进入下一轮写作。
- `src/outline_drift.py`：已有剧情大纲漂移 warn/severe 模式，可借鉴 codes/severity 形状，但不能复用为文风漂移。
- Web 章节详情 API 已把 `chapter_NN.meta.json` 作为 `meta` 返回，前端可直接展示新增的 `style_drift` 字段，无需新 API。

当前缺口：

- 没有 per-chapter 数值风格向量。
- 没有 baseline artifact。
- 没有风格漂移分数、分维度 delta、severity。
- 没有把风格偏离翻译成具体 rewrite directive。
- 没有“重写后复测”的闭环。

## Roadmap

### Iter083 - 量化文风指纹 Baseline v1

目标：先做纯本地、确定性、版权安全的文风指纹，不接告警和 rewrite。

实现要点：

- 新增 `src/style_fingerprint.py`。
- 新增 `config/style_fingerprint.yaml`。
- 新增 `paths.style_fingerprint_dir()` 和 `paths.style_fingerprint_baseline_path()`。
- 指纹计算必须是纯本地、确定性、无 LLM 的纯函数；后续 LLM 风格分析可另起迭代，不混进 v1。
- 字段契约建议包含：
  - `schema_version`
  - `fingerprint_version`
  - `language`
  - `metrics`
  - `dimension_stats`
  - `dimension_reliability`
  - `tolerance`
  - `weights`
  - `baseline_quality`
  - `source_labels`
  - `source_hashes`
- 指标建议：
  - `char_count`
  - `chinese_char_count`
  - `sentence_count`
  - `avg_sentence_length`
  - `sentence_p50`
  - `sentence_p90`
  - `short_sentence_ratio`
  - `long_sentence_ratio`
  - `paragraph_count`
  - `avg_paragraph_chars`
  - `dialogue_line_ratio`
  - `quote_span_ratio`
  - `punctuation_density`
  - `question_exclaim_density`
  - `ellipsis_density`
  - `contrast_sentence_density`
  - `ai_cliche_density`
  - `sensory_imagery_density`
  - `exposition_connector_density`
- `config/style_fingerprint.yaml` 放维度权重、tolerance floor、样本最小字数、长短句阈值、词表；`ai_cliche_density` 词表优先复用/镜像 `config/linter.yaml`，避免两套“AI 腔”口径漂移。
- baseline artifact：`data/style_fingerprint/baseline.json`，只存统计量、tolerance、hash、sample count、source labels，不存原文片段。
- `baseline_quality` 至少记录 `sample_count`、`distinct_source_count`、`total_sample_chars`、`confidence`、`insufficient_reason`；样本不足时写 skipped/insufficient 状态，不写假 0。
- CLI：
  - `python3 main.py style-fingerprint build-baseline`
  - `python3 main.py style-fingerprint inspect-draft --chapter N`
- baseline 来源优先级：
  - `data/style_examples/*.md`
  - 若后续实现需要，可扩展到起点前原文窗口，但 iter083 可先只做 style examples，避免版权与起点边界复杂度。
- 缺样本时返回 `status=insufficient_source`，不报错，不阻断 pipeline。

验收重点：

- 无 `data/style_examples` 时 graceful degrade。
- 合成文本 baseline 可稳定生成。
- baseline JSON 不含长原文片段；测试应扫描样本文本中的长连续片段不出现在 baseline。
- 样本不足时 `status=insufficient_source`，不会生成看似可用的 0 值 baseline。
- 指标计算对同一输入多次运行 byte-stable。
- 不接 writer/reviewer/Web。

### Iter084 - 风格漂移检测 + 告警

目标：把 draft 指纹和 baseline 比较，产出 drift score、分维度差异和 operator-facing 告警，但仍不改写、不阻断。

实现要点：

- 新增 `src/style_drift.py`。
- 计算每个维度的 normalized delta：`abs(current - baseline) / tolerance`，cap 到合理范围。
- 聚合 `style_drift_score`，建议按 `config/style_fingerprint.yaml` 权重；低 reliability 或 baseline 缺失维度跳过，不把缺值当 0。
- severity 固定：
  - `ok`: score `< 0.35`
  - `warn`: score `>= 0.35`
  - `red`: score `>= 0.55`
- report 至少包含 `top_dimensions`（按 weighted delta 降序）、`skipped_dimensions`、`basis`（baseline hash/version/status）。
- `chapter_NN.meta.json` 写入：
  - `style_fingerprint`
  - `style_drift`
  - `baseline_hash`
- CLI：
  - `python3 main.py style-drift --chapter N`
  - `python3 main.py style-drift-report`
- Web 章节详情增加只读 drift badge 和维度表。
- 不修改 `panel_block_policy`，不把 red drift 翻成 Reject。
- `style-drift-report` 若展示多章趋势，必须显式按 `chapter_no` 降序/最近 N 章取窗口，避免继承 PlotPilot 的早期窗口 bug。

验收重点：

- 相似合成稿为 `ok`。
- 解释腔长句稿为 `red`。
- baseline 缺失时 meta 记录 skipped 或 CLI 返回 skipped，不影响 write/review。
- Web 渲染不泄原文，只展示指标。
- 最近窗口排序有测试：章节数超过窗口上限时，report 使用最新章节而不是最早章节。

### Iter085 - 偏离维度到定向改写建议

目标：把 drift 的“哪儿偏了”翻译为结构化 rewrite guidance，接进现有 `rewrite_suggestions` 和 writer feedback，但不主动增加重写轮次。

实现要点：

- 新增 `StyleRewriteDirective` schema，字段：
  - `dimension`
  - `severity`
  - `section_hint`
  - `target_metric`
  - `current_value`
  - `target_range`
  - `guidance`
- 在 `style_drift.py` 中实现 drift-to-directives 映射：
  - 平均句长过长 → 拆长句，减少解释性从句。
  - 平均句长过短/短句过密 → 合并碎句，恢复叙事流动。
  - 对话占比过低 → 增加角色行动/对话承载信息。
  - 对话占比过高 → 用动作、环境和心理停顿承接信息，避免对白堆叠。
  - 解释连接词过密 → 删“因此/于是/这意味着”类总结。
  - 对比句频过高 → 改成动作/环境反应。
  - AI 腔词密度高 → 换成具体动作、感官或物件。
- directive 数量默认限制 5 条，和 `writer._review_feedback()` 现有 advisor 消费上限对齐。
- `reviewer.review_text()` 在 report 末尾追加 `_advisor="style_drift_advisor"` 的 `rewrite_suggestions`，不参与投票、不翻 verdict。
- `writer._review_feedback()` 现有格式可直接消费；必要时只做小幅展示增强。
- Web 评审页展示 advisor 建议即可，不新增生成入口。

验收重点：

- 构造 red drift report，review JSON 有具体 directives。
- writer feedback 包含 `style_drift_advisor` 和可执行 guidance。
- verdict 不因 drift 单独翻转。
- 不新增 LLM agent。
- 同一 drift report 多次生成 directives 顺序稳定。

### Iter086 - 风格漂移自动定向重写闭环

目标：配置开启时，red drift 可触发一次定向 rewrite，重写后重新量化，形成“检测告警 → 指令 → 改写 → 再检测”的闭环。

实现要点：

- `config/style_fingerprint.yaml` 增加：
  - `style_drift_rewrite.enabled: true`
  - `style_drift_rewrite.trigger_severity: red`
  - `style_drift_rewrite.max_style_rewrites: 1`
  - `style_drift_rewrite.min_improvement: 0.08`
- 在 `writer.write_chapters()` review approve 前插入 style drift gate：
  - baseline 缺失或样本不足 → no-op。
  - red 且启用 → 合成 soft Reject + directives，进入既有 rewrite loop。
  - 不制造 hard synthetic reject，不污染 `hard_reject` 语义。
- style rewrite 要使用独立 `style_rewrite_count`，不要混淆既有 `rewrite_count`（review/lint rewrite）。
- rewrite 后必须重新跑 fingerprint + drift，比较 `style_drift_score` 改善幅度；未达到 `min_improvement` 时记录 unresolved。
- 重写后复测，meta 写入：
  - `style_rewrite_count`
  - `style_drift_before`
  - `style_drift_after`
  - `style_drift_unresolved`
- 若重写后仍 red：
  - 不无限循环。
  - `needs_human_review=true`。
  - 保留最终草稿和 before/after 证据。
- `chapter_status` 可透出 `style_drift_unresolved`，但不要让它变成默认 blocker，除非后续真模型校准证明阈值可靠。
- 预算检查必须覆盖 style rewrite 之后的额外 LLM 调用；不要在预算不足时先改写再失败。

验收重点：

- 测试中 patch/mock 两版 draft：第一版 red，第二版改善。
- 自动 rewrite 只触发一次。
- meta 留 before/after 和 `style_rewrite_count=1`。
- baseline 缺失时行为 byte-identical。
- 预算检查仍在 rewrite 后执行。
- style rewrite 未改善时标 `style_drift_unresolved=true`，但不制造 hard halt。

## Cross-cutting Design Notes

- 不复用 PlotPilot 的三列持久化模型；本项目直接在 `chapter_NN.meta.json` 和 `data/style_fingerprint/baseline.json` 保留完整结构，避免 LLM/统计维度被压扁。
- 不把 `None` / 缺 baseline / 分析失败写成 0 分；所有 no-op 都要显式有 `status` 和 `reason`。
- 文风 drift 是“质量告警 + 定向修文信号”，不是剧情一致性或计划履约信号；不要接入 `hard_reject`、`panel_block_policy` 或 readiness blocker。
- v1 以中文续写为主，但字段命名保留 `char_count` / `language`，避免后续英文 workspace 扩展时改 schema。
- 任何 report、meta、Web UI 都只展示指标、delta、hash、source label，不展示样本原文。

## Test Plan

每轮收尾都跑：

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests
PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
.venv/bin/python3 main.py preflight
OPENAI_MODEL=mock .venv/bin/python3 main.py preflight
git diff --check
```

建议新增/扩展测试：

- `tests/test_style_fingerprint.py`
- `tests/test_style_drift.py`
- `tests/test_style_rewrite_directives.py`
- `tests/test_writer_style_drift_loop.py`
- `tests/test_style_drift_report_window.py`
- 扩展 `tests/test_writer_advisor_feedback.py`
- 扩展 `tests/test_reviewer_advisor_consumption.py`
- 扩展 `tests/test_web_routes_get.py`
- 必要时扩展 `tests/test_chapter_status.py`

## Implementation Guardrails

- 不触碰 `.env`。
- 不触碰 `小说txt/` 原文。
- 不主动写入 `data/style_examples/*.md` 或任何龙族原文片段。
- `data/style_fingerprint/baseline.json` 是 gitignored artifact，只由用户本地 workspace 生成。
- 单测必须 mock-only。
- 真模型 smoke、真模型阈值校准、10-20 章 capstone 均另起独立迭代并等待用户授权。
- 当前未跟踪文件 `续写工作台.pptx` 视为用户文件，保持不动。
- 本路线图文件当前是未跟踪文档；实现 iter083 时再按 `iter-start` 生成正式 8 段单轮记录，不把本文件当 acceptance result。

## Suggested Follow-up Prompt

```text
你现在在 /Users/dingyuxuan/Desktop/Agent续写项目。请先阅读 AGENTS.md，然后阅读 docs/AGENT_HANDOFF.md、docs/iterations/README.md、docs/iterations/iteration_083_086_style_fingerprint_roadmap.md。

目标：按路线图启动 iter083「量化文风指纹 Baseline v1」，只实现 iter083，不要提前做 iter084-086。

硬约束：
- 显式使用 iter-start skill 创建 docs/iterations/iteration_083_<slug>.md 的标准 8 段文档，并更新 docs/iterations/README.md。
- 不碰 .env、data/ 私有内容、outputs/、小说txt/；不要写入任何原文片段。
- 当前未跟踪的 续写工作台.pptx 是用户文件，保持不动。
- 默认 mock-only，不跑真模型 smoke。

实现范围：
- 新增 src/style_fingerprint.py。
- 新增 config/style_fingerprint.yaml。
- 在 src/paths.py 增加 style_fingerprint_dir() 和 style_fingerprint_baseline_path()。
- 在 main.py 增加 CLI：
  - python3 main.py style-fingerprint build-baseline
  - python3 main.py style-fingerprint inspect-draft --chapter N
- baseline 写到 data/style_fingerprint/baseline.json，只存统计量、tolerance、hash、sample_count、source labels，不存原文。
- baseline 还要记录 schema_version、fingerprint_version、language、dimension_reliability、weights、baseline_quality（sample_count/distinct_source_count/total_sample_chars/confidence/insufficient_reason）。
- 指标至少包含：char_count、chinese_char_count、句长均值/p50/p90、短句/长句比例、段长、对话行占比、引号 span 占比、标点密度、对比句频、AI 腔词密度、感官/意象词密度、解释连接词密度。
- 无 data/style_examples 或样本不足时 graceful degrade，返回 insufficient_source，不报错，不生成假 0 baseline。
- 本轮不要接 writer/reviewer，不做 drift severity，不做 Web UI。

测试：
- 新增 tests/test_style_fingerprint.py。
- 覆盖无样本 graceful degrade、合成文本 baseline 稳定生成、baseline JSON 不含长原文片段、inspect-draft 可对合成 draft 输出同一指标形状。
- 跑聚焦测试后再跑：
  PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests
  PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
  .venv/bin/python3 main.py preflight
  OPENAI_MODEL=mock .venv/bin/python3 main.py preflight
  git diff --check

收尾：
- 使用 iter-finish skill 回填 iter083 Acceptance Result。
- 按铁律⑨做只读 code review/security review，结论写入 iteration 文档。
- 同步 README SOP 与 docs/AGENT_HANDOFF.md。
- 不 push。
```
