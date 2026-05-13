# Dragon Raja AI Continuer MVP

多 Agent 长篇小说续写流水线 MVP。默认使用 `mock` 模型跑通工程流程；配置 `.env` 后可通过 LiteLLM 接真实模型。

## Quick Start

```bash
python3 main.py normalize
python3 main.py split
python3 main.py extract --volume all
python3 main.py compress
python3 main.py debate
python3 main.py write --chapters 18
python3 main.py review --target outputs/drafts
```

一键小规模验证：

```bash
python3 main.py run-all --extract-limit 2 --chapters 1 --force
```

查看流水线状态和报告：

```bash
python3 main.py status
python3 main.py check-manifest
python3 main.py manifest-report
python3 main.py review-summary
python3 main.py check-reports
python3 main.py estimate-cost
python3 main.py preflight
```

## Real Model Setup

复制 `.env.example` 为 `.env`，填入模型配置：

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=deepseek/deepseek-chat
```

默认模型配置在 `config/models.yaml`。如果不设置 `.env`，系统会使用 `mock`，不会发起网络请求。
真实模型调用会在 `logs/llm_calls.jsonl` 记录 `request_hash`、prompt/response token、context overflow 信息和 provider cache token；不会记录完整 prompt 正文。

## Real Model Hardening

- Rolling summary 会按中文句末边界保留尾部，不再直接字符硬截断。
- `extract` 超过 `chunk_threshold_chars` 的章节会分 chunk 抽取；任一 chunk 失败时整章进入 `data/extraction_failures/`，不写半成品。
- `write` 会把上一轮 reviewer reject 的结构化反馈写回下一轮 prompt，并受 `config/agents.yaml` 的 `max_review_attempts` 硬上限控制。
- `preflight` 会在真实小样本前做只读检查：`.env`、context limit、失败残留、rolling state、chunk 触发、cache provider、人工全局事实和最近 token 日志。
- `scripts/real_smoke.sh` 串起 `preflight -> extract --limit 2 -> status -> estimate-cost -> preflight`，日志写入 `logs/real_smoke_<timestamp>.log`。
- `write` 的尝试次数配置名为 `max_review_attempts`（必填键，缺失时 writer 与 preflight 直接报错），含义是初稿加重写的总次数。
- `write` 会把稳定的 system prompt、全局知识和大纲标为 prompt cache segment；不支持 cache 的 provider 会自动降级普通调用。
- `estimate-cost` 优先汇总 `logs/llm_calls.jsonl` 中的真实 token 与 cache token，没有真实日志时仍保留 source char 估算。

## Pipeline

- `normalize`：识别 UTF-16 / GB18030，输出 UTF-8 到 `data/normalized_texts/`，行号映射到 `data/source_map/`。
- `split`：生成 `data/chapter_manifest.json`，后续步骤只信这个 manifest。
- `extract`：按章节提取 JSON，加入 rolling context，长章节自动前/中/末 chunk 抽取并合并，输出到 `data/extracted_jsons/`。
- `compress`：生成 `data/knowledge_base/global_knowledge.md` 和 `knowledge_index.json`。
- `debate`：六 Agent 六轮辩论，输出 `outline.md`、`decisions.json`、`debate_log.jsonl`。
- `write`：按大纲生成章节，先过 linter，再过七 Agent 审查。
- `review`：对已有草稿目录或单文件重新审查。
- `preflight`：真实模型小样本前的只读检查；任一 FATAL 项会以非零退出码停止。
- `check-manifest`：校验 `chapter_manifest.json` 的必需字段、章节 ID 唯一性、行号范围、文件存在性和同文件章节重叠；短章作为 warning 输出。
- `check-reports`：只读校验 `chapter_manifest.md` 和 `review_summary.md` 是否与当前 JSON 输入一致；需要刷新时加 `--update`。

## Manual Overrides

把人工裁决 JSON 放入 `data/manual_overrides/`，字段会覆盖对应章节提取结果。示例：

```json
{
  "chapter_id": "longzu_3_3_ch024",
  "character_states": [
    {
      "character": "上杉绘梨衣",
      "before": "生死状态存在模型误判风险",
      "after": "已死亡",
      "status": "dead",
      "evidence_spans": []
    }
  ]
}
```

人工覆盖优先级高于模型输出，并会写入 `manual_overrides_applied`。

全局人工事实放入 `data/manual_overrides/global_facts.json`，用于“绘梨衣死亡”这类跨章隐性裁决，并会注入 compress、debate、write、review：

```json
[
  {
    "fact_id": "erii_status_dead",
    "statement": "上杉绘梨衣已死亡；这是跨章隐性线索汇总后的人工裁决，优先于模型逐章抽取。",
    "confidence": 1.0,
    "scope": "global",
    "applies_to": ["compress", "debate", "write", "review"],
    "evidence_spans": []
  }
]
```

## Tests

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
```

## Development Acceptance

固定验收：

```bash
bash scripts/verify.sh
```

该脚本会执行语法检查、完整单元测试、normalize/split、mock 小闭环、状态报告和成本估算。
脚本也会运行 `check-manifest` 和 `check-reports`，确保章节清单结构有效、生成报告没有未同步漂移。

## Real Model Checklist

- 确认 `python3 main.py status` 没有意外失败队列。
- 先跑 `python3 main.py preflight`，处理所有 FATAL。
- 确认 `python3 main.py manifest-report` 中章节切片符合预期。
- 配置 `.env` 后先跑小样本脚本：`bash scripts/real_smoke.sh`。
- 若提取失败，先看 `data/extraction_failures/`，修复后跑 `python3 main.py retry-failures`。
