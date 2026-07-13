# Iteration 096 - LiteLLM 严格离线 Mock

## Context

项目默认以 `OPENAI_MODEL=mock` 完成单测、`verify.sh` 和本地工程验证，现有硬门已阻止计费模型调用；但 LiteLLM 在首次导入时仍可能尝试刷新公开 model cost map，网络不可用时再回落到内置副本。`scripts/verify.sh` 也会加载为真实模型准备的代理适配逻辑，因此“无计费调用”目前不能等同于“物理零网络”。

本轮将 mock 模式收紧为确定性的严格离线边界：在 LiteLLM 首次导入前固定使用本地 cost map，统一 unittest、pytest、CLI、Web 与验证脚本的 mock 入口，并用可证明的网络阻断回归防止后续导入顺序或环境加载重新引入外联。真实模型路径继续保留既有 provider、代理和 cost map 行为，不触碰 `.env`，不运行任何真实文本、生图或视频请求。

## Plan

1. 梳理 LiteLLM 首次导入、dotenv 重载、proxy setup 与 mock 判定顺序，建立单一的严格离线 mock 环境初始化入口。
2. 在 `OPENAI_MODEL=mock` 时于任何 LiteLLM 导入前设置并锁定 `LITELLM_LOCAL_MODEL_COST_MAP=true`，同时避免执行仅供真实 provider 使用的代理探测或其它网络准备逻辑。
3. 对齐 `tests/__init__.py`、`tests/conftest.py`、`scripts/verify.sh` 及 CLI/Web mock 启动路径，防止本地 `.env`、父进程环境或导入顺序突破离线硬门。
4. 增加子进程级和入口级回归：在网络连接被显式禁止的环境中验证 LiteLLM 导入、canonical 单测、preflight 与 verify 关键路径不尝试外联，并验证真实模式不会被错误强制为本地 cost map。
5. 更新 AGENTS、README/README_EN、handoff 与相关运行说明，明确 mock 为物理零网络、真实模式仍需单独授权；完成聚焦检查和只读审查后再运行一次标准全量验收。

## Acceptance

- `OPENAI_MODEL=mock` 下，在首次导入 LiteLLM 之前即可观察到 `LITELLM_LOCAL_MODEL_COST_MAP=true`，且 `.env` 或父进程中的冲突值不能使 mock 路径恢复远端 cost map 刷新。
- unittest discover、pytest、`scripts/verify.sh`、mock preflight、CLI 与本地 Web 的 mock 初始化共享同一离线语义，不依赖调用者手工导出额外环境变量。
- 网络阻断回归能捕获 DNS、TCP/HTTP 和代理探测等意外外联；覆盖 LiteLLM 已安装与缺失时的 graceful fallback，并在干净子进程中验证导入顺序。
- 非 mock 配置不被全局强制为严格离线，既有真实 provider 路由、代理适配和授权边界保持兼容；本轮不读取或修改 `.env`。
- README 中“mock 无计费调用但可能刷新 cost map”的旧表述改为严格离线事实，中英文说明、AGENTS 与 handoff 保持一致。
- 聚焦测试、Python/shell 静态检查、`git diff --check`、最终 canonical、`bash scripts/verify.sh` 与 mock preflight 全部通过；真实文本、生图、视频和其它计费 provider 请求数均为 0。

## Implementation Notes

- 起始基线：iter 095 收官为 canonical 1942 tests OK，`verify.sh` exit 0，mock preflight 无 WARN/FATAL。
- 当前 `src/llm_client.py` 在模块导入阶段先执行 `_setup_proxy()`，随后导入 LiteLLM；现有测试隔离主要清理模型配置和凭据，尚未统一固定 `LITELLM_LOCAL_MODEL_COST_MAP`。
- 立项前工作树 clean；实现与聚焦验证均保持 mock，未运行真实模型或媒体请求。
- 实现将 mock/真实分流下沉到 `src.config.prepare_litellm_environment()`：先加载既有配置并解析全局有效模型，mock 覆盖冲突的 cost map 环境值且跳过 `_setup_proxy()`，真实模式不写入该开关并保留原代理逻辑。
- unittest、pytest、`verify.sh` 与短剧 mock 包装脚本在进程启动前显式钉住本地 cost map；新增干净子进程审计钩子，禁止并记录 DNS/TCP/urllib 事件后导入完整 `main`，同时核对 LiteLLM source info 为 env-forced local。
- 主线程预审补强 pytest collection 边界：`conftest.py` 在测试模块导入前即设置 mock、local cost map 并清理真实凭据，autouse fixture 复用同一函数处理测试间环境变更。
- 多视角初审发现两个真实离线缺口：默认 mock 的短剧模块入口在 pin 前间接导入 LLM 栈，且 mock token 统计在冷缓存可能由 tiktoken 下载编码。修复为模块 CLI 提前 pin + programmatic lazy import，并让 mock 使用确定性本地 token estimate；网络审计现执行 mock completion、临时根 preflight、Web import、两个直接模块入口和真实分支 fake-LiteLLM 导入。
- 最终 canonical 首跑暴露既有 NovelClient 连接测试的跨平台超时分支：裸 `TimeoutError` 未归一化，且测试真实连接 loopback 死端口。按铁律⑥记录范围扩展：客户端统一映射为 `NovelApiError(status=0)`，测试改为确定性 mock timeout，不再发起该网络连接。
- 最终标准 `verify.sh` 首跑又暴露解释器漂移：脚本裸用系统 `python3`，在当前机器解析为 Python 3.14 而 canonical 使用项目 Python 3.13，造成依赖加载错误。脚本现优先 `.venv/bin/python3`、仅在虚拟环境不存在时 fallback，并有静态回归防止 unittest 退回裸系统解释器。
- 首轮聚焦回归：配置/LiteLLM/preflight/入口影响面 unittest 94 项通过；新增离线、环境和脚本用例 pytest 24 项通过；shell syntax 与 `git diff --check` 通过。随后按 `iter-finish` 顺序完成只读审查、修复和最终全量闸门，结果见下一节。

## Acceptance Result

- **结果：通过。** mock 模式现在会在 LiteLLM 首次导入前强制 `LITELLM_LOCAL_MODEL_COST_MAP=true`、跳过真实 provider 的 proxy setup，并让 token 统计走确定性本地 estimate；真实模式保留原 cost map、代理和 provider 分支。
- **聚焦回归：** 审查修复后的 config/LiteLLM/context/preflight/入口组合以 unittest **92 项 OK**、poisoned-parent pytest **92 passed**；NovelClient timeout 聚焦 **12 项 OK**；verify 解释器修复聚焦 **17 项 OK**。Python compile、shell syntax 和 `git diff --check` 均通过。
- **离线证据：** 子进程 audit hook 同时阻断/记录 DNS、TCP 与 urllib；在冷 tiktoken cache 下导入完整 CLI/Web、执行 mock `complete_text`、临时根 preflight、两个短剧模块入口和 programmatic import，均未观察到网络事件。LiteLLM 缺失 fallback 与 fake-LiteLLM 真实分支也有覆盖。
- **只读审查：** correctness、security/boundary、tests/entry 三个视角初审分别指出短剧入口导入顺序、tiktoken 冷下载和真实分支/动态入口覆盖不足；修复后第二轮均为 **PASS**，无未解决 finding。security 审查代理曾偏离约束执行一次未配置 `import litellm`，仅尝试刷新公开 cost map 后离线回退；未调用模型/provider、未读取私有目录，已将其作为审查流程偏差记录。
- **最终全量：** canonical `.venv/bin/python -m unittest discover -s tests` 为 **1952 tests OK**（71.023s）。首跑发现并修复 NovelClient 裸 timeout/真实 loopback 测试后重验通过。
- **标准验证：** 修复系统 Python 漂移后，`bash scripts/verify.sh` 使用项目虚拟环境，内部 **1952 tests OK**，normalize、split、auto-pipeline、status、manifest/report、review summary、report check 与 cost estimate 全链 exit 0。LiteLLM 仅提示缺少可选 `botocore` 的本地能力，不含网络/provider 请求。
- **Preflight：** `OPENAI_MODEL=mock LITELLM_LOCAL_MODEL_COST_MAP=true .venv/bin/python main.py preflight` exit 0，`PREFLIGHT: ok`，项目级 FATAL/WARN 均为 none。
- **调用边界：** 本轮真实文本、生图、视频和其它计费 provider 请求均为 **0**；未读取或修改 `.env`。保留缺口仍是真多模态分段校准、小说 capstone、文风阈值与 100 集只读查询性能，与严格离线 mock 无关。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `docs/iterations/iteration_096_litellm_strict_offline_mock.md` | 本轮八段计划与后续实施、验收记录。 |
| `docs/iterations/README.md` | 追加 Iteration 096 索引。 |
| `src/config.py`、`src/llm_client.py` | 首次导入前统一判定 mock、固定本地 cost map，并仅为真实模式执行代理适配。 |
| `src/context_budget.py` | mock token 统计改为确定性本地 estimate，避免冷缓存初始化 tiktoken。 |
| `src/drama_smoke.py`、`src/drama_multimodal_smoke.py` | 模块 CLI 提前 pin mock，programmatic 路径延迟导入 LLM 栈。 |
| `scripts/verify.sh`、`scripts/drama_smoke.sh`、`scripts/drama_multimodal_smoke.sh` | 官方 mock 入口启动前钉住离线环境，verify 移除代理 socket 探测。 |
| `integrations/novel_client/client.py`、`tests/test_novel_client.py` | 将裸 timeout 归一化并移除测试中的真实 loopback 连接。 |
| `tests/test_mock_offline.py`、`tests/test_env_isolation.py`、`tests/test_context_budget.py`、`tests/test_smoke_scripts.py`、`tests/__init__.py`、`tests/conftest.py` | 配置、导入顺序、真实模式兼容、冷缓存、网络审计和入口回归。 |
| `AGENTS.md`、`README.md`、`README_EN.md` | 同步严格离线 mock 的中英文运行契约。 |

## 不在本轮范围

- 未经明确授权的真实文本、生图、视频调用，以及真实 provider 的费用、时延或质量校准。
- 升级或锁定 LiteLLM 版本、替换模型路由框架、修改真实 provider 的代理/重试/超时策略。
- 将所有第三方依赖或操作系统服务改造成通用 air-gap 发行版；本轮边界是项目的 mock 运行与验证路径。
- 小说 10-20 章 capstone、短剧真实多模态校准、episode 2+ 视频和 100 集查询性能优化。

## Notes

- 本轮显式使用 `iter-start`；实施完成后使用 `iter-finish 096` 收官。
- README 的项目状态表仅在里程碑范围或状态确实变化时更新；收官时需就地更新“流水线 SOP（实时状态）”的最近更新时间。
- 收官提交信息草案：`docs(iter096): 收官严格离线 mock（1952 tests + 三视角审查 + SOP/handoff 同步）`。
