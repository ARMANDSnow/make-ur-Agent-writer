# Agent Handoff

> 当前状态单一真源。每轮收官就地更新，不在本文件追加完整 iteration 日志。历史见 [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) 和 [`iterations/`](iterations/README.md)。

## Current Snapshot

| 项 | 当前值 |
|---|---|
| 更新时间 | iter 093，2026-07-13 收官 |
| 默认运行模式 | `OPENAI_MODEL=mock`，无 key、无计费模型请求；LiteLLM 可能刷新公开 cost map |
| Canonical 基线 | **1903 tests OK** |
| 标准验收 | `verify.sh` exit 0；mock preflight 无 WARN/FATAL；真实配置 preflight 无 FATAL |
| 当前高风险缺口 | 真多模态费用/时延/质量尚未分段实测；小说 10-20 章 capstone 尚未实跑 |
| 当前开发轮次 | 无；iter 093 已收官 |

## Capability Map

| 领域 | 已打通 | 仍未闭环 |
|---|---|---|
| 小说主链 | normalize、split、extract、compress、debate、plan、write、review、滚动摘要、关系推进、多 workspace、多语言 | 10-20 章真模型 capstone 与长期质量阈值校准 |
| 质量与安全 | 起点/指纹守门、review panel、lint、预算/超时、文风 baseline/drift/advisor、red drift 单次重写复测 | 文风真模型阈值仍需样本校准；预训练记忆泄露只能缓解，不能作绝对保证 |
| 长跑可靠性 | `write-book`、`drive-book`、supervisor、心跳/watchdog、断点恢复、workspace 写锁、预算预留 | 真模型长跑的费用和失败分布仍需 capstone 证明 |
| Web | 本地 Beta、四步工作台、可编辑设定/大纲/细纲/正文、job 恢复、搜索、版本 diff、Insights | 仍是本地研究工具，不是公网多租户产品 |
| 短剧 | 五站 job、分镜 grid、角色库、review/assembly、四导出、Insights、第 2 集、episode 1 视频 job、多模态可恢复编排 | 真文本/全角色真生图/单次真视频需分别授权实测；第 3 集以上未做 |
| 集成 | Aeloon 插件/MCP 双轨已实现；详情见 [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) | Aeloon vendored 基线与主仓后续版本需按集成文档同步 |

## Latest Accepted Evidence

- iter 093 不改业务行为；最新产品行为基线仍是 iter 092 的可恢复多模态状态机与独立授权/预算/超时边界。
- 默认启动读取从旧约 2907 行（AGENTS + handoff + index + latest iter + 3 stage summaries）降为 179 行（AGENTS + handoff），历史改为按需读取。
- handoff 从 2216 行累计日志缩为 93 行当前快照；3 份 stage summary 合并为 1 份 65 行 `PROJECT_HISTORY.md`。
- iteration 索引压缩标题、修复序号跳号，并补齐 046/047 子轮次；102 个主记录和 supplemental 快照均可定位。
- README、英文入口、产品说明、Claude 工作流和安装的 iter-start/iter-finish skill 已统一当前口径；两个 skill 均通过 `quick_validate.py`。
- canonical **1903 tests OK**；`verify.sh` exit 0；mock preflight ok/无 WARN/FATAL，当前真实配置 preflight warn/无 FATAL；相对链接、8 段结构、索引连续性和 `git diff --check` 通过。
- correctness 与 security/boundary 两个只读 subagent 的 findings 全修，最终复核 PASS；未运行真模型或媒体 smoke。

## Operating Boundaries

- 不读写 `.env`、`小说txt/`、私有 `data/` 样本；不把原文、凭据、完整 prompt 或上游响应写入文档/日志。
- `verify.sh` 与单测必须保持 mock 隔离；真实调用必须有用户针对本次入口的明确授权。
- 真文本、真生图、真视频授权彼此独立；授权不跨阶段、不从历史 state 恢复。
- 生图重试遵循“先查上游/账单，再重新授权”；视频超时不重试。
- 只 commit，不 push。

## Open Gaps

1. **短剧真实多模态校准**：分别验证五站真文本、全角色真生图、单次真视频的费用、耗时和质量。每段都需单独授权。
2. **小说 capstone**：选择干净 workspace 跑 10-20 章，验证预算、supervisor、resume、质量闸和关系推进。
3. **文风阈值**：用真模型草稿校准 baseline/drift tolerance；当前工程闭环已通，但阈值证据仍以 mock/局部样本为主。
4. **ComfyUI 与季级短剧**：真 ComfyUI workflow、第 3 集以上和整季编排未验证。
5. **集成同步**：Aeloon 内置副本不是自动跟随主仓，需要按集成文档明确同步。
6. **严格离线 mock**：mock 不发计费 provider 请求，但 LiteLLM 导入可能刷新公开 model cost map；若要求物理零网络，可后续统一设置 `LITELLM_LOCAL_MODEL_COST_MAP=true` 并回归。

## Next Candidates

- 低风险工程轮：将 LiteLLM cost map 固定为本地、继续测试可维护性或已登记 P2 技债。
- 需授权验证轮：五站真文本 smoke；全角色真生图 smoke；episode 1 单次真视频 smoke；小说 capstone。不要把这些授权合并推定。
- 产品轮：第 3 集以上的季级继承/编排，或真 ComfyUI 导出校准。

## Recovery Commands

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
bash scripts/verify.sh
python3 main.py preflight
python3 main.py status
python3 main.py write-readiness --chapters N
```

先以 mock 复现。真模型入口、长跑参数和计费边界必须读对应最新 iteration 与脚本帮助，不能从历史示例照抄。

## Documentation Map

| 需要回答的问题 | 读取位置 |
|---|---|
| 现在能做什么、缺什么 | 本文件 |
| 9 阶段节点是否打通 | 根 [`README.md`](../README.md#流水线-sop实时状态) |
| 某轮具体改了什么、怎么验 | [`iterations/README.md`](iterations/README.md) -> 对应 iteration |
| 为什么形成当前架构 | [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) |
| Aeloon 集成细节 | [`AELOON_INTEGRATION.md`](AELOON_INTEGRATION.md) |
| 用户操作 | [`product/GETTING_STARTED.md`](product/GETTING_STARTED.md) |
| 产品边界 | [`product/PRODUCT_SPEC.md`](product/PRODUCT_SPEC.md) |

## Maintenance Contract

- 收官时更新 `Current Snapshot`、`Capability Map`、`Latest Accepted Evidence`、`Open Gaps` 和 `Next Candidates` 中受影响的行。
- `Latest Accepted Evidence` 只保留最近一次会改变接力判断的证据，通常不超过 8 条。
- 不追加“Phase Status - iter NNN”长段；完整结果写入当轮 iteration，里程碑级变化再更新 `PROJECT_HISTORY.md`。
- 测试数只在本文件与最新 iteration 保留当前值；README 历史表不逐轮复制测试数字。

## Latest Transition

iter 093 完成 agent 记忆入口瘦身：当前状态、历史里程碑和逐轮证据分层维护，默认必读链缩短约 94%；同时修正产品隐私/进度表述与 iter-start/iter-finish 防膨胀契约。业务行为未变，iter 092 仍是最新业务能力基线。
