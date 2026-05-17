# Style Examples

本目录存放从原著中摘取的风格参考片段，供 writer agent 在 prompt 中按需注入。

> ⚠️ **版权**：原文片段仅本地保存，**不要 commit**。`.gitignore` 应忽略本目录下除 `README.md` 外的所有 `.md`。

---

## 一、分类（一级，互斥）

| 文件 | 用途 | writer 调用时机 |
|---|---|---|
| `opening_rhythm.md` | 章节/段落起手节奏 | 生成新章节第一段 |
| `quiet_scene.md` | 日常、过场、留白 | 推进日常情节、缓冲段 |
| `inner_monologue.md` | 内心独白（重点是路明非式自嘲） | 人物内心戏、自我剖析段 |
| `character_dialogue.md` | 对话节奏与角色腔调 | 多人对话、台词密集段 |
| `character_portrait.md` | 人物外部刻画/亮相速写 | 新人物登场、重要人物特写、群像扫描 |
| `action_burst.md` | 战斗/追逐/能力爆发 | 动作高潮段 |
| `environment_imagery.md` | 环境意象主导段 | 场景转换、章节结尾留白、地点首次登场 |
| `flashback_memory.md` | 回忆/插叙/时间跳切 | 补叙前史、伏笔回闪、情绪升华 |

**互斥原则**：每段片段只归入一个文件。边界模糊时按"该片段最显著的功能"归类，不要复制到多个文件。

---

## 二、每个片段的格式（二级，用标签做横切）

每个文件内用 `## 片段 N` 分段，统一三行 metadata + 原文：

```markdown
## 片段 1
- 来源：《龙族Ⅰ 火之晨曦》第 7 章
- 场景：路明非在芝加哥便利店买烟
- 标签：[比喻密集, 第三人称限知, 黄昏意象]

<200-500 字原文>
```

**标签**用来标横切风格（比喻密集 / 短句密集 / 黄昏意象 / 中西混搭 / 第一人称 / 第三人称限知 / 时间跳切 ……）。writer agent 可以二次过滤。

---

## 三、收录规模建议

- 每个文件 **3-5 段**，每段 **200-500 字**起步。
- 总量先控制在 ~20 段以内跑通流程，再迭代扩充。
- 模型对 in-context examples 是敏感于近邻的，**质量 > 数量**，不要堆。

---

## 四、writer agent 调用约定（实现侧）

future selector（在 `src/` 实现）按当前章节大纲的场景类型选 1-3 个 `.md` 拼进 prompt。粗略映射：

| 章节类型 | 注入文件 |
|---|---|
| 章节开头 | `opening_rhythm` + 主场景对应文件 |
| 日常推进 | `quiet_scene` + `character_dialogue` |
| 战斗高潮 | `action_burst` + `inner_monologue`（少量） |
| 情绪/抒情段 | `environment_imagery` + `flashback_memory` |
| 对话密集章 | `character_dialogue` + `inner_monologue` |
| 新人物登场 | `character_portrait` + `opening_rhythm` |

---

## 五、新增类别的红线

不要因为某段"很经典"就新建文件夹。新类别必须满足：
1. 与现有 8 类**功能上互斥**（不是题材或角色不同）。
2. 至少能稳定收到 3 段以上同类片段。
3. writer agent 在某种章节类型下需要**专门**注入它。

满足不了就用标签代替。
