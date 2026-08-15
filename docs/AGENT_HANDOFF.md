# Agent Handoff

> 当前状态单一真源。阶段历史见 [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md)，逐轮证据见 [`iterations/`](iterations/README.md)。

## Current Snapshot

| 项目 | 当前事实 |
|---|---|
| 更新时间 | iter 167 / 2026-08-15 |
| Accepted implementation commit | `bd1be596deca742c2bb0d78fea965b5604e067df` |
| 日期 / accepted iteration | 2026-08-15 / iter167 |
| 产品主线 | `main` 只支持小说原创与导入续写；完整小说+短剧快照在 `codex/short-drama` |
| implementation | `bd1be59`（主体拆分 `4ab110b`，契约修复 `a1ffb71`） |
| 标准验收 | schema v3、`canonical-novel-mock-offline`、`mock-functional`、passed；1849 tests / 15 steps / 78 秒；run `22a861a2561b4de8b2cd25aeddd7810f`；tracked scope clean |
| workspace 类型 | 可识别：`novel`、legacy `drama`；main 可创建/枚举/运行：仅 `novel` |
| 短剧 UI | 首页与作品列表保留原生 disabled 卡片按钮；无 href、handler 或跳转目标 |
| 短剧数据 | main 隐藏并 fail-closed；不读取业务内容，不迁移、不修改、不删除 |
| 发布状态 | 本轮仅本地分支和提交；未 push、未建 PR |
| 本地未跟踪项 | 9 份体检报告保持原样，未读取、移动、提交或删除 |

## Capability Map

| 领域 | 已有能力 | 当前边界 |
|---|---|---|
| 小说数据链 | normalize、split、extract、compress、五类 proposal、起点安全知识视图 | 原文和衍生运行数据保持 gitignored；不修改 `小说txt/` |
| 小说创作 | debate、chapter plan、writer、5+1 review、lint/rewrite、rolling/advance | 标准验收为 mock；长篇真 provider 质量与 SLA 未证明 |
| 创作模式 | `workspace.json` schema v2 权威 `creation_mode`；原创/续写同源投影 | legacy 只读推断；损坏/未知 metadata fail closed |
| 失败恢复 | 动态步骤安全中文、strict-approved 完成态、exact `retry_exhausted` 受控恢复 | lost/unknown/submission-unknown 和一般失败不自动重提 |
| 长跑 | write-book、drive-book、supervisor、heartbeat/watchdog、预算、写锁 | 真实 10–20 章 capstone 仍需逐次授权 |
| Web | 四阶段工作台、编辑、任务恢复、搜索、版本与创作数据；响应式 Phase A-E | 本地个人研究工具，不是公网多租户产品 |
| 短剧 | main 无运行能力；完整代码、协议和历史状态在 `codex/short-drama` | main 只识别 legacy 类型以隔离，所有历史入口不可达 |

## Latest Accepted Evidence

- iter167 从完整基线 `35c97ccedeaca1725cc1a491cebf393f6a91303a` 固定 `codex/short-drama`，在 `codex/novel-only-split` 物理移除短剧领域、媒体、CLI、Web/API/job、prompt、fixture、脚本与当前测试。
- canonical 验收升级为 schema v3 / `canonical-novel-mock-offline`，不再读取或要求 `local_drama_e2e`。implementation `bd1be59` 上 1849 tests、15 steps、78 秒全部通过；mock pipeline、manifest、report snapshot 和 preflight 均通过。
- correctness、security/boundary、Web/runner/harness 三个独立只读视角完成审查。发现的向导 DOM、logs guard、CLI import、trash 隔离/TOCTOU、孤儿媒体路由/静态资源和 acceptance 契约问题均修复；最终复核无剩余 finding。
- 早期标准验收在 1847 项中暴露 2 个旧测试契约（CSS 精确空格、invalid metadata 从 409 改为 404）；聚焦修复后通过。最终 implementation 首次受限验收的 12 个 error 均为沙箱拒绝 `127.0.0.1` bind；同一提交在允许 loopback 的环境中 1849 项全过。没有调用真实文本、图片、视频或 TTS provider。
- iter166 已完成小说原创/续写双链失败恢复：安全动态步骤、strict-approved 完成态和 exact `retry_exhausted` 恢复；该小说行为在 iter167 聚焦回归中保持。

## Retained Working Memory

### 1. 权威状态与小说模式

- workspace 选择必须先验证名称、根目录 identity、metadata 状态与 supported type；显式坏/未知/legacy drama 一律 fail closed。
- 小说来源由 `workspace.json` 的 `creation_mode` 决定。原创没有起点是正常状态；导入续写没有起点仍是续写，不得反推模式。
- overview、workbench、readiness、runner 和任务创建必须消费同一服务端投影，不能各自猜测阶段。

### 2. 安全与隐私

- 不主动读取 `.env`、`小说txt/`、私有 workspace、`data/`、`outputs/` 或 `logs/`。公开错误和 job 投影不含完整 prompt、签名 URL、凭据或 provider raw。
- mock 必须在 LiteLLM 首次导入前固定本地 cost map 并跳过代理探测；unittest discovery 触发真实调用是严重回归。
- 所有真实模型入口逐次授权。标准 `verify.sh` 只能证明 `mock-functional`。

### 3. 写作、评审与恢复

- Prompt 约束不能替代本地 schema、normalization 和 fail-closed fallback。空 ballot、缺字段、近似 JSON、布尔冒充整数、NaN/Infinity 和截断都必须在本地边界处理。
- 写作完成态要求 durable 草稿与 strict-approved review 一致。Reject、halt、重试耗尽或未知状态必须保留为可处理状态。
- 付费失败恢复必须绑定同章 durable terminal、上游 freshness、状态指纹、claim 和当前 job ownership；不能把普通 force 当成恢复。

### 4. Web 与并发边界

- dirty 与 active job 是有序但不同的导航守门：同 workspace 先解决未保存内容，离开/切书才处理 active job。
- hydration、任务或 metadata 未知时 mutation 保持禁用；lost/404/坏状态停止轮询且零重提。
- 文件身份检查必须覆盖实际 mutation 窗口。回收站 destructive 操作使用锁、nofollow parent fd、inode 二次匹配和 dir-fd 操作，避免检查后对象被替换。

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
- 不读取或提交 9 份未跟踪体检报告。

## Open Gaps

1. 小说真实 provider 的完整续写链和 10–20 章长跑质量仍需用户逐次授权；当前 canonical 不能外推。
2. Web 仍是本机个人研究工具，未做公网身份认证、多租户隔离或服务级 SLA。
3. Aeloon 集成状态继续由 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) 单独维护。
4. 短剧后续能力、真实媒体校准和历史数据访问只在 `codex/short-drama` 继续，不属于 main backlog。

## Next Candidates

1. 在明确授权后，对一份 synthetic/用户指定小说做 continuation 真 provider 最小链验证，再决定是否扩大到长篇 capstone。
2. 继续收敛小说 Web 的可访问性、恢复说明和端到端浏览器回归，不改变 novel-only 类型边界。
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

iter167 完成短剧模块安全分支拆分：完整基线 `35c97cc` 固定在 `codex/short-drama`，main 的 accepted implementation 为 `bd1be59`，只支持小说原创与导入续写。短剧运行代码、媒体链、CLI、Web/API/job、prompt、fixture、脚本和当前测试均从 main 物理移除；首页与作品列表只保留无跳转的 disabled 入口。legacy `type=drama` 仅作隔离哨兵，Web/CLI/list/direct/logs/import/trash 全部 fail closed 且 destructive 操作防替换。三个只读审查视角最终无 finding；canonical schema v3 / `canonical-novel-mock-offline` 在 1849 tests、15 steps、78 秒后 passed，级别 `mock-functional`。9 份未跟踪报告保持原样，未读取私有数据，未调用真实 provider，未 push。
