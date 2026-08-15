# AGENTS.md - 项目入口

> 所有 agent 进入仓库先读本文件；随后读 `docs/AGENT_HANDOFF.md`和`docs/PROJECT_HISTORY.md`。其它历史文档按任务需要查阅，不再作为每次 session 的默认上下文。

## 项目与边界

Dragon Raja AI Continuer 的 `main` 是一个基于 LLM 多 agent 协作的小说原创与续写研究项目，目标是支持任意小说，而非只服务当前验证书目。iter167 前的完整小说+短剧基线固定保存在 `codex/short-drama`；main 只保留禁用入口与 legacy 类型隔离哨兵，不提供短剧运行能力。

- **禁止修改 `小说txt/` 原文**。原文及其衍生数据只用于本地处理，不进入仓库。
- 默认 `OPENAI_MODEL=mock`，无 key、无计费模型请求即可完成工程验证；mock 会在 LiteLLM 首次导入前强制使用内置 cost map 并跳过代理探测，保持严格离线。真实模型仍按既有 provider/代理配置运行。
- 真模型配置由用户维护在 `.env`；模型名必须包含 provider 前缀，例如 `deepseek/deepseek-chat`。

## 新 Session 读取顺序

1. 本文件：长期规则、验证方式、路径。
2. [`docs/AGENT_HANDOFF.md`](docs/AGENT_HANDOFF.md)：唯一当前状态、缺口、下一步和最新验收基线。
3. [`docs/PROJECT_HISTORY.md`](docs/PROJECT_HISTORY.md)：阶段级项目记忆、长期决策和工程教训。
4. 仅在本轮实施或追溯证据时读 [`docs/iterations/README.md`](docs/iterations/README.md) 与最新/相关 iteration 文档；不要默认加载全部历史。
5. 用户明确指向仓库外计划时再读 `~/.claude/plans/docs-rosy-wadler.md`；文件不存在则以用户当前指令为准，不自行补造计划。

权威性顺序：当前行为以代码和测试为准；当前进度以 handoff 为准；节点级 SOP 以 README 为准；历史原因以 iteration 文档为准。

## 迭代工作流

- 每轮实现必须显式使用 `iter-start` 和 `iter-finish`。
- 仓库内 `.agents/skills/{iter-start,iter-finish}` 是项目 workflow 的唯一真源；不得在用户目录维护项目专用副本。
- iteration 文档固定 8 段：`Context / Plan / Acceptance / Implementation Notes / Acceptance Result / 文件变更汇总 / 不在本轮范围 / Notes`。
- `iter-start` 新建当轮文档并更新 iteration 索引。
- `iter-finish` 先跑聚焦检查，再完成只读多视角审查与修复，最后只跑一次标准全量验收；随后更新 README SOP，并**就地更新** handoff 当前快照和“Latest Transition”。
- 收官默认至少两个独立只读 subagent：correctness 与 security/boundary。Web、runner、多 workspace、真模型或计费入口按风险增加视角。
- 验收结论固定分为 `safe-blocked`、`mock-functional`、`local-e2e`、`provider-validated`；标准 `verify.sh` 使用 novel-only schema v3/profile，只能产生 `mock-functional`，不得据此宣称真实 provider 已验证。
- 只 commit，不 push，等待用户验收。

## 工程铁律

1. **凭据安全**：看到疑似真实凭据立即停止。不得主动读写 `.env`；日志、错误和公开 job 投影不得泄露凭据、完整 prompt 或签名 URL。
2. **版权边界**：不得主动读取、写入或提交 `小说txt/`、私有样本与原文片段。示例文件只放 schema 和 `<用户填写>` 占位符。
3. **测试隔离**：单测必须是 mock；任何让 `unittest discover` 触发真模型的改动都是 bug。
4. **Graceful degrade**：可选的 style examples、global facts、entity graph、continuation anchor 缺失时，mock 裸仓库仍须跑通。
5. **真模型需逐次授权**：`scripts/{real,debate,write}_smoke.sh` 及任何真实文本模型入口，必须等用户明确授权。
6. **范围收敛**：不顺手改计划外文件；真实运行暴露的阻塞 bug 可例外，但必须在 iteration 中记录。
7. **SOP 实时性**：收官同步 README 的项目状态、9 阶段 SOP 和真实日期；handoff 保留当前值及经筛选的阶段级工作记忆，不复制逐轮完整验收日志。
8. **收官审查**：优先使用内置代码/安全审查能力，并完成至少两个只读 subagent 视角。记录范围、结论、主线程复核和未修风险。
9. **审查边界**：subagent 不得改文件、跑真模型、触碰 `.env`、`data/`、`outputs/`、`logs/` 或 `小说txt/`。
10. **分支边界**：短剧开发、媒体 provider、归档和旧短剧 workspace 访问只在 `codex/short-drama` 上进行；main 不迁移、修改或删除这些数据。

## 标准验证

收官顺序固定为：聚焦测试/静态检查 → 多视角只读审查 → 修复 findings 并做聚焦回归 → 最终一次全量标准验证。不要在审查前先跑耗时的 `verify.sh`，以免修复后重复跑全量；最终全量失败时再按失败范围修复并重验。

```bash
bash scripts/verify.sh
```

`scripts/verify.sh` 固定使用项目 `.venv/bin/python3`，依次执行 harness 检查、语法检查、一次全量单测、mock pipeline 与 preflight，并写入 gitignored 的 `outputs/harness/acceptance.json`。其 `data/`、`outputs/`、`logs/` 验证产物已获默认授权；不得因此读取用户私有样本，也不得切换到真模型。聚焦 Python 检查同样使用 `.venv/bin/python3`。

canonical `verify.sh` 不接受 `--book`，不继承 ambient workspace，并在系统临时目录使用 synthetic workspace。收官实现/测试/workflow 先形成 implementation commit，在该 commit 上验收；随后只允许 docs-only 收官提交。

真模型 smoke 入口仅供获授权后使用：

```bash
bash scripts/real_smoke.sh
bash scripts/debate_smoke.sh
bash scripts/write_smoke.sh
```

## 关键路径

```text
main.py                  CLI 入口
src/                     小说流水线、runner 与 Web
config/                  agent/model/linter/style 配置
scripts/                 verify、harness checker、mock/real smoke、长跑入口
tests/                   mock 隔离测试
docs/AGENT_HANDOFF.md    当前状态单一真源
docs/PROJECT_HISTORY.md  压缩后的里程碑与工程教训
docs/iterations/         每轮审计记录，按需读取
workspaces/<name>/       每书本地隔离目录，内容不提交
data/ outputs/ logs/     legacy/mock 与本地产物，均 gitignored
```

涉及 Aeloon 时读 `docs/AELOON_INTEGRATION.md`；涉及产品使用读 `docs/product/GETTING_STARTED.md`。涉及短剧历史时，main 内产品文档只提供迁移提示；切换到 `codex/short-drama` 后再读该分支完整协议。

## 排障顺序

- 先确认 `OPENAI_MODEL=mock`，再复现聚焦测试。
- 行为与文档不一致时，以代码/测试为准并修正文档。
- 历史决策不清楚时，在 iteration 索引中定位相关轮次，不回读整个 handoff 历史。
- 真模型失败仅在已授权范围内检查脱敏日志；未授权时停在 preflight。
- 无法从代码、测试、handoff 或相关 iteration 得出结论时，再向用户确认。
