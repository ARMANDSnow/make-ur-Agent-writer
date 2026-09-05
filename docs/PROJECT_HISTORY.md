# Project History

> 经过筛选的项目里程碑、架构原因与长期工程教训。它与 [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) 一起作为新 session 默认记忆：handoff 回答“现在怎样做”，本文件回答“为什么形成现在的做法”；逐轮证据仍以 [`iterations/`](iterations/README.md) 为准。

## Timeline

| 迭代 | 里程碑 | 形成的长期能力 |
|---|---|---|
| 001-005 | mock 工程基础到首次真模型 extract | CLI 可观测性、manifest/report guard、失败恢复、context overflow、preflight、结构化 debate 投票 |
| 006-008 | 真模型 debate/write/review 首次闭环 | provider routing 守门、测试 mock 隔离、ballot/reviewer JSON repair、Reject 草稿完整落盘 |
| 009-013 | 写作质量与多章架构 | 风格样例、continuation anchor、lint/polish、实体关系、一致性 review、滚动章节摘要与关系推进 |
| 014-019 | 通用化与无人值守 | plot planner、五类 bootstrap、persona、多 workspace、多语言/EPUB、自动 advance、resume/retry、fail-closed review |
| 020-032 | 算法根修复与本地 Web Beta | 9 阶段 SOP、起点防剧透、planner/writer/reviewer 上下文修复、生产 runner/readiness、Web 工作台与信息架构 |
| 033-050 | Web 日常能力与全程可编辑 | 软删除、Insights、wizard、短剧 workspace 基础、真实 job 恢复、响应式 UX、Aeloon 双轨、设定/大纲/细纲/正文编辑闭环 |
| 051-057 | 真模型质量与长程驱动 | premise 扩写、review 预算、drive-book、深起点重建、canon 锚定、diff oracle、per-call timeout、风格卡与长程结构修复 |
| 058-073 | 安全、错误处理与交互硬化 | 预算/数值 fail-closed、坏 JSON 降级、路径穿越修复、错误脱敏、取消/进度、离开守卫、参数单一真源、计划履约检查 |
| 074-079 | 编辑工具与 capstone 前可靠性 | 章节版本 diff、全文搜索、panel policy、预算预留、心跳/watchdog/supervisor、workspace 写锁、预算账本与 readiness 补偿 |
| 080-082 | 短剧核心创作闭环 | 分镜 grid、角色表/角色库、AI 绘画骨架、drama reviewer、episode assembly 与复核页 |
| 083-087 | 文风量化闭环 | baseline v2、漂移检测、定向建议、可靠性守门、red drift 最多一次重写与复测择优 |
| 088-092 | 短剧交付与真实媒体安全入口 | 四导出、Insights、第 2 集、真生图安全下载、五站 job、视频 job、多模态可恢复状态机与受控生图重试 |
| 093 | Agent 记忆与文档分层 | 将累计 handoff 压缩为当前快照、合并阶段总结并压缩索引；后续复盘确认压缩幅度过大 |
| 094 | 多模态校准证据与记忆再平衡 | 增加真实/模拟证据区分、调用/耗时/产物对账；恢复阶段级工作记忆并调整收官验收顺序 |
| 095 | 短剧多集与整季交付闭环 | 连续 N+1、episode-scoped freshness v2、角色跨集出场、严格 master 与阶段 snapshot、安全确定性季包 |
| 096 | LiteLLM 严格离线 mock | 首次导入本地 cost map、零代理/tokenizer 网络准备、入口级网络审计与 verify 环境一致性 |
| 097 | 短剧真模型全链审计硬化 | 一次性授权、provider/账号绑定、严格媒体下载、durable 视频提交账本与 crash-window 对账 |
| 098 | 短剧真模型二次全链硬化 | 五站产物血统/付费恢复、实际 peer 传输、artifact 收尾与 MP4 实测复核 |
| 099 | 短剧真模型第三次全链硬化 | 共享 readiness、episode 身份/脏账本、PNG 结构 provenance 与 submitted 零重提交恢复 |
| 100 | 短剧真模型全链阻塞修复 | 稳定恢复身份、跨进程 callback、媒体 crash receipt、result-host 血统与 Web 逐次授权 |
| 101 | 短剧完整链路残余阻塞修复 | 文本 revision、Approve 血统、旧 workspace 媒体接管、季角色库与 submitted 纯轮询恢复 |
| 102 | 标准验收隔离与审计基线 | synthetic workspace、dotenv 物理短路、evidence v2、accepted commit 与 Acceptance ID 闭包 |
| 103 | 本地 Fake Provider 整链 | 图片/视频/callback/五站授权 loopback E2E，组件证据与 canonical identity 绑定 |
| 104 | Crash/Restart 与状态矩阵 | 集中付费状态；五站、图片、视频生产恢复入口与跨进程 crash 矩阵 |
| 105 | 短剧单集角色投影一致性 | reviewer、组装、Comfy 与 episode 1 视频共享冻结阵容；歧义旧数据 fail-closed |
| 106 | 短剧渲染计划与创作陈旧性边界 | fresh assembled episode 确定投影 strict RenderPlan；五态 stale 分类、幂等落盘与歧义镜头 fail-closed |
| 107 | 短剧角色资产版本与冻结选择 | 角色语义 ID、不可变版本、显式 selected CAS 与单集 active AssetRef manifest |
| 108 | 短剧美术方向版本与渲染冻结 | season ArtDirection 不可变候选、显式 selected CAS、RenderPlan ref 与单集 manifest stale 传播 |
| 109 | 短剧场景资产版本与逐镜冻结 | season SceneAsset 不可变候选、selected 双 CAS、显式 shot→scene manifest、episode used-by 与精确 stale |
| 110 | 短剧道具/线索资产版本与逐镜冻结 | season PropOrClueAsset 不可变候选、selected 双 CAS、显式 shot→0..16 refs、episode used-by 与精确 stale |
| 111 | 短剧逐镜图片规格与冻结引用 | provider-neutral 逐镜图片规格、显式角色绑定、exact 资产引用、确定性裁剪与精确 stale/store |
| 112 | 迭代上下文与经验晋升门禁 | 实现/审查上下文、tracked 安全路径、accepted 持续闭包与人工知识晋升 |
| 113 | 短剧逐镜图片候选与首尾帧绑定 | content-addressed strict PNG 候选、guarded first/tail lineage、精确 coverage/stale 与 create-only repair |
| 114 | 短剧逐镜图片能力与可恢复尝试 | provider-neutral capability、once-only attempt、durable receipt、C2 exact candidate 补账与 process-crash 零重复调用 |
| 115 | 短剧逐镜视频计划与冻结首尾帧 | provider-neutral 逐镜时长/视觉输入/exact first/optional tail/previous-tail lineage 与五态 local store |
| 116 | 短剧逐镜视频候选选择与整集覆盖 | content-addressed strict MP4、guarded selection、retired audit、精确 stale/repair 与 production coverage |
| 117 | 短剧逐镜视频能力与可恢复尝试 | provider-neutral capability、exact once authorization、adapter identity、durable receipts、D2 补账与 process-crash 零重复 submit |
| 118 | 短剧完整 SOP 真人用户验证 | Web 桌面/移动端主链 E2E、真文本/角色图局部校准、付费产物保护与 strict PNG 边界 |
| 119 | 短剧逐镜视频连续性与合成门禁 | selected snapshot、artifact-aware workspace gate、global stale 与 degraded preview 边界 |
| 120 | 短剧 Voice Profile 与逐句音频计划 | 显式 voice assignment、完整 AudioManifest、局部 stale 与 canonical mock WAV |
| 121 | 短剧可恢复 TTS Attempt | 逐句一次授权、POST/GET 分离、durable receipt 与 os._exit 恢复矩阵 |
| 122 | 短剧唯一时间线与字幕 | fresh MP4/WAV 同锁投影、严格 TimelineManifest 与同源 SRT |
| 123 | 短剧本地 FFmpeg 完整成片 | argv-only 合成计划、verified-byte staging、1080×1920/25fps MP4/SRT 与 post-probe QA |
| 124 | 短剧桌面端 SOP 与真模型验证 | 两集桌面 E2E、多集分镜/导航、任务日志安全投影与真文本/图片局部校准 |
| 125 | 短剧 ASS 与可编辑工程导出 | 同源 ASS、vendor-neutral 六轨工程、素材/字幕版本冻结与 completion marker |
| 126 | 短剧 Visual Override 与 Stale 矩阵 | 四字段不可变 override、双 CAS/receipt ledger 与 A-F 精确传播 |
| 127 | 短剧跨集资产 Used-By 与停用保护 | 四类 exact-version 反向索引、坏源 blocker、非破坏停用与新物化保护 |
| 128 | 短剧 ArtDirection 多 Scope 解析与冻结 | Episode > Series > Global、revision lineage、显式 clear 与跨 season retirement guard |
| 129 | 短剧资产管理 Web 总览与治理 | strict allowlist 六分区资产页、scope-aware/cross-season impact 与受控 CAS mutation |
| 130 | 短剧逐镜图片候选 Web 比较与选择 | strict/bounded C4 投影、metadata-safe exact PNG preview 与 guarded first/tail selection |
| 131 | 短剧逐镜视频候选 Web 与连续性门禁 | derived-only MP4 preview、attempt/coverage/continuity 投影与 guarded selection |
| 132 | 短剧 Web 合成、QA 与交付 | 持久 E3/current gate、本地 F1/F2 job、durable QA、四类 exact delivery 与 revision retention |
| 133 | 短剧持久媒体任务 DAG | episode-scoped strict ledger、active dedupe、guarded transition、failure/cancel cascade 与 unknown 零重提 |
| 134 | 短剧媒体 Worker Lease 与容量 Lane | 可信时钟 lease、owner-guarded replay、v1 在途 reconciliation 与跨集 provider×media capacity |
| 135 | 短剧媒体 Backend 能力注册与冻结解析 | 静态 capability registry、ID↔fingerprint 双向绑定与 submitted 后 frozen binding |
| 136 | 短剧媒体持久 Binding 与 Queue Client | ledger v3、provider task+binding 原子入队、legacy reconciliation 与 bounded wait/cancel |
| 137 | 短剧媒体 Owner-Guarded Provider Execution Loop | 显式 paid bridge、owner/context guarded step、inspect-or-submit crash takeover 与媒体特定 phase 路由 |
| 138 | 短剧媒体 Pricing Facts 与 Insights | 六类 append-only facts、精确定点金额、跨集 evidence 唯一性与 unknown-safe 多币种聚合 |
| 139 | 短剧媒体 Durable Lifecycle Metrics 与 Insights | 可信 ready/first-claim/terminal、legacy unknown、external exact evidence 与 terminal-denominator 指标 |
| 140 | 短剧 Typed Source Event Graph 与来源边界 | workspace/family 双 scope、source/invented、unknown causal、strict lineage、exact projection 与 no-follow store |
| 141 | Callback-only 公网素材回调与真视频安全尝试 | 独立 loopback 随机 capability 服务、Quick Tunnel 隔离、fixed single-submit；公网回读通过，provider 素材上传 safe-blocked、视频 create=0 |
| 142 | Provider 素材契约与 Episode 1 真视频闭环 | `data.Id/Status/base_resp` 严格适配、逐素材 durable upload ledger、exact-workspace profile；5.042 秒/720×1280 真实 MP4 完成，实际人民币费用未回报 |
| 143 | 真视频 20 秒质量样本 | 独立 sample namespace、20 秒 exact profile、prompt SHA lineage；真实 create 结果不明、无 task/MP4、费用 unknown、0 重试 |
| 144 | 仓库体检 findings 闭环 | 七份报告逐项核验；重试、job/Insights/pricing、mock、祖先 stale、旧视频与 workflow 残余闭环并删报告 |
| 145 | 短剧生产来源图适配与 RenderPlan 绑定 | entity/rolling-summary exact authority bytes、完整图 membership 与可重算 selection binding；source drift 精确传播为 stale/blocked |
| 146 | 短剧可失效 Context Memory Cache | text-free recent/summary/keyword identity cache、current H2/RenderPlan/policy exact binding、删除零影响与 drift/tamper 失效 |
| 147 | 短剧同源生产工作台投影 | current inspectors 安全聚合、list/canvas 同 fingerprint、零写入 GET 与真实 Web 闭环 |
| 148 | 短剧可移植项目归档 | strict portable snapshot、领域身份 preflight、exact media/evidence 与原子 no-overwrite 导入 |
| 149 | 体检报告路径、Job 与归档 CLI 闭环 | video ledger dirfd no-follow 读写删、坏 job 空投影、archive help，并在验收后删两份报告 |
| 150 | 短剧完整 SOP 前后端真人复验 | wire mutation/绕过、隔离 exact-duration A-F、取消恢复与 production UX；真文本/图窄校准，视频 create 前 safe-blocked |
| 151 | Workspace、Local Demo 与 Worker 体检闭环 | nofollow workspace identity、持久安全 target、FFmpeg/FFprobe 三层预检、test worker drain；验收后删除三份报告 |
| 152 | 小说续写 Web UI/UX 全量重设计 | 浅色中文设计系统、15 个桌面页、3 个平板页、6 个手机页、全操作/异常状态/API 映射与分期前端重构依据 |
| 153 | 小说 Web 浅色系统与共享组件落地 | Phase A/B 生产命名空间、中文失败关闭、44px 组件与实际 step 计费确认；24 组本地浏览器验证 |
| 154 | 小说 Web 公共页面 Phase C | 五个公共页生产级信息架构、响应式、异常恢复与安全动态投影；15 组真实浏览器验证 |
| 155 | 小说 Web 单章主流程 Phase D | 五个工作区主流程页、严格四阶段/readiness、持久任务恢复、编辑保护与三视口真实浏览器验证 |
| 156 | 小说 Web 高级与辅助页面 Phase E | 五个高级/辅助页、readiness/Paid 边界、只读区分、安全投影、兼容收口与三视口真实浏览器验证；Phase A-E 完成 |
| 157 | 近期体检报告安全与可靠性闭环 | KB/draft no-follow、安全异常投影、job 持久化准入/轮询终止与 owned verify 临时根 |
| 158 | 短剧 Web UIUX Phase A | 响应式 11 项导航壳、概览六态、同源 production 列表/六阶段画布与三视口 local-e2e |
| 159 | 短剧 Web UIUX Phase B | 五站创作台、当前集/季角色库、任务与编辑保护及三视口 local-e2e |
| 160 | 短剧 Web UIUX Phase C | 资产治理、逐镜图片/视频候选、安全 blob 预览与三视口 local-e2e |
| 161 | 短剧 Web UIUX Phase D | 合成交付、剧集、Insights、任务恢复与 Phase A-D 三视口全站收口 |
| 162 | 近期体检报告公开投影与 Web 边界闭环 | Job 身份脱敏、episode 2+、degraded Insights、DOM 与 cancel wire guard；验收后删两份报告 |
| 163 | 视频提交结果分流与历史 Unknown 对账 | create 未发送/拒绝/真正 unknown 三分状态、append-only CAS reconciliation receipt 与公开安全投影 |
| 164 | 近期体检报告任务恢复、传输分帧与视频计账闭环 | result context、workspace-scoped job、严格 HTTP framing 与 effective accounting；验收后删四份报告 |
| 165 | 小说 Web 模式语义与交互可靠性修复 | schema v2 原创/续写模式、阶段同源、分层导航/dirty、任务恢复与三视口 local-e2e |
| 166 | 小说原创/续写双链失败恢复与真模型前端验证 | 动态步骤安全投影、strict-approved 完成态、exact 失败章受控恢复、provider deadline 与窄范围真实前端证据 |
| 167 | 短剧模块安全分支拆分 | 完整基线固定到 `codex/short-drama`；main 物理收敛为 novel-only，legacy drama 只读隔离，canonical 升级 schema v3 |
| 168 | 小说续写体检与付费安全闭环 | mutation/intent/framing、metadata-only terminal、逐章 current-plan freshness、bounded JSONL、冻结定价/预算；真链 unknown 零重提 |
| 169 | 小说编辑与长程续写可靠性 | 保存版本确认、手改记忆恢复、单步取消、代理保留、人工大纲版本、lint 失败归档、全书规划窗口与伏笔证据 |
| 170（未完成） | 小说导入、编辑与长期状态修复 | 工程及浏览器通过，新key/luna10章提取成功；用户解除当前费用暂停条件后继续，全链仍在验收 |

## Iteration Implementation Index

> 说明列控制在 50 字以内；文件列只列主要落点，不代替各轮完整文件汇总。路线图、草稿和审计快照仍从 [`iterations/README.md`](iterations/README.md) 按需进入。

| Iter | 说明（≤50字） | 主要改动文件/目录 |
|---|---|---|
| 001-004 | 建立报告守门、真模型日志、preflight与切章置信度 | `main.py`、`src/llm_client.py`、`src/preflight.py`、`src/chapter_splitter.py`、`scripts/verify.sh` |
| 005-008 | 打通真debate/write/review，修JSON并隔离测试 | `src/debater.py`、`src/reviewer.py`、`src/writer.py`、`src/schemas.py`、`tests/__init__.py` |
| 009-013 | 加入风格、lint、实体关系、多章摘要和关系推进 | `src/style.py`、`src/linter.py`、`src/entities.py`、`src/chapter_summary.py`、`src/entity_advance.py` |
| 014-019 | 实现规划、五类bootstrap、多书、多语言和无人值守 | `src/plot_planner.py`、`src/auto_bootstrap.py`、`src/paths.py`、`src/epub_to_txt.py`、`scripts/write_book.sh` |
| 020-024 | 根修起点防剧透、上下文注入、预算与长程稳定性 | `src/start_point.py`、`src/source_excerpts.py`、`src/relationship_auditor.py`、`src/cost_estimator.py`、`src/writer.py` |
| 025-032 | 从只读面板扩展到向导、生产runner和Web工作台 | `src/auto_pipeline.py`、`src/book_runner.py`、`src/chapter_status.py`、`src/web/`、`main.py` |
| 033-035 | 补回收站、Insights、lint跳转、计划页和短剧定义 | `src/web/insights.py`、`src/web/trash.py`、`src/web/plan_view.py`、`docs/product/short_drama_module.md` |
| 036-038 | 建立短剧workspace、前两站向导并完成全仓加固 | `src/drama_planner.py`、`src/hook_designer.py`、`src/web/`、`docs/product/short_drama_creation_standard.md` |
| 039-042 | 修真实Web写作链、meta同步与三档评审；041仅诊断 | `src/writer.py`、`src/book_runner.py`、`src/reviewer.py`、`src/review_tier.py`、`src/web/jobs.py` |
| 043-045 | 完成UX与响应式收口、任务取消和本地Beta入口 | `src/web/jobs.py`、`src/web/routes.py`、`src/web/templates.py`、`src/web/static.py` |
| 046 | 实现AgentWrite分段生成并保持计划指纹兼容 | `src/schemas.py`、`src/plot_planner.py`、`src/writer.py`、`tests/test_plot_planner_segments.py`、`tests/test_writer_segments.py` |
| 046B | workspace缺persona时debate失败，阻断默认人格泄漏 | `src/debater.py`、`tests/test_debater_persona_guard.py` |
| 047 | 定义知识防剧透批次路线，实际由047a-d落地 | `docs/iterations/iteration_047_PLAN.md` |
| 047a | 新增分层token预算装配器与统一token计数 | `src/context_budget.py`、`src/llm_client.py`、`tests/test_context_budget.py` |
| 047b | 构建起点安全KB并接入写作、规划、辩论和外审 | `src/kb_view.py`、`src/writer.py`、`src/plot_planner.py`、`src/debater.py`、`src/book_runner.py` |
| 047c | 新增伏笔registry、TTL GC和must-resolve闸门 | `src/foreshadowing.py`、`src/book_runner.py`、`src/compressor.py`、`src/preflight.py` |
| 047d | 为事实和关系增加读者/角色已知防剧透轴 | `src/entities.py`、`src/manual_facts.py`、`src/schemas.py`、`tests/test_reader_character_filter.py` |
| 047B2 | 对抗验收046/047并修坏JSON、起点、伏笔和预算 | `src/kb_view.py`、`src/start_point.py`、`src/foreshadowing.py`、`src/context_budget.py`、`src/writer.py` |
| 048a | 搭四步工作台后端、premise建库和模型诊断 | `src/auto_pipeline.py`、`src/llm_client.py`、`src/web/jobs.py`、`src/web/wizard.py`、`src/web/diag.py` |
| 048b | 上线四步工作台前端、阶段判定和大纲编辑 | `src/web/routes.py`、`src/web/templates.py`、`src/web/static.py`、`tests/test_workbench_e2e.py` |
| 048c | 加入细纲预览/重生成并闭合写书指纹链 | `src/web/templates.py`、`src/web/static.py`、`tests/test_workbench_replan.py` |
| 048d | 修工作台并发、step readiness和诊断脱敏 | `src/llm_client.py`、`src/web/settings.py`、`src/web/routes.py`、`src/web/jobs.py` |
| 049 | 接入Aeloon插件、共享client/MCP和Bearer保护 | `integrations/aeloon_plugin/`、`integrations/novel_client/`、`integrations/novel_ops/`、`integrations/mcp_server/`、`src/web/auth.py` |
| 050 | 打通细纲、正文、知识库和实体编辑，加入预算护栏 | `src/plot_planner.py`、`src/writer.py`、`src/web/routes.py`、`src/web/static.py`、`src/utils.py` |
| 051 | 新增premise扩写与编辑，补评审预算和起点校验 | `src/premise_expansion.py`、`src/start_point.py`、`src/web/wizard.py`、`src/web/jobs.py`、`src/auto_pipeline.py` |
| 052 | 正式化长程分段驱动、断点续跑、总预算和进程管理 | `src/book_driver.py`、`scripts/drive_book.sh`、`src/writer.py`、`src/config.py`、`tests/test_book_driver.py` |
| 053 | 给辩论/规划加起点血统闸，强化canon和评审回灌 | `src/debater.py`、`src/plot_planner.py`、`src/writer.py`、`src/reviewer.py`、`src/auto_bootstrap.py` |
| 054 | 建立深起点ingest/rebuild，按起点过滤派生知识 | `src/start_point.py`、`src/auto_pipeline.py`、`src/auto_bootstrap.py`、`src/compressor.py`、`src/book_runner.py` |
| 055 | 为真模型加入分任务超时、分类重试和续抽策略 | `src/llm_client.py`、`src/extractor.py`、`src/config.py`、`config/models.yaml`、`src/auto_pipeline.py` |
| 056 | 新增原创书风格卡、预置库、样本提取和缓存注入 | `src/writer_style.py`、`config/style_presets.json`、`src/writer.py`、`src/web/routes.py`、`src/web/jobs.py` |
| 057 | 修规划指纹、流式卡死、旧章记忆和大纲漂移 | `src/book_driver.py`、`config/models.yaml`、`src/plot_planner.py`、`src/chapter_summary.py`、`src/outline_drift.py`、`scripts/migrate_plan_fingerprints.py` |
| 058 | 补onboarding预算、抽取显错和非有限浮点守门 | `src/web/routes.py`、`src/web/wizard.py`、`src/web/jobs.py`、`src/auto_pipeline.py`、`tests/test_float_finite_guard.py` |
| 059 | 将坏JSON、非法整数和坏上传转为可恢复blocker | `src/web/jobs.py`、`src/web/routes.py`、`src/chapter_status.py`、`src/book_driver.py`、`src/book_runner.py` |
| 060 | 收口写端并发、原子写、取消检查点和残余输入守门 | `src/web/routes.py`、`src/web/jobs.py`、`src/book_runner.py`、`src/debater.py`、`tests/test_iter060_p2.py` |
| 061 | 热修风格样本路径穿越，改用目录内随机token | `src/web/routes.py`、`src/web/jobs.py`、`tests/test_web_writer_style.py` |
| 062 | 统一Web错误卡、步骤导航和未开放短剧页签锁定 | `src/web/errors.py`、`src/web/routes.py`、`src/web/settings.py`、`src/web/static.py`、`src/web/templates.py` |
| 063 | 修复Web复审缺陷，并合并readiness语义目录 | `src/readiness_catalog.py`、`src/web/errors.py`、`src/web/jobs.py`、`src/web/routes.py`、`src/book_runner.py` |
| 064 | 统一CLI/Web/driver参数校验和typed stale错误 | `src/run_params.py`、`main.py`、`src/book_driver.py`、`src/plot_planner.py`、`src/web/errors.py` |
| 065 | 加入计划履约建议，并支持受控创建实体关系 | `src/reviewer.py`、`src/writer.py`、`src/entity_advance.py`、`src/book_runner.py`、`config/agents.yaml` |
| 066 | 硬化实体推进与resume数值，放宽长程规划上限 | `src/entity_advance.py`、`src/book_runner.py`、`src/book_driver.py`、`src/run_params.py`、`main.py` |
| 067 | 拒绝布尔/非有限数，并禁止JSON持久化NaN/Infinity | `src/run_params.py`、`src/book_driver.py`、`src/utils.py`、`tests/test_write_json_finite.py` |
| 068 | 新增底座重建job、分阶段进度、取消和预算readiness | `src/web/routes.py`、`src/web/jobs.py`、`src/web/static.py`、`src/auto_pipeline.py`、`src/extractor.py`、`src/readiness_catalog.py` |
| 069 | 重构首页三入口、顶栏命名和向导分流 | `src/web/templates.py`、`src/web/static.py`、`tests/test_web_routes_get.py` |
| 070 | 统一首页导航并增加离开工作区任务确认 | `src/web/templates.py`、`src/web/static.py`、`tests/test_web_routes_get.py` |
| 071 | 扩展离开守卫，新增active-jobs真源和模态焦点 | `src/web/templates.py`、`src/web/jobs.py`、`src/web/routes.py`、`src/web/static.py` |
| 072 | 收口侧栏守卫、任务公开视图、排序和模态可访问性 | `src/web/templates.py`、`src/web/static.py`、`src/web/jobs.py`、`src/web/routes.py` |
| 073 | 阻断计划失约/严重漂移，并硬化job公开投影 | `src/reviewer.py`、`src/book_runner.py`、`src/outline_drift.py`、`src/web/jobs.py`、`config/agents.yaml` |
| 074 | 新增章节版本枚举、安全diff API和Web对比面板 | `src/web/chapter_diff.py`、`src/web/routes.py`、`src/web/static.py`、`tests/test_web_chapter_diff.py` |
| 075 | 新增跨章全文搜索、范围过滤、高亮和结果页 | `src/search.py`、`src/web/routes.py`、`src/web/templates.py`、`src/web/static.py`、`tests/test_search.py` |
| 076 | 硬化搜索/diff并加入长跑策略、预算预留和监督器 | `src/search.py`、`src/web/chapter_diff.py`、`src/book_runner.py`、`src/book_driver.py`、`scripts/drive_book_supervised.sh` |
| 077 | 修伏笔边界、caveat恢复、陈旧拒稿和孤儿进程 | `src/foreshadowing.py`、`src/book_runner.py`、`src/book_driver.py`、`src/chapter_status.py`、`src/preflight.py` |
| 078 | 完成评分、成本、锁、摘要顺序和实体补偿硬化 | `src/reviewer.py`、`src/workspace_lock.py`、`src/book_runner.py`、`src/entity_advance.py`、`src/cost_estimator.py` |
| 079 | 收口Web/CLI写锁、实体提案缺口和mock预算演练 | `src/web/routes.py`、`src/web/jobs.py`、`main.py`、`src/book_runner.py`、`src/cost_estimator.py` |
| 080 | 实现短剧站③分镜生成、编辑、排序和网格界面 | `src/drama_schemas.py`、`src/storyboard_builder.py`、`src/web/routes.py`、`src/web/static.py`、`tests/test_drama_storyboard_grid.py` |
| 081 | 实现站④角色设计、角色库、引用图和绘图安全骨架 | `src/drama_schemas.py`、`src/character_designer.py`、`src/ai_draw_client.py`、`src/web/routes.py`、`src/web/static.py` |
| 082 | 实现短剧评审、整集组装、建议应用和剧集详情页 | `src/drama_reviewer.py`、`src/drama_store.py`、`src/web/routes.py`、`src/web/templates.py`、`tests/test_drama_store.py` |
| 083 | 建立本地文风指纹基线、草稿检测和CLI产物路径 | `src/style_fingerprint.py`、`config/style_fingerprint.yaml`、`src/paths.py`、`main.py` |
| 084 | 新增文风漂移报告，接入写章meta和Web展示 | `src/style_drift.py`、`src/writer.py`、`src/web/templates.py`、`src/web/static.py`、`tests/test_style_drift.py` |
| 085 | 将漂移映射为改写指令并接入非投票风格advisor | `src/schemas.py`、`src/style_drift.py`、`src/reviewer.py`、`tests/test_style_rewrite_directives.py` |
| 086 | 指纹升至v2，硬化可靠度、哈希、聚合和Web状态 | `src/style_fingerprint.py`、`config/style_fingerprint.yaml`、`src/style_drift.py`、`main.py`、`src/web/static.py` |
| 087 | 实现红灯单次文风改写、择优回退和状态展示 | `src/style_drift.py`、`src/writer.py`、`src/reviewer.py`、`src/chapter_status.py`、`src/web/static.py` |
| 088 | 新增四格式导出、短剧Insights和第2集流程 | `src/comfy_workflow_exporter.py`、`src/web/drama_insights.py`、`src/drama_store.py`、`src/web/routes.py`、`tests/test_drama_exports.py` |
| 089 | 接入真生图/视频客户端和授权、SSRF、落盘守门 | `src/ai_draw_client.py`、`src/drama_video_client.py`、`src/drama_image_smoke.py`、`src/preflight.py`、`src/web/routes.py` |
| 090 | 五站改为可恢复job，加入真文本预算闸和全链smoke | `src/drama_planner.py`、`src/web/routes.py`、`src/web/jobs.py`、`src/drama_smoke.py`、`scripts/drama_smoke.sh` |
| 091 | 实现单集真视频job、安全下载和Web播放闭环 | `src/drama_video.py`、`src/drama_video_client.py`、`src/drama_video_smoke.py`、`src/web/jobs.py`、`src/web/routes.py` |
| 092 | 新增可恢复多模态联测和生图三次授权重试边界 | `src/drama_multimodal_smoke.py`、`scripts/drama_multimodal_smoke.sh`、`src/ai_draw_client.py`、`src/web/routes.py` |
| 093 | 重构文档分层、压缩默认记忆并合并阶段总结 | `AGENTS.md`、`README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md`、`docs/iterations/README.md` |
| 094 | 硬化多模态校准证据并再平衡项目记忆/收官顺序 | `src/drama_multimodal_smoke.py`、`src/drama_smoke.py`、`tests/test_drama_multimodal_smoke.py`、`AGENTS.md`、`docs/` |
| 095 | 实现连续多集、freshness v2 与整季双包交付 | `src/drama_store.py`、`src/drama_season_export.py`、`src/web/routes.py`、`src/web/static.py`、`tests/test_drama_iter095_*.py` |
| 096 | 收紧 LiteLLM mock 为可审计的物理零网络路径 | `src/config.py`、`src/llm_client.py`、`src/context_budget.py`、`scripts/verify.sh`、`tests/test_mock_offline.py` |
| 097 | 硬化短剧真文本/图片/视频付费恢复边界 | `src/drama_multimodal_smoke.py`、`src/drama_video.py`、`src/ai_draw_client.py`、`src/web/jobs.py`、`tests/test_drama_iter097_hardening.py` |
| 098 | 收口短剧五站/媒体 crash 恢复与证据血统 | `src/secure_http.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py`、`src/web/jobs.py`、`tests/test_drama_iter098_hardening.py` |
| 099 | 收紧短剧 readiness、脏账本与媒体恢复身份 | `src/drama_smoke.py`、`src/ai_draw_client.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py`、`tests/test_drama_iter099_hardening.py` |
| 100 | 修复短剧真模型全链恢复与入口阻塞 | `src/web/jobs.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py`、`src/web/static.py`、`tests/test_drama_iter100_hardening.py` |
| 101 | 修复短剧完整链路残余阻塞 | `src/drama_store.py`、`src/character_designer.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py`、`tests/test_drama_iter101_blockers.py` |
| 102 | 隔离 canonical 验收并绑定审计基线 | `scripts/verify.sh`、`scripts/write_acceptance.py`、`scripts/check_agent_harness.py`、`src/config.py`、`tests/test_agent_harness.py` |
| 103 | 建立本地 fake-provider 短剧整链验收 | `scripts/run_local_drama_e2e.py`、`tests/support/local_drama_*.py`、`scripts/verify.sh`、`tests/test_local_drama_e2e.py` |
| 104 | 建立跨进程 crash/restart 与付费状态矩阵 | `src/paid_recovery_states.py`、`src/web/jobs.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py`、`tests/test_drama_*matrix.py` |
| 105 | 统一短剧单集冻结角色投影与消费端血统 | `src/drama_store.py`、`src/drama_reviewer.py`、`src/drama_season_export.py`、`src/drama_video.py`、`tests/test_drama_iter105_character_projection.py` |
| 106 | 建立 strict RenderPlan 与创作源 stale 边界 | `src/drama_schemas.py`、`src/drama_store.py`、`src/drama_render_plan.py`、`src/drama_render_store.py`、`tests/test_drama_render_*.py` |
| 107 | 建立角色资产版本、selected CAS 与单集冻结引用 | `src/drama_schemas.py`、`src/drama_assets.py`、`src/drama_asset_versions.py`、`tests/test_drama_asset*.py` |
| 108 | 建立 ArtDirection 版本、selected CAS 与 RenderPlan/manifest stale 桥接 | `src/drama_schemas.py`、`src/drama_assets.py`、`src/drama_art_direction_store.py`、`src/drama_render_store.py`、`src/workspace_lock.py`、`tests/test_drama_art_direction*.py` |
| 109 | 建立 SceneAsset 版本、selected CAS 与逐镜冻结引用 | `src/drama_schemas.py`、`src/drama_assets.py`、`src/drama_asset_versions.py`、`tests/test_drama_scene_asset*.py` |
| 110 | 建立 PropOrClueAsset 版本与逐镜零到多冻结引用 | `src/drama_schemas.py`、`src/drama_assets.py`、`src/drama_asset_versions.py`、`tests/test_drama_prop_clue_asset*.py` |
| 111 | 建立逐镜图片规格、引用装配与五态 store | `src/drama_schemas.py`、`src/drama_shot_image.py`、`src/drama_shot_image_store.py`、`tests/test_drama_shot_image*.py` |
| 112 | 建立结构化迭代上下文与经验晋升门禁 | `.agents/skills/iter-*`、`scripts/check_agent_harness.py`、`tests/test_agent_harness.py` |
| 113 | 建立逐镜图片候选、首尾帧 lineage 与显式恢复 | `src/drama_schemas.py`、`src/drama_shot_image_candidates.py`、`src/drama_shot_image_candidate_store.py`、`tests/test_drama_shot_image_candidate*.py` |
| 114 | 建立逐镜图片 capability、once-only attempt、receipt 与 crash recovery | `src/drama_schemas.py`、`src/drama_shot_image_attempts.py`、`src/drama_shot_image_attempt_store.py`、`tests/test_drama_shot_image_attempt*.py` |
| 115 | 建立逐镜视频计划、冻结首尾帧 lineage 与五态 store | `src/drama_schemas.py`、`src/drama_shot_video.py`、`src/drama_shot_video_store.py`、`tests/test_drama_shot_video*.py` |
| 116 | 建立逐镜视频候选、显式选择与整集覆盖门禁 | `src/drama_schemas.py`、`src/drama_shot_video_candidates.py`、`src/drama_shot_video_candidate_store.py`、`tests/test_drama_shot_video_candidate*.py` |
| 117 | 建立逐镜视频 capability、once-only attempt、receipt 与 crash recovery | `src/drama_schemas.py`、`src/drama_shot_video_attempts.py`、`src/drama_shot_video_attempt_store.py`、`tests/test_drama_shot_video_attempt*.py` |
| 118 | 验证并修复短剧现有完整真人用户 SOP | `src/web/`、`src/ai_draw_client.py`、`src/drama_multimodal_smoke.py`、`tests/test_drama_*.py` |
| 119 | 建立逐镜视频连续性与 production compose gate | `src/drama_schemas.py`、`src/drama_shot_video_continuity.py`、`tests/test_drama_shot_video_continuity.py` |
| 120 | 建立 Voice Profile、显式 assignment 与逐句音频计划 | `src/drama_schemas.py`、`src/drama_audio.py`、`tests/test_drama_audio.py` |
| 121 | 建立 provider-neutral once-only TTS attempt 与恢复 store | `src/drama_schemas.py`、`src/drama_tts_attempts.py`、`src/drama_tts_attempt_store.py`、`tests/test_drama_tts_attempt*.py` |
| 122 | 建立唯一 TimelineManifest、字幕 revision 与同源 SRT | `src/drama_schemas.py`、`src/drama_timeline.py`、`tests/test_drama_timeline.py` |
| 123 | 建立固定 profile 本地 FFmpeg 完整成片与媒体 QA | `src/drama_compositor.py`、`src/drama_media_qa.py`、`tests/test_drama_compositor.py` |
| 124 | 修复两集桌面 SOP、多集编辑与任务日志安全可读投影 | `src/storyboard_builder.py`、`src/web/`、`tests/test_drama_storyboard_builder.py`、`tests/test_web_routes_get.py` |
| 125 | 建立同源 ASS、六轨可编辑工程与安全完成协议 | `src/drama_schemas.py`、`src/drama_edit_export.py`、`tests/test_drama_edit_export.py` |
| 126 | 建立 visual override、可恢复选择与 stale 矩阵 | `src/drama_schemas.py`、`src/drama_visual_overrides.py`、`tests/test_drama_visual_overrides.py` |
| 127 | 建立跨集资产使用索引与非破坏停用治理 | `src/drama_schemas.py`、`src/drama_asset_usage.py`、`src/drama_asset_versions.py`、`tests/test_drama_asset_usage.py` |
| 128 | 建立 ArtDirection 多 Scope 解析与 RenderPlan 冻结 | `src/drama_art_direction_scope.py`、`src/drama_render_store.py`、`src/drama_asset_usage.py`、`tests/test_drama_art_direction_scope.py` |
| 129 | 建立资产治理 Web 投影与受控 mutation | `src/drama_asset_web.py`、`src/web/`、`tests/test_drama_asset_web.py`、`tests/test_web_server.py` |
| 130 | 建立逐镜图片候选比较、选择与安全预览 Web | `src/drama_shot_image_web.py`、`src/web/`、`tests/test_drama_shot_image_web.py`、`tests/test_web_server.py` |
| 131 | 建立逐镜视频候选、连续性与安全派生预览 Web | `src/drama_shot_video_web.py`、`src/drama_shot_video_candidate_store.py`、`src/web/`、`tests/test_drama_shot_video_web.py` |
| 132 | 建立短剧 Web 本地合成、durable QA 与 exact delivery | `src/drama_compose_web.py`、`src/drama_compositor.py`、`src/web/`、`tests/test_drama_compose_web.py` |
| 133 | 建立持久媒体 task DAG 与安全状态投影 | `src/drama_schemas.py`、`src/drama_media_tasks.py`、`tests/test_drama_media_tasks.py` |
| 134 | 建立 worker lease、认证 replay 与跨集容量 lane | `src/drama_schemas.py`、`src/drama_media_tasks.py`、`src/drama_media_worker.py`、`tests/test_drama_media_worker.py` |
| 135 | 建立静态 backend registry 与 frozen task binding | `src/drama_schemas.py`、`src/drama_media_backends/`、`tests/test_drama_media_backend_registry.py` |
| 136 | 建立持久 backend binding 与纯本地 queue client | `src/drama_schemas.py`、`src/drama_media_tasks.py`、`src/drama_media_worker.py`、`src/drama_media_queue_client.py`、`tests/test_drama_media_queue_client.py` |
| 137 | 建立 owner-guarded provider execution loop 与 paid bridge | `src/drama_media_executor.py`、`tests/test_drama_media_executor.py`、`tests/support/drama_media_executor_driver.py` |
| 138 | 建立 strict pricing facts 与安全 Insights | `src/drama_media_pricing.py`、`src/web/drama_insights.py`、`tests/test_drama_media_pricing.py` |
| 139 | 建立 durable media lifecycle metrics 与安全 Insights | `src/drama_media_tasks.py`、`src/drama_media_metrics.py`、`src/web/drama_insights.py`、`tests/test_drama_media_metrics.py` |
| 140 | 建立 typed source event graph 与来源边界 | `src/drama_schemas.py`、`src/drama_event_graph.py`、`tests/test_drama_event_graph.py` |
| 141 | 建立 callback-only 素材服务与单提交门禁 | `src/drama_asset_callback_server.py`、`src/drama_video.py`、`scripts/drama_asset_callback.sh`、`scripts/drama_video_episode1_single_submit.sh` |
| 142 | 建立 provider 素材写入恢复与单次真视频闭环 | `src/drama_video.py`、`src/drama_video_client.py`、`scripts/drama_video_episode1_single_submit.sh` |
| 143 | 建立独立 20 秒质量样本与 exact lineage | `src/drama_video.py`、`src/drama_video_smoke.py`、`scripts/drama_video_episode1_quality20_single_submit.sh` |
| 144 | 闭环七份体检报告的仍成立问题 | `src/llm_client.py`、`src/web/jobs.py`、`src/web/drama_insights.py`、`src/drama_media_pricing.py`、`src/drama_store.py` |
| 145 | 绑定生产来源快照、事件图与 RenderPlan 选择 | `src/drama_source_adapter.py`、`src/drama_render_plan.py`、`src/drama_render_store.py`、`src/drama_schemas.py` |
| 146 | 建立可失效、text-free Context Memory Cache | `src/drama_context_memory.py`、`src/drama_schemas.py`、`tests/test_drama_context_memory.py` |
| 147 | 建立同源只读 Production Workbench | `src/drama_production_workbench.py`、`src/drama_compose_web.py`、`src/web/`、`tests/test_drama_production_workbench.py` |
| 148 | 建立可校验项目归档与安全导入 | `src/drama_project_archive.py`、`main.py`、`tests/test_drama_project_archive.py` |
| 149 | 闭环 video ledger、job 巨整数与 archive help | `src/drama_video.py`、`src/web/jobs.py`、`main.py`、`tests/test_drama_video.py` |
| 150 | 真人复验并修复短剧现有 SOP | `src/drama_local_demo.py`、`src/web/`、`scripts/run_local_drama_e2e.py`、`tests/test_drama_*.py` |
| 151 | 闭环 workspace、Local Demo、媒体预检与 test worker | `src/paths.py`、`src/drama_local_demo.py`、`src/web/`、`tests/test_*.py` |
| 152 | 建立小说续写 Web UI/UX 重构规范与 Figma 交付 | `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`、Figma、iteration 文档 |
| 153 | 落地小说 Web 浅色变量、中文层与共享组件 | `src/web/templates.py`、`src/web/static.py`、`tests/test_web_ui_design_system.py` |
| 154-157 | 完成小说 Web Phase C-E 与近期体检闭环 | `src/web/`、`tests/test_web_*.py`、`scripts/verify.sh` |
| 158 | 重构短剧导航壳、概览与生产工作台 | `src/web/templates.py`、`src/web/static.py`、`tests/test_drama_web_uiux_phase_a.py` |
| 159 | 重构五站创作台与角色库 | `src/web/templates.py`、`src/web/static.py`、`tests/test_drama_web_uiux_phase_b.py` |
| 160 | 重构资产治理与逐镜媒体候选 | `src/web/templates.py`、`src/web/static.py`、`tests/test_drama_web_uiux_phase_c.py` |
| 161 | 重构合成交付、剧集、数据与任务页 | `src/web/templates.py`、`src/web/static.py`、`tests/test_drama_web_uiux_phase_d.py` |
| 162 | 闭环公开投影、多集上下文与 cancel 边界 | `src/web/jobs.py`、`src/web/routes.py`、`src/web/server.py`、`src/web/static.py`、`tests/test_web_iter162_health_closure.py` |
| 163 | 区分视频 create 结果并建立历史对账链 | `src/drama_video.py`、`src/drama_video_client.py`、`src/drama_video_reconciliation.py`、`src/web/`、`tests/test_drama_video_reconciliation.py` |
| 164 | 闭环任务恢复、传输分帧与视频计账 | `src/web/`、`src/drama_multimodal_smoke.py`、`tests/test_web_iter164_health_closure.py`、`tests/test_drama_multimodal_smoke.py` |
| 165 | 闭环小说模式语义、导航与任务恢复 | `src/web/`、`integrations/novel_ops/`、`tests/test_web_iter165_ux_reliability.py`、`tests/test_workspace_meta.py` |
| 166 | 闭环小说双链失败章恢复与模型调用守门 | `src/book_runner.py`、`src/llm_client.py`、`src/web/`、`tests/test_web_iter166_recovery.py`、`tests/test_iter166_model_request_limit.py` |
| 167 | 安全拆分短剧并建立 novel-only 边界 | `main.py`、`src/web/`、`scripts/verify.sh`、`scripts/check_novel_only_boundary.py`、`tests/test_iter167_novel_only_split.py` |
| 168 | 闭环小说 mutation、异常、freshness 与日志边界 | `src/llm_client.py`、`src/safe_*.py`、`src/web/`、`integrations/novel_client/`、`tests/test_iter168_novel_health_security.py` |
| 169 | 编辑版本与衍生记忆恢复，分段规划和伏笔证据 | `src/story_memory.py`、`src/web/`、`src/book_runner.py`、`src/foreshadowing.py`、`tests/test_iter169_reliability.py` |

## Durable Decisions

### Mock first

- 单测与 `verify.sh` 永远强制 mock，不能从 `.env` 泄漏到真实 provider。
- mock 的边界包含 LiteLLM import、代理准备和 tokenizer 冷缓存：必须在首次导入前固定本地 cost map，跳过代理探测，并以网络审计执行实际 completion/preflight；真实分支保持原 provider 行为。
- 可选知识源缺失时，裸仓库工程验证必须 graceful degrade。
- mock 只能证明编排和守门，不能证明真模型质量、费用或时延。

### Fail closed at paid and irreversible boundaries

- 模型/provider、预算、超时、workspace、episode、fingerprint 与 artifact path 在调用或写盘前验证。
- JSON/schema 失败不能静默 Approve；必要时修复已知字段，否则显式 Abstain/blocked。
- 计费媒体使用独立确认和预算。授权不从旧 job/state 继承，也不跨文本、图片、视频阶段复用。
- 文本、图片、视频可以保留各自 ledger schema，但持久状态词汇与关键分类必须由共享不可变常量驱动；新增状态会让矩阵失败，直到完成显式分类，不为统一外观提前迁移 paid ledger。
- 通用媒体 task 只编排 identity/dependency/state，不保存或替代 provider task、response、receipt 与 paid attempt evidence。`submission_unknown` 在 generic DAG 无出边并持续占用 dedupe；未来恢复必须走绑定权威 paid evidence 的专用 reconciliation。
- 通用媒体 worker ownership 只使用 workspace lock 内可信时钟；执行态 mutation 与 lost-response replay 必须绑定 current owner/token、task/lease revision 和内容寻址 receipt。过期 lease 不能靠 replay 恢复成功，takeover 必须轮换 token；缺少 owner 证据的 legacy 在途态只能 safe-block reconciliation。
- 通用 backend registry 只接受代码内显式、deep-frozen、内容寻址声明；provider/model ID 与 fingerprint 必须双向唯一并同时匹配 task。首次 binding 要冻结完整 capability/registration；进入 submitting 后不得从 current registry 重解释。C/D/E source capability 必须在转换入口重新验证，TTS synthesis 与 download 恢复语义不得被通用化抹平。
- provider task 与完整 backend binding 必须在 ledger v3 同一 workspace lock/CAS 中原子持久化；legacy provider task 明示 unbound 并等待权威 paid evidence reconciliation，不能从 current registry 补猜。本地 compose/export 明示 binding 不适用；queue wait 必须由调用方 monotonic deadline 严格约束。
- provider execution bridge 必须由受审查代码显式注入，并逐项绑定 frozen backend/task、current owner/token、lease revision 与 deadline context；外部动作前 heartbeat、动作后 CAS，且不持 workspace lock。submit 不明永不自动重发，崩溃接管只能通过权威 paid ledger 的 inspect-or-submit 恢复；generic observation 只留内容寻址 evidence fingerprint，不能保存或冒充 provider task、response、prompt、URL、path 或 paid receipt。
- 媒体 pricing facts 与 provider billing 必须分层：persisted amount 只接受精确定点微单位，estimate/authorized/reserved/actual/refunded/unknown 保留不同事实语义；unknown 不能归零，多币种不能隐式换汇或跨币种求和。evidence fingerprint 要在写侧与读侧按工作区唯一，namespace 扫描和提交必须绑定同一 nofollow directory fd；歧义、坏源或聚合超限应返回空的 degraded 汇总，而不是 partial totals。
- 媒体 lifecycle 延迟只能来自可信锁内 mutation 与 exact evidence：ready、first claim、terminal 必须单调并与 task/lease 绑定，legacy 缺失保持 unknown，不能从 caller time、最后 lease 或 `updated_at-created_at` 补猜。成功率只以 terminal task 为分母，queue/run 必须分列 known/unknown sample；应用层 create-once/content-addressed sidecar 不是签名，也不防有本机写权限者同时伪造新 ledger 与 sidecar。
- 临时公网素材回调必须与完整 Web 工作台物理分离：Tunnel 只指向 loopback callback-only 端口，成功面仅为 exact 随机 capability GET；raw query/encoding/尾斜杠/其他方法和路径统一 404，连接与并发有界，token 用后撤销。Quick Tunnel 地址不稳定，不能写入代码或视为长期部署。
- provider asset upload 与最终 video create 是两个独立外部写边界：每次 POST 前分别持久化 ambiguity marker；只有 transport 明确证明 request not sent 才能释放重试机会，已确认 asset ID 可以续用，unknown 不能自动重发或被费用 `null` 伪装成 0。
- video create 结果必须封闭为 transport 证明的 `request_not_sent`、provider 4xx 明确 `provider_rejected`、以及发送后响应丢失/不可判定的 `submission_unknown`；任务列表未增加只是负观察，不能把历史 unknown 改判为未提交或释放授权。历史对账使用独立 append-only receipt chain，绑定 exact submission identity/revision、sidecar generation 与 ledger fingerprint；一旦权威 task/rejection 结论形成，后续不能换身份改写。公开投影不得暴露 task/request ID、响应正文、素材身份或证据指纹。
- iter143 之后的真实闭环不是一份总授权：只读 task/billing/rejection（upload/create=0）、真实 TTS adapter 后 1 条语音、新 namespace 单镜图片/视频、完整单集、episode 2+/多集是五个依次独立授权阶段，前序证据和授权不自动传递。
- 质量标定样本必须同时冻结 sample namespace、目标时长、实际 prompt SHA 与授权 fingerprint；仅保存 prompt 版本字符串不足以证明样本可比，样本产物和 ledger 也不能与默认 smoke 共用路径。
- 付费失败恢复是新的受控提交，不能退化成通用 force：资格必须绑定 exact durable terminal、当前 creation mode、strict plan 与完整上游 freshness、内容无关状态指纹和 durable ledger claim，并在归档或模型调用所在写锁内复核恢复任务自身仍有 durable pending/running row；漂移、歧义或 slot 未释放一律拒绝且不自动重提。

### Keep state auditable

- 每轮 iteration 保留 8 段结构、验收命令、审查结论与未修风险。
- iter112 起在原 8 段内维护结构化 Implementation/Review Context 与 Knowledge Promotion；它们只为实现和审查路由服务，不创建第二套任务状态。`must_read` 与晋升目标必须是 Git tracked 的仓库相对普通文件，accepted 前轮不能因新 active 轮出现而停止复核。
- 聚合交付包从 canonical assembled JSON 重建；不直接归档工作目录，manifest 只公开受控字段并对成员做 SHA-256。
- 可移植项目 archive 也不是 raw workspace backup：creative 必须经 strict allowlist 重建，selection/render/timeline/QA/delivery 除 member hash 外还要交叉绑定领域身份。导入只能原子 no-overwrite 创建新 workspace；receipt 驱动的 re-export 可证明快照内部一致，但无签名/MAC 时不证明外部 provenance，也不等于可继续 provider 任务的 runnable workspace。
- LLM 调用、writer meta、review、driver state、style drift 和媒体 attempt 只记录排障所需的有界、脱敏数据。
- 运行中的草稿、失败、snapshot 和 resume 状态要完整落盘；成功/拒稿/中止不能靠文件是否存在猜测。
- 计费恢复身份要区分不可变上游输入与本次站点输出；callback/ledger 提交前崩溃时只能凭 durable receipt、provider 与产物血统零网络收尾，不能用会被本次结果改写的全量输入指纹判断 stale。

### Keep novel creation mode server-authoritative

- 小说 workspace 的原创/导入续写来源必须持久化为 schema v2 `creation_mode`，由服务端向 overview、workbench、readiness 与 run 同源投影并在任务创建前执行守门；不能从“当前是否已有续写起点”反推来源模式。
- legacy workspace 只允许 no-follow、regular-file 的只读安全推断；只有正规 `seed.txt` 且无 `upload.txt` 才视为 greenfield，其余歧义保守 continuation。GET 不迁移、不改盘，损坏 metadata 必须 fail-closed。

### Keep product branches and legacy data fail-closed

- iter167 将完整小说+短剧基线固定在 `codex/short-drama`，main 仅支持 novel。分支保存的是可运行快照，不是从主线删除历史审计记录。
- “可识别 workspace 类型”与“当前分支支持类型”必须分开：legacy `drama` metadata 只用于防止误判为小说，不能因此获得创建、枚举、direct route、import、trash 或 mutation 能力。
- destructive 操作不能只在路径检查后执行。trash restore/purge 需要锁、nofollow parent fd、对象 identity 二次匹配和 dir-fd 操作；unsupported 与不存在对公开调用方使用相同投影，避免泄漏隐藏数据存在性。
- novel-only 静态检查必须覆盖 generic media/production 名称，而不只搜索 `drama` 字面量；允许项限定为禁用入口、legacy sentinel、迁移说明和历史审计。

### Separate current truth from history

- `AGENTS.md` 是长期规则；`AGENT_HANDOFF.md` 是当前快照；README SOP 是节点状态；iteration 是历史证据。
- handoff 不再累积逐轮 Phase Status，但保留数百行经筛选的阶段级工作记忆；本文件保留架构历史与长期教训，细节链接到原 iteration。
- handoff 与本文件都是新 session 默认读物。压缩目标是去掉重复验收和过时 snapshot，不是去掉会影响接力判断的设计背景、失败模式与恢复知识。

### Review before expensive full validation

- 实现阶段先用聚焦测试、语法/静态检查和 diff 检查获得快速反馈。
- 收官先完成 correctness、security/boundary 及风险专项多视角审查，修复 findings 后做聚焦回归。
- findings 稳定后、implementation commit 前人工决定经验是否晋升；若晋升修改了 skill、checker 等非 docs-only 权威文件，必须与实现一起进入唯一 canonical 验收，不能留到验收后的收官提交。
- 耗时的 canonical + `verify.sh` + preflight 放在上述修复之后，作为最终全量闸门只跑一次；最终闸门失败时再按失败范围修复和重验。

## Engineering Lessons

1. **配置语义必须直观且硬校验**：早期 `rewrite_max` 的含义与名字不一致，最终改为 `max_review_attempts` 并移除兼容分支。模糊配置会变成运行时事故。
2. **Prompt 约束不能替代本地 normalization**：真模型曾返回空 ballot、缺字段 review 和近似 JSON。可靠路径需要 schema、repair、retry 与 fail-closed fallback 配合。
3. **测试隔离要有多层防线**：只在测试包入口设 mock 不够，直接 discovery 可能绕过它；配置加载和验证脚本也必须显式隔离。
4. **起点安全是数据摄入问题**：仅在 prompt 里说“不要剧透”不构成硬保证。需要 start-aware 提取、知识视图、指纹和物理过滤；即便如此，模型预训练记忆仍只能缓解，不能绝对消除。
5. **长流程必须能恢复而不是只会重跑**：预算账本、step timeout、snapshot、heartbeats、supervisor、workspace lock 和幂等 resume 是一组能力，缺一项都会在长跑中放大成本。
6. **同一处置语义只能有一个真源**：readiness、runner、Web 卡片和 resume 曾多次因平行判断漂移。分类、参数和错误目录应下沉为共享纯函数或 schema。
7. **媒体安全边界高于普通 LLM 文本**：URL、redirect、DNS/peer IP、MIME/magic、size、hash、原子落盘与重复计费都必须独立守门。
8. **Mock fixture 不能总为空**：graceful-degrade 会让关键闸门零覆盖；涉及关系、预算、resume、媒体状态时应提供最小非空 fixture。
9. **文档中的“当前”最容易过期**：测试数、最近 iter、下一步只保留在 handoff；产品说明和历史总结用范围化措辞并链接当前快照。
10. **项目记忆不能只按行数优化**：iter 093 将 2216 行 handoff 一次压到约 93 行，虽去掉重复，却也损失了接力所需的事故模式和阶段上下文。合理结构是短当前快照、数百行精选工作记忆、阶段历史和按需逐轮证据四层并存。
11. **昂贵验收应在审查修复之后**：先跑 `verify.sh` 再审查会在 findings 修复后重复全量。聚焦反馈前置、独立审查居中、全量闸门后置更节省时间，也不会降低最终验收强度。
12. **“mock”必须审计传递依赖和真实动作**：只断言不调用 provider 仍可能漏掉 LiteLLM cost map、proxy socket 或 tiktoken 冷下载。可靠证明需要控制首次导入顺序，在临时冷缓存与网络阻断下执行 completion/preflight，并让验证脚本固定项目解释器。
13. **付费“已确认”与“结果未知”必须分开**：请求前 marker 只能证明可能已提交，不能当作已确认扣费；但两者都必须阻止自动重发。付费恢复还需绑定输入、endpoint、model 和账号，独立 state 与 provider ledger 要在报告时交叉对账。
14. **付费响应与本地 commit 是两个状态机**：provider 已返回、artifact 已落盘、canonical 产物已提交和 orchestrator callback 完成之间都可能崩溃。每个边界都要有可复算指纹与零网络收尾路径；只有 transport 证明未发送时才能安全释放付费机会。
15. **媒体魔数不是解码证明，费用数字也不是账本证明**：真实媒体必须经过资源有界的结构/内容解析，无法可靠解析的格式应暂时 fail-closed；成本读取必须与 dirty 状态来自同一快照，未知或损坏证据不能降格为 0。
16. **付费前门禁必须与请求处在同一锁域**：先在锁外判断 fresh，再进锁调 provider，会留下 Web 编辑 TOCTOU；旧产物迁移也应在首次 runner state 前完成，否则 crash 会把新产物与旧指纹拆开。
17. **季库容量、单次输出和单集 cast 是三个边界**：共用一个 schema 上限会让“第 9 个季角色”与“单集最多 8 人”互相阻塞。Prompt 的剩余槽位、merge 后 active cast 和 meta 必须使用同一语义。
18. **验收要隔离输入，也要绑定被验收实体**：只强制 mock 不足以阻止 ambient workspace、dotenv 或全局进程环境污染。Canonical 入口应使用 synthetic workspace，在 import 前物理短路 dotenv，并用 HEAD/tree/cleanliness 证明证据对应哪个 implementation commit。聚焦 Python 检查也必须使用同等的 dotenv 隔离前置。
19. **本地 E2E 的难点是防止假阳性，不是启动一个 HTTP server**：必须证明请求真的经过生产 adapter/transport，并重读 durable state、复算 hash、穷尽计数、验证零网络 resume。组件证据必须与 canonical run/commit 绑定，而 `local-e2e` 不能借任何字段升格为 `provider-validated`。
20. **Crash 测试不能用异常或策略表代替进程死亡**：`KeyboardInterrupt`、同进程 Mock 和手工 ledger 会经过 finally、重用模块状态或自证预期。可靠矩阵要在生产 seam 后 `os._exit`，由新解释器重读 durable state，并用进程外持久 counter 区分付费 create 与合法 poll/download；这仍只证明进程 crash，不等于断电安全。
21. **全季库存与单集消费必须经同一投影分层**：角色库可以跨集增长，但 reviewer、fingerprint、组装、导出和视频若各自筛选，会让实际输入与血统漂移。应由共享纯函数冻结单集阵容；不能证明阵容的旧数据宁可要求重新评审，也不能回退整季库存。
22. **创作真源与渲染派生物必须分层**：`episode_NN.json` 不应为媒体实现细节扩 schema 或改 SHA；RenderPlan 应从可证明 fresh/Approve 快照确定重建，并以独立 fingerprint/状态管理陈旧性。缺少创作层持久 UUID 时，无法证明重排对应的重复镜头必须 fail-closed，不能用当前位置假装稳定身份。
23. **不可变候选、可变选择与单集冻结必须分层**：季级资产目录可以继续追加版本，但不能把新候选自动视为当前选择；selected mutation 需要 revision/current-ID 双 CAS。单集 manifest 只冻结当集 active selected refs，不绑定整个 catalog，否则未选候选或下一集角色会无意义地使旧集 stale。
24. **派生 ref 不能用落盘值自证来源**：RenderPlan 中已有的 ArtDirectionRef 只能是缓存结果，freshness 必须重新读取并验证当前 catalog selected；missing/invalid/orphan source 应阻断，未选候选不 stale，只有 selected 变化才沿真实依赖传播。target-token CAS 仍以所有项目写者遵守 workspace flock 为前提，不能对非合作本地进程宣称原子性。
25. **逐镜资产绑定必须显式且与内容认证分开**：没有创作层 scene ID 时，调用方必须提交完整稳定 `shot_id -> scene_id` 映射，不能从 prompt、位置或自由文本猜测；episode manifest 可作为本地权威绑定记录并重验当前 RenderPlan/catalog/selected artifact，但普通 SHA-256 只证明内容一致性，不是签名，不能宣称抵抗离线整份改写并重算 hash。
26. **“零到多个”也必须把零写出来**：逐镜道具/线索不能把缺少 mapping key、漏传 `asset_refs` 与明确 `[]` 混为一谈；完整 shot 映射和必填空列表既是 graceful degrade 证据，也是防止调用方遗漏被静默接受的 freshness 边界。先按当前 shot 数量有界校验 mapping，再读取条目，避免拒绝超限输入前遍历或复制不受信任容器。
27. **逐镜 consumer 只绑定实际使用依赖，装配完成不等于可提交**：episode frozen cast 不能代替显式 shot mapping，未出镜 frozen asset 不应使已存 plan stale；references 必须是 exact version/artifact 的 deterministic prefix。`assembled` 仅证明本地规格与引用已冻结，MIME/尺寸、provider capability、付费尝试和候选质量证据必须留在后续执行层。
28. **工作流 Markdown 也是需要 fail-closed 的接口**：checker 的标题、字段和 fenced code 解析必须与实际渲染语义一致，不能让示例或缩进差异冒充真实上下文；路由路径应拒绝绝对地址、穿越、私有根、symlink 与未跟踪必读文件，且 accepted 闭包要在后续 active iteration 出现后继续受检。
29. **媒体候选、选择与恢复要分层**：content-addressed candidate 是不可变事实，新 candidate 不能自动替换 first/tail selection；跨镜 lineage 必须绑定 source tail revision 与 target request，lost-response 只能凭 exact transition receipt 重放。缺失 artifact 可按 manifest identity create-only 恢复，但损坏/占位目标不能自动覆盖或靠重建 manifest 掩盖。
30. **付费 attempt 的一次调用承诺必须先于 provider 接线落地**：capability、provider/request identity 与 ordered exact references 要在调用前冻结，`started` 必须先 durable；只有 transport 能证明 not-sent 才可释放机会。receipt、staging、C2 candidate 与 succeeded ledger 是分阶段事实，恢复应优先用已提交的 exact candidate 补账，并在最终锁内重读 source/target。该证据只证明受控本地 writer 下的 process-crash 恢复；不能外推 power-loss、非合作本机进程或真实 provider exactly-once。
31. **媒体合成的完成态必须由同源时间线和 post-probe 共同证明**：plan 只接受显式 argv 与严格相对路径；hash/probe 后应把已验证字节固化到私有 staging，避免 FFmpeg 消费漂移源。容器总时长不能替代视频流时长，SRT 与 QA 也不能靠各自落盘值自证；应从 TimelineManifest 重建并把 output SHA、轨道规格和 required-shot coverage 一起复核。
32. **多文件可编辑导出需要显式完成协议，而不只是逐文件原子替换**：ASS 与工程文件各自原子写入仍可能形成跨文件 partial pair；应先失效旧 marker，在同一锁域内重验素材、输出目录 identity 和完整 pair，最后才提交 completion marker。字幕 revision、素材 SHA、source range、profile 与 timeline fingerprint 必须进入可重建工程，特定 NLE 兼容性只能由对应 adapter 另行证明。
33. **可恢复选择回执必须证明历史状态转换，而不只是保存结果哈希**：lost-response recovery 需要把 mutation 与 receipt 原子提交；before/after manifest 要逐版本绑定 append-only catalog、只允许目标镜头 old→new，连续保留回执必须首尾成链，ack 形成的 revision gap 才可跳过。结果状态应描述可验证事实（如目标当前是否仍被选择），不能把 ABA 误写成“从未被覆盖”。
34. **资产零引用必须来自完整扫描证明，不能来自文件缺席**：跨集 used-by 要先枚举 canonical episode/source 闭包，再把缺失、坏 envelope、identity 错位、目录 symlink 与扫描竞态显式变成 blocker。`disabled` 只关闭未来选择/物化入口，不能删除或破坏历史冻结引用；即使当前 `references=[]`，没有独立 GC 协议也不能推出物理可删除。
35. **多层 fallback 必须冻结解析历史，而不能只保存最终 ref**：Episode > Series > Global 若逐层读取却不复查先前 missing token，会在高层覆盖并发出现时短暂把低层计划判 fresh。resolution 应显式保存 selection/scope revision 并自校验 lineage；scope clear 与 lifecycle disabled 必须使用不同状态语义，Global mutation 还要检查所有已知 season ledger，不能信任调用方指定的单季证明。
36. **内容哈希有效不等于媒体可安全公开**：浏览器不应直接消费 provider MP4；应从 manifest read 前实施并发/字节门禁，对单视频轨、尺寸、sample 与线程做解码前限制，再以去 metadata 的 decode/re-encode 派生物公开。超过 Web 重验上限的已选素材应保留可清除的 exact CAS 状态，但必须显式 `web_unverified` 并阻断 compose readiness，不能读取后才拒绝或误标成领域 artifact invalid。
37. **Web 完成态必须绑定持久源、阶段锁与可交付上限**：job success 不是 durable truth；F1/F2 开始后仍要在各自锁内重读 current E3，下载应在同一 workspace snapshot 中绑定 episode/fingerprint 并重建 QA/completion。生成、验证和 Web 交付若使用不同字节上限，会产生“成功但不可下载”；content-addressed revision 还必须在幂等 replay 路径补偿清理不可达交付，否则 crash 会把有限单次输出变成无界累计磁盘。
38. **Lease 的幂等重放也是所有权操作，不是普通只读返回**：caller-controlled time 会让另一个进程提前判定 expiry，未认证或已过期 replay 会让旧 worker 把别人的状态当成自己的成功继续付费动作。可靠协议必须在同一锁域读取可信时钟，把 owner/token、task/lease revision、before-ledger 与结果指纹写进持久 receipt；无证据的 legacy 在途状态宁可 reconciliation，也不能合成 lease。
39. **Registry 的字符串 ID 与授权 fingerprint 必须形成同一身份，而不是两条并行线**：只验证 caller fingerprint 等于 task，却不证明它对应本次 provider/model ID，会在同 backend 多模型时把 A 的授权路由给 B。registration 应保存 ID↔fingerprint 双射，binding 冻结完整 capability snapshot；source Pydantic 对象也要在 API 边界重建验证，且通用抽象不能把 TTS 的“只重下、不重合成”降格为不支持 download。
40. **事件图的可追溯性需要同时区分身份闭包与认证来源**：event 只绑定 graph family 会允许跨 workspace 移植，projection 只列已选成员会允许跨图自证，helper-only 守门也会被直接反序列化绕过。可靠边界应把 workspace/family 写入 event identity，以完整有序 membership 证明 graph，以 schema 复核 exact minimum closure；即便如此，普通 source hash/content addressing 仍只是 caller-trusted 内部一致性，生产 adapter 必须另行绑定权威 source snapshot，不能把它宣称为签名 provenance。
41. **公网回调通过不等于 provider 素材上传通过**：应把本地 capability、Tunnel 公网 exact-byte 回读、provider asset upload、video create 和结果下载分别记账。素材上传若在 durable video submitting marker 前失败，只能宣称 create=0；没有只读资产查询或脱敏响应证据时不能猜上游是否部分接收，也不能用同一授权重发 POST。
42. **素材上传与视频 create 是两个独立外部写状态机**：逐素材 POST 也可能在 provider 已接收、本地未收到响应时产生孤儿或费用，因此必须先写 durable marker，只有明确 not-sent 才能释放；已确认 ID 可续跑，unknown 必须阻断自动重发。provider 未返回实际人民币费用时应保留 unknown，不能把空值解释为 0。
43. **版本标签不能单独证明质量样本可比**：应哈希实际 prompt，并用独立 namespace 隔离 artifact 与 ledger；create 返回不明、没有 task ID、只读 task 列表未变化，仍不能推出请求未到达或费用为 0，因此必须保留 unknown 且不重试。
44. **周期体检必须维护 finding 去重闭包，而不能只看最新报告**：后续报告可能漏掉早期仍成立项；应把跨报告问题归一到代码/测试/iteration 证据，按当前 HEAD 重放。多文件聚合的“有单文件上限”也不等于请求有界，身份复核必须绑定实际 bytes，资源守门还需 collector 累计预算。
45. **来源 authority、完整图身份与单集选择策略必须分层闭包**：生产事件图应绑定 entity/rolling-summary 的 exact bytes，但完整 source graph 不应随 episode spoiler boundary 改写；RenderPlan 必须冻结 workspace/family、完整有序 membership 与可本地重算的 selected/allowed/boundary binding，并由 store 从当前 authority 重建。普通 SHA 仍只证明自洽，不是签名或 MAC。
46. **辅助记忆必须是可丢弃索引，而不是第二真源**：context cache 只保存可从 current authority 重建的 event/source identity、role 与有界 query hash，并同时绑定 graph、selection、RenderPlan、episode 与 policy exact bytes；missing/delete 不应影响 canonical，任何 current binding drift 都只使 cache stale/blocked。query hash 对低熵输入可猜，不等于匿名化；应用层 token/CAS 也不能冒充抵抗 hostile 本地写者的 OS 原子保证。
47. **工作台必须是当前事实的投影，不是新真源**：资产、镜头、attempt/task、timeline 和 QA 应由后端 current inspectors 在同一安全模型中重建，list/canvas 只是同一 fingerprint 的不同视图。顶层状态必须包含完整 ledger 汇总，不能因当前镜头或 UI 截断漏掉 retired unknown/submitted；声称 read-only 的 GET 连 lock/holder 也不应创建，并可用 double-scan 在无写锁下显式暴露并发变化。
48. **身份复核与测试清理都必须覆盖实际写入窗口**：workspace 守门不能只在 selector 或请求入口检查，应在持久写前复核，并在写入新增可选 canonical 目录后刷新 identity，兼容部分初始化项目；test worker 必须 cooperative cancel 并 join 完成后才能恢复全局 workspace/env 或删除临时目录，timeout 应保留状态并明确失败。两者都不外推为抵抗最后复核后的非合作本机写者。
49. **界面规范不能发明后端能力，用户语言也不能泄漏实现词汇**：每个按钮都应绑定当前接口、现有或待迁移 hook、确认条件、处理中状态、成功去向和失败恢复；没有写入契约的操作应明确隐藏。内部枚举、模型、provider、job 字段和原始错误只留在开发映射，用户界面统一翻译为直白中文。视觉示例还必须落在声明的响应式断点内，否则不能作为前端验收依据。
50. **公共列表投影必须同时约束身份、类型与文件读取边界**：仅从目录名或未验证 metadata 猜 workspace 类型，会把损坏/替换对象送入错误域页面；公开更新时间也不能靠递归跟随路径。应从已验证 root fd 逐级 no-follow、有界读取权威产物，legacy 缺 metadata 可显式兼容，存在但损坏/未知的类型必须失败关闭。设置 secret 即使做掩码也仍泄漏片段，普通用户投影只应返回 configured 布尔和零片段值。
51. **历史付费状态的读侧迁移不能改写事实真源**：为 legacy submission 增加对账时，读取路径若顺手重写源文件，会改变首次状态、破坏 source CAS，并掩盖 ABA。应让源 submission 保持字节不变，用独立 sidecar generation、文件 revision/content identity 与 ledger fingerprint 共同保护 append-only receipt；exact replay 可幂等，但权威 resolution 身份一旦形成必须冻结。
52. **创作来源不能由起点是否存在反推**：原创书没有续写起点是正常状态，导入书暂未选起点也不会因此变成原创。来源模式必须由持久 metadata 与服务端同源投影决定，显式冲突在任务分配前拒绝；legacy 推断保持只读和保守。
53. **dirty 与 active job 是两个有序导航守门**：same-workspace 切页只处理未保存内容，不应查询或弹出运行任务提示；真正离开/切书才在 dirty 解决后处理 active job。hydration 或任务状态未知时 mutation 必须保持禁用，lost/404/坏状态停止轮询且不得自动重提。
54. **付费失败恢复不是普通 force 重跑**：UI 上看到失败稿不等于具有恢复资格；服务端必须绑定同章 exact durable terminal、完整上游 freshness/strict plan、内容无关状态指纹与 ledger claim，并在归档/调用写锁内复核本次恢复 job 自身仍是 durable active。状态漂移、任务槽未释放、lost/unknown/submission-unknown 或一般失败只能安全停止，不能猜测后重提。
55. **HTTP mutation 守门必须由完整 policy 驱动**：新增 POST/PUT 若未登记应在测试和运行时都 fail closed；重复/short `Content-Length`、`Transfer-Encoding`、Content-Type、Origin/Fetch-Site、auth 与 route intent 要在 body 和 handler/provider 之前拒绝。有付费副作用的 diagnostics 不得伪装成 GET。
56. **“已脱敏异常”必须是 total projection**：未知 provider 异常的 `__str__`、property、truthiness 和 metaclass type name 都可再次抛错，因此投影必须捕获 hostile shape，只选稳定 code/type/attempt/trace。日志 sink 失败不得覆盖本次 provider 结果或导致重提；它要标记 accounting degraded，在下一次付费 claim 和 settlement 前阻断。
57. **多章完成态要证明全集合 current，不能用最新单章代表全体**：工作台应从当前起点与权威 chapter plan 逐章构造 expected context，计划缺失/重排/损坏、任一旧章 stale 或 external-review mismatch 都不得投影 `done`。
58. **有界日志读取要同时绑定路径身份与实际 bytes**：dir-fd/`O_NOFOLLOW`/regular-file 还不足；读前后 fd 和最终 pathname/目录链必须一致，行长要在 strip 之前按原始 bytes 检查，再叠加单行、累计、JSON 深度和 dict-only 上限；任一失败只能降级为空。
59. **付费真链的预算必须在请求前可证明**：未知模型定价不能靠便宜 fallback 宣称人民币上限；显式家族定价、prompt bytes + max output 保守预留、每阶段 request/budget/deadline 冻结和链级 monotonic deadline 需同时成立。`submission_unknown` 发生后原授权不能继续用于新提交，只能无提交 inspect/reconciliation 或重新取得授权后开全新链。
60. **确认必须绑定当前版本，流程不能依赖批次大小**：保存响应只确认提交时的字段与 DOM 快照；正文审核通过不等于衍生记忆已更新，恢复写入失败仍需阻断。旧关系推进只能失效保留，不能猜测恢复。滚动规划按全书进度维护下一窗口且保留远期计划；伏笔回收绑定当前正文、计划和审核证据，逐章检查与分段启动应一致。

61. **目录身份、历史压缩与计费停止都不能只看局部表象**：合集的同名章不等于重复目录；正文保存必须比较读取版本。日志压缩应保留创建顺序、latest状态与append历史摘要，读者最终核对当前pathname，避免旧inode被当成当前恢复依据。缺usage/日志失败应覆盖Web和无scope CLI，在保留成功响应的同时阻断下一请求；测试必须清理模拟的执行上下文，不能因此放松生产停止规则。

## Historical Evidence Notes

- iter170活动迭代：实现99dd3eb canonical1959项/15步骤/101秒通过；真实新key/luna生成、提取、取消后续接成功。最小长度探针确认服务忽略max_tokens与max_completion_tokens；用户单价估算不等于服务端账单与强制费用上限，此前因此停止；随后用户明确暂不考虑预算继续测试，10章提取完成，Web原生有界流式准备243秒成功，在途取消后无后续请求，大纲恢复中，完整真实验收保持未完成。新增每请求取消门禁，已成功响应保留，新增repair/chunk请求观察到取消后停止。


- iter168 在 implementation `df3bc8a2f8b26ab4901837164570285551a1c8b5` 上 canonical 1889 tests / 15 steps / 84 秒通过，run `880f05b99e4e4f61bb6c2f31bf206c64`，schema v3、`mock-functional` / `canonical-novel-mock-offline`，`tracked_scope_clean=true`。mutation/intent/framing、typed terminal、逐章 freshness、bounded JSONL 与冻结定价/预算闭环；三路只读审查最终无 P0–P2。三视口 synthetic mock 为 `local-e2e`；真链 3 extract + compress + persona 获得响应，entity graph 为 `submission_unknown`后零重提，估算 ¥4.7503，结论 `safe-blocked`。短剧 backlog 已保留，9 份重复日报在验收后删除，未 push。
- iter167 在 implementation `bd1be596deca742c2bb0d78fea965b5604e067df` 上 canonical 1849 tests / 15 steps / 78 秒通过，run `22a861a2561b4de8b2cd25aeddd7810f`，schema v3、`mock-functional` / `canonical-novel-mock-offline`，`tracked_scope_clean=true`。完整基线 `35c97cc` 保存在 `codex/short-drama`；main 删除短剧运行/媒体/CLI/Web/API/job/prompt/fixture/script/test，只保留禁用入口和 legacy 类型隔离。三路只读审查 findings 全闭合；早期完整门禁的 2 个旧测试契约经聚焦修复，最终提交的首次受限运行又因 12 个 loopback bind `EPERM` 失败，同一提交获准后完整重验通过。9 份未跟踪报告未触碰，未读取私有 workspace，未调用真实 provider，未 push。
- iter166 在 implementation `9378f651244755e45148c5b6e3fdad33238cb4db` 上 canonical 3126 tests / 15 steps / 479 秒通过，run `348bac3ef2984d91b49c89e4875e9395`，等级 `mock-functional` / `canonical-mock-offline`，`tracked_scope_clean=true`。动态步骤安全投影、strict-approved 正文完成态、原创/续写 exact 失败章恢复与 provider deadline 守门闭环；correctness、security/boundary、Web/UX+provider/timeout 三路最终无剩余 P0-P3。首次完整验收的旧视频 timeout 断言修正后完整重验通过。确定性恢复浏览器为 mock E2E；原创 `test01` 由 Codex 观察至细纲，正文成功来自用户本地声明，续写真 provider 整链为 `safe-blocked`，不外推其它 provider、长跑或 SLA；两份未跟踪报告未触碰，未 push。
- iter165 在 implementation `e718200` 上 canonical 3072 tests / 15 steps / 502 秒通过，run `615a5147bb994c6f8179c1899dc0b055`，等级 `mock-functional` / `canonical-mock-offline`，`tracked_scope_clean=true`。schema v2 创作模式、阶段同源、dirty/active-job 分层、fail-closed 工作台与任务恢复、提示聚合和移动菜单无障碍闭环；三视口为 `local-e2e`，三路最终无剩余高置信 P1/P2。前两次 full gate 的兼容回归经聚焦修复后完整重验通过；两份未跟踪报告保持原样，未 push、未查询或调用真实 provider。
- iter164 在 implementation `817c930` 上 canonical 3043 tests / 15 steps / 467 秒通过，run `9a66e53279774023ad2e6eecbabc9a94`，等级 `mock-functional` / `canonical-mock-offline`，`tracked_scope_clean=true`。四份报告去重出的 result context、workspace-scoped job、protected mutation framing 与 reconciliation-aware accounting 四根因全部闭合；episode 2/restart-lost/Local Demo target 为 `local-e2e`。三路复审最终无剩余 P0-P3，报告在验收后删除；未 push、未查询或调用真实 provider。
- iter163 在 implementation `ea4e1d4` 上 canonical 3025 tests / 15 steps / 481 秒通过，run `44fb300e4c994e068c8131ff30f6a009`，等级 `mock-functional` / `canonical-mock-offline`。视频 create 三分状态、历史 unknown append-only CAS receipt 与公开安全投影完成；correctness、security/boundary、真实媒体/计费三路最终 no findings。首次验收的 2 个旧测试契约修复后完整重验通过；未 push、未查询或调用真实 provider。
- iter162 在 implementation `935ffc8` 上 canonical 3008 tests / 15 steps / 467 秒通过，run `0503739d35a7453cb995f5581ba0f923`，等级 `mock-functional` / `canonical-mock-offline`；episode 2 与 degraded Insights synthetic 浏览器证据为 `local-e2e`。三路复审无剩余 P0–P3；首次完整验收发现的旧逐镜视频 mutation 错误优先级回归修复后完整重验通过，两份报告随后删除；未 push、未调用真实 provider。
- iter161 在 implementation `44a391b` 上 canonical 3001 tests / 15 steps / 443 秒通过，run `0031d4965e664254ba5ecac1fa3f21de`，等级 `mock-functional` / `canonical-mock-offline`；Figma Phase D compose/episodes/Insights/jobs 与 Phase A-D 三视口证据为 `local-e2e`。四路审查 findings 全部修复，unknown/跨币种、Running/恢复、episode 2+、安全日志与 exact delivery 边界保持。首次验收 2 个 legacy 静态合同失败在修复提交后完整重验通过；未调用真实 provider。
- iter160 在 implementation `38661f3` 上 canonical 2994 tests / 15 steps / 478 秒通过，run `18e89d1666b94d5cacc249188369bcae`，等级 `mock-functional` / `canonical-mock-offline`；Figma Phase C 资产治理与逐镜图片/视频三视口证据为 `local-e2e`。correctness、security/boundary、Web/UIUX/媒体预览三路 findings 全部修复；DOM 只留公共序号，媒体预览挂载 `blob:` URL。首次沙箱运行仅因 23 个 loopback bind EPERM 失败，同一 commit 非沙箱复验通过；未调用真实 provider。
- iter159 在 implementation `9ffbb13` 上 canonical 2989 tests / 15 steps / 487 秒通过，run `5fdb0c215e0e44a09104e7f61465649b`，等级 `mock-functional` / `canonical-mock-offline`；Figma Phase B 五站创作台和角色库三视口证据为 `local-e2e`。correctness、security/boundary、Web/UIUX 三路 findings 全部修复。受限沙箱 loopback EPERM 与 3 个旧四站兼容测试契约在最终获批重验前分别解决；未调用真实 provider。
- iter157 在 implementation `3c953fd` 上 canonical 2976 tests / 15 steps / 467 秒通过，run `d2b1f5f4ea8445809f03e75603f08f47`，等级 `mock-functional` / `canonical-mock-offline`。2026-07-26 至 07-29 四份报告的 KB/draft no-follow、异常脱敏、Wizard 错误投影、job 持久化准入/轮询终止与 owned verify temp findings 全部闭合；三路审查无剩余 finding，报告在验收后删除。首次沙箱运行仅因本地回环 socket `EPERM` 失败，同提交非沙箱复验通过；未调用真实 provider。
- iter156 在 implementation `cd01ebe` 上 canonical 2956 tests / 15 steps / 466 秒通过，run `b289f10090de435f9174dc1ab54d3d15`，等级 `mock-functional` / `canonical-mock-offline`；mandatory loopback 与 Phase E 5 路由 × 3 视口、Phase C/D/短剧回归浏览器证据为 `local-e2e`。小说 Web Phase A-E 已全部落到生产 Web；四视角 findings 全部修复，无剩余 P1/P2，未调用真实 provider。
- 早期阶段测试数、调用数、成本估算与具体 snapshot 是当时证据，不代表当前值；需要时读对应 iteration 001-019。
- 真模型小说路径曾完成 extract、debate、write/review、原创 premise 多章和深起点续写样本；最新生产证据与仍待授权项以 handoff 为准。
- Aeloon 的 PR、部署方式和 vendored 同步状态由 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) 单独维护，不在这里复制。
- 历史 roadmap 与 `PLAN_DRAFT` 是决策快照，保留在 `iterations/`，但不属于默认记忆入口。
