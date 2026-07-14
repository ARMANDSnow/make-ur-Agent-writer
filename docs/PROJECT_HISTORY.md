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

### Keep state auditable

- 每轮 iteration 保留 8 段结构、验收命令、审查结论与未修风险。
- 聚合交付包从 canonical assembled JSON 重建；不直接归档工作目录，manifest 只公开受控字段并对成员做 SHA-256。
- LLM 调用、writer meta、review、driver state、style drift 和媒体 attempt 只记录排障所需的有界、脱敏数据。
- 运行中的草稿、失败、snapshot 和 resume 状态要完整落盘；成功/拒稿/中止不能靠文件是否存在猜测。
- 计费恢复身份要区分不可变上游输入与本次站点输出；callback/ledger 提交前崩溃时只能凭 durable receipt、provider 与产物血统零网络收尾，不能用会被本次结果改写的全量输入指纹判断 stale。

### Separate current truth from history

- `AGENTS.md` 是长期规则；`AGENT_HANDOFF.md` 是当前快照；README SOP 是节点状态；iteration 是历史证据。
- handoff 不再累积逐轮 Phase Status，但保留数百行经筛选的阶段级工作记忆；本文件保留架构历史与长期教训，细节链接到原 iteration。
- handoff 与本文件都是新 session 默认读物。压缩目标是去掉重复验收和过时 snapshot，不是去掉会影响接力判断的设计背景、失败模式与恢复知识。

### Review before expensive full validation

- 实现阶段先用聚焦测试、语法/静态检查和 diff 检查获得快速反馈。
- 收官先完成 correctness、security/boundary 及风险专项多视角审查，修复 findings 后做聚焦回归。
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

## Historical Evidence Notes

- 早期阶段测试数、调用数、成本估算与具体 snapshot 是当时证据，不代表当前值；需要时读对应 iteration 001-019。
- 真模型小说路径曾完成 extract、debate、write/review、原创 premise 多章和深起点续写样本；最新生产证据与仍待授权项以 handoff 为准。
- Aeloon 的 PR、部署方式和 vendored 同步状态由 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) 单独维护，不在这里复制。
- 历史 roadmap 与 `PLAN_DRAFT` 是决策快照，保留在 `iterations/`，但不属于默认记忆入口。
