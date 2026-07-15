# 短剧完整生产链阶段计划（独立路线图）

> **文档性质**：阶段性实施路线图，不是一次 iteration，不占用 `iter106` 或任何后续编号，也不代表已授权实施。未来开工时，每个候选实施单元仍须使用 `iter-start` 取得当时的下一个编号；一个阶段可以拆成多轮 iteration，也可以因风险与证据变化重新排序。
>
> **形成日期**：2026-07-14。
>
> **调研范围**：基于 ArcReel、LumenX、LocalMiniDrama、Toonflow、NarratoAI、ShortGPT、MoneyPrinterTurbo、DramAI 的固定 Git commit 做只读研究，并与本仓当前代码、测试、handoff 对照。本文中的 GitHub 链接均固定到调研 commit，避免未来主分支变化造成“文件还叫这个名字、语义已经变了”的误读。
>
> **验证边界**：本文只规划，不运行真文本、真生图、真语音或真视频，不读取 `.env`、私有原文、`data/`、`outputs/`、`logs/`。路线图中的 provider-validated 只能由未来获得逐次授权后的真实证据产生。

## 1. 执行摘要

当前项目已经完成“文本五站 → review/assembly → 单集/整季导出 → episode 1 单镜视频 → 可恢复多模态验证”的工程闭环，但距离面向创作者的完整生产链还差四块核心能力：

1. **可复用视觉资产**：角色之外还缺场景、道具/线索、统一美术方向，以及“候选版本—选中版本—被哪些镜头引用”的血统。
2. **逐镜媒体生产**：当前视频边界偏向 episode 1 高光镜兼容路径，尚未形成逐镜首帧、尾帧、视频候选、选中版本和跨镜连续性约束。
3. **声音与时间线**：缺角色级配音、旁白、原声策略、字幕、BGM/SFX、可验证时间线以及同一时间线驱动 MP4 和可编辑工程导出。
4. **生产工作台**：缺从创作分镜投影到资产、媒体任务、时间线、合成、质检的统一视图；也缺项目归档/迁移的媒体 manifest。

本路线图采用“**先做严格离线、可恢复、可验证的本地竖切，再扩大 provider/UI**”的顺序：

- 阶段 A-F 先把现有创作产物接成一条本地完整链：资产契约 → 逐镜图片/视频 → 音频时间线 → FFmpeg 合成与 QA。阶段 F 结束时，使用 mock/本地 fixture 应能产出一条结构正确、可追溯的完整 MP4；这仍是 `mock-functional` 或 `local-e2e`，不宣称真实生成质量。
- 阶段 G 再抽象通用媒体调度、provider capability、并发槽和成本估算，避免过早把 ArcReel 的通用队列复杂度搬入本仓。
- 阶段 H-I 再补长篇小说事件图、上下文记忆、画布/工作台与归档，避免 UI 或检索成为新的创作真源。
- 阶段 J 最后按“真文本、真图片、真语音、真视频”分别授权、分别取证，做 provider 校准和 capstone。

推荐的第一条实施线不是“先重写所有 job”，而是：

```text
episode_NN.json（创作真源）
  → render_plan.json（冻结的渲染计划）
  → asset/render manifests（候选、选中、SHA、血统）
  → timeline.json（画面、对白、旁白、字幕、BGM）
  → local MP4 + QA report + editable export（派生产物）
```

## 2. 当前基线与不可破坏的约束

### 2.1 已有能力

以 `docs/AGENT_HANDOFF.md` 当前快照为准，短剧已经具备：

- 五站文本 job、显式文本 revision、review 血统与 Approve 后组装。
- 连续多集、季角色库、单集冻结阵容、最多 8 人的 provider 投影边界。
- 单集 JSON/Markdown/CSV/Comfy 四种导出、严格整季母包和阶段快照。
- Insights、episode 1 视频 job、图片/视频/callback/五站授权的本地 fake-provider E2E。
- 文本、图片、视频的 crash/restart 状态矩阵，以及 `submission_unknown`、纯 poll resume、receipt/hash/fingerprint 等付费恢复边界。

### 2.2 已知缺口

- 真文本、全角色真生图、真视频只具备入口与本地证据，尚未逐类授权验证质量。
- 真图片入口目前严格 PNG；更广图片格式和 codec 尚未定义。
- episode 2+ 逐镜视频、角色配音、旁白、字幕、BGM/SFX、完整合成尚未实现。
- Comfy 目前是模板级导出，不代表真 ComfyUI workflow 已跑通。
- 当前 `src/drama_video.py` 保留单高光镜兼容职责，不适合作为整条媒体管线的唯一承载文件。

### 2.3 全阶段必须保持的项目约束

- `episode_NN.json` 继续是**创作事实真源**；媒体候选、任务状态、下载证据、时间线和合成结果不得反写成创作事实。
- 真文本、真生图、真语音、真视频是四类独立授权；一次授权不能跨媒体类型、provider、模型、预算或提交上限复用。
- 不自动重试未知付费提交。只有能证明“请求未发送”的失败才可自动重试；已拿到 provider job id 时优先纯 poll；无法确定是否提交时进入 `submission_unknown` 并等待对账/人工决策。
- `src/web/jobs.py` 保持 Web 编排与公开投影边界；内部 provider 响应、完整 prompt、签名 URL、路径和凭据不得进入公开 job。
- 默认 mock、严格离线；单测和 `verify.sh` 不得下载模型、调用 Whisper、访问 ComfyUI 或触发任何真实 provider。
- 所有媒体下载保持现有 scheme、redirect、DNS/peer IP、MIME/magic、size、hash、容器、原子落盘安全要求。
- 可选能力必须 graceful degrade，但不能把失败伪装为 production completed。可选 BGM 缺失可以标记 `completed_with_warnings`；核心视频合成失败必须 `failed`，不能复制第一段视频冒充完整成片。

## 3. 外部项目快照与许可边界

| 项目 | 调研 commit | 许可/使用边界 | 本路线图主要借鉴 |
|---|---|---|---|
| [ArcReel](https://github.com/ArcReel/ArcReel/tree/44321d055484db312877e55beb1e1e16231b59c4) | `44321d055484db312877e55beb1e1e16231b59c4` | AGPL-3.0；只做 clean-room 架构研究，不复制代码、prompt、测试、注释或独特结构 | 通用媒体队列、provider backend、并发槽、版本资产、价格、TTS、合成、剪映导出 |
| [LumenX](https://github.com/alibaba/lumenx/tree/743683387384fb1d9fff72038933e7249d416076) | `743683387384fb1d9fff72038933e7249d416076` | MIT | 资产候选/选中、剧集/系列/全局覆盖、R2V 视频任务、候选比较 UI、配音混音 |
| [LocalMiniDrama](https://github.com/xuanyustudio/LocalMiniDrama/tree/92c66dd75688d83aac3ccc31bb51378613122cbc) | `92c66dd75688d83aac3ccc31bb51378613122cbc` | MIT | 角色/场景/道具库、首尾帧绑定、逐镜视频、字幕水印合成、归档、画布投影 |
| [Toonflow](https://github.com/HBAI-Ltd/Toonflow-app/tree/bc61ec7a1b5df31293b286981a5f4ad4635464ee) | `bc61ec7a1b5df31293b286981a5f4ad4635464ee` | 仓库标 Apache-2.0，但 README 有额外商业分发/品牌条款；仅借鉴抽象，落地前单独复核 | 章节事件提取、摘要/向量/近期记忆组合、skill 工具边界 |
| [NarratoAI](https://github.com/linyqh/NarratoAI/tree/cd20aebacf4d996cfac5f50372763e2a59aedc51) | `cd20aebacf4d996cfac5f50372763e2a59aedc51` | MIT | 旁白脚本匹配、OST 策略、时间线校验、剪映草稿、成片 ASR QA |
| [ShortGPT](https://github.com/RayVentura/ShortGPT/tree/3df4e0f7a422bf7386565d498bf4521a2544c614) | `3df4e0f7a422bf7386565d498bf4521a2544c614` | MIT | 可见阶段、编辑动作模板；只借鉴体验，不采用弱恢复状态 |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo/tree/1d5fa132480ea4fddf2ae61ce46681bab4164e2f) | `1d5fa132480ea4fddf2ae61ce46681bab4164e2f` | MIT | 本地字幕/TTS/视频合成、BGM 降级；不采用“从头重跑式”阶段恢复 |
| [DramAI](https://github.com/hyyyyyyz/dramai/tree/2ec38104380823aff711c96ed852d5f713b8ac5a) | `2ec38104380823aff711c96ed852d5f713b8ac5a` | Apache-2.0 | 作为同类产品结构与术语对照，不作为第一批代码级嫁接来源 |

许可要求：

1. ArcReel 的任何落地必须用本仓术语、数据模型和测试重新设计；若未来想直接引入代码，必须先单独做 AGPL 传播范围评估，不能在普通 iteration 中顺手复制。
2. Toonflow 的 README 附加条款需在任何分发或商业化动作前重新审查；本路线图只采用“事件图/辅助记忆”的通用思想。
3. 每个未来 iteration 的 Implementation Notes 应记录参考项目、固定 commit、参考文件和 clean-room 声明。

## 4. 目标架构：三层事实与一条派生链

### 4.1 三层事实

| 层 | 权威内容 | 建议文件/模块 | 禁止事项 |
|---|---|---|---|
| 创作事实 | 核心设定、钩子、分镜语义、对白/旁白、角色、review、assembled episode | 现有 `src/drama_schemas.py`、`src/drama_store.py`、`episode_NN.json` | 不因换图、换配音或重新合成而改写创作 revision |
| 渲染事实 | 美术方向、资产版本、镜头候选、选中版本、时间线、合成参数、QA | 新 `drama_assets.py`、`drama_render_store.py`、`drama_timeline.py`、`drama_compositor.py` | 不用“目录最新文件”推断当前版本；必须显式 selected id + fingerprint + SHA |
| 执行/付费事实 | provider/model/account/endpoint、attempt、提交状态、job id、receipt、估算/实际成本 | 现有 paid ledger 语义 + 新通用 media task/backend 层 | 不以 generic `failed` 覆盖 `submission_unknown`；不泄露凭据/响应正文 |

### 4.2 派生关系

```text
CreativeEpisode
  └─ RenderPlan（冻结 episode revision、角色投影、美术方向、镜头输入）
      ├─ AssetManifest（角色/场景/道具/线索的版本与选中项）
      ├─ ShotRenderManifest（逐镜图片/视频候选与选中项）
      ├─ AudioManifest（逐句对白/旁白/BGM/SFX）
      └─ TimelineManifest（唯一时间轴）
          ├─ MP4/Web preview
          ├─ subtitles
          ├─ editable project export
          └─ MediaQAReport
```

上游任何会影响画面或声音的字段变化，都通过 fingerprint 使 RenderPlan 或下游 manifest stale；不靠删除文件触发重跑，也不自动覆盖用户已选中的候选。

### 4.3 建议目录，不作为最终实现承诺

```text
src/
  drama_assets.py
  drama_render_plan.py
  drama_render_store.py
  drama_shot_image.py
  drama_shot_video.py
  drama_audio.py
  drama_timeline.py
  drama_compositor.py
  drama_media_qa.py
  drama_edit_export.py
  drama_project_archive.py
  drama_event_graph.py
  drama_context_memory.py
  drama_media_tasks.py
  drama_media_worker.py
  drama_media_pricing.py
  drama_media_backends/
    base.py
    registry.py
    image.py
    video.py
    audio.py
```

最终路径应在对应 iteration 开工时结合当时仓库结构复核。特别是：

- 现有 `src/ai_draw_client.py` 与 `src/drama_video_client.py` 的网络安全、重定向、下载和凭据规则优先复用/包裹，不为追求统一接口重写。
- 现有 `src/drama_video.py` 继续维护 episode 1 高光兼容，新的逐镜链先旁路落地；兼容迁移完成、有测试证据后再决定是否收敛。
- `src/web/jobs.py` 只接薄适配器，不直接承担 backend registry、媒体依赖 DAG 或 FFmpeg 命令构建。

## 5. 跨阶段架构决策

### ADR-1：RenderPlan 是创作到媒体的冻结关口

新增 versioned `RenderPlan`，最少包含：

- `schema_version`、`episode_no`、`creative_revision`、`creative_fingerprint`。
- frozen cast ids/versions、art direction id/version、scene/prop/clue refs。
- 每镜 `shot_id`、源 `shot_no`、结构化画面动作、对白/旁白、目标时长、景别、运镜、transition hint。
- `source_event_ids`（阶段 H 前可空）、生成时间、生成器版本。

RenderPlan 只能由 fresh assembled episode 生成。对其手工调整只允许视觉/声音执行字段，不允许悄悄修改剧情事实；若用户要改对白、人物或事件，回到创作层产生新 revision。

参考：ArcReel 的 ordered spoken content 与 two-step review 思想；LumenX 的 `StoryboardFrame` 结构。不能照搬其类，只采用“先冻结内容，再允许视觉修订”的边界。

### ADR-2：资产使用稳定语义 ID，媒体使用不可变版本 ID

- 语义实体：`character_id`、`scene_id`、`prop_id`、`clue_id`、`shot_id`。
- 每次生成/编辑产生新的 `asset_version_id`，记录 `derived_from`、input fingerprint、provider attempt、receipt、SHA、尺寸/时长。
- `selected_version_id` 显式保存；用户选中后，不因后来生成新候选自动变化。
- episode 投影冻结“语义 ID + version ID”，从而允许季库后续增长，而旧集仍可复现。

借鉴 LumenX 的 `ImageAsset.selected_id + variants`、LocalMiniDrama 的库与 `source_id`，但补足不可变版本、hash、receipt 和冻结投影。

### ADR-3：一条有序 spoken timeline，不分散成无序数组

对白、旁白、原声片段统一进入有序 discriminated union：

- `dialogue`：角色、文本、voice profile、目标/实际时长。
- `narration`：旁白人、文本、voice profile。
- `source_audio`：保留原视频/素材原声的区间。
- `silence`：显式空白，不靠缺字段猜。

镜头层音频策略使用可读枚举 `narration_only | source_only | mixed | dialogue_only | dialogue_with_bed`，不采用 NarratoAI 的 `0/1/2` magic integer。

### ADR-4：唯一 TimelineManifest 同时驱动 MP4 与可编辑导出

不分别维护“FFmpeg 时间轴”和“剪映时间轴”。TimelineManifest 包含：

- video track segments：源 asset version、in/out、timeline start、transition。
- dialogue/narration/source audio/BGM/SFX tracks：start、duration、gain、fade。
- subtitle cues：source spoken segment、start/end、样式 token。
- canvas/output：宽高、fps、sample rate、codec profile。

MP4、SRT/ASS、剪映/其他编辑器导出都是纯派生。参考 ArcReel 的 compose/Jianying 分层、NarratoAI 的 draft builder。

### ADR-5：执行任务采用依赖 DAG，但 paid evidence 独立保留

通用任务至少区分：

```text
planned → ready → claimed → submitting → submitted → polling
                         ↘ submission_unknown
submitted/polling → downloading → validating → succeeded
任意可取消态 → cancelling → cancelled
确定终态失败 → failed
```

任务 DAG 负责“谁依赖谁”，paid ledger 负责“这次外呼到底发生了什么”。generic task state 不能替代 provider/account/endpoint/model/input/auth fingerprint、attempt receipt、same-run 证据和 artifact SHA。

### ADR-6：失败与降级必须可见

- 核心画面/声音缺失：`failed` 或 `blocked`，不得生产“看似完整”的成片。
- 明确 optional 的 BGM/SFX 缺失：可 `completed_with_warnings`，报告列出缺失项；默认不把 optional 降级扩展到对白/视频。
- preview 可允许低清或占位，但状态必须叫 `degraded_preview`，不能叫 production completed。
- FFmpeg 不可用、concat 失败或容器验证失败时 fail closed。明确拒绝 LocalMiniDrama“复制第一段视频并视为完成”的兜底。

## 6. 外部实现到本仓的文件级嫁接地图

### 6.1 ArcReel：通用媒体执行与可编辑导出

| 外部文件 | 实现要点 | 本仓嫁接点 | 取舍 |
|---|---|---|---|
| [`lib/generation_queue.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/generation_queue.py) | enqueue 时冻结 provider；claim；先持久 provider job id 再 poll；worker lease | 新 `src/drama_media_tasks.py`；`src/web/jobs.py` 仅调 client | 借状态与 lease，不复制 AGPL 实现；保留本仓更强 paid ledger |
| [`lib/db/repositories/task_repo.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/db/repositories/task_repo.py) | active-task 去重、依赖 DAG、guarded transitions、级联取消 | 本仓 JSON/原子写风格的 task store | 不因其使用 SQL 就在早期引入数据库 |
| [`lib/generation_worker.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/generation_worker.py) | provider×media capacity/slot、lease renew/takeover | 新 `src/drama_media_worker.py` | 第一版只服务 drama，避免全项目 runner 大重构 |
| [`server/services/resume_executor.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/server/services/resume_executor.py) | orphan 分类与恢复 | 对接现有 crash matrix、resume 语义 | ArcReel 的 image/audio orphan 不自动重发是正确方向；本仓继续细分 unknown submission |
| [`lib/video_backends/base.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/video_backends/base.py) | submit/poll/download 分开重试；resume 为可选 capability | 新 `drama_media_backends/base.py` | 本仓协议必须显式 `submission_unknown`，而非笼统 exception |
| [`lib/generation_queue_client.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/generation_queue_client.py) | client、wait、grace、batch specs | 新 `drama_media_queue_client.py` | Web/CLI 共用同一 client，避免平行等待逻辑 |
| [`lib/backend_assembly/assembler.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/backend_assembly/assembler.py) / [`specs.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/backend_assembly/specs.py) | 单一构造 seam，`(provider, media)` 声明映射，未知组合 loud fail | `drama_media_backends/registry.py` | 不读取 `.env`；只接已经通过 settings/preflight 的脱敏配置 |
| [`lib/config/registry.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/config/registry.py) | capability、时长、分辨率、最大参考图、pricing | 扩展 `config/models.yaml` 或独立 media capability schema | 配置加载时硬校验；不能靠前端隐藏非法选项 |
| [`lib/config/resolver.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/config/resolver.py) | payload > project > global；历史任务冻结 | attempt-frozen > render config > workspace > global mock | 已提交任务绝不能因用户改全局配置而换 provider/model |
| [`lib/pricing/types.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/pricing/types.py) / [`lookup.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/pricing/lookup.py) / [`strategies.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/pricing/strategies.py) | 按媒体/模型的估价策略 | 新 `drama_media_pricing.py`，扩展 `src/web/drama_insights.py` | 估算与 actual 分列；多币种不可悄悄相加 |
| [`lib/project_manager.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/project_manager.py) / [`lib/version_manager.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/version_manager.py) | 项目资产、候选版本、选择 | 新 `drama_render_store.py`、`drama_asset_versions.py` | `drama_store.py` 继续管创作 canonical；媒体版本独立 |
| [`lib/audio_backends/base.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/audio_backends/base.py) | TTS 协议 | 新 `drama_audio.py` 和 client | 每个 utterance 独立 attempt；合成 POST 与音频 GET 分开，下载失败不重新合成 |
| [`compose_video.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/agent_runtime_profile/.claude/skills/compose-video/scripts/compose_video.py) | probe、标准化分辨率/fps/audio/timestamps、静音补轨、xfade/cut fallback、BGM、路径守卫 | 新 `drama_compositor.py` | 用显式 argv，无 shell；先生成 filter graph 再执行；本仓重写测试 |
| [`server/services/jianying_draft_service.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/server/services/jianying_draft_service.py) / [`docs/jianying-export-guide.md`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/docs/jianying-export-guide.md) | timeline 到剪映草稿 | 新 `drama_edit_export.py` | 与 MP4 共用 TimelineManifest；导出是派生物，不是新真源 |

ArcReel 的重要修正：它并非“遇错就通用重试”。其视频链已经能在存在 job id 且 provider 支持时恢复纯 poll，TTS 也分开合成与下载；这些行为值得借鉴。但本仓当前付费证据包含 auth/input/provider/account 等更细指纹，不能被 ArcReel 的 generic task 状态降级替换。

### 6.2 LumenX：资产候选、剧集覆盖与配音

| 外部文件 | 实现要点 | 本仓嫁接点 | 注意 |
|---|---|---|---|
| [`src/apps/comic_gen/models.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/apps/comic_gen/models.py) | `ImageAsset`/`ImageVariant` selected id；`AssetUnit` 图片/视频候选；Character reference sheet/persona；Scene/Prop；StoryboardFrame 的 scene/character/prop ids、dialogue、audio note、lighting、blocking、transition | 扩展 `drama_schemas.py`；新 `drama_assets.py`、`drama_render_plan.py` | 它是 persona/base id + 候选池/作用域解析，不是完整不可变资产 DAG；本仓需补 version/hash/receipt |
| [`src/apps/comic_gen/pipeline.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/apps/comic_gen/pipeline.py) | Episode > Series > Global 资产解析；创建视频 task 时快照首帧；持久 provider id；选中候选，未 pin 时取最新 | `drama_render_store.py`、`drama_shot_video.py` | 不采用 `created_at` 最新即真源；使用 explicit selected、completed_at、fingerprint、SHA |
| [`ArtDirection.tsx`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/frontend/src/components/modules/ArtDirection.tsx) | preset/AI suggestion/custom positive/negative prompt、系列继承、覆盖确认 | Web 美术方向面板 | AI suggestion 只产生候选，不自动覆盖锁定方向 |
| [`CandidatesSection.tsx`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/frontend/src/components/modules/storyboard-r2v/shot-panel/CandidatesSection.tsx) / [`CandidateThumb.tsx`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/frontend/src/components/modules/storyboard-r2v/shot-panel/CandidateThumb.tsx) / [`CompareModal.tsx`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/frontend/src/components/modules/storyboard-r2v/shot-panel/CompareModal.tsx) | 候选缩略图、比较与选择 | 逐镜资产工作台 | UI 选择必须调用后端 guarded selection，并显示 stale/failed，不只改 DOM |
| [`src/apps/comic_gen/audio.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/apps/comic_gen/audio.py) / [`src/audio/tts.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/audio/tts.py) | dialogue+voice+instructions hash；CosyVoice/Qwen TTS；配音、Demucs、adelay/amix | `drama_audio.py`、`drama_timeline.py` | mock 不下载模型；voice identity 与文本/input hash 进入 attempt fingerprint |
| [`Timeline.tsx`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/frontend/src/components/modules/Timeline.tsx) / [`export.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/apps/comic_gen/export.py) | UI 时间线与导出壳 | 只作为信息架构反例/占位参考 | 当前 Timeline 有静态/硬编码成分，export 写 dummy bytes/TODO，SFX/BGM 也有 dummy；不能当成熟 NLE 复用 |
| [`tests/test_video_task_recovery.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/tests/test_video_task_recovery.py) | 启动时将 orphan pending/processing 归 failed | 测试恢复 UI | 本仓已有更强 resume，不能倒退为“一律失败后人工重试” |

### 6.3 LocalMiniDrama：逐镜绑定、媒体库、合成与归档

| 外部文件 | 实现要点 | 本仓嫁接点 | 取舍 |
|---|---|---|---|
| [`backend-node/migrations/01_init.sql`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/migrations/01_init.sql) | dramas/episodes/storyboards/characters/scenes/props/frame prompts/tasks/image/video/merge/library 分表 | 用于梳理实体，不直接引入数据库 | 本仓先保持 JSON + 原子写 + schema；规模证明确有瓶颈再立数据库迁移 iteration |
| [`13_character_identity_anchors.sql`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/migrations/13_character_identity_anchors.sql) / [`14_storyboard_segments_and_model_map.sql`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/migrations/14_storyboard_segments_and_model_map.sql) / [`15_storyboard_angle_structured.sql`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/migrations/15_storyboard_angle_structured.sql) | 身份锚点、style token、palette、四视图、segment、模型映射、结构化角度 | `DramaCharacter`/`CharacterSheet` 兼容扩展，RenderPlan 结构字段 | 身份锚点进入参考图/提示词投影，不在 provider 记录中保存完整 prompt |
| [`episodeStoryboardService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/episodeStoryboardService.js) | 结构化镜头、动作、对白、旁白、灯光/景深、prompt；增量 checkpoint 与 continuation | RenderPlan 构建和 staged save | 保持 `shot_id` 稳定，checkpoint 不成为创作 canonical |
| [`storyboardFrameBinding.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/storyboardFrameBinding.js) / [`tailFrameLinkService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/tailFrameLinkService.js) / [`storyboardMedia.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/frontweb/src/utils/storyboardMedia.js) | 首/尾帧绑定和相邻镜头链接 | `drama_shot_assets.py`、`drama_shot_video.py` | 绑定的是 version id；跨镜继承必须显式，不能只靠相邻文件名 |
| [`videos.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/routes/videos.js) / [`videoService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/videoService.js) | 多参考图、create/poll/resume | 通用 video backend、reference validation | provider 最大参考数来自 capability registry；冻结顺序和 SHA |
| [`characterLibraryService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/characterLibraryService.js) / [`sceneLibraryService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/sceneLibraryService.js) / [`propLibraryService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/propLibraryService.js) | 可复用角色/场景/道具快照 | `drama_assets.py` | 本仓加 `asset_version`、`content_hash`、`derived_from` 和 episode 冻结引用 |
| [`ttsService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/ttsService.js) / [`audio.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/routes/audio.js) | TTS 路由和服务 | 仅参考调用分层 | **明确不复制**：该实现会记录 text/voice/api_key/base_url，违反本仓凭据和 prompt 日志边界 |
| [`videoMergeService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/videoMergeService.js) / [`mergedEpisodePostProcess.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/mergedEpisodePostProcess.js) | concat、对白/旁白时槽、SRT、字幕/水印、mux | `drama_compositor.py` | 借步骤，不借失败兜底；FFmpeg 缺失/concat 失败时不能复制首 clip 标完成 |
| [`dramaExportService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/dramaExportService.js) / [`dramaImportService.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/backend-node/src/services/dramaImportService.js) | 项目归档/导入 | `drama_project_archive.py` | manifest 加全量 hash、schema version、选中资产、任务/receipt 与交付物分区 |
| [`dramaCanvasAdapter.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/frontweb/src/utils/dramaCanvasAdapter.js) / [`useCanvasCrud.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/frontweb/src/composables/useCanvasCrud.js) / [`useCanvasWorkflowRunner.js`](https://github.com/xuanyustudio/LocalMiniDrama/blob/92c66dd75688d83aac3ccc31bb51378613122cbc/frontweb/src/composables/useCanvasWorkflowRunner.js) | 从后端数据投影画布、CRUD、workflow runner | 阶段 I 工作台 | 画布只做 projection；执行与依赖真源仍在后端 task/render store |

### 6.4 Toonflow：小说事件图与辅助记忆

| 外部文件 | 实现要点 | 本仓嫁接点 | 取舍 |
|---|---|---|---|
| [`src/utils/cleanNovel.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/utils/cleanNovel.ts) / [`generateEvents.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/routes/novel/event/generateEvents.ts) | 分章并发提取 event summary | 新 `drama_event_graph.py` | 主实现是自由文本事件摘要，不应描述成成熟因果图；本仓必须 typed schema + source hash |
| [`src/agents/scriptAgent/tools.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/agents/scriptAgent/tools.ts) | `get_novel_events` 拼接已有 event | RenderPlan/source event projection | 事件图只供选材/一致性，不自动修改 episode |
| [`src/utils/agent/memory.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/utils/agent/memory.ts) / [`embedding.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/utils/agent/embedding.ts) | 最近消息 + 周期摘要 + 向量 top-k；摘要再展开；本地 ONNX embedding | 可选 `drama_context_memory.py` | 辅助 cache，记录 project/season/episode/event/source hash 与 invalidation；不是 canonical，mock 不下载模型 |
| [`src/agents/scriptAgent/index.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/agents/scriptAgent/index.ts) / [`skillsTools.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/utils/agent/skillsTools.ts) | script agent 与受控 skill tools | `config/drama_skills/*.md`，skill hash 进入 input fingerprint | 媒体执行仍是固定工具，不让 agent 直接构造网络请求 |
| [`updateCode.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/routes/setting/vendorConfig/updateCode.ts) / [`vm.ts`](https://github.com/HBAI-Ltd/Toonflow-app/blob/bc61ec7a1b5df31293b286981a5f4ad4635464ee/src/utils/vm.ts) | 动态转换/执行用户 provider TypeScript，暴露网络/SDK | 无嫁接 | **明确拒绝** provider 热加载和无界 VM；本仓只允许代码内注册、审查过的 backend |

### 6.5 NarratoAI、ShortGPT、MoneyPrinterTurbo：时间线、校验与阶段体验

| 外部文件 | 实现要点 | 本仓嫁接点 | 取舍 |
|---|---|---|---|
| NarratoAI [`script_settings.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/webui/components/script_settings.py) | 先生成可编辑旁白，再匹配/编辑 script table | `episode_NN.render.json`/RenderPlan review UI | 批准的是渲染计划，不改变创作 canonical |
| NarratoAI [`script_matching.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/app/services/prompts/short_drama_narration/script_matching.py) / [`clip_video.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/app/services/clip_video.py) | source timestamp、overlap、OST 0/1/2 | `ShotTimelineItem`/`AudioPolicy` | 改用 typed enum，不用 magic integer |
| NarratoAI [`short_drama_narration_validation.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/app/services/short_drama_narration_validation.py) | 时间戳、边界、字幕命中、非重叠、旁白密度、hook、连续 source-only、bridge | `drama_timeline.py` 的纯本地 validator | 上游 UI 未完整强制 validator，本仓必须在合成前 gate |
| NarratoAI [`jianying_task.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/app/services/jianying_task.py) / [`jianying_draft_builder.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/app/services/jianying_draft_builder.py) | source ranges、tracks/materials/segments/subtitles、时长 clamp | `drama_edit_export.py` | 版本化派生 exporter；不把编辑器私有格式变成内部 schema |
| ShortGPT [`abstract_content_engine.py`](https://github.com/RayVentura/ShortGPT/blob/3df4e0f7a422bf7386565d498bf4521a2544c614/shortGPT/engine/abstract_content_engine.py) / [`content_short_engine.py`](https://github.com/RayVentura/ShortGPT/blob/3df4e0f7a422bf7386565d498bf4521a2544c614/shortGPT/engine/content_short_engine.py) | `last_completed_step`、12 个可见阶段 | Web 进度标签 | ordinal 恢复太弱；只借用户可理解的阶段名，不借状态真源 |
| ShortGPT [`editing_engine.py`](https://github.com/RayVentura/ShortGPT/blob/3df4e0f7a422bf7386565d498bf4521a2544c614/shortGPT/editing_framework/editing_engine.py) | JSON action 模板驱动 caption/background/music | typed timeline action | 使用 Pydantic discriminated union 和路径白名单，不接受任意 action/命令 |
| MoneyPrinterTurbo [`app/services/task.py`](https://github.com/harry0703/MoneyPrinterTurbo/blob/1d5fa132480ea4fddf2ae61ce46681bab4164e2f/app/services/task.py) | stop_at 分阶段执行 | Web/CLI stage selection | 其恢复更接近重新开始；本仓 reuse 需检查 fingerprint/provider/auth/artifact/receipt |
| MoneyPrinterTurbo [`app/services/video.py`](https://github.com/harry0703/MoneyPrinterTurbo/blob/1d5fa132480ea4fddf2ae61ce46681bab4164e2f/app/services/video.py) | BGM 失败后保留 narration-only 并警告 | compositor optional policy | 仅当 BGM 明确 optional 才降级；告警进入交付报告和 UI |

## 7. 阶段总览与依赖

| 阶段 | 目标 | 主要结果 | 依赖 | 建议拆分 |
|---|---|---|---|---|
| A | 固化渲染契约 | RenderPlan、asset/timeline schema、stale 规则 | 当前 assembled episode | 1-2 轮 |
| B | 建立视觉资产圣经 | 角色/场景/道具/线索、美术方向、版本/选择/引用 | A | 2-3 轮 |
| C | 逐镜图片生产 | 首帧/尾帧、候选/比较/选择、跨镜绑定 | A-B | 2-3 轮 |
| D | 逐镜视频生产 | I2V/R2V、多引用、逐镜恢复、连续性 | C | 2-3 轮 |
| E | 声音与唯一时间线 | 角色配音、旁白、字幕、BGM/SFX、timeline validation | A，可与 C-D 部分并行 | 2-4 轮 |
| F | 合成、QA、可编辑导出 | 本地完整 MP4、SRT/ASS、QA、剪映类导出 | C-E | 2-3 轮 |
| G | 通用媒体调度与成本 | backend registry、依赖 DAG、并发槽、pricing/Insights | C-F 的真实重复模式 | 3-5 轮 |
| H | 小说事件图与辅助记忆 | typed event graph、来源边界、可失效检索 | A；不阻塞本地 MP4 | 2-4 轮 |
| I | 生产工作台与归档 | 画布/列表双视图、资产/任务/时间线统一投影、可移植归档 | B-G | 3-5 轮 |
| J | provider 校准与 capstone | 四类独立授权、真实证据、质量人工评审 | A-I 中对应链已 mock/local 验证 | 多轮、逐次授权 |

阶段字母不是 iteration 编号；不预留任何编号。

## 8. 阶段 A：渲染契约与 stale 边界

### 目标

在不调用任何媒体 provider 的前提下，把 `episode_NN.json` 确定性投影为 versioned RenderPlan，并定义之后所有资产、任务、时间线的血统。

### 候选本仓改动

- 修改 `src/drama_schemas.py`：新增 `RenderPlan`、`RenderShot`、`SpokenSegment`、`ArtDirectionRef`、`AssetRef`、`AudioPolicy` 的 schema；保持已有字段向后兼容。
- 新建 `src/drama_render_plan.py`：纯函数 `build_render_plan(episode, character_projection, art_direction)` 和 validator。
- 新建 `src/drama_render_store.py`：原子写、schema migration 入口、fingerprint/stale 判断，不访问网络。
- 修改 `src/drama_store.py`：只暴露 fresh assembled episode/character projection 给 builder，不承担媒体状态。
- 新建 `tests/test_drama_render_plan.py`、`tests/test_drama_render_store.py`。

### 具体实现步骤

1. 先写 schema 与 canonical JSON fixture，定义 stable `shot_id`；不能只用会因排序变化的 `shot_no` 当永久 ID。
2. 将现有 storyboard 对白/旁白归一成有序 `spoken_segments`，保留到旧字段的兼容投影。
3. 计算 `creative_fingerprint`：assembled episode schema projection + review/revision + frozen cast projection；拒绝完整 prompt 或本地绝对路径进入 fingerprint input dump。
4. RenderPlan 记录生成器版本和输入摘要；相同输入重复生成字节稳定。
5. 定义视觉-only override 白名单，例如 camera、lighting、negative prompt、transition；剧情、对白、参与角色变化必须回创作层。
6. 定义 stale 传播表并写测试：创作 revision → 全下游 stale；只换 BGM → video assets 不 stale、timeline/composite stale；只换某镜选中首帧 → 该镜视频与整集 composite stale。

### 参考文件

- ArcReel [`lib/script_models.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/lib/script_models.py)：有序 spoken content 与两阶段 review 的结构思路。
- LumenX [`models.py`](https://github.com/alibaba/lumenx/blob/743683387384fb1d9fff72038933e7249d416076/src/apps/comic_gen/models.py)：StoryboardFrame 的结构字段。
- NarratoAI [`script_settings.py`](https://github.com/linyqh/NarratoAI/blob/cd20aebacf4d996cfac5f50372763e2a59aedc51/webui/components/script_settings.py)：先审阅渲染脚本/表格再生产媒体的 UX。

### 验收门槛

- 对现有 episode 1 fixture 生成稳定 RenderPlan；重复运行无 diff。
- 任一 creative input 漂移都使计划 stale；无关字段变化不误伤全部媒体。
- 旧 workspace 缺新字段时可读并明确标记 `needs_render_plan`，不崩溃、不伪造 fresh。
- 全程 mock/纯本地，socket 哨兵证明零网络。

### 不在本阶段

不生成图片/视频/音频，不改现有 episode 1 视频成功路径，不做通用队列。

## 9. 阶段 B：视觉资产圣经与版本血统

### 目标

把当前季角色库扩展为“角色 + 场景 + 道具/线索 + 美术方向”的可复用资产体系，同时保证旧集引用可冻结、候选可比较、用户选择不被新生成覆盖。

### 候选本仓改动

- 新建 `src/drama_assets.py`：`CharacterAsset`、`SceneAsset`、`PropOrClueAsset`、`ArtDirection`、identity anchors。
- 新建 `src/drama_asset_versions.py`：不可变版本、derived_from、selected version、引用查询。
- 扩展 `src/drama_render_store.py`：asset manifest 与 episode projection。
- Web 新增资产总览和单资产候选选择；角色页保持兼容。
- 测试：`test_drama_assets.py`、`test_drama_asset_versions.py`、`test_drama_asset_projection.py`、路径/公开投影安全测试。

### 数据契约

每个语义资产至少包含：

- stable id、kind、display name、scope（global/series/episode）。
- structured identity/style fields；场景的时间/天气/空间锚点；道具/线索的 owner/state/first_seen/source_event_ids。
- immutable versions；每版有 source revision、input fingerprint、artifact metadata、SHA、provider attempt ref。
- selected version；episode frozen reference；used_by shot ids。

覆盖顺序采用 `Episode > Series > Global`，但 resolution 结果写入 RenderPlan，不在每次渲染时动态重算。

### 实施步骤

1. 先定义迁移：已有 `season_01.json` 角色不改 ID，生成 asset version 1；无图片时版本仍可只含结构/提示词，但不可伪造 artifact。
2. 增加 SceneSheet 和 PropOrClueSheet；线索与普通道具共 schema、用 `kind` 区分，便于状态演化。
3. 增加 ArtDirection 的 preset、positive/negative tokens、palette、aspect ratio、继承/override；AI 推荐仅入候选。
4. 实现 selected version 的 compare-and-set：请求带当前 selection revision，防两个页面静默互相覆盖。
5. 建 used-by 反向索引和 stale propagation；替换角色版本时列出受影响镜头，用户确认后才切换。
6. 公开 API 只返回受控 metadata 和本地安全 asset URL，不返回 provider response/prompt/签名 URL。

### 参考文件

- LumenX `models.py`、`pipeline.py` 和候选比较 UI（见 6.2）。
- LocalMiniDrama 的 character/scene/prop library 与 identity anchor migrations（见 6.3）。
- ArcReel `project_manager.py`、`version_manager.py` 和 asset types（见 6.1）。

### 验收门槛

- 旧季角色库无损迁移；episode 1 frozen cast 仍保持原 8 人边界。
- 新候选完成后不自动替换 selected version；选中后引用可复现。
- 删除被引用版本 fail closed；允许“隐藏/停用”，不物理破坏旧集。
- 场景、道具、线索可从 RenderPlan 引用，source hash 变化正确 stale。
- 资产 URL 路径穿越、非法 id、软链接、越界文件均被拒绝。

## 10. 阶段 C：逐镜图片、首尾帧与候选选择

### 目标

从当前“角色参考图 + 高光镜视频”扩展为每个镜头都有可审计的首帧/可选尾帧图片候选，并支持人物/场景/道具参考图冻结和跨镜连续性。

### 候选本仓改动

- 新建 `src/drama_shot_image.py`：逐镜 image spec、reference assembly、attempt adapter。
- 扩展 `src/drama_render_store.py`：`ShotImageCandidate`、first/tail binding、selection。
- 包裹现有 `src/ai_draw_client.py`，不重写其网络安全。
- Web 增加镜头候选、两图对比、设为首帧/尾帧、stale 和失败原因的安全投影。
- 测试：reference 顺序/上限、候选 selection、输入漂移、下载校验、crash/resume、旧高光兼容。

### 实施步骤

1. 纯函数构建每镜 image request spec：美术方向 + scene/character/prop selected versions + shot visual fields。
2. 所有 reference 记录 `asset_version_id + sha256 + role + order`；provider capability 决定最大数，超限时由确定性优先级裁剪并告警，不让 LLM 临时决定。
3. 图片生成继续沿用现有 paid attempt 语义；下载后进行 MIME/magic、尺寸、SHA、原子落盘，再标 candidate ready。
4. 首帧/尾帧是显式 binding；尾帧可以为空，不从目录里猜。下一镜可显式继承上一镜尾帧，记录 lineage。
5. 候选选择使用 version/revision guard；用户已选中的旧图即使生成了新图也不变。
6. 阶段末提供 mock/local fixture 的整集首帧覆盖率报告。

### 参考文件

- LumenX `pipeline.py` 创建视频任务时快照首帧、`CandidatesSection.tsx`/`CompareModal.tsx`。
- LocalMiniDrama `storyboardFrameBinding.js`、`tailFrameLinkService.js`、`storyboardMedia.js`。
- ArcReel image backend/queue 的 task id、resume 与版本资产设计。

### 验收门槛

- episode fixture 的全部镜头都能在零网络下得到 mock candidate 和显式 selection。
- 单镜重新生成只使该镜及依赖视频 stale，不改其他镜头选择。
- reference 超 provider 上限时 deterministic、可解释、可测试。
- crash 发生在 submit 前、response loss、provider id 持久后、下载中、下载后落账前等窗口时，遵守现有 paid state matrix。
- 现有 episode 1 高光路径回归通过。

## 11. 阶段 D：逐镜视频与跨镜连续性

### 目标

支持所有镜头的 image-to-video/reference-to-video 任务、候选与选择，并把首尾帧、参考图、目标时长和 provider capability 冻结到 attempt。

### 候选本仓改动

- 新建 `src/drama_shot_video.py`：逐镜 video spec 和 orchestration。
- 新建/扩展 `drama_media_backends/video.py`：submit/poll/download/validate 分层。
- 保留 `src/drama_video.py` 的兼容入口，以 adapter 调新链或并行验证后再迁移。
- 扩展 Web 镜头面板：生成、poll、取消、候选播放/选择、continuity warning。
- 测试：I2V/R2V capability、多参考、duration/resolution、提交未知、纯 poll、下载恢复、selection/stale。

### 实施步骤

1. `ShotVideoSpec` 冻结 provider/model、duration、resolution、first/tail frame version、reference list、prompt fingerprint。
2. backend 声明 capabilities：是否异步、是否支持 resume、最大 refs、duration set、resolution、首尾帧、费用单位。
3. submit 成功后先 durable 写 provider job id/receipt，再进入 poll；poll 不重新组装请求。
4. response loss 或无法确认提交时沿用 `submission_unknown`，禁止自动创建第二个视频。
5. download 可重试但不能导致重新 submit；下载后校验容器、时长、分辨率、是否含音轨，记录 artifact SHA。
6. 连续性检查先用确定性规则：相邻镜头角色版本/场景版本、首尾帧绑定、方向性 metadata；视觉相似度/模型评分放后续可选能力。
7. 整集 coverage gate：所有 required shots 有选中且 fresh 的视频，才进入阶段 F；placeholder 只能进入 `degraded_preview`。

### 参考文件

- ArcReel `video_backends/base.py`、`generation_worker.py`、`resume_executor.py`。
- LumenX `pipeline.py` 的 VideoTask、首帧快照、provider id 与 selection。
- LocalMiniDrama `videos.js`/`videoService.js` 的多参考与 poll resume。

### 验收门槛

- mock/local provider 对多镜头完成 create/poll/download，resume 后成功任务零网络。
- 同一个 submitted attempt 的 mode/provider 配置漂移不会被 mock 或新配置覆盖。
- 任一 required shot stale/failed 时 production compose blocked，并列出 shot ids。
- episode 2+ 的 shot id、asset projection、task path 无 episode 1 字面量泄漏。

## 12. 阶段 E：角色配音、旁白、字幕与唯一时间线

### 目标

建立角色级 voice profile、逐句 TTS attempt、原声/对白/旁白策略和唯一 TimelineManifest；在没有真实 TTS 的 mock 环境也能生成可验证的静音/测试音频 fixture。

### 候选本仓改动

- 新建 `src/drama_audio.py`、`src/drama_audio_client.py`：voice profile、utterance spec、TTS submit/download。
- 新建 `src/drama_timeline.py`：timeline builder、validator、subtitle cues、duration reconciliation。
- 扩展 `drama_schemas.py`：spoken discriminated union、AudioPolicy、TimelineManifest。
- 新建测试 `test_drama_audio.py`、`test_drama_timeline.py`、`test_drama_subtitles.py`、paid crash matrix 扩展。

### 实施步骤

1. 给角色/旁白分配稳定 voice profile id；voice/provider/model/instructions 变化进入 utterance input fingerprint。
2. 每个 spoken segment 是独立 attempt，允许单句重配；相同 text+voice+instructions+provider fingerprint 可安全 reuse。
3. TTS synthesis POST 与音频文件 GET 分开记账；下载失败只重下，不再次合成。
4. 通过实际音频 probe 获取 duration，不信 provider 文本字段；若台词超镜头时长，默认 blocked/warning，由用户选择延长镜头、加速、重写或分句，不静默截断。
5. 构建 TimelineManifest；实现 non-overlap、bounds、密度、hook、连续 source-only、bridge、字幕 cue 规则。
6. BGM/SFX 独立 track 和 optional policy；第一版允许用户提供本地安全文件或 mock fixture，不做 AI SFX 真实调用。
7. subtitle 从 spoken segment 派生，稳定绑定 segment id；人工改字幕产生 subtitle revision，不反写台词。

### 参考文件

- ArcReel `audio_backends/base.py` 以及 generation task/media generator 的 utterance 任务分层。
- LumenX `audio.py`、`tts.py` 和 dubbing/adelay/amix 管线。
- NarratoAI `script_matching.py`、`clip_video.py`、`short_drama_narration_validation.py`。
- LocalMiniDrama 音频接口只参考分层，明确不复制其凭据日志行为。

### 验收门槛

- mock episode 全部 spoken segments 生成合法音频 manifest，单句重配不重跑其他句。
- TTS response-loss、provider id/receipt 持久、下载中断、落盘后 crash 均有状态矩阵。
- Timeline validator 对 overlap、越界、负时长、NaN/Inf、bool 冒充数值、台词超镜头、字幕空/超长 fail closed。
- 无 BGM 时按 policy 产出 warning 或 blocked，状态明确。

## 13. 阶段 F：FFmpeg 合成、媒体 QA 与可编辑导出

### 目标

用阶段 C-E 的 selected assets 与 TimelineManifest 在本地确定性生成完整竖屏 MP4、字幕和可编辑工程；在合成前后做结构 QA，不把降级预览冒充生产成片。

### 候选本仓改动

- 新建 `src/drama_compositor.py`：probe、normalize、filter graph、concat/transition、mix、subtitle、watermark、mux。
- 新建 `src/drama_media_qa.py`：容器/轨道/时长/分辨率/fps/响度/黑帧或静音基础检查；ASR 为可选 provider，不进入默认验证。
- 新建 `src/drama_edit_export.py`：TimelineManifest → 剪映类草稿/通用 EDL/manifest。
- Web 增加 compose job、QA report、download/export；job 公开字段受控。
- 测试：filter graph snapshot、argv/path guards、缺音轨补静音、xfade fallback、字幕/水印、失败/降级、导出 round-trip schema。

### 实施步骤

1. 先做 `build_compose_plan()` 纯函数：输入 manifest，输出显式 ffprobe/ffmpeg argv 和 filter graph；不执行 shell 字符串。
2. 所有 clip 先 probe 并标准化分辨率、SAR、fps、time base、pix fmt、音频 sample rate/layout。
3. 无音轨视频按策略补静音；转场不支持时可回退 cut，但写 warning；核心 concat/mux 失败则 failed。
4. 音频按 timeline 使用 delay/trim/fade/amix，控制峰值/响度；字幕从同一 cue 导出 SRT/ASS 并烧录或外挂。
5. 合成后重新 probe：总时长容差、画面规格、音轨存在、文件 magic、SHA；QA 报告绑定 timeline fingerprint 和 output SHA。
6. 编辑器导出只消费 TimelineManifest；记录 exporter schema/version，不暴露绝对路径，归档时转换为包内相对路径。
7. 可选做 ASR 对齐检查，但默认 mock 绝不下载 Whisper；真实 ASR 属于独立授权/依赖评审。

### 参考文件

- ArcReel `compose_video.py`、`jianying_draft_service.py`、Jianying guide。
- LocalMiniDrama `videoMergeService.js`、`mergedEpisodePostProcess.js`。
- NarratoAI `jianying_task.py`、`jianying_draft_builder.py` 和最终 ASR/normalizer 思路。
- MoneyPrinterTurbo `video.py` 的 BGM warning 降级。

### 验收门槛

- 使用仓库合成 fixture 在严格离线环境生成完整、可 probe 的竖屏 MP4；全部 required shots 出现在时间线。
- MP4、字幕、编辑器导出共享同一 timeline fingerprint，时长在规定容差内。
- 路径穿越、软链接越界、任意命令/action 注入被拒绝；无 shell=True。
- FFmpeg 缺失、concat 失败、任一 required clip 丢失不会返回 completed。
- QA report 明确 `mock-functional`/`local-e2e`，不宣称 provider 质量。

阶段 F 是第一个产品级里程碑：**在不引入通用队列大重构的前提下，本地完整 MP4 竖切成立**。

## 14. 阶段 G：通用媒体调度、能力注册与成本

### 目标

当图片、视频、音频、合成已经出现稳定重复模式后，再抽象通用 task DAG、worker lease、provider×media 并发槽、capability registry 和 pricing。

### 候选本仓改动

- 新 `drama_media_tasks.py`、`drama_media_worker.py`、`drama_media_queue_client.py`。
- 新 `drama_media_backends/base.py`、`registry.py` 和 image/video/audio adapter。
- 新 `drama_media_pricing.py`；扩展 `config/models.yaml`、settings/preflight、`src/web/drama_insights.py`。
- `src/web/jobs.py` 用 adapter 调用，不搬入 backend 内部字段。

### 实施步骤

1. 从 C-F 的真实 task schema 提取公共最小字段；不要预先设计万能任务。
2. 定义 DAG dependency、active dedupe key、guarded transition 和 cancellation cascade；创作 job 与媒体 job 仍可分域。
3. 实现 worker lease/heartbeat/takeover；同 workspace 写操作继续服从项目锁，provider poll 可在安全边界内并发。
4. 配置 provider×media capacity；图片、视频、音频分 lane，避免视频长 poll 阻塞图片下载。
5. backend registry 在代码中声明；未知 `(provider, media, model)` loud fail；禁止动态执行用户代码。
6. attempt 配置冻结顺序：attempt > RenderPlan > workspace > global mock；submitted 后永远不重解析。
7. pricing 区分 estimate/authorized/reserved/actual/refunded/unknown；多币种分别汇总。
8. Insights 增加按 episode/shot/media/provider/model 的成功率、等待时间、实际/估算成本、unknown submission 数量。

### 参考文件

ArcReel 6.1 中 queue/task repo/worker/backend assembly/config/pricing/cost estimation 全套文件，以及其相应测试：

- [`tests/test_generation_worker_module.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/tests/test_generation_worker_module.py)
- [`tests/test_generation_queue.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/tests/test_generation_queue.py)
- [`tests/test_backend_assembly_specs.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/tests/test_backend_assembly_specs.py)
- [`tests/test_pricing_strategies.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/tests/test_pricing_strategies.py)
- [`tests/test_cost_estimation_service.py`](https://github.com/ArcReel/ArcReel/blob/44321d055484db312877e55beb1e1e16231b59c4/tests/test_cost_estimation_service.py)

这些测试只作为行为清单，不复制实现或测试文本。

### 验收门槛

- 多进程 claim 不重复；lease 过期可安全 takeover；active dedupe 不吞掉合法新 revision。
- submit/poll/download/validate retry policy 独立，unknown submission 零自动重发。
- 旧 C-F adapter 迁移前后 artifact/receipt/fingerprint 语义不变。
- Web 只见安全投影；取消和恢复刷新后仍以持久状态为准。
- estimate 与 actual 差异可审计，unknown 不被当 0 元。

## 15. 阶段 H：小说事件图、来源边界与辅助记忆

### 目标

把小说到短剧改编从“章节自由文本摘要”升级为 typed event graph，支持选集、合并、改编和防剧透来源审计；辅助记忆只做可失效 cache，不成为创作真源。

### 候选本仓改动

- 新 `src/drama_event_graph.py`：`DramaSourceEvent`、因果/前置/结果、参与者/场景/线索、source chapter ids/hash、spoiler boundary。
- 复用/投影现有 novel entity graph 与 entity advance 的概念，不直接耦合内部对象。
- 新可选 `src/drama_context_memory.py`：recent + summary + retrieval；无 embedding 时 graceful degrade。
- RenderPlan/episode meta 加 `source_event_ids` 和 graph fingerprint。

### 数据契约

`DramaSourceEvent` 至少包含：

- `event_id`、`source_chapter_ids`、`source_hash`、`spoiler_boundary`。
- participants、scene ids、prop/clue ids。
- preconditions、effects、causal parents、chronology order。
- adaptation status：selected/merged/omitted/invented；invented 必须显式，不冒充原文事件。

### 实施步骤

1. 先用 synthetic chapter/event fixture 写纯 schema、merge/split 和 boundary 测试，不读取私有原文。
2. 从现有实体/关系/章节摘要构建最小 graph adapter；无法确定因果时标 `unknown`，不让模型猜成事实。
3. episode planning 只引用 event ids；实际文本仍经当前五站创作与 review。
4. context memory 每条记录绑定 project/season/episode/event/source hash；上游变化自动失效。
5. 若使用本地 embedding，必须显式安装/缓存流程且默认测试禁下载；无模型时退化为 recent/summary/keyword。
6. skill/prompt 文件纳入版本 hash，确保不同改编策略导致下游计划 stale。

### 参考文件

- Toonflow `cleanNovel.ts`、`generateEvents.ts`、`scriptAgent/tools.ts`、`memory.ts`、`embedding.ts`。
- 本仓现有 entity graph、entity advance、start-aware ingest 和 knowledge view 约束。

### 验收门槛

- synthetic 多章事件图可稳定 build/merge/split；来源章节和 spoiler boundary 可追溯。
- 超出允许章节的 event 在 planning/render 前 fail closed。
- memory cache 删除或失效不影响 canonical 可读性；无 embedding 零网络跑通。
- invented event 与 source-derived event 在 UI/导出中明确区分。

## 16. 阶段 I：生产工作台、画布投影与项目归档

### 目标

提供创作者可操作的完整生产工作台：资产、镜头候选、任务、时间线、QA 和导出在一处可见；画布只是同一后端事实的另一种投影。项目可归档、迁移和校验。

### 候选本仓改动

- Web 新增 production workbench；列表/镜头条为默认，画布为可选视图。
- 后端提供 render/task/timeline 的安全聚合投影，避免前端拼多个内部文件。
- 新 `src/drama_project_archive.py`：manifest、hash、schema versions、相对路径、导入 preflight。
- 扩展 Insights：coverage、stale、failed/unknown、成本、QA warnings。

### 工作台信息架构

1. 顶部：creative revision、RenderPlan fresh/stale、整集 coverage、预算/授权摘要。
2. 左侧：角色/场景/道具/线索与 selected versions。
3. 主区：shot list/board，每镜首尾帧、视频候选、spoken segments、状态。
4. 底部：唯一 timeline、字幕、BGM、warnings。
5. 侧栏：任务 DAG、失败/恢复动作、receipt/cost 的安全摘要。

画布节点只能引用稳定后端 id；连线修改通过 typed API 更新 dependency/binding。前端不得自行把“节点变绿”当任务成功。

### 归档格式

- `manifest.json`：archive schema、project/season/episodes、creative/render/timeline fingerprints。
- `creative/`：允许交付的 assembled/schema 投影，不含私有原文、完整 prompt、review 内部文本。
- `assets/`：选中且被引用的 artifact；可选包含候选，清楚标注。
- `media/`：音视频、字幕、成片、编辑器导出。
- `evidence/`：脱敏 task/receipt/QA summary；不含 key、签名 URL、provider raw body。
- 每个 member 的 SHA、size、MIME；导入先校验再原子安装，不覆盖现有 workspace。

### 参考文件

- LocalMiniDrama 的 canvas adapter/CRUD/workflow runner 与 export/import services。
- LumenX 的候选/比较 UI 与 episode/series/global 覆盖确认。
- ArcReel 的 project/version manager 和 task projection。

### 验收门槛

- 列表与画布展示同一 selected/stale/task state；刷新和跨进程恢复一致。
- 所有 mutation 有 workspace lock、revision guard、路径校验和审计字段。
- archive export → 新 synthetic workspace import → hash/selection/timeline/MP4 一致。
- 导入拒绝路径穿越、重复 member、超尺寸、坏 hash、未知 schema；不信压缩包内绝对路径。
- 默认归档不包含 provider raw response、完整 prompt、签名 URL、私有原文或 `.env`。

## 17. 阶段 J：真实 provider 校准与 capstone

### 目标

在前述每一条本地链已经通过 mock/local E2E 后，逐类授权验证真实 provider 的兼容性、恢复证据、成本和人工质量；不把“API 成功”自动视为“作品质量通过”。

### 四类独立授权轨道

1. 真文本：五站/事件图/渲染计划的 schema、质量与 token/cost。
2. 真图片：角色、场景、道具、逐镜首尾帧；格式、尺寸、参考一致性、下载安全。
3. 真语音：角色 voice consistency、中文读音、时长、下载恢复、费用。
4. 真视频：I2V/R2V、参考图上限、时长/分辨率、submit/poll/download、跨镜一致性。

每次授权计划必须写清 provider/model、endpoint/account fingerprint、最大提交数、预算、单次 timeout、允许的重试类型、operator 对账步骤和终止条件。

### 校准顺序

1. preflight only：capability/config/预算/路径/素材验证，零提交。
2. 单资产最小 smoke：一个角色/场景/utterance/shot，验证格式与 paid ledger。
3. 单镜闭环：首帧 → 视频 → 配音/字幕 → compose。
4. 单集小规模闭环：限制镜头/候选数，验证恢复和成本。
5. 多集 capstone：角色/场景跨集冻结与增长、episode 2+、归档。

### 验收结论用语

- `safe-blocked`：未授权或 preflight 阻断。
- `mock-functional`：纯 mock schema/流程通过。
- `local-e2e`：本地 fake provider/真实 FFmpeg 组件闭环，无外部付费模型。
- `provider-validated`：明确 provider/model/媒体类型和证据范围；不能泛化成所有 provider 或质量。
- 人工质量评审单独记录：角色一致性、镜头可用性、口型/语音、节奏、字幕、成片观感。工程成功不自动给质量打通过。

## 18. 跨阶段验收矩阵

| 能力 | 单元/纯函数 | mock-functional | local-e2e | provider-validated |
|---|---|---|---|---|
| RenderPlan/stale | schema、fingerprint、迁移 | synthetic episode 全链 | 不需要外部 provider | 不适用 |
| 资产版本/选择 | immutable version、CAS selection | mock candidates | 本地文件/HTTP fake provider | 按图片 provider 取证 |
| 逐镜图片 | request/reference/validate | mock placeholder/fixture | fake submit/download/crash matrix | 真图片逐次授权 |
| 逐镜视频 | spec/capability/state | mock task | fake create/poll/download/resume | 真视频单次提交规则 |
| TTS/音频 | utterance hash/timeline | mock WAV fixture | fake synth/download/resume | 真语音独立授权 |
| 合成 | compose plan/filter graph | argv snapshot | 本地 FFmpeg 产 MP4/QA | 不等于生成 provider 质量 |
| 编辑器导出 | timeline projection | schema fixture | 可导入性若有本地工具则验证 | 目标编辑器版本限定 |
| 队列/worker | transition/DAG/lease | 多进程 synthetic | fake provider 并发/接管 | provider rate limit 校准 |
| 事件图/记忆 | typed graph/invalidation | synthetic chapters | 可选本地 embedding，不下载 | 真文本另授权 |
| 归档 | manifest/hash/path guards | export/import fixture | 新 workspace round trip | 不需要 provider |

## 19. 迁移、兼容与回滚策略

### 19.1 Schema 版本

- 每个新 manifest 自带独立 schema version；不要用一个全局 version 让所有文件同时迁移。
- reader 支持当前版和明确的上一版；writer 只写当前版。
- migration 是纯函数并保存 backup/迁移报告；旧 artifact 本体不重编码。

### 19.2 旧 workspace

- 无 RenderPlan：显示 `needs_render_plan`，不把已有高光视频自动认成整集 production asset。
- 只有角色库旧结构：迁为 version 1，保留原 id 和手工锁定语义。
- 只有 episode 1 高光视频：保留 legacy projection；可选择绑定为某 shot candidate，但必须通过 SHA/容器/fingerprint 检查并由用户确认。
- 旧 submitted task：继续用旧 frozen provider/auth/input 纯 poll；新 registry 不得重解释。

### 19.3 Feature flags 与回滚

- 新逐镜链先使用明确 feature flag/route seam，不替换旧路径。
- 一次 iteration 只迁一种媒体或一种读取路径；写双格式只允许短期、必须有移除计划。
- 回滚只关闭新入口，不删除 manifest/ledger；保留已付费 artifact 与 evidence。
- 不使用 destructive reset 或批量删除来“恢复 fresh”。

## 20. 风险清单与控制

| 风险 | 可能后果 | 控制 |
|---|---|---|
| 过早通用化队列 | 大重构拖慢本地完整链，破坏现有恢复 | A-F 先做 drama 域 vertical slice；G 基于真实重复模式抽象 |
| 创作/渲染真源混淆 | 换图导致 episode revision 漂移，旧集不可复现 | 三层事实、RenderPlan 冻结、显式 stale |
| 目录“最新文件”启发式 | 选中版本静默变化 | immutable version + explicit selected id + CAS |
| unknown submission 自动重试 | 重复付费、重复生成 | paid ledger 独立、submit/poll/download 分层、人工对账 |
| provider 配置漂移 | resume 换模型/账号 | attempt-frozen config，submitted 后不再 resolve |
| FFmpeg 降级过度 | 不完整视频被标成功 | production fail closed；仅 optional BGM/SFX 可警告降级 |
| UI 成为状态真源 | 刷新/多进程后状态错乱 | 后端持久 task/render store；UI 只 projection |
| 动态 provider 代码 | 任意代码执行/凭据泄漏 | 代码内 registry，拒绝 Toonflow 风格热加载/无界 VM |
| TTS/prompt 日志泄漏 | 台词、key、endpoint 暴露 | 受控 metadata；禁止完整文本/key/raw response 进入日志/公开 job |
| embedding 隐式下载 | 测试联网、环境污染 | 默认禁下载；可选依赖显式 preflight；keyword fallback |
| 外部许可污染 | AGPL/额外条款传播风险 | 固定 commit、clean-room、每轮记录参考，直接引入前单独法律/许可审查 |
| 真实质量与工程成功混淆 | 误报产品可用性 | provider evidence 与 operator quality review 分列 |

## 21. 候选实施单元拆分原则

每个未来 iteration 应满足：

- 只交付一个可验收闭环，例如“RenderPlan + stale”，而不是“做完整阶段 B”。
- 高风险边界拆开：schema/migration、真实网络 adapter、Web mutation、FFmpeg 执行、归档导入不宜全塞同一轮。
- 新 provider backend 与通用 worker 不在同一轮首次上线；先用现有 client adapter 证明行为，再抽象。
- 每轮在 Context 写固定外部 commit/文件，Implementation Notes 写“借鉴了什么、拒绝了什么”。
- 每轮默认 mock；真 provider 校准单独成轮且需要用户当次明确授权。
- 每轮仍执行项目 SOP：`iter-start` → 聚焦实现/测试 → correctness 与 security/boundary 只读审查（按 Web/runner/media 风险加视角）→ 修复 → 最终一次 `verify.sh` → `iter-finish` → commit 不 push。

建议最先落地的三个候选单元：

1. **RenderPlan 与 spoken timeline schema**：纯本地、低外部风险，为全部后续能力定真源。
2. **资产版本与 selected reference**：先迁角色，再加场景/道具；解决“生成了很多图但不知道哪张算数”。
3. **本地 compositor vertical slice**：先用 fixture clip/WAV 证明唯一时间线能生成完整 MP4，再接逐镜真生成。

这个顺序允许在不等待任何真实 provider 的情况下尽早发现 schema、时长和合成问题。

## 22. 开工前需由用户确认的产品决策

以下问题不阻碍本文成立，但会影响对应阶段的具体 iteration：

1. 首个 production target 是否固定为 `9:16 / 1080×1920 / 25或30fps`，还是要同时支持横屏；默认建议先单一 9:16 profile。
2. 第一版配音是否只做“旁白 + 主要角色”，还是所有有台词角色；默认建议全角色 schema、主要角色先提供 voice profile，缺失角色明确 blocked/人工分配。
3. 第一版编辑器导出优先剪映草稿、通用 EDL，还是只交付 TimelineManifest + SRT；默认建议先内部 TimelineManifest/SRT，再加一个版本锁定的剪映 exporter。
4. 场景/道具/线索是否允许跨 season 全局复用；默认建议 global/series/episode 三层，但 episode 必须冻结具体 version。
5. 真实 provider 优先级与预算；到阶段 J 再逐次确认，本文不预先选择或授权。

在用户没有另行拍板时，后续计划可以采用上述默认值，但涉及真实调用、商业分发许可或新增外部依赖时仍必须停下确认。

## 23. 本路线图的完成定义

本文作为阶段计划的完成标准是：

- 不占 iteration 编号，已在 `docs/iterations/README.md` 的 Supplemental Records 索引。
- 固定并记录 8 个参考项目的 commit/许可边界。
- 每个关键外部能力都具体映射到外部文件、本仓候选文件、借鉴点和拒绝项。
- 阶段 A-J 均有目标、实施步骤、验收门槛、依赖与非目标。
- 明确当前项目强于外部项目的 paid recovery、安全与 canonical 边界，不因“参考开源”而倒退。
- 下一轮实施仍由用户选择候选单元，并通过 `iter-start` 获取当时真实编号。
