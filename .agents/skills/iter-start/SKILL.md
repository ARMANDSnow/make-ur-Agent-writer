---
name: iter-start
description: 起一轮新迭代（Dragon Raja AI Continuer 项目）。建立 iteration_NNN_slug.md 的 8 段骨架并预填 Context/Plan、追加 iteration 索引、提示 README SOP 收官更新、输出 commit msg 草稿。当用户说“起 iter NNN / 开始新一轮迭代 / iter-start”时使用。
---

# iter-start — 起一轮新迭代

本文件是项目 `iter-start` workflow 的唯一真源，随仓库同步；不得在用户级 skill 目录维护项目专用副本。
本 skill 只建立 iteration 文档与索引，不跑真模型、不碰 `.env`、`data/`、`outputs/`、`logs/` 或 `小说txt/`，也不要 commit、不要 push。

## 入参

```text
/iter-start <NNN> --title "<本轮标题>" --items "#7,#11,#14"
```

- `<NNN>`：三位迭代编号。若未提供，从 `docs/iterations/README.md` 最后一条 canonical index 取得编号并加一。
- `--title`：本轮主题，用于标题与 slug。
- `--items`：可选的 bug/任务编号，用于预填 Plan。
- 关键信息缺失且无法从用户当前指令、handoff 或索引推出时再向用户确认，不自行扩张范围。

## 步骤

### 1. 确定文件名

从标题生成小写下划线 slug；中文可保留，去除不适合文件名的标点。文件名固定为：

```text
docs/iterations/iteration_NNN_<slug>.md
```

### 2. 建立固定 8 段骨架

一级标题后必须依次包含且只包含以下 8 个二级段落：

```markdown
# Iteration NNN - <标题>

## Context
<为什么做本轮；引用当前缺口与用户目标。>

## Plan
<逐项写预期行为和改动范围。>

## Acceptance
<使用 A<NNN>-01 形式的唯一 Acceptance ID，写聚焦检查、审查要求、验收等级，以及最终 bash scripts/verify.sh 的判据。>

## Implementation Notes
<实施中的选择、踩坑和范围变化。>

## Acceptance Result
<iter-finish 回填测试数、acceptance 结果、审查结论与未修风险。>

## 文件变更汇总
<表格：| 文件 | 改动 |。>

## 不在本轮范围
<明确顺延项。>

## Notes
<其它长期有价值的信息。>
```

### 3. 更新 iteration 索引

向 `docs/iterations/README.md` 的 `## Index` 末尾追加一条 canonical entry。列表序号在上一条基础上加一；列表序号与 iter 编号不是同一概念。

```markdown
<列表序号>. [Iteration NNN - <标题>](./iteration_NNN_<slug>.md)
```

### 4. 做结构检查

运行：

```bash
.venv/bin/python3 scripts/check_agent_harness.py
```

确认索引链接存在、编号一致、最新 iteration 为固定 8 段。不得为了通过检查改写旧 iteration 历史。

Acceptance 中每项可验证承诺使用唯一 `A<NNN>-<两位序号>`；收官时 Acceptance Result 必须逐项引用闭合。验收等级只能使用 `safe-blocked`、`mock-functional`、`local-e2e`、`provider-validated`。

### 5. 提醒收官同步

README 的项目状态表不按每轮追加。提醒实施者在 `iter-finish` 时仅在事实变化时更新项目状态，并就地替换 SOP 的最近一次更新时间；handoff 与 PROJECT_HISTORY 也按各自维护契约更新。

## 输出

- 报告新建文件和索引行。
- 给出 `docs(iterNNN): 迭代计划 NNN 立项（<标题>）` commit message 草稿。
- 提醒实施完成后使用 `iter-finish`。
- 不自动 commit，不 push。
