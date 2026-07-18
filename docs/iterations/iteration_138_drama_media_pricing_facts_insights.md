# Iteration 138 - 短剧媒体 Pricing Facts 与 Insights

## Context

iter133-137 已完成阶段 G 的 task DAG、worker ownership/capacity、静态 capability registry、原子 frozen binding/queue client 与 owner-guarded provider execution loop；剩余 G6 要把媒体成本从含糊的单一数字升级为可审计事实，并安全投影到现有 drama Insights。当前产品合同要求 estimate/authorized/reserved/actual/refunded/unknown 分列、多币种分别汇总，且 unknown 不得当作 0 元。本轮只处理纯本地 strict pricing fact、内容寻址持久 store 与只读聚合，不接真实 provider、不修改 C/D/E paid ledger、不测试 TTS。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_media_tasks.py`, `src/drama_media_executor.py`, `src/web/drama_insights.py`, `tests/test_drama_media_tasks.py`, `tests/test_drama_insights.py`
- `expected_changes`: `src/drama_media_pricing.py`, `src/web/drama_insights.py`, `tests/test_drama_media_pricing.py`, `tests/test_drama_insights.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_138_drama_media_pricing_facts_insights.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真实图片、视频、TTS 或额外文本 provider，不修改 C/D/E paid ledger/schema/receipt，不新增动态 pricing code/config loader、汇率换算、Web mutation 或自动扣费，不 push

1. 新增 strict 媒体 pricing fact 合同：按 task/episode/shot/media/provider/model identity 冻结 currency、estimate、authorized、reserved、actual、refunded、unknown 及 source evidence fingerprint；金额使用有界精确十进制定点表示，拒绝 bool、float、NaN/Inf、负数、超精度、未知字段和伪造 identity。
2. 建立 append-only/content-addressed 本地 pricing ledger 与 guarded transition：estimate/authorization/reservation 可在付费前逐步冻结；actual/refund 只接受权威 paid evidence fingerprint；unknown 是独立事实而非 0，不能用 generic failed/terminal 推导 actual；exact replay 幂等，冲突/倒退/跨 task splice fail closed。
3. 实现多币种安全聚合：每种 currency 分别汇总各事实、净 actual、estimate-vs-actual 差异与 unknown count；不换汇、不把缺失/损坏/unknown 计为 0，不跨币种求和，并对 task/episode/shot/media/provider/model 维度提供有界 allowlist rows。
4. 扩展现有只读 drama Insights，仅扫描 canonical pricing ledger 并返回安全投影；坏 JSON、symlink、目录、超大/过深 payload、identity/tamper/竞态异常显式计入 invalid/degraded，绝不返回 provider account、endpoint、evidence fingerprint、路径、prompt、响应或 raw ledger。
5. 用纯函数、store、replay/tamper、multi-currency、unknown/refund、Insights 缺失/坏源/零泄漏与零 socket 测试闭合 G6；不把本地 pricing fact 冒充 provider billing、发票或汇率结算。

## Acceptance

### Review Context
- `correctness_behavior`: 六类 pricing fact 的合法 transition、精确定点金额、exact replay、actual/refund/unknown 语义、多币种分组、净额/差异、task 与 episode/shot/media/provider/model 维度聚合必须确定；不得改变 G1-G5 task/executor 或旧 Insights/LLM cost 语义
- `security_boundary`: pricing store 必须 nofollow/有界/strict/content-addressed，source evidence 只能以 fingerprint 绑定且不得公开；坏源、跨 task splice、金额溢出/精度攻击、symlink/目录/竞态、provider/account/endpoint/prompt/response/path 泄露均 fail closed
- `extra_risk_view`: pricing/financial + Web/Insights 专项，复核 estimate/authorized/reserved/actual/refunded/unknown 不混淆、多币种不换汇、unknown 不归零、公开 projection 有界脱敏且旧 workspace graceful degrade

- **A138-01**：strict pricing fact/ledger 以精确定点金额和 exact task/provider/media identity 持久化；bool/float/非有限/负数/超精度/超界/额外字段、跨 task 或伪造 fingerprint 均拒绝。
- **A138-02**：estimate→authorized→reserved 与 actual/refunded/unknown 的 guarded append/replay 语义确定；actual/refund 需要权威 evidence fingerprint，unknown 不可被 generic terminal 或缺失值降格为 0，冲突回放 fail closed。
- **A138-03**：聚合按 currency 分列 estimate/authorized/reserved/actual/refunded/net actual/delta/unknown，并提供有界维度 rows；不换汇、不跨币种求和、不让 invalid/unknown 污染金额。
- **A138-04**：drama Insights 对缺失 ledger 零影响，对坏源显式 degraded/invalid，对安全 ledger 返回 allowlist 投影；不泄露 account/endpoint/evidence/fingerprint/path/prompt/response，测试期间零 socket/provider/图片/视频/TTS 调用。
- **A138-05**：聚焦回归与 correctness/security/pricing-financial-Web 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，若执行真文本仅作局部协议校准。

## Implementation Notes

- 金额持久化统一为整数微单位，公开时格式化为固定 6 位十进制字符串；不使用 binary float/Decimal JSON，也不提供汇率换算。`estimate_actual_delta` 是唯一可为负的派生字段，持久 fact 本身永远非负。
- pricing fact 额外固定 `source_evidence_kind` 与 fact kind 的一一映射；fingerprint 只证明 caller 交付的 evidence identity 未漂移，真实 adapter 仍需从 C/D/E 权威 paid ledger 产生该 evidence，generic 层不把任意 hash 宣称为 provider 账单。
- unknown 是无金额历史事实；权威 actual 后可变为已解析，但原 unknown fact 不删除。Insights 同时投影 `actual_known`、unresolved unknown/pending counts 与 `actual_complete`，因此已知小计为 0 不会掩盖未知费用。
- 写侧和 Insights 读侧都按整个 pricing namespace 复核 evidence fingerprint 唯一性；即使攻击者完全重算两个 episode ledger 的 content address，重复 evidence 也会 fail closed，Insights 不返回部分金额。
- correctness 审查发现并修复了付费 outcome 后仍可倒退补 `reserved`、以及 replay 未比较 `recorded_at_ms` 两处边界；pricing/Web 审查发现并修复了读侧跨 episode evidence 重用。security 审查进一步发现 scan 与 commit 间 namespace 替换 TOCTOU，现由同一 nofollow directory fd、`(dev, ino)` canonical identity 和提交前后复核封堵，并有 rename/monkeypatch 定向回归。
- Insights 对工作区最多聚合 4000 facts/1000 tasks，超限、坏源或证据歧义均返回 degraded 空汇总，不混入 partial totals；公开 rows 不含 account、endpoint、binding/evidence fingerprint、路径、prompt 或响应。
- 为使现有 Insights 页面实际可见，实施范围合理增加 `src/web/static.py`、`src/web/templates.py` 与 `tests/test_drama_iter088_web.py`；页面只读、数组有界并逐字段 escape，不新增 mutation。
- 本轮没有从 G2 durable ledger 推导“queue wait”：终态 task 已不保留首次 claim 时间，拿 `updated_at-created_at` 冒充等待时间会误导。完整 task success/queue-wait 指标显式顺延，不影响本轮 G6 pricing facts 验收。

## Acceptance Result

- 聚焦回归：`.venv/bin/python3 -m unittest tests.test_drama_media_pricing tests.test_drama_insights tests.test_drama_iter088_web tests.test_drama_media_tasks tests.test_drama_media_executor tests.test_web_routes_get`，**161 tests OK**；`py_compile`、agent harness 与 `git diff --check` 通过。
- 三视角只读审查：correctness 修复付费 outcome 后倒退补 reservation 与非 exact replay 忽略时间；pricing/financial + Web 修复 fully-rehashed 跨 episode evidence 重用在 Insights 被重复聚合；security 修复 scan/commit namespace 替换 TOCTOU。修复后 correctness、security/boundary、pricing-financial-Web 最终均 **no remaining P0/P1/P2 findings**。
- implementation commit `ba823c850b4477dcca013ca05844a01390cd6bb9` 上唯一标准验收 `bash scripts/verify.sh` exit 0：**2738 tests OK**、15 steps / 375 秒、run `6ceb05d4ac2042ec93253b4377d98949`、tree `2834bf7efac9628247c89e4dc0be70d8fd71cec8`、`tracked_scope_clean=true`；mock preflight **0 FATAL / 0 WARN**。总级别为 `mock-functional` / `canonical-mock-offline`，mandatory local-drama component 为 `local-e2e`，`provider_validated=false`。
- 授权真文本局部协议校准仅执行 1 request：`gpt-5.5-medium`，HTTP 200，422 tokens / 5.28 秒，exact JSON shape 与 `exact_fixed_point_pricing`、`unknown_not_zero`、`multi_currency_no_conversion`、`paid_evidence_bound_insights` 四项均通过。iter125-138 累计保守计 17/60 请求、14 次 HTTP/model response、12 次协议检查通过、预留约 ¥1.40；图片 0/20，视频/TTS 0。本次不持久化 key、prompt 或响应正文，不提升 provider 结论。
- **A138-01：通过。** 六类 fact 与 episode/task/provider/media identity 严格、内容寻址；金额只接受有界 canonical 十进制字符串并持久化精确微单位，所有 ambiguous numeric 与重算 identity splice 均拒绝。
- **A138-02：通过。** transition、CAS 与 exact replay 确定；unknown 无金额且后续 actual 只解析、不删除历史，refund 不超过 actual，付费 outcome 后不能倒退 reservation。
- **A138-03：通过。** 每币种分别汇总 known actual/refund/net/delta/unknown/pending，不换汇、不跨币种求和；工作区 facts/tasks 超限、evidence 歧义或坏源均 degraded 空汇总。
- **A138-04：通过。** Insights 缺失 graceful、坏源显式 degraded，公开字段 allowlist 且 UI escape/16 币种截断有提示；未泄漏 account/endpoint/evidence/binding/path/prompt/response，聚焦测试零 socket/provider/媒体/TTS。
- **A138-05：通过。** 聚焦、三视角修复复核、唯一 canonical 与局部真文本校准均完成，无未处理 P0/P1/P2。
- 未修风险：本地 pricing facts 不是 provider billing、发票或汇率结算；真实 adapter 仍需从 C/D/E 权威 paid ledger 产生 evidence，完整 task success/queue-wait 指标与真实媒体费用/质量仍待后续轮次。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: 六类事实、精确定点金额、unknown/多币种语义、工作区 evidence 唯一性和 Insights fail-closed 边界是阶段 G 的长期产品合同，已就地写入 G6 权威章节。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_media_pricing.py` | 新增 strict pricing fact/append-only ledger、CAS store、多币种聚合与安全 workspace 投影。 |
| `src/web/drama_insights.py` | 将安全媒体 pricing 投影接入既有只读 Insights API。 |
| `src/web/{static.py,templates.py}` | 展示分币种估算/已知实际、unknown/degraded 状态。 |
| `tests/test_drama_media_pricing.py` | 覆盖金额、transition、replay/CAS、unknown/refund、多币种、tamper、特殊文件、零泄漏与零网络。 |
| `tests/{test_drama_insights.py,test_drama_iter088_web.py}` | 固化缺失降级、API 与页面静态合同。 |
| `docs/product/short_drama_module.md` | 登记 G6 权威 pricing/Insights 语义和未验证边界。 |
| `docs/iterations/{README.md,iteration_138_*.md}` | 登记 iter138 计划、实施、审查与验收记录。 |

## 不在本轮范围

- 真实 provider billing adapter、发票/结算/汇率换算、动态价格配置或自动扣费。
- C/D/E paid ledger 迁移、Web mutation、真实媒体/TTS、主观质量与 provider SLA。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
