# Continuator / 续

最近一次更新：**iter 169**（2026-09-05，完整验收基线）

活动迭代：**iter170**（2026-09-06，工程通过，真实验收未完成；本页SOP已同步当前实现）。

本地运行的多 agent 小说续写流水线。它将知识抽取、情节规划、正文生成、审稿和关系推进拆成可恢复步骤；开发与标准验收默认使用 mock，不产生计费模型请求。

中文 · [English](README_EN.md)

> iter167 起，`main` 是小说专用主线。完整短剧实现固定保存在 `codex/short-drama`；main 只保留不可点击的入口外观，不创建、枚举、迁移或删除旧短剧 workspace。

原作语料与运行产物不进仓库：`小说txt/`、`workspaces/*/小说txt/`、`data/`、`outputs/`、`logs/` 均已忽略。仓库只保存引擎、配置、测试和文档。

## 核心能力

- 小说原创与导入续写：权威 `creation_mode`、起点安全视图、知识提案、情节辩论、章节规划、写作与评审。
- 质量守门：当前 plan/run-context 指纹、5+1 reviewer、确定性 lint、预算/超时、文风漂移与受控重写。
- 长跑恢复：`write-book`、`drive-book`、supervisor、heartbeat/watchdog、workspace 写锁和断点续跑。
- 本地 Web：四阶段工作台、设定/大纲/细纲/正文编辑、任务恢复、搜索、版本比较和创作数据。
- 安全隔离：HTTP mutation/intent、provider 异常和日志读取默认 fail closed；旧 `type=drama` metadata 只用于识别并拒绝。

当前验收基线、真实验证边界和下一步统一见 [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md)。

## 快速开始

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
bash scripts/verify.sh
```

`verify.sh` 是唯一标准验收入口：无参数运行，固定使用项目虚拟环境，强制 mock/offline，并在系统临时 synthetic workspace 中执行 harness、novel-only 边界检查、一次全量单测、mock pipeline 和 preflight。脱敏 schema v3 结果写入 `outputs/harness/acceptance.json`；它只能产生 `mock-functional` 证据。

真模型配置仅放在本地 `.env`。先运行 `python3 main.py preflight`；任何真实 smoke 都需要本次明确授权。

## 接入一本书

```bash
python3 main.py workspace-init myBook
cp ~/your-novel.txt workspaces/myBook/小说txt/

python3 main.py --book myBook normalize
python3 main.py --book myBook split
python3 main.py --book myBook init-book --extract-limit 10

for name in global_facts entity_graph continuation_anchor style_examples personas; do
  python3 main.py --book myBook apply-bootstrap --name $name --confirm
done

python3 main.py --book myBook set-start-point <chapter_id_or_volume_id>
python3 main.py --book myBook debate
python3 main.py --book myBook plan-chapters --chapters 3 --force --require-start-point
python3 main.py --book myBook write-readiness --chapters 3
bash scripts/write_book.sh --book myBook --chapters 3
```

原创 workspace 可通过 Web 向导创建，不需要续写起点。导入续写 workspace 必须先选择起点。完整上手说明见 [`docs/product/GETTING_STARTED.md`](docs/product/GETTING_STARTED.md)。

## 本地 Web

```bash
python3 main.py web              # 127.0.0.1:8765
python3 main.py web --port 9999
```

Web 只管理小说 workspace。首页与作品列表中的短剧按钮为原生禁用控件，显示“短剧模块暂未开放”，不含链接或点击处理器。旧短剧 workspace 会隐藏，直接访问返回 404。

## CLI 速查

| 命令 | 作用 |
|---|---|
| `workspace-{init,list,show,import-current}` | 小说 workspace 管理 |
| `epub-import` | EPUB 转 UTF-8 txt |
| `normalize` / `split` | 文本标准化与自动语言切章 |
| `init-book` / `apply-bootstrap` | 生成并确认知识提案 |
| `debate` / `plan-chapters` | 方向辩论与章节规划 |
| `write-book` / `write-readiness` | 生产写作与写前守门 |
| `review-chapter` / `chapter-status` | 单章复审与状态 |
| `apply-advance` | 关系推进审批/自动应用 |
| `foreshadowing list/resolve/ttl` | 查看伏笔、确认当前正文回收证据、调整期限 |
| `drive-book start/status/resume/stop/report` | 长程驱动与恢复 |
| `style-fingerprint` / `style-drift` | 文风 baseline、检测与报告 |
| `web --port 8765` | 本地 Web 工作台 |
| `preflight` / `status` / `estimate-cost` | 守门、状态与成本 |

`drama-project-archive` 和所有短剧 Web/API/job/media 接口不属于 main。完整参数以 `python3 main.py <command> --help` 为准。

## 流水线 SOP（实时状态）

| 阶段 | 动作 | 状态 |
|---|---|---|
| 1. 导入与标准化 | 建立小说 workspace、normalize 原文 | ✅ |
| 2. 自动切章 | 消费规范化 txt，保留跨卷同名章，排除局部目录，生成 manifest 与置信度报告 | ✅ |
| 3. 知识抽取 | 人物、事件、关系和章节事实；Web 单步支持进度与取消 | ✅ |
| 4. 知识压缩与确认 | 五类 proposal、人工确认、起点安全视图；单步支持取消 | ✅ |
| 5. 情节规划 | 大纲人工版本、chapter plan、全书进度 re-plan 与窗口补齐 | ✅ |
| 6. 写作 | 多上下文 writer、润色后重检 lint、失败章安全恢复；force失效后续旧记忆 | ✅ |
| 7. 审核 | 当前正文复审、安全归档旧 lint 失败；记忆更新后才 strict-approved | ✅ |
| 8. 关系更新 | proposal、conflict check、auto-advance；手改失效旧推进，伏笔凭证据确认 | ✅ |
| 9. 滚动下一章 | 当前稿记忆、逐章伏笔期限、保留远期计划、预算与 runner/supervisor | 🟨 工程已通；本次已授权真实测试继续，10章提取已完成，全链待验收 |

## 项目状态

- iter001-079：小说基础链、质量、起点安全、生产 runner、本地 Web 和可靠性工程闭环。
- iter080-164：历史上同时发展短剧能力；记录继续保留在 [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) 和 iteration 文档中。
- iter153-156、165-166：小说 Web Phase A-E、原创/续写权威模式和失败恢复闭环。
- iter167：完整基线保存在 `codex/short-drama`，main 收敛为 novel-only；canonical 升级为 schema v3 / `canonical-novel-mock-offline`。
- iter168：闭环 Web mutation/付费守门、LLM 安全异常、逐章 freshness 和有界日志；synthetic 三视口达 `local-e2e`，真链在 entity graph `submission_unknown` 后零重提并记 `safe-blocked`。
- iter169：编辑保存按提交版本确认；手改后的记忆恢复、分段规划和伏笔证据形成可回归的长程恢复流程。

iter170：合集导入、编辑版本冲突、日志长期容量、CLI计费停止及前三阶段可调预算已通过工程与浏览器回归；真实续写未通过，当前完整接受基线仍为iter169。

最新 canonical：implementation `f4eadb9`，1971 tests / 15 steps / 101 秒，`mock-functional`，`tracked_scope_clean=true`。这不代表真实 provider 完整链、长篇质量或 SLA 已验证。

## 目录结构

```text
workspaces/<name>/
  小说txt/                 本地原始文本，不提交
  data/                    标准化、抽取、知识库、人工确认数据
  outputs/                 debate、draft、review 产物
  logs/                    LLM 与 job 审计日志

src/                       小说流水线与本地 Web
config/                    agent/model/linter/style 配置
scripts/                   verify、smoke、长跑入口
tests/                     mock 隔离测试
docs/AGENT_HANDOFF.md      当前状态
docs/PROJECT_HISTORY.md    压缩里程碑
docs/iterations/           逐轮审计记录
```

不要直接修改 `小说txt/` 原文。设定、关系、起点和风格样本通过 `manual_overrides` 或 proposal 审批路径维护。

## 文档导航

| 问题 | 文档 |
|---|---|
| 当前能力、缺口、最新测试 | [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) |
| 历史架构与工程教训 | [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) |
| 每轮计划、验收、审查 | [`docs/iterations/README.md`](docs/iterations/README.md) |
| 上手操作 | [`docs/product/GETTING_STARTED.md`](docs/product/GETTING_STARTED.md) |
| 小说 Web UI/UX 规范 | [`docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`](docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md) |
| 短剧分支迁移说明 | [`docs/product/short_drama_module.md`](docs/product/short_drama_module.md) |

## 声明与技术栈

这是研究性质的个人创作工具，不是公网多租户产品。原作小说不重新分发，生成内容和本地运行数据不提交。技术栈为 Python 3.9+、LiteLLM、Pydantic、tiktoken、python-dotenv；Web 使用标准库 HTTP server 与原生 JS。

本地 Web 使用 OpenAI 兼容服务且长响应遇到网关超时，可在启动进程中显式设置 `OPENAI_WEB_STREAM=1`。仅 macOS/Linux 上 `openai/` 模型的 Web 任务使用原生 SDK 流式接收，独立进程在取消或总时限到达后退出；正文不完整时不保存半截响应，也不自动重发。缺失服务计量时保留费用未知和预算预留。默认传输保持不变；此选项不保证所有中转服务或模型参数都兼容。
