# Iteration 133 - 短剧通用媒体任务 DAG 与持久状态

## Context

iter114/117/121 已分别建立图片、视频、TTS 的 once-only attempt 与 paid recovery，iter123/125/132 完成本地 F1-F3 合成、可编辑导出和 Web exact delivery。C-F 已出现稳定重复的依赖、active dedupe、状态转换、取消与恢复语义，可以进入阶段 G；但 paid ledger/receipt 仍必须保持独立真源。本轮只完成 G1 的最小持久 task DAG，不接 provider/backend、不迁移现有 attempt、不实现 worker lease 或 pricing。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/paid_recovery_states.py`, `src/drama_shot_image_attempt_store.py`, `src/drama_shot_video_attempt_store.py`, `src/drama_tts_attempt_store.py`, `src/drama_compositor.py`, `src/workspace_lock.py`, `src/web/jobs.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_tasks.py`, `tests/test_drama_media_tasks.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_133_drama_media_task_dag_persistent_state.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真文本/图片/视频/TTS，不读取或迁移现有 paid ledger，不 push

1. 从 C-F 现有任务提取最小 strict schema：workspace-local task ID、episode/shot/media/stage、immutable input/provider identity、dependency IDs、dedupe key、状态、revision、时间与安全结果摘要；不保存 prompt、凭据、provider response 或签名 URL。
2. 建立 episode-scoped JSON task store：nofollow/regular-file/size/depth、workspace lock、原子写、content hash 与 revision/current-state CAS；坏文件、symlink、跨 workspace/episode/依赖 identity fail closed。
3. 实现 DAG 与 active dedupe：只允许依赖同 workspace/episode 的既有任务，拒绝环、自依赖、重复边；相同 dedupe+input 的 active task exact replay，不吞掉新 revision/input。
4. 实现 guarded transitions 与 cancellation cascade：状态图覆盖 planned/ready/claimed/submitting/submitted/polling/submission_unknown/downloading/validating/succeeded/failed/cancelling/cancelled；unknown submission 不得回到可 submit 状态，generic task 不得伪造或替代 paid evidence。
5. 提供 strict/bounded 只读安全投影与聚焦测试；本轮不接 Web mutation、worker、backend 或 provider。同步修正 iter132 canonical 后顺延的 F3 产品 SOP 字节上限/episode 2 本地证据措辞。

## Acceptance

### Review Context
- `correctness_behavior`: DAG 拓扑、active dedupe、revision/CAS、exact replay、guarded transition、cancel cascade 与终态幂等必须稳定；generic state 不改变 C-F artifact/receipt/fingerprint 或 paid recovery 语义
- `security_boundary`: workspace/episode/task/dependency identity、nofollow/regular-file/容量/depth、原子提交、坏 JSON/额外字段/环/竞态、公开投影脱敏与 unknown submission 零重提 fail closed
- `extra_risk_view`: runner/media/paid 专项，复核 task store 与 workspace lock、多进程边界、取消传播、generic task 和 paid ledger 的单向引用、不接 provider 的零网络证明

- **A133-01**：strict media task/DAG schema 仅接受 allowlist 字段与同 workspace/episode 依赖，环、自依赖、坏 identity、bool/非有限数、额外字段和伪 hash 被拒绝。
- **A133-02**：持久 task store 使用 workspace lock、nofollow、bounded read、原子 CAS；create/read/list/active dedupe/exact replay 在重启后确定，坏文件/symlink/竞态不覆盖。
- **A133-03**：guarded transition 与 cancel cascade 覆盖完整状态图；终态幂等，非法回退被拒，`submission_unknown` 永不自动回到 submit，合法新 input/revision 不被旧 dedupe 吞掉。
- **A133-04**：安全投影有界且不含 path、prompt、凭据、provider response、签名 URL 或 paid ledger 内部字段；现有 C-F tests/receipt/fingerprint 语义不漂移，provider/network 调用为 0。
- **A133-05**：聚焦回归与 correctness/security/runner-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 新增 `DramaMediaTask`/`DramaMediaTaskLedger` strict schema：task/dedupe/record/ledger 均 content-addressed，task 只保存 provider identity fingerprints，不保存 prompt、provider task/response、签名 URL 或 paid receipt。
- 新增 episode-scoped `episode_NNN.tasks.json` store：4 MiB 上限、strict duplicate-key JSON、nofollow regular-file read、pinned dirfd 原子写、target-token CAS 与 workspace write lock；missing ledger 只在已验证的 drama workspace 上表现为空 DAG。
- create 支持 lost-response exact replay、active dedupe 与终态后的连续 attempt；同 ledger 依赖、创建时间因果、canonical dependency list、环和跨 episode 引用 fail closed。
- transition 使用显式 allowlist；成功后在同一 ledger commit 中晋升依赖已满足的 planned task，且 child 时间不因较早的 parent transition 倒退；失败沿 planned descendants 传播为 `dependency_failed`；`submission_unknown` 无任何出边并持续占用 active dedupe，不允许 generic task 自动重发或无 paid evidence 地“确认”。
- cancel 沿 transitive dependents 传播为 `cancelling`，保留 `submission_unknown`，拒绝取消 succeeded/failed，且 stale exact cancel replay 不重复提交。
- 安全投影只公开 task/episode/media/stage/subject/dependency/state/revision/time/result hash/有限本地 outcome code；隐藏 backend/provider/model/account/endpoint identity 与所有 paid/provider 内部数据。
- 收官前新增非 drama workspace 投影测试时发现类型边界缺口；已改为 strict nofollow/regular-file/4 KiB/exact-schema metadata 读取，防止普通小说 workspace、metadata symlink/oversize/bool schema 被误报为空短剧 DAG。
- 三视角审查的有效 findings 已修复并聚焦回归：mutation CAS 入口严格拒绝 bool/float/越界 revision/time 与坏 task/ledger identity；dead dependency 新建拒绝位于 existing exact replay 之后；failed/cancelled/unknown 后的既有 child 仍可 lost-response replay，新 child 被拒；failed/unknown/cancelled outcome 采用 state-specific allowlist。
- 合理范围变化：按 iter132 canonical 后的顺延事项，在产品 SOP 中更正 F3 为“总源集 128 MiB、生成/验证/交付单一 64 MiB 上限”，并登记真实本地 episode 2 证据；不改变 F3 代码。
- 聚焦 sanity：新增媒体任务测试 15 项通过；既有 image/video/TTS attempt 26 项通过；`py_compile`、agent harness 与 `git diff --check` 通过，provider/network 调用为 0。

## Acceptance Result

<iter-finish 回填 A133-01..05、测试数、canonical、真文本校准、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: G1 的通用 task DAG、unknown submission、取消级联和 paid evidence 隔离是后续 G2+ worker/backend/pricing 的长期产品与安全契约，已在 implementation commit 前晋升至短剧模块权威 SOP。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 strict 通用媒体任务与 episode DAG ledger schema |
| `src/drama_media_tasks.py` | 新增持久 store、CAS create/transition/cancel 与安全投影 |
| `tests/test_drama_media_tasks.py` | 新增 DAG、dedupe、恢复、取消、tamper 与投影边界测试 |
| `docs/product/short_drama_module.md` | 晋升 G1 长期契约并同步 F3 顺延更正 |
| `docs/iterations/iteration_133_drama_media_task_dag_persistent_state.md` | 本轮计划与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |

## 不在本轮范围

- worker lease/heartbeat/takeover、provider×media capacity lane、backend registry/adapter、queue client、pricing/Insights。
- 现有图片/视频/TTS paid ledger 迁移、Web mutation、真实 provider、真图片/视频/TTS 与主观质量验证。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
