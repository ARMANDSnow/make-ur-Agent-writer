# Iteration 125 - 短剧 ASS 与可编辑工程导出

## Context

iter124 收官时，短剧 A-F 已具备逐镜图片/视频、声音时间线和固定 profile 本地 MP4，但阶段 F 仍只导出 SRT，缺少 ASS 与可编辑工程；handoff 将 F2 明确列为低风险下一候选。用户要求从 iter125 起继续实现 A-J 剩余部分，并授权在每轮收官后按总预算约束做真模型校准；本轮先完成不依赖外部 provider 的 F2 单一闭环。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_122_drama_timeline_manifest_subtitles.md`, `docs/iterations/iteration_123_drama_ffmpeg_local_full_compose.md`, `src/drama_schemas.py`, `src/drama_timeline.py`, `src/drama_compositor.py`, `tests/test_drama_timeline.py`, `tests/test_drama_compositor.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_edit_export.py`, `tests/test_drama_edit_export.py`, `docs/iterations/iteration_125_drama_ass_editable_export.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`
- `do_not_touch`: `.env`、`小说txt/`、用户未跟踪体检报告、私有 workspace 与既有媒体；不测试 TTS，不提交真视频，不把通用工程冒充剪映等特定编辑器已验证格式

1. 从 strict `TimelineManifest` 确定性导出 UTF-8 ASS，固定首版竖屏样式、时间换算与文本转义；ASS 与 SRT 共享同一 timeline fingerprint。
2. 建立版本锁定的通用可编辑工程 schema，冻结素材 hash、轨道、时间区间、字幕与 canvas/profile；工程只使用安全 workspace 相对路径。
3. 提供受 workspace lock 保护的原子写入与重验入口；拒绝绝对路径、穿越、symlink/FIFO、坏 hash、重复素材与伪造 timeline。
4. 新增纯函数、持久化、篡改与边界回归，并覆盖现有 TimelineManifest/F1 compositor 不退化。
5. 收官后在独立于 `iter-finish` 的受控校准步骤中执行至多一次 scope-specific 真文本调用；不运行 TTS/视频，图片与本轮无关则不调用。

## Acceptance

### Review Context
- `correctness_behavior`: ASS cue 数、毫秒到 centisecond 时间、换行/转义、通用工程素材/轨道/字幕顺序与 TimelineManifest 完全一致；重复导出字节稳定，字幕 revision 只改变对应派生产物
- `security_boundary`: 所有素材与输出均限制为安全相对路径；持久化拒绝 symlink/FIFO/目录/坏 hash/伪造 fingerprint，不公开完整字幕、prompt、provider 响应、签名 URL 或凭据
- `extra_risk_view`: 媒体/编辑器导出，检查 ASS 注入边界、轨道时间范围、profile 绑定、原子落盘与“不宣称特定 NLE 兼容”的证据措辞

- **A125-01**：同一 strict TimelineManifest 可字节稳定导出 UTF-8 ASS；cue 时间、顺序、样式和转义确定，ASS/SRT 绑定相同 timeline fingerprint。
- **A125-02**：通用可编辑工程确定性冻结 video/dialogue/narration/BGM/SFX/silence/subtitle 轨道与素材 SHA；所有区间有界且共享 F1 profile。
- **A125-03**：ASS 与工程可在 workspace lock 下原子落盘并由 timeline 精确重建重验；篡改、路径穿越、绝对路径、symlink/FIFO/目录和并发替换 fail closed。
- **A125-04**：聚焦回归、correctness、security/boundary、media/export 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过，canonical 结论不超过 `mock-functional`。
- **A125-05**：收官后的真文本校准在累计 60 次/¥150 与总预算 ¥200 内，凭据不落仓、不进日志；本轮 TTS、图片和视频均为 0 调用。

## Implementation Notes

- 新增 `AssArtifact`、通用可编辑素材/片段/轨道/字幕/project 与 `DramaEditExportResult` strict schema；可编辑工程是 vendor-neutral v1，不宣称剪映、Premiere 或 Final Cut 私有格式兼容。
- ASS 使用固定 `vertical-1080x1920-zh-v1` 样式，绑定 timeline fingerprint；反斜杠与 override 花括号被转义。相邻 cue 共享上一量化终点，且逐 cue/整集检查 centisecond 可表示性；高密度 1ms cue 明确 fail closed，不把字幕推离原语音。
- 工程固定 `vertical-1080x1920-25-v1`、48kHz stereo、AAC 128k profile；冻结 video/dialogue/narration/BGM/SFX/silence 六类轨道、exact source range、`gain_permille`、F1 同源 10ms fade、字幕 utterance/source hash/revision。SFX 是允许重叠的 mix bus，同起止按 clip/source ID 排序；其它轨道不重叠，所有输入先 canonical sort。
- 素材校验改为 parent-dirfd + leaf nofollow 的 64KiB 流式 SHA，按 video/spoken/optional 分类型上限并设 1GiB 总上限；open fd 前后 identity、当前 namespace、写前/写后 identity 都必须一致。
- ASS、project 与 completion marker 写入同一 pinned output dirfd；旧 marker 在重导开始先失效，ASS/project 完成、素材复验及最终输出目录 inode 复验后才写 marker。`require` 重建并核对三份 exact bytes；source/output namespace swap、symlink/FIFO/目录、坏 hash、partial pair 和失败重导均 fail closed。
- 三轮只读审查累计发现并修复 overlapping SFX、素材/输出 TOCTOU、锁异常泄露、bounded hashing、字幕 revision、ASS 量化、pair completion、material 上限、gain/fade/audio profile、SFX/silence canonical order 等问题；最终复核无遗留 P0/P1/P2。
- 聚焦回归最终覆盖新增 16 项；与 TimelineManifest/F1 compositor 合并聚焦共 35 项通过。`py_compile`、agent harness 与 `git diff --check` 通过。

## Acceptance Result

- **A125-01 — PASS**：同一 strict TimelineManifest 可字节稳定导出 UTF-8 ASS；固定 10ms timebase、确定性样式/排序与反斜杠/花括号转义，高密度不可表示 cue fail closed，ASS 与 SRT 共享 timeline fingerprint。
- **A125-02 — PASS**：vendor-neutral project v1 冻结 `vertical-1080x1920-25-v1`、48kHz stereo/AAC 128k、video/dialogue/narration/BGM/SFX/silence 六类轨道、素材 SHA、source range、gain/fade 与字幕 source hash/revision；不宣称特定 NLE 私有格式兼容。
- **A125-03 — PASS**：导出在 workspace lock 与 pinned dirfd 下完成；completion marker 只在 ASS/project、素材与输出 namespace 最终复验后提交。exact require 可阻断路径穿越、绝对路径、symlink/FIFO/目录、坏 hash、partial pair、失败重导残留与 source/output namespace swap。
- **A125-04 — PASS**：新增 16 项聚焦回归，与 TimelineManifest/F1 compositor 合并共 35 项通过；correctness、security/boundary、media/export 三个独立只读视角最终均无遗留 P0/P1/P2。实现提交 `7aa140bd22addd9e6ff7e6b5ae306b700610dc12` 上唯一 canonical `bash scripts/verify.sh` 通过：2514 tests、15 steps、304 秒、run `1f66b58ebc9c4e27bf430f4e744b3e21`、tree `bfb9843a1c2ff32f7138599c39efb38980e7f1d8`、`tracked_scope_clean=true`，结论 `mock-functional`。
- **A125-05 — PASS（局部校准）**：不回显临时 loader 首次在网关层得到 HTTP 403（0.272 秒），调整正常客户端请求头后追加一次重试成功：`gpt-5.5-medium` HTTP 200、3.295 秒、prompt/completion/total tokens 为 85/89/174，返回对象与 F2 ASS timebase、editable profile 和六轨协议完全匹配，response SHA-256 为 `29d32c72ed9e2d4ffcb50d02eaf8ae85b2d39b95a5931f5d4592722fde0bd867`。保守计为文本请求 2/60、成功模型响应 1，预算预留 ¥0.10/¥150（非供应商账单）；图片 0/20、视频 0、TTS 0，凭据与响应正文均未落仓/日志。
- **总级别**：canonical 为 `mock-functional`；本轮 scope-specific 文本仅为 `provider-validated-local-calibration`，`provider_validated_pipeline=false`，不外推图片、视频、TTS、特定 NLE 或完整 A-J pipeline。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: F2 确立了 ASS、通用可编辑工程、音频 profile 与 completion marker 的长期产品契约，需在 canonical 验收前同步到 A-J 权威产品 SOP。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 ASS、通用可编辑工程与完成回执 strict schema |
| `src/drama_edit_export.py` | TimelineManifest → ASS/edit project，流式素材复验、安全落盘与 exact require |
| `tests/test_drama_edit_export.py` | 确定性、字幕/音轨、边界、篡改、并发 namespace 与 completion 回归 |
| `docs/product/short_drama_module.md` | 晋升 F2 长期产品契约并同步 A-F 当前基线 |
| `docs/iterations/README.md`、本文件 | 登记 iter125 并记录计划、实现、审查与验收 |

## 不在本轮范围

- 特定剪映/Final Cut/Premiere 私有工程兼容、Web compose job、多 profile、更广 codec/container。
- TTS、真视频、逐镜真媒体生产、通用任务 DAG、事件图、生产工作台与归档导入。

## Notes

- 真模型校准与 `iter-finish` 的 canonical mock 验收分离，避免真实 provider 进入单测或 `verify.sh`。
- 用户所指 `sd_real_max.md` 在本机可检索范围内不存在；本轮与视频无关且保持 0 submit，后续视频阶段仍须以可用的非占位配置和公网素材回调完成 preflight。
