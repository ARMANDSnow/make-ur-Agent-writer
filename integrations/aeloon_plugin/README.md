# Aeloon-Pro 插件：小说续写工作台（iter 049）

在 Aeloon 聊天里用 `/novel` 开书、出细纲、写正文；需要精修时点链接跳到续写系统自带的网页工作台。

## 形态（Aeloon WebUI 里长什么样）

- 进度**流式刷在聊天里**（`ctx.send_progress`）。
- 结果是 **Markdown 消息**，Aeloon WebUI 原样渲染（表格 / 列表 / 可点链接）。
- 重交互（改大纲、读正文）→ 点消息里的链接，**新标签页**打开 `…/w/<书名>/workbench`。
- 同一套操作也注册为 **LLM 工具**，自然语言「帮我接着写一章」即可触发。

> Aeloon 插件 SDK 没有自定义面板 / iframe 扩展点，所以**不是**窗口内嵌子页；富交互一律走深链跳转。

## 两进程模型（后端随 Aeloon 自动启动）

插件只是瘦 HTTP 客户端；续写系统作为**独立进程**运行（避免阻塞 Aeloon 的事件循环，也让深链可用）。

**默认无需手动起后端**：插件 `activate` 时会幂等地在后台拉起 `python main.py web`（仅当 `base_url` 是 loopback；已在跑则探测到并复用、不重复起），Aeloon 退出时自动停掉它自己起的那个。所以装好插件、起 Aeloon，`/novel` 就能直接用，点链接也能开网页工作台。

> **前提**：本机已 clone 本仓库且其 `.venv` 装好依赖——子进程优先用 `仓库根/.venv/bin/python` 跑 `main.py`（找不到 `.venv` 才回退当前解释器）。

仍可手动起（自动启动会探测到并复用，不会冲突）：

```bash
python main.py web --port 8765
```

关掉自动启动 / 指向远程后端：把 `auto_start_backend` 设 `false`，或把 `base_url` 指向非 loopback 地址（远程视作已有服务，插件不代起）。

> ⚠️ 若 Aeloon **异常退出**（崩溃 / 被强杀，未走正常关闭流程），自动起的后端子进程可能残留占用 `8765`——下次启动会探测到并**安全复用**，但旧进程需手动 `pkill -f "main.py web"` 清理。

## 安装（本地）

> 配置项全表、是否需合并 Aeloon main、MCP 轨、排错 → 见 [`docs/AELOON_INTEGRATION.md`](../../docs/AELOON_INTEGRATION.md)。

Aeloon 的 loader 用纯 `importlib` 解析插件 `entry`，**不会**把插件目录加进 `sys.path`。
因此需要：(1) 一个 `.pth` 让 Aeloon 的 venv 能 `import` 本仓库；(2) manifest 出现在
`~/.aeloon/plugins/` 下供发现。随附脚本一键完成：

```bash
python -m integrations.aeloon_plugin.install_into_aeloon \
    --venv ~/Documents/Playground/Aeloon-Pro/.venv

# 卸载（删掉那一个 .pth + 一个符号链接）
python -m integrations.aeloon_plugin.install_into_aeloon \
    --venv ~/Documents/Playground/Aeloon-Pro/.venv --uninstall
```

然后重启 Aeloon（或重载插件），在聊天里 `/novel help`。

## 配置

Aeloon `~/.aeloon/config.json` 里 `plugins["novel.continuer"]`（缺省时用环境变量兜底）：

| 键 | 默认 | 说明 |
|---|---|---|
| `base_url` | `http://127.0.0.1:8765` | 续写服务地址（env `NOVEL_BASE_URL`） |
| `api_token` | `""` | bearer token，对应服务端 `NOVEL_API_TOKEN`（设了才需要） |
| `auto_start_backend` | `true` | loopback 时随 Aeloon 自动拉起 `main.py web`；已在跑则复用 |
| `backend_ready_timeout_s` | `20.0` | 自动启动后等待后端就绪的上限（秒） |
| `default_book` | `""` | 默认作品；省略则用唯一的那本 |
| `write_tier` | `mid` | 写作档位 high/mid/low |
| `write_budget_cny` | `5.0` | 单次写作预算（元） |
| `outline_chapters` | `3` | 细纲默认章数 |
| `write_chapters` | `1` | 正文默认章数 |

## 命令

```
/novel new <一句话设定>   开新书并自动准备设定（可 … as 书名 指定名字）
/novel outline [章数]     生成章节细纲（默认 3 章）
/novel write [章数]       续写正文（默认 1 章，带 5+1 评审）
/novel auto [章数]        一键从当前进度跑到正文
/novel status [书名]      查看四步进度
/novel open [书名]        返回网页工作台链接
/novel list               列出所有作品
/novel prepare [书名]     重新准备设定
```

## MCP 轨（备选，不装插件也能用）

把同一套操作当 MCP server 连入 Aeloon / Claude Code：见 `integrations/mcp_server/`。
两轨共享 `novel_client` + `novel_ops` + `mcp_server/tools.py` 的 `TOOL_SPECS`，行为一致。
