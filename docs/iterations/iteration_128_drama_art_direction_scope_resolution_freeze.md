# Iteration 128 - 短剧美术方向多 Scope 解析与冻结

## Context

iter127 已完成阶段 B1 的跨集 Used-By 与非破坏停用治理。阶段 B 仍缺 Episode > Series > Global 的 ArtDirection scope resolution：当前只有 season catalog，无法为单集显式覆盖，也无法证明 fallback 来源、优先级变化和 RenderPlan stale。Web 管理依赖稳定的领域协议，因此本轮先完成 B2 纯本地多 scope 解析/冻结，不做 UI 或真实图片。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_art_direction_store.py`, `src/drama_render_store.py`, `tests/test_drama_art_direction_store.py`, `tests/test_drama_render_store.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_art_direction_store.py`, `src/drama_render_store.py`, `tests/test_drama_art_direction_scope.py`, `docs/iterations/iteration_128_drama_art_direction_scope_resolution_freeze.md`, `docs/iterations/README.md`, `docs/product/short_drama_module.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、用户未跟踪体检报告和私有 workspace；不建立跨 workspace 可写 registry，不调用图片/视频/TTS provider，不 push

1. 定义 workspace 内受控的 Global、season Series 与 episode scope；Global 只作为本 workspace 的默认美术方向，不越过 workspace 边界。每个 scope 使用 strict、content-addressed catalog/selection，作用域 identity 进入 fingerprint。
2. 提供确定性的 Episode > Series > Global resolver；缺失低优先级 scope 可降级，最高命中 scope invalid/orphan 时 fail closed，不能静默跳到较低层；scope `enabled=false` 是显式 clear 并可审计地 fallback，区别于 B1 非破坏 lifecycle `disabled`。解析结果冻结 exact version、source scope 与 source selection fingerprint。
3. 将 RenderPlan create/inspect/rebuild 接入 scoped resolution；新增高优先级 override、选择变化、scope clear 或恢复必须产生可解释 stale/fallback，未选候选不 stale。
4. 所有 scope mutation 使用 workspace lock、target token 与 revision/current-ID 双 CAS；episode override 的清除也要 guarded，历史 RenderPlan 继续可读但不能冒充 fresh。
5. 审查与唯一 canonical 后，至多一次 scope-specific 真文本协议校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: Episode > Series > Global 优先级、fallback/clear、exact version 冻结与 RenderPlan stale 确定；旧 season-only workspace 兼容，未选候选不产生误 stale
- `security_boundary`: scope/season/episode identity、路径、catalog/envelope、strict int 与容量有界；symlink/FIFO/目录/坏 JSON/目标竞态 fail closed，workspace/global 名义不能越界
- `extra_risk_view`: ArtDirection/RenderPlan 血统专项，复核高优先级坏源不降级、disabled 与 clear 的 stale 语义、跨 episode/season 不串绑

- **A128-01**：三 scope identity、catalog 与 resolution schema strict、content-addressed、稳定排序，workspace-local Global 不越界。
- **A128-02**：resolver 严格执行 Episode > Series > Global；合法缺失 fallback，高优先级 invalid/orphan fail closed；scope `enabled=false` 作为显式 clear 可审计地 fallback，B1 lifecycle `disabled` 继续遵守历史读取不破坏、禁止新冻结的既有契约。
- **A128-03**：RenderPlan 冻结 resolved scope/exact version/source selection/scope revision；override/selection/scope clear/恢复精确 stale，未选候选不 stale，旧 season-only workspace 可迁移。
- **A128-04**：scope mutation 与 clear 使用双 CAS、nofollow 原子落盘和 precommit 重验；坏源、特殊文件及并发替换不覆盖旧字节。
- **A128-05**：聚焦回归与 correctness/security/art-lineage 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内，图片/视频/TTS 为 0。

## Implementation Notes

- 新增 `ScopedArtDirectionCatalog` 与 `ArtDirectionResolution`：Global/Episode catalog 将 scope identity、selection revision、activation revision 纳入 content address；resolution 显式保存 source scope、exact ref、selection/scope revision，并由 schema 重算 selection/resolution fingerprint。
- 新建 `src/drama_art_direction_scope.py`，复用既有 Series catalog，按 Episode > Series > workspace-Global 解析。resolver 对三层源执行 before/after content-token 快照复查；高层 missing→present 竞态、坏源和路径异常均 fail closed。`enabled=false` 是 guarded clear/fallback，不与 B1 lifecycle `disabled` 混同。
- RenderPlan create/inspect/rebuild 冻结完整 resolution。未选候选只改变 catalog bytes、不改变 selection revision，因此不 stale；选择、select-away/back、clear/re-enable 与优先级变化均精确 stale。旧 season-only plan 的 legacy fingerprint 仍可读取，但必须显式 rebuild 才恢复 fresh。
- scoped create/append/select/clear/re-enable 使用 workspace lock、target token、revision/current-ID CAS、nofollow 原子替换和 precommit 重验。Episode retirement guard 从 catalog season 派生；Global guard 安全枚举并检查全部已知 canonical season ledger，且初建 enabled catalog 也不能复用 disabled exact version。
- B1 usage inventory 扩展到 Global/Episode ArtDirection catalog；source snapshot 保留 scope，重复 exact identity 若 fingerprint 冲突则 blocker。为兼容新嵌套 resolution，同步修正 iter127 的跨集伪造测试夹具。
- 聚焦 sanity：83 项 assets/art-direction/render/usage 回归通过；受影响文件 `py_compile`、`git diff --check` 与 agent harness 通过。初审 correctness 1 个 P2、security 2 个 P2、lineage 2 个 P1 + 1 个 P2，主线程合并为一致性快照、season 治理、初建 retirement guard、显式 revision lineage 四类有效问题并修复；三视角复审代码无 P0/P1/P2，lineage 最后两项 docs/test 收官 finding 亦已补齐。

## Acceptance Result

- **结论**：本轮五项 Acceptance 全部通过。交付级别为 `mock-functional` / `canonical-mock-offline`；mandatory local-drama 子步骤为 `local-e2e`，`provider_validated=false`。独立 scope-specific 文本证据记为 `provider-validated-local-calibration`，不提升全项目等级。
- **A128-01**：通过；Global/Episode scoped catalog、Series 兼容层与 resolution 均 strict、content-addressed，workspace/season/episode identity 与路径隔离有专项回归。
- **A128-02**：通过；Episode > Series > Global、合法缺失 fallback、坏高层 fail closed、scope clear/fallback 与 lifecycle disabled 分离均成立；三层 source token 前后复查阻断 missing→present 竞态。
- **A128-03**：通过；RenderPlan 显式冻结 scope、exact ref、selection/scope revision 与双 fingerprint；未选候选不 stale，selection/clear ABA 精确 stale，旧 season-only plan 可读并要求显式 rebuild。
- **A128-04**：通过；scoped create/append/select/clear/re-enable 具 workspace lock、target CAS、revision/current-ID CAS、nofollow 原子写与 precommit 重验；Episode retirement 绑定 catalog season，Global 检查全部已知 canonical ledger。
- **A128-05**：通过；聚焦 sanity、correctness/security/art-lineage 三视角、唯一 canonical 与一次真文本校准均在授权和 cap 内完成。
- **实现提交**：`adcc3efb02a8b74292b134457024cb0e5e6c0127`，tree `696a5236dc8fbbaf726544d58374324e1c30c774`，`tracked_scope_clean=true`。
- **唯一 canonical**：`bash scripts/verify.sh` exit 0；2561 tests OK，15 steps，310 秒，run `68216a338c0147109202fc2cbfcb43ae`；local drama E2E passed，mock preflight 0 FATAL / 0 WARN。
- **聚焦与审查**：相关 assets/art-direction/render/usage 83 tests、受影响文件 `py_compile`、harness 与 diff check 均通过。初审确认并修复 resolver 非一致快照、caller-controlled governance season、初建 retirement guard 缺失和 revision lineage 不透明四类问题；补充 clear/re-enable ABA 与内层 fingerprint 防伪后，三路最终复核无遗留 P0/P1/P2。
- **真文本校准**：获用户本轮明确授权后只读取桌面 `key.rtf` 的 key，向指定 HTTPS endpoint 发起 1 次 `gpt-5.5-medium` 请求；HTTP 200，275 tokens，3.980 秒，严格 JSON keys 与协议 verdict 均通过。临时脚本已删除，未打印 key 或响应正文。iter125-128 累计保守计 5/60 请求、4 次模型成功、预留 ¥0.40；图片 0/20、视频 0、TTS 0。未找到用户提及的 `sd_real_max.md`，因此未推断或执行任何图片配置。
- **边界/未修风险**：未实现资产 Web 管理、物理 GC、跨 workspace registry 或真实图片/视频/语音；当前 episode artifact namespace 仍以单 workspace/season 1 主链为产品边界，多季模型未闭环。cooperative atomicity 依赖项目 writer 遵守 workspace lock。四份用户未跟踪体检报告未读取、未修改、未暂存。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: 多 scope 优先级、scope clear 与 lifecycle disabled 的区分、revision 冻结及跨 season retirement guard 是阶段 B 后续 Web/媒体入口必须共同遵守的长期产品协议，不能只留在单轮审计记录。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 scoped ArtDirection catalog/resolution，并扩展 RenderPlan 与 usage source schema |
| `src/drama_art_direction_scope.py` | 新增 Global/Series/Episode 解析、mutation、CAS、retirement 与一致性快照边界 |
| `src/drama_render_plan.py`、`src/drama_render_store.py` | 冻结 resolution，提供 stale/legacy migration 与 precommit 重验 |
| `src/drama_asset_usage.py` | scoped catalog exact-version inventory 与 workspace-global retirement guard |
| `tests/test_drama_art_direction_scope.py` | 新增优先级、clear/ABA、legacy、retirement、竞态与特殊文件测试 |
| `tests/test_drama_render_store.py`、`tests/test_drama_asset_usage.py` | 更新既有竞态/跨集夹具并覆盖 scoped inventory |
| `docs/product/short_drama_module.md` | 晋升 B2 长期产品协议 |
| `docs/iterations/README.md`、本文件 | 注册 iter128 并记录实施/审查/验收证据 |

## 不在本轮范围

- ArtDirection Web 面板、AI suggestion、真实图片质量比较、跨 workspace/global registry。
- 角色/场景/道具的多 scope、资产物理 GC、通用归档、视频与 TTS。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；本轮 implementation commit 先于唯一 canonical。
