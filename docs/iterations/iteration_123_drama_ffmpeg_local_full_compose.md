# Iteration 123 - FFmpeg 本地完整成片竖切

## Context

iter122 已以唯一 TimelineManifest 统一 fresh D4 production MP4、E2 verified WAV、silence、optional audio 与 subtitle cues，canonical 基线为 2483 tests OK。当前仍没有消费该时间线的 production compositor、post-probe QA 或严格 `1080×1920 / 25fps` 完整 MP4。本轮完成 F1，并以 synthetic workspace/fixture 媒体形成首个真实本地 FFmpeg `local-e2e`。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/iterations/iteration_122_drama_timeline_manifest_subtitles.md`, `src/drama_schemas.py`, `src/drama_timeline.py`, `src/drama_shot_video_candidate_store.py`, `src/drama_audio.py`, `scripts/verify.sh`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_compositor.py`, `src/drama_media_qa.py`, `scripts/run_local_drama_compose.py`, `tests/test_drama_compositor.py`, `docs/iterations/README.md`, `docs/iterations/iteration_123_drama_ffmpeg_local_full_compose.md`
- `do_not_touch`: `.env`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces` 与 `小说txt/`；不接真实 TTS/视频、不做 Web compose job/ASS/剪映、不 push

1. 固定 production profile 为 `1080×1920 / 25fps`；纯函数把 strict TimelineManifest 投影为显式 probe/normalize/concat/mix/mux argv/filter graph，全程 argv list、禁止 shell。
2. 执行前 strict read/probe required video/audio，校验 SHA/时长并标准化分辨率、SAR、fps/time base、pix fmt、sample rate/layout；无源音轨视频由 timeline 音频/显式静音补齐。
3. 从同一 timeline 完成视频 concat、对白/旁白 delay/trim/fade/mix、optional BGM/SFX 与 SRT 外挂或烧录；任一 required clip、probe、normalize、concat、mix、mux 失败均不得 completed。
4. post-probe 生成绑定 timeline fingerprint 与 output SHA 的 QA report，验证容器、音视频轨、1080×1920、25fps、总时长与 required-shot coverage；提供 synthetic 本地 runner 产出完整 MP4/SRT/QA。
5. 工程验收完成后再独立判断用户已授权的 synthetic J 局部文本/图片校准；凭据只由不回显进程内 loader 注入，任何 preflight 问题记 `safe-blocked`，不影响本地工程结论。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 TimelineManifest 唯一真源、required-shot 全覆盖、normalize/concat/mix/mux 顺序、无音轨策略、失败不 completed、post-probe 与 output SHA/timeline 精确绑定
- `security_boundary`: 核对 argv-only/no-shell、路径/软链接/SHA、ffprobe JSON 边界、资源/timeout、错误脱敏、输出 create/replace 与凭据/绝对路径不进入公开 plan/QA
- `extra_risk_view`: `FFmpeg/media-runtime`，核对 codec/container、SAR/fps/time-base/pix-fmt/sample-rate/layout、duration tolerance、SRT、音轨存在与真实本地 E2E

- **A123-01**：compose plan 纯函数、versioned/content-addressed，固定 1080×1920/25fps；只生成显式 argv/filter graph，无 shell string/`shell=True`/未验证 action/绝对路径公开投影。
- **A123-02**：执行前 strict probe/normalize required clips 与音频；无源音轨按明确策略补静音，核心 clip/probe/concat/mix/mux 失败 fail closed。
- **A123-03**：post-probe QA 绑定 timeline fingerprint、output SHA 与 required-shot coverage，并验证 MP4 容器、视频+音频轨、1080×1920、25fps 和时长容差。
- **A123-04**：synthetic runner 真实生成可被 ffprobe 解析的完整 MP4、SRT 和 QA；三类产物共享 timeline fingerprint，本地组件结论为 `local-e2e`，不外推 provider 质量。
- **A123-05**：聚焦检查与 correctness/security/FFmpeg 三视角审查无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 canonical `mock-functional`。

## Implementation Notes

- 新增 strict、content-addressed `DramaComposePlan` 与 `DramaComposeQaReport`，production profile 固定为 `1080×1920 / 25fps / H.264 / AAC / yuv420p / 48kHz stereo`；公开 plan/QA 只保留 workspace-relative 路径。
- 新增纯函数 compose plan：required videos 统一 scale/pad/SAR/fps/time-base/pix-fmt 后 concat；对白/旁白及 optional BGM/SFX 统一 resample、trim/fade/delay/pad/mix；没有任何 `shell=True` 或 shell command string。
- executor 在 FFmpeg 消费前先 strict read/hash/probe，再将已验证字节复制到随机私有 staging；执行、SRT 与 QA 均只接受重新构建且与 TimelineManifest 完全一致的 plan，避免源文件替换、软链接与 action 注入。
- ffprobe 使用 selector、timeout、增量 stdout/stderr hard cap 和严格 JSON/numeric validator；post-probe 同时验证容器/轨道、codec、分辨率、SAR、fps/time base、pix fmt、sample rate/layout、视频流自身时长和 required-shot coverage，输出 SHA、SRT SHA 与 timeline fingerprint 被一起绑定。
- synthetic runner 使用两段真实无音轨 fixture MP4 与两段 WAV，产出 `outputs/harness/iter123_compose_workspace/outputs/drama/compose/episode_001/` 下的 MP4/SRT/QA；最终 fingerprint 为 `10cccd4c35ad5df22b025b177c0e54f1c43f0b6777800a097dcbc5317f48c493`，MP4 SHA-256 为 `c90fae105988947b1abc508582be2b069db05c1d508746b2dab2a520be2ae28f`。
- correctness 审查发现“同时伪造 SRT/QA 可绕过重验”和“短视频可被较长音轨掩盖”两项，已分别以 manifest 重导 SRT/精确 QA 重建及 video-stream duration 校验修复；security/boundary 审查发现 TOCTOU、plan action 注入、probe pipe 无界、runner symlink、broken symlink 与 mutable-plan race，均已修复；FFmpeg/media-runtime 审查无未处理 finding，并补充短 BGM loop 回归。三视角最终复审均无未处理 P0/P1/P2。
- 聚焦回归：`py_compile` 通过；`tests.test_drama_compositor + tests.test_drama_timeline` 共 41 tests OK；harness 与 `git diff --check` 通过。Homebrew FFmpeg/ffprobe 版本为 8.1.2。
- 用户授权的 synthetic J 局部校准采用不回显进程内 key loader：`gpt-5.5-medium` 文本 1/5 次、`gpt-image-2` 首次生图 1/4 次（总图片提交 1/20）、真视频 0 次；结果为 `provider-validated-local-calibration`，仅证明本次文本/图片 endpoint 局部可用，`provider_validated_pipeline=false`，不外推 TTS、视频或 F1。

## Acceptance Result

<iter-finish 回填。>

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮新增规则均为 F1 节点实现与验收细节，现有 AGENTS/README 的凭据、真模型、收官审查和 acceptance-level 长期规则已覆盖，无需提前扩写长期权威文档。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 strict compose plan 与媒体 QA schema |
| `src/drama_media_qa.py` | 新增安全 ffprobe 执行、严格媒体解析与 post-compose QA |
| `src/drama_compositor.py` | 新增 plan 构建、staging、FFmpeg 执行、SRT/QA 落盘与重验 |
| `scripts/run_local_drama_compose.py` | 新增 synthetic workspace 本地完整成片 runner |
| `tests/test_drama_compositor.py` | 新增 F1 plan、边界、攻击面、真实 FFmpeg 与完整产物测试 |
| `docs/iterations/README.md`、本文件 | 登记 iter123 并记录实现/验收证据 |

## 不在本轮范围

- Web compose job、ASS、剪映/EDL、通用媒体 DAG、多 profile/横屏/30fps、真实 TTS/视频与自动视频重试。
- 把 fixture/local FFmpeg 或局部文本/图片校准标为完整 pipeline `provider-validated`。

## Notes

- FFmpeg 缺失或安装失败阻塞 F1 完成态；不得用复制第一段、占位视频或降规格伪报完整成片。
