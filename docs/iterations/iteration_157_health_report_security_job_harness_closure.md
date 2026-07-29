# Iteration 157 - 近期体检报告安全、Job 与 Harness 问题闭环

## Context

核验 `docs/2026-7-26体检报告.md` 至 `docs/2026-7-29体检报告.md` 的八项 finding，并以代码、测试和当前 handoff 建立去重矩阵。本轮严格 mock/offline，不访问 `.env`、`小说txt/`、私有 workspace、`data/`、`outputs/` 或 `logs/`，不调用真实 provider。

| Acceptance ID | Finding | 起始状态 | 本轮处置 | 报告删除门槛 |
|---|---|---|---|---|
| A157-01 | 嵌套 KB/draft symlink 越界 | open | workspace-relative dirfd/no-follow 文件层 | 路径回归与审查闭合 |
| A157-02 | stderr 原始异常/traceback 泄漏 | open | 统一安全异常记录器 | 注入 marker 的 body/stderr 回归闭合 |
| A157-03 | Wizard 5xx/降级回显异常 | open | 固定错误卡、trace ID 与 202 固定降级文案 | Wizard 回归闭合 |
| A157-04 | 首条 job 持久化失败仍启动 worker | open | 首条持久化升级为启动准入门 | 零 worker/handler 与回滚回归闭合 |
| A157-05 | unknown/404 job 无限轮询 | open | 严格状态分类并释放 busy | Dashboard/Wizard 行为回归闭合 |
| A157-06 | `xcrun_db` 破坏 harness 测试 | reproduced | 平台临时文件导向 owned run root | 两个既有失败转绿并通过边界回归 |
| A157-07 | Paid 按钮缺少 `aria-busy` | iter155 closed | 只补明确回归证据 | 回归通过，不重复改实现 |
| A157-08 | iteration 索引复制旧“当前基线” | open | 改为历史快照，当前事实只链接 handoff | 文档审查闭合 |

只有所有 Acceptance、只读审查和 schema v2 canonical `mock-functional` 全部闭合，才删除四份未跟踪报告；否则报告继续保留。

## Plan

### Implementation Context
- `must_read`: `src/paths.py`, `src/state.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/wizard.py`, `src/web/jobs.py`, `src/web/static.py`, `scripts/verify.sh`, `tests/test_agent_harness.py`, `tests/test_web_phase_d.py`
- `expected_changes`: `src/workspace_files.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/wizard.py`, `src/web/jobs.py`, `src/web/static.py`, `scripts/verify.sh`, `tests/test_agent_harness.py`, `tests/test_web_iter157_health_closure.py`, `docs/iterations/iteration_157_health_report_security_job_harness_closure.md`, `docs/iterations/README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、真实 provider/计费入口、`小说txt/`、私有 workspace、`data/`、`outputs/`、`logs/`；不扩展到未复现的全仓 Path I/O。

1. 引入 workspace-relative、逐分量 no-follow 的有界普通文件读写能力，并迁移本轮 KB/draft HTTP 表面。
2. 统一 routes、server、wizard、degraded/storyboard 与 draft-meta 的异常记录和 Wizard 安全错误投影。
3. 将 job 初始持久化设为启动门禁，补充后续持久化降级投影，并严格分类 Dashboard/Wizard 轮询状态。
4. 让 verify 在调用者 TMPDIR 下建立 ownership-marked run root，并把 Python/Git/Apple 临时文件全部导向内部目录。
5. 先做聚焦测试、静态检查与 harness，再完成 correctness、security/boundary、Web/runner/harness 三路独立只读审查并修复有效 finding。
6. 形成 implementation commit 后只运行一次 `bash scripts/verify.sh`；通过后删除报告并同步 README、handoff、history，形成 docs-only 收官提交。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 KB/draft 正常与部分初始化兼容、job 首条/后续持久化语义、Dashboard/Wizard 状态分类及 verify 生命周期。
- `security_boundary`: 核对 ancestor/final symlink、特殊/超限文件、异常与 trace 安全投影、外部字节不变、owned root 删除边界。
- `extra_risk_view`: Web/runner/harness 视角核对轮询 timer/busy、job worker/handler 注册顺序、short write/fsync 回滚及 Apple 工具临时文件隔离。

- **A157-01**：KB/draft 正常及部分初始化兼容；ancestor/final symlink、特殊文件、超限文件失败关闭；外部字节不变；原子写失败清理临时文件。
- **A157-02**：synthetic key、完整 prompt、版权文本、signed URL、绝对路径均不出现在 HTTP body 或 stderr；安全日志仅包含有界 event、异常类型和 trace ID。
- **A157-03**：Wizard drama/novel/pipeline 5xx 使用固定通用错误卡与 trace ID；premise expansion 仍返回 202，但只给固定 `expansion_error` 和可选 `expansion_trace_id`。
- **A157-04**：FIFO、最终 symlink、超限日志、short write、fsync 失败均导致零 worker/零 handler、槽位释放；后续 append 失败投影 `persistence_degraded=true`。
- **A157-05**：Dashboard/Wizard 仅为 `pending/running` 继续轮询；终态、404、空对象、坏 JSON、新枚举、缺失状态立即停止并释放 busy，显示核对入口。
- **A157-06**：既有两个 harness 失败转绿；owned temp 被清理；未拥有 sibling 不被删除；`xcrun_db` 同名条目不获豁免。
- **A157-07**：iter155 Paid draft-save-review 按钮 busy 回归持续通过。
- **A157-08**：2026-07-28 规划表述明确为历史快照，当前事实只链接 handoff，且保留用户已有规划内容。
- 聚焦检查包含相关 unittest、`py_compile`、agent harness 与 `git diff --check HEAD`；最终 canonical 仅运行一次并产出 schema v2 `mock-functional`。

## Implementation Notes

待实施后回填。

## Acceptance Result

待验收后回填。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 收官审查后如发现可晋升的长期规则再更新。

## 文件变更汇总

待实施后回填。

## 不在本轮范围

- 不宣称全仓所有 descendant Path I/O 已迁移为 capability-dirfd；只闭合已复现的 KB/draft 路径面。
- 不改变 provider、计费、模型、workspace schema 或真实调用授权协议。
- 不运行真实文本、图片、视频、TTS 或 billing 请求，不做 push。

## Notes

- iter155 已闭合 Paid 按钮 `aria-busy`，本轮只保留回归证据，避免重复修改实现。
- 当前两份已修改规划文档按用户默认决策保留并纳入 iter157；只修正过期的“当前基线”表述，不覆盖其它内容。
