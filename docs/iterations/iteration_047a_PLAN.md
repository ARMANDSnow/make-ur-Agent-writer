# Iteration 047a — context_budget 分层 token 预算装配器（基建）

> iter047 子迭代 1/4。总计划见 `iteration_047_PLAN.md`。

## Context

iter047 要把 writer/planner 散落的硬编码截断（如 `knowledge[:9000]`）换成「按预算 + 优先级」的确定性装配，并据此补 KB 剧透过滤 / 伏笔等。本子迭代先建共享基建 `context_budget`，**零接线、零回归**，供 047b/c/d 复用。

## Changes

- 新建 `src/context_budget.py`：
  - `Layer(name, text, priority, min_chars=0, max_chars=None, hard=False)` dataclass。
  - `assemble(layers, *, budget_tokens, token_counter)`：保持输入顺序；预算宽松 → 逐字 `"".join`（应用 max_chars 后）；超预算 → 从 priority 最低的非 `hard` 层先削、`hard` 永不削/丢、`min_chars` 为下限；确定性、必收敛（hoist 每轮一次计数）。
  - `count_tokens(text, model)`：从 `LLMClient._count_tokens` 抽出的自由函数（empty→`(0,"tiktoken")` / tiktoken→`(len(encode),"tiktoken")` / 异常→`(ceil(len/1.6),"estimate")`），token 计数单一真源。
  - `token_counter_for(model)`、`budget_for_task(task, margin_tokens=0)`（停在 `context_limit*0.9` 红线下）。
- `src/llm_client.py`：`_count_tokens` delegate 到 `count_tokens(text, self.model)`（`(tokens, method)` 返回不变 → `_request_meta`/`_log_call` 零变化）；删除多余 `import math`。
- **零接线**：未改 writer/planner/任何调用方。

## Acceptance Result

通过（mock-only）。

- 新增 `tests/test_context_budget.py` → **17 passed**（assemble：优先级淘汰 / hard 不丢 / min_chars 下限 / max_chars 上限 / 确定性 / 超大输入 / 真实 tiktoken 收敛 / 空 layers / 负预算 / 全 hard best-effort；count_tokens：delegation wiring + 冻结 oracle 对照 + estimate 分支 + empty）。
- 全量回归（3.13）：`.venv/bin/python -m pytest tests/ -q` → **618 passed, 3 failed**（3 个为既有、与本子迭代无关：`test_env_isolation` + `test_llm_client_cache`×2，见 iteration_045）。
- 子代理对抗 review 结论 **ship**：经验性确认 `count_tokens` 与历史实现 byte-faithful、`assemble` 在真实 tiktoken 与对抗 counter 下均收敛且 ≤ 预算、零接线；提出的硬化项均已收 —— M1（parity 同义反复 → 加冻结 oracle + 显式三分支）、M2（覆盖缺口 → 真实 counter / 负预算 / 空 layers / 全 hard）、L1（循环重复算 `joined()` → hoist `cur`）、N1（dead 守卫加注释）。
- 全程 mock，未跑真实模型，未 push。

## 已知后续

047b 起把 KB 层经 `assemble` 注入；`budget_for_task` 的 margin 由各调用方按需传。
