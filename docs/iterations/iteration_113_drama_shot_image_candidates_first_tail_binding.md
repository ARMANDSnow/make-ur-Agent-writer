# Iteration 113 - 短剧逐镜图片候选选择与首尾帧绑定

## Context

iter111 已把 fresh `RenderPlan`、完整显式逐镜角色 mapping、exact 角色/场景/道具线索版本与确定性 reference policy 装配成 provider-neutral `EpisodeShotImagePlan`，但只证明“每镜应如何生图”，尚未形成图片候选事实、显式选择、首帧/可选尾帧绑定和整集覆盖率。iter112 只改进 iteration workflow，不改变短剧产品能力。根据 `stage_plan_drama_full_production_pipeline` 阶段 C、README 实时 SOP 与 handoff 接力点，本轮以纯本地、零网络的 C2 为最小闭环：消费 fresh C1 plan，建立不可变候选、guarded selection、first/tail binding、紧邻镜头 typed lineage 与精确 stale/coverage 语义，为后续逐镜 provider adapter 和视频阶段提供稳定输入。

## Plan

### Implementation Context

- `must_read`: `README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_111_drama_shot_image_spec_reference_assembly.md`, `src/drama_schemas.py`, `src/drama_shot_image.py`, `src/drama_shot_image_store.py`, `src/ai_draw_client.py`, `tests/_drama_shot_image_base.py`, `tests/test_drama_shot_image.py`, `tests/test_drama_shot_image_store.py`
- `expected_changes`: `docs/iterations/iteration_113_drama_shot_image_candidates_first_tail_binding.md`, `docs/iterations/README.md`, `src/drama_schemas.py`, `src/drama_shot_image_candidates.py`, `src/drama_shot_image_candidate_store.py`, `tests/_drama_shot_image_candidate_base.py`, `tests/test_drama_shot_image_candidates.py`, `tests/test_drama_shot_image_candidate_store.py`, `README.md`, `docs/product/short_drama_module.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、私有 `data/outputs/logs` 内容、`小说txt/`、用户未跟踪体检报告；`src/ai_draw_client.py` 只读核对既有 PNG 安全边界，不接 provider、不改真生图入口；不改 Web/job、现有导出、episode-1 video、`DramaEpisode`、`RenderPlan` 或 `episode_NN.json` 契约；canonical verify 自管 acceptance 产物除外

1. 在 `drama_schemas.py` 的 `EpisodeShotImagePlan` 后增加 strict C2 schema：本地 PNG artifact、content-addressed `ShotImageCandidate`、逐镜 append-only 候选池、显式 first/tail binding、selection revision、episode manifest 与 coverage projection。candidate 必须绑定 episode、stable shot、C1 plan/request fingerprint 与实际 artifact SHA；extra、bool 冒充整数、重复/未知 ID、跨镜引用和字段篡改 fail closed。
2. 新建 `drama_shot_image_candidates.py` 作为纯函数领域层：从 fresh plan 初始化 manifest；显式追加 candidate；按 candidate ID 做 guarded selection；新候选不得自动替换既有选择。tail 必须显式表示 `none` 或 direct candidate；first 只允许 direct candidate 或紧邻上一镜当前 tail 的 `previous_tail` typed lineage，不允许从目录、文件名、位置或“最新文件”猜测。
3. candidate 与 selection 分层：candidate 绑定生成时的 request fingerprint 并保持不可变；选择变化只递增对应 shot 的 selection revision。上一镜 tail 后续改变时，下一镜既有 `previous_tail` 不自动改写，而进入可解释 stale/coverage blocked，必须用 expected revision/current binding CAS 显式重绑。
4. 新建 `drama_shot_image_candidate_store.py`，只消费 `load_fresh_episode_shot_image_plan` 的公开 seam，独立落盘 `episode_NN.shot_image_assets.json` 与受限逐镜 artifact 目录。提供 `needs_shot_image_assets | fresh | stale | invalid | blocked_source` inspect/load/create/reconcile/append/select；复用 workspace lock、source/target CAS、bounded/nofollow/nonblock/regular-file、dirfd atomic replace、artifact precommit reread 与 temp ownership 守门。candidate ready 仅证明固定 PNG 的本地 magic/结构、bounded size、width/height 与 SHA 完整性，不宣称 provider-ready，也不开放 JPEG/WebP。
5. C1 plan/request 漂移按 affected shot 精确传播：未受影响镜头的 candidate 历史与选择原样保留；受影响镜头的旧 candidate/selection 保留为审计事实但不计 fresh coverage。coverage 要求每个 required、assembled shot 有 fresh first binding；tail 可选但必须显式，C1 blocked shot 与断裂 lineage 必须单列 blocked reason，不能伪装成已覆盖。
6. 新增 synthetic fixture、纯函数和 store 聚焦测试，覆盖 schema/content address、append 不自选、first/tail/lineage、CAS/stale/coverage、PNG artifact、JSON/path/symlink/FIFO/race/锁/脱敏和零网络；回归 iter105-111、资产/RenderPlan、四导出、season export 与 episode-1 video。完成聚焦检查和三视角只读审查、修复 findings 后形成 implementation commit，最后只运行一次 canonical `bash scripts/verify.sh`，再用 `iter-finish` 收官。

## Acceptance

### Review Context

- `correctness_behavior`: 核对 C1 plan 到 C2 candidate/selection/binding 的身份闭包、新 candidate 不改 selection、first/tail 与紧邻 previous-tail lineage、精确 affected-shot stale、coverage 及 iter105-111/导出/video 向后兼容
- `security_boundary`: 核对 candidate JSON 与 artifact 的 workspace confinement、regular-file/nofollow/bounded PNG/hash/dimensions、重复键/深层/超限输入、锁/CAS/TOCTOU/temp ownership、错误脱敏和全链零网络
- `extra_risk_view`: `media/storage/recovery`，核对坏/缺 artifact、部分写入、重启重读、append/select 幂等重放、断裂 lineage 与 C1 blocked/stale 时均安全停止且可显式恢复

- **A113-01**：strict C2 schema 可 byte-stable round-trip；candidate ID/fingerprint 由 episode、shot、C1 plan/request、artifact SHA 与受控元数据确定，拒绝 extra、bool/非有限数、重复/未知 ID、跨 episode/shot 引用、篡改 fingerprint 和非 canonical 路径；不修改 `DramaEpisode`、`RenderPlan`、`EpisodeShotImagePlan` 既有 shape。
- **A113-02**：candidate 只可追加到对应 fresh、assembled shot，幂等重放仍重验 artifact；追加新 candidate 不自动选中或替换 first/tail。selection 必须显式给 candidate ID、expected selection revision 与 expected current binding，陈旧 writer、悬空/跨镜/不匹配 request candidate 均 fail closed。
- **A113-03**：first 必须 direct candidate 或紧邻上一镜 exact current tail 的 `previous_tail`；tail 必须显式 `none` 或 direct candidate。上一镜 tail 改变只使依赖 lineage stale，不自动改下一镜；coverage 精确列出 fresh first、缺失 first、C1 blocked 与 broken lineage，tail 为空不误报缺失。
- **A113-04**：C1 plan/request 变化只影响对应 shot；reconcile 在 source/target 双 CAS 下保留未受影响候选和选择，受影响旧事实可审计但不计 fresh coverage。未选 candidate、未受影响 shot 和候选追加不误 stale，affected shot IDs/reasons/fingerprints 稳定可复现。
- **A113-05**：store 五态、bounded/nofollow/nonblock/regular-file、workspace lock、source/target/selection CAS、dirfd atomic replace、artifact precommit reread 与 temp ownership 拒绝 symlink、FIFO、目录、越界、超限/深层/重复键 JSON、伪/坏/超限 PNG、hash/尺寸不符和竞态混代；invalid 文件不被覆盖，公开错误脱敏，socket 哨兵证明全链零网络。
- **A113-06**：新增链与 iter105-111、RenderPlan、角色/ArtDirection/scene/prop-clue 资产、四导出、season export、episode-1 video 聚焦回归通过；correctness/behavior、security/boundary、media/storage/recovery 三个独立只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高验收等级为 `mock-functional`，local fake-provider 仍单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片、真视频、真 ComfyUI 或任何 provider 请求。

## Implementation Notes

- 立项时 canonical 最新编号已是收官的 iter112，因此用户所说“下一轮 iter112”按索引纠正为 iter113，不重写或复制历史 iteration。
- 路线图早期建议扩展 `drama_render_store.py`；当前代码已由 iter111 建立独立 `drama_shot_image_store.py`，且资产模块依赖 render store。C2 继续使用独立 candidate store 消费 C1 public seam，避免反向依赖与第二个创作真源。
- `drama_schemas.py` 新增 content-addressed PNG artifact/candidate、append-only 候选池、direct/none/previous-tail binding、manifest 与 coverage strict schema。候选固定绑定 episode/shot/C1 plan/request/artifact identity，首尾选择与候选追加分层。
- `drama_shot_image_candidates.py` 实现纯函数 manifest 初始化、candidate append、guarded first/tail selection、reconcile、affected-shot 与 coverage。`previous_tail` 同时绑定上镜 tail revision 与本镜 request fingerprint；tail A→B→A 不会自动复活历史 lineage。
- selection lost-response 只允许 exact receipt 重放；receipt 覆盖 shot/frame、pre-manifest fingerprint、expected revision/current binding 与 desired binding。相同 desired 但 token/binding 不同的陈旧 writer 仍 fail closed，revision 限制为 `0..2_147_483_647`。
- `drama_shot_image_candidate_store.py` 实现五态 inspect/load/create/reconcile/append/select，以 workspace lock、source/target CAS、bounded strict JSON/PNG、dirfd/nofollow/nonblock/regular-file、create-only artifact、temp inode ownership 与 precommit reread 守门。候选上限、source/request 与 CAS 都在 artifact 发布前检查，正常失败清理同时核对 manifest 引用与本轮 inode identity。
- 缺失 artifact 可用 `candidate_id + expected_manifest_fingerprint + exact PNG bytes` 做 create-only 显式修复，支持多缺失逐个修复与 reconcile 后历史 candidate；其他 artifact 缺失不阻断当前目标修复。损坏或被占用的 canonical path 永不自动覆盖：需人工先隔离损坏 inode，再按 manifest 的 path/SHA-256/size/dimensions 恢复 exact bytes 并重新 inspect，不得重建 manifest 掩盖损坏事实。
- affected-shot 序列漂移按 `shot_id -> immediate predecessor` 比较，插入镜头只影响新镜与直接前驱变化的旧镜；重排/删除后历史 lineage 保留为审计事实，coverage 精确标记 broken，不自动改写。
- 第一轮三视角审查发现 tail ABA、重排 lineage schema、lost-response replay、shot order stale、coverage 闭包、artifact-before-CAS orphan、target request 漂移与缺失恢复等问题；修复后经独立 correctness、security/boundary、media/storage/recovery 二次只读复核。新链 29 项、跨 iter105–111/资产/导出/video 聚焦回归 213 项通过；未运行真模型、真生图或 provider 请求。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion

- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮新知识是 C2 产品契约与具体存储/恢复边界，已由代码、测试和当轮审计记录固化；没有新增跨迭代 workflow 规则、长期工程铁律或可复用 SOP 决策需要晋升。收官对产品 SOP 的 C2 状态同步属实时性更新，不作 Knowledge Promotion。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_113_drama_shot_image_candidates_first_tail_binding.md` | 新建 iter113 固定八段计划与 C2 边界 |
| `docs/iterations/README.md` | 追加 iter113 canonical index |
| `src/drama_schemas.py` | 新增候选、选择 receipt、首尾帧 lineage、manifest 与 coverage strict schema |
| `src/drama_shot_image_candidates.py` | 新增纯本地 candidate/selection/binding/reconcile/stale/coverage 领域函数 |
| `src/drama_shot_image_candidate_store.py` | 新增五态 strict store、CAS、create-only artifact、原子写、显式 repair 与完整性守门 |
| `tests/_drama_shot_image_candidate_base.py` | 新增基于 iter111 的 synthetic C2 fixture |
| `tests/test_drama_shot_image_candidates.py` | 新增纯函数、identity、selection receipt、lineage、affected IDs 与 coverage 测试 |
| `tests/test_drama_shot_image_candidate_store.py` | 新增五态、artifact、路径、CAS、race、并发、repair、恢复与零网络测试 |
| `README.md`、`docs/product/short_drama_module.md` | iter-finish 时按实际 accepted 能力同步实时 SOP |
| `docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | iter-finish 时就地同步当前快照与筛选后的阶段历史 |

## 不在本轮范围

- 逐镜 provider adapter、`ai_draw_client` 多参考图接线、provider capability registry、submit/poll/download、paid attempt/ledger、crash/restart 网络窗口、真实图片调用与任何计费验证。
- JPEG/WebP decoder、远端 MIME/redirect/DNS/peer-IP 下载校验、通用媒体导入；本轮只接受受限本地 PNG fixture/artifact 并证明完整性。
- Web/API/CLI、镜头候选比较 UI、资产管理 UI、跨集 used-by、ArtDirection 多 scope、通用 visual override 与完整 dependency matrix。
- 逐镜视频、episode 2+ 视频、TTS/voice、`TimelineManifest`、字幕、BGM/SFX、FFmpeg/compositor、编辑器导出、通用 DAG/worker、事件图、生产工作台与归档。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1、C1 request/plan shape、现有 Comfy/season export/episode-1 video 消费路径。
- `.env`、私有 `data/outputs/logs` 内容、`小说txt/` 与用户未跟踪文件。

## Notes

- 用户已明确确认开始实现；实现与修复期间只运行 mock/local 聚焦检查。
- 收官仍须先形成 implementation commit，再只运行一次 canonical `bash scripts/verify.sh`；验收后只允许 docs-only 收官提交，只 commit、不 push。
- implementation commit 信息草案：`feat(drama): add shot image candidate bindings (iter113)`。
