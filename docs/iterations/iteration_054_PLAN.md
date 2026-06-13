# Iteration 054 — 深起点续写：从操作纪律到机制保证（计划稿 v2）

> 承接 iter053 收官后的三视角能力审查（2026-06-13），并经 **2026-06-13 二次 workflow 对抗式核查**（11 agents / 逐文件 file:line 复核 + 完整性穷尽，证据见本档「核实回填」段 + 任务 `wauup3r0p` 输出）修订。v1→v2 的核心变化：补上审查漏掉的 **style_examples verbatim 泄露口**、修正 **054b "集中改点" 与 source_excerpts 覆盖面** 的事实错误、新增 **ingest-to-start 产品模式** 作为建议主线。

## 拍板与回填

**拍板（用户，2026-06-13）**：① iter054 主轴 = **先补深起点真能力（缺口A底座自动重建 + 缺口B泄露硬过滤）**，把"任意书任意起点安全可用"从操作纪律做成机制保证；② capstone 留作 054 之后，范围口径 = 续写原著真实后续（≤26 章，受素材约束）。

**拍板二（用户，2026-06-13，二次核查后）**：③ **ingest-to-start（054d）本轮做、作主线机制**——这才是"做成机制保证"的直接兑现；054a/b 过滤照做，但定位为**测试台 + 纵深防御**（capstone 必须留全书对照，无法物理截断，故过滤路径仍需存在）。

**模型与提速（用户，2026-06-13，已落地）**：write/debate 降到 `openai/gpt-5.5-low`（`.env` 加 `WRITER_MODEL`/`DEBATER_MODEL`，key/url 沿用 `OPENAI_*`=aetherheartpool）；extract/compress/review 保持 `gpt-5.5-high` 以保证底座真实。已实跑 `LLMClient.ping()` 验联通：write 2185ms / debate 1590ms，均 `ok:true`。

## 核实回填（2026-06-13 workflow 对抗式核查，v1 修订依据）

把"注入续写/辩论/规划 prompt 的全部原文/提取来源"逐条核实后，**真实泄露图景**与 v1（及原能力审查）有出入：

**消费层其实已封住大半**（v1 与审查低估了这点）：
- **KB** → 所有 prompt 消费方（`writer.py:85`/`debater.py:119`/`book_runner.py:783`/`plot_planner.py:473`）一律走 `kb_view.start_safe_knowledge`（kb_view.py:61-122），按 `chapter_id ≤ start_idx` 硬过滤；`global_knowledge.md` 从不原样进 prompt。压缩 KB 读全书是**有意做成超集**，由消费层收窄。
- **entity_graph 关系** → `render_active_state`/`_relationship_is_spoiler`（entities.py:41-99）按 timeline `chapter_id` + `is_after_start` 丢起点后条目。
- **manual_facts** → 已过滤（manual_facts.py:40-94）。**continuation_anchor** → 起点已设时走 `format_chapters_before_start_for_anchor`（起点有界，include_start=False）。
- **knowledge_index** → 只注入条目**计数**（writer.py:447 / debater.py:289），从不注入内容 → 无泄露。

**真正残留的泄露口只有三条**（完整性 critic：confidence high，四条 prompt 组装链已穷尽，五条之外无新增）：

| 泄露口 | 级别 | 注入端可过滤? | 现状 | file:line |
|---|---|---|---|---|
| **style_examples** | 🔴 verbatim_prose | **否** | **完全未覆盖** | bootstrap 全书采样 auto_bootstrap.py:206-214 经 `_normalized_context`:528-539（`_sample_numbered_lines`:542-551 取 head/mid/**tail** 窗）；apply 逐字落盘 cli_apply_bootstrap.py:244-259；注入 4 处 writer.py:676/1047、plot_planner.py:521、debater.py:644；`load_style_examples`（style.py:9-26）全文无 `is_after_start`。落盘 md 仅带 `<!-- source lines X-Y -->`，该行号是 normalized_texts 坐标，与 manifest `start_line/end_line`（原始 txt 坐标）**异坐标系，无法 join chapter_id** → 注入端无从过滤 |
| **source_excerpts** | 🟠 verbatim_prose | **是**（带 `source_chapter_id`） | 054a 已规划但**只覆盖 writer 路径**，且未实现 | 落盘每条带合法 `source_chapter_id`（schemas.py:392，实测 longzu 12 段全合法、与 manifest 同命名空间）→ `is_after_start` 可直接施加。但**三个注入点**：writer.py:703（写）、writer.py:149（**评审**）、book_runner.py:794（**评审上下文**）。`source_excerpts.py` 全文无 `is_after_start`。bootstrap 经同一 `_normalized_context` 全书 tail 采样（auto_bootstrap.py:267） |
| **entity_graph key_facts/description** | 🟠 facts | 否（消费端不过滤此子字段） | 054b 底座 start-aware 治本（VALID） | entities.py:104-118 实体级 key_facts/description **零起点过滤**（关系过滤≠实体字段过滤）；该图经 `bootstrap_entity_graph`→`_extractions_context`→`_load_extractions`（auto_bootstrap.py:515）构建 → 在此加起点上界即不含起点后事实 |

**两条已澄清/降级**：
- **debater 起点章尾**（debater.py:628 `load_chapter_text(start_id)[-1200:]`）→ **降为 none**：chapter_splitter.py:145 证明每章行区间硬封闭在下一章标题前，`[-1200:]` 不可能溢出后章；读的是合法起点章本身。**不动**。
- **`_load_extractions` "集中改点"** → v1 判断**不准**：存在**两处独立 glob**（auto_bootstrap.py:515 + `compressor.py:30-31` 独立实现）。但**关键澄清**：真正未被消费层覆盖的 entity_graph key_facts 只走 auto_bootstrap 这一条 → 改 `_load_extractions` 一处**即可堵住该泄露**；compressor 那条只喂 KB，而 KB 已由 kb_view 消费层过滤 → 在 compressor 加过滤是**纵深防御/物理清洁**，不是堵漏所必需。

**最致命的发现**：**longzu 当前不前向泄露纯属巧合**——`_normalized_context` 按文件名字典序 + 70k char cap 在 longzu_3_1 截断，book4/前传（起点后 idx 84-109）从未被采样；5/12 style/excerpt 样例恰在起点前（idx<83）。**把起点改早、调大 cap、或文件改名重排，起点后逐字原著立刻无过滤灌进 write+review prompt。** 与 ch024 同款"数据巧合"，非机制保证 → 坐实"换非结局深起点必触发"。

## 核心洞察（v2 修订）

v1 的洞察"底座构建 start-aware 是缺口 A、B 共同治本点"**部分成立但不完整**：
- 它**对 entity_graph key_facts 成立**（走 `_load_extractions`，加起点上界即可，无需 per-fact schema 大改）✅；
- 但它**够不到两条 verbatim 泄露口**（style_examples / source_excerpts）——这两条**绕过 `_load_extractions`，直接从 `normalized_texts` 全书采样**（auto_bootstrap.py:528-539）。v1 只字未提 style_examples，是最大遗漏。

**修订后的治本点有两层**：
1. **`_normalized_context` 采样起点上界**（auto_bootstrap.py:528-551）：这是 style_examples + source_excerpts bootstrap 的**共同上游单点**。在此按 `get_start_chapter_id()` 对应的 manifest 行号 clamp，两条 verbatim 源一并断。
2. **`_load_extractions` 起点裁剪**（auto_bootstrap.py:515）：堵 entity_graph key_facts facts 级泄露。

**而用户提的 ingest-to-start 比上述两层更彻底**：若 `normalized_texts` 物理上只含起点及之前（上传时按起点截断），则 `_normalized_context`、`_load_extractions`、所有 bootstrap、所有 `load_chapter_text` **物理上无起点后内容可采**——三条残留口 + 双 glob 问题**一并消失，无需任何 `is_after_start` 过滤**。代价：测试/capstone 需保留全书对照，故那条路径仍需过滤。结论是**两种模式并存**（见决策表）。

## Plan（四轨，按风险从低到高 + 安全优先）

1. **054a 消费/采样端 verbatim 泄露硬封（缺口B第二道防线，低风险先行）**
   - **`_normalized_context` 起点上界**（auto_bootstrap.py:528-551，**新增、v1 漏项**）：按 `start_point.get_start_chapter_id()` 对应 manifest 行号，给采样窗口加起点上界，越过起点的行不喂 LLM。无起点 fail-open 全量（铁律④逐字节不变）。**这一招同时断 style_examples + source_excerpts 的 bootstrap 源**。
   - **source_excerpts 注入端三路过滤**：在 `select_for_chapter`/`format_excerpts_for_prompt`（source_excerpts.py:160-220）下沉 `is_after_start(source_chapter_id)` 丢弃；覆盖**全部三注入点** writer.py:703 + writer.py:149 + book_runner.py:794（v1 只提 writer）。chapter_id 已确认存在，技术可行。
   - **style_examples 落盘起点校验**（cli_apply_bootstrap.py:244-259）：apply 时拒绝起点后行切片；或给 md 补 chapter_id frontmatter 供注入端 `load_style_examples`（style.py:9-26）过滤。作为 `_normalized_context` clamp 的第二道防线。
   - **entity_graph 关系 fail-open 收紧**：bootstrap prompt+schema 强制 relationship timeline 节点带 `chapter_id`（render 端 entities.py:41-75 已就绪，旧数据 fail-open 兜底）。
   - mock 测试：`_normalized_context` 起点 clamp（有/无起点）、source_excerpts 三路过滤、style_examples 起点拒切、关系 chapter_id 强制。

2. **054b 底座构建 start-aware（缺口A治本 + entity_graph key_facts 源头，中风险）**
   - **`_load_extractions` start-aware 过滤**（auto_bootstrap.py:515，可选 `before_start_only`）：从文件名解析 chapter_id，排除 `is_after_start` 的提取；bootstrap-graph/anchor-fallback/global_facts 传 True。**堵 entity_graph key_facts facts 级泄露**（消费端不过滤此子字段）。greenfield/无起点 fail-open 全量。
   - **（可选纵深）compressor.load_extractions 同步**（compressor.py:30）：物理清洁 KB；非堵漏必需（KB 已由 kb_view 消费层过滤），下沉为共用 `load_extractions_before(start_id)` 避免"改一处漏一条"。
   - **entity_graph 起点 stale sidecar**：复制 anchor 的 `_anchor_matches_current_start`（auto_bootstrap.py:112-149，iter027）给 entity_graph——sidecar 记 `start_chapter_id`，换起点后自动判 stale 强制重建。补审查指出的不对称缺口。
   - **覆盖闸前移**：`extraction_coverage_failures`（053g warn）提前到 `set-start-point` 报 + `plan-chapters` 前升 blocker。
   - **「换起点重建全链」编排 `rebuild-for-start`**：串 extract(起点窗口，复用 extract_all 的 chapter_ids 参数)→compress→bootstrap-graph --force→bootstrap-anchor --force→apply。填 longzu 4 步人肉救火的洞。**实跑 054c 前必须 mock 测穿**（避免 054c 变成给编排擦屁股）。
   - mock 测试：`_load_extractions` start-aware、graph sidecar stale、覆盖闸前移与 blocker、`rebuild-for-start` step 序。

3. **054d ingest-to-start 产品模式（主线机制 — 用户拍板本轮做，真正的"机制保证"）**
   - **流程**：先给起点 → 上传 txt → normalize → split → **丢弃起点后章节，`normalized_texts` 物理只留 ≤起点** → 下游 extract/bootstrap/excerpt/style/anchor **天然有界**。
   - **效果**：三条残留 verbatim/facts 泄露口 + 双 glob 问题**结构性消失**，无需 054a/054b 的任何 `is_after_start` 过滤（在此模式下过滤层退化为 no-op）。这才是用户拍板"任意书任意起点安全可用、做成机制"的直接兑现。
   - **与 054a/b 关系**：不互斥。ingest-to-start = **生产默认**（用户续写自己的书/连载断点，本就无起点后内容）；054a/b 过滤 = **测试台 + 纵深**（capstone 必须留全书对照，无法物理截断）。
   - **风险/边界**：split 须正确识别起点章边界；起点章本身合法保留；既有全书 workspace（longzu）不截断、走 054a/b 模式。
   - **已拍板本轮做、作主线机制**（2026-06-13 拍板二）：这是 UX 改动（上传顺序反转 + 摄入边界），范围比 v1 大；054a/b 作 backstop。实施时先 mock 测穿 split 截断有界 + 下游零起点后内容，再进 054c。

4. **054c 深起点端到端验证（真模型，验收载体）**
   - **换非结局章起点实跑**：longzu 设龙族 II/III 早期起点（起点后有大量真实素材 + 起点前后都有剧情），跑 `rebuild-for-start` → 续写 ch1–3。这是真正考验"任意起点无泄露"的载体（不再有 ch024 结局章 + 70k cap 截断的巧合规避）。
   - **diff oracle 验收（v2 新增，核心泄露验收）**：同一起点跑两遍——(A) ingest-to-start 截断模式、(B) full+054a/b 过滤模式——**机器 diff 两边注入 writer/debate 的全部材料**（KB/entity_state/excerpts/style/anchor）。过滤正确 ⇒ 应逐字节一致。比人眼"机库穿越"体检硬核。
   - **泄露体检**：续写正文 + 注入材料零起点后内容；重点验 style_examples（v1 漏的最严重口）+ source_excerpts 三路。
   - **提速档（验收主轴是查泄露非写作质量，故大胆降门槛）**：write/debate=gpt-5.5-low（已配）；`--tier low`（3/5、6.5）；`max_review_attempts`=1~2；polish off。extract/review 保持 high（底座真实，让过滤有真东西可过滤）。
   - **A-M5 / M3 搭车修**：write-book/driver 加 `--allow-stale-outline` 透传（A-M5，~4 处）；Approve+block 稿留 `approved_with_block_issues` 标记（M3）。
   - 预算：换起点底座重建 ≈¥10 + 续写 3 章（low 档 + low 模型更省）≈¥4，**≤¥20**。

## 关键设计决策（v2 修订）

| 决策项 | 结论 | 理由 |
|---|---|---|
| 缺口 B 治本架构 | **两种模式并存**：ingest-to-start（生产默认，结构性免疫）+ 054a/b 过滤（测试台 + 纵深） | ingest-to-start 一招断三条残留口（都从 normalized_texts 采样）+ 消解双 glob；但 capstone 必须留全书对照，无法物理截断，故保留过滤路径 |
| verbatim 泄露源头单点 | **`_normalized_context` 采样起点上界**（auto_bootstrap.py:528-551） | style_examples + source_excerpts bootstrap 的共同上游；v1 误判 `_load_extractions` 为唯一治本点，实际它够不到这两条 verbatim 口 |
| style_examples 过滤位置 | **bootstrap 采样端（`_normalized_context` clamp）+ 落盘校验**，**不在注入端** | 落盘 md 行号是 normalized_texts 坐标，与 manifest chapter 坐标异系，注入端无法 join chapter_id 过滤 |
| source_excerpts 过滤 | **注入端三路 `is_after_start(source_chapter_id)`**（writer.py:703+149、book_runner.py:794）+ 采样端 clamp | chapter_id 已确认存在（schemas.py:392）→ 技术可行；v1 只覆盖 writer 一路 |
| `_load_extractions` 改点 | **改 auto_bootstrap.py:515 一处即堵 entity_graph key_facts 漏**；compressor.py:30 那条为纵深（KB 已消费层过滤） | 真正未被消费层覆盖的只有 entity_graph key_facts，且只走 auto_bootstrap 这条；双 glob 全改是物理清洁，非堵漏必需 |
| entity key_facts 结构化 | **本轮不做**，靠 054b `_load_extractions` start-aware 从源头避免起点后事实 | key_facts schema 升级五处联动，绝不与真模型实跑同轮（052 纪律）；054b 治本后降为纵深 |
| debater 起点章尾 | **不动** | 核实降级为 none：每章行区间硬封闭（chapter_splitter.py:145），读的是合法起点章本身 |
| 实施顺序 | 054a（低风险纯 mock）→ 054b（中风险编排）→ **054d ingest-to-start（主线机制）** → 054c（真模型验证压轴） | 安全口先堵、底座编排次之（均纯 mock 可测）；主线机制 054d 在过滤 backstop 就位后落地；真模型验证最后。054d 虽是主线，但排在 054a/b 后以保证退路（截断出问题时过滤层仍兜住） |
| capstone | 054 之后单独立项 | 用户拍板；054 先把"任意起点安全"做成机制 |

## 实施备注（暗礁预警）

- **schema 升级纪律（052 三度强调）**：entity timeline schema（key_facts 结构化）五处联动，**绝不与真模型实跑同轮**；本轮用 054b `_load_extractions` start-aware 绕过。
- **style_examples 异坐标系陷阱**：md 注释 `<!-- source: file lines X-Y -->` 的行号锚 normalized_texts，manifest start_line/end_line 锚原始小说 txt，**不能直接 join**。故 style 过滤必须在 bootstrap/apply 阶段（那时还有 manifest 上下文），不能寄望注入端。
- **`_normalized_context` clamp 的行号来源**：需把 manifest 的章→行映射喂进采样，确保 clamp 用的是起点章的 manifest 行号上界；核 `chapter_manifest.json` 的 source_file/start_line/end_line 与 normalized_texts 行号是否同坐标系（若不同需先对齐，否则 clamp 错位）。
- **source_excerpts 评审路径易漏**：writer.py:149 + book_runner.py:794 两个评审注入点与 writer.py:703 同样未过滤，三处都要改，否则正文干净但评审材料仍泄露。
- **双 glob 别只改一处**：若做 compressor 纵深，下沉共用函数；否则 longzu 等已有全书 workspace 的 KB 物理仍含起点后（虽 kb_view 消费层兜住，但 stale sidecar/diff oracle 会暴露不一致）。
- **覆盖闸升 blocker 护存量**：greenfield 自创书无源书提取，fail-open 不拦。
- **ingest-to-start 与既有 workspace**：longzu 已摄入全书，不可截断（capstone 要对照），明确走 054a/b 模式；ingest-to-start 仅对新上传生效。
- 054c 起点选择按铁律⑥实跑前与用户确认；换起点触发底座全重建（真模型成本），跑前估算。
- 铁律⑤：收官只 commit 不 push。

## 不在本轮范围
- entity key_facts per-fact chapter 结构化（052 顺延；054b 底座 start-aware 治本后降为纵深，单独立项）。
- capstone 长程（054 之后；范围口径已拍板 ≤26 章真实后续）。
- timeline 动态建边（052 顺延）。
- 评审端反剧透硬拒因规则库（若 054a/b + ingest-to-start 充分则可不做，视 054c diff oracle 实测）。

## Acceptance（待回填）
### mock 段（门槛）
- 全量回归零失败（965 基线 + 预估 +N）；verify.sh exit 0。
- 待钉死：`_normalized_context` 起点 clamp（有/无起点）、source_excerpts 三路过滤、style_examples 起点拒切、关系 chapter_id 强制、`_load_extractions` start-aware（有/无起点）、graph sidecar stale、覆盖闸前移与 blocker、`rebuild-for-start` step 序、A-M5 逃生门透传、M3 标记。（ingest-to-start 若纳入：split 截断有界、下游零起点后内容。）

### 真模型段（门槛，深起点 ≤¥20）
- 换非结局章起点：`rebuild-for-start` 一键重建底座 → 续写 ch1–3。
- **diff oracle**：ingest-to-start ↔ full+filter 两模式注入材料逐字节一致（过滤正确性的机器证明）。
- **泄露体检**：注入材料（含 style_examples / source_excerpts 三路）+ 正文零起点后内容实证。
- 写作质量（次要）：low 档 Approve（≥2/3 章过）+ panel ≥6.5（low tier）；此为提速档，不作质量背书，需质量数另用生产档单跑。

## Notes
- 本档为计划稿 v2（2026-06-13 起草于 iter053 收官 + 能力审查 + 用户拍板乙路线 + 二次 workflow 核查之后）。
- v1→v2 修订依据：workflow 任务 `wauup3r0p`（5 维 probe + 对抗复核 + 完整性穷尽），核实详见本档「核实回填」段。
- 实施建议**专注新轮**进行（含 schema 邻域 + 编排 + 真模型验证，仿 053「计划稿→四维 subagent 审核→分轨实施→实跑验收」模式）。
- 三视角审查的 file:line 级缺口清单见 docs/AGENT_HANDOFF.md「能力边界审查」段。
