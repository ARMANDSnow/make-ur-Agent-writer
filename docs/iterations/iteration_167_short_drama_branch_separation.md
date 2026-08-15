# Iteration 167 - 短剧模块安全分支拆分

## Context

当前完整基线同时承载小说续写与短剧创作，两套产品在 CLI、Web 路由、任务调度、模型配置和 canonical 验收中深度耦合。用户要求将完整短剧能力保存在独立分支，并把 `main` 收敛为小说续写模块；main 只保留不可跳转的短剧入口外观，同时必须保证旧短剧 workspace 不被误识别、修改或删除。

## Plan

### Implementation Context
- `must_read`: `main.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/web/workspace_meta.py`, `scripts/verify.sh`, `scripts/write_acceptance.py`
- `expected_changes`: `AGENTS.md`, `README.md`, `main.py`, `config/agents.yaml`, `config/models.yaml`, `src/preflight.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/web/server.py`, `src/web/static.py`, `src/web/templates.py`, `src/web/wizard.py`, `src/web/workspace_meta.py`, `scripts/verify.sh`, `scripts/write_acceptance.py`, `tests/test_agent_harness.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_server.py`, `docs/product/short_drama_module.md`, `docs/product/short_drama_creation_standard.md`, `docs/iterations/iteration_167_short_drama_branch_separation.md`
- `do_not_touch`: 不读取或修改 `.env`、`data/`、`outputs/`、`logs/`、`workspaces/`、`小说txt/`；不读取、提交、移动或删除现有未跟踪体检报告；不修改 `codex/short-drama` 快照；不执行真模型、真生图、真视频或 TTS。

1. 在完整基线建立 `codex/short-drama`，在独立实施分支拆除 main 的短剧运行能力，最终仅以 fast-forward 更新 main。
2. 删除短剧领域、媒体、CLI、Web/API、任务、prompt、fixture、脚本与当前测试；共享模块只保留小说路径和 legacy drama 类型隔离哨兵。
3. 首页和作品列表保留无链接的短剧禁用入口；短剧向导、页面、API、媒体回调和 CLI 命令全部不可达。
4. 旧短剧 workspace 只读识别并从小说枚举隐藏，直接访问 fail closed，禁止把它迁移或当作小说处理。
5. canonical 验收升级为 novel-only schema v3/profile，移除 local drama E2E 强制步骤；同步当前文档并保留历史审计记录。

## Acceptance

### Review Context
- `correctness_behavior`: 核对小说原创/续写、导航、任务与失败恢复保持 iter166 行为；短剧 CLI/Web/job/import 均不可达；禁用入口无 href/handler；旧 drama workspace 不展示、不误判且字节不变。
- `security_boundary`: 核对删除后不存在短剧付费/provider/公开媒体入口或残留导入；legacy metadata 仅用于隔离，不允许创建或写入；所有检查不读取私有 workspace、凭据、原文、媒体和未跟踪报告。
- `extra_risk_view`: Web/runner/harness 专项：检查共享 routes/jobs/static/templates 的删除边界、404 行为、novel-only job registry，以及 schema v3 验收不再依赖短剧证据且仍保持 mock/offline。

- A167-01：`codex/short-drama` 精确指向完整基线 `35c97ccedeaca1725cc1a491cebf393f6a91303a`，main 最终只以 fast-forward 接收已验收结果；不 push、不删除分支。
- A167-02：main 的可执行代码、配置、prompt、fixture、脚本和当前测试不再包含短剧实现；历史文档、迁移提示、禁用入口文案与 legacy 类型哨兵除外。
- A167-03：首页和作品列表保留“短剧模块暂未开放”禁用控件，具备 `disabled`/`aria-disabled`，无 `href`、跳转目标或短剧创建表单。
- A167-04：短剧 CLI、页面、API、公开媒体路由和 job step 不存在；历史入口返回 404 或 argparse 非法命令，不触发 provider、任务或文件写入。
- A167-05：旧 `type=drama` workspace 可被安全识别但不会出现在 main 的 Web/CLI 小说列表，不能进入小说页面、创建短剧任务或被当作小说修改。
- A167-06：acceptance schema 为 v3、profile 为 novel-only，`verify.sh` 不再运行或校验 `local_drama_e2e`，仍强制 mock/offline、隔离 synthetic workspace 并绑定干净 implementation commit。
- A167-07：聚焦测试、语法检查、harness 检查与 diff 检查通过；correctness、security/boundary、Web/runner/harness 三个只读视角无未闭合有效 finding。
- A167-08：最终唯一一次 `bash scripts/verify.sh` 通过并产生 `mock-functional` novel-only canonical 证据；收官文档记录准确测试数、implementation commit、步骤和未修风险。

## Implementation Notes

- 在完整基线 `35c97ccedeaca1725cc1a491cebf393f6a91303a` 建立 `codex/short-drama`，并在 `codex/novel-only-split` 实施；立项提交为 `233e89b`。
- `4ab110b` 物理移除短剧领域/媒体模块、CLI 归档命令、Web 页面/API/公开媒体路由、job step、prompt、fixture、脚本和对应测试；共享 routes/jobs/static/templates/config/preflight 收敛为小说路径。
- 首页和作品列表保留两个原生 disabled 入口，统一显示“短剧模块暂未开放”；不存在 `href`、onclick 或短剧向导表单。
- workspace identity 分成 recognized 与 supported：legacy `drama` 仅作隔离哨兵，`novel` 是 main 唯一可创建、枚举和运行的类型。CLI/Web/list/direct/logs/run-step/import/trash 均 fail closed。
- 回收站对 unsupported entry 隐藏并投影为 `entry_not_found`；restore/purge 使用锁、nofollow parent fd、`(st_dev, st_ino)` 二次匹配与 dir-fd 操作，防止检查后替换导致迁移或删除旧短剧数据。
- canonical 升级为 schema v3 / `canonical-novel-mock-offline`，以 exact ordered steps 约束成功证据；新增 novel-only 静态边界检查，删除 `local_drama_e2e` 及其 evidence 依赖。
- `a1ffb71` 修正首次 canonical 暴露的两个旧契约：topbar CSS 精确空格断言，以及 invalid workspace metadata 的新 404 fail-closed 预期。

## Acceptance Result

- 结果：`mock-functional`，2026-08-15 accepted。
- implementation：`a1ffb71df295e057c3e4af5e7d2cdc5b7270364e`（主体拆分 `4ab110b`）。canonical schema v3，profile `canonical-novel-mock-offline`，run `8a1055c15cff4139acad65dedfd3686f`，1847 tests / 15 steps / 149 秒，status=passed，`tracked_scope_clean=true`。
- 聚焦检查覆盖 disabled DOM、历史路由/CLI 缺席、legacy/invalid/unsafe workspace、logs、import-current、trash list/restore/purge 与 swap、小说创建/续写/恢复、job projection、harness exact steps、py_compile、CLI help、route table、test discovery 和静态边界；回归通过。
- correctness 只读审查发现并关闭：向导 progress section 开标签丢失、logs tail 缺类型守门、import-current 可写入 legacy target、trash 可枚举/恢复/删除 unsupported entry，以及遗留 job result keys。最终复核无 finding。
- security/boundary 只读审查发现并关闭：孤儿 character-ref 路由、invalid/unsafe CLI identity、trash 公开存在性与 TOCTOU、非 `drama_` 命名的媒体 CSS/JS/job/fixture 残留。最终复核无 finding。
- Web/runner/harness 只读审查发现并关闭：向导 DOM 回归、孤儿媒体 route 500、generic static/test 残留、boundary checker 漏检/自撞、route absence 测试弱断言，以及 schema v3 acceptance 可绕过 canonical steps。最终复核无剩余问题。
- 首次 `verify.sh` 在 1847 tests 中有 2 个失败，均为拆分后旧测试契约（CSS 精确空格、invalid metadata 409→404），没有功能/provider 失败；聚焦修复提交 `a1ffb71` 后按失败重验规则完整复验并通过。全程强制 mock/offline，未调用真实文本、图片、视频或 TTS provider。
- A167-01 PASS：短剧快照 ref 精确固定；docs-only 收官后以 `--ff-only` 更新 main，不 push、不删分支。
- A167-02 PASS：静态 novel-only checker 通过；允许项之外无短剧实现引用。
- A167-03 PASS：两个禁用入口具有 `disabled` / `aria-disabled`，无跳转。
- A167-04 PASS：历史 CLI、页面、API、媒体和 job surface 不存在或返回 404。
- A167-05 PASS：legacy drama 隐藏、direct fail closed，import/trash 不修改数据并覆盖 swap 回归。
- A167-06 PASS：schema v3/profile exact steps、synthetic workspace、mock/offline 与 clean implementation binding 均由 evidence 证明。
- A167-07 PASS：聚焦检查和三个独立只读视角最终无未闭合 finding。
- A167-08 PASS（有记录偏差）：最终 successful canonical 证据完整；因首次完整门禁暴露 2 个测试契约而按项目规则修复并重验，因此本轮实际执行两次标准验收，而非计划中的单次调用。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `AGENTS.md`, `docs/PROJECT_HISTORY.md`, `docs/product/GETTING_STARTED.md`, `docs/product/NOVEL_WEB_UIUX_REDESIGN_SPEC.md`, `docs/product/PRODUCT_SPEC.md`, `docs/product/short_drama_module.md`, `docs/product/short_drama_creation_standard.md`
- `reason`: novel-only 产品边界、workspace 支持语义、canonical schema v3 和短剧分支访问规则会影响所有后续开发与用户操作，必须进入现有长期权威文档。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `main.py`、`src/`、`config/` | 删除短剧运行/媒体/任务路径，保留小说链与 legacy 类型隔离；强化 CLI/Web/trash fail-closed |
| `src/web/` | 保留禁用入口，移除短剧页面/API/媒体/JS/CSS；修复小说向导共享 progress panel |
| `scripts/` | canonical schema v3 novel-only profile；新增静态边界检查；删除短剧/local-e2e 工具 |
| `prompts/`、`tests/fixtures/` | 删除短剧 prompt 与 provider/media fixture |
| `tests/` | 删除短剧测试，新增 iter167 隔离/不变性/路由/CLI/harness 回归 |
| README、AGENTS、handoff、history、product docs | 切换为小说主线，并将短剧完整资料改为分支迁移说明 |

## 不在本轮范围

- 不把 `codex/short-drama` 反向裁剪为短剧单产品。
- 不迁移、删除或读取任何现有短剧 workspace、媒体、账本或 provider 状态。
- 不 push、不创建 PR、不执行任何真实 provider 验证。

## Notes

- 完整短剧能力以固定分支引用保全；main 的历史 iteration 继续作为审计记录，不代表当前运行能力。
