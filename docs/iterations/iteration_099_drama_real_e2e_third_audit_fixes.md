# Iteration 099 - 短剧真模型第三次全链审计修复

## Context

iter 097-098 已收紧短剧真文本、图片和视频的授权、provider 身份、付费恢复与产物血统，但真实多模态仍未获授权实跑。用户要求继续调用多个 subagent，从不同角度审计“真文本 → 全角色真生图 → 单次真视频”的潜在缺陷，并汇总后起迭代修复。

本轮由文本链、媒体/provider、计费/resume、入口/preflight 四个独立只读视角审计，主线程复核后确认仍有会造成真跑前 false-green、旧付费结果错配、预算 fail-open、坏媒体进入唯一视频提交或已付费任务无法恢复的确定性缺陷。本轮只修复可由 mock、静态检查与故障注入证明的问题；不读取 `.env` 或私有运行目录，不运行真文本、真生图、真视频、provider 状态或账单请求。

## Plan

1. 建立五站真文本共享 readiness，在任何 durable attempt 写入前校验有效模型、provider routing、凭据/base URL、context 与 max-token；同时显式处理 `OPENAI_MODEL=mock` 会覆盖 `DRAMA_MODEL` 的设置/preflight 冲突。
2. 修复真文本成功 attempt 的恢复顺序：先绑定当前 provider 与输入指纹，再允许零网络采纳 canonical artifact；上游编辑、模型或账号漂移必须 fail-closed。
3. 统一站① setup 为 episode-local track/target duration 真源，阻断 wizard/setup 漂移继续污染站③、站④、review 与 assembled episode；补充动态 prompt 语义的聚焦回归。
4. 将短剧付费文本的脏/截断 LLM 费用证据改为 fail-closed：单站结算与跨进程 resume 不得把 dirty ledger 当作零费用继续提交。
5. 增加共享的有界图片结构校验，拒绝只有魔数的截断 PNG/JPEG/WebP，并在生成落盘、artifact 恢复、视频输入和 callback 注册前复用。
6. 将图片 current/provenance 同时绑定文件 SHA、规范化 `ReferenceImage` 记录、attempt artifact 与 provider fingerprint；元数据漂移不得继续声称真实图片证据。
7. 调整视频恢复顺序：durable `submitted` 任务只需同 provider/授权与结果 allowlist 即可继续轮询，不再要求已无关的上传 callback；Web 以 durable ledger 为主状态，recent job 仅作最近尝试信息。
8. 修复校准证据：视频费用未上报时保持 unknown 而非 0；真实文本/图片证据要求完整 provider 血统；失败请求计数排除非请求的终态 bookkeeping；多模态主 state 拒绝符号链接、目录与损坏文件。

## Acceptance

- 五站任一模型仍为 mock、无 provider 前缀、缺凭据/base 或 context/max-token 自相矛盾时，在 attempt ledger 与 LLM/provider 调用前稳定阻断；设置/preflight 不再把被全局 mock 覆盖的 `DRAMA_MODEL` 表述为可真实运行。
- `response_received/succeeded` 的旧真文本 attempt 只有在 provider 与当前输入完全一致时可零网络恢复；修改 storyboard/characters/wizard 或切换模型/账号后不得复用旧 review/产物。
- setup 锁定后，后续站只使用同一 track/target duration；wizard 漂移在网络前显式阻断，不生成“核心设定与分镜赛道不同”的 fresh episode。
- 本次调用区间或累计基线后的 LLM 费用日志出现 dirty/truncated 证据时，不返回可继续使用的确定费用与剩余预算，也不发起下一次真实文本请求。
- 截断 PNG、仅 JPEG SOI、伪 WebP 在落盘/恢复/上传前拒绝；真实小图 fixture 可通过；图片元数据任一血统字段漂移使 resume/report 降级或阻断。
- 已有 `submitted` 视频 ledger 时，移除 callback public base/当前确认仍可在 0 upload、0 create 下继续 poll/download；新任务仍必须在任何 provider 请求前完成 callback readiness。
- Web 不用 aborted/lost/failed recent job 覆盖 `submitted`/`submission_unknown` durable 状态；费用未知报告为 unreported/null，不显示为 0。
- 不运行真模型或真媒体；聚焦测试、Python/shell 静态检查与 `git diff --check` 通过；收官按 `iter-finish` 完成多视角复审、最终一次 canonical + `verify.sh` + mock preflight。

## Implementation Notes

- 开工前工作树已有未跟踪 `.agents/`，视为用户文件，不修改、不暂存。
- 调研 subagent 均被限制为只读，不运行真实请求，不触碰 `.env`、`data/`、`outputs/`、`logs/`、私有 `workspaces/` 或 `小说txt/`。
- 本轮立项不构成任何真实文本、图片、视频、provider 状态或账单查询授权。
- `src/drama_smoke.py` 新增五站共享 readiness：逐任务检查非 mock/provider 前缀、API key、base URL、context/max-token，并只允许远端 HTTPS 或 loopback HTTP；Web budget attempt 与多模态文本阶段都在账本/调用前复用。settings/preflight 显式拒绝 `OPENAI_MODEL=mock` 隐藏非 mock `DRAMA_MODEL`。
- 五站 downstream 统一从已完成 setup 取得 episode/track/duration，wizard 或 storyboard 漂移在调用前阻断；五份 prompt 改为动态 episode/duration。已成功或已收到响应的文本 attempt 在零网络恢复前重新绑定 provider、输入指纹与 canonical 产物证据。
- 单站与多模态累计费用统一以原子 `(cost, dirty)` 快照结算；脏/截断账本不再当作零费用放行。报告要求真实文本/图片 provider 血统，视频未报告费用保持 `null/unreported`，并排除 `final_of_attempts` 终态 bookkeeping。
- 图片入口收口为可有界结构解码的 PNG：校验 chunk CRC、IHDR/IDAT/IEND、尺寸/像素、zlib 上限、scanline/filter 与 EOF；JPEG/WebP 在可靠有界 decoder 落地前 fail-closed。落盘、attempt 恢复、currentness、视频引用共用结构校验，并绑定规范化 `ReferenceImage` 记录 SHA、文件 SHA 与 provider。
- 多模态主 state 与视频引用拒绝符号链接/非普通文件。旧 iter 098 图片 state 缺新 provenance hash 时不自动重付，显式返回 `image_provenance_upgrade_required` 等待人工核对。
- 视频先读取 durable ledger：已有 `submitted` 任务只校验同 provider/输入/授权后继续 poll，不再要求已无关的 callback public base，也不重新 upload/create；新提交仍在 provider 调用前要求 callback readiness。Web 以 durable `submitted/submission_unknown` 为主状态，recent failed/aborted/lost 仅保留为最近尝试信息。
- 完整 MP4 codec/sample offset 专业解析、episode 2+ 角色策略、场景/角色计数 schema 与供应商资产上传幂等键不在本轮实现范围。

## Acceptance Result

- 聚焦回归：短剧/设置/媒体相关组合 **179 tests OK**；最终全量发现两处旧 hook 测试夹具缺少新增 canonical identity 字段，补齐夹具后 `tests.test_hook_designer + tests.test_drama_iter099_hardening` **30 tests OK**。`git diff --check` 通过。
- 调研阶段由 text chain、media/provider、billing/resume 三个独立只读 subagent 审计；收官阶段另由 correctness、security/boundary、tests/docs 三个独立只读 subagent 复审。所有 subagent 均未修改文件、未读取私有目录、未运行真实请求。
- correctness findings：crash-adopt 身份旁路、可选 artifact hash、`final_of_attempts` 整数误计、恢复证据缺模型；tests/docs findings：旧图片 state 迁移、setup episode 身份、费用/dirty 撕裂读、覆盖不足；security findings：远端 HTTP base、魔数伪媒体、视频引用 symlink。主线程逐项修复并请求原审查者复核。
- security 二次复核仍发现手写 JPEG/WebP 校验可接受伪结构，随后将真实媒体入口收口为严格 PNG-only；最终三视角均确认 **无未修 P0/P1**。保留风险是旧 hashless 图片 state 需人工 reconciliation，以及 JPEG/WebP 需可靠有界 decoder 后才可重新开放。
- 最终 canonical（项目虚拟环境、允许 loopback 测试端口）**2008 tests OK**；`bash scripts/verify.sh` exit 0（其内再次 **2008 tests OK**）；显式 mock preflight **0 FATAL / 0 WARN**。当前本地真实配置的只读 preflight 亦为 0 FATAL，仅保留 tokenizer/预算提示。
- 未运行真实文本、真生图、真视频、provider 状态或账单请求；真实费用、耗时和作品质量仍未校准。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_smoke.py`, `src/preflight.py`, `src/web/settings.py` | 五站共享 readiness、base URL 安全与全局 mock/短剧模型冲突守门。 |
| `src/drama_schemas.py`, `src/{drama_planner,hook_designer,storyboard_builder,character_designer,drama_reviewer}.py` | episode-local setup 身份、动态 prompt 与 downstream 漂移阻断。 |
| `prompts/drama/*.txt` | 移除硬编码 60 秒/第 1 集，改用动态集号与目标时长。 |
| `src/web/jobs.py` | 文本 attempt 恢复身份、共享 readiness 与 dirty ledger fail-closed。 |
| `src/ai_draw_client.py` | 有界 PNG 结构解码，生成/恢复/上传共用校验，JPEG/WebP 暂停开放。 |
| `src/drama_multimodal_smoke.py` | 文本/图片 provenance、原子费用证据、state 安全、视频恢复与校准报告修复。 |
| `src/drama_video.py` | submitted 零重提交流程与引用图 symlink/路径守门。 |
| `src/web/routes.py`, `src/web/static.py` | durable 视频状态优先及恢复提示。 |
| `tests/test_drama_iter099_hardening.py` | 新增 readiness、identity、billing、media、resume、Web 的故障注入回归。 |
| `tests/test_drama_*.py`, `tests/test_hook_designer.py`, `tests/test_web_settings.py` | 更新严格证据/真实 PNG/动态身份测试。 |
| `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md` | 同步当前 SOP、接力快照、里程碑与长期教训。 |
| `docs/iterations/iteration_099_drama_real_e2e_third_audit_fixes.md` | 本轮八段计划、实现、审查、验收与残余风险。 |
| `docs/iterations/README.md` | 追加 Iteration 099 索引。 |

## 不在本轮范围

- 任何真实文本、生图、视频、provider 状态查询或账单请求；真实执行仍需逐阶段重新授权。
- 专业级完整 MP4/WebM/codec 可播放性验证、转码与供应商 adapter。
- episode 2+ 视频、多季模型、episode 2+ 角色新增/视觉更新策略重构。
- 为 storyboard 增加 scene/character 引用 schema 后再准确计算 `ai_friendly_constraints`；本轮不以启发式文本解析伪造场景数。
- 供应商素材上传的计费/幂等能力调研与逐资产 durable ledger。

## Notes

- 已显式使用 `iter-start`。
- 已显式使用 `iter-finish`；按仓库规则只 commit、不 push。
- PNG-only 是当前可证明的安全能力，不代表供应商 JPEG/WebP 永久不支持；重新开放前必须引入可靠、资源有界的真实 decoder 与对抗样本。
- 旧 iter 098 hashless 图片 state 选择“阻断并人工核对”而不是自动迁移或重新付费，避免伪造 provenance 或重复计费。
- 收官提交信息：`fix(iter099): 收紧短剧真模型全链恢复与媒体边界`。
