# Iteration 047B2：iter46–47 验收 + 多 subagent 对抗测试 + H/M 修复

> 接 iter047（047a–d）之后的一轮**验收 + 加固**。对 iter046 / 046B / 047a–d 做多 subagent 对抗测试 + WebUI E2E + 真模型冒烟，直接修复确认的 H/M 缺陷并补回归测试。

## Context

- iter046（AgentWrite 分段写）/ 046B（debate persona 兜底）/ 047a–d（context_budget、KB 起点安全、伏笔 TTL 闸门、reader/character 剧透轴）已 commit 未 push，按 `AGENTS.md:31` 需用户验收。
- 验收方式：6 个对抗 subagent（A–F，mock-only、只读、零文件重叠）按模块分工复现/挖掘缺陷 → 主 agent 汇总定级 → 直接修复 H/M + 回归测试 → WebUI E2E + 真模型冒烟在修复后的状态上验证。
- **验收方法论修正（重要）**：iter047 各 PLAN 的 Acceptance 用 `pytest` 跑出"3 个 pre-existing failures"（`test_env_isolation` + `test_llm_client_cache×2`）。经核实这是 **runner 调用 artifact**——canonical runner 是 `python3 -m unittest discover -s tests`（`AGENTS.md:51`/`:111`），其下**全绿**。pytest 下 `config._running_under_unittest_discover()` 为 False，`.env`（`OPENAI_STREAM=1` + API keys）被 `load_dotenv` 反复重注入（litellm 也在 import 时 reload dotenv），导致 3 个隔离/缓存测试失败。本轮一并修复（M9），使两种 runner 一致全绿。

## 验收结论（iter46–47）

**设计承诺 / 正常路径成立**（对抗验证 PASS 的关键不变量）：
- 047b 正常路径端到端零泄漏：manifest+index 合法时，writer/planner/debater/external-review 4 个注入接缝 + 实体渲染全部 0 命中起点后 canary，起点前内容正常保留（Agent F 端到端审计）。
- 047b `style_samples` 永不外泄（Agent A canary）。
- 047d reader/character 轴 fail-open / byte-identical：三个新字段缺失时与 iter021 逐字节一致（Agent A）。
- 047a context_budget：预算宽松 byte-identical、hard 层永不丢、确定性、count_tokens 与 LLMClient parity、零接线（Agent C）。
- 046 分段写：flag off / 空 segments 单发 byte-identical；**segments 不进指纹（向后兼容关键）成立**（Agent D）。
- 046B persona guard：workspace 模式下 personas 缺失/`{}`/`null`/`[]`/损坏 5 种畸形全部 fail-fast，零龙族泄漏、零崩溃；legacy 模式不回归（Agent E）。
- 确定性：kb_view / entities / context_budget / writer prompt 组装 double-run SHA 一致（Agent F）。

**异常 / 降级路径存在多个真实缺陷**（已在本轮修复）——见下表。核心病灶：047b 把"数据完整性"当前提而非校验；047c 对非法/非规范字段缺乏 fail-closed 兜底；测试隔离只认 unittest 不认 pytest。

## 对抗发现与定级

| 级别 | 缺陷 | 位置 | 发现 |
|---|---|---|---|
| **H1** | 损坏 `knowledge_index.json` 抛 `JSONDecodeError` 而非 fail-open（`read_json` 不捕；4 调用点全不接，`book_runner` 仅捕 `OSError`） | `kb_view.py:91` | A/F 真实栈复现 |
| **H1b** | 同缺陷波及 `chapter_manifest.json` / `start_chapter.json`（裸 `read_json`） | `start_point.py:56,125`、`kb_view.py:44` | A |
| **H2** | 起点已设但 manifest 缺失/空 → `start_idx=None` → 全保留 → 起点后剧透泄漏，且块头伪称"起点安全…已过滤剧透" | `kb_view.py:104` | A/F 真实 prompt 复现 |
| **H3** | must-resolve fail-closed 闸门被 `except Exception: overdue=[]` 静默降级为 fail-open（畸形 `ttl` → `int()` 抛 → 被吞 → 整闸门放行） | `book_runner.py:418-426`、`foreshadowing.py:137` | B |
| **M1** | 伏笔"复活"：`_item_id` 含 description，重抽取改写描述 → 新 id → 人工 resolved 丢失 | `foreshadowing.py:52-59` | B |
| **M2** | `_is_resolved_status` 子串误判：`irresolvable` 含 `resolv` → 误判已闭合 → 真开放伏笔不追踪 | `foreshadowing.py:73` | B |
| **M3** | 未知/大小写状态绕过闸门：`deferred`/`Open`/`open ` 的 must-resolve 项超期也不阻断 | `foreshadowing.py:157` | B |
| **M4** | 负 `min_chars` 性能炸弹：收缩循环空转至 100k guard，真 tiktoken 单次 ~37.7s 且不可被信号中断 | `context_budget.py:125` | C |
| **M5** | `kept_states[-1]` 取数组末尾而非 manifest 最近（数组序=文件名字典序，生产可达错位） | `kb_view.py:126` | A |
| **M6** | preflight 伏笔口径与真实闸门谓词不一致：只算 `expired`，漏 `open 且过 TTL` → 运维看到"0 超期"却被拦 | `preflight.py:294-305` | E |
| **M7** | `book_runner` legacy KB 剧透告警用 CWD 相对 `Path(".")`，与 preflight/真实注入路径背离 → 非仓库根 CWD 下告警被静默吞 | `book_runner.py:406` | E |
| **M8** | 分段 `is_final` 误置于非末段 → 章中"假结尾"+ 双钩子（`is_final` 仅 OR，无"仅末段"约束） | `writer.py:809` | D |
| **M9** | pytest 3-fail artifact：`.env` 反复重注入（detector 不认 pytest；litellm import reload dotenv） | `config.py:180`、`llm_client.py:92` | E |

L 级（记入 follow-up，本轮不修）：047b 近空 index 只给 header 行无裸 KB 回退；duplicate chapter_id first-occurrence（畸形 manifest 才中招）；047c TTL strict `>` 叠加 `resume_from-1` 的 1 章过度宽限；context_budget docstring 对 `max_chars` 时 byte-identical 措辞不精确；046 非末段 prompt 仍渲染整章 `ending_hook` 文本、空段静默丢弃、`sum(段配额)` 无校验、`segment_no` 被 writer 忽略；F 注：实体 `key_facts` 不按 chapter 过滤（如写入起点后事实需复核）。`debater`/`book_runner._load_raw_chapter_plan` 等其它裸 `read_json` 非 047b 安全路径，未在本轮扩面。

## 修复实施

**KB 起点安全（`src/kb_view.py` + `src/start_point.py`）**
- H1：`start_safe_knowledge` 的 index 读取改 `read_json_optional`（损坏→回退裸 KB）。
- H1b：`kb_view._manifest_order` 与 `start_point._load_manifest`/`get_start_chapter_id` 的 `read_json` → `read_json_optional`。
- H2：`start_safe_knowledge` 在渲染前用 `_manifest_order()` 校验起点可定位（`order.get(start) is not None`）；定位不到则 fail-open 回退裸 KB，**不再渲染伪"起点安全"块**；`order` 下沉为 `_render_start_safe_index(index, start, order)` 参数。
- M5：角色状态取 `max(kept_states, key=manifest 序)` 而非 `[-1]`。

**伏笔闸门（`src/foreshadowing.py` + `src/book_runner.py`）**
- H3：`_overdue_by_ttl` 用 `try/except (TypeError,ValueError): return True`（畸形 ttl/planted 视作立即超期，fail-closed）；`book_runner` 收窄 `except`，异常时追加 `foreshadowing_gate_error:<Type>` blocker 而非静默 `overdue=[]`；`_blocker_kind` 归类。
- M1：新增 `_normalize_desc`（collapse 空白 + 去首尾标点），`_item_id` 用归一化描述（id 稳定、保留原始描述）。
- M2：`_is_resolved_status` 排除 `irresolv`。
- M3：`overdue_must_resolve` / `gc` 用 `str(status or "").strip().lower()`；未显式 resolved/expired 的（含未知词/错大小写）按 open 处理，超期即阻断。

**预算装配（`src/context_budget.py`）**：M4 — `floors=[max(0,min_chars)]`，候选谓词与 `new_len` 用 `floors`；`budget_tokens=max(0,budget_tokens)`。

**preflight / 路径（`src/preflight.py` + `src/book_runner.py`）**：M6 — preflight 同时统计 `must-resolve(expired, open)` 并据此告警；M7 — readiness KB 告警改用 `_kb_path()/_index_path()`（与真实注入同源、legacy 走 ROOT）。

**分段写（`src/writer.py`）**：M8 — `is_final = segment_index >= segment_total`（段位置权威，忽略计划误标）。

**测试隔离（`src/config.py` + `src/llm_client.py` + `tests/conftest.py`）**：M9 — detector 增 `"pytest" in sys.modules`；`llm_client` 顶部 OPENAI_STREAM pop 同样认 pytest；新增 `tests/conftest.py` autouse fixture 每个用例前 scrub mock env。canonical 不受影响（pytest 不在其 sys.modules；unittest discover 不读 conftest）。

## 回归测试

新增 `tests/test_iter047B2_regression.py`（13 项，逐缺陷"修复前可复现→修复后通过"）：H1 损坏 index fail-open、H1b 损坏 manifest/start fail-open、H2 manifest 缺失 fail-closed 无伪安全头无泄漏、M5 manifest 序、H3 畸形 ttl 仍 blocked、M1 改写不复活、M2 irresolvable 仍追踪、M3 未知/大小写仍阻断、M4 负 min_chars 不空转（计数 <50 vs 修复前 ~200k）、M6 open must-resolve 告警、M7 readiness 走注入路径、M8 段位置权威。M9 的回归即现有 `test_env_isolation` + `test_llm_client_cache` 在 pytest 下转绿。

## Acceptance Result

- **canonical `unittest discover`：`Ran 657 tests OK`**（基线 644 + 新增 13，零回归）。
- **`pytest`：`657 passed`**（修复前 `3 failed, 641 passed` → 修复后 0 failed，M9 成功；两种 runner 一致全绿）。
- **WebUI E2E（preview 浏览器 + mock 服务，`is_mock:true`）**：landing/overview/continue/chapters/chapter/reviews/insights/jobs 全部渲染 200；write-book mock job 完整生命周期（running→完成+轮询），多 Agent 评审闭环正常拒绝 mock 占位稿；console 0 error，network 仅 1 条启动竞态。**iter47 UI 端到端验证**：047b KB 起点安全已生效（无 index 缺失 warning）；临时注入含畸形 `ttl` 的超期 must-resolve registry 后，readiness 正确返回 `foreshadowing_must_resolve_overdue:2`（**H3 修复——畸形项与正常项都被计入、不再静默放行**），诊断区显示 M6 新文案"…已超期、N 个仍 open…"；删 registry 后 fail-open 恢复。
- **真模型冒烟（tianlong，`openai/gpt-5.5-high`，经代理）**：连通性 OK（2.8s）。`write-book` ch4（`--tier low --force --max-retries 1 --skip-external-review`）→ **`status=succeeded`，`verdict=Approve`**（5-agent panel：3 Approve / 2 Reject，`panel_score=7.04 ≥ 6.5`，`approve_count=3 ≥ 3`，`rewrite_count=1`），产出 **14641 字符**连贯《天龙八部》章节；成本 **¥1.04**（16 calls，prompt 345k / response 47k tokens）。
  - **047b KB 起点安全在真实数据端到端生效**：`start_safe_knowledge` 注入 **7323 字符**结构化块（vs 原文 `global_knowledge.md` 9712，过滤掉 ~2.4k 起点后内容），含"起点安全"头、仅含起点 `ch002` 及之前状态；多位 reviewer 指出 writer 自创的"灵鹫宫圣使/黑鹫木牌"设定"超出 KB 已铺垫内容"，**反向印证 KB 确被过滤到起点前**。
  - **046 指纹向后兼容真实验证**：`plan_fingerprint` 正常匹配，未触发 `plan_fingerprint_mismatch`。
  - 既有 L 级（非本轮、非阻断）：entity advance `apply_advance_failed`（`ValueError: relationship not found: ent_wuliang_east <-> ent_wuliang_west`），write 仍 succeeded。

## 文件变更汇总

- 源码：`src/kb_view.py`、`src/start_point.py`、`src/foreshadowing.py`、`src/book_runner.py`、`src/context_budget.py`、`src/preflight.py`、`src/writer.py`、`src/config.py`、`src/llm_client.py`
- 测试：`tests/test_iter047B2_regression.py`（新）、`tests/conftest.py`（新）

## 不在本轮范围

- `git push`（按 `AGENTS.md:31` 等用户验收）。
- L 级清单（上文）；047d producer 落地、047c per-chapter gc 持久化/CLI；writer 多层 prompt 迁移到 `context_budget`。

## Notes

- 6 个对抗 subagent 全程 mock-only、只读真数据、探针在 /tmp，未污染 repo（遵守 `AGENTS.md:30/:35`）。
- WebUI 演示用的临时 registry 与真模型冒烟会写 `workspaces/tianlong/`（用户已授权；workspaces/ 不进 commit）。
