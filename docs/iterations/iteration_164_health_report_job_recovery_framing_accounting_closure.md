# Iteration 164 - 近期体检报告任务恢复、传输分帧与视频计账闭环

## Context

2026-08-01 至 2026-08-04 的四份未跟踪体检报告在当前 HEAD 上持续复现同一组问题。去重后为四个 P2：短剧任务结果链接丢失 episode/Local Demo target、重启后的 job detail/cancel 跨 workspace 扫描持久日志、protected mutation 未拒绝重复或空值分帧头、视频 reconciliation 已确定结果后 calibration 仍按 raw unknown 计账。8 月 3–4 日仅增强证据，没有第五项。用户要求在修复、审查和 canonical 验收全部通过后，删除且只删除这四份报告。

## Plan

### Implementation Context
- `must_read`: `src/web/jobs.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/static.py`, `src/drama_multimodal_smoke.py`, `src/paid_recovery_states.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_server.py`, `tests/test_drama_multimodal_smoke.py`, `docs/iterations/iteration_163_drama_video_submission_outcome_reconciliation.md`
- `expected_changes`: `src/web/jobs.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/static.py`, `src/drama_multimodal_smoke.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_server.py`, `tests/test_drama_multimodal_smoke.py`, `tests/test_web_iter164_health_closure.py`, `docs/iterations/iteration_164_health_report_job_recovery_framing_accounting_closure.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不读取或修改 `.env`、`小说txt/`、私有 `data/`/`outputs/`/`logs/`/workspace 内容；不查询真实 task/billing，不调用真实文本、图片、视频或 TTS provider；不改 paid submission ledger 或 reconciliation receipt schema；canonical 验收通过前不得删除四份体检报告

1. 为 recent/detail 公共 job 投影增加严格校验的 `result_context={workspace, episode_no}`，普通短剧任务冻结源 workspace/episode，Local Demo 指向已验证 target workspace/episode 1；历史记录按受控字段降级，任务卡只使用安全上下文导航。
2. 新增 workspace-scoped job lookup；HTTP detail/cancel 只读 URL 指定 workspace 的 no-follow、有界 ledger，并在取消 mutation 锁内再次核对 workspace。全局查找只保留给可信进程内调用。
3. protected POST/PUT 在 body read 前拒绝任意 Transfer-Encoding、缺失/重复/非规范 Content-Length；单个规范超限长度保持 413，routes 层 JSON/object/intent/same-origin/64 KiB 二次守门不变。
4. 抽取 reconciliation-aware 视频计账分类器；calibration schema 升至 v2，以 effective status 计 request/unknown，另保留 raw `source_submission_status`，异常持久化和 evidence 判定复用同一语义且不触发 provider 或自动重提。
5. 补齐聚焦单测、静态检查和 synthetic mock 浏览器任务页验证；审查与 canonical 验收通过后删除四份报告并完成文档收官。

## Acceptance

### Review Context
- `correctness_behavior`: 复核四报告到四根因的去重映射、episode 2 各终态与 Local Demo target 导航、scoped job 恢复/取消语义、视频 effective/source 状态与计数矩阵、旧日志与旧 phase state 兼容以及相关聚焦和浏览器证据
- `security_boundary`: 复核 result_context 防伪与公开字段最小化、跨 workspace job 不泄漏/不误取消、no-follow/有界日志读取、重复 CL/TE 在 body read 和 dispatch 前失败关闭、paid unknown/receipt/逐次授权与零自动重提边界
- `extra_risk_view`: Web/runner/multi-workspace 与媒体计账专项：复核请求级 I/O 收敛、任务卡真实链接、restart/lost/cancel 竞态、calibration/evidence 一致性及零 provider 调用

- **A164-01**：iteration 保存四份报告到四个根因的去重闭包，8 月 3–4 日的重复证据不计为新增 finding。
- **A164-02**：公共 `result_context` 严格有界且可持久恢复；episode 2 的 succeeded/blocked/failed/lost 和 Local Demo target 链接正确，非法上下文失败关闭。
- **A164-03**：detail/cancel 在 live、restart、unknown 与跨 workspace 场景只读取 URL 指定 workspace；其它 workspace ledger 读取次数为 0，restart pending/running 仍安全投影为 lost。
- **A164-04**：duplicate CL 同值/异值、duplicate/空首 TE、缺失或非规范 CL 均在 body read/dispatch 前返回 400；单个规范超限 CL 保持 413，合法 mutation 与非 protected 行为不回归。
- **A164-05**：submitted、provider_rejected、still_unknown、request_not_sent、无 ledger legacy、坏 receipt 与 poll-only 失败的 calibration schema v2 effective/source 状态和 1/0、0/1、0/0 计数正确；provider 调用和自动重提均为 0。
- **A164-06**：iter162/163 的公开脱敏、JSON/intent/same-origin/容量守门、视频三分状态、append-only receipt 与逐次授权回归保持；不读取保护目录，不查询或调用真实 provider。
- **A164-07**：聚焦 unittest、Python/Node 静态检查、harness、diff check 与 synthetic mock 浏览器任务页通过；correctness、security/boundary、Web/runner/multi-workspace+媒体计账三路独立只读审查无剩余有效 finding。implementation commit 上最终 `bash scripts/verify.sh` exit 0、schema v2、`mock-functional` / `canonical-mock-offline`、`tracked_scope_clean=true`；浏览器证据单列 `local-e2e`，不得宣称 `provider-validated`。

## Implementation Notes

- 新建 job 在 admission 时冻结严格 `result_context`，持久行和 recent/detail 公共投影复用同一验证器；历史行只从受控 Local Demo target、互相一致的 episode 字段和安全 episode 1 默认降级。Local Demo 结果沿既有产品语义进入 target `/compose?episode_no=1`，而非在源 workspace 打开页面。
- HTTP detail/cancel 改用 workspace-scoped lookup；全局查找仍只供可信进程内调用。cancel mutation 在 `_JOBS_LOCK` 内二次核对 workspace，restart pending/running 仍只读目标 ledger 并投影为 lost。
- protected mutation 在 body read 前检查 header 全列表；任意 TE、缺失/重复/非规范 CL 返回 400，唯一规范超限 CL 保持 413。非 protected POST 的缺省空 body 行为保持兼容。
- 视频计账从同一次 durable submission snapshot 得到 raw/effective 状态、request/unknown、consumed 与费用真源；phase cost 不再覆盖 ledger。无 ledger 时兼容 both-missing 与 iter094–096 的 paid-only=1 历史形状，统一保守为 `0/1 still_unknown`；unknown-only、paid-only=0/consumed 和其它矛盾状态失败关闭。
- 三路初审共确认 1 个 lost CTA P2、3 个 Web/媒体专项 P2、1 个 paid-only 历史兼容 P2 和 1 个 legacy 精确性 P3；均经主线程复核后修复。最终 correctness、security/boundary、Web/runner/multi-workspace+媒体计账复核均无剩余 P0–P3。
- synthetic mock 浏览器实测：episode 2 succeeded 与 restart-lost CTA 均进入 `/w/alpha/write?episode=2`；Local Demo CTA 进入隔离 target `/compose?episode_no=1`。未调用 provider。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮是在落实既有 workspace isolation、公开投影、transport framing 与 paid reconciliation 合同；审查 findings 属具体实现补漏，没有形成新的跨迭代长期规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/jobs.py`、`src/web/routes.py`、`src/web/static.py` | 新增严格结果上下文、workspace-scoped job 恢复/取消和安全任务 CTA |
| `src/web/server.py` | protected mutation 重复/非规范 HTTP framing 读前失败关闭 |
| `src/drama_multimodal_smoke.py` | reconciliation-aware calibration schema v2、同快照状态/费用计账与 legacy 兼容 |
| `tests/test_web_iter164_health_closure.py`、`tests/test_web_server.py`、`tests/test_drama_multimodal_smoke.py` | 四根因、审查 findings、历史兼容与失败边界回归 |
| `docs/iterations/iteration_164_health_report_job_recovery_framing_accounting_closure.md`、`docs/iterations/README.md` | 迭代计划、实现记录、验收索引与收官证据 |

## 不在本轮范围

- 不处理 iter143 的真实 task/billing/rejection 对账，不做任何真实 provider 查询或提交。
- 不扩展 TTS/JPEG/WebP/provider adapter、完整单集或 episode 2+ 真实媒体校准。
- 不运行小说 10–20 章真模型 capstone，不调整真实文风阈值。
- 不解决 handoff 已记录的长期公网多租户、非合作本机 writer 或通用物理 GC 边界。

## Notes

- 四份报告是本轮验收前证据，保持未跟踪且不暂存；只有 A164-01 至 A164-07 全部闭合后才删除精确路径。
- 收官使用 `iter-finish`，只 commit、不 push。
