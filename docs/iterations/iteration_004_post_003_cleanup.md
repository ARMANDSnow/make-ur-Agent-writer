# Iteration 004 - max_review_attempts 硬要求 + Splitter Confidence

## Context

Iteration 003（[iteration_003_real_model_preflight.md](./iteration_003_real_model_preflight.md)）做完真模型前的工程加固和 preflight，并把 5 项明确推迟到下一轮：B2 debate 结构化投票、B3 rolling summary 伏笔表、C2 增量 compress、A4 splitter confidence、`max_review_attempts` 兼容 fallback 清理。

003 末尾留下两个尾巴：

1. `max_review_attempts` 与 `rewrite_max` / `max_rewrites` 的兼容 fallback 计划只保留一轮，004 起硬要求新键。提交前 [src/writer.py:36](../../src/writer.py) 仍是 `agent_cfg.get("max_review_attempts", agent_cfg.get("rewrite_max", 2))`，函数签名也保留了 `max_rewrites: Optional[int] = None` 旧别名，并且 [tests/test_writer.py](../../tests/test_writer.py)、[tests/test_manual_facts.py](../../tests/test_manual_facts.py)、[README.md](../../README.md) 仍有旧名残留。
2. `data/chapter_manifest.json` 的章节 entry 没有任何"这条 heading 多可信"的信号。当前 splitter 是确定性 regex + dedup，所有输出 entry 一视同仁，下游（preflight、未来人工抽检策略）无从判断哪些章节边界值得复核。低置信度章节出现在两类场景：早期密集命中区（疑似目录残留）的幸存者；以及切出来字符数极低的 entry（疑似把目录条当成了正章）。

本轮目标：**清掉 003 的尾巴 + 给 manifest 加最小可用的 confidence 信号**。不动 B2/B3/C2 与真模型联调，等真模型小样本跑出具体翻车样式后再排下一轮。

## Plan

### P1. `max_review_attempts` 硬要求

[src/writer.py](../../src/writer.py) `write_chapters` 函数：

- 删除参数 `max_rewrites: Optional[int] = None`。
- 删除 `agent_cfg.get("rewrite_max", 2)` 这层 fallback。改为：

```python
if "max_review_attempts" not in agent_cfg:
    raise KeyError("agents.yaml missing required key 'max_review_attempts'")
configured_attempts = int(agent_cfg["max_review_attempts"])
rewrite_limit = int(max_attempts) if max_attempts is not None else configured_attempts
```

- 全仓 grep 后同步替换所有调用方（test_writer.py / test_manual_facts.py 的 `max_rewrites=1` → `max_attempts=1`），README.md 删除"旧 rewrite_max 仅兼容一轮"的描述。

### P2. preflight 加 agents.yaml 必填键校验

[src/preflight.py](../../src/preflight.py) 新增 `_check_agents_config(fatal)`：复用 `load_config("agents.yaml")`，缺 `max_review_attempts` 或类型不是正整数 → FATAL，文案与 writer.py 抛出的 KeyError 对齐，便于 grep。调用点插在 `_check_env` 之后、`_check_context_limits` 之前。

### P3. A4 splitter confidence

[src/schemas.py](../../src/schemas.py) `ChapterManifestEntry` 新增 `confidence: float = Field(default=1.0, ge=0.0, le=1.0)`。默认 1.0 保证旧 manifest 反序列化兼容。

[src/chapter_splitter.py](../../src/chapter_splitter.py) 新增纯函数：

```python
def _heading_confidence(title: str, char_count: int, in_dedup_risk_zone: bool) -> float
```

三档信号取 min 后保留 2 位小数：

| 信号 | 命中 | 分数 |
|------|------|------|
| pattern | `第N章` / `第N幕` | 1.0 |
| pattern | `序章` / `序幕` / `楔子` / `尾声` | 0.9 |
| length | `char_count >= 1500` | 1.0 |
| length | `500 <= char_count < 1500` | 0.7 |
| length | `char_count < 500` | 0.4 |
| position | 不在早期密集区 | 1.0 |
| position | 早期密集区（首 100 行命中 ≥ 5）幸存者 | 0.7 |

`split_file` 改造：保留 `candidate_headings` 既有签名，在 split_file 内重算一次 raw candidates，判断早期密集区（first-100-line 命中 ≥ 5），对 start_line ≤ 100 的 entry 标记 `in_risk_zone=True`，写入 confidence。

### P4. CLI 与报告侧曝露 confidence

[src/observability.py](../../src/observability.py) `check_manifest_integrity` 增加：

- 校验 confidence 必须是数字且 ∈ [0, 1]，越界报 errors。
- 收集 confidence < 0.6 的 chapter，作为 `low_confidence_chapters` 字段返回。

`render_manifest_check`：在头部 summary 加 `low_confidence_chapters: N`，末尾加「Low Confidence (top 5)」分组列出 chapter_id + confidence。

[src/preflight.py](../../src/preflight.py) `_check_longest_chapter` 区段 INFO 新增一行：`Manifest confidence: low_confidence_chapters=N (threshold<0.6)`。

### P5. 测试

| 文件 | 新增/改动 |
|------|---------|
| [tests/test_writer.py](../../tests/test_writer.py) | `max_rewrites=1` → `max_attempts=1`（2 处） |
| [tests/test_manual_facts.py](../../tests/test_manual_facts.py) | 同上（1 处） |
| [tests/test_preflight.py](../../tests/test_preflight.py) | +1：patch `src.preflight.load_config` 让 agents.yaml 缺 `max_review_attempts`，断言 FATAL 命中且文案包含 `max_review_attempts` |
| [tests/test_splitter.py](../../tests/test_splitter.py) | +4：`_heading_confidence` 长正章=1.0、短章节<=0.4、风险区幸存者<=0.7、`split_file` 实际 entry 拿到 1.0 |
| [tests/test_manifest_report.py](../../tests/test_manifest_report.py) | +1：低置信度 entry 进 `low_confidence_chapters` 列表，渲染包含 `low_confidence_chapters: 1` 与 `c1: confidence=0.4` |

## Acceptance

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
# Ran 68 tests, OK

bash scripts/verify.sh
# OK（全流水线无报错）

python3 main.py preflight
# PREFLIGHT: warn, FATAL: none

python3 main.py split && python3 main.py check-manifest
# OK；新输出包含 low_confidence_chapters 字段

# Confidence 分布抽样
python3 -c "import json; from collections import Counter; m=json.load(open('data/chapter_manifest.json')); print(Counter(round(e['confidence'],1) for e in m))"
# Counter({1.0: 94, 0.7: 4, 0.9: 3})

# FATAL 路径手测：
python3 -c "import json,pathlib; p=pathlib.Path('config/agents.yaml'); d=json.loads(p.read_text()); d.pop('max_review_attempts'); p.write_text(json.dumps(d,ensure_ascii=False,indent=2))"
python3 main.py preflight   # PREFLIGHT: fail，FATAL 命中 "agents.yaml missing required key 'max_review_attempts'"，退出码 1
git checkout config/agents.yaml
```

## Implementation Notes

- 全仓 grep 找出 5 处旧名残留：writer.py + 2 测试文件 + README + AGENT_HANDOFF + iteration_003 历史记录。本轮替换前 4 个，iteration_003 作为历史档案不动。
- splitter 风险区判定刻意保留 `candidate_headings` 原签名 —— 它在 [tests/test_splitter.py](../../tests/test_splitter.py) 被直接调用，签名不动可避免破坏现有 toc 截断 / dedup 测试。代价是 `split_file` 内会重算一次 raw candidates，章节量级（百级）下成本可忽略。
- `_check_agents_config` 在 preflight 中放在 `_check_env` 之后、`_check_context_limits` 之前 —— 优先环境与配置类 FATAL 集中曝露，再做执行型检查。
- `check_manifest_integrity` 把 confidence 越界算作 error 而非 warning，因为 entry 是 pydantic 写出的，越界只能来自手工编辑 manifest，应当显式拒绝。
- `confidence` 字段反序列化兼容验证：旧 manifest 没有该字段时 pydantic 用默认 1.0 填空，preflight `_check_longest_chapter` 内 `entry.get("confidence", 1.0)` 也兜底。新 manifest 跑了一次 `python3 main.py split` 后 101 章 confidence 分布为 1.0×94 / 0.7×4 / 0.9×3，无低置信度章节。

## Acceptance Result

通过：

```
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests
# Ran 68 tests in 72.083s, OK

bash scripts/verify.sh
# OK

python3 main.py preflight
# PREFLIGHT: warn, 0 FATAL
# WARN: longest chapter chunked extraction（已知）+ global_facts 未写

python3 main.py check-manifest
# - low_confidence_chapters: 0
# Errors/Warnings 均沿用 003 行为

# FATAL 手测
python3 main.py preflight   # 改坏 agents.yaml 后
# PREFLIGHT: fail
# FATAL: agents.yaml missing required key 'max_review_attempts' or value is not a positive integer.
# exit code 1
```

## 文件变更汇总

| 文件 | 改动 |
|------|------|
| [src/writer.py](../../src/writer.py) | 删 `max_rewrites` 参数、`rewrite_max` fallback；缺键 raise KeyError |
| [src/schemas.py](../../src/schemas.py) | `ChapterManifestEntry` 新增 `confidence: float = 1.0` |
| [src/chapter_splitter.py](../../src/chapter_splitter.py) | 新增 `_heading_confidence`；`split_file` 计算并写入 confidence |
| [src/preflight.py](../../src/preflight.py) | 新增 `_check_agents_config` FATAL；`_check_longest_chapter` 加低置信度 INFO |
| [src/observability.py](../../src/observability.py) | `check_manifest_integrity` 校验 confidence 范围 + 收集 low_confidence；render 同步 |
| [tests/test_writer.py](../../tests/test_writer.py) | `max_rewrites=1` → `max_attempts=1` |
| [tests/test_manual_facts.py](../../tests/test_manual_facts.py) | 同上 |
| [tests/test_preflight.py](../../tests/test_preflight.py) | +1：缺 `max_review_attempts` FATAL |
| [tests/test_splitter.py](../../tests/test_splitter.py) | +4：confidence 分档 + split_file 写入验证 |
| [tests/test_manifest_report.py](../../tests/test_manifest_report.py) | +1：低置信度收集与渲染 |
| [README.md](../../README.md) | 改 `max_review_attempts` 描述：必填键，缺失即报错；删除 `rewrite_max` 兼容字样 |
| [docs/AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | 追加 iteration 004 结果；删除 Next Candidates 中已完成项 |
| [docs/iterations/README.md](./README.md) | 索引追加第 4 条 |
| 本文件 | 新建 iteration 004 记录 |

## 不在本轮范围

- B2 debate 结构化投票
- B3 rolling summary 升级为结构化伏笔追踪表
- C2 增量 compress
- 真实模型 API 联调（仍由用户人工切 `.env` + 跑 `scripts/real_smoke.sh`）

## Notes

- 当前 manifest 在 mock 模式下没有低置信度章节（最低 0.7，原因：龙族第三部下少量"序幕"类标题命中 0.9）；如果未来引入新卷出现疑似目录残留，confidence 会自动降到 0.7，preflight 与 check-manifest 都会曝露。
- writer.py 与 preflight.py 的 FATAL 文案保持一致 —— `agents.yaml missing required key 'max_review_attempts'`，便于运维同时 grep 日志和 preflight 输出定位问题。
- `_heading_confidence` 是纯函数、零外部依赖、deterministic；任何置信度策略调整（阈值、新信号）只需要改这个函数与少量测试，不会扩散。
- 下一轮（005）候选：B2 debate 结构化投票（agent 输出从自由文本升级为 `{position, reason}`），或在用户跑过真模型小样本后按真实翻车样式排优先级。
