# Iteration 144 - 体检报告问题核验与闭环修复

## Context

用户要求核对 `docs/` 下 2026-07-14 至 2026-07-20 的七份体检报告，判断各项问题在当前 HEAD 是否仍存在，修复仍成立的问题，并在问题得到自动化证据与统一验收确认后删除对应报告。iter 102–143 已吸收部分早期 findings；本轮聚焦当前仍可能成立的 Insights、generic Web job、LLM retry、pricing snapshot 与直接测试入口 mock 隔离问题，不触发任何真实 provider。

## Plan

### Implementation Context
- `must_read`: `src/web/drama_insights.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/drama_media_pricing.py`, `src/config.py`, `tests/test_drama_insights.py`, `tests/test_web_jobs_dispatch.py`, `tests/test_web_jobs_recent.py`, `tests/test_llm_client_retry.py`, `tests/test_drama_media_pricing.py`, `tests/test_mock_offline.py`, `scripts/verify.sh`
- `expected_changes`: `src/web/drama_insights.py`, `src/web/jobs.py`, `src/llm_client.py`, `src/drama_media_pricing.py`, `src/config.py`, `tests/test_drama_insights.py`, `tests/test_web_jobs_dispatch.py`, `tests/test_web_jobs_recent.py`, `tests/test_llm_client_retry.py`, `tests/test_drama_media_pricing.py`, `tests/test_mock_offline.py`, `docs/iterations/iteration_144_health_report_findings_closure.md`, `docs/iterations/README.md`
- `do_not_touch`: 不读取或修改 `.env`、`小说txt/`、私有 `workspaces/`、`data/`、`outputs/`、`logs/`；不运行真文本、真图片、真视频、真 TTS 或账单请求；七份未跟踪体检报告仅作为只读审计输入，直到对应 findings 全部闭合后才删除

1. 建立七份报告的 finding 去重矩阵，以当前代码、测试和相关 iteration 证据判断 `已修复 / 仍存在 / 已被后续设计取代`。
2. 对仍存在的问题先补最小失败回归，再修复 no-follow、有界读取、公开投影、重试、快照一致性与 mock 子进程隔离。
3. 聚焦回归后执行独立 correctness、security/boundary、Web/runner/pricing 风险审查；修复确认成立的 findings。
4. 仅在最终统一验收通过并逐项闭合 Acceptance 后删除七份对应体检报告。

## Acceptance

### Review Context
- `correctness_behavior`: 核对七份报告的每个 finding 均有当前状态与证据；Insights、job history、LLM retry、pricing collector 和直接测试子进程的正常行为与兼容路径保持正确，回归覆盖真实报告复现条件
- `security_boundary`: canonical 文件拒绝 symlink/特殊文件/竞态和超限输入，坏源 fail-closed 且不返回 partial data；公开 job 投影与日志不泄露凭据、prompt、签名 URL、响应正文或本机路径；提交未知的付费文本请求不自动重发；mock 测试不物理读取 dotenv
- `extra_risk_view`: Web/runner/pricing 专项检查 workspace no-follow、JSONL append/read 并发、跨 ledger snapshot、直接 CLI 子进程与 paid retry 状态分类

- **A144-01**：七份报告的所有 findings 完成去重核验，并在 `Implementation Notes` 记录当前状态及代码、测试或 iteration 证据。
- **A144-02**：Drama Insights 对 episode/LLM 数据执行 no-follow、有界、普通文件校验；symlink、特殊文件、竞态、坏 JSON 或超限时返回明确 degraded 空投影，不泄露 workspace 外派生信息。
- **A144-03**：generic Web job 使用 step-aware typed retry 参数与有界脱敏公开投影；持久 JSONL no-follow、有界、身份复核，异常/结果/stderr 不泄露敏感文本或本机路径。
- **A144-04**：LLM transport 明确区分可证明 `not_sent` 与 `submission_unknown`；真实/可能计费请求在 timeout、断流或未知网关终态后不自动重发，既有安全重试仅保留在可证明未发送或 mock 路径。
- **A144-05**：pricing collector 在可信 workspace lock 与稳定 namespace/target identity 下读取一致快照；任一坏源、缺失、竞态或超限返回空的 degraded 汇总，UI 不显示 partial totals。
- **A144-06**：直接 `unittest`/IDE 启动的测试子进程继承全 provider mock 与 skip-dotenv 边界，且回归证明 dotenv loader 未被访问、无 provider/network 动作。
- **A144-07**：correctness、security/boundary 与 Web/runner/pricing 三个独立只读视角无未处理有效 finding，聚焦检查与 `git diff --check` 通过。
- **A144-08**：implementation commit 上最终仅运行一次 `bash scripts/verify.sh` 并得到 schema v2 `mock-functional` / `canonical-mock-offline` passed；七份体检报告随后删除，README、handoff、history 与本轮文档完成 docs-only 收官同步。

## Implementation Notes

### 七份报告去重核验

| 报告 | 原 finding | 当前核验与处置 |
|---|---|---|
| 2026-07-14 | D-01/D-02/D-04/D-05 canonical workspace、dotenv、evidence/iteration 漂移 | 已由 iter102 的 synthetic workspace、skip-dotenv、accepted commit/tree 与无 `--book` canonical 入口闭合；当前 harness 与测试继续覆盖 |
| 2026-07-14 | D-03 单集角色数误用整季角色库 | 已由 iter105 的 episode-scoped character projection 闭合，当前相关回归通过 |
| 2026-07-15/16/17/19/20 | 五站/通用文本 timeout-after-send、断流自动重发 | 当前仍存在；本轮新增 submission-unknown 分类，timeout/connection/mid-stream/429 均不自动重发，仅明确 `request_not_sent` 可重试，并修正 cache downgrade 旁路 |
| 2026-07-15/16/17/19/20 | generic Web job params/error/result/stderr 泄露、JSONL symlink 越界读写与无界读取 | 当前仍存在；本轮改为 typed retry-param allowlist、受控结果投影、稳定错误码、stderr 不打印异常正文/traceback，并以逐级 no-follow dirfd、普通文件、4 MiB/5000 行/64 KiB 单行上限读写，坏源整体空返回 |
| 2026-07-15/16 | submitted 状态仍可下载旧视频 | 当前仍存在；本轮 `read_video()` 在任何 incomplete submission 下拒绝旧产物，固定 Web 文件端点返回 409 |
| 2026-07-15/16 | “数据不出本机”与真模型外发描述冲突 | 已由当前 `PRODUCT_SPEC.md` 的“mock 不上传、真模型向用户配置 provider 发送任务上下文”表述闭合 |
| 2026-07-15/16 | `xcrun_db` 名称无条件豁免 | 当前测试 helper 仍存在；本轮移除名称豁免，任何残留项都失败，并补同名目录不得豁免回归 |
| 2026-07-15/16 | staged/已提交 whitespace 未被 `git diff --check` 覆盖 | 当前 workflow 仍存在；本轮将两处收官命令升级为 `git diff --check HEAD`，并由 harness 强制该 marker |
| 2026-07-16/17 | 短剧产品 SOP 停在 iter110 | 已由 iter111 起连续实时同步闭合；当前 README 为 iter143 状态 |
| 2026-07-17 | 回编旧集不级联 stale 后续集/媒体 | 当前仍存在；本轮为 episode 2+ setup 冻结父集 accepted input/episode revision，`is_episode_stale()` 递归校验祖先链，旧集重组后后代立即 stale，后代 assembly/季包/媒体既有 freshness gate 随之阻断 |
| 2026-07-17 | HEAD/iter124 尚未进入 accepted evidence | 属于当时 active iteration 状态，iter124 后已按 canonical 收官；当前 iter144 由 harness 正确识别为 active |
| 2026-07-17 | episode 2+ mock storyboard 复用 episode 1 | 已由 iter124 的 episode-local mainline/hook/rewrite 修复闭合 |
| 2026-07-17 | 当时并发 iter124 聚焦失败 | 属于未提交 active 状态，iter124 最终修复并 canonical 通过；当前无法复现 |
| 2026-07-18/19/20 | 旧 Drama Insights symlink、特殊文件、坏 JSON 与无界资源 | 当前仍存在；本轮改为逐级 no-follow dirfd、普通文件与读前后 identity/content SHA-256 复核，先拒绝非 canonical episode，再限制 namespace、collector 总字节、单文件、行数、单行与 JSON 深度，任一坏源返回 degraded 空投影 |
| 2026-07-18/19/20 | pricing 跨 ledger 非一致快照、坏源 partial totals | 当前仍存在；本轮对齐 lifecycle metrics，在 workspace lock 中冻结 namespace 与实际读取 bytes 的 content token，加入 collector 总字节预算并在读后复核，任一 invalid/竞态/超限返回空 degraded |
| 2026-07-20 | 直接 unittest/IDE 子进程未物理跳过 dotenv | 当前仍存在；本轮由 `tests/__init__.py` 向子进程固定 skip-dotenv、所有 provider mock 与 local cost map，并以伪 dotenv loader、网络哨兵回归 |

实现范围相对 Plan 扩展到 `src/drama_video.py`、`src/drama_planner.py`、`src/drama_schemas.py`、`src/drama_store.py`、`src/web/routes.py`、`.agents/skills/iter-finish/SKILL.md`、`scripts/check_agent_harness.py` 及对应测试，因为逐份回溯确认 2026-07-15/16 的旧视频下载、2026-07-17 的祖先 stale、`xcrun_db` 与 staged whitespace finding 未被最新报告继续携带但仍可复现。未触碰真模型或私有数据。

### 多视角审查与修复

- correctness 首轮发现 transport 429/cache downgrade、retry 参数值等价与敏感 token 残余；修复为仅 `request_not_sent` 自动重试、严格 `projected == params` 且统一 credential guard。最终复核无 finding。
- security/boundary 首轮发现 hostile inherited `SKIP_DOTENV` 可绕过测试 mock pin、Insights stat-only ABA、非 `sk-` 凭据投影与 blocking flock；修复判定顺序、content SHA-256、常见凭据 grammar 与 `LOCK_NB`。最终复核无 finding。
- Web/runner/pricing 首轮发现 pricing 实际读取未绑定 frozen bytes，末轮又发现多文件累计 I/O 缺少 collector 总预算；修复实际 bytes token、canonical prefilter 与 16 MiB cumulative cap，并补 fail-closed 回归。最终复核无 finding。

## Acceptance Result

验收结论：**mock-functional**。未运行真实文本、图片、视频、TTS、账单或 provider 请求。

- **A144-01 closed**：已在本文件“七份报告去重核验”逐项记录 2026-07-14 至 07-20 findings 的当前状态、后续 iteration 证据与本轮处置；复核同时找回了未被最新报告继续携带的旧视频、祖先 stale、`xcrun_db` 与 staged whitespace 残余。
- **A144-02 closed**：Insights 使用逐级 no-follow dirfd、普通文件/非阻塞打开、实际 bytes SHA-256 frozen token、末次 namespace 重扫、canonical episode 预过滤，以及 namespace/16 MiB 总字节/单文件/行/JSON 深度上限；任一坏源整体 `degraded` 且无 partial totals。
- **A144-03 closed**：generic Web job 使用 step-aware typed allowlist、完整投影等价、credential grammar 与稳定错误码；JSONL 使用 no-follow、普通文件、非阻塞文件锁和总量/行数/单行上限，同进程读写由短临界区串行化；stderr、结果与持久记录不公开原异常、路径、URL、prompt 或凭据。
- **A144-04 closed**：LLM timeout、connection、429、断流与未知 gateway 终态均归为 submission unknown，不自动重发；只有异常显式 `request_not_sent=True` 才保留自动重试，cache-control downgrade 也只接受明确 provider rejection。
- **A144-05 closed**：pricing collector 在 workspace lock 中冻结 namespace 与实际 ledger bytes token，逐 ledger 读取核对 frozen len/SHA，末次重扫，并使用 16 MiB collector 总预算；坏源、ABA、缺失、重复 evidence 或超限均返回空 `degraded`。
- **A144-06 closed**：直接 `unittest`/IDE 入口先于 ambient skip flag 清理 hostile inherited provider 配置并固定 `OPENAI_MODEL/DRAMA_MODEL/PLANNER_MODEL/SD_VIDEO_MODE=mock`、skip-dotenv 与 local cost map；clean/hostile 子进程回归通过。
- **A144-07 closed**：correctness、security/boundary、Web/runner/pricing 三个独立只读视角的首轮 findings 均已修复，最终复核均无明确 finding；实现阶段最后一组相关聚焦回归 175 tests OK，job recent 竞态回归 51 tests OK，`py_compile`、harness 与 `git diff --check HEAD` 通过。
- **A144-08 closed**：canonical 第一次在 `b5899ef` 暴露 7 个跨套件兼容/恢复问题，第二次在 `89bc505` 暴露 1 个同进程 job history 读写窗口；均按失败范围修复并重验。最终在 implementation commit `f1564a107fb250abde8d5937ab5756652a60e34f` 上 `bash scripts/verify.sh` exit 0：schema v2、`status=passed`、`mock-functional` / `canonical-mock-offline`、2813 tests、15 completed steps、408 秒、run `6ceda28c13cb4235a849dc7f867f4496`、tree `c26e5d125745201b8e4a6d38a6a21047a56ad318`、`tracked_scope_clean=true`。验收后七份体检报告已删除，README/handoff/history 已就地同步。

未修风险：本轮没有残余明确 finding。现有产品级缺口（真实 provider/billing、真 TTS、长时多模态质量、小说 capstone 与公网多租户能力）保持在 handoff，不因本轮 mock 验收升级。

### Knowledge Promotion
- `decision`: `promoted`
- `destination`: `.agents/skills/iter-finish/SKILL.md`
- `reason`: 体检证明仅检查 unstaged diff 会漏掉 staged whitespace；收官聚焦与 docs-only 一致性检查长期统一使用 `git diff --check HEAD`，并由 harness marker 防止回退

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `.agents/skills/iter-finish/SKILL.md`、`scripts/check_agent_harness.py`、`tests/test_agent_harness.py` | 收官 whitespace 检查覆盖 staged diff；收紧 `xcrun_db` 平台临时项豁免 |
| `src/web/drama_insights.py`、`tests/test_drama_insights.py` | Insights no-follow、content token、累计资源有界、坏源 degraded 空投影 |
| `src/web/jobs.py`、`src/web/static.py`、`tests/test_web_jobs_recent.py`、`tests/test_web_jobs_dispatch.py` | typed retry 参数、公开/持久脱敏、JSONL no-follow/非阻塞锁/有界读写、stderr 安全与安全重试 UI |
| `src/llm_client.py`、`tests/test_llm_client_retry.py`、`tests/test_llm_client_streaming.py`、`tests/test_llm_client_cache.py`、`tests/test_iter078_cost_ledger.py` | submission-unknown 不重发与安全重试/账本语义 |
| `src/drama_media_pricing.py`、`tests/test_drama_media_pricing.py` | pricing 锁内 content-token 一致快照、累计预算与坏源空汇总 |
| `src/config.py`、`tests/__init__.py`、`tests/test_mock_offline.py` | 直接单测子进程 hostile env 清理、skip-dotenv/全 mock 继承 |
| `src/drama_video.py`、`tests/test_drama_video.py` | incomplete submission 阻断旧视频下载 |
| `src/drama_planner.py`、`src/drama_schemas.py`、`src/drama_store.py`、`src/web/routes.py`、`tests/test_drama_iter095_core.py` | 父集 accepted revision lineage 与祖先级 stale |
| `docs/iterations/README.md`、本文件 | 登记、核验矩阵与验收证据 |

## 不在本轮范围

真实 provider、真实 billing adapter、媒体主观质量、episode 2+ 真成片、真 TTS、小说 10–20 章 capstone 与公网多租户部署不在本轮范围。

## Notes

本轮只删除已经由当前代码、聚焦回归、独立审查和统一 mock 验收共同证明闭合的体检报告；若任一报告仍含未修风险，则保留该报告并在结果中说明。
