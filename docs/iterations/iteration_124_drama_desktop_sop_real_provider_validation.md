# Iteration 124 - 短剧桌面端 SOP 与真模型验证

## Context

iter123 已完成本地 FFmpeg 完整成片竖切，canonical 基线为 2493 tests OK。用户授权清空既有 workspace 后，以桌面网页为重点完整走查短剧 SOP，修复已实现模块中真人用户可遇到的功能、流程、视觉与交互问题；另授权 `gpt-5.5-medium` 文本、`gpt-image-2` 图片与 Seedance 视频配置做受预算约束的真 provider 验证，明确排除 TTS。本轮按用户要求不运行 iter-start，但仍以固定 8 段格式形成 iter124 审计记录并执行 iter-finish。

## Plan

### Implementation Context
- `must_read`: `AGENTS.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_118_drama_full_sop_real_user_validation.md`, `docs/iterations/iteration_123_drama_ffmpeg_local_full_compose.md`, `src/storyboard_builder.py`, `src/web/routes.py`, `src/web/static.py`, `src/web/templates.py`
- `expected_changes`: `src/storyboard_builder.py`, `src/web/routes.py`, `src/web/static.py`, `src/web/templates.py`, `tests/test_drama_storyboard_builder.py`, `tests/test_web_routes_get.py`, `docs/iterations/README.md`, `docs/iterations/iteration_124_drama_desktop_sop_real_provider_validation.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`
- `do_not_touch`: `.env`、`小说txt/`、用户未跟踪体检报告；不测 TTS，不 push，不把局部 provider 校准外推为完整 provider pipeline

1. 清空原有 workspace，以 fresh synthetic 项目从 Wizard 走完两集五站、编辑/重排/单镜重生、角色复用、评审组装、导出、整季交付与 mock 视频。
2. 在 1440×900 桌面浏览器巡检首页、创作台、角色库、剧集详情、Insights、任务页，检查可达性、视觉、控制台与普通用户错误呈现。
3. 对发现的功能/UX/安全投影问题分批修复、聚焦回归并阶段性 commit。
4. 在总预算 ¥200、文本不超过 60 次/¥150、图片不超过 20 张的授权内运行真文本与真图片；图片单次等满 180 秒，失败后先核上游与计费。视频只在有效 key、真实公网素材回调和预算闸均满足时提交；TTS 不运行。
5. 完成 correctness、security/boundary 与 Web/media 三视角只读审查，修复 findings 后在 implementation commit 上只跑一次 canonical `bash scripts/verify.sh`。

## Acceptance

### Review Context
- `correctness_behavior`: 两集内容不得错误复用；任意集均可从列表/详情进入编辑；五站、角色复用、评审、导出与整季状态一致；真实文本/图片证据与调用数准确
- `security_boundary`: 普通 Web API/任务页不得暴露 provider error、request fingerprint、完整 prompt、签名 URL 或凭据；真媒体闸不得绕过 key、回调、预算与 once-only 语义
- `extra_risk_view`: 桌面 Web/多媒体，核对 1440×900 布局、导航、可读时间、真实图片展示、控制台、图片时长/次数及视频 safe-blocked 结论

- **A124-01**：fresh mock 两集完整 SOP 可从桌面页面跑通；第 2 集 mock 分镜绑定本集主线/钩子，不复用第 1 集内容。
- **A124-02**：剧集列表与详情均有明确编辑入口；多集用户无需手改 URL，页面不再硬编码“回到第 1 集创作台”。
- **A124-03**：任务页用可读时间与结构化 LLM 摘要；浏览器 API 只投影白名单字段，不暴露 raw provider error/request fingerprint。
- **A124-04**：真文本五站和两张角色图在授权预算/次数/超时内形成可审计结果；真视频若 key 或公网素材回调缺失则零提交并明确 `safe-blocked`；TTS 为明确未测试。
- **A124-05**：三视角审查无未处理 P0/P1/P2；implementation commit 上唯一 canonical verify 通过，结论不超过相应证据等级。

## Implementation Notes

- fresh mock workspace `sop_qa_124` 完成两集 SOP：核心设定、钩子、分镜增删/重排/单镜重生、角色参考图与复用、评审组装、单集/整季导出、mock 竖版 MP4；浏览器按 1440×900 验证。
- later-episode mock 分镜原本逐字复用 episode 1。新增 episode-local 派生逻辑，绑定当前集标题、主线、钩子并产生差异镜头；提交 `03e6f42`。
- 多集页面原本只有“查看”，页头还硬编码回第 1 集；列表和详情新增每集“编辑”入口并移除硬编码 CTA；提交 `bd2a910`。
- 任务页原本显示 Unix 浮点时间并整段倾倒 LLM JSON。后端新增调用记录白名单投影，前端改为本地可读时间和结构化调用表，raw provider error/request hash 不进入普通页面；提交 `bce39fc`。
- 真 provider workspace `iter124_real_sop_v2`：文本五站完成，审计记录 6 次真实调用（其中 drama-plan 首次 502 后由既有 transient 策略重试成功），估算 ¥0.2721；另有错误根路径 workspace 的 1 次失败调用估算 ¥0.0252，总计 7/60、¥0.2973。两张 `gpt-image-2` 角色图首次成功，分别 113.974 秒与 105.397 秒，2/20，估算 ¥10；目检均通过。
- 视频配置文件的 key 实为 `<your-api-key>` 占位符，文本/图片 key 对视频服务只读查询也返回 HTTP 401；且本机没有供应商可访问的公网资产回调。真视频保持 0 次提交并记 `safe-blocked`，未绕过回调可达性确认；TTS 按用户要求未测试。
- 聚焦证据：分镜 builder 44 tests OK；Web 路由 120 tests OK；任务页修复后 Web 路由 86 tests OK；`test_drama*.py` 736 项中 735 通过，唯一失败为未设置 canonical `DRAGON_RAJA_SKIP_DOTENV=1` 时 unittest 隔离器清理空环境变量，按标准隔离环境复跑该用例通过；审查修复后 storyboard+Web 97 tests OK。
- correctness 发现后续集 mock 单镜重生退回 episode 1 fixture 语义与精确绑定覆盖不足；已给 replacement 重新施加本集 hook/tag/draw context，并补非空本集 mainline、hook 与 episode2 rewrite 回归。security/boundary 发现日志白名单缺少类型/长度/secret 形态归一化及坏 status 可使 JS 崩溃；已严格投影并拒绝 URL credentials/query 与任意 path segment 的 `sk-` token。Web/media 发现任务页内部英文标识和短剧错误空态；已统一中文步骤/状态/表头/结果与通用空态。三视角最终均无遗留 P0/P1/P2。
- canonical 首次启动在 0.34 秒 harness 前置检查因 iter124 Markdown 元数据格式错误停止，未进入单测；修正文档并提交 `654f226` 后重验通过：2498 tests，15 steps，303 秒，run `668bc70de8f5465fa61d8c73995ed5b9`，tree `51fc2de2d60698bea4d592045da0f7473627326c`，`tracked_scope_clean=true`，mock preflight 0 FATAL/0 WARN。

## Acceptance Result

- **A124-01 — PASS**：fresh mock 两集 SOP 完整跑通；第 2 集初次分镜与单镜重生均精确绑定本集 mainline/hook/tag，episode 1 路径保持兼容。
- **A124-02 — PASS**：列表和详情均提供 episode-scoped 编辑入口，页头不再硬编码第 1 集；1440×900 最终视觉回归无横向溢出。
- **A124-03 — PASS**：任务页使用中文步骤/状态、可读本地时间与结构化摘要；API 对 task/status/model/numeric 字段强类型、有界投影，provider error、request fingerprint、credential URL/query 与嵌套 `sk-` token 不进入浏览器。
- **A124-04 — PASS（分列结论）**：真文本五站和 2 张角色图完成 `provider-validated-local-calibration`；真视频因有效 key 与公网素材回调缺失为 `safe-blocked`、0 submit；TTS 按授权明确未测试，不外推完整 pipeline。
- **A124-05 — PASS**：correctness、security/boundary、Web/media 最终复审无遗留 P0/P1/P2。实现提交 `d4bf9e7` 后的验收元数据提交 `654f226` 上 canonical 通过：2498 tests、15 steps、303 秒、run `668bc70de8f5465fa61d8c73995ed5b9`，`tracked_scope_clean=true`，结论 `mock-functional`。
- **总级别**：canonical 为 `mock-functional`；本轮真文本/图片仅为局部 `provider-validated-local-calibration`；真视频为 `safe-blocked`，TTS 为未测试。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 任务页公开投影与真媒体 safe-blocked 均已有长期凭据/公开投影规则覆盖，本轮是现有规则的实现与验证，无需新增长期规范。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/storyboard_builder.py` | later-episode mock 分镜绑定当前集输入 |
| `src/web/static.py` | 多集编辑入口、详情编辑入口、任务页可读时间与摘要表 |
| `src/web/templates.py` | 任务页真人用户文案与脱敏说明 |
| `src/web/routes.py` | LLM 调用日志浏览器白名单投影 |
| `tests/test_drama_storyboard_builder.py` | later-episode mock 分镜差异与绑定回归 |
| `tests/test_web_routes_get.py` | 多集编辑入口、任务页投影与呈现回归 |
| `docs/iterations/README.md`、本文件 | 登记 iter124 并记录 SOP/provider/审查/验收证据 |

## 不在本轮范围

- TTS；没有有效视频 key/公网素材回调时的真视频提交；把局部文本/图片校准宣称为完整 pipeline `provider-validated`。
- 新建公网隧道、向第三方图床上传角色图、Web compose job、episode 2+ 真媒体生产、未实现路线图节点的产品化扩建。

## Notes

- 用户预授权图片追加重试，但项目长期规则仍要求首次失败/超时后先查上游任务与账单并重新确认；本轮两张图片均首次成功，无需进入重试闸。
- 真模型成本来自本地估算表；`gpt-5.5-medium` 尚无精确单价，运行时按既有 fallback 估算，因此金额不等于供应商结算单，次数与预算闸记录仍可审计。
