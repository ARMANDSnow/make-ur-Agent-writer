# Iteration 058 — P0 修复：钱与静默错误（#1 预算失效 / #2 抽取吞错 / #6b NaN·Infinity 穿透）

> 承接 iter057「长程续写 capstone 前置：5 个结构性 bug 全修复」收官（1097 tests OK）。
> 来源：`docs/FRONTEND_BUG_AUDIT_2026-06.md`——codex 三-subagent 审计（报 14 条）+ Claude 实测取证（13 条实锤 + 2 新发现 NEW-A/NEW-B，含一次真模型最小 run 坐实 #1 烧钱）。
> 本轮只做该报告 §4 划定的 **iter058 · P0 段**：花钱 / 静默数据损坏三条最高优先 bug。修复哲学沿用项目铁律：复用已验证的护栏框架（不引入新机制）、守住默认路径 byte-identical、每条 bug 确定性单测兜底、按风险递增（#6b → #2 → #1）实施。全量 **1128 passed**（1097 基线 + 31 新）。

## Context

审计用真模型最小 run 端到端坐实 **#1**：onboarding 表单填 `budget_cny=0.001` 仍发出 **9 次真实调用 / 17.6k tokens / 293s**，预算全程被无视。根因——`run_auto_pipeline` 的签名根本没有 `budget_cny` 参数；wizard 把值放进 `job_params["budget_cny"]`，但 `_step_auto_pipeline` 既不读也不传（[jobs.py](../../src/web/jobs.py)）。预算护栏当时只在 write-book 路径生效。这是「用户明确填了上限却被烧钱」的 P0。

**#2**：`extract_all(raise_on_failure=False)` 默认吞掉单章抽取失败（写进 `data/extraction_failures/` 后照常返回部分结果），onboarding/单步 extract 两处调用都不传 `raise_on_failure` → 「准备成功」实则 KB 缺章，后续 bootstrap/debate/写作建在残缺数据上。注意：iter054c 曾**特意**让 onboarding 走 `raise_on_failure=False`（"尽量多抽"）——本轮经**用户拍板**覆盖为「混合」策略（见决策表）。

**#6b**：`_float_param`（routes）/ `_optional_float`（wizard）只做 `out<min`/`out>max` 比较，IEEE-754 下 NaN 的所有比较为 False → `budget_cny=NaN/Infinity`、`min_confidence=NaN`、`timeout_minutes=NaN` 全部 202 穿过。下游 `nan>0` 为 False 绕过成本闸；`timeout=nan` 使 deadline 永不触发 → 护栏静默失效，可无限烧钱。

**关键认知（修正审计 §3.1 的连带担忧）**：审计担心 `logs/llm_calls.jsonl` 只记 token 不记 cost_cny、"预算无从计算"。核验发现这**早已解决**——[cost_estimator.py](../../src/cost_estimator.py) 的 `estimate_cost_since(line_offset)` 直接从 token 日志按单价（USD/M × 7.2 汇率）算出 `cost_cny`，write-book / review-chapter 两条路径都在用它。**因此 #1 零日志格式变更，直接复用现成预算机制。**

## 三 bug 修复（按执行/commit 顺序：小→大）

| Bug | 级别 | 根因（已核验） | 修复 |
|---|---|---|---|
| **#6b** | 🔴 P0 | `routes._float_param` / `wizard._optional_float` 仅 `<min`/`>max` 比较，NaN/±Inf 全 False 穿过；下游成本闸（`nan>0`=False）与超时 deadline（`monotonic()>nan`=False）双双失效 | 两边界函数 `float()` 后、min/max 前插 `math.isfinite` 守卫 → 非有限即返回 `"… must be a finite number"`（对齐同文件 `_int_value` 风格）；两文件加 `import math`。**defense-in-depth**：jobs.py 内部那个同名裸-float `_float_param`（money/timeout 数学前最后一跳）非有限回落 default |
| **#2** | 🔴 P0 | `extract_all(raise_on_failure=False)` 默认吞错，`auto_pipeline._run_prepare_steps` / `jobs._step_extract` 两处调用都不传 → 静默残缺 KB 报成功 | **混合**（用户拍板）：单步 `_step_extract` 传 `raise_on_failure=True` + try/except `ExtractionBatchFailure` → `_blocked("extraction_failures", …)`（友好、可见、可重试，保留已抽章节）；onboarding `_run_prepare_steps` 传 `raise_on_failure=True` → loud raise（不在残缺 KB 上续跑，已抽章留盘 resume 补失败章）。与 `rebuild_for_start` 既有 True 对齐；不动 retry_failures |
| **#1** | 🔴 P0 | `run_auto_pipeline` 无 `budget_cny` 参数，`_step_auto_pipeline` 不读不传 → onboarding 预算完全失效 | `run_auto_pipeline`/`_run_prepare_steps` 接 `budget_cny`，复用 write-book 三件套（`BudgetExceeded`/`_llm_log_line_count`/`estimate_cost_since`，lazy import）在每个 LLM 步后结算成本、超限早停 raise；`_step_auto_pipeline` 读 `budget_cny`（缺省 `_default_budget_cny()`=10元，显式 0=不设限）、捕获 `BudgetExceeded` → write-book 同款 `budget_exceeded` 终态（已在 `TERMINAL_STATUSES`）；`_summarize_result` 顺带回显 cost/budget |

> commit：每条 bug 独立一轨（#6b / #2 / #1），hash 待入库。

## 关键设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| #1 早停 vs 仅事后结算 | **步间早停**（改 run_auto_pipeline） | review-chapter 仅"事后结算"是因其"无 inter-chapter checkpoint"（[jobs.py:514](../../src/web/jobs.py)）；auto-pipeline 有 9 个天然检查点，早停能真正止损（debate 后超限即跳过 plan 的 6 次 plot_planner 调用 + write）。符合审计「步间累计成本」原意 |
| #1 onboarding 默认上限 | **复用 `_default_budget_cny()`（10 元）** | 与 write-book 一致（iter050 已为同理由给 write-book 加默认上限）；显式 0=不设限保留 API/CLI 语义。暂不单设 `NOVEL_ONBOARDING_BUDGET_CNY`（按需再分，列入不在本轮范围） |
| #1 复用 vs 新成本日志 | **复用 `estimate_cost_since`** | 现成且已从 token 日志算出 cost_cny；推翻审计「需补 per-call cost 字段」担忧，零日志格式变更 |
| #1 BudgetExceeded 导入 | **auto_pipeline 内 lazy import `from .book_runner import …`** | 已核验 book_runner 不 import auto_pipeline（无环）；jobs.py 已是同款 lazy import 先例（[:531](../../src/web/jobs.py)）。lazy 使无预算 / CLI 路径零成本 |
| #1 默认路径 byte-identical | **budget_cny≤0 → `_budget_check` 保持 None** | `_run_prepare_steps` 与主体的检查点都 `if … is not None`，默认不发生任何额外调用 / progress；`test_auto_pipeline` 9 步标签契约不变 |
| #2 失败策略 | **混合**（单步 blocked / onboarding raise） | 用户拍板。单步给可重试温和出口；onboarding 拒绝在残缺 KB 上续跑。已抽章节均留盘，resume 补失败章。仅覆盖 iter054c 的 onboarding-only「尽量多抽」决定，其余路径不动 |
| #6b 实现 | **`math.isfinite` 单道守卫** | 一道收 NaN+±Inf；对齐同文件 `_int_value`；`config.parse_budget_cny` 早有 nan/inf 拒绝先例 |

## Acceptance / 验证

**全量 `.venv/bin/python -m unittest discover -s tests`：1128 passed / 0 failed**（347s 含 E2E；1097 基线 + 31 新）。分项实测：

- **#6b**：`tests/test_float_finite_guard.py` **14 passed**——两验证器单测（NaN/inf/-inf 拒、有限值与缺省/空白通过、JSON 原生 `float('nan')` 也拒）+ `_validate_write_book_params` 单测 + jobs.py defense-in-depth 回落单测 + e2e（`/run write-book` budget_cny/min_confidence NaN·Inf → 400、`/api/wizard/start` timeout_minutes·budget_cny NaN·Inf → 400）。
- **#2**：`tests/test_extract_failure_surface.py` **6 passed**——`_step_extract` 失败转 blocked + 断言 `raise_on_failure=True` + 成功路径不变；`_run_prepare_steps` 失败 loud raise + 断言 `raise_on_failure=True` + skip_extract 不 raise。
- **#1**：`tests/test_auto_pipeline_budget.py` **11 passed**——`_step_auto_pipeline` 默认/env/显式/0 不设限/greenfield 继承/`BudgetExceeded`→终态/summary 回显（成功路径 summary 不变）；`run_auto_pipeline` 早停（extract 后超限→不跑 compress/debate/write）/ 0 不设限不调 `estimate_cost_since`（byte-identical）/ 未超限跑完。
- **回归**：`test_auto_pipeline`（9 步进度契约）、`test_web_wizard_e2e`（mock onboarding 现带 10 元默认上限仍 succeeded）、`test_workbench_e2e`（prepare-greenfield 复合步不传 budget_check 不受影响）、`test_budget_guard`、extractor/iter055 resilience 全绿。

**真模型段（不在本轮强制）**：若复跑审计 `real_run.py`，`budget_cny=0.001` 的 onboarding 应在头几步内即 `budget_exceeded` 终态（而非 §3.1 全程 running 烧 293s）。本轮以 mock 确定性验收为准。

## 暗礁与教训

- **R1（/run 的 params 是嵌套的）**：`api_run_step` 从 `payload["params"]` 取参数，不是 body 顶层。首版 #6b e2e 误把 budget_cny 放 body 顶层 → params 为空 → 202 假绿，被自查抓到。验收 e2e 必须发 `{"step":…,"params":{…}}`。
- **R2（两个同名 `_float_param`）**：`routes._float_param`（校验、返 tuple、#6b 主目标）与 `jobs._float_param`（裸 float、内部）是**不同函数**。#6b 主改前者 + `wizard._optional_float`；后者按 defense-in-depth 加回落。
- **R3（默认路径 byte-identical 是硬约束）**：#1 改 `run_auto_pipeline` 时 `budget_cny≤0` 必须零行为变化——`_budget_check` 保持 None，所有检查点 `if … is not None` 短路。`test_auto_pipeline` 逐字断言 9 步标签 + `("done",1.0)`，跑它确认未破契约。
- **R4（onboarding 现有默认上限）**：把 onboarding 接上 `_default_budget_cny()` 后，mock onboarding 会在每步后调 `estimate_cost_since` 读 llm_calls 日志——mock 成本 ~0 < 10 不触发，但须实跑 `test_web_wizard_e2e` 确认日志读取不在首检查点（extract 后）前为空而出错（extract 已产生日志行，安全）。
- **R5（mock 成本≈0）**：#1 预算用例靠 patch `estimate_cost_since` 模拟超支，勿靠真实 mock 成本触发（不确定）。
- **R6（ExtractionBatchFailure 消息 clean）**：onboarding raise 后 job error 展示 `str(exc)`——本就是友好句（含失败章 id + Cloudflare Tunnel 提示 + "re-run resumes"），非 traceback。
- **R7**：测试用 `unittest discover` 非裸 `pytest`（conftest 注明后者泄漏 `.env`）。只 commit 不 push（沿用项目纪律，push 待用户）。

## 不在本轮范围

- **iter059（P1：崩溃与卡死）**：坏 JSON 共因 #4/#5/#10/#13（裸 `read_json`→`read_json_optional`/`*_invalid` blocker）、#8 auto-advance 读移入 try、#3+NEW-B 上传 UTF-8 校验 + 0 章回滚、#6a+NEW-A 整数上限 + catch OverflowError、#9 split gate 改认 `*.txt`。
- **iter060（P2：并发与体验）**：#7 start-point reservation、#11 writer-style 样本竞态、#14 drama 原子写、#12 协作式取消。
- onboarding 专属预算 env 旋钮（`NOVEL_ONBOARDING_BUDGET_CNY`）——本轮先复用 write 默认。
- 步**内**（单次 LLM 调用粒度）预算检查——本轮步间粒度足够覆盖 onboarding（chapters=1）。
- 本轮**未做真模型实跑**（按计划，MVP 全确定性、不烧钱）。

## 关键文件

**新增**：`tests/test_float_finite_guard.py`（#6b）、`tests/test_extract_failure_surface.py`（#2）、`tests/test_auto_pipeline_budget.py`（#1）。

**修改**：
- `src/web/routes.py` — `import math` + `_float_param` isfinite 守卫（#6b）
- `src/web/wizard.py` — `import math` + `_optional_float` isfinite 守卫（#6b）
- `src/web/jobs.py` — `_float_param` defense-in-depth（#6b）；`_step_extract` 转 blocked + import `ExtractionBatchFailure`（#2）；import `BudgetExceeded` + `_step_auto_pipeline` 读 budget/捕获终态 + `_summarize_result` 回显 cost（#1）
- `src/auto_pipeline.py` — `_run_prepare_steps` extract 传 `raise_on_failure=True`（#2）；`run_auto_pipeline`/`_run_prepare_steps` 接 `budget_cny` + 步间 `_budget_check` 早停（#1）
- `docs/AGENT_HANDOFF.md`、`docs/iterations/README.md`、`README.md`（登记）
