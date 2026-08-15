# Iteration 168 - 小说续写关键缺陷闭环与真模型单章验证

## Context

iter167 已将 main 收敛为 novel-only，但 2026-08-05 至 2026-08-15 的九份每日体检在拆分前持续复现四个仍适用于小说续写的根因：Web mutation/付费动作未统一守门、LLM raw provider 异常可跨层持久化、多章工作台 freshness 可被较新章节掩盖，以及普通 LLM 日志与 preflight 缺少 no-follow/资源上限。用户要求只在 main 闭环小说关键路径，并以 synthetic 导入续写完成浏览器和一次真 provider 单章验证；短剧 findings 仅汇总到独立 backlog，不修改短剧分支。

## Plan

### Implementation Context
- `must_read`: `src/web/routes.py`, `src/web/server.py`, `src/web/static.py`, `src/llm_client.py`, `src/chapter_status.py`, `src/writer.py`, `src/preflight.py`, `tests/test_web_server.py`, `tests/test_web_iter166_recovery.py`
- `expected_changes`: `src/web/routes.py`, `src/web/server.py`, `src/web/static.py`, `src/llm_client.py`, `src/preflight.py`, `src/safe_jsonl.py`, `tests/test_iter168_novel_health_security.py`, `tests/test_web_server.py`, `docs/audits/short_drama_health_findings_2026-08.md`, `docs/iterations/iteration_168_novel_health_security_provider_validation.md`
- `do_not_touch`: 不读取或修改 `.env`、现有 `workspaces/`、`小说txt/`、私有样本、`data/`、`outputs/` 或 `logs/`；不切换或修改 `codex/short-drama`；不运行图片、视频或 TTS provider；九份日报在 canonical 通过前不得删除。

1. 以单一 mutation policy 覆盖全部 HTTP POST/PUT，统一 framing、Content-Type、same-origin 与 route-specific intent；模型 diagnostics 改为受保护 POST。
2. 工作台按当前 chapter plan 逐章构造 expected context，任何 stale/缺失/损坏章都不能被其它新章掩盖为完成。
3. LLM 终态异常改为 metadata-only typed failure，所有持久 sink 只消费稳定分类；共享 bounded JSONL reader 为 Web 与 preflight 提供 no-follow、有界、字典型读取。
4. 去重保存短剧专属三项 backlog，并注明拆分分支仍需复核 shared fixes；main 验收后删除九份重复日报。
5. 在 `/private/tmp` synthetic workspace 做三视口浏览器走查，并在最终候选 implementation 上只运行一次受限真实续写链：160 次请求、40 元、60 分钟上限；任何发送状态不明均不自动重试。

## Acceptance

### Review Context
- `correctness_behavior`: 核对全部 mutation route 的 intent/HTTP 兼容、导入续写 creation mode 与逐章 strict freshness、任务恢复/预算/timeout 既有语义、diagnostics POST 前端接线和 novel-only 路由均无回归。
- `security_boundary`: 核对 cross-site/body framing 在 handler/provider 前拒绝，raw provider 文本不进入异常链或持久 sink，JSONL reader 拒绝 symlink/非普通文件/竞态/超限/深层输入，且全程不读取凭据、原文和现有运行数据。
- `extra_risk_view`: Web/UX + provider/budget：三视口导入续写关键链、付费确认、轮询/取消/刷新、console 与横向溢出；真实链绑定 synthetic workspace、160 请求/40 元/60 分钟且 submission_unknown 零重提。

- A168-01：所有现有 POST/PUT route 均有明确 mutation policy；实际 HTTP 在读 body/调用 handler 前拒绝坏 framing、错误类型、cross-site/origin 与缺失/错误 intent，multipart 只对白名单开放。
- A168-02：模型 diagnostics 仅允许受保护 POST `{}` + `diagnose-v1`；旧 GET 返回 405，拒绝路径 provider 调用为零；浏览器所有 mutation 使用正确 intent。
- A168-03：工作台逐章使用当前 plan expected context；旧章 stale、plan item 修改/重排/缺失、外审 context mismatch 与坏 plan 均不得进入 `approved/done`。
- A168-04：LLM terminal failure 只暴露稳定 code/type/attempt/trace metadata；signed URL、Authorization、prompt、response body、嵌套秘密和未知自由文本不进入普通日志、state、failure 或 snapshot。
- A168-05：Web 与 preflight 共用 bounded JSONL reader；symlink、FIFO、替换竞态、2 MiB 单行、超过 512 KiB 累计、64 层以上 JSON 或非 dict 均安全降级为空。
- A168-06：iter165–167 creation mode、恢复、runner/request budget/deadline、novel-only 边界与 mock/offline 聚焦回归通过；correctness、security/boundary、Web/UX+provider 三视角无未闭合有效 finding。
- A168-07：Playwright 在 synthetic 临时 workspace 完成 1440×900、1024×768、390×844 关键页面检查，无关键 console error、横向溢出或不可达控件，结论至少 `local-e2e`。
- A168-08：最终候选 implementation 上真实 synthetic 三章导入续写在 160 请求/40 元/60 分钟内完成一章 strict review 则记窄范围 `provider-validated`；配置/定价/网络阻塞则如实记 `safe-blocked`，不重提不明请求。
- A168-09：实现提交后最终唯一 canonical `bash scripts/verify.sh` 通过 schema v3 / novel-only，至少 1849 tests、15 steps，标准结论 `mock-functional`；随后保留短剧 backlog 并删除九份日报。

## Implementation Notes

- Web mutation 现由单一 policy 表覆盖全部 POST/PUT；wire 层在读取 body 前校验 framing、Content-Type、Origin/Fetch-Site、intent 与可选 bearer，diagnostics 固定为 API-only 的受保护 POST。
- `NovelClient`/Aeloon/MCP 同步发送 endpoint-specific intent，cancel 固定发送空 JSON object；前端所有现有 mutation 与付费确认同步新契约。
- 工作台逐章复用 writer/runner current-plan context，并增加 current-start metadata gate；旧起点、旧 plan、缺项、重排、外审 mismatch 或任一 stale 章均不能聚合为 `done`。
- provider failure、repair failure、review/debate/extract 等跨层异常统一为 metadata-only typed terminal；`submission_unknown`、deadline、request/budget/pricing/accounting failure 在同一授权内 fail-fast，遥测失败不会重提当前请求且会阻断后续请求与 settlement。
- Web paid job 冻结 step/params/model config/budget/request/deadline；指纹、context budget 与 preflight 均消费 admission snapshot。每次调用按 prompt UTF-8 bytes + max output tokens 预留最坏费用，阶段预算合计不超过 ¥19、请求合计不超过 100。
- `safe_jsonl.tail_jsonl` 以 dir-fd + no-follow 打开，限制累计/单行/深度/类型，并在读后重新解析完整 pathname/目录链；Web 日志与 preflight 共用且所有异常降级为空。
- 浏览器在 `/private/tmp/iter168-browser.2JZsNv` 的 fresh synthetic 三章 workspace 完成导入、起点、重建、辩论、细纲、单章 strict write/review、任务/取消/刷新、日志与设置只读走查；三视口无横向溢出、不可达控件或关键 console error。Playwright DOM/交互证据正常，但截图命令持续 capture timeout，未生成截图文件，作为工具限制如实保留。
- diagnostics 没有既有浏览器调用，按 API-only 契约验收；未为其新增虚构 UI。

## Acceptance Result

<iter-finish 回填测试数、浏览器/provider 证据、审查结论与 canonical 结果。>

### Knowledge Promotion
- `decision`: `<iter-finish 回填：none|promoted>`
- `destination`: `<iter-finish 回填：none|既有长期权威文档>`
- `reason`: `<iter-finish 回填人工判断>`

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| 待回填 | 待回填 |

## 不在本轮范围

- 不修改或验证 `codex/short-drama`，不修复短剧专属三项 backlog。
- 不读取用户原文、现有 workspace、私有运行日志或 `.env`；不运行图片、视频、TTS 或 10–20 章长跑。
- 不处理与小说关键路径无关的 P3 视觉增强，不 pull/rebase/push 当前分支。

## Notes

- canonical 只能证明 `mock-functional`；真实 synthetic 单章证据不得外推其它 provider、长篇质量或 SLA。
