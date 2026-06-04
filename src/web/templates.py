"""HTML page templates with shared sidebar + topbar shell.

Information architecture:

* ``/`` — workspace shelf (no workspace context).
* ``/wizard`` — onboarding (no workspace context).
* ``/settings`` — global .env editor (no workspace context).
* ``/w/<name>`` — workspace overview (sidebar shows section list).
* ``/w/<name>/continue`` — start-point + plan + write-book cockpit.
* ``/w/<name>/write`` — drama 4-station write wizard.
* ``/w/<name>/chapters`` — manifest + drafts list.
* ``/w/<name>/chapter/<n>`` — single-chapter detail (text / review /
  lint / advisor / history tabs).
* ``/w/<name>/reviews`` — aggregated reviews.
* ``/w/<name>/jobs`` — task history + log tail.

Templates compose three pieces: ``_render_shell`` writes the
``<!doctype>`` + sidebar + topbar wrapper; each page builds its main
HTML and hands it to the shell. We keep ``string.Template`` semantics
for the outermost shell so ``${...}`` JS literals in iter 025-style
embedded scripts continue to escape via ``$$``.
"""

from __future__ import annotations

from html import escape
from string import Template
from typing import Iterable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

_BASE_TPL = Template(
    """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$TITLE</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="app $APP_CLASS">
  $SIDEBAR
  <div class="main">
    <header class="topbar">
      <nav class="breadcrumb">$BREADCRUMB</nav>
      <div class="topbar-actions">$TOPBAR_ACTIONS</div>
    </header>
    <main class="page">
      $MAIN
    </main>
    <div class="toast-stack" id="toast-stack" aria-live="polite"></div>
  </div>
</div>
<script>
window.PAGE_KIND = "$PAGE_KIND";
window.WORKSPACE_NAME = "$WORKSPACE";
window.CHAPTER_NO = $CHAPTER_NO;
</script>
<script src="/static/app.js"></script>
$EXTRA_SCRIPTS
</body>
</html>
"""
)


def _render_shell(
    *,
    title: str,
    page_kind: str,
    main_html: str,
    breadcrumb_html: str,
    topbar_actions_html: str = "",
    sidebar_html: str = "",
    workspace: str = "",
    chapter_no: Optional[int] = None,
    extra_scripts: str = "",
) -> str:
    return _BASE_TPL.substitute(
        TITLE=escape(title),
        APP_CLASS="" if sidebar_html else "no-context",
        SIDEBAR=sidebar_html,
        BREADCRUMB=breadcrumb_html,
        TOPBAR_ACTIONS=topbar_actions_html,
        MAIN=main_html,
        PAGE_KIND=escape(page_kind),
        WORKSPACE=escape(workspace),
        CHAPTER_NO=str(chapter_no) if chapter_no is not None else "null",
        EXTRA_SCRIPTS=extra_scripts,
    )


# ---------------------------------------------------------------------------
# Reused fragments
# ---------------------------------------------------------------------------


_WORKSPACE_SECTIONS: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    ("continue", "续写", "continue"),
    ("plan", "计划", "plan"),
    ("chapters", "章节", "chapters"),
    ("reviews", "评审", "reviews"),
    ("insights", "数据", "insights"),
    ("jobs", "任务", "jobs"),
)

_SECTIONS_DRAMA: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    # Drama write currently opens stations 1 and 2; later stations stay locked.
    ("write", "续写", "write"),
    ("jobs", "任务", "jobs"),
)


def _sections_for(workspace_type: str) -> Sequence[tuple[str, str, str]]:
    if workspace_type == "drama":
        return _SECTIONS_DRAMA
    return _WORKSPACE_SECTIONS


def _sidebar(workspaces: Iterable[str], active_workspace: str = "", active_section: str = "") -> str:
    items = []
    for name in workspaces:
        is_active = name == active_workspace
        cls = "sidebar-item active" if is_active else "sidebar-item"
        items.append(
            f'<a class="{cls}" href="/w/{escape(name)}/">'
            f'<span><span class="dot"></span> {escape(name)}</span>'
            f'</a>'
        )
    work_html = "\n".join(items) if items else '<p class="muted" style="padding:0 8px">尚无作品</p>'
    sections_html = ""
    if active_workspace:
        from .workspace_meta import read as _meta_read

        ws_type = _meta_read(active_workspace).get("type", "novel")
        section_items = []
        for key, label, suffix in _sections_for(ws_type):
            href = f"/w/{escape(active_workspace)}/{suffix}" if suffix else f"/w/{escape(active_workspace)}/"
            cls = "sidebar-item active" if key == active_section else "sidebar-item"
            section_items.append(
                f'<a class="{cls}" href="{href}">'
                f'<span><span class="dot"></span> {escape(label)}</span>'
                f'</a>'
            )
        sections_html = (
            '<div class="sidebar-section">'
            f'<h4>《{escape(active_workspace)}》</h4>'
            + "\n".join(section_items)
            + "</div>"
        )
    return (
        '<aside class="sidebar">'
        '<a class="brand" href="/"><span>✦</span> 续写工作台</a>'
        '<div class="sidebar-section">'
        '<h4>书架</h4>'
        f'{work_html}'
        '</div>'
        f'{sections_html}'
        '<div class="sidebar-footer">'
        '<span>127.0.0.1 · 单用户 Beta</span>'
        '<span>本地 Beta</span>'
        '</div>'
        '</aside>'
    )


def _topbar_actions(extra: str = "") -> str:
    base = (
        '<a class="btn btn-ghost" href="/trash">♻ 回收站</a>'
        '<a class="btn btn-ghost" href="/settings">⚙ 设置</a>'
        '<a class="btn btn-primary" href="/wizard">＋ 新建</a>'
    )
    return extra + base


def render_workspace_novel_only_empty(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<section class="section">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>此页面属于小说模块</h3>'
        '<p class="muted">当前 workspace 是短剧。该功能不适用于短剧模块。</p>'
        '<div class="cta cluster">'
        '<a class="btn btn-secondary" href="/w/' + escape(name) + '/">返回短剧概览</a>'
        '<a class="btn btn-primary" href="/w/' + escape(name) + '/write">进入短剧工作台</a>'
        '<a class="btn btn-ghost" href="/w/' + escape(name) + '/jobs">查看任务</a>'
        '</div>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 小说模块",
        page_kind="workspace_empty",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("小说模块", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section=""),
        workspace=name,
    )


def _crumbs(parts: Sequence[tuple[str, Optional[str]]]) -> str:
    """Render breadcrumbs. Each part is (label, href or None for current)."""
    pieces = []
    for i, (label, href) in enumerate(parts):
        if i:
            pieces.append('<span class="sep">/</span>')
        if href is None:
            pieces.append(f'<span class="here">{escape(label)}</span>')
        else:
            pieces.append(f'<a href="{href}">{escape(label)}</a>')
    return "".join(pieces)


# ---------------------------------------------------------------------------
# Page: shelf (index)
# ---------------------------------------------------------------------------


def render_index(workspaces: Iterable[str]) -> str:
    names: List[str] = list(workspaces)
    empty_hint = "" if names else "还没有作品。点击右上角「＋ 新建」上传 epub/txt。"
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">书架</p>'
        '<h1>本地写作工作台</h1>'
        '<p class="muted">选择一本书，继续安全写下去。所有数据保留在 127.0.0.1。</p>'
        '</div>'
        '<div class="shelf-stats" id="shelf-stats"></div>'
        '</header>'
        '<section class="section">'
        f'<div id="workspace-shelf" class="workspace-grid" data-empty="{escape(empty_hint)}">'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title="本地写作工作台",
        page_kind="index",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(names),
    )


# ---------------------------------------------------------------------------
# Page: trash
# ---------------------------------------------------------------------------


def render_trash(workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">回收站</p>'
        '<h1>已删除的作品</h1>'
        '<p class="muted">软删除的作品会进入这里；可 restore 回原名（同名冲突需手动改名），或永久 purge。</p>'
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


# ---------------------------------------------------------------------------
# Page: workspace overview
# ---------------------------------------------------------------------------


def render_workspace_overview(name: str, workspaces: Iterable[str]) -> str:
    from .workspace_meta import read as _meta_read

    meta = _meta_read(name)
    ws_type = meta.get("type", "novel")
    main = _drama_overview_main(name, meta) if ws_type == "drama" else _novel_overview_main(name)
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
        '<section class="overview-hero">'
        '<div class="next-action" id="overview-next-action"></div>'
        '<div class="metric-pair" id="overview-summary"></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">就绪状态</h2></div>'
        '<div id="overview-blockers"></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">细节</h2><span class="hint">流水线状态 + 成本聚合</span></div>'
        '<div class="grid cols-2">'
        '<details class="details-fold card"><summary class="card-header">流水线状态</summary>'
        '<div class="card-body" id="overview-detail-status"></div></details>'
        '<details class="details-fold card"><summary class="card-header">成本估算</summary>'
        '<div class="card-body" id="overview-detail-cost"></div></details>'
        '</div>'
        '</section>'
    )


def _drama_overview_main(name: str, meta: dict) -> str:
    created_at = escape(str(meta.get("created_at") or "（未记录）"))
    schema_version = escape(str(meta.get("schema_version", 0)))
    return (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">作品 · 短剧</p>'
        f'<h1>{escape(name)}</h1>'
        '<p class="muted">drama 工作区。点击下方“进入续写”开始 4 站审查向导。</p>'
        '</div>'
        '<div class="cluster">'
        '<span class="badge no-dot" style="color:var(--amber-strong);background:var(--amber-soft);border-color:var(--amber-soft)">短剧</span>'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">删除作品…</button>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">4 站进度</h2>'
        '<span class="hint">core_setup / hook 已完成进入下一站</span></div>'
        '<div id="drama-overview-progress" class="grid cols-2"></div>'
        '</section>'
        '<section class="section">'
        '<div class="next-action" id="drama-overview-next-action">'
        '<p class="eyebrow ornament">下一步</p>'
        '<h2 id="drama-next-headline">载入中…</h2>'
        f'<a class="btn btn-primary" href="/w/{escape(name)}/write?step=setup">▸ 进入续写</a>'
        '</div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">workspace 元信息</h2></div>'
        '<div class="card"><div class="card-body">'
        '<div class="kv-list compact">'
        '<div class="k">type</div><div class="v"><code>drama</code></div>'
        f'<div class="k">created_at</div><div class="v"><code>{created_at}</code></div>'
        f'<div class="k">schema_version</div><div class="v"><code>{schema_version}</code></div>'
        '</div>'
        '</div></div>'
        '</section>'
    )


# ---------------------------------------------------------------------------
# Page: drama write wizard
# ---------------------------------------------------------------------------


def render_workspace_write(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">续写</p>'
        '<h1>4 站审查向导</h1>'
        '<p class="muted">核心设定 → 钩子 → 分镜 → 角色，每站 AI 生成 → 你改 → 下一站。</p>'
        '</div>'
        '<div id="drama-write-progress" class="cluster"></div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="setup">① 核心设定</button>'
        '<button class="tab" data-tab="hook">② 钩子</button>'
        '<button class="tab" data-tab="storyboard">③ 分镜</button>'
        '<button class="tab" data-tab="characters">④ 角色</button>'
        '</div>'
        '<div class="tab-panel active" id="tab-setup" data-station-pane="setup">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-hook" data-station-pane="hook">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-storyboard" data-station-pane="storyboard">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>分镜表尚未开放</h3>'
        '<p class="muted">本地 Beta 暂只支持核心设定与钩子站。</p>'
        '</div></div>'
        '<div class="tab-panel" id="tab-characters" data-station-pane="characters">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>角色设定表尚未开放</h3>'
        '<p class="muted">分镜与角色设定将在后续版本上线。</p>'
        '</div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 续写",
        page_kind="drama_write",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("续写", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="write"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: continue (cockpit)
# ---------------------------------------------------------------------------


def render_workspace_continue(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">续写</p>'
        '<h1>准备续写</h1>'
        '<p class="muted">三步走：设置起点 → 生成计划 → 继续写书。</p>'
        '</div>'
        '<div id="readiness-pill"></div>'
        '</header>'

        '<section class="continue-flow">'
        # step 1 — start point
        '<div class="flow-step">'
        '<div class="step-mark">1</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">续写起点</h3>'
        '<span class="muted">从原文哪一卷/章之后开始写</span></div>'
        '<div class="card-body">'
        '<form id="start-point-form" class="form-grid-2">'
        '<div class="field"><label>起点</label>'
        '<select name="start_point" id="start-point-select"><option>载入中…</option></select></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" class="btn btn-secondary">保存起点</button>'
        '</div>'
        '</form>'
        '<div id="start-point-status"></div>'
        '</div></div></div>'

        # step 2 — plan
        '<div class="flow-step">'
        '<div class="step-mark">2</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">章节计划</h3>'
        '<span class="muted">生成 / 覆盖未来 N 章的剧情大纲</span></div>'
        '<div class="card-body">'
        '<form id="plan-form" class="form-grid-2">'
        '<div class="field"><label>计划章节数</label>'
        '<input name="target_chapters" type="number" min="1" max="200" value="5"></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="plan-submit" class="btn btn-secondary">重生成并覆盖计划</button>'
        '</div>'
        '</form>'
        '<div id="plan-status"></div>'
        '</div></div></div>'

        # step 3 — write book
        '<div class="flow-step">'
        '<div class="step-mark">3</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">继续写书</h3>'
        '<span class="muted">严格运行 write-book，自动重写 + 评审</span></div>'
        '<div class="card-body">'
        '<form id="write-book-form" class="stack">'
        '<div class="field"><label>写作预设</label>'
        '<div class="filter-toggle" id="write-preset-toggle">'
        '<button type="button" class="btn" data-write-preset="trial">试写</button>'
        '<button type="button" class="btn active" data-write-preset="production">生产</button>'
        '<button type="button" class="btn" data-write-preset="strict">严格</button>'
        '</div></div>'
        '<div class="form-grid">'
        '<div class="field"><label>写几章</label><input name="chapters" type="number" min="1" value="1"></div>'
        '<div class="field"><label>从第几章</label><input name="resume_from" type="number" min="1" value="1"></div>'
        '<div class="field"><label>评审档位</label>'
        '<select name="tier">'
        '<option value="low">low · 快速试写，宽松通过（成本最低）</option>'
        '<option value="mid" selected>mid · 日常生产，平衡通过（默认）</option>'
        '<option value="high">high · 严格评审，发布门槛</option>'
        '</select></div>'
        '</div>'
        '<details class="details-fold">'
        '<summary>高级参数</summary>'
        '<div class="form-grid">'
        '<div class="field"><label>本次最多花费 CNY</label><input name="budget_cny" type="number" min="0" step="0.1" value="10" placeholder="0 = 不限制；mock 模式不消耗真实 token"></div>'
        '<div class="field"><label>每几章重规划</label><input name="replan_every" type="number" min="0" value="0"></div>'
        '<div class="field"><label>最大重试</label><input name="max_retries" type="number" min="0" value="2"></div>'
        '<div class="field"><label>推进置信度</label><input name="min_confidence" type="number" min="0" max="1" step="0.05" value="0.7"></div>'
        '</div>'
        '<label class="field-check"><input name="auto_advance" type="checkbox" checked> 自动推进实体状态</label>'
        '<small>当前 server 配置见 /preflight。</small>'
        '</details>'
        '<div class="form-actions" style="justify-content:space-between">'
        '<span></span>'
        '<button type="submit" id="write-book-submit" class="btn btn-primary">继续写书</button>'
        '</div>'
        '</form>'
        '<div id="write-book-status"></div>'
        '</div>'
        '<div class="card-footer">'
        '<a class="btn btn-ghost btn-sm" href="/w/' + escape(name) + '/jobs">查看任务历史 →</a>'
        '</div>'
        '</div></div>'
        '</section>'

        # sidebar: readiness + recent jobs
        '<section class="section">'
        '<div class="grid cols-2">'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">就绪检查</h3></div>'
        '<div class="card-body" id="readiness-panel"></div>'
        '</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">最近任务</h3></div>'
        '<div class="card-body" id="recent-jobs"></div>'
        '</div>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 续写",
        page_kind="continue",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("续写", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="continue"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: plan viewer
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Page: chapters list
# ---------------------------------------------------------------------------


def render_workspace_chapters(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">章节</p>'
        '<h1>章节</h1>'
        '<p class="muted">原文章次 + 已生成续写草稿。点击任意一行查看详情。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="chapters-filter">'
        '<input type="search" id="chapter-search" placeholder="按章节 ID 或标题搜索…">'
        '<div class="filter-toggle cluster">'
        '<button class="btn btn-ghost btn-sm active" data-mode="all">全部</button>'
        '<button class="btn btn-ghost btn-sm" data-mode="drafts">续写</button>'
        '<button class="btn btn-ghost btn-sm" data-mode="source">原文</button>'
        '</div>'
        '</div>'
        '<div class="card flush"><div class="card-body" id="chapters-table"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 章节",
        page_kind="chapters",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("章节", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="chapters"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: chapter detail
# ---------------------------------------------------------------------------


def render_workspace_chapter_detail(name: str, chapter_no: int, workspaces: Iterable[str]) -> str:
    chapter_id = f"chapter_{chapter_no:02d}"
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        f'<p class="eyebrow ornament">第 {chapter_no} 章</p>'
        f'<h1>{escape(chapter_id)}</h1>'
        '<div class="chapter-meta-bar" id="chapter-meta-bar"></div>'
        '</div>'
        '<div class="topbar-actions">'
        f'<a class="btn btn-ghost btn-sm" href="/w/{escape(name)}/chapters">← 返回章节列表</a>'
        '</div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="body">正文</button>'
        '<button class="tab" data-tab="review">评审</button>'
        '<button class="tab" data-tab="lint">Lint</button>'
        '<button class="tab" data-tab="advisor">Advisor</button>'
        '<button class="tab" data-tab="history">历史</button>'
        '</div>'
        '<div class="tab-panel active" id="tab-body">'
        '<div id="chapter-body" class="card"><div class="card-body">载入中…</div></div>'
        '</div>'
        '<div class="tab-panel" id="tab-review"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-lint"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-advisor"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-history"><p class="muted">载入中…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 第 {chapter_no} 章",
        page_kind="chapter_detail",
        main_html=main,
        breadcrumb_html=_crumbs([
            ("书架", "/"),
            (name, f"/w/{escape(name)}/"),
            ("章节", f"/w/{escape(name)}/chapters"),
            (f"第 {chapter_no} 章", None),
        ]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="chapters"),
        workspace=name,
        chapter_no=chapter_no,
    )


# ---------------------------------------------------------------------------
# Page: reviews aggregate
# ---------------------------------------------------------------------------


def render_workspace_reviews(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">评审</p>'
        '<h1>评审聚合</h1>'
        '<p class="muted">每章的 verdict、子分数、lint 与 advisor 改写建议汇总。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="card flush"><div class="card-body" id="reviews-panel"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 评审",
        page_kind="reviews",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("评审", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="reviews"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: insights
# ---------------------------------------------------------------------------


def render_workspace_insights(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">数据</p>'
        '<h1>Insights</h1>'
        '<p class="muted">每章成本 · 缓存命中率 · 评审子分数。全部从已落盘的 jsonl / meta 聚合，不发起新调用。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">每章成本</h2>'
        '<span class="hint">按 chapter_no 聚合 llm_calls.jsonl 的 cost_cny</span></div>'
        '<div class="card"><div class="card-body" id="insights-cost"></div></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">缓存命中率</h2>'
        '<span class="hint">cache_read / (cache_read + cache_write) by model</span></div>'
        '<div class="card"><div class="card-body" id="insights-cache"></div></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">评审子分数</h2>'
        '<span class="hint">每章平均；列 = plot / prose / fidelity / total</span></div>'
        '<div class="card"><div class="card-body" id="insights-subscores"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · Insights",
        page_kind="insights",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("数据", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="insights"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: jobs history + log tail
# ---------------------------------------------------------------------------


def render_workspace_jobs(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">任务</p>'
        '<h1>任务历史</h1>'
        '<p class="muted">最近 20 个 web 任务、trace_id（可复制）、以及 llm_calls 日志尾部。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="card flush"><div class="card-body" id="jobs-recent"></div></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">最近 LLM 调用</h2>'
        '<span class="hint">logs/llm_calls.jsonl 尾部 30 行</span></div>'
        '<div id="jobs-logs"></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 任务",
        page_kind="jobs",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), (name, f"/w/{escape(name)}/"), ("任务", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="jobs"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: wizard (onboarding upload)
# ---------------------------------------------------------------------------


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
        '<strong>短剧剧本</strong>　·　创建 drama workspace，进入 4 站审查向导'
        '</label>'
        '<div class="form-actions">'
        '<a class="btn btn-ghost" href="/">取消</a>'
        '<button type="submit" class="btn btn-primary" id="type-next">下一步</button>'
        '</div>'
        '</form>'
        '</div>'
        '</section>'

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
        '<div class="field">'
        '<label>题材描述（1-500 字）</label>'
        '<textarea name="topic" rows="3" maxlength="500" required '
        'placeholder="示例：复仇 → 救赎，单线发展，强冲突"></textarea>'
        '</div>'
        '<div class="field">'
        '<label>赛道</label>'
        '<div class="cluster">'
        '<label class="field-check"><input type="radio" name="track" value="霸总" required> 霸总</label>'
        '<label class="field-check"><input type="radio" name="track" value="重生"> 重生</label>'
        '<label class="field-check"><input type="radio" name="track" value="推理"> 推理</label>'
        '<label class="field-check"><input type="radio" name="track" value="系统"> 系统</label>'
        '<label class="field-check"><input type="radio" name="track" value="觉醒"> 觉醒</label>'
        '</div>'
        '</div>'
        '<div class="form-grid-2">'
        '<div class="field">'
        '<label>集数（1-100）</label>'
        '<input name="episode_count" type="number" min="1" max="100" value="12" required>'
        '</div>'
        '<div class="field">'
        '<label>单集时长（秒）</label>'
        '<div class="cluster">'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="30"> 30</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="60" checked> 60</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="90"> 90</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="120"> 120</label>'
        '</div>'
        '</div>'
        '</div>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-primary">创建并进入续写</button>'
        '</div>'
        '</form>'
        '<div id="drama-error"></div>'
        '</div>'
        '</section>'

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


# ---------------------------------------------------------------------------
# Page: settings
# ---------------------------------------------------------------------------


def render_settings() -> str:
    main = (
        '<div class="slim-shell">'
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">设置</p>'
        '<h1>模型与环境变量</h1>'
        '<p class="muted">.env 编辑器 · 保存后需重启 web 服务才生效。API key 默认掩码显示。</p>'
        '</div>'
        '</header>'
        '<section class="card">'
        '<div class="card-header"><h3 class="ornament">当前配置</h3></div>'
        '<div class="card-body">'
        '<div id="restart-banner" hidden></div>'
        '<form id="settings-form" class="stack"></form>'
        '<div id="settings-error"></div>'
        '</div>'
        '<div class="card-footer">'
        '<button type="submit" form="settings-form" class="btn btn-primary">保存</button>'
        '</div>'
        '</section>'
        '</div>'
    )
    return _render_shell(
        title="模型设置 · 写作工作台",
        page_kind="settings",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/"), ("设置", None)]),
        topbar_actions_html='<a class="btn btn-primary" href="/wizard">＋ 新建</a>',
        sidebar_html="",
        extra_scripts='<script src="/static/settings.js"></script>',
    )


# ---------------------------------------------------------------------------
# Legacy compatibility shim — older tests/external links still call
# ``templates.render_workspace(name)``. We keep that as an alias for the
# new "continue" page since that's where the original cockpit content
# lived (start-point form / plan form / write-book form). The dispatcher
# uses ``render_workspace_*`` directly.
# ---------------------------------------------------------------------------


def render_workspace(name: str, workspaces: Optional[Iterable[str]] = None) -> str:
    return render_workspace_continue(name, workspaces or [name])
