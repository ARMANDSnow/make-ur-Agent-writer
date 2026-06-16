# Aeloon-Pro 集成与部署文档

> 本文档说明如何把「龙族 AI 续写系统」接入 Aeloon-Pro：**引入的配置**、**是否要合并到 Aeloon main 分支**、以及**详细部署步骤**。
> 落地档案见 [`iteration_049_PLAN.md`](iterations/iteration_049_PLAN.md)；插件速查见 [`integrations/aeloon_plugin/README.md`](../integrations/aeloon_plugin/README.md)。

---

## 0. TL;DR

- **不需要改 Aeloon 一行代码，也不需要合并到 Aeloon main 分支。** 续写插件作为 Aeloon 的 **workspace 插件** 安装到 `~/.aeloon/plugins/`，靠一个 `.pth` 让 Aeloon 的 venv 能 import 本仓库——这两样都是**运行时本地安装**，不进 Aeloon 仓库。
- 两条接入轨，二选一或并用：**Aeloon 原生插件**（`/novel` 命令 + LLM 工具，推荐）与 **MCP server**（`tools.mcpServers` 配置）。
- 两条轨都要求续写系统作为**独立 HTTP 服务**运行（`python main.py web`）。插件/MCP 只是瘦客户端。
- **已装 Aeloon、想从零把续写系统用起来？** 直接看下方「🚀 面向 Aeloon 用户」一节——关键是**依赖分边**：插件侧（跑在 Aeloon 进程内）**零额外依赖**，续写引擎的重依赖（litellm 等）在它**自己的独立进程**，两边天然隔离。

---

## 1. 架构与形态

```
┌─────────────────────────┐         HTTP (localhost)         ┌──────────────────────────┐
│  Aeloon-Pro             │  POST /api/.../run  → job_id      │  续写系统 (本仓库)        │
│  ├─ 插件 novel.continuer │  GET  /api/.../job/{id}  轮询      │  python main.py web       │
│  │   /novel 命令+LLM工具 │ ───────────────────────────────► │  :8765  (ThreadingHTTP)   │
│  └─ 或 MCP client        │  ← Markdown 结果 + 深链           │  workspaces/<book>/...     │
└─────────────────────────┘                                   └──────────────────────────┘
        聊天里出结果 + 进度流式                      点深链 → 新浏览器标签页打开 /w/<book>/workbench
```

- **为什么走 HTTP 而不是直接 import 续写包**：续写流水线是同步、长耗时（LLM 调用以分钟计），Aeloon 是 asyncio——内联会阻塞其事件循环；且「跳转工作台」本就要求续写服务在跑。故插件 = 异步瘦 HTTP 客户端（`asyncio.to_thread` 卸载阻塞 I/O）。
- **界面形态**：Aeloon WebUI 是 React 聊天窗口，插件输出渲染为 Markdown 气泡，链接可点（新标签页）。插件 SDK **无**自定义面板/iframe 扩展点，所以富交互（改大纲、读正文）一律走深链跳转到续写系统自带的网页工作台。

---

## 🚀 面向 Aeloon 用户：从零把续写系统用起来（依赖分边）

> 场景：你已经在用 Aeloon（venv + 依赖都齐了），现在想加上「续写系统」。

**心智模型**：续写系统是一个**独立程序**（独立进程 + 独立依赖），插件只是装在 Aeloon 里的**瘦 HTTP 客户端**。所以「部署续写系统」= 两件事：① 把续写系统作为服务跑起来；② 在 Aeloon 里装个瘦插件指过去。**不是**把续写系统塞进 Aeloon 进程。

### 依赖分边（关键，也是为什么省心）

| | 跑在哪 | 需要的依赖 | 你已有 Aeloon 时要补什么 |
|---|---|---|---|
| **插件侧** | Aeloon 进程（其 venv 内）| 只 import `integrations`（`novel_client`/`novel_ops` 是**纯 stdlib**）+ Aeloon SDK（已有）；MCP 轨另需 `mcp`（Aeloon 已自带 `>=1.26.0`）| **无需额外 pip 装**。只要一个 `.pth` 让 Aeloon venv 能 import `integrations` |
| **续写侧** | **独立进程**（自己的 venv）| 续写引擎依赖：`litellm` / `pydantic` / `python-dotenv` / `tqdm` / `tiktoken`（见 `requirements.txt`）| 给续写系统 `pip install -r requirements.txt`（它自己的 venv，或复用 Aeloon venv）|

> 实测：`import integrations.aeloon_plugin.*` **不会**拖入 `litellm` / `tiktoken` / 续写引擎 `src.*`——client/ops 只用 stdlib + HTTP。所以续写系统的重依赖即便装在**另一个 venv、甚至另一台机器**，也不会污染 Aeloon 进程。这就是「插件侧零额外依赖」的底气。

### 从零步骤（Aeloon 用户视角）

1. **拿代码**：`git clone <续写仓库> && cd <续写仓库>`。（Aeloon 机器上至少要有 `integrations/` 子树供插件 import；完整引擎可在同机或另机。）
2. **准备续写服务的运行环境**（二选一）：
   - 选项 A（推荐·隔离）：给续写系统建独立 venv → `python -m venv .venv && .venv/bin/pip install -r requirements.txt`。
   - 选项 B（复用 Aeloon venv·省事）：`<Aeloon venv>/bin/pip install -r requirements.txt`（Aeloon 已有 `pydantic`、可能有 `litellm`，已装的会跳过）。留意版本冲突；不确定就用选项 A。
3. **配置**：`cp .env.example .env`，填 `OPENAI_MODEL` 等（先验证可用 `OPENAI_MODEL=mock` 跳过 key、不联网）。
4. **起续写服务**（长驻进程，单独开一个终端/服务）：
   ```bash
   OPENAI_MODEL=mock python main.py web --port 8765      # 验证用 mock
   # 真模型：配好 .env 后  python main.py web --port 8765
   ```
5. **装插件到 Aeloon**：
   ```bash
   python -m integrations.aeloon_plugin.install_into_aeloon --venv <Aeloon venv>
   ```
   写 `.pth`（让 Aeloon venv 能 import `integrations`）+ 符号链接 manifest 进 `~/.aeloon/plugins/`。**这一步不在 Aeloon venv 里装续写依赖**（见上「依赖分边」）。
6. **若续写服务不在 `127.0.0.1:8765`**：在 `~/.aeloon/config.json` 的 `plugins["novel.continuer"].base_url` 指过去（配置全表见 §3.1）。
7. **重启 Aeloon → 聊天里 `/novel help`**。

### 最小变体：续写系统跑在别处（容器 / 另一台机）

Aeloon 机器上只需 `integrations/` 子树（够插件 import）+ `.pth`，把 `base_url` 指向跑续写服务的机器即可——Aeloon 机器上**不必有续写引擎 `src/`、也不必装 `litellm`**。续写服务在哪、用什么 venv，与 Aeloon 完全解耦。

> 机械步骤的更多细节（一键脚本 / 手工等价 / 加载验证 / 卸载）见 §4；配置项全表见 §3；MCP 轨见 §5。

---

## 2. 是否需要合并到 Aeloon main 分支？——不需要

Aeloon 的插件发现有 4 个来源（优先级低→高，见 `aeloon/plugins/_sdk/discovery.py`）：

| 来源 | 位置 | 要不要改 Aeloon | 适用 |
|---|---|---|---|
| Bundled | `aeloon/plugins/` | **要**（代码进 Aeloon 仓库 → 合 main） | 想随 Aeloon 发给所有用户 |
| Entry points | setuptools `aeloon.plugins` 组 | 不改 Aeloon，但需把本包打成可 `pip install` | 想用 pip 分发 |
| **Workspace** | **`~/.aeloon/plugins/`** | **不改 Aeloon** ✅ | **本地/单机安装（本方案）** |
| Extra paths | config 里配置的目录 | 不改 Aeloon | 自定义目录 |

**本方案用 Workspace 来源**：把插件目录符号链接进 `~/.aeloon/plugins/`，再用一个 `.pth` 让 Aeloon 的 venv 能 `import integrations.aeloon_plugin.plugin`。

- `~/.aeloon/plugins/` 是**用户运行时目录**，不是 Aeloon 仓库；
- `.pth` 写在 **Aeloon venv 的 site-packages**，是**运行时产物**，不是 Aeloon 源码；
- 因此**零 Aeloon 代码改动，无需 PR，无需合 main**。MCP 轨同理（只在 `~/.aeloon/config.json` 加 `tools.mcpServers` 一段配置）。

> 什么时候才需要合 main？只有当你想把 `novel.continuer` **作为 Aeloon 内置插件随产品发给所有 Aeloon 用户**时，才会把代码放进 `aeloon/plugins/` 并提 PR——那是产品决策，不是技术必需，而且会把续写系统的代码耦合进 Aeloon 仓库，**不推荐**。保持外部安装最干净。

> 关于 SDK 兼容：本机 Aeloon 克隆在 `dev/ui` 分支，其 `aeloon/plugins/_sdk/` 与 `origin/main` **零差异**（已 `git diff` 实测），所以插件对两个分支都适用，无需为分支差异分叉。

> 📌 **2026-06-16 更新**：现已另有一种 **bundled 内置插件法**（落在专用孤立分支 `dev/novel-ui`，非 main），免 `.pth`+符号链接安装、原生被 discovery 发现；详见 **§9**。同时 §9 记录了 Aeloon 的 **gateway 架构**——它对「在 live Aeloon 里实测插件」是关键坑，务必先读 §9.4。

---

## 3. 引入的配置

所有配置都是**可选**的——不配也能用默认值在本地跑通。分三类。

### 3.1 插件配置（Aeloon 侧）

写在 `~/.aeloon/config.json` 的 `plugins` 段，键是插件 id `"novel.continuer"`（装了即 `enabled`，默认 true）：

```jsonc
{
  "plugins": {
    "novel.continuer": {
      "enabled": true,
      "base_url": "http://127.0.0.1:8765",   // 续写服务地址
      "api_token": "",                        // 对应服务端 NOVEL_API_TOKEN，设了才填
      "default_book": "",                     // 默认作品名；省略则用唯一的那本
      "write_tier": "mid",                    // 写作档位 high/mid/low
      "write_budget_cny": 5.0,                // 单次写作预算（元）
      "outline_chapters": 3,                  // 细纲默认章数
      "write_chapters": 1,                    // 正文默认章数
      "request_timeout_s": 30.0,
      "job_timeout_s": 3600.0
    }
  }
}
```

不写 `plugins["novel.continuer"]` 也行——插件会用代码内默认值，并支持**环境变量兜底**（见 3.3）。

### 3.2 服务端配置（续写系统侧）

| 变量 | 默认 | 说明 |
|---|---|---|
| `OPENAI_MODEL` | （必填）| `mock` 或带 provider 前缀的真模型（如 `deepseek/deepseek-chat`），写在本仓库 `.env` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | 真模型时填，写在 `.env` |
| `NOVEL_API_TOKEN` | 未设 | **opt-in 鉴权**：设了之后所有 `/api/*` 须带 `Authorization: Bearer <token>` |

> ⚠️ **`NOVEL_API_TOKEN` 的取舍**：一旦设置，续写系统**自家浏览器工作台**的前端 JS（不带 header）也会被 401 挡掉——这个 token 只给**程序化客户端**（Aeloon 插件 / MCP）。本地用浏览器请**勿设**；只有把 API 暴露到非 loopback、且不需要网页工作台时才设，并在插件配置 `api_token` 里填同一个值。

### 3.3 环境变量兜底（无 config.json 时）

插件和 MCP server 都读这些 env（config.json 优先）：

```
NOVEL_BASE_URL=http://127.0.0.1:8765
NOVEL_API_TOKEN=                 # 与服务端一致
NOVEL_DEFAULT_BOOK=
NOVEL_WRITE_TIER=mid
NOVEL_WRITE_BUDGET_CNY=5.0
NOVEL_REQUEST_TIMEOUT_S=30
NOVEL_POLL_INTERVAL_S=2.0
NOVEL_JOB_TIMEOUT_S=3600
```

### 3.4 MCP 配置（仅 MCP 轨需要）

写在 `~/.aeloon/config.json` 的 `tools.mcpServers` 段（见 5.3）。

---

## 4. 详细部署：插件轨（推荐）

### 4.0 前置

| 项 | 本机实际值（按需替换）|
|---|---|
| 续写仓库根 | `/Users/dingyuxuan/Desktop/Agent续写项目` |
| Aeloon 仓库根 | `~/Documents/Playground/Aeloon-Pro` |
| Aeloon venv | `~/Documents/Playground/Aeloon-Pro/.venv`（Python 3.11）|
| Aeloon home | `~/.aeloon`（插件目录 `~/.aeloon/plugins/`，配置 `~/.aeloon/config.json`）|

> **关键原理**：Aeloon 的 loader 用纯 `importlib.import_module(entry)` 解析插件，`discovery`/`loader`/`manager` **全程不碰 `sys.path`**（已审源码）。所以 workspace 插件的 `entry` 模块必须本就在 Aeloon venv 的 path 上 → 用 `.pth` 把续写仓库根加进去，让 `import integrations.aeloon_plugin.plugin` 解析得到。

### 4.1 一键安装（推荐）

在续写仓库根执行：

```bash
python -m integrations.aeloon_plugin.install_into_aeloon \
    --venv ~/Documents/Playground/Aeloon-Pro/.venv
```

它只做两件可逆的事（**绝不碰 Aeloon 代码**）：

1. 写 `.pth`：`<Aeloon venv>/lib/python3.11/site-packages/novel_continuer_repo.pth` → 内容是续写仓库根路径（让 `integrations.*` 可 import）；
2. 建符号链接：`~/.aeloon/plugins/novel_continuer` → `<续写仓库>/integrations/aeloon_plugin`（让 manifest `aeloon.plugin.json` 被 discovery 扫到）。

可选参数：`--site-packages <dir>`（直接给 site-packages，替代 `--venv`）、`--aeloon-home <dir>`（默认 `~/.aeloon`）、`--name <dir名>`（默认 `novel_continuer`）。

### 4.2 手工安装（等价，便于理解/排错）

```bash
REPO=/Users/dingyuxuan/Desktop/Agent续写项目
SITE=~/Documents/Playground/Aeloon-Pro/.venv/lib/python3.11/site-packages

# 1) .pth：让 Aeloon venv 能 import 续写仓库
echo "$REPO" > "$SITE/novel_continuer_repo.pth"

# 2) manifest 进 discovery 扫描目录
ln -s "$REPO/integrations/aeloon_plugin" ~/.aeloon/plugins/novel_continuer
```

### 4.3 验证已被 Aeloon 发现并能加载（不开 WebUI）

用 Aeloon **自己的** discovery + loader 验证（PYTHONPATH 只给 aeloon root，`integrations` 靠 `.pth`）：

```bash
PYTHONPATH=~/Documents/Playground/Aeloon-Pro \
  ~/Documents/Playground/Aeloon-Pro/.venv/bin/python - <<'PY'
from pathlib import Path
from aeloon.plugins._sdk.discovery import PluginDiscovery
from aeloon.plugins._sdk.loader import PluginLoader
disc = PluginDiscovery(workspace_dir=Path("~/.aeloon/plugins").expanduser())
cand = next(c for c in disc.discover_all() if c.manifest.id == "novel.continuer")
print("discovered:", cand.source_label)                 # workspace:novel_continuer
loader = PluginLoader()
print("validate:", loader.validate_candidate(cand))     # []
cls = loader.load_plugin_class(cand.manifest)            # 仅靠 .pth import
print("loaded:", cls.__name__)                           # NovelPlugin
PY
```

### 4.4 启动续写服务（两进程模型，必需）

```bash
cd /Users/dingyuxuan/Desktop/Agent续写项目
# mock（无需 API key，先验证链路）
OPENAI_MODEL=mock python main.py web --port 8765
# 或真模型：先在 .env 配好 OPENAI_MODEL/OPENAI_API_KEY，再 python main.py web --port 8765
```

### 4.5 在 Aeloon 里用

重启 Aeloon（或重载插件）后，聊天里：

```
/novel help                          看用法
/novel new 一句话设定                 开新书 + 自动准备设定（流式进度）
/novel outline [章数]                生成章节细纲
/novel write [章数]                  续写正文（带 5+1 评审）
/novel auto [章数]                   一键从当前进度跑到正文
/novel status / open / list / prepare
```

也可对 agent 说自然语言（如「帮我接着写一章」）触发同名 **LLM 工具**（`novel_create` / `novel_write_chapters` / …）。结果是 Markdown 气泡，点链接新标签页打开 `/w/<书名>/workbench` 精修。

### 4.6 卸载

```bash
python -m integrations.aeloon_plugin.install_into_aeloon \
    --venv ~/Documents/Playground/Aeloon-Pro/.venv --uninstall
```

只删那一个 `.pth` + 一个符号链接；重启 Aeloon 即彻底移除。

---

## 5. 详细部署：MCP 轨（备选 / 并用）

不装插件，也可把同一套 8 个工具当 MCP server 接入 Aeloon 或 Claude Code。两轨共享 `novel_client` + `novel_ops` + `mcp_server/tools.py` 的 `TOOL_SPECS`，行为一致。

### 5.1 装 mcp 依赖

MCP server 需要 `mcp` 包（Aeloon venv 已自带 `mcp>=1.26.0`；独立用则）：

```bash
pip install -r integrations/requirements.txt
```

### 5.2 独立运行（自检）

```bash
NOVEL_BASE_URL=http://127.0.0.1:8765 python -m integrations.mcp_server.server
```

### 5.3 接入 Aeloon（`~/.aeloon/config.json`）

```jsonc
{
  "tools": {
    "mcpServers": {
      "novel": {
        "type": "stdio",
        "command": "/Users/dingyuxuan/Desktop/Agent续写项目/.venv/bin/python",
        "args": ["-m", "integrations.mcp_server.server"],
        "env": {
          "NOVEL_BASE_URL": "http://127.0.0.1:8765",
          "PYTHONPATH": "/Users/dingyuxuan/Desktop/Agent续写项目"
        }
      }
    }
  }
}
```

> `command` 用哪个 python 都行，只要它能 `import integrations.mcp_server.server`（通过 `PYTHONPATH` 或 `.pth`）和 `import mcp`。用 Aeloon venv 的 python（已带 mcp）+ `PYTHONPATH=续写仓库根` 最省事。

### 5.4 接入 Claude Code（`.mcp.json`）

```jsonc
{
  "mcpServers": {
    "novel": {
      "command": "python",
      "args": ["-m", "integrations.mcp_server.server"],
      "env": { "NOVEL_BASE_URL": "http://127.0.0.1:8765",
               "PYTHONPATH": "/Users/dingyuxuan/Desktop/Agent续写项目" }
    }
  }
}
```

---

## 6. 升级与维护

- **改插件代码即时生效**：`~/.aeloon/plugins/novel_continuer` 是**符号链接**指向仓库，`.pth` 指向仓库根——`git pull` 续写仓库后，重启 Aeloon 即用上新代码，**无需重装**。
- **续写系统升级**：照常更新本仓库；插件/MCP 通过稳定的 HTTP 契约调用，多数升级无需动 Aeloon 侧。
- **Aeloon 升级**：SDK 在 `dev/ui` 与 `main` 间零差异；如未来 Aeloon 改 `_sdk` 契约，受影响的只有薄胶水 `plugin.py` / `tool_adapter.py`。

---

## 7. 排错

| 症状 | 原因 / 排查 |
|---|---|
| `/novel` 命令 Aeloon 不认 | 插件没被发现：查 `~/.aeloon/plugins/novel_continuer` 软链是否在、`aeloon.plugin.json` 是否可读；跑 4.3 验证脚本。 |
| 加载报 `ModuleNotFoundError: integrations` | `.pth` 没装或指错：确认 `<Aeloon venv>/lib/python*/site-packages/novel_continuer_repo.pth` 内容是续写仓库根。注意 Aeloon 跑在**哪个 venv**——`.pth` 要写进那个 venv。 |
| 命令回 `连不上续写服务` | 续写服务没起或端口不符：`python main.py web --port 8765`；查 `base_url`。 |
| `/api/*` 全 401 | 设了 `NOVEL_API_TOKEN`：插件 `api_token` 要填同值；浏览器工作台在 token 模式下不可用（见 3.2）。 |
| 浏览器点深链打不开 | 续写服务没起，或 host/port 与深链不符（深链由服务端 `base_url` 决定）。 |
| MCP `tools/list` 空 / server 起不来 | `command` 的 python 不能 `import mcp` 或 `import integrations.mcp_server.server`：用 Aeloon venv python + `PYTHONPATH`。 |

---

## 8. 安全与限制

- **绑定 loopback**：续写服务默认 `127.0.0.1`；绑非 loopback 会打印警告，此时建议配 `NOVEL_API_TOKEN`。
- **token 与浏览器互斥**：见 3.2。
- **无自定义 UI 面板**：Aeloon 插件 SDK 无面板/iframe 扩展点，富交互走深链——这是确认过的形态，不是临时方案。
- **版权/数据**：续写产物落在续写仓库的 `workspaces/<book>/`，不经 Aeloon 持久化；Aeloon 只拿到聊天里的 Markdown 摘要 + 深链。

---

## 9. 实测补遗（2026-06-16）：bundled 内置插件法 + Aeloon gateway 架构 + 踩坑

> 本节记录把续写并入 Aeloon-Pro `dev/novel-ui` 分支、并把该分支**装成可跑部署做前后端实测**时的新发现。§4 的 workspace 安装法仍然有效；本节是**第二种部署法 + live 调试的关键坑**。

### 9.1 第二种部署法：bundled 内置插件（已落在 `dev/novel-ui`）

与 §4 的「workspace 安装（`.pth` + 符号链接）」并列的另一种形态，已实装在 `AetherHeart-AI/Aeloon-Pro` 的孤立分支 `dev/novel-ui`：

- **位置**：`aeloon/plugins/NovelContinuation/`，4 个文件——`aeloon.plugin.json`（id=`novel.continuer`，声明 `/novel` + 8 工具）、`__init__.py`、`plugin.py`（薄 shim）、`README.md`。
- **原理**：`plugin.py` 用路径 shim（`Path(__file__).resolve().parents[3] / "novel_web"`）把**同分支内**的 `novel_web/` 加进 `sys.path`，再 `from integrations.aeloon_plugin.plugin import NovelPlugin` 复用同一份插件类——**单一真源、零逻辑重复**。
- **好处**：原生被 discovery 扫到，**免 `.pth` + 符号链接安装**；clone 该分支 + 起 Aeloon 即自动有 `/novel`。
- **与 §2「不合并 main」的关系**：bundled 这次是放在**专用孤立分支 `dev/novel-ui`**（不是 main），main 仍保持干净；属于"按分支交付快照"，不是"随产品发给所有用户"。
- **坑①（打包）**：Aeloon 根 `.gitignore` 有一条**裸 `docs` 规则**，会吞掉 `novel_web/docs/`（任意名为 `docs` 的子目录）。提交这些文档须 `git add -f`（父目录被父级规则排除后，子 `.gitignore` 无法救回）。

### 9.2 把 `dev/novel-ui` 装成可跑部署

```bash
cd ~/Desktop/Aeloon-Pro            # dev/novel-ui 检出
python3.11 -m venv .venv           # pyproject requires-python >= 3.11
.venv/bin/pip install -e .         # 装 aeloon-ai 1.0.0(editable) + 全部依赖
```
后端（novel_web）用同一部署自包含启动即可（新 venv 已含 litellm/pydantic/tiktoken 等引擎依赖）：
```bash
cd ~/Desktop/Aeloon-Pro/novel_web
OPENAI_MODEL=mock ../.venv/bin/python main.py web --port 8765
```

### 9.3 ⚠️ 关键架构：Aeloon 是 gateway 架构（live 测插件必读）

- `aeloon agent` **默认连一个常驻 gateway 进程**，**插件由 gateway 加载**，不是 agent 自己。
- 后果：要让某部署的插件在 live `/novel` 里生效，**gateway 必须从该部署的 venv 启动**。若机器上已有**别的部署**的 gateway 在跑（如 Playground `dev/ui` 占 `:18790`、或另一个 checkout 起的 gateway），你的 `aeloon agent` 会连上**那个**→ 看不到本部署的 `/novel`。
- 排查命令：
  ```bash
  ps aux | grep 'aeloon gateway' | grep -v grep
  lsof -nP -i :18790
  lsof -a -p <gateway_pid> -d cwd      # 看该 gateway 属于哪个部署(cwd)
  ```
- **坑②（最关键，最易误判）**：`discover_all()` / `build_lightweight_plugin_registry()` 能发现/注册插件 **≠** live agent 能用它。前者是**元数据扫描**（与 venv 里的代码一致即可），后者取决于 **agent 连的是哪个 gateway**。本次就是：元数据层一路绿、但 live `/novel` 不认，根因是 agent 连到了别的部署的常驻 gateway。

### 9.4 live 跑 `/novel` 的两种方式

**A. gateway 模式（贴近真实使用，推荐）**——让 gateway 从 `dev/novel-ui` 部署起：
```bash
# 先停掉/避开别的部署占用的 gateway 端口（默认 :18790）
cd ~/Desktop/Aeloon-Pro && .venv/bin/aeloon gateway        # 端口冲突时加 --port
# 另一终端
cd ~/Desktop/Aeloon-Pro && .venv/bin/aeloon agent          # 交互；输入 /novel help
```

**B. `--standalone` 进程内加载（绕过外部 gateway）**——实测能加载 novel（启动日志 `✓ Plugins loaded: …novel.continuer…`），但有三道限制：
- 只支持 `llmBackend=local`（云端 config 会被拒：`--standalone only supports llmBackend=local`）。可在隔离 config 里把 `llmBackend` 改成 `local`。
- 其 `-m "/novel ..."` **一次性模式只 init 不处理消息**（不打印命令回复）；要交互 TTY 才能看到分发结果。
- 隔离测试可用 `AELOON_HOME=<临时目录>` 自定义 home + `AELOON_TRUST_WORKSPACE=1` 过 workspace trust 门禁；但**隔离 home 缺登录态**（`auth/` + `webui-auth.json`），云端模式会报 `gateway 握手失败：请先登录`——需从真实 `~/.aeloon` 拷 `auth/` 等。

### 9.5 坑③：workspace 安装法（§4）在本机未观察到生效

- 现象：`~/.aeloon/plugins/novel_continuer` 符号链接在，但运行中部署的 `~/.aeloon/plugin_state.json` **没有 `novel.continuer` 条目**，live `/novel` 不认（被当普通聊天发给 LLM）。
- 可能原因（**待确认**，按怀疑度排序）：
  1. `.pth` 没写进**实际在跑的那个** Aeloon venv——本机有 Playground / `Aeloon-Pro-devui` 等多个部署，venv 各异，`.pth` 装错 venv 就不生效。
  2. 符号链接目标路径含**非 ASCII**（`/Users/.../Agent续写项目/...`），`.pth` 对非 ASCII 路径的解析存疑——建议把仓库放到纯 ASCII 路径或改 `.pth` 写法再验。
  3. **来源优先级覆盖**：workspace 源（优先级 30）会盖过 bundled 源（10），二者同 id `novel.continuer`；若 workspace 那份坏了/没生效，理论上仍可能挡住 bundled。用 bundled 法时**应移除/确认没有**该 workspace 符号链接。

### 9.6 本次实测确切结论

| 项 | 结果 |
|---|---|
| `dev/novel-ui` 装成可跑部署 | ✅ `~/Desktop/Aeloon-Pro/.venv`（py3.11 + aeloon-ai 1.0.0 + 全依赖） |
| 后端 novel_web（用户视角） | ✅ 工作台首页 HTTP 200（标题「续写工作台·本地多 Agent 创作引擎」）+ `/api/workspaces` 正常 + mock 全链路（new/outline/status 通、write 被 readiness 护栏正确拦截） |
| bundled `/novel` 加载 | ✅ 真实 aeloon 进程启动日志 `✓ Plugins loaded: …novel.continuer…`；`discover_all()` source=bundled；`register()` 注册 /novel + 8 工具 |
| live 交互 `/novel` 回复 | ⚠️ headless 自动化未打印——因 gateway 架构（§9.3）+ standalone/local/login/TTY 限制（§9.4-B）。交互终端按 §9.4-A 从 `dev/novel-ui` 部署起 gateway+agent 即可正常用 |
