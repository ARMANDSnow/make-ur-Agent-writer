# Iteration 075 - 全文搜索（跨章检索）

## Context

iter074 上线了「章节版本 diff」（读者/编辑向质量复核工具）。iter075 是 iter074-077 路线图的第二步，与 diff 同为主线读者/编辑向工具，但更净新增、更独立。目的是**跨章正文内容检索**——做连贯性核查（实体/伏笔/关键词跨章定位）与长书导航：「我在续写里提到某实体，原著/KB 里它是什么状态？」一键定位。

**与现有能力的区分**：章节列表页已有 `#chapter-search`（`templates.py:881`）——那只是对**已加载表格**按「章节 ID / 标题」做本地过滤，不读正文。iter075 是跨章**正文内容**全文检索，二者互补。

已确认 scope 决策（用户 2026-07-01 拍板）：
1. 搜索默认覆盖 **原文 + 续写 + 知识库** 三语料，UI 带勾选开关可临时缩小范围。
2. **顺带对 iter074 的 diff / 历史 tab 做轻度前端美化**（对齐设计系统，不改 diff 逻辑）。
3. **就近清一小部分 i18n**（表头 / step 标签等残留的 workspace→作品）。

规模基线：longzu ~110 章 / ~330 万字，纯内存 `str.lower().find` 全扫 <100ms；真正成本是磁盘 IO，用 `normalized_file` 级读缓存收口。暂不建索引（>500 章 / >50M 字再上 SQLite FTS5）。

## Plan

- **search.py（新，纯函数模块）** → 大小写不敏感字面子串匹配（不编译用户正则，规避 ReDoS）；三语料 `original/draft/kb`；`Snippet{text,offsets}` + `SearchHit` + `SearchResult{truncated,truncated_reasons}`；有界收口（query/snippets/chapters 三维，无静默截断）；graceful 降级；`normalized_file` 级读缓存。入口 `search_workspace(query, *, sources=None)`，调用方须在 `use_workspace` 上下文内。
- **web-search-page** → `routes.py` 加 `api_workspace_search` + `render_workspace_search_page` + 2 行路由 + import；`templates.py` 加 `render_workspace_search` + 侧栏「搜索」入口；`static.py` 加 `.search-*` CSS + `initSearch` JS（`pageKind==="search"` 门控，DOM + offsets 安全高亮，绝不 innerHTML 拼正文）。
- **iter074-diff-polish** → `static.py` 对 `.diff-*`（historytab）做轻度观感打磨，不改数据流与端点。
- **i18n-small-cleanup** → 扫 templates 用户可见残留英文/`workspace` 表头/step 标签替换一小批，本段列出清单。

## Acceptance

- 单测：新建 `tests/test_search.py`（纯函数矩阵）+ `tests/test_web_search.py`（`routes.dispatch` 端到端），`OPENAI_MODEL=mock`（铁律③）全绿，总数从 1385 上升。
- `bash scripts/verify.sh` + `python3 main.py preflight` 通过。
- Web 端到端：`/w/<longzu>/search` 搜已知实体（如「路明非」）截图证明三色 badge / `<mark>` 高亮 / 命中计数 / 空态 / 勾选切换语料 / draft 结果跳章节详情；iter074 历史 tab 美化后观感截图。
- `/code-review high` + `/security-review`（铁律⑨，重点 query 注入 / ReDoS / XSS）结论回填本文件。

## Implementation Notes

**lower() 长度保险的最终方案（比计划更简洁）**：计划里设想「片段级 `len(seg)!=len(seg.lower())` → offsets=[] 不高亮」。实现时想通一条更强的不变式：`str.lower()` 只让码点扩张（`'İ'.lower()` 长度 1→2）、从不收缩，故 `len(text)==len(text.lower())` ⟺ 每码点 1:1 映射 ⟺ lower 串下标在原串精确对应。于是 `_scan_unit` 里：长度相等 → `display=原文`（保留大小写高亮）；不等（罕见外文边角）→ `display=hay_lower`，offset 仍精确落在 display 上。**高亮永远正确，无需 offsets=[] 降级**，仅在极罕见情形把该片段显示为小写。`test_length_changing_lower_no_crash_no_misalign` 用 `İstanbul` 覆盖此分支。

**match_count 与片段截断解耦**：`match_count` 用 `hay_lower.count(needle_lower)`（C 实现、非重叠、与 `_find_all` 推进语义一致）记真实总数；片段仅取前 `MAX_SNIPPETS_PER_CHAPTER` 个。故「命中 6 处只显示 5 段」时用户仍看到「6 处」且 `truncated_reasons` 含 `snippets:<key>`（无静默截断）。

**draft 文件名坑**：`chapter_03.partial.md` 的 `Path.stem` == `chapter_03.partial`，用 `re.match(r"^chapter_(\d+)$", stem)` 正好排除（`.partial` 破坏纯数字尾），同时 `\d+` 兼容 3 位章号（`chapter_100`）。计划里担心的 `int(split("_")[1])` 崩溃被规避。

**i18n 实际替换清单（4 处，就近小范围，铁律⑦）**：`templates.py` — ① 3 处 `<label>workspace 名</label>`→`<label>作品名</label>`（novel/drama/premise 三个创建表单；只改 label 文本，`<input name="workspace">` 表单字段名不动，后端契约不变）；② `创建 drama workspace`→`创建短剧作品`。表头（`<th>verdict/step/...`）多为技术术语且有测试断言风险，本轮不动。

**iter074 diff 美化实际改动项（只观感、不碰数据流/端点）**：`.diff-panel` 加 `border-top` 分隔上方 meta；`.diff-controls select` 加卡片式边框 + jade focus ring；`.diff-view` 加 `max-height:480px` 滚动 + `box-shadow`；`.diff-line.diff-add/del` 加左侧 3px accent 竖条（jade/sienna）便于快速扫描增删。

**搜索页竞态防护**：`initSearch` 用 `seq` 单调递增，`fetch` 回调只在 `mine===seq` 落地——快速打字时旧响应不会覆盖新结果。250ms 防抖 + Enter 立即搜 + source 勾选变即重渲。

**XSS 高亮全 DOM 构建**：`buildSnippet` 按 offsets 把片段切成 `[textNode, <mark>(textNode), …]`，`renderSearchHit` 用 `textContent` 写标题/计数/badge，全程零 `innerHTML` 拼正文；`showEmpty` 也用 `textContent` 写含用户 query 的「未找到「X」」文案。越界 offset 静默跳过。

## Acceptance Result

**单测**：`.venv`(Python 3.13)`unittest discover` = **1415 tests OK**（较 iter074 的 1385 +30：`test_search.py` 19 + `test_web_search.py` 11）。含命中/未命中/空 query graceful/空 workspace/正则特殊字符字面量/ReDoS 输入秒回/大小写不敏感 offset 指原文/跨章排序/有界三维(query_len·snippets·chapters)/**悬空 reason 修复回归**/sources None-vs-空语义/XSS 片段原样/坏 manifest 容错/读缓存 read_text=1/lower 长度保险/KB fail-open/to_dict JSON 化；route 端到端命中/空 q→200/缺 q→200/非法名→400/不存在→404/**sources 作用域**/URL 编码中文/XSS body 合法 JSON/页面渲染/drama novel-only guard。

> 注：`bash scripts/verify.sh` 用裸 `python3`(系统 3.9)会有 3 个**既有环境 error**（`test_book_runner*` 的 `dict|None` PEP604 运行时 + `test_context_budget` 缺 `tiktoken`），全在本轮未碰的文件，与 iter075 无关；权威套件是 `.venv` discover（与历史「tests OK」口径一致）。`python3 main.py preflight`(venv) 仅 WARN/INFO 无 FATAL。新增文件在系统 3.9 下 `py_compile` 通过。

**Web 端到端**（preview_* + 合成 demo workspace「sdemo」，验完即删，零版权原文）：`/w/sdemo/search` 搜「星火」→ 4 单元按 **续写→原文→原文→知识库** 排序、三色 source badge、amber `<mark>` DOM 高亮、命中计数、换行折叠+省略号、汇总「共 N 处命中 · M 个单元」；draft 结果链 `/w/sdemo/chapter/1`、原文/KB 为只读 span；**取消勾选「原文」→ 后端 `sources=draft,kb` 作用域重搜**（日志实证）、全部取消→「请选择检索范围」不发请求；空态/无结果态齐全；console 全程无报错。iter074 历史 tab 美化后：面板分隔线、卡片式版本选择器 + focus ring、带边框滚动 diff 视图、增删行左侧 accent 竖条，均正常渲染。

**铁律⑨ 代码审查**：
- `/code-review high`（3 finder 并行：search.py 正确性 / 前端 XSS+API / 跨文件约定复用）→ 修 2 真实问题 + 1 顺带：① **[HIGH-value] `truncated_reasons` 悬空引用**（>200 章且每章 >5 命中时被 MAX_CHAPTERS 丢弃的章仍留 `snippets:chXXX`）→ 改为从最终存活 hits 派生，顺带简化 `_search_*` 去 reason 管道；② **[MED] API 忽略 `sources` 参数**（前端只能客户端过滤 → 过滤后 truncated 提示误导 + 无谓全扫）→ sources 透传后端做作用域检索，total_matches/truncated 变准确；③ **[LOW] source 勾选无防抖** → 补 250ms debounce。**未采纳**（附理由）：showEmpty「XSS」实为 textContent 安全；catch「竞态」误读（已有 `mine===seq` 守卫）；chapter_no 范围（后端由真实草稿派生 + 详情页已校验 1-9999）；fail-open 过宽（铁律④ 且已 `_log_degraded` 记录）；render 复用（8+ 同模式函数的更广重构，铁律⑦）。
- `/security-review`（聚焦 sub-task 审 iter075 攻击面）→ **无 HIGH/MEDIUM 漏洞**。核实：XSS 全 DOM textNode 无 innerHTML 拼正文（confidence 95%）；路径穿越——读取路径全来自 manifest `normalized_file`(pipeline 写) + `drafts_dir().glob` + workspace 名 `_validate_workspace_name` 拒 `/\..`（98%）；无正则/SQL/模板/subprocess 注入，query 只进 `str.find`（99%）；workspace 线程本地隔离；KB `respect_start_point=True` 过滤起点后剧透；零 `.env`/API key（铁律①）。
- **未修风险**：无。所有 finder 真实问题已修并加回归测试；安全无残留。

## 文件变更汇总

| 文件 | 改动 |
|---|---|
| `src/search.py` | 新增：跨章全文检索纯函数模块 |
| `src/web/routes.py` | `api_workspace_search` + `render_workspace_search_page` + 2 路由 + import |
| `src/web/templates.py` | `render_workspace_search` + 侧栏「搜索」+ i18n 小清理 |
| `src/web/static.py` | `.search-*` CSS + `initSearch` JS + iter074 diff 轻度美化 |
| `tests/test_search.py` | 新增：纯函数测试矩阵 |
| `tests/test_web_search.py` | 新增：route 端到端测试 |
| `docs/iterations/README.md` | 追加索引 |
| `docs/AGENT_HANDOFF.md` | 追加 Phase Status |
| `README.md` | SOP 表 + 时间戳 |

## 不在本轮范围

SQLite/FTS 索引、模糊/前缀/相关度打分、用户正则模式、drama 语料搜索、跨 workspace 全局搜索、char-level diff、iter074 diff tab 信息架构深度重做。

## Notes

**教训 / 设计要点**：
- **`str.lower()` 长度不变式**是本轮高亮正确性的地基：lower 只让码点扩张从不收缩，故 `len(text)==len(text.lower())` ⟺ 1:1 映射 ⟺ 下标精确对应。这条不变式让「命中定位在 lower 串、切片高亮在原串」成立，比原计划的「片段级 offsets=[] 降级」更简洁且高亮永不丢失。
- **铁律⑨ 真的抓到了东西**：3-finder code-review 抓到 truncated_reasons 悬空引用（纯逻辑，测试没覆盖到 200+ 章边界）+ API 忽略 sources（前后端契约不一致）。两个都不是崩溃级，但都是「看起来对、边界上错」的类型——正是审查的价值区。误报也多（6 个候选里 2 个真、其余误读/超范围），高 effort 召回偏置的预期形态。
- **合成 demo workspace 做 Web 验证**：为避免截图展示龙族/天龙原文（铁律②），建了全虚构的 `sdemo`（搜索词「星火」）验完即删。比在真 workspace 上验证更干净，且对三语料排序/badge/高亮有完全控制。

**后续候选**：iter076 长跑可靠性硬化（面板拒稿不 halt 整书 + 每章预算预留 + 每阶段超时 + 心跳文件 + crash 自恢复）是 iter077 真模型 capstone 的前置门。搜索延伸：SQLite FTS5（>500 章/>50M 字触发，dataclass schema 已与 FTS `snippet()/offsets()` 对齐，届时只换 `_search_*` 实现）/ 结果分页 / KB 起点过滤视图 / char-level diff。

**对铁律的影响**：无新增。本轮严守铁律①（零 .env/key）②（合成内容验证不写原文）④（全路径 fail-open）⑤（只 commit 不 push）⑦（i18n/iter074 美化范围如实标注，未扩到计划外文件）⑧⑨（SOP/handoff 同步 + 双审查）。
