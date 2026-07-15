# Iteration 108 - 短剧美术方向资产版本与 RenderPlan 冻结

## Context

`stage_plan_drama_full_production_pipeline.md` 与当前短剧 SOP 显示：iter107 已闭环角色不可变版本、selected CAS 和单集 `AssetRef`，但阶段 A2/B 仍缺通用视觉覆盖、场景/道具/线索和 `ArtDirection`。本轮不扩成整个阶段 B，而选择已有真实代码 seam 的 `ArtDirection` 单一竖切：`ArtDirectionRef` 已存在于 `drama_schemas`，`build_render_plan` 已将它写入 `RenderPlan v1` 指纹，但 `drama_render_store` 目前仍接受调用者直接传入任意 ref，inspect 又使用已落盘 ref 自证，无法证明 ref 来自不可变候选和当前 selected，也无法在选择变化后使计划 stale。

本轮借鉴固定 LumenX commit `743683387384fb1d9fff72038933e7249d416076` 的 `src/apps/comic_gen/models.py`、`pipeline.py` 与 `frontend/src/components/modules/ArtDirection.tsx` 中“preset/自定义候选、显式选择、系列继承”的产品分层；只重写本仓所需的 schema、内容寻址、CAS 与安全持久化，不复制其代码，也不采用“最新候选自动成为当前选择”的语义。首版只做 season/series 级单一 selected 方向，不做 global/episode override 解析，不接 Web 或 provider。

相比之下，通用 visual override 目前没有 schema/store/真实逐镜消费者；场景、道具、线索在 `StoryboardShot`/`RenderShot` 中也没有稳定语义 ID。两者若在本轮展开，会同时引入新真源、绑定协议和下游抽象，违反路线图“一轮一个可验收闭环”的拆分原则，因此顺延。

## Plan

1. 在 `src/drama_schemas.py` 新增 strict `ArtDirectionSpec`、内容寻址 `ArtDirectionVersion` 与 `ArtDirectionCatalog`：包含稳定 `art_direction_id`、preset、bounded positive/negative tokens、palette、aspect ratio、`derived_from`、版本/目录 fingerprint、`selected_version_id` 和 `selection_revision`；保持现有 `ArtDirectionRef`、`RenderPlan.schema_version=1`、DramaEpisode、Storyboard、CharacterSheet 与角色资产 schema 不变。`ArtDirectionRef.fingerprint` 明确绑定 selected version fingerprint。
2. 在 `src/drama_assets.py` 增加纯函数 `build_art_direction_version`、`append_art_direction_version`、`select_art_direction_version` 与 `selected_art_direction_ref`。版本 append-only、相同候选幂等，新候选不自动 selected；选择同时校验 expected revision/current version ID，A→B→A 不能绕过旧 revision。AI suggestion 只允许作为显式传入的候选来源，不在本轮调用模型。
3. 新建 `src/drama_art_direction_store.py`，固定 season 1 首版路径为 `data/assets/season_01.art_direction.json`，提供 catalog inspect/create/append/select/load-selected-ref。复用 bounded duplicate-key/finite/depth JSON、`O_NOFOLLOW | O_NONBLOCK`、workspace write lock、target token CAS、目录 fd 同目录临时文件与 atomic replace；新低层 store 不反向依赖 `drama_render_store`，避免和现有 `drama_asset_versions → drama_render_store` 形成循环导入。
4. 修改 `src/drama_render_store.py`：store 层始终从 fresh ArtDirection catalog 解析 selected ref，不再信任调用者提供的 ref。为兼容现有签名，调用者若传 `art_direction_ref`，它只能作为 expectation 且必须与 catalog selected 精确一致；无 catalog 时只允许 legacy `None`。无 catalog + 旧 plan ref 为 `None` 继续 fresh；无 catalog却存在非空 ref、catalog invalid 或 selected ref 无法证明时 fail closed；selected 变化精确使 RenderPlan stale，必须显式 `replace_stale=True` 才按当前 selected 重建。
5. 保持 `src/drama_render_plan.py` 的 builder 主体不变，复用其已存在的 `art_direction_ref` 注入与 `plan_fingerprint` 计算。增加回归证明：未选候选不改变计划，selected 改变后旧计划 stale；显式重建生成字节稳定的新计划，并沿现有 `drama_asset_versions.inspect_episode_asset_manifest` 链使旧单集角色 manifest stale，重建 manifest 后恢复 fresh。
6. 新建 `tests/test_drama_art_directions.py` 与 `tests/test_drama_art_direction_store.py`，扩展 `tests/test_drama_render_store.py`、`tests/test_drama_asset_versions.py`。覆盖 strict schema、内容寻址、派生无环、append/select 幂等、双 CAS/ABA、legacy missing、伪造/孤儿 ref、精确 stale、source/target race、symlink/FIFO/目录/越界/超限/deep JSON 与 socket 零网络；聚焦回归 iter105-107 的 character projection、RenderPlan、角色 catalog/manifest、season export 和 legacy episode-1 video。
7. 实施阶段先做聚焦测试和静态检查，再按 `iter-finish` 进行 correctness 与 security/boundary 至少两路只读审查；schema/freshness 作为本轮高风险专项增加第三视角。修复 findings 后只运行一次最终 `bash scripts/verify.sh`，并仅在事实变化时同步 README、handoff、PROJECT_HISTORY 及当前仍停留在 iter106 口径的 `docs/product/short_drama_module.md`。

## Acceptance

- **A108-01**：ArtDirection strict schema 对 ID、版本/content fingerprint、token/palette/aspect 边界、版本唯一性、同资产 derived-from/无环、extra 字段、duplicate JSON key、NaN/Infinity 与 bool-as-int 全部 fail closed；不修改 DramaEpisode、Storyboard、CharacterSheet、角色资产 schema 或 RenderPlan v1 shape。
- **A108-02**：ArtDirection 版本只追加；相同候选与相同选择幂等且不改 bytes/mtime；新候选不自动 selected；selection revision + current version ID 双 CAS 覆盖并发冲突和真实 ABA，未知/跨 catalog/孤儿版本无写入失败。
- **A108-03**：catalog store 对 missing/fresh/invalid 有确定状态；bounded/nofollow/nonblock、workspace lock、target token CAS、目录 fd atomic replace 拒绝 symlink、FIFO、目录、路径越界、超限/深层 JSON 与 replace 前 target race，异常不公开完整 token 列表或本地绝对路径。
- **A108-04**：RenderPlan 只冻结可证明 fresh catalog 的 selected `ArtDirectionRef`；无 catalog 且 ref 为 `None` 的旧 workspace 保持兼容，调用者伪造 ref、catalog invalid、无 catalog 的孤儿 ref 均不能成为 fresh。相同输入重复构建字节稳定，不改 creative fingerprint 或 frozen character projection。
- **A108-05**：追加未选候选不误 stale；selected 改变精确使 RenderPlan stale，并通过现有 render-plan 依赖使 EpisodeAssetManifest stale；显式重建计划/manifest 后恢复 fresh。角色 selection、非活跃角色、账务/评审字段的既有精确 freshness 不退化，全链 socket 哨兵证明零网络。
- **A108-06**：聚焦回归覆盖 iter105-107、season export 与 episode-1 legacy video；correctness、security/boundary、schema/freshness 三视角无未处理 P0/P1，P2 有明确处置；最终只运行一次 `bash scripts/verify.sh`。canonical 结论最多为 `mock-functional`，独立短剧组件仍单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片或真视频。

## Implementation Notes

- 首版 `ArtDirection` 固定为 workspace 内 season/series 级目录与单一 selected 方向；global/episode scope、跨 season 继承与冲突解析后续另立迭代。`AssetVersion`/`AssetArtifact` 仍保持角色专用，ArtDirection 使用并行 strict schema，只复用内容寻址与 CAS 语义。
- `ArtDirectionVersion.version_fingerprint` 覆盖完整 canonical payload，`version_id=ad_<fingerprint 前 24 位>`；catalog fingerprint 同时覆盖版本集合、selected ID 与 selection revision。append 使用 whole-catalog CAS，select 使用 revision + 当前 selected ID 双 CAS，新候选不会自动成为 selected。
- store 固定写入 `data/assets/season_NN.art_direction.json`，复用 strict bounded JSON 和 workspace lock，并使用 parent dirfd、`O_NOFOLLOW | O_NONBLOCK`、target token、同目录临时文件与 atomic replace；公共 mutation 边界将 Pydantic token、绝对路径和 lock holder 细节统一脱敏。
- RenderPlan 创建与 inspect 都从 fresh catalog 独立解析 selected ref；调用者传入 ref 只作为 expectation。legacy 无 catalog + `None` 保持兼容，catalog invalid、无 catalog却有孤儿 ref或 ref 不匹配均 fail closed。selected 改变使旧 plan 精确 stale，继而沿既有依赖使 EpisodeAssetManifest stale。
- 聚焦回归先完成 181 项（iter105-107、season export、legacy video 及新增 ArtDirection 链），审查修复后的相关回归 56 项通过；`py_compile`、agent harness 与 `git diff --check` 通过。socket 哨兵覆盖 create/append/select 及 ArtDirection→RenderPlan→EpisodeAssetManifest 重建全链。
- correctness 审查发现间接孤儿链可能泄漏 `KeyError`；security/boundary 审查发现公共异常可能泄漏 token/path/holder，并发现共享 workspace lock 的 lock/holder symlink 外写风险；schema/freshness 审查发现空白 token/preset 与若干 no-write/blocked/offline 证据缺口。以上均已修复并补回归，最终审查结论在 Acceptance Result 回填。
- 已接受的 P2 威胁模型：所有项目认可的并发写者必须统一遵守 workspace flock；本机其他进程或直接文件篡改属于既有严格本地对手 TOCTOU，不宣称 target-token check 对非合作写者提供原子 CAS。

## Acceptance Result

- 待用户确认后实施，并在 `iter-finish` 中逐项引用 A108-01 至 A108-06 回填。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_108_drama_art_direction_version_render_plan_freeze.md` | 建立 iter108 的 Context、代码落点、实施顺序与 Acceptance 骨架 |
| `docs/iterations/README.md` | 追加 canonical iteration 索引 |

## 不在本轮范围

- 通用 visual override sidecar、camera/lighting/negative prompt/transition CAS 与尚无真实消费者的全量 dependency stale 矩阵。
- SceneAsset、PropOrClueAsset、线索状态演化、稳定 scene/prop/clue ID、逐镜 typed refs、used-by 反向索引与 global/episode scope resolution。
- Web/API/CLI、候选比较 UI、图片/视频/TTS provider、paid ledger、通用媒体任务 DAG 与成本抽象。
- 首尾帧、逐镜图片/视频、TimelineManifest、字幕、BGM/SFX、FFmpeg、ComfyUI、episode 2+ 视频或任何真实调用。
- 修改 `episode_NN.json`、季角色表、RenderPlan v1 schema、现有 legacy video/export 消费路径，或读取/修改 `.env`、私有样本与 `小说txt/`。

## Notes

- 本轮显式使用 repository-local `iter-start`；实施完成后必须使用 `iter-finish`，先聚焦检查与多视角只读审查，修复 findings 后再做最终一次标准全量验收。
- 两份未跟踪体检报告属于用户文件，保持不读、不改、不 stage、不 commit。
- 立项提交信息草稿：`docs(iter108): 迭代计划 108 立项（短剧美术方向资产版本与 RenderPlan 冻结）`；起轮不自动 commit、不 push。
