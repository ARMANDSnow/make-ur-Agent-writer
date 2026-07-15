# Iteration 107 - 短剧角色资产版本与冻结选择

## Context

`stage_plan_drama_full_production_pipeline.md` 与当前短剧 SOP 将 iter106 的 strict RenderPlan 视为阶段 A1；下一接力点是 A2/B1 的角色资产版本与 selected reference。现有 `CharacterSheet.reference_images` 仍把列表顺序当作当前引用，没有不可变版本、显式选择、CAS 或单集冻结 AssetRef。为避免把媒体事实反写进 `episode_NN.json`、季角色表或 RenderPlan v1，本轮建立纯本地的季级角色资产目录与集级冻结 manifest；不接 Web、provider 或逐镜媒体。

## Plan

1. 在 `drama_schemas` 新增 strict `AssetVersion`、`CharacterAsset`、`AssetRef`、`CharacterAssetCatalog` 与 `EpisodeAssetManifest`，使用内容寻址版本 ID、严格 fingerprint、可选受控 artifact，以及显式 selected/revision。
2. 新建 `drama_assets` 纯函数层，从 CharacterSheet 的渲染身份字段生成确定版本；迁移 legacy `reference_images` 而不移动文件，首项保持当前 selected 语义，无图片角色只生成 metadata-only 版本。
3. 新建 `drama_asset_versions` store，在 `data/assets/season_01.character_assets.json` 与 `outputs/episodes/episode_NN.asset_manifest.json` 持久化严格 envelope，复用 bounded/nofollow 读取、workspace 写锁、source/target CAS 与目录-fd 原子替换边界。
4. 实现 catalog create/inspect/refresh、append-only version 与 selected CAS；相同追加/选择幂等，新候选不自动切换 selected，stale/invalid 不静默覆盖。
5. 只从 fresh RenderPlan 与 fresh catalog 生成单集 manifest，精确覆盖冻结角色；绑定 RenderPlan 与 active selected refs，而不绑定整个 catalog，避免未选候选和非活跃角色误伤旧集。
6. 用 synthetic workspace 覆盖 schema、legacy 迁移、metadata-only、append/select、并发 CAS、五态 inspection、symlink/路径/JSON 边界、精确 stale 与 socket 零网络，并回归 iter105/106、season export 和 episode-1 legacy video。

## Acceptance

- **A107-01**：所有新 schema 对版本、ID、fingerprint、唯一性、derived-from 同资产/无环、duplicate JSON key、NaN/Infinity、bool 冒充整数和 extra 字段进行 fail-closed 校验。
- **A107-02**：旧角色 ID 无损迁移；多引用按原顺序生成不可变版本并选择第一项；无图片只生成 metadata-only 版本；重复创建字节稳定，且不修改 CharacterSheet、`episode_NN.json` 或 RenderPlan v1。
- **A107-03**：版本只追加；相同候选幂等；新候选不改变 selected；相同选择不增加 revision、不改写文件。跨角色 derived-from、未知版本或历史覆盖均失败。
- **A107-04**：selected mutation 同时验证 expected selection revision/current selected ID；workspace lock 内复核 source/target token。并发冲突、ABA、symlink、非普通文件、路径越界、超限/深层 JSON 均无写入失败。
- **A107-05**：catalog/manifest 分别区分 `needs_*/fresh/stale/invalid/blocked_source`；active selection 或 RenderPlan 变化精确使 manifest stale，未选候选、非活跃角色和账务/评审字段变化不误伤。
- **A107-06**：聚焦回归覆盖角色合并、iter105 冻结角色投影、iter106 RenderPlan/store、season export 与 episode-1 legacy video；socket 哨兵证明新链零网络。correctness 与 security/boundary 两视角无未处理 P0/P1，最终只运行一次 `bash scripts/verify.sh`；canonical 结论最多为 `mock-functional`，独立短剧组件仍为 `local-e2e`、`provider_validated=false`。

## Implementation Notes

- `src.drama_assets` 负责纯函数投影：角色渲染身份排除 `appearances`、`generated_episode_nos`、`manual_override`、`agent_suggestions` 等账务/评审字段；legacy `reference_images` 按当前顺序生成不可变版本，首项为初始 selected，无图片角色生成不带 artifact 的 metadata-only 版本。
- `src.drama_asset_versions` 暴露 catalog 的 create/inspect/refresh/load、version append、selection CAS，以及 episode manifest 的 create/inspect/load；catalog 固定写入 `data/assets/season_01.character_assets.json`，manifest 固定写入 `outputs/episodes/episode_NN.asset_manifest.json`。
- 新 store 使用 bounded duplicate-key/NaN/depth JSON、`O_NOFOLLOW | O_NONBLOCK`、workspace 写锁、目录 fd 原子替换和双 target-token 复核；temp 写完后再次读取 CharacterSheet/source，最后校验 appended/selected artifact，随后复核 target token，竞态失败不覆盖原文件。
- Manifest freshness 只投影 fresh RenderPlan 的 `frozen_character_ids`、对应角色当前渲染身份与 selected version/artifact；未选候选、非活跃角色及整个 catalog 的无关变化不会误伤旧集。
- 聚焦回归共 109 tests，通过；其中 iter107 资产测试 23 tests，覆盖真实 selection ABA、precommit CharacterSheet/artifact 变化、baseline 前与 replace 前 target 变化、FIFO/symlink/目录/超限/deep JSON、精确 stale 与 socket 零网络。
- 三路独立只读审查结论均为无遗留 P0-P2：correctness 发现并推动关闭 target CAS、selected artifact 最终复核等窗口；security/boundary 推动补齐 FIFO、真 ABA 与 precommit race 证据；schema/freshness 推动加入 `asset_id` 归属、active-only freshness 与五态测试。未扩大到 Web/provider、场景/道具或 RenderPlan v1。

## Acceptance Result

- **A107-01 — PASS**：strict schema 对内容寻址 ID/full fingerprint、唯一性、同资产 derived-from/无环、duplicate key、NaN/Infinity、bool-as-int 与 extra 字段全部 fail closed；foreign version 和重签 source fingerprint 均有反例测试。
- **A107-02 — PASS**：legacy 角色 ID 与引用顺序无损迁移，首项 selected；无引用图只产 metadata-only version，不伪造 artifact/SHA。重复 create 字节与 mtime 稳定，CharacterSheet、`episode_NN.json`、RenderPlan v1 均未修改。
- **A107-03 — PASS**：append-only、相同候选/相同选择幂等，新候选不自动 selected；selection revision 单调增加。跨角色版本、未知版本与派生链错误无写入失败。
- **A107-04 — PASS**：revision + current selected 双 CAS 覆盖 A→B→A 真 ABA；source baseline、precommit CharacterSheet/artifact、target baseline 前/replace 前变化均经注入证明原 target bytes 不变。nofollow、FIFO/目录、路径、超限与深层 JSON 边界通过。
- **A107-05 — PASS**：catalog/manifest 五态均覆盖；manifest 只绑定 fresh RenderPlan 与 active selected refs。未选候选、非活跃角色/source 变化不误 stale，active selection/artifact 或 RenderPlan 变化精确 stale，stale 必须显式替换。
- **A107-06 — PASS（有流程偏差）**：109 项聚焦回归通过；correctness、security/boundary、schema/freshness 三路独立只读复核最终均为 P0/P1/P2 = 0。Accepted implementation commit `3147bf59143f9fd9169ce410acbcc2a6ae808694` 上 authoritative canonical evidence `run_id=f3c0d58e4e98430da14554885328e860`：2155 tests、15 steps、144 秒、exit 0、`tracked_scope_clean=true`、tree `b2b05c9bd227511df256c35b2c9458a17098ac39`，mock preflight 0 FATAL / 0 WARN，结论 `mock-functional`。mandatory loopback evidence 为 `local-e2e`、`provider_validated=false`，图片/上传/轮询/callback/视频与五站授权计数闭合。
- 流程偏差：第一次 canonical 长输出调用返回时，后台 session id 被截断，主线程误判为中断并在同一 clean HEAD/tree 上启动第二个 process；最终 evidence 只接受后启动且完整结束的 run。实现和文档在两次调用之间没有变化，但“仅一次 invocation”未被严格满足，故在此显式记录，不把重复调用隐藏为单次。
- 验收等级：**mock-functional**；fake-provider 组件另列 **local-e2e**；**provider-validated=false**。未运行真文本、真生图、真视频，未读取 `.env`、私有样本或两份体检报告。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_107_drama_character_asset_version_selection.md` | 建立 iter107 计划、Acceptance ID 与审计骨架 |
| `docs/iterations/README.md` | 追加 canonical iteration 索引 |
| `src/drama_schemas.py` | 新增 strict 角色资产版本、目录、AssetRef 与单集 manifest 契约 |
| `src/drama_assets.py` | 新增角色渲染身份投影、legacy 迁移、append/select 与 manifest 纯函数 |
| `src/drama_asset_versions.py` | 新增本地 catalog/manifest 五态检查、安全持久化、CAS 与 freshness 接口 |
| `src/drama_store.py` | strict workspace leaf 读取增加 `O_NONBLOCK`，非普通文件 fail closed |
| `tests/test_drama_assets.py` | 覆盖 schema、内容寻址、迁移、派生链与纯函数边界 |
| `tests/test_drama_asset_versions.py` | 覆盖 store、并发 CAS、五态、精确 stale、安全边界与离线链路 |
| `README.md` | 同步 iter107 短剧里程碑与实时 SOP |
| `docs/AGENT_HANDOFF.md` | 就地更新当前能力、验收基线、缺口与接力点 |
| `docs/PROJECT_HISTORY.md` | 追加 iter107 阶段索引与长期资产冻结决策 |

## 不在本轮范围

- 场景、道具、线索、ArtDirection 完整库；通用 visual override/stale 传播矩阵。
- Web/API、候选比较 UI、图片/视频/TTS provider、paid ledger 与通用媒体队列。
- 首尾帧、逐镜图片/视频、TimelineManifest、字幕、BGM/SFX、FFmpeg、ComfyUI 或任何真实调用。
- 修改 DramaEpisode、CharacterSheet、RenderPlan v1 或现有 legacy video/export 消费路径。

## Notes

- 本轮显式使用 repository-local `iter-start`；实施完成后使用 `iter-finish`，仅在事实变化时就地同步 README、handoff 与 PROJECT_HISTORY。
- 当前 README、handoff、短剧 SOP 的用户改动和两份未跟踪体检报告保持原样；体检报告不读取、不 stage、不 commit。
- 立项提交信息草稿：`docs(iter107): 迭代计划 107 立项（短剧角色资产版本与冻结选择）`；起轮不自动 commit、不 push。
- implementation commit：`3147bf59143f9fd9169ce410acbcc2a6ae808694`；收官只追加 docs-only commit，不 push。
