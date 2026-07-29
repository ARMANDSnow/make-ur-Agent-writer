# Iteration 161 - 短剧 Web UIUX Phase D：合成交付、剧集、数据与任务收口

## Context

iter158-160 已完成短剧响应式页面壳、概览、production、五站创作台、角色库、资产治理及逐镜媒体候选。本轮依据 Figma Phase D 桌面、平板与移动设计，继续复用 `ui-drama` 壳、语义变量、共享组件与响应式断点，重构 compose、episodes、insights、jobs 并完成短剧全站一致性收口；timeline/QA/delivery、episode freshness、pricing/lifecycle 与 job recovery 的现有安全投影仍是唯一真源。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_160_drama_web_uiux_phase_c_assets_shot_media.md`, `docs/product/short_drama_module.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `src/web/drama_insights.py`, `src/web/jobs.py`, `tests/test_drama_compose_web.py`, `tests/test_drama_episodes_api.py`, `tests/test_drama_iter088_web.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_web_uiux_phase_d.py`, `docs/iterations/iteration_161_drama_web_uiux_phase_d_delivery_episodes_insights_jobs.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、私有样本或未跟踪文件；不修改 `ui-public`/`ui-novel`、compose/timeline/QA/delivery schema、任务 DAG、pricing facts、lifecycle、恢复、API、计价或付费授权语义；不调用真实文本、图片、视频或 TTS provider。

1. 读取 Figma Phase D 的 compose、episodes、insights、jobs 桌面节点及对应平板/移动节点，映射到现有 `ui-drama` 结构并复核 Phase A-C 跨页一致性。
2. 重构 `/compose`，分层呈现 timeline readiness、compose job、QA、字幕修订与 exact delivery，保留本地合成、取消、恢复、四类 exact download 和交付保留语义。
3. 重构 `/episodes`，呈现整季进度、单集状态、评审、时长、episode 入口、下一集创建、季快照、master/package 与 freshness。
4. 重构 `/insights`，区分创作、媒体、任务、费用与 known/unknown，不把未知费用、成功率或生命周期时间纳入确定统计。
5. 重构 `/jobs` 短剧视图，区分 active、terminal、blocked、lost、submission unknown，保留取消、刷新、恢复及安全日志投影。
6. 用 synthetic workspace 覆盖创作→production→local demo→compose→delivery，并完成全站导航、空状态、错误卡、状态词、焦点、触控、ARIA 与响应式一致性清理。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 exact delivery 下载重新验证当前字节、stale timeline/QA 不可交付、episode 2+ 路由、Insights known/unknown 分母、active job 离开守卫及 lost/unknown 零自动重试。
- `security_boundary`: 核对 compose/download/job mutation 的 JSON/intent/same-origin/workspace lock 与 exact identity，任务日志和页面不泄露 prompt、路径、凭据、provider response、task ID、签名 URL或内部错误。
- `extra_risk_view`: `Web/UIUX 与 runner/recovery：逐节点对照 Figma，在 1440×1024、1024×900、390×844 检查状态分层、键盘/ARIA、44px、3px focus、无横向溢出、取消/恢复/持久 job 与 synthetic A-F→delivery 路径`

- A161-01：`/compose` 在三视口呈现 Missing、Ready、Running、Stale、Blocked、Failed、Complete，并保持 timeline/QA/current bytes fail-closed、本地合成、取消、恢复、字幕 CAS、四类 exact delivery 与保留语义。
- A161-02：`/episodes` 清晰呈现整季进度、单集状态、评审、时长和 episode 入口；下一集、季快照、master/package 与 episode freshness 保持，episode 2+ 上下文不丢失。
- A161-03：`/insights` 区分创作、媒体、任务、费用与 known/unknown；未知费用、成功率与生命周期时间不进入确定性统计。
- A161-04：`/jobs` 区分 active、terminal、blocked、lost、submission unknown；取消、刷新、恢复与安全日志投影保持，lost/unknown 不自动重试。
- A161-05：短剧全站 Loading、Empty、Ready、Running、Stale、Blocked、Failed、Lost、Complete 使用一致中文非颜色状态、恢复动作、导航和 leave guard；页面不显示内部枚举或敏感实现字段。
- A161-06：compose、episodes、insights、jobs 在 1440×1024、1024×900、390×844 无横向溢出，可见触控目标不少于 44×44，3px focus ring、ARIA 与键盘路径完整；Phase A-D 跨页面视觉/兼容回归通过。
- A161-07：synthetic workspace 完成创作→production→local demo→compose→delivery；exact download、stale/unknown/blocked 与 job recovery 重点回归通过。
- A161-08：聚焦检查后完成 correctness、security/boundary、Web/UIUX、runner/recovery 四路独立只读审查，修复有效 findings 后在 implementation commit 上运行 canonical `bash scripts/verify.sh`；最终工程结论最多为 `mock-functional`。

## Implementation Notes

<实施后回填。>

## Acceptance Result

<iter-finish 回填。>

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 待收官复核。

## 文件变更汇总

<实施后回填。>

## 不在本轮范围

- 不修改 compose/timeline/QA/delivery、episode、task DAG、pricing 或 lifecycle 领域协议。
- 不新增 provider adapter、平台发布、真实 TTS、真实逐镜媒体或公网交付能力。
- 不调用真实 provider，不写入 Figma，不修改 `ui-public`/`ui-novel`。

## Notes

- 计划提交信息：`docs(iter161): 迭代计划 161 立项（短剧 Web UIUX Phase D）`。

