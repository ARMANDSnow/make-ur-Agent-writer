# Iteration 079-083 路线图 — 短剧（drama）模块实施规划

> **文档性质**：多轮迭代路线图（batch roadmap），不是单轮 iteration 记录。iter079-083 每轮开工时仍按惯例用 `/iter-start` 建各自的 8 段 iteration 文档，规划/实现时参考本文件的对应轮次分解与架构决策（ADR a-f）。实施中若偏离本路线图，在当轮 iteration 文档 Notes 登记，083 收官时统一回填产品文档 v2。
>
> **产出方式**：2026-07-04 规划会话（2 个 Explore agent 摸底现状 + 1 个 Plan agent 出方案 + 用户三项拍板），原始计划文件 `~/.claude/plans/iter-quizzical-lampson.md`。

## Context

**为什么做**：短剧模块是本项目继 novel 主链路之后的第二条产品线（产品定义书 `docs/product/short_drama_module.md` v1）。目标用户是自媒体 AI 短剧创作者——要的不是"AI 写剧本"，而是**剧本 + 分镜 + 角色三件套闭环**，产出直接喂 AI 绘画（SD/ComfyUI/即梦）。

**现状**：iter036 落了基础设施（workspace.type / wizard 分支 / 路由防御），iter037 落了 4 站向导前 2 站（`src/drama_planner.py` 站①核心设定 + `src/hook_designer.py` 站②钩子，**mock-only，真模型路径 `raise NotImplementedError`，routes 层 `mock=True` 硬编码，只支持 episode_01**）。之后主线转回 novel（iter038-078），站③④、drama_reviewer、AI 绘画 client、导出、episode 详情页全部未做。

**结果目标**：短剧从「向导前 2 站 mock 演示」推进到「4 站闭环 + 评审 + 4 种导出 + 多集重生 + 真模型路径打通」，批次末尾具备真模型 smoke 实跑条件（等授权）。

## 用户已拍板决策（本批不再讨论）

1. **排期**：短剧优先；novel 真模型 capstone 顺延到短剧批次后。短剧从 **iter079** 起（前置条件：iter078 先走完 `/iter-finish` 收尾提交，工作树不能把 P1 修复批与 drama 批次混入同一 diff）。
2. **真模型**：本批内打通全部 drama 文本 agent 的真模型路径（站③④新实现自带；站①②在 083 补课去掉 NotImplementedError）；批次末尾建 smoke 资产（铁律⑥：实跑必须等用户授权，未授权则批次以「资产就绪」收尾）。
3. **AI 绘画**：通用 HTTP client 骨架（`AI_DRAW_ENDPOINT`/`AI_DRAW_API_KEY` env 配置）+ mock placeholder 预览图（SVG 文本水印，零 pillow 依赖）；Comfy workflow .json 导出做全；**不实测真绘画 API**。
4. 沿用产品文档 §6 已拍板项：中文锁定、导出 JSON/MD/CSV/Comfy、season_no 预留 UI 单季、manual_override 只追加不覆盖、drama/novel 完全隔离（D4）。

## 迭代总览

| iter | 主题 | 核心交付 | 依赖 |
|---|---|---|---|
| **079** | 站③ 分镜 + grid 编辑器 | `drama_schemas.py` + `storyboard_builder.py`（真模型路径自带）+ 分镜 grid + `episode_paths()` helper + fixtures×5 | iter078 收尾提交 |
| **080** | 站④ 角色 + 角色库 + AI 绘画骨架 | `character_designer.py` + manual_override 合并纯函数 + `/w/<name>/characters` 页 + `ai_draw_client.py` + fixtures×5 | 079 |
| **081** | drama_reviewer + 整集组装 + episodes 页 | `drama_reviewer.py`（独立轻量）+ `assemble_episode()` + episodes 列表/详情 5-tab + fixtures×5 | 079+080 |
| **082** | 导出 ×4 + Insights + 第 2 集重生 | `comfy_workflow_exporter.py` + JSON/MD/CSV 导出 + insights 子页 + episode_no 全面参数化 + §3.2 重生流 + fixtures×5 | 081 |
| **083** | 真模型收口批 | 站①②补课 + models.yaml 5 task 收齐 + 每站 job 化（200→202）+ prompts 定稿 + `scripts/drama_smoke.sh` + 产品文档 v2 | 079-082 |

每轮惯例：8 段 iteration 文档、全量单测 mock 跑（.venv python，基线 1517+）、`/code-review high` + `/security-review`（铁律⑨）、commit 不 push（铁律⑤）。

## 关键架构决策（ADR a-f）

- **a. models.yaml 分 5 个 task**（`drama_plan/hook/storyboard/character/review`），共享 `model_env: "DRAMA_MODEL"` 一键切模型（PLANNER_MODEL 先例，同步进 settings.py ALLOWED_KEYS）。决定性理由：`LLMClient.complete_json` **无 per-call temperature 参数**（llm_client.py:432），温度只能 task 级配——review 要 0.1 低温、hook 要 0.7 高创意。全部 `stream: false`（iter055 教训：litellm 流式下 per-call 超时失效）。建议值：plan 0.6/1500、hook 0.7/1000、storyboard 0.5/4500（timeout 400）、character 0.4/3000、review 0.1/1500；task 随所属 iter 渐进入表。
- **b. 站生成调用：079-082 保持同步 POST（mock 毫秒级），083 与真模型同批迁移为 job**（产品 §4.1 终态；job 化唯一动机是真模型 10-60s 延迟，两者因果耦合同批上线改一次测一次）。前端从 079 起收敛进 `runStation()` 单一 helper 留 seam；083 生成端点 200→**202+job_id**，`runStation` 内切 start→poll（复用现有 pollJob 基建），job handler 是站 runner 薄封装+progress_cb 检查点（组装 0.2/LLM 0.7/落盘 0.9），白拿 cancel/busy 409/`web_jobs.jsonl` 持久化/离开守卫。保存类 PUT 永远同步（纯磁盘写）。API 一次性 breaking change 可接受（唯一消费者是自家 JS），同轮改写 API 层测试无双契约残留，站 runner 函数级单测不动。`/api/workspace/<name>/run` 通用端点的 drama 屏蔽保留，站间前置校验留在 drama 专用端点层。
- **c. 真模型路径形状**：新建 `src/drama_schemas.py`（pydantic，不进 novel 域 schemas.py，D4 隔离）；站 runner 统一签名 `run(workspace, *, mock=None, episode_no=1)`——`mock=None` 时按 `client.is_mock` 自动探测（全仓语义一致，铁律③保持：`OPENAI_MODEL=mock` 下永不构造网络调用），mock 分支走现有 fixture 加载字节不变（**不走** `_mock_json`——那是按 response_model 名分发的 novel 分发器）；真分支 `LLMClient(task).complete_json(Model)` 白拿两级 JSON repair（parse repair + schema repair）。**硬/软校验分层**：pydantic 硬校验只放结构性约束（高光恰 1、6-9 镜、时长 1-30s、shot_no 连续），craft 规则（总时长 ±3s、台词 ≤15 字/句、首镜 2-3s 特写/近景、末镜 8-10s）走 `validate_storyboard_soft()` 返 warnings——硬拒会触发 repair 重调烧钱且侵犯用户手编主权。创作规范 snapshot 全文注入保持（可复现性优先，~10K tokens/站），`_trim_snapshot_sections()` 裁剪杆备用，083 smoke 实测成本后再拍是否默认裁剪。
- **d. 分镜 grid 前端**：原生表单控件（select 景别·运镜 / number 时长 / textarea 画面·旁白·台词），**不用 contenteditable**（static.py 是 Python 字符串拼接 JS，粘贴净化/选区管理是高危区，反斜杠双写坑现存实例 static.py:1418/2527）；★ 高光列用单 name radio 组天然唯一 + 服务端 PUT 硬校验双保险；**拖拽砍成 ↑/↓ 按钮**（6-9 行不值 DnD 状态机复杂度，记 backlog）；保存粒度=整表 PUT 替换 + 服务端 shot_no 重排 + `workspace_reserved` 互斥 + `write_json` 原子（iter060 #14 先例）。施工红线：grid JS ≤350 行、禁新增正则字面量（必要时 `RegExp` 构造器串拼）、复用 `.tabs/.card/escapeHtml/showToast` 现组件。
- **e. fixture 策略**：新增 20 个——079 `track_{pinyin}_storyboard.json`×5（含 narrative + 内嵌 `alt_shots` 供「重生本镜」mock，不增文件数）、080 `_characters`×5（主角+反派全字段 + visual_contrast_with 互指）、081 `_review`×5（**全金路径 Approve**；Reject/Abstain 分支用测试内联构造，防演示流程莫名被打回）、082 `_hooks_ep2`×5。**内容合规机器断言化**（`test_drama_fixture_lint`）：总时长 60±3s、镜1 为 2-3s 特写/近景、恰 1 高光、末镜 8-10s、台词 ≤15 字/句、角色 prompt 无主观禁词、**不含龙族专名禁词表**（铁律②机器化防手滑；drama fixture 本身全为 Claude 原创内容，每轮 Implementation Notes 声明原创性）。已知局限文档化：用户选 30/90/120s 时 mock 仍返 60s 表。沿用 iter037 §A/§B 双轨约定：骨架占位先行跑通测试，创作内容随后替换不破 schema。
- **f. drama_reviewer 独立轻量实现（~200 行），不复用 novel reviewer 框架**——reviewer.py 964 行深度绑定 novel 域（linter 前置/entity_graph/personas/tier/多 agent 投票），drama 是 1 agent + 5 子分，复用需绕开 80% 框架。复用的是**模式**而非代码：① `complete_json` 两级 repair；② iter078 P1-1 分数护栏规格下沉到 pydantic validator（接受 int/float/纯数字字符串，拒绝 bool——`float(True)==1.0` 钻闸教训——与 NaN/Inf——json.loads 接受裸 NaN 字面量生产可达——clamp [0,10]）；③ **verdict 本地确定性推导**不信 LLM 自报（任一子分 <5→Reject+回站映射 `hook→站②、pace/ai_friendly→站③、character_consistency→站④、cliffhanger→站②`；全 ≥7→Approve；否则 Abstain+advisor；LLM 自报 verdict 仅 cross-check 不一致记 `verdict_warning`）；④ 解析失败 → Abstain + `review_parse_failed` + `needs_human_review=true`（drama 评审不 gate 破坏性动作、无自动重写循环，伪造 Reject 会无理由踢回用户——诚实 Abstain+人审标记即此处的 fail-closed）。**偏离产品文档 §4.1「复用 reviewer 投票框架」，083 出 v2 登记改判**。

## 每轮分解

### iter079 — 站③ 分镜生成 + grid 编辑器
- 新：`src/drama_schemas.py`（StoryboardShot/DramaStoryboard 含 narrative + soft 校验 + `episode_paths()` helper，从本轮起杜绝 `episode_01` 字面量继续扩散）、`src/storyboard_builder.py`（`run` + `rewrite_shot` 重生本镜，mock 取 fixture alt_shots；前置校验站② done）、`src/web/storyboard_grid.py`（GET/PUT handler，routes.py 只注册防膨胀——wizard.py 先例）、`prompts/drama/storyboard_builder.txt`（§三 AI 友好 + §四 黄金分割 3/12/25/20 + 输出 schema 与 pydantic 字段一字不差）、storyboard fixtures×5、`tests/test_drama_storyboard_builder.py` / `test_drama_storyboard_grid.py` / `test_drama_fixture_lint.py`
- 改：models.yaml +`drama_storyboard`；agents.yaml +段（诚实标注 documentation-only，083 收口，对口 iter078 P2「drama_agents 死配置」）；routes.py 注册 3 端点（生成 POST 本轮同步 200 / PUT / rewrite-shot POST）；drama_view.py 站③解锁逻辑；templates/static tab-③ empty-state→grid 实装 + `runStation()` seam
- 验收：5 赛道 mock ①→②→③ 走通、grid 编辑保存→GET 回读一致；高光唯一（UI radio + PUT 双 highlight 400 双层，零高光允许但 soft warning）；时长 footer 实时 ±3s 变色；重生本镜只换指定镜其余字节不变；无文件 CTA 不崩 / 站②未完成 400 带回站提示 / novel workspace 400（`_drama_endpoint_error` 复用）；fixture lint 全过
- 备注：narrative 归站③产出（与分镜同源一致 + 少一次 LLM 调用），偏离 §2.2 原设，记当轮 Context

### iter080 — 站④ 角色 + 角色库 + AI 绘画骨架
- 新：`src/character_designer.py`（从 setup+storyboard 抽出场角色 → 合并进 `data/characters/season_01.json`；**`merge_character_sheet()` 纯函数**：锁定行冻结+agent 产出只追加 `agent_suggestions[]`（D3）、未锁定行整体替换、新角色写入、缺字段按 incoming 为准——表驱动测试即规格）、drama_schemas 增补 DramaCharacter/CharacterSheet（id `^c\d{3}$`、lora_token ascii snake）、`src/ai_draw_client.py`（env 配置进 settings.py ALLOWED_KEYS+SECRET_KEYS 掩码；未配置/mock → `make_placeholder_svg(character_id, name)` 零依赖水印图；真调用 urllib 标准库 + scheme 白名单 http/https + 不 follow 跨 scheme 重定向 + 响应大小上限 + 超时 + key 永不入日志/workspace 文件）、`src/web/characters.py`（GET/PUT 角色表、POST redraw、GET `character-ref/<cid>/<file>` 只读图片端点：cid/filename 双正则 + resolve 后 `relative_to` 校验 + 不列目录）、`prompts/drama/character_designer.txt`（§五 LoRA 描述顺序 + 反主观词 + 视觉对照）、characters fixtures×5、测试 ×3（merge 表驱动 ≥8 case / ai_draw 降级+oversize+key 不入日志 / API）
- 改：models.yaml +`drama_character`；routes 注册；templates `_SECTIONS_DRAMA` +characters + 角色库页 + write tab-④ 实装；static 角色卡组件（预览图/特征/签名/prompt 编辑/锁定 checkbox/重画）；drama_view 站④状态；settings.py
- 验收：5 赛道 mock 生成 season_01.json schema 合规（contrast 互指成对）；**manual_override 回归**（勾选后重跑站④手编字段逐字节不变、建议进 suggestions、未锁角色正常更新）；铁律④ 无目录/无文件/图缺失全空态；`AI_DRAW_ENDPOINT` 未配置零网络（socket 哨兵，`tests/_socket_skip.py` 基建）；路径穿越（`../`/绝对路径/非法 cid）400
- security-review 重点：ai_draw_client（本批唯一外呼组件，SSRF/key 泄漏面）+ 图片端点

### iter081 — drama_reviewer + 整集组装 + episodes 页
- 新：`src/drama_reviewer.py`（ADR-f，落 `outputs/episodes/episode_{NN}.review.json`）、drama_schemas 增补 DramaSubScores（护栏 validator）/ DramaReview / `derive_verdict()` / REJECT_STATION_MAP / AdvisorSuggestion（**结构化** `{station, field|shot_no, new_value, reason}`，自由文本只展示不可 apply——fail-closed）、`src/drama_store.py`（`assemble_episode(workspace, n)` → episode_NN.json §2.2 全字段（ai_friendly_constraints 实算 + self_check + ending_hook 取选定钩）+ meta §2.3（verdict/sub_scores/cost_cny mock=0/highlight_shot_no/duration delta）+ **输入指纹**防组装后改分站文件的 stale）、`prompts/drama/drama_reviewer.txt`（§二§三§五§九 + 5 维满分标准）、review fixtures×5（金路径）、测试 ×3
- 改：models.yaml +`drama_review`；routes +5 端点（review / assemble / apply-suggestion——复用各站 PUT 校验落建议 / episodes / episode detail）；templates `_SECTIONS_DRAMA` +episodes + 列表页 + 详情 5-tab（剧本 narrative / 分镜只读复用 079 渲染 / 角色本集出场 / 评审 5 子分+advisor+一键 apply+Reject 回站 CTA / 导出 tab 占位 locked——iter062 先例）；static 复用章节详情 tab 基建（bindHashTabs/loadTabPanel）；write 向导尾部「评审+组装」CTA
- 验收：mock 全链 5 赛道到详情页 4 tab 有数据；verdict 三分支精确（`{hook:4}`→Reject+回站② CTA；`{pace:6}`→Abstain+建议卡+一键 apply 生效后提示需重评审；全≥7→Approve）；**子分护栏矩阵 ≥10 case**（"8" 字符串接受 / 8.4 clamp 取整规则明确 / NaN/Infinity 拒绝→按 0 计留 `score_warning` / bool 拒绝 / -3/15 clamp）；解析失败→Abstain 不伪造 Reject；重复组装幂等、缺前置 400 指明缺哪站；episode_NN.json 为唯一导出真源 + 详情页 stale 横幅「分站内容已变需重新组装」；无 episodes 目录列表页空态

### iter082 — 导出 ×4 + Insights + 第 2 集重生
- 新：`src/comfy_workflow_exporter.py`（`build_workflow(episode, characters)` 纯函数无网络：每镜 CheckpointLoaderSimple→CLIPTextEncode（ai_draw_prompt + 角色 prompt_template_sd 拼接，lora_token 以 LoraLoader 占位节点引用）→KSampler→VAEDecode→SaveImage；`_generator: "drama_comfy_exporter_v1"` 版本标记；文档明示「模板级导出，导入后需接线，不承诺 import 即跑」）、`src/web/drama_insights.py`（独立文件对齐 D4：成本按 llm_calls.jsonl `task` 前缀 `drama_` 聚合 + meta.cost_cny 双口径并列 / 时长达标率 `|estimate-target|≤3s` 占比 / 钩子类型分布）、hooks_ep2 fixtures×5、测试 ×3
- 改：drama_store +`to_markdown_table`/`to_csv`（**utf-8-sig** 保 Excel 中文）+ 导出同时落盘 §2.5 路径（`episode_NN.storyboard.csv/.md`、`episode_NN.comfy.json`）；routes `GET .../episode/<n>/export?format=json|md|csv|comfy`（白名单 + Content-Disposition）+ `POST .../next-episode`；**episode_no 全面参数化**（drama_planner/hook_designer/storyboard_builder/character_designer/drama_view/storyboard_grid 全部过 `episode_paths()`；重构独立 commit + ep1 字节不变断言）；§3.2 重生流：站①继承上集 core_setup **不调 LLM**（可改「本集主线推进」）、站② prompt 注入已用钩子清单（mock 取 ep2 fixture 断言必新）、站③注入 season 角色 visual_signature 清单（prompt 组装层断言含签名串）、站④「本集是否引入新角色」判定无新角色→`skipped`；templates/static episodes 多集行 + 导出 tab 实装 4 按钮 + insights 页 + `_SECTIONS_DRAMA` +insights + 向导「开始第 N+1 集」CTA
- 验收：ep1 四格式导出 golden 断言（mock 确定性）+ §2.5 落盘路径 + comfy.json 可解析每镜有 SaveImage；ep2 全流程（继承设定显示 / 3 候选与 ep1 已选不同 5 赛道断言 / 无新角色 skipped 可直达评审 / 列表 2 行）；insights 0/1/多集不崩（铁律④）、mock 成本恒 0 标注「真模型后生效」；grep 断言站点模块无 `episode_01` 字面量残留；csv BOM 头字节断言；format fuzz（`../../`→400）
- 已知限制记录：「钩子必新」真模型下无确定性保证（prompt 注入 + reviewer cliffhanger 维度兜底）

### iter083 — 真模型收口批
- 站①②补课：`drama_planner.py`/`hook_designer.py` 去 NotImplementedError → ADR-c 统一形状（`LLMClient("drama_plan"/"drama_hook")` + `complete_json`；drama_schemas 补 DramaSetup / HookCandidates——hooks 恰 3、type Literal 三选一各一）；routes 层 `mock=True` 硬编码移除
- models.yaml drama_plan/drama_hook 入表 5 task 收齐（ADR-a 值）；settings.py ALLOWED_KEYS +`DRAMA_MODEL`；agents.yaml drama 段收口（接线 `sections_required` 裁剪或明确标注 documentation-only，二选一诚实记录，了结 iter078 P2「死配置」项）
- job 化（ADR-b）：jobs.py 注册 5 步 `drama-plan/-hooks/-storyboard/-characters/-review`（storyboard 带 `params.mode: full|rewrite_shot`，handler=站 runner 薄封装+progress_cb+episode_no）；5 生成端点 200→**202+job_id**；`runStation()` 切 start→poll+取消按钮；API 层测试同轮迁移无双契约
- prompts ×5 定稿终审（对照创作规范、输出 schema 与 pydantic 字段一字不差、禁 markdown 包裹条款）
- `scripts/drama_smoke.sh`：单赛道（重生）真模型全链 ①→②→③→④→评审→组装→四导出 + llm_calls 成本汇总；`--confirm-real-smoke` 必选 gate（铁律⑥）；**drama 无 CLI 子命令**——smoke 以最小 python 入口驱动（`main.py` 加 `drama-run` 子命令或 `python3 -m` 直调站 runner，实施时定；standalone 脚本必须显式处理 `OPENAI_MODEL`——iter078 踩坑：unittest 之外没有 mock 安全网）
- 成本预估回填：单集 ≈ 5 站 ×（snapshot ~10K tokens + 输入）→ deepseek 约 ¥0.15-0.25/集（与产品 meta 示例 0.18 吻合）；meta.cost_cny 走 `estimate_cost_since` 每站入账（write-book job 先例）
- `docs/product/short_drama_module.md` **v2 变更摘要表**（narrative 归站③ / reviewer 独立改判 / 导出细节 / agents.yaml 接线 / 60s fixture 局限 / 成本实测），commit `docs(drama): bump short_drama_module.md to v2`
- 验收：mock 全量单测 OK；`test_drama_real_path_guard`（mock 下 5 站零网络；`DRAMA_MODEL=deepseek/deepseek-chat` 形状 monkeypatch 断言 task 名与 response_model 正确不实调）；smoke 脚本存在 + 缺 confirm 拒跑 + mock dry-run 全链通过；job 5 步注册/busy 409/cancel 生效/web_jobs.jsonl 落行；（**用户授权后**）smoke 实跑结果回填 Acceptance Result，未授权则明记「资产就绪，smoke 待授权」

## 跨 iter 公共风险

1. **static.py 拼接 JS 膨胀**（5506 行起步，预计 +1500）：每轮 JS 预算写进施工单（079≤350/080≤300/081≤400/082≤350/083≤150），超 7000 行 backlog 立项拆独立 bundle（非本批）。
2. **schema 五轮演化漂移**：`drama_schemas.py` 单一真源 + 落盘文件带 `schema_version:1` + 每轮向后兼容读旧文件测试。
3. **产品文档偏离沉默积累**（narrative 归站③ / reviewer 独立 / 60s fixture 局限）：偏离随轮登记 iteration Notes，083 统一 v2 变更摘要——不让偏离沉默。
4. **083 体量偏大**（站①②补课+job 化+prompts+smoke）：若单轮吃不下按仓库先例拆 083/083a——job 化与真模型必须同批不可拆，可拆出去的是 prompts 终审/产品 v2 文档。
5. **测试命名**：定为 `test_drama_*.py` feature 线命名（`test_iterNNN_*` 留给跨模块修复批），5 轮测试互相可发现防重复。

## 验证方式

- 每轮：`PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest discover -s tests` 全绿（用 .venv，裸 python3 缺 pydantic）+ `bash scripts/verify.sh` + `python3 main.py preflight` + 铁律⑨双审查
- Web 验证：preview 起 server → wizard 建 drama workspace → 逐站走 mock 全链 → episodes 详情页 → 导出四格式下载
- 批次终验（083 后）：mock 下 5 赛道 ×2 集全链回归 + smoke 脚本 dry-run；真模型 smoke 等用户授权后实跑并回填
