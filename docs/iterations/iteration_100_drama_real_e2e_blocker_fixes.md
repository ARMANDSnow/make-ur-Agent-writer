# Iteration 100 - 短剧真模型全链阻塞修复

## Context

iter 097-099 已连续收紧短剧真文本、全角色生图与单次视频的授权、账本、产物血统和媒体校验，但尚未获授权进行真实多模态校准。用户要求继续由多个只读 subagent 从不同角度调研潜在 bug，并优先修复会阻塞一次完整真模型 E2E 的确定性问题。

本轮由文本状态机、图片/视频媒体链、operator/入口集成三个独立视角审计，主线程结合代码与官方 OpenAI Images 文档复核。确认的主阻塞包括：CLI 新视频 callback capability 只存在于无 HTTP listener 的进程内；hooks/characters 的 paid-attempt 输入指纹会被本次成功结果自改写，导致 crash 后无法零网络采纳；`budget_exceeded` 可绕过核账再次付费；图片与视频各有“产物已落盘、durable receipt 未提交”的 crash window；Web 五站真实文本入口无法提供后端必需的逐次授权参数；默认 `gpt-image-2` 请求仍发送当前官方示例未使用的旧式 `response_format` 字段。

本轮只修复可由 mock、故障注入、静态检查和本地跨进程 callback 模拟证明的工程问题，不读取 `.env` 或私有运行目录，不运行真文本、真生图、真视频、provider 状态或账单请求。

## Plan

1. 将视频素材 capability 从纯进程内字典改为短期、有界、冻结字节且可跨本机 Web/CLI 进程读取的 durable store；保留不可猜 token、过期、撤销、hash、PNG 与 symlink/普通文件守门，并用 callback 精确字节回读证明后才允许 provider upload。
2. 修复 hooks/characters paid-attempt 的自变异输入身份：将稳定上游投影与本次输出分离，使 provider 已成功、canonical artifact 已提交但 callback 崩溃时可以 0 provider 调用采纳，同时继续阻断真实上游漂移。
3. 将 `budget_exceeded` 纳入付费重试核账边界，禁止普通确认直接覆盖并二次请求；补 readiness 错误码，避免缺 key/base/context 等问题被误报为 `still_mock`。
4. 收口媒体 crash window：图片按 attempt staging/receipt 后再提交 canonical reference；视频 `submitted` 恢复优先校验已存在的完整本地产物并补写 `succeeded` ledger，避免签名 URL 过期后仍强制联网。
5. 修正 OpenAI-compatible `gpt-image-2` 请求形状，移除不属于当前 GPT Image 2 官方生成示例的 `response_format`，继续依赖默认 base64 PNG 响应并保持 compatible URL fallback。
6. 为 Web 五站真实文本调用增加不持久化的一次性确认、预算与超时输入；历史 job/retry 不继承确认，未知提交仍需独立 retry + 上游/账单核对。
7. 补强可直接阻塞供应商接收的本地媒体守门：PNG critical chunk/PLTE/顺序/zlib 尾部校验，以及视频 result-host lineage 冻结；完整 codec/fMP4 与逐素材上传幂等账本若无法在本轮可靠落地则明确顺延。
8. 用聚焦 mock、故障注入、跨进程 callback 与前端/API 回归覆盖上述状态序列；随后按 `iter-finish` 完成 correctness、security/boundary、billing/resume、tests/operator 多视角只读复审，修复 findings 后只跑一次 canonical + `verify.sh` + mock preflight。

## Acceptance

- CLI 注册的素材 token 可由独立 Web 进程读取同一冻结 PNG，过期/撤销/篡改/符号链接/超限均拒绝；callback 证明失败时 provider upload/create 请求数为 0。
- hooks 与 characters 在“canonical 已提交、multimodal callback 前崩溃”后可 0 provider 调用恢复；setup/storyboard/provider/account 等真实上游漂移仍在网络前阻断。
- 已有 `budget_exceeded` paid attempt 时，无 retry + reconciliation 双确认不得再次调用 provider；CLI 对 mock、缺 key、坏 base、context/max-token 分别给出稳定且脱敏的 readiness code。
- 图片在 provider bytes 已收到后的任一 commit crash 均可 0 provider 调用收尾；视频在 MP4/meta 已提交但 ledger 仍 `submitted` 时可 0 poll/0 download 补写成功账本。
- GPT Image 2 请求不发送旧式 `response_format`，仍能解析 `data[0].b64_json` 的严格 PNG。
- Web 五站真实文本未逐次确认时 0 provider 调用；确认后传递本次预算/超时，公开 job 与 retry 参数不持久化任何 `confirm_*`。
- 缺 PLTE 的 indexed PNG、未知 critical chunk、非法 chunk 顺序或 zlib 尾部数据在上传/视频引用前拒绝；submitted 视频的 result-host allowlist 漂移显式阻断或要求 reconciliation。
- 不运行任何真模型或真媒体；聚焦测试、Python/shell/JS 静态检查与 `git diff --check` 通过；最终 canonical、`scripts/verify.sh`、显式 mock preflight 全绿。

## Implementation Notes

- 开工前工作树已有未跟踪 `.agents/`，视为用户文件，不修改、不暂存。
- 调研调用 3 个只读 subagent：text chain、media chain、entrypoint/E2E；均被明确禁止改文件、运行真模型或触碰 `.env`、`data/`、`outputs/`、`logs/`、`小说txt/`。
- 主线程使用 `openai-docs` skill 核对 GPT Image 2 请求契约；官方 Docs MCP 未安装且全局安装审批被拒绝，随后仅使用官方 OpenAI 域的只读文档回退，没有修改全局 Codex 配置。
- 文本站将精确输入指纹与稳定 recovery fingerprint 分离；hooks 排除本次 selected hook，characters 排除本次角色表，同时安全升级 legacy 首次角色 attempt。普通 hooks 恢复不再把单个 selected hook 伪装成候选列表。
- `budget_exceeded` 加入文本/多模态核账状态并保持终态，readiness 公开稳定脱敏错误码；`drama_smoke` 不再默认清空进程全局 job。
- 图片 provider 输出先落 attempt 专属 staging，写 durable receipt 后再提交 canonical reference；staging 路径严格绑定角色、attempt 和随机后缀。PNG 守门新增 PLTE、未知 critical chunk、IDAT 顺序与 zlib 尾部校验。
- 视频素材 capability 改为 workspace 内 durable store，绑定 token、hash、size、类型与过期时间；提交账本冻结 result-host fingerprint，local MP4/meta 的 task/provider/cost 必须与 ledger 交叉一致后才可零网络采纳。
- Web 进度仅公开五站是否为 real；五个站点每次调用重新请求一次性确认、正预算和有界超时，reconciliation 另行确认，确认字段不进入 durable job 投影。
- 收官调用 correctness、security/boundary、E2E/operator 3 个独立只读 subagent。首轮发现并修复视频 local adoption 缺 provider/cost 血统、multimodal 覆盖 `budget_exceeded`、错误 staging schema、callback 文案仍限制同进程、单 hook 恢复重写候选、submitted 成功账本与本地产物未充分交叉验证等 P1；原视角复审后均确认关闭，无新 P0/P1。
- security 复审保留的 P2 为目录父级 symlink/TOCTOU 尚未全面升级到 dirfd 级原语，以及进程被 SIGKILL 时 capability 可能残留至过期、暂无主动孤儿 sweep；均不构成本轮单用户本机真链确定性阻塞。
- 本轮立项不构成任何真实文本、图片、视频、provider 状态或账单查询授权。

## Acceptance Result

- 聚焦测试：272 tests OK；首轮 findings 修复后最终 79 tests OK。
- 静态/格式：相关 Python `py_compile`、`node --check src/web/static.py`、`git diff --check` 通过。
- canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true .venv/bin/python3 -m unittest discover -s tests` → **Ran 2023 tests，OK（skipped=7）**。受限沙箱首跑的 12 个 error 全为 `test_novel_client` 绑定 `127.0.0.1` 被拒；允许本机回环后同命令全绿。
- `OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true bash scripts/verify.sh` → exit 0；受限沙箱首跑同样只在上述 loopback 测试失败，允许回环后脚本全绿。
- `OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true .venv/bin/python3 main.py preflight` → `PREFLIGHT: ok`，0 FATAL / 0 WARN。
- 3 个调研视角与 3 个收官复审视角均遵守只读边界；主线程复核后无未修 P0/P1。未运行真文本、真生图、真视频、provider 状态或账单请求。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_100_drama_real_e2e_blocker_fixes.md` | 本轮八段计划与后续实施、验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 100 索引。 |
| `README.md` | 同步 iter 100 项目状态、SOP 与短剧能力边界。 |
| `docs/AGENT_HANDOFF.md` | 更新当前快照、最新证据、工作记忆与 transition。 |
| `docs/PROJECT_HISTORY.md` | 追加 iter 100 里程碑、实施索引与长期恢复身份教训。 |
| `src/web/jobs.py` | 分离 exact/recovery 指纹，修复自变异恢复与付费核账状态。 |
| `src/drama_smoke.py` | 细分真实文本 readiness 错误并避免默认清空全局 jobs。 |
| `src/drama_multimodal_smoke.py` | 增加图片 staging receipt、稳定文本恢复、callback 可达确认与终态保持。 |
| `src/ai_draw_client.py` | 修正 GPT Image 2 请求形状、支持 staging 输出并强化 PNG 校验。 |
| `src/drama_video.py` | 实现 durable callback capability、result-host/provider/cost 血统与本地产物零网络收尾。 |
| `src/web/routes.py` | 向前端安全公开五站 real/mock 布尔状态。 |
| `src/web/static.py` | 为五站真实文本调用逐次收集确认、预算、超时与可选核账确认。 |
| `tests/test_drama_iter100_hardening.py` | 新增 15 项迭代回归测试。 |
| `tests/test_drama_image_video_clients.py` | 更新 GPT Image 2 请求契约断言。 |
| `tests/test_drama_iter098_hardening.py` | 适配图片 staging 与视频 result-host 血统。 |
| `tests/test_drama_iter099_hardening.py` | 补 result-host fingerprint fixture。 |
| `tests/test_drama_multimodal_smoke.py` | 适配 callback 可达确认新参数。 |
| `tests/test_drama_video.py` | 适配 submitted ledger 的 result-host 血统。 |

## 不在本轮范围

- 任何真实文本、生图、视频、provider 状态查询或账单请求；真实执行仍需逐阶段重新授权。
- episode 2+ 视频、批量真实媒体、真 ComfyUI、公网多租户化与供应商选型。
- 未取得权威供应商契约前，不凭推测修改视频 HTTP 200/201/202 或 endpoint dialect。
- 专业级 codec 解码、所有合法 fragmented MP4 支持、供应商级素材上传幂等键与逐资产计费语义；若本轮不能以有界依赖和确定 fixture 完整证明，则保留为后续专项。
- capability store 与图片输出目录的父级 symlink/TOCTOU 尚未全面改成 dirfd 级原语；SIGKILL 后的 capability 孤儿仅靠到期拒绝，没有主动 sweep。当前叶子 O_NOFOLLOW、目录 symlink 拒绝、hash/expiry 校验已覆盖主要本机边界，后续可做专项 P2 加固。

## Notes

- 已显式使用 `iter-start`。
- 已显式使用 `iter-finish` 完成聚焦检查、多视角只读审查、findings 修复、最终标准验收与文档同步。
- 官方请求契约复核：GPT Image 2 模型页与 Images guide 当前生成示例使用 `/v1/images/generations`、`model`/`prompt`，响应读取 `data[0].b64_json`，未使用 `response_format`。
- 收官提交信息：`docs(iter100): 收口短剧真模型全链阻塞修复`；只 commit，不 push。
