# Iteration 092 - 短剧真实多模态联测编排与生图重试硬化

## Context

Iteration 090-091 已分别完成短剧五站真文本 job 化、真生图安全入口与 episode 1 真视频端到端 wiring，mock 路径全绿。但多视角只读审查确认，当前仍不适合从 fresh workspace 一次性执行“真写作 + 真生图 + 真视频”：现有 `drama_smoke` 只为首个角色生图，视频入口却要求所有本集出场角色都有 fresh 参考图；生图当前是单次 300s、零重试，没有落地用户新指定的“超过 2 分钟可能失败，简化 prompt，再给首轮之外 2 次、每次 180s 受控重试机会”策略。

此外，真文本五站的 `budget_cny` 按站事后结算，`timeout-seconds` 也是每站而非全链总 deadline；真文本/生图与真视频两个 smoke 入口之间没有可恢复的阶段编排。本轮先把这些阻塞收口为安全、可审计、可分段授权的联测工具；立项不构成任何真文本、真生图或真视频授权。

## Plan

1. 新增可恢复的短剧多模态 smoke orchestrator/state machine，固定阶段为 `real_text -> all_character_images -> reassemble -> video_readiness -> real_video`；每个可能计费的媒体阶段使用独立确认、预算和超时，不得传递/继承上一阶段授权。
2. 将真生图改为所有 episode-1 出场角色逐张处理，每张成功后原子回填；任一角色缺图或失败即停在可恢复状态，不得进入视频提交。
3. 落地 `AGENTS.md` 工程铁律第 10 条：首轮生图失败/超时后先简化 prompt，再提供首轮之外最多 2 次、每次 180s 的受控重试机会。重试不得在同一进程中盲目自动发起；必须先停为 `awaiting_retry_authorization`，记录脱敏 attempt 审计，等 operator 确认上游任务/账单状态后再显式 resume。
4. 为生图定义确定性 prompt profile：首轮保留必需的主体/服装/构图/背景/无字要求，重试轮收缩到有界简化模板；不改写原始角色 schema 内容，只对请求副本做有界派生。
5. 为生图增加独立的 strict-bool 确认、finite 正预算、每次预估费用与总 attempt 上限；未确认、超预算、超次数或前一 attempt 状态未核对时，在网络前 fail-closed。日志只保留 attempt、timeout、prompt profile/hash、provider task/status 和有界费用，不记凭据、完整 prompt 或上游正文。
6. 区分生图 timeout 与普通 network/provider 失败，保证 urllib/socket 超时不再被统一折叠成 generic `ValueError`；失败状态可安全恢复且不重跑已成功的真文本站或角色图。
7. 将真文本预算/超时收口为联测级总预算和总 deadline：每站传剩余预算/时间，每次 LLM 前作最小预留或明确记录单调用 overshoot 语义；不得把一个每站 timeout 宣称为全链 deadline。
8. 真视频前增加零计费 readiness：必须通过 `load_video_inputs`、全角色参考图、episode hash/fingerprint/freshness、provider 结果域与预估费用配置检查；将 `SD_ASSET_PUBLIC_BASE_URL` “同一进程 capability token 可回连”作为明确的 operator 前置项。真视频仍保持一次付费提交、超时不重试。
9. 补齐 shell/Python/Web 入口、resume/state、全角色图、prompt 降级、最多 3 次总提交（首轮 + 2 次重试）、180s 超时、账单确认、预算/总 deadline、未授权 0 network 与视频零重试回归。
10. 收官运行 canonical、`scripts/verify.sh`、mock/真实配置 preflight、mock 多模态全链、Python/Node/shell/diff 检查；使用 `iter-finish`，并至少完成 correctness、security/billing boundary、orchestrator/Web integration 三个独立只读 subagent 审查与修后复核。

## Acceptance

- fresh episode-1 workspace 可在同一可恢复 run 中完成 mock 五站、所有出场角色图、重新组装、video readiness 与 mock 视频；成功阶段 resume 时不重复执行。
- 真文本、真生图、真视频三份授权严格独立；任一确认/正预算/正超时缺失都在网络前拒绝，不能通过 resume 或旧 state 继承。
- 所有本集出场角色均有当前参考图后才能进入视频 readiness；缺图、错 episode、stale/fingerprint/hash 不一致均 0 视频提交。
- 生图首轮之外最多 2 次重试，每次硬 timeout=180s；首轮失败后使用简化 prompt profile，每次 resume 都需要独立 operator 确认已查上游状态/账单，超过 3 次总提交必须 0 network。
- 生图有独立有界预算/预估费用守门和脱敏 attempt 审计；日志/公开 job 投影不含 API key、Authorization、完整 prompt、签名 URL 或上游响应正文。
- 真文本联测使用总预算和总 deadline，输出每站实际消耗与 remaining 值；任一上限到达后停在可恢复状态，不继续后续付费阶段。
- 真视频仍严格一次付费 submit、`automatic_retries=0`；生图重试策略不得污染视频 client/job/smoke。
- canonical unittest 以 **1880 tests OK** 为基线全绿；`PATH="$PWD/.venv/bin:$PATH" OPENAI_MODEL=mock bash scripts/verify.sh` exit 0；mock preflight 无 WARN/FATAL，真实配置 preflight 无 FATAL；Python/Node/shell syntax 与 `git diff --check` 通过。
- 未获用户后续分别明确授权时，真文本、真生图、真视频的网络请求/提交数均保持 0。实现验收后先报告服务/模型、最大请求数、最坏费用、时长/比例/分辨率和精确待执行命令，再等授权。
- correctness、security/billing boundary、orchestrator/Web integration 三视角首审、修复、复核结论与未修风险写入本文 `Acceptance Result` 或 `Notes`。

## Implementation Notes

- 开工时已有用户要求的 `AGENTS.md` / `docs/AGENT_HANDOFF.md` 生图全局测试记忆改动，以及未跟踪用户文件 `续写工作台.pptx`；本轮保留前者并不读取、修改、暂存或提交后者。
- `~/.claude/plans/docs-rosy-wadler.md` 当前不存在；本文以用户本轮指令和三个独立只读 subagent 的已确认证据为计划来源。
- 实现期间不得读取/修改 `.env`、不得读写用户私有样本或 `小说txt/`、不得跑任何真模型/真生图/真视频 smoke。

## Acceptance Result

- **功能验收**：新增可恢复 `real_text -> all_character_images -> reassemble -> video_readiness -> real_video` 编排器、shell 入口与脱敏 Web 状态投影。fresh `iter092_mock_validation` workspace 完成五站、2 名出场角色全图、重组、readiness 与 mock 视频；结果 `network_requests=0 / automatic_retries=0`，同命令 resume 不重跑已成功阶段。
- **生图重试边界**：首轮使用完整有界 prompt；失败后停在 `awaiting_retry_authorization`，每次 resume 要求独立重试确认 + 已查上游状态/账单，改用简化 prompt，每次 180s，每角色总提交最多 3 次。按预估费用在请求前记账，成功 artifact 恢复会校验 workspace containment 与 SHA-256。视频仍为单次付费提交、超时不重试。
- **预算/时间**：真文本改为全链总预算与总 deadline，各站仅接收 remaining 值并在后续阶段前 fail-closed；单站已在途调用仍是事后结算，已显式标记 `single_station_may_overshoot_before_settlement`。
- **铁律⑨审查**：correctness 首审发现 standalone 真生图后重组可用 `0.001` 绕过已耗尽的文本预算/deadline；已改为重组前严格守门、事后结算并复核超额。security/boundary 首审发现被篡改的 succeeded `artifact_path` 可在 resume 校验时读取 workspace 外文件；已增加 state 字段校验、`resolve()+relative_to()` containment 与 tamper 回归。两视角修后复核均 **PASS**；orchestrator/Web integration 首审直接 **PASS**。无未修 blocker/High/Medium。
- **验收证据**：聚焦影响面 **155 tests OK**；最终 canonical **1903 tests OK (skipped=7)**（较 iter091 的 1880 新增 23）；`PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh` exit 0（内部同样 **1903 tests OK** + auto-pipeline/status/manifest/report/cost 全过）；mock preflight ok/无 WARN/FATAL，真实配置 preflight warn/无 FATAL；Python `py_compile`、shell `bash -n`、`git diff --check` 通过。首次受限沙箱 canonical 的 12 个 localhost bind `PermissionError` 已在仅放开 loopback 的标准重跑中证实全绿。
- **付费边界**：本轮未运行真文本、真生图或真视频，三类真实网络请求/提交数均为 0。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_092_drama_multimodal_smoke_hardening.md` | 本轮 8 段计划与验收记录。 |
| `docs/iterations/README.md` | 追加 iter092 索引。 |
| `src/drama_multimodal_smoke.py` / `scripts/drama_multimodal_smoke.sh` | 新增可恢复的多模态联测状态机、独立授权/预算/时间闸与 shell 入口。 |
| `src/ai_draw_client.py` | 区分 timeout/network/provider 异常，支持有界 prompt override 与单 attempt 总 timeout。 |
| `src/drama_smoke.py` / `src/drama_video_smoke.py` | 支持总预算/deadline、按阶段 resume 以及不重置/不重建已有输入。 |
| `src/web/routes.py` | 新增只读、脱敏的多模态 smoke 状态路由。 |
| `tests/test_drama_multimodal_smoke.py` | 覆盖 fresh/resume、独立授权、预算/deadline、生图最多 3 次、账单确认、状态篡改与视频零重试。 |
| `README.md` / `docs/AGENT_HANDOFF.md` / `AGENTS.md` | 同步 iter092 SOP、Phase Status 与当前状态。 |

## 不在本轮范围

- 未经用户后续分别明确授权的真文本、真生图或真视频请求。
- 将小说 `scripts/write_smoke.sh` 与短剧视频链路拼接；本轮“写作”仅指短剧五站真文本。
- episode 2 视频、第 3 集以上季级编排、批量生图/视频、视频付费请求自动重试。
- 小说 10-20 章 capstone、文风阈值真模型校准与真 ComfyUI 工作流。

## Notes

- 本轮已显式使用 `iter-start` skill；实施收官必须显式使用 `iter-finish`。
- README SOP 表结构开工时不改；收官时同步短剧阶段状态、“最近一次更新”、`docs/AGENT_HANDOFF.md` Phase Status 和 `AGENTS.md` 当前状态。
- 立项提交信息草案：`docs(iter092): 迭代计划 092 立项（短剧真实多模态联测编排与生图重试硬化）`。
- 收官提交信息：`docs(iter092): 收口短剧多模态 smoke 与受控生图重试（验收 + 审查 + SOP/handoff 同步）`。
