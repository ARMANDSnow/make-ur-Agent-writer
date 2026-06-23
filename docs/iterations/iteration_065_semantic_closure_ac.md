# Iteration 065 - 语义闭环 a/c：计划履约 reviewer + entity 新建关系

## Context

Codex 一轮只读调研提 2×P1 + 4×P2，六条全部 confirmed。**iter064 已收 #1–#5**（CLI/Web 数值守门统一、outline_stale 出口统一、移动端 CSS 作用域、错误卡路径脱敏、workspace HTML pattern 单源）。剩下的 P2 #6「续写长程语义闭环」是 large 级核心写作循环改动，iter064 与用户确认推迟到 iter065+（见 `iteration_064_codex_findings_hardening.md` 末尾「不在本轮范围」）。

#6 三个子项：
- **(a) 计划履约 reviewer**：5 个 review agent 无一检查本章是否真的履约了 `chapter_plan_item.key_events`——writer prompt 写了「key_events（必须全部发生）」，但写完无独立校验，写手悄悄漏 beat 无人发现。
- **(b) outline drift 行为闭环**：`outline_drift` 只 warn 从不 block，过时 outline 长期烤进每章 prompt。
- **(c) entity 新建关系**：`entity_advance` 要求关系对预存在，否则 `relationship_not_found` 跳过；真模型续写常提图里没有的新关系对，被静默丢弃。

**本轮范围（与用户确认）**：只做 **(a) + (c)**——都是确定性 / 纯增量、默认行为字节级不变、mock 全可测、不引入新 serialized block 契约。**(b) 推迟 iter066**：它是三者中唯一把「原本能跑的长程 run」变成「中途拒绝」的改动（warn→block 在 `rolling_summary` 落后 drafts 时会误判 severe drift 而 block 健康 run），需配 driver/Web 级联的专项审查（铁律⑨ runner/gate 改动条款）。

## Plan

- **#6a（计划履约 reviewer）**：`src/reviewer.py` 新增确定性 `_plan_compliance_issues(draft, chapter_plan_item)`（中文字符 bigram 覆盖度判 beat 是否 missing），镜像 iter023 P5 `relationship_auditor`（`reviewer.py:480-518`）append synthetic agent `plan_compliance`。block 触发极保守（漏掉多数 beat 才 Reject，少数漏失只产 advisory）。`review_text()` 签名加 `chapter_plan_item=None`（末位默认），`writer.py:266` 传入。`chapter_plan_item is None`/无 key_events → 返回 `[]` 自跳过（字节级不变）。surfacing 全走现有 rewrite feedback + `retry_exhausted`，无新 kind/exit/status。
- **#6c（entity 新建关系）**：`apply_advance_proposals`/`_apply_selected`（`entity_advance.py:105/213`）加 `allow_creation=False`/`creation_confidence=0.85`，`rel is None` 分支（line 238）满足 conf 阈值 + 非 hard-conflict（复用 `proposal_validator._hard_conflict_markers`）时创建新关系，否则保留现有 skip。result 加 `created_count`/`created`。`config/agents.yaml` 加 `entity_advance.{allow_creation,creation_confidence}`（默认 false/0.85），`book_runner._auto_apply_advances` 透传。surfacing 走现有 `advances` 字段。

## Acceptance

- `OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests`：≥1250 + 新增，OK (skipped=6)。
- `OPENAI_MODEL=mock bash scripts/verify.sh`：exit 0。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：无 FATAL/WARN。
- (a) 回归门：`chapter_plan_item=None` → review.json 不含 plan_compliance agent；多数 beat 缺失 → synthetic Reject；单个改写 beat 仍命中 → 不误 block。
- (c) 回归门：`allow_creation=False` → 仍 skip（字节级不变）；`True`+conf≥0.85 → 新关系 append（anchor_chapter 格式正确）；conf<0.85 / hard-conflict → 拒绝。
- 收官 `/code-review high` + `/security-review`（+ (c) 数据文件改动的深度审查）结论回填本文件。

## Implementation Notes

**起轮**：先用 4 个只读 explore agent + 综合 agent 把 (a)(b)(c) 三处的现有行为、集成点、测试约定摸清，确认 iter064 已收 #1–#5，本轮唯一剩 #6。与用户确认范围 = (a)+(c)，(b) 推迟 iter066。

**Item (a) — 计划履约 reviewer（确定性建议级，非阻断）**：
- 镜像 iter023 P5 `relationship_auditor` 的「确定性后置」思路，但 **不是 synthetic 投票 agent**。新增 `_plan_compliance_misses(draft, chapter_plan_item)`：取每个 `key_events` 的中文字符 bigram 集合，命中率 < `COVER_THRESHOLD` 判「正文中几乎找不到」。`review_text()` 末位加 `chapter_plan_item=None`，`writer.py:266` 传入；`chapter_plan_item is None`/无 key_events/key_events 非 list → 返回 `[]` 自跳过（铁律④ 字节级不变）。
- **与计划的偏差（收官审查 P2 驱动，诚实记录）**：计划原写「漏多数 beat 才硬 block（synthetic Reject）」。收官对抗审查（对真实 `longzu/chapter_plan.json` 实测）证明：计划里的 beat 是 40–70 字名词密集句，被「忠实但戏剧化」换句后 bigram 命中率会掉到 0.1–0.4，硬 block 会**误拒忠实好稿、烧光 rewrite 预算**——正是我们把 (b) warn→block 推迟想避免的同一类误报。故**改为建议级**：把缺失 beat 作为 `_advisor="plan_compliance"` 的 rewrite_suggestion 喂进既有 `rewrite_suggestions` 通道（`_review_feedback` 的「改写顾问建议」段渲染，与 verdict 无关；写进 review.json），**永不翻转 verdict / 不 block**。阈值同步下调到 0.15（只点「基本没写到」的 beat，少打扰忠实改写）。

**Item (c) — entity 新建关系（confidence-gated CREATE，默认关闭）**：
- `apply_advance_proposals`/`_apply_selected` 加 `allow_creation=False`/`creation_confidence=0.85`；`_apply_selected` 的 `rel is None` 分支在 `allow_creation` 时按「非空 new_state + 非 hard-conflict + conf≥阈值」创建新关系，否则带具体 reason 跳过（`creation_empty_state`/`creation_hard_conflict`/`creation_below_confidence`）。`created` 经可选 mutable list 出参收集（保持 `_apply_selected` 2-tuple 返回 → 既有 4 处直接调用的测试字节级不变）。result 加 `created_count`/`created`，`applied_count` 减去 created（= 纯 advance 数，legacy 断言不破）。
- 上游 `book_runner._auto_apply_advances` 从 `config/agents.yaml` 读 `entity_advance.{allow_creation,creation_confidence}`（默认 false/0.85，读取/float 强转全包 try → 坏配置 fail-closed 回默认）。`anchor_chapter` 严格沿用 `f"续写第{chapter_no:02d}章"`（字节稳定）。

## Acceptance Result

**门禁（铁律③/④，必须 `.venv/bin/python3`；verify.sh 须 `PATH=$PWD/.venv/bin:$PATH` 否则裸 python3 缺 pydantic 173 import error 误判）**：
- `OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests`：**1269 tests OK**（基线 1250 + 19 新增；本环境非沙箱 skipped=0）。
- `OPENAI_MODEL=mock PATH=$PWD/.venv/bin:$PATH bash scripts/verify.sh`：**exit 0**。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：**FATAL none / WARN none**。
- (a) 回归：`chapter_plan_item=None`/全覆盖 → 无 plan_compliance 建议、verdict 不变；缺失 beat → rewrite_suggestion 出现且 **verdict 仍 Approve**（坐实非阻断）；非 list key_events → 自跳过。
- (c) 回归：`allow_creation=False` → 仍 `relationship_not_found` skip（字节级不变，`ApplyAdvanceSkipsMissingRelationshipTests` 全绿）；`True`+conf≥0.85+非空+非冲突 → 新关系 append（anchor 格式正确）；空 new_state→`creation_empty_state`；hard-conflict→`creation_hard_conflict`；conf<阈值→`creation_below_confidence`。

**审查（铁律⑨）**：3 维度（correctness/security-data/reuse-ironlaw）workflow + 对抗逐条核验，11 raw findings / 9 confirmed。本轮高风险（runner + 持久化数据文件改写）故按⑨拆多 agent 独立视角对抗审，未跑 ultra（需用户授权计费）。处置：
- **P2（已修）plan-compliance 硬 block 误拒忠实戏剧化好稿**（对真实 longzu 计划坐实）→ 改建议级，永不翻转 verdict（见 Implementation Notes 偏差）。
- **P2（已修）allow_creation 绕过 `_is_applyable_proposal`、空 new_state 建垃圾边** → 创建分支强制非空 new_state（`creation_empty_state`）。
- **P2→已修（reuse）`_hard_conflict_markers` 从派生副本导入** → 改从 canonical `relationship_auditor` 导入（杜绝双副本漂移）。
- **P3（已修）key_events 为字符串时逐字符误判** → isinstance(list/tuple) 守门。
- **nit（已修）`render_apply_advance_result` 不显示 created** → 加 created 行（CLI 暂未暴露 allow_creation，属前瞻补全）。
- **未修（诚实登记）**：confidence Infinity/NaN 写入 entity_graph.json 是 **iter065 前既有**风险（legacy advance 路径同样存在，非本轮引入；需 select_auto_indexes 已用 `>=` 过滤 NaN，Infinity 需手改坏 proposals 文件），按铁律⑦ scope 收敛顺延；plan-compliance bigram 是**粗略词法信号非语义履约判定**（长 beat 戏剧化换句会漏报，建议级已无 block 风险，局限登记在案）。
- 铁律①自查：diff 无新增 `sk-`/`.env`/key 读写路径；仅 `src/`/`config`/`tests`/`docs` 改动，未碰 `data/`/`outputs/`/`小说txt/`。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/reviewer.py` | **(a)** `COVER_THRESHOLD`/`_cjk_clean`/`_char_bigrams`/`_beat_coverage`/`_plan_compliance_misses`；`review_text()` 加 `chapter_plan_item` 参；advisor 段后把缺失 beat 作 `_advisor=plan_compliance` 建议入 `rewrite_suggestions`（非阻断） |
| `src/writer.py` | **(a)** 主 review 调用传 `chapter_plan_item`（shadow review 不传，诊断旁路） |
| `src/entity_advance.py` | **(c)** `apply_advance_proposals`/`_apply_selected` 加 `allow_creation`/`creation_confidence`；`rel is None` 创建分支（非空 new_state + hard-conflict + conf 三闸）；`created` 出参 + `created_count`/`created` result；`_hard_conflict_markers` 从 canonical `relationship_auditor` 导入 |
| `src/book_runner.py` | **(c)** `_auto_apply_advances` 从 agents.yaml 读 `entity_advance` 配置并透传（默认关闭，坏配置 fail-closed） |
| `src/cli_apply_advance.py` | **(c)** `render_apply_advance_result` 显示 created（前瞻补全；CLI 暂未暴露开关） |
| `config/agents.yaml` | **(c)** 新增 `entity_advance.{allow_creation:false, creation_confidence:0.85}` + 说明注释 |
| `tests/test_reviewer_plan_compliance.py` | **新增** (a) 覆盖度/自跳过/非阻断建议集成测试 |
| `tests/test_entity_advance.py` | **扩** (c) 默认关闭仍 skip / 创建 / 空态拒绝 / hard-conflict 拒绝 / conf 拒绝 / 公开入口 created_count |

## 不在本轮范围

- **(b) outline-drift warn→block** → iter066 单独做（warn→block 升级 + 新 `outline_drift_severe` readiness kind + driver/Web 级联，配专项审查）。
- **Aeloon 文档同步行**（codex 建议 #5）：归属用户并行的 Aeloon 提交——`docs/AELOON_INTEGRATION.md` 含用户在途 PR #541 未提交改动，iter064 已在 §11.4 登记并约定不并入本仓库代码提交。
- 小债：F3-3 timeout 校验 3 处重复抽 helper、`_blocker_kind` 薄别名清理——顺延。

## Notes

**教训**：
- **收官对抗审查救了一个 P2**：(a) 原计划「漏多数 beat 硬 block」乍看保守（要多数+≥2），但对**真实长 beat**实测才暴露——字符 bigram 命中率对「忠实戏剧化换句」极不鲁棒，硬 block 会误拒好稿。证明「短 fixture 测试通过」≠「真实数据安全」，关键阈值/判定必须拿真实 plan 验证。建议级是正确落点：既给独立信号又零误报风险，与全项目「宁可漏报不误报」一致。
- **(a) 与 (b) 推迟的一致性**：(b) outline-drift warn→block 推迟正因「会把健康 run 变中途拒绝」；若 (a) 硬 block 上线就是自相矛盾。最终 (a) 非阻断 = 同一安全哲学贯彻到底。
- **环境坑复发**：`verify.sh` 内部用裸 `python3`，本机 homebrew python3 缺 pydantic → 173 import error 让 verify 误判 exit 1。必须 `PATH=$PWD/.venv/bin:$PATH bash scripts/verify.sh`（已在 Acceptance Result 标注）。

**plan-compliance 局限（在案）**：`_beat_coverage` 是字符 bigram 词法覆盖度，不是语义履约判定——长 beat 戏剧化换句会漏报，重名/通用词会虚高。建议级 + 阈值 0.15 把它定位成「只点基本没写到的 beat」的低噪提示，不当语义闸用。若未来要真语义履约判定，需 LLM agent 或带分词器的实体锚定（本轮刻意不引依赖）。

**后续候选（iter066+）**：
- **(b) outline-drift warn→block**（本轮推迟的 #6 第三子项）：新 `outline_drift_severe` readiness kind + driver/Web 级联，配专项审查；注意 `rolling_summary` 落后 drafts 的误报风险（0.2 阈值 + MIN_ANCHORS 缓解）。
- plan-compliance 升级为实体锚定 / LLM 语义履约（仅当建议级信号实跑证明不够用时）。
- 既有候选：confidence 非有限值在 entity_graph 写入的统一 clamp（含 legacy advance 路径，跨 iter064 backlog）、KB 起点过滤安全视图、drama 站③④ 等维持原状。

**对铁律的影响**：(a) 建议级走既有 `rewrite_suggestions` 通道、(c) 默认关闭 → 两者都满足铁律④（裸仓库字节级不变）。新增 `entity_advance` 配置项是 cap/开关单源，未来调阈值只改 agents.yaml 一处。
