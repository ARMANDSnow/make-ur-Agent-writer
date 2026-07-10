# Iteration 084 - 文风漂移检测 + 告警

## Context

`iteration_083_086_style_fingerprint_roadmap.md` 将文风指纹路线拆为 baseline、漂移告警、定向建议与自动重写四步。iter083 已交付纯本地 `style_fingerprint` baseline artifact 和 draft 指标检查，但仍未把章节草稿与 baseline 做对比，也没有 severity、meta 留痕或 Web 只读展示。

本轮承接 iter084：只做文风漂移检测与告警。drift 是 operator-facing quality signal，不改变 writer/reviewer verdict，不阻断 readiness/write-book，不接自动重写；真实模型 smoke 不在本轮范围。

## Plan

- 新增 `src/style_drift.py`：读取 baseline 的 `metrics/tolerance/weights/dimension_reliability/baseline_hash`，计算 per-dimension normalized delta、聚合 `style_drift_score` 与 `ok/warn/red` severity。
- 扩展 CLI：新增 `style-drift --chapter N` 合并写入已有 chapter meta；新增 `style-drift-report [--limit N]` 按最近章节窗口输出趋势。
- 接入 writer：成功与 lint-failure meta 持久化时写入 `style_fingerprint`、`style_drift`、`baseline_hash`；缺 baseline 或检测失败只记录 skipped，不改 verdict/review/rewrite 语义。
- Web 章节详情新增文风 drift badge 与只读“文风”tab，展示 severity、score、baseline hash、top dimensions 与 skipped dimensions，不展示原文片段。
- 新增/扩展测试覆盖 drift scoring、skipped 场景、meta 合并、最近窗口排序、CLI parser、Web UI hook、writer mock meta。

## Acceptance

- 相似合成稿 drift severity 为 `ok`；解释腔长句稿为 `red`。
- baseline 缺失或 `insufficient_source` 时返回/写入 skipped，不制造 0 分，不影响 draft/review。
- 缺维度、低可靠度、缺 tolerance 或非有限值进入 `skipped_dimensions`，不参与加权平均。
- `style-drift --chapter N` 只在已有 meta 文件存在时合并写入，不创建半 meta；保留原 `verdict`、`needs_human_review`、`rewrite_count`、`draft_sha256`。
- `style-drift-report --limit N` 明确按 `chapter_no` 降序取最近窗口，避免早期窗口 bug。
- Web 章节详情只展示数值指标和 hash，不泄露 baseline 样本或 draft 原文片段之外的内容。
- 验收命令：`.venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`、`git diff --check`。

## Implementation Notes

- 新增 `src/style_drift.py`，复用 iter083 的 `style_fingerprint.calculate_metrics()` 生成 draft 指标，再读取 baseline 的 `metrics` / `tolerance` / `weights` / `dimension_reliability` / `baseline_hash` 做对比。公式按计划落地：`normalized_delta = min(abs(current - baseline) / tolerance, 3.0)`，`dimension_score = normalized_delta / 3.0`，总分为有效维度加权平均，severity 固定为 `ok <0.35`、`warn >=0.35`、`red >=0.55`。
- skipped 语义保持 fail-closed：baseline 缺失、`insufficient_source`、baseline 字段不完整、无可比较维度时 `status/severity=skipped` 且 `style_drift_score=null`；缺维度、缺/非正 tolerance、非有限值、低可靠度、非正 weight 均进入 `skipped_dimensions`，不按 0 分参与平均。
- `style-drift --chapter N` 会读取 `outputs/drafts/chapter_NN.md`，输出 fingerprint + drift 报告；仅当 `chapter_NN.meta.json` 已存在且是非空 dict 时才合并写入，不创建半 meta。合并只新增/更新 `style_fingerprint`、`style_drift`、`baseline_hash`，保留原 verdict/hash/rewrite 字段。
- `style-drift-report [--limit N]` 只读 `chapter_*.meta.json`，按 `chapter_no` 降序取最近窗口，默认 10，上限 200；缺 drift 的章节以 skipped 行展示，避免早期窗口 bug。
- `writer.write_chapters()` 在 lint-failure 持久化和正常持久化两条路径写 meta 前调用 `style_drift.annotate_meta()`。该函数内部 catch-all，drift 失败只写 skipped，不改变 `verdict`、`needs_human_review`、`rewrite_count`、`draft_sha256` 或 reviewer/linter 决策。
- Web 章节详情顶部新增文风 badge，并新增“文风”tab；展示 severity、score、baseline hash、fingerprint status、top dimensions 与 skipped dimensions。前端只渲染数值指标/hash/reason，并经过 `escapeHtml()`，不展示 baseline 样本或额外原文片段。
- 审查中修正五处边界：corrupt baseline `sample_count` 不再抛 `ValueError`/`OverflowError`；显式传入空 baseline 不再因假值回退读取磁盘 baseline，而是按缺失 baseline skipped；缺/非有限 weight 进入 `skipped_dimensions`，不再默认 1.0；skipped 复测会清理旧 `baseline_hash`；Web/报告不再用旧 top-level hash 回填 skipped 结果。

## Acceptance Result

- `.venv/bin/python3 -m unittest discover -s tests`：**1723 tests OK**（75.139s；需允许本地端口绑定测试）。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`：exit 0；内部 **1723 tests OK**（230.986s），随后 auto-pipeline/status/manifest/report/cost 全部通过。
- `.venv/bin/python3 main.py preflight`：exit 0，`PREFLIGHT: warn`，无 FATAL；WARN 为当前真实配置态的 tiktoken model mapping、cache provider 与默认预算提示。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：exit 0，`PREFLIGHT: ok`，无 WARN。
- `git diff --check`：通过。
- 聚焦回归：`tests.test_style_drift` **10 tests OK**；覆盖 ok/red、baseline missing/insufficient skipped、corrupt basis、低可靠/缺 tolerance/缺 weight skipped、meta 合并不写原文、半 meta 禁止、skipped 复测清旧 hash、report 最近窗口与 CLI parser。
- 多视角 subagent 审查（按用户要求补跑并固化为后续强制流程）：correctness subagent 发现 3 项有效问题并已修：缺/坏 `weights` 被默认 1.0、skipped 后旧 `baseline_hash` 可残留、`sample_count=Infinity` 可让 CLI 崩溃。security/boundary subagent 无安全 blocker，确认无真模型入口、无 `.env`/API key 泄漏、无原文/样本片段持久化、Web escape 到位；提示 `style-drift --chapter` 设计上会写已有 meta，与 writer 并发时仍可能 last-writer-wins。
- 主线程复核：补测上述 3 项并重跑受影响测试、完整 unittest、`verify.sh`、preflight 双态与 `git diff --check`。另将 `AGENTS.md` 与全局 `iter-finish` skill 更新为“每轮收官默认至少 2 个只读 subagents（correctness + security/boundary）”。
- 未修风险：drift 仍是 operator-facing signal，不阻断、不自动 rewrite；manual `style-drift --chapter` 与 writer 并发仍可能最后写入者覆盖 meta 字段（atomic JSON 可防半文件，不解决业务并发），rewrite directives 与 red drift 复测留 iter085/086。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/style_drift.py` | 新增文风漂移检测与报告。 |
| `main.py` | 新增 style drift CLI。 |
| `src/writer.py` | 写章 meta 时补充 drift 指标。 |
| `src/web/templates.py` / `src/web/static.py` | 章节详情文风只读展示。 |
| `tests/test_style_drift.py` | 新增 drift 核心与 meta/report 测试。 |
| `tests/test_writer.py` | 扩展 writer mock 路径断言：新增 meta 字段不改变 Approve/Reject 语义。 |
| `tests/test_web_routes_get.py` / `tests/test_static_subscore_compat.py` | 覆盖“文风”tab、badge 与维度表渲染入口。 |
| `README.md` / `AGENTS.md` / `docs/AGENT_HANDOFF.md` / `docs/iterations/README.md` | iter-finish SOP 同步。 |
| `/Users/dingyuxuan/.codex/skills/iter-finish/SKILL.md` | 更新全局 iter-finish skill：后续每轮收官默认至少 2 个只读 subagents 多视角审查。 |

## 不在本轮范围

- Iter085：把偏离维度映射为 rewrite directives 并接入 reviewer advisor/writer feedback。
- Iter086：red drift 自动定向重写与重写后复测闭环。
- 任意真模型 smoke、自动改写、hard reject、readiness blocker、`panel_block_policy` 接线。

## Notes

- 本轮立项显式使用 `iter-start` skill；收尾按 `iter-finish` 流程同步验收、审查、README SOP 与 `docs/AGENT_HANDOFF.md`。
- baseline 仍只来自用户本地 `data/style_examples/*.md`，本轮不读取或写入 `小说txt/` 原文，不改 `.env`。
- 未跟踪 `续写工作台.pptx` 是用户文件，保持不动。
- 下轮 iter085 可直接消费 `style_drift.top_dimensions` / `skipped_dimensions` / `basis.baseline_hash` 映射 rewrite directives；不要把 skipped 当作低风险绿灯，也不要在 writer/reviewer 里把 severity 当作 hard reject。
