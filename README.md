# Continuator / 续

本地运行的多 agent 小说续写与短剧创作流水线。它把知识抽取、情节规划、正文生成、审稿、关系推进和媒体任务拆成可恢复步骤；开发默认使用 mock，不产生计费模型请求。

中文 · [English](README_EN.md)

原作语料与运行产物不进仓库：`小说txt/`、`workspaces/*/小说txt/`、`data/`、`outputs/`、`logs/` 均已忽略。仓库只保存引擎、配置、测试和文档。

## 核心能力

- **小说续写**：normalize → split → extract → compress → debate → plan → write → review → rolling/advance。
- **质量守门**：起点安全视图、指纹、5+1 reviewer、确定性 lint、预算/超时、文风漂移与一次受控重写。
- **长跑恢复**：`write-book`、`drive-book`、supervisor、heartbeat/watchdog、workspace 写锁、断点续跑。
- **本地 Web**：四步工作台、设定/大纲/细纲/正文编辑、job 恢复、全文搜索、版本 diff、Insights。
- **短剧**：五站 job、分镜 grid、角色库、review/assembly、四种导出、第 2 集、角色生图与 episode 1 视频安全入口。

当前验收基线、真实验证边界和下一步统一见 [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md)。

## 快速开始

mock 模式不需要 key，也不调用模型 provider。LiteLLM 导入时可能刷新公开 model cost map，失败后自动使用本地备份：

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
python3 -m unittest discover -s tests
bash scripts/verify.sh
python3 main.py preflight
```

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
| Agent 记忆、历史归档与收官流程 | 093-094 | ✅ 当前/历史职责分离；恢复精选工作记忆；全量验收后置 |

历史里程碑见 [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md)，逐轮验收见 [`docs/iterations/README.md`](docs/iterations/README.md)。

## 流水线 SOP（实时状态）

最近一次更新：**iter 094**（2026-07-13，收官）。多模态 smoke 已补齐文本模型/调用账本、失败恢复耗时、图片 attempt、视频容器/指纹与脱敏校准报告；mock 证据与真实样本明确分离，本轮未运行真实计费请求。项目记忆在 iter 093 分层基础上恢复精选阶段上下文，收官固定先多视角审查修复、最后执行一次全量验收。

图例：✅ 已打通　⚠️ 工程已通但真实校准未完成　❌ 未打通

| 阶段 | 当前能力 | 状态 | 关键迭代 |
|---|---|---|---|
| 1. 输入准备 | normalize、split、manifest、多语言/EPUB | ✅ | 001-002, 018 |
| 2. 知识抽取 | extract、compress、五类 bootstrap/apply | ✅ | 003-004, 015-016 |
| 3. 起点判断 | start point、anchor、长程起点一致性硬门 | ✅ | 021, 027 |
| 4. 世界观激活 | facts/entity/persona 与起点安全知识视图 | ✅ | 010-011, 021, 047 |
| 5. 情节规划 | debate、chapter plan、周期 re-plan | ✅ | 005, 014, 029 |
| 6. 写作 | 多上下文 writer、lint/rewrite、partial draft | ✅ | 009-013, 022-023, 039 |
| 7. 审核 | fail-closed panel、三档阈值、文风检测/建议/复测 | ✅ | 019, 022-024, 042, 083-087 |
| 8. 关系更新 | proposal、conflict check、auto-advance | ✅ | 013, 019, 029 |
| 9. 滚动下一章 | rolling summary、成本/预算、runner/supervisor | ⚠️ | 工程已通；10-20 章真模型 capstone 待授权 |
| Web/短剧 | 可编辑工作台；短剧五站、导出、图片/视频 job、校准证据报告 | ⚠️ | mock 工程与对账闭环；真多模态待分段授权与人工质量判断 |

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
