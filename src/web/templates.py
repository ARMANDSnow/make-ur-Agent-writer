"""iter 025: HTML page templates.

We use ``string.Template`` instead of f-strings so the templates can
contain ``${name}`` placeholders without conflicting with JavaScript's
``${...}`` template literals — embedded JS gets escaped via ``$$``.

The HTML is intentionally a thin skeleton: panels load their data via
``fetch('/api/...')`` from ``static.JS_DASHBOARD``. This keeps the server
side stupid and lets unit tests verify the JSON API independently of any
rendering.
"""

from __future__ import annotations

from html import escape
from string import Template
from typing import Iterable


_INDEX_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>WebUI · 续写 dashboard</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header><h1>续写 dashboard</h1><p class="muted">iter 026 · stdlib-only · 127.0.0.1 · <a href="/wizard">+ 新建 workspace</a> · <a href="/settings">模型设置</a></p></header>
<main>
  <section>
    <h2>Workspaces</h2>
    <ul class="workspace-list">
$ITEMS
    </ul>
    <p class="muted">$EMPTY_HINT</p>
  </section>
</main>
</body>
</html>
"""
)


_WORKSPACE_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>$NAME · WebUI</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header>
  <h1><a href="/">←</a> $NAME</h1>
  <p class="muted">workspace dashboard</p>
</header>
<main>
  <section id="panel-status"><h2>Status</h2><div class="panel-body" data-source="status">loading…</div></section>
  <section id="panel-cost"><h2>Cost</h2><div class="panel-body" data-source="cost">loading…</div></section>
  <section id="panel-manifest"><h2>Manifest</h2><div class="panel-body" data-source="manifest">loading…</div></section>
  <section id="panel-reviews"><h2>Reviews</h2><div class="panel-body" data-source="reviews">loading…</div></section>
</main>
<script>window.WORKSPACE_NAME = "$NAME";</script>
<script src="/static/app.js"></script>
</body>
</html>
"""
)


def render_index(workspaces: Iterable[str]) -> str:
    names = list(workspaces)
    if names:
        items = "\n".join(
            f'      <li><a href="/workspace/{escape(n)}/">{escape(n)}</a></li>' for n in names
        )
        empty_hint = ""
    else:
        items = ""
        empty_hint = (
            "(no workspaces yet — run `python3 main.py workspace-init <name>` "
            "to create one)"
        )
    return _INDEX_TPL.substitute(ITEMS=items, EMPTY_HINT=empty_hint)


def render_workspace(name: str) -> str:
    return _WORKSPACE_TPL.substitute(NAME=escape(name))


_WIZARD_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>新建 workspace · WebUI</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header>
  <h1><a href="/">←</a> 新建 workspace</h1>
  <p class="muted">上传小说 epub / txt，自动跑完 9 步 SOP 写出第 1 章</p>
</header>
<main>
  <section id="panel-upload">
    <h2>第 1 步 · 上传</h2>
    <form id="wizard-form" enctype="multipart/form-data">
      <p><label>workspace 名 <input name="workspace" required pattern="[a-zA-Z0-9_一-鿿][a-zA-Z0-9_一-鿿-]{0,30}[a-zA-Z0-9_一-鿿]?" title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符"></label></p>
      <p><label>小说文件 <input name="upload" type="file" accept=".epub,.txt" required></label></p>
      <p><button type="submit">开始</button></p>
    </form>
    <div id="upload-error" class="error"></div>
  </section>
  <section id="panel-progress" hidden>
    <h2>第 2 步 · 流水线进度</h2>
    <div class="panel-body" id="progress-body">等待 worker…</div>
  </section>
</main>
<script src="/static/wizard.js"></script>
</body>
</html>
"""
)


def render_wizard() -> str:
    return _WIZARD_TPL.substitute()


_SETTINGS_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>模型设置 · WebUI</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header>
  <h1><a href="/">←</a> 模型设置</h1>
  <p class="muted">.env 编辑器 · 保存后需重启 web 服务才生效</p>
</header>
<main>
  <section>
    <h2>当前配置</h2>
    <div id="restart-banner" class="error" hidden></div>
    <form id="settings-form" class="kv-form"></form>
    <p><button type="submit" form="settings-form">保存</button></p>
    <div id="settings-error" class="error"></div>
  </section>
</main>
<script src="/static/settings.js"></script>
</body>
</html>
"""
)


def render_settings() -> str:
    return _SETTINGS_TPL.substitute()
