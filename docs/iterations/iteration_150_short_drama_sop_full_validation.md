# Iteration 150 - 短剧完整 SOP 前后端真人验证与修复

## Context

用户要求以真人会实际点击、刷新、误操作和中途取消的方式，完整验证已宣称实现的短剧 SOP，修复前后端流程阻断、虚假完成态、数据污染、安全边界与不美观/反人类 UI；改动阶段性 commit、只 commit 不 push。本轮获单次明确授权，从桌面 `key.rtf` 仅加载 allowlist 配置做限额真实验证：最多 10 次文本、2 张角色图、1 次 5 秒视频/20 元，暂无真实 TTS。凭据不得进入命令、日志、报告或仓库。

用户明确本轮不用 `iter-start`；本文在实现和审查完成后按 iter 固定八段补建，作为最终汇总报告并衔接 iter149。

## Plan

### Implementation Context
- `must_read`: `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_118_drama_full_sop_real_user_validation.md`, `src/web/routes.py`, `src/web/server.py`, `src/web/jobs.py`, `src/web/static.py`, `src/web/templates.py`, `src/drama_local_demo.py`, `src/drama_smoke.py`, `src/drama_video.py`
- `expected_changes`: `src/drama_local_demo.py`, `src/drama_reviewer.py`, `src/drama_smoke.py`, `src/storyboard_builder.py`, `src/web/jobs.py`, `src/web/routes.py`, `src/web/server.py`, `src/web/static.py`, `src/web/templates.py`, `scripts/run_local_drama_e2e.py`, `tests/test_drama_characters_api.py`, `tests/test_drama_local_demo.py`, `tests/test_drama_sop_bugfixes.py`, `tests/test_local_drama_e2e.py`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_150_short_drama_sop_full_validation.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env*`、`小说txt/`、私有原文/样本；不得回显/提交 `key.rtf` 或凭据；真模型仅限用户授权额度；视频 unknown/失败不得自动重提；不 push

1. 从创建、五站创作、评审组装、production、逐镜媒体到 compose/交付逐层核对代码、测试与真实浏览器行为，先修复能由 mock/本地确定复现的问题。
2. 建立源项目不变的隔离 `localdemo_*` A-F 验收入口，生成 synthetic 媒体并验证 exact duration、MP4/SRT/ASS/edit 与 QA；补取消、恢复、路径和 mutation 防护。
3. 在明示额度内分别验证真实文本、角色图与视频前置条件；任何公网素材/账单/unknown 歧义均 fail-closed，真实 TTS 不伪造。
4. 完成桌面和 390×844 真人点击、刷新、移动端触控/溢出/文案检查，以及 correctness 和 security/boundary 独立只读审查；关闭有效 findings 后运行 canonical 验收。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五站时长/集数、dirty/重生成、job 取消/恢复、隔离项目 exact-duration A-F、四件套交付与源项目不变；真实调用次数、费用和完成态不得夸大
- `security_boundary`: 核对全部 drama mutation 的 JSON/intent/same-origin/size 边界、symlink/no-follow、通用 `/run` 绕过、凭据与 provider raw/signed URL 脱敏、unknown/失败零自动重提
- `extra_risk_view`: Web/移动端/真实计费媒体专项：真人点击、刷新、触控高度、横向溢出、用户文案、视频公网素材可达性与账单/任务列表先行对账

- A150-01：已实现短剧 mutation 入口统一要求 JSON、显式 intent 与 same-origin，超限/坏集数/通用 `/run` drama 绕过均 fail-closed；用户错误不泄露内部异常或配置。
- A150-02：从已组装源项目启动本地 A-F 时创建新 `localdemo_*`，源角色表和 RenderPlan 不变；隔离项目完成目标时长、逐镜覆盖、QA 与 MP4/SRT/ASS/edit 四件套，取消能杀进程并清理半成品。
- A150-03：五站 UI 的 dirty/rewrite/regenerate、真实文本一次性授权、进度/错误、移动端 44px 触控与普通用户文案可用；桌面和 390×844 无横向溢出。
- A150-04：真实文本不超过 10 调用、角色图不超过 2 张、真实视频不超过一次 create/20 元；前置不满足时零提交，真实 TTS 明示未实现。
- A150-05：correctness/behavior、security/boundary 与 Web/计费媒体视角完成独立只读审查，所有确认有效的 P0-P2 findings 已修复并聚焦回归通过。
- A150-06：最终实现 commit 上 canonical `bash scripts/verify.sh` 通过，结论仅为 `mock-functional`；本地隔离 A-F 可记 `local-e2e`，真实文本/角色图只记窄范围 provider 校准，不升级为完整 `provider-validated`。

## Implementation Notes

- 五站与生产 API 增加统一 mutation 防护：wire POST/PUT 强制 `application/json`、`x-drama-mutation-intent: mutate-v1`、Fetch Metadata/Origin 同源检查与 64 KiB 上限；通用 `/run` 拒绝全部 drama handler，防止绕过真实授权和参数校验。
- 分镜 30/60/90/120 秒 mock 输出改为精确重定时；集数只接受 1-100 整数，不再静默回退；评审先做本地时长门禁，明显错误不浪费模型调用。
- `localdemo_*` 是新的隔离验收 profile：源项目只作为“已组装且允许启动”的入口，系统新建目标项目并在 mock 五站后生成 RenderPlan、资产、逐镜 PNG/MP4、synthetic TTS、TimelineManifest、合成与 exact 四件套。源项目角色表哈希与 RenderPlan 均保持不变。
- 本地 A-F 的取消能力从父 job 传入 creative 子 job、FFmpeg 约 250ms checkpoint、逐镜图片/视频、口播与 TTS 循环；失败或取消通过 `finally` 删除 FFmpeg 半成品。进度按 creative 20% + A-F 80% 单调缩放。
- production、compose、逐镜图片/视频等结构性动作补 dirty 离开/覆盖确认；rewrite 成功后清除 dirty；真实文本改为一次性可读授权对话框。移动端原生 button 与 `.btn` 最小高度 44px，页面无横向溢出；production 内部术语移入折叠诊断或换成普通中文。
- correctness 初审发现本地验收最初会写入源项目、共享角色表并固定 30 秒，已改为全新隔离 workspace 和 selected duration。security 审查发现通用 `/run` 可绕过 drama 专用门禁、PUT 预读未限长，均已关闭。最终复核又关闭 FFmpeg 取消半成品、后半段取消延迟、raw acceptance level 和内部术语残留，最终无 P0-P2。
- 首轮 canonical 共执行 2888 项后在 unittest 阶段报告 1 failure/3 errors；可复现 failure 是新增 `drama-local-demo` 未加入全局任务中文名映射，离开保护弹窗会显示内部 step ID。补为“短剧本地 A-F 演练”后，改动面 88 项与 Web/路由高风险 123 项聚焦回归均通过；其余 error 未在对应聚焦范围复现，交由修复后的 canonical 重验确认。
- 第二轮 canonical 共执行 2888 项后仅余 3 个同源 error：旧 RenderPlan 测试在构造重复镜头时把 60 秒分镜改成 55/56 秒，新时长评审按设计返回 Reject，测试却仍直接组装。保留“必须 Approve 才能组装”的生产门禁，仅让三个测试夹具把时长差补偿到中间镜头；RenderPlan/RenderStore 29 项聚焦回归通过。
- 第三轮 canonical 的 2888 项单测已全部通过，随后 mandatory `local_drama_e2e` 失败。根因是本轮 wire mutation header 和一次性授权弹窗已经升级，本地验收脚本仍模拟旧请求且检查旧预算/超时赋值。脚本现携带 JSON + `mutate-v1`，验证弹窗授权及重试二次确认；新增单测后该模块 8 项和独立 loopback 全链均通过。
- 真实文本五站 5/5 首次成功，共 5 次模型调用，约 125.8 秒，记录成本约 ¥0.2483；两张角色图 2/2 首次成功，人工检查为完整竖版角色全身图、无明显破损/水印，按配置估算约 ¥2。未在报告保存完整 prompt、响应或凭据。
- 真视频先做零提交 task-list 鉴权并成功读取受控投影；配置的 trycloudflare 公网素材域名已失效，callback probe 在 upload/create 前失败。因禁止把完整本地 Web 端口临时暴露公网，本轮 `safe-blocked`：create 0、视频费用 0、无重试。项目没有真实 TTS adapter，未填写/调用 TTS。
- 真人浏览器先完成桌面五站→production→隔离 A-F→compose，隔离项目 60 秒、6/6 镜、四件套可下载；最终 390px 复验可见按钮最小 44px、无横向溢出、无 `RenderPlan/typed edges/local-e2e/revision/provider` 等普通页面内部词。

## Acceptance Result

- `A150-01` 至 `A150-05` 已由聚焦回归、真实浏览器、限额 provider 记录与 correctness/security 两路最终只读复核确认通过；最终复核无未处理 P0-P2。
- `A150-06` 前两轮 canonical 均在 unittest 阶段失败：首轮 2888 项、1 failure/3 errors，第二轮 2888 项、仅余 3 个同源 error；第三轮 2888 项单测全过但 mandatory `local_drama_e2e` 因旧 Web 请求/授权契约失败。三类问题均已修复并聚焦回归通过，待下一轮 canonical 重验后回填 accepted implementation commit、test count、steps、run ID、tree 与 duration。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 隔离 synthetic 验收不等于真实 provider、unknown 零重提、逐次授权和凭据脱敏均是现有长期规则；本轮只把当前能力与实测边界同步到产品 SOP，不新增跨项目 workflow 规则。

## 文件变更汇总

| 范围 | 改动 |
|---|---|
| `src/web/routes.py`、`server.py`、`jobs.py` | drama mutation/size/同源门禁、通用 run 拒绝、job 取消/进度/真实授权与脱敏 |
| `src/storyboard_builder.py`、`drama_reviewer.py`、`drama_smoke.py` | 四档时长、先验本地门禁、embedded mock 与取消/环境隔离 |
| `src/drama_local_demo.py` | 新增隔离 `localdemo_*` A-F 本地验收、exact media、取消与半成品清理 |
| `scripts/run_local_drama_e2e.py` | 同步 Web mutation 与一次性授权弹窗契约，保持 mandatory loopback 验收可执行 |
| `src/web/static.py`、`templates.py` | dirty/确认、移动端触控与布局、production/compose UX 和普通用户文案 |
| `tests/` 短剧相关模块 | mutation、安全路径、时长、隔离/源项目不变、取消、UI 契约与恢复回归 |
| `docs/product/short_drama_module.md` | v18 当前 SOP、隔离本地验收与真实校准边界 |
| 本文、README/handoff/history/index | 验收报告与当前状态同步 |

## 不在本轮范围

- 不实现真实 TTS adapter、BGM/SFX 质量链、平台自动发布、多人/公网部署或 archive Web UI。
- 不以 synthetic 本地 A-F 证明真实图片/视频/TTS 作品质量；不以五站文本或两张角色图成功证明逐镜视频、完整单集或多集 capstone。
- 不绕过公网素材服务要求，不把本地完整 Web 端口临时暴露到公网；视频 callback 不可达时不提交、不重试、不产生费用。
- 不读取/修改 `.env`、小说原文或私有样本，不提交 `key.rtf`、真实凭据、完整 prompt、provider raw response 或 signed URL。

## Notes

本轮实现 commits 从 `cb96773` 起按问题域分阶段形成；最终只 commit、不 push。真实 provider 工作区与隔离 `localdemo_*` 作为 gitignored 本地验证证据保留，不能当作仓库内可复现实例。
