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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>本地写作工作台</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="app-header">
  <div>
    <h1>本地写作工作台</h1>
    <p class="muted">127.0.0.1 · mock-first · 单用户 Beta</p>
  </div>
  <nav><a class="button secondary" href="/wizard">新建作品</a><a class="button secondary" href="/settings">模型设置</a></nav>
</header>
<main class="page-shell">
  <section class="hero-band">
    <div>
      <p class="eyebrow">书架</p>
      <h2>选择一本书，继续安全写下去</h2>
    </div>
    <div class="hero-stats" id="shelf-stats"></div>
  </section>
  <section class="section-flat">
    <div id="workspace-shelf" class="workspace-grid" data-empty="$EMPTY_HINT">loading...</div>
  </section>
</main>
<script>window.PAGE_KIND = "index";</script>
<script src="/static/app.js"></script>
</body>
</html>
"""
)


_WORKSPACE_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$NAME · 写作工作台</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="app-header">
  <div>
    <h1><a href="/">←</a> $NAME</h1>
    <p class="muted">写作工作台 · 设置起点、生成计划、检查就绪、继续写书</p>
  </div>
  <nav><a class="button secondary" href="/wizard">新建作品</a><a class="button secondary" href="/settings">模型设置</a></nav>
</header>
<main class="page-shell">
  <section class="workspace-hero">
    <div>
      <p class="eyebrow">当前作品</p>
      <h2>$NAME</h2>
    </div>
    <div id="workspace-summary" class="summary-strip"></div>
  </section>

  <section class="cockpit-grid">
    <div class="panel action-panel">
      <div class="panel-title">
        <h2>准备续写</h2>
        <span id="readiness-pill" class="pill">loading</span>
      </div>
      <form id="start-point-form" class="control-grid">
        <label>续写起点<select name="start_point" id="start-point-select"></select></label>
        <button type="submit" class="button secondary">保存起点</button>
      </form>
      <form id="plan-form" class="control-grid">
        <label>计划章节数<input name="target_chapters" type="number" min="1" max="200" value="5"></label>
        <button type="submit" class="button secondary" id="plan-submit">生成/重生成计划</button>
      </form>
      <form id="write-book-form" class="write-grid">
        <label>写几章<input name="chapters" type="number" min="1" value="1"></label>
        <label>从第几章<input name="resume_from" type="number" min="1" value="1"></label>
        <label>预算 CNY<input name="budget_cny" type="number" min="0" step="0.1" value="0"></label>
        <label>每几章重规划<input name="replan_every" type="number" min="0" value="0"></label>
        <label>最大重试<input name="max_retries" type="number" min="0" value="2"></label>
        <label>推进置信度<input name="min_confidence" type="number" min="0" max="1" step="0.05" value="0.7"></label>
        <label class="check-row"><input name="auto_advance" type="checkbox" checked> 自动推进实体状态</label>
        <button type="submit" class="button primary" id="write-book-submit">继续写书</button>
      </form>
    </div>
    <div class="panel">
      <div class="panel-title"><h2>就绪检查</h2><button class="icon-button" id="refresh-readiness" title="刷新">↻</button></div>
      <div id="readiness-panel" class="panel-body">loading...</div>
      <div id="job-status" class="panel-body"></div>
      <div id="recent-jobs" class="panel-body"></div>
    </div>
  </section>

  <section class="tabs">
    <div class="tab-list">
      <button class="tab active" data-tab="drafts">产出</button>
      <button class="tab" data-tab="reviews">评审</button>
      <button class="tab" data-tab="manifest">原文章节</button>
      <button class="tab" data-tab="status">流水线</button>
      <button class="tab" data-tab="cost">成本</button>
    </div>
    <div class="tab-panel active" id="tab-drafts"><div id="drafts-panel" class="panel-body">loading...</div></div>
    <div class="tab-panel" id="tab-reviews"><div class="panel-body" data-source="reviews">loading...</div></div>
    <div class="tab-panel" id="tab-manifest"><div class="panel-body" data-source="manifest">loading...</div></div>
    <div class="tab-panel" id="tab-status"><div class="panel-body" data-source="status">loading...</div></div>
    <div class="tab-panel" id="tab-cost"><div class="panel-body" data-source="cost">loading...</div></div>
  </section>
</main>
<script>window.WORKSPACE_NAME = "$NAME";</script>
<script>window.PAGE_KIND = "workspace";</script>
<script src="/static/app.js"></script>
</body>
</html>
"""
)


def render_index(workspaces: Iterable[str]) -> str:
    names = list(workspaces)
    empty_hint = "" if names else "还没有作品。点击“新建作品”上传 epub/txt。"
    return _INDEX_TPL.substitute(EMPTY_HINT=escape(empty_hint))


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
