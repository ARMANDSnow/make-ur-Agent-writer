# Iteration 088 - 短剧四格式导出 + Insights + 第 2 集重生

## Context

Iteration 080-082 已完成短剧站③分镜、站④角色与角色库、AI 绘画安全骨架、轻量 drama reviewer、整集组装以及 episodes 列表/详情复核页；Iteration 083-087 的文风指纹路线也已收官。当前短剧链路能生成、编辑、评审和组装第 1 集，但导出 tab 仍是占位，产品侧没有聚合指标，且多个站点仍被 `episode_01` 单集假设锁定。

本轮回到 `iteration_079_083_drama_module_roadmap.md` 中因编号平移而顺延的“导出 ×4 + Insights + 第 2 集重生”，把当前单集复核闭环推进为可交付、可观察、可多集延续的 mock 产品闭环。约定的 `~/.claude/plans/docs-rosy-wadler.md` 不存在；本轮以路线图原 iter082 切片、iter082 收官记录、AGENT_HANDOFF 以及用户本轮选定方向为准，旧计划中的编号与测试基线按 iter088 / 1775 tests 更新。

## Plan

- 以 `episode_NN.json` 为唯一导出真源，实现 JSON、Markdown、CSV 和 Comfy workflow 四种导出；导出内容与 episode detail 使用同一口径。
- 新增纯本地 `comfy_workflow_exporter`，为每镜构建模板节点链并写入 `_generator` 版本标记；产品文案明确“模板级导出，导入后仍需按本地模型/workflow 接线”。
- 新增 drama Insights：并列展示 drama LLM 日志成本与 episode meta 成本，统计时长达标率和钩子类型分布；缺目录、坏日志行、旧 meta 缺字段时 graceful degrade。
- 将 planner、hook、storyboard、characters、drama view/grid、review/assemble 和相关 Web/API 的 `episode_no` 全链参数化，统一复用严格正整数解析与 `episode_paths()`，保持 episode 1 行为兼容。
- 增加“开始下一集”流程：站①继承上集核心设定且不调用 LLM；站②注入已用钩子清单并在 mock 下返回新候选；站③注入季角色 visual signature；无新角色时站④可标记 `skipped` 并继续评审/组装。
- 实装 episodes/detail 页四个导出按钮、Insights 入口、多集列表和“开始第 N+1 集”CTA。
- 新增 5 赛道 episode 2 hook fixtures、导出 golden、Insights 与多集回归；先以 episode 1 兼容测试钉住参数化重构，再接 episode 2。

## Acceptance

- episode 1 的 JSON/Markdown/CSV/Comfy 四种格式均可下载，并按约定的 `episode_NN.*` 路径落盘；JSON 与 Comfy 输出可解析。
- Comfy workflow 为每镜生成至少一个 SaveImage 节点并保留 `_generator` 版本标记；实现全程无网络、不调用真实 AI 绘画 API。
- CSV 使用 `utf-8-sig`，BOM 与 quoting 有回归测试；导出格式严格走白名单，路径式/非法 format 输入返回 400，服务端独立生成文件名与 Content-Disposition。
- episode 1 参数化前后保持兼容，既有 review、assemble、stale fingerprint、episode detail 与 5 赛道 mock 流程不回归。
- episode 2 mock 全链通过：继承上集核心设定、3 个钩子候选与 episode 1 已选项不同、站③输入含季角色 visual signature、无新角色可跳过站④并继续评审/组装。
- Episodes 列表显示两集；Insights 在 0/1/多集下均不崩，mock 成本恒为 0 并注明真模型启用后才产生真实费用。
- `episode_no` 严格拒绝 bool、浮点、非有限值、非正整数与越界值；定向检查确认站点实现不再被 `episode_01` 字面量锁死，fixture/兼容说明仅按显式白名单排除。
- canonical unittest 在 1775 基线上全绿；`scripts/verify.sh` exit 0；真实配置 preflight 无 FATAL，mock preflight ok；Python/Node 语法检查与 `git diff --check` 通过。不跑真模型 smoke。
- 收官按铁律⑨至少执行 correctness 与 security/boundary 两个独立只读 subagent 审查；因涉及 Web/API 与多 workspace 路径，增加 Web/integration 视角并将 findings、修复和复核结论写回本文。

## Implementation Notes

- `episode_NN.json` 是导出唯一真源，不允许各格式从分站文件临时拼装出不同口径；stale episode 应沿用既有提示语义。
- 参数化重构先钉住 episode 1 路径、fixture、指纹和 API 兼容，再引入 episode 2，降低横跨多站点的回归风险。
- Insights 读取 `llm_calls.jsonl` 时只聚合 `drama_` task，坏行跳过并留统计口径；不得回显 prompt、error 原文、key 或其他敏感字段。
- 第 2 集“钩子必新”在 mock fixture 中做确定性断言；真模型路径只通过已用钩子 prompt 排除和 reviewer cliffhanger 维度兜底，不夸大为确定性保证。
- Comfy 导出保持纯函数和版本化模板；本轮不承担具体 ComfyUI checkpoint、LoRA 或本地节点兼容性。
- 前端优先复用既有 tabs、toast、错误卡和严格 episode number helper，避免继续无界膨胀 `static.py`；若实现明显超出既有路线图的约 350 行 JS 预算，需在 Notes 解释并拆分。

## Acceptance Result

完成。episode 1 维持既有 review、assemble、stale fingerprint 和 detail 行为；在完成组装后可从 detail 下载 `episode_01.json`、`.md`、`.csv` 和 `.comfy.json`。JSON 作为单一快照真源，CSV 带 UTF-8 BOM、CRLF/引用与公式注入中和，Markdown 转义原始 HTML，Comfy 输出为无网络的版本化模板工作流，每镜至少一个 SaveImage 节点。

Insights 同时展示短剧任务 LLM 日志成本、episode meta 成本、时长达标率与钩子类型分布；只读取 `drama_` task，坏日志、坏 meta、缺目录和 0/1/多集状态都降级处理，不回显 prompt、错误原文或敏感字段。mock 成本为 0，并明确提示真实成本仅会在启用真模型后产生。

episode 参数化已贯穿 stations、存储、schema、view 和 Web API。第 2 集必须经 `next-episode` 从已完整组装、指纹有效的第 1 集初始化；站①在本地继承核心设定而不调 LLM，站②排除已用钩子，站③接收季角色 visual signature。无新角色时站④明确为 `skipped` 并可继续评审/组装；有新角色时则强制生成第 2 集角色表。当前 CTA 和路由有界地只支持启动第 2 集，不会伪装为无限季级生成。

收官三视角只读审查均为 PASS。correctness 首审发现直接 `/drama/plan` 可绕开后续集门禁、下一集对部分 artifact/meta/指纹 fail-open 且锁外预检有 TOCTOU、episode 3 CTA 会误用 episode 2 hooks、schema 会 coercion bool/float/string、站④ skipped/appearance 语义不完整；均已修复。第二轮补出“有新角色时可绕过角色生成”与 locked appearance 丢失，也已修复并复核 PASS。security/boundary 首审发现 next-episode meta/fingerprint fail-open、TOCTOU、导出读取/写入竞态、Insights 数值无界/非有限值、Markdown raw HTML；均已收口；复核再发现 Insights 会把 `true`/`1.0` 当作同一集，已改为严格整数 identity 后 PASS。Web/integration 首审发现导出 href 信任 artifact `episode_no`、skipped UI 语义错配；后续与角色门禁/appearance 两项交叉复核均 PASS。

验收命令及结果：

- `OPENAI_MODEL=mock PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`：**1813 tests OK**（291.134s）。
- 收官修复后的定向 exports/Insights/episode2/Web 回归：**41 tests OK**；随后新增的角色门禁、locked appearances、Insights 严格 identity：**3 tests OK**。
- `PATH="$PWD/.venv/bin:$PATH" OPENAI_MODEL=mock bash scripts/verify.sh`：exit 0（内部 **1813 tests OK** / 300.019s，随后 mock auto-pipeline、status、manifest、review report、cost 全部通过）。
- `.venv/bin/python3 main.py preflight`：warn、无 FATAL；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：ok、无 WARN。
- 全量 `src` `py_compile`、`node --check`（dashboard/wizard/settings 三份 bundle）与 `git diff --check` 均通过。

未运行真模型、真绘图或真实 ComfyUI smoke（铁律⑥；本轮未获授权）。

## 文件变更汇总

| 状态 | 文件/子系统 | 实际改动 |
| --- | --- | --- |
| 新增 | `src/comfy_workflow_exporter.py` | Comfy workflow 纯函数、版本化模板和每镜 SaveImage 节点。 |
| 新增 | `src/web/drama_insights.py` | 短剧成本、时长达标率与钩子分布的有界聚合。 |
| 修改 | `src/drama_schemas.py`、`src/drama_store.py`、`src/{drama_planner,hook_designer,storyboard_builder,character_designer,drama_reviewer}.py` | 严格 episode number、四格式导出、所有 station 的 episode 参数化、第 2 集继承与角色 appearance 语义。 |
| 修改 | `src/web/{routes,server,templates,static,drama_view}.py` | 导出 API/安全响应头、drama Insights、episode 深链、下一集 CTA 与 station④ skipped/new-character UI。 |
| 新增/修改 | `tests/fixtures/drama/`、`tests/test_drama_exports.py`、`tests/test_drama_insights.py`、`tests/test_drama_iter088_web.py` 及既有 drama/Web 测试 | 五赛道第 2 集 hooks、导出/Insights golden、兼容性、竞态和安全边界回归。 |
| 修改 | 本文、`docs/iterations/README.md`、`README.md`、`docs/AGENT_HANDOFF.md`、`AGENTS.md` | iter088 收官记录、实时 SOP 与交接点。 |

## 不在本轮范围

- 站①②真模型补课、五站 job 化、202/poll/cancel 迁移与 `scripts/drama_smoke.sh`。
- 真模型 smoke、真实 AI 绘画 API 或真实 ComfyUI workflow 可用性实测。
- 小说主链路 10-20 章 capstone 长跑。
- 文风自动修文阈值/费用校准，或把 `style_drift_unresolved` 升级为阻断。
- 自动生成第 3 集及以上的长程季级规划；本轮只用第 2 集验证 episode 参数化与重生机制。

## Notes

- 本轮已显式使用 `iter-start` 与 `iter-finish` skill 完成开工和收官。
- 计划来源为 `docs/iterations/iteration_079_083_drama_module_roadmap.md` 原 iter082 切片；因 iter079 被 capstone hardening 占用、iter083-087 转入文风路线，实际编号顺延为 iter088。
- 最大回归风险是 `episode_no` 参数化破坏 episode 1 路径、fixture 命名、stale fingerprint 或 Web 深链；实现与验证应把这一风险作为独立切片处理。
- 不改 `.env`，不主动读写 `data/`、`outputs/`、`小说txt/` 或用户私有样本，不跑真模型；`verify.sh` 仅按既有授权写 gitignored 验收产物。
- 当前未跟踪 `续写工作台.pptx` 是用户文件，本轮保持不动、不 staged、不提交。
- 未提交、未 push。提交信息草案：`Iteration 088: add drama exports insights and episode 2`。
