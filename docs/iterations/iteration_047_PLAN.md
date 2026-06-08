# Iteration 047 — 补 KB 剧透 gap（拆 047a–d）

> **独立详细计划**。Phase 6 总览见 `~/Desktop/Agent续写/02 Phase 与迭代路线图.md`；046 / 046B 见同目录 `iteration_046_PLAN.md` / `iteration_046B_PLAN.md`。
> 本迭代拆 **047a–d**，每个子迭代单独 commit + 单独 iteration doc（`iteration_047{a..d}_PLAN.md`），结果回填各自 Acceptance Result。
> 前置（已完成）：046/046B 已提交（`bdf040a` / `68462c5`，main，未 push）。

---

## Context（为什么做）

调研报告（`~/Desktop/AI小说续写商业化调研/AI小说续写商业化调研报告.md`，§3.1 借鉴 PlotPilot `reducer.py`）点名本引擎在「长程一致性 / 防剧透」上的两处 gap，而这正是 To B「卖铲子」主轴最看重的能力：

- **gap (a)**：实体/事实剧透过滤只按 `chapter_id` 一刀切，缺「读者已知 vs 角色已知」的细分轴。
- **gap (b)**：**KB 散文（`global_knowledge.md`）完全不过滤**——它是整本书压缩出来的全局知识，包含续写起点之后的原作结局/反转，会被原样塞进 writer/planner 的 prompt，造成剧透泄漏。当前仅 `preflight._check_start_safe_knowledge` 出一条 WARN，无任何实际过滤。

同时引入两件配套：**分层 token 预算装配器**（把散落的硬编码截断换成确定性预算）与**伏笔 TTL GC + must-resolve 闸门**（长篇必备的伏笔回收纪律）。

**取向（已与用户确认）**：拆成 4 个独立可测、可独立提交的子迭代；reader/character 走**轻量 fail-open**（不建完整逐角色知识图），**优先补高价值的 KB 起点安全过滤**；每个子迭代 mock-first、保持 `tests/` 全绿、**缺新字段时逐字回退现状**。

---

## 现状核实（已读代码，file:line）

- **剧透过滤（起点制）**：`entities._relationship_is_spoiler`(entities.py:41–59) + `manual_facts._fact_has_spoiler_evidence`(manual_facts.py:40–62)，均按 `start_point.is_after_start(chapter_id)` 判断「是否在续写起点之后」。
- **4 处消费方**：`writer._write_prompt`(writer.py:623 调 `render_active_state`)、`plot_planner._build_planner_prompt`(plot_planner.py:76/78)、`debater.build_outline`(debater.py:697)、`reviewer.review_text`(reviewer.py:319–320)。`global_facts_summary`(manual_facts.py:65–89) 同被 5 处消费（含 compressor.py:72）。
- **渲染**：`render_active_state(graph, respect_start_point=True)`(entities.py:62–127) 输出「当前活跃关系」块；timeline 项形如 `{anchor_chapter|chapter_id, state, active}`，**目前无 reader_known/character_known 字段**。
- **KB 不过滤（gap b）**：`writer.py:73` 直接 `kb_path.read_text()`，`plot_planner._load_knowledge`(plot_planner.py:280) 同样读原文；`preflight._check_start_safe_knowledge`(preflight.py:269–275) 仅 append 一条 WARN。
- **knowledge_index**：`compressor.build_knowledge_index`(compressor.py:33–57)，foreshadowing 条目已带 `chapter_id`（compressor.py:53）；characters/relationships/worldbuilding **暂未统一带 chapter_id**（047b 需补）。
- **token / 预算**：`LLMClient._count_tokens`(llm_client.py:430–442，返回 `(tokens, method)`)、`_check_context`(llm_client.py:444–450，`prompt+max_tokens > context_limit*0.9` 抛 `LLMContextOverflowError`)；`get_model_config(task)`(config.py) 提供 `context_limit`/`max_tokens`（`config/models.yaml`）。
- **闸门**：`book_runner.check_write_readiness`(book_runner.py:310–420) 收集 `blockers: List[str]` 并返回结构化结果；`_blocker_kind`(504–515) 归类、`_primary_blocker`(481–501) 给标签/CTA（范式如 `start_point_missing`）。preflight 在 `run_preflight` 里按 `_check_*(fatal/warn/info, root)` 注册。
- **workspace 路径**：`src/paths.py` 的 data 文件范式（workspace 级解析）。
- **测试夹具**：`tests/test_spoiler_filter.py`（设 `WORKSPACE_NAME` + 建 manifest + start_point + entity_graph + facts，已覆盖 chapter_id 过滤，是 047b/d 的理想扩展点）；`tests/test_entities.py`、`tests/test_manual_facts.py`、`tests/test_book_runner*.py`、`tests/test_preflight.py`。

---

## 047a — `context_budget.py` 分层 token 预算装配器（基建，先建，零接线）

**目标**：提供一个确定性、纯 stdlib 的分层装配器，后续 047b/c/d 用它把 writer/planner 里散落的硬编码截断（如 `knowledge[:9000]`）换成「按预算 + 优先级」装配；本子迭代**只建模块 + 单测，不接任何调用方**，零回归。

**新建 `src/context_budget.py`**
- 数据结构：`Layer(name: str, text: str, priority: int, min_chars: int = 0, max_chars: int | None = None, hard: bool = False)`（用 dataclass）。
- `assemble(layers: list[Layer], *, budget_tokens: int, token_counter: Callable[[str], int]) -> str`：
  - 行为：**输出保持传入顺序**（priority 只用于「超预算时先截谁」的决策，不重排可见顺序，避免 prompt 漂移）。
  - 预算充足时：逐字拼接各层（与现有朴素拼接逐字一致）。
  - 超预算时：从 **priority 最低**的非 hard 层开始，按 `max_chars`/`min_chars` 收缩文本，直到总 token ≤ `budget_tokens`；`hard=True` 层永不被截/丢。
  - 确定性：同输入同输出，不依赖时间/随机。
- **token 计数复用**：把 `LLMClient._count_tokens`(llm_client.py:430–442) 抽成模块级自由函数 `count_tokens(text, model) -> tuple[int, str]`，`LLMClient._count_tokens` 改为薄包装调用它（保持 `(tokens, method)` 返回不变，确保 `_request_meta`/`_log_call` 行为零变化）。`context_budget` 用该自由函数。
- 预算推导（供调用方用，本子迭代仅提供 helper）：`budget_for_task(task) = get_model_config(task)["context_limit"] - get_model_config(task)["max_tokens"]`，再留一点 margin 主动避开 `_check_context` 的 `*0.9` 红线。

**验收**：单测覆盖；不改任何现有调用方 → 全量回归零变化。
**测试（新 `tests/test_context_budget.py`）**：预算宽松 → 输出 == 各层朴素拼接（逐字）；超预算 → 先截最低优先级层、hard 层不动；确定性；超大输入 → 总 token ≤ 预算；`count_tokens` 自由函数与 `LLMClient._count_tokens` 结果一致。
**风险/回滚**：极低（无调用方）。回滚 = 删模块（client 薄包装一并还原）。

---

## 047b — KB 起点安全过滤（gap b，高价值，优先）

**目标**：让 writer/planner 看到的「全局知识」是「续写起点 ≤S 的读者视角」，不再泄露 S 之后的原作 canon。

**改动 / 复用**
1. `compressor.build_knowledge_index`(compressor.py:33–57)：给各类目条目统一带 `chapter_id`（foreshadowing 已带；扩到 characters/relationships/worldbuilding——它们本就来自带 chapter_id 的 per-chapter 抽取，flatten 时一并写入）。
2. 新增 `start_safe_knowledge(*, respect_start_point=True) -> str`（放新 `src/kb_view.py`，或 `manual_facts.py` 邻域，与现有 `global_facts_summary` 同风格）：读 `knowledge_index.json`，过滤掉 `start_point.is_after_start(chapter_id)` 的条目；**无 `chapter_id` 的条目保留（fail-open）**；渲染为结构化「全局知识（起点安全）」块。无起点 / 无 index → 回退现有原文 KB（**逐字不变**）。
3. 接线：`writer._write_prompt`(writer.py:73 读 KB → 619 注入) 与 `plot_planner`(`_load_knowledge` plot_planner.py:280 → `_build_planner_prompt`:340)：「全局知识」层改用 `start_safe_knowledge()`，并经 047a 的 `assemble` 作为 KB 层注入；**其余层顺序/内容不变 → 预算不紧时整体逐字不变**。
4. `preflight._check_start_safe_knowledge`(preflight.py:269–275)：从「仅 WARN」升级为报告 KB 是否已起点安全过滤（过滤可用 → INFO；不可用 → 保留 WARN）。

**验收**：index 中 `chapter_id` 在起点之后的条目被排除出装配后的 KB 块；起点前 / 无 `chapter_id` 条目保留；无起点 → KB 块逐字不变；preflight 反映过滤状态。
**测试**：扩 `tests/test_spoiler_filter.py`（复用其 manifest+start_point 夹具，加 KB 块过滤用例）；compressor 测加「各类目带 chapter_id」断言。
**风险/回滚**：散文 `global_knowledge.md` 非章节分段、难逐章过滤 → 本子迭代**以结构化 index 为起点安全 KB 源**、原文散文作 fail-open 兜底（如需更彻底，compressor 后续再产 `global_knowledge.start_safe.md`，留作 047b+）。回滚 = KB 层切回原文读取。

---

## 047c — 伏笔 TTL GC + must-resolve fail-closed 闸门

**目标**：把扁平的 foreshadowing 列表升级为有「种植章 / TTL / 必须回收」状态的 registry，超期未回收的 must-resolve 伏笔**挡住续写入口**（长篇质量纪律）。

**改动 / 复用**
1. 新建 `src/foreshadowing.py` + `paths.foreshadowing_registry_path()`（仿现有 data 文件范式）：registry 持久化 `data/foreshadowing_registry.json`（workspace 级）。结构：
   ```json
   {"version": 1, "items": [
     {"id": "fo_001", "description": "...", "planted_chapter": 3, "ttl": 8, "must_resolve": false, "status": "open"}
   ]}
   ```
   从 `knowledge_index.json["foreshadowing"]`(compressor.py:53，已带 chapter_id) 构建 `planted_chapter`。
2. **TTL 以「章数」而非 wall-clock**（确定性、可测、规避 `Date.now`）：`gc(current_chapter)` 把 `current_chapter - planted_chapter > ttl` 且仍 `open` 的标 `expired`，产确定性报告；`resolve(id)` 标 `resolved`。
3. **must-resolve 闸门**：`gc` 后若存在 `must_resolve` 且 `expired` 的项 → `book_runner.check_write_readiness`(310–420) 追加 blocker `foreshadowing_must_resolve_overdue`；扩 `_blocker_kind`(504–515)（`if "foreshadowing" in blocker: return "foreshadowing_overdue"`）+ `_primary_blocker`(481–501) 标签表（`"foreshadowing_overdue": ("有 must-resolve 伏笔超期未回收", "review_foreshadowing", "查看伏笔状态")`）。
4. preflight 加 `_check_foreshadowing_registry`（WARN 级 GC 状态，仿 `_check_start_safe_knowledge` 注册到 `run_preflight`）。
5. **可选**：把「待回收伏笔（open / must-resolve）」作为一层经 `assemble` 注入 writer prompt——**registry 不存在则不注入 → 现有 prompt 逐字不变**（规避 prompt-substring 测试风险）。

**验收**：plant→open、resolve→resolved、超 ttl→expired 均确定性；`must_resolve` 超期 → `write-readiness` 返结构化 blocker + 正确 `primary_blocker.kind`；**无 registry → 行为完全不变**。
**测试**：新 `tests/test_foreshadowing.py`（plant/resolve/expire/must-resolve 挡 readiness/无 registry no-op）；扩 `tests/test_book_runner*.py`（blocker + primary_blocker 断言，仿既有范式）+ `tests/test_preflight.py`。
**风险/回滚**：registry 漂移于真实进度 → 除 `must_resolve` 外仅咨询性。回滚 = 不建 registry（闸门/注入自动 no-op）。

---

## 047d — reader/character 细分轴（轻量 fail-open，风险最高放最后）

**目标**：在 start-point 过滤之上，加**可选**「读者已知 vs 角色已知」轴，防止把读者尚未读到的反转写进某角色 POV。**不建完整逐角色知识图。**

**改动 / 复用**
- `entities.py`：`render_active_state`(62–127) + `_relationship_is_spoiler`(41–59) 的 timeline 项加**可选** `reader_known`（读者获知章）/`character_known{char_id: 章}`；渲染加 `viewpoint` 形参（默认值保持现状输出）。`manual_facts._fact_has_spoiler_evidence`(40–62) 加可选 `reader_known_after`。
- **缺字段 → 完全回退 start-point/chapter_id 现状（fail-open，零破坏）**；4 处调用方默认 `viewpoint` 不变，**仅 writer 续写路径**用 reader 视角投影。

**验收**：`reader_known=ch10` 的关系/事实，写 ch5 时被过滤、写 ch12 时出现；≥1 fixture 体现 reader≠character；新字段全缺时 `tests/test_spoiler_filter.py`/`test_entities.py` 全绿（逐字不变）。
**测试**：扩 `tests/test_spoiler_filter.py`（reader/character 用例 + 缺字段逐字不变回归）。
**风险/回滚**：触全仓最受测的 entities/facts + 4 调用方 → 严格按字段存在性 gate + 默认 viewpoint 不变。回滚 = 移除可选字段读取。

---

## 子迭代顺序、依赖与共享

- **顺序**：047a（基建）→ 047b（KB 起点安全，高价值）→ 047c（伏笔 GC + 闸门）→ 047d（reader/character，最后）。每步独立 commit（`Iteration 047a: …`）、独立 `iteration_047{a..d}_PLAN.md`、独立全绿。
- **依赖**：047b/c/d 都复用 047a 的 `assemble` 与 `count_tokens`；047b 的 chapter_id 补全为 047c 的 registry 提供 `planted_chapter` 来源；047d 复用 047b 已经过 `assemble` 的注入点。
- **跨子迭代复用清单**：`context_budget.assemble`/`count_tokens`（b/c/d）；`start_point.is_after_start`（b/d）；`knowledge_index.json` chapter_id（b/c）；`book_runner._primary_blocker` 标签范式（c）；`tests/test_spoiler_filter.py` 夹具（b/d）。

## 全局风险与缓解

1. **装配重构扰动全仓最受测代码**（writer/planner 的 prompt substring 测试）→ `assemble` 预算不紧时**逐字复现原序**；KB/伏笔/reader 全部按「新字段/registry 存在性」gate，缺则 no-op。
2. **must-resolve 闸门误挡**（registry 与真实进度漂移）→ 仅 `must_resolve` 项 fail-closed，其余咨询性；`_primary_blocker` 给明确 CTA。
3. **token 自由函数抽取**改到热路径 → 保持 `(tokens, method)` 返回与 client 行为逐字不变，单测对齐。

## 验证（命令 + 每子迭代）

```bash
cd ~/Desktop/Agent续写项目
PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python -m pytest tests/ -q   # 应保持「绿 + 3 个既有无关失败」
```
- **047a**：`test_context_budget.py`（优先级淘汰 / hard 不丢 / 确定性 / 预算不紧时逐字=朴素拼接 / count_tokens 对齐）。
- **047b**：扩 `test_spoiler_filter.py`（起点后 index 条目被排除、起点前/无 chapter_id 保留、无起点逐字不变）+ compressor chapter_id 断言。
- **047c**：`test_foreshadowing.py`（plant/resolve/expire 确定性 + must-resolve 超期挡 readiness + 无 registry no-op）；扩 `test_book_runner*` + `test_preflight`。
- **047d**：扩 `test_spoiler_filter.py`（reader_known/character_known；新字段全缺时逐字不变）。

> 既有 3 个失败（`test_env_isolation` + `test_llm_client_cache`×2）为 iter045 起记录在案、与本计划无关；每子迭代须保证不新增失败。

## Acceptance Result

（待 047a–d 逐步实现后回填；或见各 `iteration_047{a..d}_PLAN.md`。）
