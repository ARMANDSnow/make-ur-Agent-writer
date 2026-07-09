# Iteration 082 - 短剧 drama_reviewer + 整集组装 + episodes 页

## Context

Iteration 080/081 已把短剧站③分镜 grid、站④角色表、角色库与 AI 绘画安全骨架打通；短剧 4 站已经可以产出核心设定、钩子、分镜和角色三件套。路线图 `iteration_079_083_drama_module_roadmap.md` 原计划的 `drama_reviewer + 整集组装 + episodes 页` 因编号平移成为本轮实际 iter082。

本轮目标是把 4 站产物组装成一个可复核的 episode 真源，并提供轻量 drama reviewer 与 Web episodes 页面，形成“生成 → 编辑 → 评审 → 组装 → 查看”的闭环。仓库外默认计划文件 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在；本轮依据 handoff、iter081、短剧路线图与只读 subagent 摸底结论执行。

## Plan

- 新增 drama reviewer：独立轻量实现，不复用 novel reviewer；新增 review schema、5 维子分、advisor suggestions 与本地确定性 verdict 推导。
- 新增整集组装：把 setup、storyboard、character sheet、review 组装为 `episode_01.json` 与 meta，记录输入指纹并暴露 stale 状态。
- 新增 episodes Web/API：review、assemble、apply suggestion、episodes 列表、episode 详情；写作页站④后提供“评审并组装”CTA。
- 新增 5 赛道 review fixtures 与测试：金路径 Approve，Reject/Abstain/parse failed/分数护栏用测试内联构造。
- 严守 scope：不做导出四格式、Insights、第 2 集重生、job 化、站①②真模型补课、真模型 smoke 或真实绘图 API 实测。

## Acceptance

- 5 赛道 mock 从站①②③④到 review + assemble + episode detail 走通。
- verdict 三分支确定性：任一子分 <5 -> Reject 并映射回站点；全 >=7 -> Approve；其余 -> Abstain + advisor。
- 分数护栏覆盖数字字符串、bool、NaN/Infinity、越界 clamp 与 `score_warning`。
- reviewer parse failed 返回 Abstain + `needs_human_review=true`，不伪造 Reject。
- `assemble_episode()` 幂等；缺前置文件 400 并指出缺哪站；分站内容变化后 episode detail 显示 stale。
- novel workspace 400；bad episode_no 400；Web route 在真实配置态仍固定 mock，不触发真模型。
- 验收命令：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`、`git diff --check`。不跑真模型 smoke（铁律⑥）。

## Implementation Notes

- `drama_reviewer` 独立于 novel reviewer：单 agent、5 维子分、本地确定性 verdict，不复用章节 panel / lint / tier 逻辑。Web review 端点本轮固定 `mock=True`，避免真实配置态误触真模型。
- `DramaReview` 对模型 verdict 只做输入参考；最终 verdict 由本地子分推导：任一 `<5` 为 Reject，全 `>=7` 为 Approve，其余 Abstain。parse failed 特判为 Abstain + `needs_human_review=true`。
- `drama_store.assemble_episode()` 把 setup、storyboard、characters、review 组装为 `episode_01.json` 与 `episode_01.meta.json`，meta 记录 canonical input fingerprint；后续分站内容变化后 episode detail 可标记 stale。
- Web 新增 `/w/{name}/episodes` 与 `/w/{name}/episode/1`，episode detail 以只读 tabs 展示剧本、分镜、角色、评审与导出占位；站④新增“评审并组装”CTA。
- `apply-suggestion` 本轮只做结构化轻量应用：setup/hook/storyboard/characters 四站就地写回并触发 stale；复杂多轮 rewrite、自动重评审与 job 化留后续。
- 收尾只读 code review 发现 2 项有效问题并已修：真实 reviewer exception fallback 原会把 dict 再交给 `model_to_dict` 崩溃；`episode_no=1.9` 原会被 `int()` 截断到 1。分别补回归测试。
- 安全审查未发现 API key / `.env` 泄漏、未发现 tracked diff 触碰受保护路径；提醒未跟踪 `续写工作台.pptx` 为 61MB 二进制且有版权边界风险，本轮保持不 staged、不提交。

## Acceptance Result

- 聚焦回归：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_drama_reviewer tests.test_drama_store tests.test_drama_episodes_api tests.test_drama_fixture_lint tests.test_web_routes_get -v` = **108 tests OK**。
- 语法/静态检查：`py_compile` 覆盖触达 Python 模块 OK；`node --check /tmp/iter082_app.js` OK；`git diff --check` OK。
- 全量单测：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests` = **1707 tests OK**。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` exit 0（内部同样 **1707 tests OK**，随后 mock auto-pipeline/status/manifest/report/cost 全过；LiteLLM 远程 cost map timeout fallback 与 `botocore` 缺失为既有非阻断 warning）。
- `.venv/bin/python3 main.py preflight` = warn / 无 FATAL（既有 tiktoken/model cache/NOVEL_DEFAULT_BUDGET_CNY warning）；`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = ok / 无 WARN。
- 铁律⑨审查：2 个只读 subagent 并行完成 correctness 与 security/boundary review。Correctness P1/P3 已修并补测；security 无 HIGH/MED tracked diff 问题，确认 Web review 不触发真模型，未跟踪 PPTX 不纳入提交。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/drama_schemas.py` | 增加 episode/review schema、review score guard、verdict 推导、episode/meta model 与 review/station path。 |
| `src/drama_reviewer.py` | 新增轻量 drama reviewer runner、prompt 构造、mock fixture/真模型 wiring 与 parse failed fallback。 |
| `src/drama_store.py` | 新增 episode assembly、list/detail/stale/fingerprint helper。 |
| `src/web/routes.py` | 新增 drama review / assemble / apply-suggestion / episodes API 与 episode 页面路由，补 strict `episode_no` 解析。 |
| `src/web/templates.py` | 新增 episodes 列表页与 episode detail tabs，drama 侧栏加入 episodes。 |
| `src/web/static.py` | 站④“评审并组装”CTA、episodes/detail 前端渲染、review card、suggestion 应用与 tab whitelist。 |
| `config/models.yaml` | 新增 `drama_review` task 配置。 |
| `prompts/drama/drama_reviewer.txt` | 新增短剧整集评审 prompt。 |
| `tests/fixtures/drama/*_review.json` | 新增 5 赛道原创 review fixtures。 |
| `tests/test_drama_reviewer.py` | 覆盖 mock/real wiring、三分支 verdict、score guards、parse failed fallback。 |
| `tests/test_drama_store.py` | 覆盖 assemble、幂等、缺 review、stale、list/detail。 |
| `tests/test_drama_episodes_api.py` | 覆盖 API 金路径、前置缺失、novel workspace、bad episode_no、真实配置态 mock-only、busy、apply suggestion、页面渲染。 |
| `tests/test_drama_fixture_lint.py` / `tests/test_web_routes_get.py` | 接入 review fixture lint 与 episodes route/static string 回归。 |
| `docs/iterations/README.md` / 本文件 | 登记 iter082。 |

## 不在本轮范围

- JSON/MD/CSV/Comfy 四格式导出与导出 tab 实装。
- Insights 页面、第 2 集重生与 episode_no 全链参数化。
- 站①②真模型补课、每站 job 化、`scripts/drama_smoke.sh`。
- 真模型 smoke、真实 AI 绘画 API 实测。
- 小说主链路 capstone 真模型长跑。

## Notes

- 本轮立项显式使用 `iter-start` skill；实现时使用 subagents 做只读摸底与收尾审查。
- 当前工作树中未跟踪 `续写工作台.pptx` 视为用户文件，保持不动。
- 路线图原 “iter082 导出 + Insights + 第 2 集重生” 因前序编号平移顺延；本轮实际承接原路线图 “drama_reviewer + 整集组装 + episodes 页”。
- 真模型 smoke 与真实 AI 绘画 API 实测未跑，遵守铁律⑥。
