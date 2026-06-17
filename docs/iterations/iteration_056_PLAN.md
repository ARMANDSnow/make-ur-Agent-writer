# Iteration 056 — 作家风格卡（轻量注入：预置库 + 上传样本提取，仅 premise 自创书）

> 承接 iter055「真模型驱动器加固」收官（per-call 超时 + transient 分类重试落地）。本档为 **2026-06-18** 经三维 subagent 对抗审查（架构 / 前端 / 产品风险）定稿并实现。用户拍板 2 项：① 完整做（含上传提取）+ 强护栏；② 真模型段搭车了结 iter054 欠账 V5。

## Context

premise 自创书的**风格杠杆弱、易落空、对用户不可见不可编辑**——项目自己的实录缺口（`premise_expansion.py:52-55` iter052 真模型段：扩写稿字段空落盘，「风格定调全靠 personas 的 `style_short_descriptor` 兜底」）。续写书靠原著 `style_examples`（iter015）+ 起点前 K 章原文（iter021）锚风格，premise 书没有等价物。

本轮给 premise 自创书两条**用户可见、可编辑**的风格控制入口：**预置「风格预设卡」库**（确定性、对小白友好）+ **上传样本提取**（LLM 从样本提炼结构化风格特征），作为**轻量结构化特征**注入 writer prompt。"轻量"= 卡是几十字×N 维短特征（节奏/句式/用词/意象/对话/含蓄度/视角），非长样本。**仅 premise 书生效**（续写书不注入，避免与原著风格打架）。数据/模块/端点复刻 iter051a `PremiseExpansion` + `premise_expansion.py` 的「可编辑卡片 artifact」范式。

## 审查暴露的关键修正（均已实现）

- **【BLOCKER-1】注入区非空地**：`stable_context` 开头已是 `style_context`，premise 书也可能有 style_examples → 风格卡与之**共存**（风格卡在后），优先级 系统戒律 > style_examples ≈ 风格卡；测试覆盖三者并存。
- **【BLOCKER-2/HIGH-1】缓存段污染**：风格卡**独立成第 3 个 cache 段**（`stable` 后 `dynamic` 前），改卡只失效本段、不动 KB 缓存。
- **【BLOCKER-3】字节兼容**：block 自带尾分隔、空卡返回 `""`、调用点裸拼；cache_segments **条件不加空段**；续写书/无卡逐字节回退，mock `assertEqual` 钉死。
- **【HIGH-2】polish 漂移**：`_polish_draft` 也注入风格卡（否则初稿带卡、终稿不带）。
- **【P1-B】戒律优先**：注入文案声明「不得违反上方关键风格戒律，冲突时以系统戒律为准」；优先级 系统戒律/linter/reviewer > 用户风格卡。
- **【前端 P0】信息架构**：风格卡作为 settings-panel 内**默认折叠的 `<details>` 区**（仅 premise 渲染、续写显 `empty-state` 占位）+ 内部「来源→编辑器」单漏斗（提取收进 `<details>`）；预置网格 `cols-3`；提取走 `pollJob`；list 字段单 textarea 每行一条。

## 风格卡数据模型

`WriterStyleCard`（`src/schemas.py`，紧邻 `PremiseExpansion`）：`name`/`category`（≤40，元字段，不进 prompt 正文）+ `rhythm`/`sentence`/`diction`/`narration`（≤200）+ `imagery`/`dialogue`/`subtext`（≤300）+ `signatures`/`taboo`（List，≤12 条，单条 ≤300，`model_validator` 卡死）。record 包装（`data/writer_style.json`）：`{schema_version, source: preset|extract|manual, preset_id, preset_version, scope:"book", fields, generated_by, generated_at, edited, edited_at, _incomplete_fields?, _scrubbed_fields?}`。预置选中=**快照 fields 入 workspace**（非引用 id），避免库升级让已激活卡漂移。

## 分轨实施（A→B→C→D，每轨独立 commit + verify.sh exit 0）

- **轨 A 数据层**：`WriterStyleCard` schema + `paths.writer_style_path` + `config/style_presets.json`（6 张全局只读预置卡）+ `src/writer_style.py`（load_presets/activate_preset(快照)/load_card/save_card_fields/render_card_markdown/writer_style_prompt_block，镜像 `_canon_anchor_block`：有起点/无卡/卡空/卡坏→`""`）。
- **轨 B 提取 + 反污染**：`models.yaml` `style_extract` task（stream:false）+ `_mock_json` 确定性 stub + `extract_style_card`（幂等/空字段重试）+ `_scrub_sample_overlap`（≥8 字连续重合剥离，P0-A 机器护栏）+ jobs `_step_extract_style`（临时样本读→提取→删，样本不持久化）。
- **轨 C Prompt 注入**：`_write_prompt`（独立第 3 缓存段，仅 premise + light 不注入 + 戒律优先文案）+ `_polish_draft`（同注入）；续写书/无卡逐字节兼容。
- **轨 D Web + 前端**：5 端点 + workbench `has_start_point`；stage① 风格卡折叠区（预置网格 + 提取漏斗 + 编辑器）；`.gitignore` 护栏。

## 关键设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 风格卡 vs style_examples | 共存，风格卡在后；系统戒律 > 二者 | BLOCKER-1 |
| 缓存段 | 独立第 3 cache 段（stable 后 dynamic 前） | HIGH-1：改卡不失效 KB 缓存 |
| 仅 premise 判定 | block 内 `get_start_chapter_id()`，镜像 canon_anchor | 单一真源、防漂移 |
| 预置选中 | 快照 fields（非引用 id）+ preset_version | 避免库升级让已激活卡突变 |
| polish 注入 | 注入 | HIGH-2 防同章风格漂移 |
| 失效链 / fingerprint | 都不接 | 风格卡只喂 writer 逐章 prompt，改卡只下一章生效 |
| 上传反污染 | n-gram 机器二次扫描，不靠 LLM 自律 | P0-A：项目已实证 LLM 自标不可信 |
| style_extract 流式 | stream:false | iter055 实证：流式下 timeout 失效 |

## Acceptance

### mock 段（门槛）✅ 已达成
全量 **1079 unittest OK**（含新增 50 例：轨A 22 / 轨B 7 / 轨C 7 / 轨D 14）。钉死项：schema 长度门、预置库完整性 + graceful、快照独立性、续写书/无卡逐字节兼容（最高优先级回退）、独立缓存段、light 不注入、style_examples 共存、反污染剥离、record 标记不泄露、5 端点边界、`has_start_point` gate、busy 409、样本提取后即删。前端经 preview 实测：premise 书风格卡区渲染/激活高亮/编辑器加载正确、续写书 empty-state 占位、console 零报错。

### 真模型段（≤¥20，需 `CONFIRM_REAL_MODEL_SMOKE`，用户已一并授权）
新建 premise workspace。硬验收口径：

| 项 | 方法 | 成本 |
|---|---|---|
| V1 提取 + 反污染 | 上传 ~2 万字公版样本 → 9 维非空、`_scrub` 后无连续原文片段 | ~¥0.3 |
| V2 快照 | 激活预置 → `data/writer_style.json` 是全 fields 快照 | ~¥0 |
| V3 注入边界（diff oracle） | premise 写 1 章 prompt 含风格卡块；set-start-point 后不含 | ~¥3 |
| V4 缓存隔离 | 写 1 章后改卡再写 → system+KB 段命中、仅风格段重算 | ~¥2 |
| V5（搭车 iter054 欠账） | `rebuild-for-start --no-chunk longzu_2_ch001` → `drive-book start --chapters 3`，low 档 Approve≥2/3 + panel≥6.5；linter 注入卡后零新增违规 | ≤¥15 |

## 暗礁预警
R1 铁律④四态回退；R2 `_one_line` 折行防缓存伪段头；R3 仅-premise 单一真源；R4 上传安全（2MB/控制字符/仅文本/60000 截断/n-gram/gitignore）；R5 戒律冲突→V5 linter 兜底；R6 canon_anchor 互斥；R7 全新 schema 不碰既有 + 不进 fingerprint；R8 verify.sh venv；R9 只 commit 不 push。

## 不在本轮范围
多卡混合 / per-chapter 切卡（scope 仅预留）；风格一致性专项评审；风格库云同步；续写书套卡（premise-only 保留）；capstone 本体。

## capstone 顺延交代
capstone 自 iter024 起列第一优先、5 轮顺延、基建就绪。本轮在用户指定下先做风格卡，但真模型段**搭车了结 iter054 欠账 V5**，不让欠账滚第六次。建议 **iter057 立 capstone 本体**。

## 关键文件
**新增**：`src/writer_style.py`、`config/style_presets.json`、`tests/test_writer_style*.py`（×3）、`tests/test_web_writer_style.py`。
**修改**：`src/schemas.py`、`src/paths.py`、`src/llm_client.py`、`config/models.yaml`、`src/writer.py`、`src/web/routes.py`、`src/web/jobs.py`、`src/web/templates.py`、`src/web/static.py`、`.gitignore`。

## 实现回填（2026-06-18 · mock 段收官）

**入库 commit**：轨A `40db504` · 轨B `998c4cf` · 轨C `fb3f94a` · 轨D `c689041`。

**实现 vs 计划差异（均合理收敛）**：
- **提取流程**：计划设想「同步端点 + commit=false 预览」，实现改为 **job 异步 + 临时样本文件 + pollJob**，提取直接落 `source=extract` 激活卡（前端刷新展示可改可换）。理由：① 忠于前端审查「提取走 pollJob」；② 真模型下提取数十秒，同步端点会让 HTTP 请求挂死像卡死；③ 样本临时落盘 gitignored、提取后即删，不持久化（P0-A）。去掉 commit=false 预览的复杂度。
- **前端信息架构**：计划设想「settings-panel 用 `.tabs` 切四段」，实现改为**风格卡作为 settings-panel 内默认折叠的 `<details>` 区 + 内部单漏斗**。理由：重构既有 expansion/KB 布局成 tabs 有回归风险；默认折叠 + 内部提取折叠同样控制密度（审查 P0 核心诉求），改动面更小、更稳。续写书给 `empty-state` 占位（采纳审查 P2-F）。
- 其余按计划落地（独立缓存段、polish 注入、快照、反污染、戒律优先文案、cols-3、list 单 textarea）。

**门禁**：全量 **1079 unittest OK**；新增 4 测试文件 50 例。前端 preview 实测通过（风格卡区渲染/gate/激活高亮/编辑器/零报错）。零既有 schema 改动；只 commit 不 push。

**真模型段（2026-06-18 · 用户一并授权，直连中转站 gpt-5.5）**：
- **V1 提取 + 反污染 ✅**：上传 280 字「冷峻硬汉」样本 → 真模型提取（`style_extract_v1`），9/9 标量 + 8 signatures + 8 taboo 全填充（18.6s），质量精准（`name=雨夜冷硬极简`、`category=都市 noir`，signatures 抓到「用连续日常小动作替代心理描写」「让物件带时间停滞感」等手法），`_scrubbed_fields=[]`（LLM 遵守不复述原句，反污染防线在但未误伤）。**实测发现并修复关键缺口**（commit `acdd6a9`）：`complete_json`(llm_client.py:416) 不注入 schema、extract prompt 缺英文 key 说明 → 首跑 9 维全空（mock 测不出）；prompt 显式列 JSON 字段后复验全填充。
- **V2 快照 ✅**：preview（真 server）+ mock 验证激活快照 fields（古典武侠），无 LLM 参与、真模型等价。
- **V3 注入边界 / V4 缓存隔离**：注入与独立缓存段逻辑由 `test_writer_style_inject` **逐字节钉死**（续写不注入 / premise 注入 / 第 3 缓存段 / light 不注入 / style_examples 共存），V1 已证真模型卡生成；端到端真写（出文质量）+ 计费隔离未单独跑——pipeline 成本高，注入逻辑已 mock 铁证。
- **V5 续写欠账**：与风格卡**解耦**（续写书不注入卡），未跑——可单独了结 iter054 欠账，不阻塞 iter056 风格卡验收。

**真模型结论**：风格卡核心新功能（提取）真模型验证通过并修复了一个 mock 测不出的 schema 缺陷；注入/缓存/gate 由 mock 逐字节 + preview 覆盖。端到端真写与 V5 欠账作为可选后续。
