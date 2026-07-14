# Iteration 102 - 标准验收隔离与审计基线收口

## Context

2026-07-14 体检确认：iter 101 后的 harness 提交 `5b71fdc` 尚未进入 iteration/handoff；标准 `verify.sh` 还会继承 ambient workspace、物理读取 `.env`，acceptance evidence 也未绑定 workspace scope 与 accepted implementation commit。本轮先恢复唯一标准验收入口的安全性与可审计性，再进入后续 fake-provider E2E。

## Plan

1. canonical `verify.sh` 拒绝 `--book` 与未知参数，清除 ambient workspace，并仅在系统临时目录运行 synthetic mock workspace。
2. 增加 verify 专用 dotenv 短路，保证任何 Python 进程都不打开项目 `.env`。
3. acceptance evidence 升级为 v2，记录验收等级、隔离 scope、git HEAD/tree 与 tracked cleanliness，并在 start/finish 之间复核身份。
4. handoff 增加 accepted implementation commit；checker 在无 active iteration 时阻断收官后实现/测试/workflow 漂移，并忽略普通未跟踪 docs 报告。
5. 定义四级验收术语与 Acceptance ID 闭包；更新 repository-local iter skills 和相关文档。
6. 仅补验并正式接纳 `5b71fdc` 及本轮变更；不改写 iter 101 历史数字。

## Acceptance

- `A102-01`：ambient `WORKSPACE_NAME`/`BOOK` 不进入 canonical pipeline；`--book`/未知参数在 evidence 与 workspace 访问前退出 64。
- `A102-02`：全部 mock pipeline 步骤只访问带本轮 marker 的临时 synthetic workspace，成功/失败均安全清理，私有 sentinel workspace 不变。
- `A102-03`：`DRAGON_RAJA_SKIP_DOTENV=1` 在 dotenv import/路径访问前短路，并有子进程级未调用证明。
- `A102-04`：acceptance schema v2 记录 `mock-functional`、`canonical-mock-offline`、`isolated-mock`、HEAD/tree/cleanliness；不含书名、路径、正文或凭据。
- `A102-05`：accepted commit 缺失、非祖先或无 active iter 时的受保护漂移均 fail-closed；active next iter 与 docs-only 收官通过。
- `A102-06`：Acceptance ID 唯一且在收官结果逐项闭合；旧 evidence 可被新运行安全覆盖，既有 symlink/concurrency/missing-venv/zero-test 守门保持。
- 聚焦回归、相关静态检查、三视角只读审查通过；修复 findings 后最终只运行一次 `bash scripts/verify.sh`，全程 mock/offline。

## Implementation Notes

- canonical verify 在参数解析阶段拒绝任何非 `--help` 参数，随后清除 ambient book 环境；所有 main 步骤通过 `run_isolated_cli.py` 将唯一 workspace root 定向到 `mktemp` 目录，输入仅为固定 `<用户填写正文>` synthetic fixture。
- dotenv 使用双层物理短路：项目 loader 的 `DRAGON_RAJA_SKIP_DOTENV=1` 与 python-dotenv/LiteLLM 的 `PYTHON_DOTENV_DISABLED=1`，均在任何 Python 进程前设置。
- evidence v2 固定 `mock-functional` / `canonical-mock-offline` / `isolated-mock`，start/finish 绑定 HEAD/tree；除普通未跟踪 `docs/**` 报告外，tracked dirty 和任何未跟踪实现/workflow 都会阻断。
- checker 新增 accepted implementation commit 祖先/漂移校验与 102 起的 Acceptance ID 闭包。收官 tracked allowlist 仅含 README、handoff、history、iteration index 与当轮 iteration 文档。
- 首轮审查确认并修复：Git quote 导致中文/空格路径绕过、allowlist 过宽、后置 `--book legacy` 逃逸、cleanup marker symlink、LiteLLM 自行加载 dotenv、ID 可整体省略以及 wrapper 未真实执行测试等 findings。
- 首次全量验收暴露短剧图片阶段会将默认 `AI_DRAW_MODEL` 回写到进程环境，污染后续测试。已改为仅在读取点使用默认值，并增加不修改进程环境的回归；修复后按 workflow 重跑统一验收。

## Acceptance Result

<待 iter-finish 回填 A102-01 至 A102-06、测试数、统一验收和审查结论。>

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `scripts/verify.sh`、`scripts/run_isolated_cli.py`、`src/config.py` | 隔离 synthetic workspace、拒绝 named verify、双层 dotenv 短路和安全清理。 |
| `scripts/write_acceptance.py`、`scripts/check_agent_harness.py` | evidence v2、git identity/cleanliness、accepted commit 与 Acceptance ID 闭包。 |
| `tests/test_agent_harness.py`、`tests/test_mock_offline.py`、`tests/test_smoke_scripts.py` | 参数、真实 wrapper、dotenv、Git Unicode/dirty、evidence 与兼容回归。 |
| `src/drama_multimodal_smoke.py`、`tests/test_drama_multimodal_smoke.py` | 消除默认图片模型对进程环境的副作用，封住全量测试顺序污染。 |
| `AGENTS.md`、`.agents/skills/`、handoff、iteration 索引 | 验收等级、两提交收官、当前 active iteration 与审计入口。 |

## 不在本轮范围

- local fake-provider HTTP E2E、跨进程 callback、crash/restart 矩阵与付费状态穷举。
- D-03 单集角色投影、统一 paid-attempt ledger 重构、任何真实 provider 请求。

## Notes

- 本轮显式使用 repository-local `iter-start`；实施完成后必须使用 `iter-finish`。
- 只 commit，不 push；未跟踪体检报告保持用户所有，不暂存。
