# Iteration 093 - Agent 记忆文档瘦身与归档

## Context

项目累计 92 轮迭代后，`AGENTS.md`、`docs/AGENT_HANDOFF.md`、README SOP、阶段总结和最新 iteration 文档之间出现大量重复。尤其 handoff 已膨胀到两千余行，新 agent 每次 session 需要重复读取历史实现细节，当前状态与过时过程记录也混在一起。

本轮以“短、准、可追溯”为目标：缩短默认必读链路，建立清晰的当前状态单一真源；历史事实保留为按需归档，不改业务代码、运行数据或私有内容。

## Plan

1. 盘点进度、handoff、phase/stage、iteration 文档及其引用，识别重复、失效与高频入口。
2. 重写 `AGENTS.md` 与 `docs/AGENT_HANDOFF.md` 的职责边界，只保留新 session 必需的约束、当前能力、风险和下一步。
3. 合并阶段总结等小型历史文件，压缩 iteration 索引中的冗长标题；历史 iteration 正文原则上保留，必要时只处理重复草稿或失效入口。
4. 更新所有受影响链接、README SOP 与维护约定，增加文档结构/链接检查，确保后续迭代不会再次把 handoff 写成长日志。

## Acceptance

- 默认必读文档链明显缩短，当前状态、未完成事项和安全边界无相互矛盾。
- 被合并或删除文件的仓库内引用全部更新；相对 Markdown 链接可验证。
- iteration 索引保留全部历史入口，但条目简洁、编号和链接准确。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests`、`bash scripts/verify.sh`、`python3 main.py preflight` 均通过。
- correctness 与 security/boundary 两个只读 subagent 完成独立审查，主线程复核并记录未修风险。

## Implementation Notes

- 将文档分为四层：`AGENTS.md`（长期规则）、`AGENT_HANDOFF.md`（当前快照）、`README.md`（用户入口与 SOP）、`PROJECT_HISTORY.md` / iteration（按需历史）。handoff 不再追加历轮 Phase Status。
- 三份 stage summary 合并为 `PROJECT_HISTORY.md`；历史 iteration 正文与 `PLAN_DRAFT` 保留，索引只缩短标题并补齐漏项/序号。
- 同步清理 `README_EN.md`、产品说明、短剧定义和 Claude 工作流中的过时“当前”表述；明确真模型会向用户配置 provider 发送必要上下文。
- correctness 首审发现安装的 `iter-finish` 仍会重新膨胀 handoff，触发 `skill-creator` 更新 iter-start/iter-finish；两者均通过 `quick_validate.py`。这些 skill 位于用户级 Codex 目录，不属于仓库提交。
- mock 验收观察到 LiteLLM 导入会尝试刷新公开 model cost map；因此将“绝对无网络”收窄为“无计费模型请求”，并把严格离线开关记入后续候选。

## Acceptance Result

- **瘦身结果**：旧默认必读链约 **2907 行**（AGENTS 143 + handoff 2216 + index 106 + latest iter 75 + stage summaries 367）；新默认只读 AGENTS 86 + handoff 93，共 **179 行，减少约 94%**。同口径核心文档总量由 3162 行降为 524 行。
- **结构/链接**：relative Markdown link 检查无断链；iteration index **102** 个主记录连续、主文件无漏项；iter093 八段各 1 次；删除的 stage 文件在活跃入口中无残留引用；`git diff --check` 通过。
- **工程验收**：`.venv/bin/python3 -m unittest discover -s tests` **1903 tests OK**；`PATH="$PWD/.venv/bin:$PATH" OPENAI_MODEL=mock bash scripts/verify.sh` exit 0，内部同样 **1903 tests OK** 且 mock pipeline/report/manifest/cost 全过；mock preflight `ok`、无 WARN/FATAL；当前真实配置 preflight `warn`、无 FATAL。
- **环境说明**：首次系统 Python 运行缺 `tiktoken`，受限沙箱另有 13 个 localhost bind error；改用项目 `.venv` 并仅放开本机回环后 canonical 全绿。未运行任何真模型、真生图或真视频 smoke。
- **铁律审查**：correctness 首审发现 1 High（iter-finish 仍追加 Phase Status）、1 Medium（PRODUCT_SPEC 旧进度）和若干 Low 引用漂移；security 首审/复审发现产品隐私“全本地”误述及 `logs/` 边界漏项。全部修复后两个独立只读 subagent 最终复核均 **PASS**，主线程复核链接、编号、隐私、授权和 skill validation 通过；无未修 blocker/High/Medium。
- **残余 Low**：mock 无计费 provider 请求，但 LiteLLM 可能访问公开 cost-map URL；用户级 skill 的更新不随仓库 clone 分发，异机仍以仓库 `AGENTS.md` 为准并需单独同步 skill。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_093_docs_memory_compaction.md` | 建立本轮计划与验收记录 |
| `AGENTS.md` / `CLAUDE.md` | 缩短默认入口，统一读取顺序、维护与安全边界 |
| `README.md` / `README_EN.md` | 将逐轮长表压为里程碑 + 当前 SOP，修正 mock 网络口径 |
| `docs/AGENT_HANDOFF.md` | 2216 行累计日志改为 93 行当前快照 |
| `docs/PROJECT_HISTORY.md` | 合并三份 stage summary，保留压缩里程碑与长期教训 |
| `docs/iterations/README.md` | 压缩标题、修复序号、补齐主记录并追加 iter 093 |
| `docs/product/PRODUCT_SPEC.md` / `short_drama_module.md` | 删除过时进度，修正本地落盘与 provider 外发边界 |
| `docs/CLAUDE_CODE_WORKFLOW_OPTIMIZATION_2026-06.md` | 同步新 handoff/SOP/铁律与已落地 skill 状态 |
| `docs/stage_01_summary.md` / `stage_02_summary.md` / `stage_03_summary.md` | 合并后删除 |
| `~/.codex/skills/{iter-start,iter-finish}/SKILL.md` | 用户级 skill 防膨胀契约与边界同步（仓库外） |

## 不在本轮范围

- 不改业务代码、配置语义、运行数据或私有样本。
- 不跑任何真模型、真生图或真视频 smoke。
- 不重写历史技术事实；历史记录只做结构整理、去重和归档。

## Notes

- 仓库外计划文件 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在，本轮直接以用户目标作为范围依据。
- 历史 iteration 正文没有批量改写；它们是审计证据，不属于默认记忆负担。冗长 `PLAN_DRAFT` 归入 supplemental，只在追溯原始决策时读取。
- 收官提交信息：`docs(iter093): 精简 agent 记忆入口与历史归档（验收 + 审查 + SOP/handoff 同步）`。
