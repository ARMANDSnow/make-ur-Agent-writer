# Iteration 089 - 短剧真实生图接入与视频 API 安全预备

## Context

Iteration 081 已交付短剧站④角色参考图的 placeholder 与自定义 HTTP 绘图骨架，但现有客户端只接受“端点直接返回图片字节”，Web 重画入口也固定走 mock，尚不能使用 OpenAI 兼容图片生成接口。用户现已提供可复用既有 AetherHeart key/base URL 的 `gpt-image-2` 图片模型，并授权本轮进行真模型生图 smoke。

同时，用户提供了素材上传、素材查询、视频任务提交与任务查询协议。视频生成仍暂缓：本轮只实现可测试的数据契约、URL/响应守门与显式授权 gate，不提交任何真实视频任务，不读取或改写 `.env`，也不把 key 写入仓库、日志或 workspace 产物。

## Plan

1. 扩展 `ai_draw_client`：支持 OpenAI 兼容 `/v1/images/generations`、`gpt-image-2`、base64/受控公网 URL 响应，并复用现有图片类型与 5MB 上限守门。
2. 将站④ Web“重画”从硬编码 mock 改为按配置自动探测；未配置/默认 mock 继续生成本地 SVG，真实配置才调用远端。
3. 新增短剧视频 API 客户端：素材上传/查询、任务查询与生成 payload 契约；真实视频提交必须经过显式 `allow_real_video=True` gate，本轮不启用。
4. 补充 settings/preflight/单测与最小 smoke 入口；使用既有 AetherHeart key/base URL 进行一张 `gpt-image-2` 真图 smoke，输出仅记录脱敏状态与产物元数据。
5. 收官执行 canonical 单测、`scripts/verify.sh`、mock preflight、授权的真生图 smoke，以及 correctness 与 security/boundary 双视角只读审查。

## Acceptance

- mock-only 默认路径零网络，站④重画仍生成可预览 SVG；测试发现模式下不会读取 `.env` 或触发真调用。
- OpenAI 兼容图片请求使用模型 `gpt-image-2`，鉴权只存在于请求头；支持合规 base64 图片和受控公网图片 URL，拒绝坏 base64、非图片、超 5MB、私网 URL、重定向与不支持格式。
- Web 重画真实配置路径不再被 `mock=True` 截断；错误响应对用户保持脱敏，不回显 key、上游响应正文或本地敏感路径。
- 视频素材/任务查询可通过 mock HTTP 响应验证；视频生成若未显式授权必须在发网前拒绝。本轮测试与 smoke 均不得调用 `/v1/video/generate`。
- 真生图 smoke 只生成一张低风险原创角色测试图，产物位于 gitignored workspace/data 路径；不修改 `.env`，不运行真视频生成。
- canonical 单测、`bash scripts/verify.sh`、`python3 main.py preflight` 通过；双视角审查结论与残余风险回填。

## Implementation Notes

- 开工时工作树仍保留 iter088 的未提交实现与文档；本轮不回退、不覆盖这些用户已有改动，iter089 新增差异按文件和 hunks 单独记录。
- `/Users/dingyuxuan/Downloads/sd_real_max.md` 采用脱敏读取，仅提取协议结构；未输出或持久化任何凭据。
- OpenAI-compatible 生图改为显式 `AI_DRAW_MODEL` opt-in；`AI_DRAW_BASE_URL`/`AI_DRAW_API_KEY` 必须整对配置，两者都缺时才整对复用 `OPENAI_BASE_URL`/`OPENAI_API_KEY`，禁止跨 pair 拼接凭据。
- Web 重画先保存当前角色表，再以 `application/json` + 严格布尔 `confirm_real_image=true` 发起；mock 默认仍只写本地 SVG。真实路径持 workspace write guard，避免同 workspace 并发双花，但长请求会暂时阻塞该 workspace 其它写操作。
- 图片响应先完成 JSON/base64/5MB/magic/MIME/host/TLS 校验，再以同目录临时文件 + `fsync` + `os.replace` 原子落盘。`ReferenceImage` 同时记录 requested/provider model/size 与 PNG IHDR width/height；JPEG/WebP 当前宽高诚实为 `null`。
- `drama_video_client` 已覆盖素材上传/查询、任务列表/详情和生成 payload；真实 `/v1/video/generate` 只有调用者显式传 `allow_real_video=True` 才能触发，本轮没有任何真实视频请求。
- 首次 Python `urllib` 探针因上游请求特征返回 403；补产品 User-Agent 后只读模型端点不再被 403 拦截。真实图片生成通过同一 `/v1/images/generations` API 的直连 curl 成功，返回随后经过生产解析/尺寸/原子落盘逻辑验证；为避免重复计费，修正为 120 秒超时后的 shell smoke 未再发第二张图。

## Acceptance Result

完成。

- canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests -q` → **1839 tests OK**（60.389s）。最终 `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0，内部同样 **1839 tests OK**（239.018s），随后 mock auto-pipeline、status、manifest/report/cost 全过，report snapshots OK。
- preflight：`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = **ok / 无 WARN / 无 FATAL**；真实配置 `.venv/bin/python3 main.py preflight` = **warn / 无 FATAL**，仅保留 tiktoken 模型映射、cache provider 与默认预算等既有提醒。
- 静态/聚焦：最终媒体与 iter088 影响面聚焦 **107 tests OK**；`py_compile`、`bash -n`、`shellcheck`（可用时）、`git diff --check` 通过。裸系统 `python3` 的首次 verify 因未安装 `tiktoken` 失败；切回仓库 canonical `.venv` 后完整通过，未改验证脚本。
- 真生图：用户授权下向既有 AetherHeart base/key 提交 1 个原创角色请求；请求 `gpt-image-2 / 1024x1024`，上游返回 `gpt-image-2-codex / size=auto`，实际 PNG **940×1673 / 1,546,048 bytes**。响应未含视频调用，图片与脱敏 `smoke_result.json` 位于 gitignored `workspaces/iter089_image_smoke/data/character_refs/c001/`；未修改 `.env`。
- 铁律⑨：correctness、security/boundary、Web/integration 三个独立只读 subagent 完成首审、修复与最终复核。首审发现凭据 pair 交叉回退 High、Web 付费/CSRF、smoke 内部门缺失、HTTP 明文凭据、URL shape/preflight 漂移、签名 URL 日志、非原子落盘、旧 prompt 付费、旧图 slot、provider 尺寸不可观测等问题；全部修复。最终三视角均 **PASS**，无剩余 correctness 或 High/Medium security finding。
- 主线程复核：确认 mock 默认零网络、显式图片 opt-in、JSON 逐请求确认、专用 pair 整对回退、HTTPS/NoRedirect/公网 IP/结果域 allowlist、响应上限与 magic、原子替换、视频生成 gate、测试 env scrub 均成立；未发现 key、响应正文或私有文本进入 tracked artifact。
- 残余风险：HTTPS allowlisted hostname 仍有 DNS 二次解析的 Low 风险，但成功利用还需目标端提供该 hostname 的有效 TLS 证书；JPEG/WebP 暂不提取宽高；Web 同步生图会持写锁最长约 120 秒；上游可能忽略请求 size，现已留 requested/provider/actual 元数据并用 `object-fit: contain` 避免方形裁切。这些均不阻断本轮。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_089_drama_real_image_video_api_guard.md` | 本轮 8 段计划与验收记录。 |
| `docs/iterations/README.md` | 追加 iter089 索引。 |
| `src/ai_draw_client.py` | OpenAI-compatible `gpt-image-2`、独立 opt-in、凭据整对回退、TLS/SSRF/响应/原子落盘与实际元数据。 |
| `src/drama_video_client.py` | 素材与视频任务协议客户端、参数校验及真实生成显式 gate。 |
| `src/drama_image_smoke.py`、`scripts/drama_image_smoke.sh` | 双层确认的一图 smoke 与脱敏结果记录。 |
| `src/drama_schemas.py` | `ReferenceImage` 增加 requested/provider size/model 与可选宽高。 |
| `src/config.py`、`src/preflight.py`、`src/web/settings.py` | 媒体配置、测试 scrub、secret mask 与 preflight 守门。 |
| `src/web/routes.py`、`src/web/static.py` | 逐请求 JSON 确认、保存后重画、同 slot 替换与竖图 contain 预览。 |
| `tests/test_drama_image_video_clients.py` 等 | 协议、凭据、TLS/SSRF、CSRF、原子性、smoke、settings 与隔离回归。 |

## 不在本轮范围

- 真实视频生成任务提交、轮询完成、下载成片或费用/时长实测。
- 第 3 集及以上季级编排、五站全面真模型 job 化、完整 `drama_smoke.sh` 文本模型实跑。
- ComfyUI 真实 workflow 导入执行、LoRA/checkpoint 适配或真绘图批量生产。

## Notes

- 真生图属于用户本轮明确授权的唯一远端生成动作；真视频继续遵守显式授权 gate。
- 上游实际模型别名与尺寸会偏离请求值；本轮不伪装成 1024 方图，按 requested/provider/actual 三层诚实留痕。
- iter088 与 iter089 在同一未提交工作树中连续完成，且共享文件缺少可靠中间快照；为避免人为拆分造成不可验证的中间状态，提交时合并为一个收官 commit，并明确覆盖两轮。
- 提交信息草案：`feat(iter088-089): 完成短剧多集交付与真实生图安全接入`。
