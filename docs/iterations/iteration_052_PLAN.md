# Iteration 052 — 长程驱动器正式化 + F6/F7 清债（30 章 longzu 实跑为验证载体）

> 承接 iter051 收官顺延项与结构性暗礁。iter051 Notes 实录：真模型长流程（2 小时级）的驱动进程不能寄生在 agent 会话后台任务里——smoke051 因 context 回收与超时低估死过 2 次，临时 double-fork 解法未落盘进仓库；F7 开场补丁淘汰等待 F6 真模型验证；30 章 capstone 顺延至本轮。
>
> **拍板结论（用户，2026-06-12）**：① 本轮三轨 = **A 长程驱动器正式化（主轨）+ C F6 真模型验证/F7 淘汰（清债）+ 收官实跑**；② 30 章 longzu 实跑预算 **¥40（封顶 50）**，**不作为独立 capstone 立项**，而是 A 轨驱动器验证与 C 轨 F6 验证的共同载体；③ D 轨候选（Aeloon 反馈集成 / KB 回退交互软化 / entity timeline schema 升级）经实勘**三项全裁**，仅搭车收 timeline 实测证据；④ 50–100 章 capstone 独立立项顺延 iter053+。

## Context

smoke051 用 agent 会话后台任务驱动 2 小时级真模型流程，会话 context 压缩/重启会**静默回收进程组**（无信号无 traceback），实测死过 2 次：一次 context 回收、一次 debate 超时参数低估（gpt-5.5-high 单 call 1.5–3 分钟 × 36 calls ≈ 1 小时）。当时的临时解法是 Python double-fork + `os.setsid()` 脱离到 launchd（ppid=1），但该脚本是会话临时产物，未进仓库（全仓 grep `setsid|fork` 零命中）。项目侧的断点韧性其实已经达标——debate done_keys 逐条续跑（`src/debater.py:122`，iter015）、write-book 已批章跳过（`src/book_runner.py:137`，`skipped_approved`）、web_jobs 落盘（`src/web/jobs.py:97`）、预算三点校验——三次中断零数据损失、零重复花费。缺的不是幂等 gate，是**一个正式的、脱离会话生命周期的、能断点续跑可审计的驱动器**。

这恰好和两件顺延事项咬合：① 30 章 longzu 长程实跑（iter025+ 原计划，051 确认顺延本轮）没有驱动器就跑不完；② F6（起点一致性集中校验 `src/start_point.py:191::enforce_consistency`，051b 落地、mock 13 例钉死）需要真模型路径验证「落稳」，之后 F7（`src/writer.py:706-716` 的 opening_instruction 覆写创可贴，iter027 引入）才能淘汰——而 30 章实跑正是 F6 正路径验证与 F7 分段对照的天然载体。三件事合成一轮：**驱动器是工具，实跑是验证，清债搭车**。

## Plan（三轨拆分）

1. **052a 长程驱动器正式化**（主轨）
   - 新建 `src/book_driver.py`（核心编排逻辑，mock 可测）+ `scripts/drive_book.sh`（薄包装：with_proxy、venv PATH、真模型确认闸沿用 `CONFIRM_REAL_MODEL_SMOKE` 惯例，`tests/test_smoke_scripts.py` 同款断言）+ `main.py` 新增 `drive-book` 子命令（`start` / `status [--json]` / `resume` / `stop` / `report`）。
   - **进程模型：子进程编排公开 CLI**（`main.py --book X write-book ...`），非 in-process import `run_write_book`。step 级 wall-clock 超时（缺省 `--step-timeout-minutes 180`）：超时 SIGTERM 子进程组 → 记 timeout 事件 → 终态 `paused`，resume 续跑零重复花费。
   - **脱离方式**：`--detach` 时 Python double-fork + `os.setsid()`（ppid=1），stdio 重定向 `workspaces/<book>/logs/driver/driver_<ts>.log`，detach 路径包 `caffeinate -i` 防机器睡眠。
   - **状态文件**（`workspaces/<book>/logs/driver/`，在 workspaces gitignore 覆盖内）：`driver_state.json`（原子写复用 `utils.write_json`；**只存启动参数与审计字段，不存章节进度**）+ `driver_events.jsonl`（append-only：step 启停/退出码/结果摘要/中断恢复）+ `driver.pid`（pid+pgid，防双驱动器互斥）。
   - **step 图**：preflight（FATAL→blocked）→ ensure-plan（guard：`chapter_plan.json` 缺失 / `_plan_metadata_failures` 非空 / 长度 < plan-target 才跑 `plan-chapters --force --require-start-point`，防 resume 重花 planner 钱）→ 可选 debate（默认 `--skip-debate`，done_keys 天然幂等）→ `write_segment` × N（`--chapters <segment-size> --resume-from <盘面推导> --replan-every K --budget-cny <剩余额度> --tier <t>`）→ 每段末心跳 + 段报告（approve rate / panel_score 从 meta 聚合）+ `--pause-after-segment` 钩子（F7 中途换码用）。
   - **子进程结果消费**：退出码契约 `main.py:438-447`（blocked=4 / budget_exceeded=3 / failed=1）+ 末行 JSON（解析从尾部找第一个可解析行，钉死噪音测试）。exit 4 → 终态 `blocked` 停人审，**不自动 --force**；`--on-blocked force-once` 作显式逃生门（默认关）。exit 3 → 透传 `budget_exceeded`。
   - **预算双层**：驱动器级总账（启动记 `llm_calls.jsonl` 行偏移，每段前 `estimate_cost_since` 对照 `--budget-cny`）+ write-book 段内上限（传剩余额度）。
   - **与 web_jobs 绕开不复用**：jobs 是 server 进程内 daemon 线程，生命周期错配；驱动器不写 `web_jobs.jsonl`（那是 server 的账本），两者只共享底层幂等 gate。
   - mock 测试（新建 `tests/test_book_driver.py`，预估 +18~22 例）：状态机单测用 `--cmd-prefix` 注入 stub 子进程（段切分 / resume 跳过 / 终态映射 / 剩余预算 / 末行 JSON 解析含噪音）；断点续跑 E2E 走 mock 真管道（`OPENAI_MODEL=mock` + `WRITER_FORCE_FAIL=1` 让 ch2 失败 → blocked → 清注入 → resume → 断言 ch1 `skipped_approved` 零重写）；state 原子性；detach 的 fork/setsid 不进单测（实机验证），pid/信号路径 mock `os.kill` 覆盖；`tests/test_smoke_scripts.py` +2。

2. **052b 清债轨：F6 真模型验证 + F7 淘汰**
   - **F6 验证（零代码改动预期）**：
     - 正路径搭车 30 章实跑：plan-chapters 与每段 write-book readiness 都穿过 `enforce_consistency`，全程零 `start_chapter_id_*` / `start_point_fingerprint_*` 失败即正向证据。
     - 负路径（零 LLM 成本，本地计算）：实跑收官后临时 `set-start-point` 改起点 → `write-readiness` 必须报 `start_chapter_id_mismatch` + `start_point_fingerprint_mismatch` → 恢复原起点 → 回 ready；命令输出落档本文件。
   - **F7 淘汰（严格依赖 F6 正/负路径双通过）**：
     - F7 = `src/writer.py:706-716` 的 `opening_instruction` 覆写块（iter027 文档写的 :524 是旧行号，已漂移；**686-693 的 ending_block 是 iter013 产物，不可误删**）。
     - 步骤：① mock 段删除覆写块，`tests/test_writer.py` 钉 F7 文案的断言**显式翻转**（断言覆写块不存在、有 previous_chapter_ending 时 opening_instruction 仍为基础版），**独立 commit 作回滚单元**，并钉死「F7 删除后 prompt 其余部分逐字节不变」；② 真模型分段对照：段 1（ch1–5）保留 F7 跑基线 → `--pause-after-segment 1` → 落 F7 删除 commit → resume 跑 ch6–30（子进程模型天然加载新码）；③ 判定：ch6–15 中 ≥2 章因时间线回跳/重述已交代内容被 Reject，或开场衔接分轴（主角本位/伏笔猎人/关系一致性）显著低于段 1 → 触发回滚。
     - 回滚预案：`git revert <F7 commit>` → 受影响章 `write-book --force` 重写（预算余量已留）。
   - **D 轨搭车动作（零开发成本）**：30 章实跑天然产生 ~30 份 entity advance proposal + `proposal_skipped` 日志（051b F5 产物），收官时汇总 timeline 实际形态与 skip 原因分布，作为 entity timeline schema 未来立项的实测输入。

3. **052c 收官验证轨：30 章 longzu 实跑**
   - **第 0 步（零 LLM 成本）**：① 从回收站恢复 workspace `workspaces/_trash/longzu__20260606_020325/` → `workspaces/longzu/`（`src/web/trash.py:97::restore_trash_entry` 或等价；已确认当前无同名冲突）；② 清场：旧 ch1–3 草稿 + ch1 last_failure 残留 + `_iter027_wrong_start_quarantine` 隔离目录 + rolling_chapter_summary 归档到 `outputs/drafts/snapshots/pre_iter052_<ts>/`（否则 readiness 被 existing_output blocked）；③ 校验：preflight 零 FATAL、起点 `longzu_3_3_ch024` 在位、`.env` 确认 `OPENAI_STREAM=1`（iter027 Cloudflare 524 教训）、预算 env。
   - **跑法**（实跑前仍按铁律⑥确认时点）：
     ```bash
     python3 main.py --book longzu drive-book start \
       --chapters 30 --segment-size 5 --replan-every 5 \
       --plan-target 10 --skip-debate \
       --budget-cny 40 --tier mid \
       --pause-after-segment 1 --detach --confirm-real-run
     ```
     plan 策略：首 plan 10 章 + replan-every 5 滚动 append（readiness 只要求首窗口；append 模式保留已写章 plan 项）。debate 跳过：done_keys 续跑已被 smoke051 三次真模型中断验证，省 ~1hr + ¥1–2。成本测算：30 × ¥0.3–0.5 + replan planner calls + 重试余量 ≈ ¥20–32，上限 40（封顶 50 内）。
   - **中断恢复演练（A 轨核心验收，安排在段 2 中途）**：`drive-book stop` → 确认 state=stopped、`ps -g <pgid>` 无残留 → `resume --detach` → llm_calls 行数对账证明零重复花费（已批章 `skipped_approved`）；`ps -o ppid= -p <pid>` = 1 证明脱离；人为重启 agent 会话后进程存活。
   - 铁律⑧：README「项目阶段 SOP（实时状态）」表 + `docs/AGENT_HANDOFF.md` 末尾 Phase Status 同步。
   - 铁律⑨：收官前双视角只读对抗审查——视角 A（驱动器进程管理/断点续跑正确性）× 视角 B（预算安全/真模型成本控制），结论写进 Acceptance Result。

## 关键设计决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| 驱动器进程模型 | 子进程编排公开 CLI，非 in-process import | 崩溃隔离；公开 CLI 即生产契约（iter028/029 既定）；每段重新加载代码使 F7 中途换码可行；可实施 step 级超时杀进程组 |
| 脱离方式 | Python double-fork + `os.setsid()`（`--detach` 可选） | smoke051 实测唯一可靠；macOS 无 setsid 命令；nohup 不换 session 照死；launchd plist 安装/卸载/调试三重摩擦过重 |
| 与 web_jobs 关系 | 绕开，仅共享底层幂等 gate | jobs 是 server 内 daemon 线程，生命周期绑死 server；不写 web_jobs.jsonl 避免账本混淆 |
| 章节进度真源 | 永远从盘面 chapter_status 推导，state 文件只存参数/审计 | 防第二真源（与 050 指纹唯一真源同一哲学）；resume = 重读参数 + 逐段重算 next_unapproved |
| blocked 处理 | 默认停人审，不自动 --force | 自动 force 掩盖质量回退是反目标；`--on-blocked force-once` 显式 opt-in 逃生门 |
| 预算防线 | 驱动器总账（行偏移）+ write-book 段内上限双层 | 单层在段边界有结算滞后；双层封死 |
| F7 淘汰节拍 | 段 1 带补丁基线 → pause → 删 → 段 2+ 对照；独立 commit | 同一跑次内对照（同 plan 同起点）；revert 即原样回滚 |
| debate | 30 章实跑默认跳过，复用既有 outline | 续跑 gate 已被 smoke051 真模型验证三次；省时省钱聚焦主目标 |
| plan 策略 | 首 10 章 + replan-every 5 append | readiness 首窗口语义既有支持；滚动 plan 贴合 rolling 现实，顺带实测 replan 路径 |
| D 轨三项 | 全裁，仅搭车收 timeline 证据 | Aeloon 无新反馈输入=无事可做；「刺眼」未经实机证实；timeline schema 升级牵动剧透过滤/advance 链/编辑白名单/bootstrap schema 五处联动，绝不与 30 章实跑同轮 |

## 实施备注（暗礁预警）

- 驱动器 vs web server 同 workspace **无跨进程锁**（jobs 锁在 server 进程内）——SOP 纪律：实跑期间 web 只读不发 job；`driver.pid` 只防双驱动器。
- `setsid` 不防机器睡眠——`caffeinate -i` 必须进 drive_book.sh 的 detach 路径。
- write-book stdout 有 print 噪音、JSON 结果在末行——解析必须「从尾部找第一个可解析 JSON 行」，钉测试。
- replan append 失败后 resume 会重跑同窗口 planner call（多花一次 planner 钱但不损坏 plan，plot_planner 有重编号兜底）——ensure-plan guard 用 `_plan_metadata_failures` 判空才跳过。
- mock 下 write-book 走通 approve 的姿势有两套历史行为（严格 reject vs tier flow succeeded）——驱动器 E2E 测试照 `tests/test_book_runner_tier_flow.py` 既有配置，实施时先核。
- 旧 longzu 残留（ch1 last_failure、隔离目录）清场必须彻底，否则 readiness 被 existing_output blocked。
- 验收命令统一 `.venv/bin/python`；verify.sh 需 venv PATH（050/051 两轮实录）。
- 既有 `scripts/watchdog.sh`（llm_calls mtime 心跳，warn/abort 两档，iter027）可直接复用/集成，不重造心跳监控。

## Acceptance Result（待回填）

### mock 验收（门槛）

- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` 全绿（877 + 新增 ~22 ≈ 900）；`PATH=.venv/bin bash scripts/verify.sh` 全链 exit 0。
- 待钉死断言：驱动器断点续跑 E2E（ch2 失败 → resume → ch1 `skipped_approved` 零重写）；`driver_state.json` 原子性（中断点永远可解析）；末行 JSON 解析抗噪音；F7 删除后 prompt 其余部分逐字节不变；`tests/test_writer.py` F7 断言显式翻转。

### 真模型段（门槛，30 章 longzu 实跑）

- 30/30 章最终 Approve；首次通过率 > 80%；panel_score 均值 > 8.0；fingerprint 家族失败 = 0；总成本 ≤ ¥40。
- ≥1 次中断恢复演练：llm_calls 行数对账零重复花费 + `ppid=1` 脱离证据 + 会话重启后进程存活。
- F6 负路径四码实录（mismatch 两码出现 → 恢复 → ready）。
- F7 段间对照结论（段 1 基线 vs 段 2+ 删除后；回滚则记录 revert + 重写章号）。
- entity timeline 证据包：advance proposal 形态汇总 + `proposal_skipped` 原因分布。

### 铁律⑨ 对抗审查（待回填）

- 视角 A（驱动器进程管理/断点续跑正确性）：待审。
- 视角 B（预算安全/真模型成本控制）：待审。

## 不在本轮范围

- 50–100 章 capstone 独立立项——顺延 iter053+，待本轮驱动器验证后再上量级。
- premise 扩写多轮自评/迭代精修——051 顺延口径不变。
- Aeloon 反馈集成——等实机反馈输入，无输入即无事可做。
- KB stage 回退交互软化——「刺眼」仍是未经实机证实的假设。
- entity timeline schema 升级——五处联动大改，本轮仅搭车收实测证据（见 052b）。

## Notes

- 本档为计划稿（2026-06-12 起草，拍板项见篇首引言块），Acceptance 待实施后回填。
- 接力点：实施顺序建议 052a mock 段（驱动器 + 测试）→ 052b mock 段（F7 删除独立 commit，先不合入实跑分支语义，等 F6 验证）→ 052c 第 0 步清场 → 30 章实跑（段 1 含 F7 基线 → pause → F7 commit → 段 2+）→ F6 负路径 → 铁律⑧⑨收官。
- 行号引用已于起草日核对：`src/writer.py:706-716`（F7）、`src/start_point.py:191`（F6）、`src/book_runner.py:137`（skipped_approved）、`src/debater.py:122`（done_keys）、`src/web/jobs.py:97`（_persist_job）、`src/web/trash.py:97`（restore）、`main.py:438-447`（退出码）。实施时行号可能再漂移，以符号名为准。
- 铁律⑤：收官只 commit 不 push。
