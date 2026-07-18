# Iteration 134 - 短剧媒体 Worker Lease 与容量 Lane

## Context

iter133 已完成 G1 episode-scoped 持久 task DAG、active dedupe、guarded transition、failure/cancel cascade 与安全投影；但 task 仍只能由调用方直接推进，尚无多进程安全的 claim、heartbeat、lease expiry/takeover 或 provider×media capacity。阶段 G 的下一依赖是 G2：先建立完全本地、零 provider 的 worker ownership 与容量语义，再进入 backend registry/queue client；现有图片、视频、TTS paid ledger 继续保持独立权威真源。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_media_tasks.py`, `src/drama_schemas.py`, `src/workspace_lock.py`, `src/paid_recovery_states.py`, `src/web/jobs.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `tests/test_drama_media_tasks.py`, `tests/test_drama_media_worker.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_134_drama_media_worker_lease_capacity.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真图片/视频/TTS，不读取或迁移现有 paid ledger，不接 backend/provider/queue/Web mutation，不 push

1. 在 G1 ledger 内加入 strict lease 记录并提供确定性 schema migration；task/dedupe/input/provider identity、artifact 与 paid evidence identity 不变，坏旧版本、伪 lease、重复 owner/task、过期/未来时间和额外字段 fail closed。
2. 实现原子 claim：只 claim `ready` task，在同一 ledger commit 中转为 `claimed` 并写 lease；workspace lock 下扫描全部 episode ledger 的未过期 lease，按 provider identity×media lane 执行显式容量，避免分集超卖。
3. 实现 heartbeat/release/takeover：仅持有匹配 owner+lease token 的 worker 可续租或释放；未过期 lease 不可抢占，过期 lease 可由新 worker 在同一原子 commit 中 takeover；旧 token/ABA/stale revision 不得恢复所有权。
4. 取消/失败/成功等终态必须清除 lease；worker crash 只依赖持久 deadline 判定，不读 PID、不猜进程存活；`submission_unknown` 不 claim、不 takeover、不释放 active dedupe。
5. 提供 bounded worker/lease 安全投影与跨进程/跨 episode 聚焦测试；本轮无执行 loop、无 provider adapter、无网络、无 pricing，`src/web/jobs.py` 行为保持不变。

## Acceptance

### Review Context
- `correctness_behavior`: ledger v1→v2 兼容、claim/heartbeat/release/takeover 状态机、lease CAS/ABA、跨 episode lane 容量、终态 lease 清理与 G1 exact replay 必须确定；现有 C-F artifact/receipt/fingerprint 和 paid recovery 语义不漂移
- `security_boundary`: worker/token/provider/lane identity、strict int/time/duration/capacity、nofollow bounded multi-ledger scan、workspace lock/原子提交、symlink/坏 JSON/竞态、过期判断与公开投影脱敏均 fail closed
- `extra_risk_view`: runner/media/paid 专项，复核多进程 claim、跨 episode 容量、crash/takeover、lease 与 paid authorization 单向边界、零 provider/network

- **A134-01**：strict lease/current ledger schema 与 v1→v2 migration 保持 G1 task/dedupe/input/provider identity，拒绝伪 owner/token/lane、bool/float/越界时间与坏 hash。
- **A134-02**：workspace lock 下多进程/多 episode claim 至多一次；provider×media lane 容量不会因 episode 分片超卖，capacity full 明确 blocked 且不改变 ledger。
- **A134-03**：heartbeat/release/takeover 使用 owner+token+task revision+ledger fingerprint guarded CAS；未过期不可抢占、过期可安全接管、旧 token 与 exact replay 不制造双 owner。
- **A134-04**：终态/取消清理 lease，unknown submission 永不自动 claim/resubmit；安全投影不含 token、worker/provider/account/path/prompt/paid evidence，现有 G1/C-F 回归与 provider/network 0 调用成立。
- **A134-05**：聚焦回归与 correctness/security/runner-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- G1 `DramaMediaTaskLedger` 保留为 strict v1 reader；新增 v2 ledger 将 lease、release/transition replay receipt 与 task 放在同一 content-addressed envelope。非在途 v1 保持 task/dedupe identity 并在下一次受控 mutation 原子写 v2；缺失 ownership 的六种 v1 在途态显式 safe-block 到 reconciliation，不伪造 lease。
- 新增 `DramaMediaWorkerLease` 及认证 receipt：绑定 task revision、worker/token fingerprints、provider×media lane、capacity、lease revision、before-ledger/task identity、claim/heartbeat/expiry 与 record hash；owner/token/lane/receipt 不进入公开投影。
- 新增 `drama_media_worker.py`：workspace lock 内读取可信时钟并完成 claim、heartbeat、release、expired takeover；调用方不再提供 mutation clock。claim 用 bounded no-follow scan 覆盖 workspace 全部 episode ledger，active policy 不一致或 capacity full 不写 target。
- G2 关闭通用 `ready→claimed` 与 post-claim transition 旁路；执行态 mutation/replay 必须匹配 live owner/token、task/lease CAS，terminal/unknown/release lost-response 依赖同 ledger receipt。takeover 必须轮换 token；所有返回 lease 的 replay 在 expiry 后 fail closed。
- release、claim、takeover 与 transition 均拒绝 task 时间回拨；expired release 只能 takeover/reconciliation。terminal/unknown/cancel 清 lease，receipt 生命周期随后续 task mutation 确定性替换或清理；本轮仍无 provider execution loop。
- 三视角首轮发现 caller-controlled clock、transition ownership bypass、v1 in-flight、token ABA、expired release、unauthenticated replay/time rewind；主线程逐项复核并修复。两轮复核又发现 active/terminal replay 与 expired replay 窗口，补充可信时钟 live check 和 authenticated transition receipt 后收敛。
- 聚焦 sanity：G2+G1 共 29 tests OK；G2/G1 + paid recovery + image/video attempt store 共 79 tests OK。覆盖 fork 双进程 claim、跨 episode capacity、v1 safe migration/reconciliation、owner/expiry guarded replay、receipt auth、token rotation、time monotonic、strict numeric/nofollow bounded scan 与 socket 零网络；`py_compile`、harness、`git diff --check` 通过。

## Acceptance Result

- **A134-01 — passed**：新增 strict v2 ledger、worker lease、release/transition receipt；task/dedupe/input/provider identity 保持不变。非在途 v1 逻辑升级后下一次 mutation 写 v2；`claimed/submitting/submitted/polling/downloading/validating` 六种缺 owner 证据的 v1 在途态显式 `requires reconciliation`，不合成授权。strict numeric/hash/time/order/task binding 与 receipt content address 均由 schema 和聚焦矩阵覆盖。
- **A134-02 — passed**：claim 在 workspace lock 内以 bounded no-follow scan 遍历全部 canonical episode ledger，使用同一可信时钟计算未过期 lease；provider fingerprint×media kind lane 的 capacity 与 active policy 跨集共享。fork 双进程同 task 竞争只有一个 owner，capacity full/policy drift/坏 namespace 均不改目标 ledger。
- **A134-03 — passed**：claim/heartbeat/release/takeover 及 execution transition 使用 owner+token、task/lease revision、ledger fingerprint guarded CAS；所有 worker mutation 和返回 active lease 的 replay 都在锁内重验可信时钟。expired release/heartbeat/replay fail closed，takeover 必须轮换 token；release/transition lost-response 由同 ledger receipt 认证，非 owner、旧 owner、current-revision 冒认和 ABA 均被回归阻断。
- **A134-04 — passed**：terminal、`submission_unknown` 与 cancel cascade 确定性清 lease/失效同 task receipt；unknown 仍无 generic 出边且不能 claim/resubmit。公开投影不含 owner/token/lane/provider/account/path/prompt/paid evidence；worker/task 模块不导入 provider adapter 或 paid store。最终聚焦 G1/G2 29 tests OK；此前 G1/G2 + paid recovery + image/video attempt store 79 tests OK，图片/视频/TTS/provider/network 调用均为 0。
- **A134-05 — passed**：correctness、security/boundary、runner/media/paid 三视角首轮共发现 caller-controlled clock、post-claim ownership bypass、v1 in-flight、token ABA、expired release、unauthenticated replay 与时间回拨；主线程逐条复现修复。后续复核继续发现 active/terminal/expired replay 窗口并补 trusted-clock live check 与 authenticated transition receipt；三视角最终均 **no findings（P0-P2）**，未修风险仅为本轮明确排除的 G3+ backend/queue/provider loop/pricing 和真实媒体校准。
- implementation commit `d19dfbb3192a3fcac90e685291b161a12341e5e5` 上唯一 canonical `bash scripts/verify.sh` exit 0：**2657 tests OK**、15 steps、369 秒，run `b67107f7411a4e53a7569fa259535047`，tree `000eb6f491acd4c2781cbb8901e5c6c2e1996aa1`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN。总口径 `mock-functional` / `canonical-mock-offline`，mandatory local-drama 子步骤为 `local-e2e`，`provider_validated=false`。
- 真文本按授权发生 2 次 HTTP attempt：第一次网关 HTTP 403、0.350 秒、无模型响应；按预授权追加一次相同模型/协议请求并仅补标准 User-Agent，`gpt-5.5-medium` HTTP 200、6.208 秒、provider usage 364 tokens，`trusted_clock / authenticated_transition_replay / token_rotation_takeover / legacy_inflight_reconciliation` 四项均 true，协议校准通过。iter125-134 累计保守计 13/60 请求、10 次 HTTP/model response、8 次协议检查通过，预留约 ¥1.00；图片 0/20、视频/TTS 0。未读取 `.env`，key、完整 prompt 与 response 正文均未输出或落盘。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: G2 的可信时钟、owner-guarded transition、v1 在途 reconciliation、token rotation 与认证 replay receipt 是后续 G3+ backend/queue/执行 loop 必须共同遵守的长期边界，已在 implementation commit 前晋升到短剧模块权威契约。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 strict worker lease、release/transition receipt 与 v2 task ledger |
| `src/drama_media_tasks.py` | 增加安全 v1→v2、owner-guarded transition、认证 replay 与 lease/receipt 生命周期 |
| `src/drama_media_worker.py` | 新增可信时钟 claim/heartbeat/release/takeover、跨集 lane capacity 与安全投影 |
| `tests/test_drama_media_tasks.py` | G1 测试改由 worker lease 进入 claimed |
| `tests/test_drama_media_worker.py` | 新增多进程、跨集容量、lease 恢复与迁移测试 |
| `docs/product/short_drama_module.md` | 晋升 G2 worker ownership 与 capacity 长期契约 |
| `docs/iterations/iteration_134_drama_media_worker_lease_capacity.md` | 本轮计划与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |

## 不在本轮范围

- backend registry/adapter、queue client/Web mutation、provider submit/poll/download/validate loop、pricing/Insights。
- 现有图片/视频/TTS paid ledger 迁移、真实图片/视频/TTS、TTS 测试与主观质量验证。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
