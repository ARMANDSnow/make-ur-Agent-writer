# 短剧 + 表格 模块 · 产品定义书

> **文档性质**：PM 产品定义书。**iter 035 开题写就，不产出代码**；iter 036 起的施工单作者以此为输入逐项拆解。
>
> **作者**：Claude · **创建日**：2026-06-03 · **状态**：v0 草案（待用户 review §6 关键决策点）
>
> **不在范围**：真模型 capstone、视频生成、分镜可视化、TTS 配音、多语言

---

## 1. 用户场景与目标

### 1.1 目标用户画像

- **主要**：自媒体短剧创作者 —— 抖音 / 快手 / 视频号 上做 1-3 分钟竖屏短剧的小团队（1-3 人）或个人创作者。
- **次要**：网文作者拓品类、长剧编剧做 pitch / 试集本、教学场景（编剧课用 AI 辅助）。
- **典型工作模式**：
  - 一周出 3-5 集；剧本写完 1-2 天内拍摄 + 剪辑出片。
  - 已有题材方向（霸总 / 重生 / 系统流 / 推理短剧 等子赛道），缺的是 **快速把脑中梗概变成可拍剧本** 的能力。
  - 重度依赖人物表 / 场景表 / 道具表来维持连续集的连续性（否则第 10 集时主角突然换名字 / 出现没铺垫过的道具）。

### 1.2 与 novel 模块用户的差异

| 维度 | novel 用户 | drama 用户 |
|---|---|---|
| 产出粒度 | 1 章 ≈ 4000 字，30+ 章长篇 | 1 集 ≈ 200-600 字，20-100 集系列 |
| 单元节奏 | 章节内多场景、章首章末有钩 | 单集 3-6 场，场场要钩 |
| 评审重点 | 文笔 / 关系一致 / 伏笔回收 | 对白口语化 / 节奏紧凑 / 钩子吊人 / 时长准 |
| 辅助数据 | entity_graph 走 LLM 生成 | 人物 / 场景 / 道具 4 张表，**用户高频手编** |
| 导出 | 整本 .md / 章节列表 | 单集 Fountain `.fountain` / `.fdx` 可直接进剪辑/拍摄流程 |

### 1.3 用户旅程（创作单部短剧）

```
1. 起步     用户在书架点「+ 新建」→ wizard 选「短剧」类型 → 填题材 / 受众 / 集数 / 单集时长
2. 调研     AI 6-agent 辩论（套用 novel 现成的 debate 模块）→ 产出 logline + 整剧大纲 + 初版人物 / 场景 / 道具表
3. 用户校准 在 4 张表里手编 / 删 / 增（manual_override 标记）→ 锁定起点
4. 规划     一键 plan-episodes → plan_episodes.json（类比 chapter_plan.json）
5. 写集     write-episode 单集生成（Fountain 输出 + 自动更新 4 张表的关联字段）
6. 评审     drama_reviewer 5 维度子分数 → 不达标自动重写（沿用 write-book 的 retry/budget 逻辑）
7. 导出     单集 / 整剧导出 .fountain / .fdx / .txt / .md
```

### 1.4 成功指标（v1 落地后）

- **快**：从「我想做一个霸总赛道短剧」到「拿到第 1 集可拍剧本」≤ 30 分钟（mock 模式秒级；真模型按 token 预算）
- **稳**：第 1 集 → 第 20 集人物名字、关系、关键道具零漂移（4 张表锁住）
- **可用**：导出的 Fountain 可在 Highland / FadeIn / Slugline 等专业工具打开无报错
- **可控成本**：单集真模型成本 ≤ ¥0.5（mock 模式 ¥0）

---

## 2. 内容 Schema

### 2.1 剧本格式选 Fountain syntax（核心决策）

**为什么 Fountain**：
- **纯文本**：与现有 `outputs/drafts/chapter_NN.md` 一致的 git-friendly 存储
- **Markdown 友好**：可在 WebUI 用现有 `_mdToHtml` 风格的渲染器加几行规则就能可读化
- **工业标准**：Highland / FadeIn / Slugline / Fade In 等专业编剧工具原生支持，有现成 `.fountain → .fdx / .pdf` 转换链路
- **学习成本低**：剧本只有 5-6 种格式约定（slugline / action / character / dialogue / parenthetical / transition）

**最小 Fountain 子集**（v1 实现）：

```fountain
Title: 第 3 集 · 顶楼对峙
Credit: AI Continuator (drama)
Episode: 3
Duration: 90s

INT. 总裁办公室 - 夜

落地窗外的城市灯火。林见秋背对门口，手里把玩一只白瓷茶杯。

林见秋
(头也不回)
你以为我会让你走？

苏念站在门口，攥着辞职信，指节发白。

苏念
您没有理由留我。

(片刻沉默。林见秋转身，茶杯重重砸在桌面。)

林见秋
我从来不需要理由。

CUT TO:
```

支持的元素：
- `Title: / Credit: / Episode: / Duration:` —— title page（我们扩展用于元数据）
- `INT.` / `EXT.` 开头 = scene heading（slugline）
- 全大写一行 = character name（紧接的下一段是 dialogue）
- `(...)` 包裹 = parenthetical（动作 / 表情提示）
- 普通段落 = action / stage direction
- `CUT TO: / FADE OUT:` 等 transition

### 2.2 单集落盘结构

```
workspaces/<name>/
├── data/
│   ├── tables/
│   │   ├── people.json       # 人物表（含 manual_override 标记）
│   │   ├── scenes.json       # 场景表
│   │   ├── props.json        # 道具表
│   │   └── timeline.json     # 时间线（episode × beat 网格）
│   └── (其它沿用 novel)
├── outputs/
│   ├── debate/               # 沿用 novel 的 6-agent 辩论
│   │   ├── outline.md
│   │   ├── decisions.json
│   │   └── plan_episodes.json   # 类比 chapter_plan.json
│   ├── episodes/
│   │   ├── episode_01.fountain
│   │   ├── episode_01.meta.json   # verdict / cost / sub_scores / duration_estimate
│   │   ├── episode_01.review.json # 类比 chapter_NN.review.json
│   │   └── ...
│   └── (其它沿用)
└── logs/                     # 完全沿用
```

### 2.3 单集元数据 schema（`episode_NN.meta.json`）

```json
{
  "episode_no": 3,
  "title": "顶楼对峙",
  "target_duration_seconds": 90,
  "estimated_duration_seconds": 84,
  "char_count": 412,
  "scene_count": 2,
  "verdict": "Approve",
  "rewrite_count": 1,
  "needs_human_review": false,
  "cost_cny": 0.18,
  "agent_reviews": [
    {
      "agent_name": "对白评审",
      "verdict": "Approve",
      "score": 8,
      "sub_scores": {
        "plot": 7,
        "dialog_naturalness": 9,
        "pace": 8,
        "hook_strength": 8,
        "duration_compliance": 9
      },
      "issues": [],
      "suggestions": []
    }
  ],
  "table_updates": {
    "people": ["林见秋", "苏念"],
    "scenes": ["总裁办公室"],
    "props": ["白瓷茶杯", "辞职信"]
  }
}
```

### 2.4 4 张辅助表 schema

**人物表 `people.json`**：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "p001",
      "name": "林见秋",
      "role": "主角 / 总裁",
      "arc_summary": "从权术冷峻到承认自己被打动",
      "voice_notes": "短句、命令式、少形容词",
      "appearances": [1, 2, 3, 5, 7],
      "manual_override": false
    }
  ]
}
```

**场景表 `scenes.json`**：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "s001",
      "location": "总裁办公室",
      "interior_or_exterior": "INT",
      "first_episode": 1,
      "usage_count": 4,
      "notes": "落地窗、深色木桌、单人沙发",
      "manual_override": true
    }
  ]
}
```

**道具表 `props.json`**：

```json
{
  "schema_version": 1,
  "entries": [
    {
      "id": "prop001",
      "item": "白瓷茶杯",
      "debut_episode": 3,
      "final_episode": null,
      "story_function": "权力具象化；后续可砸 / 可碎；象征林见秋的克制",
      "manual_override": false
    }
  ]
}
```

**时间线表 `timeline.json`**：

```json
{
  "schema_version": 1,
  "rows": [
    {"episode_no": 1, "main_plot_progress": "霸总初次出场，给苏念塞辞职信压力", "subplot_progress": "苏念家境暗线", "manual_override": false},
    {"episode_no": 2, "main_plot_progress": "苏念准备辞职", "subplot_progress": "母亲住院", "manual_override": true}
  ]
}
```

`manual_override: true` 的行 / 条目，agent 后续重写时**必须保留**，并把 LLM 提议作为 *建议* 写入 advisor，而不是直接覆盖。

---

## 3. 工作流

### 3.1 Bootstrap（一次性，新建 drama workspace 时）

类比 novel 的 `auto-pipeline-greenfield`，drama 的 bootstrap pipeline：

```
1. 用户填表  题材描述 / 受众 / 集数 / 单集时长 / 已有题材参考（可选 .txt 上传）
2. 6-agent 辩论  套用现成 debate 模块；6 个 agent 换成 drama 视角：
   - 题材定位（霸总 / 重生 / 推理 / 系统 等子赛道判断）
   - 人物原型
   - 节奏控制（每集 hook 模板）
   - 受众心理（抖音 vs 快手 vs 视频号）
   - 商业可行性（变现钩 / 完播率）
   - 制作可行性（场景数 / 演员数 / 道具复杂度）
3. 产出     outputs/debate/outline.md (logline + 主线 + 风格指南)
            outputs/debate/decisions.json (6 个关键问题的投票)
            data/tables/{people,scenes,props,timeline}.json 初版
```

### 3.2 Plan episodes（用户校准 4 张表后）

```
入参    target_episodes / start_from_episode / replan_every (类比 novel)
聚合    outline.md + people.json + scenes.json + props.json + timeline.json
输出    outputs/debate/plan_episodes.json
        [{episode_no, title, logline, hook_in, hook_out, scenes_to_use, people_in_play, beats, target_duration_seconds, plot_purpose}]
```

### 3.3 Write episode（单集生成 + 自动 advance 4 张表）

```
入参    episode_no / budget_cny / max_retries / min_confidence / require_external_review (照搬 write-book)
流程    plan_episodes[episode_no] → 上集 ending state → 4 张表当前状态 → episode_writer
       → 产出 episode_NN.fountain + meta.json
       → drama_reviewer 5 子分数
       → 不达标 retry（最多 max_retries 次）
       → 达标后 advance_tables：解析剧本里出现的人物 / 场景 / 道具，更新 4 张表
                              · 新出现的非 manual_override 条目自动入库
                              · 已存在的更新 appearances / usage_count
                              · manual_override=true 的条目只追加，不覆盖
```

### 3.4 Review episode（独立可触发）

类比 novel 的 `review-chapter`，针对单集重跑 5 子分数评审，不重写。

### 3.5 Export

- 单集：下载 `.fountain`（默认）/ `.fdx`（需要 `fountain-tools` 之类的纯 Python 转换器）/ `.txt`（脱掉 Fountain 标记）
- 整剧：tarball `<workspace>_episodes.zip`，里面 `episode_01.fountain` ... + `manifest.md`

---

## 4. 与现有 novel 模块的复用 / 改动 / 新增

### 4.1 完全复用（一字不动）

| 模块 | 复用方式 |
|---|---|
| `src/llm_client.py` | drama agent 同样走 LiteLLM |
| `src/debater.py` | drama 6-agent 辩论沿用，仅换 agent 配置 |
| `src/reviewer.py` 框架 | 多 agent 投票 + sub_scores 直接套；drama_reviewer 只是 `agents.yaml` 的新条目 |
| `src/observability.py` | 成本日志、`llm_calls.jsonl` 完全沿用 |
| `src/web/jobs.py` | 任务模型不变（plan / write / review 三类） |
| `src/web/server.py` | 不动 |
| `src/web/templates.py` `_BASE_TPL` / `_topbar_actions` / `_render_shell` | 不动 |
| `src/web/static.py` 的 design tokens / components / `showToast` / modal / tabs | 不动 |
| `src/web/trash.py` | 不动 —— drama workspace 同样进 `_trash/` |
| `src/web/insights.py` | 不动；后续 drama 单独写 `drama_insights.py` |
| wizard 多步表单底盘 | 复用，仅添加 type 选择步 |

### 4.2 最小改动（影响面：5 个文件）

| 文件 | 改动 |
|---|---|
| `src/paths.py` | 加 `episodes_dir() / plan_episodes_path() / tables_dir() / people_table_path() / scenes_table_path() / props_table_path() / timeline_table_path()` |
| `src/cli_workspace.py` | `init_workspace(name, type="novel")` 加 type 参数；落 `data/workspace.json` `{type: "novel"|"drama"}` |
| `src/web/_naming.py` | 不动（workspace 名字规则不变） |
| `src/web/templates.py` | `_WORKSPACE_SECTIONS` 改成 type-aware 函数 `_sections_for(type)`；render_workspace_overview 加类型 badge |
| `src/web/routes.py` | `/api/workspaces/overview` 返每个 workspace 加 `type` 字段；新增 drama 路由（见 4.3） |

### 4.3 新增 drama-only 文件

```
src/
├── drama_planner.py        # 类比 plot_planner.py，输出 plan_episodes.json
├── episode_writer.py       # 类比 writer.py，输出 .fountain
├── drama_reviewer.py       # 5 子分数评审器（plot / dialog_naturalness / pace / hook_strength / duration_compliance）
├── fountain_renderer.py    # Fountain → HTML（WebUI 展示用，纯字符串处理）
├── fountain_exporter.py    # Fountain → FDX / TXT（导出用）
├── table_advance.py        # 解析 .fountain 提取人物 / 场景 / 道具并 advance 4 张表
└── web/
    ├── drama_view.py       # 聚合单集 / 整剧 / 4 张表数据给 API
    └── tables.py           # 4 张表的 GET / PUT API + manual_override 合并逻辑

prompts/drama/
├── debater_topic_position.txt
├── debater_topic_pace.txt
├── ...
├── drama_planner.txt
├── episode_writer.txt
├── drama_reviewer.txt
└── table_advance.txt

config/
└── agents.yaml             # 增加 drama_agents 段（与 novel_agents 并列）
```

---

## 5. WebUI IA 集成草图

### 5.1 Wizard 加 type 选择（第 0 步）

```
┌─────────────────────────────────────────────┐
│  ✦ 新建作品                                 │
│  ─────────────────────────────              │
│                                             │
│  你要创作什么？                             │
│                                             │
│  ○ 小说续写（章 → 章）                      │
│    导入 epub/txt，AI 续写长篇                │
│                                             │
│  ● 短剧剧本（集 → 集）                      │
│    填题材，AI 生成可拍 Fountain 剧本        │
│                                             │
│  [ 下一步 ]                                 │
└─────────────────────────────────────────────┘
```

后续 wizard 步骤按 type 分支：
- novel：保持现状（upload .epub/.txt）
- drama：题材 / 受众 / 集数 / 单集时长 表单 + 可选参考 txt

### 5.2 Sidebar sections 按 type 切

```python
_SECTIONS_NOVEL = (
    ("overview", "概览", ""),
    ("continue", "续写", "continue"),
    ("plan", "计划", "plan"),
    ("chapters", "章节", "chapters"),
    ("reviews", "评审", "reviews"),
    ("insights", "数据", "insights"),
    ("jobs", "任务", "jobs"),
)
_SECTIONS_DRAMA = (
    ("overview", "概览", ""),
    ("write", "写集", "write"),
    ("plan", "大纲", "plan"),
    ("episodes", "分集", "episodes"),
    ("tables", "人物 · 场景 · 道具", "tables"),
    ("reviews", "评审", "reviews"),
    ("insights", "数据", "insights"),
    ("jobs", "任务", "jobs"),
)
```

### 5.3 书架卡片显示类型 badge

`/` 主页每张 workspace card 顶部右上角：
- novel workspace：`<span class="badge no-dot">小说</span>`
- drama workspace：`<span class="badge jade">短剧</span>`（用现有 jade-soft tokens）

### 5.4 关键新页面 IA

```
/w/<drama-name>/tables  →  4 个 tab：人物 / 场景 / 道具 / 时间线
                          每 tab 一个可编辑 grid（行可增删 / 单元格双击编辑）
                          行带 manual_override checkbox（用户勾上后 agent 不再覆盖）
                          顶部「让 AI 补全」按钮 → 提交所有 manual_override=false 的行让 LLM 重生

/w/<drama-name>/episodes  →  分集列表（沿用 chapters 页面的结构）
                            每行：集号 / 标题 / verdict / 时长估算 / 字数 / [查看]

/w/<drama-name>/episode/<n>  →  类比 chapter detail：
                              tab 1 剧本（Fountain 渲染 + scene/dialog 高亮）
                              tab 2 评审（5 子分数横条 + issues）
                              tab 3 表格变更（本集导致 4 张表的哪些行更新）
                              tab 4 历史（rewrite_count / 时长 vs 目标差值）
                              tab 5 导出（按钮：.fountain / .fdx / .txt）
```

### 5.5 4 张表 grid 组件草图

```
┌─────────────────────────────────────────────────────────────────┐
│  人物表                            [+ 新增] [让 AI 补全] [保存] │
│  ───────────────────────────────────────────────────────────── │
│  name      role         voice_notes        appearances  override│
│  林见秋    主角 / 总裁  短句、命令式…      1,2,3,5,7    ☐      │
│  苏念      女主         软糯、欲言又止…    1,2,3        ☑      │
│  夏老板    反派 / 父亲  威压、长句…        5,7          ☐      │
└─────────────────────────────────────────────────────────────────┘
```

实现要求（不用 React、不用 grid 库）：
- 复用 iter 032 `.table` 样式
- 单元格双击 → contenteditable
- Enter / blur 保存（PUT `/api/workspace/<name>/tables/people/<row_id>`）
- 顶部 Save 按钮调用批量 PUT
- 数据流：拉 `GET /api/workspace/<name>/tables/people` → 渲染 → 用户编辑 → PUT 单行 → 重渲染

---

## 6. 关键决策点（待用户 review）

| # | 决策 | 推荐 | 备选 |
|---|---|---|---|
| D1 | 剧本格式 | **Fountain syntax** | Markdown 自定义 / 纯 JSON |
| D2 | 集时长范围 | **60-180 秒，缺省 90** | 让用户输 1-300 任意；锁死单一时长 |
| D3 | 表格双向编辑合并策略 | **manual_override 行只追加 advisor 建议，不覆盖；非 override 行随 advance 重写** | 全用户优先 / 全 AI 优先 / 每次都 diff 提示 |
| D4 | drama / novel 是否共享角色库 | **完全隔离**（drama workspace 不引用 novel workspace 数据） | 提供 import 入口 |
| D5 | 导出格式 | **首版只做 .fountain + .txt；.fdx 留 iter 040+** | 一上来就 .fdx + .pdf |
| D6 | 语言 | **首版只锁中文** | 同时支持英文产出（agent prompt 双语） |
| D7 | 6-agent 辩论复用还是改写 | **复用 debate 框架，只换 agent 列表 + prompt** | 重写 drama 专属辩论模块 |
| D8 | 是否支持竖屏 / 横屏标注 | 首版不做 | meta 加 `aspect_ratio` 字段 |

**用户 review 时只需关注 D1-D5**；D6-D8 可在 iter 036 开工前确认。

---

## 7. 与 iter 036+ 的桥接（建议拆分）

按本文档拆解，预估 4 个 iter 完成 drama 模块 v1：

| iter | 主题 | 大致内容 |
|---|---|---|
| **036** | drama 基础设施 | `workspace.type` 字段 + wizard type 分支 + 书架 type badge + drama 空 workspace 骨架（目录 + `workspace.json`）+ sidebar `_sections_for(type)` |
| **037** | drama bootstrap + plan | `prompts/drama/*.txt` 全套 + `drama_planner.py` + drama wizard auto-pipeline（mock）+ `/w/<name>/plan` drama 视图（plan_episodes.json + 4 张表初版） |
| **038** | episode write + 表格 grid | `episode_writer.py` + `fountain_renderer.py` + `/w/<name>/episodes` + `/w/<name>/episode/<n>` + `/w/<name>/tables` 4 表 grid（含 manual_override 合并） |
| **039** | review + advance + export | `drama_reviewer.py` 5 子分数 + `table_advance.py` 自动推进 4 张表 + Fountain → TXT 导出 + drama Insights 子页 |

每 iter 仍按 iter 033/034 的施工单粒度（§A/§B + 完整 HTML/JS 片段 + 测试断言模板）交付给 Codex。

---

## 8. 风险与开放问题

### 8.1 已识别风险

- **mock 模式输出质量**：drama 对话比小说叙述更难 mock；mock 模式下产出的 .fountain 可能完全是占位符。**缓解**：mock 用 fixture-driven，预制 10 集示范 fixture。
- **manual_override 合并复杂度**：用户改了表 + LLM 又跑了一遍，冲突处理逻辑容易出 bug。**缓解**：v1 严格"override 行只追加"，复杂合并留 iter 040+。
- **Fountain 渲染兼容性**：自研渲染器可能不覆盖所有专业工具的 edge case。**缓解**：v1 只支持上面 §2.1 列出的最小子集；用户能在 Highland 打开导出文件即合格。
- **agent prompt 调优周期**：drama prompt 第一版几乎必然不够口语化 / 不够紧凑。**缓解**：iter 037-039 留 mock 调试空间，真模型 capstone 推迟到 iter 040+。

### 8.2 待用户决策（D1-D5 不定 iter 036 起不动）

见 §6。

### 8.3 长期 backlog（不进 iter 036-039）

- 视频生成 / 分镜可视化
- TTS 配音 + 角色音色库
- 真模型 capstone（多用户 / 多剧并行）
- 跨剧角色库 / 题材模板市场
- 协作编辑（多用户同时编一张表）

---

## 9. 文档版本与维护

- **v0** 2026-06-03 · Claude 起草，待用户 review §6
- **v1** （iter 036 启动前）· 用户拍板 D1-D5 后定稿
- **v2** （iter 039 收官后）· 根据落地经验回填实际 schema 与 prompt

本文档以 git commit message `docs(drama): bump short_drama_module.md to vN` 形式滚动维护，不直接覆盖 v0 历史。
