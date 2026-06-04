# Iteration 042 — happy path 跑通 + 打分制三档（兼容版）

> 文件名沿用草稿盒路径；iter039/040 plan 已归档到 `docs/iterations/iteration_039_PLAN_DRAFT.md` / `iteration_040_PLAN_DRAFT.md`（040 待 codex prep 一并 add）。

## Context

**为什么这一轮做这个**：iter041 调查报告（`docs/iterations/iteration_041_INVESTIGATION.md`）锁定 happy path 跑不通的两条根因 —— F3（reviewer source context 漏传）+ F1（原作风格模拟 agent prompt 过严）。同时用户提了 N1+N2（审核分档 + 打分阈值），目标是让"每轮真实验收成本从 ¥5 降到 ¥1-2"，给后续所有迭代节流。本轮把 F3 + F1 + N1+N2 合并实施，让 happy path 在 mid 档跑通 approved。

**P2 兼容方案确认**（用户拍板）：verdict 字段保留为主信号，新增 score 字段 + 档位阈值组合判定，向后兼容历史 workspace。

**用户视角痛点**：
- 龙族 ch2 在 high 档（现有 fail-closed）真的过不去，需要 mid 档兜底
- 打分制不只是给 ch2 用，是给每次 iter 验收节流的基础设施
- F1 调优配合 F3 才有意义（漏传 source 时 F1 调宽也救不回）

**iter042 目标**：让 `OPENAI_MODEL=<real>` + `WRITE_REVIEW_TIER=mid` 跑龙族 ch2 出 approved；mid 档成本 < 2 元；high 档保留现有严苛逻辑作为发布门槛。

---

## 修复方案

### §A · F3 reviewer source context 漏传修复

**根因**：`book_runner.py:641-647 review_target()` 调用 `review_text()` 只传 run_context/draft_sha256，漏传 knowledge/source_chapters/scene_excerpts。external review prompt 体量从 source-rich 的 ~33k chars 降到 ~17k chars，原作风格模拟 agent 拿不到原文对照 → fail-closed Reject。

**实施**：
1. **`src/reviewer.py review_target()`** 签名扩展，接收可选 `knowledge` / `source_chapters` / `scene_excerpts`，透传给 `review_text()`
2. **`src/book_runner.py:143, 186`** 两处 review_target 调用前，按 writer.py L193-209 同款逻辑预先计算：
   ```python
   review_source = start_point.format_chapters_before_start_for_anchor(k=3, limit_chars=8000)
   scene_matches = source_excerpts.select_for_chapter(chapter_plan_item, k=3) if chapter_plan_item else []
   scene_excerpts_text = source_excerpts.format_excerpts_for_prompt(scene_matches, limit_chars=8000) if scene_matches else ""
   knowledge = _load_knowledge()  # 复用 writer 已有的 knowledge 加载逻辑
   review_target(md_path, knowledge=knowledge, source_chapters=review_source, scene_excerpts=scene_excerpts_text, enforce_relationship_checklist=True)
   ```
3. 抽出一个内部 helper `_build_review_context(chapter_plan_item)` 放在 `book_runner.py` 顶层，封装这三段计算，避免 L143 / L186 两处重复
4. **`writer.py shadow_review`（L182）也补一下**：当前 shadow_review 也漏传 source；既然顺手就修了。优先级低于主修复，但同一轮内做掉

**验收**：单测 `tests/test_book_runner_review_context.py`：mock review_text spy，断言被调用时收到非空 knowledge/source_chapters/scene_excerpts。

---

### §B · F1 原作风格模拟 agent prompt 调优

**根因**：`config/agents.yaml:99-102` 原作风格模拟 agent 在 source 对照后仍倾向 fail-closed Reject 主观项（密度/留白/台词端正等）。

**实施**：
- 修改 system_prompt_template，按 iter041 §6 推荐的判定原则改写：
  - **必须 Reject 的情况**：原文对照后确认风格硬伤（明显 AI 腔、严重 voice 漂移、与 {author_name} 既定文风背离）
  - **降级 major（Approve + major issue）的情况**：密度偏满 / 留白不足 / 台词端正度等主观维度
  - 显式说明"在 source_chapters 提供时，必须先对照原文再裁决"，强制 source 使用
- 不改其他 4 个 agent prompt（iter041 调查显示其他 agent 并非 systematic 偏严）

**验收**：
- 跑一次 reviewer regression smoke：用 iter029_beta_ok 已 approved 的章节 + 龙族 ch2 draft 各跑一次 review_text，断言：
  - iter029 章节仍 Approve（无 regression）
  - 龙族 ch2 mock 档下 verdict 改善（不强求 Approve，但 issue 应从 Reject 降级到 major）

---

### §C · N1+N2 打分制 + 三档阈值（P2 兼容方案）

**核心约束**：verdict 字段保留为主信号（chapter_status 不动）；新增 `tier` 概念 + score 阈值；historical workspace 不破坏。

#### §C.1 · 引入档位配置

**位置**：新增 `src/review_tier.py`（小模块，单一职责）

```python
TIER_HIGH = "high"   # 现状 fail-closed + panel_score >= 8.5
TIER_MID  = "mid"    # 至少 4/5 Approve + panel_score >= 7.5
TIER_LOW  = "low"    # 至少 3/5 Approve + panel_score >= 6.5

DEFAULT_TIER = TIER_MID  # iter042 起，默认 mid（开发期友好）

def resolve_tier() -> str:
    """从 env WRITE_REVIEW_TIER 读取，默认 mid，校验合法档位"""

@dataclass
class TierThresholds:
    min_approve_count: int       # panel 中 Approve 投票数下限
    min_panel_score: float        # 加权平均分下限
```

env 变量 `WRITE_REVIEW_TIER` 读取；Web job params 也支持（透传到 worker 环境）；不传时走 DEFAULT_TIER。

#### §C.2 · reviewer.py aggregation 改造

**位置**：`src/reviewer.py:489-498`

把硬写的 `any(Reject) → Reject` 改成 tier-aware：

```python
tier = review_tier.resolve_tier()
thresholds = review_tier.thresholds_for(tier)

approve_count = sum(1 for r in substantive if r["verdict"] == "Approve")
panel_score = _weighted_panel_score(substantive)  # 用已有 plot/prose/fidelity 加权

if approve_count >= thresholds.min_approve_count and panel_score >= thresholds.min_panel_score:
    verdict = "Approve"
else:
    verdict = "Reject"
```

`_weighted_panel_score` 复用已有的 `AgentReview.score`（reviewer.py L80-95 weighted avg of plot/prose/fidelity），panel score = 5 个 agent score 的算术平均。

#### §C.3 · report schema 扩展

**位置**：`src/reviewer.py:577-586` report 顶层 + `src/writer.py:365-378` meta 写入

新增字段（向后兼容，旧字段全保留）：
- `tier`: 本次 review 使用的档位
- `panel_score`: 5 agent 加权平均分
- `approve_count`: panel 中 Approve 投票数
- `tier_thresholds`: 当时档位的 min_approve_count / min_panel_score 快照（便于事后审计）

写入 reviews/chapter_NN.review.json + drafts/chapter_NN.meta.json 两处。

#### §C.4 · book_runner + writer 透传 tier

**位置**：`book_runner.run_write_book()` 接收 `tier` 参数，透传给 writer.write_chapters；writer 在调 review_text 时传 tier；review_text 内部用 tier 决定 aggregation。

env 变量是兜底，参数链路是主路径（便于 Web 端 per-job override）。

#### §C.5 · Web 端档位入口（轻量）

**位置**：`src/web/jobs.py _step_write_book` 接收 `tier` 参数（job params），透传给 run_write_book

不改前端 UI（iter043 做）；先支持 API 级别 override：`POST /api/workspace/<ws>/write-book { "tier": "mid" }`。

#### §C.6 · 单测

- `tests/test_review_tier.py`：thresholds 表、env 解析、默认值
- `tests/test_reviewer_tier_aggregation.py`：构造 5 agent reviews（4 Approve 1 Reject、score 7.8 均值）：
  - high 档 → Reject（fail-closed）
  - mid 档 → Approve（4/5 + 7.8 >= 7.5）
  - low 档 → Approve
- `tests/test_book_runner_tier_flow.py`：env=low + mock writer → meta.json 含 tier=low + panel_score 字段

---

## §D · 真实验收

### 阶段 1 · 单测
```bash
.venv/bin/python -m unittest discover
```
基线：OK (skipped=6)，期望 ~563 tests（559 + 4 类新增）。

### 阶段 2 · mock 链路
```bash
OPENAI_MODEL=mock .venv/bin/python main.py preflight
PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
OPENAI_MODEL=mock WRITE_REVIEW_TIER=mid .venv/bin/python -m src.cli write-book --chapters 1 --workspace iter029_beta_ok  # tier 透传冒烟
```

### 阶段 3 · 真实模型 · 龙族 ch2 happy path（mid 档）
**预算**：< 5 元一次性授权，codex 自主跑，不中断等额外授权

- 备份 `/tmp/iter042_baseline_$(date +%Y%m%d_%H%M%S)/`：现有 chapter_02.* + reviews/chapter_02.*
- 删 chapter_02.{md,meta.json,partial.md,failure.json} + reviews/chapter_02.review.json
- 跑 `WRITE_REVIEW_TIER=mid budget=10`，write-book chapter=2
- **验收基准**：
  - meta.json + review.json verdict=Approve（两文件一致）
  - meta.json 含 `tier=mid` + `panel_score >= 7.5` + `approve_count >= 4`
  - 成本 < 3 元
  - job status=succeeded
- 如果 mid 档仍 Reject：判断是 panel_score 不够还是 approve_count 不够；如果 panel_score >= 7.5 但 approve_count=3 → 说明 F1 调优后某个 agent 仍硬卡，记录 incident + 算 iter042 收官；如果 panel_score < 7.5 → 说明 writer 真的有质量短板，转 iter043 调查

### 阶段 4 · high 档 regression（确认未破坏发布门槛）
- 用 iter029_beta_ok 已 approved 的章节，`WRITE_REVIEW_TIER=high` mock 跑一次 review_text
- 断言：仍 Approve（high 档兼容现有 fail-closed 语义）

---

## 关键文件清单

| 文件 | 改动 |
|---|---|
| `src/review_tier.py`（新建） | TIER_* 常量 + thresholds 表 + resolve_tier() / thresholds_for() |
| `src/reviewer.py` | review_target() 签名加 source 参数透传；aggregation L489-498 改 tier-aware；report schema L577-586 加 tier/panel_score/approve_count |
| `src/book_runner.py` | _build_review_context() helper；L143/L186 调 review_target 时传 source；run_write_book 接收 tier 参数 |
| `src/writer.py` | shadow_review 补传 source；write_chapters 接收 tier 透传；meta 写入加 tier/panel_score |
| `config/agents.yaml:99-102` | 原作风格模拟 agent system_prompt_template 改写 |
| `src/web/jobs.py _step_write_book` | 接收 tier job param |
| `tests/test_review_tier.py`（新建） | 档位配置单测 |
| `tests/test_reviewer_tier_aggregation.py`（新建） | 三档投票/打分聚合单测 |
| `tests/test_book_runner_review_context.py`（新建） | F3 source 透传单测 |
| `tests/test_book_runner_tier_flow.py`（新建） | tier 参数链路 + meta 字段单测 |
| `docs/iterations/iteration_042_PLAN.md`（新建） | codex 执行档案 |
| `docs/iterations/iteration_040_PLAN_DRAFT.md`（新建） | 把 ~/.claude/plans/ 的 iter040 plan 副本归档（顺手补，因 iter040 prep 没归档） |

## 已有可复用工具

- `src/start_point.format_chapters_before_start_for_anchor` —— 原文锚点（writer.py L193 已用）
- `src/source_excerpts.select_for_chapter` + `format_excerpts_for_prompt` —— 场景匹配（writer.py L198 已用）
- `src/persona_loader` —— agents.yaml 占位符渲染
- `src/schemas.AgentReview.score` —— 已有的加权平均分（plot/prose/fidelity）
- `src/utils.read_json / write_json` —— meta + review JSON 读写

## 边界 / 不在本轮做

- 不动 chapter_status.py（verdict 字段仍是主判定，sync 后两文件一致即可）
- 不动其他 4 个 reviewer agent prompt（只调 F1 原作风格模拟）
- 不改前端 UI（tier 暂只 API 入口，iter043 做 UI）
- iter039 P2 三件套 + drama P3 + N3 WebUI 重构 → iter043
- F1 调优如发现需要其他 agent 配合放宽 → 记录 iter044 backlog，本轮不动
- 不 push 任何 commit

---

## iter043 / iter044 预告（不在本轮）

### iter043 · WebUI 用户友好重构（含 drama 模块 UX）
- §A 调查轮：subagent + 网页设计 skill 输出 UX audit（含 drama）
- §B 实施：错误态视觉 / 导航 / onboarding / continue 页 readiness 信息密度 / drama 模块 UX
- §C 顺手合并：iter039 P2 三件套（jobs 80 字截断 / sidebar lost 区分 / onboarding budget+cancel）
- §D tier 档位 UI 入口（iter042 留下的 API → 前端选档器）

### iter044 · 收尾
- drama 模块 P3 backlog 6 项
- F1 二次调优（如 iter042 后仍需）
- writer pending_external_review fallback（iter040 留的，若仍需）
- AGENTS.md / README / SOP 全面刷新
