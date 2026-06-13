# Iteration 053 — 中间产物起点校验 + 写手 canon 锚定增强 + longzu 复仇局（计划稿）

> 承接 iter052 真模型实跑的三条实测发现（2026-06-12，全部有现场证据）：
> ① **主因**——5月30日"四部曲结局后"时代的陈旧 debate outline 在起点已改为 `longzu_3_3_ch024` 后仍被 plan-chapters 信任，重新生成的章纲整体跳线到错误时间线，写手九稿全灭（panel 5.68→6.16 横盘）；outline/decisions 等 **LLM 中间产物不受任何起点一致性校验**（F6 只管 plan↔起点指纹）。
> ② **次因**——写手把预训练记忆里的原著后期设定写进正文（"路鸣泽四分之一生命交易"，起点处只有"愿意交换么"悬念）；`start_safe_knowledge`（047b）管 KB 注入、管不住模型记忆；现行笼统反馈回灌对此无效（九稿分数横盘实证）。
> ③ **小缺口**——premise 扩写稿 6 字段无非空校验（shudian052 实测 genre_tone/world_notes/central_conflict 空着落盘，靠 personas 兜底未出事；2026-06-12 盘面复核 arc_hints 同为空）。
>
> **拍板结论（用户，2026-06-12）**：① 三轨照单全收（a 中间产物校验 / b canon 锚定增强 / c longzu 复仇局）；② 053c 预算上限 **¥12**；③ 计划稿在 052 实跑收尾期并行起草，**053 实施等 052 收官后开始**（052 驱动器子进程从磁盘热加载代码，跑动中改 src/ 会污染 F7 对照——经用户确认的隔离纪律）；④（实施启动时追加）**053c 提速降本授权**——不影响质量前提下可换更快模型档（如 GPT-5.5-low）、票数闸降至 **3/5**。落地方式：保 7.5 分数线只降票数（review_tier 新增 env 覆写，**不**整体换 `--tier low`——low 档会把分数线连降到 6.5，违背"不影响质量"前提）；模型换档经 models.yaml 补 `model_env` 钩子按任务粒度控制（config.py:104 现成机制），写手任务若换档则 ch1 出稿即人审对照；⑤（2026-06-13 /goal 授权）**真模型预算 ¥50+ 一次性授权、整轮迭代含 053c 由 agent 自主完成**——铁律⑥时点确认成立；ch1 段间人审由 agent 按决策表执行；**模型档全程保持 052 同款 gpt-5.5-high 默认档、不动用 model_env 换档**（双重理由：铁律⑨ B-H1 计价豁免——cost_estimator 单价表单一价，换档会让 ¥12 预算闸计价失真；以及 panel 基线可比性——验收阈值全部建立在 052/6月5日 同模型口径上）；053c 仍按拍板②的 ¥12 上限跑，¥50 余量留给可能的二轮/补跑。
>
> **本档已过 2026-06-12 四维 subagent 审核**（代码锚点核实 × 052 文档口径核对 × 盘面状态实勘 × 对抗设计审查），采纳项以"审查 A/B/C/D 编号"标注于各节，初稿勘误汇总见 Notes。

## Context

iter052 的 longzu 实跑暴露了一条干净的因果链：清场时为省 debate 成本保留了旧 outline（驱动器"outline 存在即跳过 debate"的省钱设计）→ ensure-plan `--force` 重规划时 planner 信任了这份起点错位两代的大纲 → 章纲 ch1 从"3E 考场"跳线到"心神机库倒计时" → 写手按错误图纸施工，怎么重写都过不了"当前状态=3E 前"的评审。同日 shudian052（自创书）同一条流水线 8.0–8.5 一次过，单变量对照成立：**流水线无恙，缺的是中间产物的时间线护栏**。

护栏缺口的本质：F6（`start_point.enforce_consistency`，051b 集中、052 真模型双路径验证）守住了 chapter_plan ↔ 起点的指纹一致性，但 debate 的三件套（outline.md / decisions.json / debate_log.jsonl）**落盘时不记录起点、消费时不校验起点**——`plot_planner.generate_chapter_plan` 直接 `outline_path.read_text()`（plot_planner.py:75），旧大纲与新起点的错配静默穿透。053a 把 F6 的指纹哲学推广到中间产物层。

**审核补充（2026-06-12 盘面实勘）**：毒链不止 outline——`workspaces/longzu/outputs/debate/chapter_plan.json` 现存按毒 outline 生成的 10 章跳线 plan（ch1"黑色机库里的倒计时"），且起点此后未再变过，其 F6 指纹四码全绿；driver 的 ensure-plan guard（book_driver.py:347-364）见 plan 条数 ≥ plan-target 即判 plan_sufficient 跳过重规划。所以 053a 必须连带补 plan↔outline 的血统链，053c 第 0 步必须连 chapter_plan.json 一起归档——否则重 debate 出干净新大纲后，旧毒 plan 直通写手，¥12 原样重演 052 事故，还会把"指纹一致"的绿灯误读成"预训练泄露比预想深"的假证据（审查 A1/C3）。

次因（预训练剧透泄露）独立存在：即便图纸干净，写手仍可能掏记忆里的后期设定（052 实跑中"路鸣泽交易"并不在章纲里）。053b 从两头夹击：写作前的硬约束声明 + 被拒后的结构化违例回灌（现行 `_review_feedback` 把 block 级拒因和普通建议混拼成一段文字，writer.py:1027-1061，模型分不清"禁令"与"可选优化"）。

## Plan（三轨拆分）

1. **053a 中间产物起点一致性校验**（主轨，治主因）
   - **落盘侧**：`run_debate()` 收官写 decisions.json 时注入元数据：`start_chapter_id` / `start_point_fingerprint`（复用 `start_point.start_point_fingerprint()`，start_point.py:178）/ `outline_sha256`（同批 outline.md 的内容哈希，强绑定配对文件）/ `generated_at`。**注入方式：写盘前以普通 dict 键钉入（debater.py:232），`DebateDecisions` schema（schemas.py:327）不动**——该 schema 是 `complete_json` 发给 LLM 的结构契约（debater.py:656-672），加字段会进 LLM 契约、招幻觉假指纹（审查 A8）；存量消费方（web plan_view / observability / static）已核实全部 dict 式读取，新增键零破坏。**写入顺序倒置：outline.md 先落、decisions.json 后落作 commit 标记**——driver step 超时 SIGTERM 杀在两写之间时（smoke051 实录过 debate 超时），不会留下"新鲜指纹 decisions + 旧 outline"的错配窗口（审查 A2）。
   - **消费侧**：新增 `start_point.outline_consistency_failures(decisions: dict) -> List[str]`（集中进 F6 同一模块，延续唯一真源哲学），校验两层：起点指纹匹配 + `outline_sha256` 与盘上 outline.md 实际内容匹配（堵手改 outline / 半写错配，审查 A2）。`plot_planner.generate_chapter_plan` 读 outline 前调用：
     - decisions **有指纹且任一不匹配 → 硬拦**（拒绝规划；报错文案区分"起点真的变了"与"可能只是重切章/normalize 改了行号"两种情形并给对应处置指引，避免误报把用户训练成习惯性逃生，审查 A7）——052 事故场景，fail-closed；
     - decisions **无指纹、或 decisions.json 缺失但 outline.md 存在 → 一律 warn 放行**（两条路径显式归入同一分支并各自 mock 钉死——否则删一个文件就能绕过硬拦，审查 A2；输出+事件留痕"建议 debate --force 刷新大纲指纹"）——fail-open 护存量，先例 kb_view 047b；warn 同步进 web 工作台一行提示（plan_view 已读 decisions.json，成本极低；detached driver 的 step log 没人看，审查 A5）；
     - `--allow-stale-outline` 显式逃生门（plan-chapters 与 drive-book 均透传）；放行时在 plan metadata 记 `stale_outline_acknowledged` + 时间戳，留审计痕（审查 A9）；
     - write_chapters 的就绪检查同步调用，**warn 级不拦**——writer 自己也直读 outline 注入每章 prompt（writer.py:68-78、:625），不加这条则写作面完全在护栏外（审查 A4）。
   - **plan↔outline 血统链（审查 A1，053c 的隐式硬依赖，随 053a 落地）**：`generate_chapter_plan` 落盘 chapter_plan.json 时记录所读 outline 的 `outline_sha256`；F6 `enforce_consistency` 扩一条"plan 所记哈希 ≠ 盘上 outline"的失败项（warn 级起步）。不补这条，debate 重跑后下游旧 plan 自动陈旧而无人察觉——052 的缺口原样上移一层（盘面现存毒 chapter_plan.json 即实证，见 Context 审核补充）。
   - **debate force**：`run_debate(topic="", force=False)` 新增 force 参数——force 时归档（非删除）outline.md / decisions.json / debate_log.jsonl 到 `outputs/debate/snapshots/<ts>/` 再全新辩论；CLI `debate --force` + web `_step_debate` 透传（jobs.py:398）。**done_keys 防洗白（审查 A3）**：debate_log.jsonl 首条记录落起点指纹，非 force 续跑（debater.py:128-160）前校验，不匹配 → 拒绝续跑并提示 force——否则"outline 缺失 + 旧 log 在"的组合会用旧起点时代的 transcript 重建 outline 并盖上新鲜指纹。
   - **驱动器联动（缺省 fail-closed，审查 A6）**：debate 跳过逻辑升级三态——outline 存在且指纹一致 → 跳过；指纹不匹配 → **缺省 blocked 停人审**（事件 `debate_stale_outline_blocked`），对齐 052 自家哲学"blocked 默认停人审，不自动 --force"（自动重辩 ≈ ¥1–2 且 debate 步前无预算闸，静默烧钱反目标——初稿"自动重跑"设计否决）；`--force-debate` 启动参数显式选择重辩（等价 debate --force，且**联动归档失效下游 chapter_plan.json**——否则 ensure-plan guard 见旧 plan 条数够数直接跳过重规划，A1 事故路径复活）。旗标优先级明文化：`--skip-debate` 与 `--force-debate` 互斥报错；`--allow-stale-outline` 仅放行 plan 侧校验，不改 debate 步行为。
   - mock 测试：指纹+outline 哈希写入与写入顺序断言、匹配/不匹配/无指纹/decisions 缺失四态、plan 硬拦与逃生门审计留痕、血统链记录与校验、log 指纹续跑拒绝、driver 三态（含缺省 blocked 与 --force-debate 联动失效 plan）、debate force 归档（预估 +20 例）。

2. **053b 写手 canon 锚定增强**（副轨，治次因）
   - **反剧透硬约束（条件注入，铁律④）**：`_write_prompt` 的 system_prompt 末尾（writer.py:593-613 区域）追加锚定块，**文案用时间锚定而非注入锚定（审查 B1）**——给出起点坐标，大意："本次续写起点为 <start_chapter_id>（起点状态一句话）；原著**在该起点之后**发生的事件、设定揭示、人物关系变化一律视为不存在，禁止引用或暗示；起点**之前**的原著事实可正常使用；允许原创不冲突的新元素"。不用"未注入的设定一律视为不存在"措辞——knowledge 注入存在截断窗口，那会连起点前、没挤进窗口的合法 canon 一并误杀，fidelity 反降。**仅在 `start_point.get_start_chapter_id()` 非空（续写已出版书）时注入**；无起点（premise 自创书）prompt 逐字节不变（自创书无"原著记忆"可泄露，注入只浪费 token）。另挂独立 env 开关（命名循项目 env 惯例，实施时定），供 053c 分段单变量对照与紧急回退。
   - **拒因结构化回灌**：`_review_feedback`（writer.py:1027）升级为分层模板——`## 评审标记的 block 级违例（逐条禁令，本稿必须规避）`（按 `issues[].severity == "block"` 过滤，含 reviewer/rule_id/anchor/message，**不再限定该评审整体 verdict=Reject**，修复现状 block-but-Approve 漏灌缺陷，writer.py:1032）置顶 + `## 必须处理的修改建议`（major + rewrite_suggestions）+ `## 可选优化` 其后。**`_blocking_reasons`（writer.py:1064）同口径同步修改**——只改 `_review_feedback` 会让回灌清单与 last_failure/web 失败面两套口径（审查 B2）。整体 Approve 即过闸的主路径行为零变化（writer.py:266-268 的 break 先于 feedback 重算，"过闸稿被要求重写"的语义矛盾不存在），逐字节断言钉死。
   - **跨 retry 周期反馈播种（审查 B3，从初稿"实施时核"升格为交付物）**：实勘结论——book_runner 每个 retry 周期先归档全部产物含 review.json（book_runner.py:178-187、611-630）再调 write_chapters，而 write_chapters 每章 `feedback = ""` 起步（writer.py:154），外审 block 拒因（gf_longzu_014/015，恰是 053c 指定的回灌效果探针）随归档消失，下一周期第一稿完全失忆；052 九稿横盘的"周期间断链"部分由此解释。修法：retry 周期 >0 时把上一周期的 block 清单（复用同一分层模板）作为 write_chapters 初始 feedback 喂入。不修这条，053c 的 rule_id 探针只测得到半条链路。
   - **premise 扩写非空校验（搭车，独立 commit 便于单独回滚，审查 D1）**：`expand_premise` 落盘前校验 6 字段非空——空字段自动重试一次（带"以下字段缺失必须补全"提示），仍空则照常落盘但记 `_incomplete_fields` 标记 + 工作台 stage① 显示"建议补全"。标记放 record 层而非 fields 层（`load_expansion` 用 `PremiseExpansion(**record["fields"])` 反序列化，premise_expansion.py:116-120，塞 fields 层直接炸），并断言标记不进 `expansion_prompt_block`（debate prompt 消费它，debater.py:84-86）。
   - mock 测试：锚定块条件注入（有起点注入且含起点坐标 / 无起点逐字节不变 / env 开关关闭逐字节不变）、回灌分层格式与 block-but-Approve 修复、`_blocking_reasons` 同口径、Approve 主路径零变化、跨周期播种（周期 2 第一稿 feedback 含上一周期 block 清单）、扩写空字段重试与 record 层标记不进 prompt（预估 +15 例）。

3. **053c 收官实跑：longzu 复仇局**（验收载体，¥12 上限）
   - **回答 052 留下的悬念**："干净图纸下龙族到底能不能写"——6月5日 plan（"听力考试"）压线 7.5 通过的先例支持能过。
   - **第 0 步（零 LLM 成本）：清场 + 断言（审查 C3，归档清单较初稿扩容）**，全部留档不删：① debate 三件套（5月30日 outline/decisions/debate_log；053a 落地后亦可交 `--force-debate` 统一归档，手工归档则务必**三件同批**，防 done_keys 洗白）；② **chapter_plan.json**——盘面现存的 10 章跳线毒 plan，起点未变故 F6 全绿，不归档则 ensure-plan guard 直接复用它（见 Context 审核补充）；③ 052 失败残留：drafts 下 ch1 草稿+meta、rolling_chapter_summary.json、last_failure（残留草稿会触发 readiness 的 existing_output block；rolling summary 会把失败稿剧情喂给 planner/writer）。归档后**断言目录态干净**，确认起点 `longzu_3_3_ch024`、preflight 零 FATAL。
   - **第 0.5 步（拍板④落地，随 053a/b 代码一并实施的两个小项）**：① review_tier 新增 `WRITE_REVIEW_MIN_APPROVE` env 覆写——只降票数，分数线随 tier 不动，夹紧 1–5，缺省/非法值回退 tier 预设（铁律④回退契约）；② models.yaml 给 write/review/debate 补 `model_env` 钩子（`WRITER_MODEL`/`REVIEWER_MODEL`/`DEBATER_MODEL`，复用 config.py:104 现成机制，零代码改动）。
   - **跑法（分段单变量，审查 B4）**：初稿 053a+053b 同时生效是混合实验——ch1 过闸归因不了"干净图纸"，ch1 连拒也分不清是预训练泄露还是 053b 文案过度保守。借 052 F7 对照同款分段暂停机制拆开：
     - 段一（ch1，仅 053a）：`drive_book.sh --book longzu start --chapters 5 --segment-size 1 --pause-after-segment 1 --plan-target 5 --force-debate --require-start-point --budget-cny 12 --tier mid --detach --confirm-real-run`，外加 `WRITE_REVIEW_MIN_APPROVE=3`（票数闸 3/5、分数线 7.5 不动，拍板④）；canon 锚定 env 开关**关闭**——重 debate（新大纲带指纹）→ 重 plan（血统链+校验生效）→ ch1 只吃干净图纸。模型档按需经 `WRITER_MODEL`/`REVIEWER_MODEL`/`DEBATER_MODEL` 覆写。
     - 段二起（ch2–5，053a+053b）：人审 ch1 结果后**开启**锚定与新回灌，resume 续跑（resume 默认清零 pause_after_segment，book_driver.py:716-719），053b 效果与 ch1 形成段间对照。
     - 旗标核实更正：包装层 `drive_book.sh` **接受** `--confirm-real-smoke` 并映射为 `--confirm-real-run` + 确认闸（drive_book.sh:24-45）；python 入口只认 `--confirm-real-run`（main.py:325）——初审"旗标不存在"的勘误只对 python 入口成立，两种写法实际都通。`--pause-after-segment` 已核实存在（main.py:321）。
   - **验收判定（决策表，审查 C2——替代初稿"怎么跑都算过"的判定真空）**：
     | 结果 | 判定 | 下一步 |
     |---|---|---|
     | ch1 过闸，且 ch1–5 Approve ≥ 3/5、panel 均值 ≥ 7.5（prose/plot 分轴不低于 6月5日基线，防 fidelity 提升掩盖文笔回退） | 053 全验收通过 | capstone 立项解锁 |
     | ch1 过闸，ch2–5 因 fidelity **之外**的轴（prose/AI 句式等）失守 | 053a 验收通过，053b 存疑 | 053b 二轮调文案 |
     | ch1 fidelity 连拒（干净图纸假说证伪） | 053a 凭指纹/血统/留痕证据**单独**验收；证伪是有效结论，不算验收失败 | 证据回流 053b 二轮 |
     | 预算中断提前止跑 | 以实写章数为分母重判并注记 | 视余额决定补跑 |
   - **口径注记（拍板④）**：3/5 票闸下的 Approve 率与 052 的 4/5 口径不可直接对比，跨轮对照以 panel 分数轴为准（分数线 7.5 未动）；6月5日基线为 plan 级 Approve，不受票数口径影响。
   - 预算可行性（052 双载体实测对标：longzu 15 章段 ¥6.40/92 calls；shudian052 7 章 ¥11.10，其中 debate 44 calls ≈¥2.4）：debate ≈¥2.4 + plan ¥0.3–0.5 + 5 章 × 1–2 稿 ≈ ¥6–9.5，最坏路径（ch1 三周期连拒）仍 ≤ ¥12；segment-size 1 顺带让 driver 级预算总账逐章生效（初稿单段配置全程只查一次，审查 C1）。
   - **票数闸形态预判（052 收官新输入）**：052 段二重试主因是票数闸边界拒（首稿 panel ≥7.94 全过分数线、被 2/5 票打回，首过率 2/7，每次边界重试 ≈¥0.6）。053c 若 ch2–5 以同形态失守（panel 不低于基线、仅票数不够），归 052 顺延的"票数闸阈值观察"轨，**不计入 053b 文案副作用判定**——决策表第二行的"失守"以拒因轴为准。
   - **操作者竞态纪律（052 暗礁①实录）**：段一 pause 人审期间禁止计划外人工 resume（052 实跑 22:09 的计划外 resume 曾跳过 F7 切换步）；段二 resume 时 canon 锚定 env 开关在命令行显式设置，并核实经 drive_book.sh → detach 子进程透传。
   - 实跑前按铁律⑥再次确认时点。

## 关键设计决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| 指纹存放位置 | decisions.json 写盘前以普通 dict 键注入元数据（含 outline_sha256）；`DebateDecisions` schema 与 outline.md 均不动 | outline 是给 LLM 读的散文体，塞 front-matter 会进 prompt；schema 是 complete_json 的 LLM 契约，加字段招幻觉假指纹（审查 A8）；decisions 与 outline 同批落盘并以内容哈希强绑定（审查 A2） |
| 校验失败分级 | 有指纹不匹配=硬拦（052 事故场景）；无指纹/decisions 缺失=warn 放行（存量兼容）；`--allow-stale-outline` 逃生+审计留痕 | 全 fail-open 等于没修（052 的毒 outline 恰是无指纹的——属"指纹机制出生前"存量，053c 第 0 步单独清场）；硬拦覆盖的是未来全部**起点身份**错配——KB 重建/facts 修订/personas 重绑等上游变更不在指纹范围，明示不过度承诺（审查 A7） |
| 校验函数归属 | `start_point.outline_consistency_failures()`，不散落 plot_planner | F6 唯一真源哲学（051b）：起点一致性全家桶集中一个模块 |
| plan↔outline 血统链 | plan 落盘记 outline_sha256，F6 扩 warn 级校验；driver 重辩联动失效旧 plan | 不补则 debate 重跑后旧 plan 静默陈旧，052 缺口原样上移一层——盘面现存毒 chapter_plan.json 即实证（审查 A1） |
| debate force 语义 | 归档三件套再全新辩论，不是断点续跑；debate_log 带起点指纹，续跑前校验 | done_keys 续跑会让"重跑"静默变"跳过"（debater.py:128-160）；旧 log 重建 outline 再盖新指纹的"洗白"路径一并堵死（审查 A3）；归档保毒源证据可考 |
| driver 遇陈旧 outline | 缺省 blocked 停人审，`--force-debate` 显式重辩（初稿"自动重跑"否决） | 对齐 052 哲学"blocked 默认停人审，不自动 force"；自动重辩静默烧 ¥1–2 且 debate 步前无预算闸（审查 A6） |
| 反剧透约束 | 时间锚定文案（禁起点**之后**，不禁起点前）+ 仅起点存在时注入 + env 开关；无起点逐字节不变 | 铁律④回退契约；"注入锚定"会误杀没挤进 knowledge 截断窗口的起点前合法 canon，fidelity 反降（审查 B1）；env 开关供 053c 单变量对照 |
| 回灌分层 | block 禁令置顶 + major 建议 + 可选优化；`_review_feedback` 与 `_blocking_reasons` 同口径双修 | 052 九稿横盘实证笼统反馈无效；模型需要"禁令"与"建议"的显式区分；单修一处会造成回灌与失败面两套口径（审查 B2） |
| 053c 只跑 5 章、分段跑 | 不搭 30 章 capstone；ch1 仅 053a，ch2–5 加 053b | 回答"干净图纸假说"5 章足够，但归因需要单变量（审查 B4）；capstone 仍单独立项（052 顺延口径不变） |

## 实施备注（暗礁预警）

- **实施前置依赖：052 收官**——✅ 已满足：052 于 2026-06-12 23:33 收官（commit 14a6d6f，真模型双载体回填，全天 ≈¥18.1 收在 ¥20 信封）；实施前复核 `workspaces/shudian052/logs/driver/driver_state.json` status=stopped / phase=done。F7 段间对照已定版（基线 8.31 vs 删除版 8.48，拆除坐实、89eaa84 不 revert），src/ 改动禁令解除。
- **实施顺序与 commit 边界（审查 D2）**：053a（落盘→消费→血统链→driver）先行，是 053c 的硬依赖（--force-debate / 血统链 / plan 失效联动）；053b 独立 commit（沿用 052b "F7 独立回滚单元"纪律）；premise 搭车再独立一个 commit；env 开关保证 053b 可单独关闭对照。
- decisions.json 元数据以 dict 键注入、schema 不动（见 053a）；存量消费方已 grep 核实全部 dict 式读取（debater 落盘、paths、web plan_view / observability / static），新增键零破坏。
- `_review_feedback` 升级注意 token 预算：block 清单全量回灌，major/建议保留现行 top-N 截断（writer.py:1051 的 [:5] 惯例——初稿写 1056 系行号偏差，已勘误）。
- 反剧透文案的"过度保守"风险（怕剧透连合理推进都不敢写）以时间锚定措辞缓解（见 053b），验收侧再以 prose/plot 分轴基线兜底（见 053c 决策表）。
- driver 旗标：`--force-debate` 与 `--skip-debate` 互斥校验；`--allow-stale-outline` 只作用于 plan 侧校验，不改 debate 步行为。
- longzu 复仇局第 0 步按扩容清单清场（debate 三件套 + chapter_plan.json + 草稿残留 + rolling summary）；手工归档 debate 件时**三件同批**（漏 debate_log 会被 done_keys 续跑把新 debate 静默拼到旧辩论上，审查 A3/C4）。
- 验收命令统一 `.venv/bin/python`；verify.sh 需 venv PATH（050/051/052 三轮实录；verify.sh 内部裸用 python3，须先激活 venv）。

## Acceptance Result（待回填）

### mock 验收 ✅（2026-06-13 回填，含 053d 铁律⑨直修后终值）
- 全量回归 **959 passed 零失败**（907 → 954 → 959，净 +52：053a +25 / 拍板④ +6 / 053b +11 / premise +5 / 053d 铁律⑨钉死 +5——预估 +38 偏保守；另 test_cli_integration 的 run_debate 调用契约随 `--force` 透传同步更新）；`PATH=.venv/bin bash scripts/verify.sh` 全链 exit 0。
- 已钉死断言（原"待钉死"清单全部落地）：decisions 指纹+outline 哈希写入与写入顺序；plan 四态（匹配过/不匹配硬拦/无指纹 warn/decisions 缺失 warn 同道）；逃生门审计留痕；plan↔outline 血统链记录与校验；debate_log 指纹续跑拒绝；driver 三态（缺省 blocked + --force-debate 联动失效 plan + 一次性旗标消费）；debate --force 归档；锚定块条件注入（无起点与 env 关闭均逐字节不变）；回灌分层四节顺序与 block-but-Approve 修复 + `_blocking_reasons` 同口径 + 全 Approve 零回灌；跨周期反馈播种（含 write_chapters 端到端）；扩写空字段重试与 record 层标记不进 prompt、手工补全摘牌；`WRITE_REVIEW_MIN_APPROVE` 覆写（3/5 生效、缺省/非法回退、夹紧）；models.yaml model_env 钩子（mock 隔离不被突破）。
- 测试分布：053a → `tests/test_iter053a_outline_guard.py`；拍板④ → `tests/test_iter053_decision4_overrides.py`；053b → `tests/test_iter053b_canon_anchor.py`；premise → `tests/test_iter053_premise_guard.py`。
- commit 边界（审查 D2 纪律，四个独立回滚单元）：053a=`78cdc75`、拍板④=`4dd1ed6`、053b=`27cdea9`、premise=`0e2049b`。

### 053c 实跑实录（2026-06-13，进行中——四层毒源逐层剥洋葱）

> 拍板⑤（/goal，¥50+ 授权）下自主执行。每一层都是"按图索骥跑一段 → 取证 → 停机 → 机制化修复 → 复跑"的循环，全部留档可考。

| 轮次 | 现象 | 根因 | 修复 | 花费节点 |
|---|---|---|---|---|
| 点火一（段一 v1） | 053a 全链绿灯（指纹/血统/log 头全匹配）但全新辩论仍产出"黑色机库"ch1——起点 ch024 是 III 尾声（机库之战已收束三个月），新大纲却把高潮当"当前局势"重演 | **根因②**：debate prompt 从无 plot_planner 自 iter021/027 就有的显式起点块；毒 anchor 以 must-anchor 满权威注入（id 级 provenance 拦不住内容毒：anchor meta 记 ch024、内容锚高潮中段） | **053e**（`fa40b2e`）：`_start_point_prompt_block` 注入 agent 轮次/decisions/outline 三个 prompt 面，显式压过 must-anchor；plan 落盘后停机取证 | ¥2.83（debate 44 calls + plan） |
| anchor 重生成 | 修完 053e 重新 bootstrap-anchor，**新 anchor 仍锚机库** | **根因③**：anchor 采样窗口 off-by-one——`format_chapters_before_start_for_anchor` 起点章 exclusive，起点章本身（真正的交接点）永远不进窗口；ch021-023 还在高潮里，ch024 才是时间跳跃的尾声 → 重新生成多少次都是毒（5/30 毒 anchor 由此成因，非一次性事故） | **053f**（`d9a0564`）：include_start 开关（(start-k, start] 闭区间），bootstrap 走 inclusive + "以最后一章结尾时空为准"指令；重生成后 anchor 正确锚尾声（"东京危机已过去三个月"） | ¥0.15 ×2 |
| 复跑（段一 v2） | 053e+053f 生效：新大纲自带"起点校准"节（机库 0 次、"禁止重演已收束战局"白纸黑字）、plan v3 ch1「夜航」无缝衔接尾声最后一幕——**真·干净图纸首次产出**。但 ch1 首稿 panel 5.44 连拒，拒因全部 entity/relationship 系："当前状态停在入学初期、3E 考试前后" | **根因④（最深层）**：extracted_jsons 只有全书 110 章的**前 3 章**（5/29 init 小 limit），起点在第 ~100 章——KB/entity_graph 整条派生链锚死"入学初期"，评审拿旧实体图当硬尺连拒贴起点的正确稿件。同时坐实：052 九稿全灭拒因与 6/5「听力考试」7.5"基线"同源——后者是恰好写进旧底座时代的**假基线** | **053g**（`9163a59`）：`extraction_coverage_failures` warn 护栏进 readiness；运营面补提取 3_3 卷 24 章（进行中）→ recompress → 实体图重建 → resume（plan v3 内容正确，不重辩） | 二轮 debate+plan+ch1 两稿 ≈¥5.0；补提取预估 ≈¥4 |
| A-H1 实战 | resume --force-debate 时 `stale_plan_archived` 在 debate 之前触发 | 铁律⑨ A-H1 修复的顺序在真实中断-恢复链上首次实战命中 | —— | —— |
| 根因④变体 | 补提取+KB 重建后 bootstrap-graph **仍**锚序章/入学初期 | **根因④-b（截断毒）**：`_extractions_context` 把 27 章 compact JSON 尾部截断到 65k，LLM 只看到字典序最前的早期章节；5/29 首建只 3 章不触发、提取补全反而引爆 | **053h**（`fda280a`）：recent_first 由近及远整项累加、丢最早章；重建后实体图正确锚 III 尾期（绘梨衣之死/生命交易/全员就位） | bootstrap-graph ×2 ≈¥1 |
| **终验收（段一三攻 + 段二）** | **ch1–5 全 5/5 满票 Approve**，panel 7.50/7.56/7.52/7.64/7.74（均值 **7.59**）；机库/倒计时/心神原型机全章 **0** 次；ch1 anchor=False（纯 053a 净图纸单独验证）vs ch2–5 anchor=True（053b 锚定）；ch4/ch5 各重试 1 次过审（053b 跨周期播种实战，052 九稿横盘的对照反例） | 四层毒源全部根除，干净底座下流水线本就能写 | 全链验收兑现 | 干净 pass ≈¥9.6（底座修复后单 pass，回原 ¥12 量级内） |

**验收判定（决策表第一行命中）**：ch1 过闸 ✓（且 anchor=False 即纯净图纸下过，干净图纸假说**铁证成立**）；ch1–5 Approve 5/5 ≥ 3/5 ✓；panel 均值 7.59 ≥ 7.5 ✓ → **053 全验收通过，capstone 立项解锁**。3/5 票闸全程未派上用场（5 章 approve_count 均 5/5），质量为真而非降阈值蒙混。

**成本总账**：全程 driver-scope **¥23.61**（拍板⑤ ¥50+ 授权内，拍板② ¥12 是单 pass 口径、不含剥四层毒源的取证）= 取证+底座重建 ¥14.0（两轮辩论/三轮 plan/ch1 三攻 + 24 章提取/KB/实体图×2）+ 最终干净 pass ¥9.6。**关键：底座修复后单 pass 5 章 ≈¥9.6，回到原 ¥12 设计量级**——证明四层护栏不增边际成本，贵的是一次性的历史债清偿。

- **预算执行记录**：拍板②的 ¥12 为单 pass 设计；实跑剥出四层毒源后按拍板⑤（¥50+）扩执行预算——resume 时驱动器 `--budget-cny 20`，全程含补提取预计 ≤¥20。
- **052 根因考古的修订**：052 收官记载的主因（陈旧 outline）成立但不完备——它是四层毒源的最外层；"6/5 旧 plan 贴起点可过"的对照证据实为"贴旧底座可过"。052 文档不改（历史记录），以本实录为准。

### 真模型段 ✅（2026-06-13 收官，longzu 复仇局通过）
- 决策表第一行命中：ch1 过闸（anchor=False 纯净图纸，干净图纸假说铁证成立）+ ch1–5 **5/5 满票 Approve** + panel 均值 **7.59** ≥ 7.5 → **053 全验收通过，capstone 解锁**。
- 实跑剥出 052"根因考古"未触达的更深三层（debate 缺起点块 / anchor 采样 off-by-one / 提取底座断层 + 截断毒），逐层机制化为 053e/f/g/h，全部 mock 钉死；详见上方"053c 实跑实录"四层剥洋葱表。
- 成本 ¥23.61（含一次性历史债清偿，拍板⑤授权内）；干净底座单 pass 5 章 ≈¥9.6 回原量级。
- 配方速记（实施段核定版）：第 0 步清场断言（debate 三件套 + **毒 chapter_plan.json** + ch1 残留 + rolling summary）→ 段一 `drive_book.sh --book longzu start --chapters 5 --segment-size 1 --pause-after-segment 1 --plan-target 5 --force-debate --require-start-point --budget-cny 12 --tier mid --detach --confirm-real-run` + `WRITE_REVIEW_MIN_APPROVE=3` + `WRITER_CANON_ANCHOR=0`（ch1 仅 053a）→ 人审 → 段二 resume 开启锚定跑 ch2–5。

### 铁律⑨ 对抗审查 ✅（2026-06-13 回填，053c 点火前完成）
- 双视角 subagent 并行：A 指纹/血统校验链正确性、存量兼容与逃生门审计 × B 反剧透副作用、回灌 token 成本与跨周期播种正确性。结论：**1H + 5M + 3L 当轮直修**（commit `3506b36`，053d）。
- **A-H1（必修）**：`--force-debate` 的 plan 归档原在 debate 子进程之后——debate 超时/中断会让"联动失效"永久丢失，resume（旗标默认清零）补完辩论后 ensure-plan 见旧 plan 条数够数直接复用，052 毒 plan 事故在中断路径上复活。修法：plan 归档挪到 debate **之前**（plan 因 force 意图失效、与 debate 结果无关），失败路径测试钉死。
- 其余直修：A-M2 outline 写盘前 CR 规范化（防哈希假阳性硬拦）；A-M3 无头 log + 带元数据 decisions → fail-closed；A-M4 driver 读 decisions 容错四面同口径；A-L2 空 log 补指纹头；A-L4 force 归档挪到 persona 校验后；B-M1 章节 meta 落 `canon_anchor_active`（段间对照凭据）；B-M4 播种剥离 lint 行号；B-L5 web 补全摘牌。
- **记入 053c 观察项（带病点火获准）**：B-M2 polish 路径（Approve+<3000字）现在会吃到 block 行（053c 章节均 >3500 字，风险低）；B-M3 Approve+block 稿出货无痕（3/5 票闸下人审时专门翻 Approve 章的 agent_reviews 查 block）；B-M5 3/5 票 × Abstain 交互削弱 fail-closed（解析失败率低，观察）；A-M5 append/replan 路径丢审计痕 + 不透传逃生门（053c 不走 replan-every，排 054）。
- B-H1 条件性发现（模型换档 × cost_estimator 单价表计价失真）→ 以拍板⑤"不换档"豁免。
- 测试密闭性连环挂根因修复：plot_planner 存量测试补 patch DECISIONS_PATH + setUp 止血（verify.sh 在 repo 根留下带指纹 decisions 与测试 tmp outline 撞 content_mismatch，setUp 抛异常致 patch 泄漏）。mock 全量 **959 passed**（954→959）。

## 不在本轮范围
- 30–100 章 capstone（仍单独立项，依赖 053c 结论）。
- entity timeline schema 升级（052 已收 12 章 advance proposal 证据，继续观察）。
- Aeloon 反馈集成 / KB stage 回退交互软化（顺延口径不变）。
- 评审拒因的跨章记忆（同类违例在后续章节预防性提示）——视 053c 结果再议。
- 指纹范围扩展到 KB/facts/personas 等 debate 上游全量输入（审查 A7 已明示本轮只保"起点身份"错配，扩展另行立项）。
- 票数闸 tier 预设表修改（`review_tier._THRESHOLDS` 不动）——053c 经拍板④的 env 覆写跑 3/5；预设值是否永久调整，视 053c 证据再议。

## Notes
- 本档为计划稿（2026-06-12 起草于 052 实跑收尾等待期，拍板项见篇首）；052 已于同日收官（commit 14a6d6f），**实施于 2026-06-12 启动**。052 收官回填与本档立项依据全部吻合：候选①②即 053a/053b，候选③动态建边、④capstone、⑤票数闸观察仍单独立项（见"不在本轮范围"）。
- 052 移交的三条实测发现已全部转化为本档立项依据（见篇首引言块）。
- **2026-06-12 四维 subagent 审核修订实录**：①代码锚点 12 项全查——勘误 `--confirm-real-smoke`→`--confirm-real-run`、writer.py:1056→:1051，其余锚点（plot_planner.py:75 / start_point.py:178 / schemas.py:327 / writer.py:593-613、1027-1061、1032 / debater.py:128-160 / jobs.py:398 / book_runner.py:633-670 / 测试数 907）全部命中；②052 文档口径核对——三条发现、shudian052 对照、6月5日基线、¥6.40 实测成本、顺延项、移交建议全部一致；③盘面实勘——毒源三件套（5月30日，无指纹）、毒 chapter_plan.json（F6 全绿）、起点 longzu_3_3_ch024、premise 空字段、snapshots 目录无冲突均确认；④对抗审查——采纳 plan↔outline 血统链、decisions↔outline 内容绑定与写序倒置、done_keys 防洗白、driver 缺省 blocked、schema 改 dict 注入、反剧透改时间锚定、跨周期播种升格交付物、053c 分段单变量 + 验收决策表、第 0 步清单扩容。
- 053c 跑前重读 052 PLAN 的"真模型段一"拒因实录——评审的 block 级 rule_id（gf_longzu_014/015，已核实存在于 longzu global_facts.json）是验证回灌效果的现成探针。初稿另列的 `timeline_3E_exam` 在 052 文档与盘面均无出处（系"时间线前置"拒因的描述性归类、非真实 rule_id），已剔除。
- 铁律⑤：收官只 commit 不 push。
