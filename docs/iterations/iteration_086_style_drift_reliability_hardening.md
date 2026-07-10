# Iteration 086 - 文风漂移可靠性修复与 Web 防御纵深

## Context

Iter083-085 已交付纯本地文风 baseline、章节漂移检测和确定性改写建议，但收官复审与主线程复现确认了若干会破坏后续 red 自动重写前提的可靠性问题：超大有限权重可溢出为 `Infinity/NaN` 并被误钳成绿色；短单样本 baseline 会显示成功却完全不可比较；top-5、坏历史 meta、CLI 并发和 Web 脏数据边界仍有缺口。

本轮将路线图原定的 red 自动重写顺延，只做这些已确认 bug 的修复与防御纵深。目标是先把 baseline、drift、CLI 和章节详情的信号做成可信、可解释、不会因坏数据崩溃的前置底座。

## Plan

- 将指纹算法升级为 `local-stat-v2`：单换行按物理段落统计，low reliability baseline 明确降级，整数配置拒绝非有限值。
- 新 baseline artifact 移除样本文件名和逐样本无盐 SHA256；读取时重算 hash 并拒绝坏 hash 或旧算法版本。
- 用稳定缩放的加权平均修复极大权重溢出；advisor 瞬时分析全维度后再过滤，持久化 top-5 契约不变。
- 清洗历史 drift report 的 NaN/Infinity 与畸形数组；为手工 `style-drift --chapter` 增加完整读改写窗口的 workspace 写锁。
- 补齐章节详情 `#style` 深链接、全 tab 失败态、null/畸形数据容错、状态区分、Advisor 来源与 tab ARIA 状态。
- 运行聚焦与全量 mock 验收，按项目铁律完成 correctness、security/boundary 双只读审查和文档同步。

## Acceptance

- 多个 `1e308` 有限权重不会产生 NaN 或误判绿色；严重合成漂移仍为 red，非有限聚合 fail-closed。
- 500-3999 字单样本 baseline 返回 `insufficient_source/low_reliability`；4000 字单样本和两个短样本边界按 medium 可靠度可用。
- v2 baseline hash 在读取时核验；缺失、分叉或篡改均 skipped，v1 明确提示重建；新 artifact 不含文件名或逐样本原文 digest。
- 单换行、双换行、空白行和 CRLF 使用一致的段落口径；Infinity 整数配置不击穿 build/inspect CLI。
- 前五个不可映射维度不会吞掉第六个有效 AI 腔 directive，meta/Web 仍最多持久化五个 top dimensions。
- 坏历史 meta 可被 `allow_nan=False` 严格序列化；手工 drift 写锁冲突退出且不覆盖 meta。
- `#style` 刷新保持激活；draft API 失败时各 tab 不永久 loading；null/`[null]` 不伪装零值或中断 JS；tab ARIA 与 Advisor 来源可见。
- canonical unittest、`scripts/verify.sh`、真实配置/mock preflight、`node --check` 与 `git diff --check` 全部通过；不跑真模型 smoke。

## Implementation Notes

- `style_fingerprint` 升级为 `local-stat-v2`：段落统一按非空物理行统计；source 门槛通过但 reliability=low 时写 `insufficient_source/low_reliability` 空指标 artifact。旧 v1 baseline 不迁移，运行时返回 `incompatible_version`，用户需显式重建。
- baseline hash 改为 strict canonical JSON（`allow_nan=False`），`baseline_hash/hash` 两个别名必须同时存在、相等且匹配重算 digest；任一缺失、分叉、篡改或非有限值均 `invalid_hash`。新 artifact 取消 `source_labels/source_hashes`，不再持久化样本文件名或逐样本原文 digest。
- drift 聚合先按最大有限 weight 缩放，再用 `math.fsum` 求加权平均，避免多个 `1e308` 溢出；聚合任何非有限结果返回 `invalid_weight_aggregation`。invalid/incompatible baseline 的不可信 hash 不进入 basis/meta，旧顶层 `baseline_hash` 会被清理。
- `rewrite_directives_for_text()` 瞬时请求全部 drift 维度，再由 directive mapper 过滤并截五条；章节 meta 与 Web 的默认 `top_dimensions` 仍保持 top-5。
- `style_drift_report()` 将坏历史 score 降级为 `skipped/invalid_style_drift_score`，过滤非对象维度并递归清洗 NaN/Infinity；`style-drift --chapter` 仅在 CLI 外层持有 workspace flock，覆盖完整 draft read → analysis → meta merge，冲突 exit 4。
- Web 章节详情新增 `#style` 白名单、全 tab 错误卡、编辑禁用态、strict 数值解析、坏数组过滤、未检测/已跳过 badge 与 Advisor 来源。共享 tab 初始化 `tablist/tab/tabpanel` 语义，维护 selected/controls/labelledby/hidden，并支持跳过 disabled 的 Home/End/四方向键 roving focus。
- 未接 red 自动重写、复测或新 LLM 调用；不改变 verdict、review、rewrite_count、readiness 或 hard-reject 语义。

## Acceptance Result

- 聚焦回归：`tests.test_style_fingerprint tests.test_style_drift tests.test_style_rewrite_directives tests.test_static_subscore_compat tests.test_web_routes_get` **130 tests OK**。
- canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests` **1757 tests OK**（396.583s；收官最终轮）。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`：exit 0；内部 **1757 tests OK**（415.373s），随后 auto-pipeline/status/manifest/report/cost 全过。
- `.venv/bin/python3 main.py preflight`：`warn`、无 FATAL；`OPENAI_MODEL=mock ... preflight`：`ok`、无 WARN/FATAL。
- JS `node --check`、`git diff --check` 均通过；真模型 smoke 未跑（铁律⑥）。
- Playwright 临时 mock server smoke：`#style` 首开与刷新保持选中；null/false/`top_dimensions:[null]` 降级正确；Advisor `_advisor` 以文本转义；ArrowRight 从文风切到 Advisor 并同步 hash/selected/focus；成功路径 console 0 error。故障注入 HTTP 500 时六个目标面板均显示错误卡且无“载入中”，编辑区与两个保存按钮禁用；console 仅有预期 resource 500，无未捕获 JS 错误。
- correctness 审查发现 4 项并已修：非有限 `schema_version` 穿透严格 JSON、invalid/incompatible hash 仍回写 meta、hash 单 alias 未 fail-closed、`_safe_float` 超大整数 OverflowError。复核 GO。
- security/privacy 审查发现 2 项并已修：hash 单 alias 接受、baseline canonical JSON 允许 NaN/Infinity。复核 PASS；确认 artifact 不含样本名/原文 digest、无 secret/XSS 新路径。
- Web/integration 审查发现 2 项并已修：roving tab 无键盘导航、badge 对 `false/""/[]` 伪装 0.00。复核无 blocker。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/style_fingerprint.py` / `config/style_fingerprint.yaml` | v2 段落口径、可靠度门槛、严格 hash、配置数值守门与隐私最小化。 |
| `src/style_drift.py` / `main.py` | 稳定权重聚合、全维度 advisor、严格报告、invalid hash 清理与 CLI 写锁。 |
| `src/web/static.py` | 深链接、失败态、脏数据降级、状态区分、Advisor 来源与完整 tab ARIA/键盘交互。 |
| `tests/test_style_fingerprint.py` / `tests/test_style_drift.py` / `tests/test_style_rewrite_directives.py` | baseline、数值、hash、report、锁与 top-5 回归。 |
| `tests/test_static_subscore_compat.py` / `tests/test_web_routes_get.py` | Web 深链、错误态、严格数值、脏数组、Advisor 与 ARIA 契约。 |
| `docs/iterations/README.md` / `README.md` / `AGENTS.md` / `docs/AGENT_HANDOFF.md` | iter086 立项、验收、SOP 与交接同步。 |

## 不在本轮范围

- red drift 自动定向重写、重写后复评分、`style_rewrite_count` 和 unresolved 状态。
- 新 LLM agent、真模型 smoke、readiness/hard reject/panel policy 接线。
- 自动迁移用户本地 gitignored v1 baseline；用户需显式重建。

## Notes

- 本轮立项显式使用 `iter-start`；收官显式使用 `iter-finish`。
- 不改 `.env`，不读写 `data/`、`outputs/`、`小说txt/` 或用户私有样本，不触碰未跟踪 `续写工作台.pptx`。
- 仓库外 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在，以用户确认计划和仓库内路线图为准。
- 提交只 commit、不 push。
- `local-stat-v2` 改变段落指标口径并收紧 artifact contract，现有本地 v1 baseline 会 fail-closed；升级后应运行 `python3 main.py style-fingerprint build-baseline` 重建。
- correctness、security/privacy、Web/integration 三个独立只读 subagent 均完成首审与修后复核，所有 finding 已关闭，无未修 blocker。
