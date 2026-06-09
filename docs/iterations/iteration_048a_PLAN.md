# Iteration 048a — 小白四步工作台·后端骨架

> iter048 串行子迭代 1/3（048a 后端骨架 → 048b 前端工作台+大纲回写 → 048c 细纲只读+重生成+写书兼容）。总设计与红队结论见 `~/.claude/plans/02-phase-iter048-*.md`（草拟）。本轮只做后端、无前端、无指纹链。

## Context

iter048 是 Phase 6（产品力补齐）路线图既定迭代「小白四步封装：一句话开书 → 四步按钮 → 全程可编辑 → 一键测 Key」。初版单迭代计划经对抗 subagent 红队审查，证伪两处硬伤：(1) 细纲 JSON 手改回写会撞 `write-book` 的 `plan_fingerprint` 门禁（`book_runner._plan_metadata_failures`），"能编辑但编辑完写不了书"；(2) `prepare` 复合 step "机械抽函数无语义变更"的说法被进度分母 + `test_auto_pipeline` 契约双重证伪。结论：原计划 scope 收不住、切分方向部分反了。

据此把 iter048 拆成**按依赖+难度排序的串行子迭代**，把指纹链暗礁隔离到 048c 单独验证。**048a 取最干净的后端骨架三件**：均为后端、互相独立、有现成复用基座、无前端 / 无指纹链 ——
1. premise「一句话开书」入口（落 `小说txt/seed.txt`，喂现有 greenfield 路径）；
2. `prepare-greenfield` 复合 step（把 9 步 SOP 的前 6 步 normalize→apply-bootstrap 封成一个可单独触发的 job，含红队点名的进度契约修正）；
3. 全 task 一键测 Key 矩阵（枚举各 task 模型、去重探测连通性）。

## Plan

1. **`src/auto_pipeline.py`**：抽 `_run_prepare_steps(*, progress_cb, total, emit_done, skip_extract, extract_limit, force)`，把 `run_auto_pipeline` 的前 6 步搬入；`total` 参数化进度分母、`emit_done` 控制是否自发 `("done",1.0)` 哨兵。`run_auto_pipeline` 调它传 `total=9, emit_done=False`，后续 debate/plan/write/done 不变。
2. **`src/web/jobs.py`**：新增 `_step_prepare_greenfield` 调 `_run_prepare_steps(total=6, emit_done=True)`（6 步重映射到自含的 0→1.0 进度条）；注册到 `STEP_HANDLERS["prepare-greenfield"]`（白名单加一行 = code review event）。
3. **`src/web/wizard.py` + `routes.py`**：新增 `start_premise_workspace`（JSON 入口，校验 name + premise 1-2000 字 → `init_workspace(type="novel")` → 包装为单章写 `小说txt/seed.txt` + 路径越界防御 → 202 `{name}`，不起 job）；routes 注册 `api_wizard_premise_start` + `POST /api/wizard/premise-start`。
4. **`src/llm_client.py` + `src/web/diag.py`（新）+ `routes.py`**：`LLMClient.ping()`（mock 短路零联网、`max_tokens=1`、error 截断且 redact api_key）；`diag.collect_model_diagnostics()`（`TASKS` 硬编码、distinct model 去重各 ping 一次）；routes 注册 `api_diag_models` + `GET /api/diag/models`。
5. **`tests/test_premise_prepare_diag.py`（新）**：mock-only 覆盖上述全部 + 进度契约。

## Acceptance

- `OPENAI_MODEL=mock` 下 `python -m unittest discover -s tests` 全绿（基线 661 → 674，+13）。
- `OPENAI_MODEL=mock python main.py preflight` → FATAL/WARN none。
- premise 开书：合法 202 + `seed.txt` 含 premise；空/纯空白/超 2000 字/非法 name → 400；同名 → 409；非 JSON content-type → 415。
- `prepare-greenfield` step：经 `POST /run` 跑完 `succeeded`，进度填满到 `1.0`（不卡 5/6 或 5/9），产出 data 产物。
- `run_auto_pipeline` 仍发全 9 步 + `("done",1.0)`（`test_auto_pipeline` + 新回归测试双重守门）。
- `GET /api/diag/models`：mock 下 `is_mock:true`、`all_ok:true`、6 task 去重为 1 个 mock 探测、`litellm.completion` 断言 not-called（零联网）。

## Implementation Notes

- **进度契约（红队 #1 修正）**：原"机械抽函数无语义变更"是错的——`_notify` 写死 `total=len(STEPS)=9`，6 步复合 step 若 naive 复用会卡在 5/9≈56%；且 `test_auto_pipeline.py:67-70` 锁死 9 步顺序 + `("done",1.0)`。解法是把 `total`/`emit_done` 参数化：full pipeline 传 `total=9,emit_done=False`（契约 byte-identical），workbench step 传 `total=6,emit_done=True`（自含 0→1.0 条）。
- **premise 必须包装成单章（计划错误假设修正）**：原计划"关键技术前提"写"splitter 对任何非空 normalized≥1 章"——**实测不成立**。`chapter_splitter.HEADING_RE` 靠"第N章/楔子/序章"等标题分章，几十字裸 premise 无标题 → split 产 0 章 → 下游 extract 报 `chapter manifest not found`。修复：`start_premise_workspace` 把 premise 包成 `第一章 缘起\n\n{premise}\n` 再写 seed.txt，给 split 恰好 1 章作 KB 种子。KB 对短 premise 仍偏空（049 扩写增强），这是 greenfield 既定取舍。改动限在 wizard，不碰 splitter 核心。
- **测 Key 合规**：`ping()` mock 短路在 `import litellm` 之前（零联网）；真实分支 error 先 `replace(api_key,"***")` 再截断 200 字（铁律① 绝不回显 key）；用户点击触发的 `max_tokens=1` 探测性质等同 `preflight`（铁律⑥）。`diag.TASKS` 经 preflight 的 task model table 与全仓 `LLMClient("…")` 调用双重核对，确认为 `write/review/debate/extract/compress/plot_planner`。
- **scope 收敛**：`_summarize_result` 不为 prepare-greenfield 加专门分支（现有 dict 兜底 `{"keys": sorted(...)}` 够用）；收官审核发现并删除了本轮一度引入的 `base_index` 死参数（见 Acceptance Result 视角 A）。

## Acceptance Result

- **测试**：`unittest discover` = **674 OK**（基线 661 + 新增 13），零回归（删 `base_index` 为等价变换，待最终复核钉牢）。`main.py preflight` = FATAL/WARN none。
- **收官对抗审核（铁律⑨，3 视角）**：
  - **视角 A（pipeline 重构+进度契约，subagent 完成）**：从 `HEAD~1` 取 inline 版做 AST 函数边界 + dedent 逐行 diff、并 Python 复算所有 fraction。结论：**9 步契约 byte-identical**（prep 段 53 行 0 差异、tail 段 AST 切片 0 差异），debate/plan/write = 6/9·7/9·8/9 精确成立，两模式 fraction 正确，无可变默认 / 异常吞没 / 终态劫持。唯一可执行建议：`base_index` 两处皆传 0 且 tail 不联动 = 死参数 → **已采纳删除**。
  - **视角 B（premise 入口安全，主对话自审）**：path 越界防御 `resolve().relative_to` + name 已 `_validate_name` 双层；premise 非 str（list/dict）走 400；init_workspace 成功后写 seed 失败 `shutil.rmtree` 回滚干净；seed 包装即使 premise 含"第N章"最多多分章（无害）。无阻塞。
  - **视角 C（测 Key + key 泄漏，主对话自审）**：mock 短路零联网；两个 error 分支均不含原始 key（completion 分支 redact + 截断；import 分支异常与 key 无关）；去重 `setdefault(str(model))` 正确；空 clients 聚合 `all_ok=False/is_mock=False` 已处理。无阻塞。
- 视角 B 原计划用 subagent 但被用户中断、视角 C subagent 遇 ECONNRESET，故 B/C 由主对话只读核验完成；铁律⑨「≥1 subagent」由视角 A 满足。

## 文件变更汇总

- `src/auto_pipeline.py`（改）：抽 `_run_prepare_steps`（前 6 步、`total`/`emit_done` 参数化进度）；`run_auto_pipeline` 调它，9 步契约不变。
- `src/web/jobs.py`（改）：`_step_prepare_greenfield` + `STEP_HANDLERS` 注册 `"prepare-greenfield"`。
- `src/web/wizard.py`（改）：`start_premise_workspace`（premise→单章 seed.txt，路径防御，202）。
- `src/llm_client.py`（改）：`LLMClient.ping()`（mock 短路 / `max_tokens=1` / redact key）。
- `src/web/diag.py`（新）：`collect_model_diagnostics()`（TASKS 去重 ping 矩阵）。
- `src/web/routes.py`（改）：`import diag` + `api_wizard_premise_start` + `api_diag_models` + 2 行 `_ROUTES`。
- `tests/test_premise_prepare_diag.py`（新）：13 个 mock 测试。

## 不在本轮范围

- **048b**：四阶段工作台前端页（`/w/{name}/workbench`、`_WORKSPACE_SECTIONS` 入口、pollJob 驱动、gate、stage 探测防旧产物误判）、大纲 md 回写 `PUT /outline`、premise 前端入口。
- **048c**：细纲只读展示 + "重新生成细纲"（重跑 plan-chapters，天然重算指纹）+ write-book 兼容回归。
- **049**：正文逐章深度编辑 + 重 review；premise 扩写质量增强；设定（KB/entity_graph）编辑；真模型授权与测 Key 成本护栏深化。
- 本轮不跑真模型（铁律⑥），不做任何前端 / UI。

## Notes

- **premise 可行性是本轮最大发现**：计划假设"非空 seed → split≥1 章"被实测推翻，根因是 splitter 依赖章节标题。已用 wizard 端包装修复并写进回归测试，但这也提示 049 的"premise 扩写"需正视"几十字种子 → 高质量多章"的真实落差。
- **base_index 删除**：收官审核发现它是无消费者且无法实现偏移意图（`run_auto_pipeline` 的 tail 用自己的 `_notify`）的"坏预留"，已删除以免误导后人；048b 若需分阶段偏移进度再按需重新设计。
- **下一步（048b）**：注意红队另两条尚未兑现的修正——`_WORKSPACE_SECTIONS` 必须加 workbench 入口（否则侧栏无链接 + 高亮失效）、workbench 的 plan-chapters/write-book 调用必须显式传 `require_start_point:false`（不能复用 continue 页的 `true`）。
- 验收命令需用项目 `.venv/bin/python`（系统 python3 缺 pydantic/litellm）。
