# Iteration 121 - 短剧可恢复 TTS Attempt

## Context

iter120 已完成显式 Voice Profile/Assignment、逐句 UtteranceSpec 与完整 AudioManifest，canonical 基线为 2411 tests OK。E2 需要在不接真实 TTS 的前提下建立 provider-neutral capability、逐 utterance 一次性授权、durable attempt/receipt 与 crash recovery，使合成 POST 和音频 GET 的恢复语义严格分离。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_120_drama_voice_profile_utterance_plan.md`, `src/drama_schemas.py`, `src/drama_audio.py`, `src/drama_shot_video_attempts.py`, `src/drama_shot_video_attempt_store.py`, `src/paid_recovery_states.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_tts_attempts.py`, `src/drama_tts_attempt_store.py`, `tests/test_drama_tts_attempts.py`, `tests/test_drama_tts_attempt_store.py`, `docs/iterations/README.md`, `docs/iterations/iteration_121_drama_recoverable_tts_attempt.md`
- `do_not_touch`: `.env`、`key.rtf`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces` 内容与 `小说txt/`；不接真实 TTS、不把文本/图片模型当语音模型、不调用网络、不 push

1. 新增 provider-neutral TTS capability、逐 utterance authorization/spec、attempt record、submission/artifact receipt 与验证后的 WAV artifact schema。
2. `started` 在 submit 前 durable；只有明确 `not_sent` 可释放。response loss / `submission_unknown` 或已持久 provider request ID 时禁止再次合成。
3. 合成 POST 与音频 GET 分账；下载失败只重下，verified artifact 可按 exact utterance/spec 复用，单句 reconfigure 不影响其他 utterance。
4. 使用注入式 fake adapter 与新解释器 `os._exit` 覆盖 submit 前、response loss、receipt 后、下载中和落盘后崩溃窗口；全程零真实 provider。

## Acceptance

### Review Context
- `correctness_behavior`: 核对逐 utterance 独立 attempt/authorization、状态迁移、POST/GET 分离、exact artifact reuse、单句重配隔离与跨进程恢复
- `security_boundary`: 核对 durable ledger/artifact 路径、SHA/WAV 实体验证、provider identity、错误脱敏、special file/oversize/bool/NaN 与零网络默认
- `extra_risk_view`: `paid-recovery/audio`，核对 started-before-submit、response-loss/unknown/已持久 provider ID 永不重合成，下载失败只 GET，五个 os._exit 窗口无重复付费 POST

- **A121-01**：TTS capability、authorization、spec、attempt/receipt/artifact 均 strict/versioned/content-addressed，authorization 精确绑定一个 utterance 且最多一次 synth POST。
- **A121-02**：`not_sent`、`submission_unknown`、`submitted`、artifact received、succeeded/failed 状态穷尽且恢复 fail closed；response loss 或 provider ID durable 后 submit count 不再增加。
- **A121-03**：下载失败/崩溃只能重下；验证后的 exact WAV 可零 POST/GET 复用，单句 voice/text 重配不重跑其他 utterance。
- **A121-04**：注入式 fake adapter 和跨进程 `os._exit` 覆盖五个 crash window；默认测试零网络，不使用 `gpt-5.5-medium` 或 `gpt-image-2` 作为语音模型。
- **A121-05**：聚焦检查与三视角审查无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`。

## Implementation Notes

- 新增 versioned/content-addressed TTS capability、逐 utterance authorization/spec、submission/artifact receipt 与 attempt record；capability 必须与 E1 provider/model 精确一致，明确拒绝本批文本/图片模型。
- runner 在 synthesis POST 前以 dirfd/no-follow、随机 O_EXCL temp、exact previous-token CAS、file fsync、atomic replace 与 parent fsync durable 写入 `started`；任何不确定或 identity drift 都变为 `submission_unknown`，仅经 transport 证明的 `not_sent` 可释放。
- provider request ID durable 后只允许 GET。下载字节先严格 probe、匹配 capability sample rate，再把绑定 spec+submission+SHA 的 artifact receipt durable 写入；随后 create-only 落盘，因此落盘后崩溃可零 GET 收尾，receipt 后未落盘则只重下并 exact compare。
- succeeded artifact 丢失/漂移、orphan WAV、special/symlink/oversize、provider/model/adapter drift 均 fail closed；typed provider terminal reject 进入可达 `provider_failed` 且永不再次 POST。
- 5 个新解释器 `os._exit` 窗口覆盖 submit 前、response 后 receipt 前、receipt 后、download 中与 artifact 落盘后；另有 identity-flip、not-sent、下载失败、sample mismatch、两句局部重配与零调用复用回归。聚焦 41 tests、py_compile、harness 与 diff check 通过。
- correctness、security/boundary、paid-recovery/audio 初审 findings 均已修复；最终三路无遗留 P0/P1/P2。

## Acceptance Result

- **A121-01 PASS**：TTS capability、authorization、spec、submission/artifact receipt 与 attempt record 均 strict/versioned/content-addressed；授权精确绑定一个 E1 utterance、provider/model/capability 与最多一次 POST。
- **A121-02 PASS**：started/not_sent/submission_unknown/submitted/artifact_received/succeeded/provider_failed 均有可达、受守卫的持久迁移；identity drift 与 response loss 永久阻断再次合成，只有可信 not-sent 释放。
- **A121-03 PASS**：durable provider ID 后仅 GET；下载失败只重下，receipt-before-write 允许 exact artifact 零 GET 收尾；两句回归证明单 voice 重配不重跑无关 utterance。
- **A121-04 PASS**：fake adapter 与 5 个新解释器 `os._exit` 窗口通过，POST/GET 计数符合恢复语义；全程 mock/offline，文本与图片模型均被 capability gate 拒绝。
- **A121-05 PASS**：41 项聚焦回归、py_compile、harness 与 diff check 通过；correctness、security/boundary、paid-recovery/audio 三路最终无遗留 P0/P1/P2。implementation commit `aca76870248f91817f761ab1123206d21b4d746f` 上唯一 canonical run `841f8685ed5b43889fcd4b8d3e6e14ee` 为 2452 tests / 15 steps / 238 秒、exit 0、tree `9ecd6f072acce2654b83e86643e7f3cddf205a55`、`tracked_scope_clean=true`，mock preflight 0 WARN/FATAL；总级别 `mock-functional`，local-drama 组件 `local-e2e`，`provider_validated=false`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮是既有 paid once-only、receipt-before-artifact 与 no-follow durable writer 原则在 TTS 的领域化落实，未形成新的仓库级 workflow 规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 TTS capability/authorization/spec/receipt/artifact/attempt 严格 schema |
| `src/drama_tts_attempts.py` | 新增一次性 TTS 纯状态机与 terminal transition |
| `src/drama_tts_attempt_store.py` | 新增 durable writer、provider-neutral adapter 与 POST/GET 分离恢复 runner |
| `tests/test_drama_tts_attempts.py` | 覆盖 capability、授权、输入绑定和纯状态迁移 |
| `tests/test_drama_tts_attempt_store.py`、`tests/_tts_crash_worker.py` | 覆盖 durable recovery、五个 os._exit 窗口与局部复用 |
| `docs/iterations/README.md` | 追加 iter121 canonical 索引 |

## 不在本轮范围

- 真实 TTS adapter/voice cloning、TimelineManifest、SRT、BGM/SFX 与 FFmpeg。
- 通用媒体 DAG、Web voice editor、真实语音质量/SLA 与费用校准。

## Notes

- 沿用现有 paid recovery 的一次性提交语义，但保持 TTS 独立 schema/ledger，不做跨领域大迁移。
