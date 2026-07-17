# Iteration 131 - 短剧逐镜视频候选 Web 与连续性门禁

## Context

iter115-119 已完成 D1-D4 的 provider-neutral 逐镜视频 plan、content-addressed strict MP4 候选、显式选择、once-only submit/poll/download 恢复、整集 coverage 与 deterministic continuity/compose gate；iter130 已证明逐镜图片候选可用 strict/bounded Web 投影和 guarded mutation 安全落地。A-J 阶段 D 仍缺候选播放/选择、attempt 状态、continuity warning 与 production compose readiness 的同源 Web 界面。本轮补齐 D5 本地 Web 闭环，不接真实视频 provider、不提交或生成媒体。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_shot_video.py`, `src/drama_shot_video_candidates.py`, `src/drama_shot_video_candidate_store.py`, `src/drama_shot_video_attempts.py`, `src/drama_shot_video_attempt_store.py`, `src/drama_shot_video_continuity.py`, `src/drama_shot_image_web.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_shot_video_candidate_store.py`, `tests/test_drama_shot_video_continuity.py`, `tests/test_drama_shot_image_web.py`
- `expected_changes`: `src/drama_shot_video_web.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_shot_video_web.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_131_drama_shot_video_candidate_web_continuity.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不开放任意文件/URL，不返回 prompt/provider response/task id/签名 URL，不接真视频/图片/TTS，不 push

1. 新增 strict/bounded 逐镜视频 Web projection：按 stable shot 展示 plan/candidate freshness、selected binding、attempt 的安全状态类、coverage、continuity warning 与 production compose readiness，不公开 prompt、provider job/result、artifact path 或内部错误正文。
2. 新增 drama-only 视频候选页面和 GET API；候选播放只通过 exact workspace/episode/shot/candidate 身份的同源媒体路由，并重验 strict manifest、canonical MP4 artifact、size/SHA/container 结构。
3. 提供 guarded 候选选择，服务端重算 source plan、manifest revision、current selection 与 target token；支持 exact lost-response replay，stale/retired/placeholder 候选不可伪装为 production-ready。
4. 页面明确区分 missing/pending/submitted/unknown/failed/succeeded、ready/placeholder/stale/invalid 与 continuity hard blockers/soft warnings；409 自动刷新，窄屏和键盘操作可用。
5. 聚焦测试、三视角只读审查、唯一 canonical 后，至多一次真文本 UI/协议校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: D1-D4 plan/candidate/selection/attempt/coverage/continuity 语义与页面一致；guarded selection、lost-response no-op、placeholder/degraded preview、stale/retired、episode 2 身份和 compose readiness 准确
- `security_boundary`: drama-only、workspace/episode/shot/candidate identity、exact MP4 artifact route、Range/HEAD/请求体容量、same-origin/intent、路径/symlink/坏 manifest/坏 MP4 与错误脱敏 fail closed
- `extra_risk_view`: Web/media/paid-state 专项，复核浏览器不能枚举任意 artifact 或泄露 provider task/result/prompt/reference，GET/selection 不触发 submit/poll/download/付费调用，公开 attempt 状态不制造恢复承诺

- **A131-01**：逐镜视频 projection strict、bounded、稳定排序，准确表达 plan/candidate/selection/attempt/coverage/continuity 与 compose readiness 的安全状态。
- **A131-02**：新增 drama-only 页面、GET API 与 exact MP4 route；缺失可选状态 graceful degrade，坏 manifest/artifact/identity/symlink fail closed，媒体响应具受控 HEAD/Range 行为。
- **A131-03**：候选选择复用 D2 领域 CAS；服务端重算 freshness/coverage/continuity，409/no-op/lost-response、placeholder/retired/stale 语义确定。
- **A131-04**：Web mutation 具 JSON/intent/same-origin/strict size，HTML/API/media 不泄露 prompt、reference path、provider task/result、key、绝对路径或签名 URL；本轮 provider/media 调用为 0。
- **A131-05**：聚焦回归与 correctness/security/Web-media-paid 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内且不升级总 provider 验收。

## Implementation Notes

- 新增 drama-only `/w/<name>/shot-videos`、strict/bounded overview API、exact MP4 HEAD/GET/single-Range 路由和 guarded selection。projection 只公开 stable identity、selection、受控 attempt 状态类、coverage、continuity 与 compose readiness；GET/播放/选择均不进入 submit/poll/download/cancel/provider 路径。
- 原始 provider MP4 永不直接返回浏览器。服务端按 exact manifest identity 重验 source，再派生静音、最长 30 秒、360 宽/12fps/512kbps 的 H.264 preview；清除 audio/subtitle/data/chapter/metadata，限制 4 MiB 输出并复核 MP4 box allowlist。浏览器 `preload=none` 且无初始 `src`，用户点击后才加载，并保留显式重试按钮。
- 为关闭媒体 DoS 与 metadata finding，合理扩展 `src/drama_shot_video_candidate_store.py`：默认领域行为不变，新增可选 sample/单视频轨 probe 和 bounded selected-artifact inspection/mutation 参数。Web 限制 source 32 MiB、单合法视频轨、长边 1920/短边 1080、36,000 samples、整页 64 个 preview identity、每镜 8 个候选、preview/overview/mutation 并发各 2、FFmpeg decoder/filter/encoder 单线程、same-SHA in-flight dedupe 与 4 项 LRU。
- 已选 source 超过 Web 32 MiB 时不读取、不误判领域 artifact invalid，也不隐藏 selection；投影为 `web_unverified`，允许 exact CAS clear，同时注入 continuity hard blocker，不能显示 compose ready。Web mutation 的 select/persist/precommit 均受 32 MiB/defer 参数和全局并发门禁约束；新选择若超过 32 MiB 直接拒绝。
- correctness 初审发现 attempt summary 与 per-shot latest 来自两个不一致快照、source-plan stale candidate 被误标 current、HEAD 416 长度和 CSS token 问题；均以 fingerprint 绑定、fresh D1 spec 对比、HEAD entity length 和既有 CSS token 修复。
- security/Web-media-paid 初审及复审发现 raw MP4 metadata、未受控预载/转码、manifest inspection 前读取、FFmpeg 像素/sample/thread 资源、multi-video-track 绕过、oversize selected 隐藏、overview/mutation busy 500 与 domain mutation 100 MiB 绕过；逐项修复并加入 adversarial/bounded 回归。最终 correctness、security/boundary、Web/media/paid 三视角均无未处理 P0/P1/P2。
- 聚焦检查：受影响 Python `py_compile`、dashboard JavaScript `node --check`、68 项相关 unittest、agent harness 与 `git diff --check` 通过；未在审查前运行全量 discovery 或 canonical。

## Acceptance Result

- **A131-01 — passed**：D1-D4 stable shot/request/candidate/selection、latest attempt 安全状态类、coverage、continuity 与 compose readiness 由同一 bounded projection 重建；source-plan stale compare-only，placeholder 和 `web_unverified` 均不能伪装 production ready。
- **A131-02 — passed**：drama-only 页面/API 与 exact MP4 HEAD/GET/single-Range 路由通过。原始 MP4 不公开；派生 preview 经 decode/re-encode、metadata/轨道清除、4 MiB/单轨/尺寸/sample/线程/并发门禁和结构复核。缺失、坏 identity/manifest/artifact、Range 与 busy 均 fail closed。
- **A131-03 — passed**：selection 复用 D2 manifest fingerprint、selection revision/current selection CAS；current candidate 选择、clear、exact lost-response replay、stale/retired/oversize selected clear 语义确定，mutation 从 bounded overview 到 domain precommit 均受 Web 资源门禁约束。
- **A131-04 — passed**：same-origin/intent/32 KiB body、workspace/episode/shot/candidate exact identity、公开字段 allowlist 与派生媒体边界通过；测试钉住 GET/media/select 不进入 submit/poll/download/provider。图片、视频、TTS 真实调用均为 0。
- **A131-05 — passed（真文本校准未通过语义检查）**：implementation commit `53c13139ac3baf0977d0a85d6c584b0df1129cc2` 上唯一 canonical `bash scripts/verify.sh` exit 0：**2610 tests OK**、15 steps、333 秒，run `9356464938a748e88918d8ee48f74178`，tree `9c856d38c35ac3125b11c1337ab57a72150cb301`，`tracked_scope_clean=true`，mock preflight 0 FATAL / 0 WARN，结论 `mock-functional`；mandatory local-drama step 为 `local-e2e`，不升级 provider 结论。correctness、security/boundary、Web/media/paid 三视角最终均无遗留 P0/P1/P2。
- 真文本按授权仅调用 1 次：`gpt-5.5-medium`，HTTP 200，11.370 秒，provider usage 552 tokens；四项协议布尔检查均为 false，因此记录为“传输/模型响应成功，语义校准未通过”，不计为本轮协议校准成功，也不重试。iter125-131 累计保守计 8/60 请求、7 次 HTTP/model response、6 次协议检查通过，预留约 ¥0.70；图片 0/20、视频/TTS 0。未读取 `.env`，key、完整 prompt 与 response 正文均未输出或落盘。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: 原始 provider MP4 不可直接公开、派生 preview 必须重编码去 metadata，并在 manifest read 前实施字节/轨道/尺寸/sample/线程/并发门禁；oversize selected 要保留可清除但不得宣称 compose ready。这些是后续视频 Web/compose 共用的长期安全与产品语义。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_131_drama_shot_video_candidate_web_continuity.md` | 本轮计划与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |
| `docs/product/short_drama_module.md` | 晋升 D5 Web projection、派生媒体与资源边界 |
| `src/drama_shot_video_candidate_store.py` | 可选 bounded inspection/mutation 与 single-video-track/sample probe，默认领域契约不变 |
| `src/drama_shot_video_web.py` | D2-D4 安全 projection、派生 preview、attempt/coverage/continuity 与 guarded selection |
| `src/web/routes.py` | D5 GET/media/select API、same-origin/intent/Range/503 映射 |
| `src/web/server.py` | HEAD 与媒体安全响应头透传 |
| `src/web/templates.py` | drama-only 镜头视频候选页面 |
| `src/web/static.py` | 候选播放/选择、状态与连续性 UI |
| `tests/test_drama_shot_video_web.py` | projection、媒体、CAS、付费零调用和 adversarial 资源边界回归 |
| `tests/test_web_server.py` | HEAD/Range 与请求体容量回归 |

## 不在本轮范围

- 真实视频 provider/network adapter、submit/poll/cancel/download 动作、真实媒体生成与重试。
- Web compose/FFmpeg job、时间线编辑、production workbench/archive、真图片/TTS。

## Notes

- README、handoff 与 PROJECT_HISTORY 仅在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
