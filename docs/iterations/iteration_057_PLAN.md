# Iteration 057 — 长程续写 capstone 前置：5 个结构性 bug 全修复

> 承接 iter056「作家风格卡」收官 + iter056 末**长程续写结构性审查**（双 subagent 对抗 + 源码核验发现 5 个「3 章测不出、30+ 章爆」的真 bug，详见 `docs/AGENT_HANDOFF.md`「iter056 附」）。iter056 末用户拍板「5 bug 留 iter057」；本轮 **2026-06-18 用户接力指令反转为「现在修」**。先派 3 个 general-purpose subagent 逐行复核根因/影响半径/向后兼容/测试缺口（修正原审查 2 处认知偏差），再按风险递增实施，**每个 bug 独立 commit**。全量 **1097 passed**。

## Context

iter056 的 V5 续写 3 章全 Approve **只证短链路功能打通、非长程稳定**。capstone（30+ 章长程续写，自 iter024 起列第一优先、6 轮顺延、基建就绪）的前置阻塞正是这 5 个 bug——它们在 3 章窄路径上测不出，但 30+ 章（开 `--replan-every` + 多次 resume + 中转站抖动）必然引爆。本轮把它们清掉，是 capstone 真跑前的「拆弹」。

修复哲学（沿用项目铁律）：阻断器（P0）优先；HIGH-2/P1-C 先上**确定性 MVP**（无 LLM、可纯单测、不烧钱），完整版（需真模型验证）留后续；每个 bug 独立 commit + 分项回归 + 全量兜底。

## 审核流程（subagent 审核 + 源码逐行核验）

按领域分 3 个 general-purpose subagent **只读**审核，再由主 agent 集中实施（避免多 agent 并行改共享文件 `book_driver.py`/`book_runner.py` 冲突）：

- **subagent A（规划/断点）**：P0-A + BLOCKER-1 —— plot_planner / chapter_status / book_driver / entity_advance。
- **subagent B（LLM 流式）**：P0-B —— llm_client / models.yaml，深度对比方案 A/B。
- **subagent C（长程记忆/一致性）**：HIGH-2 + P1-C —— chapter_summary / book_runner / start_point / reviewer。

**原审查 2 处认知纠偏（subagent 复核 + 源码核验得出）**：
1. **P0-A 比记录更严重**：非「30 章后爆」，而是「**触发一次 replan → 下一段 resume 立刻 `BookRunBlocked` 卡死**」（`book_driver` 每段重 walk 全盘，第一个已写章即 mismatch）。
2. **P1-C 因果链下半段错**：原记录称「reviewer 拿失真 outline 当 fidelity 基准误拒正确承接」——**核验发现 reviewer 根本不消费 outline**（`reviewer.py:247` 无 outline 参数，fidelity 基准是「源书原文风格」）。漂移的真实危害在 **write-time 把过时 outline 逐字喂进每章 writer prompt**（`writer.py:686`），不是 review 误拒。→ 修复方向相应调整，MVP 只做漂移**可见性**，不碰 reviewer。

## 5 bug 修复（按执行/commit 顺序）

| Bug | 级别 | 根因（已核验） | 修复 | commit |
|---|---|---|---|---|
| **BLOCKER-1** | 🟠 | `book_driver.py:764` 默认 `plan_target = min(10, …)` 钉死 10 → `--chapters 30` 默认配置 ch11+ 缺 plan、规划阶段 fail-closed block | 删 `min(10,…)`，默认 = `chapters+resume_from-1` 覆盖全程，与 readiness 口径对齐 | `938a4a6` |
| **P0-B** | 🔴 | `models.yaml` write **唯独缺 `stream` 键** → `OPENAI_STREAM=1` 走流式 → litellm 不把 `request_timeout:480` 落 SSE read（iter055 V2 实测）→ `_consume_stream` 裸循环无 idle 保护 → 单章卡满 driver 180min 兜底 | write 加 `stream:false`（**方案A 止血，用户拍板**）：当前架构无流式真实消费者（产出落盘+人工审，detach stdout 进 DEVNULL），UX 损失≈零；非流式 litellm 遵守 timeout | `b71411d` + `9e657d5` |
| **P0-A** | 🔴 | `plot_planner.py:319` plan_fingerprint 哈希 **chapters 全列表 + target_chapters** → replan append 改 fingerprint → 已写章 meta 冻结旧指纹 mismatch → 非 `skipped_approved` → `BookRunBlocked` / `--force` 重写 + `entity_advance` 非幂等重复突变实体图 | 收窄为只哈希**全局上下文**（overall_arc + start_chapter_id + start_point_fingerprint），章节级交给 `chapter_plan_item_fingerprint`（按章，已正确）；schema_version 1→2 | `0992e50` |
| **HIGH-2** | 🟠 | `chapter_summary.py` `compressed_older` **零写盘**（仅 `_empty_state` 初始化 + render 读）→ older 章记忆靠 render 砍成 12 字/条、只留 10 条 → ch25+ 早期伏笔/设定失忆 | **MVP**：确定性逐章 compact 写盘（滑出近场 5 章 → 一行 ≤60 字、上限 40 章），render 优先吃它、prune 同步回退；空时回落旧逻辑（向后兼容） | `692feb7` |
| **P1-C** | 🟠 | `book_driver.py:309` outline 守卫只校验 provenance（起点指纹/sha256），无「剧情 vs outline 语义偏离」检测 | **MVP**：`src/outline_drift.py` outline 提及的实体锚点在最近 10 章 rolling 命中率 <0.4 → `outline_semantic_drift` warn（**只 warn 不 block**，接入 book_runner readiness warn lane，best-effort 不让探针 block） | `4c876c2` |

## 关键设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| P0-B 方案 A vs B | **方案 A（stream:false）止血** | 当前架构无流式真实消费者，UX 损失≈零；方案 B（idle-deadline watchdog）有 litellm `.close()` 跨版本风险、mock 测不全，留后续真模型验证 |
| P0-A plan_fingerprint 范围 | 只哈希全局上下文，**完全不含任何章节内容** | 绕过「只哈希未写章」second-truth-source trap；replan append 不动全局 → 已写章稳定；起点移动仍翻转 → 保住失效检测 |
| P0-A 向后兼容 | **配套迁移脚本**（不可省） | 218 个现存 meta + 活跃 workspace 升级即全盘 mismatch；`scripts/migrate_plan_fingerprints.py` 幂等刷新 plan/meta/review |
| web 编辑 strict-expire 语义 | **接受新精确语义**（用户拍板） | plan_fingerprint 收窄**必然**把「编辑任意章→所有已写章 strict-expire」变为「只 expire 被编辑章（via item 指纹）」；二者技术不可兼得（要 replan 不卡死就不能让加章/改章翻转全局指纹）；`routes.written_chapters_invalidated` 同步只报被编辑章 |
| HIGH-2 方向 | 实现 compressed_older 写盘（非重定位职责） | KB/entity 只兜源书 canon，兜不住「续写自生情节钩子」，rolling 是其唯一长程载体 |
| HIGH-2 / P1-C 深度 | **先上确定性 MVP** | 无 LLM、可纯单测、不烧钱；完整版（LLM 压缩 / LLM 语义判定）需真模型验证 |
| P1-C 修复落点 | write-time prompt + planner，**不碰 reviewer** | 纠偏：reviewer 不消费 outline，漂移真实战场在 write-time 喂图纸 |

## 向后兼容（P0-A 迁移实证）

`scripts/migrate_plan_fingerprints.py`（一次性、幂等、纯 I/O）：对活跃 workspace（`workspaces/*/outputs` + 根 `outputs/`，跳过 `_`/`.` 开头与 snapshots）刷新 `chapter_plan.json` 的 plan_fingerprint + 所有 `chapter_NN.meta.json`/`reviews/*.review.json` 的 `run_context.plan_fingerprint`。

**已真跑**：longzu / shudian052 / tianlong / root —— **4 plan + 15 meta + 17 review** 刷新，迁移后逐 workspace 验证 plan `stored==recompute`、各 meta 全对齐 plan_fingerprint（实证）。i38drama01（短剧用 episodes）正确跳过。

## Acceptance / 验证

**全量 `pytest` 1097 passed / 0 failed**（310s 含 E2E）。分项实测：
- BLOCKER-1：`test_book_driver` 31 passed（含 E2E）+ 3 新单测（默认 plan_target 分支此前零覆盖）。
- P0-B：streaming/timeout 测试通过；**全量回归抓到 1 个 subagent 漏看的回归**（`test_openai_stream_env_enables_streaming_by_default` 用 write task 测 env 默认流式，write→非流式后过时 → 改用 default task）。
- P0-A：影响范围 106 passed（plot_planner/chapter_status/book_runner/workbench/web_plan/migrate）；新增 `test_append_preserves_plan_fingerprint` + chapter_status 真实校验链（现有 replan 测试 mock 掉 chapter_status 是**伪覆盖**）+ 迁移脚本单测。
- HIGH-2：rolling 19 passed（累积/render可见/prune回退）；现有 4 章测试不触发 compact（<5）、旧格式保留。
- P1-C：P1-C+readiness 58 passed（drift detected/clean/锚点不足/别名命中）。

## 暗礁与教训

- **R1**：P0-A「改哈希」本身是小修，但向后兼容迁移**不可省**——否则把「replan 卡死」换成「升级即全盘卡死」，更糟。迁移必须与哈希改动同 PR/同轮落地。
- **R2（教训）**：subagent 只读审给的「不受影响测试」清单**不可全信**——P0-B 的 streaming env 测试就被漏看，靠**全量回归兜底**抓到。任何改了「task 默认行为」的改动，必须跑全量而非只跑 subagent 点名的文件。
- **R3**：P0-A 触发了一个被 `test_workbench_replan.py:331` 明确 pin、警告勿削弱的产品语义——subagent A 也漏审，主 agent 源码核验时发现、经用户拍板处理。**核验 pin 测试的 docstring 是必要步骤**。
- **R4**：HIGH-2 `prune_from_chapter` 必须同步回退 `compressed_older`，否则重写章的旧紧凑行残留毒化 retry。
- **R5**：P1-C 探针 best-effort try/except 包裹，**任何异常都不得让它 block readiness**（漏报优于误报/误 block，本项目铁律：误报训练用户习惯性逃生）。
- **R6**：只 commit 不 push（沿用项目纪律）。

## 不在本轮范围（完整版留后续，均需真模型验证）

- **P0-B 方案 B**：保流式 + `_consume_stream` per-chunk idle-deadline watchdog（保留前端实时预览能力）。
- **HIGH-2 完整版**：周期性 LLM 二次压缩 older 章节（融合伏笔链、控 token 增长），复用 `compress` task + 仿 `writer._summarize_chapter` mock-safe 范式。
- **P1-C 完整版**：LLM 语义判定漂移 + write-time fidelity 基准从静态 outline 切到滚动上下文（漂移高时 outline 降级为背景参考）。
- **capstone 本体**：30+ 章真跑。前置顺序（沿用 iter056 审查）：先 mock 全跑 30 章 + 真模型 ch1-15 → 才谈 30+ 真跑。`test_book_driver.py` 的「replan + 段间 resume + 流式卡死」端到端 subprocess 层仍可加固（本轮已补 chapter_status 真实校验链层）。
- **本轮未做真模型实跑**（按计划，MVP 全确定性、不烧钱）。

## 关键文件

**新增**：`scripts/migrate_plan_fingerprints.py`、`src/outline_drift.py`、`tests/test_migrate_plan_fingerprints.py`、`tests/test_outline_drift.py`。

**修改**：`src/book_driver.py`（BLOCKER-1）、`config/models.yaml` + `tests/test_llm_client_stream_per_task.py` + `tests/test_llm_client_streaming.py`（P0-B）、`src/plot_planner.py` + `src/web/routes.py`（P0-A）、`src/chapter_summary.py`（HIGH-2）、`src/book_runner.py`（P1-C 接入）、`docs/AGENT_HANDOFF.md`；测试更新 `tests/test_book_driver.py`、`tests/test_plot_planner_append.py`、`tests/test_plot_planner_edit.py`、`tests/test_chapter_status.py`、`tests/test_workbench_replan.py`、`tests/test_web_plan_edit.py`、`tests/test_chapter_summary.py`。
