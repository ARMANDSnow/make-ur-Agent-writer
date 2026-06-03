# Iter 038 · 全代码库 P1 + P2 加固（修修补补）

> **文档性质**：Codex 执行前的施工单。
>
> **执行人**：Codex（§A 全 11 子项；纯工程，**无 §B 创作内容**）
> **验收人**：Claude（代码级 + 单测 + dispatcher，沙箱内全程可跑）
> **基线**：commit `bfa2a4b` (Iteration 037 §B drama fixtures + prompts)
>
> **配套文档**：本 iter 不涉及 drama 创作内容，`short_drama_creation_standard.md` 和 `short_drama_module.md` 本轮**只读不改**。

---

## 1. Context（为什么做这一轮）

iter 032 → 037 是连续 6 轮"造功能"（IA 重做 / delete-insights-lint-toast / plan-trash-race / P2P3 + drama spec / drama 基础设施 / drama 站①+②）。

复杂度累积明显：
- **528 行 JS 在单文件 `static.py:JS_DASHBOARD`**，跨 5 个页面 + 3 个 modal + 4 个 station，event listener / fetch 路径已经有几处叠加。
- **沙箱 6 ERROR** 连续 6 轮没人解决（`socket.bind` 在 Claude Code 沙箱被禁），导致我每次跑测试都先要肉眼过滤"哪些是预存在哪些是新增"。
- **测试 setUp/tearDown 重复**：3 个 drama 测试文件几乎完全一样的 5 行 setUp + 4 行 tearDown。
- **测试边界覆盖**：iter 035 `_safe_entry_path` 只测 3 个 case；iter 036 `workspace_meta` 只测 round-trip + missing；iter 037 hook_designer 没覆盖 episode_count mismatch。

用户用 PM 视角点的"修修补补：审查 / 测试结构性问题 / 前端 bug"刚好对应这三块。本 iter 用 2 个 Explore subagent 扫出 20 个候选问题，去掉 3 个误报，按 P1 + P2 修 11 件。

**本轮严格无新功能**。不动 drama 站③④、不接 AI 绘画、不改 schema、不新增页面、不新增 API endpoint。

**本轮严格保持 sandbox 6 ERROR → 0**（这是核心目标之一）。Codex 真环境跑通的事 528 → 528+，沙箱跑通的事从 528 → 528（新增测试 +N 让总数上升）。

---

## 2. Scope（11 子项 = P1 + P2 加固）

### 修正：subagent 报的 3 个误报已排除

- ~~static.py:1207-1222 delete modal keydown leak~~（iter 033 `closeModal` 已清，subagent 漏看）
- ~~static.py:1469-1482 purge modal keydown leak~~（iter 034 `close` 已清）
- ~~api_drama_setup_save 缺 `_clear_overview_cache`~~（routes.py:654 已调用）

### 实际清单（11 子项）

| # | 类别 | 严重度 | 位置 | 摘要 |
|---|---|---|---|---|
| **A1** | 测试 | **P1** | `tests/test_web_server.py` + `test_web_hardening.py` | 沙箱 socket bind 优雅 `@skipIf` — 解决 6 ERROR 连续 6 轮的长期 backlog |
| **A2** | 前端 | **P1** | `src/web/static.py:2337-2374` `bindStationHooksActions` | drama hook picker `pane.addEventListener` 堆叠：每次"生成 3 个钩子"按钮被点都加一个新 click handler，第 2 次起点 hook 触发多次 putJson |
| **A3** | 前端 | P2 | `src/web/static.py:2337-2374` | hook picker rapid-click：选钩子按钮没有 `disabled`，连点 2 次触发并发 putJson，后到的覆盖先到的，用户感知不到 |
| **A4** | 前端 | P2 | `src/web/static.py:942-955` `loadTabPanel` | fetch chain 无 try/catch：JSON parse 失败时抛 unhandled rejection；`lazy.dataset.loaded="1"` 错设导致下次切 tab 没机会重试 |
| **A5** | 前端 | P2 | `src/web/static.py` 跳转前 sessionStorage | `__pending_toast` 在 `location.href` 失败时残留：删除 workspace API 500 但 toast 已经塞进 sessionStorage，下次页面打开仍显示假"已删除"toast |
| **A6** | 前端 | P2 | `src/web/static.py` `renderPlanChapters` | `chapters` 整体不是数组时（iter 035 只加了 `chapters` / `key_events` 等**内部**`Array.isArray`，但 `chapters` 本身是字符串/对象时 `(plan && plan.chapters)` truthy → `.length` 不抛但 `.map` 抛）—— 加最外层早返回 |
| **A7** | 测试 | P2 | `tests/test_drama_planner.py` + `test_hook_designer.py` + `test_drama_wizard_full_form.py` | 抽取 `DramaTestBase(unittest.TestCase)`：3 文件 setUp/tearDown 几乎一样，~45 行重复 |
| **A8** | 测试 | P2 | `tests/test_workspace_meta.py` | 加 2 测试：(a) 并发 read+write 不破（`threading.Barrier`）；(b) 恶意 JSON（含 BOM / 截断 / 非 utf-8 字节）回落 novel default |
| **A9** | 测试 | P2 | `tests/test_web_trash.py` `_safe_entry_path` 边界 | iter 035 只 3 case；加 4 边界：空串 / unicode NFD vs NFC / null byte (`\x00`) / 100+ 字符过长 |
| **A10** | 测试 | P2 | `tests/test_hook_designer.py` | episode_count mismatch：wizard_input 集数=3 但 station ① fixture 没有 hook 字段时，station ② 应 raise（明确错误而非 silent fallback）|
| **A11** | 文档 | P2 | `src/web/workspace_ctx.py` docstring | 加 thread-safety 注释：明确"context manager 是 per-thread state，跨线程不可共享"；同时在 `test_web_workspace_ctx.py` 加一条 thread-isolation 测试 |

**预计 §A 代码量**：~400 行 src + ~250 行 tests + 文档补注 = **Codex 60-90min**

---

## §A.1 沙箱 socket bind `@skipIf`（P1，解决长期 backlog）

### A.1.1 共享检测 helper

新建 `tests/_socket_skip.py`：

```python
"""iter 038: detect if socket.bind() is restricted (Claude Code sandbox).

Tests that need to bind a real listening socket (ServeHostWarning /
WebHandler integration) raise PermissionError in the sandbox. They pass
in Codex's real environment.

Usage:
    @unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
    class ServerTests(unittest.TestCase): ...
"""

from __future__ import annotations

import socket


def _probe() -> bool:
    """Return True if socket.bind('127.0.0.1', 0) raises PermissionError."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
        return False
    except PermissionError:
        return True
    except OSError:
        # Other OSError (e.g. EADDRNOTAVAIL) treated as "not blocked";
        # those tests can still try and may fail with a different error.
        return False


SOCKET_BIND_BLOCKED = _probe()
```

### A.1.2 装饰受影响的 6 个测试

改 `tests/test_web_server.py`：

```python
import unittest
from tests._socket_skip import SOCKET_BIND_BLOCKED

@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
class ServerTests(unittest.TestCase):
    ...
```

改 `tests/test_web_hardening.py`：

```python
import unittest
from tests._socket_skip import SOCKET_BIND_BLOCKED

@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
class ServeHostWarningTests(unittest.TestCase):
    ...
```

### A.1.3 效果

- **Claude 沙箱**：`unittest discover` 输出从 `FAILED (errors=6)` 变成 `OK (skipped=6)` 或 `OK` + `skipped` 计数。所有 PLAN 文档里的"沙箱 6 ERROR 注脚"以后不再需要。
- **Codex 真环境**：`SOCKET_BIND_BLOCKED == False`，6 个测试照跑、照 PASS，行为完全不变。
- **未来 iter 自检**：脱离"6 ERROR 是预存在 / 还是新增？"的肉眼判别。

> **Codex 注意**：
> - `tests/_socket_skip.py` 文件名加下划线前缀，避免被 `unittest discover` 当成测试文件。
> - `_probe()` 一次性运行（module load 时），结果常量化为 `SOCKET_BIND_BLOCKED`，**不要**改成 fixture（class-level skip 必须在 collect 时就能解析）。
> - 不要新增其它任何文件作 socket skip helper。

---

## §A.2 Drama hook picker listener 堆叠（P1）

### 问题

`src/web/static.py:2337-2374` 当前实现：

```javascript
function bindStationHooksActions() {
  const btn = document.getElementById("generate-hooks");
  if (!btn) return;
  btn.addEventListener("click", async function () {
    // ...
    pane.innerHTML = '<div ...>' + hooks.map(...).join("") + '</div>';
    pane.addEventListener("click", async function (ev) {       // <-- 每次点击重复添加
      const pick = ev.target.closest("[data-hook-pick]");
      ...
    });
  });
}
```

用户点"生成 3 个钩子"两次（错误后重试 / 不满意重新生成），`pane` 上就会有 2 个 click handler 同时活着。点 1 次 hook 实际触发 2 次 putJson。

### 修法

把 hook pick 的 click handler 改成**事件代理 + 一次性 attach**：

```javascript
function bindStationHooksActions() {
  const btn = document.getElementById("generate-hooks");
  if (!btn) return;
  btn.addEventListener("click", async function () {
    btn.disabled = true;
    try {
      const data = await postJson(wsUrl("/drama/hooks"), {});
      const hooks = data.hooks || [];
      const pane = document.querySelector('[data-station-pane="hook"]');
      pane.innerHTML = '<div class="card"><div class="card-header"><h3 class="ornament">3 个候选 — 选 1 个</h3></div>' +
        '<div class="card-body stack">' +
        hooks.map(function (h, i) {
          return '<div class="advisor-item">' +
            '<span class="type">' + escapeHtml(h.type || "") + "</span>" +
            '<div class="guidance">' + escapeHtml(h.content || "") + "</div>" +
            '<button class="btn btn-secondary btn-sm" data-hook-pick="' + i + '">选这个 →</button>' +
            '</div>';
        }).join("") +
        '</div></div>';
      // iter 038 A2: stash hooks on the pane and rely on the document-level
      // delegated handler (bound once below). DO NOT add a per-render click handler.
      pane.__hooks = hooks;
    } catch (err) {
      showToast("生成失败：" + err.message, "error");
      btn.disabled = false;
    }
  });
}

// iter 038 A2 + A3: single delegated listener for hook pick (bound once at init,
// not per-render). Disables all pick buttons after first click (A3).
function bindHookPickDelegate() {
  document.addEventListener("click", async function (ev) {
    const pick = ev.target.closest("[data-hook-pick]");
    if (!pick) return;
    const pane = pick.closest('[data-station-pane="hook"]');
    if (!pane || !pane.__hooks) return;
    // A3: disable all pick buttons immediately to block rapid-click
    pane.querySelectorAll("[data-hook-pick]").forEach((b) => { b.disabled = true; });
    const idx = Number(pick.getAttribute("data-hook-pick"));
    try {
      await putJson(wsUrl("/drama/setup"), { hook: pane.__hooks[idx] });
      showToast("钩子已锁定", "info");
      await loadStationHooks();
      await loadDramaProgress();
    } catch (err) {
      showToast("保存失败：" + err.message, "error");
      // Re-enable so user can retry
      pane.querySelectorAll("[data-hook-pick]").forEach((b) => { b.disabled = false; });
    }
  });
}
```

在 `initDramaWrite()` 里调用一次 `bindHookPickDelegate()`（替代旧的 inline 绑定）。

> **Codex 注意**：
> - `pane.__hooks = hooks` 是把数据贴在 DOM 节点上，避免闭包持久引用导致内存泄漏。
> - `document.addEventListener` 全局只 bind 一次，因为 `bindHookPickDelegate` 仅在 `initDramaWrite()` 调用 1 次，page navigation 重新载入页面（不是 SPA）所以 document 也是新的。
> - **iter 037 测试 `test_static_js_has_hook_picker` 之类的（如有）必须更新断言** —— 如果有测试断言 `pane.addEventListener("click"` 字面量，本轮要改为断言 `bindHookPickDelegate` 存在。

---

## §A.3 Hook picker rapid-click race（P2）

合并进 §A.2 的修法里。上面 `pane.querySelectorAll("[data-hook-pick]").forEach((b) => b.disabled = true)` 已经覆盖。

测试：

```python
def test_hook_picker_disables_all_buttons_on_first_click(self) -> None:
    # 在 static.JS_DASHBOARD 里 grep：
    # 期望 bindHookPickDelegate 里包含 'forEach((b) => { b.disabled = true; })'
    js = static.JS_DASHBOARD
    self.assertIn("bindHookPickDelegate", js)
    self.assertIn("data-hook-pick", js)
    self.assertIn("forEach((b) => { b.disabled = true; })", js)
```

---

## §A.4 `loadTabPanel` 错误兜底（P2）

### 问题

```javascript
function loadTabPanel(tabName) {
  const container = document.getElementById("tab-" + tabName);
  if (!container) return;
  const lazy = container.querySelector("[data-lazy]");
  if (!lazy) return;
  if (lazy.dataset.loaded === "1") return;
  const url = lazy.dataset.lazy;
  fetch(url)
    .then((res) => res.json().then((d) => ({ ok: res.ok, data: d })))
    .then((wrap) => {
      if (!wrap.ok) throw new Error(wrap.data.error || "load failed");
      lazy.dataset.loaded = "1";
      const renderer = window["__renderPanel_" + tabName];
      if (renderer) renderer(lazy, wrap.data);
      else lazy.innerHTML = '<pre>' + escapeHtml(JSON.stringify(wrap.data, null, 2)) + '</pre>';
    })
    .catch((err) => {
      lazy.innerHTML = '<div class="alert error">' + escapeHtml(err.message || String(err)) + '</div>';
    });
}
```

`res.json()` 抛 SyntaxError（非法 JSON）时 catch 能接到，但 `lazy.dataset.loaded` 仍是 "0"，行为正确。但 `dataset.loaded = "1"` 在错误后没回滚 —— 实际上**没有**这个 bug；当前实现 `dataset.loaded = "1"` 只在 try 块 if 通过后才设。**审 subagent 找的这一处其实没问题**。

**真问题**（细看）：`fetch().then(res => res.json().then(...))` 嵌套 promise chain 一旦 `res.json()` 失败（response body 不是 JSON），错误被 catch 但 `wrap` 是 undefined，触发误导性 alert "Cannot read property 'ok' of undefined"。

### 修法

改为 `await` 风格 + 明确分支：

```javascript
async function loadTabPanel(tabName) {
  const container = document.getElementById("tab-" + tabName);
  if (!container) return;
  const lazy = container.querySelector("[data-lazy]");
  if (!lazy) return;
  if (lazy.dataset.loaded === "1") return;
  const url = lazy.dataset.lazy;
  try {
    const res = await fetch(url);
    let data;
    try {
      data = await res.json();
    } catch (parseErr) {
      throw new Error("response is not valid JSON (status " + res.status + ")");
    }
    if (!res.ok) {
      throw new Error(data.error || "HTTP " + res.status);
    }
    lazy.dataset.loaded = "1";
    const renderer = window["__renderPanel_" + tabName];
    if (renderer) renderer(lazy, data);
    else lazy.innerHTML = '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
  } catch (err) {
    lazy.innerHTML = '<div class="alert error">' + escapeHtml(err.message || String(err)) + '</div>';
  }
}
```

> **Codex 注意**：施工单 §3 红线 #5 要求"保留 `loadTabPanel` 标识符"——只改实现，函数名不变。

---

## §A.5 `__pending_toast` 跳转失败清理（P2）

### 问题

`showDeleteModal` 里：

```javascript
sessionStorage.setItem("__pending_toast",
  JSON.stringify({ kind: "info", msg: "已删除 《" + name + "》 → " + data.trashed_to }));
window.location.href = "/";
```

如果 `location.href` 失败（极少见，但浏览器 popup blocker / extension 拦截），sessionStorage 残留。下次用户在同一 tab 打开任何页面，假"已删除" toast 弹出。

drama wizard 提交后也有类似模式：

```javascript
sessionStorage.setItem("__pending_toast",
  JSON.stringify({ kind: "info", msg: "短剧 workspace 已创建：" + data.name }));
window.location.href = "/w/" + encodeURIComponent(data.name) + "/write?step=setup";
```

### 修法

加 helper：

```javascript
function setPendingToastAndNavigate(toast, url) {
  sessionStorage.setItem("__pending_toast", JSON.stringify(toast));
  // iter 038 A5: schedule cleanup in case navigation fails or is delayed.
  // 5 seconds is longer than any normal navigation; if we're still on this
  // page after 5s, the toast is stale, clear it.
  setTimeout(function () {
    sessionStorage.removeItem("__pending_toast");
  }, 5000);
  window.location.href = url;
}
```

替换 2 处 `sessionStorage.setItem("__pending_toast", ...) + window.location.href = ...` 为 `setPendingToastAndNavigate(...)` 调用。

测试（grep 即可）：

```python
def test_static_js_has_pending_toast_cleanup(self) -> None:
    js = static.JS_DASHBOARD
    self.assertIn("setPendingToastAndNavigate", js)
    self.assertIn("sessionStorage.removeItem", js)
```

---

## §A.6 `renderPlanChapters` 最外层非数组早返回（P2）

### 问题

iter 035 §A.2 修了 5 处 `Array.isArray` 内部兜底，但 `chapters` 整体不是数组（是字符串 / 对象 / null）时：

```javascript
function renderPlanChapters(box, plan, draftChapters, draftVerdicts) {
  if (!box) return;
  const chapters = Array.isArray(plan && plan.chapters) ? plan.chapters : [];  // iter 035 修了
  const arc = (plan && plan.overall_arc) || "";
  if (!chapters.length) { ... }
  ...
}
```

如果 `chapters = "string"` 走 `[]`，无害。如果 `chapters = {0: ...}` 走 `[]`，无害。**实际**没问题。subagent 的 P2.4 也是误报 —— iter 035 修复已经覆盖。

**改为**：真问题是 `draftChapters` 不是数组时 `new Set(draftChapters.map(...))` 抛。补丁：

```javascript
function renderPlanChapters(box, plan, draftChapters, draftVerdicts) {
  if (!box) return;
  const chapters = Array.isArray(plan && plan.chapters) ? plan.chapters : [];
  if (!chapters.length) {
    box.innerHTML = '<p class="muted">尚无章节计划。先在「续写」里生成一份。</p>';
    return;
  }
  // iter 038 A6: defend against draftChapters being non-array (server bug or
  // local edit dropped the field)
  const draftArr = Array.isArray(draftChapters) ? draftChapters : [];
  const draftSet = new Set(draftArr.map((n) => Number(n)));
  // ...剩余原样
}
```

测试：

```python
def test_static_js_renderPlanChapters_defends_draftChapters_non_array(self) -> None:
    js = static.JS_DASHBOARD
    self.assertIn("Array.isArray(draftChapters)", js)
```

---

## §A.7 Drama 测试共享 `DramaTestBase`（P2）

### 问题

`tests/test_drama_planner.py:20-34`、`tests/test_hook_designer.py:20-34`、`tests/test_drama_wizard_full_form.py` 三个文件的 setUp/tearDown 几乎一样：

```python
def setUp(self) -> None:
    os.environ["OPENAI_MODEL"] = "mock"
    self._tmp = tempfile.TemporaryDirectory()
    self._saved_ws_dir = paths.WORKSPACE_DIR
    self._saved_env = os.environ.get("WORKSPACE_NAME")
    os.environ.pop("WORKSPACE_NAME", None)
    paths.WORKSPACE_DIR = Path(self._tmp.name)

def tearDown(self) -> None:
    paths.WORKSPACE_DIR = self._saved_ws_dir
    if self._saved_env is None:
        os.environ.pop("WORKSPACE_NAME", None)
    else:
        os.environ["WORKSPACE_NAME"] = self._saved_env
    self._tmp.cleanup()
```

### 修法

新建 `tests/_drama_base.py`：

```python
"""iter 038: shared setUp/tearDown for drama-related tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cli_workspace import init_workspace
from src.web import wizard


class DramaTestBase(unittest.TestCase):
    """Base class for any test that needs a drama workspace + snapshot.

    Sets OPENAI_MODEL=mock, isolates WORKSPACE_NAME / WORKSPACE_DIR,
    provides ``_make_drama_workspace(name, track, snapshot=True)`` for
    quick fixture creation.
    """

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _make_drama_workspace(
        self,
        name: str,
        track: str = "霸总",
        *,
        snapshot: bool = True,
        episode_count: int = 12,
        episode_duration_seconds: int = 60,
    ) -> None:
        """Create a drama workspace with wizard_input.json (and optionally snapshot)."""
        init_workspace(name, type="drama")
        data_dir = paths.WORKSPACE_DIR / name / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "wizard_input.json").write_text(
            json.dumps({
                "workspace": name,
                "topic": "test topic",
                "track": track,
                "episode_count": episode_count,
                "episode_duration_seconds": episode_duration_seconds,
                "schema_version": 1,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        if snapshot:
            wizard._snapshot_creation_standard(name)
```

改 3 个测试文件用 `DramaTestBase`：

```python
# tests/test_drama_planner.py
from tests._drama_base import DramaTestBase

class DramaPlannerTests(DramaTestBase):
    def _workspace(self, name, track="霸总", *, snapshot=True):
        self._make_drama_workspace(name, track, snapshot=snapshot)
    # 其余测试方法不动
```

> **Codex 注意**：`_drama_base.py` 也用下划线前缀避免 unittest discover 当 test。

---

## §A.8 `workspace_meta` 并发 + corrupt JSON 测试（P2）

`tests/test_workspace_meta.py` 加 2 测试：

```python
def test_concurrent_read_write_does_not_corrupt(self) -> None:
    """iter 038 A8: workspace_meta.read while write is in progress
    must not return a half-written file."""
    import threading
    name = "concurrent"
    workspace_meta.write(name, type="novel")
    results = []
    barrier = threading.Barrier(3)

    def writer():
        barrier.wait()
        for _ in range(50):
            workspace_meta.write(name, type="drama")
            workspace_meta.write(name, type="novel")

    def reader():
        barrier.wait()
        for _ in range(50):
            try:
                m = workspace_meta.read(name)
                results.append(m["type"])
            except Exception as exc:
                results.append(f"err:{exc}")

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(2)]
    for t in threads: t.start()
    barrier.wait()  # ensure all enter
    for t in threads: t.join(timeout=5)
    # Every result must be a valid type (or err:..., but never half-written)
    for r in results:
        self.assertIn(r, {"novel", "drama"}, f"corrupt read: {r!r}")


def test_malformed_json_with_bom_falls_back_to_novel(self) -> None:
    """iter 038 A8: file with UTF-8 BOM should not break read()."""
    path = workspace_meta.workspace_meta_path("bommed")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write file with BOM prefix + then truncated content
    path.write_bytes(b"\xef\xbb\xbf{\"type\": \"drama")  # truncated
    m = workspace_meta.read("bommed")
    self.assertEqual(m["type"], "novel")  # fallback per iter 036 contract
    self.assertEqual(m["schema_version"], 0)
```

---

## §A.9 `_safe_entry_path` 边界测试（P2）

`tests/test_web_trash.py` 加 4 测试：

```python
def test_safe_entry_path_rejects_empty_string(self) -> None:
    ok, reason = _safe_entry_path("")
    self.assertFalse(ok)
    self.assertEqual(reason, "malformed_entry")


def test_safe_entry_path_rejects_null_byte(self) -> None:
    ok, reason = _safe_entry_path("alpha\x00__20260101_120000")
    self.assertFalse(ok)
    self.assertEqual(reason, "malformed_entry")


def test_safe_entry_path_rejects_too_long(self) -> None:
    ok, reason = _safe_entry_path("a" * 200 + "__20260101_120000")
    self.assertFalse(ok)
    self.assertEqual(reason, "malformed_entry")


def test_safe_entry_path_accepts_unicode_nfc(self) -> None:
    # 龙 is in NFC form already; ensure regex matches Han characters
    ok, reason = _safe_entry_path("龙族__20260101_120000")
    self.assertTrue(ok, f"reason: {reason}")
```

---

## §A.10 hook_designer episode_count mismatch（P2）

`tests/test_hook_designer.py` 加：

```python
def test_hooks_raises_when_setup_missing_required_fields(self) -> None:
    """iter 038 A10: if station ① output lacks core_setup.protagonist,
    station ② must raise (not silently fall back to wizard_input track)."""
    self._make_drama_workspace("partial", "霸总")
    # Create a corrupted setup.json with track but no core_setup
    setup_path = paths.WORKSPACE_DIR / "partial" / "outputs" / "episodes" / "episode_01.setup.json"
    setup_path.parent.mkdir(parents=True, exist_ok=True)
    setup_path.write_text(
        json.dumps({"track": "霸总"}),  # missing core_setup entirely
        encoding="utf-8",
    )
    # Hook designer should raise — partial setup is not a valid station ① output
    with self.assertRaises((KeyError, ValueError)) as ctx:
        hook_designer.run("partial", mock=True)
    # The error should mention the missing field for debugging
    self.assertIn("core_setup", str(ctx.exception).lower())
```

并且改 `src/hook_designer.py` 加这个 raise 检查：

```python
def run(workspace: str, *, mock: bool = True) -> Dict[str, Any]:
    # ...
    setup_path = paths.WORKSPACE_DIR / workspace / "outputs" / "episodes" / "episode_01.setup.json"
    if not setup_path.is_file():
        raise FileNotFoundError(
            f"station ① must complete before station ②; missing {setup_path}"
        )
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    # iter 038 A10: validate station ① output structure
    if not isinstance(setup.get("core_setup"), dict) or "protagonist" not in setup["core_setup"]:
        raise ValueError(
            f"station ① output for {workspace!r} missing core_setup.protagonist; "
            f"station ② cannot proceed"
        )
    # ...剩余原样
```

---

## §A.11 `workspace_ctx` thread-safety 文档化（P2）

改 `src/web/workspace_ctx.py` docstring（在文件顶部 module docstring 后追加）：

```python
"""
Thread-safety contract
======================

``use_workspace(name)`` is a context manager that mutates ``paths``
module-level state for the current thread only. Implementation uses
``threading.local()`` so nested calls in the same thread stack
correctly.

**Cross-thread**: do NOT share an open ``use_workspace`` context across
threads. Each thread that needs a workspace must call ``use_workspace``
itself.

**Tests**: ``tests/test_web_workspace_ctx.py:test_thread_isolation``
locks this contract with a 2-thread race.
"""
```

`tests/test_web_workspace_ctx.py` 加：

```python
def test_thread_isolation(self) -> None:
    """iter 038 A11: use_workspace state is per-thread; one thread's
    workspace context must not leak to another."""
    import threading
    results = {}

    def worker(name, expected):
        with use_workspace(name):
            results[name] = paths.workspace_dir() == expected

    barrier = threading.Barrier(2)
    def w1():
        barrier.wait()
        worker("alpha", paths.WORKSPACE_DIR / "alpha")
    def w2():
        barrier.wait()
        worker("beta", paths.WORKSPACE_DIR / "beta")

    (paths.WORKSPACE_DIR / "alpha").mkdir(parents=True, exist_ok=True)
    (paths.WORKSPACE_DIR / "beta").mkdir(parents=True, exist_ok=True)
    t1 = threading.Thread(target=w1)
    t2 = threading.Thread(target=w2)
    t1.start(); t2.start()
    t1.join(); t2.join()
    self.assertTrue(results["alpha"])
    self.assertTrue(results["beta"])
```

---

## 3. 工程铁律

### 🚨 不可逾越的红线

1. **本轮严格无新功能**。不动 schema、不接 AI 绘画、不新增页面 / API / fixture / prompt。
2. **沙箱 socket bind ERROR 从 6 → 0**（用 skipIf 优雅跳过，**不**改成 `@unittest.expectedFailure` 也不删测试）；Codex 真环境 6 测试照跑、照 PASS。
3. **保留全部 30 个 JS 标识符 + 协议表达式**（与 iter 037 §3 一致）。本轮新增可被字符串检测的标识符：
   - `bindHookPickDelegate`
   - `setPendingToastAndNavigate`
   - `__hooks`（pane 上的数据贴存）
4. **drama 创作内容只读**：`tests/fixtures/drama/*.json`、`prompts/drama/*.txt`、`docs/product/short_drama_creation_standard.md`、`docs/product/short_drama_module.md` 一行不改。Claude §B 已经在 iter 037 commit `bfa2a4b` 落定。
5. **`loadTabPanel` 改 async/await 但函数名不变**（iter 026 测试断言此名字）。
6. **不要 push**。提交 message：`Iteration 038: P1+P2 hardening pass (sandbox skip / hook leak / test fixture extraction)`

### ⚠️ 容易踩的坑

| # | 坑 | 对策 |
|---|---|---|
| K1 | `_socket_skip.py` 被 `unittest discover` 当成测试模块 | 文件名带下划线前缀（不以 `test_` 开头） |
| K2 | `_drama_base.py` 同 | 下划线前缀 |
| K3 | `SOCKET_BIND_BLOCKED` 在 import 时 probe，引入跨平台 / 临时 socket exhaustion 风险 | 用 with-statement 自动关 socket；OSError 默认返 False（让测试自己 fail，而不是 skip） |
| K4 | iter 037 测试如有断言 `pane.addEventListener("click"` 字面量 | 改为断言 `bindHookPickDelegate` |
| K5 | A2 修法把 `pane.__hooks = hooks` 贴 DOM 节点 | 节点被替换时旧 `__hooks` 自然 GC，无内存泄漏；但**不要**改用 `window.__hooks` global（多 workspace 共用会撞） |
| K6 | A5 `setTimeout` 5000ms cleanup 与 toast 显示时长（也 5000ms）数值相同 | 故意的 —— navigation 应该秒级完成；toast 是 navigation 完成后的事 |
| K7 | A7 `DramaTestBase` 继承时 unittest 仍把它当测试类发现并跑 0-test class | base 类内不要有 `test_*` 方法，且 class 名不以 `Test` 开头（`DramaTestBase` 本身不被 discover） |
| K8 | A8 并发测试 flaky | 用 `threading.Barrier` 同步起点，循环 50 次，验证所有 result 都是合法值，不验证特定 race 序 |
| K9 | A10 改 hook_designer.run 加 raise，可能破现有 iter 037 测试 | iter 037 `test_mock_returns_three_hooks_per_track` setUp 里通过 `_make_drama_workspace + 手写 setup.json with core_setup.protagonist` 已经满足；不破 |
| K10 | A1 skipIf 的 reason 字符串 grep 测试 | 加 `tests/test_socket_skip.py` 测试 `SOCKET_BIND_BLOCKED in (True, False)`；reason 字面量本身不需测 |

### ✅ 必须自带的边界测试（继承习惯）

至少 4 条：
1. `SOCKET_BIND_BLOCKED` 是 bool（不是 None / 异常）
2. 6 个原 ERROR 测试在沙箱里返回 SKIP 而非 ERROR / FAIL
3. `bindHookPickDelegate` 仅在 JS_DASHBOARD 出现 1 次（避免重复 bind）
4. `setPendingToastAndNavigate` 调用点为 2 处（删除 workspace + drama wizard 提交）

---

## 4. Codex 自检（commit 前必跑）

```bash
# 1. 全套 unittest — 沙箱应 OK + 6 skipped；Codex 真环境应全 OK（不再有 ERROR 注脚）
.venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
# 沙箱期望："Ran N tests, OK (skipped=6)" — N = 536 + 本轮新增

# 2. 沙箱 skip 数 = 6（核心目标）
.venv/bin/python3 -c "
import unittest
loader = unittest.TestLoader()
suite = loader.loadTestsFromName('tests')
runner = unittest.TextTestRunner(verbosity=0)
result = runner.run(suite)
print(f'skipped: {len(result.skipped)}')
print(f'errors: {len(result.errors)}')
print(f'failures: {len(result.failures)}')
"
# 沙箱期望：skipped >= 6, errors = 0, failures = 0

# 3. 关键字符串 + dispatcher 不变（30 + 3 = 33）
.venv/bin/python3 -c "
from src.web import static
required = [
    # iter 026-037 保留 30 个
    'loadTabPanel', 'scheduleReadiness', 'writeBookJobRunning',
    'readinessRequestSeq', 'readinessTimer',
    \"submit.disabled = writeBookJobRunning || data.status === 'blocked'\",
    'showToast', 'showDeleteModal', 'jumpToParagraph', 'initInsights',
    'data-jump-line', '__pending_toast',
    'initPlan', 'renderPlanChapters', 'renderOutlineMarkdown', 'renderDecisions',
    '_mdToHtml', 'data-plan-pane',
    'initTrash', 'reloadTrashList', 'showPurgeModal',
    'data-trash-restore', 'data-trash-purge',
    '_ALLOWED_TAB_KEYS', 'typeBadge',
    'initDramaWrite', 'loadStationSetup', 'loadStationHooks',
    'loadDramaProgress', 'data-station-pane',
    # iter 038 新增 3 个
    'bindHookPickDelegate', 'setPendingToastAndNavigate', 'Array.isArray(draftChapters)',
]
for kw in required:
    assert kw in static.JS_DASHBOARD, f'missing: {kw}'
n = static.JS_DASHBOARD.count('Array.isArray(')
assert n >= 6, f'Array.isArray count = {n}'  # iter 035 5 + iter 038 1 = 6
print(f'all {len(required)} identifiers present; Array.isArray={n}')
"

# 4. dispatcher 14 路径不变（与 iter 037 §4 第 2 块完全相同）
PYTHONPATH=. .venv/bin/python3 -c "<iter 037 §4 第 2 块脚本>"
# 前 13 条 200；最后一条（drama /continue）404
```

把 4 块输出原文贴进 §7 Codex Run Log。

---

## 5. Claude 验收：V1-V12

| # | 项 | 方法 |
|---|---|---|
| V1 | `SOCKET_BIND_BLOCKED` helper 存在且为 bool | grep + import 测 |
| V2 | 6 测试在沙箱里 `skipped` 而非 `ERROR`（**关键**） | 全套 unittest |
| V3 | Codex 真环境 6 测试照 PASS（Codex Run Log 验证） | 读 §7 |
| V4 | `bindHookPickDelegate` 取代 inline pane handler | grep + 测 |
| V5 | hook pick 按钮被点后 `disabled = true` | grep |
| V6 | `loadTabPanel` 改 async/await 但函数名不变 | grep |
| V7 | `setPendingToastAndNavigate` 2 处调用 | grep `setPendingToastAndNavigate` 计数 |
| V8 | `Array.isArray(draftChapters)` 兜底 | grep |
| V9 | `DramaTestBase` 抽取 + 3 测试文件继承 | import 测 |
| V10 | `workspace_meta` 并发 + BOM 测试通过 | 单测 |
| V11 | `_safe_entry_path` 4 新边界测试通过 | 单测 |
| V12 | iter 037 基线 536 + 本轮新增 ≈ 550；沙箱 errors=0, skipped=6 | 全套 unittest |

---

## 6. 不在 iter 038

- 站 ③ 分镜 / 站 ④ 角色（iter 039）
- AI 绘画 client / Comfy 导出（iter 039）
- drama_reviewer（iter 039）
- 真模型接入（iter 040+）
- 任何 P3 修复（转 iter 040 backlog）：
  - hardcoded inline color hex in JS badge（应抽 `.badge.drama / .badge.novel` CSS class）
  - subscore table inline style（应抽 CSS class + data-attribute）
  - workspace card metric inline font-size
  - `_workspace_html_guard_novel_only` 与 `_workspace_html_guard` 抽象
  - toast 5000ms 硬编码无 dismiss 按钮
  - drama wizard textarea placeholder 改 user-facing 文案
- 任何"功能增强"性质改动（drama 子页面 / 导出 / 评审）

---

## 7. Codex Run Log（Codex 执行后填）

> Codex 请在这里粘贴 §4 四块命令的原文输出。**注意**：本轮 `unittest discover` 在 Codex 真环境应该 `OK` 无 ERROR 也无 skipped（因为 `SOCKET_BIND_BLOCKED == False`）；在沙箱里应该 `OK (skipped=6)`。不再需要 6-ERROR 注脚。

执行时间：2026-06-04 00:25 CST。执行环境：Codex sandbox，mock-only；未运行任何真模型 smoke，未修改 `.env` / `data/` / `outputs/` / `小说txt/` / `tests/fixtures/drama/` / `prompts/drama/` / `docs/product/short_drama_*.md`。

### 1. 全套 unittest

```bash
$ .venv/bin/python3 -m unittest discover -s tests 2>&1 | tail -5
.........................................
----------------------------------------------------------------------
Ran 549 tests in 2.110s

OK (skipped=6)
```

### 2. 沙箱 skipped/errors/failures 计数

计划中的 `loader.loadTestsFromName('tests')` 在当前仓库布局下返回 `Ran 0 tests`，不能作为有效计数。因此本轮采用标准 discover 输出作为全套计数依据：`OK (skipped=6)` 等价于 `errors=0, failures=0, skipped=6`。另外对原 6 个 socket-bind ERROR 所在套件做了 targeted 复核：

```bash
$ .venv/bin/python3 -m unittest tests.test_socket_skip tests.test_web_server tests.test_web_hardening
.ssss...ss....
----------------------------------------------------------------------
Ran 14 tests in 0.019s

OK (skipped=6)
```

### 3. 33 个 JS 标识符 + `Array.isArray` 守门

```bash
$ .venv/bin/python3 -c "<§4 string guard>"
all 33 identifiers present; Array.isArray=6
```

额外 JS 语法检查：

```bash
$ node --check /private/tmp/iter038_app.js
$ node --check /private/tmp/iter038_wizard.js
```

两条命令均退出 0，无输出。

### 4. dispatcher 14 路径不变

```bash
$ PYTHONPATH=. .venv/bin/python3 -c "<iter 037 §4 dispatcher smoke>"
200 /
200 /trash
200 /wizard
200 /settings
200 /w/a_n/
200 /w/a_n/continue
200 /w/b_d/
200 /w/b_d/write
200 /w/b_d/jobs
404 /w/b_d/continue
```

### 5. 额外 sanity

```bash
$ OPENAI_MODEL=mock OPENAI_API_KEY= OPENAI_BASE_URL= PLANNER_API_KEY= PLANNER_BASE_URL= PLANNER_MODEL= OPENAI_STREAM= PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh
...
Report snapshots OK: data/chapter_manifest.md, outputs/reviews/review_summary.md
...
# Cost Estimate
- chapters: 1
- source_chars: 86
- estimated_source_tokens: 54
- extract_calls: 1
- compress_calls: 1
- debate_calls: 36
- review_calls_per_written_chapter: 7
```

```bash
$ OPENAI_MODEL=mock OPENAI_API_KEY= OPENAI_BASE_URL= PLANNER_API_KEY= PLANNER_BASE_URL= PLANNER_MODEL= OPENAI_STREAM= .venv/bin/python3 main.py preflight
PREFLIGHT: ok

## FATAL
- none

## WARN
- none
```

```
LiteLLM 在无网络 sandbox 中会打印 cost map fallback warning；不影响 mock-only 验证。
```

---

## 8. Acceptance Result（Claude 验收后填）

> Claude 填写 V1-V12 结果 + 转 iter 039 backlog（drama 站 ③ ④）+ 转 iter 040 backlog（P3 清单）。

Codex pre-commit self-check: V1-V12 对应实现均已落地，Claude 最终验收待 §5 执行。

Subagent 审核：
- 审核 agent：Wegener（只读 diff/static review）。
- 覆盖范围：A1 socket skip、A2/A3 hook picker delegate、A4 `loadTabPanel`、A5 pending toast、A6 `draftChapters` guard、A7 test base extraction、A8 workspace_meta atomic write/tests、A9-A11 边界测试/doc。
- 初始结论：Go；无 blocker。指出 1 个 P3：`tests/_socket_skip.py` 只 probe loopback，但 `ServeHostWarningTests` 也会 bind `0.0.0.0`。
- 处理结果：已补 `SOCKET_WILDCARD_BIND_BLOCKED = _probe("0.0.0.0")`；`ServeHostWarningTests` 在 loopback 或 wildcard 任一被 sandbox 禁止时 skip。targeted socket suite 复跑 `OK (skipped=6)`。
- 未修风险：无本轮 blocker。仍不开放 drama 站 ③/④，不接真模型，不接 AI 绘画；P3 UI polish 仍按 §6 留后续。
