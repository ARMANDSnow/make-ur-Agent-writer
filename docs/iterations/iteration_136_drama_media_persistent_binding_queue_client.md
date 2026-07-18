# Iteration 136 - 短剧媒体持久 Binding 与 Queue Client

## Context

iter133-135 已完成 G1 task DAG、G2 worker ownership/capacity 与 G3 static registry/frozen binding，但 binding 仍只存在于调用进程内；worker crash 或服务重启后，queue 无法从持久状态证明某个 task 应继续使用哪份 capability snapshot。阶段 G 的 G4 先把 binding 与 task/lease 原子持久化，并提供 Web/CLI 可共用的纯本地 queue client；provider submit/poll/download/validate execution loop 继续后移，避免在持久恢复合同稳定前接入付费动作。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_backends/base.py`, `src/drama_media_backends/registry.py`, `src/workspace_lock.py`, `src/web/jobs.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_queue_client.py`, `tests/test_drama_media_tasks.py`, `tests/test_drama_media_worker.py`, `tests/test_drama_media_queue_client.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_136_drama_media_persistent_binding_queue_client.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发 provider/图片/视频/TTS，不新增 adapter callable 或 execution loop，不读取/迁移 C-F paid ledger，不接 Web mutation，不做 pricing/Insights，不 push

1. 将 G2 ledger 安全扩展为包含 task→frozen backend binding 的 strict 新版本；task、lease、receipt、dedupe、input/provider/account/endpoint identity 与已有 paid evidence 语义不变。G1/G2 legacy ledger 可确定读取；缺 binding 的旧 task 明示 `legacy_unbound`，不能从 current registry 补猜已提交任务。
2. 实现 task+binding 单次原子 enqueue：先用 G3 registry 解析 exact task identity，再在同一 workspace lock/ledger commit 中写 task 与完整 binding；active dedupe exact replay 返回原 task/binding，registry drift、部分同 ID、stale expected ledger、重复/foreign binding 与 crash window fail closed。
3. 绑定生命周期只允许 pre-submission 首次建立；claim 与后续 worker transition 必须要求 exact persisted binding。`submitting/submitted/polling/submission_unknown/downloading/validating` 永不从 current registry 重解析；terminal/cancel 保留 binding 供审计和恢复，不把 generic binding 当 paid authorization。
4. 新增纯本地 queue client：enqueue、get、bounded wait、cancel request 与 safe projection 共用 task ledger；wait 使用调用方 monotonic deadline/受控 poll interval，只读且零 busy loop，服务重启后以 durable task/binding 为准。cancel 复用 G1 cascade/guard，不伪造 provider cancel confirmation。
5. 用 fork/restart、v2→v3、enqueue crash/replay、registry drift、unknown/terminal、timeout/cancel 与 socket 零网络测试证明恢复；本轮无 provider adapter/execution loop、无真实媒体、无 pricing。

## Acceptance

### Review Context
- `correctness_behavior`: v2→v3 identity-preserving migration、task+binding atomic enqueue/exact replay、active dedupe、claim/transition binding gate、restart wait/cancel 与 terminal audit retention必须确定；不得改变 G1/G2 lease/receipt 或 C/D/E paid artifact/authorization/fingerprint 语义
- `security_boundary`: strict ledger/binding schema、task-binding cross identity、expected ledger/task revision、nofollow/size/depth/symlink/lock/CAS、monotonic wait bounds、cancel scope、安全 projection和 legacy submitted unbound reconciliation 必须 fail closed；零 dynamic code/credential/provider/network
- `extra_risk_view`: runner/media/paid 专项，复核原子 enqueue crash window、worker consume persisted binding、unknown 零重提、cancel 不冒充 provider confirmation、wait 无无界轮询与 generic/paid 单向边界

- **A136-01**：strict binding ledger migration 保持 G1-G3 task/lease/receipt/identity；旧 unbound submitted/unknown 明示 reconciliation，不能从 current registry 合成 binding。
- **A136-02**：task+binding 在一个 guarded commit 原子 enqueue；exact replay/active dedupe 返回原 snapshot，registry drift、stale CAS、foreign/duplicate binding 与中断不形成半绑定 task。
- **A136-03**：claim 与 execution transition 只消费 persisted exact binding；submitted 以后不重解析，terminal/cancel 保留审计 binding，unknown 永不自动 resubmit，generic binding 不替代 paid authorization/receipt。
- **A136-04**：queue client 的 enqueue/get/bounded wait/cancel/restart 行为持久且安全投影脱敏；timeout/cancel 无 busy loop、越权 episode/task 或 provider/network/TTS 调用。
- **A136-05**：聚焦回归与 correctness/security/runner-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 新增 strict `DramaMediaTaskLedgerV3`，在 G2 task/lease/release receipt/transition receipt 之外保存按 task ID 排序且唯一的完整 G3 backend binding。schema 逐项重验 task ID、input、media、backend 与 provider/model fingerprint；v1/v2 只做 identity-preserving 逻辑迁移，缺 binding 的 provider task 投影为 `legacy_unbound`，本地 compose/export 为 `not_applicable`。
- 新增 `enqueue_bound_media_task`，在单一 workspace lock 与 ledger CAS 内完成 proposed task、G3 resolution、task+binding 单次原子 commit。exact replay/active dedupe 只返回原 binding；旧 unbound task、provider/model ID 漂移和 registry/task identity 不一致均 fail closed，不提供“事后补绑”。
- provider task 的 worker claim/heartbeat/release/takeover 与 leased execution transition 要求 persisted binding；compose/export 保持原 G2 本地 lease 语义。所有 ledger writer 原样携带已有 binding，cancel/terminal 也保留审计快照。generic binding 不含 provider task/response/authorization，也没有触碰 C/D/E paid ledger。
- 新增纯本地 `drama_media_queue_client.py`：安全 enqueue/get、最长 300 秒 monotonic bounded wait 和 current-CAS cancel；公开投影新增 `frozen`、`legacy_unbound`、`not_applicable` 三态，不暴露 backend/provider/model/account/endpoint 或 binding fingerprints。
- 首轮聚焦测试共 63 项；审查修复后新增 provider unbound/dedupe poison、依赖列表锁前边界、deadline 后完成与 compose 本地 lease 回归。image/video/audio fixture 改为原子 bound enqueue；compose/export 只走 G1 unbound 本地编排，投影为 `not_applicable`，并保持 G2 lease/receipt 语义。
- 实施中发现 frozen capability 的 Python 表示使用 tuple，而 strict 反序列化只接受 JSON list；ledger 构造改用 `model_dump(mode="json")`，使内存构造、canonical bytes 与重启读取保持一致。

## Acceptance Result

- 聚焦验收：审查修复后 66 项媒体 task/worker/backend/queue client 回归全部通过；相关 `py_compile`、harness checker 与 `git diff --check` 通过。
- 多视角审查：correctness、security/boundary、runner/media/paid 三个独立只读视角完成。初审发现 provider task 可绕过原子 binding、依赖数组边界检查晚于 workspace lock，以及 wait 会接受 deadline 后才观察到的终态；主线程逐项修复并补回归，终审均为 no findings。
- 唯一 canonical：implementation commit `d116de9d7de0271f006810773c1847ced372c646` 上 `bash scripts/verify.sh` exit 0，**2694 tests OK**、15 steps / 369 秒，run `4662e3bc93b74ac5934bdd823e00022b`，tree `2e8b410c045ba128135b1eb295b93d5e2929a157`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN。
- 真文本局部协议校准：使用用户授权配置执行 1 request，HTTP 200、284 tokens、3.188 秒；`atomic_task_binding_commit`、`deadline_bounded_wait`、`legacy_provider_unbound_reconciliation`、`local_task_binding_not_applicable` 四项均通过。iter125-136 累计保守计 15/60 requests、12 次 HTTP/model response、10 次协议通过、预留约 ¥1.20；图片 0/20，视频/TTS 0。
- `A136-01`：通过；v1/v2 identity-preserving migration 与 legacy unbound reconciliation 回归覆盖。
- `A136-02`：通过；task+binding 单次原子入队、exact replay、dedupe 与 registry drift fail-closed 回归覆盖。
- `A136-03`：通过；provider binding gate、terminal/cancel retention、unknown 零重提与 local lease 回归覆盖。
- `A136-04`：通过；queue enqueue/get/bounded wait/cancel/restart 与三态安全投影回归覆盖。
- `A136-05`：通过；聚焦、三视角、唯一 canonical 与真文本局部协议校准均完成。总验收保持 `mock-functional` / `canonical-mock-offline`，mandatory `local_drama_e2e` 为 `local-e2e`，`provider_validated=false`；本次真文本只校准协议理解，不证明真实图片/视频/TTS provider 执行。
- 未修风险：无未处理 P0/P1/P2；G5 provider execution loop、pricing/Insights、现有 paid ledger reconciliation 与真实媒体质量仍在本轮范围外。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: provider task 的原子 task+binding、legacy 禁止补猜，以及 `frozen/legacy_unbound/not_applicable` 三态是后续 G5 execution/pricing 与 I workbench 都必须复用的持久产品合同，已在 G4 权威段落就地固化。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 strict ledger v3 与 task-binding identity 校验。 |
| `src/drama_media_tasks.py` | v1/v2→v3 逻辑迁移、原子 bound enqueue、provider binding gate、锁前依赖边界与三态投影。 |
| `src/drama_media_worker.py` | 所有 ledger mutation 保留 binding；provider task 强制 binding，local compose/export 保持 G2 lease。 |
| `src/drama_media_queue_client.py` | 新增纯本地 enqueue/get/bounded wait/cancel client。 |
| `tests/_drama_media_backend_fixture.py` | 新增 image/video/audio 零网络 registry fixture。 |
| `tests/test_drama_media_{tasks,worker,queue_client,backend_registry}.py` | 覆盖迁移、原子性、恢复、deadline、cancel、安全投影、local lease 与边界回归。 |
| `docs/product/short_drama_module.md` | 晋升 G4 持久 binding/queue client 权威合同与精确边界。 |
| `docs/iterations/{README.md,iteration_136_*.md}` | 登记 iter136、计划、实施、审查与验收记录。 |

## 不在本轮范围

- provider adapter callable、submit/poll/download/validate execution loop、Web mutation、pricing/Insights。
- 现有 C/D/E paid ledger 迁移、真实图片/视频/TTS、TTS 测试与主观质量验证。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
