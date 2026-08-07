# Iteration 166 - 小说原创/续写双链失败恢复与真模型前端验证

## Context

用户在一句话原创开书与导入小说续写两条 Web 链路中确认了同类恢复故障：运行期合法子阶段被显示为“未识别步骤”；正文任务未成功后，“查看并重试”只跳到第 4 步，readiness 仍保持阻断且“开始写书”不可点击。只读定位表明，前端混用了顶层 `job.step` 与动态 `job.current_step`，`retry_exhausted` CTA 没有接通 `write-book force=true` 的可恢复协议，工作台又把任意草稿存在误判为完成。本轮在不读取用户原文或凭据的前提下统一修复原创/续写双链，补齐有界真实文本授权，并以两个全新 synthetic workspace 做浏览器单章真模型验证。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_165_novel_web_mode_navigation_reliability.md`, `src/readiness_catalog.py`, `src/web/static.py`, `src/web/jobs.py`, `src/web/routes.py`, `src/book_runner.py`, `src/chapter_status.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_jobs_dispatch.py`, `tests/test_book_runner.py`
- `expected_changes`: `src/web/static.py`, `src/web/jobs.py`, `src/web/routes.py`, `src/llm_client.py`, `src/debater.py`, `tests/test_web_iter166_recovery.py`, `tests/test_web_ui_design_system.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_jobs_dispatch.py`, `tests/test_book_runner.py`, `docs/iterations/iteration_166_novel_dual_flow_recovery_real_provider_validation.md`, `docs/iterations/README.md`
- `do_not_touch`: `.env`、用户现有 `workspaces/`、`小说txt/` 原文、私有样本、`data/`、`outputs/`、`logs/`、两份未跟踪体检报告；真实文本只允许用户已授权的当前 Web provider/model，双链累计最多 160 次请求/人民币 40 元，不运行图片、视频或 TTS

- 分离顶层任务与运行子阶段展示，对合法动态进度做中文白名单归类，未知值安全回退且不泄漏原始内部 ID。
- 修正工作台正文状态：仅严格通过进入 `done`，失败稿投影为可查看、可确认恢复的 `retry_required`。
- 为原创与续写建立同一套失败稿恢复协议：服务端重新校验当前失败章与状态指纹，用户明确确认后以单章 `force=true` 新建 job；旧稿归档，历史确认不复用，lost/unknown/active 零重提。
- 修正 `/continue` 与 `/workbench` 的恢复 UX、一般失败分类、重复点击和任务槽释放竞态，不再出现禁用按钮死路。
- 为真实小说付费步骤加入服务端校验的人民币额度、超时与模型请求数上限；同一阶段授权不继承到下一阶段或 force 恢复。
- 使用 synthetic 原创和三章 synthetic 导入文本，从浏览器逐步点击到单章正文；先做当前 Web 模型联通性检查，失败时保留现场并等待用户更换模型/API 后继续，不自动重发不明请求。

## Acceptance

### Review Context
- `correctness_behavior`: 复核原创/续写两种 creation mode 的动态 current_step 显示、工作台严格完成判定、失败章恢复资格与 force 单章重写、旧稿归档、新 job/轮询、双击与 slot-release 竞态；普通失败、预算失败、lost/unknown 不得误入正文恢复
- `security_boundary`: 复核恢复状态指纹、workspace/章节/计划/模式重新校验、确认字段不持久化或重放、公开投影不泄漏原文/路径/raw step/完整 prompt/provider 响应；真实模型严格受 160 请求/40 元、分阶段额度与超时约束，且不读取 `.env` 或私有 workspace
- `extra_risk_view`: Web/UX + provider/budget 专项：两条全新 synthetic 链的桌面/平板/移动端点击、付费确认、刷新恢复、取消、console、请求/费用闭合，以及联通失败后换模型继续的安全边界

- **A166-01**：合法静态/动态 `current_step` 均显示安全中文；未知子阶段不泄漏原始值、不显示“未识别步骤”，主进度与取消提示同源。
- **A166-02**：工作台公开 `write_state` 与 `retry_chapter`；Reject/halt/retry_exhausted 草稿不判 `done`，原创与续写均停留在可处理正文阶段。
- **A166-03**：失败稿恢复提供查看与显式确认；服务端状态指纹/current mode/plan/chapter/slot 校验通过后才新建单章 force job，旧稿归档、新 job ID 可轮询，确认字段不持久化。
- **A166-04**：`/continue` 与 `/workbench` 均无 disabled 死路；双击、状态漂移、终态/slot-release 409、刷新/取消有确定行为，lost/submission_unknown/未知/一般失败/额度失败零自动重提。
- **A166-05**：所有真实小说付费阶段校验 `budget_cny`、`timeout_minutes`、`max_model_requests`；请求前检查阶段/累计上限，未知定价或上限耗尽停止，付费确认不进入可重放 params。
- **A166-06**：聚焦 Python/JS/mock E2E 覆盖原创/续写、动态步骤、恢复协议、归档、竞态、预算/超时/请求上限并通过；浏览器三视口无关键 console error/warning、横向溢出或不可达控件，证据至少 `local-e2e`。
- **A166-07**：当前 Web provider/model 经脱敏 preflight 后，synthetic 原创与续写各自从前端逐步点击到一章正文；双链累计不超过 160 请求/40 元。证据闭合则分别记窄范围 `provider-validated`，否则按实际阻塞记 `safe-blocked`，不得外推长跑或其它 provider。
- **A166-08**：correctness、security/boundary、Web/UX+provider/budget 三路只读审查无未处理有效 finding；implementation commit 上最终只运行一次 `bash scripts/verify.sh` 并通过，canonical 不低于 iter165 的 3072 tests，标准结论为 `mock-functional`。

## Implementation Notes

- 前端把稳定的 `job.step` 与动态 `job.current_step` 分开翻译；合法动态阶段走白名单中文标签，未知值只回退顶层任务名或“任务处理中”。主进度、取消提示与任务详情共用同一函数。
- 工作台以 `write_state=not_started|needs_review|retry_required|approved` 表达正文状态，只有严格通过才进入 `done`。`/continue`、`/workbench` 与任务页仅对 exact `retry_exhausted` 提供“查看失败稿→显式确认→归档并重新生成本章”，一般失败、额度不足、lost/unknown 均不获得 force 入口；409 按 busy/需对账/状态漂移给出确定动作且不自动重提。
- 新恢复协议的内容无关指纹绑定创作模式、续写 manifest 与已解析起点、扩写稿、KB→大纲→细纲 freshness、正文/meta/review。POST 与 worker 写锁内各复核一次；任务账本使用 `absent|ok|indeterminate` 三态和 durable claim，跨进程插入或更新任何 foreign job 都在归档/模型调用前阻断。
- force 归档改为 dir-fd + `O_NOFOLLOW`/no-replace：拒绝 symlink/非目录，唯一目录不覆盖，同一代全部副本与 reason 落盘后才移除当前稿。一次确认、状态指纹、ledger claim 与 worker job id 均不进入公开投影或通用重放参数。
- Web 小说模型阶段以服务端 step 表同时提供默认值与硬上限；真实 provider 的每次 attempt（含安全重试、cache downgrade、JSON repair）都计入 ContextVar 请求额度，并在调用前检查已知费用。未知价格在 preflight 与首次 provider 请求前 fail closed；mock 保持严格离线，CLI 历史估值兼容不作为付费硬上限。
- 立项后的首轮三视角审查闭合了坏/超限 ledger fail-open、归档 symlink/覆盖、专用 intent 漂移、wizard 自动扩写缺限制、上游 freshness/起点未绑定、409 无操作提示和跨进程 paid-job 竞态。收官复审又闭合 raw `current_step` 公开/持久泄漏、通用 `/run force=true` 绕过、非 exact 同章 `retry_exhausted` 恢复、legacy/tampered plan 假入口、timeout 误报取消、wrapped provider failure 丢分类、lost/unknown 重提、细纲更新后隐藏恢复入口，以及流式读取不受外层 deadline 约束。
- 用户启动隔离服务后，Codex 在原创 synthetic `test01` 的真实浏览器链路中观察到准备、大纲和 5 章细纲成功，工作台进入“④ 撰写正文”，“开始写书”可用，动态步骤未再出现“未识别步骤”。随后两次正文尝试均在约 125 秒后收到上游 timeout，系统未自动重发且未生成草稿/评审；用户重启后自行完成本地测试并明确报告成功。该证据仅将原创链标记为“Codex 观察至细纲 + 正文成功为用户声明”，不伪装成 Codex 观察到的正文成功。
- 续写 synthetic 链没有取得完整真实 provider 浏览器证据；其导入/恢复协议由确定性 mock E2E 覆盖。三视口与完整双链 provider 走查也未形成可审计证据，因此本轮不得宣称完整双链 `provider-validated`，也不外推其它 provider、多章长跑或 SLA。用户本轮明确取消价格/预算考量，但实现仍保留请求数、超时和配置上限；凭据、provider 地址和文本内容均未进入文档。
- 收官 findings 修复后的聚焦回归为 338 tests OK，受影响 Python 语法检查、harness（accepted iter165 / active iter166）与 `git diff --check` 均通过。Web 活动 deadline 会强制改用带剩余时间 clamp 的非流式 provider 请求；若同步 provider SDK 完全违反 timeout 契约且永久不返回，Python 工作线程仍无法提供进程级强杀，这是外部 transport 残余而不是本轮的硬中断保证。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 付费失败恢复必须绑定 exact durable terminal、完整上游 freshness、内容无关状态指纹与 durable ledger claim，并在归档/付费调用所在写锁内再次复核；这是可复用于其它付费重试入口的长期安全规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `<iter-finish 回填>` | `<iter-finish 回填>` |

## 不在本轮范围

- 用户私有原文、现有 workspace 与两份未跟踪体检报告。
- 图片、视频、TTS、短剧、多章长跑、10–20 章 capstone 和其它 provider 的质量/SLA 外推。
- 与原创/续写双链无关的纯视觉 P3；记录后顺延，不扩大本轮。

## Notes

- 真模型使用当前 Web 设置中的 provider-prefixed 模型；联通或鉴权失败时暂停并等待用户更换模型/API，再经新授权继续，不把失败直接当作取消测试。
- implementation 完成后必须使用 `iter-finish` 收官；只 commit、不 push。
