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

## Acceptance Result（mock 段 2026-06-12 回填；真模型段进行中）

### mock 验收 ✅

- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` → **907 OK**（877 → 907，净 +30：驱动器 28 + smoke_scripts 2，零回归）；`PATH=.venv/bin bash scripts/verify.sh` 全链 exit 0。
- 钉死的断言（全部落地，tests/test_book_driver.py）：
  - 断点续跑 E2E（mock 真管道）：start → `--pause-after-segment 1`（ch1 Approve）→ `WRITER_FORCE_FAIL=1` resume → ch1 `skipped_approved` 且段成本 0.0 且 draft_sha256 不变（零重写三重证据）→ 清除注入 resume → succeeded；
  - 末行 JSON 解析抗噪音（噪音行前后夹击、非 dict JSON、损坏 JSON 全跳过）；
  - 段切分/终态映射（exit 4 → blocked 停人审不带 --force / exit 3 → budget_exceeded 透传 / 超时 SIGTERM → paused）；
  - 预算双层：驱动器级总账段前强拦（无任何 write-book 调用）+ 剩余额度传段内 `--budget-cny`；
  - `--on-blocked force-once` 显式逃生门（第二次调用才带 --force，仅一次）；
  - 双驱动器互斥（pid 存活 → exit 2）、真模型确认闸（非 mock 无 --confirm-real-run → exit 64）、resume workspace 错配拒绝；
  - 编排层 crash 落 `failed` 终态（不留 running 假象）；pid 消失 + 终态未落 → status 显示 `lost`；
  - F7 翻转（tests/test_writer.py）：覆写文案不存在 + 基础指令仍在 + iter013 ending_block 保留 + **本章计划块不再随 previous_chapter_ending 变化**（逐字节钉死）。
- **设计发现（mock 行为考古）**：mock `_mock_text` 的 write 任务固定返回 ~60 字稿，确定性 linter `short_chapter_length`（<2500 error）必拦 → mock write-book 历史上必 Reject（暗礁 5 "两套历史行为"的根源）。052a 新增 `MOCK_WRITER_CHARS` mock-only 钩子（iter019 `WRITER_FORCE_FAIL` 同款 opt-in 模式，缺省逐字节不变），E2E 由此走通 approve 路径。
- **暗礁实录复现**：drive_book.sh 首版忘了 venv PATH（050/051 暗礁原样复现），当轮直修为脚本内自带 `.venv/bin/python3` 优先解析。

### 铁律⑨ 对抗审查 ✅（双视角并行，2026-06-12）

- 视角 A（驱动器进程管理/断点续跑正确性）：其报告的 **H-1（resume 后 segments 跨 attempt 混合）经复核不成立**——`_run_steps` 每 attempt 开头 `state["segments"] = []` 重建，且 stub 测试断言 resume 后 `segments[0]` 为 `skipped_approved`（若混合应为旧 attempt 的 `written`）已实证；按 051 视角 B 同款惯例记录复核结论。M×2 当轮直修：A-M1 `_spent_cny` 吞异常加 stderr 留痕（保守低估仍成立，但失效要可见）；A-M2 detach 孙进程 stdio 重定向失败显式 `os._exit(1)`。A-M3 测试补强：segments 不跨 attempt 混合的显式断言。信号竞态/子进程组杀法/预算跨 attempt 总账/JSON 解析均查证安全。
- 视角 B（预算安全/真模型成本控制）：12 项必查全通过——env 组合矩阵无"驱动器以为 mock、子进程烧真钱"的组合（config 的 mock 短路优先级保证）；预算失效模式保守（低估→闸更宽不会多扣）；`MOCK_WRITER_CHARS` 仅 `is_mock` 路径可达、877 存量测试零影响；F7 删除单点、指纹链完整；step log 无密钥泄漏面。直修 B-M1（确认闸显式 bool()）+ B-L1（钩子 clamp 1e6 防 OOM）。

### 真模型段一：longzu 15 章实跑 → ch1 质量闸 blocked（2026-06-12，有效产出）

- 用户拍板：**15 章 / ¥20 上限 / 保 gpt-5.5-high**（换快模型会破坏 F7 对照与 051 基线可比性的分析获采纳，先 15 章后可 resume 续 30 的方案获选）。
- 启动实录：detach 后 `ppid=1` ✓；preflight 零 FATAL；ensure-plan `--force --require-start-point` 重 plan 10 章（旧 3 章 plan 归档 `pre_iter052_20260612_162921`）；起点 `longzu_3_3_ch024`。
- **运行结果**：驱动器无人值守稳定运行 2 小时（16:44–18:44）零进程事故，ch1 经 3 个重试周期（约 9 稿、2 次 stale 归档）全被评审团打回 → `retry_exhausted` → **按设计 blocked 停人审、未自动 --force**。总耗 ¥6.40 / ¥20（92 calls）。
- **拒因（高质量质量闸实证）**：panel 轨迹 5.68→5.84→6.02→6.16（横盘），文笔轴稳定 7–8 分，block 级拒因全部集中 fidelity 轴：① 时间线前置（把起点处尚未展开的 3E 考试当既成事实调用）；② 未来信息泄露（"路鸣泽四分之一生命交易"——起点处只有"愿意交换么"悬念）；③ "日本支部心神战机黑箱预案"等设定 KB 零铺垫。手工事实规则（gf_longzu_014/015）逐稿精准命中。
- **根因（事后取证修正版，铁证实录）**：初判归因"写手预训练记忆泄露"**不完整**。真正主因是**陈旧中间产物污染重规划**：`outputs/debate/outline.md`（2026-05-30 11:33 生成，《龙族一至四之后》**结局方案**大纲——"零已进入关东基地机库……东京上空赫尔佐格以新生白王之姿"；关键词统计：心神×19、赫尔佐格×15、零×14、东京×9 vs 考试×1、3E×1）诞生于"四部曲结局后续写"旧玩法时代；iter027 把起点改到第 3 卷 3E 线时隔离了错误草稿与 anchor（`_iter027_wrong_start_quarantine` / `_iter027_wrong_anchor_quarantine`），**唯独 outline.md 漏在原位**。052 清场时为省 debate 成本（驱动器"outline 存在即跳过辩论"的省钱设计）有意保留了它 → ensure-plan `--force` 重规划时 planner 把结局向大纲当剧情方向 → **章纲整体跳线**（实证：重规划章纲 ch1「黑色机库里的倒计时」/ ch2「没有驾照的试飞员」/ ch3「东京上空的黑色折纸」，写手写"心神黑箱预案"是按图施工而非自创）→ 写手 9 稿全部死在按错误图纸施工。评审从第一稿就指出"时间线错位"——它在说**图纸错了**，不是施工差了。预训练泄露（路鸣泽交易不在章纲里）仍存在但降级为次要噪音。
- **修正后的结论**：① 归因一半是清场失误（保留 outline 没做时间线核对）、一半是系统缺口——**F6 校验 plan↔起点指纹，但 outline/decisions 等 debate 产物没有任何起点一致性闸**（LLM 中间产物不是"原著资料"，start_safe_knowledge 管不到它）；② 流程问题比记忆问题好治得多，且"干净大纲下龙族能否过闸"**未被本次证伪**（2026-06-05 起点修复后人工监督规划的「听力考试里的哥哥」章纲曾 7.5 压线 Approve）；③ 驱动器与评审团全程无辜且立功。**iter053 立项修正为：① outline/decisions 中间产物的起点一致性校验（主）；② 写手反剧透硬约束（辅）**。
- **F6 验证双路径完成** ✅：正路径——整个实跑（plan + 9 稿写作 + readiness）全程零 `start_chapter_id_*` / `start_point_fingerprint_*` 失败；负路径（零成本实录）——`set-start-point longzu_3_3_ch020` → readiness 报 `chapter_plan:start_chapter_id_mismatch` + `chapter_plan:start_point_fingerprint_mismatch` → 恢复 ch024 → start 相关 blockers 清零。
- 用户拍板（blocked 后）：longzu 止损，canon 锚定转 iter053；驱动器剩余验收换 premise 书载体（方案 B+A）。

### 真模型段二：shudian052 premise 书实跑 ✅（2026-06-12 收官，7/7 Approve）

- 载体：smoke051 同款种子「旧书店店主收到亡友的信，预言七天后被谋杀」+ 051a 扩写路径（expand_premise → prepare-greenfield 六步，进程内复刻 wizard 流），workspace `shudian052`。
- 跑法：`drive_book.sh --book shudian052 start --chapters 12 --segment-size 4 --replan-every 4 --plan-target 8 --budget-cny 12 --tier mid --allow-missing-start-point --pause-after-segment 1 --detach`；debate 由驱动器执行（44 calls ~¥2.4——真模型 debate step 覆盖，longzu 段跳过了它）。
- **节拍实录**：seg1（ch1–4，F7 基线工作树）→ 22:04 `paused_after_segment` 按设计触发 ✓ → 22:09 **计划外 resume**（用户终端发起 `resume --detach --confirm-real-run`；段 1 四章 `skipped_approved` 零成本重走——意外多收一次"暂停→恢复"实证，但跳过了 agent 的 F7 切换步）→ 22:38 计划内**中断恢复演练**补位执行：`stop`（终态 stopped、子进程组零残留）→ 工作树切 F7 删除版（`git checkout main -- src/writer.py`）→ 途中无确认闸的 resume 被 **exit 64 当场拒绝（确认闸实弹验证 ✓）** → `resume --detach`（attempt 3、`ppid=1` ✓）→ **账本 206 行 → 206 行，零重复花费 ✓** → seg2 跑至 ch7 过审，按用户拍板「ch7 跑完即收官」由监视器自动 `stop`。
- **结果**：7/7 章 Approve，panel 8.04 / 8.40 / 8.30 / 8.50 / 8.72 / 8.36 / 8.36；成本 **¥11.10 / ¥12**。与 longzu 构成单变量对照（同管道同评审同阈值：自创书 8.0+ 一次过 vs 续写书 5.7–6.2 全灭），坐实段一失败归因。
- **F7 段间对照定版**：基线（ch1–4，F7 在）panel 均值 **8.31** vs 删除版（ch5–7，F7 拆）**8.48**；开场衔接敏感轴（主角本位）7/7 全 Approve；全程零「时间线回跳/重述已交代内容」类拒因——**回滚条件未触发，F7 拆除坐实（89eaa84 保留，不 revert）**。
- **timeline 证据包**（D 轨搭车）：7 份 advance proposal 文件、20+ 条提案（置信度 0.91–0.98），**几乎全部被 `relationship_not_found` 跳过（76 条审计日志，051b F5 产物首次在长程现形）**——推进机制只认实体图既有关系边，greenfield 实体图天生边稀疏 → premise 书实体时间线全程未推进，一致性全靠滚动摘要扛。「高置信提案允许动态建边」应为 timeline schema 升级立项的核心论据。
- 顺带观察：①重试主因是**票数闸边界拒**（ch3–7 首稿 panel 全部 ≥7.94 过分数线、但 2/5 票被打回），首过率 2/7——tier=mid 的 4/5 票对 premise 书可能偏严，每次边界重试 ≈ ¥0.6，可作后续调阈值输入；②本次扩写稿 6 字段中 genre_tone/world_notes/central_conflict 为空（schema 无非空校验，051 改进点），风格定调由 personas 的 `style_short_descriptor` 顶住。

### 成功指标对照（原 30 章 longzu 口径，载体经用户两次拍板变更后如实核对）

| 指标（原口径） | 实际 | 判定 |
|---|---|---|
| 30/30 章 Approve | longzu 0/15（质量闸 blocked，有效产出）；shudian052 **7/7**（用户拍板 ch7 止） | ✓（载体/范围变更经拍板） |
| 首次通过率 > 80% | shudian052 2/7（边界拒全为票数闸，panel 均 ≥7.94） | ⚠️ 如实记录，转阈值观察 |
| panel 均值 > 8.0 | **8.38**（7 章） | ✓ |
| fingerprint 家族失败 = 0 | 两跑全程 **0** | ✓（F6 正路径） |
| 总成本 ≤ 预算 | longzu ¥6.40/20 + shudian ¥11.10/12 + prep ≈ **¥18.1**，收在 ¥20 信封 | ✓ |
| ≥1 次中断恢复零重复花费 | stop→切码→resume，账本 206→206 行 | ✓ |
| 无人值守存活 + ppid=1 | longzu 2h + shudian052 4.7h，双跑 ppid=1，零进程事故 | ✓ |

## 不在本轮范围

- 50–100 章 capstone 独立立项——顺延 iter053+，待本轮驱动器验证后再上量级。
- premise 扩写多轮自评/迭代精修——051 顺延口径不变。
- Aeloon 反馈集成——等实机反馈输入，无输入即无事可做。
- KB stage 回退交互软化——「刺眼」仍是未经实机证实的假设。
- entity timeline schema 升级——五处联动大改，本轮仅搭车收实测证据（见 052b）。

## Notes

- 本档**已收官**（2026-06-12 单日完成：mock 段 907 OK + 真模型双载体实跑）。三轨全兑现：052a 驱动器 step 全图真模型逐项点亮（preflight/debate/ensure-plan/readiness/分段写作/pause/stop-resume/blocked/确认闸/预算账）；052b F6 双路径验证 + F7 拆除经段间对照坐实；052c 双载体实跑（longzu 验证「出事停得对」、shudian052 验证「顺利跑得完」）。
- **longzu 失败根因链（实测考古，iter053 立项核心输入）**：直接根因 = **陈旧中间产物污染重 plan**——5/30 的「四部曲结局后」debate outline 在清场时被保留（驱动器"outline 存在即跳过 debate"的省钱设计反噬），ensure-plan `--force` 重 plan 时被它带到错误时间线（对照：6/5 起点修复后的旧 plan「听力考试」贴起点可过 7.5，今日「机库倒计时」plan 必死）；深层根因 = 写手**预训练记忆泄露**（"路鸣泽四分之一生命交易"不在 plan 里，是写手自己掏的；`start_safe_knowledge` 管 KB 注入、管不住权重记忆）。评审团（含 gf_longzu_014/015 手工反剧透规则）逐稿精准命中两类问题，是全程表现最好的组件。
- **iter053 候选立项**（按优先级）：① **中间产物起点一致性校验**——outline/decisions 无章节号、不走起点过滤，F6 只管 plan↔start 指纹；建议 plan 前对 outline 做时效/起点一致性 gate（或 ensure-plan 缺 plan 时强制重 debate）；② **canon 锚定增强**——写手 prompt 硬约束「KB 之外的原著知识一律当不存在」+ 评审 block 级拒因结构化回灌重写 prompt（当前笼统反馈循环对剧透问题无效：九稿分数横盘 5.68→6.16）；③ **timeline 动态建边**——高置信 advance 提案 `relationship_not_found` 时允许建边（本轮 76 条跳过实证）；④ 30–100 章 capstone（驱动器已就绪，待 ①② 落地后用干净 plan 重战 longzu）；⑤ 票数闸阈值观察（premise 书边界拒成本）。
- **暗礁实录（本轮新增）**：① 实跑期间**外部人工操作与 agent 节拍存在竞态**——22:09 计划外 resume 跳过了 F7 切换步（驱动器无"操作者锁"，SOP 纪律：实跑期间人工 stop/resume 前先与值守方通气）；② drive_book.sh 首版忘 venv PATH（050/051 暗礁三度复现，已改为脚本内自带解析）；③ zsh 不做未引号变量词分割（`$ARGS` 需 `${=ARGS}` 或显式写开）；④ 扩写稿 schema 无非空校验，真模型可返回空字段。
- 行号引用已于起草日核对（F7/F6/skipped_approved/done_keys 等七处），行号会漂移、以符号名为准。
- 铁律⑤：收官只 commit 不 push。
