# Iteration 002 - Real Model Hardening A+B1+C1

## Context

MVP 工程闭环已在 mock 模式跑通。切真模型前，需要处理真实上下文窗口、长章节截断、reviewer reject 反馈闭环和 prompt cache 复用。

## Plan

- A1: rolling summary 按中文句末边界截断，并限制 rolling summary 历史长度。
- A2: LLM 调用记录 request hash、prompt/response chars、token 计量、context overflow。
- A3: 长章节 chunked extraction，失败不写半成品，成功后合并结构化结果。
- B1: reviewer issues 结构化，writer 重写 prompt 注入上一轮 reject 反馈，加入 rewrite 硬上限和阻塞原因留存。
- C1: writer 的 knowledge/outline/system prompt 走 cache segment，LLM 日志记录 provider cache usage。

## Acceptance

通过：

```bash
PYTHONPYCACHEPREFIX="$PWD/.pycache" python3 -m unittest discover -s tests -v
```

当前测试数：55。

通过：

```bash
bash scripts/verify.sh
```

验收后状态摘要：

- manifest: 101 chapters, 0 errors, 2 short-chapter warnings.
- extract: 2 JSON files, 0 failures.
- write: 1 draft, 1 meta, 0 failures.
- review: 4 reports.
- cost estimator now reports logged prompt/response tokens and cache token fields from `logs/llm_calls.jsonl`.

## Notes

本轮跳过 A4/B2/B3/C2/D，等真实小样本跑出具体失败样式后再排下一批。
