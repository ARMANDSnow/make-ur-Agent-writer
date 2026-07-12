# AGENTS.md - 项目入口

> 所有 agent 进入仓库先读本文件；随后读 `docs/AGENT_HANDOFF.md`和`docs/PROJECT_HISTORY.md`。其它历史文档按任务需要查阅，不再作为每次 session 的默认上下文。

## 项目与边界

Dragon Raja AI Continuer 是一个基于 LLM 多 agent 协作的小说续写与短剧生成研究项目，目标是支持任意小说，而非只服务当前验证书目。

- **禁止修改 `小说txt/` 原文**。原文及其衍生数据只用于本地处理，不进入仓库。
- 默认 `OPENAI_MODEL=mock`，无 key、无计费模型请求即可完成工程验证。LiteLLM 导入时可能刷新公开 model cost map 并回落本地缓存，这不属于模型调用。
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
- iteration 文档固定 8 段：`Context / Plan / Acceptance / Implementation Notes / Acceptance Result / 文件变更汇总 / 不在本轮范围 / Notes`。
- `iter-start` 新建当轮文档并更新 iteration 索引。
- `iter-finish` 先跑聚焦检查，再完成只读多视角审查与修复，最后只跑一次标准全量验收；随后更新 README SOP，并**就地更新** handoff 当前快照和“Latest Transition”。
- 收官默认至少两个独立只读 subagent：correctness 与 security/boundary。Web、runner、多 workspace、真模型或计费入口按风险增加视角。
- 只 commit，不 push，等待用户验收。

## 工程铁律

1. **凭据安全**：看到疑似真实凭据立即停止。不得主动读写 `.env`；日志、错误和公开 job 投影不得泄露凭据、完整 prompt 或签名 URL。
2. **版权边界**：不得主动读取、写入或提交 `小说txt/`、私有样本与原文片段。示例文件只放 schema 和 `<用户填写>` 占位符。
3. **测试隔离**：单测必须是 mock；任何让 `unittest discover` 触发真模型的改动都是 bug。
4. **Graceful degrade**：可选的 style examples、global facts、entity graph、continuation anchor 缺失时，mock 裸仓库仍须跑通。
5. **真模型需逐次授权**：`scripts/{real,debate,write}_smoke.sh` 及任何真文本、真生图、真视频入口，必须等用户明确授权。
6. **范围收敛**：不顺手改计划外文件；真实运行暴露的阻塞 bug 可例外，但必须在 iteration 中记录。
7. **SOP 实时性**：收官同步 README 的项目状态、9 阶段 SOP 和真实日期；handoff 保留当前值及经筛选的阶段级工作记忆，不复制逐轮完整验收日志。
8. **收官审查**：优先使用内置代码/安全审查能力，并完成至少两个只读 subagent 视角。记录范围、结论、主线程复核和未修风险。
9. **审查边界**：subagent 不得改文件、跑真模型、触碰 `.env`、`data/`、`outputs/`、`logs/` 或 `小说txt/`。
10. **真生图超时策略**：仅在用户明确授权后使用。首次失败/超时后先查上游任务状态与账单，再经重新授权使用简化 prompt；首轮外最多 2 次，每次 180 秒。真视频仍是单次提交、超时不重试。

## 标准验证

收官顺序固定为：聚焦测试/静态检查 → 多视角只读审查 → 修复 findings 并做聚焦回归 → 最终一次全量标准验证。不要在审查前先跑耗时的 `verify.sh`，以免修复后重复跑全量；最终全量失败时再按失败范围修复并重验。

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
bash scripts/verify.sh
python3 main.py preflight
```

`scripts/verify.sh` 写入 gitignored 的 `data/`、`outputs/`、`logs/` 验证产物已获默认授权。不得因此读取用户私有样本，也不得切换到真模型。

真模型 smoke 入口仅供获授权后使用：

```bash
bash scripts/real_smoke.sh
bash scripts/debate_smoke.sh
bash scripts/write_smoke.sh
```

## 关键路径

```text
main.py                  CLI 入口
src/                     流水线、runner、Web、小说与短剧领域逻辑
config/                  agent/model/linter/style 配置
scripts/                 verify、mock/real smoke、长跑入口
tests/                   mock 隔离测试
docs/AGENT_HANDOFF.md    当前状态单一真源
docs/PROJECT_HISTORY.md  压缩后的里程碑与工程教训
docs/iterations/         每轮审计记录，按需读取
workspaces/<name>/       每书本地隔离目录，内容不提交
data/ outputs/ logs/     legacy/mock 与本地产物，均 gitignored
```

涉及 Aeloon 时读 `docs/AELOON_INTEGRATION.md`；涉及产品使用读 `docs/product/GETTING_STARTED.md`；涉及短剧协议读 `docs/product/short_drama_module.md` 和创作规范。

## 排障顺序

- 先确认 `OPENAI_MODEL=mock`，再复现聚焦测试。
- 行为与文档不一致时，以代码/测试为准并修正文档。
- 历史决策不清楚时，在 iteration 索引中定位相关轮次，不回读整个 handoff 历史。
- 真模型失败仅在已授权范围内检查脱敏日志；未授权时停在 preflight。
- 无法从代码、测试、handoff 或相关 iteration 得出结论时，再向用户确认。
