# Iteration 141 - 短剧 Callback-only 公网素材回调与 Episode 1 真视频验证

## Context

iter140 收官时，短剧真视频仍缺供应商可访问的公网素材回调，canonical 基线为 2765 tests OK、`mock-functional`，`provider_validated=false`。现有完整 Web 工作台已经提供 `/media/drama-assets/<token>`，但不能将整套本地工作台直接暴露到公网。本轮按用户批准的小范围方案新增独立 callback-only loopback 服务，经 Cloudflare Quick Tunnel 只公开短时随机 token 素材；实现验收后，再在精确 workspace、单次提交、人民币 20 元硬预算与 600 秒超时边界内验证旧 episode 1 参考图视频链。

## Plan

### Implementation Context
- `must_read`: `src/drama_video.py`, `src/drama_video_smoke.py`, `src/preflight.py`, `src/web/routes.py`, `src/web/server.py`, `scripts/drama_video_smoke.sh`, `tests/test_drama_video.py`
- `expected_changes`: `src/drama_asset_callback_server.py`, `scripts/drama_asset_callback.sh`, `tests/test_drama_asset_callback_server.py`
- `do_not_touch`: 不读取或修改 `.env`、`data/`、`outputs/`、`logs/`、`workspaces/`、`小说txt/`；不改变完整 Web 工作台路由；不扩展 JPEG/WebP、逐镜视频、TTS 或完整成片；不自动重提真视频；不纳入现有未跟踪体检报告

1. 新增独立 callback server，只绑定 `127.0.0.1`，只复用 `drama_video.read_public_asset()`；精确 GET token 路由成功返回冻结 PNG，其余路径、编码、query、尾斜杠与所有其他方法统一返回空正文 404。
2. 服务禁用 access log，不回显 token/path/method；固定 `no-store`、`nosniff`、`Content-Length` 和连接关闭，连接超时 5 秒、最多 8 个并发请求。
3. 新增安全启动脚本，禁止 dotenv，强制文本 mock 并清除 provider key 环境继承；不在代码内创建、托管或解析 Quick Tunnel。
4. 保持 `SD_ASSET_PUBLIC_BASE_URL=https://<random>.trycloudflare.com` 与既有 `/media/drama-assets/<token>` 拼接契约不变；5 秒、9:16、720p、无音频、无水印继续使用既有常量。
5. implementation commit 和 canonical mock 验收通过后，经授权安装 `cloudflared`，以前台 Quick Tunnel 指向 callback-only 端口；用户自行更新 `.env`。先做零提交任务列表探针和 callback 预检，再在用户提供精确 workspace 名称后执行最多一次真视频 create。

## Acceptance

### Review Context
- `correctness_behavior`: 独立服务精确复用现有 capability store，合法 token 返回 exact PNG，所有拒绝分支一致 404；视频接口、固定规格、过期撤销与现有 Web 行为不回归
- `security_boundary`: listener 仅 loopback；raw path/method/query/编码 fail closed；日志、错误与启动信息不泄露 token、路径、凭据或环境；无 dotenv/provider 网络；并发、连接和响应有界
- `extra_risk_view`: 真实媒体/Tunnel/计费视角：Tunnel 只指向 callback-only 服务，首次 provider 请求前完成公网 exact-byte probe；单次 create、20 元硬上限、600 秒超时、durable ledger 恢复和不重提边界成立

- `A141-01`：专项测试证明有效随机 token 经独立 HTTP 服务返回 exact PNG，冻结字节、SHA-256、过期和撤销继续 fail closed。
- `A141-02`：无效 token、百分号编码、query、尾斜杠、工作台路径、HEAD/POST/OPTIONS 与任意其他方法统一为空正文 404，响应和日志不含 capability。
- `A141-03`：非 loopback 启动被拒；启动脚本禁止 dotenv、强制文本 mock、清除 provider key；服务限制为 5 秒连接超时和 8 个并发请求，不触发外部网络。
- `A141-04`：callback 专项测试、现有视频/capability 回归、语法、harness 与 diff 检查通过；correctness、security/boundary、真实媒体/Tunnel/计费三个只读审查视角无未处理有效 finding；最终一次 `bash scripts/verify.sh` 通过并保持 `mock-functional`。
- `A141-05`：若用户提供精确 workspace 且提交前检查通过，Quick Tunnel 根路径保持 404，首个冻结素材公网 exact-byte probe 在任何 provider upload/create 前通过；最多一次 create 完成 5 秒±0.25 秒、720×1280 MP4 下载与 fingerprint 校验。若未提供 workspace 或遇到不确定状态，则以 `safe-blocked`/durable 状态收口，0 次或最多 1 次 submit，绝不自动重提。

## Implementation Notes

- 新增的 callback server 不导入完整 Web dispatcher，只在请求命中精确 raw request-target 后惰性调用 `drama_video.read_public_asset()`；既有 Web 路由和 `SD_ASSET_PUBLIC_BASE_URL` 拼接契约未改。
- 服务以 8 个 handler semaphore、5 秒整连接 timer deadline、固定 connection-close 响应限制资源；覆盖 stdlib 双前导斜杠规范化、反射型 parser error、HTTP/0.9 与未知 method，所有已解析拒绝分支统一为空正文 404。
- 原计划外新增 `episode1-single-submit-v1` 最后一跳 authorization profile 与专用脚本，是媒体/计费审查发现的必要范围变化：generic smoke 保持兼容；专用入口只接受一次 `--book`，固定 20 元、600 秒并拒绝任何参数放大。
- 20 元是本地估算/授权硬门，不是 provider 账单侧 max-spend；供应商实际计费若高于估算，只能在完成后标记 `budget_exceeded`，不能事前阻止或自动退款。
- loopback 进程冒烟确认 `/` 与 `/api/workspaces` 都是 404/0-byte；未启动 Tunnel、未读取 `.env`、未访问 provider。
- 首轮审查 findings：correctness 1 项（`//` raw path）、security 4 项（parser 反射、HTTP/0.9、slowloris total deadline、NaN/Infinity）及复核 1 项（early parser 0-byte）、媒体/计费 1 项（20 元/600 秒可参数放大）；全部修复并经原审查者最终复核为 none。
- 首次 canonical 验收在 unittest 阶段失败（2775 tests，34 failures / 113 errors），共同症状是全局 `paths.WORKSPACE_DIR` 漂移到临时目录。为移除本轮测试与既有异步 job 的竞态，capability register/read/revoke 增加默认兼容的显式 `store_root`，callback 测试不再跨请求 patch 全局路径；callback+video+异步 compose+paths 56 项聚焦回归通过，原 correctness/security 审查者复核为 none。该次失败不计为验收通过证据。
- 第二次 canonical 暴露出本机 FFmpeg 已缺失：最先失败的既有 `drama_edit_export` 测试在 `setUp` 中改写全局路径后无法启动 FFmpeg，因 `setUp` 异常未执行 `tearDown`，继而造成相同的 34 failures / 113 errors 级联。经用户授权用 Homebrew 恢复 FFmpeg 后，callback→edit export→shot video web→paths→workspace isolation 顺序的 66 项回归全部通过。
- 同次诊断还收紧了 callback 生命周期：`create_server()` 只构造 loopback listener，不再改写宿主进程环境；dotenv/provider/mock 钉死移到独立 CLI `main()`，且 shell 启动脚本仍在 Python 导入前重复钉死。新增回归分别证明 library 构造零环境副作用、CLI 入口清除 provider key。
- accepted implementation 上启动 callback 与 Quick Tunnel 后，公网 `/`、`/api/workspaces` 均为 404/0-byte；为跨对话保持运行，两个前台程序放入具名临时 detached `screen` 会话，未注册系统服务，收官时需精确停止。
- 真实零提交探针在 `iter124_real_sop_v2` 上确认：Episode 1 与两张 PNG 参考图齐备，无 durable video ledger/旧视频；`GET /v1/video/tasks` 鉴权成功且只见 1 个 completed task。供应商详情实际返回 `task.outputs: [signed_url]`，暴露出完成态解析器只认单数 `output/result` 的阻塞 bug；保持 0 submit 后补齐严格单元素 outputs 支持。
- outputs 修复的 correctness/security/media 复核进一步关闭三类边界：枚举所有出现的 legacy URL 别名并要求 exact 单值；`None` 空占位保持兼容，其他非法类型/长度/结构 fail closed；在 DNS/连接前以固定错误拒绝非 ASCII、空白/control、非法 port、非 HTTPS/credentials/fragment，避免签名 query 进入异常日志。30 项视频聚焦测试通过，最终三视角复核均为 none。
- 只读详情探针随后确认既有 completed 输出 hostname 与 `SD_VIDEO_RESULT_HOSTS` 精确匹配；但当前 `SD_VIDEO_ESTIMATED_COST_CNY` 分类为 `over_20`，不满足本轮授权门，故仍为 0 submit，禁止通过降低真实估算来绕过。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: callback-only 公网暴露、raw request-target 校验、整连接 deadline 与本地授权上限不等于 provider 账单封顶，属于后续真实媒体入口需要复用的长期安全边界。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_asset_callback_server.py` | 新增 loopback、callback-only、有界且静默的随机 capability HTTP 服务 |
| `scripts/drama_asset_callback.sh` | 新增禁止 dotenv/清除 provider key 的安全启动入口 |
| `src/drama_video.py` | 新增 episode 1 单提交 profile 门禁，并为 capability store 增加默认兼容的显式测试根以消除全局路径竞态 |
| `src/drama_video_smoke.py` | 将可选 authorization profile 透传到真实视频 job |
| `scripts/drama_video_episode1_single_submit.sh` | 新增只接受 `--book`、固定授权参数的专用真实验证入口 |
| `tests/test_drama_asset_callback_server.py` | 覆盖 exact PNG、统一 404、raw protocol、日志、loopback 和总 deadline |
| `tests/test_drama_video.py` | 覆盖 profile 边界与 smoke 到最后一跳的透传 |
| `docs/iterations/README.md`、本 iteration | 建立 iter141 索引、计划、审查路由与实施证据 |

## 不在本轮范围

- 不公开完整本地 Web 工作台，不建立长期或生产 Cloudflare Tunnel。
- 不读取、写入或回显 `.env` 与真实 key。
- 不增加 JPEG/WebP callback 支持，不接入逐镜视频、TTS、FFmpeg 完整成片或 episode 2+。
- 不将一次 legacy episode 1 provider 验证外推为完整短剧生产链已验证。

## Notes

- Quick Tunnel 每次重启都会得到新域名；每次真视频前由用户更新 `SD_ASSET_PUBLIC_BASE_URL`。
- `SD_VIDEO_RESULT_HOSTS` 只接受既有 completed 输出的精确 hostname，不保存或记录完整签名 URL。
- 视频超时或网络状态不确定时只查 task 与账单，不重提。
