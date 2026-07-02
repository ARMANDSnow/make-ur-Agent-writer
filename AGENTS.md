# AGENTS.md — 项目上下文锚点

> **任何 AI agent（codex / claude / 其他）进入本仓库时，先读完本文件再做任何事。**
> 这是省去每次重新解释项目背景的 entrypoint。预计 2-3 分钟读完。

## 项目本质

Dragon Raja AI Continuer MVP：基于 LLM 多 agent 协作的中文小说续写流水线。当前主验证书目 龙族（江南），但目标是任意小说通用化。

**不许修改 `小说txt/` 原文。** 该目录含原作者版权文本，仅用于 normalize/extract 输入。

## 默认模式

- **mock-only（默认）**：`OPENAI_MODEL=mock`，无 API key，全流水线本地跑通用于工程验证
- **真模型（用户手工切）**：`.env` 中 `OPENAI_MODEL=deepseek/deepseek-chat`（**必须带 provider 前缀**，iter 006 踩过坑）

## 进入工作流前必读（按顺序）

1. **当前状态**：[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) — 截至最后一轮迭代的完整能力清单 + Next Candidates
2. **迭代索引**：[docs/iterations/README.md](docs/iterations/README.md) — 按编号排列，每轮一个 .md
3. **最新迭代详情**：上面索引里最大编号的那个 iteration_NNN_*.md（8 段标准结构）
4. **阶段总结**：[docs/stage_01_summary.md](docs/stage_01_summary.md)、[docs/stage_02_summary.md](docs/stage_02_summary.md)、[docs/stage_03_summary.md](docs/stage_03_summary.md) — 阶段性回顾与工程教训
5. **当前任务计划**：用户每轮把详细计划写在 `~/.claude/plans/docs-rosy-wadler.md`（仓库外），任务指令会指向该文件

## 工程铁律（违反必须给理由）

1. **API key 安全**：任何时刻看到 `sk-` 模式立即停止。不主动改 `.env`，不主动跑真模型 smoke。`.env` 已在 `.gitignore`
2. **小说原文版权**：`data/style_examples/*.md` 和 `data/entity_graph.json` 由用户本地手填，**不要主动写入任何 龙族 原文片段**。`*.example.json` 等示例文件只放 schema + `<用户填写>` 占位符
3. **测试隔离**：单测必须 `OPENAI_MODEL=mock` 跑（`tests/__init__.py` 已强制），任何让 `unittest discover` 触发真模型调用的改动都是 bug
4. **mock 路径 graceful degrade**：所有可选数据源（style_examples、global_facts、entity_graph、continuation_anchor）缺失时**不报错**，让 `verify.sh` 在裸仓库也能跑通
5. **commit 不 push**：完成迭代后只 commit 不 push，等用户验收
6. **真模型 smoke 必须等用户授权**：`scripts/{real,debate,write}_smoke.sh` 涉及真 API 调用，必须用户回"可以跑了"才能执行
7. **scope 收敛**：不要把"顺手修一下"扩展到计划外文件。真模型暴露的真实 bug 例外（iter 008 修 reviewer/writer 是这种情况）但要在文档里诚实记录
8. **SOP 实时性**（iter 021 新增）：每轮 iter 收官时必须同步 [README.md「项目阶段 SOP（实时状态）」](README.md#项目阶段-sop实时状态) 表格的状态字段（✅/⚠️/❌）+ "最近一次更新" 时间戳 + `docs/AGENT_HANDOFF.md` 末尾追加 Phase Status。这个表是用户判断"哪里打通了 / 哪里还没"的单一真实来源
9. **迭代末尾代码审查**（iter 031 引入，2026-06 升级为内置 skill）：每轮 iter 收官前，必须对本轮改动做结构性/程序性只读审查。**优先用内置 skill**：跑 `/code-review high`（正确性 bug + 复用/简化/效率）+ `/security-review`（API key / `.env` 泄漏自查，对口第 1 条）。Web / runner / 多 workspace / 真模型入口等高风险改动，加跑 `/code-review ultra`（云端多 agent，需用户授权、计费）或拆 2 个独立视角 subagent 并行审。审查范围、结论、未修风险必须写进当轮 iteration 的 `Acceptance Result` 或 `Notes`，再提交。审查为只读：不得跑真模型 smoke、不得触碰 `.env`、`data/`、`outputs/`、`小说txt/`。

## 迭代记录格式

每轮新建 `docs/iterations/iteration_NNN_<short_name>.md`，**必须 8 段**：

```
Context / Plan / Acceptance / Implementation Notes / Acceptance Result / 文件变更汇总 / 不在本轮范围 / Notes
```

同步更新 `docs/iterations/README.md` 索引 + `docs/AGENT_HANDOFF.md` 末尾追加。

## 验证命令

```bash
# 工程 sanity（每次改完代码先跑）
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
bash scripts/verify.sh
python3 main.py preflight

# 真模型 smoke（仅用户授权后）
bash scripts/real_smoke.sh     # extract 小样本，~$0.03
bash scripts/debate_smoke.sh   # debate 全链路，~$0.15
bash scripts/write_smoke.sh    # write 1 章端到端，~$0.20-0.30
```

## 关键路径速查

```
src/                      # 主代码
  config.py               # load_config / ROOT / dotenv（dotenv 在测试态会被跳过）
  llm_client.py           # 真/mock 模型抽象，cache_segments 注入，token 日志
  preflight.py            # 上游守门 FATAL/WARN/INFO 三档
  writer.py               # 章节生成 + lint + review + polish 循环
  reviewer.py             # 7 agent review，agent_name repair
  debater.py              # 6 轮辩论 + 裁决投票（ballot 字段修复）
  linter.py               # 确定性句式 lint，含阈值化规则
  extractor.py            # chunked extraction + rolling summary
  compressor.py           # 全局知识库构建
  chapter_splitter.py     # 章节切分 + confidence 评分
  style.py                # data/style_examples/ loader
  entities.py             # data/entity_graph.json loader（iter 011 引入）

config/
  agents.yaml             # max_review_attempts / polish_pass / continuation_anchor / review_agents
  models.yaml             # 各 task 的 model/temperature/max_tokens/context_limit
  linter.yaml             # 规则启用与阈值

data/                     # 全部 gitignored（产物 + 用户私有内容）
  normalized_texts/       # 原文规范化（衍生自 小说txt/）
  extracted_jsons/        # 章节抽取
  rolling_summaries/      # 跨章滚动摘要
  knowledge_base/         # compress 产物
  manual_overrides/       # 用户手填的 global_facts.json
  style_examples/         # 用户手挑的江南文风片段
  entity_graph.json       # 用户手填的实体关系图（iter 011 引入）
  chapter_manifest.json   # 切章索引（含 confidence）

outputs/                  # 全部 gitignored
  debate/                 # decisions.json / outline.md / debate_log.jsonl / snapshots/
  drafts/                 # chapter_NN.md + meta.json + snapshots/
  reviews/                # 各章 review json

logs/                     # 全部 gitignored
  llm_calls.jsonl         # 每次调用的 model/status/token/hash（append-only）
  *_smoke_<ts>.log        # 真模型 smoke 全程 stdout/stderr
```

## 当前阶段 & SOP 状态

**最后更新**：iter 076（2026-07-02）

**SOP 实时状态**：见 [README.md「项目阶段 SOP（实时状态）」](README.md#项目阶段-sop实时状态) — 9 阶段表格 + ✅/⚠️/❌ 状态标记。每 iter 完成时由当轮负责的 agent 同步更新（工程铁律第 8 条）。

**当前 iter**：076（长跑可靠性硬化 + iter074/075 codex 修复批 — capstone 前置门，iter074-077 路线图第三步；路线图计划稿 `~/.claude/plans/logical-snuggling-gray.md`、本轮细化 `~/.claude/plans/iter-076-bright-simon.md`）
**已完成阶段**：1-4 主链路全打通；5.3/8.3/9.3 进入 `write-book` 生产 runner；Web 本地 Beta 多页 IA（iter 029-044，含 wizard/cancel/mobile 响应式）；iter 045-052 产品力补齐 + Aeloon 插件/MCP 双轨集成（iter049）+ 全程可编辑闭环（iter050）+ premise 扩写质量（iter051）+ 长程驱动器 `drive-book` 正式化（iter052，detach/断点续跑/预算双层）；iter 053-057 续写机制保证 + 驱动器加固 + 作家风格卡 + capstone 前置 5 bug 全修；iter 058-064 前端 P0/P1/P2 收口 + UX 重构 + CLI/Web 健壮性对齐；iter 065-073 语义闭环（plan-compliance reviewer + entity CREATE）+ 长流程 fail-closed 数值/JSON 硬化 + leave-guard 异步竞态 + outline-drift severe block + job API 三档投影 + entity_state 注入护栏；iter 074 章节版本 diff；iter 075 全文搜索（三语料跨章检索）；iter 076 长跑可靠性硬化（panel_block_policy 拒稿不 halt + 每章预算预留 + 分档超时 + driver 心跳 & watchdog --driver + supervisor crash 自动重启）+ codex 六项修复批。实时细节以 README「最近一次更新」叙述 + `docs/AGENT_HANDOFF.md` 末尾 Phase Status 为准。
**关键证据**：工程主链路 **STRUCTURE GO**（2026-06-26 真模型前置排查未发现会崩溃/静默损坏的引擎 bug，唯一隐患 entity_state 无界注入已修 commit `178ab62`）；**过夜长跑推荐入口**（iter076 起）：`nohup bash scripts/drive_book_supervised.sh --book <名> --confirm-real-smoke -- --chapters N --tier mid --budget-cny <软阈> &` + 另终端 `bash scripts/watchdog.sh --book <名> --driver`（supervisor 决策表自动 resume、watchdog 心跳判活 TERM→KILL 升级留场）；`write-readiness -> write-book` 与 `drive-book --detach` 仍是无 supervisor 时的生产入口；Web `/` 书架 → 侧栏 → `/w/{name}/{overview,continue,plan,chapters,chapter/{n},reviews,insights,jobs}` 多页 IA，章节详情页「历史」tab 多版本 diff（iter074）+ 全文搜索页（iter075）；`unittest discover`（.venv）为 **1475 tests OK**（iter076 收官）；mock 25 章长流程回归三关全过（succeeded+25/25 Approve+心跳新鲜 / resume 零新 LLM 调用 / supervisor 集成 exit 0）；真模型实证 longzu 续写 ch1-5 全 Approve（iter053-056）、shudian premise 书 7/7 Approve（panel 均值 8.38，iter052）。**缺口**：20+ 章真模型长程 capstone 未端到端跑通（iter076 已补齐自动恢复层，待 iter077 实跑验证）。
**后续候选（iter077，路线图收官步）**：真模型 capstone 实跑（10-20 章，铁律⑥需用户授权；建议 `on_soft_reject=caveat_continue + max_panel_rejections=2 + tier=mid`）。其它：Aeloon 深色模式对齐（跨仓库字节级 + `aeloon_sync_check.sh` 验）/ drama 站③分镜·④角色 / AI 绘画 client / Comfy 导出 / drama_reviewer / char-level diff / KB 起点过滤安全视图 / auto-advance 缺失关系上游校验 / mock planner 尊重 --chapters（低价值）/ 可靠性 MEDIUM-LOW（段级预算回滚、指标导出、退避 jitter）。
**详细阶段总结**：[stage_03_summary.md](docs/stage_03_summary.md) + 最新 iteration .md 的 Notes / 下一步段落

## 常用 git 操作

```bash
# 完成一轮迭代
git add <相关文件>
git commit -m "Iteration NNN: <短描述>"
# 不要 push，等用户验收

# 用户验收完成后由用户或 claude 决定 push
```

提交 author 已配置为用户的 GitHub identity，commit 直接挂上。`.gitignore` 已覆盖 `.env / data/ / outputs/ / logs/ / .claude/settings.local.json / 小说txt/`。

## 出现问题时

- 不确定计划意图 → 读 `~/.claude/plans/docs-rosy-wadler.md`
- 不确定历史决策 → 读对应 `docs/iterations/iteration_NNN_*.md` 的 Context + Notes
- 不确定工程教训 → 读 stage 总结 + AGENT_HANDOFF
- 测试挂了 → 先确认 `OPENAI_MODEL=mock`，再看是否引入了未 mock 的真模型路径
- 真模型调用挂了 → 看 `logs/llm_calls.jsonl` 末尾几条的 error 字段；常见原因：litellm provider 前缀错、key 过期、context overflow（已有 LLMContextOverflowError 守门）

**任何时候不确定，停下来问用户，不要猜。**
