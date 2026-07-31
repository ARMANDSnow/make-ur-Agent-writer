# Iteration 162 - 近期体检报告公开投影、多集上下文与 Web 边界闭环

## Context

2026-7-30 与 2026-7-31 两份只读体检报告基于同一 `c71664a` 基线，后一份确认前一日后无代码漂移；两份报告去重后共有 7 项仍成立 finding：公开 job 投影暴露 provider task 身份、概览与 production 空态丢失 episode 2+ 上下文、Insights 将 degraded 占位零展示为确定事实、production DOM 暴露未使用的稳定 `shot_id`、job cancel 未经过统一 wire mutation guard、`jobs.py` 顶层说明与 durable ledger 事实不符，以及 iter160 Knowledge Promotion 原因仍为收官占位。

本轮按用户要求建立单轮闭环：先保留两份报告作为验收依据，修复并完成聚焦回归、三路只读审查与唯一 canonical 验收；只有全部通过后才删除这两份未跟踪报告。默认 mock/offline，只 commit、不 push，不调用真实 provider。

## Plan

### Implementation Context
- `must_read`: `src/web/jobs.py`, `src/web/routes.py`, `src/web/static.py`, `src/drama_media_metrics.py`, `tests/test_web_jobs_recent.py`, `tests/test_jobs_cancel.py`, `tests/test_drama_media_metrics.py`, `tests/test_drama_web_uiux_phase_a.py`, `tests/test_drama_web_uiux_phase_c.py`, `tests/test_drama_web_uiux_phase_d.py`, `docs/iterations/iteration_160_drama_web_uiux_phase_c_assets_shot_media.md`
- `expected_changes`: `src/web/jobs.py`, `src/web/routes.py`, `src/web/static.py`, `tests/test_web_iter162_health_closure.py`, `docs/iterations/iteration_160_drama_web_uiux_phase_c_assets_shot_media.md`, `docs/iterations/iteration_162_health_report_projection_episode_web_boundary_closure.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有样本或 workspace、真实 provider、paid ledger/schema、`data/`、`outputs/`、`logs/`；最终验收前不得删除两份体检报告

- 从 job recent/detail 的公共 result allowlist 与 drama result summary 中移除 `task_id`、`provider`、`provider_model`；内部 job 与权威 paid ledger 保持不变。
- 概览从 URL 读取并校验 1–100 的 `episode_no`，progress、production、导航和 CTA 使用同一集；production 空态使用投影返回的 episode 回到对应创作台评审步骤。
- Insights 仅在 media metrics/duration 来源为 `ok` 时解释数值；degraded 时统一显示未知与来源待核对，不展示确定性占位零。
- 从 production DOM 删除无消费者的 `data-shot-id`，交互继续只使用公开 sequence。
- 将 job cancel wire route 纳入现有 JSON、显式 intent、same-origin 与 64 KiB body cap；保留 `headers=None` 的可信进程内测试 seam。
- 修正 `jobs.py` 持久化架构说明，并闭合 iter160 的 Knowledge Promotion 占位。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 recent/detail 仍保留所需安全字段、episode 2+ 的概览数据和所有恢复链接不回落到第 1 集、Insights 正常零与 degraded 未知可区分、production sequence 交互不回归
- `security_boundary`: 核对 provider task 身份不再进入公共 API/DOM，cancel wire 的 JSON、intent、same-origin、body cap 在 mutation 前执行，可信进程内 seam 与内部 paid ledger 不被误删
- `extra_risk_view`: Web/UIUX 真实浏览器核对 episode 2 概览/空态、Insights degraded 文案、production DOM 和桌面/窄屏恢复路径

- **A162-01**：recent/detail 对普通 `mvt-*` 与非凭据形态输入均不返回 `task_id`、`provider`、`provider_model`，内部 job/ledger 数据不变。
- **A162-02**：概览缺省/非法 episode 安全回落到 1；合法 episode 2+ 的 progress、production、概览导航与下一步 CTA 始终保持同一 episode。
- **A162-03**：production 无镜头空态链接使用服务端 `data.episode_no`，进入 `/write?episode=<n>&step=review`。
- **A162-04**：media metrics 或 duration degraded 时摘要与明细显示 `—`/“来源待核对”，不宣称未知任务为 0 或“当前没有未知样本”；`ok` 状态仍可明确显示零。
- **A162-05**：production DOM 不含稳定 `shot_id`，sequence 选择、键盘/点击与详情渲染保持可用。
- **A162-06**：job cancel wire 对跨站、simple form、错误 Content-Type、缺 intent 与超限 body fail-closed；合法 same-origin JSON cancel 仍返回 202，`headers=None` 进程内调用兼容。
- **A162-07**：`jobs.py` 模块说明与 live pool + bounded durable public ledger 一致；iter160 Knowledge Promotion 已闭合且不改写当轮验收事实。
- **A162-08**：聚焦测试、JS/Python 静态检查、harness、diff check 与 correctness/security/Web 三路只读审查 findings 全部闭合；implementation commit 上最终 `bash scripts/verify.sh` exit 0、`mock-functional`、`tracked_scope_clean=true`，随后才删除两份指定报告。

## Implementation Notes

- 公开 recent/detail 的 result allowlist 与 drama result summary 同时移除 `task_id`、`provider`、`provider_model`；源 provider result 与受控 paid ledger 未改。`jobs.py` 顶层架构说明同步为 live in-memory pool + bounded durable public ledger。
- 新增 URL episode 解析 helper，严格接受 1–100，非法/缺省回落到 1；概览 progress、production、workspace home/创作/生产导航及下一步 CTA 统一使用同一 episode。production 无镜头空态从服务端投影的 `episode_no` 返回对应评审步骤。
- Insights 将 media metrics 与 duration 的 `status` 分别作为解释门禁：`ok=0` 仍显示确定零，degraded 只显示 `—` 与来源待核对。production 镜头按钮删除 `data-shot-id`，点击与原生键盘激活继续读取公开 `data-shot-sequence`。
- protected mutation path 扩展至 `/job/<id>/cancel`；dispatch 层要求不超过 64 KiB 的 UTF-8 JSON object、显式 intent 与 same-origin，server 层在读 body 前拒绝超限、非法/负 Content-Length 和任意 Transfer-Encoding。Dashboard 既有 `postJson` 已兼容，Wizard 直连 cancel 补齐 JSON/intent/body。
- 新增行为级 Node 回归，直接执行生产 JS 验证 episode 2、非法 episode 回落、真实 fetch/CTA/nav、sequence 点击重渲染以及 Insights degraded/`ok=0` 对照；socket 回归验证 cancel transport cap 与模糊 framing。
- 聚焦矩阵最终 236 tests OK；Python compile、Dashboard/Wizard `node --check`、harness 与 `git diff --check` 通过。LiteLLM 仅报告未安装可选 `botocore` warning，不影响 mock/offline 行为。
- Playwright 使用 `/private/tmp/iter162-browser-workspaces-v3` synthetic drama workspace：概览实际请求 episode 2，侧栏/CTA 保持 episode 2；production 空态链接为 `/write?episode=2&step=review`；media/duration degraded 均显示 `—`/来源待核对，DOM 无 `data-shot-id`，console 0 error / 0 warning。该证据为 `local-e2e`，临时服务与浏览器已关闭。
- 初审三路提出测试覆盖、malformed JSON 与模糊 transport framing findings；主线程修复后复审确认 correctness、security/boundary、Web/UIUX 均无剩余 P0–P3。security 另观察到既有真视频 status 接口会返回其专用安全 meta；该接口不属于两份报告明确指向的 recent/detail finding，本轮未扩张其既有合同。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮修复既有公开投影、episode 贯通和 mutation guard 合同中的实现偏差，不新增需要晋升到长期权威文档的规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/jobs.py` | 收紧公开 result identity，并更新 durable job 架构说明。 |
| `src/web/routes.py`、`src/web/server.py` | 将 cancel 纳入 JSON/intent/same-origin/64 KiB 双层 wire guard。 |
| `src/web/static.py` | 贯通 episode 2+ 概览/空态，修正 degraded Insights，删除 production DOM stable ID，修复 Wizard cancel 请求。 |
| `tests/test_web_iter162_health_closure.py` | 新增七项 finding 的跨层行为回归。 |
| `tests/test_web_jobs_recent.py`、`tests/test_web_server.py`、`tests/test_drama_web_uiux_phase_a.py`、`tests/test_drama_web_uiux_phase_d.py` | 更新公开投影、transport cap、episode/DOM 与 Insights 合同回归。 |
| `docs/iterations/iteration_160_drama_web_uiux_phase_c_assets_shot_media.md` | 闭合历史 Knowledge Promotion reason 占位。 |
| `docs/iterations/iteration_162_health_report_projection_episode_web_boundary_closure.md`、`docs/iterations/README.md` | 记录本轮计划、实现、验收与索引。 |

## 不在本轮范围

- 不改变 Insights 后端 schema、job 内部存储、paid ledger、provider adapter、计价或授权语义。
- 不扩建公网多租户 CSRF 体系，不调用真实文本、图片、视频或 TTS provider。
- 不处理两份报告之外的产品路线图与真实媒体 capstone 缺口。

## Notes

- 两份报告均为未跟踪文件；删除只发生在 canonical 验收通过之后，不进入 Git 提交。
- browser/synthetic workspace 证据可记为 `local-e2e`；标准 `verify.sh` 只产生 `mock-functional`，不得外推为 `provider-validated`。
