# Iteration 137 - 短剧媒体 Owner-Guarded Provider Execution Loop

## Context

iter133-136 已完成 G1 task DAG、G2 worker ownership/capacity、G3 static registry/frozen binding 与 G4 原子持久 binding/纯本地 queue client，但 queue 尚不能把一个已 claim 的 provider task 按 frozen capability 驱动到 submit、poll、download、validate。阶段 G 的 G5 建立由 current lease owner 驱动、按付费证据 fail-closed 的执行 loop；本轮只用注入 fake adapter 与 synthetic paid-evidence bridge 验证编排，不接真实 provider、不迁移 C/D/E paid ledger，也不测试 TTS。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_queue_client.py`, `src/drama_media_backends/base.py`, `src/drama_media_backends/registry.py`, `src/drama_shot_image_attempt_store.py`, `src/drama_shot_video_attempt_store.py`, `src/drama_tts_attempt_store.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_media_tasks.py`, `src/drama_media_worker.py`, `src/drama_media_executor.py`, `tests/test_drama_media_executor.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_137_drama_media_owner_guarded_provider_execution_loop.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真实文本以外的 provider、图片、视频或 TTS，不新增动态 adapter loading，不读取/改写现有 C/D/E paid ledger，不接 Web mutation，不做 pricing/Insights，不 push

1. 新增 strict execution adapter/paid-evidence bridge 协议；adapter 由受审查代码显式注入并绑定 exact persisted backend binding、task input、worker/token 与 lease revision，不允许从 registry 重解析、动态 import、携带 credential/prompt/URL 或把 generic receipt 当 paid receipt。
2. 建立 owner-guarded 单步执行：在 provider 动作前把 generic task 原子推进到对应 phase，动作后再次以 current owner/token、task/lease revision 和 expected ledger CAS 提交 observation；外部动作不占 workspace lock，失去 lease 或 takeover 后旧 worker 的结果不能提交。
3. submit/poll/download/validate 各自独立策略：只有 paid bridge 明确 `not_sent` 才能形成可重试失败；提交结果不明直接进入 `submission_unknown` 且零自动重发；poll pending 保持可恢复；download/validate 只消费权威 paid/artifact evidence fingerprint，不保存上游 task ID、响应正文、URL 或字节。
4. 支持同步 image、异步 video 和 synthesis/download 分离的 audio capability 形态，但本轮仅用零网络 fake bridge；loop 有 bounded step/deadline/cancel/heartbeat 边界，不做无界轮询，不把 cancel request 冒充 provider cancel confirmation。
5. 用 crash/restart、takeover、lost response replay、unknown、not-sent、pending、terminal failure、download/validate failure、binding drift 与 socket 零网络测试证明一次性和恢复；不改变 C/D/E paid ledger schema、authorization、artifact 或 receipt 真源。

## Acceptance

### Review Context
- `correctness_behavior`: image/video/audio phase 路由、owner/token/revision 守卫、submit unknown 零重提、poll pending 恢复、download/validate exact evidence、lost-response replay、takeover 与 terminal lease cleanup 必须确定；不得改变 G1-G4 task/dedupe/binding 或 C/D/E paid ledger 语义
- `security_boundary`: adapter/bridge 必须显式注入且 identity-bound；无动态 code/credential/network，外部动作不持 workspace lock，所有返回只接受 strict bounded enum/fingerprint；旧 owner、stale CAS、binding/provider drift、超时、取消与异常 fail closed，公开错误不泄露 prompt/URL/response/path/paid evidence
- `extra_risk_view`: runner/media/paid 专项，复核 pre-call/post-call crash windows、权威 paid evidence 单向桥接、unknown/no-resubmit、TTS synthesis/download 分离、cancel 不伪造上游确认与零网络测试证明

- **A137-01**：strict adapter/paid bridge 只消费 exact persisted binding 与 current owner lease；动态 callable/registry re-resolution/identity drift/旧 owner result 均 fail closed。
- **A137-02**：submit、poll、download、validate 以 owner-guarded step 和 ledger CAS 推进；同步 image、异步 video、audio synthesis/download 路由及 crash/restart/lost-response replay 行为确定。
- **A137-03**：只有权威 `not_sent` 可形成安全失败；`submission_unknown` 零自动重发，pending 可恢复，terminal/cancel/failed lease cleanup 与 generic/paid evidence 单向边界保持。
- **A137-04**：loop 的 deadline、heartbeat、step 上限、异常与 projection 有界，测试期间零 socket/provider/图片/视频/TTS 调用，且不修改 C/D/E paid ledger schema 或产物。
- **A137-05**：聚焦回归与 correctness/security/runner-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 新增 `DramaMediaPaidEvidenceBridge` 显式代码 seam 与 content-addressed observation。bridge 不携带 credential、prompt、URL、provider task ID、response、artifact path 或 paid receipt；identity 必须逐项匹配 frozen binding/task，observation 额外绑定 exact execution context fingerprint，阻断跨 task、跨 owner 或旧 lease replay。
- executor 每个 bridge action 前先以 current owner/token heartbeat；provider 动作在 workspace lock 外执行，动作后的 generic transition 继续用 heartbeat 后的 task/lease revision 与 ledger CAS。旧 owner、过期 lease、并发 cancel/takeover 的结果无法提交，崩溃后由下一 owner 调 bridge 的 inspect-or-submit 合同读取权威 paid ledger。调用方 deadline 同时进入 context fingerprint；generic 层到期后不开始新动作，真实 bridge 仍须据此约束自身 transport，因为同步调用不能由 executor 安全抢占。
- phase 路由保留媒体差异：同步 image 为 submit→validate，异步 video 为 submit→poll→download→validate，audio 为 synthesis submit→download→validate。pending 立即返回，run 最多 16 步且零 sleep；cancel request 不调用 bridge 或写 `cancel_confirmed`。
- 只有 bridge 明示 `not_sent` 才落确定失败；submit 异常、坏 observation 与 post-call identity drift 保守进入 `submission_unknown`。poll/download/validate 非结构化异常保留原 phase 供恢复；结构化 terminal observation 才提交对应 failed/succeeded。
- 审查补强调用前 deadline 二次检查，以及三类 `os._exit` 新解释器 crash seam：generic `submitting` 后、paid submit 已记账但 generic 未提交后、generic `submitted` 已提交但 caller 未收响应后；均由持久 synthetic paid counter 与过期 lease takeover 恢复，submit 外部计数严格保持 1。另覆盖 cancel 与 in-flight submit 竞态，旧结果不能把 `cancelling` 写成 submitted。为承载该证明，实际变更面合理增加 `tests/support/drama_media_executor_driver.py`。
- 本轮没有新增真实 adapter 或动态 loader，没有读取/迁移 C/D/E paid ledger；新增 audio download 异常后只重下载、不重 synthesis 的恢复回归。73 项 G2-G5 聚焦回归通过；当前 G5 证据为 `mock-functional`，不把 synthetic bridge 冒充 production-adapter `local-e2e`。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: owner-guarded bridge identity/context、inspect-or-submit、三类 crash window、deadline 与 generic/paid 单向边界是后续真实 adapter、pricing/Insights 和生产工作台必须复用的持久产品合同，已在 G5 权威段落与阶段表就地固化。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_media_executor.py` | 新增 owner-guarded bounded execution loop、显式 paid bridge、context-bound observation 与安全投影。 |
| `tests/test_drama_media_executor.py` | 覆盖 image/video/audio 路由、pending/restart、unknown/not-sent、identity/context drift、cancel/deadline 与零网络。 |
| `tests/support/drama_media_executor_driver.py` | 新增 `os._exit` 后新解释器、持久 paid counter 与 takeover 恢复 driver。 |
| `docs/product/short_drama_module.md` | 登记 G5 权威合同、精确恢复边界与未验证范围。 |
| `docs/iterations/{README.md,iteration_137_*.md}` | 登记 iter137 计划、实施、审查与验收记录。 |

## 不在本轮范围

- 真实图片/视频/TTS provider adapter、真实 TTS 测试、Web mutation、pricing/Insights。
- 现有 C/D/E paid ledger 迁移、自动 reconciliation、真实媒体质量与 provider SLA 结论。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
