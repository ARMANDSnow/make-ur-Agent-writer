# Iteration 047c — 伏笔 TTL GC + must-resolve fail-closed 闸门

> iter047 子迭代 3/4。总计划见 `iteration_047_PLAN.md`。

## Context

`knowledge_index.json["foreshadowing"]` 是扁平列表、无生命周期状态。本子迭代加 workspace 级 registry（章数 TTL），超期未回收的 **must-resolve** 伏笔挡住续写入口——长篇质量纪律。

## Changes

- 新建 `src/foreshadowing.py` + `paths.foreshadowing_registry_path()`：registry `data/foreshadowing_registry.json`，项 `{id, description, kind, planted_chapter(=0), ttl(章数), must_resolve, status(open|resolved|expired)}`。
  - `build_registry`：从 knowledge_index 建，**merge-additive**（resolve/expire 决定经 re-extract 存活）；skip 已回收 status（substring 匹配，排除 `unresolved`/`partial`）；`must_resolve = kind ∈ {clue, unresolved}`。
  - `gc(current)`：open 且 `current-planted>ttl` → expired（仅变更才写盘）；`resolve(id)`。
  - `overdue_must_resolve(current)`：纯读；must_resolve 且 (expired 或 open-超期)；无/损坏 registry → `[]`（fail-open）。
- `book_runner.check_write_readiness`：`overdue_must_resolve(resume_from-1)` 非空 → blocker；扩 `_blocker_kind`/`_primary_blocker`（CTA `show_diagnostics`，避免死按钮）。
- `compressor.compress_all`：末尾 `build_registry`（闸门在正常流程自动生效）。
- `preflight._check_foreshadowing_registry`（INFO 计数 + must-expired WARN）。

## Acceptance Result

通过（mock-only）。

- `tests/test_foreshadowing.py` → **11 passed**（kinds 覆盖 / skip messy status / TTL 边界 / gc 持续 block / gc 条件写 / resolve / merge 保留 resolved / 损坏 registry no-op / 真实 registry 端到端 readiness / 首章不挡 / blocker 分类+CTA）。
- 全量回归（3.13）：`.venv/bin/python -m pytest tests/ -q` → **636 passed, 3 failed**（3 个既有、与本子迭代无关）。
- 子代理对抗 review = **fix-then-ship**，全部收掉：**H1**（must_resolve=kind=="unresolved" 只覆盖实测 18% open 伏笔 → 改 `kind ∈ {clue,unresolved}`）；**H2 correctness**（skip-list 精确匹配漏 `resolved_in_chunk`/`partially_*` → substring）；**H3 dormant**（无 caller build registry → 接进 `compress_all`；CTA 死按钮 → 降级 `show_diagnostics`）；**M1**（损坏 JSON → `read_json_optional` 降级）；**M2**（rebuild 复活已 resolved → merge-additive）；**M3**（off-by-one → `resume_from-1`）；**L1**（`_item_id` json 编码防注入）；**L2**（`_blocker_kind` 删冗余 `"foreshadowing" in blocker`）；**L3**（gc 条件写）。
- 实现自测抓到并修复一处共因 bug：substring `"resolv"` 误匹配 `"unresolved"`（已排除 `unresolv`/`partial`）。
- 全程 mock，未跑真实模型，未 push。

## 已知后续

gc 持久化（写循环每章调 gc）+ CLI `resolve`/列表 + 专门 web 伏笔视图，留后续；闸门当前靠 readiness 实时算 overdue（registry 由 compress 自动建），已可触发。
