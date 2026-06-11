# Iteration 050 — 全程可编辑闭环 + 预算护栏（产品打磨包）

> 承接 048d 预定、被 iter049 插队顺延的产品打磨工作。用户 2026-06-11 拍板范围：**编辑闭环优先**（#2 细纲结构化编辑 + #3 正文/设定编辑回写为核心，#1 UX/a11y、#6 B-M-2、#7 文档回填顺带摊销，**授权小额真模型 smoke ≤15 元**）；#4 premise 扩写质量与 Aeloon 进一步打磨顺延。

## Context

「全程可编辑」的最后一块拼图：设定/大纲已可编辑（048 系列），细纲只读+重新生成（048c），正文与 KB/entity_graph 无编辑回写。048c 红队证伪过「PUT 原始 JSON + 手搓指纹」的原路——本轮的解法是把「重跑 plan-chapters」泛化为「复用 plot_planner 的指纹重算唯一入口」：结构化字段 PUT → Pydantic 校验 → `_attach_plan_fingerprints` 重算 → 原子写盘。指纹永远不被任何写路径手搓，门禁自洽 by construction。

## Plan（三轨拆分）

1. **050a 细纲编辑轨**：`apply_chapter_plan_item_edit` + `PUT /chapter-plan/<n>` + stage③ 内联编辑表单；B-M-2 指纹黑名单改白名单；D4 stale 灰显 + B3-hint 指纹 CTA。
2. **050b 正文/设定编辑轨**：`PUT /draft/<n>`（md+meta 同锁双写）+ `review-chapter` job + 章节详情「编辑」tab；KB/entity/relationship 编辑端点 + stage① 设定面板；D1 友好 409 + D7 label-for + C3c 控制字符闸。
3. **050c 收官轨**：README/Handoff 回填（4.5/4.6、命令表、U.14）；预算护栏（`NOVEL_DEFAULT_BUDGET_CNY` 默认 10 元上限 + preflight WARN + stage④ 预算输入）；真模型端到端 smoke。

## 关键设计决策

- **指纹唯一真源**（A 项核心）：`plot_planner._ITEM_FINGERPRINT_FIELDS` 白名单（8 个语义字段）同时驱动 `chapter_plan_item_fingerprint` / `plan_fingerprint` 内层过滤 / `EDITABLE_PLAN_ITEM_FIELDS`（白名单 − chapter_no）。canonical item 新旧哈希逐字节相等（测试钉死），未知未来字段不再能静默废掉全书指纹。
- **`refresh_start_point=False`**：编辑路径保留 plan **存储**的 `start_point_fingerprint`，不从 live 状态重算——否则会伪造「plan 在当前起点下生成」的新鲜度，骗过 `_plan_metadata_failures` 的起点变更检测（book_runner.py:586）。
- **编辑任一章 → 全部已写章 strict 过期**：writer 把全 plan 的 `plan_fingerprint` 写进每章 meta（writer.py:507），这是与「重新生成细纲」一致的**有意语义**（048c 已接受），不是 bug。端点返回 `written_chapters_invalidated`、前端确认弹窗、测试显式断言。**禁止**改成「只哈希未写章」（第二真源陷阱）。非编辑章的 item dict 字节不动 → item 级指纹幸存，恢复路径是重写/重评审受影响章，不必整本重 plan。
- **md+meta 同锁双写**（B1 核心）：`reviewer.review_target` 只信 `meta.draft_sha256`、从不重哈希文件——PUT draft 必须在同一 `workspace_reserved` 持有期内完成 md 写盘 + meta sha 重算 + `needs_human_review=True`，否则永久 `draft_hash_mismatch`。编辑后 `external_review_stale` 正确触发 = 「需重新评审」自解释信号。
- **KB 编辑保留 mtime 链回退**：保存 KB → 工作台提示重新生成大纲/细纲（048b 红队修正③本意），文案管理预期，不 hack mtime。
- **entity/relationship 白名单**：entity 可改 `name/aliases/tags/key_facts/description`；relationship 仅可改 active timeline entry 的 `state`（writer 唯一消费的文本）。`id/type/src_id/dst_id/relation_type/timeline.chapter_id/order/active` 全部不可改（剧透过滤与 advance 链依赖，entities.py:41-141）。relationship 无稳定 id，契约为 GET /entity-graph 当前数组下标 + reserved 锁防移位。
- **预算护栏**：web write-book 的 `budget_cny` 默认从 0.0（无上限）改为 `NOVEL_DEFAULT_BUDGET_CNY`（缺省 10.0 元）；显式传 0 仍=无上限（CLI 语义不变）；preflight 真模型态缺 env → WARN（mock 静默）；review-chapter 成本计入 estimate-cost 总账（v1 不单独强拦，记录在案）。

## L 级代号权威定义（原 4 路审查报告未落盘，本表为唯一解释）

| 代号 | 定义 | 落点 |
|---|---|---|
| D1 | fetch helpers 丢弃 status/payload，409 只显示 "workspace busy" | `_httpError` 挂 status+payload；409+running_job_id → 「工作区正被另一任务占用（job xx…）」 |
| D4 | plan 加载中 / mtime-stale 时 preview 无区分 | 「细纲加载中…」首帧占位；has_plan=false 但旧 plan 存在 → 灰显 +「细纲已过期」+ 编辑按钮禁用 |
| D7 | 表单 `<label>` 无 for/id 关联 | workbench / 章节详情 / 全部 050 新表单补齐 |
| C3(c) | 文本 PUT 入口接受 C0/C1 控制字符 | `routes._contains_control_chars`（保留 \t\n\r），挂 outline/premise/chapter-plan/draft/kb/entity/relationship 全部入口 |
| B3-hint | write-book blocked 为 fingerprint 家族时无行动指引 | CTA_ACTIONS 加 `plan_fingerprint_stale`（jobActionKind 正则归一全家族）：「细纲已变更/过期」+ 重写/重生成指引 |

## 实施备注（暗礁实录）

- **JS bundle 换行陷阱**：`static.py` 的 JS 是非 raw Python 三引号字符串，JS 字符串字面量里的换行必须写 `"\\n"`（Python 转义后 JS 才看到 `\n`）；050b 初版 `renderEntityPanel` 误写 `"\n"` 被 Python 转成真实换行撕裂 bundle（"Invalid or unexpected token"，整页 JS 静默失效）。实机走查抓到，已修并与存量 `split("\\n")` 约定对齐。浏览器实机走查是这类错误的唯一防线——铁律「UI 改动必实机」再次自证。
- verify.sh 必须在 venv PATH 下跑（裸 `python3` 是 homebrew 3.13 无依赖）：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`。

## Acceptance Result

### mock 验收（050a+050b+050c 护栏）

- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **805 OK**（758 → 805，+47：plot_planner_edit 10 / web_plan_edit 11 / workbench_replan +2 / web_draft_edit 6+1 / web_kb_entity_edit 4 / budget_guard 10 / 其余为既有计数差）；`PATH=.venv/bin bash scripts/verify.sh` 全链 OK（805 测 + 9 步 mock pipeline）。
- 钉死的结构性断言：白名单 vs 旧黑名单哈希逐字节相等 + 未知字段免疫；编辑后 write-book 零 fingerprint 失败（mirror 048c）；编辑任一章 → `written_chapters_invalidated` + 已写章 plan 级过期但 item 级指纹幸存；`start_point_fingerprint` 保留不重算；编辑→重评审后 stale 家族消失、仅剩 mock 固有 `external_review_reject`；KB 保存触发 stage 回退；entity id 拒改 400；预算默认 10 元 / 显式 0 不被覆盖 / preflight WARN mock 静默。
- 浏览器实机（mock，ui050a）：stage③ 编辑表单（字段预填、动态增删行、保存）→ 指纹自洽 → write-book 仅 `retry_exhausted`；D4 过期灰显；章节详情编辑 tab「保存并重新评审」→ md/meta/review 三方 sha 一致；stage① KB 编辑器 + 实体多行 key_facts 编辑落盘；console 零报错。

### 真模型 smoke（用户授权 ≤15 元，2026-06-11）

专用 workspace `smoke050`（premise 一句话开书：旧书店店主收到亡友预言谋杀的信），模型 `openai/gpt-5.5-high`（中转站），server 带 `NOVEL_DEFAULT_BUDGET_CNY=10` 起跑。全链：

1. **preflight（真模型态）**：零 FATAL；新 `_check_budget_guard` WARN 在未设 env 时实机目击（设 env 后消失）。
2. **测 Key 矩阵**：`GET /api/diag/models` → `all_ok: true`（write ping 4669ms）。
3. **premise → prepare-greenfield → debate → plan-chapters(2 章)**：全部 succeeded（debate 36 calls 真模型约 50 分钟，无人值守 job + 轮询链路工作正常）。
4. **A 项真模型门禁证据**：`PUT /chapter-plan/1` 编辑标题 + 替换章末 key_event（plan_fingerprint `645fb02e→db1d1970` 由唯一真源重算）→ `write-book --chapters 1 --tier low --budget-cny 5` → **succeeded，verdict Approve**（4012 字），`first_blocked: None`（零指纹失败）；`meta.run_context.plan_fingerprint` == 编辑后指纹，且编辑新增的章末事件（门缝里的第二封信/钟面）确实进入正文 —— writer 消费的是编辑后的细纲。
5. **B 项真模型链路证据**：`PUT /draft/1` 追加段落（`review_stale: true` 如期）→ `review-chapter` job succeeded → `strict_failures` 仅 `["external_review_reject"]`（真模型评审对编辑后文本的真实判断）——`external_review_stale` / `draft_hash_mismatch` 全部消失，md/meta/review **三方 sha 一致**，review 的 `run_context` 携带编辑后 plan_fingerprint。
6. **成本留痕**：74 LLM calls，prompt 570,654 + response 207,528 tokens，估算 **¥2.75**（项目单价表口径，预算 15 元，实耗 18%）；write-book 段受 `budget_cny=5` 上限保护，未触发 `budget_exceeded`（一章成本远低于上限，路径由 test_budget_guard + 既有 `BudgetExceeded` 测试覆盖）。
7. **清理**：smoke050 → `workspaces/_trash/smoke050_iter050_smoke_20260611`；真模型 server 停机。

## 不在本轮范围

- premise 扩写质量增强（#4，顺延 051+）。
- Aeloon 集成进一步打磨——视实机反馈另定。
- review-chapter 独立预算强拦（v1 仅计入总账）。
- KB 保存 stage 回退的交互软化（实机反馈刺眼再议，不 hack mtime）。

## Notes

- 验收命令用 `.venv/bin/python`。
- 三轨提交：050a `f896f2f`、050b `d22a3af`、050c（本提交）。
