# iter041 Reviewer Reject 根因诊断

## 0. 用户人眼判断

用户快读 `workspaces/longzu/outputs/drafts/chapter_02.md` 后认为 draft 质量“还不错”，本轮优先怀疑 reviewer 层，而非先归因 writer 质量崩坏。

## 1. Agent panel Reject 解剖（表）

| Agent 名 | verdict | 关键 critique 摘录（最多 3 句） | Reject 理由分类 |
|---|---|---|---|
| 主角本位 | Approve | 主角主动性成立；但“召唤拒绝型”、高于诺玛权限、夔门坐标揭示偏直白。 | 非 Reject；B/D |
| 角色关系一致性 | Approve | 3E 像普通英语听力；高于诺玛权限未交代来源；诺诺判断略接近读心。 | 非 Reject；D/C |
| 伏笔猎人 | Approve | “召唤拒绝型”过早固化谜团；夔门坐标直发 N96 需确认不冲突后续调度。 | 非 Reject；B/D |
| 世界观守门人 | Approve | 3E 机制需明确；手机收到高权限任务需解释来源；芬格尔潜入略显安保松动。 | 非 Reject；D |
| 原作风格模拟 | Reject | 连续抛“召唤拒绝型 / 高于诺玛权限 / 夔门”，留白被削薄；教授争论像说明书；诺诺台词导师化。 | A 为主，兼 C/B/D |

## 2. Hallucinate 率

仅 1 个 Reject agent：`原作风格模拟`。其 7 条具体指控均可在 draft 中 grep 到 anchor：`召唤——拒绝——型`、`来源权限：高于诺玛当前显示级别`、`夔门`、教授脑电图台词、诺诺劝诫、S 级奖状式内心总结、密集吐槽比喻、芬格尔异常索引情报。汇总：1 agent 共 7 条具体指控，真实且可成立 5 条，hallucinate 0 条，存在但 reviewer 价值判断偏严/误读 2 条（诺诺导师化、路明非内心总结）。结论：不是凭空幻觉，而是抓到真实文本后按风格 veto 过严。

## 3. 系统性偏见

`原作风格模拟`是最敏感 agent，但不是固定 Reject。`longzu` ch1-ch9 中，它对 ch1/ch2/ch3 Reject，对 ch4/ch6/ch7/ch8 Approve，对 ch5/ch9 也 Approve（即使 overall Reject），分布约 3 Reject / 6 Approve。`iter029_beta_ok` 基线有限：ch1 Approve 但 `agent_reviews=[]`；ch2 有 panel 但 overall Reject。可见偏见类型是“对直白解释、过密比喻、AI 式风格模仿高度敏感”。

## 4. 基线对比

| 维度 | longzu ch2 Reject | longzu ch4 Approved | longzu ch6 Approved |
|---|---:|---:|---:|
| panel 票型 | 4A/1R | 5A | 5A |
| 总 issues / major | 28 / 12 | 24 / 5 | 29 / 5 |
| `原作风格模拟` | R，7 issues，4 major | A，5 issues，2 major | A，6 issues，2 major |

critique 长度不是主差异：ch2 总 message 字数 1651，ch6 1657。最显著差异是 ch2 的 major 密度翻倍，且集中在唯一 Reject agent；现有聚合规则任一 substantive Reject 即 overall Reject，所以 4/5 通过仍被一票否决。

## 5. Context 输入

meta 与 review 的 `run_context` 一致：`start_chapter_id=longzu_3_3_ch024`，三类 fingerprint 均匹配 plan。`longzu` 也有可用参考：起点前三章可组成 8000 字上下文，`source_excerpts` 有 12 条 metadata。但外部 `review_target()` 只把 `run_context/draft_sha256` 传给 `review_text()`，没有传 `knowledge/source_chapters/scene_excerpts`；这些只在 writer 内嵌 review 路径传入。日志不存 prompt 原文，只能看 hash/token；旁证是 source-rich review 常见 33k-34k chars，最终 external review 仅 16k-17k chars。因此最终判 Reject 的 reviewer 很可能没有拿到真正龙族原文风格参照。

## 6. 结论 + 修复方向候选

判断：draft 有真实可改短板（信息揭示偏直、系统标签偏硬、幽默密度偏满），但不足以证明 writer 差到应被 4/5 panel 否决。根因优先级是 reviewer 输入/聚合层：external review 漏传原文参照后，由 `原作风格模拟` 触发 fail-closed veto。

推荐 F3：Source context 输入修复。证据：§5 数据存在但调用点漏传；最终 prompt 体量约为 source-rich review 的一半。工作量：中。风险：低，主要是成本和 prompt 变长。

推荐 F1：调优 `原作风格模拟` prompt。具体问题：允许输出 major，但只有原文对照后确认风格硬伤/人物 voice 阻断才 Reject；对密度、留白、台词端正等主观项默认 Approve+major。工作量：轻到中。风险：中，过松会漏真 AI 腔；建议配合 F3 做，暂不优先放宽 panel 阈值。
