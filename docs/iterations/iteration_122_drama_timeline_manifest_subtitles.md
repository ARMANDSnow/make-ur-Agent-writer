# Iteration 122 - 短剧唯一 TimelineManifest 与字幕

## Context

iter121 已完成逐 utterance once-only TTS attempt 与 verified WAV artifact，canonical 基线为 2452 tests OK。D4 production video selections 与 E2 audio artifacts 仍缺少共同的唯一时间轴；F1 不能分别推导视频、混音和字幕，否则会产生漂移。本轮建立严格 versioned TimelineManifest 与同源 SRT。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_119_drama_shot_video_continuity_compose_gate.md`, `docs/iterations/iteration_121_drama_recoverable_tts_attempt.md`, `src/drama_schemas.py`, `src/drama_shot_video_continuity.py`, `src/drama_audio.py`, `src/drama_tts_attempt_store.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_timeline.py`, `tests/test_drama_timeline.py`, `docs/iterations/README.md`, `docs/iterations/iteration_122_drama_timeline_manifest_subtitles.md`
- `do_not_touch`: `.env`、`key.rtf`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces` 内容与 `小说txt/`；不调用 provider、不执行 FFmpeg、不改创作台词、不 push

1. 新增 versioned TimelineManifest，统一承载有序 video/dialogue/narration/silence、可选 BGM/SFX policy 与 subtitle cues。
2. builder 只消费 D4 ready 的 production selections、E1 ready AudioManifest 与 E2 succeeded exact WAV artifact；按镜头和 spoken source order 确定布局。
3. 台词音频总长超过所属镜头、跨镜越界、负数/NaN/Inf/bool、重叠/断序、空/超长字幕全部 fail closed；optional BGM 缺失产生 warning。
4. SRT 从同一 manifest 确定导出；人工字幕 revision 只生成新的 subtitle cue/timeline fingerprint，不反写 E1 文本。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 D4/E1/E2 freshness 与 episode/shot/utterance exact binding、镜头连续布局、音频逐句顺序、超镜头 blocked、silence 填充、SRT/revision 同源 fingerprint
- `security_boundary`: 核对路径/SHA 只来自既有严格 artifact、所有时间数值 strict bounded、列表/文本/Unicode/control 边界、错误脱敏与零网络
- `extra_risk_view`: `timeline/numeric-validation`，核对 bounds/non-overlap/连续顺序、负数/NaN/Inf/bool、跨镜越界、字幕空值/超长、optional BGM warning 和 forged rehash

- **A122-01**：TimelineManifest strict/versioned/content-addressed，并与 D4 selected binding、E1 AudioManifest、E2 exact artifacts 绑定；video clips 连续覆盖 required shots。
- **A122-02**：dialogue/narration 在各自镜头内按 source order 非重叠排列，剩余时长显式 silence；任何超镜头或 stale/missing artifact 明确 blocked/fail closed。
- **A122-03**：毫秒数值、clip/cue bounds、跨镜、重叠、断序、bool/NaN/Inf 与空/超长字幕均 fail closed；optional BGM 缺失产生 warning。
- **A122-04**：SRT 与 timeline 使用同一 fingerprint；人工字幕 revision 确定性更新 cue/SRT/timeline，不修改 source utterance text。
- **A122-05**：聚焦检查与三视角审查无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`。

## Implementation Notes

- 新增 `TimelineManifest` 及 video/audio/silence/optional-audio/subtitle/SRT 严格 schema；所有时间使用 strict integer ms，video 必须连续覆盖，dialogue/narration 与 silence 必须逐镜精确 partition。
- production builder 在单一 workspace write lock 内完成 D4 selected MP4 inspection、plan/report 重建、E2 WAV strict read/probe 与 timeline projection；typed model 输入一律 dump 后重校验，artifact path 精确绑定 episode/shot/candidate/utterance。
- optional BGM/SFX 绑定 SHA/size/duration/sample-rate；builder 使用 canonical order，BGM 单轨不重叠，disabled policy 禁止 BGM，non-loop 排期不得长于源音频。缺少 optional BGM 只产生 warning。
- SRT 只由同一 TimelineManifest 导出并可通过 exact regeneration 授权；字幕 revision 改 cue 与 timeline fingerprint，不改 source text hash。字幕拒绝 CR/LF/`-->`，避免结构注入。
- 聚焦回归覆盖 missing/stale source、超镜头、strict numeric/跨镜/partition、artifact identity、WAV 篡改、optional policy 与 SRT/typed-instance forgery；timeline 模块 31 tests 通过，相关 D4/E1/E2/E3 组合 90 tests 通过，py_compile、harness 与 diff check 通过。
- correctness、security/boundary、timeline/numeric-validation 三路只读审查共报告 10 项去重前 findings；修复 D4/E3 锁间隙、optional 元数据、路径身份、SRT 结构、列表边界与 typed-model mutation 后三路最终均 `no findings`。

## Acceptance Result

- **A122-01 PASS**：TimelineManifest 及各 clip/cue/SRT schema 均 strict/versioned/content-addressed；D4 report/selected bindings、E1 manifest 与 E2 artifact 身份被精确绑定，required video 连续覆盖整集。
- **A122-02 PASS**：dialogue/narration 按 AudioManifest source order 在所属镜头内布局，尾部显式 silence；missing/stale/非 succeeded artifact 与音频超镜头全部 fail closed，不截断。
- **A122-03 PASS**：strict integer ms、bounds、chronological order、逐镜 partition、跨镜/跨集 artifact path、optional BGM order/non-overlap/policy/source duration 与 subtitle text 均有正反向回归；缺 BGM 仅产生 `optional_bgm_missing` warning。
- **A122-04 PASS**：字幕 revision 只更新 cue/timeline fingerprint 并保留 source text hash；SRT 由 manifest 确定导出，只有 exact regeneration 可授权，typed model 原地篡改被重新校验拒绝。
- **A122-05 PASS**：timeline 模块 31 tests、相关 D4/E1/E2/E3 组合 90 tests、py_compile、harness 与 diff check 通过；correctness、security/boundary、timeline/numeric-validation 三路最终无遗留 P0/P1/P2。implementation commit `f5e94516f037317cd885ed7c9da37f75f53a58e9` 上唯一 canonical run `5a7e62f0c8d744539df8e46e2b7ac6cb` 为 2483 tests / 15 steps / 277 秒、exit 0、tree `2c81e6dca8d326486e6614d55d367e2f48e46a6a`、`tracked_scope_clean=true`，mock preflight 0 WARN/FATAL；总级别 `mock-functional`，local-drama 组件 `local-e2e`，`provider_validated=false`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮结论是 E3 节点实现与测试细节；长期边界已由 AGENTS 与短剧 SOP 覆盖，待收官仅同步阶段状态，不新增跨阶段规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 Timeline/SRT strict schemas、内容寻址与跨轨一致性校验。 |
| `src/drama_timeline.py` | 新增同锁 production projection、字幕 revision、SRT 导出与精确授权。 |
| `tests/test_drama_timeline.py` | 新增 E3 正反向、数值、freshness、optional audio 与 forgery 回归。 |
| `docs/iterations/README.md` | 追加 iter122 索引。 |
| `docs/iterations/iteration_122_drama_timeline_manifest_subtitles.md` | 记录计划、验收、实现与审查证据。 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 收官同步 A-J SOP、当前快照与阶段历史。 |

## 不在本轮范围

- FFmpeg compose/probe/QA、ASS/剪映、真实 BGM/SFX provider 与 Web timeline editor。
- 静默截断、自动加速语音、修改创作台词或把 optional 音乐冒充 required 完成。

## Notes

- 本轮时间单位统一为严格整数毫秒；F1 只能消费本 manifest，不另建平行时间轴。
