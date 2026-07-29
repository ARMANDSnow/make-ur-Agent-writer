# Iteration 159 - 短剧 Web UIUX Phase B：五站创作台与角色库

## Context

iter158 已完成短剧响应式 11 项导航壳、概览与 production 工作台。本轮依据 Figma D03–D07、D10、T02、M02，在严格复用 `ui-drama` 语义变量、共享组件与响应式断点的前提下，重构五站创作台和角色库，同时保持 episode/step、任务恢复、离开守卫、stale/readiness、手工覆盖与付费角色图保护等既有领域语义。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/iteration_158_drama_web_uiux_phase_a_shell_overview_production.md`, `docs/product/short_drama_module.md`, `src/web/templates.py`, `src/web/static.py`, `src/web/routes.py`, `tests/test_drama_iter088_web.py`, `tests/test_drama_characters_api.py`, `tests/test_drama_web_uiux_phase_a.py`
- `expected_changes`: `src/web/templates.py`, `src/web/static.py`, `tests/test_drama_web_uiux_phase_b.py`, `docs/iterations/iteration_159_drama_web_uiux_phase_b_creation_characters.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: 不修改 `.env`、`小说txt/`、`workspaces/`、`data/`、`outputs/`、`logs/`、私有样本或未跟踪文件；不修改 `ui-public`/`ui-novel`、API、schema、五站状态机、评审 verdict、assembly、计价、授权、付费 receipt、SubmissionUnknown/Lost 或恢复语义；不调用真实文本、图片、视频、TTS provider。

1. 逐一读取 Figma D03–D07、D10、T02、M02 design context，映射到 iter158 的 `ui-drama` 页面壳、断点、语义变量和共享组件。
2. 重构 `/w/{name}/write` 为五站创作台，保留故事设定、钩子设计、分镜脚本、角色设计、评审与组装的领域顺序、episode/step 刷新恢复、五站 job、保存/重生成、离开守卫和 stale/readiness。
3. 重构 `/w/{name}/characters`，清晰区分当前集角色与季角色库，展示锁定、手工覆盖、引用图片、出场集数和生成状态，并保持保存、重绘、逐次授权和付费产物保护。
4. 为 Loading、Empty、Ready、Dirty、Running、Stale、Blocked、Error 提供中文、非颜色且可恢复的页面状态；平板使用阶段横向导航/抽屉，移动使用单列步骤流和固定主操作区。
5. 新增聚焦合同与真实浏览器检查，覆盖 episode/step、`data-leave-guard`、键盘 tabs/steps、job cancel/recovery、手工编辑保护、paid receipt 保护与未知/丢失不重试。

## Acceptance

### Review Context
- `correctness_behavior`: 核对五站顺序与 episode/step 刷新恢复、保存/重生成/五站 job、取消与恢复、leave guard、stale/readiness、评审组装，以及角色季/集分区、锁定/手工覆盖/引用/出场/生成状态和手工/付费产物不可被覆盖。
- `security_boundary`: 核对页面无 prompt、绝对路径、provider response、签名 URL、凭据或内部枚举；不改 API/schema/状态机/计价/授权；真实绘图仍逐次授权，paid receipt 与 SubmissionUnknown/Lost 保持 fail-closed、零自动重试。
- `extra_risk_view`: `Web/UIUX：逐节点对照 D03–D07、D10、T02、M02，在 1440×1024、1024×900、390×844 核对响应式、无横向溢出、44×44 触控、3px 焦点、五站 ARIA/键盘语义、八态文案与固定主操作区`

- A159-01：`/write` 在桌面、平板、移动对齐 Figma，并保留五站领域顺序、episode/step、刷新恢复、五站 job、保存、重生成、任务恢复、离开守卫与 stale/readiness。
- A159-02：五站 tab/step 具备正确 `aria-current`/`aria-selected`、roving `tabindex` 和方向键语义；移动单列步骤流、固定主操作区不遮挡内容。
- A159-03：`/characters` 清晰区分当前集角色与季角色库，并展示锁定、手工覆盖、引用图片、出场集数与生成状态；保存、重绘、逐次授权与付费 receipt 保护不回归。
- A159-04：Loading、Empty、Ready、Dirty、Running、Stale、Blocked、Error 均有中文非颜色表达、具体原因和安全恢复动作；页面不显示 prompt、路径、provider response 或内部枚举。
- A159-05：聚焦测试覆盖 episode/step 刷新恢复、`data-leave-guard`、键盘语义、job cancel/recovery、手工编辑不得被重生成覆盖、paid image receipt 不得被 mock 重绘覆盖、SubmissionUnknown/Lost 不自动重试。
- A159-06：synthetic workspace 覆盖 Empty、Editing、Running、Stale、Blocked、Error；三视口真实浏览器无横向溢出，触控目标不少于 44×44，3px focus ring 可见，键盘路径与 ARIA 正确，证据为 `local-e2e`。
- A159-07：聚焦检查后完成 correctness、security/boundary、Web/UIUX 三路独立只读审查，主线程复核并修复有效 findings；implementation commit 上最后仅运行一次 `bash scripts/verify.sh`，工程结论最多为 `mock-functional`。

## Implementation Notes

- 读取 Figma D03–D07、D10、T02、M02 与全局响应式规范，将桌面左侧五站轨、平板横向阶段轨、移动单列步骤流和固定主操作条落在 iter158 的 `ui-drama` 壳与语义变量上，未复制 token。
- `/write` 新增 episode 工具条、五站 progress summary 与独立“评审与组装”第五站；hash/query、roving tab、`aria-current`/`aria-selected`、active job 恢复、Dirty/Running/Stale/Blocked/Error 投影继续复用既有数据和 job API。
- 分镜编辑器不再渲染绘图 prompt 控件；保存时从已加载的安全内存对象保留原字段，避免无意清空 schema 值。角色表同样不把 LoRA/SD prompt 放入 DOM，保存时保留原值。
- `/characters` 增加 episode 刷新恢复与跨导航同步，按 appearances 分出当前集角色和季角色库；角色分组后的收集按原始索引排序，避免视觉重排导致人物写错位。
- 角色卡显示锁定、手工覆盖、引用图片、出场集数与生成状态；本地预览/真实参考图区分和服务端付费凭据保护未改变。前序分镜未完成时以中文 Blocked 卡和恢复入口呈现。
- 聚焦回归：56 tests 通过（Phase A/B、characters API、iter088 Web、storyboard grid、前端 bundle Node syntax），`check_agent_harness.py` 与 `git diff --check` 通过。
- synthetic mock 浏览器链路依次完成 Empty/Blocked → 故事设定 → 钩子选择 → 分镜 → 角色 Ready；1440×1024、1024×900、390×844 均无横向溢出、可见交互目标不小于 44px，方向键切站后 `aria-selected`/`aria-current` 同步且 focus ring 为 3px。
- 三路只读审查结论：correctness 发现 episode 2+ 角色分组/active job 串集与站④按钮文案 3 项；security/boundary 发现 skipped raw enum 与“agent 建议”2 项；Web/UIUX 发现隐藏 Running 恢复卡、select/textarea 触控/焦点、skipped/stale、离开守卫、移动主操作 5 项。主线程逐项复核后全部修复，并补充聚焦合同；无未修高风险 finding。

## Acceptance Result

- A159-01：通过。`/write` 在三档壳内保留五站领域顺序、episode/step 刷新恢复、五站任务、保存/重生成、离开守卫及 stale/readiness；站⑤评审与组装已与站④角色设计分离。
- A159-02：通过。五站使用 roving `tabindex`、`aria-selected` 与 `aria-current="step"`，方向键可切站；桌面为阶段侧轨、平板为横向阶段轨、移动为单列步骤流和固定主操作区。
- A159-03：通过。`/characters` 按当前集与季角色库分区，显示锁定、手工覆盖、引用图片、出场集数和生成状态；episode-specific job 恢复、手工字段保留、逐次授权与 paid receipt 防覆盖语义未改变。
- A159-04：通过。Loading、Empty、Ready、Dirty、Running、Stale、Blocked、Error 均有中文非颜色投影和恢复动作；页面 DOM 不展示 prompt、LoRA、绝对路径、provider response、签名 URL或内部枚举。
- A159-05：通过。Phase A/B、角色 API、iter088 Web、storyboard grid 与前端 bundle 聚焦回归共 56 tests 通过；另对第五站兼容契约做 10 项定向回归。覆盖 episode/step、leave guard、任务恢复、手工编辑与付费图片保护、unknown/lost 零自动重试。
- A159-06：通过。synthetic mock 链覆盖 Empty/Blocked、Editing、Running、Stale、Error 与最终 Ready；1440×1024、1024×900、390×844 均无横向溢出，可见交互目标不小于 44px，focus ring 为 3px，键盘切站后 ARIA 同步。该浏览器证据记为 `local-e2e`。
- A159-07：通过。correctness、security/boundary、Web/UIUX 三路独立只读审查分别发现 3、2、5 项有效 finding；主线程全部复核修复并完成聚焦回归，无剩余已知高风险 finding。
- Canonical：accepted implementation commit `9ffbb13f23d4a9b46ca58a4795be4a91cd210321` 上 `bash scripts/verify.sh` exit 0；schema v2，15 steps，**2989 tests OK**，487 秒，run `5fdb0c215e0e44a09104e7f61465649b`，`tracked_scope_clean=true`，`verification_profile=canonical-mock-offline`。
- 验收运行说明：首次受限沙箱运行的 24 个 error 均为 loopback `socket.bind` EPERM，同时捕获 2 个旧四站文案契约；第二次获批运行再捕获 1 个旧“站④后直接评审”兼容契约。更新 implementation commit 后按相同 mock/offline 配置完整重验通过；这些均未触发真实 provider。
- 最终结论：工程验收为 `mock-functional`；三视口浏览器证据为 `local-e2e`。本轮未调用真实文本、图片、视频或 TTS provider，不是 `provider-validated`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮是既有短剧 Web 壳和既有领域语义上的页面实现，没有产生需要提升为长期工程规则的新决策。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/templates.py` | 重构五站创作台与角色库页面骨架、episode 工具条、状态区和移动主操作。 |
| `src/web/static.py` | 实现五站导航/进度/评审站、角色集季分区、安全字段保留、响应式与无障碍行为。 |
| `src/web/routes.py` | 角色库页面接收并校验 episode 上下文。 |
| `tests/test_drama_web_uiux_phase_b.py` | 新增 Phase B 页面、恢复、边界、响应式和保护合同。 |
| `docs/iterations/README.md` | 追加 iter159 索引。 |
| `docs/iterations/iteration_159_drama_web_uiux_phase_b_creation_characters.md` | 记录计划、实施、审查与验收。 |

## 不在本轮范围

- 不重构资产治理、镜头图片/视频、合成交付、剧集、Insights 或 Jobs 主体页面。
- 不修改后端 API、schema、五站状态机、评审 verdict、assembly、计价、授权或 paid receipt 语义。
- 不调用真实 provider，不写入 Figma，不修改 `ui-public`/`ui-novel`。

## Notes

- 计划提交信息：`docs(iter159): 迭代计划 159 立项（短剧 Web UIUX Phase B）`。
