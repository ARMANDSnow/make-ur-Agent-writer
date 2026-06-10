# integrations/ — 把续写系统接到外部 Agent host（iter 049）

一套 host 无关的适配层，让 Aeloon-Pro 等平台以**插件 / MCP** 两种形式调用续写系统。
续写系统作为独立 HTTP 服务（`python main.py web`）运行；适配器只是瘦客户端，重交互
（改大纲 / 读正文）走深链跳转网页工作台。

> 📘 **完整的配置项、是否需合并 Aeloon main、详细部署步骤与排错** → [`docs/AELOON_INTEGRATION.md`](../docs/AELOON_INTEGRATION.md)。

## 分层

| 子包 | 作用 | 依赖 |
|---|---|---|
| `novel_client/` | 异步 HTTP 客户端（job 轮询 + bearer token + 深链），blocking I/O 经 `asyncio.to_thread` 卸载 | stdlib |
| `novel_ops/` | host 无关高层操作（开书 → 细纲 → 正文）+ Markdown 格式化 | 无 |
| `mcp_server/` | MCP stdio server（8 工具）；`tools.py` 的 `TOOL_SPECS` 同时喂 Aeloon | `mcp`（可选）|
| `aeloon_plugin/` | Aeloon 原生插件：`/novel` 命令 + LLM 工具 | Aeloon SDK（host 提供）|

`TOOL_SPECS`（`mcp_server/tools.py`）是命令与工具的**单一真源**，MCP 与 Aeloon 两轨共享，杜绝漂移。

## 两轨怎么用

先起续写服务（两轨都依赖它）：

```bash
python main.py web --port 8765
```

- **Aeloon 插件**（推荐）：见 [`aeloon_plugin/README.md`](aeloon_plugin/README.md)——`.pth` + `~/.aeloon/plugins/` 一键安装脚本。
- **MCP**（Aeloon `mcpServers` / Claude Code `.mcp.json`）：

  ```bash
  pip install -r integrations/requirements.txt
  NOVEL_BASE_URL=http://127.0.0.1:8765 python -m integrations.mcp_server.server
  ```

## 鉴权（可选）

服务端 `NOVEL_API_TOKEN` 一旦设置，所有 `/api/*` 需带 `Authorization: Bearer <token>`；
浏览器深链（`/w/...`）豁免。客户端 / 插件 / MCP 通过同名 `NOVEL_API_TOKEN`（或插件 config
`api_token`）注入。默认不设 = 本地单机开放。

> ⚠️ **注意（设计取舍）**：设了 token 后，**自家浏览器工作台**的前端 JS 因不带 header 会被
> 401 挡掉——token 是给**程序化客户端**（Aeloon 插件 / MCP）的。本地用浏览器请**勿设**；
> 只有把 API 暴露给外部、且不需要网页工作台时才设。

## 测试

`tests/test_novel_client.py` · `test_novel_ops.py` · `test_mcp_tools.py` · `test_aeloon_plugin.py`
全部在 `OPENAI_MODEL=mock` 下纯 stdlib 运行，**不 import** `mcp` / Aeloon SDK，随主套件
`unittest discover -s tests` 一起跑。
