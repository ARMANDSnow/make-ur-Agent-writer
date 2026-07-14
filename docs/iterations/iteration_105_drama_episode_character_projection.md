# Iteration 105 - 短剧单集角色投影一致性

## Context

iter 095/101 已将季角色库容量与单集最多 8 人的 active cast 分离，并由 fingerprint v2 在组装时冻结 `character_fingerprint_ids`。但 D-03 仍存在确定性语义错位：reviewer prompt、组装元数据和单集 Comfy 导出仍可能各自读取整季角色库；其中后续集无 active cast 时的 Comfy fallback 会把整季角色灌入单集 workflow，既可能突破 8 人上限，也会让模型实际看到的角色与 review/input fingerprint 血统不一致。本轮只统一单集消费端的角色投影，不修改季角色库 CRUD、整季交付语义或验收基础设施。

## Plan

1. 在 `drama_store` 建立共享、纯函数式的单集角色投影，以严格 `CharacterSheet`、`episode_no` 和可选冻结角色 ID 为输入；显式 ID 必须存在、唯一且不超过 8 人，输出确定、只读且归一到当前集。
2. reviewer prompt 改用共享投影，排除未来集、其他集角色和 reference prompt、agent suggestions 等内部字段；确保 reviewer 实际看到的角色与 review fingerprint 使用同一集合。
3. 组装结果中的 `main_character_count` 等单集约束改按共享投影计算，并与 `DramaEpisodeMeta.character_fingerprint_ids` 保持一致。
4. standalone 与 season-package 的单集 Comfy 导出显式传递冻结角色 ID，删除 episode 2+ 无 active cast 时回退整季角色库的逻辑；合法 skip/reuse 后仍可导出已证明的本集阵容。
5. episode 1 视频输入同步采用 meta 冻结阵容，只要求本集角色具备参考图；不扩展 episode 2+ 真视频能力。
6. 保持角色生成阶段查看全季 ID、防冲突 merge、Web 角色库 GET/PUT 和 `characters/season_01.json` 的全季语义不变；episode 2+ 缺冻结 ID 且无法从 appearances 证明阵容的旧数据 fail-closed，要求重新评审/组装，不新增 schema migration。

## Acceptance

- **A105-01**：共享单集投影严格校验 `episode_no`、`CharacterSheet` 与可选冻结 ID，确定性返回和单集 fingerprint 同源的唯一角色集合，正常结果不超过 8 人；非法、缺失或越界 ID 显式失败，且函数不修改输入或磁盘。
- **A105-02**：reviewer 只接收本集投影；未来集、其他集角色及 reference prompt、provider/review 内部字段不进入 prompt，本集角色变化仍进入 review lineage，实际 prompt 阵容与 review fingerprint 一致。
- **A105-03**：assembled episode 的 `main_character_count` 等于本集投影人数；review prompt、review/input fingerprint 与 `meta.character_fingerprint_ids` 使用同一角色集合。
- **A105-04**：单集 Comfy workflow 只为本集阵容建立 LoRA/prompt 节点；9 人以上季库也不突破单集 8 人上限，合法 skip/reuse 可导出，歧义旧数据显式失败而非退回全季角色库。
- **A105-05**：季角色库仍可超过 8 人且不被投影读取改写；角色生成/保存/重画、Web 全表编辑与整季角色导出保持全季语义，无 schema/ledger migration、无真实 provider 调用。
- **A105-06**：聚焦回归覆盖 episode 1/2、active/future-only、skip/reuse、9 人季库、非法 frozen IDs、输入不变性、standalone/season Comfy 与 episode 1 视频；correctness、security/boundary、multi-episode/export 三视角只读审查无未处理 P0/P1。最终 `bash scripts/verify.sh` 在 implementation commit 上通过并仅产生 `mock-functional` canonical 证据，短剧组件保持独立 `local-e2e`、`provider_validated=false`，且不访问真实 provider、私有 workspace 或用户内容。

## Implementation Notes

- 在 `drama_store` 新增共享纯函数 `episode_character_projection`，严格验证冻结 ID 非空、唯一、存在且最多 8 人；输出只保留本集阵容、归一 appearances，并移除 review lock 字段与指向本集外角色的 `visual_contrast_with`。
- episode 1 的 legacy fallback 只接受 `appearances=[]` 的默认角色；只有 future-only 角色时在 provider 调用前 fail-closed。episode 2+ 无 active cast 时不再回退整季角色库；Web 的合法 skip 路径只继承上一集 fresh、Approve、同季同集号的 v2 frozen IDs，且不改写季角色表。
- reviewer prompt、review fingerprint、assemble `main_character_count`、meta frozen IDs、standalone/season Comfy 与 episode 1 视频已统一到同一投影。角色生成 prompt、Web 全表编辑和 `characters/season_01.json` 仍保持全季语义。
- season readiness 在宣称 ready 前验证每集角色投影；歧义 legacy v1 集按 stale 排除，避免 readiness 成功后导出抛裸异常。`is_episode_stale` 同时严格校验 meta schema、episode/season/verdict 与 frozen IDs。
- 聚焦回归覆盖纯投影、reviewer、assemble、standalone/season export、episode 1 video、双集 Web skip/reuse、9 人季库、future-only、misfiled meta 与 legacy v1 readiness，共 **134 tests OK**；语法、harness 与 `git diff --check` 通过。
- correctness/behavior、security/boundary、multi-episode/export 三视角只读审查的重复报告去重后为 2 个 P1、2 个 P2、1 个 P3 覆盖建议，均已修复并复核；当前无未处理 P0-P3。未运行真实文本、图片或视频 provider。

## Acceptance Result

由 `iter-finish` 按 A105-01 至 A105-06 逐项回填测试数、审查结论、最终 acceptance evidence 与未修风险。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_105_drama_episode_character_projection.md` | 建立 iter105 计划、验收 ID 与审计记录骨架 |
| `docs/iterations/README.md` | 追加 canonical iteration 索引 |
| `src/drama_store.py`、`src/drama_schemas.py` | 单集投影真源、冻结 ID 严格校验、组装/指纹/stale 一致性 |
| `src/drama_reviewer.py`、`src/web/jobs.py` | reviewer 使用本集阵容，Web skip 从上一集可信 meta 继承冻结阵容 |
| `src/comfy_workflow_exporter.py`、`src/drama_season_export.py` | 删除整季 Comfy fallback，standalone/season 导出与 readiness 统一使用冻结投影 |
| `src/drama_video.py` | episode 1 视频只读取和校验冻结阵容及其参考图 |
| `tests/test_drama_iter105_character_projection.py` | 新增单集投影、双集 Web/导出、legacy、隐私与视频专项回归 |
| `tests/test_drama_exports.py`、`tests/test_drama_reviewer.py`、`tests/test_drama_iter095_core.py` | 更新 skip/reuse 与 legacy fail-closed 历史契约 |

## 不在本轮范围

- Web 角色库改成单集编辑器、GET/PUT patch/merge 协议或季角色库 schema/容量重构。
- `characters/season_01.json` 的全季角色投影、100 集查询性能优化或多季模型。
- 任何真实文本、图片、视频 provider 调用、状态查询、账单校验或质量判定。
- episode 2+ 真视频、真 ComfyUI 校准、JPEG/WebP decoder 或更广 codec/容器支持。
- paid-ledger、canonical 验收基础设施或无关小说流水线改造。

## Notes

- 本轮显式使用 repository-local `iter-start`；实施完成后必须使用 `iter-finish`，并仅在事实变化时就地同步 README SOP、handoff 与 `PROJECT_HISTORY.md`。
- 用户未跟踪的 `docs/2026-7-14体检报告.md` 保持原样，不读取、不 stage、不 commit。
- 建议立项提交信息：`docs(iter105): 迭代计划 105 立项（短剧单集角色投影一致性）`；本次起轮不自动 commit、不 push。
