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
5. 在 `/private/tmp` synthetic workspace 做三视口浏览器走查，并在最终候选 implementation 上运行受限真实续写链：初始 160 次请求/40 元/60 分钟；用户在定价守门暴露后明确将本轮总额授权提高到 100 元，但任何发送状态不明仍不自动重试。

## Acceptance

### Review Context
- `correctness_behavior`: 核对全部 mutation route 的 intent/HTTP 兼容、导入续写 creation mode 与逐章 strict freshness、任务恢复/预算/timeout 既有语义、diagnostics POST 前端接线和 novel-only 路由均无回归。
- `security_boundary`: 核对 cross-site/body framing 在 handler/provider 前拒绝，raw provider 文本不进入异常链或持久 sink，JSONL reader 拒绝 symlink/非普通文件/竞态/超限/深层输入，且全程不读取凭据、原文和现有运行数据。
- `extra_risk_view`: Web/UX + provider/budget：三视口导入续写关键链、付费确认、轮询/取消/刷新、console 与横向溢出；真实链绑定 synthetic workspace、160 请求/60 分钟与当次明确授权额，且 submission_unknown 零重提。

- A168-01：所有现有 POST/PUT route 均有明确 mutation policy；实际 HTTP 在读 body/调用 handler 前拒绝坏 framing、错误类型、cross-site/origin 与缺失/错误 intent，multipart 只对白名单开放。
- A168-02：模型 diagnostics 仅允许受保护 POST `{}` + `diagnose-v1`；旧 GET 返回 405，拒绝路径 provider 调用为零；浏览器所有 mutation 使用正确 intent。
- A168-03：工作台逐章使用当前 plan expected context；旧章 stale、plan item 修改/重排/缺失、外审 context mismatch 与坏 plan 均不得进入 `approved/done`。
- A168-04：LLM terminal failure 只暴露稳定 code/type/attempt/trace metadata；signed URL、Authorization、prompt、response body、嵌套秘密和未知自由文本不进入普通日志、state、failure 或 snapshot。
- A168-05：Web 与 preflight 共用 bounded JSONL reader；symlink、FIFO、替换竞态、2 MiB 单行、超过 512 KiB 累计、64 层以上 JSON 或非 dict 均安全降级为空。
- A168-06：iter165–167 creation mode、恢复、runner/request budget/deadline、novel-only 边界与 mock/offline 聚焦回归通过；correctness、security/boundary、Web/UX+provider 三视角无未闭合有效 finding。
- A168-07：Playwright 在 synthetic 临时 workspace 完成 1440×900、1024×768、390×844 关键页面检查，无关键 console error、横向溢出或不可达控件，结论至少 `local-e2e`。
- A168-08：最终候选 implementation 上真实 synthetic 三章导入续写在 160 请求/60 分钟与当次明确授权总额内完成一章 strict review 则记窄范围 `provider-validated`；配置/定价/网络阻塞或 `submission_unknown` 则如实记 `safe-blocked`，不重提不明请求。
- A168-09：实现提交后最终唯一 canonical `bash scripts/verify.sh` 通过 schema v3 / novel-only，至少 1849 tests、15 steps，标准结论 `mock-functional`；随后保留短剧 backlog 并删除九份日报。

## Implementation Notes

- Web mutation 现由单一 policy 表覆盖全部 POST/PUT；wire 层在读取 body 前校验 framing、Content-Type、Origin/Fetch-Site、intent 与可选 bearer，diagnostics 固定为 API-only 的受保护 POST。
- `NovelClient`/Aeloon/MCP 同步发送 endpoint-specific intent，cancel 固定发送空 JSON object；前端所有现有 mutation 与付费确认同步新契约。
- 工作台逐章复用 writer/runner current-plan context，并增加 current-start metadata gate；旧起点、旧 plan、缺项、重排、外审 mismatch 或任一 stale 章均不能聚合为 `done`。
- provider failure、repair failure、review/debate/extract 等跨层异常统一为 metadata-only typed terminal；`submission_unknown`、deadline、request/budget/pricing/accounting failure 在同一授权内 fail-fast，遥测失败不会重提当前请求且会阻断后续请求与 settlement。
- Web paid job 冻结 step/params/model config/budget/request/deadline；指纹、context budget 与 preflight 均消费 admission snapshot。每次调用按 prompt UTF-8 bytes + max output tokens 预留最坏费用；默认仍保守，显式授权时四阶段 server maxima 合计 ¥95、请求 maxima 合计 100，本轮已发生费用与后续 maxima 之和仍低于用户授权的 ¥100。
- `safe_jsonl.tail_jsonl` 以 dir-fd + no-follow 打开，限制累计/单行/深度/类型，并在读后重新解析完整 pathname/目录链；Web 日志与 preflight 共用且所有异常降级为空。
- 浏览器在 `/private/tmp/iter168-browser.2JZsNv` 的 fresh synthetic 三章 workspace 完成导入、起点、重建、辩论、细纲、单章 strict write/review、任务/取消/刷新、日志与设置只读走查；三视口无横向溢出、不可达控件或关键 console error。Playwright DOM/交互证据正常，但截图命令持续 capture timeout，未生成截图文件，作为工具限制如实保留。
- diagnostics 没有既有浏览器调用，按 API-only 契约验收；未为其新增虚构 UI。

## Acceptance Result

- **实现闭环**：`b434117` 完成 mutation policy、逐章 freshness、metadata-only LLM failure、bounded JSONL 和 frozen paid scope；真链又暴露 GPT-5.5 家族定价与明确授权额高于默认值时的 admission 缺口，分别在 `fc266b2` / `987c0c4` 闭环；`df3bc8a` 只修正 canonical 暴露的旧测试“默认值=硬上限”断言。
- **聚焦回归**：安全、freshness、Web/job、NovelClient、reviewer、provider terminal/budget 等正确聚焦集均通过；收官后追加的定价与预算变更又通过 94、128 和 65 项针对性回归。
- **三视角审查**：correctness、security/boundary、Web/UX+provider 均为独立只读审查；其中 NovelClient intent、typed terminal fail-fast、hostile exception shape、telemetry/accounting degrade、safe JSONL TOCTOU/行长、当前起点 freshness、费用预留、retry caps 等有效 findings 全部修复，最终复核无仍成立 P0–P2。
- **浏览器**：`/private/tmp/iter168-browser.2JZsNv` 的全新 synthetic 三章导入书完成起点、重建、辩论、细纲、单章 strict write/review、任务/取消/刷新、日志与设置走查；1440×900、1024×768、390×844 无横向溢出、不可达控件或关键 console error，结论 `local-e2e`。截图命令持续 capture timeout，未伪造图片证据。
- **真 provider**：仅使用 `/private/tmp/iter168-provider.1brmuX` synthetic workspace。定价修复后 3 次 extract、compress 和 persona 调用均获得确认响应；entity graph 请求在 125.5 秒后进入 `submission_unknown`，typed failure 与 job 共用 trace，当场终止且零重提。安全日志 7 行、本地估算 ¥4.7503，未超过用户后续明确授权的 ¥100；未到达 debate/plan/write，结论 `safe-blocked`，不记 `provider-validated`。
- **canonical**：最终 implementation `df3bc8a2f8b26ab4901837164570285551a1c8b5` 上 `bash scripts/verify.sh` 通过；schema v3 / `canonical-novel-mock-offline`，1889 tests / 15 steps / 84 秒，run `880f05b99e4e4f61bb6c2f31bf206c64`，`tracked_scope_clean=true`，标准等级 `mock-functional`。前一次完整门禁的 4 个失败均为 iter166 旧预算断言，聚焦修正后完整重验通过。
- **报告收束**：短剧专属三项及 shared-fix 移植提醒已保存到 `docs/audits/short_drama_health_findings_2026-08.md`；canonical 通过后删除 2026-08-05/06/09/10/11/12/13/14/15 九份重复未跟踪日报。
- A168-01 PASS：policy 完整性与实际 HTTP pre-body 拒绝矩阵通过，拒绝路径 handler/provider 调用为零。
- A168-02 PASS：diagnostics 仅允许 protected POST `{}` + `diagnose-v1`，旧 GET 为 405，所有已有浏览器 mutation intent 已更新。
- A168-03 PASS：当前起点/plan 逐章 expected context 和 external review 一致性均有 stale/corrupt/reorder/missing 反例回归。
- A168-04 PASS：provider/repair/reviewer/debate/extract 异常只保留 typed metadata，hostile shape 与嵌套秘密投影均零泄漏。
- A168-05 PASS：Web/preflight 共享 reader 对 symlink、FIFO、TOCTOU、原始超长行、累计上限、深度与非 dict 均空降级。
- A168-06 PASS：iter165–167、NovelClient/Aeloon、恢复、冻结预算/超时和 novel-only 聚焦回归通过；三路审查无未闭合 P0–P2。
- A168-07 PASS：三视口 synthetic 关键链为 `local-e2e`；截图 capture timeout 作为工具限制明示，不影响 DOM/交互/溢出/console 结论。
- A168-08 SAFE-BLOCKED：真链在 entity graph 产生 `submission_unknown`，当场零重提；未完成 strict 单章，不宣称 `provider-validated`。
- A168-09 PASS：final canonical 1889 tests / 15 steps / schema v3 novel-only 通过，等级 `mock-functional`；短剧 backlog 保留，九份重复日报在此后删除。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: mutation policy 完整性、total exception projection、遥测失败后计费 fail-closed、逐章 freshness 与 `submission_unknown` 零重提是会直接影响后续实现/验收决策的长期边界。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/{server,routes,jobs,static,templates,safe_log}.py` | mutation/intent/framing/origin 守门、冻结付费 scope、工作台 freshness、恢复与预算 UX |
| `src/{llm_client,safe_errors,safe_jsonl,preflight,cost_estimator}.py` | typed metadata-only failure、total 安全投影、有界 no-follow 日志、定价/计费 fail-closed |
| `src/{extractor,compressor,debater,reviewer,writer,writer_style,premise_expansion,book_runner,auto_pipeline}.py` | terminal fail-fast、当前 plan/run context、冻结 model/preflight 与安全 sink |
| `integrations/novel_client/client.py` | Aeloon/MCP/NovelClient 的 endpoint-specific intent 与空 JSON cancel |
| `tests/test_*.py` | mutation、freshness、exception/log、budget/provider、NovelClient 与 iter165–167 回归 |
| `docs/audits/short_drama_health_findings_2026-08.md` | 冻结短剧分支的三项待办和 shared fixes 移植提醒 |

## 不在本轮范围

- 不修改或验证 `codex/short-drama`，不修复短剧专属三项 backlog。
- 不读取用户原文、现有 workspace、私有运行日志或 `.env`；不运行图片、视频、TTS 或 10–20 章长跑。
- 不处理与小说关键路径无关的 P3 视觉增强，不 pull/rebase/push 当前分支。

## Notes

- canonical 只能证明 `mock-functional`；真实 synthetic 单章证据不得外推其它 provider、长篇质量或 SLA。
