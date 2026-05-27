# Iteration 024 — 长程稳定性（advisor 消费链路 + 自动 re-plan + budget ceiling + proposal 冲突检测）

## Context

iter 023 把 5+1 agent panel 跑出来，reviewer 首次给出 actionable 内容反馈（"主角全章未出场" / "奥丁过早直呼其名" / "需关联太子伏笔"），但 **iter 023 把 advisor 配置就绪却没接消费链路** —— writer rewrite-loop 看不到 advisor 的 RewriteSuggestion，5+1 agent 的具体建议浪费。

iter 024 是 **iter 025 capstone（跑完整 30-100 章）的前置稳定性投资**：

1. **advisor 消费链路**（iter 023 收尾）—— 让 reviewer 的 actionable 建议真转化为 writer 下一稿改进
2. **自动 re-plan**（SOP 5.3）—— 跑 ch11 时 chapter_plan 还停留在 iter 020 手工产的 ch1-30 plan，没法响应 ch1-10 已写的实际进展
3. **budget ceiling**（SOP 9.3）—— iter 020 跑 longzu 30 章时无法预知何时会超 ¥30；iter 025 capstone 100 章预算 ¥80-140 必须有硬保护
4. **proposal 冲突检测**（SOP 8.3）—— apply-advance 自动应用 entity proposal 可能让下一章 plan 的 `relationships_in_play` 不可满足

4 项互补：advisor 给 writer 改进信号；re-plan 让 outline 跟着实际章节走；budget 守住预算；proposal 守住一致性。

## Plan

| P | 任务 | 文件 |
|---|------|------|
| P1 | advisor 消费链路 | `src/reviewer.py` `load_advisor_agents` + advisor 段 + report.rewrite_suggestions；`src/writer.py` `_review_feedback` 加 advisor section |
| P2 | plot_planner --append --from-chapter | `src/plot_planner.py` `generate_chapter_plan(append_count, from_chapter)`；`main.py` 加 flags；`scripts/write_book.sh` `--replan-every K` |
| P3 | per-章 cost + budget ceiling | `src/cost_estimator.py` `estimate_cost_since` + `cost_cny` 共享；`scripts/write_book.sh` `--budget-cny N` + exit 3 |
| P4 | proposal vs plan 冲突检测 | `src/proposal_validator.py` 新建（hard-conflict heuristic）；`scripts/write_book.sh` apply-advance 前 dry-run |
| P5 | 测试 +15 → ~289 | 6 个新 test 文件 |
| P6 | longzu ch1-3 真模型 smoke | 验证 advisor 消费 + re-plan + budget |
| P7 | SOP 同步 + 报告 + commit | README/AGENTS/HANDOFF |

## Acceptance Result

| # | 项 | 实测 | 结果 |
|---|---|------|------|
| A1 | P1-P4 全部代码落地 + 单测覆盖 | 4/4 完成 | ✅ |
| A2 | **advisor 真模型实战产 actionable suggestions**（critical）| 5 条 RewriteSuggestion 落到 meta，含 section + type + guidance | ✅ |
| A3 | longzu ch1 在 advisor 消费下 Approve | ❌ 仍 Reject（同 iter 023：模型仍写诺诺视角而非主角）；advisor 准确诊断并给具体改写建议 | ⚠️ 半成功 |
| A4 | scene_excerpts / advisor / 程序化 auditor 共存 | meta 含 agent_reviews + rewrite_suggestions + deterministic_relations | ✅ |
| A5 | 总测试 ≥ 289 全绿 | **296 OK / 3.2s**（plan 估 289，超 7） | ✅ |
| A6 | 4 workspace preflight FATAL=none | byte-identical 保留 | ✅ |
| A7 | 真模型成本 ≤ ¥5 | **¥1.53**（30% 预算）| ✅ |
| A8 | SOP 4 节点 ❌→✅ + iter 024 报告 | README + AGENTS + AGENT_HANDOFF + 本文 | ✅ |

### A2 真模型 advisor 消费实证（iter 024 critical 突破）

longzu workspace 设 start_point=longzu_4 跑 ch1，advisor "改写顾问" 在 reviewer panel 跑完后被调用，产 5 条 RewriteSuggestion 完整 actionable：

| # | section | type | guidance（节选）|
|---|---|---|---|
| 1 | 开场段落 | rewrite | 将开场视角改为路明非在宿舍惊醒，梦中康斯坦丁低语'母亲'，随后通过同宿舍芬格尔的闲聊侧面带出诺诺深夜离校，激活路明非的焦虑感。结尾用路明非的内心独白'我得去'收束 |
| 2 | 诺诺逃往B3停车场段落 | add | 当奥丁因苏小妍的声音停住时，加入一段路明非视角的割裂叙事：他正在赶往医院途中，突然感到血脉灼烧，眼前闪现苏小妍说出'Ma'的模糊片段 |
| 3 | 神秘男人出场段落 | rewrite | 将神秘男人的'我等了十六年'台词，改为朝向路明非（而非诺诺）发出，暗示此人是路明非失踪的父亲或关联者 |
| 4 | 文中插入段落 | add | 在诺诺从医院旋转门逃入走廊后，插入一段学院教授会议室场景：古德里安教授察觉'尼伯龙根指数飙升' |
| 5 | 结尾 hook | add | 在章节末尾，路明非接过神秘男人的短刀时，刀身龙文与青铜封印阵产生共振 |

每条都包含**具体的"在哪里"（section）+ "怎么改"（type: rewrite/add）+ 详细 guidance**。这是 iter 020-023 reviewer 从未达到的编辑级具体建议。writer rewrite-loop 现在通过 `_review_feedback()` 的「## 改写顾问建议（按优先级，必须在下一稿处理）」section 真消费这些建议。

### A3 ch1 仍 Reject 的诚实记录

| 维度 | iter 023 ch1 | iter 024 ch1 |
|---|---|---|
| advisor suggestions | 0（配置就绪但未调用） | **5（落 meta）** |
| 字数 | 4587 | 5936 / 4029 |
| lint warning 数 | 15 | 8 |
| 5 agent 投票 | 3A + 2R | 2A + 3R |
| 主角本位 plot | 4 | 3 |
| 主角本位 issue | 主角缺席 | 主角缺席（重复） |

ch1 第 2 次仍 Reject 的根因 **不是 iter 024 修复缺失**，而是 deepseek 在拿到"诺诺抱苏小妍逃" anchor 时强烈倾向用诺诺视角写。advisor 已经在第 1 次就准确诊断（"主角路明非未在本章中出现或采取任何行动..."），但 writer 下一稿仍未完全改正。这是模型层 prompt-following 边界，超出 iter 024 scope（iter 025+ 可考虑：强制 writer system_prompt 加"主角必须在开场前 500 字露面"硬规则）。

**A2 critical 标志（advisor 真产 actionable 建议）已达成**；A3（ch1 Approve）半达成（advisor 信号产了但 writer 没完全执行）。iter 020-024 信号质量演化：
- iter 020 ch10：lint cascade Reject（reviewer 短路）
- iter 021 ch1：lint cascade Reject（reviewer 短路）
- iter 022 ch1：lint warning + 8 agent 全 7 笼统 Reject
- iter 023 ch1：lint warning + 5 agent specific 内容判断
- **iter 024 ch1：lint warning + 5 agent + advisor 5 条 actionable 建议**

### A2 其它 3 项（P2/P3/P4）：单测覆盖 ✅，真模型未触发

P2 re-plan / P3 budget / P4 proposal validator 三项都在 write_book.sh 的 *成功路径* 后触发（每章 success 后才打 [cost] / 检查 budget / 触发 re-plan）。iter 024 P6 smoke ch1 Reject 没走到成功路径，所以日志中没看到这些标记。但单测覆盖完整：
- `tests/test_cost_per_chapter.py` 4 项：cost_cny 数学、estimate_cost_since 0 件 / 部分 / 越界
- `tests/test_proposal_validator.py` 3 项：safe / hard-conflict / 无下一章 plan
- `tests/test_plot_planner_append.py` 2 项：append 保留 head + 重编号 / 无 append 模式不变
- `tests/test_write_book_replan_budget.py` 7 项：shell flag 解析 + exit code 3 + proposal_validator 集成 + per-章 cost 日志 + PIPESTATUS 保留

## File Summary

| 文件 | 改动 | 进 git |
|---|---|---|
| `src/reviewer.py` | + `load_advisor_agents()` + advisor 段（产 rewrite_suggestions）+ `_build_advisor_context_block()` | ✅ |
| `src/writer.py` | `_review_feedback()` 加 advisor section（cap 5 条） | ✅ |
| `src/plot_planner.py` | `generate_chapter_plan(append_count, from_chapter)` + `_format_existing_tail` + prompt 加 starting_chapter_no | ✅ |
| `src/cost_estimator.py` | + `cost_cny()` + `estimate_cost_since(line_offset)` + 共享 deepseek pricing 常量 | ✅ |
| `src/proposal_validator.py` | 新建（hard-conflict heuristic + `_HARD_CONFLICT_KEYWORDS` 复用 relationship_auditor）| ✅ |
| `src/cli_apply_bootstrap.py` | + `source_excerpts` apply 分支（iter 023 遗漏） | ✅ |
| `src/schemas.py` | iter 023 RewriteSuggestion 在 iter 024 真消费 | (已 commit) |
| `main.py` | `plan-chapters` 加 `--append` + `--from-chapter` flags + dispatch | ✅ |
| `scripts/write_book.sh` | + `--replan-every K` + `--budget-cny N` flags + INITIAL_LLM_LINES + cost report + proposal validator + exit 3 | ✅ |
| `tests/test_cost_per_chapter.py` | 新建 +4 | ✅ |
| `tests/test_proposal_validator.py` | 新建 +3 | ✅ |
| `tests/test_plot_planner_append.py` | 新建 +2 | ✅ |
| `tests/test_reviewer_advisor_consumption.py` | 新建 +3 | ✅ |
| `tests/test_writer_advisor_feedback.py` | 新建 +3 | ✅ |
| `tests/test_write_book_replan_budget.py` | 新建 +7 | ✅ |
| `tests/test_reviewer.py` | iter 023 已有 patches 扩展 load_advisor_agents → []（向后兼容） | ✅ |
| `tests/test_reviewer_kb_source_injection.py` | 同上 | ✅ |
| `README.md` | SOP 5.3 / 7.6 / 8.3 / 9.3 ❌→✅ + 时间戳更新 | ✅ |
| `AGENTS.md` | 当前 iter 改 024 + 下一步候选 → iter 025 | ✅ |
| `docs/AGENT_HANDOFF.md` | + Phase 4 Status iter 024 段 | ✅ |
| `docs/iterations/iteration_024_long_horizon_stability.md` | 本文 | ✅ |
| `docs/iterations/README.md` | + 第 24 行 | ✅ |
| `workspaces/longzu/outputs/drafts/chapter_01_iter024_advisor_demo.md` | iter 024 demo（含 5 条 advisor suggestions 的对照样本）| ❌（gitignored） |

## 不在本轮范围

- iter 025 capstone（完整 ~30-100 章）
- WebUI（iter 020 报告原计划，长程稳定后可启动）
- KB 按起点过滤（需 LLM 重写 KB）
- entity_graph timeline schema 升级（让 deterministic_relations + proposal_validator 更密集）
- writer hard-rule "主角必须 500 字内露面"（iter 025+ 处理 ch1 始终 Reject 问题）
- ASOIAF / 其它 workspace 跨语言验证
- bootstrap-source-excerpts 默认 router 改 deepseek（claude-opus refusal 问题，iter 023 末记录）

## Notes

1. **iter 024 P6 smoke 跑了 4 次定位 harness kill 问题 + 1 次 zsh glob 错误**：前 3 次后台 bash 被 monitor stop 信号波及死掉（iter 022 也踩过），第 4 次 zsh `rm chapter_01.last_failure_attempt*` 在无匹配时 `set -e` 直接 exit 1 让脚本根本没启动。改用 `find -delete` 解决。最后第 5 次干净完成 ¥1.53
2. **advisor 不影响 verdict**：iter 024 设计明确 advisor 只产 RewriteSuggestion，不投票。verdict 仍由 5 个 review_agents 的 substantive Approve/Reject 决定。advisor 失败（parse 错误 / runtime error）只 log_event 不 raise，保持向后兼容
3. **iter 023 老 meta.json 自动 graceful**：iter 020-023 写的 chapter_NN.meta.json 没有 `rewrite_suggestions` 字段 → pydantic / json default 让旧数据零修改读出（chapter_status / collect_iter020_data 都 graceful skip 这字段）
4. **shared pricing 去重**：iter 020 `scripts/collect_iter020_data.py` 和 iter 024 `src/cost_estimator.py` 都有 deepseek 定价常量；iter 024 把 collect 脚本改用 cost_estimator.cost_cny（避免数字漂移）
5. **write_book.sh exit code 现在 3 种**：0=success、2=retry exhausted（iter 019/022）、**3=budget ceiling hit（iter 024）**。每种都先 take_snapshot 再 exit，保证 partial progress + diagnostics 落盘
6. **proposal validator v1 保守**：只在 proposal `new_state` 含 hard-conflict 关键词（敌对/已死/已背叛/...）且下一章 plan 明确提到 src↔dst 互动时才 BLOCK。其它情况默认 SAFE 放行，匹配 iter 023 行为
