# Iter 034 · Plan viewer + Trash 闭环 + delete race fix

> **文档性质**：本文件是 **Codex 执行前的施工单**，不是事后总结。Codex 执行完后请把验收结果追加到本文末尾的「Codex Run Log」节；iter 收官时再由 reviewer 写「Acceptance Result」节。
>
> **执行人**：Codex
> **验收人**：Claude（会用浏览器自动化跑真实用户流程 + 读代码 + 跑 unittest）
> **基线**：commit `6d72334` (Iteration 033 acceptance)

---

## 1. Context（为什么做这一轮）

iter 033 把"删除"和"看数据"补齐之后，仍有两个高频用户痛点：

1. **看不到写作蓝图**。`outputs/debate/chapter_plan.json` 是 "下一章该写什么" 的权威来源，`outline.md` 是 6-agent 辩论后的全局走向，`decisions.json` 是关键岔路的裁决记录 —— 但 UI 完全没有入口。用户要么 `cat` jsonl，要么记不住。**这是"写作前打开 WebUI 第一眼应该看的页面"**。
2. **删了之后没有回头路**。iter 033 把 workspace 软删除到 `_trash/` 已经工作，但 UI 里既无法列出回收站、无法 restore、也无法 purge。要清理只能去 shell。同时 Mendel 审核标记的 P2 **delete-vs-job-start race**（busy-check 与 rename 之间存在数毫秒窗口）还在。

iter 034 把这两件事一起做掉。**不引入新设计 token、不动 iter 032 的 design system、不引入新依赖**。所有视觉复用 iter 032 的 tokens + iter 033 的 modal + Insights 渲染套路。

---

## 2. Scope（2 个交付物）

| # | 名称 | 类型 | 复杂度 |
|---|---|---|---|
| A | Plan viewer 子页面 `/w/{name}/plan` | UI + API + 测试 | 中-大 |
| B | Trash 闭环 + delete race fix | UI + API + 并发测试 | 中 |

下面每个交付物单独列「目标 / 后端契约 / 前端模板与 JS / 测试 / 验收硬指标」。

---

### A. Plan viewer (`/w/{name}/plan`)

#### A.1 目标

新增工作区子页面 `/w/{name}/plan`，**3 个 tab**：

1. **章节计划**（默认 tab）：从 `chapter_plan.json` 渲染每章一张卡片，展示 `chapter_no / title / opening_scene / key_events / relationships_in_play / ending_hook / target_chinese_chars / plot_purpose`。**已经有 draft 的章节卡顶部加一条 verdict 徽章**（复用 iter 032 `verdictBadge`）。
2. **大纲 outline.md**：从 `outline.md` 渲染。**用一个 ≤50 行的极简 markdown 渲染器**（`#` / `##` / `###` → `<h1-3>`、`- ` 开头行 → `<ul><li>`、空行段落分隔、其它行原样段落）。**禁止引入任何 markdown 库**。
3. **辩论决议**：从 `decisions.json` 渲染 `topic` + `aggregation_method` + 每个 `votes[]` 一张卡（`question` / `result` / for[] / against[] / `agent_votes` 折叠详情）。

**顶部摘要条**：`overall_arc` 一行 + `start_chapter_id` + `plan_fingerprint` (短哈希 8 位) + `已写 N / 计划 M`。

侧栏：把「计划」项插在 `_WORKSPACE_SECTIONS` 里 `("continue", ...)` 和 `("chapters", ...)` 之间。

#### A.2 后端契约

新增文件 **`src/web/plan_view.py`**：

```python
"""iter 034: aggregate chapter_plan.json + outline.md + decisions.json
for the Plan viewer page.

Pure read-only aggregation. No LLM calls, no writes. Caller enters the
workspace context.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import paths
from ..utils import read_json_optional


def collect_plan() -> Dict[str, Any]:
    plan = read_json_optional(paths.chapter_plan_path(), {})
    if not isinstance(plan, dict):
        plan = {}
    decisions = read_json_optional(paths.debate_decisions_path(), {})
    if not isinstance(decisions, dict):
        decisions = {}
    outline_md = ""
    outline_path = paths.outline_path()
    if outline_path.exists():
        try:
            outline_md = outline_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            outline_md = ""
    draft_chapters = _draft_chapter_numbers()
    return {
        "plan": plan,
        "outline_md": outline_md,
        "decisions": decisions,
        "draft_chapters": draft_chapters,
    }


def _draft_chapter_numbers() -> List[int]:
    drafts = paths.drafts_dir()
    if not drafts.exists():
        return []
    nums: List[int] = []
    for md in drafts.glob("chapter_*.md"):
        try:
            nums.append(int(md.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(nums)
```

新增 handler + 路由（在 `src/web/routes.py`）：

```python
def api_workspace_plan(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .plan_view import collect_plan
    with use_workspace(name):
        return _json(200, collect_plan())


def render_workspace_plan_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_plan(name, list_workspaces()))
```

注册（仿现有 insights 那两行）：

```python
("GET", re.compile(r"^/w/(?P<name>[^/]+)/plan/?$"),
 lambda name, **_: render_workspace_plan_page(name)),
("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/plan/?$"),
 lambda name, **_: api_workspace_plan(name)),
```

#### A.3 前端模板 + JS

**A.3.1 侧栏注册**

在 `src/web/templates.py` 把 `_WORKSPACE_SECTIONS` 改为（**只插一行**）：

```python
_WORKSPACE_SECTIONS: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    ("continue", "续写", "continue"),
    ("plan", "计划", "plan"),
    ("chapters", "章节", "chapters"),
    ("reviews", "评审", "reviews"),
    ("insights", "数据", "insights"),
    ("jobs", "任务", "jobs"),
)
```

**A.3.2 模板**

新增 `render_workspace_plan(name, workspaces)`（仿 iter 033 `render_workspace_insights` 同结构）：

```python
def render_workspace_plan(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">计划</p>'
        '<h1>写作蓝图</h1>'
        '<p class="muted">章节计划 · 全局大纲 · 辩论决议。所有来源都是只读 JSON / Markdown，本页不发起新调用。</p>'
        '</div>'
        '<div id="plan-summary" class="cluster"></div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="chapters">章节计划</button>'
        '<button class="tab" data-tab="outline">大纲</button>'
        '<button class="tab" data-tab="decisions">辩论决议</button>'
        '</div>'
        '<div class="tab-panel active" id="tab-chapters" data-plan-pane="chapters">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-outline" data-plan-pane="outline">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-decisions" data-plan-pane="decisions">'
        '<p class="muted">载入中…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 计划",
        page_kind="plan",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("计划", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="plan"),
        workspace=name,
    )
```

**A.3.3 JS（在 `JS_DASHBOARD` 里新增；dispatcher 加 `if (pageKind === "plan") return initPlan();`）**

```javascript
async function initPlan() {
  const chBox = document.querySelector('[data-plan-pane="chapters"]');
  const olBox = document.querySelector('[data-plan-pane="outline"]');
  const dcBox = document.querySelector('[data-plan-pane="decisions"]');
  const sumBox = document.getElementById("plan-summary");
  if (chBox) chBox.innerHTML = skeleton(4);
  try {
    const data = await fetchJson(wsUrl("/plan"));
    renderPlanSummary(sumBox, data);
    renderPlanChapters(chBox, data.plan || {}, data.draft_chapters || []);
    renderOutlineMarkdown(olBox, data.outline_md || "");
    renderDecisions(dcBox, data.decisions || {});
  } catch (err) {
    if (chBox) chBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}

function renderPlanSummary(box, data) {
  if (!box) return;
  const plan = data.plan || {};
  const drafts = data.draft_chapters || [];
  const fp = plan.plan_fingerprint ? String(plan.plan_fingerprint).slice(0, 8) : "—";
  const target = plan.target_chapters || (plan.chapters || []).length || 0;
  box.innerHTML =
    '<span class="badge no-dot">起点 <code>' + escapeHtml(plan.start_chapter_id || "—") + '</code></span>' +
    '<span class="badge no-dot">指纹 <code>' + escapeHtml(fp) + '</code></span>' +
    '<span class="badge no-dot">已写 ' + drafts.length + ' / 计划 ' + target + '</span>';
}

function renderPlanChapters(box, plan, draftChapters) {
  if (!box) return;
  const chapters = (plan && plan.chapters) || [];
  const arc = (plan && plan.overall_arc) || "";
  if (!chapters.length) {
    box.innerHTML = '<p class="muted">尚无章节计划。先在「续写」里生成一份。</p>';
    return;
  }
  const draftSet = new Set(draftChapters);
  const arcHtml = arc
    ? '<div class="alert info" style="margin-bottom:16px"><strong>整体走向：</strong>' +
      escapeHtml(arc) + '</div>'
    : '';
  const cards = chapters.map(function (c) {
    const written = draftSet.has(c.chapter_no);
    const head =
      '<div class="card-header" style="align-items:flex-start">' +
      '<div><p class="eyebrow ornament">第 ' + c.chapter_no + ' 章</p>' +
      '<h3>' + escapeHtml(c.title || "(无标题)") + '</h3></div>' +
      (written
        ? '<span class="badge ready">已写</span>'
        : '<span class="badge no-dot">未写</span>') +
      '</div>';
    const events = (c.key_events || []).map(function (e) {
      return '<li>' + escapeHtml(e) + '</li>';
    }).join("");
    const rels = (c.relationships_in_play || []).map(function (r) {
      return '<span class="badge no-dot">' + escapeHtml(typeof r === "string" ? r : JSON.stringify(r)) + '</span>';
    }).join(" ");
    const body =
      '<div class="card-body">' +
      (c.opening_scene
        ? '<p><strong>开场：</strong>' + escapeHtml(c.opening_scene) + '</p>'
        : '') +
      (events ? '<div><strong>关键事件</strong><ul>' + events + '</ul></div>' : '') +
      (rels ? '<div><strong>涉及关系</strong><div class="cluster" style="margin-top:6px">' + rels + '</div></div>' : '') +
      (c.ending_hook
        ? '<p><strong>结尾钩子：</strong>' + escapeHtml(c.ending_hook) + '</p>'
        : '') +
      (c.plot_purpose
        ? '<p class="muted"><strong>定位：</strong>' + escapeHtml(c.plot_purpose) + '</p>'
        : '') +
      (c.target_chinese_chars
        ? '<p class="muted">目标字数：' + c.target_chinese_chars + '</p>'
        : '') +
      '</div>';
    return '<div class="card" style="margin-bottom:16px">' + head + body + '</div>';
  }).join("");
  box.innerHTML = arcHtml + cards;
}

function renderOutlineMarkdown(box, md) {
  if (!box) return;
  if (!md || !md.trim()) {
    box.innerHTML = '<p class="muted">outline.md 不存在或为空。</p>';
    return;
  }
  box.innerHTML = '<div class="card"><div class="card-body reading-body">' +
    _mdToHtml(md) + '</div></div>';
}

function _mdToHtml(md) {
  // ≤50-line bespoke renderer. No lib. Handles: #/##/### headings,
  // - bullets (consecutive), blank-line paragraphs, otherwise raw line.
  const lines = md.replace(/\\r\\n/g, "\\n").split("\\n");
  const out = [];
  let inList = false;
  function closeList() { if (inList) { out.push("</ul>"); inList = false; } }
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.replace(/\\s+$/, "");
    if (!line.trim()) { closeList(); continue; }
    let m = /^(#{1,3})\\s+(.*)$/.exec(line);
    if (m) {
      closeList();
      const level = m[1].length;
      out.push("<h" + level + ">" + escapeHtml(m[2]) + "</h" + level + ">");
      continue;
    }
    m = /^\\-\\s+(.*)$/.exec(line);
    if (m) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push("<li>" + escapeHtml(m[1]) + "</li>");
      continue;
    }
    closeList();
    out.push("<p>" + escapeHtml(line) + "</p>");
  }
  closeList();
  return out.join("");
}

function renderDecisions(box, decisions) {
  if (!box) return;
  const votes = (decisions && decisions.votes) || [];
  if (!votes.length) {
    box.innerHTML = '<p class="muted">decisions.json 不存在或没有 votes。</p>';
    return;
  }
  const head =
    '<div class="alert info" style="margin-bottom:16px">' +
    '<strong>主题：</strong>' + escapeHtml(decisions.topic || "(未命名)") +
    '　·　<strong>聚合：</strong>' + escapeHtml(decisions.aggregation_method || "—") +
    '　·　<strong>transcript 段：</strong>' + (decisions.transcript_items || 0) +
    '</div>';
  const cards = votes.map(function (v) {
    const fors = (v.for || []).join("；") || "—";
    const againsts = (v.against || []).join("；") || "—";
    const agents = (v.agent_votes || []).map(function (a) {
      return '<li><strong>' + escapeHtml(a.agent_name || "?") + '</strong> · ' +
        escapeHtml(a.position || "—") + '：' + escapeHtml(a.reason || "—") + '</li>';
    }).join("");
    return (
      '<div class="card" style="margin-bottom:12px">' +
      '<div class="card-header"><h3>' + escapeHtml(v.question || "(无问题)") + '</h3></div>' +
      '<div class="card-body">' +
      '<p><strong>裁决：</strong>' + escapeHtml(v.result || "—") + '</p>' +
      '<p><strong>支持：</strong>' + escapeHtml(fors) + '</p>' +
      '<p><strong>反对：</strong>' + escapeHtml(againsts) + '</p>' +
      (agents
        ? '<details><summary class="muted">agent_votes (' + (v.agent_votes || []).length + ')</summary><ul>' + agents + '</ul></details>'
        : '') +
      '</div></div>'
    );
  }).join("");
  box.innerHTML = head + cards;
}
```

#### A.4 测试

**A.4.1** `tests/test_web_routes_get.py` 加：

```python
def test_workspace_plan_page_renders(self) -> None:
    status, _ct, body = routes.dispatch("GET", "/w/alpha/plan")
    self.assertEqual(status, 200)
    html = body.decode("utf-8")
    self.assertIn('data-plan-pane="chapters"', html)
    self.assertIn('data-plan-pane="outline"', html)
    self.assertIn('data-plan-pane="decisions"', html)
    # sidebar 应有「计划」链接 active
    self.assertIn('href="/w/alpha/plan"', html)

def test_api_workspace_plan_returns_aggregates(self) -> None:
    status, data = self._get_json("/api/workspace/alpha/plan")
    self.assertEqual(status, 200)
    for k in ("plan", "outline_md", "decisions", "draft_chapters"):
        self.assertIn(k, data)
```

**A.4.2** 新建 `tests/test_web_plan_view.py`：

```python
"""iter 034: Plan viewer aggregation unit tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web.plan_view import collect_plan
from src.web.workspace_ctx import use_workspace


class PlanViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        (ws / "data").mkdir(parents=True)
        (ws / "outputs" / "drafts").mkdir(parents=True)
        (ws / "outputs" / "debate").mkdir(parents=True)
        (ws / "outputs" / "debate" / "chapter_plan.json").write_text(
            json.dumps({
                "target_chapters": 3,
                "overall_arc": "arc",
                "start_chapter_id": "alpha_ch001",
                "plan_fingerprint": "abc1234567890",
                "chapters": [
                    {"chapter_no": 1, "title": "t1", "key_events": ["e1", "e2"]},
                    {"chapter_no": 2, "title": "t2"},
                    {"chapter_no": 3, "title": "t3"},
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (ws / "outputs" / "debate" / "outline.md").write_text(
            "# 标题\n\n## 二级\n\n- 项 a\n- 项 b\n\n段落正文。\n",
            encoding="utf-8",
        )
        (ws / "outputs" / "debate" / "decisions.json").write_text(
            json.dumps({
                "topic": "T",
                "aggregation_method": "majority",
                "transcript_items": 12,
                "votes": [
                    {"question": "Q1", "result": "R1", "for": ["A"], "against": [],
                     "agent_votes": [{"agent_name": "X", "position": "agree", "reason": "ok"}]}
                ],
            }), encoding="utf-8",
        )
        # 1 draft only
        (ws / "outputs" / "drafts" / "chapter_01.md").write_text("body", encoding="utf-8")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_collect_plan_full(self) -> None:
        with use_workspace("alpha"):
            data = collect_plan()
        self.assertEqual(data["plan"]["target_chapters"], 3)
        self.assertIn("二级", data["outline_md"])
        self.assertEqual(data["decisions"]["votes"][0]["question"], "Q1")
        self.assertEqual(data["draft_chapters"], [1])

    def test_collect_plan_missing_files_returns_empties(self) -> None:
        # Wipe debate/ contents
        debate = paths.WORKSPACE_DIR / "alpha" / "outputs" / "debate"
        for f in debate.iterdir():
            f.unlink()
        with use_workspace("alpha"):
            data = collect_plan()
        self.assertEqual(data["plan"], {})
        self.assertEqual(data["outline_md"], "")
        self.assertEqual(data["decisions"], {})
        self.assertEqual(data["draft_chapters"], [1])
```

---

### B. Trash 闭环 + delete race fix

#### B.1 目标

1. 新顶级页 `/trash`（**全局，不属于单一 workspace**），列出 `_trash/*` 所有条目，支持 **restore**（rename 回原名）和 **purge**（真递归 rm + 二次确认）。
2. 顶栏在 `⚙ 设置` 左侧加 `♻ 回收站` 链接。
3. 修 Mendel P2 race：把 `workspace_running_job` 检查 + `rename` 包到一个 workspace-scoped reservation lock 里。

#### B.2 后端契约

**B.2.1 扩 `src/web/trash.py`**（在现有 `soft_delete_workspace` 后追加）：

```python
import shutil
from datetime import datetime
from typing import List


def list_trash_entries() -> List[Dict[str, Any]]:
    """Scan workspaces/_trash/* and return per-entry metadata."""
    root = paths.WORKSPACE_DIR / TRASH_DIR_NAME
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        original_name, _, ts = name.partition("__")
        deleted_at = ""
        if ts:
            # ts shape: YYYYMMDD_HHMMSS optionally suffixed _N
            base = ts.split("_")[0] + ts.split("_")[1] if "_" in ts else ts
            try:
                dt = datetime.strptime(base[:15], "%Y%m%d%H%M%S")
                deleted_at = dt.isoformat(timespec="seconds")
            except (ValueError, IndexError):
                deleted_at = ts
        size_bytes = 0
        file_count = 0
        for path in entry.rglob("*"):
            if path.is_file():
                file_count += 1
                try:
                    size_bytes += path.stat().st_size
                except OSError:
                    continue
        out.append({
            "entry": name,
            "original_name": original_name,
            "deleted_at": deleted_at,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "file_count": file_count,
        })
    return out


def restore_trash_entry(entry: str) -> Tuple[bool, str]:
    """Move workspaces/_trash/<entry>/ back to workspaces/<original_name>/.
    Returns (ok, message). If <original_name> already exists, returns
    (False, "name_collision") — caller maps to HTTP 409."""
    src = paths.WORKSPACE_DIR / TRASH_DIR_NAME / entry
    if not src.is_dir():
        return False, "entry_not_found"
    original_name, _, _ = entry.partition("__")
    if not original_name:
        return False, "malformed_entry"
    target = paths.WORKSPACE_DIR / original_name
    if target.exists():
        return False, "name_collision"
    src.rename(target)
    return True, str(target.relative_to(paths.WORKSPACE_DIR))


def purge_trash_entry(entry: str) -> Tuple[bool, str]:
    """Hard-delete workspaces/_trash/<entry>/ via shutil.rmtree. No undo."""
    src = paths.WORKSPACE_DIR / TRASH_DIR_NAME / entry
    if not src.is_dir():
        return False, "entry_not_found"
    shutil.rmtree(src)
    return True, "purged"
```

**B.2.2 加 `src/web/jobs.py:workspace_reserved`** 上下文管理器（在 `workspace_running_job` 后追加）：

```python
from contextlib import contextmanager

@contextmanager
def workspace_reserved(workspace: str):
    """Lock workspace for the duration of the with block. Raises
    RuntimeError('workspace_busy:<jid>') if already locked. Used by
    destructive ops like delete to close the race between busy-check
    and the destructive action itself."""
    with _WORKSPACE_LOCK:
        existing = _WORKSPACE_JOBS.get(workspace)
        if existing:
            raise RuntimeError(f"workspace_busy:{existing}")
        _WORKSPACE_JOBS[workspace] = "__reserved_delete__"
    try:
        yield
    finally:
        with _WORKSPACE_LOCK:
            if _WORKSPACE_JOBS.get(workspace) == "__reserved_delete__":
                del _WORKSPACE_JOBS[workspace]
```

> **Codex 注意**：现有 `start_job` 已经持 `_WORKSPACE_LOCK` 检查并写入 `_WORKSPACE_JOBS[workspace]`。`workspace_reserved` 占位 `__reserved_delete__` 后，`start_job` 会因为 workspace already busy 返 RuntimeError，正是想要的效果。

**B.2.3 改 `api_workspace_delete`**（routes.py:240 周围）：把 busy-check + 调 trash 包进 `with jobs.workspace_reserved(name):`：

```python
def api_workspace_delete(name: str, body: bytes) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict) or payload.get("confirm") != name:
        return _json(400, {"error": "confirm field must equal the workspace name"})
    from . import trash as _trash
    try:
        with jobs.workspace_reserved(name):
            ok, msg = _trash.soft_delete_workspace(name)
            if not ok:
                return _json(404 if msg == "workspace_not_found" else 500, {"error": msg})
            _clear_overview_cache()
            return _json(200, {"trashed_to": msg})
    except RuntimeError as exc:
        m = str(exc)
        if m.startswith("workspace_busy:"):
            return _json(409, {"error": "workspace busy",
                               "running_job_id": m.split(":", 1)[1]})
        raise
```

**B.2.4 新增 4 个 trash API handler**（routes.py 末尾）：

```python
def api_trash_list() -> Tuple[int, str, bytes]:
    from . import trash as _trash
    return _json(200, {"entries": _trash.list_trash_entries()})


_TRASH_ENTRY_RE = re.compile(r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿-]{0,63}__[0-9]{8}_[0-9]{6}(?:_\d+)?$")


def _validate_trash_entry(entry: str) -> bool:
    return bool(_TRASH_ENTRY_RE.match(entry))


def api_trash_restore(entry: str) -> Tuple[int, str, bytes]:
    if not _validate_trash_entry(entry):
        return _json(400, {"error": "invalid trash entry"})
    from . import trash as _trash
    ok, msg = _trash.restore_trash_entry(entry)
    if not ok:
        code = {"entry_not_found": 404, "name_collision": 409, "malformed_entry": 400}.get(msg, 500)
        return _json(code, {"error": msg})
    _clear_overview_cache()
    return _json(200, {"restored_to": msg})


def api_trash_purge(entry: str, body: bytes) -> Tuple[int, str, bytes]:
    if not _validate_trash_entry(entry):
        return _json(400, {"error": "invalid trash entry"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict) or payload.get("confirm") != entry:
        return _json(400, {"error": "confirm field must equal the entry name"})
    from . import trash as _trash
    ok, msg = _trash.purge_trash_entry(entry)
    if not ok:
        return _json(404 if msg == "entry_not_found" else 500, {"error": msg})
    return _json(200, {"purged": entry})


def render_trash_page() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_trash(list_workspaces()))
```

**B.2.5** _ROUTES 注册（4 行）：

```python
("GET", re.compile(r"^/trash/?$"), lambda **_: render_trash_page()),
("GET", re.compile(r"^/api/trash/?$"), lambda **_: api_trash_list()),
("POST", re.compile(r"^/api/trash/(?P<entry>[^/]+)/restore/?$"),
 lambda entry, **_: api_trash_restore(entry)),
("POST", re.compile(r"^/api/trash/(?P<entry>[^/]+)/purge/?$"),
 lambda entry, _body=b"", **_: api_trash_purge(entry, _body)),
```

#### B.3 前端模板 + JS

**B.3.1** 顶栏加 ♻ 链接。把 `_topbar_actions()` 改为：

```python
def _topbar_actions(extra: str = "") -> str:
    base = (
        '<a class="btn btn-ghost" href="/trash">♻ 回收站</a>'
        '<a class="btn btn-ghost" href="/settings">⚙ 设置</a>'
        '<a class="btn btn-primary" href="/wizard">＋ 新建</a>'
    )
    return extra + base
```

**B.3.2** 新增 `render_trash(workspaces)` 模板：

```python
def render_trash(workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">回收站</p>'
        '<h1>已删除的作品</h1>'
        '<p class="muted">软删除自 iter 033 起进入这里；可 restore 回原名（同名冲突需手动改名），或永久 purge。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="card flush"><div class="card-body" id="trash-list"></div></div>'
        '</section>'
    )
    return _render_shell(
        title="回收站 · 写作工作台",
        page_kind="trash",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), ("回收站", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces),
        workspace="",
    )
```

**B.3.3** JS（dispatcher 加 `if (pageKind === "trash") return initTrash();`；新模块在 JS_DASHBOARD 末尾）：

```javascript
async function initTrash() {
  const box = document.getElementById("trash-list");
  if (!box) return;
  box.innerHTML = skeleton(4);
  await reloadTrashList();
}

async function reloadTrashList() {
  const box = document.getElementById("trash-list");
  if (!box) return;
  try {
    const data = await fetchJson("/api/trash");
    const entries = data.entries || [];
    if (!entries.length) {
      box.innerHTML = emptyState("回收站是空的", "目前没有已删除的作品。", "");
      return;
    }
    const rows = entries.map(function (e) {
      return (
        '<tr>' +
        '<td><code>' + escapeHtml(e.entry) + '</code></td>' +
        '<td>' + escapeHtml(e.original_name) + '</td>' +
        '<td><span class="muted">' + escapeHtml(e.deleted_at) + '</span></td>' +
        '<td>' + e.size_mb + ' MB</td>' +
        '<td>' + e.file_count + '</td>' +
        '<td class="cluster">' +
        '<button class="btn btn-secondary btn-sm" data-trash-restore="' +
        escapeHtml(e.entry) + '">restore</button>' +
        '<button class="btn btn-danger btn-sm" data-trash-purge="' +
        escapeHtml(e.entry) + '">purge</button>' +
        '</td>' +
        '</tr>'
      );
    }).join("");
    box.innerHTML =
      '<table class="table"><thead><tr>' +
      '<th>entry</th><th>原 name</th><th>删除时间</th><th>大小</th><th>文件</th><th></th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  } catch (err) {
    box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
  }
}

document.addEventListener("click", async function (ev) {
  const r = ev.target.closest("[data-trash-restore]");
  if (r) {
    ev.preventDefault();
    const entry = r.getAttribute("data-trash-restore");
    r.disabled = true;
    try {
      const data = await postJson("/api/trash/" + encodeURIComponent(entry) + "/restore", {});
      showToast("已 restore：" + data.restored_to, "info");
      await reloadTrashList();
    } catch (err) {
      showToast("restore 失败：" + err.message, "error");
      r.disabled = false;
    }
    return;
  }
  const p = ev.target.closest("[data-trash-purge]");
  if (p) {
    ev.preventDefault();
    showPurgeModal(p.getAttribute("data-trash-purge"));
  }
});

function showPurgeModal(entry) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML =
    '<div class="modal" role="dialog" aria-modal="true">' +
    '<div class="modal-header">永久删除 <code>' + escapeHtml(entry) + '</code></div>' +
    '<div class="modal-body">' +
    '<p>这一步会从磁盘 <code>shutil.rmtree</code> 这个条目，<strong>无法恢复</strong>。</p>' +
    '<p>输入 <strong>' + escapeHtml(entry) + '</strong> 以确认。</p>' +
    '<div class="field"><label>entry 名</label>' +
    '<input type="text" id="modal-purge-input" autocomplete="off">' +
    '</div>' +
    '<div id="modal-purge-error"></div>' +
    '</div>' +
    '<div class="modal-footer">' +
    '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
    '<button type="button" class="btn btn-danger" id="modal-purge-btn" disabled>确认永久删除</button>' +
    '</div></div>';
  document.body.appendChild(backdrop);
  const input = backdrop.querySelector("#modal-purge-input");
  const btn = backdrop.querySelector("#modal-purge-btn");
  const err = backdrop.querySelector("#modal-purge-error");
  function close() {
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
  }
  function onKey(ev) { if (ev.key === "Escape") close(); }
  input.addEventListener("input", function () {
    btn.disabled = input.value !== entry;
  });
  backdrop.addEventListener("click", function (ev) {
    if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
  });
  document.addEventListener("keydown", onKey);
  btn.addEventListener("click", async function () {
    btn.disabled = true;
    err.innerHTML = '<div class="alert info">正在 purge…</div>';
    try {
      await postJson("/api/trash/" + encodeURIComponent(entry) + "/purge",
        { confirm: entry });
      close();
      showToast("已永久删除：" + entry, "info");
      await reloadTrashList();
    } catch (e) {
      err.innerHTML = '<div class="alert error">' + escapeHtml(e.message) + "</div>";
      btn.disabled = false;
    }
  });
  setTimeout(function () { input.focus(); }, 0);
}
```

#### B.4 测试

**B.4.1** 扩 `tests/test_web_trash.py` 加 list / restore / purge / collision 4 个用例：

```python
def test_list_trash_entries_after_soft_delete(self) -> None:
    soft_delete_workspace("alpha")
    from src.web.trash import list_trash_entries
    entries = list_trash_entries()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0]["original_name"], "alpha")
    self.assertGreaterEqual(entries[0]["file_count"], 1)

def test_restore_renames_back(self) -> None:
    ok, msg = soft_delete_workspace("alpha")
    entry = msg.split("/")[-1]
    from src.web.trash import restore_trash_entry
    ok, restored = restore_trash_entry(entry)
    self.assertTrue(ok)
    self.assertTrue((paths.WORKSPACE_DIR / "alpha" / "marker.txt").exists())

def test_restore_name_collision(self) -> None:
    ok, msg = soft_delete_workspace("alpha")
    entry = msg.split("/")[-1]
    # Re-create alpha to force a collision on restore
    (paths.WORKSPACE_DIR / "alpha").mkdir()
    from src.web.trash import restore_trash_entry
    ok, msg = restore_trash_entry(entry)
    self.assertFalse(ok)
    self.assertEqual(msg, "name_collision")

def test_purge_removes_from_disk(self) -> None:
    ok, msg = soft_delete_workspace("alpha")
    entry = msg.split("/")[-1]
    from src.web.trash import purge_trash_entry
    ok, _ = purge_trash_entry(entry)
    self.assertTrue(ok)
    self.assertFalse((paths.WORKSPACE_DIR / "_trash" / entry).exists())
```

**B.4.2** `tests/test_web_routes_post.py` 加 trash API 用例：

```python
def test_trash_list_returns_entries(self) -> None:
    # delete alpha first
    routes.dispatch("POST", "/api/workspace/alpha/delete",
                    json.dumps({"confirm": "alpha"}).encode())
    status, _ct, body = routes.dispatch("GET", "/api/trash")
    self.assertEqual(status, 200)
    data = json.loads(body)
    self.assertEqual(len(data["entries"]), 1)
    self.assertEqual(data["entries"][0]["original_name"], "alpha")

def test_trash_purge_requires_confirm(self) -> None:
    routes.dispatch("POST", "/api/workspace/alpha/delete",
                    json.dumps({"confirm": "alpha"}).encode())
    entries = json.loads(routes.dispatch("GET", "/api/trash")[2])["entries"]
    entry = entries[0]["entry"]
    status, _ct, body = routes.dispatch(
        "POST", f"/api/trash/{entry}/purge",
        json.dumps({"confirm": "wrong"}).encode(),
    )
    self.assertEqual(status, 400)
```

**B.4.3** **race fix** 用 `threading.Barrier`：

```python
def test_delete_vs_start_job_race_resolved(self) -> None:
    """Iter 034 (Mendel P2): the window between busy-check and rename
    must be closed by the workspace_reserved lock so a concurrent
    start_job either fails-busy first or queues after delete completes."""
    import threading
    from src.web import jobs

    barrier = threading.Barrier(2)
    results = {"delete_status": None, "start_error": None}

    def delete_worker():
        barrier.wait()
        status, _ct, _body = routes.dispatch(
            "POST", "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        results["delete_status"] = status

    def start_worker():
        barrier.wait()
        try:
            jobs.start_job("alpha", "normalize", {})
        except RuntimeError as exc:
            results["start_error"] = str(exc)

    t1 = threading.Thread(target=delete_worker)
    t2 = threading.Thread(target=start_worker)
    t1.start(); t2.start()
    t1.join(timeout=5); t2.join(timeout=5)
    # Exactly one of them won. Either delete=200 + start raised busy,
    # OR delete=409 (because start beat it) + start ran. Both are fine.
    if results["delete_status"] == 200:
        self.assertTrue("workspace_busy" in (results["start_error"] or "") or
                         "workspace_not_found" in (results["start_error"] or ""))
    else:
        self.assertEqual(results["delete_status"], 409)
```

---

## 3. Codex 必须遵守的工程铁律

1. **不要新增任何 CSS 颜色字面量**。所有颜色用 iter 032 已定义的 CSS 变量。
2. **不要引入任何前端 / 后端依赖**。Plan viewer 的 markdown 渲染器必须 ≤50 行手写。
3. **不要 hard-rm 任何工作区** 除了 `purge_trash_entry` 这一处明确接口；该接口必须验证 confirm == entry。
4. **不要 push 远程**。提交标题 `Iteration 034: plan viewer + trash close-loop + delete race fix`。
5. **不要动 iter 032 / 033 已通过的测试断言**。新测试都加在新文件或现有用例后。
6. **保留 iter 026 / 030 / 032 / 033 的 JS 标识符**：`loadTabPanel / scheduleReadiness / readinessRequestSeq / writeBookJobRunning / readinessTimer / showToast / showDeleteModal / jumpToParagraph / initInsights / data-jump-line / __pending_toast` 必须能字符串搜索命中。
7. **不要重做视觉**。本迭代禁止动 iter 032 design tokens / `.btn-*` / `.badge` / `.card` / `.sidebar` / `.tabs` / `.modal*` 样式。Trash purge modal 必须**直接复用** iter 033 的 `.modal-backdrop / .modal / .modal-header / .modal-body / .modal-footer` 类。
8. **侧栏「数据」之上、「续写」之下**：`_WORKSPACE_SECTIONS` 顺序必须是 `overview / continue / plan / chapters / reviews / insights / jobs`。

---

## 4. Codex 自检清单（commit 前必跑）

```bash
# 1. 单元测试
.venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
# 必须只剩 iter 032 起就存在的 6 个沙箱 socket.bind 错误，本迭代不引入新 ERROR / FAIL

# 2. dispatcher 级冒烟
.venv/bin/python3 -c "
from src.web import routes
for p in ['/', '/trash', '/w/longzu/', '/w/longzu/plan', '/w/longzu/continue',
          '/w/longzu/chapters', '/w/longzu/chapter/1', '/w/longzu/reviews',
          '/w/longzu/insights', '/w/longzu/jobs']:
    print(routes.dispatch('GET', p)[0], p)
"
# 全部 200。

# 3. 关键字符串存在
.venv/bin/python3 -c "
from src.web import static
for kw in [
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    # iter 026-033 protected identifiers
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
]:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
print('all js identifiers present')
"

# 4. _trash 仍不进 list_workspaces，且 trash API 返回正常
.venv/bin/python3 -c "
from src.cli_workspace import list_workspaces
from src.web import routes
import json
print('list_workspaces() ->', list_workspaces())
status, _, body = routes.dispatch('GET', '/api/trash')
print('GET /api/trash status:', status, 'entries:', len(json.loads(body).get('entries', [])))
"
```

把以上 4 块输出**原文**贴进文末「Codex Run Log」。

---

## 5. 验收：Claude 的浏览器真实用户流程

Codex 提交之后，由 Claude 用 `mcp__Claude_in_Chrome` 跑下面 10 条流程（沙箱不允许时降级为代码级 + dispatcher + 用户实操）。

| # | 流程 | 关键检查点 |
|---|---|---|
| F1 | `/` 视觉无回归 | iter 032 / 033 视觉仍在；侧栏书架仍按 mtime 排 |
| F2 | 顶栏看到 `♻ 回收站` 链接 | 在 `⚙ 设置` 左边，文字 / 图标准确 |
| F3 | 进入 `/w/longzu/plan` 三 tab 切换 | 顶部摘要含 起点 + plan_fingerprint 短哈希 + 已写/计划；3 个 tab 内容齐全 |
| F4 | 章节卡顶部 verdict 徽章 | 已写 → 绿色「已写」badge，未写 → 灰色「未写」badge |
| F5 | `/trash` 列表加载 | 含 entry / 原 name / 删除时间 / 大小 MB / file count |
| F6 | restore 一个测试条目 | 列表刷新 + toast 通知 + workspaces 列表恢复 |
| F7 | 同名 restore 冲突 | 409 + alert error + 列表保持 |
| F8 | purge modal 输入校验 | 输错 entry 名按钮 disable；输对才亮；Esc/取消/遮罩三路关 |
| F9 | 真 purge 一个测试条目 | 文件系统消失 + 列表刷新 + toast 通知 |
| F10 | mock 起 job 同时试图删除 | 409 阻断（race fix 生效） |

**任一项不过：不验收，要求 Codex 修。**

---

## 6. 明确不在本迭代范围（留给 iter 035+）

- World viewer（entity graph / global facts / personas）
- 章节 rewrite 多版本 diff
- 章节 .md / .epub 导出
- restore 时的"覆盖原有同名工作区"选项
- 自动定期清空 `_trash/`（超过 N 天 / 超过 X MB）
- Toast 接 SSE / WebSocket 真正的 push
- 暗色模式
- 章节全文搜索
- 工作区重命名 UI
- 手动 entity proposal 审批入口
- 真模型 capstone

---

## 7. Codex Run Log（Codex 执行后填）

> Codex 请在这里粘贴 §4 四块命令的原文输出 + 任何你自己想记录的注意事项。

```
$ .venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5

----------------------------------------------------------------------
Ran 462 tests in 1.919s

FAILED (errors=6)

$ .venv/bin/python3 -c "
from src.web import routes
for p in ['/', '/trash', '/w/longzu/', '/w/longzu/plan', '/w/longzu/continue',
          '/w/longzu/chapters', '/w/longzu/chapter/1', '/w/longzu/reviews',
          '/w/longzu/insights', '/w/longzu/jobs']:
    print(routes.dispatch('GET', p)[0], p)
"
17:46:51 - LiteLLM:WARNING: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno 8] nodename nor servname provided, or not known. Falling back to local backup.
17:46:52 - LiteLLM:WARNING: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
17:46:52 - LiteLLM:WARNING: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
200 /
200 /trash
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
for kw in [
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    # iter 026-033 protected identifiers
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
]:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
print('all js identifiers present')
"
all js identifiers present

$ .venv/bin/python3 -c "
from src.cli_workspace import list_workspaces
from src.web import routes
import json
print('list_workspaces() ->', list_workspaces())
status, _, body = routes.dispatch('GET', '/api/trash')
print('GET /api/trash status:', status, 'entries:', len(json.loads(body).get('entries', [])))
"
17:47:31 - LiteLLM:WARNING: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno 8] nodename nor servname provided, or not known. Falling back to local backup.
17:47:31 - LiteLLM:WARNING: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
17:47:32 - LiteLLM:WARNING: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
list_workspaces() -> ['alpha', 'asoiaf', 'iter029_beta_ok', 'longzu', 'xueZhong']
GET /api/trash status: 200 entries: 2

$ PYTHONDONTWRITEBYTECODE=1 OPENAI_MODEL=mock .venv/bin/python3 -m unittest tests.test_web_plan_view tests.test_web_trash tests.test_web_routes_get tests.test_web_routes_post tests.test_web_jobs_dispatch
17:45:50 - LiteLLM:WARNING: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno 8] nodename nor servname provided, or not known. Falling back to local backup.
17:45:51 - LiteLLM:WARNING: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
17:45:51 - LiteLLM:WARNING: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
.................................................................
extract:   0%|          | 0/1 [00:00<?, ?it/s]
extract: 100%|██████████| 1/1 [00:00<00:00, 333.78it/s]
..............
----------------------------------------------------------------------
Ran 79 tests in 0.712s

OK

Subagent read-only audit: Sartre reported three issues before commit:
1. delete-vs-job-start race could still recreate workspaces/<name>/logs after delete.
2. workspaces/_trash nested private data was visible to git status.
3. trash restore/list truncated workspace names containing "__".

Follow-up fixes applied:
- jobs.start_job now re-checks workspace existence under _WORKSPACE_LOCK and routes.api_run_step maps workspace_not_found to 404.
- .gitignore now ignores workspaces/_trash/.
- trash entry parsing now splits against the trailing timestamp, preserving workspace names like foo__bar.
```

---

## 8. Acceptance Result（Claude 验收后填）

> 由 Claude（reviewer）填写 §5 的 10 条流程结果 + 截图链接 + 通过 / 退回意见。

```
(待 Claude 验收后填写)
```
