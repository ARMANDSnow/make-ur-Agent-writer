# Agent Handoff

> 当前状态单一真源。阶段历史见 [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md)，逐轮证据见 [`iterations/`](iterations/README.md)。

## Current Snapshot

| 项目 | 当前事实 |
|---|---|
| 更新时间 | iter 169 / 2026-09-05（完整验收基线；活动进展见 Active iteration） |
| Accepted implementation commit | `df9627b565f511e43f229471fc5ec0d804ea5ebc` |
| 日期 / accepted iteration | 2026-09-05 / iter169 |
| Active iteration | iter170；实现 `31f19902a78ab863f06976f3900ce9e5482390d4`（主体 `5fae2e3`），canonical 1965 tests / 15 steps / 101秒 passed、mock-functional；run `27c553af886345b9a08399313c4834cf` |
| 产品主线 | `main` 只支持小说原创与导入续写；完整小说+短剧快照在 `codex/short-drama` |
| implementation | `df9627b`（主体 `a7d67d5`，润色 lint 测试兼容 `df9627b`） |
| 标准验收 | schema v3、`canonical-novel-mock-offline`、`mock-functional`、passed；1911 tests / 15 steps / 85 秒；run `1af2f656d61848b9ac7ca98ad8c3eb24`；tracked scope clean |
| workspace 类型 | 可识别：`novel`、legacy `drama`；main 可创建/枚举/运行：仅 `novel` |
| 短剧 UI | 首页与作品列表保留原生 disabled 卡片按钮；无 href、handler 或跳转目标 |
| 短剧数据 | main 隐藏并 fail-closed；不读取业务内容，不迁移、不修改、不删除 |
| 发布状态 | 本轮仅本地分支和提交；未 push、未建 PR |
| 本轮范围 | iter170已修F01–F11及F13–F20；包含有界流式、工作台状态、细纲覆盖与投票检查点，1965项canonical通过。多章请求上限和长辩论上下文已修复。新key/luna10章提取和Web准备成功，大纲恢复中；用户暂不考虑预算继续测试，整体仍未完成 |

## Capability Map

| 领域 | 已有能力 | 当前边界 |
|---|---|---|
| 小说数据链 | normalize、split、extract、compress、五类 proposal、起点安全知识视图 | 原文和衍生运行数据保持 gitignored；不修改 `小说txt/` |
| 小说创作 | debate、chapter plan、writer、5+1 review、lint/rewrite、rolling/advance | 标准验收为 mock；长篇真 provider 质量与 SLA 未证明 |
| 创作模式 | `workspace.json` schema v2 权威 `creation_mode`；原创/续写同源投影 | legacy 只读推断；损坏/未知 metadata fail closed |
| 失败恢复 | 动态步骤安全中文、strict-approved 完成态、exact `retry_exhausted` 受控恢复、当前稿审核后的 lint 失败归档与记忆恢复 | lost/unknown/submission-unknown 和一般失败不自动重提 |
| 长跑 | write-book、drive-book、supervisor、heartbeat/watchdog、预算、写锁、按全书进度补计划、逐章伏笔门禁 | 真实 10–20 章 capstone 仍需逐次授权 |
| Web | 四阶段工作台、编辑、任务恢复、搜索、版本与创作数据；响应式 Phase A-E、保存版本快照、单步取消 | 本地个人研究工具，不是公网多租户产品 |
| 安全边界 | mutation policy/intent、typed metadata-only provider failure、bounded no-follow JSONL、逐章 strict freshness、冻结计费 scope | 遥测/定价不可用时 fail closed；`submission_unknown` 无自动出边 |
| 短剧 | main 无运行能力；完整代码、协议和历史状态在 `codex/short-drama` | main 只识别 legacy 类型以隔离，所有历史入口不可达 |

## Latest Accepted Evidence

- iter170 活动迭代的工程证据：`31f1990` canonical 1965 tests / 15 steps / 101秒 passed、`mock-functional`；真实浏览器慢GET和双标签冲突通过（`local-e2e`），三路只读审查及增量复审无剩余高置信P0–P2。
- iter170 真实边界：2026-09-06新key/luna最小生成HTTP200/15token，原文提取与取消后缓存续接成功；单价按用户USD0.01/百万输入输出token暂算。服务对max_tokens和max_completion_tokens均忽略16token上限（实际203/214），用户随后明确暂不考虑预算继续测试，临时服务已恢复；10章提取完成，Web有界流式准备243秒成功，真实取消停止后续请求；大纲已保存28次发言并在恢复。旧provider的RateLimitError/BadGatewayError保留历史证据；正文与完整链未通过，accepted仍为169。

- iter169 修复编辑保存竞态、旧故事记忆复用、单步取消、用户代理丢失、大纲人工编辑、旧 lint 失败状态和分段规划；伏笔提供当前正文证据确认及 TTL CLI，逐章检查不依赖批次大小。
- correctness、security/boundary、Web/UX 三路独立只读审查及增量复审完成；有效 findings 已修复，审查范围内无剩余 P0–P2。原有范围外 P2 保留为 backlog。
- 合成回归覆盖两段五章、恢复跳章、缺失计划补齐、正文编辑后的记忆/实体失效、过期回收证据、代理默认保留和 normalize → Web split；真实 JavaScript 行为测试覆盖输入/DOM 快照与 GET 乱序。本轮未运行浏览器端到端或真实模型。
- implementation `df9627b565f511e43f229471fc5ec0d804ea5ebc` 上 canonical schema v3 / `canonical-novel-mock-offline` 以 1911 tests / 15 steps / 85 秒 通过；run `1af2f656d61848b9ac7ca98ad8c3eb24`，`tracked_scope_clean=true`，等级 `mock-functional`。首次全量暴露旧风格测试缺少润色 lint 模拟结果，修正后 35 项聚焦及独立复审通过，再完整重验。
- 历史 iter168 的 entity graph `submission_unknown` 仍保持 `safe-blocked`，本轮没有发出真实请求或取得新的 provider 验证证据。

## Retained Working Memory

### 1. 权威状态与小说模式

- workspace 选择必须先验证名称、根目录 identity、metadata 状态与 supported type；显式坏/未知/legacy drama 一律 fail closed。
- 小说来源由 `workspace.json` 的 `creation_mode` 决定。原创没有起点是正常状态；导入续写没有起点仍是续写，不得反推模式。
- overview、workbench、readiness、runner 和任务创建必须消费同一服务端投影，不能各自猜测阶段。

### 2. 安全与隐私

- 不主动读取 `.env`、`小说txt/`、私有 workspace、`data/`、`outputs/` 或 `logs/`。公开错误和 job 投影不含完整 prompt、签名 URL、凭据或 provider raw。
- 程序默认保留用户代理；只有显式 `DRAGON_RAJA_PROXY_MODE=sandbox-63501` 才适配本地隧道，失败仍保留原代理。
- mock 必须在 LiteLLM 首次导入前固定本地 cost map 并跳过代理探测；unittest discovery 触发真实调用是严重回归。
- 所有真实模型入口逐次授权。标准 `verify.sh` 只能证明 `mock-functional`。
- 真实模型必须有明确本地定价才能在请求前预留最坏费用；日志/计费 sink 降级后阻断下一次付费请求和 settlement。

### 3. 写作、评审与恢复

- Prompt 约束不能替代本地 schema、normalization 和 fail-closed fallback。空 ballot、缺字段、近似 JSON、布尔冒充整数、NaN/Infinity 和截断都必须在本地边界处理。
- 手改正文先失效当前章及后续章记忆；按章重新审核后用当前正文摘录恢复记忆，旧实体推进保留为失效历史。审核通过但记忆更新失败仍不可完成。
- 滚动规划按全书进度补齐下一窗口并保留远期计划；伏笔人工确认绑定当前正文/计划/审核，证据过期即恢复门禁。
- 写作完成态要求 durable 草稿与 strict-approved review 一致。Reject、halt、重试耗尽或未知状态必须保留为可处理状态。
- 付费失败恢复必须绑定同章 durable terminal、上游 freshness、状态指纹、claim 和当前 job ownership；不能把普通 force 当成恢复。

### 4. Web 与并发边界

- 保存只确认实际提交的字段值及 DOM 身份；保存过程中新增输入仍 dirty，异步详情刷新必须拒绝过期成功与失败。
- dirty 与 active job 是有序但不同的导航守门：同 workspace 先解决未保存内容，离开/切书才处理 active job。
- hydration、任务或 metadata 未知时 mutation 保持禁用；lost/404/坏状态停止轮询且零重提。
- 文件身份检查必须覆盖实际 mutation 窗口。回收站 destructive 操作使用锁、nofollow parent fd、inode 二次匹配和 dir-fd 操作，避免检查后对象被替换。
- 日志和 preflight 只能通过共享 bounded reader 读取：dir-fd/no-follow、regular-file、读前后 pathname identity、单行/累计/深度上限任一失败都降级为空。

### 5. novel-only 分支边界

- `drama` 是“可识别但不支持”的只读隔离标记，不是 main 的可创建类型。
- Web/CLI 小说列表、direct route、logs、run-step、import-current、active trash、trash restore/purge 都必须拒绝 legacy drama；公开响应不泄露隐藏条目是否存在。
- 静态边界检查允许禁用入口文案、legacy sentinel、迁移说明和历史审计，除此之外 main 的执行代码、配置、脚本与当前测试不能引用短剧实现。
- 需要访问旧短剧数据或继续短剧开发时切换 `codex/short-drama`；不得在 main 增加迁移、清理或兼容写入捷径。

### 6. 迭代与验收

- 每轮用 `iter-start` 建档；聚焦检查后至少 correctness 与 security/boundary 两个只读审查视角，修复并聚焦回归，再运行 canonical。
- implementation commit 上运行 `bash scripts/verify.sh`；通过后只允许 docs-only 收官提交。若完整验收暴露真实回归，按失败范围修复并完整重验。
- Acceptance Result 必须记录 implementation、测试数、profile、级别、审查范围、findings 处置和未修风险，不把 mock 或本地浏览器证据外推为 provider 验证。

## Operating Boundaries

- main 不提供短剧 CLI、页面、API、媒体回调、job step、归档或 workspace 创建。
- 历史 iteration 与 PROJECT_HISTORY 保留为审计记录，不代表 main 当前可运行能力。
- 不 push、不建 PR，除非用户另行明确要求。
- 短剧专属 backlog 只在 main 记录；实际复核/移植必须切到 `codex/short-drama`。

## Open Gaps

1. 小说真实 provider 续写链在 entity graph 留有 `submission_unknown`；无权威 provider inspect/reconciliation 时不得重提原请求。完整单章与 10–20 章长跑仍未验证。
2. Web 仍是本机个人研究工具，未做公网身份认证、多租户隔离或服务级 SLA。
3. Aeloon 集成状态继续由 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) 单独维护。
4. iter170工程通过，真实新key/luna可生成，但provider忽略输出token上限，严格费用边界未验证。概览任务状态已修，另有分块进度和rolling坏条目/较早缺口的待办，不能宣称所有UX/长跑问题消失。
5. 短剧后续能力、真实媒体校准和历史数据访问只在 `codex/short-drama` 继续，不属于 main backlog。

## Next Candidates

1. 先寻找不产生新提交的 provider inspect/reconciliation 证据处理 iter168 entity graph unknown；若上游不提供查询，保持 `safe-blocked`，只能在用户再次明确授权后开全新 synthetic 链。
2. 用户已明确暂不考虑预算，继续iter170的准备→规划→正文/长跑；旧key不落盘，所有费用保留用户单价估算与未知预留的区别。
3. 定期运行静态 novel-only 边界检查，避免 generic media/production 命名的短剧残留重新进入 main。

## Recovery Commands

```bash
git status --short --branch
.venv/bin/python3 scripts/check_agent_harness.py
.venv/bin/python3 scripts/check_novel_only_boundary.py
bash scripts/verify.sh
```

`verify.sh` 不接受 `--book`，不继承 ambient workspace，固定在系统临时目录创建 synthetic novel workspace。

## Documentation Map

| 问题 | 权威位置 |
|---|---|
| 当前状态、缺口、下一步 | 本文 |
| 小说 9 阶段 SOP | 根 [`README.md`](../README.md#流水线-sop实时状态) |
| 阶段历史与长期教训 | [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) |
| 逐轮证据 | [`iterations/README.md`](iterations/README.md) |
| 用户上手 | [`product/GETTING_STARTED.md`](product/GETTING_STARTED.md) |
| 短剧分支迁移 | [`product/short_drama_module.md`](product/short_drama_module.md) |

## Maintenance Contract

- 收官时更新 `Current Snapshot`、`Latest Accepted Evidence`、`Open Gaps`、`Next Candidates` 和 `Latest Transition`。
- 当前事实以代码和测试为准，进度以本文为准，SOP 以 README 为准，历史原因以 iteration/PROJECT_HISTORY 为准。
- 不在本文复制逐轮完整验收日志；只保留会影响下一次接力判断的证据和边界。

## Latest Transition

iter170仍未完整完成：F01–F11及F13/F14已实现，两路增量审查通过，implementation `31f1990` canonical 1965 tests / 15 steps / 101秒 passed。真实10章提取完成；压缩遇125秒超时，正从缓存恢复。用户已明确暂不考虑预算继续测试，F12保留为上游限制而非暂停条件。分块反馈与rolling较早缺口另列待办；accepted iteration保持169，未push。
