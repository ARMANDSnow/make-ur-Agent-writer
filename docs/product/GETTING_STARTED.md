# 续 · 上手指南

> 给想直接用起来的人。照着走，从一本小说到一份续写稿。
> 想看完整产品规格 → [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。

---

## 1. 它能帮你做什么

把一本小说（`.txt` 或 `.epub`）交给它，它会：**读懂人物和设定 → 规划后面的情节 → 一章一章写出来 → 自己派一个 AI 评审团审稿**。你只需要在几个关键路口做决定（从哪章接着写、用多严的标准、花多少钱），其余它自己跑。

也可以**只用一句话立意**起一本全新的原创小说。

---

## 2. 动手前准备

| 你需要 | 说明 |
|---|---|
| Python 3.9+ | 跑 `python3 --version` 确认 |
| 一个 API Key | OpenAI 兼容即可（GPT / DeepSeek / Claude 等），填进 `.env` |
| 一本书 | `.txt` 或 `.epub`，放进对应 workspace |
| 想清楚起点 | 你想"从原著第几章之后"开始续写 |

`.env` 最少配三行（参考 `.env.example`）：

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=...      # 用官方就留空
OPENAI_MODEL=gpt-...     # 想先不花钱，填 mock
```

---

## 3. 先免费试一遍（强烈建议）

把 `OPENAI_MODEL` 设为 `mock`，整条流程**不花钱、不联网**就能跑通——正文会是占位短稿，但能让你确认每一步都顺、命令都对。等流程跑顺了，再换成真模型出文。

> mock 是默认模式：照第 4 节的命令直接跑，跑出来的就是 mock 结果。

---

## 4. 正式续写一本书（六步）

以续写《龙族》为例，`<book>` 换成你的书名。每步都标了**你要做的决定**。

### ① 建库 + 放书
```bash
python3 main.py workspace-init longzu
# txt：直接拷进 workspaces/longzu/ 下的原文目录
# epub：python3 main.py --book longzu epub-import --src ~/longzu.epub
```
🟢 *决定*：给这本书起个名字（后面所有命令靠 `--book` 认它）。

### ② 切章
```bash
python3 main.py --book longzu normalize   # 规范化编码
python3 main.py --book longzu split       # 自动切章（中英文自动判定）
```
👀 *会看到*：一份章节清单，每章带置信评分。切歪了可人工调。

### ③ 抽设定（产出 5 类提案，你来确认）
```bash
python3 main.py --book longzu init-book --extract-limit 10
```
它会提取出 5 类材料：**事实库 / 人物关系图 / 起点锚点 / 风格样例 / 角色卡**，但**先不落盘**——你看过觉得对，再确认：
```bash
python3 main.py --book longzu apply-bootstrap --name entity_graph --confirm
# 其余 4 类同理：global_facts / continuation_anchor / style_examples / personas
```
🟢 *决定*：抽得对不对、要不要手改。这是续写质量的地基，值得花两分钟看。

### ④ 选起点
```bash
python3 main.py --book longzu set-start-point <章节ID>
```
🟢 *决定*：从哪一章之后开始续。**定下后，系统只让后续步骤看到"这一章及以前"的内容**——这是它防剧透的关键。

### ⑤ 规划情节
```bash
python3 main.py --book longzu debate                          # 多 agent 辩论方向
python3 main.py --book longzu plan-chapters --chapters 3 --force   # 生成 3 章细纲
```
👀 *会看到*：续写方向的辩论结论 + 一份分章细纲（写手的"施工图"）。
🟢 *决定*：方向满意吗？细纲可以改了再往下走。

### ⑥ 开写 + 看稿
```bash
python3 main.py --book longzu write-readiness --chapters 3    # 起飞前自检
bash scripts/write_book.sh --book longzu --chapters 3 --tier mid --budget-cny 10
```
🟢 *决定*：
- `--tier`：**草稿用 `low`、正经写用 `mid`、出版级用 `high`**（越高越严，越容易被打回重写）；
- `--budget-cny`：花到这个数就自动停，**不会偷偷超支**。

写完查结果：
```bash
python3 main.py --book longzu chapter-status 1   # 看某章的稿子和评审意见
python3 main.py estimate-cost                    # 看一共花了多少
```

---

## 5. 想要图形界面

不爱敲命令就开网页版：

```bash
python3 main.py web        # 浏览器打开 http://127.0.0.1:8765
```

进去是一个**四步工作台**：设定 → 大纲 → 细纲 → 正文，每步点按钮跑、产物能直接在页面上改。**一句话开一本原创书**走这条路最顺。

---

## 6. 想一口气连写几十章

用长程驱动器，让它后台无人值守地连写，中途断了也能接着跑、**不会重复花钱**：

```bash
python3 main.py --book longzu drive-book start --chapters 30 --detach
python3 main.py --book longzu drive-book status     # 看进度和账本
```
遇到质量不过关的章，它会**停下来等你看**，不会硬着头皮往下写。

---

## 7. 花多少钱 & 不超支

- **量级感知**：真模型下单章大约 **¥1 上下**，试跑十几章在 **¥20 量级**（随模型和章长浮动）。
- **三道保险**：① 先用 `mock` 免费验流程；② 每条写作命令带 `--budget-cny`，超了立即停；③ 真花钱前先 `python3 main.py preflight` 体检环境，报错照提示修 `.env` 再跑。

---

## 8. 常见问题

**Q：某章被 blocked / Reject 了？**
这是**好事**——评审团觉得它不够好或有剧透风险，主动拦下了（系统宁可拦错不放过）。看它给的拒因，对症处理：改细纲后重规划、调低 tier 先出草稿、或换个更合适的起点。

**Q：preflight 报错跑不动？**
基本都是 `.env` 没配对（key、模型名、base_url）。按报错提示改，FATAL 项不过就不会真烧钱，放心修。

**Q：想换个起点重来？**
重设 `set-start-point` 后，重跑 ④之后的步骤即可。已有全本的书，系统会自动按新起点重建知识库。

**Q：只想白嫖看看效果，不想花钱？**
全程 `OPENAI_MODEL=mock`。流程、门禁、报表都真实，只有正文是占位稿——验证"跑不跑得通"完全够用。

**Q：能同时弄好几本书吗？**
能。每本一个 workspace，靠 `--book` 切换，互不干扰。

---

*更深的机制（防剧透三道护栏、评审面板、diff oracle 等）和当前进度见 [PRODUCT_SPEC.md](PRODUCT_SPEC.md) 与项目根 [README.md](../../README.md)。*
