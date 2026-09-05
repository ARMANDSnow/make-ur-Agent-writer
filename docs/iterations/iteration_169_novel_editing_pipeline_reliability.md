# Iteration 169 - 小说编辑与长程续写可靠性修复

## Context

用户要求修复本次多视角审查的三个 P1（保存竞态、手改前文的故事记忆、单步取消），并追加代理保留、Web 切章、大纲人工编辑、旧失败标记、分段滚动规划及伏笔生命周期六项。基线为 752fbe6；先复核现有修复，避免重复改动或取消安全门禁。

## Plan

### Implementation Context
- `must_read`: `src/web/static.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/chapter_summary.py`, `src/book_runner.py`, `src/writer.py`, `src/llm_client.py`, `src/foreshadowing.py`, `src/plot_planner.py`, `tests/test_jobs_cancel.py`
- `expected_changes`: `src/web/static.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/chapter_summary.py`, `src/book_runner.py`, `src/writer.py`, `src/llm_client.py`, `src/foreshadowing.py`, `src/plot_planner.py`, `scripts/with_proxy.sh`, `main.py`, `tests/test_iter169_reliability.py`, `tests/test_jobs_cancel.py`, `docs/iterations/iteration_169_novel_editing_pipeline_reliability.md`
- `do_not_touch`: 不读取或修改凭据、私有小说和现有 workspace；不调用真实模型，不修改短剧分支；其余审查 P2 不顺手修复。

1. 保存响应只确认实际提交版本；保存途中新增输入继续受导航保护，覆盖同根编辑器。
2. 前文人工修改后失效的摘要/结尾和推进不得静默注入下一章，提供明确可执行的恢复路径；缺失可选记忆仍兼容。
3. Web 单步抽取、压缩、设定任务接通取消检查，下一次调用前停止。
4. 默认保留用户代理，特殊代理适配需显式启用；复核并回归真实 normalize 到 Web split 的 mock 链。
5. 人工大纲保存记录来源/hash，保留起点边界；审核只在当前正文及通过条件充分时解除可恢复旧失败。
6. 分段/恢复/段末滚动规划覆盖下一窗口；伏笔使用明确证据和人工确认更新，逐章检查一致，不以自动宣告回收绕过门禁。

## Acceptance

### Review Context
- `correctness_behavior`: 覆盖编辑中保存及导航、摘要版本与手改后继续、单步取消、代理保留、大纲编辑到规划、lint/审核终态、分段规划和伏笔回收，已修问题保留兼容回归。
- `security_boundary`: 手改来源不能绕过起点/正文 hash；取消后零新增请求；默认代理零探测；不触碰私有数据或真模型，持久状态失败关闭，未知付费失败不得误清。
- `extra_risk_view`: Web/UX：真实 JS 异步时序、可操作恢复说明、批次与单章状态一致性。

- A169-01：所有受影响编辑器保存中新增输入仍 dirty，导航不得当作已保存；执行 JavaScript 行为回归。
- A169-02：人工改稿后的旧记忆不能进入下一章，合成数据回归覆盖版本漂移、恢复及可选缺失。
- A169-03：真实单步 handler 的 callback 接线及取消前后调用计数 mock 回归通过。
- A169-04：代理显式配置默认保留、特殊适配显式启用；normalize → Web split 集成回归通过。
- A169-05：合法人工大纲可生成计划；起点错配/未确认修改继续阻断；当前正文审核通过时安全解除旧可恢复失败。
- A169-06：分段规划及恢复覆盖下一窗口；伏笔证据确认/TTL/逐章检查有 mock 回归。
- A169-07：correctness、security/boundary、Web/UX 三路只读审查有效 findings 闭合，聚焦回归通过。
- A169-08：implementation commit 上最终运行 bash scripts/verify.sh，通过 canonical-novel-mock-offline/schema v3；等级仅 mock-functional，随后 docs-only 同步 README/handoff/history。

## Implementation Notes

- Web split 当前已接受 txt/md，原书伏笔默认来源豁免已有历史修复；新增真实 normalize → Web split 的合成回归，不重复修改既有逻辑。
- 同根保存覆盖九类编辑器，快照检查字段值/DOM 身份/连接状态；迟到 GET 成功与失败均按序号处理，细纲保存后同步退出旧编辑器。
- 新增 `src/story_memory.py` 集中持久失效与审核后摘录恢复，扩展 `src/workspace_files.py` 的 no-follow 删除接口；关联 `src/readiness_catalog.py`、`src/web/templates.py` 和产品指南给出恢复说明。这些为实现原 Plan 所需范围扩展。
- 当前稿严格审核通过后，仅解除有明确 lint 结构的旧失败；未知/付费/超时失败保留，归档走 no-follow 路径。
- 滚动规划按全书边界运行并保留远期尾部；纯读 readiness 仅将合法连续缺失尾部投影为可补齐，实际 runner 在预算检查后补齐并复核。
- 收官修正：`src/chapter_status.py` 的 strict 完成态纳入记忆待更新；补齐窗口记录本次生成上界，避免紧接着重复规划。
- 伏笔新增本地 CLI 人工确认/TTL 入口，证据绑定当前正文、细纲和审核；逐章门禁一致，模型不自动声明回收。
- 聚焦测试文件扩展到 `tests/test_iter169_reliability.py`、旧 runner/global-boundary 与 proxy/mock 断言；使用真实 JS Node 时序测试及真实 runner 的合成两段五章回归。
- 安全预检发现损坏 JSON 被视作缺失、回收证据过期及归档 symlink 边界，均已修正并增加反例测试。

## Acceptance Result

- 聚焦检查：任务/runner/代理/编辑等 172 项通过，Web 安全与编辑 105 项通过，长程/伏笔/append 90 项通过；审查修正后 78 项回归通过（组间有重叠，不相加为唯一测试数）。
- correctness、security/boundary、Web/UX 三路独立只读审查完成；损坏 JSON、回收证据漂移、归档 no-follow、异步编辑刷新、重复补齐规划和记忆失败完成态 findings 均已修复，主线程复核及增量复审无剩余有效 P0–P2。
- JavaScript 行为验证含 PUT 中新增输入、动态字段增删/替换/顺序、节点断开、GET 倒序；Web reviewer 额外验证旧 GET 错误被忽略、最新错误保留。
- 最终 canonical 待 implementation commit 后执行；不声明 local-e2e 或 provider-validated。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: 保存确认必须绑定提交版本，审核通过与衍生记忆可用需分开；滚动规划与证据回收必须独立于批次边界。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/web/static.py` | 编辑快照确认、导航与过期 GET 保护 |
| `src/story_memory.py`, `src/chapter_summary.py`, `src/chapter_status.py`, `src/writer.py` | 手改失效、审核后摘录恢复、完成态及润色后 lint |
| `src/web/routes.py`, `src/web/jobs.py`, `src/workspace_files.py` | 大纲人工版本、单步取消、恢复入口、安全归档 |
| `src/book_runner.py`, `src/plot_planner.py` | 分段窗口补齐/去重、保留远期计划、逐章门禁 |
| `src/foreshadowing.py`, `main.py` | 伏笔证据确认与 TTL CLI |
| `src/llm_client.py`, `scripts/with_proxy.sh` | 默认保留代理、显式适配 |
| `src/readiness_catalog.py`, `src/web/templates.py`, `docs/product/GETTING_STARTED.md` | 恢复状态与操作说明 |
| `tests/test_iter169_reliability.py`, `tests/test_book_runner.py`, `tests/test_mock_offline.py` | 行为回归与旧契约更新 |

## 不在本轮范围

不修复其余 P2（取消日志竞态、日志容量、加载前编辑、包装脚本 tier、旧 write force）、不做真实模型质量评价，不 push。

## Notes

立项提交信息草稿：docs(iter169): 迭代计划 169 立项（小说编辑与长程续写可靠性修复）。收官使用 iter-finish，就地同步 README SOP 与 handoff/history，不另建状态真源。
