# Iteration 147 - 短剧同源生产工作台投影

## Context

iter146 已完成 H1-H3 来源图与可失效辅助记忆。按 A-J 阶段 I，本轮先建立统一、只读、同源的 production workbench：后端聚合 creative/RenderPlan、资产、逐镜图片与视频、任务、时间线、QA 和交付状态，前端列表/镜头板只消费该安全投影，不从内部文件拼状态；archive export/import 留给下一轮独立处理写入与迁移边界。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `src/drama_asset_web.py`, `src/drama_shot_image_web.py`, `src/drama_shot_video_web.py`, `src/drama_compose_web.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_asset_web.py`, `tests/test_drama_shot_image_web.py`, `tests/test_drama_shot_video_web.py`, `tests/test_drama_compose_web.py`
- `expected_changes`: `src/drama_production_workbench.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_production_workbench.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_147_drama_production_workbench_projection.md`, `docs/iterations/README.md`
- `do_not_touch`: `.env*`、`data/`、`logs/`、`outputs/`、`workspaces/`、`小说txt/`、私有样本、真实 provider/TTS；不得把 provider raw body、prompt、路径、签名 URL、凭据或内部 receipt 暴露到 Web

1. 新增 strict/bounded production workbench 聚合投影；creative/render freshness、资产 selected、逐镜图片/视频 coverage、timeline/QA/delivery 与 task/cost 安全摘要从现有领域检查器重建，缺失可选面显式 degraded，不伪造 green。
2. 新增 drama-only workbench page/API。默认 shot list/board 使用稳定后端 ID，列表与可选画布模型共享同一 projection fingerprint；前端不得根据 DOM 或客户端连线推导任务成功。
3. 所有路由保持只读、零 provider、bounded transport 与 allowlist projection；novel workspace、坏 episode、内部路径/付费原始状态、symlink/坏 JSON 整体 fail closed 或显式 blocked。
4. 聚焦测试覆盖 fresh/degraded/stale/blocked、跨 episode/workspace、确定性/bounds/隐私、同源 list/canvas、刷新恢复和 Web 路由；用真实本地浏览器完成桌面与窄屏视觉/交互验收。

## Acceptance

### Review Context
- `correctness_behavior`: 核对聚合状态只来自现有 current inspectors、shot/task/timeline/QA 的稳定 ID 与排序、缺失可选面不误标成功、list/canvas 同 fingerprint、刷新/跨进程重建一致及 legacy workspace graceful degrade
- `security_boundary`: 核对 drama-only scope、bounded projection、nofollow/坏 JSON/symlink 与跨 episode fail closed，且不泄露路径、prompt、provider raw body、签名 URL、凭据、内部 receipt 或未脱敏错误
- `extra_risk_view`: Web/aggregation：核对 API 和页面只读零 provider，前端不自行拼内部状态或把画布节点颜色当 durable truth，并以真实浏览器覆盖桌面/窄屏

- A147-01：strict workbench projection 确定聚合 creative/render、assets、shots、tasks、timeline/QA/delivery；稳定 ID/排序与 projection fingerprint 可重算，缺失/陈旧/阻塞状态不伪造 ready。
- A147-02：list 与 canvas model 来自同一 projection，刷新及新进程重建 byte-stable；页面/API 为 drama-only、只读、零 provider，legacy/可选缺失 graceful degrade。
- A147-03：安全投影有界且 allowlist，不含路径、prompt、provider raw response、签名 URL、key、内部 paid receipt；坏 episode、跨 scope、symlink/特殊文件、坏/超限 JSON fail closed。
- A147-04：聚焦测试、语法、harness、diff check 及真实浏览器桌面/窄屏验收通过；correctness、security/boundary、Web/aggregation 三个独立只读审查无未处理有效 finding。
- A147-05：implementation commit 后最终仅一次 `bash scripts/verify.sh` 通过并记录 `mock-functional`；Web 真实本地路径另记 `local-e2e`，不声称 provider validation。

## Implementation Notes

- 新增 `src/drama_production_workbench.py`：从 current RenderPlan/source binding、asset governance、逐镜 image/video、video attempt ledger、media task DAG 与 compose/QA/delivery inspectors 重建 strict/bounded allowlist projection；列表与画布共用可重算 `source_projection_fingerprint`，强制 node/edge ID 唯一且引用完整。
- 新增 drama-only `GET /w/<workspace>/production` 与 `GET /api/workspace/<workspace>/drama/production`；导航、响应式 list/canvas tabs、ARIA tab/tabpanel 关联与方向键/Home/End 切换均不含 mutation/provider 入口。
- 工作台单集上限为 100 shots、256 selected assets、256 tasks、700 nodes、1500 edges；边超限按 ID 确定性截断并显式报告 omitted，task/attempt 统计保留完整 ledger 语义。
- 状态聚合 fail closed：active/failed/cancelled task 不得变绿；当前镜头外的 unknown/submitted attempt、`reconciliation_required`、坏 inspector、stale/partial asset 均上浮。未识别 task subject 置 `null`，公开投影不包含 prompt、路径、provider raw body、signed URL、credential/account fingerprint、paid receipt 或异常正文。
- 为确保 GET 真正零写入，`src/drama_compose_web.py` 增加 double-scan read-only overview：两次 exact inspection 不同则显式 busy，不获取/创建 workspace write lock。
- 真实本地浏览器验证通过：桌面列表→关系画布、`ArrowLeft` 键盘回切、390×844 窄屏响应式布局与空 drama workspace safe-blocked 投影均正常；临时 workspace/截图仅位于 `/private/tmp`。
- 聚焦回归 161 tests 通过（workbench/compose/asset/image/video/Web GET），新增 workbench 文件 12 tests 通过；语法、harness 与 `git diff --check` 通过。
- 三个独立只读审查闭合了 prop/clue kind、partial/stale asset、时长上限、task/attempt 聚合、unknown subject 脱敏、GET 锁写入与 tabs 可访问性等 findings；主线复核后无剩余 P0-P3。

## Acceptance Result

- **A147-01 通过**：`DramaProductionWorkbench` 从现有 current inspectors 重建 strict/bounded 投影，source/list/canvas fingerprint 可重算且强制一致；missing/stale/blocked/busy 与当前镜头外 attempt ledger 状态都不会伪造 ready。
- **A147-02 通过**：drama-only page/API 只消费同一服务端 projection；空/legacy workspace graceful degrade，GET 通过 double-scan compose overview 保持零 workspace lock 写入，不触发 provider。
- **A147-03 通过**：投影字段、数量、node/edge 与 transport 有界；未识别 subject 脱敏，不含路径、prompt、provider raw response、signed URL、key/account fingerprint、paid receipt 或异常正文。坏 episode/workspace/source/ledger 显式拒绝或 fail closed。
- **A147-04 通过**：12 项新测试与 161 项聚焦回归通过，py_compile、harness、diff check 通过；真实本地浏览器桌面 list/canvas、键盘切换与 390×844 窄屏通过。correctness、security/boundary、Web/accessibility 三视角最终无剩余 P0-P3。
- **A147-05 通过**：implementation commit `ff1bd11dca99e6852368483422591b56f06700cd` 上仅运行一次 `bash scripts/verify.sh`，2844 tests / 15 steps / 442 秒，run `29a99181da324bfc893c1fafadc0a962`，tree `acb2b9b255d78058895cda4bb8b6823d8a48fcda`，`tracked_scope_clean=true`。标准级别 `mock-functional` / `canonical-mock-offline`，mandatory local-drama 组件与真实本地 Web 均记 `local-e2e`，`provider_validated=false`。

结论：iter147 收官。I1 同源只读 production workbench 形成本地工程闭环；I2 archive export/import、可写画布/统一操作、真 provider/billing/TTS 仍不在本轮结论中。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: I1 的同源投影、只读边界、状态聚合与 bounded/privacy 合约是后续 I2/J 与产品 SOP 的长期依赖，不应只保留在单轮验收记录中。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_production_workbench.py` | 新增 strict/bounded 同源工作台投影、状态聚合、fingerprint 校验与 canvas model |
| `src/drama_compose_web.py` | 新增零锁写入的 double-scan read-only compose overview |
| `src/web/routes.py` | 新增 drama-only production page/API 路由 |
| `src/web/templates.py` | 新增 production page 与导航入口 |
| `src/web/static.py` | 新增 list/canvas 渲染、状态摘要、响应式布局与 tabs 键盘交互 |
| `tests/test_drama_production_workbench.py` | 新增确定性、bounds、状态、隐私、路由、零写入与辅助功能回归 |
| `docs/product/short_drama_module.md` | 升级 v16，登记 I1 工程合约与 I2 缺口 |
| `docs/iterations/iteration_147_drama_production_workbench_projection.md` | 记录本轮计划、实施、审查与验收证据 |
| `docs/iterations/README.md` | 追加 iter147 索引 |

## 不在本轮范围

阶段 I archive export/import 与 mutation/typed canvas editing、物理 GC、真实 provider/billing/TTS、平台发布。

## Notes

计划提交信息：`docs(iter147): 迭代计划 147 立项（短剧同源生产工作台投影）`。
