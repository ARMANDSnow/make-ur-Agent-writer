# Iteration 076 - 长跑可靠性硬化 + iter074/075 codex 修复批

## Context

用户对真模型 capstone（10-20 章过夜跑）的核心诉求是「睡前开跑、睡醒不能中断/跑废」（iter074-077 路线图，计划稿 `~/.claude/plans/logical-snuggling-gray.md`；本轮细化计划 `~/.claude/plans/iter-076-bright-simon.md`）。现有 detach/断点续跑机制本身扎实（resume 零 LLM 花费、进度全从盘面推导），但**自动恢复层有洞**，一晚上会「跑废」的真凶集中在五处：面板拒稿 halt 全书（`book_runner.py:297-299` retry_exhausted 后 break）、预算「花前查」无预留可能中途耗尽留半成品、driver 单一 `--step-timeout-minutes` 粒度粗（debate 可 3h、write 段不该）、watchdog 只看 `llm_calls.jsonl` mtime 测不到后处理卡死、crash/watchdog 杀掉后无自动重启（恢复要手动 resume）。本轮修这 5 个 HIGH 项，是 iter077 真模型 capstone 的前置门。

另：外部 codex 审查 iter074（章节版本 diff）/075（全文搜索）报了 6 个主问题 + 若干低风险项，经逐条源码核实**全部属实**（含内部复核曾误判「不属实」的 2 条：`sources=` 空值经 `parse_qs` 默认丢弃变 `None`→全搜；搜索 `run()` 的 early return 在 `++seq` 之前→旧响应可覆盖空态）。用户指示「这次一并修掉」，作为本轮前置 A 部分（独立 commit）。

**计划可行性核查修正**（对照路线图原文）：① runner 级策略改名 `panel_block_policy`（原 `on_blocked` 与 driver 既有段级 `--on-blocked stop|force-once` 撞名）；② review 不是 driver 独立 step（在 write-book 内部），分档超时按 step 种类拆 debate/plan/write，review 由 write 段超时兜底；③ 心跳语义分层——心跳测 **driver 进程**卡死，child 卡死由 step 超时兜（此时心跳仍在跳）。

## Plan

**A 部分：codex 修复批**（独立 commit `fix(iter076a)`）
1. `search.py:199` manifest `normalized_file` 越界读 → `resolve().relative_to(normalized_dir)` 收容，越界跳过
2. `routes.py:2609` `parse_qs` 加 `keep_blank_values=True`（消费点已逐一审安全）+ `?sources=` 空值回归
3. `static.py` 搜索 `run()` 的 `++seq` 移到首行（early return 前）
4. `static.py` `runChapterDiff` 加 `diffSeq` stale guard + select change 自动重跑
5. `search.py:321` `total_matches` 截断前求和（全局真实数）+ 前端截断提示注明
6. `chapter_diff.py` `_version_entry` 收容校验（防 snapshot 内 symlink 探测）+ 去全文读（`chars`→`size_bytes` via `st_size`）；`compute_diff` 加输入/输出上限 + `truncated`
7. 低风险项：API `path`/`snapshot_path` 相对化、搜索页 URL 恢复 `q`/`sources`、搜索框 aria-label、自动搜索 ≥2 字（Enter 允许 1 字）

**B 部分：长跑可靠性硬化**（commit `feat(iter076)`）
1. **HIGH#1** 面板拒稿不 halt：`agents.yaml` 新 `panel_block_policy {on_soft_reject, max_panel_rejections, on_hard_reject}`（默认全保守=现行为）；reviewer report 顶层 `hard_reject` + helper；chapter_status 透出 `hard_reject`/`caveat_approved`；book_runner soft→caveat_continue 标记继续 / hard→force_once bonus 一轮 / 其余 halt
2. **HIGH#2** 每章预算预留：`cost_estimator.estimate_next_chapter_cost`（累计值差分 + 近 3 章滑动均值 + config default）；`agents.yaml budget_reserve {safety_factor, default_chapter_cost_cny}`；章前闸不足 → `budget_exceeded + reserve_stop` 干净停
3. **HIGH#3** 分档超时：drive-book 新 `--debate/--plan/--write-timeout-minutes`（fallback `--step-timeout-minutes`），start/resume 双侧校验
4. **HIGH#4** 心跳：`_run_step` 30s 切片 poll + `logs/driver/driver_heartbeat.json`（含 shell 友好 `epoch`）；`watchdog.sh` 新 `--driver` 模式读心跳判活 + abort 前写 `watchdog_abort.json` 标记
5. **HIGH#5** crash 自动重启：新 `scripts/drive_book_supervised.sh` 前台循环 start/resume（exit code + state 决策表、指数退避、上限 5 次、caffeinate、确认闸、`SUPERVISE_CMD` 可测注入）；driver paused 出口落 `paused_reason`

## Acceptance

- 全部 mock 验（铁律③⑥，本轮不跑真模型）：新增单测覆盖 A 部分各修复回归 + soft/hard reject 分类与 `panel_block_policy` 各分支 + 预算预留（够/不够/budget=0）+ 分档超时解析（start/resume/fallback）+ 心跳文件写入节拍与字段 + watchdog driver 模式判活 + supervisor 重启退避各分支（假 exit code 剧本）
- `.venv` `unittest discover` 全绿（≥1415 + 新增）；`bash scripts/verify.sh`；`python3 main.py preflight`
- mock 25 章长流程回归（handoff 教训⑤最短路径 + `MOCK_WRITER_CHARS=4000`，drive-book 全链路）：零崩溃、resume 零新 LLM 调用、心跳文件持续刷新
- 铁律⑨：runner/driver 高风险改动 → 2 个独立视角 subagent 并行审 + `/security-review`；`/code-review ultra` 为用户可选加跑（需用户授权计费）。结论回填本文件

## Implementation Notes

**A 部分（codex 修复批，独立 commit `476318c`）**：
- **search 收容闸**：`_search_original` 读前 `Path(nf).resolve().relative_to(normalized_dir.resolve())`，越界/symlink 逃逸按坏章跳过（cache 标 None）。副作用：读取走 resolve 后路径（macOS `/var`→`/private/var`），既有读缓存测试改按文件名聚合计数。
- **total_matches**：截断前求和一行前移；`hit_count` 仍是截断后展示面，`SearchResult` docstring 明确两者语义差。
- **keep_blank_values 全局化**：dispatch 一处改动；消费点逐一核过（variant/v1/v2/q 走 `or ""`，`_parse_int`/`_parse_n` 对 `int("")` catch ValueError 落 default），补 `?sources=` 与 `?n=` 两条回归钉死。
- **chapter_diff**：`_version_entry` 收容 + `stat` 取 `size_bytes`（原 `chars` 前端/测试零消费，安全改名）；`exists` 语义收紧为「收容内真实文件」——快照内 symlink 逃逸的版本直接不进列表（也就进不了 `valid_ids`，diff 端点触盘前 400）。`compute_diff` 输入上限 500k/侧 + 输出 5000 行 + `truncated` 标记（截断说明作为 meta 行回传，前端零改动即可展示）。
- **路径投影**：`_ws_relative` 应用于 `_draft_summary`/`api_workspace_draft`（meta 浅拷贝改投影字段，磁盘 meta.json 不动）+ `book_runner._snapshot` 源头相对化（消费方仅 jobs/前端展示，测试 fixture 本就是相对路径风格）。
- **前端**：搜索 `run()` 的 `++seq` 提到 early return 前（codex #3 的根修）；`diffSeq` 双函数守卫 + select `onchange` 自动重跑；URL `replaceState` 恢复 `q`/`sources`；自动检索 ≥2 字（Enter/URL 恢复视同显式允许单字）；aria-label。

**B 部分（长跑硬化）**：
- **HIGH#1**：reviewer report 顶层 `hard_reject` + 导出 `has_hard_synthetic_reject`（chapter_status 内联同语义派生，避免把 reviewer 重依赖拖进轻量 triage 模块，注释互指同步）。runner 重试循环 for→while 支持 hard×force_once 的单次 bonus attempt；caveat 放行走 fall-through 复用 approved 路径的章后公共步骤（auto_advance/costs/replan 一致——实体推进与滚动摘要必须跟上正文）。`skipped_caveat` 分支置于「存在未 approve 旧产物 → BookRunBlocked」之前，resume 不会被自己放行的章卡死。`caveats` 进全部 6 个 summary payload。**默认全保守**（halt/halt/0）＝原行为逐字节回归（有测试钉死）。
- **HIGH#2**：`estimate_next_chapter_cost` 对 costs **累计值**序列先差分再滑动均值（首元素本身即第一章成本，`prev=0` 起步天然正确；负差分=脏账本丢弃）；预留闸放在 **skip 判断之后**（skip 章零花费不占预留，resume 尾段全 skip 场景不误停）、动笔前（含 reviewed_existing 外审路径）。复用 `budget_exceeded` 管道 + `reserve_stop` 标记，driver/CLI 零新映射。
- **HIGH#3**：`_step_timeout(params, kind)` fallback 链（kind→step→180 默认，0 与坏值都回落）；start/resume 双侧校验复制 iter073 模式；review 在 write-book 内部由 write 档兜底（本段 docstring + agents.yaml note 写明）。
- **HIGH#4**：`_run_step` 整段 `child.wait(全量)` 改 30s 切片 poll，每片 + step 边界各写一拍 `driver_heartbeat.json`（`epoch` 整型秒供 shell 零依赖提取；cost 每拍经 `_spent_cny` 自带兜底）。语义分层：**心跳测 driver 进程**，child 卡死由 step 超时兜（此时心跳仍在跳）。watchdog `--driver` 模式读心跳 epoch（缺失回退 llm mtime 老逻辑），abort 前 tmp+mv 原子写 `watchdog_abort.json`；driver 模式 pid 缺省逐轮从 `driver.pid` 重读（supervisor 重启后 pid 会变）。顺手修了 legacy `STAT_FMT` 探测的潜在错判（原以 LOG_PATH 存在性探测 stat 方言，文件未生成时 macOS 会误落 `stat -c`；现加 `$0` 兜底探测）。
- **HIGH#5**：新 `scripts/drive_book_supervised.sh`（不动 drive_book.sh——其内容有测试断言）。**前台**循环 start/resume（wait 拿 exit code 最可靠，弃 detach 轮询方案）；决策表=exit code × `state.status` × `paused_reason` × watchdog 标记新鲜度（mtime ≥ 本轮起点；消费改名 `.consumed` 留证）；指数退避 `SUPERVISE_BACKOFF_BASE×2^n` 封顶 60s、`SUPERVISE_MAX_RESTARTS`（默认 5）超限 exit 75 响亮升级人工、单轮存活 ≥600s 重启计数归零；supervisor 自起 `caffeinate -i -w $$`（driver 的 caffeinate 仅 detach 路径起，前台归 supervisor 管）；真模型确认闸与 drive_book.sh 同款；`SUPERVISE_CMD`/`SUPERVISE_BACKOFF_BASE` 测试钩子让决策表可被 stub 剧本全覆盖。driver 侧配套：全部 paused 出口经 `_paused()` 落 `paused_reason`（step_timeout / pause_after_segment），resume/新一轮运行清空；`cmd_status` 透出 `paused_reason` + `heartbeat_age_seconds`。
- **测试基建顺手项**：DRIVER_STUB 剧本新增 `sleep_s`（超时/心跳剧本用）；`_driver_args` 未加新键（getattr 缺省 None 天然兼容）。

**与计划的偏差（铁律⑦）**：无计划外文件。计划内微调：① watchdog STAT_FMT 探测兜底（见上，与 --driver 模式同文件顺手修，一行）；② `_version_entry` 的 `chars`→`size_bytes` 改名（计划里已列，确认零消费后执行）。

## Acceptance Result

**单测**：`.venv`(Python 3.13) `unittest discover` = **1468 tests OK**（较 iter075 的 1415 +53；两次复跑确认，期间一次并行争抢下的计时闪失已排除）。审查修复批后新增/扩展再 +7（supervisor 13、panel_policy 12、budget_reserve 7、chapter_diff 19、routes_get path 断言），终态数字以收官全量为准（见下）。

**verify.sh**：系统 python3.9 下 3 个**既有环境性** error（`test_book_runner*` 模块加载 pydantic/PEP604 ×2 + 缺 tiktoken ×1）——与 iter074/075 记录逐字节同口径，非本轮引入；权威套件是 `.venv` discover。`preflight`(venv) 无 FATAL，仅常规 WARN/INFO。

**mock 25 章长流程回归**（合成文本 workspace，零版权原文，验完即删）：`drive-book start --chapters 25 --segment-size 25 --replan-every 5`（mock planner 固定 5 章 → 靠滚动 replan，见 Notes）三关全过——**PASS-1** succeeded + 25/25 Approve + 心跳新鲜（step=write_seg1, age=0s）；**PASS-2** resume 零新 LLM 调用（llm_calls.jsonl 369 行不变）；**PASS-3** `drive_book_supervised.sh --resume-first` 真 driver 集成一轮收口 exit 0、仍零花费。审查修复批落地后已重跑确认。

**铁律⑨ 双视角审查（2 独立 subagent 并行）**：
- **视角 A（正确性/状态机/时序）**：确认无问题——重试 while+bonus 边界（max_retries=0、bonus 单发、必然终止，与旧 for 逐字节等价）、caveat fall-through 与 approved 路径共段代码、`written[-1]` 前提（异常路径都在 append 前 return）、切片 poll 数学与 `started` 作用域（无 NameError 路径）、`rc=$?` 捕获与空数组习语、`json_int_field` 提取（实测 `"pid"` 不会误配 `"pgid"`）。报 3 MED + 3 LOW。
- **视角 B（安全/注入/fail-open/铁律）**：铁律①全 diff 零命中（唯一 "secret" 是收容测试的合成 fixture 名）；铁律②新测试全合成文本；search 收容闸实（读取对象=过闸的同一 resolved）；keep_blank_values 全消费点核毕安全；XSS 无新增面；原子写无撕裂读。报 2 MED + 9 LOW + INFO 若干。
- **已修**（本轮内落地 + 回归测试钉死）：**A3/B-M1/B-M2 三个 MED 全修**——① 预留闸下移至补外审分支之后（纯补外审 resume 不再被整章预留误停）；② supervisor 加 `SUPERVISE_MAX_ROUNDS`（默认 48）总轮次硬顶（不随存活归零重置，封死慢崩无界环=同时解决 A5a）+ 真模型无 `--budget-cny` 启动 WARN；③ watchdog driver 模式 TERM→30s→SIGKILL 升级 + abort 后留场看护（abort_armed 缴械/上膛）。**A2a**（caveat 配额跨 run 累计：起跑计入盘面存量 caveat 章）。LOW 批：**B-L1**（path 投影挪进 use_workspace 块内，跨书浏览泄露复活面关死）、**B-L2**（心跳写失败一次性 stderr 留痕）、**B-L4**（负 default 回落 2.0 与 note 对齐）、**B-L5**（预留闸裸调 budget_check_cb 包干净收场）、**B-L6**（resolve_version_text current 分支补收容复检）、**B-L7**（watchdog kill 前校验 pid 命令行防复用误杀）、**B-L9**（supervisor `supervise.pid` 互斥）、**B-L3/L8**（agents.yaml note 口径修正 + supervisor 头注声明「先停 supervisor 再停 driver」「每 book 单 supervisor」）。
- **已接受残留（未修，附理由）**：B-L6 附带项（meta.json/archive_reason.json 仍跟随 symlink——需本地写权限者可直接读目标，无新增信任边界）；A2b/B-L3 首条（非面板原因的不过审也记 `panel_soft_reject`——标签失真但放行+晨查行为符合过夜韧性意图，note 已声明覆盖面）；A6b（STAT_FMT 探测在 GNU coreutils 的理论错判——macOS-only 项目，且属既有嫌疑非本轮引入）；B-INFO 心跳每拍全量读账本（预期规模无碍，长账本纯性能注记）；`_snapshot` 相对化 fallback 死代码（无害防御）。
- **视角 A 补注**：首轮视角 A agent 撞会话限额未产出，以紧凑 prompt 重发后完成——两视角均为独立 subagent，符合铁律⑨「高风险改动双视角」要求；`/code-review ultra` 为用户可选加跑（需用户授权计费，未执行）。

## 文件变更汇总

**A 部分（commit `fix(iter076a)` = `476318c`）**

| 文件 | 改动 |
|---|---|
| `src/search.py` | normalized_file 收容闸（resolve+relative_to，越界/symlink 跳过）+ total_matches 截断前求和 |
| `src/web/routes.py` | dispatch `keep_blank_values=True` + `_ws_relative` 路径投影（drafts 列表/详情） |
| `src/web/chapter_diff.py` | `_safe_stat_size` 收容 + 零正文 IO（chars→size_bytes）+ `compute_diff` 输入/输出上限与 truncated |
| `src/web/static.py` | 搜索 seq 提前 / diffSeq stale guard + select 自动重跑 / 截断提示 / URL 恢复 / ≥2 字门槛 |
| `src/web/templates.py` | 搜索框 aria-label |
| `src/book_runner.py` | `_snapshot` 快照路径相对化外发 |
| `tests/test_search.py` `tests/test_web_search.py` `tests/test_web_chapter_diff.py` | +9 回归 |

**B 部分（commit `feat(iter076)`）**

| 文件 | 改动 |
|---|---|
| `src/reviewer.py` | report 顶层 `hard_reject` + `has_hard_synthetic_reject` helper |
| `src/chapter_status.py` | `hard_reject`（meta+外审派生）/ `caveat_approved` 字段 |
| `src/book_runner.py` | `panel_block_policy` 加载与分诊（caveat_continue/force_once/halt）、`skipped_caveat`、`_mark_caveat_approved`、`budget_reserve` 章前预留闸、`caveats` 进 summary；审查修复：预留闸下移至补外审分支后（A3）、caveat 配额计入盘面存量跨 run 累计（A2a）、预留闸裸调包干净收场（B-L5）、负 default 回落（B-L4） |
| `src/cost_estimator.py` | `estimate_next_chapter_cost`（累计值差分 + 滑动均值 + default 兜底，单条脏账跳过） |
| `src/book_driver.py` | `_step_timeout` 分档（debate/plan/write）+ start/resume 双侧校验、30s 切片心跳 `driver_heartbeat.json`、`_paused()`/`paused_reason`、status 透出心跳年龄；审查修复：心跳写失败一次性留痕（B-L2） |
| `src/web/routes.py` | 审查修复：draft 详情投影挪进 use_workspace 块内（B-L1） |
| `src/web/chapter_diff.py` | 审查修复：`resolve_version_text` current 分支收容复检（B-L6） |
| `main.py` | drive-book 新 `--debate/--plan/--write-timeout-minutes` |
| `config/agents.yaml` | `panel_block_policy` + `budget_reserve` 块（含语义注释，默认保守；审查后修正 note 口径 B-L3/L4） |
| `scripts/watchdog.sh` | `--driver` 心跳判活模式 + `watchdog_abort.json` 标记 + pid 自动回退 + STAT_FMT 探测兜底；审查修复：TERM→30s→SIGKILL 升级 + abort 后留场（abort_armed，B-M2/A5b）+ kill 前 pid 命令行校验（B-L7） |
| `scripts/drive_book_supervised.sh` | 新增：crash 自动重启 supervisor（决策表/退避/上限/caffeinate/确认闸/测试钩子）；审查修复：`SUPERVISE_MAX_ROUNDS` 总轮次硬顶 + 真模型无预算 WARN（B-M1/A5a）+ `supervise.pid` 互斥（B-L9）+ 人工干预约定头注（B-L8） |
| `tests/test_book_runner_panel_policy.py` | 新增 12 例：分诊全分支 + 加载器坏值 + 跨 run 配额（A2a） |
| `tests/test_book_runner_budget_reserve.py` | 新增 7 例：预留够/不够/budget=0/skip 不占预留 + 补外审不误停（A3）+ 负 default 回落（L4） |
| `tests/test_cost_estimator.py` | +5 例：差分/滑窗/脏账/负差分/default 钳制 |
| `tests/test_chapter_status.py` | +1 例：hard_reject 派生优先级 + caveat×failure |
| `tests/test_reviewer_plan_compliance.py` | +2 例：report 字段 + helper 矩阵 |
| `tests/test_book_driver.py` | +8 例：fallback 链/双侧校验/心跳节拍与字段/paused_reason；stub 支持 `sleep_s` |
| `tests/test_supervisor.py` | 新增 13 例：决策表全分支 + MAX_ROUNDS 慢崩封顶 + pid 互斥/残留（stub 剧本） |
| `tests/test_smoke_scripts.py` | +2 例：watchdog --driver 与 supervised 契约断言（含审查修复项） |
| `tests/test_web_chapter_diff.py` | +1 例：current 分支 symlink 逃逸 fail-closed（L6） |
| `tests/test_web_routes_get.py` | +path 相对投影断言（L1 回归） |
| `docs/iterations/*076*.md` + `docs/iterations/README.md` + `README.md` + `docs/AGENT_HANDOFF.md` | 迭代文档 / 索引 / SOP 表 / handoff（铁律⑧） |

## 不在本轮范围

- 真模型 capstone 实跑（iter 077，需用户授权，铁律⑥）
- 可靠性 MEDIUM/LOW 项（段级预算回滚、指标导出、可配置退避 jitter）
- writer 内部评审阶段粒度超时（由 write 段超时兜底，本轮不下钻）
- Aeloon 深色模式对齐 / drama 站③④ / SQLite FTS / char-level diff（backlog 不变）

## Notes

**教训 / 已知边界**：
- **mock planner 固定 5 章**：`plan-chapters --chapters 25 --force` 在 mock 下只写「mock 五章大纲」（5 章），忽略 --chapters。25 章回归第一版用 `drive-book --segment-size 5` 在段 2 的 readiness 撞 `chapter_plan_missing`——**不是本轮 bug，是 mock 路径既有边界**：真模型下 planner 真生成 N 章无此问题；mock 下长程必须靠 `--replan-every` 的滚动 append（readiness 对 replan_every 有容忍逻辑，只要求覆盖到下一个 replan 点）。回归改走 handoff 教训⑤同款 `--segment-size 25 --replan-every 5` 路径。**后续候选**：mock planner 尊重 --chapters（低价值：只影响 mock 长程分段组合，真模型无此形态）。
- 心跳的语义分层要在文档里反复讲清：**心跳测 driver 进程**（切片 poll 期间持续刷新），child 卡死由 step 超时兜（此时心跳仍在跳）——两层各管一头，watchdog --driver 判的是前者。

**后续候选**：iter077 真模型 capstone 实跑（10-20 章，铁律⑥需用户授权；建议配置 `on_soft_reject=caveat_continue + max_panel_rejections=2 + tier=mid`，入口 `nohup bash scripts/drive_book_supervised.sh --book longzu --confirm-real-smoke -- --chapters 20 ...` + `watchdog.sh --driver`）；可靠性 MEDIUM/LOW（段级预算回滚 / 指标导出 / 退避 jitter）；mock planner --chapters；Aeloon 深色模式对齐等 backlog 不变。

**对铁律的影响**：无新增铁律。①（零 key/env 触碰）②（回归/测试全合成文本）③（全 mock）⑤（只 commit 不 push）⑥（真模型入口全部带确认闸，包括新 supervisor）⑦（无计划外文件，微调已在 Implementation Notes 标注）⑧⑨（本文件 + SOP + 双审查）。
