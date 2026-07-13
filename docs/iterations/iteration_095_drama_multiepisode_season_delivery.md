# Iteration 095 - 短剧多集与整季交付闭环

## Context

Iteration 088 已交付第 2 集与单集四格式导出，Iteration 090-094 完成五站 job、多模态可恢复编排和 mock 校准证据；当前短剧主链仍把后续集创建限制在 episode 2，视频限制在 episode 1，并缺少产品协议声明的整季交付包。

本轮把现有单集能力推广为严格连续的多集生产，并同时提供完整整季母包与可中途交付的阶段快照。实现继续以 mock 为默认，不触发真实文本、生图或视频请求；单季、单集导出和 episode 1 视频契约保持兼容。

## Plan

1. 将剧集状态与 `next-episode` 收口到同一连续性判定，支持按 `episode_count` 初始化任意 N+1，并保留有效 setup 的幂等恢复。
2. 修复 episode 3+ 的 setup 继承、mock 钩子唯一性、全历史钩子去重和角色 appearances 累积。
3. 引入 episode-scoped freshness v2 与旧 meta 兼容迁移，避免未来集角色变化误判旧集 stale。
4. 增加 season readiness、严格 master ZIP 与部分 snapshot ZIP，固定安全 manifest、导出成员、原子写入和确定性字节。
5. 扩展剧集 API 与 Web 页面，提供明确的下一集阻断原因、可交付统计和两种季包入口。
6. 增加多集、freshness、导出、Web/API 和安全边界回归；聚焦验证与只读审查完成后再运行一次标准全量验收。

## Acceptance

- 第 1 集到第 3 集的 mock 五站链可连续完成；只允许从最新连续、完整且 fresh 的第 N 集初始化 N+1，重复初始化不改写已有有效产物。
- `episode_count` 与 episode number 继续严格限制为整数 1-100；跳集、断档、stale、孤儿产物、计划上限和越界均 fail-closed。
- episode 3+ 不继承前集本集主线或钩子；mock 候选跨集唯一，本地去重覆盖全部历史而 prompt 仍只带最近 20 条。
- 角色 appearances 可累计到 100；未来集 appearance 或新角色不令旧集 stale，旧集活跃角色的实际视觉字段或参考图变化仍会令该集 stale。
- `mode=master` 只在计划内全部剧集连续、完整、fresh 且引用资产完整时导出；`mode=snapshot` 至少包含一集 fresh 完整集，并在 manifest 记录排除项。
- 两种 ZIP 均从 assembled JSON 重建四种单集导出，包含季角色表和合法引用图，不包含 setup、候选、评审原文、meta、日志、完整 prompt 或 provider state；路径安全、原子写入且同输入字节稳定。
- Web/API 显示一致的下一集和季包 readiness；小说 workspace、非 season 1、非法 mode 和 write conflict 保持既有安全边界。
- 聚焦测试、Python compile、`git diff --check`、最终 canonical、`bash scripts/verify.sh` 与 mock preflight 全部通过；真实模型和媒体请求数为 0。

## Implementation Notes

- 起始基线：canonical 1915 tests OK；短剧聚焦 232 tests OK。
- 当前仅支持 `season_no=1`，不升级 workspace schema；`data/wizard_input.json` 的 `episode_count` 继续是计划集数真源。
- 立项阶段已确认工作树 clean；`main` 相对 `origin/main` ahead 56、behind 2，不在本轮同步远端。
- GET 剧集状态与 POST `next-episode` 现共用 `_drama_next_episode_state`；有效 setup 幂等恢复，非法 setup、跳集、断档、孤儿、SHA/freshness 失败和计划上限均给出稳定 blocker。
- episode 3+ 只继承系列字段并重置本集主线/钩子；mock 钩子以全历史精确去重，prompt 仍只携带最近 20 条。
- 新 assembly 写入 freshness v2 与冻结的活跃角色 ID；旧 v1 只在当前仍 fresh 时迁移。角色表所有写入口先迁移，跳过新角色时也会持久化本集 appearance。
- 季包导出采用 dirfd/openat、`O_NOFOLLOW`、同 fd 有界读取、总成员预算、固定 ZIP 元数据和目录内原子替换；失败保留上次成功包。
- `iter-finish` 前完成 correctness、security/export、Web/API 三视角审查；发现的 legacy fingerprint 漂移、空 appearance、setup 校验、快照提示、计划上限、修复入口、ZIP 字段泄漏/TOCTOU/预算问题均已修复，最终三方 PASS。

## Acceptance Result

- **通过**。第 1→2→3 集 mock 链、连续性/幂等/上限、episode 3+ 继承重置、20+ 历史钩子去重、appearance 1-100、v1→v2 迁移与旧集 freshness 语义均有回归。
- master/snapshot 的成员、过滤、manifest、响应头、确定性、原子替换、引用资产异常、符号链接/路径穿越、源文件 TOCTOU 和 64 MiB 总预算均有回归；非法 mode/season、小说 workspace 与 write conflict 保持 fail-closed。
- 短剧聚焦：`python -m unittest discover -s tests -p 'test_drama*.py'` → **252 tests OK**。
- 最终 canonical（项目 `.venv`）：`python -m unittest discover -s tests` → **1942 tests OK**，相对 iter 094 基线新增 27 项。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0，内含 1942 tests、mock auto-pipeline、manifest/report/cost 检查；`OPENAI_MODEL=mock .venv/bin/python main.py preflight` 为 ok、无 WARN/FATAL。
- Python compile 与 `git diff --check` 通过；验证和实现均未发起真实文本、生图或视频请求。LiteLLM 仅尝试刷新公开 cost map 并超时回落本地备份，不属于计费模型调用。
- 最终审查无阻断项；保留 P3 性能尾项：100 集时 GET episodes 会在状态与 season readiness 间重复读取部分文件，不影响正确性。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_095_drama_multiepisode_season_delivery.md` | 本轮八段计划、实施、审查与验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 095 索引。 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 同步当前能力、验收基线、历史里程碑与后续缺口。 |
| `src/drama_planner.py`、`src/hook_designer.py`、`src/character_designer.py`、`src/drama_schemas.py` | 多集继承、全历史钩子去重、appearance 1-100 与 freshness v2 schema。 |
| `src/drama_store.py`、`src/drama_season_export.py` | episode-scoped freshness/migration 与安全、确定性、原子季包生成。 |
| `src/web/routes.py`、`src/web/jobs.py`、`src/web/static.py`、`src/web/templates.py` | 统一下一集状态、季包 API、角色迁移写入口与剧集页入口/阻断展示。 |
| `src/drama_smoke.py`、`src/drama_multimodal_smoke.py`、`src/drama_video_smoke.py` | 角色表写入前迁移并补齐写锁。 |
| `tests/test_drama_iter095_core.py`、`tests/test_drama_iter095_web.py`、`tests/test_drama_season_export.py`、`tests/test_drama_character_designer.py` | 核心、多集 Web/API、季包安全与角色累积回归。 |

## 不在本轮范围

- episode 2+ 视频、逐镜媒体资产、真 ComfyUI workflow、批量真生图或真视频。
- 未经明确授权的真文本、真生图或真视频调用，以及真实供应商质量校准。
- season 2+、公网多租户部署、workspace schema 升级或小说主链改造。

## Notes

- 本轮已显式使用 `iter-start` 与 `iter-finish`；多视角审查与 findings 修复先于最终全量验收。
- 无真实付费调用，也未改 workspace schema。
- 收官提交信息草案：`feat(iter095): 完成短剧多集与整季交付闭环`。
