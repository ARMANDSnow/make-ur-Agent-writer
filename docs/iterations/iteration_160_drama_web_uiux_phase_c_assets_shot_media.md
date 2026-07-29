# Iteration 160 - 短剧 Web UIUX Phase C：资产治理与逐镜媒体候选

## Context

iter158 已完成短剧响应式 11 项导航壳、概览与 production，iter159 已完成五站创作台与角色库。本轮依据 Figma D11-D13、T04、M04，继续复用 `ui-drama` 页面壳、语义变量、共享组件和响应式断点，重构资产治理、镜头图片与镜头视频页面；现有安全投影仍是 used-by、impact、coverage、continuity 与 stale 的唯一真源。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_159_drama_web_uiux_phase_b_creation_characters.md`, `docs/product/short_drama_module.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `tests/test_drama_asset_web.py`, `tests/test_drama_shot_image_web.py`, `tests/test_drama_shot_video_web.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_web_uiux_phase_c.py`, `docs/iterations/iteration_160_drama_web_uiux_phase_c_assets_shot_media.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、私有样本或未跟踪文件；不修改 `ui-public`/`ui-novel`、asset schema、candidate manifest、CAS、attempt receipt、provider capability、付费授权、零重提、API 或领域状态语义；不调用真实文本、图片、视频、TTS provider。

1. 读取 Figma D11-D13、T04、M04 design context，映射桌面分栏、平板详情抽屉和移动“需处理优先”单列候选卡到既有 `ui-drama` 结构。
2. 重构 `/assets`，按角色、场景、道具、线索、美术方向呈现 selected version、scope、used-by、impact、active/disabled、stale/blocked 与安全原因，继续只消费现有治理投影。
3. 重构 `/shot-images`，按镜头呈现首帧/尾帧、当前选择、历史候选、stale lineage、缺失引用及 exact preview/CAS select/clear/安全重绘入口。
4. 重构 `/shot-videos`，分层呈现 first/tail/previous-tail 输入、candidate/attempt/coverage/continuity/degraded preview，并保留 exact selection、clear、恢复和安全预览。
5. 覆盖 Empty/Ready/Stale/Blocked、Missing/Selected/Degraded/Unknown 等状态；完成三视口、键盘、ARIA、44px、3px focus、无横向溢出及敏感字段不暴露验证。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 episode 切换、selection revision/current binding、selected 始终可见、stale candidate 只读、exact select/clear/recovery，以及 SubmissionUnknown/Lost 零自动 submit。
- `security_boundary`: 核对资产 mutation 的 JSON/intent/same-origin/workspace lock、preview 不暴露 raw provider URL，oversize/web_unverified 可安全 clear，页面不显示 hash、绝对路径、provider task ID、签名 URL或内部错误。
- `extra_risk_view`: `Web/UIUX/媒体预览：逐节点对照 D11-D13/T04/M04，在 1440×1024、1024×900、390×844 检查分栏/抽屉/需处理优先卡、44px、3px focus、完整键盘路径、安全派生预览与非颜色状态表达`

- A160-01：`/assets` 在三视口清晰呈现五类资产、selected version、scope、used-by、impact、active/disabled、stale/blocked 与具体原因，且所有判断来自既有安全投影。
- A160-02：`/shot-images` 按镜头呈现首尾帧、当前/历史候选、stale lineage 和缺失引用；保留 exact preview、CAS selection、clear 和安全重绘，stale 候选只读且 selected 始终可见。
- A160-03：`/shot-videos` 分层呈现 first/tail/previous-tail、candidate、attempt、coverage、continuity、degraded preview；保留 exact selection、clear、恢复与安全预览。
- A160-04：episode、selection revision/current binding、unknown/lost 零重提和资产 mutation 守门均不回归；不修改 schema、manifest、receipt、capability、计价或授权语义。
- A160-05：资产 Empty/Ready/Stale/Blocked，图片 Missing/Selected/Stale/Blocked，视频 Missing/Selected/Degraded/Unknown/Blocked 均有中文非颜色原因与安全动作。
- A160-06：三视口无横向溢出，触控目标不少于 44×44，3px focus ring 与完整键盘操作可见；页面不显示 hash、绝对路径、provider task ID、签名 URL、raw provider URL 或内部错误。
- A160-07：聚焦检查后完成 correctness、security/boundary、Web/UIUX/媒体预览三路独立只读审查，修复有效 findings 后在 implementation commit 上运行 canonical `bash scripts/verify.sh`；最终工程结论最多为 `mock-functional`。

## Implementation Notes

- 读取 Figma D11 `40:269`、D12 `40:336`、D13 `40:416`、T04 `45:148`、M04 `46:117`，将桌面主从分栏、平板横向选择器和移动单列“需处理优先”映射到既有 `ui-drama` 壳；未复制 token，也未触碰 `ui-public`/`ui-novel`。
- `/assets` 改为角色、场景、道具/线索、美术方向四组入口和六段服务端治理投影，展示当前版本、作用域、冻结引用数量、切换影响、启用/停用与 stale/blocked 原因；mutation 继续使用 JSON、intent、same-origin、workspace lock 与原有 revision 校验。
- `/shot-images` 改为镜头主从浏览、首尾帧关系、当前/历史候选、对比与 CAS 选择/清除；“只看需处理”仍保留当前已选镜头，空状态返回链接保留 episode 2+ 上下文。
- `/shot-videos` 分层展示候选、attempt、coverage、continuity、降级预览与 exact selection/clear；当前安全投影未包含具体 first/tail/previous-tail 绑定时明确不在前端推断，SubmissionUnknown/Lost 仍保持零自动重提。
- 只把 section/item/version/shot/candidate 的序号写入 DOM，真实 ID 与 revision 仅保留在内存投影中；图片和视频预览经同源 endpoint 读取后以 `blob:` URL 挂载，页面 DOM 不出现内部 ID、fingerprint 前缀或预览路径。
- 聚焦回归：Phase A/B/C、assets、shot image、shot video、GET routes、web server、image/video clients 与 production workbench 共 207 项通过，11 项按既有条件跳过；另有 Phase C 聚焦 50 项通过。JS 语法、Python 语法与 `git diff --check` 通过。
- 浏览器复核覆盖 1440×1024、1024×900、390×844 三视口的 assets、shot-images、shot-videos：9 组均无横向溢出且无小于 44×44 的可见交互目标；桌面为 `330px + detail`，平板/移动为单列；键盘 ArrowDown 同步焦点、`aria-selected` 与唯一详情面板，focus ring 为 3px solid；图片自动安全预览与视频按需预览均只挂载 `blob:` URL。
- 三路只读审查结论：correctness 指出 episode 空状态上下文和已选图片筛选问题；security/boundary 指出 DOM ID/preview URL 暴露风险；Web/UIUX/媒体预览指出 category tab 语义不完整、视频输入关系存在前端推断和 continuity 缺少公共镜头定位。上述 findings 均已修复并完成聚焦回归；主线程复核未发现遗留高风险项。

## Acceptance Result

<iter-finish 回填。>

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 待收官复核。

## 文件变更汇总

<实施后回填。>

## 不在本轮范围

- 不重构 compose、episodes、insights 或 jobs 主体页面。
- 不修改 asset/candidate/attempt/provider 领域协议、API、计价、授权或零重提语义。
- 不调用真实 provider，不写入 Figma，不修改 `ui-public`/`ui-novel`。

## Notes

- 计划提交信息：`docs(iter160): 迭代计划 160 立项（短剧 Web UIUX Phase C）`。
