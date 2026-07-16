# Iteration 114 - 短剧逐镜图片 Provider 能力与可恢复生成尝试

## Context

iter111 已把 fresh `RenderPlan`、exact 角色/场景/道具线索版本与确定性 reference policy 装配为 provider-neutral `EpisodeShotImagePlan`；iter113 已建立 content-addressed strict PNG 候选、显式 first/tail/previous-tail selection、精确 stale/coverage 与 create-only repair。当前 handoff 与 README 明示的阶段 C 下一缺口，是 provider capability、逐镜生成 attempt 和 paid/crash 恢复接缝；但现有 `ai_draw_client.redraw_character_reference()` 强绑定角色生图、只发送 prompt/model/size，不能证明消费了 C1 的 exact 多参考图。本轮因此只做纯本地 C3：冻结 capability/provider/request 身份，通过可注入的确定性 fake adapter 建立一次调用、durable receipt、候选入池与重启零重复调用闭环；不接真实网络 adapter，不运行任何真生图。

## Plan

### Implementation Context
- `must_read`: `README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_111_drama_shot_image_spec_reference_assembly.md`, `docs/iterations/iteration_113_drama_shot_image_candidates_first_tail_binding.md`, `src/drama_schemas.py`, `src/drama_shot_image.py`, `src/drama_shot_image_store.py`, `src/drama_shot_image_candidates.py`, `src/drama_shot_image_candidate_store.py`, `src/paid_recovery_states.py`, `src/ai_draw_client.py`, `src/drama_multimodal_smoke.py`, `tests/_drama_shot_image_candidate_base.py`, `tests/test_drama_shot_image_candidate_store.py`, `tests/test_drama_paid_recovery_states.py`, `tests/test_drama_crash_restart_matrix.py`
- `expected_changes`: `docs/iterations/iteration_114_drama_shot_image_provider_capability_attempt_recovery.md`, `docs/iterations/README.md`, `src/drama_schemas.py`, `src/drama_shot_image_attempts.py`, `src/drama_shot_image_attempt_store.py`, `src/paid_recovery_states.py`, `tests/_drama_shot_image_attempt_base.py`, `tests/test_drama_shot_image_attempts.py`, `tests/test_drama_shot_image_attempt_store.py`, `tests/support/drama_shot_image_attempt_driver.py`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`
- `do_not_touch`: `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/`、用户未跟踪体检报告；不改 `src/ai_draw_client.py`、`src/drama_multimodal_smoke.py`、`tests/support/local_drama_provider.py` 或任何真实网络/provider 协议；不改 Web/jobs、CLI、preflight/config、现有导出、episode-1 video、`DramaEpisode`、`RenderPlan`、C1/C2 既有 identity；canonical verify 自管 acceptance 产物除外

1. 在 `drama_schemas.py` 增加 strict `ShotImageProviderCapability`、attempt spec、artifact receipt、attempt record 与 episode ledger/inspection projection。attempt 冻结 episode/shot、C1 plan/request fingerprint、C2 pre-manifest fingerprint、provider/capability fingerprint、prompt SHA、exact effective reference fingerprint、artifact receipt 与 candidate identity；持久状态禁止保存 key、完整 prompt、endpoint、签名 URL 或 provider raw response，也不修改 C1/C2 既有 schema shape。
2. 新建 `drama_shot_image_attempts.py` 作为纯函数领域层：从 fresh C1 request、fresh C2 manifest 与静态 capability 构建 byte-stable attempt spec；校验 ordered exact references、输出 `image/png` 和 capability compatibility。C1 已完成的确定性 reference policy 是唯一裁剪层，attempt 层不得二次临时裁剪、猜测或伪称已消费 provider 不支持的 reference；不兼容时在任何 adapter 调用前 fail closed。
3. 定义最小、代码内可注入的 `ShotImageProviderAdapter` seam，仅供本地 deterministic fake adapter 与未来已审查 backend 实现；不做动态 registry、热加载或通用 worker。adapter 接收内存中的受控 prompt、exact reference bytes 和私有 staging path，返回受控结果；持久 ledger 只保存 fingerprints、bounded metadata 与 strict PNG receipt。
4. 新建 `drama_shot_image_attempt_store.py`：在 workspace lock 内重读 fresh C1/C2、provider/capability 与 target CAS，先 durable 写 `started` 再允许一次 adapter 调用；strict PNG 落私有 staging 后 durable 写 `artifact_received`，再只通过现有 `append_local_shot_image_candidate()` 进入 C2，最后以 exact candidate/manifest identity 写 `succeeded`。candidate 继续 content-addressed，新候选不得自动选择 first/tail，也不建立第二套候选真源或 PNG validator。
5. 恢复按现有 image paid vocabulary fail closed：只有能证明 request not sent 的分支可释放本轮未提交机会；单独 `started` 视为 submission outcome unknown，timeout/network/provider/local error 均不得自动重调 adapter；`artifact_received`、candidate 已 append 但 ledger 未成功、以及 exact succeeded 重放都只能凭 receipt/candidate identity 零 adapter 收尾。C1/C2/provider/capability/CAS 漂移时保留旧证据并 blocked，不把旧 artifact 附到新 request。
6. 新增纯函数、store 与真实子进程 crash seam 测试。测试 fake adapter 使用持久 counter 证明 marker-before-call、response loss、staging/receipt/candidate/ledger 各窗口重启后的 generate delta 为零，并覆盖 schema、fingerprint、source/target/provider ABA、深层/超限/重复键 JSON、PNG/hash/尺寸、symlink/FIFO/目录、TOCTOU/temp ownership、错误脱敏和 socket sentinel。完成聚焦检查和三视角只读审查、修复 findings 后形成 implementation commit，最后只运行一次 canonical `bash scripts/verify.sh`，再用 `iter-finish` 收官。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 C1 request → capability-bound attempt → receipt → C2 candidate 的 exact identity、C1 单一 reference 裁剪语义、marker-before-call、candidate append 幂等、new candidate 不自动选择、provider/CAS 漂移与 iter105-113 向后兼容
- `security_boundary`: 核对 ledger/staging 的 workspace confinement、bounded strict JSON/PNG、nofollow/nonblock/regular-file、symlink/FIFO/目录/TOCTOU、provider/account/model/endpoint 只存 fingerprint、错误与公开投影不泄露完整 prompt/URL/response/凭据、全链除注入 fake adapter 外零网络
- `extra_risk_view`: `media/storage/recovery`，核对 started unknown outcome、staging adoption、artifact receipt、candidate append 后补账、真实子进程 crash、provider counter 与 restart delta，以及 source/target/provider ABA 时均不重复调用且安全停止

- **A114-01**：capability、attempt spec、artifact receipt、attempt record 与 episode ledger 可 byte-stable round-trip；拒绝 extra、bool 冒充整数、非有限数、未知状态、字段组合错误、跨 episode/shot 身份、非 canonical 相对路径和 fingerprint 篡改；不改变 `DramaEpisode`、`RenderPlan`、`EpisodeShotImagePlan` 与 C2 manifest/candidate 既有 shape。
- **A114-02**：attempt 只从 fresh assembled C1 request 与 fresh C2 manifest 构建，冻结 provider/capability、plan/request、pre-manifest、prompt 与 ordered exact reference fingerprints；capability 不支持媒体类型或 exact references 时零 adapter 调用并 fail closed。C1 reference policy 保持唯一确定性裁剪层，attempt 不二次裁剪、不猜引用、不伪称已发送。
- **A114-03**：每次 adapter 调用前在同一 workspace lock/CAS 域内 durable 写 `started`；fake adapter 持久 counter 证明每个 attempt 最多调用一次。只有明确 request-not-sent 可安全释放；started/timeout/network/provider/local error 重启均不得自动重调，provider/capability/config 漂移不得续跑旧 attempt。
- **A114-04**：strict PNG 先形成 bounded receipt，再只经 `append_local_shot_image_candidate()` 进入 C2；receipt SHA/尺寸与 candidate ID/fingerprint/manifest post-fingerprint 精确互证。`artifact_received`、candidate 已存在与 succeeded lost-response 可零 adapter 幂等收尾，不产生重复 candidate，也不修改 first/tail selection。
- **A114-05**：真实子进程覆盖 call 前、started 后、adapter 结果后、receipt 后、candidate append 后和 succeeded 后 crash；除明确 not-sent 外 restart generate delta 均为 0。store 的 bounded strict JSON/PNG、workspace lock、source/target/provider CAS、nofollow/nonblock/regular-file、dirfd/atomic replace、inode ownership、symlink/FIFO/目录、深层/超限/重复键 JSON、坏 PNG/hash/尺寸、race 与错误脱敏均通过，socket 哨兵证明生产路径零网络。
- **A114-06**：新增链与 iter105-113、C1/C2、资产/RenderPlan、paid recovery matrix、四导出、season export、episode-1 video 聚焦回归通过；correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高验收等级为 `mock-functional`，`provider_validated=false`，不运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。

## Implementation Notes

- 采用“领域纯函数 + strict local store + 注入 adapter”三层拆分：`drama_shot_image_attempts.py` 只负责 capability/spec/receipt/ledger 状态机，`drama_shot_image_attempt_store.py` 负责 workspace lock、CAS、staging、C2 bridge 与恢复；本轮不注册或连接真实 provider。
- adapter 只接收内存中的受控 prompt 与 C1 ordered exact reference bytes，并返回 bytes；私有 staging 完全由 store 管理，避免把本地路径误当成 provider 协议。C1 reference policy 仍是唯一裁剪层，capability 不兼容时在 durable marker 与 adapter 调用前失败。
- attempt ledger 位于 `logs/drama_shot_images/episode_NN.attempts.json`，staging 位于 `logs/drama_shot_images/episode_NN/<shot_id>/<attempt_id>.png`。ledger 不保存 prompt、endpoint、URL、key 或 raw response；adapter 异常先退出活动 `except`，再用 bounded 状态与公开消息持久化/抛出，避免通过 exception context 泄露原始错误。
- `started` 在 adapter 调用前持久化；只有 `RequestNotSentError` 这一注入契约可释放未提交机会。timeout/network/provider/local error 与 outcome unknown 均保留证据且不自动重调。adapter 正常返回但 staging 尚未落盘的窗口仍视为 unknown，不冒充可恢复结果。
- receipt 在 staging 写入前完成 strict PNG identity/尺寸校验。`artifact_received` 先查 C2 exact candidate：candidate 已持久化时，即使 staging 丢失或损坏，也可零 adapter 补账；仅 candidate 缺失时才从 receipt-verified staging 经 `append_local_shot_image_candidate()` 入池。
- 最终 `succeeded` 落账前在 workspace lock 内重新读取 ledger、fresh C1/C2，复核 source 与 receipt-derived exact candidate，并绑定锁内最新 manifest fingerprint；因此 C2 selection race 可安全补账，source/candidate 漂移则保留证据并停止。
- inspection 以“每镜 latest unresolved 优先阻断；否则查当前 plan/request 的 compatible succeeded execution fact”为准，既不让旧历史永久污染当前状态，也能正确处理 source A→B→A。
- 成功 staging 暂不自动删除。审查中发现基于 stat/unlink 的清理会引入 inode TOCTOU；本轮选择保留私有 paid evidence，后续如需 GC 必须另建显式、可审计的回收协议。
- durability 声明严格限于本轮真实子进程 crash/restart 证据。ledger/staging 文件与最终 parent directory 会 fsync，但首次创建的多级父目录未逐级证明断电持久性；不外推 power-loss、内核崩溃或 production provider exactly-once。
- 三视角审查先后修复：unresolved provider/source drift 二次提交、ledger 8MB CAS、PNG receipt 前置、candidate-first 补账、危险 staging cleanup、目录 fsync、candidate identity 交叉验证、历史 inspection 污染、adapter-return crash seam、最终锁前 C1/C2 race、source ABA 与 exception-context 脱敏。
- A114-05 的直接故障注入覆盖 duplicate/deep/oversize JSON、ledger/staging symlink/FIFO/目录、partial ledger/staging write、owned temp cleanup、temp inode replacement、target precommit mutation、`O_NOFOLLOW` 缺失、receipt/candidate tamper、尺寸越界、错误脱敏与真实子进程 crash windows。残余威胁边界是不遵守 workspace lock 的本机进程在最终检查至 replace 微窗口直接篡改；不宣称穷尽所有 hostile-filesystem TOCTOU 或 content ABA。
- 范围变化：用户在实现确认时明确要求收官同步“进度记录、SOP 的阶段记录文档”，因此 docs-only 收官会在原 `README.md`、handoff/history 之外同步 `docs/product/short_drama_module.md` 的阶段 C 现状；不改实现 Plan，也不触碰其它产品协议。

## Acceptance Result

- **A114-01：通过。** capability/spec/receipt/record/ledger/inspection strict schemas 与 byte-stable fingerprints 已落地；extra、bool/数值、状态组合、路径与 fingerprint 篡改均由纯函数/schema 测试拒绝，C1/C2/`DramaEpisode`/`RenderPlan` 既有 shape 未改。
- **A114-02：通过。** attempt 只从 fresh C1+C2 构建并冻结 provider/capability、plan/request、pre-manifest、prompt SHA 与 ordered exact references；capability 不兼容在 marker/adapter 前失败。socket sentinel 证明本轮生产路径零网络，attempt 层无二次裁剪。
- **A114-03：通过。** adapter 前 durable `started` 与持久 counter 证明每 attempt 最多调用一次；只有 `RequestNotSentError` 可释放机会，started/timeout/network/provider/local error 与 provider/capability/source drift 均不会自动重调。adapter raw exception 在退出活动 `except` 后才映射为 bounded public error，exception context 与 ledger 均不泄露测试 secret。
- **A114-04：通过。** strict PNG receipt 在 staging 前完成 identity/尺寸校验，只经既有 C2 append 入池；receipt/candidate identity 交叉校验。artifact_received、candidate 已 append 后 staging 丢失/损坏、succeeded lost response 均可零 adapter 补账，不重复 candidate、不改 first/tail selection。
- **A114-05：通过（限定 process crash）。** 真实子进程覆盖 after-started、outcome-unknown call、adapter-return、staging、receipt、candidate、succeeded 窗口；除明确 not-sent 外 restart generate delta 均为 0。直接故障注入覆盖 duplicate/deep/oversize JSON、ledger/staging symlink/FIFO/目录、partial ledger/staging write、owned temp cleanup、temp inode replacement、target precommit mutation、`O_NOFOLLOW` 缺失、receipt/candidate tamper、尺寸越界、final-lock C2 race、source ABA 与错误脱敏。
- **A114-06：通过。** iter105-114/C1-C2/资产/RenderPlan/paid recovery/导出/season/video 聚焦回归 **255 tests OK**；correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角二次复审均无遗留 P0/P1/P2。
- authoritative canonical `bash scripts/verify.sh` 在 implementation commit `562bf7f3f45b26135157793eb90fe3d6531c1400` 上 exit 0：**2319 tests OK**，15 steps / 164 秒，run `9233ee3898044ca58b019e91754db46c`，tree `bf99ecfb59a8b7c57b882fdfd64e7b0e45a6d59d`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN。最终 evidence 为 `mock-functional` / `canonical-mock-offline`；`local_drama_e2e` 子步骤为 fake-provider `local-e2e`，`provider_validated=false`。
- 验收次数偏差：首次 canonical run 在 `b218049` 上通过，但 docs-only 收官 checker 随后发现用户追加要求的 `docs/product/short_drama_module.md` 不属于 post-accept closure 白名单。该 SOP 变更被补入 amended implementation commit 后，首次 evidence 因 commit identity 改变而作废；因此按收官门禁失败后的修复流程重新运行一次，并只以上述 `562bf7f` evidence 为最终权威证据。
- 未运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。残余边界：首次创建的多级父目录未逐级证明断电持久性；成功 staging 为避免 inode cleanup TOCTOU 暂保留；不遵守 workspace lock 的本机进程仍可在最终检查微窗口竞态。本轮不宣称 power-loss、hostile-filesystem 或 production-provider exactly-once。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮形成的是短剧阶段 C 的产品专用 capability/attempt/recovery 契约，已由代码、测试、iteration 与既有短剧 SOP 承载；未产生需要推广到跨项目 AGENTS/skill 的新工作流规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_114_drama_shot_image_provider_capability_attempt_recovery.md` | 新建 iter114 固定八段计划与 C3 边界 |
| `docs/iterations/README.md` | 追加 iter114 canonical index |
| `src/drama_schemas.py` | 新增 strict capability、attempt spec/receipt/record/ledger/inspection schemas |
| `src/drama_shot_image_attempts.py` | 新增 C3 byte-stable 领域状态机与 exact identity 构建 |
| `src/drama_shot_image_attempt_store.py` | 新增一次调用、durable marker/receipt、C2 bridge、CAS 与 crash recovery store |
| `src/paid_recovery_states.py` | 复用既有 paid image 状态词汇作为 shot-image attempt/receipt canonical aliases |
| `tests/_drama_shot_image_attempt_base.py` | 新增 C3 synthetic fixture |
| `tests/test_drama_shot_image_attempts.py` | 新增 capability/spec/receipt/ledger 纯函数与 schema 测试 |
| `tests/test_drama_shot_image_attempt_store.py` | 新增 once-only、恢复、边界、race、脱敏与 C2 bridge 测试 |
| `tests/support/drama_shot_image_attempt_driver.py` | 新增真实子进程 crash-window driver |
| `tests/test_drama_paid_recovery_states.py` | 锁定 shot-image paid vocabulary 与既有 image canonical identity |
| `README.md` | 同步 iter114 状态与短剧阶段 C 的 C1-C3 当前边界 |
| `docs/AGENT_HANDOFF.md` | 就地更新当前基线、能力/缺口、验收证据与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | 追加 iter114 里程碑、实现索引与 paid attempt 长期决策 |
| `docs/product/short_drama_module.md` | 按用户要求更新完整生产 SOP 的阶段 C 实时记录 |

## 不在本轮范围

- 真实 `ai_draw_client` 逐镜接线、真实 provider、多参考图上传/编码协议、真实授权/预算/计费、provider poll/download、自动重试或人工对账 UI。
- loopback HTTP fake-provider 新协议、production URL allowlist、动态 capability registry、通用 task DAG/worker/lease/provider lane/pricing/Insights；这些不能由本轮测试 adapter 外推。
- JPEG/WebP decoder、远端 MIME/redirect/DNS/peer-IP 下载校验、通用媒体导入；本轮沿用 strict PNG 本地 artifact 边界。
- Web/API/CLI、镜头候选比较 UI、批量生成、自动 first/tail selection、资产管理 UI、跨集 used-by、ArtDirection 多 scope 或通用 visual override。
- 逐镜视频、episode 2+ 视频、TTS/voice、`TimelineManifest`、字幕、BGM/SFX、FFmpeg/compositor、编辑器导出、事件图、生产工作台与归档。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1、C1 request/plan shape、C2 candidate/manifest identity、现有 Comfy/season export/episode-1 video 消费路径。
- `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪文件。

## Notes

- 本轮立项只建立 iteration 文档与索引；用户确认前不实现、不跑业务测试或 `verify.sh`。
- 现有 `ai_draw_client` 的 prompt-only 角色生图协议不能冒充已消费 C1 exact references；后续真实 network adapter 必须另起 iteration，并逐次确认真实 provider、协议、授权、预算和恢复边界。
- `docs/product/short_drama_module.md` 的阶段 C 细表在立项时仍写“逐镜候选未实现”；用户确认实现时明确要求收官同步 SOP 阶段记录，因此 docs-only 收官已按 C1-C3 当前事实就地修正，仍保留真实 provider/JPEG-WebP/质量 UI/GC/power-loss 未完成边界。
- implementation commit 信息草案：`feat(drama): add recoverable shot image attempts (iter114)`。
