# Iteration 055 — 真模型驱动器加固专项（计划稿 v3 · 审核修正版）

> 承接 iter054「深起点续写」mock 段收官（986 单测绿、diff oracle 逐字节证毕封口正确）。本档为 **2026-06-17 审核** 后的修正版——逐条核对 v2 草案对 `llm_client.py` / `extractor.py` / `config.py` 的 file:line 断言，发现 **3 处与现状不符**（含 1 处会让核心 track A 静默失效），经用户拍板 2 个调参决策后定稿。

## 拍板与审核修正

**拍板（用户，2026-06-17）**：① iter055 主轴 = **真模型驱动器加固专项**，capstone 本轮顺延；② 未来 capstone 语义口径 = **自由生成 30+ 章长程续写**（B1 推荐，不受原著素材量约束）→ 故驱动器按**长程规格**加固。

**审核三处修正（2026-06-17，逐行复核 + 用户拍板）**：

1. **【最关键】Track A 按 v2 字面实现会静默失效** → 已修。v2 说把 `request_timeout: 120` 放 `models.yaml` **default 块**、靠 `config.py:140-144` "自动透传"。但那段 `**{...}` **只透传 `task_cfg` 的 key、不含 default 块的 key**（`config.py:142` `for key, value in task_cfg.items()`），而 `request_timeout` 又没像 `retry_attempts`（`config.py:134`）那样被显式映射 → `self.config.get("request_timeout")` 恒为 `None`，超时永不生效。**修法**：在 `get_model_config` 显式映射 `request_timeout`（读 `default`，因 `default.update(task_cfg)` 故 task 块可覆盖），并加 `LLM_REQUEST_TIMEOUT` env 覆盖。

2. **Track B 前提是错的** → 已纠正。v2 说 `retry_attempts` 缺省 =1「默认根本不重试」。但 `models.yaml:7-8` default 块写死 **`retry_attempts: 5`、`retry_backoff_seconds: 2`**——`config.py:134` 的 `,1)` fallback 仅在 key 缺失时生效，而 key 存在=5。**真实运行一直重试 5 次（线性 2/4/6/8s）**。Track B 的两个改动（指数退避、transient 分类）依然有价值，但"加 `retry_attempts: 3`"实为 **5→3 的下调**。

3. **全局 120s 超时会误杀长生成** → 已改分任务。120s 放 default 块对**所有** task 生效，但 `write`（max_tokens 8000）、尤其 `plot_planner`（max_tokens 16000 / gpt-5.5，`models.yaml:52-56`）合法生成可能 >120s → 被超时打断 → 重试烧钱。

**用户拍板两个调参值（2026-06-17）**：
- **超时 = 分任务**：`extract`/`review`/`compress`/`debate`/`premise_expand` 继承 default **120s**；`write` **240s**；`plot_planner` **300s**。
- **`retry_attempts` = 3**：配合新 per-call 超时把单 step 最坏耗时从 5×timeout 压到 3×timeout。

## 根因（v2 诊断已逐行证实）

iter054 真模型段续写 ch1-3 冒烟**跑挂**，根因不在续写逻辑，而在驱动器健壮性：

- **LLM 调用无 per-call 超时**（已核 `llm_client.py:184-189` kwargs 确无 `timeout`）：aetherheartpool 中转站偶发挂请求 / Cloudflare Tunnel 宕机（Error 1033/530）时，litellm 调用**永久阻塞**。**关键**：无超时 → 首个调用永不返回、永不抛异常 → 既存的 5 次重试**根本不触发**。`book_driver` 的 180min wall-clock 是 per-step 兜底，救不了单个卡死的 call。
- **长章分块极慢**：longzu 章 20-30K 字，超 `chunk_threshold_chars`（24000）走 3 子调用，拥堵下实测 967s/章；30K 仍在 128K context 内，绕分块单调用快得多。
- **健壮 extract 驱动是 /tmp 临时脚本**（已删）：流式进度 + 每章超时重试 + 断点续跑 + 绕分块，每次实跑临时手写，应固化进 `src/`。

**预期产出**：把"实跑能扛中转站抖动、长章不卡、断点能续"从临时脚本做成 `src/` 机制；并用加固后驱动器**顺带补完 iter054 欠的续写 ch1-3**（拿它当压力测试载体）。

## 分轨实施（依赖 A→B，C 独立，D 收口；每轨独立 commit）

### 轨 A — LLM per-call 超时（治本点①）· 纯 mock
- `src/config.py` `get_model_config` 返回 dict **显式映射** `request_timeout`：`"request_timeout": _env_float("LLM_REQUEST_TIMEOUT", _safe_float(default.get("request_timeout", 0), 0))`（**0 = 关闭，字节兼容旧行为**；env 优先，便于实跑现场调旋钮）。
- `src/llm_client.py` `complete_text` kwargs（`:184-189`）+ `ping` kwargs（`:254-263`）加 `if self.config.get("request_timeout"): kwargs["timeout"] = float(self.config["request_timeout"])`（`>0` 才加 → 未配时不含 timeout key，逐字节兼容）。
- `config/models.yaml`：default 块加 `request_timeout: 120`；`tasks.write` 加 `request_timeout: 240`；`tasks.plot_planner` 加 `request_timeout: 300`。
- **净改**：1 config 映射 + 2 处 kwargs（各 1 行）+ 3 条 yaml；零新函数（`_env_float`/`_safe_float` 已存在 `config.py:187`/`:208`）。
- **R9**：`drop_params=True`（`llm_client.py:73`）不丢 `timeout`（litellm 顶层支持参数）。

### 轨 B — 指数退避 + transient 分类重试（治本点①配套）· 纯 mock
现状默认重试 5 次但**线性退避无分类**（任何异常包括 schema/context 错都空耗 5 次 ≈ 20s sleep），须治本：
- `src/llm_client.py` 新增模块级 `_is_transient(exc)`：**鸭子判定**——`isinstance(exc, LLMContextOverflowError)` 显式返回 `False`；否则 `type(exc).__name__ in {Timeout, APITimeoutError, APIConnectionError, ServiceUnavailableError, RateLimitError, InternalServerError}` 或错误串含 `530/1033/502/503/504/timeout/tunnel/cloudflare`（小写匹配）。用类名+串关键词而非 `isinstance(litellm.X)`，避开 litellm 跨版本类名漂移（requirements 未 pin）。
- 退避公式（`:224`）改 `min(base * 2**(attempt-1), cap) + random.uniform(0, jitter)`（`import random`），`base`=`retry_backoff_seconds`、`cap`=`retry_backoff_cap_seconds`、`jitter`=`retry_backoff_jitter_seconds`。
- 分支（`:223`）：`if attempt < attempts and _is_transient(last_exc): sleep` `else: break`——schema/context 错**立即抛、不空耗** attempts。**保留** cache 降级 `continue` 路径（`:218-222`）在 transient 判定之上不动。
- `config/models.yaml` default：`retry_attempts: 5→3`（用户拍板）、加 `retry_backoff_cap_seconds: 30`、`retry_backoff_jitter_seconds: 1`（`retry_backoff_seconds: 2` 沿用为 base）；`config.py` 用 `_safe_float` 映射两个新 key（仿 `:135`）。
- 铁律④兼容：mock 在 `complete_text:164-168` 短路于重试循环前，故 mock 路径逐字节不变、verify.sh 不受影响。

### 轨 C — 绕分块/长章单调用（治本点②）· 纯 mock
加 `chunk_bypass_max_chars`：`threshold < len(text) <= bypass_max` 走单调用，超过才回退 3 子调用（保留超长章安全网）。
- `src/extractor.py:55-64 _extract_settings` 加 `"chunk_bypass_max_chars": int(task_cfg.get("chunk_bypass_max_chars", 0))`（`_extract_settings` 直读 `load_config("models.yaml")` 的 `tasks.extract`，不经 `get_model_config`，故 task key 直达，无需 config.py 改）。
- `src/extractor.py:234` `_extract_chapter_data`：`bypass_max = int(settings.get("chunk_bypass_max_chars", 0))`（**`.get` 不下标**——现存 `test_extractor_chunking.py:45-49` 手构 settings 无此 key，下标会 KeyError）；`effective_threshold = max(threshold, bypass_max)`；`if len(text) <= effective_threshold:` 走单调用。`bypass_max=0` → effective=threshold → 逐字节兼容旧行为。
- `config/models.yaml tasks.extract` 加 `chunk_bypass_max_chars: 48000`（覆盖 20-30K longzu 章，仍 << 128K×0.9）。
- 护栏：`_check_context`（`llm_client.py:515-521`，调用点 `:163` 先于重试循环）兜底——bypass 设太大撑爆即抛 `LLMContextOverflowError`，轨 B 不会瞎重试，直接暴露配置错。

### 轨 D — 健壮 extract 驱动固化（治本点③）· mock + 实跑入口
A/B/C 落地后 `extract_all` 已具「断点续跑(`:373` `out_path.exists() and not force`) + 每章隔离(`:390-424`) + call 级超时重试 + 绕分块」，轨 D 只补「流式进度 + 一键入口」，**不重写循环**：
- `src/extractor.py` 加 `import time`；`extract_all`（`:336`）加参 `no_chunk: bool=False`（设 `extract_settings["chunk_bypass_max_chars"]=10**9` 复用同一 effective_threshold 旋钮、强制单调用）、`per_chapter_attempts: Optional[int]=None`（**整章级**重试，区别于轨 B 的 call 级——分块合并失败 call 级救不了，包住 `_extract_chapter_data`）；每章发 `log_event("extract","progress", {done/total/chapter_id/elapsed_ms})`（`state.py:22` `**payload` 支持任意载荷）。
- 加 `extract_window(chapter_ids, *, no_chunk=False, resume=True)` 薄封装，正式替代 `/tmp/extract_window.py`（`resume=True` → `force=False`，勿与 raise_on_failure 的 force 搅在一起）。
- `main.py` extract parser（`:117-120`）加 `--no-chunk/--per-chapter-attempts/--chapter-ids`；handler（`:448`）透传。`rebuild-for-start`：parser（`:157`）加 `--no-chunk`，`auto_pipeline.rebuild_for_start`（`:253`）加 `no_chunk` 参并透传到 extract_all（`:312`）。
- 复用 `retry_failures`（`:444`，注意它用 `force=True`）、`raise_on_failure`（`:341`，04eb8a0 已落地）。

## 关键设计决策（精简）

| 决策点 | 结论 | 理由 |
|---|---|---|
| per-call 超时实现 | **litellm 原生 `timeout=`**，禁用 signal | `signal.alarm` 只主线程可用（driver 子进程/web daemon 线程必崩）；线程 wrapper 杀不掉底层 socket |
| **request_timeout 解析（审核修正）** | **`get_model_config` 显式映射**（非靠 default 块透传） | `config.py:142` 只透传 `task_cfg` key、不含 default 块；不显式映射则恒 None、超时静默失效 |
| **超时粒度（用户拍板）** | **分任务**：extract/review 120 · write 240 · plot_planner 300 | 全局 120 误杀 16K-token plot_planner / 8K write 长生成 → 重试烧钱；显式映射后 task 块可覆盖 default |
| 重试放哪层 | **llm_client 为主（call 级）+ extractor 补整章级** | call 级 transient 全 task 共性放最底层；整章重试管分块合并失败；driver per-step 180min 不动 |
| **retry_attempts（用户拍板）** | **5→3** | 配新 per-call 超时把单 step 最坏耗时从 5×timeout 压到 3×timeout；指数退避+jitter 已补抗抖动 |
| 退避策略 | **指数 + 上限 30s + 抖动** | 530/1033 是 provider 过载，线性退避加剧拥堵；指数+jitter 错峰契合中转站恢复后拥堵 |
| 错误分类 | **仅 transient 重试**，schema/context/JSON 立即抛 | 非 transient 重试纯浪费且掩盖 bug（现状空耗 5 次 ≈ 20s） |
| 绕分块实现 | **`chunk_bypass_max_chars` 上限 + `--no-chunk` 旗标** | 同一旋钮不同刻度；保留 >128K 超长章分块安全网；`_check_context` 兜底 |
| 驱动固化形态 | **增强 extract_all + 薄封装**，不新建模块 | extract_all 已有续跑/隔离/可见性，新模块=重复造轮+二次真源 |

## Acceptance

### mock 段（门槛，纯 mock 隔离 / 不真联网 / 不真 sleep）
- 全量回归零失败、每提交独立 `verify.sh` exit 0、`python3 -m unittest discover -s tests` 全绿。
- 钉死项（逐项 mock 测）：
  - **轨 A**：`patch litellm.completion` 捕获 kwargs，断言 extract task 含 `timeout==120`（验显式映射真生效）；write task `timeout==240`；未配（request_timeout=0）时**不含** timeout key（字节兼容）；ping 同测。
  - **轨 B**：transient（Timeout/530/1033）触发重试且 `attempt==2`；非 transient（如普通 ValueError）**立即 break、completion 只调 1 次**；`_is_transient(LLMContextOverflowError())==False` 单测；耗尽 attempts 抛 RuntimeError；退避序列指数封顶（patch `time.sleep` 记 delay、jitter 注 0）。**测试须 `patch is_mock→False` 否则短路在 `:164-168` 测不到重试。**
  - **轨 C**：30K + bypass=48000 → call `count==1`（对比 `test_extractor_chunking.py:53` 的 `==3`）；60K → `==3`；bypass 缺省/0 → 旧行为（30K→3）。
  - **轨 D**：预置 ch001.json + force=False → 秒跳过；`no_chunk=True` 单调用；progress 事件含 done/total/chapter_id；per_chapter_attempts 整章重试。

### 真模型段（≤¥20，需 `CONFIRM_REAL_MODEL_SMOKE`，分步授权，搭车补 iter054 欠账）
载体复用 iter054c 深起点 `longzu_2_ch001`（克隆已被 054 删除 → 先免费重跑 ingest-to-start 重建）。

| 项 | 方法 | 成本 |
|---|---|---|
| V1 绕分块测速 | 同一 ~25K 长章 `--no-chunk` vs 3 子调用，对比 progress elapsed_ms，期望 « 967s | ~¥0.3 |
| V2 超时生效 | 临时 `LLM_REQUEST_TIMEOUT=5` 故意触发→ ~5s 即 Timeout 重试（非无限挂） | ~¥0 |
| V3 退避实证 | `llm_calls.jsonl` 看 attempt 时间戳间隔呈指数 | 搭车 |
| V4 断点续跑 | 补提取跑一半 Ctrl-C → 重跑断言已提取章秒跳过（mtime 不变） | ~¥0 |
| V5 rebuild + 续写 ch1-3 | `rebuild-for-start --no-chunk` → `drive-book start --chapters 3`，验收 low 档 Approve≥2/3 + panel≥6.5（补 iter054 欠账） | ≤¥15 |

先 V1-V4（<¥3）验证加固生效，再放 V5。加固后 530 损耗应显著低于 iter054c 的 ¥2.93。**真模型段需用户显式授权，本轮交付只到 mock 段收官 + 交接。**

## 暗礁预警
- **R2**：litellm `timeout=` 是单次请求超时；**write/plot_planner max_tokens 大、非 stream 长生成**可能逼近 timeout——故 write 240 / plot_planner 300 给足余量；extract（max_tokens 3500）120 较安全。
- **R3**：断点续跑幂等 key = 文件存在（`:373`）；`force=True`（reextract/retry_failures）会重提取——`extract_window(resume=True)` 必须 `force=False`。
- **R8**：`_is_transient` 用鸭子判定（类名 + 错误串），不 `isinstance(litellm.X)`（跨版本类名漂移）。
- **R-C**：`_extract_chapter_data` 读 bypass 用 `settings.get(...,0)` 非下标，否则现存 chunking 测试 KeyError。
- **铁律**：本轮**零 schema 改动**（entity key_facts/timeline 全顺延，绝不与真模型同轮改）；收官**只 commit 不 push**（跨仓库 push 被分类器硬拦，最后一步交用户手动）。

## 不在本轮范围
- capstone 本体（30+ 章长程续写）顺延——本轮只按长程规格加固驱动器。
- entity timeline / key_facts schema（052 起反复顺延）。
- Aeloon 集成线（§9.5 workspace 安装坑③等，另轮）。
- 中转站/Tunnel provider 侧治理（只做客户端加固扛抖动）。
- driver per-step 超时/状态机重构（180min 兜底不动）。

## 关键文件
- `src/llm_client.py`（轨 A/B：per-call timeout + 指数退避分类重试，`complete_text:148-227` / `ping:229-272`）
- `src/extractor.py`（轨 C/D：绕分块 `_extract_chapter_data:234` + `extract_all:336` 流式/no_chunk/续跑）
- `src/config.py`（轨 A/B：`get_model_config` 显式映射 request_timeout + 两个 backoff key，仿 `:134-135`）
- `config/models.yaml`（`request_timeout` 分任务 / `retry_attempts:3` / `retry_backoff_cap`/`jitter` / `chunk_bypass_max_chars`）
- `main.py` + `src/auto_pipeline.py`（轨 D：extract/rebuild-for-start CLI 旗标 + no_chunk 透传）
- 收官回填 `docs/AGENT_HANDOFF.md`

## 验证（end-to-end）
1. 每轨改完跑 `python3 -m unittest discover -s tests`（mock，秒级）+ `bash scripts/verify.sh`（exit 0）。
2. 新增超时/重试/绕分块/续跑 mock 测试随对应轨提交，确保字节兼容（无配置时旧行为不变）。
3. 真模型段经用户 `CONFIRM_REAL_MODEL_SMOKE` 授权后，按 V1→V5 分步跑；先 <¥3 验加固，再 ≤¥15 补续写 ch1-3。
