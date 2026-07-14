# Iteration 104 - Crash/Restart 与状态矩阵

## Context

iter 097-101 已多轮修复短剧真文本、图片和视频链路的恢复边界，但后续迭代仍发现早期验收未覆盖的 crash window 与状态漂移。iter 102-103 已恢复 canonical 验收的隔离可信度并建立本地 fake-provider 整链；本轮在不访问真实 provider、私有 workspace 或用户内容的前提下，用跨进程 crash/restart 与穷举状态矩阵验证付费请求的零重复、账本/产物一致性和 fail-closed 恢复。

## Plan

1. 建立测试专用 subprocess driver，在测试 seam 写入最小 durable snapshot 后执行 `os._exit`，再由新进程恢复；不增加生产 fault 环境变量。
2. 参数化遍历短剧五站文本入口的付费状态、恢复规则与漂移判定，避免各站只覆盖不同字符串子集。
3. 建立图片六阶段矩阵：未发送、提交未知、响应收到、staging 写入、receipt 写入、canonical promote；逐场景断言 provider 请求次数、零重复付费与 artifact lineage。
4. 建立视频六阶段矩阵：提交前、submitting、submitted/task-id、媒体落盘、meta 落盘、succeeded ledger；逐场景断言 provider create/poll/download 次数和 ledger/产物一致性。
5. 将付费恢复状态收敛为统一枚举或集中定义，并对所有成员做穷举测试；只修复矩阵实际复现的问题，不预先进行 paid-ledger 大重构。
6. 收官时复核 iter 102-104 Acceptance ID 的承诺闭包，确认 hardening 未破坏 canonical mock-functional 与短剧 local-e2e 证据。

## Acceptance

- **A104-01**：测试专用 subprocess driver 能在指定 seam 执行 `os._exit`，并由独立新进程恢复；生产代码不新增 fault-injection 环境变量或真实 provider 旁路。
- **A104-02**：五站文本入口参数化遍历统一付费状态和恢复规则，覆盖合法恢复、提交未知不重发、成功态幂等、输入/模型/endpoint 漂移 fail-closed。
- **A104-03**：图片矩阵覆盖未发送、提交未知、响应收到、staging、receipt、canonical 六个阶段；每个阶段断言 provider 请求次数、零重复付费、ledger/receipt/canonical 血统一致性。
- **A104-04**：视频矩阵覆盖提交前、submitting、submitted/task-id、媒体落盘、meta 落盘、succeeded ledger 六个阶段；每个阶段断言 create/poll/download 次数、零重复 create、ledger/产物一致性和合法恢复。
- **A104-05**：付费状态采用统一枚举或集中定义，穷举测试证明所有成员均被文本、图片、视频策略显式处置；只提交矩阵证明必要的生产修复，不实施预防性 paid-ledger 大重构。
- **A104-06**：correctness、security/boundary 与 iter102-104 acceptance-closure 三视角只读审查无未处理 P0/P1；最终 `bash scripts/verify.sh` 在 implementation commit 上通过并仅产生 `mock-functional` canonical 证据，短剧组件保持独立 `local-e2e`、`provider_validated=false`，且不访问真实 provider、私有 workspace 或用户内容。

## Implementation Notes

- 新增 `src/paid_recovery_states.py`，以纯字符串 `frozenset` 集中现有文本、图片、视频持久状态及关键分类；不引入 Enum 序列化、ledger schema migration 或 paid-ledger 重构。`src/web/jobs.py`、`src/drama_multimodal_smoke.py`、`src/drama_video.py` 仅把原有内联集合机械替换为共享常量，矩阵未证明需要新的生产行为修复。
- 新增测试专用 crash driver。driver 只接受带 marker 的系统临时 synthetic workspace，使用白名单子进程环境并在导入生产模块前短路 dotenv；crash seam 写入带 PID/import nonce 的原子 marker 后执行 `os._exit(86)`，恢复由全新解释器完成。生产代码未增加 fault-injection 环境变量或 localhost/provider 旁路。
- 文本矩阵对五站逐项遍历全部持久状态、unknown、精确 canonical 恢复及 input/model/endpoint/account 单项漂移；另对五站逐一验证 durable `submitting` 后进程死亡，fresh restart 不触发 provider 并要求 reconciliation。
- 图片矩阵执行生产 `_run_images` 覆盖六个窗口。`response_received` 在当前 adapter 中没有独立持久状态，因此用独立外部 response event 证明“响应已到但 staging 未 durable”，随后与 submission unknown 一样保持 `started` 并 fail-closed；staging、receipt、canonical fallback 均验证 provider total/delta、receipt/bytes/projection hash 和 staging 清理。代表性 canonical projection seam 使用真实 `os._exit` 后零 provider 恢复。
- 视频矩阵执行生产 `video_status` 与 `run_video_job` 覆盖六个窗口，分别统计 upload/create/poll/download。额外在真实 `create_video_task` 内记录首次 create 后、task-id 落盘前执行 `os._exit`，fresh restart 保持 `submitting`、总 create=1、poll/download=0；media/meta torn pair 也经 fresh process 修复。零重复付费只约束 create，submitted 后合法 poll/download 可增加。
- 中期审查发现初版策略表自证，已改为生产入口驱动；最终审查又发现 submitting create-response-loss、model/endpoint 独立漂移、canonical fallback、response 可观察性与测试 workspace escape 缺口，均在测试侧闭合。测试明确只证明进程 crash/restart，不外推为断电或内核崩溃安全。
- 聚焦回归：findings 修复后，新状态/矩阵与既有代表性恢复用例共 **25 项通过**；implementation commit 上唯一一次 canonical 验收 **2100 tests OK**，完整 evidence 见下节。

## Acceptance Result

- **A104-01 — 通过。** 两个测试专用 driver 在导入生产模块前固定 skip-dotenv/mock 白名单环境，只写带 marker 的系统临时 synthetic workspace；seam marker 含 PID 与 import nonce，随后执行 `os._exit(86)`，恢复进程的 nonce 不同。生产代码未增加 fault-injection 环境变量、真实 provider 旁路或 localhost 放行。
- **A104-02 — 通过。** 五站逐项遍历 `TEXT_ATTEMPT_STATUSES`、unknown、精确 canonical 恢复及 input/model/endpoint/account 单字段漂移；所有不安全状态都在 provider 前 fail-closed。五站还分别验证 durable `submitting` 进程死亡后 fresh restart 不自动发请求并要求 reconciliation。
- **A104-03 — 通过。** 图片六阶段均执行生产 `_run_images`：每场景总 generate=1，恢复增量仅 not-sent=1，其余=0；staging/receipt/canonical fallback 最终 bytes SHA、receipt SHA、projection/record SHA 一致并清理 staging。当前 adapter 没有独立 durable response 状态，矩阵用持久 `image_response_received` event 区分“响应已到”与 submission unknown，二者均安全收敛到 `started` fail-closed。canonical projection 代表 seam 经 fresh process 零 provider 收尾。
- **A104-04 — 通过。** 视频六阶段均执行生产 `video_status` 与 `run_video_job`：只有 pre-submit create=1；submitted/media 合法 poll+download 各 1；meta/succeeded 零网络。create-response-loss seam 在生产 `create_video_task` 内先持久化第 1 次 create，再于 task-id 落盘前 `os._exit(86)`；fresh restart 保持 `submitting`、总 create=1、poll/download=0。media/meta torn pair 也经 fresh process 修复为 ledger/artifact/hash 一致。
- **A104-05 — 通过。** `src/paid_recovery_states.py` 以 `frozenset` 集中三域现有状态与分类，production validator/branch 与穷举测试引用同一真源。矩阵未复现新的生产行为缺陷，因此只做等价集合替换；无 ledger schema migration、无预防性 paid-ledger 大重构。
- **A104-06 — 通过。** correctness/behavior、security/boundary、acceptance-closure/harness 三视角初审发现 1 个 P1、4 个 P2 验收缺口，全部修复并复核清零；最终无未处理 P0-P2。聚焦回归 **25 tests OK**。唯一一次 `bash scripts/verify.sh` 在 implementation commit `e10a585f51fc9a3868586e5ca2ba57a9e85f1fbb`（tree `f185ac00232b9eaa3c235797eaf87b17dc6efff3`）上 exit 0：**2100 tests OK**，15 steps / 142 秒，schema v2、`mock-functional`、`canonical-mock-offline`、`isolated-mock`、`tracked_scope_clean=true`，mock preflight **0 FATAL / 0 WARN**。
- 独立短剧组件证据与同一 run/HEAD/tree 绑定：`local-e2e`、`provider_validated=false`；2 image generate、2 asset upload、2 asset poll、1 video create、2 video poll、1 video download、2 callback fetch，五站授权 5/5，成功后 zero-network resume。未运行真实文本、图片、视频 provider 或账单接口。
- 用户未跟踪的 `docs/2026-7-14体检报告.md` 保持原样，未读取、未 stage、未 commit。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_104_crash_restart_state_matrix.md` | 建立 iter104 计划、验收 ID 与审计记录骨架 |
| `docs/iterations/README.md` | 追加 canonical iteration 索引 |
| `src/paid_recovery_states.py` | 集中文本、图片、视频既有付费恢复状态与分类 |
| `src/web/jobs.py` | 文本 attempt validator、canonical 恢复与 reconciliation 引用共享状态 |
| `src/drama_multimodal_smoke.py` | 文本采用、图片 receipt、视频计数与阻断引用共享状态 |
| `src/drama_video.py` | 视频 ledger validator 与状态投影引用共享状态 |
| `tests/support/drama_crash_driver.py` | 图片/视频六阶段、真实 `os._exit` 和持久 provider counter driver |
| `tests/support/drama_text_crash_driver.py` | 五站文本 durable submitting 跨进程 driver |
| `tests/test_drama_paid_recovery_states.py` | 状态集合、分类和生产 validator 穷举测试 |
| `tests/test_drama_crash_restart_matrix.py` | 文本、图片、视频生产入口矩阵与代表性跨进程恢复测试 |
| `tests/test_drama_text_crash_restart_matrix.py` | 五站全状态、漂移与逐站 fresh-process crash 矩阵 |
| `README.md` | 同步 iter104 项目状态与实时 SOP |
| `docs/AGENT_HANDOFF.md` | 更新 canonical 基线、accepted commit、能力、缺口与 transition |
| `docs/PROJECT_HISTORY.md` | 追加 iter104 里程碑、实现索引、长期决策与工程教训 |

## 不在本轮范围

- D-03 单集角色投影修复，后续另起单一业务迭代。
- 真实文本、图片、视频 provider 调用、状态查询、账单校验或质量判定。
- 未经矩阵复现证明的统一 paid-ledger 架构重写。
- episode 2+ 真视频、ComfyUI 与更广 codec 支持。

## Notes

- 用户未跟踪的 `docs/2026-7-14体检报告.md` 保持原样，不读取、不 stage、不 commit。
- 收官遵循 `iter-finish`：聚焦检查与多视角只读审查在前，implementation commit 后只运行一次 canonical `verify.sh`，最后 docs-only 收官提交；只 commit、不 push。
