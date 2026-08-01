# Iteration 163 - 短剧视频提交结果分流与历史 Unknown 对账凭证

## Context

当前真实视频 create 将 provider 明确拒绝与响应丢失混入同一个 `submission_unknown`，使“请求确定未发送”“provider 明确拒绝”“提交状态真正未知”无法被可靠区分。iter143 的历史 create 只有本地 `submitting` 账本；在没有绑定该次尝试的权威 task、billing 或 rejection 新证据前必须继续保持 unknown，任务列表未新增不能证明请求未发送，也不能释放重提机会。本轮只做 mock/offline 工程实现与安全投影，不查询真实 provider，不运行真实媒体，不改变 iter143 的历史事实。

## Plan

### Implementation Context
- `must_read`: `src/drama_video.py`, `src/drama_video_client.py`, `src/secure_http.py`, `src/paid_recovery_states.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/web/static.py`, `tests/test_drama_video.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_143_drama_video_20s_quality_sample.md`
- `expected_changes`: `src/drama_video.py`, `src/drama_video_client.py`, `src/paid_recovery_states.py`, `src/web/routes.py`, `src/web/static.py`, `tests/test_drama_video.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_163_drama_video_submission_outcome_reconciliation.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不读取或修改 `.env`、`data/`、`outputs/`、`logs/`、`workspaces/`、`小说txt/`；不调用真实 provider、不执行真实 TTS/图片/视频、不查询 iter143 task/billing/rejection、不改写 iter143 历史账本或证据

1. 为视频 create 建立明确、封闭的结果分类：transport 证明请求未发送；provider 已返回明确拒绝；发送后无可判定响应而提交状态真正未知。仅第一类允许恢复未消费机会，明确拒绝必须持久化为已消费终态，真正未知继续 fail closed。
2. 为历史 `submission_unknown` 建立独立、append-only、CAS 保护的 reconciliation receipt。凭证必须绑定精确 submission revision/identity 与权威证据类别；冲突、乱序、覆盖、重复但不一致和无证据推断均拒绝。无凭证或凭证只证明“列表未新增”时保持 unknown。
3. 为视频状态/API/页面建立安全公开投影，只暴露产品可用的安全状态与动作提示，不公开 provider task/request ID、响应正文、素材身份或证据指纹。
4. 用回归测试固定 iter143：没有权威新证据时仍为 unknown；task list count/absence 不是权威否定证据；任何再次运行或 Web 动作均不得 upload/create。
5. 在产品 SOP 与 handoff 中固化后续真实闭环的独立授权顺序：iter143 只读 task/billing/rejection（upload/create=0）→ 实现真实 TTS adapter 后授权 1 条语音 → 新 namespace 授权 1 个单镜图片/视频样本 → 通过后完整单集 → episode 2+ 与多集另行授权。前一步授权与证据不得传递到后一步。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 create 三分法与异常边界是否互斥完备；明确未发送是否仅在 transport 可证明时释放机会；明确拒绝与真正 unknown 是否各自持久化且不触发重提；legacy/iter143 行为是否向后兼容
- `security_boundary`: 核对 reconciliation receipt 的 append-only、CAS、nofollow/原子写、identity/revision/evidence 校验；公开 API/DOM/错误是否排除 task/request ID、响应正文、素材身份与所有 evidence/provider 指纹
- `extra_risk_view`: 真实媒体与计费恢复专项：核对 task-list absence 不被当作权威证据，iter143 未被重分类或重提，所有后续 provider 阶段保持逐项独立授权且本轮 provider 调用为零

- `A163-01`：聚焦测试证明 video create 的 `request_not_sent`、`provider_rejected`、`submission_unknown` 三类互斥；仅明确未发送可安全恢复机会，后两类均消费原授权且不自动重提。
- `A163-02`：聚焦测试证明 reconciliation receipt 只追加、CAS 绑定 exact submission identity/revision；exact replay 幂等，冲突/乱序/覆盖/未知证据类别 fail closed，只有绑定的权威 task/billing/rejection 证据可以形成确定结论。
- `A163-03`：Web/API/DOM 安全测试证明公开状态只含 allowlist 字段与安全文案，不含 provider task/request ID、响应正文、素材身份、prompt/hash 或 evidence/provider 指纹。
- `A163-04`：iter143 回归证明无新权威 receipt 时始终为 `submission_unknown`；“任务列表未增加/未发现匹配任务”不能转为未发送或拒绝，重复运行、刷新和对账读取均为 upload/create=0。
- `A163-05`：SOP 与 handoff 明确五段真实闭环各自需要新的显式授权，顺序和 `upload/create=0` 只读边界完整，前序授权不跨阶段继承。
- `A163-06`：聚焦检查、correctness/security/真实媒体计费三个独立只读审查视角闭合；最终只运行一次 `bash scripts/verify.sh` 并达到 `mock-functional`，不得据此宣称 `provider-validated`。

## Implementation Notes

- 新增 `VideoCreateRejected`，只把 4xx create 响应分类为 provider 明确拒绝；5xx、畸形 JSON、成功响应缺/冲突 task ID 仍保守归入真正 unknown。异常不保存 response body，只携带有界 status/outcome/error class/request ID 供私有 ledger 使用。
- Episode 1 video ledger 新增 `request_not_sent / submission_unknown / provider_rejected`，保留旧 `submitting` 兼容 unknown。只有 `request_not_sent` 的 `submission_count=0`；其余 create 结果均消费原授权且无自动重提。
- 合理范围扩展：新增 `src/drama_video_reconciliation.py` 与两份 iter163 测试，并同步 `src/drama_multimodal_smoke.py`、crash matrix。Receipt 独立于原 submission ledger，使用 exact submission identity、无写入 source revision、sidecar generation、sequence/time、previous receipt、evidence 与 ledger fingerprint；workspace lock 下执行 source/sidecar/ledger 多重 CAS，再复用 no-follow 原子 ledger writer。Legacy status/inspect/run 不迁移或改写原 `submission.json`，A→B→A 与 stale view 均 fail closed。
- Task-list absence 被建模为 `task_list_observation + still_unknown`；schema 不允许历史 receipt 形成 `request_not_sent`。只有 exact task query 或明确 provider rejection 可形成确定结论，billing 无 task 仍保持 unknown。
- Web API 在领域安全投影外再做第二层 allowlist；成功视频 meta、拒绝与对账状态均不公开 provider task/request ID、response body、素材/sample identity 或任何证据/provider/prompt fingerprint。前端只对 `request_not_sent` 提供重新明确授权入口，拒绝与 unknown 均隐藏 create。
- 本轮没有真实查询、upload/create、TTS、图片或视频调用；没有读取 `.env`、私有 workspace、运行日志或小说原文。用户给出的五段真实闭环只写入产品 SOP，未被解释为本轮授权。
- 聚焦回归最终为 136 tests OK。三路独立只读审查先发现并修复：resolution 同类身份可被改写、source CAS 的 ABA 缺口、legacy read-time migration、multimodal reconciliation-aware poll-only 漂移，以及 known/unknown 计账重叠；修复后 correctness、security/boundary、真实媒体/计费三路最终均为 no findings。

## Acceptance Result

- `A163-01`：通过。client/ledger/恢复矩阵已将 `request_not_sent`、`provider_rejected`、`submission_unknown` 建模为互斥结果；只有 transport 明确证明未发送时 `submission_count=0` 且可在新的显式授权下重试，拒绝与 unknown 均消费原授权并禁止自动重提。
- `A163-02`：通过。reconciliation sidecar 为 append-only receipt chain，绑定 exact submission identity、source revision、ledger fingerprint、sidecar generation、sequence/time 与 previous receipt；exact replay 幂等，stale/乱序/冲突/ABA/结论改写均 fail closed，且读取 legacy submission 不改写源文件。
- `A163-03`：通过。领域投影与 Web API 双 allowlist，页面只显示安全状态和动作提示；task/request ID、response body、素材/sample 身份及 evidence/provider/prompt fingerprint 均不进入公开 JSON/DOM。
- `A163-04`：通过。iter143-compatible 回归固定：无绑定该次提交的权威新证据时始终为 `submission_unknown`；task-list absence 只能追加 `still_unknown` 观察，不能推出未发送/拒绝，inspect/resume/reconciliation read 的 upload/create 均为 0。
- `A163-05`：通过。产品 SOP、README 与 handoff 固化五段独立授权顺序：iter143 只读 task/billing/rejection（upload/create=0）→ 实现真实 TTS adapter 后 1 条语音 → 新 namespace 下 1 个单镜图片/视频样本 → 通过后完整单集 → episode 2+ 与多集另行授权；授权不跨阶段继承。
- `A163-06`：通过。聚焦回归最终 **136 tests OK**；correctness、security/boundary、真实媒体/计费三个独立只读审查视角的 findings 修复后均为 no findings。首次 canonical 验收在 3025 项中发现 2 个旧测试仍断言旧 `submitting`/按钮契约，已由 `ea4e1d4` 同步为三分状态契约；随后按失败范围完整重验通过。

最终标准验收：implementation commit `ea4e1d4ce8f362abb1ed534ea9e3d518b186c2de` 上执行 `bash scripts/verify.sh`，**3025 tests OK**，15 steps，481 秒，run `44fb300e4c994e068c8131ff30f6a009`，schema v2 `status=passed`、`acceptance_level=mock-functional`、`verification_profile=canonical-mock-offline`、`workspace_scope=isolated-mock`、`tracked_scope_clean=true`；`local_drama_e2e` 子步骤通过，但不把总级别升级为 `local-e2e` 或 `provider-validated`。本轮真实 provider 查询、upload、create、TTS、图片与视频调用均为 0。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: video create 三分法、历史 unknown 对账证据等级和五段独立授权顺序会持续约束真实媒体恢复与下一轮入口，属于长期产品安全协议而非仅本轮实现细节。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_video_client.py` | 为 create 4xx 增加有界、无正文的明确拒绝类型；5xx/坏响应继续保守为 unknown |
| `src/drama_video.py` | 持久化 create 三分法、接入私有 reconciliation resolution、收窄公开视频 meta |
| `src/drama_video_reconciliation.py` | 新增 append-only receipt、sidecar generation、source/ledger CAS、结论冻结与 no-follow 原子持久化 |
| `src/paid_recovery_states.py` | 扩展视频状态词汇，拆分 known-consumed 与 submission unknown 互斥计账 |
| `src/drama_multimodal_smoke.py` | 统一 reconciliation-aware poll-only 恢复及 request_not_sent/unknown 计账 |
| `src/web/routes.py` | Web resume 使用安全领域状态，API 再做顶层与 nested video allowlist |
| `src/web/static.py` | 增加三类安全文案，仅 request_not_sent 显示重新独立授权入口 |
| `tests/test_drama_image_video_clients.py` | 覆盖 4xx 明确拒绝、正文脱敏与 5xx unknown |
| `tests/test_drama_video.py` | 覆盖 create 三分法、耐久状态、重试边界与安全公开 meta |
| `tests/test_drama_video_reconciliation.py` | 覆盖 iter143 unknown、append/CAS/ABA/结论冻结、legacy 不改写与 poll-only |
| `tests/test_web_iter163_video_reconciliation.py` | 覆盖 Web allowlist、DOM 文案/按钮与对账后 poll-only resume |
| `tests/test_drama_multimodal_smoke.py` | 覆盖 multimodal 未发送计账与共享 reconciliation-aware resume view |
| `tests/test_drama_paid_recovery_states.py` | 固定完整、互斥的状态分类 |
| `tests/test_drama_crash_restart_matrix.py` | 固定所有视频状态的恢复策略 |
| `tests/test_drama_iter098_hardening.py` | 同步 request_not_sent 耐久 marker 契约 |
| `tests/test_drama_iter097_hardening.py` | 将旧 `submitting` 断言同步为明确的 `submission_unknown` |
| `tests/test_drama_iter099_hardening.py` | 同步 Web 三分状态下的授权按钮契约 |
| `docs/product/short_drama_module.md` | 固化三分法、私有对账、公开边界与五段独立授权 SOP |
| `docs/iterations/README.md`、本文件 | 登记 iter163 并记录计划、实现、审查与验收证据 |

## 不在本轮范围

- 不真实查询 iter143 task/billing/rejection，不修改其 unknown 历史事实，不提交或重提任何真实视频。
- 不实现或调用真实 TTS adapter，不授权语音、图片、视频、完整单集、episode 2+ 或多集。
- 不把 mock/local 验收表述为真实 provider、费用、SLA 或主观质量证据。

## Notes

- 用户给定的真实闭环顺序属于后续授权路线图，不是本轮任何真实外部动作的授权。
