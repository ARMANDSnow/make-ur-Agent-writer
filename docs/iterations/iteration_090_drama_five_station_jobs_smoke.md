# Iteration 090 - 短剧五站真模型 Job 化 + 全链 Smoke

## Context

Iteration 080-082 已完成短剧站③分镜、站④角色、轻量评审与整集组装；Iteration 088 补齐四格式导出、Insights 和第 2 集继承；Iteration 089 又接入 OpenAI-compatible 真实生图，并为视频 API 建立了安全客户端与显式授权门。当前短剧模块已具备完整的 mock 产品闭环，但站①策划、站②钩子、站③分镜、站④角色与站⑤评审/组装仍缺少统一的后台 job 生命周期，真模型文本链路也尚未通过一条可复现、可取消、可观测的端到端 smoke 验证。

本轮承接短剧路线图中顺延的“站①②真模型补课 + 五站 job 化 + `drama_smoke.sh`”收口批：把耗时生成从同步请求迁移到既有 Web job/poll/cancel 语义，统一五站的状态、错误、重试和产物边界，并提供严格受权的全链 smoke 入口。立项本身不构成真模型调用授权；任何付费文本、图片或视频请求仍须遵守铁律⑥，其中真实视频生成继续保持禁用。

## Plan

1. 盘点五站现有 API、产物指纹、workspace 写锁与通用 Web job 基础设施，定义统一的 drama job step、状态机、公开投影和失败恢复语义。
2. 为站①策划与站②钩子补齐真模型任务配置、结构化输出修复、超时/取消 checkpoint、脱敏错误与 mock graceful-degrade；保持五赛道 fixture 和 episode 1/2 行为兼容。
3. 将站①策划、站②钩子、站③分镜、站④角色、站⑤评审/组装迁移到 202 + job id + poll/cancel 流程；防止重复提交、跨 workspace 污染、取消后继续写盘和旧 job 覆盖新产物。
4. 统一五站的 episode number、依赖前置门、artifact/meta/fingerprint 校验、workspace write guard 与 stale 处理；失败不得留下可被误判为完成的半成品。
5. 新增 `scripts/drama_smoke.sh` 及对应 Python/CLI 编排入口，覆盖 workspace 准备、五站生成、评审组装、导出与 Insights 核验；默认 mock，真实运行必须显式确认并具备预算/超时/日志边界。
6. 增加五站 job、取消竞态、resume/stale、episode 2、Web 状态恢复、错误脱敏与 smoke 脚本测试；同步前端按钮、进度、取消和失败重试体验。
7. 收官运行 canonical 单测、`scripts/verify.sh`、mock preflight、静态检查与 mock 全链 smoke；获得用户明确授权后才运行一次受控真模型短剧 smoke，并记录成本、耗时、调用数和脱敏产物证据。
8. 按铁律⑨执行 correctness、security/boundary 与 Web/job integration 至少三个独立只读审查视角，修复确认问题并把范围、结论和残余风险回填本文。

## Acceptance

- 五站耗时入口统一返回 202/job id，前端通过 poll 展示 pending/running/succeeded/failed/cancelled，支持刷新恢复与协作式取消；mock 默认路径零网络。
- 同一 workspace/episode/station 的重复提交、旧 job 回写、取消后写盘和跨 workspace 路径访问均被确定性阻止；写锁、原子落盘与 artifact fingerprint 语义不回归。
- 站①②真实配置可调用对应 drama task，结构化输出坏 JSON、缺字段、超时和上游错误均 fail-closed 或明确降级，不回显 prompt、响应正文、凭据或本地敏感路径。
- episode 1 与 episode 2 的五站依赖门、角色 skipped/new-character 分支、评审组装、导出与 Insights 全部兼容；既有 5 赛道 fixture 回归通过。
- `scripts/drama_smoke.sh` 默认以 mock 完成五站→组装→四格式导出→Insights 核验；真实模式必须同时要求显式确认、有效配置、预算/超时边界，并保证不会提交真实视频任务。
- 在用户明确授权后，受控真模型 smoke 至少完成一集文本五站链路并留下脱敏的状态、调用数、耗时、成本与产物元数据；若未获授权，收官须明确记录该项未执行，不能伪装为通过。
- canonical unittest 在 **1839 tests** 基线上全绿；`PATH="$PWD/.venv/bin:$PATH" OPENAI_MODEL=mock bash scripts/verify.sh` exit 0；mock preflight ok，真实配置 preflight 无 FATAL；Python/Node/shell 语法与 `git diff --check` 通过。
- 收官至少完成 correctness、security/boundary、Web/job integration 三个独立只读 subagent 审查，主线程复核 findings；不得触碰 `.env`、私有样本、`data/`、`outputs/` 或 `小说txt/`，不得未经授权运行真模型。

## Implementation Notes

- 复用通用 job registry / workspace write lock / `pollJob` / cancel 机制，新增 `drama-plan`、`drama-hooks`、`drama-storyboard`、`drama-characters`、`drama-review-assemble` 五个 allowlisted step。原五站 POST 生成入口由同步 200 payload 迁移为 **202 + job_id**；这是 API breaking change，调用方必须 poll job 终态后再 GET artifact。
- 站①/②新增严格 `DramaSetup` / `DramaHookCandidates` schema 与 `drama_plan` / `drama_hooks` 模型任务；默认 mock，真文本必须每请求同时给出 `confirm_real_text=true`、finite 正预算和 finite 正超时，路由层与 job last-hop 双层守门。每站在模型返回后、artifact 写入前结算本 job 增量成本；超预算不提交产物。
- 站点进度改为严格级联 fail-closed；storyboard 在角色、reviewer、assembler 三层均校验 `episode_no`。站⑤对 review/episode/meta 三件做提交前快照，取消或组装失败回滚；站①或影响设定的手工编辑会失效旧 hook candidates。
- Web 支持写作页五站刷新重连，未选 hook 会恢复已持久化候选而不重复付费；独立角色库可重连任意 episode 的角色 job，并将 episode context 贯穿生成/保存/重画/评审/跳转。
- `scripts/drama_smoke.sh` 默认 mock 串联五 job、选 hook、组装、JSON/Markdown/CSV/Comfy 导出与 Insights，且固定 `video_requests=0`。真文本与真生图使用独立确认闸；真生图限 1 张角色参考图、固定 OpenAI-compatible `gpt-image-2` 路径，明确拒绝 legacy `AI_DRAW_ENDPOINT`。

## Acceptance Result

- **功能验收**：默认 `bash scripts/drama_smoke.sh --book iter090_mock_final` 成功，五个 job 全部 succeeded，4 种导出非空，Insights `llm_calls=0 / cost_cny=0`，`video_requests=0`。用户本轮仅授权真生图，**未授权真文本**，因此五站真文本 smoke 未运行。真生图 smoke 提交 1 次请求后在 120s 超时，未返回图片；为避免潜在重复计费未自动重试。真视频请求为 0。
- **canonical**：`.venv/bin/python3 -m unittest discover -s tests` / `verify.sh` 内部均为 **1857 tests OK (skipped=7)**；`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0，随后 mock auto-pipeline/status/manifest/review report/cost 全过。首次受限沙箱运行有 12 个 localhost bind `PermissionError`，在允许回环端口的环境重跑后全绿，非代码失败。
- **preflight / 静态检查**：`OPENAI_MODEL=mock ... preflight` = ok/无 WARN/FATAL；当前真实配置 preflight = warn/无 FATAL。`py_compile`、dashboard `node --check`、`bash -n scripts/drama_smoke.sh`、`git diff --check` 均通过。最终 drama/Web 影响面聚焦 **187 tests OK**。
- **铁律⑨三视角审查**：correctness 首审发现 episode identity、站⑤ partial commit、parse-failed 结算顺序与超时边界；security/boundary 发现 job last-hop 缺 timeout 守门；Web/integration 发现旧 hook candidates 复用、角色库 episode 2 重连/跳转错位。上述可修项全部修复并加回归，三路修后复核均 **PASS**，无剩余 blocker。
- **残余风险（非 blocker）**：`timeout_minutes` 是协作式 deadline，无法主动中断已阻塞的 provider HTTP，底层仍由 models.yaml `request_timeout=400` 封顶；预算是单次调用后结算的软上限；站⑤ rollback 在极端二次 I/O 失败时只能 best-effort；setup 写入与候选文件 unlink 不是单一多文件原子操作。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `config/agents.yaml`, `config/models.yaml` | 短剧五站文档配置与站①/② model task。 |
| `src/drama_schemas.py`, `src/drama_planner.py`, `src/hook_designer.py` | 站①/②严格 schema 与真/mock 模型 wiring。 |
| `src/character_designer.py`, `src/drama_reviewer.py`, `src/drama_store.py` | storyboard episode identity 三层 fail-closed。 |
| `src/web/jobs.py`, `src/web/routes.py` | 五 job handler、双层确认/预算/超时守门、workspace×step 隔离、站⑤ rollback、202 API。 |
| `src/web/static.py`, `src/web/drama_view.py` | poll/cancel/reconnect、候选恢复、角色库 episode context、五站严格进度/stale。 |
| `src/drama_smoke.py`, `scripts/drama_smoke.sh` | 五站全链 smoke、分离真文本/真生图授权、四导出/Insights/零视频核验。 |
| `tests/_drama_base.py`, `tests/test_drama_*.py`, `tests/test_hook_designer.py`, `tests/test_smoke_scripts.py`, `tests/test_web_routes_*.py` | 五站 job、预算/取消/超时、episode 2、rollback、Web 恢复与 smoke 回归。 |
| `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `AGENTS.md` | iter090 立项/收官、SOP 与接力状态。 |

## 不在本轮范围

- 真实视频生成、任务轮询完成、下载成片及费用/时长实测。
- 第 3 集及以上的季级长程编排与无限 episode 自动生成。
- ComfyUI 真实 workflow、LoRA/checkpoint 适配或批量真实生图生产。
- 小说主链路 10-20 章 capstone，以及文风自动修文阈值/费用校准。

## Notes

- 本轮已显式使用 `iter-start` skill 立项；收官必须使用 `iter-finish`。
- `README.md` 的“项目阶段 SOP（实时状态）”结构本轮开工不改；收官时必须更新对应短剧阶段状态与“最近一次更新”时间戳，并在 `docs/AGENT_HANDOFF.md` 追加 iter090 Phase Status。
- 当前未跟踪 `续写工作台.pptx` 是用户文件，保持不动、不 staged、不提交。
- 立项提交信息草案：`docs(iter090): 迭代计划 090 立项（短剧五站真模型 Job 化 + 全链 Smoke）`。
- 本轮已使用 `iter-finish` 完成 canonical 验收、三视角审查、SOP 与 handoff 同步。
- 本轮用户授权的是真生图，不是真文本；未将生图授权扩张为五站文本调用或视频调用。
