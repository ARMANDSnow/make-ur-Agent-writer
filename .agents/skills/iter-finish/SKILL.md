---
name: iter-finish
description: 收尾一轮迭代（Dragon Raja AI Continuer 项目）。先做聚焦检查与多视角只读审查、修复 findings，最后只运行一次统一 verify 验收；回填 Acceptance Result，并就地同步 README、handoff 与 PROJECT_HISTORY。当用户说“收尾 iter NNN / 完成迭代 / iter-finish”时使用。
---

# iter-finish — 收尾一轮迭代

本文件是项目 `iter-finish` workflow 的唯一真源，随仓库同步；不得在用户级 skill 目录维护项目专用副本。
只 commit、不 push；不跑真模型 smoke，不碰 `.env`、`data/`、`outputs/`、`logs/` 或 `小说txt/` 中的私有内容。

## 入参

```text
/iter-finish <NNN>
```

编号缺省时取 `docs/iterations/README.md` 最后一条 canonical index。开始前确认唯一匹配的 `docs/iterations/iteration_NNN_*.md` 存在且具有固定 8 段。

## 步骤

### 1. 聚焦 sanity

根据 diff 运行覆盖改动面的低成本检查，例如：

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest <受影响测试模块>
.venv/bin/python3 -m py_compile <受影响 Python 文件>
.venv/bin/python3 scripts/check_agent_harness.py
git diff --check HEAD
```

此阶段不要运行全量 discovery 或 `scripts/verify.sh`。聚焦检查失败时先修复并回归，再进入审查。

### 2. 多视角只读审查

- 派发前重读当轮 `### Implementation Context` 与 `### Review Context`，按实际 diff 复核 `expected_changes`、`correctness_behavior`、`security_boundary` 和 `extra_risk_view`。上下文是路由提示，不是 Git 硬白名单；合理范围变化写入 `Implementation Notes`，不要重写已批准的 Plan 承诺。
- 至少安排 correctness/behavior 与 security/boundary 两个独立只读 subagent。
- Web、runner、多 workspace、真实模型、计费或媒体入口按风险增加视角。
- correctness/behavior subagent 必须收到 `correctness_behavior`，security/boundary subagent 必须收到 `security_boundary`；`extra_risk_view` 非 `none` 时另行派发对应只读视角。所有视角同时收到实际 diff、必要的 `must_read` 与 `do_not_touch`，不得把整份无界历史上下文塞给 subagent。
- subagent 明确禁止改文件、跑真模型、读取 `.env` 或触碰 `data/`、`outputs/`、`logs/`、`小说txt/`。
- 主线程逐条复核 finding，只修复确认成立的问题，并运行覆盖修复面的聚焦回归。
- 未处理完有效 finding 前不得进入最终全量验收。

findings 稳定且聚焦回归通过后、形成 implementation commit 前，必须完成人工 `### Knowledge Promotion` 判断并写入 active iteration：

- `decision` 只能是 `` `none` `` 或 `` `promoted` ``。
- `none` 必须配 `` `destination`: `none` `` 和非空 `reason`。
- `promoted` 的 `destination` 使用逗号分隔的反引号路径，只能指向 Git tracked、非 symlink、已存在的 `AGENTS.md`、两项仓库 workflow skill、`docs/PROJECT_HISTORY.md` 或相关 `docs/product/*.md`，并写非空 `reason`。
- 若晋升目标不是 docs-only 收官文件，必须在 implementation commit 前实际落地，使唯一 `verify.sh` 覆盖该规则；`PROJECT_HISTORY.md` 可按既有契约在 docs-only 收官提交更新。
- README 与 handoff 的常规状态同步不属于经验晋升；不得新增 journal、sidecar、task 状态文件或自动写入长期文档。
- 最终验收后若才发现需修改非 docs-only 权威文件的新经验，顺延到下一轮，不得制造 acceptance 后实现/workflow 漂移。

### 3. 最终只运行一次标准验收

审查与聚焦回归完成后，先把实现、测试、workflow 和 active iteration 文档提交为 implementation commit，确保 tracked tree 干净；再执行最终验收。`verify.sh` 只产生 `mock-functional` 证据。

审查、修复和聚焦回归结束后，只执行：

```bash
bash scripts/verify.sh
```

`verify.sh` 固定使用项目 `.venv/bin/python3`，强制 mock/offline，执行 harness 检查、语法检查、一次全量 unittest、mock pipeline 与 preflight，并生成脱敏的 `outputs/harness/acceptance.json`。不得在它前后再单独重复全量 unittest 或 preflight。

失败时按失败范围修复后重验；无法解决则停止，不同步完成态文档。成功后从控制台和 acceptance JSON 提取 canonical 测试数、步骤与结果，回填当轮 `Acceptance Result`。

同时逐项引用 Acceptance ID，并把 evidence 的 `git_head` 记录为 handoff 的 `Accepted implementation commit`。随后只做 README、handoff、history、iteration/index 的 docs-only 收官提交。

最终验收后回填完整 `Acceptance Result` 时，保留 implementation commit 前已经完成的 `Knowledge Promotion` 判断；不得在此时新改非 docs-only 权威文件。

### 4. 就地更新 README

- `## 项目状态`：仅在里程碑范围或状态确实变化时更新，不追加逐轮实现细节或测试数。
- `## 流水线 SOP（实时状态）`：就地替换最近一次 iter、真实日期和当前成果，更新受影响节点；不保留“上一轮/再上一轮”累述链。

### 5. 就地更新 handoff 与 history

- 按 `docs/AGENT_HANDOFF.md` 的 Maintenance Contract 更新 Current Snapshot、Capability Map、Latest Accepted Evidence、Open Gaps、Next Candidates 和 Latest Transition 中发生变化的事实。
- Retained Working Memory 只在长期能力、边界、事故模式或恢复知识变化时就地修订。
- `docs/PROJECT_HISTORY.md` 只补阶段里程碑、长期决策或工程教训，不复制 Acceptance Result 全文。
- 不得新增逐轮 `Phase Status - iter NNN`，不得把完整验收日志复制进 handoff。

### 6. 收官一致性检查

文档同步完成后再次运行聚焦的：

```bash
.venv/bin/python3 scripts/check_agent_harness.py
git diff --check HEAD
```

这不是第二次全量验收。确认 iteration 八段、索引、README 与 handoff accepted iter 一致。

## 输出

- 报告 canonical 测试数、统一验收结果、各审查视角与未修风险。
- 列出同步的文档，并给出 `docs(iterNNN): <收尾摘要>（验收 + 审查 + SOP/handoff 同步）` 草稿。
- 如代码尚未提交，提醒先提交代码/测试，再提交收官文档。
- 不自动 push，等待用户验收。
