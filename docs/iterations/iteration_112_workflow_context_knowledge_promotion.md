# Iteration 112 - 迭代上下文清单与经验晋升门禁

## Context

现有 `iter-start -> 实施 -> iter-finish` 已具备固定八段、Acceptance ID、独立只读审查、implementation commit 与单次 canonical 验收，但实施者必读材料、预计变更面和各审查视角仍散落在 Plan/Acceptance prose 中，无法被稳定检查或直接交给 subagent。本轮在不安装 Trellis、不引入其代码/依赖和第二套状态系统的前提下，clean-room 吸收“实现/审查上下文分离”和“经验人工晋升”两项工作流经验。

## Plan

### Implementation Context

- `must_read`: `.agents/skills/iter-start/SKILL.md`, `.agents/skills/iter-finish/SKILL.md`, `scripts/check_agent_harness.py`, `tests/test_agent_harness.py`
- `expected_changes`: `.agents/skills/iter-start/SKILL.md`, `.agents/skills/iter-finish/SKILL.md`, `scripts/check_agent_harness.py`, `tests/test_agent_harness.py`, `docs/iterations/iteration_112_workflow_context_knowledge_promotion.md`, `docs/iterations/README.md`, `README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`; 私有 `data/outputs/logs` 内容；`小说txt/`; 用户未跟踪体检报告；产品运行逻辑；canonical verify 自管的 acceptance 产物除外

1. 保留固定八个 H2，在 Plan、Acceptance、Acceptance Result 内分别增加 `Implementation Context`、`Review Context`、`Knowledge Promotion` 固定 H3 与可机读字段。
2. 更新 `iter-start`，让后续迭代自动预填三块结构、字段语义、路径边界和风险专项视角规则。
3. 更新 `iter-finish`，要求审查前按实际 diff 复核上下文并向对应只读 subagent 提供视角材料，收官时人工填写经验晋升判断。
4. 扩展 agent harness，以 iter112 为结构启用边界，校验块/字段唯一性、路径安全、必读文件存在性及 accepted 后的经验晋升闭包；不迁移 iter001-111。
5. 为新旧格式兼容、结构失败、路径边界和经验晋升状态补聚焦测试；不增加 Acceptance 逐项文件映射、sidecar、journal、hooks 或自动知识抽取。
6. 聚焦检查与三视角审查完成后形成 implementation commit，只运行一次 `bash scripts/verify.sh`，再做 docs-only 收官提交；不运行真模型或 provider smoke。

## Acceptance

### Review Context

- `correctness_behavior`: 核对 iter001-111 向后兼容、iter112 新格式正反例、active/accepted 状态切换、Acceptance ID 与单次 canonical verify 旧约束不回归
- `security_boundary`: 核对绝对路径、路径穿越、私有目录、缺失 must_read、受保护 do_not_touch 表述及错误信息均 fail closed 且不读取私有内容
- `extra_risk_view`: `workflow/backward-compatibility`，核对两项 skill、checker、测试与 iter112 自举格式一致，且不产生第二套工作流真源

- **A112-01**：iter112 起的最新 iteration 必须在正确 H2 内各有且仅有一个 `Implementation Context`、`Review Context`、`Knowledge Promotion`；必填字段唯一、非空，实施/审查字段不得保留占位符，iter001-111 无需迁移且继续通过。
- **A112-02**：`must_read` 与 `expected_changes` 只接受仓库相对安全路径，拒绝绝对路径、`..`、`.env`、`data/`、`outputs/`、`logs/`、`小说txt/`；`must_read` 必须存在，`expected_changes` 允许计划中新文件，`do_not_touch` 可显式列出受保护边界。
- **A112-03**：active iter112 允许 `Knowledge Promotion` 待 `iter-finish` 回填；accepted 后 `decision=none` 必须配 `destination=none` 和非空 reason，`decision=promoted` 只能指向既有长期权威文档并带非空 reason。
- **A112-04**：`iter-start` 与 `iter-finish` 明确上下文清单的生成、审查前复核、按视角派发和人工经验晋升语义；不新增 Trellis 依赖、`.trellis/`、task JSON、journal、hook 或自动长期文档写入。
- **A112-05**：聚焦测试、语法检查、harness 与 diff 检查通过；correctness/behavior、security/boundary、workflow/backward-compatibility 三个只读视角无未处理 P0/P1/P2。修复 findings 后只运行一次 canonical `bash scripts/verify.sh`，最高验收等级为 `mock-functional`，不运行任何真 provider。

## Implementation Notes

- checker 以 `STRUCTURED_CONTEXT_FROM_ITER = 112` 为唯一迁移门槛；只检查 latest iteration，iter001-111 保持原结构。三个固定 H3 必须各自唯一且位于指定 H2，字段解析忽略 fenced code，避免示例文本冒充真实清单。
- `must_read` 与 `expected_changes` 使用逗号分隔的反引号仓库相对路径。两者均拒绝绝对路径、Windows/backslash 变体、`..`、`.env*`、私有根目录和解析后越界；`must_read` 额外要求现有普通文件，`expected_changes` 允许尚未创建的安全路径。
- active iteration 的 Knowledge Promotion 只能是三项全部待填或三项全部有效；accepted 后 `none`/`promoted` 分支 fail closed。`promoted` 目标必须存在、Git tracked、非 symlink 且属于现有长期权威文档白名单，README/handoff 不作为经验晋升目标。
- 两项 workflow skill 已加入生成、审查前复核、按视角派发和人工晋升规则；经验判断前移到 findings 稳定后、implementation commit 前，非 docs-only 晋升必须进入唯一验收。未增加 Trellis 代码/依赖、sidecar、journal、hook、自动写入或第二套状态。
- 首轮 correctness/behavior、security/boundary、workflow/backward-compatibility 审查确认并修复四组重叠 finding：fenced H2 截断、symlink/未跟踪/大小写私有路径绕过、accepted 前轮被 active 后轮遮蔽、路径列表分隔符过宽；同时收紧 TMPDIR 白名单并修正晋升落地时机。
- checker 改为 fence-aware H2/H3/字段同源解析，严格对齐 CommonMark closing fence、backtick info、0-3 空格 ATX 标题/列表字段与 closing `#`；accepted document 始终按完成态复核，active latest 另行按进行态校验。路径解析拒绝 Windows drive、NUL、非 canonical POSIX、受保护根、symlink/loop、越界、解析异常和既有非普通文件；`must_read` 必须 tracked。
- `tests.test_agent_harness` 增至 51 tests，覆盖 iter111 旧格式、active/accepted iter112/113、块/字段唯一性、checker/renderer 双视图 spoof、严格分隔符、tracked/symlink/private/casefold/异常路径、未来文件、基础审查视角和经验晋升正反例。
- 聚焦测试首次暴露 macOS 会在 fixture `TMPDIR` 生成非项目的 `xcrun_db`；测试只白名单这个已确认的平台项，其余任何临时残留仍失败，生产 `verify.sh` 未改。这是计划内测试文件中的环境兼容修复，无产品范围扩张。
- 审查修复后聚焦结果：51 tests OK；checker 专项 37 tests OK；`py_compile`、agent harness（accepted 111 / active 112 / 121 entries）与 `git diff --check` 通过。
- security 视角建议强制 `do_not_touch` 重复五项全局禁区，主线程未采纳：该字段按批准契约只补充本轮边界、不替代 `AGENTS.md`；已采纳其“所有 reviewer 同时收到 do_not_touch”建议。
- correctness/behavior、security/boundary、workflow/backward-compatibility 三个独立只读视角完成二次复核，所有已确认 findings 均关闭，最终无遗留 P0/P1/P2。

## Acceptance Result

<iter-finish 回填 A112-01 至 A112-05、implementation commit、canonical 证据、审查结论与未修风险。>

### Knowledge Promotion

- `decision`: `promoted`
- `destination`: `.agents/skills/iter-start/SKILL.md`, `.agents/skills/iter-finish/SKILL.md`, `docs/PROJECT_HISTORY.md`
- `reason`: 实现/审查上下文分离、tracked 安全路径和验收前人工经验晋升属于后续每轮都要遵守的长期工作流规则；两项 skill 已在 implementation 范围落地，阶段历史在 docs-only 收官同步。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_112_workflow_context_knowledge_promotion.md` | 新建 iter112 固定八段计划与结构化上下文/经验晋升契约 |
| `docs/iterations/README.md` | 追加 iter112 canonical index |
| `.agents/skills/iter-start/SKILL.md` | 后续 iteration 骨架加入三个固定 H3、字段语义与路径/风险边界 |
| `.agents/skills/iter-finish/SKILL.md` | 审查前复核并按视角派发上下文，收官人工完成经验晋升判断 |
| `scripts/check_agent_harness.py` | iter112+ 结构化上下文、路径安全与 accepted 经验晋升门禁 |
| `tests/test_agent_harness.py` | 新旧格式、fail-closed 路径/结构/晋升测试及 macOS 临时目录夹具硬化 |

## 不在本轮范围

- 安装、vendoring 或运行 Trellis；引入其源码、prompt、依赖、许可证负担或生成目录。
- `.trellis/`、task JSON、sidecar manifest、journal、channel、hook、自动知识抽取、自动长期文档写入或第二套任务状态机。
- Acceptance 逐项 Related files/Promise 元数据、产品运行逻辑、Web/runner/provider/media 行为和公开 API。
- 真文本、真生图、真视频、真 ComfyUI、真实 provider 请求或计费验证。
- `.env`、私有 `data/outputs/logs`、`小说txt/` 与用户未跟踪文件。

## Notes

- 本轮严格使用仓库内 `iter-start` 与 `iter-finish`；立项后实施，收官只 commit、不 push。
- `expected_changes` 是路由与审查提示，不是 Git 硬白名单；必要范围变化必须写入 Implementation Notes。
- README 与 handoff 的常规状态同步不计入 `Knowledge Promotion`；长期经验只允许人工晋升到现有权威文档。
- 立项提交信息草案：`docs(iter112): 迭代计划 112 立项（上下文清单与经验晋升门禁）`。
