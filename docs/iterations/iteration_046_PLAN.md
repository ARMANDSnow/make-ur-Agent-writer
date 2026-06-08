# Iteration 046 — AgentWrite 配额循环（segmented write）

## Context

长章常欠字：`writer.py` 的目标带是「中文正文 3500-5500 字」，但单发生成（single-shot）经常欠到 3000 以下才触发 polish 扩写，长度与节奏不可控。LongWriter 的 AgentWrite 思路（Apache，可商用）给出干净解法：planner 产出**每章的分段计划 + 字数配额**，writer **逐段生成**、按配额写、**非末段抑制收尾**（不写章节结尾/下章钩子），只有末段收束全章。

本轮为 Phase 6 第一迭代（产品力补齐主线）。**干净重写**该思路，不复制任何竞品代码。外部执行档案：`~/.claude/plans/phase6-groovy-shannon.md`。

## Plan

1. **schema**：`schemas.py` 新增 `ChapterSegment{segment_no, beat, target_chinese_chars(300-2000), is_final}`，`ChapterPlanItem` 加 `segments: List[ChapterSegment] = []`（可选；空 = 单发，向后兼容）。
2. **指纹向后兼容**：`plot_planner.chapter_plan_item_fingerprint` 与 `plan_fingerprint` 把 `segments` 加入排除集——segments 是写作期分解、非 plan 语义变化，排除后**新增字段不会令任何 pre-046 的 on-disk plan 触发 `plan_fingerprint_mismatch` fail-closed**。
3. **planner prompt**：`_build_planner_prompt` 加可选 segments 说明（bullet 11）；schema 块自动文档化新字段。
4. **writer**：`agents.yaml` 加 `segmented_write`（默认 `false`）；`write_chapters` 读开关，attempt 循环内分支——开关开 + 本章有 segments → `_write_chapter_segmented(...)` 逐段生成并拼接；否则走原 `_write_prompt` + `_complete_write_text` 单发路径（**逐字不变**）。lint/review/polish/persist 仍对拼接后整章跑一次（不变）。
5. **分段 prompt**：`_write_prompt` 加 `segment/segment_index/segment_total/prior_segments_text` 可选参数（缺省 None → 单发输出逐字不变）；新增 `_segment_directive_block`（beat + 非末段抑制收尾 + 段>1 不重开场 + 前文衔接）。稳定块（style/KB/outline/entity）仍 `cache:True` 跨段恒定，仅每段动态块 `cache:False`，分段对缓存成本友好。
6. **测试**：新增 `tests/test_plot_planner_segments.py`、`tests/test_writer_segments.py`。

## Acceptance

- 开关开 + N 段 → N 次 LLM 调用并拼接为整章；非末段 prompt 含「本段不是最后一段/不要收束全章」、末段含「本段是本章最后一段」；段>1 含「本章已写前文 / 不要从 opening_scene 重新开场」。
- 每段 prompt 用「本段目标长度」替换「中文正文 3500-5500 字」。
- 开关关、或本章无 segments → 单发，调用数=1、prompt 保留「中文正文 3500-5500 字」。
- `segments` 不影响章节指纹（向后兼容）。
- 全量回归不因本轮新增任何失败。

## Implementation Notes

- 关键约束：`_write_prompt` 的所有 segment 改动**全部 guard 在 `segment is not None` 之后**，`length_block`/`segment_block` 在 segment 为 None 时逐字复现原字符串 → `test_writer.py` 既有 `_write_prompt` 断言（如「中文正文 3500-5500 字」「本章计划」「当前活跃关系」）全部不受影响。
- 指纹排除 segments 是**必须**而非可选：否则 `model_to_dict` 会给每个 item 注入 `"segments": []`，使重算指纹 ≠ pre-046 存档指纹，`book_runner` 会 fail-closed 拒写既有工作区。
- mock 路径无需改：`llm_client._mock_json` 的 mock `ChapterPlan` 不带 segments → 既有 mock 流水线测试行为不变。
- 开关沿用 `polish_pass` 的 `agents.yaml` 配置范式；WebUI/auto_pipeline/book_runner 零改动（仍调 `write_chapters`）。

## Acceptance Result

通过（mock-only，未跑真实模型 smoke）。

- **环境修复**：本机 Homebrew `python@3.13` 曾被移除导致 `.venv` 解释器悬空；已 `brew install python@3.13` 重装，`.venv`（Python 3.13.13）恢复，依赖完好（pydantic 2.13.4 等）。此前只能用系统 3.9.6 跑、2 个 PEP604 模块无法导入的问题已消除。
- **新增测试**：`tests/test_plot_planner_segments.py`（4）+ `tests/test_writer_segments.py`（5）→ 全过。
- **全量回归（3.13）**：`.venv/bin/python -m pytest tests/ -q` → **601 passed, 3 failed**；3 个失败为既有、与本轮无关（`test_env_isolation` + `test_llm_client_cache`×2，见 iteration_045），已 `git stash` 验证 baseline 同样失败。
- **子代理审查/实测**：对抗式 code review 经验性确认 ①单发 prompt 在 `segment is None` 时逐字不变、②指纹排除 segments 后 pre-046 存档指纹不变（含 `model_to_dict` 注入 `segments:[]` 的情况）、③分段缓存切分正确。审查 M2（段配额 `le` 太紧，2 段切分 6000 字会令整 plan 加载失败）已修：`le` 2000→4000；N1（断言每段配额数值）已补。实测子代理在 mock 下行为验证通过。
- **已知后续（segmented_write 开启前再处理，默认关）**：M1 非末段 prompt 仍带整章 `target_chinese_chars`/`ending_hook`，宜在分段模式下隐藏；M3 分段中途失败的 partial 落盘只保留失败段、丢弃已完成段；N2 可加单发 prompt 的 golden 回归。
- 全程 mock，未改 `.env`/`data/`/`outputs/`，未跑真实模型，未 push。
