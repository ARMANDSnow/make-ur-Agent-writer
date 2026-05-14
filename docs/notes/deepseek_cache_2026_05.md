# DeepSeek Cache 调研 - 2026-05

## 当前 Shape

项目在 [src/llm_client.py](../../src/llm_client.py) 的 `_prepare_messages` 中给可缓存段添加 message-level 字段：

```json
{"cache_control": {"type": "ephemeral"}}
```

该字段目前只在 `cache_enabled=true` 的 task 生效。现有配置里 `write` 开启，`debate` 未开启；因此 iteration 006 debate smoke 的 cache write/read 主要来自 provider 自动缓存返回字段，而不是项目主动给 debate 注入 cache segments。

## LiteLLM 透传行为

本机 LiteLLM DeepSeek adapter 位于：

`/Users/dingyuxuan/Library/Python/3.9/lib/python/site-packages/litellm/llms/deepseek/chat/transformation.py`

观察点：

- DeepSeek adapter 继承 OpenAI GPT transform，没有看到专门消费 `cache_control` 的 DeepSeek 分支。
- adapter 默认 api base 是 `https://api.deepseek.com/beta`，但项目显式传入 `.env` 的 `OPENAI_BASE_URL` 时，LiteLLM 会用该 base 并拼接 `/chat/completions`。
- LiteLLM `utils.is_cached_message` 注释表明 `cache_control` 是 Anthropic/Gemini context caching 形态，不是 DeepSeek 专用协议。

## DeepSeek 端点要求

DeepSeek 官方 Context Caching 文档说明缓存自动启用，不需要修改代码；命中状态通过 response usage 的 `prompt_cache_hit_tokens` 与 `prompt_cache_miss_tokens` 返回：

- [Context Caching](https://api-docs.deepseek.com/guides/kv_cache)
- [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)

文档强调命中依赖“后续请求完整复用此前已持久化的前缀”，且缓存是 best-effort，不保证 100% 命中。`/beta` 端点主要是 FIM / prefix completion 等 beta 功能要求；Context Caching 文档本身未要求切 `/beta`。

## 受控实验

实验方式：

- 使用 `LLMClient("write")`，因为 `write.cache_enabled=true`。
- 构造完全相同的两次 prompt。
- `cache_segments[0]` 设为长 system prefix 且 `cache=true`。
- 第二次调用紧跟第一次。

结果，`logs/llm_calls.jsonl` 最后两条：

```text
call 1: status=ok, prompt_tokens=504, response_tokens=1, cache_read_tokens=0, cache_write_tokens=504
call 2: status=ok, prompt_tokens=504, response_tokens=1, cache_read_tokens=0, cache_write_tokens=504
```

两次 request hash 完全相同，但第二次仍没有 `cache_read_tokens`。

## 结论

当前路径下没有观察到 DeepSeek cache read 命中。更可能的解释是：

- DeepSeek disk cache 的命中/持久化是 best-effort，短间隔完全相同 prompt 也未必立即 read；
- 或者 LiteLLM / DeepSeek 对 `cache_control` 不做 Anthropic 式显式缓存语义，DeepSeek 只按服务端自动 prefix cache 计费；
- 或者 `.env` 显式 base URL 与 LiteLLM DeepSeek 默认 `/beta` 行为不同，但官方 Context Caching 文档没有把 `/beta` 作为缓存前提。

## 下一步建议

Iteration 008 先不改代码，建议加 preflight WARN 或 cost report note：DeepSeek cache read may remain 0 even when write/miss tokens are logged. 如果要继续查，下一轮用 3 次同前缀、间隔 60 秒的实验，比本轮 2 次紧邻调用更贴近官方“common prefix persistence”规则。
