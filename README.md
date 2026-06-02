<div align="center">

# Continuator / 续

**一条用工程方法构建的多 Agent 长篇小说续写流水线。**

[简体中文](README.md) · [English](README_EN.md)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-421_passing-brightgreen.svg)](#%E9%A1%B9%E7%9B%AE%E7%8A%B6%E6%80%81)
[![Iterations](https://img.shields.io/badge/iterations-31_logged-orange.svg)](docs/iterations/)
[![LiteLLM](https://img.shields.io/badge/router-LiteLLM-purple.svg)](https://github.com/BerriAI/litellm)
[![Mock-first](https://img.shields.io/badge/dev-mock_first-success.svg)](#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)

</div>

---

## TL;DR

读入一部已出版小说 → 构建结构化知识库 → 6 个 agent 辩论续写方向 → 用强推理模型规划 N 章 → 每章由便宜快模型生成 → 5 个 reviewer + 确定性 linter 质量把关 → **`write-readiness → write-book` 一个可靠的本地继续写书入口**。

**不是**"又一个套壳 GPT"。重点是**围绕 LLM 的工程脚手架**：19 轮 mock 优先的迭代、真模型验证、preflight 守门、reviewer fail-closed 抗 silent-approve、多 workspace 隔离、中英文双语切章 + stdlib EPUB 提取、每次调用的成本遥测。

实证：《龙族》（江南）+《冰与火之歌》（GRRM 英文）+ 自有小说均能跑通同一条流水线。最新真模型测试：**龙族 ch1 → Approve、13.8K 字符、单章成本 ~¥0.45**（gpt-5.5）。

> 原作小说本体被 gitignored。本仓库只发布引擎，不发布语料。

---

## 为什么这个项目值得点开

| 层 | 在代码里长什么样 |
|---|---|
| **Mock 优先开发** | 421 个单元测试，**几秒跑完**，一个 token 都不烧。`tests/__init__.py` 强制 `OPENAI_MODEL=mock`，防 `.env` 泄露污染测试。 |
| **Preflight 守门** | 真模型跑之前 7 类 FATAL 检查 + N 条 WARN：env / context limit / agents 配置 / rolling state / manifest 完整性 / **provider routing** / 人工事实 / cache 提供商提示。 |
| **多 workspace 隔离** | iter 017：每本书一个 `workspaces/<name>/{data,outputs,小说txt,logs}/`。`--book myBook` 切换；sha256 baseline 4/4 互不污染。 |
| **多语言切章 + EPUB 提取** | iter 018：CJK 字符比率自动判中英；中文 `第N章` / 英文 `CHAPTER / POV / 全大写` 两套 regex。`.epub` 用 stdlib `zipfile + xml.etree + html.parser` 直接转 txt，**零新依赖**。 |
| **本地 Beta 写作入口** | iter 029-030：CLI 用 `write-readiness -> write-book`；Web 首页显示每本书 readiness，workspace 工作台支持设置起点、生成计划、继续写书、查看草稿/阻塞原因。 |
| **Reviewer fail-closed** | iter 019 audit：5-agent 中任一 JSON 解析失败，记 `Abstain + _fallback_reason="(parse_failed)"`，不当 Approve；最终 verdict 任一 substantive Reject → Reject，零 substantive Approve → Reject。 |
| **带 timeline 的 Entity graph** | 角色/地点/概念作为 entity；关系携带 `timeline[]`，`active=true` 标记当前续写起点状态。**writer 只看 active state**；"关系一致性" reviewer 对照核验。 |
| **成本遥测** | 每次 LLM 调用记 `request_hash`、prompt/response tokens、cache_read/cache_write tokens。`estimate-cost` 按 provider 单价聚合。龙族 ch1 真模型实测：30 calls / 143K prompt（cache 命中 58%）/ 36K response / **~¥0.45**。 |
| **Persona 抽象** | iter 016：debate / reviewer 的 5 agent 不再硬编码龙族角色名；每本书 `init-book` 自动用 LLM 出 personas proposal → 人工审 → 落 `data/manual_overrides/personas.json`，模板渲染。 |
| **迭代日志** | [31 条](docs/iterations/)，每条 Context / Plan / Acceptance / 实测数字 / File summary 完整工程复盘。仓库本身就是一份工程日记。 |

---

## 快速开始

### Mock 模式 —— 不需要 API key，不联网

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
bash scripts/verify.sh      # 421 unit tests + 全流水线 mock，退出 0 = 接通
```

### 真模型模式（gpt-5.5 / deepseek / 任何 OpenAI 兼容 provider）

```bash
cp .env.example .env
# 编辑 .env，例如：
#   OPENAI_API_KEY=<OPENAI_API_KEY>
#   OPENAI_BASE_URL=https://your-gateway.example/v1
#   OPENAI_MODEL=openai/gpt-5.5
# 可选：PLANNER_* 三件套（不设则 planner 跟随 OPENAI_*）

python3 main.py preflight                                      # 7 类 FATAL 检查，非零退出 = 别跑真模型
python3 main.py --book myBook write-readiness --chapters 2     # 就绪/阻塞检查
bash scripts/write_book.sh --book myBook --chapters 2          # wrapper → python3 main.py write-book
```

### 接入任意小说（5 步走）

```bash
# 1) 起 workspace + 把 txt（或 .epub）丢进去
python3 main.py workspace-init myBook
cp ~/your-novel.txt workspaces/myBook/小说txt/
# 英文 EPUB 走 stdlib 提取：
# python3 main.py --book myBook epub-import --src ~/novel.epub --out myBook.txt

# 2) 自动检测语言 → 规范化 → 切章
python3 main.py --book myBook normalize
python3 main.py --book myBook split

# 3) LLM 出 5 类 proposal（entity_graph / global_facts / continuation_anchor / style_examples / personas），人工审过再 confirm
python3 main.py --book myBook init-book --extract-limit 10
# 编辑 workspaces/myBook/data/proposals/*.json 后：
for name in global_facts entity_graph continuation_anchor style_examples personas; do
  python3 main.py --book myBook apply-bootstrap --name $name --confirm
done

# 4) 设置续写起点 + 6-agent 辩论 + 强模型 N 章规划
python3 main.py --book myBook set-start-point <chapter_id_or_volume_id>
python3 main.py --book myBook debate
python3 main.py --book myBook plan-chapters --chapters 3 --force --require-start-point

# 5) 本地 Beta 写作入口
python3 main.py --book myBook write-readiness --chapters 3
bash scripts/write_book.sh --book myBook --chapters 3
# 标志：--max-retries N、--min-confidence X、--no-auto-advance、--replan-every K、--budget-cny N
# 退出码：0 = 全章 Approve，3 = budget_exceeded，4 = blocked
```

切换书只改一个 flag（`--book otherBook`），或 `export WORKSPACE_NAME=otherBook` 一次性生效。`workspace-list` / `workspace-show` 看现有 workspace。

### Run the writing cockpit（iter 030-031）

CLI 看完状态嫌切来切去？跑一个本地浏览器写作工作台：

```bash
python3 main.py web              # 默认 127.0.0.1:8765
# 或自定义端口
python3 main.py web --port 9999
```

打开 `http://127.0.0.1:8765/` 看所有 workspace 的 readiness / 起点 / plan / 草稿 / 最近 job；点进一本书后可以：

- 设置续写起点（chapter 或 volume）。
- 生成/重生成章节计划（Web job，强制 `--force --require-start-point`）。
- 检查阻塞原因与推荐命令。
- 启动 `write-book`，配置章节数、预算、replan、retry、entity auto-advance。
- 查看只读 draft 预览、review、manifest、status、cost。

stdlib only（http.server + string.Template + vanilla JS，**0 新依赖**）。默认绑 127.0.0.1 不外露；mock-only 验收；真模型长跑仍需用户明确授权。

#### Web 服务启动 / 换端口 / 关闭

推荐使用项目虚拟环境启动，避免系统 Python 缺依赖：

```bash
cd /Users/dingyuxuan/Desktop/Agent续写项目
.venv/bin/python3 main.py web                 # 默认 127.0.0.1:8765
.venv/bin/python3 main.py web --port 8766     # 8765 被占用时换端口
```

打开浏览器：

```text
http://127.0.0.1:8765/
http://127.0.0.1:8766/
```

关闭方式：

```bash
# 如果服务在当前终端前台运行
Ctrl+C

# 如果端口被旧进程占用，先查 PID 再 kill
lsof -ti tcp:8765
kill <PID>

# 也可以直接查 8766
lsof -ti tcp:8766
kill <PID>
```

判断端口是否被占用：

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

如果 8765 仍显示旧 UI，说明旧 server 没关；关闭旧 PID 后重新启动，或临时改用 `--port 8766`。

---

## 文件分区管理

每本书一个 workspace，默认结构如下：

```text
workspaces/<book>/
  小说txt/                 # 用户放入的原始 txt/epub 转换文本；gitignored
  data/
    normalized_texts/      # normalize 输出
    extracted_jsons/       # extract 输出
    knowledge_base/        # compress 输出
    manual_overrides/      # 用户确认后的 facts/entity/personas/start point 等
    proposals/             # init-book 生成、等待人工确认的 proposal
    chapter_manifest.json  # split 输出的章节索引
  outputs/
    debate/                # debate / chapter_plan.json / outline / decisions
    drafts/                # chapter_NN.md、meta、failure、snapshot
    reviews/               # chapter_NN.review.json
  logs/
    llm_calls.jsonl        # LLM 调用、token、成本遥测
    web_jobs.jsonl         # Web job 历史
```

管理原则：

| 区域 | 用途 | 是否提交 |
|---|---|---|
| `src/`, `config/`, `scripts/`, `tests/`, `docs/` | 代码、配置、测试、文档 | ✅ 提交 |
| `workspaces/<book>/小说txt/` | 用户本地原文输入 | ❌ 不提交 |
| `workspaces/<book>/data/` | 抽取、知识库、人工确认数据 | ❌ 不提交 |
| `workspaces/<book>/outputs/` | debate、plan、draft、review、snapshot | ❌ 不提交 |
| `workspaces/<book>/logs/` | 调用日志、Web job、成本记录 | ❌ 不提交 |
| 根目录 `data/`, `outputs/`, `logs/` | legacy / verify mock 路径 | ❌ 不提交 |

常用 workspace 命令：

```bash
python3 main.py workspace-list
python3 main.py workspace-show --name myBook
python3 main.py workspace-init myBook

# 所有生产命令都用 --book 指定目标书
python3 main.py --book myBook write-readiness --chapters 3
python3 main.py --book myBook write-book --chapters 3 --budget-cny 5
```

不要修改 `小说txt/` 中的原文内容；要修结构化事实、人物关系、风格片段，改 `data/manual_overrides/` 或重新生成/确认 proposal。旧 draft/review 不需要手动删除；生产 runner 会在 `--force` 或 retry 时归档 stale artifact。

## CLI 速查

| 命令 | 作用 |
|---|---|
| `workspace-{init,list,show,import-current}` | 多 workspace 管理（iter 017） |
| `epub-import` | EPUB → UTF-8 txt，stdlib only（iter 018） |
| `normalize` / `split` | 自动识别编码 + 语言；切章产 `chapter_manifest.json` |
| `init-book` | 一键产 5 类 proposal（entity_graph / facts / anchor / style / personas） |
| `apply-bootstrap --name X --confirm` | 审过的 proposal 落盘 |
| `debate` | 6 agent × 6 轮 + 结构化投票 → outline.md + decisions.json |
| `plan-chapters --chapters N` | 强模型一次出 N 章规划（iter 014） |
| `write --chapters N --resume-from i --force` | 多章生成 + 8 reviewer + lint + polish |
| `review-chapter <i>` / `chapter-status <i>` | 独立复审 / 单章状态 JSON（iter 019） |
| `apply-advance --chapter i --auto-apply --confirm` | entity advance（iter 019） |
| `preflight` / `status` / `estimate-cost` | 守门 / 状态 / 成本汇总 |

详见 [README_EN.md](README_EN.md)，含架构图、3-tier 执行说明、所有迭代日志索引。

---

## 项目状态

| 阶段 | 范围 | 状态 |
|---|---|---|
| 阶段 1（iter 001-005）| Mock 优先基础、CLI、preflight | ✅ |
| 阶段 2（iter 006-008）| 首次真模型 smoke + debate 结构化投票 | ✅ |
| 阶段 3（iter 009-013）| 写作质量轴：entity graph / 一致性 reviewer / 多章架构 | ✅ |
| 阶段 4（iter 014-019）| 多 workspace + 多语言 + 无人值守 + 审计加固 | ✅ |
| 阶段 5（iter 020+）| Web Dashboard + 本地 Beta 写作入口 | ✅ |

阶段小结：[stage_01](docs/stage_01_summary.md) · [stage_02](docs/stage_02_summary.md) · [stage_03](docs/stage_03_summary.md)。
会话延续锚点：[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md)。

---

## 项目阶段 SOP（实时状态）

一条完整续写指令从输入到输出途中的 9 个阶段 + 各节点当前打通状态。本节是**实时活文档**，每轮 iter 收官时同步更新。最近一次更新：**iter 031（2026-06-02）** — WebUI 写作工作台完成 post-iter030 hardening：首页坏 plan 单本 blocked 不拖垮全局、recent job 恢复尊重 workspace root、隐藏 tab 懒加载、readiness 输入 debounce、overview 短 TTL cache；真模型长跑仍待用户授权。

> 图例：✅ 已打通 ⚠️ 部分打通（含 gap） ❌ 未打通

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
| 3.1 | 用户指定起点（`set-start-point chapter_id\|volume_id`）| ✅ | **iter 021**；iter 027 起 `write_book.sh` 默认强制要求 |
| 3.2 | bootstrap_continuation_anchor 按起点采样原文 | ✅ | **iter 021**（A1 闭环） |

### 阶段 4 — 关系/世界观激活
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 4.1 | load entity_graph + active state | ✅ | iter 011 |
| 4.2 | load global_facts | ✅ | iter 010 |
| 4.3 | load personas | ✅ | iter 016 |
| 4.4 | 按起点过滤剧透 — global_facts | ✅ | **iter 021** |
| 4.5 | 按起点过滤剧透 — entity_graph relationships | ⚠️ | **iter 021** 仅过滤含 chapter_id 的；schema 升级 iter 022 |
| 4.6 | 按起点过滤剧透 — KB | ⚠️ | **iter 028** 先落 preflight WARN；真实 KB view / LLM 重写仍待后续 |

### 阶段 5 — 情节规划
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 5.1 | debate → outline.md | ✅ | iter 005 |
| 5.2 | plot_planner 读 KB + rolling_summary + entity + outline | ✅ | **iter 021**（A3 修复） |
| 5.3 | 写完 K 章后自动 re-plan（plot_planner --append --from-chapter）| ✅ | **iter 029** 由 Python `write-book --replan-every K` 触发 |

### 阶段 6 — 写作（writer）
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 6.1 | read KB + facts + entity_state + chapter_plan + rolling_summary + style | ✅ | iter 011-016 |
| 6.2 | read 起点前 K 章原文 | ✅ | **iter 021**（A2 修复） |
| 6.3 | lint 自检 × 3 轮 rewrite | ✅ | iter 010 |
| 6.4 | lint 阈值动态化（按字数缩放）| ✅ | **iter 022 B1**（4000 字 base × dynamic scale）|
| 6.5 | writer prompt 加 anti-pattern（去字面例避免 priming） | ✅ | **iter 022 B2** |
| 6.6 | writer 读 scene-matched 经典片段（按 chapter_plan 选段）| ✅ | **iter 023 P3**（替代硬切起点前 K 章）|

### 阶段 7 — 审核
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 7.1 | 5+1 agent reviewer panel（精简自 iter 022 的 8 agent）| ✅ | **iter 023 P4**（合并情感/连续/关系 3 agent → 1，加 1 advisor）|
| 7.2 | fail-closed parse_failed → Abstain | ✅ | iter 019 audit |
| 7.3 | reviewer sub-score（plot/prose/fidelity 3 维 + 单 score legacy）| ✅ | **iter 022 B3**（真模型实测分化：plot 4-8 区分度首现）|
| 7.4 | reviewer 读 KB + 起点附近原文 + scene-matched 经典片段 | ✅ | iter 022 B4 + **iter 023 P3** |
| 7.5 | 程序化关系一致性检测（deterministic_relations）| ✅ | **iter 023 P5**（0 LLM 成本，替代 LLM agent）|
| 7.6 | 改写顾问 advisor（不投票，输出 RewriteSuggestion 列表）| ✅ | iter 023 P4（配置）+ **iter 024 P1**（writer rewrite-loop 真消费）|

### 阶段 8 — 关系更新
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 8.1 | writer 写完调 propose_entity_advance | ✅ | iter 019 |
| 8.2 | apply-advance --auto-apply --min-confidence | ✅ | iter 019 |
| 8.3 | proposal 与 plan 冲突检测（apply-advance 前 dry-run）| ✅ | **iter 029** 进入 `book_runner` auto-advance 链路 |

### 阶段 9 — 滚动到下一章
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| 9.1 | rolling_summary 更新 | ✅ | iter 013 |
| 9.2 | rolling_summary 分层（摘要 + 最近 K 章原文片段）| ✅ | **iter 022 B5**（schema 加 text_snippet 字段） |
| 9.3 | per-章 cost 实时报告 + budget ceiling | ✅ | **iter 029** `write-book --budget-cny N` 返回 `budget_exceeded` / exit 3 |

### infra & UI
| # | 节点 | 状态 | 备注 |
|---|---|---|---|
| I.1 | `write_book.sh` wrapper | ✅ | **iter 029** 只透传到 `python3 main.py write-book` |
| I.2 | shell 生产循环退出码问题 | ✅ | **iter 029** shell 不再拥有循环，退出码由 Python CLI 返回 |
| I.3 | 长程续写起点/plan 一致性硬门 | ✅ | **iter 027**（缺 start point / plan 无 `start_chapter_id` / plan 与当前 start 不一致均失败） |
| I.4 | 生产写作入口 `write-book` 严格 runner | ✅ | **iter 028**（start/plan/draft/review 指纹、stale 归档、blocked/succeeded/failed snapshot） |
| I.5 | `write-readiness` 就绪检查 | ✅ | **iter 029**（ready/warn/blocked + blockers/warnings/recommended_commands） |
| U.1 | WebUI dashboard | ✅ | **iter 025**（`python3 main.py web` 起 stdlib http.server；workspace 列表 + 4 panel 全量 reviews） |
| U.2 | 模型切换 panel + onboarding wizard | ✅ | **iter 026**（`/wizard` 上传 epub/txt → 后端 `auto-pipeline` 9 步 worker → ch1 落盘；`/settings` 读 .env + key 屏蔽 + 原子写）|
| U.3 | `auto-pipeline` 子命令（CLI + wizard 共享绿地编排）| ✅ | **iter 028** 普通 Web 生产不再暴露 generic `auto-pipeline`；wizard 使用 `auto-pipeline-greenfield` |
| U.4 | Web job 状态持久化 + fail-closed summary | ✅ | **iter 028**（`succeeded/blocked/failed/aborted/lost`，Reject/needs_human_review 不算 success） |
| U.5 | Web “继续写书”本地 Beta 入口 | ✅ | **iter 029**（dashboard 显示 readiness、阻塞原因、推荐命令；普通区不展示 `draft-once-dev`） |
| U.6 | Web 写作工作台 | ✅ | **iter 030-031**（首页 workspace overview；详情页设置起点/覆盖式重生成计划/继续写书/只读 draft 预览/最近 job 恢复；iter 031 加坏 plan 容错、懒加载、debounce、短 TTL cache） |

---

## 范围 & 声明

- 这是**研究性质的工程练习**，不是产品
- 原作小说**不被重新分发**：`小说txt/` / `workspaces/*/小说txt/` / `data/` / `outputs/` / `logs/` 全 gitignored；仓库只含**代码 / 配置 / prompt / 文档 / 迭代日志**
- 生成的续写章节是源作品的衍生作品，只保留本地
- 任何小说都能跑：丢 `.txt` 或 `.epub` 进去，跑 `init-book`，剩下的流水线一致

---

## 技术栈

- **Python 3.9+**
- [LiteLLM](https://github.com/BerriAI/litellm) —— 多 provider 路由
- [Pydantic](https://docs.pydantic.dev/) —— schema 唯一来源
- [tiktoken](https://github.com/openai/tiktoken) —— token 计数（`cl100k_base` 回落）
- [python-dotenv](https://github.com/theskumar/python-dotenv)

无 async、无框架锁定、无 orchestration 库、无 web 框架（iter 020 Web Dashboard 也坚持 stdlib `http.server`）。纯 Python + LLM + JSON I/O。

---

<div align="center">

用 31 轮 *先测量，再 commit* 建出来的项目。

</div>
