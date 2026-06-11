# Aeloon-Pro 插件：小说续写工作台（iter 049）

在 Aeloon 聊天里用 `/novel` 开书、出细纲、写正文；需要精修时点链接跳到续写系统自带的网页工作台。

## 形态（Aeloon WebUI 里长什么样）

- 进度**流式刷在聊天里**（`ctx.send_progress`）。
- 结果是 **Markdown 消息**，Aeloon WebUI 原样渲染（表格 / 列表 / 可点链接）。
- 重交互（改大纲、读正文）→ 点消息里的链接，**新标签页**打开 `…/w/<书名>/workbench`。
- 同一套操作也注册为 **LLM 工具**，自然语言「帮我接着写一章」即可触发。

> Aeloon 插件 SDK 没有自定义面板 / iframe 扩展点，所以**不是**窗口内嵌子页；富交互一律走深链跳转。

## 两进程模型

插件只是瘦 HTTP 客户端；续写系统作为独立进程运行（避免阻塞 Aeloon 的事件循环，也让深链可用）：

```bash
# 终端 A：起续写系统（mock 或真模型；本仓库根目录）
python main.py web --port 8765

# 终端 B：照常起你的 Aeloon
```

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
