# Iteration 142 - 短剧 Provider 素材契约适配与单次真视频复验

## Context

iter141 已证明 callback-only Quick Tunnel 的公网 exact-byte 素材回读成立，但真实 Episode 1 在首个 provider 素材上传请求/响应阶段 `safe-blocked`，视频 create=0。用户本轮明确授权再次进行真模型测试，并要求视频尽量限制在 1 分钟内；现有真实视频规格固定为 5 秒，满足该时长边界。用户提供的供应商文档显示素材创建与查询对象使用 `data.Id`、`data.Status` 和 `data.base_resp`，当前解析器未兼容 `Id`，且失败诊断不足以区分 HTTP、JSON 与字段契约问题。本轮先完成该契约适配与脱敏诊断，再在已有 Episode 1 workspace、单次 create、人民币 20 元硬预算和异步不重提边界内复验。

## Plan

### Implementation Context
- `must_read`: `src/drama_video.py`, `src/drama_video_client.py`, `src/preflight.py`, `scripts/drama_video_smoke.sh`, `scripts/drama_video_episode1_single_submit.sh`, `tests/test_drama_video.py`, `tests/test_drama_image_video_clients.py`, `tests/support/local_drama_provider.py`
- `expected_changes`: `src/drama_video.py`, `src/drama_video_client.py`, `tests/test_drama_video.py`, `tests/test_drama_image_video_clients.py`, `tests/support/local_drama_provider.py`
- `do_not_touch`: 不读取或修改 `.env`、`小说txt/` 和用户未跟踪体检报告；不把 `key.rtf` 中的配置或任何凭据写入仓库、日志或报告；不扩展真文本、真生图、TTS、逐镜视频或 episode 2+；不自动重提视频

1. 兼容供应商文档中的 `data.Id` / `data.Status` / `data.base_resp`，同时保留既有严格单值、冲突和非法 ID fail-closed 行为。
2. 对素材上传/查询响应增加有界脱敏分类，最多暴露阶段、HTTP 状态、JSON 对象层级和枚举化契约错误；不保存或回显 key、完整响应、URL/query、prompt、素材 token 或签名地址。
3. 更新本地 fake provider 与聚焦测试，使文档契约成为可复现 fixture，并覆盖非零 `base_resp.status_code`、冲突 ID、缺失状态及异常结构。
4. implementation commit 和 canonical mock 验收通过后，启动新的 callback-only Quick Tunnel；先做零提交任务列表鉴权与公网 exact-byte probe，再对 `iter124_real_sop_v2` 执行一次专用真实入口。
5. 视频规格保持 5 秒、9:16、720p、无音频、无水印；最多一次 video create，预算上限 20 元，任务状态不明或超时只查询与核账、不重提。

## Acceptance

### Review Context
- `correctness_behavior`: `data.Id` / `data.Status` / `data.base_resp` 与既有兼容形态解析一致，合法单值成功、冲突或错误状态 fail closed；5 秒固定规格、一次 create、轮询下载和 MP4 校验不回归
- `security_boundary`: 诊断只包含有界枚举与 HTTP/结构分类，不泄露响应正文、凭据、prompt、callback capability、完整 URL/query 或签名结果；错误分支不放宽 SSRF、result host、deadline 与 durable ledger 门禁
- `extra_risk_view`: 真实媒体/Tunnel/计费视角：新 Tunnel 只公开 callback-only 服务；先零提交鉴权与 exact-byte probe；本轮授权只覆盖 `iter124_real_sop_v2` 的一次 5 秒 create 和 20 元估算，unknown/timeout 不重提

- `A142-01`：聚焦测试证明上传响应 `{"success":true,"data":{"Id":"...","base_resp":{"status_code":0}}}` 与查询响应 `data.Id/data.Status` 可通过，错误/冲突/非法/缺失字段 fail closed。
- `A142-02`：客户端与 runner 的错误分类有界脱敏，测试证明输出、异常与 job 投影不包含 key、响应正文、prompt、callback token、完整 URL/query 或签名地址。
- `A142-03`：视频相关聚焦测试、语法、harness 与 diff 检查通过；correctness、security/boundary、真实媒体/Tunnel/计费三个只读审查视角无未处理有效 finding。
- `A142-04`：最终一次 `bash scripts/verify.sh` 通过，工程结论保持 `mock-functional`，不得由 mock 验收升级真实 provider 结论。
- `A142-05`：真实复验前任务列表鉴权与 callback exact-byte probe 通过；专用入口最多一次 create，成功时产出 5 秒±0.25 秒、720×1280 MP4 并校验 fingerprint。若任何 provider 写结果不明、超时或失败，则保存可恢复的脱敏事实，以 `safe-blocked` 收口且绝不自动重提。

## Implementation Notes

- 用户提供的供应商文档把素材创建 ID 写为 `data.Id`、查询状态写为 `data.Status=Active`，而旧解析只接受 `id/ID/AssetID` 与 ready/available 等状态；本轮按文档增加大小写精确兼容，不放宽资源 ID 字符集。
- `base_resp.status_code` 与可选 `success` 在 root/asset/data 全部受支持容器统一校验；任一非零、非法结构、重复 JSON key、跨容器 ID/status 冲突或重复 asset ID 都在 video create 前 fail closed。异常只使用固定有界消息，不拼接 provider body、字段值、URL 或底层异常。
- 真实媒体审查指出素材 upload 本身也是 provider 写动作，旧代码只在 video create 前落 durable marker，无法阻止 upload 响应丢失后的重发。新增独立 asset-upload ledger：逐素材 POST 前写 `submitting`；只有 transport 证明 request not sent 才删除首次 marker 或恢复 prior-ready；已确认 asset ID 可从下一 index 继续；unknown 永久阻止自动 repost；create 的 request-not-sent 可复用 `uploaded_all` ID。
- 原计划外把本轮 profile 在最后一跳绑定到精确 workspace `iter124_real_sop_v2`，shell 与 Python gate 双层拒绝其他 workspace；通用 iter141 profile 保持兼容。
- 初轮审查 findings：correctness 发现查询别名/容器冲突与重复 asset ID；security 发现重复 JSON key、hostile Mapping、`asset.base_resp` 漏检；真实媒体/计费发现 upload 缺 durable ambiguity marker、授权未绑定 workspace。全部修复后，视频/客户端/local-E2E/iter098 相关 **89 tests OK**，语法、harness 与 diff check 通过。

## Acceptance Result

<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 素材 upload 与最终 video create 都属于可能产生 provider 侧状态或费用的写动作，必须分别在请求前建立 durable ambiguity boundary；该规则适用于后续所有真实媒体 adapter。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_142_drama_video_asset_contract_real_retry.md` | 建立本轮计划、验收边界与实施记录 |
| `docs/iterations/README.md` | 追加 iter142 canonical 索引 |
| `src/drama_video.py` | 适配文档化素材 envelope，统一冲突校验，新增可恢复 asset-upload ledger 与 exact workspace profile |
| `src/drama_video_client.py` | 在 JSON transport 边界拒绝任意层重复字段 |
| `scripts/drama_video_episode1_single_submit.sh` | 将本轮单提交入口绑定到精确 workspace/profile |
| `tests/test_drama_video.py` | 覆盖 Id/Status/base_resp、冲突/重复、hostile Mapping、upload unknown 与 workspace 门禁 |
| `tests/test_drama_image_video_clients.py` | 覆盖 root/data/base_resp 重复 JSON key |
| `tests/test_drama_iter098_hardening.py` | 为跨进程复用 asset ID 的 provider fingerprint 固定测试账号 |
| `tests/support/local_drama_provider.py` | 本地 provider 改用文档化 `data.Id/data.Status/base_resp` 契约 |

## 不在本轮范围

- 不公开完整本地 Web 工作台，不建立长期或生产 Tunnel。
- 不读取、写入或回显 `.env` 与真实 key；不把用户桌面配置材料提交入库。
- 不运行真文本、真生图或 TTS，不接入逐镜视频、完整成片或 episode 2+。
- 不把一次 5 秒 Episode 1 结果外推为完整短剧生产链已验证。

## Notes

- “1 分钟内”按成片时长执行，现有固定 5 秒规格不变；异步 provider 完成时间无法保证在 60 秒内，仍使用 600 秒轮询 deadline 防止因过短本地等待造成不明状态。
- `SD_ASSET_PUBLIC_BASE_URL` 的 Quick Tunnel 域名每次启动均变化，只能由用户本地配置维护，不写入仓库。
- 真视频超时或网络状态不确定时只查 task 与账单，不重提。
