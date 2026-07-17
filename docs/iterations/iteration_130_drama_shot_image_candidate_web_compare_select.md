# Iteration 130 - 短剧逐镜图片候选 Web 比较与选择

## Context

iter111/113/114 已完成 C1-C3 的 provider-neutral 逐镜图片 request、content-addressed strict PNG 候选、首帧/尾帧/previous-tail lineage、coverage 与 once-only attempt；iter129 完成资产治理 Web，但镜头图片候选仍只能通过领域 API/文件检查。A-J 阶段 C 明确要求候选缩略图、两图比较、guarded selection、stale/failed 安全投影。本轮补齐 C4 本地 Web 闭环，不接真实图片 provider，不生成媒体，并在 implementation commit 内同步上轮因 accepted-commit 边界延后的产品 SOP B3 状态。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_shot_image_candidates.py`, `src/drama_shot_image_candidate_store.py`, `src/drama_shot_image_store.py`, `src/web/routes.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_shot_image_candidate_store.py`, `tests/test_drama_asset_web.py`
- `expected_changes`: `src/drama_shot_image_web.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_shot_image_web.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_130_drama_shot_image_candidate_web_compare_select.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有 workspace、`data/outputs/logs` 私有内容和用户未跟踪体检报告；不开放任意文件/URL，不返回 prompt/provider response/签名 URL，不接真图片/视频/TTS，不 push

1. 新增 strict/bounded 逐镜图片 Web projection：按 stable shot 展示 request freshness、候选 identity、首帧/尾帧/previous-tail selection、coverage、artifact 可用性和脱敏 blocker，不公开 prompt、reference 路径、provider metadata 或本地绝对路径。
2. 新增 drama-only 镜头图片候选页面和 GET API；候选缩略图只通过 exact workspace/episode/shot/candidate 身份的受控同源媒体路由返回，并重验 manifest 与 PNG bytes。
3. 提供两图比较与 guarded 首帧/尾帧选择。mutation 必须携带 manifest revision、current binding/request identity 与显式 intent；服务端重算 target，不允许客户端伪造 stale/coverage/lineage。
4. 页面区分 missing/stale/invalid/blocked/ready、未选候选和已选候选；409 自动刷新，窄屏可用，键盘/屏幕阅读器可辨识比较与选择状态。
5. 聚焦测试、三视角只读审查、唯一 canonical 后，至多一次真文本 UI/协议校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: C1/C2 request/manifest/candidate/selection/coverage 语义与页面一致；首帧/尾帧 guarded selection、lost-response no-op、stale/previous-tail lineage 和 episode 2 身份准确
- `security_boundary`: drama-only、workspace/episode/shot/candidate identity、PNG exact artifact route、请求体/容量、same-origin/intent、路径/symlink/坏 manifest/坏 PNG 与错误脱敏 fail closed
- `extra_risk_view`: Web/media 治理专项，复核浏览器不能枚举任意 artifact、候选比较不泄露 reference/prompt/provider、mutation 不产生 provider/付费调用且不绕过领域 CAS

- **A130-01**：逐镜图片 projection strict、bounded、稳定排序，准确表达 request freshness、candidate/selection/coverage/lineage 与脱敏 blocker。
- **A130-02**：新增 drama-only 页面、GET API 与 exact PNG route；缺失可选状态 graceful degrade，坏 manifest/artifact/identity/symlink fail closed。
- **A130-03**：两图比较与首帧/尾帧 guarded selection 复用 C2 领域 CAS；服务端重算 coverage/stale，409/no-op/lost-response 语义确定。
- **A130-04**：Web mutation 具 JSON/intent/same-origin/strict size，HTML/API/media 不泄露 prompt、reference path、provider response、key、绝对路径或签名 URL；本轮 provider/media 调用为 0。
- **A130-05**：聚焦回归与 correctness/security/Web-media 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内且不升级总 provider 验收。

## Implementation Notes

- 新增 `src/drama_shot_image_web.py` strict allowlist projection：公开 stable shot、request fingerprint、candidate identity/尺寸、current/selectable、首尾/previous-tail binding、coverage、manifest revision 与有界原因；不公开 artifact path、reference、prompt 或 provider metadata。
- 候选媒体路由只接受 URL 中 exact workspace/episode/shot/candidate identity。响应前重读并认证 strict manifest、canonical artifact bytes、PNG 结构/尺寸/size/SHA；浏览器拿到的是剥离 metadata 的 derived preview，而不是任意文件下载。
- PNG sanitizer 只保留 IHDR/PLTE/IDAT/IEND 及严格合法的 `tRNS`。text/EXIF/未知 ancillary 和非法/重复/IDAT 后/type4/6 `tRNS` 被剥离；合法 grayscale/truecolor/indexed transparency 保留，输出再次通过结构与尺寸校验。
- 页面提供两图比较、首帧/尾帧选择和清除尾帧；新候选不自动变更 selection。候选 `current` 与 overview `mutation_allowed` 均由服务端重算：source-plan stale 只读比较，selection/lineage stale 可通过 current direct candidate 修复。
- mutation 同时要求 JSON、`X-Drama-Shot-Image-Intent: mutate-v1`、Origin/Host 与 Fetch Metadata；route/HTTP transport 均为 32 KiB cap，服务端复用 C2 manifest fingerprint、selection revision、current binding 与 workspace lock。
- 聚焦回归覆盖 exact lost-response replay：尾帧切换使下一镜 previous-tail broken 后，相同请求重放 `changed=false`，随后可把下一镜改为 current direct candidate 恢复 fresh。按钮 aria-label 包含 shot/candidate/当前首尾状态；窄屏复用 responsive grid。
- 初审确认并修复 4 类有效问题：lineage stale 被全局 fresh gate 阻断 P1；旧 request/source-stale 候选仍可点 P2；按钮无障碍名称不可区分 P2；PNG ancillary metadata 泄露 P1。复审进一步发现并修复非法 `tRNS` 绕过 P1 与合法透明度误删 P2；三视角最终均 no findings。
- 合理范围变化：`docs/product/short_drama_module.md` 在 implementation commit 内同步 iter129 B3，并新增 C4 与 PNG derived-preview 安全规则；`tests/test_web_server.py` 增加真实 HTTP read-before-allocation cap。

## Acceptance Result

<iter-finish 回填 A130-01..05、测试数、canonical、真文本校准、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: PNG artifact 通过结构/SHA 认证并不意味着适合原样公开；Web preview 必须剥离可能携带 prompt/provider/path/签名 URL 的 ancillary metadata，同时严格保留合法 `tRNS` 透明像素语义。这一规则适用于后续图片候选、工作台和归档预览，已写入 C4 产品 SOP。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_shot_image_web.py` | strict/bounded C2 Web projection、guarded selection 与安全 PNG derived preview |
| `src/web/routes.py`、`src/web/server.py` | drama-only 页面/API/exact PNG route、same-origin intent 与 transport cap |
| `src/web/templates.py`、`src/web/static.py` | 镜头图片导航、两图比较、首尾选择、stale/current 状态与可访问交互 |
| `tests/test_drama_shot_image_web.py`、`tests/test_web_server.py` | projection/CAS/replay/lineage/metadata/tRNS/HTTP cap 回归 |
| `docs/product/short_drama_module.md` | 同步 B3，新增 C4 与安全预览长期规则 |
| `docs/iterations/iteration_130_drama_shot_image_candidate_web_compare_select.md` | 本轮计划与验收记录 |
| `docs/iterations/README.md` | iteration 索引 |

## 不在本轮范围

- 真实图片 provider/network adapter、多参考上传、JPEG/WebP、图片生成/重试、物理删除/GC。
- 逐镜视频 Web、时间线编辑、Web compose、production workbench/archive、真视频/TTS。

## Notes

- README、handoff 与 PROJECT_HISTORY 仅在 iter-finish 且事实变化后同步；implementation commit 先于唯一 canonical。
