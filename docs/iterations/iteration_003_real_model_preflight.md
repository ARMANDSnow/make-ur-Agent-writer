# Iteration 003 - Real Model Preflight + Loose Ends

## Context

Iteration 002 完成真模型前的工程加固（A1/A2/A3/B1/C1），55 个测试和 `scripts/verify.sh` 全绿，但只在 mock 模式跑过。在切真模型之前还差三件事：

1. 没有任何机制阻止用户把全量 extraction 直接打到真模型上：`.env` 没填、`context_limit` 配错、长章节会触发 `LLMContextOverflowError`、`tiktoken` 找不到模型回落到估算——这些问题在第一次真实调用时才会暴露，浪费 token 还污染 `extraction_failures`。
2. 验收 iteration 002 时发现 `rewrite_max` 的命名陷阱：当前 `rewrite_max: 2` 实际只允许 1 次重写（`range(1, rewrite_limit + 1)` 是总尝试次数）。语义和直觉不一致，配置文件读起来会误导。
3. 验收时还看到 `check-reports` 实际是 iteration 001 加的（已记录），属于澄清而非修复。

本轮目标：**让真模型小样本能"按一个按钮就跑通"，且失败前有明确的 preflight 拦截。** 不动 B2/B3/C2 等创作质量与成本结构性改造，等真模型小样本跑出具体翻车样式后再排下一批。

## Plan

### P1. `python3 main.py preflight` 命令

新增 [src/preflight.py](src/preflight.py) 与 [main.py](main.py) 子命令，纯只读检查，输出结构化报告并以非零退出码反馈致命错误。

检查项分三档：

**FATAL（任何一项不通过即退出码非零）**

- `.env` 中 `OPENAI_API_KEY` 非空（除非 `OPENAI_MODEL=mock`）。
- `OPENAI_BASE_URL` 在 `OPENAI_MODEL != mock` 时非空，且能 `urlparse` 出 host。
- 当前选用模型在 [config/models.yaml](config/models.yaml) 每个 task 下 `context_limit` 字段存在且 > 0。
- `logs/` 目录可写。
- `data/extraction_failures/` 中残留失败计数 == 0（如果非 0，要求先跑 `retry-failures` 或人工清理）。
- `data/rolling_summaries/<volume>.json` 与 `data/extracted_jsons/` 一致：rolling state 中 `previous_summaries` 的最后一条章节 id 应在 `extracted_jsons/` 出现。漂移则报错，避免续提取时摘要错位。

**WARN（打印但不失败）**

- `tiktoken.encoding_for_model(model)` 失败、回落到 `cl100k_base`（中文 token 计数会偏低 5-10%）。
- 最长章节估算 prompt_tokens：取 `data/chapter_manifest.json` 最大 `char_count` 章节，按当前 `extract` 任务模板用 `_request_meta` 跑一次（不发请求），若 `prompt_tokens + max_tokens > 0.9 * context_limit`，提示该章节会触发 chunked extraction（不是错误，但要让用户知道）。
- `cache_enabled=true` 但模型名不属于已知支持 cache 的 provider 前缀（Anthropic / Bedrock-anthropic / DeepSeek 已知，OpenAI ChatCompletion 当前不支持 prompt-level cache_control）。命中即提示"cache 不会生效"。
- `manual_overrides/global_facts.json` 不存在或为空：提示 `绘梨衣死亡` 等关键人工裁决未注入。

**INFO（仅展示）**

- 当前各 task 模型、temperature、max_tokens、context_limit 一览表。
- 章节统计：总数、最长章节字符数、超过 `chunk_threshold_chars` 的章节数。
- `logs/llm_calls.jsonl` 最近 10 条的 status 分布与 token 总和。

输出格式：先一行 `PREFLIGHT: <ok|warn|fail>`，再分组打印 FATAL/WARN/INFO，最后一段是「建议下一步」（基于状态给出 `extract --limit 2 --volume longzu_1` 之类的具体命令）。

### P2. `scripts/real_smoke.sh`

新增固定脚本，串起来跑：

```
preflight  →  extract --volume longzu_1 --limit 2 --force  →  status  →  estimate-cost  →  preflight
```

末尾再跑一次 preflight 是为了确认 small-sample 后没有新增 `extraction_failures`、rolling state 没漂移。脚本任何一步非零退出码就 abort，stdout/stderr 同时落到 `logs/real_smoke_<timestamp>.log`。

不替代 `scripts/verify.sh`（mock + 单测），并存。

### P3. 修 `rewrite_max` 命名陷阱

在 [config/agents.yaml](config/agents.yaml) 把 `rewrite_max` 重命名为 `max_review_attempts`（含义：初稿 + 重写的总次数上限）。在 [src/writer.py:31](src/writer.py) 读取处加兼容 fallback：

```python
agent_cfg.get("max_review_attempts", agent_cfg.get("rewrite_max", 2))
```

同步：
- [src/writer.py:21](src/writer.py) 函数参数 `max_rewrites` 改名 `max_attempts`，旧名作为 deprecated 别名保留一轮。
- [tests/test_writer_rewrite_loop.py](tests/test_writer_rewrite_loop.py) 把 `max_rewrites=2` 改成 `max_attempts=2`，断言保持 `rewrite_count == 1`（语义未变，只是名字更准）。
- [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) 更新一行说明。

不改默认值（仍是 2），即"初稿 + 1 次重写"。

### P4. `preflight` 单测

[tests/test_preflight.py](tests/test_preflight.py) 至少覆盖：

- 缺少 API key + 非 mock 模型 → FATAL，退出码非零。
- 模型为 mock 且其他都 OK → ok。
- `extraction_failures` 残留 1 条 → FATAL。
- rolling state 中最后一章不在 extracted_jsons → FATAL。
- 最长章节估算超过 `0.9 * context_limit` → WARN（不 FATAL）。
- 不依赖真实 LLM 调用，全部用临时目录和 patch。

## Acceptance

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
bash scripts/verify.sh
python3 main.py preflight     # 期望 PREFLIGHT: ok 或 warn（mock 模式）
bash scripts/real_smoke.sh    # mock 模式下应 OK；切到真模型时是用户操作
```

新增测试预计 55 + 6 ≈ 61 条。

## Implementation Notes

- `src/preflight.py` 已实现 FATAL / WARN / INFO 三档报告，且不调用远端模型。
- `python3 main.py preflight` 会在 FATAL 时返回非零退出码。
- `scripts/real_smoke.sh` 会把全量 stdout/stderr tee 到 `logs/real_smoke_<timestamp>.log`。
- `config/agents.yaml` 已改用 `max_review_attempts`；`src/writer.py` 暂时保留 `rewrite_max` 与 `max_rewrites` fallback。
- `extractor` 后续 rolling state 会写入 `previous_chapter_ids`，preflight 对旧 schema 给 WARN，对存在但漂移的 last id 给 FATAL。

## Acceptance Result

通过：

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
# Ran 62 tests
# OK

bash scripts/verify.sh
# OK

python3 main.py preflight
# PREFLIGHT: warn, 0 FATAL

bash scripts/real_smoke.sh
# OK, log written under logs/real_smoke_<timestamp>.log
```

当前 mock preflight WARN：

- 最长章节 `longzu_1_ch004` 超过 `chunk_threshold_chars=24000`，会触发 chunked extraction。
- `data/manual_overrides/global_facts.json` 缺失或为空，真实小样本前建议写入关键人工事实。

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/preflight.py](src/preflight.py) | 新建，FATAL/WARN/INFO 三档检查 |
| [main.py](main.py) | 加 `preflight` 子命令 |
| [scripts/real_smoke.sh](scripts/real_smoke.sh) | 新建小样本一键脚本 |
| [src/writer.py](src/writer.py) | `max_review_attempts` 重命名 + 兼容旧键 |
| [config/agents.yaml](config/agents.yaml) | `rewrite_max` → `max_review_attempts` |
| [tests/test_writer_rewrite_loop.py](tests/test_writer_rewrite_loop.py) | 跟随重命名，断言不变 |
| [tests/test_preflight.py](tests/test_preflight.py) | 新建，6 条 |
| [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) | 更新 preflight 与 max_review_attempts 说明 |
| [README.md](README.md) | 加 preflight 与 real_smoke 章节 |

## 不在本轮范围

- B2 debate 结构化投票
- B3 rolling summary 升级为结构化伏笔追踪表
- C2 增量 compress
- A4 splitter confidence 字段
- 真实模型 API 联调本身——本轮只做拦截与脚手架，真模型按钮由用户人工按

## Notes

`real_smoke.sh` 默认在 mock 模式跑通，作为日常 sanity check；切真模型只需要改 `.env` 中 `OPENAI_MODEL` 后再跑同一个脚本，preflight 会自动从"WARN: mock"切到检查 API key/base_url。这样真实跑模型这件事降级成"改一行 .env + 跑一个脚本"，最大化一致性。

`max_review_attempts` 的兼容 fallback 计划只保留一轮，下一轮（004）开始硬要求新键。
