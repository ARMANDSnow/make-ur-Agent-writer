<div align="center">

# Continuator / 续

**一条用工程方法构建的多 Agent 长篇小说续写流水线。**

[简体中文](README.md) · [English](README_EN.md)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-216_passing-brightgreen.svg)](#%E9%A1%B9%E7%9B%AE%E7%8A%B6%E6%80%81)
[![Iterations](https://img.shields.io/badge/iterations-19_logged-orange.svg)](docs/iterations/)
[![LiteLLM](https://img.shields.io/badge/router-LiteLLM-purple.svg)](https://github.com/BerriAI/litellm)
[![Mock-first](https://img.shields.io/badge/dev-mock_first-success.svg)](#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)

</div>

---

## TL;DR

读入一部已出版小说 → 构建结构化知识库 → 6 个 agent 辩论续写方向 → 用强推理模型规划 N 章 → 每章由便宜快模型生成 → 5 个 reviewer + 确定性 linter 质量把关 → **`scripts/write_book.sh` 一条命令多章无人值守 + 失败重试 + 自动 entity advance**。

**不是**"又一个套壳 GPT"。重点是**围绕 LLM 的工程脚手架**：19 轮 mock 优先的迭代、真模型验证、preflight 守门、reviewer fail-closed 抗 silent-approve、多 workspace 隔离、中英文双语切章 + stdlib EPUB 提取、每次调用的成本遥测。

实证：《龙族》（江南）+《冰与火之歌》（GRRM 英文）+ 自有小说均能跑通同一条流水线。最新真模型测试：**龙族 ch1 → Approve、13.8K 字符、单章成本 ~¥0.45**（gpt-5.5）。

> 原作小说本体被 gitignored。本仓库只发布引擎，不发布语料。

---

## 为什么这个项目值得点开

| 层 | 在代码里长什么样 |
|---|---|
| **Mock 优先开发** | 216 个单元测试，**4 秒跑完**，一个 token 都不烧。`tests/__init__.py` 强制 `OPENAI_MODEL=mock`，防 `.env` 泄露污染测试。 |
| **Preflight 守门** | 真模型跑之前 7 类 FATAL 检查 + N 条 WARN：env / context limit / agents 配置 / rolling state / manifest 完整性 / **provider routing** / 人工事实 / cache 提供商提示。 |
| **多 workspace 隔离** | iter 017：每本书一个 `workspaces/<name>/{data,outputs,小说txt,logs}/`。`--book myBook` 切换；sha256 baseline 4/4 互不污染。 |
| **多语言切章 + EPUB 提取** | iter 018：CJK 字符比率自动判中英；中文 `第N章` / 英文 `CHAPTER / POV / 全大写` 两套 regex。`.epub` 用 stdlib `zipfile + xml.etree + html.parser` 直接转 txt，**零新依赖**。 |
| **无人值守 write_book** | iter 019：`scripts/write_book.sh --book X N` 跑 N 章不间断。失败自动重试（默认 max-retries=2）、entity advance proposals 自动应用（confidence>=0.7）、snapshot 在成功/重试用尽两条路径都落盘。 |
| **Reviewer fail-closed** | iter 019 audit：5-agent 中任一 JSON 解析失败，记 `Abstain + _fallback_reason="(parse_failed)"`，不当 Approve；最终 verdict 任一 substantive Reject → Reject，零 substantive Approve → Reject。 |
| **带 timeline 的 Entity graph** | 角色/地点/概念作为 entity；关系携带 `timeline[]`，`active=true` 标记当前续写起点状态。**writer 只看 active state**；"关系一致性" reviewer 对照核验。 |
| **成本遥测** | 每次 LLM 调用记 `request_hash`、prompt/response tokens、cache_read/cache_write tokens。`estimate-cost` 按 provider 单价聚合。龙族 ch1 真模型实测：30 calls / 143K prompt（cache 命中 58%）/ 36K response / **~¥0.45**。 |
| **Persona 抽象** | iter 016：debate / reviewer 的 5 agent 不再硬编码龙族角色名；每本书 `init-book` 自动用 LLM 出 personas proposal → 人工审 → 落 `data/manual_overrides/personas.json`，模板渲染。 |
| **迭代日志** | [19 条](docs/iterations/)，每条 Context / Plan / Acceptance / 实测数字 / File summary 完整工程复盘。仓库本身就是一份工程日记。 |

---

## 快速开始

### Mock 模式 —— 不需要 API key，不联网

```bash
git clone https://github.com/ARMANDSnow/make-ur-Agent-writer.git
cd make-ur-Agent-writer
pip install -r requirements.txt
bash scripts/verify.sh      # 216 unit tests + 全流水线 mock，~30 秒，退出 0 = 接通
```

### 真模型模式（gpt-5.5 / deepseek / 任何 OpenAI 兼容 provider）

```bash
cp .env.example .env
# 编辑 .env，例如：
#   OPENAI_API_KEY=sk-...
#   OPENAI_BASE_URL=https://your-gateway.example/v1
#   OPENAI_MODEL=openai/gpt-5.5
# 可选：PLANNER_* 三件套（不设则 planner 跟随 OPENAI_*）

python3 main.py preflight                        # 7 类 FATAL 检查，非零退出 = 别跑真模型
bash scripts/write_book.sh --book myBook 2       # 写 2 章，无人值守
```

### 接入任意小说（5 步走）

```bash
# 1) 起 workspace + 把 txt（或 .epub）丢进去
python3 main.py workspace-init myBook
cp ~/your-novel.txt workspaces/myBook/小说txt/
# 英文 EPUB 走 stdlib 提取：
# python3 main.py --book myBook epub-import --src ~/novel.epub --out myBook.txt

# 2) 自动检测语言 → 规范化 → 切章
python3 main.py --book myBook normalize
python3 main.py --book myBook split

# 3) LLM 出 5 类 proposal（entity_graph / global_facts / continuation_anchor / style_examples / personas），人工审过再 confirm
python3 main.py --book myBook init-book --extract-limit 10
# 编辑 workspaces/myBook/data/proposals/*.json 后：
for name in global_facts entity_graph continuation_anchor style_examples personas; do
  python3 main.py --book myBook apply-bootstrap --name $name --confirm
done

# 4) 6-agent 辩论 + 强模型 N 章规划
python3 main.py --book myBook debate
python3 main.py --book myBook plan-chapters --chapters 3

# 5) 无人值守多章写作
bash scripts/write_book.sh --book myBook 3
# 标志：--max-retries N（默认 2）、--min-confidence X（默认 0.7）、--no-auto-advance
# 退出码：0 = 全章 Approve，2 = 某章重试用尽
```

切换书只改一个 flag（`--book otherBook`），或 `export WORKSPACE_NAME=otherBook` 一次性生效。`workspace-list` / `workspace-show` 看现有 workspace。

---

## CLI 速查

| 命令 | 作用 |
|---|---|
| `workspace-{init,list,show,import-current}` | 多 workspace 管理（iter 017） |
| `epub-import` | EPUB → UTF-8 txt，stdlib only（iter 018） |
| `normalize` / `split` | 自动识别编码 + 语言；切章产 `chapter_manifest.json` |
| `init-book` | 一键产 5 类 proposal（entity_graph / facts / anchor / style / personas） |
| `apply-bootstrap --name X --confirm` | 审过的 proposal 落盘 |
| `debate` | 6 agent × 6 轮 + 结构化投票 → outline.md + decisions.json |
| `plan-chapters --chapters N` | 强模型一次出 N 章规划（iter 014） |
| `write --chapters N --resume-from i --force` | 多章生成 + 8 reviewer + lint + polish |
| `review-chapter <i>` / `chapter-status <i>` | 独立复审 / 单章状态 JSON（iter 019） |
| `apply-advance --chapter i --auto-apply --confirm` | entity advance（iter 019） |
| `preflight` / `status` / `estimate-cost` | 守门 / 状态 / 成本汇总 |

详见 [README_EN.md](README_EN.md)，含架构图、3-tier 执行说明、所有迭代日志索引。

---

## 项目状态

| 阶段 | 范围 | 状态 |
|---|---|---|
| 阶段 1（iter 001-005）| Mock 优先基础、CLI、preflight | ✅ |
| 阶段 2（iter 006-008）| 首次真模型 smoke + debate 结构化投票 | ✅ |
| 阶段 3（iter 009-013）| 写作质量轴：entity graph / 一致性 reviewer / 多章架构 | ✅ |
| 阶段 4（iter 014-019）| 多 workspace + 多语言 + 无人值守 + 审计加固 | ✅ |
| 阶段 5（iter 020+）| Web Dashboard（stdlib-only，mock 验收） | 计划中 |

阶段小结：[stage_01](docs/stage_01_summary.md) · [stage_02](docs/stage_02_summary.md) · [stage_03](docs/stage_03_summary.md)。
会话延续锚点：[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md)。

---

## 范围 & 声明

- 这是**研究性质的工程练习**，不是产品
- 原作小说**不被重新分发**：`小说txt/` / `workspaces/*/小说txt/` / `data/` / `outputs/` / `logs/` 全 gitignored；仓库只含**代码 / 配置 / prompt / 文档 / 迭代日志**
- 生成的续写章节是源作品的衍生作品，只保留本地
- 任何小说都能跑：丢 `.txt` 或 `.epub` 进去，跑 `init-book`，剩下的流水线一致

---

## 技术栈

- **Python 3.9+**
- [LiteLLM](https://github.com/BerriAI/litellm) —— 多 provider 路由
- [Pydantic](https://docs.pydantic.dev/) —— schema 唯一来源
- [tiktoken](https://github.com/openai/tiktoken) —— token 计数（`cl100k_base` 回落）
- [python-dotenv](https://github.com/theskumar/python-dotenv)

无 async、无框架锁定、无 orchestration 库、无 web 框架（iter 020 Web Dashboard 也坚持 stdlib `http.server`）。纯 Python + LLM + JSON I/O。

---

<div align="center">

用 19 轮 *先测量，再 commit* 建出来的项目。

</div>
