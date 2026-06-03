# 短剧 + 表格 模块 · 产品定义书

> **文档性质**：PM 产品定义书，iter 036+ 的 Codex 施工单作者以此为输入。
>
> **版本**：v1 · 2026-06-03（v0 写于 2026-06-03 早些时候，假设 Fountain 剧本，被用户工作流截图证伪 → 当日下午升 v1）
>
> **作者**：Claude
>
> **配套文档**：`docs/product/short_drama_creation_standard.md` v1（创作规范预设，给 LLM agent 作 system prompt 之源）
>
> **不在范围**：真模型 capstone、视频生成 SaaS、TTS 配音、多语言、跨剧 IP 复用

---

## 变更摘要（v0 → v1）

| 维度 | v0 假设 | v1 真实需求（基于用户工作流截图 + N1-N3 决策） |
|---|---|---|
| 核心产出 | 单一 Fountain syntax 剧本 | **三件套**：叙事剧本 + 分镜表 + 角色设定表 |
| 辅助表 | 4 张（人物 / 场景 / 道具 / 时间线） | **1 张核心角色设定表**（分镜表本身已是结构化数据） |
| 集时长 | 60-180 秒可变 | **60 秒默认，用户可选 30 / 60 / 90 / 120**（N2） |
| 工作流 | 一键生成全部 | **分步审查向导 4 站**：核心设定 → 钩子 → 分镜 → 角色（N4） |
| 下游消费 | 真人摄制 / 编剧工具 | **AI 绘画 + LoRA**（当前），AI 视频生成（后期）（N1） |
| 角色一致性 | 表格字段维护 | **LoRA-ready 文字 prompt + 内置预览图**（调外部 AI 绘画 API）（N3） |
| 导出 | .fountain / .fdx / .pdf | **JSON / Markdown table / CSV / Comfy workflow .json** |
| 季概念 | 平铺集 | **schema 预留 season 字段，UI v1 仅显单季**（N5 = γ） |

---

## 1. 用户场景与目标

### 1.1 目标用户

- **主要**：自媒体 AI 短剧创作者 —— 抖音 / 快手 / 视频号上做 1-3 分钟竖屏短剧的个人 / 小团队
- **关键工作模式**：
  - 已掌握 ComfyUI / SD WebUI / 即梦 / Midjourney 至少一种 AI 绘画工具
  - 已熟悉"LoRA / Reference"维护角色一致性
  - 需要的不是"AI 写剧本"——市面工具一抓一把；需要的是**剧本 + 分镜 + 角色 + 一致性维护**的全流程闭环
- **次要**：学编剧的学生、网文转短剧的作者、传统编剧学 AI 工具链

### 1.2 用户旅程（创作单集）

```
1. 选类型     wizard 选「短剧」→ 起名
2. 4 站向导    站 ① 核心设定（赛道 + 题材 + 人物一句话定型）
              站 ② 钩子（情绪 / 悬念 / 反差，AI 出 3 选 1，用户改）
              站 ③ 分镜（AI 出 60s × 6-9 镜，用户改）
              站 ④ 角色（AI 出 LoRA-ready 文字卡 + 预览图，用户改）
3. 评审       drama_reviewer 5 维度打分（钩子 / 节奏 / AI 友好 / 角色一致 / 钩出）
4. 导出       分镜表 JSON + 角色 prompt + Comfy workflow .json
5. 用户在 ComfyUI / SD / 即梦里跑出每个镜头的静态图
6. 用户用剪辑工具拼成短剧成片
```

### 1.3 与 novel 模块的差异（v1 实测版）

| 维度 | novel | drama |
|---|---|---|
| 单元粒度 | 1 章 ≈ 4000 字 | 1 集 = 60s = 6-9 镜头 |
| 产出 | 单一文本 | **3 件套**（剧本 + 分镜 + 角色） |
| 用户干预 | 一键 + 事后审 | **分步审查**（4 站每站可改） |
| 评审 | 文笔 / 关系 / 伏笔 | 钩子 / 节奏 / AI 友好 / 角色一致 / 钩出 |
| 下游 | 阅读 / 导出 .md | AI 绘画 → 拼接 → 短剧成片 |
| 集间关系 | 强（草蛇灰线） | 中（同一季角色表复用，剧情独立 hook） |

---

## 2. 内容 Schema

### 2.1 剧本格式选 JSON（v0 的 Fountain 被推翻）

**为什么不用 Fountain**：Fountain 是给真人摄制组用的（INT./EXT. slugline / parenthetical / transition）。AI 短剧的下游是 AI 绘画 / 视频生成，需要的是**镜头级结构化数据**，不是片场指令。

**选 JSON 的理由**：
- 一行一个镜头（与分镜表天然对齐）
- 字段稳定可校验
- 喂下游 AI 工具方便（直接 `prompt_list = [shot.画面内容 for shot in storyboard]`）
- Comfy workflow .json 同源，导出 0 转换成本
- Markdown table 渲染只是字段 join，UI 端 50 行内可实现

### 2.2 单集 schema（`episode_NN.json`）

```json
{
  "episode_no": 1,
  "season_no": 1,
  "title": "她重生在被抛弃的那一天",
  "logline": "26 岁女主被未婚夫抛弃当晚，重生回三年前同一天的早晨",
  "track": "重生",
  "target_duration_seconds": 60,
  "estimated_duration_seconds": 58,

  "core_setup": {
    "protagonist": "林晚，26 岁，普通职场女性，深爱周铭",
    "antagonist": "周铭，28 岁，精致利己型完美男友",
    "emotional_hook": "被抛弃 → 重生 → 第一次不再卑微"
  },

  "ai_friendly_constraints": {
    "scene_count": 2,
    "main_character_count": 2,
    "max_dialog_chars_per_line": 15,
    "narrative_mode": "纯画面驱动"
  },

  "narrative": "[起] ... [承] ... [转] ... [合] ...",

  "storyboard": [
    {
      "shot_no": 1,
      "shot_size": "特写",
      "camera_move": "静止",
      "duration_seconds": 3,
      "visual_content": "林晚的手紧握订婚戒指，关节发白；背景虚化是周铭的西装下摆",
      "voiceover": "",
      "dialogue": "",
      "ai_draw_prompt": "26-year-old Chinese woman's hand, knuckles white, holding diamond engagement ring, ...",
      "motion_prompt": null,
      "camera_movement_for_video": null,
      "is_highlight": false
    },
    {
      "shot_no": 6,
      "shot_size": "特写",
      "camera_move": "静止",
      "duration_seconds": 7,
      "visual_content": "林晚嘴角微微上扬，第一次露出平静的笑",
      "voiceover": "",
      "dialogue": "林晚：\"对。\" / \"我同意。\"",
      "ai_draw_prompt": "26-year-old Chinese woman, gentle smile, ...",
      "motion_prompt": null,
      "camera_movement_for_video": null,
      "is_highlight": true
    }
  ],

  "ending_hook": {
    "type": "悬念钩",
    "content": "抽屉里的「股权代持协议」露出一角"
  },

  "self_check": {
    "hook_match_track": true,
    "highlight_shot_no": 6,
    "duration_within_tolerance": true
  }
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `track` | 赛道 from `[霸总, 重生, 推理, 系统, 觉醒]` |
| `ai_friendly_constraints` | 创作规范 §三 的 5 条硬约束，**每集必填**作为自检凭证 |
| `narrative` | 创作规范 §二 的 [起][承][转][合] 4 段叙事正文（~300 字） |
| `storyboard[]` | 分镜表，每行一镜（创作规范 §四） |
| `storyboard[].ai_draw_prompt` | 喂给 SD / Comfy 的英文 prompt（角色名替换为 LoRA token 后） |
| `storyboard[].motion_prompt` / `camera_movement_for_video` | **预留字段**（N1 (b) 未来切 AI 视频生成时启用，v1 写 null） |
| `storyboard[].is_highlight` | "截图级"高光镜头，一集只能有 1 个 |
| `ending_hook.type` | 钩出类型 from `[情绪钩, 悬念钩, 反差钩]` |

### 2.3 单集 meta（`episode_NN.meta.json`）

类比 novel 的 `chapter_NN.meta.json`：

```json
{
  "episode_no": 1,
  "season_no": 1,
  "verdict": "Approve",
  "rewrite_count": 0,
  "needs_human_review": false,
  "cost_cny": 0.18,
  "agent_reviews": [
    {
      "agent_name": "drama_reviewer",
      "verdict": "Approve",
      "score": 8,
      "sub_scores": {
        "hook": 9,
        "pace": 8,
        "ai_friendly": 9,
        "character_consistency": 8,
        "cliffhanger": 8
      },
      "issues": [],
      "suggestions": []
    }
  ],
  "highlight_shot_no": 6,
  "duration_estimate_vs_target": {"target": 60, "estimate": 58, "delta": -2}
}
```

子分数 5 维度沿用创作规范 §九。

### 2.4 角色设定表（`data/characters/season_NN.json`）

```json
{
  "schema_version": 1,
  "season_no": 1,
  "characters": [
    {
      "id": "c001",
      "name": "林晚",
      "role": "主角 / 重生女主",
      "age_range": "25-27",
      "gender": "女",
      "lora_token": "lin_wan",

      "visual_features": {
        "face": "鹅蛋脸、单眼皮、嘴角下垂呈平眉抿唇型",
        "hair": "齐肩短发、刘海三七分",
        "body": "中等身高、背挺得直、走路时双手放在身侧"
      },

      "wardrobe_default": "米白色高领毛衣 + 灰色西装裤",
      "expression_keywords": ["克制", "警觉", "不轻易笑"],
      "visual_signature": "左耳一只极小的圆形银耳钉",

      "prompt_template_sd": "26-year-old Chinese woman, oval face, single-eyelid, gentle downturn lips, shoulder-length black hair with side-swept bangs, ivory turtleneck sweater, grey suit pants, small round silver earring on left ear only, restrained expression, ...",

      "reference_images": [
        {
          "path": "data/character_refs/c001/portrait_neutral.png",
          "generated_by": "sd_xl_1.0",
          "prompt": "...",
          "seed": 42
        }
      ],

      "appearances": [1, 2, 3, 5, 7],
      "manual_override": false,

      "visual_contrast_with": {
        "target_id": "c002",
        "rules": {
          "color_temperature": "冷调（米白/灰/深蓝） vs 暖调（酒红/棕/金）",
          "camera_height": "起初被俯拍 vs 起初俯拍主角",
          "frame_position": "画面左侧 vs 画面右侧"
        }
      }
    }
  ]
}
```

**字段约束**：
- `lora_token`：LoRA 触发词，下游 AI 绘画里用 `<lora:lin_wan:1.0>` 或 `lin_wan_v1` 等
- `prompt_template_sd`：英文 prompt，可直接拼接到分镜表 `ai_draw_prompt`
- `reference_images[]`：内置 AI 绘画 API 出的预览图，落盘 `workspaces/<name>/data/character_refs/<id>/`
- `manual_override`：用户手编后置 true，agent 重生时**只追加 advisor 建议，不覆盖**
- `visual_contrast_with`：主角 vs 反派的视觉对照规则（创作规范 §5.3）

### 2.5 落盘结构

```
workspaces/<drama-name>/
├── data/
│   ├── workspace.json              # {type: "drama", season_no: 1, schema_version: 1}
│   ├── characters/
│   │   └── season_01.json          # 第 1 季角色设定表
│   ├── character_refs/
│   │   ├── c001/
│   │   │   ├── portrait_neutral.png
│   │   │   ├── portrait_smile.png
│   │   │   └── portrait_angry.png
│   │   └── c002/...
│   └── creation_standard.snapshot.md  # 复制本期 short_drama_creation_standard.md，固化进 workspace（防上游文档变动影响已生成内容）
├── outputs/
│   ├── debate/                     # 6-agent 题材辩论（沿用 novel）
│   │   ├── outline.md
│   │   └── decisions.json
│   ├── episodes/
│   │   ├── episode_01.json         # 单集 schema (§2.2)
│   │   ├── episode_01.meta.json    # 单集 meta (§2.3)
│   │   ├── episode_01.review.json
│   │   ├── episode_01.storyboard.csv  # 导出的 CSV
│   │   ├── episode_01.storyboard.md   # 导出的 Markdown table
│   │   └── episode_01.comfy.json   # 导出的 Comfy workflow
│   └── exports/
│       └── season_01_master.zip    # 整季打包（剧本 + 分镜 + 角色 + 预览图）
└── logs/                           # 沿用 novel
```

---

## 3. 工作流（分步审查向导 v1）

### 3.1 整体（4 站向导）

```
[wizard 0] 类型 → drama → 空骨架 → 跳 /w/<name>/
              ↓
[wizard 1] 站 ① 核心设定
         · AI 出：赛道判断 + 主角一句话 + 反派一句话 + 情绪钩子
         · 用户：可改任意字段；锁定后 → 站 ②
              ↓
[wizard 2] 站 ② 钩子
         · AI 出：3 个钩子候选（情绪钩 / 悬念钩 / 反差钩 各 1）
         · 用户：选 1 个，可微调；锁定后 → 站 ③
              ↓
[wizard 3] 站 ③ 分镜
         · AI 出：60s × 6-9 镜分镜表（按创作规范 §四 黄金分割）
         · 用户：可改每行任意字段；增删镜头；标记高光镜号
         · 用户：可触发"重生本镜"局部重写
         · 锁定后 → 站 ④
              ↓
[wizard 4] 站 ④ 角色
         · AI 出：每个出场角色的 LoRA-ready prompt + 调外部 AI 绘画 API 出 2-3 张预览图
         · 用户：可改 prompt；可触发"重画"；选 1 张作为基准图
         · 用户：勾选 manual_override 后 agent 后续重生不覆盖
         · 锁定后 → 整集落盘
              ↓
[evaluate] drama_reviewer 5 维度自动评审
              ↓
[export] 用户从 /episode/<n> 页一键导出 JSON / Markdown / CSV / Comfy workflow
```

### 3.2 重生（continuation）

第 2 集起，wizard 4 站简化：

- 站 ① 核心设定：自动继承（用户可改"本集主线推进"）
- 站 ② 钩子：必出新钩（不重复）
- 站 ③ 分镜：AI 必须复用同一季角色的 visual_signature
- 站 ④ 角色：只显示"本集是否引入新角色"；不引入则跳过

### 3.3 evaluate 与重写

- 任一子分数 < 5 → 自动 Reject + 提示用户回到对应站（钩子分低回站 ②；分镜分低回站 ③）
- 任一子分数 5-7 → Abstain + advisor 给出改写建议，用户可选 "接受 advisor" 一键 apply
- 全 ≥ 7 → Approve，落盘 + 通知

### 3.4 mock-first 策略

iter 037-039 全部 mock 优先：
- mock 模式下 episode_writer 用 fixture 出预制的 5 个示范集（涵盖 5 个赛道）
- mock 模式下 AI 绘画 API 用 placeholder 图（带角色 ID 水印）
- 真模型接入留给 iter 040+ 用户验证产品形态后再做

---

## 4. 与 novel 模块的复用 / 改动 / 新增

### 4.1 完全复用（零改动）

| 模块 | 复用说明 |
|---|---|
| `src/llm_client.py` | drama agent 同样走 LiteLLM |
| `src/debater.py` | drama 6-agent 题材辩论沿用，仅换 agent 列表 |
| `src/reviewer.py` 多 agent 投票框架 | drama_reviewer 复用此框架 |
| `src/observability.py` / `cost_estimator.py` | 成本日志 + 缓存命中率统计 |
| `src/web/jobs.py` | drama 每站作为一个 job |
| `src/web/server.py` / `routes.py` 调度 | 不动 |
| `src/web/templates.py` `_BASE_TPL` + design tokens | 不动 |
| `src/web/static.py` design system + iter 026-035 保留标识符 | 不动 |
| `src/web/trash.py` | drama workspace 同样可软删除 / restore / purge |
| `src/web/_naming.py` | workspace 名规则不变 |

### 4.2 iter 036 已落（基础设施层）

参见 `docs/iterations/iteration_036_PLAN.md`：
- `src/web/workspace_meta.py`
- `src/cli_workspace.init_workspace(name, type=)`
- `/api/workspaces/overview` 加 type 字段
- wizard 第 0 步 type 选择 + `/api/wizard/drama-start`
- 书架 type badge
- `_sections_for(type)` 函数化
- drama overview 占位 + novel-only route guard

### 4.3 iter 037+ 新增（drama-only）

```
src/
├── drama_planner.py            # 站 ① 核心设定 agent
├── hook_designer.py            # 站 ② 钩子 agent
├── storyboard_builder.py       # 站 ③ 分镜 agent
├── character_designer.py       # 站 ④ 角色 agent
├── drama_reviewer.py           # 5 维度评审
├── ai_draw_client.py           # 通用 HTTP client（SD WebUI / Stability / 用户 endpoint+key）
├── comfy_workflow_exporter.py  # Comfy workflow .json 导出
└── web/
    ├── drama_view.py           # 聚合分集 + 角色 + 评审数据给 API
    ├── characters.py           # 角色表 GET / PUT API（manual_override 合并）
    └── storyboard_grid.py      # 分镜表 GET / PUT API

prompts/drama/
├── drama_planner.txt
├── hook_designer.txt
├── storyboard_builder.txt
├── character_designer.txt
├── drama_reviewer.txt
└── ai_draw_prompt_template.txt

config/
└── agents.yaml                 # 增加 drama_agents 段（与 novel_agents 并列）

docs/product/
└── short_drama_creation_standard.md  # iter 035 已落，drama agent system prompt 之源
```

---

## 5. WebUI IA 集成草图

### 5.1 Wizard step 0 type 选择

参见 iter 036 §A.4.3（已实现）。

### 5.2 Drama sidebar sections（按 iter 演进开放）

| iter | 开放的 section |
|---|---|
| iter 036（已） | overview / jobs |
| iter 037 | + write（4 站向导入口）/ characters |
| iter 038 | + episodes / storyboard |
| iter 039 | + reviews / insights / export |

### 5.3 关键页面 IA

```
/w/<drama-name>/                  # overview：当前进度 + 下一步建议 + 删除入口（iter 036 已）
/w/<drama-name>/write             # 4 站向导（iter 037）
  /write?step=setup
  /write?step=hook
  /write?step=storyboard
  /write?step=characters
/w/<drama-name>/episodes          # 分集列表（iter 038）
/w/<drama-name>/episode/<n>       # 单集详情（iter 038）
  tab 1 剧本（narrative 渲染）
  tab 2 分镜表（grid）
  tab 3 角色（本集出场）
  tab 4 评审（5 子分数 + advisor）
  tab 5 导出（JSON / MD / CSV / Comfy）
/w/<drama-name>/characters        # 角色库（iter 037-038 渐进）
/w/<drama-name>/reviews           # 评审聚合（iter 039）
/w/<drama-name>/insights          # 成本 / 时长达标率 / 钩子类型分布（iter 039）
/w/<drama-name>/jobs              # 任务历史（iter 036 已）
```

### 5.4 分镜表 grid 草图（iter 038）

```
┌───┬──────┬────────┬─────┬─────────────────────────┬──────┬─────────┬─────┐
│ # │ 景别 │ 运镜   │ 时长│ 画面内容                │ 旁白 │ 台词    │ ★  │
├───┼──────┼────────┼─────┼─────────────────────────┼──────┼─────────┼─────┤
│ 1 │ 特写 │ 静止   │ 3s  │ 林晚的手紧握订婚戒指…   │      │         │ ☐  │
│ 2 │ 近景 │ 缓推   │ 8s  │ 林晚抬头，看见周铭…     │      │         │ ☐  │
│...│ ...  │ ...    │ ... │ ...                     │ ...  │ ...     │ ... │
│ 6 │ 特写 │ 静止   │ 7s  │ 林晚嘴角微微上扬…       │      │ "对。"  │ ★  │
│ 7 │ 中近 │ 跟拍   │10s  │ 林晚走进卧室拉开抽屉…   │ 这一 │         │ ☐  │
│   │      │        │     │                         │ 次…  │         │     │
└───┴──────┴────────┴─────┴─────────────────────────┴──────┴─────────┴─────┘
   总时长: 58s / 60s (delta -2s)        [+ 行] [重生本镜] [一键导出]
```

- 单元格双击 → contenteditable
- 行可拖拽排序
- ★ 列只能勾 1 行（高光镜头唯一）
- 总时长 / 60s 实时计算 + 颜色提示

### 5.5 角色库草图（iter 037-038）

```
┌─────────────────────────────────────────────────┐
│  角色库（第 1 季）              [+ 新增] [保存] │
│  ─────────────────────────────────────────────  │
│                                                 │
│  ┌────────┐  林晚（c001）           ☑ 锁定     │
│  │ [图]   │  主角 / 重生女主                   │
│  │ [图]   │  齐肩短发 / 米白高领 / 平眉抿唇    │
│  │ [图]   │  visual_signature: 左耳银耳钉      │
│  └────────┘  [改 prompt] [重画] [导 LoRA-token] │
│                                                 │
│  ┌────────┐  周铭（c002）           ☐         │
│  │ [图]   │  反派 / 精致利己男友               │
│  │ [图]   │  ...                                │
│  └────────┘                                     │
└─────────────────────────────────────────────────┘
```

---

## 6. 关键决策点（已拍板）

iter 035 v0 列了 D1-D6 待用户拍板；本 v1 已收到答复，固定如下：

| # | 决策 | v1 落定 |
|---|---|---|
| **D1** | 剧本格式 | **JSON 三件套**（剧本 + 分镜 + 角色）—— Fountain 弃 |
| **D2** | 集时长 | **60s 默认，可选 30/60/90/120**（N2） |
| **D3** | 表格双向合并 | **manual_override 行只追加 advisor 建议，不覆盖**；其它字段随 agent 重生重写 |
| **D4** | drama / novel 隔离 | **完全隔离**（drama workspace 不引用 novel 数据） |
| **D5** | 导出格式 | **JSON（主）+ Markdown table + CSV + Comfy workflow .json**；.fdx / .pdf 不做 |
| **D6** | 语言 | **首版锁中文** |
| **N1** | AI 绘画 API | **通用 HTTP client（用户提供 endpoint + key）+ Comfy workflow .json 导出**；目前 (a) 静态图，后期 (b) AI 视频生成预留字段 |
| **N3** | 角色一致性 | **LoRA-ready 文字 prompt + 内置 AI 绘画预览图**；预览图调外部 API 出，落盘 `data/character_refs/` |
| **N4** | 用户干预方式 | **按钮触发 + 分步审查 4 站**（核心设定 → 钩子 → 分镜 → 角色），未来加对话式 |
| **N5** | season 概念 | **schema 预留 `season_no` 字段**；UI v1 仅显单季（"第 1 季"），用户做第二季时再加 UI |

---

## 7. iter 拆分（v1 重定）

| iter | 主题 | 内容 | 估时 |
|---|---|---|---|
| **036（已）** | 基础设施 | workspace.type / wizard type 分支 / 书架 badge / sidebar 函数化 / drama overview 占位 / novel-only route guard | 60-90min |
| **037** | 4 站向导骨架 + drama_planner | `/w/<name>/write` 4 站页面 + drama_planner.py + hook_designer.py + mock fixtures + 创作规范注入 system prompt | 大 |
| **038** | 分镜 + 角色 + AI 绘画 client | storyboard_builder.py + character_designer.py + ai_draw_client.py 通用 HTTP client + `/w/<name>/characters` grid + 分镜 grid 编辑器 + comfy_workflow_exporter.py | 大 |
| **039** | 评审 + 导出 + Insights | drama_reviewer.py + `/w/<name>/episode/<n>` 5-tab 详情 + 4 种导出 + drama Insights 子页 + season_no schema 持久化 | 中 |
| **040+** | 真模型 capstone + iter | 真模型 prompt 调优 + Fountain 转换器（如果用户后期需要）+ 多语言 + 跨剧 IP 复用 + 对话式 (N4 (c)) | 后续 |

---

## 8. 风险与开放问题

### 8.1 已识别风险

- **mock 输出不真实**：drama 比 novel 更"看产出质量"，mock fixture 必须精心设计（至少覆盖 5 个赛道 × 2 集 = 10 个示范）。**缓解**：iter 037 写 fixture 时，由 Claude 用创作规范严格自写，不是随便填字。
- **AI 绘画 API 切换碎片化**：用户 endpoint 千差万别（SD WebUI v1.x / v2 / ComfyUI / Stability / Replicate）。**缓解**：v1 通用 client 只走最简 REST + multipart，复杂 ComfyUI 走 workflow .json 导出而非直接调用。
- **角色一致性"假阳性"**：LoRA-ready prompt 写得再好，下游 LoRA 训练质量不可控。**缓解**：v1 只做 prompt + 预览图基准，**不承诺最终成片的一致性**；用户自己保证 LoRA 训练。
- **创作规范文档漂移**：`short_drama_creation_standard.md` 持续迭代；已生成的剧本可能依赖旧版规范。**缓解**：drama workspace 创建时**快照** `creation_standard.md` 到 `data/creation_standard.snapshot.md`，agent 用 snapshot 而非全局文件，**保证已生成内容可复现**。
- **N4 (c) 对话式与按钮式 UI 冲突**：未来对话式接入时按钮 UI 可能要重做。**缓解**：iter 037 设计 4 站时把"AI 出 → 用户改"动作抽象成一个对话泡，按钮 UI 是泡的折叠形态，未来展开成对话不破。

### 8.2 长期 backlog（iter 040+）

- 视频生成 / 分镜可视化（N1 (b)）
- TTS 配音 + 角色音色库
- 真模型多剧并行 / 团队协作
- 跨剧 IP 复用 / 题材模板市场
- 对话式 AI 助手（N4 (c)）
- Fountain / FDX 导出（如果用户需要专业摄制）

---

## 9. 文档版本与维护

- **v0** 2026-06-03 上午 · Fountain 假设，被用户工作流截图证伪
- **v1** 2026-06-03 下午 · 三件套 schema + 4 站向导 + N1-N5 拍板（**当前版本**）
- **v2 计划** iter 039 收官后 · 根据 iter 037-039 实测经验回填 prompt 模板、确认字段、修正 IA

本文档以 git commit message `docs(drama): bump short_drama_module.md to vN` 形式滚动维护。

每一次 v 升级必须列**变更摘要表**（v0 → v1 已示范，见文首）。

---

## 10. 与创作规范的关系

本文件（`short_drama_module.md`）= **产品定义**：schema / IA / 工作流 / iter 拆分。

`short_drama_creation_standard.md` = **创作铁律**：60s 节奏 / AI 友好硬约束 / 分镜规则 / 角色定型 / 雷区 / 赛道母题。

两个文件的关系：

```
short_drama_module.md       规定"系统怎么实现"
        ↓ 引用
short_drama_creation_standard.md  规定"创作内容怎么写"
        ↓ 注入
drama agent system prompt   agent 行为
        ↓ 产出
episode_NN.json / characters / reviews
```

任何一份文档动了，另一份必须同步检查。
