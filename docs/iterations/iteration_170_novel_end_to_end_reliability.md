# Iteration 170 - 小说真实续写与长流程可靠性修复

## Context

用户要求启动项目、多角度实测并修复续写/长跑/WebUI 阻塞，真实模型累计不超过 200 元，最终必须真实验收。基线 iter169/c99f8c2。问题与修复方案先提交于 `docs/audits/novel-audit-2026-09-05.md`，包含实际中文合集导入错分、双标签保存覆盖、任务持久化、预算与记忆缺陷。

## Plan

### Implementation Context
- `must_read`: `src/text_normalizer.py`, `src/chapter_splitter.py`, `src/web/static.py`, `src/web/templates.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/story_memory.py`, `src/writer.py`, `src/book_runner.py`, `scripts/write_book.sh`
- `expected_changes`: `src/text_normalizer.py`, `src/chapter_splitter.py`, `src/web/static.py`, `src/web/templates.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/story_memory.py`, `src/writer.py`, `src/book_runner.py`, `scripts/write_book.sh`, `tests/test_iter170_reliability.py`, `docs/audits/novel-audit-2026-09-05.md`
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
- A170-08：implementation commit 上 canonical `bash scripts/verify.sh` 通过，等级仅 mock-functional。
- A170-09：干净工作区真实准备、规划、续写与长流程/恢复实测，逐步记录模型调用、费用与真实结果；必须获得 provider-validated，未通过不得宣称本轮完成。

## Implementation Notes

恢复实测新增F10（阶段预算无输入），已先补入审计报告；本轮追加最小WebUI修复。保留默认费用及backend边界，准备原创3/续写20，大纲33，细纲10；不改正文/恢复合同。139项聚焦通过，correctness与security/boundary两路增量审查无findings；真实浏览器12元确认一致、21元和空值阻断通过，未新增计费。需形成新的implementation commit并重新canonical，旧证据不覆盖追加变更。

首次canonical跑1928项，旧iter168无scope日志失败测试泄漏sticky计费停止状态，连带后续LLM用例失败，另两条UI静态合同未适配新文案/disabled。修正测试隔离与断言，77项聚焦通过，独立复审确认未削弱生产保护；将形成测试修正commit后完整重验。

先报告后立项。真实调用1次遭上游RateLimitError，保留最坏费用预留2.79036元，实际账单未确认。原文路径由用户明确提供，仅主线程处理；新测试根位于系统临时目录，mock 与 real 数据隔离。

## Acceptance Result

- 聚焦检查：首批17项；修复后48项、82项、LLM/写作106项及最终65项通过（集合重叠，不相加）。
- A170-01：PASS，最新源码原文导入保留88章，起点en_upload_ch088/尾声，normalized行138688–139405，第四部目录/正文不进入该边界，源SHA256未变化。
- A170-02：PASS，真实浏览器慢GET期间textarea/双保存禁用，完成后启用；双tab A成功/B冲突且输入保留。CAS与缺版本测试通过。
- A170-03：PASS，取消/完成线程时序、逻辑历史CAS、own pending触发压缩、ABA、旧5010行、替换旧inode、压缩失败保留原日志回归通过。
- A170-04：工程PASS，Web/CLI缺失usage、坏usage转换和日志sink失败阻断下一请求；真实测试外层累计保守预留硬上限200元，不回收未知实际费用。
- A170-05：PASS，实际legacy writer prompt捕获排除旧当前/未来记忆，后代失效；normal skip文件不变。runner归档前失效时序经独立审查。
- A170-06：PASS，fake Python实际argv两种tier语法与缺值exit64。
- A170-07：PASS，correctness、security/boundary、Web/计费三路审查及增量复审。真实序章误删、旧inode读取、旧超行数、CLI缺usage/坏usage已修复；范围内无剩余高置信P0–P2。
- A170-08：PASS。implementation `54a9f98897ce815e0f7f315a4679540590958932`（主体 `5fae2e3`）上 canonical schema v3 / `canonical-novel-mock-offline` 通过；1928 tests / 15 steps / 86秒，run `36a0c20f612c443796d65749f18a9926`，`tracked_scope_clean=true`，仅 `mock-functional`。
- A170-09：未通过。真实首请求在extract首章返回provider_unavailable/RateLimitError，1次，无续写产物；没有provider-validated或真实长跑证据。需上游恢复，整体迭代保持未完成。

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

当前可继续测试的独立 Web 服务为 localhost:8768，测试根 `/private/tmp/novel-audit-20260905/real`。服务启动不发模型请求；外层累计最坏费用预留保留在该测试根，仅主线程/用户访问。此临时测试位置不属于可提交产物。
