# Iteration 119 - 短剧逐镜视频连续性与合成门禁

## Context

iter118 收官基线为 2393 tests OK；D1-D3 已完成逐镜视频计划、候选选择、整集 coverage 与 once-only attempt 恢复，但阶段 F 尚缺少一个只消费 fresh production selections 的确定性连续性与合成前门禁。本轮落实 A-J 路线图的 D4 纯本地闭环，不调用真实媒体 provider。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `docs/iterations/iteration_117_drama_shot_video_provider_capability_attempt_recovery.md`, `src/drama_schemas.py`, `src/drama_shot_video.py`, `src/drama_shot_video_candidates.py`, `tests/test_drama_shot_video_candidates.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_shot_video_continuity.py`, `tests/test_drama_shot_video_continuity.py`, `docs/iterations/README.md`, `docs/iterations/iteration_119_drama_shot_video_continuity_compose_gate.md`
- `do_not_touch`: `.env`、`key.rtf`、用户未跟踪体检报告、私有 `data/outputs/logs/workspaces` 内容与 `小说txt/`；不接真实视频、不新增 Web mutation、不改 episode 1 高光兼容入口、不 push

1. 建立内容寻址的 `ShotVideoContinuityReport`，把 D2 coverage、相邻首尾帧 lineage、角色/场景版本变化与镜头方向性风险投影为有界结果。
2. 建立 compose-readiness gate：只有 fresh production coverage 且无硬连续性问题才 ready；placeholder 只能 `degraded_preview`；missing/stale/invalid/blocked 均 fail closed。
3. 保持单镜 stale 的精确传播与 episode 2+ 隔离；不以目录最新文件或 episode 1 常量推断选择。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 D2 coverage 到 D4 状态映射、相邻 previous-tail lineage、selected exact candidate、单镜 stale 传播、placeholder 降级和 episode 2+ 隔离
- `security_boundary`: 核对所有输入有界严格、路径/哈希只来自既有验证 schema、错误不暴露本地路径或候选内容、全程零网络且不读取私有 workspace
- `extra_risk_view`: `media-continuity`，核对角色/场景 exact version 变化、首尾帧连续性、镜头方向告警与 compose gate 不产生假阳性 ready

- **A119-01**：相同 D1 plan 与 D2 manifest 重复生成 byte-stable D4 report；所有 production selection fresh 时 compose ready。
- **A119-02**：missing、stale、invalid artifact、blocked source 均阻断；仅 placeholder 时明确 `degraded_preview` 且不得 production compose。
- **A119-03**：previous-tail lineage 必须与相邻源镜尾帧完全一致；角色/场景 exact version 或明显方向性变化产生确定性 warning，不自动篡改选择。
- **A119-04**：单镜请求变化只影响该镜和直接 lineage dependent；episode 2+ 的 identity、路径与报告不含 episode 1 特判。
- **A119-05**：聚焦检查与三视角只读审查无未处理 P0/P1/P2；implementation commit 上唯一一次 `bash scripts/verify.sh` 通过并保持 `mock-functional`。

## Implementation Notes

- 新增纯 D4 report 与唯一公开的 workspace-aware production gate；后者在同一 workspace flock 内完成 fresh plan、manifest、selected MP4 实体校验与 report 投影。
- report 绑定有序 selected request/revision/candidate/artifact SHA，而不是整个 append-only manifest；因此 selection CAS 会使下游 stale，未选候选追加不会误伤。
- 三视角初审发现并修复 global stale 假 ready、artifact 声明自证、未绑定 selection、输入集合无界、公开纯 gate 易误用和 lock/CAS 竞态；修复后 31 项 D2/D4 聚焦回归通过，三路复核无遗留 P0/P1/P2。
- clean-room 借鉴阶段计划中的连续性与 guarded selection 思路；未复制外部实现，未接网络或 provider。

## Acceptance Result

- **A119-01 PASS**：相同 D1/D2 facts 生成 byte-stable report；workspace-aware gate 在 flock 内重验 selected MP4 后返回 production ready。
- **A119-02 PASS**：missing、global/per-shot stale、invalid artifact 与 blocked source 均阻断；placeholder 仅为 `degraded_preview`。
- **A119-03 PASS**：previous-tail exact lineage 由 D1 schema 与 D4 重验双层约束；角色/场景 exact version 和推拉反转只产生确定性 warning。
- **A119-04 PASS**：report 只绑定有序 selected snapshot，selection CAS 变化会 stale，未选候选追加不误伤；episode 2 report identity 无 episode 1 字面量。
- **A119-05 PASS**：31 项聚焦回归、py_compile、harness 与 diff check 通过；correctness、security/boundary、media-continuity 三路最终无遗留 P0/P1/P2。implementation commit `dd0c89aea68e7283c2347d451d287ec676837b01` 上唯一 canonical run `ee4b1b4a1fa2495a879ecd151760155c` 为 2404 tests / 15 steps / 235 秒、exit 0、tree `561c5544a53d584e06e609b4910a4c251a97c665`、`tracked_scope_clean=true`，mock preflight 0 WARN/FATAL；总级别 `mock-functional`，local-drama 组件 `local-e2e`，`provider_validated=false`。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮结论是既有“selected 显式真源、workspace 锁与 artifact 实体校验”长期规则在 D4 的具体落实，没有形成新的跨项目 workflow 规则。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增 D4 continuity report schema 与一致性校验 |
| `src/drama_shot_video_continuity.py` | 新增 selected snapshot、连续性投影与 workspace-aware compose gate |
| `tests/test_drama_shot_video_continuity.py` | 覆盖 ready/degraded/blocked、global stale、CAS、artifact tamper、episode 2 与输入边界 |
| `docs/iterations/README.md`、本文 | iter-start 索引与实施审计 |

## 不在本轮范围

- Voice Profile、TTS、TimelineManifest、字幕与 FFmpeg 合成。
- 真实视频 provider/network、Web 生产工作台、通用媒体 DAG 和视觉相似度模型。

## Notes

- clean-room 参考路线图固定的 ArcReel、LumenX 与 LocalMiniDrama commit，只借鉴状态/连续性思想，不复制外部实现。
