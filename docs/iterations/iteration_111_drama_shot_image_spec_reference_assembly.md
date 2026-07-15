# Iteration 111 - 短剧逐镜图片规格与冻结引用装配

## Context

`stage_plan_drama_full_production_pipeline.md` 将媒体段依赖定义为 `A → B → C → D`，其中阶段 C 的第一步是从美术方向、场景、角色、道具/线索 selected versions 与镜头视觉字段构建确定性的逐镜 image request spec，并在 reference 超出 provider 能力时按固定优先级裁剪和显式告警。当前 iter106 已建立 strict `RenderPlan`，iter107-110 已分别闭环角色、season `ArtDirection`、场景、道具/线索的不可变版本、selected CAS 与 episode 冻结 manifest；实时 SOP 仍把逐镜图片、首尾帧和候选选择列为未实现。

本轮选择阶段 C 的第一个纯本地闭环：`fresh RenderPlan + fresh episode asset manifests + 显式 shot→character bindings + bounded reference policy → byte-stable EpisodeShotImagePlan`。现有 `StoryboardShot` / `RenderShot` 没有可证明的逐镜角色 ID，因此必须由调用方提交覆盖全部当前镜头的 `shot_id -> ordered character_ids`，不得从 `visual_action`、`image_prompt`、shot 位置或目录最新文件猜测。SceneAsset 与 PropOrClueAsset 已有逐镜 typed manifest，可直接按稳定 `shot_id` 复用；角色 manifest 只有 episode 冻结阵容，不能把整集 cast 冒充每镜参与角色。

iter110 指出完整 visual override 在没有逐镜消费者时会虚构 stale；本轮会建立它未来应消费的 `ShotImageRequestSpec.request_fingerprint` seam，但不同时引入通用 override sidecar、白名单、revision/CAS 和第二套 store。这样本轮仍是单一派生闭环，下一轮若实现 override，可只针对已经存在的图片输入真源定义精确影响面。固定外部参考仍限于阶段计划记录的 LumenX commit `743683387384fb1d9fff72038933e7249d416076` 与 LocalMiniDrama commit `92c66dd75688d83aac3ccc31bb51378613122cbc` 的 reference binding / candidate-selection 分层；只 clean-room 重写本仓契约，不复制外部代码、prompt 或 provider 语义。

## Plan

1. 在 `src/drama_schemas.py` 新增与现有资产 schema 隔离的 strict `ShotImageReference`、`ShotImageReferencePolicy`、`ShotImageRequestSpec` 与 `EpisodeShotImagePlan`。每镜 spec 绑定稳定 `shot_id`、`RenderShot.source_fingerprint`、当前 `ArtDirectionRef`/exact version、有效视觉字段、显式角色/场景/道具线索来源、被采用的 artifact-bearing refs、有界 warnings、逐镜 `request_fingerprint`；episode plan 绑定 season/episode、`RenderPlan.plan_fingerprint`、四类上游 manifest/selection fingerprint、mapping/policy fingerprint 与自身 plan fingerprint。不修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint 或 `RenderPlan.schema_version=1` shape。
2. 新建 `src/drama_shot_image.py`，实现纯函数 `build_episode_shot_image_plan(...)`。输入只接受已验证的 `RenderPlan`、角色 `EpisodeAssetManifest` 与对应 fresh catalog、selected ArtDirection exact version、`EpisodeSceneAssetManifest` 与对应 fresh catalog、`EpisodePropOrClueAssetManifest` 与对应 fresh catalog、完整显式 `shot_id -> ordered character_ids` 以及窄化的 `ShotImageReferencePolicy`；输出按 `RenderPlan.shots` 顺序确定，重复调用字节稳定，不读文件、不访问网络。
3. 显式角色 mapping 必须恰好覆盖全部当前 shot；单镜允许 `0..8` 个本集 frozen character IDs，顺序由调用方明确且不得重复。未知/遗漏/多余 shot、越过 frozen cast、重复角色、bool/非 list/超限容器全部 fail closed。场景必须来自同 shot 的 `ShotSceneRef`；道具/线索保持同 shot manifest 的 `0..16` 有序 refs。不得用 episode 全阵容替代逐镜角色，也不得从自由文本、prompt、位置、文件名或资产目录推断绑定。
4. 参考装配首版使用版本化固定优先级 `character → scene → prop/clue`，同类内部保留显式 mapping/manifest 顺序；`ShotImageReferencePolicy.max_reference_images` 作为 provider-neutral 的纯数据快照进入 fingerprint。超过上限时确定性保留前 N 个 artifact-bearing refs，并输出受控 reason/count，不让 LLM 临时选择。selected version 无 artifact 时不得伪造 path/SHA：显式镜头角色缺 artifact 使该镜 blocked；scene/prop/clue 的 exact structured spec 可继续进入文本指导，但只能在 artifact 存在时成为 image reference。本轮只冻结现有 path/SHA/size，不宣称已完成 MIME、尺寸或 provider capability 校验。
5. 新建 `src/drama_shot_image_store.py`，避免让已被 `drama_asset_versions.py` 引用的 `drama_render_store.py` 反向导入资产层形成循环。路径固定为 `outputs/episodes/episode_NN.shot_image_plan.json`；提供 `needs_shot_image_plan | fresh | stale | invalid | blocked_source` 五态 inspect/load/create/replace。builder/store 复用 `load_fresh_render_plan`、`load_fresh_episode_asset_manifest`、`load_fresh_episode_scene_asset_manifest`、`load_fresh_episode_prop_or_clue_asset_manifest` 与 `load_fresh_art_direction_catalog` 的公开 seam，不重新实现上游 freshness。
6. freshness 只绑定实际消费的 exact versions/artifacts 与显式 mapping/policy，不把整个 catalog 当依赖。未选候选、未使用资产或无关账务字段变化不得误 stale；已使用 selected/version/artifact、ArtDirection、RenderPlan shot/source、上游 manifest、角色 mapping 或 reference policy 变化精确 stale/blocked。上游当前不 fresh 时分类为 `blocked_source`；上游恢复并与已存 plan fingerprint 不一致时分类为 `stale`。替换 stale plan 必须显式 `replace_stale=True + expected_plan_fingerprint`，invalid 文件保留且不得静默覆盖。
7. store 复用 bounded duplicate-key/finite/depth JSON、`O_NOFOLLOW | O_NONBLOCK`、regular-file、workspace write lock、source/target token CAS、parent-dirfd 同目录临时文件与 atomic replace。create/replace 幂等早退前仍重验实际引用 artifact bytes；precommit 在同一临界区重读 RenderPlan、ArtDirection、三类 episode manifest/catalog、target token 与 artifact bytes，拒绝混合不同代 source。公共异常只返回有界分类，不回显 prompt、visual/spec tokens、绝对路径、lock holder、provider response、账号或签名 URL。
8. 新建 `tests/test_drama_shot_image.py` 与 `tests/test_drama_shot_image_store.py`。覆盖 strict schema、字节稳定、完整逐镜角色 mapping、引用顺序/裁剪、metadata-only 与 blocked 规则、实际使用/未使用依赖、逐镜 affected IDs、五态 inspection、显式 stale replacement、source/target/artifact race、symlink/FIFO/目录/越界/超限/deep/duplicate-key/NaN/Infinity、异常脱敏与 socket 零网络。聚焦回归覆盖 iter105-110、RenderPlan、角色/ArtDirection/SceneAsset/PropOrClueAsset、四导出、season export 与 legacy episode-1 video。
9. 本轮不修改 `ai_draw_client.py`、`drama_multimodal_smoke.py`、`drama_video.py`、`main.py`、Web routes/jobs/static 或 `scripts/run_local_drama_e2e.py`；不生成图片候选、不接 provider、不建立 paid attempt。实施阶段先跑新增/受影响聚焦测试、相关 `py_compile`、agent harness 与 `git diff --check`。收官按 `iter-finish` 执行 correctness/freshness、security/boundary、consumer-truth/compatibility 三个独立只读视角；修复 findings 后只运行一次最终 `bash scripts/verify.sh`。

## Acceptance

- **A111-01**：strict `ShotImageReference` / policy / request spec / episode plan 对 ID、kind、顺序、数量、fingerprint、path/SHA/size、extra、bool-as-int、非有限数和非规范字符串全部 fail closed；每镜与 episode fingerprints 覆盖完整 canonical 输入且重复构建字节稳定，不修改创作事实、上游 manifest 或 RenderPlan v1。
- **A111-02**：builder 只接受 fresh RenderPlan、fresh 角色/场景/道具线索 manifests 与 catalogs、可证明的 selected ArtDirection exact version、完整显式 `shot_id -> 0..8 ordered character_ids` 和 bounded policy。遗漏/多余/未知/重复/跨集/越过 frozen cast 的绑定阻断；不得从 prompt、画面文本、位置、文件名或目录推断角色/资产。
- **A111-03**：逐镜 reference assembly 按版本化 `character → scene → prop/clue` 与各自显式顺序确定；超过 `max_reference_images` 时结果、warning reason/count 和 fingerprint 稳定。角色 selected 无 artifact 时该镜 blocked；scene/prop/clue metadata-only 只作为结构化指导，不伪造 image reference，也不宣称 provider-ready。
- **A111-04**：EpisodeShotImagePlan 只绑定实际使用的 exact versions/artifacts 与 mapping/policy。未选候选、未使用资产和无关字段不误 stale；已使用 selected/version/artifact、ArtDirection、RenderPlan shot/source、upstream manifest、角色 mapping 或 policy 变化精确 stale/blocked，并报告受影响 shot IDs。显式 CAS replace 恢复 fresh，且不反向修改 episode、RenderPlan、资产 manifest、既有导出或 episode-1 video。
- **A111-05**：五态 store、bounded/nofollow/nonblock/regular-file、workspace lock、source/target CAS、dirfd atomic replace 与 artifact precommit reread 拒绝 symlink、FIFO、目录、越界、超限/深层/重复键 JSON 和竞态混代；invalid 文件不被覆盖，异常脱敏，socket 哨兵证明全链零网络。
- **A111-06**：聚焦回归覆盖 iter105-110 与现有短剧导出/video 兼容链；correctness/freshness、security/boundary、consumer-truth/compatibility 无未处理 P0/P1，P2 有明确处置。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高验收等级为 `mock-functional`，local fake-provider 仍单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片、真视频或真 ComfyUI。

## Implementation Notes

- 已新增 strict `ShotImageReferencePolicy` / `ShotImageRequestSpec` / `EpisodeShotImagePlan`，并用完整显式 `shot_id -> ordered character_ids` 构建 provider-neutral 的逐镜输入。单镜状态为 `assembled | blocked`；`assembled` 只表示本地规格装配完成，不是 provider-ready。
- reference 优先级固定为 `character -> scene -> prop/clue`，按 policy 确定性裁剪并把 warning/count/policy fingerprint 纳入每镜 fingerprint。character artifact 缺失会 blocked；scene/prop/clue metadata-only 仍保留 exact structured version，但不伪造 image reference。
- `EpisodeShotImagePlan` 只投影实际出镜角色的 exact ref/version/artifact；未出镜 frozen character 的 selected version 变化不误 stale。已使用角色在 episode manifest 重建前为 `blocked_source`，重建后才进入 `stale` 并报告 affected shots。角色 mapping fingerprint 按 `shot_id` canonical 排序，revision 只随 mapping 内容改变。
- store 固定落在 `outputs/episodes/episode_NN.shot_image_plan.json`，提供五态 inspect/load/create/replace、显式 stale 双 CAS、artifact bytes 重验、workspace lock 和 dirfd atomic replace。temp 使用高熵名，持有 fd 到 replace，并仅在 named dev/ino 仍属于本调用时 cleanup。
- 已比较两种候选：`visual override + C1` 能让 override 立即拥有消费者，但会同轮引入第二个可变真源、白名单、双 CAS 与独立 store；`C1 only` 可先冻结真实图片输入与 reference fingerprint，再让后续 override 精确依赖现存 consumer。为遵守“一轮一个可验收闭环”，本轮采用后者。
- `src/drama_render_store.py` 不作为新 store 落点，因为 `src/drama_asset_versions.py` 已依赖它；反向读取资产 manifests 会形成循环依赖。新 store 独立依赖两者的 public load/inspect seam。
- 角色 `AssetVersion` 只保存 identity fingerprint 与 optional artifact，不保留旧 selected version 的完整角色文本；因此不得读取当前 CharacterSheet 冒充旧版 prompt。首版显式镜头角色必须具有冻结 artifact，缺失时 blocked。
- 聚焦验证为新增链 23 tests OK，iter105-110 / RenderPlan / 资产 / 四导出 / season export / episode-1 video 兼容链 184 tests OK；相关 `py_compile`、agent harness 和 `git diff --check` 均通过。
- correctness/freshness、security/boundary、consumer-truth/compatibility 三个独立只读视角共发现并关闭 schema exact closure、source fingerprint、actual-used freshness、binding revision、status 命名、temp ownership 与异常脱敏等 findings；最终复核无遗留 P0/P1/P2。

## Acceptance Result

待 `iter-finish` 回填；当前仅完成立项与只读方案审计，未执行实现测试、全量验收或真实 provider 调用。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_111_drama_shot_image_spec_reference_assembly.md` | 新建 iter111 固定 8 段计划、Acceptance 与实现落点审计 |
| `docs/iterations/README.md` | 追加 iter111 canonical index |
| `src/drama_schemas.py` | 新增 strict 逐镜图片 reference/policy/request/episode plan schema 与跨字段 exact closure |
| `src/drama_shot_image.py` | 新增纯本地、provider-neutral 的显式角色绑定与确定性 reference assembly |
| `src/drama_shot_image_store.py` | 新增五态 freshness、显式 CAS replace、artifact 重验与 strict atomic persistence |
| `tests/_drama_shot_image_base.py` | 新增 iter111 synthetic 本地资产/manifest 共享 fixture |
| `tests/test_drama_shot_image.py` | 新增 schema、mapping、priority/truncation、metadata-only、fingerprint 聚焦测试 |
| `tests/test_drama_shot_image_store.py` | 新增五态、freshness、CAS、artifact/path/lock/race/temp ownership 边界测试 |

## 不在本轮范围

- 通用 visual override sidecar、camera/lighting/negative prompt/transition 白名单与双 CAS；RenderPlan v2；BGM/首尾帧/逐镜视频/Timeline/composite 的完整 dependency stale 矩阵。
- `ShotImageCandidate`、候选持久化/比较/选择、first/tail binding、跨镜 lineage、整集覆盖率与图片质量人工评审。
- `ai_draw_client` 多参考图 adapter、provider capability registry、submit/poll/download、paid ledger、crash/restart、JPEG/WebP decoder、图片 MIME/尺寸验证与任何真实调用。
- Web/API/CLI、两图比较 UI、资产管理 UI、跨集 used-by 缓存、ArtDirection global/episode scope。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1 shape、现有 Comfy/season export/episode-1 video 消费路径。
- 逐镜视频、TTS/voice、TimelineManifest、字幕、BGM/SFX、FFmpeg、ComfyUI、通用 DAG/worker、事件图与归档。
- `.env`、私有 `data/outputs/logs`、`小说txt/` 与用户未跟踪文件。

## Notes

- 立项阶段只修改本 iteration 文档与 canonical index，不 commit、不 push；用户确认前不得开始业务实现。
- 实施完成后必须使用 `iter-finish`；在 implementation commit 上完成审查与最终一次 canonical 验收，随后只允许 docs-only 收官提交。
- 收官时仅在事实变化后更新 README 项目状态，并就地替换 SOP 最近更新时间；同步 handoff 当前快照/Latest Transition 与 PROJECT_HISTORY 阶段历史。
- 提交信息草案：`docs(iter111): 迭代计划 111 立项（短剧逐镜图片规格与冻结引用装配）`。
