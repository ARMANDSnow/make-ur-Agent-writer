# Iteration 120 - 短剧 Voice Profile 与逐句音频计划

## Context

iter119 已完成 D4 artifact-aware production compose gate，canonical 基线为 2404 tests OK。RenderPlan 已有有序 spoken segments，但 v1 dialogue speaker 明确保持 unresolved；阶段 E 不能从台词文本猜角色。本轮建立显式 Voice Profile、segment assignment 与逐句 AudioManifest 的 E1 纯本地闭环。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_119_drama_shot_video_continuity_compose_gate.md`, `src/drama_schemas.py`, `src/drama_render_plan.py`, `tests/test_drama_render_plan.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_audio.py`, `tests/test_drama_audio.py`, `docs/iterations/README.md`, `docs/iterations/iteration_120_drama_voice_profile_utterance_plan.md`
- `do_not_touch`: `.env`、`key.rtf`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces` 内容与 `小说txt/`；不接真实 TTS、不调用文本/图片模型、不修改 RenderPlan 创作事实、不 push

1. 新增 content-addressed VoiceProfile、显式 VoiceAssignment、UtteranceSpec 与 AudioManifest 严格 schema。
2. 以完整 `segment_id → profile/speaker` 映射解决对白 speaker；旁白只能使用独立 narrator profile，角色不得互相借声。
3. 缺 assignment/profile、speaker 非 frozen cast 或 scope 不匹配时 manifest 明确 blocked；相同输入 byte-stable，单句或 profile 改动只影响对应 utterance 与 manifest。
4. 只使用标准库生成/校验有界 mock WAV fixture，为 E2 测试准备零网络音频，不建立真实 provider seam。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 unresolved dialogue 经显式 assignment 解析、narrator/character scope、完整 segment coverage、单句精确 stale、稳定 identity 与旧 RenderPlan 兼容
- `security_boundary`: 核对 profile/model/instructions/text 的长度与字符边界、NaN/bool/重复/未知 ID、WAV 资源上限、错误脱敏与零网络
- `extra_risk_view`: `audio-schema/privacy`，核对 voice identity 不含 key/endpoint/raw response、缺 voice 必须 blocked、不得猜 speaker 或自动借声

- **A120-01**：VoiceProfile/Assignment/Utterance/AudioManifest 严格 content-addressed，重复构建 byte-stable。
- **A120-02**：每个 spoken segment 必须显式覆盖；dialogue speaker 属于 frozen cast 且 profile scope 匹配，narration 只能使用 narrator profile。
- **A120-03**：缺 profile/assignment、重复/未知 segment、非法 speaker 均 blocked 或 fail closed；不自动替代声音。
- **A120-04**：单句文本或 voice identity 变化只改变对应 utterance identity 和 manifest；有界 mock WAV 可由标准库生成并严格 probe，全程零网络。
- **A120-05**：聚焦检查与三视角审查无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`。

## Implementation Notes

- 新增四类 versioned、content-addressed 持久 schema，并由 `AudioManifest` 保存 RenderPlan fingerprint、frozen cast、完整 source segment 顺序与 resolved/blocked 精确分区。
- 旧 RenderPlan 的 dialogue speaker 继续保持 unresolved；E1 只接受显式 `segment_id → profile/speaker` assignment，不从文本猜角色。旁白和角色 profile 在 builder 与持久 validator 两层隔离。
- utterance identity 只绑定本句文本、voice、instructions、provider identity 与 source segment，不把整份 RenderPlan fingerprint 扩散到每句，因此单 profile/单句变更不会误伤无关 utterance；manifest 负责整集 freshness 绑定。
- mock WAV 仅生成标准库 PCM16 mono fixture；probe 固定 canonical 44-byte RIFF 布局、完整 fmt 数值、文件长度与 30 秒/3 MB 上限，拒绝尾随或 ancillary payload。
- 聚焦检查：`tests.test_drama_audio` 与 `tests.test_drama_render_plan` 共 14 tests OK；`py_compile`、harness（accepted 119 / active 120 / 129 entries）和 `git diff --check` 通过。
- 三视角审查发现并修复 schema version、source-position sequence、episode/frozen cast/scope 交叉绑定、空 frozen cast、WAV 尾随与 fmt 歧义、profile 非字符串异常边界；最终复核无未处理 P0/P1/P2。

## Acceptance Result

- **A120-01 PASS**：VoiceProfile、VoiceAssignment、UtteranceSpec 与 AudioManifest 均为 strict/versioned/content-addressed；重复投影 byte-stable。
- **A120-02 PASS**：manifest 完整保存 source segment 顺序与 frozen cast；dialogue 只由显式 assignment 解析，narration 只接受独立 narrator profile。
- **A120-03 PASS**：缺 assignment/profile 明确 blocked；未知/重复 segment fail closed，持久 validator 重验 episode、sequence、scope、speaker 与 profile 交叉绑定，不猜 speaker、不借声。
- **A120-04 PASS**：profile/单句变更只改变实际依赖它的 utterance；canonical PCM16 mono WAV fixture 具备路径/SHA/数值与资源边界，全程零网络。
- **A120-05 PASS**：14 项聚焦回归、py_compile、harness 与 diff check 通过；correctness、security/boundary、audio-schema/privacy 三路最终无遗留 P0/P1/P2。implementation commit `d52d161b8a2dbe5504dfab4aab53b52d51450d06` 上唯一 canonical run `d9d6118ae586499b9e3fb7c181858faa` 为 2411 tests / 15 steps / 239 秒、exit 0、tree `8040fe26b4f4d0eb605251eae74bc5770433618a`、`tracked_scope_clean=true`，mock preflight 0 WARN/FATAL；总级别 `mock-functional`，local-drama 组件 `local-e2e`，`provider_validated=false`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮经验属于 E1 schema、局部 stale 与 mock WAV 的节点内实现约束，已由 schema、测试和本 iteration 固化；没有需要新增到仓库级长期规则的跨阶段事故模式。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 VoiceProfile、VoiceAssignment、UtteranceSpec、AudioManifest 与 MockWavFixture 严格 schema |
| `src/drama_audio.py` | 新增显式 voice assignment、逐句投影与 canonical mock WAV 生成/probe |
| `tests/test_drama_audio.py` | 覆盖稳定投影、缺 voice、scope/frozen cast、局部 stale、伪造与 WAV 边界 |
| `docs/iterations/README.md` | 追加 iter120 canonical 索引 |

## 不在本轮范围

- TTS provider、paid attempt/receipt、TimelineManifest、字幕、BGM/SFX 与 FFmpeg。
- Web voice editor、自动 voice casting、真实声音克隆和真实模型调用。

## Notes

- clean-room 只借鉴路线图固定外部 commit 的逐句任务与 voice profile 分层，不复制外部代码。
