# Claude Code 工作流优化调研报告（2026-06）

> 本报告调研「用 Claude Code 实现整个项目时还有哪些可优化点」。每条建议都标了「对口哪条铁律/痛点」+「具体怎么用」+「工作量/收益」，看完即可逐项决定落地。落地动作（写 skill、配 hook 等）是后续单独任务，本报告不改任何代码。

---

## Context（为什么做这次调研）

诉求：用 Claude Code 实现整个项目（Dragon Raja AI Continuer + 并入 Aeloon-Pro），还有哪些可优化点 —— 点名「代码审查」「前端设计」类 skill，但强调 skill 只是一方面。

**调研方法**：3 个 Explore subagent 并行摸底（① Claude Code 配置盘点 ② 项目工作流与痛点 ③ 前端结构与验证）+ 读 `AGENTS.md` 全文 + 核对 `DesignSync` 工具能力。

**一句话核心发现**：
> 项目纪律非常严（当前 `AGENTS.md` 10 条铁律 + 8 段迭代格式 + 文档同步），历史上主要靠手工执行。后续已用 iter-start/iter-finish、固定验收和多视角审查把其中一部分机制化；本报告保留当时的问题背景。

---

## 一、现状盘点（已用 vs 缺失）

| 维度 | 现状 | 状态 |
|---|---|---|
| 权限管理 | 全局 152 行细粒度 allowlist | ✅ 重度使用 |
| 模型/代理配置 | Haiku/Sonnet/Opus + 本地代理 URL | ✅ |
| 启动配置 | `.claude/launch.json` 3 个（web/mock/aeloon-webui） | ✅ |
| Context 管理 | 全局 CLAUDE.md 规范 Explore/Plan subagent + chapter | ✅ 做得好 |
| 迭代约定 | `AGENTS.md` 10 条铁律 + 8 段格式 | ✅ 文档，已由 skill 辅助执行 |
| **代码审查** | 铁律第8条「迭代末尾 subagent 审核」 | ✅ 已纳入 iter-finish |
| **前端验证** | iter043 UX 审计**手工开浏览器走查 5 条 journey** | ⚠️ 无自动化 |
| **迭代收尾** | 5 处文档（PLAN/索引/README SOP表/HANDOFF/commit）**手工同步** | ❌ 纯手工 |
| 项目级 hooks | 无（无 PreToolUse/PostToolUse/Stop） | ❌ 缺失 |
| 自定义 command/agent/skill/workflow | 全无（全局仅 obsidian skill） | ❌ 缺失 |
| 本地门禁 | 无 pre-commit、无 lint（Aeloon-Pro 有 ruff） | ❌ 缺失 |
| MCP | 未挂任何 MCP | ➖ 暂无明确需求 |

---

## 二、优化清单（按优先级排序）

### 🔴 P0-A 代码审查 & 安全审查标准化（点名 · 零开发即用）

**对口**：铁律第8条「迭代末尾必须调 subagent 做结构性/程序性只读审核，高风险增加独立视角」+ 第1条「API key 安全」。

**直接用现成内置 skill 替代/增强**（无需开发）：

| skill | 用法 | 替代什么 |
|---|---|---|
| `/code-review high` | 审当前 diff 的正确性 bug + 复用/简化/效率 | 手搓的结构性审核 prompt |
| `/code-review ultra` | **云端多 agent** 深审整条分支（按用户授权、计费） | 铁律第8条的高风险附加视角 |
| `/security-review` | 扫当前分支待提交改动的安全问题 | 铁律第1条 API key / `.env` 泄漏自查 |
| `/simplify` | 只做复用/简化/效率清理并应用 | iter038 遗留的 inline style / 代码债（P3 backlog） |

**落地方式**：铁律第8条与 `iter-finish` 固定要求 `/code-review high` + `/security-review` 等价审查及至少两个只读 subagent，结论写入 `Acceptance Result`。

---

### 🔴 P0-B 重复迭代劳动自动化（点名 · 一次开发长期省）

**对口**：铁律第7条（SOP 实时同步）+ 迭代记录格式（8 段）+ iteration、索引、README、handoff 与 commit msg 的同步。

**用 `skill-creator` 做两个项目级 skill**（落到 `.claude/skills/`）：

```
/iter-start <NNN> --title "前端P2并发" --items "#7,#11,#14"
  → 生成 docs/iterations/iteration_NNN_<slug>.md（8 段骨架，Context/Plan 预填）
  → docs/iterations/README.md 索引追加一行
  → 根 README.md「流水线 SOP（实时状态）」在收官时就地更新
  → 输出 commit msg 草稿

/iter-finish <NNN>
  → 跑 unittest discover + verify.sh，把 test count 回填 Acceptance Result
  → 触发 /code-review + /security-review（即 P0-A），结论写进 Acceptance Result/Notes
  → 同步根 README SOP 表状态字段(✅/⚠️/❌) + "最近更新"时间戳（铁律第7条）
  → AGENT_HANDOFF.md 就地更新当前快照与 Latest Transition（iter093 起不再追加 Phase Status）
  → 输出 docs(iterNNN) commit msg
```

**收益**：减少模板劳动并消除漏同步；iter093 起 handoff 只保留当前快照，避免自动化反向制造上下文膨胀。

---

### 🔴 P0-C 前端验证自动化（点名 · 投入最大但替代手工走查）

**对口**：iter043 UX 审计靠**手工开浏览器走查 5 条 journey + 人肉截图存 `/tmp/`**；缺 E2E / 可访问性 / visual regression。前端有两块：① Agent续写自己的 Python WebUI（`src/web/` 生成 HTML，stdlib）② Aeloon-Pro `ui/frontend`（React 19 + Vite + Tailwind + Vitest 103+ 测试，Scholar 设计系统）。

**落地**：

| 能力 | 工具 | 覆盖 |
|---|---|---|
| E2E 自动走查 | **Playwright** | iter043 那 5 条 journey（cold start→wizard→continue→failure recovery→drama）脚本化，每轮自动跑 + 自动截图，替代手工 |
| 可访问性 | **axe-core / @axe-core/playwright** | WCAG 2.1 AA 自动扫（当前完全空白） |
| 视觉回归 | Playwright screenshot 快照 | 防深色模式/样式债改动引入视觉不一致 |
| 本机验证 | 内置 `/verify` skill | 改完前端跑起来真看一眼（替代"让用户手工确认"） |
| 设计系统同步（可选） | `/design-sync` + DesignSync 工具 | 把 Aeloon Scholar 设计系统组件库与 claude.ai/design 项目同步管理；**偏重，仅当要正式维护设计系统时做** |

**收益**：把 iter043/iter060 那种"手工走查 5 条 journey"变成一条命令；a11y 从 0 到有。**工作量**：高（Playwright 搭建 + 写 5 条 journey 脚本，1–2 天）。**建议**：先做 Playwright 跑 happy path + 1 条 failure recovery，a11y/visual 增量补。

---

### 🟡 P1-D 防误操作护栏（hooks · 未点名但开发成本极低、防灾价值高）

**对口**：工作流约定「只 commit 不 push」与铁律第1/2条的凭据/版权边界。这些约定可用 hooks 硬执行：

| hook | 作用 |
|---|---|
| `PreToolUse[Bash]` matcher `git push` | 非用户显式授权则 block（exit 2）——落实只 commit 不 push |
| `PreToolUse[Edit\|Write]` 路径含 `.env`/`data/`/`outputs/`/`logs/`/`小说txt/` | 直接 block——铁律第1/2条版权与密钥护栏 |
| `PostToolUse[Edit\|Write]` matcher `src/*.py` | 提示/自动跑相关单测子集 |
| `Stop` hook | 收尾时检查"碰了 src 但没同步 README SOP 表"→ 提醒（兜底铁律第7条） |

**收益**：把三条最重要的安全/纪律铁律从"靠记性"变成"硬拦截"。**工作量**：低（几个 shell 命令 + settings 配置，1–2 小时）。**建议**：和 P0-B 一起做。

---

### 🟡 P1-E 真模型实跑工具化

**对口**：真模型长跑需要逐次授权（铁律第5条）。当前已有 per-call/step timeout、预算、resume、heartbeat 与 supervisor，剩余工作是真模型 capstone 校准。

**落地**：把现有 `scripts/drive_book.sh` 包成带护栏的 skill 或 workflow——内嵌预算上限 cap、自动 preflight、超时/预算监控、结束自动汇总 `cost_cny`/`panel_score`/status。可结合 `/loop`(自定步调轮询进度) 或 `/schedule`(cron 云端值守)。
**⚠️ 注意**：长跑值守期间用户会从终端 commit/resume，定时任务别和用户手动操作抢锁，要先约定节拍。
**工作量**：中。**优先级**：本轮未勾选，列为可选。

---

### 🟢 P2 锦上添花（备选，暂不主推）

- **pre-commit 本地门禁**：抄 Aeloon-Pro 的 ruff 配置 + 加一条"扫 `read_json(` 非 optional 调用点"的规则（直接对口 iter059 坏 JSON crash 教训）。项目纪律是不 push，所以 **GitHub Actions CI 价值有限**，但**本地 pre-commit 有用**。
- **workflow 编排**（已开 `enableWorkflows`）：铁律第8条的多视角审查适合 parallel-verify；真模型多 tier/多书并跑仍需遵守逐次授权。
- **`fewer-permission-prompts` skill**：权限列表已 152 行说明弹窗很多，可用它扫高频只读调用、整理 allowlist。
- **项目级 `CLAUDE.md`**：已建薄壳并通过 `@AGENTS.md` 引入当前规则。

---

## 三、推荐落地路线图

| 步骤 | 做什么 | 工作量 | 见效 |
|---|---|---|---|
| **第 1 步（今天）** | P0-A：下一轮 iter 收尾改用 `/code-review high` + `/security-review`；改一句 SOP 措辞 | ≈0 | 立即 |
| **第 2 步（半天）** | P0-B 的 `/iter-start` `/iter-finish` + P1-D 护栏 hooks 一起做 | 中 | 每轮省 20–30min + 硬纪律 |
| **第 3 步（1–2 天）** | P0-C：Playwright 跑 happy path + failure recovery，a11y 增量补 | 高 | 替代手工走查 |
| 后续可选 | P1-E 真模型工具化 / P2 pre-commit / workflow / 薄 CLAUDE.md | — | 按需 |

---

## 四、不推荐 / 暂不做（避免过度工程）

- **MCP 集成**：当前开发流程无明确需求，不为了用而用。
- **GitHub Actions CI**：项目纪律"只 commit 不 push"，远端 CI 触发面窄，本地 pre-commit 已覆盖核心收益。
- **`/design-sync` 全量铺设**：仅当要把 Scholar 当正式设计系统长期维护时才值得，否则偏重。

---

## 五、附录：本报告引用的可用 skill / 工具清单

| 名称 | 类型 | 用途 |
|---|---|---|
| `/code-review`（含 `ultra`） | 内置 | diff/分支代码审查；ultra=云端多 agent |
| `/security-review` | 内置 | 待提交改动安全审查 |
| `/simplify` | 内置 | 复用/简化/效率清理并应用 |
| `/verify` | 内置 | 跑起来真验证改动是否生效 |
| `skill-creator` | 内置 | 造/改/评测自定义 skill（用于 P0-B） |
| `update-config` | 内置 | 配 hooks / 权限 / env 进 settings.json（用于 P1-D） |
| `fewer-permission-prompts` | 内置 | 扫高频只读调用、整理 allowlist |
| `/loop` `/schedule` | 内置 | 轮询/定时（用于 P1-E 真模型值守） |
| `/design-sync` + `DesignSync` | 内置 | 设计系统组件库与 claude.ai/design 同步（P0-C 可选） |
| Playwright + axe-core | 外部 | 前端 E2E + 可访问性（用于 P0-C，需新引入） |
