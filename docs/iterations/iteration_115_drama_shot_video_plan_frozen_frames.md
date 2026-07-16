# Iteration 115 - 短剧逐镜视频计划与冻结首尾帧契约

## Context

iter111、iter113 与 iter114 已依次完成阶段 C 的 provider-neutral 逐镜图片 request/exact references、content-addressed strict PNG 候选与显式 first/tail/previous-tail selection，以及 capability/once-only fake attempt/durable receipt/process-crash 零重复调用；当前 canonical 基线为 2319 tests OK，`provider_validated=false`。现有 `src/drama_video.py` 仍是 episode 1 单高光镜兼容 job，不能作为多镜头生产链的输入真源。

根据 `stage_plan_drama_full_production_pipeline` 阶段 D 与当前短剧 SOP，本轮只交付 D1 的纯本地窄闭环：从 fresh `RenderPlan`、fresh C1 `EpisodeShotImagePlan` 和 coverage ready 的 fresh C2 candidate manifest，确定性构建 provider-neutral `EpisodeShotVideoPlan`，为每个 stable shot 冻结目标时长、受控视觉输入、exact selected first、显式 optional tail、ordered exact references 与完整 source/selection lineage。用户确认前只完成本计划立项，不改业务代码；本轮也不接真实 provider、视频候选/attempt、Web/CLI 或通用 worker。

## Plan

### Implementation Context
- `must_read`: `README.md`, `docs/iterations/README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_113_drama_shot_image_candidates_first_tail_binding.md`, `docs/iterations/iteration_114_drama_shot_image_provider_capability_attempt_recovery.md`, `src/drama_schemas.py`, `src/drama_render_store.py`, `src/drama_shot_image.py`, `src/drama_shot_image_store.py`, `src/drama_shot_image_candidates.py`, `src/drama_shot_image_candidate_store.py`, `src/drama_video.py`, `src/drama_video_client.py`, `tests/_drama_shot_image_candidate_base.py`, `tests/test_drama_shot_image_candidates.py`, `tests/test_drama_shot_image_candidate_store.py`, `tests/test_drama_video.py`
- `expected_changes`: `docs/iterations/iteration_115_drama_shot_video_plan_frozen_frames.md`, `docs/iterations/README.md`, `src/drama_schemas.py`, `src/drama_shot_video.py`, `src/drama_shot_video_store.py`, `tests/_drama_shot_video_base.py`, `tests/test_drama_shot_video.py`, `tests/test_drama_shot_video_store.py`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪体检报告；`src/drama_video.py`、`src/drama_video_client.py` 仅作 episode-1 兼容回归，不改旧 job/client/smoke；不改 Web/jobs/routes、CLI/runner、paid recovery、C1-C3、`DramaEpisode`、`RenderPlan`、现有导出或任何真实 provider/network 入口；canonical verify 自管 acceptance 产物除外

1. 在 `src/drama_schemas.py` 新增 strict D1 schema：`ShotVideoFrameRef` 冻结 first/tail 的 source shot、candidate、artifact path/SHA/size/dimensions、binding revision 与 lineage；`ShotVideoRequestSpec` 冻结 stable shot、目标时长、受控 visual/camera/transition 输入摘要、exact first、显式 optional tail、C1 ordered exact references 与 source/selection fingerprints；`EpisodeShotVideoPlan` 保存同集有序 requests 和 byte-stable plan fingerprint。不得改变 `RenderPlan` 或 C1-C3 既有 shape。
2. 新建 `src/drama_shot_video.py` 作为纯函数领域层：只从同一 episode 的 fresh RenderPlan、C1 plan 与 C2 manifest 构建计划；C2 coverage 必须为 `ready`。direct first/tail 必须解析为 exact current candidate；`previous_tail` first 必须同时绑定上一镜 exact tail candidate、source shot、tail revision 与 target request lineage。tail 缺省不是隐式缺字段，而是显式 `none`。
3. D1 只冻结 provider-neutral 视频输入，不冻结 provider/model/account/endpoint/capability，也不执行第二次 reference 裁剪。每镜目标时长来自 `RenderShot.target_duration_seconds`；旧高光 job 的 5 秒、720p 或 episode-1 常量不得进入新协议。后续 D2 attempt lowering 再按 video capability 决定支持模式、分辨率和 provider 有效输入。
4. 新建 `src/drama_shot_video_store.py`，落盘 `episode_NN.shot_video_plan.json`，提供 `needs_shot_video_plan | fresh | stale | invalid | blocked_source` inspect/load/create。store 复用公开 fresh seams，在 workspace lock 内完成 source/target CAS、bounded strict JSON、nofollow/nonblock/regular-file、dirfd atomic replace、precommit source reread与显式 stale replacement；上游 non-ready、坏/缺 frame 或 broken lineage 均 fail closed，不覆盖 invalid 文件。
5. stale/affected-shot 语义保持精确：某镜 selected first/tail 或 request 变化只影响该镜；上一镜 tail 改变并破坏下一镜 `previous_tail` 时同时影响目标镜；追加未选 candidate、无关镜头变化和显式 tail=`none` 不得误 stale。旧 workspace 未有 D1 plan 时只返回 `needs_shot_video_plan`，不认领或迁移现有 episode-1 高光视频。
6. 新增 synthetic fixture、纯函数与 store 聚焦测试，覆盖 schema/fingerprint、episode 2+ 路径、direct/previous-tail/none、C2 coverage gate、artifact identity、精确 stale、JSON/path/symlink/FIFO/目录/race/锁/partial-write/temp ownership/脱敏和 socket sentinel 零网络，并回归 iter105-114、RenderPlan、C1-C3、四导出、season export 与 legacy episode-1 video。完成聚焦检查和三视角只读审查、修复 findings 后形成 implementation commit，最后只运行一次 canonical `bash scripts/verify.sh`，再用 `iter-finish` 收官。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 RenderPlan/C1/C2 三层 source identity、stable shot 顺序、target duration、direct/previous-tail/none exact binding、ordered references、精确 affected-shot stale、未选 candidate 不误伤及 legacy episode-1 video 向后兼容
- `security_boundary`: 核对 plan JSON 与 selected frame artifact 的 workspace confinement、bounded strict read、nofollow/nonblock/regular-file、path/SHA/size/dimensions、workspace lock、source/target CAS、TOCTOU/temp ownership、错误脱敏和全链零网络
- `extra_risk_view`: `media/storage/recovery`，核对坏/缺 frame、broken lineage、partial write、重启重读、selection race、source ABA 与 explicit stale replacement 均安全停止且不把旧输入写成 fresh

- **A115-01**：`ShotVideoFrameRef`、`ShotVideoRequestSpec` 与 `EpisodeShotVideoPlan` 可 strict、byte-stable round-trip；拒绝 extra、bool 冒充整数、非有限数、重复/跨 episode/shot identity、非 canonical 路径和 fingerprint 篡改；不改变 `DramaEpisode`、`RenderPlan` 与 C1-C3 既有 shape。
- **A115-02**：计划只从 fresh RenderPlan、fresh C1、fresh C2 且 coverage=`ready` 构建；逐镜冻结 exact first、显式 optional tail、target duration、受控视觉输入与 C1 ordered exact references，不重新排序、裁剪、猜测引用或提前绑定 provider/model/capability。
- **A115-03**：direct first/tail 与 `previous_tail` first 均解析到 exact candidate artifact；`previous_tail` 同时绑定 source shot、candidate fingerprint、tail revision 与 target request lineage。缺 first、断裂 lineage、stale/坏/缺 artifact 在任何后续视频行为前 fail closed，tail=`none` 保持合法且可复现。
- **A115-04**：stale 传播精确到真实依赖：selected first/tail 变化只影响依赖镜头，broken previous-tail 影响目标镜；未选 candidate append、无关镜头和 tail=`none` 不误 stale。旧 workspace 明示 `needs_shot_video_plan`，不认领旧 episode-1 高光产物。
- **A115-05**：store 五态、workspace lock、source/target CAS、explicit stale replacement、bounded strict JSON、nofollow/nonblock/regular-file、dirfd atomic replace、precommit reread与temp ownership拒绝 symlink、FIFO、目录、深层/超限/重复键 JSON、partial write、target/temp race 与 source ABA；invalid 文件不被覆盖，公开错误脱敏，socket sentinel 证明全链零网络。
- **A115-06**：新增链与 iter105-114、RenderPlan、C1-C3、四导出、season export、legacy episode-1 video 聚焦回归通过；correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高验收等级为 `mock-functional`，`provider_validated=false`，不运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。

## Implementation Notes

- 立项阶段已完成 Explore 与 Plan 两个独立只读视角；二者一致建议从阶段 C 转入 D1，并把 provider-neutral plan 与后续 provider attempt 分层。
- 用户已明确确认进入实现；实现阶段保持 mock/local，未触发真实 provider、真模型或旧 episode-1 视频网络链。
- D1 不把旧 `drama_video.py` 的 episode-1/高光/固定规格常量升级为新真源；新计划只消费 A/C 阶段的 fresh public seams。
- `EpisodeShotVideoPlan` 不绑定整份 C2 candidate manifest fingerprint，而只绑定 current selected first/tail、selection/tail revision、coverage 与每镜 request/source identity；因此追加未选 candidate 不会误 stale 已冻结视频输入。
- C2 reconcile 会合法保留 request 未变镜头的历史 candidate。`candidate_source_plan_fingerprint` 保留候选诞生时 provenance，不强制等于当前整份 C1 root；当前可用性由 per-shot request fingerprint、current manifest membership、coverage ready、fresh loader 与 precommit source reread共同证明，避免单镜变化迫使全片重生图。
- strict frame schema 以 season/episode/source shot/candidate request/source plan/fixed `local_png`/artifact identity 重算 C2 candidate ID/fingerprint，并要求 canonical artifact path；previous-tail 同时与上一镜冻结 tail 的 candidate/request/artifact/tail revision 对齐。
- store 使用五态 inspect、workspace lock、source/target 双 CAS、bounded strict JSON、nofollow/nonblock/regular-file、dirfd atomic replace、fsync、precommit reread 与 temp inode ownership；幂等早退同样二次复核 target token，invalid target 不自动覆盖。
- 第一轮 correctness/behavior、security/boundary、media/storage/recovery 审查发现历史 provenance 错绑当前 C1 root、candidate/path 自证、previous-tail lineage、reference uniqueness、幂等 target race 与覆盖缺口；修复并补 fully-rehashed forge、单镜 reconcile、artifact missing 和 race 回归后，三个视角最终均无遗留 P0/P1/P2。D1 新链 **19 tests OK**，跨 iter105-114/资产/导出/season/legacy video 聚焦回归 **265 tests OK**。

## Acceptance Result

- **结论**：六项 acceptance 全部通过。本轮最高验收等级为 `mock-functional`；canonical 内的本地 fake-provider 组件为 `local-e2e`，`provider_validated=false`。未运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider/network 请求。
- **A115-01**：通过。三个 D1 strict schema 可 byte-stable round-trip，并拒绝 extra、bool/非有限数、跨 episode/shot、重复 refs、非 canonical artifact path、candidate/frame/request/plan fingerprint 篡改；C1-C3、`DramaEpisode` 与 `RenderPlan` 既有 shape 未改。
- **A115-02**：通过。计划只消费 fresh RenderPlan、fresh C1 与 coverage=`ready` 的 fresh C2；逐镜保持 source order，冻结 target duration、受控视觉输入、exact first、显式 optional tail 和 C1 ordered exact refs，未绑定 provider/model/capability。
- **A115-03**：通过。direct first/tail 与 previous-tail 均重验 exact candidate/artifact；previous-tail 绑定上一镜 candidate/request/artifact/tail revision。缺 first、坏/缺 artifact、断裂 lineage 与 fully-rehashed revision forgery 均在视频行为前 fail closed。
- **A115-04**：通过。selected first/tail、request 与 previous-tail 依赖精确传播；单镜 C1 变化后，C2 reconcile 保留的未变历史 candidate 可继续复用；未选 candidate append 不会使 D1 stale，旧 workspace 明示 `needs_shot_video_plan`。
- **A115-05**：通过。五态 store、workspace lock、source/target CAS、explicit stale replacement、bounded strict JSON、nofollow/nonblock/regular-file、dirfd atomic replace、precommit reread与temp inode ownership均有直接测试；invalid、symlink/FIFO/目录、深层/超限 JSON、partial write、target/temp/source race 与缺 artifact 均安全停止且不覆盖旧计划。
- **A115-06**：通过。D1 新链 **19 tests OK**；iter105-114、资产/RenderPlan/C1-C3、四导出、season export 与 legacy episode-1 video 聚焦回归 **265 tests OK**。correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角在 findings 修复后均无遗留 P0/P1/P2。
- **Canonical acceptance**：只运行一次 `bash scripts/verify.sh`，在 implementation commit `0526bd797e5d8713062aa180930f7b17f0b889ff` 上 exit 0；**2338 tests OK**，15 steps / 188 秒，run `067c3dca6e5a411889235f4e0ffb7dc2`，tree `af76834e9cdf36837d48cb5ce0f5f59958c5c777`，`tracked_scope_clean=true`，`canonical-mock-offline`，mock preflight **0 FATAL / 0 WARN**。
- **审查与未修风险**：历史 candidate provenance 错绑当前 C1 root、candidate/path 自证、previous-tail lineage、reference uniqueness、幂等 target race 与覆盖缺口均已修复。无未处理 P0/P1/P2；保留范围风险是尚无视频 provider capability/attempt/candidate/selection、网络执行、整集 coverage、power-loss 证明与真实质量证据。
- **实现提交**：`0526bd797e5d8713062aa180930f7b17f0b889ff`（`feat(drama): add provider-neutral shot video plans (iter115)`）。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮形成的是短剧阶段 D1 的产品专用 plan/schema/store 契约，已由代码、测试与当轮审计记录承载；未产生新的跨项目 workflow 规则、长期工程铁律或需修改仓库 skill/checker 的经验。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_115_drama_shot_video_plan_frozen_frames.md` | 新建 iter115 固定八段计划与 D1 边界 |
| `docs/iterations/README.md` | 追加 iter115 canonical index |
| `src/drama_schemas.py` | 新增 D1 strict frame/request/episode-plan schema 与 content-address/lineage 自证 |
| `src/drama_shot_video.py`、`src/drama_shot_video_store.py` | 新增 provider-neutral plan 纯函数、精确 affected-shot 分析与五态 strict local store |
| `tests/_drama_shot_video_base.py`、`tests/test_drama_shot_video.py`、`tests/test_drama_shot_video_store.py` | 新增 D1 fixture、领域/存储/竞态/篡改/历史 candidate 复用测试 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | `iter-finish` 按实际 accepted 能力同步 SOP、当前快照与阶段历史 |

## 不在本轮范围

- 真实或 fake network provider backend、provider/model/account/endpoint/capability registry、多参考上传协议、授权、预算、计费、`.env` 与任何真媒体调用。
- video attempt/candidate/selection、submit/poll/download/task id/receipt、paid crash matrix、自动重试、人工对账、视觉连续性评分或 production compose coverage gate。
- Web/API/CLI/runner、批量生成、通用 DAG/worker/lease/provider lane/pricing/Insights，以及修改旧 `drama_video.py`/`drama_video_client.py`/multimodal smoke。
- episode 2+ 旧视频链迁移、逐镜真实视频、TTS/voice、`TimelineManifest`、字幕、BGM/SFX、FFmpeg/compositor、QA、编辑器导出、工作台和归档。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1、C1-C3 identity/schema、现有 Comfy/season export/episode-1 video 消费路径。
- `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪文件。

## Notes

- 用户已明确确认开始实现；实现与聚焦检查均为 mock/local，未触发任何真模型或 provider。
- implementation commit 信息草案：`feat(drama): add provider-neutral shot video plans (iter115)`。
- 立项提交信息草案：`docs(iter115): 迭代计划 115 立项（短剧逐镜视频计划与冻结首尾帧契约）`。
- 实施完成后使用 `iter-finish` 完成聚焦检查、多视角只读审查、最终一次 canonical 验收与 README/handoff/history 收官同步；只 commit，不 push。
