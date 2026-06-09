# Iteration 048c — 小白四步工作台·细纲只读 + 重新生成 + 写书指纹链兼容回归

> iter048 串行子迭代 3/3（048a 后端骨架 → 048b 前端工作台+大纲回写 → **048c 细纲只读+重生成+写书兼容**）。本轮把工作台 stage③ 从「跳走查看细纲」升级为「就地只读展示 + 重生成按钮」，并兑现整个 iter048 红队拆分的核心承诺：**让"改细纲"路径完全绕开 write-book 的指纹门禁陷阱**。

## Context

iter048 草案最初想把"细纲 JSON 可编辑回写"放进 048b，红队对抗审查证伪此路：`book_runner._plan_metadata_failures`（`book_runner.py:561-606`）对 `chapter_plan.json` 做严格的 `plan_fingerprint` + 逐章 `chapter_plan_item_fingerprint` 比对，任何就地编辑（哪怕用 PUT 自动保留旧指纹）都会让 write-book 立刻 `blocked` —— 即"能编辑但编辑完写不了书"。串行子迭代拆分把这条暗礁隔离到 048c **单独验证**：本轮唯一的存在理由就是证明，"重新生成"路径（重跑 `plan-chapters` step，让 `generate_chapter_plan` 末尾的 `_attach_plan_fingerprints` 自动重算所有指纹）**与 write-book 的指纹 gate 自洽**，不撞 mismatch。

UX 层面，048b 的 stage③ 只在卡片底部留了"查看细纲详情 →"链接到 `/plan` 页，要离开工作台才能看到细纲；048c 把细纲只读展示**搬回 stage③ 卡片内**，同时把"生成细纲"按钮按 has_plan 切换为"重新生成细纲"，明确告诉用户"换细纲走重生成、不走手改"。结构化字段编辑（每章 7+ 字段 + 数组增删 + 范围校验）与正文/设定编辑一起留 049。

## Plan

1. **`src/web/templates.py` `render_workspace_workbench` stage③**：在 `#plan-chapters-status` 后加 `<div id="plan-chapters-preview" class="muted">尚未生成细纲。</div>` 占位容器。卡片其它结构不变。
2. **`src/web/static.py` `refreshWorkbench`**：
   - 拉 `/plan` 的位置从「has_outline 且大纲未脏」内移出（因为现在还要渲染细纲），重构为「has_outline 时拉一次 /plan → 回填大纲（仍守 dirty/focus）+ 渲染细纲」。
   - 新增 `renderPlanPreview(plan)`：用 `kv-list compact` 类渲染 `第NN章 / title / · 约 N 字`，每章一行；无细纲时回落到"尚未生成细纲。"占位文案。
   - 按 `has_plan` 切换 `#plan-chapters-submit` 按钮文案为「生成细纲」/「重新生成细纲」。
3. **`tests/test_workbench_replan.py`（新）**：mock 全链路 premise→prepare→debate→plan-chapters 后**手动破坏** `chapter_plan.json` 的 `plan_fingerprint` 与某一章的 `chapter_plan_item_fingerprint`（模拟"假设有人手改了细纲"），然后再次跑 `plan-chapters`（即"重新生成细纲"按钮触发的路径），断言：(a) 所有指纹**全部重算**且自洽；(b) write-book 不再撞 `plan_fingerprint_mismatch` / `chapter_NN_plan_item_fingerprint_mismatch`（draft 落盘）；(c) workbench status 仍正确反映 has_plan。
4. **不做**：PUT `/chapter-plan` 手改回写、结构化字段编辑、正文/设定编辑 —— 全部留 049。

## Acceptance

- `OPENAI_MODEL=mock` 下 `.venv/bin/python -m unittest discover -s tests` 全绿（基线 681 → **684**，+3）。
- `OPENAI_MODEL=mock python main.py preflight` → PREFLIGHT: ok，FATAL/WARN none。
- 浏览器实机：workbench stage③ 卡片内展示细纲列表（`第01章 mock 第 1 章 · 约 4000 字` …第 05 章），按钮文案为「重新生成细纲」。
- 指纹链测试：损坏 `plan_fingerprint` 后重跑 plan-chapters → 指纹自动恢复自洽且与 `plan_fingerprint(data)` 重算结果相等；write-book 之后不报 `plan_fingerprint_mismatch` / `plan_fingerprint_missing`，draft 落盘。

## Implementation Notes

- **指纹链自洽的机制**：`generate_chapter_plan(...)`（`plot_planner.py:33`）写盘前必调 `_attach_plan_fingerprints(data, start_chapter_id=...)`（`plot_planner.py:171, 220-227`），它先按每章 `chapter_plan_item_fingerprint(item)` 重算并写入 item，再按 `plan_fingerprint(data)` 重算并写入顶层。所以任意来源的旧指纹（用户手改、JSON 字段错位、本测试人为破坏）在重生成后都会被无条件覆盖为对新 data 的正确哈希。这是把"改细纲走 PUT"的暗礁化解为"改细纲走重跑 step"的根本依据。
- **mock 限制带来的更强测试设计**：mock 的 `ChapterPlan` 在 `llm_client._mock_json:566-585` 硬编码 5 章（`range(1, 6)`），不论 `target_chapters` 传几都返回同样结构；初版测试想用「target=7 后 chapters 数变 7」证明 re-plan 生效，被这条 mock 限制证伪。**反过来用作更精确的反陷阱证据**：保持 target=5、人为损坏 fingerprint，重跑后断言**指纹被改回正确值**——这比"内容变了导致指纹变了"更直接证明了 `_attach_plan_fingerprints` 总会重算（即使数据没变也写）。
- **前端最小入侵**：stage③ 卡片只新增一个 `<div>` 容器，HTML 行数 +1；JS 把已有的 `/plan` 拉取重构为「同一次拉取里顺手渲染细纲」，无额外网络请求；按钮文案随 `has_plan` 自动切换，无需后端配合。048b 的所有测试无需修改即可继续绿（事实：跑 `test_workbench_e2e` 7/7 OK 不动）。
- **stage④ 在 mock 下仍是 `blocked` (`retry_exhausted`)**：mock reviewer 默认 Reject（`reviewer.py:68`），写出 draft 但拿不到 strict-approved。`test_write_book_after_replan_passes_fingerprint_gate` 据此**只**断言 first_blocked.reason 不是 fingerprint 类，且 `chapter_01.md` 落盘 —— 这恰好证明"写手开跑了"=fingerprint gate 已通过。真实模型可 Approve（铁律⑥需用户授权）。

## Acceptance Result

- **测试**：`OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` = **684 OK**（基线 681 + 新增 3，零回归；048b 的 7 个 workbench e2e 测试无需改动继续绿，证明前端改动对已有契约无破坏）。
- **preflight**：FATAL/WARN none。
- **浏览器实机（CLAUDE.md 铁律：UI 改动须实机走过）**：
  - 启动 `web-mock` dev server → 通过 API 链路驱动 premise(workspace=livebook2) → prepare-greenfield → debate → plan-chapters；
  - 导航到 `/w/livebook2/workbench`：stage pill 显示"当前：④ 正文"，stage③ 卡片内 **`#plan-chapters-preview` 渲染细纲列表**（第 01-05 章，每条形如「第NN章 / mock 第 N 章 · 约 4000 字」），**按钮文案 = "重新生成细纲"**（has_plan=true 触发文案切换），未禁用；
  - 大纲 textarea 仍自动回填 mock 大纲（048b 不回归）；console 全程零错误；
  - 实机 workspace `livebook2` 已清理。
- **指纹链自洽核心证据**：`test_replan_recomputes_fingerprints_after_corruption` 在人为把 `plan_fingerprint` 置为 `"deadbeef"*8`、第 1 章 `chapter_plan_item_fingerprint` 置为 `"cafebabe"*8` 后再跑 `plan-chapters`，断言所有指纹恢复到 `plan_fingerprint(data)` / `chapter_plan_item_fingerprint(item)` 的当前重算值 —— **绕开"手改陷阱"的设计在端到端层面被钉牢**。
- **收官对抗审核（铁律⑨）**：本轮三个测试本身就是对红队最深暗礁（指纹链）的反陷阱守门；UI 改动是 048b 现有卡片的 +1 div + JS 重构，对已有契约零破坏（684 全绿即证据）。API 已恢复但本轮自审已充分覆盖（test_workbench_replan 三测 + 实机），未额外 spawn subagent。

## 文件变更汇总

- `src/web/templates.py`（改）：stage③ 卡片加 `#plan-chapters-preview` 占位容器（HTML +1 div）。
- `src/web/static.py`（改）：`refreshWorkbench` 重构「拉 /plan + 回填大纲 + 渲染细纲 + 切按钮文案」一次完成；新增 `renderPlanPreview(plan)`。
- `tests/test_workbench_replan.py`（新）：3 个 mock 测试（指纹腐化后重生成自洽 / write-book 不撞 fingerprint gate / workbench status 反映重生成）。

## 不在本轮范围

- **049**：细纲结构化字段编辑（每章 7+ 字段 + 数组增删 + 范围校验）+ 正文逐章深度编辑回写 + 重 review；premise 扩写质量增强；设定（KB/entity_graph）编辑回写；真模型授权 + 测 Key 成本护栏深化；阶段①子步粒度进度展示。
- 本轮不跑真模型（铁律⑥），不做 PUT `/chapter-plan` 手改回写，不做手动指纹处理。

## Notes

- **iter048 串行子迭代完结**：048a 后端骨架（674 OK）→ 048b 前端工作台+大纲回写（681 OK + 实机）→ 048c 细纲只读+重生成+指纹自洽（684 OK + 实机）。红队对原计划的 7 条修正全部兑现：①`_WORKSPACE_SECTIONS` 入口（048b）②`require_start_point:false`（048b）③mtime 链防旧产物误判（048b）④prepare-greenfield 进度契约修正（048a）⑤premise 包装单章修复 splitter 假设（048a）⑥`_validate_plan_chapters_params` 行为变更（048b）⑦细纲"重生成"路径绕开指纹链陷阱（048c）。
- **指纹链 vs 手改设计反思**：红队的核心洞察是"自洽性约束被 PUT 设计错位绕过会破坏整个 stage④"。本轮的解决路径不是修补指纹算法、不是新增 reconciliation 代码、而是**改路径**——让所有"改细纲"都走 generate_chapter_plan 的天然指纹重算。这是产品设计层面消解工程暗礁的范例，比"指纹自洽 + 手改保险"的代码方案稳得多。
- **mock 与真实模型行为差异**：mock ChapterPlan 硬编码 5 章不响应 target_chapters，mock reviewer 默认 Reject 让 stage④ 必然 `retry_exhausted` —— 这两条都不是 bug，是 mock 设计的固有结构。真实模型下 plan-chapters 可生成不同章数、reviewer 可 Approve，workbench 端到端可在真实模型下完成首章生产。
- 验收命令需用 `.venv/bin/python`。
