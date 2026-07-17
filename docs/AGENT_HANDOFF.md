# Agent Handoff

> 当前状态单一真源，也是新 session 的工作记忆入口。每轮收官就地更新当前事实，并保留经筛选的阶段级能力、约束与事故教训；不再逐轮复制完整验收日志。更完整的里程碑见 [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md)，逐轮证据见 [`iterations/`](iterations/README.md)。

## Current Snapshot

| 项 | 当前值 |
|---|---|
| 更新时间 | iter 126，2026-07-18 收官 |
| 默认运行模式 | `OPENAI_MODEL=mock`，无 key、无 provider 请求；LiteLLM 本地 cost map、无代理探测，mock token 统计不初始化 tiktoken |
| Canonical 基线 | **2537 tests OK** |
| Accepted implementation commit | `8eeef4f9b11f3cb280cbed5956d057ce4999b2f2` |
| 标准验收 | schema v2 `mock-functional` / `canonical-mock-offline`，status=passed；`local_drama_e2e` 子步骤通过、`provider_validated=false`；`verify.sh` exit 0；mock preflight 无 WARN/FATAL |
| 当前高风险缺口 | 真语音、真视频、episode 2+ 成片及完整逐镜/单集媒体质量与费用仍未实测；视频配置仍缺有效 key 与公网素材回调；小说 10-20 章 capstone 尚未实跑 |
| 当前开发轮次 | 无；iter126 已完成 A2 visual-only override、双 CAS/receipt 恢复与 A-F stale dependency matrix；本轮 1 次 scope-specific 真文本校准，图片/视频/TTS 均 0 调用 |

## Capability Map

| 领域 | 已打通 | 仍未闭环 |
|---|---|---|
| 小说主链 | normalize、split、extract、compress、debate、plan、write、review、滚动摘要、关系推进、多 workspace、多语言 | 10-20 章真模型 capstone 与长期质量阈值校准 |
| 质量与安全 | 起点/指纹守门、review panel、lint、预算/超时、严格离线 mock、文风 baseline/drift/advisor、red drift 单次重写复测 | 文风真模型阈值仍需样本校准；预训练记忆泄露只能缓解，不能作绝对保证 |
| 长跑可靠性 | `write-book`、`drive-book`、supervisor、心跳/watchdog、断点恢复、workspace 写锁、预算预留 | 真模型长跑的费用和失败分布仍需 capstone 证明 |
| Web | 本地 Beta、四步工作台、可编辑设定/大纲/细纲/正文、job 恢复、搜索、版本 diff、Insights、多集编辑入口、中文可读且脱敏的任务历史 | 仍是本地研究工具，不是公网多租户产品 |
| 短剧 | 五站 job、显式文本 revision、Approve review 血统组装、连续多集（计划上限 100）、季角色库与单集冻结阵容/8 人边界、A1 strict RenderPlan 与五态 stale、A2 visual-only immutable candidate/双 CAS/effective manifest/receipt ledger/v1 stale matrix、角色/season ArtDirection/season SceneAsset/season PropOrClueAsset 不可变版本与显式 selected CAS、角色/scene/prop-clue manifests 与 episode used-by、C1-C3 逐镜图片、D1-D4 逐镜视频 compose gate、E1 VoiceProfile/逐句 AudioManifest、E2 once-only TTS recovery、E3 strict TimelineManifest/SRT、F1 FFmpeg 1080×1920/25fps MP4 与媒体 QA、F2 同源 ASS/vendor-neutral 六轨工程/完成回执、单集四导出、严格整季母包/阶段快照、Insights、episode 1 高光视频 job、多模态可恢复编排 | 资产 Web/跨集 used-by、ArtDirection 多 scope、真实逐镜图片/视频 provider 与主观质量、真实 TTS adapter、特定 NLE adapter/Web compose job、多 profile、更广 codec、episode 2+ 成片及真语音/真视频未验证 |
| 集成 | Aeloon 插件/MCP 双轨已实现；详情见 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) | Aeloon vendored 基线与主仓后续版本需按集成文档同步 |

## Latest Accepted Evidence

- iter118 以真实浏览器走通全新短剧 workspace：建档、五站、分镜 6→7→6 增删、角色图、评审组装、四导出、第 2 集、季快照、Insights 与 mock 高光视频；桌面/移动端视觉检查后修复 query/hash、分镜推进、角色保存、stale 下载、付费真图保护、媒体 lock/symlink 与 decoder 宣称边界。
- 指定 provider/model 的 synthetic 真文本五站共 5 calls、项目估算 ¥0.2562、131.49 秒；真角色图 2 张、无重试、98.344/94.568 秒，结构与人工视觉复核通过。真视频停在 `awaiting_video_authorization`，submit=0；该证据只覆盖本次样本，不外推完整 provider、视频或 SLA。
- iter123 F1 从唯一 TimelineManifest 生成 argv-only FFmpeg plan，在 probe/hash 后以私有 staging 固化已验证字节，完成视频 normalize/concat、音频 delay/trim/fade/mix、SRT 与严格 post-probe QA；synthetic 产物为 1080×1920/25fps H.264/AAC MP4，required shots 全覆盖。
- iter124 fresh 两集桌面 SOP 走通；后续集 mock 初次分镜/单镜重生绑定本集 mainline/hook，多集列表/详情均可直接编辑；任务页使用中文步骤、可读时间与强类型脱敏 LLM 摘要。
- iter124 真文本五站审计 6 calls，另有错误根路径 1 次失败请求，总计 7/60、估算 ¥0.2973；2 张真角色图首次成功、113.974/105.397 秒、2/20、估算 ¥10，人工视觉复核通过。视频文档仅含 key 占位符且文本 key 对视频服务 401，同时无公网素材回调，因此 0 submit `safe-blocked`；TTS 未测。
- iter125 F2 从唯一 TimelineManifest 确定导出同源 ASS 与 vendor-neutral 六轨可编辑工程；素材 SHA/source range、音频 gain/fade/profile、字幕 source hash/revision 和 completion marker 可精确重建重验，partial pair 与 source/output namespace swap fail closed。
- iter126 A2 新增四字段 visual-only override、append-only content-addressed catalog、revision/current-ID 双 CAS、effective manifest 与最多 512 条 receipt ledger；before/after 双快照证明单镜头 delta，连续保留 receipt 必须成链，ack gap、lost response、ABA `target_current` 语义均有回归。v1 matrix 精确覆盖 creative、各 override 字段、BGM 与 first frame 对 A-F 的传播。
- iter125-126 scope-specific 文本校准累计保守计 3/60 请求、2 次模型成功；iter126 单次 HTTP 200、164 tokens/3.198 秒并完全匹配 transition matrix。累计预留 ¥0.20，图片 0/20、视频/TTS 0；证据仅为 `provider-validated-local-calibration`。
- canonical **2537 tests OK**（项目 `.venv`）；implementation commit `8eeef4f` 上 exit 0，15 steps / 301 秒，run `497adce99a36419099eb71f56f8f16e2`，tree `aedd8692c35ef80df2ff17daf54ffdb3e7306210`，`tracked_scope_clean=true`，mock preflight **0 FATAL / 0 WARN**。总级别仍是 `mock-functional` / `canonical-mock-offline`，mandatory local-drama component 为 `local-e2e`；correctness、security/boundary、media/workflow 最终无遗留 P0/P1/P2。

## Retained Working Memory

本节不是逐轮 changelog，而是从 iter 093 前的累计 handoff 中恢复的接力信息。只有会影响设计、排障、验收或授权判断的事实保留在这里；细节数字、历史命令和当时 snapshot 仍回到对应 iteration 查证。

### 1. 系统主链与权威边界

- 小说主链的稳定顺序是 `normalize → split → extract → compress → debate → plan → write → review → rolling summary / entity advance`。Web、CLI、runner 和长程 driver 最终必须落到同一组领域函数与状态语义，不能各自维护平行判断。
- `main.py` 是 CLI 汇入口；`src/auto_pipeline.py` 负责工作区准备/重建；`src/book_runner.py` 负责生产单章；`src/book_driver.py` 负责多章驱动；`src/web/jobs.py` 只做可恢复 job 编排与安全公开投影。
- 当前行为看代码和测试，当前进度看本文件，节点 SOP 看 README，阶段原因看 `PROJECT_HISTORY.md`，逐轮证据看 iteration。历史文档中的测试数、预算或“当前”不能覆盖本文件。
- Aeloon 是 vendored 插件与 MCP/共享 client 双轨集成，版本同步、鉴权与部署边界只以 `docs/AELOON_INTEGRATION.md` 为准，不从主仓代码存在推定线上已更新。

### 2. Mock、真实调用与凭据安全

- 所有单测、`verify.sh` 和默认开发链必须强制 `OPENAI_MODEL=mock`。测试环境即使存在 `.env` 也不能触发真实 provider；任何 discovery 路径能绕过 mock 都是 P0/P1 级回归。
- mock 必须在 LiteLLM 首次导入前强制本地 cost map、跳过 proxy setup，并让 token 统计走本地 estimate；新入口若不能提前 pin 环境，就必须延迟导入 LLM 栈。网络审计要执行实际 completion/preflight，而不只验证 import。
- `.env` 由用户维护，agent 不主动读取或修改。日志、异常、job 公开视图与报告不得包含 key、Authorization、完整 prompt、签名 URL、上游响应正文或无界自由文本。
- 真文本、真生图、真视频是三类独立授权。授权只适用于本次精确入口、模型/服务、提交上限、预算与超时，不跨阶段、不从旧对话或 resume state 继承。
- 真实 smoke 失败时先停在可恢复状态。生图首次失败/超时后先查上游任务和账单，再申请新授权；最多额外 2 次简化 prompt、每次 180 秒。视频单次提交，超时不重试。

### 3. 起点安全、知识视图与版权边界

- 不读取、修改或提交 `小说txt/` 与私有原文衍生数据。仓库示例只能保存 schema 与占位符；工作区原文、运行输出和日志都应保持 gitignored。
- “不要剧透”不是硬保证。可靠链路依赖 start-aware ingest、continuation anchor、knowledge view、plan fingerprint 和物理过滤共同约束；模型预训练记忆仍无法被绝对消除，只能明确披露为残余风险。
- 深起点续写需要 ingest/rebuild，而不是简单换一个 chapter id。起点变化后，抽取物、压缩摘要、计划、关系图和后续草稿的血统/指纹都要重新判断 freshness。
- 可选 style examples、global facts、entity graph、continuation anchor、persona 缺失时，裸仓库 mock 仍须 graceful degrade；但生产 readiness 可以对关键缺失显式 blocked，二者不能混为一谈。

### 4. 结构化 LLM 输出与 fail-closed

- Prompt 约束不能替代本地 schema/normalization。历史真模型曾返回空 ballot、缺字段 review、近似 JSON、布尔冒充整数、NaN/Infinity 与截断内容；所有计费/写盘/Approve 边界必须本地验证。
- reviewer JSON 允许对已知形态做有限 repair；无法可靠修复时必须 Abstain/blocked，不能为了流水线继续而默认 Approve。
- 写手、规划、辩论和 review 的上下文预算需共享 token 计数与分层装配器。预算不足时保留 canon、起点和当前计划，裁剪低优先级历史；不要在各 agent 内复制不同的截断算法。
- 配置名必须与语义一致并在加载时硬校验。历史 `rewrite_max`/attempt 语义漂移说明“保留兼容但含义变化”会把错误推迟到长跑，应优先迁移到单一真源。

### 5. 生产写作、评审与状态提交

- 单章生产不是“生成文件即成功”。必须能区分 partial draft、reviewed、approved、rejected、aborted 和 stale；失败/拒稿草稿仍需完整落盘以供排障，但不能被下一章误认成已提交正文。
- review panel、计划履约检查、outline drift、lint 和 style drift 是不同维度。确定性硬门先执行，LLM reviewer 不应覆盖起点、指纹、预算或严重漂移等本地 blocker。
- 文风闭环采用 baseline v2 → drift → directives → red drift 最多一次定向重写 → 复测择优。mock 证明 wiring，不证明阈值适合真实作家/书目，真实阈值仍是待校准项。
- 实体/关系更新先产 proposal，经冲突检查后 apply；新实体关系必须受控创建。rolling summary、entity compensation 和 chapter commit 的顺序不能随意交换，否则 resume 会出现正文与记忆不一致。

### 6. 长跑、预算与恢复

- 长流程的正确目标是可恢复，不是“永不失败”。`drive-book`、heartbeat/watchdog、supervisor、workspace lock、snapshot、attempt ledger 和预算预留共同构成可靠性边界。
- 预算在调用前预留、调用后按实际结算；非有限数、布尔、负值或陈旧 state 必须 fail-closed。readiness 的估算不是账单，实际 cost 仍需审计 ledger 核对。
- workspace 写锁同时覆盖 CLI 和 Web 写入口。取消需要阶段检查点；孤儿进程、陈旧 heartbeat 和 crash-active step 必须能在 resume 时被明确归类，不能静默重复提交。
- 10-20 章 capstone 仍未完成，因此“工程长跑闭环”不能表述成“真实长期质量/费用已证明”。真跑前先使用干净 workspace、固定起点和有限预算，并逐次取得授权。

### 7. Web 与本地产品定位

- Web 是本地个人研究工作台，默认绑定 loopback，不是公网多租户产品。任何面向公网的鉴权、租户隔离、CSRF、速率限制或对象存储结论都不能从本地安全守门外推。
- 四步工作台支持 premise、设定、大纲、细纲、正文的编辑与再生成；编辑后必须使依赖的 fingerprint/readiness 失效，不能继续沿用旧计划或旧草稿。
- Job 的公开投影只允许受控字段和短状态；内部异常、provider 文本、路径、prompt、URL 与大对象不能直接透传。恢复页面需要从持久 state 重建，而不是只依赖进程内 future。
- 搜索、章节 diff、Insights、软删除/回收站属于编辑辅助能力；它们应只读或显式确认，不得绕过 workspace 路径约束和写锁。

### 8. 短剧创作与媒体链

- 短剧主流程已覆盖五站文本、站③分镜 grid、站④角色/角色库、review/assembly、连续多集、四格式单集导出、Insights，以及严格整季母包/阶段快照；episode 1 视频边界保持不变。
- 创作层不因渲染需求改写 `DramaEpisode` 或 episode SHA；`episode_NN.json` 为创作真源，`episode_NN.render_plan.json` 是可丢弃/可重建的渲染派生物。若未来要求语义编辑后仍保持永久镜头 UUID，必须单独修改创作 schema 和保存链，不能在渲染层猜测对应。
- SceneAsset 场景绑定只接受调用方显式完整的稳定 shot ID 映射；没有 typed 创作 source 时宁可 blocked，不从分镜文本、prompt、位置或目录最新文件猜场景。manifest 是本地绑定记录，不是签名 provenance。
- episode frozen cast 不是逐镜角色真源；图片输入必须为每个 stable shot 提交完整显式角色 mapping。`assembled` 只代表离线规格/引用装配，metadata-only 资产不得伪造 image ref，也不得藉此宣称 provider-ready。
- C3 的 `ShotImageProviderCapability` 与注入 adapter 是本地执行契约，不是动态 provider registry。C1 仍是唯一 reference 裁剪层；C3 不二次裁剪。`RequestNotSentError`、provider fingerprint 与 adapter 行为依赖未来实现方可信接线，本轮 fake 证据不能外推真实 provider。
- D1 的 `EpisodeShotVideoPlan` 是 provider-neutral 输入契约：从 fresh RenderPlan/C1/C2 冻结逐镜时长、exact selected first/optional tail、ordered refs 与 previous-tail lineage。它不代表已建立视频 provider capability、attempt/candidate/selection 或 submit/poll/download；旧 episode 1 高光 job 也不是 D1 真源。
- D2 的 `EpisodeShotVideoCandidateManifest` 是逐镜本地视频事实：candidate 不可变、selection 可变且需 guarded CAS，删除镜头保留 retired audit；production coverage 只接受 current D1 下 exact selected、artifact 完整且非 placeholder 的 required shots。它不等于 provider 执行或视频质量验证。
- D3 的 `EpisodeShotVideoAttemptLedger` 是逐镜付费执行事实：authorization 必须绑定 exact episode/shot/request 与 provider/model/account/endpoint/auth，adapter operational identity 在 submit/poll/download 前重验；同一授权有任何非 not-sent 事实后即 consumed。unknown 只能对账后显式关闭，不能猜 task 或自动重提；fake/process-crash 证据不能外推真实 provider exactly-once。
- 下一集只能从最新连续、完整且 fresh 的前集初始化；`episode_count` 是计划真源。季包只从 assembled JSON 和安全投影重建，不能把 setup、候选钩子、评审原文、prompt、日志或 provider state 混入交付物。
- 真实媒体下载必须同时校验 scheme、redirect、DNS 与 peer IP、MIME/magic、size、hash、容器和原子落盘。仅检查扩展名或响应头不构成安全边界。
- Iter 092 的多模态 state machine 支持 fresh/resume、独立授权、预算/deadline 与生图重试；Iter 094 补齐校准证据；Iter 097-101 继续收口旧旁路、provider 身份、文本 revision/review 血统、五站/媒体 crash window、跨进程 callback、旧 workspace 接管、多集角色和 submitted 纯轮询恢复。
- 文本证据按五站记录 task/model SHA、调用数、耗时与 cost，并以严格 attempt ledger 绑定 endpoint/账号/输入/产物；成功产物可零网络恢复，未知提交才要求对账。
- 图片证据按角色/attempt 记录 objective metadata、规范化记录 SHA、文件 SHA、provider、耗时和尺寸；当前真实图片只接受严格 PNG。视频以 durable ledger 区分确定未发送、提交未知、已提交、终态失败与成功，报告交叉重读 ledger 和本地产物，避免 crash window 低报付费请求。
- 校准报告只说明证据完整度，不自动给真实作品质量打通过。`real_execution_recorded_unverified` 仍需 operator quality review；本地存在记录也不能证明本次真实调用已发生。

### 9. 历史事故模式与排障顺序

1. 先确认 mock，再用最小聚焦测试复现；不要一上来跑全量或真模型。
2. 先检查 shared schema/normalizer/readiness，再检查 CLI/Web/runner 调用方；同一 bug 多入口出现通常意味着真源下沉不够。
3. 对 stale/fingerprint 问题先画清输入、派生产物和 commit 顺序；不要用删除 state 或强制重跑掩盖血统错误。
4. 对 provider timeout 先区分“请求未提交、已提交未知、上游成功但下载失败”。只有第一类能安全自动重试；媒体尤其要先核账。
5. 对测试环境差异先记录解释器、依赖和 loopback 权限。本仓标准基线使用项目可用依赖环境；系统 Python 缺包不代表业务回归。
6. 对文档冲突按权威顺序修正，不让过时的历史测试数或旧入口重新进入 README/handoff 当前表述。

### 10. 迭代收官与记忆维护

- 每轮先 `iter-start` 建 8 段 iteration；实现中记录范围变化和真实阻塞；`iter-finish` 负责审查、最终验收、README、handoff、history 与 commit message 草案。
- iter112 起在原 8 段内显式维护 Implementation/Review Context：实施前列本轮必读与预计变更面，审查前按最终 diff 复核，并把 correctness、security/boundary 与风险专项上下文分别派给对应只读视角；它是 iteration 的路由清单，不是第二套状态真源或 Git 硬白名单。
- Knowledge Promotion 在 findings 稳定后、implementation commit 前人工判断；非 docs-only 的长期规则修改必须进入 canonical 验收，README/handoff 的常规状态同步不算晋升。下一轮 active 出现后，前一轮 accepted 闭包仍须持续通过 checker。
- 耗时全量验证只在多视角审查和 findings 修复之后执行一次。审查前只跑覆盖改动面的聚焦测试、语法/静态检查和 diff 检查；若最终全量失败，再按失败范围修复并重验。
- 收官至少有 correctness 与 security/boundary 两个独立只读视角；Web、runner、多 workspace、真实模型/计费或媒体入口按风险增加。subagent 不改文件、不跑真模型、不碰私有目录。
- handoff 不恢复逐轮 `Phase Status` 累计模式，但也不能再次压成几十行。保留本节这类阶段级工作记忆；只有事实变化时就地更新，过时细节迁入 `PROJECT_HISTORY.md` 或具体 iteration。
- `PROJECT_HISTORY.md` 与 handoff 都是新 session 默认记忆：前者回答“为何如此”，后者回答“现在怎样做”。iteration 只在实施和追证时按需读取。

### 11. Phase-Level Continuity Memory

以下阶段记忆用于判断“一个看似局部的改动会触碰哪些旧承诺”。它不替代 `PROJECT_HISTORY.md` 的里程碑索引，而是保留各阶段形成的兼容性边界和复发风险。

#### Phase A — iter 001-008：工程骨架与第一次真实链路

- 早期先建立 manifest、run report、preflight、失败恢复和 context overflow 可见性，随后才接真实 extract/debate/write/review；这决定了新 provider 能力必须先进入可观测/可恢复骨架。
- 真模型 ballot 与 reviewer 输出第一次证明“能返回文本”不等于“结构可用”，因此 JSON repair、schema validation 和 Reject 草稿完整落盘成为后续所有 agent 的底线。
- 测试 discovery 曾可能继承本地真实配置，最终形成配置层、测试入口与验证脚本多层 mock 隔离。修改配置加载时要优先回归这一事故。

#### Phase B — iter 009-019：多章质量、通用化与无人值守

- style examples、anchor、lint/polish、实体关系、章节摘要和关系推进在这一阶段形成；后续“简化上下文”不能只保留 plan 而丢掉这些长期一致性输入。
- plot planner、五类 bootstrap、persona、多 workspace、多语言/EPUB 把项目从单书脚本变为通用系统；任何默认值都不能偷偷绑定当前验证书目。
- 自动 advance、resume/retry 与 fail-closed review 让无人值守成为可能，但 proposal/apply 与 review/commit 的边界必须保留人工可审计性。

#### Phase C — iter 020-032：算法根修复与 Web Beta

- 起点防剧透、planner/writer/reviewer 上下文和关系一致性曾做过根级修复；相似缺陷优先检查 shared source assembly，不要只在 prompt 末尾补一句规则。
- 9 阶段 SOP、生产 runner/readiness 和 Web 工作台在此阶段对齐；CLI 能跑而 Web 不能恢复，或 Web 显示 ready 而 runner blocked，都属于语义分叉回归。
- Web 最初从只读 dashboard 扩展为 wizard/auto-pipeline。现有路由仍要兼容旧 workspace 的缺失字段与可选产物，不能假设都由最新向导创建。

#### Phase D — iter 033-050：可编辑工作台、短剧底座与 Aeloon

- 回收站、Insights、计划页、错误提示和响应式 UX 逐步加入；删除/编辑动作应通过明确 API 和确认，不以 DOM 状态代替持久状态。
- 短剧 workspace 与前两站在 iter 036-038 建立，后续站点共用其 schema、目录和 episode 语义；修改短剧路径时需兼容早期 workspace。
- iter 039-042 修过真实 Web 写作链、meta/review verdict 和三档评分，说明 job 完成态、正文 meta 与 review 文件必须同步提交。
- Aeloon 双轨与全程编辑闭环在 049-050 形成；共享 client/MCP 的认证和 budget guard 不能被 Web 内部便捷函数绕过。

#### Phase E — iter 051-057：真模型质量与长程结构

- premise 扩写、review budget、drive-book 和 canon 锚定经过真实样本验证，但样本有限，不能把一次 5/5 Approve 外推成任意书目质量保证。
- 深起点 diff oracle 暴露过派生知识越界；start point 变化必须重建或拒绝 stale artifact，而不是仅在 writer 阶段过滤。
- per-task timeout、分类重试和续抽策略源自真实 provider 卡死/截断；新增模型必须明确哪些错误可重试，不能对 unknown submission 自动重发。
- 长程审查修过计划指纹、流式卡死、旧章记忆和大纲漂移；这些是 capstone 前仍需重点观测的历史高发点。

#### Phase F — iter 058-067：输入、安全与 fail-closed 清债

- 前端曾有预算静默错误、坏 JSON 崩溃、非法整数、并发写和取消不及时；公共输入要在进入 runner 前标准化为 typed value/error。
- iter 061 的风格样本路径穿越是重要安全事故：任何用户可控 filename、workspace、episode、character id 都必须目录约束与随机内部 token 配合。
- readiness 目录合并、CLI/Web 参数统一和 typed stale error 是为消除平行判断；新 blocker 应先进入共享 catalog/schema，再由各入口渲染。
- bool 是 Python int 子类、JSON 可默认输出 NaN/Infinity 等语言细节曾绕过预算/状态守门；数值判断必须显式拒绝 bool 和非有限值。

#### Phase G — iter 068-073：重建、可取消与导航一致性

- 底座重建成为正式 job 后，进度、取消、预算和 readiness 需要跨进程持久；只更新内存进度会让刷新后的页面误判。
- 三功能入口、首页导航和 leave guard 逐步重构；active jobs 的真源在后端，前端模态只负责提示，不能单靠前端阻止危险离开。
- 计划失约和严重 outline drift 被提升为 blocker，job 公开投影也被收紧；新增公开字段必须先判断是否会泄露内部异常或长文本。

#### Phase H — iter 074-079：编辑复核与 capstone 前硬化

- 章节 diff 与全文搜索都经过路径、范围、高亮和旧版本兼容加固；它们是读者/编辑工具，不应改变正文 commit 或绕过软删除语义。
- 六方长跑审查修过伏笔边界、caveat 恢复、陈旧拒稿、孤儿进程、评分/成本、摘要顺序和实体补偿，这些是长跑审查 checklist 的来源。
- supervisor、heartbeat/watchdog、预算预留、workspace lock 与 mock budget rehearsal 已工程闭环；真实 capstone 的目的仍是验证分布和阈值，而不是补基础 wiring。

#### Phase I — iter 080-088：短剧核心与文风量化

- 分镜 grid、角色设计/角色库、review/assembly、导出、Insights 和 episode 2 形成产品闭环；角色引用与 shot/episode 关系是媒体产物 fingerprint 的上游。
- 文风 baseline/drift/advisor/red rewrite 是小说链的旁路质量系统。重写最多一次并复测择优，避免 style loop 无限消耗预算或覆盖更好的原稿。
- 四格式导出包含下游工具 schema，修改字段名或排序需要兼容测试和版本声明，不能只按当前 Web 展示调整。

#### Phase J — iter 089-094：真实媒体入口与校准证据

- iter 089 先建立授权、SSRF、下载落盘和 video client 安全骨架；iter 090 再把五站文本 job 化；iter 091 完成 episode 1 视频闭环；顺序体现“安全边界先于真实调用”。
- iter 092 把文本、全角色图片和单次视频编成可恢复状态机，并限制图片 retry；真实阶段授权仍相互独立，resume 只恢复状态、不恢复权限。
- iter 094 解决“state 显示完成但证据不足”的问题：对账 LLM ledger、失败耗时、提交次数和产物内容，报告只给 evidence status，不替 operator 做质量结论。
- 下一次真实校准应分三次向用户报告精确命令、模型/服务、最大请求/提交数、最坏费用和 timeout；任何一段未授权都保持 0 提交，不因前段成功自动推进。

#### Phase K — iter 093-094：项目记忆与收官流程复盘

- iter 093 正确识别了 2000+ 行逐轮累计 handoff 的重复和过期风险，但一次压到约 93 行导致设计背景、历史事故和恢复知识不足。
- iter 094 采用四层记忆：AGENTS 长期规则、handoff 当前事实+工作记忆、PROJECT_HISTORY 阶段原因、iteration 逐轮证据。优化指标是接力质量，不是最低行数。
- 同轮将耗时全量验收移到多视角审查/修复之后；前置聚焦检查仍保证审查基于可运行代码，后置 full gate 保证最终状态没有降低验收强度。

#### Phase L — iter 095：连续多集与整季交付

- 下一集创建统一为计划内连续 N+1，只有最新连续、完整且 fresh 的前集可推进；有效 setup 可幂等恢复，跳集、断档、孤儿与 stale 均 fail-closed。
- freshness v2 冻结本集活跃角色范围，角色 appearances 可累积至 100；未来角色变化不误伤旧集，但旧集活跃角色视觉与参考图仍参与 stale 判定。
- master/snapshot 都从 assembled JSON 重建并使用受控 manifest、成员 hash、固定 ZIP 元数据、安全有界读取和原子替换；工作目录不能直接作为交付包来源。

## Operating Boundaries

- 不读写 `.env`、`小说txt/`、私有 `data/` 样本；不把原文、凭据、完整 prompt 或上游响应写入文档/日志。
- `verify.sh` 与单测必须保持 mock 隔离；真实调用必须有用户针对本次入口的明确授权。
- 真文本、真生图、真视频授权彼此独立；授权不跨阶段、不从历史 state 恢复。
- 生图重试遵循“先查上游/账单，再重新授权”；视频超时不重试。
- 只 commit，不 push。

## Open Gaps

1. **短剧真实多模态后续校准**：iter124 已验证指定样本的五站真文本与 2 张角色图；真视频仍缺有效服务 key 与公网素材回调，全角色/多题材图像、逐镜/单集媒体费用与质量仍需分别授权。
2. **小说 capstone**：选择干净 workspace 跑 10-20 章，验证预算、supervisor、resume、质量闸和关系推进。
3. **文风阈值**：用真模型草稿校准 baseline/drift tolerance；当前工程闭环已通，但阈值证据仍以 mock/局部样本为主。
4. **短剧媒体**：A1/A2 渲染与 stale、C1-C3 本地逐镜图片、D1-D4 逐镜视频、E1-E3 voice/TTS/timeline 与 F1/F2 本地完整成片/可编辑导出已完成；资产 Web/跨集 used-by、真实图片/视频/语音 provider adapter、质量比较、JPEG/WebP、staging GC/power-loss、真实 BGM/SFX、特定 NLE/Web compose、episode 2+ 与真实多模态质量仍未验证。
5. **集成同步**：Aeloon 内置副本不是自动跟随主仓，需要按集成文档明确同步。
6. **多集查询性能**：100 集时 `GET /drama/episodes` 会在状态与季包 readiness 间重复读取部分文件，可后续缓存一次请求内的扫描结果。
7. **严格本地对手 TOCTOU**：项目锁可阻止本项目 Web/runner 并发，workspace lock/holder、state/PNG 和新增 ArtDirection store 已使用 nofollow dirfd；若威胁模型包含不遵守 flock 的本机其他进程在最终检查后竞态替换目标或父目录，仍需更强的统一 dirfd/事务协议。

## Next Candidates

- 低风险工程轮：可靠有界 JPEG/WebP decoder、provider 幂等键/资产上传恢复调研、100 集只读扫描优化或已登记 P2 技债。
- 低风险短剧阶段轮：推进 B1 跨集 used-by/Web 管理、C 的 JPEG/WebP/staging GC，或 F3 Web compose；不得把 vendor-neutral F2 冒充特定 NLE 兼容。
- 需授权验证轮：全角色/多题材真生图、补齐有效视频 key/公网素材回调后的 episode 1 单次真视频、逐镜/单集媒体或小说 capstone。不要把这些授权合并推定；iter118/124 的文本与角色图证据不自动授权复跑。
- 产品轮：100 集状态扫描性能优化、episode 2+ 视频、多季模型，或真 ComfyUI 导出校准。

## Recovery Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests
bash scripts/verify.sh
.venv/bin/python3 main.py preflight
.venv/bin/python3 main.py status
.venv/bin/python3 main.py write-readiness --chapters N
```

先以 mock 复现。真模型入口、长跑参数和计费边界必须读对应最新 iteration 与脚本帮助，不能从历史示例照抄。

## Documentation Map

| 需要回答的问题 | 读取位置 |
|---|---|
| 现在能做什么、缺什么 | 本文件 |
| 小说 9 阶段与短剧生产节点是否打通 | 根 [`README.md`](../README.md#流水线-sop实时状态) |
| 某轮具体改了什么、怎么验 | [`iterations/README.md`](iterations/README.md) -> 对应 iteration |
| 为什么形成当前架构 | [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) |
| Aeloon 集成细节 | [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) |
| 用户操作 | [`product/GETTING_STARTED.md`](product/GETTING_STARTED.md) |
| 产品边界 | [`product/PRODUCT_SPEC.md`](product/PRODUCT_SPEC.md) |
| 短剧端到端 SOP 与实时完成度 | [`product/short_drama_module.md`](product/short_drama_module.md#11-完整生产-sop实时状态) |

## Maintenance Contract

- 收官时更新 `Current Snapshot`、`Capability Map`、`Latest Accepted Evidence`、`Open Gaps` 和 `Next Candidates` 中受影响的行。
- `Latest Accepted Evidence` 只保留最近一次会改变接力判断的证据，通常不超过 8 条。
- `Retained Working Memory` 保留阶段级能力、长期约束、事故模式和恢复知识；事实变化时就地修订。目标是数百行可工作的记忆，不回到 2000+ 行逐轮日志，也不再次压成几十行摘要。
- 不追加“Phase Status - iter NNN”逐轮长段；完整结果写入当轮 iteration，同时更新 `PROJECT_HISTORY.md` 的阶段历史与长期教训。
- 测试数只在本文件与最新 iteration 保留当前值；README 历史表不逐轮复制测试数字。

## Latest Transition

iter126 完成 A2 visual-only override 与 `drama-stale-matrix-v1`：四字段不可变候选、revision/current-ID 双 CAS、effective manifest、安全原子 state 和最多 512 条的 before/after receipt ledger；历史 receipt 逐版本绑定 catalog、连续修订成链，lost response、ack gap、same-shot supersede 与 ABA `target_current` 都有确定语义。矩阵把 creative/override/BGM/first-frame 精确投影到 A-F 节点且不误伤 spoken audio/无关镜头。本轮 scope-specific 真文本 1/1 成功、164 tokens/3.198 秒；累计 iter125-126 保守 3/60 请求、¥0.20，图片 0/20、视频/TTS 0。三视角最终无遗留 P0/P1/P2；canonical 2537 tests、15 steps、301 秒，run `497adce99a36419099eb71f56f8f16e2`，mock preflight 0 WARN/FATAL，总级别 `mock-functional`，局部文本为 `provider-validated-local-calibration`。
