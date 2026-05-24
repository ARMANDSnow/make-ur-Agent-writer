# 阶段 3 小结：多书 workspace + 多语言 + 无人值守 + 审计加固

> 覆盖范围：[iteration 014](./iterations/iteration_014_plot_planner.md) - [iteration 019](./iterations/iteration_019_unattended_writer.md)
> 时间窗：2026-05-18 至 2026-05-24
> 阶段定义：从"单书、中文、有人值守"上升到"任意中英文小说 → init-book → debate → write_book.sh 无人值守"端到端可用，并通过审计修复消除两个 silent-failure 漏洞。

## 阶段目标回顾

阶段 2 末已经能让 deepseek 写出第 1 章并通过 7-reviewer 审查，但日常使用仍有 4 个摩擦点：

1. **章节排版孤立**：write_smoke.sh 只产 1 章，无 plot planner 提供下一章衔接信息
2. **persona 硬编码**：要换书必须改 `config/agents.yaml` 里的 5 个 persona 描述
3. **单书目录耦合**：所有 outputs / data / logs 共享一份目录，多书会互相覆盖
4. **每章手工 gate**：write_book.sh 每章打印 `apply-advance --proposal-idx <list>` 然后 exit 0，要人盯着

阶段 3 末的达成定义是：

- 任意中英文小说 → `init-book` 自动起 persona / 自动 propose / 自动 advance → `debate` 产 outline → `write_book.sh --book <name> N` 跑 N 章不间断不要人
- 多书并存零干扰（sha256 byte-identical baseline）
- 5-agent reviewer 失败时不 silent approve（fail-closed Abstain）
- workspace 路径不被 `WORKSPACE_NAME=../escaped` 类输入穿越
- write_book.sh 重试用尽时 snapshot 必须落盘

## 已交付能力（阶段累计）

### 1. Plot planner 衔接（iter 014）

`python3 main.py plan-chapters --chapters N` 调 claude-opus-4-5 一次产 N 章规划，写到 `outputs/debate/chapter_plan.json`，writer 每章 prompt 注入 `chapter_n.brief + chapter_n+1.preview` 让段尾自然挂下章钩子。`write_smoke.sh` 升级为 `write_book.sh`，承载多章循环骨架。

### 2. Persona 抽象（iter 015 + 016）

iter 015 引入 `auto_bootstrap` —— 用 LLM 从小说样本自动产 4 类 proposal：`entity_graph_seed / global_facts / continuation_anchor / style_examples`，人工 `cli_apply_bootstrap.py` 审批落 disk。

iter 016 把 persona 也变成 proposal：`bootstrap-personas` 调 LLM 出 5 个 agent 的角色描述（名称 + 视角 + 关注点 + 评分维度），落 `data/manual_overrides/personas.json`，`src/persona_loader.py` 在 debate 和 review 阶段把模板里的 `{persona_name}` 等占位符替换成 workspace 自己的 persona。换书不再改任何 yaml。

### 3. 多 workspace 隔离（iter 017）

`src/paths.py` 把所有 module-level 路径常量改成函数（`data_dir()` 等），每次调用重读 `WORKSPACE_NAME` env。CLI 加 `--book <name>` 前置解析，等价于 `export WORKSPACE_NAME=<name>`。所有 outputs / data / 小说txt / logs 移到 `workspaces/<name>/`。legacy 模式（env 不设或 == `"legacy"`）保留 byte-identical 旧行为。

实证：xueZhong（《血中》中文）+ longzu（《龙族》中文）+ asoiaf（《冰与火》英文）+ legacy 4 个 preflight 全绿、4 套 sha256 baseline 不互相污染。

### 4. 多语言切章 + EPUB 提取（iter 018）

`src/lang_detect.py` 用 CJK 字符比率自动判中英。`src/chapter_splitter.py` 同时挂中文（`第N章` / `卷N`）和英文（`POV` / `CHAPTER N` / `^[A-Z ]{3,}\n` block）两套 regex，按检出语言切换。`src/epub_to_txt.py` 用 stdlib `zipfile + xml.etree + html.parser` 不引入 ebooklib / beautifulsoup 把 epub 转 txt + 还原章节顺序（spine 元数据）。

ASOIAF 英文 epub → 110 章拆分 + 章节标题命中率 100%，跑通 init-book 全流程（含 plot_planner 用英文出大纲）。

### 5. 无人值守 write_book.sh（iter 019）

- 新增 `python3 main.py chapter-status <i>` 纯 IO 查询：返回 `{exists, approved, needs_review, failure, verdict, rewrite_count}`，`approved` 当且仅当 `exists ∧ ¬failure ∧ ¬needs_review ∧ verdict=="Approve"`
- `apply-advance` 新增 `--auto-apply --min-confidence 0.7 --allow-empty --confirm`：阈值之上自动选 proposal index 应用，无匹配也 exit 0 不打断 loop
- `scripts/write_book.sh` 删除所有 `--proposal-idx <comma-list>` 提示和 `Then re-run` 文案；改为 `--max-retries 2`（默认）循环：写完 → review-chapter → chapter-status 查 approved → 不通过则 `clear_chapter_state(i)` 再来 → 用尽次数打 `GAVE UP on chapter N` 并 exit 2
- 通过则 `apply-advance --auto-apply` 推进 entity_graph，进下一章
- `WRITER_FORCE_FAIL` 测试钩子（仅 `OPENAI_MODEL=mock` 时生效）让 retry-path 在单测里也能覆盖

### 6. 审计修复（iter 019 audit pass）

阶段 3 末做了一次代码审计，发现两个 silent-failure 类问题，独立 commit：

**6.1 Reviewer silent-approve bug（commit `7a33425`）**

旧 `src/reviewer.py` 在 5-agent 循环里若任一 agent JSON 解析失败，会立刻把当前 review batch 当 Approve 返回，永不进入后续 agent，verdict 写成 Approve。在 longzu + xueZhong 两个真实 workspace 的 reviews 目录都找到了带 `(parse_failed)` 字样的 silent Approve 记录。

修复：解析失败的 agent 改记 `verdict="Abstain"` + `_fallback_reason="(parse_failed)"`，loop 继续；post-loop 用 fail-closed 规则——任何 substantive Reject → Reject；零 substantive Approve → Reject；只有 ≥1 Approve 且 0 Reject → Approve。新增 `_fallback_reason="(all_agents_parse_failed)"` 标记全 abstain 的情况。

回归测试 `tests/test_reviewer_text_review.py` 原本是把 bug 当 spec 写的，一并改成断言新的 fail-closed 行为。

**6.2 workspace name 路径穿越（commit `81afc5a` 的一部分）**

旧 `src/paths.py` 对 `WORKSPACE_NAME` 不做校验，`WORKSPACE_NAME="../escaped"` 会被 resolve 成 `workspaces/../escaped`，章节会写到 workspaces 之外。单用户本地场景下威胁有限，但 fat-finger 一次就把章节散到意外目录里。

修复：`_validate_workspace_name(name)` 拒绝 `/`, `\\`, 首字符 `.`, 包含 `..`；Unicode（如 `龙族`）仍允许。`workspace_name()` 和 `workspace_root()` 都过校验。

**6.3 write_book.sh snapshot 丢失（commit `81afc5a` 的另一部分）**

旧脚本里 snapshot 块在主循环 `done` 之后，但 `exit 2`（重试用尽）在循环 *内部*，意味着 GAVE UP 路径根本走不到 snapshot ——失败的部分进度被丢弃，用户失去 diagnostics。

修复：抽出 `take_snapshot(suffix)` 函数，成功路径调 `take_snapshot ""`，失败路径调 `take_snapshot "_aborted_chNN"` *在* `exit 2` 之前。新增结构性测试断言两条路径都调用 + 顺序正确。

## 真模型 smoke 结果（阶段 3 末）

| Workspace | 命令 | 结果 |
|---|---|---|
| longzu | `bash scripts/write_book.sh --book longzu 1` | ch1 Approve（4 Approve + 1 Abstain），lint 0 issues，draft 13.8K 字符，30 LLM calls，~¥0.45 |
| xueZhong | preflight + status | 4 模式全绿、sha256 baseline 不变 |
| asoiaf | preflight + status | 同上 + 多语言切章 110 章无 regression |
| legacy | preflight + status | byte-identical iter 013 行为 |

audit 修复的实战验证：longzu ch1 review 命中了"1 agent parse_failed"场景，旧版本会 silent Approve 写错的章节；新版本记 Abstain 不计票，靠其余 4 个 substantive Approve 决出最终 Approve —— 正确通过且不基于错误信号。

## 工程指标

| 指标 | 阶段 2 末 | 阶段 3 末 | 变化 |
|---|---|---|---|
| 测试数 | ~135 | 215 | +80 |
| `src/` 模块 | 21 | 26 | +5（lang_detect / epub_to_txt / persona_loader / paths / chapter_status / entity_advance） |
| CLI subcommand | 16 | 24 | +8（plan-chapters / workspace-* × 4 / bootstrap-personas / chapter-status / apply-advance auto flags） |
| Iteration doc | 13 | 19 | +6 |
| 外部依赖 | litellm + pydantic + tiktoken + python-dotenv | 同左 | **不变（iter 018 epub 提取坚持 stdlib-only）** |
| 真模型成本（阶段累计） | ~$2 | ~$3 | +$1（iter 016 / 017 / 019 各跑了 1 章 longzu 真模型 smoke）|

## 剩余风险与下阶段入口

### 风险

- **`not_x_but_y` lint 规则严格**：阈值 2 次，超了就 Reject。longzu ch1 第一次跑命中 6 次卡两轮重写。规则本身没问题，但 prompt 没有提示模型避免这类句式 → iter 020 或之后可以把 lint 规则反向喂给 writer system prompt
- **`apply-advance --min-confidence 0.7` 是全局阈值**：所有 relationship 类型共用一个数。如果某类 proposal 普遍 confidence 偏低，会被一刀切。未来可按关系类型分阈值
- **plot_planner 走 claude-opus-4-5 中转**：和 writer/reviewer 不在同一家 provider。`PLANNER_*` env 独立，但维护成本 = 2 套 key 管理
- **reviewer audit 修复后，单 agent parse_failed 会拉低 Approve 票数比例**：5 agents 里 1 个 abstain 时 Approve 票从 5 降到 4，更接近被一个真 Reject 翻盘的边界。模型稳定性是关键。生产中要监控 `_fallback_reason="(parse_failed)"` 出现频率
- **EPUB spine interleave**：iter 018 ASOIAF chapter_manifest 第一项是 337K 字符（spine 把 Book 1 和 appendix 交织了）。当前可接受，长远要在 chapter_splitter 加 size-cap fallback

### 下阶段入口（iter 020 候选）

阶段 3 把 CLI 链路打磨到了"unattended end-to-end runnable"。日常使用的剩余摩擦点已经从"流程没跑通"变成"要在多个 workspace 间切换 + 查 status + 看 cost"。iter 020 plan 已存盘 `/Users/dingyuxuan/.claude/plans/dapper-conjuring-mochi.md`，方向是 **stdlib-only 单用户本地 Web Dashboard**（`http.server` + `string.Template`，端口 8765，零新依赖），让浏览器代替 `python3 main.py --book X status` 这类查询，并提供"按钮触发 normalize / split / debate / write_book"的 mock-only 验收路径。**iter 020 全程零 LLM 成本**。

阶段 3 不引入认证 / 多用户 / WebSocket / SPA —— 这些都留给后续阶段，避免阶段 3 出口处膨胀。

## 阶段验收

| # | 项 | 结果 |
|---|---|---|
| A | 中英文小说均能 init-book → debate → write_book end-to-end | ✅ longzu / asoiaf 全跑通 |
| B | 多 workspace 隔离 byte-identical | ✅ sha256 baseline 4/4 |
| C | write_book.sh 真无人值守（无 manual gate string） | ✅ tests/test_write_book_script + 真模型 smoke |
| D | 5-agent reviewer 失败时 fail-closed | ✅ longzu ch1 实战命中 parse_failed 路径，未 silent approve |
| E | workspace 路径不可穿越 | ✅ tests/test_paths 5 个新断言 + ValueError |
| F | snapshot 在成功 + 失败两路都落盘 | ✅ tests/test_write_book_script + take_snapshot helper |
| G | 测试 ≥ 200 全绿 | ✅ 215 / 215 OK |
| H | 真模型 ≤ ¥5 单章 | ✅ ~¥0.45（longzu ch1 含 1 次失败重试）|
| I | iter 014-019 文档齐全 + README index | ✅ 6 份新 doc + AGENT_HANDOFF 更新 |

阶段 3 关闭。下一步：阶段 4 入口 = iter 020 Web Dashboard 设计（mock-only 验收，不接触真 key，零新依赖）。
