# Iteration 170 - 小说真实续写与长流程可靠性修复

## Context

用户要求启动项目、多角度实测并修复续写/长跑/WebUI 阻塞，真实模型累计不超过 200 元，最终必须真实验收。基线 iter169/c99f8c2。问题与修复方案先提交于 `docs/audits/novel-audit-2026-09-05.md`，包含实际中文合集导入错分、双标签保存覆盖、任务持久化、预算与记忆缺陷。

## Plan

### Implementation Context
- `must_read`: `src/text_normalizer.py`, `src/chapter_splitter.py`, `src/web/static.py`, `src/web/templates.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/story_memory.py`, `src/writer.py`, `src/book_runner.py`, `src/plot_planner.py`, `src/config.py`, `src/openai_stream.py`, `src/cost_estimator.py`, `src/debater.py`, `src/partial_recovery.py`, `src/reviewer.py`, `scripts/write_book.sh`
- `expected_changes`: `src/text_normalizer.py`, `src/chapter_splitter.py`, `src/web/static.py`, `src/web/templates.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/story_memory.py`, `src/writer.py`, `src/book_runner.py`, `src/plot_planner.py`, `src/config.py`, `src/openai_stream.py`, `src/cost_estimator.py`, `src/debater.py`, `src/partial_recovery.py`, `src/reviewer.py`, `scripts/write_book.sh`, `tests/test_iter170_reliability.py`, `docs/audits/novel-audit-2026-09-05.md`
- `do_not_touch`: `.env`、原文源文件、所有既有 workspace 产物与短剧分支。用户仅授权主线程复制指定原文到干净测试空间；subagent 坚持只读代码/测试，禁止私有内容。

1. F01 中文合集识别/正文切章/起点边界；通用规则不硬编码书名。
2. F02/F03 加载门禁、保存版本冲突，保留用户输入。
3. F04/F05 持久化顺序、日志容量与恢复证据保护。
4. F06 缺失 usage 安全停止，真实执行累计预算不得靠未知估算释放。
5. F07/F08 force 后续失效及旧记忆 cutoff；F09 wrapper 参数合同。

## Acceptance

### Review Context
- `correctness_behavior`: 中文真实格式与合成格式切章、force 后代失效/正常跳过、任务终态与恢复、版本冲突及兼容测试。
- `security_boundary`: 不修改原文、不读凭据、unknown 零重提、缺 usage 不继续计费、压缩 no-follow/锁/原子持久化与恢复 CAS。
- `extra_risk_view`: Web 真实浏览器延迟/双标签/取消恢复，真实模型预算与指定起点防剧透边界。

- A170-01：F01 合成回归与指定原文无计费导入，确认第三部末尾且第四部不进入后续上下文。
- A170-02：F02/F03 加载失败/延迟与双标签冲突聚焦和浏览器验证。
- A170-03：F04/F05 时序、容量、重启和 unknown/恢复证据聚焦测试。
- A170-04：F06 usage 缺失/坏值阻断下一请求，真实链累计硬预算。
- A170-05：F07/F08 当前及后续旧摘要/实体/审核失效，force 失败安全与正常 resume 不变。
- A170-06：F09 tier 两种语法和缺值实际 argv 回归。
- A170-07：至少 correctness、security/boundary 与 Web/计费三个只读审查；主线程复核修复 findings。
- A170-08：PASS。新增实现 `f4eadb9` 上 canonical schema v3 / `canonical-novel-mock-offline` 通过；1973 tests / 15 steps / 97秒，run `71fc3a36e6004f08a739b86d2c4b6832`，`tracked_scope_clean=true`，仅 `mock-functional`。此证据替代此前工程验证。
- A170-09：干净工作区真实准备、规划、续写与长流程/恢复实测，逐步记录模型调用、费用与真实结果；必须获得 provider-validated，未通过不得宣称本轮完成。

## Implementation Notes

F23：真实多轮修订仍Reject后查明写手计划未传模型评审，可能导致新增事件修改要求不对称。仅将本章指纹白名单字段构成≤6000字符完整JSON摘要，五评审/顾问/两处简化回退共用；缺计划不变、排除未来章节和额外字段。明确计划非既有事实且不得覆盖硬事实，不改阈值。两路只读审查通过；合成捕获验证所有请求路径，原有计划/关系硬拒绝和评分回归通过。真实旧任务7244078f在审查取消，保留v2完整失败稿用于新上下文恢复；此前内容评分不宣称误判或通过。

F22：标准档首次14–15次模型调用、一次重写增加7次，发现按章20的默认被错误用作不可提高的最大值。主写作与显式失败章恢复最大值改为160，默认仍按章20/恢复20，保留其他计费/时限/资格/确认边界。41项聚焦、两路只读审查与增量复审通过；浏览器3章手填100后改1章仍100，提示可调上限160。当前真实任务60额度未更改。

F21：真实首章正文完成后内部审查上游失败，已有partial缺少恢复上下文会导致正文重写。增加schema v2上下文及正文指纹，只允许完整正文阶段恢复到lint及完整审查；旧版/不匹配文件先保留不可覆盖快照后重写。安全读取拒绝符号链接、特殊文件和超限；归档失败及来源变化在模型前阻断。53项聚焦通过，correctness与security独立只读审查无剩余P0–P2，并补runner正常/force/重试参数回归。SIGKILL前未落盘正文不在此恢复保证内。真实旧版partial不会伪造元数据迁移。

F20：真实36次发言完成后裁决context_too_large、零新增请求，定位旧摘要仅限条数且整体截头丢后轮。改为保留全部条目的有界头尾摘录、完整JSON，各消费者显式限额；裁决使用冻结client token门禁搜索可行摘要，大纲保留完整问题。审查发现收缩跳过窄窗口及省略标记膨胀短响应，均修复并复审通过。68项聚焦通过；原36条真实记录无模型预检：旧摘要105752字符→23999字符，完整裁决prompt27693token，全部轮次/角色仍在，原日志字节不变。

F19：多章正常写作至少约15请求/章，Web却固定20次硬上限。先记录设计缺陷，改为已验证章节数×20并保留全局160上限，两个表单按章数同步未手改默认值；手动低值保留，单章恢复仍20。132项聚焦通过；两路审查发现预设程序改章数漏触发同步，已补input派发和联合Node回归，增量复审通过。

F17/F18：真实恢复复核发现成功票被日志重写删除、问题重建使旧票下标失去含义。先补审计后增加原子裁决检查点与发言/问题指纹、保留并验证成功票、旧票无问题版本明确阻断。新增4项隔离反例涵盖部分投票恢复、大纲失败后只重做大纲、损坏/legacy原文件保护、检查点写失败不投票。132项聚焦通过，两路独立复审完成；审查发现损坏JSON检查点可被跳过，已改为损坏/非对象记录在重写前阻断，新增首票前中断与原字节保留反例，增量复审通过。未知响应通用标题不再误称超时。

F16：真实任务发现完成卡片仍有取消按钮、本页发起任务顶栏长期等待中；先记审计后修复。所有pollJob路径共享job_id绑定的顶栏更新，终态无取消，状态未知保持独立控件锁并清旧快照，恢复轮询拒绝旧任务迟到响应。两路审查有效findings均闭合，44项聚焦含真实Node忙碌清理/错序测试通过；隔离真实浏览器运行20%同步、失败无取消按钮、断网后提交仍禁用通过。真实debate继续在ffbf12a服务上运行，未中断。

F15：Web非流式compress两次125秒超时，独立CLI stream155.43秒成功。新增显式OPENAI_WEB_STREAM，仅openai/且Web deadline作用域启用原生SDK有界流。审查提出模型参数映射、异步DNS/清理超时、在途取消未知计费三项，已增加GPT-5/o系列参数转换、spawn独立进程硬退出边界、unknown预留持久化与费用累计保留。补修IPC半帧阻塞为非阻塞有界JSON接收；补修spawn大参数发送阻塞为启动后非阻塞IPC发送，覆盖JSON转义膨胀；72项流式/LLM和32项费用配置聚焦通过，三路独立增量复审全部通过，将在实现提交上canonical。

F14：首次细纲缺章节仍成功的问题已先写入审计，补请求数量校验、连续编号和target规范化，不新增付费重试；不足不落盘并保留旧计划。两项反例测试覆盖空/少章、超量/重复编号与force旧文件保护，47项聚焦通过。独立审查发现新增测试误归无隔离类，已移入临时workspace fixture并重跑；错误测试新建的合成目录按创建时间确认后移出仓库，不涉及既有workspace。两路复审通过；新实现8bf8b6d canonical1934项/15步骤/87秒通过。

用户明确暂不考虑预算继续测试，F12不再作为暂停条件，保留估算记录。原文准备从7章缓存续接。F13概览运行状态误导先记入审计，追加最小前端修复与状态转换实测，79项聚焦与两路增量审查通过；审查发现失败/未知状态误回落已修，浏览器running→succeeded、running→failed、断网状态待确认通过。将以新实现提交覆盖完整验收。

2026-09-06 新key/luna最小生成通过，按用户提供的USD0.01/百万输入输出token暂算；新模型仅临时进程配置，未写.env或仓库单价。真实准备取消已保存两章且未发第三章。新增F11先写审计报告，追加每请求取消门禁与terminal传播，74项聚焦回归通过，correctness及security/boundary两路增量审查无高置信P0–P2；新实现2ae8386完整验收1932项/15步骤/83秒通过。

恢复实测新增F10（阶段预算无输入），已先补入审计报告；本轮追加最小WebUI修复。保留默认费用及backend边界，准备原创3/续写20，大纲33，细纲10；不改正文/恢复合同。139项聚焦通过，correctness与security/boundary两路增量审查无findings；真实浏览器12元确认一致、21元和空值阻断通过，未新增计费。新增实现提交2ae8386已重新canonical通过1932项/15步骤/83秒；旧证据由本次替代。

首次canonical跑1928项，旧iter168无scope日志失败测试泄漏sticky计费停止状态，连带后续LLM用例失败，另两条UI静态合同未适配新文案/disabled。修正测试隔离与断言，77项聚焦通过，独立复审确认未削弱生产保护；将形成测试修正commit后完整重验。

先报告后立项。累计3次真实调用，最初RateLimitError，恢复后的WebUI请求BadGatewayError，不含原文的最小连通性亦失败；保留最坏费用预留5.609916元，实际账单未确认。原文路径由用户明确提供，仅主线程处理；新测试根位于系统临时目录，mock 与 real 数据隔离。

## Acceptance Result

F17真实增量：裁决检查点已落盘后在4张票完成时从Web取消；同服务恢复后检查点与原4票hash全部不变，只补2票并发起大纲请求（新增3请求）。F20真实裁决已成功通过，不再发生长发言汇总上下文溢出。F19隔离真实浏览器3章自动60、切单章预设自动20、手动12后改3章仍12通过。

- 聚焦检查：首批17项；修复后48项、82项、LLM/写作106项及最终65项通过（集合重叠，不相加）。
- A170-01：PASS，最新源码原文导入保留88章，起点en_upload_ch088/尾声，normalized行138688–139405，第四部目录/正文不进入该边界，源SHA256未变化。
- A170-02：PASS，真实浏览器慢GET期间textarea/双保存禁用，完成后启用；双tab A成功/B冲突且输入保留。CAS与缺版本测试通过。
- A170-03：PASS，取消/完成线程时序、逻辑历史CAS、own pending触发压缩、ABA、旧5010行、替换旧inode、压缩失败保留原日志回归通过。
- A170-04：工程PASS，Web/CLI缺失usage、坏usage转换和日志sink失败阻断下一请求；真实测试外层累计保守预留硬上限200元，不回收未知实际费用。
- A170-05：PASS，实际legacy writer prompt捕获排除旧当前/未来记忆，后代失效；normal skip文件不变。runner归档前失效时序经独立审查。
- A170-06：PASS，fake Python实际argv两种tier语法与缺值exit64。
- A170-07：PASS，correctness、security/boundary、Web/计费三路审查及增量复审。真实序章误删、旧inode读取、旧超行数、CLI缺usage/坏usage已修复；范围内无剩余高置信P0–P2。
- A170-08：PASS。新增实现 `f4eadb9` 上 canonical schema v3 / `canonical-novel-mock-offline` 通过；1973 tests / 15 steps / 97秒，run `71fc3a36e6004f08a739b86d2c4b6832`，`tracked_scope_clean=true`，仅 `mock-functional`。此证据替代此前工程验证。
- A170-09：真实全链进行中。10章提取、Web准备、36次大纲发言/6票裁决/大纲及3章细纲成功；投票取消恢复仅补缺失票，原记录不变。首章完整正文已生成，真实审查取消后schema v2检查点恢复直接进入审查、未重复WRITE。三章严格审核与跨章记忆尚待验收。用户暂不考虑预算继续测试，仍保留usage估算及未知费用。
- F11增量：PASS（工程）。74项聚焦、两路独立审查；新增实现2ae8386 canonical 1932项/15步骤/83秒通过，终止回调阻止新增请求并穿透修复链。在途成功响应保留。真实取消/续接在启动于F11之前的服务上观测，不混称为新代码全部真实验收。
- F10增量：PASS，139项聚焦及两路独立审查通过。浏览器12元确认一致、21元及空值阻止提交，取消不发起请求；仅前三阶段预算可调整，正文/恢复合同不变。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 合集章名不能全局去重；日志压缩必须保持逻辑历史与当前文件身份，缺计费数据的停止规则须覆盖CLI。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/chapter_splitter.py` | 局部目录过滤、重复卷章名保留及目录截断边界 |
| `src/web/static.py`, `templates.py`, `routes.py` | 加载门禁、正文版本CAS与冲突输入保留 |
| `src/web/jobs.py` | 有序持久化、逻辑历史压缩与当前身份复核 |
| `src/llm_client.py` | Web/CLI计费缺失和日志异常均停止新增请求 |
| `src/story_memory.py`, `writer.py`, `book_runner.py` | force后代失效、衍生历史清理与提示cutoff |
| `scripts/write_book.sh` | tier透传 |
| `tests/test_iter170_reliability.py`及旧编辑夹具 | 新反例与版本协议兼容回归 |
| 本文、索引、审计报告 | 方案和阶段证据 |

## 不在本轮范围

短剧、媒体生成、公网多租户、原文修改、旧工作区迁移与历史未知请求重提；不能证明所有可能 bug 不存在。

## Notes

只 commit、不 push。收官按 iter-finish 同步 README SOP、handoff、PROJECT_HISTORY；真实失败保留为未通过并说明原因。

独立 Web 服务原为 localhost:8768，2026-09-06已按用户继续测试指令恢复临时服务；测试根 `/private/tmp/novel-audit-20260905/real`。服务启动不发模型请求；外层累计最坏费用预留保留在该测试根，仅主线程/用户访问。此临时测试位置不属于可提交产物。

2026-09-06先前暂停快照（后续已恢复）：7章提取JSON落盘，任务明确aborted/cancelled；累计16次请求（旧模型3、新模型13，含3个诊断请求），Luna按用户单价估算含诊断约0.019253元，非服务端账单。含此前未知费用的账本预留5.667020352元；发现输出限制不生效后不把该预留宣称严格上界。专用含key进程已退出，后续无后台模型调用。真实准备/规划/正文全链仍未验收。
