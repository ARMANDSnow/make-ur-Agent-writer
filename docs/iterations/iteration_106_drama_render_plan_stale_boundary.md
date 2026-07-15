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

- `FreshEpisodeSnapshot` 从 assembled episode/meta/季角色表与 setup/storyboard/review 的严格、有界、nofollow JSON 读取中建立；重新校验 Approve、episode SHA、review/input fingerprint、episode/season 身份和 1–8 人单集投影。v2 逐字保留 meta 冻结 ID 顺序；v1 只在旧 review 血统和 cast 可证明时放行。
- `shot_id` 是 `episode_no + (beat/visual/voiceover/dialogue) 语义核 + occurrence` 的 96-bit 截断 hash，不使用 `shot_no`。完全相同的重复镜头可确定投影；语义相同但执行字段不同时，由于没有创作层持久 UUID 无法证明重排对应关系，v1 显式 fail-closed。
- `RenderPlan` 与 envelope 不写 wall-clock 时间，只记录固定 `render-plan-v1` generator；creative fingerprint 覆盖 render-relevant episode、批准血统与冻结角色投影 hash，不写 review 内文、绝对路径、provider 数据或签名 URL。snapshot 在 builder 内再校验 episode/projection/verdict/fingerprint，防止 frozen dataclass 内层 dict 被原地篡改。
- render store 在 workspace 写锁中完成 inspect、source 快照、build、source/target CAS 与落盘；最终写入通过 `O_NOFOLLOW` 目录 fd 链、同目录临时文件和 atomic replace 完成。这不宣称断电级 fsync 安全。
- 聚焦回归最终为 **63 tests OK**（新 RenderPlan/store、`drama_store`、iter105 角色投影和既有 video freshness）；语法、harness 和 `git diff --check` 通过。correctness、security/boundary、schema/freshness 三视角完成多轮只读审查，重复镜头、snapshot 血统、并发 CAS、symlink/finite JSON、v1 兼容与状态分类 findings 全部修复，最终无未处理 P0–P2。
- 首次调用 canonical 入口在任何测试/pipeline 启动前，因用户已有 stage-plan README 链接与当轮索引尚处于 tracked dirty 而 fail-closed。随后将该 stage plan/README 原样纳入 `5e30ed8` 验收基线；正式全量 steps 只执行一次并通过。两份体检报告全程未读取、未 stage、未 commit。

## Acceptance Result

- **A106-01 通过**：RenderPlan/RenderShot/ArtDirectionRef/有序 spoken union 均为 strict `extra=forbid` v1 schema，严格校验版本、ID、连续 sequence、唯一引用、数值、四态 AudioPolicy 与 plan fingerprint；Dialogue speaker 只能为 `null`。现有 DramaEpisode 没有新增字段。
- **A106-02 通过**：fresh loader 对所有创作血统做 strict/bounded/nofollow 读取，要求 Approve、episode SHA、review/meta fingerprint、episode/season 身份与 1–8 人冻结投影一致。v1 episode 1 可证明 cast 兼容通过；v1 episode 2 歧义在写盘前 `blocked_source`。
- **A106-03 通过**：episode 1/2 相同 fresh 输入重复 build 的 plan/envelope/文件字节一致，fresh 幂等返回不重写；输入快照与磁盘源不被修改。creative revision 直接采用 meta input fingerprint，产物不含时钟、review 内文、provider 数据或绝对路径。
- **A106-04 通过**：distinct 镜头重排保持 ID，时长/运镜/绘图 prompt 只改 source/plan fingerprint，画面核心/旁白/对白变化产生新 ID；完全重复镜头确定且唯一，无持久 UUID 时的歧义重复显式阻断。spoken 严格按每镜“旁白→对白”全局排序，legacy 回投逐字一致且不猜 speaker。
- **A106-05 通过**：missing/fresh/stale/invalid/blocked_source、显式 stale 替换、unknown schema、bad JSON/hash、finite/deep JSON、symlink/非普通文件、workspace/episode 路径和 source/target 并发变化均有回归。invalid/stale 不会被默认覆盖，只有严格 `replace_stale=True` 才能替换合法 stale plan。
- **A106-06 通过**：socket 哨兵证明 create/inspect 零网络；聚焦 **63 tests OK**，三视角最终无未处理 P0–P2。正式 canonical `bash scripts/verify.sh` 在 accepted baseline `5e30ed82faa9e1e0d81d743aa87dd5238de9cca2` / tree `ad3f2d1462039e73e92b81af5473828d57b38e08` 上 exit 0：**2132 tests OK**、15 steps、140 秒、`tracked_scope_clean=true`、preflight **0 FATAL / 0 WARN**。
- Canonical evidence 为 schema v2 `mock-functional` / `canonical-mock-offline`；独立短剧组件仍为 `local-e2e`、`provider_validated=false`。未运行真实文本、生图、视频、FFmpeg 或 ComfyUI，不代表真供应商校准。
- 未修风险：本轮范围内无未处理 P0–P2；AssetRef/资产版本、override CAS、TimelineManifest、BGM/首尾帧 stale 传播和真媒体生成继续保留给 A2/B/E 及后续阶段。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_106_drama_render_plan_stale_boundary.md` | 建立 iter106 计划、验收 ID 与审计骨架 |
| `docs/iterations/README.md`、`docs/iterations/stage_plan_drama_full_production_pipeline.md` | 追加 canonical iteration 索引并保留/纳入 A–J 阶段计划 |
| `src/drama_schemas.py` | 新增 strict RenderPlan、RenderShot、spoken segment、AudioPolicy 与 ArtDirectionRef v1 契约 |
| `src/drama_store.py` | 新增 strict fresh render snapshot、批准血统、episode SHA 与单集角色投影守门 |
| `src/drama_render_plan.py` | 新增确定性 RenderPlan builder、镜头/segment ID 与 legacy spoken 回投 |
| `src/drama_render_store.py` | 新增五态 inspection、幂等 create/load、stale 替换、写锁/CAS 与 nofollow 原子落盘 |
| `tests/test_drama_render_plan.py`、`tests/test_drama_render_store.py`、`tests/test_drama_store.py` | 新增 schema、freshness、ID、状态机、legacy、路径/并发和零网络回归 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 就地同步实时 SOP、当前接力点与阶段级工程记忆 |

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
