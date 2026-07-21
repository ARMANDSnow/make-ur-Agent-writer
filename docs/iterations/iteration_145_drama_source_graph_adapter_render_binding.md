# Iteration 145 - 短剧生产来源图适配与 RenderPlan 绑定

## Context

iter140 已完成 H1 workspace/family-bound typed source event graph，但仍只接受调用方结构化 assertion，不能证明 source hash 对应当前小说 entity/summary 权威快照，RenderPlan 也尚未绑定 graph selection。按 A-J 阶段 H2，本轮建立纯本地、零网络、默认不读取原文章节的生产适配与 exact graph fingerprint 绑定；不让 source graph 改写创作层 canonical episode。

## Plan

### Implementation Context
- `must_read`: `src/drama_event_graph.py`, `src/drama_render_plan.py`, `src/chapter_summary.py`, `src/entity_advance.py`, `src/paths.py`, `tests/test_drama_event_graph.py`, `tests/test_drama_render_plan.py`, `docs/product/short_drama_module.md`
- `expected_changes`: `src/drama_source_adapter.py`, `src/drama_render_plan.py`, `tests/test_drama_source_adapter.py`, `tests/test_drama_render_plan.py`, `docs/iterations/iteration_145_drama_source_graph_adapter_render_binding.md`, `docs/iterations/README.md`, `docs/product/short_drama_module.md`
- `do_not_touch`: `.env*`、`data/`、`outputs/`、`logs/`、`workspaces/`、`小说txt/`、真实 provider 与 TTS；不得保存章节原文、完整 prompt、provider response 或凭据

1. 建立 strict source snapshot adapter，只从调用方显式传入的 entity graph 与 rolling-summary canonical bytes/安全投影构造 H1 typed events；每个事件绑定 exact source snapshot fingerprint，缺失、越界、坏 schema 或身份漂移时整体 fail closed。
2. 无法从现有结构确定因果时保持 unknown，不调用 LLM、不从自然语言相似度猜测；适配产物只保留有界 typed atoms、source ids/hash 与必要血统，不复制章节摘要原文。
3. 为 RenderPlan 增加可选 exact graph selection binding：冻结 source event IDs、graph fingerprint、selection fingerprint 与 spoiler boundary；重建和 inspect 时重验 current graph/selection，变化只使渲染派生物 stale，不改 canonical episode SHA。
4. 覆盖确定性 replay、summary/entity source drift、跨 workspace/family、spoiler 越界、tamper、无源 graceful degrade 与零 socket 测试。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 adapter 的确定性、source snapshot 漂移失效、unknown causal 语义、RenderPlan exact graph selection freshness、旧 workspace 兼容与 canonical episode 不被改写
- `security_boundary`: 核对 no raw chapter/summary/prompt 持久化、bounded canonical bytes、workspace/family/spoiler 约束、路径与 symlink 边界、tamper/cross-scope fail closed、零网络
- `extra_risk_view`: H2 adaptation provenance：核对 entity/summary 权威快照认证范围、source identity 与 graph/selection/RenderPlan 指纹闭包，避免把 content hash 宣称为签名

- A145-01：source adapter 从 synthetic entity/summary 权威快照确定性构造 strict H1 graph；exact replay 稳定，输入漂移产生新 snapshot/graph identity。
- A145-02：adapter 不保存原始摘要文本，坏/超限/跨 scope 整体拒绝；完整 source graph 不按 episode boundary 裁剪，selection 的剧透越界整体拒绝；无可用 source 返回结构化 `insufficient_source`，零网络且不报错。
- A145-03：RenderPlan 可选冻结 exact source event IDs、graph fingerprint、selection fingerprint 与 spoiler boundary；current binding 漂移进入 stale/blocked，旧无 binding workspace 保持兼容，canonical episode SHA 不变。
- A145-04：聚焦单测、语法检查、harness 与 diff check 通过；correctness、security/boundary、adaptation provenance 三个只读审查无未处理有效 finding。
- A145-05：最终仅一次 `bash scripts/verify.sh` 通过，验收级别记录为 `mock-functional`；本轮不声称 provider validation。

## Implementation Notes

- 新增纯 bytes adapter 与 named-workspace production loader。source snapshot fingerprint 绑定 exact entity/rolling-summary bytes，完整 graph 与 spoiler selection policy 分离；summary 缺失 graceful degrade，现存坏源 fail closed。
- production entity timeline 的 `anchor_chapter=续写第NN章` 由 `entity_advance.parse_chapter_anchor` 单一 parser 解析；未知 anchor 不猜，身份冲突拒绝。timeline 先单次 validate/index，避免 chapters × relationships × timeline 的 CPU 放大。
- 原计划只列 `drama_render_plan.py`，实施中确认仅在纯 builder 冻结 projection 仍会被 caller hash 自证，因此合理扩展到 `drama_schemas.py` 与 `drama_render_store.py`：store 只接 family/selected IDs/boundary，内部重建 current production graph，inspect/precommit 均重读来源。
- RenderPlan 新 binding 只进入 plan fingerprint；旧 unbound payload/fingerprint、canonical episode SHA 与 creative fingerprint 保持兼容。没有逐镜 typed mapping 时不填 shot-level event IDs。
- 三视角审查先后发现并闭合：family ID/scope splice、unknown explicit chapter ID 被低优先级 anchor 覆盖、full graph historical proof 缺失、selected ID 非 graph member、不可本地重算的 projection claim。最终 RenderPlan 冻结 bounded full-graph membership records，并从 graph root、selected/allowed IDs 与 boundary 重算 selection-binding fingerprint。
- 聚焦回归最终覆盖 149 tests；correctness/behavior、security/boundary、adaptation provenance 三个独立只读视角均为 no remaining P0-P3。

## Acceptance Result

- A145-01 ✅：synthetic entity/rolling-summary exact bytes 可确定性构建 H1 graph；exact replay 稳定，任何 authority bytes 漂移都会改变 snapshot 与 graph identity，但 family identity 保持稳定。
- A145-02 ✅：adapter 仅冻结有界 ID/hash/fact atoms，不持久化摘要原文；坏 schema、非有限数、身份冲突、跨 scope、symlink/特殊文件/超限整体 fail closed。无 rolling summary 返回 `insufficient_source`，entity 缺失则以 degraded source 明示，全部路径零网络。
- A145-03 ✅：RenderPlan 可选冻结 workspace/family、source snapshot、full-graph ordered membership、selected/allowed IDs、spoiler boundary 与可本地重算的 selection binding；production create/inspect/precommit 均从当前 authority 重建。合法 source drift 为 stale，坏/缺 authority 为 blocked，legacy unbound plan 兼容，canonical episode SHA 与 creative fingerprint 不变。
- A145-04 ✅：聚焦回归 149 tests 通过；harness、语法检查与 `git diff --check` 通过。correctness/behavior、security/boundary、adaptation provenance 三个独立只读视角发现的 scope splice、未知 chapter identity 覆盖、graph membership/selection 自证等问题均已修复，最终均为 no remaining P0-P3。
- A145-05 ✅：implementation commit `626873e0833de1cb713ff50d3b3c3d31df546849` 上仅运行一次 `bash scripts/verify.sh`：2824 tests、15 steps、442 秒、run `4848df3127bd4f019c5ce61c01f0f02d`，tree `76a9c18b14e505fa9b077c51a03bb52bcf23a6fb`，`tracked_scope_clean=true`，exit 0。总验收为 `mock-functional` / `canonical-mock-offline`，mandatory `local_drama_e2e` 子步骤通过；本轮未调用真实 provider，`provider-validated` 不成立。

结论：iter145 **accepted**。残余风险：普通 SHA/content addressing 不是签名或 MAC，不能抵抗具有本机写权限者对 authority 与派生证据的整套重写；H3 context memory、I 生产工作台/归档和 J 真 provider capstone 仍未实现。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: H2 的 authority-bytes、完整 source graph 与 episode policy 分离、RenderPlan exact graph/selection identity closure、stale/blocked 分类及非签名边界会持续约束 H3/I/J 与后续 Web/归档，属于长期产品协议。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_source_adapter.py` | 新增 bounded pure adapter、named-workspace exact double-read production loader、timeline 单次 strict index、graceful degrade 与隐私安全投影。 |
| `src/drama_render_plan.py` | 接入 workspace/family/snapshot/full-graph/selection binding 与纯 freshness helper，保持 creative episode 不变。 |
| `src/drama_render_store.py` | production create/inspect/precommit 从当前 authority 重建 graph/selection，合法 drift stale、坏/缺 source blocked。 |
| `src/drama_schemas.py` | 增加 RenderPlan H2 strict fields、graph membership proof、family/graph/selection fingerprint 自校验与 legacy fallback。 |
| `src/entity_advance.py` | 公开 canonical `parse_chapter_anchor` 并保留旧私有别名。 |
| `tests/test_drama_source_adapter.py` | 覆盖 exact bytes、隐私、limits、nofollow、anchor/identity、nonfinite、graceful degrade 与零网络。 |
| `tests/test_drama_render_plan.py` | 覆盖 H2 builder/store E2E、source drift/block、precommit race、legacy/cross-scope 与 fully-rehashed tamper。 |
| `docs/product/short_drama_module.md` | 晋升 H2 authority、RenderPlan binding、freshness 与 threat-boundary 产品协议，版本升至 v14。 |
| `docs/iterations/README.md` | 追加 iter145 canonical 索引。 |
| `docs/iterations/iteration_145_drama_source_graph_adapter_render_binding.md` | 记录计划、实现、审查、验收与文件范围。 |

## 不在本轮范围

H3 context memory、I 生产工作台/归档、物理 GC、真实 image/video/text provider 校准、真实 billing、Web provider submit/poll/cancel、TTS 与平台发布。

## Notes

计划提交信息：`docs(iter145): 迭代计划 145 立项（短剧生产来源图适配与 RenderPlan 绑定）`。
