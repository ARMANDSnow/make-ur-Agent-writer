# Iteration 083 - 量化文风指纹 Baseline v1

## Context

`iteration_083_086_style_fingerprint_roadmap.md` 明确指出，本项目当前缺少可复测的 per-text 文风量化向量、baseline artifact、漂移分数与定向重写闭环。PlotPilot 的 VoiceFingerprint 思路可借鉴其“样本 / baseline / 章节评分”边界，但其默认指标过粗、样本不足落 0、漂移窗口取早期章节等问题不适合照搬。

本轮只启动 iter083：先做纯本地、确定性、版权安全的 baseline v1。baseline 来源仅限用户本地维护的 `data/style_examples/*.md`，输出只包含统计量、tolerance、hash、sample_count 与 source labels，不写入任何原文片段；缺目录或样本不足时 graceful degrade 为 `insufficient_source`，不阻断现有 mock-only 流水线。

## Plan

- 新增 `src/style_fingerprint.py`：实现纯函数指标计算、style_examples baseline 构建、draft 指标检查与 JSON artifact 生成。
- 新增 `config/style_fingerprint.yaml`：集中配置短/长句阈值、样本最小字数、tolerance floor、维度权重与词表。
- 扩展 `src/paths.py`：增加 `style_fingerprint_dir()` 与 `style_fingerprint_baseline_path()`，兼容 legacy/workspace path resolution。
- 扩展 `main.py` CLI：新增 `python3 main.py style-fingerprint build-baseline` 与 `python3 main.py style-fingerprint inspect-draft --chapter N`。
- 新增 `tests/test_style_fingerprint.py`：覆盖无样本 graceful degrade、合成文本 baseline 稳定生成、baseline JSON 不含长原文片段、合成 draft inspect 输出同一指标形状。
- 为 iter084-086 留清晰接力点：不接 writer/reviewer，不做 drift severity，不做 Web UI，不跑真模型 smoke。

## Acceptance

- `python3 main.py style-fingerprint build-baseline` 在无 `data/style_examples` 或样本不足时 exit 0，并输出/写入 `status=insufficient_source`。
- 合成 style examples 可生成 byte-stable `data/style_fingerprint/baseline.json`，包含指标、dimension_stats、tolerance、weights、baseline_quality、source_labels/source_hashes，不包含长原文片段。
- 指标至少包含：句长均值/p50/p90、短句/长句比例、段长、对话占比、标点密度、对比句频、AI 腔词密度、感官/意象词密度、解释连接词密度。
- `python3 main.py style-fingerprint inspect-draft --chapter N` 可对合成 draft 输出与 baseline 同形的指标结构，不依赖 baseline 存在。
- 验收命令：聚焦 `tests/test_style_fingerprint.py` 后，跑 `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`、`git diff --check`。

## Implementation Notes

- `src/style_fingerprint.py` 走纯本地确定性实现，不接 `LLMClient`，不读取 `.env`，也不接 writer/reviewer/Web。baseline 来源仅为 `data/style_examples/*.md`，测试里用临时目录和合成文本注入，避免写入或断言任何原文片段。
- baseline artifact 设计为只保留统计量与溯源摘要：`metrics`、`dimension_stats`、`dimension_reliability`、`tolerance`、`weights`、`baseline_quality`、`sample_count`、`source_labels`、`source_hashes`、`baseline_hash/hash`。未存 sample 文本、句子、段落或 excerpt。
- 无样本、目录缺失、总字数不足或样本数不足时统一返回并写入 `status=insufficient_source`，`metrics/stats/tolerance` 为空；不制造 0 值 baseline，避免后续漂移检测误判。
- `inspect-draft --chapter N` 只读取 `outputs/drafts/chapter_NN.md` 并输出同一指标 shape，不依赖 baseline 是否存在；缺 draft 或非法 chapter graceful degrade 为状态 JSON。
- 配置集中在 `config/style_fingerprint.yaml`：短/长句阈值、样本下限、tolerance floor、维度权重、AI 腔词/感官意象/解释连接词等词表与对比句 pattern。实现中对坏 pattern 和非 list 词表做容错，保证 mock-only 路径不因配置小错崩溃。
- `paths.py` 的 `style_fingerprint_dir()` / `style_fingerprint_baseline_path()` 跟随既有 `data_dir()`，兼容 legacy 根目录与 `--book` workspace。

## Acceptance Result

- 聚焦测试：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_style_fingerprint tests.test_paths -v`，23 tests OK。
- 全量单测：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`，1712 tests OK。首次裸 sandbox 运行时本地 `127.0.0.1` 端口绑定测试被拦，按既有验收口径改用授权执行后通过。
- 全量验收：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0；脚本内部同样 1712 tests OK，随后 normalize/split/auto-pipeline/status/manifest/report/cost 全跑通。`verify.sh` 写入 gitignored `data/`/`outputs/` 验证产物，本轮经用户明确授权执行；未手工读取或写入私有样本/原文。
- Preflight：`.venv/bin/python3 main.py preflight` = warn/无 FATAL（当前真实配置态模型/cache/budget 提示）；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok/无 WARN。
- 静态检查：`py_compile` 覆盖 `src/style_fingerprint.py`、`main.py`、`src/paths.py`、`tests/test_style_fingerprint.py`、`tests/test_paths.py` OK；`git diff --check` 通过。
- 代码审查（铁律⑨，只读）：未发现阻塞问题。核对重点为 baseline contract、insufficient source 不落假零、hash 稳定性、CLI 只做薄封装、path helper workspace 兼容、未接 writer/reviewer/Web/drift severity。
- 安全审查（铁律⑨，只读）：未发现 API key / `.env` 泄漏路径；无真模型调用；baseline JSON 不持久化原文片段；测试只使用合成文本与临时目录。运行时唯一新增写入是用户显式命令 `build-baseline` 下的 `data/style_fingerprint/baseline.json` 统计 artifact，符合本轮范围。
- 真模型 smoke 未跑，符合默认 mock-only 与铁律⑥。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/style_fingerprint.py` | 新增纯本地文风指纹指标、baseline 构建与 draft inspect。 |
| `config/style_fingerprint.yaml` | 新增文风指纹阈值、词表、权重与 tolerance 配置。 |
| `src/paths.py` | 新增 style fingerprint artifact path helpers。 |
| `main.py` | 新增 `style-fingerprint` CLI。 |
| `tests/test_style_fingerprint.py` | 新增 baseline 与 inspect-draft 回归测试。 |
| `tests/test_paths.py` | 覆盖 legacy/workspace 下新增 path helper。 |
| `README.md` | 同步 CLI 速查、项目阶段与 SOP 最近一次更新。 |
| `AGENTS.md` | 写入用户对 iter-finish 自动执行 `verify.sh` 的项目记忆，并同步当前状态。 |
| `docs/AGENT_HANDOFF.md` | 追加 iter083 Phase Status 与 iter084-086 接力点。 |
| `docs/iterations/README.md` / 本文件 | 登记 iter083。 |

## 不在本轮范围

- Iter084：风格漂移检测、drift score、severity、meta 写入与 Web badge。
- Iter085：偏离维度到 rewrite directives，接入 reviewer advisor 与 writer feedback。
- Iter086：red drift 自动定向重写与重写后复测闭环。
- 任意真模型 smoke、writer/reviewer 接线、Web UI、新 API、起点原文窗口 baseline。

## Notes

- 本轮立项显式使用 `iter-start` skill；收尾将使用 `iter-finish` skill 同步验收、审查、README SOP 与 `docs/AGENT_HANDOFF.md`。
- 当前工作树中未跟踪 `续写工作台.pptx` 是用户文件，保持不动。
- `iteration_083_086_style_fingerprint_roadmap.md` 是路线图交接文档，不替代本轮 8 段 iteration 记录。
- Iter084 接力：基于本轮 baseline artifact 做 draft 指标对比、drift score/severity 与 meta 写入，仍应保持样本不足 graceful degrade。
- Iter085 接力：把偏离维度映射为 reviewer advisor / writer feedback 可消费的 rewrite directives，先读本轮 `dimension_stats/tolerance/weights`，不要重新设计 baseline schema。
- Iter086 接力：仅在 drift severity 足够明确时做 red drift 定向重写与重写后复测；本轮没有任何自动重写入口。
