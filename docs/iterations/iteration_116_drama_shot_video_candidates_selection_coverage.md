# Iteration 116 - 短剧逐镜视频候选选择与整集覆盖门禁

## Context

iter115 已完成阶段 D1：从 fresh RenderPlan、C1 与 coverage ready 的 C2 确定性生成 provider-neutral `EpisodeShotVideoPlan`，冻结逐镜目标时长、exact first/optional tail、ordered references 与 previous-tail lineage，并以五态 strict local store 管理 freshness；当前 canonical 基线为 2338 tests OK，`provider_validated=false`。但 D1 只回答“每镜视频应使用什么输入”，尚无不可变视频候选、显式 selected、精确 stale/reconcile 或整集 production coverage，旧 `src/drama_video.py` 仍只是 episode 1 高光视频兼容入口。

根据 README、`short_drama_module` 与独立 A-J 阶段计划，本轮交付阶段 D2 的纯本地窄闭环：消费 fresh D1 plan，建立 content-addressed strict MP4 候选、guarded selection、逐镜 freshness 与整集 coverage gate，为后续 D3 的 provider capability、异步 submit/poll/download 和付费 crash recovery 提供稳定落点。立项阶段只创建本 iteration 与索引，不改业务代码；本轮实施也不连接 fake/真实网络 provider，不运行任何真视频。

## Plan

### Implementation Context
- `must_read`: `README.md`, `docs/iterations/README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_113_drama_shot_image_candidates_first_tail_binding.md`, `docs/iterations/iteration_115_drama_shot_video_plan_frozen_frames.md`, `src/drama_schemas.py`, `src/drama_shot_image_candidates.py`, `src/drama_shot_image_candidate_store.py`, `src/drama_shot_video.py`, `src/drama_shot_video_store.py`, `src/drama_video.py`, `tests/_drama_shot_video_base.py`, `tests/test_drama_shot_video.py`, `tests/test_drama_shot_video_store.py`, `tests/test_drama_video.py`
- `expected_changes`: `docs/iterations/iteration_116_drama_shot_video_candidates_selection_coverage.md`, `docs/iterations/README.md`, `src/drama_schemas.py`, `src/drama_shot_video_candidates.py`, `src/drama_shot_video_candidate_store.py`, `tests/_drama_shot_video_candidate_base.py`, `tests/test_drama_shot_video_candidates.py`, `tests/test_drama_shot_video_candidate_store.py`, `README.md`, `docs/product/short_drama_module.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪体检报告；`src/drama_video.py` 只读核对既有 MP4/episode-1 兼容边界，不改旧 job/client/smoke；不接 fake/真实网络 provider，不改 Web/jobs/routes、CLI/runner、paid recovery、D1、C1-C3、`DramaEpisode`、`RenderPlan`、现有导出或任何授权/计费入口；canonical verify 自管 acceptance 产物除外

1. 在 `src/drama_schemas.py` 增加 strict D2 schema：受限本地 MP4 artifact、content-addressed `ShotVideoCandidate`、逐镜 append-only 候选池、显式 selected binding/revision、episode manifest 与 coverage projection。candidate 必须绑定 season/episode/stable shot、D1 plan/spec fingerprint 与实际 artifact SHA/size/duration/dimensions；extra、bool 冒充数值、非有限数、重复/未知 ID、跨集跨镜引用和 fingerprint 篡改均 fail closed，不改变 D1 既有 shape。
2. 新建 `src/drama_shot_video_candidates.py` 作为纯函数领域层：从 fresh D1 plan 初始化 manifest；显式追加 exact candidate；按 candidate ID、expected manifest fingerprint、expected selection revision 与 expected current binding 做 guarded selection；append 与 select 分层，新候选不得自动替换已选视频。为 lost-response 幂等重放提供绑定完整 transition identity 的受控 receipt，陈旧 writer 不得借“desired 相同”越过 CAS。
3. D2 只接收受限本地 MP4 字节并执行 bounded container/video-track、duration、width/height、SHA 与 canonical path 校验；candidate source 明示为 local artifact，不伪造 provider、task、receipt、费用或真实质量证据。音轨存在与否只作为受控 metadata，不改变阶段 E 的声音真源；placeholder 不得计入 production-ready coverage。
4. 新建 `src/drama_shot_video_candidate_store.py`，独立落盘 `episode_NN.shot_video_assets.json` 与 episode-scoped artifact，提供 `needs_shot_video_assets | fresh | stale | invalid | blocked_source` inspect/load/create/reconcile/append/select/repair。store 只消费 `load_fresh_episode_shot_video_plan` 公开 seam，并在 workspace lock 内实施 source/target/selection CAS、bounded strict JSON/MP4、nofollow/nonblock/regular-file、dirfd create-only/atomic replace、artifact precommit reread、fsync 与 temp/final inode ownership；invalid 或损坏目标不得被自动覆盖。
5. D1 plan/spec 漂移按 stable shot 精确传播：未受影响镜头保留候选历史与 selection，受影响旧 candidate 继续可审计但不计 fresh coverage；新候选 append、未选 candidate、无关镜头和 candidate metadata 顺序不得误 stale。coverage 必须穷尽列出 selected-fresh、missing-selection、stale-source、invalid/missing-artifact 与 blocked-source；只有所有 required shots 都有 exact selected fresh 非 placeholder 视频时才返回 production compose ready，并稳定列出 blocker shot IDs。
6. 新增 synthetic MP4 fixture、纯函数与 store 聚焦测试，覆盖 schema/content address、append 不自选、selection CAS/receipt、episode 2+、精确 reconcile/stale/coverage、MP4 container/track/duration/dimensions、JSON/path/symlink/FIFO/目录/race/锁/partial-write/temp ownership/repair/脱敏和 socket sentinel 零网络；回归 iter105-115、A-B/C1-C3/D1、四导出、season export 与 legacy episode-1 video。完成聚焦检查和三视角只读审查、修复 findings 后形成 implementation commit，最后只运行一次 canonical `bash scripts/verify.sh`，再用 `iter-finish` 收官。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 D1 plan/spec 到 D2 candidate/selection 的身份闭包、append 不自选、guarded selection/lost-response receipt、精确 affected-shot reconcile、整集 coverage gate、episode 2+ 路径及 legacy episode-1 video 向后兼容
- `security_boundary`: 核对 manifest JSON 与 MP4 artifact 的 workspace confinement、bounded strict read、nofollow/nonblock/regular-file、container/video-track/SHA/size/duration/dimensions、锁/CAS/TOCTOU/temp ownership、错误脱敏和全链零网络
- `extra_risk_view`: `media/storage/recovery`，核对坏/缺/placeholder MP4、partial write、重启重读、append/select 幂等重放、D1 source race/ABA、artifact repair 与 coverage blocker 均安全停止且不把旧视频认作 production ready

- **A116-01**：strict D2 schema 可 byte-stable round-trip；candidate ID/fingerprint 由 season/episode/shot、D1 plan/spec 与 artifact identity/受控媒体 metadata 确定，拒绝 extra、bool/非有限数、重复/未知 ID、跨 episode/shot、非 canonical path 与 fingerprint 篡改；不修改 `DramaEpisode`、`RenderPlan`、C1-C3 或 D1 既有 shape。
- **A116-02**：candidate 只可追加到对应 fresh D1 shot，幂等重放仍重验 artifact；append 不自动选择。selection 必须显式携带 candidate ID、expected manifest fingerprint、expected revision/current binding 与 exact transition receipt；陈旧、悬空、跨镜或 source/spec 不匹配的 candidate 均 fail closed。
- **A116-03**：受限本地 MP4 必须通过 bounded container/video-track、SHA/size、duration 与 dimensions 校验并与 candidate 自证一致；坏/超限/无视频轨/伪扩展/metadata 不符与 placeholder 不得进入 production-ready coverage。D2 不记录或宣称 provider/task/费用/真实质量，音轨 metadata 不取代阶段 E。
- **A116-04**：D1 变化只影响真实依赖 shot；reconcile 在 source/target 双 CAS 下保留未受影响历史与 selection，漂移旧事实不计 fresh coverage。coverage 穷尽并稳定分类 selected-fresh、missing、stale、invalid/missing artifact 与 blocked source；任一 required shot 非 fresh 时 production compose blocked 并列出 stable shot IDs。
- **A116-05**：store 五态、workspace lock、source/target/selection CAS、bounded strict JSON/MP4、nofollow/nonblock/regular-file、dirfd create-only/atomic replace、precommit reread、fsync 与 temp/final inode ownership拒绝 symlink、FIFO、目录、越界、深层/超限/重复键 JSON、partial write、target/temp/source race 与 ABA；invalid/损坏文件不被覆盖，exact repair 可审计，公开错误脱敏，socket sentinel 证明全链零网络。
- **A116-06**：新增链与 iter105-115、资产/RenderPlan/C1-C3/D1、四导出、season export、paid recovery 和 legacy episode-1 video 聚焦回归通过；correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高验收等级为 `mock-functional`，fake-provider 组件仍单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。

## Implementation Notes

- 立项阶段根据 iter115 的明确顺延项与 A-J 阶段 D 的 2-3 轮拆分，将 D2 限定为 candidate/selection/coverage 的纯本地事实层；provider capability、异步 attempt、submit/poll/download 和 paid crash recovery 顺延到后续 D3。
- 领域层沿用 C2 已验证的“不可变 candidate / 可变 selected / guarded revision”分层，但 identity 改为绑定 D1 `plan_fingerprint + spec_fingerprint + MP4 artifact metadata`。append 不自选，lost-response 只允许 exact transition fingerprint 重放。
- store 不导入或改写旧 `drama_video.py` job；为避免新纯本地路径初始化旧 job/LLM 依赖，在 D2 store 内实现独立的 bounded ISO-BMFF probe，只接受 100 MiB 内 MP4，限制单层与全文件 box/sample 数，要求唯一 `ftyp/moov`、受支持 video sample entry，并以 `stsd/stsz/stts/stsc/stco|co64` 证明每个样本完整落在 `mdat`；duration 取 video track 时基，audio-track presence 仍只作 metadata。
- manifest freshness 与 production coverage 分层：缺 selection 或显式 placeholder 不破坏 manifest freshness，但 coverage 分别为 `incomplete` / `invalid`；只有每个 required shot 的 exact selected candidate 与当前 D1 spec 一致且 artifact 完整、非 placeholder 时才 `ready`。
- reconcile 保留历史 candidate 与 selection，只有 request 漂移的 shot 排除在 fresh coverage 外；删除的 shot pool 移入 `retired_shots` 审计池，重新出现时可恢复，未受影响镜头保持字节级候选/选择事实。旧 artifact 缺失或损坏不靠重建 manifest 掩盖，只允许 exact referenced bytes 的 create-only repair。
- store 复用项目 workspace lock、strict JSON reader 与 workspace root 守门，并补 source/target/selection CAS、nofollow/nonblock/regular-file、dirfd create-only artifact、atomic manifest replace、fsync、precommit source/artifact reread 与 temp/final inode ownership。普通 inspection 只重验 active selected artifact，按 manifest 的 256 candidate / 4 GiB declared history / 512 MiB selected inspection 总预算约束资源，并以 artifact declared size 作 strict read 上限；写操作在锁内做最多 2048 项的 canonical temp/orphan crash-residue 清扫。
- correctness/behavior、security/boundary、media/storage/recovery 三个只读视角均无 P0；共同指出的 header-only/坏 offset MP4、真实 store blocker coverage 缺失、删镜历史丢失，以及资源扫描/进程退出残留问题，分别用 sample reachability probe、逐镜 invalid/blocked projection、retired audit pool、manifest/scan budget 与受限 recovery 修复。补充 episode 2 完整 create → append → select → ready、selected/unselected artifact、坏 `stco` 与 recovery 证据后，D2 新链 **22 tests OK**；资产、C1-C3、D1、paid vocabulary、导出、season export 与 legacy episode-1 video 聚焦回归 **262 tests OK**；最终 canonical 结果见 Acceptance Result。

## Acceptance Result

- **A116-01 — 通过**：新增 strict `ShotVideoArtifact / Candidate / Selection / CandidatePool / EpisodeManifest / CoverageReport`，candidate identity 绑定 season/episode/shot、D1 plan/spec 与 MP4 identity；canonical path、bool/extra/重复/跨集/重哈希篡改均有测试。未修改 `DramaEpisode`、RenderPlan、C1-C3 或 D1 shape。
- **A116-02 — 通过**：append 与 select 分层，新 candidate 不自选；selection 使用 expected manifest fingerprint、revision/current binding 与 exact transition receipt，lost-response 仅允许原 transition 重放。store 在写锁内重读 source/target/selected artifact。
- **A116-03 — 通过**：MP4 probe 有 100 MiB 单文件、单层/全文件 box、sample 数限制，并校验唯一 `ftyp/moov`、supported sample entry、track duration、dimensions 与 `stsd/stsz/stts/stsc/stco|co64 → mdat` 样本可达性；坏 offset、box bomb、伪扩展、missing/placeholder 均不能 production ready。
- **A116-04 — 通过**：D1 plan/spec 漂移按 stable shot 精确传播，删除镜头移入 `retired_shots` 审计池；coverage 稳定穷尽 selected fresh、missing、stale、invalid/missing artifact、placeholder、blocked source，episode 2 完整 create → append → select → ready 已验证。
- **A116-05 — 通过**：五态 store、strict JSON/MP4、workspace lock、source/target/selection CAS、nofollow/nonblock/regular-file、dirfd create-only/atomic replace、fsync、precommit reread、exact repair、短写/temp ownership 与最多 2048 项的 canonical crash-residue recovery 通过。manifest 额外限制 256 candidates、4 GiB declared history 与 512 MiB selected scan；普通 inspect 只读取 active selected 且以 declared size 为上限。socket sentinel 证明 D2 全链零网络。
- **A116-06 — 通过**：D2 新链 **22 tests OK**；资产、C1-C3、D1、paid vocabulary、导出、season export 与 legacy episode-1 video 聚焦回归 **262 tests OK**。correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角均无 P0；发现的 MP4 可达性、真实 store blocker coverage、删镜审计历史、资源扫描与 crash residue P1/P2 均已修复，最终无遗留 P0/P1/P2。
- implementation commit：`df58cc37e7381b1e870594a448c34db147c029d1`（`feat(drama): add shot video candidates and coverage (iter116)`）。
- canonical acceptance：最终获准的非沙箱 `bash scripts/verify.sh` exit 0，**2360 tests OK**，15 steps / 196 秒，run `3dec3ffb95ed4f1eb1bc4b22022d1a47`，tree `8211cc49eb0c12416dd3dce706d4b94b65b7a135`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN。首次沙箱执行的 14 个错误全部来自环境禁止 loopback bind；未改代码，同一 implementation commit 按执行环境规则重验通过。
- 验收等级：总级别 `mock-functional`；canonical 中既有 fake-provider 子步骤为 `local-e2e`；`mock_offline=true`、`provider_validated=false`。未运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider。
- 未修风险：D2 只证明受控本地 writer/process-level persistence 与结构化 MP4 样本可达性，不证明完整 codec decode/主观质量、power-loss、敌对本机进程、视频 provider exactly-once 或真实逐镜视频；这些继续属于 D3/J 与既定范围外边界。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮 finding 均是 D2 产品协议与本地 MP4/store 实现细节，已由 schema、测试和 iteration 审计固定；没有新增跨项目通用规则需要提升到长期权威文档。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_116_drama_shot_video_candidates_selection_coverage.md` | 新建 iter116 固定八段计划与 D2 边界 |
| `docs/iterations/README.md` | 追加 iter116 canonical index |
| `src/drama_schemas.py` | 新增 D2 strict MP4 artifact/candidate/selection/pool/manifest/coverage schema |
| `src/drama_shot_video_candidates.py` | 新增纯本地 candidate append、guarded selection、reconcile、affected-shot 与 coverage 领域逻辑 |
| `src/drama_shot_video_candidate_store.py` | 新增 bounded MP4 probe、五态 strict store、artifact create-only/repair、CAS 与原子持久化 |
| `tests/_drama_shot_video_candidate_base.py` | 新增基于 D1/C2 的 synthetic MP4 candidate fixture |
| `tests/test_drama_shot_video_candidates.py` | 新增 content address、selection receipt、stale/reconcile/coverage 与 schema 测试 |
| `tests/test_drama_shot_video_candidate_store.py` | 新增 MP4、路径/特殊文件、锁/CAS/race/repair/短写/零网络 store 测试 |
| `README.md` | 同步 iter116 里程碑、实时 SOP 与 D1-D2 精确边界 |
| `docs/AGENT_HANDOFF.md` | 就地更新当前快照、能力/缺口、验收证据与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | 追加 iter116 阶段里程碑与实现索引 |

实施与收官时按实际 diff 补充业务代码、测试、README、产品 SOP、handoff 与 history；不得用预计变更冒充已完成事实。

## 不在本轮范围

- 视频 provider capability、attempt/ledger、fake/真实 network adapter、submit/poll/download/task id/provider receipt、付费 crash matrix、自动重试、人工对账、授权、预算、计费与 `.env`。
- Web/API/CLI/runner、批量生成/轮询/取消、候选播放/比较 UI、视觉相似度或模型连续性评分、通用 DAG/worker/lease/provider lane/pricing/Insights。
- 修改旧 `src/drama_video.py`、`src/drama_video_client.py`、multimodal smoke 或 episode-1 高光路径；episode 2+ 旧视频链迁移与任何真实逐镜视频生成。
- TTS/voice、音频生成、`TimelineManifest`、字幕、BGM/SFX、FFmpeg/compositor、媒体 QA、编辑器导出、生产工作台、归档与 provider capstone。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1、C1-C3 identity/schema、D1 plan/spec identity、现有 Comfy/season export 消费路径。
- JPEG/WebP 图片扩展、更多视频 container/codec、power-loss/内核崩溃/敌对本机进程证明；本轮 durability 结论最多限定于受控本地 writer 与 process-level persistence。
- `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪文件。

## Notes

- 立项提交信息草案：`docs(iter116): 迭代计划 116 立项（短剧逐镜视频候选选择与整集覆盖门禁）`。
- 实施提交信息草案：`feat(drama): add shot video candidates and coverage (iter116)`。
- 实施完成后必须使用 `iter-finish`，按聚焦检查 → 三视角只读审查 → findings 修复/聚焦回归 → implementation commit → 最终一次 `bash scripts/verify.sh` → README/SOP/handoff/history 收官的顺序执行；只 commit，不 push。
