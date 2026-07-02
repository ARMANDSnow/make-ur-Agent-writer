# Continuator / 续

读入一部已出版的小说，抽出里面的设定和人物，然后用一组 LLM agent 接着往下写。续写、规划、审稿分别交给不同的模型，整条流水线在本地跑。

中文 · [English](README_EN.md)

原作语料不进仓库。`小说txt/`、`data/`、`outputs/`、`logs/` 都在 `.gitignore` 里，这里只有引擎。

## 它做什么

一条续写指令大致这样走：

normalize 原文 → 切章 → 抽 entity 和设定 → 压成知识库 → 几个 agent 辩论续写方向 → 强模型规划接下来 N 章 → 便宜模型逐章生成 → reviewer 团加 linter 把关 → 落盘。

CLI 的入口是 `write-readiness` 和 `write-book`。另外有一个本地网页版（`main.py web`），把这套流程搬进浏览器。

跑通过的书有龙族（江南）、冰与火之歌（GRRM 英文）、以及几本自己写的小说，用的是同一条流水线。最近一次真模型测试是龙族第 2 章，tier=mid 通过，panel_score 7.58，成本 ¥0.909。

## 几个设计取舍

- 开发默认 mock。1369 个单测几秒跑完，不烧 token；`tests/__init__.py` 里强制 `OPENAI_MODEL=mock`，避免 `.env` 漏进测试。
- 真模型跑之前先过 preflight。env、context limit、provider 路由、manifest 完整性等几类 FATAL 检查不过，就不让往下跑。
- 一本书一个 workspace（`workspaces/<name>/`），靠 `--book` 切换，彼此不串数据。
- 中英文自动判定切章；EPUB 用标准库 `zipfile + xml.etree + html.parser` 直接转 txt，没引新依赖。
- reviewer 是 fail-closed 的：JSON 解析失败记 Abstain 而不是默认放行；只要有一个 reviewer 给出 substantive Reject，整章就判 Reject。
- 每次 LLM 调用都记 token 和成本，`estimate-cost` 按 provider 单价汇总。

## 快速开始

mock 模式不需要 key，也不联网：

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
python3 -m unittest discover -s tests
```

`unittest discover` 跑完全部单测（几秒，不烧 token）就是引擎装好了。`bash scripts/verify.sh` 在此之上再跑一遍 mock 流水线——注意脚本内部用裸 `python3`，要确保依赖装在该解释器上（本仓库开发用 `.venv/bin/python3`，跑测试同理：`.venv/bin/python3 -m unittest discover -s tests`）。

真模型模式配 `.env`：

```bash
cp .env.example .env
# OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
# planner 想用单独的模型就再配 PLANNER_*，不配就跟随 OPENAI_*
python3 main.py preflight
```

preflight 非零退出就别接着跑真模型。

## 接一本新书

```bash
# 建 workspace，把 txt 或 epub 放进去
python3 main.py workspace-init myBook
cp ~/your-novel.txt workspaces/myBook/小说txt/
# epub 走标准库提取：
# python3 main.py --book myBook epub-import --src ~/novel.epub --out myBook.txt

# 标准化加切章，语言自动判
python3 main.py --book myBook normalize
python3 main.py --book myBook split

# 抽设定，生成 5 类 proposal，人工看过再 confirm
python3 main.py --book myBook init-book --extract-limit 10
for name in global_facts entity_graph continuation_anchor style_examples personas; do
  python3 main.py --book myBook apply-bootstrap --name $name --confirm
done

# 定起点，辩论，规划
python3 main.py --book myBook set-start-point <chapter_id_or_volume_id>
python3 main.py --book myBook debate
python3 main.py --book myBook plan-chapters --chapters 3 --force --require-start-point

# 写
python3 main.py --book myBook write-readiness --chapters 3
bash scripts/write_book.sh --book myBook --chapters 3
```

`write-book` 常用参数：`--max-retries`、`--budget-cny`、`--tier low|mid|high`、`--no-auto-advance`、`--replan-every`。退出码 0 表示全章通过，3 是预算超了，4 是被阻塞。

换书改 `--book` 就行，或者 `export WORKSPACE_NAME=otherBook` 一次性生效。`workspace-list` 和 `workspace-show` 看现有的 workspace。

## 网页版

不想在 CLI 里来回切状态，可以起一个本地网页：

```bash
python3 main.py web              # 默认 127.0.0.1:8765
python3 main.py web --port 9999  # 换端口
```

首页是所有 workspace 的概览：起点、计划、草稿、最近任务。进到一本书里能做这些事：

- 设置续写起点（按 chapter 或 volume）
- 生成或重排章节计划
- 看阻塞原因和推荐命令
- 配好章节数、预算、tier、retry 等参数后启动 `write-book`
- 看只读草稿、review、manifest、status、cost
- 上传新书走 onboarding 向导，中途能请求协作式 cancel
- 把不要的 workspace 二次确认后软删进回收站

手机上侧栏会收成抽屉，宽表格横向滚动。

只用标准库（`http.server` + `string.Template` + 原生 JS），没有前端依赖，默认只绑 `127.0.0.1`。想纯看界面不花钱，启动时加 `OPENAI_MODEL=mock` 覆盖即可。端口被旧进程占了就换一个，或者先 `lsof -ti tcp:8765 | xargs kill` 再起。

## 目录结构

每本书一个 workspace：

```text
workspaces/<book>/
  小说txt/                 原始 txt / epub 转换文本，不进仓库
  data/
    normalized_texts/      normalize 输出
    extracted_jsons/       extract 输出
    knowledge_base/        compress 输出
    manual_overrides/      确认过的设定 / 人物 / 起点
    proposals/             init-book 生成、待人工确认
    chapter_manifest.json  切章索引
  outputs/
    debate/                辩论、chapter_plan.json、outline
    drafts/                chapter_NN.md、meta、failure、snapshot
    reviews/               chapter_NN.review.json
  logs/
    llm_calls.jsonl        调用、token、成本
    web_jobs.jsonl         网页任务历史
```

进仓库的只有 `src/`、`config/`、`scripts/`、`tests/`、`docs/`。每本书的 `小说txt/`、`data/`、`outputs/`、`logs/` 都不进。根目录下的 `data/`、`outputs/`、`logs/` 是 legacy 和 verify 的 mock 路径，同样不提交。

别直接改 `小说txt/` 里的原文；要改设定、人物关系、风格片段，去改 `data/manual_overrides/` 或重新生成 proposal。旧草稿不用手删，runner 在 `--force` 或重试时会自己归档 stale 文件。

## CLI 速查

| 命令 | 作用 |
|---|---|
| `workspace-{init,list,show,import-current}` | 多 workspace 管理（iter 017） |
| `epub-import` | EPUB → UTF-8 txt，只用标准库（iter 018） |
| `normalize` / `split` | 自动识别编码加语言；切章产 `chapter_manifest.json` |
| `init-book` | 一次产 5 类 proposal（entity_graph / facts / anchor / style / personas） |
| `apply-bootstrap --name X --confirm` | 审过的 proposal 落盘 |
| `debate` | 6 agent × 6 轮加结构化投票 → outline.md + decisions.json |
| `plan-chapters --chapters N` | 强模型一次出 N 章规划（iter 014） |
| `write --chapters N --resume-from i --force` | 多章生成 + 5+1 reviewer + lint + polish |
| `review-chapter <i>` / `chapter-status <i>` | 独立复审 / 单章状态 JSON（iter 019） |
| `apply-advance --chapter i --auto-apply --confirm` | entity advance（iter 019） |
| `set-start-point <chapter_id>` / `show-start-point` | 续写起点管理（iter 021；写前硬门 iter 027） |
| `write-book --chapters N --tier T --budget-cny B --replan-every K` | 生产级严格 runner：指纹门禁 + 三档评审 + 预算护栏 + 自动 re-plan（iter 028-029/042；segments 配额循环 iter 046） |
| `write-readiness --chapters N` | 写前就绪检查 ready/warn/blocked（iter 029） |
| `drive-book start/status/resume/stop/report` | 长程驱动器：脱离会话（detach + ppid=1）分段编排 debate/plan/write-book，断点续跑零重复花费 + 预算双层 + blocked 停人审 + 审计账本（iter 052） |
| `auto-pipeline --chapters N --force` | 9 步 SOP 一键编排，CLI 与 WebUI wizard 共用（iter 026/028） |
| `web --port 8765` | 本地 WebUI：书架 / 四阶段工作台 / 章节 / 评审 / 任务（iter 025 起；工作台 iter 048；全程可编辑 iter 050） |
| `preflight` / `status` / `estimate-cost` | 守门 / 状态 / 成本汇总 |

[README_EN.md](README_EN.md) 里有架构图、3-tier 执行说明和全部迭代日志索引。

## 项目状态

| 阶段 | 范围 | 状态 |
|---|---|---|
| 阶段 1（iter 001-005）| mock 优先基础、CLI、preflight | 完成 |
| 阶段 2（iter 006-008）| 首次真模型 smoke + debate 结构化投票 | 完成 |
| 阶段 3（iter 009-013）| 写作质量轴：entity graph / 一致性 reviewer / 多章架构 | 完成 |
| 阶段 4（iter 014-019）| 多 workspace + 多语言 + 无人值守 + 审计加固 | 完成 |
| 阶段 5（iter 020-045）| Web Dashboard + 本地 Beta 写作入口 + UX 收尾 | 完成 |
| 阶段 6（iter 046-048）| 产品力补齐：AgentWrite 配额循环 / 补 KB 剧透 gap / **小白四步工作台**（一句话开书 + premise→四阶段 pollJob + 大纲编辑保存 + 一键测 Key）；canonical 694 tests OK | 完成 |
| 集成（iter 049）| **Aeloon-Pro 插件 / MCP 双轨集成**（`/novel` 命令 + 8 LLM 工具 + 服务端 opt-in token 闸）；canonical 758 tests OK | 完成 |
| 阶段 7（iter 049-050）| **Aeloon 双轨集成 + 全程可编辑闭环**：iter049 Aeloon-Pro 插件 / MCP（已并入 main）；iter050 细纲结构化编辑（指纹白名单 + 唯一真源重算）/ 正文编辑回写 + 重评审 / KB·实体编辑 / 预算护栏 / 铁律⑨ 对抗审查 M×4+L×3 全修；canonical 808 tests OK | 完成 |
| 阶段 8（iter 051）| **premise 扩写质量增强 + 评审预算强拦 + 技债清偿**：051a 一句话立意 → LLM 结构化扩写稿（stage① 可编辑、prepare/debate/bootstrap 三点消费、缺失逐字节回退）；051b `NOVEL_REVIEW_BUDGET_CNY` 独立强拦 + F3/F5/F6/F8 清偿（F4 验证已闭环、F7 显式顺延）；铁律⑨ 双视角审查 M×1+L×2 直修；canonical 877 tests OK。真模型对照 smoke（gpt-5.5-high）：扩写 vs 裸 seed，panel 8.16→8.50、KB +161%、章纲密度 +50%、正文 +26%，成本 +17%（合计 ¥5.96/30 元），均 Approve | 完成 |
| 阶段 9（iter 052）| **长程驱动器正式化 + F6/F7 清债**：052a `drive-book` 子进程编排（detach ppid=1 / 断点续跑零重复花费 / 预算双层 / blocked 停人审 / 审计账本）；052b F6 真模型正负路径双验证 + F7 prompt 补丁拆除（段间对照 8.31→8.48 零退化坐实）；铁律⑨ 双视角审查（H-1 复核误报）M×4+L×1 直修；canonical 907 tests OK。真模型双载体实跑（gpt-5.5-high，合计 ≈¥18.1）：longzu 15 章 ch1 质量闸 blocked（根因=陈旧 outline 污染重 plan + 写手预训练剧透泄露 → iter053 立项）；shudian052 premise 书 **7/7 章 Approve**（panel 8.04–8.72），中断演练账本 206→206 行零重复实证 | 完成 |
| 阶段 10（iter 053-056）| **续写机制保证 + 驱动器加固 + 风格卡**：iter053 中间产物起点校验 + 写手 canon 锚定（longzu 复仇局剥四层毒源、ch1-5 全 5/5 Approve）；iter054 深起点续写底座 start-aware 重建 + 泄露硬过滤；iter055 真模型驱动器加固（per-call 超时 + transient 分类重试 + 批处理非流式拿回超时）；iter056 作家风格卡（预置库 + 上传样本提取，仅 premise；搭车了结 iter054 欠账 **V5 续写 ch1-3 完整 Approve**、panel 7.82/7.36/7.52、¥7.54）| 完成 |
| 阶段 11（iter 057）| **长程续写 capstone 前置：5 个结构性 bug 全修复**（双 subagent 对抗审查 + 源码核验后实施，每 bug 独立 commit）：P0-A plan_fingerprint 收窄全局上下文（replan append 不再卡死已写章 + 幂等迁移脚本）/ P0-B write `stream:false` 拿回 litellm 超时 / HIGH-2 rolling `compressed_older` 确定性压缩写盘止早期失忆 / BLOCKER-1 plan_target 默认覆盖全程 / P1-C outline 语义漂移命中率探针；HIGH-2·P1-C 完整版 + P0-B 方案B 留后续真模型验证。canonical **1097** tests OK | 完成 |
| 阶段 12（iter 058）| **前端用户路径 P0 修复（钱与静默错误）**——源自 `docs/FRONTEND_BUG_AUDIT_2026-06.md`（codex 三-subagent 审计 + 真模型取证，复用已验证护栏框架、零新机制）：#1 onboarding 预算失效（`run_auto_pipeline` 接 `budget_cny` + 步间结算早停，复用 write-book 机制；缺省 10 元上限、显式 0=不设限）/ #2 抽取失败静默吞（混合策略：单步 `_step_extract`→`blocked`、onboarding→loud raise，已抽章留盘）/ #6b NaN·Infinity 穿透 float 校验（`math.isfinite` 守卫，曾绕过成本闸 + 永不超时）；P1（iter059）/P2（iter060）顺延。canonical **1128** tests OK | 完成 |
| 阶段 13（iter 059）| **前端用户路径 P1 修复（崩溃与卡死）**——源自 `docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 P1 段（坏 JSON 为主线，复用 `read_json_optional` 护栏、默认路径 byte-identical、全确定性）：坏 JSON 共因 **#4/#5/#10/#13**（chapter_plan / draft meta·review / rolling summary / driver state·pid 逐调用点 `read_json_optional`；**#4** Option B 产独立 `chapter_plan_invalid` blocker + 前端标签「章节计划文件损坏」，GET /readiness 不再泄 `readiness_error`）/ **#8** auto-advance 坏 proposal·graph 降级 no-op（止「job failed 但内容已落盘」割裂态）/ **#3+NEW-B** 上传 UTF-8 校验 + 0 章同步预检回滚（对齐坏 EPUB UX）/ **#6a+NEW-A** 整数参数 `math.isfinite`+`OverflowError` 守卫（Infinity 不再 500）+ 上限 / **#9** 单步 split gate 改认 `*.txt`；P2（iter060）顺延。canonical 1128→**1158** tests OK（+30）| 完成 |
| 阶段 14（iter 060）| **P2 收官 + Codex 复审补漏（审计 16 条全部清零 open）**——源自 `docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 P2 段 4 条 + 一轮 Codex 复审（复用 `workspace_reserved` / 原子 `write_json` / `read_json_optional` / `math.isfinite` 护栏、零新机制、默认路径 byte-identical、全确定性）：**#7** `set_start_point` 包 `workspace_reserved`（reserved 期间不再穿透写入）/ **#11** writer-style 样本改每请求唯一 uuid 路径 + `write_text_atomic`（止两并发互相覆盖样本，TOCTOU）/ **#14** drama `plan`/`setup_save` 改原子 `write_json` + `workspace_reserved`（setup_save 整个读-改-写进 reservation 闭死竞争窗口）/ **#12** debate 协作式取消 checkpoint（**方案A**：`run_debate` 加 `progress_cb`，每 agent LLM 调用前插 `_check_cancelled`——debate 此前是唯一无取消粒度的 step；writer/book_runner 章内外已有检查点无需改；**方案B**（流式中断）触红线→iter061）；**Codex 复审补漏 A–F**（iter058/059 护栏的对称入口）：**A** `/readiness` 整数参数补 write-book 同上限（`chapters=999999999` 不再物化 10 亿元素 `range`）/ **B** 所有 step 的 `timeout_minutes` 补 finite 校验 + `_timeout_deadline` 加 `math.isfinite` 兜底（双层，止 `nan` deadline 永不超时）/ **C/D/E** web 读面（manifest/草稿详情·列表/PUT graph）裸 `read_json`→`read_json_optional`（修正 Codex 误判：坏 JSON 是「500 击穿」非「泄露文案」，server.py 统一兜底 `internal server error`）/ **F** `book_runner` 5 处残余裸读→`read_json_optional`（790/791 击穿 resume、858 顶替善后快照，`read_json` 至此全无裸读）。canonical 1158→**1180** tests OK（+22）| 完成 |
| 阶段 15（iter 061-062）| **前端 UX 重构 + P0 热修**：iter061 extract-style `sample_path` 路径穿越热修（路由只传随机 token、handler 32-hex 校验后 data_dir 内重建路径）；iter062（基于 iter043 UX audit 三类残留痛点、针对性修复、保留零依赖 stdlib 架构）**报错收口**（新增 `src/web/errors.py` 错误目录 + 后端 ~15 处裸 `str(exc)`→友好 card + 前端 `renderErrorCard`/`_fetchWrapped` 网络·超时·坏JSON 分类 + 全局错误边界）/ **导航补全**（topbar 常驻 ⌂ home + 工作台可点回看步骤条 + 单一「下一步」CTA + 深层页「回概览」）/ **假按钮上锁**（drama ③④ tab disabled+🔒+即将上线、hash 不强切 + readiness/书架卡/overview 阻断项人话翻译 + 禁用按钮 title 说明）；铁律⑨ 2 视角 subagent 审查 P0/P1/P2 全修 + /security-review 无 ≥MEDIUM（净改进安全姿态）。canonical **1201** tests OK | 完成 |
| 阶段 16（iter 063）| **codex iter062 复审 bug 收口 + 后端审查①-⑦清零 + readiness 目录合并 + 移动端导航审计 + iter061 登记**：codex 3 视角 + Playwright 复审 iter062 暴露 7 个回归/遗漏（A1 plan-chapters 裸 ValueError→blocked 友好卡 + pollJob 卡化 / A2 剩余裸 `str(exc)`→card + `errTitle` toast / A3 wizard 上传卡中文化 / A4 `pattern` `v`-flag 裸连字符 SyntaxError→转义 / A5 timeout 校验后丢弃（=后端审查②）→携带 / A6 章节页文案 / A7 `#edit` 深链）全修；顺延的后端代码审查 **①-⑦** 全收（① 孤儿版权样本取消即泄漏=P0-A 护栏：handler try/finally + glob 清扫 + dispatch finally per-token 清扫覆盖 queued-cancel / ③ `/run` timeout `maximum=1440` / ④ 坏 meta 降级不覆盖 / ⑤ readiness clamp `clamped` 上报 / ⑥ 无效 token→blocked 删后门 / ⑦ drama/plan reservation 扩到包 run）；**三份 readiness 目录合并**（新建核心层 `src/readiness_catalog.py`，`book_runner._primary_blocker` + `errors._READINESS` + 前端注入 `window.READINESS_CATALOG` 全派生）；移动端 iter062 新导航元素 375px 审计（已适配，无需新增 @media）；iter061 四处登记补全。铁律⑨ `/code-review high`（3 finder 角度，3 发现全处理含本轮引入的 toast/card 回归）+ `/security-review` 无 ≥MEDIUM。canonical **1214** tests OK | 完成 |
| 阶段 17（iter 064）| **Codex findings 收口：CLI/Web 健壮性对齐 + 硬化**（6 条 finding 全核验属实，前 5 条有界硬化，语义闭环 large→iter065+）：**#1** 新建核心层 `src/run_params.py`（cap 表 + finite 守门）统一 CLI/Web/driver——Web 改薄包装复用、`main.py` 4 arm + `book_driver._build_params` 硬拒绝 `SystemExit(2)`、`book_runner` budget finite 末线防御（`--chapters 999999999` 不再 OOM、`--budget-cny nan` 不再绕过成本闸）/ **#2** `OutlineStale(ValueError)` 统一 plan-chapters stale-outline 出口（CLI 复用 `readiness_catalog` 友好文案 + exit4，不再裸 ValueError）/ **#3** 移动端 `.topbar-actions` 作用域到 `.topbar-actions-wrap`（不再误伤概览/章节内容按钮）/ **#4** `errors._redact_paths` 脱敏错误卡——收官审查补漏 12 处 handler 裸 `error` 键同类泄漏（新增 `exception_body` 两字段脱敏）+ 父目录含空格路径完整脱敏（P1）/ **#5** `WORKSPACE_NAME_HTML_PATTERN` 单源（前后端 `foo-` 一致拒绝）。铁律⑨ 3 维度 workflow 审查 + 对抗验证（correctness 零、reuse 零、security 1×P1 已修）；Aeloon §11.4 待同步登记。canonical **1250** tests OK | 完成 |

阶段小结：[stage_01](docs/stage_01_summary.md) · [stage_02](docs/stage_02_summary.md) · [stage_03](docs/stage_03_summary.md)。会话延续锚点：[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md)。

## 流水线 SOP（实时状态）

一条续写指令从输入到输出经过 9 个阶段，下面是各节点当前的打通状态。这是一份活文档，每轮 iter 收官时同步。最近一次更新：**iter 076**（2026-07-02，收官）——**长跑可靠性硬化 + iter074/075 codex 修复批（capstone 前置门，直击「过夜不跑废」）**：五个 HIGH 全落地——① **面板拒稿不再 halt 整书**：`agents.yaml` 新 `panel_block_policy {on_soft_reject, max_panel_rejections, on_hard_reject}`（默认全保守=原行为逐字节回归）；reviewer report 顶层 `hard_reject` 区分 synthetic 硬拦（plan_compliance/deterministic_relations）与面板 soft 拒稿，soft 可 `caveat_continue` 放行（meta 标 `caveat_approved`、verdict 仍 Reject 晨查入口不变、resume 走 `skipped_caveat` 不重写、配额跨 run 累计计入盘面存量）、hard 可 `force_once` 给一轮 bonus 重写；② **每章预算预留**：`estimate_next_chapter_cost`（costs 累计值差分+近 3 章滑动均值+config default）×`safety_factor`，动笔前余额不足 → `budget_exceeded+reserve_stop` 干净停不留半成品（闸位于 skip/补外审分支之后，零花费路径不误停）；③ **分档 step 超时**：drive-book 新 `--debate/--plan/--write-timeout-minutes`（fallback `--step-timeout-minutes`，start/resume 双侧校验）；④ **driver 心跳**：`_run_step` 30s 切片 poll 写 `logs/driver/driver_heartbeat.json`（shell 友好 `epoch`），watchdog 新 `--driver` 模式读心跳判活（语义分层：心跳测 driver 进程、child 卡死由 step 超时兜）+ abort 前写 `watchdog_abort.json` 标记 + TERM→30s→SIGKILL 升级 + abort 后留场看护；⑤ **crash 自动重启**：新 `scripts/drive_book_supervised.sh` 前台循环 start/resume（exit code×status×paused_reason×标记新鲜度决策表、指数退避、`SUPERVISE_MAX_RESTARTS=5` + `SUPERVISE_MAX_ROUNDS=48` 双上限、`supervise.pid` 互斥、caffeinate、确认闸同款），driver paused 出口落 `paused_reason` 区分「step 超时该自动 resume」与「pause-after-segment 人工意图」。前置 A 部分修 codex 审查 iter074/075 六项主发现（全属实）+ 低风险批：search manifest 越界读收容（resolve+relative_to 防 symlink）/ `?sources=` 空值 keep_blank_values / 搜索与 diff 前端 stale guard（seq 提前 + diffSeq + select 自动重跑）/ total_matches 截断前求和 / versions 零正文 IO+symlink 收容（chars→size_bytes）+ compute_diff 输入 500k·输出 5000 行上限 / path 投影相对化 / 搜索页 URL 恢复 + aria-label + ≥2 字门槛。**铁律⑨双视角 subagent 审查**：正确性视角确认重试 while+bonus/caveat fall-through/切片数学/决策表无问题；安全视角铁律①②零命中；3 MED（预留闸误停补外审、watchdog 一发即退无 KILL 升级、caveat 配额跨 run 重置）+ 9 LOW 全修或 doc 声明，残留仅理论性条目附理由。mock 25 章长流程回归三关全过（succeeded+25/25 Approve+心跳新鲜 / resume 零新 LLM 调用 / supervisor --resume-first 真集成 exit 0）。canonical **1475 tests OK**（见 iteration_076 Acceptance Result；数字以收官全量为准）。过夜推荐入口：`nohup bash scripts/drive_book_supervised.sh --book <名> --confirm-real-smoke -- --chapters 20 --tier mid ... &` + `bash scripts/watchdog.sh --book <名> --driver`。

图例：✅ 已打通　⚠️ 部分打通（含 gap）　❌ 未打通

### 阶段 1 — 输入准备
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 1.1 | normalize（小说 txt 标准化）| ✅ | iter 001 |
| 1.2 | split → chapter_manifest.json | ✅ | iter 002，多语言 iter 018 |
| 1.3 | 原文留 `小说txt/` 供下游读 | ✅ | writer 起 iter 021 开始读 |

### 阶段 2 — 知识抽取
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 2.1 | extract（采样章节抽 entity/fact）| ✅ | iter 003 |
| 2.2 | compress → global_knowledge.md | ✅ | iter 004 |
| 2.3 | bootstrap × 5（facts/graph/anchor/style/personas）| ✅ | iter 015-016 |
| 2.4 | apply-bootstrap × 5 | ✅ | iter 015 |

### 阶段 3 — 起点判断
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 3.1 | 用户指定起点（`set-start-point chapter_id\|volume_id`）| ✅ | iter 021；iter 027 起 `write_book.sh` 默认强制要求 |
| 3.2 | bootstrap_continuation_anchor 按起点采样原文 | ✅ | iter 021（A1 闭环） |

### 阶段 4 — 关系/世界观激活
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 4.1 | load entity_graph + active state | ✅ | iter 011 |
| 4.2 | load global_facts | ✅ | iter 010 |
| 4.3 | load personas | ✅ | iter 016 |
| 4.4 | 按起点过滤剧透 — global_facts | ✅ | iter 021 |
| 4.5 | 按起点过滤剧透 — entity_graph relationships | ✅ | iter 021 基础 chapter_id 过滤；iter 047d 补 `reader_known` / `character_known`（POV viewpoint）过滤，无新字段时与 021 字节一致（fail-open） |
| 4.6 | 按起点过滤剧透 — KB | ✅ | iter 028 preflight WARN；iter 047b `kb_view.start_safe_knowledge` 真实起点安全视图，plot_planner / 外部 review 已消费 |

### 阶段 5 — 情节规划
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 5.1 | debate → outline.md | ✅ | iter 005 |
| 5.2 | plot_planner 读 KB + rolling_summary + entity + outline | ✅ | iter 021（A3 修复） |
| 5.3 | 写完 K 章后自动 re-plan（plot_planner --append --from-chapter）| ✅ | iter 029 由 `write-book --replan-every K` 触发 |

### 阶段 6 — 写作（writer）
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 6.1 | read KB + facts + entity_state + chapter_plan + rolling_summary + style | ✅ | iter 011-016 |
| 6.2 | read 起点前 K 章原文 | ✅ | iter 021（A2 修复） |
| 6.3 | lint 自检 × 3 轮 rewrite | ✅ | iter 010 |
| 6.4 | lint 阈值动态化（按字数缩放）| ✅ | iter 022 B1（4000 字 base × dynamic scale）|
| 6.5 | writer prompt 加 anti-pattern（去字面例避免 priming）| ✅ | iter 022 B2 |
| 6.6 | writer 读 scene-matched 经典片段（按 chapter_plan 选段）| ✅ | iter 023 P3（替代硬切起点前 K 章）|
| 6.7 | 失败时 partial draft 落盘 | ✅ | iter 039 write/review/budget 异常保留 `chapter_NN.partial.md` + `chapter_NN.failure.json` |

### 阶段 7 — 审核
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 7.1 | 5+1 agent reviewer panel（精简自 iter 022 的 8 agent）| ✅ | iter 023 P4（合并情感/连续/关系 3 agent → 1，加 1 advisor）|
| 7.2 | fail-closed parse_failed → Abstain | ✅ | iter 019 audit |
| 7.3 | reviewer sub-score（plot/prose/fidelity 3 维 + 单 score legacy）| ✅ | iter 022 B3（真模型实测分化：plot 4-8 区分度首现）|
| 7.4 | reviewer 读 KB + 起点附近原文 + scene-matched 经典片段 | ✅ | iter 022 B4 + iter 023 P3；iter 042 修 external `review_target()` source context 漏传 |
| 7.5 | 程序化关系一致性检测（deterministic_relations）| ✅ | iter 023 P5（0 LLM 成本，替代 LLM agent）|
| 7.6 | 改写顾问 advisor（不投票，输出 RewriteSuggestion 列表）| ✅ | iter 023 P4（配置）+ iter 024 P1（writer rewrite-loop 真消费）|
| 7.7 | external review verdict 回写 writer meta | ✅ | iter 040 `book_runner._sync_meta_with_external_review()`；`require_external_review=True` 下 meta/review 文件状态一致 |
| 7.8 | reviewer 三档打分阈值 | ✅ | iter 042 `WRITE_REVIEW_TIER` / Web job param 支持 `high/mid/low`；5 agent panel 用 `approve_count + panel_score` 判定，默认 `mid` |

### 阶段 8 — 关系更新
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 8.1 | writer 写完调 propose_entity_advance | ✅ | iter 019 |
| 8.2 | apply-advance --auto-apply --min-confidence | ✅ | iter 019 |
| 8.3 | proposal 与 plan 冲突检测（apply-advance 前 dry-run）| ✅ | iter 029 进入 `book_runner` auto-advance 链路；iter 042 approved 后 apply-advance 缺失关系降级 no-op，避免尾部异常拖垮 job |

### 阶段 9 — 滚动到下一章
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 9.1 | rolling_summary 更新 | ✅ | iter 013 |
| 9.2 | rolling_summary 分层（摘要 + 最近 K 章原文片段）| ✅ | iter 022 B5（schema 加 text_snippet 字段）|
| 9.3 | per-章 cost 实时报告 + budget ceiling | ✅ | iter 029 `write-book --budget-cny N` 返回 `budget_exceeded` / exit 3；iter 039 write/review/polish 章内预算检查；iter 076 章前预留闸（剩余 < safety×下章预估 → `reserve_stop` 干净停，不留半成品） |

### infra & UI
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| I.1 | `write_book.sh` wrapper | ✅ | iter 029 只透传到 `python3 main.py write-book` |
| I.2 | shell 生产循环退出码问题 | ✅ | iter 029 shell 不再拥有循环，退出码由 Python CLI 返回 |
| I.3 | 长程续写起点/plan 一致性硬门 | ✅ | iter 027（缺 start point / plan 无 `start_chapter_id` / plan 与当前 start 不一致均失败）|
| I.4 | 生产写作入口 `write-book` 严格 runner | ✅ | iter 028（start/plan/draft/review 指纹、stale 归档、blocked/succeeded/failed snapshot）|
| I.5 | `write-readiness` 就绪检查 | ✅ | iter 029（ready/warn/blocked + blockers/warnings/recommended_commands）|
| I.6 | 面板拒稿整书策略 `panel_block_policy` | ✅ | iter 076（soft 可 `caveat_continue` 放行 + `max_panel_rejections` 预算 / hard synthetic 拒稿 `halt`\|`force_once` bonus 一轮；默认全保守=原 halt 行为；caveat 章 `verdict` 仍 Reject 供晨检，resume 跳过不重写）|
| I.7 | drive-book 分档超时 + driver 心跳 | ✅ | iter 076（`--debate/--plan/--write-timeout-minutes` 缺省回落 `--step-timeout-minutes`；`_run_step` 30s 切片写 `logs/driver/driver_heartbeat.json`（shell 友好 `epoch`）；心跳测 driver 进程、child 卡死由 step 超时兜；`watchdog.sh --driver` 读心跳判活、abort 前写 `watchdog_abort.json` 标记）|
| I.8 | crash 自动重启 supervisor | ✅ | iter 076 `scripts/drive_book_supervised.sh`（前台循环 start/resume；exit code × `status` × `paused_reason` × watchdog 标记决策表；指数退避封顶 60s、默认 5 次超限 exit 75 升级人工、存活 ≥600s 计数归零；自带 caffeinate 与真模型确认闸；过夜入口 `nohup ... supervised.sh --book X -- --chapters 20` + `watchdog.sh --driver`）|
| U.1 | WebUI dashboard | ✅ | iter 025（`python3 main.py web` 起 stdlib http.server；workspace 列表 + 4 panel 全量 reviews）|
| U.2 | 模型切换 panel + onboarding wizard | ✅ | iter 026（`/wizard` 上传 epub/txt → 后端 `auto-pipeline` 9 步 worker → ch1 落盘；`/settings` 读 .env + key 屏蔽 + 原子写）；iter 044 wizard 加 budget/timeout/extract limit、mock/real 标识与协作式 cancel |
| U.3 | `auto-pipeline` 子命令（CLI + wizard 共享绿地编排）| ✅ | iter 028 普通 Web 生产不再暴露 generic `auto-pipeline`；wizard 使用 `auto-pipeline-greenfield` |
| U.4 | Web job 状态持久化 + fail-closed summary | ✅ | iter 028（`succeeded/blocked/failed/aborted/lost`，Reject/needs_human_review 不算 success）；iter 039 live running job 不再误标 lost，blocked reason 读 `result_summary.first_blocked` |
| U.5 | Web “继续写书”本地 Beta 入口 | ✅ | iter 029（dashboard 显示 readiness、阻塞原因、推荐命令；普通区不展示 `draft-once-dev`）|
| U.6 | Web 写作工作台 | ✅ | iter 030-031（首页 workspace overview；详情页设置起点 / 覆盖式重生成计划 / 继续写书 / 只读 draft 预览 / 最近 job 恢复；iter 031 加坏 plan 容错、懒加载、debounce、短 TTL cache）；iter 039 write-book 细粒度 progress + partial draft 链接 |
| U.7 | Web 信息架构 + 视觉系统 | ✅ | iter 032（侧栏 + 工作区子页面 `/w/{name}/{overview,continue,chapters,chapter/{n},reviews,jobs}`；旧 `/workspace/{name}` → 301；文学化暖色调 design tokens；统一组件库；Chapter 详情页曝光 reviewer 子分数 / lint anchor / advisor / rewrite 历史）|
| U.8 | Web 日常使用补齐 | ✅ | iter 033（工作区二次确认软删除到 `_trash`；新增 `/w/{name}/insights` 数据页；lint anchor → 正文段落跳转 + 高亮；job terminal / 跨页删除 toast）|
| U.9 | Web type-aware workspace 基础设施 | ✅ | iter 036（`workspace.json` schema v1；旧 workspace 缺文件默认 novel；wizard drama-start 进入 drama 分支；novel-only 页面 404，`/run` 对 drama 400）|
| U.10 | Web drama 4 站审查向导（前 2 站）| ✅ | iter 037-038（drama wizard 5 字段 + `wizard_input.json` + `creation_standard.snapshot.md`；`/w/{name}/write` 4 tab；站 ①/② mock fixture-driven；iter 038 修 hook picker listener leak / rapid-click race，站 ③④ 仍待后续开放）|
| U.11 | Web 真实续写链路可观测/可恢复 | ✅ | iter 039（recent jobs running/lost 修复；blocked reason 展示；`variant=partial` draft API；chapters 页 partial/failure 行）；iter 040 meta/review verdict 同步；iter 042 `longzu` ch2 tier=mid 真实 happy path approved + job succeeded |
| U.12 | Web UX audit + 收尾响应式 | ✅ | iter 043 UX audit + D-1/D-2/D-3/D-4/D-6；iter 044 D-5/D-7/D-8，sidebar drawer、topbar actions 折叠、jobs/chapters/reviews 表格移动端横向滚动、Insights `scores || sub_scores` 兼容 |
| U.13 | Web 小白四步工作台 + 一句话开书 + 一键测 Key | ✅ | iter 048a-d：`/wizard` 加 premise-form（一句话开书，落 seed.txt 单章包装）→ `/w/{name}/workbench` 四阶段卡片（设定→大纲→细纲→正文，`prepare-greenfield` 复合 step 把前 6 步封单 job + 进度契约 `total/emit_done` 参数化）；mtime 链 stage gate（改 premise 重跑①后旧 outline/plan 自动失效）；大纲 textarea PUT `/outline` + `workspace_reserved` 闭锁；细纲只读 + "重新生成"绕开指纹链暗礁；`GET /api/diag/models` mock 短路 + Bearer/sk- 正则 redact。6 个 prep step 加 `_blocked(reason,error)` readiness check |
| U.14 | Web 全程可编辑闭环 | ✅ | iter 050a-b：stage③ 细纲每章内联结构化编辑（7 字段 + 数组增删 + 客户端预校验 + 已写章过期确认弹窗；服务端 Pydantic 校验 + `_attach_plan_fingerprints` 唯一真源重算，编辑后 write-book 零指纹失败）；章节详情「编辑」tab（保存 / 保存并重新评审 → `review-chapter` job，md+meta 同锁双写闭死 `draft_hash_mismatch`）；stage①「查看/编辑设定」面板（KB textarea + 实体 name/key_facts/description + 活跃关系 state；不可改 id/type/participants/timeline 键位）；D1/D4/D7/C3c/B3-hint 集中修 |

## 声明

- 这是研究性质的工程练习，不是产品。
- 原作小说不重新分发：`小说txt/`、`workspaces/*/小说txt/`、`data/`、`outputs/`、`logs/` 全部 gitignored，仓库只含代码、配置、prompt、文档、迭代日志。
- 生成的续写章节是源作品的衍生作品，只保留在本地。
- 换任何一本小说流程都一样：丢 `.txt` 或 `.epub` 进去，跑 `init-book`，后面的流水线一致。

## 技术栈

- Python 3.9+
- [LiteLLM](https://github.com/BerriAI/litellm)，多 provider 路由
- [Pydantic](https://docs.pydantic.dev/)，schema 唯一来源
- [tiktoken](https://github.com/openai/tiktoken)，token 计数（回落 `cl100k_base`）
- [python-dotenv](https://github.com/theskumar/python-dotenv)

没有 async，没有 web 框架，没有 orchestration 库。Web Dashboard 也是标准库 `http.server`，纯 Python + LLM + JSON I/O。
