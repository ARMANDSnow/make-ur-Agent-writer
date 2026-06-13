# Iteration 054 — 深起点续写：从操作纪律到机制保证（计划稿）

> 承接 iter053 收官后的三视角能力审查（2026-06-13，证据见 AGENT_HANDOFF「能力边界审查」段）：
> ① **无泄露断言降级**——KB + 人工事实两路硬过滤 ✅；但 entity_graph 实体描述（key_facts/description）零过滤、关系 fail-open、source_excerpts 零过滤 ❌；评审端无反剧透硬拒因；053b canon 锚定是软约束。longzu 未爆剧透是**数据巧合**（起点 ch024 恰是结局章、只提取到 ch024），非机制保证。
> ② **任意起点断言降级**——数据模型层支持（起点可设/可校验/可过滤），但底座（提取/KB/实体图）不按起点自动重建；init 默认 `extract-limit=10` 全书前切，深起点根因④系统性必现；longzu 实跑 4 步救火（补提取→recompress→bootstrap-graph --force→bootstrap-anchor --force）没一步被编排。
>
> **拍板（用户，2026-06-13）**：① iter054 主轴 = **先补深起点真能力（缺口A底座自动重建 + 缺口B泄露硬过滤）**，把"任意书任意起点安全可用"从操作纪律做成机制保证；② capstone 留作 054 之后，范围口径 = 续写原著真实后续（≤26 章，受素材约束）。

## Context

iter053 把**中间产物的起点一致性**（指纹/血统/时间线）补成了硬护栏，但审查揭出更底层的两个缺口，且二者同源：

**核心洞察——缺口 A 与 B 的共同治本点是"底座构建 start-aware"**。entity_graph/KB/anchor 全部派生自 `extracted_jsons`（`auto_bootstrap._load_extractions` glob 全量，auto_bootstrap.py:488-490 集中点）。若底座构建只基于**起点及之前**的提取：
- 缺口 B（泄露）从源头解决——底座物理上不含起点后内容，entity_graph 的 key_facts 里不会出现起点后事实（无需 per-fact 过滤这种 schema 大改）；
- 缺口 A（自动重建）的一半解决——换起点只需重跑 bootstrap（输入窗口随起点变），不需重提取（提取保持全量、数据完整）。

消费端 `is_after_start` 过滤（kb_view 047b / entities 关系 / 待补的 source_excerpts）作为**第二道防线**保留（defense-in-depth）——提取窗口若因操作失误含起点后章节时兜底。

## Plan（三轨拆分，按风险从低到高 + 安全优先排序）

1. **054a 消费端泄露硬过滤（缺口B第二道防线，低风险先行）**
   - **source_excerpts 起点过滤**（审查点名的零过滤泄露口）：`source_excerpts.select_for_chapter` / `load_excerpts` 摘样时排除 `is_after_start(source_chapter_id)` 的片段；bootstrap_source_excerpts 同步。无起点逐字节不变（铁律④）。**最独立、纯 mock 可测、零 schema 风险——本轨第一项**。
   - **entity_graph 关系 fail-open 收紧**：bootstrap prompt + schema 强制每个 relationship timeline 节点带 `chapter_id`（旧数据仍 fail-open 兜底）；render 端过滤逻辑已就绪（entities.py:41-75），只缺生成端保证字段存在。
   - **entity 实体级 first_seen 过滤**：`EntityProposal` 加可选 `first_seen_chapter_id`，bootstrap 标注，`render_active_state` 对 `is_after_start(first_seen)` 的实体整体跳过（起点时不该存在的实体）。fail-open 护存量。
   - mock 测试：source_excerpts 起点过滤（有起点排除/无起点不变）、关系 chapter_id 强制、实体 first_seen 跳过。

2. **054b 底座构建 start-aware（缺口A治本 + 缺口B源头，中风险）**
   - **`_load_extractions` start-aware 过滤**（集中改点）：可选 `before_start_only` 参数——从文件名解析 chapter_id，排除 `is_after_start` 的提取；compress/bootstrap-graph/bootstrap-anchor 的底座构建路径传 True，greenfield/无起点 fail-open 全量（逐字节不变）。这一招让 KB/实体图/anchor 物理上只基于起点前。
   - **entity_graph 起点 stale sidecar**：复制 anchor 的 `_anchor_matches_current_start` 机制（auto_bootstrap.py:112-149，iter027）给 entity_graph——sidecar 记 `start_chapter_id`，换起点后自动判 stale 强制重建。补上审查指出的"anchor 有、graph 没有"的不对称缺口。
   - **覆盖闸前移**：`extraction_coverage_failures`（053g，现 readiness warn）提前到 `set-start-point` 时报 + `plan-chapters` 前升 blocker（避免 debate/plan 钱白花）。
   - **「换起点重建全链」编排**：新增 `rebuild-for-start`（或 set-start-point 后自动触发）串 extract(起点窗口，复用 extract_all 已有 chapter_ids 参数)→compress→bootstrap-graph --force→bootstrap-anchor --force→apply。填 longzu 实跑 4 步人肉救火的洞。
   - mock 测试：_load_extractions start-aware（有起点排除/无起点全量）、graph sidecar stale 检测、覆盖闸前移、编排命令 step 序。

3. **054c 深起点端到端验证（真模型，验收载体）**
   - **换非结局章起点实跑**：longzu 设一个龙族 II/III 早期起点（起点后有大量真实素材 + 起点前后都有剧情），跑 `rebuild-for-start` → 一键重建底座 → drive-book 续写 ch1–3。这是真正考验"任意起点无泄露"的载体（longzu ch024 结局章规避了泄露口，新起点不再规避）。
   - **泄露体检**：续写正文 + 注入材料（entity_state/excerpts）零起点后内容；对照 053c 的"机库穿越"体检方法。
   - **A-M5 / M3 搭车修**（053d 观察项，capstone 路径放大）：write-book/driver 加 `--allow-stale-outline` 透传（A-M5，~4 处）；Approve+block 稿留 `approved_with_block_issues` 标记供人审（M3）。
   - 预算：换起点底座重建（提取窗口 + KB + 图 + anchor）≈¥10 + 续写 3 章 ≈¥6，**≤¥20**（拍板⑤ ¥50+ 授权内）。

## 关键设计决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| 缺口 B 治本位置 | 底座构建端 start-aware（054b）为主，消费端 is_after_start（054a）为第二道防线 | 构建端裁剪让 KB/实体图物理上不含起点后，避开 key_facts per-fact 过滤的 schema 大改；消费端兜底防提取窗口操作失误 |
| 提取是否裁剪 | **不裁剪**，提取保持全量；只在 `_load_extractions` 的底座构建消费路径过滤 | 提取全量 = 数据完整，换更晚起点无需重提取；过滤集中在一个消费点，风险可控 |
| entity key_facts 结构化 | **本轮不做**，靠 054b 底座 start-aware 从源头避免起点后事实 | key_facts 字符串→带 chapter_id 结构是 052 顺延的"entity timeline schema 升级"，五处联动大改，绝不与实跑同轮（052 纪律）；054b 治本后它降为 defense-in-depth，可后续单独立项 |
| 实施顺序 | 054a（低风险纯 mock）→ 054b（中风险，含 sidecar/编排）→ 054c（真模型验证） | 安全口先堵（source_excerpts 是确证泄露口）；底座编排次之；真模型验证压轴 |
| capstone | 054 之后单独立项 | 用户拍板；054 先把"任意起点安全"做成机制，capstone 再以干净能力验长程一致性 |

## 实施备注（暗礁预警）

- **schema 升级纪律（052 三度强调）**：entity timeline schema（key_facts 结构化）五处联动，**绝不与真模型实跑同轮**；本轮用 054b 底座 start-aware 绕过，key_facts 结构化顺延。
- `_load_extractions` 是底座构建的集中消费点也是风险点——start-aware 过滤要确保无起点时 `before_start_only` 路径与现状逐字节一致（greenfield 全量）。
- source_excerpts 的 chapter_id 来源：摘样片段是否带 source_chapter_id？实施时核 `bootstrap_source_excerpts` 落盘结构（审查指 auto_bootstrap.py:229-276）。
- entity_graph sidecar 要与 anchor sidecar 命名/机制对齐（`.entity_graph.meta.json` 记 start_chapter_id），apply 时盖章（cli_apply_bootstrap.py:234-238 同款）。
- 覆盖闸升 blocker 要护存量：无提取的 greenfield 自创书不该被拦（greenfield 无源书提取概念，fail-open）。
- 054c 起点选择按铁律⑥实跑前与用户确认；换起点会触发底座全重建（真模型成本），跑前估算。
- 铁律⑤：收官只 commit 不 push。

## 不在本轮范围
- entity key_facts per-fact chapter 结构化（052 顺延的 entity timeline schema 升级；054b 底座 start-aware 治本后降为 defense-in-depth，单独立项）。
- capstone 30 章长程（054 之后；范围口径已拍板≤26 章真实后续）。
- timeline 动态建边（052 顺延，继续观察）。
- 评审端反剧透硬拒因规则库（审查指出当前无；若 054a/b 硬过滤充分则可不做，视 054c 实测）。

## Acceptance（待回填）
### mock 段（门槛）
- 全量回归零失败（965 基线 + 预估 +N）；verify.sh exit 0。
- 待钉死：source_excerpts 起点过滤、关系 chapter_id 强制、实体 first_seen 跳过、_load_extractions start-aware（有/无起点）、graph sidecar stale、覆盖闸前移与 blocker、rebuild-for-start 编排序、A-M5 逃生门透传、M3 标记。
### 真模型段（门槛，深起点 ≤¥20）
- 换非结局章起点：rebuild-for-start 一键重建底座 → 续写 ch1–3 注入材料 + 正文零起点后泄露实证；Approve ≥2/3、panel ≥7.5。

## Notes
- 本档为计划稿（2026-06-13 起草于 iter053 收官 + 能力审查 + 用户拍板乙路线之后）。
- 实施建议**专注新轮**进行（含 schema 邻域 + 编排 + 真模型验证，仿 053「计划稿→四维 subagent 审核→分轨实施→实跑验收」模式）。
- 三视角审查的 file:line 级缺口清单见 docs/AGENT_HANDOFF.md「能力边界审查」段，是本档立项的直接依据。
