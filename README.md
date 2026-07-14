# Continuator / 续

本地运行的多 agent 小说续写与短剧创作流水线。它把知识抽取、情节规划、正文生成、审稿、关系推进和媒体任务拆成可恢复步骤；开发默认使用 mock，不产生计费模型请求。

中文 · [English](README_EN.md)

原作语料与运行产物不进仓库：`小说txt/`、`workspaces/*/小说txt/`、`data/`、`outputs/`、`logs/` 均已忽略。仓库只保存引擎、配置、测试和文档。

## 核心能力

- **小说续写**：normalize → split → extract → compress → debate → plan → write → review → rolling/advance。
- **质量守门**：起点安全视图、指纹、5+1 reviewer、确定性 lint、预算/超时、文风漂移与一次受控重写。
- **长跑恢复**：`write-book`、`drive-book`、supervisor、heartbeat/watchdog、workspace 写锁、断点续跑。
- **本地 Web**：四步工作台、设定/大纲/细纲/正文编辑、job 恢复、全文搜索、版本 diff、Insights。
- **短剧**：五站 job、分镜 grid、角色库、review/assembly、连续多集、单集四导出、整季母包/阶段快照，以及角色生图与 episode 1 视频安全入口。

当前验收基线、真实验证边界和下一步统一见 [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md)。

## 快速开始

mock 模式不需要 key、不调用模型 provider，也不会联网刷新 LiteLLM cost map；项目会在 LiteLLM 首次导入前强制使用其内置副本并跳过真实模型代理探测：

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
bash scripts/verify.sh
```

`verify.sh` 是唯一标准验收入口：只接受无参数运行，固定使用项目虚拟环境，强制 mock/offline，在系统临时 synthetic workspace 中只运行一次全量单测、mock pipeline、preflight 与 harness 一致性检查；脱敏 schema v2 结果写入 `outputs/harness/acceptance.json`。它只能产生 `mock-functional` 级别证据。

真模型配置放在本地 `.env`，先跑 preflight；真实 smoke 必须经过单独授权。

```bash
cp .env.example .env
# OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
# planner 可另配 PLANNER_*；否则跟随 OPENAI_*
python3 main.py preflight
```

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

常用写作参数：`--max-retries`、`--budget-cny`、`--tier low|mid|high`、`--no-auto-advance`、`--replan-every`。退出码 0 表示完成，3 表示预算停止，4 表示被守门阻塞。

## 本地 Web

```bash
python3 main.py web              # 127.0.0.1:8765
python3 main.py web --port 9999
```

Web 可管理小说与短剧 workspace，显示 readiness、job、草稿、review、章节历史和 Insights。它基于标准库 `http.server` 与原生 JS，默认只绑定本机；当前定位是个人研究工具，不是公网多租户服务。

## 目录结构

```text
workspaces/<name>/
  小说txt/                 本地原始文本，不提交
  data/                    标准化、抽取、知识库、人工确认数据
  outputs/                 debate、draft、review、drama/episode 产物
  logs/                    LLM 与 job 审计日志

src/                       主代码
config/                    agent/model/linter/style 配置
scripts/                   verify、smoke、长跑入口
tests/                     mock 隔离测试
docs/AGENT_HANDOFF.md      当前状态
docs/PROJECT_HISTORY.md    压缩里程碑
docs/iterations/           逐轮审计记录
```

不要直接修改 `小说txt/` 原文。设定、关系、起点和风格样本通过 `manual_overrides` 或 proposal 审批路径维护。

## CLI 速查

| 命令 | 作用 |
|---|---|
| `workspace-{init,list,show,import-current}` | workspace 管理 |
| `epub-import` | EPUB 转 UTF-8 txt |
| `normalize` / `split` | 文本标准化与自动语言切章 |
| `init-book` / `apply-bootstrap` | 生成并确认五类知识 proposal |
| `debate` / `plan-chapters` | 方向辩论与章节规划 |
| `write-book` / `write-readiness` | 生产写作与写前守门 |
| `review-chapter` / `chapter-status` | 单章复审与状态 |
| `apply-advance` | 关系推进审批/自动应用 |
| `drive-book start/status/resume/stop/report` | 长程驱动与恢复 |
| `style-fingerprint` / `style-drift` | 文风 baseline、检测与报告 |
| `web --port 8765` | 本地 Web 工作台 |
| `preflight` / `status` / `estimate-cost` | 守门、状态与成本 |

完整参数以 `python3 main.py <command> --help` 为准。

## 项目状态

| 里程碑 | 迭代 | 状态 |
|---|---|---|
| mock 基础与首次真模型链路 | 001-008 | ✅ 完成 |
| 写作质量、多章、通用化、无人值守 | 009-019 | ✅ 完成 |
| 起点安全、生产 runner、本地 Web Beta | 020-050 | ✅ 完成 |
| 真模型质量、长程驱动、安全与可靠性 | 051-079 | ✅ 工程闭环；小说 capstone 待授权实跑 |
| 短剧核心与文风量化闭环 | 080-087 | ✅ 完成 |
| 短剧交付与真实媒体安全入口 | 088-092 | ⚠️ 工程闭环；真多模态待分段授权校准 |
| 短剧多集与整季交付闭环 | 095 | ✅ mock 工程闭环；真多模态仍待分段授权 |
| Agent 记忆、历史归档与收官流程 | 093-094 | ✅ 当前/历史职责分离；恢复精选工作记忆；全量验收后置 |
| Mock 严格离线与验证环境一致性 | 096 | ✅ 本地 cost map、零代理探测、零 tokenizer 下载；verify 固定项目虚拟环境 |
| 短剧真模型全链审计硬化 | 097 | ✅ 付费授权/恢复、provider 身份、媒体下载与 durable submission ledger 已收口；真校准仍待分段授权 |
| 短剧真模型二次全链硬化 | 098 | ✅ 五站产物血统、付费 crash 恢复、实际 peer 传输与媒体规格复核已收口；真校准仍待分段授权 |
| 短剧真模型第三次全链硬化 | 099 | ✅ readiness/身份/脏账本、图片结构与 submitted 恢复已收口；真校准仍待分段授权 |
| 短剧真模型全链阻塞修复 | 100 | ✅ 跨进程 callback、稳定恢复身份、媒体 crash receipt 与 Web 逐次授权已收口；真校准仍待分段授权 |
| 短剧完整链路残余阻塞修复 | 101 | ✅ 文本 revision、Approve 血统、旧 workspace 媒体接管、多集角色与 submitted 纯轮询恢复已收口；真校准仍待分段授权 |
| 标准验收隔离与审计基线 | 102 | ✅ 无参数 canonical 入口、synthetic workspace、dotenv 物理短路、evidence v2 与 accepted commit 守门已收口 |
| 本地 Fake Provider 整链 | 103 | ✅ 图片/视频/callback/五站授权 loopback `local-e2e` 已纳入 canonical；不代表真供应商验证 |
| Crash/Restart 与状态矩阵 | 104 | ✅ 五站文本、图片六阶段、视频六阶段经生产入口与跨进程 `os._exit` 验证；付费状态已集中，未做 ledger 大重构 |

历史里程碑见 [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md)，逐轮验收见 [`docs/iterations/README.md`](docs/iterations/README.md)。

## 流水线 SOP（实时状态）

最近一次更新：**iter 104**（2026-07-14，收官）。Canonical 继续必跑本地 fake-provider 短剧整链；新增测试专用跨进程 crash/restart 与状态穷举矩阵，五站文本、图片六阶段、视频六阶段均调用生产恢复入口并核对 provider 次数与产物血统。组件证据仍为 `local-e2e`，总验收仍为 `mock-functional`，不等于真供应商校准。未运行真实文本、生图或视频。

图例：✅ 已打通　⚠️ 工程已通但真实校准未完成　❌ 未打通

| 阶段 | 当前能力 | 状态 | 关键迭代 |
|---|---|---|---|
| 运行基础 | mock 严格离线、dotenv 物理短路、隔离 synthetic workspace、accepted commit/evidence 审计绑定、必跑 local-drama E2E、test-only 跨进程 crash/restart | ✅ | 006-008, 047B2, 096, 102-104 |
| 1. 输入准备 | normalize、split、manifest、多语言/EPUB | ✅ | 001-002, 018 |
| 2. 知识抽取 | extract、compress、五类 bootstrap/apply | ✅ | 003-004, 015-016 |
| 3. 起点判断 | start point、anchor、长程起点一致性硬门 | ✅ | 021, 027 |
| 4. 世界观激活 | facts/entity/persona 与起点安全知识视图 | ✅ | 010-011, 021, 047 |
| 5. 情节规划 | debate、chapter plan、周期 re-plan | ✅ | 005, 014, 029 |
| 6. 写作 | 多上下文 writer、lint/rewrite、partial draft | ✅ | 009-013, 022-023, 039 |
| 7. 审核 | fail-closed panel、三档阈值、文风检测/建议/复测 | ✅ | 019, 022-024, 042, 083-087 |
| 8. 关系更新 | proposal、conflict check、auto-advance | ✅ | 013, 019, 029 |
| 9. 滚动下一章 | rolling summary、成本/预算、runner/supervisor | ⚠️ | 工程已通；10-20 章真模型 capstone 待授权 |
| Web/短剧 | 可编辑工作台；短剧五站、显式文本 revision、Approve 血统组装、连续多集、季角色库/单集 8 人边界、单集/季级导出、旧 Web workspace 真生图接管、跨进程素材 callback、媒体 crash receipt、submitted 纯轮询恢复、集中付费状态与 crash/restart 矩阵、fake-provider local-E2E | ⚠️ | local-E2E 与真跑前安全闭环；真多模态待分段授权与人工质量判断（088-104） |

## 文档导航

| 问题 | 文档 |
|---|---|
| 当前能力、缺口、最新测试 | [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) |
| 历史架构与工程教训 | [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) |
| 每轮计划、验收、审查 | [`docs/iterations/README.md`](docs/iterations/README.md) |
| 上手操作 | [`docs/product/GETTING_STARTED.md`](docs/product/GETTING_STARTED.md) |
| Aeloon 集成 | [`docs/AELOON_INTEGRATION.md`](docs/AELOON_INTEGRATION.md) |
| 短剧产品协议 | [`docs/product/short_drama_module.md`](docs/product/short_drama_module.md) |

## 声明

- 这是研究性质的个人创作工具，不是正式产品。
- 原作小说不重新分发；生成内容与本地运行数据均不提交。
- 真模型与媒体调用可能产生费用，必须经用户针对本次入口明确授权。

## 技术栈

Python 3.9+、LiteLLM、Pydantic、tiktoken、python-dotenv。核心流水线没有异步框架或外部 orchestration 框架；Web 使用标准库 HTTP server。
