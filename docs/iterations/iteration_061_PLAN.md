# Iteration 061 - #11 extract-style 路径穿越 P0 热修（接力登记补全）

> **登记说明**：iter061 是一次 **P0 安全热修**（commit `bce579c`，2026-06-23），当时未走完整四处登记——无 PLAN 文件、不在 `iterations/README.md` 与根 README 状态表。本文件是 **iter063 Part E 的事后补登记**（铁律⑧闭环），内容据 commit `bce579c` 与 `docs/AGENT_HANDOFF.md` iter061 段还原。

## Context

iter060 #11（writer-style 唯一样本，修 TOCTOU）让上传路由把样本的**绝对路径**塞进 `job params.sample_path`，`_step_extract_style`（`jobs.py`）裸 `Path()` 信任该路径并 `read_text` + `unlink`。而 `/run` 端点允许任意 params → 攻击者 `POST {step:"extract-style", params:{sample_path:"/任意路径"}}` 即可让该 step **读取并删除 workspace 外的任意文件**（实测：外部文件被删、`writer_style.json` 被生成）。这是 iter060 #11 修复 TOCTOU 时引入的**路径穿越回归**，P0。

## Plan

- `#11-P0` 关闭路径穿越：路由不再传路径，只传随机 token；handler 在 `data_dir` 内用校验过的 token 重建路径，**路径永不取自调用方输入**。

## Acceptance

- 端到端 `/run` 恶意 `sample_path` / 非法 `token` → workspace 外文件存活、不被读取或删除。
- 既有 #11 唯一样本测试改为 token 契约后仍绿。
- `unittest discover` 全绿；只 commit 不 push。

## Implementation Notes

- **修复**（`src/web/routes.py` + `src/web/jobs.py`）：路由 `api_workspace_writer_style_extract` 生成 `uuid4().hex` token，把样本写到 `.writer_style_sample.<token>.tmp`（`write_text_atomic`），只把 `sample_token` 入 job params。handler `_step_extract_style` 用 `re.fullmatch(r"[0-9a-f]{32}", token)` 校验后，在 `data_dir` 内 `with_name` 重建路径——穿越不可能；非法/缺失 token 回落固定路径（仍在 `data_dir` 内）。
- **+4 测试**：含端到端 `/run` 恶意 `sample_path` / traversal `token` → 外部文件存活；既有 #11 测试改 token 契约。
- **`bce579c` 同时捎带**（非本热修核心，但同一 commit）：`AGENTS.md` 铁律⑨ 升级为内置 `/code-review` + `/security-review` skill；新增 `docs/CLAUDE_CODE_WORKFLOW_OPTIMIZATION_2026-06.md` 调研报告。
- **接力登记**：`bce579c` 还在 `AGENT_HANDOFF.md` 末尾登记了 iter060+iter061 代码审查（`/code-review high`）发现的 7 条问题（①-⑦，iter061 未覆盖的真实问题），划归后续迭代修复。

## Acceptance Result

- 路径穿越关闭（端到端测试：外部文件不被读/删）。
- 单测全绿（基线 1180 + #11 token 契约新测）。
- 只 commit 不 push（`bce579c`）。
- *（事后补记，回归数据以当时 commit 为准。）*

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/web/routes.py` | extract 路由改传随机 token（不传路径）+ `write_text_atomic` 暂存样本 |
| `src/web/jobs.py` | `_step_extract_style` 用 32-hex token 校验 + `data_dir` 内 `with_name` 重建路径；非法 token 回落固定路径 |
| `tests/test_web_writer_style.py` | +4 路径穿越/契约测试；既有 #11 测试改 token 契约 |
| `AGENTS.md` | 铁律⑨ 升级为内置 `/code-review`+`/security-review` skill |
| `docs/CLAUDE_CODE_WORKFLOW_OPTIMIZATION_2026-06.md`（新增） | 工作流优化调研报告 |

## 不在本轮范围

- iter060/061 代码审查发现的 ①-⑦（孤儿版权样本、timeout 丢弃、坏 meta 等）——登记到 `AGENT_HANDOFF.md`，顺延后续迭代（**iter063 已全部修复**）。
- iter061 的文档四处登记——**本文件即为 iter063 Part E 的补登记**。

## Notes

- iter063 ⑥ 进一步收口了本轮遗留的"非法 token 回落固定路径"后门（无合法 token → 直接 blocked，不再回落 clobber-prone 路径）。
- 编号说明：git 历史里 iter061 在 iter060 与 iter062 之间；`iterations/README.md` 索引此前缺这一条，iter063 Part E 补入。
