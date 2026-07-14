# Iteration 103 - 本地 Fake Provider 整链

## Context

iter 102 已将 canonical 验收隔离到 synthetic workspace 并绑定审计基线，但现有 mock 主要证明组件编排，没有稳定覆盖“真实 loopback HTTP 传输 → provider adapter → 媒体落盘 → ledger/callback”整链。本轮建立测试专用 fake provider，填补 D-04/D-05 对应的本地 E2E 证据，不接触真实供应商。

## Plan

1. 建立只在测试作用域启动的 loopback fake provider，提供确定性图片、视频 create/poll/result、严格 PNG/MP4 fixture 与脱敏请求计数。
2. 仅通过测试侜用域依赖注入允许 loopback peer；不增加任何生产 localhost provider 开关。
3. 使用 synthetic drama workspace 覆盖图片 HTTP 整链、独立 callback 进程的视频整链，以及五站前端参数、route 校验和 worker 接收的一次性授权闭包。
4. 为 OpenAI adapter 与 compatible adapter 建立分离的 golden request fixture，记录本地复核日期并明确非供应商权威。
5. canonical verify 增加必跑 `local_drama_e2e` 步骤和独立组件 evidence；loopback 不可用时 fail-closed，不得以 skip 充当通过。

## Acceptance

- `A103-01`：fake provider 仅绑定 loopback，返回严格 PNG/MP4 fixture，请求计数只投影方法/路由/次数，不记录授权值、prompt 或完整 URL。
- `A103-02`：图片整链经真实 HTTP 传输进入生产 adapter，完成 staging/receipt/canonical 提升并验证结构、hash 与单次 provider 请求。
- `A103-03`：独立 Web callback 进程完成视频 create/poll/result 与严格 MP4 下载，ledger、meta 和本地产物一致，不重复提交。
- `A103-04`：五站真文本参数从前端构造、route 校验到 worker 消费完整闭包，授权只适用当次站点且不进入公开 job 投影。
- `A103-05`：OpenAI/compatible golden contract 分离、有复核日期与“非供应商权威”声明，两类 adapter 的请求形状均由回归锁定。
- `A103-06`：`verify.sh` 必跑 `local_drama_e2e`；独立组件 evidence 为 `local-e2e`，总 evidence 仍为 `mock-functional`；loopback 失败/禁用时整体验收失败而非 skip。
- 聚焦回归、correctness/behavior、security/boundary、provider-contract/Web-callback 三视角只读审查通过；修复 findings 后在 implementation commit 上运行最终 `bash scripts/verify.sh`。

## Implementation Notes

- 实验台保持生产 `src/` 零改动。loopback URL/peer 放行与 `HTTPSConnection → HTTPConnection` 替身只存在 `run_local_drama_e2e.py` 进程内，退出后由回归反向证明生产 validator 仍拒绝 `127.0.0.1`。
- fake provider 只绑定 `127.0.0.1:0`，返回确定性严格 PNG 与通过生产 box/sample 探测的 5s 720×1280 MP4；对外计数只含固定路由分类与次数。
- 图片链经生产 OpenAI image adapter 发出真实 loopback HTTP，覆盖每角色单次请求、staging、artifact receipt、canonical promote 与 staging cleanup。
- 视频链使用独立 callback 子进程投影生产 route；fake provider 实际回调两个 PNG capability，再执行 asset upload/poll、单次 create、两次 poll、result download 与 ledger/meta/canonical 提交。
- 五站闭包同时检查前端统一 payload helper、真实 route 参数守门和 worker 接收；每站下一个缺授权请求均被 400 拒绝。
- component evidence 使用独立原子单硬链接 JSON，绑定同一 acceptance run/HEAD/tree；canonical finish 用 `O_NOFOLLOW`、限长与读前后 stat 校验，拒绝缺失、陈旧、symlink 或任何 `provider-validated` 声明。
- 三视角审查后修复所有有效 findings：MP4 `tkhd`/sample-entry 尺寸假一致、视频缺成功后零网络 resume、图片 receipt/hash/reference 只查字段存在、前端检查未针对实际 `JS_DASHBOARD`、passed evidence 可省略组件 step、provider-validation 别名声明绕过、callback 可探测任意本机端口、ambient image endpoint 优先级与畸形 image row 断连。

## Acceptance Result

<待 iter-finish 逐项回填 A103-01 至 A103-06。>

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `scripts/run_local_drama_e2e.py`、`tests/support/local_drama_*.py` | loopback fake provider、独立 callback 进程、图片/视频/五站整链与脱敏 component evidence。 |
| `tests/fixtures/provider_contracts/*.json`、`tests/test_local_drama_e2e.py` | OpenAI image 与 compatible video 本地 golden contract、媒体严格性、守门不放宽与 evidence 安全回归。 |
| `scripts/verify.sh`、`scripts/write_acceptance.py` | canonical 必跑 `local_drama_e2e`，且将组件证据与当次 run/commit 严格绑定。 |
| `tests/test_agent_harness.py`、`tests/test_smoke_scripts.py` | 缺失/陈旧/伪造/symlink evidence、E2E 失败不 skip 与 verify 入口回归。 |
| `docs/iterations/README.md`、本文档、handoff | iter103 立项、active snapshot 与证据计划。 |

## 不在本轮范围

- 任何真实 provider 请求、账单/任务状态查询或产品环境 localhost 放行。
- crash/restart 状态穷举矩阵、统一 paid-ledger 重构与 D-03 单集角色投影。

## Notes

- 本轮显式使用 repository-local `iter-start`；收官必须使用 `iter-finish`。
- 本地 fake provider 只能将对应组件提升为 `local-e2e`，不能产生 `provider-validated` 证据。
- 只 commit、不 push；未跟踪体检报告保持用户所有。
