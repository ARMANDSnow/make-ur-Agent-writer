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
.sidebar-library { min-height: 0; }
.sidebar-library h4 { display: flex; justify-content: space-between; gap: var(--space-2); }
.sidebar-library h4 span { font-variant-numeric: tabular-nums; }
.sidebar-library-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: min(32vh, 280px);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}
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
.sidebar-item > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
/* iter070: hide ☰ (nav-toggle) and ⋯ (topbar-menu-toggle) on desktop. This rule
   MUST sit AFTER `.btn { display: inline-flex }` above — both are single-class
   selectors (0,1,0), so when this was at the top of the topbar block `.btn` won
   on source order and the two toggles leaked as dead buttons on desktop. Placed
   here it wins on source order. The <=768px media query re-shows them (same
   0,1,0, later in the file) so mobile/landing behaviour is unchanged. */
.nav-toggle, .topbar-menu-toggle { display: none; }

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
.badge-drama { color: var(--amber-strong); background: var(--amber-soft); border-color: var(--amber); }
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
.style-preset-card.active { border-color: var(--jade); background: var(--jade-soft); }
.style-preset-card h4 { margin: 0 0 4px; font-size: var(--fs-md); }
.style-preset-card .card-body { padding: var(--space-3); }
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
.shot-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);
}
.shot-image-candidate {
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  overflow: hidden;
  background: var(--bg-card);
}
.shot-image-candidate img,
.shot-image-compare img {
  width: 100%;
  aspect-ratio: 9 / 16;
  object-fit: contain;
  background: var(--bg-sunken);
}
.shot-image-candidate .candidate-body { padding: var(--space-3); }
.shot-image-compare {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.shot-image-compare:empty { display: none; }
.shot-image-compare figure { margin: 0; }
.shot-image-compare figcaption { overflow-wrap: anywhere; }
.shot-video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
  gap: var(--space-4);
}
.shot-video-candidate {
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--bg-card);
  overflow: hidden;
}
.shot-video-candidate video {
  display: block;
  width: 100%;
  aspect-ratio: 9 / 16;
  max-height: 480px;
  background: #111;
}
.shot-video-candidate .candidate-body { padding: var(--space-3); }
.drama-episode-table { min-width: 620px; }
.drama-episode-table th, .drama-episode-table td { white-space: nowrap; }
.storyboard-table { min-width: 1120px; }
.storyboard-table textarea {
  width: 100%;
  min-width: 180px;
  min-height: 74px;
  resize: vertical;
}
.storyboard-table input[type=number] { width: 74px; }
.storyboard-table select { min-width: 88px; }
.storyboard-actions { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.storyboard-duration.ready { color: var(--jade-strong); }
.storyboard-duration.warn { color: var(--amber-strong); }
.storyboard-duration.blocked { color: var(--sienna); }
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

/* iter 074: chapter version diff (history tab) — iter075 观感打磨（不改数据流/端点） */
.diff-panel { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--rule); }
.diff-panel > h4 { font-size: var(--fs-sm); margin: 0 0 var(--space-3); color: var(--ink-2); letter-spacing: .02em; }
.diff-controls { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; font-size: var(--fs-sm); color: var(--ink-2); }
.diff-controls label { display: inline-flex; align-items: center; gap: var(--space-2); }
.diff-controls select {
  max-width: 260px; padding: var(--space-1) var(--space-2);
  border: 1px solid var(--rule-strong); border-radius: var(--radius-1);
  background: var(--bg-card); color: var(--ink-1); font-size: var(--fs-sm);
}
.diff-controls select:focus { outline: none; border-color: var(--jade); box-shadow: 0 0 0 2px var(--jade-soft); }
.diff-controls .diff-arrow { color: var(--ink-3); }
.diff-output { margin-top: var(--space-3); }
.diff-view {
  border: 1px solid var(--rule); border-radius: var(--radius-2); overflow: auto;
  font-family: var(--font-mono); font-size: var(--fs-xs); line-height: 1.65;
  background: var(--bg-card); max-height: 480px; box-shadow: var(--shadow-card);
}
.diff-line { padding: 1px var(--space-3); white-space: pre-wrap; word-break: break-word; border-left: 3px solid transparent; }
.diff-line.diff-add { background: var(--jade-soft); border-left-color: var(--jade); }
.diff-line.diff-del { background: var(--sienna-soft); border-left-color: var(--sienna); }
.diff-line.diff-hunk { color: var(--ink-3); background: var(--bg-sunken); }
.diff-line.diff-meta { color: var(--ink-3); background: var(--bg-sunken); font-style: italic; }
.diff-line.diff-ctx { color: var(--ink-2); }

/* iter075: 全文搜索页 */
.search-hero { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-4); }
.search-box-wrap { position: relative; display: flex; align-items: center; }
.search-box-wrap .search-icon { position: absolute; left: var(--space-4); color: var(--jade); font-size: var(--fs-lg); pointer-events: none; opacity: .7; }
.search-box {
  width: 100%;
  padding: var(--space-3) var(--space-4) var(--space-3) calc(var(--space-6) + var(--space-2));
  font-size: var(--fs-lg); font-family: var(--font-serif);
  border: 1px solid var(--rule-strong); border-radius: var(--radius-2);
  background: var(--bg-card); color: var(--ink-1);
}
.search-box::placeholder { color: var(--ink-3); }
.search-box:focus { outline: none; border-color: var(--jade); box-shadow: 0 0 0 3px var(--jade-soft); }
.search-sources { gap: var(--space-4); font-size: var(--fs-sm); color: var(--ink-2); }
.search-sources label { display: inline-flex; align-items: center; gap: var(--space-1); cursor: pointer; }
.search-summary { margin: 0 0 var(--space-4); font-size: var(--fs-sm); }
.search-results { display: flex; flex-direction: column; gap: var(--space-4); }
.search-hit { padding: var(--space-4); }
.search-hit-head { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); flex-wrap: wrap; }
.search-hit-title { font-family: var(--font-serif); font-size: var(--fs-lg); color: var(--ink-1); text-decoration: none; }
a.search-hit-title:hover { color: var(--jade); text-decoration: underline; }
.search-hit-title.muted-link { color: var(--ink-2); }
.search-hit-count { margin-left: auto; font-size: var(--fs-xs); color: var(--ink-3); }
.search-snippet {
  font-family: var(--font-serif); font-size: var(--fs-md); line-height: 1.9;
  color: var(--ink-2); margin: var(--space-2) 0 0; white-space: pre-wrap; word-break: break-word;
}
.search-snippet + .search-snippet { padding-top: var(--space-2); border-top: 1px dashed var(--rule); }
.search-snippet mark {
  background: var(--amber-soft); color: var(--amber-strong);
  padding: 0 2px; border-radius: var(--radius-1); font-weight: 600;
}
/* source badge 三色：original=金(参照)、draft=品牌绿(可编辑)、kb=砖红(参考) */
.badge.source-original { color: var(--gold); background: var(--gold-soft); border-color: var(--gold-soft); }
.badge.source-draft { color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge.source-kb { color: var(--sienna); background: var(--sienna-soft); border-color: var(--sienna-soft); }

/* ---------- Review / advisor readability polish (global) ---------- */
.subscore-bar .track { height: 8px; }
.subscore-bar .val { font-family: var(--font-serif); font-size: var(--fs-sm); color: var(--ink-1); }
.badge.approve, .badge.reject { font-weight: 700; }
.advisor-item { border-left: 3px solid var(--jade); }

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
/* iter071 (codex F6): the 3-way leave-guard footer — equal-width, single-line
   buttons so the choices read as a tidy, consistent row instead of ragged
   content-sized boxes that wrap at different points. */
.modal-footer-equal .btn { flex: 1 1 0; min-width: 0; white-space: nowrap; }

/* ---------- responsive ---------- */
@media (max-width: 1024px) {
  .overview-hero { grid-template-columns: 1fr; }
  .grid.cols-3, .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* ---------- Landing page (investor entry) ---------- */
.lp {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-5) 0 var(--space-7);
}
.lp-hero {
  text-align: center;
  padding: var(--space-8) var(--space-7);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background:
    radial-gradient(120% 80% at 18% 0%, var(--jade-soft) 0%, transparent 55%),
    radial-gradient(100% 80% at 92% 8%, var(--amber-soft) 0%, transparent 50%),
    var(--bg-card);
}
.lp-hero-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.lp-wordmark {
  font-family: var(--font-serif);
  font-size: var(--fs-h2);
  font-weight: 600;
  color: var(--ink-1);
  letter-spacing: .02em;
}
.lp-hero .eyebrow { justify-content: center; }
.lp-title {
  font-family: var(--font-serif);
  font-size: var(--fs-display);
  line-height: 1.25;
  margin: var(--space-3) 0 var(--space-4);
  color: var(--ink-1);
}
.lp-lead {
  max-width: 36em;
  margin: 0 auto var(--space-5);
  font-size: var(--fs-lg);
  line-height: 1.7;
}
.lp-hero-cta { justify-content: center; }
.lp-hero-cta .btn { min-width: 132px; }

.lp-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-5);
}
/* iter069: 3 cards degrade to 2 columns on tablets, then to 1 column at
   <=768px (in the mobile block below). This rule MUST sit after the base
   3-col rule above — equal specificity, so source order decides the winner;
   placing it inside the earlier responsive @media block let the later base
   rule override it and stranded a cramped 3-up row at ~800px. */
@media (max-width: 1024px) {
  .lp-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.lp-card {
  display: flex;
  flex-direction: column;
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;
}
.lp-card:hover {
  transform: translateY(-2px);
  border-color: var(--rule-strong);
  box-shadow: 0 6px 20px rgba(42, 37, 32, .08);
}
.lp-card .card-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.lp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.lp-card-head h2 {
  font-family: var(--font-serif);
  font-size: var(--fs-h2);
  margin: 0;
  color: var(--ink-1);
}
.lp-feats {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.lp-feats li {
  position: relative;
  padding-left: var(--space-5);
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: 1.5;
}
.lp-feats li::before {
  content: "✦";
  position: absolute;
  left: 0;
  top: 0;
  color: var(--jade);
  font-size: var(--fs-xs);
}
.lp-feat-beta { color: var(--ink-3); }
.lp-feat-beta::before { color: var(--gold); }
.lp-card-footer .btn { width: 100%; justify-content: center; }

.lp-trust {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding-top: var(--space-3);
}
.lp-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}
.lp-metrics .tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
}
.lp-metrics .tile .v {
  font-family: var(--font-serif);
  font-size: var(--fs-display);
  line-height: 1;
  color: var(--jade-strong);
}
.lp-metrics .tile .k {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink-1);
}
.lp-metrics .tile .sub {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
.lp-chips { justify-content: center; flex-wrap: wrap; }

@keyframes lp-fade-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
.fade-up { animation: lp-fade-up .5s ease both; }
.fade-up-1 { animation-delay: .08s; }
.fade-up-2 { animation-delay: .16s; }
.fade-up-3 { animation-delay: .24s; }
.fade-up-4 { animation-delay: .32s; }
@media (prefers-reduced-motion: reduce) {
  .fade-up, .fade-up-1, .fade-up-2, .fade-up-3, .fade-up-4 { animation: none; }
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
  /* iter064 #3: scope the mobile dropdown pattern to the SHELL topbar (the only
     .topbar-actions inside .topbar-actions-wrap). The bare selector also hit
     in-page content action rows (overview "删除作品…", chapter-detail back
     links) that reuse the .topbar-actions class, hiding them at <=768px. */
  .topbar-actions-wrap .topbar-actions {
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
  .topbar-actions-wrap .topbar-actions.open { display: flex; }
  .topbar-actions-wrap .topbar-actions .btn {
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
  .lp { padding: var(--space-4) 0 var(--space-6); gap: var(--space-5); }
  .lp-hero { padding: var(--space-6) var(--space-5); }
  .lp-title { font-size: var(--fs-h1); }
  .lp-cards { grid-template-columns: 1fr; }
  .lp-metrics { grid-template-columns: 1fr; }
}

/* ====================================================================== *
 * iter062: friendly error cards + workbench step rail + locked tabs +
 * topbar home button. All built on existing tokens (paper/ink/jade/amber/
 * sienna), no new colours.
 * ====================================================================== */

/* topbar home: cluster nav-toggle + home + breadcrumb on the left, push
 * the page actions to the far right (override the bare space-between). */
.topbar .home-btn { flex: 0 0 auto; }
.topbar .breadcrumb { margin-right: auto; }
/* iter069: landing (page_kind=="landing" → .app.lp-chrome) hides the shared
   topbar nav cluster so the hero keeps only ⚙ 设置. We hide ONLY ☰ (nav-toggle)
   and ⌂ (home-btn): ⌂ is the sole element shown at every breakpoint, and ☰ is
   redundant on a sidebar-less landing. We deliberately do NOT hide ⋯
   (.topbar-menu-toggle): on desktop it's already hidden by the base
   `.nav-toggle,.topbar-menu-toggle{display:none}` rule (relocated in iter070 to
   sit after `.btn` so source order wins), and ⚙ 设置 shows inline, but on
   <=768px ⋯ is the ONLY way to open the
   .topbar-actions dropdown that holds ⚙ 设置 — hiding it would strand the lone
   landing action on mobile. .lp-chrome X (0-2-0) beats the desktop default and
   the <=768px home-btn rules (all 0-1-0); display:none also drops these from
   the a11y tree (no aria-hidden needed). Scoped to landing via APP_CLASS so
   wizard/settings keep their ⌂ / ⋯. */
.lp-chrome .nav-toggle,
.lp-chrome .home-btn { display: none; }
html { scroll-behavior: smooth; }

/* friendly error card (replaces bare .alert.error traceback dumps) */
.error-card {
  background: var(--sienna-soft);
  border: 1px solid var(--sienna);
  border-radius: var(--radius-2);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.error-card-head { display: flex; gap: var(--space-3); align-items: flex-start; }
.error-card-icon { color: var(--sienna); font-size: var(--fs-xl); line-height: 1.2; flex: 0 0 auto; }
.error-card-copy { min-width: 0; }
.error-card-title { font-weight: 600; color: var(--ink-1); margin: 0; }
.error-card-cause { color: var(--ink-2); margin: 4px 0 0; font-size: var(--fs-sm); }
.error-card-actions { margin: 0; }
.error-card-trace { margin: 0; font-size: var(--fs-xs); color: var(--ink-3); }
.error-card-trace code { color: var(--ink-2); }
.error-card-tech { margin: 0; }
.error-card-tech > summary { cursor: pointer; font-size: var(--fs-xs); color: var(--ink-3); }
.error-card-tech pre {
  background: var(--bg-sunken); border-radius: var(--radius-1);
  padding: var(--space-2) var(--space-3); font-size: var(--fs-xs);
  color: var(--ink-2); margin: var(--space-2) 0 0;
}

/* workbench clickable step rail */
.stepbar { list-style: none; display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0; }
.stepbar .step { display: flex; align-items: center; font-size: var(--fs-sm); color: var(--ink-3); }
.stepbar .step a { color: var(--ink-2); border: 0; display: inline-flex; align-items: center; gap: var(--space-2); }
.stepbar .step a:hover { color: var(--jade); border: 0; }
.stepbar .step.done, .stepbar .step.done a { color: var(--jade-strong); }
.stepbar .step.current, .stepbar .step.current a { color: var(--amber-strong); font-weight: 600; }
.stepbar .step.locked { color: var(--ink-3); cursor: not-allowed; }
.stepbar .step:not(:last-child)::after { content: "›"; color: var(--ink-3); margin-left: var(--space-3); }
.stepbar .step-glyph {
  display: inline-flex; width: 18px; height: 18px; border-radius: 50%;
  align-items: center; justify-content: center; font-size: var(--fs-xs);
  background: var(--bg-sunken); color: var(--ink-3);
}
.stepbar .step.done .step-glyph { background: var(--jade); color: #fff; }
.stepbar .step.current .step-glyph { background: var(--amber-soft); color: var(--amber-strong); box-shadow: inset 0 0 0 2px var(--amber); }

/* locked tab (drama ④) + coming-soon pill */
.tab.locked, .tab[disabled] { opacity: .55; cursor: not-allowed; }
.tab.locked:hover { background: transparent; }
.badge-soon {
  font-size: var(--fs-xs); color: var(--amber-strong); background: var(--gold-soft);
  border-radius: var(--radius-pill); padding: 0 var(--space-2); margin-left: var(--space-1);
}

/* drama character cards */
.character-grid { display: grid; gap: var(--space-4); grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.character-card {
  display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: var(--space-4);
  padding: var(--space-4); border: 1px solid var(--line); border-radius: var(--radius-2);
  background: var(--bg);
}
.character-ref-box { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }
.character-ref-img, .character-ref-placeholder {
  width: 100%; aspect-ratio: 1 / 1; border: 1px solid var(--line); border-radius: var(--radius-1);
  background: var(--bg-sunken);
}
.character-ref-img { object-fit: contain; }
.character-ref-placeholder {
  display: flex; align-items: center; justify-content: center; color: var(--ink-3);
  font-size: var(--fs-sm); text-align: center; padding: var(--space-3);
}
.check-row { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--ink-2); font-size: var(--fs-sm); }
@media (max-width: 720px) {
  .character-card { grid-template-columns: 1fr; }
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
  // iter063 Part C: CTA_ACTIONS is DERIVED from the injected readiness catalog
  // (window.READINESS_CATALOG, sourced from src/readiness_catalog.py) so the
  // three former copies — here / errors._READINESS / book_runner._primary_blocker
  // — can no longer drift. label/action/cta_label/hint map from
  // label/cta_action/cta_label/cause. plan_fingerprint_stale is a frontend-only
  // synthetic kind (produced by jobActionKind, not a real readiness blocker), so
  // it stays defined locally.
  const CTA_ACTIONS = (function () {
    const out = {};
    const cat = window.READINESS_CATALOG || {};
    for (const kind in cat) {
      if (!Object.prototype.hasOwnProperty.call(cat, kind)) continue;
      const spec = cat[kind] || {};
      out[kind] = {
        label: spec.label,
        action: spec.cta_action,
        cta_label: spec.cta_label,
        hint: spec.cause,
      };
    }
    // iter 050 (B3-hint): the whole fingerprint failure family
    // (plan_fingerprint_mismatch / chapter_NN_plan_item_fingerprint_* /
    // start_point_fingerprint_*) maps here via jobActionKind.
    out.plan_fingerprint_stale = {
      label: "细纲已变更/过期",
      action: "run_plan_chapters",
      cta_label: "重新生成细纲",
      hint: "细纲在写作后被修改或重新生成。可重写受影响章节，或重新生成细纲后再续写。",
    };
    return out;
  })();
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
  // iter 050 (D1): keep status + payload on the thrown error and translate
  // the bare "workspace busy" 409 into an actionable message. Every caller
  // that renders err.message gets the friendly text for free.
  function _httpError(res, data) {
    let msg = data.error || ("HTTP " + res.status);
    if (res.status === 409 && data.running_job_id) {
      msg = "工作区正被另一任务占用（job " + String(data.running_job_id).slice(0, 8) +
        "…），请等待其完成或在任务页取消后重试";
    }
    const err = new Error(msg);
    err.status = res.status;
    err.payload = data;
    return err;
  }
  // iter062: one fetch wrapper that classifies failures into friendly codes
  // (network / timeout / bad_json) so every caller's catch can renderErrorCard.
  // Polling endpoints opt out of the 30s timeout (long jobs are expected).
  const POLL_URL_RE = /(\\/job\\/|\\/jobs\\/recent|\\/readiness|\\/logs\\/tail|\\/status|\\/cost)/;
  async function _fetchWrapped(url, opts) {
    opts = opts || {};
    let controller = null, timer = null;
    const isPoll = opts.poll || POLL_URL_RE.test(url);
    if (!isPoll && typeof AbortController !== "undefined") {
      controller = new AbortController();
      opts = Object.assign({}, opts, { signal: controller.signal });
      timer = setTimeout(function () { controller.abort(); }, 30000);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      const aborted = e && e.name === "AbortError";
      const err = new Error((aborted ? FRONT_ERROR_CATALOG.timeout : FRONT_ERROR_CATALOG.network).title);
      err.code = aborted ? "timeout" : "network";
      throw err;
    } finally {
      if (timer) clearTimeout(timer);
    }
    let data;
    try {
      data = await res.json();
    } catch (parseErr) {
      if (!res.ok) { const he = new Error("HTTP " + res.status); he.status = res.status; throw he; }
      const be = new Error(FRONT_ERROR_CATALOG.bad_json.title); be.code = "bad_json"; throw be;
    }
    if (!res.ok) throw _httpError(res, data);
    return data;
  }
  async function fetchJson(url, opts) {
    return _fetchWrapped(url, opts);
  }
  async function postJson(url, payload, opts) {
    return _fetchWrapped(url, Object.assign({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }, opts || {}));
  }
  async function putJson(url, payload, opts) {
    return _fetchWrapped(url, Object.assign({
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }, opts || {}));
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
    ensureLeaveGuardDelegate();
  }
  function statusBadge(status) {
    const raw = String(status || "blocked");
    const cls = raw.toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "blocked";
    return '<span class="badge ' + escapeHtml(cls) + '">' + escapeHtml(statusLabel(raw)) + "</span>";
  }
  const STATUS_LABELS = {
    succeeded: "已完成", completed: "已完成", ok: "成功", ready: "已就绪",
    pending: "等待中", queued: "排队中", running: "进行中", generating: "生成中",
    failed: "失败", error: "失败", retry_error: "本次失败", blocked: "已阻断",
    cancelled: "已取消", canceled: "已取消", unknown: "未知",
  };
  function statusLabel(status) {
    const raw = String(status || "unknown");
    return STATUS_LABELS[raw.toLowerCase()] || raw;
  }
  function verdictBadge(verdict) {
    if (!verdict) return '<span class="badge no-dot">—</span>';
    const v = String(verdict).toLowerCase();
    const cls = v === "approve" ? "approve" : v === "reject" ? "reject" : "abstain";
    const labels = { approve: "通过", reject: "驳回", abstain: "待定" };
    return '<span class="badge ' + cls + '">' + escapeHtml(labels[v] || verdict) + "</span>";
  }
  function finiteStyleNumber(value) {
    if (value == null || typeof value === "boolean") return null;
    if (typeof value === "string" && !value.trim()) return null;
    // Arrays and objects are never numeric fields, even if Number([]) happens
    // to coerce to zero. Keep badges and detail tables on the same strict path.
    if (typeof value === "object") return null;
    let number;
    try { number = Number(value); } catch (e) { return null; }
    return Number.isFinite(number) ? number : null;
  }
  function styleDriftBadge(drift) {
    if (!drift || !drift.status) {
      return '<span class="badge no-dot badge-muted">文风未检测</span>';
    }
    const severity = drift.severity ? String(drift.severity).toLowerCase() : "skipped";
    const score = finiteStyleNumber(drift.style_drift_score);
    const cls = severity === "ok" ? "approve" : severity === "warn" ? "warn" : severity === "red" ? "reject" : "no-dot badge-muted";
    const label = severity === "skipped"
      ? "文风已跳过"
      : "文风 " + severity + (Number.isFinite(score) ? " " + score.toFixed(2) : "");
    return '<span class="badge ' + cls + '">' + escapeHtml(label) + "</span>";
  }
  function styleRewriteBadge(meta) {
    if (!meta || meta.style_drift_unresolved !== true) return "";
    return '<span class="badge warn">文风改写未解决</span>';
  }
  function typeBadge(type) {
    if (type === "drama") {
      return '<span class="badge no-dot badge-drama">🎬 短剧</span>';
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
    return stepLabel(job.step) + " · " + statusLabel(job.status);
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
      if (action === "reload") {
        window.location.reload();
        return;
      }
      if (action === "go_jobs") {
        window.location.href = ws ? wsHref("/jobs") : "/library";
        return;
      }
      if (action === "go_workbench") {
        window.location.href = ws ? wsHref("/workbench") : "/library";
        return;
      }
      // iter068 (Cluster E): the generate-* CTAs. The forms that actually run
      // these jobs live on the workbench stage cards — on the workbench page we
      // smooth-scroll to the card; elsewhere (continue page, which has no
      // stage-prepare-card / stage-outline-card) we navigate to the workbench
      // with the anchor. kb_missing / extraction_coverage_missing both route to
      // stage ① (生成设定 / 重建续写底座); outline_missing/stale to stage ②.
      if (action === "run_prepare" || action === "run_rebuild_for_start") {
        gotoStage("stage-prepare-card", "prepare-form");
        return;
      }
      if (action === "run_debate") {
        gotoStage("stage-outline-card", "outline-form");
        return;
      }
      // show_diagnostics (and any unknown action) falls through to open the
      // readiness diagnostics panel below.
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
  // iter068 (Cluster E): scroll to a workbench stage card if it's on the current
  // page (workbench), else navigate to the workbench with the anchor (continue
  // page has no stage cards). Centralizes the cross-page "go fix it" routing.
  function gotoStage(cardId, formId) {
    const el = document.getElementById(formId) || document.getElementById(cardId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    window.location.href = ws ? (wsHref("/workbench") + "#" + cardId) : "/library";
  }
  // iter068 (Cluster E): map a catalog cta_action to the page/anchor that can
  // fix it, shared by the job-drawer CTA link. Mirrors bindCtaActions' routing.
  function ctaActionHref(action) {
    switch (action) {
      case "go_plan": return wsHref("/plan");
      case "run_debate": return wsHref("/workbench") + "#stage-outline-card";
      case "run_prepare":
      case "run_rebuild_for_start": return wsHref("/workbench") + "#stage-prepare-card";
      case "run_plan_chapters": return wsHref("/workbench") + "#stage-plan-card";
      default: return wsHref("/continue");
    }
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
  // iter062: friendly error cards. The backend hands every error response a
  // ``card`` ({code,title,cause,actions,trace_id,technical}); frontend-only
  // failures (network/timeout/bad JSON) carry an ``err.code`` we look up here.
  var FRONT_ERROR_CATALOG = {
    network: { code: "network", title: "连不上本地服务", cause: "本地服务可能没在运行，或端口被占用。请确认服务已启动后重试。", actions: [{ label: "刷新重试", action: "reload" }] },
    timeout: { code: "timeout", title: "请求超时", cause: "服务端响应太慢，任务可能仍在后台长跑。可去任务页查看进度。", actions: [{ label: "去任务页", action: "go_jobs" }] },
    bad_json: { code: "bad_json", title: "返回数据异常", cause: "服务端返回的内容不是预期格式，刷新后通常即可恢复。", actions: [{ label: "刷新重试", action: "reload" }] },
  };
  function _normalizeErrorCard(p) {
    if (p && p.payload && p.payload.card) return p.payload.card;
    if (p && p.card) return p.card;
    if (p && p.code && FRONT_ERROR_CATALOG[p.code]) return FRONT_ERROR_CATALOG[p.code];
    var msg = (p && p.payload && p.payload.error) || (p && p.message) ||
      (p && p.error) || (typeof p === "string" ? p : "") || "未知错误";
    return { code: "client_error", title: "出错了", cause: msg, actions: [], trace_id: "", technical: "" };
  }
  function renderErrorCard(payload) {
    var card = _normalizeErrorCard(payload);
    var actions = (card.actions || []).map(function (a) {
      if (a.href) return '<a class="btn btn-secondary btn-sm" href="' + escapeHtml(a.href) + '">' + escapeHtml(a.label) + "</a>";
      return '<button type="button" class="btn btn-secondary btn-sm" data-cta-action="' + escapeHtml(a.action || "") + '">' + escapeHtml(a.label) + "</button>";
    }).join("");
    return '<div class="error-card" role="alert">' +
      '<div class="error-card-head"><span class="error-card-icon" aria-hidden="true">⚠</span>' +
      '<div class="error-card-copy"><p class="error-card-title">' + escapeHtml(card.title || "出错了") + "</p>" +
      '<p class="error-card-cause">' + escapeHtml(card.cause || "") + "</p></div></div>" +
      (actions ? '<div class="error-card-actions cluster">' + actions + "</div>" : "") +
      (card.trace_id ? '<p class="error-card-trace">编号 <code>' + escapeHtml(card.trace_id) + "</code> " + copyButton(card.trace_id) + "</p>" : "") +
      (card.technical ? '<details class="details-fold error-card-tech"><summary>技术详情</summary><pre>' + escapeHtml(card.technical) + "</pre></details>" : "") +
      "</div>";
  }
  // iter063 A2: prefer the backend card's friendly title for one-line error
  // toasts. The `error` field may still carry the raw exception text for
  // back-compat (iter062 4xx/FNF convention), so reach into the card first.
  function errTitle(err) {
    if (err && err.payload && err.payload.card && err.payload.card.title) return err.payload.card.title;
    if (err && err.card && err.card.title) return err.card.title;
    const raw = err && err.payload && err.payload.error;
    const friendly = {
      real_image_would_be_overwritten: "已有付费生成的参考图，本地预览不会覆盖它",
      paid_image_state_requires_repair: "付费生图记录需要修复，已停止覆盖参考图",
    };
    if (raw && friendly[raw]) return friendly[raw];
    return (err && err.message) || "出错了";
  }
  // Translate a raw readiness blocker code into human text for the diagnostic
  // list (reuses CTA_ACTIONS; raw code still shown folded in the details).
  function readinessReasonText(code) {
    var k = String(code || "").split(":")[0];
    var cfg = CTA_ACTIONS[k];
    if (cfg && cfg.label) return cfg.label;
    var named = {
      overview_error: "概览数据读取失败",
      drama_progress_error: "短剧进度读取失败",
      readiness_error: "续写入口检查失败",
      chapter_plan_invalid: "章节计划文件损坏",
      preflight_failed: "工程预检未通过",
    };
    return named[k] || code || "未知阻断项";
  }
  function copyButton(text) {
    return (
      '<button class="copy-btn" type="button" data-copy="' + escapeHtml(text) + '">复制</button>'
    );
  }
  // iter072 (#7): copy with a non-secure-context fallback. navigator.clipboard
  // is undefined on plain HTTP (LAN beta over http://192.168.x.x), so the
  // modern path silently no-ops there. Fall back to a hidden <textarea> +
  // execCommand('copy'); if even that fails, the button says "手动复制" so the
  // user knows to select it themselves rather than being left guessing.
  function legacyCopy(value) {
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch (e) {
      return false;
    }
  }
  function copyText(value, btn) {
    function done(ok) {
      if (!btn) return;
      // Remember the real label once and clear any in-flight restore, so a rapid
      // double-click can't capture a transient "✓"/"手动复制" as the label and
      // leave the button stuck on it.
      if (!("_copyLabel" in btn)) btn._copyLabel = btn.textContent;
      if (btn._copyTimer) clearTimeout(btn._copyTimer);
      btn.textContent = ok ? "✓" : "手动复制";
      btn._copyTimer = setTimeout(function () { btn.textContent = btn._copyLabel; }, ok ? 900 : 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(
        function () { done(true); },
        function () { done(legacyCopy(value)); }
      );
      return;
    }
    done(legacyCopy(value));
  }
  function bindCopy(root) {
    (root || document).addEventListener("click", function (ev) {
      const btn = ev.target.closest("[data-copy]");
      if (!btn) return;
      copyText(btn.getAttribute("data-copy") || "", btn);
    });
  }
  bindCopy(document);

  // iter062: last-resort global boundary. Uncaught JS errors / rejected
  // promises surface as a lightweight toast instead of a silently frozen page.
  window.addEventListener("error", function () {
    try { showToast("页面出了点问题，可刷新重试", "error"); } catch (e) {}
  });
  window.addEventListener("unhandledrejection", function (ev) {
    try {
      const c = _normalizeErrorCard(ev && ev.reason);
      showToast(c.title || "出错了", "error");
    } catch (e) {}
  });

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
    // iter063 A7: "edit" was dropped when iter062 trimmed unimplemented tabs,
    // which broke the /chapter/N#edit deep-link (it IS implemented). Restore it.
    "body", "edit", "review", "lint", "style", "advisor", "history",
    "chapters", "outline", "decisions",
    "setup", "hook", "storyboard", "characters",
    "script", "storyboard-view", "characters-view", "export", "video",
  ];
  function bindHashTabs() {
    function prepare(list, listIndex) {
      const tabsRoot = list.parentElement;
      list.setAttribute("role", "tablist");
      list.querySelectorAll(".tab").forEach((tab, tabIndex) => {
        const key = tab.dataset.tab || String(tabIndex);
        const target = tabsRoot.querySelector("#tab-" + key);
        if (!tab.id) tab.id = "tab-control-" + listIndex + "-" + key;
        tab.setAttribute("role", "tab");
        if (target) {
          tab.setAttribute("aria-controls", target.id);
          target.setAttribute("role", "tabpanel");
          target.setAttribute("aria-labelledby", tab.id);
        }
        const selected = tab.classList.contains("active");
        tab.setAttribute("aria-selected", selected ? "true" : "false");
        tab.tabIndex = selected ? 0 : -1;
        if (target) target.hidden = !selected;
      });
    }
    function activate(tab) {
      if (!tab) return;
      const list = tab.closest(".tab-list");
      if (!list) return;
      const tabsRoot = list.parentElement;
      list.querySelectorAll(".tab").forEach((t) => {
        const selected = t === tab;
        t.classList.toggle("active", selected);
        t.setAttribute("aria-selected", selected ? "true" : "false");
        t.tabIndex = selected ? 0 : -1;
        const panel = tabsRoot.querySelector("#tab-" + t.dataset.tab);
        if (panel) {
          panel.classList.toggle("active", selected);
          panel.hidden = !selected;
        }
      });
    }
    document.querySelectorAll(".tab-list").forEach(prepare);
    function replaceActiveTabLocation(tabName) {
      if (!tabName) return;
      const url = new URL(location.href);
      if (url.searchParams.has("step")) url.searchParams.set("step", tabName);
      url.hash = tabName;
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
    document.addEventListener("click", function (ev) {
      const tab = ev.target.closest(".tab");
      if (!tab) return;
      // Locked tabs (e.g. drama ④) are inert — no activation/route.
      if (tab.disabled || tab.getAttribute("aria-disabled") === "true") return;
      activate(tab);
      if (tab.dataset.tab) {
        replaceActiveTabLocation(tab.dataset.tab);
      }
      loadTabPanel(tab.dataset.tab);
    });
    document.addEventListener("keydown", function (ev) {
      const tab = ev.target.closest && ev.target.closest('.tab[role="tab"]');
      if (!tab) return;
      const list = tab.closest(".tab-list");
      if (!list) return;
      const enabled = Array.from(list.querySelectorAll('.tab[role="tab"]')).filter((item) => (
        !item.disabled && item.getAttribute("aria-disabled") !== "true"
      ));
      if (!enabled.length) return;
      const current = enabled.indexOf(tab);
      let next = null;
      if (ev.key === "Home") next = enabled[0];
      else if (ev.key === "End") next = enabled[enabled.length - 1];
      else if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {
        next = enabled[(Math.max(0, current) + 1) % enabled.length];
      } else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
        next = enabled[(Math.max(0, current) - 1 + enabled.length) % enabled.length];
      }
      if (!next) return;
      ev.preventDefault();
      activate(next);
      next.focus();
      if (next.dataset.tab) replaceActiveTabLocation(next.dataset.tab);
      loadTabPanel(next.dataset.tab);
    });
    const params = new URLSearchParams(location.search || "");
    const initialFromQuery = params.get("step") || "";
    const initialFromHash = (location.hash || "").replace(/^#/, "");
    const initial = (_ALLOWED_TAB_KEYS.indexOf(initialFromHash) >= 0 ? initialFromHash : initialFromQuery);
    if (initial && _ALLOWED_TAB_KEYS.indexOf(initial) >= 0) {
      const t = document.querySelector('.tab[data-tab="' + initial + '"]');
      if (t) activate(t);
      replaceActiveTabLocation(initial);
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
      const data = await fetchJson(url);
      lazy.dataset.loaded = "1";
      const renderer = window["__renderPanel_" + tabName];
      if (renderer) renderer(lazy, data);
      else lazy.innerHTML = '<pre>' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
    } catch (err) {
      lazy.innerHTML = renderErrorCard(err);
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
          shelf.dataset.empty || "从一句话开新书、导入小说续写或新建短剧，开始你的第一部作品。",
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
      shelf.innerHTML = renderErrorCard(err);
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
      (type !== "drama" && blockers.length ? '<p class="alert error" style="margin-top:12px">' + escapeHtml(readinessReasonText(blockers[0])) + "</p>" : "") +
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
      if (summary) summary.innerHTML = renderErrorCard(err);
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
        hint = blockers.length ? readinessReasonText(blockers[0]) : "存在阻断项，需先处理。";
        cta = '<a class="btn btn-secondary" href="/w/' + encodeURIComponent(ws) + '/continue">查看待办</a>';
      }
      nextAction.innerHTML =
        '<p class="eyebrow ornament">下一步</p>' +
        '<h2>' + escapeHtml(hint) + '</h2>' +
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
          blockers.map(function (b) {
            return escapeHtml(readinessReasonText(b)) + ' <span class="muted">(' + escapeHtml(b) + ')</span>';
          }).join("<br>") + "</div>"
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
        .catch((e) => { statusBox.innerHTML = renderErrorCard(e); });
    }
    if (costBox) {
      costBox.innerHTML = skeleton(3);
      fetchJson(wsUrl("/cost"))
        .then((d) => { costBox.innerHTML = renderKV(d); })
        .catch((e) => { costBox.innerHTML = renderErrorCard(e); });
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
          : "创作与评审已完成。可以进入角色库继续整理视觉资产";
      }
    } catch (err) {
      box.innerHTML = renderErrorCard(err);
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

  // iter072 (#6): one focus-trap + dedup helper behind every modal. It records
  // the element that had focus, traps Tab/Shift+Tab inside the modal, closes on
  // Escape, restores focus to the trigger on close, and tears down any
  // already-open modal first so a double trigger can't stack two backdrops and
  // leak a keydown listener (settles iter071's deferred "全局 focus-trap + 模态
  // 去重" a11y debt). Caller queries its fields off `backdrop` first, then calls
  // mountModal (which appends to body + sets initial focus) and wires the
  // returned close() to its buttons / backdrop click.
  let _activeModalTeardown = null;
  function mountModal(backdrop, opts) {
    opts = opts || {};
    if (_activeModalTeardown) _activeModalTeardown();  // dedup: never stack modals
    const previousActive = document.activeElement;
    function focusables() {
      return Array.prototype.slice.call(backdrop.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter(function (el) { return el.offsetParent !== null; });
    }
    function onKeyDown(ev) {
      if (ev.key === "Escape") { ev.preventDefault(); close(); return; }
      if (ev.key !== "Tab") return;
      const els = focusables();
      if (!els.length) return;
      const first = els[0], last = els[els.length - 1];
      const act = document.activeElement;
      if (ev.shiftKey && (act === first || !backdrop.contains(act))) {
        ev.preventDefault(); last.focus();
      } else if (!ev.shiftKey && (act === last || !backdrop.contains(act))) {
        ev.preventDefault(); first.focus();
      }
    }
    let closed = false;
    function close() {
      if (closed) return;
      closed = true;
      document.removeEventListener("keydown", onKeyDown);
      backdrop.remove();
      if (_activeModalTeardown === close) _activeModalTeardown = null;
      if (previousActive && typeof previousActive.focus === "function") {
        try { previousActive.focus(); } catch (e) { /* trigger gone — ignore */ }
      }
      // iter073 (codex E): optional close hook so callers can reset state on
      // EVERY close path (stay button, backdrop click, AND Esc — which fires
      // this internal close directly). Backward-compatible: unset = no-op.
      if (typeof opts.onClose === "function") opts.onClose();
    }
    document.body.appendChild(backdrop);
    document.addEventListener("keydown", onKeyDown);
    _activeModalTeardown = close;
    setTimeout(function () {
      const target = opts.initialFocus || focusables()[0];
      if (target && typeof target.focus === "function") target.focus();
    }, 0);
    return close;
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
    const input = backdrop.querySelector("#modal-confirm-input");
    const confirmBtn = backdrop.querySelector("#modal-confirm-btn");
    const errBox = backdrop.querySelector("#modal-error");
    const closeModal = mountModal(backdrop, { initialFocus: input });
    input.addEventListener("input", function () {
      confirmBtn.disabled = input.value !== name;
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) {
        closeModal();
      }
    });
    confirmBtn.addEventListener("click", async function () {
      confirmBtn.disabled = true;
      errBox.innerHTML = '<div class="alert info">正在移动到 trash…</div>';
      try {
        const data = await postJson("/api/workspace/" + encodeURIComponent(name) + "/delete",
          { confirm: name });
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "已删除 《" + name + "》 → " + data.trashed_to },
          "/library"
        );
      } catch (err) {
        errBox.innerHTML = renderErrorCard(err);
        confirmBtn.disabled = false;
      }
    });
  }

  // iter071: map internal step ids (jobs.py STEP_HANDLERS keys) to the Chinese
  // the user should actually see — raw ids like "write-book" must never leak
  // into user-facing copy (the leave-guard modal surfaced this). Unknown ids
  // fall back to the id so a new backend step is still legible, not blank.
  const STEP_LABELS = {
    "normalize": "规范化原文", "split": "切分章节", "extract": "抽取设定",
    "compress": "构建知识库", "bootstrap": "生成实体提案", "apply-bootstrap": "应用实体提案",
    "debate": "生成大纲", "plan-chapters": "规划章节", "write-book": "续写正文",
    "review-chapter": "评审章节", "draft-once-dev": "试写一章",
    "auto-pipeline-greenfield": "一键开新书", "prepare-greenfield": "准备开新书",
    "rebuild-for-start": "重建续写底座", "expand-premise": "扩写设定",
    "extract-style": "提取文风",
    "drama-plan": "短剧站①核心设定", "drama-hooks": "短剧站②钩子",
    "drama-storyboard": "短剧站③分镜", "drama-characters": "短剧站④角色",
    "drama-review-assemble": "短剧站⑤评审组装",
    "drama_plan": "短剧站①核心设定", "drama_hooks": "短剧站②钩子",
    "drama_storyboard": "短剧站③分镜", "drama_character": "短剧站④角色",
    "drama_review": "短剧站⑤评审组装",
    "drama-video": "短剧视频生成",
    "drama-compose": "短剧本地合成交付",
  };
  function stepLabel(step) {
    return STEP_LABELS[step] || step || "任务";
  }

  // iter072 (#2): the leave-guard's primary button must name where it goes.
  // iter071 only split "/" (回首页) vs everything-else (去书架), so /trash,
  // /settings, /wizard and a sidebar workspace switch all mislabelled as
  // "去书架". Map each real destination; /w/{name}/ becomes "切到《name》".
  function leaveDestinationLabel(href) {
    if (href === "/") return "回首页";
    if (href === "/library") return "去书架";
    if (href === "/trash") return "去回收站";
    if (href === "/settings") return "去设置";
    if (href === "/wizard") return "去新建";
    // /w/{name}/... → switch workspace. Parse with string ops (the JS lives in
    // a non-raw Python string, where an escaped slash inside a regex literal
    // would trip a Python SyntaxWarning).
    const h = href || "";
    if (h.indexOf("/w/") === 0) {
      const rest = h.slice(3);
      const slash = rest.indexOf("/");
      let nm = slash >= 0 ? rest.slice(0, slash) : rest;
      if (nm) {
        try { nm = decodeURIComponent(nm); } catch (e) { /* stray % — use raw */ }
        return "切到《" + nm + "》";
      }
    }
    return "离开本页";
  }

  // iter070: leave-guard. The three in-app "leave this workspace" links (⌂→/,
  // brand & first breadcrumb→/library) carry data-leave-guard. On click we
  // SYNCHRONOUSLY preventDefault — an async job check can't beat the browser's
  // navigation otherwise — then ask /jobs/recent whether this workspace has a
  // pending/running job. None → navigate immediately. Active → a 3-way modal
  // (stay / cancel+leave / leave with jobs continuing in the background). We
  // only treat pending/running as active: historicalJobStatus() omits
  // "succeeded", so reusing it would falsely block a just-finished run. No
  // beforeunload — tab close / refresh stay unguarded (jobs survive anyway).
  let leaveGuardDelegateBound = false;
  // iter073 (codex E): guard the leave-check against an async race. Each click
  // bumps leaveGuardSeq and captures it; a /jobs/active response is honored only
  // if its seq is still the latest, so a slow first click can't navigate to its
  // (now-stale) destination after a second click. leaveGuardModalOpen collapses
  // rapid double-clicks to a single modal — the open modal keeps its ORIGINAL
  // destination and never silently jumps elsewhere.
  let leaveGuardSeq = 0;
  let leaveGuardModalOpen = false;
  function ensureLeaveGuardDelegate() {
    if (leaveGuardDelegateBound) return;
    leaveGuardDelegateBound = true;
    document.addEventListener("click", function (ev) {
      const link = ev.target && ev.target.closest ? ev.target.closest("[data-leave-guard]") : null;
      if (!link) return;
      if (!window.WORKSPACE_NAME) return;  // no workspace context → nothing to guard
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button === 1) return;
      const href = link.getAttribute("href") || "/";
      ev.preventDefault();  // synchronous — must precede the async check
      if (leaveGuardModalOpen) return;  // a modal is up; resolve it first
      const seq = ++leaveGuardSeq;
      checkLeaveGuard(href, seq);
    });
  }
  async function checkLeaveGuard(href, seq) {
    let active = [];
    try {
      // iter071 (codex F2): /jobs/active reads the in-memory pool directly, so a
      // just-enqueued pending job (started_at=None) can't be truncated out the
      // way /jobs/recent?n=10 could once enough terminal rows piled up. The
      // endpoint already returns only pending/running; the filter is a harmless
      // double guard against any future shape drift.
      const data = await fetchJson(wsUrl("/jobs/active"));
      if (seq !== leaveGuardSeq) return;  // a newer click superseded this one
      active = (data.jobs || []).filter(function (j) {
        return j.status === "pending" || j.status === "running";
      });
    } catch (err) {
      if (seq !== leaveGuardSeq) return;
      window.location.href = href;  // fail open — don't trap the user on a fetch error
      return;
    }
    if (seq !== leaveGuardSeq) return;
    if (!active.length) {
      window.location.href = href;
      return;
    }
    leaveGuardModalOpen = true;
    showLeaveGuardModal(href, active);
  }
  function showLeaveGuardModal(href, activeJobs) {
    const n = activeJobs.length;
    const leaveLabel = leaveDestinationLabel(href);
    // iter071 (codex F5): show Chinese step names (续写正文…), never raw ids.
    const steps = activeJobs.map(function (j) { return stepLabel(j.step); }).join("、");
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    // iter071 (codex F6): modal-footer-equal makes the three choices equal-width
    // and single-line; labels are kept short ("取消并离开"/"去书架") so they don't
    // wrap into the ragged, mismatched buttons the 3-way modal showed before. The
    // "任务后台继续" caveat lives in the body copy, so the leave button needn't
    // repeat it.
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="leave-guard-title">' +
      '<div class="modal-header" id="leave-guard-title">当前作品有任务正在运行</div>' +
      '<div class="modal-body">' +
      '<p>《' + escapeHtml(window.WORKSPACE_NAME) + '》还有 ' + n + ' 个任务在跑（' +
      escapeHtml(steps) + '）。<strong>离开本页不会停止它们</strong>，任务会在后台继续，' +
      '稍后可在任务页查看进度。</p>' +
      '<div id="leave-guard-error"></div>' +
      '</div>' +
      '<div class="modal-footer modal-footer-equal">' +
      '<button type="button" class="btn btn-ghost" data-modal-close>留在本页</button>' +
      '<button type="button" class="btn btn-danger" id="leave-guard-cancel-leave">取消并离开</button>' +
      '<button type="button" class="btn btn-primary" id="leave-guard-leave">' +
      escapeHtml(leaveLabel) + '</button>' +
      '</div>' +
      '</div>';
    const errBox = backdrop.querySelector("#leave-guard-error");
    const leaveBtn = backdrop.querySelector("#leave-guard-leave");
    const cancelLeaveBtn = backdrop.querySelector("#leave-guard-cancel-leave");
    const stayBtn = backdrop.querySelector("[data-modal-close]");
    // iter072 (#6): focus starts on the least-destructive "留在本页" (iter071
    // F3 intent), and the shared helper adds the Tab trap + focus-restore.
    // iter073 (codex E): onClose resets the single-modal guard on every
    // non-navigating close (stay / backdrop / Esc) so future leave clicks work.
    const closeModal = mountModal(backdrop, {
      initialFocus: stayBtn,
      onClose: function () { leaveGuardModalOpen = false; },
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) closeModal();
    });
    leaveBtn.addEventListener("click", function () {
      window.location.href = href;  // jobs keep running server-side
    });
    cancelLeaveBtn.addEventListener("click", async function () {
      cancelLeaveBtn.disabled = true;
      errBox.innerHTML = '<div class="alert info">正在请求取消…</div>';
      // best-effort: a job may finish between the check and the cancel (cancel
      // API returns 409); swallow per-job errors and leave regardless — the
      // user's intent is to navigate away.
      await Promise.all(activeJobs.map(function (j) {
        return postJson(wsUrl("/job/" + j.job_id + "/cancel")).catch(function () {});
      }));
      window.setPendingToastAndNavigate(
        { kind: "info", msg: "已请求取消 " + n + " 个任务" }, href
      );
    });
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
      if (chBox) chBox.innerHTML = renderErrorCard(err);
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
    // iter 053a: outline↔start-point staleness warning (audit A5).
    const oc = data.outline_consistency || {};
    let outlineWarn = '';
    // iter072 (#8): point Web users at the in-app action ("② 大纲 · 生成大纲" on
    // the workbench) instead of leaking a non-executable CLI command
    // (`debate --force`) they have no terminal to run.
    if (oc.checked && oc.stale) {
      outlineWarn =
        '<div class="alert error" style="margin-top:8px"><strong>辩论大纲陈旧：</strong>' +
        '大纲生成时的起点与当前起点不一致（' + escapeHtml((oc.codes || []).join(', ')) + '）。' +
        '请在工作台「② 大纲」重新生成大纲后再规划，否则章纲会跨时间线。</div>';
    } else if (oc.checked && oc.metadata_missing) {
      outlineWarn =
        '<div class="alert info" style="margin-top:8px">辩论大纲没有起点指纹' +
        '（指纹机制之前的存量产物）。在工作台「② 大纲」重新生成一次大纲即可刷新指纹。</div>';
    }
    box.innerHTML =
      '<span class="badge no-dot">起点 <code>' + escapeHtml(plan.start_chapter_id || "—") + '</code></span>' +
      '<span class="badge no-dot">指纹 <code>' + escapeHtml(fp) + '</code></span>' +
      '<span class="badge no-dot">已写 ' + drafts.length + ' / 计划 ' + target + '</span>' +
      outlineWarn;
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
      box.innerHTML = renderErrorCard(err);
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
        showToast("restore 失败：" + errTitle(err), "error");
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
    const input = backdrop.querySelector("#modal-purge-input");
    const btn = backdrop.querySelector("#modal-purge-btn");
    const err = backdrop.querySelector("#modal-purge-error");
    const close = mountModal(backdrop, { initialFocus: input });
    input.addEventListener("input", function () {
      btn.disabled = input.value !== entry;
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
    });
    btn.addEventListener("click", async function () {
      btn.disabled = true;
      err.innerHTML = '<div class="alert info">正在 purge…</div>';
      try {
        await postJson("/api/trash/" + encodeURIComponent(entry) + "/purge", { confirm: entry });
        close();
        showToast("已永久删除：" + entry, "info");
        await reloadTrashList();
      } catch (e) {
        err.innerHTML = renderErrorCard(e);
        btn.disabled = false;
      }
    });
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
  // iter 048b: four-stage workbench. Each stage fires its step job and the
  // next card is gated on the previous stage's artifact (GET /workbench).
  async function initWorkbench() {
    // iter068 (Cluster A): an existing book (has_start_point) must rebuild its
    // continuation base — NOT run greenfield onboarding. The stage ① job, and
    // the require_start_point gate on plan-chapters / write-book, all follow
    // lastWorkbenchStatus.has_start_point so the workbench never silently
    // bypasses the start-point consistency gate for a real continuation.
    const hasStartPoint = function () {
      return !!(lastWorkbenchStatus && lastWorkbenchStatus.has_start_point);
    };
    bindWorkbenchStage("prepare-form", "prepare-submit", "prepare-status",
      function () { return hasStartPoint() ? "rebuild-for-start" : "prepare-greenfield"; },
      function () {
        // rebuild = 补齐底座（reextract 默认 false，只补缺口）；greenfield = 强制重提。
        return hasStartPoint() ? { window: 10 } : { force: true };
      });
    bindWorkbenchStage("outline-form", "outline-submit", "outline-status", "debate", function () {
      return {};
    });
    bindWorkbenchStage("plan-chapters-form", "plan-chapters-submit", "plan-chapters-status", "plan-chapters", function (form) {
      // require_start_point follows has_start_point: an existing book MUST enforce
      // the gate (else plan drifts off the real start); a greenfield premise has
      // no prior start point so it stays false.
      return { target_chapters: Number(form.elements.target_chapters.value || 5), require_start_point: hasStartPoint() };
    });
    bindWorkbenchStage("write-book-form", "write-book-submit", "write-book-status", "write-book", function (form) {
      return {
        chapters: Number(form.elements.chapters.value || 1),
        tier: form.elements.tier ? form.elements.tier.value || "mid" : "mid",
        budget_cny: form.elements.budget_cny ? Number(form.elements.budget_cny.value || 10) : 10,
        require_start_point: hasStartPoint(),
        require_plan: true,
      };
    });
    bindOutlineSave();
    bindSettingsPanel();
    await refreshWorkbench();
  }
  // iter 050 (B3): stage ① on-demand KB / entity_graph editor. Loads only
  // when the user opens the panel — no extra fetches on the refresh loop.
  let settingsPanelInvalidate = null;
  function bindSettingsPanel() {
    const toggle = document.getElementById("settings-toggle");
    const panel = document.getElementById("settings-panel");
    const kbArea = document.getElementById("kb-md");
    const kbSave = document.getElementById("kb-save");
    if (!toggle || !panel || !kbArea || !kbSave) return;
    let loaded = false;
    async function loadPanelData() {
      try {
        const kb = await fetchJson(wsUrl("/kb"));
        if (!kbArea.dataset.dirty && document.activeElement !== kbArea) {
          kbArea.value = kb.content || "";
        }
        loaded = true;
      } catch (err) {
        kbArea.placeholder = "知识库尚未生成（" + err.message + "）";
      }
      await loadExpansionPanel();
      await renderEntityPanel();
      await loadStyleCardPanel();
    }
    // iter 050d (M-2): re-running stage ① regenerates KB + entity_graph —
    // an open panel must reload, or its relationship indices and content go
    // stale and a save would hit the wrong object (server echo-check is the
    // backstop; this keeps the UI honest proactively).
    settingsPanelInvalidate = function () {
      loaded = false;
      if (!panel.hidden) loadPanelData();
    };
    toggle.addEventListener("click", async function () {
      panel.hidden = !panel.hidden;
      toggle.textContent = panel.hidden ? "查看 / 编辑设定 ▾" : "收起设定 ▴";
      if (panel.hidden || loaded) return;
      await loadPanelData();
    });
    bindExpansionPanel();
    bindStyleCardPanel();
    kbArea.addEventListener("input", function () { kbArea.dataset.dirty = "1"; });
    kbSave.addEventListener("click", async function () {
      if (!kbArea.value.trim()) {
        showToast("知识库不能为空", "error");
        return;
      }
      kbSave.disabled = true;
      try {
        await putJson(wsUrl("/kb"), { content: kbArea.value });
        delete kbArea.dataset.dirty;
        showToast("知识库已保存；下游大纲 / 细纲将提示重新生成", "info");
        await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        kbSave.disabled = false;
      }
    });
  }
  // iter 051a: stage ① structured premise-expansion editor. Field ids map
  // 1:1 onto PremiseExpansion schema fields; list fields are one-per-line
  // textareas (same convention as the entity key_facts editor).
  const EXPANSION_FIELDS = [
    { id: "exp-genre-tone", key: "genre_tone", list: false },
    { id: "exp-protagonist", key: "protagonist", list: false },
    { id: "exp-world-notes", key: "world_notes", list: true },
    { id: "exp-central-conflict", key: "central_conflict", list: false },
    { id: "exp-ending-anchor", key: "ending_anchor", list: false },
    { id: "exp-arc-hints", key: "arc_hints", list: true },
  ];
  function expansionEls() {
    const els = {};
    for (const f of EXPANSION_FIELDS) {
      els[f.key] = document.getElementById(f.id);
      if (!els[f.key]) return null;
    }
    return els;
  }
  async function loadExpansionPanel() {
    const els = expansionEls();
    const emptyHint = document.getElementById("expansion-empty");
    if (!els) return;
    let data = null;
    try {
      data = await fetchJson(wsUrl("/premise-expansion"));
    } catch (err) {
      if (emptyHint) emptyHint.hidden = false;
      return;
    }
    if (emptyHint) emptyHint.hidden = true;
    const fields = (data && data.fields) || {};
    for (const f of EXPANSION_FIELDS) {
      const el = els[f.key];
      if (el.dataset.dirty || document.activeElement === el) continue;
      const value = fields[f.key];
      el.value = f.list ? ((value || []).join("\\n")) : (value || "");
    }
    // iter 053: 扩写重试后仍有空字段 → 建议补全提示（052 实测 shudian052
    // genre_tone/world_notes/central_conflict 空着落盘、靠 personas 兜底）。
    const incomplete = (data && data._incomplete_fields) || [];
    const statusBox = document.getElementById("expansion-status");
    if (statusBox && incomplete.length) {
      statusBox.innerHTML =
        '<div class="alert warn" data-incomplete-hint="1">扩写稿有未补全字段：' +
        escapeHtml(incomplete.join("、")) +
        '。建议手工补全后保存，或点「重新扩写」。</div>';
    } else if (statusBox && statusBox.querySelector('[data-incomplete-hint]')) {
      // 铁律⑨ B-L5：补全后摘牌（只清自己的提示，不动保存 toast）。
      statusBox.innerHTML = '';
    }
  }
  function bindExpansionPanel() {
    const els = expansionEls();
    const save = document.getElementById("expansion-save");
    const regen = document.getElementById("expansion-regen");
    const box = document.getElementById("expansion-status");
    if (!els || !save || !regen) return;
    for (const f of EXPANSION_FIELDS) {
      els[f.key].addEventListener("input", function () { els[f.key].dataset.dirty = "1"; });
    }
    save.addEventListener("click", async function () {
      const fields = {};
      for (const f of EXPANSION_FIELDS) {
        const raw = els[f.key].value;
        fields[f.key] = f.list
          ? raw.split("\\n").map(function (s) { return s.trim(); }).filter(function (s) { return s; })
          : raw.trim();
      }
      const hasContent = EXPANSION_FIELDS.some(function (f) {
        return f.list ? fields[f.key].length : fields[f.key];
      });
      if (!hasContent) {
        showToast("扩写稿不能全空", "error");
        return;
      }
      save.disabled = true;
      try {
        await putJson(wsUrl("/premise-expansion"), { fields: fields });
        for (const f of EXPANSION_FIELDS) delete els[f.key].dataset.dirty;
        showToast("扩写稿已保存；需重新生成设定（KB / 实体）才会生效", "info");
        await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        save.disabled = false;
      }
    });
    regen.addEventListener("click", async function () {
      if (!window.confirm("重新扩写会覆盖当前扩写稿（含手工修改），确定？")) return;
      regen.disabled = true;
      if (box) box.innerHTML = '<div class="alert info">正在重新扩写…</div>';
      try {
        const data = await postJson(wsUrl("/run"), { step: "expand-premise", params: { force: true } });
        await pollJob(data.job_id, box, regen, async function () {
          for (const f of EXPANSION_FIELDS) delete els[f.key].dataset.dirty;
          await loadExpansionPanel();
          await refreshWorkbench();
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
        regen.disabled = false;
      }
    });
  }
  // iter 056: 作家风格卡面板（仅 premise 自创书；list 字段单 textarea 每行一条，
  // 同 expansion 约定）。提取走 pollJob，与「重新扩写」同构。
  const STYLE_FIELDS = [
    { id: "style-name", key: "name", list: false },
    { id: "style-category", key: "category", list: false },
    { id: "style-rhythm", key: "rhythm", list: false },
    { id: "style-sentence", key: "sentence", list: false },
    { id: "style-diction", key: "diction", list: false },
    { id: "style-imagery", key: "imagery", list: false },
    { id: "style-dialogue", key: "dialogue", list: false },
    { id: "style-subtext", key: "subtext", list: false },
    { id: "style-narration", key: "narration", list: false },
    { id: "style-signatures", key: "signatures", list: true },
    { id: "style-taboo", key: "taboo", list: true },
  ];
  function styleEls() {
    const els = {};
    for (const f of STYLE_FIELDS) {
      els[f.key] = document.getElementById(f.id);
      if (!els[f.key]) return null;
    }
    return els;
  }
  async function renderPresetGrid() {
    const grid = document.getElementById("style-preset-grid");
    if (!grid) return;
    let presets = [];
    try { presets = (await fetchJson(wsUrl("/style-presets"))).presets || []; } catch (err) { return; }
    let activeId = "";
    try { activeId = (await fetchJson(wsUrl("/writer-style"))).preset_id || ""; } catch (err) {}
    grid.innerHTML = presets.map(function (p) {
      const c = p.card || {};
      const active = p.id === activeId;
      return '<article class="card style-preset-card' + (active ? ' active' : '') + '">' +
        '<div class="card-body"><h4>' + escapeHtml(c.name || "") + '</h4>' +
        '<div><span class="badge no-dot">' + escapeHtml(c.category || "") + '</span>' +
        (active ? ' <span class="badge">使用中</span>' : '') + '</div>' +
        '<p class="muted">' + escapeHtml((c.rhythm || "").slice(0, 38)) + '</p></div>' +
        '<div class="card-footer"><button type="button" class="btn btn-ghost btn-sm" data-style-activate="' +
        escapeHtml(p.id) + '"' + (active ? " disabled" : "") + '>' + (active ? "已使用" : "用这张") + '</button></div>' +
        '</article>';
    }).join("");
  }
  async function loadStyleCardPanel() {
    const fold = document.getElementById("style-card-fold");
    if (!fold) return;
    let hasStart = false;
    try { hasStart = !!(await fetchJson(wsUrl("/workbench"))).has_start_point; } catch (err) {}
    const body = document.getElementById("style-card-body");
    if (hasStart) {
      // 续写书：给 empty-state 占位，避免「功能去哪了」的疑惑（前端审查 P2-F）
      fold.hidden = false;
      if (body) body.innerHTML = '<div class="empty-state">✦ 风格卡仅用于自创书<p class="muted">续写作品文风以原著为准。</p></div>';
      return;
    }
    fold.hidden = false;
    await renderPresetGrid();
    const els = styleEls();
    const empty = document.getElementById("style-card-empty");
    if (!els) return;
    let data = null;
    try { data = await fetchJson(wsUrl("/writer-style")); } catch (err) { if (empty) empty.hidden = false; return; }
    if (empty) empty.hidden = true;
    const fields = (data && data.fields) || {};
    for (const f of STYLE_FIELDS) {
      const el = els[f.key];
      if (el.dataset.dirty || document.activeElement === el) continue;
      const v = fields[f.key];
      el.value = f.list ? ((v || []).join("\\n")) : (v || "");
    }
    const box = document.getElementById("style-card-status");
    const scrubbed = (data && data._scrubbed_fields) || [];
    if (box && scrubbed.length) {
      box.innerHTML = '<div class="alert warn">提取时检测到与样本重合的片段已自动剥离：' +
        escapeHtml(scrubbed.join("、")) + '。可手工补写后保存。</div>';
    } else if (box) { box.innerHTML = ""; }
  }
  function bindStyleCardPanel() {
    const els = styleEls();
    if (!els) return;
    const grid = document.getElementById("style-preset-grid");
    const save = document.getElementById("style-save");
    const extractBtn = document.getElementById("style-extract-btn");
    for (const f of STYLE_FIELDS) {
      els[f.key].addEventListener("input", function () { els[f.key].dataset.dirty = "1"; });
    }
    if (grid) grid.addEventListener("click", async function (ev) {
      const btn = ev.target.closest("[data-style-activate]");
      if (!btn) return;
      const pid = btn.getAttribute("data-style-activate");
      btn.disabled = true;
      try {
        await postJson(wsUrl("/writer-style/activate"), { preset_id: pid });
        for (const f of STYLE_FIELDS) delete els[f.key].dataset.dirty;
        showToast("已应用风格卡；下一章写作时生效", "info");
        await loadStyleCardPanel();
      } catch (err) {
        showToast("应用失败：" + errTitle(err), "error");
        btn.disabled = false;
      }
    });
    if (save) save.addEventListener("click", async function () {
      const fields = {};
      for (const f of STYLE_FIELDS) {
        const raw = els[f.key].value;
        fields[f.key] = f.list
          ? raw.split("\\n").map(function (s) { return s.trim(); }).filter(function (s) { return s; })
          : raw.trim();
      }
      const hasContent = STYLE_FIELDS.some(function (f) { return f.list ? fields[f.key].length : fields[f.key]; });
      if (!hasContent) { showToast("风格卡不能全空", "error"); return; }
      save.disabled = true;
      try {
        await putJson(wsUrl("/writer-style"), { fields: fields });
        for (const f of STYLE_FIELDS) delete els[f.key].dataset.dirty;
        showToast("风格卡已保存；下一章写作时生效", "info");
        await renderPresetGrid();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally { save.disabled = false; }
    });
    if (extractBtn) extractBtn.addEventListener("click", async function () {
      const textEl = document.getElementById("style-sample-text");
      const fileEl = document.getElementById("style-sample-file");
      const box = document.getElementById("style-extract-status");
      const fd = new FormData();
      if (fileEl && fileEl.files && fileEl.files[0]) fd.append("sample", fileEl.files[0]);
      if (textEl && textEl.value.trim()) fd.append("text", textEl.value);
      if (!fd.has("sample") && !fd.has("text")) { showToast("请粘贴样本或选择文件", "error"); return; }
      extractBtn.disabled = true;
      if (box) box.innerHTML = '<div class="alert info">正在提取风格特征…</div>';
      try {
        const resp = await fetch(wsUrl("/writer-style/extract"), { method: "POST", body: fd });
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
        await pollJob(data.job_id, box, extractBtn, async function () {
          for (const f of STYLE_FIELDS) delete els[f.key].dataset.dirty;
          await loadStyleCardPanel();
          showToast("已提取风格卡；可微调后保存", "info");
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
        extractBtn.disabled = false;
      }
    });
  }
  async function renderEntityPanel() {
    const box = document.getElementById("entity-panel");
    if (!box) return;
    let graph;
    try {
      graph = await fetchJson(wsUrl("/entity-graph"));
    } catch (err) {
      box.innerHTML = '<p class="muted">实体图谱尚未生成。</p>';
      return;
    }
    const entities = (graph.entities || []).filter(function (e) { return e && e.id; });
    const rels = graph.relationships || [];
    const entityNames = {};
    entities.forEach(function (e) { entityNames[String(e.id)] = e.name || e.id; });
    let html = '<div class="field"><label>实体（名称 / 核心事实 / 描写可编辑）</label></div>';
    entities.forEach(function (e, i) {
      const facts = (e.key_facts || []).join("\\n");
      html += '<div class="card" style="margin-bottom:8px"><div class="card-body">' +
        '<div class="field"><label for="ent-name-' + i + '">名称 <span class="muted">[' +
        escapeHtml(String(e.type || "entity")) + " · " + escapeHtml(String(e.id)) + ']</span></label>' +
        '<input type="text" id="ent-name-' + i + '" value="' + escapeHtml(e.name || "") + '"></div>' +
        '<div class="field"><label for="ent-facts-' + i + '">核心事实（每行一条）</label>' +
        '<textarea id="ent-facts-' + i + '" rows="3">' + escapeHtml(facts) + '</textarea></div>' +
        '<div class="field"><label for="ent-desc-' + i + '">描写</label>' +
        '<textarea id="ent-desc-' + i + '" rows="2">' + escapeHtml(e.description || "") + '</textarea></div>' +
        '<div class="form-actions" style="justify-content:flex-end">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-entity-save="' + i + '" data-entity-id="' + escapeHtml(String(e.id)) + '">保存实体</button>' +
        '</div></div></div>';
    });
    const activeRels = [];
    rels.forEach(function (r, idx) {
      const active = ((r && r.timeline) || []).find(function (t) { return t && t.active; });
      if (active) activeRels.push({ idx: idx, rel: r, active: active });
    });
    if (activeRels.length) {
      html += '<div class="field"><label>活跃关系（当前状态可编辑）</label></div>';
      activeRels.forEach(function (item) {
        const r = item.rel;
        const src = entityNames[String(r.src_id)] || r.src_id || "?";
        const dst = entityNames[String(r.dst_id)] || r.dst_id || "?";
        html += '<div class="field" style="margin-bottom:8px">' +
          '<label for="rel-state-' + item.idx + '">' + escapeHtml(src + " ↔ " + dst) +
          ' <span class="muted">(' + escapeHtml(String(r.relation_type || "关系")) + ')</span></label>' +
          '<div style="display:flex;gap:4px">' +
          '<input type="text" id="rel-state-' + item.idx + '" value="' + escapeHtml(item.active.state || "") + '" style="flex:1">' +
          '<button type="button" class="btn btn-ghost btn-sm" data-rel-save="' + item.idx + '"' +
          ' data-src-id="' + escapeHtml(String(r.src_id || "")) + '"' +
          ' data-dst-id="' + escapeHtml(String(r.dst_id || "")) + '">保存</button>' +
          '</div></div>';
      });
    }
    box.innerHTML = html;
    box.querySelectorAll("[data-entity-save]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const i = btn.dataset.entitySave;
        const fields = {
          name: document.getElementById("ent-name-" + i).value.trim(),
          key_facts: document.getElementById("ent-facts-" + i).value.split("\\n")
            .map(function (s) { return s.trim(); }).filter(function (s) { return s; }),
          description: document.getElementById("ent-desc-" + i).value.trim(),
        };
        if (!fields.name) {
          showToast("实体名称不能为空", "error");
          return;
        }
        btn.disabled = true;
        try {
          await putJson(wsUrl("/entity/" + encodeURIComponent(btn.dataset.entityId)), { fields: fields });
          showToast("实体已保存：" + fields.name, "info");
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
        } finally {
          btn.disabled = false;
        }
      });
    });
    box.querySelectorAll("[data-rel-save]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const idx = btn.dataset.relSave;
        const state = document.getElementById("rel-state-" + idx).value.trim();
        if (!state) {
          showToast("关系状态不能为空", "error");
          return;
        }
        btn.disabled = true;
        try {
          // iter 050d (M-2): echo src/dst so the server can detect a
          // regenerated graph (stale index) instead of editing the wrong rel.
          await putJson(wsUrl("/relationship/" + idx), {
            state: state,
            src_id: btn.dataset.srcId || "",
            dst_id: btn.dataset.dstId || "",
          });
          showToast("关系状态已保存", "info");
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
          if (err.payload && err.payload.stale_index) await renderEntityPanel();
        } finally {
          btn.disabled = false;
        }
      });
    });
  }
  function bindWorkbenchStage(formId, submitId, boxId, step, paramsFn) {
    const form = document.getElementById(formId);
    if (!form) return;
    const submit = document.getElementById(submitId);
    const box = document.getElementById(boxId);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (submit) submit.disabled = true;
      // iter068 (Cluster A): step may be a function so the same form can dispatch
      // a different job by current state — stage ① runs rebuild-for-start for an
      // existing book (has_start_point) but prepare-greenfield for a greenfield
      // premise. Resolved here at submit time, after refreshWorkbench populated
      // lastWorkbenchStatus.
      const stepName = typeof step === "function" ? step() : step;
      if (box) box.innerHTML = '<div class="alert info">正在运行 ' + escapeHtml(stepName) + "…</div>";
      try {
        const params = paramsFn ? paramsFn(form) : {};
        const data = await postJson(wsUrl("/run"), { step: stepName, params: params });
        await pollJob(data.job_id, box, submit, async () => {
          await refreshWorkbench();
          // iter 050d (M-2): stage ① rewrites KB/entity_graph — reload the
          // settings panel if it's open so indices don't go stale. Both the
          // greenfield and rebuild-for-start variants touch those artifacts.
          if ((stepName === "prepare-greenfield" || stepName === "rebuild-for-start") && settingsPanelInvalidate) settingsPanelInvalidate();
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
        if (submit) submit.disabled = false;
      }
    });
  }
  function bindOutlineSave() {
    const btn = document.getElementById("outline-save");
    const area = document.getElementById("outline-md");
    if (!btn || !area) return;
    area.addEventListener("input", function () {
      area.dataset.dirty = "1";
    });
    btn.addEventListener("click", async function () {
      if (!area.value.trim()) {
        showToast("大纲不能为空", "error");
        return;
      }
      btn.disabled = true;
      try {
        await putJson(wsUrl("/outline"), { outline: area.value });
        delete area.dataset.dirty;
        showToast("大纲已保存", "info");
        await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        btn.disabled = false;
      }
    });
  }
  function setStageEnabled(id, on) {
    const el = document.getElementById(id);
    if (el) el.disabled = !on;
  }
  // iter062: clickable step rail. done/current steps anchor to their stage
  // card (smooth-scroll via CSS); locked steps are inert with a lock glyph.
  function renderStepbar(st) {
    const bar = document.getElementById("workbench-stepbar");
    if (!bar) return;
    const steps = [
      { key: "prepare", label: "① 设定", target: "stage-prepare-card", done: !!st.has_kb, locked: false },
      { key: "outline", label: "② 大纲", target: "stage-outline-card", done: !!st.has_outline, locked: !st.has_kb },
      { key: "plan", label: "③ 细纲", target: "stage-plan-card", done: !!st.has_plan, locked: !st.has_outline },
      { key: "write", label: "④ 正文", target: "stage-write-card", done: st.stage === "done", locked: !st.has_plan },
    ];
    bar.innerHTML = steps.map(function (s) {
      const current = st.stage === s.key;
      const cls = "step" + (s.locked ? " locked" : s.done ? " done" : current ? " current" : "");
      const mark = s.locked ? '<span class="step-glyph lock" aria-hidden="true">🔒</span>'
        : s.done ? '<span class="step-glyph tick" aria-hidden="true">✓</span>'
        : '<span class="step-glyph" aria-hidden="true">·</span>';
      if (s.locked) {
        return '<li class="' + cls + '" aria-disabled="true">' + mark + escapeHtml(s.label) + "</li>";
      }
      return '<li class="' + cls + '"><a href="#' + s.target + '">' + mark + escapeHtml(s.label) + "</a></li>";
    }).join("");
  }
  async function refreshWorkbench() {
    let st;
    try {
      st = await fetchJson(wsUrl("/workbench"));
    } catch (err) {
      return;
    }
    const pill = document.getElementById("workbench-stage-pill");
    if (pill) {
      const labels = { prepare: "① 设定", outline: "② 大纲", plan: "③ 细纲", write: "④ 正文", done: "✓ 已出稿" };
      // iter062: surface a single "next step" primary CTA next to the badge.
      const next = !st.has_kb ? { l: st.has_start_point ? "重建续写底座" : "生成设定", t: "stage-prepare-card" }
        : !st.has_outline ? { l: "生成大纲", t: "stage-outline-card" }
        : !st.has_plan ? { l: "生成细纲", t: "stage-plan-card" }
        : st.stage !== "done" ? { l: "开始续写", t: "stage-write-card" }
        : null;
      const cta = next
        ? ' <a class="btn btn-primary btn-sm" href="#' + next.t + '">下一步：' + escapeHtml(next.l) + "</a>"
        : ' <a class="btn btn-secondary btn-sm" href="' + wsHref("/chapters") + '">查看章节</a>';
      pill.innerHTML = '<span class="badge">当前：' + escapeHtml(labels[st.stage] || st.stage || "?") + "</span>" + cta;
    }
    renderStepbar(st);
    // iter 051a: KB older than the (edited) expansion → tell the user to
    // re-run stage ① instead of silently writing on stale settings.
    const expansionStaleHint = document.getElementById("expansion-stale-hint");
    if (expansionStaleHint) {
      expansionStaleHint.innerHTML = st.expansion_stale
        ? '<div class="alert warn">扩写稿已更新：请重新「生成设定」（KB / 实体），下游大纲 / 细纲会随之提示重建。</div>'
        : "";
    }
    // Gate each stage on its prerequisite artifact (mtime-validated server-side).
    setStageEnabled("outline-submit", !!st.has_kb);
    setStageEnabled("outline-save", !!st.has_outline);
    setStageEnabled("plan-chapters-submit", !!st.has_outline);
    setStageEnabled("write-book-submit", !!st.has_plan);
    // iter 048c: re-label the plan-chapters button so users see that they're
    // RE-generating an existing plan (重生成 = re-plan from scratch, since the
    // backend already forces force=true; we drop the prior chapter_plan.json
    // and re-run generate_chapter_plan which calls _attach_plan_fingerprints,
    // so write-book's plan_fingerprint gate stays self-consistent — no手改
    // JSON or manual fingerprint plumbing involved).
    const planBtn = document.getElementById("plan-chapters-submit");
    if (planBtn) planBtn.textContent = st.has_plan ? "重新生成细纲" : "生成细纲";
    // Pull the read-only artifacts (outline + chapter_plan) in a single
    // fetch and refresh whatever sections have data. has_plan implies
    // has_outline in our gate, and outline_md回填 is gated on "user not editing".
    lastWorkbenchStatus = st;
    // iter068 (Cluster A): stage ① copy + submit label follow has_start_point —
    // an existing book rebuilds its continuation base, a greenfield premise
    // generates settings from scratch. Reset both branches so switching
    // workspaces never leaves stale copy.
    const prepareSubmit = document.getElementById("prepare-submit");
    const prepareSubtitle = document.getElementById("prepare-subtitle");
    const prepareHint = document.getElementById("prepare-hint");
    if (st.has_start_point) {
      if (prepareSubmit) prepareSubmit.textContent = "重建续写底座";
      if (prepareSubtitle) prepareSubtitle.textContent = "已有续写起点：补提取起点窗口并重建 KB / 实体图 / 锚点";
      if (prepareHint) prepareHint.textContent = "将对起点前最近章节补齐提取，并据此重建续写底座（补齐底座，不强制全量重提）。";
    } else {
      if (prepareSubmit) prepareSubmit.textContent = "生成设定";
      if (prepareSubtitle) prepareSubtitle.textContent = "从开书的一句话立意提取知识库与实体设定";
      if (prepareHint) prepareHint.textContent = "开书时填写的一句话已写入 seed.txt；点右侧生成设定（KB / 实体）。";
    }
    if (st.has_outline) {
      // iter 050 (D4): explicit loading placeholder on first paint so an
      // empty box never reads as "no plan exists".
      const previewBox = document.getElementById("plan-chapters-preview");
      if (previewBox && !planPreviewLoaded && planEditingChapter == null) {
        previewBox.className = "muted";
        previewBox.textContent = "细纲加载中…";
      }
      let plan;
      try {
        plan = await fetchJson(wsUrl("/plan"));
      } catch (err) {
        return;
      }
      const area = document.getElementById("outline-md");
      if (area && !area.dataset.dirty && document.activeElement !== area) {
        if (typeof plan.outline_md === "string") area.value = plan.outline_md;
      }
      renderPlanPreview(plan && plan.plan, st);
      planPreviewLoaded = true;
    }
  }
  // iter 050: structured per-chapter plan editing (workbench stage ③).
  // While an editor is open, periodic refreshes must not clobber the form.
  let planEditingChapter = null;
  let planPreviewLoaded = false;
  let lastPlanChapters = [];
  let lastWorkbenchStatus = null;
  function renderPlanPreview(plan, st) {
    const box = document.getElementById("plan-chapters-preview");
    if (!box) return;
    if (planEditingChapter != null) return;
    const chapters = (plan && plan.chapters) || [];
    lastPlanChapters = chapters;
    if (!chapters.length) {
      box.className = "muted";
      box.textContent = "尚未生成细纲。";
      return;
    }
    // iter 050 (D4): a plan that exists but failed the workbench mtime gate
    // (upstream KB/outline newer) renders greyed-out with an explicit stale
    // notice instead of masquerading as current.
    const stale = !!(st && st.has_plan === false);
    let html = "";
    if (stale) {
      html += '<p class="muted">细纲已过期（上游设定/大纲已更新），请重新生成。以下为旧细纲：</p>';
    }
    html += '<div class="kv-list compact"' + (stale ? ' style="opacity:.55"' : "") + '>';
    for (const ch of chapters) {
      const num = ch.chapter_no == null ? "?" : String(ch.chapter_no).padStart(2, "0");
      const title = ch.title || "(未命名)";
      const target = ch.target_chinese_chars ? "约 " + ch.target_chinese_chars + " 字" : "";
      html += '<div class="k">第' + escapeHtml(num) + '章</div>' +
        '<div class="v">' + escapeHtml(title) +
        (target ? ' <span class="muted">· ' + escapeHtml(target) + '</span>' : '') +
        (!stale && ch.chapter_no != null
          ? ' <button type="button" class="btn btn-ghost btn-sm" data-plan-edit="' + Number(ch.chapter_no) + '">编辑</button>'
          : '') +
        '</div>';
    }
    html += "</div>";
    box.className = "";
    box.innerHTML = html;
    box.querySelectorAll("[data-plan-edit]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openPlanEditor(Number(btn.dataset.planEdit));
      });
    });
  }
  function planEditorListRows(containerId, values, placeholder) {
    return values.map(function (value, i) {
      return '<div class="plan-edit-row" style="display:flex;gap:4px;margin-bottom:4px">' +
        '<input type="text" id="' + containerId + '-' + i + '" value="' + escapeHtml(value) + '" placeholder="' + escapeHtml(placeholder) + '" style="flex:1">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-row-del aria-label="删除此行">✕</button>' +
        '</div>';
    }).join("");
  }
  function bindPlanEditorList(container, placeholder, addBtn, max) {
    function rebindDel() {
      container.querySelectorAll("[data-row-del]").forEach(function (btn) {
        btn.onclick = function () { btn.parentElement.remove(); };
      });
    }
    rebindDel();
    addBtn.addEventListener("click", function () {
      if (container.querySelectorAll("input").length >= max) {
        showToast("最多 " + max + " 条", "error");
        return;
      }
      const row = document.createElement("div");
      row.className = "plan-edit-row";
      row.style.cssText = "display:flex;gap:4px;margin-bottom:4px";
      row.innerHTML = '<input type="text" placeholder="' + escapeHtml(placeholder) + '" style="flex:1">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-row-del aria-label="删除此行">✕</button>';
      container.appendChild(row);
      rebindDel();
    });
  }
  function planEditorListValues(container) {
    return Array.from(container.querySelectorAll("input"))
      .map(function (inp) { return inp.value.trim(); })
      .filter(function (v) { return v; });
  }
  function openPlanEditor(chapterNo) {
    const box = document.getElementById("plan-chapters-preview");
    const ch = lastPlanChapters.find(function (c) { return c.chapter_no === chapterNo; });
    if (!box || !ch) return;
    planEditingChapter = chapterNo;
    const num = String(chapterNo).padStart(2, "0");
    const textField = function (id, label, value, textarea) {
      return '<div class="field">' +
        '<label for="' + id + '">' + escapeHtml(label) + '</label>' +
        (textarea
          ? '<textarea id="' + id + '" rows="2">' + escapeHtml(value || "") + '</textarea>'
          : '<input type="text" id="' + id + '" value="' + escapeHtml(value || "") + '">') +
        '</div>';
    };
    box.innerHTML =
      '<div class="plan-edit-form">' +
      '<p><strong>编辑第' + escapeHtml(num) + '章细纲</strong></p>' +
      textField("plan-edit-title", "章节标题", ch.title) +
      textField("plan-edit-opening", "开场场景（一句话，writer 必须遵守）", ch.opening_scene, true) +
      '<div class="field"><label for="plan-edit-events-0">核心事件（2-7 条，本章必须发生）</label>' +
      '<div id="plan-edit-events">' + planEditorListRows("plan-edit-events", ch.key_events || [], "事件描述") + '</div>' +
      '<button type="button" class="btn btn-ghost btn-sm" id="plan-edit-events-add">＋ 添加事件</button></div>' +
      '<div class="field"><label for="plan-edit-rels-0">重点演进的关系（可空）</label>' +
      '<div id="plan-edit-rels">' + planEditorListRows("plan-edit-rels", ch.relationships_in_play || [], "如：路明非 ↔ 陈雯雯") + '</div>' +
      '<button type="button" class="btn btn-ghost btn-sm" id="plan-edit-rels-add">＋ 添加关系</button></div>' +
      textField("plan-edit-hook", "结尾钩子（留给下章承接）", ch.ending_hook, true) +
      '<div class="field"><label for="plan-edit-target">目标中文字数（2500-6000）</label>' +
      '<input type="number" id="plan-edit-target" min="2500" max="6000" step="100" value="' + Number(ch.target_chinese_chars || 4000) + '"></div>' +
      textField("plan-edit-purpose", "本章在全书弧线中的作用", ch.plot_purpose, true) +
      '<p class="muted">章号不可修改；整体调整请用「重新生成细纲」。保存会重算细纲指纹。</p>' +
      '<div style="display:flex;gap:8px;margin-top:8px">' +
      '<button type="button" class="btn btn-primary btn-sm" id="plan-edit-save">保存</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" id="plan-edit-cancel">取消</button>' +
      '</div></div>';
    box.className = "";
    bindPlanEditorList(document.getElementById("plan-edit-events"), "事件描述", document.getElementById("plan-edit-events-add"), 7);
    bindPlanEditorList(document.getElementById("plan-edit-rels"), "如：路明非 ↔ 陈雯雯", document.getElementById("plan-edit-rels-add"), 20);
    document.getElementById("plan-edit-cancel").addEventListener("click", function () {
      planEditingChapter = null;
      refreshWorkbench();
    });
    document.getElementById("plan-edit-save").addEventListener("click", async function () {
      const saveBtn = this;
      const fields = {
        title: document.getElementById("plan-edit-title").value.trim(),
        opening_scene: document.getElementById("plan-edit-opening").value.trim(),
        key_events: planEditorListValues(document.getElementById("plan-edit-events")),
        relationships_in_play: planEditorListValues(document.getElementById("plan-edit-rels")),
        ending_hook: document.getElementById("plan-edit-hook").value.trim(),
        target_chinese_chars: parseInt(document.getElementById("plan-edit-target").value, 10),
        plot_purpose: document.getElementById("plan-edit-purpose").value.trim(),
      };
      // Client-side pre-checks mirror ChapterPlanItem ranges; the server
      // (Pydantic) stays the source of truth.
      if (!fields.title || !fields.opening_scene || !fields.ending_hook || !fields.plot_purpose) {
        showToast("标题、开场、钩子、章节作用均不能为空", "error");
        return;
      }
      if (fields.key_events.length < 2 || fields.key_events.length > 7) {
        showToast("核心事件需要 2-7 条", "error");
        return;
      }
      if (!(fields.target_chinese_chars >= 2500 && fields.target_chinese_chars <= 6000)) {
        showToast("目标字数需在 2500-6000 之间", "error");
        return;
      }
      const draftCount = lastWorkbenchStatus ? lastWorkbenchStatus.draft_count || 0 : 0;
      if (draftCount > 0 && !window.confirm(
        "当前已写正文 " + draftCount + " 章。保存细纲修改后，这些章节的评审状态将过期，需要重写或重新评审。继续保存？"
      )) return;
      saveBtn.disabled = true;
      try {
        const res = await putJson(wsUrl("/chapter-plan/" + chapterNo), { fields: fields });
        planEditingChapter = null;
        const invalidated = res.written_chapters_invalidated || [];
        showToast("第" + num + "章细纲已保存" +
          (invalidated.length ? "；已写章节（" + invalidated.join(", ") + "）评审状态已过期" : ""));
        refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        saveBtn.disabled = false;
      }
    });
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
        box.innerHTML = renderErrorCard(err);
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
        box.innerHTML = renderErrorCard(err);
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
        jobBox.innerHTML = renderErrorCard(err);
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
      if (submit) submit.title = writeBookJobRunning ? "有任务进行中，请等待完成" : (data.status === 'blocked' ? "前置未就绪，请先处理上方阻断项" : "");
    } catch (err) {
      if (requestSeq !== readinessRequestSeq) return;
      panel.innerHTML = renderErrorCard(err);
      if (submit) { submit.disabled = true; submit.title = "续写入口检查失败，请稍后重试"; }
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
    if (blockers.length) details.push('<div class="alert error">' + blockers.map(function (b) {
      return escapeHtml(readinessReasonText(b)) + ' <span class="muted">(' + escapeHtml(b) + ')</span>';
    }).join("<br>") + "</div>");
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
      box.innerHTML = renderErrorCard(err);
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
    if (status === "succeeded") return icon + " 已完成" + (job.result_summary && job.result_summary.snapshot_path ? " · 快照已就绪" : "");
    if (reason) return icon + " " + statusLabel(status) + " · " + reason;
    if (line) return icon + " " + statusLabel(status) + " · " + line;
    return icon + " " + statusLabel(status);
  }
  function jobActionKind(job) {
    const detail = jobBlockedDetail(job);
    const reason = detail && detail.reason ? detail.reason : "";
    if (CTA_ACTIONS[reason]) return reason;
    if (/fingerprint/.test(reason)) return "plan_fingerprint_stale";
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
    // iter068 (Cluster E): route by the catalog cta_action to the page/anchor
    // that actually fixes the blocker, instead of hardcoding /plan vs /continue
    // (the old code sent outline_missing to the read-only /plan page).
    const target = ctaActionHref(cfg.action);
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
    const body = backdrop.querySelector(".modal-body");
    const footer = backdrop.querySelector(".modal-footer");
    // iter072 (#6): previously this modal had no Escape and no focus handling
    // at all; the shared helper grants it the trap + restore for free.
    const close = mountModal(backdrop);
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
      body.innerHTML = renderErrorCard(err);
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
      showToast("重试失败：" + errTitle(err), "error");
      if (btn) btn.disabled = false;
    }
  }
  // iter063 A1: render a terminal job failure / blocked state as a friendly
  // error card (human title + cause + CTA) instead of dumping the raw
  // "reason · error" line (e.g. "outline_stale · stale debate outline (…)").
  function renderJobFailureCard(job) {
    const detail = jobBlockedDetail(job);
    const reason = (detail && detail.reason) || "";
    const line = jobFailureLine(job);
    // A DIRECT readiness-kind match → friendly kind card (title + cause + CTA).
    const direct = CTA_ACTIONS[reason];
    if (job.status === "blocked" && direct) {
      return renderErrorCard({ card: {
        code: reason,
        title: direct.label,
        cause: direct.hint || line || "",
        actions: direct.action ? [{ label: direct.cta_label, action: direct.action }] : [],
        trace_id: job.trace_id || "",
      }});
    }
    // failed / aborted / budget_exceeded / blocked-with-unrecognized-reason:
    // surface the REAL error line as the cause (don't mask it with a generic
    // retry hint), and offer a retry CTA via jobActionKind where it fits.
    const titles = { aborted: "任务已取消", budget_exceeded: "预算已用尽", lost: "任务状态丢失", blocked: "续写入口受阻" };
    const fallback = CTA_ACTIONS[jobActionKind(job)];
    return renderErrorCard({ card: {
      code: job.status || "client_error",
      title: titles[job.status] || "任务未成功",
      cause: line || (fallback && fallback.hint) || "",
      actions: fallback && fallback.action ? [{ label: fallback.cta_label, action: fallback.action }] : [],
      trace_id: job.trace_id || "",
    }});
  }
  // iter068 (Cluster C): one document-level delegate for the cancel buttons
  // pollJob renders. Bound once (guard flag). Cancel state is server-driven —
  // the next 1s poll reflects job.cancel_requested — so we only disable the
  // button locally to prevent double-submits. POSTs the existing cancel API.
  let jobCancelDelegateBound = false;
  function ensureJobCancelDelegate() {
    if (jobCancelDelegateBound) return;
    jobCancelDelegateBound = true;
    document.addEventListener("click", async function (ev) {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-cancel-job]") : null;
      if (!btn) return;
      ev.preventDefault();
      const jobId = btn.getAttribute("data-cancel-job") || "";
      if (!jobId) return;
      btn.disabled = true;
      try {
        await postJson(wsUrl("/job/" + jobId + "/cancel"));
        showToast("已请求取消，等待当前不可中断步骤结束", "info");
      } catch (err) {
        btn.disabled = false;
        showToast("取消失败：" + errTitle(err), "error");
      }
    });
  }
  async function pollJob(jobId, box, submit, afterDone) {
    ensureJobCancelDelegate();
    while (true) {
      let job;
      try {
        job = await fetchJson(wsUrl("/job/" + jobId));
      } catch (err) {
        box.innerHTML = renderErrorCard(err);
        if (submit) submit.disabled = false;
        return;
      }
      const pct = Math.round((job.progress || 0) * 100);
      // iter068 (Cluster C): a cancel control + jobs-page link on the live card,
      // so a long run can be stopped from wherever it's polled (workbench /
      // continue), not just the wizard. Honest copy about the cooperative-cancel
      // boundary — a synchronous litellm call can't be hard-killed mid-flight.
      const cancelPending = !!job.cancel_requested;
      let waited = "";
      if (typeof job.started_at === "number" && isFinite(job.started_at)) {
        waited = " · 已等待 " + Math.max(0, Math.round(Date.now() / 1000 - job.started_at)) + " 秒";
      }
      box.innerHTML =
        '<div class="kv-list compact">' +
        '<div class="k">job</div><div class="v"><code>' + escapeHtml(jobId) + "</code></div>" +
        '<div class="k">status</div><div class="v">' + statusBadge(job.status || "?") + "</div>" +
        '<div class="k">step</div><div class="v">' + escapeHtml(job.current_step || "?") + "</div>" +
        '<div class="k">progress</div><div class="v">' + pct + "%</div>" +
        "</div>" +
        '<div class="progress"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<div class="form-actions" style="margin-top:8px">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-cancel-job="' + escapeHtml(jobId) + '"' + (cancelPending ? " disabled" : "") + ">取消任务</button>" +
        ' <a class="btn btn-ghost btn-sm" href="' + wsHref("/jobs") + '">任务页</a>' +
        "</div>" +
        (cancelPending
          ? '<div class="alert warn" style="margin-top:6px">已请求取消 · 当前步骤「' + escapeHtml(job.current_step || "?") + "」" + waited + "；最多再等当前一次不可中断调用或本地子进程结束。</div>"
          : "");
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
          // iter063 A1: friendly card (incl. CTA) instead of a raw reason dump.
          box.innerHTML += renderJobFailureCard(job);
          // Toast title mirrors the card: a direct readiness-kind label, else
          // the bare status (don't claim a fallback kind the card doesn't show).
          const d = jobBlockedDetail(job);
          const direct = CTA_ACTIONS[(d && d.reason) || ""];
          showToast(stepLabel + " · " + (direct ? direct.label : job.status), "error");
        }
        if (afterDone) await afterDone(job);
        return job;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  // ===== page: full-text search (iter075) =================================
  // XSS 安全高亮的根：后端只回原始片段文本 + 整数 offsets；这里全程用 DOM
  // (createElement/createTextNode) 构建，绝不 innerHTML 拼正文/用户输入。即使
  // 正文含 <script>/<img onerror> 也只当纯文本渲染。
  const SEARCH_SOURCE_LABELS = { original: "原文", draft: "续写", kb: "知识库" };

  function buildSnippet(snippet) {
    const frag = document.createDocumentFragment();
    const text = String((snippet && snippet.text) || "");
    const offs = (snippet && Array.isArray(snippet.offsets)) ? snippet.offsets : [];
    let cursor = 0;
    for (let i = 0; i < offs.length; i++) {
      const pair = offs[i];
      if (!Array.isArray(pair) || pair.length < 2) continue;
      const start = pair[0], end = pair[1];
      if (typeof start !== "number" || typeof end !== "number") continue;
      if (start < cursor || end > text.length || start >= end) continue;  // 越界防御
      if (start > cursor) frag.appendChild(document.createTextNode(text.slice(cursor, start)));
      const mark = document.createElement("mark");
      mark.appendChild(document.createTextNode(text.slice(start, end)));
      frag.appendChild(mark);
      cursor = end;
    }
    if (cursor < text.length) frag.appendChild(document.createTextNode(text.slice(cursor)));
    return frag;
  }

  function renderSearchHit(hit) {
    const card = document.createElement("article");
    card.className = "search-hit card";
    const head = document.createElement("div");
    head.className = "search-hit-head";
    const badge = document.createElement("span");
    badge.className = "badge source-" + String(hit.source);
    badge.textContent = SEARCH_SOURCE_LABELS[hit.source] || String(hit.source || "");
    head.appendChild(badge);
    let titleEl;
    if (hit.source === "draft" && hit.chapter_no != null) {
      titleEl = document.createElement("a");
      titleEl.href = wsHref("/chapter/" + encodeURIComponent(hit.chapter_no));
      titleEl.className = "search-hit-title";
    } else {
      titleEl = document.createElement("span");
      titleEl.className = "search-hit-title muted-link";
    }
    titleEl.textContent = String(hit.title || "");   // textContent，永不 innerHTML
    head.appendChild(titleEl);
    const count = document.createElement("span");
    count.className = "search-hit-count";
    count.textContent = (hit.match_count || 0) + " 处";
    head.appendChild(count);
    card.appendChild(head);
    const snippets = Array.isArray(hit.snippets) ? hit.snippets : [];
    for (let i = 0; i < snippets.length; i++) {
      const p = document.createElement("p");
      p.className = "search-snippet";
      p.appendChild(buildSnippet(snippets[i]));
      card.appendChild(p);
    }
    return card;
  }

  async function initSearch() {
    const input = document.getElementById("search-input");
    const box = document.getElementById("search-results");
    const summary = document.getElementById("search-summary");
    const sourcesBox = document.getElementById("search-sources");
    if (!input || !box || !summary) return;
    let timer = null, seq = 0;

    function selectedSources() {
      return Array.prototype.slice
        .call(sourcesBox ? sourcesBox.querySelectorAll("input:checked") : [])
        .map(function (c) { return c.value; });
    }
    function showEmpty(title, body) {
      box.innerHTML = "";                       // 静态文案，无用户输入拼接
      const div = document.createElement("div");
      div.className = "empty-state";
      const orn = document.createElement("span");
      orn.className = "ornament"; orn.textContent = "✦";
      const h = document.createElement("h3"); h.textContent = title;   // textContent 安全
      const p = document.createElement("p"); p.className = "muted"; p.textContent = body || "";
      div.appendChild(orn); div.appendChild(h); div.appendChild(p);
      box.appendChild(div);
    }

    function syncUrl(q, active) {
      // iter076（codex 低风险项）：q/sources 写回 URL（replaceState 不产生历史条目），
      // 刷新/分享链接可恢复检索状态。
      try {
        const params = new URLSearchParams(location.search || "");
        if (q) params.set("q", q); else params.delete("q");
        if (active && active.length && active.length < 3) params.set("sources", active.join(","));
        else params.delete("sources");
        const qs = params.toString();
        history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
      } catch (e) { /* URL API 不可用时静默跳过 */ }
    }

    async function run(fromEnter) {
      // iter076（codex 审查 iter075 #3）：seq 必须在任何 early return **之前**递增——
      // 否则清空输入/取消勾选后，慢的在途旧响应回来仍 mine===seq，把空态覆盖回结果。
      const mine = ++seq;
      const q = input.value.trim();
      summary.textContent = "";
      const active = selectedSources();
      syncUrl(q, active);
      if (!q) { showEmpty("输入关键词开始检索", "支持跨章定位实体、伏笔与关键词。"); return; }
      // iter076（codex 低风险项）：单字自动检索扫描面大——防抖路径要求 ≥2 字，
      // Enter 显式检索仍允许单字。
      if (!fromEnter && q.length < 2) {
        showEmpty("再输入一个字，或按 Enter 直接检索", "单字检索范围较大，自动检索需至少 2 字。");
        return;
      }
      if (!active.length) { showEmpty("请选择检索范围", "勾选上方原文 / 续写 / 知识库其中之一。"); return; }
      summary.textContent = "检索中…";
      let data;
      try {
        // sources 传给后端做范围检索：total_matches / truncated 因而反映真实范围。
        data = await fetchJson(wsUrl("/search?q=" + encodeURIComponent(q) +
          "&sources=" + encodeURIComponent(active.join(","))));
      } catch (err) {
        if (mine === seq) { box.innerHTML = renderErrorCard(err); summary.textContent = ""; }
        return;
      }
      if (mine !== seq) return;                  // 已被更新的查询覆盖，丢弃旧响应
      const hits = data.hits || [];              // 后端已按 sources 过滤，无需客户端二次过滤
      if (!hits.length) {
        summary.textContent = "";
        showEmpty("未找到「" + q + "」", "换个关键词，或调整上方语料范围试试。");
        return;
      }
      // iter076：total_matches 现在是截断前全局真实数，截断提示注明展示面。
      let s = "共 " + (data.total_matches || 0) + " 处命中 · " + hits.length + " 个单元";
      if (data.truncated) s += "（结果较多，已截断：仅展示前 " + hits.length + " 个单元的片段）";
      summary.textContent = s;
      const frag = document.createDocumentFragment();
      hits.forEach(function (h) { frag.appendChild(renderSearchHit(h)); });
      box.innerHTML = "";
      box.appendChild(frag);
    }

    function debouncedRun() { clearTimeout(timer); timer = setTimeout(run, 250); }  // 250ms 防抖
    input.addEventListener("input", debouncedRun);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { clearTimeout(timer); run(true); }
    });
    if (sourcesBox) sourcesBox.addEventListener("change", debouncedRun);   // 勾选变即重渲（含防抖）

    // iter076（codex 低风险项）：从 URL 恢复 q/sources——刷新不丢状态。恢复的 q
    // 视同显式检索（允许单字）。
    try {
      const params0 = new URLSearchParams(location.search || "");
      const src0 = (params0.get("sources") || "").trim();
      if (src0 && sourcesBox) {
        const want = src0.split(",");
        Array.prototype.slice.call(sourcesBox.querySelectorAll("input")).forEach(function (c) {
          c.checked = want.indexOf(c.value) !== -1;
        });
      }
      const q0 = (params0.get("q") || "").trim();
      if (q0) { input.value = q0; run(true); }
    } catch (e) { /* URL API 不可用时保持默认空态 */ }
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
      box.innerHTML = renderErrorCard(err);
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
    bindDraftEditor(num);
    try {
      const data = await fetchJson(wsUrl("/draft/" + num));
      renderChapterDetail(data);
    } catch (err) {
      renderChapterDetailLoadError(err);
    }
  }
  function renderChapterDetailLoadError(err) {
    const errorHtml = renderErrorCard(err);
    ["chapter-body", "tab-review", "tab-lint", "tab-style", "tab-advisor", "tab-history"].forEach((id) => {
      const box = document.getElementById(id);
      if (box) box.innerHTML = errorHtml;
    });
    const area = document.getElementById("draft-edit-area");
    const saveBtn = document.getElementById("draft-save");
    const saveReviewBtn = document.getElementById("draft-save-review");
    const statusBox = document.getElementById("draft-edit-status");
    if (area) {
      area.disabled = true;
      area.placeholder = "正文加载失败";
    }
    if (saveBtn) saveBtn.disabled = true;
    if (saveReviewBtn) saveReviewBtn.disabled = true;
    if (statusBox) statusBox.innerHTML = errorHtml;
  }
  // iter 050 (B1/B2): in-place draft edit + optional re-review job.
  function bindDraftEditor(num) {
    const area = document.getElementById("draft-edit-area");
    const saveBtn = document.getElementById("draft-save");
    const saveReviewBtn = document.getElementById("draft-save-review");
    const statusBox = document.getElementById("draft-edit-status");
    if (!area || !saveBtn || !saveReviewBtn) return;
    area.addEventListener("input", function () { area.dataset.dirty = "1"; });
    async function saveDraft() {
      const content = area.value;
      if (!content.trim()) {
        showToast("正文不能为空", "error");
        return null;
      }
      const res = await putJson(wsUrl("/draft/" + num), { content: content });
      delete area.dataset.dirty;
      return res;
    }
    saveBtn.addEventListener("click", async function () {
      saveBtn.disabled = saveReviewBtn.disabled = true;
      try {
        const res = await saveDraft();
        if (res) {
          if (statusBox) statusBox.innerHTML = "";
          showToast("第 " + num + " 章已保存；评审已过期，请重新评审", "info");
          const data = await fetchJson(wsUrl("/draft/" + num));
          renderChapterDetail(data);
        }
      } catch (err) {
        // iter063 A2: route through the error card (cause + action) in the
        // editor's status slot instead of a one-line raw-message toast.
        if (statusBox) statusBox.innerHTML = renderErrorCard(err);
        else showToast("保存失败：" + errTitle(err), "error");
      } finally {
        saveBtn.disabled = saveReviewBtn.disabled = false;
      }
    });
    saveReviewBtn.addEventListener("click", async function () {
      saveBtn.disabled = saveReviewBtn.disabled = true;
      try {
        const res = await saveDraft();
        if (!res) return;
        const job = await postJson(wsUrl("/run"), {
          step: "review-chapter",
          params: { chapter: Number(num) },
        });
        await pollJob(job.job_id, statusBox, null, async function () {
          const data = await fetchJson(wsUrl("/draft/" + num));
          renderChapterDetail(data);
        });
      } catch (err) {
        // iter063 A2: surface the friendly card in the editor status slot.
        if (statusBox) statusBox.innerHTML = renderErrorCard(err);
        else showToast("保存或评审失败：" + errTitle(err), "error");
      } finally {
        saveBtn.disabled = saveReviewBtn.disabled = false;
      }
    });
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
  function fmtStyleNumber(value, digits) {
    const n = finiteStyleNumber(value);
    if (n == null) return "—";
    return n.toFixed(digits == null ? 3 : digits);
  }
  function isPlainObject(value) {
    if (value == null || Object.prototype.toString.call(value) !== "[object Object]") return false;
    const proto = Object.getPrototypeOf(value);
    return proto === Object.prototype || proto === null;
  }
  function renderStyleRewriteAudit(rewriteMeta) {
    const rewriteCount = rewriteMeta ? finiteStyleNumber(rewriteMeta.style_rewrite_count) : null;
    const rewriteTriggered = Number.isFinite(rewriteCount) && rewriteCount >= 1;
    const before = rewriteMeta && isPlainObject(rewriteMeta.style_drift_before) ? rewriteMeta.style_drift_before : null;
    const after = rewriteMeta && isPlainObject(rewriteMeta.style_drift_after) ? rewriteMeta.style_drift_after : null;
    const improvement = rewriteMeta ? finiteStyleNumber(rewriteMeta.style_drift_improvement) : null;
    const rewriteStatus = rewriteMeta && typeof rewriteMeta.style_rewrite_status === "string"
      ? rewriteMeta.style_rewrite_status : "unknown";
    if (!rewriteTriggered && !(rewriteMeta && rewriteMeta.style_drift_unresolved === true)) return "";
    return '<h4>定向改写复测</h4>' +
      '<div class="kv-list compact">' +
      '<div class="k">result</div><div class="v">' + escapeHtml(rewriteStatus) +
        (rewriteMeta && rewriteMeta.style_rewrite_applied === true ? " · 已采用" : " · 已回退") + "</div>" +
      '<div class="k">before</div><div class="v">' + (before ? styleDriftBadge(before) : "—") + "</div>" +
      '<div class="k">after</div><div class="v">' + (after ? styleDriftBadge(after) : "—") + "</div>" +
      '<div class="k">improvement</div><div class="v">' +
        (Number.isFinite(improvement) ? escapeHtml(improvement.toFixed(3)) : "—") + "</div>" +
      '<div class="k">unresolved</div><div class="v">' +
        (rewriteMeta && rewriteMeta.style_drift_unresolved === true ? "是" : "否") + "</div>" +
      "</div>";
  }
  function renderStyleDriftPanel(drift, fingerprint, baselineHash, rewriteMeta) {
    const rewriteHtml = renderStyleRewriteAudit(rewriteMeta);
    if (!isPlainObject(drift) || !drift.status) {
      return '<div class="stack"><p class="muted">本章暂无文风漂移检测记录。</p>' + rewriteHtml + "</div>";
    }
    const basis = drift.basis || {};
    const score = drift.style_drift_score == null ? "—" : fmtStyleNumber(drift.style_drift_score, 3);
    const hash = basis.baseline_hash || (drift.status !== "skipped" ? baselineHash : "") || "";
    const top = Array.isArray(drift.top_dimensions) ? drift.top_dimensions.filter(isPlainObject) : [];
    const skipped = Array.isArray(drift.skipped_dimensions) ? drift.skipped_dimensions.filter(isPlainObject) : [];
    const rows = top.map((d) => (
      "<tr>" +
      "<td>" + escapeHtml(d.dimension || "") + "</td>" +
      "<td>" + fmtStyleNumber(d.current_value, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.baseline_value, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.tolerance, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.normalized_delta, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.dimension_score, 3) + "</td>" +
      "</tr>"
    )).join("");
    const skippedHtml = skipped.length
      ? '<div class="muted">跳过维度：' + skipped.slice(0, 8).map((d) => (
          escapeHtml((d.dimension || "?") + "(" + (d.reason || "skipped") + ")")
        )).join("，") + (skipped.length > 8 ? "…" : "") + "</div>"
      : "";
    const table = rows
      ? tableScroll('<table><thead><tr><th>维度</th><th>当前</th><th>Baseline</th><th>Tolerance</th><th>Delta</th><th>Score</th></tr></thead><tbody>' + rows + '</tbody></table>')
      : '<p class="muted">暂无可比较维度。</p>';
    return '<div class="stack">' +
      '<div class="kv-list compact">' +
      '<div class="k">severity</div><div class="v">' + styleDriftBadge(drift) + "</div>" +
      '<div class="k">score</div><div class="v">' + escapeHtml(score) + "</div>" +
      '<div class="k">baseline_hash</div><div class="v"><code>' + escapeHtml(hash ? String(hash).slice(0, 16) : "—") + "</code></div>" +
      '<div class="k">status</div><div class="v">' + escapeHtml(drift.status || "skipped") + (drift.reason ? " · " + escapeHtml(drift.reason) : "") + "</div>" +
      '<div class="k">fingerprint</div><div class="v">' + escapeHtml((fingerprint && fingerprint.status) || "—") + "</div>" +
      '</div>' +
      '<h4>偏离最高维度</h4>' +
      table +
      skippedHtml +
      rewriteHtml +
      "</div>";
  }
  function renderChapterDetail(data) {
    const meta = data.meta || {};
    const review = data.review || {};
    const num = data.chapter;
    const editArea = document.getElementById("draft-edit-area");
    const saveBtn = document.getElementById("draft-save");
    const saveReviewBtn = document.getElementById("draft-save-review");
    if (editArea) {
      editArea.disabled = false;
      editArea.placeholder = "";
    }
    if (saveBtn) saveBtn.disabled = false;
    if (saveReviewBtn) saveReviewBtn.disabled = false;
    // header bar
    const head = document.getElementById("chapter-meta-bar");
    if (head) {
      const cost = meta.cost_cny != null ? "¥" + Number(meta.cost_cny).toFixed(3) : "—";
      head.innerHTML =
        verdictBadge(meta.verdict || review.verdict) +
        styleDriftBadge(meta.style_drift) +
        styleRewriteBadge(meta) +
        '<span class="badge no-dot">rewrite ×' + (meta.rewrite_count || 0) + "</span>" +
        '<span class="badge no-dot">' + (meta.chinese_char_count || 0) + " 字</span>" +
        '<span class="badge no-dot">' + escapeHtml(cost) + "</span>" +
        (meta.needs_human_review ? '<span class="badge warn">需复核</span>' : "");
    }
    // edit tab — populate unless the user is mid-edit (mirrors outline-md)
    if (editArea && !editArea.dataset.dirty && document.activeElement !== editArea) {
      editArea.value = data.content || "";
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
    // style drift tab
    const styleBox = document.getElementById("tab-style");
    if (styleBox) {
      styleBox.innerHTML = renderStyleDriftPanel(meta.style_drift, meta.style_fingerprint, meta.baseline_hash, meta);
    }
    // advisor tab
    const advBox = document.getElementById("tab-advisor");
    if (advBox) {
      const suggestions = Array.isArray(meta.rewrite_suggestions)
        ? meta.rewrite_suggestions.filter(isPlainObject)
        : [];
      if (!suggestions.length) {
        advBox.innerHTML = '<p class="muted">advisor 未提出改写建议。</p>';
      } else {
        advBox.innerHTML = '<div class="stack">' + suggestions.map((s) => (
          '<div class="advisor-item">' +
          '<span class="type">' + escapeHtml(s.type || "rewrite") + "</span>" +
          (s._advisor ? '<span class="muted">来源：' + escapeHtml(s._advisor) + "</span>" : "") +
          '<div class="section">' + escapeHtml(s.section || "(整段)") + "</div>" +
          '<div class="guidance">' + escapeHtml(s.guidance || "") + "</div>" +
          "</div>"
        )).join("") + "</div>";
      }
    }
    // history tab (iter 074: + 多版本草稿 diff)
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
        '<div class="diff-panel">' +
        '<h4>多版本对比</h4>' +
        '<div class="diff-controls">' +
        '<label>基准 <select id="diff-v1"></select></label>' +
        '<span class="diff-arrow">→</span>' +
        '<label>对比 <select id="diff-v2"></select></label>' +
        '<button type="button" id="diff-run" class="btn btn-secondary btn-sm">对比</button>' +
        '</div>' +
        '<div id="diff-output" class="diff-output muted">载入版本…</div>' +
        '</div>';
      loadChapterDiffVersions(num);
    }
  }
  // iter 074: chapter version diff (current draft vs archived retry snapshots)
  // iter076（codex 审查 iter074 #4）：diffSeq stale guard——连续切版本/重渲染时，
  // 慢的旧响应不得覆盖新选择的结果（与搜索页 seq 同款）。
  let diffSeq = 0;
  async function loadChapterDiffVersions(num) {
    const out = document.getElementById("diff-output");
    const s1 = document.getElementById("diff-v1");
    const s2 = document.getElementById("diff-v2");
    if (!out || !s1 || !s2) return;
    const mine = ++diffSeq;
    let versions;
    try {
      const data = await fetchJson(wsUrl("/chapter/" + num + "/versions"));
      versions = data.versions || [];
    } catch (err) {
      if (mine !== diffSeq) return;
      out.className = "diff-output";
      out.innerHTML = renderErrorCard(err);
      return;
    }
    if (mine !== diffSeq) return;
    const controls = document.querySelector(".diff-controls");
    if (versions.length < 2) {
      if (controls) controls.style.display = "none";
      out.className = "diff-output muted";
      out.textContent = versions.length
        ? "本章只有当前草稿一个版本，暂无历史快照可对比。"
        : "本章暂无草稿版本。";
      return;
    }
    if (controls) controls.style.display = "";
    const optHtml = versions.map(function (v) {
      return '<option value="' + escapeHtml(v.id) + '">' + escapeHtml(v.label) +
        (v.verdict ? "（" + escapeHtml(v.verdict) + "）" : "") + "</option>";
    }).join("");
    s1.innerHTML = optHtml;
    s2.innerHTML = optHtml;
    s1.value = versions[1].id;  // newest snapshot as baseline
    s2.value = versions[0].id;  // current draft
    const runBtn = document.getElementById("diff-run");
    if (runBtn) runBtn.onclick = function () { runChapterDiff(num); };
    // iter076（codex 审查 iter074 #4）：下拉变化即自动重跑——否则旧结果静默挂着
    // 与新选择不符（对齐搜索页「勾选变即重渲」的行为）。
    s1.onchange = function () { runChapterDiff(num); };
    s2.onchange = function () { runChapterDiff(num); };
    runChapterDiff(num);
  }
  async function runChapterDiff(num) {
    const out = document.getElementById("diff-output");
    const s1 = document.getElementById("diff-v1");
    const s2 = document.getElementById("diff-v2");
    if (!out || !s1 || !s2) return;
    const mine = ++diffSeq;                     // early return 前递增（同搜索页教训）
    const v1 = s1.value;
    const v2 = s2.value;
    if (v1 === v2) {
      out.className = "diff-output muted";
      out.textContent = "请选择两个不同的版本。";
      return;
    }
    out.className = "diff-output muted";
    out.textContent = "对比中…";
    let data;
    try {
      data = await fetchJson(wsUrl("/chapter/" + num + "/diff?v1=" +
        encodeURIComponent(v1) + "&v2=" + encodeURIComponent(v2)));
    } catch (err) {
      if (mine !== diffSeq) return;
      out.className = "diff-output";
      out.innerHTML = renderErrorCard(err);
      return;
    }
    if (mine !== diffSeq) return;               // 已被更新的对比覆盖，丢弃旧响应
    if (data.identical) {
      out.className = "diff-output muted";
      out.textContent = "两个版本内容一致。";
      return;
    }
    out.className = "diff-output";
    const rows = (data.diff_lines || []).map(function (ln) {
      return '<div class="diff-line diff-' + escapeHtml(ln.type || "ctx") + '">' +
        escapeHtml(ln.text || "") + "</div>";
    }).join("");
    out.innerHTML = '<div class="diff-view">' + rows + "</div>";
  }
  function renderAgentReview(a) {
    // iter042 schema evolution: current reviewer output writes `scores`;
    // older artifacts used `sub_scores`, so the UI accepts both.
    const sub = (a.scores && Object.keys(a.scores).length ? a.scores : a.sub_scores) || {};
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
      box.innerHTML = renderErrorCard(err);
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
      costBox.innerHTML = renderErrorCard(err);
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
  function dramaEpisodeNo() {
    const value = Number(CHAPTER_NO == null ? 1 : CHAPTER_NO);
    return Number.isSafeInteger(value) && value >= 1 && value <= 100 ? value : 1;
  }

  function dramaApiUrl(path) {
    return dramaApiUrlFor(path, dramaEpisodeNo());
  }

  function dramaApiUrlFor(path, episodeNo) {
    const separator = String(path).includes("?") ? "&" : "?";
    return wsUrl(path + separator + "episode_no=" + encodeURIComponent(String(episodeNo)));
  }

  function dramaPayload(payload) {
    return Object.assign({}, payload || {}, { episode_no: dramaEpisodeNo() });
  }

  async function dramaGenerationPayload(step, payload, episodeNo) {
    const targetEpisode = Number(episodeNo || dramaEpisodeNo());
    const progress = await fetchJson(dramaApiUrlFor("/drama/progress", targetEpisode));
    const realSteps = progress.real_text_steps || {};
    const out = Object.assign({}, payload || {}, { episode_no: targetEpisode });
    if (realSteps[step] !== true) return out;

    const confirmed = window.confirm(
      "当前站使用真模型，可能产生费用。是否仅授权本次生成？"
    );
    if (!confirmed) throw new Error("已取消本次真模型生成");
    const budgetRaw = window.prompt("请输入本次预算上限（CNY，必须大于 0）", "10");
    if (budgetRaw == null) throw new Error("已取消本次真模型生成");
    const timeoutRaw = window.prompt("请输入本次超时分钟数（0 < 分钟数 <= 1440）", "10");
    if (timeoutRaw == null) throw new Error("已取消本次真模型生成");
    const budget = Number(budgetRaw);
    const timeout = Number(timeoutRaw);
    if (!Number.isFinite(budget) || budget <= 0) throw new Error("真模型预算必须大于 0");
    if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 1440) {
      throw new Error("真模型超时必须大于 0 且不超过 1440 分钟");
    }
    out.confirm_real_text = true;
    out.budget_cny = budget;
    out.timeout_minutes = timeout;
    const reconciled = window.confirm(
      "仅当这是失败后的重试，且你已核对上游任务状态与账单时选择“确定”；首次生成请选择“取消”。"
    );
    if (reconciled) {
      out.confirm_text_retry = true;
      out.confirm_upstream_status_and_billing_checked = true;
    }
    return out;
  }

  async function initDramaWrite() {
    bindHashTabs();
    bindHookPickDelegate();
    if (await resumeDramaActiveJob()) return;
    await loadStationSetup();
    await loadStationHooks();
    await loadStationStoryboard();
    await loadStationCharacters();
    await loadDramaProgress();
  }

  async function resumeDramaActiveJob() {
    try {
      const active = await fetchJson(wsUrl("/jobs/active"));
      const rows = active.jobs || [];
      const job = rows.find(function (row) { return String(row.step || "").indexOf("drama-") === 0; });
      if (!job || !job.job_id) return false;
      const detail = await fetchJson(wsUrl("/job/" + job.job_id));
      const params = detail.params || {};
      if (Number(params.episode_no || 1) !== dramaEpisodeNo()) return false;
      const stationByStep = {
        "drama-plan": "setup", "drama-hooks": "hook", "drama-storyboard": "storyboard",
        "drama-characters": "characters", "drama-review-assemble": "characters",
      };
      const station = stationByStep[detail.step];
      const pane = station ? document.querySelector('[data-station-pane="' + station + '"]') : null;
      if (!pane) return false;
      await pollJob(job.job_id, pane, null, async function (done) {
        if (done.status === "succeeded" && detail.step === "drama-review-assemble") {
          window.location.href = "/w/" + encodeURIComponent(WORKSPACE_NAME) + "/episode/" + encodeURIComponent(String(dramaEpisodeNo()));
          return;
        }
        await loadStationSetup();
        await loadStationHooks();
        await loadStationStoryboard();
        await loadStationCharacters();
        await loadDramaProgress();
      });
      return true;
    } catch (err) {
      return false;
    }
  }

  async function loadDramaProgress() {
    const box = document.getElementById("drama-write-progress");
    if (!box) return;
    try {
      const data = await fetchJson(dramaApiUrl("/drama/progress"));
      box.innerHTML = (data.stations || []).map(function (s) {
        const cls = s.status === "done" ? "ready" :
          s.status === "locked" ? "blocked" : "warn";
        const statusLabel = { done: "已完成", locked: "待前置步骤", todo: "待处理" }[s.status] || s.status;
        return '<span class="badge ' + cls + '">' + escapeHtml(s.label) +
          " · " + escapeHtml(statusLabel) + "</span>";
      }).join("");
    } catch (err) {
      box.innerHTML = renderErrorCard(err);
    }
  }

  async function loadStationSetup() {
    const pane = document.querySelector('[data-station-pane="setup"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(dramaApiUrl("/drama/progress"));
      const station = (data.stations || []).find((s) => s.id === "setup");
      pane.innerHTML = renderStationSetup(station, data.wizard_input);
      bindStationSetupActions();
    } catch (err) {
      pane.innerHTML = renderErrorCard(err);
    }
  }

  function renderStationSetup(station, wizardInput) {
    const status = station ? station.status : "todo";
    const data = station ? station.data : null;
    const core = (data && data.core_setup) || data || {};
    let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ① 核心设定</h3>' +
      '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + (status === "done" ? "已完成" : "待处理") + '</span></div>' +
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
      const continuationFields = dramaEpisodeNo() > 1
        ? '<div class="field"><label>本集主线推进</label><textarea name="episode_mainline" rows="2">' + escapeHtml(data.episode_mainline || "") + '</textarea></div>' +
          '<label class="check-row"><input type="checkbox" name="introduces_new_characters" ' + (data.introduces_new_characters ? "checked" : "") + '> 本集引入新角色（未勾选则沿用季角色并跳过站④生成）</label>'
        : "";
      html += '<form id="station-setup-form" class="stack">' +
        '<div class="field"><label>一句话故事</label>' +
        '<textarea name="logline" rows="2">' + escapeHtml(data.logline || "") + "</textarea></div>" +
        '<div class="field"><label>主角设定</label>' +
        '<textarea name="protagonist" rows="2">' + escapeHtml(core.protagonist || "") + "</textarea></div>" +
        '<div class="field"><label>反派 / 对手设定</label>' +
        '<textarea name="antagonist" rows="2">' + escapeHtml(core.antagonist || "") + "</textarea></div>" +
        '<div class="field"><label>情绪钩子</label>' +
        '<textarea name="emotional_hook" rows="2">' + escapeHtml(core.emotional_hook || "") + "</textarea></div>" +
        continuationFields +
        '<div class="form-actions">' +
        (dramaEpisodeNo() === 1 ? '<button type="button" class="btn btn-secondary" id="regenerate-setup">重新生成</button>' : '') +
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
          const data = await postJson(
            wsUrl("/drama/plan"), await dramaGenerationPayload("drama-plan", {})
          );
          const pane = document.querySelector('[data-station-pane="setup"]');
          await pollJob(data.job_id, pane, genBtn, async function (job) {
            if (job.status !== "succeeded") return;
            await loadStationSetup();
            await loadStationHooks();
            await loadStationStoryboard();
            await loadStationCharacters();
            await loadDramaProgress();
          });
        } catch (err) {
          showToast("生成失败：" + errTitle(err), "error");
          genBtn.disabled = false;
        }
      });
    }
    const regenBtn = document.getElementById("regenerate-setup");
    if (regenBtn) {
      regenBtn.addEventListener("click", async function () {
        regenBtn.disabled = true;
        try {
          const data = await postJson(
            wsUrl("/drama/plan"), await dramaGenerationPayload(
              "drama-plan", { confirm_new_text_revision: true }
            )
          );
          const pane = document.querySelector('[data-station-pane="setup"]');
          await pollJob(data.job_id, pane, regenBtn, async function (job) {
            if (job.status !== "succeeded") return;
            await loadStationSetup();
            await loadStationHooks();
            await loadStationStoryboard();
            await loadStationCharacters();
            await loadDramaProgress();
          });
        } catch (err) {
          showToast("重新生成失败：" + errTitle(err), "error");
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
        if (dramaEpisodeNo() > 1) {
          payload.episode_mainline = form.elements.episode_mainline.value;
          payload.introduces_new_characters = !!form.elements.introduces_new_characters.checked;
        }
        try {
          await putJson(wsUrl("/drama/setup"), dramaPayload(payload));
          showToast("已保存，进入站 ②", "info");
          const tab = document.querySelector('.tab[data-tab="hook"]');
          if (tab) tab.click();
          await loadStationHooks();
          await loadStationStoryboard();
          await loadStationCharacters();
          await loadDramaProgress();
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
        }
      });
    }
  }

  async function loadStationHooks() {
    const pane = document.querySelector('[data-station-pane="hook"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(dramaApiUrl("/drama/progress"));
      const station = (data.stations || []).find((s) => s.id === "hook");
      if (station && station.status === "locked") {
        pane.innerHTML = '<div class="alert info">请先完成站 ①</div>';
        return;
      }
      if (!station || !station.data) {
        const candidates = await fetchJson(dramaApiUrl("/drama/hook-candidates"));
        if (candidates.exists && (candidates.hooks || []).length) {
          renderHookCandidates(pane, candidates.hooks || []);
          return;
        }
      }
      pane.innerHTML = renderStationHooks(station);
      bindStationHooksActions();
    } catch (err) {
      pane.innerHTML = renderErrorCard(err);
    }
  }

  function renderStationHooks(station) {
    const status = station ? station.status : "todo";
    const data = station ? station.data : null;
    let html = '<div class="card"><div class="card-header"><h3 class="ornament">站 ② 钩子</h3>' +
      '<span class="badge ' + (status === "done" ? "ready" : "warn") + '">' + (status === "done" ? "已完成" : "待处理") + '</span></div>' +
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
        '<div class="k">钩子类型</div><div class="v"><code>' + escapeHtml(data.type || "") + "</code></div>" +
        '<div class="k">钩子内容</div><div class="v">' + escapeHtml(data.content || "") + "</div>" +
        '</div>' +
        '<div class="alert info">站 ② 已锁定，可以进入站 ③ 分镜。</div>';
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
        const pane = document.querySelector('[data-station-pane="hook"]');
        if (!pane) return;
        const data = await postJson(
          wsUrl("/drama/hooks"), await dramaGenerationPayload("drama-hooks", { confirm_new_text_revision: true })
        );
        await pollJob(data.job_id, pane, btn, async function (job) {
          if (job.status !== "succeeded") return;
          const candidates = await fetchJson(dramaApiUrl("/drama/hook-candidates"));
          renderHookCandidates(pane, candidates.hooks || []);
        });
      } catch (err) {
        showToast("生成失败：" + errTitle(err), "error");
        btn.disabled = false;
      }
    });
  }

  function renderHookCandidates(pane, hooks) {
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
        await putJson(wsUrl("/drama/setup"), dramaPayload({ hook: pane.__hooks[idx] }));
        showToast("钩子已锁定", "info");
        const tab = document.querySelector('.tab[data-tab="storyboard"]');
        if (tab) tab.click();
        await loadStationHooks();
        await loadStationStoryboard();
        await loadStationCharacters();
        await loadDramaProgress();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
        pane.querySelectorAll("[data-hook-pick]").forEach((b) => { b.disabled = false; });
      }
    });
  }

  async function loadStationStoryboard() {
    const pane = document.querySelector('[data-station-pane="storyboard"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const progress = await fetchJson(dramaApiUrl("/drama/progress"));
      const station = (progress.stations || []).find((s) => s.id === "storyboard");
      if (station && station.status === "locked") {
        pane.innerHTML = '<div class="alert info">请先完成站 ② 钩子。</div>';
        return;
      }
      const data = await fetchJson(dramaApiUrl("/drama/storyboard"));
      if (!data.exists || !data.storyboard) {
        pane.__storyboard = null;
        pane.innerHTML = renderStationStoryboardEmpty();
      } else {
        pane.__storyboard = data.storyboard;
        pane.innerHTML = renderStationStoryboard(data.storyboard, data.soft_warnings || []);
        updateStoryboardDuration(pane);
      }
      bindStationStoryboardActions();
    } catch (err) {
      pane.innerHTML = renderErrorCard(err);
    }
  }

  function renderStationStoryboardEmpty() {
    return '<div class="card"><div class="card-header"><h3 class="ornament">站 ③ 分镜</h3>' +
      '<span class="badge warn">待处理</span></div><div class="card-body">' +
      '<div class="empty-state"><span class="ornament">✦</span>' +
      '<h3>等待生成分镜表</h3>' +
      '<p class="muted">站 ③ 会把钩子拆成 6 到 9 个可编辑镜头。</p>' +
      '<button type="button" class="btn btn-primary" id="generate-storyboard">▸ 生成分镜表</button>' +
      '</div></div></div>';
  }

  function renderStationStoryboard(board, warnings) {
    const shots = board.shots || [];
    const warningHtml = warnings && warnings.length
      ? '<div class="alert warn">软提醒：' + warnings.map(warningText).map(escapeHtml).join("；") + '</div>'
      : "";
    const head = '<table class="table storyboard-table"><thead><tr>' +
      '<th>#</th><th>景别</th><th>运镜</th><th>秒</th><th>画面</th><th>旁白</th><th>台词</th><th>高光</th><th>操作</th>' +
      '</tr></thead><tbody>';
    const rows = shots.map(renderStoryboardRow).join("");
    return '<div class="card"><div class="card-header"><h3 class="ornament">站 ③ 分镜</h3>' +
      '<span class="badge ready">已完成</span></div><div class="card-body stack">' +
      '<form id="station-storyboard-form" class="stack">' +
      '<div class="form-grid-2">' +
      '<div class="field"><label>标题</label><input name="title" value="' + escapeHtml(board.title || "") + '"></div>' +
      '<div class="field"><label>目标时长</label><input name="target_duration_seconds" type="number" min="30" max="180" value="' + Number(board.target_duration_seconds || 60) + '"></div>' +
      '</div>' +
      '<div class="field"><label>本集剧情</label><textarea name="narrative" rows="3">' + escapeHtml(board.narrative || "") + '</textarea></div>' +
      warningHtml +
      '<div class="cluster" style="justify-content:space-between">' +
      '<strong class="storyboard-duration" data-storyboard-duration></strong>' +
      '<div class="cluster"><button type="button" class="btn btn-secondary btn-sm" data-storyboard-add>＋ 添加镜头</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-storyboard-clear-highlight>清空高光</button></div>' +
      '</div>' +
      tableScroll(head + rows + '</tbody></table>') +
      '<div class="form-actions">' +
      '<button type="button" class="btn btn-secondary" id="regenerate-storyboard">重新生成</button>' +
      '<button type="submit" class="btn btn-primary">保存并进入站 ④ →</button>' +
      '</div></form></div></div>';
  }

  function renderStoryboardRow(shot, idx, allShots) {
    const num = idx + 1;
    return '<tr data-shot-row="' + idx + '">' +
      '<td><strong>' + num + '</strong><input type="hidden" data-field="beat" value="' + escapeHtml(shot.beat || "") + '"></td>' +
      '<td><select data-field="shot_size">' + storyboardOptions(["特写", "近景", "中景", "全景", "远景"], shot.shot_size) + '</select></td>' +
      '<td><select data-field="camera_movement">' + storyboardOptions(["固定", "推", "拉", "摇", "移", "跟", "升降"], shot.camera_movement) + '</select></td>' +
      '<td><input type="number" min="1" max="30" data-field="duration_seconds" value="' + Number(shot.duration_seconds || 1) + '"></td>' +
      '<td><textarea rows="3" data-field="visual">' + escapeHtml(shot.visual || "") + '</textarea>' +
      '<textarea rows="2" data-field="ai_draw_prompt" placeholder="AI 绘画 prompt">' + escapeHtml(shot.ai_draw_prompt || "") + '</textarea></td>' +
      '<td><textarea rows="3" data-field="narration">' + escapeHtml(shot.narration || "") + '</textarea></td>' +
      '<td><textarea rows="3" data-field="dialogue">' + escapeHtml(shot.dialogue || "") + '</textarea></td>' +
      '<td><input type="radio" name="storyboard-highlight" data-field="is_highlight" ' + (shot.is_highlight ? "checked" : "") + '></td>' +
      '<td><div class="storyboard-actions">' +
      '<button type="button" class="btn btn-icon" title="上移" data-shot-move="up">↑</button>' +
      '<button type="button" class="btn btn-icon" title="下移" data-shot-move="down">↓</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-shot-rewrite="' + num + '">重生</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-shot-delete="' + idx + '"' + (allShots.length <= 6 ? ' disabled title="至少保留 6 个镜头"' : '') + '>删除</button>' +
      '</div></td></tr>';
  }

  function storyboardOptions(values, current) {
    return values.map(function (v) {
      return '<option value="' + escapeHtml(v) + '"' + (v === current ? " selected" : "") + '>' + escapeHtml(v) + '</option>';
    }).join("");
  }

  function warningText(code) {
    const text = String(code);
    if (text === "highlight_missing") return "尚未选择高光镜头";
    if (text === "highlight_multiple") return "高光镜头超过 1 个";
    if (text === "first_shot_hook_shape") return "首镜建议 2-3 秒特写或近景";
    if (text === "last_shot_duration") return "末镜建议 8-10 秒";
    if (text.indexOf("duration_delta:") === 0) return "总时长偏离目标 " + text.split(":")[1] + " 秒";
    if (text.indexOf("dialogue_too_long:") === 0) return "有台词单句超过 15 字";
    return text;
  }

  function collectStoryboardFromPane(pane) {
    const base = pane.__storyboard || {};
    const form = document.getElementById("station-storyboard-form");
    const rows = Array.from(pane.querySelectorAll("[data-shot-row]"));
    const shots = rows.map(function (tr, idx) {
      const get = function (field) {
        const el = tr.querySelector('[data-field="' + field + '"]');
        return el ? el.value : "";
      };
      const high = tr.querySelector('[data-field="is_highlight"]');
      return {
        shot_no: idx + 1,
        beat: get("beat"),
        shot_size: get("shot_size"),
        camera_movement: get("camera_movement"),
        duration_seconds: Number(get("duration_seconds") || 1),
        visual: get("visual"),
        narration: get("narration"),
        dialogue: get("dialogue"),
        ai_draw_prompt: get("ai_draw_prompt"),
        is_highlight: !!(high && high.checked),
      };
    });
    return Object.assign({}, base, {
      title: form && form.elements.title ? form.elements.title.value : (base.title || ""),
      target_duration_seconds: form && form.elements.target_duration_seconds ? Number(form.elements.target_duration_seconds.value || 60) : (base.target_duration_seconds || 60),
      narrative: form && form.elements.narrative ? form.elements.narrative.value : (base.narrative || ""),
      shots: shots,
    });
  }

  function bindStationStoryboardActions() {
    const pane = document.querySelector('[data-station-pane="storyboard"]');
    if (!pane) return;
    const genBtn = document.getElementById("generate-storyboard");
    if (genBtn) {
      genBtn.addEventListener("click", async function () {
        genBtn.disabled = true;
        try {
          const data = await postJson(
            wsUrl("/drama/storyboard"), await dramaGenerationPayload("drama-storyboard", {})
          );
          await pollJob(data.job_id, pane, genBtn, async function (job) {
            if (job.status !== "succeeded") return;
            await loadStationStoryboard();
            await loadStationCharacters();
            await loadDramaProgress();
          });
        } catch (err) {
          showToast("生成失败：" + errTitle(err), "error");
          genBtn.disabled = false;
        }
      });
      return;
    }
    const form = document.getElementById("station-storyboard-form");
    if (!form) return;
    form.addEventListener("input", function () { updateStoryboardDuration(pane); });
    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      try {
        const payload = collectStoryboardFromPane(pane);
        const data = await putJson(wsUrl("/drama/storyboard"), dramaPayload({ storyboard: payload }));
        pane.__storyboard = data.storyboard;
        pane.innerHTML = renderStationStoryboard(data.storyboard, data.soft_warnings || []);
        bindStationStoryboardActions();
        updateStoryboardDuration(pane);
        await loadDramaProgress();
        await loadStationCharacters();
        showToast("分镜表已保存，进入站 ④", "info");
        const charactersTab = document.querySelector('.tab[data-tab="characters"]');
        if (charactersTab) charactersTab.click();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      }
    });
    const regenBtn = document.getElementById("regenerate-storyboard");
    if (regenBtn) {
      regenBtn.addEventListener("click", async function () {
        regenBtn.disabled = true;
        try {
          const data = await postJson(
            wsUrl("/drama/storyboard"), await dramaGenerationPayload(
              "drama-storyboard", { confirm_new_text_revision: true }
            )
          );
          await pollJob(data.job_id, pane, regenBtn, async function (job) {
            if (job.status !== "succeeded") return;
            await loadStationStoryboard();
            await loadStationCharacters();
            await loadDramaProgress();
          });
        } catch (err) {
          showToast("重新生成失败：" + errTitle(err), "error");
          regenBtn.disabled = false;
        }
      });
    }
    pane.querySelectorAll("[data-shot-move]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const row = btn.closest("[data-shot-row]");
        const idx = Number(row ? row.getAttribute("data-shot-row") : -1);
        const direction = btn.getAttribute("data-shot-move");
        const board = collectStoryboardFromPane(pane);
        const next = direction === "up" ? idx - 1 : idx + 1;
        if (idx < 0 || next < 0 || next >= board.shots.length) return;
        const tmp = board.shots[idx];
        board.shots[idx] = board.shots[next];
        board.shots[next] = tmp;
        pane.__storyboard = board;
        pane.innerHTML = renderStationStoryboard(board, []);
        bindStationStoryboardActions();
        updateStoryboardDuration(pane);
      });
    });
    const addBtn = pane.querySelector("[data-storyboard-add]");
    if (addBtn) {
      addBtn.disabled = (pane.__storyboard && pane.__storyboard.shots || []).length >= 9;
      addBtn.addEventListener("click", function () {
        const board = collectStoryboardFromPane(pane);
        if (board.shots.length >= 9) {
          showToast("每集最多 9 个镜头", "error");
          return;
        }
        board.shots.push({
          shot_no: board.shots.length + 1,
          beat: "补充镜头",
          shot_size: "中景",
          camera_movement: "固定",
          duration_seconds: 3,
          visual: "",
          narration: "",
          dialogue: "",
          ai_draw_prompt: "",
          is_highlight: false,
        });
        pane.__storyboard = board;
        pane.innerHTML = renderStationStoryboard(board, []);
        bindStationStoryboardActions();
        updateStoryboardDuration(pane);
      });
    }
    pane.querySelectorAll("[data-shot-delete]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const board = collectStoryboardFromPane(pane);
        if (board.shots.length <= 6) {
          showToast("每集至少保留 6 个镜头", "error");
          return;
        }
        const idx = Number(btn.getAttribute("data-shot-delete"));
        if (!Number.isInteger(idx) || idx < 0 || idx >= board.shots.length) return;
        board.shots.splice(idx, 1);
        board.shots.forEach(function (shot, shotIdx) { shot.shot_no = shotIdx + 1; });
        pane.__storyboard = board;
        pane.innerHTML = renderStationStoryboard(board, []);
        bindStationStoryboardActions();
        updateStoryboardDuration(pane);
      });
    });
    pane.querySelectorAll("[data-shot-rewrite]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          const shotNo = Number(btn.getAttribute("data-shot-rewrite"));
          const data = await postJson(wsUrl("/drama/storyboard/rewrite-shot"), dramaPayload({
            shot_no: shotNo,
            storyboard: collectStoryboardFromPane(pane),
          }));
          pane.__storyboard = data.storyboard;
          pane.innerHTML = renderStationStoryboard(data.storyboard, data.soft_warnings || []);
          bindStationStoryboardActions();
          updateStoryboardDuration(pane);
          showToast("本镜已重生", "info");
          await loadStationCharacters();
        } catch (err) {
          showToast("重生失败：" + errTitle(err), "error");
          btn.disabled = false;
        }
      });
    });
    const clearBtn = pane.querySelector("[data-storyboard-clear-highlight]");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        pane.querySelectorAll('[data-field="is_highlight"]').forEach(function (el) { el.checked = false; });
        updateStoryboardDuration(pane);
      });
    }
  }

  function updateStoryboardDuration(pane) {
    const el = pane.querySelector("[data-storyboard-duration]");
    if (!el) return;
    const board = collectStoryboardFromPane(pane);
    const total = (board.shots || []).reduce(function (sum, shot) {
      const n = Number(shot.duration_seconds || 0);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
    const target = Number(board.target_duration_seconds || 60);
    const delta = total - target;
    const cls = Math.abs(delta) <= 3 ? "ready" : (Math.abs(delta) <= 10 ? "warn" : "blocked");
    el.className = "storyboard-duration " + cls;
    el.textContent = "总时长 " + total + " 秒 / 目标 " + target + " 秒（" + (delta >= 0 ? "+" : "") + delta + "）";
  }

  async function loadStationCharacters() {
    const pane = document.querySelector('[data-station-pane="characters"]');
    if (!pane) return;
    pane.innerHTML = skeleton(3);
    try {
      const progress = await fetchJson(dramaApiUrl("/drama/progress"));
      const station = (progress.stations || []).find((s) => s.id === "characters");
      if (station && station.status === "locked") {
        pane.innerHTML = '<div class="alert info">请先完成站 ③ 分镜。</div>';
        return;
      }
      const data = await fetchJson(dramaApiUrl("/drama/characters"));
      if (!data.exists || !data.sheet) {
        pane.__characterSheet = null;
        pane.__characterSkipped = false;
        pane.innerHTML = renderCharactersEmpty("站 ④ 角色", "站 ④ 会把主角、反派和 AI 绘画 prompt 整理成角色表。");
      } else {
        pane.__characterSheet = data.sheet;
        pane.__characterSkipped = !!data.skipped;
        pane.innerHTML = renderCharacterSheet(data.sheet, "站 ④ 角色", !!data.skipped);
      }
      bindCharacterSheetActions(pane);
    } catch (err) {
      pane.innerHTML = renderErrorCard(err);
    }
  }

  async function initDramaCharacters() {
    const root = document.getElementById("characters-page-root");
    if (!root) return;
    root.innerHTML = skeleton(4);
    try {
      const active = await fetchJson(wsUrl("/jobs/active"));
      const job = (active.jobs || []).find(function (row) {
        return row.step === "drama-characters";
      });
      if (job && job.job_id) {
        const detail = await fetchJson(wsUrl("/job/" + job.job_id));
        const episodeNo = Number((detail.params || {}).episode_no || 1);
        root.__dramaEpisodeNo = episodeNo;
        await pollJob(job.job_id, root, null, async function () {
          await loadDramaCharactersPage(root, episodeNo);
        });
        return;
      }
    } catch (err) {
      // A stale/lost active-job record must not hide the persisted character sheet.
    }
    await loadDramaCharactersPage(root);
  }

  async function loadDramaCharactersPage(root, episodeNo) {
    const targetEpisode = Number(episodeNo || root.__dramaEpisodeNo || dramaEpisodeNo());
    root.__dramaEpisodeNo = targetEpisode;
    try {
      const data = await fetchJson(dramaApiUrlFor("/drama/characters", targetEpisode));
      if (!data.exists || !data.sheet) {
        root.__characterSheet = null;
        root.__characterSkipped = false;
        root.innerHTML = renderCharactersEmpty("角色库", "完成站③后，可以生成本季角色设定表。");
      } else {
        root.__characterSheet = data.sheet;
        root.__characterSkipped = !!data.skipped;
        root.innerHTML = renderCharacterSheet(data.sheet, "角色库", !!data.skipped);
      }
      bindCharacterSheetActions(root);
    } catch (err) {
      root.innerHTML = renderErrorCard(err);
    }
  }

  function renderCharactersEmpty(title, hint) {
    return '<div class="card"><div class="card-header"><h3 class="ornament">' + escapeHtml(title) + '</h3>' +
      '<span class="badge warn">待处理</span></div><div class="card-body">' +
      '<div class="empty-state"><span class="ornament">✦</span>' +
      '<h3>等待生成角色表</h3>' +
      '<p class="muted">' + escapeHtml(hint) + '</p>' +
      '<button type="button" class="btn btn-primary" data-generate-characters>▸ 生成角色表</button>' +
      '</div></div></div>';
  }

  function renderCharacterSheet(sheet, title, skipped) {
    const chars = sheet.characters || [];
    const cards = chars.map(renderCharacterCard).join("");
    return '<div class="card"><div class="card-header"><h3 class="ornament">' + escapeHtml(title) + '</h3>' +
      '<span class="badge ' + (skipped ? "warn" : "ready") + '">' + (skipped ? "沿用季角色" : "已完成") + '</span></div><div class="card-body stack">' +
      (skipped ? '<div class="alert info">本集未引入新角色，沿用本季角色设定；可直接评审并组装。</div>' : '') +
      '<form data-character-sheet-form class="stack">' +
      '<div class="kv-list compact">' +
      '<div class="k">季数</div><div class="v">第 ' + escapeHtml(String(sheet.season_no || 1)) + ' 季</div>' +
      '<div class="k">来源分镜</div><div class="v">' + escapeHtml(sheet.source_storyboard_title || "") + '</div>' +
      '</div>' +
      '<div class="character-grid">' + cards + '</div>' +
      '<div class="form-actions">' +
      (skipped ? '' : '<button type="button" class="btn btn-secondary" data-regenerate-characters>重新生成</button>') +
      '<button type="submit" class="btn btn-primary">保存角色表</button>' +
      '<button type="button" class="btn btn-primary" data-review-assemble>评审并组装</button>' +
      '</div></form></div></div>';
  }

  function renderCharacterCard(character, idx) {
    const vf = character.visual_features || {};
    const img = firstCharacterImage(character);
    const imageHtml = img
      ? '<img class="character-ref-img" src="' + escapeHtml(characterRefUrl(character.id, img.path)) + '" alt="' + escapeHtml(character.name || character.id) + '">'
      : '<div class="character-ref-placeholder">未生成参考图</div>';
    const canRedrawLocal = !img || isLocalPreviewImage(img);
    return '<section class="character-card" data-character-card="' + idx + '">' +
      '<div class="character-ref-box">' + imageHtml +
      (canRedrawLocal ? '<button type="button" class="btn btn-secondary btn-sm" data-redraw-character="' + escapeHtml(character.id || "") + '">重画本地预览</button>' : '<span class="badge ready">真实参考图</span>') + '</div>' +
      '<div class="stack">' +
      '<div class="cluster" style="justify-content:space-between">' +
      '<strong><code>' + escapeHtml(character.id || "") + '</code> · ' + escapeHtml(character.name || "") + '</strong>' +
      '<label class="check-row"><input type="checkbox" data-char-field="manual_override" ' + (character.manual_override ? "checked" : "") + '> 锁定</label>' +
      '</div>' +
      '<div class="form-grid-2">' +
      charInput("name", "姓名", character.name || "") +
      charInput("role", "角色", character.role || "") +
      charInput("age_range", "年龄段", character.age_range || "") +
      charInput("gender", "性别", character.gender || "") +
      charInput("lora_token", "LoRA token", character.lora_token || "") +
      charInput("wardrobe_default", "默认服装", character.wardrobe_default || "") +
      '</div>' +
      charTextarea("visual_signature", "视觉签名", character.visual_signature || "", 2) +
      '<div class="form-grid-2">' +
      charTextarea("vf_face", "face", vf.face || "", 2) +
      charTextarea("vf_hair", "hair", vf.hair || "", 2) +
      charTextarea("vf_body", "body", vf.body || "", 2) +
      charTextarea("expression_keywords", "表情关键词", (character.expression_keywords || []).join("，"), 2) +
      '</div>' +
      charTextarea("prompt_template_sd", "SD Prompt", character.prompt_template_sd || "", 4) +
      renderSuggestionCount(character) +
      '</div></section>';
  }

  function charInput(field, label, value) {
    return '<div class="field"><label>' + escapeHtml(label) + '</label><input data-char-field="' + field + '" value="' + escapeHtml(value) + '"></div>';
  }

  function charTextarea(field, label, value, rows) {
    return '<div class="field"><label>' + escapeHtml(label) + '</label><textarea rows="' + rows + '" data-char-field="' + field + '">' + escapeHtml(value) + '</textarea></div>';
  }

  function renderSuggestionCount(character) {
    const count = (character.agent_suggestions || []).length;
    return count ? '<div class="alert info">已有 ' + count + ' 条 agent 建议待人工查看。</div>' : "";
  }

  function firstCharacterImage(character) {
    const refs = character.reference_images || [];
    return refs.find(function (ref) {
      return /[.]png$/i.test(String(ref && ref.path || ""));
    }) || null;
  }

  function isLocalPreviewImage(image) {
    return ["placeholder_png", "mock-multimodal-smoke"].includes(String(image && image.generated_by || ""));
  }

  function characterRefUrl(cid, relPath) {
    const parts = String(relPath || "").split("/");
    const filename = parts[parts.length - 1] || "";
    return wsUrl("/character-ref/" + encodeURIComponent(cid || "") + "/" + encodeURIComponent(filename));
  }

  function collectCharacterSheet(root) {
    const base = root.__characterSheet || { schema_version: 1, season_no: 1, episode_no: 1, characters: [] };
    const oldChars = base.characters || [];
    const cards = Array.from(root.querySelectorAll("[data-character-card]"));
    const characters = cards.map(function (card, idx) {
      const old = oldChars[idx] || {};
      const get = function (field) {
        const el = card.querySelector('[data-char-field="' + field + '"]');
        return el ? el.value : "";
      };
      const checked = function (field) {
        const el = card.querySelector('[data-char-field="' + field + '"]');
        return !!(el && el.checked);
      };
      return Object.assign({}, old, {
        name: get("name"),
        role: get("role"),
        age_range: get("age_range"),
        gender: get("gender"),
        lora_token: get("lora_token"),
        wardrobe_default: get("wardrobe_default"),
        visual_signature: get("visual_signature"),
        prompt_template_sd: get("prompt_template_sd"),
        manual_override: checked("manual_override"),
        expression_keywords: splitKeywords(get("expression_keywords")),
        visual_features: Object.assign({}, old.visual_features || {}, {
          face: get("vf_face"),
          hair: get("vf_hair"),
          body: get("vf_body"),
        }),
      });
    });
    return Object.assign({}, base, { characters: characters });
  }

  function splitKeywords(text) {
    return String(text || "").replaceAll("，", ",").split(",").map(function (item) { return item.trim(); }).filter(Boolean);
  }

  function bindCharacterSheetActions(root) {
    const targetEpisode = Number(root.__dramaEpisodeNo || dramaEpisodeNo());
    const characterPayload = function (payload) {
      return Object.assign({}, payload || {}, { episode_no: targetEpisode });
    };
    const gen = root.querySelector("[data-generate-characters], [data-regenerate-characters]");
    if (gen) {
      gen.addEventListener("click", async function () {
        gen.disabled = true;
        try {
          const data = await postJson(
            wsUrl("/drama/characters"),
            await dramaGenerationPayload("drama-characters", { confirm_new_text_revision: true }, targetEpisode)
          );
          const terminal = await pollJob(data.job_id, root, gen, async function (job) {
            if (job.status !== "succeeded") return;
            if (root.id === "characters-page-root") await loadDramaCharactersPage(root, targetEpisode);
            else await loadStationCharacters();
            await loadDramaProgress();
          });
          if (terminal && terminal.status === "succeeded") {
            const skipped = !!((terminal.result_summary || {}).skipped);
            showToast(skipped ? "本集沿用季角色" : "角色表已生成", "info");
          }
        } catch (err) {
          showToast("生成失败：" + errTitle(err), "error");
          gen.disabled = false;
        }
      });
    }
    const form = root.querySelector("[data-character-sheet-form]");
    if (form) {
      form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        try {
          const data = await putJson(wsUrl("/drama/characters"), characterPayload({ sheet: collectCharacterSheet(root) }));
          root.__characterSheet = data.sheet;
          root.innerHTML = renderCharacterSheet(data.sheet, root.id === "characters-page-root" ? "角色库" : "站 ④ 角色", !!root.__characterSkipped);
          bindCharacterSheetActions(root);
          await loadDramaProgress();
          showToast("角色表已保存", "info");
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
        }
      });
    }
    root.querySelectorAll("[data-redraw-character]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          const cid = btn.getAttribute("data-redraw-character") || "";
          const saved = await putJson(wsUrl("/drama/characters"), characterPayload({ sheet: collectCharacterSheet(root) }));
          root.__characterSheet = saved.sheet;
          const data = await postJson(
            wsUrl("/drama/characters/" + encodeURIComponent(cid) + "/redraw"),
            characterPayload({})
          );
          root.__characterSheet = data.sheet;
          root.innerHTML = renderCharacterSheet(data.sheet, root.id === "characters-page-root" ? "角色库" : "站 ④ 角色", !!root.__characterSkipped);
          bindCharacterSheetActions(root);
          showToast("参考图已更新", "info");
        } catch (err) {
          showToast("重画失败：" + errTitle(err), "error");
          btn.disabled = false;
        }
      });
    });
    const reviewBtn = root.querySelector("[data-review-assemble]");
    if (reviewBtn) {
      reviewBtn.addEventListener("click", async function () {
        reviewBtn.disabled = true;
        try {
          const saved = await putJson(wsUrl("/drama/characters"), characterPayload({ sheet: collectCharacterSheet(root) }));
          root.__characterSheet = saved.sheet;
          const data = await postJson(
            wsUrl("/drama/review"),
            await dramaGenerationPayload("drama-review-assemble", { confirm_new_text_revision: true }, targetEpisode)
          );
          await pollJob(data.job_id, root, reviewBtn, async function (job) {
            if (job.status !== "succeeded") return;
            window.location.href = "/w/" + encodeURIComponent(WORKSPACE_NAME) + "/episode/" + encodeURIComponent(String(targetEpisode));
          });
        } catch (err) {
          showToast("组装失败：" + errTitle(err), "error");
          reviewBtn.disabled = false;
        }
      });
    }
  }

  // ===== page: drama episodes =============================================
  function dramaNextEpisodeReason(data) {
    const code = String(data.next_episode_blocked_reason || "");
    const labels = {
      episode_sequence_gap: "检测到剧集断档，请先修复本地产物。",
      orphan_episode_artifact: "检测到孤儿剧集产物，请先清理或恢复对应剧集。",
      previous_episode_incomplete: "上一集尚未完整组装。",
      previous_episode_artifact_mismatch: "上一集产物的集数不一致。",
      previous_episode_fingerprint_missing: "上一集缺少输入指纹，需要重新组装。",
      previous_episode_sha_mismatch: "上一集内容与 meta 校验值不一致，需要重新组装。",
      previous_episode_stale: "上一集输入已变化，请先重新评审并组装。",
      next_episode_setup_invalid: "下一集 setup 无法恢复，请修复后再继续。",
      planned_episode_count_reached: "已达到计划集数。"
    };
    return labels[code] || String(data.next_episode_blocked_message || "下一集暂不可开始。");
  }

  async function initDramaEpisodes() {
    const box = document.getElementById("episodes-panel");
    if (!box) return;
    box.innerHTML = skeleton(4);
    try {
      const data = await fetchJson(wsUrl("/drama/episodes"));
      const episodes = data.episodes || [];
      const rows = episodes.map(function (ep) {
        return '<tr>' +
          '<td>第 ' + escapeHtml(String(ep.episode_no || "")) + ' 集</td>' +
          '<td>' + escapeHtml(ep.title || "") + '</td>' +
          '<td>' + verdictBadge(ep.verdict || "") + '</td>' +
          '<td>' + escapeHtml(String(ep.estimated_duration_seconds || 0)) + ' 秒</td>' +
          '<td>' + (ep.stale ? '<span class="badge warn">需重新组装</span>' : '<span class="badge ready">已就绪</span>') + '</td>' +
          '<td><div class="cluster">' +
          '<a class="btn btn-secondary btn-sm" href="/w/' + encodeURIComponent(WORKSPACE_NAME) + '/episode/' + encodeURIComponent(String(ep.episode_no || 1)) + '">查看</a>' +
          '<a class="btn btn-ghost btn-sm" href="/w/' + encodeURIComponent(WORKSPACE_NAME) + '/write?episode=' + encodeURIComponent(String(ep.episode_no || 1)) + '">编辑</a>' +
          '</div></td>' +
          '</tr>';
      }).join("");
      const episodeList = episodes.length
        ? tableScroll('<table class="table drama-episode-table"><thead><tr><th>集数</th><th>标题</th><th>评审</th><th>时长</th><th>状态</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>')
        : emptyState("尚无已组装剧集", "从第 1 集创作台开始；完成评审并组装后，可导出的剧集数据会出现在这里。", "");
      const nextNo = Number(data.next_episode_no || 0);
      let nextAction = "";
      if (Number.isSafeInteger(nextNo) && nextNo === 1 && !data.next_episode_blocked_reason) {
        const label = data.next_episode_initialized ? "继续第 1 集" : "开始第 1 集";
        nextAction = '<div class="form-actions"><a class="btn btn-primary" href="/w/' + encodeURIComponent(WORKSPACE_NAME) + '/write?episode=1">' + label + ' →</a></div>';
      } else if (data.can_start_next && Number.isSafeInteger(nextNo)) {
        const label = data.next_episode_initialized ? "继续第 " : "开始第 ";
        nextAction = '<div class="form-actions"><button type="button" class="btn btn-primary" data-start-next-episode="' + escapeHtml(String(nextNo)) + '">' + label + escapeHtml(String(nextNo)) + ' 集 →</button></div>';
      } else {
        const repairNo = Number(data.next_episode_repair_no || 0);
        const repairLink = Number.isSafeInteger(repairNo) && repairNo > 0
          ? ' <a class="btn btn-secondary btn-sm" href="/w/' + encodeURIComponent(WORKSPACE_NAME) + '/write?episode=' + encodeURIComponent(String(repairNo)) + '">修复第 ' + escapeHtml(String(repairNo)) + ' 集</a>'
          : '';
        nextAction = '<div class="alert info"><span>' + escapeHtml(dramaNextEpisodeReason(data)) + '</span>' + repairLink + '</div>';
      }

      const season = data.season_export || {};
      const eligible = Array.isArray(season.eligible_episode_nos) ? season.eligible_episode_nos.length : 0;
      const planned = Number(data.planned_episode_count || season.planned_episode_count || 0);
      const seasonBase = wsUrl("/drama/season/1/export?mode=");
      const masterButton = season.master_ready
        ? '<a class="btn btn-primary" href="' + seasonBase + 'master" download>导出整季母包</a>'
        : '<button type="button" class="btn btn-primary" disabled title="整季母包要求计划内全部剧集均已就绪且完整">导出整季母包</button>';
      const snapshotButton = season.snapshot_ready
        ? '<a class="btn btn-secondary" href="' + seasonBase + 'snapshot" download>导出阶段快照</a>'
        : '<button type="button" class="btn btn-secondary" disabled title="至少需要一集已就绪的完整剧集">导出阶段快照</button>';
      const excluded = Array.isArray(season.excluded) ? season.excluded : [];
      const missingRefs = Array.isArray(season.missing_reference_images) ? season.missing_reference_images.length : 0;
      const assetErrors = Array.isArray(season.asset_errors) ? season.asset_errors.length : 0;
      let seasonHint = "计划内剧集与角色引用均已就绪。";
      if (!season.master_ready) {
        const reasons = [];
        if (excluded.length) reasons.push(String(excluded.length) + " 集未完成或已过期");
        if (missingRefs) reasons.push(String(missingRefs) + " 个引用图缺失");
        if (assetErrors) reasons.push(String(assetErrors) + " 个引用资产不安全或无效");
        seasonHint = "母包未就绪：" + (reasons.length ? reasons.join("，") : "等待完整剧集或角色引用") + "。";
        seasonHint += season.snapshot_ready ? " 可先导出阶段快照。" : " 当前也没有可导出的阶段快照。";
      }
      const exportCard = '<div class="card" style="margin-top:16px"><div class="card-header"><h3 class="ornament">整季交付</h3><span class="badge">可交付 ' + escapeHtml(String(eligible)) + '/' + escapeHtml(String(planned)) + ' 集</span></div><div class="card-body stack"><p class="muted">' + escapeHtml(seasonHint) + '</p><div class="cluster">' + masterButton + snapshotButton + '</div></div></div>';
      box.innerHTML = episodeList + nextAction + exportCard;
      const nextBtn = box.querySelector("[data-start-next-episode]");
      if (nextBtn) {
        nextBtn.addEventListener("click", async function () {
          nextBtn.disabled = true;
          try {
            const result = await postJson(wsUrl("/drama/next-episode"), { after_episode_no: Number(nextBtn.getAttribute("data-start-next-episode")) - 1 });
            const episodeNo = Number(result.episode_no || nextNo);
            window.location.href = "/w/" + encodeURIComponent(WORKSPACE_NAME) + "/write?episode=" + encodeURIComponent(String(episodeNo));
          } catch (err) {
            showToast("下一集初始化失败：" + errTitle(err), "error");
            nextBtn.disabled = false;
          }
        });
      }
    } catch (err) {
      box.innerHTML = renderErrorCard(err);
    }
  }

  async function initDramaEpisodeDetail() {
    bindHashTabs();
    try {
      const data = await fetchJson(wsUrl("/drama/episode/" + encodeURIComponent(String(CHAPTER_NO || 1))));
      renderDramaEpisodeDetail(data);
    } catch (err) {
      ["script", "storyboard-view", "characters-view", "review", "export", "video"].forEach(function (id) {
        const box = document.getElementById("tab-" + id);
        if (box) box.innerHTML = renderErrorCard(err);
      });
    }
  }

  function renderDramaEpisodeDetail(data) {
    const assembled = !!data.episode;
    const episode = data.episode || {};
    const meta = data.meta || {};
    const review = data.review || {};
    const characters = (data.characters && data.characters.characters) || [];
    const stale = !!data.stale;
    const staleHtml = stale ? '<div class="alert warn">分站内容已变更，请重新评审并组装。</div>' : "";
    const scriptBox = document.getElementById("tab-script");
    if (scriptBox) {
      scriptBox.innerHTML = !assembled
        ? '<div class="alert warn">本集评审尚未通过，因此没有可发布的组装产物；请在“评审”页查看并应用建议。</div>'
        : staleHtml +
        '<div class="card"><div class="card-header"><h3 class="ornament">' + escapeHtml(episode.title || "未命名") + '</h3>' +
        verdictBadge((stale && review.verdict) || meta.verdict || "") + '</div><div class="card-body stack">' +
        '<div class="kv-list compact">' +
        '<div class="k">一句话故事</div><div class="v">' + escapeHtml(episode.logline || "") + '</div>' +
        '<div class="k">赛道</div><div class="v"><code>' + escapeHtml(episode.track || "") + '</code></div>' +
        '<div class="k">预估 / 目标时长</div><div class="v">' + escapeHtml(String(episode.estimated_duration_seconds || 0)) + ' / ' + escapeHtml(String(episode.target_duration_seconds || 0)) + ' 秒</div>' +
        '</div>' +
        '<div class="reading-body"><p>' + escapeHtml(episode.narrative || "") + '</p></div>' +
        '</div></div>';
    }
    const storyBox = document.getElementById("tab-storyboard-view");
    if (storyBox) {
      const rows = (episode.storyboard || []).map(function (shot) {
        return '<tr><td>' + escapeHtml(String(shot.shot_no || "")) + '</td>' +
          '<td>' + escapeHtml(shot.shot_size || "") + '</td>' +
          '<td>' + escapeHtml(shot.camera_move || "") + '</td>' +
          '<td>' + escapeHtml(String(shot.duration_seconds || 0)) + '</td>' +
          '<td>' + escapeHtml(shot.visual_content || "") + '</td>' +
          '<td>' + escapeHtml(shot.dialogue || "") + '</td>' +
          '<td>' + (shot.is_highlight ? '<span class="badge ready">高光</span>' : '') + '</td></tr>';
      }).join("");
      storyBox.innerHTML = tableScroll('<table class="table table-wide"><thead><tr><th>#</th><th>景别</th><th>运镜</th><th>秒</th><th>画面</th><th>台词</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>');
    }
    const charBox = document.getElementById("tab-characters-view");
    if (charBox) {
      charBox.innerHTML = characters.length
        ? '<div class="character-grid">' + characters.map(function (c) {
            const img = firstCharacterImage(c);
            const imageHtml = img
              ? '<div class="character-ref-box"><img class="character-ref-img" src="' + escapeHtml(characterRefUrl(c.id, img.path)) + '" alt="' + escapeHtml(c.name || c.id) + '"></div>'
              : '<div class="character-ref-placeholder">暂无参考图</div>';
            return '<section class="character-card">' + imageHtml + '<div class="stack">' +
              '<strong><code>' + escapeHtml(c.id || "") + '</code> · ' + escapeHtml(c.name || "") + '</strong>' +
              '<p class="muted">' + escapeHtml(c.role || "") + '</p>' +
              '<p>' + escapeHtml(c.visual_signature || "") + '</p>' +
              '<details class="details-fold"><summary>查看 SD Prompt</summary><pre>' + escapeHtml(c.prompt_template_sd || "") + '</pre></details>' +
              '</div></section>';
          }).join("") + '</div>'
        : '<p class="muted">暂无角色表。</p>';
    }
    const reviewBox = document.getElementById("tab-review");
    if (reviewBox) {
      const agents = review && review.verdict ? [review] : (meta.agent_reviews || []);
      const suggestions = review.suggestions || [];
      const suggestionHtml = suggestions.length
        ? '<div class="stack">' + suggestions.map(renderDramaSuggestion).join("") + '</div>'
        : '<p class="muted">暂无优化建议。</p>';
      reviewBox.innerHTML = '<div class="stack">' +
        (agents.length ? agents.map(renderDramaReviewCard).join("") : '<p class="muted">暂无评审记录。</p>') +
        suggestionHtml +
        '</div>';
      bindDramaSuggestionActions(reviewBox);
    }
    const exportBox = document.getElementById("tab-export");
    if (exportBox) {
      const episodeNo = Number(CHAPTER_NO || 1);
      const formats = [
        ["json", "JSON 真源"],
        ["md", "Markdown 分镜表"],
        ["csv", "CSV（Excel 中文）"],
        ["comfy", "Comfy workflow 模板"],
      ];
      const buttons = formats.map(function (item) {
        const href = wsUrl("/drama/episode/" + encodeURIComponent(String(episodeNo)) + "/export?format=" + encodeURIComponent(item[0]));
        return stale
          ? '<button type="button" class="btn btn-secondary" disabled>' + escapeHtml(item[1]) + '</button>'
          : '<a class="btn btn-secondary" download href="' + href + '">' + escapeHtml(item[1]) + '</a>';
      }).join("");
      exportBox.innerHTML = !assembled
        ? '<div class="alert warn">评审通过并组装后才能导出。</div>'
        : staleHtml + '<div class="card"><div class="card-header"><h3 class="ornament">导出</h3></div><div class="card-body stack"><p class="muted">所有格式均来自已组装的 episode JSON 真源。Comfy 为模板级 workflow，导入后仍需接入本地 checkpoint、LoRA 与节点。</p>' + (stale ? '<a class="btn btn-primary" href="/w/' + encodeURIComponent(WORKSPACE_NAME) + '/write?episode=' + encodeURIComponent(String(episodeNo)) + '#characters">返回创作台重新评审并组装</a>' : '') + '<div class="cluster">' + buttons + '</div></div></div>';
    }
    loadDramaVideoPanel();
  }

  function dramaVideoStateLabel(state) {
    const labels = {
      not_ready: "待准备", ready: "可生成", pending: "待准备",
      "upload-assets": "上传素材", queued: "排队", generating: "生成中",
      download: "下载成片", succeeded: "成功", failed: "失败",
      submitted: "已提交·可续查", submission_unknown: "提交结果待对账",
      aborted: "取消", cancelled: "取消", timeout: "超时", lost: "失败",
      budget_exceeded: "成功（超预算）",
    };
    return labels[String(state || "")] || String(state || "待准备");
  }

  async function loadDramaVideoPanel() {
    const box = document.getElementById("tab-video");
    if (!box) return;
    box.innerHTML = skeleton(2);
    try {
      const data = await fetchJson(wsUrl("/drama/video"));
      renderDramaVideoPanel(box, data);
    } catch (err) {
      box.innerHTML = renderErrorCard(err);
    }
  }

  function renderDramaVideoPanel(box, data) {
    const state = String(data.state || "not_ready");
    const video = data.video || {};
    const job = data.job || null;
    let body = '<div class="alert info">状态：' + escapeHtml(dramaVideoStateLabel(state)) + '</div>';
    if ((state === "succeeded" || state === "budget_exceeded") && data.download_ready) {
      const src = wsUrl("/drama/video/file");
      if (state === "budget_exceeded") {
        body += '<div class="alert warn">实际上报费用超出本次授权上限；已保留已付费生成的成片，不会自动重试。</div>';
      }
      body += '<video controls preload="metadata" style="display:block;width:100%;max-width:420px;aspect-ratio:9/16;background:#111" src="' + src + '"></video>' +
        '<div class="kv-list compact"><div class="k">规格</div><div class="v">' + escapeHtml(String(video.duration_seconds || 5)) + ' 秒 · ' + escapeHtml(video.ratio || "9:16") + ' · ' + escapeHtml(video.resolution || "720p") + '</div>' +
        '<div class="k">文件</div><div class="v">' + escapeHtml(String(video.file_size_bytes || 0)) + ' bytes</div></div>' +
        '<a class="btn btn-primary" download="episode_01.video.mp4" href="' + src + '">下载成片</a>';
      if (data.latest_attempt_state && ["failed", "cancelled", "timeout", "lost"].includes(data.latest_attempt_state)) {
        body += renderErrorCard({ message: "最近一次重新生成未完成：" + dramaVideoStateLabel(data.latest_attempt_state) +
          (job && job.error ? "（" + job.error + "）" : "") });
      }
    } else if (job && (job.status === "pending" || job.status === "running")) {
      body += '<p class="muted">刷新页面会自动恢复；取消仅会停止本地轮询，不保证撤销上游已提交的计费任务。</p>' +
        '<button type="button" class="btn btn-danger" data-video-cancel="' + escapeHtml(job.job_id || "") + '">取消视频任务</button>';
    } else if (job && ["failed", "aborted", "lost", "budget_exceeded"].includes(job.status) &&
        state !== "submitted" && state !== "submission_unknown") {
      body += renderErrorCard({ message: "视频任务未完成：" + (job.error || dramaVideoStateLabel(job.status)) });
    } else if (state === "not_ready") {
      body += '<p class="muted">请确保第 1 集已重新评审并组装，且本集角色都有当前参考图。</p>';
    } else {
      if (state === "submitted") {
        body += '<div class="alert info">上游任务已持久化提交；使用原授权参数再次点击只会续查，不会重复上传或新建任务。</div>';
      } else if (state === "submission_unknown") {
        body += '<div class="alert warn">提交结果未知，请先查上游任务与账单；系统不会自动重试。</div>';
      }
      body += '<p class="muted">MVP 固定生成 1 个 5 秒、9:16、720p、无音频无水印的视频任务。</p>' +
        (data.real_mode && state !== "submitted"
          ? '<div class="alert warn">真实视频是独立计费授权，不继承真文本或真生图确认。预估费用：¥' + escapeHtml(String(data.estimated_cost_cny == null ? "未配置" : data.estimated_cost_cny)) + '</div>' +
            '<div class="form-grid-2"><div class="field"><label for="video-budget">预算上限（元）</label><input id="video-budget" type="number" min="0.01" step="0.01"></div>' +
            '<div class="field"><label for="video-timeout">超时（分钟）</label><input id="video-timeout" type="number" min="1" max="60" step="1" value="5"></div></div>' +
            '<label class="check-row"><input id="video-confirm" type="checkbox"> 我确认提交 1 个真实视频计费任务，且超时后不自动重试</label>'
          : '') +
        (state === "submission_unknown" ? '' : '<button type="button" class="btn btn-primary" data-video-generate>' +
          (state === "submitted" ? '继续查询' : '生成视频') + '</button>');
    }
    box.innerHTML = '<div class="card"><div class="card-header"><h3 class="ornament">第 1 集视频</h3><span class="badge">' + escapeHtml(dramaVideoStateLabel(state)) + '</span></div><div class="card-body stack">' + body + '</div></div>';
    const generate = box.querySelector("[data-video-generate]");
    if (generate) generate.addEventListener("click", async function () {
      generate.disabled = true;
      try {
        const payload = { episode_no: 1 };
        if (state === "submitted") {
          payload.resume_submitted = true;
        } else if (data.real_mode) {
          payload.confirm_real_video = !!(document.getElementById("video-confirm") && document.getElementById("video-confirm").checked);
          payload.budget_cny = Number(document.getElementById("video-budget") && document.getElementById("video-budget").value);
          payload.timeout_minutes = Number(document.getElementById("video-timeout") && document.getElementById("video-timeout").value);
        }
        const result = await postJson(wsUrl("/drama/video"), payload);
        await pollJob(result.job_id, box, generate, loadDramaVideoPanel);
      } catch (err) {
        box.innerHTML = renderErrorCard(err);
      }
    });
    const cancel = box.querySelector("[data-video-cancel]");
    if (cancel) cancel.addEventListener("click", async function () {
      cancel.disabled = true;
      try {
        await postJson(wsUrl("/job/" + encodeURIComponent(cancel.getAttribute("data-video-cancel")) + "/cancel"), {});
        await loadDramaVideoPanel();
      } catch (err) {
        box.innerHTML = renderErrorCard(err);
      }
    });
    if (job && (job.status === "pending" || job.status === "running") && job.job_id) {
      setTimeout(function () { pollJob(job.job_id, box, null, loadDramaVideoPanel); }, 0);
    }
  }

  async function initDramaInsights() {
    const costBox = document.getElementById("drama-insights-cost");
    const durationBox = document.getElementById("drama-insights-duration");
    const hooksBox = document.getElementById("drama-insights-hooks");
    if (!costBox || !durationBox || !hooksBox) return;
    costBox.innerHTML = skeleton(3);
    durationBox.innerHTML = skeleton(2);
    hooksBox.innerHTML = skeleton(3);
    try {
      const data = await fetchJson(wsUrl("/insights"));
      const llm = data.llm_cost || {};
      const meta = data.episode_meta_cost || {};
      costBox.innerHTML = '<div class="kv-list compact">' +
        '<div class="k">LLM 日志</div><div class="v">¥' + escapeHtml(Number(llm.cost_cny || 0).toFixed(4)) + ' · ' + escapeHtml(String(llm.calls || 0)) + ' 次</div>' +
        '<div class="k">Episode meta</div><div class="v">¥' + escapeHtml(Number(meta.cost_cny || 0).toFixed(4)) + ' · ' + escapeHtml(String(meta.episodes || 0)) + ' 集</div>' +
        '<div class="k">说明</div><div class="v">' + escapeHtml(data.cost_note || "mock 成本为 0，真模型启用后生效。") + '</div>' +
        '</div>';
      const duration = data.duration || {};
      const rate = Number(duration.rate || 0);
      const pct = Math.max(0, Math.min(100, Math.round(rate * 100)));
      durationBox.innerHTML = '<div class="stack"><div class="progress"><div class="progress-fill" style="width:' + pct + '%"></div></div><p><strong>' + pct + '%</strong> · ' + escapeHtml(String(duration.within_tolerance || 0)) + ' / ' + escapeHtml(String(duration.total || 0)) + ' 集在目标 ±' + escapeHtml(String(duration.tolerance_seconds || 3)) + ' 秒内</p></div>';
      const hookRows = data.hook_types || [];
      hooksBox.innerHTML = hookRows.length
        ? tableScroll('<table class="table"><thead><tr><th>类型</th><th>集数</th></tr></thead><tbody>' + hookRows.map(function (row) { return '<tr><td>' + escapeHtml(row.type || "(unknown)") + '</td><td>' + escapeHtml(String(row.count || 0)) + '</td></tr>'; }).join("") + '</tbody></table>')
        : '<p class="muted">尚无已组装剧集。</p>';
    } catch (err) {
      costBox.innerHTML = renderErrorCard(err);
      durationBox.innerHTML = "";
      hooksBox.innerHTML = "";
    }
  }

  function renderDramaReviewCard(review) {
    const sub = review.sub_scores || {};
    const keys = ["hook", "pace", "ai_friendly", "character_consistency", "cliffhanger"];
    const labels = { hook: "开场钩子", pace: "节奏", ai_friendly: "AI 制作友好度", character_consistency: "角色一致性", cliffhanger: "结尾钩子" };
    const bars = keys.map(function (k) {
      const v = sub[k];
      const pct = (v == null ? 0 : Math.max(0, Math.min(10, Number(v))) * 10);
      return '<div class="subscore-bar"><span class="label">' + escapeHtml(labels[k] || k) + '</span><div class="track"><i style="width:' + pct + '%"></i></div><span class="val">' + (v == null ? "—" : escapeHtml(String(v))) + '</span></div>';
    }).join("");
    const issues = (review.issues || []).map(function (it) { return '<li>' + escapeHtml(String(it)) + '</li>'; }).join("");
    return '<div class="review-card"><div><div class="name">短剧评审</div><div class="verdict">' + verdictBadge(review.verdict || "") + '<span class="muted" style="margin-left:6px">总分 ' + escapeHtml(String(review.score == null ? "—" : review.score)) + '</span></div></div><div class="stack">' + bars + (issues ? '<ul>' + issues + '</ul>' : '') + '</div></div>';
  }

  function renderDramaSuggestion(suggestion, idx) {
    return '<div class="advisor-item">' +
      '<span class="type">' + escapeHtml(suggestion.station || "") + '</span>' +
      '<div class="section">' + escapeHtml(suggestion.field || (suggestion.shot_no ? "shot " + suggestion.shot_no : "")) + '</div>' +
      '<div class="guidance">' + escapeHtml(suggestion.reason || "") + '</div>' +
      '<pre>' + escapeHtml(suggestion.new_value || "") + '</pre>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-drama-apply-suggestion="' + idx + '">应用建议</button>' +
      '</div>';
  }

  function bindDramaSuggestionActions(root) {
    root.querySelectorAll("[data-drama-apply-suggestion]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const data = await fetchJson(wsUrl("/drama/episode/" + encodeURIComponent(String(CHAPTER_NO || 1))));
        const review = data.review || {};
        const suggestions = review.suggestions || [];
        const idx = Number(btn.getAttribute("data-drama-apply-suggestion"));
        const suggestion = suggestions[idx];
        if (!suggestion) return;
        btn.disabled = true;
        try {
          await postJson(wsUrl("/drama/apply-suggestion"), { episode_no: CHAPTER_NO || 1, suggestion: suggestion });
          showToast("建议已应用，请重新评审并组装", "info");
          await initDramaEpisodeDetail();
        } catch (err) {
          showToast("应用失败：" + errTitle(err), "error");
          btn.disabled = false;
        }
      });
    });
  }

  // ===== page: jobs =======================================================
  function formatJobTimestamp(value) {
    const seconds = Number(value);
    if (!isFinite(seconds) || seconds <= 0) return "—";
    try {
      return new Date(seconds * 1000).toLocaleString("zh-CN", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
        hour12: false,
      });
    } catch (_err) {
      return "—";
    }
  }
  function renderLlmCallSummary(rows) {
    if (!rows.length) return '<p class="muted">llm_calls.jsonl 尚无内容。</p>';
    const body = rows.map(function (call) {
      const prompt = Number(call.prompt_tokens) || 0;
      const response = Number(call.response_tokens) || 0;
      const duration = Number(call.duration_ms);
      return '<tr>' +
        '<td>' + escapeHtml(stepLabel(call.task || call.operation || "")) + '</td>' +
        '<td>' + statusBadge(call.status || "unknown") + '</td>' +
        '<td><code>' + escapeHtml(call.model || "—") + '</code></td>' +
        '<td>' + (isFinite(duration) ? escapeHtml((duration / 1000).toFixed(1) + " 秒") : "—") + '</td>' +
        '<td>' + escapeHtml(String(prompt)) + ' / ' + escapeHtml(String(response)) + '</td>' +
        '<td>' + escapeHtml(String(call.attempt || 1)) + '</td>' +
        '</tr>';
    }).join("");
    return tableScroll('<table class="table table-wide"><thead><tr>' +
      '<th>任务</th><th>状态</th><th>模型</th><th>耗时</th><th>输入 / 输出 tokens</th><th>尝试</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table>');
  }
  async function initJobs() {
    const recentBox = document.getElementById("jobs-recent");
    const logsBox = document.getElementById("jobs-logs");
    if (recentBox) recentBox.innerHTML = skeleton(4);
    if (logsBox) logsBox.innerHTML = skeleton(4);
    try {
      const data = await fetchJson(wsUrl("/jobs/recent?n=20"));
      const items = data.jobs || [];
      if (!items.length) {
        recentBox.innerHTML = emptyState("尚无任务历史", "发起第一个生成任务后会出现在这里。", "");
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
            "<td>" + escapeHtml(stepLabel(job.step)) + "</td>" +
            "<td>" + statusBadge(job.status || "?") + "</td>" +
            '<td><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code> " + copyButton(job.job_id || "") + "</td>" +
            '<td><span class="trace">' + escapeHtml(trace || "—") + "</span>" + (trace ? " " + copyButton(trace) : "") + "</td>" +
            "<td>" + escapeHtml(formatJobTimestamp(job.started_at)) + "</td>" +
            "<td>" + escapeHtml(note ? note.slice(0, 120) : "") + "</td>" +
            "</tr>" +
            '<tr class="job-drawer-row" id="' + rowId + '"><td colspan="7">' + renderJobDrawer(job) + "</td></tr>"
          );
        }).join("");
        recentBox.innerHTML =
          tableScroll('<table class="table table-wide jobs-table"><thead><tr>' +
          "<th></th><th>任务</th><th>状态</th><th>任务编号</th><th>追踪编号</th><th>开始时间</th><th>结果</th>" +
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
      recentBox.innerHTML = renderErrorCard(err);
    }
    try {
      const data = await fetchJson(wsUrl("/logs/tail?n=30"));
      const lines = data.lines || [];
      logsBox.innerHTML = renderLlmCallSummary(lines);
    } catch (err) {
      logsBox.innerHTML = renderErrorCard(err);
    }
  }

  // ---- drama asset governance (iter129) ---------------------------------
  function assetReferenceText(refs) {
    refs = refs || [];
    if (!refs.length) return "尚未被已冻结分镜引用";
    return refs.map(function (ref) {
      const shots = (ref.shot_ids || []).length
        ? " · " + ref.shot_ids.map(escapeHtml).join("、")
        : "";
      return "第 " + Number(ref.season_no) + " 季 / 第 " +
        Number(ref.episode_no) + " 集" + shots;
    }).join("；");
  }

  function renderDramaAssetVersion(item, version, overview) {
    const selected = !!version.selected;
    const disabled = version.status === "disabled";
    const refs = version.references || [];
    const selectAttrs = [
      'data-asset-select',
      'data-kind="' + escapeHtml(item.kind) + '"',
      'data-asset-id="' + escapeHtml(item.asset_id) + '"',
      'data-version-id="' + escapeHtml(version.version_id) + '"',
      'data-selected-id="' + escapeHtml(item.selected_version_id) + '"',
      'data-selection-revision="' + Number(item.selection_revision) + '"',
      'data-season-no="' + Number(overview.season_no) + '"',
    ];
    if (item.scope) selectAttrs.push('data-scope="' + escapeHtml(item.scope) + '"');
    if (item.episode_no) selectAttrs.push('data-episode-no="' + Number(item.episode_no) + '"');
    if (!version.selection_allowed) {
      if (disabled) {
        selectAttrs.push('title="当前季 lifecycle 已停用，不能选择该版本"');
        selectAttrs.push('aria-label="该版本当前季已停用，不能选择"');
      } else {
        selectAttrs.push('title="跨季治理阻断：其他季已停用或治理状态无效"');
        selectAttrs.push('aria-label="该版本当前季可用，但跨季不可选择"');
      }
    }
    const selectButton = selected
      ? '<span class="badge success">当前选中</span>'
      : '<button type="button" class="btn btn-secondary btn-sm" ' +
          selectAttrs.join(" ") +
          (disabled || !version.selection_allowed || !item.impact_complete ? " disabled" : "") +
          '>设为选中</button>';
    const statusButton =
      '<button type="button" class="btn btn-secondary btn-sm" data-asset-status ' +
      'data-kind="' + escapeHtml(item.kind) + '" ' +
      'data-asset-id="' + escapeHtml(item.asset_id) + '" ' +
      'data-version-id="' + escapeHtml(version.version_id) + '" ' +
      'data-current-status="' + escapeHtml(version.status) + '" ' +
      'data-retirement-revision="' + Number(overview.retirement_revision) + '" ' +
      (overview.mutation_allowed || disabled ? "" : "disabled ") + '>' +
      (disabled ? "重新启用" : "停用") + '</button>';
    const statusLabel = disabled
      ? '<span class="badge warning">已停用</span>'
      : (!version.selection_allowed
          ? '<span class="badge warning">当前季可用</span>' +
            '<div class="hint">跨季不可选择：其他季已停用或治理状态无效</div>'
          : '<span class="badge success">可用</span>');
    return (
      '<tr>' +
      '<td><code>' + escapeHtml(version.version_id) + '</code>' +
      (version.derived_from ? '<div class="hint">源自 ' + escapeHtml(version.derived_from) + '</div>' : "") +
      '</td>' +
      '<td>' + statusLabel + '</td>' +
      '<td>' + escapeHtml(assetReferenceText(refs)) + '</td>' +
      '<td><div class="cluster">' + selectButton + statusButton + '</div></td>' +
      '</tr>'
    );
  }

  function renderDramaAssetItem(item, overview) {
    const scopeLabel = item.scope
      ? " · " + ({ series: "剧集级", global: "工作区全局", episode: "单集覆盖" }[item.scope] || item.scope)
      : "";
    const stale = (item.stale_references || []).length
      ? '<p class="hint">切换后需重建的既有冻结引用：' +
          escapeHtml(assetReferenceText(item.stale_references)) + '</p>'
      : '<p class="hint">当前选中版本没有冻结引用。</p>';
    let scopeToggle = "";
    if ((item.scope === "global" || item.scope === "episode") && item.scope_revision != null) {
      const selectedVersion = (item.versions || []).find(function (version) {
        return version.selected;
      });
      const scopeBlocked = !item.impact_complete ||
        (!item.enabled && selectedVersion && !selectedVersion.selection_allowed);
      const scopeTitle = (!item.enabled && selectedVersion && !selectedVersion.selection_allowed)
        ? (selectedVersion.status === "disabled"
            ? 'title="当前季 lifecycle 已停用，不能重新启用该覆盖" ' +
              'aria-label="当前季版本已停用，该覆盖不可重新启用" '
            : 'title="跨季治理阻断：其他季已停用或治理状态无效" ' +
              'aria-label="该覆盖因跨季治理阻断而不可重新启用" ')
        : "";
      scopeToggle =
        '<button type="button" class="btn btn-secondary btn-sm" data-art-scope-toggle ' +
        'data-scope="' + escapeHtml(item.scope) + '" ' +
        'data-enabled="' + String(!!item.enabled) + '" ' +
        'data-scope-revision="' + Number(item.scope_revision) + '" ' +
        'data-season-no="' + Number(overview.season_no) + '" ' +
        (item.episode_no ? 'data-episode-no="' + Number(item.episode_no) + '" ' : "") +
        scopeTitle +
        (scopeBlocked ? "disabled " : "") +
        '>' + (item.enabled ? "清除覆盖" : "重新启用覆盖") + '</button>';
    }
    return (
      '<article class="card">' +
      '<div class="card-body">' +
      '<div class="section-title"><div><h3><code>' + escapeHtml(item.asset_id) +
      '</code>' + escapeHtml(scopeLabel) + '</h3>' + stale + '</div>' + scopeToggle + '</div>' +
      '<div class="table-scroll"><table class="table table-wide"><thead><tr><th>版本</th><th>状态</th>' +
      '<th>已用于</th><th>操作</th></tr></thead><tbody>' +
      (item.versions || []).map(function (version) {
        return renderDramaAssetVersion(item, version, overview);
      }).join("") +
      '</tbody></table></div></div></article>'
    );
  }

  function renderDramaAssetOverview(overview) {
    const sectionLabels = {
      characters: "角色",
      art_direction_series: "美术方向 · Series",
      art_direction_global: "美术方向 · Global",
      art_direction_episode: "美术方向 · Episode",
      scenes: "场景",
      props_and_clues: "道具与线索",
    };
    const blockers = overview.blockers || [];
    const summary =
      '<div class="card"><div class="card-body">' +
      '<div class="cluster"><span class="badge ' + (blockers.length ? "warning" : "success") + '">' +
      (blockers.length ? "引用扫描不完整" : "引用扫描完整") + '</span>' +
      '<span class="muted">已扫描第 ' +
      ((overview.scanned_episode_nos || []).map(Number).join("、") || "—") +
      ' 集</span></div>' +
      (blockers.length
        ? '<ul>' + blockers.map(function (b) {
            return '<li><code>' + escapeHtml(b.source + ":" + b.code) + '</code>' +
              (b.episode_no ? "（第 " + Number(b.episode_no) + " 集）" : "") + '</li>';
          }).join("") + '</ul>'
        : "") +
      '</div></div>';
    const sections = (overview.sections || []).map(function (section) {
      const label = sectionLabels[section.key] || section.key;
      const stateText = {
        fresh: "就绪",
        missing: "尚未建立",
        stale: "已过期",
        blocked_source: "上游未就绪",
        invalid: "无效（已阻断变更）",
      }[section.state] || section.state;
      const body = (section.items || []).length
        ? section.items.map(function (item) {
            return renderDramaAssetItem(item, overview);
          }).join("")
        : '<div class="empty-state"><p>' + escapeHtml(stateText) + '</p>' +
          ((section.reasons || []).length
            ? '<p class="hint"><code>' + escapeHtml(section.reasons.join(", ")) + '</code></p>'
            : "") + '</div>';
      return (
        '<section class="section"><div class="section-title"><h2>' + escapeHtml(label) +
        '</h2><span class="badge ' + (section.state === "fresh" ? "success" : "warning") + '">' +
        escapeHtml(stateText) + '</span></div>' + body + '</section>'
      );
    }).join("");
    return summary + sections;
  }

  function assetMutationOptions() {
    return {
      headers: {
        "Content-Type": "application/json",
        "X-Drama-Asset-Intent": "mutate-v1",
      },
    };
  }

  async function initDramaAssets() {
    const root = document.getElementById("assets-page-root");
    if (!root) return;
    const episodeInput = document.getElementById("asset-episode-no");
    const refresh = document.getElementById("asset-refresh");
    let overview = null;
    function episodeNo() {
      const value = Number(episodeInput && episodeInput.value || 1);
      return Number.isInteger(value) && value >= 1 && value <= 100 ? value : 1;
    }
    async function load() {
      root.setAttribute("aria-busy", "true");
      try {
        overview = await fetchJson(
          wsUrl("/drama/assets?season_no=1&episode_no=" + encodeURIComponent(episodeNo()))
        );
        root.innerHTML = renderDramaAssetOverview(overview);
      } catch (err) {
        root.innerHTML = renderErrorCard(err);
      } finally {
        root.removeAttribute("aria-busy");
      }
    }
    if (refresh) refresh.addEventListener("click", load);
    if (episodeInput) episodeInput.addEventListener("change", load);
    root.addEventListener("click", async function (ev) {
      const select = ev.target.closest("[data-asset-select]");
      const status = ev.target.closest("[data-asset-status]");
      const scope = ev.target.closest("[data-art-scope-toggle]");
      if (!select && !status && !scope) return;
      const button = select || status || scope;
      button.disabled = true;
      try {
        let result;
        if (select) {
          const payload = {
            kind: select.dataset.kind,
            asset_id: select.dataset.assetId,
            version_id: select.dataset.versionId,
            expected_selection_revision: Number(select.dataset.selectionRevision),
            expected_selected_version_id: select.dataset.selectedId,
            season_no: Number(select.dataset.seasonNo),
            view_episode_no: episodeNo(),
          };
          if (select.dataset.scope) payload.scope = select.dataset.scope;
          if (select.dataset.episodeNo) payload.episode_no = Number(select.dataset.episodeNo);
          result = await postJson(
            wsUrl("/drama/assets/select"),
            payload,
            assetMutationOptions()
          );
        } else if (status) {
          const current = status.dataset.currentStatus;
          result = await postJson(
            wsUrl("/drama/assets/status"),
            {
              kind: status.dataset.kind,
              asset_id: status.dataset.assetId,
              version_id: status.dataset.versionId,
              status: current === "disabled" ? "active" : "disabled",
              expected_revision: Number(status.dataset.retirementRevision),
              expected_current_status: current,
              season_no: 1,
              view_episode_no: episodeNo(),
            },
            assetMutationOptions()
          );
        } else {
          const enabled = scope.dataset.enabled === "true";
          const payload = {
            scope: scope.dataset.scope,
            enabled: !enabled,
            expected_scope_revision: Number(scope.dataset.scopeRevision),
            expected_enabled: enabled,
            view_episode_no: episodeNo(),
          };
          if (scope.dataset.scope === "episode") {
            payload.season_no = Number(scope.dataset.seasonNo);
            payload.episode_no = Number(scope.dataset.episodeNo);
          }
          result = await postJson(
            wsUrl("/drama/assets/art-direction-scope"),
            payload,
            assetMutationOptions()
          );
        }
        overview = result.overview;
        root.innerHTML = renderDramaAssetOverview(overview);
        const affected = (result.affected_references || []).length;
        showToast(
          (result.changed ? "资产状态已更新" : "状态未变化") +
          (affected ? "；影响 " + affected + " 个集级引用" : ""),
          "success"
        );
      } catch (err) {
        root.insertAdjacentHTML("afterbegin", renderErrorCard(err));
        if (err && err.status === 409) {
          await load();
        } else {
          button.disabled = false;
        }
      }
    });
    await load();
  }

  // ---- C2 shot image candidate compare/select (iter130) ----------------
  function shotImageBindingText(binding) {
    if (!binding) return "未选择";
    if (binding.kind === "none") return "不使用尾帧";
    if (binding.kind === "previous_tail") {
      return "沿用上一镜尾帧 " + String(binding.candidate_id || "");
    }
    return String(binding.candidate_id || "");
  }

  function shotImageStateText(state) {
    return ({
      needs_shot_image_assets: "尚未建立候选清单",
      fresh: "候选清单有效",
      stale: "候选或来源已过期",
      invalid: "候选清单无效",
      blocked_source: "上游未就绪",
    })[state] || String(state || "未知");
  }

  function renderShotImageCandidate(candidate, shot, mutationAllowed) {
    const badges = [];
    if (candidate.selected_first) badges.push('<span class="badge success">首帧</span>');
    if (candidate.selected_tail) badges.push('<span class="badge success">尾帧</span>');
    if (!candidate.current) badges.push('<span class="badge warning">旧 request 候选</span>');
    const identity = "镜头 " + shot.shot_id + " 候选 " + candidate.candidate_id;
    return (
      '<article class="shot-image-candidate">' +
      '<img src="' + escapeHtml(candidate.preview_url) + '" alt="镜头 ' +
      escapeHtml(shot.shot_id) + ' 的候选 ' + escapeHtml(candidate.candidate_id) + '" loading="lazy">' +
      '<div class="candidate-body"><div class="cluster">' + badges.join("") + '</div>' +
      '<p><code>' + escapeHtml(candidate.candidate_id) + '</code></p>' +
      '<p class="hint">' + Number(candidate.width) + "×" + Number(candidate.height) +
      " · " + Number(candidate.size_bytes) + " bytes</p>" +
      '<div class="cluster">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-shot-image-compare ' +
      'data-shot-id="' + escapeHtml(shot.shot_id) + '" data-candidate-id="' +
      escapeHtml(candidate.candidate_id) + '" aria-pressed="false" aria-label="' +
      escapeHtml("加入对比：" + identity + (candidate.current ? "" : "（旧 request，只读）")) +
      '">加入对比</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-shot-image-select="first" ' +
      'data-shot-id="' + escapeHtml(shot.shot_id) + '" data-candidate-id="' +
      escapeHtml(candidate.candidate_id) + '" aria-label="' +
      escapeHtml((candidate.selected_first ? "当前首帧：" : "设为首帧：") + identity) + '"' +
      (!mutationAllowed || !candidate.current || candidate.selected_first ? " disabled" : "") +
      '>设为首帧</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-shot-image-select="tail" ' +
      'data-shot-id="' + escapeHtml(shot.shot_id) + '" data-candidate-id="' +
      escapeHtml(candidate.candidate_id) + '" aria-label="' +
      escapeHtml((candidate.selected_tail ? "当前尾帧：" : "设为尾帧：") + identity) + '"' +
      (!mutationAllowed || !candidate.current || candidate.selected_tail ? " disabled" : "") +
      '>设为尾帧</button>' +
      '</div></div></article>'
    );
  }

  function renderShotImageOverview(overview) {
    const state = shotImageStateText(overview.state);
    const summary =
      '<div class="card"><div class="card-body"><div class="cluster">' +
      '<span class="badge ' + (overview.state === "fresh" ? "success" : "warning") + '">' +
      escapeHtml(state) + '</span>' +
      (overview.coverage
        ? '<span class="muted">覆盖：' + escapeHtml(overview.coverage.status) + '</span>'
        : "") +
      '</div>' +
      ((overview.reasons || []).length
        ? '<p class="hint"><code>' + escapeHtml(overview.reasons.join(", ")) + '</code></p>'
        : "") +
      (!overview.mutation_allowed && overview.manifest_fingerprint
        ? '<p class="hint">当前来源已变化；候选可预览比较，但需先重建 C1/C2 才能选择。</p>'
        : "") +
      '</div></div>';
    if (!(overview.shots || []).length) {
      return summary + '<div class="empty-state"><p>' + escapeHtml(state) + '</p></div>';
    }
    return summary + overview.shots.map(function (shot) {
      const candidates = (shot.candidates || []).length
        ? '<div class="shot-image-grid">' + shot.candidates.map(function (candidate) {
            return renderShotImageCandidate(candidate, shot, overview.mutation_allowed);
          }).join("") + '</div>'
        : '<div class="empty-state"><p>当前镜头还没有 PNG 候选。</p></div>';
      return (
        '<section class="section"><div class="section-title"><div><h2><code>' +
        escapeHtml(shot.shot_id) + '</code></h2>' +
        '<p class="hint">首帧：' + escapeHtml(shotImageBindingText(shot.first_binding)) +
        ' · 尾帧：' + escapeHtml(shotImageBindingText(shot.tail_binding)) + '</p></div>' +
        '<span class="badge ' + (shot.coverage_state === "covered" ? "success" : "warning") + '">' +
        escapeHtml(shot.coverage_state) + '</span></div>' +
        candidates +
        '<div class="cluster" style="margin-top:12px">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-shot-image-clear-tail ' +
        'data-shot-id="' + escapeHtml(shot.shot_id) + '" aria-label="' +
        escapeHtml("清除镜头 " + shot.shot_id + " 的尾帧选择") + '"' +
        (!overview.mutation_allowed ||
          (shot.tail_binding && shot.tail_binding.kind === "none") ? " disabled" : "") +
        '>清除尾帧</button></div></section>'
      );
    }).join("");
  }

  async function initDramaShotImages() {
    const root = document.getElementById("shot-images-page-root");
    if (!root) return;
    const compareRoot = document.getElementById("shot-image-compare");
    const episodeInput = document.getElementById("shot-image-episode-no");
    const refresh = document.getElementById("shot-image-refresh");
    let overview = null;
    let compared = [];
    function episodeNo() {
      const value = Number(episodeInput && episodeInput.value || 1);
      return Number.isInteger(value) && value >= 1 && value <= 100 ? value : 1;
    }
    function findShot(shotId) {
      return (overview && overview.shots || []).find(function (shot) {
        return shot.shot_id === shotId;
      });
    }
    function findCandidate(shot, candidateId) {
      return (shot && shot.candidates || []).find(function (candidate) {
        return candidate.candidate_id === candidateId;
      });
    }
    function renderCompare() {
      if (!compareRoot) return;
      compareRoot.innerHTML = compared.map(function (entry) {
        return '<figure><img src="' + escapeHtml(entry.preview_url) + '" alt="对比候选 ' +
          escapeHtml(entry.candidate_id) + '"><figcaption><code>' +
          escapeHtml(entry.candidate_id) + '</code></figcaption></figure>';
      }).join("");
    }
    async function load() {
      root.setAttribute("aria-busy", "true");
      compared = [];
      renderCompare();
      try {
        overview = await fetchJson(
          wsUrl("/drama/shot-images?episode_no=" + encodeURIComponent(episodeNo()))
        );
        root.innerHTML = renderShotImageOverview(overview);
      } catch (err) {
        root.innerHTML = renderErrorCard(err);
      } finally {
        root.removeAttribute("aria-busy");
      }
    }
    if (refresh) refresh.addEventListener("click", load);
    if (episodeInput) episodeInput.addEventListener("change", load);
    root.addEventListener("click", async function (ev) {
      const compare = ev.target.closest("[data-shot-image-compare]");
      const select = ev.target.closest("[data-shot-image-select]");
      const clearTail = ev.target.closest("[data-shot-image-clear-tail]");
      if (compare) {
        const shot = findShot(compare.dataset.shotId);
        const candidate = findCandidate(shot, compare.dataset.candidateId);
        if (!candidate) return;
        const key = shot.shot_id + ":" + candidate.candidate_id;
        const index = compared.findIndex(function (item) { return item.key === key; });
        if (index >= 0) {
          compared.splice(index, 1);
          compare.setAttribute("aria-pressed", "false");
          compare.textContent = "加入对比";
        } else {
          if (compared.length >= 2) {
            showToast("一次最多比较两个候选", "warn");
            return;
          }
          compared.push(Object.assign({ key: key }, candidate));
          compare.setAttribute("aria-pressed", "true");
          compare.textContent = "移出对比";
        }
        renderCompare();
        return;
      }
      if (!select && !clearTail) return;
      const button = select || clearTail;
      const shot = findShot(button.dataset.shotId);
      if (!shot || !overview || !overview.manifest_fingerprint) return;
      const frame = clearTail ? "tail" : select.dataset.shotImageSelect;
      const candidateId = clearTail ? null : select.dataset.candidateId;
      button.disabled = true;
      try {
        const result = await postJson(
          wsUrl("/drama/shot-images/select"),
          {
            episode_no: episodeNo(),
            shot_id: shot.shot_id,
            frame: frame,
            candidate_id: candidateId,
            expected_selection_revision: Number(shot.selection_revision),
            expected_current_binding: frame === "first" ? shot.first_binding : shot.tail_binding,
            expected_manifest_fingerprint: overview.manifest_fingerprint,
          },
          {
            headers: {
              "Content-Type": "application/json",
              "X-Drama-Shot-Image-Intent": "mutate-v1",
            },
          }
        );
        overview = result.overview;
        compared = [];
        renderCompare();
        root.innerHTML = renderShotImageOverview(overview);
        showToast(result.changed ? "镜头图片选择已更新" : "选择未变化", "success");
      } catch (err) {
        root.insertAdjacentHTML("afterbegin", renderErrorCard(err));
        if (err && err.status === 409) {
          await load();
        } else {
          button.disabled = false;
        }
      }
    });
    await load();
  }

  // ---- D2-D4 shot video candidates and continuity (iter131) ------------
  function shotVideoStateText(state) {
    return ({
      needs_shot_video_assets: "尚未建立视频候选清单",
      fresh: "视频候选清单有效",
      stale: "候选或来源已过期",
      invalid: "视频候选清单无效",
      blocked_source: "上游视频计划未就绪",
    })[state] || String(state || "未知");
  }

  function shotVideoCoverageText(state) {
    return ({
      ready: "可进入合成",
      incomplete: "选择未完整",
      stale: "选择已过期",
      invalid: "候选产物无效",
      web_unverified: "所选产物超出 Web 重验上限",
      blocked_source: "上游来源阻塞",
      missing: "尚未选择",
      placeholder: "仅占位预览",
      blocked: "来源阻塞",
    })[state] || String(state || "未知");
  }

  function renderShotVideoCandidate(candidate, shot, mutationAllowed) {
    const identity = "镜头 " + shot.shot_id + " 视频候选 " + candidate.candidate_id;
    const badges = [];
    if (candidate.selected) badges.push('<span class="badge success">已选择</span>');
    if (candidate.is_placeholder) badges.push('<span class="badge warning">占位预览</span>');
    if (!candidate.current) badges.push('<span class="badge warning">旧 request</span>');
    if (!candidate.preview_available) badges.push('<span class="badge warning">预览超限</span>');
    const media = candidate.preview_available && candidate.preview_url
      ? '<video controls preload="none" playsinline data-shot-video-preview="' +
        escapeHtml(candidate.preview_url) + '" aria-label="' +
        escapeHtml(identity) + '"></video>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-shot-video-load-preview>' +
        '加载／重试安全预览</button>' +
        '<p class="hint">安全派生预览：静音，最长 30 秒。</p>'
      : '<div class="empty-state"><p>候选已登记，但超过 Web 安全预览上限。</p></div>';
    return (
      '<article class="shot-video-candidate">' +
      media +
      '<div class="candidate-body"><div class="cluster">' + badges.join("") + '</div>' +
      '<p><code>' + escapeHtml(candidate.candidate_id) + '</code></p>' +
      '<p class="hint">' + Number(candidate.width) + "×" + Number(candidate.height) +
      " · " + (Number(candidate.duration_milliseconds) / 1000).toFixed(3) + " 秒 · " +
      Number(candidate.size_bytes) + " bytes" +
      (candidate.has_audio_track ? " · 源候选含音轨" : " · 源候选无音轨") + '</p>' +
      '<div class="cluster">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-shot-video-select ' +
      'data-shot-id="' + escapeHtml(shot.shot_id) + '" data-candidate-id="' +
      escapeHtml(candidate.candidate_id) + '" aria-label="' +
      escapeHtml((candidate.selected ? "当前选择：" : "选择：") + identity +
        (candidate.is_placeholder ? "（仅降级预览）" : "")) + '"' +
      (!mutationAllowed || !candidate.current || candidate.selected ? " disabled" : "") +
      '>选择候选</button>' +
      '</div></div></article>'
    );
  }

  function renderShotVideoOverview(overview) {
    const state = shotVideoStateText(overview.state);
    const continuity = overview.continuity;
    const attempts = overview.attempts || {};
    let summary =
      '<div class="card"><div class="card-body"><div class="cluster">' +
      '<span class="badge ' + (overview.state === "fresh" ? "success" : "warning") + '">' +
      escapeHtml(state) + '</span>' +
      (overview.coverage
        ? '<span class="muted">覆盖：' +
          escapeHtml(shotVideoCoverageText(overview.coverage.status)) + '</span>'
        : "") +
      (continuity
        ? '<span class="badge ' + (continuity.ready_for_compose ? "success" : "warning") +
          '">合成：' + escapeHtml(continuity.status) + '</span>'
        : "") +
      '</div>' +
      '<p class="hint">Attempt：' + escapeHtml(attempts.state || "needs_attempts") +
      ' · 未发送 ' + Number(attempts.not_sent_count || 0) +
      ' · 未知 ' + Number(attempts.unknown_count || 0) +
      ' · 已提交 ' + Number(attempts.submitted_count || 0) +
      ' · 终态 ' + Number(attempts.terminal_count || 0) + '</p>' +
      ((overview.reasons || []).length
        ? '<p class="hint"><code>' + escapeHtml(overview.reasons.join(", ")) + '</code></p>'
        : "") +
      (!overview.mutation_allowed && overview.manifest_fingerprint
        ? '<p class="hint">当前 D1 来源已变化；候选仅可播放，需先 reconcile 才能选择。</p>'
        : "") +
      '</div></div>';
    if (continuity) {
      const warnings = []
        .concat((continuity.broken_lineage_shot_ids || []).map(function (id) {
          return "首尾帧 lineage：" + id;
        }))
        .concat((continuity.character_version_change_shot_ids || []).map(function (id) {
          return "角色版本变化：" + id;
        }))
        .concat((continuity.scene_version_change_shot_ids || []).map(function (id) {
          return "场景版本变化：" + id;
        }))
        .concat((continuity.camera_reversal_shot_ids || []).map(function (id) {
          return "镜头方向反转：" + id;
        }));
      if (warnings.length) {
        summary += '<div class="callout warning"><strong>连续性提示</strong><span>' +
          escapeHtml(warnings.join("；")) + '</span></div>';
      }
    }
    if (!(overview.shots || []).length) {
      return summary + '<div class="empty-state"><p>' + escapeHtml(state) + '</p></div>';
    }
    return summary + overview.shots.map(function (shot) {
      const candidates = (shot.candidates || []).length
        ? '<div class="shot-video-grid">' + shot.candidates.map(function (candidate) {
            return renderShotVideoCandidate(candidate, shot, overview.mutation_allowed);
          }).join("") + '</div>'
        : '<div class="empty-state"><p>当前镜头还没有 MP4 候选。</p></div>';
      const omitted = Number(shot.omitted_candidate_count || 0)
        ? '<p class="hint">为控制浏览器资源，本镜头另有 ' +
          Number(shot.omitted_candidate_count) + ' 个候选未在本页投影。</p>'
        : "";
      const attempt = shot.attempt
        ? shot.attempt.status + " / " + shot.attempt.outcome
        : "无 attempt";
      return (
        '<section class="section"><div class="section-title"><div><h2><code>' +
        escapeHtml(shot.shot_id) + '</code></h2>' +
        '<p class="hint">Attempt：' + escapeHtml(attempt) + '</p></div>' +
        '<span class="badge ' + (shot.coverage_state === "ready" ? "success" : "warning") +
        '">' + escapeHtml(shotVideoCoverageText(shot.coverage_state)) + '</span></div>' +
        candidates + omitted +
        '<div class="cluster" style="margin-top:12px">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-shot-video-clear ' +
        'data-shot-id="' + escapeHtml(shot.shot_id) + '" aria-label="' +
        escapeHtml("清除镜头 " + shot.shot_id + " 的视频选择") + '"' +
        (!overview.mutation_allowed || !shot.selected ? " disabled" : "") +
        '>清除选择</button></div></section>'
      );
    }).join("");
  }

  async function initDramaShotVideos() {
    const root = document.getElementById("shot-videos-page-root");
    if (!root) return;
    const episodeInput = document.getElementById("shot-video-episode-no");
    const refresh = document.getElementById("shot-video-refresh");
    let overview = null;
    function episodeNo() {
      const value = Number(episodeInput && episodeInput.value || 1);
      return Number.isInteger(value) && value >= 1 && value <= 100 ? value : 1;
    }
    function findShot(shotId) {
      return (overview && overview.shots || []).find(function (shot) {
        return shot.shot_id === shotId;
      });
    }
    async function load() {
      root.setAttribute("aria-busy", "true");
      try {
        overview = await fetchJson(
          wsUrl("/drama/shot-videos?episode_no=" + encodeURIComponent(episodeNo()))
        );
        root.innerHTML = renderShotVideoOverview(overview);
      } catch (err) {
        root.innerHTML = renderErrorCard(err);
      } finally {
        root.removeAttribute("aria-busy");
      }
    }
    if (refresh) refresh.addEventListener("click", load);
    if (episodeInput) episodeInput.addEventListener("change", load);
    root.addEventListener("click", async function (ev) {
      const loadPreview = ev.target.closest("[data-shot-video-load-preview]");
      if (loadPreview) {
        const card = loadPreview.closest(".shot-video-candidate");
        const video = card && card.querySelector("[data-shot-video-preview]");
        if (video) {
          video.setAttribute("src", video.dataset.shotVideoPreview);
          video.load();
        }
        return;
      }
      const select = ev.target.closest("[data-shot-video-select]");
      const clear = ev.target.closest("[data-shot-video-clear]");
      if (!select && !clear) return;
      const button = select || clear;
      const shot = findShot(button.dataset.shotId);
      if (!shot || !overview || !overview.manifest_fingerprint) return;
      button.disabled = true;
      try {
        const result = await postJson(
          wsUrl("/drama/shot-videos/select"),
          {
            episode_no: episodeNo(),
            shot_id: shot.shot_id,
            candidate_id: clear ? null : select.dataset.candidateId,
            expected_selection_revision: Number(shot.selection_revision),
            expected_current_selection: shot.selected,
            expected_manifest_fingerprint: overview.manifest_fingerprint,
          },
          {
            headers: {
              "Content-Type": "application/json",
              "X-Drama-Shot-Video-Intent": "mutate-v1",
            },
          }
        );
        overview = result.overview;
        root.innerHTML = renderShotVideoOverview(overview);
        showToast(result.changed ? "镜头视频选择已更新" : "选择未变化", "success");
      } catch (err) {
        root.insertAdjacentHTML("afterbegin", renderErrorCard(err));
        if (err && err.status === 409) {
          await load();
        } else {
          button.disabled = false;
        }
      }
    });
    await load();
  }

  function composeStateLabel(state) {
    return {
      needs_timeline: "等待 E3 时间线",
      ready: "可以合成",
      partial: "交付不完整",
      complete: "QA 通过",
      stale: "时间线已过期",
      invalid: "产物无效",
      busy: "工作区繁忙",
    }[state] || state || "未知";
  }

  function renderComposeOverview(data) {
    const state = data.state || "needs_timeline";
    const good = state === "complete";
    const actionable = data.ready_to_compose === true;
    const warnings = (data.warnings || []).length
      ? '<div class="callout warning"><strong>门禁提示</strong><span><code>' +
        escapeHtml(data.warnings.join(", ")) + '</code></span></div>'
      : "";
    const summary =
      '<div class="card"><div class="card-body">' +
      '<div class="section-title"><div><h2>Episode ' +
      Number(data.episode_no || 1) + '</h2><p class="hint">时间线 <code>' +
      escapeHtml((data.timeline_fingerprint || "尚未落盘").slice(0, 24)) +
      '</code></p></div><span class="badge ' + (good ? "success" : actionable ? "warning" : "") +
      '">' + escapeHtml(composeStateLabel(state)) + '</span></div>' +
      '<div class="kv-list compact">' +
      '<div class="k">时长</div><div class="v">' +
      (data.duration_ms == null ? "—" : (Number(data.duration_ms) / 1000).toFixed(3) + " s") +
      '</div><div class="k">镜头</div><div class="v">' + Number(data.shot_count || 0) +
      '</div><div class="k">字幕</div><div class="v">' + Number(data.subtitle_count || 0) +
      '</div></div></div></div>';
    let action = "";
    if (state === "needs_timeline") {
      action =
        '<div class="empty-state"><h3>尚无可消费的 E3 时间线</h3>' +
        '<p>请先由音频/时间线流程提交经过服务端验证的 TimelineManifest。此页不接受手工 JSON 上传。</p></div>';
    } else if (state === "stale") {
      action =
        '<div class="empty-state"><h3>上游事实已变化</h3>' +
        '<p>重新完成 D4/E3 后再合成；历史交付不会冒充当前结果。</p></div>';
    } else if (state === "busy") {
      action = '<div class="alert info">另一个写任务正在占用工作区，请稍后刷新。</div>';
    } else if (actionable) {
      action =
        '<div class="form-actions"><button type="button" class="btn btn-primary" id="compose-start">' +
        (state === "ready" ? "开始本地合成" : "重新生成完整交付") +
        '</button><span class="hint">FFmpeg 最长 180 秒；取消会在当前不可中断子进程结束后生效。</span></div>';
    }
    const qa = data.qa
      ? '<div class="card"><div class="card-body"><h3>QA 证据</h3>' +
        '<div class="kv-list compact"><div class="k">等级</div><div class="v">' +
        escapeHtml(data.qa.acceptance_level || "") +
        '</div><div class="k">规格</div><div class="v">' +
        escapeHtml(data.qa.profile || "") +
        '</div><div class="k">覆盖</div><div class="v">' +
        Number(data.qa.covered_shot_count || 0) + " / " +
        Number(data.qa.required_shot_count || 0) +
        '</div><div class="k">MP4 SHA-256</div><div class="v"><code>' +
        escapeHtml(data.qa.output_sha256 || "") +
        '</code></div></div></div></div>'
      : "";
    const downloads = (data.deliverables || []).length
      ? '<div class="card"><div class="card-body"><h3>Exact 交付</h3><div class="cluster">' +
        data.deliverables.map(function (item) {
          return '<a class="btn btn-secondary" href="' + escapeHtml(item.url || "") +
            '" download="' + escapeHtml(item.filename || "") + '">' +
            escapeHtml(String(item.kind || "").toUpperCase()) + '</a>';
        }).join("") + '</div></div></div>'
      : "";
    const job = data.job;
    const jobNote = job && ["blocked", "failed", "aborted", "lost"].indexOf(job.status) >= 0
      ? '<div class="alert warn">最近一次合成任务：' +
        escapeHtml(job.status) + '。页面状态仍以磁盘上的 exact 产物为准。</div>'
      : "";
    return summary + warnings + action + qa + downloads + jobNote;
  }

  async function initDramaCompose() {
    const root = document.getElementById("compose-page-root");
    if (!root) return;
    const episodeInput = document.getElementById("compose-episode-no");
    const refresh = document.getElementById("compose-refresh");
    let overview = null;
    function episodeNo() {
      const value = Number(episodeInput && episodeInput.value || 1);
      return Number.isInteger(value) && value >= 1 && value <= 100 ? value : 1;
    }
    async function load() {
      root.setAttribute("aria-busy", "true");
      try {
        overview = await fetchJson(
          wsUrl("/drama/compose?episode_no=" + encodeURIComponent(episodeNo()))
        );
        root.innerHTML = renderComposeOverview(overview);
        const job = overview.job;
        if (job && (job.status === "pending" || job.status === "running") && job.job_id) {
          await pollJob(job.job_id, root, null, load);
        }
      } catch (err) {
        root.innerHTML = renderErrorCard(err);
      } finally {
        root.removeAttribute("aria-busy");
      }
    }
    if (refresh) refresh.addEventListener("click", load);
    if (episodeInput) episodeInput.addEventListener("change", load);
    root.addEventListener("click", async function (ev) {
      const start = ev.target.closest("#compose-start");
      if (!start) return;
      start.disabled = true;
      try {
        const data = await postJson(
          wsUrl("/drama/compose"),
          { episode_no: episodeNo() },
          {
            headers: {
              "Content-Type": "application/json",
              "X-Drama-Compose-Intent": "run-local-v1",
            },
          }
        );
        await pollJob(data.job_id, root, start, load);
      } catch (err) {
        root.insertAdjacentHTML("afterbegin", renderErrorCard(err));
        start.disabled = false;
      }
    });
    await load();
  }

  // ---- dispatch ---------------------------------------------------------
  function boot() {
    initShellControls();
    // iter062: error cards render on every page now, so their CTA buttons
    // (data-cta-action) must be live everywhere — bind once globally, not only
    // on /continue. Idempotent (ctaActionsBound guard), document-delegated.
    bindCtaActions();
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
    if (pageKind === "workbench") return initWorkbench();
    if (pageKind === "chapters") return initChapters();
    if (pageKind === "search") return initSearch();
    if (pageKind === "chapter_detail") return initChapterDetail();
    if (pageKind === "reviews") return initReviews();
    if (pageKind === "plan") return initPlan();
    if (pageKind === "insights") return initInsights();
    if (pageKind === "drama_write") return initDramaWrite();
    if (pageKind === "drama_characters") return initDramaCharacters();
    if (pageKind === "drama_assets") return initDramaAssets();
    if (pageKind === "drama_shot_images") return initDramaShotImages();
    if (pageKind === "drama_shot_videos") return initDramaShotVideos();
    if (pageKind === "drama_compose") return initDramaCompose();
    if (pageKind === "drama_episodes") return initDramaEpisodes();
    if (pageKind === "drama_episode_detail") return initDramaEpisodeDetail();
    if (pageKind === "drama_insights") return initDramaInsights();
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
  const panelPremise = document.getElementById("panel-premise");
  const panelProgress = document.getElementById("panel-progress");
  const typeForm = document.getElementById("type-form");
  const novelForm = document.getElementById("wizard-form");
  const dramaForm = document.getElementById("drama-form");
  const premiseForm = document.getElementById("premise-form");
  const errBox = document.getElementById("upload-error");
  const dramaErrBox = document.getElementById("drama-error");
  const premiseErrBox = document.getElementById("premise-error");
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

  // iter062: self-contained friendly error card for the wizard bundle (the
  // dashboard bundle has its own richer renderErrorCard; this one renders the
  // same .error-card CSS but without the CTA/copy wiring the wizard lacks).
  var FRONT_ERROR_CATALOG = {
    network: { title: "连不上本地服务", cause: "本地服务可能没在运行，或端口被占用。请确认服务已启动后重试。" },
    timeout: { title: "请求超时", cause: "服务端响应太慢，任务可能仍在后台长跑。" },
    bad_json: { title: "返回数据异常", cause: "服务端返回的内容不是预期格式，刷新后通常即可恢复。" },
  };
  function renderErrorCard(p) {
    var card = (p && p.payload && p.payload.card) || (p && p.card) ||
      (p && p.code && FRONT_ERROR_CATALOG[p.code]) || null;
    if (!card) {
      var msg = (p && p.payload && p.payload.error) || (p && p.error) || (p && p.message) ||
        (typeof p === "string" ? p : "") || "请稍后重试";
      card = { title: "出错了", cause: msg };
    }
    return '<div class="error-card" role="alert">' +
      '<div class="error-card-head"><span class="error-card-icon" aria-hidden="true">⚠</span>' +
      '<div class="error-card-copy"><p class="error-card-title">' + escapeHtml(card.title || "出错了") + '</p>' +
      '<p class="error-card-cause">' + escapeHtml(card.cause || "") + '</p></div></div>' +
      (card.trace_id ? '<p class="error-card-trace">编号 <code>' + escapeHtml(card.trace_id) + '</code></p>' : '') +
      "</div>";
  }

  loadServerMode();

  // Deep-link: /wizard?type=drama (or ?type=novel) jumps straight to that panel.
  (function applyTypeFromQuery() {
    var t = new URLSearchParams(location.search || "").get("type");
    if (!t) return;
    if (t === "drama") {
      if (typeForm) { try { typeForm.elements.ws_type.value = "drama"; } catch (e) {} }
      show(panelDrama);
    } else if (t === "premise") {
      if (typeForm) { try { typeForm.elements.ws_type.value = "premise"; } catch (e) {} }
      show(panelPremise);
    } else if (t === "novel") {
      show(panelUpload);
    }
  })();

  function show(panel) {
    [panelType, panelUpload, panelDrama, panelPremise, panelProgress].forEach((p) => {
      if (p) p.hidden = (p !== panel);
    });
  }

  async function loadServerMode() {
    if (!modeCard) return;
    try {
      const res = await fetch("/api/preflight");
      const data = await res.json().catch(() => ({}));
      const model = String(data.model || "mock");
      const isMock = !!data.is_mock;
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
      else if (t === "premise") show(panelPremise);
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
        if (!res.ok) {
          // JS_WIZARD has no _httpError (that lives in the dashboard bundle);
          // build a carrying error so renderErrorCard reads payload.card.
          const e = new Error(data.error || ("HTTP " + res.status));
          e.status = res.status;
          e.payload = data;
          throw e;
        }
        cancelRequestedJobs.add(jobId);
        const notice = document.getElementById("cancel-notice");
        if (notice) notice.innerHTML = '<div class="alert info">取消请求已发送，等待 worker 响应。</div>';
      } catch (err) {
        if (!err.status && !err.code) err.code = "network";
        const notice = document.getElementById("cancel-notice");
        if (notice) notice.innerHTML = renderErrorCard(err);
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
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          errBox.innerHTML = renderErrorCard(data);
          submitBtn.disabled = false;
          return;
        }
        show(panelProgress);
        poll(data.name, data.job_id);
      } catch (err) {
        err.code = err.code || "network";
        errBox.innerHTML = renderErrorCard(err);
        submitBtn.disabled = false;
      }
    });
  }

  if (premiseForm) {
    premiseForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (premiseErrBox) premiseErrBox.innerHTML = "";
      const fd = new FormData(premiseForm);
      const payload = {
        workspace: (fd.get("workspace") || "").trim(),
        premise: (fd.get("premise") || "").trim(),
        // iter 051a: unchecked checkbox is absent from FormData → false
        expand: fd.get("expand") != null,
      };
      const submitBtn = premiseForm.querySelector("button[type=submit]");
      submitBtn.disabled = true;
      try {
        const res = await fetch("/api/wizard/premise-start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (premiseErrBox) premiseErrBox.innerHTML = renderErrorCard(data);
          submitBtn.disabled = false;
          return;
        }
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "已创建：" + data.name + "，进入工作台" },
          "/w/" + encodeURIComponent(data.name) + "/workbench"
        );
      } catch (err) {
        err.code = err.code || "network";
        if (premiseErrBox) premiseErrBox.innerHTML = renderErrorCard(err);
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
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          dramaErrBox.innerHTML = renderErrorCard(data);
          submitBtn.disabled = false;
          return;
        }
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "短剧 workspace 已创建：" + data.name },
          "/w/" + encodeURIComponent(data.name) + "/write?step=setup"
        );
      } catch (err) {
        err.code = err.code || "network";
        dramaErrBox.innerHTML = renderErrorCard(err);
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
        if (!err.status && !err.code) err.code = "network";
        progressBody.innerHTML = renderErrorCard(err);
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
        '<a class="btn btn-ghost" href="/library">继续浏览书架</a>' +
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
        '<a class="btn btn-ghost" href="/library">返回书架</a>';
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
    errBox.innerHTML = '<div class="alert error">读取设置失败，请确认本地服务在运行后刷新重试。</div>';
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
      errBox.innerHTML = '<div class="alert error">保存失败，请确认网络与本地服务后重试。</div>';
    }
  });
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
})();
"""
