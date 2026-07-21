# 短剧 + 表格 模块 · 产品定义书

> **文档性质**：PM 产品定义书 + 短剧完整生产 SOP；前者保留 v1 决策背景，后者记录当前实现状态。
>
> **版本**：v17 状态补充 · 2026-07-21；v1 产品基线形成于 2026-06-03，当前实现基线为 iter 148，事实以 [`../AGENT_HANDOFF.md`](../AGENT_HANDOFF.md) 为准。
>
> **作者**：Claude
>
> **配套文档**：`docs/product/short_drama_creation_standard.md` v1（创作规范预设，给 LLM agent 作 system prompt 之源）
>
> **范围说明**：第 1-10 节保留 v1 产品决策与当时的施工拆分，不再充当实时进度表；第 11 节依据独立 [A-J 阶段计划](../iterations/stage_plan_drama_full_production_pipeline.md) 记录端到端 SOP、已实现边界与待完成项。本次只更新规划文档，不作为一轮 iteration。

---

## 变更摘要（v0 → v1）

| 维度 | v0 假设 | v1 真实需求（基于用户工作流截图 + N1-N3 决策） |
|---|---|---|
| 核心产出 | 单一 Fountain syntax 剧本 | **三件套**：叙事剧本 + 分镜表 + 角色设定表 |
| 辅助表 | 4 张（人物 / 场景 / 道具 / 时间线） | **1 张核心角色设定表**（分镜表本身已是结构化数据） |
| 集时长 | 60-180 秒可变 | **60 秒默认，用户可选 30 / 60 / 90 / 120**（N2） |
| 工作流 | 一键生成全部 | **分步审查向导 4 站**：核心设定 → 钩子 → 分镜 → 角色（N4） |
| 下游消费 | 真人摄制 / 编剧工具 | **AI 绘画 + 参考图 + 单视频生成入口**；真实媒体仍需逐次授权 |
| 角色一致性 | 表格字段维护 | **LoRA-ready 文字 prompt + 内置预览图**（调外部 AI 绘画 API）（N3） |
| 导出 | .fountain / .fdx / .pdf | **JSON / Markdown table / CSV / Comfy workflow .json** |
| 季概念 | 平铺集 | **schema 预留 season 字段，UI v1 仅显单季**（N5 = γ） |

### v1 → v2 状态补充

| 变化 | v2 记录方式 |
|---|---|
| “4 站向导”与当前“五站 job”口径不同 | 前四站仍是用户创作向导；把 review + Approve assembly 明确记为站⑤ |
| v1 到手工外部工具结束 | 追加 `RenderPlan → 资产 → 逐镜媒体 → TimelineManifest → 合成/QA → 工作台/归档 → provider 校准` 的完整生产 SOP |
| 旧文把角色预览图与资产选择写在同一站 | 区分“站④角色卡/季角色库”与“阶段 B-C 不可变资产版本/逐镜图片”；角色/ArtDirection/Scene/Prop-Clue 版本及 C1-C3 逐镜图片本地契约已部分完成，真实 provider 与质量工作流仍未完成 |
| 旧文缺少实时落地状态 | 每个阶段明确标注 ✅ 已实现、🟨 部分实现、⏳ 待实现或 🔒 待逐次授权验证 |

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
- **v1** 2026-06-03 下午 · 三件套 schema + 4 站创作向导 + N1-N5 拍板
- **v2** 2026-07-15 · 保留 v1 产品决策，追加“五站创作 + A-J 媒体生产”的完整实时 SOP
- **v3** 2026-07-18 · 同步 A-F1 已实现基线，并登记 F2 ASS/通用可编辑工程与安全 completion marker
- **v4** 2026-07-18 · 登记 A2 visual-only override、双 CAS 选择、effective manifest 与 stale dependency matrix
- **v5** 2026-07-18 · 登记 F3 Web 本地合成、持久 E3 时间线、QA 真值与 exact 交付边界
- **v6** 2026-07-18 · 登记 G1 最小持久 task DAG、active dedupe、guarded transition 与取消级联
- **v7** 2026-07-18 · 登记 G2 worker lease、heartbeat/takeover 与跨集 capacity lane
- **v8** 2026-07-18 · 登记 G3 静态 backend capability registry 与 attempt-frozen binding
- **v9** 2026-07-18 · 登记 G4 ledger v3、原子 frozen binding 与纯本地 queue client
- **v10** 2026-07-18 · 登记 G5 owner-guarded provider execution loop
- **v11** 2026-07-18 · 登记 G6 strict pricing facts 与分币种 Insights
- **v12** 2026-07-18 · 登记 G7 durable lifecycle metrics 与成功率/等待时间 Insights
- **v13** 2026-07-18 · 登记 H1 typed source event graph、来源与 spoiler boundary
- **v14** 2026-07-21 · 登记 H2 production entity/summary adapter 与 RenderPlan exact graph binding
- **v15** 2026-07-21 · 登记 H3 text-free context memory cache、current binding 与失效协议
- **v16** 2026-07-21 · 登记 I1 同源只读 production workbench、安全聚合投影与列表/画布 Web（**当前版本**）

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

---

## 11. 完整生产 SOP（实时状态）

本节回答两件事：短剧从创建 workspace 到交付成片应该怎样流转；截至 iter 147，哪些步骤已经具备工程闭环，哪些仍只是规划。它不改变第 1-10 节的历史产品决策，也不把独立阶段计划算作一次 iteration。

状态图例：

- ✅ **已实现**：当前 mock/canonical 工程链已有明确代码与测试证据。
- 🟨 **部分实现**：阶段目标只完成了一个可验收子闭环，不能宣称整阶段完成。
- ⏳ **待实现**：可能已有可复用底座，但该阶段定义的完整产物与验收门槛尚未闭环。
- 🔒 **待逐次授权验证**：工程入口或 preflight 已存在，真实 provider 请求仍必须逐类、逐次获得用户授权。

### 11.1 真源、派生关系与全程守门

短剧链固定分成三层事实，不能互相顶替：

| 事实层 | 真源 | 约束 |
|---|---|---|
| 创作事实 | Approve 后的 `episode_NN.json`、meta 与冻结角色投影 | 剧情、对白、人物和镜头创作语义只能回到五站创作链修改 |
| 渲染事实 | `RenderPlan`、资产版本与选择、逐镜媒体、`TimelineManifest`、QA | 都是可失效、可重建的派生物；不得为了换图、配音或剪辑去改 episode SHA |
| 执行/付费事实 | task state、provider/account/endpoint/model/input/auth fingerprint、receipt、ledger、artifact SHA | 通用任务状态不能替代付费证据；unknown submission 禁止自动重发 |

```text
drama workspace
  → 五站创作与人工修订
  → Approve canonical episode_NN.json
  → RenderPlan
  → 资产版本 / 逐镜图片 / 逐镜视频 / 音频 manifests
  → 唯一 TimelineManifest
  → 本地 MP4 + 字幕 + 可编辑导出 + QA
  → 生产工作台 / 可移植归档
  → 分媒体真实 provider 校准
```

全程共同守门：默认 `OPENAI_MODEL=mock` 严格离线；workspace、episode、路径、有限数、预算与授权在调用/落盘前校验；真文本、真图片、真语音、真视频的授权彼此独立，不从旧 job 或历史成功状态继承。

### 11.2 创作、评审与创作层交付

| 阶段 | 输入 | 主要动作 | 产物 | 进入下一步的门槛 | 当前状态 |
|---|---|---|---|---|---|
| 0. 建立 workspace | 类型 `drama`、项目名、计划集数、目标时长 | 创建隔离 workspace 与短剧向导骨架；加载本项目的创作规范 | drama workspace、wizard input、规范快照/版本信息 | workspace 类型、路径和数值合法；不得混用 novel 数据 | ✅ 已实现；当前 canonical/mock 证据以 60 秒为主，30/90/120 秒待专项验证 |
| 1. 站①核心设定 | 赛道/题材/人物意图、规范 | 生成或继承本集主线、主角/反派核心设定；用户可编辑 | setup/core setup | 核心人物和本集主线完整；episode 身份一致 | ✅ `drama-plan` 已实现 |
| 2. 站②钩子 | 已完成 setup、赛道母题 | 生成情绪/悬念/反差候选；用户选择、微调并锁定 | selected hook + 候选记录 | 必须有明确 hook 类型和内容；后续不得静默沿用旧集钩子 | ✅ `drama-hooks` 已实现 |
| 3. 站③叙事与分镜 | setup、selected hook、时长、规范、季角色投影 | 生成起承转合与镜头 grid；支持编辑、排序、增删和单镜重生 | narrative + storyboard + AI draw/motion 字段 | 6-9 镜、字段范围、连续 shot_no 和最多一个高光由本地硬校验；时长/首末镜/对白等软规则显式告警；场景/人物数主要由 prompt 与创作规范约束 | ✅ `drama-storyboard` 已实现；已接受证据以 60 秒 fixture 为主 |
| 4. 站④角色与季角色库 | setup、storyboard、已有季角色表 | 生成 LoRA-ready 角色卡；合并季角色库；保护 manual override；登记本集 appearances（最多 8 人） | season character sheet + episode-scoped candidate projection + 引用图记录 | 角色 ID、episode 身份与每集 8 人上限合法；手工锁定字段不能被 agent 覆盖 | ✅ `drama-characters` 已实现；不可变资产版本另属阶段 B |
| 5. 站⑤评审、修订与组装 | 前四站产物、本集角色投影、规范 | 五维评审；Reject 回对应站，Abstain 提供 advisor 并由用户决定；revision 后重评；仅 Approve 执行 assembly 并冻结本集角色 IDs | review、meta（含 frozen cast）、canonical `episode_NN.json` | verdict=Approve、输入 fingerprint/episode SHA/角色投影一致；坏 JSON 或血统不明 fail-closed | ✅ `drama-review-assemble` 已实现 |
| 6. 连续多集 | 最新连续、完整、fresh 的 N 集，`episode_count`，季角色库 | 初始化 N+1；继承系列级设定但要求新钩子；复用既有视觉签名，只生成/补充新角色 | 下一集五站输入与最终 canonical episode | 只允许最新连续 N→N+1；跳集、断档、stale、孤儿和超过计划上限均阻断 | ✅ season 1 内 mock 工程闭环，计划上限 100 集；多季模型未完成 |
| 7. 创作层交付与洞察 | fresh/Approve episode 或完整季 | 单集导出 JSON/MD/CSV/Comfy；生成严格 master/snapshot 季包；汇总受控 Insights | 单集四导出、季包/快照、成本/时长/钩子洞察 | 导出只从 canonical episode 重建；master 要计划内全部集连续完整 fresh；snapshot 至少一集完整 fresh | ✅ 已实现；Comfy 只是 workflow 文件，真 ComfyUI 未验证 |

创作规范的节奏、镜头、AI 友好约束、角色定型与 reviewer 分数阈值继续以 [`short_drama_creation_standard.md`](short_drama_creation_standard.md) 为准。这里记录流程和状态，不复制全部内容规则。

### 11.3 媒体生产 A-J

| 阶段 | 输入 | 主要动作与产物 | 验收门槛 | 当前状态与精确边界 |
|---|---|---|---|---|
| A. 渲染契约与 stale | fresh/Approve canonical episode、冻结角色投影 | 确定性生成 strict `RenderPlan`；稳定 shot ID、有序 spoken segments、fingerprint、五态 inspect；visual-only override 与依赖传播 | 相同输入字节稳定；创作变化 stale；旧 workspace 明示 `needs_render_plan`；override 不能改剧情/对白/角色；零网络 | ✅ **A1+A2 纯本地闭环已完成**：RenderPlan 外新增 camera movement、lighting、negative prompt、剪辑 transition 四类 shot-scoped override，不可变候选、derived-from、revision/current-ID 双 CAS、effective manifest 和 atomic catalog+manifest state；未选候选不改变下游 fingerprint，selected old/new spec 的字段增加、修改与清空按 v1 矩阵取依赖并集。角色/ArtDirection/场景/道具引用仍由 B 的独立 manifest 冻结 |
| B. 视觉资产圣经 | RenderPlan、现有季角色库 | 建立角色/场景/道具/线索/美术方向；每次生成或编辑产生不可变 version；显式 selected/derived-from/used-by | 旧角色无损迁移；新候选不自动替换 selected；被引用版本不可静默删除；路径/URL 安全 | 🟨 **B1-B3 本地治理与 Web 闭环已完成**：四类不可变版本、显式 selected/CAS、跨集 exact-version used-by、active/disabled ledger、ArtDirection Episode > Series > Global 与 strict allowlist 资产治理页已实现；停用不删除历史，mutation 服务端重算 impact。物理 GC 未实现 |
| C. 逐镜图片与首尾帧 | A-B、镜头视觉字段、selected references、provider capability | 构建每镜 image spec；生成/校验候选；显式选择首帧与可选尾帧；绑定跨镜 lineage；输出覆盖率 | 每个 required shot 有明确 selection；引用超限确定性裁剪并告警；单镜重生只 stale 依赖项；付费 crash matrix 不退化 | 🟨 **C1-C4 本地契约与候选 Web 已实现**：C1 冻结 request/exact refs，C2 提供 content-addressed strict PNG 候选、guarded first/tail/previous-tail 与 coverage/repair，C3 提供 provider-neutral capability、once-only attempt、durable receipt，C4 提供 exact PNG 安全预览、两图比较和 guarded first/tail selection。真实 provider/network、多参考上传、JPEG/WebP、显式 staging GC 和 power-loss 证明未实现 |
| D. 逐镜视频与连续性 | C 的 selected first/tail、references、镜头时长、provider capability | 每镜 I2V/R2V submit→durable receipt/id→poll→download/validate；候选选择与确定性连续性检查 | unknown submission 不重提；download 可重试但不 resubmit；任一 required shot stale/failed 时 production compose blocked | 🟨 **D1-D5 本地闭环已完成**：冻结输入、候选/coverage、once-only attempt、artifact 重验、首尾帧 lineage 与 production compose gate，并提供 strict/bounded 候选播放、选择、attempt/continuity/compose readiness Web；真实 provider/network、Web submit/poll/cancel 和 episode 2+ 成片仍未闭环 |
| E. 配音、旁白、字幕与唯一时间线 | RenderPlan spoken segments、voice profiles、selected video、BGM/SFX policy | 每句独立 TTS attempt；合成 POST 与下载 GET 分账；probe 实际时长；构建 `TimelineManifest` 和 subtitle cues | overlap、越界、非有限数、台词超镜头、坏字幕 fail-closed；下载失败不重新合成；无 BGM 按 policy warning/blocked | ✅ **E1-E3 纯本地闭环已完成**：VoiceProfile、AudioManifest、once-only TTS recovery、strict TimelineManifest、optional BGM/SFX 与同源 SRT；真实 TTS/BGM/SFX 和主观音频质量未验证 |
| F. 合成、媒体 QA 与可编辑导出 | C-D selected media、E 的唯一时间线 | 纯函数生成 ffprobe/ffmpeg argv 与 filter graph；标准化、混音、字幕、水印、mux；post-probe QA；导出 SRT/ASS/编辑器工程 | required shots 全覆盖；MP4/字幕/export 共享 timeline fingerprint；路径/命令注入被拒；缺 clip/FFmpeg/concat 失败不得 completed | 🟨 **F1-F3 本地与 Web 闭环已完成**：F1 生成固定 1080×1920/25fps H.264/AAC MP4、SRT 与 QA；F2 从同一 timeline 导出 UTF-8 ASS 和版本锁定的通用可编辑工程；F3 将 E3 成功结果持久化为 Web 唯一输入，提供本地 compose job、durable QA truth 与 exact MP4/SRT/ASS/edit 下载。FFmpeg 单线程、跨 workspace 单槽、总源集 128 MiB、生成/验证/交付单一 64 MiB 上限；current D4/E3、F1/F2 与返回字节在同一锁快照验证，真实本地 episode 2 已覆盖。特定 NLE 私有格式、多 profile、更广 codec/container 与真实媒体质量仍未闭环 |
| G. 通用媒体调度、能力与成本 | C-F 已出现的稳定重复任务 | 提取最小 task DAG、dedupe、guarded transitions、cancel cascade、worker lease、provider×media lanes、capability registry、pricing/Insights | 多进程不重复 claim；unknown submission 零自动重发；迁移前后 artifact/receipt/fingerprint 不变；estimate/actual/unknown 分列 | 🟨 **G1-G7 持久调度、pricing 与 lifecycle metrics 已实现**：episode-scoped strict DAG、worker lease/capacity lane、代码内 registry、provider task+frozen binding 原子入队、纯本地 queue client、owner-guarded execution loop、六类 append-only pricing facts，以及 durable ready/first-claim/terminal lifecycle 与 success/queue/run Insights 已落地。generic task/pricing 只绑定受控 evidence fingerprint，不保存 provider task/response 或替代 paid ledger/billing。真实 adapter/账单对接尚未实现 |
| H. 小说事件图与辅助记忆 | synthetic 或允许范围内的章节结构、现有 entity/summary 投影 | typed event graph build/merge/split；记录 source/spoiler；episode 引用 event IDs；上下文 cache 绑定 hash 并可失效 | 超来源/剧透边界 fail-closed；unknown 因果不猜；invented 与 source-derived 明示；无 embedding 时零网络降级 | ✅ **H1-H3 纯本地闭环已实现**：H1 提供 strict typed graph 与来源/改编/因果/lineage；H2 从 named workspace exact entity/rolling-summary bytes 重建 production graph 并冻结 RenderPlan binding；H3 只缓存 exact event/source identity，以 hashed keyword + recent + summary 零网络查询，绑定 workspace/season/episode/source/graph/RenderPlan/policy，current 漂移 stale/blocked，cache missing/delete 不影响 canonical。公开 Web/UI 与真实提取仍由 I/J 承接 |
| I. 生产工作台与项目归档 | B-G 的 render/task/timeline/QA 事实 | 后端聚合安全投影；列表/画布同源；统一操作资产/镜头/任务/时间线/QA/预算；archive export/import | UI 不是新真源；mutation 有锁和 revision guard；归档 round-trip 保持 hash/selection/timeline/MP4；拒绝路径穿越/坏 hash/未知 schema | ✅ **I1+I2 纯本地闭环已实现**：I1 drama-only Web 从 current inspectors 聚合 creative/RenderPlan、selected assets、逐镜 image/video、task DAG、timeline/QA/delivery，列表与画布共享 source projection fingerprint。I2 提供确定性、有上限的 ZIP export/preflight/import CLI，只创建新 drama workspace，并交叉核验 creative/selection/render identity/timeline 源媒体/QA/MP4。默认不带 RenderPlan 完整 prompt、review/provider raw、signed URL、credential/account fingerprint 或 paid authorization；画布 mutation/操作按钮仍不在本地闭环内 |
| J. 真 provider 校准与 capstone | 对应链已通过 mock/local E2E、本次明确授权 | 真文本、真图片、真语音、真视频四轨分别执行 preflight→单资产→单镜→受限单集→多集；记录费用、恢复与人工质量 | 每次写清 provider/model/account fingerprint、提交上限、预算、timeout、可重试类型、对账与终止条件；API 成功不自动等于作品质量通过 | ⏳ 🔒 现有五站文本、全角色图片、episode 1 单视频入口可分别申请授权校准；完整单镜/单集/多集 capstone 仍依赖 B-F。当前为 `mock-functional` + fake-provider `local-e2e`、`provider_validated=false` |

#### A2 stale dependency matrix v1

矩阵输出是 strict、content-addressed 的内部控制事实；`change → scope → affected_nodes` 由 schema 精确校验，不能由调用方提交任意节点列表。视觉候选只追加不 stale；只有 selected old/new spec 的实际字段差异触发传播，字段被清空也计为变化，多字段切换取依赖并集。

| 变化 | scope | 必须 stale | 明确不 stale |
|---|---|---|---|
| creative revision | episode | RenderPlan、逐镜图片/视频 request+candidate、audio plan、timeline、composite、edit export、media QA | 无 |
| camera movement / lighting / negative prompt override | shot | 该镜 image request+candidate、video plan+candidate；整集 timeline、composite、edit export、media QA | RenderPlan、audio plan、其它镜独立候选 |
| 剪辑 transition override | shot | timeline、composite、edit export、media QA | RenderPlan、逐镜图片/视频 provider 资产、audio plan |
| BGM selection | episode | timeline、composite、edit export、media QA | RenderPlan、逐镜图片/视频、spoken audio plan |
| selected first frame | shot | 该镜 video plan+candidate；整集 timeline、composite、edit export、media QA | RenderPlan、image candidate 本体、audio plan |

这里的 `transition` 是 timeline/F 层剪辑转场，不写入图片或视频 provider request；若未来新增 provider 生成侧的 motion transition，应另立字段和矩阵版本，不能静默扩大 v1 含义。A2 state 以一次严格读取所得的 bytes token 做目标 CAS，RenderPlan token 在 replace 前后重验；该原子性仍以所有项目写者遵守 workspace flock 为前提，不宣称抵抗不合作本机进程在最后一条指令间的抢占。

每次真实 selection mutation 与一条 content-addressed transition receipt 原子提交；receipt 保存 before/after effective manifest，schema 强制只有目标 shot 从 old version 变到 new version、其它 shot 不变，且两个快照的每个版本都精确存在于 append-only catalog。未确认 receipt 最多保留 512 条，满额时 fail closed，调用方可显式 acknowledge；旧请求重试只读恢复、不再次写盘。结果状态 `target_current` 仅表示该 receipt 的目标版本当前仍被选择，`superseded` 表示当前目标不同，`no_op` 表示本次没有 mutation；它不把 ABA 历史误称为“从未被覆盖”。

#### B1 跨集 Used-By 与停用治理

跨集反向索引以 season 为作用域，从角色、ArtDirection、场景、道具/线索四类 catalog 和各集 frozen RenderPlan/manifest 重新投影。索引保存 exact semantic ID、immutable version ID、episode/shot 引用和受控 source SHA；未被任何集使用的候选版本仍显式存在，`references=[]`。文件名、内嵌 episode identity、catalog fingerprint 与 version fingerprint 必须一致；任一 source 缺失、损坏、超限、特殊文件、目录 symlink 或扫描竞态都会形成有界 blocker，不能降格为零引用。

生命周期 ledger 只有 `active` 与 `disabled`，mutation 使用 state revision + current status 双 CAS，并把停用决定绑定到当次 usage index fingerprint。`disabled` 不删除版本、artifact 或历史 manifest，也不把已有 selected/no-op 读取改写为失败；但它会阻止该 exact version 被重新选择，以及被新的或替换后的 RenderPlan/character/scene/prop-clue manifest 再次冻结。显式恢复 `active` 产生新 revision 后才可重新选择或物化。当前不提供物理删除/GC；未来即使增加 GC，也必须另立可证明的引用闭包和迁移协议，不能把 `references=[]` 直接解释为可删除。

#### B2 ArtDirection 多 Scope 解析与冻结

ArtDirection 解析固定为 workspace 内 `Episode > Series > Global`。Series 沿用 season catalog；Global 是该 workspace 的默认方向，不是跨 workspace registry；Episode 是带 season/episode identity 的显式覆盖。缺失的高层可向下 fallback，schema-invalid、orphan、特殊文件或读取竞态必须 fail closed。scoped catalog 的 `enabled=false` 表示用户显式 clear，可审计地 fallback；它不同于 B1 lifecycle `disabled`：后者继续允许历史 selected/no-op 与既有 RenderPlan 读取，但禁止新建、替换、重新选择或重新启用时冻结该 exact version。

resolver 在一次解析前后复查 Episode、Series、Global 三个源的 content token，包括 missing token，避免高优先级覆盖在层间读取时出现却仍把旧低优先级 RenderPlan 判 fresh。解析结果写入 RenderPlan，显式冻结 source scope、exact ref、selection revision，以及 scoped Global/Episode 的 activation revision；selection fingerprint 与 resolution fingerprint 均由 schema 重新派生校验。追加未选候选不 stale；选择切换、select-away/back、clear/re-enable 和 scope 优先级变化会因 revision 或 ref 变化精确 stale。没有 resolution 的旧 season-only RenderPlan 仍可严格读取，但 inspect 会要求显式 rebuild 完成迁移。

scoped mutation 与既有 catalog 相同，使用 workspace lock、目标 bytes token、revision/current-ID CAS、nofollow 原子替换和 precommit 重验。Episode retirement guard 强绑定 catalog season；Global create/select/re-enable 必须检查 workspace 中全部已知 canonical season ledger，调用方不能借另一 season 的空 ledger 绕过停用。Global 与 Episode catalog 的全部 immutable versions 也进入 B1 exact-version inventory；同 identity 不同 fingerprint 会形成 blocker。

#### B3 资产管理 Web 总览与治理

drama-only 资产页 `/w/<name>/assets` 从领域事实重建 character、ArtDirection Series/Global/Episode、scene、prop/clue 六个分区。公开投影只允许 semantic/version ID、selected、当前 season lifecycle、跨 season selection eligibility、exact-version Used-By、scope-specific stale impact、revision 与有界 blocker；缺失可选 catalog 显示空状态，坏源、身份错位、特殊文件与扫描竞态 fail closed。

选择、active/disabled、ArtDirection clear/re-enable 都在 workspace reservation/lock 中由服务端重建当前 overview，再使用 revision/current identity/target token CAS 调用既有领域 writer；Global impact 与可选择性扫描全部 canonical season。mutation 具 JSON、显式 intent、same-origin/Fetch Metadata 与双层 32 KiB 上限。B3 不提供媒体上传/删除或物理 GC，也不混淆 B1 lifecycle disabled 与 B2 scope clear。

#### C4 逐镜图片候选 Web 比较与选择

drama-only `/w/<name>/shot-images` 只投影 C2 已登记的 stable shot、request freshness、candidate ID/fingerprint、首帧/尾帧/previous-tail binding、coverage 与有界原因。候选图通过包含 workspace/episode/shot/candidate exact identity 的同源路由读取；每次响应前重新校验 strict manifest、canonical artifact path、PNG 结构、尺寸、size 与 SHA，不接受客户端路径或任意 URL。Web 预览是经认证 artifact 的安全派生物：剥离 text/EXIF/未知 ancillary metadata，只有符合颜色类型、长度、顺序和唯一性约束的合法 `tRNS` 可保留，避免 prompt/provider/path/签名 URL 泄露，同时不破坏透明像素语义。

两图比较只在浏览器消费上述安全 URL；首帧/尾帧选择和清除尾帧由服务端按当前 manifest 找到 exact candidate，再复用 C2 manifest fingerprint、selection revision 与 current binding CAS。新候选不会自动变更 selection，exact lost-response replay 不二次写盘，409 后页面刷新权威状态。C4 不生成图片、不调用 provider，也不扩大 C3 的真实执行声明。

#### D5 逐镜视频候选 Web 与连续性门禁

drama-only `/w/<name>/shot-videos` 从 D1-D4 重建 stable shot、当前 request、候选/selection、latest attempt 安全状态类、coverage、deterministic continuity warning 与 compose readiness。公开 attempt 只含本地 attempt ID、受控状态和 outcome，不返回 backend/account/provider task/result、prompt hash、staging/artifact path、签名 URL 或错误正文；页面 GET、播放和选择不得触发 submit、poll、download、cancel 或任何付费调用。

候选播放 URL 绑定 exact workspace/episode/shot/candidate identity；每次 HEAD/GET/单一 byte Range 前重验 strict manifest、canonical MP4 bytes、size/SHA/container/时长/尺寸/音轨。浏览器不接收原始 provider MP4，而是消费本地 decode/re-encode、去音轨/字幕/章节/metadata、最长 30 秒、最大 360 宽/12fps/512kbps 的派生预览；输出还要通过 4 MiB 上限、MP4 box allowlist 和结构复核。源候选 Web 预览上限 32 MiB、恰好一个合法视频轨、长边 1920/短边 1080（横竖屏均可）与 36,000 个视频 sample，每镜最多投影 8 个候选、整页最多 64 个 preview identity 并优先保留 selected；浏览器只在用户显式点击后绑定媒体 URL，服务端从 manifest inspection 前开始限制最多 2 个并发预览，FFmpeg decoder/filter/encoder 均为单线程，LRU 4 项。超限候选仍显示身份且允许清除 selection，但标记 `web_unverified`、不加载预览且不宣称 compose ready。不能把“D2 内容哈希有效”直接等同于“媒体可安全公开”。候选选择复用 D2 manifest fingerprint、selection revision/current selection CAS，允许 exact lost-response replay；旧 request/retired 候选只读，placeholder 只形成 `degraded_preview`，任何 hard blocker 都不得显示为 production compose ready。

#### F3 Web 本地合成、QA 与 exact 交付

E3 production gate 成功后，在同一 workspace lock 内以 pinned dirfd/no-follow 原子提交 episode-scoped TimelineManifest；浏览器不能上传任意时间线。字幕修订只能按 current timeline fingerprint 与 cue ID 做 CAS，修订后的同一 TimelineManifest 继续驱动 SRT、ASS 和 editable project。`/w/<name>/compose` 从 current D4、持久 E3、F1 QA 与 F2 completion marker 重建 `needs_timeline/ready/partial/stale/invalid/complete`，job history 或进程内 future 永远不是完成真源；服务重启后只要 exact 产物仍通过重验，页面仍显示 complete。

compose job 在 FFmpeg 与 F2 各自锁域开始前重新验证 current D4/E3/source，并在最终返回 `committed=true` 前再复核；FFmpeg 使用 argv-only、单线程、128 MiB 总源集、64 MiB 单一生成/验证/交付硬上限与跨 workspace 单槽，取消/期限在最长 250 ms 的子进程轮询点 kill/wait 并清理 staging/temp。执行失败是 `failed`，缺 timeline/stale/capacity 等前置条件是带安全 blocker 的 `blocked`；页面按 exact episode 关联 job，不能跨集轮询或取消。

MP4/SRT/ASS/edit 下载 URL 绑定 episode 与完整 timeline fingerprint。current D4/E3、F1 probe/QA、F2 completion/source identity 和本次返回字节必须在同一 workspace lock 快照内成立；Web MP4 上限 64 MiB，HTTP compose GET/HEAD/Range 整体单槽，响应仅使用固定文件名和 allowlist headers。HEAD/单 Range 不改变 exact authorization；坏 fingerprint、partial set、symlink、namespace/source 替换或 hash 不符均 fail closed。F3 不调用文本、图片、视频、TTS 或 ASR provider。

#### G1 最小持久媒体任务 DAG

G1 只抽取 C-F 已稳定重复的编排字段：episode、media/stage、subject、immutable input/provider identity fingerprints、依赖、dedupe、attempt、状态、revision、时间和有界结果码。任务按 episode 写入 strict content-addressed ledger；同一 dedupe/input 的 active task exact replay，终态后只有连续的新 attempt 才能创建。依赖必须引用同 ledger 的既有任务，环、自依赖、跨 episode 引用、坏 hash/额外字段、symlink 和 CAS 竞态 fail closed；依赖全部 succeeded 时，planned dependent 在同一原子提交中晋升 ready。

状态转换采用显式 allowlist；`submission_unknown` 在 G1 无出边并持续占用 active dedupe，generic task 不能据此重发 provider 请求，未来只能由绑定 paid evidence 的专用 reconciliation 扩展。新任务拒绝依赖 failed/cancelled/cancelling/unknown task，但既有 task 的 lost-response exact replay 仍成立；依赖失败沿 planned descendants 确定性传播为 `dependency_failed`。取消从目标沿 DAG 传播到 active dependents 并进入 `cancelling`，只有外部确定取消后才能写 `cancelled`；unknown submission 保持 unknown。公开投影不含 backend/account/endpoint/model fingerprints、provider task/result、prompt、path、response 或签名 URL。G1 不接 worker/backend/provider，也不读取、迁移或替代图片、视频、TTS 的 paid ledger/receipt。

#### G2 Worker lease 与容量 lane

G2 将 lease、task 与认证 replay receipt 放在同一 episode ledger 原子提交。旧 G1 v1 ledger 仅在不存在 `claimed/submitting/submitted/polling/downloading/validating` 时确定性逻辑升级，task ID、dedupe、input/provider identity 不变；iter136 起逻辑升级目标为 v3，下一次 mutation 也写 v3。缺少 owner/token 证据的 v1 在途态必须 safe-block 到显式 reconciliation，不能合成所有权。`claimed` 只能由 worker API 创建，后续执行态 transition 同样必须匹配 current worker/token、task/lease revision、ledger identity 和未过期 lease；release 与 worker transition 的 lost-response replay 由同 ledger 内容寻址 receipt 认证，不能由非 owner 冒认。

所有 worker mutation 都在 workspace lock 内读取一次可信 wall clock；调用方不能伪造未来时间提前释放容量、续租或 takeover。claim 以 bounded no-follow 扫描覆盖全部 episode ledger 的未过期 lease；相同 provider identity×media kind 共享 capacity，active lane policy 不一致 loud fail，避免 episode 分片超卖。未过期 lease 不可接管，过期 lease 只能用新 token 在同一提交中替换 owner 并增加 task/lease revision；不读 PID 或猜进程是否存活，任何返回 lease 的 exact replay 也必须在可信时钟下仍有效。lease 随 succeeded/failed/cancelled/submission_unknown 或 cancel cascade 清除；unknown 仍不可 claim/重提。公开 worker 投影只含 episode/task/media/stage/state/revision/heartbeat/expiry 与 active/expired，不含 owner、token、lane、provider/account/path/prompt 或 paid evidence。G2 尚无执行 loop/backend/provider/queue/Web mutation，因此不能把 worker ownership 表述为真实媒体执行已接通。

#### G3 静态 backend capability registry 与冻结 binding

G3 registry 是由受审查代码显式传入声明后构建的 deep-frozen、content-addressed snapshot，不读取 `.env`、endpoint、credential 或用户模块名，也没有 dynamic import、entry point、任意 callable、热加载或网络副作用。唯一 lookup key 是 canonical `(provider_id, media_kind, model_id)`；provider/model ID 与 fingerprint 在 registry 内双向唯一，重复 key、同 backend 跨 provider/media 的歧义 ownership、不同 model ID 复用 fingerprint、未知组合、大小写/`.`/`..` 路径歧义与 backend/task identity drift 均 loud fail。同一 backend 可为同一 provider/media 声明多个 model，但每项 capability 与 registration 独立内容寻址。

现有 C3 image、D3 video 与 E2 TTS capability 在 API 边界重新验证后只做纯转换：G3 descriptor 保存原 `source_capability_fingerprint` 及公共执行约束，不修改或替代原 attempt、authorization、artifact、submission/terminal receipt；TTS 明确保留“同步 synthesis POST 后独立 download，可只重下不重合成”。首次 task binding 只允许在 `planned/ready/claimed`，同时校验 task backend/media/provider/model fingerprints；binding 内冻结完整 registration/capability snapshot 与原 registry fingerprint。`submitting` 及之后的 task 没有原 binding 必须 safe-block，携带原 binding 时即使当前 registry 已更新也继续使用原 snapshot，不能重解释或据此自动重提。公开 registry projection 只展示 backend/media 和有界能力，不含 provider/model、任何 fingerprint、endpoint/account/prompt/path/response/paid evidence。G3 仍无 adapter callable、queue、provider execution、Web mutation 或 pricing，因此不能表述为真实媒体 backend 已接通。

#### G4 持久 binding 与纯本地 queue client

G4 把 G3 `DramaMediaBackendBinding` 作为 image/video/audio provider task 的持久事实写入 episode ledger v3。新 provider task 必须在同一 workspace lock、同一次 ledger CAS 和同一个原子替换中同时写入 task 与完整 frozen binding；不存在“先建 task、稍后补 binding”的可观察中间态，无 binding 的通用 create 入口只接受本地 compose/export。v1/v2 账本读取后逻辑迁移到 v3，但不会使用当前 registry 猜测历史 binding：未绑定 provider task 显式投影为 `legacy_unbound`，ready 也不可 claim，在途任务继续 safe-block 到人工 reconciliation；compose/export 投影为 `not_applicable` 并保留 G2 lease/receipt 语义。每次 transition、claim、heartbeat、release、takeover、cancel 都原样保留已有 binding；终态和取消不会删除审计快照。

同 task 的 lost-response replay 只接受持久 binding 内的 provider/model/backend identity；即使进程重启或当前 registry 的 capability snapshot 已更新，也返回原 binding，不重新解析和换绑。`claimed` 及执行态必须存在与 task immutable identity 精确一致的 binding；账本 schema 同时校验 task ID、input、media、backend、provider/model fingerprint、排序和唯一性。generic ledger 仍不存 provider task ID、response、签名 URL、credential、prompt 或 paid receipt。

纯本地 queue client 只提供原子 enqueue、安全 get、最长 300 秒的 monotonic bounded wait，以及 current-CAS cancel。公开结果只含 task 编排字段和 `frozen`、`legacy_unbound`、`not_applicable` 三态；第三态只用于本地 compose/export。投影不暴露 provider/model/account/endpoint/binding fingerprint；wait 有最小轮询间隔且超时不改变持久状态。G4 不含 adapter、provider submit/poll/download、执行 loop、Web mutation、动态加载、pricing 或自动重试，因此不能把“可排队”表述为“真实媒体已执行”。

#### G5 Owner-Guarded Provider Execution Loop

G5 新增的 generic executor 只驱动 task state 与 worker lease，不成为第四套 paid ledger。provider 动作必须通过受审查代码显式注入的 `DramaMediaPaidEvidenceBridge`；不支持配置字符串、entry point、dynamic import 或用户代码热加载。bridge identity 必须逐项匹配 persisted binding 与 task 的 backend/provider/model/account/endpoint/source capability fingerprint，bridge ID 也必须等于 frozen backend ID。每条 observation 只含受控 phase/outcome 与 paid/artifact evidence fingerprint，并内容寻址绑定 exact task revision、binding、current worker/token 和 lease revision；不能把另一个 task、旧 owner 或 takeover 前的 paid evidence 投影到当前 generic task。

executor 在每个外部动作前用 current owner/token 对 lease heartbeat，再在动作后用新的 task/lease revision 与 ledger CAS 提交 generic observation。workspace lock 不跨 provider 动作持有；若动作期间 cancel、takeover 或 lease 过期，旧 worker 的结果不能提交，下一任 owner 必须从权威 paid ledger inspect/resume。bridge 的 `submit` 契约固定为 inspect-or-submit：generic task 留在 `submitting` 时先读取该媒体已有 paid evidence，不能盲目重提。显式 `not_sent` 才能安全落为可新建后续 attempt 的确定失败；submit 抛错、坏 observation 或 post-call identity drift 一律进入 `submission_unknown`。poll pending 保持可恢复，poll/download/validate 的本地异常保留原 phase 供安全重试；只有权威结构化 terminal observation 才写 generic failed/succeeded。

路由保持媒体差异：同步 image 在 submit 后跳过通用 download 并进入 validate；异步 video 使用独立 poll→download→validate；audio 保留 synthesis submit 与 download 分离。loop 最多 16 步、调用方 deadline 最长 300 秒、零 sleep/busy polling，pending 立即返回；deadline 进入 content-addressed bridge context，executor 在到期后不开始新的 bridge 动作，实际 adapter 仍必须用该 deadline 约束自己的 transport，不能把同步 Python 调用误称为可被 generic 层抢占。`cancelling` 只投影 cancel requested，不调用或伪造 provider cancel confirmation。G5 当前只有 socket-blocked fake bridge、持久 synthetic paid counter 和 fresh-interpreter takeover 的 `mock-functional` 证据；没有内置真实 image/video/TTS adapter、没有迁移或修改 C/D/E paid ledger，也没有 Web mutation、pricing/Insights、production-adapter `local-e2e` 或 provider-validated 结论。

#### G6 Strict Pricing Facts 与分币种 Insights

G6 的 pricing ledger 是 task-bound 审计投影，不是 provider 账单、发票或新的 paid ledger。每条 fact 绑定 exact episode/task/input/subject/media/stage、frozen backend/provider/model/account/endpoint/binding identity，以及受控 source evidence kind/fingerprint；持久金额只用整数微单位，写入 API 只接受规范非负十进制字符串（最多 6 位小数），拒绝 bool、float、科学计数、NaN/Inf、负数、前导零、超精度和超界金额。事实类别固定为 `estimate / authorized / reserved / actual / refunded / unknown`；对应 evidence kind 固定为 quote/authorization/reservation/paid-actual/paid-refund/paid-submission-unknown，不能跨类别重解释。

同一 task 的 facts append-only、内容寻址、sequence/time 单调并在 workspace lock + target token CAS 下原子提交。estimate 必须先出现，authorized 后才允许 reserved/actual/unknown；reserved 不得超过 authorized，unknown 不带金额且不能在 actual 后追加，后续权威 actual 可以解析历史 unknown；refund 可分次追加但累计不得超过 actual。exact fact replay 零写入，冲突 replay、跨 task evidence 复用、币种漂移、identity splice 与倒退 transition fail closed。actual 可以高于 estimate/authorized，偏差必须可见，不能为了“预算正常”截断已发生的付费事实；generic task terminal/failed 也不能自行推导 actual、refund 或 0 元。

只读 Insights 扫描 canonical episode pricing namespace，逐 ledger 重验 strict envelope/bytes、task 与 frozen binding identity；缺失 pricing 对旧 workspace 是空状态，坏 JSON、超限、symlink/目录、非 canonical 名称、tamper 或 task drift 只形成 `degraded/invalid`，不把金额混入 totals。公开行只含 task/episode/subject/media/stage/provider/model、currency、六类安全金额与 unresolved unknown；不含 account/endpoint、任何 fingerprint/evidence、provider task/response/receipt、prompt、URL 或 path。币种永远分组显示，不换汇、不生成跨币种总额；`actual_known` 只汇总已知事实，并与 `unknown_submission_tasks`、`pending_actual_tasks`、`actual_complete` 同时展示，unknown 不会因为已知 subtotal 为 0 而被解释成零费用。当前 UI 只读展示该安全投影；真实 billing adapter、自动价格策略/汇率/结算仍未实现，task lifecycle 指标由 G7 独立承接。

#### G7 Durable Lifecycle Metrics 与 Insights

G7 将 task ledger 升级为 v4，但不改既有 task ID、dedupe 或 record fingerprint：独立 strict lifecycle fact 按 task 保存 `ready_at_ms`、`first_claimed_at_ms` 与 `terminal_at_ms`，并和 task/lease/receipt 在同一 workspace lock、同一 ledger CAS 与同一原子替换中提交。新建 task 的 created/ready 时间只取锁内可信时钟，兼容 `now_ms` 不进入事实；dependency 晋升使用 task 单调更新时间，首次 claim 同时冻结 before/claimed task、initial lease 与 before-ledger identity 的内容寻址证据，terminal 时间精确绑定终态 task 更新时间。claim evidence 先写入独立 no-follow immutable sidecar，主 ledger 的原子替换才让它生效；sidecar 缺失、漂移或与主 ledger 不一致都使 ledger 无法读取。release、reclaim、heartbeat、后续 transition 与 expired takeover 永远保留原 first-claim evidence。

v1-v3 逻辑迁移会把原 canonical source ledger 保存在独立 immutable sidecar，v4 主账本只携带有界 migration evidence 并在每次读取时反查原 source task；旧账本仍守 4 MiB 上限，含新 evidence 的 v4 使用独立 8 MiB 上限，避免在主 ledger 内复制整份旧数据。这里的 immutable 是应用层 no-overwrite/create-once 与内容寻址边界，不是签名、MAC 或 OS 级防篡改承诺。历史上已经 ready/claimed/terminal 的 task 明示 `legacy_unknown`，不能把迁移后的再次 claim 冒充首次，也不能仅翻转标志伪造迁移来源。只有来源中仍为 planned、因而可证明从未 ready/claim 的 task，才从后续可观测晋升开始建立完整 lifecycle；legacy task 后续可追加可证明 terminal，但绝不从 `updated_at-created_at`、最后 lease 或 caller supplied time 反推历史 queue wait。

只读 lifecycle Insights 按 episode/subject/media/stage/provider/model 分组，明确投影 task/terminal/succeeded/failed/cancelled/submission-unknown/pending 数量；success rate 的分母固定为 terminal task。queue wait 只在 ready + first claim 同时可证时计算，run duration 只在 first claim + terminal 同时可证时计算，并同时公开 known/unknown sample count、sum 与 deterministic average string；无样本返回 `null` 而不是伪 0。读取在 workspace 一致锁内完成，namespace/target token 前后重验，且实际解析字节的 source token 必须等于初始快照；task namespace 非 canonical、symlink/目录、坏 ledger、identity drift、超过 4000 tasks/1000 rows 或扫描竞态均 fail closed 为 degraded 空汇总。公开 projection 不含 worker/token/lease、account/endpoint/fingerprint、provider task、paid evidence、prompt、response、迁移来源或 path。真实 provider SLA、自动告警和分位数不在 G7。

#### H1 Typed Source Event Graph 与来源边界

H1 事件图只接收调用方显式提供的结构化事实，不读取原文章节、自由文本摘要或路径，也不从章节邻接、实体关系或文本相似度猜测因果。每个 event 同时绑定 workspace scope 与独立 immutable graph-family scope、稳定 content-addressed ID、逐章 `chapter_id/chapter_no/source_hash`、等于最高来源章的 spoiler boundary、排序唯一的参与者/场景/道具/线索，以及内容寻址的 typed precondition/effect；fact 的 subject/object/value 只能是无空格、无路径分隔符的 bounded opaque atom，没有专用或自由文本的原文、prompt、path、response、credential 字段。调用方仍不得把敏感内容编码进 opaque atom，H1 projection 也尚不能作为无需额外审查的公开 Web projection。来源类型固定为 `source_derived / invented / mixed`；original invented 不得携带 source，original mixed 不合法，source-derived 不得标 invented。`causality_complete=false` 明示已知 parent 之外仍有未知因果，不能被 builder 自动补全。

graph 对 event、source identity、causal parent 与 merge/split lineage 做全闭包验证：workspace scope 与 graph-family scope 分列，不同 workspace 或 family 的 event 不可拼接；所有 parent 必须存在且不晚于 child，causal+lineage 联合图不得成环；同一 chapter ID 或 chapter number 的另一 hash/alias 冲突。merge 必须精确保留 parent 的 source、typed facts、参与者/资产、可证明 causal parents 与 completeness，source-derived 与 invented 混合后只能标 mixed；split 必须由至少两个 child 对 parent 的 precondition/effect 做无重叠完整分区，child 不能改变 source、参与者/资产或 causal facts。build/merge/split 都是 deterministic exact replay，不生成自然语言事件，也不修改 episode/RenderPlan。

持久 graph 是 workspace-local immutable artifact：canonical envelope/bytes、8 MiB 上限、逐级 no-follow 目录、create-once hard-link commit 和 exact replay；symlink、目录、坏/重复 JSON、非 canonical bytes、scope/source splice 或 ID/hash drift 均 fail closed。graph fingerprint 由完整有序且逐条 content-addressed 的 event ID/fingerprint membership records 产生；selection 携带该安全 manifest proof，对显式 event IDs 递归加入 causal + lineage ancestors，要求结果恰好等于按 graph order 排列的最小闭包，并在返回任何内容前核对允许 chapter ID 与最大 spoiler boundary。任一 selected/ancestor/source 越界、omitted 混入、unselected/cross-graph event 注入时整体拒绝，不返回 partial graph。projection 没有专用自由文本、provider、credential 或 embedding 字段，但 opaque atom 仍是调用方可信输入，不能据此宣称它天然适合公开。

这些 source hash、event/graph fingerprint 和 create-once 规则只证明 caller-trusted 结构化 assertion 的内部一致性与内容 identity；H1 不读取 chapter bytes 对账，也没有签名、MAC 或外部 source ledger，不能抵抗有本机写权限者离线重写完整原始 graph 并生成一套全新 ID。H2 已补上当前本地 entity/summary authority bytes 与 RenderPlan 的 production binding；H3 只消费该 binding 并保持 disposable，UI 仍由 I 承接。H1 单独只证明 synthetic `mock-functional` contract，H2/H3 也不把本地 content identity 升格为签名 provenance。

#### H2 Production Source Adapter 与 RenderPlan Graph Binding

H2 保留 H1 的纯结构化 builder，同时新增 named-workspace production loader：只读取 `entity_graph.json` 与 `rolling_chapter_summary.json`，不读取章节原文；两份文件均使用 bounded/no-follow strict reader，并做 exact pair double-read。rolling summary 缺失或无可用章节返回 `insufficient_source`，entity graph 缺失允许 summary-only 且明示 degraded；现存但为空、坏 JSON、duplicate key、非有限数、超限、目录或 symlink 均 fail closed。source snapshot fingerprint 只绑定 adapter 版本、workspace scope 与两份 authority bytes 的存在态/SHA，不混入 episode spoiler policy；完整 graph 不按 boundary 裁成 partial graph。

adapter 每个章节事件只持久化 source chapter id/no/hash、opaque entity ids 与 hash 化 typed relationship fact，不复制 summary、key event、snippet、关系状态或 trigger 文本。`chapter_id/source_chapter`、strict `chapter_no` 与 canonical `续写第NN章` anchor 按明确优先级映射；冲突身份拒绝，未知 anchor 不猜并记录 degraded。无法证明因果时固定 `causality_complete=false`，默认零网络、无 LLM/embedding。

生产 RenderPlan store 不接受 caller-supplied projection 加任意 hash 自证 provenance；入口只接 graph family、selected event IDs 与 spoiler boundary，内部从当前 authority bytes 重建完整 graph 和 exact closure projection。RenderPlan 只在派生层冻结 family、source snapshot、full graph、workspace/family scope、projection、selected/allowed ids 与 boundary；创作 episode、episode SHA 和 creative fingerprint 不变，没有逐镜显式映射时 shot-level event ids 保持空。inspect 每次重读 current authority：合法 byte drift 或 full graph 变化为 stale，source 缺失/损坏/unsafe 为 blocked；写入 precommit 再重建一次，变化时不覆盖旧 plan。旧无 binding RenderPlan 继续按原 fingerprint/freshness 运行。

这里的“authority”仅指当前本地 named-workspace entity/summary 文件在合作锁域和 exact double-read 下的字节身份，不是签名、MAC 或外部版权 provenance；有本机写权限者仍可整套重写来源与派生物。公开 Web projection 仍需由阶段 I 独立实现和安全审查。

#### H3 Disposable Context Memory Cache

H3 不增加第四层创作真源。每个 cache 固定绑定 workspace/project scope、season、episode、graph family、source snapshot、完整有序 graph membership、H2 selected event IDs/selection binding、RenderPlan fingerprint 与 context policy fingerprint；每条 record 再逐条绑定 event ID/fingerprint、source fingerprint 与 chronology。current inspect 会从 production entity/rolling-summary authority 和 current RenderPlan 重新构造 H2 closure，并逐条对账 record source；source/graph/selection/RenderPlan/policy 任一漂移都返回 stale，authority 或 RenderPlan 不可用返回 blocked。删除、缺失或损坏 cache 不会修改或遮蔽 canonical episode、RenderPlan 和 event graph，也不阻止这些权威产物独立读取。

recent、summary 与 keyword 三类 memory 都只保存 event identity。keyword 在内存中做 NFKC/trim/casefold 后哈希，持久化只含 hash 与 event IDs，不保存明文查询；这减少直接泄漏但不是加密，低熵词仍可能被离线字典猜测，因此 cache 不能作为公开匿名数据。默认 policy fingerprint 绑定 `config/agents.yaml`、短剧创作规范、H3 builder 与 RenderPlan builder 的 exact bytes；策略变化会使旧 cache stale。当前没有 embedding 分支、模型下载、LLM 或 socket 调用，查询按 keyword → recent → summary 确定性去重并受限返回；未来若引入本地 embedding，必须另立显式安装/cache/零下载测试与隐私审查。

持久 cache 使用 canonical strict JSON、2 MiB 上限、workspace/season/episode 隔离、逐级 no-follow 目录与 workspace lock；missing create 以 temp + fsync + hard-link no-overwrite 提交，已存在 cache 只有显式 replacement 才在合作锁域内经 target-token guard 后 replace，并在 commit/replay 前重建 current binding。duplicate/nonfinite/unknown schema、symlink/目录/特殊文件、跨 scope、full membership/selection/record tamper 均 fail closed；坏目标不会被自动覆盖。replacement 的 token guard 不是针对非合作本机写者的 OS compare-and-swap，本地 content hash 也不是签名或 MAC；cache 是可删除派生物，不能据此声称 hostile-writer 防篡改。

#### I1 同源只读 Production Workbench

drama-only `/w/<name>/production` 与 `/api/workspace/<name>/drama/production` 不读取前端拼装状态，而是调用既有 current RenderPlan、asset governance、C/D candidate、G task 与 E/F compose inspectors，重建 creative revision、来源 binding、selected asset versions、逐镜 image/video coverage、latest safe attempt outcome、task dependency、timeline、QA 与 exact delivery 的统一 allowlist projection。RenderPlan 绑定 H graph 时，工作台重新读取 production entity/rolling-summary authority 并用 exact projection 对账，只公开 `source_derived / invented / mixed` 数量和 `unbound/fresh/stale/blocked` binding state，不公开事件原文、typed fact atoms 或 source path。

列表和可选画布都引用同一 stable asset/shot/task/timeline ID 集，并携带完全相同的 `source_projection_fingerprint`；canvas node/typed edge 只是服务端事实的另一种有界视图，前端颜色和连线不会写回 durable task，也不能把节点变绿解释为 provider 成功。单集最多投影 100 shots、256 selected assets、256 tasks、700 nodes 与 1500 edges，超出边数确定性截断并显式报告 omitted；task unknown/failed 计数仍覆盖完整已验证 ledger，不能因 UI 截断消失。

API/page 只接受 drama workspace 和 1-100 episode，GET 不包含 mutation、submit、poll、cancel 或 provider 调用。公开字段不含本地/内部路径、visual/text prompt、provider raw response、signed URL、credential、account/endpoint fingerprint、paid receipt/evidence 或未脱敏异常；可选 catalog/manifest 缺失显示 missing/incomplete，坏 source、symlink/特殊文件、坏 JSON、identity drift、submission unknown 或 inspector failure 显式 blocked/invalid，不伪造 ready。iter147 已以真实本地浏览器覆盖桌面列表、画布切换与 390px 窄屏；canvas mutation 和操作按钮仍属于后续范围。

#### I2 可移植 Project Archive

`drama-project-archive export/preflight/import` 默认零网络、零 provider。archive 把从 canonical episode 明确字段 allowlist 重建的 portable episode 与清空 `agent_reviews` 的 meta 放入 `creative/`，把 exact selected/reference PNG 放入 `assets/`，把 current timeline、其 content-addressed 源音视频和 exact MP4/SRT/ASS/edit 放入 `media/`，把 typed selected asset/shot binding、render source identity、task 计数和 strict QA report 放入 `evidence/`。PNG 必须通过 magic/chunk/CRC 检查且不得含 textual/EXIF chunk；其他静态资产格式当前 safe-blocked。RenderPlan 本体因包含完整生图 prompt 而不入包，manifest/evidence 只保留 original source episode SHA、plan fingerprint 和安全计数。

导入在任何 target 写入前完整检查 ZIP 路径/属性、case-fold 冲突、member 数量/单件/总解压/压缩比、schema/MIME/size/hash 与 manifest 外成员，再交叉对账 portable/source episode SHA、typed selection + selected artifact、render source binding、timeline 与每个 source hash、strict QA report、从 timeline 重建的 SRT/ASS/edit 及 MP4 SHA。通过后只能以私有 staging + fsync + OS atomic no-replace 创建新 drama workspace；已存在 target 不会被覆盖，rename 后父目录 fsync 失败则返回已提交的 `commit_uncertain`。导入快照依据收据逐字节重导出，保持成员、project/archive identity 不变。它是可校验的迁移/交付 snapshot，不是可继续调 provider 的 runnable raw workspace，也不保留 attempt ledger、完整 prompt 或可重放付费授权。

### 11.4 依赖顺序与完成口径

创作段按 `0 → 1 → 2 → 3 → 4 → 5 → 6/7` 执行；Reject/Abstain 回到对应站修订，只有 Approve 才能写 canonical episode。

媒体段按以下依赖推进：

1. `A → B → C → D`；E 依赖 A，可与 C-D 的实现部分并行。
2. F 同时依赖 C、D、E，是第一个可以称为“本地完整 MP4 生产链”的节点。
3. G 只在 C-F 已出现稳定重复模式后抽象，避免过早用通用队列大改现有安全恢复边界。
4. H 依赖 A，但不阻塞 F；I 在 B-G 的后端事实稳定后建设。
5. J 只校准已经通过 mock/local 验证的对应链，且四类真实能力分别授权、分别取证。

截至 iter 148，可以准确表述为：**创作五站、连续多集、A1/A2 渲染与精确 stale 契约、B1-B3 本地资产治理与 Web、C1-C4 逐镜图片候选 Web、D1-D5 逐镜视频候选/连续性 Web、E3→F3 的持久时间线、本地合成 job、QA 真值和 exact 四件套交付，G1-G7 持久媒体任务 DAG/worker/registry/execution/pricing/lifecycle metrics，H1-H3 source event graph/production authority/disposable memory，以及 I1 同源只读 production workbench + I2 可校验迁移/交付 snapshot 已形成可本地恢复、可重建并可携带交付证据的工程闭环**。I2 的导入结果不是 runnable raw workspace。不能据此表述为“真实短剧生产链已 provider-validated”：B 的物理 GC，C/D/F 的多格式、多 profile、真实媒体，G 的真实 adapter/账单与 J provider/capstone 仍未闭环。

### 11.5 规划外边界

当前 A-J 路线图以“本地完整 MP4、字幕、可编辑导出、生产工作台、归档和 provider 校准”为终点，不包含抖音、快手、视频号等平台的自动发布 adapter，也没有账号、审核、发布回执或失败恢复状态设计。现阶段成片只能人工发布；若要自动发布，应另立产品规划，不能把它写成 A-J 已排期能力。
