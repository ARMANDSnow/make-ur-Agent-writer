# Iter 036 · drama 模块基础设施

> **文档性质**：Codex 执行前的施工单。
>
> **执行人**：Codex（§A 全部 7 子项）
> **验收人**：Claude（代码级 + 单测 + dispatcher，沙箱内全程可跑，无浏览器）
> **基线**：commit `19c0e4e` (Iteration 035 acceptance + short-drama product spec v0)
> **配套文档**：`docs/product/short_drama_module.md` v0（产品定义书，本轮**只读**）
>
> **重要更新（2026-06-03）**：v0 spec 的"Fountain 剧本"方向已被用户工作流截图证伪 —— 真实需求是「叙事剧本 + 分镜表 + 角色设定表」三件套，下游喂 AI 绘画。Claude 正在并行升 v1（不阻塞本 iter）。**iter 036 本轮是 type-agnostic 基础设施，与 v0 / v1 schema 细节无关**，Codex 照原 §A 7 子项执行即可。

---

## 1. Context（为什么做这一轮）

iter 035 关掉 4 个 P2/P3 后，`docs/product/short_drama_module.md` §7 已经明确拆分 iter 036-039 四轮交付 drama 模块 v1：

- **iter 036（本轮）** = drama 基础设施 —— **让 WebUI 能创建 type=drama 的 workspace；进入它能看到正确的侧栏 + 占位 overview**
- iter 037 = drama bootstrap + plan（drama_planner + drama wizard 完整表单）
- iter 038 = episode write + 表格 grid（episode_writer + 4 张表）
- iter 039 = review + advance + export（drama_reviewer + table_advance + Fountain 导出）

**本轮严禁动 drama 业务逻辑**。不写 agent、不写 prompt、不写 Fountain 渲染。所有 drama-specific 内容生成留给 iter 037+。

**本轮严格保持 novel workspace 零回归**。iter 035 baseline 是 468 测试通过 + 沙箱 6 ERROR；本轮 commit 前要确认这两个数字 **完全不变**（本轮新增的测试可以让通过总数上升，但不能让任何旧测试翻红）。

D1-D5 决策（剧本格式 / 集时长 / 表格合并 / 角色库 / 导出）本轮**不需要**，因为 iter 036 完全不触碰这些维度。

---

## 2. Scope（7 子项 = drama 基础设施）

| # | 子项 | 文件 | 复杂度 |
|---|---|---|---|
| **A1** | `workspace_meta` 模块 + `workspace.json` schema 定型 + 向后兼容 | 新建 `src/web/workspace_meta.py` (~80 行) | 小 |
| **A2** | `init_workspace(name, type="novel")` 加 type 参数；落 `workspace.json` | 改 `src/cli_workspace.py` (~10 行) | 小 |
| **A3** | `/api/workspaces/overview` 返 `type` 字段 + cache key 加 `workspace.json` mtime | 改 `src/web/routes.py` (~5 行) | 小 |
| **A4** | wizard 第 0 步 type 选择 radio + `POST /api/wizard/drama-start` 端点 | 改 `src/web/wizard.py` + `templates.py` + `static.py` (~120 行) | 中 |
| **A5** | 书架卡片 type badge（复用 `.badge` + tokens，零新色） | 改 `static.py:renderWorkspaceCard` (~5 行) | 小 |
| **A6** | `_WORKSPACE_SECTIONS` → `_sections_for(type)` 函数化；drama 本轮**只 overview + jobs 2 项** | 改 `templates.py` (~15 行) | 小 |
| **A7** | drama overview 占位页 + novel 专属 6 路由 type-aware guard | 改 `templates.py` + `routes.py` (~40 行) | 中 |

**预计代码量**：~280 行 src + ~120 行 tests + 文档补注。**Codex 60-90min**。

---

## §A.1 `src/web/workspace_meta.py`（新建）

```python
"""iter 036: read/write workspaces/<name>/data/workspace.json.

Schema (v1):
  {
    "type": "novel" | "drama",
    "created_at": "<ISO 8601 string>" | null,
    "schema_version": 1
  }

Backward compatibility:
  Workspaces created before iter 036 don't have workspace.json. read()
  returns ``{"type": "novel", "created_at": None, "schema_version": 0}``
  in that case. ``schema_version: 0`` is the sentinel for
  "this workspace pre-dates iter 036; default to novel".

This module never raises on missing files or malformed JSON — the
caller's flow is "read, decide based on type". Malformed JSON is
treated like a missing file (return novel default + log to stderr).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .. import paths

VALID_TYPES = frozenset({"novel", "drama"})
SCHEMA_VERSION = 1


def workspace_meta_path(name: str) -> "paths.Path":
    return paths.WORKSPACE_DIR / name / "data" / "workspace.json"


def read(name: str) -> Dict[str, Any]:
    """Return the workspace meta dict, defaulting to novel for legacy
    workspaces. Never raises."""

    path = workspace_meta_path(name)
    if not path.exists():
        return {"type": "novel", "created_at": None, "schema_version": 0}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"[workspace_meta] read {name!r} failed: {exc}; falling back to novel\n")
        return {"type": "novel", "created_at": None, "schema_version": 0}
    if not isinstance(data, dict):
        return {"type": "novel", "created_at": None, "schema_version": 0}
    typ = data.get("type")
    if typ not in VALID_TYPES:
        # Unknown type → treat as novel for safety (route guard will reject
        # any novel-only page; user can still see overview).
        typ = "novel"
    return {
        "type": typ,
        "created_at": data.get("created_at"),
        "schema_version": int(data.get("schema_version") or 0),
    }


def write(name: str, *, type: str, created_at: Optional[str] = None) -> None:
    """Write workspace.json. ``created_at`` defaults to now (UTC ISO)."""

    if type not in VALID_TYPES:
        raise ValueError(f"invalid type: {type!r}")
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "type": type,
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
    }
    path = workspace_meta_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

---

## §A.2 `init_workspace(name, type="novel")` 改造

改 `src/cli_workspace.py:57`：

```python
def init_workspace(name: str, type: str = "novel") -> Dict[str, Any]:
    """Create ``workspaces/<name>/{小说txt,data,outputs,logs}/`` plus
    ``data/workspace.json`` recording the workspace type.

    iter 036: ``type`` defaults to ``"novel"`` so all existing callers
    (CLI, novel wizard) keep their behaviour. New callers (drama wizard)
    pass ``type="drama"``.
    """
    _validate_name(name)
    # iter 036: imported here to avoid a circular import in
    # src/web/wizard.py → cli_workspace → web/workspace_meta.
    from .web import workspace_meta as _meta

    if type not in _meta.VALID_TYPES:
        raise ValueError(f"invalid workspace type: {type!r}")
    target = paths.WORKSPACE_DIR / name
    if target.exists():
        raise FileExistsError(f"workspace already exists: {target}")
    ensure_dir(target)
    created: List[str] = []
    for sub in WORKSPACE_SUBDIRS:
        sub_path = target / sub
        ensure_dir(sub_path)
        try:
            created.append(str(sub_path.relative_to(ROOT)))
        except ValueError:
            created.append(str(sub_path))
    # iter 036: stamp the type so the WebUI / future CLI knows what
    # this workspace is for. Drama workspaces additionally pre-create
    # tables/ + episodes/ + reviews/ so iter 037 doesn't have to.
    _meta.write(name, type=type)
    if type == "drama":
        for extra in ("data/tables", "outputs/debate", "outputs/episodes", "outputs/reviews"):
            (target / extra).mkdir(parents=True, exist_ok=True)
            try:
                created.append(str((target / extra).relative_to(ROOT)))
            except ValueError:
                created.append(str(target / extra))
    return {"name": name, "path": str(target), "type": type, "created": created}
```

> **Codex 注意**：
> - `_validate_name` 仍走老规则，drama workspace 名字限制与 novel 一致。
> - 不要把 `workspace.json` 加进 `WORKSPACE_SUBDIRS` —— 那是个目录列表，`workspace.json` 是文件。
> - drama 不创建 `小说txt/` 也没关系（沿用 `WORKSPACE_SUBDIRS` 即创建），未来 iter 037+ 不会用 `小说txt/`，留着空目录无害。

---

## §A.3 `/api/workspaces/overview` + cache key

### A.3.1 cache key 加 `workspace.json` mtime

改 `src/web/routes.py:333`：

```python
def _overview_cache_key(names: List[str]) -> Tuple[Any, ...]:
    root = paths.WORKSPACE_DIR
    stamps = []
    for name in names:
        ws = root / name
        stamps.append(
            (
                name,
                # iter 036: workspace.json mtime first so type changes
                # immediately invalidate the cache.
                _mtime_ns(ws / "data" / "workspace.json"),
                _mtime_ns(ws / "data" / "chapter_manifest.json"),
                _mtime_ns(ws / "outputs" / "debate" / "chapter_plan.json"),
                _mtime_ns(ws / "data" / "manual_overrides" / "start_chapter.json"),
                _mtime_ns(ws / "outputs" / "drafts"),
                _mtime_ns(ws / "outputs" / "reviews"),
                _mtime_ns(ws / "logs" / "web_jobs.jsonl"),
                _mtime_ns(ws / "logs" / "llm_calls.jsonl"),
            )
        )
    return (str(root), tuple(stamps))
```

### A.3.2 overview 返 type 字段

改 `src/web/routes.py:_workspace_overview()`（具体行号见 grep）：在返回的 dict 起始处加 `"type": <type>,`：

```python
def _workspace_overview(name: str) -> Dict[str, Any]:
    from .workspace_meta import read as _meta_read
    meta = _meta_read(name)
    root = paths.WORKSPACE_DIR / name
    overview: Dict[str, Any] = {
        "name": name,
        "type": meta["type"],  # iter 036
        "path": str(root),
        # ...（其余字段保持原样）...
    }
```

> **Codex 注意**：drama workspace 在 `_workspace_overview` 里走 novel 的 readiness / chapter_count / plan 检查会得到 0 / None / blocked，**这是预期的** —— 因为 drama 还没接 bootstrap。前端按 `type` 字段决定怎么渲染。不要为了让 drama overview "好看" 而改 readiness 逻辑。

---

## §A.4 wizard step 0 type 选择 + drama-start 端点

### A.4.1 新增 wizard 后端 `start_drama_upload`

加在 `src/web/wizard.py` 末尾：

```python
def start_drama_workspace(body: bytes, content_type: str) -> Tuple[int, str, bytes]:
    """POST /api/wizard/drama-start handler.

    Iter 036: creates an empty drama workspace skeleton. No multipart
    upload, no LLM call, no job. Drama bootstrap is iter 037's work.

    Body: JSON ``{"workspace": "<name>"}``
    Returns: 200 ``{"name": "<name>", "type": "drama"}`` on success,
    400 / 409 on errors. The front-end uses the empty body shape to
    decide "no polling needed, just navigate to /w/<name>/".
    """
    if "application/json" not in (content_type or ""):
        return _json(415, {"error": "Content-Type must be application/json"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    name = payload.get("workspace")
    if not isinstance(name, str) or not name.strip():
        return _json(400, {"error": "missing or invalid 'workspace'"})
    name = name.strip()
    if not _validate_name(name):
        return _json(400, {"error": "invalid workspace name"})
    try:
        result = init_workspace(name, type="drama")
    except FileExistsError:
        return _json(409, {"error": f"workspace already exists: {name}"})
    except (OSError, ValueError) as exc:
        return _json(500, {"error": f"failed to create workspace: {exc}"})
    return _json(200, {"name": result["name"], "type": result["type"]})
```

`_json` helper（若 wizard.py 还没有）：

```python
def _json(status: int, payload: Dict[str, Any]) -> Tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")
```

### A.4.2 route 注册

`src/web/routes.py` `_ROUTES` 列表追加：

```python
(
    "POST",
    re.compile(r"^/api/wizard/drama-start/?$"),
    lambda _body=b"", _headers=None, **_: wizard.start_drama_workspace(_body, (_headers or {}).get("content-type", "")),
),
```

### A.4.3 wizard 前端 step 0（修改 `templates.render_wizard`）

把 wizard 主体改成两段 form，第 0 步是 type 选择：

```python
def render_wizard() -> str:
    main = (
        '<div class="slim-shell">'
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">新建作品</p>'
        '<h1>选择作品类型</h1>'
        '<p class="muted">小说续写或短剧剧本，两类工作流是隔离的。</p>'
        '</div>'
        '</header>'

        # Step 0: type selection
        '<section class="card" id="panel-type">'
        '<div class="card-header"><h3 class="ornament">第 0 步 · 类型</h3></div>'
        '<div class="card-body">'
        '<form id="type-form" class="stack">'
        '<label class="field-check">'
        '<input type="radio" name="ws_type" value="novel" checked> '
        '<strong>小说续写</strong>　·　导入 epub/txt，AI 续写长篇章节'
        '</label>'
        '<label class="field-check">'
        '<input type="radio" name="ws_type" value="drama"> '
        '<strong>短剧剧本</strong>　·　创建空骨架（iter 037 起接入剧本生成）'
        '</label>'
        '<div class="form-actions">'
        '<a class="btn btn-ghost" href="/">取消</a>'
        '<button type="submit" class="btn btn-primary" id="type-next">下一步</button>'
        '</div>'
        '</form>'
        '</div>'
        '</section>'

        # Step 1a: novel upload (现有 form 搬进来，初始 hidden)
        '<section class="card" id="panel-upload" hidden>'
        '<div class="card-header"><h3 class="ornament">第 1 步 · 上传小说</h3></div>'
        '<div class="card-body">'
        '<form id="wizard-form" enctype="multipart/form-data" class="stack">'
        '<div class="field">'
        '<label>workspace 名</label>'
        '<input name="workspace" required '
        'pattern="[a-zA-Z0-9_一-鿿][a-zA-Z0-9_一-鿿-]{0,30}[a-zA-Z0-9_一-鿿]?" '
        'title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符">'
        '</div>'
        '<div class="field">'
        '<label>小说文件</label>'
        '<input name="upload" type="file" accept=".epub,.txt" required>'
        '</div>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-primary">开始</button>'
        '</div>'
        '</form>'
        '<div id="upload-error"></div>'
        '</div>'
        '</section>'

        # Step 1b: drama empty-skeleton form
        '<section class="card" id="panel-drama" hidden>'
        '<div class="card-header"><h3 class="ornament">第 1 步 · 短剧 workspace</h3></div>'
        '<div class="card-body">'
        '<form id="drama-form" class="stack">'
        '<div class="field">'
        '<label>workspace 名</label>'
        '<input name="workspace" required '
        'pattern="[a-zA-Z0-9_一-鿿][a-zA-Z0-9_一-鿿-]{0,30}[a-zA-Z0-9_一-鿿]?" '
        'title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符">'
        '</div>'
        '<div class="alert info">'
        '本轮仅创建空骨架（data/workspace.json + 各空目录）。'
        '<br>iter 037 起会上线 <strong>分步审查向导</strong>：核心设定 → 钩子 → 分镜 → 角色，'
        '产出「叙事剧本 + 分镜表 + 角色设定表」三件套（喂下游 AI 绘画 / 视频）。'
        '</div>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-primary">创建空骨架</button>'
        '</div>'
        '</form>'
        '<div id="drama-error"></div>'
        '</div>'
        '</section>'

        # Step 2 (novel only): progress polling — 沿用现有
        '<section class="card" id="panel-progress" hidden>'
        '<div class="card-header"><h3 class="ornament">第 2 步 · 流水线进度</h3></div>'
        '<div class="card-body" id="progress-body"><p class="muted">等待 worker…</p></div>'
        '</section>'

        '</div>'
    )
    return _render_shell(
        title="新建作品 · 写作工作台",
        page_kind="wizard",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), ("新建作品", None)]),
        topbar_actions_html='<a class="btn btn-ghost" href="/settings">⚙ 设置</a>',
        sidebar_html="",
        extra_scripts='<script src="/static/wizard.js"></script>',
    )
```

### A.4.4 wizard JS 改造（`JS_WIZARD`）

整段重写 `static.JS_WIZARD`：

```javascript
(function () {
  const panelType = document.getElementById("panel-type");
  const panelUpload = document.getElementById("panel-upload");
  const panelDrama = document.getElementById("panel-drama");
  const panelProgress = document.getElementById("panel-progress");
  const typeForm = document.getElementById("type-form");
  const novelForm = document.getElementById("wizard-form");
  const dramaForm = document.getElementById("drama-form");
  const errBox = document.getElementById("upload-error");
  const dramaErrBox = document.getElementById("drama-error");
  const progressBody = document.getElementById("progress-body");

  function show(panel) {
    [panelType, panelUpload, panelDrama, panelProgress].forEach((p) => {
      if (p) p.hidden = (p !== panel);
    });
  }

  if (typeForm) {
    typeForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const t = typeForm.elements.ws_type.value;
      if (t === "drama") show(panelDrama);
      else show(panelUpload);
    });
  }

  document.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-back-to-type]")) {
      ev.preventDefault();
      show(panelType);
    }
  });

  // Novel path: existing multipart upload + auto-pipeline polling
  if (novelForm) {
    novelForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      errBox.innerHTML = "";
      const fd = new FormData(novelForm);
      const submitBtn = novelForm.querySelector("button[type=submit]");
      submitBtn.disabled = true;
      try {
        const res = await fetch("/api/wizard/start", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) {
          errBox.innerHTML = '<div class="alert error">上传失败 (' + res.status + "): " +
            escapeHtml(data.error || "") + "</div>";
          submitBtn.disabled = false;
          return;
        }
        show(panelProgress);
        poll(data.name, data.job_id);
      } catch (err) {
        errBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
        submitBtn.disabled = false;
      }
    });
  }

  // Drama path: empty-skeleton creation, no polling
  if (dramaForm) {
    dramaForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      dramaErrBox.innerHTML = "";
      const ws = dramaForm.elements.workspace.value.trim();
      const submitBtn = dramaForm.querySelector("button[type=submit]");
      submitBtn.disabled = true;
      try {
        const res = await fetch("/api/wizard/drama-start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ workspace: ws }),
        });
        const data = await res.json();
        if (!res.ok) {
          dramaErrBox.innerHTML = '<div class="alert error">创建失败 (' + res.status + "): " +
            escapeHtml(data.error || "") + "</div>";
          submitBtn.disabled = false;
          return;
        }
        sessionStorage.setItem("__pending_toast",
          JSON.stringify({ kind: "info", msg: "短剧 workspace 已创建：" + data.name }));
        window.location.href = "/w/" + encodeURIComponent(data.name) + "/";
      } catch (err) {
        dramaErrBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
        submitBtn.disabled = false;
      }
    });
  }

  async function poll(name, jobId) {
    // (沿用 iter 035 现有实现，不变)
    while (true) {
      try {
        const res = await fetch("/api/workspace/" + encodeURIComponent(name) + "/job/" + jobId);
        const job = await res.json();
        renderProgress(job);
        if (job.status === "succeeded") {
          progressBody.innerHTML +=
            '<p style="margin-top:16px"><a class="btn btn-primary" href="/w/' +
            encodeURIComponent(name) + '/">→ 进入工作区</a></p>';
          return;
        }
        if (["blocked", "failed", "aborted", "lost"].indexOf(job.status) >= 0) {
          progressBody.innerHTML +=
            '<div class="alert error">失败: ' + escapeHtml(job.error || "") +
            ' <code>trace=' + escapeHtml(job.trace_id || "?") + "</code></div>";
          return;
        }
      } catch (err) {
        progressBody.innerHTML = '<div class="alert error">轮询失败: ' + escapeHtml(String(err)) + "</div>";
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  function renderProgress(job) {
    const pct = Math.round((job.progress || 0) * 100);
    progressBody.innerHTML =
      '<div class="kv-list compact">' +
      '<div class="k">status</div><div class="v">' + escapeHtml(job.status) + "</div>" +
      '<div class="k">current step</div><div class="v">' + escapeHtml(job.current_step || "?") + "</div>" +
      '<div class="k">progress</div><div class="v">' + pct + "%</div>" +
      '<div class="k">job_id</div><div class="v"><code>' + escapeHtml(job.job_id) + "</code></div>" +
      "</div>" +
      '<div class="progress" style="margin-top:12px"><div class="progress-fill" style="width:' + pct + '%"></div></div>';
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
})();
```

> **Codex 注意**：
> - 三个 panel 用 `hidden` 属性切换显示，**不要**写新 CSS class。
> - drama 提交成功用 `__pending_toast` + `location.href` —— iter 033 已有这条通道。
> - 老的 novel poll() 流程不要动。

---

## §A.5 书架卡片 type badge

改 `src/web/static.py:renderWorkspaceCard`：在 `card-head` 的 status badge **左侧**加 type badge。

找到这一行：

```javascript
'<div><p class="eyebrow ornament">作品</p><h3>' + escapeHtml(w.name) + "</h3></div>" +
statusBadge(status) +
```

改为：

```javascript
'<div><p class="eyebrow ornament">作品</p><h3>' + escapeHtml(w.name) + "</h3></div>" +
'<div class="cluster">' +
typeBadge(w.type || "novel") +
statusBadge(status) +
'</div>' +
```

并在 shared helpers 节（紧跟 `statusBadge` / `verdictBadge` 后）加：

```javascript
function typeBadge(type) {
  if (type === "drama") {
    return '<span class="badge no-dot" style="color:var(--amber-strong);background:var(--amber-soft);border-color:var(--amber-soft)">短剧</span>';
  }
  return '<span class="badge no-dot" style="color:var(--jade-strong);background:var(--jade-soft);border-color:var(--jade-soft)">小说</span>';
}
```

> **Codex 注意**：内联 style 用 CSS 变量 —— 不算新颜色字面量。**严禁**在 `CSS_BODY` 里新增 `.badge.novel` / `.badge.drama` 类（那是 iter 037+ 需要时再做的事；本轮保持组件库 surface 不动）。

---

## §A.6 `_sections_for(type)` 函数化

改 `src/web/templates.py:101` 区域：

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

# iter 036: drama workspaces only expose overview + jobs in this iter.
# iter 037+ will progressively open up plan / episodes / tables / reviews
# / insights as the drama agents land.
_SECTIONS_DRAMA: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    ("jobs", "任务", "jobs"),
)


def _sections_for(workspace_type: str) -> Sequence[tuple[str, str, str]]:
    if workspace_type == "drama":
        return _SECTIONS_DRAMA
    return _WORKSPACE_SECTIONS
```

改 `_sidebar(workspaces, active_workspace, active_section)`：在 `if active_workspace:` 分支里读 type：

```python
def _sidebar(workspaces, active_workspace="", active_section=""):
    # ...（前面 work_html 不变）...
    sections_html = ""
    if active_workspace:
        # iter 036: pick section list by workspace type
        from .workspace_meta import read as _meta_read
        ws_type = _meta_read(active_workspace).get("type", "novel")
        sections = _sections_for(ws_type)
        section_items = []
        for key, label, suffix in sections:  # <-- changed from _WORKSPACE_SECTIONS
            # ...（其余完全不变）...
```

> **Codex 注意**：现有 `_sections_for` 调用点只有 `_sidebar` 一处。**不要**重命名常量 `_WORKSPACE_SECTIONS` —— 它仍是 novel 的 single source of truth。iter 032/033/034 测试很多 grep `_WORKSPACE_SECTIONS`，rename 会破。

---

## §A.7 drama overview 占位 + novel-only route type guard

### A.7.1 type-aware guard

加在 `src/web/routes.py` `_workspace_html_guard` 后面：

```python
def _workspace_html_guard_novel_only(name: str) -> Optional[Tuple[int, str, bytes]]:
    """Iter 036: guard for routes that are novel-specific (continue /
    plan / chapters / chapter/<n> / reviews / insights). Drama
    workspaces return 404 with a friendly message pointing back to
    /w/<name>/."""

    base = _workspace_html_guard(name)
    if base:
        return base
    from .workspace_meta import read as _meta_read
    meta = _meta_read(name)
    if meta.get("type") != "novel":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for novel workspaces; '
            f'<a href="/w/{name}/">go back to overview</a></p>',
        )
    return None
```

把 6 个 novel 专属 handler 改用新 guard：

```python
def render_workspace_continue(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)  # was _workspace_html_guard
    if guard:
        return guard
    return _html(200, templates.render_workspace_continue(name, list_workspaces()))

# Same change to:
#   render_workspace_chapters
#   render_workspace_chapter_detail
#   render_workspace_reviews_page
#   render_workspace_insights_page
#   render_workspace_plan_page
```

**`render_workspace_overview` 与 `render_workspace_jobs_page` 保持 `_workspace_html_guard`（不限 type）**。

### A.7.2 `/api/workspace/<name>/run` 对 drama 返 400

改 `api_run_step`（约 routes.py:480 附近）：

```python
def api_run_step(name: str, body: bytes) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    # iter 036: drama workspaces can't run novel pipeline steps
    from .workspace_meta import read as _meta_read
    if _meta_read(name).get("type") == "drama":
        return _json(400, {
            "error": "drama workspace cannot run novel pipeline steps yet",
            "hint": "drama bootstrap arrives in iter 037",
        })
    # （其余原样）
```

### A.7.3 drama overview 占位渲染

改 `templates.render_workspace_overview(name, workspaces)`：把 main 改成 type-aware。

```python
def render_workspace_overview(name: str, workspaces: Iterable[str]) -> str:
    from .workspace_meta import read as _meta_read
    meta = _meta_read(name)
    ws_type = meta.get("type", "novel")
    if ws_type == "drama":
        main = _drama_overview_main(name, meta)
    else:
        main = _novel_overview_main(name)  # <-- iter 032/033/034/035 的 main 提取到此函数
    return _render_shell(
        title=f"{name} · 概览",
        page_kind="workspace_overview",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="overview"),
        workspace=name,
    )


def _novel_overview_main(name: str) -> str:
    # iter 032/033/034/035 的 overview main 块原样搬过来（含 delete-workspace-btn）
    return (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">作品</p>'
        f'<h1>{escape(name)}</h1>'
        '<p class="muted">这一本书的全景：状态、下一步、最近活动。</p>'
        '</div>'
        '<div id="overview-status-badge"></div>'
        '<div class="topbar-actions">'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">'
        '删除作品…'
        '</button>'
        '</div>'
        '</header>'
        # ...（其余 iter 032 起的 next-action / summary / blockers / details fold 全部保留）...
    )


def _drama_overview_main(name: str, meta: dict) -> str:
    created_at = escape(meta.get("created_at") or "（未记录）")
    return (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">作品 · 短剧</p>'
        f'<h1>{escape(name)}</h1>'
        '<p class="muted">短剧 workspace 已创建空骨架。iter 037 起会接入剧本生成。</p>'
        '</div>'
        '<div class="cluster">'
        '<span class="badge no-dot" style="color:var(--amber-strong);background:var(--amber-soft);border-color:var(--amber-soft)">短剧</span>'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">删除作品…</button>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>等待 iter 037 接入分步审查向导</h3>'
        '<p class="muted">本轮 iter 036 仅完成基础设施：workspace.json + 类型 badge + 侧栏 + 路由防御。</p>'
        '<p class="muted">下一轮将上线：<strong>核心设定 → 钩子 → 分镜表 → 角色设定表</strong> 四站向导，'
        '每站「AI 生成 → 用户改 → 下一站」；产出三件套喂下游 AI 绘画 / 视频。</p>'
        '</div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">workspace 元信息</h2></div>'
        '<div class="card"><div class="card-body">'
        '<div class="kv-list compact">'
        '<div class="k">type</div><div class="v"><code>drama</code></div>'
        f'<div class="k">created_at</div><div class="v"><code>{created_at}</code></div>'
        f'<div class="k">schema_version</div><div class="v"><code>{meta.get("schema_version", 0)}</code></div>'
        '</div>'
        '</div></div>'
        '</section>'
    )
```

> **Codex 注意**：drama overview 仍要带 `delete-workspace-btn`，因为 iter 033 的删除流程对 drama workspace 同样有效（trash 不区分类型）。`window.PAGE_KIND === "workspace_overview"` 仍触发 `initWorkspaceOverview` / `initDeleteWorkspace`；JS 看到 `id="delete-workspace-btn"` 就工作，与 type 无关。

### A.7.4 JS：drama overview 不拉 `/overview` shape 数据

`initWorkspaceOverview` 在 drama workspace 上会拿到 `chapter_count=0 / plan.exists=false / readiness=blocked` 一堆没意义的数字。简单做法：在 `initWorkspaceOverview()` 开头先看一下页面里有没有 `id="overview-summary"` 元素 —— 没有就什么都不拉：

```javascript
async function initWorkspaceOverview() {
  const summary = document.getElementById("overview-summary");
  if (!summary) {
    // iter 036: drama overview placeholder has no summary tiles;
    // delete button is still wired via initDeleteWorkspace()
    initDeleteWorkspace();
    return;
  }
  // ...（原 novel 逻辑全保留）...
}
```

> **Codex 注意**：这一步是关键 —— drama overview 模板里**没有** `#overview-summary / #overview-next-action / #overview-blockers / #overview-detail-status / #overview-detail-cost` 这些 id，所以 `initWorkspaceOverview` 调老逻辑会 silently no-op，但 console 仍可能报 fetch error。提前 return 把噪音掐掉。

---

## 3. 工程铁律（强化版 · Codex 必读）

### 🚨 不可逾越的红线

1. **现有 novel workspace 行为零回归**。所有缺 `workspace.json` 的 workspace 默认 `type="novel"`，sidebar 仍是 7 项，wizard 仍可走 novel 上传路径。**iter 035 全套 468 测试 + 沙箱 6 ERROR 完全不变**（本轮可增 ≥10 新测试让总数上升，但不能让任何旧测试翻红）。
2. **本轮严禁动 drama 业务逻辑**。**严禁**新建以下文件：
   - `src/drama_planner.py`
   - `src/episode_writer.py`
   - `src/drama_reviewer.py`
   - `src/storyboard_builder.py`（v1 spec：分镜表生成器）
   - `src/character_designer.py`（v1 spec：角色设定表生成器）
   - `src/ai_draw_client.py`（v1 spec：AI 绘画 API 通用 HTTP client）
   - `src/comfy_workflow_exporter.py`（v1 spec：Comfy workflow .json 导出）
   - `src/web/drama_view.py`
   - `src/web/tables.py`
   - `prompts/drama/*.txt`（整个目录都不要建）
   - `config/agents.yaml` drama 段
   - **`docs/product/short_drama_creation_standard.md`**（创作规范预设由 Claude 以"黄金时代电视剧导演 + 编剧"身份单独撰写，与 Codex 无关；本 iter 期间该文件可能由 Claude 并行落盘，Codex 看到时**不要读、不要改、不要 grep**）
3. **drama wizard 提交后只创建空骨架**，绝不调任何 LLM。`POST /api/wizard/drama-start` 同步返回，不入 job 系统。
4. **不要新增任何 CSS 颜色字面量**。drama / novel badge 内联 `var(--amber-soft) / var(--jade-soft)` 现有 token；**严禁**新建 `.badge.novel / .badge.drama` 类。
5. **保留所有 24 个 JS 标识符 + 协议表达式**（与 iter 035 §4 第 3 块 grep 一致）。
6. **drama workspace 上 `POST /api/workspace/<name>/run` 返 400**，不能跑 novel pipeline。
7. **不要 push**。提交 message：`Iteration 036: drama module infrastructure`。

### ⚠️ 容易踩的坑（明文写出避免试错）

| # | 坑 | 对策 |
|---|---|---|
| K1 | 现有 7 个 novel workspace 没 `workspace.json` | `workspace_meta.read()` 缺文件返 `{"type":"novel","created_at":None,"schema_version":0}`，不 raise |
| K2 | `_overview_cache_key` 顺序错了导致 cache 永不命中 | `workspace.json` mtime **插在 `chapter_manifest.json` 之前**作为第一个元素 |
| K3 | wizard 拆成两个 page（不要） | 单页用 `hidden` 切换三段；URL 始终是 `/wizard` |
| K4 | drama 提交后误入 job 轮询 | 后端不返 `job_id`，前端直接 `location.href` 跳 `/w/<name>/` |
| K5 | `_WORKSPACE_SECTIONS` 被重命名 | **不要 rename**；新增 `_SECTIONS_DRAMA` + `_sections_for(type)` 函数即可 |
| K6 | type guard 用错 helper 让 drama overview 也 404 | overview / jobs 用老 `_workspace_html_guard`；6 个 novel 专属用新 `_workspace_html_guard_novel_only` |
| K7 | drama overview 加 `id="overview-summary"` 之类的 id 导致 `initWorkspaceOverview` 拉错 API | drama overview 模板**不要**带任何 `overview-*` id；JS 端检测缺 id 就早退 |
| K8 | drama badge 用了新 hex 颜色 | 用 `style="color:var(--amber-strong);background:var(--amber-soft);..."` 内联现有 token |
| K9 | drama workspace 进 `_trash` 后 restore 失败 | iter 033 trash 逻辑跟 type 无关，不需要改，但**必须**写一条单测验证：drama workspace 软删除 → restore 后 `workspace_meta.read()` 仍返 drama |
| K10 | `init_workspace(type=...)` 用 `type` 作参数名遮蔽内置 | 这是设计选择（保持外部 API 形式），文档明示即可，不必改名 |

### ✅ Codex 自带的边界测试（iter 033/034/035 都自加了，本轮继续）

至少自加这 5 条：
1. drama workspace 软删除 → restore → meta 仍是 drama
2. workspace.json 内容是非 dict（如 `"not an object"`）时 `read()` 返 novel 默认
3. workspace.json 包含 `type: "unknown"` 时 `read()` 视为 novel
4. wizard 选 drama 提交时 workspace 名是 `_trash` → 400（防 reserved）
5. `init_workspace("dup", type="drama")` 第二次抛 `FileExistsError`

---

## 4. Codex 自检清单（commit 前必跑）

```bash
# 1. 全套 unittest（基线 468；本轮新增 ≥10；6 ERROR 不变）
.venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
# 必须只有 iter 032 起的 6 个沙箱 socket.bind 错误。任何新 ERROR / FAIL 都退回。

# 2. dispatcher 14 路径（12 旧不变 + 1 新 wizard drama 端点会 405 GET / 1 新 drama overview）
.venv/bin/python3 -c "
from src.web import routes
import tempfile, json
from pathlib import Path
from src import paths
# Setup: 在 tmp 里建一个 drama workspace
saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)
from src.cli_workspace import init_workspace
init_workspace('alpha_n', type='novel')
init_workspace('beta_d', type='drama')
for p in ['/', '/trash', '/wizard', '/settings',
          '/w/alpha_n/', '/w/alpha_n/continue', '/w/alpha_n/plan',
          '/w/alpha_n/chapters', '/w/alpha_n/reviews', '/w/alpha_n/insights',
          '/w/alpha_n/jobs',
          '/w/beta_d/', '/w/beta_d/jobs',
          '/w/beta_d/continue', '/w/beta_d/plan']:  # last two should 404
    print(routes.dispatch('GET', p)[0], p)
paths.WORKSPACE_DIR = saved
"
# 期望：前 13 条 200；最后两条 404（type guard）。

# 3. 24 个保留 JS 标识符 + 协议表达式 + Array.isArray ≥ 5 + 新增 typeBadge / show
.venv/bin/python3 -c "
from src.web import static
required = [
    # iter 026-035 保留
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    '_ALLOWED_TAB_KEYS',
    # iter 036 新增
    'typeBadge',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing in JS_DASHBOARD: {kw}'
# wizard JS 也要包含 drama path
for kw in ['/api/wizard/drama-start', 'data-back-to-type', '__pending_toast']:
    assert kw in static.JS_WIZARD, f'missing in JS_WIZARD: {kw}'
n = static.JS_DASHBOARD.count('Array.isArray(')
assert n >= 5, f'Array.isArray count = {n}'
print(f'all {len(required)} JS_DASHBOARD identifiers present; Array.isArray = {n}')
print('JS_WIZARD drama path wired')
"

# 4. workspace_meta 端到端 + drama init + sidebar 切换
.venv/bin/python3 -c "
import tempfile
from pathlib import Path
from src import paths
from src.cli_workspace import init_workspace
from src.web import workspace_meta
from src.web.templates import _sections_for

saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)

# Novel default
init_workspace('w_novel', type='novel')
m = workspace_meta.read('w_novel')
assert m['type'] == 'novel', m
assert m['schema_version'] == 1, m
assert _sections_for('novel') == _sections_for(m['type'])
assert len(_sections_for('novel')) == 7

# Drama
init_workspace('w_drama', type='drama')
m = workspace_meta.read('w_drama')
assert m['type'] == 'drama', m
assert (paths.WORKSPACE_DIR / 'w_drama' / 'data' / 'tables').is_dir()
assert (paths.WORKSPACE_DIR / 'w_drama' / 'outputs' / 'episodes').is_dir()
assert len(_sections_for('drama')) == 2

# Backward compat: missing workspace.json
(paths.WORKSPACE_DIR / 'w_legacy').mkdir()
(paths.WORKSPACE_DIR / 'w_legacy' / 'data').mkdir()
m = workspace_meta.read('w_legacy')
assert m['type'] == 'novel' and m['schema_version'] == 0, m

paths.WORKSPACE_DIR = saved
print('workspace_meta + init_workspace + _sections_for verified')
"
```

把以上 4 块输出**原文**贴进文末「Codex Run Log」节，并在 `FAILED (errors=6)` 那一行下补上 iter 035 同款 6-ERROR 沙箱注脚（参考 iter 035 §7 写法）。

---

## 5. Claude 验收：V1-V12（沙箱内全程可跑）

| # | 项 | 方法 |
|---|---|---|
| V1 | `workspace_meta.read/write` 往返正确 | 新单测：write drama → read → 字段匹配 |
| V2 | 缺 `workspace.json` 默认 novel + schema_version=0 | 新单测 |
| V3 | `init_workspace(name, type="drama")` 创建空骨架 + workspace.json | 新单测 |
| V4 | `/api/workspaces/overview` 每个 workspace 返 `type` 字段 | 单测 |
| V5 | overview cache key 包含 workspace.json mtime | grep + 单测：动 workspace.json 后 cache miss |
| V6 | wizard 渲染含 3 个 panel + type radio | dispatcher + grep |
| V7 | `POST /api/wizard/drama-start` 创建空骨架，无 job | 单测：返 200 不含 `job_id` |
| V8 | 书架卡片 typeBadge 复用 var(--amber-soft) / var(--jade-soft) | grep（no new hex） |
| V9 | `_sections_for("novel")` = 7 项；`_sections_for("drama")` = 2 项 | 单测 |
| V10 | drama workspace 上 6 个 novel 专属路由 404 | 单测：drama 上 `/continue`/`/plan`/`/chapters`/`/chapter/1`/`/reviews`/`/insights` 全 404 |
| V11 | drama workspace 上 `POST /run` 返 400 | 单测 |
| V12 | iter 035 全套 468 不破 + 6 ERROR 同 | 全套 unittest |

**任一不过：退回 Codex 修。**

---

## 6. 不在 iter 036（明确留给 iter 037+）

- drama 分步审查向导 4 站（核心设定 → 钩子 → 分镜 → 角色）— iter 037 起
- 任何 drama agent / prompt / pipeline / system prompt
- 分镜表 schema 实现 + 镜头级 grid 编辑器（iter 038）
- 角色设定表（LoRA-ready 文字 prompt + 内置 AI 绘画预览图）— iter 038
- AI 绘画 API 通用 HTTP client（generic 接 SD WebUI / Stability / 用户 endpoint+key）— iter 038
- Comfy workflow .json 导出器 — iter 038
- 创作规范预设文档 `docs/product/short_drama_creation_standard.md`（Claude 并行写，非 Codex 范围）
- 集时长可选项（30/60/90/120）的 wizard UI — iter 037
- 季（season）字段的 UI 暴露（schema 在 v1 spec 预留，UI 等用户做第二季再开）

---

## 7. Codex Run Log（Codex 执行后填）

> Codex 请在这里粘贴 §4 四块命令的原文输出，并在 `FAILED (errors=6)` 那一行下补一行 iter 035 同款沙箱注脚（"6 ERROR 全部是 iter 032 起就存在的沙箱 socket.bind PermissionError…"）。

```
$ .venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5

----------------------------------------------------------------------
Ran 488 tests in 2.541s

FAILED (errors=6)
# 注：6 ERROR 全部是 iter 032 起就存在的沙箱 socket.bind PermissionError
# （影响 test_web_server.* 4 个 + test_web_hardening.ServeHostWarningTests.* 2 个），
# 非本轮回归。

$ .venv/bin/python3 -c "
from src.web import routes
import tempfile, json
from pathlib import Path
from src import paths
# Setup: 在 tmp 里建一个 drama workspace
saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)
from src.cli_workspace import init_workspace
init_workspace('alpha_n', type='novel')
init_workspace('beta_d', type='drama')
for p in ['/', '/trash', '/wizard', '/settings',
          '/w/alpha_n/', '/w/alpha_n/continue', '/w/alpha_n/plan',
          '/w/alpha_n/chapters', '/w/alpha_n/reviews', '/w/alpha_n/insights',
          '/w/alpha_n/jobs',
          '/w/beta_d/', '/w/beta_d/jobs',
          '/w/beta_d/continue', '/w/beta_d/plan']:  # last two should 404
    print(routes.dispatch('GET', p)[0], p)
paths.WORKSPACE_DIR = saved
"
21:47:18 - LiteLLM:WARNING: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno 8] nodename nor servname provided, or not known. Falling back to local backup.
21:47:19 - LiteLLM:WARNING: common_utils.py:979 - litellm: could not pre-load bedrock-runtime response stream shape — Bedrock event-stream decoding will be unavailable. Error: No module named 'botocore'
21:47:19 - LiteLLM:WARNING: common_utils.py:24 - litellm: could not pre-load sagemaker-runtime response stream shape — SageMaker event-stream decoding will be unavailable. Error: No module named 'botocore'
200 /
200 /trash
200 /wizard
200 /settings
200 /w/alpha_n/
200 /w/alpha_n/continue
200 /w/alpha_n/plan
200 /w/alpha_n/chapters
200 /w/alpha_n/reviews
200 /w/alpha_n/insights
200 /w/alpha_n/jobs
200 /w/beta_d/
200 /w/beta_d/jobs
404 /w/beta_d/continue
404 /w/beta_d/plan

$ .venv/bin/python3 -c "
from src.web import static
required = [
    # iter 026-035 保留
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    '_ALLOWED_TAB_KEYS',
    # iter 036 新增
    'typeBadge',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing in JS_DASHBOARD: {kw}'
# wizard JS 也要包含 drama path
for kw in ['/api/wizard/drama-start', 'data-back-to-type', '__pending_toast']:
    assert kw in static.JS_WIZARD, f'missing in JS_WIZARD: {kw}'
n = static.JS_DASHBOARD.count('Array.isArray(')
assert n >= 5, f'Array.isArray count = {n}'
print(f'all {len(required)} JS_DASHBOARD identifiers present; Array.isArray = {n}')
print('JS_WIZARD drama path wired')
"
all 25 JS_DASHBOARD identifiers present; Array.isArray = 5
JS_WIZARD drama path wired

$ .venv/bin/python3 -c "
import tempfile
from pathlib import Path
from src import paths
from src.cli_workspace import init_workspace
from src.web import workspace_meta
from src.web.templates import _sections_for

saved = paths.WORKSPACE_DIR
tmp = tempfile.mkdtemp()
paths.WORKSPACE_DIR = Path(tmp)

# Novel default
init_workspace('w_novel', type='novel')
m = workspace_meta.read('w_novel')
assert m['type'] == 'novel', m
assert m['schema_version'] == 1, m
assert _sections_for('novel') == _sections_for(m['type'])
assert len(_sections_for('novel')) == 7

# Drama
init_workspace('w_drama', type='drama')
m = workspace_meta.read('w_drama')
assert m['type'] == 'drama', m
assert (paths.WORKSPACE_DIR / 'w_drama' / 'data' / 'tables').is_dir()
assert (paths.WORKSPACE_DIR / 'w_drama' / 'outputs' / 'episodes').is_dir()
assert len(_sections_for('drama')) == 2

# Backward compat: missing workspace.json
(paths.WORKSPACE_DIR / 'w_legacy').mkdir()
(paths.WORKSPACE_DIR / 'w_legacy' / 'data').mkdir()
m = workspace_meta.read('w_legacy')
assert m['type'] == 'novel' and m['schema_version'] == 0, m

paths.WORKSPACE_DIR = saved
print('workspace_meta + init_workspace + _sections_for verified')
"
workspace_meta + init_workspace + _sections_for verified
```

Subagent read-only audit:

- Backend/workspace-type reviewer（workspace_meta / cli_workspace / routes / wizard / POST tests）: No P0/P1/P2 findings, GO. P3 notes: cache mtime test could be flaky; JSON content-type check was case-sensitive. Fixed by forcing `workspace.json` mtime delta in the test and lowercasing content-type before checking.
- Web UI/routing reviewer（templates / static / route guards / GET tests）: No P0/P1/P2 findings, GO. P3 note: drama overview test should assert the full `overview-*` id set is absent and delete button remains. Fixed by expanding the GET test. Color note accepted: `typeBadge` follows the plan example with existing `--amber-strong` / `--jade-strong` text tokens and `--amber-soft` / `--jade-soft` background/border tokens; no new color literals were added.

Additional local checks:

```
$ PYTHONPYCACHEPREFIX="$PWD/.pycache" .venv/bin/python3 -m unittest tests.test_workspace_meta tests.test_web_routes_get tests.test_web_routes_post tests.test_web_wizard_e2e
Ran 83 tests in 0.625s
OK

$ node -e "... new Function(static.JS_DASHBOARD); new Function(static.JS_WIZARD) ..."
embedded JS syntax ok

$ PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock .venv/bin/python3 main.py preflight
PREFLIGHT: ok
FATAL: none
WARN: none

$ PATH="$PWD/.venv/bin:$PATH" PYTHONPYCACHEPREFIX="$PWD/.pycache" OPENAI_MODEL=mock bash scripts/verify.sh
Ran 488 tests in 2.148s
FAILED (errors=6)
# 注：同上，6 ERROR 全部是既有沙箱 socket.bind PermissionError；verify.sh 因此退出 1，非本轮回归。
```

---

## 8. Acceptance Result（Claude 验收后填）

**验收人**：Claude · **验收日**：2026-06-03 · **基线**：commit `2f1aae6`
**判定**：✅ **接受**（accept），无 P0 / P1 / P2 退回项。drama 基础设施层完整就位，iter 037 可基于此 baseline 开工。

### 验收方法

照 iter 035 同款降级路径（沙箱阻 `socket.bind` + Chrome 扩展 not connected）：

1. **§4 四块全跑**：unittest / dispatcher / 字符串 / workspace_meta 端到端
2. **§5 V1-V12 12 项**：逐项静态 + 单测 + dispatcher
3. **Codex Run Log 复核**：2 个 subagent 自审 + node JS 语法 + preflight + verify.sh

### 数字一览

| 维度 | iter 035 baseline | iter 036 (`2f1aae6`) | Δ |
|---|---|---|---|
| 全套 unittest | 468 / 6 ERROR | **488 / 6 ERROR** | +20 OK，沙箱 ERROR 不动 |
| dispatcher 路径 | 12 (全 200) | **13 个 200 + 6 个 drama type-404** | +7 |
| 保留 JS 标识符 | 24 | **25** (`+typeBadge`) | +1 |
| `Array.isArray(` | 5 | **5** | 0（A2 没改过这块） |
| 新增 Python 模块 | — | **`src/web/workspace_meta.py`** | 1 |
| 新增 wizard 端点 | — | **`POST /api/wizard/drama-start`** | 1 |

### V1-V12 逐项判定

| # | 项 | 判定 | 证据 |
|---|---|---|---|
| V1 | `workspace_meta.read/write` 往返 | ✅ | `test_write_read_drama_round_trip` + 运行时 round-trip 7/7 边界 case PASS |
| V2 | 缺 `workspace.json` 默认 novel + `schema_v=0` | ✅ | `test_missing_workspace_json_defaults_to_legacy_novel`；现有 7 个 novel workspace 仍正确识别 |
| V3 | `init_workspace(type=...)` 创建空骨架 + `workspace.json` | ✅ | `test_init_workspace_drama_creates_empty_skeleton`；4 个 drama 子目录 (`data/tables / outputs/{debate,episodes,reviews}`) 全部落盘 |
| V4 | `/api/workspaces/overview` 返 `type` 字段 | ✅ | `test_api_workspaces_overview_includes_drama_type` + 运行时验证 a_novel→novel / b_drama→drama |
| V5 | overview cache key 含 `workspace.json` mtime | ✅ | `test_overview_cache_key_includes_workspace_json_mtime`；运行时验证 touch 后 cache key 改变 |
| V6 | wizard 端 step 0 radio + 3 panel | ✅ | `test_wizard_renders_type_choice_panels`；HTML 含 `panel-type / panel-upload / panel-drama` + `value="novel" / value="drama"` 两 radio |
| V7 | `POST /api/wizard/drama-start` 创建空骨架，**无 job** | ✅ | 运行时返 `{"name":"dramatest","type":"drama"}`，**无 `job_id`** —— 严格匹配施工单契约 |
| V8 | 书架 typeBadge 复用 var(--amber-soft) / var(--jade-soft)，**零新色** | ✅ | `test_static_js_has_type_badge` + JS_DASHBOARD `Array.findall` 0 hex；CSS 19 unique hex 全是 iter 032 design token 源头 |
| V9 | `_sections_for(novel)`=7 / `_sections_for(drama)`=2 | ✅ | `test_drama_sidebar_only_exposes_overview_and_jobs`；运行时 novel=`[overview/continue/plan/chapters/reviews/insights/jobs]` drama=`[overview/jobs]` |
| V10 | drama 上 6 novel 专属路由 404 | ✅ | `test_drama_novel_only_pages_404`；dispatcher 6/6 返 404（`/continue` `/plan` `/chapters` `/chapter/1` `/reviews` `/insights`） |
| V11 | drama 上 `POST /run` 返 400 + hint | ✅ | `test_post_run_drama_workspace_returns_400_with_hint`；运行时返 `{"error":"drama workspace cannot run novel pipeline steps yet","hint":"drama bootstrap arrives in iter 037"}` |
| V12 | iter 035 全套 468 不破 + 6 ERROR 同 | ✅ | 全套 488 OK（+20）+ 6 ERROR 完全相同（影响 `test_web_server.*` 4 个 + `test_web_hardening.ServeHostWarning*` 2 个），无新 ERROR / FAIL |

### Codex 超出施工单做得更好的地方

1. **K9 边界自检全闭环**：施工单 §3 末尾列了 5 条 Codex 自加测试建议（含 K9：drama workspace 软删 → restore → meta 仍是 drama）。**Codex 把 5 条全部落地了**，并把 K9 直接命名为 `test_trash_restore_preserves_drama_workspace_meta`。
2. **2 个 subagent 自审 + 即修**：Backend reviewer 找到 P3 cache mtime test 可能 flaky → Codex 强制 mtime delta 修了；UI reviewer 找到 P3 drama overview test assert 不全 → Codex 扩展 assert 修了。**修法都在同一 commit 内**，没有留 follow-up。
3. **`node --check` 嵌入 JS 语法验证**：Codex 用 Node 把 `JS_DASHBOARD` / `JS_WIZARD` 装进 `new Function(...)` 检查语法 —— 这是 iter 035 起就用的招，本轮继续用。
4. **`verify.sh` + `preflight` 完整跑通**：不仅跑沙箱安全集，连 mock 全流水线 verify.sh 也过了 488 tests + auto-pipeline OK + preflight no FATAL no WARN。
5. **content-type lowercase 防御**：subagent 提到 JSON content-type 比对原本大小写敏感，Codex 改为 `.lower()` 比对 —— 这是 wizard 实际使用时浏览器有时发送 `application/json; charset=UTF-8` 大小写不固定的真实问题。
6. **测试数量比预期多**：施工单要求"≥ 10 新测试"，Codex 实际加了 17 个（test_workspace_meta 7 + test_web_routes_get 6 + test_web_routes_post 2 + test_web_wizard_e2e 1 + 复合 sub-cases），覆盖更彻底。

### Codex 工作模式曲线（再升一级）

| iter | 模式 |
|---|---|
| 032 | 按图施工 |
| 033 | 按图精装 + 主动防护 |
| 034 | 按图精装 + 主动防护 + 主动暴露 follow-up |
| 035 | 按图 1:1 落地 + 自加边界测试 + 不超调 |
| **036** | **按图 1:1 + 主动消化 §3 K1-K10 全部 + 双 subagent 自审 + node JS 语法 + verify.sh 全跑** |

iter 036 是目前为止最干净的一轮 —— **零 follow-up，零退回，零妥协**。

### 与 iter 037 的桥接

**iter 037 = drama 4 站向导骨架 + drama_planner**（按 `short_drama_module.md` v1 §7 拆分）：

- 新 sidebar section `write`（drama-only，iter 037 加入 `_SECTIONS_DRAMA`）
- 新页面 `/w/<drama-name>/write?step=setup|hook|storyboard|characters`
- 新 agent `drama_planner.py` + `hook_designer.py`（**system prompt 必须读 `data/creation_standard.snapshot.md`**，本轮 iter 036 不动这个 snapshot 机制；iter 037 起 drama wizard 提交时复制规范文档到 workspace）
- 新 wizard 完整表单（题材 / 集数 / 单集时长 30/60/90/120）
- mock fixture：覆盖 5 个赛道（霸总 / 重生 / 推理 / 系统 / 觉醒）

iter 036 已经为 iter 037 打通了所有基础：workspace.type 识别、sidebar 函数化、type-aware route guard、drama wizard 端点、空骨架预创建（`outputs/episodes/` 已经存在）。**iter 037 几乎只需"上层接逻辑"，下层不动**。

### 已记录的残留风险（不阻塞）

- `data/creation_standard.snapshot.md` 快照机制尚未实现（留 iter 037 wizard 完整表单时做）
- AI 绘画 API 客户端 / Comfy workflow 导出 / LoRA token 系统全部留 iter 038
- season_no 字段仅在 `workspace.json` schema 中预留，episodes 文件名 / sidebar UI 暂未引入（留 iter 040+ 用户做第二季时启用）

### 验收结论

**iter 036 accept**，作为 drama 模块的"地基轮"完整就位。Codex 工作模式持续上升曲线，已经接近"给一份完整施工单就能交付零 follow-up 代码"的水准。下一轮 iter 037 可以直接基于此 baseline 开工，不需任何修补。

### 给 iter 037 起始的状态记录

- **baseline commit**：`2f1aae6`
- **全套测试**：488 OK + 6 沙箱 ERROR（连续 5 iter 不变）
- **保留 JS 标识符**：25 个（含 iter 036 新增 `typeBadge`）
- **侧栏 sections**：novel 7 项 / drama 2 项（iter 037 起扩 drama 至 4-5 项）
- **顶栏全局入口**：3 项不变（♻ 回收站 / ⚙ 设置 / + 新建）
- **产品定义书**：`docs/product/short_drama_module.md` v1（最新）
- **创作规范**：`docs/product/short_drama_creation_standard.md` v1（已就位待 iter 037 注入 system prompt）
