# Iteration 067 - codex iter066 复审 residual 收口：fail-closed 数值/JSON 守门补全

## Context

iter064/066 已把「NaN/Infinity/越界数值导致守门 fail-open」修掉大部分。codex 在 iter066
之后做二次只读复审，又指出 3 个**残留 fail-open 缝隙**，本轮全部读码确认属实并一次收口：

1. **bool 当数字钻过 `validate_float`**（源头 `src/book_runner.py:911` creation_confidence）。
   Python `bool` 是 `int` 子类：`float(False)==0.0`、`float(True)==1.0`，`math.isfinite`
   通过、`[0,1]` 范围通过，故 `validate_float(False)` 返回 `(None, 0.0)`。配合
   `agents.yaml` 里 `allow_creation: true` + 误写 `creation_confidence: false`（YAML 裸
   `false` = 布尔 False），创建闸门被悄悄降到 0.0 → 任意 confidence 过闸 = 全开。
2. **`drive-book resume` 不重校验已持久化的 budget/timeout**（`src/book_driver.py:818
   cmd_resume`）。iter066 #3 只校验**显式覆盖值**；不传覆盖时，`driver_state.json` 里早已
   持久化的 `params["budget_cny"]`/`step_timeout_minutes` 原样流过。pre-iter064 残留 / 手改
   的 NaN budget → `_run_steps:356` `nan or 0.0` 为 `nan` → 成本闸 `spent >= nan` 恒 False
   = 静默关闸。
3. **`write_json` 默认 `allow_nan=True`，把已损坏图原样写回**（`src/entity_advance.py:211/235`
   + `src/utils.py:29`）。`read_json`/in-memory 深拷贝都保留非有限浮点，confirm 时
   `write_json` 把图里**别处既有**的 NaN/Infinity（非标准 JSON）原样写回。iter066 #4 只清洗
   了「当前 proposal 的 confidence」，没堵图本身的既有腐败。

目标产出：fail-closed 收口这 3 条 + 配套 mock 单测 + 项目 SOP 文档登记，按铁律⑤只 commit 不 push。

## Plan

- **F1（creation_confidence-bool）**：`src/run_params.py` 的 `validate_float`/`validate_int`
  在 coerce 前中心化加 `isinstance(value, bool)` 守门 → 一处堵死、连带封住全部 13 个调用方。
  `book_runner.py:911` 无需改：`cc_err` 为真 → `creation_confidence` 回落 0.85 安全默认。
- **F2（resume-persisted-budget）**：`cmd_resume` 改成对**生效后**的 budget/timeout 始终重
  校验（覆盖值优先，否则取持久化值），失败 `return 2`，把清洗后的值写回 `params`；复用
  `run_params.validate_float/int`，不新增逻辑。
- **F3（write_json-allow_nan）**：`src/utils.py:write_json` 的 `json.dumps` 加
  `allow_nan=False` 全局兜底——非有限浮点永不落盘；既有损坏图 confirm 抛 `ValueError`，
  auto_advance 经 `book_runner.py:931` 既有 `except ValueError` 优雅降级为 `apply_advance_failed`。

## Acceptance

- `tests/test_float_finite_guard.py` / `tests/test_int_finite_guard.py`：补 bool 被拒用例。
- `tests/test_book_driver.py`：持久化 NaN budget / bad timeout + 不传覆盖 resume → `return 2`。
- `tests/test_entity_advance.py`：图含 NaN，confirm 路径抛 `ValueError`。
- `tests/`（utils）：`write_json` 直写含 `float("nan")` → 抛 `ValueError`，无 tmp 残留。
- `OPENAI_MODEL=mock` 全量 `unittest discover` 全绿；`verify.sh`、`preflight` 通过；`git diff --check` 干净。

## Implementation Notes

- **F1 中心化拒 bool**：在 `validate_int`/`validate_float` coerce 前各加
  `isinstance(value, bool)` 守门（`validate_float` 放在 `allow_blank` 早返回之后，确保
  `None`/`""` 仍走默认值语义）。`book_runner.py:911` 无需改：`cc_err` 为真时既有
  `creation_confidence = 0.85 if cc_err else cc_val` 自动回落安全默认，闸门不再被
  `creation_confidence: false` 降到 0.0。两个 Explore 审查 agent 确认全仓 13 处调用方
  无一依赖「bool 当 1/0」旧行为（CLI argparse 永不产 bool，Web 字段是字符串）。
- **F2 effective 值重校验**：`cmd_resume` 把「仅校验显式覆盖」改为「校验生效值（覆盖优先，
  否则取持久化值）」。三处边界靠 `is not None`（非 falsy）守住：override `0.0`/`0` 是合法
  覆盖、持久化 `0.0` budget = 无上限（`allow_blank=True` 只判 `None`/`""`，不吃 0.0）、
  持久化 timeout `None`（老 state）→ `DEFAULT_STEP_TIMEOUT_MINUTES`。清洗值无条件写回，
  既有 NaN/越界值被覆盖为合法形态。验证仍在写回前 → 失败 `return 2`，state 不半改。
- **F3 write_json fail-closed**：`json.dumps(..., allow_nan=False)`，且**先序列化再建 tmp
  文件**，保证被拒 payload 不留下 `.tmp.*` 残留。这是全局后端兜底（entity_graph 回写 /
  driver_state / chapter_plan / *.meta 全覆盖）。专门跑了一个 Explore agent 反查「除零均值
  产 NaN 后落盘」的回归面：`_weighted_panel_score`(reviewer.py:242)、beat coverage
  (reviewer.py:277)、outline_drift hit_rate、lang_detect、book_runner 进度比例——**全部分母
  有 0 守卫**，confidence 聚合走 `coerce_finite_confidence`/Pydantic `ge/le` 约束，结论
  「no non-finite write_json path found」，全局化安全。
- **测试 seed 绕过**：F2/F3 的「既有损坏数据」用例必须用 stdlib `json.dumps`（默认
  `allow_nan=True`）直接写裸文件 seed——`_save_state`/`write_json` 现在自身就拒 NaN，无法
  用来制造 on-disk 腐败 fixture。

## Acceptance Result

- **单测**：`OPENAI_MODEL=mock .venv/bin/python3 -m unittest discover -s tests` →
  **1294 tests OK**（较 iter066 的 1281 +13：run_params bool ×2、write_json ×5、
  book_driver F2 ×4、entity_advance F3 ×2）。
- **verify.sh**：`OPENAI_MODEL=mock PATH=.venv... bash scripts/verify.sh` 通过（裸仓库
  graceful degrade，成本估算正常输出）。
- **preflight**：`main.py preflight` → **FATAL none / WARN none**。
- **git diff --check**：clean（无空白/冲突标记）。
- **代码审查（铁律⑨）**：`/code-review high`——2 个独立 Explore 视角（write_json 全局回归面 +
  F1/F2 逻辑边界）+ 主对话 line-by-line，**0 finding**（survived = `[]`）。
- **安全审查（铁律⑨/对口铁律①）**：diff secret 扫描无 `sk-`/key 材料；未触碰
  `.env`/`data/`/`outputs/`/`小说txt/`/`settings.local`；本轮为 fail-closed 硬化，提升安全姿态。
- **未修风险**：无。F3 对「既有 entity_graph 已腐败」采用拒绝写入（非自动清洗），代价是
  腐败图会阻断后续 advance 直到手动修——属预期 fail-closed 取舍，auto-heal 列 iter068 debt。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/run_params.py` | F1：`validate_int`/`validate_float` coerce 前各加 `isinstance(value, bool)` 拒绝守门 |
| `src/book_driver.py` | F2：`cmd_resume` 改为校验「生效后」budget/timeout（覆盖优先否则持久化值），清洗值无条件写回 |
| `src/utils.py` | F3：`write_json` 用 `allow_nan=False`，先序列化再建 tmp（被拒 payload 不留残留） |
| `tests/test_run_params.py` | 补 `validate_int`/`validate_float` 拒 bool 用例 ×2 |
| `tests/test_book_driver.py` | 新增 `Iter067ResidualGuardTests`：持久化 NaN budget/坏 timeout 无覆盖 resume → return 2 + happy path ×4 |
| `tests/test_entity_advance.py` | 新增 `ApplyAdvanceCorruptGraphFailClosedTests`：损坏图 confirm 抛 ValueError / dry-run 不写 ×2 |
| `tests/test_write_json_finite.py` | 新建：`write_json` 拒 NaN/Inf/嵌套非有限 + 无 tmp 残留 + 有限值 round-trip ×5 |
| `docs/iterations/iteration_067_failclosed_residual_guards.md` | 本轮迭代记录 |
| `docs/iterations/README.md` | 追加 iter067 索引行 |

## 不在本轮范围

- 真模型 smoke（铁律⑥，需用户授权）。
- entity_graph 读时自动清洗 / auto-heal 既有 NaN（→ iter068 debt）。
- codex 早前 P3 Web path redaction（async job/wizard）——非数值守门，本轮不并入。
- 仓库当前 dirty 的 Aeloon 并行文件——与本轮无关，不动。

## Notes

- 这是 iter065→066→067 的「codex 复审收口」第三轮：iter066 收了 #1-#5（fail-closed 数值/
  类型守门主体），本轮收 iter066 之后 codex 二次复审暴露的 3 个 residual。三条共同主题是
  **「守门写对了，但漏了一个钻入口」**：F1 漏 bool 子类、F2 漏持久化态、F3 漏既有腐败回写。
- **教训**：「fail-closed 数值守门」要同时堵住三类入口——(a) 本次输入、(b) 持久化/历史态、
  (c) 类型混淆（bool/字符串）。单测 fixture 制造「坏数据」时要警惕：守门加严后，连 seed 都得
  绕过守门（本轮 F2/F3 用裸 `json.dumps(allow_nan=True)` 直写）。
- **后续候选（iter068+）**：entity_graph 读时 auto-heal 既有 NaN（让 advance 不被腐败图阻断）/
  codex 早前 P3 Web path redaction（async job/wizard 原始错误串）/ AGENTS.md 列的既有 backlog。
