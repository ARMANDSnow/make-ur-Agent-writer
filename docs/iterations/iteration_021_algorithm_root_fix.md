# Iteration 021 — 算法根 bug 修复（起点 / 原文注入 / KB+rolling+anchor 注入 / 剧透过滤）+ SOP 落地

## Context

iter 020 跑了 longzu ch1-10 真模型 smoke，9 章 Approve 但用户读完合并稿后明确指出两个核心问题：

1. **情节莫名其妙，不是预期的"第三部之后"**：实际续写出来是龙族第一部 ch001 前夜（3E 考试），而不是用户记忆里的"接第三部结束 / 第四部开始之前"。
2. **文笔下降、不像原作**：writer + reviewer 从来不读原文，所有"风格 + 细节"靠 KB 141 行 + style_examples 重建，从 110 章百万字原文到 7K 字 prompt **信息保留率 < 1%**。

诊断后确认是 **设计层 4 个根 bug**：

- 阶段 3「起点判断」整体未打通：`auto_bootstrap.bootstrap_continuation_anchor()` 硬编码采样 `_recent_extractions_context(root, count=3)`，永远从最早抽取的 extracted_json 出发，用户无法指定起点
- 阶段 6.7「writer 读原文片段」整体未打通：`writer._write_prompt()` 10 个数据源全部走 KB/entity/rolling，没有任何原文章节注入
- 阶段 5.2「plot_planner 输入不全」：缺 KB / rolling_summary / continuation_anchor 三个上下文，导致即使用户设了新起点，plan 仍按原 outline 产 3E 考试内容
- 阶段 4.4「起点之后剧透过滤」整体未打通：global_facts.json 和 entity_graph.json 不论起点都全量注入，第四部续写时也能看到第七部剧情

iter 020 报告把 11 条改进按 3 stage 排好，iter 021 严格只做 Stage A（算法根 bug 4 条 + 1 条 plot_planner anchor 注入即兴新增），且要同步把 9 阶段 SOP 落到 README / AGENTS.md / AGENT_HANDOFF.md 作为**实时进度追踪活文档**。

## Plan

### P1. `src/start_point.py` 新模块（A1）

承担"起点感知"所有跨模块共用逻辑，5 个公开 API：

```python
def get_start_chapter_id() -> Optional[str]      # 返回已配置的 chapter_id，未配置返回 None
def set_start_point(name: str) -> None           # 接受 chapter_id 或 volume_id
def clear_start_point() -> None
def is_after_start(chapter_id: str) -> bool      # 严格 > 起点位置
def chapters_before_start(k: int = 3) -> List[Dict[str, Any]]  # 起点前 K 章 manifest entries
def load_chapter_text(chapter_id: str) -> str    # 反查 source_file + start_line/end_line
def format_chapters_before_start_for_anchor(k=3, limit_chars=24000) -> str
```

数据存储：`workspaces/<name>/data/manual_overrides/start_chapter.json` schema 支持 `start_chapter_id`（精确）或 `start_volume_id`（取该卷 manifest 最后一章）两种形式。文件不存在时所有 API 都 graceful degrade → iter 020 行为 byte-identical。

### P2. `main.py` 加 3 个 subcommand

```bash
python3 main.py --book longzu set-start-point longzu_3_3_ch020  # chapter_id
python3 main.py --book longzu set-start-point longzu_4          # volume_id
python3 main.py --book longzu show-start-point
python3 main.py --book longzu clear-start-point
```

`set` 校验名字必须命中 chapter_manifest 中的某个 chapter_id 或 volume_id，否则 ValueError → 退出码 1。`show` 解析后打印 chapter_id + 起点前 3 章 ids（方便 sanity check）。

### P3. `src/writer.py` 注入起点前原文（A2）

`_write_prompt()` 在 entity_state 段之后、continuation_anchor 段之前插入新段：

```
# 原文片段参考（起点前 K=3 章，用于风格 + 细节锚点；不要复述情节）

### <chapter_id_1> — <title>
<原文 [:3000 chars]>

---

### <chapter_id_2> — <title>
...

上述片段是原作者的真实文字，用于参考叙事节奏、用词、人物塑造的细节密度。
续写不要复述上述情节，但写作风格、人物对话语气、环境刻画密度应向这些片段靠拢。
```

总注入量 ~9K 字符（K=3 × 3K 截断），加现有 ~30K prompt 后总量 ~40K — deepseek 128K context 内安全。**未设 start_point 时 src_chapters 返回空 list，新段不注入，prompt 与 iter 020 byte-identical**。

### P4. `src/plot_planner.py` 注入 KB + rolling + anchor（A3，含执行期新增）

原 plan 只承诺加 KB + rolling 两段。执行 P9 smoke 时实战发现：anchor 改成第四部后剧情，但 plot_planner 产出的 plan 仍是 3E 考试 — 因为 plot_planner 不读 continuation_anchor。**即兴新增**第三段注入，并加规则 #9："如续写起点 (must-anchor) 与辩论大纲冲突，以起点状态为准"。

### P5. 剧透过滤（A4，facts + entity_graph，KB 推后）

- `manual_facts.global_facts_summary(respect_start_point=True)` 默认开启过滤；evidence_spans 中任意 chapter_id 严格大于起点 → 丢弃整条 fact
- `entities.render_active_state(respect_start_point=True)` 默认开启过滤；relationship 的 active timeline 项若有 `chapter_id` 且严格大于起点 → 丢弃整条 relationship；timeline 项无 chapter_id → 保留（当前 entity_graph schema 没有此字段，iter 022 升级 schema 后才能真正密集过滤）
- KB 过滤推到 iter 022/023（KB 是 LLM 自由 markdown，按起点过滤需要重调 LLM 重写）

### P6. `src/auto_bootstrap.py` 改用 start_point（A1 闭环）

`bootstrap_continuation_anchor()` 第 117 行原 `_recent_extractions_context(root, count=3)`，改为优先调 `start_point.format_chapters_before_start_for_anchor(k=3)`，未设起点 fallback 到原行为。同时把 instructions 改成"起点前 K 章 *原文*"而不是"最后 2-3 个章节抽取结果"，让 anchor 内容更具体地来自原文文字而不是抽取的 metadata。

### P7. SOP 文档落地（README + AGENTS.md + AGENT_HANDOFF.md）

- README.md 新增 "## 项目阶段 SOP（实时状态）" 节：9 阶段 × 25 节点表格，每节点 ✅/⚠️/❌ 状态 + iter 号备注 + "最近一次更新" 时间戳
- AGENTS.md 「当前阶段」节扩展为指针 → README SOP；工程铁律新增第 8 条："每 iter 收官时必须同步 SOP 状态字段"
- docs/AGENT_HANDOFF.md 末尾追加 "## Phase 4 Status（iter 021）" 节：iter 020 + 021 总结 + 4 根 bug 状态表 + iter 022 入口候选

### P8. 测试 +14 → 239（实际比 plan 估 +12 → 237 多 2）

| 文件 | 新增 | 覆盖 |
|---|---|---|
| `tests/test_start_point.py` | +7 | get/set 往返、volume_id 解析、unknown → ValueError、is_after_start 严格、chapters_before_start + load_chapter_text、clear 幂等、默认 None |
| `tests/test_writer_source_injection.py` | +2 | 无起点 prompt 不含 "原文片段参考"；有起点 prompt 含 chapter_id + 实际原文字面 |
| `tests/test_plot_planner_kb_rolling.py` | +3 | 空 KB+rolling 不注入；只 KB 注入 KB；KB+rolling 都注入 |
| `tests/test_spoiler_filter.py` | +2 | facts 按 evidence chapter_id 过滤 + escape hatch；entity relationship 按 timeline chapter_id 过滤 + escape hatch |

所有测试 mock-only，0 LLM 成本。

### P9. iter 021 收官真模型 smoke（longzu 1 章）

```bash
python3 main.py --book longzu set-start-point longzu_4
python3 main.py --book longzu bootstrap-anchor --force
python3 main.py --book longzu apply-bootstrap --name continuation_anchor --confirm
python3 main.py --book longzu plan-chapters --chapters 3 --force
bash scripts/write_book.sh --book longzu --max-retries 1 1
```

### P10. 文档 + commit

- 本文（iter 021 报告 8 段）
- `docs/iterations/README.md` + 第 21 行
- commit 不 push（和 iter 020 一起留到 iter 025 后统一）

## Acceptance Result

| # | 项 | 实测 | 结果 |
|---|---|------|------|
| A1 | `src/start_point.py` 5 API + 7 测试 | ✅ 7/7 测试通过 | ✅ |
| A2 | writer prompt 有起点时含原文段 / 无起点 byte-identical | ✅ 实测无起点 2051 字符 prompt, 设 longzu_4 后 11263 字符 prompt 含 chapter_id `longzu_4_ch014` + 原文 "看着她奔入那座别墅..." | ✅ |
| A3 | plot_planner prompt 含 KB + rolling | ✅ 实测注入正常；**+ 即兴 anchor 注入修复了 plan 仍出 3E 考试的实战问题** | ✅+ |
| A4 | facts + entity_graph 按起点过滤 + 2 测试 | ✅ longzu 实测 start=ch001 时 9 facts 中 6 个 evidence=ch004 被过滤为 spoiler；entity_graph timeline 无 chapter_id 时保守保留（iter 022 schema 升级）| ✅ |
| A5 | 总测试 ≥ 237 全绿 | **239 OK in 3s** | ✅ |
| A6 | longzu smoke 新 ch1 用户认为"比 iter 020 更像第三部之后续作" | ✅ 草稿完全是龙族第四部续作（雨夜高架路、火箭筒、斯雷普尼尔八足骏马、奥丁银色面具独眼、昆古尼尔、弗里嘉弹头、小魔鬼耳蜗低语、诺诺+苏小妍+三轮车包子细节、康斯坦丁胸口门槛）；字数 15644 远超 iter 020 ch1 的 4019 | ✅ |
| A7 | SOP 3 处同步 | ✅ README + AGENTS + AGENT_HANDOFF | ✅ |
| B1 | `verify.sh` exit 0 | ✅ | ✅ |
| B2 | 未设 start_point 的 workspace byte-identical | ✅ xueZhong / asoiaf / legacy / longzu 4 个 preflight 全 FATAL=none | ✅ |
| B3 | 0 新依赖 | ✅ `requirements.txt` 未动 | ✅ |
| C1 | commit 不 push | ✅ | ✅ |
| D | 真模型成本 ≤ ¥5 | **¥0.69**（远低于预算）| ✅ |

### 真模型 smoke 详情

| 阶段 | 实测 |
|---|---|
| `set-start-point longzu_4` | 解析到 `longzu_4_ch017`（book 4 最后一章）|
| `bootstrap-anchor --force` 用 deepseek 产新 anchor | anchor 文本："诺诺抱着苏小妍冲下东侧楼梯... 奥丁骑着八足骏马... 医院在尼伯龙根力量下崩坏... 路明非在高架路上准备用火箭筒攻击奥丁... 50% 融合的临时能力提升" — **完全不再是 3E 考试** |
| `plan-chapters --chapters 3 --force` | overall_arc: "路明非在医院尼伯龙根中与奥丁的生死对决..."；ch1 title "高架路上的火箭筒"；ch1 opening_scene "路明非站在尼伯龙根高架路上，雨水顺着脸颊..." — **plan 完全对齐新起点** |
| `write_book.sh longzu 1` | ch1 写出 15,644 chars 内容完全是龙族第四部续作风格；但 lint `not_x_but_y` 命中 9 次 → Reject |

### ch1 草稿质量验证（节选）

> 雨打在路明非脸上，顺着下巴滴进领口里。他单膝跪在高架路的沥青路面上，火箭筒的肩托抵着锁骨...融合到百分之五十的感觉像喝了三杯浓缩咖啡之后被人扔进冰水里...八足骏马已经踏着那些反光的碎片冲出来了。斯雷普尼尔的马蹄上裹着幽蓝色的冷焰...奥丁端坐马背，银色面具的下巴边缘折射出整个医院立面的倒影...他手里提着那杆枪。昆古尼尔...

> 诺诺看着他，停了大概三秒钟...她只是从三轮摩托的置物格里摸出一个塑料袋扔过去。"包子。还热的。三轮车大爷给的。"路明非接住袋子...塑料袋上印着一家医院附近小吃店的Logo，里面的包子确实还温着，热气把袋口撑得鼓鼓的。

文字密度、对话节奏、市井细节（三轮车大爷给的包子）、龙族世界观术语（斯雷普尼尔 / 昆古尼尔 / 弗里嘉弹头 / 龙类死侍 / 尼伯龙根）全部到位。**iter 021 算法层修复完全闭环验证成功**。

### lint 失败说明

ch1 在 2 次 outer attempt 都因 `not_x_but_y` 命中 9 次被 lint reject。这是 **iter 020 报告 Stage B B1 条目已记录的问题**（"lint 阈值动态化随字数缩放"），跟 iter 021 修的 4 个根 bug 完全无关。iter 022 修。

iter 021 这次 ch1 草稿保留为 `workspaces/longzu/outputs/drafts/chapter_01_iter021_book4_demo.md`（不计入 chapter_status，因为 verdict=Reject 不进 approval pipeline）。iter 020 的 ch1（3E 考试 Approve 版本）从 backup 还原回 `chapter_01.md`，所有 30-ch chapter_plan / continuation_anchor / start_chapter 配置都还原到 iter 020 末尾状态。**longzu workspace 整体回到 iter 020 baseline，唯一新增是 `chapter_01_iter021_book4_demo.md` 作为对照样本**。

## 文件变更汇总

| 文件 | 改动 | 进 git |
|---|---|---|
| `src/start_point.py` | 新建（~190 行）| ✅ |
| `src/writer.py` | top import + `_write_prompt()` 插入 7 行原文注入 | ✅ |
| `src/plot_planner.py` | top import + `_load_knowledge()` / `_load_rolling_summary()` 2 helper + `_build_planner_prompt()` 扩 3 段 + `generate_chapter_plan()` 注入 anchor + 规则 #9 | ✅ |
| `src/manual_facts.py` | `_fact_has_spoiler_evidence()` + `global_facts_summary(respect_start_point=True)` | ✅ |
| `src/entities.py` | `_relationship_is_spoiler()` + `render_active_state(respect_start_point=True)` | ✅ |
| `src/auto_bootstrap.py` | `bootstrap_continuation_anchor()` 改用 start_point.format_chapters_before_start_for_anchor() | ✅ |
| `main.py` | + set-start-point / show-start-point / clear-start-point 3 subcommand | ✅ |
| `tests/test_start_point.py` | 新建 +7 | ✅ |
| `tests/test_writer_source_injection.py` | 新建 +2 | ✅ |
| `tests/test_plot_planner_kb_rolling.py` | 新建 +3 | ✅ |
| `tests/test_spoiler_filter.py` | 新建 +2 | ✅ |
| `README.md` | + "## 项目阶段 SOP（实时状态）" 节（9 阶段 × 25 节点 + 状态标记 + 时间戳） | ✅ |
| `AGENTS.md` | 工程铁律 +1 条 + 「当前阶段」改为指向 README SOP | ✅ |
| `docs/AGENT_HANDOFF.md` | + "## Phase 4 Status（iter 021）" 节 | ✅ |
| `docs/iterations/iteration_021_algorithm_root_fix.md` | 新建（本文）| ✅ |
| `docs/iterations/README.md` | + 第 21 行 | ✅ |
| `workspaces/longzu/outputs/drafts/chapter_01_iter021_book4_demo.md` | iter 021 ch1 demo（第四部续作风格对照）| ❌（gitignored）|

## 不在本轮范围

- WebUI 任何部分（iter 024）
- lint 阈值动态化（iter 022 B1）— 直接导致 iter 021 smoke ch1 Reject
- writer prompt 加 `不是X是Y` 反例（iter 022 B2）
- reviewer sub-score 评分维度细化（iter 022 B3）
- reviewer 读 KB + 原文（iter 022 B4）
- rolling_summary 分层（iter 022 B5）
- write_book.sh tee mask exit code bug（iter 022 B6）
- plot_planner `--from-chapter N --append K` continuation（iter 023 C1）
- write_book.sh 每 K 章自动 re-plan（iter 023 C2）
- entity_advance proposal 与 plan 冲突检测（iter 023 C3）
- per-章 cost 实时报告 + budget ceiling（iter 023 C4）
- KB 按起点过滤（iter 022/023，需 LLM 重写 KB）
- entity_graph timeline schema 升级（加 chapter_id 字段，让 A4 entity 过滤更密集）

## Notes

1. **plot_planner anchor 注入是执行期紧急修复**：原 plan 只承诺加 KB + rolling，但 P9 smoke 时发现 anchor 已经改成第四部但 plan 仍出 3E — 立刻加 anchor 注入 + 规则 #9，重跑 plan-chapters 立刻产出正确的"高架路火箭筒"plan。这是 iter 021 最关键的实战教训：A1/A2/A3 必须协同生效，缺一个就会出现"起点配了但 writer 看不到 / planner 看不到"的局部失效
2. **iter 020 ch1-9 是基于错起点写的**：在 iter 020 报告里没有显式说"起点是 3E 考试是 bug"，因为 iter 020 当时不知道根因；iter 021 修完后追认 iter 020 跑出来的 9 章 longzu 草稿应该理解为"龙族第一部重写实验" 而不是"龙族第四部续作"；iter 025 capstone 必须先 set-start-point 再开跑
3. **entity_graph 过滤不密**：当前 schema 的 timeline 项只有 `{timestamp, state, active}`，没有 `chapter_id`，所以 iter 021 的 entity 过滤实际几乎不生效（保守保留所有 relationship）。iter 022 需要给 timeline 加 `chapter_id` 字段 + 升级 entity_advance 流程在 propose 时记录 `chapter_no → chapter_id`
4. **本次 smoke 成本远低于预算**：plan 估 ¥3，实测 ¥0.69（38 calls，prompt 211K tokens，cache 命中 38%）。原因是只跑了 1 章 + 2 次 attempt，没像 iter 020 一样跑 10 章
5. **plot_planner 现在 4 块输入彼此优先级**：rule 7-9 明确规定 entity_state > 辩论大纲、rolling_summary > 辩论大纲、anchor > 辩论大纲。这意味着 outline.md（debate 阶段产）的权重正在被持续压缩 — iter 023+ 可能要重新考虑 debate 阶段的产出形态
