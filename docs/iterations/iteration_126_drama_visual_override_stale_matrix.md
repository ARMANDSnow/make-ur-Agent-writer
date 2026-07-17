# Iteration 126 - 短剧 Visual Override 与 Stale 依赖矩阵

## Context

iter125 已完成 F2 同源 ASS 与通用可编辑工程，canonical 基线为 2514 tests OK。A-J 实时 SOP 中 A2 仍缺通用 visual-only override 以及可执行的依赖传播矩阵，导致 camera、lighting、negative prompt、transition 等后期视觉调整只能回写创作事实或由各媒体节点自行猜 stale。本轮完成 A2 单一闭环，不调用媒体 provider。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_106_drama_render_plan_stale_boundary.md`, `src/drama_schemas.py`, `src/drama_render_plan.py`, `src/drama_render_store.py`, `src/drama_art_direction_store.py`, `tests/test_drama_render_store.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_visual_overrides.py`, `tests/test_drama_visual_overrides.py`, `docs/iterations/iteration_126_drama_visual_override_stale_matrix.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`, `docs/product/short_drama_module.md`
- `do_not_touch`: `.env`、`小说txt/`、用户未跟踪体检报告和私有 workspace；不把剧情、对白、角色增删放进视觉 override；不调用图片/视频/TTS provider，不 push

1. 定义 visual-only override 白名单与严格 schema：camera、lighting、negative prompt、transition；每个候选不可变、content-addressed，选择使用 revision/current-ID 双 CAS。
2. 建立 episode/shot scoped catalog 与 selected effective manifest；只绑定当前 fresh RenderPlan 的稳定 shot ID，拒绝剧情、对白、角色、绝对路径、prompt/provider 响应等越界字段。
3. 实现安全原子持久化、fresh/stale/invalid/blocked_source 检查与显式 stale reconcile；未选候选不使下游 stale，selected 变化只影响真实依赖。
4. 固化版本化 stale dependency matrix：creative revision、visual override 各字段、BGM selection、selected first frame 的受影响节点与 shot/episode scope 可确定投影。
5. 审查与 canonical 后，独立做至多一次 scope-specific 真文本协议校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: 候选/选择/有效 manifest 字节稳定；双 CAS 阻断 stale/ABA；未选候选不 stale；camera/lighting/negative prompt 与 transition 的依赖集合不同且 shot scope 精确
- `security_boundary`: strict extra-forbid、长度/数量/hash/path 边界；只接受 fresh RenderPlan 的稳定 shot ID；symlink/FIFO/目录、坏 JSON/hash、并发目标替换、锁异常和越界创作字段 fail closed
- `extra_risk_view`: 资产/媒体血统，核对 override 不改 creative episode、source fingerprint 与 selected revision 可追溯，BGM/first-frame/creative change 的传播表不漏 composite/QA 且不误伤无关图片/音频

- **A126-01**：四类 visual-only override 有严格、content-addressed 候选和双 CAS 选择；剧情、对白、参与角色等变化仍必须回创作层。
- **A126-02**：effective manifest 绑定 exact fresh RenderPlan/shot/source 与 selected refs；未选候选不改变 manifest，selected 变化按字段与镜头精确改变 fingerprint。
- **A126-03**：catalog/manifest 安全原子落盘并可重建重验；损坏、路径/文件类型、并发替换、stale RenderPlan 与伪造 fingerprint fail closed。
- **A126-04**：版本化依赖矩阵覆盖 creative revision、visual override、BGM selection 与 selected first frame，明确 affected nodes、scope 和不受影响节点。
- **A126-05**：聚焦回归与 correctness/security/media-lineage 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内，图片/视频/TTS 为 0。

## Implementation Notes

- 在 `drama_schemas` 固化四字段 visual-only spec、不可变 content-addressed version、canonical catalog、effective manifest、selection impact/transition/result 与 `drama-stale-matrix-v1`。所有纯函数入口都重建 typed model，防止 `validate_assignment=False` 的对象突变绕过 hash 与语义校验。
- 新增 `drama_visual_overrides`：candidate append、revision/current-ID 双 CAS selection、fresh/stale/invalid/blocked_source inspect、显式 reconcile，以及 nofollow/dirfd/fsync 原子 state writer。writer 同时使用同次严格读取的目标 bytes token，并在 replace 前后重验 RenderPlan token；坏 JSON、重复键、NaN、symlink/FIFO/目录、锁异常与并发替换全部 fail closed。
- selection mutation 与最多 512 条的 content-addressed receipt ledger 同文件提交；receipt 以 before/after manifest 证明单镜头 old→new，所有快照版本精确绑定 append-only catalog。丢失响应可按旧 CAS 请求零写恢复，ack 显式删除；ledger 满额拒绝新 selection。`target_current/superseded/no_op` 表达当前目标状态，不把 ABA 等同于未被覆盖。
- v1 矩阵把 creative revision、camera/lighting/negative prompt、剪辑 transition、BGM selection、selected first frame 投影到 A-F 精确节点；字段清空与多字段切换取 old/new 差异并集，未选候选不传播。
- 审查阶段先后修复 typed model mutation、catalog 排序、调用方伪造影响节点、字段清空漏传播、target/RenderPlan TOCTOU、锁错误泄露、receipt 丢失恢复、历史 receipt 混绑、连续 receipt 断链与 ABA 命名歧义。最终聚焦回归覆盖 65 个 visual/render/edit tests，另有 iter126 专项 23 tests，静态编译、harness 与 `git diff --check` 通过。

## Acceptance Result

<iter-finish 回填测试数、canonical、真模型校准、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: A2 固化了 visual-only 白名单、selection old/new diff、transition 剪辑层语义与跨 C-F 的长期 stale 矩阵，必须进入 A-J 产品 SOP 真源。

## 文件变更汇总

- `src/drama_schemas.py`：A2 override、receipt 与 stale matrix strict schemas。
- `src/drama_visual_overrides.py`：纯函数、持久化、inspect/reconcile、selection/ack/recovery 与依赖分类实现。
- `tests/test_drama_visual_overrides.py`：A2 功能、安全、并发、伪造、恢复与矩阵回归。
- `docs/product/short_drama_module.md`：提升 A2 长期 SOP 与 v1 矩阵。
- `docs/iterations/{README.md,iteration_126_drama_visual_override_stale_matrix.md}`：迭代索引与审计记录。
- `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md`：canonical 后同步当前快照与阶段记忆。

## 不在本轮范围

- Web override 编辑器、特定图片/视频 provider adapter、质量比较、BGM 素材生成、通用任务 DAG。
- TTS、真图片、真视频、episode 2+ 真媒体与特定 NLE adapter。

## Notes

- 真文本协议校准与 `iter-finish` 的 mock canonical 分离，凭据只在临时进程内注入。
