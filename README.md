# Continuator / 续

本地运行的多 agent 小说续写与短剧创作流水线。它把知识抽取、情节规划、正文生成、审稿、关系推进和媒体任务拆成可恢复步骤；开发默认使用 mock，不产生计费模型请求。

中文 · [English](README_EN.md)

原作语料与运行产物不进仓库：`小说txt/`、`workspaces/*/小说txt/`、`data/`、`outputs/`、`logs/` 均已忽略。仓库只保存引擎、配置、测试和文档。

## 核心能力

- **小说续写**：normalize → split → extract → compress → debate → plan → write → review → rolling/advance。
- **质量守门**：起点安全视图、指纹、5+1 reviewer、确定性 lint、预算/超时、文风漂移与一次受控重写。
- **长跑恢复**：`write-book`、`drive-book`、supervisor、heartbeat/watchdog、workspace 写锁、断点续跑。
- **本地 Web**：四步工作台、设定/大纲/细纲/正文编辑、job 恢复、全文搜索、版本 diff、Insights。
- **短剧**：五站 job、分镜 grid、角色库、review/assembly、连续多集、单集四导出、整季母包/阶段快照、逐镜图片 C1-C3、逐镜视频 D1-D4、声音 E1-E3，以及 F1 本地 FFmpeg 竖屏 MP4/SRT/媒体 QA。

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
| 短剧单集角色投影一致性 | 105 | ✅ reviewer、组装、单集/季包 Comfy 与 episode 1 视频统一冻结阵容；歧义旧数据 fail-closed |
| 短剧渲染计划与创作陈旧性边界 | 106 | ✅ fresh assembled episode 可确定投影为 strict RenderPlan；五态 stale 检查、幂等落盘与歧义镜头 fail-closed |
| 短剧角色资产版本与冻结选择 | 107 | ✅ 角色语义 ID、不可变版本、显式 selected/CAS 与单集 AssetRef manifest 形成纯本地闭环 |
| 短剧美术方向版本与渲染冻结 | 108 | ✅ season 级 ArtDirection 不可变候选、显式 selected/CAS 与 RenderPlan/manifest stale 传播形成纯本地闭环 |
| 短剧场景资产版本与逐镜冻结 | 109 | ✅ season SceneAsset 不可变版本、selected 双 CAS、显式 shot→scene 冻结、used-by 与精确 stale 形成纯本地闭环 |
| 短剧道具/线索资产版本与逐镜冻结 | 110 | ✅ season PropOrClueAsset 不可变版本、selected 双 CAS、显式 shot→0..16 refs、used-by 与精确 stale 形成纯本地闭环 |
| 短剧逐镜图片规格与冻结引用 | 111 | ✅ 显式逐镜角色绑定、exact 资产版本、确定性 reference 裁剪与五态本地 plan store 形成 C1 闭环；不代表已生图 |
| 迭代上下文与经验晋升门禁 | 112 | ✅ 原 8 段 iteration 内固定实现/审查路由与人工 Knowledge Promotion；不新建任务状态 |
| 短剧逐镜图片候选与首尾帧绑定 | 113 | ✅ content-addressed 本地 PNG 候选、显式选择、first/tail/previous-tail lineage、覆盖率与 strict repair 形成 C2 闭环 |
| 短剧逐镜图片能力与可恢复尝试 | 114 | ✅ provider-neutral capability、once-only attempt、durable receipt、C2 exact candidate 补账与进程 crash 零重复调用形成 C3 mock-only 闭环 |
| 短剧逐镜视频计划与冻结首尾帧 | 115 | ✅ provider-neutral 逐镜视频计划冻结时长、受控视觉输入、exact first/optional tail 与 previous-tail lineage；五态本地 store 形成 D1 闭环 |
| 短剧逐镜视频候选选择与整集覆盖 | 116 | ✅ content-addressed strict MP4 候选、guarded selection、retired audit、精确 stale/repair 与 production coverage 形成 D2 纯本地闭环 |
| 短剧逐镜视频能力与可恢复尝试 | 117 | ✅ provider-neutral capability、exact once authorization、adapter identity、durable receipts、D2 candidate 补账与 process-crash 零重复 submit 形成 D3 mock-only 闭环 |
| 短剧完整 SOP 真人用户验证 | 118 | ✅ 当前 Web 创作/交付主链完成桌面与移动端 E2E；真文本 5 calls、真图 2 张局部校准通过，真视频未执行；付费产物与本地预览边界收口 |
| 短剧本地完整成片链 | 119-123 | ✅ D4 compose gate、E1/E2 voice/TTS recovery、E3 唯一时间线/SRT 与 F1 FFmpeg 1080×1920/25fps MP4/QA 已完成 |

历史里程碑见 [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md)，逐轮验收见 [`docs/iterations/README.md`](docs/iterations/README.md)。

## 流水线 SOP（实时状态）

最近一次更新：**iter 123**（2026-07-17，收官）。当前状态以 [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) 为准。现有短剧 Web 主链已经过桌面与 390px 移动端真人用户路径验证；逐镜图片 C1-C3、逐镜视频 D1-D4、声音/时间线 E1-E3 与 F1 本地合成形成完整纯本地链。F1 只消费 strict `TimelineManifest`，以 FFmpeg 8.1.2 生成并 post-probe 验证 `1080×1920 / 25fps` H.264/AAC MP4、SRT 与绑定 output SHA/timeline fingerprint 的媒体 QA；当前仍只有 fake/bounded 音频与 fixture 视频。iter123 另完成指定 endpoint 的 synthetic 文本 1 call/图片 1 submit 局部校准，真语音/真视频仍为 0 submit；该证据不把 F1 或完整 pipeline 升格为 provider-validated。完整目标流程来自独立的 [A-J 阶段计划](docs/iterations/stage_plan_drama_full_production_pipeline.md)，不是已完成能力清单。总验收为 `mock-functional`，F1 synthetic 组件为 `local-e2e`。

图例：✅ 已实现　🟨 部分实现　⏳ 待实现　🔒 待逐次授权验证

### 小说续写 SOP

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
| 9. 滚动下一章 | rolling summary、成本/预算、runner/supervisor | 🟨 | 工程已通；10-20 章真模型 capstone 待授权 |

### 短剧完整生产 SOP

短剧分成两段：前半段把创作结果冻结为 `episode_NN.json`，后半段只从它派生渲染、资产、时间线和成片。媒体结果不得反写创作事实；任务 DAG 也不得替代独立的付费 ledger、receipt 与恢复证据。详细输入、产物和验收门槛见 [`docs/product/short_drama_module.md`](docs/product/short_drama_module.md#11-完整生产-sop实时状态)。

| 阶段 | 动作与主要产物 | 状态 | 已实现边界 / 待完成项 |
|---|---|---|---|
| 0. 运行与 workspace | 建立隔离的 drama workspace；mock/offline、路径、预算与授权守门 | ✅ | 默认零真实请求；真文本、图片、语音、视频授权互不继承 |
| 1. 核心设定 | 站①生成赛道、主线与人物核心设定，用户可编辑 | ✅ | 五站 job 的 `drama-plan` |
| 2. 钩子选择 | 站②生成钩子候选，选择并锁定本集钩子 | ✅ | 五站 job 的 `drama-hooks` |
| 3. 叙事与分镜 | 站③生成叙事和镜头 grid，支持编辑、排序和局部重生 | ✅ | 镜头结构/字段有本地硬校验，时长等软规则显式告警；当前 canonical/mock 证据以 60 秒为主，30/90/120 秒待专项验证 |
| 4. 角色与季角色库 | 站④生成角色卡、合并季角色库并登记本集 appearances（最多 8 人） | ✅ | 五站 job 的 `drama-characters`；角色不可变资产版本与 selected reference 由阶段 B 的独立目录承接 |
| 5. 评审与组装 | 站⑤五维评审，revision 后仅从 Approve 血统组装 canonical episode，并将本集角色 IDs 冻结进 meta | ✅ | `episode_NN.json` 是创作事实真源；解析失败/血统不一致 fail-closed |
| 6. 连续多集与创作交付 | 只从最新连续、完整、fresh 前集创建 N+1；导出 JSON/MD/CSV/Comfy、严格季包/快照与 Insights | ✅ | 当前仅 season 1、计划上限 100 集；多季模型未闭环；Comfy 仅为 workflow 导出 |
| A. 渲染契约与 stale | canonical episode → strict `RenderPlan`、稳定镜头 ID、有序 spoken segments、五态检查 | 🟨 | **A1 已完成**；A2 已冻结角色、ArtDirection、场景与道具/线索 selected refs，并让 ArtDirection/RenderPlan/资产选择精确传播到对应单集 manifest；通用 visual override 与后续媒体依赖矩阵待完成 |
| B. 视觉资产圣经 | 角色/场景/道具/线索、美术方向、不可变版本与显式 selected reference | 🟨 | 角色、season ArtDirection、SceneAsset 与 PropOrClueAsset 已有不可变版本和 selected CAS；场景及道具/线索支持 episode used-by；跨集 used-by/Web 管理与 ArtDirection 多 scope 待实现 |
| C. 逐镜图片 | 每镜图片候选、首帧/可选尾帧、引用冻结、比较选择与覆盖率 | 🟨 | **C1+C2+C3 纯本地闭环已实现**：provider-neutral request/exact refs，content-addressed strict PNG 候选与 guarded first/tail/previous-tail lineage，provider-neutral capability、once-only attempt、durable receipt、C2 exact candidate 补账与进程 crash 零重复调用；真实 provider/network adapter、多参考上传协议、JPEG/WebP、质量比较 UI、显式 staging GC 与 power-loss 证明未实现 |
| D. 逐镜视频 | 每镜 I2V/R2V 输入计划、submit→poll→download、候选选择与跨镜连续性 | 🟨 | **D1-D4 纯本地闭环已完成**：D1-D3 冻结输入、候选/coverage 与 once-only 恢复；D4 以有序 selected snapshot、artifact 实体重验、global stale、首尾帧 lineage 和连续性 warning 建立 production compose gate。真实 provider/network、主观视觉相似度、Web/CLI 与 episode 2+ 成片未实现；旧 episode 1 高光入口保持兼容 |
| E. 声音与唯一时间线 | 角色 voice、逐句 TTS、旁白、字幕、BGM/SFX 与 `TimelineManifest` | ✅ | **E1-E3 纯本地闭环已完成**：VoiceProfile/AudioManifest、逐 utterance once-only recovery，以及只消费 fresh D4/E2 artifact 的 strict TimelineManifest；视频/对白/旁白/silence/optional BGM/SFX 和字幕共享 fingerprint，SRT 由同一 manifest 确定导出。仅 fake adapter/bounded WAV，真实 TTS、真实 BGM/SFX 与主观音频质量未验证 |
| F. 合成、QA 与可编辑导出 | 同一时间线驱动 FFmpeg 竖屏 MP4、SRT/ASS、媒体 QA 和编辑器工程 | 🟨 | **F1 本地完整成片已完成**：argv-only compose plan、输入 SHA/probe/private staging、视频 normalize/concat、音频 delay/trim/fade/mix、SRT 与 post-probe QA，固定 1080×1920/25fps H.264/AAC。ASS、编辑器工程/Web job、多 profile 与更广 codec/container 待 F2+ |
| G. 通用媒体调度与成本 | 从 C-F 抽象 task DAG、worker lease、provider capability、并发 lane 与 pricing | ⏳ | 已有领域专用恢复/付费 ledger；尚未做通用调度，且不得用通用状态替代付费证据 |
| H. 小说事件图与辅助记忆 | typed event graph、来源/防剧透边界、可失效的上下文 cache | ⏳ | 小说实体/摘要可作基础；短剧事件图与 `source_event_ids` 未实现，不阻塞阶段 F |
| I. 生产工作台与归档 | 同源展示资产/镜头/任务/时间线/QA；安全 archive 导出与导入 | ⏳ | 已有剧集页、Insights 和季包；尚无统一生产工作台及含媒体/证据的可移植归档 |
| J. 真 provider 校准与 capstone | 真文本、真图片、真语音、真视频分别 preflight、最小 smoke、单镜、单集、多集校准 | ⏳ 🔒 | iter118 已完成五站真文本（5 calls）与 2 张角色真图；iter123 另完成 synthetic 文本 1 call 与图片 1 submit 局部校准。真语音/真视频、全角色/多题材、单镜/单集/多集和 SLA 仍未验证 |
| 现有规划之外：平台发布 | 将成片上传到抖音、快手、视频号等平台 | ⏳ | A-J 没有发布 adapter、账号审核或回执状态设计；现阶段只能人工发布，后续需另行规划 |

## 文档导航

| 问题 | 文档 |
|---|---|
| 当前能力、缺口、最新测试 | [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md) |
| 历史架构与工程教训 | [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md) |
| 每轮计划、验收、审查 | [`docs/iterations/README.md`](docs/iterations/README.md) |
| 上手操作 | [`docs/product/GETTING_STARTED.md`](docs/product/GETTING_STARTED.md) |
| Aeloon 集成 | [`docs/AELOON_INTEGRATION.md`](docs/AELOON_INTEGRATION.md) |
| 短剧完整 SOP 与产品协议 | [`docs/product/short_drama_module.md`](docs/product/short_drama_module.md#11-完整生产-sop实时状态) |

## 声明

- 这是研究性质的个人创作工具，不是正式产品。
- 原作小说不重新分发；生成内容与本地运行数据均不提交。
- 真模型与媒体调用可能产生费用，必须经用户针对本次入口明确授权。

## 技术栈

Python 3.9+、LiteLLM、Pydantic、tiktoken、python-dotenv。核心流水线没有异步框架或外部 orchestration 框架；Web 使用标准库 HTTP server。
