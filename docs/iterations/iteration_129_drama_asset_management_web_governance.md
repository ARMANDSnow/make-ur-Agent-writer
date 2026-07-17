# Iteration 129 - 短剧资产管理 Web 总览与治理

## Context

iter127-128 已完成阶段 B 的 exact-version Used-By/停用治理与 ArtDirection Episode > Series > Global 解析冻结，但这些事实尚无统一 Web 入口。用户仍需通过代码或文件判断四类资产的 selected version、跨集引用、retirement 状态和 scoped ArtDirection 来源，也无法从页面执行受控选择、停用/恢复与 override clear。阶段 C-F 的候选与成片已经依赖这些稳定领域协议，因此本轮完成 B3 本地资产管理 Web 闭环，不接真实 provider，不生成媒体。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_asset_usage.py`, `src/drama_art_direction_scope.py`, `src/drama_asset_versions.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_characters_api.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`
- `expected_changes`: `src/drama_asset_web.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_asset_web.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_129_drama_asset_management_web_governance.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不开放任意文件/URL，不返回 prompt/provider response/签名 URL，不接真图片/视频/TTS，不 push

1. 新增脱敏、strict、bounded 的资产 Web projection：统一展示 character、ArtDirection、scene、prop/clue 的 semantic ID、版本、selected/active 状态、scope、used-by、blocker 与 stale impact，不把 catalog 原始自由文本或 provider metadata直接透传。
2. 新增 drama-only 资产管理页面和 API。GET 必须对缺失可选 catalog graceful degrade、对坏源 fail closed；Web 页面使用现有 workspace 导航、可访问状态和响应式组件。
3. 将候选选择、B1 active/disabled mutation、ArtDirection Episode override clear/re-enable 接到现有领域 CAS。每个 mutation 必须携带 expected revision/current identity，服务端重算 usage/impact；禁止客户端提交任意 affected shots 或借另一 season 绕过治理。
4. Mutation 使用现有 same-origin/JSON/CSRF 与 workspace lock 边界，错误投影有界脱敏；lost response 重试只允许领域层已证明的 exact no-op，不新增第二套 Web 状态真源。
5. 审查与唯一 canonical 后，至多一次资产 Web 协议真文本校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: 四类资产投影完整且稳定；selected/used-by/retirement/scope 来源一致；选择、停用/恢复、ArtDirection clear/re-enable 的双 CAS/no-op/stale 影响准确；缺失可选 catalog 不破坏旧 workspace
- `security_boundary`: drama-only、workspace/season/episode/asset/version identity、请求体与容量 strict；CSRF/content-type、路径、symlink/坏源、错误脱敏和公开字段白名单 fail closed
- `extra_risk_view`: Web/资产治理专项，复核客户端不可伪造 impact/revision/scope、lifecycle disabled 与 scope clear 不混淆、API 不泄露 prompt/provider/本地绝对路径或签名 URL

- **A129-01**：四类资产 Web projection strict、bounded、稳定排序，只公开受控 metadata；used-by/blocker/retirement/scope 与领域层事实一致。
- **A129-02**：新增 drama-only 资产页面与 GET API；旧 workspace 缺 catalog 可用，坏源/身份错位 fail closed，导航与响应式基本契约成立。
- **A129-03**：候选选择、active/disabled、ArtDirection clear/re-enable 通过领域双 CAS；服务端重算 impact，stale/no-op/lost-response 语义确定。
- **A129-04**：POST/PUT 边界具 JSON/CSRF、strict identity、nofollow/lock/error redaction；API/HTML 不泄露 prompt、provider response、key、绝对路径或签名 URL。
- **A129-05**：聚焦回归与 correctness/security/Web-governance 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内，图片/视频/TTS 为 0。

## Implementation Notes

- 新增 `src/drama_asset_web.py` 作为严格 allowlist projection。Web 只公开 semantic/version ID、selected、当前 season lifecycle、跨 season `selection_allowed`、exact-version Used-By、scope-specific stale impact、revision 与脱敏 blocker；不序列化 catalog spec、prompt、artifact path 或 provider metadata。
- 资产页固定展示 character、ArtDirection Series/Global/Episode、scene、prop/clue 六个分区。缺失 catalog 显示空状态；invalid/读取竞态不回显原始异常并阻断对应 mutation。列表顺序按 semantic/version ID 显式排序。
- candidate selection、active/disabled 与 scoped clear/re-enable 均先在 `jobs.workspace_reserved` 内重建服务端 overview/CAS，再调用既有领域 writer；客户端不能提交 affected shots。exact current no-op 仍进入领域 CAS，但返回 `changed=false` 与空 impact；旧 revision 返回 409。
- ArtDirection 同时保留 B1 exact-version Used-By 与 scope-specific impact：从经过严格解析的 persisted RenderPlan resolution 过滤 Series/Global/Episode，避免相同 content-addressed version 在不同 scope 之间串引用。Global impact/可选择性扫描全部已知 plan season 与 canonical retirement ledger，引用显式携带 season/episode。
- 新增 `X-Drama-Asset-Intent: mutate-v1`、JSON、Origin/Host 与 Fetch Metadata 校验。32 KiB cap 同时存在于 route 和 HTTP transport；transport 在 `rfile.read` 前拒绝超限 body。所有 mutation 仍由领域层 nofollow、目标 token、workspace lock 与 precommit CAS 落盘。
- Web 端在 409 后刷新权威 overview；所有 mutation 携带 `view_episode_no`；响应式表格复用 `.table/.table-scroll`。lifecycle disabled 与 scope enabled/clear 使用不同字段和文案。
- 聚焦证据：`py_compile`、Dashboard JS `node --check`、agent harness、`git diff --check` 通过；184 项 Web/B1/B2/asset 聚焦回归通过。
- 审查初轮共确认并修复：transport 读前限流 P2；scope impact 串线 P1；Global 单季投影/治理 P1；409 旧 CAS、响应式表格、episode view、disabled-selected no-op、Global 跨季影响等 P2。修复后已重新派发三视角复审。
- 合理范围变化：为复用安全的 persisted RenderPlan 冻结事实，新增 `inspect_stored_render_plan`；为 Web 与领域共用 Global 治理 season 集，公开既有 nofollow 枚举的只读包装 `list_asset_governance_season_nos`；新增真实 HTTP handler 限流回归 `tests/test_web_server.py`。

## Acceptance Result

- **A129-01 — passed**：`src/drama_asset_web.py` 对 character、ArtDirection（Series/Global/Episode）、scene、prop/clue 使用 strict allowlist 和确定性排序；公开字段限于 semantic/version identity、selected/lifecycle/scope、exact-version Used-By、scope-specific impact、revision 与有界 blocker，不透传 catalog 自由文本、prompt、provider metadata、artifact path 或签名 URL。
- **A129-02 — passed**：新增 drama-only `/w/<name>/assets` 与 `GET /api/workspace/<name>/drama/assets`；缺失可选 catalog 为空状态，坏源、跨 season/episode identity、特殊文件和读取竞态 fail closed。现有 workspace 导航、可访问状态和响应式表格契约均由聚焦测试覆盖。
- **A129-03 — passed**：select、active/disabled、ArtDirection clear/re-enable 均由服务端重建权威 overview 后使用既有 revision/current identity/target-token CAS；客户端不能提交 impact。exact current no-op 返回 `changed=false` 且空 affected refs，旧 revision 返回 409 并由 Web 刷新；Global 影响与可选择性覆盖全部已知 canonical season。
- **A129-04 — passed**：mutation 同时要求 JSON、`X-Drama-Asset-Intent: mutate-v1`、Origin/Host 与 Fetch Metadata；route/HTTP transport 均设 32 KiB cap，后者在 `rfile.read` 前拒绝超限 body。workspace reservation、nofollow、lock、precommit CAS 与有界错误投影保持生效。
- **A129-05 — passed**：最终聚焦回归 205 tests，`py_compile`、Dashboard JS `node --check`、agent harness 与 `git diff --check` 通过。correctness、security/boundary、Web-governance 三个独立只读复审最终均无 findings，主线程复核无未处理 P0/P1/P2。
- Implementation commit `443f56427fda789864c662ff4342d571d595d353` 上唯一 canonical `bash scripts/verify.sh` 通过：2574 tests、15/15 steps、310 秒，run `816d5c73c07141fdbb540efda7fe4020`，tree `55894cecca947b67db77a0367e105d6fdfe366ee`，`tracked_scope_clean=true`，mock preflight 0 WARN/FATAL；验收级别 `mock-functional` / `canonical-mock-offline`，mandatory `local_drama_e2e` 通过，`provider_validated=false`。
- 本轮真文本协议校准 1/1 成功：`gpt-5.5-medium`，HTTP 200，151 tokens，2.758 秒，strict JSON exact keys 与四项约束全部匹配。累计 iter125-129 为 6/60 次文本请求、5 次模型成功，保守预留约 ¥0.50；图片 0/20，视频/TTS 0。本证据只记为局部文本协议校准，不把总验收升级为 provider-validated。
- 未修风险：物理 GC、真实逐镜图片/视频 provider、主观媒体质量、JPEG/WebP、通用 production workbench/归档、真实 TTS 与 episode 2+ 成片仍在后续范围；本轮无已知未处理 P0/P1/P2。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮经验均是既有 B1 exact-version lifecycle、B2 scoped resolution、Web allowlist/CAS 与 transport bounded-body 规则的具体落地，没有形成新的跨模块长期工程规则；产品状态会在常规 docs-only 收官中就地同步。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_asset_web.py` | strict/bounded 资产投影、scope-aware/cross-season impact 与三类治理 mutation |
| `src/drama_asset_usage.py` | 公开既有 nofollow Global governance season 枚举 |
| `src/drama_render_store.py` | 只校验 persisted RenderPlan、不重算当前 source 的 inspection |
| `src/web/routes.py` | drama-only 页面/API、JSON/intent/origin/CAS/error 投影 |
| `src/web/server.py` | 三个资产 mutation 的 read-before-allocation 32 KiB transport cap |
| `src/web/templates.py`、`src/web/static.py` | 资产治理导航、页面、响应式交互与 409 恢复 |
| `tests/test_drama_asset_web.py`、`tests/test_web_server.py` | 四类 projection、scope/season/CAS/no-op/CSRF/transport 回归 |
| `docs/iterations/README.md`、本文件 | iter129 索引、计划、实施与审查证据 |

## 不在本轮范围

- 真实候选生成、图片上传/删除、物理 GC、跨 workspace registry、批量自动选择。
- C-F 媒体候选管理、通用 task DAG、归档导入、真图片/视频/TTS。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；本轮 implementation commit 先于唯一 canonical。
