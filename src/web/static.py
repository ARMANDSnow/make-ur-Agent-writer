"""iter 032: embedded CSS / JS for the WebUI.

Iter 032 reworks the WebUI's information architecture and visual system
(see ``docs/iterations/iteration_032_webui_ia_visual.md``):

* New literary-warm design tokens (rice-paper background, ink text,
  jade brand colour, amber CTA, serif headings).
* A unified component library defined in CSS variables — every
  template renders against the same .btn / .badge / .card / .tabs /
  .breadcrumb / .sidebar / .skeleton / .kv-list / .empty-state shapes.
* JS is still served as a single ``/static/app.js`` bundle that
  branches on ``window.PAGE_KIND``. We deliberately keep the iter 026 /
  iter 030 identifiers ``loadTabPanel``, ``scheduleReadiness``,
  ``readinessRequestSeq``, ``writeBookJobRunning``, ``readinessTimer``
  and the ``submit.disabled = writeBookJobRunning || data.status === 'blocked'``
  expression so the iter 026 test suite stays green.
"""

from __future__ import annotations


CSS_BODY = """\
/* ========================================================================
 * iter 032 — literary warm design system
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

/* iter 033: confirm modal */
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
  :root { --sidebar-w: 0px; }
  .app { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .page { padding: var(--space-4); }
  .form-grid, .grid.cols-2, .form-grid-2 { grid-template-columns: 1fr; }
  .review-card { grid-template-columns: 1fr; }
}
"""


JS_DASHBOARD = """\
/* iter 032 — single JS bundle, dispatches on window.PAGE_KIND.
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
 * Iter 026 / iter 030 identifiers preserved verbatim so the existing
 * web test suite stays green:
 *   loadTabPanel, scheduleReadiness, readinessRequestSeq,
 *   writeBookJobRunning, readinessTimer, the
 *   ``submit.disabled = writeBookJobRunning || data.status === 'blocked'``
 *   expression.
 */
(function () {
  const ws = window.WORKSPACE_NAME || "";
  const pageKind = window.PAGE_KIND || "";

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
  function wsUrl(suffix) {
    return "/api/workspace/" + encodeURIComponent(ws) + suffix;
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

  function showToast(msg, kind) {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : kind === "warn" ? " warn" : "");
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(function () {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  }

  // ---- shared: chapter detail tab routing (hash deep-link) --------------
  // Keep in sync with chapter-detail and plan-view tab keys.
  const _ALLOWED_TAB_KEYS = [
    "body", "review", "lint", "advisor", "history",
    "chapters", "outline", "decisions",
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
    const initial = (location.hash || "").replace(/^#/, "");
    if (initial && _ALLOWED_TAB_KEYS.indexOf(initial) >= 0) {
      const t = document.querySelector('.tab[data-tab="' + initial + '"]');
      if (t) activate(t);
    }
  }

  // ``loadTabPanel`` identifier preserved (iter 026 test asserts it).
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
    const readiness = w.readiness || {};
    const status = readiness.status || "blocked";
    const blockers = readiness.blockers || [];
    const start = w.start_point && w.start_point.has_start_point
      ? (w.start_point.start_chapter_id || "已设置")
      : "未设置";
    const plan = w.plan && w.plan.exists ? (w.plan.chapters || 0) + " 章" : "缺失";
    const url = "/w/" + encodeURIComponent(w.name) + "/";
    return (
      '<a class="workspace-card" href="' + url + '">' +
      '<div class="card-head">' +
      '<div><p class="eyebrow ornament">作品</p><h3>' + escapeHtml(w.name) + "</h3></div>" +
      statusBadge(status) +
      "</div>" +
      '<div class="metrics">' +
      '<div class="metric"><span class="k">原文章节</span><span class="v">' + (w.chapter_count || 0) + "</span></div>" +
      '<div class="metric"><span class="k">续写草稿</span><span class="v">' + (w.draft_count || 0) + "</span></div>" +
      '<div class="metric"><span class="k">评审通过</span><span class="v">' +
      (w.review_accepted || 0) + "/" + (w.review_total || 0) +
      "</span></div>" +
      '<div class="metric"><span class="k">起点</span><span class="v" style="font-size:14px">' + escapeHtml(start) + "</span></div>" +
      '<div class="metric"><span class="k">计划</span><span class="v" style="font-size:14px">' + escapeHtml(plan) + "</span></div>" +
      '<div class="metric"><span class="k">最近任务</span><span class="v" style="font-size:14px">' +
      escapeHtml(w.recent_job ? (w.recent_job.step || "?") + " · " + (w.recent_job.status || "?") : "无") +
      "</span></div>" +
      "</div>" +
      (blockers.length ? '<p class="alert error" style="margin-top:12px">' + escapeHtml(blockers[0]) + "</p>" : "") +
      "</a>"
    );
  }

  // ===== page: workspace overview =========================================
  async function initWorkspaceOverview() {
    const summary = document.getElementById("overview-summary");
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
        sessionStorage.setItem("__pending_toast",
          JSON.stringify({ kind: "info", msg: "已删除 《" + name + "》 → " + data.trashed_to }));
        window.location.href = "/";
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
    const draftSet = new Set((draftChapters || []).map((n) => Number(n)));
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
  function bindWriteBook() {
    const form = document.getElementById("write-book-form");
    if (!form) return;
    const submit = document.getElementById("write-book-submit");
    const jobBox = document.getElementById("write-book-status");
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
    let html = '<div class="kv-list compact">' +
      '<div class="k">status</div><div class="v">' + statusBadge(status) + "</div>" +
      '<div class="k">chapters</div><div class="v">' + escapeHtml(String(data.chapters || "?")) + "</div>" +
      '<div class="k">resume_from</div><div class="v">' + escapeHtml(String(data.resume_from || "?")) + "</div>" +
      '<div class="k">plan_window</div><div class="v">' + escapeHtml(String(data.plan_window || "?")) + "</div>" +
      "</div>";
    if (blockers.length) html += '<div class="alert error">' + blockers.map(escapeHtml).join("<br>") + "</div>";
    if (warnings.length) html += '<div class="alert warn">' + warnings.map(escapeHtml).join("<br>") + "</div>";
    if (commands.length) {
      html += '<div class="command-list">' +
        commands.map((c) => "<code>" + escapeHtml(c) + "</code>").join("") + "</div>";
    }
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
      box.innerHTML = items.map((job) => (
        '<div class="kv-list compact" style="margin-bottom:8px">' +
        '<div class="k">step</div><div class="v">' + escapeHtml(job.step || "?") + "</div>" +
        '<div class="k">status</div><div class="v">' + statusBadge(job.status || "?") + "</div>" +
        '<div class="k">job</div><div class="v"><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code></div>" +
        "</div>"
      )).join("");
    } catch (err) {
      box.innerHTML = '<div class="alert error">' + escapeHtml(err.message) + "</div>";
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
      box.innerHTML =
        '<div class="kv-list compact">' +
        '<div class="k">job</div><div class="v"><code>' + escapeHtml(jobId) + "</code></div>" +
        '<div class="k">status</div><div class="v">' + statusBadge(job.status || "?") + "</div>" +
        '<div class="k">step</div><div class="v">' + escapeHtml(job.current_step || "?") + "</div>" +
        '<div class="k">progress</div><div class="v">' + pct + "%</div>" +
        "</div>" +
        '<div class="progress"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        (job.error ? '<div class="alert error" style="margin-top:8px">' + escapeHtml(job.error) +
          (job.trace_id ? ' <code>trace=' + escapeHtml(job.trace_id) + '</code>' : '') + "</div>" : "");
      const terminal = ["succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"];
      if (terminal.indexOf(job.status) >= 0) {
        if (submit) submit.disabled = false;
        const stepLabel = job.step || job.current_step || "task";
        if (job.status === "succeeded") {
          showToast(stepLabel + " 已完成", "info");
        } else {
          const reason = (job.error || "").split("\\n")[0].slice(0, 80);
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
      '<table class="table" id="chapters-data-table"><thead><tr>' +
      "<th>#</th><th>类型</th><th>章节 ID</th><th>标题</th>" +
      "<th>verdict</th><th>review</th><th>rewrite</th><th>字数</th><th></th>" +
      "</tr></thead><tbody>"
    );
    for (const d of drafts) {
      const r = reviewByCh.get(d.chapter) || {};
      const id = "chapter_" + String(d.chapter).padStart(2, "0");
      const title = r.title || "";
      const detailHref = "/w/" + encodeURIComponent(ws) + "/chapter/" + d.chapter;
      rows.push(
        '<tr class="chapter-row" data-title="' + escapeHtml(title) + '" data-id="' + escapeHtml(id) +
        '" data-status="' + escapeHtml(d.verdict || "") + '">' +
        "<td>" + d.chapter + "</td>" +
        "<td>续写</td>" +
        "<td><code>" + escapeHtml(id) + "</code></td>" +
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
    box.innerHTML = rows.join("");
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
        '<p class="muted" style="margin-top:12px">多版本草稿对比（diff）留待 iter 033。</p>';
    }
  }
  function renderAgentReview(a) {
    const sub = a.sub_scores || {};
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
        '<table class="table"><thead><tr>' +
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
      box.innerHTML = statsHtml + head + rows + "</tbody></table>";
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
      if (v == null) return '<td style="text-align:center;color:var(--ink-3)">—</td>';
      let bg = "var(--bg-card)";
      if (v >= 7) bg = "var(--jade-soft)";
      else if (v >= 5) bg = "var(--gold-soft)";
      else bg = "var(--sienna-soft)";
      return '<td style="text-align:center;background:' + bg + ';font-family:var(--font-mono)">' +
        v.toFixed(2) + '</td>';
    };
    const head = '<tr><th>章</th><th>plot</th><th>prose</th><th>fidelity</th><th>total</th><th>agents</th></tr>';
    const body = rows.map((r) =>
      '<tr><td>ch ' + r.chapter + '</td>' +
      cell(r.plot) + cell(r.prose) + cell(r.fidelity) + cell(r.total) +
      '<td style="text-align:center" class="muted">' + r.agents + '</td></tr>'
    ).join("");
    box.innerHTML = '<table class="table">' + head + body + '</table>';
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
        const rows = items.map((job) => {
          const trace = job.trace_id || "";
          return (
            '<tr class="job-row">' +
            "<td>" + escapeHtml(job.step || "?") + "</td>" +
            "<td>" + statusBadge(job.status || "?") + "</td>" +
            '<td><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code> " + copyButton(job.job_id || "") + "</td>" +
            '<td><span class="trace">' + escapeHtml(trace || "—") + "</span>" + (trace ? " " + copyButton(trace) : "") + "</td>" +
            "<td>" + escapeHtml(job.started_at ? String(job.started_at) : "—") + "</td>" +
            "<td>" + escapeHtml(job.error ? job.error.slice(0, 80) : "") + "</td>" +
            "</tr>"
          );
        }).join("");
        recentBox.innerHTML =
          '<table class="table"><thead><tr>' +
          "<th>step</th><th>status</th><th>job_id</th><th>trace_id</th><th>started</th><th>note</th>" +
          "</tr></thead><tbody>" + rows + "</tbody></table>";
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
    if (pageKind === "jobs") return initJobs();
  }
  document.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();
})();
"""


JS_WIZARD = """\
(function () {
  const form = document.getElementById("wizard-form");
  const errBox = document.getElementById("upload-error");
  const progressPanel = document.getElementById("panel-progress");
  const progressBody = document.getElementById("progress-body");
  if (!form) return;

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errBox.textContent = "";
    const fd = new FormData(form);
    const submitBtn = form.querySelector("button[type=submit]");
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
      progressPanel.hidden = false;
      poll(data.name, data.job_id);
    } catch (err) {
      errBox.innerHTML = '<div class="alert error">网络错误: ' + escapeHtml(String(err)) + "</div>";
      submitBtn.disabled = false;
    }
  });

  async function poll(name, jobId) {
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
