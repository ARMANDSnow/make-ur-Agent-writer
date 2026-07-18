# Iteration 139 - 短剧媒体 Durable Lifecycle Metrics 与 Insights

## Context

iter133-138 已完成阶段 G 的 task DAG、worker lease/capacity、静态 capability registry、原子 frozen binding、owner-guarded execution 与 strict pricing facts；阶段计划 G 的剩余验收项是按 episode/shot/media/provider/model 投影成功率和等待时间。当前终态 task 只保留 `created_at_ms/updated_at_ms`，lease 清除后首次 ready/claim 时间丢失，不能用 `updated_at-created_at` 冒充 queue wait。本轮以 backward-compatible ledger v4 lifecycle facts 保存可证明的 ready/first-claim/terminal 时间，并安全接入既有只读 Insights；不接真实 provider、不修改 C/D/E paid ledger、不测试 TTS。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_pricing.py`, `src/web/drama_insights.py`, `tests/test_drama_media_tasks.py`, `tests/test_drama_media_worker.py`, `tests/test_drama_insights.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_metrics.py`, `src/web/drama_insights.py`, `src/web/static.py`, `src/web/templates.py`, `tests/test_drama_media_metrics.py`, `tests/test_drama_media_tasks.py`, `tests/test_drama_media_worker.py`, `tests/test_drama_insights.py`, `tests/test_drama_iter088_web.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_139_drama_media_durable_lifecycle_metrics_insights.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真实图片、视频、TTS 或额外文本 provider，不修改 C/D/E paid ledger/schema/receipt，不从 caller time、进程时钟或终态差值猜测历史等待时间，不新增 Web mutation，不 push

1. 将通用媒体 task ledger 逻辑升级为 v4，在 task 外以 strict/content-addressed lifecycle facts 记录 `ready_at_ms`、`first_claimed_at_ms`、`terminal_at_ms`；新 task、依赖晋升、首次 claim、takeover、release、terminal/cancel cascade 都在原 task/lease CAS 同一原子提交中维护，重放不改时间。
2. v1-v3 ledger 继续可读并逻辑迁移；历史 lifecycle 缺失保持 unknown，绝不从 `updated_at-created_at` 或最后 lease 反推。新 task 必须有完整 lifecycle entry，旧 task 后续能证明的新事件可追加，但未知 ready 时间不补猜。
3. 新增有界只读 metrics 聚合：按 episode/subject/media/stage/provider/model 统计 terminal/succeeded/failed/cancelled/unknown/pending、success rate，以及仅在完整 lifecycle 可证时计算 queue wait/run duration；known sample count 与 unknown count 分列。
4. 将 safe metrics projection 接入 drama Insights 与页面；task ledger 缺失 graceful，坏源、symlink、identity/tamper、跨集上限异常显式 degraded，不泄漏 owner/token、lease、account/endpoint/fingerprint、provider task、paid evidence、prompt/response/path。
5. 用纯 schema、migration、dependency-ready、first claim/takeover/replay、terminal/cancel cascade、unknown legacy、aggregation、Insights redaction/limits 与零 socket 测试闭合阶段 G 最后一项。

## Acceptance

### Review Context
- `correctness_behavior`: lifecycle 时间只来自可信 workspace-lock 内 mutation 并与 task/lease 同提交；ready/first-claim/terminal 单调且 exact replay 稳定，legacy unknown 不补猜；成功率分母、pending/unknown/cancel 分类和 queue/run sample 数必须确定
- `security_boundary`: ledger v4 strict/content-addressed/nofollow/CAS；caller 时间、重算 fingerprint、跨 episode/task splice、symlink/目录/坏 JSON/超限与 workspace 扫描竞态 fail closed；公开 metrics 不含 owner/token/lease/account/endpoint/fingerprint/provider task/paid evidence/path/prompt/response
- `extra_risk_view`: runner/multi-workspace + observability/Web 专项，复核 claim/takeover/cancel cascade 原子性、旧 ledger migration、聚合上限、success-rate 分母与页面 unknown/degraded 表达

- **A139-01**：ledger v4 lifecycle facts 与 task/lease 同一原子提交，ready/first-claim/terminal 时间严格、单调、内容寻址；takeover/replay 不改首次时间，伪造/倒退/额外字段拒绝。
- **A139-02**：v1-v3 旧 ledger 可读，缺失 lifecycle 明示 unknown；不得以 `updated_at-created_at`、最后 lease 或 caller supplied time补猜 queue wait。
- **A139-03**：安全聚合按 episode/subject/media/stage/provider/model 投影 terminal/success/failure/cancel/unknown/pending、success rate 与 known/unknown queue/run samples；无可证明样本时不返回伪 0。
- **A139-04**：Insights 缺失 graceful、坏源 degraded、公开字段 allowlist 且有界；测试期间零 socket/provider/图片/视频/TTS 调用，不泄漏私有 identity 或 paid evidence。
- **A139-05**：聚焦回归与 correctness/security/runner-observability-Web 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- task ledger 升级为 v4；每个 task 都有严格、内容寻址并绑定 input identity 的 lifecycle。新建/晋升 ready、首次 claim、terminal 分别由锁内可信时钟和 task 单调时间产生；caller `now_ms` 只保留 strict shape 兼容，不进入新事实，也不阻断延迟 exact replay。
- first claim 不只保存一个时间：同时冻结 ready 前 task、claimed task、initial lease 与 before-ledger identity，并在主 ledger 生效前写入独立 no-follow、create-once sidecar。后续 transition/release/reclaim/takeover/terminal 只引用原证据；读取时 sidecar 必须逐字节匹配，缺失、替换、symlink 或单独重哈希主 ledger 均 fail closed。
- v1-v3 读取后生成 compact migration evidence；只有 source 中仍为 planned 的 task 可从后续可观测 ready 开始完整计时，其他历史 task 永久保留 ready/first-claim unknown。首次写 v4 前将原 canonical legacy ledger 保存为独立 sidecar，读取时反查 exact source task。旧账本继续使用 4 MiB 上限，v4 使用 8 MiB 上限，避免把完整 source 复制进主 ledger。
- metrics 在 workspace 一致锁中扫描 canonical episode namespace；初始 namespace/target token、每次实际解析字节的 source token和最终 namespace/target token必须一致。任何坏源、竞态、symlink、非 canonical entry、超过 4000 tasks/1000 rows 都返回 degraded 空汇总，不返回部分 totals。
- success rate 分母固定为 terminal task；submission-unknown 与 pending 分列。queue wait 只使用 ready+first claim，run duration 只使用 first claim+terminal；known/unknown samples、sum 与 deterministic average 同时公开，无样本为 `null`。
- 首轮三视角审查发现：caller ready 时间污染、dependency promotion 时间倒退、legacy reclaim 冒充首次、状态/lease/terminal 绑定不足、metrics 非一致扫描。修复后复核又发现 first-claim/legacy 自证、非 dependency failed 缺 evidence、ready snapshot 未精确绑定和旧账本体积翻倍风险；均以可信时钟、状态约束、external sidecar anchor、分代上限和 source-token 校验闭合。
- correctness、security/boundary、runner/observability-Web 三路最终复核均为无剩余 P0/P1/P2。sidecar 的 immutable 仅指应用层 no-overwrite/create-once 与内容寻址，不宣称签名、MAC、OS 防篡改或抵抗本机写者同时离线伪造主账本与全新 sidecar。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: lifecycle 时间来源、first-claim/legacy 外部证据、成功率分母、known/unknown 样本与一致快照是阶段 G 的长期产品/恢复合同，已同步进 G7 权威段落。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | ledger v4 与 strict lifecycle fact schema。 |
| `src/drama_media_{tasks,worker,metrics}.py` | 原子生命周期维护与安全 metrics 聚合。 |
| `src/web/{drama_insights.py,static.py,templates.py}` | 接入只读 task lifecycle metrics。 |
| `tests/test_drama_media_{metrics,tasks,worker}.py` | 覆盖 schema、migration、claim/replay/takeover/terminal/cancel 与聚合边界。 |
| `tests/test_drama_media_{queue_client,executor,pricing}.py` | 升级 v4 fixture，并回归 queue/executor/pricing 与 evidence sidecar 兼容。 |
| `tests/{test_drama_insights.py,test_drama_iter088_web.py}` | 固化 API/UI 的 allowlist、unknown 与 degraded 合同。 |
| `docs/product/short_drama_module.md` | 登记阶段 G 完整 lifecycle metrics 权威语义。 |
| `docs/iterations/{README.md,iteration_139_*.md}` | 登记 iter139 计划、实施、审查与验收记录。 |

## 不在本轮范围

- 真实 provider/billing adapter、Web provider mutation、自动 SLA 告警、直方图/分位数、跨币种费用、真实媒体/TTS。
- 阶段 H typed event graph、阶段 I production workbench/归档、阶段 J 多模态 capstone。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
