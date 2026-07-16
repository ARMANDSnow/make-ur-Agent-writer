# Iteration 117 - 短剧逐镜视频 Provider 能力与 Once-only Attempt 恢复

## Context

iter115 已完成阶段 D1：从 fresh RenderPlan、C1 与 coverage-ready C2 冻结 provider-neutral `EpisodeShotVideoPlan`，逐镜记录目标时长、exact first/optional tail、ordered references 与 previous-tail lineage。iter116 已完成阶段 D2：建立 content-addressed strict MP4 candidate、append/selection 分层、retired audit、精确 stale/reconcile/repair 与整集 production coverage；当前 canonical 基线为 **2360 tests OK**，总级别 `mock-functional`，本地组件 `local-e2e`、`provider_validated=false`。D1-D2 仍不包含视频 provider capability、attempt、submit/poll/download 或付费 crash recovery，旧 `src/drama_video.py` 继续只是 episode 1 高光视频兼容入口。

根据 handoff、PROJECT_HISTORY、短剧 A-J SOP 与 iter116 的明确顺延项，本轮优先规划阶段 D3 的纯本地窄闭环：冻结 provider/capability/授权与 D1-D2 exact identity，通过代码内注入的 deterministic fake adapter 验证一次 submit、durable submission/terminal/artifact receipt、纯 poll/download 恢复及 D2 candidate 补账。执行状态必须明确投影为 `not_sent | unknown | submitted | terminal`；任何 recorded attempt 都不得自动再次 submit，只有 `not_sent` 可在新的显式操作下开启新 attempt，`unknown` 必须停在对账/人工处置边界。

本轮延续阶段计划中固定的 clean-room 参考边界：ArcReel commit `44321d055484db312877e55beb1e1e16231b59c4` 的 `lib/video_backends/base.py`、`lib/generation_worker.py`、`server/services/resume_executor.py`，LumenX commit `743683387384fb1d9fff72038933e7249d416076` 的 video task/recovery 抽象，以及 LocalMiniDrama commit `92c66dd75688d83aac3ccc31bb51378613122cbc` 的 `videos.js` / `videoService.js`；只借鉴 submit/poll/download 分层与恢复思想，不复制外部代码、prompt、测试或独特结构。立项阶段只创建本 iteration 与索引，不开始业务实现，不读取 `.env`，不调用 fake HTTP 或真实 provider，不产生任何真实视频请求。

## Plan

### Implementation Context
- `must_read`: `README.md`, `docs/iterations/README.md`, `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_114_drama_shot_image_provider_capability_attempt_recovery.md`, `docs/iterations/iteration_115_drama_shot_video_plan_frozen_frames.md`, `docs/iterations/iteration_116_drama_shot_video_candidates_selection_coverage.md`, `src/drama_schemas.py`, `src/paid_recovery_states.py`, `src/drama_shot_image_attempts.py`, `src/drama_shot_image_attempt_store.py`, `src/drama_shot_video.py`, `src/drama_shot_video_store.py`, `src/drama_shot_video_candidates.py`, `src/drama_shot_video_candidate_store.py`, `src/drama_video.py`, `src/drama_video_client.py`, `tests/_drama_shot_video_base.py`, `tests/_drama_shot_video_candidate_base.py`, `tests/test_drama_shot_video.py`, `tests/test_drama_shot_video_store.py`, `tests/test_drama_shot_video_candidates.py`, `tests/test_drama_shot_video_candidate_store.py`, `tests/test_drama_paid_recovery_states.py`, `tests/test_drama_crash_restart_matrix.py`, `tests/test_drama_video.py`
- `expected_changes`: `docs/iterations/iteration_117_drama_shot_video_provider_capability_attempt_recovery.md`, `docs/iterations/README.md`, `src/drama_schemas.py`, `src/paid_recovery_states.py`, `src/drama_shot_video_attempts.py`, `src/drama_shot_video_attempt_store.py`, `tests/_drama_shot_video_attempt_base.py`, `tests/test_drama_shot_video_attempts.py`, `tests/test_drama_shot_video_attempt_store.py`, `tests/support/drama_shot_video_attempt_driver.py`, `tests/test_drama_paid_recovery_states.py`, `README.md`, `docs/product/short_drama_module.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪体检报告；`src/drama_video.py`、`src/drama_video_client.py`、现有 video job/smoke/multimodal 链只读核对兼容边界，不修改旧 episode 1 高光视频链；不接 fake HTTP 或真实网络 provider，不改 Web/jobs/routes、CLI/runner、preflight/config、现有授权/计费入口、通用 DAG/worker、C1-C3、D1-D2、`DramaEpisode`、`RenderPlan`、现有导出；canonical verify 自管 acceptance 产物除外

1. 在 `src/drama_schemas.py` 增加 strict D3 schema：provider-neutral video capability、付费提交门禁快照、attempt spec、submission/terminal/artifact receipt、attempt record、episode ledger 与 inspection projection。attempt 冻结 season/episode/stable shot、D1 plan/spec、D2 pre-manifest、mode、duration/resolution、exact first/tail/ordered references、provider/model/account/endpoint/auth/capability/authorization fingerprints 与单次提交上限；持久状态不得保存 key、完整 prompt、签名 URL、provider raw response 或无界错误文本，也不改变 D1/D2 既有 schema shape。
2. 新建 `src/drama_shot_video_attempts.py` 作为纯函数领域层：只从 fresh D1 spec、fresh D2 manifest、静态 capability 与显式授权门禁构建 byte-stable attempt。提交前必须验证 I2V/R2V mode、async/resume、first/tail 支持、ordered exact references/最大引用数、duration、resolution、输出 `video/mp4`、估算费用/授权预算与 `max_submit_calls=1`；任一不兼容、未知费用或授权/CAS 不一致均在 adapter 调用前 fail closed，D1 仍是唯一输入装配真源，D3 不二次裁剪或重组引用。
3. 定义最小代码内可注入 `ShotVideoProviderAdapter` seam，分离 `submit / poll / download`；只为 deterministic local fake adapter 与未来单独审查的 backend 提供协议，不做动态 registry、热加载、网络 transport、通用 task DAG 或 worker。fake adapter 使用进程外持久 counter 与受控 opaque task/result token，证明每个 attempt 的 `submit` 最多一次；允许 submitted attempt 重复安全 `poll`，允许 terminal-success 后重试 `download`，但二者都不得回到 submit。
4. 新建 `src/drama_shot_video_attempt_store.py`：在同一 workspace lock 与 source/target/provider/authorization CAS 域内完成最后一道付费门禁并先 durable 写 started marker，再允许一次 submit。明确四类恢复投影：transport 明证未发送为 `not_sent`；started 后 crash、response loss 或无法证明提交结果为 `unknown`；durable provider task id/submission receipt 后为 `submitted`，只可纯 poll/download；provider 明确失败、D2 exact candidate 已补账成功或本 attempt 明确关闭为 `terminal`。所有 recorded attempt 零自动重复 submit，`not_sent` 也只能由新的显式 attempt 重新发起，`unknown` 不得靠猜测 task id、目录产物或新配置恢复。
5. submitted 路径必须先 durable 保存 bounded submission receipt，再记录 poll terminal receipt；terminal success 只允许以冻结 task/provider identity 下载到私有 staging，复用 D2 bounded MP4 probe 形成 artifact receipt，并只通过既有 `append_local_shot_video_candidate()` 进入 D2。receipt、MP4 identity、candidate ID/fingerprint 与 post-manifest fingerprint 必须精确互证；candidate append 不自动选择，D2 explicit selection 与整集 coverage 仍是 production compose 的唯一门禁。artifact receipt、candidate 已 append、succeeded lost-response 与重启补账均只能零 submit 收尾。
6. 新增纯函数、store、deterministic fake adapter 与真实子进程 crash seam 测试，覆盖 schema/fingerprint、付费前门禁、capability matrix、episode 2+、submit once、not-sent/unknown/submitted/terminal 穷尽分类、纯 poll/download、D2 candidate 补账但不自选、selection 后 coverage、provider/source/authorization ABA、深层/超限/重复键 JSON、MP4/hash/时长/尺寸、symlink/FIFO/目录、partial write、TOCTOU/temp ownership、错误脱敏与 socket sentinel。聚焦回归范围包括 iter105-116、C1-C3、D1-D2、paid vocabulary/crash matrix、四导出、season export、local fake-provider 既有链与 legacy episode-1 video；先做相关单测、`py_compile`、harness 与 `git diff --check`，再完成三视角只读审查和 findings 聚焦回归，最后只运行一次 canonical `bash scripts/verify.sh`。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 D1 exact spec → capability/authorization-bound attempt → durable submission/terminal/artifact receipts → D2 candidate 的身份闭包，四类状态投影穷尽且无歧义，submit once、纯 poll/download、candidate 不自选、D2 selection/整集 coverage、episode 2+ 与 legacy episode-1 video 向后兼容
- `security_boundary`: 核对提交前授权/预算/上限门禁与 workspace/provider/source/target CAS，ledger/staging 的 bounded strict JSON/MP4、nofollow/nonblock/regular-file、symlink/FIFO/目录/TOCTOU/temp ownership，持久/公开错误不泄露 prompt、URL、raw response、凭据或内部路径，生产链除注入 local fake adapter 外保持零网络
- `extra_risk_view`: `media/paid-recovery`，核对 marker-before-submit、not-sent 明证、unknown 安全停止、submitted 纯恢复、terminal 收口、submit/poll/download crash windows、进程外 counter、receipt/candidate 补账、provider/source/authorization ABA 与整集 coverage 均不重复付费提交、不把旧/坏视频认作 production ready

- **A117-01**：capability、submission gate、attempt spec、submission/terminal/artifact receipts、record/ledger/inspection strict schemas 可 byte-stable round-trip；细粒度状态必须穷尽映射到 `not_sent | unknown | submitted | terminal`，拒绝 extra、bool/非有限数、未知状态/组合、跨 episode/shot、非 canonical path 与 fingerprint 篡改；D1/D2、`DramaEpisode` 与 `RenderPlan` 既有 shape 不变。
- **A117-02**：attempt 只从 fresh D1 与 fresh D2 构建并冻结 exact plan/spec/pre-manifest、mode、时长/分辨率、first/tail/ordered references、provider/capability/authorization identity；付费 submit 前在同一锁/CAS 域完成 capability、授权预算、单次提交上限和输入完整性门禁。不兼容、费用未知/越界或任一 identity 漂移时 submit counter 保持 0，D3 不二次裁剪、猜测或重组 D1 输入。
- **A117-03**：每次 submit 前先 durable 写 started marker；真实子进程与 fake adapter 持久 counter 证明每个 attempt 的 submit delta 最多为 1，且任何 recorded attempt 的自动恢复 submit delta 为 0。明确未发送进入 `not_sent`；started/crash/response-loss 进入 `unknown` 并等待对账；durable task id/receipt 进入 `submitted` 后只 poll/download；成功、明确失败或显式关闭进入 `terminal`。即使 `not_sent` 也只允许新的显式 attempt，不在 resume 内自动重提。
- **A117-04**：submitted attempt 的 provider/task/capability/authorization identity 不因当前配置或 mock 漂移而改变；poll 可恢复且不重组请求，terminal-success 后 download 可重试但不 resubmit。submission、terminal 与 artifact receipt 均 bounded、durable、相互绑定；坏/冲突 task/result、provider terminal failure、下载中断与 receipt 漂移 fail closed，不把 unknown 当 failed、submitted 或零费用。
- **A117-05**：strict MP4 只经 D2 validator 与 `append_local_shot_video_candidate()` 入池，artifact receipt、candidate 与 manifest post-state 精确互证；artifact_received、candidate 已 append 和 succeeded lost-response 可零 submit 补账。新 candidate 不自动选择，只有既有 D2 guarded selection 后才可能补齐整集 production coverage；任一 required shot missing/stale/invalid/blocked 继续列出 stable shot IDs 并阻断阶段 F。
- **A117-06**：D3 新链、iter105-116、C1-C3、D1-D2、paid recovery/crash matrix、四导出、season export、既有 local fake-provider 与 legacy episode-1 video 聚焦回归通过；correctness/behavior、security/boundary、media/paid-recovery 三个独立只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`；最高总验收等级为 `mock-functional`，D3 deterministic fake adapter 证据单列 `local-e2e`、`provider_validated=false`，不运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。

## Implementation Notes

- 已新增 provider-neutral capability、exact paid authorization gate、attempt spec、submission/terminal/artifact/closure receipts、record/episode ledger 与四类 inspection。授权同时绑定 authorization id、episode、shot、D1 request、provider/model/account/endpoint/auth 与 budget/max-submit；adapter 必须暴露对应的 secret-free immutable identity，submit/poll/download 前 exact match。
- 状态实现为 `started → not_sent | submission_unknown | submitted → provider_succeeded | provider_failed → artifact_received → succeeded`，另以 `closed_unknown` 保存人工对账后的显式关闭事实；四类投影保持 `not_sent | unknown | submitted | terminal`。同一 authorization fingerprint 在出现任何非 `not_sent` 事实后不可再次用于新 attempt；`not_sent` 也必须显式传入 `start_new_attempt=True`，resume 永不 submit。
- strict store 在 workspace lock 内先 durable 写 started marker，再执行唯一一次 adapter submit；submitted 后只 poll/download。terminal-success 下载到 private staging，经既有 D2 MP4 identity 校验并只调用 `append_local_shot_video_candidate()` 入池；candidate 不自选，succeeded 会复核 exact D2 candidate。代码内 `LocalFakeShotVideoAdapter` 只消费注入的 synthetic MP4 bytes，不含 HTTP/registry/provider transport。
- submission receipt 绑定 attempt/backend/account/authorization/input，terminal receipt 绑定 submission receipt；ledger 在 backend/account scope 内拒绝 task/result token 冲突。unknown closure 使用 bounded resolution 与 evidence fingerprint，不把未知结果改写为 not-sent。
- crash driver 覆盖 started、submit response-loss、submitted、terminal、download、staging、artifact、candidate 与 succeeded lost-response 窗口，并以进程外 counter 证明 restart submit delta 为 0。episode 2 store 链覆盖 attempt/receipts/D2 candidate、不自选与显式 selection 后 coverage ready。
- 三视角只读审查均无 P0；共同发现并已修复：单次授权可跨 shot/terminal failure 复用（P1）、adapter/model identity 未进入实际调用闭包（P1/P2）、task/result token 冲突未拒绝（P2）、unknown 缺少 durable explicit-close（P2），以及 episode 2 store 证据不足（P3）。主线程补齐 exact authorization consumption、adapter identity gate、receipt collision guard、closure transition 与定向回归；修复后 D3/paid 32 tests OK，D1-D3/C1-C3/RenderPlan/导出/legacy video 聚焦 235 tests OK。
- 全程保持 `OPENAI_MODEL=mock`、socket sentinel/代码内 fake；未读取 `.env`、未接真实 provider、未产生真实视频请求，未修改旧 episode 1 高光视频模块。canonical `verify.sh` 尚未运行，留待 implementation commit 后唯一一次执行。

## Acceptance Result

- **A117-01 PASS**：capability、exact submission gate、attempt spec、submission/terminal/artifact/closure receipts、record/episode ledger/inspection 均为 strict、fingerprinted、extra-forbid schema；细状态穷尽映射到 `not_sent | unknown | submitted | terminal`。D3/paid 聚焦 32 tests 通过，D1/D2 与既有 schema 未改 shape。
- **A117-02 PASS**：attempt 只接受 fresh D1/D2 exact identity；authorization 绑定 episode/shot/request 与 provider/model/account/endpoint/auth，adapter operational identity 在 marker 前 exact match。mode、tail、references、duration、resolution、budget 与 `max_submit_calls=1` 不满足时 submit counter=0。
- **A117-03 PASS**：workspace lock 内 started marker 先于 submit；同一 authorization 的任一非 not-sent 事实 durable consumed，provider failure/replay 不再 submit。not-sent 只有显式 `start_new_attempt=True` 才能新建 attempt；unknown 可 durable explicit-close，resume 永不 submit。九个真实子进程 crash 窗口与进程外 counter 证明 restart submit delta=0。
- **A117-04 PASS**：submission receipt 绑定 attempt/backend/account/authorization/input，terminal receipt 绑定 submission receipt；wrong adapter/model/backend 在 poll/download 前零调用，backend/account scope 下 task/result collision 与 receipt/identity drift fail closed。submitted 只 poll，provider-success 后 download 可重试且不 resubmit。
- **A117-05 PASS**：artifact 使用既有 D2 bounded strict MP4 identity，private staging 与 artifact receipt 互证，只经 `append_local_shot_video_candidate()` 入池；candidate 不自选，candidate/manifest/succeeded lost-response 可零 submit 补账。episode 2 store 链验证 receipts→D2 candidate→显式 selection→整集 coverage ready。
- **A117-06 PASS**：修复审查 findings 后，D3/paid **32 tests OK**，D1-D3/C1-C3/RenderPlan/导出/season export/legacy episode-1 video 聚焦 **235 tests OK**，`py_compile`、harness 与 `git diff --check` 通过。correctness/behavior、security/boundary、media/paid-recovery 三个独立只读视角最终无遗留 P0/P1/P2。

canonical `bash scripts/verify.sh` 在 implementation commit `daa06529399714fd0de57d705954cedc72747fda` 上仅运行一次并通过：**2386 tests OK**，15 completed steps，236 秒，run `34f7fcbf83fb4be18a1638f3db80bc87`，tree `fdc749b540d10e5c4ffea8a4edf5a4b9e4a41157`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN。标准总等级为 **`mock-functional`**；mandatory local-drama 与本轮代码内 fake adapter 证据为组件级 **`local-e2e`**，**`provider_validated=false`**。未读取 `.env`，未运行真文本、真图片、真视频、真 ComfyUI 或任何真实 provider 请求。

剩余风险均在本轮明确边界之外：真实 provider 的任务语义/账单/费用/超时/质量未验证；process-crash 证据不证明 power-loss 或真实 provider exactly-once；尚无 D4 主观质量/跨镜连续性、Web/CLI、staging GC、完整 episode 2+ 成片。旧 episode 1 高光视频链保持未修改。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮新增规则是短剧 D3 provider/authorization/task/receipt identity 闭包的项目内具体实现；跨项目通用原则已由 AGENTS 的付费入口、逐次授权与真视频单次提交铁律覆盖，无需另建重复长期文档。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_117_drama_shot_video_provider_capability_attempt_recovery.md` | 新建 iter117 固定八段计划与 D3 边界 |
| `docs/iterations/README.md` | 追加 iter117 canonical index |
| `src/drama_schemas.py` | 增加 D3 capability、exact once authorization、receipts、record/ledger/inspection strict schema |
| `src/paid_recovery_states.py` | 增加 D3 全状态与四类恢复投影 |
| `src/drama_shot_video_attempts.py` | 新增 attempt 构建、状态迁移、closure 与 D2 completion 纯函数 |
| `src/drama_shot_video_attempt_store.py` | 新增 durable ledger/staging、adapter identity gate、submit-once 恢复与 local fake adapter |
| `tests/_drama_shot_video_attempt_base.py` | 新增 synthetic D3 capability/gate/MP4 fixture |
| `tests/test_drama_shot_video_attempts.py` | 新增 strict schema、状态迁移、四类投影与 episode 2 identity 测试 |
| `tests/test_drama_shot_video_attempt_store.py` | 新增 submit-once、授权消费、adapter/task/result/closure、D2 bridge、coverage 与文件边界测试 |
| `tests/support/drama_shot_video_attempt_driver.py` | 新增真实子进程 crash-window 与持久 counter driver |
| `tests/test_drama_paid_recovery_states.py` | 增加 D3 四类状态穷尽性断言 |
| `README.md` | 同步 iter117 里程碑与短剧 D1-D3 实时 SOP |
| `docs/AGENT_HANDOFF.md` | 就地更新当前基线、能力/缺口、验收证据与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | 追加 iter117 阶段级里程碑与关键实现路径 |

表内仅列实际变更；用户未跟踪体检报告、旧 episode 1 视频链与其它计划外文件均未修改。

## 不在本轮范围

- 任何真实 video provider/network adapter、fake HTTP server、真实 task API、真实上传/下载、`.env`、凭据、真实授权、真实预算扣费、真实视频请求与 provider 校准；本轮只允许代码内 deterministic local fake adapter。
- 修改旧 `src/drama_video.py`、`src/drama_video_client.py`、Web video job/routes/static、smoke/multimodal、episode 1 高光视频产物与兼容行为；不把旧高光 ledger/task 迁入 D3。
- Web/API/CLI/runner、批量逐镜生成、后台轮询/取消、候选播放/比较 UI、人工对账 UI、通用 DAG/worker/lease/provider lane/registry/pricing/Insights；这些属于后续 D/G/I 或单独入口轮次。
- 自动选择 D2 candidate、用最新目录文件猜 selection、视觉相似度/模型质量评分、跨镜主观连续性、episode 2+ 完整成片；D3 只建立执行事实并继续服从 D2 guarded selection/coverage。
- TTS/voice、音频、`TimelineManifest`、字幕、BGM/SFX、FFmpeg/compositor、媒体 QA、编辑器导出、生产工作台、归档与阶段 J provider capstone。
- 修改 `DramaEpisode`、Storyboard、`episode_NN.json`、creative fingerprint、RenderPlan v1、C1-C3 identity/schema、D1 plan/spec identity、D2 candidate/selection/coverage identity、现有 Comfy/season export 消费路径。
- power-loss、内核崩溃、敌对本机进程或 production provider exactly-once 证明；durability 结论最多限定于受控本地 writer 与真实子进程 crash/restart。
- `.env`、私有 `data/outputs/logs/workspaces` 内容、`小说txt/` 与用户未跟踪文件。

## Notes

- 立项提交信息草案：`docs(iter117): 迭代计划 117 立项（短剧逐镜视频 Provider 能力与 Once-only Attempt 恢复）`。
- 实施提交信息草案：`feat(drama): add recoverable shot video attempts (iter117)`。
- 用户确认实施后再开始业务代码；完成后必须使用 `iter-finish`，按聚焦检查 → 三视角只读审查 → findings 修复/聚焦回归 → implementation commit → 最终一次 `bash scripts/verify.sh` → README/SOP/handoff/history 收官同步的顺序执行；只 commit，不 push。
