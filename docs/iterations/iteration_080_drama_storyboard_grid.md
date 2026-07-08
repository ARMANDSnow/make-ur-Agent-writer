# Iteration 080 - 短剧站③分镜生成 + grid 编辑器

## Context

Iteration 079 已被 capstone 前写锁与预算硬化占用并收官；短剧路线图 `iteration_079_083_drama_module_roadmap.md` 中的“079 站③分镜 + grid 编辑器”因此平移到本轮实际编号 080 执行。

当前 drama 模块已有站①核心设定与站②钩子，站③/④在 Web 中仍表现为 locked。短剧产品线要从“前 2 站 mock 演示”推进到“剧本 + 分镜 + 角色三件套闭环”，本轮先补齐分镜表生成、可编辑 grid、重生本镜与基础校验。

## Plan

- 新增 `src/drama_schemas.py`：定义分镜 schema、`episode_paths()` 路径 helper、硬/软校验分层；两个以上高光硬拒，零高光仅 soft warning。
- 新增 `src/storyboard_builder.py`：站③ runner 支持 mock fixture 与真模型 `LLMClient("drama_storyboard").complete_json(DramaStoryboard)` 路径；本轮不实跑真模型。
- 新增 `prompts/drama/storyboard_builder.txt`、`config/models.yaml` 的 `drama_storyboard` task、`config/agents.yaml` documentation-only 配置。
- 新增 Web API：GET/POST/PUT `/drama/storyboard` 与 POST `/drama/storyboard/rewrite-shot`；drama-only，站②未完成 400，写入统一走 `_workspace_write_guard` + `write_json`。
- 解锁 Web 站③ tab，实现原生表单 grid：景别、运镜、时长、画面、旁白、台词、高光、上/下移、重生本镜、保存整表与总时长提示；站④继续 locked。
- 新增 5 赛道原创 storyboard fixtures，含 `alt_shots` 供 mock 重生本镜；持久化产物不保留 `alt_shots`。

## Acceptance

- 5 赛道 mock ①→②→③ 走通，生成的 storyboard schema 合规、总时长 60±3 秒、恰 1 高光。
- grid 保存后 GET 回读一致，服务端重排 `shot_no`；两个以上高光 400，零高光保存成功并返回 `highlight_missing` soft warning。
- 重生本镜只替换指定镜，其余镜头字节级不变。
- 站②缺失 400、novel workspace 400、无 storyboard 文件 GET 返回空态不崩。
- fixture lint 通过：6-9 镜、首镜 2-3 秒特写/近景、末镜 8-10 秒、台词单句 ≤15 字、不含龙族专名。
- 验收命令：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`。不跑真模型 smoke（铁律⑥）。

## Implementation Notes

- 分镜路径统一经 `episode_paths()` 落到 `outputs/episodes/episode_01.storyboard.json`；站② setup 也迁到同一路径 helper，避免 Web/API 与 agent runner 拼路径漂移。
- `storyboard_builder.run(..., mock=None)` 采用 `LLMClient("drama_storyboard").is_mock` 自动探测；mock 路径读取 5 赛道 fixture 并剥离 `alt_shots`，真模型路径只完成 wiring，本轮未实跑。
- Web 站③保持同步 200 API；GET/POST/PUT/rewrite 均限制 drama workspace，且站②未完成时返回 400。写入路径统一在 `_workspace_write_guard` 内用 `write_json` 持久化。
- Grid 保存服务端重排 `shot_no`；两个以上高光硬 400，零高光保存但返回 `highlight_missing` soft warning。生成/重生路径也在写盘前做双高光硬拒兜底。
- “重生本镜”支持带当前 grid payload 调用，避免用户上移/下移或未保存编辑后被磁盘旧版覆盖；持久化结果仍只替换目标镜。
- 本轮未修改 `.env`、`小说txt/` 或版权原文；`bash scripts/verify.sh` 按仓库既有行为生成了 gitignored 的 `data/`/`outputs/` 验证产物。

## Acceptance Result

- Implementation-phase checks（2026-07-08）：
  - `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_drama_storyboard_builder tests.test_drama_storyboard_grid tests.test_drama_fixture_lint tests.test_drama_view tests.test_workspace_overview_drama tests.test_web_routes_get`：109 tests OK。
  - `node --check` on `JS_DASHBOARD`：OK。
  - `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m py_compile src/drama_schemas.py src/storyboard_builder.py src/web/routes.py`：OK。
- iter-finish checks（2026-07-08）：
  - `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_drama_storyboard_builder tests.test_drama_storyboard_grid tests.test_drama_view tests.test_drama_fixture_lint tests.test_workspace_overview_drama tests.test_web_routes_get`：115 tests OK（含审查修复新增回归）。
  - `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m py_compile src/drama_schemas.py src/storyboard_builder.py src/web/routes.py src/web/drama_view.py`：OK。
  - `PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`：1661 tests OK。
  - `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`：exit 0（内部 1661 tests OK，随后 auto-pipeline/status/manifest/report/cost 全过）。
  - `.venv/bin/python3 main.py preflight`：exit 0，PREFLIGHT warn，无 FATAL；WARN 为当前真实配置 token/cache/budget 提示。
  - `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`：exit 0，PREFLIGHT ok。
  - `git diff --check`：OK；新增 diff 未发现 `sk-...` 形态。
- 铁律⑨审查（按用户要求使用 2 个只读 subagent）：
  - `/code-review high` 发现 4 个有效问题并已修：Web 生成/重生在真实环境可能误走真模型（站③ Web 改为 iter080 mock-only，真模型路径留 runner/iter083）；`rewrite_shot()` 真模型 prompt 缺当前 storyboard 上下文（补 bounded context）；progress 只看 `shots>=6` 可能把双高光坏文件标 done（改用 schema + hard validation）；双高光硬拒仅在 route 层（下沉 `validate_storyboard_hard()` 并接入 builder/route/view）。
  - `/security-review` 发现 3 个有效问题并已修：RuntimeError 可能把 provider/prompt/key-like 内容回给 Web（改 generic `server_error` card + 日志脱敏）；客户端可伪造/持久化超长 `hook`（schema 限长 + PUT/runner/rewrite 统一用站②服务端 hook snapshot）；Web API 误触真模型风险同上改为 mock-only。
  - 复核结论：无剩余 P1/P2 blocker；残留风险仅为站③真模型 smoke、job 化与站①②真模型补课按路线图顺延到 iter083，本轮未跑真模型 smoke（铁律⑥）。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/drama_schemas.py` | 新增分镜 schema、episode 路径 helper、soft warning 校验。 |
| `src/storyboard_builder.py` | 新增站③分镜 runner 与单镜重生逻辑，支持 mock fixture 与真模型 wiring。 |
| `prompts/drama/storyboard_builder.txt` | 新增站③分镜 agent prompt。 |
| `config/models.yaml` | 新增 `drama_storyboard` task。 |
| `config/agents.yaml` | 新增 documentation-only `storyboard_builder` 配置。 |
| `src/hook_designer.py` | 站② setup 路径改用 `episode_paths()`。 |
| `src/web/routes.py` | 新增 storyboard GET/POST/PUT/rewrite API，接入 drama-only、站②前置、写锁和高光校验。 |
| `src/web/drama_view.py` | drama progress 增加 storyboard todo/done 状态。 |
| `src/web/templates.py` | 解锁站③ tab，站④继续 locked。 |
| `src/web/static.py` | 新增 storyboard grid 渲染、编辑、保存、排序、重生和时长 footer 交互。 |
| `tests/fixtures/drama/track_*_storyboard.json` | 新增 5 赛道原创 storyboard fixture 与 mock `alt_shots`。 |
| `tests/test_drama_storyboard_builder.py` | 覆盖 mock 生成、站②缺失、重生单镜、soft warning、prompt 组装。 |
| `tests/test_drama_storyboard_grid.py` | 覆盖 API 空态、生成、保存回读、双/零高光、重生、站②缺失、novel workspace、写锁冲突。 |
| `tests/test_drama_fixture_lint.py` | 覆盖 fixture 机器规则、禁用龙族专名、AI prompt 主观词和 `alt_shots` schema。 |
| `tests/_drama_base.py`、`tests/test_drama_view.py`、`tests/test_web_routes_get.py`、`tests/test_workspace_overview_drama.py` | 更新 drama 测试 helper 与站③状态/UI 断言。 |
| `AGENTS.md` | 记录项目记忆：每轮必须使用 `iter-start` + `iter-finish`，实施时可适当使用 subagents 节约主窗口上下文。 |
| `README.md`、`docs/AGENT_HANDOFF.md`、`docs/iterations/README.md`、`docs/iterations/iteration_080_drama_storyboard_grid.md` | 追加 iter080 索引并同步 SOP/Phase Status/计划/实施/验证/审查结论。 |

## 不在本轮范围

- 站④角色 + 角色库 + AI 绘画骨架（顺延下一轮短剧迭代）。
- drama_reviewer、整集组装、episodes 页、导出、Insights、多集重生。
- 站①②真模型路径补课、每站 job 化、`scripts/drama_smoke.sh`；按路线图留到真模型收口批。
- 真模型 smoke 实跑（铁律⑥，需用户明确授权）。

## Notes

- 本轮编号采用仓库真实最新迭代 +1，即 `080`；短剧路线图原“079 站③”内容整体平移到本轮执行。
- 本轮 fixture 均为原创短剧示例，不写入任何龙族原文片段。
- 站③ Web 端在 iter080 明确固定 mock-only，避免真实配置态误触模型；真模型 wiring 只保留在 runner 层，待 iter083 授权 smoke 与 job 化统一收口。
