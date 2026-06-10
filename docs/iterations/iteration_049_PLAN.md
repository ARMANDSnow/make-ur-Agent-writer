# Iteration 049 — Aeloon 插件 + MCP 双轨集成（补齐 `aeloon_plugin` + 服务端 token 闸）

> 把"小说续写系统"以插件形式接入第三方 Agent 平台 **Aeloon-Pro**。本轮在已落地 95% 的 `integrations/` 脚手架（MCP 轨 + host 无关 ops 层，44 测全过，untracked）之上，补齐唯一缺口 **`integrations/aeloon_plugin/`**（Aeloon 原生插件：`/novel` 命令族 + LLM 可调用工具），并给我方 WebUI 加一道 **opt-in 的 bearer token 闸**，把既有脚手架与新测试一起固化进 canonical 套件。不改动续写流水线本身。

## Context

用户希望"在 Aeloon 的 WebUI 里用上我们的续写系统"。经源码调研（私有仓库 `AetherHeart-AI/Aeloon-Pro`，1.0.0 alpha，2026-06-10 仍活跃）确认其集成形态：

- **Aeloon WebUI** 是 React 19 聊天窗口，插件输出渲染为 **GFM Markdown 消息流**（表格/代码块/图片/流式进度），消息里的 `http://` 链接**可点击、新标签页打开**。
- 插件 SDK **没有**自定义面板 / iframe / webview 扩展点 → **做不到"Aeloon 窗口内嵌子窗口"**。
- 因此目标体验 = **在 Aeloon 聊天里用 `/novel` 命令或自然语言驱动四步流程，进度流式刷在聊天里；需要精修（改大纲、看审稿）时点链接跳转到我们自己的工作台页面 `/w/{name}/workbench`**。

**关键现状（本轮接续点）**：此前某轮已起 `integrations/` 脚手架（git untracked），结构扎实：

| 模块 | 完成度 | 要点 |
|---|---|---|
| `novel_client/`（client.py, errors.py） | ✅ 完整 | stdlib `urllib` 同步实现 + `asyncio.to_thread` 异步包装（不阻塞 host 事件循环）；零三方依赖；`run_and_wait()` job 轮询至终态；`Authorization: Bearer` 注入；`workbench_url()` 深链 |
| `novel_ops/`（ops.py, config.py, formatting.py） | ✅ 完整 | 8 个 host 无关 `op_*` 协程（new/prepare/outline/write/auto/status/open/list）；书名三级解析；`emit()` 进度回调；formatting 输出含深链的 Markdown |
| `mcp_server/`（server.py, tools.py） | ✅ 完整 | 8 个 MCP tool，stdio transport，`mcp` SDK 懒加载（不进 mock 套件） |
| **`aeloon_plugin/`** | ❌ **不存在** | 仅在 `integrations/__init__.py` 声明了意图 |
| 测试 | ✅ 44 测全过 | `test_novel_client`(13) + `test_novel_ops`(20) + `test_mcp_tools`(11)，stdlib stub server / FakeClient，无 mcp/aiohttp 依赖 |

用户拍板的 scope：**插件 + MCP 双轨**、交互做到**命令 + LLM 工具**、**可实机验收**（用户本机有 Aeloon-Pro 环境）。

## Plan

### 1. 新建 `integrations/aeloon_plugin/`（本轮主体，补缺口）

设计原则承袭脚手架：**把所有可测逻辑放进 host 无关层，`plugin.py` 只做薄胶水**（Aeloon SDK 仅在 host 进程内可 import，我方仓库测不到）。

- **`commands.py`（host 无关，全可测）** — 命令解析与分发，**不 import Aeloon SDK**：
  - `parse_novel_command(args: str) -> tuple[str, dict]`：把 `/novel new 一句话` / `write 2` / `outline` / `auto` / `status [book]` / `open [book]` / `list` / `prepare` 解析成 `(sub, kwargs)`，含用法错误兜底。
  - `async run_novel_command(sub, kwargs, client, cfg, emit, reply)`：把子命令路由到对应 `novel_ops.op_*`，用 `emit` 透传进度、`reply` 回最终 Markdown。复用 `novel_ops` 与 `formatting`，**零重复逻辑**。
- **`tool_adapter.py`（薄）** — 把 `mcp_server/tools.py` 的 `TOOL_SPECS` 复用成 Aeloon `Tool` 对象（name/description/parameters/`async execute`），execute 内部转调 `tools.dispatch(name, args, client, cfg)`。**一份工具规格喂两个 host**（MCP + Aeloon），杜绝漂移。
- **`plugin.py`（薄胶水，唯一 import SDK 处，不单测）** — `class NovelPlugin(Plugin)`：
  - `register(api)`：`api.register_config_schema(NovelPluginConfig)`；`api.register_command("novel", self._cmd, description=...)`；遍历 `tool_adapter` 注册 LLM 工具。
  - `activate(api)`：从 config 构建 `NovelClient` + `NovelOpsConfig` 存于 self。
  - `_cmd(ctx, args)`：`parse_novel_command` → `run_novel_command(..., emit=ctx.send_progress, reply=ctx.reply)`。
  - `NovelPluginConfig`（pydantic）：`base_url`(默认 `http://127.0.0.1:8765`)、`api_token`、`default_book`、`write_tier`、`write_budget_cny`、`outline_chapters`、`write_chapters`。
- **`aeloon.plugin.json`** — manifest：`id`含`.`（如 `novelcontinuer.dragonraja`）、`entry: "integrations.aeloon_plugin.plugin:NovelPlugin"`、`provides.commands:["novel"]`、`provides.tools:[8 个]`、`requires.aeloon_version`。
- **`__init__.py`** — 导出 `NovelPlugin`、`parse_novel_command`、`run_novel_command`。
- **`README.md`** — 安装（复制到 `~/.aeloon/plugins/novelcontinuer/` 或 setuptools entry point `aeloon.plugins`）、配置、**两进程模型**（先 `python main.py web` 起我方服务，插件再连）、`/novel` 用法表。

> ⚠️ Aeloon 是私有 alpha，SDK 签名（`Plugin`/`PluginAPI.register_command`/`register_tool`/`CommandContext.reply/send_progress`/`Tool`）以**调研材料**为准；实现时须对照用户本机**实际安装版本**校准，差异只会落在 `plugin.py` 薄胶水层与 `tool_adapter.py`。

### 2. 服务端 opt-in bearer token 闸（我方 `src/web/`）

客户端已会发 `Authorization: Bearer`，服务端需对称地认。**默认关闭 → 零影响既有行为与 694 测**。

- **`src/web/auth.py`（新）**：`required_token()` 读 env `NOVEL_API_TOKEN`（经 `config.py`）；`check_request_auth(path, headers) -> dict|None`：token 未设→放行（`None`）；已设且 `path` 命中 `/api/` → 要求 `Authorization: Bearer <token>`，常量时间比对，缺失/不符→返回 401 错误 dict。**非 `/api/` 路径（landing、`/w/`、static）豁免**，保证浏览器深链免 token 直达工作台。
- **接线点**：`routes.dispatch()`（`src/web/routes.py:1451`，唯一咽喉）入口处早返 401 `{"error":"unauthorized"}`。
- **env 命名**与客户端/MCP 既有约定一致：均为 `NOVEL_API_TOKEN`。

### 3. 测试固化（铁律：进 canonical 套件）

- 既有 44 测已在 `tests/`，`unittest discover -s tests` 自动纳入（已确认 mock-clean、不 import mcp）→ 本轮把它们正式计入 canonical。
- **`tests/test_aeloon_plugin.py`（新）**：`parse_novel_command` 全分支路由 + 用法错误；`run_novel_command` 经 `FakeClient`+捕获式 `emit/reply` 跑通各子命令（**不 import Aeloon SDK**，验证薄胶水之下逻辑完整）。
- **`tests/test_web_auth.py`（新）**：token 未设→放行；已设+正确→200；已设+缺失/错误→401；深链 `/w/x/workbench` 豁免。

### 4. 文档与依赖（铁律⑧ 同步）

- `integrations/README.md`（总览）+ `aeloon_plugin/README.md`（安装）+ Aeloon `mcpServers` 与 Claude Code `.mcp.json` 配置片段。
- `integrations/requirements.txt`：`mcp>=1.26.0`（仅 MCP server 可选用；Aeloon SDK 由 host 提供，不 pip 装）。**不污染 core `requirements.txt`**。
- 同步 `README.md` 项目阶段 SOP 表（加"外部集成"行 + 时间戳）、`docs/AGENT_HANDOFF.md` Phase Status、`docs/iterations/README.md` 索引。

## Acceptance

- `OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` 全绿；canonical 694 →（+44 既有 + 新增约 12–16）≈ **750±**，零回归。
- `OPENAI_MODEL=mock python main.py preflight` → ok，FATAL/WARN none。
- **实机（用户授权，mock 模型，双轨）**：
  - 起 `OPENAI_MODEL=mock python main.py web --port 8765`。
  - **MCP 轨**：`python -m integrations.mcp_server.server` 连入 → 调 `novel_create`→`novel_status`→`novel_open_workbench`，返回含深链的 Markdown；浏览器打开 `/w/{name}/workbench` 截图。
  - **Aeloon 轨**：插件装入 `~/.aeloon/plugins/`，Aeloon WebUI 里 `/novel new <一句话>` → 聊天里见**流式进度** → `/novel status` → 点深链跳转落在我方工作台。截 Aeloon 聊天 + 工作台两图。
  - **LLM 工具**：在 Aeloon 里自然语言"帮我接着写一章"能触发 `novel_write_chapters` 工具。
  - **鉴权**：设 `NOVEL_API_TOKEN` 后，带 token 客户端通、裸请求 `/api/*` 得 401，而 `/w/...` 深链仍直达。

## Implementation Notes

- **为何插件/MCP 走 HTTP 而非直接 import 续写包**：续写流水线是**同步、长耗时**（LLM 调用以分钟计），Aeloon/MCP host 是 asyncio——内联运行会阻塞 host 事件循环；且"跳转工作台"本就要求我方 HTTP 服务在跑。故适配器=瘦 HTTP 客户端，我方系统作独立进程，天然支持深链。`novel_client` 已按此实现（`asyncio.to_thread` 卸载阻塞 I/O）。
- **薄胶水边界**：`plugin.py` 是唯一 import Aeloon SDK 的文件，刻意只做"解析 ctx → 调 host 无关函数"，不放业务逻辑——这样 SDK 版本漂移/我方测不到 SDK 都只影响这一薄层，`commands.py`/`tool_adapter.py`/`novel_ops` 全可单测。
- **一份工具规格喂两 host**：`TOOL_SPECS` 同时驱动 MCP `dispatch` 与 Aeloon `Tool`，避免两套 schema 漂移；这也是"命令 + LLM 工具"两种入口共享一套 op 的体现。
- **token 闸 opt-in 的理由**：localhost 单机场景鉴权非必需，但客户端已具备发 token 能力、调研也点名服务端零鉴权风险；用 env 默认关→保 694 测与本地开发零改动，设置后才生效，scope 最小且对称。豁免非 `/api/` 是为了浏览器深链无需带 header 即可打开工作台。
- **迭代插队说明**：048d Notes 曾预定 iter049 做产品打磨（L级 UX/a11y、细纲结构化字段编辑、正文逐章编辑、premise 扩写质量、真模型 smoke、B-M-2）。本轮外部集成插队，理由：`integrations/` 脚手架已落 95% 且处于 untracked 漂移态，趁热补齐 Aeloon 插件并固化测试，避免未跟踪代码长期腐化；产品打磨项整体顺延 **iter050**。

## Acceptance Result

（2026-06-10 执行）

- **测试**：`OPENAI_MODEL=mock .venv/bin/python -m unittest discover -s tests` = **758 OK**（048d 基线 694 → +64：既有 44 集成测纳入 canonical + 新增 20 = `test_aeloon_plugin` 11 + `test_web_auth` 9），零回归。`preflight` = ok，FATAL/WARN none。
- **真实 SDK 自检**（Aeloon `.venv` py3.11 + repo 经 PYTHONPATH 注入）：用 Aeloon 自己的 `load_manifest` 校验 `aeloon.plugin.json`（id/entry 正则过）→ `entry` 导入为真 `Plugin` 子类 → `register()` 注册 `novel` 命令 + `NovelPluginConfig` schema + **8 个真 `aeloon.core.agent.tools.base.Tool`**（mutating / read_only 分级正确）→ 用**真实 `CommandContext`** 跑 `/novel status` handler 产出正确 Markdown。**修正一处**：`PluginAPI` 不在 `_sdk.__init__` 导出（研究材料偏差），改在 `TYPE_CHECKING` 下从 `_sdk.api` 引入（照 Aeloon 自带 Wiki 插件惯例；`plugin.py` 有 `from __future__ import annotations`，注解不在运行时求值）。
- **Aeloon 轨实机加载（部署机制决定性证明）**：`install_into_aeloon.py` 写入 `.pth`（repo root → Aeloon venv site-packages）+ 符号链接（`~/.aeloon/plugins/novel_continuer` → 本包）；随后 Aeloon **自己的** `PluginDiscovery(workspace_dir=~/.aeloon/plugins)` 发现 `novel.continuer`（source `workspace:novel_continuer`）→ `validate_candidate` 零错误 → `load_plugin_class` **仅靠 .pth** import 我方包（PYTHONPATH 只给 aeloon root，未给本 repo）→ 实例化 + `register` = `novel` 命令 + 8 工具。
- **MCP 轨实机往返**：① 对**实时 mock 服务**走 `tools.dispatch`——`novel_create` 真建工作区并跑完 prepare → `novel_status` 阶段推进「② 故事大纲（设定✓）」→ `novel_open_workbench` 出深链 → `novel_list_books` 列出含新书的 4 部。② **真实 `mcp` 客户端 SDK** 启动我方 `python -m integrations.mcp_server.server` 子进程：`initialize` → `tools/list`=8 → `call_tool[novel_list_books / novel_open_workbench]` 命中实时服务返回含深链 Markdown。
- **鉴权**：`test_web_auth` 覆盖 token 未设放行 / 正确通过 / 缺·错·无 scheme→401 / `/w/` 深链与 landing 豁免；`routes.dispatch` 实跑同款。
- **未做（留给用户/后续）**：Aeloon WebUI 聊天气泡**字面截图**需启动并驱动用户本机 WebUI；功能正确性已由 Aeloon 自身 loader + 真实 CommandContext + 真实 mcp 客户端三重实机证明。插件当前**已装**在用户 Aeloon（卸载：`python -m integrations.aeloon_plugin.install_into_aeloon --venv … --uninstall`），可直接 `/novel help`。真模型端到端 smoke（铁律⑥）未跑，需用户授权。

## 文件变更汇总

- `integrations/aeloon_plugin/`（新）：`__init__.py`（SDK-free 导出）、`commands.py`（`parse_novel_command` + `run_novel_command`）、`tool_adapter.py`（复用 `TOOL_SPECS` 建 Aeloon `Tool`）、`plugin.py`（`NovelPlugin` 薄胶水，唯一 import SDK）、`aeloon.plugin.json`（manifest）、`install_into_aeloon.py`（`.pth` + 符号链接安装/卸载）、`README.md`。
- `src/web/auth.py`（新）：opt-in bearer token 闸（env `NOVEL_API_TOKEN`，默认关→零影响既有测）。
- `src/web/routes.py`（改）：`dispatch()` 入口接 `auth.required_token` + `auth.is_authorized`，缺/错 token 返 401；import 行加 `auth`。
- `tests/test_aeloon_plugin.py`（新，11）、`tests/test_web_auth.py`（新，9）。
- `tests/test_novel_client.py` / `test_novel_ops.py` / `test_mcp_tools.py`（既有 untracked 44 测 → 本轮纳入 canonical）。
- `integrations/novel_client/` `novel_ops/` `mcp_server/`（既有脚手架，本轮复用未改）。
- `integrations/README.md`（新，总览）、`integrations/requirements.txt`（新，`mcp` 可选依赖）。
- `docs/AELOON_INTEGRATION.md`（新）：集成与部署权威文档——配置全表 / 是否合 Aeloon main / 详细部署 / 升级 / 排错。
- `docs/iterations/iteration_050_PLAN.md`（新）：048d 顺延的产品打磨包计划稿。
- `README.md` / `docs/AGENT_HANDOFF.md` / `docs/iterations/README.md`（铁律⑧ 同步）。

### 部署机制（实测定死，写给后续）

- Aeloon loader 用纯 `importlib.import_module(entry)` 解析插件，`manager`/`discovery`/`loader` **全程不碰 `sys.path`**（全仓唯一 sys.path 操作是 SkillGraph 自举）。故 workspace 插件的 `entry` 必须本就在 Aeloon venv path 上 → 方案 = `.pth`（让 `integrations.*` 可 import）+ manifest 符号链接进 `~/.aeloon/plugins/`（供 discovery 扫描）。`install_into_aeloon.py` 一键完成、`--uninstall` 可逆，只动一个 `.pth` + 一个符号链接，**绝不碰 Aeloon 代码**。
- **依赖隔离**：核心 `requirements.txt` 不动；`mcp` 仅 MCP server 可选用（列入 `integrations/requirements.txt`）；Aeloon SDK 由 host 提供（不 pip 装）。插件运行在 Aeloon venv（自带 pydantic2 + mcp）。
- 用户本机 Aeloon 克隆在 `~/Documents/Playground/Aeloon-Pro`（`dev/ui` 分支），SDK 在 `dev/ui` 与 `origin/main` 间零差异（`git diff` 实测），无需兼容两版。

## 不在本轮范围

- **不改续写流水线**（writer/reviewer/debater/planner/runner 业务逻辑零改动），仅在其外围加适配层与可选鉴权。
- **不做** Aeloon WebUI 内嵌自定义面板/iframe —— SDK 无此扩展点（调研已确认）；富交互一律走深链跳转。
- **不引入 CORS** —— 适配器是服务端 Python HTTP 客户端、深链是整页导航，均无浏览器跨域 fetch。
- **不发 PyPI / 不做 setuptools entry point 自动发现**（README 给手动安装路径即可，entry point 留作后续）。
- **不做真模型端到端 smoke**（铁律⑥需用户单独授权；本轮 mock 即可证双轨链路）。
- 048d 预定的产品打磨项（L级 UX/a11y、细纲结构化编辑、正文编辑、premise 扩写质量、B-M-2）→ 顺延 iter050。

## Notes

- **接续点**：本轮以 untracked `integrations/`（44 测）为基座，净新增 = `aeloon_plugin/` + 服务端 token 闸 + 两个新测 + 文档。
- **实机依赖**：Aeloon 轨验收需用户本机 Aeloon-Pro 环境（用户已确认具备）；MCP 轨可用 Claude Code `.mcp.json` 独立验证，不依赖 Aeloon。
- **iter050 接力**：048d 顺延的产品打磨包 + 视集成实机反馈决定是否向 Aeloon 团队提 `register_webui_panel` 类 feature request。
- 验收命令需用 `.venv/bin/python`。
