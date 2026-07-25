# Iteration 151 - 体检报告 Workspace、Local Demo 与 Worker 闭环

## Context

用户要求核验并闭环 `docs/2026-7-23体检报告.md`、`docs/2026-7-24体检报告.md`、`docs/2026-7-25体检报告.md` 中去重后的四项正式 finding，并在确认问题均解决后删除这三份未跟踪报告。当前 accepted baseline 为 iter150；live code 仍存在 workspace symlink 越界、Local A-F 刷新后目标丢失、FFmpeg/FFprobe 假就绪和 test-only worker reset 不 drain 四项问题。本轮保持 mock/offline，不扩入报告中的长期残余风险。

## Plan

### Implementation Context
- `must_read`: `src/paths.py`, `src/cli_workspace.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/web/static.py`, `src/drama_local_demo.py`, `tests/test_drama_local_demo.py`, `tests/test_web_hardening.py`, `tests/test_web_routes_post.py`, `tests/test_web_jobs_recent.py`
- `expected_changes`: `src/paths.py`, `src/cli_workspace.py`, `src/web/routes.py`, `src/web/jobs.py`, `src/web/static.py`, `src/drama_local_demo.py`, `tests/test_paths.py`, `tests/test_drama_local_demo.py`, `tests/test_web_hardening.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_jobs_dispatch.py`, `docs/iterations/iteration_151_health_report_workspace_local_demo_worker_closure.md`, `docs/iterations/README.md`
- `do_not_touch`: 不读写 `.env*`、`小说txt/`、私有样本、`data/`、`outputs/`、`logs/`；不运行真模型、真图片、真视频、TTS 或 billing；不删除四项 finding 之外的文件；canonical 验收通过前不删除三份体检报告。

1. 建立共享 nofollow workspace identity 探针，让 CLI selector/show/import、Web 读写 guard 与 job worker 复用，并在写锁/worker 执行前复核身份。
2. 为 `drama-local-demo` 持久化严格验证的 target/source/episode 公共上下文；前端以 source-workspace scoped job ID 恢复轮询，成功单次跳转，历史成功显式找回，失败态不自动重跑。
3. 在创建隔离 workspace 前有界预检 FFmpeg/FFprobe，运行期媒体失败映射为有限领域 blocker；已创建的失败/取消隔离项目保留并通过 job target 可追溯。
4. 跟踪 test worker handle；`reset_for_tests()` cooperative cancel 后有界 join，全部退出才清表，超时 fail closed；修正 fixture teardown 顺序。

## Acceptance

### Review Context
- `correctness_behavior`: 四项 finding 的行为闭环、旧 workspace/job 兼容、Local A-F 刷新/关闭恢复与单次跳转、worker drain 无跨 fixture 写入，并核对三份报告只在最终验收通过后删除。
- `security_boundary`: workspace/canonical 子目录 symlink、identity swap、外部 marker 零读写、job target 严格投影、错误脱敏、test reset 锁序与超时 fail-closed；不得放宽 retry/provider/secret 边界。
- `extra_risk_view`: Web/runner/multi-workspace/media 专项：真实浏览器刷新恢复、390px、FFmpeg/FFprobe preflight、active/recent/detail 一致性与无误跳转。

- **A151-01**：workspace root 或 canonical 子目录为 symlink/特殊文件时不进入 selector，Web/CLI/job 入口 fail closed；外部 synthetic marker 不可读写，正常和部分初始化 workspace 兼容。
- **A151-02**：Local Demo target/source/episode 以专用字段持久化并安全公开，params 仍为空且不可重试；刷新/关闭恢复同一 job，成功单次跳转，历史成功可找回，失败/取消/lost 不误跳转。
- **A151-03**：缺 FFmpeg 或 FFprobe 时 GET blocked、POST 409、零目标 workspace；检查到执行间失效及运行期媒体失败映射为有限 blocker，不泄露路径/stderr。
- **A151-04**：`reset_for_tests()` 等待 worker 退出后才返回；timeout 不清表，thread start failure 无 handle 泄漏，旧 worker 不写入下一 fixture。
- **A151-05**：聚焦测试、py_compile、harness 与 diff check 通过；correctness、security/boundary、Web/runner/multi-workspace/media 三个只读审查无未处理有效 finding；Playwright 桌面与 390px 刷新恢复通过，等级为 `local-e2e`。
- **A151-06**：implementation commit 上唯一一次 `bash scripts/verify.sh` 通过并产生 `mock-functional` canonical 证据；随后删除三份确切体检报告、同步 README/handoff/history，并完成 docs-only 收官 commit。

## Implementation Notes

- A151-01：在 `src/paths.py` 建立 nofollow dirfd workspace identity 与“保留既有 identity、允许新增可选 canonical 目录”的复核语义；CLI、Web selector/guard/overview、写锁和 job worker 统一接入。`start_job()` 在持久写前复核，持久写可能创建 `logs/` 后刷新 worker identity，既关闭可确定替换写入，也保持部分初始化 workspace 兼容。
- A151-02：Local Demo job 增加经 source hash、episode、随机后缀严格验证的安全 target 字段；JSONL、active/recent/detail 同口径公开，旧日志不猜 target。前端 localStorage 只存 source+episode scoped 32 位 job ID；服务端恢复 target，成功单次跳转，历史成功显式打开，失败/取消不跳转。
- A151-03：FFmpeg/FFprobe 各自执行 5 秒、4096 bytes 有界 version probe；GET/POST/worker 三层门禁，`DramaMediaQaError` 与真实 compositor `DramaComposeError` 都收敛为安全 `local_demo_media_failed` blocker，取消仍原样传播。
- A151-04：worker handle 在启动前登记、wrapper finally 清理；test reset cooperative cancel 后在锁外按统一 deadline join，timeout 保留状态并抛错。全仓审计并修正直接 teardown 与 `addCleanup` 的 drain-before-restore 顺序。
- 聚焦回归：288 项相关 unittest 通过；`py_compile` 与 `git diff --check` 通过。Playwright 桌面与 390×844 均实测运行中刷新恢复同一 job；390px 证据 job `87c0bcbc39fc47f78629b3a3f8110faa` 从 72% 恢复并进入 `localdemo_da2868e8_1_ef4dc295` compose，QA 为 `local-e2e`、30.000s、6/6；另一个 job `7fc3b1f9a1914adeb12230168cff7a4c` 实测 `aborted` 后仍停源页且 pending key 清除。
- 三个独立只读审查视角为 correctness、security/boundary、Web/runner/multi-workspace/media；去重后 findings 已全部修复并完成聚焦回归，最终复核结果记录于 Acceptance Result。

## Acceptance Result

待 `iter-finish` 回填。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `docs/PROJECT_HISTORY.md`
- `reason`: workspace identity 的“持久写前复核 + 可选目录创建后刷新”与 test worker 的 drain-before-global-restore 是跨模块长期工程约束，应压缩为阶段级教训；具体逐测证据仍只留在本 iteration。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/paths.py`, `src/cli_workspace.py` | 统一 workspace identity、nofollow 探针、CLI 隔离与替换复核 |
| `src/web/routes.py`, `src/web/jobs.py` | Web/API/write/job guard、Local Demo 安全持久字段、worker registry 与 reset drain |
| `src/web/static.py` | Local Demo 刷新恢复、历史找回、episode 隔离与终态导航 |
| `src/drama_local_demo.py` | FFmpeg/FFprobe 有界预检与运行期安全 blocker |
| `tests/test_paths.py`, `tests/test_cli_integration.py`, `tests/test_web_hardening.py`, `tests/test_web_routes_get.py`, `tests/test_web_routes_post.py` | symlink、identity replacement、零外部读写与 Web guard 回归 |
| `tests/test_drama_local_demo.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_jobs_dispatch.py` | 媒体门禁、target 持久投影、跨 workspace 伪造、worker 生命周期回归 |
| 17 个既有 Web/runner fixture 测试文件 | 统一 teardown/addCleanup 为 drain worker 后恢复全局 workspace/env |

## 不在本轮范围

- 真实 provider/billing/TTS/公网 callback、iter143 unknown 对账、archive 签名/MAC、generic cancel 公网威胁模型与其它报告残余风险。
- 在最后一次 identity 复核后持续替换目录的 hostile、非合作本机 writer；本轮不把 Path 型全仓 I/O 重构为 capability-dirfd。

## Notes

- 三份报告当前未被 Git 跟踪，删除不会形成 deletion diff；删除事实与验收证据由本 iteration 的 Acceptance Result 记录。
- 立项 commit message 草稿：`docs(iter151): 迭代计划 151 立项（体检报告问题闭环）`。
- 实际实现额外修改 17 个既有 fixture 测试文件，仅用于落实 A151-04 已批准的全调用方 teardown 顺序审计，不扩展生产功能范围。
