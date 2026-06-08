# Iteration 046B — debate 龙族 人格回退修复（bug fix）

## Context

用户实际跑其他小说时反馈：**debate agent 默认是龙族且无法自动修改**（人格读作 路明非 / 江南 / 言灵·龙王 等）。

根因（子代理 + 代码核实）：`src/debater.run_debate` 本身已正确调用 `persona_loader`——`render_agent_fields` 在 `personas is None` 时返回 `agents.yaml` 的**legacy 龙族字段**（`persona_loader.py:129-130`）。问题是：**在 workspace 模式下若该 workspace 没有 `personas.json`，会静默回退龙族**。触发路径：①`run-all`（跳过 bootstrap+apply，`main.py:533-538`）②单独 `debate` ③onboarding 未跑完的 workspace。`auto-pipeline`/WebUI 向导路径会先 bootstrap+apply personas，本来就正常（已用 `tianlong`=天龙八部 验证）。加重项：默认 topic 硬编码龙族（`debater.py:67`）、`_hardcoded_outline` 与 mock `build_decisions` 投票硬编码龙族角色名。

## Plan / Changes（`src/debater.py`）

1. **fail-fast 守卫**：`run_debate` 在 `load_personas()` 后，若 `paths.workspace_name()` 且 personas 为 None → 抛 `FileNotFoundError`，给出可操作指引（先 `bootstrap-personas` + `apply-bootstrap --name personas`，或直接 `auto-pipeline`）。**不再静默回退龙族**。legacy 模式（无 workspace）保留原验证语料回退行为不变。
2. **默认 topic 去龙族**：签名 `run_debate(topic="")`；加载 personas 后，有主角则 `f"{protagonist}线的长篇续写结局方案"`，否则通用 `"长篇小说续写结局方案"`。
3. **去龙族 fallback 文本**：`_hardcoded_outline` 核心共识 bullet 改为通用；mock `build_decisions` 的两条投票问题改为通用（去 路鸣泽/楚子航/夏弥）——覆盖默认 mock/demo 路径。

> 范围说明：**未改 run-all 的步骤序列**（其在真实 workspace 用法下现在会被守卫拦下并提示用 `auto-pipeline`）。若希望 `run-all` 一条命令自动带 bootstrap，可后续让它委托 `run_auto_pipeline`（Option 2，需改其 1 个集成测试）。

## Acceptance Result

通过（mock-only）。

- **新增/更新测试**：`tests/test_debater_persona_guard.py`（4：workspace 缺 personas → fail-fast；legacy 仍可跑；默认 topic 通用且全 outline 无龙族名；有 personas 用主角名）；更新 `test_debater.py::test_mock_client_uses_hardcoded_decisions`（mock 投票去龙族）。
- **全量回归（3.13）**：`.venv/bin/python -m pytest tests/ -q` → **601 passed, 3 failed**（3 个为既有、与本轮无关，见 iteration_045）。
- **子代理实测（mock 端到端）**：新建 workspace `楚天阔`（古龙武侠）——无 personas 时 `main.py --book … debate` fail-fast、debate 目录保持空（无静默龙族）；补 personas 后 outline 标题 `# 楚天阔线的长篇续写结局方案`、agent 名 `楚天阔本位/古龙人格模拟`、全文无 路明非/江南/言灵/龙王/龙族。
- **已知后续（低优先）**：L1 守卫的 `FileNotFoundError` 在 WebUI 中显示为 job “failed” 而非更柔和的 “blocked”（消息已可操作）；L3 `run_auto_pipeline` 吞掉 personas apply 失败后会撞守卫——可在 debate 前对 personas 做 apply 状态检查。
- 全程 mock，未跑真实模型，未 push。
