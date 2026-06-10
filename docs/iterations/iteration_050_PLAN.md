# Iteration 050 — 产品打磨包（048d / 049 顺延）

> 承接 048d 预定、被 iter049（Aeloon 插件 + MCP 双轨集成）插队顺延的产品打磨工作。本文件为**计划稿**，未执行。

## Context

iter048 收官时（048d Notes）为 iter049 预定了一组「全程可编辑 + 质量」打磨项。iter049 因 `integrations/` 脚手架已落 95%、需趁热补齐 Aeloon 插件并固化测试而插队，这些项整体顺延本轮。用户 2026-06-10 拍板此顺延。

## Plan（候选清单，执行时再定优先级与拆分）

1. **L 级 UX/a11y 集中修**：D1 友好 409 文案 / D4 stale plan loading 占位 / D7 `<label for>` 关联 / C3(c) 控制字符过滤 / B3-hint 提示 —— 与下面正文/设定编辑前端一起做摊销。
2. **细纲结构化字段编辑**：兑现「全程可编辑」最后一块（每章 7+ 字段 + 数组增删 + 范围校验）。**约束**：保持 `write-book` 的 `plan_fingerprint` / `chapter_plan_item_fingerprint` 门禁自洽——改动走「重跑 plan-chapters」而非手改回写（参照 048c 的暗礁处理）。
3. **正文逐章深度编辑回写 + 重 review**；设定（KB / entity_graph）编辑回写。
4. **premise 扩写质量增强**（短种子 → 高质量多章）。
5. **真模型端到端 smoke**（铁律⑥需用户授权）；测 Key 成本护栏深化。
6. **B-M-2 防御性重构**：`chapter_plan_item_fingerprint` 字段黑名单改白名单。
7. 046/047 README/Handoff 回填仍待办（沿 048a–c 接力点）。

## 不在本轮范围

- Aeloon 集成的进一步打磨——视 iter049 实机反馈另定；如确有需要，可向 Aeloon 团队提 `register_webui_panel` 类 feature request（当前 SDK 无自定义面板扩展点，富交互走深链）。

## Notes

- 紧接 iter049（Aeloon 插件 + MCP 双轨集成）之后。验收命令用 `.venv/bin/python`。
