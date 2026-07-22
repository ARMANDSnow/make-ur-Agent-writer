# Iteration 149 - 体检报告路径、Job 与归档 CLI 问题闭环

## Context

2026-7-21 与 2026-7-22 两份只读体检报告合并去重后留下三项可复现问题：真视频 submission/asset-upload durable ledger 可跟随祖先目录 symlink 越出 workspace 读写；Web job history 遇到 JSON 巨整数时未 fail-closed，导致 recent-jobs 返回 400 并公开解析器细节；project archive export 的 README 与子命令 help 未说明必需的 `--book <workspace>`。用户要求在独立迭代中定位、修复并确认闭环，随后删除对应体检报告。

## Plan

### Implementation Context
- `must_read`: `src/drama_video.py`, `src/web/jobs.py`, `main.py`, `README.md`, `tests/test_drama_video.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_routes_get.py`, `tests/test_drama_project_archive.py`
- `expected_changes`: `src/drama_video.py`, `src/web/jobs.py`, `main.py`, `README.md`, `tests/test_drama_video.py`, `tests/test_web_jobs_recent.py`, `tests/test_web_routes_get.py`, `tests/test_drama_project_archive.py`, `docs/2026-7-21体检报告.md`, `docs/2026-7-22体检报告.md`, `docs/iterations/iteration_149_health_report_path_job_cli_closure.md`, `docs/iterations/README.md`, `docs/AGENT_HANDOFF.md`, `docs/PROJECT_HISTORY.md`
- `do_not_touch`: `.env`、`小说txt/`、私有样本、真实 workspace 内容、`data/`、`outputs/`、`logs/`；不得发起真实文本、图片、视频、TTS、provider task 或 billing 请求；iter143 未知的 20 秒 create 不得重提

1. 将真视频 submission/asset-upload ledger 的 default 与 quality-sample namespace 改为逐分量 dirfd no-follow I/O；读取绑定同一 fd、普通文件与大小上限，写入使用同目录独占临时文件、fsync 和 dirfd-relative 原子替换，路径不安全时 fail-closed。
2. 让 job history 对巨整数等 `json.loads()` 的 `ValueError` 整体降级为空投影，并加入 direct reader 与 HTTP 200/空 jobs/无解析器细节回归。
3. 为 archive export 子命令 help 与 README 增加 canonical `--book <workspace>` 用法，并加入 help 回归。
4. 聚焦回归与多视角审查稳定、唯一 canonical 验收通过后，删除两份已闭环的体检报告；同步 README、handoff 与 history。

## Acceptance

### Review Context
- `correctness_behavior`: 核对 default/quality-sample、submission/asset-upload 四类 ledger 的现有状态机与 once-only 恢复语义不变；坏 job history 只降级当前持久投影且 recent HTTP 保持 200；archive CLI canonical 命令与真实预解析顺序一致
- `security_boundary`: 核对 ledger 的 workspace root、`logs`、sample 目录与最终文件均不跟随 symlink，读写有界且原子，异常不泄露路径/provider 数据；job 巨整数和坏 JSON 不公开解释器细节；全程 mock-only、不触碰保护目录
- `extra_risk_view`: Web、CLI 与付费媒体恢复专项：复核 route 错误投影、archive help 可复制性、submission-unknown/asset-upload unknown 零自动重发，以及多 workspace 路径隔离

- A149-01：祖先 `logs`、`drama_video_samples` 或 sample 目录为 symlink 时，四类 ledger 均拒绝 workspace 外读写；正常 default 与 quality-sample ledger 仍可写、读、替换并保留状态校验。
- A149-02：有界 JSONL 行含 5000 位整数时，`recent_jobs()` 返回 `[]`；recent-jobs HTTP 返回 200 与 `jobs=[]`，响应不包含 `digits`、`set_int_max_str_digits` 或解释器异常正文。
- A149-03：`drama-project-archive export --help` 与 README 明确显示可复制的 `python3 main.py --book <workspace> drama-project-archive export`，现有 export/preflight/import 行为保持兼容。
- A149-04：correctness/behavior、security/boundary 与 Web/CLI/paid-media 专项只读审查完成，主线程复核并关闭所有有效 findings；聚焦测试、py_compile、harness 与 `git diff --check` 通过。
- A149-05：implementation commit 上最终只运行一次 `bash scripts/verify.sh` 并通过，验收等级为 `mock-functional`；不借此宣称真实 provider 已验证。
- A149-06：前三项问题、全部审查和 canonical 验收均闭环后删除 `docs/2026-7-21体检报告.md` 与 `docs/2026-7-22体检报告.md`，README SOP、handoff、history 与 iteration 索引同步且收官一致性检查通过。

## Implementation Notes

- 新增统一 video ledger dirfd 层：从 workspace root 开始逐级 `O_DIRECTORY|O_NOFOLLOW` 打开或创建 `logs/drama_video_samples/<sample>`，最终读取要求普通文件且不超过 64 KiB，before/after identity 稳定；写入在同一 dirfd 下使用随机独占临时文件、file/directory fsync 与 relative `os.replace()`。
- 三路初审共同发现 `RequestNotSentError` 的旧 path-based `unlink()` 未纳入新边界：祖先在 marker 写入后被换成外部 symlink 时可能越界删除。主线程确认后新增 dirfd-safe delete、最终普通文件检查、relative unlink 与 fsync，并补 default/quality-sample ancestor-swap 回归。
- security 复核要求把计划中声明的 final-target no-follow 与 bounded read 变成直接证据；新增最终 symlink 对 read/write/delete 全拒绝、外部字节不变，以及超限文件在 `os.read` 前拒绝的回归。
- correctness 初审发现 archive help 将 `--book` 误写为必须前置；实际 `_consume_book_pre_arg` 允许任意位置。最终文案保留前置 canonical 示例并明确 `may appear anywhere`。
- 主线程迁移 reader 后及时补回原先由 path helper 隐式提供的 `episode_no == 1` 校验，并加入直接回归。
- job JSONL 在 `json.loads()` 边界捕获其普通 `ValueError` 子类，保持整份坏源空投影；未扩张为 schema 重构。
- 首次 canonical 在 2870 项中的 paid-recovery vocabulary 测试失败：该测试 patch 旧 path helper 将 ledger 路由到临时文件，新安全 reader 按设计只走 workspace dirfd，因此返回缺失。生产行为无异常；将测试 fixture 改为 patch `paths.WORKSPACE_DIR` 并通过真实 workspace-relative ledger 路径验证所有声明状态，作为实现后合理范围变化。

## Acceptance Result

- `A149-01` 通过：default/quality-sample 的 submission/asset-upload 四类 ledger 统一使用逐级 dirfd no-follow；正常创建/替换/读取、`episode_no == 1` 与状态词表回归通过。祖先/final symlink、祖先 swap、特殊目标与超限文件均 fail-closed，workspace 外同名字节保持不变；两处 `RequestNotSent` 清理改走 safe unlink，unknown 仍零自动重提。
- `A149-02` 通过：5000 位整数 JSONL 的 direct `recent_jobs()` 返回 `[]`；HTTP recent-jobs 返回 200 与 `jobs=[]`，响应不含 `digits` 或 `set_int_max_str_digits`。
- `A149-03` 通过：export 子命令 help 与 README 均展示 `python3 main.py --book <workspace> drama-project-archive export`；help 如实说明 selector 可位于任意位置，既有 export/preflight/import round-trip 回归通过。
- `A149-04` 通过：py_compile、harness、`git diff --check` 与 176 项聚焦回归通过。correctness/behavior、security/boundary、Web/CLI/paid-media 三路独立只读审查共关闭 P2 cleanup race、P3 help 语义与 P3 final-target/size 证据覆盖，最终无未处理 P0-P3；主线程逐项复核。
- `A149-05` 通过：首次 canonical 在 2870 项中的旧测试 fixture seam 失败，修复并形成新 implementation commit 后按失败范围重验；accepted implementation `048beeac853afd4dbf1ad90e8fd23d904ea79b65` 上最终 `bash scripts/verify.sh` exit 0，2870 tests、15 steps、439 秒、run `63e08c4becd044bcb5bfd49acc36a34a`，tree `5b9dfd106f5d7eae6ae1f5fcc95583f336b20f6b`，`tracked_scope_clean=true`，结论 `mock-functional` / `canonical-mock-offline`，local-drama 子步骤为 `local-e2e`，`provider_validated=false`。
- `A149-06` 通过：前三项问题、审查和 canonical 均闭环后删除两份未跟踪体检报告；README SOP、handoff、history 与 iteration 索引已同步，收官一致性检查通过。

### Knowledge Promotion
- `decision`: `none`
- `destination`: `none`
- `reason`: 本轮落实的逐级 no-follow、坏持久源 fail-closed 与 unknown 零自动重提均已是 AGENTS、handoff/history 和既有 store 的长期规则；没有新增需要晋升的架构决策。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/drama_video.py` | submission/asset-upload ledger 改为有界 dirfd no-follow read/write/delete，保留 episode 与 once-only 状态边界 |
| `src/web/jobs.py` | 巨整数等 JSON `ValueError` 整体降级为空 job 投影 |
| `main.py` | archive export help 增加必需 workspace selector、canonical 命令与真实位置语义 |
| `README.md` | CLI 速查补可复制的 archive export 命令 |
| `tests/test_drama_video.py` | 增加祖先/final symlink、cleanup swap、oversize、episode 边界回归 |
| `tests/test_web_jobs_recent.py` | 增加 5000 位整数 direct reader 回归 |
| `tests/test_web_routes_get.py` | 增加 recent-jobs HTTP 200、空 jobs 与无解析器泄漏回归 |
| `tests/test_drama_project_archive.py` | 增加 export help/usage 回归 |
| `tests/test_drama_paid_recovery_states.py` | 将 video ledger 状态词表测试迁移到真实 dirfd workspace fixture |
| `docs/iterations/README.md` | 追加 iter149 索引 |
| `docs/2026-7-21体检报告.md`、`docs/2026-7-22体检报告.md` | 对应 findings 验收闭环后删除 |
| `docs/AGENT_HANDOFF.md`、`docs/PROJECT_HISTORY.md` | 同步 accepted evidence、当前缺口与阶段里程碑 |
| 本文档 | 记录计划、实施选择、审查 findings 与验收证据 |

## 不在本轮范围

- 不处理 iter148 已登记的 archive 签名/MAC、staging GC、掉电耐久与非合作本机写者残余。
- 不访问或重试 iter143 状态不明的 20 秒真视频 create，不做任何真 provider/TTS/媒体请求。
- 不扩展真实多集、小说 10–20 章 capstone 或公网多租户能力。

## Notes

两份体检报告是未跟踪的用户文件；仅在对应 findings 通过本轮 canonical 验收并完成文档证据回填后删除。
