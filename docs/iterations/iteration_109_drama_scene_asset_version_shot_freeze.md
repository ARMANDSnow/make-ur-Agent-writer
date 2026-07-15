# Iteration 109 - 短剧场景资产版本与逐镜冻结引用

## Context

`stage_plan_drama_full_production_pipeline.md` 与当前短剧 SOP 显示：iter106 已建立 strict `RenderPlan` 与 stale 边界，iter107 已闭环角色不可变版本、selected CAS 和单集角色 `AssetRef`，iter108 已闭环 season 级 `ArtDirection` 不可变候选、selected CAS、`RenderPlan` 冻结与 manifest stale 传播；阶段 B 仍缺场景、道具/线索、逐镜 typed 引用与 used-by 血统，阶段 A2 的通用 visual override 也尚未完成。

本轮在“visual override”与“SceneAsset”两个当前候选中选择 SceneAsset 单资产竖切。代码审计确认：现有 `StoryboardShot` 只有自由文本 `visual`，没有可证明的 `scene_id`；现有 `AssetVersion`、`AssetRef`、`AssetArtifact` 和 `EpisodeAssetManifest` 又严格绑定角色 ID、`data/character_refs/` 与 8 人边界，不能靠放宽旧 schema 冒充通用资产。与此同时，`RenderPlan v1` 已提供稳定 `shot_id`、`source_fingerprint` 和 fresh 检查，可让独立场景 manifest 接受显式 `shot_id -> scene_id` 绑定，而不从文本猜场景、不修改创作真源或 RenderPlan shape。

本轮借鉴固定 LocalMiniDrama commit `92c66dd75688d83aac3ccc31bb51378613122cbc` 的 `backend-node/src/services/sceneLibraryService.js` 所体现的场景库抽象；只重写本仓所需的 strict schema、内容寻址、selected CAS、安全持久化和逐镜冻结协议，不复制其代码、prompt 或运行语义。首版只做 workspace 内 season/series 级场景目录和单集显式绑定，不接 Web、provider、图片生成或场景自动抽取。

通用 visual override 虽可复用 `RenderShot.camera_movement/image_prompt/transition_hint`，但当前尚无逐镜媒体消费者；若本轮同时做 override、SceneAsset、Prop/Clue 或 RenderPlan v2，会把多个真源、CAS 和 stale 协议混在一起。按路线图“一轮一个可验收闭环”，本轮只交付“场景候选版本 -> 显式 selected -> 逐镜冻结引用 -> used-by/freshness”。

## Plan

1. 在 `src/drama_schemas.py` 新增与角色契约隔离的 strict `SceneSpec`、`SceneAssetArtifact`、`SceneAssetVersion`、`SceneAsset`、`SceneAssetRef`、`SceneAssetCatalog`、`ShotSceneRef` 与 `EpisodeSceneAssetManifest`。`scene_id` 使用稳定语义 ID（首版 `sNNN`），版本使用内容寻址 `sv_<24hex>`；场景 identity 至少覆盖 bounded display name、地点、时间、天气、空间锚点和视觉 tokens。不得放宽现有角色 `cNNN`、`av_*`、`data/character_refs/`、8 人 manifest 或 `RenderPlan.schema_version=1` 约束。
2. 在 `src/drama_assets.py` 增加场景纯函数：构建 version/catalog、创建场景、追加候选、显式选择、构建单集场景 manifest 与派生 episode-level used-by。初始场景只允许由一个可验证 v1 建立；后续版本 append-only，新候选不自动 selected；相同追加/选择幂等，跨场景 `derived_from`、孤儿链、环、伪造 fingerprint 与 artifact metadata 全部 fail closed。
3. 在 `src/drama_asset_versions.py` 复用现有 bounded duplicate-key/finite/depth JSON、`O_NOFOLLOW | O_NONBLOCK`、regular-file、workspace write lock、target token CAS、parent dirfd 同目录临时文件与 atomic replace，增加场景 catalog 和 episode manifest store。首版路径固定为 `data/assets/season_NN.scene_assets.json` 与 `outputs/episodes/episode_NN.scene_asset_manifest.json`；场景 artifact 只能位于 `data/scene_refs/<scene_id>/`，不能复用或放宽角色 artifact validator。
4. `create_episode_scene_asset_manifest` 只消费 fresh `RenderPlan`、fresh scene catalog 与调用者显式提供的完整 `shot_id -> scene_id` 映射。每个当前 RenderShot 必须且只能绑定一个已存在场景；未知、遗漏、重复 shot/scene、跨 season、伪造 ref 或失效 selected 均阻断。绑定按 `RenderPlan.shots` 顺序确定落盘，重排后凭稳定 `shot_id` 保持语义引用；目标镜头消失、新镜头未绑定或 source 无法证明时显式 stale/blocked，不按 `source_shot_no`、位置、`visual_action`、prompt 或“最新文件”猜测。
5. manifest 只冻结本集实际使用场景的 selected version ref，并从 `ShotSceneRef` 派生 `scene_id -> used_by shot_ids`；不绑定整个 catalog。追加未选候选、修改未被本集使用的场景或角色资产变化不得误 stale；已使用场景的 selected/version/artifact 变化、RenderPlan/ArtDirection 变化或镜头集合变化精确使 scene manifest stale，显式携带 source/target CAS 重建后恢复 fresh。场景变化不得反向修改 `episode_NN.json`、creative fingerprint、RenderPlan、角色 `EpisodeAssetManifest` 或既有 export/video 产物。
6. 不提供物理删除已引用版本的公共路径；catalog 保持 append-only。若本地篡改使已冻结 ref 消失、artifact hash/regular-file 校验失败或 catalog/manifest invalid，inspect 必须保留旧文件并 fail closed，不能静默选择其他候选或覆盖。公共异常只给有界分类，不回显完整 spec/visual tokens、绝对路径、lock holder、provider 信息或签名 URL。
7. 新建 `tests/test_drama_scene_assets.py` 与 `tests/test_drama_scene_asset_store.py`，并按需扩展 `tests/test_drama_asset_versions.py`、`tests/test_drama_render_store.py`。覆盖 strict schema、内容寻址、metadata-only/artifact、append/select 幂等、revision + current selected ID 双 CAS/ABA、显式逐镜绑定、重排/孤儿、used-by、精确 stale、replace、source/target race、symlink/FIFO/目录/越界/超限/deep JSON、异常脱敏与 socket 零网络；聚焦回归 iter105-108、角色 catalog/manifest、RenderPlan、ArtDirection、四导出、season export 与 legacy episode-1 video。
8. 实施阶段先运行聚焦单测、相关 `py_compile`、`.venv/bin/python3 scripts/check_agent_harness.py` 与 `git diff --check`。随后按 `iter-finish` 做 correctness、security/boundary 两路独立只读审查，并增加 schema/freshness 专项视角；修复 findings 并做聚焦回归后，只运行一次最终 `bash scripts/verify.sh`。收官结论最高为 `mock-functional`；本地 fake-provider 证据仍单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片或真视频。

## Acceptance

- **A109-01**：场景 strict schema 对 `sNNN`/`sv_<24hex>`、完整内容 fingerprint、bounded identity/style 字段、版本唯一性、同场景 `derived_from`/无环、artifact 路径/size/hash、extra、duplicate JSON key、NaN/Infinity 与 bool-as-int 全部 fail closed；不修改 DramaEpisode、Storyboard、角色资产 schema、角色 8 人 manifest 或 RenderPlan v1 shape。
- **A109-02**：SceneAsset 版本只追加；初始 v1 可证明 selected，后续新候选不自动 selected；相同候选与相同选择保持 bytes/mtime；selection revision + current selected version ID 双 CAS 覆盖并发和真实 ABA，未知/跨场景/孤儿版本无写入失败。
- **A109-03**：单集场景 manifest 只接受 fresh RenderPlan、fresh catalog 与显式完整的 `shot_id -> scene_id` 映射；每镜恰好一个场景，重排按稳定 `shot_id` 保持引用，目标消失/新增未绑定/伪造 ref 明确 stale 或 blocked；任何路径都不得从自由文本、prompt、shot 位置或目录最新文件猜测场景。
- **A109-04**：manifest 只冻结实际使用场景的 selected refs 并提供确定性 episode-level used-by；未选候选、未使用场景和角色资产变化不误 stale；已使用 selected/version/artifact、RenderPlan/ArtDirection 或镜头集合变化精确 stale，显式重建后恢复 fresh，且 RenderPlan、角色 manifest、创作 episode 与既有导出/视频不被场景选择反向改写。
- **A109-05**：scene catalog/manifest 对 missing/fresh/stale/invalid/blocked_source 状态分类确定；bounded/nofollow/nonblock、regular-file、workspace lock、target/source CAS、dirfd atomic replace 拒绝 symlink、FIFO、目录、越界、超限/深层 JSON 与 precommit race；公共异常脱敏，全链 socket 哨兵证明零网络，invalid/stale 文件不被静默覆盖。
- **A109-06**：聚焦回归覆盖 iter105-108、角色/ArtDirection/RenderPlan/season export/legacy video；correctness、security/boundary、schema/freshness 三视角无未处理 P0/P1，P2 有明确处置。findings 修复后最终只运行一次 `bash scripts/verify.sh`；canonical 结论最高为 `mock-functional`，独立短剧组件仍单列 `local-e2e`、`provider_validated=false`，不运行任何真 provider。

## Implementation Notes

- 用户确认后已进入实现。`drama_schemas.py` 新增与角色资产完全隔离的 SceneAsset schema 家族；`drama_assets.py` 新增内容寻址 version/catalog、append/select 双 CAS、显式逐镜绑定与 used-by 纯函数；`drama_asset_versions.py` 新增 season catalog、episode manifest 的 strict store、artifact bytes 复验、source/target CAS、atomic replace 与 freshness 状态机。
- 场景 manifest 是本轮显式 `shot_id -> scene_id` 绑定的权威本地记录；inspect 可证明其 schema/内部 hash、RenderPlan shot/source、当前 selected ref 与 artifact bytes 一致，但不宣称能对抗可离线重写整份 envelope 并重算全部 SHA-256 的本机攻击者。该边界与当前本地 catalog 的非签名 threat model 一致；若未来要求不可抵赖的绑定历史，应另立迭代引入独立事件账本或签名 provenance，而不是把 SHA-256 冒充签名。
- 审查首轮发现并已修复：幂等 create/append/select 早退前未统一复验 artifact；公共纯函数/store 会回显 Pydantic 输入、artifact 路径或 workspace lock holder；非 Mapping pairs 可被 `dict()` 静默折叠；`create_scene_asset_catalog` 幂等范围过宽；同一路径可被不同 immutable artifact metadata 复用。修复后公共错误改为固定分类且无原始异常链，create 只认首个场景首个 root version，所有幂等入口都先复验 bytes。
- 新增专项证据覆盖 ArtDirection selected 变化经 RenderPlan 精确传播至 scene manifest、missing/invalid/blocked_source、NaN/Infinity/deep JSON、artifact missing/FIFO/目录/超限、parent/target symlink、late target/source CAS、重复 pairs、锁/spec/path 脱敏、artifact path immutable reuse 与 socket 零网络。
- 当前聚焦结果：`tests.test_drama_scene_assets + tests.test_drama_scene_asset_store` 22 tests 通过；iter105-109/角色资产/RenderPlan/ArtDirection/导出/season export/legacy video 共 143 tests 通过；相关 `py_compile`、agent harness（accepted iter108 / active iter109 / 118 index entries）与 `git diff --check` 通过。correctness、security/boundary、schema/freshness 三路最终只读复审均为 P0=0、未解决 P1=0；security 无剩余 P2，schema 的 threat-model 明示与 invalid manifest 保留建议均已落实。最终 canonical `verify.sh` 尚未运行，等待 implementation commit。
- 只读探索曾比较两条候选：逐镜 visual override 的局部 seam 更小，但缺少逐镜媒体消费者；SceneAsset 可复用 iter107 的版本/CAS/manifest 语义并推进路线图首要“可复用视觉资产”缺口，因此选后者。visual override 继续作为独立后续轮，不在本轮顺手实现。
- 场景绑定首版由领域/store API 接收显式映射；没有 typed 创作 source 时宁可 blocked，也不做 LLM/关键词抽取或位置猜测。若未来要把 scene ID 写回创作层或建立 SceneSheet 编辑入口，必须另立迭代和 schema migration。

## Acceptance Result

待实现、审查与 `iter-finish` 回填；当前无测试数、验收等级或 provider 证据。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_109_drama_scene_asset_version_shot_freeze.md` | 新建 iter109 八段式计划，记录 Stage B SceneAsset 单资产竖切、代码落点、边界与验收门槛 |
| `docs/iterations/README.md` | 追加 Iteration 109 canonical 索引 |
| `src/drama_schemas.py` | 新增 strict SceneSpec、immutable SceneAsset version/catalog/ref、逐镜绑定与 episode scene manifest schema |
| `src/drama_assets.py` | 新增场景内容寻址、append/select CAS、显式 shot binding、used-by 纯函数及脱敏公共边界 |
| `src/drama_asset_versions.py` | 新增 scene catalog/manifest strict persistence、artifact 校验、状态机、workspace lock、source/target CAS 与 atomic replace |
| `tests/test_drama_scene_assets.py` | 新增场景纯函数、schema/fingerprint、ABA、异常脱敏测试 |
| `tests/test_drama_scene_asset_store.py` | 新增 store、freshness、ArtDirection 传播、安全边界、race、零网络与 legacy compatibility 测试 |

## 不在本轮范围

- `PropOrClueAsset`、线索状态演化、道具/线索 typed refs、跨 season/global/episode scope resolution、ArtDirection 多 scope/继承。
- 通用 visual override sidecar、camera/lighting/negative prompt/transition CAS、RenderPlan v2 与完整媒体 dependency stale 矩阵。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、现有角色 `AssetRef`/`EpisodeAssetManifest` 或 RenderPlan v1 shape；不把 scene ID 反写创作层，不从文本自动抽取。
- Web/API/CLI、资产比较 UI、scene library 页面、跨集 used-by 扫描缓存、隐藏/停用产品交互与物理删除 API。
- 图片/视频/TTS provider、paid ledger、首尾帧、逐镜图片/视频、TimelineManifest、字幕、BGM/SFX、FFmpeg、ComfyUI、episode 2+ 视频、通用 DAG/worker 或任何真实调用。
- 读取或修改 `.env`、`data/` 私有样本、`outputs/`/`logs/` 用户产物、`小说txt/` 与未跟踪体检报告。

## Notes

- 本轮显式使用 repository-local `iter-start`；用户确认后方可进入实现，实施完成后必须使用 `iter-finish`，先聚焦检查与多视角只读审查，修复 findings 后再做最终一次标准全量验收。
- 立项阶段不 commit、不 push；提交信息草稿：`docs(iter109): 迭代计划 109 立项（短剧场景资产版本与逐镜冻结引用）`。
- 两份未跟踪体检报告属于用户文件，保持不读、不改、不 stage、不 commit。
