# Iteration 066 - codex iter065 复审 findings 收口（上）：fail-closed 数值/类型守门

## Context

codex 对 iter064/iter065 改动做了一轮只读复审，提出 8 条 findings（3×P1 / 4×P2 / 1×P3）。3 个 Explore subagent 逐条追踪数据流 + 主代码核读，**全部属实**（6 条完全属实、2 条部分属实）。共同根因 = **输入边界没 fail-closed**：用 `bool()`/`float()` 裸转配置与 proposal 字段，NaN/inf/空白字符串/坏类型在 IEEE-754 比较下静默穿透阈值门，让「防资源耗尽 + 防脏数据」的守门形同虚设。这些都不是已激发的线上 bug（当前 `agents.yaml` 配置干净、默认 mock 路径不触发），但全是**手工误配 / 真模型脏输出 / 长程 run 自阻塞**会踩中的真实坑。

与用户确认**分 2 轮**：本轮 iter066 收 5 条 fail-closed 数值/类型守门（#1/#2/#3/#4/#5，含**全部 3×P1**）；iter067 收 3 条语义信号链路 + Web 脱敏（#6/#7/#8，全 P2/P3）。用户另定 3 个设计决策：① #5 用 cap **解耦**方案（CLI→2000、WebUI 留 200）；② #4 的 isfinite 守门**扩到 legacy advance 路径**一并清（消掉 iter065 README 里「顺延」的那条）；③ #2 存在性校验取**最严**（src/dst 两端都必须在 entities）。用户复审 plan 给出的 6 条精炼已并入（#4 拆 coerce/select、#1 补 import 用清洗值、#3 不半改 state、#7 补 CLI review-chapter→iter067、固定 8 段名、验证命令带 mock+venv）。

复用 iter064 已建好的 `src/run_params.py` 守门工具栈（`validate_int`/`validate_float`/`math.isfinite`），不造新机制。

## Plan

实施顺序 **#4 → #2 → #1 → #3 → #5**（#2/#4 同改 `_apply_selected` 紧邻；#1 的 fail-closed 以 #4 的有限性为底线）：

- **#4 (P2)** confidence 非有限值穿透：`entity_advance.py` 新增 `coerce_finite_confidence`（写 timeline 用，坏值→0.0），`select_auto_indexes` 加 `math.isfinite` continue（保持「坏值 skip」语义，不 coerce）。
- **#2 (P1)** src/dst 不 strip、不校验存在性：`_apply_selected` 加 `.strip()` + 创建分支新增 `creation_unknown_entity` 档（两端都须在 `graph["entities"]`）。
- **#1 (P1)** allow_creation/creation_confidence 配置非 fail-closed：`book_runner.py` 用 `is True` 严格比较 + `run_params.validate_float` 清洗值。
- **#3 (P1)** resume 覆盖参数绕过守门：`book_driver.cmd_resume` 校验前置、写清洗值、失败 `return 2` 不半改 state。
- **#5 (P2)** plan_target 超 200 self-block：`run_params.INT_CAPS["target_chapters"]` 200→2000（与 chapters/plan_target 对齐），WebUI 200 由 `routes._validate_plan_chapters_params` 内联独立保持。

## Acceptance

- 全量 `OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests` 绿（基线 iter065 = 1269）。
- `verify.sh` exit 0、`preflight` 无 FATAL。
- 铁律⑨：runner 改动属高风险 → 拆 2 个独立视角只读 subagent 并行审（正确性 + 安全/复用），结论写入 Acceptance Result。
- 铁律⑦：aeloon 并行工作文件（`docs/AELOON_INTEGRATION.md`、`CLAUDE.md`、`aeloon超前部分实现指南/`、`scripts/aeloon_sync_check.sh`）**不并入** iter066 代码提交。

## Implementation Notes

- **#4**：拆成两套是关键（用户精炼）。`coerce_finite_confidence(value, default=0.0)` 仅用于**写 timeline**（创建分支 / legacy advance 写入 / `timeline_not_a_list` 日志参数），坏值→0.0 既保证标准 JSON 又让创建路径 confidence 落到创建门下方（fail-closed）。`select_auto_indexes` **不能**用 coerce——它当前对 unparseable 已 `continue`，但 `float("inf")` 解析成功后 `inf >= min_confidence` 恒 True 会被选中（nan 已被 `>=` 挡掉，inf 是漏网点）；改法是 `if not math.isfinite(conf): continue`，保持「坏值 skip」语义。若 coerce→0.0，`--min-confidence 0` 时坏值反被选中（契约倒退）。
- **#2**：`entity_ids` 集合在循环外构建一次（复用 `entities.py:101` 的 `{str(e.get("id")) ...}` 模式）；`creation_unknown_entity` reason 排在 `creation_empty_state`/`creation_hard_conflict` 之后、`creation_below_confidence` 之前。新校验只在 `if allow_creation:` 外壳内，**allow_creation=False 时完全不走**——iter052 稀疏边 `relationship_not_found` 路径字节级不变。
- **#1**：book_runner.py 顶部加 `from . import run_params`；`allow_creation = ea_cfg.get("allow_creation") is True`（字符串 `"false"`/`"true"`/任意非 bool → False）；`creation_confidence` 用 `validate_float(..., minimum=0.0, maximum=1.0)` 的清洗值，err 回 0.85。整块仍在既有 try/except 内兜底。
- **#3**：把 budget_cny/step_timeout_minutes 校验提到**动 `state["params"]` 之前**（原 pause/force_debate 写入之前），任一 err → `print(err, file=sys.stderr); return 2`，此时 state 完全未触碰；通过后写 validate 返回的**清洗值**。`budget_cny` 走 `validate_float(minimum=0.0)`，`step_timeout_minutes` 走 `validate_int(minimum=0, maximum=1440)`（driver 全程当 int 用，`DEFAULT_STEP_TIMEOUT_MINUTES=180`）。`is not None` 覆盖语义与原 for 循环一致。
- **#5**：`routes.py:2026` `_validate_plan_chapters_params` 把 200 **内联写死、不读 INT_CAPS**，故改 INT_CAPS 只影响 CLI/driver，WebUI 单次上限自动保持 200（解耦零 blast radius）。`main.py:553` 注释更新说明 CLI 2000 / WebUI 200 的不对称是有意解耦。

## Acceptance Result

- **canonical 1281 tests OK**（基线 iter065 = 1269，+12：test_entity_advance +4 / test_apply_advance_auto +2 / test_book_runner +2 / test_book_driver +4；test_run_params 改 2 个既有边界测试，未增数量）。
- `verify.sh` exit 0（须 `PATH=$PWD/.venv/bin`）；`preflight` 无 FATAL。
- **铁律⑨ 双视角只读 subagent 审查**：
  - **正确性 + 契约**：五条修复实现正确完整，无 bug、无契约破坏（确认 allow_creation=False 时稀疏边路径字节对齐）、测试覆盖充分（选择/创建/写入三路径 + state 不半改不变式）→ **可提交**。
  - **安全 + 复用**：无 `sk-`/密钥/`.env` 风险；日志与 JSON 序列化均经 coerce 硬化（不再写 NaN/Infinity 字面量）；`cmd_resume` 的 `print(err)` 来自 run_params、只含参数名+约束不回显原值；`validate_float` 与 `coerce_finite_confidence` 的 isfinite「重复」是语义正当（守门 vs 透明清理）→ **安全可提交**。
  - **未修风险（诚实登记）**：`cmd_resume` 校验与 `_build_params` 的 validate 有结构相似，可在未来覆盖命令增多时抽公共函数（本轮按铁律⑦ scope 收敛不做）。
- **关键证据**：`creation_confidence:"nan"` → 回落 0.85；`allow_creation:"false"` → 不创建；resume `--budget-cny nan` → `budget_cny must be a finite number` + return 2 且 state 未改；resume `--step-timeout-minutes 99999` → `step_timeout_minutes must be <= 1440`；`target_chapters=201` 现通过、`2001` 拒；driver `chapters=200 resume_from=50` → plan_target=249 校验通过（不再 self-block）。

## 文件变更汇总

- `src/entity_advance.py`：新增 `coerce_finite_confidence`；`select_auto_indexes` 加 isfinite continue；`_apply_selected` src/dst strip + `creation_unknown_entity` 存在性校验 + 三处写 confidence 改 coerce；`import math`。
- `src/book_runner.py`：`from . import run_params`；`_auto_apply_advances` 配置解析 fail-closed（is True + validate_float）。
- `src/book_driver.py`：`cmd_resume` 数值覆盖参数校验前置 + 写清洗值 + 失败 return 2 不半改 state。
- `src/run_params.py`：`INT_CAPS["target_chapters"]` 200→2000。
- `main.py`：plan-chapters arm 注释更新（CLI 2000 / WebUI 200 解耦）。
- `tests/`：test_entity_advance（nonfinite/ghost/whitespace/legacy-coerce）、test_apply_advance_auto（select isfinite ×2）、test_book_runner（配置 fail-closed ×2）、test_book_driver（resume 守门 ×3 + 长程 plan_target ×1）、test_run_params（200→2000 边界 + CLI over-2000 改名）。

## 不在本轮范围

- **iter067（codex findings 下）**：#6 plan_compliance 建议被 `[:5]` 截断（reviewer prepend）、#7 standalone review 不传 chapter_plan_item（含 CLI review-chapter）、#8 Web 路径脱敏（jobs.py:899 + wizard.py×4）。
- **jobs.py:891** `BookRunBlocked` 的 `str(exc)`：与 #8 同类，readiness 文案通常不含绝对路径，留 iter067 #8 一并评估。
- **cmd_resume / _build_params 校验抽公共函数**：审查建议，scope 收敛顺延。
- **codex #6 (b) outline-drift warn→block**：iter065 顺延项，仍未做（与本轮 codex findings 无关，独立顺延）。

## Notes

- codex findings 编号映射：#1=book_runner.py:904 / #2=entity_advance.py:266-308 / #3=book_driver.py:849 / #4=entity_advance.py:272·368·92 / #5=book_driver.py:799（实修在 run_params.py:41）。
- 本轮消掉了 iter065 README SOP 里登记的「confidence 非有限值写入是既有风险、legacy advance 同存、顺延」——#4 的 coerce 已覆盖创建 + legacy 两条写 timeline 路径。
- 计划文件：`~/.claude/plans/codex-findings-p1-src-book-runner-py-lin-agile-bunny.md`（含 8 条核实结论 + 2 轮完整方案）。
- 下一步：iter067 实施 #6/#7/#8。
