# Iteration 132 - 短剧 Web 合成、QA 与交付

## Context

iter119-123 已完成 D4 compose gate、E3 唯一 TimelineManifest 与 F1 本地 FFmpeg 完整成片/QA，iter125 完成 F2 ASS 与 vendor-neutral 可编辑工程，iter131 又补齐 D5 视频候选/连续性 Web。当前 F 的核心领域能力仍缺同源 Web compose job、可恢复状态、QA 投影和 exact download，用户无法从本地工作台把已就绪时间线安全地推进到成片交付。本轮补齐 F3 本地 Web 闭环，不接真图片/视频/TTS provider。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_compositor.py`, `src/drama_media_qa.py`, `src/drama_timeline.py`, `src/drama_edit_export.py`, `src/web/jobs.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_compositor.py`, `tests/test_drama_edit_export.py`, `tests/test_web_server.py`
- `expected_changes`: `src/drama_compose_web.py`, `src/web/jobs.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_compose_web.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_132_drama_web_compose_qa_delivery.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不触发真图片/视频/TTS，不公开 artifact path、FFmpeg stderr、prompt/provider response、签名 URL 或凭据，不 push

1. 新增 drama-only compose 页面与 strict/bounded readiness projection：只从 fresh D4/E3/F1/F2 领域事实重建状态，展示 timeline fingerprint、compose readiness、QA 摘要、ASS/edit-project completion 和安全的缺口分类。
2. 通过现有 Web job 基础设施接入本地 compose；开始前在同一锁域重验 current timeline/selected artifacts，运行中具明确 pending/running/succeeded/failed/cancelled 状态，失败不保留伪 completed。
3. 新增 exact episode/fingerprint 绑定的 MP4、SRT、ASS、edit-project 下载；每次响应前重验 completion/QA/source identity、regular-file/nofollow/size/hash，支持有界 HEAD/Range，仅公开固定文件名与 allowlist headers。
4. 页面支持显式启动、状态刷新、取消与安全下载；409/503/失败状态可恢复，窄屏和键盘可用，不把进程内 future 当持久完成真源。
5. 聚焦测试、Web/runner/media 三视角只读审查、唯一 canonical 后，至多一次真文本 UI/协议校准；图片/视频/TTS 真实调用均为 0。

## Acceptance

### Review Context
- `correctness_behavior`: F1 compose plan/execution/QA 与 F2 ASS/edit-project 同源 timeline 语义不漂移；fresh/stale/missing/failed/cancelled/succeeded、exact replay、episode 2 和 lost-response 状态准确
- `security_boundary`: drama-only、workspace/episode/fingerprint identity、FFmpeg argv/no-shell、job lock/cancel、exact download、HEAD/Range/size/hash/nofollow、错误脱敏与零 provider 调用 fail closed
- `extra_risk_view`: Web/runner/media 专项，复核刷新/重启后的 durable truth、重复 compose/cancel 竞态、partial outputs、下载期间源替换、CPU/磁盘资源上限与公开 job/QA 字段

- **A132-01**：compose readiness projection strict、bounded，准确区分 timeline/D4/F1/F2/QA 状态且只公开 allowlist 字段。
- **A132-02**：Web compose job 在 current source 与 workspace 锁内执行本地 F1/F2，支持进度/取消/恢复；重复请求、stale source、partial output 和失败不得伪装 completed。
- **A132-03**：MP4/SRT/ASS/edit-project exact download 重验 fingerprint/completion/size/hash/regular file，HEAD/Range 与响应头受控，坏 identity/path/symlink/替换 fail closed。
- **A132-04**：页面可完成启动→状态→QA→下载，错误/409/503 可恢复且不泄露路径、stderr、prompt、provider state、key 或签名 URL；真实图片/视频/TTS/provider 调用为 0。
- **A132-05**：聚焦回归与 correctness/security/Web-runner-media 三视角无未处理 P0/P1/P2；implementation commit 上唯一 `bash scripts/verify.sh` 通过并保持 `mock-functional`，真文本若执行只作局部协议校准。

## Implementation Notes

- 新增 `drama_compose_web`，但浏览器不接收 TimelineManifest JSON：E3 production gate 成功后直接在同一 workspace lock 内以 pinned dirfd/no-follow 原子提交 episode-scoped timeline；subtitle revision 只能按 current timeline fingerprint 与 cue ID 做 CAS，修订后的同一 timeline 继续驱动 SRT/ASS/edit project。
- compose overview 从 current D4、持久 E3、F1 QA、F2 completion/source identity 重建 `needs_timeline/ready/partial/stale/invalid/complete`。active/recent job 只按 exact episode 投影，服务重启后的 `lost` job 不覆盖 durable artifact truth。
- compose job 使用现有 Web worker，但执行入口是纯本地 F1/F2：FFmpeg 与 F2 各自在持锁后重新检查 current D4/E3/source，最终 `committed=true` 前再次复核。执行失败为 `failed`；缺 timeline/stale/capacity 为带 `first_blocked` 安全原因的 `blocked`。
- 资源边界：跨 workspace compose 全局单槽；FFmpeg decoder/filter/encoder 单线程，128 MiB 总 source set、64 MiB 单一生成/验证/交付上限与 `-fs`，180 秒硬 timeout；job cancel/deadline 通过 250 ms process checkpoint kill/wait，并清理 staging/temp。HTTP compose overview/download/HEAD/Range 整体单槽。
- exact MP4/SRT/ASS/edit URL 绑定 episode 与完整 timeline fingerprint；current D4/E3、F1 probe/QA、F2 completion/source identity 和返回 bytes 在同一 workspace lock 快照内验证。响应仅给固定文件名与 allowlist headers，不公开本地 path、stderr、provider/prompt/task/signature。
- 聚焦真 FFmpeg 暴露旧 F1 QA 对非 frame-aligned duration 的误判：402 ms timeline 在 25fps CFR 下确定性量化为 440 ms。QA 改为绑定 `ceil(duration × fps)` 的帧网格并以相邻错误帧回归；没有放宽 source duration、codec/profile、timeline metadata 或 shot coverage。
- correctness 审查最初报告 5 项：E3→F3 不可达/字幕 revision 无持久缝、跨集 job 串线、current guard 不在 FFmpeg/F2 锁内、执行失败误标 blocked、episode 2/帧量化覆盖不足。初修复后复核又发现 E3 重放覆盖人工字幕、lost-response CAS 无 exact replay、stage lock 未绑定 stored E3 identity；现以 subtitle-descendant preservation、只存 hash 的 transition receipt 和锁内 current E3 exact equality 修复。量化与跨集 job 已新增回归；episode 2 回归走真实本地 setup/render/assets/C1-C2/D1-D4/E3/F1/F2 链、current timeline 重读、公开 ready→complete overview、四类 exact route/固定文件名和 wrong-episode 404。
- security/boundary 审查最初报告 4 项：500 MB 并发 materialize、下载多锁窗口、FFmpeg 不响应取消、timeline parent TOCTOU。分别以 64 MiB+HTTP 单槽、同锁快照、process checkpoint、复用 F2 pinned-dirfd writer 修复；复核发现 128 MiB 生成与 64 MiB Web 交付上限不一致，现统一为单源 64 MiB 并补 `64 MiB + 1` fail-closed 回归。
- Web/runner/media 审查最初报告 7 项：除上述资源/快照问题外，补齐 global compose slot/线程与 source/output cap、episode job filter、`first_blocked` 投影、compose POST transport+route 32 KiB/JSON/intent guard，以及窄屏下载按钮 flex-wrap。复核发现 timeline revision 会永久累积旧 F1/F2；现于 current timeline 提交锁内按 episode/fingerprint 清理不可达的 allowlist 交付文件，不遍历或删除其它命名空间；E3/字幕 exact replay 也会幂等补偿中断的 prune，已有无效 namespace 一律 fail closed。
- 三个视角终审均为 no findings；主线程确认所有有效 P0/P1/P2 已修复并以聚焦回归覆盖。
- 合理范围变化：为修复真实 QA 与资源/锁边界，除预期 Web adapter 外同步修改 `drama_timeline`、`drama_compositor`、`drama_media_qa`、`drama_edit_export` 及其聚焦测试；不涉及 provider、私有 workspace、TTS 真调用或原文。

## Acceptance Result

- **A132-01 — passed**：Web overview 只从 current D4、持久 E3、F1 QA 与 F2 completion/source identity 重建 `needs_timeline/ready/partial/stale/invalid/complete`；job 只作 exact episode 的运行态投影，公开字段保持 allowlist。
- **A132-02 — passed**：drama-only compose job 仅执行本地 F1/F2；FFmpeg/F2 均在各自 workspace lock 内重读 stored E3 并要求 exact identity，最终 `committed=true` 前再次复核。全局 compose 单槽、64 MiB 单一输出上限、128 MiB 总源集、单线程、timeout/cancel checkpoint、subtitle CAS exact replay 与中断后 retention 补偿均有回归。
- **A132-03 — passed**：MP4/SRT/ASS/edit 下载绑定 workspace、episode 与完整 timeline fingerprint，并在同一 workspace lock 快照内重验 F1 probe/QA、F2 completion/source identity、regular-file/size/hash；HEAD/Range、固定文件名和 allowlist headers 通过。真实本地 episode 2 fixture 走完 D1-D4/E3/F1/F2、公开 ready→complete overview、四类 route 与 wrong-episode 404。
- **A132-04 — passed**：页面支持显式启动、刷新/重启后的 durable truth、取消、QA 摘要与四件套下载；32 KiB JSON/intent/transport guard、409/503 恢复、窄屏按钮和错误脱敏已覆盖。真实图片/视频/TTS 调用均为 0。
- **A132-05 — passed（真文本语义校准未通过）**：implementation commit `5543588ad77b8fac482a7a9767ad29dc443e0c61` 上唯一 canonical `bash scripts/verify.sh` exit 0：**2628 tests OK**、15 steps、369 秒，run `edab55b42f19464cbfe7abe7a5a978eb`，tree `4cabd5068f1ac88374daba9d549bca1cbacb24b7`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN，结论 `mock-functional`；mandatory local-drama step 为 `local-e2e`，不升级 provider 结论。最终聚焦 F3 module 为 17 tests OK；correctness、security/boundary、Web/runner/media 三视角终审均 no findings。
- 真文本按授权共发生 2 次 HTTP attempt：第一次网关 HTTP 403、无 model response；获预授权追加重试后，`gpt-5.5-medium` HTTP 200，21.135 秒，provider usage 1375 tokens。四项检查中 durable truth、锁内 current E3、零 provider 执行为 true，exact episode+fingerprint download 为 false，因此记录为“传输/模型响应成功，语义校准未通过”，不再重试。iter125-132 累计保守计 10/60 请求、8 次 HTTP/model response、6 次协议检查通过，预留约 ¥0.80；图片 0/20、视频/TTS 0。未读取 `.env`，key、完整 prompt 与 response 正文均未输出或落盘。
- **未修风险**：当前是本地个人研究工具；64 MiB 下载在 HTTP 单槽内有界 materialize，不是公网流式多租户方案。真实逐镜媒体、真实 TTS、特定 NLE、多 profile/codec 与主观质量仍未验证；本轮模型语义校准的 1 项 false 不覆盖 canonical、代码审查与 deterministic 回归结论。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: F3 的 E3 持久 hand-off、durable artifact truth、同锁 exact download、FFmpeg/HTTP 资源上限与失败分类是后续 G-I 必须复用的长期产品边界，已在 implementation commit 前晋升到短剧产品 SOP。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_132_drama_web_compose_qa_delivery.md` | 本轮计划与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |
| `src/drama_compose_web.py` | E3 持久 hand-off、compose readiness/job、QA 与 exact delivery |
| `src/drama_timeline.py` | E3 成功结果在同锁内提交 F3 timeline |
| `src/drama_compositor.py` | precompose/current gate、资源上限、单线程与 under-lock verifier |
| `src/drama_media_qa.py` | 25fps 帧网格 QA 与可取消 bounded process |
| `src/drama_edit_export.py` | preexport/current gate 与 under-lock exact verifier |
| `src/web/jobs.py` | drama-compose handler、取消 checkpoint 与安全 blocker/结果投影 |
| `src/web/routes.py` | compose 页面/API、episode 隔离、POST guard 与 exact downloads |
| `src/web/server.py` | compose transport cap 与 HTTP read 单槽 |
| `src/web/templates.py`、`src/web/static.py` | F3 页面、状态、QA、取消和四件套下载 |
| `tests/test_drama_compose_web.py` | E3/F3、竞态、取消、资源、状态与下载回归 |
| `tests/test_drama_compositor.py`、`tests/test_web_server.py` | FFmpeg 上限与 transport cap 回归 |
| `docs/product/short_drama_module.md` | 晋升 F3 长期 SOP 与精确完成边界 |
| `README.md` | 就地同步项目状态与 A-J SOP |
| `docs/AGENT_HANDOFF.md` | 当前快照、证据、缺口、候选与 Latest Transition |
| `docs/PROJECT_HISTORY.md` | iter132 阶段里程碑与长期交付边界 |

## 不在本轮范围

- 真实图片/视频/TTS provider、Web submit/poll/cancel、真实媒体生成或主观质量判断。
- 通用 G 阶段 worker/DAG/pricing、I 阶段统一 production workbench/archive、特定 NLE adapter 和多 profile。

## Notes

- README、handoff 与 PROJECT_HISTORY 仅在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
