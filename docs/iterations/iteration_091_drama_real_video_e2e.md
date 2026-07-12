# Iteration 091 - 短剧真实视频端到端闭环

## Context

Iteration 089 已提供 `DramaVideoClient` 的素材/任务协议、安全 URL 基础守门与真实生成显式 gate；Iteration 090 已将短剧五站统一迁移到 202 + 后台 job + poll/cancel，并用 mock smoke 跑通五站、四格式导出与 Insights。当前缺口是：结构化 episode、分镜、角色与参考图尚不能通过一个有界、可恢复、可取消且下载安全的后台任务生成并交付真实视频。

本轮把 episode 1 收口为单任务 MVP：五站文本产物与 fresh 素材通过严格校验后，上传素材、提交一次视频生成、后台轮询、下载校验、原子落盘并在 Web 播放/下载。立项不构成真文本、真生图或真视频授权；三类授权彼此独立。完成 mock 实现与验收后，必须先报告预计费用、模型/服务、时长、比例、分辨率和命令，只有用户明确回复“可以跑真实视频 smoke”才允许提交一次真实视频任务。

## Plan

1. 盘点 `DramaVideoClient`、五站 artifact/fingerprint、参考图 schema、通用 Web job registry 与现有下载/URL 守门，定义视频 job 状态机、公开投影和 200→202 等 breaking changes。
2. 新增独立视频后台 job：episode 1、单任务、固定合法时长/比例/分辨率；支持素材上传/查询、任务提交、状态轮询、协作式取消、finite 正预算/超时与无自动重试。
3. 建立三层独立授权：真实视频请求必须同时满足 `confirm_real_video=true`、finite 正预算和 finite 正超时；不得继承真文本或真生图确认，未确认时在任何网络请求前拒绝。
4. 对 episode、storyboard、characters、reference images 做 fresh/fingerprint/episode/schema fail-closed 校验；stale、错 episode、缺素材、坏 schema 均不得上传或提交。
5. 下载链加入 HTTPS/结果域 allowlist、禁止或受控 redirect、Content-Type、最大尺寸、视频 magic/container、原子落盘与 episode/task/provider 脱敏元数据；不保存签名 URL、Authorization header 或上游响应正文。
6. Web 增加待准备、上传素材、排队、生成中、成功、失败/取消/超时状态；支持刷新恢复、协作式取消、失败原因卡片和成片播放/下载。
7. 新增 `scripts/drama_video_smoke.sh` 与 Python 编排：默认 mock 全链零网络；真实模式 shell + JSON 双确认、一次最多一个付费任务、超时不自动重试，输出脱敏状态/耗时/费用/文件大小/时长/分辨率。
8. 补齐协议、安全边界、竞态/取消、刷新恢复、Web/job integration 与 smoke 测试，并保持五站、四导出、Insights、第 2 集和小说主链路不回归。
9. 调查 iter090 image2 超时链路（仅代码与脱敏记录），确认 120 秒是否低于上游实际生成时延；未来获授权时建议单次 180–300 秒且绝不自动重试。
10. 收官运行 canonical、`scripts/verify.sh`、mock/真实配置 preflight、Python/Node/shell/diff 检查及 mock 视频全链；使用 `iter-finish` 并完成 correctness、security/boundary、Web/job integration 三个独立只读 subagent 审查、修复与复核。

## Acceptance

- 视频耗时入口返回 202 + job id，不同步阻塞 HTTP；前端 poll 展示完整状态并支持刷新恢复与取消。
- 真实视频三闸独立成立：严格布尔 `confirm_real_video=true`、finite 正预算、finite 正超时，任一缺失都在网络前拒绝；真文本/真生图授权不得继承。
- MVP 仅允许 episode 1、一个视频任务、固定合法时长/比例/分辨率；无批量、无自动重试任何可能计费请求。
- 输入只接受当前 fresh episode/storyboard/characters/reference images；stale、错 episode、缺素材、坏 schema fail-closed 且网络请求数为 0。
- 下载通过 HTTPS/allowlist/redirect/Content-Type/size/magic/container 校验并原子落盘；元数据含 episode/task/provider 与安全的大小/时长/分辨率，不含签名 URL、Authorization 或上游正文。
- `scripts/drama_video_smoke.sh` 默认 mock 全链成功、网络请求数为 0；真实模式需命令行与 JSON 双确认，一次运行最多提交一个真实任务，超时不重试。
- canonical unittest 在 **1857 tests OK (skipped=7)** 基线上全绿；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0；mock preflight ok，真实配置 preflight 无 FATAL；Python/Node/shell syntax 与 `git diff --check` 通过。
- 五站、四格式导出、Insights、第 2 集和小说主链路不回归；API breaking changes 明确记录。
- correctness、security/boundary、Web/job integration 三个独立只读 subagent 首审、修复与复核均 PASS；结论与残余风险回填本文。
- 未获用户“可以跑真实视频 smoke”授权时，真视频提交必须保持 0；mock 验收后先报告预计费用、服务/模型、时长、比例、分辨率和待执行命令。

## Implementation Notes

- 开工时 `main` 仅有用户未跟踪文件 `续写工作台.pptx`；本轮保持不读取、不修改、不暂存、不提交。
- 指定计划文件 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在；本轮以用户在任务消息中给出的 11 项范围与授权边界作为权威计划，不扩展到第 2 集视频、批量生成或自动重试。
- 真实文本、真实生图与真实视频均未获本轮默认授权；实现、测试与标准验收只走 mock/只读 preflight。
- 新增 `drama-video` 独立 job：HTTP 只返 202/job id，worker 完成素材能力 URL 注册、上传/查询、单次计费提交、轮询、下载与原子提交。取消是协作式的：停止本地轮询，不伪称能撤销上游已提交任务。
- 真视频下载使用 HTTPS exact-host allowlist；TLS connect 后、发送签名 path 前再校验实际 peer IP，拒绝 redirect/非 200/错 MIME/超 100MiB/非 MP4。视频与 meta 用 `video_sha256` 绑定并可回滚；签名 URL、Authorization 与上游正文不落盘。
- episode/meta 新增 `episode_sha256` 完整性绑定；视频输入同时校验 episode/storyboard/characters 的 episode identity、source fingerprint、reference image schema/magic/hash。旧的 assembled episode 需重新评审组装后才可生成视频，这是有意的 fail-closed 兼容性变化。
- Web 第 1 集新增 `#video` tab，展示待准备/上传/排队/生成/成功/失败/取消/超时，刷新自动恢复 poll；第 2 集不暴露第 1 集视频操作。已有成片时仍显示最新失败原因；实际费用超授权上限时标 `budget_exceeded` 但保留已付费成片。
- `scripts/drama_video_smoke.sh` 默认在隔离 workspace 跑五站→参考图→视频 job→下载/校验，mock MP4 可播放，上报 `network_requests=0 / automatic_retries=0`。真模式要求 shell 口令 + CLI flag + request JSON `confirm_real_video=true`，且只消费已有 fresh workspace。
- iter090 image2 失败原因与当时记录一致：已成功过的同类请求在后续生成时超过 120s，无证据表明是连通性或 schema 问题。`ai_draw_client` 单次 timeout 调整为 300s，仍不自动重试；本轮未发生图请求，也无法代替 provider 账单确认上次是否计费。

## Acceptance Result

- canonical：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python -m unittest discover -s tests` → **1880 tests OK**（67.269s）。裸系统 Python 首跑因未安装 `tiktoken` 且 sandbox 禁止 localhost bind 不成立；切回项目 `.venv` 并允许测试回环端口后全绿。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` → **exit 0**；内部同样 **1880 tests OK**（185.779s），随后 auto-pipeline/status/manifest/review snapshot/cost 全过。
- preflight：`OPENAI_MODEL=mock .venv/bin/python main.py preflight` = **ok / 无 WARN/FATAL**；当前真实配置 `.venv/bin/python main.py preflight` = **warn / 无 FATAL**（仅既有 tokenizer/cache/default budget warning）。
- 视频 mock smoke：`bash scripts/drama_video_smoke.sh --book iter091_mock_review` 成功；**network_requests=0, automatic_retries=0, 834 bytes, 5s, 9:16, 720p, cost=0**。未确认真视频的 shell 路径在建 client/网络前拒绝。
- 静态验收：Python `py_compile`、dashboard Node `--check`、shell `bash -n`/shellcheck（如安装）、`git diff --check` 均通过。Playwright 实测 `#video` 深链、成片播放/下载、第 1 集限制与状态恢复，最终页面无 console 错误。
- 三个独立只读 subagent 审查均在 findings 修复后复核 **PASS**：
  - correctness（77 tests OK）：收口 characters episode identity、episode content hash、asset status fail-closed、prompt 预校验、deadline remaining timeout、video/meta hash+rollback、旧成片下最新失败展示。
  - security/boundary（62 tests OK）：收口下载 DNS rebinding 窗口、redirect/MIME/size/magic、超预算与费用缺失投影、能力 token、授权隔离和取消语义；只余已开始 capability GET 无法事后强制中断、极端二次 I/O 故障回滚 best-effort 两项 Low residual。
  - Web/job integration（153 tests OK）：恢复自动 poll、episode 2 隔离、timeout/cancelled 区分、旧成片+最新失败并存、`budget_exceeded` 可播放/下载且不误报失败。
- 兼容性/API 记录：新增 `POST /api/workspace/{name}/drama/video` 从设计起即为 **202**，调用方必须 poll `GET .../drama/video`；没有替换旧的同步视频 endpoint。`DramaEpisodeMeta` 新增 `episode_sha256`，旧 episode 要重新组装才能进入视频流程。现有五站、四导出、Insights、第 2 集与小说主链路在 canonical/verify 中无回归。
- 未执行真文本、真生图、真视频；真视频任务提交数保持 **0**。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_091_drama_real_video_e2e.md` | 本轮 8 段计划、实现与验收记录。 |
| `docs/iterations/README.md` | 追加 iter091 索引。 |
| `src/drama_video.py`, `src/drama_video_smoke.py`, `scripts/drama_video_smoke.sh` | 有界视频管线、安全下载/原子落盘与 mock/真模式双闸 smoke。 |
| `src/drama_video_client.py` | 多参考素材 payload、有界 timeout 与资源查询完善。 |
| `src/drama_schemas.py`, `src/drama_store.py` | assembled episode 内容 hash 绑定。 |
| `src/web/jobs.py`, `src/web/routes.py`, `src/web/static.py`, `src/web/templates.py` | 202 video job、tokenized media route、状态/播放/下载/取消 Web 闭环。 |
| `src/config.py`, `src/preflight.py`, `tests/__init__.py` | 视频配置隔离、preflight 与测试强制 mock。 |
| `src/ai_draw_client.py` | image2 单次超时由 120s 放宽到 300s，仍零自动重试。 |
| `tests/test_drama_video.py`, `tests/test_drama_image_video_clients.py`, `tests/test_smoke_scripts.py` | 授权/freshness/provider/下载/原子性/job/Web/smoke 回归。 |
| `README.md`, `docs/AGENT_HANDOFF.md`, `AGENTS.md` | SOP 实时状态与 Phase Status 同步。 |

## 不在本轮范围

- 未经用户后续明确授权的真实文本、真实生图或真实视频请求。
- episode 2 的真实视频、第 3 集以上季级编排、批量视频、自动重试计费请求。
- 真 ComfyUI、批量角色/分镜生图与小说 10–20 章 capstone。
- 对上轮可能已计费的 image2 超时请求进行盲目重试。

## Notes

- 本轮已显式使用 `iter-start` skill；收官必须显式使用 `iter-finish`。
- README SOP 表结构开工时不改；收官同步对应短剧阶段状态、“最近一次更新”、`docs/AGENT_HANDOFF.md` Phase Status 与 `AGENTS.md` 当前状态。
- 立项提交信息草案：`docs(iter091): 迭代计划 091 立项（短剧真实视频端到端闭环）`。
- 真视频待用户另行授权：当前固定 `dreamina-seedance-2-0-hc / 5s / 9:16 / 720p / 无音频 / 无水印`。公开第三方同类报价约 US$0.50–0.90/5s，但本项目 provider 实际计费未校准；建议请求前在 provider console 确认 `SD_VIDEO_ESTIMATED_COST_CNY`，首次授权预算上限建议 ¥10，timeout 300s，且绝不自动重试。
- 收官提交信息：`Iteration 091: 完成短剧真实视频端到端闭环`。
