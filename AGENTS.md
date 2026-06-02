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
4. **阶段总结**：[docs/stage_01_summary.md](docs/stage_01_summary.md)、[docs/stage_02_summary.md](docs/stage_02_summary.md) — 阶段性回顾与工程教训
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

**SOP 实时状态**：见 [README.md「项目阶段 SOP（实时状态）」](README.md#项目阶段-sop实时状态) — 9 阶段表格 + ✅/⚠️/❌ 状态标记。每 iter 完成时由当轮负责的 agent 同步更新（工程铁律第 8 条）。

**当前 iter**：031（Web Cockpit hardening + handoff refresh，mock-only）
**已完成阶段**：1-4 主链路全打通；5.3 / 8.3 / 9.3 已进入 `write-book` 生产 runner；Web 本地 Beta 入口 iter 029-031 已打通并完成 post-iter030 hardening。实时细节以 README SOP + `docs/AGENT_HANDOFF.md` 末尾为准。
**关键证据**：`write-readiness -> write-book` 是当前推荐生产入口；Web cockpit 支持设置起点、覆盖式重生成计划、继续写书、只读 draft/review 查看、recent job 恢复；iter 031 修复坏 plan 单本容错、persisted job workspace root、隐藏 tab 懒加载、readiness debounce、overview 短 TTL cache。
**下一步候选**：真模型 capstone 完整 ~30-100 章 / KB 按起点过滤安全视图 / entity_graph timeline schema 升级 / Web 在线编辑与复审入口 / LiteLLM lazy-import 与 cost 增量索引。
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
