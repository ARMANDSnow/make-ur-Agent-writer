# Iteration 048d — iter048 对抗审查 H/M 级修复

> iter048 串行子迭代 4/4（验收补丁轮）。承接 048a/b/c 落地后按铁律⑨ 4 路并行 subagent 对抗审查发现的 1 个 H 阻塞 + 5 个 M 风险；不增加新功能，仅加固已有落地。

## Context

iter048 三个子迭代落地后，主对话 spawn 4 个并行对抗审查 subagent（视角 A 状态机/竞态、B 指纹链、C API 安全/key 泄漏、D 前端 JS/UX），共发现 1 H + 5 M + 多个 L 级风险。L 级 UX/a11y 推 049 摊销前端工作；H/M 集中本轮修。

| 等级 | 编号 | 问题 | 是否 iter048 引入 |
|---|---|---|---|
| **H 阻塞** | A5 | `write_text_atomic` tmp 文件名固定 `.tmp` → 并发写撞文件名 | 跨轮遗留，048 让触发面变宽（PUT outline + debater + compress 多线程写同名 tmp） |
| M | A2 | PUT outline 在 `workspace_busy` check 到 write 之间有 TOCTOU 窗口 | 048b 引入 |
| M | A4 | 多个 `_step_*` 缺前置产物 readiness 校验 → 产物缺失时 job `failed` 而非友好 `blocked` | 跨轮遗留，红队点名 `_step_debate` |
| M | B-M-1 | `test_workbench_replan` 只测 `*_mismatch`，未覆盖 `*_missing` 与 plan-vs-draft 链 | 048c 测试 gap |
| M | C2(a) | `LLMClient.ping()` 的 `err.replace(key, "***")` 只挡明文 key，未挡 Bearer / sk- 前缀编码形式 | 048a 引入 |

**用户拍板的两个 scope 决策**：C2(a) 用正则加固（保留排错信息）；A4 扫所有 prep step（一劳永逸，不止 debate）。

## Plan

1. **`src/state.py`** — A5：`write_text_atomic` 的 tmp 后缀从固定 `.tmp` 改为 `.tmp.{pid}.{tid}`，加 `os`/`threading` import。**附带改动**：`src/web/settings.py:159` 自写 `.tmp` 后缀同步加；`tests/test_web_settings.py` 两处 `.tmp` 断言改 glob 匹配 `.tmp*`。
2. **`src/web/routes.py`** — A2：`api_workspace_outline_save` 删除单点 `workspace_busy` 检查，写操作放进 `jobs.workspace_reserved` 上下文；捕 `RuntimeError("workspace_busy:<jid>")` 映射 409。范式照抄 [`api_workspace_trash`](src/web/routes.py:305)。
3. **`src/web/jobs.py`** — A4：新增 `_blocked(reason, error)` helper；给 6 个 prep step 加前置产物 readiness check：`split`(normalized_missing) / `extract`(manifest_missing) / `compress`(extractions_missing) / `bootstrap`(extractions_missing) / `apply-bootstrap`(proposal_missing) / `debate`(kb_missing)。统一返 `{"status":"blocked","blocked":[{"reason","error"}]}`。
4. **`src/llm_client.py`** — C2(a)：`LLMClient.ping()` 的 except 块叠加 `re.sub(r"Bearer\s+\S+", "Bearer ***", err)` 和 `re.sub(r"sk-[A-Za-z0-9_\-]{16,}", "sk-***", err)`，保留异常类型供排错（用户能区分 401/429）。加 `re` import。
5. **测试加固（10 个新测）**：
   - `test_workbench_replan.py` 补 3 测：`*_missing` 路径恢复 + plan-vs-draft mtime 链失效。
   - `test_web_jobs_dispatch.py` 补 6 测：6 个 prep step blocked 断言（含红队点名的 `kb_missing`）。
   - `test_premise_prepare_diag.py` 补 1 测：注入含 `Bearer sk-...` 的 litellm 异常 → `ping()` 返回的 error 中 token 被替换为 `Bearer ***`/`sk-***`。

## Acceptance

- `OPENAI_MODEL=mock` 下 `.venv/bin/python -m unittest discover -s tests` 全绿（基线 684 → **694**，+10）。
- `OPENAI_MODEL=mock python main.py preflight` → PREFLIGHT: ok, FATAL/WARN none。
- 浏览器实机：
  - A4：premise 开书后**跳过** prepare-greenfield 直接点 debate → job 终态 `blocked` 而非 `failed`，summary 含 `blocked` 键。
  - A2：debate job 跑中并发 PUT `/outline` → 409 + `running_job_id` 字段。
- 红队 H/M 全消化。

## Implementation Notes

- **A5 是跨轮基础设施 fix，不算 048 回归**：但 iter048 触发面变宽（PUT outline + 大量并发 step）让这个潜在竞态从"理论上可能"变成"workbench 用户随手能触发"。修在 048d 而非单独跨轮 commit 的理由：和 A2 同根（PUT outline 是最危险触发点），打包修+测一起更连贯。
- **A4 扫所有 prep step 的额外收益**：除红队点名的 `_step_debate`，`_step_split/extract/compress/bootstrap/apply-bootstrap` 都缺 readiness check。扫了之后产物链路顺手变成自解释的"用户点错了下一步会看到 reason: xxx_missing 而非 trace_id"。helper `_blocked()` 把模板从 4 行收到 1 行，未来加 step 可以照抄。
- **C2(a) 正则的边界选择**：`sk-[A-Za-z0-9_\-]{16,}` 用 16+ 避免误伤 `sk-test` 这类短测试 key 名。`Bearer\s+\S+` 用 `\S+` 而非更严格的字符集，因为 Authorization 头里 token 可能含 base64 padding `=` 等。**保留 `type(exc).__name__` 在前**：用户能从"AuthenticationError"/"RateLimitError" 区分 401 vs 429，符合用户拍板的"正则加固"而非"只回类型名"决策。
- **测试用 `_assert_blocked` helper** 统一 6 个 prep step blocked 模式：减少模板代码、未来加 step 一行测试可以加。
- **C2(a) 测试的关键设计**：注入的 leaking_msg 里的 token (`sk-leakedabcdef1234567890XYZ`) **故意不等于** client.config["api_key"]（设为 `totally-different-configured-key`），这样**只有正则层能 redact**——证明正则真起作用，不是被旧的明文 replace 兜了底。
- **iter048d 不再 spawn 二次对抗审查**：本轮本身就是上一轮审查的修复回应，回填测试 + 实机验证即是对原审查的证据答辩，避免无限镜厅。L 级建议（D7 a11y label-for / C3(c) 控制字符过滤等）推 049。

## Acceptance Result

- **测试**：`OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` = **694 OK**（基线 684 + 新增 10，零回归）。其中关键回归保护点：
  - `test_workbench_e2e` 7/7 OK（PUT outline 改 workspace_reserved 后 busy 409 测试仍工作）
  - `test_premise_prepare_diag` 14/14 OK（C2(a) 加固后原有 mock 短路测试不变）
  - 现有 step 测试（`test_web_jobs_dispatch` 等）OK（A4 加 readiness 后已有路径走"产物存在 → 不 blocked"分支不变）
- **preflight**：FATAL/WARN none。
- **浏览器实机**（CLAUDE.md 铁律）：
  - **A4**：premise→直点 debate → job final_status `blocked`，summary keys `["blocked","status"]`（非 failed/trace_id）。
  - **A2**：premise→prepare→直点 debate 启动后并发 PUT `/outline` → 409 `{"error":"workspace busy","running_job_id":"e3809b7d..."}`。
  - 实机 workspace `a2test`/`a4test` 已清理。
- **iter048d 不二次审查**（避免无限镜厅）；本轮的 10 测 + 实机验证就是对原 4 路审查的证据答辩。

## 文件变更汇总

- `src/state.py`（改）：`write_text_atomic` tmp 后缀 `.tmp.{pid}.{tid}`，加 os/threading import。
- `src/web/settings.py`（改）：同款 tmp 后缀加固，加 threading import。
- `src/web/routes.py`（改）：`api_workspace_outline_save` 用 `workspace_reserved` 闭锁，捕 RuntimeError 映射 409。
- `src/web/jobs.py`（改）：新增 `_blocked()` helper；6 个 prep step 加 readiness check。
- `src/llm_client.py`（改）：`ping()` redact 叠加 Bearer/sk- 正则，加 re import。
- `tests/test_web_settings.py`（改）：2 处 `.tmp` 断言改 glob 匹配。
- `tests/test_workbench_replan.py`（改）：补 3 个测试（missing fp / missing item fp / plan-vs-draft）。
- `tests/test_web_jobs_dispatch.py`（改）：补 6 个 prep step blocked 测试 + `_assert_blocked` helper。
- `tests/test_premise_prepare_diag.py`（改）：补 1 个 C2(a) redact 测试。

## 不在本轮范围

- L 级 UX/a11y：D7 `<label for>` 关联 / D1 友好 409 文案 / D4 stale plan loading 占位 / C3(c) 控制字符过滤 / B3 hint 提示 → 推 049（与正文/设定编辑一起做更划算，前端工作量摊销）。
- B-M-2 `chapter_plan_item_fingerprint` 黑名单改白名单 → 防御性重构推 049。
- 真模型端到端 smoke（铁律⑥需用户授权）。
- 不动 048a/b/c 已交付的功能契约。

## Notes

- **iter048 完整收官（含 048d）**：
  - 048a 后端骨架（674 OK） → 048b 前端工作台+大纲（681 OK）→ 048c 细纲+重生成（684 OK）→ 048d 对抗审查 H/M 修复（**694 OK**）
  - 红队原计划 7 条修正 + 4 路对抗审查 H/M 共 5 条全部兑现
- **iter049 接力**：
  1. L 级 UX/a11y 集中修（D1/D4/D7/C3(c)/B3-hint）
  2. 细纲结构化字段编辑（每章 7+ 字段 + 数组增删 + 范围校验）—— 048 的"全程可编辑"承诺最后一块
  3. 正文逐章深度编辑回写 + 重 review；设定（KB/entity_graph）编辑回写
  4. premise 扩写质量增强（短种子→高质量多章）
  5. 真模型端到端 smoke + 测 Key 成本护栏深化
  6. B-M-2 指纹排除字段黑名单改白名单（防御性）
- 046/047 README/Handoff 回填仍待办（沿 048a/b/c 接力点）。
- 验收命令需用 `.venv/bin/python`。
