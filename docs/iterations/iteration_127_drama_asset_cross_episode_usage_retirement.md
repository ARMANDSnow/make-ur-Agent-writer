# Iteration 127 - 短剧资产跨集 Used-By 与停用保护

## Context

iter126 已完成 A2 visual-only override 与 A-F stale dependency matrix。A-J 实时 SOP 的阶段 B 仍只有 episode-scoped used-by：角色、ArtDirection、场景、道具/线索的不可变版本可以被多集冻结引用，但尚无统一跨集反向索引，也没有“被引用版本不可静默删除、只允许显式停用”的可执行策略。本轮只完成 B1 跨集 usage/retirement 闭环，不做资产 Web UI 或真实 provider。

## Plan

### Implementation Context
- `must_read`: `docs/iterations/stage_plan_drama_full_production_pipeline.md`, `docs/product/short_drama_module.md`, `src/drama_schemas.py`, `src/drama_asset_versions.py`, `src/drama_art_direction_store.py`, `tests/test_drama_asset_versions.py`, `tests/test_drama_art_direction_store.py`
- `expected_changes`: `src/drama_schemas.py`, `src/drama_asset_usage.py`, `src/drama_asset_versions.py`, `src/drama_art_direction_store.py`, `tests/test_drama_asset_usage.py`, `docs/iterations/iteration_127_drama_asset_cross_episode_usage_retirement.md`, `docs/iterations/README.md`, `docs/product/short_drama_module.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、用户未跟踪体检报告和私有 workspace 内容；不物理删除资产/版本或历史 manifest；不调用图片/视频/TTS provider，不 push

1. 建立 season-scoped、content-addressed used-by index，统一投影 character、ArtDirection、scene、prop/clue 的 exact version 与 episode/shot 引用；按 episode/version 稳定排序，候选未被任何 frozen manifest 使用时明确为空。
2. 扫描只接受受控 episode 文件名和 strict manifest/envelope；invalid、unsupported、symlink/FIFO/目录或扫描竞态不能被当成“零引用”，而要形成有界 blocker，使 retirement fail closed。
3. 定义 append-only retirement governance：版本只能 active→disabled，不提供物理删除；mutation 使用 revision/current-state 双 CAS，已冻结历史引用保持可读，disabled 版本禁止成为新的 selected，但原有 selected/manifest 不被静默改写。
4. 将 character/ArtDirection/scene/prop-clue 的选择入口接入统一 governance guard；恢复 active 必须显式新 revision，跨页面 stale/ABA 请求被拒绝。
5. 审查与 canonical 后，独立做至多一次 scope-specific 真文本协议校准；图片/视频/TTS 均不调用。

## Acceptance

### Review Context
- `correctness_behavior`: 四类资产跨集 used-by 完整、稳定且不漏 episode/shot；停用不破坏旧集，所有新选择入口一致拒绝 disabled；双 CAS、幂等与恢复 active 行为确定
- `security_boundary`: episode 枚举、manifest/envelope、asset/version id、路径与数量有界；invalid/symlink/FIFO/目录/并发替换 fail closed；公开错误不泄露本地路径、prompt、provider 或签名 URL
- `extra_risk_view`: 资产/多 workspace 血统，复核 stale manifest 仍计入删除保护、候选未选不误报 used-by、跨集索引不把 workspace/season/episode 混绑

- **A127-01**：四类资产 exact version 的跨集 used-by index 字节稳定、完整且 content-addressed；episode/shot scope 与空引用明确。
- **A127-02**：坏 manifest、特殊文件、超限/深层 JSON 与扫描竞态不能降格为零引用；retirement 在索引不完整时 fail closed。
- **A127-03**：retirement state 只允许显式 active/disabled、revision/current-state 双 CAS 和安全原子落盘；不提供物理删除。
- **A127-04**：disabled 版本不能成为 character/ArtDirection/scene/prop-clue 的新 selected；既有 selected 与旧集 frozen refs 保持可读，显式恢复后可再次选择。
- **A127-05**：聚焦回归与 correctness/security/asset-lineage 三视角无未处理 P0/P1/P2；implementation commit 上唯一 canonical 通过，真文本校准在总 cap 内，图片/视频/TTS 为 0。

## Implementation Notes

- 新增 `drama_asset_usage` 领域层：从 season 四类 strict catalog 与各集 frozen RenderPlan/manifest 确定性重建 exact-version 反向索引；所有 catalog version 都进入索引，未使用候选以空 references 表达。索引绑定 source bytes SHA、稳定排序和 canonical fingerprint，不写第二份可漂移 cache。
- episode namespace 从 workspace root dirfd 开始逐段 `O_DIRECTORY|O_NOFOLLOW` 打开；canonical episode 或任一 B source 会建立 episode inventory，四类源缺项、坏 envelope、特殊文件、内外 episode identity 错位、目录替换与扫描竞态都生成有界 blocker。真正尚无 episode/canonical source 的初始态仍允许空索引。
- 新增 season retirement ledger：仅有 active/disabled，state revision 与 expected current status 双 CAS，原子 envelope 写入；disabled entry 绑定当次 usage index fingerprint，决策永远 `can_physically_delete=false`。restore active 必须产生新 revision。
- character、ArtDirection、scene、prop/clue 的 selected mutation 均在写前和 precommit 拒绝 disabled target；新建/替换 RenderPlan 与三类 episode manifest 同样拒绝冻结 disabled selected。已有 fresh/no-op、旧 manifest 和历史 exact refs 继续可读，不因停用被改写或删除。
- 初轮只读审查发现并修复：RenderPlan 内嵌 episode 与文件名错位会误归集（correctness P2）；中间 `outputs` symlink 可把非法 namespace 降格为空扫描（security P2）；缺失 sibling source 可伪造 zero-use、disabled selected 仍能被新集物化（asset-lineage P1×2）。修复后 correctness/security/asset-lineage 三路复核均无遗留 P0/P1/P2。
- 聚焦证据：iter127 专项 12 tests、相关 asset/render 回归 87 tests 全部通过；`py_compile`、agent harness（accepted 126 / active 127 / 136 entries）与 `git diff --check` 通过。未读取 `.env`、私有 workspace、`小说txt/` 或用户体检报告，未调用网络/provider。

## Acceptance Result

<iter-finish 回填测试数、canonical、真模型校准、审查结论与未修风险。>

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/product/short_drama_module.md`
- `reason`: 跨集 Used-By、disabled 的历史可读/未来不可物化语义及“零引用不等于可物理删除”是阶段 B 后续 Web、归档和 GC 必须共享的长期产品边界。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_schemas.py` | 新增跨集 usage index、source/blocker、retirement state/decision strict schemas |
| `src/drama_asset_usage.py` | 新增 nofollow 扫描、exact-version used-by、停用决策与双 CAS ledger |
| `src/drama_asset_versions.py` | character/scene/prop-clue selection 与新物化接入 active guard |
| `src/drama_art_direction_store.py` | ArtDirection selection 接入 active guard |
| `src/drama_render_store.py` | 新/替换 RenderPlan 阻止冻结 disabled ArtDirection |
| `tests/test_drama_asset_usage.py` | 覆盖跨集、零使用、坏源/目录、identity、CAS、停用/恢复与四类入口 |
| `docs/product/short_drama_module.md` | 晋升 B1 跨集 Used-By 与非破坏停用长期 SOP |
| `docs/iterations/README.md`、本文件 | 登记 iter127、计划、证据、审查与收官结果 |

## 不在本轮范围

- 资产总览/候选比较 Web UI、跨 workspace/global registry、物理 GC、特定 provider 删除 API。
- ArtDirection 的 Global/Series/Episode 多 scope resolution、真实图片/视频、TTS 与资产主观质量比较。

## Notes

- README、handoff 与 PROJECT_HISTORY 只在 iter-finish 且事实变化后同步；本轮 implementation commit 先于唯一 canonical。
