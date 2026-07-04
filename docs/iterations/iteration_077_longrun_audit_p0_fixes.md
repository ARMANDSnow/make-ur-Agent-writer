# Iteration 077 - 长跑审查修复批：六方审查 P0 五项（capstone 前置硬门）

## Context

iter076 交付长跑可靠性硬化后，对「20+ 章真模型 capstone」做了一轮**六方并行只读审查**：6 个独立视角 subagent（断点续跑/状态持久化、无界增长/上下文膨胀、预算/超时/重试/心跳、错误路径/数据损坏、并发/信号/进程、配置一致性/CLI 边界）+ codex 独立报告交叉对照。共确认约 40 个独立问题（P0×5 / P1×8 组 / P2 若干），完整清单见本文件 Notes 与「不在本轮范围」。

核心结论：单次不中断的跑是稳的（原子写、预算总账、supervisor 决策表均通过审查）；**问题集中在三个交界处**——①恢复路径 × iter076 新特性、②续写模式 × 源书遗留数据、③配置 × 静默回落。其中一颗雷是**确定性**的：不修，capstone 到 ch16 必停。另有两个测试盲区被暴露：mock 提取的 foreshadowing 恒为空使伏笔闸门路径零覆盖；caveat resume 测试打桩 `_load_chapter_plan` 使 readiness 生产路径零覆盖——iter076「mock 25 章三关全过」对这批雷没有背书力。

本轮只修 P0 五项（capstone 硬门），P1/P2 顺延。capstone 实跑顺延至 iter078。

## Plan

- **P0-1 伏笔 TTL 闸门 ch16 确定性封死**（A2 独家，CONFIRMED）
  `src/foreshadowing.py:104-180` + `src/book_runner.py:794-816`：续写书 compress 播种源书伏笔为 `planted_chapter=0, ttl=12, must_resolve=True`，无自动 resolve 路径，expired 仍 block；`resume_from-1>12`（默认段划分即 ch16 段入口）全部变 blocker → exit 4 → supervisor 终态。
  → 修法：`planted_chapter=0` 的源书遗留项默认不进 must_resolve 闸门（或播种用起点相对章号），只对续写期间新种伏笔 fail-closed；mock extractor 补非空 foreshadowing fixture 使闸门路径可测。
- **P0-2 caveat×resume 双断点**（A1+A3+codex 三方交叉）
  断点 A：`check_write_readiness`（`src/book_runner.py:750-779`）不认 `caveat_approved` → caveat 章判 blocker；断点 B：`_mark_caveat_approved`（`src/book_runner.py:119-131`）不清理 `failure.json`，而 `chapter_status.py:102-108` 要求 `not failure` 才认 caveat。
  → 修法：readiness 逐章循环对 `caveat_approved` 按 approved 同等豁免；caveat 放行时归档 failure.json（或 chapter_status 在 meta.caveat_approved 时豁免 failure），三处判定口径统一；回归测试**不得打桩 plan**，直击生产路径。
- **P0-3 panel_block_policy 配置手滑静默回落 halt**（A6，沙箱实测）
  `src/book_runner.py:54-61`：非法枚举零告警回落 halt、`int(True)` 变 1；`caveat_continue + max_panel_rejections=0` 组合等效 halt；`_snapshot` 不回显生效策略、preflight 不校验。
  → 修法：解析失败 stderr WARN + 生效 policy 写进 snapshot 输出；preflight 加 agents.yaml panel_block_policy 合法性 + 矛盾组合检查（WARN 档）。
- **P0-4 孤儿 write-book 双写者**（A1+A3+codex 交叉；A5 补两条独立成孤路径）
  主路径：`cmd_resume`（`src/book_driver.py:964-1068`）不收割 `state["child_pid"]`（对照 cmd_stop:1155 有收割）；补充路径①：`_run_step` 中 `_save_state`/`_emit` 的 OSError 绕过 `_terminate_child`（`book_driver.py:346/364-365`，emit 先于杀）；补充路径②：SIGTERM 落在 Popen 前窗口，`_run_step` 不查 `_STOP_REQUESTED`（`book_driver.py:326-343`）。
  → 修法：cmd_resume（及 run_driver 启动时）镜像 cmd_stop 收割 child 进程组；Popen 到 reap 整段 try/finally 内无条件 `_terminate_child`、timeout 路径先杀后 emit；`_run_step` Popen 前与 wait 切片内检查 `_STOP_REQUESTED`。
- **P0-5 「Reject 稿在盘 + 外审窗口」被杀 → resume 永久 blocked**（A1+A3 双方独立确认）
  `src/book_runner.py:274-311`：kill 落在「attempt 已 persist（meta verdict=Reject）、下一 attempt 归档未发生」窗口，fresh resume 的 attempt 0 不归档直接 `BookRunBlocked` → exit 4 终态；附带 `reviewed_existing` 补外审 Reject 绕过 panel_block_policy（:305-306）。
  → 修法：resume 对「exists 且非 approved 且 run_context 指纹与当前一致」的 stale 拒稿章走既有归档+重写路径（与 attempt>0 同款）；`reviewed_existing` Reject 分支接入 panel_block_policy。

## Acceptance

- `PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests` 全绿（基线 1475 + 本轮新增回归）
- `bash scripts/verify.sh`、`python3 main.py preflight` 通过
- 每个 P0 各配直击生产路径的回归测试，特别要求：
  - P0-1：mock fixture 带非空 foreshadowing registry，覆盖「源书遗留项不 block / 续写新种项仍 fail-closed」两侧
  - P0-2：readiness 测试真实加载 plan（不打桩 `_load_chapter_plan`），覆盖 caveat 章 + failure.json 章的 resume 通过
  - P0-4：resume 收割孤儿 child 的单测（模拟盘面残留 child_pid）
  - P0-5：盘面 Reject 稿 + 指纹一致时 resume 归档重写而非 blocked
- mock 25 章长流程回归三关复跑（succeeded / resume 零新调用 / supervisor 集成 exit 0），本轮起含非空伏笔 registry
- 铁律⑨：`/code-review high` + `/security-review`，结论与未修风险回填本文件
- 真模型 smoke 不在本轮验收内（铁律⑥，capstone 顺延 iter078）

## Implementation Notes

- **P0-1 方案选择：读取侧豁免而非播种侧改造**。`build_registry` 是 merge-additive——改播种字段救不了已存在的 registry（longzu 等存量 workspace 需重 compress 才生效）；改在 `overdue_must_resolve` 读取侧按 `planted_chapter<=0` 排除（新增 `is_boundary_item`/`boundary_overdue_must_resolve`），存量 registry 零迁移即修复。fail-closed 边界保持：`planted_chapter` 不可解析 → **不算** boundary（继续 block）；边界项降级为 readiness warning `foreshadowing_boundary_overdue:N` + preflight info 分列「闸门项/源书遗留项」。逃生门：手工把某边界项 `planted_chapter` 改为正数章号即重新武装闸门（文档化于模块 docstring）。
- **P0-1 测试迁移**：`test_foreshadowing.py` 4 个用例 + `test_iter047B2_regression.py` 3 个用例把旧「边界项 block」语义钉死——迁移原则：047B2 的原命题（malformed ttl / 未知 status 必须 fail-closed）与边界豁免正交，fixture 改 `planted_chapter=1` 保命题不变；新增 capstone 形状用例（`resume_from=16` 不 block）、续写新种项仍 block、unparseable planted 仍 block。
- **P0-2 断点 B 方案**：caveat 放行时把 `failure.json` **原子改名**为 `*.failure.caveat.json`（审计内容保留、`observability` 的 `*.failure.json` glob 自然排除已分诊项），meta 记 `caveat_archived_failure`；归档失败让 OSError 直接抛（宁可本 run failed 也不留「caveat=True 但 failure 在盘」的半标记态）。`chapter_status` 的 `not failure` 语义不动。
- **P0-3**：`_panel_block_policy` 区分「键缺失走默认（不告警）」与「显式给出但解析失败（告警）」；yaml 裸 bool 的 `max_panel_rejections` 不再被 `int(True)` 静默变 1；`caveat_continue + max<=0` 矛盾组合告警。告警集进返回值 `config_warnings` + 默认 stderr 一行；preflight 新增 `_check_panel_block_policy`（惰性 import 规避 book_runner→preflight 环形依赖）；`run_write_book` 每个快照经 `_snap` 包装回显生效策略（踩坑：`replace_all` 把包装器自身的内部调用也换成了递归，另 4 空格缩进的最终快照漏换——已修）。
- **P0-4 三条成孤路径全堵**：①`cmd_resume`/`cmd_start` 接管前 `_reap_orphan_child`（TERM→宽限→KILL 升级；killpg 前用 `ps -o command=` 校验含 step 子命令关键字，pid 复用给 `main.py web` 等无关进程时不杀只清指针）；②`_run_step` Popen→reap 整段 try/finally 无条件收割 + timeout 分支**先杀后 emit**；③Popen 前与 wait 切片内检查 `_STOP_REQUESTED`（TERM 落在信号 handler 无子可杀的窗口时不再起新段/切片内补杀）。踩坑：测试里孤儿是测试进程的直接子进程，死后成僵尸使 `os.kill(pid,0)` 仍成功 → 空等宽限 + KILL 升级吃 EPERM（macOS 对僵尸组 killpg 的行为）——生产无此形态（孤儿由 init 收割），代码补 EPERM 兜底、测试用 `proc.poll()` 收僵尸 + 缩短宽限。
- **P0-5**：新增 `_is_resumable_stale_reject`——「同配置中断期拒稿残迹」白名单判定（strict_failures ⊆ {external_review_missing/reject/needs_human/stale} 且 verdict∈{Reject,Approve}）；命中走 attempt>0 同款归档（reason=`stale_reject_resume`）+ 播种上一稿拒因重写；任何 mismatch/legacy/meta 缺失/人工痕迹保持 BookRunBlocked。readiness 同口径豁免为 `stale_reject_will_rewrite` warning（原 `external_review_missing` 特例收紧为 verdict=Approve 才走补外审标签）。附带修复 A3-F4 旁路：`reviewed_existing` 补外审被拒不再 `blocked+break` 绕过 panel_block_policy，改与重试耗尽同款分诊（可 caveat 则 `reviewed_existing_with_caveats` 继续）。
- **scope 备注（铁律⑦）**：全部改动落在计划内五项；顺手项仅两处且直接服务 P0（P0-5 顺带把 readiness 的 external_review_missing 警告加了 verdict 条件；P0-4 的 EPERM 兜底）。六方审查的 P1/P2 一律未动。
- **铁律⑨审查修复批**（收官审查发现，当轮直修，详见 Acceptance Result）：`panel_halted` halt 落盘标记 + stale 谓词补 `failure`/`panel_halted` + `.failure.caveat.json` 归档 + reaper 记录 `child_cmd` 精确比对/ps 失败不放行 + `cmd_stop` 统一走 reaper。踩坑记录：verify.sh 用系统 python3.9（非 .venv），其 3 个 error（PEP604 注解 ×2 + 缺 tiktoken）是 iter076 已记录的既有环境性问题——本轮一度误读为回归，实为管道 `$?` 取到 tail 的退出码；canonical 口径以 .venv 全量为准。

## Acceptance Result

- **unittest**：`discover -s tests`（.venv）= **1517 tests OK**（iter076 基线 1475 → P0 批 1509 → 铁律⑨审查修复批 +8）。含 2 个旧测试语义迁移（`test_book_runner.py` 的 readiness 用例钉死了 P0-5 旧「拒稿残迹必 block」语义；fixture 改为身份不可验证的 legacy 形状，原命题——fail-closed 边界仍 block——保留）。
- **verify.sh**：仅 3 个**既有环境性** error（system python3.9 的 PEP604 注解 ×2 + 缺 tiktoken ×1），与 iter076 收官时相同、非本轮引入；.venv 全量为准。**preflight**：`PREFLIGHT: ok`（含本轮新增的 `panel_block_policy 生效值` info 行）。
- **mock 25 章长流程回归**（合成文本 workspace `iter077_longrun`，零版权原文，验后已删；`--chapters 25 --segment-size 25 --replan-every 5 --allow-missing-start-point` + `MOCK_WRITER_CHARS=4000`）：
  - **PASS-1** drive-book start：exit 0、`status=succeeded`、25/25 章落盘。
  - **PASS-1b（本轮新增关，P0-1 in vivo）**：registry 被 mock fixture 播种非空（2 项边界种子，闸门路径首次获得 mock 覆盖）；`write-readiness --chapters 5 --resume-from 16`（修复前确定性杀死 capstone 的形状）= `status=warn` + `foreshadowing_boundary_overdue:2`，零 blocker。
  - **PASS-2** resume：exit 0、llm_calls.jsonl 369 行不变（零新 LLM 调用）。
  - **PASS-3** `drive_book_supervised.sh --resume-first`：round=1 exit 0、25/25 `skipped_approved`、`cost_cny` 零增量、supervisor 收口 `succeeded — all done`。
- **铁律⑨ 双审查**（本轮属 runner/driver 高风险改动，按升级条款跑 8 finder 视角）：
  - `/code-review high`：8 个独立 finder subagent（逐行/被删行为/跨文件/复用/简化/效率/修复深度/约定），6 个完成、2 个（逐行 A、跨文件 C）撞账号会话限额未产出——覆盖补偿：被删行为视角实际做了逐 hunk 级审计，跨文件视角已由本轮立项前的六方审查独立覆盖；候选由本体逐条 inline 核验（省配额）。**产出 1 个 bug 级 CONFIRMED**：`_is_resumable_stale_reject` 不看 `failure`/halt 结论——lint 终败章与 retry 耗尽 halt 章的盘面恰落白名单，resume 会静默重烧注定失败的整轮重试（halt 语义只活一个进程生命周期）。**审查修复批（+8 tests，全绿后复验 1517 OK）**：①谓词补 `failure`/`panel_halted` 双检查；②新增 `_mark_panel_halted` 把 halt 分诊结论落盘（retry_exhausted/hard_reject/external_review_reject 三径），`chapter_status` 透出——「停下等人」跨进程存活；③`.failure.caveat.json` 进归档 suffix 清单（force 重写不再留跨世代审计残片）；④`_reap_orphan_child` 堵 fail-open：ps 查询失败改按 cmd_stop 先例无校验收割（不放行第二写者）+ `state["child_cmd"]` 记录启动 argv 精确比对（pid 复用给另一 workspace 的 step 不误杀）+ EPERM=非亲儿子只清指针；⑤`cmd_stop` 孤儿收割统一改调 `_reap_orphan_child`（获得判别式+KILL 升级，旧内联版一枪 TERM 谎报 stopped）；⑥补 expired-gating 测试覆盖（迁移丢失面回填）。
  - `/security-review`：**零发现**。六类逐查（subprocess argv 构造为 list+int 强转无注入面 / killpg 目标全出自本方 state 且有判别护栏 / 文件名 `:02d` 格式化无穿越 / `sk-`·`.env`·secret 模式 grep 零命中（铁律①）/ stderr 与快照无敏感泄漏 / 无新反序列化面）。mock fixture 合成文本，铁律②干净。
  - **审查后未修风险**（P2/技债，记入下一轮候选）：处置五分类（skip_approved/skip_caveat/补外审/stale 重写/block）应下沉 `chapter_status` 单一真源（readiness 与 run 两条平行链已第三次同步手改，本轮谓词漏 `failure` 正是平行维护的实证）；boundary 判定应改播种时显式 `origin` 字段（当前 planted_chapter<=0 猜测——若未来加「续写回灌 compress」，新种伏笔会生而 advisory、闸门静默失效）；caveat 分诊块两处同构可抽闭包；`_snap` 未吸收 7 处基底 payload；`include_boundary` 参数 test-only；registry 每 readiness 双读盘 + preflight 重复 load_config（毫秒级）；readiness 对非标 verdict 的收窄为有意为之（与 run 口径一致、提前失败）。
- **已知未修风险**（本轮范围外，见「不在本轮范围」）：P1 全部顺延（reviewer NaN crash、Web/CLI 无锁、预算账本失真、entity 三连、rolling 落盘顺序、指纹不含 model/tier、tiktoken 计数、env 守门盲区）——capstone 可按 Notes 跑前清单操作规避；caveat 章的 `--force` 重写不归档 `*.failure.caveat.json` 残留（无害审计残迹，随 P1 批处理）。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/foreshadowing.py` | P0-1：`is_boundary_item` / `boundary_overdue_must_resolve` 新增；`overdue_must_resolve` 默认排除 `planted_chapter<=0` 边界项（`include_boundary` 可开）；模块 docstring 记语义与逃生门 |
| `src/book_runner.py` | P0-1：readiness 边界项降级 warning；P0-2：readiness 豁免 `caveat_approved`、`_mark_caveat_approved` 归档 failure.json；P0-3：`_panel_block_policy` config_warnings + stderr + `_snap` 快照回显；P0-5：`_is_resumable_stale_reject` + stale 残迹归档重写 + readiness 同口径 warning + `reviewed_existing` 接入 panel_block_policy；审查修复：谓词补 failure/panel_halted、`_mark_panel_halted` halt 落盘、`.failure.caveat.json` 归档 |
| `src/book_driver.py` | P0-4：`_reap_orphan_child`（含 cmdline 判别与 EPERM 兜底）挂入 `cmd_start`/`cmd_resume`；`_run_step` Popen 段 try/finally 无条件收割、timeout 先杀后 emit、Popen 前/切片内 `_STOP_REQUESTED` 检查；审查修复：`state["child_cmd"]` 记录+精确比对、ps 失败不放行、`cmd_stop` 统一走 reaper |
| `src/chapter_status.py` | 审查修复：透出 `panel_halted` 字段（halt 结论跨进程可见） |
| `src/preflight.py` | P0-1：伏笔 registry 计数分列闸门项/源书遗留项；P0-3：`_check_panel_block_policy` 前置校验 + 生效值 info |
| `src/llm_client.py` | P0-1：mock ChapterExtraction 的 foreshadowing 改非空 fixture（mock 长跑对闸门路径不再零覆盖） |
| `tests/test_foreshadowing.py` | 语义迁移 ×4 + 新增 capstone 形状/新种项仍 block/unparseable 仍 block ×4 |
| `tests/test_iter047B2_regression.py` | h3/m3/m6 fixture 改 `planted_chapter=1` 保原命题 + 新增边界项不告警用例 |
| `tests/test_book_runner_panel_policy.py` | loader 全等断言迁移 ×2 + P0-3 新增 6 用例（typo/bool/矛盾组合/合法零告警/preflight 透出/快照回显） |
| `tests/test_iter077_caveat_readiness.py` | 新增：P0-2 双断点回归（真 plan 落盘不打桩，含对照组防盲区复发）×6 |
| `tests/test_iter077_orphan_reaping.py` | 新增：P0-4 回归（真实进程组收割/不误杀/resume+start 挂钩/TERM 窗口/emit OSError）×8 |
| `tests/test_iter077_stale_reject_resume.py` | 新增：P0-5 回归（判定函数矩阵/归档重写/mismatch 仍 block/policy 接入/readiness 豁免）×11 |

## 不在本轮范围

六方审查的 P1/P2 顺延为 backlog（capstone 前可靠操作规避，规避项见 Notes 跑前清单）：

- **P1**：reviewer NaN/Inf crash + 字符串分数 fail-open（reviewer.py:87-97）；Web/CLI 无互斥锁双写（全仓无 flock，jobs.py:1289 vs book_driver.py:893）；预算账本三重失真（单价硬编码 deepseek / 失败 attempt 不入账 / 脏行 fail-open 0 元）；entity 子系统三连（approved 后 advance 丢失窗口 / 空 new_state 绕三重门毒化 entity_graph / `_propose_entity_advance` 第 5 注入点无界 timeline）；rolling summary 先于正文落盘的 resume 自我毒化；run_context 指纹不含 model/tier（mock 章混真书）；tiktoken 中文虚高 1.5-2× + deepseek 64K/128K 矛盾；env/preflight 守门盲区（WRITE_REVIEW_TIER / LLM_REQUEST_TIMEOUT 非有限值 / max_tokens↔context_limit / anchor 假阳性）
- **P2**：双 resume TOCTOU、watchdog `pid_is_driver` 判别式过宽、cmd_stop killpg 无校验、supervise.pid trap 缺 INT/TERM、RESET_SECONDS 使 MAX_RESTARTS 对慢楔死失效、手动 stop 被 supervisor 覆盖、resume 静默丢参数 / --resume-first 丢预算帽、force-once 整段重写、Web budget 0.0 无上限、"0.0000" 无上限段、content:null 误判、score 不 clamp、extract_json_object 切片、debate log 清洗非原子、SIGTERM 无 handler partial 承诺失效、--book 拼错静默建目录、llm_calls.jsonl O(n²) 重读、drama_agents 死配置等
- capstone 真模型实跑（→ iter078，铁律⑥需用户授权）

## Notes

- **审查方法**：6 个 general-purpose subagent 并行只读审查（中途因额度暂停 4 个、恢复后接续原上下文完成），总耗约 110 万 subagent token；与 codex 独立报告交叉对照。交叉命中项（孤儿双写、caveat 双断点、reviewer NaN）可信度最高；我方独有重大项：伏笔闸门、panel_block_policy 静默 halt、Web/CLI 无锁、指纹不含 model/tier。
- **测试盲区教训**：mock 路径的 graceful degrade（铁律④）会让 fail-closed 闸门在 mock 回归中零覆盖——mock fixture 应给可选数据源至少一份非空样本，否则「25 章 mock 全过」对相应闸门无背书力；打桩过深的单测（`_load_chapter_plan`→None）同理。
- **capstone 跑前清单**（若 P1 未修即实跑）：跑前打印 `_panel_block_policy()` 生效值；清 shell/.env 的 WRITE_REVIEW_TIER 等脏值；用干净 workspace（或对 mock 排练章 --force）；确认 workspace 的 continuation_anchor.txt 存在；`--budget-cny` 空格形式且 >0；watchdog 用 `--driver` 不带 `--pid`；长跑期间 dashboard 只读；人工干预先停 supervisor 再 drive-book stop。
