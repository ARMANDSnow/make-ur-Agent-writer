# Iteration 118 - 短剧完整 SOP 真人用户验证与修复

## Context

iter117 已完成逐镜视频 D3 纯本地恢复契约，canonical 基线为 2386 tests OK，总级别 `mock-functional`，本地 fake-provider 组件为 `local-e2e`。本轮不继续扩建 E-I，而是按真人用户路径验证当前已声称实现或部分实现的短剧模块：建档、五站创作、分镜编辑、角色库/参考图、评审组装、单集四导出、多集衔接、整季快照、Insights、任务恢复与旧 episode-1 高光视频入口。

用户明确授权真文本不超过 60 次且预算不超过 ¥200，真图不超过 20 张，单次生图等待满 180 秒后才判超时，允许在总 cap 内追加重试。真视频本轮不执行，仅依用户提供的 `sd_real_max.md` 核对并配置 API key 以外的安全默认。用户允许本轮不执行 iter-start，但要求在 iter117 后交付固定八段的 iter118 报告、分阶段 commit、只 commit 不 push。

## Plan

### Implementation Context
- `must_read`: `AGENTS.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/GETTING_STARTED.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_117_drama_shot_video_provider_capability_attempt_recovery.md`, `.agents/skills/iter-finish/SKILL.md`, `src/web/routes.py`, `src/web/static.py`, `src/web/templates.py`, `src/ai_draw_client.py`, `src/drama_multimodal_smoke.py`, `src/drama_video_client.py`
- `expected_changes`: `src/ai_draw_client.py`, `src/drama_multimodal_smoke.py`, `src/web/routes.py`, `src/web/static.py`, `src/web/templates.py`, `tests/test_drama_characters_api.py`, `tests/test_drama_image_video_clients.py`, `tests/test_drama_iter088_web.py`, `tests/test_drama_storyboard_grid.py`, `tests/test_drama_multimodal_smoke.py`, `tests/test_drama_iter097_hardening.py`, `tests/test_web_routes_get.py`, `README.md`, `docs/product/short_drama_module.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/iterations/README.md`, `docs/iterations/iteration_118_drama_full_sop_real_user_validation.md`
- `do_not_touch`: `.env`、`key.rtf`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces`内容与 `小说txt/`；不实现 E-I，不执行真视频，不 push；不将 key、完整 prompt、签名 URL 或 provider raw response 写入代码、文档或公开输出

1. 以全新 synthetic drama workspace 从建档走到分镜、角色、评审、组装、导出、第 2 集和 mock 高光视频，同时检查桌面与 390px 移动端。
2. 修复刷新丢站点、分镜增删/推进缺失、mock SVG 与视频 strict PNG 冲突、短剧文案误导、角色图未消费、多 workspace 侧栏挤压、移动表格逐字折行与工程术语外泄。
3. 使用受预算/次数/超时守门的 durable multimodal runner 执行真文本与真图，人工复核产物质量；真视频保持零提交。
4. 分阶段 commit；先聚焦检查，再依 iter-finish 做 correctness、security/boundary、Web/media 三视角只读审查，修复 findings 后只运行一次 canonical `bash scripts/verify.sh`，最后 docs-only 收官。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五站状态/刷新/手编边界、角色图到视频 readiness、评审/组装/stale、四导出、多集继承、整季快照、任务取消/恢复与浏览器真实点击路径
- `security_boundary`: 核对凭据不落盘/不输出，真文本/图/视频授权互不继承，预算/调用数/超时、路径/下载/HTML escape、provider 端点、本地 lock 和用户未跟踪文件边界
- `extra_risk_view`: `web/media-user-truth`，核对桌面/移动可用性、用户文案与实际能力一致、mock/真图格式消费、真产物可见性、旧高光视频不冒充整集成片

- **A118-01**：synthetic workspace 从新建到站①-⑤、评审组装、角色图、mock 高光视频全部可达；刷新不丢步骤，6-9 镜可增删排序，修改后 stale/review/assembly 正确。
- **A118-02**：JSON/Markdown/CSV/Comfy 四导出可下载且可解析；第 2 集可从 fresh 第 1 集继承，阶段快照可用，整季母包的未完成理由真实可读。
- **A118-03**：mock 参考图为 strict PNG 并能被视频 readiness 消费；单集详情真实显示角色图；生图按 180 秒超时和总次数 cap 执行，无隐式真视频提交。
- **A118-04**：桌面与 390px 移动端的主流路径可用；侧栏不再挤压当前导航，剧集表可读/可滚动，已实现能力不以误导文案或 `todo/done/fresh/Approve` 工程术语呈现给普通用户。
- **A118-05**：真文本不超过 60 calls/¥200，真图不超过 20 张；报告只记录脱敏模型/provider fingerprint、计数、估算费用、耗时和质量结论，凭据、完整 prompt、签名 URL 与 raw response 不泄露。
- **A118-06**：聚焦回归、静态检查与三视角只读审查无未处理 P0/P1/P2；实现 commit 上只运行一次 `bash scripts/verify.sh` 并通过，canonical 结论与真 provider 局部校准证据严格分列。

## Implementation Notes

- 第一阶段 commit `3e90778` 修复浏览器创作主链：query/hash 站点一致、分镜增删/自动推进、安全 mock PNG、短剧导航/保密/站数文案与 dotenv 注入边界。
- 第二阶段 commit `56e504a` 修复交付与真人 UX：角色图显示、prompt 折叠、侧栏限高滚动、移动剧集表、中文状态/评审/设定标签、真生图友好错误，并将 Seedance 端点/模型写入保持 mock 的 `.env.example`。
- 真文本使用 synthetic 推理题材，五站共 5 calls，项目估算费用 ¥0.2562，耗时 131.49 秒，五站 schema/review/assembly 全部通过；人工检查剧本与分镜可读、钩子清晰。
- 真图为 2 名角色各1次，耗时 98.344/94.568 秒，无重试，两张均通过 strict image/hash/reference 检查并符合角色视觉签名。运行状态停在 `awaiting_video_authorization`，真视频 submit=0。
- 导出、第2集继承、季快照、Insights、mock 视频与真产物桌面/移动页面均已实际操作或解析验证。
- correctness、security/boundary、Web/media 三视角无 P0；发现并修复的 P1/P2 包括：注入 key 后漏载 `.env` 非密钥媒体配置、角色编辑后未保存即评审、本地预览可覆盖付费真图、stale 剧集仍显示可下载、同源主动 SVG、lock symlink/special-file 边界、JPEG/WebP 宣称与 strict decoder 不一致、video ready/空态文案误导。修复后三路复核均为无遗留 P0/P1/P2。
- 修复后 272 项短剧广聚焦回归与 174 项安全/配置/角色专项回归分别通过，`py_compile`、harness 与 `git diff --check` 通过；canonical 结果待 implementation commit 后回填。

## Acceptance Result

- **A118-01**：待 canonical 收官。
- **A118-02**：待 canonical 收官。
- **A118-03**：待 canonical 收官。
- **A118-04**：待 canonical 收官。
- **A118-05**：待 canonical 收官。
- **A118-06**：待 canonical 收官。

### Knowledge Promotion
- `decision`: <pending>
- `destination`: <pending>
- `reason`: <pending>

## 文件变更汇总

- 待收官时按实际提交回填。

## 不在本轮范围

- E-I：语音、时间线/字幕/BGM、整集 FFmpeg MP4、通用媒体 DAG/成本调度、生产工作台/归档。
- 任何真视频上传、submit、poll、download、账单或 provider 质量结论；本轮只配置非 key 默认。
- 抖音/快手/视频号自动发布、账号/审核/回执，以及未在当前 Web 产品宣称中可达的 C/D 新生产工具。
- 用户凭据、`.env`、私有原文/workspace 内容和未跟踪体检报告。

## Notes

- 用户明确豁免 iter-start；本文是实施后补建的审计与收官记录，不伪造立项提交。
- 真文本/图校准仅证明本次指定 provider/model 与 synthetic 样本，不泛化到真视频、所有题材或稳定 SLA。
- 只 commit，不 push；用户未跟踪体检报告保持原样。
