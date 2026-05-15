# 阶段 2 小结：真模型 Debate → 首章 Write/Review 收口

> 覆盖范围：[iteration 006](./iterations/iteration_006_debate_real_smoke.md) - [iteration 008](./iterations/iteration_008_write_smoke_and_ballot_repair.md)
> 时间窗：2026-05-14 至 2026-05-15
> 阶段定义：从真模型 debate 联调到首次 DeepSeek 写作 + 7 reviewer 审查跑通，确认阶段 3 的质量改造入口。

## 阶段目标回顾

阶段 1 已证明 extract 小样本能跑通，但 compress / debate / write / review 仍主要停留在 mock 路径。阶段 2 的目标不是立刻产出可发布章节，而是把 DeepSeek 真模型链路拉到可观测、可恢复、可讨论的状态：知道模型在哪些 JSON 约束上失手，知道 debate 投票是否能形成多数，知道首章 write/review 的真实质量问题。

阶段末达成的定义是：真模型至少跑通 `debate + 1 章 write + review`，并留下可复盘的日志、snapshot、review issue 和阶段 3 质量方向。

## 已交付能力（阶段累计）

### 真模型执行入口

```bash
python3 main.py preflight
bash scripts/debate_smoke.sh
bash scripts/write_smoke.sh
python3 main.py estimate-cost
```

### 工程加固

- `python3 main.py preflight` 会在真模型前检查 LiteLLM provider routing，裸 `deepseek-chat` 会 FATAL，正确配置为 `deepseek/deepseek-chat`。
- `python3 -m unittest discover -s tests` 与 `bash scripts/verify.sh` 均强制 mock，避免 `.env` 污染测试并误烧真模型额度。
- Debate ballot 从 prompt-only 约束升级为 repair layer：缺 `position` 时可从 alias 字段或 `reason` 推断。
- Reviewer JSON 输出缺 `agent_name` 时会在本地 repair 后再交给 `AgentReview` 校验。
- Writer 对 Reject / lint-failed draft 不再只留截断 preview，而是完整写出 `chapter_XX.md`，并在 meta 标 `needs_human_review=true`。
- Debate 与 draft smoke 都有 snapshot 目录，避免后续 mock verify 覆盖真模型产物。

### 数据 / 产物

- 真模型 extract 小样本：2 章，来自 iteration 005，是阶段 2 继续验证的基础输入。
- 真模型 compress：1 次，用于 write smoke 前刷新 `data/knowledge_base/`。
- Debate smoke：多轮 mock + real 混合；真实重点样本为 iteration 006、007、008 三次。
- 真模型 write：1 章，最终 `chapter_01.md` 1825 字。
- 真模型 review：1 章 × 7 reviewer，最终 16 条结构化 issue。
- 最新关键 snapshot：`outputs/drafts/snapshots/20260514_220808/`。

## 验证状态（阶段末）

| 项 | 状态 |
|---|---|
| 单测 | ✅ 86 / 86（iteration 008 收尾） |
| `bash scripts/verify.sh` | ✅ 退出码 0，新增 LLM rows 为 mock |
| `python3 main.py preflight` | ✅ warn，0 FATAL |
| Debate ballot | ✅ iteration 008 真模型 6/6 non-fallback |
| Write sample | ✅ `chapter_01.md` 1825 字，meta 完整 |
| Review sample | ✅ 7 reviewer，16 structured issues，最终 Reject |
| Extraction failures | ✅ 0 |
| Secret scan | ✅ 无新增真实 key；历史说明文字命中已知且非 key |

## 关键数字

| 指标 | 值 | 来源 |
|------|----|------|
| DeepSeek 总记录 | 492 | `logs/llm_calls.jsonl` 中 `model=deepseek/deepseek-chat` |
| DeepSeek 成功调用 | 344 `ok` | 同上；148 条 error 主要来自早期沙箱网络/本地拒错 |
| DeepSeek ok token | prompt 1,510,569 / response 365,016 | 同上，仅 `status=ok` |
| cache_read / cache_write | 29,312 / 1,481,257 | 同上，仅 `status=ok` |
| iteration 006 final real block | 48/48 ok，264,755 tokens | `iteration_006_debate_real_smoke.md` |
| iteration 007 final real block | 50/50 ok，287,875 tokens | `iteration_007_ballot_hardening_and_test_isolation.md` |
| iteration 008 measured block | 67/67 ok，prompt 319,183 / response 69,615 | `iteration_008_write_smoke_and_ballot_repair.md` |
| Ballot 完整率 | 0/6 -> 3/6 -> 6/6 | iterations 006 / 007 / 008 |
| 首章长度 | 1825 字 | `outputs/drafts/snapshots/20260514_220808/chapter_01.md` |
| Review 结果 | 4/7 Reject，16 issues | `chapter_01.meta.json` |
| 成本估算 | 约 $0.40-$0.80 | 按 DeepSeek-V3 低价/标准价口径和 ok token 估算；以控制台账单为准 |

## 工程教训（按真模型暴露顺序）

1. **LiteLLM provider 前缀（005-006）**：裸 `deepseek-chat` 在本地 LiteLLM 下无法解析 provider，必须使用 `deepseek/deepseek-chat`。已前移到 preflight FATAL。
2. **测试隔离不是“应该会”而是硬要求（007）**：直接 `unittest discover` 会绕过 package init，导致 `.env` 仍可能被读。已在 `tests/__init__.py`、`src/config.py`、`scripts/verify.sh` 三层隔离。
3. **Ballot prompt 失效分两层（006-008）**：先是 `{"ballots":[]}`，再是 near-correct JSON 缺 `position`。prompt 加硬只能解决一半，最终需要本地 repair/normalization。
4. **Reviewer / Writer 真实 JSON 不会完全服从 schema（008）**：reviewer 缺 `agent_name`、writer lint failure 不落完整草稿，都是 mock 不会自然暴露的问题。已修复。
5. **写作质量不是“链路跑通”的副产品（008）**：首章能写、能审、能出 issue，但用户评分 5/10。主要问题是没看过原文风格、时间锚点模糊、章节偏短、解释性台词重。这是 iteration 009 的主战场。

## 当前局限 / 已知 WARN

1. `tiktoken` 对 `deepseek/deepseek-chat` 无直接 encoding，仍回落估算；成本只作近似。
2. DeepSeek cache 行为混合：debate 多数 `cache_read_tokens=0`，write/review 出现少量 read；需要后续在 preflight 或 cost report 里解释。
3. 首章 `needs_human_review=true`，不是质量通过稿。它是阶段 3 的真实样本输入。
4. `scripts/write_smoke.sh` 在 008 第一次不是无中断成功，而是暴露 reviewer bug 后恢复完成。脚本本身已具备路径，但以后仍应关注 review JSON 稳定性。

## 阶段 3 双轴

| 轴 | 起点 | 近期目标 |
|----|------|----------|
| 写作质量轴 | iteration 009 | 风格样例注入、continuation anchor、长度约束、多一次 rewrite，把 5/10 拉到 7+/10 |
| 通用化轴 | iteration 011+ | workspace 目录隔离、多语言 splitter、agent persona 抽象、独立续作模式 |

阶段 3 不应先铺通用化。当前最短板是单书产出质量；先让龙族样本可读，再把能力抽象出去。

## 阶段 3 起点判断

阶段 2 到这里可以收口：

- 真模型 extract / compress / debate / write / review 均至少跑过样本。
- 真模型 JSON 失败模式已经有本地 repair 策略。
- 真模型写作样本有完整正文、meta、review issues 和 snapshot。
- 下一轮已经不是“能不能跑”，而是“怎样写得更像、写得更长、定位更清楚”。

下一步进入 iteration 009：Writing Quality Surge。
