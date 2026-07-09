# Iteration 081 - 短剧站④角色 + 角色库 + AI 绘画骨架

## Context

Iteration 080 已完成短剧站③分镜生成、Grid 编辑、重生本镜与 mock-only Web 闭环；站④仍处于 locked 状态。短剧批次的目标是把产品线从“前 2 站 mock 演示”推进到“剧本 + 分镜 + 角色三件套闭环”，因此下一步应补齐角色设定、角色库页与 AI 绘画骨架。

短剧路线图 `iteration_079_083_drama_module_roadmap.md` 原标“iter080 站④角色 + 角色库 + AI 绘画骨架”，但实际 iter079 被 capstone P2 占用、iter080 执行站③，故本轮按仓库真实最新编号平移为 iter081。默认计划文件 `~/.claude/plans/docs-rosy-wadler.md` 当前不存在；本轮立项依据为 handoff、iter080 记录、短剧路线图与只读 subagent 摸底结论。

## Plan

- 扩展 `src/drama_schemas.py`：新增 `DramaCharacter` / `CharacterSheet` 等角色 schema，覆盖角色 id、视觉签名、SD/Comfy prompt、LoRA token、锁定字段、agent suggestions 与角色引用图路径约束。
- 新增 `src/character_designer.py`：从站② setup + 站③ storyboard 抽取本集角色，支持 5 赛道 mock fixture 与真模型 wiring；本轮不实跑真模型。
- 实现 `merge_character_sheet()` 纯函数：锁定角色保护用户手编字段，agent 新结果进入 `agent_suggestions[]`；未锁定角色可更新，新角色追加，表驱动测试固化规格。
- 新增 `src/ai_draw_client.py`：`AI_DRAW_ENDPOINT` 未配置或 mock 时零网络生成 placeholder SVG；真 HTTP client 仅做安全骨架，包含 http/https scheme 白名单、超时、响应大小上限、key 脱敏与不落盘。
- 新增角色库 Web/API：站④生成/读取/保存/重画 preview、`/w/<name>/characters` 角色库页、只读 `character-ref` 图片端点；drama-only、站③前置、路径穿越 fail-closed、写入走 `_workspace_write_guard`。
- 解锁 Web 站④ tab：角色卡展示、prompt 编辑、锁定 checkbox、保存整表、重画 placeholder；drama progress 从 locked 改为 storyboard done 后 todo/done。
- 新增 5 赛道原创 characters fixtures 与测试，覆盖 schema、manual override、AI 绘画降级、图片端点安全、fixture 合规与无龙族专名。

## Acceptance

- 5 赛道 mock ①→②→③→④ 走通，生成 `data/characters/season_01.json` schema 合规；主角/反派 `visual_contrast_with` 互指成对，`lora_token` 为 ascii snake。
- 勾选 locked/manual override 后重跑站④，手编字段逐字节不变，agent 新建议进入 `agent_suggestions[]`；未锁定角色正常更新，新角色追加。
- `AI_DRAW_ENDPOINT` 未配置时零网络，返回 placeholder SVG；配置项进入 settings allowlist/secret mask，key 不写日志或 workspace 文件。
- `character-ref` 端点对非法 cid、`../`、绝对路径、跨目录文件均 400；缺图、缺目录、缺角色表均 graceful 空态。
- novel workspace 400；缺站③ storyboard 时 400 并提示回站③；无角色文件时写作页与角色库页不崩。
- fixture lint 通过：角色 prompt 无主观禁词、不含龙族专名，视觉对照字段成对，生成内容为原创短剧示例。
- 验收命令：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests`、`PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh`、`.venv/bin/python3 main.py preflight`、`OPENAI_MODEL=mock .venv/bin/python3 main.py preflight`。不跑真模型 smoke（铁律⑥）。

## Implementation Notes

- 新增 `character_paths()` 与 `DramaCharacter` / `CharacterSheet` / `ReferenceImage` schema，角色表固定落盘 `data/characters/season_01.json`，引用图路径限制在 workspace 内 `data/character_refs/`。
- `character_designer.run()` 复用站② setup 与站③ storyboard；mock 分支读取 5 赛道原创 fixture，真模型分支只 wiring 到 `LLMClient("drama_character").complete_json(CharacterSheet)`，本轮不实跑。
- `merge_character_sheet()` 采用 `manual_override` 作为唯一持久化锁定开关：锁定角色保留旧字段并追加 agent suggestion；未锁定角色允许被 incoming 覆盖，但保留既有 `reference_images`，避免重跑站④清空已生成参考图；suggestions 按 schema 上限保留最近 12 条。
- `ai_draw_client` 默认零网络写 deterministic SVG placeholder；真实 endpoint 骨架保留但 fail-closed：仅 http/https，固定 30s timeout，响应 5MB 上限，API key 只进 Authorization header，不写日志或 workspace 文件。收尾安全审查后补强公网地址校验，并且真实响应只接受 PNG/JPEG/WebP，拒绝第三方 SVG 与未知 content-type。
- Web 生成与重画本轮固定 `mock=True`，避免真实配置态误触模型或绘图服务；真模型/真绘图实跑留到 drama 真模型收口批。
- 新增 `/w/<name>/characters` 角色库页，并在 drama sidebar 加“角色库”；写作页 `#characters` deep-link 解锁，支持角色卡、prompt 编辑、锁定 checkbox、保存、重新生成、重画 placeholder。
- `character-ref` 端点只服务合法 cid/filename，限制图片扩展名白名单与 5MB 读取上限；跨目录、非法 id、坏文件类型均 fail-closed。
- `verify.sh` 按既有流程写入 gitignored `data/` / `outputs/` mock 验证产物；这些不是本轮提交内容。

## Acceptance Result

- 聚焦回归：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_drama_character_designer tests.test_drama_characters_api tests.test_drama_fixture_lint tests.test_drama_view tests.test_web_routes_get tests.test_web_settings` -> **121 tests OK**。
- 触达模块编译：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m py_compile src/drama_schemas.py src/character_designer.py src/ai_draw_client.py src/web/drama_view.py src/web/routes.py src/web/settings.py src/web/static.py src/web/templates.py` -> OK。
- 全量单测：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests` -> **1685 tests OK**。
- `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` -> exit 0；内部 `python3 -m unittest discover -s tests -v` 同样 **1685 tests OK**，随后 auto-pipeline / status / manifest / report / cost 检查通过。过程中 LiteLLM 远程 cost map 拉取超时但 fallback 到本地备份，不影响 exit 0。
- `.venv/bin/python3 main.py preflight` -> `PREFLIGHT: warn`，**FATAL none**；WARN 为当前真实配置态既有 token encoding/cache provider/default budget 提示。
- `OPENAI_MODEL=mock .venv/bin/python3 main.py preflight` -> `PREFLIGHT: ok`，**FATAL none / WARN none**。
- Web JS：提取 `src.web.static.JS_DASHBOARD` 到 `/tmp/iter081_app.js` 后 `node --check /tmp/iter081_app.js` -> OK。
- `git diff --check` -> OK。
- 铁律⑨代码审查：2 个只读 subagent 并行。Correctness 视角无 blocker，发现 2 个 P1 + 2 个 P2；已修 P1「锁定角色 suggestions 超过 12 后重跑 400」与 P1「未锁定角色重跑丢 `reference_images`」，已修 P2「未知 content-type 写 `.bin`」。P2「Web 重画固定 mock=True」与本轮计划一致，保留并在文档中明确真绘图实跑顺延。
- 铁律⑨安全审查：无 HIGH，发现 3 个 MED；已修 `AI_DRAW_ENDPOINT` SSRF 风险（公网地址校验）、真实绘图响应 SVG/未知类型落盘风险（仅 PNG/JPEG/WebP）、`character-ref` 无读取大小上限（扩展名白名单 + 5MB cap）。未发现 API key / `.env` 泄漏；未跑真模型 smoke。

## 文件变更汇总

| 文件 | 改动 |
| --- | --- |
| `src/drama_schemas.py` | 增加角色路径、引用图、角色、角色表 schema 与校验。 |
| `src/character_designer.py` | 新增站④角色 runner、prompt 组装、mock/真模型 wiring、合并规则。 |
| `src/ai_draw_client.py` | 新增 placeholder SVG 与真实绘图 HTTP client 安全骨架。 |
| `prompts/drama/character_designer.txt` | 新增站④角色设计师 prompt。 |
| `config/models.yaml` | 新增 `drama_character` task，使用 `DRAMA_MODEL` 与非流式配置。 |
| `src/web/routes.py` | 新增角色表 GET/POST/PUT、重画、引用图端点与角色库页面路由。 |
| `src/web/static.py` | 解锁 `#characters`，新增角色卡、编辑、保存、重生、重画与角色库页面逻辑。 |
| `src/web/templates.py` | 新增 drama sidebar“角色库”、角色库页面模板、站④ tab 文案。 |
| `src/web/drama_view.py` | `collect_drama_progress()` 接入站④ todo/done 状态。 |
| `src/web/settings.py` | settings allowlist/secret mask 增加 `DRAMA_MODEL`、`AI_DRAW_ENDPOINT`、`AI_DRAW_API_KEY`。 |
| `tests/fixtures/drama/track_*_characters.json` | 新增 5 赛道原创角色 fixture。 |
| `tests/test_drama_character_designer.py` | 新增角色 runner 与 merge 规则测试。 |
| `tests/test_drama_characters_api.py` | 新增角色 Web/API、placeholder、引用图安全测试。 |
| `tests/test_drama_fixture_lint.py`、`tests/test_drama_view.py`、`tests/test_web_routes_get.py`、`tests/test_web_settings.py` | 扩展 fixture lint、progress、路由、settings 回归。 |
| `docs/iterations/README.md`、本文件 | 登记 iter081 与验收记录。 |

## 不在本轮范围

- drama_reviewer、整集组装、episodes 列表/详情页。
- JSON/MD/CSV/Comfy 导出、Insights、第 2 集重生。
- 站①②真模型补课、站③/④真模型 smoke、每站 job 化、`scripts/drama_smoke.sh`。
- 小说主链路 10-20 章 capstone 真模型长跑。

## Notes

- 本轮立项显式使用 `iter-start` skill，并用 2 个只读 subagent 分别提炼 iter081 计划与摸底 drama 站④代码/文档边界。
- 仓库外默认计划文件 `~/.claude/plans/docs-rosy-wadler.md` 未找到；若用户另有新计划文件，实施前需补读并按最新计划调整。
- 收尾使用 `iter-finish` skill；README「项目阶段 SOP（实时状态）」与 `docs/AGENT_HANDOFF.md` Phase Status 已同步。
- 本轮真模型与真 AI 绘画 smoke 均未跑（铁律⑥）。Web 站④生成和重画保持 mock-only；真实绘图 client 只是安全骨架。
- 未跟踪 `续写工作台.pptx` 视为用户文件，保持不动。
