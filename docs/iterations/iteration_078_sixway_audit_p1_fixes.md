# Iteration 078 - 六方审查 P1 修复批（8 组）+ 技债 2 项

## Context

iter077 修完六方并行审查（6 subagent 视角 + codex 交叉对照，~40 项分级）的 P0 五项后，P1 八组与铁律⑨审查提名的 2 项技债顺延至本轮。用户拍板范围：**P1 全部 8 组 + 技债 2 项一轮清空**，目标是让 iter079 的真模型 capstone 实跑不再依赖 iter077 Notes 的「跑前清单规避」（人工规避项大部分失效化）。P2 继续顺延。

问题清单来源：`iteration_077_longrun_audit_p0_fixes.md`「不在本轮范围」（P1 八组）+ Acceptance Result「审查后未修风险」（技债 2 项）。本轮立项前由 3 个 Explore agent 并行核实全部代码触点，Plan agent 抽查修正了三处初判偏差（NaN 消费主现场在 reviewer.py:685 而非 book_runner；「失败 attempt 缺 token」实为 N 次重试只记 1 条 error 的漏账 + 超时 response tokens 无记录；prune_from_chapter 已在归档路径接线、唯一缺口是 fresh-write 路径）。完整计划见 `~/.claude/plans/iter077-bug-5-p0-iter-async-oasis.md`。

## Plan

按「重要程度 × 依赖关系」排序实施，每项完成后立即跑全量单测：

1. **P1-1 reviewer 分数护栏** — `_coerce_score`（接受数字/纯数字字符串，拒绝 bool/NaN/Inf，clamp [0,10]）+ `_agent_weighted_score`/`_weighted_panel_score`/`_repair_agent_review_dict` 三处护栏 + :685 判定处 `score_warning` 留痕
2. **P1-7 workspace 写锁** — 新建 `src/workspace_lock.py`（fcntl.flock LOCK_EX|LOCK_NB + holder json；`WorkspaceLocked` 继承 `BookRunBlocked` 零新退出码）；加锁点 `run_write_book` 入口 + main.py legacy `write`
3. **P1-5 rolling 落盘顺序** — writer stage 顺序反转为 persist→summarize→rolling→提案；readiness 补 `rolling_summary_gap:NN` warning；fresh-write 前 `prune_from_chapter` 补线
4. **P1-4 entity 三连**（②→③→①）— `_apply_selected` 统一非空校验；`_propose_entity_advance` 16K 截断（补 iter073 漏掉的第 5 注入点）；`advance_applied` sidecar + skip 分支补偿 apply + `unapplied_auto_indexes` 锚点去重（存量零迁移）
5. **P1-6 指纹补 model/review_tier** — `_run_context` 加两键；chapter_status 新键「双方非空才比对」（旧 meta 兼容）；mock 章混真书从静默跳过变显式 block
6. **P1-2 预算账本** — `MODEL_PRICING` 按 model 前缀查表 + 聚合逐行计价；重试循环每失败 attempt 记 `retry_error`（最终 error 条 prompt_tokens 置 0 防双计）；脏行 `dirty_lines` 计数 + WARN
7. **P1-3 CJK 计数 + 64K 统一** — count_tokens 对 deepseek 前缀 `min(tiktoken_raw, ceil(cjk*0.75+other*0.4))`（只减不增结构保证）；models.yaml 8 处 128000→64000；preflight yaml vs DEFAULT 矛盾检查
8. **P1-8 preflight 守门 4 项** — WRITE_REVIEW_TIER 脏值 FATAL；`_env_float` 补 isfinite（LLM_REQUEST_TIMEOUT）；max_tokens↔context_limit FATAL/WARN；anchor 空文件 WARN
9. **技债-2 foreshadowing origin** — 播种侧显式 `origin: source_book|continuation`；`is_boundary_item` origin 优先、无 origin 回落 `planted_chapter<=0` 旧启发式（存量零迁移）
10. **技债-1 处置五分类下沉**（收官重构，行为零变更硬约束）— chapter_status 新增 `ChapterDisposition` 枚举 + `classify_disposition` 纯函数，run/readiness 双循环消费同一真源

## Acceptance

- `PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests` 全绿（基线 1517 + 本轮新增；.venv canonical）
- `bash scripts/verify.sh`（允许既有 3 个环境性 error，不允许新增）、`python3 main.py preflight` 通过（期待新增 tier/context_limit/anchor 回显行）
- 每项配直击生产路径的回归测试（禁 stub 内部函数，mock 边界在 LLMClient/文件系统 fixture 层）
- mock 25 章长流程五关：PASS-1 start / PASS-1b readiness resume-from 16（P0-1 回归保持）/ PASS-2 resume 零新调用（P1-4① 补偿与 P1-5 prune 零 LLM 实证）/ PASS-3 supervised 收口 / **PASS-4（本轮新增）锁 in vivo**：主跑期间另起 write-book 立即被拒且报错含 holder 信息
- 铁律⑨：`/code-review high` + `/security-review`（本轮含 runner/writer/web 交界 + 新锁模块，高风险面按升级条款考虑多视角），结论回填本文件
- 真模型 smoke 不在本轮验收内（铁律⑥，capstone → iter079）

## Implementation Notes

- **踩坑（铁律③/⑥相关，如实记录）**：P1-5 调试期间，一个临时 standalone 调试脚本忘了设 `OPENAI_MODEL=mock`（绕过了 `tests/__init__.py` 的强制 mock），触发 writer mock 流程时实际发起了真模型调用尝试——4 次 attempt 全部 524 超时失败、零成功完成、无产出写盘；log 残留在 `logs/llm_calls.jsonl`（error 记录）。教训：**任何 standalone 脚本必须显式 `OPENAI_MODEL=mock`**，unittest 之外没有安全网。该事件同时暴露 `.env` 当前指向的真模型端点存在超时问题（跑 capstone 前值得复核）。
- **P1-1**：`_coerce_score` 落地时确认真 crash 点是 `_repair_agent_review_dict:96` 的 `int(nan)`（ValueError）/`int(inf)`（OverflowError）且不在 try 内——json.loads 接受裸 NaN 字面量，生产可达；`_agent_weighted_score` 的 NaN 透传是第二层（fallback/synthetic dict 绕过 pydantic 时）。字符串分数在 weighted 层本来就能解析，真正的 fail-open 在 nesting 层（isinstance 丢弃 → score 兜底 7）。
- **P1-7**：`WorkspaceLocked` 不做成 `BookRunBlocked` 子类（会造成 workspace_lock↔book_runner 循环 import），改为 `run_write_book` 包装层 catch-and-reraise，同样达成零新退出码。`run_write_book` 拆成锁包装 + `_run_write_book_unlocked`（签名不变）。顺手项（服务 P1-7）：`main.py` 的 legacy `write` 与 `run-all` 写章段也拿锁（同为写章入口）。
- **P1-5**：writer 循环重排为 persist → summarize/rolling → 提案 → reports.append（`proposal_path` 后移）；新增 `persisted` 标志，已持久化章不再写误导性 partial。`prune_from_chapter` 加「无变化不落盘」守卫（fresh-write 每章调用不再空写文件）。readiness gap 检查收敛为「rolling 数据非空才启用」——手工搭建/迁移 workspace 无 rolling 属正常形态（铁律④），真实长跑从 ch1 起有条目不受影响。测试踩坑：裸 fixture 的 mock 稿必然 lint 失败 → 主 review 不可达（只有 shadow review 且异常被吞），对照组杀点改用 `count_chinese_chars` 首调点（persist 前）。
- **P1-4**：②空 state 校验放在 deactivate 循环**之前**（否则旧 active 条目已被灭活才 skip，图被改坏）；③注入改四字段投影（src/dst/relation_type/old_active_state）——提案指令本就只要求这些，timeline（无界部分）整体不进 prompt，条目边界截断 + 省略标记；①sidecar 语义 = 「runner 已对本章完成 advance 处置」（含 no-op/失败降级，与 run 不重试失败 advance 的既有语义一致），补偿只认 sidecar 缺失 + 提案在盘；`unapplied_auto_indexes` 用 `chapter_anchor()` 共享常量做精确比对（写入/判定两侧防漂移）。
- **P1-6**：`WorkspaceLocked`→`BookRunBlocked` 同款兼容思路——chapter_status 新键「双方都非空才比对」单独小循环，旧 4 键循环字节不动；readiness 的 tier 解析宽容降级（脏 env 由 preflight FATAL 与 run raise 负责报，readiness 不抢报）；`check_write_readiness` 加 `tier` 参数由 `run_write_book` 透传（readiness 独立调用走 env/默认）。
- **P1-2**：核实修正——`_log_call` error 路径本就带 request_meta（含 prompt 估算），真失真是 N 次重试只记 1 条 + 超时 response 无记录。修复后 `retry_error` 逐 attempt 入账、终态 error 条 token 置零 + `final_of_attempts` 防双计；聚合改逐 record 按 model 计价；mock 计价归零（既有测试零冲突）。语义迁移 ×1：`test_llm_client_streaming` 的「失败只在最终放弃记账」旧断言改为 retry_error+ok 两条（原命题——中流失败重试成功、partial 不泄漏——不变）。**测试铁律发现**：unittest 下 `config.load_dotenv_if_available` 每次调用强制 `OPENAI_MODEL=mock`（argv 探测）——env patch 打不过这道硬门；非 mock 路径测试要改 client 实例属性（`client.model`），standalone 脚本（argv 无 unittest）则完全没有这道防护、会真读 .env（见上方踩坑）。
- **P1-3**：config 层封顶只对「已知前缀且非 mock」生效——mock 是假模型无物理上限，封顶会改变 mock 回归行为（plot_planner 200K 在 mock 态被压到 128K 的坑，实施中发现并规避）；`min(raw, estimate)` 结构保证修正只减不增。models.yaml **未改**（task 块不带 model 字段、运行时 model 由 env 决定，静态改 64000 会误伤 gpt/claude 运行形态）——64K 口径由 config 层动态封顶实现，与计划的「改 yaml 8 处」是同目标的更优落点（scope 说明：行为等价于计划，且对未知模型更安全）。
- **P1-8**：anchor 检查改走 `load_continuation_anchor` 单一真源后暴露真·假阳性：workspace 态 yaml 的 anchor 根本不生效（load 只在 repo root 回落 yaml），旧检查却按 yaml 值放行。语义迁移 ×1：`test_preflight` 超长章用例的 fixture（max_tokens=5000/context_limit=100）恰是新 FATAL 要抓的矛盾配置，fixture 改自洽值（50/100）保原命题。
- **技债-2 设计修正**：origin 无条件优先会杀死 iter077 逃生门（planted_chapter 改正数重新武装）——初版实现被既有测试当场抓住。终版两轴语义：`continuation` → 无条件进闸门（防未来回灌毒化的钉子）；`source_book`/缺失/非法 → 走 planted 启发式（存量零迁移 + 逃生门保留）。
- **技债-1**：`classify_disposition` 纯函数下沉 chapter_status；`_is_resumable_stale_reject`/`_RESUMABLE_REJECT_FAILURES` 迁移后在 book_runner 留别名（test_iter077_stale_reject_resume 等 import 面零改动）；run/readiness 双循环只换判定、动作原地。一处显式统一：approved 与 caveat_approved 同真的病态盘面（正常流程不可达——caveat 章 verdict 恒 Reject），旧 readiness 先看 caveat、旧 run 先看 approved，classify 取 run 顺序。book_runner 全家桶 98 测试 + 全量回归零断言改动（等价性证明）。

## Acceptance Result

- **工程验证（canonical）**：`.venv/bin/python3 -m unittest discover -s tests` = **1622 tests OK**（需要允许本地 127.0.0.1 测试端口；裸沙箱会拦 `test_novel_client`），`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` = exit 0（内部同样 **1622 tests OK**，随后 normalize/split/auto-pipeline/status/manifest/report/cost 全跑通），`.venv/bin/python3 main.py preflight` = `PREFLIGHT: warn`/无 FATAL（WARN 均为当前 `.env` 模型配置、cache provider、预算默认值提示），`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` = `PREFLIGHT: ok`/无 WARN。`git diff --check` 与 `.venv/bin/python3 -m py_compile main.py src/*.py src/web/*.py tests/*.py` 均通过。
- **mock 25 章长流程五关**：本轮收官过程中已完成 PASS-1 start 25 章、PASS-1b `write-readiness --resume-from 16` 边界回归、PASS-2 resume 零新 LLM 调用、PASS-3 supervised resume-first 收口、PASS-4 双 `write-book` in vivo 竞锁（被拒方 exit 4 且报错含 holder 信息）。这组证据覆盖 P0-1 逃生门、P1-4 补偿、P1-5 prune、P1-7 写锁。
- **铁律⑨ /code-review high 等价执行**：8 个 finder 视角（逐行、被删行为、跨文件、复用、效率、altitude、约定、简化）+ 主对话 inline verify。第一轮确认并直修 8 项：reaper argv[1:] 尾部比对、readiness tier 意图、SUPPLEMENT 两出口补偿、entity recency 守门、伏笔缺 `planted_chapter` fail-closed、负 timeout 拒收、标量 JSON 残行计脏行、Web/auto-pipeline 写锁覆盖。
- **铁律⑨ 高风险追加双视角**：并发/锁/driver 视角确认 4 个 P1 并直修：`cmd_stop` 收割后 reload 前先落盘 child 清理结果；`drive-book resume --tier` 真正覆盖 persisted tier；`run-all` 与 `auto-pipeline` 从整条流水线入口拿写锁（不是只锁最终写章段）；CLI/Web review 入口也拿写锁，避免与长跑归档/重写交叉。保留 P2：reaper 的 argv[1:] 尾部匹配仍可能被极端 wrapper 形态绕过；`_STOP_REQUESTED` 是进程级 flag，CLI 正常退出无风险，嵌入式复用场景可后续在 run entry reset。
- **/security-review**：确认无 `.env`/真实 API key/`data`/`outputs`/`小说txt` 入提交；`rg "sk-"` 命中均为测试假 key 或历史文档占位。唯一 P1 为 `llm_client._log_call` 会把 provider/proxy 原始异常写入 `logs/llm_calls.jsonl`，在 iter078 `retry_error` 逐 attempt 入账后暴露面更大；已新增 `_sanitize_error_text`，统一脱敏 configured key、Bearer token、`sk-*` 形态与 prompt/messages/input/content 片段，并补回归测试。
- **真模型 smoke**：未跑（铁律⑥）。iter079+ capstone 仍需用户明确授权。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/reviewer.py` | P1-1：`_coerce_score` 新增；`_repair_agent_review_dict` 子分数嵌套/嵌套 scores 清洗改 coerce（修 NaN crash + 字符串 fail-open）；`_agent_weighted_score`/`_weighted_panel_score` isfinite 护栏；判定处 non-finite → 0.0 + `score_warning` 留痕 |
| `src/workspace_lock.py` | P1-7 新增：fcntl.flock 非阻塞独占写锁 + holder json + `WorkspaceLocked`（选 flock 理由见模块 docstring） |
| `src/book_runner.py` | P1-7：`run_write_book` 拆锁包装 + `_run_write_book_unlocked`；P1-5：fresh-write 前 prune + readiness `rolling_summary_gap`；P1-4①：`_mark_advance_applied`/`_compensate_missing_advance`/sidecar + skip 分支补偿 + 归档 suffix；P1-6：`_expected_write_model` + 三处 `_run_context` 接线 + readiness `tier` 参数；技债-1：处置判定改消费 `classify_disposition`（谓词迁移留别名） |
| `src/writer.py` | P1-5：stage 重排 persist→summarize/rolling→提案 + `persisted` 标志；P1-4③：`_propose_entity_advance` 四字段投影 + 16K 条目边界截断；P1-6：`_run_context` 加 model/review_tier + 调用点接线 |
| `src/chapter_status.py` | P1-6：新键「双方非空才比对」（meta + 外审两侧）；技债-1：`ChapterDisposition` 枚举 + `classify_disposition` + `is_resumable_stale_reject`/`RESUMABLE_REJECT_FAILURES` 单一真源 |
| `src/entity_advance.py` | P1-4②：`_apply_selected` 空 new_state 统一 skip（deactivate 前）；P1-4①：`chapter_anchor()` 共享常量 + `unapplied_auto_indexes` 补偿去重 |
| `src/chapter_summary.py` | P1-5：`prune_from_chapter` 无变化不落盘守卫 |
| `src/cost_estimator.py` | P1-2：`MODEL_PRICING` 前缀查表（mock=0/未知回落+单次 WARN）+ `cost_cny(model=)` + 聚合逐 record 计价 + `dirty_lines` 透出 |
| `src/llm_client.py` | P1-2：重试循环逐 attempt 记 `retry_error`；终态 error 条 `zero_tokens` + `final_of_attempts` 防双计；security-review P1：`_sanitize_error_text` 脱敏 provider 异常中的 key/token/prompt payload |
| `src/context_budget.py` | P1-3：`count_tokens` 对 deepseek 前缀 `min(raw, cjk*0.75+other*0.4)`（method=`tiktoken_cjk_capped`） |
| `src/config.py` | P1-3：`_known_context_cap` + `get_model_config` 已知前缀（非 mock）context_limit 封顶；P1-8：`_env_float` 补 isfinite |
| `src/preflight.py` | P1-3：`_check_context_limits` 加 warn lane（yaml>上限 WARN 生效值 / <上限 INFO）；P1-8：`_check_review_tier` FATAL+INFO、LLM_REQUEST_TIMEOUT WARN、max_tokens↔context_limit FATAL/WARN、anchor 检查改走 `load_continuation_anchor` 单一真源（workspace 态 yaml 假阳性点破 + manual 优先回显） |
| `src/foreshadowing.py` | 技债-2：播种带 `origin: source_book`；`is_boundary_item` 两轴判定（continuation 硬进闸门 / source_book 与存量走 planted 启发式保逃生门） |
| `src/auto_pipeline.py` | P1-7 追加：`run_auto_pipeline` 整条流水线入口拿写锁，避免 prepare/write 混跑；内部实现下沉 `_run_auto_pipeline_unlocked` 防自锁 |
| `main.py` | P1-7：legacy `write`、`run-all` 全链路、CLI `review`/`review-chapter` 拿锁（exit 4）；write-readiness 加 `--tier` |
| `src/web/jobs.py` | P1-7：`_step_write_book` 传 `lock_source="web-job"`；Web review-chapter 与 auto-pipeline lock conflict 映射为 blocked/workspace_locked |
| 新测试 ×5 | `test_iter078_workspace_lock.py`（7）/ `test_iter078_rolling_order.py`（7）/ `test_iter078_entity_compensation.py`（12）/ `test_iter078_cost_ledger.py`（7）/ `test_iter078_disposition_matrix.py`（14） |
| **收官审查修复批**（铁律⑨，8 项直修 + 双视角 P1 追加，详见 Acceptance Result） | `src/book_driver.py`（reaper argv[1:] 尾部比对 + readiness step 透传 --tier + stop 收割结果先落盘 + resume tier override）/ `src/book_runner.py`（readiness 无 tier 意图不冒充默认值；SUPPLEMENT 两出口补 advance 补偿）/ `main.py`（write-readiness 加 --tier；run-all/review/review-chapter 写锁）/ `src/auto_pipeline.py`（全链路写锁）/ `src/entity_advance.py`（补偿 recency 守门 + `_anchor_chapter_no`）/ `src/config.py`（`_env_float` 拒负数）/ `src/cost_estimator.py`（标量 JSON 残行计脏行 ×2 处）/ `src/foreshadowing.py`（planted_chapter 键缺失 fail-closed）/ `src/web/jobs.py`（draft-once-dev、review-chapter、auto-pipeline 写锁覆盖）/ `.gitignore`（workspaces/*/write.lock 等测试残留） |
| 收官修复批测试 | `tests/test_iter078_finish_review_fixes.py`（12：tier 意图 ×3 / SUPPLEMENT 补偿 ×1 / recency ×3 / 伏笔缺键 ×2 / 负超时 ×2 / 脏行 ×1）+ `tests/test_iter077_orphan_reaping.py` 增 argv[0] re-exec / ps 失败收割 / stop 持久化用例 + `tests/test_iter078_cost_ledger.py` 增 error 脱敏用例 + `tests/test_iter078_workspace_lock.py` 增 auto-pipeline/review lock 用例 + `tests/test_book_driver.py` 增 resume tier override 用例 |
| 扩展测试 ×9 | `test_reviewer_subscore` +5 / `test_reviewer_tier_aggregation` +2 / `test_web_jobs_dispatch` +1 / `test_entity_advance` +1 / `test_book_runner_review_context` +6 / `test_context_budget` +9 / `test_preflight` +11 / `test_foreshadowing` +4 / 语义迁移 ×2（`test_llm_client_streaming` 重试账本、`test_preflight` 超长章 fixture） |

## 不在本轮范围

- P2 全部继续顺延：双 resume TOCTOU、watchdog `pid_is_driver` 判别式过宽、supervise.pid trap 缺 INT/TERM、RESET_SECONDS/MAX_RESTARTS、Web budget 0.0 语义、content:null 误判、score 不 clamp（外审侧）、extract_json_object 切片、debate log 清洗非原子、SIGTERM partial 承诺、--book 拼错静默建目录、llm_calls.jsonl O(n²) 重读、drama_agents 死配置等
- rolling gap 自动回填（需 LLM 调用，破坏 resume 零调用契约；操作者可 --force 重写）
- 失败 attempt 的 response token 估算（超时场景结构性不可知，由 budget reserve safety_factor 吸收，声明为已知残留低估）
- plan-chapters / debate 等非写章 step 加锁（scope 收敛，写章双写才是本案）
- 真模型 capstone 实跑（→ iter079，铁律⑥需用户授权）
- Aeloon 深色模式 / drama 站 / AI 绘画 client 等既有 backlog 候选

## Notes

- **铁律⑦补记（收官审查「约定」视角发现）**：`tests/test_book_runner.py` 与 `tests/test_book_runner_retry_progress.py` 头部的 `from __future__ import annotations` 是本轮顺手修（verify.sh 卫生，PEP604 在旧解释器下的 import error），当时未入文件变更汇总——在此诚实补记。该项不改变任何被测语义。
- **verify.sh 解释器漂移（环境性，非本轮引入）**：裸 `python3` 现解析到 Homebrew 3.13（无 pydantic），verify.sh 直跑报 201 个 import error（旧口径是 system 3.9 的 3 个 error）。规避：`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` = exit 0 全绿。canonical 口径维持 .venv 全量 unittest。
- **收官审查最重要发现（已修）**：`_reap_orphan_child` 的 argv 整串精确比对在 macOS framework Python 下**永不匹配**（进程自我 re-exec 改写 argv[0]）——iter076/077 搭的 supervisor 自动恢复链在本机 100% 失效且清掉孤儿指针（视角 A 本机实证）。capstone 前必修项，已改 argv[1:] 尾部比对 + 真进程回归钉死。
- **readiness tier 指纹不对称（已修）**：P1-6 的 tier 指纹只在 run 侧有意图来源，readiness 三个外部调用方（CLI/driver step/Web）都拿 DEFAULT_TIER 冒充期望值——`--tier high` 的长跑会被新一轮 attempt-1 readiness 逐章误 BLOCK（capstone 推荐 tier=mid 恰好掩盖它）。已改「无意图不比对」+ CLI/driver 透传 `--tier`。
- **审查后未修风险（P2/技债，下一轮候选）**：
  - writer「persist 后、提案落盘前」死亡窗口：章 approved 但提案不存在 → 补偿无源可放（P1-5 顺序调换的残留缺口，仅 rolling gap 有 warning，entity 侧无告警）——候选：提案落盘挪到 persist 前或补「提案缺失」readiness warning。
  - reaper 仍用 argv[1:] 尾部比对作为「同一个 write-book step」判别，已修 macOS framework Python argv[0] 变形，但极端 wrapper/launcher 形态仍可能触发 P2 误判；候选：state 记录 step token/env nonce 并让 child 回写 heartbeat。
  - `_STOP_REQUESTED` 是 module-level flag，真实 CLI 收到 stop 后进程结束，风险低；嵌入式复用同一 Python 进程时可在 driver run entry reset，避免测试式复用残留。
  - pre-iter077 的 halt 残迹无 `panel_halted` 标记，升级后 resume 会按 stale 归档重写（一次性迁移形态；升级后首跑前人工核查留盘 Reject 章）。
  - mock 计价归零使预算闸在 mock 长跑中不可达（budget 管道接线错误要到真模型才暴露）——候选：mock 假单价演练开关。
  - `_known_context_cap` 子串匹配对第三方路由（openrouter/deepseek）过保守封 64K（有 WARN 回显，方向安全）；preflight `WRITE_REVIEW_TIER` FATAL 扩面到非写链路（fail-closed 可辩护）。
  - Web 章节手工编辑端点（iter050）不拿 P1-7 写锁——本轮锁范围=「批量写者互斥」，单章手工保存与 CLI 长跑交叉属已知边界，候选下沉 `workspace_reserved` 桥接 flock。
  - 结构性技债批（简化/复用/效率/altitude 视角，均记录未修）：caveat 分诊块两处同构抽 `_triage_panel_reject`；run_context 指纹比对 4 份近似循环抽 helper；`_snap`/`_snapshot` 双名与 5 键 payload 手抄；`expected+chapter_status` 组合三处手抄；`_next_unapproved_chapter` 仍手搓 approved-only 视图（五分类下沉的残余第三链）；`_RESUMABLE_REJECT_FAILURES` 别名 src 内零消费者可删；`workspace_lock._write_holder` 复用 `utils.write_json`；`_propose_entity_advance` 截断复用 `entities._truncate_state_text`；model 家族匹配三模块三份语义收敛共享 matcher；`_cjk_capped_estimate` 改预编译正则、`_pricing_for_model` 加 memo、账本增量读 offset；`_panel_block_policy` 下沉叶子模块消惰性 import；`include_boundary` 参数 test-only。
  - 补偿用**当前** plan 校验旧提案（replan 后 conflict 判定漂移）——recency 守门已把可倒退面收窄到前沿章，残余形态影响有限，记录即止。
- **capstone（iter079+ 实跑）跑前清单增补**（沿用 iteration_077 Notes 清单，另加）：①升级后首跑前核查留盘 Reject/halt 残迹；②混有 mock 残留日志的 workspace 重标定 `--budget-cny`（mock 行现在计 0，retry_error 逐笔入账会比历史经验更早触发预算闸）；③`--tier` 非 mid 时确认全链路（本轮已修 readiness 侧）。
- **后续候选**：iter079-083 短剧（drama）模块批次（roadmap 文档已就位，novel 真模型 capstone 顺延至该批次后）。
