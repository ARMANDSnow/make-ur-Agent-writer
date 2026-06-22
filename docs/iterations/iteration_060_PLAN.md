# Iteration 060 — P2 收官 + Codex 复审补漏

> 承接 iter059「前端用户路径 P1 修复（坏 JSON 与数据完整性）」收官（canonical 1158 tests OK）。
> 来源：`docs/FRONTEND_BUG_AUDIT_2026-06.md` §4 划定的 **iter060 · P2 段（并发与体验）** 4 条
> （#7/#11/#14/#12）+ 一轮 **Codex 复审补漏（A–F）**——补 iter058/059 finite 守卫与坏-JSON
> 降级未覆盖的对称入口。**审计 16 条至此全部清零 open。** 沿用 iter058/059 铁律：复用已验证
> 护栏（`workspace_reserved` / `write_json` 原子写 / `read_json_optional` / `math.isfinite`）、
> 零新机制、默认路径 byte-identical、确定性单测兜底、按风险递增分 commit、全程不烧钱。

## Context

P2 的共同主线是**并发安全与可中断性**：写端点缺 `workspace_reserved` 互斥（reserved 期间仍穿透
写入绕过 409）、临时样本走固定路径（两并发互相覆盖）、写盘非原子（读-改-写有竞争窗口）、长步骤
内无协作式取消检查点（取消只在 step 边界生效）。

Codex 复审则发现 iter058/059 的护栏存在**对称入口漏网**：iter058 #6b 只给 `/run` 校验了
`budget_cny`/`min_confidence` 的有限性、iter059 #6a 只给 write-book/plan-chapters 的整数参数
设了上限——但 `/readiness` 的整数入口、其它 step 的 `timeout_minutes`、以及 web 读面与
`book_runner` 残余的裸 `read_json` 都还在原始 buggy 状态。同一类 bug 的不同入口，本轮一次收齐。

核验过的根因：
- `api_workspace_readiness`（`routes.py`）的 `chapters`/`resume_from`/`replan_every` 经
  `_parse_int` 裸 `int()` 无上限 → `chapters=999999999` 流入 `book_runner` 的
  `list(range(...))` 物化近 10 亿元素（write-book 入口 iter059 已 clamp 到 2000/10000/2000，
  readiness 这个**对称入口**漏了）。
- 只有 write-book/plan-chapters 校验 `timeout_minutes` 参数；其它 step 的 `timeout=NaN/inf`
  穿到 `_timeout_deadline`（`jobs.py`）因 IEEE-754（`nan<=0` 为 False）产出 `nan` deadline，
  `monotonic()>nan` 恒 False → **超时永不触发**（iter058 #6b 的同类 bug，换了个入口）。
- web 读面（manifest / 草稿详情 / 草稿列表 / entity·relationship PUT graph）与 `book_runner`
  5 处残余仍用裸 `read_json` → 坏文件抛 `JSONDecodeError`（iter059 R6 主动 scope 外的残余）。
- 4 个 P2 写端点/步骤的并发与取消缺陷（见下表）。

## P2 4 条 + Codex 复审 A–F 修复（按 commit 顺序：低→高风险）

| # | 组 | 根因 | 修复 |
|---|---|---|---|
| Codex-A | /readiness 整数上限 | `api_workspace_readiness` 经 `_parse_int` 裸 `int()` 无上限 → `chapters=999999999` 流入 `book_runner` `list(range())` 物化近 10 亿元素 | 进入 handler 后 clamp `chapters`/`resume_from`/`replan_every` 到 write-book 同上限（2000/10000/2000），仿 `api_workspace_logs_tail` 的 handler 内 clamp |
| Codex-B | timeout 有限性（双层） | 仅 write-book/plan-chapters 校验 `timeout_minutes`；其它 step 的 `NaN/inf` 穿到 `_timeout_deadline` 产 `nan` deadline → `monotonic()>nan` 恒 False → 永不超时 | ① `_validated_run_params` 对**所有** step 用 `_float_param` 校验 `timeout_minutes`（NaN/inf/负→400）；② `_timeout_deadline` 加 `math.isfinite` 兜底（defense-in-depth） |
| Codex-C/D/E | web 读面坏 JSON | manifest(543)/草稿详情(1617/1620/1621)/草稿列表(1642/1655/1656)/entity·relationship PUT graph(1323/1398) 裸 `read_json` → 坏文件 `JSONDecodeError` → server.py 兜底返 **500 击穿读面** | 裸 `read_json`→`read_json_optional`；PUT 两处坏 graph 降级 `{}` 后命中既有 `isinstance` 守卫返回 404『run prepare first』、在 `write_json` 前 return，**不覆盖坏文件** |
| Codex-F | book_runner 残余 | 5 处裸 `read_json`（728/741/790/791/858）：790/791 经 try 外路径冒泡出 `run_write_book` 击穿 resume，858 在异常善后中二次抛错顶替原始快照（iter059 R6 主动 scope 外的残余） | 5 处→`read_json_optional`；`read_json` 至此 `book_runner` **全无裸读**，清理未用 import |
| #7 | 起点保存 reservation | `api_workspace_set_start_point` 裸 `use_workspace`，reserved（write-book auto_advance 持锁）时仍穿过写入绕过 409 互斥 | 写块包 `jobs.workspace_reserved` + `use_workspace`（照搬 `draft_save` 范式），`workspace_busy`→409 |
| #11 | writer-style 唯一样本 | 样本固定落 `.writer_style_sample.tmp` 且写在 `start_job` 抢锁前 → 两并发 extract 互相覆盖样本 | 路由改每请求唯一 uuid 路径 + `write_text_atomic` + `sample_path` 入 job params；handler 优先读 params 路径（回落固定名）并提取后删；job 起不来时清理暂存样本 |
| #14 | drama 写端点原子化+reservation | `api_drama_plan`/`api_drama_setup_save` 裸 `write_text`（非原子）+无 reservation；setup_save 读-改-写有竞争窗口可被并发 `/drama/plan` 冲掉 | 两端点写块包 `workspace_reserved` + 改 `write_json`（原子，同 `ensure_ascii=False`/`indent=2`），setup_save 整个 R-M-W 进 reservation；`workspace_busy`→409 |
| #12 | debate 协作式取消 checkpoint | debate 是唯一无取消粒度的 step（`_step_debate` 没传 `progress_cb`，`run_debate` 无该参数）→ 整个 debate（N agents×M rounds+投票，~52s/call）期间 `_check_cancelled` 一次不跑，取消只在 step 结束后生效 | **方案A**：`run_debate` 加可选 `progress_cb`，在每 agent LLM 调用前（try 之外）+ build_decisions/每选票/build_outline 前插检查点；`_step_debate` 传入。writer/book_runner 章内外已有 progress 检查点，无需改 |

## 关键设计决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| Codex-A clamp 位置 | **handler 内 clamp，不在 `_parse_int`** | readiness 是只读探测，clamp 后继续跑（非 400 拒绝），仿同文件 `api_workspace_logs_tail` 既有 clamp 范式；write-book 入口 iter059 已 clamp，本轮补对称入口 |
| Codex-B 为何双层 | **参数校验 + deadline 兜底两道** | 上层 `_validated_run_params` 对所有 step 用 `_float_param`（早拒 400）；下层 `_timeout_deadline` 加 `math.isfinite`（defense-in-depth，任何漏网的非有限 timeout 不再产 nan deadline 致永不超时） |
| Codex-C/D/E 修复理由（**核验校正**） | **「500 击穿」而非「泄露 JSONDecodeError 文案」** | Codex 原报告说"泄露 JSONDecodeError 文案"**不成立**：`server.py:60-73` 统一返 `{"error":"internal server error"}`，真异常只进 stderr。坏 JSON 实际后果是 `read_json` 抛错 → server.py 兜底返 **500 击穿读面**，故降级理由是"500 击穿"非"泄露文案" |
| PUT graph 降级落点 | **降级 `{}` → 命中既有 `isinstance` 守卫 → 404『run prepare first』** | `{}` 不是预期的 dict-with-entities 结构，命中既有守卫在 `write_json` 前 return 404，**绝不覆盖坏文件**（保留现场待人工修复） |
| Codex-F 790/791/858 优先级 | **必修**（非纯防御） | 790/791 经 try 外路径会冒泡出 `run_write_book` 击穿 resume；858 在异常善后路径中二次抛错会顶替原始快照（丢失真实失败原因） |
| #11 唯一路径 vs 同一 reservation | **唯一 uuid 路径 + 原子写** | 比"写样本+起 job 包进同一 reservation"更轻：每请求 uuid 天然无碰撞，`write_text_atomic` 防半写；job 起不来时清理暂存样本避免临时文件泄漏 |
| #14 原子写选型 | **复用既有 `write_json`** | 项目已有原子 `write_json`（同 `ensure_ascii=False`/`indent=2`），不新造原子写；setup_save 整个读-改-写进 reservation 闭死竞争窗口 |
| #12 方案 A vs 方案 B | **方案 A（协作式 checkpoint），方案 B 推迟 iter061** | 方案 A 零配置改动、确定性可测；方案 B（流式中断 + debate 开 stream）需碰 `llm_client`/stream 配置，触碰"真模型须超时重试驱动"红线，显式推迟 |
| #12 检查点插入位置 | **每 agent LLM 调用前（try 之外）** | 若放 try 内，`JobCancelled` 会被 `except Exception` 吞掉；放 try 之外才能真正抛出中断 |

## Acceptance / 验证

canonical **1158 → 1180 tests OK（+22）**，全确定性、mock-only、不烧钱：
`.venv/bin/python -m unittest discover -s tests` 全绿。

分项新增：
- Codex-A：+2（`tests/test_int_finite_guard.py`）——readiness `chapters=999999999` 被 clamp。
- Codex-B：+3（`tests/test_float_finite_guard.py`）——非 write-book step 的 `timeout=NaN/inf/负`
  →400；`_timeout_deadline` 对非有限输入产有限/None deadline。
- Codex-C/D/E：+5（`tests/test_bad_json_blockers.py`）——manifest/草稿详情/草稿列表坏 JSON 不再
  500 击穿；PUT graph 坏文件降级 404『run prepare first』且不覆盖坏文件。
- Codex-F：+3（`tests/test_bad_json_blockers.py`）——book_runner 5 处坏 JSON 降级，resume 不
  击穿、异常善后快照保真。
- #7：+2（`tests/test_iter060_p2.py`）——reserved 时 set_start_point→409。
- #11：+3（`tests/test_web_writer_style.py`）——两并发样本路径互不覆盖、提取后删、job 起不来清理。
- #14：+2（`tests/test_web_routes_post.py`）——reserved 时 drama plan/setup_save→409；setup_save
  R-M-W 原子。
- #12：+2（`tests/test_iter060_p2.py`）——debate 协作式取消在 agent 调用前生效。

默认路径未变验证：`read_json_optional` 对合法/缺失文件与 `read_json` 返回一致（仅坏分支不同）；
clamp 上限远高于真实值（合法输入不受影响）；`workspace_reserved` 仅在并发持锁时改变行为；
`write_json` 与原 `write_text` 对合法数据同字节（`ensure_ascii=False`/`indent=2`）。

## 暗礁与教训

- **R1 Codex「泄露文案」核验校正**：Codex C/D/E 原报告称坏 JSON 会"泄露 `JSONDecodeError`
  文案给用户"——**逐行核验不成立**：`server.py:60-73` 对任何未捕获异常统一返
  `{"error":"internal server error"}`，原始异常串只进 stderr。真实后果是 `read_json` 抛错被
  server.py 兜底成 **HTTP 500 击穿读面**。故修复理由更正为"500 击穿"而非"泄露文案"，文档据实表述。
- **R2 #11 唯一路径需在 job 起不来时清理**：改 per-request uuid 样本路径后，若 `start_job`
  抢锁失败（并发败者），暂存样本不会被 job handler 消费删除 → **临时文件泄漏**。路由层在 job
  起不来的分支显式清理暂存样本，避免 workspace 残留垃圾。
- **R3 #14 复用既有 `write_json` 而非新造原子写**：项目早有原子 `write_json`（写 tmp +
  `os.replace` rename，`ensure_ascii=False`/`indent=2`），drama 两端点直接换用即得原子性，零新原语；
  setup_save 的整个读-改-写包进 reservation 才闭死并发 `/drama/plan` 冲掉的竞争窗口。
- **R4 writer/book_runner 已有取消粒度、#12 只需补 debate**：审计 #12 笼统说"长步骤无取消
  检查点"，但逐步核验——writer 章内（rewrite loop）、book_runner 章间（chapter loop）已有
  `progress`/`_check_cancelled` 检查点；**唯一缺口是 debate**（`_step_debate` 没传 `progress_cb`、
  `run_debate` 无该参数）。故本轮只给 debate 补检查点，不动 writer/book_runner，scope 精准。
- **R5 Codex-B 双层防御**：参数层早拒（`_validated_run_params` 对所有 step 校验）本可独立修复，
  但 `_timeout_deadline` 再加 `math.isfinite` 兜底——任何未来漏网的非有限 timeout 不再产 nan
  deadline 致永不超时，对齐 iter058 #6b「`jobs._float_param` defense-in-depth」范式。
- **R6 Codex-F 收口 book_runner 裸读**：iter059 R6 曾主动把 book_runner 5 处裸 `read_json`
  （728/741/790/791/858）划出 P1 scope 避免 creep；本轮 Codex 复审确认 790/791 击穿 resume、
  858 顶替善后快照属真 bug，一并收口——`read_json` 至此 `book_runner` 全无裸读。

## 不在本轮范围（iter061 候选）

- **#12 方案 B**：流式中断 + debate 开 `stream`（碰 `llm_client`/stream 配置）——触碰
  「真模型须超时重试驱动」红线，**显式推迟 iter061**（需真模型验证流式中断不破坏 SSE read 超时）。
- #4/#1 真模型复跑坐实端到端（`chapter_plan_invalid` / `budget_exceeded`，前几轮 mock 确定性为准）。
- 审计 16 条已全部清零 open；后续为真模型验证与产品打磨，非 bugfix。

## 关键文件

**修改**：`src/web/routes.py`（Codex-A readiness clamp + Codex-C/D/E manifest/草稿/PUT graph
`read_json_optional` + #7 set_start_point reservation + #11 writer-style uuid 样本 + #14 drama
原子写+reservation）· `src/web/jobs.py`（Codex-B `_validated_run_params` timeout 校验 +
`_timeout_deadline` `math.isfinite` 兜底 + #11 handler 读 params 样本路径 + #12 `_step_debate`
传 `progress_cb`）· `src/book_runner.py`（Codex-F 5 处裸读→`read_json_optional` + 清理未用
import）· `src/debater.py`（#12 `run_debate` 加可选 `progress_cb` + 各检查点）
**新增测试**：`tests/test_iter060_p2.py`（#7/#12）（+ 扩 `tests/test_int_finite_guard.py`(Codex-A)/
`tests/test_float_finite_guard.py`(Codex-B)/`tests/test_bad_json_blockers.py`(Codex-C/D/E/F)/
`tests/test_web_writer_style.py`(#11)/`tests/test_web_routes_post.py`(#14)）
**不改**：`src/utils.py`（`read_json`/`read_json_optional` 共享原语，仅作锚点）·
`src/llm_client.py`（#12 方案 B 推迟，不碰 stream 配置）· `src/writer.py` / `book_runner` 章循环
（已有取消粒度，#12 无需改）
