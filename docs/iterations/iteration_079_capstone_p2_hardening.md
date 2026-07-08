# Iteration 079 - Capstone 前写锁与预算硬化

## Context

iter078 收口六方审查 P1 八组后，subagents 与本地核验均确认：当前没有“已发现但未修”的确认 P1/High。剩余最接近长跑生产风险的条目集中在 capstone 前 P2 边界：Web 手工写端点只受进程内 `workspace_reserved` 保护、CLI `apply-advance` 未纳入跨进程 flock、approved 章缺 entity proposal 时 readiness 不可见、mock 预算路径缺显式演练开关。

本轮按 P2 hardening 包推进，目标不是把 P2 包装成 P1，而是在不跑真模型、不扩大 scope 的前提下，把 capstone 期间最容易误操作的写入边界补齐。

## Plan

- Web 手工写端点桥接 `workspace_lock`：draft/outline/KB/start-point/chapter-plan/entity/relationship/writer-style/premise/drama 保存等 `workspace_reserved` 路径统一拿跨进程 flock，锁冲突返回 409 且不落盘。
- CLI `apply-advance` 加写锁：与 write-book auto-advance 互斥，锁冲突沿用 exit 4 家族，entity_graph/proposal 不变。
- Readiness 增加 `entity_proposal_gap:NN` warning：approved/caveat 章缺 `advance_applied` sidecar 且无 proposal 文件时可见，只 warn、不 blocker、不触发 LLM。
- Mock 预算演练开关：默认 mock 成本仍为 0；显式 `MOCK_COST_CNY_PER_1K_TOKENS` 正有限值时让 mock 日志产生非零估算，用于测试 budget reserve 接线。

## Acceptance

- 新增 Web 锁测试：持有 flock 时 PUT draft/outline/KB/entity/relationship 等返回 409 且文件未变；既有 Web job reservation 409 不回归。
- 新增 `apply-advance` 锁测试：锁被持有时 CLI exit 4，`entity_graph.json` 不变。
- 新增 proposal gap readiness 测试：缺 proposal+sidecar 出 warning；有 proposal 或 sidecar 不告警。
- 新增 mock 预算测试：默认 mock 成本为 0；设置 `MOCK_COST_CNY_PER_1K_TOKENS` 后估算非零并可触发预算预留路径。
- 验收命令：`.venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`。不跑真模型 smoke（铁律⑥）。

## Implementation Notes

- 立项前置：沿用本轮 subagent + 本地核验结论，没有确认“已发现但未修”的 P1/High；本轮按 P2 hardening 包推进，不改写风险等级。
- Web 手工写端点新增 `_workspace_write_guard(name, source)`：先占用进程内 `jobs.workspace_reserved(name)`，再进入 `use_workspace(name)` 并获取 `workspace_lock.acquire_write_lock(source=...)`。这样 Web 内并发与 CLI/driver 跨进程写者都走同一个 409 出口；既有 Web job reservation 的 `workspace busy` 响应保持原 shape。
- 收尾复核补线：`writer-style/extract` 上传暂存阶段也先拿 flock，CLI 长跑持锁时直接 409、不落临时样本、不排 job；extract-style worker 写 `writer_style.json` 前再拿 flock，锁冲突转 Web-safe blocker。
- `main.py apply-advance` 在调用 `apply_advance_cli` 前获取写锁；锁冲突打印 `WorkspaceLocked` holder 摘要并 `SystemExit(4)`，不进入 auto-apply、不改 `entity_graph.json` 或 proposal 文件。
- `check_write_readiness` 对会被 skip 的 approved/caveat 章追加 `entity_proposal_gap:NN` warning：仅在 `advance_applied` sidecar 与 proposal 文件都不存在时提示；有任一补偿源即静默，且不触发 LLM 回填。
- 收尾复核补线：`resume_from-1` 前一章若正文在盘且 approved/caveat，也按同口径检查 `entity_proposal_gap`。该章不在当前写入窗口循环里，但下一章 prompt 直接依赖它的 ending_state。
- `MOCK_COST_CNY_PER_1K_TOKENS` 仅在正有限值时生效，把 mock prompt/cache/response token 统一按该 CNY/1K 估算；默认 mock 价格仍为 0，坏值/0/NaN 均回退 0。
- 验收中裸沙箱运行全量 unittest / verify 会被 `test_novel_client` 的 `127.0.0.1` 临时端口绑定拦截；按工具规则申请非沙箱重跑后通过。该失败与本轮实现无关。

## Acceptance Result

- `git diff --check`：通过。
- `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m py_compile main.py src/book_runner.py src/cost_estimator.py src/web/jobs.py src/web/routes.py tests/test_iter079_capstone_hardening.py tests/test_web_jobs_dispatch.py tests/test_web_writer_style.py`：通过。
- `.venv/bin/python3 -m unittest tests.test_iter079_capstone_hardening tests.test_web_jobs_dispatch tests.test_web_writer_style`：60 tests OK。
- `.venv/bin/python3 -m unittest tests/test_web_draft_edit.py`、`.venv/bin/python3 -m unittest tests/test_web_kb_entity_edit.py`、`.venv/bin/python3 -m unittest tests/test_iter078_workspace_lock.py`：通过（邻近锁/编辑回归）。
- `.venv/bin/python3 -m unittest discover -s tests`：通过，**1633 tests OK**（skipped=6）。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`：exit 0，内部 **1633 tests OK**，随后 auto-pipeline/status/manifest/report/cost 检查通过。
- `.venv/bin/python3 main.py preflight`：exit 0，`PREFLIGHT: warn`，无 FATAL；WARN 为当前真实配置态模型/token/cache/默认预算提示。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：exit 0，`PREFLIGHT: ok`，无 WARN/FATAL。
- 未跑真模型 smoke（铁律⑥）。
- 铁律⑨只读审查：收尾按用户要求起 2 个 subagent。Security 发现 1 个 Medium：Web job JSON 仍可能暴露 raw `WorkspaceLocked` 诊断（绝对 `write.lock` path/argv）→ 修为 `workspace locked` + `holder.source/started_at` allowlist，覆盖 `write-book`、`review-chapter`、`draft-once-dev`、`extract-style`，并加 job detail/recent 不泄漏测试；此前 Web 手工 409 `holder` 原始诊断泄漏也已修。Correctness 发现 1 个 P2：`resume_from=2` 只检查前一章 rolling gap、不检查 entity proposal gap → 补 `resume_from-1` approved/caveat 章 warning，并加回归。两项均已修，无剩余 P1/P2 blocker。
- 最终版补跑：`git diff --check`、py_compile、聚焦 60 tests、全量 unittest、`verify.sh`、两种 preflight 均通过；未跑真模型 smoke（铁律⑥）。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/web/routes.py` | 新增 Web 写 guard 与锁冲突响应；手工写端点从进程内 reservation 扩展为 reservation + workspace flock。 |
| `src/web/jobs.py` | Web job 的 workspace lock blocker 脱敏；extract-style 写卡前拿 flock；通用 blocked summary 保留 first_blocked。 |
| `main.py` | `apply-advance` 调用前获取 workspace 写锁，锁冲突 exit 4。 |
| `src/book_runner.py` | readiness 对 approved/caveat skip 章与 `resume_from-1` 前章新增 `entity_proposal_gap:NN` warning。 |
| `src/cost_estimator.py` | 新增 `MOCK_COST_CNY_PER_1K_TOKENS` 正有限值 mock 预算演练开关。 |
| `tests/test_iter079_capstone_hardening.py` | 新增 Web 手工写锁、apply-advance 锁、entity proposal gap、mock cost override 回归测试。 |
| `tests/test_web_jobs_dispatch.py` | 新增 Web job workspace lock 脱敏回归测试。 |
| `tests/test_web_writer_style.py` | 新增 writer-style/extract CLI 持锁时 409 且不暂存样本回归测试。 |
| `README.md` | 同步 SOP 最近一次更新与项目状态表。 |
| `docs/AGENT_HANDOFF.md` | 追加 iter079 Phase Status。 |
| `docs/iterations/iteration_079_capstone_p2_hardening.md` | 本轮 8 段迭代记录与验收结果。 |
| `docs/iterations/README.md` | 追加 Iteration 079 索引行。 |

## 不在本轮范围

- reaper nonce / heartbeat token 判别式。
- `_STOP_REQUESTED` 嵌入式复用 reset。
- 旧 halt 残迹一次性迁移。
- 小说真模型 capstone 实跑（需用户明确授权）。
- drama 站③路线图实现。

## Notes

- 本轮前置结论：没有确认未修 P1/High；本轮是 capstone 前 P2 硬化包。
- 不触碰 `.env`、`data/`、`outputs/`、`小说txt/`；仓库未跟踪 `续写工作台.pptx` 视为用户文件，保持不动。
