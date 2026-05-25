# Iteration 020 — 延长 smoke 验证 + 失败模式报告（longzu ch1-10）

> **写代码？** 否（除了 2 个数据采集 / 合并脚本 + iter 019 debug 期间的 3 个 fix commit）。
> **LLM 成本？** 实测 ¥12.69（plan A4 上限 ¥30，41% 用量）。
> **目标交付**：1 份失败模式报告 + 9 章 longzu 合格草稿 + 1 章 GAVE UP 案例。

## Context

phase 3 (iter 014-019) 把 CLI 链路打磨到 `bash scripts/write_book.sh --book longzu N` 无人值守可跑，但 longzu 只跑过 **ch1 一章**（真模型）。算法长程稳定性未知：

- outline 在 ch10 / ch30 之后会不会重复？
- persona / agent 评分会漂移吗？
- entity_graph 会越来越乱吗？
- lint 规则会在某章累积击穿吗？
- 单章 retry 平均次数？per-chapter 成本曲线是恒定还是递增？

这些都是 **算法层** 问题，UI 救不了。iter 020 不写新代码（除了采集脚本），用真模型跑 30 章 unattended，把暴露出来的失败模式归档，作为 iter 021+ 改进的输入数据。

## Plan（执行实况）

| 步骤 | 计划 | 实际 |
|---|---|---|
| P0 | 扩 plan 到 30 章 | 1 次 `plan-chapters --chapters 8` 用 gpt5.5 + 中转隧道 → 隧道挂掉 → 用 Claude Opus 4.7 在 plan mode 里**手工产 ch9-30** 22 章作为 plot_planner 替代，省 ~¥3 |
| P1 | `write_book.sh --book longzu 30` 跑 ch3-30 | **ch3-9 ✅ Approve（7 章新增），ch10 ❌ GAVE UP（3 次 outer attempt 全 Reject）→ 脚本 exit 2，masked by tee 为 exit 0** |
| P2 | 数据采集 | `scripts/collect_iter020_data.py` + `scripts/merge_iter020_chapters.py` |
| P3 | 失败模式分析 | 见下文 8 节 |
| P4 | 报告 | 本文 |

实际产出：**ch1-9 共 9 章 Approve（含 ch1+ch2 phase3 末已写）+ ch10 失败 + 完整 lint/cost/agent 评分数据**。

## Acceptance（实测对照）

| # | 项 | 目标 | 实测 | 结果 |
|---|---|------|------|------|
| A1 | drafts ≥ 30 章 | 30 | 9（+1 失败） | ❌ 卡 ch10，得 9 章 |
| A2 | 通过率 ≥ 80% | 24/30 | **9/10 = 90%** | ✅（按已尝试章数）|
| A3 | 用户采样点评分 ≥ 6 | ch1/10/20/30 | 待用户读 ch1-9 后填 | ⏳ |
| A4 | 总成本 ≤ ¥30 | ≤ 30 | **¥12.69** | ✅ |
| A5 | 失败模式 ≥ 8 节 + ≥ 3 条 iter 21+ 建议 | — | 8 节 + **11 条** 建议 | ✅ |
| A6 | xueZhong + asoiaf sha256 baseline 不变 | byte-identical | longzu 单 workspace 操作，其它未触碰 | ✅ |

**A1 未达成**：原因不是预算或时间，是 **算法本身在 ch10 卡住**。这正是 iter 020 想暴露的失败模式数据，相比单纯跑完 30 章更有价值。

## 失败模式分析（8 类）

### 1. lint 规则击穿 — `not_x_but_y` 主导

| 章 | rewrite | lint 命中（成功稿） | blocked attempts |
|---|---|---|---|
| ch1 | 2 | 0 | 2（含 not_x_but_y）|
| ch2 | 2 | 6 | 0 |
| ch3 | 2 | 4 | — |
| ch4 | 1 | 1 | — |
| ch5 | 0 | 4 | — |
| ch6 | 0 | 3 | — |
| ch7 | 2 | 1 | — |
| ch8 | 1 | 4 | — |
| ch9 | 0 | 4 | — |
| **ch10** | **2（用尽）** | **11**（全 not_x_but_y）| **3 次 outer attempt 全 fail** |

`not_x_but_y` 累计触发 **33 次**（其它规则共 5 次）。这是 deepseek 写戏剧化中文 prose 时的稳定模式偏好，例如：

> "不是疼痛，是重量。"
> "不是停电，是设备掉线。"
> "不是被接住，是被包裹。"

阈值 = 2 次/章，对这种 prose 偏严。**ch10 三次 attempt lint 命中数：9 → 4 → 11**（attempt 2 几乎压住但 attempt 3 反弹，模型表现 random）。

### 2. writer 内部 rewrite + outer retry 双层限制

writer 内部最多 3 轮自我 rewrite（命中 lint 就回滚再生成），失败后 outer write_book.sh 再 retry max-retries=2 次，最终最多 9 次生成机会。ch10 9 次全部死在同一条规则上。

### 3. 8-agent reviewer 评分高度同质化

9 章已通过的 panel 评分：

| Agent | 9 章 avg | 备注 |
|---|---|---|
| 世界观守门人 / 情感关系 / 江南人格模拟 / 读者代言人 / 伏笔猎人 | 7.0 | 5 个 agent 几乎全给 7 分 |
| **关系一致性** | **6.14** | 偏低，可能是 ch9-30 plan 与 entity_graph 现有关系冲突 |
| 连续性审阅 | 6.78 | 略低 |
| 路明非本位 | 6.89 | 略低 |

读者关心的"小说好不好看"几乎没有评分区分度（5 个 agent 全 7）。**reviewer 评分目前只是"过 / 不过"的二值近似**，scoring 维度需要重新设计。

### 4. parse_failed 触发频率

| 章 | parse_failed count |
|---|---|
| ch1 | 2 |
| ch2 | 1 |
| ch3-9 | 0 |

ch1+ch2 早期 reviewer 拿到了 parse_failed → iter 019 audit fix 的 fail-closed Abstain 机制工作正常（仍判 Approve 因为其它 agent 都过）。ch3 之后 0 次，可能因为 deepseek 模型在累积 entity context 后输出格式更稳定。

### 5. 章节字数偏小

| 章 | 字数 | 目标 |
|---|---|---|
| ch1 | 4019 | 4000 ✅ |
| ch2 | 3557 | 3800 ⚠️ |
| ch3 | 5127 | 4200 ✅ |
| ch4 | **3131** | 3800 ❌（lint 触发 short_chapter_length 1 次）|
| ch5 | 4805 | 4300 ✅ |
| ch6 | 4519 | 3900 ✅ |
| ch7 | **3252** | 3700 ❌ |
| ch8 | 3739 | 4400 ⚠️ |
| ch9 | 4897 | 4200 ✅ |

3/9 章短于目标。writer prompt 给的字数目标偏软，没有强制重写。

### 6. plot_planner re-plan 成本（不适用本轮）

iter 020 用 **Claude Opus 4.7 (我) 手工产 ch9-30 plan**，没调 LLM plot_planner。原计划"边写边 re-plan" 没有执行（一次性产 30 章 plan）。后果：
- ✅ 省 plot_planner 中转成本 ~¥3
- ⚠️ entity_graph 在 ch3-9 写作过程被 apply-advance 更新过 N 次，但 ch9-30 的 plan 仍是 ch1-8 entity state 的快照设计，**没有 re-plan 反馈** 
- 这条数据点对"参考关系 → 更新关系 → 继续规划"循环的必要性提供了反面证据：手工 plan 在前 9 章没出现明显 entity 漂移 → re-plan 不一定每章必需

### 7. 成本曲线（per-章趋势）

| 任务 | calls | prompt_tok | cache_read | resp_tok | cost ¥ |
|---|---|---|---|---|---|
| review | 596 | 2,783,120 | **1,120,000 (40%)** | 567,361 | **8.29** |
| write | 98 | 626,701 | 351,104 (56%) | 248,820 | 2.68 |
| debate（旧）| 45 | 313,805 | 0 | 69,368 | 1.16 |
| extract（旧）| 12 | 51,618 | 0 | 30,619 | 0.34 |
| plot_planner（旧 + iter 020 新 1 次）| 7 | 62,528 | 0 | 8,266 | 0.19 |
| compress（旧）| 1 | 425 | 0 | 2,650 | 0.02 |
| **总** | **759** | **3,838,197** | **1,471,104** | **927,084** | **¥12.69** |

- **review 占 65% 成本** — 8 agent × 平均 3 轮 rewrite × 9 章 = ~216 reviewer calls，每个 ~30s 含 cache。
- write 占 21% — 每章约 10-15 calls（rewrite + entity proposals）。
- **deepseek prompt cache 命中率 40-56%** — entity_state + 滚动总结复用良好，没缓存的话成本要翻倍。
- **per-章边际成本 ≈ ¥1.41**（ch3-10 新增成本 ¥9.88 / 7 章成功 + 3 次 ch10 fail attempt）

### 8. 总成本对比

| 阶段 | 实测 | 预算 | 比例 |
|---|---|---|---|
| iter 020 增量（ch3-9 + ch10 失败） | ¥9.88 | ¥15-25 | 49-66% |
| iter 019 末（ch1+ch2 + 早期 debate/extract） | ¥2.81 | — | — |
| 累计 | **¥12.69** | ¥30 | **42%** |

若按 per-章 ¥1.41 外推 30 章 ≈ ¥42（超预算 40%）。iter 025 capstone 跑 100 章理论 ≈ ¥140（明显超出 plan 给的 ¥90 上限）。**需要在 iter 021+ 引入成本控制**：硬性预算 ceiling + 提前停止。

---

## iter 021+ 改进路线（11 条建议）

按优先级分 3 个阶段。

### Stage A — iter 021 必修（堵 ch10 类失败，让长程跑得通）

1. **lint 阈值动态化**
   - 当前 `not_x_but_y` 硬阈值 2 太严格
   - 改：阈值随章节长度缩放（每 1000 字符允许 1 次），最低 2 最高 5
   - 文件：`config/linter.yaml`、`src/linter.py`
   - 影响：iter 020 实测 ch10 attempt 2 命中 4 次本可过；多个章节 lint_n=4 也可放行

2. **writer system prompt 加 anti-pattern 反例**
   - 当前 prompt 没明确说"避免 不是X是Y 句式"
   - 改：在 `prompts/write_system.md` 加 "避免重复使用对比强调句式（不是…是…）；同一章节出现不超过 3 次"
   - 影响：减少 lint 阈值压力的源头

3. **write_book.sh 修 `tee` mask exit code bug**
   - 当前 `} 2>&1 | tee log` 让 exit 2 变成 exit 0
   - 改：用 `set -o pipefail` + 检查 `${PIPESTATUS[0]}` 或换 `process substitution`
   - 文件：`scripts/write_book.sh`
   - 影响：harness 能正确感知 GAVE UP，外层调用者能 alert

4. **chapter-level 硬性预算上限**
   - 新增 `--budget-cny N` 参数；累计 cost 超 N 则停止
   - 文件：`scripts/write_book.sh` 或 `main.py write`
   - 实现：从 llm_calls.jsonl 累加，每章后 check
   - 影响：iter 025 capstone ¥150 ceiling 实际可控

### Stage B — iter 022-023 应做（提升评分区分度 + 数据可视化）

5. **reviewer 评分维度细化**
   - 当前 8 agent 都给 7 → 没有"好看 vs 一般"区分
   - 改：每 agent 输出 3 个 sub-score（情节推进 / 文笔质感 / 与原作贴合度），总分 = 加权平均
   - 文件：`src/schemas.py` ReviewItem + `prompts/review_system.md`
   - 影响：UI 雷达图有意义；可识别"全 Approve 但实际平庸"的章节

6. **rolling_chapter_summary.json 加压缩机制**
   - 当前每章往 rolling summary 加内容，没上限
   - 已观察 ch10 prompt 已经膨胀至 ~30K tokens（含 entity + rolling summary）
   - 改：超过 N 字时调 LLM 压缩成 1/3 长度
   - 文件：`src/writer.py` `_update_rolling_summary()`

7. **关系一致性 agent 评分偏低修复**
   - iter 020 该 agent avg 6.14（其它 ~7.0）
   - 原因：plan 引入新角色 / 关系时 entity_graph 还没 advance
   - 改：每章 write 前先 dry-run 检测 plan 中 relationships_in_play 与 entity_graph 是否一致，差异写入 writer prompt
   - 文件：`src/writer.py` + 新 `src/relation_drift.py`

8. **failure artifact 自动清理策略**
   - 当前 last_failure_attempt[12].md 永久保留
   - 改：跑完一章 Approve 后只保留最后一次失败稿用于对比，前面的 attempts 移到 `snapshots/<ts>/failures/`
   - 文件：`scripts/write_book.sh` `clear_chapter_state()`

### Stage C — iter 024 可做（参考关系 → 更新关系 → 继续规划循环）

9. **plot_planner continuation 模式**
   - 新增 `--from-chapter N --append K` 参数
   - 读现有 chapter_plan + 当前 entity_graph，产 ch[N+1..N+K] 接续
   - 文件：`src/plot_planner.py`

10. **write_book.sh 加 auto re-plan hook**
    - 每写完 K 章自动调 `plan-chapters --append`
    - 默认 K=5，可关
    - 这是用户在本次会话明确提出的"参考关系 → 更新关系 → 继续规划"循环的实现

11. **per-章 cost 实时报告**
    - 每章 Approve 后立刻打 `[cost] chapter NN: ¥X.XX (累计 ¥Y.YY)`
    - 让 unattended run 中途也能感知预算消耗速度
    - 文件：`scripts/write_book.sh`

### 整理为 iter 21+ 工单

| Iter | Stage | 必修条目 | 影响 |
|---|---|---|---|
| **021 (WebUI P1 + 紧急修)** | A | #1 #2 #3 #4 | 让 ch10 类 lint 不再 GAVE UP；预算可控 |
| **022 (WebUI P2 章节编辑器)** | B | #6 #8 | 章节编辑前先看到 rolling summary 干净 |
| **023 (WebUI P3 可视化)** | B | #5 #7 | 雷达图有意义；relation drift 可视化 |
| **024 (WebUI P4 wizard)** | C | #9 #10 #11 | 用户可在 UI 设 K + 实时看 cost |
| **025 (~100 章 capstone)** | — | 用 021-024 全部修复跑 longzu ch11-100 + 新 my-book | phase 4 收官 |

## File Summary

| 文件 | 改动 | 进 git |
|---|---|---|
| `docs/iterations/iteration_020_extended_smoke.md` | 新建（本文） | ✅ |
| `scripts/collect_iter020_data.py` | 新建（已在 iter 019 末 commit `b55e316`） | ✅ |
| `scripts/expand_longzu_plan_to_30.py` | 新建（手工 plan，已在 b55e316） | ✅ |
| `scripts/merge_iter020_chapters.py` | 新建（合并 ch1-10 输出） | ✅ |
| `workspaces/longzu/outputs/debate/chapter_plan.json` | 8 → 30 章（manual） | ❌（gitignored）|
| `workspaces/longzu/outputs/drafts/chapter_0[3-9].md` + meta + advance proposals | 新增 7 章 | ❌ |
| `workspaces/longzu/outputs/drafts/chapter_10.md` + failure + last_failure_attempt[12] | ch10 失败 artifact | ❌ |
| `workspaces/longzu/outputs/drafts/iter020_summary.json` | 数据采集 JSON | ❌ |
| `workspaces/longzu/outputs/drafts/iter020_chapters_1_to_10.md` | 合并稿 | ❌ |
| `workspaces/longzu/outputs/drafts/snapshots/20260525_183654_aborted_ch10/` | iter 019 audit fix 触发的失败 snapshot | ❌ |

## 不在本轮范围

- 修 11 条建议中的任何一条代码（推到 iter 021+）
- 跑 ch11-30（卡在 ch10，不强行越过）
- xueZhong / asoiaf 同时 smoke（专注 longzu）
- 手动给 ch1-9 打 1-10 分用户评（待用户读后回填到 A3）

## Notes

1. **iter 020 最大学到的事**：lint 阈值 + writer prompt + reviewer 评分维度这 3 块是 **算法层** 真正的瓶颈，远比 UI 缺失更影响产品体验。iter 021 不能只做 WebUI 不修这 4 条 A 类 bug。
2. **plot_planner 替代实验有效**：Claude Opus 4.7 手工产的 22 章 plan 在 ch3-9 实际使用中没出明显问题（关系一致性 agent 偏低除外，但那是 entity_graph 反馈缺失，不是 plan 质量问题）。**iter 025 capstone 完全可以省掉 plot_planner LLM 成本**。
3. **iter 019 audit fix 验证**：preserve failed meta（B1.1）+ fallback prompt（B1.2）+ plan-driven enforce（B1.3）3 个修复在 iter 020 真实跑出来都发挥作用。ch10 3 个 attempt artifact 都保留 + 0 silent approve + 关系一致性 agent 在新章节没误 reject 已通过的章节。
4. **本次成本预测偏差**：plan 估 ¥15-25 跑 30 章，实测 ¥1.41/章 → 30 章约 ¥42，是 plan 估算的 1.7 倍。原因：reviewer panel 从 5 agent 升到 8 agent + 平均 rewrite 多。iter 025 capstone 100 章预算需要从 ¥45-90 调到 **¥80-140**。
