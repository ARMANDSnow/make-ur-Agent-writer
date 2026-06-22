# 前端用户路径 Bug 实测取证报告（codex 三-subagent 审计复核）

> 日期：2026-06-22 · 复核人：Claude · 状态：**实测取证完成，供后续 bugfix iter 领取**
> 方法：3 个 Explore agent 逐行核对代码 + 自建 mock 隔离探针实跑（`routes.dispatch` 走真实前端代码路径）+ 一次最小真模型 onboarding。
> 安全边界：全程 mock/隔离 throwaway workspace + 一次真模型用独立 `audit_real_probe`，**未触碰用户小说 / 真实 data·outputs / .env 值**。探针脚本存于 `/tmp/audit_probes/`。

---

## 0. 总结论

codex 这轮审计**质量很高**：报的 14 条，**13 条完全属实、1 条（#8）机制属实但有状态细节**，**无一误报**。实测中我**另外发现 2 个新 bug**（NEW-A 整数 Infinity→500、NEW-B 非 UTF-8 上传被接受）。

一个**共因**贯穿 #4/#5/#10/#13：关键状态文件用了**裸 `read_json()`（存在但损坏→抛 `JSONDecodeError`）**而非带兜底的 `read_json_optional()`（[utils.py:15 vs 21](src/utils.py:15)）。一个统一改法可同时收掉这四条。

| # | 论断 | 判定 | 实测证据（关键） |
|---|------|------|------|
| 1 | 预算字段 onboarding 路径失效 | ✅ 实锤 | budget_cny=0.001 → mock 下 job succeeded、不触发 budget_exceeded；真模型实测 **9 次真实调用 / 17.6k tokens / 293s 仍 running**，预算全程被无视（见 §3.1） |
| 2 | 抽取失败被静默吞 | ✅ 实锤 | 第2章抽取抛错 → `extract_all` **不抛**、返回 1 条结果、写 1 个 failure 文件；`raise_on_failure` 默认 False 且调用方不传 |
| 3 | 空/无章节书 → workspace 滞留 + 重传 409 | ✅ 实锤 | 无章节 TXT → job **failed** + workspace **滞留** + 重传同名 **409**，须手删 |
| 4 | 坏 chapter_plan.json → traceback | ✅ 实锤 | write-book job **硬 failed**(raw JSONDecodeError)；GET /readiness 降级成泄露原始异常的 `readiness_error:` blocker，均非干净 `chapter_plan_invalid` |
| 5 | 坏 draft meta/review → 击穿恢复 | ✅ 实锤 | `chapter_status()` 直抛 JSONDecodeError；resume/status 受影响（readiness 在前置 blocker 缺失时会先短路） |
| 6a | Web 整数参数无上限 | ✅ 实锤 | chapters=999999999 → **HTTP 202 接受**（对比 plan-chapters 有 maximum=200） |
| 6b | NaN/Infinity 穿过浮点校验 | ✅ 实锤 | budget_cny=**NaN 和 Infinity 都 202 穿过**；min_confidence=NaN 穿过；NaN 让预算/超时判断全部失效 |
| 7 | 起点保存无 workspace 互斥 | ✅ 实锤 | workspace reserved 时 /run 被 409 挡，**/start-point 却穿过** |
| 8 | auto-advance 已批准后炸整轮 | ✅ 实锤 | 坏 entity_graph → `_auto_apply_advances` 抛**未捕获** JSONDecodeError（读在 try 之外）；正文已落盘故是"job failed + 内容已写"的割裂态 |
| 9 | split 单步找 \*.md 但 normalize 出 \*.txt | ✅ 实锤 | normalize 出 `.txt`、零 `.md`，split 单步 → `blocked: normalized_missing` |
| 10 | rolling summary 文档说降级、实际阻断 | ✅ 实锤 | 坏 JSON → JSONDecodeError，与 docstring "malformed degrade" 直接矛盾 |
| 11 | writer-style 固定临时文件竞态 | ✅ 实锤 | 固定 `.writer_style_sample.tmp`，写在抢 job 锁之前；两并发 → [202,409]，胜者 job 可能读到败者样本 |
| 12 | cancel/timeout 仅 checkpoint 检查 | ✅ 属实（代码实锤） | `_check_cancelled` 只在 `_progress` 间隙跑；长 LLM 调用期间不可中断（真模型实测见 §3.3） |
| 13 | driver state/pid 坏 JSON 无诊断降级 | ✅ 实锤 | `load_state`/`_another_driver_running` 裸 read_json → JSONDecodeError，无 `driver_state_invalid` 提示 |
| 14 | drama 写端点同步/非原子/无 reservation | ✅ 实锤 | PUT /drama/setup 在 reserved 时仍 **200 穿过**；裸 write_text 非原子（对比 utils 已有原子 write_json） |
| **NEW-A** | 整数参数 Infinity → 500（非 400） | 🆕 新发现 | chapters=Infinity → `int(float('inf'))` OverflowError 未捕获 → **HTTP 500 trace_id**；chapters=NaN → 干净 400 |
| **NEW-B** | 非 UTF-8 二进制 .txt 被接受 | 🆕 新发现 | 二进制 .txt → **202 接受** → job failed → workspace 滞留 → 重传 409（#3 同族，上传层无内容/编码校验） |

---

## 1. 测试方法与可信度

- **入口忠实**：所有 Web 探针通过 `src.web.routes.dispatch(method, path, body, headers)` 调用 —— 这正是 HTTP server（`http.server`）分发到的同一套 handler，与前端 POST 完全同路径（参考 `tests/test_web_wizard_e2e.py` 样板）。
- **mock 隔离**：`OPENAI_MODEL=mock` + 清空真模型 key + `paths.WORKSPACE_DIR` 指向临时目录 + `jobs.reset_for_tests()`，零 API 费用、零真实数据接触。
- **真模型一次**：`audit_real_probe` 独立 workspace + `LLM_REQUEST_TIMEOUT=90`（per-call 超时兜底）+ watchdog 硬退出 + 1 章极小样本，跑真实 onboarding 取费用账本。
- **探针脚本**：`/tmp/audit_probes/probe_phase1.py`、`probe_phase2.py`、`probe_phase3_misc.py`、`probe_phase4b.py`、`real_run.py`。

---

## 2. 逐条详情

### P0 —— 花钱 / 静默数据损坏

#### #1 预算字段在 onboarding 路径完全失效 · ✅ 实锤
- **真实复现**：wizard 上传带 `budget_cny=0.001` → job `succeeded`，**不触发** `budget_exceeded`。真模型实测见 §3.1（真实扣费远超 0.001）。
- **根因**：wizard 把 budget_cny 放进 job_params（[wizard.py:185](src/web/wizard.py:185)）→ job kind=`auto-pipeline-greenfield`（[wizard.py:191](src/web/wizard.py:191)）→ `_step_auto_pipeline`（[jobs.py:597](src/web/jobs.py:597)）调 `run_auto_pipeline(...)`，而该函数签名**根本没有 budget_cny 参数**（[auto_pipeline.py:150](src/auto_pipeline.py:150)）。预算只在 write-book 路径生效（[jobs.py:590](src/web/jobs.py:590)）。
- **用户场景**：新书 onboarding 表单填了预算上限 → 被完全无视 → 9 步链路一路烧钱。
- **修复方向**：`run_auto_pipeline` 接 budget_cny 并在步间累计成本 → 超限提前 `budget_exceeded`；或 onboarding 表单暂时下掉预算字段直到接通。

#### #2 抽取失败被静默吞、上层照报成功 · ✅ 实锤
- **真实复现**：构造 2 章 manifest、令第 2 章抽取抛错 → `extract_all(raise_on_failure=False)`（调用方默认用法）**返回 1 条结果、不抛异常**，失败章只写进 `data/extraction_failures/`；同条件 `raise_on_failure=True` 则抛 `ExtractionBatchFailure`。
- **根因**：[extractor.py:480](src/extractor.py:480) `except Exception` 吞错 → [extractor.py:497](src/extractor.py:497) 仅当 `raise_on_failure` 才抛（默认 False）；`auto_pipeline.py:101` 与 `jobs.py:358` 调用时都不传。
- **用户场景**：上传整本书，个别章抽取失败（网络/Tunnel 抖动）→ "准备成功"，实则 KB 残缺，后续 bootstrap/写作基于缺章数据。
- **修复方向**：onboarding/prepare 路径传 `raise_on_failure=True`，或把失败章升级为 `blocked` 让前端可见、可重试。

#### #6b NaN/Infinity 穿过浮点校验，预算与超时双双失效 · ✅ 实锤（比报告更严重）
- **真实复现**：`POST /run write-book` 注入 `budget_cny=NaN` → **202**；`budget_cny=Infinity` → **202**（budget_cny 无 maximum，两者都穿）；`min_confidence=NaN` → **202**（`nan>1.0` 为 False）；`min_confidence=Infinity` → 400（有 maximum 挡住）。
- **根因**：[routes.py:1925](src/web/routes.py:1925) `_float_param` 仅 `out<min`/`out>max` 比较，对 NaN 全 False；同理 [wizard.py:438](src/web/wizard.py:438) `_optional_float`。下游 `budget_cny=nan` 使 `nan>0` 为 False 绕过成本闸（[jobs.py:590](src/web/jobs.py:590)）；`timeout_minutes=nan` 使 `nan<=0` 为 False → deadline=nan → `monotonic()>nan` 永 False → **永不超时**（[jobs.py:235](src/web/jobs.py:235)）。
- **用户场景**：API 直调或异常输入注入 NaN → 预算/超时护栏静默失效，可无限烧钱。
- **修复方向**：`_float_param`/`_optional_float` 增加 `math.isfinite()` 校验，非有限即 400。

---

### P1 —— 崩溃 / 卡死用户

#### #3 + NEW-B 空/无章节/非 UTF-8 上传 → job 失败 + workspace 滞留 409 · ✅ 实锤
- **真实复现**：
  - 无章节标题 TXT → 上传 202 → job **failed**（错误诡异：`chapter manifest not found; run normalize then split`）→ workspace **滞留** → 重传同名 **409**。
  - 二进制/非 UTF-8 `.txt` → **202 接受**（裸 `write_bytes`，无编码校验，[wizard.py:143](src/web/wizard.py:143)）→ 同样 failed + 滞留 + 409。
- **缓解边界**：坏 EPUB **已**回滚（iter 026 修复，`test_corrupt_epub_rolls_back_workspace`）。缺口在 **TXT/空内容路径**：`write_bytes` 永不抛 → 不进回滚分支 → 残缺 workspace 留存。
- **根因**：上传层不校验"内容是否可被后续 split 出章节 / 是否 UTF-8"；prepare 失败后不回滚已建 workspace。
- **修复方向**：上传后校验 UTF-8；prepare 跑完若 manifest 0 章 → 友好报错 + 回滚 workspace（对齐坏 EPUB 的处理）。

#### #4/#5/#10/#13 坏 JSON 状态文件 → traceback 而非友好 blocker · ✅ 实锤（共因）
- **共因**：关键状态文件用裸 `read_json`（[utils.py:15](src/utils.py:15)，存在但损坏→抛 `JSONDecodeError`），而非 `read_json_optional`（[utils.py:21](src/utils.py:21)，坏文件降级）。
- **逐条实测**：
  - **#4** chapter_plan.json 坏 → `_load_chapter_plan` 抛；write-book job **硬 failed**(raw JSONDecodeError)；GET /readiness 被 `_safe_readiness` 接住但**把原始异常串泄成 `readiness_error:JSONDecodeError...` blocker**，都不是干净 `chapter_plan_invalid`。
  - **#5** chapter_01.meta.json 坏 → `chapter_status()` 直抛（[chapter_status.py:52](src/chapter_status.py:52)）；resume/status 受击穿（readiness 端点在 start_point/plan 等前置 blocker 缺失时会先短路，须 workspace 足够 ready 才会读到坏 meta）。
  - **#10** rolling_chapter_summary.json 坏 → `load_rolling_summary()` 抛 JSONDecodeError，**与 docstring "malformed degrade to empty" 直接矛盾**（[chapter_summary.py:33](src/chapter_summary.py:33)）。
  - **#13** driver_state.json / driver.pid 坏 → `load_state`、`_another_driver_running` 抛（[book_driver.py:110](src/book_driver.py:110)）；drive-book status/resume/stop traceback，无 `driver_state_invalid` 诊断。
- **修复方向**：上述读取点统一改 `read_json_optional` 或包 try/except → 转 `*_invalid` blocker，提示用户重建对应文件。

#### #8 auto-advance 已批准后仍抛未捕获异常 · ✅ 实锤
- **真实复现**：坏 entity_graph.json + 跑 `_auto_apply_advances(1)` → 抛**未捕获** JSONDecodeError。
- **根因**：[book_runner.py:854](src/book_runner.py:854) `read_json(entity_graph)` 在 try/except（[book_runner.py:876](src/book_runner.py:876) 仅 catch FileNotFoundError/IndexError/ValueError，且**这两个 read_json 在 try 之外**）之外；proposal 文件读（line 848）同理。
- **状态细节**：发生在章节已 Approve、正文已落盘之后 → "job failed 但内容已在盘上"的割裂态（非数据丢失，但恢复需手动）。
- **修复方向**：把 line 848/854 的读取移入 try 或改 `read_json_optional`。

#### #6a + NEW-A 整数参数无上限；Infinity → 500 · ✅ 实锤
- **真实复现**：chapters=999999999 → **202 接受**（`_int_param` 调用不传 maximum，[routes.py:1854](src/web/routes.py:1854)）；chapters=Infinity → `int(float('inf'))` OverflowError **未被 catch** → **HTTP 500 trace_id**；chapters=NaN → 干净 400。
- **根因**：`_int_value` 只 catch `(TypeError, ValueError)`（[routes.py:1916](src/web/routes.py:1916)），OverflowError 漏网；且四个整数参数都无 maximum。
- **修复方向**：`_int_value` 增 finite 守卫 + catch OverflowError → 400；为 chapters/resume_from/max_retries/replan_every 设合理上限。

#### #9 split 单步 gate 找 \*.md 但 normalize 产 \*.txt · ✅ 实锤
- **真实复现**：normalize 产 `*.txt`、零 `*.md`；split 单步 → `blocked: normalized_missing`。
- **根因**：[jobs.py:344](src/web/jobs.py:344) glob `*.md` vs [text_normalizer.py](src/text_normalizer.py) 输出 `.txt`。auto-pipeline 直接调 `split_all()` 不走此 gate 故无感，**单步 split 永远被误挡**。
- **修复方向**：gate 改 `*.txt`（或同时认 `*.txt`/`*.md`）。

---

### P2 —— 并发 / 竞态 / 体验

#### #7 起点保存无 workspace reservation · ✅ 实锤 → ✅ 已修(iter060)
- **真实复现**：workspace reserved 时，`POST /run`(normalize) → 409（正确挡），`POST /start-point` → 穿过（到 use_workspace 内部才因样本无效 400，**未被 409 挡**）。
- **根因**：[routes.py:554](src/web/routes.py:554) `api_workspace_set_start_point` 只用 `use_workspace`，缺 `jobs.workspace_reserved`（其余写端点都用了）。
- **修复方向**：set_start_point 包 `with jobs.workspace_reserved(name)`。
- **修复（iter060）**：写块包 `jobs.workspace_reserved` + `use_workspace`（照搬 `draft_save` 范式），`workspace_busy`→409。+2 单测（`tests/test_iter060_p2.py`）。

#### #11 writer-style 样本固定临时文件 + 写在抢锁前（TOCTOU）· ✅ 实锤 → ✅ 已修(iter060)
- **真实复现**：两并发 extract → [202, 409]；样本路径是**每 workspace 固定**的 `.writer_style_sample.tmp`（[paths.py:258](src/paths.py:258)），写在 [routes.py:1238](src/web/routes.py:1238)（`use_workspace` 内）**但在 `start_job`（1239）抢锁之前** → 败者的写可覆盖胜者样本，胜者 job 读到错样本。
- **修复方向**：样本写到 per-job 唯一路径，或把"写样本 + 起 job"包进同一 reservation。
- **修复（iter060）**：路由改每请求唯一 uuid 路径 + `write_text_atomic` + `sample_path` 入 job params；handler 优先读 params 路径（回落固定名）并提取后删；job 起不来时清理暂存样本（防临时文件泄漏）。+3 单测（`tests/test_web_writer_style.py`）。

#### #14 drama 写端点非原子 + 无 reservation · ✅ 实锤 → ✅ 已修(iter060)
- **真实复现**：PUT /drama/setup 在 workspace reserved 时仍 **200 穿过**；`api_drama_plan`/`api_drama_setup_save` 用裸 `write_text`（[routes.py:1459](src/web/routes.py:1459) / [routes.py:1494](src/web/routes.py:1494)），非原子（项目已有原子 `write_json`，[utils.py:29](src/utils.py:29)），无 reservation。
- **修复方向**：改 `write_json`（原子）+ 包 `workspace_reserved`。接真模型后竞态会放大。
- **修复（iter060）**：两端点写块包 `workspace_reserved` + 改 `write_json`（原子，同 `ensure_ascii=False`/`indent=2`），setup_save 整个读-改-写进 reservation 闭死被并发 `/drama/plan` 冲掉的竞争窗口；`workspace_busy`→409。+2 单测（`tests/test_web_routes_post.py`）。

#### #12 cancel/timeout 仅在 progress checkpoint 检查 · ✅ 属实（代码实锤）→ ✅ 已修(iter060，方案A；方案B→iter061)
- **根因**：[jobs.py:756](src/web/jobs.py:756) `_check_cancelled` 只在 `_progress` 回调与 handler 前后跑；单次长 LLM 调用期间无检查点 → 取消/超时要等当前调用返回才生效。真模型实测见 §3.3。
- **修复方向**：在长步骤内部插入协作式取消检查；或给 LLM 调用设可中断超时（已有 `LLM_REQUEST_TIMEOUT` 机制可复用）。
- **修复（iter060，方案A）**：核验确认 **debate 是唯一无取消粒度的 step**（writer 章内 rewrite loop、book_runner 章间 chapter loop 已有检查点）。`run_debate` 加可选 `progress_cb`，在每 agent LLM 调用前（**try 之外**，否则 `JobCancelled` 被 `except Exception` 吞）+ build_decisions/每选票/build_outline 前插检查点；`_step_debate` 传入。**方案B**（流式中断 + debate 开 `stream`，碰 `llm_client`/stream 配置）触「真模型须超时重试驱动」红线 → **显式推迟 iter061**。+2 单测（`tests/test_iter060_p2.py`）。

---

## 3. 真模型最小 run 实测（Phase 3）

> 环境：`openai/gpt-5.5-low` via `aetherheartpool.top`，workspace=`audit_real_probe`，1 章样本，budget_cny=0.001，per-call 超时 90s + 420s watchdog。

### 3.1 #1 预算失效（端到端）· ✅ 真模型坐实
- budget_cny=0.001 的 onboarding 实际发出 **9 次真实模型调用**（extract×1 / compress×1 / debate×1 / plot_planner×6），合计 **17,602 prompt tokens**、约 **293s** 真实模型耗时（extract 单次 29s、debate 单次 52s）。
- 全程 job 状态 = `running`，**从未触发 `budget_exceeded`**；我主动停止时它仍在 planning 阶段继续烧。
- **结论**：¥0.001 的预算上限被 onboarding 完全无视，真实消耗远超该额度。与 mock + 代码追踪（budget_cny 从不进 `run_auto_pipeline`）形成端到端闭环。
- **连带发现**：`logs/llm_calls.jsonl` **只记 token、不记 cost_cny**（每条仅 prompt/response tokens）。意味着 #1 修复时若要按 CNY 累计预算，这份账本无成本字段可依——需一并补 per-call 成本估算（token×单价），否则 onboarding 预算无从计算。

### 3.2 #2 抽取吞错（端到端机会性观测）
- 本次样本仅 1 章且该章 extract 调用 `status=ok`（未自然失败）→ #2 未在真模型中触发。已在 mock 用 monkeypatch **确定性复现**（见 §2 #2），结论不受影响。

### 3.3 #12 取消延迟（旁证）
- 本次真实单次调用耗时：extract 29s、**debate 52s**。用户若在这类长调用期间点"取消"，须等当前调用返回（最长 ~52s）才生效——印证 #12 "仅 checkpoint 检查"在真实延迟量级下的体感问题。

### 3.4 旁证：真模型路径的高延迟 / 缓冲特性
- 9 次调用累计 293s；脚本 stdout 块缓冲导致前端进度"看着冻住"实则一直在跑——与既有认知（aetherheartpool 高延迟、偶发慢/挂）一致。长程任务必须靠超时重试驱动兜底（本次靠 `LLM_REQUEST_TIMEOUT=90` + watchdog 安全收尾，未失控）。

---

## 4. 后续 bugfix iter 规划

> 验收统一基线：`python -m unittest discover -s tests` 全绿 + 每条对应的复现脚本从"崩/穿/吞"变成"友好拦/正确拒/可见失败"。

### iter 058 · P0：钱与静默错误（最高优先）· ✅ 已修(iter058，1128 tests OK)
- **#1**：`run_auto_pipeline` 增 budget_cny 入参 + 步间成本累计 → 超限 `budget_exceeded`（或 onboarding 暂时下掉预算字段）。改 `auto_pipeline.py` / `jobs.py:597`。
- **#2**：onboarding/prepare 调 `extract_all(raise_on_failure=True)`，或把失败章升级为 `blocked`。改 `auto_pipeline.py:101` / `jobs.py:358`。
- **#6b**：`_float_param`/`_optional_float` 加 `math.isfinite` 守卫。改 `routes.py:1925` / `wizard.py:438`。
- 验收：探针 phase1/phase2 中 #1/#6b 用例返回拒绝；构造抽取失败的 onboarding 报 blocked 而非 succeeded。

### iter 059 · P1：崩溃与卡死 · ✅ 已修(iter059，1158 tests OK)
- **坏 JSON 共因 #4/#5/#10/#13**：统一改 `read_json_optional` / 转 `*_invalid` blocker。改 `chapter_status.py:52/116`、`chapter_summary.py:33`、`book_driver.py:110/718`、`book_runner.py:361/645`、`writer.py` 计划加载。
- **#8**：`_auto_apply_advances` 把 entity_graph/proposal 读移入 try 或改 optional。改 `book_runner.py:848/854`。
- **#3 + NEW-B**：上传校验 UTF-8；prepare 后 manifest 0 章 → 友好报错 + 回滚 workspace。改 `wizard.py:143` 附近 + prepare 收尾。
- **#6a + NEW-A**：`_int_value` 加 finite 守卫 + catch OverflowError + 设上限。改 `routes.py:1909`。
- **#9**：split gate 改认 `*.txt`。改 `jobs.py:344`。
- 验收：phase2 全部坏状态用例返回 `*_invalid` blocker / 友好 4xx，无 traceback / 500。

### iter 060 · P2：并发与体验 · ✅ 已修(iter060，1180 tests OK)
- **#7** ✅：set_start_point 包 `workspace_reserved`。改 `routes.py:554`。→ 写块包 `jobs.workspace_reserved`+`use_workspace`（照搬 `draft_save`），`workspace_busy`→409。
- **#11** ✅：writer-style 样本改 per-job 唯一路径。改 `routes.py:1234` / `paths.py:258`。→ 每请求唯一 uuid 路径 + `write_text_atomic` + `sample_path` 入 job params，handler 优先读 params 路径回落固定名、提取后删、job 起不来清理暂存样本。
- **#14** ✅：drama 写端点改 `write_json`（原子）+ `workspace_reserved`。改 `routes.py:1459/1494`。→ 两端点改原子 `write_json`+包 `workspace_reserved`，setup_save 整个读-改-写进 reservation 闭死竞争窗口。
- **#12** ✅（方案A）：长步骤内插协作式取消检查 / 可中断超时。改 `jobs.py:756` 调用链 + `book_runner` 写循环。→ **核验确认 debate 是唯一缺取消粒度的 step**（writer/book_runner 章内外已有检查点），`run_debate` 加 `progress_cb`、每 agent LLM 调用前（try 之外）插检查点，`_step_debate` 传入；**方案B**（流式中断+debate 开 stream）触红线 → **iter061**。
- 验收：并发探针不再出现样本互覆盖 / reserved 期间写穿透；cancel 在合理时间内生效。✅ 1158→**1180** tests OK（+22）。

### iter 060 附 · Codex 复审补漏 A–F（iter058/059 护栏的对称入口）· ✅ 已收口(iter060)

> 复审动机：iter058 #6b 只给 `/run` 校验了 `budget_cny`/`min_confidence` 有限性、iter059 #6a 只给 write-book/plan-chapters 的整数参数设了上限——**同一类 bug 的其它入口**（`/readiness` 整数、其它 step 的 `timeout_minutes`、web 读面与 `book_runner` 残余裸 `read_json`）仍在原始 buggy 状态。本轮一次收齐。

- **A** ✅ `/readiness` 整数上限：`api_workspace_readiness` 经 `_parse_int` 裸 `int()` 无上限 → `chapters=999999999` 流入 `book_runner` `list(range(...))` 物化近 10 亿元素（write-book 入口 iter059 已 clamp 2000/10000/2000、readiness 对称入口漏了）。handler 内 clamp `chapters`/`resume_from`/`replan_every` 到同上限（仿 `api_workspace_logs_tail`）。
- **B** ✅ timeout 有限性（双层）：仅 write-book/plan-chapters 校验 `timeout_minutes` → 其它 step 的 `NaN/inf` 穿到 `_timeout_deadline` 产 `nan` deadline、`monotonic()>nan` 恒 False **永不超时**（iter058 #6b 同类 bug 换入口）。`_validated_run_params` 对所有 step 用 `_float_param` 校验（NaN/inf/负→400）+ `_timeout_deadline` 加 `math.isfinite` 兜底。
- **C/D/E** ✅ web 读面坏 JSON 降级：manifest(543)/草稿详情(1617/1620/1621)/草稿列表(1642/1655/1656)/entity·relationship PUT graph(1323/1398) 裸 `read_json`→`read_json_optional`。**核验校正**：Codex 原报「泄露 `JSONDecodeError` 文案」**不成立**——`server.py:60-73` 对未捕获异常统一返 `{"error":"internal server error"}`、异常串只进 stderr；真实后果是坏 JSON 抛错被兜底成 **HTTP 500 击穿读面**。PUT 两处坏 graph 降级 `{}` 后命中既有 `isinstance` 守卫返 404『run prepare first』、在 `write_json` 前 return，**不覆盖坏文件**。
- **F** ✅ `book_runner` 残余裸读：5 处（728/741/790/791/858，iter059 R6 主动 scope 外的残余）→`read_json_optional`。790/791 经 try 外路径冒泡出 `run_write_book` 击穿 resume、858 在异常善后中二次抛错顶替原始快照；`read_json` 至此 `book_runner` **全无裸读**。
- 验收：补漏入口全部返回友好 4xx / 降级，无 500 击穿 / 永不超时；并入 iter060 全量 **1180 tests OK**。**至此审计 16 条全部清零 open。**

---

## 5. 附录：复现命令

```bash
# 零成本 mock 探针（隔离，安全）
.venv/bin/python /tmp/audit_probes/probe_phase1.py       # #1 #3 #6a #6b #7 #9 + NEW-A
.venv/bin/python /tmp/audit_probes/probe_phase2.py       # #4 #5 #8 #10 #13 + 6b(inf)
.venv/bin/python /tmp/audit_probes/probe_phase3_misc.py  # #2 #11 #14 + fuzzing(NEW-B)
.venv/bin/python /tmp/audit_probes/probe_phase4b.py      # #11 修正 + NEW-B 深挖
# 一次最小真模型 run（花钱，已带超时/watchdog/独立 workspace）
.venv/bin/python /tmp/audit_probes/real_run.py
# 清理真模型 throwaway workspace
rm -rf workspaces/audit_real_probe
```
