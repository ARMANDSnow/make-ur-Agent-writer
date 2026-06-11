# Iteration 051 — premise 扩写质量增强 + 评审预算强拦 + 技债清偿

> 承接 iter050 收官顺延项。iter050「不在本轮范围」明确顺延三件事中，**#4 premise 扩写质量增强**为本轮主轨；**review-chapter 独立预算强拦**（050 v1 仅计入总账）与 **iter047 code-review carry-over（F3–F8）**作为副轨摊销。Aeloon 进一步打磨与 KB stage 回退软化继续等实机反馈，不进本轮。
>
> **拍板结论（用户，2026-06-11）**：① 本轮真模型 smoke 预算上限 **≤30 元**（高于草案建议的 15 元：对照实验调用量约为 050 的 2 倍，留足各跑 2 章 + 重试余量；对照口径仍与 050 一致）；② 30–100 章 longzu 端到端 capstone（iter025+ 原计划）**不纳入本轮**，确认顺延 iter052 单独立项 + 单独预算授权；③ 三轨范围照单采用。

## Context

iter048a 落地「一句话开书」：`POST /api/wizard/premise-start`（`src/web/wizard.py:301`）把 ≤2000 字的 premise 包成最小单章文档（`第一章 缘起\n\n{premise}\n`）写入 seed.txt，再走 prepare-greenfield 抽取 KB/entity_graph。代码注释当时已自认这条路的瘦弱性（"a few-dozen-char premise — 049 enriches it; that thinness is the …"）：几十字的种子抽不出像样的实体图与世界观，下游 debate / plan-chapters 拿到的上下文极薄，多章规划质量全靠模型即兴。050 真模型 smoke（smoke050，旧书店店主收到亡友预言谋杀的信）验证了链路通，但规划质量受限于种子信息密度的问题原样保留。

本轮的解法不是把 premise 直接塞给更贵的模型硬抗，而是在 premise 与 prepare-greenfield 之间插一个**显式的、可编辑的扩写产物**：LLM 把一句话种子扩写为结构化设定稿（题材基调 / 主角卡 / 世界观要点 / 主冲突与结局锚点 / 前 N 章弧线提示），落盘为工作台 stage① 可见可编辑的文档，用户改完再喂 prepare-greenfield。这与 050「全程可编辑闭环」的产品哲学一致：**每个 LLM 中间产物都该是用户可审可改的一等公民**，而不是管道里的暗物质。

副轨两件事都是已立案的欠账：review-chapter 在 050 只计入 estimate-cost 总账、无独立上限（050 计划原文「v1 不单独强拦，记录在案」）；iter047 code-review 的 F3–F8 六项加固在 048/049/050 三轮被功能轨连续挤占，再不清偿就会成为永久背景噪音。

## Plan（三轨拆分）

1. **051a premise 扩写质量轨**（主轨）
   - 新增 premise 扩写 agent（mock 优先，铁律③/④）：输入一句话种子，输出结构化扩写稿（建议字段：genre_tone / protagonist / world_notes / central_conflict / ending_anchor / arc_hints，具体 schema 实施时定）。
   - 扩写稿落盘为 workspace 内独立产物（与 seed.txt 并列），进工作台 stage① 展示 + 编辑回写（复用 050 编辑闭环模式：Pydantic 校验 → 原子写盘 → 下游 stage 过期提示）。
   - prepare-greenfield / debate 的 prompt 链路改为优先消费扩写稿；**扩写稿缺失时 graceful degrade 回退现状裸 seed 路径**（铁律④，verify.sh 裸仓库可跑）。
   - premise-start 流程接入：扩写作为 wizard 的可选一步（默认开、可跳过），mock 态返回确定性 stub。
   - C3c 控制字符闸、长度闸（参照 050 M-4 字段级上限口径）覆盖扩写稿全部文本入口。

2. **051b 护栏与技债轨**（副轨）
   - review-chapter 独立预算强拦：新增 env（建议 `NOVEL_REVIEW_BUDGET_CNY`，语义与 `NOVEL_DEFAULT_BUDGET_CNY` 对齐：缺省合理上限、显式 0=无上限、nan/inf/负数 isfinite 拦截——直接复用 050 L-3 的校验函数）；超限行为与 write-book `budget_exceeded` 同款。
   - iter047 carry-over 清偿：
     - F3：config `int(WRITE_MAX_TOKENS)` 等数字 env 解析 try/except 加固（与 F8 合并实施）。
     - F4：streaming gate base_url 规范化。
     - F5：entity_advance invalid 高置信 proposal 静默跳过 → 加日志。
     - F6：起点一致性校验集中到 `src/start_point.py::enforce_consistency`。
     - F7：prompt 开场段降级补丁淘汰（**仅当 F6 落地且测试钉死后**执行，否则顺延并记录）。
     - F8：抽 `_env_int` / `_env_bool` / `_env_choice` helpers 到 config.py，存量散落解析迁移。

3. **051c 收官轨**
   - 真模型 smoke（**需用户授权，铁律⑥**）：同一句话种子跑「裸 seed（现状路径）vs 扩写稿路径」对照各 1–2 章，对比 plan 质量（panel_score / 实体图规模 / 章纲信息密度）与成本，证据落盘本档。预算上限 **≤30 元**（额度已拍板，实跑前仍按铁律⑥确认时点）。
   - 铁律⑧：README「项目阶段 SOP（实时状态）」表 + `docs/AGENT_HANDOFF.md` 末尾 Phase Status 同步。
   - 铁律⑨：收官前 ≥1 个 subagent 只读对抗审查；本轮触碰 web 路由 + wizard + 预算护栏，属高风险面，按惯例拆 2 视角并行（扩写链路/编辑闭环正确性 × API 安全/预算护栏），结论写进 Acceptance Result。

## 关键设计决策

- **扩写稿是独立产物，不覆写 seed.txt**：seed 是用户原话、扩写是模型推断，混写会让「用户到底说了什么」不可考。prepare-greenfield 优先读扩写稿、缺失回退 seed——单向消费、无第二真源。
- **可编辑性复用 050 模式而非另起炉灶**：校验 → 原子写（`write_json` 050 M-1 已全局原子化）→ 下游过期提示。扩写稿编辑后 prepare-greenfield 产物视为过期，提示重跑——与 KB 编辑→stage 回退同一语义，不 hack mtime。
- **mock 态确定性 stub**：扩写 agent 在 `OPENAI_MODEL=mock` 下返回固定结构化稿，保证 808+ 测试零真模型调用（铁律③）且下游断言可钉死。
- **review 预算独立 env 而非复用 default**：write-book 与 review-chapter 成本量级与频次不同（review 可被用户反复触发），共用一个上限会互相挤兑；两 env 校验逻辑共享同一 isfinite 函数，不复制粘贴。
- **F7 严格依赖 F6**：开场段降级补丁是起点一致性缺口的创可贴，先集中校验、测试钉死，再拆补丁；顺序倒置会在真模型路径上裸奔。F6 未在本轮落稳则 F7 显式顺延，不抢跑。
- **30–100 章 capstone 不进本轮**：成本量级（估算数十元起）与本轮「质量增强」目标正交，且 capstone 最好在 premise/plan 质量增强落地后跑——否则跑出来的长程质量问题分不清是规划薄还是写作弱。建议 iter052 单独立项、单独授权预算。

## Acceptance Result（2026-06-11 回填）

### mock 验收 ✅

- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **877 OK**（808 → 837（051a +29）→ 875（051b +38）→ 877（051c 审查修复 +2），零回归）；`PATH=.venv/bin bash scripts/verify.sh` 全链 exit 0。
- 钉死的结构性断言（全部落地）：
  - 扩写稿缺失时回退路径逐字节等价：mock KB == `_mock_knowledge_markdown` verbatim（`test_kb_without_expansion_is_byte_identical_to_pre051`）、debate prompt 无注入块、`_extractions_context` 输出不变；
  - 扩写稿编辑后下游过期：PUT → `has_kb=False` / `expansion_stale=True` / stage 回退 ①，重跑 prepare 清除（`WorkbenchStalenessTests`）；
  - review-chapter 超 `NOVEL_REVIEW_BUDGET_CNY` → `budget_exceeded` 终态带 cost_cny/budget_cny（test_budget_guard 预算矩阵 14 例：缺省 5.0 / 显式 0 无上限 / nan/inf/负数回缺省 / params 覆盖 env）；
  - F6 集中后入口唯一：`start_point.enforce_consistency` 四码与原 `book_runner._plan_metadata_failures` 内联块逐字节同码，plot_planner/book_runner 两调用点 patch 断言走同一函数（test_start_point +13 例）。

### 浏览器实机（mock，铁律「UI 改动必实机」）✅

- ui051 workspace 全程走查：premise 开书（expand 默认勾选）→ 自动扩写 job → stage① 设定面板字段回填（mock stub 确定性值，list 字段按行渲染）→「生成设定」→ KB 含「premise 扩写稿」section → 手改题材基调 → 保存 → 过期提示出现 + stage 回退 ① + 大纲按钮禁用 → 重跑 prepare → 提示清除 + 重新生成的 KB 携带手改内容（"实机改过的题材基调：哥特悬疑"进入 KB）→ console 零 warn/error。

### 铁律⑨ 对抗审查 ✅（双视角并行）

- 视角 A（扩写链路/编辑闭环正确性）：H×0，M×1 + L×2 当轮直修——M-1 `_extractions_context` 截断顺序（拼接后截断可切坏 JSON → 改为扩写稿长度预算扣减，缺失路径仍逐字节等价）；L-1 `render_expansion_markdown` 字段内换行破坏 markdown 列表结构 → 渲染边界折叠为单行；L-2 残缺 artifact 缺 premise 键 → save 时 setdefault 兜底。各补钉死测试。
- 视角 B（API 安全/预算护栏）：auth 闸覆盖新端点 ✓、XSS 零发现 ✓、预算边界矩阵（0/-0.0/1e308/nan/布尔）✓、并发账结（workspace 单 job 锁封死）✓、mcp_server `_env_float` 副本无漂移 ✓。其报告的"控制字符闸放行 \n"经复核**不成立为缺口**：C3c 有意放行 \t\n\r（多行编辑面 KB/outline/draft 依赖），与既有 KB 编辑面立场一致；其实质关切（字段换行伪造 prompt 段头）已由 L-1 渲染折叠在消费边界消除。

### 真模型 smoke ✅（2026-06-12，gpt-5.5-high tier=mid，预算 ≤30 元）

同一句话种子「旧书店店主收到一封亡友的信，信中预言了他自己将在七天后被谋杀」，两条路径各跑 premise-start → [扩写] → prepare-greenfield → debate（6 agent×5 轮+裁决）→ plan-chapters(5) → write-book 1 章 + 评审团：

| 指标 | 裸 seed（现状） | 扩写路径（051a） | 差异 |
|---|---|---|---|
| **panel_score** | 8.16 | **8.50** | +0.34（plot/prose/fidelity 全轴抬升；伏笔猎人 8→9、主角本位 8→9） |
| 章末 verdict | Approve | Approve | 均一次过、needs_human_review=False |
| KB 字符数 | 2914 | **7610** | +161%（扩写稿 6 字段注入 compress） |
| 实体图规模 | 12 实体 / 12 关系 | 14 实体 / 11 关系 | 实体 +2 |
| 章纲信息密度 plan_json | 3637 字符 | **5467 字符** | +50% |
| 章纲 opening/hook 均长 | 38.6 / 39.4 | **44.4 / 49.4** | 开场+15%、钩子+25% |
| key_events 总数 | 25 | 21 | 扩写路径每事件更具体（字数更长），数量略少 |
| 正文 ch1 字数 | 3757 | **4745** | +26% |
| 成本 | ¥2.75（76 calls） | ¥3.22（71 calls） | **+¥0.47（+17%）** |

**两路径合计 ¥5.96 / 30 元预算（耗 20%）。**

**结论**：扩写路径以 +17% 成本换来 panel +0.34、KB 信息量 +161%、章纲密度 +50%、正文 +26%——种子信息密度提升直接传导到下游规划与写作质量，且未触发任何评审失败或一致性退化。051a「在 premise 与 prepare 之间插显式可编辑扩写稿」的设计假设由真模型对照实测证实。裸 seed 路径同时复现了 050 smoke 的 ¥2.75 基线（76 calls 同口径），证明扩写链路对回退路径零回归。

**暗礁**：debate 阶段 gpt-5.5-high 单 call 1.5–3 分钟 × 36 calls ≈ 1 小时，是长流程主要耗时来源；驱动器需 ≥2 小时超时 + 断点续跑（详见 Notes 结构性暗礁）。

## 不在本轮范围

- Aeloon 集成进一步打磨——继续等实机反馈。
- KB 保存 stage 回退交互软化——实机反馈刺眼再议，不 hack mtime。
- 30–100 章 longzu 端到端 capstone——建议 iter052 单独立项 + 单独预算授权（理由见关键设计决策末条）。
- premise 扩写的多轮自评/迭代精修（agent 自己评自己改）——v1 先落「一次扩写 + 人工可编辑」，多轮精修视真模型对照结果再议。

## Notes

- 本档**已收官**（mock 段 2026-06-11 + 真模型对照 smoke 2026-06-12）。拍板项全部兑现：① smoke 实耗 ¥5.96/30 元；② capstone 顺延 iter052；③ 三轨照单采用。扩写路径质量优势经真模型对照实测证实（panel +0.34，详见 Acceptance）。
- **设计偏离记录（051a）**：premise-start 的 `expand` 参数 **API 缺省 false、wizard 前端 checkbox 默认勾选**——计划原文「默认开、可跳过」落在 UI 层而非 API 层。理由：API 默认 true 会让 novel_client/MCP/存量测试的「create-only、不起 job」契约被打破，且 premise→prepare 紧链式调用会撞 409 workspace_busy 竞态；UI 默认勾选保住产品语义，程序化调用方显式 opt-in。
- **F4 验证结论**：streaming gate base_url 规范化已于 iter027 P2b-fix v2 落地（`llm_client._normalize_url`），本轮零代码改动，补 2 个等价类测试钉死（尾斜杠/大小写/None 降级）。
- **F7 显式顺延**：F6 本轮才落地、未经真模型路径验证「落稳」，按计划依赖关系不抢跑；建议 051 smoke 或 iter052 验证 F6 后再拆 writer.py 开场补丁。
- **F6 原文出处校准**：F3–F8 实际出自 iter027 capstone 文档 P7 /code-review findings（AGENT_HANDOFF.md 同文转录），非 047 系列；本档第 26 行「iter047 carry-over」沿用了 050 收官时的口径，特此校准。
- 暗礁：扩写稿消费的三个注入点（compress/debate/bootstrap）统一走 `expansion_prompt_block()` 单点降级——任何新消费点必须复用它，不得自行 read JSON（否则破坏"缺失=逐字节等价"的回退契约）。
- **暗礁（结构性，smoke051 实录）**：真模型长流程（2 小时级）的驱动进程**不能寄生在 agent 会话的后台任务里**——会话 context 压缩/重启会静默回收进程组（无信号无 traceback，smoke051 因此死过一次；另一次是 debate 超时参数低估了 gpt-5.5-high 单 call 1.5–3 分钟 × 36 calls 的量级）。macOS 无 `setsid` 命令，正确的脱离方式是 Python double-fork + `os.setsid()`（ppid=1 归 launchd）。项目侧韧性已达标：debate_log 逐条落盘断点续跑 + web_jobs 持久化 + 幂等驱动 gate，三次中断零数据损失、零重复花费。
- 验收命令统一 `.venv/bin/python`；verify.sh 需 venv PATH（050 暗礁实录）。
- 铁律⑤：收官只 commit 不 push。
