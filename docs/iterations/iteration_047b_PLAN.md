# Iteration 047b — KB 起点安全过滤（gap b）

> iter047 子迭代 2/4。总计划见 `iteration_047_PLAN.md`。

## Context

报告 gap (b)：KB 散文 `global_knowledge.md` 由全书压缩、含续写起点之后的原作结局/反转，被原样塞进 writer/planner/debater/外部 review 的 prompt，造成剧透泄漏（此前仅 preflight WARN，无实际过滤）。本子迭代让所有 KB 注入点只看「起点 ≤S 的读者视角」。

## Changes

- 新建 `src/kb_view.py`：`start_safe_knowledge(kb_path=, index_path=, respect_start_point=True)`。
  - 有起点 + 有 `knowledge_index.json` → `_render_start_safe_index`：从 index 过滤 `is_after_start` 的条目（无 `chapter_id` 保留 = fail-open），渲染结构化「全局知识（起点安全）」块（角色状态 / 关系 / 未闭合伏笔 / 世界观；`style_samples` **故意不纳入**——含 verbatim 原文引用会剧透）。
  - 否则（无起点 / 无 index / `respect=False`）→ 原文 KB 逐字（fail-open，byte-identical）。
  - **KB 路径是注入式 seam**：调用方传各自 `_kb_path()`/`_index_path()`，保证测试 patch 有效、不误读真实仓库 data（修 review M1）。
  - `_manifest_order` 保留 `chapter_id` 首次出现，与 `start_point._index_of` 对齐（修 review L1）。
- 接线 **4 处** KB 注入点（全部传各自路径）：`writer.write_chapters`、`plot_planner._load_knowledge`、`debater.run_debate`、`book_runner._build_review_context`（外部 review）。compressor 各类目条目本就带 `chapter_id`（无需改）。
- `preflight._check_start_safe_knowledge`：有 index → INFO（已起点安全），无 index → WARN；`book_runner` ready-check 过时警告同步（仅无 index 才 warn，修 review L2）。

## Acceptance Result

通过（mock-only）。

- 新增 `tests/test_kb_view.py` → **7 passed**（无起点 / 无 index / `respect=False` 逐字回退；起点后条目过滤、起点前/无 chapter_id 保留；注入 kb_path 生效；book_runner 外部 review context 起点安全）。
- 全量回归（3.13）：`.venv/bin/python -m pytest tests/ -q` → **625 passed, 3 failed**（3 个既有、与本子迭代无关：`test_env_isolation` + `test_llm_client_cache`×2）。
- 子代理对抗 review = **fix-then-ship**，已全部收掉：**H1**（`book_runner._build_review_context` 外部 review 漏接、仍把全书原文 KB 喂给 reviewer —— gap b 真正闭合的关键）已接线；**M1**（测试 patch `src.X.KB_PATH` 成死代码 + 读真实仓库 data）以**注入式 kb_path** 根治；**L1**（manifest 重复 id）/**L2**（过时警告文案）/**M2**（补端到端测试）/**N2**（preflight 文案补全）均收。
- byte-identical：无起点时 writer/planner/debater/book_runner 的 KB 注入与 047b 前逐字一致（子代理探针 + 全量验证）。
- 全程 mock，未跑真实模型，未 push。

## 已知后续

N1（`plot_planner._load_knowledge` 局部 import 风格）留 NIT。结构性根治：把所有 KB 读取强制走 `kb_view.start_safe_knowledge`、删散落的 `kb_path.read_text()`，可从源头杜绝再漏（follow-up）。
