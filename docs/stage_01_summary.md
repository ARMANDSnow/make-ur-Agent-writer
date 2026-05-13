# 阶段 1 小结：Mock 工程加固 → 首次真模型小样本

> 覆盖范围：[iteration 001](./iterations/iteration_001_observability_guards.md) - [iteration 005](./iterations/iteration_005_debate_vote_and_real_smoke.md)
> 时间窗：2026-05-04 至 2026-05-13
> 阶段定义：从 mock-only 流水线到第一次真模型 extract 小样本跑通，**任何创作质量结构性改造（B3 / C2）尚未开始**。

## 阶段目标回顾

iteration 001 之前，项目只有"能跑通 mock 全流水线"的状态；不知道真模型上哪些环节会先翻。

本阶段不追求一次性产出长篇续写，而是把"准备真模型"做扎实：可观测性、失败 resume、prompt cache、context overflow 防护、preflight 拦截、配置硬约束、章节边界置信度。**最后一步用 2 章 DeepSeek-V3 extract 小样本验证整套工程没在真模型路径上裂开**。

## 已交付能力（阶段累计）

### CLI 表面

```
python3 main.py [normalize | split | extract | compress | debate | write | review | run-all]
python3 main.py [status | manifest-report | review-summary | estimate-cost | retry-failures]
python3 main.py [check-manifest | check-reports | preflight]

bash scripts/verify.sh        # mock + 单测，日常 sanity
bash scripts/real_smoke.sh    # preflight → extract --limit 2 → status → estimate-cost → preflight
bash scripts/debate_smoke.sh  # 下一轮 debate 真模型联调入口（当前 mock 验证）
```

### 数据 / 知识资产

- `data/normalized_texts/` 6 卷规范化文本，`data/chapter_manifest.json` 101 章索引（含 confidence 字段）
- `data/extracted_jsons/` 章节抽取，超长章 chunk 化（24k 字阈值，3 chunk + 中文句界合并）
- `data/rolling_summaries/<volume>.json` 跨章滚动摘要 + 句末边界裁剪 + 上限项数
- `data/knowledge_base/global_knowledge.md` + `knowledge_index.json` 全局压缩
- `data/manual_overrides/global_facts.json` 人工裁决（如"绘梨衣已死亡"），注入 extract / debate / write / review 四个阶段的 prompt
- `data/extraction_failures/` chunked 失败兜底（preflight 见到残留即 FATAL）
- `outputs/debate/{decisions.json, outline.md, debate_log.jsonl}` debate 产物，含结构化投票轨迹（"裁决投票"轮）
- `outputs/drafts/`、`outputs/reviews/` 续写与审查结果
- `logs/llm_calls.jsonl` 每次 LLM 调用的 token / hash / 状态留痕

### 可观测 / 守门

| 守门 | 入口 | 触发条件 |
|------|------|---------|
| 测试 | `python3 -m unittest discover -s tests` | 73 条单测 |
| 流水线 sanity | `bash scripts/verify.sh` | mock 跑通 + check-reports + check-manifest |
| Preflight | `python3 main.py preflight` | 缺 API key、context limit 错配、`agents.yaml` 缺 `max_review_attempts`、失败残留、rolling 漂移、chunk 阈值、low confidence 章节、最近 token 日志 |
| Manifest 完整性 | `python3 main.py check-manifest` | chapter_id 重复、行范围冲突、normalized 缺失、confidence 越界 / 低置信度统计 |
| Snapshot drift | `python3 main.py check-reports` | manifest / review summary Markdown 与 JSON 输入失同步 |
| 调用追溯 | `logs/llm_calls.jsonl` + `python3 main.py estimate-cost` | model / status / prompt_tokens / response_tokens / cache_read / cache_write / request_hash |

### 工程硬约束（阶段累计的"不可降级项"）

- `agents.yaml` 的 `max_review_attempts` 是**必填正整数**，writer 与 preflight 同步报错（004 起）
- writer 把 system prompt / 全局知识 / outline 标为 prompt cache segment；provider 不支持 cache 时自动降级，不靠 try/except 兜底
- extract 章节 prompt 超 context 时**抛 `LLMContextOverflowError` 不打远端**
- chunked extract **全 chunk 成功才合并**，任一失败整章进 failures（避免半成品）
- reviewer 反馈支持 `rule_id / severity / anchor`，writer 把 reject 的具体规则 ID 写回下一轮 prompt
- rolling summary 按中文句末边界裁剪（非字符硬截断）+ 上限项数（配置）
- splitter 输出 `confidence ∈ [0,1]`，由 heading pattern × 章节长度 × dedup 风险区三个确定性信号取 min
- debate 投票从"LLM 事后猜 for/against"升级为"agent 自报 ballot → 显式多数决聚合"，平票标 `[平票]`，多数反对标 `[多数反对]`
- 所有迭代记录在 `docs/iterations/<NNN>_*.md`，每轮含 Context / Plan / Acceptance / Implementation Notes / Acceptance Result / 文件变更汇总 / 不在本轮范围 / Notes 八段

## 验证状态（阶段末）

| 项 | 状态 |
|---|---|
| 单测 | ✅ 73 / 73 |
| `bash scripts/verify.sh` | ✅ 退出码 0 |
| `python3 main.py preflight`（mock） | ✅ warn，0 FATAL |
| `bash scripts/real_smoke.sh`（DeepSeek-V3） | ✅ 2 章 extract 0 failure，前后两次 preflight 均 warn 0 FATAL |
| 日志干净度 | ✅ 清理 4 条早期 litellm 本地拒错残留 |
| 全仓 `grep "sk-"` | ✅ 无命中 |

## 关键数字

| 指标 | 值 | 来源 |
|------|----|------|
| 总测试 | 73 条（005 末） | `unittest discover` |
| 章节总数 | 101 | `data/chapter_manifest.json` |
| 最长章节 | longzu_1_ch004，121,406 字 | preflight INFO |
| 超 chunk 阈值章节 | 38 / 101 | preflight INFO |
| 低置信度章节（<0.6） | 0 | check-manifest |
| DeepSeek 小样本耗时 | 2 分 25 秒 / 2 章 | real_smoke 日志 |
| 单次调用平均 | ~6,000 prompt_tokens / 2,500 response_tokens | llm_calls.jsonl |
| 真模型小样本成本 | ≈ $0.030 / 2 章 | DeepSeek-V3 单价估算 |
| 累计真实 token | prompt 41,877 / response 17,107 | 本次 7 个调用 |

按当前单价线性外推：跑完 101 章 extract 约 **$1.5**；如果整套（extract + compress + debate + write + review）按 `estimate-cost` 累计的 mock-期 `llm_logged_calls=691` 拆分实际打 deepseek：粗估单卷 **$10-15**。**这个数字尚未实测**，阶段 2 第一轮可以专门确认。

## 工程教训（按踩坑顺序）

1. **rewrite_max 命名陷阱（002 → 003）**：配置项叫 `rewrite_max: 2` 但实际是"初稿 + 重写的总尝试次数"，读起来误导。003 重命名 `max_review_attempts` 并保留一轮 fallback，004 起硬要求新键。**经验：配置语义和直觉不一致就是 bug**。
2. **fallback 一轮原则（004）**：兼容代码"先留一轮"很容易留半年。004 明确"上一轮加，下一轮删"，避免技术债累积。同时 grep 出 5 个外部调用方（测试 + README），一并替换不留尾巴。
3. **API key 在对话泄露（005）**：用户两次在 chat 里粘贴明文 key。第一次让用户轮换；第二次坚持让用户自己用 heredoc 写 .env，**Claude 端从未持有真实 key**。
4. **litellm provider 前缀（005）**：本地 litellm 1.83.9 不认裸 `deepseek-chat`，要求 `deepseek/deepseek-chat`。**经验：跑真模型前先 `python3 -c "from litellm import get_llm_provider; print(get_llm_provider(model))"` 做客户端侧路由 sanity**。这一步可以加进 preflight 作为 FATAL（候选下一轮做）。
5. **chunked extraction 失败不能半合并（002）**：之前任一 chunk 失败可能写出"半本章"。002 加硬约束：全 chunk OK 才 merge，否则整章进 failures。chunked 设计的真正难点是错误模式而不是切分逻辑。
6. **prompt cache 降级路径要可见（002）**：早期 cache_control 注入失败会让整条 prompt 跑挂；现在 LLMClient 在第一次失败时自动降级到普通 prompt 重试一次，并在 llm_calls.jsonl 记录降级标记。

## 当前局限 / 已知 WARN（阶段末 preflight）

1. `tiktoken has no direct encoding for model 'deepseek/deepseek-chat'`：tiktoken 没有 DeepSeek 的官方 encoding，回落到 `cl100k_base`，中文 token 计数会偏低 5-10%。**不阻塞**，但 estimate-cost 略保守。
2. `Longest chapter longzu_1_ch004 estimated prompt_tokens=244100`：章节本身 121k 字，单个 chunk 也接近 context_limit 90% —— 当前 chunked extraction 已经处理（切 3 chunk），但有可能在某些 chunk 边界把语义割断。**等阶段 2 真模型 debate / write 跑出具体翻车样式再决定要不要细化**。
3. `data/manual_overrides/global_facts.json is missing or empty`：人工裁决未注入。**走真模型前应至少写入"绘梨衣已死亡 / 路明非血统未净化"等关键事实**，否则 debate / write 会自由发挥。
4. **未实测**：真模型 compress / debate / write / review 全链路。只有 extract 跑过 2 章真模型。下一轮做 debate 真模型小样本时，会暴露 prompt 是否在 deepseek 上稳定输出合法 JSON、长 prompt 拼接是否撞 token、prompt cache 是否真触发等。

## 阶段 2 候选（优先级建议）

| 候选 | 类型 | 建议优先级 | 理由 |
|------|------|----------|------|
| **手工写 `global_facts.json`** | 数据 | **P0**（用户操作） | 跑 debate 真模型前的硬前提，5 分钟工作量 |
| **真模型 debate 小样本** | 验证 | **P1** | `bash scripts/debate_smoke.sh`，约 40 次调用，估算 ~$0.50；暴露真模型下 prompt / JSON 稳定性 |
| **preflight 加 provider routing 检查** | 工程 | **P1** | 005 的踩坑直接对应到 FATAL，避免再次浪费一次跑 |
| **B3 rolling summary 结构化伏笔表** | 创作质量 | **P2** | 需要数据迁移，建议在 debate / write 真模型跑出"伏笔丢失"样式后再做 |
| **真模型 write + review** | 验证 | **P2** | 一次写一章 ≈ 7 次 review，先 debate 再 write |
| **C2 增量 compress** | 工程 | **P3** | 当前不是瓶颈；单次 compress 仅 1 次调用 |
| **加权投票 / veto** | 创作质量 | **P3** | 005 多数决跑顺后再考虑给"伏笔猎人 / 世界观守门人"加权 |
| **轻量 dashboard / TUI** | 体验 | **P4** | 报告确实变多了，但目前 CLI 还顶得住 |

## 阶段 3 起点的判断标准

阶段 2 完成的标志（提前定义，避免"无止境工程"）：

- 真模型小样本至少跑通 **debate + 1 章 write + review**
- 知道真模型下首次重大翻车的具体样式（伏笔丢失 / 角色 OOC / JSON 失败 / context 撞墙 / 风格 AI 腔）
- 至少有 1 条**基于真模型样本**的结构性改造记录（B3 / 加权投票 / 风格 lint 加强 / chunk 边界回避 / ……）
- 跑完整 18 章续写一遍的成本和耗时被实测

到那个点，阶段 3 才考虑"批量产出 + 内容质量打磨"。

---

**备注**：本文件作为里程碑回顾，不参与 iteration 自然编号；阶段 2 完成后另起 `stage_02_summary.md`。所有原子迭代记录仍在 [docs/iterations/](./iterations/) 下按数字顺序。
