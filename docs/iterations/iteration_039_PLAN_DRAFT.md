# Iteration 039 — WebUI 小说续写真实链路修复

## Context

**为什么这一轮做这个**：iter038 解决了 unittest `OK (skipped=6)` 的心智负担后，codex 用真实 `.env` 模型配置对前端跑了一次"模拟普通用户"的探针（covered onboarding / 续写 / jobs / 错误链路），结果发现 **短路径 UI 可操作，但真实续写链路在 job 状态展示、预算控制、失败落盘上有产品级 bug**。

**用户视角的问题**：
- 提交 write-book 后前端进度卡在 10%，但后端已经跑了 1 次 write + 6 次 review —— 用户以为卡死了
- job 失败后 `chapter_02.md` 完全没落盘，前面真实模型烧掉的 tokens 全废
- recent jobs 把还在跑的 running job 误标 lost，前端体感"任务消失"
- plan-chapters blocked 时前端只显示 "blocked / 100%"，不告诉用户 `outline_missing`，必须查 API
- `budget_cny=5` 不能在章内止损，可能多烧 1 整章

**iter039 目标**：让"真实用户用真实模型在前端跑完小说续写全流程（大纲生成 / 续写 / debate / rewrite）"成为可观测、可恢复、可控制的体验。**验收基准 = 用龙族第一部前 N 章作为续写起点跑通**，最低标准是所有 web 功能正常实现。

## 修复清单

### P0-A · recent_jobs 误标 lost（根因：第二个 if 写错）

**位置**：`src/web/jobs.py:148-153`

**当前 bug**：
```python
if snapshot.get("status") in {"pending", "running"}:
    live = get_job(str(snapshot.get("job_id")))
    snapshot = live or snapshot
    if snapshot.get("status") in {"pending", "running"}:  # ← live 是 running 也命中
        snapshot["status"] = "lost"
```

**修复**：第二个 if 改为"内存里查不到 → 才算 lost"：
```python
if snapshot.get("status") in {"pending", "running"}:
    live = get_job(str(snapshot.get("job_id")))
    if live is not None:
        snapshot = live  # 内存还在 = 还活着，保留 live 的实时 status/progress
    else:
        snapshot["status"] = "lost"
        snapshot["error"] = "worker process restarted before this job reached a terminal state"
```

**验收**：live running job 在 sidebar / jobs 页 / continue 页统一显示 running；只有 process restart 后内存里查不到时才显示 lost。新增单测覆盖两路分支。

---

### P0-B · 失败时 partial artifact 落盘（最高优先：真实 token 不能浪费）

**位置**：`src/writer.py write_chapters()` 主循环 + `src/book_runner.py run_write_book()` 外层

**当前 bug**：write_chapters 主循环 130-226 行没 try/except，attempt 循环里 LLM 流式中断 → 直接抛 → book_runner 也直接抛 → worker `_update(status="failed")` → 已生成的 draft 完全丢失，chapter_NN.md 不存在。

**修复**：
1. **writer.py**：在 attempt 循环里维护"当前最新 non-empty draft"。主循环加 try/except；异常时若有 draft，写到 `chapter_NN.partial.md` + `chapter_NN.failure.json`（含 attempt 数、last_error、draft sha256），然后重抛。
2. **book_runner.py**：在 chapter for-loop 外层加 try/except 包住 `write_chapters` + `review_target`。捕获后把已完成 chapters + 当前 chapter 的 partial 信息塞进 result，return `{"status": "failed", "chapters": written, "partial": {chapter, stage, draft_path, attempt}, ...}`，让 _summarize_result 也展示。
3. **jobs.py `_summarize_result`**（L433-444）：write-book 摘要加 `partial` 字段透传。

**验收**：模拟真实模型流式中断（mock client raise mid-stream），跑完后 `workspaces/<ws>/drafts/chapter_02.partial.md` + `.failure.json` 存在；前端 jobs 页能看到 "failed · partial draft saved → chapter_02.partial.md"。

---

### P0-C · write-book 细粒度 progress 回调

**位置**：`src/writer.py write_chapters()` + `src/book_runner.py:75`

**当前 bug**：progress 仅在 book_runner 章节边界回调（`chapter-{N}`, 0.1 + 0.8×(offset-1)/total）；writer 内部 attempt + review 循环对 progress 不可见，所以一章内 5-20s 的 LLM 调用 + 6 次 review 期间，前端进度条不动。

**修复方案**：
1. **writer.write_chapters 新增 `progress_cb` 参数**：签名 `Callable[[str, float], None]`，其中 fraction ∈ [0, 1] 表示**章内** sub-progress。
2. **writer 内部回调点**（最小集，避免噪音）：
   - 进入 attempt：`("write-attempt-{K}", 0.05)`
   - write 完 + lint pass：`("review-attempt-{K}", 0.50)`
   - review 完（每次）：`("review-done-attempt-{K}", 0.55 + 0.05×attempt)` 直到 max
   - polish 阶段（若启用）：`("polish", 0.85)`
   - 章节完成：`("finalize", 0.95)`
3. **book_runner 透传 + 映射**：
   ```python
   def _chapter_progress(sub_step, sub_fraction):
       chapter_base = 0.1 + 0.8 * (offset - 1) / total
       chapter_span = 0.8 / total
       progress(f"chapter-{chapter_no}/{sub_step}", chapter_base + chapter_span * sub_fraction)
   write_chapters(..., progress_cb=_chapter_progress)
   ```

**验收**：真实模型跑 1 章时，前端在 5-90 秒内能看到 `chapter-1/write-attempt-1 → review-attempt-1 → review-done-attempt-1 → ...` 的 current_step 切换，progress 单调递增。

---

### P0-D · 章内预算止损

**位置**：`src/book_runner.py:76,175`（当前章节边界检查）+ `src/writer.py` attempt/review 后

**当前 bug**：`estimate_cost_since(initial_log_lines)` 仅在章节循环开始和章节完成后调用，章内多次 LLM 调用累计超预算不会被中断。

**修复**：
1. 把 `estimate_cost_since` + `initial_log_lines` 作为 closure 包成 `budget_check_cb: Callable[[], float|None]`（返回当前 cost_cny，超预算时返回 None 给 writer 主循环用一个特殊信号）。更简单：定义 `class BudgetExceeded(RuntimeError)`，超预算时 `budget_check_cb()` 内部直接 raise；writer 在 attempt 循环 + review 循环里调用，让异常自然向上传播。
2. book_runner 外层 try/except `BudgetExceeded`，捕获后 `progress("budget_exceeded", 1.0)` + return budget_exceeded snapshot（含已写章节 + partial 信息）。
3. 配合 P0-B：BudgetExceeded 也走 partial artifact 落盘。

**验收**：预算 `budget_cny=1` 跑龙族续写，应在第 1 章 write 或 review 阶段触发 budget_exceeded（而非"等第 1 章整章完成后才发现"），且已 write 的 draft 通过 P0-B 落盘。

---

### P1-A · blocked / failed 时前端展示 result_summary.first_blocked

**位置**：`src/web/static.py:1721-1757`（pollJob）+ `2405-2446`（initJobs/jobs 页）+ `1700-1720`（sidebar）

**当前**：pollJob 第 1740-1750 行只读 `job.error`，完全不读 `job.result_summary.first_blocked.reason / error`。Jobs 页 initJobs L2425 同。

**修复**：
1. 新增 helper：
   ```js
   function jobBlockedDetail(job) {
     const fb = job.result_summary && job.result_summary.first_blocked;
     if (!fb) return null;
     return { chapter: fb.chapter, reason: fb.reason, error: fb.error, status: fb.status };
   }
   function jobFailureLine(job) {
     const detail = jobBlockedDetail(job);
     if (detail && (detail.reason || detail.error)) {
       return [detail.chapter ? `ch${detail.chapter}` : null, detail.reason, detail.error]
         .filter(Boolean).join(' · ');
     }
     return (job.error || '').split('\n')[0];
   }
   ```
2. pollJob：terminal alert + showToast 改用 `jobFailureLine(job)`，blocked 状态下优先 reason。
3. jobs 页：note 字段同步改用 jobFailureLine，并把 P2-A 一起做（可展开详情 / trace_id badge）。
4. sidebar：与 jobs 页一致。

**验收**：plan-chapters 触发 outline_missing 时，continue 页直接看到 "blocked · outline_missing"；write-book 失败时看到 "ch2 · network_error · stream interrupted"。

---

### P1-B · partial artifact 在前端有入口

**位置**：write-book 摘要 + chapters 页

**修复**：
1. _summarize_result write-book 增加 `partial` 字段（来自 P0-B）。
2. pollJob terminal 分支若 result_summary.partial 存在，渲染 "已保存 partial draft: <chapter_NN.partial.md>" 链接（指向 chapters 页或直接 GET `/api/workspace/<ws>/draft/<chapter>?variant=partial`，后者需新增路由）。
3. chapters 页 renderChapters 识别 `.partial.md` 变体，标 "partial / failure"。

**验收**：write-book 中途失败后，continue 页 alert 给出 partial 链接，点击能查看那一章已生成的部分。

---

## P2 收尾（视时间塞入；不阻塞 P0/P1 验收）

- **P2-A · Jobs 页 80 字截断 → 可展开详情**：`src/web/static.py:2425` 把 `.slice(0, 80)` 改成"折叠 + 展开按钮"；trace_id 单独显示为 `<code>` badge。
- **P2-B · sidebar 区分历史 lost vs 当前状态**：refreshRecentJobsSidebar 在 lost 行加 "(历史)" 标记 + 视觉降权（灰色），避免和当前 readiness 混淆。
- **P2-C · onboarding 加 budget/timeout/cancel**：wizard panel-progress 增加 cancel 按钮（POST `/api/workspace/<ws>/job/<id>/cancel`，需新增路由 + jobs._JOBS 取消标志）；auto-pipeline-greenfield 表单加可选 budget_cny 输入。

P2-C 涉及 backend 新路由；如果时间紧可独立切到 iter040。

---

## 关键文件清单

| 文件 | 改动 |
|---|---|
| `src/web/jobs.py` | recent_jobs lost 判定（L148-153）；`_summarize_result` write-book 加 partial（L433-444） |
| `src/book_runner.py` | 主循环 try/except；progress 透传 + sub-fraction 映射；budget_check_cb closure + BudgetExceeded |
| `src/writer.py` | `write_chapters` 新增 `progress_cb` + `budget_check_cb` 参数；attempt/review 循环 try + partial 落盘 |
| `src/web/static.py` | pollJob (L1721-1757) + initJobs (L2405-2446) + sidebar (L1700-1720)：blocked detail helper |
| `src/web/templates.py` | （P2-A）jobs 页 note 折叠展开；（P2-C）onboarding budget 输入 |
| `src/web/routes.py` | （P1-B）partial draft GET 路由；（P2-C）job cancel POST 路由 |
| `tests/test_web_jobs_recent.py`（新建） | recent_jobs lost 判定的两路单测 |
| `tests/test_writer_progress.py`（新建） | writer progress_cb 触发次数/顺序断言 |
| `tests/test_book_runner_partial.py`（新建） | mock 中断异常 → partial 落盘 |

## 已有可复用工具

- `cost_estimator.estimate_cost_since` —— 直接喂给 budget_check_cb，不要重写
- `paths.drafts_dir() / write_text_atomic` —— partial.md 落盘走现有原子写
- `chapter_status` —— partial 文件不破坏 approved 判定（确认 `.partial.md` 不在它的扫描列表里）
- `BookRunBlocked` —— 现有异常基类；BudgetExceeded 与之并列，jobs.py 已有 except 钩子可扩展

## 验收（顺序执行）

### 阶段 1 · 单测
```bash
.venv/bin/python -m unittest discover
```
基线必须保持 `OK (skipped=6)`，新增测试全 pass。

### 阶段 2 · mock 模型链路（无 token 成本）
- `OPENAI_MODEL=mock` 起 web，新建 workspace
- 注入 `WRITER_FORCE_FAIL=1` 跑 write-book，确认 partial.md + failure.json 落盘
- 跑 plan-chapters 制造 outline_missing，确认前端展示 reason
- 跑 write-book 多章节，观察 progress 是否细粒度跳动

### 阶段 3 · 真实模型 · 龙族第一部
- 素材来源：`workspaces/longzu/小说txt/龙族Ⅰ火之晨曦.txt`（786KB 完整本，约 24 章）
- 准备：从完整本里截取前 3-5 章为起点 .txt（不必全本上传，省 extract 时间 + 控制 plan 上下文）；保存为新 workspace 的输入
- web onboarding 新书 → upload → extract → 起点选最后一章 → plan-chapters 续写 3 章大纲 → write-book chapter=1
- 观察：
  - chapter-1 进度 5-90s 期间是否细粒度更新
  - 若中断（手动 kill worker 或网络）→ partial 是否落盘
  - debate / rewrite 入口是否可用
- 验收基准：**至少跑通 1 章 approved**，所有 web 功能可点击不崩。

### 阶段 4 · 预算止损
- 设 `budget_cny=0.5`（够触发但不烧太多）跑 write-book chapter=2
- 观察是否在章内某次 LLM 后立刻 budget_exceeded（而非整章后）

## 边界 / 不在本轮做

- 不动 `litellm` / `llm_client.py` 的核心调用栈（除非 budget_check_cb 必须）—— iter037/038 已经动过，本轮聚焦 web UI 层
- drama 模块 P3 backlog（badge inline color / subscore table 等 6 项）保持转 iter040
- onboarding 表单大改不在本轮（P2-C 只加 budget 输入，不重做 wizard）
