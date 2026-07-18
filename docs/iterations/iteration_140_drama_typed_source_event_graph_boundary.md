# Iteration 140 - 短剧 Typed Source Event Graph 与来源边界

## Context

iter139 已闭合阶段 G1-G7 的通用媒体调度、pricing 与 lifecycle metrics；A-J SOP 的下一项是阶段 H，将小说到短剧改编从自由文本摘要升级为可追溯的 typed event graph。现有 RenderPlan 已预留 `source_event_ids`，小说侧也有 entity/summary 基础，但尚无严格事件身份、source chapter/hash、spoiler boundary、因果未知语义或安全持久图。本轮先完成 H1 的纯本地事件图核心与来源边界，只使用 synthetic/调用方显式结构化输入，不读取私有原文、不调用 LLM/embedding、不把事件图变成创作真源。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_render_plan.py`, `src/entity_advance.py`, `src/chapter_summary.py`, `tests/test_drama_render_plan.py`, `tests/test_entity_advance.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_event_graph.py`, `tests/test_drama_event_graph.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_140_drama_typed_source_event_graph_boundary.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不读取真实章节/摘要/实体数据，不触发真实文本、embedding、图片、视频或 TTS，不动态执行 provider/skill 代码，不修改 A-G paid/media ledger，不 push

1. 定义 strict/frozen typed event 与 graph schema：稳定 event ID、source-derived/invented 明示、source chapter IDs/hash、spoiler boundary、参与者/场景/道具/线索、typed precondition/effect、chronology 与 causal parent；额外字段、重复/悬空 identity、伪 source、bool/非有限/超限均拒绝。
2. 实现 deterministic graph build/validate 与 content-addressed canonical store；只接受调用方显式结构化 facts，不从自由文本、章节号邻接或实体关系猜因果。来源事件必须有可验证 source identity，invented 事件不得冒充 source-derived。
3. 实现严格 merge/split lineage：合并保留全部来源与因果 unknown，拆分只能分配已有 typed facts 并记录 parent/derived lineage；重放幂等，跨图 splice、循环因果、越界 chronology/spoiler 与 source hash 冲突 fail closed。
4. 提供有界 selection/projection：给定允许章节/spoiler boundary 只返回完整可追溯闭包；任何选中事件、祖先或来源越界即整体拒绝，不返回部分图，也不自动改写 episode/RenderPlan。
5. 使用 synthetic 多章 fixture、tamper/limits/nofollow/replay/merge/split/boundary 与零 socket 测试闭合 H1；后续 H2 再接小说 entity/summary adapter 与 RenderPlan graph fingerprint，H3 再做可失效 context memory。

## Acceptance

### Review Context
- `correctness_behavior`: source-derived/invented 互斥语义、source identity、chronology/causal DAG、deterministic fingerprint、merge/split lineage、exact replay 与 selection 闭包必须稳定；unknown 因果不得被邻接或文本推断，不能改变现有 episode/RenderPlan canonical
- `security_boundary`: strict/bounded/content-addressed/nofollow store；章节/source hash/spoiler boundary、悬空/循环/跨图 splice、symlink/目录/坏 JSON/超限和 namespace 竞态 fail closed；不得读取私有原文或公开 source text/path/prompt/response
- `extra_risk_view`: multi-workspace + adaptation provenance 专项，复核 graph identity/来源闭包、merge/split 防洗白、legacy/缺失 graceful 与默认零网络

- **A140-01**：strict typed event/graph schema 明示 source-derived 与 invented；source chapter/hash/spoiler、参与者/资产、typed facts、chronology/causal identity 有界确定，额外/重复/悬空/循环/伪来源均拒绝。
- **A140-02**：build/store 内容寻址、canonical、nofollow 且 exact replay 幂等；不同 workspace/graph/source 不可 splice，坏源、symlink、目录、竞态和超限 fail closed。
- **A140-03**：merge/split 保存可验证 parent/derived lineage 与完整来源闭包，不猜 unknown causal relation，不允许 invented/source-derived 互相洗白。
- **A140-04**：selection 在允许章节与 spoiler boundary 内返回完整有界投影；任一 selected event、causal ancestor 或 source 越界时整体拒绝，不返回 partial graph，不修改 episode/RenderPlan。
- **A140-05**：synthetic 聚焦回归与 correctness/security/provenance 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 新增 `DramaEventFact / DramaSourceEvent / DramaEventGraph / DramaEventProjection` strict/frozen schema 与纯本地 builder。fact 只接受 bounded opaque atom；event 身份同时绑定 workspace scope 与独立 graph-family scope，graph 身份绑定完整有序 event membership records，避免 event、family 或 workspace splice。
- source-derived / invented / mixed 与 selected / merged / split / omitted 分开建模；merge 精确保留来源、typed facts、资产 identity、可证明 causal parent 与 completeness，split 必须至少两个 child 无重叠完整分区。`causality_complete=false` 保留 unknown，不从章节邻接、实体关系或文本推导因果。
- selection 只接受显式 event IDs，递归求 causal + lineage 的最小闭包，并严格按 graph order 投影；任一 omitted、source chapter 或 spoiler 越界整体拒绝。projection 携带完整 graph membership manifest，但不携带未选 event facts。
- graph store 使用 canonical envelope/bytes、8 MiB 上限、逐级 no-follow、临时文件 fsync + hard-link create-once 与 exact replay；save/load 均复核 workspace scope。没有读取原文、summary、私有路径，没有 LLM/embedding/network，也不修改 episode/RenderPlan。
- 三视角审查发现并修复：load 跨 workspace 复制、projection 非最小闭包/跨 graph 注入、workspace 与 family scope 混淆、event 跨 workspace 移植、omitted 直接反序列化、projection 重排多 fingerprint、membership record 非内容寻址、fact 顺序与 pre-bound 检查，以及文档对 opaque atom/哈希 provenance 的过度承诺。所有 helper-only 约束均下沉至 schema，并以 fully rehashed direct-model 回归闭合。
- clean-room 只采用 Toonflow 固定 commit 中“事件摘要/辅助记忆”的通用思想；schema、持久化、测试与边界均独立实现，未复制其代码、prompt 或自由文本事件结构。

## Acceptance Result

- 聚焦回归：`.venv/bin/python3 -m unittest tests.test_drama_event_graph tests.test_drama_render_plan tests.test_drama_assets tests.test_drama_store tests.test_entity_advance tests.test_chapter_summary tests.test_context_budget`，**97 tests OK**；H1 自身 16 tests，`py_compile`、agent harness 与 `git diff --check` 通过。
- 三个独立只读视角（correctness、security/boundary、multi-workspace+adaptation provenance）最终均为 **no remaining P0/P1/P2**。审查中修复了跨 workspace graph copy/load 与 event transplant、workspace/family scope 绕过、projection 非 exact/canonical closure、omitted 直接反序列化、membership record 自证、merge/split/事实排序与 pre-bound，以及文档 provenance/opaque atom 过度承诺；主线程逐项以 fully-rehashed 回归复核。未修风险：H1 source hash 仍是 caller-trusted assertion，没有权威 chapter-byte ledger、签名或 MAC；生产 adapter、RenderPlan binding 与 context memory 留给 H2/H3。
- implementation commit：`dfe64adfbadfb80f79e77bdffe89e6b0936c6f93`（`feat(iter140): add typed source event graph`）。
- 唯一 canonical：`bash scripts/verify.sh` exit 0，**2765 tests / 15 steps / 379 秒**，run `3c4b8062cef34e16bb26027d7fb158d7`，tree `7721632b283a720c5ef573dd262637bbfefd958b`，`tracked_scope_clean=true`，mock preflight **0 FATAL / 0 WARN**；总级别 `mock-functional / canonical-mock-offline`，mandatory local-drama 子步骤 `local-e2e` 通过，未升级为 provider-validated。
- 真文本局部协议校准：`gpt-5.5-medium` 单次 HTTP 200，5.056 秒、442 tokens，`typed_source_invented_separation / unknown_causality_not_inferred / exact_graph_closure_boundary / content_identity_not_authenticated_provenance` **4/4 true**。未保存或回显 key、响应正文或完整 prompt；本轮图片/视频/TTS 0。iter125-140 累计保守计 **20/60 requests、15 responses、13 protocol passes、约 ¥1.80 预留**，图片 **0/20**。
- **A140-01 PASS**：event/fact/graph strict schema 同时绑定 workspace/family，source/invented/mixed、typed facts、chronology/parent 与来源 identity 全部有界且内容寻址。
- **A140-02 PASS**：canonical no-follow create-once store、exact replay 与 save/load workspace 复核通过；坏 JSON、special file、symlink、hash/ID/scope splice fail closed。
- **A140-03 PASS**：merge/split 精确保留来源、事实、资产与 causal/lineage，unknown 不补猜，invented/source-derived 无洗白旁路。
- **A140-04 PASS**：projection 是 graph-order 的 exact minimum causal+lineage closure；omitted、source/spoiler 越界、extra/cross-graph/cross-workspace 全量拒绝。
- **A140-05 PASS**：聚焦、三视角、唯一 canonical 与局部真文本校准均完成；结论严格限定为 H1 synthetic/mock-functional contract。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: H1 的 workspace/family identity、来源/改编语义、exact closure、持久化及“内容身份不等于认证 provenance”会约束 H2/H3、RenderPlan 与后续 Web 公共投影，属于长期产品协议而非单轮实现细节。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 workspace/family 双 scope 的 strict event/fact/graph/lineage/projection schema。 |
| `src/drama_event_graph.py` | 新增 deterministic build/merge/split/store/selection 与 no-follow content-addressed store。 |
| `tests/test_drama_event_graph.py` | 16 个 synthetic 测试覆盖来源、unknown causal、fully-rehashed 绕过、边界、持久化与零网络。 |
| `docs/product/short_drama_module.md` | 登记 H1 权威协议、安全资格与 H2/H3 缺口。 |
| `docs/iterations/{README.md,iteration_140_*.md}` | 登记本轮索引、计划、实施、审查与验收。 |

## 不在本轮范围

- 小说 entity/summary 的生产 adapter、LLM 事件提取、embedding/向量检索、context memory cache。
- episode/RenderPlan graph fingerprint 写入、Web/UI、事件编辑 mutation、真实 provider、媒体/TTS 与主观改编质量。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
- clean-room 仅采用 Toonflow 固定 commit 中“事件摘要/辅助记忆”的通用思想，不复制其代码、prompt、测试或自由文本事件结构；本仓事件图使用独立 strict typed schema。
