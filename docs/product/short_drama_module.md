# 短剧模块迁移说明

iter167 起，`main` 是小说原创与续写专用主线，不再包含短剧运行能力。

- 完整小说+短剧实现与本文件的完整历史版本保存在分支 `codex/short-drama`，固定拆分基线为 `35c97ccedeaca1725cc1a491cebf393f6a91303a`。
- main 只在首页和作品列表保留“短剧模块暂未开放”的禁用入口外观；控件没有链接、点击处理器或跳转目标。
- main 不提供短剧 CLI、Web 页面、API、job step、媒体回调、归档、创建或恢复功能。
- 旧 `type=drama` workspace 仅被只读识别为不支持类型，并从小说列表隐藏。main 不迁移、修改或删除其数据。
- 需要继续短剧开发或访问旧短剧 workspace 时，请先切换到 `codex/short-drama`。历史 iteration 和 [`PROJECT_HISTORY.md`](../PROJECT_HISTORY.md) 继续保留审计记录，但不代表 main 当前能力。

不要在 main 为旧短剧数据添加临时兼容写入或清理入口；任何此类工作都应在短剧分支单独规划、验收和授权。
