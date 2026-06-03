# Iter 035 · P2/P3 防御纵深清扫 + 短剧模块产品定义书（开题）

> **文档性质**：本文件是 **Codex 执行前的施工单**。Codex 执行完后请把验收结果追加到本文末尾「Codex Run Log」节；iter 收官时再由 reviewer 写「Acceptance Result」节。
>
> **执行人**：Codex（**仅 §A**）+ Claude（**仅 §B**，由 Claude 直接落盘 `docs/product/short_drama_module.md`，与 Codex 无关）
> **验收人**：Claude（§A 走代码级 + 单测 + dispatcher，沙箱内全程跑完；§B 由用户单独 review）
> **基线**：commit `23f4fd2` (Iteration 034 acceptance)

---

## 1. Context（为什么做这一轮）

iter 034 验收时 Codex 自带 subagent 暴露了 4 个 P2/P3 防御纵深项；同时用户提出后续要加 **AI 短剧剧本 + 表格创作** 模块（表格 = 短剧创作的辅助数据，bundle 在一起）。

本轮节奏：

- **§A 小工程动作**：把 4 个 follow-up 关闭，让代码层卫生达到 iter 036 开新模块前的洁净度。Codex 30-45min 内完成。
- **§B 大方向调研**：用户已选定"短剧 + 表格 bundle"，**iter 035 不写一行新模块代码**，但 Claude 把产品定义、用户场景、输入输出 schema、与现有 novel 模块的复用与新增、IA 集成草图、agent prompt 骨架沉淀成 `docs/product/short_drama_module.md`。iter 036 起 Codex 照着干。

明确边界：iter 035 不动 `workspace_type` 抽象、不改后端 schema、不加新 sidebar 入口。

---

## 2. Scope（2 个交付物）

| # | 名称 | 类型 | 执行人 | 复杂度 |
|---|---|---|---|---|
| A | 4 个 P2/P3 防御纵深清扫 | 代码 + 单测 + 文档补注 | **Codex** | 小 |
| B | 短剧模块产品定义书 `docs/product/short_drama_module.md` | PM 文档（~600 行） | **Claude** | N/A（与 Codex 无关） |

下面 §A 详展开；§B 是元任务说明，Codex 跳过。

---

### A. 4 个 P2/P3 防御纵深清扫

#### A.1 trash.py helper 自防（P2）

**问题**：`restore_trash_entry` / `purge_trash_entry` 把 `entry` 字符串直接拼 `paths.WORKSPACE_DIR / TRASH_DIR_NAME / entry`，自身不防 `../` 和保留名。当前 route 层 `_TRASH_ENTRY_RE` 已拦，但 hard-rm 集中点必须自防 —— 未来 CLI、单测、其它 module 调用绕过 route 时这是最后一道闸。

**修法**：在 `src/web/trash.py` 新增私有 helper：

```python
# Workspaces under _trash/ MUST match this shape. The route layer
# enforces a similar regex at the edge; helper-level enforcement
# closes the door for any future caller that bypasses the route.
_ENTRY_NAME_RE = re.compile(r"^(?P<original>.+)__(?P<ts>[0-9]{8}_[0-9]{6}(?:_\d+)?)$")  # 已存在

_SAFE_ENTRY_RE = re.compile(
    r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿-]{0,63}"
    r"__[0-9]{8}_[0-9]{6}(?:_\d+)?$"
)
_RESERVED_ORIGINAL_NAMES = frozenset({"legacy", "_trash", "", ".", ".."})


def _safe_entry_path(entry: str) -> Tuple[bool, str]:
    """Validate ``entry`` and return (ok, message).

    Rejects path-traversal segments ('..', '/'), empty/dot names, and
    entries whose ``original`` portion is a reserved sentinel like
    ``legacy`` (paths sentinel) or ``_trash`` (would resurrect the
    trash root itself).

    Returns (True, "") on success; (False, reason) otherwise.
    Callers map failures to ``entry_not_found`` / 400 / 404 per the
    existing API convention — the failure shape is the existing error
    space, not a new one.
    """
    if not entry or "/" in entry or "\\" in entry or ".." in entry.split("__")[0]:
        return False, "malformed_entry"
    if not _SAFE_ENTRY_RE.match(entry):
        return False, "malformed_entry"
    match = _ENTRY_NAME_RE.match(entry)
    original = match.group("original") if match else ""
    if original in _RESERVED_ORIGINAL_NAMES:
        return False, "reserved_name"
    return True, ""
```

然后在 `restore_trash_entry` 和 `purge_trash_entry` 入口第一行调用：

```python
def restore_trash_entry(entry: str) -> Tuple[bool, str]:
    ok, reason = _safe_entry_path(entry)
    if not ok:
        return False, reason  # "malformed_entry" or "reserved_name"
    # ...剩余逻辑不变...


def purge_trash_entry(entry: str) -> Tuple[bool, str]:
    ok, reason = _safe_entry_path(entry)
    if not ok:
        return False, reason
    # ...剩余逻辑不变...
```

> **Codex 注意**：route 层 (`api_trash_restore` / `api_trash_purge`) 的 `_validate_trash_entry` 已经做类似拦截；本子项是**纵深防御**，不是替换 route 层 —— 两道都要保留。route 层失败仍返 400/404；helper 层失败由 route 转发为 404（因为路由处的 `restore_trash_entry` 接 `entry_not_found` → 404，`reserved_name` 是新 reason，请在 route handler 里加映射 `{"reserved_name": 400}`）。

#### A.2 Plan viewer 5 处 `Array.isArray` 兜底（P2）

**问题**：`src/web/static.py` 的 `renderPlanChapters` / `renderDecisions` 用 `(plan && plan.chapters) || []` 做兜底。当 `chapter_plan.json` 的 `chapters` 是字符串、对象等非数组时（手工编辑或上游 bug），表达式不抛错（truthy），但下一步 `.map` 抛 `TypeError`，整个 Plan 初始化 catch 后清空其它 pane。

**修法**：5 处替换：

| 位置（行号 ±2，按 iter 034 的 static.py 计） | 原表达式 | 改为 |
|---|---|---|
| `renderPlanChapters` line ~1208 `chapters` | `(plan && plan.chapters) \|\| []` | `Array.isArray(plan && plan.chapters) ? plan.chapters : []` |
| `renderPlanChapters` line ~1230 `key_events` | `(c.key_events \|\| [])` | `(Array.isArray(c.key_events) ? c.key_events : [])` |
| `renderPlanChapters` line ~1233 `relationships_in_play` | `(c.relationships_in_play \|\| [])` | `(Array.isArray(c.relationships_in_play) ? c.relationships_in_play : [])` |
| `renderDecisions` `decisions.votes` | `(decisions && decisions.votes) \|\| []` | `Array.isArray(decisions && decisions.votes) ? decisions.votes : []` |
| `renderDecisions` `v.agent_votes` | `(v.agent_votes \|\| [])` | `(Array.isArray(v.agent_votes) ? v.agent_votes : [])` |

> **Codex 注意**：以上行号是参考；以 `grep -n` 找实际位置为准。**只改这 5 处**，不要顺手改 `Insights` 或 `Chapters` 的同类表达式（那些不在本子项范围）。

#### A.3 `bindHashTabs` 白名单匹配（P3）

**问题**：`src/web/static.py:903-907`：

```javascript
const initial = (location.hash || "").replace(/^#/, "");
if (initial) {
  const t = document.querySelector('.tab[data-tab="' + initial + '"]');
  if (t) activate(t);
}
```

恶意 / 畸形 hash 如 `#x"]; ...` 让 `querySelector` 因非法 CSS 选择器抛 `SyntaxError`，进而让 `initPlan` / `initChapterDetail` boot 失败。

**修法**：白名单：

```javascript
const _ALLOWED_TAB_KEYS = [
  "body", "review", "lint", "advisor", "history",
  "chapters", "outline", "decisions",
];
const initial = (location.hash || "").replace(/^#/, "");
if (initial && _ALLOWED_TAB_KEYS.indexOf(initial) >= 0) {
  const t = document.querySelector('.tab[data-tab="' + initial + '"]');
  if (t) activate(t);
}
```

> **Codex 注意**：白名单 8 项 = 现有 chapter detail 5 个 tab (body / review / lint / advisor / history) + plan viewer 3 个 tab (chapters / outline / decisions)。未来加 tab 必须同步扩白名单 —— 在 `_ALLOWED_TAB_KEYS` 上方加一行注释提示。

#### A.4 `iter 034 PLAN.md §7 Run Log` 补注（P3）

**问题**：iter 034 Codex Run Log 里写 `FAILED (errors=6)`，但没在同段解释这 6 个是预存在的沙箱 socket-bind 错误。subagent 读起来略暧昧。

**修法**：在 `docs/iterations/iteration_034_PLAN.md` §7 Run Log 的 `FAILED (errors=6)` 那一行**紧接的下一行**插入：

```
# 注：6 ERROR 全部是 iter 032 起就存在的沙箱 socket.bind PermissionError
# （影响 test_web_server.* 4 个 + test_web_hardening.ServeHostWarningTests.* 2 个），
# 非本轮回归。详见 iter 032 验收记录。
```

#### A.5 新增测试（Codex 自加）

**A.5.1 `tests/test_web_trash.py` 加 3 用例**：

```python
def test_safe_entry_path_rejects_path_traversal(self) -> None:
    from src.web.trash import _safe_entry_path
    for bad in ("../alpha", "../../etc", "alpha/../beta", "a\\b__20260101_120000"):
        ok, reason = _safe_entry_path(bad)
        self.assertFalse(ok, f"{bad!r} should be rejected")
        self.assertEqual(reason, "malformed_entry")


def test_safe_entry_path_rejects_reserved_names(self) -> None:
    from src.web.trash import _safe_entry_path
    for bad in ("legacy__20260101_120000", "_trash__20260603_000000"):
        ok, reason = _safe_entry_path(bad)
        self.assertFalse(ok, f"{bad!r} should be rejected")
        self.assertEqual(reason, "reserved_name")


def test_safe_entry_path_accepts_well_formed(self) -> None:
    from src.web.trash import _safe_entry_path
    for good in ("alpha__20260101_120000", "alpha__20260101_120000_2", "龙族__20260101_120000"):
        ok, reason = _safe_entry_path(good)
        self.assertTrue(ok, f"{good!r} should be accepted; got {reason}")
```

**A.5.2 `tests/test_web_routes_get.py` 加 2 用例**：

```python
def test_static_js_has_array_isarray_guards(self) -> None:
    """A2 — Plan renderer must not blow up on malformed-but-truthy JSON."""
    status, _ct, body = routes.dispatch("GET", "/static/app.js")
    self.assertEqual(status, 200)
    js = body.decode("utf-8")
    # 5 sites should now use Array.isArray
    self.assertGreaterEqual(js.count("Array.isArray("), 5)


def test_static_js_has_tab_whitelist(self) -> None:
    """A3 — bindHashTabs must filter against a whitelist."""
    status, _ct, body = routes.dispatch("GET", "/static/app.js")
    self.assertEqual(status, 200)
    js = body.decode("utf-8")
    self.assertIn("_ALLOWED_TAB_KEYS", js)
    for kw in ("body", "review", "lint", "advisor", "history", "chapters", "outline", "decisions"):
        self.assertIn(f'"{kw}"', js)
```

---

### B. 短剧模块产品定义书（Claude 直接写，与 Codex 无关）

落盘文件：`docs/product/short_drama_module.md`（~600 行）

文档大纲（Claude 内部记录，Codex 不需要看）：
1. 用户场景与目标
2. 内容 schema（Fountain syntax + 4 张辅助表）
3. 工作流
4. 与现有 novel 模块的复用 / 改动 / 新增
5. WebUI IA 集成草图
6. Agent prompt 骨架
7. 边界与不在本期内
8. 与 iter 036+ 的桥接

文档目的：让 iter 036 起的 Codex 施工单作者基于此文档直接拆 §A/§B/§C。**iter 035 不动一行代码与之相关**。

---

## 3. Codex 必须遵守的工程铁律

1. **本轮只做 §A 4 件子项**，§B 是 Claude 元任务，**禁止读、改、生成 `docs/product/short_drama_module.md`**。
2. 不要新增任何 CSS 颜色字面量。
3. 不要引入任何前后端依赖。
4. 不要 push。提交 message：`Iteration 035: P2/P3 defense-in-depth cleanup`
5. **不要改 iter 026 / 030 / 032 / 033 / 034 的 22 个保留 JS 标识符** 和协议表达式：
   ```
   loadTabPanel / scheduleReadiness / readinessRequestSeq /
   writeBookJobRunning / readinessTimer /
   submit.disabled = writeBookJobRunning || data.status === 'blocked' /
   showToast / showDeleteModal / jumpToParagraph / initInsights /
   data-jump-line / __pending_toast /
   initPlan / renderPlanChapters / renderOutlineMarkdown / renderDecisions /
   _mdToHtml / data-plan-pane /
   initTrash / reloadTrashList / showPurgeModal /
   data-trash-restore / data-trash-purge
   ```
6. **不要重做视觉**。本轮禁止动 iter 032 design tokens / `.btn-*` / `.badge` / `.card` / `.sidebar` / `.tabs` / `.modal*` 样式。
7. A2 只改我列出的 5 处 `Array.isArray`，不要顺手扩到 Insights / Chapters 等其它 renderer。
8. A4 是改 `iter 034 PLAN.md`，**不动 §7 之外**的任何字。

---

## 4. Codex 自检清单（commit 前必跑）

```bash
# 1. 全套 unittest
.venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
# 必须只剩 iter 032 起就存在的 6 个沙箱 socket.bind 错误。
# 沙箱安全集（92→111→应继续 ≥111）应全过；本轮新加 5 个测试，预期 116 OK。

# 2. dispatcher 级冒烟（12 条路径不变）
.venv/bin/python3 -c "
from src.web import routes
for p in ['/', '/trash', '/wizard', '/settings',
          '/w/longzu/', '/w/longzu/plan', '/w/longzu/continue',
          '/w/longzu/chapters', '/w/longzu/chapter/1',
          '/w/longzu/reviews', '/w/longzu/insights', '/w/longzu/jobs']:
    print(routes.dispatch('GET', p)[0], p)
"

# 3. 关键字符串存在（22 + 本轮新增 3 = 25）
.venv/bin/python3 -c "
from src.web import static
required = [
    # iter 026-034 保留
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    # iter 035 新增
    '_ALLOWED_TAB_KEYS',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
# Array.isArray 应至少 5 次
n = static.JS_DASHBOARD.count('Array.isArray(')
assert n >= 5, f'Array.isArray count = {n}, expected >= 5'
print(f'all {len(required)} identifiers present; Array.isArray count = {n}')
"

# 4. trash helper 自防生效
.venv/bin/python3 -c "
from src.web.trash import _safe_entry_path
cases = [
    ('../alpha', False),
    ('legacy__20260101_120000', False),
    ('_trash__20260101_120000', False),
    ('alpha/../beta', False),
    ('alpha__20260101_120000', True),
    ('龙族__20260603_120000', True),
]
for entry, expected_ok in cases:
    ok, reason = _safe_entry_path(entry)
    assert ok == expected_ok, f'{entry!r}: ok={ok}, reason={reason}, expected={expected_ok}'
print('trash safe-entry self-defense verified')
"
```

把以上 4 块输出**原文**贴进文末「Codex Run Log」节，**注意 §A.4 已经要求 iter 034 Run Log 加 6-ERROR 注脚**，本轮 §7 同样规则：在 `FAILED (errors=6)` 那一行下补一行注脚。

---

## 5. 验收：Claude 走代码级（沙箱内全程可跑，无需浏览器）

| # | 项 | 方法 |
|---|---|---|
| V1 | A1 实现存在 | grep `_safe_entry_path` in `src/web/trash.py` + 检查 `restore_trash_entry` / `purge_trash_entry` 第一行调用 |
| V2 | A1 单测全过 | `unittest tests.test_web_trash` 必含 3 个新用例 |
| V3 | A1 route 层 `reserved_name` 映射 | grep route handler 含 `"reserved_name": 400` 或等效映射 |
| V4 | A2 5 处 `Array.isArray` | `static.JS_DASHBOARD.count('Array.isArray(') >= 5` |
| V5 | A2 不动 Insights / Chapters | diff vs 23f4fd2 限定在 `renderPlanChapters` + `renderDecisions` 函数体内 |
| V6 | A3 白名单生效 | grep `_ALLOWED_TAB_KEYS` + 8 个 token 字符串 |
| V7 | A4 iter 034 PLAN 注脚 | grep `iter 032 起就存在的沙箱` in `docs/iterations/iteration_034_PLAN.md` |
| V8 | dispatcher 12 路径 200 | 见 §4 第 2 块输出 |
| V9 | 22 + 1 个保留标识符 | 见 §4 第 3 块输出 |
| V10 | 全套 unittest | 6 ERROR 与 iter 034 同；无新 ERROR / FAIL |

**任一不过：退回 Codex 修。**

---

## 6. 明确不在本迭代范围（留给 iter 036+）

- 短剧模块的所有代码（workspace.type 字段 / wizard 类型选择 / drama agent / 表格 grid 编辑器 / Fountain 渲染）
- restore "覆盖原有同名工作区" 选项
- `_trash/` 自动定期清理
- Toast SSE/WS push
- 暗色模式
- 章节全文搜索
- workspace rename UI
- 章节 .md/.epub 导出
- 真模型 capstone

---

## 7. Codex Run Log（Codex 执行后填）

> Codex 请在这里粘贴 §4 四块命令的原文输出。**`FAILED (errors=6)` 那一行下方加一行注脚**：
> ```
> # 注：6 ERROR 全部是 iter 032 起就存在的沙箱 socket.bind PermissionError
> # （影响 test_web_server.* 4 个 + test_web_hardening.ServeHostWarningTests.* 2 个），
> # 非本轮回归。
> ```

```
$ .venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5

----------------------------------------------------------------------
Ran 468 tests in 1.932s

FAILED (errors=6)
# 注：6 ERROR 全部是 iter 032 起就存在的沙箱 socket.bind PermissionError
# （影响 test_web_server.* 4 个 + test_web_hardening.ServeHostWarningTests.* 2 个），
# 非本轮回归。

$ .venv/bin/python3 -c "
from src.web import routes
for p in ['/', '/trash', '/wizard', '/settings',
          '/w/longzu/', '/w/longzu/plan', '/w/longzu/continue',
          '/w/longzu/chapters', '/w/longzu/chapter/1',
          '/w/longzu/reviews', '/w/longzu/insights', '/w/longzu/jobs']:
    print(routes.dispatch('GET', p)[0], p)
"
20:07:46 - LiteLLM:WARNING: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno 8] nodename nor servname provided, or not known. Falling back to local backup.
20:07:47 - LiteLLM:WARNING: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
20:07:47 - LiteLLM:WARNING: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
200 /
200 /trash
200 /wizard
200 /settings
200 /w/longzu/
200 /w/longzu/plan
200 /w/longzu/continue
200 /w/longzu/chapters
200 /w/longzu/chapter/1
200 /w/longzu/reviews
200 /w/longzu/insights
200 /w/longzu/jobs

$ .venv/bin/python3 -c "
from src.web import static
required = [
    # iter 026-034 保留
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    # iter 035 新增
    '_ALLOWED_TAB_KEYS',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
# Array.isArray 应至少 5 次
n = static.JS_DASHBOARD.count('Array.isArray(')
assert n >= 5, f'Array.isArray count = {n}, expected >= 5'
print(f'all {len(required)} identifiers present; Array.isArray count = {n}')
"
all 24 identifiers present; Array.isArray count = 5

$ .venv/bin/python3 -c "
from src.web.trash import _safe_entry_path
cases = [
    ('../alpha', False),
    ('legacy__20260101_120000', False),
    ('_trash__20260101_120000', False),
    ('alpha/../beta', False),
    ('alpha__20260101_120000', True),
    ('龙族__20260603_120000', True),
]
for entry, expected_ok in cases:
    ok, reason = _safe_entry_path(entry)
    assert ok == expected_ok, f'{entry!r}: ok={ok}, reason={reason}, expected={expected_ok}'
print('trash safe-entry self-defense verified')
"
trash safe-entry self-defense verified
```

Subagent read-only audit:

- A2-A4 reviewer（static / docs / tests）: No P1/P2/P3 findings.
- A1 reviewer（trash / routes）: found P2 that `re.match(...$)` accepts a final newline. Fixed by switching trash/route validators and `_split_entry_name` to `fullmatch()`, adding helper regression for `\n` / `\r`, and adding route regression for `%0A`; focused `tests.test_web_trash tests.test_web_routes_post` passed 28 tests OK.

---

## 8. Acceptance Result（Claude 验收后填）

> 由 Claude（reviewer）填写 §5 的 V1-V10 结果 + 通过 / 退回意见。

```
(待 Claude 验收后填写)
```
