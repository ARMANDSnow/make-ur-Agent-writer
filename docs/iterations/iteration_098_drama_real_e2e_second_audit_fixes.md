# Iteration 098 - 短剧真模型二次全链审计修复

## Context

iter 097 已收紧短剧真文本、图片和视频的授权、provider 身份与恢复边界，但真实多模态仍未获授权实跑。用户要求继续以至少 5 个 subagent 调研全流程潜在 bug，并汇总后起迭代修复。本轮由 6 个只读视角覆盖 text、image、video、Web jobs、跨阶段 freshness 与 provider/billing，主线程复核后确认仍存在会造成真实质量断链、重复计费/证据失真或凭据越界的确定性缺陷。

本轮只修复可由 mock、故障注入与静态检查证明的工程问题；不读取 `.env`、私有 workspace、`data/`、`outputs/`、`logs/` 或 `小说txt/`，不运行真文本、真生图、真视频或上游账单请求。

## Plan

1. 修复站②语义断链与 schema fail-open：向真模型注入有界站①设定视图，并在本地强制三类钩子类型与固定顺序。
2. 为真文本五站冻结可稳定复算的 canonical 产物指纹；resume、跨阶段校准和人工编辑后重新进入时若血统漂移则网络前 fail-closed/降级证据。
3. 下沉 Web 真文本付费 attempt 状态：绑定 step/input/model/endpoint/account，区分本地前置失败、结果未知与终态；crash/cancel/timeout 后未经上游与账单核对不得重复提交。
4. 为图片与视频带凭据 API 使用 connect/TLS 后实际 peer 校验的共享 HTTPS JSON transport，确保在发送 path/body/Authorization 前拒绝私网 peer，并继续拒绝 redirect 与超限响应。
5. 重构图片 attempt/provenance：冻结 provider/account/model、episode-1 cast 与渲染输入指纹；区分本地拒绝、可能已提交、响应已收到和 artifact 已落盘，支持 crash 后零网络收尾并避免零请求假计费。
6. 修复图片校准聚合：按冻结 cast 选择每角色最新有效成功 attempt，角色移出 appearances 或合法重绘都不会 false-green/false-negative。
7. 冻结视频原始授权预算/估价/timeout 并在 resume 复核；Web 状态直接投影 durable submission ledger；补最小严格 MP4/WebM 结构与实际规格校验，不再接受 12-byte `ftyp` 或把声明规格当实测规格。
8. 先跑覆盖改动面的聚焦 mock/故障注入与语法检查，再按 `iter-finish` 用 correctness、security/boundary 及 billing/resume 至少三个独立只读视角复审；修复 findings 后只跑一次 canonical + `verify.sh` + mock preflight。

## Acceptance

- 站② prompt 含有有界、canonical 的站①核心设定；任意类型、重复类型或乱序的 3 个钩子均被 schema 拒绝且不提交产物。
- 真文本 completed step 的稳定产物被编辑、替换、删除或损坏后，resume 在 provider 调用前停止，校准不得继续声称纯真模型全链证据。
- Web 真文本 provider 调用发生 crash/cancel/timeout 后，新一次普通确认不能直接重发；必须同时确认 retry 与上游任务/账单已核对，且 provider/model/account 漂移在网络前拒绝。
- 图片/视频 API DNS 预查为公网但实际 socket peer 为私网时，path/body/Authorization 均未发送；公网 peer 正常，redirect、响应上限和 MIME/schema 守门保持有效。
- 图片本地前置失败为 0 confirmed/unknown request、0 估算消耗且不占付费 attempt；provider 结果已落盘后的 crash 可在 0 network 下完成提交；provider/cast/渲染输入漂移 fail-closed。
- 图片报告对角色 appearances 变化降级，对同角色两次合法成功重绘只取最新 current success，同时保留总 request/attempt 计量。
- 视频 submitted resume 只能沿用首次授权预算/估价/timeout；`video_status` 不依赖 recent jobs；截断/伪容器或实际 duration/dimensions/ratio 不符时不写 succeeded 产物。
- 不运行任何真模型或真媒体；聚焦测试、Python/shell 静态检查和 `git diff --check` 通过；最终 canonical、`scripts/verify.sh`、mock preflight 全绿。

## Implementation Notes

- 开工前工作树已有未跟踪 `.agents/`，视为用户文件，不修改、不暂存。
- 调研调用 6 个只读 subagent：text、image、video、Web jobs、跨阶段、provider/billing；均被明确禁止改文件、发起真请求或触碰受限目录。
- subagent 原始 findings 经主线程合并去重；钩子 `content <= 30` 建议与现有产品 fixture 冲突，未纳入硬约束，保留类型/顺序这两个确定性 schema 修复。
- 本轮立项不构成任何真实文本、图片、视频、provider 状态或账单查询授权。
- 站② prompt 改为注入有界、canonical 的站①设定视图；`DramaHookCandidates` 本地强制三种 hook 类型及固定顺序。
- 新增共享 `secure_http`：HTTPS connect/TLS 后读取实际 socket peer，校验通过后才发送 path/body/Authorization；图片与视频客户端改走此 transport。
- 五站 Web 真文本新增严格 durable attempt ledger，绑定输入/provider/账号和目标产物指纹；`response_received/succeeded` 且 canonical 产物匹配时零网络恢复，损坏、符号链接或漂移一律阻断。
- 多模态 runner 冻结五站产物指纹、图片 provider/cast/render 输入；图片区分确定未发送、请求失败、`artifact_received` 与成功，本地 commit 异常保持可恢复状态并限制 artifact 在 workspace 内。
- 视频 ledger 冻结预算、估价、timeout 与 provider；确定未发送不消耗单次提交，其他 create 异常保持 unknown。MP4 以 box/sample table 解析实测时长、尺寸与比例，回读和状态再次复核。
- 校准报告把 durable text/video ledger 与本地 audit 交叉去重，并单列 text/image submission unknown，避免 crash 后低报为 0 请求。
- 收官调用 3 个独立只读 subagent：correctness/schema、security/boundary、billing/resume。主线程修复其确认的 text commit→ledger/callback 重复计费窗口、图片普通 commit 异常、ledger 损坏 fail-open、artifact 越界恢复、视频 `RequestNotSentError` 误耗机会、assembled episode 指纹缺口、回读未复核 MP4 与报告低报问题。

## Acceptance Result

- 聚焦短剧回归：`294 tests OK`。
- Python 受影响模块 `py_compile`、4 个 shell 脚本 `bash -n`、`git diff --check`：通过。
- 收官审查：6 个前置调研 subagent + 3 个独立收官只读 subagent；无 P0，确认的 P1/P2 已全部修复并聚焦复验，无遗留 P0/P1。
- canonical：`1987 tests OK`。首次 sandbox 内运行仅因 12 个既有 `novel_client` 用例无权绑定 `127.0.0.1` 报错；在允许本机 loopback、仍保持 mock/无外网 provider 的环境重验全绿。
- `bash scripts/verify.sh`：exit 0；同样在允许既有 loopback 测试的环境完成。
- `OPENAI_MODEL=mock DRAMA_MODEL=mock ... python main.py preflight`：`PREFLIGHT: ok`，0 FATAL / 0 WARN。
- 未读取 `.env`、私有 workspace 或 `小说txt/`；未运行真文本、真生图、真视频、provider 状态或账单请求。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_098_drama_real_e2e_second_audit_fixes.md` | 本轮八段计划、实施与验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 098 索引。 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 同步实时 SOP、当前快照、阶段记忆与长期工程教训。 |
| `src/secure_http.py` | 新增凭据请求实际 peer 校验、有界响应和明确未发送异常。 |
| `src/ai_draw_client.py`、`src/drama_video_client.py` | 图片/视频 provider API 改用共享安全 transport。 |
| `src/drama_schemas.py`、`src/hook_designer.py` | 固定钩子类型/顺序并补站①→②上下文。 |
| `src/drama_smoke.py`、`src/drama_multimodal_smoke.py` | 修文本 callback 血统、跨阶段 freshness、图片恢复/报告和多模态证据。 |
| `src/drama_video.py` | 冻结视频授权，区分未发送/未知，直接投影 ledger，并严格解析/回读 MP4 规格。 |
| `src/web/jobs.py`、`src/web/routes.py` | 新增真文本 paid-attempt ledger、零网络 commit 恢复与一次性 retry/reconciliation 参数。 |
| `tests/test_drama_iter098_hardening.py` | 覆盖本轮 schema、peer、ledger、crash、路径、报告和媒体回读边界。 |
| `tests/test_drama_characters_api.py`、`tests/test_drama_image_video_clients.py`、`tests/test_drama_multimodal_smoke.py`、`tests/test_drama_video.py` | 适配 transport/规格语义并补回归断言。 |

## 不在本轮范围

- 任何真实文本、生图、视频、provider 状态查询或账单请求；仍需逐阶段重新授权。
- episode 2+ 视频、批量真实媒体、真 ComfyUI、公网多租户化与供应商选型。
- 文本单 station 的绝对硬预算：当前只能在调用后按 usage 结算，仍需在真实校准说明最大单站 overshoot；供应商若支持 reservation/幂等键可另轮设计。
- 通用媒体转码、完整专业级容器修复与所有 codec 支持；本轮只做安全有界的规格解析/拒绝。
- 视频 reference asset upload 本身仍无供应商幂等键/逐资产 durable ledger；其失败发生在 create POST 前，不消耗视频生成提交，但可能重复上传，留作后续 provider 能力调研。

## Notes

- 已显式使用 `iter-start`；起始提交信息草稿：`docs(iter098): 迭代计划 098 立项（短剧真模型二次全链审计修复）`。
- 收官按 `iter-finish` 在最终全量验收后同步 README、handoff 与 PROJECT_HISTORY；只 commit，不 push。
- 已显式使用 `iter-finish` 完成聚焦检查、多视角只读审查、findings 修复、最终标准验收与文档同步。
- 收官提交信息：`fix(iter098): 硬化短剧真模型全链恢复与证据边界`。
