# Iteration 106 - 短剧渲染计划与创作陈旧性边界

## Context

`stage_plan_drama_full_production_pipeline.md` 将 `episode_NN.json` 定义为创作事实真源，并把 RenderPlan 设为创作层到媒体层的冻结关口。当前仓库已在 iter 105 统一单集冻结角色投影，但 assembled episode 仍只有连续 `shot_no`、整段 narration/dialogue 与多处各自实现的 freshness 校验；不存在稳定镜头语义 ID、全局有序 spoken schema、严格 RenderPlan 文件或统一 stale 状态。本轮只交付阶段 A 的第一个纯本地闭环，为后续资产版本、逐镜媒体、声音时间线与合成提供可审计上游，不提前引入 provider、Web、CLI 或通用媒体队列。

## Plan

1. 在 `drama_schemas` 新增严格 `extra=forbid` 的 v1 RenderPlan、RenderShot、Narration/Dialogue segment、AudioPolicy 与可选 ArtDirectionRef；保持现有 DramaEpisode schema 和导出 SHA 不变。
2. 在 `drama_store` 新增 fresh render snapshot 入口，统一验证 episode/meta/角色表、Approve verdict、episode SHA、现有 input fingerprint/freshness 与单集冻结角色投影。
3. 新建纯函数 RenderPlan builder：使用现有 meta input fingerprint 作为 opaque creative revision，计算受控 creative/shot/plan fingerprint，并生成不依赖 `shot_no` 的确定性 96-bit 镜头语义 ID。
4. 将每镜非空旁白、对白按固定顺序投影为 episode 全局有序 segment；不拆句、不猜对白 speaker，空镜头使用 `audio_policy=silent`。
5. 新建严格 render store，在 `outputs/episodes/episode_NN.render_plan.json` 保存确定性 envelope；区分 `needs_render_plan/fresh/stale/invalid/blocked_source`，幂等不重写，stale 默认保留，坏 schema/坏 hash/非普通文件禁止自动覆盖。
6. 用 synthetic workspace 覆盖 episode 1/2、角色投影、镜头重排/编辑/重复、旧 workspace、坏 JSON/schema/hash、symlink、路径隔离、幂等字节和 socket 零网络；保持现有 video/export/paid ledger 行为不变。

## Acceptance

- **A106-01**：严格 RenderPlan/spoken schema 对版本、ID、枚举、episode/season、连续 segment sequence、唯一引用、数值、extra 字段与 fingerprint 进行 fail-closed 校验；现有 DramaEpisode schema、SHA 与导出不变化。
- **A106-02**：`load_fresh_episode_for_render` 只接受 schema 有效、Approve、episode SHA 一致、当前输入 fresh 且单集冻结角色投影可证明的 assembled episode；所有不一致均在 RenderPlan 写盘前失败，输入与磁盘源文件不被修改。
- **A106-03**：相同 fresh 输入产生语义与字节稳定的 RenderPlan/envelope；episode 1/2 均可生成，creative revision/fingerprint 绑定现有批准血统与本集角色，不保存 review 内文、绝对路径、provider 数据或易变时间。
- **A106-04**：镜头 ID 不依赖 `shot_no`；distinct 镜头重排保持 ID，执行字段变化只改变 source/plan fingerprint，画面核心、旁白或对白变化产生新语义 ID，重复镜头确定且无冲突。spoken segments 全局有序、legacy 回投逐字一致且不猜 speaker。
- **A106-05**：render store 对 missing/fresh/stale/invalid/blocked_source、显式 stale 替换、未知 schema、坏 JSON/hash/episode、symlink/非普通文件和 workspace/episode 隔离进行严格分类；fresh 幂等不重写，stale/invalid 文件不被静默销毁。
- **A106-06**：聚焦回归覆盖新模块、`drama_store`、iter 105 角色投影和既有 video freshness；correctness、security/boundary、schema/freshness 三视角只读审查无未处理 P0/P1。最终只运行一次 `bash scripts/verify.sh` 并通过，canonical 结论最多为 `mock-functional`，独立短剧组件仍为 `local-e2e`、`provider_validated=false`，不运行真实 provider。

## Implementation Notes

待实施时回填确定性 ID/fingerprint 的最终 canonical payload、兼容选择、聚焦测试结果、审查 findings 与范围变化。外部项目只按阶段路线图固定 commit 做 clean-room 架构参考，不复制代码、prompt、测试或独特结构。

## Acceptance Result

待 `iter-finish` 按 A106-01 至 A106-06 逐项回填。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_106_drama_render_plan_stale_boundary.md` | 建立 iter106 计划、验收 ID 与审计骨架 |
| `docs/iterations/README.md` | 追加 canonical iteration 索引 |

## 不在本轮范围

- AssetRef、场景/道具/线索库、不可变资产版本与 selected reference。
- 视觉 override 写接口/CAS、BGM/首尾帧/逐镜视频/时间线的跨产物 stale 传播。
- TimelineManifest、TTS、字幕、FFmpeg、ComfyUI、图片/视频/语音 provider 或任何真实调用。
- Web/CLI 入口、paid ledger、通用媒体任务 DAG/worker、episode 1 legacy video 迁移。
- 把稳定 UUID 写回创作 storyboard；若未来要求语义编辑后仍保持永久 ID，另立迭代修改创作层。

## Notes

- 本轮显式使用 repository-local `iter-start`；实施完成后必须使用 `iter-finish`，并仅在事实变化时就地同步 README、handoff 与 `PROJECT_HISTORY.md`。
- 用户现有的 stage plan/README 增量与两份未跟踪体检报告保持原样；体检报告不读取、不 stage、不 commit。
- 建议立项提交信息：`docs(iter106): 迭代计划 106 立项（短剧渲染计划与创作陈旧性边界）`；起轮不自动 commit、不 push。
