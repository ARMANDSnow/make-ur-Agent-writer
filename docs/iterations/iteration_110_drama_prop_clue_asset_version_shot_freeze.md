# Iteration 110 - 短剧道具/线索资产版本与逐镜冻结引用

## Context

`stage_plan_drama_full_production_pipeline.md` 将阶段 B 定义为“角色 + 场景 + 道具/线索 + 美术方向”的可复用视觉资产体系，并要求 immutable version、显式 selected、episode frozen reference、used-by 与 source 变化后的 stale 传播。当前 iter107-109 已分别闭环角色、season `ArtDirection` 与 season `SceneAsset`；实时 SOP 仍明确缺道具/线索，而阶段 C 的逐镜图片又要求人物、场景、道具/线索的 selected refs 共同冻结。

本轮因此选择 `PropOrClueAsset` 单资产竖切，不做通用 visual override。代码审计确认：`src/drama_schemas.py` 的 `SceneAsset` 家族已提供独立 strict schema/ref/逐镜 manifest 骨架；`src/drama_assets.py` 已提供 append-only、selected 双 CAS、稳定 shot 绑定和 used-by 纯函数；`src/drama_asset_versions.py` 已提供严格 store、五态 freshness、source/target CAS 与安全原子替换。但场景是“每镜恰好一个”，道具/线索是“每镜显式零到多个”；角色又受 `cNNN`/`av_*`/单集 8 人约束，不应放宽既有 schema 或急于抽成 `GenericAsset`。

相比之下，visual override 当前只有 `RenderShot.camera_movement/image_prompt/transition_hint` 等局部 seam，`RenderPlan v1` 仍每次从创作快照重建且尚无逐镜图片/视频消费者。此时实现完整 dependency stale 矩阵会虚构尚不存在的下游产物；继续顺延到阶段 C 首个真实消费者立项时再定边界。

本轮借鉴固定 LocalMiniDrama commit `92c66dd75688d83aac3ccc31bb51378613122cbc` 的 prop library 分层与 LumenX commit `743683387384fb1d9fff72038933e7249d416076` 的候选/显式选择产品思路；只 clean-room 重写本仓需要的 strict schema、内容寻址、CAS、逐镜冻结与安全持久化，不复制外部代码、prompt 或运行语义。

## Plan

1. 在 `src/drama_schemas.py` 新增与角色/场景契约隔离的 strict `PropOrClueSpec`、`PropOrClueArtifact`、`PropOrClueAssetVersion`、`PropOrClueAsset`、`PropOrClueAssetRef`、`PropOrClueAssetCatalog`、`ShotPropOrClueRefs` 和 `EpisodePropOrClueAssetManifest`。道具与线索共用 schema，以 immutable `kind=prop|clue` 区分；稳定语义 ID 使用 `pNNN|lNNN`，版本 ID 使用内容寻址 `pcv_<24hex>`，kind 与 ID prefix 必须一致。Spec 首版包含 bounded `display_name`、可选 `owner_character_id`、`state_label`、可选 `first_seen_episode_no` 与 `visual_tokens`；不把未验证的事件来源冒充 provenance。不修改 `DramaEpisode`、Storyboard、角色/场景 schema 或 `RenderPlan.schema_version=1` shape。
2. 首版 catalog 仅为 workspace 内 season/series 级，允许显式空 catalog，以保持“本集无道具/线索”的 graceful degrade。每个语义资产最多 256 个 append-only versions；artifact 可为空，存在时只允许 POSIX 相对路径 `data/prop_clue_refs/<pNNN|lNNN>/...`，并绑定 regular-file/size/SHA。新资产的首个 root version 显式 selected；后续候选只追加、不自动选中，不提供物理删除已引用版本的公共路径。
3. 在 `src/drama_assets.py` 增加道具/线索纯函数：创建空 catalog、构建内容寻址 version、新增语义资产、追加候选、显式选择、构建单集 manifest 和派生 used-by。add/append 使用 catalog fingerprint CAS；select 同时核对 `selection_revision` 与当前 `selected_version_id`，覆盖并发与真 ABA；相同请求幂等且保持 bytes/mtime。`derived_from` 只能指向同一资产的已有版本，kind 不可在版本链中漂移，状态变化以新版本表达而不原地改写。
4. 单集 manifest 只接受 fresh `RenderPlan`、fresh prop/clue catalog 与调用者显式提供的完整 `shot_id -> ordered list[asset_id]` 映射。每个当前 RenderShot 必须恰好出现一次；单镜列表允许空，非空时最多 16 项、不得重复，顺序视为调用者明确的引用优先级。未知资产、遗漏/重复 shot、跨 season、kind-ID 不一致、失效 selected、伪造 ref 或越界应 fail closed；不得从 `visual_action`、prompt、shot 位置、文件名或目录最新项推断绑定。
5. manifest 按 `RenderPlan.shots` 顺序落盘，只冻结本集实际引用资产的当前 selected refs，并派生 `asset_id -> ordered shot_ids` 的 episode-level used-by；全部镜头显式空列表时 manifest 仍合法，used-by 为空。追加未选候选、新增/切换未使用资产或变更角色/场景 manifest 不得误 stale；已使用 selected/version/artifact bytes、RenderPlan/ArtDirection、shot source/集合或显式映射变化须精确 stale。只有映射变化才递增 `binding_revision`；按原映射吸收 selected 变化时不递增绑定 revision。
6. 在 `src/drama_asset_versions.py` 增加独立 prop/clue store，路径固定为 `data/assets/season_NN.prop_clue_assets.json` 与 `outputs/episodes/episode_NN.prop_clue_asset_manifest.json`。catalog 使用 `needs_prop_clue_catalog | fresh | invalid`；episode manifest 使用 `needs_prop_clue_manifest | fresh | stale | invalid | blocked_source`。inspect 重读当前 RenderPlan/catalog，只复验实际引用的 artifact 并重算 expected manifest；replace 必须显式 `replace_stale=True + expected_manifest_fingerprint`，invalid 文件保留且不得静默覆盖。
7. store 复用已有 bounded duplicate-key/finite/depth JSON、`O_NOFOLLOW | O_NONBLOCK`、regular-file、workspace write lock、target token、source fingerprint/CAS、parent-dirfd 同目录临时文件与 atomic replace。create/add/append/select 的幂等早退前仍须复验 artifact bytes；precommit 重读 source 和 target，拒绝竞态替换。公共异常只返回有界分类，不回显 spec/visual tokens、绝对路径、lock holder、prompt、provider 或签名 URL。
8. 新建 `tests/test_drama_prop_clue_assets.py` 与 `tests/test_drama_prop_clue_asset_store.py`。覆盖空 catalog/全空绑定、strict schema、ID-kind/path、内容寻址、metadata-only/artifact、add/append/select 幂等、双 CAS/ABA、0..16 完整绑定、重排/镜头增删、used-by、五态 freshness、精确 stale/rebuild、replacement/source-target race、symlink/FIFO/目录/越界/超限/deep JSON/duplicate key/NaN/Infinity、公共异常脱敏与 socket 零网络。聚焦回归覆盖 iter105-109、角色/ArtDirection/RenderPlan/SceneAsset、四导出、season export 与 legacy episode-1 video。
9. 实施阶段先跑新增/受影响的聚焦单测、相关 `py_compile`、agent harness 与 `git diff --check`。收官按 `iter-finish` 执行 correctness、security/boundary、schema/freshness 三个独立只读视角，修复 findings 并做聚焦回归后，只运行一次最终 `bash scripts/verify.sh`。最高默认验收结论为 `mock-functional`；不运行真文本、真生图或真视频。

## Acceptance

- **A110-01**：strict schema 对 `pNNN|lNNN`、kind-prefix、`pcv_<24hex>`、完整 fingerprint、bounded spec、版本唯一性、同资产 `derived_from`/无环、artifact path/size/hash、extra、duplicate JSON key、NaN/Infinity 与 bool-as-int 全部 fail closed；不修改既有创作、角色、场景或 RenderPlan v1 schema。
- **A110-02**：catalog 可显式为空；新增资产建立可证明的初始 selected，后续版本只追加且不自动切换；add/append/select 幂等，selection revision + current selected ID 双 CAS 覆盖并发与 ABA，跨资产、kind 漂移、孤儿/环形版本冲突均应失败且不得写入。
- **A110-03**：episode manifest 只接受 fresh RenderPlan、fresh catalog 与完整显式 `shot_id -> 0..16 ordered asset_ids`；空列表合法，遗漏/未知/重复/越界/伪造绑定阻断，重排后按稳定 shot ID 保持语义引用；不得从自由文本、prompt、位置或文件名推断。
- **A110-04**：manifest 只冻结实际使用 refs 并确定性派生 used-by；全空绑定合法。未选候选、未使用资产及角色/场景 manifest 变化不误 stale；已使用 selected/version/artifact、RenderPlan/ArtDirection、shot source/集合或映射变化精确 stale，显式 CAS 重建恢复 fresh，且不反写 episode、RenderPlan、角色/场景 manifest 或既有导出/视频。
- **A110-05**：catalog 三态和 episode manifest 五态分类确定；bounded/nofollow/nonblock、regular-file、workspace lock、source/target CAS、dirfd atomic replace 拒绝 symlink、FIFO、目录、越界、超限/深层 JSON 与 precommit race。invalid/stale 文件不被静默覆盖，公共异常脱敏，socket 哨兵证明零网络。
- **A110-06**：聚焦回归覆盖 iter105-109 与既有短剧导出/video 兼容链；correctness、security/boundary、schema/freshness 无未处理 P0/P1，P2 有明确处置；修复 findings 后只运行一次 canonical `bash scripts/verify.sh`，验收等级为 `mock-functional`，`provider_validated=false`，不运行任何真模型/真媒体入口。

## Implementation Notes

- 用户确认后按计划选择“短剧道具/线索资产版本与逐镜冻结引用”竖切；未引入通用 visual override，也未修改 `DramaEpisode`、Storyboard、角色/场景 schema 或 `RenderPlan v1` shape。
- `src/drama_schemas.py` 新增独立的 prop/clue strict schema 家族。`pNNN|lNNN` 与 `kind` 双向绑定，`pcv_<24hex>` 由 immutable content 计算；catalog 与逐镜 `asset_refs` 均要求调用方显式传入，空值用 `[]` 表达，避免“字段漏传”和“明确为空”被混为一谈。
- `src/drama_assets.py` 新增空 catalog、version build、add/append/select、selected ref、episode manifest 与 used-by 纯函数。逐镜映射先按当前 shot 数量做有界检查，再读取条目；每个 shot 显式给出 `0..16` 个有序且不重复的资产 ID。重复 add 即使发生在 append/select 之后仍识别为初始 root 的幂等重放，不回退当前 catalog。
- `src/drama_asset_versions.py` 新增 season catalog 与 episode manifest store，复用现有 duplicate-key/finite/depth JSON、nofollow/nonblock/regular-file、workspace lock、source/target CAS、parent-dirfd 临时文件和 atomic replace。manifest 持久化先构建有界 probe，再从其规范化结果执行 artifact 复验与 precommit，避免在拒绝超限输入前无界复制调用方 mapping。
- 新增 18 个 iter110 测试，并纳入 iter105-109、ArtDirection、RenderPlan、SceneAsset、短剧导出、season export 与 episode-1 video 的 161 个聚焦回归。覆盖显式空值、内容寻址、版本链/环、artifact path ownership、双 CAS/ABA、完整 `0..16` 绑定、精确 stale、invalid 保留、特殊文件、超限/deep/non-finite JSON、source/target race、异常脱敏与 socket 零网络。
- correctness 只读审查无 P0/P1，P2 为演进后重复 root add 的幂等语义；已修复并补回归。security/boundary 审查无 P0/P1，P2 为超限 mapping 在边界检查前可能被复制、特殊文件与竞态矩阵覆盖不足；已改为有界 probe 并补测试。schema/freshness 审查发现 1 个 P1（`assets`/`asset_refs` 默认空会掩盖漏字段）与 1 个 P2（环、同路径异 metadata、invalid/special-file/race 等代表性覆盖不足）；已将两字段改为必填并补齐相应测试。修复后无未处理 P0/P1/P2，范围未扩大。
- `docs/product/short_drama_module.md` 属于 harness 的 implementation scope，不能作为 accepted commit 之后的 closure drift；因此先在 `7fd98f9` 同步产品 SOP，再把完整收官状态固化为 `8f8d659` 并以该 HEAD 作为最终验收实体。验收后只回填本条证据和 handoff，不再修改实现或产品协议。

## Acceptance Result

- **A110-01：通过。** 独立 strict schema 已约束 `pNNN|lNNN`/kind、`pcv_<24hex>`、content/catalog/manifest fingerprints、bounded spec、append-only 同资产版本链、无环、artifact ownership/size/SHA、extra、bool-as-int 与有限 JSON；`assets`/`asset_refs` 必填且允许显式 `[]`。既有创作、角色、场景和 RenderPlan v1 schema 未改变。
- **A110-02：通过。** 空 catalog、新资产 root selected、候选 append 不自动切换、add/append/select 幂等及 selection revision + current selected ID 双 CAS/ABA 均有回归；跨资产 derivation、kind 漂移、孤儿/环和同 artifact path 异 metadata 均 fail closed。演进后的重复 root add 保留当前 catalog，不回退版本或选择。
- **A110-03：通过。** manifest 只接受 fresh RenderPlan/catalog 与完整显式 `shot_id -> 0..16 ordered asset_ids`；所有当前 shot 都必须出现，`[]` 合法，tuple/遗漏/未知/重复/超限被拒，且在读取条目前先按当前 shot 数量做有界检查。实现不读取自由文本、prompt、位置或目录最新项推断绑定。
- **A110-04：通过。** manifest 只冻结实际使用 selected refs并确定性派生 episode used-by；全空绑定合法。未选候选/未使用资产不 stale，已使用 selection/version/artifact、RenderPlan/ArtDirection 与显式 mapping 变化精确 stale；原 mapping 吸收 selection 变化不增加 `binding_revision`，显式 CAS replace 恢复 fresh，未反写任何上游创作或既有消费端。
- **A110-05：通过。** catalog 三态、manifest 五态与 invalid 保留已覆盖；bounded duplicate-key/finite/depth JSON、nofollow/nonblock/regular-file、workspace lock、source/target CAS、parent-dirfd atomic replace 拒绝 symlink/FIFO/目录/超限及 precommit race。公共错误有界脱敏，socket 哨兵证明 iter110 路径零网络。
- **A110-06：通过。** 新增 18 个 iter110 测试；受影响链 161 个聚焦测试通过，覆盖 iter105-109、RenderPlan、角色/ArtDirection/SceneAsset、导出、season export 与 episode-1 video。correctness、security/boundary、schema/freshness 三个只读视角的 1 个 P1、3 个 P2 已全部修复并回归，最终无未处理 P0/P1/P2。
- **最终全量验收：通过。** accepted HEAD `8f8d6592ecb2640092ebad658c84d8b3258bcdce` / tree `37d101ec39020d9906e164d3da39209bcb7e6907`（核心实现 commit `4bd4c44`）上 canonical `bash scripts/verify.sh`：**2215 tests OK**，15 steps，141 秒，run `f57770902c544b49a5a1c20876f042af`，`tracked_scope_clean=true`，mock pipeline、local fake-provider E2E 与 preflight（0 FATAL / 0 WARN）通过。首次受限沙箱尝试仅因禁止 loopback bind 和注入 `xcrun_db` 临时项失败；产品 SOP 纳入 implementation scope 后，最终完整 HEAD 在沙箱外重验通过，环境/收官分类错误不计为代码 finding。
- **验收等级：`mock-functional`。** local fake-provider 子步骤为 `local-e2e`，`provider_validated=false`；未运行真文本、真生图、真视频或真 ComfyUI。已知残余边界只有本轮明确排除的通用 visual override、Web/跨集 used-by、ArtDirection 多 scope 与后续 C-J 媒体链，以及普通 SHA-256 不提供离线改写认证、非合作本机写者不受 workspace flock 完全约束。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增道具/线索 strict schema、immutable version/ref、catalog 与逐镜 manifest |
| `src/drama_assets.py` | 新增版本构建、catalog add/append/select、逐镜冻结与 used-by 纯函数 |
| `src/drama_asset_versions.py` | 新增 prop/clue catalog/manifest 的严格持久化、inspect/load、CAS 与安全写入 |
| `tests/test_drama_prop_clue_assets.py` | 新增 schema、fingerprint、版本、双 CAS、显式绑定与脱敏测试 |
| `tests/test_drama_prop_clue_asset_store.py` | 新增 store 五态、精确 stale、竞态/路径/特殊文件/零网络测试 |
| `README.md` / `docs/product/short_drama_module.md` / `docs/AGENT_HANDOFF.md` / `docs/PROJECT_HISTORY.md` | 就地同步 iter110 实时 SOP、当前快照、Latest Transition、阶段历史与长期教训 |

## 不在本轮范围

- 通用 visual override sidecar/CAS、RenderPlan v2、BGM/首尾帧/逐镜媒体/Timeline/composite 的完整 dependency stale 矩阵。
- 将 prop/clue ID 反写 `DramaEpisode`/Storyboard、从镜头文本/prompt 自动抽取资产或从位置/最新文件猜测绑定。
- 线索事件图、因果/前置/结果、`source_event_ids` 真实性验证、状态演化操作与跨 episode 时间线。
- global/series/episode 多 scope 继承/动态 resolution、ArtDirection 多 scope、场景 Web/跨集 used-by。
- Web/API/CLI、资产候选比较 UI、跨集 used-by 缓存、隐藏/停用/删除产品交互。
- 逐镜图片/视频、首尾帧、provider、paid ledger、TimelineManifest、TTS/BGM/SFX、FFmpeg、ComfyUI 与任何真实调用。
- `.env`、私有 `data/outputs/logs`、`小说txt/` 与用户未跟踪文件。

## Notes

- 本轮立项只写 iteration 文档与 canonical index；用户确认后才开始业务实现，不 commit、不 push。
- `docs/product/short_drama_module.md` 的实时表述仍停在 iter108 且把 SceneAsset 列为未完成；当前事实以 README/handoff/iter109 为准，实施收官时必须就地修正，不让旧表述改变本轮范围。
- 此轮最紧邻的实现骨架是 `src/drama_schemas.py` 的 SceneAsset 段、`src/drama_assets.py` 的 scene version/catalog/select/manifest/used-by 纯函数，以及 `src/drama_asset_versions.py` 的 scene catalog/manifest store。
- 实施完成后使用 `iter-finish`；实现 commit 上验收，随后只允许 docs-only 收官提交。
- 提交信息草案：`docs(iter110): 迭代计划 110 立项（短剧道具线索资产版本与逐镜冻结引用）`。
