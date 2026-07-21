# Iteration 146 - 短剧可失效 Context Memory Cache

## Context

iter145 已完成 H2 production entity/rolling-summary authority adapter 与 RenderPlan source graph binding。按 A-J 阶段 H3，本轮在不增加创作真源、不复制原文章节/摘要文本、不依赖 embedding 下载的前提下，为短剧 planning/render 建立 recent + summary + keyword 的结构化辅助记忆 cache；cache 删除、缺失或失效不得影响 canonical episode、RenderPlan 或 source graph 的可读性。

## Plan

### Implementation Context
- `must_read`: `src/drama_event_graph.py`, `src/drama_source_adapter.py`, `src/drama_render_plan.py`, `src/drama_render_store.py`, `src/drama_schemas.py`, `tests/test_drama_event_graph.py`, `tests/test_drama_render_plan.py`, `docs/product/short_drama_module.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`
- `expected_changes`: `src/drama_context_memory.py`, `src/drama_schemas.py`, `tests/test_drama_context_memory.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_146_drama_context_memory_cache_invalidation.md`, `docs/iterations/README.md`
- `do_not_touch`: `.env*`、`data/`、`logs/`、`workspaces/`、`小说txt/`、原文章节与私有样本、真实 provider/TTS；cache 不得保存摘要原文、完整 prompt、凭据、签名 URL 或 provider response

1. 定义 strict、content-addressed context cache：绑定 workspace/project、season、episode、graph family、source snapshot、完整 graph identity、RenderPlan fingerprint 与策略文件 bytes fingerprint；每条记录绑定 exact event/event fingerprint/source fingerprint。
2. recent、summary 与 keyword retrieval 只冻结 event IDs/typed identity；keyword 使用规范化查询 hash，不持久化明文关键词。无 embedding 模型时保持零网络 deterministic fallback，不下载模型、不调用 LLM。
3. 提供纯 build/query/inspect 与 named-workspace no-follow store。current graph/snapshot/RenderPlan/policy 任一漂移都返回 stale/blocked；missing cache 返回 `missing`，不得污染或改写 canonical source/episode/RenderPlan。
4. 覆盖 exact replay、跨 season/episode/workspace、source/policy/render drift、删除/损坏/symlink/超限、keyword hash、zero-network 与 legacy H1/H2 不回归。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 recent/summary/keyword 的确定性和 bounded ordering、每条记录 exact event/source identity、上游/策略漂移失效、cache missing/deletion 对 canonical 零影响及 episode 隔离
- `security_boundary`: 核对不持久化原文/摘要/明文关键词/prompt/路径/凭据，nofollow 与 workspace scope、坏/超限 JSON、symlink/特殊文件、跨 scope/tamper fail closed、零网络
- `extra_risk_view`: H3 cache provenance：核对 cache 不成为新真源，graph/RenderPlan/policy 身份闭包可本地重算，hash 不被宣称为签名或 MAC

- A146-01：strict cache 从 synthetic H2 graph/projection 确定构建，recent/summary/keyword 查询稳定，每条记录绑定 project/season/episode/event/source identity，exact replay bytes 稳定。
- A146-02：source snapshot、graph、RenderPlan 或策略 bytes 漂移使 cache stale/blocked；cache missing/deletion/invalid 不改写 canonical episode、RenderPlan 或 graph，重建只依赖当前 authority。
- A146-03：默认无 embedding 的 fallback 零网络；持久化投影不含摘要原文、明文关键词、完整 prompt、路径或凭据；跨 workspace/season/episode、symlink、特殊文件、超限与 tamper 整体拒绝。
- A146-04：聚焦单测、语法检查、harness 与 diff check 通过；correctness、security/boundary、cache provenance 三个独立只读审查无未处理有效 finding。
- A146-05：implementation commit 后最终仅一次 `bash scripts/verify.sh` 通过并记录 `mock-functional`；本轮不声称 provider validation。

## Implementation Notes

- 新增 text-free H3 cache：每条 record 只含 event ID/fingerprint、source fingerprint、chronology、recent/summary role 与 hashed keyword，不含章节/摘要/角色/关系文本、明文 keyword、prompt、路径或 provider 数据。combined query 固定按 keyword → recent → summary 去重，默认无 embedding/LLM/socket 分支。
- cache 绑定 workspace、season、episode、graph family/scope、source snapshot、full graph membership、H2 selected/selection binding、RenderPlan 与 policy exact bytes。production inspect 从 current H2 authority 重建并逐 record 对账；cache missing/delete 不读取或改写 canonical authority。
- policy fingerprint 绑定 `config/agents.yaml`、短剧创作规范、H3 builder 与 RenderPlan builder exact bytes；逐级 dir-fd no-follow、regular/size 与 double-read 防止路径/读取竞态。keyword 先做 raw cap，再 NFKC/trim/casefold/hash；hash 不是加密或匿名化。
- store missing create 使用 fsync temp + hard-link no-overwrite；不同 cache 只允许显式 replacement，并在 cooperative workspace lock 内做 target-token guard 与 precommit current binding 重读。exact replay 同样二次重读 current binding；不宣称 hostile-writer OS CAS。
- 三视角初审发现并闭合：exact replay 漏二次 binding、record source/episode fully-rehashed 对账、raw/nested container subclass 与超长 keyword 前置限流、missing create 覆盖竞态风险、store/special-file/precommit/cross-scope 覆盖不足。最终 correctness/behavior、security/boundary、cache provenance 均为 no remaining P0-P3。
- 聚焦回归覆盖 157 tests；H3 专项 8 tests 覆盖 deterministic/privacy/zero-network、source/policy/render/episode drift、fully-rehashed tamper、delete、replay/precommit、explicit replace、cross workspace、oversize/deep/duplicate/nonfinite、symlink/目录/FIFO、container subclass、long keyword 与 create race。

## Acceptance Result

- A146-01：通过。H3 strict cache 从已验证 H2 graph/projection 确定构建，recent/summary/keyword 查询、exact replay bytes 与逐 record project/season/episode/event/source identity 均由专项测试覆盖。
- A146-02：通过。source snapshot、graph membership、selection binding、RenderPlan、episode 与 policy drift 均返回 stale/blocked；missing/delete/invalid cache 不修改 canonical authority，production rebuild 只读取 current H2/RenderPlan/policy。
- A146-03：通过。默认实现零 embedding/LLM/socket；持久化只含身份、role 与规范化 keyword hash，不含原文、摘要原文、明文 keyword、prompt、路径或 provider 数据。跨 scope、symlink/目录/FIFO、超限/deep/duplicate/nonfinite 与 fully-rehashed tamper 均 fail-closed。
- A146-04：通过。H3 专项 8 tests、相关聚焦回归 157 tests、语法/harness/diff check 均通过；correctness/behavior、security/boundary、cache provenance 三个独立只读审查最终均无 P0-P3。
- A146-05：通过。accepted implementation `b29048fef51968b914d18a504e6863396de25c14` 上仅运行一次 canonical `bash scripts/verify.sh`：2832 tests、15 steps、448 秒、run `33d5cbc717f649f6b0f9d7b39a21a4e2`、tree `836f021f93a234ef57ae9fa50cc5c22163bf67e0`、`tracked_scope_clean=true`、exit 0，结论为 `mock-functional` / `canonical-mock-offline`，mandatory `local_drama_e2e` 通过；未运行真实 provider。

残余风险：keyword SHA-256 对低熵查询仍可被离线猜测，不等于匿名化；explicit replacement 的 target-token guard 只覆盖遵守 workspace flock 的合作写者，不宣称抵抗 hostile/non-cooperative 本地进程；I 的统一生产工作台/归档与 J 的 provider capstone 尚未实现。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: disposable cache 不成为真源、current H2/RenderPlan/policy exact binding、hashed keyword 非匿名边界、no-overwrite create 与 cooperative replacement 限制会持续约束 I 的工作台/归档和 J 的 provider capstone，属于长期产品协议。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_context_memory.py` | 新增 H3 pure build/query/inspect、policy/keyword fingerprint、production current rebuild、strict no-follow store 与 replay/precommit freshness。 |
| `src/drama_schemas.py` | 新增 strict content-addressed `DramaContextMemoryRecord/Cache`、full graph/selection/scope/record identity 自校验与 exact nested types。 |
| `tests/test_drama_context_memory.py` | 覆盖 H3 pure/production、隐私/零网络、drift/tamper、delete/replay/replace/race、跨 scope、坏 JSON/特殊文件与 bounded container。 |
| `docs/product/short_drama_module.md` | 晋升 H3 disposable cache、current binding、keyword/privacy、store 与 threat-boundary 协议，版本升至 v15。 |
| `docs/iterations/README.md` | 追加 iter146 canonical 索引。 |
| `docs/iterations/iteration_146_drama_context_memory_cache_invalidation.md` | 记录计划、实现、审查、验收与文件范围。 |

## 不在本轮范围

阶段 I production workbench/archive、物理 GC、真实 provider/billing/Web submit-poll-cancel、TTS 与平台发布。

## Notes

计划提交信息：`docs(iter146): 迭代计划 146 立项（短剧可失效 Context Memory Cache）`。
