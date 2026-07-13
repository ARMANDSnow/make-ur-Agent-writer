# Iteration 097 - 短剧真模型全链审计硬化

## Context

Iteration 090-096 已完成短剧五站、全角色生图、episode 1 视频与多模态校准的 mock 工程闭环，但真实文本、图片和视频尚未完成分段供应商实测。用户要求在不发起任何真实请求的前提下，以多个只读 subagent 审计一次“真文本 → 全角色真生图 → 单次真视频”的全流程潜在缺陷，并据此起迭代修复。

三路审计确认：当前既有会在付费前阻断实跑的配置/入口问题，也有旧授权重放、跨集视频失效、媒体下载 peer-IP、结构化输出身份字段和 preflight false-green 等确定性缺陷；另有 provider deadline、未知提交恢复、视频 callback 拓扑与统一媒体账本等需要更深状态机设计的问题。本轮优先修复可被 mock/静态测试完整证明的高风险缺陷，并对尚不能完整恢复的计费边界 fail-closed，不运行真实文本、生图或视频。

## Plan

1. 修复分阶段 `real-image` / `real-video` resume 的配置加载顺序：仅在本次严格授权通过后加载 dotenv，并在首次媒体 readiness/凭据读取前完成；未授权和 report-only 保持零加载、零网络。
2. 将 standalone `drama_video_smoke` 在项目/LLM import 前固定文本 mock，并补 poisoned-parent + 网络审计，避免 video-only 扩大到真实文本初始化。
3. 从持久 job 的公开 retry 参数中剥离所有一次性确认字段，阻止 `confirm_real_text=true` 从历史 job/刷新状态直接重放；真实付费步骤必须重新确认。
4. 将五个短剧文本 task 纳入 preflight 的 provider、凭据、routing、context/max-token 检查，修复真实短剧配置 false-green。
5. 修复共享季角色表更新到 episode 2+ 后 episode 1 视频 readiness/readback 被误判失效：按 episode 1 相关角色构造稳定投影，不信任共享表顶层 `episode_no`。
6. 将真实图片结果下载改为 TLS connect 后、发送签名 path 前校验实际 peer IP，同时保留 exact-host、DNS、公网、无重定向、MIME/magic/size 守门。
7. 收紧真模型结构化输出：服务端覆盖 storyboard/character/review 的 season、track、duration、source identity；review 五项评分缺失时必须 `Abstain + parse_failed`，不得作为正常五站成功组装。
8. 修复多模态失败状态和证据语义：文本异常不得永久显示 running；视频在实际 POST 前失败不得误记 paid submission。评估并优先实现统一 durable video submission/task ledger；若不能在本轮完整覆盖 Web、CLI 与 crash resume，则在付费前 fail-closed 并明确顺延。
9. 对 callback 同进程拓扑增加可验证的零计费 readiness；不得仅凭布尔确认就开始 provider 素材上传。CLI 无可达 callback server 时应在任何 provider 请求前停止并给出稳定 blocker。
10. 用聚焦 mock 回归覆盖上述边界；随后按 `iter-finish` 完成 correctness、security/billing、provider/resume 至少三视角只读复审，修复 findings 后只跑一次 canonical + `verify.sh` + mock preflight。

## Acceptance

- 未授权、report-only、默认 mock 和 video-only smoke 均不加载媒体凭据、不初始化真实文本分支、不产生 DNS/TCP/urllib provider 事件。
- `.env`-only 的分阶段媒体配置会在本次授权后、readiness 前进入运行时；测试仅验证 loader 顺序，不读取真实 `.env`。
- recent/detail/retry 投影不含任何 `confirm_*` 一次性授权；重试真实短剧步骤缺少新确认时在网络前拒绝。
- preflight 对五个短剧 task 的无 provider 前缀、缺 key/base、坏 context/max-token 给出与小说 task 一致的 WARN/FATAL 语义。
- episode 1 组装/视频产物在 episode 2/3 更新共享角色表后仍可验证、播放与下载；episode 1 相关角色图片或内容变化仍会正确判 stale。
- 图片结果 URL 的 DNS 为公网但实际 peer 为私网时，在发送签名 path 前拒绝；错误不得包含完整 URL 或签名 query。
- 模型返回合法但错误的 season/track/duration/source identity 不得污染 canonical 产物；review `{}` 或缺任一评分维度不得作为正常成功评审。
- 文本失败状态为可恢复的 failed/blocked 而非幽灵 running；零视频 POST 的前置失败不记作 paid submission。callback 拓扑未被实际证明时 provider 请求数为 0。
- 不运行真模型、真生图或真视频；聚焦测试、Python/shell 静态检查和 `git diff --check` 通过；最终 canonical、`scripts/verify.sh`、mock preflight 全绿。

## Implementation Notes

- 开工前工作树已有未跟踪 `.agents/`，视为用户文件，本轮不读取其私有内容、不修改、不暂存。
- 调研由 text-chain、media-chain、entry/security 三个独立只读 subagent 完成；均未改文件、未运行真实模型、未触碰 `.env`、`data/`、`outputs/`、`logs/` 或 `小说txt/`。
- 本轮立项不构成任何真实文本、图片、视频或 provider 网络授权。
- 真文本五 task 已进入 preflight；CLI 与 core 入口都会在 workspace/job 创建前拒绝仍是 mock 的“真跑”。Job deadline 通过 context-local scope 压到每个 provider attempt 与 retry backoff。
- 真文本恢复同时锁定 model SHA 与 endpoint/model/account 复合哈希；crash-active 或当前进程已捕获的 provider 失败都持久化 `retry_required_step`，只有“重试授权 + 上游任务/账单已核对”两项都为真才能再提交。
- 视频付费窗口改为严格 durable ledger：`submitting` 表示结果未知，`submitted` 可持 task id 继续轮询，`failed/succeeded` 保留受限 cost 证据。损坏、不可读、符号链接账本与输入/provider/账号漂移均 fail-closed；冲突 provider task id 被拒绝。
- 图片签名 URL 下载在 TLS connect 后、发送 path/query 前校验实际 peer IP，且必须 MIME/magic 一致。视频 callback capability 保存注册时冻结 bytes，不再跟随可变 path。
- 旧 `drama_smoke --real-image`、standalone `drama_image_smoke` 和 Web 真实角色重画会绕过预算/attempt ledger，均已禁用或固定 mock；真生图统一从 multimodal runner 进入。
- storyboard/character/review 的 season、track、duration、source 与 reviewer identity 由服务端覆盖；真 review 缺任一评分必须 `Abstain + parse_failed`。episode 1 视频使用稳定角色投影，后续集数的出场 bookkeeping/新角色不会使旧视频误 stale。

## Acceptance Result

- 聚焦回归：`test_drama*.py` **277 tests OK**；追加的授权、SSRF/MIME、账本损坏、provider drift、task-id 冲突、callback 置换、crash-window 和跨集回读用例全绿。
- 静态检查：改动 Python `py_compile`、四个短剧 shell `bash -n`、`git diff --check` 通过。
- 最终 canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests`（项目 `.venv` 置于 `PATH` 首位）为 **1970 tests OK**，exit 0。
- `bash scripts/verify.sh`：exit 0。
- `OPENAI_MODEL=mock DRAMA_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true python3 main.py preflight`：`PREFLIGHT: ok`，**0 FATAL / 0 WARN**。
- 真文本、真生图、真视频和计费 provider 请求均未运行。
- 只读收官复审：
  - correctness/schema：发现 core mock 伪真跑、已捕获文本失败重试绕过核账、provider endpoint 漂移、reviewer identity 污染；均已修复。
  - security/boundary：发现损坏视频账本可被当作不存在、旧生图旁路、deadline 前误记付费、callback path TOCTOU 和缺 MIME 守门；均已修复。
  - billing/resume/provider：发现 video ledger/state crash-window 低报、冲突 task id、账号漂移和失败 cost 丢失；均已修复。
- 主线复核结论：无未修 P0/P1；实际 MP4 时长/分辨率解析和供应商级幂等键仍按本轮范围外登记。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_097_drama_real_e2e_audit_hardening.md` | 本轮八段计划、实施与验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 097 索引。 |
| `src/drama_smoke.py`、`src/drama_multimodal_smoke.py`、`src/llm_client.py`、`src/preflight.py` | 真文本 core readiness、provider deadline/身份绑定、重试核账与五 task preflight。 |
| `src/drama_video.py`、`src/drama_video_smoke.py`、`scripts/drama_video_smoke.sh` | 稳定跨集输入、callback 快照、严格 durable submission ledger、provider/task/cost 验证与 video-only 文本 mock 固定。 |
| `src/ai_draw_client.py` | 签名结果下载的实际 peer-IP、无跳转、size 与 MIME/magic 守门。 |
| `src/drama_schemas.py`、`src/drama_reviewer.py`、`src/storyboard_builder.py`、`src/character_designer.py` | 缺失评分 fail-closed 与服务端 canonical identity 覆盖。 |
| `src/web/jobs.py`、`src/web/routes.py`、`src/web/static.py` | 历史 job 授权剥离、job deadline scope，Web 真重画旁路禁用。 |
| `src/drama_image_smoke.py`、`scripts/drama_image_smoke.sh`、`src/drama_smoke.py`、`scripts/drama_smoke.sh` | 禁用无预算/无 attempt ledger 的旧真生图入口。 |
| `tests/test_drama_iter097_hardening.py`、`tests/test_drama_*.py`、`tests/test_mock_offline.py`、`tests/test_smoke_scripts.py` | 新增与更新授权、账本、SSRF/MIME、恢复、跨集、旧入口及离线回归。 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 同步 iter 097 SOP、当前基线、接力快照与长期付费恢复教训。 |

## 不在本轮范围

- 任何真实文本、生图、视频、上游任务查询或账单请求；真实执行仍需逐阶段重新授权。
- episode 2+ 视频、批量真媒体、真 ComfyUI、公网多租户化与供应商选型。
- 若无法在不引入半套语义的前提下完整落地：LLM provider 内部硬取消、跨供应商账单 API、视频 POST 响应丢失时的供应商级幂等键，以及完整 MP4 时长/分辨率解析，将明确登记后续迭代。

## Notes

- 已显式使用 `iter-start`。
- 已显式使用 `iter-finish`，按“聚焦检查 → 三视角只读审查 → findings 修复/聚焦复验 → 最终全量”收官。
- 为统计测试数而运行的非标准 `python -c` loader 未携带 local cost-map 环境，导致 LiteLLM 尝试访问公开 cost-map；DNS 失败后使用内置副本，未调用模型、生图或视频 provider。该命令不属于 canonical/verify，后续计数也应显式 pin mock/local cost map。
- 收官提交信息：`docs(iter097): 收官短剧真模型全链审计硬化`。
