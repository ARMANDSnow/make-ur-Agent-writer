# CLAUDE.md

> 本仓库的工程上下文、进入工作流前必读清单、9 条工程铁律、迭代记录格式与关键路径速查，统一维护在 [AGENTS.md](AGENTS.md)。
>
> Claude Code 原生优先读 `CLAUDE.md`，故此处用 `@` import 引入 `AGENTS.md`，确保任何 claude 会话进入本仓库即自动加载铁律（与 Aeloon-Pro 的做法一致，单一真实来源仍是 `AGENTS.md`）。

@AGENTS.md

---

## 项目级 skill（迭代收尾自动化）

每轮迭代用以下两个 skill 自动同步「5 处文档」，替代手工模板劳动（见 `docs/CLAUDE_CODE_WORKFLOW_OPTIMIZATION_2026-06.md` P0-B）：

- `/iter-start <NNN> --title "..." --items "#7,#11"` — 起新一轮：建 8 段 iteration 文件骨架（预填 Context/Plan）+ 追加索引 + 输出 commit msg 草稿
- `/iter-finish <NNN>` — 收尾：跑单测/verify 回填验收 + 触发 `/code-review high` + `/security-review`（铁律⑨）+ 同步 README SOP 表与时间戳（铁律⑧）+ 追加 AGENT_HANDOFF Phase Status + 输出 `docs(iterNNN)` commit msg
