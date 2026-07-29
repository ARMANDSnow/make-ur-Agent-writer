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

import json
from html import escape
from string import Template
from typing import Iterable, List, Optional, Sequence

from .. import readiness_catalog
from ._naming import WORKSPACE_NAME_HTML_PATTERN
from .jobs import _default_budget_cny

# iter063 Part C: the readiness catalog is a build-time constant; serialize it
# once so the injected window.READINESS_CATALOG is identical on every page.
# Escape ``<`` to ``<`` so the data can never break out of the inline
# <script> (e.g. a future label containing "</script>") — structurally safe
# regardless of catalog edits, not relying on the data staying ``<``-free.
# json.loads round-trips ``<`` back to ``<``, so the catalog is unchanged.
_READINESS_CATALOG_JSON = json.dumps(readiness_catalog.KINDS, ensure_ascii=False).replace("<", "\\u003c")


def _format_budget(value: float) -> str:
    """Render 10.0 as "10" but keep real decimals (5.5 stays "5.5")."""
    return f"{value:g}"


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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23FBF7F0'/><text x='16' y='23' font-size='20' text-anchor='middle' fill='%233F6B5A'>&#10022;</text></svg>">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="app $APP_CLASS">
  $SIDEBAR
  <div class="sidebar-overlay" data-sidebar-close></div>
  <div class="main">
    <header class="topbar">
      <button type="button" class="btn btn-icon nav-toggle" data-sidebar-toggle aria-label="打开侧栏">☰</button>
      <a class="btn btn-icon home-btn" href="/" data-leave-guard aria-label="回首页" title="回首页">⌂</a>
      <nav class="breadcrumb">$BREADCRUMB</nav>
      <div class="topbar-actions-wrap">
        <button type="button" class="btn btn-icon topbar-menu-toggle" data-topbar-menu-toggle aria-label="打开页面操作">⋯</button>
        <div class="topbar-actions">$TOPBAR_ACTIONS</div>
      </div>
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
window.READINESS_CATALOG = $READINESS_CATALOG;
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
    # Phase A namespace: public/novel pages may evolve independently from the
    # production-heavy drama UI. Shared structural classes stay compatible;
    # visual overrides key off this explicit scope instead of page-specific
    # selectors. Workspace metadata is already the routing authority.
    ui_scope = "ui-public"
    if workspace:
        from .workspace_meta import read as _meta_read

        ui_scope = "ui-drama" if _meta_read(workspace).get("type", "novel") == "drama" else "ui-novel"
    if ui_scope == "ui-public":
        breadcrumb_html = breadcrumb_html.replace(
            'class="here"', 'class="here" aria-current="page"', 1
        )
    return _BASE_TPL.substitute(
        TITLE=escape(title),
        APP_CLASS=(
            f"no-context lp-chrome {ui_scope}"
            if page_kind == "landing"
            else ((ui_scope) if sidebar_html else f"no-context {ui_scope}")
        ),
        SIDEBAR=sidebar_html,
        BREADCRUMB=breadcrumb_html,
        TOPBAR_ACTIONS=topbar_actions_html,
        MAIN=main_html,
        PAGE_KIND=escape(page_kind),
        WORKSPACE=escape(workspace),
        CHAPTER_NO=str(chapter_no) if chapter_no is not None else "null",
        READINESS_CATALOG=_READINESS_CATALOG_JSON,
        EXTRA_SCRIPTS=extra_scripts,
    )


# ---------------------------------------------------------------------------
# Reused fragments
# ---------------------------------------------------------------------------


_WORKSPACE_SECTIONS: Sequence[tuple[str, str, str]] = (
    ("overview", "作品概览", ""),
    ("workbench", "创作工作台", "workbench"),
    ("continue", "批量续写", "continue"),
    ("plan", "故事规划", "plan"),
    ("chapters", "章节列表", "chapters"),
    ("search", "内容搜索", "search"),  # iter075: 跨章全文检索（章节的姊妹操作）
    ("reviews", "内容检查", "reviews"),
    ("insights", "创作数据", "insights"),
    ("jobs", "任务记录", "jobs"),
)

_SECTIONS_DRAMA: Sequence[tuple[str, str, str]] = (
    ("overview", "概览", ""),
    ("write", "创作台", "write"),
    ("production", "生产工作台", "production"),
    ("characters", "角色库", "characters"),
    ("assets", "资产治理", "assets"),
    ("shot_images", "镜头图片", "shot-images"),
    ("shot_videos", "镜头视频", "shot-videos"),
    ("compose", "合成交付", "compose"),
    ("episodes", "剧集", "episodes"),
    ("insights", "数据", "insights"),
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
        # iter072 (#1): switching to *another* workspace leaves the current
        # one, so a non-active item must carry data-leave-guard like the
        # ⌂/brand/topbar exits — otherwise a running job is silently abandoned
        # (no three-choice modal). The active item just re-opens the current
        # workspace overview (same context) and stays unguarded; the per-
        # workspace section links below are likewise in-workspace navigation.
        guard = "" if is_active else " data-leave-guard"
        items.append(
            f'<a class="{cls}" href="/w/{escape(name)}/"{guard}>'
            f'<span><span class="dot"></span> {escape(name)}</span>'
            f'</a>'
        )
    work_html = "\n".join(items) if items else '<p class="muted" style="padding:0 8px">尚无作品</p>'
    sections_html = ""
    responsive_nav_html = ""
    if active_workspace:
        from .workspace_meta import read as _meta_read

        ws_type = _meta_read(active_workspace).get("type", "novel")
        section_items = []
        responsive_items = []
        for key, label, suffix in _sections_for(ws_type):
            href = f"/w/{escape(active_workspace)}/{suffix}" if suffix else f"/w/{escape(active_workspace)}/"
            if key == active_section:
                section_items.append(
                    '<span class="sidebar-item active" aria-current="page">'
                    f'<span><span class="dot"></span> {escape(label)}</span>'
                    '</span>'
                )
                responsive_items.append(
                    '<span class="drama-responsive-nav-item active" aria-current="page" '
                    f'data-drama-nav-item="{escape(key)}">{escape(label)}</span>'
                )
            else:
                section_items.append(
                    f'<a class="sidebar-item" href="{href}" data-leave-guard>'
                    f'<span><span class="dot"></span> {escape(label)}</span>'
                    f'</a>'
                )
                responsive_items.append(
                    f'<a class="drama-responsive-nav-item" href="{href}" data-leave-guard '
                    f'data-drama-nav-item="{escape(key)}">{escape(label)}</a>'
                )
        sections_html = (
            '<div class="sidebar-section">'
            f'<h4>《{escape(active_workspace)}》</h4>'
            + "\n".join(section_items)
            + "</div>"
        )
        if ws_type == "drama":
            # The tablet rail and desktop sidebar are generated from the same
            # canonical 11-item section tuple. Mobile keeps the four primary
            # destinations visible; "更多" opens the existing full sidebar, so
            # workspace switching and every route remain one guarded action away.
            primary_keys = {"overview", "write", "production", "jobs"}
            mobile_items = [
                item for key, item in zip(
                    (row[0] for row in _SECTIONS_DRAMA), responsive_items
                ) if key in primary_keys
            ]
            responsive_nav_html = (
                '<nav class="drama-tablet-nav" aria-label="短剧主导航">'
                '<a class="drama-nav-brand" href="/library" data-leave-guard aria-label="返回书架">✦</a>'
                '<div class="drama-tablet-nav-scroll">' + "".join(responsive_items) + '</div>'
                '<button type="button" class="btn btn-icon" data-sidebar-toggle aria-label="切换作品">作品</button>'
                '</nav>'
                '<nav class="drama-mobile-nav" aria-label="短剧主导航">'
                + "".join(mobile_items) +
                '<button type="button" class="drama-responsive-nav-item" data-sidebar-toggle '
                'aria-label="打开全部导航">更多</button></nav>'
            )
    return (
        responsive_nav_html +
        '<aside class="sidebar">'
        '<a class="brand" href="/library" data-leave-guard><span>✦</span> 续写工作台</a>'
        '<div class="sidebar-section sidebar-library">'
        f'<h4>书架 <span>{len(items)}</span></h4>'
        f'<div class="sidebar-library-list">{work_html}</div>'
        '</div>'
        f'{sections_html}'
        '<div class="sidebar-footer">'
        '<span>仅在本机运行 · 单用户</span>'
        '<span>离线模式可用</span>'
        '</div>'
        '</aside>'
    )


def _topbar_actions(extra: str = "", *, current: str = "") -> str:
    # iter071 (codex F1): 回收站/设置/新建 also LEAVE the current workspace, so
    # they must carry data-leave-guard like ⌂/brand/first-crumb — otherwise a
    # running job is silently abandoned (no three-choice modal) when the user
    # exits via these three. On non-workspace pages WORKSPACE_NAME is "" and the
    # delegate short-circuits (static.py ~2128), so the attribute is a no-op
    # there. `extra` (page-local actions that stay in-workspace) is untouched.
    items = []
    if current != "trash":
        items.append('<a class="btn btn-ghost" href="/trash" data-leave-guard>♻ 回收站</a>')
    if current != "settings":
        items.append('<a class="btn btn-ghost" href="/settings" data-leave-guard>⚙ 设置</a>')
    if current != "wizard":
        items.append('<a class="btn btn-primary" href="/wizard" data-leave-guard>＋ 新建</a>')
    base = "".join(items)
    return extra + base


def render_workspace_novel_only_empty(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<section class="section">'
        '<div class="empty-state">'
        '<span class="ornament">✦</span>'
        '<h3>此页面属于小说模块</h3>'
        '<p class="muted">当前作品是短剧。该功能不适用于短剧模块。</p>'
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
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("小说模块", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section=""),
        workspace=name,
    )


def render_workspace_type_unknown(name: str, workspaces: Iterable[str]) -> str:
    """Fail-closed page for present but unreadable workspace metadata."""
    main = (
        '<section class="section"><div class="empty-state">'
        '<span class="ornament">✦</span><h3>作品类型待确认</h3>'
        '<p class="muted">暂时无法确认这部作品属于小说还是短剧，因此没有打开创作页面。作品内容没有被修改。</p>'
        '<div class="cta cluster"><a class="btn btn-secondary" href="/library">返回作品列表</a>'
        '<button type="button" class="btn btn-ghost" data-cta-action="reload">重新读取</button></div>'
        '</div></section>'
    )
    return _render_shell(
        title=f"{name} · 状态待确认",
        page_kind="workspace_empty",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html="",
        workspace="",
    )


def _crumbs(parts: Sequence[tuple[str, Optional[str]]]) -> str:
    """Render breadcrumbs. Each part is (label, href or None for current)."""
    pieces = []
    for i, (label, href) in enumerate(parts):
        if i:
            pieces.append('<span class="sep">/</span>')
        if href is None:
            pieces.append(f'<span class="here">{escape(label)}</span>')
        elif i == 0:
            # iter070: the first crumb ("书架"→/library) is an in-app "leave this
            # workspace" exit; mark it so the leave-guard delegate can intercept
            # it while a job runs. Later crumbs stay within the workspace.
            pieces.append(f'<a href="{href}" data-leave-guard>{escape(label)}</a>')
        else:
            pieces.append(f'<a href="{href}">{escape(label)}</a>')
    return "".join(pieces)


# ---------------------------------------------------------------------------
# Page: shelf (index)
# ---------------------------------------------------------------------------


def render_index(workspaces: Iterable[str]) -> str:
    names: List[str] = list(workspaces)
    empty_hint = "" if names else "还没有作品。可以创建小说作品，也可以创建短剧作品。"
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">我的作品</p>'
        '<h1>作品列表</h1>'
        '<p class="muted">查看小说与短剧的最近进度，从上次停下的位置继续。</p>'
        '</div>'
        '<div class="shelf-stats" id="shelf-stats"></div>'
        '</header>'
        '<section class="public-toolbar" aria-label="作品筛选与创建">'
        '<div class="field public-search">'
        '<label for="library-search">查找作品</label>'
        '<input id="library-search" type="search" placeholder="输入作品名称" autocomplete="off" '
        'aria-describedby="library-search-help">'
        '<small id="library-search-help">只筛选当前已加载的作品，不会修改作品内容。</small>'
        '</div>'
        '<div class="cluster public-toolbar-actions">'
        '<a class="btn btn-primary" href="/wizard?type=novel">创建小说作品</a>'
        '<a class="btn btn-secondary" href="/wizard?type=drama">创建短剧作品</a>'
        '</div>'
        '</section>'
        '<section class="section">'
        '<div id="library-status" class="sr-status" role="status" aria-live="polite"></div>'
        f'<div id="workspace-shelf" class="workspace-list" data-empty="{escape(empty_hint)}">'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title="作品列表 · 续写工作台",
        page_kind="index",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html="",
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
        '<p class="muted">这里的内容尚未永久删除。你可以恢复作品，或在确认名称后永久删除。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="public-notice" role="note"><strong>操作范围</strong>'
        '<span>恢复或永久删除只影响你选择的这一部作品，其他作品不会改变。</span></div>'
        '<div id="trash-list" class="trash-list" aria-live="polite"></div>'
        '</section>'
    )
    return _render_shell(
        title="回收站 · 写作工作台",
        page_kind="trash",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), ("回收站", None)]),
        topbar_actions_html=_topbar_actions(current="trash"),
        sidebar_html="",
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
        breadcrumb_html=_crumbs([("书架", "/library"), (name, None)]),
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
        '<p class="muted">先确认当前作品能否继续，再从上次保存的位置开始。</p>'
        '</div>'
        '<div id="overview-status-badge"></div>'
        '<div class="topbar-actions">'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">'
        '删除作品…'
        '</button>'
        '</div>'
        '</header>'
        '<section class="overview-hero phase-d-overview">'
        '<div class="next-action" id="overview-next-action"></div>'
        '<div class="metric-pair" id="overview-summary"></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">待处理问题</h2><span class="hint">不会自动覆盖已保存内容</span></div>'
        '<div id="overview-blockers"></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">最近保存的章节</h2><a class="btn btn-ghost btn-sm" href="/w/' + escape(name) + '/chapters">查看全部章节</a></div>'
        '<div id="overview-recent-chapter"></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">最近保存与准备情况</h2><span class="hint">状态来自已保存记录</span></div>'
        '<div class="grid cols-2">'
        '<details class="details-fold card"><summary class="card-header">准备情况</summary>'
        '<div class="card-body" id="overview-detail-status"></div></details>'
        '<details class="details-fold card"><summary class="card-header">内容概况</summary>'
        '<div class="card-body" id="overview-detail-cost"></div></details>'
        '</div>'
        '</section>'
    )


def _drama_overview_main(name: str, meta: dict) -> str:
    return (
        '<header class="page-header drama-page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">作品 · 短剧</p>'
        f'<h1>{escape(name)}</h1>'
        '<p class="muted">从创作到交付，按已保存状态继续当前一集。</p>'
        '</div>'
        '<div class="cluster">'
        '<span class="badge no-dot badge-drama">短剧</span>'
        '<button type="button" class="btn btn-danger btn-sm" id="delete-workspace-btn">删除作品…</button>'
        '</div>'
        '</header>'
        '<section id="drama-overview-summary" class="drama-overview-summary" aria-live="polite">'
        '<div class="drama-summary-card skeleton-block"></div><div class="drama-summary-card skeleton-block"></div>'
        '<div class="drama-summary-card skeleton-block"></div><div class="drama-summary-card skeleton-block"></div>'
        '</section>'
        '<div class="drama-overview-layout">'
        '<section class="section drama-overview-stages">'
        '<div class="section-title"><div><p class="eyebrow ornament">进度</p><h2>创作与生产阶段</h2></div>'
        '<span class="hint">状态来自已保存的安全投影</span></div>'
        '<div id="drama-overview-progress" class="drama-stage-list"></div>'
        '</section>'
        '<aside class="drama-overview-aside">'
        '<section class="next-action" id="drama-overview-next-action">'
        '<p class="eyebrow ornament">下一步</p><h2 id="drama-next-headline">正在读取进度</h2>'
        '<p class="muted" id="drama-next-reason">将根据当前状态给出恢复入口。</p>'
        f'<div class="cluster" id="drama-next-actions"><a class="btn btn-primary" href="/w/{escape(name)}/write?step=setup">进入创作台</a></div>'
        '</section>'
        '<section class="card drama-recent-task"><div class="card-body" id="drama-overview-recent-task">'
        '<p class="eyebrow ornament">最近任务</p><p class="muted">正在读取状态…</p></div></section>'
        '</aside></div>'
    )


# ---------------------------------------------------------------------------
# Page: drama write wizard
# ---------------------------------------------------------------------------


def render_workspace_write(name: str, workspaces: Iterable[str], episode_no: int = 1) -> str:
    main = (
        '<header class="page-header drama-page-header drama-write-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · 五站创作</p>'
        f'<h1>第 {episode_no} 集 · 短剧创作台</h1>'
        '<p class="muted">故事设定 → 钩子设计 → 分镜脚本 → 角色设计 → 评审与组装；保存后再进入下游。</p>'
        '</div>'
        '<div class="drama-write-tools">'
        f'<label class="field compact" for="drama-write-episode">当前集 <input id="drama-write-episode" type="number" min="1" max="100" value="{episode_no}" inputmode="numeric"></label>'
        '<button class="btn btn-secondary" id="drama-write-refresh" type="button">刷新状态</button>'
        '</div>'
        '</header>'
        '<section id="drama-write-status" class="drama-write-status" data-ui-state="loading" aria-live="polite">'
        '<strong>正在读取五站进度</strong><span>已保存内容不会被修改。</span></section>'
        '<section class="tabs drama-station-workbench">'
        '<div class="tab-list drama-station-nav" aria-label="五站创作步骤">'
        '<button class="tab active" data-tab="setup" aria-current="step"><span>01</span>故事设定</button>'
        '<button class="tab" data-tab="hook"><span>02</span>钩子设计</button>'
        '<button class="tab" data-tab="storyboard"><span>03</span>分镜脚本</button>'
        '<button class="tab" data-tab="characters"><span>04</span>角色设计</button>'
        '<button class="tab" data-tab="review"><span>05</span>评审与组装</button>'
        '</div>'
        '<div id="drama-write-progress" class="drama-station-summary" aria-live="polite"></div>'
        '<div class="tab-panel active" id="tab-setup" data-station-pane="setup">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-hook" data-station-pane="hook">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-storyboard" data-station-pane="storyboard">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-characters" data-station-pane="characters">'
        '<p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-review" data-station-pane="review">'
        '<p class="muted">载入中…</p></div>'
        '</section>'
        '<div class="drama-mobile-primary" aria-label="当前步骤主操作">'
        '<span id="drama-mobile-step-label">第 1 站 · 故事设定</span>'
        '<button type="button" class="btn btn-primary" id="drama-mobile-primary-action">执行当前主操作</button>'
        '</div>'
    )
    return _render_shell(
        title=f"{name} · 短剧创作",
        page_kind="drama_write",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), (f"第 {episode_no} 集", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="write"),
        workspace=name,
        chapter_no=episode_no,
    )


def render_workspace_characters(name: str, workspaces: Iterable[str], episode_no: int = 1) -> str:
    main = (
        '<header class="page-header drama-page-header drama-characters-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · 角色资产</p>'
        '<h1>第 1 季 · 角色库</h1>'
        '<p class="muted">先处理当前集角色，再维护季级设定；锁定与真实参考图不会被普通重生成静默替换。</p>'
        '</div>'
        '<div class="cluster drama-character-tools">'
        f'<label class="field compact" for="characters-episode-no">当前集 <input id="characters-episode-no" type="number" min="1" max="100" value="{episode_no}" inputmode="numeric"></label>'
        f'<a class="btn btn-secondary" data-leave-guard href="/w/{escape(name)}/write?episode={episode_no}&step=characters#characters">回到角色设计</a>'
        '</div>'
        '</header>'
        '<section class="callout info drama-character-boundary"><strong>生成边界</strong>'
        '<span>本地预览可安全重画；真实绘图仍需逐次授权。已存在的付费参考图与生成凭据受服务端保护。</span></section>'
        '<section id="characters-page-root" data-ui-state="loading" aria-live="polite">'
        '<div class="character-loading"><p class="muted">正在读取当前集与季角色库…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 角色库",
        page_kind="drama_characters",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("角色库", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="characters"),
        workspace=name,
        chapter_no=episode_no,
    )


def render_workspace_production(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header drama-page-header production-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · I 阶段</p>'
        '<h1>生产工作台</h1>'
        '<p class="muted">在一处查看创作版本、资产选择、逐镜素材、任务进度、时间线、质检与交付。</p>'
        '</div>'
        '<div class="cluster">'
        '<label class="field compact">集数 '
        '<input id="production-episode-no" type="number" min="1" max="100" value="1" inputmode="numeric">'
        '</label>'
        '<button class="btn btn-secondary" id="production-refresh" type="button">刷新</button>'
        '</div>'
        '</header>'
        '<section class="section production-workbench-section">'
        '<div class="callout info">'
        '<strong>安全的状态总览</strong>'
        '<span>镜头列表与关系画布只读取服务端已保存状态，不会调用付费服务，也不会修改素材选择或任务状态；“本地 A-F 演练”会新建隔离验收项目，不改写当前项目。</span>'
        '</div>'
        '<div class="tabs production-view-tabs" role="tablist" aria-label="生产工作台视图">'
        '<button class="tab active" type="button" role="tab" id="production-tab-list" '
        'data-production-view="list" aria-controls="production-panel-list" aria-selected="true" tabindex="0">镜头列表</button>'
        '<button class="tab" type="button" role="tab" id="production-tab-canvas" '
        'data-production-view="canvas" aria-controls="production-panel-canvas" aria-selected="false" tabindex="-1">关系画布</button>'
        '</div>'
        '<div id="production-page-root" aria-live="polite"><p class="muted">载入中…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 生产工作台",
        page_kind="drama_production",
        main_html=main,
        breadcrumb_html=_crumbs(
            [("书架", "/library"), (name, f"/w/{escape(name)}/"), ("生产工作台", None)]
        ),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(
            workspaces,
            active_workspace=name,
            active_section="production",
        ),
        workspace=name,
    )


def render_workspace_assets(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · B 阶段</p>'
        '<h1>资产治理</h1>'
        '<p class="muted">统一查看角色、美术方向、场景与道具/线索的版本、引用、停用状态和影响集。</p>'
        '</div>'
        '<div class="cluster">'
        '<label class="field compact">集数 '
        '<input id="asset-episode-no" type="number" min="1" max="100" value="1" inputmode="numeric">'
        '</label>'
        '<button class="btn btn-secondary" id="asset-refresh" type="button">刷新</button>'
        '</div>'
        '</header>'
        '<section class="section drama-governance-page">'
        '<div class="callout info">'
        '<strong>非破坏式治理</strong>'
        '<span>停用不会删除文件；切换版本不会改写已冻结分镜。影响集由服务端按当前引用重新计算。</span>'
        '</div>'
        '<div id="assets-page-root" class="asset-governance-root" aria-live="polite">'
        '<p class="muted">载入中…</p>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 资产治理",
        page_kind="drama_assets",
        main_html=main,
        breadcrumb_html=_crumbs(
            [("书架", "/library"), (name, f"/w/{escape(name)}/"), ("资产治理", None)]
        ),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(
            workspaces,
            active_workspace=name,
            active_section="assets",
        ),
        workspace=name,
    )


def render_workspace_shot_images(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · C 阶段</p>'
        '<h1>镜头图片候选</h1>'
        '<p class="muted">按镜头比较安全图片预览，并在当前版本上选择首帧或尾帧。</p>'
        '</div>'
        '<div class="cluster drama-media-header-actions">'
        '<label class="field compact">集数 '
        '<input id="shot-image-episode-no" type="number" min="1" max="100" value="1" inputmode="numeric">'
        '</label>'
        '<button class="btn btn-secondary" id="shot-image-needs-toggle" type="button" aria-pressed="false">只看需处理</button>'
        '<button class="btn btn-secondary" id="shot-image-refresh" type="button">刷新</button>'
        '</div>'
        '</header>'
        '<section class="section drama-media-page">'
        '<div class="callout info">'
        '<strong>候选不会自动替换选择</strong>'
        '<span>页面只读取已登记且通过校验的图片；比较和选择不会发起图片生成或付费调用。</span>'
        '</div>'
        '<div id="shot-image-compare" class="shot-image-compare" aria-live="polite"></div>'
        '<div id="shot-images-page-root" class="drama-media-root" aria-live="polite">'
        '<p class="muted">载入中…</p>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 镜头图片候选",
        page_kind="drama_shot_images",
        main_html=main,
        breadcrumb_html=_crumbs(
            [("书架", "/library"), (name, f"/w/{escape(name)}/"), ("镜头图片", None)]
        ),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(
            workspaces,
            active_workspace=name,
            active_section="shot_images",
        ),
        workspace=name,
    )


def render_workspace_shot_videos(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · D 阶段</p>'
        '<h1>镜头视频候选</h1>'
        '<p class="muted">播放已登记的安全候选，显式选择，并查看生成记录、整集覆盖与连续性。</p>'
        '</div>'
        '<div class="cluster drama-media-header-actions">'
        '<label class="field compact">集数 '
        '<input id="shot-video-episode-no" type="number" min="1" max="100" value="1" inputmode="numeric">'
        '</label>'
        '<button class="btn btn-secondary" id="shot-video-needs-toggle" type="button" aria-pressed="false">只看需处理</button>'
        '<button class="btn btn-secondary" id="shot-video-refresh" type="button">刷新</button>'
        '</div>'
        '</header>'
        '<section class="section drama-media-page">'
        '<div class="callout info">'
        '<strong>此页不会提交视频任务</strong>'
        '<span>只读取本地安全投影；播放和选择不会提交、轮询、下载上游结果或产生付费调用。</span>'
        '</div>'
        '<div id="shot-videos-page-root" class="drama-media-root" aria-live="polite">'
        '<p class="muted">载入中…</p>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 镜头视频候选",
        page_kind="drama_shot_videos",
        main_html=main,
        breadcrumb_html=_crumbs(
            [("书架", "/library"), (name, f"/w/{escape(name)}/"), ("镜头视频", None)]
        ),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(
            workspaces,
            active_workspace=name,
            active_section="shot_videos",
        ),
        workspace=name,
    )


def render_workspace_compose(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧 · F 阶段</p>'
        '<h1>本地合成与交付</h1>'
        '<p class="muted">从已验证的 E3 时间线生成竖屏 MP4、SRT、ASS 与通用剪辑工程。</p>'
        '</div>'
        '<div class="cluster">'
        '<label class="field compact">集数 '
        '<input id="compose-episode-no" type="number" min="1" max="100" value="1" inputmode="numeric">'
        '</label>'
        '<button class="btn btn-secondary" id="compose-refresh" type="button">刷新</button>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="callout info">'
        '<strong>合成只在本机执行</strong>'
        '<span>此页不会调用文本、图片、视频或 TTS provider；下载只开放当前时间线经 QA 验证的 exact 产物。</span>'
        '</div>'
        '<div id="compose-page-root" aria-live="polite">'
        '<p class="muted">载入中…</p>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 本地合成与交付",
        page_kind="drama_compose",
        main_html=main,
        breadcrumb_html=_crumbs(
            [("书架", "/library"), (name, f"/w/{escape(name)}/"), ("合成交付", None)]
        ),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(
            workspaces,
            active_workspace=name,
            active_section="compose",
        ),
        workspace=name,
    )


def render_workspace_episodes(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧</p>'
        '<h1>剧集</h1>'
        '<p class="muted">继续连续创作，并从已组装 JSON 真源导出单集或整季交付包。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div id="episodes-panel"><p class="muted">载入中…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 剧集",
        page_kind="drama_episodes",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("剧集", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="episodes"),
        workspace=name,
    )


def render_workspace_episode_detail(name: str, workspaces: Iterable[str], episode_no: int) -> str:
    video_tab = '<button class="tab" data-tab="video">视频</button>' if episode_no == 1 else ''
    video_panel = '<div class="tab-panel" id="tab-video"><p class="muted">载入中…</p></div>' if episode_no == 1 else ''
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧</p>'
        f'<h1>第 {episode_no} 集</h1>'
        '<p class="muted">剧本、分镜、角色与评审记录。</p>'
        '</div>'
        '<div class="cluster">'
        f'<a class="btn btn-primary" href="/w/{escape(name)}/write?episode={episode_no}">编辑本集</a>'
        f'<a class="btn btn-secondary" href="/w/{escape(name)}/episodes">返回剧集</a>'
        '</div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="script">剧本</button>'
        '<button class="tab" data-tab="storyboard-view">分镜</button>'
        '<button class="tab" data-tab="characters-view">角色</button>'
        '<button class="tab" data-tab="review">评审</button>'
        '<button class="tab" data-tab="export">导出</button>'
        + video_tab +
        '</div>'
        '<div class="tab-panel active" id="tab-script"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-storyboard-view"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-characters-view"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-review"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-export"><p class="muted">载入中…</p></div>'
        + video_panel +
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 第 {episode_no} 集",
        page_kind="drama_episode_detail",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("剧集", f"/w/{escape(name)}/episodes"), (f"第 {episode_no} 集", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="episodes"),
        workspace=name,
        chapter_no=episode_no,
    )


def render_workspace_drama_insights(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">短剧</p>'
        '<h1>数据 Insights</h1>'
        '<p class="muted">查看短剧调用成本、媒体任务分币种事实、单集时长达标率与钩子类型分布。</p>'
        '</div>'
        '<div class="cluster">'
        f'<a class="btn btn-secondary" href="/w/{escape(name)}/episodes">返回剧集</a>'
        '</div>'
        '</header>'
        '<section class="section stack">'
        '<div class="card"><div class="card-header"><h3>成本口径</h3></div><div class="card-body" id="drama-insights-cost"></div></div>'
        '<div class="card"><div class="card-header"><h3>媒体任务</h3></div><div class="card-body" id="drama-insights-media-metrics"></div></div>'
        '<div class="card"><div class="card-header"><h3>时长达标率</h3></div><div class="card-body" id="drama-insights-duration"></div></div>'
        '<div class="card"><div class="card-header"><h3>钩子类型</h3></div><div class="card-body" id="drama-insights-hooks"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 短剧数据",
        page_kind="drama_insights",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("数据", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="insights"),
        workspace=name,
    )
# ---------------------------------------------------------------------------
# Page: continue (cockpit)
# ---------------------------------------------------------------------------


def render_workspace_continue(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">高级创作</p>'
        '<h1>批量续写</h1>'
        '<p class="muted">适合已有起点和章节计划的作品。首次创作请先使用单章创作工作台。</p>'
        '</div>'
        '<div class="cluster"><span class="badge no-dot">高级入口</span><div id="readiness-pill"></div></div>'
        '</header>'

        '<div class="alert info advanced-entry-note" role="note">批量续写会按同一组设置连续处理多章；开始前将重新检查起点、章节计划与本次可用额度。</div>'

        '<section class="continue-flow">'
        # step 1 — start point
        '<div class="flow-step">'
        '<div class="step-mark">1</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">确认续写起点</h3>'
        '<span class="muted">从哪一章之后承接故事</span></div>'
        '<div class="card-body">'
        '<form id="start-point-form" class="form-grid-2">'
        '<div class="field"><label for="start-point-select">起点</label>'
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
        '<div class="card-header"><h3 class="ornament">维护章节计划</h3>'
        '<span class="muted">仅在现有计划不再适用时重新生成</span></div>'
        '<div class="card-body">'
        '<form id="plan-form" class="form-grid-2">'
        '<div class="field"><label for="plan-target-chapters">计划章节数</label>'
        '<input id="plan-target-chapters" name="target_chapters" type="number" min="1" max="200" value="5"></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="plan-submit" class="btn btn-paid" data-ui-action="paid">重新生成并覆盖计划</button>'
        '</div>'
        '</form>'
        '<div id="plan-status"></div>'
        '</div></div></div>'

        # step 3 — write book
        '<div class="flow-step">'
        '<div class="step-mark">3</div>'
        '<div class="card">'
        '<div class="card-header"><h3 class="ornament">设置批量续写</h3>'
        '<span class="muted">确认章节范围、写作方式与检查严格程度</span></div>'
        '<div class="card-body">'
        '<form id="write-book-form" class="stack">'
        '<div class="field"><span class="field-label">写作方式</span>'
        '<div class="filter-toggle" id="write-preset-toggle" role="group" aria-label="选择写作方式">'
        '<button type="button" class="btn" data-write-preset="trial" aria-pressed="false">试写</button>'
        '<button type="button" class="btn active" data-write-preset="production" aria-pressed="true">生产</button>'
        '<button type="button" class="btn" data-write-preset="strict" aria-pressed="false">严格</button>'
        '</div></div>'
        '<div class="form-grid">'
        '<div class="field"><label for="continue-chapters">续写章节数</label><input id="continue-chapters" name="chapters" type="number" min="1" value="1" aria-describedby="continue-chapters-help"><small id="continue-chapters-help">本次连续处理的章节数量。</small></div>'
        '<div class="field"><label for="continue-resume">续写起始章</label><input id="continue-resume" name="resume_from" type="number" min="1" value="1"></div>'
        '<div class="field"><label for="continue-tier">检查严格程度</label>'
        '<select id="continue-tier" name="tier">'
        '<option value="low">快速 · 宽松通过（使用额度较少）</option>'
        '<option value="mid" selected>标准 · 平衡通过（默认）</option>'
        '<option value="high">严格 · 发布门槛</option>'
        '</select></div>'
        '</div>'
        '<details class="details-fold">'
        '<summary>高级参数</summary>'
        '<div class="form-grid">'
        '<div class="field"><label for="continue-budget">本次可用额度（人民币）</label><input id="continue-budget" name="budget_cny" type="number" min="0" step="0.1" value="10" aria-describedby="continue-budget-help"><small id="continue-budget-help">额度不足时可在此调整；不会锁住其他设置。</small></div>'
        '<div class="field"><label for="continue-timeout">最长等待时间（分钟）</label><input id="continue-timeout" name="timeout_minutes" type="number" min="0" max="1440" value="30" aria-describedby="continue-timeout-help"><small id="continue-timeout-help">到时后停止继续等待，已经保存的内容仍会保留。</small></div>'
        '<div class="field"><label for="continue-replan">每几章重规划</label><input id="continue-replan" name="replan_every" type="number" min="0" value="0"></div>'
        '<div class="field"><label for="continue-retries">最大重试</label><input id="continue-retries" name="max_retries" type="number" min="0" value="2"></div>'
        '<div class="field"><label for="continue-confidence">推进置信度</label><input id="continue-confidence" name="min_confidence" type="number" min="0" max="1" step="0.05" value="0.7"></div>'
        '</div>'
        '<label class="field-check"><input name="auto_advance" type="checkbox" checked> 自动推进实体状态</label>'
        '<small>开始前会自动检查当前运行方式与可用额度。</small>'
        '</details>'
        '<div class="form-actions" style="justify-content:space-between">'
        '<span></span>'
        '<button type="submit" id="write-book-submit" class="btn btn-paid" data-ui-action="paid">检查并继续</button>'
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
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("续写", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="continue"),
        workspace=name,
    )


def render_workspace_workbench(name: str, workspaces: Iterable[str]) -> str:
    """iter 048b: the小白 four-stage workbench. One card per stage
    (设定→大纲→细纲→正文); each fires its step job via pollJob and the
    front-end gates the next card on the previous stage's artifacts. Stage ②
    embeds an editable outline textarea (PUT /outline). Reuses the continue
    page's flow-step / card / status-box structure verbatim."""
    esc = escape(name)
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">工作台</p>'
        '<h1>单章创作工作台</h1>'
        '<p class="muted">按准备设定、生成大纲、生成细纲、撰写正文四个阶段继续；已保存结果不会被自动覆盖。</p>'
        '</div>'
        '<div id="workbench-stage-pill"></div>'
        '</header>'

        # iter062: clickable step rail — jump back to any done/current stage;
        # locked stages are non-interactive. Filled by refreshWorkbench().
        '<div class="workbench-running-note" role="note">任务开始后可以离开此页，处理仍会继续；随时从“任务记录”返回查看。</div>'
        '<ol class="stepbar" id="workbench-stepbar" aria-label="四阶段进度"></ol>'

        '<section class="continue-flow">'
        # stage ① 设定 (prepare-greenfield)
        '<div class="flow-step">'
        '<div class="step-mark">1</div>'
        '<div class="card workbench-stage-card" id="stage-prepare-card">'
        '<div class="card-header"><h3 class="ornament">准备设定</h3>'
        # iter068 (Cluster A): id hooks so refreshWorkbench() can rewrite the
        # copy for an existing-book continuation (重建续写底座) vs greenfield.
        '<span class="muted" id="prepare-subtitle">从开书的一句话立意提取知识库与实体设定</span></div>'
        '<div class="card-body">'
        '<form id="prepare-form" class="form-grid-2">'
        '<div class="field"><label>立意</label>'
        '<div class="muted" id="prepare-hint">开书时填写的立意已保存；点右侧生成作品知识与角色设定。</div></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="prepare-submit" class="btn btn-paid" data-ui-action="paid">生成设定</button>'
        '</div>'
        '</form>'
        '<div id="prepare-status"></div>'
        # iter 051a: expansion-stale hint (KB older than the edited expansion)
        '<div id="expansion-stale-hint"></div>'
        # iter 050 (B3): on-demand KB / entity_graph editor
        '<div class="form-actions" style="margin-top:12px">'
        '<button type="button" id="settings-toggle" class="btn btn-ghost btn-sm">查看 / 编辑设定 ▾</button>'
        '</div>'
        '<div id="settings-panel" hidden>'
        # iter 051a: structured premise expansion editor (data/premise_expansion.json)
        '<div class="field"><label>立意扩写稿（开书立意的结构化扩写，可编辑）</label>'
        '<div id="expansion-empty" class="muted" hidden>尚未生成扩写稿；可点「重新扩写」生成，或直接填写后保存。</div></div>'
        '<div class="field"><label for="exp-genre-tone">题材基调</label>'
        '<input type="text" id="exp-genre-tone" maxlength="300"></div>'
        '<div class="field"><label for="exp-protagonist">主角卡</label>'
        '<textarea id="exp-protagonist" rows="3" maxlength="2000"></textarea></div>'
        '<div class="field"><label for="exp-world-notes">世界观要点（每行一条）</label>'
        '<textarea id="exp-world-notes" rows="3"></textarea></div>'
        '<div class="field"><label for="exp-central-conflict">主冲突</label>'
        '<textarea id="exp-central-conflict" rows="2" maxlength="2000"></textarea></div>'
        '<div class="field"><label for="exp-ending-anchor">结局锚点</label>'
        '<textarea id="exp-ending-anchor" rows="2" maxlength="1000"></textarea></div>'
        '<div class="field"><label for="exp-arc-hints">前期弧线提示（每行一条）</label>'
        '<textarea id="exp-arc-hints" rows="3"></textarea></div>'
        '<div class="form-actions" style="justify-content:flex-end">'
        '<button type="button" id="expansion-regen" class="btn btn-paid btn-sm" data-ui-action="paid">重新扩写</button>'
        '<button type="button" id="expansion-save" class="btn btn-secondary btn-sm">保存扩写稿</button>'
        '</div>'
        '<div id="expansion-status"></div>'
        '<hr class="divider">'
        '<div class="field"><label for="kb-md">作品知识库（可编辑）</label>'
        '<textarea id="kb-md" rows="12"></textarea></div>'
        '<p class="muted">保存设定后，工作台会按依赖链提示重新生成大纲 / 细纲；'
        '已写正文与其评审记录不受影响。</p>'
        '<div class="form-actions" style="justify-content:flex-end">'
        '<button type="button" id="kb-save" class="btn btn-secondary btn-sm">保存知识库</button>'
        '</div>'
        '<div id="entity-panel" style="margin-top:12px"></div>'
        # iter 056: 作家风格卡（仅 premise 自创书；JS 据 workbench has_start_point gate）
        '<details class="details-fold" id="style-card-fold" style="margin-top:12px" hidden>'
        '<summary class="card-header">作家风格卡 <span class="muted">（仅自创书，注入写作笔法）</span></summary>'
        '<div id="style-card-body">'
        '<p class="muted" style="margin:8px 0">从预置库选一张，或上传样本提取；可在下方编辑器微调。仅从立意创建的作品生效，下一章写作时应用。</p>'
        '<div id="style-preset-grid" class="grid cols-3"></div>'
        '<details style="margin-top:12px"><summary class="muted">没有合适的？从写作样本提取 →</summary>'
        '<div class="field" style="margin-top:8px"><label for="style-sample-text">粘贴写作样本（≥200 字；只提炼笔法，不复制情节）</label>'
        '<textarea id="style-sample-text" rows="5"></textarea></div>'
        '<div class="field"><label for="style-sample-file">或上传文本文件（.txt / .md）</label>'
        '<input type="file" id="style-sample-file" accept=".txt,.md"></div>'
        '<div class="form-actions"><button type="button" id="style-extract-btn" class="btn btn-paid btn-sm" data-ui-action="paid">提取风格卡</button></div>'
        '<div id="style-extract-status"></div>'
        '</details>'
        '<hr class="divider">'
        '<div id="style-card-empty" class="muted" hidden>尚未设定风格卡；从上方选预置或提取样本，或直接填写后保存。</div>'
        '<div class="field"><label for="style-name">风格卡名称</label>'
        '<input type="text" id="style-name" maxlength="40"></div>'
        '<div class="field"><label for="style-category">流派定位</label>'
        '<input type="text" id="style-category" maxlength="40"></div>'
        '<div class="field"><label for="style-rhythm">叙事节奏</label>'
        '<textarea id="style-rhythm" rows="2" maxlength="200"></textarea></div>'
        '<details><summary class="muted">更多风格维度</summary>'
        '<div class="field" style="margin-top:8px"><label for="style-sentence">句式特征</label>'
        '<textarea id="style-sentence" rows="2" maxlength="200"></textarea></div>'
        '<div class="field"><label for="style-diction">用词偏好</label>'
        '<textarea id="style-diction" rows="2" maxlength="200"></textarea></div>'
        '<div class="field"><label for="style-imagery">意象比喻</label>'
        '<textarea id="style-imagery" rows="2" maxlength="300"></textarea></div>'
        '<div class="field"><label for="style-dialogue">对话风格</label>'
        '<textarea id="style-dialogue" rows="2" maxlength="300"></textarea></div>'
        '<div class="field"><label for="style-subtext">含蓄度</label>'
        '<textarea id="style-subtext" rows="2" maxlength="300"></textarea></div>'
        '<div class="field"><label for="style-narration">叙述视角</label>'
        '<textarea id="style-narration" rows="2" maxlength="200"></textarea></div>'
        '<div class="field"><label for="style-signatures">标志性笔法（每行一条）</label>'
        '<textarea id="style-signatures" rows="3"></textarea></div>'
        '<div class="field"><label for="style-taboo">规避笔法（每行一条）</label>'
        '<textarea id="style-taboo" rows="2"></textarea></div>'
        '</details>'
        '<div class="form-actions" style="justify-content:flex-end">'
        '<button type="button" id="style-save" class="btn btn-secondary btn-sm">保存风格卡</button>'
        '</div>'
        '<div id="style-card-status"></div>'
        '</div>'
        '</details>'
        '</div>'
        '</div></div></div>'

        # stage ② 大纲 (debate) + editable outline
        '<div class="flow-step">'
        '<div class="step-mark">2</div>'
        '<div class="card workbench-stage-card" id="stage-outline-card">'
        '<div class="card-header"><h3 class="ornament">生成大纲</h3>'
        '<span class="muted">生成全书故事大纲，可直接编辑后保存</span></div>'
        '<div class="card-body">'
        '<form id="outline-form" class="form-grid-2">'
        '<div class="field"><label>大纲生成</label>'
        '<div class="muted">根据作品设定生成可编辑的故事大纲</div></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="outline-submit" class="btn btn-paid" data-ui-action="paid">生成大纲</button>'
        '</div>'
        '</form>'
        '<div id="outline-status"></div>'
        '<div class="field" style="margin-top:12px"><label for="outline-md">大纲内容（可编辑）</label>'
        '<textarea id="outline-md" rows="12" placeholder="生成后在此查看 / 编辑大纲，然后点保存…"></textarea></div>'
        '<div class="form-actions" style="justify-content:flex-end">'
        '<button type="button" id="outline-save" class="btn btn-secondary">保存大纲</button>'
        '</div>'
        '</div></div></div>'

        # stage ③ 细纲 (plan-chapters) — read-only detail via /plan
        '<div class="flow-step">'
        '<div class="step-mark">3</div>'
        '<div class="card workbench-stage-card" id="stage-plan-card">'
        '<div class="card-header"><h3 class="ornament">生成细纲</h3>'
        '<span class="muted">生成分章细纲（章节计划）</span></div>'
        '<div class="card-body">'
        '<form id="plan-chapters-form" class="form-grid-2">'
        '<div class="field"><label for="plan-target-chapters">计划章节数</label>'
        '<input id="plan-target-chapters" name="target_chapters" type="number" min="1" max="200" value="5"></div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="plan-chapters-submit" class="btn btn-paid" data-ui-action="paid">生成细纲</button>'
        '</div>'
        '</form>'
        '<div id="plan-chapters-status"></div>'
        '<div id="plan-chapters-preview" class="muted" style="margin-top:12px">尚未生成细纲。</div>'
        '</div>'
        '<div class="card-footer">'
        '<a class="btn btn-ghost btn-sm" href="/w/' + esc + '/plan">查看细纲详情 →</a>'
        '</div>'
        '</div></div>'

        # stage ④ 正文 (write-book)
        '<div class="flow-step">'
        '<div class="step-mark">4</div>'
        '<div class="card workbench-stage-card" id="stage-write-card">'
        '<div class="card-header"><h3 class="ornament">撰写正文</h3>'
        '<span class="muted">逐章生成正文，自动评审</span></div>'
        '<div class="card-body">'
        '<form id="write-book-form" class="form-grid">'
        '<div class="field"><label for="write-chapters-input">写几章</label>'
        '<input id="write-chapters-input" name="chapters" type="number" min="1" value="1"></div>'
        '<div class="field"><label for="write-tier-select">评审档位</label>'
        '<select id="write-tier-select" name="tier">'
        '<option value="low">快速 · 试写</option>'
        '<option value="mid" selected>标准 · 日常创作</option>'
        '<option value="high">严格 · 发布门槛</option>'
        '</select></div>'
        # iter 050d (M-3): the input's default VALUE comes from
        # NOVEL_DEFAULT_BUDGET_CNY at render time — the form always submits
        # budget_cny explicitly, so without this the env cap would never
        # reach workbench-started jobs.
        '<div class="field"><label for="write-budget-input">预算上限（元）</label>'
        '<input id="write-budget-input" name="budget_cny" type="number" min="0" step="0.5" value="'
        + _format_budget(_default_budget_cny()) + '">'
        '<span class="muted">填 0 表示不设上限；使用真实生成时不建议这样设置。</span>'
        '</div>'
        '<div class="form-actions" style="align-items:flex-end">'
        '<button type="submit" id="write-book-submit" class="btn btn-paid" data-ui-action="paid">开始写书</button>'
        '<a id="write-book-open-chapter" class="btn btn-primary" href="/w/' + esc + '/chapters" hidden>打开章节</a>'
        '</div>'
        '</form>'
        '<div id="write-book-status"></div>'
        '</div>'
        '<div class="card-footer">'
        '<a class="btn btn-ghost btn-sm" href="/w/' + esc + '/chapters">查看章节 →</a>'
        '</div>'
        '</div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 工作台",
        page_kind="workbench",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("工作台", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="workbench"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: plan viewer
# ---------------------------------------------------------------------------


def render_workspace_plan(name: str, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">故事规划</p>'
        '<h1>故事规划</h1>'
        '<p class="muted">章节计划可以编辑；全局大纲和创作决定仅供查看。本页不会重新生成内容。</p>'
        '</div>'
        '<div id="plan-summary" class="cluster"></div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="chapters">章节计划</button>'
        '<button class="tab" data-tab="outline">大纲</button>'
        '<button class="tab" data-tab="decisions">创作决定</button>'
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
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("计划", None)]),
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
        '<h1>章节列表</h1>'
        '<p class="muted">原文章节仅供阅读参照；续写章节可以打开、编辑并查看保存与检查记录。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="chapters-filter phase-d-toolbar">'
        '<div class="field"><label for="chapter-search">搜索章节</label><input type="search" id="chapter-search" placeholder="输入章节标题"></div>'
        '<div class="field"><span class="field-label">来源</span><div class="filter-toggle cluster" aria-label="按章节来源筛选">'
        '<button class="btn btn-ghost btn-sm active" data-mode="all">全部</button>'
        '<button class="btn btn-ghost btn-sm" data-mode="drafts">续写章节</button>'
        '<button class="btn btn-ghost btn-sm" data-mode="source">原文章节</button>'
        '</div></div>'
        '<div class="field"><label for="chapter-sort">排序</label><select id="chapter-sort"><option value="newest">最近更新</option><option value="number">章节顺序</option></select></div>'
        '<button type="button" class="btn btn-secondary" id="chapter-clear-filter">清除筛选</button>'
        '</div>'
        '<div id="chapter-filter-status" class="sr-status" role="status" aria-live="polite"></div>'
        '<div class="card flush"><div class="card-body" id="chapters-table"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 章节",
        page_kind="chapters",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("章节", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="chapters"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: full-text search (iter075)
# ---------------------------------------------------------------------------


def render_workspace_search(name: str, workspaces: Iterable[str]) -> str:
    # 三态容器均由 static.py 的 initSearch() 在客户端渲染：初始引导 → 检索中 →
    # 有结果 / 无结果 / 错误卡。后端只出骨架，正文/高亮全在前端 DOM 安全构建。
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">内容搜索</p>'
        '<h1>内容搜索</h1>'
        '<p class="muted">在章节、人物和故事资料中组合查找；输入内容按原样匹配。</p>'
        '</div>'
        '</header>'
        '<section class="section">'
        '<div class="search-hero">'
        '<div class="search-box-wrap">'
        '<span class="search-icon" aria-hidden="true">✦</span>'
        '<input type="search" id="search-input" class="search-box" '
        'aria-label="全文搜索关键词" '
        'placeholder="输入关键词，如「路明非」「言灵」「诺诺」…" autofocus '
        'autocomplete="off" spellcheck="false">'
        '</div>'
        '<div class="search-sources cluster" id="search-sources">'
        '<label><input type="checkbox" value="original" checked> 原文章节</label>'
        '<label><input type="checkbox" value="draft" checked> 续写章节</label>'
        '<label><input type="checkbox" value="kb" checked> 人物与故事资料</label>'
        '</div>'
        '<button type="button" class="btn btn-secondary" id="search-clear">清除筛选</button>'
        '</div>'
        '<p class="search-summary muted" id="search-summary"></p>'
        '<div id="search-results" class="search-results">'
        '<div class="empty-state"><span class="ornament">✦</span>'
        '<h3>输入关键词开始检索</h3>'
        '<p class="muted">支持跨章定位实体、伏笔与关键词。</p></div>'
        '</div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 搜索",
        page_kind="search",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("搜索", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="search"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: chapter detail
# ---------------------------------------------------------------------------


def render_workspace_chapter_detail(name: str, chapter_no: int, workspaces: Iterable[str]) -> str:
    main = (
        '<header class="page-header">'
        '<div class="titles">'
        f'<p class="eyebrow ornament">第 {chapter_no} 章</p>'
        f'<h1>第 {chapter_no} 章</h1>'
        '<div class="chapter-meta-bar" id="chapter-meta-bar"></div>'
        '</div>'
        '<div class="topbar-actions">'
        f'<a class="btn btn-ghost btn-sm" href="/w/{escape(name)}/chapters" data-leave-guard>← 返回章节列表</a>'
        f'<a class="btn btn-ghost btn-sm" href="/w/{escape(name)}/" data-leave-guard>回作品概览</a>'
        '</div>'
        '</header>'
        '<section class="tabs">'
        '<div class="tab-list">'
        '<button class="tab active" data-tab="body">正文</button>'
        '<button class="tab" data-tab="edit">编辑</button>'
        '<button class="tab" data-tab="review">内容检查</button>'
        '<button class="tab" data-tab="lint">文字检查</button>'
        '<button class="tab" data-tab="style">文风</button>'
        '<button class="tab" data-tab="advisor">修改建议</button>'
        '<button class="tab" data-tab="history">保存记录</button>'
        '</div>'
        '<div class="tab-panel active" id="tab-body">'
        '<div id="chapter-body" class="card"><div class="card-body">载入中…</div></div>'
        '</div>'
        # iter 050 (B1/B2): in-place draft edit + re-review
        '<div class="tab-panel" id="tab-edit">'
        '<div class="card"><div class="card-body">'
        '<div class="field"><label for="draft-edit-area">正文内容（可编辑）</label>'
        '<textarea id="draft-edit-area" rows="24" placeholder="载入中…"></textarea></div>'
        '<p class="muted" id="draft-edit-help">保存后，旧的内容检查结果需要更新；“保存并重新检查”会在保存后开始一次独立检查。</p>'
        '<div class="form-actions">'
        '<button type="button" id="draft-save" class="btn btn-secondary">保存</button>'
        '<button type="button" id="draft-save-review" class="btn btn-paid" data-ui-action="paid">保存并重新检查</button>'
        '</div>'
        '<div id="draft-edit-status" class="save-state" role="status" aria-live="polite">尚未修改</div>'
        '</div></div>'
        '</div>'
        '<div class="tab-panel" id="tab-review"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-lint"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-style"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-advisor"><p class="muted">载入中…</p></div>'
        '<div class="tab-panel" id="tab-history"><p class="muted">载入中…</p></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 第 {chapter_no} 章",
        page_kind="chapter_detail",
        main_html=main,
        breadcrumb_html=_crumbs([
            ("书架", "/library"),
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
        '<p class="eyebrow ornament">内容检查</p>'
        '<h1>内容检查</h1>'
        '<p class="muted">集中查看人物、时间、地点、设定与前后文问题。本页只提供查看位置，不会修改检查状态。</p>'
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
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("评审", None)]),
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
        '<h1>创作数据</h1>'
        '<p class="muted">只读汇总已保存记录中的各章使用额度、内容复用情况与内容检查分项。</p>'
        '</div>'
        '<span class="badge no-dot">只读统计</span>'
        '</header>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">每章额度</h2>'
        '<span class="hint">按章节汇总已保存的生成调用</span></div>'
        '<div class="card"><div class="card-body" id="insights-cost"></div></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">内容复用情况</h2>'
        '<span class="hint">展示已保存记录中可确认的内容复用比例</span></div>'
        '<div class="card"><div class="card-body" id="insights-cache"></div></div>'
        '</section>'
        '<section class="section">'
        '<div class="section-title"><h2 class="ornament">内容检查分项</h2>'
        '<span class="hint">按章节展示剧情、文笔与设定一致性</span></div>'
        '<div class="card"><div class="card-body" id="insights-subscores"></div></div>'
        '</section>'
    )
    return _render_shell(
        title=f"{name} · 创作数据",
        page_kind="insights",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("数据", None)]),
        topbar_actions_html=_topbar_actions(),
        sidebar_html=_sidebar(workspaces, active_workspace=name, active_section="insights"),
        workspace=name,
    )


# ---------------------------------------------------------------------------
# Page: jobs history + log tail
# ---------------------------------------------------------------------------


def render_workspace_jobs(name: str, workspaces: Iterable[str]) -> str:
    from .workspace_meta import read as _meta_read

    is_drama = _meta_read(name).get("type", "novel") == "drama"
    if is_drama:
        main = (
            '<header class="page-header"><div class="titles"><p class="eyebrow ornament">任务</p>'
            '<h1>任务历史</h1><p class="muted">查看最近任务与经过保护的调用摘要。</p></div></header>'
            '<section class="section"><div class="card flush"><div class="card-body" id="jobs-recent"></div></div></section>'
            '<section class="section"><div class="section-title"><h2 class="ornament">最近生成调用</h2>'
            '<span class="hint">已隐藏请求与生成服务错误详情</span></div><div id="jobs-logs"></div></section>'
        )
    else:
        main = (
        '<header class="page-header">'
        '<div class="titles">'
        '<p class="eyebrow ornament">任务</p>'
        '<h1>任务记录</h1>'
        '<p class="muted">任务离页后仍会继续。这里按已保存状态显示进度、结果和安全恢复入口。</p>'
        '</div>'
        '</header>'
        '<section class="jobs-filter filter-toggle cluster" aria-label="筛选任务">'
        '<button type="button" class="btn btn-ghost active" data-job-filter="all">全部</button>'
        '<button type="button" class="btn btn-ghost" data-job-filter="active">处理中</button>'
        '<button type="button" class="btn btn-ghost" data-job-filter="done">已完成</button>'
        '<button type="button" class="btn btn-ghost" data-job-filter="attention">需要处理</button>'
        '</section>'
        '<div id="jobs-filter-status" class="sr-status" role="status" aria-live="polite"></div>'
        '<section class="section">'
        '<div class="card flush"><div class="card-body" id="jobs-recent"></div></div>'
        '</section>'
        '<div id="jobs-logs" hidden aria-hidden="true"></div>'
        )
    return _render_shell(
        title=f"{name} · 任务",
        page_kind="jobs",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), (name, f"/w/{escape(name)}/"), ("任务", None)]),
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
        '<h1>创建作品</h1>'
        '<p class="muted">先选择创作方式；每种方式所需内容、是否生成以及完成后的去向都不同。</p>'
        '</div>'
        '</header>'
        '<div class="alert info wizard-mode-card" id="wizard-mode-card">当前运行方式：检测中…</div>'
        '<p class="muted wizard-mode-help">需要使用真实生成服务时，请先在 '
        '<a href="/settings">设置</a> 中完成连接配置并重启；默认离线试跑不会发起真实请求。</p>'

        '<section class="card" id="panel-type">'
        '<div class="card-header"><h3 class="ornament">第 0 步 · 类型</h3></div>'
        '<div class="card-body">'
        '<form id="type-form" class="stack" aria-describedby="type-form-help">'
        '<p id="type-form-help" class="muted">选择后会先进入对应表单，不会立即创建或生成内容。</p>'
        '<label class="field-check wizard-choice">'
        '<input type="radio" name="ws_type" value="novel" checked> '
        '<span><strong>从本地原文创建</strong><small>需要作品名和本地小说文件；提交后会整理原文并在当前运行方式下准备初始内容。</small></span>'
        '</label>'
        '<label class="field-check wizard-choice">'
        '<input type="radio" name="ws_type" value="drama"> '
        '<span><strong>创建短剧作品</strong><small>需要题材、类型、集数和时长；先建立独立短剧作品，不会在此步生成媒体。</small></span>'
        '</label>'
        '<label class="field-check wizard-choice">'
        '<input type="radio" name="ws_type" value="premise"> '
        '<span><strong>创建原创故事</strong><small>需要作品名和一句话立意；可选择是否生成设定，完成后进入小说工作台。</small></span>'
        '</label>'
        '<div class="form-actions">'
        '<a class="btn btn-ghost" href="/library">取消</a>'
        '<button type="submit" class="btn btn-primary" id="type-next">下一步</button>'
        '</div>'
        '</form>'
        '</div>'
        '</section>'

        '<section class="card" id="panel-upload" hidden>'
        '<div class="card-header"><h3 class="ornament">第 1 步 · 上传小说</h3></div>'
        '<div class="card-body">'
        '<div class="wizard-help-card">'
        '<p class="eyebrow ornament">会发生什么</p>'
        '<div class="kv-list compact">'
        '<div class="k">1</div><div class="v">导入文本并切章</div>'
        '<div class="k">2</div><div class="v">抽取知识库与起始设定</div>'
        '<div class="k">3</div><div class="v">生成首章草稿，可随时请求取消</div>'
        '</div>'
        '</div>'
        '<form id="wizard-form" enctype="multipart/form-data" class="stack">'
        '<div class="field">'
        '<label for="upload-workspace">作品名</label>'
        '<input id="upload-workspace" name="workspace" required aria-describedby="upload-workspace-help" '
        # iter064 #5: single-sourced from _naming.WORKSPACE_NAME_HTML_PATTERN so
        # the client check can't drift from the backend WORKSPACE_NAME_RE again.
        # The constant keeps the iter063 A4 escaped hyphen (Chromium `v` flag)
        # and forbids a trailing hyphen (the optional non-capturing group),
        # which the old `[...]?` final char wrongly allowed (e.g. `foo-`).
        f'pattern="{WORKSPACE_NAME_HTML_PATTERN}" '
        'title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符">'
        '<small id="upload-workspace-help">必填；使用便于识别的名称，不需要填写本地目录。</small>'
        '</div>'
        '<div class="field">'
        '<label for="upload-file">小说文件</label>'
        '<input id="upload-file" name="upload" type="file" accept=".epub,.txt" required aria-describedby="upload-file-help">'
        '<small id="upload-file-help">必填；选择电子书文件或 UTF-8 编码的纯文本文件。创建失败时需要重新确认文件选择。</small>'
        '</div>'
        '<details class="details-fold wizard-advanced">'
        '<summary>高级选项</summary>'
        '<div class="form-grid-2">'
        '<div class="field">'
        '<label>人民币额度上限</label>'
        '<input name="budget_cny" type="number" min="0" step="0.1" placeholder="0 = 不限制">'
        '</div>'
        '<div class="field">'
        '<label>超时分钟</label>'
        '<input name="timeout_minutes" type="number" min="0" step="1" placeholder="0 = 不启用">'
        '</div>'
        '<div class="field">'
        '<label>本次抽取章节数</label>'
        '<input name="extract_limit" type="number" min="1" max="200" value="5">'
        '</div>'
        '</div>'
        '</details>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-paid" data-ui-action="paid">导入并创建</button>'
        '</div>'
        '</form>'

        '<div id="upload-error" role="alert" aria-live="assertive"></div>'
        '</div>'
        '</section>'

        '<section class="card" id="panel-premise" hidden>'
        '<div class="card-header"><h3 class="ornament">第 1 步 · 一句话开书</h3></div>'
        '<div class="card-body">'
        '<form id="premise-form" class="stack">'
        '<div class="field">'
        '<label for="premise-workspace">作品名</label>'
        '<input id="premise-workspace" name="workspace" required aria-describedby="premise-workspace-help" '
        # iter064 #5: single-sourced from _naming.WORKSPACE_NAME_HTML_PATTERN so
        # the client check can't drift from the backend WORKSPACE_NAME_RE again.
        # The constant keeps the iter063 A4 escaped hyphen (Chromium `v` flag)
        # and forbids a trailing hyphen (the optional non-capturing group),
        # which the old `[...]?` final char wrongly allowed (e.g. `foo-`).
        f'pattern="{WORKSPACE_NAME_HTML_PATTERN}" '
        'title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符">'
        '<small id="premise-workspace-help">必填；创建成功后会成为作品列表中的显示名称。</small>'
        '</div>'
        '<div class="field">'
        '<label for="premise-text">一句话立意</label>'
        '<textarea id="premise-text" name="premise" rows="3" maxlength="2000" required aria-describedby="premise-text-help" '
        'placeholder="例：少年觉醒上古血脉，在宗门倾轧中逆天改命。"></textarea>'
        '<small id="premise-text-help">必填；写清主角、目标与主要冲突，之后仍可在工作台修改设定。</small>'
        '</div>'
        # iter 051a: expansion is opt-out — checked by default, skippable
        '<div class="field"><label style="font-weight:normal">'
        '<input type="checkbox" name="expand" checked> '
        '自动扩写设定（推荐）：把一句话立意扩成结构化设定稿，可在工作台查看 / 编辑'
        '</label></div>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-paid" data-ui-action="paid">从一句话开始</button>'
        '</div>'
        '</form>'
        '<div id="premise-error" role="alert" aria-live="assertive"></div>'
        '</div>'
        '</section>'

        '<section class="card" id="panel-drama" hidden>'
        '<div class="card-header"><h3 class="ornament">第 1 步 · 短剧作品</h3></div>'
        '<div class="card-body">'
        '<div class="wizard-help-card">'
        '<p class="eyebrow ornament">会发生什么</p>'
        '<div class="kv-list compact">'
        '<div class="k">1</div><div class="v">创建独立短剧作品</div>'
        '<div class="k">2</div><div class="v">保存题材、赛道与创作规范快照</div>'
        '<div class="k">3</div><div class="v">进入 4 站创作与评审组装流程，任务可在进度页取消</div>'
        '</div>'
        '</div>'
        '<form id="drama-form" class="stack">'
        '<div class="field">'
        '<label for="drama-workspace">作品名</label>'
        '<input id="drama-workspace" name="workspace" required aria-describedby="drama-workspace-help" '
        # iter064 #5: single-sourced from _naming.WORKSPACE_NAME_HTML_PATTERN so
        # the client check can't drift from the backend WORKSPACE_NAME_RE again.
        # The constant keeps the iter063 A4 escaped hyphen (Chromium `v` flag)
        # and forbids a trailing hyphen (the optional non-capturing group),
        # which the old `[...]?` final char wrongly allowed (e.g. `foo-`).
        f'pattern="{WORKSPACE_NAME_HTML_PATTERN}" '
        'title="字母 / 数字 / 下划线 / 中文 / 中间可含 -；不超过 32 字符">'
        '<small id="drama-workspace-help">必填；创建后会成为短剧作品列表中的显示名称。</small>'
        '</div>'
        '<div class="field">'
        '<label for="drama-topic">题材描述（1-500 字）</label>'
        '<textarea id="drama-topic" name="topic" rows="3" maxlength="500" required aria-describedby="drama-topic-help" '
        'placeholder="示例：复仇 → 救赎，单线发展，强冲突"></textarea>'
        '<small id="drama-topic-help">必填；概括核心冲突和故事走向，创建后仍可继续完善。</small>'
        '</div>'
        '<fieldset class="field" aria-describedby="drama-track-help">'
        '<legend>赛道（必填）</legend>'
        '<div class="cluster">'
        '<label class="field-check"><input type="radio" name="track" value="霸总" required> 霸总</label>'
        '<label class="field-check"><input type="radio" name="track" value="重生"> 重生</label>'
        '<label class="field-check"><input type="radio" name="track" value="推理"> 推理</label>'
        '<label class="field-check"><input type="radio" name="track" value="系统"> 系统</label>'
        '<label class="field-check"><input type="radio" name="track" value="觉醒"> 觉醒</label>'
        '</div>'
        '<small id="drama-track-help">选择最接近的故事类型，用于准备对应创作规范。</small>'
        '</fieldset>'
        '<div class="form-grid-2">'
        '<div class="field">'
        '<label for="drama-episode-count">集数（1-100）</label>'
        '<input id="drama-episode-count" name="episode_count" type="number" min="1" max="100" value="12" required aria-describedby="drama-episode-count-help">'
        '<small id="drama-episode-count-help">必填；填写计划创建的总集数。</small>'
        '</div>'
        '<fieldset class="field" aria-describedby="drama-duration-help">'
        '<legend>单集时长（秒）</legend>'
        '<div class="cluster">'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="30"> 30</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="60" checked> 60</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="90"> 90</label>'
        '<label class="field-check"><input type="radio" name="episode_duration_seconds" value="120"> 120</label>'
        '</div>'
        '<small id="drama-duration-help">选择每集计划时长，默认 60 秒。</small>'
        '</fieldset>'
        '</div>'
        '<details class="details-fold wizard-advanced">'
        '<summary>高级选项</summary>'
        '<div class="form-grid-2">'
        '<div class="field">'
        '<label for="drama-budget">人民币额度上限</label>'
        '<input id="drama-budget" name="budget_cny" type="number" min="0" step="0.1" placeholder="0 = 不限制" aria-describedby="drama-budget-help">'
        '<small id="drama-budget-help">可选；仅限制后续真实生成任务，创建作品本身不会使用额度。</small>'
        '</div>'
        '<div class="field">'
        '<label for="drama-timeout">超时分钟</label>'
        '<input id="drama-timeout" name="timeout_minutes" type="number" min="0" step="1" placeholder="0 = 不启用" aria-describedby="drama-timeout-help">'
        '<small id="drama-timeout-help">可选；用于后续任务等待，创建作品不受影响。</small>'
        '</div>'
        '</div>'
        '</details>'
        '<div class="form-actions">'
        '<button type="button" class="btn btn-ghost" data-back-to-type>← 返回</button>'
        '<button type="submit" class="btn btn-primary">创建并进入短剧创作</button>'
        '</div>'
        '</form>'
        '<div id="drama-error" role="alert" aria-live="assertive"></div>'
        '</div>'
        '</section>'

        '<section class="card" id="panel-progress" hidden>'
        '<div class="card-header"><h3 class="ornament">第 2 步 · 创建进度</h3></div>'
        '<div class="card-body" id="progress-body"><p class="muted">等待任务开始…</p></div>'
        '</section>'
        '</div>'
    )
    return _render_shell(
        title="新建作品 · 写作工作台",
        page_kind="wizard",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), ("新建作品", None)]),
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
        '<h1>使用设置</h1>'
        '<p class="muted">查看当前运行方式并调整创作偏好；连接信息仅在高级设置中按需修改。</p>'
        '</div>'
        '</header>'
        '<section class="card">'
        '<div class="card-header"><h3 class="ornament">当前运行方式</h3></div>'
        '<div class="card-body">'
        '<div id="settings-mode" class="public-mode-summary" role="status" aria-live="polite">正在读取…</div>'
        '<p class="muted">“离线模式”表示不会发起真实请求；“尚未开始”只表示当前没有创作任务，两者含义不同。</p>'
        '</div></section>'
        '<section class="card">'
        '<div class="card-header"><h3 class="ornament">创作偏好</h3><span class="badge no-dot badge-muted">可修改</span></div>'
        '<div class="card-body">'
        '<div id="restart-banner" hidden></div>'
        '<form id="settings-form" class="stack" aria-describedby="settings-help"></form>'
        '<p id="settings-help" class="muted">只显示当前页面允许安全修改的偏好；保存后按页面提示操作。</p>'
        '<div id="settings-error" role="status" aria-live="polite"></div>'
        '</div>'
        '<div class="card-footer">'
        '<button type="submit" form="settings-form" class="btn btn-primary">保存设置</button>'
        '</div>'
        '</section>'
        '</div>'
    )
    return _render_shell(
        title="使用设置 · 续写工作台",
        page_kind="settings",
        main_html=main,
        breadcrumb_html=_crumbs([("书架", "/library"), ("设置", None)]),
        topbar_actions_html='<a class="btn btn-primary" href="/wizard">＋ 新建</a>',
        sidebar_html="",
        extra_scripts='<script src="/static/settings.js"></script>',
    )


# ---------------------------------------------------------------------------
# Page: landing (investor-facing root entry, full-screen, no sidebar)
# ---------------------------------------------------------------------------


# Inline brand mark: an open book outlined in jade with an amber ✦ spark.
# Pure inline SVG, no external asset, no bare ``$`` (Template-safe).
_LP_LOGO_SVG = (
    '<svg class="lp-logo" width="44" height="44" viewBox="0 0 44 44" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M22 11 C18 8.5 11 8.5 7 10 V34 C11 32.5 18 32.5 22 35 '
    'C26 32.5 33 32.5 37 34 V10 C33 8.5 26 8.5 22 11 Z" '
    'fill="#FFFEFB" stroke="#3F6B5A" stroke-width="1.8" stroke-linejoin="round"/>'
    '<path d="M22 11 V35" stroke="#3F6B5A" stroke-width="1.4"/>'
    '<path d="M30.5 14 l1.25 3.05 3.05 1.25 -3.05 1.25 -1.25 3.05 '
    '-1.25 -3.05 -3.05 -1.25 3.05 -1.25 Z" fill="#C97B3D"/>'
    '</svg>'
)


def render_landing() -> str:
    main = (
        '<div class="lp">'
        '<header class="lp-hero fade-up">'
        '<div class="lp-hero-brand">' + _LP_LOGO_SVG +
        '<span class="lp-wordmark">续写工作台</span></div>'
        '<p class="eyebrow ornament">小说与短剧创作工具</p>'
        '<h1 class="lp-title">把故事从想法带到下一章</h1>'
        '<p class="lp-lead muted">可以导入本地小说继续创作，也可以从一句话建立原创故事；短剧作品使用独立入口。作品内容保留在本机，是否使用真实生成取决于你之后的设置与逐次确认。</p>'
        '</header>'
        '<section class="lp-cards public-entry-grid" aria-label="开始使用">'
        '<article class="card lp-card fade-up fade-up-1">'
        '<div class="card-body">'
        '<div class="lp-card-head"><h2>创建小说作品</h2></div>'
        '<p class="muted">导入本地原文继续写，或从一句话建立原创故事。选择方式后再填写所需内容。</p></div>'
        '<div class="card-footer lp-card-footer">'
        '<a class="btn btn-primary" href="/wizard">创建小说作品</a></div>'
        '</article>'
        '<article class="card lp-card fade-up fade-up-2">'
        '<div class="card-body">'
        '<div class="lp-card-head"><h2>打开已有作品</h2></div>'
        '<p class="muted">查看本机已有的小说与短剧，了解最近进度并从上次停下的位置继续。</p></div>'
        '<div class="card-footer lp-card-footer">'
        '<a class="btn btn-secondary" href="/library">打开已有作品</a></div>'
        '</article>'
        '<article class="card lp-card fade-up fade-up-3">'
        '<div class="card-body">'
        '<div class="lp-card-head"><h2>进入短剧作品</h2></div>'
        '<p class="muted">创建独立短剧作品并进入短剧创作流程。真实文字、图片、视频和声音仍需分别确认。</p></div>'
        '<div class="card-footer lp-card-footer">'
        '<a class="btn btn-secondary" href="/wizard?type=drama">进入短剧作品</a></div>'
        '</article>'
        '</section>'
        '<section class="public-next-step fade-up fade-up-4">'
        '<h2>接下来会发生什么</h2>'
        '<ol><li>选择作品类型与创建方式</li><li>填写当前方式需要的内容</li><li>确认运行方式后创建作品</li><li>进入对应工作台继续创作</li></ol>'
        '<p class="muted">页面初始化失败时，可以重新加载；已有本地作品不会因此改变。</p>'
        '</section>'
        '</div>'
    )
    return _render_shell(
        title="续写工作台 · 本地协作创作工具",
        page_kind="landing",
        main_html=main,
        breadcrumb_html=_crumbs([("续写工作台", None)]),
        topbar_actions_html='<a class="btn btn-ghost" href="/settings">⚙ 设置</a>',
        sidebar_html="",
        extra_scripts="",
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
