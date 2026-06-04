"""Embedded CSS / JS for the WebUI.

The current WebUI uses a shared information architecture and visual system
(see ``docs/iterations/iteration_032_webui_ia_visual.md``):

* New literary-warm design tokens (rice-paper background, ink text,
  jade brand colour, amber CTA, serif headings).
* A unified component library defined in CSS variables — every
  template renders against the same .btn / .badge / .card / .tabs /
  .breadcrumb / .sidebar / .skeleton / .kv-list / .empty-state shapes.
* JS is still served as a single ``/static/app.js`` bundle that
  branches on ``window.PAGE_KIND``. We deliberately keep established
  identifiers ``loadTabPanel``, ``scheduleReadiness``,
  ``readinessRequestSeq``, ``writeBookJobRunning``, ``readinessTimer``
  and the ``submit.disabled = writeBookJobRunning || data.status === 'blocked'``
  expression so the iter 026 test suite stays green.
"""

from __future__ import annotations

from typing import Any, Mapping


def job_actionable_summary(job: Mapping[str, Any]) -> str:
    status = str(job.get("status") or "?")
    icons = {
        "succeeded": "✓",
        "blocked": "!",
        "failed": "!",
        "lost": "?",
        "running": "…",
        "pending": "…",
        "aborted": "!",
        "budget_exceeded": "¥",
    }
    result = job.get("result_summary")
    summary = result if isinstance(result, Mapping) else {}
    first_blocked = summary.get("first_blocked")
    blocked = first_blocked if isinstance(first_blocked, Mapping) else {}
    reason = str(blocked.get("reason") or "")
    line = _job_failure_line(job)
    icon = icons.get(status, "•")
    if status == "succeeded":
        return icon + " succeeded" + (" · snapshot ready" if summary.get("snapshot_path") else "")
    if reason:
        return icon + " " + status + " · " + reason
    if line:
        return icon + " " + status + " · " + line
    return icon + " " + status


def jobActionableSummary(job: Mapping[str, Any]) -> str:
    return job_actionable_summary(job)


def _job_failure_line(job: Mapping[str, Any]) -> str:
    result = job.get("result_summary")
    summary = result if isinstance(result, Mapping) else {}
    first_blocked = summary.get("first_blocked")
    blocked = first_blocked if isinstance(first_blocked, Mapping) else {}
    if blocked and (blocked.get("reason") or blocked.get("error")):
        parts = []
        if blocked.get("chapter"):
            parts.append(f"ch{blocked.get('chapter')}")
        if blocked.get("reason"):
            parts.append(str(blocked.get("reason")))
        if blocked.get("error"):
            parts.append(str(blocked.get("error")))
        return " · ".join(parts)
    if summary.get("error"):
        return str(summary.get("error")).split("\n")[0]
    return str(job.get("error") or "").split("\n")[0]


CSS_BODY = """\
/* ========================================================================
 * Literary warm design system
 * ----------------------------------------------------------------------
 * Layer order: tokens → reset → typography → layout → components →
 * page-specific overrides. Anything that needs to mutate a colour or
 * radius should reach for a token, never a literal hex.
 * ====================================================================== */

:root {
  /* paper / ink palette */
  --bg-paper: #FBF7F0;
  --bg-card: #FFFEFB;
  --bg-sunken: #F4EEE2;
  --bg-overlay: rgba(42, 37, 32, 0.45);
  --ink-1: #2A2520;
  --ink-2: #5C544A;
  --ink-3: #9B9285;
  --ink-inverse: #FBF7F0;

  /* brand accents */
  --jade: #3F6B5A;
  --jade-soft: #E6EFE9;
  --jade-strong: #2E5343;
  --amber: #C97B3D;
  --amber-soft: #F8E7D3;
  --amber-strong: #A35F27;
  --sienna: #A8533D;
  --sienna-soft: #F4DCD2;
  --gold: #B89249;
  --gold-soft: #F4E7C7;

  /* lines & shadows */
  --rule: #E7DFD2;
  --rule-strong: #D4C9B4;
  --shadow-card: 0 1px 0 var(--rule);

  /* spacing scale */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;

  /* radius */
  --radius-1: 4px;
  --radius-2: 8px;
  --radius-pill: 999px;

  /* typography */
  --font-serif: "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC",
    "STSong", "SimSun", Georgia, serif;
  --font-sans: "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue",
    -apple-system, BlinkMacSystemFont, "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", "SFMono-Regular", Menlo,
    Consolas, monospace;
  --fs-xs: 12px;
  --fs-sm: 13px;
  --fs-md: 14px;
  --fs-lg: 16px;
  --fs-xl: 18px;
  --fs-h2: 22px;
  --fs-h1: 28px;
  --fs-display: 36px;

  /* layout */
  --sidebar-w: 240px;
  --topbar-h: 56px;
  --reading-w: 720px;
}

/* ---------- reset ---------- */
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg-paper);
  color: var(--ink-1);
  font-family: var(--font-sans);
  font-size: var(--fs-md);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
h1, h2, h3, h4 { font-family: var(--font-serif); margin: 0; font-weight: 600; line-height: 1.3; color: var(--ink-1); }
h1 { font-size: var(--fs-h1); }
h2 { font-size: var(--fs-h2); }
h3 { font-size: var(--fs-xl); }
h4 { font-size: var(--fs-lg); }
p { margin: 0 0 var(--space-3); }
a { color: var(--jade); text-decoration: none; border-bottom: 1px solid transparent; transition: border-color .15s ease; }
a:hover { border-bottom-color: var(--jade); }
code, pre, kbd, samp { font-family: var(--font-mono); font-size: var(--fs-sm); }
pre { white-space: pre-wrap; word-break: break-word; }
hr { border: 0; border-top: 1px solid var(--rule); margin: var(--space-4) 0; }
small { font-size: var(--fs-xs); color: var(--ink-3); }

.muted { color: var(--ink-3); }
.subdued { color: var(--ink-2); }
.eyebrow {
  font-family: var(--font-serif);
  text-transform: none;
  letter-spacing: 0.08em;
  font-size: var(--fs-xs);
  color: var(--jade);
  margin: 0;
}
.ornament::before { content: "✦"; color: var(--jade); margin-right: .35em; }

/* ---------- layout: app shell ---------- */
.app {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  min-height: 100vh;
}
.app.no-context { grid-template-columns: 1fr; }

.sidebar {
  background: var(--bg-card);
  border-right: 1px solid var(--rule);
  padding: var(--space-5) var(--space-4);
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.sidebar .brand {
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  color: var(--ink-1);
  display: flex;
  align-items: center;
  gap: .35em;
  border: 0;
}
.sidebar .brand:hover { border-bottom: 0; color: var(--jade); }
.sidebar-section { display: flex; flex-direction: column; gap: var(--space-1); }
.sidebar-section h4 {
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  color: var(--ink-3);
  letter-spacing: 0.06em;
  margin-bottom: var(--space-2);
  font-weight: 500;
  padding: 0 var(--space-2);
}
.sidebar-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-1);
  color: var(--ink-2);
  border: 0;
  font-size: var(--fs-sm);
}
.sidebar-item:hover { background: var(--bg-sunken); color: var(--ink-1); border: 0; }
.sidebar-item.active {
  background: var(--jade-soft);
  color: var(--jade-strong);
  font-weight: 600;
}
.sidebar-item .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ink-3);
  flex: 0 0 6px;
}
.sidebar-item.active .dot { background: var(--jade); }
.sidebar-item .meta { font-size: var(--fs-xs); color: var(--ink-3); }
.sidebar-footer {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
.sidebar-overlay { display: none; }

.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--rule);
  background: var(--bg-paper);
  position: sticky;
  top: 0;
  z-index: 5;
}
.topbar .breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}
.breadcrumb a { color: var(--ink-2); border: 0; }
.breadcrumb a:hover { color: var(--jade); }
.breadcrumb .sep { color: var(--ink-3); }
.breadcrumb .here { color: var(--ink-1); font-weight: 600; }
.nav-toggle, .topbar-menu-toggle { display: none; }
.topbar-actions-wrap { display: flex; align-items: center; position: relative; }
.topbar-actions { display: flex; gap: var(--space-2); align-items: center; }

.page {
  padding: var(--space-6);
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}
.page-header { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.page-header .titles { display: flex; flex-direction: column; gap: var(--space-1); }
.page-header h1 { font-size: var(--fs-display); }

.section { display: flex; flex-direction: column; gap: var(--space-4); }
.section-title { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
.section-title h2 { font-size: var(--fs-h2); }
.section-title .hint { color: var(--ink-3); font-size: var(--fs-sm); }

/* ---------- components ---------- */

/* buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 36px;
  padding: var(--space-2) var(--space-4);
  border: 1px solid transparent;
  border-radius: var(--radius-1);
  font-family: inherit;
  font-size: var(--fs-sm);
  font-weight: 600;
  cursor: pointer;
  background: transparent;
  color: var(--ink-1);
  transition: background .15s ease, border-color .15s ease, color .15s ease;
}
.btn:focus-visible { outline: 2px solid var(--jade); outline-offset: 2px; }
.btn[disabled], .btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-primary {
  background: var(--amber);
  color: #fff;
  border-color: var(--amber);
}
.btn-primary:hover:not(:disabled) { background: var(--amber-strong); border-color: var(--amber-strong); }
.btn-secondary {
  background: var(--bg-card);
  color: var(--jade-strong);
  border-color: var(--rule-strong);
}
.btn-secondary:hover:not(:disabled) { background: var(--jade-soft); border-color: var(--jade); }
.btn-ghost {
  background: transparent;
  color: var(--ink-2);
  border-color: transparent;
}
.btn-ghost:hover:not(:disabled) { background: var(--bg-sunken); color: var(--ink-1); }
.btn-danger {
  background: transparent;
  color: var(--sienna);
  border-color: var(--sienna);
}
.btn-icon {
  width: 36px; padding: 0;
  background: var(--bg-card);
  border-color: var(--rule);
  color: var(--ink-2);
}
.btn-sm { min-height: 28px; padding: var(--space-1) var(--space-3); font-size: var(--fs-xs); }

/* badges / status pills */
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-2);
  border-radius: var(--radius-pill);
  font-size: var(--fs-xs);
  font-weight: 600;
  border: 1px solid var(--rule);
  background: var(--bg-card);
  color: var(--ink-2);
  white-space: nowrap;
}
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .7; }
.badge.no-dot::before { display: none; }
.badge.ready, .badge.succeeded, .badge.done, .badge.approve { color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge.warn, .badge.queued, .badge.warning, .badge.abstain { color: var(--gold); background: var(--gold-soft); border-color: var(--gold-soft); }
.badge.blocked, .badge.failed, .badge.aborted, .badge.reject, .badge.lost { color: var(--sienna); background: var(--sienna-soft); border-color: var(--sienna-soft); }
.badge.running, .badge.pending { color: var(--amber-strong); background: var(--amber-soft); border-color: var(--amber-soft); }
.badge-novel { color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge-drama { color: var(--amber-strong); background: var(--amber-soft); border-color: var(--amber-soft); }
.badge-muted { color: var(--ink-3); background: var(--bg-sunken); border-color: var(--rule); }

/* card */
.card {
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--rule);
}
.card-header h3 { font-size: var(--fs-lg); }
.card-header .lead { color: var(--ink-3); font-size: var(--fs-sm); margin: 2px 0 0; }
.card-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.card-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--rule);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  background: var(--bg-sunken);
}
.card.flush .card-body { padding: 0; }

/* grid utilities */
.grid { display: grid; gap: var(--space-4); }
.grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.grid.cols-auto { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.cluster { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.stack { display: flex; flex-direction: column; gap: var(--space-3); }

/* kv-list */
.kv-list {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--space-2) var(--space-4);
  font-size: var(--fs-sm);
}
.kv-list .k { color: var(--ink-3); }
.kv-list .v { color: var(--ink-1); word-break: break-word; }
.kv-list .v code { color: var(--ink-2); }
.kv-list.compact { font-size: var(--fs-xs); gap: var(--space-1) var(--space-3); }

/* forms */
.field { display: flex; flex-direction: column; gap: var(--space-1); font-size: var(--fs-sm); }
.field label { color: var(--ink-2); font-weight: 500; font-size: var(--fs-xs); }
.field input, .field select, .field textarea {
  width: 100%;
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-1);
  background: var(--bg-card);
  color: var(--ink-1);
  font-family: inherit;
  font-size: var(--fs-sm);
}
.field input:focus, .field select:focus, .field textarea:focus {
  outline: 2px solid var(--jade);
  outline-offset: 0;
  border-color: var(--jade);
}
.field-check {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-1);
  font-size: var(--fs-sm);
}
.field-check input { width: auto; min-height: 0; }
.form-grid { display: grid; gap: var(--space-3) var(--space-4); grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid-2 { display: grid; gap: var(--space-3) var(--space-4); grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-actions { display: flex; justify-content: flex-end; gap: var(--space-2); align-items: center; }

/* tabs */
.tabs { display: flex; flex-direction: column; gap: var(--space-4); }
.tab-list {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--rule);
  overflow-x: auto;
}
.tab {
  border: 0;
  background: transparent;
  padding: var(--space-2) var(--space-3);
  font-family: inherit;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-2);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  white-space: nowrap;
}
.tab:hover { color: var(--ink-1); }
.tab.active { color: var(--jade-strong); border-bottom-color: var(--jade); }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* breadcrumbs reused in sub-pages (under topbar) */
.subnav {
  display: flex;
  gap: var(--space-1);
  align-items: center;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}

/* empty-state */
.empty-state {
  text-align: center;
  padding: var(--space-7) var(--space-5);
  background: var(--bg-card);
  border: 1px dashed var(--rule-strong);
  border-radius: var(--radius-2);
  color: var(--ink-2);
}
.empty-state .ornament { color: var(--jade); font-size: var(--fs-h2); display: block; margin-bottom: var(--space-3); }
.empty-state h3 { margin-bottom: var(--space-2); color: var(--ink-1); }
.empty-state .cta { margin-top: var(--space-4); }
.empty-state .cta.cluster { justify-content: center; }

/* skeleton — replaces "loading..." */
.skeleton {
  background: linear-gradient(90deg, var(--bg-sunken) 0%, #EFE7D6 50%, var(--bg-sunken) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: var(--radius-1);
  color: transparent;
  min-height: 1em;
}
.skeleton.row { height: 14px; margin: 6px 0; }
.skeleton.row.short { width: 40%; }
.skeleton.row.long { width: 88%; }
.skeleton-block { padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* toast placeholder */
.toast-stack { position: fixed; bottom: var(--space-5); right: var(--space-5); display: flex; flex-direction: column; gap: var(--space-2); z-index: 50; }
.toast {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--jade);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-1);
  font-size: var(--fs-sm);
  box-shadow: 0 2px 6px rgba(42, 37, 32, .08);
}
.toast.error { border-left-color: var(--sienna); }
.toast.warn { border-left-color: var(--gold); }
.toast-dismiss {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 0;
}

/* alerts inline */
.alert {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-1);
  font-size: var(--fs-sm);
  border: 1px solid var(--rule);
  background: var(--bg-card);
}
.alert.error { background: var(--sienna-soft); border-color: var(--sienna-soft); color: var(--sienna); }
.alert.warn { background: var(--gold-soft); border-color: var(--gold-soft); color: var(--amber-strong); }
.alert.info { background: var(--jade-soft); border-color: var(--jade-soft); color: var(--jade-strong); }

/* tables */
.table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.table th, .table td { padding: var(--space-2) var(--space-3); text-align: left; vertical-align: top; border-bottom: 1px solid var(--rule); }
.table th { font-weight: 600; color: var(--ink-2); font-size: var(--fs-xs); text-transform: none; letter-spacing: 0.04em; background: var(--bg-sunken); }
.table tbody tr { transition: background .12s ease; }
.table tbody tr:hover { background: var(--bg-sunken); }
.table .link-cell { color: var(--jade); cursor: pointer; }
.table-scroll {
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.table-wide { min-width: 760px; }
.jobs-table { min-width: 920px; }
.job-toggle {
  width: 28px;
  min-height: 28px;
  padding: 0;
}
.job-drawer-row { display: none; }
.job-drawer-row.open { display: table-row; }
.job-drawer {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-card);
  border-left: 3px solid var(--jade);
}
.job-drawer .drawer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);
}
.job-drawer pre {
  max-height: 240px;
  overflow: auto;
  margin: 0;
  background: var(--bg-sunken);
  padding: var(--space-3);
  border-radius: var(--radius-1);
}

/* progress */
.progress { height: 8px; background: var(--bg-sunken); border-radius: var(--radius-pill); overflow: hidden; }
.progress-fill { height: 100%; background: var(--amber); transition: width .3s ease; }

/* command list (recommended commands) */
.command-list { display: flex; flex-direction: column; gap: var(--space-2); }
.command-list code {
  display: block;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-sunken);
  border-radius: var(--radius-1);
  color: var(--ink-1);
  white-space: pre-wrap;
}

/* ---------- page: dashboard / workspace shelf ---------- */
.shelf-stats { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.workspace-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4); }
.workspace-card {
  display: block;
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  color: var(--ink-1);
  text-decoration: none;
  transition: border-color .15s ease, transform .12s ease;
}
.workspace-card:hover { border-color: var(--jade); transform: translateY(-1px); }
.workspace-card .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); margin-bottom: var(--space-4); }
.workspace-card h3 { font-size: var(--fs-h2); }
.workspace-card .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.workspace-card .metric .k { display: block; font-size: var(--fs-xs); color: var(--ink-3); }
.workspace-card .metric .v { display: block; margin-top: 2px; font-size: var(--fs-lg); font-weight: 600; color: var(--ink-1); }
.workspace-card .metric .v.metric-small { font-size: var(--fs-sm); }
.workspace-card .metric.history { opacity: .6; }

.sidebar-job {
  margin-bottom: var(--space-2);
}
.sidebar-job.history { opacity: .6; }

/* ---------- page: workspace overview ---------- */
.overview-hero {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--space-5);
  align-items: stretch;
}
.next-action {
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.next-action .eyebrow { margin-bottom: 0; }
.next-action .hint { color: var(--ink-2); }
.next-action .cta-row { display: flex; gap: var(--space-2); margin-top: var(--space-2); flex-wrap: wrap; }

.metric-pair {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}
.metric-pair .tile {
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-4);
}
.metric-pair .tile .k { font-size: var(--fs-xs); color: var(--ink-3); }
.metric-pair .tile .v { font-size: var(--fs-display); font-weight: 600; color: var(--ink-1); font-family: var(--font-serif); }
.metric-pair .tile .sub { font-size: var(--fs-xs); color: var(--ink-3); }

.details-fold summary {
  cursor: pointer;
  font-size: var(--fs-sm);
  color: var(--ink-2);
  padding: var(--space-2) 0;
  list-style: none;
}
.details-fold summary::before { content: "▸"; margin-right: .35em; color: var(--ink-3); }
.details-fold[open] summary::before { content: "▾"; }

/* ---------- page: continue (cockpit) ---------- */
.readiness-primary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--bg-card);
}
.readiness-primary .copy { display: flex; flex-direction: column; gap: var(--space-1); }
.readiness-primary h3 { font-size: var(--fs-lg); }
.readiness-primary p { color: var(--ink-2); margin: 0; }
.readiness-status-row { margin-top: var(--space-3); }
.readiness-diagnostics { margin-top: var(--space-3); }
.continue-flow {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.flow-step {
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: var(--space-4);
}
.flow-step .step-mark {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--jade-soft);
  color: var(--jade-strong);
  font-family: var(--font-serif);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.flow-step.done .step-mark { background: var(--jade); color: #fff; }

/* ---------- page: chapters list ---------- */
.chapters-filter {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  align-items: center;
}
.chapters-filter input[type=search] {
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-1);
  min-width: 220px;
  background: var(--bg-card);
  font: inherit;
}
.filter-toggle .btn { border-radius: var(--radius-1); }
.filter-toggle .btn.active { background: var(--jade-soft); border-color: var(--jade); color: var(--jade-strong); }

/* ---------- page: chapter detail ---------- */
.chapter-meta-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}
.reading-body {
  max-width: var(--reading-w);
  margin: 0 auto;
  padding: var(--space-5) 0;
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  line-height: 1.95;
  color: var(--ink-1);
}
.reading-body p { margin: 0 0 1.1em; text-indent: 2em; }
.reading-body h1, .reading-body h2 { text-indent: 0; text-align: center; margin: 1.5em 0 .8em; }
.reading-body .jump-highlight { background-color: var(--gold-soft); transition: background-color 1.5s ease; }
.review-card {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 2fr;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--bg-card);
}
.review-card .name { font-family: var(--font-serif); font-size: var(--fs-lg); }
.review-card .verdict { margin-top: var(--space-1); }
.subscore-bar { display: flex; align-items: center; gap: var(--space-2); font-size: var(--fs-xs); color: var(--ink-2); }
.subscore-bar .label { width: 56px; }
.subscore-bar .track { flex: 1; height: 6px; background: var(--bg-sunken); border-radius: var(--radius-pill); overflow: hidden; }
.subscore-bar .track > i { display: block; height: 100%; background: var(--jade); }
.subscore-bar .val { width: 32px; text-align: right; }
.subscore-cell {
  text-align: center;
  font-family: var(--font-mono);
}
.subscore-cell-empty {
  color: var(--ink-3);
  background: var(--bg-card);
}
.subscore-cell-approve { background: var(--jade-soft); }
.subscore-cell-warn { background: var(--gold-soft); }
.subscore-cell-fail { background: var(--sienna-soft); }

.lint-group { border: 1px solid var(--rule); border-radius: var(--radius-2); background: var(--bg-card); overflow: hidden; }
.lint-group h4 { padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--rule); background: var(--bg-sunken); font-size: var(--fs-sm); }
.lint-group ul { list-style: none; padding: 0; margin: 0; }
.lint-group li { padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--rule); font-size: var(--fs-sm); display: flex; gap: var(--space-3); }
.lint-group li:last-child { border-bottom: 0; }
.lint-group li.link-cell { cursor: pointer; }
.lint-group li.link-cell:hover { background: var(--bg-sunken); }
.lint-group li .anchor { color: var(--ink-3); font-family: var(--font-mono); font-size: var(--fs-xs); }
.lint-group li .severity { color: var(--gold); font-size: var(--fs-xs); }
.lint-group li .severity.error { color: var(--sienna); }
.lint-group li .severity.warn { color: var(--gold); }

.advisor-item {
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-4);
}
.advisor-item .type { font-size: var(--fs-xs); color: var(--jade); text-transform: uppercase; letter-spacing: .04em; }
.advisor-item .section { font-family: var(--font-serif); font-size: var(--fs-lg); margin-top: 2px; }
.advisor-item .guidance { color: var(--ink-2); margin-top: var(--space-2); white-space: pre-wrap; }

/* ---------- page: jobs ---------- */
.job-row .trace {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
.copy-btn {
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: var(--radius-1);
  padding: 2px 6px;
  font-size: 11px;
  color: var(--ink-3);
  cursor: pointer;
}
.copy-btn:hover { color: var(--ink-1); background: var(--bg-sunken); }
.logs-tail {
  background: var(--bg-sunken);
  border: 1px solid var(--rule);
  border-radius: var(--radius-1);
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  max-height: 360px;
  overflow: auto;
  color: var(--ink-1);
}

/* ---------- wizard + settings (slim pages) ---------- */
.slim-shell {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-7) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.wizard-mode-card { margin: 0; }
.wizard-help-card {
  padding: var(--space-4);
  background: var(--bg-sunken);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
}
.wizard-help-card .eyebrow { margin-bottom: var(--space-2); }
.wizard-advanced { border-top: 1px solid var(--rule); padding-top: var(--space-2); }
.wizard-progress-actions {
  margin-top: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.wizard-progress-actions .cluster { justify-content: flex-start; }

/* confirm modal */
.modal-backdrop {
  position: fixed; inset: 0;
  background: var(--bg-overlay);
  display: flex; align-items: center; justify-content: center;
  z-index: 40;
  padding: var(--space-5);
}
.modal {
  width: 100%;
  max-width: 480px;
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.modal-header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--rule);
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
}
.modal-body { padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-3); }
.modal-footer {
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--rule);
  background: var(--bg-sunken);
  display: flex; justify-content: flex-end; gap: var(--space-2);
}

/* ---------- responsive ---------- */
@media (max-width: 1024px) {
  .overview-hero { grid-template-columns: 1fr; }
  .grid.cols-3, .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 768px) {
  .app { grid-template-columns: 1fr; }
  .sidebar {
    position: fixed;
    z-index: 31;
    top: 0;
    left: 0;
    width: min(82vw, 280px);
    max-width: 280px;
    height: 100vh;
    transform: translateX(-100%);
    transition: transform .18s ease;
    box-shadow: 8px 0 24px rgba(42, 37, 32, .12);
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-overlay.open {
    display: block;
    position: fixed;
    inset: 0;
    background: var(--bg-overlay);
    z-index: 30;
  }
  .app.no-context .nav-toggle { display: none; }
  .nav-toggle { display: inline-flex; flex: 0 0 36px; }
  .topbar {
    padding: var(--space-3) var(--space-4);
    gap: var(--space-2);
  }
  .topbar .breadcrumb {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    white-space: nowrap;
  }
  .breadcrumb a, .breadcrumb .here {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 42vw;
  }
  .topbar-menu-toggle { display: inline-flex; }
  .topbar-actions {
    display: none;
    position: absolute;
    right: 0;
    top: calc(100% + var(--space-2));
    min-width: 168px;
    padding: var(--space-2);
    background: var(--bg-card);
    border: 1px solid var(--rule);
    border-radius: var(--radius-2);
    box-shadow: 0 8px 24px rgba(42, 37, 32, .12);
    z-index: 25;
    flex-direction: column;
    align-items: stretch;
  }
  .topbar-actions.open { display: flex; }
  .topbar-actions .btn {
    width: 100%;
    justify-content: flex-start;
  }
  .table-scroll {
    margin: 0 calc(-1 * var(--space-4));
    padding: 0 var(--space-4) var(--space-2);
    background:
      linear-gradient(to right, var(--bg-card) 30%, rgba(255, 254, 251, 0)) left center / 36px 100% no-repeat local,
      linear-gradient(to left, var(--bg-card) 30%, rgba(255, 254, 251, 0)) right center / 36px 100% no-repeat local,
      radial-gradient(farthest-side at 0 50%, rgba(42, 37, 32, .18), rgba(42, 37, 32, 0)) left center / 12px 100% no-repeat scroll,
      radial-gradient(farthest-side at 100% 50%, rgba(42, 37, 32, .18), rgba(42, 37, 32, 0)) right center / 12px 100% no-repeat scroll;
  }
  .page { padding: var(--space-4); }
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .page-header h1 { font-size: var(--fs-h1); }
  .form-grid, .grid.cols-2, .form-grid-2 { grid-template-columns: 1fr; }
  .review-card { grid-template-columns: 1fr; }
}
"""


JS_DASHBOARD = """\
/* Single JS bundle, dispatches on window.PAGE_KIND.
 *
 * Page kinds:
 *   index               — workspace shelf at /
 *   workspace_overview  — /w/<name>
 *   continue            — /w/<name>/continue   (cockpit forms)
 *   chapters            — /w/<name>/chapters
 *   chapter_detail      — /w/<name>/chapter/<n>
 *   reviews             — /w/<name>/reviews
 *   plan                — /w/<name>/plan
 *   jobs                — /w/<name>/jobs
 *
 * Established identifiers are preserved verbatim so the existing
 * web test suite stays green:
 *   loadTabPanel, scheduleReadiness, readinessRequestSeq,
 *   writeBookJobRunning, readinessTimer, the
 *   ``submit.disabled = writeBookJobRunning || data.status === 'blocked'``
 *   expression.
 */
(function () {
  const ws = window.WORKSPACE_NAME || "";
  const pageKind = window.PAGE_KIND || "";
  const CTA_ACTIONS = {
    start_point_missing: {
      label: "未设置续写起点",
      action: "scroll_to_start_point",
      cta_label: "去设置起点",
      hint: "先选定从原作哪一章之后开始续写。",
    },
    outline_missing: {
      label: "缺少全书大纲",
      action: "go_plan",
      cta_label: "去计划页",
      hint: "先生成或检查全书走向，再进入章节续写。",
    },
    chapter_plan_missing: {
      label: "缺少章节计划",
      action: "run_plan_chapters",
      cta_label: "生成章节计划",
      hint: "续写需要本章计划；可以先用默认目标章数生成。",
    },
    retry_exhausted: {
      label: "已有草稿未通过",
      action: "retry_write_book",
      cta_label: "查看并重试",
      hint: "先查看失败原因，再用相同或调整后的参数重试。",
    },
  };
  const WRITE_PRESETS = {
    trial: { tier: "low", chapters: 1, max_retries: 1, budget_cny: 2, auto_advance: false },
    production: { tier: "mid", chapters: 1, max_retries: 2, budget_cny: 10, auto_advance: true },
    strict: { tier: "high", chapters: 1, max_retries: 3, budget_cny: 30, auto_advance: true },
  };

  // ---- shared helpers ----------------------------------------------------
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  async function fetchJson(url) {
    const res = await fetch(url);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }
  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }
  async function putJson(url, payload) {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
  }
  function wsUrl(suffix) {
    return "/api/workspace/" + encodeURIComponent(ws) + suffix;
  }
  function wsHref(suffix) {
    return "/w/" + encodeURIComponent(ws) + suffix;
  }
  let shellControlsBound = false;
  function initShellControls() {
    if (shellControlsBound) return;
    shellControlsBound = true;
    const sidebar = document.querySelector(".sidebar");
    const overlay = document.querySelector(".sidebar-overlay");
    const navToggle = document.querySelector("[data-sidebar-toggle]");
    const topbarToggle = document.querySelector("[data-topbar-menu-toggle]");
    const topbarActions = document.querySelector(".topbar-actions");
    if (topbarToggle && topbarActions && !topbarActions.textContent.trim()) {
      topbarToggle.hidden = true;
    }
    function closeSidebar() {
      if (sidebar) sidebar.classList.remove("open");
      if (overlay) overlay.classList.remove("open");
    }
    function closeTopbarMenu() {
      if (topbarActions) topbarActions.classList.remove("open");
    }
    if (navToggle && sidebar && overlay) {
      navToggle.addEventListener("click", function () {
        const open = !sidebar.classList.contains("open");
        sidebar.classList.toggle("open", open);
        overlay.classList.toggle("open", open);
        if (open) closeTopbarMenu();
      });
      overlay.addEventListener("click", closeSidebar);
      sidebar.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) closeSidebar();
      });
    }
    if (topbarToggle && topbarActions) {
      topbarToggle.addEventListener("click", function (ev) {
        ev.stopPropagation();
        const open = !topbarActions.classList.contains("open");
        topbarActions.classList.toggle("open", open);
        if (open) closeSidebar();
      });
      document.addEventListener("click", function (ev) {
        if (!ev.target.closest(".topbar-actions-wrap")) closeTopbarMenu();
      });
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeSidebar();
        closeTopbarMenu();
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) {
        closeSidebar();
        closeTopbarMenu();
      }
    });
  }
  function statusBadge(status) {
    const cls = (status || "blocked").toLowerCase();
    return '<span class="badge ' + escapeHtml(cls) + '">' + escapeHtml(status || "?") + "</span>";
  }
  function verdictBadge(verdict) {
    if (!verdict) return '<span class="badge no-dot">—</span>';
    const v = String(verdict).toLowerCase();
    const cls = v === "approve" ? "approve" : v === "reject" ? "reject" : "abstain";
    return '<span class="badge ' + cls + '">' + escapeHtml(verdict) + "</span>";
  }
  function typeBadge(type) {
    if (type === "drama") {
      return '<span class="badge no-dot badge-drama">短剧</span>';
    }
    return '<span class="badge no-dot badge-novel">小说</span>';
  }
  function mutedStatusBadge(status) {
    return '<span class="badge no-dot badge-muted">' + escapeHtml(status || "?") + "</span>";
  }
  function tableScroll(html) {
    return '<div class="table-scroll">' + html + "</div>";
  }
  function historicalJobStatus(status) {
    return ["lost", "failed", "blocked", "aborted", "budget_exceeded"].indexOf(status || "") >= 0;
  }
  function recentJobLabel(job) {
    if (!job) return "无";
    return (job.step || "?") + " · " + (job.status || "?");
  }
  function recentJobMetric(job) {
    const cls = historicalJobStatus(job && job.status) ? ' class="metric history"' : ' class="metric"';
    return '<div' + cls + '><span class="k">最近任务</span><span class="v metric-small">' +
      escapeHtml(recentJobLabel(job)) + "</span></div>";
  }
  function dramaProgressList(progress) {
    if (!progress || typeof progress !== "object") return [];
    const keys = ["station1", "station2", "station3", "station4"];
    return keys.map(function (key) { return progress[key]; }).filter(Boolean);
  }
  function dramaOverallStatus(progress) {
    const stations = dramaProgressList(progress);
    if (!stations.length) return "warn";
    const firstOpen = stations.find(function (s) { return s.status === "todo"; });
    if (firstOpen) return "warn";
    return "ready";
  }
  function ctaConfig(kind, fallback) {
    const base = CTA_ACTIONS[kind] || {};
    return {
      label: fallback && fallback.label || base.label || "需要处理",
      action: fallback && fallback.cta_action || base.action || "show_diagnostics",
      cta_label: fallback && fallback.cta_label || base.cta_label || "查看诊断",
      hint: base.hint || (fallback && fallback.raw) || "",
    };
  }
  function renderCtaButton(kind, fallback, cls) {
    const cfg = ctaConfig(kind, fallback || {});
    return '<button type="button" class="btn ' + escapeHtml(cls || "btn-primary") +
      '" data-cta-action="' + escapeHtml(cfg.action) + '">' + escapeHtml(cfg.cta_label) + "</button>";
  }
  let ctaActionsBound = false;
  function bindCtaActions() {
    if (ctaActionsBound) return;
    ctaActionsBound = true;
    document.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-cta-action]") : null;
      if (!btn) return;
      const action = btn.getAttribute("data-cta-action") || "";
      if (action === "go_plan") {
        window.location.href = wsHref("/plan");
        return;
      }
      if (action === "scroll_to_start_point") {
        scrollAndFocus("start-point-form", "start_point");
        return;
      }
      if (action === "run_plan_chapters") {
        scrollAndFocus("plan-form", "target_chapters");
        return;
      }
      if (action === "retry_write_book") {
        scrollAndFocus("write-book-form", "resume_from");
        return;
      }
      const details = document.querySelector("#readiness-panel details");
      if (details) {
        details.open = true;
        details.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
  function scrollAndFocus(formId, fieldName) {
    const form = document.getElementById(formId);
    if (!form) return;
    form.scrollIntoView({ behavior: "smooth", block: "start" });
    const field = form.elements && form.elements[fieldName];
    if (field && field.focus) setTimeout(function () { field.focus(); }, 250);
  }
  function skeleton(rows) {
    let out = '<div class="skeleton-block">';
    for (let i = 0; i < (rows || 3); i++) {
      const cls = i % 2 ? "skeleton row long" : "skeleton row short";
      out += '<div class="' + cls + '"></div>';
    }
    return out + "</div>";
  }
  function emptyState(title, body, ctaHtml) {
    return (
      '<div class="empty-state"><span class="ornament">✦</span>' +
      '<h3>' + escapeHtml(title) + '</h3>' +
      '<p class="muted">' + escapeHtml(body || "") + '</p>' +
      (ctaHtml ? '<div class="cta">' + ctaHtml + '</div>' : '') +
      '</div>'
    );
  }
  function copyButton(text) {
    return (
      '<button class="copy-btn" type="button" data-copy="' + escapeHtml(text) + '">复制</button>'
    );
  }
  function bindCopy(root) {
    (root || document).addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-copy]");
      if (!btn) return;
      const value = btn.getAttribute("data-copy") || "";
      if (navigator.clipboard) {
        navigator.clipboard.writeText(value).then(
          function () { btn.textContent = "✓"; setTimeout(() => { btn.textContent = "复制"; }, 900); },
          function () {}
        );
      }
    });
  }
  bindCopy(document);

  function showToast(msg, kind, options) {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const opts = options || {};
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : kind === "warn" ? " warn" : "");
    const text = document.createElement("span");
    text.textContent = msg;
    el.appendChild(text);
    if (opts.dismiss !== false) {
      const close = document.createElement("button");
      close.type = "button";
      close.className = "toast-dismiss";
      close.setAttribute("aria-label", "关闭通知");
      close.textContent = "×";
      close.addEventListener("click", function () { removeToast(el); });
      el.appendChild(close);
    }
    stack.appendChild(el);
    setTimeout(function () { removeToast(el); }, 5000);
  }
  function removeToast(el) {
    if (!el || !el.parentNode) return;
    el.style.transition = "opacity .4s ease";
    el.style.opacity = "0";
    setTimeout(function () { if (el.parentNode) el.remove(); }, 400);
  }
  window.setPendingToastAndNavigate = function (toast, url) {
    sessionStorage.setItem("__pending_toast", JSON.stringify(toast));
    setTimeout(function () {
      sessionStorage.removeItem("__pending_toast");
    }, 5000);
    window.location.href = url;
  };

  // ---- shared: chapter detail tab routing (hash deep-link) --------------
  // Keep in sync with chapter-detail and plan-view tab keys.
  const _ALLOWED_TAB_KEYS = [
    "body", "review", "lint", "advisor", "history",
    "chapters", "outline", "decisions",
    "setup", "hook", "storyboard", "characters",
  ];
  function bindHashTabs() {
    function activate(tab) {
      if (!tab) return;
      const list = tab.closest(".tab-list");
      if (!list) return;
      list.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const tabsRoot = list.parentElement;
      tabsRoot.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      const target = tabsRoot.querySelector("#tab-" + tab.dataset.tab);
      if (target) target.classList.add("active");
    }
    document.addEventListener("click", function (ev) {
      const tab = ev.target.closest(".tab");
      if (!tab) return;
      activate(tab);
      if (tab.dataset.tab) {
        history.replaceState(null, "", "#" + tab.dataset.tab);
      }
      loadTabPanel(tab.dataset.tab);
    });
    const params = new URLSearchParams(location.search || "");
    const initialFromQuery = params.get("step") || "";
    const initial = initialFromQuery || (location.hash || "").replace(/^#/, "");
    if (initial && _ALLOWED_TAB_KEYS.indexOf(initial) >= 0) {
      const t = document.querySelector('.tab[data-tab="' + initial + '"]');
      if (t) activate(t);
      if (initialFromQuery) history.replaceState(null, "", "#" + initial);
    }
  }

  // ``loadTabPanel`` identifier preserved (iter 026 test asserts it).
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

  // ===== page: index ======================================================
  async function initIndex() {
    const shelf = document.getElementById("workspace-shelf");
    const stats = document.getElementById("shelf-stats");
    if (!shelf) return;
    shelf.innerHTML = skeleton(4);
    try {
      const data = await fetchJson("/api/workspaces/overview");
      const items = data.workspaces || [];
      if (!items.length) {
        shelf.innerHTML = emptyState(
          "书架还是空的",
          shelf.dataset.empty || "上传一本 epub/txt 开始你的第一本书。",
          '<a class="btn btn-primary" href="/wizard">＋ 新建作品</a>'
        );
        if (stats) stats.innerHTML = "";
        return;
      }
      const ready = items.filter((w) => (w.readiness || {}).status === "ready").length;
      const warn = items.filter((w) => (w.readiness || {}).status === "warn").length;
      const blocked = items.filter((w) => (w.readiness || {}).status === "blocked").length;
      if (stats) {
        stats.innerHTML = [
          '<span class="badge no-dot">共 ' + items.length + " 本</span>",
          '<span class="badge ready">就绪 ' + ready + "</span>",
          '<span class="badge warn">警示 ' + warn + "</span>",
          '<span class="badge blocked">受阻 ' + blocked + "</span>",
        ].join("");
      }
      shelf.innerHTML = items.map(renderWorkspaceCard).join("");
    } catch (err) {
      shelf.innerHTML = '<div class="alert error">加载失败: ' + escapeHtml(err.message) + "</div>";
    }
  }
  function renderWorkspaceCard(w) {
    const type = w.type || "novel";
    const readiness = w.readiness || {};
    const status = type === "drama" ? dramaOverallStatus(w.drama_progress) : (readiness.status || "blocked");
    const blockers = readiness.blockers || [];
    const start = w.start_point && w.start_point.has_start_point
      ? (w.start_point.start_chapter_id || "已设置")
      : "未设置";
    const plan = w.plan && w.plan.exists ? (w.plan.chapters || 0) + " 章" : "缺失";
    const url = "/w/" + encodeURIComponent(w.name) + "/";
    const body = type === "drama" ? renderDramaWorkspaceMetrics(w) : renderNovelWorkspaceMetrics(w, start, plan);
    return (
      '<a class="workspace-card" href="' + url + '">' +
      '<div class="card-head">' +
      '<div><p class="eyebrow ornament">作品</p><h3>' + escapeHtml(w.name) + "</h3></div>" +
      '<div class="cluster">' +
      typeBadge(type) +
      statusBadge(status) +
      '</div>' +
      "</div>" +
      body +
      (type !== "drama" && blockers.length ? '<p class="alert error" style="margin-top:12px">' + escapeHtml(blockers[0]) + "</p>" : "") +
      "</a>"
    );
  }
  function renderNovelWorkspaceMetrics(w, start, plan) {
    return '<div class="metrics">' +
      '<div class="metric"><span class="k">原文章节</span><span class="v">' + (w.chapter_count || 0) + "</span></div>" +
      '<div class="metric"><span class="k">续写草稿</span><span class="v">' + (w.draft_count || 0) + "</span></div>" +
      '<div class="metric"><span class="k">评审通过</span><span class="v">' +
      (w.review_accepted || 0) + "/" + (w.review_total || 0) +
      "</span></div>" +
      '<div class="metric"><span class="k">起点</span><span class="v metric-small">' + escapeHtml(start) + "</span></div>" +
      '<div class="metric"><span class="k">计划</span><span class="v metric-small">' + escapeHtml(plan) + "</span></div>" +
      recentJobMetric(w.recent_job) +
      "</div>";
  }
  function renderDramaWorkspaceMetrics(w) {
    const stations = dramaProgressList(w.drama_progress);
    const stationHtml = stations.map(function (s, idx) {
      return '<div class="metric"><span class="k">站 ' + (idx + 1) + ' · ' + escapeHtml(s.label || s.id || "") +
        '</span><span class="v metric-small">' + escapeHtml(s.status || "?") + "</span></div>";
    }).join("");
    return '<div class="metrics">' +
      (stationHtml || '<div class="metric"><span class="k">站点</span><span class="v metric-small">未初始化</span></div>') +
      recentJobMetric(w.recent_job) +
      "</div>";
  }

  // ===== page: workspace overview =========================================
  async function initWorkspaceOverview() {
    const dramaProgress = document.getElementById("drama-overview-progress");
    if (dramaProgress) {
      initDeleteWorkspace();
      await loadDramaOverview();
      return;
    }
    const summary = document.getElementById("overview-summary");
    if (!summary) {
      initDeleteWorkspace();
      return;
    }
    if (summary) summary.innerHTML = skeleton(4);
    try {
      const data = await fetchJson("/api/workspaces/overview");
      const item = (data.workspaces || []).find((w) => w.name === ws) || {};
      renderOverview(item);
    } catch (err) {
      if (summary) summary.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
    loadOverviewDetails();
    initDeleteWorkspace();
  }
  function renderOverview(item) {
    const readiness = item.readiness || {};
    const statusEl = document.getElementById("overview-status-badge");
    if (statusEl) statusEl.innerHTML = statusBadge(readiness.status || "blocked");
    const summary = document.getElementById("overview-summary");
    if (summary) {
      summary.innerHTML =
        '<div class="tile"><span class="k">原文章节</span><span class="v">' + (item.chapter_count || 0) + "</span></div>" +
        '<div class="tile"><span class="k">续写草稿</span><span class="v">' + (item.draft_count || 0) + "</span></div>" +
        '<div class="tile"><span class="k">评审通过</span><span class="v">' +
        (item.review_accepted || 0) + '<span class="sub"> / ' + (item.review_total || 0) + '</span></span></div>' +
        '<div class="tile"><span class="k">计划章节</span><span class="v">' + ((item.plan || {}).chapters || 0) + "</span></div>";
    }
    const nextAction = document.getElementById("overview-next-action");
    if (nextAction) {
      const status = readiness.status || "blocked";
      const blockers = readiness.blockers || [];
      const commands = readiness.recommended_commands || [];
      const start = item.start_point && item.start_point.has_start_point
        ? (item.start_point.start_chapter_id || "（已设置）")
        : "未设置";
      let hint = "";
      let cta = '<a class="btn btn-primary" href="/w/' + encodeURIComponent(ws) + '/continue">▸ 进入续写</a>';
      if (status === "ready") {
        hint = "一切就绪。可以直接续写下一章。";
      } else if (status === "warn") {
        hint = "可以续写，但有可关注的提示。";
      } else {
        hint = blockers[0] || "存在阻断项，需先处理。";
        cta = '<a class="btn btn-secondary" href="/w/' + encodeURIComponent(ws) + '/continue">查看待办</a>';
      }
      nextAction.innerHTML =
        '<p class="eyebrow ornament">下一步</p>' +
        '<h2>' + hint + '</h2>' +
        '<p class="hint">起点：' + escapeHtml(start) + '　·　计划：' + ((item.plan || {}).chapters || 0) + ' 章</p>' +
        '<div class="cta-row">' + cta +
        (commands.length ? '<a class="btn btn-ghost" href="#commands">查看建议命令</a>' : "") + '</div>';
    }
    const blockersBox = document.getElementById("overview-blockers");
    if (blockersBox) {
      const blockers = readiness.blockers || [];
      const warnings = readiness.warnings || [];
      const commands = readiness.recommended_commands || [];
      const parts = [];
      if (blockers.length) {
        parts.push(
          '<div class="alert error"><strong>阻断：</strong>' +
          blockers.map(escapeHtml).join("<br>") + "</div>"
        );
      }
      if (warnings.length) {
        parts.push(
          '<div class="alert warn"><strong>警示：</strong>' +
          warnings.map(escapeHtml).join("<br>") + "</div>"
        );
      }
      if (commands.length) {
        parts.push(
          '<div id="commands" class="command-list">' +
          '<p class="eyebrow">建议命令</p>' +
          commands.map((c) => "<code>" + escapeHtml(c) + "</code>").join("") +
          "</div>"
        );
      }
      blockersBox.innerHTML = parts.join("") ||
        '<div class="alert info">没有阻断项也没有警示，可以继续写作。</div>';
    }
  }
  async function loadOverviewDetails() {
    const statusBox = document.getElementById("overview-detail-status");
    const costBox = document.getElementById("overview-detail-cost");
    if (statusBox) {
      statusBox.innerHTML = skeleton(4);
      fetchJson(wsUrl("/status"))
        .then((d) => { statusBox.innerHTML = renderKV(d); })
        .catch((e) => { statusBox.innerHTML = '<div class="alert error">' + escapeHtml(e.message) + "</div>"; });
    }
    if (costBox) {
      costBox.innerHTML = skeleton(3);
      fetchJson(wsUrl("/cost"))
        .then((d) => { costBox.innerHTML = renderKV(d); })
        .catch((e) => { costBox.innerHTML = '<div class="alert error">' + escapeHtml(e.message) + "</div>"; });
    }
  }
  function renderKV(obj) {
    if (!obj || typeof obj !== "object") return '<p class="muted">(empty)</p>';
    const rows = [];
    for (const [k, v] of Object.entries(obj)) {
      const val = typeof v === "object" ? JSON.stringify(v) : String(v);
      rows.push('<div class="k">' + escapeHtml(k) + '</div><div class="v">' + escapeHtml(val) + "</div>");
    }
    return rows.length ? '<div class="kv-list compact">' + rows.join("") + "</div>" : '<p class="muted">(empty)</p>';
  }

  async function loadDramaOverview() {
    const box = document.getElementById("drama-overview-progress");
    const headline = document.getElementById("drama-next-headline");
    if (!box) return;
    box.innerHTML = skeleton(4);
    try {
      const data = await fetchJson(wsUrl("/drama/progress"));
      box.innerHTML = (data.stations || []).map(function (s) {
        const cls = s.status === "done" ? "ready" :
          s.status === "locked" ? "blocked" : "warn";
        return '<div class="card"><div class="card-body">' +
          '<div class="cluster">' +
          '<span class="eyebrow ornament">' + escapeHtml(s.id) + "</span>" +
          '<span class="badge ' + cls + '">' + escapeHtml(s.status) + "</span></div>" +
          '<h3>' + escapeHtml(s.label) + "</h3>" +
          "</div></div>";
      }).join("");
      const todo = (data.stations || []).find((s) => s.status === "todo");
      if (headline) {
        headline.textContent = todo
          ? "下一步：完成「" + todo.label + "」"
          : "前 2 站已完成。分镜与角色设定将在后续版本上线";
      }
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
      if (headline) headline.textContent = "载入失败";
    }
  }

  function initDeleteWorkspace() {
    const btn = document.getElementById("delete-workspace-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      showDeleteModal(ws);
    });
  }

  function showDeleteModal(name) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
      '<div class="modal-header" id="modal-title">删除作品 《' + escapeHtml(name) + '》</div>' +
      '<div class="modal-body">' +
      '<p>这一步会把整个工作区移动到 <code>workspaces/_trash/</code>，' +
      '并不会立即从磁盘 rm。要彻底清理需要你手动删除 trash 目录。</p>' +
      '<p>为了避免误删，请在下方输入 <strong>' + escapeHtml(name) + '</strong> 以确认。</p>' +
      '<div class="field">' +
      '<label>workspace 名</label>' +
      '<input type="text" id="modal-confirm-input" autocomplete="off" placeholder="' +
      escapeHtml(name) + '">' +
      '</div>' +
      '<div id="modal-error"></div>' +
      '</div>' +
      '<div class="modal-footer">' +
      '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
      '<button type="button" class="btn btn-danger" id="modal-confirm-btn" disabled>确认删除</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(backdrop);
    const input = backdrop.querySelector("#modal-confirm-input");
    const confirmBtn = backdrop.querySelector("#modal-confirm-btn");
    const errBox = backdrop.querySelector("#modal-error");
    function closeModal() {
      document.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
    }
    function onKeyDown(ev) {
      if (ev.key === "Escape") closeModal();
    }
    input.addEventListener("input", function () {
      confirmBtn.disabled = input.value !== name;
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) {
        closeModal();
      }
    });
    document.addEventListener("keydown", onKeyDown);
    confirmBtn.addEventListener("click", async function () {
      confirmBtn.disabled = true;
      errBox.innerHTML = '<div class="alert info">正在移动到 trash…</div>';
      try {
        const data = await postJson("/api/workspace/" + encodeURIComponent(name) + "/delete",
          { confirm: name });
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "已删除 《" + name + "》 → " + data.trashed_to },
          "/"
        );
      } catch (err) {
        errBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
        confirmBtn.disabled = false;
      }
    });
    setTimeout(() => input.focus(), 0);
  }

  // ===== page: plan viewer ==============================================
  async function initPlan() {
    bindHashTabs();
    const chBox = document.querySelector('[data-plan-pane="chapters"]');
    const olBox = document.querySelector('[data-plan-pane="outline"]');
    const dcBox = document.querySelector('[data-plan-pane="decisions"]');
    const sumBox = document.getElementById("plan-summary");
    if (chBox) chBox.innerHTML = skeleton(4);
    if (olBox) olBox.innerHTML = skeleton(3);
    if (dcBox) dcBox.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(wsUrl("/plan"));
      renderPlanSummary(sumBox, data);
      renderPlanChapters(chBox, data.plan || {}, data.draft_chapters || [], data.draft_verdicts || {});
      renderOutlineMarkdown(olBox, data.outline_md || "");
      renderDecisions(dcBox, data.decisions || {});
    } catch (err) {
      if (chBox) chBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
      if (olBox) olBox.innerHTML = "";
      if (dcBox) dcBox.innerHTML = "";
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
  function renderPlanChapters(box, plan, draftChapters, draftVerdicts) {
    if (!box) return;
    const chapters = Array.isArray(plan && plan.chapters) ? plan.chapters : [];
    const arc = (plan && plan.overall_arc) || "";
    if (!chapters.length) {
      box.innerHTML = '<p class="muted">尚无章节计划。先在「续写」里生成一份。</p>';
      return;
    }
    const draftArr = Array.isArray(draftChapters) ? draftChapters : [];
    const draftSet = new Set(draftArr.map((n) => Number(n)));
    const arcHtml = arc
      ? '<div class="alert info" style="margin-bottom:16px"><strong>整体走向：</strong>' + escapeHtml(arc) + '</div>'
      : '';
    const cards = chapters.map(function (c) {
      const no = Number(c.chapter_no || 0);
      const written = draftSet.has(no);
      const verdict = draftVerdicts && draftVerdicts[String(no)];
      const head =
        '<div class="card-header" style="align-items:flex-start">' +
        '<div><p class="eyebrow ornament">第 ' + escapeHtml(String(c.chapter_no || "?")) + ' 章</p>' +
        '<h3>' + escapeHtml(c.title || "(无标题)") + '</h3></div>' +
        '<div class="cluster">' +
        (written ? '<span class="badge ready">已写</span>' : '<span class="badge no-dot">未写</span>') +
        (written && verdict ? verdictBadge(verdict) : '') +
        '</div></div>';
      const events = (Array.isArray(c.key_events) ? c.key_events : []).map(function (e) {
        return '<li>' + escapeHtml(e) + '</li>';
      }).join("");
      const rels = (Array.isArray(c.relationships_in_play) ? c.relationships_in_play : []).map(function (r) {
        return '<span class="badge no-dot">' + escapeHtml(typeof r === "string" ? r : JSON.stringify(r)) + '</span>';
      }).join(" ");
      const body =
        '<div class="card-body">' +
        (c.opening_scene ? '<p><strong>开场：</strong>' + escapeHtml(c.opening_scene) + '</p>' : '') +
        (events ? '<div><strong>关键事件</strong><ul>' + events + '</ul></div>' : '') +
        (rels ? '<div><strong>涉及关系</strong><div class="cluster" style="margin-top:6px">' + rels + '</div></div>' : '') +
        (c.ending_hook ? '<p><strong>结尾钩子：</strong>' + escapeHtml(c.ending_hook) + '</p>' : '') +
        (c.plot_purpose ? '<p class="muted"><strong>定位：</strong>' + escapeHtml(c.plot_purpose) + '</p>' : '') +
        (c.target_chinese_chars ? '<p class="muted">目标字数：' + escapeHtml(String(c.target_chinese_chars)) + '</p>' : '') +
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
    box.innerHTML = '<div class="card"><div class="card-body reading-body">' + _mdToHtml(md) + '</div></div>';
  }
  function _mdToHtml(md) {
    const lines = md.replace(/\\r\\n/g, "\\n").split("\\n");
    const out = [];
    let inList = false;
    function closeList() { if (inList) { out.push("</ul>"); inList = false; } }
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].replace(/\\s+$/, "");
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
    const votes = Array.isArray(decisions && decisions.votes) ? decisions.votes : [];
    if (!votes.length) {
      box.innerHTML = '<p class="muted">decisions.json 不存在或没有 votes。</p>';
      return;
    }
    const head =
      '<div class="alert info" style="margin-bottom:16px">' +
      '<strong>主题：</strong>' + escapeHtml(decisions.topic || "(未命名)") +
      '　·　<strong>聚合：</strong>' + escapeHtml(decisions.aggregation_method || "—") +
      '　·　<strong>transcript 段：</strong>' + escapeHtml(String(decisions.transcript_items || 0)) +
      '</div>';
    const cards = votes.map(function (v) {
      const fors = (v["for"] || []).join("；") || "—";
      const againsts = (v.against || []).join("；") || "—";
      const agents = (Array.isArray(v.agent_votes) ? v.agent_votes : []).map(function (a) {
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
        (agents ? '<details><summary class="muted">agent_votes (' + (v.agent_votes || []).length + ')</summary><ul>' + agents + '</ul></details>' : '') +
        '</div></div>'
      );
    }).join("");
    box.innerHTML = head + cards;
  }

  // ===== page: trash =====================================================
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
          '<td>' + escapeHtml(String(e.size_mb)) + ' MB</td>' +
          '<td>' + escapeHtml(String(e.file_count)) + '</td>' +
          '<td class="cluster">' +
          '<button class="btn btn-secondary btn-sm" data-trash-restore="' + escapeHtml(e.entry) + '">restore</button>' +
          '<button class="btn btn-danger btn-sm" data-trash-purge="' + escapeHtml(e.entry) + '">purge</button>' +
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
    function onKey(ev) {
      if (ev.key === "Escape") close();
    }
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
        await postJson("/api/trash/" + encodeURIComponent(entry) + "/purge", { confirm: entry });
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

  // ===== page: continue (start-point + plan + write-book cockpit) =========
  // Iter 026 / 030 identifiers preserved: scheduleReadiness,
  // readinessRequestSeq, writeBookJobRunning, readinessTimer + the
  // 'submit.disabled = writeBookJobRunning || data.status === "blocked"'
  // expression.
  let readinessTimer = null;
  let readinessRequestSeq = 0;
  let writeBookJobRunning = false;

  async function initContinue() {
    bindCtaActions();
    bindStartPoint();
    bindPlan();
    bindWriteBook();
    await populateStartPointSelect();
    await refreshReadiness();
    await refreshRecentJobsSidebar();
  }
  async function populateStartPointSelect() {
    const select = document.getElementById("start-point-select");
    if (!select) return;
    try {
      const [manifestData, startData] = await Promise.all([
        fetchJson(wsUrl("/manifest")),
        fetchJson(wsUrl("/start-point")),
      ]);
      const chapters = manifestData.chapters || [];
      const current = (startData.start_point || {}).start_chapter_id ||
        (((startData.start_point || {}).manifest || {}).volume_id) || "";
      const byVolume = new Map();
      for (const ch of chapters) {
        const volume = ch.volume_id || "unknown";
        if (!byVolume.has(volume)) byVolume.set(volume, []);
        byVolume.get(volume).push(ch);
      }
      let html = '<option value="">— 选择续写起点 —</option>';
      for (const [volume, entries] of byVolume.entries()) {
        html += '<optgroup label="' + escapeHtml(volume) + '">';
        html += '<option value="' + escapeHtml(volume) + '">卷末: ' + escapeHtml(volume) + "</option>";
        for (const ch of entries) {
          html += '<option value="' + escapeHtml(ch.chapter_id || "") + '">' +
            escapeHtml(ch.chapter_id || "") + " · " + escapeHtml(ch.title || "") + "</option>";
        }
        html += "</optgroup>";
      }
      select.innerHTML = html;
      if (current) select.value = current;
    } catch (err) {
      select.innerHTML = '<option>载入失败</option>';
    }
  }
  function bindStartPoint() {
    const form = document.getElementById("start-point-form");
    if (!form) return;
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const value = form.elements.start_point.value;
      const box = document.getElementById("start-point-status");
      if (!box) return;
      if (!value) {
        box.innerHTML = '<div class="alert warn">请先选择一个起点</div>';
        return;
      }
      box.innerHTML = '<div class="alert info">正在保存…</div>';
      try {
        const data = await postJson(wsUrl("/start-point"), { start_point: value });
        const sp = (data.start_point || {}).start_chapter_id || value;
        box.innerHTML = '<div class="alert info">已保存起点：' + escapeHtml(sp) + "</div>";
        await refreshReadiness();
      } catch (err) {
        box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
      }
    });
  }
  function bindPlan() {
    const form = document.getElementById("plan-form");
    if (!form) return;
    const submit = document.getElementById("plan-submit");
    const box = document.getElementById("plan-status");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      box.innerHTML = '<div class="alert info">正在生成计划…</div>';
      try {
        const target = Number(form.elements.target_chapters.value || 5);
        const data = await postJson(wsUrl("/run"), {
          step: "plan-chapters",
          params: { target_chapters: target },
        });
        await pollJob(data.job_id, box, submit, async () => {
          await refreshReadiness();
        });
      } catch (err) {
        box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
        submit.disabled = false;
      }
    });
  }
  function bindWritePresets(form) {
    const toggle = document.getElementById("write-preset-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-write-preset]");
      if (!btn) return;
      const preset = WRITE_PRESETS[btn.getAttribute("data-write-preset") || ""];
      if (!preset) return;
      toggle.querySelectorAll("[data-write-preset]").forEach(function (item) {
        item.classList.toggle("active", item === btn);
      });
      if (form.elements.tier) form.elements.tier.value = preset.tier;
      if (form.elements.chapters) form.elements.chapters.value = String(preset.chapters);
      if (form.elements.max_retries) form.elements.max_retries.value = String(preset.max_retries);
      if (form.elements.budget_cny) form.elements.budget_cny.value = String(preset.budget_cny);
      if (form.elements.auto_advance) form.elements.auto_advance.checked = Boolean(preset.auto_advance);
      scheduleReadiness();
    });
  }
  function bindWriteBook() {
    const form = document.getElementById("write-book-form");
    if (!form) return;
    const submit = document.getElementById("write-book-submit");
    const jobBox = document.getElementById("write-book-status");
    bindWritePresets(form);
    if (form.elements.resume_from) {
      form.elements.resume_from.addEventListener("input", function () {
        form.elements.resume_from.dataset.userEdited = "1";
      });
    }
    form.addEventListener("input", scheduleReadiness);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (readinessTimer) { clearTimeout(readinessTimer); readinessTimer = null; }
      writeBookJobRunning = true;
      submit.disabled = true;
      jobBox.innerHTML = '<div class="alert info">starting…</div>';
      const params = {
        chapters: Number(form.elements.chapters.value || 1),
        resume_from: Number(form.elements.resume_from.value || 1),
        max_retries: Number(form.elements.max_retries.value || 2),
        replan_every: Number(form.elements.replan_every.value || 0),
        budget_cny: Number(form.elements.budget_cny.value || 0),
        min_confidence: Number(form.elements.min_confidence.value || 0.7),
        tier: form.elements.tier ? form.elements.tier.value || "mid" : "mid",
        auto_advance: Boolean(form.elements.auto_advance.checked),
        require_start_point: true,
        require_plan: true,
        require_external_review: true,
      };
      try {
        const data = await postJson(wsUrl("/run"), { step: "write-book", params });
        await pollJob(data.job_id, jobBox, submit, async () => {
          writeBookJobRunning = false;
          await refreshReadiness();
          await refreshRecentJobsSidebar();
        });
      } catch (err) {
        writeBookJobRunning = false;
        jobBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
        submit.disabled = false;
      }
    });
  }
  function scheduleReadiness() {
    if (readinessTimer) clearTimeout(readinessTimer);
    readinessTimer = setTimeout(() => {
      readinessTimer = null;
      refreshReadiness();
    }, 500);
  }
  async function refreshReadiness() {
    const form = document.getElementById("write-book-form");
    const panel = document.getElementById("readiness-panel");
    const pill = document.getElementById("readiness-pill");
    const submit = document.getElementById("write-book-submit");
    if (!form || !panel) return;
    const chapters = form.elements.chapters ? form.elements.chapters.value || "1" : "1";
    const resumeFrom = form.elements.resume_from ? form.elements.resume_from.value || "1" : "1";
    const replanEvery = form.elements.replan_every ? form.elements.replan_every.value || "0" : "0";
    const requestSeq = ++readinessRequestSeq;
    try {
      const url = wsUrl("/readiness?chapters=" + encodeURIComponent(chapters) +
        "&resume_from=" + encodeURIComponent(resumeFrom) +
        "&replan_every=" + encodeURIComponent(replanEvery));
      const data = await fetchJson(url);
      if (requestSeq !== readinessRequestSeq) return;
      const nextChapter = Number(data.next_unapproved_chapter || 0);
      if (form.elements.resume_from && nextChapter > 0 &&
          form.elements.resume_from.dataset.userEdited !== "1" &&
          Number(form.elements.resume_from.value || 0) !== nextChapter) {
        form.elements.resume_from.value = String(nextChapter);
        refreshReadiness();
        return;
      }
      panel.innerHTML = renderReadinessPanel(data);
      if (pill) pill.innerHTML = statusBadge(data.status || "blocked");
      if (submit) submit.disabled = writeBookJobRunning || data.status === 'blocked';
    } catch (err) {
      if (requestSeq !== readinessRequestSeq) return;
      panel.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
      if (submit) submit.disabled = true;
    }
  }
  function renderReadinessPanel(data) {
    const blockers = data.blockers || [];
    const warnings = data.warnings || [];
    const commands = data.recommended_commands || [];
    const status = data.status || "?";
    const primary = data.primary_blocker || null;
    const kind = primary ? primary.kind : "";
    const cfg = ctaConfig(kind, primary || {});
    let html = '<div class="readiness-primary">' +
      '<div class="copy">' +
      '<p class="eyebrow ornament">下一步</p>' +
      '<h3>' + escapeHtml(status === "blocked" ? cfg.label : status === "warn" ? "可以续写，但有提示" : "续写入口已就绪") + "</h3>" +
      '<p>' + escapeHtml(status === "blocked" ? (cfg.hint || primary.raw || "请先处理阻断项。") : status === "warn" ? "建议看一眼诊断提示，但不影响开始写作。" : "参数与前置产物都已通过检查。") + "</p>" +
      "</div>" +
      '<div class="cluster">' +
      (status === "blocked" ? renderCtaButton(kind, primary || {}, "btn-primary") : '<button type="submit" form="write-book-form" class="btn btn-primary">开始续写</button>') +
      "</div>" +
      "</div>";
    html += '<div class="kv-list compact readiness-status-row">' +
      '<div class="k">status</div><div class="v">' + statusBadge(status) + "</div>" +
      '<div class="k">chapters</div><div class="v">' + escapeHtml(String(data.chapters || "?")) + "</div>" +
      '<div class="k">resume_from</div><div class="v">' + escapeHtml(String(data.resume_from || "?")) + "</div>" +
      '<div class="k">next</div><div class="v">' + escapeHtml(String(data.next_unapproved_chapter || "—")) + "</div>" +
      '<div class="k">plan_window</div><div class="v">' + escapeHtml(String(data.plan_window || "?")) + "</div>" +
      "</div>";
    const details = [];
    if (blockers.length) details.push('<div class="alert error">' + blockers.map(escapeHtml).join("<br>") + "</div>");
    if (warnings.length) details.push('<div class="alert warn">' + warnings.map(escapeHtml).join("<br>") + "</div>");
    if (commands.length) {
      details.push('<div class="command-list">' +
        commands.map((c) => "<code>" + escapeHtml(c) + "</code>").join("") + "</div>");
    }
    html += '<details class="details-fold readiness-diagnostics"><summary>诊断详情</summary>' +
      (details.join("") || '<div class="alert info">没有阻断项也没有警示。</div>') +
      "</details>";
    return html;
  }
  async function refreshRecentJobsSidebar() {
    const box = document.getElementById("recent-jobs");
    if (!box) return;
    try {
      const data = await fetchJson(wsUrl("/jobs/recent?n=3"));
      const items = data.jobs || [];
      if (!items.length) {
        box.innerHTML = '<p class="muted">尚无历史任务</p>';
        return;
      }
      const current = items.filter(function (job) { return !historicalJobStatus(job.status); });
      const history = items.filter(function (job) { return historicalJobStatus(job.status); });
      const groups = [];
      if (current.length) {
        groups.push('<div class="sidebar-section"><h4>当前 / 最近完成</h4>' + current.map(renderSidebarJob).join("") + "</div>");
      }
      if (history.length) {
        groups.push('<div class="sidebar-section"><h4>历史</h4>' + history.map(renderSidebarJob).join("") + "</div>");
      }
      box.innerHTML = groups.join("") || '<p class="muted">尚无历史任务</p>';
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }
  function renderSidebarJob(job) {
    const isHistory = historicalJobStatus(job.status);
    return '<div class="kv-list compact sidebar-job' + (isHistory ? " history" : "") + '">' +
      '<div class="k">step</div><div class="v">' + escapeHtml(job.step || "?") + "</div>" +
      '<div class="k">status</div><div class="v">' + (isHistory ? mutedStatusBadge(job.status || "?") : statusBadge(job.status || "?")) + "</div>" +
      '<div class="k">job</div><div class="v"><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code></div>" +
      (jobActionableSummary(job) ? '<div class="k">note</div><div class="v">' + escapeHtml(jobActionableSummary(job).slice(0, 120)) + "</div>" : "") +
      "</div>";
  }
  function jobBlockedDetail(job) {
    const fb = job.result_summary && job.result_summary.first_blocked;
    if (!fb) return null;
    return { chapter: fb.chapter, reason: fb.reason, error: fb.error, status: fb.status };
  }
  function jobFailureLine(job) {
    const detail = jobBlockedDetail(job);
    if (detail && (detail.reason || detail.error)) {
      return [detail.chapter ? `ch${detail.chapter}` : null, detail.reason, detail.error]
        .filter(Boolean).join(' · ');
    }
    const summaryError = job.result_summary && job.result_summary.error;
    if (summaryError) return String(summaryError).split('\\n')[0];
    return (job.error || '').split('\\n')[0];
  }
  function jobActionableSummary(job) {
    const status = job.status || "?";
    const icons = {
      succeeded: "✓",
      blocked: "!",
      failed: "!",
      lost: "?",
      running: "…",
      pending: "…",
      aborted: "!",
      budget_exceeded: "¥",
    };
    const detail = jobBlockedDetail(job);
    const reason = detail && detail.reason ? detail.reason : "";
    const line = jobFailureLine(job);
    const icon = icons[status] || "•";
    if (status === "succeeded") return icon + " succeeded" + (job.result_summary && job.result_summary.snapshot_path ? " · snapshot ready" : "");
    if (reason) return icon + " " + status + " · " + reason;
    if (line) return icon + " " + status + " · " + line;
    return icon + " " + status;
  }
  function jobActionKind(job) {
    const detail = jobBlockedDetail(job);
    const reason = detail && detail.reason ? detail.reason : "";
    if (CTA_ACTIONS[reason]) return reason;
    const partial = job.result_summary && job.result_summary.partial;
    if (partial && partial.chapter) return "retry_exhausted";
    if (job.status === "failed" || job.status === "blocked" || job.status === "budget_exceeded") return "retry_exhausted";
    return "";
  }
  function resultSummaryRows(summary) {
    if (!summary || typeof summary !== "object") return '<p class="muted">无 result_summary。</p>';
    return '<div class="kv-list compact">' + Object.keys(summary).sort().map(function (key) {
      const value = summary[key];
      const rendered = value && typeof value === "object"
        ? "<pre>" + escapeHtml(JSON.stringify(value, null, 2)) + "</pre>"
        : escapeHtml(String(value == null ? "—" : value));
      return '<div class="k">' + escapeHtml(key) + '</div><div class="v">' + rendered + '</div>';
    }).join("") + "</div>";
  }
  function jobChapterNumber(job) {
    const partial = job.result_summary && job.result_summary.partial;
    if (partial && partial.chapter) return Number(partial.chapter);
    const blocked = job.result_summary && job.result_summary.first_blocked;
    if (blocked && blocked.chapter) return Number(blocked.chapter);
    const params = job.params || {};
    if (params.resume_from) return Number(params.resume_from);
    return 0;
  }
  function renderJobPageCta(kind) {
    if (!kind) return "";
    const cfg = ctaConfig(kind, {});
    const target = kind === "outline_missing" ? wsHref("/plan") : wsHref("/continue");
    return '<a class="btn btn-secondary btn-sm" href="' + target + '">' + escapeHtml(cfg.cta_label) + "</a>";
  }
  function renderJobDrawer(job) {
    const summary = job.result_summary || {};
    const partial = summary.partial || null;
    const chapter = jobChapterNumber(job);
    const actionKind = jobActionKind(job);
    const actions = [];
    if (partial && partial.chapter) {
      actions.push('<button type="button" class="btn btn-secondary btn-sm" data-job-partial="' + escapeHtml(String(partial.chapter)) + '">查看 partial draft</button>');
    }
    if (job.status === "succeeded" && chapter) {
      actions.push('<a class="btn btn-secondary btn-sm" href="' + wsHref("/chapter/" + chapter) + '">查看章节</a>');
    }
    if (actionKind) actions.push(renderJobPageCta(actionKind));
    if (job.status !== "running" && job.status !== "pending") {
      actions.push('<button type="button" class="btn btn-primary btn-sm" data-job-retry="' + escapeHtml(job.job_id || "") + '">用相同参数重试</button>');
    }
    return '<div class="job-drawer">' +
      '<div class="drawer-grid">' +
      '<div class="kv-list compact">' +
      '<div class="k">summary</div><div class="v">' + escapeHtml(jobActionableSummary(job)) + '</div>' +
      '<div class="k">trace_id</div><div class="v">' + escapeHtml(job.trace_id || "—") + (job.trace_id ? " " + copyButton(job.trace_id) : "") + '</div>' +
      '<div class="k">snapshot_path</div><div class="v">' + escapeHtml(summary.snapshot_path || "—") + '</div>' +
      '<div class="k">partial</div><div class="v">' + (partial && partial.chapter ? '<button type="button" class="copy-btn" data-job-partial="' + escapeHtml(String(partial.chapter)) + '">chapter_' + String(partial.chapter).padStart(2, "0") + ".partial.md</button>" : "—") + '</div>' +
      '</div>' +
      '<div class="stack">' +
      '<p class="eyebrow">恢复动作</p>' +
      '<div class="cluster">' + (actions.join("") || '<span class="muted">暂无动作</span>') + '</div>' +
      '</div>' +
      '</div>' +
      '<details class="details-fold"><summary>完整 result_summary</summary>' + resultSummaryRows(summary) + '</details>' +
      '</div>';
  }
  function openPartialPreview(chapter) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
      '<div class="modal-header">partial draft · chapter ' + escapeHtml(chapter) + '</div>' +
      '<div class="modal-body"><div class="alert info">正在载入…</div></div>' +
      '<div class="modal-footer">' +
      '<button type="button" class="btn btn-ghost" data-modal-close>关闭</button>' +
      '</div></div>';
    document.body.appendChild(backdrop);
    const body = backdrop.querySelector(".modal-body");
    const footer = backdrop.querySelector(".modal-footer");
    function close() { backdrop.remove(); }
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
    });
    fetchJson(wsUrl("/draft/" + encodeURIComponent(chapter) + "?variant=partial")).then(function (data) {
      const text = data.content || "";
      const preview = text.length > 2000 ? text.slice(0, 2000) + "\\n…" : text;
      const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      const href = URL.createObjectURL(blob);
      body.innerHTML = '<pre>' + escapeHtml(preview || "（空）") + "</pre>";
      footer.innerHTML =
        '<a class="btn btn-secondary" download="chapter_' + String(data.chapter || chapter).padStart(2, "0") + '.partial.md" href="' + href + '">下载完整</a>' +
        '<button type="button" class="btn btn-ghost" data-modal-close>关闭</button>';
    }).catch(function (err) {
      body.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    });
  }
  async function retryJob(job, btn) {
    if (!job) return;
    if (btn) btn.disabled = true;
    try {
      const data = await postJson(wsUrl("/run"), { step: job.step, params: job.params || {} });
      showToast("已重新启动：" + (job.step || "job"), "info");
      if (data && data.job_id) setTimeout(function () { initJobs(); }, 500);
    } catch (err) {
      showToast("重试失败：" + err.message, "error");
      if (btn) btn.disabled = false;
    }
  }
  async function pollJob(jobId, box, submit, afterDone) {
    while (true) {
      let job;
      try {
        job = await fetchJson(wsUrl("/job/" + jobId));
      } catch (err) {
        box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
        if (submit) submit.disabled = false;
        return;
      }
      const pct = Math.round((job.progress || 0) * 100);
      const failureLine = jobFailureLine(job);
      box.innerHTML =
        '<div class="kv-list compact">' +
        '<div class="k">job</div><div class="v"><code>' + escapeHtml(jobId) + "</code></div>" +
        '<div class="k">status</div><div class="v">' + statusBadge(job.status || "?") + "</div>" +
        '<div class="k">step</div><div class="v">' + escapeHtml(job.current_step || "?") + "</div>" +
        '<div class="k">progress</div><div class="v">' + pct + "%</div>" +
        "</div>" +
        '<div class="progress"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        (failureLine ? '<div class="alert error" style="margin-top:8px">' + escapeHtml(failureLine) +
          (job.trace_id ? ' <code>trace=' + escapeHtml(job.trace_id) + '</code>' : '') + "</div>" : "");
      const terminal = ["succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"];
      if (terminal.indexOf(job.status) >= 0) {
        const partial = job.result_summary && job.result_summary.partial;
        if (partial && partial.chapter) {
          const label = "chapter_" + String(partial.chapter).padStart(2, "0") + ".partial.md";
          box.innerHTML += '<div class="alert warn" style="margin-top:8px">partial draft saved: ' +
            '<a href="' + wsUrl("/draft/" + partial.chapter + "?variant=partial") + '">' +
            escapeHtml(label) + "</a></div>";
        }
        if (submit) submit.disabled = false;
        const stepLabel = job.step || job.current_step || "task";
        if (job.status === "succeeded") {
          showToast(stepLabel + " 已完成", "info");
        } else {
          const reason = jobFailureLine(job).slice(0, 80);
          showToast(stepLabel + " · " + job.status + (reason ? "：" + reason : ""), "error");
        }
        if (afterDone) await afterDone();
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  // ===== page: chapters list ==============================================
  async function initChapters() {
    const box = document.getElementById("chapters-table");
    if (!box) return;
    box.innerHTML = skeleton(6);
    try {
      const [drafts, manifest, reviews] = await Promise.all([
        fetchJson(wsUrl("/drafts")),
        fetchJson(wsUrl("/manifest")),
        fetchJson(wsUrl("/reviews")).catch(() => ({ chapters: [] })),
      ]);
      const reviewByCh = new Map();
      for (const r of (reviews.chapters || [])) reviewByCh.set(r.chapter, r);
      renderChapters(box, drafts.drafts || [], manifest.chapters || [], reviewByCh);
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
    bindChapterFilter();
  }
  function renderChapters(box, drafts, manifest, reviewByCh) {
    if (!drafts.length && !manifest.length) {
      box.innerHTML = emptyState(
        "还没有章节",
        "上传一本书并完成流水线后，章节会出现在这里。",
        ""
      );
      return;
    }
    const rows = [];
    rows.push(
      '<table class="table table-wide" id="chapters-data-table"><thead><tr>' +
      "<th>#</th><th>类型</th><th>章节 ID</th><th>标题</th>" +
      "<th>verdict</th><th>review</th><th>rewrite</th><th>字数</th><th></th>" +
      "</tr></thead><tbody>"
    );
    for (const d of drafts) {
      const r = reviewByCh.get(d.chapter) || {};
      const id = "chapter_" + String(d.chapter).padStart(2, "0");
      const title = r.title || "";
      const isPartial = d.variant === "partial";
      const detailHref = isPartial ? wsUrl("/draft/" + d.chapter + "?variant=partial") : "/w/" + encodeURIComponent(ws) + "/chapter/" + d.chapter;
      const typeCell = isPartial
        ? '<span class="badge warn">partial</span> <span class="badge reject">failure</span>'
        : "续写";
      rows.push(
        '<tr class="chapter-row" data-title="' + escapeHtml(title) + '" data-id="' + escapeHtml(id) +
        '" data-status="' + escapeHtml(d.verdict || "") + '">' +
        "<td>" + d.chapter + "</td>" +
        "<td>" + typeCell + "</td>" +
        "<td><code>" + escapeHtml(id + (isPartial ? ".partial" : "")) + "</code></td>" +
        "<td>" + escapeHtml(title) + "</td>" +
        "<td>" + verdictBadge(d.verdict) + "</td>" +
        "<td>" + verdictBadge(d.review_verdict) + "</td>" +
        "<td>" + escapeHtml(String(d.rewrite_count == null ? "—" : d.rewrite_count)) + "</td>" +
        "<td>" + escapeHtml(String(d.chars || 0)) + "</td>" +
        '<td><a class="btn btn-ghost btn-sm" href="' + detailHref + '">查看 →</a></td>' +
        "</tr>"
      );
    }
    for (const ch of manifest) {
      rows.push(
        '<tr class="chapter-row source" data-title="' + escapeHtml(ch.title || "") + '" data-id="' +
        escapeHtml(ch.chapter_id || "") + '">' +
        "<td>—</td>" +
        '<td><span class="badge no-dot">原文</span></td>' +
        "<td><code>" + escapeHtml(ch.chapter_id || "") + "</code></td>" +
        "<td>" + escapeHtml(ch.title || "") + "</td>" +
        '<td colspan="4" class="muted">' +
        escapeHtml(ch.volume_id || "") + " · " + escapeHtml(String(ch.char_count || "")) + " 字" + "</td>" +
        "<td></td>" +
        "</tr>"
      );
    }
    rows.push("</tbody></table>");
    box.innerHTML = tableScroll(rows.join(""));
  }
  function bindChapterFilter() {
    const search = document.getElementById("chapter-search");
    const toggles = document.querySelectorAll(".filter-toggle .btn");
    let mode = "all";
    function apply() {
      const q = (search && search.value || "").trim().toLowerCase();
      document.querySelectorAll("#chapters-data-table tbody tr").forEach((tr) => {
        const isSource = tr.classList.contains("source");
        const title = (tr.dataset.title || "").toLowerCase();
        const id = (tr.dataset.id || "").toLowerCase();
        const matchesQuery = !q || title.includes(q) || id.includes(q);
        let matchesMode = true;
        if (mode === "drafts") matchesMode = !isSource;
        else if (mode === "source") matchesMode = isSource;
        tr.style.display = (matchesQuery && matchesMode) ? "" : "none";
      });
    }
    if (search) search.addEventListener("input", apply);
    toggles.forEach((btn) => {
      btn.addEventListener("click", () => {
        toggles.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        mode = btn.dataset.mode || "all";
        apply();
      });
    });
  }

  // ===== page: chapter detail ============================================
  async function initChapterDetail() {
    bindHashTabs();
    bindLintJump();
    const num = window.CHAPTER_NO;
    if (!num) return;
    try {
      const data = await fetchJson(wsUrl("/draft/" + num));
      renderChapterDetail(data);
    } catch (err) {
      document.getElementById("chapter-body").innerHTML =
        '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }
  function _asLineNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  function _extractAnchorLine(anchor) {
    if (anchor == null) return null;
    if (typeof anchor === "number" || typeof anchor === "string") return _asLineNumber(anchor);
    if (typeof anchor === "object") {
      for (const k of ["paragraph", "line", "para", "index"]) {
        const n = _asLineNumber(anchor[k]);
        if (n != null) return n;
      }
    }
    return null;
  }
  function _extractIssueLine(issue) {
    const line = _asLineNumber(issue && issue.line);
    return line != null ? line : _extractAnchorLine(issue && issue.anchor);
  }
  function _findReadingLine(line) {
    let target = document.querySelector('.reading-body [data-line="' + line + '"]');
    if (!target) {
      const nodes = Array.from(document.querySelectorAll(".reading-body [data-line]"));
      target = nodes.find((el) => Number(el.getAttribute("data-line")) >= line) || nodes[nodes.length - 1];
    }
    return target || null;
  }
  function _highlightReadingLine(target) {
    if (!target) return;
    target.classList.remove("jump-highlight");
    void target.offsetWidth;
    target.classList.add("jump-highlight");
    setTimeout(function () { target.classList.remove("jump-highlight"); }, 4000);
  }
  function jumpToParagraph(line) {
    _highlightReadingLine(_findReadingLine(line));
    const tabBody = document.querySelector('.tab[data-tab="body"]');
    if (tabBody) tabBody.click();
    setTimeout(function () {
      const target = _findReadingLine(line);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      _highlightReadingLine(target);
    }, 50);
  }
  function bindLintJump() {
    document.addEventListener("click", function (ev) {
      const li = ev.target.closest("li[data-jump-line]");
      if (!li) return;
      const line = Number(li.getAttribute("data-jump-line"));
      if (Number.isFinite(line)) jumpToParagraph(line);
    });
  }
  function renderChapterDetail(data) {
    const meta = data.meta || {};
    const review = data.review || {};
    const num = data.chapter;
    // header bar
    const head = document.getElementById("chapter-meta-bar");
    if (head) {
      const cost = meta.cost_cny != null ? "¥" + Number(meta.cost_cny).toFixed(3) : "—";
      head.innerHTML =
        verdictBadge(meta.verdict || review.verdict) +
        '<span class="badge no-dot">rewrite ×' + (meta.rewrite_count || 0) + "</span>" +
        '<span class="badge no-dot">' + (meta.chinese_char_count || 0) + " 字</span>" +
        '<span class="badge no-dot">' + escapeHtml(cost) + "</span>" +
        (meta.needs_human_review ? '<span class="badge warn">需复核</span>' : "");
    }
    // body — render as paragraphs
    const body = document.getElementById("chapter-body");
    if (body) {
      const lines = (data.content || "").split(/\\n/);
      body.innerHTML = '<div class="reading-body">' +
        lines.map((line, idx) => {
          const sourceLine = idx + 1;
          if (!line.trim()) return "";
          if (line.startsWith("#")) {
            return '<h2 data-line="' + sourceLine + '">' + escapeHtml(line.replace(/^#+\\s*/, "")) + "</h2>";
          }
          return '<p data-line="' + sourceLine + '">' + escapeHtml(line) + "</p>";
        }).join("") + "</div>";
    }
    // reviews tab
    const reviewsBox = document.getElementById("tab-review");
    if (reviewsBox) {
      const agents = review.agent_reviews || meta.agent_reviews || [];
      if (!agents.length) {
        reviewsBox.innerHTML = '<p class="muted">本章暂无评审记录。</p>';
      } else {
        reviewsBox.innerHTML = agents.map(renderAgentReview).join("");
      }
    }
    // lint tab
    const lintBox = document.getElementById("tab-lint");
    if (lintBox) {
      const issues = meta.lint_issues || [];
      if (!issues.length) {
        lintBox.innerHTML = '<p class="muted">无 lint 提示。</p>';
      } else {
        const byRule = new Map();
        for (const it of issues) {
          const k = it.rule_id || it.rule || it.type || "misc";
          if (!byRule.has(k)) byRule.set(k, []);
          byRule.get(k).push(it);
        }
        const groups = [];
        for (const [rule, list] of byRule.entries()) {
          groups.push(
            '<div class="lint-group">' +
            '<h4>' + escapeHtml(rule) + " · " + list.length + "</h4>" +
            "<ul>" +
            list.map((it) => {
              const anchorLine = _extractIssueLine(it);
              return '<li' + (anchorLine != null ? ' class="link-cell" data-jump-line="' + anchorLine + '"' : "") + '>' +
                '<span class="severity ' + escapeHtml((it.severity || "").toLowerCase()) + '">' +
                escapeHtml(it.severity || "info") + '</span>' +
                '<span>' + escapeHtml(it.message || JSON.stringify(it)) + '</span>' +
                (it.anchor ? '<span class="anchor">@ ' + escapeHtml(JSON.stringify(it.anchor)) + '</span>' : '') +
                '</li>';
            }).join("") +
            "</ul>" +
            "</div>"
          );
        }
        lintBox.innerHTML = '<div class="stack">' + groups.join("") + "</div>";
      }
    }
    // advisor tab
    const advBox = document.getElementById("tab-advisor");
    if (advBox) {
      const suggestions = meta.rewrite_suggestions || [];
      if (!suggestions.length) {
        advBox.innerHTML = '<p class="muted">advisor 未提出改写建议。</p>';
      } else {
        advBox.innerHTML = '<div class="stack">' + suggestions.map((s) => (
          '<div class="advisor-item">' +
          '<span class="type">' + escapeHtml(s.type || "rewrite") + "</span>" +
          '<div class="section">' + escapeHtml(s.section || "(整段)") + "</div>" +
          '<div class="guidance">' + escapeHtml(s.guidance || "") + "</div>" +
          "</div>"
        )).join("") + "</div>";
      }
    }
    // history tab
    const histBox = document.getElementById("tab-history");
    if (histBox) {
      histBox.innerHTML =
        '<div class="kv-list compact">' +
        '<div class="k">rewrite_count</div><div class="v">' + (meta.rewrite_count || 0) + "</div>" +
        '<div class="k">rewrite_round</div><div class="v">' + (meta.rewrite_round || 0) + "</div>" +
        '<div class="k">polish_applied</div><div class="v">' + String(meta.polish_applied || false) + "</div>" +
        '<div class="k">snapshot_path</div><div class="v"><code>' + escapeHtml(meta.snapshot_path || "(无)") + "</code></div>" +
        '<div class="k">path</div><div class="v"><code>' + escapeHtml(data.path || "") + "</code></div>" +
        "</div>" +
        '<p class="muted" style="margin-top:12px">多版本草稿对比（diff）将在后续版本开放。</p>';
    }
  }
  function renderAgentReview(a) {
    // iter042 schema evolution: current reviewer output writes `scores`;
    // older artifacts used `sub_scores`, so the UI accepts both.
    const sub = a.scores || a.sub_scores || {};
    const bars = ["plot", "prose", "fidelity"].map((k) => {
      const v = sub[k];
      const pct = (v == null ? 0 : Math.max(0, Math.min(10, Number(v))) * 10);
      return '<div class="subscore-bar"><span class="label">' + k + "</span>" +
        '<div class="track"><i style="width:' + pct + '%"></i></div>' +
        '<span class="val">' + (v == null ? "—" : v) + "</span></div>";
    }).join("");
    const issues = (a.issues || []).slice(0, 6).map((it) =>
      "<li>" + escapeHtml(typeof it === "string" ? it : JSON.stringify(it)) + "</li>"
    ).join("");
    return (
      '<div class="review-card">' +
      '<div><div class="name">' + escapeHtml(a.agent_name || "?") + "</div>" +
      '<div class="verdict">' + verdictBadge(a.verdict) +
      '<span class="muted" style="margin-left:6px">score=' + (a.score == null ? "—" : a.score) + "</span></div></div>" +
      '<div class="stack">' + bars +
      (issues ? '<details><summary class="muted">issues (' + (a.issues || []).length + ")</summary><ul>" + issues + "</ul></details>" : "") +
      "</div></div>"
    );
  }

  // ===== page: reviews ====================================================
  async function initReviews() {
    const box = document.getElementById("reviews-panel");
    if (!box) return;
    box.innerHTML = skeleton(6);
    try {
      const data = await fetchJson(wsUrl("/reviews"));
      const chs = data.chapters || [];
      const stats = data.stats || {};
      if (!chs.length) {
        box.innerHTML = emptyState("尚无评审记录", "生成草稿后这里会列出每章评审结果。", "");
        return;
      }
      const statsHtml =
        '<div class="cluster" style="margin-bottom:16px">' +
        '<span class="badge no-dot">共 ' + (stats.total || 0) + " 章</span>" +
        '<span class="badge ready">通过 ' + (stats.accepted || 0) + "</span>" +
        '<span class="badge no-dot">rewrite_max ' + (stats.rewrite_max || 0) + "</span>" +
        '<span class="badge no-dot">advisor ' + (stats.advisor_suggestions_total || 0) + "</span>" +
        "</div>";
      const head =
        '<table class="table table-wide"><thead><tr>' +
        "<th>ch</th><th>verdict</th><th>rewrite</th><th>字数</th><th>agents</th><th>advisor</th><th></th>" +
        "</tr></thead><tbody>";
      const rows = chs.map((c) => {
        const detail = "/w/" + encodeURIComponent(ws) + "/chapter/" + c.chapter;
        return "<tr>" +
          "<td>" + c.chapter + "</td>" +
          "<td>" + verdictBadge(c.verdict) + "</td>" +
          "<td>" + (c.rewrite_count == null ? "—" : c.rewrite_count) + "</td>" +
          "<td>" + (c.chinese_char_count || 0) + "</td>" +
          "<td>" + (c.agent_reviews || []).length + "</td>" +
          "<td>" + (c.rewrite_suggestions || []).length + "</td>" +
          '<td><a class="btn btn-ghost btn-sm" href="' + detail + '">详情 →</a></td>' +
          "</tr>";
      }).join("");
      box.innerHTML = statsHtml + tableScroll(head + rows + "</tbody></table>");
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }

  // ===== page: insights ==================================================
  async function initInsights() {
    const costBox = document.getElementById("insights-cost");
    const cacheBox = document.getElementById("insights-cache");
    const subBox = document.getElementById("insights-subscores");
    if (!costBox || !cacheBox || !subBox) return;
    costBox.innerHTML = skeleton(4);
    cacheBox.innerHTML = skeleton(3);
    subBox.innerHTML = skeleton(5);
    try {
      const data = await fetchJson(wsUrl("/insights"));
      renderCostByChapter(costBox, data.cost_by_chapter || []);
      renderCacheByModel(cacheBox, data.cache_by_model || []);
      renderSubscores(subBox, data.subscores || []);
    } catch (err) {
      costBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
      cacheBox.innerHTML = "";
      subBox.innerHTML = "";
    }
  }

  function renderCostByChapter(box, rows) {
    if (!rows.length) { box.innerHTML = '<p class="muted">尚无 llm_calls 记录。</p>'; return; }
    const max = Math.max.apply(null, rows.map((r) => r.cost_cny || 0)) || 1;
    const lines = rows.map((r) => {
      const cost = Number(r.cost_cny || 0);
      const pct = Math.round((cost / max) * 100);
      return (
        '<div style="display:grid;grid-template-columns:56px 1fr 80px;gap:8px;align-items:center;margin-bottom:6px">' +
        '<span class="muted" style="text-align:right">ch ' + r.chapter + '</span>' +
        '<div class="progress" style="height:14px"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<span style="font-family:var(--font-mono);font-size:var(--fs-xs)">¥' + cost.toFixed(3) +
        ' · ' + r.calls + ' 次</span>' +
        '</div>'
      );
    }).join("");
    box.innerHTML = lines;
  }

  function renderCacheByModel(box, rows) {
    if (!rows.length) { box.innerHTML = '<p class="muted">尚无 llm_calls 记录。</p>'; return; }
    const lines = rows.map((r) => {
      const pct = Math.round((r.hit_ratio || 0) * 100);
      return (
        '<div class="kv-list compact" style="margin-bottom:8px">' +
        '<div class="k">model</div><div class="v"><code>' + escapeHtml(r.model) + '</code></div>' +
        '<div class="k">calls</div><div class="v">' + r.calls + '</div>' +
        '<div class="k">cache_read</div><div class="v">' + r.cache_read_tokens + '</div>' +
        '<div class="k">cache_write</div><div class="v">' + r.cache_write_tokens + '</div>' +
        '<div class="k">hit_ratio</div><div class="v">' +
        '<div class="progress" style="display:inline-block;width:120px;vertical-align:middle">' +
        '<div class="progress-fill" style="width:' + pct + '%"></div></div> ' + pct + '%</div>' +
        '</div>'
      );
    }).join("");
    box.innerHTML = lines;
  }

  function renderSubscores(box, rows) {
    if (!rows.length) { box.innerHTML = '<p class="muted">尚无评审记录。</p>'; return; }
    const cell = (v) => {
      if (v == null) return '<td class="subscore-cell subscore-cell-empty">—</td>';
      const n = Number(v);
      if (!Number.isFinite(n)) return '<td class="subscore-cell subscore-cell-empty">—</td>';
      const cls = n >= 7 ? "subscore-cell-approve" : n >= 5 ? "subscore-cell-warn" : "subscore-cell-fail";
      return '<td class="subscore-cell ' + cls + '">' + n.toFixed(2) + '</td>';
    };
    const head = '<tr><th>章</th><th>plot</th><th>prose</th><th>fidelity</th><th>total</th><th>agents</th></tr>';
    const body = rows.map((r) =>
      '<tr><td>ch ' + r.chapter + '</td>' +
      cell(r.plot) + cell(r.prose) + cell(r.fidelity) + cell(r.total) +
      '<td class="subscore-cell subscore-cell-empty">' + r.agents + '</td></tr>'
    ).join("");
    box.innerHTML = '<table class="table">' + head + body + '</table>';
  }

  // ===== page: drama write ==================================================
  async function initDramaWrite() {
    bindHashTabs();
    bindHookPickDelegate();
    await loadStationSetup();
    await loadStationHooks();
    await loadDramaProgress();
  }

  async function loadDramaProgress() {
    const box = document.getElementById("drama-write-progress");
    if (!box) return;
    try {
      const data = await fetchJson(wsUrl("/drama/progress"));
      box.innerHTML = (data.stations || []).map(function (s) {
        const cls = s.status === "done" ? "ready" :
          s.status === "locked" ? "blocked" : "warn";
        return '<span class="badge ' + cls + '">' + escapeHtml(s.label) +
          " · " + escapeHtml(s.status) + "</span>";
      }).join("");
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }

  async function loadStationSetup() {
    const pane = document.querySelector('[data-station-pane="setup"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(wsUrl("/drama/progress"));
      const station = (data.stations || []).find((s) => s.id === "setup");
      pane.innerHTML = renderStationSetup(station, data.wizard_input);
      bindStationSetupActions();
    } catch (err) {
      pane.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }

  function renderStationSetup(station, wizardInput) {
    const status = station ? station.status : "todo";
    const data = station ? station.data : null;
    const core = (data && data.core_setup) || data || {};
    let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ① 核心设定</h3>' +
      '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + escapeHtml(status) + '</span></div>' +
      '<div class="card-body stack">';
    if (wizardInput) {
      html += '<div class="kv-list compact">' +
        '<div class="k">题材</div><div class="v">' + escapeHtml(wizardInput.topic || "") + "</div>" +
        '<div class="k">赛道</div><div class="v"><code>' + escapeHtml(wizardInput.track || "") + "</code></div>" +
        '<div class="k">集数</div><div class="v">' + escapeHtml(String(wizardInput.episode_count || 0)) + "</div>" +
        '<div class="k">单集时长</div><div class="v">' + escapeHtml(String(wizardInput.episode_duration_seconds || 0)) + " 秒</div>" +
        '</div>';
    }
    if (data) {
      html += '<form id="station-setup-form" class="stack">' +
        '<div class="field"><label>logline</label>' +
        '<textarea name="logline" rows="2">' + escapeHtml(data.logline || "") + "</textarea></div>" +
        '<div class="field"><label>protagonist</label>' +
        '<textarea name="protagonist" rows="2">' + escapeHtml(core.protagonist || "") + "</textarea></div>" +
        '<div class="field"><label>antagonist</label>' +
        '<textarea name="antagonist" rows="2">' + escapeHtml(core.antagonist || "") + "</textarea></div>" +
        '<div class="field"><label>emotional_hook</label>' +
        '<textarea name="emotional_hook" rows="2">' + escapeHtml(core.emotional_hook || "") + "</textarea></div>" +
        '<div class="form-actions">' +
        '<button type="button" class="btn btn-secondary" id="regenerate-setup">重新生成</button>' +
        '<button type="submit" class="btn btn-primary">保存并进入站 ② →</button>' +
        '</div></form>';
    } else {
      html += '<div class="empty-state">' +
        '<span class="ornament">✦</span>' +
        '<h3>等待生成核心设定</h3>' +
        '<p class="muted">点击生成，产出主角 / 反派 / 情绪钩子。</p>' +
        '<button type="button" class="btn btn-primary" id="generate-setup">▸ 生成核心设定</button>' +
        "</div>";
    }
    html += "</div></div>";
    return html;
  }

  function bindStationSetupActions() {
    const genBtn = document.getElementById("generate-setup");
    if (genBtn) {
      genBtn.addEventListener("click", async function () {
        genBtn.disabled = true;
        try {
          await postJson(wsUrl("/drama/plan"), {});
          showToast("核心设定已生成", "info");
          await loadStationSetup();
          await loadStationHooks();
          await loadDramaProgress();
        } catch (err) {
          showToast("生成失败：" + err.message, "error");
          genBtn.disabled = false;
        }
      });
    }
    const regenBtn = document.getElementById("regenerate-setup");
    if (regenBtn) {
      regenBtn.addEventListener("click", async function () {
        regenBtn.disabled = true;
        try {
          await postJson(wsUrl("/drama/plan"), {});
          showToast("核心设定已重新生成", "info");
          await loadStationSetup();
          await loadStationHooks();
          await loadDramaProgress();
        } catch (err) {
          showToast("重新生成失败：" + err.message, "error");
          regenBtn.disabled = false;
        }
      });
    }
    const form = document.getElementById("station-setup-form");
    if (form) {
      form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        const payload = {
          logline: form.elements.logline.value,
          protagonist: form.elements.protagonist.value,
          antagonist: form.elements.antagonist.value,
          emotional_hook: form.elements.emotional_hook.value,
        };
        try {
          await putJson(wsUrl("/drama/setup"), payload);
          showToast("已保存，进入站 ②", "info");
          history.replaceState(null, "", "#hook");
          const tab = document.querySelector('.tab[data-tab="hook"]');
          if (tab) tab.click();
          await loadStationHooks();
          await loadDramaProgress();
        } catch (err) {
          showToast("保存失败：" + err.message, "error");
        }
      });
    }
  }

  async function loadStationHooks() {
    const pane = document.querySelector('[data-station-pane="hook"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(wsUrl("/drama/progress"));
      const station = (data.stations || []).find((s) => s.id === "hook");
      if (station && station.status === "locked") {
        pane.innerHTML = '<div class="alert info">请先完成站 ①</div>';
        return;
      }
      pane.innerHTML = renderStationHooks(station);
      bindStationHooksActions();
    } catch (err) {
      pane.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }

  function renderStationHooks(station) {
    const status = station ? station.status : "todo";
    const data = station ? station.data : null;
    let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ② 钩子</h3>' +
      '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + escapeHtml(status) + '</span></div>' +
      '<div class="card-body stack">';
    if (!data) {
      html += '<div class="empty-state">' +
        '<span class="ornament">✦</span>' +
        '<h3>等待生成钩子候选</h3>' +
        '<p class="muted">AI 会出 3 个候选：情绪钩 / 悬念钩 / 反差钩，你选 1 个继续。</p>' +
        '<button type="button" class="btn btn-primary" id="generate-hooks">▸ 生成 3 个钩子</button>' +
        "</div>";
    } else {
      html += '<div class="kv-list compact">' +
        '<div class="k">type</div><div class="v"><code>' + escapeHtml(data.type || "") + "</code></div>" +
        '<div class="k">content</div><div class="v">' + escapeHtml(data.content || "") + "</div>" +
        '</div>' +
        '<div class="alert info">站 ② 已锁定。分镜与角色设定将在后续版本上线。</div>';
    }
    html += "</div></div>";
    return html;
  }

  function bindStationHooksActions() {
    const btn = document.getElementById("generate-hooks");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      btn.disabled = true;
      try {
        const data = await postJson(wsUrl("/drama/hooks"), {});
        const hooks = data.hooks || [];
        const pane = document.querySelector('[data-station-pane="hook"]');
        if (!pane) return;
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
        pane.__hooks = hooks;
      } catch (err) {
        showToast("生成失败：" + err.message, "error");
        btn.disabled = false;
      }
    });
  }

  let hookPickDelegateBound = false;
  function bindHookPickDelegate() {
    if (hookPickDelegateBound) return;
    hookPickDelegateBound = true;
    document.addEventListener("click", async function (ev) {
      const pick = ev.target.closest("[data-hook-pick]");
      if (!pick) return;
      const pane = pick.closest('[data-station-pane="hook"]');
      if (!pane || !pane.__hooks) return;
      pane.querySelectorAll("[data-hook-pick]").forEach((b) => { b.disabled = true; });
      const idx = Number(pick.getAttribute("data-hook-pick"));
      try {
        await putJson(wsUrl("/drama/setup"), { hook: pane.__hooks[idx] });
        showToast("钩子已锁定", "info");
        await loadStationHooks();
        await loadDramaProgress();
      } catch (err) {
        showToast("保存失败：" + err.message, "error");
        pane.querySelectorAll("[data-hook-pick]").forEach((b) => { b.disabled = false; });
      }
    });
  }

  // ===== page: jobs =======================================================
  async function initJobs() {
    const recentBox = document.getElementById("jobs-recent");
    const logsBox = document.getElementById("jobs-logs");
    if (recentBox) recentBox.innerHTML = skeleton(4);
    if (logsBox) logsBox.innerHTML = skeleton(4);
    try {
      const data = await fetchJson(wsUrl("/jobs/recent?n=20"));
      const items = data.jobs || [];
      if (!items.length) {
        recentBox.innerHTML = emptyState("尚无任务历史", "点击「续写」启动第一个任务后会出现在这里。", "");
      } else {
        const byId = new Map();
        const rows = items.map((job) => {
          byId.set(job.job_id || "", job);
          const trace = job.trace_id || "";
          const note = jobActionableSummary(job);
          const rowId = "job-drawer-" + escapeHtml(job.job_id || "");
          return (
            '<tr class="job-row">' +
            '<td><button type="button" class="btn btn-icon btn-sm job-toggle" aria-expanded="false" aria-controls="' + rowId + '" data-job-toggle="' + escapeHtml(job.job_id || "") + '">▸</button></td>' +
            "<td>" + escapeHtml(job.step || "?") + "</td>" +
            "<td>" + statusBadge(job.status || "?") + "</td>" +
            '<td><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code> " + copyButton(job.job_id || "") + "</td>" +
            '<td><span class="trace">' + escapeHtml(trace || "—") + "</span>" + (trace ? " " + copyButton(trace) : "") + "</td>" +
            "<td>" + escapeHtml(job.started_at ? String(job.started_at) : "—") + "</td>" +
            "<td>" + escapeHtml(note ? note.slice(0, 120) : "") + "</td>" +
            "</tr>" +
            '<tr class="job-drawer-row" id="' + rowId + '"><td colspan="7">' + renderJobDrawer(job) + "</td></tr>"
          );
        }).join("");
        recentBox.innerHTML =
          tableScroll('<table class="table table-wide jobs-table"><thead><tr>' +
          "<th></th><th>step</th><th>status</th><th>job_id</th><th>trace_id</th><th>started</th><th>note</th>" +
          "</tr></thead><tbody>" + rows + "</tbody></table>");
        recentBox.onclick = function (ev) {
          const toggle = ev.target.closest("[data-job-toggle]");
          if (toggle) {
            const id = toggle.getAttribute("data-job-toggle") || "";
            const drawer = document.getElementById("job-drawer-" + id);
            if (drawer) {
              const open = !drawer.classList.contains("open");
              drawer.classList.toggle("open", open);
              toggle.setAttribute("aria-expanded", open ? "true" : "false");
              toggle.textContent = open ? "▾" : "▸";
            }
            return;
          }
          const partial = ev.target.closest("[data-job-partial]");
          if (partial) {
            openPartialPreview(partial.getAttribute("data-job-partial") || "");
            return;
          }
          const retry = ev.target.closest("[data-job-retry]");
          if (retry) {
            retryJob(byId.get(retry.getAttribute("data-job-retry") || ""), retry);
          }
        };
      }
    } catch (err) {
      recentBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
    try {
      const data = await fetchJson(wsUrl("/logs/tail?n=30"));
      const lines = data.lines || [];
      logsBox.innerHTML = lines.length
        ? '<pre class="logs-tail">' + lines.map((l) => escapeHtml(JSON.stringify(l))).join("\\n") + "</pre>"
        : '<p class="muted">llm_calls.jsonl 尚无内容。</p>';
    } catch (err) {
      logsBox.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
    }
  }

  // ---- dispatch ---------------------------------------------------------
  function boot() {
    initShellControls();
    const pending = sessionStorage.getItem("__pending_toast");
    if (pending) {
      sessionStorage.removeItem("__pending_toast");
      try {
        const t = JSON.parse(pending);
        showToast(t.msg, t.kind || "info");
      } catch (e) {}
    }
    if (pageKind === "index") return initIndex();
    if (pageKind === "trash") return initTrash();
    if (pageKind === "workspace_overview") return initWorkspaceOverview();
    if (pageKind === "continue") return initContinue();
    if (pageKind === "chapters") return initChapters();
    if (pageKind === "chapter_detail") return initChapterDetail();
    if (pageKind === "reviews") return initReviews();
    if (pageKind === "plan") return initPlan();
    if (pageKind === "insights") return initInsights();
    if (pageKind === "drama_write") return initDramaWrite();
    if (pageKind === "jobs") return initJobs();
  }
  document.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();
})();
"""


JS_WIZARD = """\
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
  const modeCard = document.getElementById("wizard-mode-card");
  const cancelRequestedJobs = new Set();
  const CTA_ACTIONS = {
    running: {
      title: "任务进行中",
      hint: "可以离开此页继续浏览；取消会在 worker 下一个检查点生效。",
    },
    succeeded: {
      title: "导入完成",
      hint: "下一步可以设置起点、查看章节，或进入续写入口。",
    },
    failed: {
      title: "任务未完成",
      hint: "查看失败详情后，可以回到 wizard 重新开始。",
    },
    aborted: {
      title: "任务已取消",
      hint: "取消请求已生效；可以重新开始或返回书架。",
    },
  };

  loadServerMode();

  function show(panel) {
    [panelType, panelUpload, panelDrama, panelProgress].forEach((p) => {
      if (p) p.hidden = (p !== panel);
    });
  }

  async function loadServerMode() {
    if (!modeCard) return;
    try {
      const res = await fetch("/api/settings");
      const data = await res.json().catch(() => ({}));
      const settings = data.settings || {};
      const model = String(settings.OPENAI_MODEL || "mock");
      const isMock = !model || model === "mock";
      modeCard.innerHTML = '<strong>当前 server 模式：' + (isMock ? "mock" : "real") + '</strong>' +
        '<br><span class="muted">OPENAI_MODEL=' + escapeHtml(model || "mock") +
        (isMock ? "，本次不会消耗真实 token。" : "，请确认已授权真实模型运行。") + "</span>";
    } catch (err) {
      modeCard.innerHTML = '<strong>当前 server 模式：mock</strong>' +
        '<br><span class="muted">未读取到设置，按默认 mock-only 展示。</span>';
    }
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

  if (progressBody) {
    progressBody.addEventListener("click", async function (ev) {
      const btn = ev.target.closest("[data-cancel-job]");
      if (!btn) return;
      ev.preventDefault();
      const name = btn.getAttribute("data-workspace") || "";
      const jobId = btn.getAttribute("data-cancel-job") || "";
      if (!name || !jobId) return;
      btn.disabled = true;
      try {
        const res = await fetch("/api/workspace/" + encodeURIComponent(name) + "/job/" + jobId + "/cancel", {
          method: "POST",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
        cancelRequestedJobs.add(jobId);
        const notice = document.getElementById("cancel-notice");
        if (notice) notice.innerHTML = '<div class="alert info">取消请求已发送，等待 worker 响应。</div>';
      } catch (err) {
        const notice = document.getElementById("cancel-notice");
        if (notice) notice.innerHTML = '<div class="alert error">取消失败: ' + escapeHtml(String(err.message || err)) + "</div>";
        btn.disabled = false;
      }
    });
  }

  if (novelForm) {
    novelForm.addEventListener("submit", async (ev) => {
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

  if (dramaForm) {
    dramaForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      dramaErrBox.innerHTML = "";
      const fd = new FormData(dramaForm);
      const payload = {
        workspace: (fd.get("workspace") || "").trim(),
        topic: (fd.get("topic") || "").trim(),
        track: fd.get("track") || "",
        episode_count: Number(fd.get("episode_count") || 0),
        episode_duration_seconds: Number(fd.get("episode_duration_seconds") || 0),
        budget_cny: Number(fd.get("budget_cny") || 0),
        timeout_minutes: Number(fd.get("timeout_minutes") || 0),
      };
      const submitBtn = dramaForm.querySelector("button[type=submit]");
      submitBtn.disabled = true;
      try {
        const res = await fetch("/api/wizard/drama-start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          dramaErrBox.innerHTML = '<div class="alert error">创建失败 (' + res.status + "): " +
            escapeHtml(data.error || "") + "</div>";
          submitBtn.disabled = false;
          return;
        }
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "短剧 workspace 已创建：" + data.name },
          "/w/" + encodeURIComponent(data.name) + "/write?step=setup"
        );
      } catch (err) {
        dramaErrBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
        submitBtn.disabled = false;
      }
    });
  }

  async function poll(name, jobId) {
    while (true) {
      try {
        const res = await fetch("/api/workspace/" + encodeURIComponent(name) + "/job/" + jobId);
        const job = await res.json();
        renderProgress(job, name, jobId);
        if (job.status === "succeeded") {
          return;
        }
        if (["blocked", "failed", "aborted", "lost", "budget_exceeded"].indexOf(job.status) >= 0) {
          return;
        }
      } catch (err) {
        progressBody.innerHTML = '<div class="alert error">轮询失败: ' + escapeHtml(String(err)) + "</div>";
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  function renderProgress(job, name, jobId) {
    const pct = Math.round((job.progress || 0) * 100);
    progressBody.innerHTML =
      '<div class="kv-list compact">' +
      '<div class="k">status</div><div class="v">' + escapeHtml(job.status) + "</div>" +
      '<div class="k">current step</div><div class="v">' + escapeHtml(job.current_step || "?") + "</div>" +
      '<div class="k">progress</div><div class="v">' + pct + "%</div>" +
      '<div class="k">job_id</div><div class="v"><code>' + escapeHtml(job.job_id) + "</code></div>" +
      "</div>" +
      '<div class="progress" style="margin-top:12px"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
      renderWizardActions(job, name, jobId);
  }
  function renderWizardActions(job, name, jobId) {
    const status = job.status || "pending";
    const group = (status === "succeeded")
      ? "succeeded"
      : (status === "aborted" ? "aborted" : (status === "running" || status === "pending" ? "running" : "failed"));
    const cfg = CTA_ACTIONS[group] || CTA_ACTIONS.failed;
    const workspaceHref = "/w/" + encodeURIComponent(name) + "/";
    const jobsHref = workspaceHref + "jobs";
    const continueHref = workspaceHref + "continue";
    const chaptersHref = workspaceHref + "chapters";
    const trace = job.trace_id ? ' <code>trace=' + escapeHtml(job.trace_id) + '</code>' : "";
    const err = job.error ? '<div class="alert error">详情: ' + escapeHtml(job.error) + trace + "</div>" : "";
    let buttons = "";
    if (group === "running") {
      buttons =
        '<a class="btn btn-ghost" href="/">继续浏览书架</a>' +
        '<a class="btn btn-secondary" href="' + jobsHref + '">查看任务</a>' +
        '<button type="button" class="btn btn-danger" data-workspace="' + escapeHtml(name) +
        '" data-cancel-job="' + escapeHtml(jobId) + '"' +
        (cancelRequestedJobs.has(jobId) ? " disabled" : "") + ">取消任务</button>";
    } else if (group === "succeeded") {
      buttons =
        '<a class="btn btn-primary" href="' + continueHref + '">设置起点</a>' +
        '<a class="btn btn-secondary" href="' + chaptersHref + '">查看章节</a>' +
        '<a class="btn btn-secondary" href="' + continueHref + '">开始续写</a>';
    } else if (group === "aborted") {
      buttons =
        '<a class="btn btn-primary" href="/wizard">重新开始</a>' +
        '<a class="btn btn-ghost" href="/">返回书架</a>';
    } else {
      buttons =
        '<a class="btn btn-secondary" href="' + jobsHref + '">查看失败详情</a>' +
        '<a class="btn btn-primary" href="/wizard">回到 wizard 重试</a>';
    }
    return '<div class="wizard-progress-actions">' +
      '<div class="alert ' + (group === "failed" ? "error" : group === "aborted" ? "warn" : "info") + '">' +
      '<strong>' + escapeHtml(cfg.title) + '</strong><br>' + escapeHtml(cfg.hint) + "</div>" +
      '<div id="cancel-notice">' +
      (cancelRequestedJobs.has(jobId) && group === "running" ? '<div class="alert info">取消请求已发送，等待 worker 响应。</div>' : "") +
      "</div>" +
      err +
      '<div class="cluster">' + buttons + "</div>" +
      "</div>";
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
})();
"""


JS_SETTINGS = """\
(async function () {
  const form = document.getElementById("settings-form");
  const errBox = document.getElementById("settings-error");
  const banner = document.getElementById("restart-banner");
  if (!form) return;
  let initial = {};
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    initial = data.settings || {};
  } catch (err) {
    errBox.innerHTML = '<div class="alert error">读取失败: ' + escapeHtml(String(err)) + "</div>";
    return;
  }
  for (const [k, v] of Object.entries(initial)) {
    const row = document.createElement("div");
    row.className = "field";
    row.innerHTML =
      '<label>' + escapeHtml(k) + "</label>" +
      '<input name="' + escapeHtml(k) + '" type="text" value="' + escapeHtml(v) +
      '" placeholder="(empty)" autocomplete="off">';
    form.appendChild(row);
  }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errBox.innerHTML = "";
    if (banner) banner.hidden = true;
    const payload = {};
    for (const input of form.querySelectorAll("input")) {
      if (input.value === initial[input.name]) continue;
      payload[input.name] = input.value;
    }
    if (Object.keys(payload).length === 0) {
      errBox.innerHTML = '<div class="alert warn">(没有改动)</div>';
      return;
    }
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        errBox.innerHTML = '<div class="alert error">保存失败 (' + res.status + "): " +
          escapeHtml(data.error || "") + "</div>";
        return;
      }
      if (banner) {
        banner.hidden = false;
        banner.innerHTML = '<div class="alert info">已保存 ' +
          escapeHtml((data.updated_keys || []).join(", ")) + "，请重启 web 服务以让新模型生效</div>";
      }
    } catch (err) {
      errBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
    }
  });
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
})();
"""
