# Iteration 087 - 文风 Red Drift 定向重写与复测闭环

## Context

Iter083-086 已完成纯本地文风 baseline v2、章节 drift score/severity、确定性 rewrite directives 与 Web 告警，但 red drift 目前仍只能被看到，不会自动形成“定向修文→复审→复评分”闭环。Iter086 已补齐 hash/version、稳定聚合、CLI 写锁和 Web 防御纵深，本轮在这些可信前置上完成最多一次的 red-only 自动修文。

## Plan

- 为 `style_fingerprint.yaml` 增加默认开启的 red-only rewrite policy，非法配置 fail-closed 禁用并由 preflight 告警。
- 在 writer 正常 review-loop 和 terminal polish 后加入一次性 style gate，复用 write model，不新增 agent/task。
- 候选稿使用同一 baseline/config 快照计算 before/after，必须 lint 通过、panel Approve 且 score 严格下降才采用；否则回退原批准稿。
- 候选复审不覆盖正式 review artifact；仅在候选被采用时原子替换。
- meta 留存 style rewrite 计数、选择状态、before/after、改善值与 unresolved；chapter status/Web 透出告警但不改 approved 语义。
- 补齐配置、writer、review artifact、预算、status 和 Web 回归。

## Acceptance

- 有效 v2 baseline + red + Approve 稿恰触发一次 style write 和一次候选复审；warn/ok/skipped/关闭/非 Approve 零额外 LLM。
- 候选仅在非空、lint 无 error、panel Approve 且 score 严格下降时采用；其他情况回退原稿。
- before/after 基于同一 baseline hash；最终 `style_drift/baseline_hash/draft_sha256/review artifact` 与落盘正文一致。
- `style_rewrite_count` 与旧 `rewrite_count/rewrite_round` 隔离，最多 1，无无限循环。
- 候选未采用、改善 `<0.08` 或采用后仍 red 时 `style_drift_unresolved=true`，但不改 verdict/hard reject/needs-human/readiness/panel policy。
- style LLM 前后、候选 panel 前后调用现有预算检查；超限保持现有 partial/failure 恢复语义。
- Web 展示 before→after、是否采用与 unresolved，坏 meta 和动态文本不造成 JS/XSS 问题。
- canonical unittest、`scripts/verify.sh`、真实配置/mock preflight、`node --check`、`git diff --check` 全部通过；不跑真模型 smoke。

## Implementation Notes

- `style_fingerprint.yaml` 新增 `style_drift_rewrite` policy：默认 `enabled=true`、只触发 `red`、最多 1 次、最小改善 0.08。`parse_rewrite_policy()` 严格拒绝 bool/string/NaN/Infinity/越界数值，缺失或非法配置禁用自动修文并由 preflight 告警。
- writer 在旧 review-loop 与 terminal polish 之后运行一次性 style transaction：用同一 baseline/config 内存快照计算 before/after，以完整原稿 + 确定性 directives 调用现有 write model。候选必须 score 严格下降、lint 无 error、panel Approve 才采用。
- `review_text(..., persist=False)` 为候选复审返回完整 report 但不覆盖 canonical artifact；只在候选采用且正文/meta 落盘后替换正式 review。非持久复审日志不记录 LLM 回显、raw verdict 或 Pydantic input，仅留 error type/长度。
- 修文候选空、未改善、lint/review/本地分析异常均 fail-open 回退原批准稿；post-polish transaction 失败时回退的是真正经过 panel 的 pre-polish 稿及对应 report，不把未复审 polish 稿伪装成批准稿。预算异常仍在 style LLM/panel 前后四个阶段外抛，保持 partial/failure 语义。
- 触发后 meta 写 `style_rewrite_count/applied/status`、`style_drift_before/after/improvement/unresolved`；最终顶层 drift/hash 对应实际落盘稿。`chapter_status` 透出 count/unresolved，但 approved 不消费 unresolved。
- Web 文风 tab 显示候选 before→after、改善值、采用/回退与 unresolved；即使顶层 drift 缺失/畸形也保留 rewrite audit。手工 PUT 正文会清除与旧 draft hash 绑定的全部 style 字段。

## Acceptance Result

- 最终聚焦回归：`tests.test_style_rewrite_loop` + style/reviewer/writer/status/preflight/Web 受影响集 **200 tests OK**；Python `py_compile`、JS `node --check /dev/stdin`、`git diff --check` 通过。
- canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests` **1775 tests OK**（226.593s）。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0；内部同样 **1775 tests OK**（409.553s），随后 mock auto-pipeline/status/manifest/review report/cost 全过。LiteLLM 远程 cost map timeout fallback 与缺 `botocore` 为非阻断 warning。
- `.venv/bin/python3 main.py preflight` = warn、无 FATAL；`OPENAI_MODEL=mock ... preflight` = ok、无 WARN/FATAL。真模型 smoke 未跑（铁律⑥）。
- correctness 首审发现 2×P1（本地 style 异常误中断、post-polish 回退未复审稿）+ 测试缺口，全部修复并复核 PASS。
- security/boundary 首审发现 2×P2（字符串数值可启用付费路径、候选回显可进日志），追加复核扩展到所有 candidate-sensitive log，全部收口并最终 PASS。
- Web/integration 首审发现 P1 手工编辑保留 stale style artifact + P2 顶层 drift 早退吞 rewrite audit，全部修复并复核 PASS。三视角无残留 blocker。

## 文件变更汇总

| 子系统 | 改动 |
| --- | --- |
| `config/style_fingerprint.yaml` / `src/style_drift.py` / `src/preflight.py` | red-only policy、严格配置守门、同 baseline 文本分析快照与 preflight WARN。 |
| `src/writer.py` / `src/reviewer.py` | post-polish 一次性 style transaction、安全择优、四段预算检查、候选非持久复审与日志隐私收口。 |
| `src/chapter_status.py` / `src/web/{routes,static}.py` | unresolved/count 非阻断透出、Web before/after 展示、手工编辑 stale artifact 清理。 |
| `tests/` | 新增 style rewrite 状态机/预算/异常/回退矩阵，扩展 reviewer、preflight、status 与 Web 回归。 |
| `docs/iterations/README.md` / `README.md` / `AGENTS.md` / `docs/AGENT_HANDOFF.md` | iter087 索引、SOP 状态、审查/验收与接力信息。 |

## 不在本轮范围

- warn 自动改写、多轮 style rewrite、精确原文 anchor、readiness blocker。
- 短剧导出/Insights/第 2 集重生，小说 10-20 章真模型 capstone。
- 自动迁移用户本地 v1 baseline；升级后仍需用户显式重建。

## Notes

- 本轮显式使用 `iter-start`，收官显式使用 `iter-finish`。
- 不改 `.env`，不读写 `data/`、`outputs/`、`小说txt/` 或用户私有样本，不触碰未跟踪 `续写工作台.pptx`。
- 真模型 smoke 不跑；收官必须 correctness、security/boundary、Web/integration 三视角只读审查。
- correctness、security/boundary、Web/integration 三个独立只读 subagent 均已完成首审与修后复核，所有 finding 关闭，无残留 blocker。
- 现有本地 v1 baseline 仍需显式执行 `python3 main.py style-fingerprint build-baseline` 重建；本轮不自动迁移。
- 下轮候选回到短剧导出/Insights/第 2 集重生，或经用户单独授权后跑小说 10-20 章真模型 capstone。
- 提交只 commit、不 push：`Iteration 087: close style drift rewrite loop`。
