# Iteration 059 — P1 修复：坏 JSON 与数据完整性

> 承接 iter058「前端用户路径 P0 修复（钱与静默错误）」收官（canonical 1128 tests OK）。
> 来源：`docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 划定的 **iter059 · P1 段（崩溃与卡死）**。
> 本轮只做该段 5 组共 9 条 bug；沿用 iter058 铁律：复用已验证护栏、零新机制、默认路径
> byte-identical、确定性单测兜底、按风险递增分 commit、全程不烧钱。

## Context

审计的共同主线：关键状态文件用了裸 `read_json()`（文件存在但损坏会抛 `JSONDecodeError`），
以及上传 / 整数参数边界缺校验。用户一旦命中损坏文件或非法输入，就撞到 traceback / HTTP 500 /
workspace 卡死，而非友好降级或干净 blocker。

核验过的根因：
- `src/utils.py` `read_json` 裸读抛错；`read_json_optional` 已 catch
  `OSError/UnicodeDecodeError/JSONDecodeError` 降级——全项目可降级读取点都用它，本轮补漏网点。
  **不改 `read_json` 本身**（`write_json` 原子指纹门控等多处依赖它 fail-loud）。
- `_load_chapter_plan` 有**两条抛错路径**：`read_json` 的 `JSONDecodeError` + `ChapterPlan(**data)`
  对"合法 JSON 但错 schema"的 pydantic `ValidationError`。只换 `read_json_optional` 不够，需包一层。
- `routes._int_value` 只 catch `(TypeError, ValueError)`：`chapters=Infinity`（JSON 字面量 →
  `float('inf')`）走 `int(float('inf'))` 抛 `OverflowError` 漏成 HTTP 500；且四个整数参数无上限。
- 上传 `.txt` 走裸 `write_bytes`（永不抛），0 章 / 非 UTF-8 文件被 202 接受 → 后台 job failed +
  workspace 滞留 → 同名重传 409。坏 EPUB 已在 iter026 回滚（`test_corrupt_epub_rolls_back_workspace`）。

## 5 组 bug 修复（按 commit 顺序：小→大 / 低→高风险）

| # | 组 | 根因 | 修复 |
|---|---|---|---|
| #9 | split gate | `jobs._step_split` gate glob `*.md`，但 normalize 产 `*.txt` → 单步 split 永远 `blocked: normalized_missing` | gate 改同时认 `*.txt`/`*.md`；auto-pipeline 直调 `split_all()` 不走 gate，byte-identical |
| #10 | rolling summary | `chapter_summary.load_rolling_summary` docstring 承诺 "malformed degrade" 但用裸 `read_json` 抛错 | → `read_json_optional`，文档与实现一致，坏文件降级空态 |
| #6a+NEW-A | 整数参数 | `routes._int_value` 漏 `OverflowError`（Infinity→500）；四参数无上限（999999999 被接受） | `_int_value` 加 `math.isfinite` 预检 + `OverflowError`→400；四参数加上限 2000/10000/20/2000 |
| #5 | draft meta/review | `chapter_status` 裸 `read_json` 读 meta(:52)/review(:116) → 坏文件击穿 resume/status | meta→`read_json_optional(.,{})`（approved=False）；review→`read_json_optional(.,None)`（落既有 `external_review_invalid`） |
| #13 | driver state/pid | `book_driver` 5 处裸 `read_json` → 坏 `driver_state.json`/`driver.pid` traceback drive-book status/resume/stop | 5 处→`read_json_optional`；`cmd_status` 加 `driver_state_invalid` 诊断（存在但不可读≠缺失） |
| #4 | 坏 chapter_plan | `_load_chapter_plan` 裸读 + pydantic 抛；GET /readiness 经 `_safe_readiness` 泄 `readiness_error:JSONDecodeError` | **Option B**：新 `ChapterPlanInvalid`；readiness catch→独立 `chapter_plan_invalid` blocker + 前端标签"章节计划文件损坏" |
| #8 | auto-advance | `book_runner._auto_apply_advances` proposal(:873)/entity_graph(:879) 读在 try 外 → 章节已落盘后坏文件抛未捕获，job failed 而内容已在盘（割裂态） | 两处→`read_json_optional`；坏文件降级为 no-op（`applied_count=0`） |
| #3+NEW-B | 上传校验 | `wizard.start_upload` `.txt` 裸 `write_bytes` 不校验；0 章 prepare 后 manifest 缺 → cryptic failed + workspace 滞留 + 409 | `.txt` decode UTF-8 校验 + 同步 0 章探针 → `_UploadRejected`→rmtree+400；`auto_pipeline` split 后 0 章 raise（后台兜底，在 extract 前） |

## 关键设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 坏 JSON 在底层 `read_json` 改 vs 逐调用点改 | **逐调用点** | `read_json` 被 `write_json` 指纹门控等依赖 fail-loud；底层降级会掩盖真实损坏、破坏默认路径保证 |
| #4 blocker 形态（用户拍板） | **Option B：独立 `chapter_plan_invalid` kind** | 用户能在 UI 区分"损坏"vs"缺失"；多改前端 `_blocker_kind`/`_primary_blocker` label map ~6 行，CTA 仍是重新生成计划 |
| #4 `_load_chapter_plan` 守护范围 | 守 read **与** pydantic 构造 | 合法 JSON 但错 schema（缺 `target_chapters`/`overall_arc`/`chapters`）也抛 `ValidationError`，单换 `read_json_optional` 不够 |
| `ChapterPlanInvalid` 基类 | 子类 `ValueError` | 既有 catch `ValueError` 的调用点（replan 的 `except Exception`、jobs `_step_review_chapter`）自然降级，作安全网 |
| #5 review 默认值 | `read_json_optional(.,None)` 非 `{}` | `{}` 是 dict 会绕过 `isinstance` 检查落到 reject；`None` 落既有 `external_review_invalid`，语义准确 |
| #3 上传回滚（用户路径） | **Option 1：同步预检** | 起 greenfield job 前同步探针 + rmtree，对齐坏 EPUB UX（友好 400、无滞留、同名秒重传），规避异步线程内 rmtree 与 `_WORKSPACE_LOCK` 竞态 |
| #3 0 章探针 vs 后台兜底 | 两层 | 同步探针（lenient，仅无任何标题才拒，防误拒合法上传）在 wizard 层；`auto_pipeline` split 后 0 章 raise 作绕过 wizard 的权威后台兜底（在 `extract_all(raise_on_failure)` 前，让"0 章"友好错误优先） |
| #13 `driver_state_invalid` 暴露面 | CLI stdout 诊断，不进 readiness blockers | driver 状态经 stdout 文本/JSON 消费，与 readiness blocker 列表消费者不同 |

## Acceptance / 验证

canonical **1128 → 1158 tests OK（+30）**，全确定性、mock-only、不烧钱。

分项新增：
- 新建 `tests/test_bad_json_blockers.py`（A 组共因 14）：RollingSummary(2)/ChapterStatus(2)/
  DriverState(4)/ChapterPlanInvalid(5)/AutoAdvance(1)。
- 新建 `tests/test_int_finite_guard.py`（#6a/NEW-A 13，对标 iter058 `test_float_finite_guard`）：
  含头条 E2E `chapters=Infinity → 400 而非 500`、`999999999 → 400`、`5 → 202`。
- 扩 `tests/test_web_jobs_dispatch.py`(+1 #9)、`tests/test_web_wizard_e2e.py`(+2 #3/NEW-B
  回滚，镜像 corrupt-epub)。
- #4 头条回归：GET /readiness 坏 plan 不再泄 `readiness_error:JSONDecodeError`，产
  `chapter_plan_invalid` + `primary_blocker.kind`/label「章节计划文件损坏」。

默认路径未变验证：`read_json_optional` 对合法/缺失文件与 `read_json` 返回一致（仅坏分支不同）；
split gate 仅"增"识别 `.txt`；整数上限远高于真实值；合法 UTF-8 decode→write_text 同字节。

## 暗礁与教训

- **R1 旧测试钉死 buggy 行为**：`test_web_routes_get.test_api_workspaces_overview_bad_plan...`
  原断言坏 plan 产 `readiness_error` 泄漏（正是审计 #4 要修的 bug）→ 更新为断言干净
  `chapter_plan_invalid` + 无 `readiness_error`。
- **R2 #3 兜底打到 iter058 测试**：`test_auto_pipeline_budget`/`test_extract_failure_surface`
  mock `split_all=[]`（占位"不关心"）→ 撞新 0 章 guard 提前 raise。改 mock 为非空 list
  （split 成功应≥1 章，[] 本不真实）→ 它们仍测 extract/budget 真意图。
- **R3 #4 调用方扇出**：`_load_chapter_plan` 新增抛错路径，6 调用点逐一审计——
  `run_write_book`(:82)/`writer.write_chapters`(:88) 兜成 None（require_plan=False 边缘）、
  readiness 入口 catch→blocker、`jobs._step_review_chapter` 兜成 blocked、replan 已在
  `except Exception` 内；子类 `ValueError` 作安全网。
- **R4 #4 schema 双抛**：`ChapterPlan(**data)` 对错 schema 抛 pydantic `ValidationError`，
  必须连 read 一起守；空 `{}` plan 也从崩溃变干净 blocker（改进）。
- **R5 #13 顺手收 driver 内 chapter_plan 读**：`book_driver` ensure-plan 的 chapter_plan 读
  `or {}` 只兜 None 不兜坏 JSON，一并改 `read_json_optional`（同文件同类 bug，原子提交）。
- **R6 scope 自律**：`book_runner` 另有 5 处裸 `read_json`（meta/review/failure，728/741/790/791/858）
  **不在审计 P1 清单**，本轮不动，避免 scope creep。

## 不在本轮范围（iter060 · P2：并发与体验）

- #7 `set_start_point` 包 `workspace_reserved`
- #11 writer-style 样本改 per-job 唯一路径（TOCTOU）
- #14 drama 写端点改 `write_json`（原子）+ `workspace_reserved`
- #12 长步骤内插协作式取消检查 / 可中断超时

## 关键文件

**修改**：`src/web/jobs.py`(#9 split gate + #4 review-chapter) · `src/chapter_summary.py`(#10) ·
`src/web/routes.py`(#6a `_int_value`/上限) · `src/chapter_status.py`(#5) · `src/book_driver.py`(#13
5 读 + 诊断) · `src/writer.py`(#4 `ChapterPlanInvalid`/`_load_chapter_plan`) · `src/book_runner.py`(#4
readiness/blocker/`_load_raw_chapter_plan` + #8 auto-advance) · `src/web/wizard.py`(#3/NEW-B) ·
`src/auto_pipeline.py`(#3 0 章兜底)
**新增测试**：`tests/test_bad_json_blockers.py` · `tests/test_int_finite_guard.py`（+ 扩
`test_web_jobs_dispatch`/`test_web_wizard_e2e`；更新 `test_web_routes_get`/`test_auto_pipeline_budget`/
`test_extract_failure_surface`）
**不改**：`src/utils.py`（`read_json`/`read_json_optional` 共享原语，仅作锚点）
