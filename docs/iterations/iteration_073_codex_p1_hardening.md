# Iteration 073 — codex 复审 P1 一次性收口（review 误拒/计划履约/Web jobs/leave-guard/JSON 安全 + outline-drift severe block + 第二批 docs/校验）

## Context

真模型长程续写实测前的一轮硬化。用户转述 codex 复审的一批已确认 P1 + 第二批 docs/校验问题。这些缺陷在长程实跑里会：误拒正确稿件烧光预算（broad-cast warn_only 没进主/外审）、放行抛弃计划/漂移大纲的坏稿（plan compliance 不阻断 / outline drift 仅 warn）、Web 监控面板长期显示失联任务（recent_jobs 排序）/ 吐非法 JSON（NaN/Inf）/ 外发冗余 job 字段、leave-guard 异步竞态跳错页。本轮一次性收口，给真模型实跑铺平地基。

**两个经用户确认的设计决定**：
1. **Plan-compliance 拦截默认开启**（`enabled=true, miss_ratio=1.0`）：只在「全部 key_events 都字面零重合 = 整章抛弃计划」时翻 Reject。有意反转 iter065「只建议不阻断」，三重护栏压低误拒。
2. **outline-drift 纳入本轮**，但只在高置信、严重、**持续**（最近 10 章聚合窗口，近似代表持续偏离，非严格逐章连续检测）drift 时 block；续写场景才 block，新书 + 普通 drift 继续 warn。

来源：用户转述 codex findings（带 file:line）→ 3 个 Explore subagent 并行精确探查（reviewer/writer broad-cast+plan / web jobs 排序+字段+JSON / leave-guard+第二批）→ Plan subagent 起草 + Plan-mode AskUserQuestion 定 2 scope（B 默认开 ratio=1.0 / outline-drift 纳入但严格 gate）→ 实现中据 codex 二次复审修正 5 点（D1 持久化也清洗 / D3 详情页保留 params 轻量档 / B 先迁移测试再加合成 Reject / E modal-open 语义+测试 / 持续措辞不过度承诺 / timeout=0 语义）。

## Plan

| 编号 | 问题 | 修法 |
|---|---|---|
| **D1** | 非有限 JSON（NaN/±Inf）落 HTTP 响应 + `web_jobs.jsonl` | 共享 `jobs._finite_json_safe` 递归清洗，`routes._json` + `jobs._persist_job` 双侧应用 |
| **A1** | broad-cast warn_only 没进主 review（硬编码 True） | `writer.py:271` → `enforce_checklist_mode` |
| **A2** | 外审硬编码 True，无 plan-derived warn_only | `book_runner` 两处 `review_target` → `_enforce_checklist_for_plan(item)` |
| **B3** | 外审不跑 plan-compliance（无 chapter_plan_item） | `review_target` 加 `chapter_plan_item` 形参 + 转发；book_runner 两处传 `item` |
| **B1/B2** | plan compliance 永不翻 verdict，缺关键事件也 Approve | config `plan_compliance_block`（默认开）+ 严重缺失注入合成 Reject（先迁移旧测试锁 enabled=false 语义） |
| **I** | outline drift 仅 warn，长篇质量风险 | `outline_drift_severity` 三态 + 续写场景 severe→blocker + `readiness_catalog` kind + config |
| **C** | recent_jobs 旧 lost 压过新成功（overview limit=1） | 先 reconcile lost（用 `_JOBS.get`）再排序切片，lost 视为 terminal |
| **D2/D3** | job API 外发 raw record | 三档投影：overview→`public_job_view`，/jobs/recent→`public_job_summary_view`，/job/<id>→`public_job_detail_view` |
| **E** | leave-guard 异步竞态跳错页 | `leaveGuardSeq` 序列校验 + `leaveGuardModalOpen` 单模态 + `mountModal` onClose 复位 |
| **F** | README 测试数过时 + 裸 verify.sh | 命令改 `unittest discover` + venv 注记 + 实测数 |
| **G** | iter072 E2E 缺记 | iter072 Acceptance Result 据实回填 |
| **H** | drive-book start step-timeout 不校验 | `_build_params` 加 `validate_int(minimum=0,maximum=1440)`，与 resume 对齐 |

## Acceptance

- 单测：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`（基线 iter072 1341 OK + 新增 D/A/B/I/E/H 测试）。
- `python3 main.py preflight` exit 0；`node --check`（渲染后 app.js）OK。
- `bash scripts/verify.sh` 本机因脚本裸 `python3` 缺 pydantic 不可跑（与本轮无关），等价闸门 = venv discover。
- 铁律⑨：`/code-review high` + `/security-review`；铁律⑧：README SOP 表 + AGENT_HANDOFF Phase Status 同步。
- 前端：leave-guard 竞态属时序竞态，preview 难稳定复现 → `node --check` + `STATIC_JS` 字符串/逻辑断言代偿，E2E 据实顺延（见 Notes）。

## Implementation Notes

- **D1**：`_finite_json_safe` 放 `jobs.py`（与 `_as_ts` 同层），`routes._json` import 复用。codex 二次复审点：只清洗响应而不清洗 `_persist_job` 落盘，脏值会被 `recent_jobs` 读回再外发，故**双侧**清洗。
- **A1/A2/B3 耦合**：A2 与 B3 都改 `book_runner` 同两处 `review_target` 调用（existing-draft + retry），合并改避免二次编辑；A2 复用 writer 既有私有符号 import（`_enforce_checklist_for_plan`），不另设共享模块；`review_target` 新增 keyword-only `chapter_plan_item=None` 向后兼容（`web/jobs.py` 草稿重审调用不传，self-skip）。
- **B**：先做 config helper `_plan_compliance_block_cfg`（默认 `(False,1.0)` fail-safe）+ 迁移 `test_reviewer_plan_compliance` 旧 9 测试 patch `(False,1.0)` 锁「enabled=false advisory 不阻断」语义；再把 `plan_misses` 计算上移到 panel 聚合前、severe 时注入 `_synthetic` Reject（复用 `deterministic_relations` 既有 `hard_synthetic_reject` 路径）；advisory 循环复用同一 `plan_misses`（单源，删重复计算）。误拒护栏：bigram 粗信号 + ratio=1.0 整章抛弃 + 阈值 0.15 + agents.yaml 可关。
  - **mock-skip（实跑必踩，单测后补发现）**：默认开启后，**真实 mock 流水线 E2E**（`drive-book` 全链 `test_checkpoint_resume_full_chain`，write-book 跑 subprocess 真 review_text）会被 block —— mock 写手是确定性 fixture，不遵循计划，draft 与全部 key_events 零字面重合 → 每章误判 Reject → 击穿 mock 流水线（违铁律④）。修法：`_plan_compliance_block_cfg(is_mock)` 在 mock 模式（`client.is_mock`）返回 disabled；review_text 传 `client.is_mock`。单测 patch 整个函数（忽略 `is_mock` 实参）→ block 逻辑照测；advisory 不受 mock 影响（只 block 决策 gate）。这是「真模型质量闸不应被 mock fixture 误触」的边界，与 mock graceful degrade 同源。
- **I**：`outline_drift_severity` 复用 `outline_drift_codes` 的锚点/rolling/命中率逻辑（none/warn 边界字节级一致），加 severe 层 `hit_rate<0.2 且 anchors≥5`。book_runner severe + `require_start_point` + config 开 → `blockers.append("outline_severe_drift:...")`（与 extraction-gap 481 同「续写 block / 新书 warn」模式），`run_write_book` 入口 `BookRunBlocked` 硬停。`readiness_catalog` 加 `outline_drift_severe` kind（CTA run_debate）+ classify 分支。**「持续」诚实映射**：建立在最近 10 章聚合窗口，近似代表持续偏离，非严格逐章连续检测。**mock-skip**：`_outline_drift_block_enabled` 同样在 mock 模式（`OPENAI_MODEL` 以 mock 开头）返回 False —— mock rolling 是 fixture 不必跟 outline，severe block 会误触 mock 续写 E2E（与 B 同源 fail-open；readiness 测试 patch 函数绕过）。
- **C**：reconcile lost-ness 提到 sort 之前，用 `_JOBS.get`（内存直查，避开 `get_job` 的 persisted-fallback glob + 二次 lost 转换）；lost 落定后 `active=0`，不再压过更新 succeeded。现有 3 个 live-active 测试（保持 `_JOBS` live）继续绿。
- **D2/D3（轻量档，用户决定）**：overview→最小 `public_job_view`（drop params/trace/result_summary，多 workspace 首页收益最大）；/jobs/recent→`public_job_summary_view`，/job/<id>→`public_job_detail_view`。**codex 二次复审点修正**：原计划「/jobs/recent 丢 params」会破坏 jobs-table 抽屉 `renderJobDrawer` 的「用相同参数重试」（`byId.get(job_id)` 取 `/jobs/recent` 对象 repost `{step, params}`）+ `jobChapterNumber` 的 `params.resume_from` 兜底 → 实测 summary view **保留 params**，只 drop 内部 `cancel_*`；详情页 detail view 在此基础上加 `cancel_*`。三档共同价值 = 显式 allowlist（未来内部字段不自动外泄）+ 叠加 D1 清洗。**残留**：list/detail 仍下发 params（本地单用户、未跨信任边界）；彻底零 params 需拆后端 `/job/<id>/retry` + 章节号改 result_summary 派生，留后续。
- **E**：`leaveGuardSeq` 每次点击 `++` 并捕获进闭包，`/jobs/active` 返回后所有导航/弹窗分支前校验 `seq===leaveGuardSeq`（含 catch fail-open）；`leaveGuardModalOpen` 模态开期间忽略新点击（modal 保持**原** href，绝不静默跳错页）；`mountModal` 加可选 `onClose`（Esc 走内部 close，故需 hook 而非包 closeModal）复位 `leaveGuardModalOpen`。⚠ 本段不新增正则字面量（避 `\/` SyntaxWarning）。
- **H**：`_build_params` 加独立 `validate_int(step_timeout_minutes, minimum=0, maximum=1440)`（不在 `INT_CAPS`，不能塞 `validate_run_params`），与 `cmd_resume` 完全对齐。`minimum=0` 保持对齐——但 0 ≠「无上限」：`_run_steps` `int(0 or DEFAULT)` → 180，由测试钉死。前置预算守门排本轮外（新行为设计 + 需真模型验证）。

## Acceptance Result

- **单测**：`.venv/bin/python3 -m unittest discover -s tests` = **1369 OK**（iter072 基线 1341 + 本轮新增 28：plan-compliance block 6 / web jobs recent+proj+finite 7 / writer 主审 warn_only 1 / outline_drift severity+classify 7 / book_runner severe-drift 2 / book_driver start-timeout 4 / leave-guard JS 1 / job detail finite 1，含 book_runner_review_context 转发断言扩充）。必须用 `.venv/bin/python3`（裸 python3 缺 pydantic）。
- **JS 语法**：`node --check`（渲染后 `JS_DASHBOARD`/`JS_WIZARD`）OK。
- **verify.sh**：本机不可跑（脚本第 41 行裸 `python3` 缺 pydantic，259 ImportError，与本轮无关）；等价闸门 = 上面 venv discover。`python3 main.py preflight` = exit 0。
- **铁律⑨ 代码审查**：`/code-review high`（5 角度 finder：line-by-line / removed-behavior / cross-file / reuse-simplify-efficiency / altitude-conventions + 对抗核实）surfaced 3 actionable + cleanup notes，**3 actionable 全修**：① cross-file —— Web `_step_review_chapter`（jobs.py）的第三处 `review_target` 漏改、仍硬编码 `enforce_relationship_checklist=True` 且不传 `chapter_plan_item`，导致同一章经 Web 重评审 vs `run_write_book` verdict 分叉（broad-cast 误严拒 + plan-compliance 不跑）→ 改为 `_enforce_checklist_for_plan(item)` + 传 `chapter_plan_item=item`，与 book_runner 对齐；② removed-behavior —— `outline_severe_drift` blocker 的 CTA 文案「用 --force 覆盖」是错的（`--force`/`allow_existing_blockers` 只清 `existing_output_not_strict_approved`，清不掉本 blocker）→ 改 CTA + catalog cause 指向 `config/agents.yaml` 开关；③ altitude（3 角度共识）—— mock 判定双机制不一致（reviewer 用 `client.is_mock`、book_runner 用裸 `os.getenv("OPENAI_MODEL")`，在「env 空 + models.yaml default=mock」时分歧 → drift gate 可能误 block mock 续写，违铁律④）→ 新增 `config.is_mock_mode()`（复用 `get_model_config` 解析，匹配 `LLMClient.is_mock` 语义），book_runner 改用之。另采纳 1 efficiency cleanup（`recent_jobs` 一次性快照 `_JOBS` 取代逐行加锁）+ 修 `outline_drift.py` 过时 docstring。**未采纳（留 Notes）**：`_synthetic_reject` 工厂抽两处合成 Reject（会动既有 `deterministic_relations` 块，铁律⑦ scope 收敛）；`_finite_json_safe` 全 payload 递归（correctness 优先，量级同 json.dumps）；`outline_drift_severity` 与 `_codes` 各算一遍命中率（readiness 路径非热点、镜像逻辑 + 注释）。**`/security-review`**：**0 HIGH / 0 MEDIUM**，净降暴露 —— 三档 job 投影都是改前「raw 全字段」的严格子集（不可能新增外泄），overview 收紧到最小 `public_job_view`（剔除 params）；leave-guard JS 只处理 int/bool + `window.location.href` 导航（非 innerHTML sink）；未碰 `.env`/`data/`/`小说txt/`。
- **前端 E2E**：leave-guard「快速双击」是时序竞态，preview 工具难稳定复现 → `node --check` + `STATIC_JS` 字符串断言（`leaveGuardSeq`/`leaveGuardModalOpen`/seq 校验/onClose 复位）代偿，E2E 据实顺延（与 iter072 回填同源处理）。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/jobs.py` | D1 `_finite_json_safe`（共享 + `_persist_job` 清洗）/ C recent_jobs reconcile-先于-sort（一次性快照 `_JOBS`）/ D3 `public_job_summary_view`+`public_job_detail_view` / 复审修：`_step_review_chapter` 第三处 review_target 对齐（enforce 派生 + 传 chapter_plan_item） |
| `src/web/routes.py` | D1 `_json` 复用清洗 / D2 overview→`public_job_view` / D3 recent→summary、job/<id>→detail |
| `src/config.py` | 复审修：`is_mock_mode()` 规范 mock 判定（复用 `get_model_config`，匹配 `LLMClient.is_mock`） |
| `src/web/static.py` | E leave-guard `leaveGuardSeq`+`leaveGuardModalOpen`+seq 校验 / `mountModal` 加 `onClose` |
| `src/writer.py` | A1 主审 `enforce_checklist_mode` |
| `src/book_runner.py` | A2 import + 两处外审 enforce 派生 / B3 两处传 `chapter_plan_item` / I severe-drift→blocker + `_outline_drift_block_enabled` |
| `src/reviewer.py` | B3 `review_target` 加 `chapter_plan_item` / B1/B2 `import math` + `_plan_compliance_block_cfg` + `_plan_key_events_count` + 合成 Reject 注入 + misses 上移复用 |
| `src/outline_drift.py` | I `DRIFT_SEVERE_HIT_RATE`/`DRIFT_SEVERE_MIN_ANCHORS` + `outline_drift_severity` |
| `src/readiness_catalog.py` | I `outline_drift_severe` kind + classify 分支 |
| `src/book_driver.py` | H `_build_params` step_timeout `validate_int` |
| `config/agents.yaml` | B1 `plan_compliance_block` + I `outline_drift_block` |
| `README.md` | F 快速开始命令 + venv 注记 + 测试数 |
| `docs/iterations/iteration_072_*.md` | G E2E 缺记回填 |
| tests | `test_reviewer_plan_compliance`（迁移+block 类）/ `test_web_jobs_recent`（C+D+finite）/ `test_web_routes_get`（leave-guard JS + job detail）/ `test_writer`（主审 warn_only）/ `test_book_runner_review_context`（转发）/ `test_outline_drift`（severity+classify）/ `test_book_runner`（severe-drift）/ `test_book_driver`（start-timeout） |

## 不在本轮范围

- **KB 起点过滤 warn→block**：续写场景**已是 blocker**（book_runner extraction-gap），仅新书 warn（fail-open 铁律④）——无需改。
- **原文重合检测**：`writer_style._scrub_sample_overlap` **已硬清洗字段**（≥8 字连续重合直接清空），非 warn-only——无需改。
- **drive-book 前置预算守门**（低预算被 debate/plan 花掉）：新行为设计 + 需真模型验证，非 P1 收口。
- **outline_drift 完整版**（LLM 语义判定 + write-time 基准切滚动上下文）：需真模型验证，留后续。
- **公开 job API 彻底零 params**：需拆后端 `/job/<id>/retry` 端点 + 章节号 result_summary 派生，触及 run/retry 流程；用户选轻量档（详情页保留 params），留升级路径。
- **`scripts/verify.sh` 解释器对齐**：完整环境脚本，改解释器超范围（README 指向 venv 命令即可）。

## Notes

- **B 误拒边界**（写进 doc 供回退判断）：判定用中文 bigram 命中率（粗词法信号，非语义履约）；`miss_ratio=1.0` 只在全部 key_events 字面零重合时 block = 整章抛弃；残余误拒 = 极端浓缩 + 全程近义改写且零字面重合的好稿（实践近乎只对应真抛弃）；回退 = `config/agents.yaml` 关 `plan_compliance_block.enabled`。
- **A↔B 正交**：A 让 broad-cast 章更宽（关系 checklist 缺失不再 Reject），B 让整章抛弃计划更严——两条独立 review 来源互不冲突，一章可同时 A-warn_only + B-block（正确）。
- **I 回退** = `config/agents.yaml` 关 `outline_drift_block.enabled`；severe 误 block 需大纲 5+ 核心实体在最近 10 章持续缺席（真漂移）。
- **iter072 E2E 缺记**已回填（见 iter072 Acceptance Result「前端 E2E（iter73 回填）」），形成可追溯链。
- **复审驱动的 scope 扩展（铁律⑦ 诚实记录）**：原 plan 说「`web/jobs.py:720` 草稿重审 review_target 保持不传 chapter_plan_item」——但 `/code-review high` cross-file 角度查出该处（`_step_review_chapter`）的 `item` **本就已解析**（line 782），漏改会让同一章经 Web 重评审 vs `run_write_book` verdict 分叉。这是「真实 bug 例外」（plan 的假设错了），故扩到该处对齐，并据实记录。其 verdict 行为与 book_runner 外审同一条 `review_text` 路径（已被 `PlanComplianceBlockTests` + `test_book_runner_review_context` 覆盖），未单独加 web 测试。
- **下轮候选**：公开 job API 彻底零 params（后端 retry 端点）/ `_synthetic_reject` 工厂统一两处合成 Reject / outline_drift LLM 语义版 / drive-book 前置预算守门 / 批量命名中文化 / drama 站③④ / 真模型 capstone。
